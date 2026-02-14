"""
Network interface monitoring collector.

Uses psutil.net_io_counters(pernic=True) for bytes/packets/errors/drops
and psutil.net_if_stats() for isup, speed, mtu, duplex.
Supports auto-discovery, optional rate (KiB/s), and optional Wi-Fi RSSI (dBm).
"""

import asyncio
import re
from datetime import datetime

import psutil

from ..config.schema import DefaultsConfig, DeviceConfig, NetworkConfig, NetworkMatchType
from ..models.device import Device, create_device_from_ref
from ..models.sensor import DeviceClass, Sensor, StateClass
from .base import Collector, CollectorResult, build_sensor


def discover_network_interfaces() -> list[str]:
    """
    Discover network interface names from the system.

    Returns:
        List of interface names (e.g. eth0, wlan0).
        Excludes loopback (lo) by default; filter/exclude in config can refine.
    """
    try:
        counters = psutil.net_io_counters(pernic=True)
    except Exception:
        return []
    # Return sorted list; lo can be included and filtered via exclude in config
    return sorted(counters.keys())


def _calc_rate(
    current: float,
    prev: float | None,
    time_delta: float | None,
) -> float | None:
    """Compute rate (difference per second). Returns None if not enough data."""
    if prev is None or time_delta is None or time_delta <= 0:
        return None
    return (current - prev) / time_delta


