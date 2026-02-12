"""
Metric collectors for system telemetry.
"""

from .ac_power import ACPowerCollector
from .base import Collector, CollectorResult
from .battery import BatteryCollector
from .container import ContainerCollector
from .custom import CustomCollector
from .disk import DiskCollector
from .gpu import GPUCollector
from .network import NetworkCollector
from .process import ProcessCollector
from .service import ServiceCollector
from .system import SystemCollector
from .temperature import TemperatureCollector

__all__ = [
    "Collector",
    "CollectorResult",
    "ACPowerCollector",
    "SystemCollector",
    "TemperatureCollector",
    "ProcessCollector",
    "BatteryCollector",
    "ServiceCollector",
    "ContainerCollector",
    "CustomCollector",
    "DiskCollector",
    "GPUCollector",
    "NetworkCollector",
]
