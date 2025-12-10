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

from ..config.schema import ContainerConfig, ContainerMatchType, DefaultsConfig, DeviceConfig
from ..models.device import Device, create_device_from_ref
from ..models.sensor import DeviceClass, Sensor, StateClass
from ..utils.docker_api import ContainerInfo, DockerClient, DockerError
from .base import Collector, CollectorResult, build_sensor


def _calc_rate(
    current: int,
    previous: float | None,
    time_delta: float | None,
) -> float | None:
    """Calculate MiB/s rate based on previous value and time delta."""
    if previous is None or time_delta is None or time_delta <= 0:
        return None
    return max(0.0, (current - previous) / (1024 * 1024) / time_delta)


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
        device_templates: dict[str, DeviceConfig] | None = None,
        parent_device: Device | None = None,
    ):
        """
        Initialize container collector.

        Args:
            config: Container configuration
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

        # Docker client
        self.docker = DockerClient()

        # Matched container
        self._container: ContainerInfo | None = None
        self._container_state = "unknown"

        # Previous values for rate calculation
        self._prev_network_rx: float | None = None
        self._prev_network_tx: float | None = None
        self._prev_disk_read: float | None = None
        self._prev_disk_write: float | None = None
        self._prev_timestamp: datetime | None = None

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
                if fnmatch.fnmatch(container.name, match_value) or re.search(
                    match_value, container.name
                ):
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

    def create_device(self) -> Device | None:
        """Create device for container metrics."""
        container_name = self._container.name if self._container else self.config.name
        return create_device_from_ref(
            device_ref=self.config.device_ref,
            source_type=self.SOURCE_TYPE,
            collector_id=self.collector_id,
            topic_prefix=self.topic_prefix,
            default_name=f"Container: {container_name}",
            manufacturer="Docker",
            model="Container",
            parent_device=self.parent_device,
            device_templates=self.device_templates,
        )

    def create_sensors(self) -> list[Sensor]:
        """Create sensors based on configuration."""
        sensors: list[Sensor] = []
        device = self.device
        ha_cfg = self.config.ha_config

        def add(
            metric: str,
            display: str,
            *,
            unit: str | None = None,
            device_class: DeviceClass | str | None = None,
            state_class: StateClass | None = None,
            icon: str | None = None,
        ) -> None:
            sensors.append(
                build_sensor(
                    source_type=self.SOURCE_TYPE,
                    source_name=self.name,
                    metric_name=metric,
                    display_name=display,
                    device=device,
                    topic_prefix=self.topic_prefix,
                    unit=unit,
                    device_class=device_class,
                    state_class=state_class,
                    icon=icon,
                    ha_config=ha_cfg,
                )
            )

        if self.config.state:
            add("state", "State", icon="mdi:docker")

        if self.config.health:
            add("health", "Health", icon="mdi:heart-pulse")

        if self.config.cpu:
            add(
                "cpu_percent",
                "CPU Usage",
                unit="%",
                state_class=StateClass.MEASUREMENT,
                icon="mdi:chip",
            )

        if self.config.memory:
            add(
                "memory_usage",
                "Memory Usage",
                unit="MiB",
                device_class=DeviceClass.DATA_SIZE,
                state_class=StateClass.MEASUREMENT,
                icon="mdi:memory",
            )
            add(
                "memory_percent",
                "Memory %",
                unit="%",
                state_class=StateClass.MEASUREMENT,
                icon="mdi:memory",
            )
            add(
                "memory_limit",
                "Memory Limit",
                unit="MiB",
                device_class=DeviceClass.DATA_SIZE,
                state_class=StateClass.MEASUREMENT,
                icon="mdi:memory",
            )

        if self.config.network:
            add(
                "network_rx",
                "Network RX",
                unit="MiB",
                device_class=DeviceClass.DATA_SIZE,
                state_class=StateClass.TOTAL_INCREASING,
                icon="mdi:download",
            )
            add(
                "network_tx",
                "Network TX",
                unit="MiB",
                device_class=DeviceClass.DATA_SIZE,
                state_class=StateClass.TOTAL_INCREASING,
                icon="mdi:upload",
            )

        if self.config.network_rate:
            add(
                "network_rx_rate",
                "Network RX Rate",
                unit="MiB/s",
                device_class=DeviceClass.DATA_RATE,
                state_class=StateClass.MEASUREMENT,
                icon="mdi:download",
            )
            add(
                "network_tx_rate",
                "Network TX Rate",
                unit="MiB/s",
                device_class=DeviceClass.DATA_RATE,
                state_class=StateClass.MEASUREMENT,
                icon="mdi:upload",
            )

        if self.config.disk:
            add(
                "disk_read",
                "Disk Read",
                unit="MiB",
                device_class=DeviceClass.DATA_SIZE,
                state_class=StateClass.TOTAL_INCREASING,
                icon="mdi:harddisk",
            )
            add(
                "disk_write",
                "Disk Write",
                unit="MiB",
                device_class=DeviceClass.DATA_SIZE,
                state_class=StateClass.TOTAL_INCREASING,
                icon="mdi:harddisk",
            )

        if self.config.disk_rate:
            add(
                "disk_read_rate",
                "Disk Read Rate",
                unit="MiB/s",
                device_class=DeviceClass.DATA_RATE,
                state_class=StateClass.MEASUREMENT,
                icon="mdi:harddisk",
            )
            add(
                "disk_write_rate",
                "Disk Write Rate",
                unit="MiB/s",
                device_class=DeviceClass.DATA_RATE,
                state_class=StateClass.MEASUREMENT,
                icon="mdi:harddisk",
            )

        if self.config.uptime:
            add(
                "uptime",
                "Uptime",
                unit="s",
                device_class=DeviceClass.DURATION,
                state_class=StateClass.TOTAL_INCREASING,
                icon="mdi:clock-outline",
            )

        add("pids", "Processes", state_class=StateClass.MEASUREMENT, icon="mdi:application-outline")

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

        # Health - "n/a" if no healthcheck defined
        if self.config.health:
            result.set("health", container.health or "n/a")

        # If container is not running, skip stats
        if not container.is_running:
            return result

        # Get container stats
        try:
            stats = await self.docker.get_stats(container.id)
        except DockerError as e:
            result.set_error(str(e))
            return result

        # Current timestamp for rate calculation
        now = datetime.now()
        time_delta = (now - self._prev_timestamp).total_seconds() if self._prev_timestamp else None

        if self.config.cpu:
            result.set("cpu_percent", round(stats.cpu_percent, 1))

        if self.config.memory:
            result.set("memory_usage", round(stats.memory_usage_mb, 1))
            result.set("memory_percent", round(stats.memory_percent, 1))
            result.set("memory_limit", round(stats.memory_limit_mb, 1))

        # Network total
        network_rx_bytes = stats.network_rx_bytes
        network_tx_bytes = stats.network_tx_bytes
        if self.config.network:
            result.set("network_rx", round(network_rx_bytes / (1024 * 1024), 2))
            result.set("network_tx", round(network_tx_bytes / (1024 * 1024), 2))

        # Network rate (MiB/s)
        if self.config.network_rate:
            rx_rate = _calc_rate(network_rx_bytes, self._prev_network_rx, time_delta)
            tx_rate = _calc_rate(network_tx_bytes, self._prev_network_tx, time_delta)
            if rx_rate is not None:
                result.set("network_rx_rate", round(rx_rate, 2))
            if tx_rate is not None:
                result.set("network_tx_rate", round(tx_rate, 2))
            self._prev_network_rx = network_rx_bytes
            self._prev_network_tx = network_tx_bytes

        # Disk total
        disk_read_bytes = stats.block_read
        disk_write_bytes = stats.block_write
        if self.config.disk:
            result.set("disk_read", round(disk_read_bytes / (1024 * 1024), 2))
            result.set("disk_write", round(disk_write_bytes / (1024 * 1024), 2))

        # Disk rate (MiB/s)
        if self.config.disk_rate:
            read_rate = _calc_rate(disk_read_bytes, self._prev_disk_read, time_delta)
            write_rate = _calc_rate(disk_write_bytes, self._prev_disk_write, time_delta)
            if read_rate is not None:
                result.set("disk_read_rate", round(read_rate, 2))
            if write_rate is not None:
                result.set("disk_write_rate", round(write_rate, 2))
            self._prev_disk_read = disk_read_bytes
            self._prev_disk_write = disk_write_bytes

        # Update timestamp for next rate calculation
        self._prev_timestamp = now

        if self.config.uptime and container.started_at:
            try:
                started = datetime.fromisoformat(container.started_at.replace("Z", "+00:00"))
                uptime = int((datetime.now().astimezone() - started).total_seconds())
                result.set("uptime", max(0, uptime))
            except Exception:
                pass

        result.set("pids", stats.pids)

        return result