async def _get_wifi_rssi(interface: str) -> int | None:
    """
    Get Wi-Fi signal strength (RSSI) in dBm for a wireless interface.

    Tries `iw dev <iface> link` first (signal: -42 dBm), then
    `iwconfig <iface>` (Signal level=-42). Returns None if not wireless or unavailable.
    """
    # Try iw first (nl80211)
    try:
        proc = await asyncio.create_subprocess_exec(
            "iw",
            "dev",
            interface,
            "link",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0 and stdout:
            # Match "signal: -42 dBm"
            m = re.search(r"signal:\s*(-?\d+)\s*dBm", stdout.decode("utf-8", errors="ignore"))
            if m:
                return int(m.group(1))
    except (TimeoutError, FileNotFoundError):
        pass

    # Fallback: iwconfig (wireless-tools)
    try:
        proc = await asyncio.create_subprocess_exec(
            "iwconfig",
            interface,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0 and stdout:
            # Match "Signal level=-42" or "Signal level=-42 dBm"
            m = re.search(r"Signal\s+level[=:](-?\d+)", stdout.decode("utf-8", errors="ignore"))
            if m:
                return int(m.group(1))
    except (TimeoutError, FileNotFoundError):
        pass

    return None


class NetworkCollector(Collector):
    """
    Collector for network interface metrics.

    Reads from psutil net_io_counters (pernic) and net_if_stats.
    """

    SOURCE_TYPE = "network"

    def __init__(
        self,
        config: NetworkConfig,
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

        # Interface name from match config
        self._interface_name: str = (
            config.match.value
            if config.match and config.match.type == NetworkMatchType.NAME
            else config.name
        )

        self._prev_bytes_sent: float | None = None
        self._prev_bytes_recv: float | None = None
        self._prev_packets_sent: float | None = None
        self._prev_packets_recv: float | None = None
        self._prev_timestamp: datetime | None = None

    async def initialize(self) -> None:
        """Verify interface exists."""
        interfaces = discover_network_interfaces()
        if self._interface_name not in interfaces:
            pass  # Will report not_found in collect
        await super().initialize()

    def create_device(self) -> Device | None:
        """Create device for network interface (system device by default)."""
        return create_device_from_ref(
            device_ref=self.config.device_ref,
            source_type=self.SOURCE_TYPE,
            collector_id=self.collector_id,
            topic_prefix=self.topic_prefix,
            default_name=f"Network: {self._interface_name}",
            manufacturer="Penguin Metrics",
            model="Network Interface",
            parent_device=self.parent_device,
            device_templates=self.device_templates,
            use_parent_as_default=True,
        )

    def create_sensors(self) -> list[Sensor]:
        """Create sensors for enabled metrics."""
        sensors: list[Sensor] = []
        device = self.device
        ha_cfg = self.config.ha_config
        name = self._interface_name
        prefix = f"Network {name}"

        def add(
            metric: str,
            display: str,
            *,
            unit: str | None = None,
            device_class: DeviceClass | str | None = None,
            state_class: StateClass | None = None,
            icon: str | None = "mdi:network",
            entity_type: str = "sensor",
            suggested_display_precision: int | None = None,
        ) -> None:
            sensors.append(
                build_sensor(
                    source_type=self.SOURCE_TYPE,
                    source_name=name,
                    metric_name=metric,
                    display_name=display,
                    device=device,
                    topic_prefix=self.topic_prefix,
                    unit=unit,
                    device_class=device_class,
                    state_class=state_class,
                    icon=icon,
                    entity_type=entity_type,
                    ha_config=ha_cfg,
                    suggested_display_precision=suggested_display_precision,
                )
            )

        if self.config.bytes:
            add(
                "bytes_sent",
                f"{prefix} Bytes Sent",
                unit="B",
                device_class=DeviceClass.DATA_SIZE,
                state_class=StateClass.TOTAL_INCREASING,
                suggested_display_precision=0,
            )
            add(
                "bytes_recv",
                f"{prefix} Bytes Recv",
                unit="B",
                device_class=DeviceClass.DATA_SIZE,
                state_class=StateClass.TOTAL_INCREASING,
                suggested_display_precision=0,
            )
        if self.config.packets:
            add("packets_sent", f"{prefix} Packets Sent", state_class=StateClass.TOTAL_INCREASING)
            add("packets_recv", f"{prefix} Packets Recv", state_class=StateClass.TOTAL_INCREASING)
        if self.config.errors:
            add("errin", f"{prefix} Errors In", state_class=StateClass.TOTAL_INCREASING)
            add("errout", f"{prefix} Errors Out", state_class=StateClass.TOTAL_INCREASING)
        if self.config.drops:
            add("dropin", f"{prefix} Drops In", state_class=StateClass.TOTAL_INCREASING)
            add("dropout", f"{prefix} Drops Out", state_class=StateClass.TOTAL_INCREASING)
        if self.config.rate:
            add(
                "bytes_sent_rate",
                f"{prefix} Send Rate",
                unit="KiB/s",
                device_class=DeviceClass.DATA_RATE,
                state_class=StateClass.MEASUREMENT,
                suggested_display_precision=2,
            )
            add(
                "bytes_recv_rate",
                f"{prefix} Recv Rate",
                unit="KiB/s",
                device_class=DeviceClass.DATA_RATE,
                state_class=StateClass.MEASUREMENT,
                suggested_display_precision=2,
            )
        if self.config.packets_rate:
            add(
                "packets_sent_rate",
                f"{prefix} Packets Sent Rate",
                unit="p/s",
                state_class=StateClass.MEASUREMENT,
            )
            add(
                "packets_recv_rate",
                f"{prefix} Packets Recv Rate",
                unit="p/s",
                state_class=StateClass.MEASUREMENT,
            )
        if self.config.isup:
            sensors.append(
                build_sensor(
                    source_type=self.SOURCE_TYPE,
                    source_name=name,
                    metric_name="isup",
                    display_name=f"{prefix} Up",
                    device=device,
                    topic_prefix=self.topic_prefix,
                    entity_type="binary_sensor",
                    icon="mdi:ethernet",
                    ha_config=ha_cfg,
                    value_template="{{ 'ON' if value_json.isup else 'OFF' }}",
                )
            )
        if self.config.speed:
            add("speed", f"{prefix} Speed", unit="Mbps")
        if self.config.mtu:
            add("mtu", f"{prefix} MTU")
        if self.config.duplex:
            add("duplex", f"{prefix} Duplex")
        if self.config.rssi:
            add(
                "rssi",
                f"{prefix} Signal",
                unit="dBm",
                state_class=StateClass.MEASUREMENT,
                icon="mdi:wifi",
                suggested_display_precision=0,
            )

        return sensors

    async def collect(self) -> CollectorResult:
        """Collect network interface metrics."""
        result = CollectorResult()
        name = self._interface_name

        try:
            counters_per_nic = psutil.net_io_counters(pernic=True)
        except Exception:
            result.set_unavailable("not_found")
            return result

        if name not in counters_per_nic:
            result.set_unavailable("not_found")
            return result

        now = datetime.now()
        time_delta = None
        if self._prev_timestamp is not None:
            time_delta = (now - self._prev_timestamp).total_seconds()
        self._prev_timestamp = now

        nic = counters_per_nic[name]
        bytes_sent = nic.bytes_sent
        bytes_recv = nic.bytes_recv
        packets_sent = nic.packets_sent
        packets_recv = nic.packets_recv

        result.set_state("online")

        if self.config.bytes:
            result.set("bytes_sent", bytes_sent)
            result.set("bytes_recv", bytes_recv)
        if self.config.packets:
            result.set("packets_sent", packets_sent)
            result.set("packets_recv", packets_recv)
        if self.config.errors:
            result.set("errin", nic.errin)
            result.set("errout", nic.errout)
        if self.config.drops:
            result.set("dropin", nic.dropin)
            result.set("dropout", nic.dropout)

        if self.config.rate and time_delta is not None:
            sent_rate_b = _calc_rate(bytes_sent, self._prev_bytes_sent, time_delta)
            recv_rate_b = _calc_rate(bytes_recv, self._prev_bytes_recv, time_delta)
            if sent_rate_b is not None:
                result.set("bytes_sent_rate", round(sent_rate_b / 1024, 2))
            if recv_rate_b is not None:
                result.set("bytes_recv_rate", round(recv_rate_b / 1024, 2))
        self._prev_bytes_sent = float(bytes_sent)
        self._prev_bytes_recv = float(bytes_recv)

        if self.config.packets_rate and time_delta is not None:
            ps_rate = _calc_rate(packets_sent, self._prev_packets_sent, time_delta)
            pr_rate = _calc_rate(packets_recv, self._prev_packets_recv, time_delta)
            if ps_rate is not None:
                result.set("packets_sent_rate", round(ps_rate, 1))
            if pr_rate is not None:
                result.set("packets_recv_rate", round(pr_rate, 1))
        self._prev_packets_sent = float(packets_sent)
        self._prev_packets_recv = float(packets_recv)

        try:
            stats = psutil.net_if_stats()
        except Exception:
            stats = {}
        if name in stats:
            s = stats[name]
            if self.config.isup:
                result.set("isup", s.isup)
            if self.config.speed:
                result.set("speed", s.speed)
            if self.config.mtu:
                result.set("mtu", s.mtu)
            if self.config.duplex:
                result.set(
                    "duplex",
                    s.duplex.name.lower() if hasattr(s.duplex, "name") else str(s.duplex).lower(),
                )

        if self.config.rssi:
            rssi = await _get_wifi_rssi(name)
            if rssi is not None:
                result.set("rssi", rssi)

        return result
