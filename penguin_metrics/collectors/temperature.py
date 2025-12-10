"""
Temperature collector from thermal zones.

Reads temperature from /sys/class/thermal/thermal_zone*/temp
and from psutil's sensors_temperatures() for hwmon sensors.
"""

from pathlib import Path
from typing import NamedTuple

import psutil

from ..config.schema import DefaultsConfig, SystemConfig, TemperatureConfig
from ..models.device import Device
from ..models.sensor import DeviceClass, Sensor, StateClass, create_sensor
from .base import Collector, CollectorResult


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
    zones = []
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
    index: int  # Index in the chip's sensor list


def discover_hwmon_sensors() -> list[HwmonSensor]:
    """
    Discover hwmon temperature sensors via psutil.

    Returns:
        List of HwmonSensor tuples
    """
    sensors = []

    try:
        temps = psutil.sensors_temperatures()
        for chip_name, entries in temps.items():
            for i, entry in enumerate(entries):
                label = entry.label or f"sensor{i}"
                sensors.append(
                    HwmonSensor(
                        chip=chip_name,
                        label=label,
                        index=i,
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
    ):
        """
        Initialize temperature collector.

        Args:
            config: System or temperature configuration
            defaults: Default settings
            topic_prefix: MQTT topic prefix
            parent_device: Parent device (if part of system collector)
        """
        if isinstance(config, TemperatureConfig):
            name = config.name
            collector_id = config.id
            update_interval = config.update_interval
            self.specific_zone = config.zone
            self.specific_hwmon = config.hwmon
            self.specific_path = config.path
        else:
            # Legacy: SystemConfig passed (should not happen anymore)
            name = f"{config.name}_temperature"
            collector_id = (
                f"{config.id or config.name}_temp" if config.id else f"{config.name}_temp"
            )
            update_interval = config.update_interval
            self.specific_zone = None
            self.specific_hwmon = None
            self.specific_path = None

        super().__init__(
            name=name,
            collector_id=collector_id,
            update_interval=update_interval or defaults.update_interval,
        )

        self.config = config
        self.defaults = defaults
        self.topic_prefix = topic_prefix
        self.parent_device = parent_device

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

    def create_device(self) -> Device:
        """Create device for temperature metrics."""
        if self.parent_device:
            return self.parent_device

        return Device(
            identifiers=[f"penguin_metrics_{self.topic_prefix}_temperature_{self.collector_id}"],
            name=f"Temperature: {self.name}",
            manufacturer="Penguin Metrics",
            model="Temperature Monitor",
        )

    def _add_temp_sensors(
        self,
        sensors: list[Sensor],
        sensor_name: str,
        display_name: str,
        device: Device,
        enabled_by_default: bool = True,
    ) -> None:
        """Add state and temp sensors for a temperature source."""
        # State sensor: online/not_found
        sensors.append(
            create_sensor(
                source_type="temperature",
                source_name=sensor_name,
                metric_name="state",
                display_name=f"{display_name} State",
                device=device,
                topic_prefix=self.topic_prefix,
                icon="mdi:thermometer-check",
                enabled_by_default=enabled_by_default,
            )
        )

        # Temperature value sensor
        sensors.append(
            create_sensor(
                source_type="temperature",
                source_name=sensor_name,
                metric_name="temp",
                display_name=display_name,
                device=device,
                topic_prefix=self.topic_prefix,
                unit="°C",
                device_class=DeviceClass.TEMPERATURE,
                state_class=StateClass.MEASUREMENT,
                icon="mdi:thermometer",
                enabled_by_default=enabled_by_default,
            )
        )

    def create_sensors(self) -> list[Sensor]:
        """Create sensors for discovered thermal zones."""
        sensors = []
        device = self.device

        # Add specific hwmon sensor if configured (manual configuration)
        if self._hwmon_sensors:
            for chip, label, _ in self._hwmon_sensors:
                # Manual config: use self.name as the sensor name
                self._add_temp_sensors(
                    sensors,
                    sensor_name=self.name,
                    display_name=f"Temperature: {chip} {label}",
                    device=device,
                )
            return sensors

        # Add thermal zones (auto-discovered)
        for zone in self._zones:
            zone_label = zone.type if zone.type != zone.name else zone.name
            self._add_temp_sensors(
                sensors,
                sensor_name=zone_label,
                display_name=f"Temperature: {zone.type}",
                device=device,
            )

        # Add all hwmon sensors only if no specific zone/hwmon configured
        if not self.specific_zone and not self.specific_path and not self.specific_hwmon:
            try:
                temps = psutil.sensors_temperatures()
                for name, entries in temps.items():
                    for i, entry in enumerate(entries):
                        label = entry.label or f"sensor{i}"
                        sensor_name = f"{name}_{label}".lower().replace(" ", "_")

                        self._add_temp_sensors(
                            sensors,
                            sensor_name=sensor_name,
                            display_name=f"Temperature: {name} {label}",
                            device=device,
                        )
            except Exception:
                pass

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
