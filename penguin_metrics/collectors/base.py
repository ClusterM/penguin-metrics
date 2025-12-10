"""
Base collector interface for metric collection.

All collectors inherit from the abstract Collector class and implement
the collect() method to gather metrics from various sources.
"""

import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..models.device import Device
from ..models.sensor import Sensor, SensorState


@dataclass
class CollectorResult:
    """Result of a collection cycle."""

    # Data dict for JSON publication (key -> value)
    data: dict[str, Any] = field(default_factory=dict)

    # Source state (online, running, not_found, etc.)
    state: str = "online"

    # Collector availability
    available: bool = True

    # Error message if collection failed
    error: str | None = None

    # Collection timestamp
    timestamp: datetime = field(default_factory=datetime.now)

    def set(self, key: str, value: Any) -> None:
        """Set a data value."""
        self.data[key] = value

    def set_state(self, state: str) -> None:
        """Set the source state."""
        self.state = state
        self.data["state"] = state

    def set_unavailable(self, state: str = "not_found") -> None:
        """Mark source as unavailable."""
        self.available = False
        self.state = state
        self.data = {"state": state}

    def set_error(self, error: str) -> None:
        """Mark collection as failed with error."""
        self.available = False
        self.error = error
        self.state = "error"
        self.data = {"state": "error"}

    def to_json_dict(self) -> dict[str, Any]:
        """Get data dict for JSON serialization."""
        return self.data

    def __repr__(self) -> str:
        status = "OK" if self.available else f"ERROR: {self.error}"
        return f"CollectorResult({len(self.data)} fields, state={self.state}, {status})"


class Collector(ABC):
    """
    Abstract base class for metric collectors.

    Each collector is responsible for:
    1. Defining its sensors (get_sensors)
    2. Creating its device (get_device)
    3. Collecting metrics periodically (collect)

    Collectors can be enabled/disabled and have configurable intervals.
    """

    # Source type for topic structure (override in subclasses)
    SOURCE_TYPE: str = "unknown"

    def __init__(
        self,
        name: str,
        collector_id: str | None = None,
        update_interval: float = 10.0,
        enabled: bool = True,
        topic_prefix: str = "penguin_metrics",
    ):
        """
        Initialize collector.

        Args:
            name: Human-readable collector name
            collector_id: Unique identifier (generated from name if not provided)
            update_interval: Collection interval in seconds
            enabled: Whether collector is enabled
            topic_prefix: MQTT topic prefix (for unique_id generation)
        """
        self.name = name
        self.collector_id = collector_id or self._sanitize_id(name)
        self.update_interval = update_interval
        self.enabled = enabled
        self.topic_prefix = topic_prefix

        # Internal state
        self._device: Device | None = None
        self._sensors: list[Sensor] = []
        self._initialized = False
        self._last_result: CollectorResult | None = None
        self._availability = SensorState.UNKNOWN

    def sensor_id(self, metric: str) -> str:
        """
        Generate sensor unique_id for a metric.

        Format: penguin_metrics_{topic_prefix}_{source_type}_{name}_{metric}
        Example: penguin_metrics_penguin_metrics_system_cpu_percent

        Args:
            metric: Metric name (cpu_percent, memory_used, etc.)

        Returns:
            Unique sensor ID
        """
        if self.SOURCE_TYPE == "system":
            return f"penguin_metrics_{self.topic_prefix}_system_{metric}"
        return (
            f"penguin_metrics_{self.topic_prefix}_{self.SOURCE_TYPE}_{self.collector_id}_{metric}"
        )

    def source_topic(self, topic_prefix: str) -> str:
        """
        Get MQTT topic for this source's JSON data.

        Format: {prefix}/{type}/{name} or {prefix}/{type} for system
        Examples:
            - opi5max/system
            - opi5max/temperature/soc
            - opi5max/docker/myapp

        Args:
            topic_prefix: Base topic prefix

        Returns:
            Full MQTT topic string for JSON payload
        """
        if self.SOURCE_TYPE == "system":
            return f"{topic_prefix}/system"
        return f"{topic_prefix}/{self.SOURCE_TYPE}/{self.collector_id}"

    @staticmethod
    def _sanitize_id(value: str) -> str:
        """Sanitize a string for use as an identifier."""
        result = []
        for char in value.lower():
            if char.isalnum():
                result.append(char)
            elif char in " -_.":
                result.append("_")

        sanitized = "".join(result)
        while "__" in sanitized:
            sanitized = sanitized.replace("__", "_")

        return sanitized.strip("_")

    async def initialize(self) -> None:
        """
        Initialize the collector.

        Called once before the first collection. Override to perform
        setup operations like discovering sensors.
        """
        self._device = self.create_device()
        self._sensors = self.create_sensors()
        self._initialized = True

    @abstractmethod
    def create_device(self) -> Device | None:
        """
        Create the Home Assistant device for this collector.

        Returns:
            Device instance for sensor grouping
        """
        pass

    @abstractmethod
    def create_sensors(self) -> list[Sensor]:
        """
        Create sensors for this collector.

        Returns:
            List of Sensor instances
        """
        pass

    @abstractmethod
    async def collect(self) -> CollectorResult:
        """
        Collect metrics from the source.

        This method is called periodically at update_interval.

        Returns:
            CollectorResult with collected metrics
        """
        pass

    @property
    def device(self) -> Device | None:
        """Get the collector's device."""
        return self._device

    @property
    def sensors(self) -> list[Sensor]:
        """Get the collector's sensors."""
        return self._sensors

    @property
    def availability(self) -> SensorState:
        """Get current availability state."""
        return self._availability

    def get_sensor(self, sensor_id: str) -> Sensor | None:
        """
        Get sensor by ID.

        Supports both full unique_id (type_name_metric) and legacy format (collector_id_metric).
        """
        for sensor in self._sensors:
            if sensor.unique_id == sensor_id:
                return sensor

        # Try matching by metric suffix (for backwards compatibility during migration)
        # If sensor_id is "collector_id_metric", try to find "type_name_metric"
        if "_" in sensor_id:
            metric_name = (
                sensor_id.split("_", 1)[-1]
                if sensor_id.startswith(self.collector_id)
                else sensor_id
            )
            expected_id = self.sensor_id(metric_name)
            for sensor in self._sensors:
                if sensor.unique_id == expected_id:
                    return sensor

        return None

    async def safe_collect(self) -> CollectorResult:
        """
        Safely collect metrics, catching exceptions.

        Returns:
            CollectorResult, with error set if collection failed
        """
        if not self._initialized:
            await self.initialize()

        try:
            result = await self.collect()
            self._last_result = result
            self._availability = SensorState.ONLINE if result.available else SensorState.OFFLINE
            return result

        except Exception as e:
            result = CollectorResult()
            result.set_error(str(e))
            self._last_result = result
            self._availability = SensorState.OFFLINE
            return result

    async def run_forever(self) -> AsyncIterator[CollectorResult]:
        """
        Run collector in a loop, yielding results.

        Yields:
            CollectorResult after each collection cycle
        """
        while True:
            if self.enabled:
                result = await self.safe_collect()
                yield result

            await asyncio.sleep(self.update_interval)

    def __repr__(self) -> str:
        status = "enabled" if self.enabled else "disabled"
        return f"{self.__class__.__name__}({self.name!r}, {status}, {self.update_interval}s)"


