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

from ..config.schema import BatteryConfig, BatteryMatchType, DefaultsConfig, DeviceConfig
from ..models.device import Device, create_device_from_ref
from ..models.sensor import DeviceClass, Sensor, StateClass, create_sensor
from .base import Collector, CollectorResult, apply_overrides_to_sensors, build_sensor


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
            collector_id=config.name,
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
        if self.config.match:
            match self.config.match.type:
                case BatteryMatchType.PATH:
                    path = Path(self.config.match.value)
                    if path.exists():
                        self._battery = BatteryInfo(
                            name=path.name,
                            path=path,
                            type="battery",
                        )
                case BatteryMatchType.NAME:
                    for battery in discover_batteries():
                        if battery.name == self.config.match.value:
                            self._battery = battery
                            break
        else:
            # No match: use first available battery
            batteries = discover_batteries()
            if batteries:
                self._battery = batteries[0]

        await super().initialize()

    def create_device(self) -> Device | None:
        """Create device for battery metrics (uses system device by default)."""
        return create_device_from_ref(
            device_ref=self.config.device_ref,
            source_type=self.SOURCE_TYPE,
            collector_id=self.collector_id,
            topic_prefix=self.topic_prefix,
            default_name=f"Battery: {self.config.label}",
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

        if self.config.voltage_max:
            add(
                "voltage_max",
                "Voltage Max",
                unit="V",
                device_class=DeviceClass.VOLTAGE,
                state_class=StateClass.MEASUREMENT,
                icon="mdi:flash",
            )

        if self.config.voltage_min:
            add(
                "voltage_min",
                "Voltage Min",
                unit="V",
                device_class=DeviceClass.VOLTAGE,
                state_class=StateClass.MEASUREMENT,
                icon="mdi:flash",
            )

        if self.config.voltage_max_design:
            add(
                "voltage_max_design",
                "Voltage Max (Design)",
                unit="V",
                device_class=DeviceClass.VOLTAGE,
                state_class=StateClass.MEASUREMENT,
                icon="mdi:flash",
            )

        if self.config.voltage_min_design:
            add(
                "voltage_min_design",
                "Voltage Min (Design)",
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

        if self.config.constant_charge_current:
            add(
                "constant_charge_current",
                "Const Charge Current",
                unit="A",
                device_class=DeviceClass.CURRENT,
                state_class=StateClass.MEASUREMENT,
                icon="mdi:current-dc",
            )

        if self.config.constant_charge_current_max:
            add(
                "constant_charge_current_max",
                "Const Charge Current Max",
                unit="A",
                device_class=DeviceClass.CURRENT,
                state_class=StateClass.MEASUREMENT,
                icon="mdi:current-dc",
            )

        if self.config.health:
            add("health", "Health", icon="mdi:battery-heart-variant")

        if self.config.present:
            add("present", "Present", icon="mdi:battery-check")

        if self.config.technology:
            add("technology", "Technology", icon="mdi:battery")

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

        if self.config.energy_now:
            sensors.append(
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
                )
            )

        if self.config.energy_full:
            sensors.append(
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
                )
            )

        if self.config.energy_full_design:
            sensors.append(
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
                )
            )

        if self.config.charge_full_design:
            sensors.append(
                build_sensor(
                    source_type=self.SOURCE_TYPE,
                    source_name=self.collector_id,
                    metric_name="charge_full_design",
                    display_name="Charge Full (Design)",
                    device=device,
                    topic_prefix=self.topic_prefix,
                    unit="mAh",
                    device_class=DeviceClass.ENERGY,
                    state_class=StateClass.MEASUREMENT,
                    icon="mdi:battery",
                    ha_config=ha_cfg,
                )
            )

        # HA binary sensors derived from status (no extra MQTT fields)
        binary_sensors = [
            create_sensor(
                source_type=self.SOURCE_TYPE,
                source_name=self.collector_id,
                metric_name="is_charging",
                display_name="Is Charging",
                device=device,
                topic_prefix=self.topic_prefix,
                entity_type="binary_sensor",
                use_json=False,
                value_template="{{ 'ON' if value_json.state == 'charging' else 'OFF' }}",
                device_class="battery_charging",
                icon="mdi:battery-charging-outline",
                ha_config=ha_cfg,
            ),
            create_sensor(
                source_type=self.SOURCE_TYPE,
                source_name=self.collector_id,
                metric_name="is_discharging",
                display_name="Is Discharging",
                device=device,
                topic_prefix=self.topic_prefix,
                entity_type="binary_sensor",
                use_json=False,
                value_template="{{ 'ON' if value_json.state == 'discharging' else 'OFF' }}",
                icon="mdi:battery-arrow-down",
                ha_config=ha_cfg,
            ),
        ]
        apply_overrides_to_sensors(binary_sensors, ha_cfg)
        sensors.extend(binary_sensors)

        return sensors

    async def collect(self) -> CollectorResult:
        """Collect battery metrics."""
        result = CollectorResult()

        if not self._battery:
            result.set_unavailable("not_found")
            return result

        path = self._battery.path

        # Check if battery still exists (device was unplugged)
        # When device is unplugged, the sysfs directory disappears
        if not path.exists():
            result.set_unavailable("not_found")
            return result

        # Status is always collected for state
        # Check if status file exists (may be missing if device partially disappeared)
        status_file = path / "status"
        if not status_file.exists():
            result.set_unavailable("not_found")
            return result

        status = read_sysfs_value(status_file)
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

        if self.config.voltage_max:
            v_max = read_sysfs_float(path / "voltage_max", scale=0.000001)
            if v_max is not None:
                result.set("voltage_max", round(v_max, 2))

        if self.config.voltage_min:
            v_min = read_sysfs_float(path / "voltage_min", scale=0.000001)
            if v_min is not None:
                result.set("voltage_min", round(v_min, 2))

        if self.config.voltage_max_design:
            v_max_d = read_sysfs_float(path / "voltage_max_design", scale=0.000001)
            if v_max_d is not None:
                result.set("voltage_max_design", round(v_max_d, 2))

        if self.config.voltage_min_design:
            v_min_d = read_sysfs_float(path / "voltage_min_design", scale=0.000001)
            if v_min_d is not None:
                result.set("voltage_min_design", round(v_min_d, 2))

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

        if self.config.present:
            present = read_sysfs_int(path / "present")
            if present is not None:
                result.set("present", present)

        if self.config.technology:
            tech = read_sysfs_value(path / "technology")
            if tech:
                result.set("technology", tech)

        if self.config.constant_charge_current:
            ccc = read_sysfs_float(path / "constant_charge_current", scale=0.000001)
            if ccc is not None:
                result.set("constant_charge_current", round(ccc, 3))

        if self.config.constant_charge_current_max:
            ccc_max = read_sysfs_float(path / "constant_charge_current_max", scale=0.000001)
            if ccc_max is not None:
                result.set("constant_charge_current_max", round(ccc_max, 3))

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
        if self.config.energy_now:
            energy_now = read_sysfs_float(path / "energy_now", scale=0.000001)
            if energy_now is not None:
                result.set("energy_now", round(energy_now, 2))

        if self.config.energy_full:
            energy_full = read_sysfs_float(path / "energy_full", scale=0.000001)
            if energy_full is not None:
                result.set("energy_full", round(energy_full, 2))

        if self.config.energy_full_design:
            energy_full_design = read_sysfs_float(path / "energy_full_design", scale=0.000001)
            if energy_full_design is not None:
                result.set("energy_full_design", round(energy_full_design, 2))

        if self.config.charge_full_design:
            charge_full_design = read_sysfs_int(path / "charge_full_design")
            if charge_full_design is not None:
                # sysfs reports in µAh → convert to mAh
                result.set("charge_full_design", round(charge_full_design / 1000, 0))

        return result
