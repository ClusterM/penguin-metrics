"""
GPU monitoring collector (minimal implementation).

Attempts to read GPU metrics from various sysfs interfaces.
Supports:
- DRM subsystem (/sys/class/drm/)
- hwmon for temperature
- devfreq for ARM GPUs (Rockchip, Mali, etc.)

Note: Full GPU monitoring is vendor-specific. This provides
basic metrics where available through standard interfaces.
"""

from pathlib import Path
from typing import NamedTuple

from .base import Collector, CollectorResult
from ..models.device import Device
from ..models.sensor import Sensor, DeviceClass, StateClass, create_sensor
from ..config.schema import SystemConfig, DefaultsConfig


class GPUDevice(NamedTuple):
    """GPU device information."""
    name: str
    path: Path
    type: str  # drm, devfreq, hwmon


def _read_file(path: Path, default: str = "") -> str:
    """Read a file, returning default on error."""
    try:
        return path.read_text().strip()
    except Exception:
        return default


def _read_int(path: Path, default: int = 0) -> int:
    """Read an integer from a file."""
    content = _read_file(path)
    if not content:
        return default
    try:
        return int(content)
    except ValueError:
        return default


def discover_gpu_devices() -> list[GPUDevice]:
    """
    Discover available GPU devices from sysfs.
    
    Returns:
        List of GPUDevice tuples
    """
    devices = []
    
    # Check devfreq for ARM GPUs (Rockchip, Mali, etc.)
    devfreq = Path("/sys/class/devfreq")
    if devfreq.exists():
        for entry in devfreq.iterdir():
            name = entry.name.lower()
            if "gpu" in name or "mali" in name:
                devices.append(GPUDevice(
                    name=entry.name,
                    path=entry,
                    type="devfreq",
                ))
    
    # Check DRM subsystem
    drm = Path("/sys/class/drm")
    if drm.exists():
        for entry in drm.iterdir():
            if entry.name.startswith("card") and not "-" in entry.name:
                # This is a GPU card, not a connector
                devices.append(GPUDevice(
                    name=entry.name,
                    path=entry,
                    type="drm",
                ))
    
    return devices


def get_devfreq_metrics(device: GPUDevice) -> dict[str, float | int | str]:
    """
    Get metrics from a devfreq device.
    
    Args:
        device: GPUDevice with type="devfreq"
    
    Returns:
        Dictionary of metrics
    """
    metrics = {}
    path = device.path
    
    # Current frequency (Hz -> MHz)
    cur_freq = _read_int(path / "cur_freq")
    if cur_freq > 0:
        metrics["frequency"] = cur_freq // 1_000_000
    
    # Min/max frequency
    min_freq = _read_int(path / "min_freq")
    max_freq = _read_int(path / "max_freq")
    if min_freq > 0:
        metrics["frequency_min"] = min_freq // 1_000_000
    if max_freq > 0:
        metrics["frequency_max"] = max_freq // 1_000_000
    
    # Governor
    governor = _read_file(path / "governor")
    if governor:
        metrics["governor"] = governor
    
    # Load/utilization (some devfreq drivers provide this)
    load_path = path / "load"
    if load_path.exists():
        load = _read_int(load_path)
        metrics["utilization"] = load
    
    # Trans stats for utilization estimation
    trans_stat = path / "trans_stat"
    if trans_stat.exists():
        content = _read_file(trans_stat)
        # Parse utilization from trans_stat if available
        for line in content.splitlines():
            if "total" in line.lower():
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        metrics["transitions"] = int(parts[-1])
                    except ValueError:
                        pass
    
    return metrics


def get_drm_metrics(device: GPUDevice) -> dict[str, float | int | str]:
    """
    Get metrics from a DRM device.
    
    Args:
        device: GPUDevice with type="drm"
    
    Returns:
        Dictionary of metrics
    """
    metrics = {}
    path = device.path / "device"
    
    # Try to get vendor/device info
    vendor = _read_file(path / "vendor")
    if vendor:
        metrics["vendor"] = vendor
    
    # Check for hwmon subdirectory for temperature
    hwmon = path / "hwmon"
    if hwmon.exists():
        for hw_entry in hwmon.iterdir():
            temp_input = hw_entry / "temp1_input"
            if temp_input.exists():
                temp = _read_int(temp_input)
                if temp > 0:
                    metrics["temperature"] = temp // 1000  # millidegrees to degrees
                break
    
    # GPU busy percent (Intel)
    busy_path = path / "gt" / "gt0" / "rps_cur_freq_mhz"
    if busy_path.exists():
        freq = _read_int(busy_path)
        if freq > 0:
            metrics["frequency"] = freq
    
    # AMD/Intel specific paths
    for freq_path in [
        path / "pp_dpm_sclk",  # AMD
        path / "gt_cur_freq_mhz",  # Intel legacy
    ]:
        if freq_path.exists():
            content = _read_file(freq_path)
            # Parse current frequency from output
            for line in content.splitlines():
                if "*" in line:  # Current state marked with *
                    parts = line.split()
                    for part in parts:
                        if part.endswith("Mhz") or part.endswith("MHz"):
                            try:
                                metrics["frequency"] = int(part[:-3])
                            except ValueError:
                                pass
                            break
            break
    
    return metrics


