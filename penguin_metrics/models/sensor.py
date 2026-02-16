"""
Home Assistant sensor model for MQTT Discovery.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .device import Device


def _sanitize_id(value: str) -> str:
    """Sanitize a string for use in topics and identifiers."""
    result = []
    for char in value.lower():
        if char.isalnum():
            result.append(char)
        elif char in " -_.":
            result.append("_")

    sanitized = "".join(result)
    while "__" in sanitized:
        sanitized = sanitized.replace("__", "_")

    return sanitized.strip("_")


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


class BinarySensorDeviceClass(Enum):
    """Home Assistant binary_sensor device classes."""

    BATTERY = "battery"
    BATTERY_CHARGING = "battery_charging"
    CONNECTIVITY = "connectivity"
    PLUG = "plug"
    POWER = "power"
    RUNNING = "running"
    PROBLEM = "problem"
    PRESENCE = "presence"


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
    suggested_display_precision: int | None = None

    # Home Assistant configuration
    device_class: DeviceClass | BinarySensorDeviceClass | str | None = None
    state_class: StateClass | str | None = None
    icon: str | None = None

    # Entity configuration
    entity_type: str = "sensor"  # "sensor" or "binary_sensor"
    enabled_by_default: bool = True
    entity_category: str | None = None  # "config", "diagnostic"

    # Availability
    payload_available: str = "online"
    payload_not_available: str = "offline"

    # Binary sensor state payloads (for entity_type="binary_sensor" when state_topic uses custom payloads)
    payload_on: str | None = None
    payload_off: str | None = None

    # JSON attributes
    json_attributes_topic: str | None = None
    json_attributes_template: str | None = None

    # Current state (not part of discovery)
    _state: Any = field(default=None, repr=False, compare=False)
    _availability: SensorState = field(default=SensorState.UNKNOWN, repr=False, compare=False)
    _ha_extra_fields: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)
    _dual_availability: dict[str, Any] | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
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
    def state(self, value: Any) -> None:
        """Set sensor state/value."""
        self._state = value
        if value is not None:
            self._availability = SensorState.ONLINE

    @property
    def availability(self) -> SensorState:
        """Get sensor availability."""
        return self._availability

    @availability.setter
    def availability(self, value: SensorState) -> None:
        """Set sensor availability."""
        self._availability = value

    def set_unavailable(self) -> None:
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

        # Check for dual availability (global status + local state)
        dual_avail = getattr(self, "_dual_availability", None)
        if dual_avail:
            # Build value_template based on source type
            # Maps various states to online/offline
            source_type = dual_avail["source_type"]
            valid_states: tuple[str, ...]
            if source_type == "service":
                valid_states = ("active",)
            elif source_type == "docker":
                valid_states = ("running",)
            elif source_type == "process":
                valid_states = ("running",)
            elif source_type == "battery":
                valid_states = ("charging", "discharging", "full", "not charging")
            else:
                valid_states = ("online",)

            states_str = ", ".join(f"'{s}'" for s in valid_states)
            local_tpl = f"{{{{ 'online' if value_json.state in [{states_str}] else 'offline' }}}}"

            result["availability_mode"] = "all"
            result["availability"] = [
                {
                    "topic": dual_avail["global_topic"],
                    "payload_available": "online",
                    "payload_not_available": "offline",
                },
                {
                    "topic": dual_avail["local_topic"],
                    "value_template": local_tpl,
                    "payload_available": "online",
                    "payload_not_available": "offline",
                },
            ]
        elif self.availability_topic:
            # Simple availability (for system which uses global status only)
            result["availability_topic"] = self.availability_topic
            result["payload_available"] = self.payload_available
            result["payload_not_available"] = self.payload_not_available

        if self.value_template:
            result["value_template"] = self.value_template

        if self.unit_of_measurement:
            result["unit_of_measurement"] = self.unit_of_measurement

        if self.suggested_display_precision is not None:
            result["suggested_display_precision"] = self.suggested_display_precision

        # Device class
        if self.device_class:
            if isinstance(self.device_class, (DeviceClass, BinarySensorDeviceClass)):
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

        # Binary sensor: custom payload_on/payload_off when state_topic uses non-ON/OFF values
        if self.entity_type == "binary_sensor" and (
            self.payload_on is not None or self.payload_off is not None
        ):
            if self.payload_on is not None:
                result["payload_on"] = self.payload_on
            if self.payload_off is not None:
                result["payload_off"] = self.payload_off

        if self.json_attributes_topic:
            result["json_attributes_topic"] = self.json_attributes_topic

        if self.json_attributes_template:
            result["json_attributes_template"] = self.json_attributes_template

        # Apply extra fields from ha_config
        if hasattr(self, "_ha_extra_fields") and self._ha_extra_fields:
            result.update(self._ha_extra_fields)

        return result

    def get_discovery_topic(self, prefix: str = "homeassistant") -> str:
        """
        Get the MQTT topic for discovery message.

        Args:
            prefix: HA discovery prefix

        Returns:
            Discovery topic string
        """
        return f"{prefix}/{self.entity_type}/{self.unique_id}/config"

    def apply_ha_overrides(self, ha_config: Any) -> None:
        """
        Apply Home Assistant sensor overrides from config.

        Args:
            ha_config: HomeAssistantSensorConfig instance with overrides
        """
        if ha_config is None:
            return

        # Apply known fields
        if ha_config.name is not None:
            self.name = ha_config.name
        if ha_config.icon is not None:
            self.icon = ha_config.icon
        if ha_config.unit_of_measurement is not None:
            self.unit_of_measurement = ha_config.unit_of_measurement
        if ha_config.device_class is not None:
            self.device_class = ha_config.device_class
        if ha_config.state_class is not None:
            self.state_class = ha_config.state_class
        if ha_config.entity_category is not None:
            self.entity_category = ha_config.entity_category
        if ha_config.enabled_by_default is not None:
            self.enabled_by_default = ha_config.enabled_by_default

        # Store extra fields for later use in to_discovery_dict
        if ha_config.extra_fields:
            self._ha_extra_fields = ha_config.extra_fields

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
    device_class: DeviceClass | BinarySensorDeviceClass | str | None = None,
    state_class: StateClass | str | None = None,
    icon: str | None = None,
    availability_topic: str | None = None,
    use_json: bool = True,
    value_template: str | None = None,
    entity_type: str = "sensor",
    suggested_display_precision: int | None = None,
    **kwargs: Any,
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
    # Sanitize source_name for unique_id only (must be valid HA entity ID)
    sanitized_name = _sanitize_id(source_name) if source_name else ""

    # Build unique_id with prefix for uniqueness across systems
    if sanitized_name:
        unique_id = f"penguin_metrics_{topic_prefix}_{source_type}_{sanitized_name}_{metric_name}"
    else:
        unique_id = f"penguin_metrics_{topic_prefix}_{source_type}_{metric_name}"

    # Build state_topic (must match the actual publish topic from source_topic())
    # Use source_name as-is — no sanitization — to match collector_id in the topic
    if source_name:
        state_topic = f"{topic_prefix}/{source_type}/{source_name}"
    else:
        state_topic = f"{topic_prefix}/{source_type}"

    # Build value_template to extract metric from JSON, unless a custom template is provided
    if value_template is None and use_json:
        value_template = f"{{{{ value_json.{metric_name} }}}}"

    # Availability handling
    # For system: use only global status topic
    # For others: use both global status AND local state in JSON
    global_status_topic = f"{topic_prefix}/status"

    ha_config = kwargs.pop("ha_config", None)

    sensor = Sensor(
        unique_id=unique_id,
        name=display_name,
        state_topic=state_topic,
        availability_topic=global_status_topic,  # Default for simple case
        device=device,
        value_template=value_template,
        unit_of_measurement=unit,
        device_class=device_class,
        state_class=state_class,
        icon=icon,
        entity_type=entity_type,
        suggested_display_precision=suggested_display_precision,
        **kwargs,
    )

    if ha_config:
        sensor.apply_ha_overrides(ha_config)

    # For non-system sources, store dual availability info
    # Both global status AND local state must be available
    # Exception: "state" sensor itself doesn't need dual availability
    # (it shows the state, so checking state for availability is redundant)
    if source_type != "system" and metric_name != "state":
        sensor._dual_availability = {
            "global_topic": global_status_topic,
            "local_topic": state_topic,
            "source_type": source_type,
        }

    return sensor
