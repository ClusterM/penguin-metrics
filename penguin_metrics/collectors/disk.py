"""
Disk space monitoring collector.

Reads disk usage from mounted partitions via psutil.
Supports auto-discovery of block devices.

Collects:
- Total size (GiB)
- Used space (GiB)
- Free space (GiB)
- Usage percentage (%)
"""

from pathlib import Path
from typing import NamedTuple

import psutil

from ..config.schema import DefaultsConfig, DeviceConfig, DiskConfig
from ..models.device import Device, _add_via_device_if_needed
from ..models.sensor import DeviceClass, Sensor, StateClass, create_sensor
from .base import Collector, CollectorResult


class DiskInfo(NamedTuple):
    """Disk partition information."""

    device: str  # e.g., /dev/sda1, /dev/nvme0n1p1
    mountpoint: str  # e.g., /, /home
    fstype: str  # e.g., ext4, btrfs
    name: str  # Short name: sda1, nvme0n1p1


def discover_disks() -> list[DiskInfo]:
    """
    Discover mounted disk partitions.

    Returns:
        List of DiskInfo tuples for block devices
    """
    disks = []

    for partition in psutil.disk_partitions(all=False):
        # Skip non-physical devices (tmpfs, devtmpfs, etc.)
        if not partition.device.startswith("/dev/"):
            continue

        # Skip special filesystems
        if partition.fstype in ("squashfs", "overlay", "tmpfs", "devtmpfs"):
            continue

        # Extract short device name (sda1, nvme0n1p1)
        device_path = Path(partition.device)
        short_name = device_path.name

        disks.append(
            DiskInfo(
                device=partition.device,
                mountpoint=partition.mountpoint,
                fstype=partition.fstype,
                name=short_name,
            )
        )

    return disks


def get_disk_by_name(name: str) -> DiskInfo | None:
    """Find disk by device name (e.g., sda1, nvme0n1p1)."""
    for disk in discover_disks():
        if disk.name == name:
            return disk
    return None


def get_disk_by_mountpoint(mountpoint: str) -> DiskInfo | None:
    """Find disk by mountpoint (e.g., /, /home)."""
    for disk in discover_disks():
        if disk.mountpoint == mountpoint:
            return disk
    return None


