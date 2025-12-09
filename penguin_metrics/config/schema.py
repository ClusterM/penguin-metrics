"""
Configuration schema with dataclasses for validation and type safety.

Defines all configuration sections, their fields, defaults, and validation.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from pathlib import Path

from .parser import ConfigDocument, Block, Directive


class DeviceGrouping(Enum):
    """Strategy for grouping sensors into Home Assistant devices."""
    PER_SOURCE = "per_source"  # Each process/service/container = separate device
    SINGLE = "single"          # All sensors in one device
    HYBRID = "hybrid"          # System metrics in one device, others separate


class ProcessMatchType(Enum):
    """How to match/find a process."""
    NAME = "name"              # Exact process name (comm)
    PATTERN = "pattern"        # Regex pattern on cmdline
    PID = "pid"                # Exact PID
    PIDFILE = "pidfile"        # Read PID from file
    CMDLINE = "cmdline"        # Substring in cmdline


class ServiceMatchType(Enum):
    """How to match/find a systemd service."""
    UNIT = "unit"              # Exact unit name
    PATTERN = "pattern"        # Glob pattern on unit name


class ContainerMatchType(Enum):
    """How to match/find a Docker container."""
    NAME = "name"              # Exact container name
    PATTERN = "pattern"        # Regex pattern on name
    IMAGE = "image"            # Image name
    LABEL = "label"            # Container label


class RetainMode(Enum):
    """MQTT retain message modes."""
    OFF = "off"                # Don't retain any messages
    ONLINE = "online"          # Only retain availability (LWT) status
    FULL = "full"              # Retain all messages (default)


@dataclass
class DeviceConfig:
    """Home Assistant device configuration."""
    name: str | None = None
    manufacturer: str = "Penguin Metrics"
    model: str = "Linux Monitor"
    hw_version: str | None = None
    sw_version: str | None = None
    identifiers: list[str] = field(default_factory=list)
    
    @classmethod
    def from_block(cls, block: Block | None) -> "DeviceConfig":
        """Create DeviceConfig from a parsed 'device' block."""
        if block is None:
            return cls()
        
        return cls(
            name=block.get_value("name"),
            manufacturer=block.get_value("manufacturer", "Penguin Metrics"),
            model=block.get_value("model", "Linux Monitor"),
            hw_version=block.get_value("hw_version"),
            sw_version=block.get_value("sw_version"),
        )


@dataclass
class MQTTConfig:
    """MQTT connection configuration."""
    host: str = "localhost"
    port: int = 1883
    username: str | None = None
    password: str | None = None
    client_id: str | None = None
    topic_prefix: str = "penguin_metrics"
    qos: int = 1
    retain: RetainMode = RetainMode.ONLINE
    keepalive: int = 60
    
    @classmethod
    def from_block(cls, block: Block | None) -> "MQTTConfig":
        """Create MQTTConfig from a parsed 'mqtt' block."""
        if block is None:
            return cls()
        
        # Parse retain mode
        retain_val = block.get_value("retain", "full")
        if isinstance(retain_val, bool):
            # Backwards compatibility: on -> online, off -> off
            retain_mode = RetainMode.ONLINE if retain_val else RetainMode.OFF
        else:
            retain_str = str(retain_val).lower()
            retain_map = {
                "off": RetainMode.OFF,
                "online": RetainMode.ONLINE,
                "full": RetainMode.FULL,
                "on": RetainMode.ONLINE,  # Backwards compatibility
            }
            retain_mode = retain_map.get(retain_str, RetainMode.ONLINE)
        
        return cls(
            host=block.get_value("host", "localhost"),
            port=int(block.get_value("port", 1883)),
            username=block.get_value("username"),
            password=block.get_value("password"),
            client_id=block.get_value("client_id"),
            topic_prefix=block.get_value("topic_prefix", "penguin_metrics"),
            qos=int(block.get_value("qos", 1)),
            retain=retain_mode,
            keepalive=int(block.get_value("keepalive", 60)),
        )
    
    def should_retain_data(self) -> bool:
        """Check if data messages should be retained."""
        return self.retain == RetainMode.FULL
    
    def should_retain_status(self) -> bool:
        """Check if status/availability messages should be retained."""
        return self.retain in (RetainMode.FULL, RetainMode.ONLINE)


@dataclass
class HomeAssistantConfig:
    """Home Assistant integration configuration."""
    discovery: bool = True
    discovery_prefix: str = "homeassistant"
    device_grouping: DeviceGrouping = DeviceGrouping.PER_SOURCE
    device: DeviceConfig = field(default_factory=DeviceConfig)
    state_file: str = "/var/lib/penguin-metrics/registered_sensors.json"
    
    @classmethod
    def from_block(cls, block: Block | None) -> "HomeAssistantConfig":
        """Create HomeAssistantConfig from a parsed 'homeassistant' block."""
        if block is None:
            return cls()
        
        grouping_str = block.get_value("device_grouping", "per_source")
        try:
            grouping = DeviceGrouping(grouping_str)
        except ValueError:
            grouping = DeviceGrouping.PER_SOURCE
        
        return cls(
            discovery=bool(block.get_value("discovery", True)),
            discovery_prefix=block.get_value("discovery_prefix", "homeassistant"),
            device_grouping=grouping,
            device=DeviceConfig.from_block(block.get_block("device")),
            state_file=block.get_value("state_file", "/var/lib/penguin-metrics/registered_sensors.json"),
        )


@dataclass
class LoggingConfig:
    """Logging configuration."""
    level: str = "info"  # debug, info, warning, error
    file: str | None = None  # Log file path
    file_level: str = "debug"  # File log level
    file_max_size: int = 10  # Max file size in MB
    file_keep: int = 5  # Number of backup files to keep
    colors: bool = True  # Colored console output
    format: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    
    @classmethod
    def from_block(cls, block: Block | None) -> "LoggingConfig":
        """Create LoggingConfig from a parsed 'logging' block."""
        if block is None:
            return cls()
        
        return cls(
            level=block.get_value("level", "info"),
            file=block.get_value("file"),
            file_level=block.get_value("file_level", "debug"),
            file_max_size=int(block.get_value("file_max_size", 10)),
            file_keep=int(block.get_value("file_keep", 5)),
            colors=bool(block.get_value("colors", True)),
            format=block.get_value("format", "%(asctime)s [%(levelname)s] %(name)s: %(message)s"),
        )


@dataclass
class SystemDefaultsConfig:
    """Default settings for system collectors."""
    cpu: bool = True
    cpu_per_core: bool = False
    memory: bool = True
    swap: bool = True
    load: bool = True
    uptime: bool = True
    gpu: bool = False
    
    @classmethod
    def from_block(cls, block: Block | None) -> "SystemDefaultsConfig":
        if block is None:
            return cls()
        return cls(
            cpu=bool(block.get_value("cpu", True)),
            cpu_per_core=bool(block.get_value("cpu_per_core", False)),
            memory=bool(block.get_value("memory", True)),
            swap=bool(block.get_value("swap", True)),
            load=bool(block.get_value("load", True)),
            uptime=bool(block.get_value("uptime", True)),
            gpu=bool(block.get_value("gpu", False)),
        )


@dataclass
class ProcessDefaultsConfig:
    """Default settings for process collectors."""
    cpu: bool = True
    memory: bool = True
    smaps: bool | None = None  # None = use global smaps setting
    io: bool = False
    fds: bool = False
    threads: bool = False
    aggregate: bool = False
    
    @classmethod
    def from_block(cls, block: Block | None) -> "ProcessDefaultsConfig":
        if block is None:
            return cls()
        smaps_val = block.get_value("smaps")
        return cls(
            cpu=bool(block.get_value("cpu", True)),
            memory=bool(block.get_value("memory", True)),
            smaps=None if smaps_val is None else bool(smaps_val),
            io=bool(block.get_value("io", False)),
            fds=bool(block.get_value("fds", False)),
            threads=bool(block.get_value("threads", False)),
            aggregate=bool(block.get_value("aggregate", False)),
        )


@dataclass
class ServiceDefaultsConfig:
    """Default settings for service collectors."""
    cpu: bool = True
    memory: bool = True
    smaps: bool | None = None
    state: bool = True
    restart_count: bool = False
    
    @classmethod
    def from_block(cls, block: Block | None) -> "ServiceDefaultsConfig":
        if block is None:
            return cls()
        smaps_val = block.get_value("smaps")
        return cls(
            cpu=bool(block.get_value("cpu", True)),
            memory=bool(block.get_value("memory", True)),
            smaps=None if smaps_val is None else bool(smaps_val),
            state=bool(block.get_value("state", True)),
            restart_count=bool(block.get_value("restart_count", False)),
        )


@dataclass
class ContainerDefaultsConfig:
    """Default settings for container collectors."""
    cpu: bool = True
    memory: bool = True
    network: bool = False
    disk: bool = False
    state: bool = True
    health: bool = False
    uptime: bool = False
    
    @classmethod
    def from_block(cls, block: Block | None) -> "ContainerDefaultsConfig":
        if block is None:
            return cls()
        return cls(
            cpu=bool(block.get_value("cpu", True)),
            memory=bool(block.get_value("memory", True)),
            network=bool(block.get_value("network", False)),
            disk=bool(block.get_value("disk", False)),
            state=bool(block.get_value("state", True)),
            health=bool(block.get_value("health", False)),
            uptime=bool(block.get_value("uptime", False)),
        )


@dataclass
class BatteryDefaultsConfig:
    """Default settings for battery collectors."""
    capacity: bool = True
    status: bool = True
    voltage: bool = False
    current: bool = False
    power: bool = False
    health: bool = False
    cycles: bool = False
    temperature: bool = False
    time_to_empty: bool = False
    time_to_full: bool = False
    
    @classmethod
    def from_block(cls, block: Block | None) -> "BatteryDefaultsConfig":
        if block is None:
            return cls()
        return cls(
            capacity=bool(block.get_value("capacity", True)),
            status=bool(block.get_value("status", True)),
            voltage=bool(block.get_value("voltage", False)),
            current=bool(block.get_value("current", False)),
            power=bool(block.get_value("power", False)),
            health=bool(block.get_value("health", False)),
            cycles=bool(block.get_value("cycles", False)),
            temperature=bool(block.get_value("temperature", False)),
            time_to_empty=bool(block.get_value("time_to_empty", False)),
            time_to_full=bool(block.get_value("time_to_full", False)),
        )


@dataclass
class CustomDefaultsConfig:
    """Default settings for custom collectors."""
    type: str = "number"
    timeout: float = 5.0
    
    @classmethod
    def from_block(cls, block: Block | None) -> "CustomDefaultsConfig":
        if block is None:
            return cls()
        return cls(
            type=block.get_value("type", "number"),
            timeout=float(block.get_value("timeout", 5.0)),
        )


@dataclass
class DefaultsConfig:
    """Default settings inherited by collectors."""
    update_interval: float = 10.0  # seconds
    smaps: bool = False
    availability_topic: bool = True
    auto_refresh_interval: float = 0  # seconds, 0 = disabled
    
    # Per-source-type defaults
    system: SystemDefaultsConfig = field(default_factory=SystemDefaultsConfig)
    process: ProcessDefaultsConfig = field(default_factory=ProcessDefaultsConfig)
    service: ServiceDefaultsConfig = field(default_factory=ServiceDefaultsConfig)
    container: ContainerDefaultsConfig = field(default_factory=ContainerDefaultsConfig)
    battery: BatteryDefaultsConfig = field(default_factory=BatteryDefaultsConfig)
    custom: CustomDefaultsConfig = field(default_factory=CustomDefaultsConfig)
    
    @classmethod
    def from_block(cls, block: Block | None) -> "DefaultsConfig":
        """Create DefaultsConfig from a parsed 'defaults' block."""
        if block is None:
            return cls()
        
        interval = block.get_value("update_interval", 10.0)
        if isinstance(interval, str):
            interval = 10.0
        
        refresh = block.get_value("auto_refresh_interval", 0)
        if isinstance(refresh, str):
            refresh = 0
        
        return cls(
            update_interval=float(interval),
            smaps=bool(block.get_value("smaps", False)),
            availability_topic=bool(block.get_value("availability_topic", True)),
            auto_refresh_interval=float(refresh),
            system=SystemDefaultsConfig.from_block(block.get_block("system")),
            process=ProcessDefaultsConfig.from_block(block.get_block("process")),
            service=ServiceDefaultsConfig.from_block(block.get_block("service")),
            container=ContainerDefaultsConfig.from_block(block.get_block("container")),
            battery=BatteryDefaultsConfig.from_block(block.get_block("battery")),
            custom=CustomDefaultsConfig.from_block(block.get_block("custom")),
        )


@dataclass
class AutoDiscoveryConfig:
    """
    Unified auto-discovery configuration.
    
    Used by: temperatures, batteries, containers, services
    
    Example:
        temperatures {
            auto on;
            filter "nvme_*";
            filter "soc_*";
            exclude "internal*";
            exclude "test*";
        }
    """
    enabled: bool = False
    filters: list[str] = field(default_factory=list)    # Include only matching (glob patterns)
    excludes: list[str] = field(default_factory=list)   # Exclude matching (glob patterns)
    
    @classmethod
    def from_block(cls, block: Block | None) -> "AutoDiscoveryConfig":
        """Create AutoDiscoveryConfig from a parsed block."""
        if block is None:
            return cls()
        
        # "auto on;" or "auto off;"
        auto_val = block.get_value("auto")
        enabled = False
        if auto_val is not None:
            if isinstance(auto_val, bool):
                enabled = auto_val
            elif isinstance(auto_val, str):
                enabled = auto_val.lower() in ("on", "true", "yes", "1")
        
        # Get all filter and exclude values
        filters = block.get_all_values("filter")
        excludes = block.get_all_values("exclude")
        
        return cls(
            enabled=enabled,
            filters=filters,
            excludes=excludes,
        )
    
    def matches(self, name: str) -> bool:
        """
        Check if a name matches the filter/exclude patterns.
        
        Args:
            name: Name to check
            
        Returns:
            True if name should be included
        """
        import fnmatch
        
        # Check excludes first - if any matches, exclude
        for pattern in self.excludes:
            if fnmatch.fnmatch(name, pattern):
                return False
        
        # Check filters - if any matches, include
        if self.filters:
            for pattern in self.filters:
                if fnmatch.fnmatch(name, pattern):
                    return True
            return False  # Has filters but none matched
        
        # No filters = include all (that weren't excluded)
        return True


@dataclass
class SystemConfig:
    """System-wide metrics configuration."""
    name: str = "system"  # Optional, not used in topics
    id: str | None = None
    device: DeviceConfig = field(default_factory=DeviceConfig)
    
    # Metrics flags
    cpu: bool = True
    cpu_per_core: bool = False
    memory: bool = True
    swap: bool = True
    load: bool = True
    uptime: bool = True
    gpu: bool = False
    
    # Settings
    update_interval: float | None = None  # None = use defaults
    
    @classmethod
    def from_block(cls, block: Block, defaults: DefaultsConfig) -> "SystemConfig":
        """Create SystemConfig from a parsed 'system' block."""
        name = block.name or "system"
        sd = defaults.system  # System-specific defaults
        
        interval = block.get_value("update_interval")
        if interval is None:
            interval = defaults.update_interval
        
        # Helper to get value with source-type default fallback
        def get_bool(name: str, sd_val: bool) -> bool:
            val = block.get_value(name)
            return bool(val) if val is not None else sd_val
        
        return cls(
            name=name,
            id=block.get_value("id"),
            device=DeviceConfig.from_block(block.get_block("device")),
            cpu=get_bool("cpu", sd.cpu),
            cpu_per_core=get_bool("cpu_per_core", sd.cpu_per_core),
            memory=get_bool("memory", sd.memory),
            swap=get_bool("swap", sd.swap),
            load=get_bool("load", sd.load),
            uptime=get_bool("uptime", sd.uptime),
            gpu=get_bool("gpu", sd.gpu),
            update_interval=float(interval) if interval else None,
        )


@dataclass
class ProcessMatchConfig:
    """Process matching configuration."""
    type: ProcessMatchType
    value: str | int
    
    @classmethod
    def from_directive(cls, directive: Directive | None) -> "ProcessMatchConfig | None":
        """Create ProcessMatchConfig from a 'match' directive."""
        if directive is None:
            return None
        
        if len(directive.values) < 2:
            return None
        
        match_type_str = str(directive.values[0]).lower()
        match_value = directive.values[1]
        
        type_map = {
            "name": ProcessMatchType.NAME,
            "pattern": ProcessMatchType.PATTERN,
            "pid": ProcessMatchType.PID,
            "pidfile": ProcessMatchType.PIDFILE,
            "cmdline": ProcessMatchType.CMDLINE,
            "cmdline_contains": ProcessMatchType.CMDLINE,
        }
        
        match_type = type_map.get(match_type_str)
        if match_type is None:
            return None
        
        return cls(type=match_type, value=match_value)


@dataclass
class ProcessConfig:
    """Process monitoring configuration."""
    name: str
    id: str | None = None
    match: ProcessMatchConfig | None = None
    device: DeviceConfig = field(default_factory=DeviceConfig)
    sensor_prefix: str | None = None
    
    # Metrics flags
    cpu: bool = True
    memory: bool = True
    smaps: bool | None = None  # None = use defaults
    io: bool = False
    fds: bool = False
    threads: bool = False
    aggregate: bool = False  # Sum metrics from all matching processes
    
    # Settings
    update_interval: float | None = None
    
    @classmethod
    def from_block(cls, block: Block, defaults: DefaultsConfig) -> "ProcessConfig":
        """Create ProcessConfig from a parsed 'process' block."""
        name = block.name or "process"
        pd = defaults.process  # Process-specific defaults
        
        # smaps: check block, then process defaults, then global
        smaps_val = block.get_value("smaps")
        if smaps_val is not None:
            smaps = bool(smaps_val)
        elif pd.smaps is not None:
            smaps = pd.smaps
        else:
            smaps = None  # Will use global defaults.smaps
        
        interval = block.get_value("update_interval")
        if interval is None:
            interval = defaults.update_interval
        
        # Helper to get value with source-type default fallback
        def get_bool(name: str, pd_val: bool) -> bool:
            val = block.get_value(name)
            return bool(val) if val is not None else pd_val
        
        return cls(
            name=name,
            id=block.get_value("id"),
            match=ProcessMatchConfig.from_directive(block.get_directive("match")),
            device=DeviceConfig.from_block(block.get_block("device")),
            sensor_prefix=block.get_value("sensor_prefix"),
            cpu=get_bool("cpu", pd.cpu),
            memory=get_bool("memory", pd.memory),
            smaps=smaps,
            io=get_bool("io", pd.io),
            fds=get_bool("fds", pd.fds),
            threads=get_bool("threads", pd.threads),
            aggregate=get_bool("aggregate", pd.aggregate),
            update_interval=float(interval) if interval else None,
        )
    
    def should_use_smaps(self, defaults: DefaultsConfig) -> bool:
        """Determine if smaps should be used (respecting defaults)."""
        if self.smaps is not None:
            return self.smaps
        return defaults.smaps
    
    @classmethod
    def from_defaults(cls, name: str, match: "ProcessMatchConfig", defaults: DefaultsConfig) -> "ProcessConfig":
        """Create ProcessConfig from defaults (for auto-discovery)."""
        pd = defaults.process
        return cls(
            name=name,
            match=match,
            cpu=pd.cpu,
            memory=pd.memory,
            smaps=pd.smaps,
            io=pd.io,
            fds=pd.fds,
            threads=pd.threads,
            aggregate=pd.aggregate,
            update_interval=defaults.update_interval,
        )


@dataclass
class ServiceMatchConfig:
    """Service matching configuration."""
    type: ServiceMatchType
    value: str
    
    @classmethod
    def from_directive(cls, directive: Directive | None) -> "ServiceMatchConfig | None":
        """Create ServiceMatchConfig from a 'match' directive."""
        if directive is None:
            return None
        
        if len(directive.values) < 2:
            return None
        
        match_type_str = str(directive.values[0]).lower()
        match_value = str(directive.values[1])
        
        type_map = {
            "unit": ServiceMatchType.UNIT,
            "pattern": ServiceMatchType.PATTERN,
        }
        
        match_type = type_map.get(match_type_str)
        if match_type is None:
            return None
        
        return cls(type=match_type, value=match_value)


@dataclass
class ServiceConfig:
    """Systemd service monitoring configuration."""
    name: str
    id: str | None = None
    match: ServiceMatchConfig | None = None
    device: DeviceConfig = field(default_factory=DeviceConfig)
    
    # Metrics flags
    cpu: bool = True
    memory: bool = True
    smaps: bool | None = None
    state: bool = True
    restart_count: bool = False
    
    # Settings
    update_interval: float | None = None
    
    @classmethod
    def from_block(cls, block: Block, defaults: DefaultsConfig) -> "ServiceConfig":
        """Create ServiceConfig from a parsed 'service' block."""
        name = block.name or "service"
        svd = defaults.service  # Service-specific defaults
        
        # smaps: check block, then service defaults, then global
        smaps_val = block.get_value("smaps")
        if smaps_val is not None:
            smaps = bool(smaps_val)
        elif svd.smaps is not None:
            smaps = svd.smaps
        else:
            smaps = None
        
        interval = block.get_value("update_interval")
        if interval is None:
            interval = defaults.update_interval
        
        def get_bool(name: str, svd_val: bool) -> bool:
            val = block.get_value(name)
            return bool(val) if val is not None else svd_val
        
        return cls(
            name=name,
            id=block.get_value("id"),
            match=ServiceMatchConfig.from_directive(block.get_directive("match")),
            device=DeviceConfig.from_block(block.get_block("device")),
            cpu=get_bool("cpu", svd.cpu),
            memory=get_bool("memory", svd.memory),
            smaps=smaps,
            state=get_bool("state", svd.state),
            restart_count=get_bool("restart_count", svd.restart_count),
            update_interval=float(interval) if interval else None,
        )
    
    def should_use_smaps(self, defaults: DefaultsConfig) -> bool:
        """Determine if smaps should be used (respecting defaults)."""
        if self.smaps is not None:
            return self.smaps
        return defaults.smaps
    
    @classmethod
    def from_defaults(cls, name: str, match: "ServiceMatchConfig", defaults: DefaultsConfig) -> "ServiceConfig":
        """Create ServiceConfig from defaults (for auto-discovery)."""
        svd = defaults.service
        return cls(
            name=name,
            match=match,
            cpu=svd.cpu,
            memory=svd.memory,
            smaps=svd.smaps,
            state=svd.state,
            restart_count=svd.restart_count,
            update_interval=defaults.update_interval,
        )


@dataclass
class ContainerMatchConfig:
    """Container matching configuration."""
    type: ContainerMatchType
    value: str
    
    @classmethod
    def from_directive(cls, directive: Directive | None) -> "ContainerMatchConfig | None":
        """Create ContainerMatchConfig from a 'match' directive."""
        if directive is None:
            return None
        
        if len(directive.values) < 2:
            return None
        
        match_type_str = str(directive.values[0]).lower()
        match_value = str(directive.values[1])
        
        type_map = {
            "name": ContainerMatchType.NAME,
            "pattern": ContainerMatchType.PATTERN,
            "image": ContainerMatchType.IMAGE,
            "label": ContainerMatchType.LABEL,
        }
        
        match_type = type_map.get(match_type_str)
        if match_type is None:
            return None
        
        return cls(type=match_type, value=match_value)


@dataclass
class ContainerConfig:
    """Docker container monitoring configuration."""
    name: str
    id: str | None = None
    match: ContainerMatchConfig | None = None
    device: DeviceConfig = field(default_factory=DeviceConfig)
    auto_discover: bool = False
    
    # Metrics flags
    cpu: bool = True
    memory: bool = True
    network: bool = False
    disk: bool = False
    state: bool = True
    health: bool = False
    uptime: bool = False
    
    # Settings
    update_interval: float | None = None
    
    @classmethod
    def from_block(cls, block: Block, defaults: DefaultsConfig) -> "ContainerConfig":
        """Create ContainerConfig from a parsed 'container' block."""
        name = block.name or "container"
        cd = defaults.container  # Container-specific defaults
        
        interval = block.get_value("update_interval")
        if interval is None:
            interval = defaults.update_interval
        
        def get_bool(name: str, cd_val: bool) -> bool:
            val = block.get_value(name)
            return bool(val) if val is not None else cd_val
        
        return cls(
            name=name,
            id=block.get_value("id"),
            match=ContainerMatchConfig.from_directive(block.get_directive("match")),
            device=DeviceConfig.from_block(block.get_block("device")),
            auto_discover=bool(block.get_value("auto_discover", False)),
            cpu=get_bool("cpu", cd.cpu),
            memory=get_bool("memory", cd.memory),
            network=get_bool("network", cd.network),
            disk=get_bool("disk", cd.disk),
            state=get_bool("state", cd.state),
            health=get_bool("health", cd.health),
            uptime=get_bool("uptime", cd.uptime),
            update_interval=float(interval) if interval else None,
        )
    
    @classmethod
    def from_defaults(cls, name: str, match: "ContainerMatchConfig", defaults: DefaultsConfig) -> "ContainerConfig":
        """Create ContainerConfig from defaults (for auto-discovery)."""
        cd = defaults.container
        return cls(
            name=name,
            match=match,
            cpu=cd.cpu,
            memory=cd.memory,
            network=cd.network,
            disk=cd.disk,
            state=cd.state,
            health=cd.health,
            uptime=cd.uptime,
            update_interval=defaults.update_interval,
        )


@dataclass
class TemperatureConfig:
    """Temperature sensor configuration."""
    name: str
    id: str | None = None
    zone: str | None = None       # Thermal zone name (e.g., "soc-thermal", "thermal_zone0")
    hwmon: str | None = None      # Hwmon sensor name (e.g., "soc_thermal_sensor0")
    path: str | None = None       # Direct path to temp file
    update_interval: float | None = None
    
    @classmethod
    def from_block(cls, block: Block, defaults: DefaultsConfig) -> "TemperatureConfig":
        """Create TemperatureConfig from a parsed 'temperature' block."""
        name = block.name or "temperature"
        
        interval = block.get_value("update_interval")
        if interval is None:
            interval = defaults.update_interval
        
        return cls(
            name=name,
            id=block.get_value("id"),
            zone=block.get_value("zone"),
            hwmon=block.get_value("hwmon"),
            path=block.get_value("path"),
            update_interval=float(interval) if interval else None,
        )


@dataclass
class BatteryConfig:
    """Battery monitoring configuration."""
    name: str
    id: str | None = None
    path: str | None = None
    battery_name: str | None = None  # BAT0, BAT1, etc.
    device: DeviceConfig = field(default_factory=DeviceConfig)
    
    # Metrics flags
    capacity: bool = True
    status: bool = True
    voltage: bool = False
    current: bool = False
    power: bool = False
    health: bool = False
    cycles: bool = False
    temperature: bool = False
    time_to_empty: bool = False
    time_to_full: bool = False
    
    # Settings
    update_interval: float | None = None
    
    @classmethod
    def from_block(cls, block: Block, defaults: DefaultsConfig) -> "BatteryConfig":
        """Create BatteryConfig from a parsed 'battery' block."""
        name = block.name or "battery"
        bd = defaults.battery  # Battery-specific defaults
        
        interval = block.get_value("update_interval")
        if interval is None:
            interval = defaults.update_interval
        
        def get_bool(name: str, bd_val: bool) -> bool:
            val = block.get_value(name)
            return bool(val) if val is not None else bd_val
        
        return cls(
            name=name,
            id=block.get_value("id"),
            path=block.get_value("path"),
            battery_name=block.get_value("name"),  # the battery name like BAT0
            device=DeviceConfig.from_block(block.get_block("device")),
            capacity=get_bool("capacity", bd.capacity),
            status=get_bool("status", bd.status),
            voltage=get_bool("voltage", bd.voltage),
            current=get_bool("current", bd.current),
            power=get_bool("power", bd.power),
            health=get_bool("health", bd.health),
            cycles=get_bool("cycles", bd.cycles),
            temperature=get_bool("temperature", bd.temperature),
            time_to_empty=get_bool("time_to_empty", bd.time_to_empty),
            time_to_full=get_bool("time_to_full", bd.time_to_full),
            update_interval=float(interval) if interval else None,
        )


@dataclass
class CustomSensorConfig:
    """Custom command/script sensor configuration."""
    name: str
    id: str | None = None
    command: str | None = None
    script: str | None = None
    device: DeviceConfig = field(default_factory=DeviceConfig)
    
    # Output parsing
    type: str = "number"  # number, string, json
    unit: str | None = None
    scale: float = 1.0
    
    # Home Assistant
    device_class: str | None = None
    state_class: str | None = None
    
    # Settings
    update_interval: float | None = None
    timeout: float = 5.0
    
    @classmethod
    def from_block(cls, block: Block, defaults: DefaultsConfig) -> "CustomSensorConfig":
        """Create CustomSensorConfig from a parsed 'custom' block."""
        name = block.name or "custom"
        cud = defaults.custom  # Custom-specific defaults
        
        interval = block.get_value("update_interval")
        if interval is None:
            interval = defaults.update_interval
        
        # Get type with fallback to custom defaults
        type_val = block.get_value("type")
        type_str = type_val if type_val is not None else cud.type
        
        # Get timeout with fallback to custom defaults
        timeout_val = block.get_value("timeout")
        timeout = float(timeout_val) if timeout_val is not None else cud.timeout
        
        return cls(
            name=name,
            id=block.get_value("id"),
            command=block.get_value("command"),
            script=block.get_value("script"),
            device=DeviceConfig.from_block(block.get_block("device")),
            type=type_str,
            unit=block.get_value("unit"),
            scale=float(block.get_value("scale", 1.0)),
            device_class=block.get_value("device_class"),
            state_class=block.get_value("state_class"),
            update_interval=float(interval) if interval else None,
            timeout=timeout,
        )


@dataclass
class Config:
    """Complete application configuration."""
    mqtt: MQTTConfig = field(default_factory=MQTTConfig)
    homeassistant: HomeAssistantConfig = field(default_factory=HomeAssistantConfig)
    defaults: DefaultsConfig = field(default_factory=DefaultsConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    
    # Auto-discovery settings (plural blocks: temperatures, batteries, etc.)
    auto_temperatures: AutoDiscoveryConfig = field(default_factory=AutoDiscoveryConfig)
    auto_batteries: AutoDiscoveryConfig = field(default_factory=AutoDiscoveryConfig)
    auto_containers: AutoDiscoveryConfig = field(default_factory=AutoDiscoveryConfig)
    auto_services: AutoDiscoveryConfig = field(default_factory=AutoDiscoveryConfig)
    auto_processes: AutoDiscoveryConfig = field(default_factory=AutoDiscoveryConfig)  # Not implemented
    
    # Manual collectors (singular blocks: temperature, battery, etc.)
    system: list[SystemConfig] = field(default_factory=list)
    processes: list[ProcessConfig] = field(default_factory=list)
    services: list[ServiceConfig] = field(default_factory=list)
    containers: list[ContainerConfig] = field(default_factory=list)
    temperatures: list[TemperatureConfig] = field(default_factory=list)
    batteries: list[BatteryConfig] = field(default_factory=list)
    custom: list[CustomSensorConfig] = field(default_factory=list)
    
    @classmethod
    def from_document(cls, doc: ConfigDocument) -> "Config":
        """Create Config from a parsed ConfigDocument."""
        config = cls()
        
        # Parse global blocks
        config.mqtt = MQTTConfig.from_block(doc.get_block("mqtt"))
        config.homeassistant = HomeAssistantConfig.from_block(doc.get_block("homeassistant"))
        config.defaults = DefaultsConfig.from_block(doc.get_block("defaults"))
        config.logging = LoggingConfig.from_block(doc.get_block("logging"))
        
        # Parse auto-discovery blocks (plural names)
        config.auto_temperatures = AutoDiscoveryConfig.from_block(doc.get_block("temperatures"))
        config.auto_batteries = AutoDiscoveryConfig.from_block(doc.get_block("batteries"))
        config.auto_containers = AutoDiscoveryConfig.from_block(doc.get_block("containers"))
        config.auto_services = AutoDiscoveryConfig.from_block(doc.get_block("services"))
        config.auto_processes = AutoDiscoveryConfig.from_block(doc.get_block("processes"))
        
        # Parse collector blocks (singular names for manual configuration)
        for block in doc.get_blocks("system"):
            config.system.append(SystemConfig.from_block(block, config.defaults))
        
        for block in doc.get_blocks("process"):
            config.processes.append(ProcessConfig.from_block(block, config.defaults))
        
        for block in doc.get_blocks("service"):
            config.services.append(ServiceConfig.from_block(block, config.defaults))
        
        for block in doc.get_blocks("container"):
            config.containers.append(ContainerConfig.from_block(block, config.defaults))
        
        for block in doc.get_blocks("temperature"):
            config.temperatures.append(TemperatureConfig.from_block(block, config.defaults))
        
        for block in doc.get_blocks("battery"):
            config.batteries.append(BatteryConfig.from_block(block, config.defaults))
        
        for block in doc.get_blocks("custom"):
            config.custom.append(CustomSensorConfig.from_block(block, config.defaults))
        
        return config

