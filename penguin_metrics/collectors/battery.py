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

from ..config.schema import BatteryConfig, DefaultsConfig, DeviceConfig
from ..models.device import Device, create_device_from_ref
from ..models.sensor import DeviceClass, Sensor, StateClass
from .base import Collector, CollectorResult, build_sensor


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
    batteries: list[BatteryInfo] = []
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
            batteries.append(
                BatteryInfo(
                    name=device.name,
                    path=device,
                    type=device_type,
                )
            )

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
        parent_device: Device | None = None,
        device_templates: dict[str, DeviceConfig] | None = None,
    ):
        """
        Initialize battery collector.

        Args:
            config: Battery configuration
            defaults: Default settings
            topic_prefix: MQTT topic prefix
            parent_device: Parent device (system device)
            device_templates: Device template definitions
        """
        super().__init__(
            name=config.name,
            collector_id=config.id or config.name,
            update_interval=config.update_interval or defaults.update_interval,
        )

        self.config = config
        self.defaults = defaults
        self.topic_prefix = topic_prefix
        self.parent_device = parent_device
        self.device_templates = device_templates or {}

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

    def create_device(self) -> Device | None:
        """Create device for battery metrics (uses system device by default)."""
        battery_name = self._battery.name if self._battery else "Unknown"
        return create_device_from_ref(
            device_ref=self.config.device_ref,
            source_type=self.SOURCE_TYPE,
            collector_id=self.collector_id,
            topic_prefix=self.topic_prefix,
            default_name=f"Battery: {battery_name}",
            manufacturer="Unknown",
            model="Battery",
            parent_device=self.parent_device,
            device_templates=self.device_templates,
            use_parent_as_default=True,
        )

    def create_sensors(self) -> list[Sensor]:
        """Create sensors based on configuration."""
        sensors: list[Sensor] = []
        device = self.device
        ha_cfg = self.config.ha_config

        def add(
            metric: str,
            display: str,
            *,
            unit: str | None = None,
            device_class: DeviceClass | str | None = None,
            state_class: StateClass | None = None,
            icon: str | None = None,
        ) -> None:
            sensors.append(
                build_sensor(
                    source_type=self.SOURCE_TYPE,
                    source_name=self.collector_id,
                    metric_name=metric,
                    display_name=display,
                    device=device,
                    topic_prefix=self.topic_prefix,
                    unit=unit,
                    device_class=device_class,
                    state_class=state_class,
                    icon=icon,
                    ha_config=ha_cfg,
                )
            )

        if self.config.capacity:
            add(
                "capacity",
                "Capacity",
                unit="%",
                device_class=DeviceClass.BATTERY,
                state_class=StateClass.MEASUREMENT,
                icon="mdi:battery",
            )

        if self.config.status:
            add("status", "Status", icon="mdi:battery-charging")

        if self.config.voltage:
            add(
                "voltage",
                "Voltage",
                unit="V",
                device_class=DeviceClass.VOLTAGE,
                state_class=StateClass.MEASUREMENT,
                icon="mdi:flash",
            )

        if self.config.current:
            add(
                "current",
                "Current",
                unit="A",
                device_class=DeviceClass.CURRENT,
                state_class=StateClass.MEASUREMENT,
                icon="mdi:current-dc",
            )

        if self.config.power:
            add(
                "power",
                "Power",
                unit="W",
                device_class=DeviceClass.POWER,
                state_class=StateClass.MEASUREMENT,
                icon="mdi:lightning-bolt",
            )

        if self.config.health:
            add("health", "Health", icon="mdi:battery-heart-variant")

        if self.config.cycles:
            add(
                "cycles",
                "Cycle Count",
                state_class=StateClass.TOTAL_INCREASING,
                icon="mdi:battery-sync",
            )

        if self.config.temperature:
            add(
                "temperature",
                "Temperature",
                unit="°C",
                device_class=DeviceClass.TEMPERATURE,
                state_class=StateClass.MEASUREMENT,
                icon="mdi:thermometer",
            )

        if self.config.time_to_empty:
            add(
                "time_to_empty",
                "Time to Empty",
                unit="min",
                device_class=DeviceClass.DURATION,
                state_class=StateClass.MEASUREMENT,
                icon="mdi:battery-arrow-down",
            )

        if self.config.time_to_full:
            add(
                "time_to_full",
                "Time to Full",
                unit="min",
                device_class=DeviceClass.DURATION,
                state_class=StateClass.MEASUREMENT,
                icon="mdi:battery-arrow-up",
            )

        # Energy capacity sensors
        sensors.extend(
            [
                build_sensor(
                    source_type=self.SOURCE_TYPE,
                    source_name=self.collector_id,
                    metric_name="energy_now",
                    display_name="Energy Now",
                    device=device,
                    topic_prefix=self.topic_prefix,
                    unit="Wh",
                    device_class=DeviceClass.ENERGY,
                    state_class=StateClass.MEASUREMENT,
                    icon="mdi:battery",
                    ha_config=ha_cfg,
                ),
                build_sensor(
                    source_type=self.SOURCE_TYPE,
                    source_name=self.collector_id,
                    metric_name="energy_full",
                    display_name="Energy Full",
                    device=device,
                    topic_prefix=self.topic_prefix,
                    unit="Wh",
                    device_class=DeviceClass.ENERGY,
                    state_class=StateClass.MEASUREMENT,
                    icon="mdi:battery",
                    ha_config=ha_cfg,
                ),
                build_sensor(
                    source_type=self.SOURCE_TYPE,
                    source_name=self.collector_id,
                    metric_name="energy_full_design",
                    display_name="Energy Full (Design)",
                    device=device,
                    topic_prefix=self.topic_prefix,
                    unit="Wh",
                    device_class=DeviceClass.ENERGY,
                    state_class=StateClass.MEASUREMENT,
                    icon="mdi:battery",
                    ha_config=ha_cfg,
                ),
            ]
        )

        return sensors

    async def collect(self) -> CollectorResult:
        """Collect battery metrics."""
        result = CollectorResult()

        if not self._battery:
            result.set_unavailable("not_found")
            return result

        path = self._battery.path

        # Status is always collected for state
        status = read_sysfs_value(path / "status")
        if status:
            result.set_state(status.lower())
        else:
            result.set_state("unknown")

        if self.config.capacity:
            capacity = read_sysfs_int(path / "capacity")
            if capacity is not None:
                result.set("capacity", capacity)

        if self.config.voltage:
            voltage = read_sysfs_float(path / "voltage_now", scale=0.000001)
            if voltage is not None:
                result.set("voltage", round(voltage, 2))

        if self.config.current:
            current = read_sysfs_float(path / "current_now", scale=0.000001)
            if current is not None:
                # Preserve sign: negative = discharge, positive = charge (kernel convention)
                result.set("current", round(current, 3))

        if self.config.power:
            power = read_sysfs_float(path / "power_now", scale=0.000001)
            if power is not None:
                # Preserve sign from driver if provided
                result.set("power", round(power, 2))
            else:
                voltage = read_sysfs_float(path / "voltage_now", scale=0.000001)
                current = read_sysfs_float(path / "current_now", scale=0.000001)
                if voltage is not None and current is not None:
                    # Preserve sign: negative current → negative power (discharge)
                    result.set("power", round(voltage * current, 2))

        if self.config.health:
            health = read_sysfs_value(path / "health")
            if health:
                result.set("health", health)

        if self.config.cycles:
            cycles = read_sysfs_int(path / "cycle_count")
            if cycles is not None:
                result.set("cycles", cycles)

        if self.config.temperature:
            temp = read_sysfs_float(path / "temp", scale=0.1)
            if temp is not None:
                result.set("temperature", round(temp, 1))

        if self.config.time_to_empty:
            tte = read_sysfs_int(path / "time_to_empty_now")
            if tte is not None:
                result.set("time_to_empty", tte)

        if self.config.time_to_full:
            ttf = read_sysfs_int(path / "time_to_full_now")
            if ttf is not None:
                result.set("time_to_full", ttf)

        # Energy values
        energy_now = read_sysfs_float(path / "energy_now", scale=0.000001)
        if energy_now is not None:
            result.set("energy_now", round(energy_now, 2))

        energy_full = read_sysfs_float(path / "energy_full", scale=0.000001)
        if energy_full is not None:
            result.set("energy_full", round(energy_full, 2))

        energy_full_design = read_sysfs_float(path / "energy_full_design", scale=0.000001)
        if energy_full_design is not None:
            result.set("energy_full_design", round(energy_full_design, 2))

        if len(result.data) <= 1:  # Only state
            result.set_error("Failed to read battery data")

        return result