class DiskCollector(Collector):
    """
    Collector for disk space metrics.

    Reads disk usage from mounted partitions.
    """

    SOURCE_TYPE = "disk"

    def __init__(
        self,
        config: DiskConfig,
        defaults: DefaultsConfig,
        topic_prefix: str = "penguin_metrics",
        parent_device: Device | None = None,
        device_templates: dict[str, DeviceConfig] | None = None,
    ):
        """
        Initialize disk collector.

        Args:
            config: Disk configuration
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

        # Disk info
        self._disk: DiskInfo | None = None

    async def initialize(self) -> None:
        """Find the disk device."""
        if self.config.mountpoint:
            # Find by mountpoint
            self._disk = get_disk_by_mountpoint(self.config.mountpoint)
        elif self.config.path:
            # Find by device name (sda1, nvme0n1p1)
            self._disk = get_disk_by_name(self.config.path)
        else:
            # Try to find by config name
            self._disk = get_disk_by_name(self.config.name)

        await super().initialize()

    def create_device(self) -> Device | None:
        """Create device for disk metrics (uses system device by default)."""
        device_ref = self.config.device_ref
        disk_name = self._disk.name if self._disk else self.config.name

        # Handle "none" - no device
        if device_ref == "none":
            return None

        # Handle "auto" - create unique device
        if device_ref == "auto":
            device = Device(
                identifiers=[f"penguin_metrics_{self.topic_prefix}_disk_{self.collector_id}"],
                name=f"Disk: {disk_name}",
                manufacturer="Penguin Metrics",
                model="Disk Monitor",
            )
            _add_via_device_if_needed(device, self.parent_device, self.SOURCE_TYPE)
            return device

        # Handle template reference
        if device_ref and device_ref not in ("system", "auto", "none"):
            if device_ref in self.device_templates:
                template = self.device_templates[device_ref]
                device = Device(
                    identifiers=template.identifiers.copy(),
                    extra_fields=template.extra_fields.copy() if template.extra_fields else {},
                )
                _add_via_device_if_needed(device, self.parent_device, self.SOURCE_TYPE)
                return device

        # Default for disk: use parent device (system)
        if self.parent_device:
            return self.parent_device

        # Fallback if no parent device
        device = Device(
            identifiers=[f"penguin_metrics_{self.topic_prefix}_disk_{self.collector_id}"],
            name=f"Disk: {disk_name}",
            manufacturer="Penguin Metrics",
            model="Disk Monitor",
        )
        _add_via_device_if_needed(device, self.parent_device, self.SOURCE_TYPE)
        return device

    def create_sensors(self) -> list[Sensor]:
        """Create sensors for disk metrics."""
        sensors = []
        device = self.device
        disk_name = self._disk.name if self._disk else self.config.name

        # Display name prefix - include disk identifier for system device
        name_prefix = f"Disk {disk_name}"

        if self.config.total:
            sensors.append(
                create_sensor(
                    source_type="disk",
                    source_name=disk_name,
                    metric_name="total",
                    display_name=f"{name_prefix} Total",
                    device=device,
                    topic_prefix=self.topic_prefix,
                    unit="GiB",
                    device_class=DeviceClass.DATA_SIZE,
                    state_class=StateClass.MEASUREMENT,
                    icon="mdi:harddisk",
                )
            )

        if self.config.used:
            sensors.append(
                create_sensor(
                    source_type="disk",
                    source_name=disk_name,
                    metric_name="used",
                    display_name=f"{name_prefix} Used",
                    device=device,
                    topic_prefix=self.topic_prefix,
                    unit="GiB",
                    device_class=DeviceClass.DATA_SIZE,
                    state_class=StateClass.MEASUREMENT,
                    icon="mdi:harddisk",
                )
            )

        if self.config.free:
            sensors.append(
                create_sensor(
                    source_type="disk",
                    source_name=disk_name,
                    metric_name="free",
                    display_name=f"{name_prefix} Free",
                    device=device,
                    topic_prefix=self.topic_prefix,
                    unit="GiB",
                    device_class=DeviceClass.DATA_SIZE,
                    state_class=StateClass.MEASUREMENT,
                    icon="mdi:harddisk",
                )
            )

        if self.config.percent:
            sensors.append(
                create_sensor(
                    source_type="disk",
                    source_name=disk_name,
                    metric_name="percent",
                    display_name=f"{name_prefix} Usage",
                    device=device,
                    topic_prefix=self.topic_prefix,
                    unit="%",
                    state_class=StateClass.MEASUREMENT,
                    icon="mdi:harddisk",
                )
            )

        # Apply HA overrides from config to all sensors
        if self.config.ha_config:
            for sensor in sensors:
                sensor.apply_ha_overrides(self.config.ha_config)

        return sensors

    async def collect(self) -> CollectorResult:
        """Collect disk metrics."""
        result = CollectorResult()

        if not self._disk:
            result.set_unavailable("not_found")
            return result

        try:
            usage = psutil.disk_usage(self._disk.mountpoint)
        except (OSError, PermissionError) as e:
            result.set_error(str(e))
            result.set_unavailable("error")
            return result

        result.set_state("online")

        # Convert bytes to GB (1 GB = 1024^3 bytes)
        gb = 1024 * 1024 * 1024

        if self.config.total:
            result.set("total", round(usage.total / gb, 2))

        if self.config.used:
            result.set("used", round(usage.used / gb, 2))

        if self.config.free:
            result.set("free", round(usage.free / gb, 2))

        if self.config.percent:
            result.set("percent", round(usage.percent, 1))

        return result