class GPUCollector(Collector):
    """
    Collector for GPU metrics.
    
    Attempts to read GPU data from standard sysfs interfaces.
    """
    
    def __init__(
        self,
        config: SystemConfig,
        defaults: DefaultsConfig,
        topic_prefix: str = "penguin_metrics",
        parent_device: Device | None = None,
    ):
        """
        Initialize GPU collector.
        
        Args:
            config: System configuration
            defaults: Default settings
            topic_prefix: MQTT topic prefix
            parent_device: Parent device (if part of system collector)
        """
        name = f"{config.name}_gpu"
        collector_id = f"{config.id or config.name}_gpu"
        
        super().__init__(
            name=name,
            collector_id=collector_id,
            update_interval=config.update_interval or defaults.update_interval,
        )
        
        self.config = config
        self.defaults = defaults
        self.topic_prefix = topic_prefix
        self.parent_device = parent_device
        
        # Discovered GPUs
        self._gpus: list[GPUDevice] = []
    
    async def initialize(self) -> None:
        """Discover GPU devices."""
        self._gpus = discover_gpu_devices()
        await super().initialize()
    
    def create_device(self) -> Device:
        """Create device for GPU metrics."""
        if self.parent_device:
            return self.parent_device
        
        return Device(
            identifiers=[f"gpu_{self.collector_id}"],
            name=f"GPU: {self.name}",
            manufacturer="Penguin Metrics",
            model="GPU Monitor",
        )
    
    def create_sensors(self) -> list[Sensor]:
        """Create sensors for discovered GPUs."""
        sensors = []
        device = self.device
        
        for gpu in self._gpus:
            gpu_id = gpu.name.replace(".", "_").replace("-", "_")
            
            sensors.append(create_sensor(
                source_id=self.collector_id,
                metric_name=f"{gpu_id}_frequency",
                display_name=f"GPU {gpu.name} Frequency",
                device=device,
                topic_prefix=self.topic_prefix,
                unit="MHz",
                device_class=DeviceClass.FREQUENCY,
                state_class=StateClass.MEASUREMENT,
                icon="mdi:chip",
            ))
            
            # Temperature sensor if available
            sensors.append(create_sensor(
                source_id=self.collector_id,
                metric_name=f"{gpu_id}_temperature",
                display_name=f"GPU {gpu.name} Temperature",
                device=device,
                topic_prefix=self.topic_prefix,
                unit="°C",
                device_class=DeviceClass.TEMPERATURE,
                state_class=StateClass.MEASUREMENT,
                icon="mdi:thermometer",
                enabled_by_default=False,
            ))
            
            # Utilization if available
            sensors.append(create_sensor(
                source_id=self.collector_id,
                metric_name=f"{gpu_id}_utilization",
                display_name=f"GPU {gpu.name} Utilization",
                device=device,
                topic_prefix=self.topic_prefix,
                unit="%",
                state_class=StateClass.MEASUREMENT,
                icon="mdi:chip",
                enabled_by_default=False,
            ))
        
        return sensors
    
    async def collect(self) -> CollectorResult:
        """Collect GPU metrics."""
        result = CollectorResult()
        
        if not self._gpus:
            result.set_error("No GPU devices found")
            return result
        
        for gpu in self._gpus:
            gpu_id = gpu.name.replace(".", "_").replace("-", "_")
            
            if gpu.type == "devfreq":
                metrics = get_devfreq_metrics(gpu)
            elif gpu.type == "drm":
                metrics = get_drm_metrics(gpu)
            else:
                continue
            
            if "frequency" in metrics:
                result.add_metric(
                    f"{self.collector_id}_{gpu_id}_frequency",
                    metrics["frequency"],
                )
            
            if "temperature" in metrics:
                result.add_metric(
                    f"{self.collector_id}_{gpu_id}_temperature",
                    metrics["temperature"],
                )
            
            if "utilization" in metrics:
                result.add_metric(
                    f"{self.collector_id}_{gpu_id}_utilization",
                    metrics["utilization"],
                )
        
        if not result.metrics:
            result.set_error("No GPU metrics available")
        
        return result

