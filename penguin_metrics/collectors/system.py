"""
System-wide metrics collector.

Collects:
- CPU usage (overall and per-core)
- Memory usage (total, used, available, percent)
- Swap usage
- Load average (1, 5, 15 minutes)
- Uptime
"""

import platform
import socket
from datetime import datetime
from pathlib import Path

import psutil

from ..config.schema import DefaultsConfig, DeviceConfig, SystemConfig
from ..models.device import Device
from ..models.sensor import DeviceClass, Sensor, StateClass, create_sensor
from .base import Collector, CollectorResult


def _get_system_info() -> dict[str, str | None]:
    """
    Get basic system information for device auto-creation.

    Returns:
        Dictionary with hostname, manufacturer, model, os, kernel
    """
    info: dict[str, str | None] = {
        "hostname": None,
        "manufacturer": None,
        "model": None,
        "os": None,
        "kernel": None,
    }

    # Hostname
    try:
        info["hostname"] = socket.gethostname()
    except Exception:
        info["hostname"] = platform.node() or "linux"

    # Try to get hardware info from DMI (requires root or readable files)
    dmi_paths = {
        "manufacturer": [
            "/sys/class/dmi/id/sys_vendor",
            "/sys/class/dmi/id/board_vendor",
            "/sys/class/dmi/id/chassis_vendor",
        ],
        "model": [
            "/sys/class/dmi/id/product_name",
            "/sys/class/dmi/id/board_name",
        ],
    }

    for key, paths in dmi_paths.items():
        for path in paths:
            try:
                value = Path(path).read_text().strip()
                if value and value.lower() not in ("", "to be filled by o.e.m.", "default string"):
                    info[key] = value
                    break
            except Exception:
                continue

    # Try device-tree model (for ARM SBCs like Raspberry Pi, Orange Pi)
    if not info["model"]:
        try:
            model = Path("/proc/device-tree/model").read_text().strip().rstrip("\x00")
            if model:
                info["model"] = model
        except Exception:
            pass

    # Extract manufacturer from model if not set
    if info["model"] and not info["manufacturer"]:
        model_lower = info["model"].lower()
        # Common patterns for SBCs
        brand_patterns = {
            "raspberry pi": "Raspberry Pi",
            "orange pi": "Orange Pi",
            "opi": "Orange Pi",  # Abbreviation in device-tree
            "banana pi": "Banana Pi",
            "rock pi": "Radxa",
            "radxa": "Radxa",
            "nvidia": "NVIDIA",
            "jetson": "NVIDIA",
            "pine64": "Pine64",
            "khadas": "Khadas",
            "odroid": "Hardkernel",
            "beaglebone": "BeagleBoard.org",
        }
        for pattern, brand in brand_patterns.items():
            if pattern in model_lower:
                info["manufacturer"] = brand
                break

    # OS info
    try:
        # Try to get pretty name from os-release
        os_release = Path("/etc/os-release")
        if os_release.exists():
            for line in os_release.read_text().splitlines():
                if line.startswith("PRETTY_NAME="):
                    info["os"] = line.split("=", 1)[1].strip('"')
                    break
        if not info["os"]:
            info["os"] = f"{platform.system()} {platform.release()}"
    except Exception:
        info["os"] = platform.system()

    # Kernel version
    try:
        info["kernel"] = platform.release()
    except Exception:
        pass

    return info


