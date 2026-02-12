"""
System-wide metrics collector.

Collects:
- Kernel version (always)
- CPU usage (overall and per-core)
- Memory and swap (total, used, percent)
- Load average (1, 5, 15 minutes)
- Uptime and boot time
- Disk I/O (bytes and KiB/s rate)
- CPU frequency (current/min/max MHz; N/A on some ARM/virtual)
- Process count (total and running)
"""

import platform
import socket
from datetime import datetime, timezone
from pathlib import Path

import psutil

from ..config.schema import DefaultsConfig, DeviceConfig, SystemConfig
from ..models.device import Device
from ..models.sensor import DeviceClass, Sensor, StateClass
from .base import Collector, CollectorResult, build_sensor


def _calc_rate_kib(
    current: float,
    previous: float | None,
    time_delta: float | None,
) -> float | None:
    """Calculate KiB/s rate from bytes and time delta."""
    if previous is None or time_delta is None or time_delta <= 0:
        return None
    return max(0.0, (current - previous) / 1024 / time_delta)


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

        # For disk I/O rate (KiB/s)
        self._prev_disk_read: float | None = None
        self._prev_disk_write: float | None = None
        self._prev_disk_timestamp: datetime | None = None

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
        ha_cfg = getattr(self.config, "ha_config", None)

        def add_sensor(
            metric: str,
            display: str,
            *,
            unit: str | None = None,
            device_class: DeviceClass | None = None,
            state_class: StateClass | None = None,
            icon: str | None = None,
            suggested_display_precision: int | None = None,
        ) -> None:
            sensors.append(
                build_sensor(
                    source_type="system",
                    source_name="",
                    metric_name=metric,
                    display_name=display,
                    device=device,
                    topic_prefix=self.topic_prefix,
                    unit=unit,
                    device_class=device_class,
                    state_class=state_class,
                    icon=icon,
                    ha_config=ha_cfg,
                    suggested_display_precision=suggested_display_precision,
                )
            )

        # Kernel version is always exposed (cannot be disabled)
        sensors.append(
            build_sensor(
                source_type="system",
                source_name="",
                metric_name="kernel_version",
                display_name="Kernel Version",
                device=device,
                topic_prefix=self.topic_prefix,
                icon="mdi:linux",
                ha_config=ha_cfg,
            )
        )

        if self.config.cpu:
            add_sensor(
                "cpu_percent",
                "CPU Usage",
                unit="%",
                state_class=StateClass.MEASUREMENT,
                icon="mdi:chip",
            )

        if self.config.cpu_per_core:
            # Create sensors for each CPU core
            cpu_count = psutil.cpu_count()
            if cpu_count:
                for i in range(cpu_count):
                    add_sensor(
                        f"cpu{i}_percent",
                        f"CPU Core {i} Usage",
                        unit="%",
                        state_class=StateClass.MEASUREMENT,
                        icon="mdi:chip",
                    )

        if self.config.memory:
            sensors.extend(
                [
                    build_sensor(
                        source_type="system",
                        source_name="",  # System has no source_name - uses /system/{metric}
                        metric_name="memory_percent",
                        display_name="Memory Usage",
                        device=device,
                        topic_prefix=self.topic_prefix,
                        unit="%",
                        state_class=StateClass.MEASUREMENT,
                        icon="mdi:memory",
                        ha_config=ha_cfg,
                    ),
                    build_sensor(
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
                        ha_config=ha_cfg,
                    ),
                    build_sensor(
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
                        ha_config=ha_cfg,
                    ),
                ]
            )

        if self.config.swap:
            sensors.extend(
                [
                    build_sensor(
                        source_type="system",
                        source_name="",  # System has no source_name - uses /system/{metric}
                        metric_name="swap_percent",
                        display_name="Swap Usage",
                        device=device,
                        topic_prefix=self.topic_prefix,
                        unit="%",
                        state_class=StateClass.MEASUREMENT,
                        icon="mdi:harddisk",
                        ha_config=ha_cfg,
                    ),
                    build_sensor(
                        source_type="system",
                        source_name="",
                        metric_name="swap_used",
                        display_name="Swap Used",
                        device=device,
                        topic_prefix=self.topic_prefix,
                        unit="MiB",
                        device_class=DeviceClass.DATA_SIZE,
                        state_class=StateClass.MEASUREMENT,
                        icon="mdi:harddisk",
                        ha_config=ha_cfg,
                        suggested_display_precision=1,
                    ),
                    build_sensor(
                        source_type="system",
                        source_name="",
                        metric_name="swap_total",
                        display_name="Swap Total",
                        device=device,
                        topic_prefix=self.topic_prefix,
                        unit="MiB",
                        device_class=DeviceClass.DATA_SIZE,
                        state_class=StateClass.MEASUREMENT,
                        icon="mdi:harddisk",
                        ha_config=ha_cfg,
                        suggested_display_precision=1,
                    ),
                ]
            )

        if self.config.disk_io:
            add_sensor(
                "disk_read",
                "Disk Read",
                unit="B",
                device_class=DeviceClass.DATA_SIZE,
                state_class=StateClass.TOTAL_INCREASING,
                icon="mdi:harddisk",
                suggested_display_precision=0,
            )
            add_sensor(
                "disk_write",
                "Disk Write",
                unit="B",
                device_class=DeviceClass.DATA_SIZE,
                state_class=StateClass.TOTAL_INCREASING,
                icon="mdi:harddisk",
                suggested_display_precision=0,
            )
        if self.config.disk_io_rate:
            add_sensor(
                "disk_read_rate",
                "Disk Read Rate",
                unit="KiB/s",
                device_class=DeviceClass.DATA_RATE,
                state_class=StateClass.MEASUREMENT,
                icon="mdi:harddisk",
                suggested_display_precision=2,
            )
            add_sensor(
                "disk_write_rate",
                "Disk Write Rate",
                unit="KiB/s",
                device_class=DeviceClass.DATA_RATE,
                state_class=StateClass.MEASUREMENT,
                icon="mdi:harddisk",
                suggested_display_precision=2,
            )

        if self.config.cpu_freq and psutil.cpu_freq() is not None:
            add_sensor(
                "cpu_freq_current",
                "CPU Frequency",
                unit="MHz",
                state_class=StateClass.MEASUREMENT,
                icon="mdi:chip",
                suggested_display_precision=0,
            )
            add_sensor(
                "cpu_freq_min",
                "CPU Frequency Min",
                unit="MHz",
                state_class=StateClass.MEASUREMENT,
                icon="mdi:chip",
                suggested_display_precision=0,
            )
            add_sensor(
                "cpu_freq_max",
                "CPU Frequency Max",
                unit="MHz",
                state_class=StateClass.MEASUREMENT,
                icon="mdi:chip",
                suggested_display_precision=0,
            )

        if self.config.process_count:
            add_sensor(
                "process_count_total",
                "Process Count Total",
                state_class=StateClass.MEASUREMENT,
                icon="mdi:counter",
                suggested_display_precision=0,
            )
            add_sensor(
                "process_count_running",
                "Process Count Running",
                state_class=StateClass.MEASUREMENT,
                icon="mdi:counter",
                suggested_display_precision=0,
            )

        if self.config.boot_time:
            sensors.append(
                build_sensor(
                    source_type="system",
                    source_name="",
                    metric_name="boot_time",
                    display_name="Boot Time",
                    device=device,
                    topic_prefix=self.topic_prefix,
                    icon="mdi:clock-outline",
                    ha_config=ha_cfg,
                    device_class=DeviceClass.TIMESTAMP,
                )
            )

        if self.config.load:
            sensors.extend(
                [
                    build_sensor(
                        source_type="system",
                        source_name="",  # System has no source_name - uses /system/{metric}
                        metric_name="load_1m",
                        display_name="Load Average (1m)",
                        device=device,
                        topic_prefix=self.topic_prefix,
                        state_class=StateClass.MEASUREMENT,
                        icon="mdi:gauge",
                        ha_config=ha_cfg,
                    ),
                    build_sensor(
                        source_type="system",
                        source_name="",  # System has no source_name - uses /system/{metric}
                        metric_name="load_5m",
                        display_name="Load Average (5m)",
                        device=device,
                        topic_prefix=self.topic_prefix,
                        state_class=StateClass.MEASUREMENT,
                        icon="mdi:gauge",
                        ha_config=ha_cfg,
                    ),
                    build_sensor(
                        source_type="system",
                        source_name="",  # System has no source_name - uses /system/{metric}
                        metric_name="load_15m",
                        display_name="Load Average (15m)",
                        device=device,
                        topic_prefix=self.topic_prefix,
                        state_class=StateClass.MEASUREMENT,
                        icon="mdi:gauge",
                        ha_config=ha_cfg,
                    ),
                ]
            )

        if self.config.uptime:
            add_sensor(
                "uptime",
                "Uptime",
                unit="s",
                device_class=DeviceClass.DURATION,
                state_class=StateClass.TOTAL_INCREASING,
                icon="mdi:clock-outline",
            )

        return sensors

    async def collect(self) -> CollectorResult:
        """Collect system metrics."""
        result = CollectorResult()

        # Kernel version is always collected (cannot be disabled)
        try:
            result.set("kernel_version", platform.release())
        except Exception:
            result.set("kernel_version", "unknown")

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
            result.set("swap_total", round(swap.total / (1024 * 1024), 1))

        # Disk I/O (system-wide)
        if self.config.disk_io or self.config.disk_io_rate:
            io = psutil.disk_io_counters()
            if io is not None:
                read_bytes = io.read_bytes
                write_bytes = io.write_bytes
                if self.config.disk_io:
                    result.set("disk_read", read_bytes)
                    result.set("disk_write", write_bytes)
                now = datetime.now()
                if self.config.disk_io_rate:
                    time_delta = None
                    if self._prev_disk_timestamp is not None:
                        time_delta = (now - self._prev_disk_timestamp).total_seconds()
                    read_rate = _calc_rate_kib(read_bytes, self._prev_disk_read, time_delta)
                    write_rate = _calc_rate_kib(write_bytes, self._prev_disk_write, time_delta)
                    if read_rate is not None:
                        result.set("disk_read_rate", round(read_rate, 2))
                    if write_rate is not None:
                        result.set("disk_write_rate", round(write_rate, 2))
                self._prev_disk_read = float(read_bytes)
                self._prev_disk_write = float(write_bytes)
                self._prev_disk_timestamp = now

        # CPU frequency (may be None on ARM/virtual)
        if self.config.cpu_freq:
            freq = psutil.cpu_freq()
            if freq is not None:
                result.set("cpu_freq_current", round(freq.current, 0))
                if freq.min is not None:
                    result.set("cpu_freq_min", round(freq.min, 0))
                if freq.max is not None:
                    result.set("cpu_freq_max", round(freq.max, 0))

        # Process count
        if self.config.process_count:
            try:
                total = len(psutil.pids())
                running = sum(
                    1
                    for p in psutil.process_iter(attrs=["status"], ad_value=None)
                    if p.info.get("status") == "running"
                )
                result.set("process_count_total", total)
                result.set("process_count_running", running)
            except (psutil.Error, AttributeError):
                pass

        # Boot time (ISO string for HA timestamp)
        if self.config.boot_time:
            try:
                bt = psutil.boot_time()
                boot_dt = datetime.fromtimestamp(bt, tz=timezone.utc)
                result.set("boot_time", boot_dt.isoformat())
            except (OSError, ValueError):
                pass

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
