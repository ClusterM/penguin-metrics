"""
Process monitoring collector.

Supports multiple matching strategies:
- By name: exact process name (comm)
- By pattern: regex on command line
- By PID: exact process ID
- By pidfile: read PID from a file
- By cmdline: substring match in command line

Collects:
- CPU usage
- Memory (RSS, and PSS/USS via smaps)
- I/O (read/write bytes)
- File descriptors
- Thread count
"""

import re
import time
from pathlib import Path

import psutil

from ..config.schema import DefaultsConfig, DeviceConfig, ProcessConfig, ProcessMatchType
from ..models.device import Device, create_device_from_ref
from ..models.sensor import DeviceClass, Sensor, StateClass
from ..utils.smaps import get_process_memory
from .base import (
    CollectorResult,
    MultiSourceCollector,
    build_sensor,
)


def find_processes_by_name(name: str) -> list[psutil.Process]:
    """Find processes by exact name (comm)."""
    result = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if proc.info["name"] == name:
                result.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return result


def find_processes_by_pattern(pattern: str) -> list[psutil.Process]:
    """Find processes by regex pattern on command line."""
    regex = re.compile(pattern)
    result = []
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmdline = proc.info.get("cmdline")
            if cmdline:
                cmdline_str = " ".join(cmdline)
                if regex.search(cmdline_str):
                    result.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return result


def find_process_by_pid(pid: int) -> list[psutil.Process]:
    """Find process by exact PID."""
    try:
        proc = psutil.Process(pid)
        if proc.is_running():
            return [proc]
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return []


def find_process_by_pidfile(pidfile: str) -> list[psutil.Process]:
    """Find process by reading PID from a file."""
    try:
        pid = int(Path(pidfile).read_text().strip())
        return find_process_by_pid(pid)
    except (FileNotFoundError, ValueError, PermissionError):
        return []


def find_processes_by_cmdline(substring: str) -> list[psutil.Process]:
    """Find processes by substring in command line."""
    result = []
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmdline = proc.info.get("cmdline")
            if cmdline:
                cmdline_str = " ".join(cmdline)
                if substring in cmdline_str:
                    result.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return result


