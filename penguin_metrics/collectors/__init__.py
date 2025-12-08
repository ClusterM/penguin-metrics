"""
Metric collectors for system telemetry.
"""

from .base import Collector, CollectorResult
from .system import SystemCollector
from .temperature import TemperatureCollector
from .process import ProcessCollector
from .battery import BatteryCollector
from .service import ServiceCollector
from .container import ContainerCollector
from .custom import CustomCollector
from .gpu import GPUCollector

__all__ = [
    "Collector",
    "CollectorResult",
    "SystemCollector",
    "TemperatureCollector",
    "ProcessCollector",
    "BatteryCollector",
    "ServiceCollector",
    "ContainerCollector",
    "CustomCollector",
    "GPUCollector",
]

