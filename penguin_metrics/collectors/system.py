"""
System-wide metrics collector.

Collects:
- CPU usage (overall and per-core)
- Memory usage (total, used, available, percent)
- Swap usage
- Load average (1, 5, 15 minutes)
- Uptime
"""

import psutil
from datetime import datetime

from .base import Collector, CollectorResult
from ..models.device import Device
from ..models.sensor import Sensor, DeviceClass, StateClass, create_sensor
from ..config.schema import SystemConfig, DefaultsConfig


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
    ):
        """
        Initialize system collector.
        
        Args:
            config: System configuration
            defaults: Default settings
            topic_prefix: MQTT topic prefix
        """
        super().__init__(
            name=config.name,
            collector_id=config.id,
            update_interval=config.update_interval or defaults.update_interval,
        )
        
        self.config = config
        self.defaults = defaults
        self.topic_prefix = topic_prefix
        
        # For CPU percent calculation
        self._last_cpu_times = None
        self._last_per_cpu_times = None
    
    def create_device(self) -> Device:
        """Create device for system metrics."""
        device_config = self.config.device
        
        return Device(
            identifiers=["system"],
            name=device_config.name or "System",
            manufacturer=device_config.manufacturer,
            model=device_config.model,
            hw_version=device_config.hw_version,
            sw_version=device_config.sw_version,
        )
    
    def sensor_id(self, metric: str) -> str:
        """Generate sensor ID without source name (system has no name)."""
        if metric:
            return f"{self.SOURCE_TYPE}_{metric}"
        return self.SOURCE_TYPE
    
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
            sensors.append(create_sensor(
                source_type="system",
                source_name="",  # System has no source_name - uses /system/{metric}
                metric_name="cpu_percent",
                display_name="CPU Usage",
                device=device,
                topic_prefix=self.topic_prefix,
                unit="%",
                state_class=StateClass.MEASUREMENT,
                icon="mdi:chip",
            ))
        
        if self.config.cpu_per_core:
            # Create sensors for each CPU core
            cpu_count = psutil.cpu_count()
            if cpu_count:
                for i in range(cpu_count):
                    sensors.append(create_sensor(
                        source_type="system",
                source_name="",  # System has no source_name - uses /system/{metric}
                        metric_name=f"cpu{i}_percent",
                        display_name=f"CPU Core {i} Usage",
                        device=device,
                        topic_prefix=self.topic_prefix,
                        unit="%",
                        state_class=StateClass.MEASUREMENT,
                        icon="mdi:chip",
                        enabled_by_default=False,  # Disabled by default to reduce clutter
                    ))
        
        if self.config.memory:
            sensors.extend([
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
                    unit="MB",
                    device_class=DeviceClass.DATA_SIZE,
                    state_class=StateClass.MEASUREMENT,
                    icon="mdi:memory",
                ),
                create_sensor(
                    source_type="system",
                source_name="",  # System has no source_name - uses /system/{metric}
                    metric_name="memory_available",
                    display_name="Memory Available",
                    device=device,
                    topic_prefix=self.topic_prefix,
                    unit="MB",
                    device_class=DeviceClass.DATA_SIZE,
                    state_class=StateClass.MEASUREMENT,
                    icon="mdi:memory",
                    enabled_by_default=False,
                ),
                create_sensor(
                    source_type="system",
                source_name="",  # System has no source_name - uses /system/{metric}
                    metric_name="memory_total",
                    display_name="Memory Total",
                    device=device,
                    topic_prefix=self.topic_prefix,
                    unit="MB",
                    device_class=DeviceClass.DATA_SIZE,
                    state_class=StateClass.MEASUREMENT,
                    icon="mdi:memory",
                    enabled_by_default=False,
                ),
            ])
        
        if self.config.swap:
            sensors.extend([
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
                    unit="MB",
                    device_class=DeviceClass.DATA_SIZE,
                    state_class=StateClass.MEASUREMENT,
                    icon="mdi:harddisk",
                    enabled_by_default=False,
                ),
            ])
        
        if self.config.load:
            sensors.extend([
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
                    enabled_by_default=False,
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
                    enabled_by_default=False,
                ),
            ])
        
        if self.config.uptime:
            sensors.append(create_sensor(
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
            ))
        
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
            result.set("memory_available", round(mem.available / (1024 * 1024), 1))
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

