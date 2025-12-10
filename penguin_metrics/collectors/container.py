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
from ..models.device import Device, _add_via_device_if_needed
from ..models.sensor import DeviceClass, Sensor, StateClass, create_sensor
from ..utils.docker_api import ContainerInfo, DockerClient, DockerError
from .base import Collector, CollectorResult


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
        device_ref = self.config.device_ref
        container_name = self._container.name if self._container else self.config.name

        # Handle "none" - no device
        if device_ref == "none":
            return None

        # Handle "system" - use parent device
        if device_ref == "system" and self.parent_device:
            return self.parent_device

        # Handle template reference
        if device_ref and device_ref not in ("system", "auto"):
            if device_ref in self.device_templates:
                template = self.device_templates[device_ref]
                device = Device(
                    identifiers=template.identifiers.copy(),
                    extra_fields=template.extra_fields.copy() if template.extra_fields else {},
                )
                _add_via_device_if_needed(device, self.parent_device, self.SOURCE_TYPE)
                return device

        # Default for container: auto-create device
        device = Device(
            identifiers=[f"penguin_metrics_{self.topic_prefix}_container_{self.collector_id}"],
            name=f"Container: {container_name}",
            manufacturer="Docker",
            model="Container",
        )
        _add_via_device_if_needed(device, self.parent_device, self.SOURCE_TYPE)
        return device

    def create_sensors(self) -> list[Sensor]:
        """Create sensors based on configuration."""
        sensors = []
        device = self.device

        # Container sensors use short names - device name provides context
        if self.config.state:
            sensors.append(
                create_sensor(
                    source_type="docker",
                    source_name=self.name,
                    metric_name="state",
                    display_name="State",
                    device=device,
                    topic_prefix=self.topic_prefix,
                    icon="mdi:docker",
                )
            )

        if self.config.health:
            sensors.append(
                create_sensor(
                    source_type="docker",
                    source_name=self.name,
                    metric_name="health",
                    display_name="Health",
                    device=device,
                    topic_prefix=self.topic_prefix,
                    icon="mdi:heart-pulse",
                )
            )

        if self.config.cpu:
            sensors.append(
                create_sensor(
                    source_type="docker",
                    source_name=self.name,
                    metric_name="cpu_percent",
                    display_name="CPU Usage",
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
                        source_type="docker",
                        source_name=self.name,
                        metric_name="memory_usage",
                        display_name="Memory Usage",
                        device=device,
                        topic_prefix=self.topic_prefix,
                        unit="MiB",
                        device_class=DeviceClass.DATA_SIZE,
                        state_class=StateClass.MEASUREMENT,
                        icon="mdi:memory",
                    ),
                    create_sensor(
                        source_type="docker",
                        source_name=self.name,
                        metric_name="memory_percent",
                        display_name="Memory %",
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
                        display_name="Memory Limit",
                        device=device,
                        topic_prefix=self.topic_prefix,
                        unit="MiB",
                        device_class=DeviceClass.DATA_SIZE,
                        state_class=StateClass.MEASUREMENT,
                        icon="mdi:memory",
                    ),
                ]
            )

        if self.config.network:
            sensors.extend(
                [
                    create_sensor(
                        source_type="docker",
                        source_name=self.name,
                        metric_name="network_rx",
                        display_name="Network RX",
                        device=device,
                        topic_prefix=self.topic_prefix,
                        unit="MiB",
                        device_class=DeviceClass.DATA_SIZE,
                        state_class=StateClass.TOTAL_INCREASING,
                        icon="mdi:download",
                    ),
                    create_sensor(
                        source_type="docker",
                        source_name=self.name,
                        metric_name="network_tx",
                        display_name="Network TX",
                        device=device,
                        topic_prefix=self.topic_prefix,
                        unit="MiB",
                        device_class=DeviceClass.DATA_SIZE,
                        state_class=StateClass.TOTAL_INCREASING,
                        icon="mdi:upload",
                    ),
                ]
            )

        if self.config.network_rate:
            sensors.extend(
                [
                    create_sensor(
                        source_type="docker",
                        source_name=self.name,
                        metric_name="network_rx_rate",
                        display_name="Network RX Rate",
                        device=device,
                        topic_prefix=self.topic_prefix,
                        unit="MiB/s",
                        device_class=DeviceClass.DATA_RATE,
                        state_class=StateClass.MEASUREMENT,
                        icon="mdi:download",
                    ),
                    create_sensor(
                        source_type="docker",
                        source_name=self.name,
                        metric_name="network_tx_rate",
                        display_name="Network TX Rate",
                        device=device,
                        topic_prefix=self.topic_prefix,
                        unit="MiB/s",
                        device_class=DeviceClass.DATA_RATE,
                        state_class=StateClass.MEASUREMENT,
                        icon="mdi:upload",
                    ),
                ]
            )

        if self.config.disk:
            sensors.extend(
                [
                    create_sensor(
                        source_type="docker",
                        source_name=self.name,
                        metric_name="disk_read",
                        display_name="Disk Read",
                        device=device,
                        topic_prefix=self.topic_prefix,
                        unit="MiB",
                        device_class=DeviceClass.DATA_SIZE,
                        state_class=StateClass.TOTAL_INCREASING,
                        icon="mdi:harddisk",
                    ),
                    create_sensor(
                        source_type="docker",
                        source_name=self.name,
                        metric_name="disk_write",
                        display_name="Disk Write",
                        device=device,
                        topic_prefix=self.topic_prefix,
                        unit="MiB",
                        device_class=DeviceClass.DATA_SIZE,
                        state_class=StateClass.TOTAL_INCREASING,
                        icon="mdi:harddisk",
                    ),
                ]
            )

        if self.config.disk_rate:
            sensors.extend(
                [
                    create_sensor(
                        source_type="docker",
                        source_name=self.name,
                        metric_name="disk_read_rate",
                        display_name="Disk Read Rate",
                        device=device,
                        topic_prefix=self.topic_prefix,
                        unit="MiB/s",
                        device_class=DeviceClass.DATA_RATE,
                        state_class=StateClass.MEASUREMENT,
                        icon="mdi:harddisk",
                    ),
                    create_sensor(
                        source_type="docker",
                        source_name=self.name,
                        metric_name="disk_write_rate",
                        display_name="Disk Write Rate",
                        device=device,
                        topic_prefix=self.topic_prefix,
                        unit="MiB/s",
                        device_class=DeviceClass.DATA_RATE,
                        state_class=StateClass.MEASUREMENT,
                        icon="mdi:harddisk",
                    ),
                ]
            )

        if self.config.uptime:
            sensors.append(
                create_sensor(
                    source_type="docker",
                    source_name=self.name,
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

        # PIDs count
        sensors.append(
            create_sensor(
                source_type="docker",
                source_name=self.name,
                metric_name="pids",
                display_name="Processes",
                device=device,
                topic_prefix=self.topic_prefix,
                state_class=StateClass.MEASUREMENT,
                icon="mdi:application-outline",
            )
        )

        # Apply HA overrides from config to all sensors
        if self.config.ha_config:
            for sensor in sensors:
                sensor.apply_ha_overrides(self.config.ha_config)

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
            if self._prev_timestamp and self._prev_network_rx is not None:
                time_delta = (now - self._prev_timestamp).total_seconds()
                if time_delta > 0:
                    rx_rate = (
                        (network_rx_bytes - self._prev_network_rx) / (1024 * 1024) / time_delta
                    )
                    tx_rate = (
                        (network_tx_bytes - self._prev_network_tx) / (1024 * 1024) / time_delta
                    )
                    result.set("network_rx_rate", round(max(0, rx_rate), 2))
                    result.set("network_tx_rate", round(max(0, tx_rate), 2))
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
            if self._prev_timestamp and self._prev_disk_read is not None:
                time_delta = (now - self._prev_timestamp).total_seconds()
                if time_delta > 0:
                    read_rate = (
                        (disk_read_bytes - self._prev_disk_read) / (1024 * 1024) / time_delta
                    )
                    write_rate = (
                        (disk_write_bytes - self._prev_disk_write) / (1024 * 1024) / time_delta
                    )
                    result.set("disk_read_rate", round(max(0, read_rate), 2))
                    result.set("disk_write_rate", round(max(0, write_rate), 2))
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
