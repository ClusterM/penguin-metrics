"""
Home Assistant MQTT Discovery integration.

Handles:
- Discovery message generation
- Entity registration
- Device grouping
- Availability handling
- Cleanup of stale sensors
"""

import json
import logging
from pathlib import Path
from typing import Any

from ..config.schema import HomeAssistantConfig
from ..const import APP_NAME, APP_URL, APP_VERSION
from ..models.sensor import Sensor
from .client import MQTTClient

logger = logging.getLogger(__name__)

# Default state file location
DEFAULT_STATE_FILE = "/var/lib/penguin-metrics/registered_sensors.json"


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
        state_file: str | None = None,
    ):
        """
        Initialize Home Assistant Discovery.

        Args:
            mqtt_client: MQTT client for publishing
            config: Home Assistant configuration
            state_file: Path to state file for tracking registered sensors
        """
        self.mqtt = mqtt_client
        self.config = config
        self.state_file = Path(state_file) if state_file else Path(DEFAULT_STATE_FILE)

        # Track registered entities (current session)
        self._registered_sensors: set[str] = set()
        self._registered_devices: set[str] = set()

        # Previously registered sensors (from state file)
        self._previous_sensors: set[str] = set()

    def _load_state(self) -> set[str]:
        """Load previously registered sensors from state file."""
        # Try primary location
        try:
            if self.state_file.exists():
                data = json.loads(self.state_file.read_text())
                return set(data.get("sensors", []))
        except Exception as e:
            logger.debug(f"Could not load primary state file: {e}")

        # Try fallback location
        fallback = Path.home() / ".penguin-metrics" / "registered_sensors.json"
        try:
            if fallback.exists():
                data = json.loads(fallback.read_text())
                self.state_file = fallback  # Use fallback for future operations
                return set(data.get("sensors", []))
        except Exception as e:
            logger.debug(f"Could not load fallback state file: {e}")

        return set()

    def _save_state(self) -> None:
        """Save registered sensors to state file."""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            data = {"sensors": list(self._registered_sensors)}
            self.state_file.write_text(json.dumps(data, indent=2))
            logger.debug(f"Saved {len(self._registered_sensors)} sensors to state file")
        except PermissionError:
            # Try fallback to user's home directory
            fallback = Path.home() / ".penguin-metrics" / "registered_sensors.json"
            try:
                fallback.parent.mkdir(parents=True, exist_ok=True)
                data = {"sensors": list(self._registered_sensors)}
                fallback.write_text(json.dumps(data, indent=2))
                logger.debug(f"Saved state to fallback: {fallback}")
                self.state_file = fallback  # Use fallback for future operations
            except Exception as e:
                logger.warning(f"Failed to save state file (fallback): {e}")
        except Exception as e:
            logger.warning(f"Failed to save state file: {e}")

    async def cleanup_stale_sensors(self) -> int:
        """
        Remove sensors that were previously registered but no longer exist.

        Returns:
            Number of sensors removed
        """
        self._previous_sensors = self._load_state()

        if not self._previous_sensors:
            logger.debug("No previous sensors found in state file")
            return 0

        logger.debug(
            f"Previous session had {len(self._previous_sensors)} sensors, "
            f"current session has {len(self._registered_sensors)} sensors"
        )

        # Find sensors that were registered before but not now
        stale = self._previous_sensors - self._registered_sensors

        if not stale:
            logger.debug("No stale sensors to clean up")
            return 0

        logger.info(f"Cleaning up {len(stale)} stale sensors from Home Assistant")

        for sensor_id in stale:
            # Publish empty payload to remove sensor from HA
            # Try both sensor and binary_sensor (we don't know which it was)
            for entity_type in ("sensor", "binary_sensor"):
                await self._clear_discovery(sensor_id, entity_type)
            logger.info(f"Removed stale sensor: {sensor_id}")

        return len(stale)

    async def finalize_registration(self) -> None:
        """
        Finalize sensor registration - cleanup stale and save state.

        Call this after all sensors have been registered.
        """
        removed = await self.cleanup_stale_sensors()
        if removed:
            logger.info(f"Removed {removed} stale sensors from previous session")

        self._save_state()

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
        return f"{self.discovery_prefix}/{sensor.entity_type}/{sensor.unique_id}/config"

    async def _clear_discovery(self, sensor_id: str, entity_type: str = "sensor") -> None:
        """Publish empty payload to remove discovery for given sensor/entity type."""
        topic = f"{self.discovery_prefix}/{entity_type}/{sensor_id}/config"
        await self.mqtt.publish(topic, "", qos=1, retain=True)

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
            "name": APP_NAME,
            "sw_version": APP_VERSION,
            "support_url": APP_URL,
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

        await self._clear_discovery(sensor.unique_id, sensor.entity_type)
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
            await self._clear_discovery(sensor_id, "sensor")

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
    topic = f"{discovery_prefix}/{sensor.entity_type}/{sensor.unique_id}/config"

    payload = sensor.to_discovery_dict(discovery_prefix)
    payload["origin"] = {
        "name": APP_NAME,
        "sw_version": APP_VERSION,
        "support_url": APP_URL,
    }

    return topic, payload
