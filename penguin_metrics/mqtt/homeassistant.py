"""
Home Assistant MQTT Discovery integration.

Handles:
- Discovery message generation
- Entity registration
- Device grouping
- Availability handling
"""

import json
import logging
from typing import Any

from .client import MQTTClient
from ..models.sensor import Sensor
from ..models.device import Device
from ..config.schema import HomeAssistantConfig


logger = logging.getLogger(__name__)


class HomeAssistantDiscovery:
    """
    Home Assistant MQTT Discovery handler.
    
    Publishes discovery messages to register sensors and devices
    with Home Assistant automatically.
    """
    
    def __init__(
        self,
        mqtt_client: MQTTClient,
        config: HomeAssistantConfig,
    ):
        """
        Initialize Home Assistant Discovery.
        
        Args:
            mqtt_client: MQTT client for publishing
            config: Home Assistant configuration
        """
        self.mqtt = mqtt_client
        self.config = config
        
        # Track registered entities
        self._registered_sensors: set[str] = set()
        self._registered_devices: set[str] = set()
    
    @property
    def discovery_prefix(self) -> str:
        """Get discovery topic prefix."""
        return self.config.discovery_prefix
    
    def _get_discovery_topic(self, sensor: Sensor) -> str:
        """
        Get the discovery topic for a sensor.
        
        Args:
            sensor: Sensor to get topic for
        
        Returns:
            Discovery topic string
        """
        return f"{self.discovery_prefix}/sensor/{sensor.unique_id}/config"
    
    def _build_discovery_payload(self, sensor: Sensor) -> dict[str, Any]:
        """
        Build discovery payload for a sensor.
        
        Args:
            sensor: Sensor to build payload for
        
        Returns:
            Discovery payload dictionary
        """
        payload = sensor.to_discovery_dict(self.discovery_prefix)
        
        # Add origin info
        payload["origin"] = {
            "name": "Penguin Metrics",
            "sw_version": "0.1.0",
            "support_url": "https://github.com/clusterm/penguin-metrics",
        }
        
        return payload
    
    async def register_sensor(self, sensor: Sensor) -> None:
        """
        Register a sensor with Home Assistant.
        
        Args:
            sensor: Sensor to register
        """
        if not self.config.discovery:
            return
        
        topic = self._get_discovery_topic(sensor)
        payload = self._build_discovery_payload(sensor)
        
        await self.mqtt.publish_json(topic, payload, qos=1, retain=True)
        self._registered_sensors.add(sensor.unique_id)
        
        logger.debug(f"Registered sensor: {sensor.unique_id}")
    
    async def unregister_sensor(self, sensor: Sensor) -> None:
        """
        Unregister a sensor from Home Assistant.
        
        Sends empty payload to remove the entity.
        
        Args:
            sensor: Sensor to unregister
        """
        if not self.config.discovery:
            return
        
        topic = self._get_discovery_topic(sensor)
        
        # Empty payload removes the entity
        await self.mqtt.publish(topic, "", qos=1, retain=True)
        self._registered_sensors.discard(sensor.unique_id)
        
        logger.debug(f"Unregistered sensor: {sensor.unique_id}")
    
    async def register_sensors(self, sensors: list[Sensor]) -> None:
        """
        Register multiple sensors.
        
        Args:
            sensors: List of sensors to register
        """
        for sensor in sensors:
            await self.register_sensor(sensor)
    
    async def publish_sensor_state(self, sensor: Sensor) -> None:
        """
        Publish current sensor state to MQTT.
        
        Args:
            sensor: Sensor to publish state for
        """
        if sensor.state is None:
            return
        
        state_value = sensor.format_state()
        await self.mqtt.publish(sensor.state_topic, state_value)
    
    async def publish_sensor_states(self, sensors: list[Sensor]) -> None:
        """
        Publish states for multiple sensors.
        
        Args:
            sensors: List of sensors to publish
        """
        for sensor in sensors:
            await self.publish_sensor_state(sensor)
    
    async def publish_state_batch(
        self,
        states: dict[str, Any],
        topic_prefix: str = "penguin_metrics",
    ) -> None:
        """
        Publish multiple sensor states efficiently.
        
        Args:
            states: Dictionary mapping sensor_id to value
            topic_prefix: Base topic prefix
        """
        for sensor_id, value in states.items():
            # Parse sensor_id to get topic
            # Format: source_id_metric_name
            topic = f"{topic_prefix}/{sensor_id.rsplit('_', 1)[0]}/{sensor_id.split('_')[-1]}"
            
            if isinstance(value, float):
                value = round(value, 2)
            
            await self.mqtt.publish(topic, str(value))
    
    async def cleanup(self) -> None:
        """
        Clean up all registered entities.
        
        Sends empty payloads to remove all entities from Home Assistant.
        """
        for sensor_id in list(self._registered_sensors):
            topic = f"{self.discovery_prefix}/sensor/{sensor_id}/config"
            await self.mqtt.publish(topic, "", qos=1, retain=True)
        
        self._registered_sensors.clear()
        self._registered_devices.clear()
        
        logger.info("Cleaned up Home Assistant discovery entities")


def build_sensor_discovery(
    sensor: Sensor,
    discovery_prefix: str = "homeassistant",
) -> tuple[str, dict[str, Any]]:
    """
    Build discovery topic and payload for a sensor.
    
    Args:
        sensor: Sensor to build discovery for
        discovery_prefix: HA discovery prefix
    
    Returns:
        Tuple of (topic, payload)
    """
    topic = f"{discovery_prefix}/sensor/{sensor.unique_id}/config"
    
    payload = sensor.to_discovery_dict(discovery_prefix)
    payload["origin"] = {
        "name": "Penguin Metrics",
        "sw_version": "0.1.0",
    }
    
    return topic, payload

