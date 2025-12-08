"""
Base collector interface for metric collection.

All collectors inherit from the abstract Collector class and implement
the collect() method to gather metrics from various sources.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncIterator
import asyncio

from ..models.sensor import Sensor, SensorState
from ..models.device import Device


@dataclass
class MetricValue:
    """A single metric value with metadata."""
    
    sensor_id: str
    value: Any
    timestamp: datetime = field(default_factory=datetime.now)
    attributes: dict[str, Any] = field(default_factory=dict)
    
    def __repr__(self) -> str:
        return f"MetricValue({self.sensor_id}={self.value})"


@dataclass
class CollectorResult:
    """Result of a collection cycle."""
    
    # List of collected metrics
    metrics: list[MetricValue] = field(default_factory=list)
    
    # Collector availability
    available: bool = True
    
    # Error message if collection failed
    error: str | None = None
    
    # Collection timestamp
    timestamp: datetime = field(default_factory=datetime.now)
    
    def add_metric(self, sensor_id: str, value: Any, **attributes) -> None:
        """Add a metric value to the result."""
        self.metrics.append(MetricValue(
            sensor_id=sensor_id,
            value=value,
            timestamp=self.timestamp,
            attributes=attributes,
        ))
    
    def set_error(self, error: str) -> None:
        """Mark collection as failed with error."""
        self.available = False
        self.error = error
    
    def __repr__(self) -> str:
        status = "OK" if self.available else f"ERROR: {self.error}"
        return f"CollectorResult({len(self.metrics)} metrics, {status})"


class Collector(ABC):
    """
    Abstract base class for metric collectors.
    
    Each collector is responsible for:
    1. Defining its sensors (get_sensors)
    2. Creating its device (get_device)
    3. Collecting metrics periodically (collect)
    
    Collectors can be enabled/disabled and have configurable intervals.
    """
    
    def __init__(
        self,
        name: str,
        collector_id: str | None = None,
        update_interval: float = 10.0,
        enabled: bool = True,
    ):
        """
        Initialize collector.
        
        Args:
            name: Human-readable collector name
            collector_id: Unique identifier (generated from name if not provided)
            update_interval: Collection interval in seconds
            enabled: Whether collector is enabled
        """
        self.name = name
        self.collector_id = collector_id or self._sanitize_id(name)
        self.update_interval = update_interval
        self.enabled = enabled
        
        # Internal state
        self._device: Device | None = None
        self._sensors: list[Sensor] = []
        self._initialized = False
        self._last_result: CollectorResult | None = None
        self._availability = SensorState.UNKNOWN
    
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
    def create_device(self) -> Device:
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
        """Get sensor by ID."""
        for sensor in self._sensors:
            if sensor.unique_id == sensor_id:
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
            
            # Update sensor states from result
            for metric in result.metrics:
                sensor = self.get_sensor(metric.sensor_id)
                if sensor:
                    sensor.state = metric.value
                    sensor.availability = self._availability
            
            return result
        
        except Exception as e:
            result = CollectorResult()
            result.set_error(str(e))
            self._last_result = result
            self._availability = SensorState.OFFLINE
            
            # Mark all sensors as unavailable
            for sensor in self._sensors:
                sensor.set_unavailable()
            
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
                    for metric in result.metrics:
                        if metric.sensor_id not in aggregated:
                            aggregated[metric.sensor_id] = []
                        if isinstance(metric.value, (int, float)):
                            aggregated[metric.sensor_id].append(metric.value)
            except Exception:
                continue
        
        # Sum aggregated values
        for sensor_id, values in aggregated.items():
            if values:
                combined.add_metric(sensor_id, sum(values))
        
        if not combined.metrics:
            combined.set_error("Failed to collect from any source")
        
        return combined
    
    @property
    def source_count(self) -> int:
        """Get number of discovered sources."""
        return self._source_count

