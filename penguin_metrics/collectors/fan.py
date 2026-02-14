"""
Fan (RPM) monitoring collector from hwmon sysfs.

Reads fan speed from /sys/class/hwmon/hwmon*/fan*_input (RPM).
Supports manual config by hwmon name and auto-discovery.
"""

from pathlib import Path
from typing import NamedTuple

from ..config.schema import DefaultsConfig, DeviceConfig, FanConfig, FanMatchType
from ..models.device import Device, create_device_from_ref
from ..models.sensor import Sensor, StateClass
from .base import Collector, CollectorResult, build_sensor


class FanInput(NamedTuple):
    """Fan input info: metric name and sysfs path."""

    metric_name: str  # fan1_rpm, fan2_rpm, or rpm (single fan)
    path: Path


def discover_fan_hwmons() -> list[tuple[str, str, list[FanInput]]]:
    """
    Discover hwmon instances that have fan*_input.

    Returns:
        List of (hwmon_dir_basename, display_name, list of FanInput).
        E.g. [("hwmon0", "coretemp", [FanInput("fan1_rpm", Path(...))]), ...]
    """
    result: list[tuple[str, str, list[FanInput]]] = []
    hwmon_base = Path("/sys/class/hwmon")

    if not hwmon_base.exists():
        return result

    for hwmon_dir in sorted(hwmon_base.iterdir()):
        if not hwmon_dir.is_dir():
            continue
        basename = hwmon_dir.name  # hwmon0, hwmon1, ...
        fan_inputs = sorted(hwmon_dir.glob("fan*_input"))
        if not fan_inputs:
            continue

        display_name = basename
        try:
            name_file = hwmon_dir / "name"
            if name_file.exists():
                display_name = name_file.read_text().strip() or basename
        except Exception:
            pass

        inputs: list[FanInput] = []
        for i, p in enumerate(fan_inputs):
            # fan1_input -> fan1_rpm, fan2_input -> fan2_rpm
            stem = p.stem  # fan1_input -> fan1
            num_part = stem.replace("fan", "").replace("_input", "")
            if num_part.isdigit():
                metric_name = f"fan{num_part}_rpm"
            else:
                metric_name = f"fan{i + 1}_rpm"
            inputs.append(FanInput(metric_name=metric_name, path=p))

        if len(inputs) == 1:
            inputs = [FanInput(metric_name="rpm", path=inputs[0].path)]
        result.append((basename, display_name, inputs))

    return result


class FanCollector(Collector):
    """
    Collector for fan speed (RPM) from hwmon sysfs.

    One collector per hwmon device; reports one or more fan*_rpm metrics.
    """

    SOURCE_TYPE = "fan"

    def __init__(
        self,
        config: FanConfig,
        defaults: DefaultsConfig,
        topic_prefix: str = "penguin_metrics",
        parent_device: Device | None = None,
        device_templates: dict[str, DeviceConfig] | None = None,
    ):
        super().__init__(
            name=config.name,
            collector_id=config.name,
            update_interval=config.update_interval or defaults.update_interval,
        )
        self.config = config
        self.defaults = defaults
        self.topic_prefix = topic_prefix
        self.parent_device = parent_device
        self.device_templates = device_templates or {}
        self._fan_inputs = self._resolve_fan_inputs()

    def _resolve_fan_inputs(self) -> list[FanInput]:
        """Resolve fan*_input paths from match hwmon (so create_sensors can run before initialize)."""
        if not self.config.match or self.config.match.type != FanMatchType.HWMON:
            return []
        hwmon_path = Path("/sys/class/hwmon") / self.config.match.value
        if not hwmon_path.exists():
            return []
        inputs: list[FanInput] = []
        for p in sorted(hwmon_path.glob("fan*_input")):
            stem = p.stem
            num_part = stem.replace("fan", "").replace("_input", "")
            metric_name = f"fan{num_part}_rpm" if num_part.isdigit() else "fan1_rpm"
            inputs.append(FanInput(metric_name=metric_name, path=p))
        if len(inputs) == 1:
            inputs = [FanInput(metric_name="rpm", path=inputs[0].path)]
        return inputs

    async def initialize(self) -> None:
        """No-op; fan inputs resolved in __init__."""
        await super().initialize()

    def create_device(self) -> Device | None:
        """Create device for fan metrics (system device by default)."""
        return create_device_from_ref(
            device_ref=self.config.device_ref,
            source_type=self.SOURCE_TYPE,
            collector_id=self.collector_id,
            topic_prefix=self.topic_prefix,
            default_name=f"Fan: {self.config.label}",
            model="Fan (hwmon)",
            parent_device=self.parent_device,
            device_templates=self.device_templates,
            use_parent_as_default=True,
        )

    def create_sensors(self) -> list[Sensor]:
        """Create sensors for each fan input (created after initialize)."""
        sensors: list[Sensor] = []
        device = self.device
        ha_cfg = getattr(self.config, "ha_config", None)

        for fin in self._fan_inputs:
            display = f"Fan {self.config.label} {fin.metric_name.replace('_', ' ').title()}"
            sensors.append(
                build_sensor(
                    source_type=self.SOURCE_TYPE,
                    source_name=self.config.name,
                    metric_name=fin.metric_name,
                    display_name=display,
                    device=device,
                    topic_prefix=self.topic_prefix,
                    unit="RPM",
                    state_class=StateClass.MEASUREMENT,
                    icon="mdi:fan",
                    ha_config=ha_cfg,
                    suggested_display_precision=0,
                )
            )
        return sensors

    async def collect(self) -> CollectorResult:
        """Read RPM from each fan*_input."""
        result = CollectorResult()
        if not self._fan_inputs:
            result.set_unavailable("no_fan_inputs")
            return result

        result.set_state("online")
        for fin in self._fan_inputs:
            try:
                value = int(fin.path.read_text().strip())
                result.set(fin.metric_name, value)
            except (OSError, ValueError):
                pass
        return result