class SystemCollector(Collector):
    """
    Collector for system-wide metrics.

    Uses psutil to gather CPU, memory, swap, load, and uptime information.
    """

    SOURCE_TYPE = "system"

    def __init__(
        self,
        config: SystemConfig,
        defaults: DefaultsConfig,
        topic_prefix: str = "penguin_metrics",
        device_templates: dict[str, DeviceConfig] | None = None,
    ):
        """
        Initialize system collector.

        Args:
            config: System configuration
            defaults: Default settings
            topic_prefix: MQTT topic prefix
            device_templates: Device template definitions
        """
        super().__init__(
            name=config.name,
            collector_id=None,  # System uses fixed topic /system
            update_interval=config.update_interval or defaults.update_interval,
        )

        self.config = config
        self.defaults = defaults
        self.topic_prefix = topic_prefix
        self.device_templates = device_templates or {}

        # For CPU percent calculation
        self._last_cpu_times = None
        self._last_per_cpu_times = None

    def create_device(self) -> Device | None:
        """Create device for system metrics."""
        device_ref = self.config.device_ref

        # Handle "none" - no device
        if device_ref == "none":
            return None

        # Handle template reference
        if device_ref and device_ref not in ("system", "auto"):
            if device_ref in self.device_templates:
                template = self.device_templates[device_ref]
                return Device(
                    identifiers=template.identifiers.copy(),
                    extra_fields=template.extra_fields.copy() if template.extra_fields else {},
                )

        # Default: auto-create system device based on system info
        sys_info = _get_system_info()

        # Use hostname as device name
        device_name = sys_info["hostname"] or "System"

        # Manufacturer: from DMI/device-tree, or default
        manufacturer = sys_info["manufacturer"] or "Linux"

        # Model: from DMI/device-tree, or OS name
        model = sys_info["model"] or sys_info["os"] or "Linux System"

        # SW version: kernel version
        sw_version = sys_info["kernel"]

        return Device(
            identifiers=[f"penguin_metrics_{self.topic_prefix}_system"],
            name=device_name,
            manufacturer=manufacturer,
            model=model,
            sw_version=sw_version,
        )

    def sensor_id(self, metric: str) -> str:
        """Generate sensor ID without source name (system has no name)."""
        if metric:
            return f"penguin_metrics_{self.topic_prefix}_system_{metric}"
        return f"penguin_metrics_{self.topic_prefix}_system"

    def metric_topic(self, metric_sensor_id: str, topic_prefix: str) -> str:
        """Build topic as {prefix}/system/{metric}."""
        # metric_sensor_id is like "system_cpu_percent"
        parts = metric_sensor_id.split("_", 1)
        if len(parts) == 2:
            metric = parts[1]
            return f"{topic_prefix}/{self.SOURCE_TYPE}/{metric}"
        return f"{topic_prefix}/{self.SOURCE_TYPE}"

    def create_sensors(self) -> list[Sensor]:
        """Create sensors based on configuration."""
        sensors = []
        device = self.device

        if self.config.cpu:
            sensors.append(
                create_sensor(
                    source_type="system",
                    source_name="",  # System has no source_name - uses /system/{metric}
                    metric_name="cpu_percent",
                    display_name="CPU Usage",
                    device=device,
                    topic_prefix=self.topic_prefix,
                    unit="%",
                    state_class=StateClass.MEASUREMENT,
                    icon="mdi:chip",
                )
            )

        if self.config.cpu_per_core:
            # Create sensors for each CPU core
            cpu_count = psutil.cpu_count()
            if cpu_count:
                for i in range(cpu_count):
                    sensors.append(
                        create_sensor(
                            source_type="system",
                            source_name="",  # System has no source_name - uses /system/{metric}
                            metric_name=f"cpu{i}_percent",
                            display_name=f"CPU Core {i} Usage",
                            device=device,
                            topic_prefix=self.topic_prefix,
                            unit="%",
                            state_class=StateClass.MEASUREMENT,
                            icon="mdi:chip",
                        )
                    )

        if self.config.memory:
            sensors.extend(
                [
                    create_sensor(
                        source_type="system",
                        source_name="",  # System has no source_name - uses /system/{metric}
                        metric_name="memory_percent",
                        display_name="Memory Usage",
                        device=device,
                        topic_prefix=self.topic_prefix,
                        unit="%",
                        state_class=StateClass.MEASUREMENT,
                        icon="mdi:memory",
                    ),
                    create_sensor(
                        source_type="system",
                        source_name="",  # System has no source_name - uses /system/{metric}
                        metric_name="memory_used",
                        display_name="Memory Used",
                        device=device,
                        topic_prefix=self.topic_prefix,
                        unit="MiB",
                        device_class=DeviceClass.DATA_SIZE,
                        state_class=StateClass.MEASUREMENT,
                        icon="mdi:memory",
                    ),
                    create_sensor(
                        source_type="system",
                        source_name="",  # System has no source_name - uses /system/{metric}
                        metric_name="memory_total",
                        display_name="Memory Total",
                        device=device,
                        topic_prefix=self.topic_prefix,
                        unit="MiB",
                        device_class=DeviceClass.DATA_SIZE,
                        state_class=StateClass.MEASUREMENT,
                        icon="mdi:memory",
                    ),
                ]
            )

        if self.config.swap:
            sensors.extend(
                [
                    create_sensor(
                        source_type="system",
                        source_name="",  # System has no source_name - uses /system/{metric}
                        metric_name="swap_percent",
                        display_name="Swap Usage",
                        device=device,
                        topic_prefix=self.topic_prefix,
                        unit="%",
                        state_class=StateClass.MEASUREMENT,
                        icon="mdi:harddisk",
                    ),
                    create_sensor(
                        source_type="system",
                        source_name="",  # System has no source_name - uses /system/{metric}
                        metric_name="swap_used",
                        display_name="Swap Used",
                        device=device,
                        topic_prefix=self.topic_prefix,
                        unit="MiB",
                        device_class=DeviceClass.DATA_SIZE,
                        state_class=StateClass.MEASUREMENT,
                        icon="mdi:harddisk",
                    ),
                ]
            )

        if self.config.load:
            sensors.extend(
                [
                    create_sensor(
                        source_type="system",
                        source_name="",  # System has no source_name - uses /system/{metric}
                        metric_name="load_1m",
                        display_name="Load Average (1m)",
                        device=device,
                        topic_prefix=self.topic_prefix,
                        state_class=StateClass.MEASUREMENT,
                        icon="mdi:gauge",
                    ),
                    create_sensor(
                        source_type="system",
                        source_name="",  # System has no source_name - uses /system/{metric}
                        metric_name="load_5m",
                        display_name="Load Average (5m)",
                        device=device,
                        topic_prefix=self.topic_prefix,
                        state_class=StateClass.MEASUREMENT,
                        icon="mdi:gauge",
                    ),
                    create_sensor(
                        source_type="system",
                        source_name="",  # System has no source_name - uses /system/{metric}
                        metric_name="load_15m",
                        display_name="Load Average (15m)",
                        device=device,
                        topic_prefix=self.topic_prefix,
                        state_class=StateClass.MEASUREMENT,
                        icon="mdi:gauge",
                    ),
                ]
            )

        if self.config.uptime:
            sensors.append(
                create_sensor(
                    source_type="system",
                    source_name="",  # System has no source_name - uses /system/{metric}
                    metric_name="uptime",
                    display_name="Uptime",
                    device=device,
                    topic_prefix=self.topic_prefix,
                    unit="s",
                    device_class=DeviceClass.DURATION,
                    state_class=StateClass.TOTAL_INCREASING,
                    icon="mdi:clock-outline",
                )
            )

        return sensors

    async def collect(self) -> CollectorResult:
        """Collect system metrics."""
        result = CollectorResult()

        # CPU usage
        if self.config.cpu:
            cpu_percent = psutil.cpu_percent(interval=None)
            result.set("cpu_percent", round(cpu_percent, 1))

        if self.config.cpu_per_core:
            per_cpu = psutil.cpu_percent(interval=None, percpu=True)
            for i, percent in enumerate(per_cpu):
                result.set(f"cpu{i}_percent", round(percent, 1))

        # Memory
        if self.config.memory:
            mem = psutil.virtual_memory()
            result.set("memory_percent", round(mem.percent, 1))
            result.set("memory_used", round(mem.used / (1024 * 1024), 1))
            result.set("memory_total", round(mem.total / (1024 * 1024), 1))

        # Swap
        if self.config.swap:
            swap = psutil.swap_memory()
            result.set("swap_percent", round(swap.percent, 1))
            result.set("swap_used", round(swap.used / (1024 * 1024), 1))

        # Load average
        if self.config.load:
            try:
                load1, load5, load15 = psutil.getloadavg()
                result.set("load_1m", round(load1, 2))
                result.set("load_5m", round(load5, 2))
                result.set("load_15m", round(load15, 2))
            except (OSError, AttributeError):
                # Not available on all platforms
                pass

        # Uptime
        if self.config.uptime:
            boot_time = psutil.boot_time()
            uptime_seconds = int(datetime.now().timestamp() - boot_time)
            result.set("uptime", uptime_seconds)

        # System collector doesn't have state - uses global status
        return result
