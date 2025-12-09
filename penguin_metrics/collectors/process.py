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
from pathlib import Path
from typing import Any
import psutil

from .base import MultiSourceCollector, CollectorResult
from ..models.device import Device
from ..models.sensor import Sensor, DeviceClass, StateClass, create_sensor
from ..config.schema import ProcessConfig, ProcessMatchType, DefaultsConfig
from ..utils.smaps import get_process_memory, SmapsInfo


def find_processes_by_name(name: str) -> list[psutil.Process]:
    """Find processes by exact name (comm)."""
    result = []
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            if proc.info['name'] == name:
                result.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return result


def find_processes_by_pattern(pattern: str) -> list[psutil.Process]:
    """Find processes by regex pattern on command line."""
    regex = re.compile(pattern)
    result = []
    for proc in psutil.process_iter(['pid', 'cmdline']):
        try:
            cmdline = proc.info.get('cmdline')
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
    for proc in psutil.process_iter(['pid', 'cmdline']):
        try:
            cmdline = proc.info.get('cmdline')
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
    ):
        """
        Initialize process collector.
        
        Args:
            config: Process configuration
            defaults: Default settings
            topic_prefix: MQTT topic prefix
        """
        super().__init__(
            name=config.name,
            collector_id=config.id or config.name,
            update_interval=config.update_interval or defaults.update_interval,
            aggregate=config.aggregate,
        )
        
        self.config = config
        self.defaults = defaults
        self.topic_prefix = topic_prefix
        self.use_smaps = config.should_use_smaps(defaults)
        
        # Cached process info
        self._processes: list[psutil.Process] = []
        self._process_state = "unknown"  # running, not_found, error
    
    def create_device(self) -> Device:
        """Create device for process metrics."""
        device_config = self.config.device
        
        return Device(
            identifiers=[f"process_{self.collector_id}"],
            name=device_config.name or f"Process: {self.config.name}",
            manufacturer=device_config.manufacturer,
            model="Process Monitor",
        )
    
    def create_sensors(self) -> list[Sensor]:
        """Create sensors based on configuration."""
        sensors = []
        device = self.device
        
        # Process state sensor
        sensors.append(create_sensor(
            source_type="process",
            source_name=self.name,
            metric_name="state",
            display_name=f"{self.config.name} State",
            device=device,
            topic_prefix=self.topic_prefix,
            icon="mdi:application",
        ))
        
        # Process count (for aggregate mode)
        if self.config.aggregate:
            sensors.append(create_sensor(
                source_type="process",
            source_name=self.name,
                metric_name="count",
                display_name=f"{self.config.name} Process Count",
                device=device,
                topic_prefix=self.topic_prefix,
                state_class=StateClass.MEASUREMENT,
                icon="mdi:counter",
            ))
        
        if self.config.cpu:
            sensors.append(create_sensor(
                source_type="process",
            source_name=self.name,
                metric_name="cpu_percent",
                display_name=f"{self.config.name} CPU Usage",
                device=device,
                topic_prefix=self.topic_prefix,
                unit="%",
                state_class=StateClass.MEASUREMENT,
                icon="mdi:chip",
            ))
        
        if self.config.memory:
            sensors.extend([
                create_sensor(
                    source_type="process",
            source_name=self.name,
                    metric_name="memory_rss",
                    display_name=f"{self.config.name} Memory RSS",
                    device=device,
                    topic_prefix=self.topic_prefix,
                    unit="MB",
                    device_class=DeviceClass.DATA_SIZE,
                    state_class=StateClass.MEASUREMENT,
                    icon="mdi:memory",
                ),
                create_sensor(
                    source_type="process",
            source_name=self.name,
                    metric_name="memory_percent",
                    display_name=f"{self.config.name} Memory Usage",
                    device=device,
                    topic_prefix=self.topic_prefix,
                    unit="%",
                    state_class=StateClass.MEASUREMENT,
                    icon="mdi:memory",
                ),
            ])
        
        if self.use_smaps:
            sensors.extend([
                create_sensor(
                    source_type="process",
            source_name=self.name,
                    metric_name="memory_pss",
                    display_name=f"{self.config.name} Memory PSS",
                    device=device,
                    topic_prefix=self.topic_prefix,
                    unit="MB",
                    device_class=DeviceClass.DATA_SIZE,
                    state_class=StateClass.MEASUREMENT,
                    icon="mdi:memory",
                ),
                create_sensor(
                    source_type="process",
            source_name=self.name,
                    metric_name="memory_uss",
                    display_name=f"{self.config.name} Memory USS",
                    device=device,
                    topic_prefix=self.topic_prefix,
                    unit="MB",
                    device_class=DeviceClass.DATA_SIZE,
                    state_class=StateClass.MEASUREMENT,
                    icon="mdi:memory",
                ),
            ])
        
        if self.config.io:
            sensors.extend([
                create_sensor(
                    source_type="process",
            source_name=self.name,
                    metric_name="io_read",
                    display_name=f"{self.config.name} I/O Read",
                    device=device,
                    topic_prefix=self.topic_prefix,
                    unit="MB",
                    device_class=DeviceClass.DATA_SIZE,
                    state_class=StateClass.TOTAL_INCREASING,
                    icon="mdi:harddisk",
                ),
                create_sensor(
                    source_type="process",
            source_name=self.name,
                    metric_name="io_write",
                    display_name=f"{self.config.name} I/O Write",
                    device=device,
                    topic_prefix=self.topic_prefix,
                    unit="MB",
                    device_class=DeviceClass.DATA_SIZE,
                    state_class=StateClass.TOTAL_INCREASING,
                    icon="mdi:harddisk",
                ),
            ])
        
        if self.config.fds:
            sensors.append(create_sensor(
                source_type="process",
            source_name=self.name,
                metric_name="num_fds",
                display_name=f"{self.config.name} Open Files",
                device=device,
                topic_prefix=self.topic_prefix,
                state_class=StateClass.MEASUREMENT,
                icon="mdi:file-multiple",
            ))
        
        if self.config.threads:
            sensors.append(create_sensor(
                source_type="process",
            source_name=self.name,
                metric_name="num_threads",
                display_name=f"{self.config.name} Threads",
                device=device,
                topic_prefix=self.topic_prefix,
                state_class=StateClass.MEASUREMENT,
                icon="mdi:cpu-64-bit",
            ))
        
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
            
            if self.config.io:
                try:
                    io_counters = proc.io_counters()
                    result.set("io_read", round(io_counters.read_bytes / (1024 * 1024), 1))
                    result.set("io_write", round(io_counters.write_bytes / (1024 * 1024), 1))
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
            total_io_read = 0.0
            total_io_write = 0.0
            total_fds = 0
            total_threads = 0
            
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
                    
                    if self.config.io:
                        try:
                            io = proc.io_counters()
                            total_io_read += io.read_bytes
                            total_io_write += io.write_bytes
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
                    memory_real_pss = (total_pss_anon + total_pss_shmem + total_swap_pss) / (1024 * 1024)
                else:
                    # Fallback: if breakdown not available, we can't calculate real PSS
                    # This shouldn't happen if smaps_rollup is used
                    memory_real_pss = 0.0
                result.set("memory_pss", round(memory_real_pss, 2))
                result.set("memory_uss", round(total_anonymous / (1024 * 1024), 2))
            
            if self.config.io:
                result.set("io_read", round(total_io_read / (1024 * 1024), 1))
                result.set("io_write", round(total_io_write / (1024 * 1024), 1))
            
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

