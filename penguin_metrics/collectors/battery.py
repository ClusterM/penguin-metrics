"""
Battery monitoring collector.

Reads battery information from /sys/class/power_supply/
Supports multiple batteries (BAT0, BAT1, etc.)

Collects:
- Capacity (percentage)
- Status (charging, discharging, full, not charging)
- Voltage
- Current
- Power
- Health
- Cycle count
- Temperature
- Time to empty/full
"""

from pathlib import Path
from typing import NamedTuple

from .base import Collector, CollectorResult
from ..models.device import Device
from ..models.sensor import Sensor, DeviceClass, StateClass, create_sensor
from ..config.schema import BatteryConfig, DefaultsConfig


class BatteryInfo(NamedTuple):
    """Battery device information."""
    name: str
    path: Path
    type: str


def discover_batteries() -> list[BatteryInfo]:
    """
    Discover battery devices from /sys/class/power_supply.
    
    Returns:
        List of BatteryInfo for battery devices
    """
    batteries = []
    power_supply = Path("/sys/class/power_supply")
    
    if not power_supply.exists():
        return batteries
    
    for device in sorted(power_supply.iterdir()):
        type_file = device / "type"
        
        try:
            device_type = type_file.read_text().strip().lower() if type_file.exists() else ""
        except Exception:
            continue
        
        if device_type == "battery":
            batteries.append(BatteryInfo(
                name=device.name,
                path=device,
                type=device_type,
            ))
    
    return batteries


def read_sysfs_value(path: Path, default: str | None = None) -> str | None:
    """Read a value from a sysfs file."""
    try:
        return path.read_text().strip()
    except Exception:
        return default


def read_sysfs_int(path: Path, default: int | None = None) -> int | None:
    """Read an integer value from a sysfs file."""
    value = read_sysfs_value(path)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def read_sysfs_float(path: Path, scale: float = 1.0, default: float | None = None) -> float | None:
    """Read a float value from a sysfs file with optional scaling."""
    value = read_sysfs_int(path)
    if value is None:
        return default
    return value * scale


