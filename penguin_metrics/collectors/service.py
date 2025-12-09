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
import re
from pathlib import Path
from typing import Any
import psutil

from .base import Collector, CollectorResult
from ..models.device import Device
from ..models.sensor import Sensor, DeviceClass, StateClass, create_sensor
from ..config.schema import ServiceConfig, ServiceMatchType, DefaultsConfig
from ..utils.cgroup import (
    get_systemd_service_cgroup,
    get_cgroup_stats,
    get_cgroup_pids,
    CgroupStats,
)
from ..utils.smaps import aggregate_smaps, SmapsInfo


async def run_systemctl(*args: str) -> tuple[int, str]:
    """
    Run systemctl command asynchronously.
    
    Returns:
        Tuple of (exit_code, output)
    """
    proc = await asyncio.create_subprocess_exec(
        "systemctl", *args,
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
    ):
        """
        Initialize service collector.
        
        Args:
            config: Service configuration
            defaults: Default settings
            topic_prefix: MQTT topic prefix
        """
        super().__init__(
            name=config.name,
            collector_id=config.id or config.name,
            update_interval=config.update_interval or defaults.update_interval,
        )
        
        self.config = config
        self.defaults = defaults
        self.topic_prefix = topic_prefix
        self.use_smaps = config.should_use_smaps(defaults)
        
        # Resolved unit name
        self._unit_name: str | None = None
        self._cgroup_path: str | None = None
        self._service_state = "unknown"
        
        # For CPU percent calculation (delta-based)
        self._last_cpu_usec: int = 0
        self._last_cpu_time: float = 0.0
    
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
    
    def create_device(self) -> Device:
        """Create device for service metrics."""
        device_config = self.config.device
        unit = self._unit_name or self.config.name
        
        return Device(
            identifiers=[f"penguin_metrics_{self.topic_prefix}_service_{self.collector_id}"],
            name=device_config.name or f"Service: {unit}",
            manufacturer=device_config.manufacturer,
            model="Systemd Service",
        )
    
    def create_sensors(self) -> list[Sensor]:
        """Create sensors based on configuration."""
        sensors = []
        device = self.device
        
        if self.config.state:
            sensors.append(create_sensor(
                source_type="service",
                source_name=self.name,
                metric_name="state",
                display_name=f"{self.config.name} State",
                device=device,
                topic_prefix=self.topic_prefix,
                icon="mdi:cog",
            ))
        
        if self.config.restart_count:
            sensors.append(create_sensor(
                source_type="service",
                source_name=self.name,
                metric_name="restarts",
                display_name=f"{self.config.name} Restart Count",
                device=device,
                topic_prefix=self.topic_prefix,
                state_class=StateClass.TOTAL_INCREASING,
                icon="mdi:restart",
            ))
        
        if self.config.cpu:
            sensors.append(create_sensor(
                source_type="service",
                source_name=self.name,
                metric_name="cpu_percent",
                display_name=f"{self.config.name} CPU",
                device=device,
                topic_prefix=self.topic_prefix,
                unit="%",
                state_class=StateClass.MEASUREMENT,
                icon="mdi:chip",
            ))
        
        if self.config.memory:
            sensors.extend([
                create_sensor(
                    source_type="service",
                source_name=self.name,
                    metric_name="memory",
                    display_name=f"{self.config.name} Memory",
                    device=device,
                    topic_prefix=self.topic_prefix,
                    unit="MB",
                    device_class=DeviceClass.DATA_SIZE,
                    state_class=StateClass.MEASUREMENT,
                    icon="mdi:memory",
                ),
                create_sensor(
                    source_type="service",
                source_name=self.name,
                    metric_name="memory_cache",
                    display_name=f"{self.config.name} Cache",
                    device=device,
                    topic_prefix=self.topic_prefix,
                    unit="MB",
                    device_class=DeviceClass.DATA_SIZE,
                    state_class=StateClass.MEASUREMENT,
                    icon="mdi:memory",
                    enabled_by_default=False,
                ),
            ])
        
        if self.use_smaps:
            sensors.extend([
                create_sensor(
                    source_type="service",
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
                    source_type="service",
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
        
        # Process count
        sensors.append(create_sensor(
            source_type="service",
                source_name=self.name,
            metric_name="processes",
            display_name=f"{self.config.name} Processes",
            device=device,
            topic_prefix=self.topic_prefix,
            state_class=StateClass.MEASUREMENT,
            icon="mdi:application-outline",
            enabled_by_default=False,
        ))
        
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
            import time
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
        
        if self.use_smaps and pids:
            smaps = aggregate_smaps(pids)
            result.set("memory_pss", round(smaps.memory_real_pss_mb, 2))
            result.set("memory_uss", round(smaps.memory_real_uss_mb, 2))
        
        return result

