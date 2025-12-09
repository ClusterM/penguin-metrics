"""
Docker container monitoring collector.

Monitors Docker containers and collects metrics via Docker API.

Collects:
- Container state (running, exited, paused, etc.)
- Health status (if healthcheck defined)
- CPU usage
- Memory usage
- Network I/O
- Block I/O
"""

import fnmatch
import re
from datetime import datetime
from typing import Any

from .base import Collector, CollectorResult
from ..models.device import Device
from ..models.sensor import Sensor, DeviceClass, StateClass, create_sensor
from ..config.schema import ContainerConfig, ContainerMatchType, DefaultsConfig
from ..utils.docker_api import DockerClient, ContainerInfo, ContainerStats, DockerError


class ContainerCollector(Collector):
    
    SOURCE_TYPE = "docker"
    """
    Collector for Docker container metrics.
    
    Monitors a Docker container using the Docker API.
    """
    
    def __init__(
        self,
        config: ContainerConfig,
        defaults: DefaultsConfig,
        topic_prefix: str = "penguin_metrics",
    ):
        """
        Initialize container collector.
        
        Args:
            config: Container configuration
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
        
        # Docker client
        self.docker = DockerClient()
        
        # Matched container
        self._container: ContainerInfo | None = None
        self._container_state = "unknown"
    
    async def _find_container(self) -> ContainerInfo | None:
        """Find container matching the configuration."""
        if not self.config.match:
            return None
        
        if not self.docker.available:
            return None
        
        match_type = self.config.match.type
        match_value = self.config.match.value
        
        try:
            containers = await self.docker.list_containers(all=True)
        except DockerError:
            return None
        
        for container in containers:
            if match_type == ContainerMatchType.NAME:
                if container.name == match_value:
                    return container
            
            elif match_type == ContainerMatchType.PATTERN:
                if fnmatch.fnmatch(container.name, match_value) or \
                   re.search(match_value, container.name):
                    return container
            
            elif match_type == ContainerMatchType.IMAGE:
                if match_value in container.image:
                    return container
            
            elif match_type == ContainerMatchType.LABEL:
                # Format: "key=value" or just "key"
                if "=" in match_value:
                    key, value = match_value.split("=", 1)
                    if container.labels.get(key) == value:
                        return container
                else:
                    if match_value in container.labels:
                        return container
        
        return None
    
    async def initialize(self) -> None:
        """Find the container to monitor."""
        self._container = await self._find_container()
        await super().initialize()
    
    def create_device(self) -> Device:
        """Create device for container metrics."""
        device_config = self.config.device
        container_name = self._container.name if self._container else self.config.name
        
        return Device(
            identifiers=[f"penguin_metrics_{self.topic_prefix}_container_{self.collector_id}"],
            name=device_config.name or f"Container: {container_name}",
            manufacturer=device_config.manufacturer or "Docker",
            model="Container",
        )
    
    def create_sensors(self) -> list[Sensor]:
        """Create sensors based on configuration."""
        sensors = []
        device = self.device
        
        if self.config.state:
            sensors.append(create_sensor(
                source_type="docker",
                source_name=self.name,
                metric_name="state",
                display_name=f"{self.config.name} State",
                device=device,
                topic_prefix=self.topic_prefix,
                icon="mdi:docker",
            ))
        
        if self.config.health:
            sensors.append(create_sensor(
                source_type="docker",
                source_name=self.name,
                metric_name="health",
                display_name=f"{self.config.name} Health",
                device=device,
                topic_prefix=self.topic_prefix,
                icon="mdi:heart-pulse",
            ))
        
        if self.config.cpu:
            sensors.append(create_sensor(
                source_type="docker",
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
                    source_type="docker",
                source_name=self.name,
                    metric_name="memory_usage",
                    display_name=f"{self.config.name} Memory Usage",
                    device=device,
                    topic_prefix=self.topic_prefix,
                    unit="MB",
                    device_class=DeviceClass.DATA_SIZE,
                    state_class=StateClass.MEASUREMENT,
                    icon="mdi:memory",
                ),
                create_sensor(
                    source_type="docker",
                source_name=self.name,
                    metric_name="memory_percent",
                    display_name=f"{self.config.name} Memory %",
                    device=device,
                    topic_prefix=self.topic_prefix,
                    unit="%",
                    state_class=StateClass.MEASUREMENT,
                    icon="mdi:memory",
                ),
                create_sensor(
                    source_type="docker",
                source_name=self.name,
                    metric_name="memory_limit",
                    display_name=f"{self.config.name} Memory Limit",
                    device=device,
                    topic_prefix=self.topic_prefix,
                    unit="MB",
                    device_class=DeviceClass.DATA_SIZE,
                    state_class=StateClass.MEASUREMENT,
                    icon="mdi:memory",
                    enabled_by_default=False,
                ),
            ])
        
        if self.config.network:
            sensors.extend([
                create_sensor(
                    source_type="docker",
                source_name=self.name,
                    metric_name="network_rx",
                    display_name=f"{self.config.name} Network RX",
                    device=device,
                    topic_prefix=self.topic_prefix,
                    unit="MB",
                    device_class=DeviceClass.DATA_SIZE,
                    state_class=StateClass.TOTAL_INCREASING,
                    icon="mdi:download",
                ),
                create_sensor(
                    source_type="docker",
                source_name=self.name,
                    metric_name="network_tx",
                    display_name=f"{self.config.name} Network TX",
                    device=device,
                    topic_prefix=self.topic_prefix,
                    unit="MB",
                    device_class=DeviceClass.DATA_SIZE,
                    state_class=StateClass.TOTAL_INCREASING,
                    icon="mdi:upload",
                ),
            ])
        
        if self.config.disk:
            sensors.extend([
                create_sensor(
                    source_type="docker",
                source_name=self.name,
                    metric_name="disk_read",
                    display_name=f"{self.config.name} Disk Read",
                    device=device,
                    topic_prefix=self.topic_prefix,
                    unit="MB",
                    device_class=DeviceClass.DATA_SIZE,
                    state_class=StateClass.TOTAL_INCREASING,
                    icon="mdi:harddisk",
                ),
                create_sensor(
                    source_type="docker",
                source_name=self.name,
                    metric_name="disk_write",
                    display_name=f"{self.config.name} Disk Write",
                    device=device,
                    topic_prefix=self.topic_prefix,
                    unit="MB",
                    device_class=DeviceClass.DATA_SIZE,
                    state_class=StateClass.TOTAL_INCREASING,
                    icon="mdi:harddisk",
                ),
            ])
        
        if self.config.uptime:
            sensors.append(create_sensor(
                source_type="docker",
                source_name=self.name,
                metric_name="uptime",
                display_name=f"{self.config.name} Uptime",
                device=device,
                topic_prefix=self.topic_prefix,
                unit="s",
                device_class=DeviceClass.DURATION,
                state_class=StateClass.TOTAL_INCREASING,
                icon="mdi:clock-outline",
            ))
        
        # PIDs count
        sensors.append(create_sensor(
            source_type="docker",
                source_name=self.name,
            metric_name="pids",
            display_name=f"{self.config.name} Processes",
            device=device,
            topic_prefix=self.topic_prefix,
            state_class=StateClass.MEASUREMENT,
            icon="mdi:application-outline",
            enabled_by_default=False,
        ))
        
        return sensors
    
    async def collect(self) -> CollectorResult:
        """Collect container metrics."""
        result = CollectorResult()
        
        if not self.docker.available:
            result.set_error("Docker socket not available")
            return result
        
        # Refresh container info
        self._container = await self._find_container()
        
        if not self._container:
            result.set_unavailable("not_found")
            return result
        
        container = self._container
        self._container_state = container.state
        result.set_state(container.state)
        
        # Health
        if self.config.health and container.health:
            result.set("health", container.health)
        
        # If container is not running, skip stats
        if not container.is_running:
            return result
        
        # Get container stats
        try:
            stats = await self.docker.get_stats(container.id)
        except DockerError as e:
            result.set_error(str(e))
            return result
        
        if self.config.cpu:
            result.set("cpu_percent", round(stats.cpu_percent, 1))
        
        if self.config.memory:
            result.set("memory_usage", round(stats.memory_usage_mb, 1))
            result.set("memory_percent", round(stats.memory_percent, 1))
            result.set("memory_limit", round(stats.memory_limit_mb, 1))
        
        if self.config.network:
            result.set("network_rx", round(stats.network_rx_bytes / (1024 * 1024), 2))
            result.set("network_tx", round(stats.network_tx_bytes / (1024 * 1024), 2))
        
        if self.config.disk:
            result.set("disk_read", round(stats.block_read / (1024 * 1024), 2))
            result.set("disk_write", round(stats.block_write / (1024 * 1024), 2))
        
        if self.config.uptime and container.started_at:
            try:
                started = datetime.fromisoformat(container.started_at.replace("Z", "+00:00"))
                uptime = int((datetime.now().astimezone() - started).total_seconds())
                result.set("uptime", max(0, uptime))
            except Exception:
                pass
        
        result.set("pids", stats.pids)
        
        return result