class BatteryCollector(Collector):
    """
    Collector for battery metrics.
    
    Reads battery status from /sys/class/power_supply.
    """
    
    SOURCE_TYPE = "battery"
    
    def __init__(
        self,
        config: BatteryConfig,
        defaults: DefaultsConfig,
        topic_prefix: str = "penguin_metrics",
    ):
        """
        Initialize battery collector.
        
        Args:
            config: Battery configuration
            defaults: Default settings
            topic_prefix: MQTT topic prefix
        """
        super().__init__(
            name=config.name,
            collector_id=config.id or config.name,
            update_interval=config.update_interval or defaults.update_interval,
        )
        
        self.config = config
        self.defaults = defaults
        self.topic_prefix = topic_prefix
        
        # Battery device info
        self._battery: BatteryInfo | None = None
    
    async def initialize(self) -> None:
        """Find the battery device."""
        if self.config.path:
            # Specific path provided
            path = Path(self.config.path)
            if path.exists():
                self._battery = BatteryInfo(
                    name=path.name,
                    path=path,
                    type="battery",
                )
        elif self.config.battery_name:
            # Find by name
            for battery in discover_batteries():
                if battery.name == self.config.battery_name:
                    self._battery = battery
                    break
        else:
            # Use first available battery
            batteries = discover_batteries()
            if batteries:
                self._battery = batteries[0]
        
        await super().initialize()
    
    def create_device(self) -> Device:
        """Create device for battery metrics."""
        device_config = self.config.device
        battery_name = self._battery.name if self._battery else "Unknown"
        
        return Device(
            identifiers=[f"battery_{self.collector_id}"],
            name=device_config.name or f"Battery: {battery_name}",
            manufacturer=device_config.manufacturer or "Unknown",
            model="Battery",
        )
    
    def create_sensors(self) -> list[Sensor]:
        """Create sensors based on configuration."""
        sensors = []
        device = self.device
        
        if self.config.capacity:
            sensors.append(create_sensor(
                source_id=self.collector_id,
                metric_name="capacity",
                display_name=f"{self.config.name} Capacity",
                device=device,
                topic_prefix=self.topic_prefix,
                unit="%",
                device_class=DeviceClass.BATTERY,
                state_class=StateClass.MEASUREMENT,
                icon="mdi:battery",
            ))
        
        if self.config.status:
            sensors.append(create_sensor(
                source_id=self.collector_id,
                metric_name="status",
                display_name=f"{self.config.name} Status",
                device=device,
                topic_prefix=self.topic_prefix,
                icon="mdi:battery-charging",
            ))
        
        if self.config.voltage:
            sensors.append(create_sensor(
                source_id=self.collector_id,
                metric_name="voltage",
                display_name=f"{self.config.name} Voltage",
                device=device,
                topic_prefix=self.topic_prefix,
                unit="V",
                device_class=DeviceClass.VOLTAGE,
                state_class=StateClass.MEASUREMENT,
                icon="mdi:flash",
            ))
        
        if self.config.current:
            sensors.append(create_sensor(
                source_id=self.collector_id,
                metric_name="current",
                display_name=f"{self.config.name} Current",
                device=device,
                topic_prefix=self.topic_prefix,
                unit="A",
                device_class=DeviceClass.CURRENT,
                state_class=StateClass.MEASUREMENT,
                icon="mdi:current-dc",
            ))
        
        if self.config.power:
            sensors.append(create_sensor(
                source_id=self.collector_id,
                metric_name="power",
                display_name=f"{self.config.name} Power",
                device=device,
                topic_prefix=self.topic_prefix,
                unit="W",
                device_class=DeviceClass.POWER,
                state_class=StateClass.MEASUREMENT,
                icon="mdi:lightning-bolt",
            ))
        
        if self.config.health:
            sensors.append(create_sensor(
                source_id=self.collector_id,
                metric_name="health",
                display_name=f"{self.config.name} Health",
                device=device,
                topic_prefix=self.topic_prefix,
                icon="mdi:battery-heart-variant",
            ))
        
        if self.config.cycles:
            sensors.append(create_sensor(
                source_id=self.collector_id,
                metric_name="cycles",
                display_name=f"{self.config.name} Cycle Count",
                device=device,
                topic_prefix=self.topic_prefix,
                state_class=StateClass.TOTAL_INCREASING,
                icon="mdi:battery-sync",
            ))
        
        if self.config.temperature:
            sensors.append(create_sensor(
                source_id=self.collector_id,
                metric_name="temperature",
                display_name=f"{self.config.name} Temperature",
                device=device,
                topic_prefix=self.topic_prefix,
                unit="°C",
                device_class=DeviceClass.TEMPERATURE,
                state_class=StateClass.MEASUREMENT,
                icon="mdi:thermometer",
            ))
        
        if self.config.time_to_empty:
            sensors.append(create_sensor(
                source_id=self.collector_id,
                metric_name="time_to_empty",
                display_name=f"{self.config.name} Time to Empty",
                device=device,
                topic_prefix=self.topic_prefix,
                unit="min",
                device_class=DeviceClass.DURATION,
                state_class=StateClass.MEASUREMENT,
                icon="mdi:battery-arrow-down",
            ))
        
        if self.config.time_to_full:
            sensors.append(create_sensor(
                source_id=self.collector_id,
                metric_name="time_to_full",
                display_name=f"{self.config.name} Time to Full",
                device=device,
                topic_prefix=self.topic_prefix,
                unit="min",
                device_class=DeviceClass.DURATION,
                state_class=StateClass.MEASUREMENT,
                icon="mdi:battery-arrow-up",
            ))
        
        # Energy capacity sensors
        sensors.extend([
            create_sensor(
                source_id=self.collector_id,
                metric_name="energy_now",
                display_name=f"{self.config.name} Energy Now",
                device=device,
                topic_prefix=self.topic_prefix,
                unit="Wh",
                device_class=DeviceClass.ENERGY,
                state_class=StateClass.MEASUREMENT,
                icon="mdi:battery",
                enabled_by_default=False,
            ),
            create_sensor(
                source_id=self.collector_id,
                metric_name="energy_full",
                display_name=f"{self.config.name} Energy Full",
                device=device,
                topic_prefix=self.topic_prefix,
                unit="Wh",
                device_class=DeviceClass.ENERGY,
                state_class=StateClass.MEASUREMENT,
                icon="mdi:battery",
                enabled_by_default=False,
            ),
            create_sensor(
                source_id=self.collector_id,
                metric_name="energy_full_design",
                display_name=f"{self.config.name} Energy Full (Design)",
                device=device,
                topic_prefix=self.topic_prefix,
                unit="Wh",
                device_class=DeviceClass.ENERGY,
                state_class=StateClass.MEASUREMENT,
                icon="mdi:battery",
                enabled_by_default=False,
            ),
        ])
        
        return sensors
    
    async def collect(self) -> CollectorResult:
        """Collect battery metrics."""
        result = CollectorResult()
        
        if not self._battery:
            result.set_error("No battery found")
            return result
        
        path = self._battery.path
        
        if self.config.capacity:
            capacity = read_sysfs_int(path / "capacity")
            if capacity is not None:
                result.add_metric(f"{self.collector_id}_capacity", capacity)
        
        if self.config.status:
            status = read_sysfs_value(path / "status")
            if status:
                result.add_metric(f"{self.collector_id}_status", status.lower())
        
        if self.config.voltage:
            # voltage_now is in microvolts
            voltage = read_sysfs_float(path / "voltage_now", scale=0.000001)
            if voltage is not None:
                result.add_metric(f"{self.collector_id}_voltage", round(voltage, 2))
        
        if self.config.current:
            # current_now is in microamps
            current = read_sysfs_float(path / "current_now", scale=0.000001)
            if current is not None:
                result.add_metric(f"{self.collector_id}_current", round(abs(current), 3))
        
        if self.config.power:
            # power_now is in microwatts
            power = read_sysfs_float(path / "power_now", scale=0.000001)
            if power is not None:
                result.add_metric(f"{self.collector_id}_power", round(power, 2))
            else:
                # Calculate from voltage and current if power_now not available
                voltage = read_sysfs_float(path / "voltage_now", scale=0.000001)
                current = read_sysfs_float(path / "current_now", scale=0.000001)
                if voltage and current:
                    power = abs(voltage * current)
                    result.add_metric(f"{self.collector_id}_power", round(power, 2))
        
        if self.config.health:
            health = read_sysfs_value(path / "health")
            if health:
                result.add_metric(f"{self.collector_id}_health", health)
        
        if self.config.cycles:
            cycles = read_sysfs_int(path / "cycle_count")
            if cycles is not None:
                result.add_metric(f"{self.collector_id}_cycles", cycles)
        
        if self.config.temperature:
            # temp is in tenths of degrees Celsius
            temp = read_sysfs_float(path / "temp", scale=0.1)
            if temp is not None:
                result.add_metric(f"{self.collector_id}_temperature", round(temp, 1))
        
        if self.config.time_to_empty:
            # time_to_empty_now is in minutes
            tte = read_sysfs_int(path / "time_to_empty_now")
            if tte is not None:
                result.add_metric(f"{self.collector_id}_time_to_empty", tte)
        
        if self.config.time_to_full:
            ttf = read_sysfs_int(path / "time_to_full_now")
            if ttf is not None:
                result.add_metric(f"{self.collector_id}_time_to_full", ttf)
        
        # Energy values (in microwatt-hours, convert to Wh)
        energy_now = read_sysfs_float(path / "energy_now", scale=0.000001)
        if energy_now is not None:
            result.add_metric(f"{self.collector_id}_energy_now", round(energy_now, 2))
        
        energy_full = read_sysfs_float(path / "energy_full", scale=0.000001)
        if energy_full is not None:
            result.add_metric(f"{self.collector_id}_energy_full", round(energy_full, 2))
        
        energy_full_design = read_sysfs_float(path / "energy_full_design", scale=0.000001)
        if energy_full_design is not None:
            result.add_metric(f"{self.collector_id}_energy_full_design", round(energy_full_design, 2))
        
        if not result.metrics:
            result.set_error("Failed to read battery data")
        
        return result