class ProcessCollector(MultiSourceCollector):
    """
    Collector for process metrics.

    Monitors one or more processes based on matching configuration.
    Supports aggregation for multiple matching processes.
    """

    SOURCE_TYPE = "process"

    def __init__(
        self,
        config: ProcessConfig,
        defaults: DefaultsConfig,
        topic_prefix: str = "penguin_metrics",
        device_templates: dict[str, DeviceConfig] | None = None,
        parent_device: Device | None = None,
    ):
        """
        Initialize process collector.

        Args:
            config: Process configuration
            defaults: Default settings
            topic_prefix: MQTT topic prefix
            device_templates: Device template definitions
            parent_device: System device (for device_ref="system")
        """
        super().__init__(
            name=config.name,
            collector_id=config.name,
            update_interval=config.update_interval or defaults.update_interval,
            aggregate=config.aggregate,
        )

        self.config = config
        self.defaults = defaults
        self.topic_prefix = topic_prefix
        self.device_templates = device_templates or {}
        self.parent_device = parent_device
        self.use_smaps = config.should_use_smaps(defaults)

        # Cached process info
        self._processes: list[psutil.Process] = []
        self._process_state = "unknown"  # running, not_found, error
        self._prev_pid_io: dict[int, tuple[int, int, float]] = {}
        self._prev_agg_io: tuple[int, int] | None = None
        self._prev_agg_time: float | None = None

    def create_device(self) -> Device | None:
        """Create device for process metrics."""
        return create_device_from_ref(
            device_ref=self.config.device_ref,
            source_type=self.SOURCE_TYPE,
            collector_id=self.collector_id,
            topic_prefix=self.topic_prefix,
            default_name=f"Process: {self.config.name}",
            manufacturer="Penguin Metrics",
            model="Process Monitor",
            parent_device=self.parent_device,
            device_templates=self.device_templates,
        )

    def create_sensors(self) -> list[Sensor]:
        """Create sensors based on configuration."""
        sensors = []
        device = self.device

        # Process sensors use short names - device name provides context
        sensors.append(
            build_sensor(
                source_type="process",
                source_name=self.name,
                metric_name="state",
                display_name="State",
                device=device,
                topic_prefix=self.topic_prefix,
                icon="mdi:application",
                ha_config=self.config.ha_config,
            )
        )

        # Process count (for aggregate mode)
        if self.config.aggregate:
            sensors.append(
                build_sensor(
                    source_type="process",
                    source_name=self.name,
                    metric_name="count",
                    display_name="Process Count",
                    device=device,
                    topic_prefix=self.topic_prefix,
                    state_class=StateClass.MEASUREMENT,
                    icon="mdi:counter",
                    ha_config=self.config.ha_config,
                )
            )

        if self.config.cpu:
            sensors.append(
                build_sensor(
                    source_type="process",
                    source_name=self.name,
                    metric_name="cpu_percent",
                    display_name="CPU Usage",
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
                        source_type="process",
                        source_name=self.name,
                        metric_name="memory_rss",
                        display_name="Memory RSS",
                        device=device,
                        topic_prefix=self.topic_prefix,
                        unit="MiB",
                        device_class=DeviceClass.DATA_SIZE,
                        state_class=StateClass.MEASUREMENT,
                        icon="mdi:memory",
                        ha_config=self.config.ha_config,
                    ),
                    build_sensor(
                        source_type="process",
                        source_name=self.name,
                        metric_name="memory_percent",
                        display_name="Memory Usage",
                        device=device,
                        topic_prefix=self.topic_prefix,
                        unit="%",
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
                        source_type="process",
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
                        source_type="process",
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
                        source_type="process",
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
                        source_type="process",
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
                        source_type="process",
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
                        source_type="process",
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

        if self.config.fds:
            sensors.append(
                build_sensor(
                    source_type="process",
                    source_name=self.name,
                    metric_name="num_fds",
                    display_name="Open Files",
                    device=device,
                    topic_prefix=self.topic_prefix,
                    state_class=StateClass.MEASUREMENT,
                    icon="mdi:file-multiple",
                    ha_config=self.config.ha_config,
                )
            )

        if self.config.threads:
            sensors.append(
                build_sensor(
                    source_type="process",
                    source_name=self.name,
                    metric_name="num_threads",
                    display_name="Threads",
                    device=device,
                    topic_prefix=self.topic_prefix,
                    state_class=StateClass.MEASUREMENT,
                    icon="mdi:cpu-64-bit",
                    ha_config=self.config.ha_config,
                )
            )

        return sensors

    async def discover_sources(self) -> list[psutil.Process]:
        """Find processes matching the configuration."""
        if self.config.match is None:
            return []

        match_type = self.config.match.type
        match_value = self.config.match.value

        if match_type == ProcessMatchType.NAME:
            processes = find_processes_by_name(str(match_value))
        elif match_type == ProcessMatchType.PATTERN:
            processes = find_processes_by_pattern(str(match_value))
        elif match_type == ProcessMatchType.PID:
            processes = find_process_by_pid(int(match_value))
        elif match_type == ProcessMatchType.PIDFILE:
            processes = find_process_by_pidfile(str(match_value))
        elif match_type == ProcessMatchType.CMDLINE:
            processes = find_processes_by_cmdline(str(match_value))
        else:
            processes = []

        self._processes = processes
        self._process_state = "running" if processes else "not_found"

        return processes

    async def collect_from_source(self, source: psutil.Process) -> CollectorResult:
        """Collect metrics from a single process."""
        result = CollectorResult()

        try:
            proc = source
            now = time.time()

            if self.config.cpu:
                try:
                    import os

                    cpu_percent = proc.cpu_percent()
                    num_cpus = os.cpu_count() or 1
                    cpu_percent = min(cpu_percent / num_cpus, 100.0)
                    result.set("cpu_percent", round(cpu_percent, 1))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            if self.config.memory:
                try:
                    mem_info = proc.memory_info()
                    mem_percent = proc.memory_percent()
                    result.set("memory_rss", round(mem_info.rss / (1024 * 1024), 1))
                    result.set("memory_percent", round(mem_percent, 1))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            if self.use_smaps:
                smaps = get_process_memory(proc.pid)
                if smaps:
                    result.set("memory_pss", round(smaps.memory_real_pss_mb, 2))
                    result.set("memory_uss", round(smaps.memory_real_uss_mb, 2))

            if self.config.disk or self.config.disk_rate:
                try:
                    io_counters = proc.io_counters()
                    read_bytes = io_counters.read_bytes
                    write_bytes = io_counters.write_bytes

                    if self.config.disk:
                        result.set("disk_read", round(read_bytes / (1024 * 1024), 2))
                        result.set("disk_write", round(write_bytes / (1024 * 1024), 2))

                    if self.config.disk_rate:
                        prev = self._prev_pid_io.get(proc.pid)
                        if prev:
                            prev_read, prev_write, prev_ts = prev
                            dt = now - prev_ts
                            if dt > 0:
                                read_rate = (read_bytes - prev_read) / dt / (1024 * 1024)
                                write_rate = (write_bytes - prev_write) / dt / (1024 * 1024)
                                result.set("disk_read_rate", round(read_rate, 2))
                                result.set("disk_write_rate", round(write_rate, 2))
                        self._prev_pid_io[proc.pid] = (read_bytes, write_bytes, now)
                except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                    pass

            if self.config.fds:
                try:
                    result.set("num_fds", proc.num_fds())
                except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                    pass

            if self.config.threads:
                try:
                    result.set("num_threads", proc.num_threads())
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            result.set_state("running")

        except psutil.NoSuchProcess:
            result.set_unavailable("not_found")
        except psutil.AccessDenied:
            result.set_error("Access denied")

        return result

    async def collect(self) -> CollectorResult:
        """Collect process metrics."""
        sources = await self.discover_sources()
        result = CollectorResult()

        if not sources:
            result.set_unavailable("not_found")
            if self.config.aggregate:
                result.set("count", 0)
            return result

        if self.config.aggregate:
            result.set("count", len(sources))

            # Aggregate metrics from all processes
            total_cpu = 0.0
            total_rss = 0.0
            total_mem_percent = 0.0
            total_pss_anon = 0.0
            total_pss_shmem = 0.0
            total_swap_pss = 0.0
            total_anonymous = 0.0
            total_disk_read_bytes = 0
            total_disk_write_bytes = 0
            total_fds = 0
            total_threads = 0
            current_time = time.time()

            for proc in sources:
                try:
                    if self.config.cpu:
                        total_cpu += proc.cpu_percent()

                    if self.config.memory:
                        mem_info = proc.memory_info()
                        total_rss += mem_info.rss
                        total_mem_percent += proc.memory_percent()

                    if self.use_smaps:
                        smaps = get_process_memory(proc.pid)
                        if smaps:
                            total_pss_anon += smaps.pss_anon
                            total_pss_shmem += smaps.pss_shmem
                            total_swap_pss += smaps.swap_pss
                            total_anonymous += smaps.anonymous

                    if self.config.disk or self.config.disk_rate:
                        try:
                            io = proc.io_counters()
                            total_disk_read_bytes += io.read_bytes
                            total_disk_write_bytes += io.write_bytes
                        except (psutil.AccessDenied, AttributeError):
                            pass

                    if self.config.fds:
                        try:
                            total_fds += proc.num_fds()
                        except (psutil.AccessDenied, AttributeError):
                            pass

                    if self.config.threads:
                        total_threads += proc.num_threads()

                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            if self.config.cpu:
                import os

                num_cpus = os.cpu_count() or 1
                total_cpu = min(total_cpu / num_cpus, 100.0)
                result.set("cpu_percent", round(total_cpu, 1))

            if self.config.memory:
                result.set("memory_rss", round(total_rss / (1024 * 1024), 1))
                result.set("memory_percent", round(total_mem_percent, 1))

            if self.use_smaps:
                # Calculate real PSS (excluding file-backed mappings)
                if total_pss_anon > 0 or total_pss_shmem > 0:
                    memory_real_pss = (total_pss_anon + total_pss_shmem + total_swap_pss) / (
                        1024 * 1024
                    )
                else:
                    # Fallback: if breakdown not available, we can't calculate real PSS
                    # This shouldn't happen if smaps_rollup is used
                    memory_real_pss = 0.0
                result.set("memory_pss", round(memory_real_pss, 2))
                result.set("memory_uss", round(total_anonymous / (1024 * 1024), 2))

            if self.config.disk:
                result.set("disk_read", round(total_disk_read_bytes / (1024 * 1024), 2))
                result.set("disk_write", round(total_disk_write_bytes / (1024 * 1024), 2))

            if self.config.disk_rate:
                if self._prev_agg_io and self._prev_agg_time:
                    prev_read, prev_write = self._prev_agg_io
                    dt = current_time - self._prev_agg_time
                    if dt > 0:
                        read_rate = (total_disk_read_bytes - prev_read) / dt / (1024 * 1024)
                        write_rate = (total_disk_write_bytes - prev_write) / dt / (1024 * 1024)
                        result.set("disk_read_rate", round(read_rate, 2))
                        result.set("disk_write_rate", round(write_rate, 2))
                self._prev_agg_io = (total_disk_read_bytes, total_disk_write_bytes)
                self._prev_agg_time = current_time

            if self.config.fds:
                result.set("num_fds", total_fds)

            if self.config.threads:
                result.set("num_threads", total_threads)

            result.set_state("running")

        else:
            # Single process (first match)
            single_result = await self.collect_from_source(sources[0])
            result.data = single_result.data
            result.state = single_result.state
            result.available = single_result.available

        return result
