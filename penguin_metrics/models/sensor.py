"""
Home Assistant sensor model for MQTT Discovery.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .device import Device


class SensorState(Enum):
    """Sensor availability state."""
    ONLINE = "online"
    OFFLINE = "offline"
    UNKNOWN = "unknown"


class DeviceClass(Enum):
    """Home Assistant sensor device classes."""
    # Common
    NONE = None
    
    # Measurements
    TEMPERATURE = "temperature"
    HUMIDITY = "humidity"
    PRESSURE = "pressure"
    POWER = "power"
    ENERGY = "energy"
    CURRENT = "current"
    VOLTAGE = "voltage"
    FREQUENCY = "frequency"
    
    # Data
    DATA_SIZE = "data_size"
    DATA_RATE = "data_rate"
    
    # Battery
    BATTERY = "battery"
    
    # Time
    DURATION = "duration"
    TIMESTAMP = "timestamp"
    
    # Other
    MONETARY = "monetary"
    SIGNAL_STRENGTH = "signal_strength"


class StateClass(Enum):
    """Home Assistant sensor state classes."""
    MEASUREMENT = "measurement"
    TOTAL = "total"
    TOTAL_INCREASING = "total_increasing"


@dataclass
class Sensor:
    """
    Represents a Home Assistant sensor for MQTT Discovery.
    
    Each sensor publishes its value to a state topic and can be
    configured with various Home Assistant attributes.
    """
    
    # Required
    unique_id: str
    name: str
    
    # Topics
    state_topic: str = ""
    availability_topic: str | None = None
    
    # Device association
    device: Device | None = None
    
    # Value configuration
    value_template: str | None = None
    unit_of_measurement: str | None = None
    
    # Home Assistant configuration
    device_class: DeviceClass | str | None = None
    state_class: StateClass | str | None = None
    icon: str | None = None
    
    # Entity configuration
    enabled_by_default: bool = True
    entity_category: str | None = None  # "config", "diagnostic"
    
    # Availability
    payload_available: str = "online"
    payload_not_available: str = "offline"
    
    # JSON attributes
    json_attributes_topic: str | None = None
    json_attributes_template: str | None = None
    
    # Current state (not part of discovery)
    _state: Any = field(default=None, repr=False, compare=False)
    _availability: SensorState = field(default=SensorState.UNKNOWN, repr=False, compare=False)
    
    def __post_init__(self):
        """Initialize topics if not set."""
        if not self.state_topic:
            self.state_topic = f"penguin_metrics/sensor/{self.unique_id}/state"
        
        if self.availability_topic is None and self.device:
            # Use device-level availability by default
            pass
    
    @property
    def state(self) -> Any:
        """Get current sensor state/value."""
        return self._state
    
    @state.setter
    def state(self, value: Any):
        """Set sensor state/value."""
        self._state = value
        if value is not None:
            self._availability = SensorState.ONLINE
    
    @property
    def availability(self) -> SensorState:
        """Get sensor availability."""
        return self._availability
    
    @availability.setter
    def availability(self, value: SensorState):
        """Set sensor availability."""
        self._availability = value
    
    def set_unavailable(self):
        """Mark sensor as unavailable."""
        self._availability = SensorState.OFFLINE
        self._state = None
    
    def to_discovery_dict(self, topic_prefix: str = "homeassistant") -> dict[str, Any]:
        """
        Convert to dictionary for Home Assistant MQTT Discovery.
        
        Args:
            topic_prefix: HA discovery topic prefix
        
        Returns:
            Dictionary for discovery payload
        """
        result: dict[str, Any] = {
            "unique_id": self.unique_id,
            "name": self.name,
            "state_topic": self.state_topic,
        }
        
        if self.device:
            result["device"] = self.device.to_discovery_dict()
        
        if self.availability_topic:
            # Check if we have an availability template (for JSON-based availability)
            avail_tpl = getattr(self, "_availability_template", None)
            if avail_tpl:
                # Use availability list format for JSON template
                result["availability"] = [{
                    "topic": self.availability_topic,
                    "value_template": avail_tpl,
                    "payload_available": "online",
                    "payload_not_available": "not_found",
                }]
            else:
                # Simple availability (for system which uses global status)
                result["availability_topic"] = self.availability_topic
                result["payload_available"] = self.payload_available
                result["payload_not_available"] = self.payload_not_available
        
        if self.value_template:
            result["value_template"] = self.value_template
        
        if self.unit_of_measurement:
            result["unit_of_measurement"] = self.unit_of_measurement
        
        # Device class
        if self.device_class:
            if isinstance(self.device_class, DeviceClass):
                if self.device_class.value:
                    result["device_class"] = self.device_class.value
            else:
                result["device_class"] = self.device_class
        
        # State class
        if self.state_class:
            if isinstance(self.state_class, StateClass):
                result["state_class"] = self.state_class.value
            else:
                result["state_class"] = self.state_class
        
        if self.icon:
            result["icon"] = self.icon
        
        if not self.enabled_by_default:
            result["enabled_by_default"] = False
        
        if self.entity_category:
            result["entity_category"] = self.entity_category
        
        if self.json_attributes_topic:
            result["json_attributes_topic"] = self.json_attributes_topic
        
        if self.json_attributes_template:
            result["json_attributes_template"] = self.json_attributes_template
        
        return result
    
    def get_discovery_topic(self, prefix: str = "homeassistant") -> str:
        """
        Get the MQTT topic for discovery message.
        
        Args:
            prefix: HA discovery prefix
        
        Returns:
            Discovery topic string
        """
        return f"{prefix}/sensor/{self.unique_id}/config"
    
    def format_state(self) -> str:
        """
        Format state value for MQTT publishing.
        
        Returns:
            Formatted state string
        """
        if self._state is None:
            return ""
        
        if isinstance(self._state, bool):
            return "on" if self._state else "off"
        
        if isinstance(self._state, float):
            # Limit decimal places for cleaner output
            return f"{self._state:.2f}"
        
        return str(self._state)


def create_sensor(
    source_type: str,
    source_name: str,
    metric_name: str,
    display_name: str,
    device: Device | None = None,
    topic_prefix: str = "penguin_metrics",
    unit: str | None = None,
    device_class: DeviceClass | str | None = None,
    state_class: StateClass | str | None = None,
    icon: str | None = None,
    availability_topic: str | None = None,
    use_json: bool = True,
    **kwargs,
) -> Sensor:
    """
    Factory function to create a sensor for a metric.
    
    All sources now publish JSON to a single topic per source.
    Sensors use value_template to extract their specific value.
    
    Args:
        source_type: Type of source (system, temperature, process, docker, service, battery, custom, gpu)
        source_name: Name of the source (nginx, homeassistant, etc.)
        metric_name: Name of the metric (cpu_percent, memory, temp, etc.)
        display_name: Human-readable name for HA
        device: Associated device
        topic_prefix: Base topic prefix
        unit: Unit of measurement
        device_class: HA device class
        state_class: HA state class
        icon: MDI icon name
        availability_topic: Override availability topic
        use_json: If True, use value_template to extract from JSON (default)
        **kwargs: Additional sensor attributes
    
    Returns:
        Configured Sensor instance
    
    Topic structure (JSON per source):
        {prefix}/system                    - system metrics (no state field)
        {prefix}/{type}/{name}             - all other sources
    
    Examples:
        penguin_metrics/system             -> {"cpu_percent": 75, "memory_percent": 45}
        penguin_metrics/temperature/soc    -> {"temp": 42.0, "state": "online"}
        penguin_metrics/docker/nginx       -> {"cpu_percent": 5.0, "state": "running"}
    """
    # Build unique_id
    if source_name:
        unique_id = f"{source_type}_{source_name}_{metric_name}"
    else:
        unique_id = f"{source_type}_{metric_name}"
    
    # Build state_topic (JSON topic for the source)
    if source_name:
        state_topic = f"{topic_prefix}/{source_type}/{source_name}"
    else:
        state_topic = f"{topic_prefix}/{source_type}"
    
    # Build value_template to extract metric from JSON
    value_template = f"{{{{ value_json.{metric_name} }}}}" if use_json else None
    
    # Availability handling
    # For system: use global status topic
    # For others: use state field in JSON
    if source_type == "system":
        avail_topic = f"{topic_prefix}/status"
        avail_tpl = None
    else:
        # Availability is in the same JSON topic
        avail_topic = state_topic
        avail_tpl = "{{ value_json.state }}"
    
    if availability_topic:
        avail_topic = availability_topic
    
    sensor = Sensor(
        unique_id=unique_id,
        name=display_name,
        state_topic=state_topic,
        availability_topic=avail_topic,
        device=device,
        value_template=value_template,
        unit_of_measurement=unit,
        device_class=device_class,
        state_class=state_class,
        icon=icon,
        **kwargs,
    )
    
    # Store availability template for discovery payload
    if avail_tpl:
        sensor._availability_template = avail_tpl
    
    return sensor

