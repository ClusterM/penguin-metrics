"""
Temperature collector from thermal zones.

Reads temperature from /sys/class/thermal/thermal_zone*/temp
and from psutil's sensors_temperatures() for hwmon sensors.
"""

from pathlib import Path
from typing import Any, NamedTuple

import psutil

from ..config.schema import (
    DefaultsConfig,
    DeviceConfig,
    SystemConfig,
    TemperatureConfig,
    TemperatureMatchType,
)
from ..models.device import Device, create_device_from_ref
from ..models.sensor import DeviceClass, Sensor, StateClass
from .base import Collector, CollectorResult, build_sensor


class ThermalZone(NamedTuple):
    """Thermal zone information."""

    name: str
    path: Path
    type: str


def discover_thermal_zones() -> list[ThermalZone]:
    """
    Discover available thermal zones from sysfs.

    Returns:
        List of ThermalZone tuples
    """
    zones: list[ThermalZone] = []
    thermal_path = Path("/sys/class/thermal")

    if not thermal_path.exists():
        return zones

    for zone_dir in sorted(thermal_path.glob("thermal_zone*")):
        type_file = zone_dir / "type"
        temp_file = zone_dir / "temp"

        if not temp_file.exists():
            continue

        try:
            zone_type = type_file.read_text().strip() if type_file.exists() else zone_dir.name
        except Exception:
            zone_type = zone_dir.name

        zones.append(
            ThermalZone(
                name=zone_dir.name,
                path=zone_dir,
                type=zone_type,
            )
        )

    return zones


def read_thermal_zone_temp(zone: ThermalZone) -> float | None:
    """
    Read temperature from a thermal zone.

    Args:
        zone: ThermalZone to read from

    Returns:
        Temperature in Celsius, or None if unavailable
    """
    temp_file = zone.path / "temp"

    try:
        # Temperature is in millidegrees Celsius
        temp_raw = temp_file.read_text().strip()
        return int(temp_raw) / 1000.0
    except Exception:
        return None


class HwmonSensor(NamedTuple):
    """Hardware monitor sensor information."""

    chip: str  # Chip name (e.g., soc_thermal, nvme)
    label: str  # Sensor label (e.g., sensor0, Composite)
    sensor_index: int  # Index in the chip's sensor list


def discover_hwmon_sensors() -> list[HwmonSensor]:
    """
    Discover hwmon temperature sensors via psutil.

    Returns:
        List of HwmonSensor tuples
    """
    sensors: list[HwmonSensor] = []

    try:
        temps = psutil.sensors_temperatures()
        for chip_name, entries in temps.items():
            for i, entry in enumerate(entries):
                label = entry.label or f"sensor{i}"
                sensors.append(
                    HwmonSensor(
                        chip=chip_name,
                        label=label,
                        sensor_index=i,
                    )
                )
    except Exception:
        pass

    return sensors


