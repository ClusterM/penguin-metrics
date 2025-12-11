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
from ..models.device import Device, create_device_from_ref
from ..models.sensor import DeviceClass, Sensor, StateClass
from .base import Collector, CollectorResult, build_sensor


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
            collector_id=config.name,
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
        disk_name = self._disk.name if self._disk else self.config.name
        return create_device_from_ref(
            device_ref=self.config.device_ref,
            source_type=self.SOURCE_TYPE,
            collector_id=self.collector_id,
            topic_prefix=self.topic_prefix,
            default_name=f"Disk: {disk_name}",
            manufacturer="Penguin Metrics",
            model="Disk Monitor",
            parent_device=self.parent_device,
            device_templates=self.device_templates,
            use_parent_as_default=True,
        )

    def create_sensors(self) -> list[Sensor]:
        """Create sensors for disk metrics."""
        sensors: list[Sensor] = []
        device = self.device
        disk_name = self._disk.name if self._disk else self.config.name
        ha_cfg = getattr(self.config, "ha_config", None)

        name_prefix = f"Disk {disk_name}"

        def add(metric: str, display: str, unit: str, *, icon: str = "mdi:harddisk") -> None:
            sensors.append(
                build_sensor(
                    source_type="disk",
                    source_name=disk_name,
                    metric_name=metric,
                    display_name=display,
                    device=device,
                    topic_prefix=self.topic_prefix,
                    unit=unit,
                    device_class=DeviceClass.DATA_SIZE,
                    state_class=StateClass.MEASUREMENT,
                    icon=icon,
                    ha_config=ha_cfg,
                )
            )

        if self.config.total:
            add("total", f"{name_prefix} Total", "GiB")

        if self.config.used:
            add("used", f"{name_prefix} Used", "GiB")

        if self.config.free:
            add("free", f"{name_prefix} Free", "GiB")

        if self.config.percent:
            sensors.append(
                build_sensor(
                    source_type="disk",
                    source_name=disk_name,
                    metric_name="percent",
                    display_name=f"{name_prefix} Usage",
                    device=device,
                    topic_prefix=self.topic_prefix,
                    unit="%",
                    state_class=StateClass.MEASUREMENT,
                    icon="mdi:chart-donut",
                    ha_config=ha_cfg,
                )
            )

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
