"""
Temperature collector from thermal zones.

Reads temperature from /sys/class/thermal/thermal_zone*/temp
and from psutil's sensors_temperatures() for hwmon sensors.
"""

from pathlib import Path
from typing import NamedTuple
import psutil

from .base import Collector, CollectorResult
from ..models.device import Device
from ..models.sensor import Sensor, DeviceClass, StateClass, create_sensor
from ..config.schema import SystemConfig, TemperatureConfig, DefaultsConfig


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
        
        zones.append(ThermalZone(
            name=zone_dir.name,
            path=zone_dir,
            type=zone_type,
        ))
    
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
    chip: str       # Chip name (e.g., soc_thermal, nvme)
    label: str      # Sensor label (e.g., sensor0, Composite)
    index: int      # Index in the chip's sensor list


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
                sensors.append(HwmonSensor(
                    chip=chip_name,
                    label=label,
                    index=i,
                ))
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
            self.warning_temp = config.warning
            self.critical_temp = config.critical
        else:
            name = f"{config.name}_temperature"
            collector_id = f"{config.id or config.name}_temp" if config.id else f"{config.name}_temp"
            update_interval = config.update_interval
            self.specific_zone = None
            self.specific_hwmon = None
            self.specific_path = None
            self.warning_temp = None
            self.critical_temp = None
        
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
                path = Path(self.specific_path).parent
                name = Path(self.specific_path).parent.name
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
            identifiers=[f"temp_{self.collector_id}"],
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
        sensors.append(create_sensor(
            source_type="temperature",
            source_name=sensor_name,
            metric_name="state",
            display_name=f"{display_name} State",
            device=device,
            topic_prefix=self.topic_prefix,
            icon="mdi:thermometer-check",
            enabled_by_default=enabled_by_default,
        ))
        
        # Temperature value sensor
        sensors.append(create_sensor(
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
        ))
    
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
                            enabled_by_default=False,  # Hwmon sensors disabled by default
                        )
            except Exception:
                pass
        
        return sensors
    
    def _add_temp_metrics(
        self,
        result: CollectorResult,
        sensor_name: str,
        temp_value: float | None,
        high: float | None = None,
        critical: float | None = None,
    ) -> None:
        """Add state and temp metrics for a temperature sensor."""
        if temp_value is not None:
            # Sensor is available
            result.add_metric(f"{sensor_name}_state", "online")
            result.add_metric(
                f"{sensor_name}_temp",
                round(temp_value, 1),
                high=high,
                critical=critical,
            )
        else:
            # Sensor not available
            result.add_metric(f"{sensor_name}_state", "not_found")
    
    async def collect(self) -> CollectorResult:
        """Collect temperature readings."""
        result = CollectorResult()
        
        # Read specific hwmon sensor if configured (manual)
        if self._hwmon_sensors:
            found = False
            try:
                temps = psutil.sensors_temperatures()
                for chip, label, idx in self._hwmon_sensors:
                    if chip in temps and idx < len(temps[chip]):
                        entry = temps[chip][idx]
                        self._add_temp_metrics(
                            result,
                            sensor_name=self.name,
                            temp_value=entry.current,
                            high=entry.high,
                            critical=entry.critical,
                        )
                        found = True
            except Exception:
                pass
            
            if not found:
                # Sensor not found - publish not_found state
                self._add_temp_metrics(result, sensor_name=self.name, temp_value=None)
            return result
        
        # Read from thermal zones (auto-discovered)
        for zone in self._zones:
            zone_label = zone.type if zone.type != zone.name else zone.name
            temp = read_thermal_zone_temp(zone)
            self._add_temp_metrics(result, sensor_name=zone_label, temp_value=temp)
        
        # Read all hwmon sensors (auto-discovered, only if no specific config)
        if not self.specific_zone and not self.specific_path and not self.specific_hwmon:
            try:
                temps = psutil.sensors_temperatures()
                for name, entries in temps.items():
                    for i, entry in enumerate(entries):
                        label = entry.label or f"sensor{i}"
                        sensor_name = f"{name}_{label}".lower().replace(" ", "_")
                        
                        self._add_temp_metrics(
                            result,
                            sensor_name=sensor_name,
                            temp_value=entry.current,
                            high=entry.high,
                            critical=entry.critical,
                        )
            except Exception:
                pass
        
        if not result.metrics:
            result.set_error("No temperature sensors available")
        
        return result
    
    def metric_topic(self, metric_sensor_id: str, topic_prefix: str) -> str:
        """
        Build MQTT topic for temperature metric.
        
        Format: {prefix}/temperature/{sensor_name}/{metric}
        Example: penguin_metrics/temperature/soc-thermal/temp
        """
        # metric_sensor_id format: {sensor_name}_{metric} (e.g., "soc-thermal_temp")
        # Split into sensor_name and metric
        if "_state" in metric_sensor_id:
            sensor_name = metric_sensor_id.rsplit("_state", 1)[0]
            metric = "state"
        elif "_temp" in metric_sensor_id:
            sensor_name = metric_sensor_id.rsplit("_temp", 1)[0]
            metric = "temp"
        else:
            # Fallback
            sensor_name = metric_sensor_id
            metric = "value"
        
        return f"{topic_prefix}/temperature/{sensor_name}/{metric}"

