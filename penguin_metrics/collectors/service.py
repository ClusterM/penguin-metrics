"""
Systemd service monitoring collector.

Monitors systemd services and collects metrics from their cgroups.
Supports aggregating metrics across all processes in a service.

Collects:
- Service state (active, inactive, failed, etc.)
- CPU usage (from cgroup)
- Memory usage (from cgroup)
- PSS/USS if smaps enabled
- Restart count
"""

import asyncio
import fnmatch
import time

import psutil

from ..config.schema import DefaultsConfig, DeviceConfig, ServiceConfig, ServiceMatchType
from ..models.device import Device, create_device_from_ref
from ..models.sensor import DeviceClass, Sensor, StateClass
from ..utils.cgroup import (
    get_cgroup_pids,
    get_cgroup_stats,
    get_systemd_service_cgroup,
)
from ..utils.smaps import aggregate_smaps
from .base import Collector, CollectorResult, build_sensor


async def run_systemctl(*args: str) -> tuple[int, str]:
    """
    Run systemctl command asynchronously.

    Returns:
        Tuple of (exit_code, output)
    """
    proc = await asyncio.create_subprocess_exec(
        "systemctl",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    return proc.returncode or 0, stdout.decode().strip()


async def get_service_property(unit: str, prop: str) -> str | None:
    """
    Get a property value from systemctl show.

    Args:
        unit: Unit name
        prop: Property name

    Returns:
        Property value or None
    """
    code, output = await run_systemctl("show", "-p", prop, "--value", unit)
    if code == 0 and output:
        return output
    return None


async def get_service_state(unit: str) -> str:
    """
    Get the active state of a service.

    Args:
        unit: Unit name

    Returns:
        State string (active, inactive, failed, etc.)
    """
    state = await get_service_property(unit, "ActiveState")
    return state or "unknown"


async def get_service_main_pid(unit: str) -> int | None:
    """
    Get the main PID of a service.

    Args:
        unit: Unit name

    Returns:
        Main PID or None
    """
    pid_str = await get_service_property(unit, "MainPID")
    if pid_str:
        try:
            pid = int(pid_str)
            return pid if pid > 0 else None
        except ValueError:
            pass
    return None


async def get_service_restart_count(unit: str) -> int:
    """
    Get the restart count of a service.

    Args:
        unit: Unit name

    Returns:
        Number of restarts
    """
    count_str = await get_service_property(unit, "NRestarts")
    if count_str:
        try:
            return int(count_str)
        except ValueError:
            pass
    return 0


async def list_units(pattern: str = "*.service") -> list[str]:
    """
    List systemd units matching a pattern.

    Args:
        pattern: Glob pattern for unit names

    Returns:
        List of matching unit names
    """
    code, output = await run_systemctl(
        "list-units",
        "--type=service",
        "--no-legend",
        "--no-pager",
    )

    if code != 0:
        return []

    units = []
    for line in output.splitlines():
        parts = line.split()
        if parts:
            unit = parts[0]
            if fnmatch.fnmatch(unit, pattern):
                units.append(unit)

    return units


class ServiceCollector(Collector):
    SOURCE_TYPE = "service"
    """
    Collector for systemd service metrics.

    Monitors a systemd service and collects metrics from its cgroup
    and individual processes.
    """

    def __init__(
        self,
        config: ServiceConfig,
        defaults: DefaultsConfig,
        topic_prefix: str = "penguin_metrics",
        device_templates: dict[str, DeviceConfig] | None = None,
        parent_device: Device | None = None,
    ):
        """
        Initialize service collector.

        Args:
            config: Service configuration
            defaults: Default settings
            topic_prefix: MQTT topic prefix
            device_templates: Device template definitions
            parent_device: System device (for device_ref="system")
        """
        super().__init__(
            name=config.name,
            collector_id=config.id or config.name,
            update_interval=config.update_interval or defaults.update_interval,
        )

        self.config = config
        self.defaults = defaults
        self.topic_prefix = topic_prefix
        self.device_templates = device_templates or {}
        self.parent_device = parent_device
        self.use_smaps = config.should_use_smaps(defaults)

        # Resolved unit name
        self._unit_name: str | None = None
        self._cgroup_path: str | None = None
        self._service_state = "unknown"

        # For CPU percent calculation (delta-based)
        self._last_cpu_usec: int = 0
        self._last_cpu_time: float = 0.0
        self._last_disk_bytes: tuple[int, int] | None = None
        self._last_disk_time: float | None = None

    async def initialize(self) -> None:
        """Resolve the service unit name."""
        if self.config.match:
            if self.config.match.type == ServiceMatchType.UNIT:
                self._unit_name = self.config.match.value
            elif self.config.match.type == ServiceMatchType.PATTERN:
                # Find first matching unit
                units = await list_units(self.config.match.value)
                if units:
                    self._unit_name = units[0]

        if self._unit_name and not self._unit_name.endswith(".service"):
            self._unit_name = f"{self._unit_name}.service"

        if self._unit_name:
            self._cgroup_path = get_systemd_service_cgroup(self._unit_name)

        await super().initialize()

    def create_device(self) -> Device | None:
        """Create device for service metrics."""
        unit = self._unit_name or self.config.name
        return create_device_from_ref(
            device_ref=self.config.device_ref,
            source_type=self.SOURCE_TYPE,
            collector_id=self.collector_id,
            topic_prefix=self.topic_prefix,
            default_name=f"Service: {unit}",
            manufacturer="Penguin Metrics",
            model="Systemd Service",
            parent_device=self.parent_device,
            device_templates=self.device_templates,
        )

    def create_sensors(self) -> list[Sensor]:
        """Create sensors based on configuration."""
        sensors = []
        device = self.device

        # Service sensors use short names - device name provides context
        if self.config.state:
            sensors.append(
                build_sensor(
                    source_type="service",
                    source_name=self.name,
                    metric_name="state",
                    display_name="State",
                    device=device,
                    topic_prefix=self.topic_prefix,
                    icon="mdi:cog",
                    ha_config=self.config.ha_config,
                )
            )

        if self.config.restart_count:
            sensors.append(
                build_sensor(
                    source_type="service",
                    source_name=self.name,
                    metric_name="restarts",
                    display_name="Restart Count",
                    device=device,
                    topic_prefix=self.topic_prefix,
                    state_class=StateClass.TOTAL_INCREASING,
                    icon="mdi:restart",
                    ha_config=self.config.ha_config,
                )
            )

        if self.config.cpu:
            sensors.append(
                build_sensor(
                    source_type="service",
                    source_name=self.name,
                    metric_name="cpu_percent",
                    display_name="CPU",
                    device=device,
                    topic_prefix=self.topic_prefix,
                    unit="%",
                    state_class=StateClass.MEASUREMENT,
                    icon="mdi:chip",
                    ha_config=self.config.ha_config,
                )
            )

        if self.config.memory:
            sensors.extend(
                [
                    build_sensor(
                        source_type="service",
                        source_name=self.name,
                        metric_name="memory",
                        display_name="Memory Cgroup",
                        device=device,
                        topic_prefix=self.topic_prefix,
                        unit="MiB",
                        device_class=DeviceClass.DATA_SIZE,
                        state_class=StateClass.MEASUREMENT,
                        icon="mdi:memory",
                        ha_config=self.config.ha_config,
                    ),
                    build_sensor(
                        source_type="service",
                        source_name=self.name,
                        metric_name="memory_cache",
                        display_name="Cache",
                        device=device,
                        topic_prefix=self.topic_prefix,
                        unit="MiB",
                        device_class=DeviceClass.DATA_SIZE,
                        state_class=StateClass.MEASUREMENT,
                        icon="mdi:memory",
                        ha_config=self.config.ha_config,
                    ),
                ]
            )

        if self.use_smaps:
            sensors.extend(
                [
                    build_sensor(
                        source_type="service",
                        source_name=self.name,
                        metric_name="memory_pss",
                        display_name="Memory PSS",
                        device=device,
                        topic_prefix=self.topic_prefix,
                        unit="MiB",
                        device_class=DeviceClass.DATA_SIZE,
                        state_class=StateClass.MEASUREMENT,
                        icon="mdi:memory",
                        ha_config=self.config.ha_config,
                    ),
                    build_sensor(
                        source_type="service",
                        source_name=self.name,
                        metric_name="memory_uss",
                        display_name="Memory USS",
                        device=device,
                        topic_prefix=self.topic_prefix,
                        unit="MiB",
                        device_class=DeviceClass.DATA_SIZE,
                        state_class=StateClass.MEASUREMENT,
                        icon="mdi:memory",
                        ha_config=self.config.ha_config,
                    ),
                ]
            )

        if self.config.disk:
            sensors.extend(
                [
                    build_sensor(
                        source_type="service",
                        source_name=self.name,
                        metric_name="disk_read",
                        display_name="Disk Read",
                        device=device,
                        topic_prefix=self.topic_prefix,
                        unit="MiB",
                        device_class=DeviceClass.DATA_SIZE,
                        state_class=StateClass.TOTAL_INCREASING,
                        icon="mdi:harddisk",
                        ha_config=self.config.ha_config,
                    ),
                    build_sensor(
                        source_type="service",
                        source_name=self.name,
                        metric_name="disk_write",
                        display_name="Disk Write",
                        device=device,
                        topic_prefix=self.topic_prefix,
                        unit="MiB",
                        device_class=DeviceClass.DATA_SIZE,
                        state_class=StateClass.TOTAL_INCREASING,
                        icon="mdi:harddisk",
                        ha_config=self.config.ha_config,
                    ),
                ]
            )

        if self.config.disk_rate:
            sensors.extend(
                [
                    build_sensor(
                        source_type="service",
                        source_name=self.name,
                        metric_name="disk_read_rate",
                        display_name="Disk Read Rate",
                        device=device,
                        topic_prefix=self.topic_prefix,
                        unit="MiB/s",
                        device_class=DeviceClass.DATA_RATE,
                        state_class=StateClass.MEASUREMENT,
                        icon="mdi:harddisk",
                        ha_config=self.config.ha_config,
                    ),
                    build_sensor(
                        source_type="service",
                        source_name=self.name,
                        metric_name="disk_write_rate",
                        display_name="Disk Write Rate",
                        device=device,
                        topic_prefix=self.topic_prefix,
                        unit="MiB/s",
                        device_class=DeviceClass.DATA_RATE,
                        state_class=StateClass.MEASUREMENT,
                        icon="mdi:harddisk",
                        ha_config=self.config.ha_config,
                    ),
                ]
            )

        # Process count
        sensors.append(
            build_sensor(
                source_type="service",
                source_name=self.name,
                metric_name="processes",
                display_name="Processes",
                device=device,
                topic_prefix=self.topic_prefix,
                state_class=StateClass.MEASUREMENT,
                icon="mdi:application-outline",
                ha_config=self.config.ha_config,
            )
        )

        return sensors

    async def collect(self) -> CollectorResult:
        """Collect service metrics."""
        result = CollectorResult()

        if not self._unit_name:
            result.set_unavailable("not_found")
            return result

        # Get service state
        state = await get_service_state(self._unit_name)
        self._service_state = state
        result.set_state(state)

        # Get restart count
        if self.config.restart_count:
            restarts = await get_service_restart_count(self._unit_name)
            result.set("restarts", restarts)

        # If service is not active, skip cgroup metrics
        if self._service_state != "active":
            return result

        # Refresh cgroup path
        if not self._cgroup_path:
            self._cgroup_path = get_systemd_service_cgroup(self._unit_name)

        if not self._cgroup_path:
            return result

        # Get cgroup stats
        cg_stats = get_cgroup_stats(self._cgroup_path)

        if self.config.cpu:
            import os

            current_time = time.time()
            current_cpu_usec = cg_stats.cpu_usage_usec

            # Calculate CPU percent from delta
            cpu_percent = 0.0
            if self._last_cpu_time > 0:
                time_delta = current_time - self._last_cpu_time
                cpu_delta_usec = current_cpu_usec - self._last_cpu_usec

                if time_delta > 0 and cpu_delta_usec >= 0:
                    num_cpus = os.cpu_count() or 1
                    cpu_percent = (cpu_delta_usec / 1_000_000) / time_delta / num_cpus * 100.0
                    cpu_percent = min(cpu_percent, 100.0)

            self._last_cpu_usec = current_cpu_usec
            self._last_cpu_time = current_time
            result.set("cpu_percent", round(cpu_percent, 1))

        if self.config.memory:
            result.set("memory", round(cg_stats.memory_mb, 1))
            result.set("memory_cache", round(cg_stats.memory_cache / (1024 * 1024), 1))

        # Get PIDs for smaps and process count
        pids = get_cgroup_pids(self._cgroup_path)
        result.set("processes", len(pids))

        if (self.config.disk or self.config.disk_rate) and pids:
            total_read = 0
            total_write = 0
            for pid in pids:
                try:
                    proc = psutil.Process(pid)
                    io_counters = proc.io_counters()
                    total_read += io_counters.read_bytes
                    total_write += io_counters.write_bytes
                except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                    continue

            if self.config.disk:
                result.set("disk_read", round(total_read / (1024 * 1024), 2))
                result.set("disk_write", round(total_write / (1024 * 1024), 2))

            if self.config.disk_rate:
                now = time.time()
                if self._last_disk_bytes and self._last_disk_time:
                    prev_read, prev_write = self._last_disk_bytes
                    dt = now - self._last_disk_time
                    if dt > 0:
                        read_rate = (total_read - prev_read) / dt / (1024 * 1024)
                        write_rate = (total_write - prev_write) / dt / (1024 * 1024)
                        result.set("disk_read_rate", round(read_rate, 2))
                        result.set("disk_write_rate", round(write_rate, 2))
                self._last_disk_bytes = (total_read, total_write)
                self._last_disk_time = now

        if self.use_smaps and pids:
            smaps = aggregate_smaps(pids)
            result.set("memory_pss", round(smaps.memory_real_pss_mb, 2))
            result.set("memory_uss", round(smaps.memory_real_uss_mb, 2))

        return result