class TemperatureCollector(Collector):
    """
    Collector for temperature sensors.

    Supports both sysfs thermal zones and hwmon sensors via psutil.
    """

    SOURCE_TYPE = "temperature"

    def __init__(
        self,
        config: SystemConfig | TemperatureConfig,
        defaults: DefaultsConfig,
        topic_prefix: str = "penguin_metrics",
        parent_device: Device | None = None,
        device_templates: dict[str, DeviceConfig] | None = None,
    ):
        """
        Initialize temperature collector.

        Args:
            config: System or temperature configuration
            defaults: Default settings
            topic_prefix: MQTT topic prefix
            parent_device: Parent device (if part of system collector)
            device_templates: Device template definitions
        """
        if isinstance(config, TemperatureConfig):
            name = config.name
            collector_id = config.name
            update_interval = config.update_interval
            self._device_ref = config.device_ref
            # Extract match target
            self.specific_zone: str | None = None
            self.specific_hwmon: str | None = None
            self.specific_path: str | None = None
            if config.match:
                match config.match.type:
                    case TemperatureMatchType.ZONE:
                        self.specific_zone = config.match.value
                    case TemperatureMatchType.HWMON:
                        self.specific_hwmon = config.match.value
                    case TemperatureMatchType.PATH:
                        self.specific_path = config.match.value
        else:
            # Legacy: SystemConfig passed (should not happen anymore)
            name = f"{config.name}_temperature"
            collector_id = f"{config.name}_temp"
            update_interval = config.update_interval
            self.specific_zone = None
            self.specific_hwmon = None
            self.specific_path = None
            self._device_ref = None

        super().__init__(
            name=name,
            collector_id=collector_id,
            update_interval=update_interval or defaults.update_interval,
        )

        self.config = config
        self.defaults = defaults
        self.topic_prefix = topic_prefix
        self.parent_device = parent_device
        self.device_templates = device_templates or {}

        # Discovered zones and hwmon sensors
        self._zones: list[ThermalZone] = []
        self._hwmon_sensors: list[tuple[str, str, int]] = []  # (chip, label, index)

    async def initialize(self) -> None:
        """Discover thermal zones on initialization."""
        if self.specific_hwmon:
            # Specific hwmon sensor configured - find it
            try:
                temps = psutil.sensors_temperatures()
                target = self.specific_hwmon.lower().replace("-", "_")
                for chip, entries in temps.items():
                    for i, entry in enumerate(entries):
                        label = entry.label or f"sensor{i}"
                        sensor_name = f"{chip}_{label}".lower().replace(" ", "_").replace("-", "_")
                        if sensor_name == target or label.lower().replace("-", "_") == target:
                            self._hwmon_sensors = [(chip, label, i)]
                            break
                    if self._hwmon_sensors:
                        break
            except Exception:
                pass
        elif self.specific_zone or self.specific_path:
            # Specific thermal zone configured
            if self.specific_path:
                # Path and name are not used, but kept for potential future use
                _ = Path(self.specific_path).parent
                _ = Path(self.specific_path).parent.name
            else:
                # Find zone by type or name
                for zone in discover_thermal_zones():
                    if zone.type == self.specific_zone or zone.name == self.specific_zone:
                        self._zones = [zone]
                        break
        else:
            # Discover all zones
            self._zones = discover_thermal_zones()

        await super().initialize()

    def create_device(self) -> Device | None:
        """Create device for temperature metrics."""
        return create_device_from_ref(
            device_ref=self._device_ref,
            source_type=self.SOURCE_TYPE,
            collector_id=self.collector_id,
            topic_prefix=self.topic_prefix,
            default_name=f"Temperature: {self.config.label}",
            model="Temperature Sensor",
            parent_device=self.parent_device,
            device_templates=self.device_templates,
            use_parent_as_default=True,
        )

    def _add_temp_sensor(
        self,
        sensors: list[Sensor],
        sensor_name: str,
        display_name: str,
        device: Device | None,
        ha_config: Any,
    ) -> None:
        """Add temperature sensor (state is in JSON but no HA sensor for it)."""
        sensors.append(
            build_sensor(
                source_type="temperature",
                source_name=sensor_name,
                metric_name="temp",
                display_name=display_name,
                device=device,
                topic_prefix=self.topic_prefix,
                unit="°C",
                device_class=DeviceClass.TEMPERATURE,
                state_class=StateClass.MEASUREMENT,
                ha_config=ha_config,
            )
        )

    def create_sensors(self) -> list[Sensor]:
        """Create sensors for discovered thermal zones."""
        sensors: list[Sensor] = []
        device = self.device
        # source_name must match collector_id for correct state_topic
        source_name = self.collector_id

        ha_cfg = self.config.ha_config if isinstance(self.config, TemperatureConfig) else None

        # Add specific hwmon sensor if configured (manual configuration)
        if self._hwmon_sensors:
            self._add_temp_sensor(
                sensors,
                sensor_name=source_name,
                display_name=f"{self.config.label} Temperature",
                device=device,
                ha_config=ha_cfg,
            )
            return sensors

        # Add thermal zones (first zone — each collector handles one sensor)
        if self._zones:
            self._add_temp_sensor(
                sensors,
                sensor_name=source_name,
                display_name=f"{self.config.label} Temperature",
                device=device,
                ha_config=ha_cfg,
            )

        return sensors

    async def collect(self) -> CollectorResult:
        """Collect temperature readings."""
        result = CollectorResult()

        # Read specific hwmon sensor if configured (manual)
        if self._hwmon_sensors:
            try:
                temps = psutil.sensors_temperatures()
                for chip, _label, idx in self._hwmon_sensors:
                    if chip in temps and idx < len(temps[chip]):
                        entry = temps[chip][idx]
                        result.set("temp", round(entry.current, 1))
                        result.set_state("online")
                        return result
            except Exception:
                pass

            # Sensor not found
            result.set_unavailable("not_found")
            return result

        # Read from thermal zones (first one only - each collector handles one sensor)
        if self._zones:
            zone = self._zones[0]
            # Check if zone still exists (sensor/device was removed)
            if not zone.path.exists():
                result.set_unavailable("not_found")
                return result
            temp = read_thermal_zone_temp(zone)
            if temp is not None:
                result.set("temp", round(temp, 1))
                result.set_state("online")
            else:
                result.set_unavailable("not_found")
            return result

        # No sensors configured/discovered
        result.set_error("No temperature sensor available")
        return result