def apply_overrides_to_sensors(sensors: Iterable[Sensor], ha_config: Any) -> None:
    """Apply Home Assistant overrides to all sensors in iterable."""
    if not ha_config:
        return
    for sensor in sensors:
        sensor.apply_ha_overrides(ha_config)


class MultiSourceCollector(Collector):
    """
    Base class for collectors that monitor multiple sources.

    For example, a process collector that monitors multiple processes
    matching a pattern, or a container collector for multiple containers.
    """

    def __init__(
        self,
        name: str,
        collector_id: str | None = None,
        update_interval: float = 10.0,
        enabled: bool = True,
        aggregate: bool = False,
    ):
        """
        Initialize multi-source collector.

        Args:
            name: Human-readable collector name
            collector_id: Unique identifier
            update_interval: Collection interval in seconds
            enabled: Whether collector is enabled
            aggregate: Whether to sum metrics from all sources
        """
        super().__init__(name, collector_id, update_interval, enabled)
        self.aggregate = aggregate
        self._source_count = 0

    @abstractmethod
    async def discover_sources(self) -> list[Any]:
        """
        Discover sources to monitor.

        Returns:
            List of sources (PIDs, container IDs, etc.)
        """
        pass

    @abstractmethod
    async def collect_from_source(self, source: Any) -> CollectorResult:
        """
        Collect metrics from a single source.

        Args:
            source: Source to collect from

        Returns:
            CollectorResult for this source
        """
        pass

    async def collect(self) -> CollectorResult:
        """Collect from all discovered sources."""
        sources = await self.discover_sources()
        self._source_count = len(sources)

        if not sources:
            result = CollectorResult()
            result.set_error("No sources found")
            return result

        if self.aggregate:
            # Aggregate metrics from all sources
            return await self._collect_aggregated(sources)
        else:
            # Return metrics from first source (for single-match)
            return await self.collect_from_source(sources[0])

    async def _collect_aggregated(self, sources: list[Any]) -> CollectorResult:
        """Collect and aggregate metrics from all sources."""
        combined = CollectorResult()
        aggregated: dict[str, list[float]] = {}

        for source in sources:
            try:
                result = await self.collect_from_source(source)
                if result.available:
                    for key, value in result.data.items():
                        if key == "state":
                            continue
                        if key not in aggregated:
                            aggregated[key] = []
                        if isinstance(value, (int, float)):
                            aggregated[key].append(value)
            except Exception:
                continue

        # Sum aggregated values
        for key, values in aggregated.items():
            if values:
                combined.set(key, sum(values))

        if not combined.data:
            combined.set_error("Failed to collect from any source")
        else:
            combined.set_state("online")

        return combined

    @property
    def source_count(self) -> int:
        """Get number of discovered sources."""
        return self._source_count
