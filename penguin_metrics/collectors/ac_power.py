"""
AC power (external power supply) monitoring collector.

Reads the 'online' attribute from /sys/class/power_supply/<name>/online.
Publishes AC power connection status (online boolean) for use as a binary sensor in Home Assistant.
Also provides auto-discovery helpers for power supplies under /sys/class/power_supply.
"""

from pathlib import Path
from typing import NamedTuple

from ..config.schema import ACPowerConfig, DefaultsConfig, DeviceConfig
from ..models.device import Device, create_device_from_ref
from ..models.sensor import Sensor
from .base import Collector, CollectorResult, build_sensor


class PowerSupplyInfo(NamedTuple):
    """Power supply device information."""

    name: str
    path: Path
    type: str


def discover_ac_power() -> list[PowerSupplyInfo]:
    """
    Discover non-battery power supplies from /sys/class/power_supply.

    Returns:
        List of PowerSupplyInfo for non-battery devices (e.g. AC, mains, USB).
    """
    devices: list[PowerSupplyInfo] = []
    power_supply = Path("/sys/class/power_supply")

    if not power_supply.exists():
        return devices

    for device in sorted(power_supply.iterdir()):
        type_file = device / "type"

        try:
            device_type = type_file.read_text().strip().lower() if type_file.exists() else ""
        except Exception:
            continue

        # Skip actual batteries; everything else is treated as external power
        if device_type == "battery":
            continue

        devices.append(
            PowerSupplyInfo(
                name=device.name,
                path=device,
                type=device_type,
            )
        )

    return devices


def read_online(path: Path) -> int | None:
    """
    Read the 'online' value from sysfs (1 = connected, 0 = disconnected).

    Returns:
        1 if AC is online, 0 if offline, None if read failed
    """
    online_file = path / "online"
    if not online_file.exists():
        return None
    try:
        value = online_file.read_text().strip()
        return 1 if value == "1" else 0
    except Exception:
        return None


class ACPowerCollector(Collector):
    """
    Collector for external AC power supply status.

    Reads from /sys/class/power_supply/<name>/online.
    """

    SOURCE_TYPE = "ac_power"

    def __init__(
        self,
        config: ACPowerConfig,
        defaults: DefaultsConfig,
        topic_prefix: str = "penguin_metrics",
        parent_device: Device | None = None,
        device_templates: dict[str, DeviceConfig] | None = None,
    ):
        super().__init__(
            name=config.name,
            collector_id=config.name,
            update_interval=config.update_interval or defaults.update_interval,
            topic_prefix=topic_prefix,
        )
        self.config = config
        self.defaults = defaults
        self.topic_prefix = topic_prefix
        self.device_templates = device_templates or {}
        self.parent_device = parent_device

        if config.path:
            self._sysfs_path = Path(config.path)
        else:
            # Use device_name (name directive) or block name for sysfs device
            sysfs_name = config.device_name or config.name
            self._sysfs_path = Path("/sys/class/power_supply") / sysfs_name

    def create_device(self) -> Device | None:
        """Create device for AC power sensor."""
        display_name = (
            self.config.ha_config.name
            if self.config.ha_config and self.config.ha_config.name
            else self.config.name
        )
        return create_device_from_ref(
            device_ref=self.config.device_ref,
            source_type=self.SOURCE_TYPE,
            collector_id=self.collector_id,
            topic_prefix=self.topic_prefix,
            default_name=f"AC Power: {display_name}",
            manufacturer="Penguin Metrics",
            model="AC Power",
            parent_device=self.parent_device,
            device_templates=self.device_templates,
            # By default, group with system device (device system;)
            use_parent_as_default=True,
        )

    def create_sensors(self) -> list[Sensor]:
        """Create binary sensor for AC online state."""
        display_name = self.config.name
        if self.config.ha_config and self.config.ha_config.name:
            display_name = self.config.ha_config.name

        sensor = build_sensor(
            source_type=self.SOURCE_TYPE,
            source_name=self.collector_id,
            metric_name="online",
            display_name=display_name,
            device=self.device,
            topic_prefix=self.topic_prefix,
            entity_type="binary_sensor",
            icon="mdi:power-plug",
            ha_config=self.config.ha_config,
            value_template="{{ 'ON' if value_json.online else 'OFF' }}",
        )
        return [sensor]

    async def collect(self) -> CollectorResult:
        """Read AC online state from sysfs."""
        result = CollectorResult()
        value = read_online(self._sysfs_path)

        if value is None:
            result.set_unavailable("not_found")
            return result

        # State indicates source availability (always "online" if data read successfully)
        # "online" field contains the actual AC power connection status (boolean)
        result.set_state("online")
        result.set("online", value == 1)
        return result
