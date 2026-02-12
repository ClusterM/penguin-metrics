"""
Configuration schema with dataclasses for validation and type safety.

Defines all configuration sections, their fields, defaults, and validation.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .parser import Block, ConfigDocument, Directive


class ProcessMatchType(Enum):
    """How to match/find a process."""

    NAME = "name"  # Exact process name (comm)
    PATTERN = "pattern"  # Regex pattern on cmdline
    PID = "pid"  # Exact PID
    PIDFILE = "pidfile"  # Read PID from file
    CMDLINE = "cmdline"  # Substring in cmdline


class ServiceMatchType(Enum):
    """How to match/find a systemd service."""

    UNIT = "unit"  # Exact unit name
    PATTERN = "pattern"  # Glob pattern on unit name


class ContainerMatchType(Enum):
    """How to match/find a Docker container."""

    NAME = "name"  # Exact container name
    PATTERN = "pattern"  # Regex pattern on name
    IMAGE = "image"  # Image name
    LABEL = "label"  # Container label


class RetainMode(Enum):
    """MQTT retain message modes."""

    OFF = "off"  # Don't retain any messages
    ON = "on"  # Retain all messages (default)


@dataclass
class DeviceConfig:
    """Home Assistant device configuration."""

    identifiers: list[str] = field(default_factory=list)
    # All fields (including name, manufacturer, model, etc.) go to extra_fields
    extra_fields: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_block(cls, block: Block | None) -> "DeviceConfig":
        """Create DeviceConfig from a parsed 'device' block."""
        if block is None:
            return cls()

        # Collect all fields into extra_fields
        extra_fields: dict[str, Any] = {}
        for directive in block.directives:
            if directive.name == "identifiers":
                # identifiers is special - it's a list
                continue
            elif len(directive.values) == 1:
                extra_fields[directive.name] = directive.values[0]
            else:
                extra_fields[directive.name] = directive.values

        # Get identifiers separately (if specified)
        identifiers = block.get_all_values("identifiers")

        return cls(
            identifiers=identifiers,
            extra_fields=extra_fields,
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
    retain: RetainMode = RetainMode.ON
    keepalive: int = 60

    @classmethod
    def from_block(cls, block: Block | None) -> "MQTTConfig":
        """Create MQTTConfig from a parsed 'mqtt' block."""
        if block is None:
            return cls()

        # Parse retain mode
        retain_val = block.get_value("retain", "full")
        if isinstance(retain_val, bool):
            retain_mode = RetainMode.ON if retain_val else RetainMode.OFF
        else:
            retain_str = str(retain_val).lower()
            retain_map = {
                "off": RetainMode.OFF,
                "on": RetainMode.ON,
                "true": RetainMode.ON,
                "false": RetainMode.OFF,
            }
            retain_mode = retain_map.get(retain_str, RetainMode.ON)

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

    def should_retain(self) -> bool:
        """Check if messages should be retained."""
        return self.retain == RetainMode.ON

    def should_retain_status(self) -> bool:
        """
        Check if availability/status messages should be retained.

        Currently mirrors retain mode for data; kept separate for future
        configurability.
        """
        return self.should_retain()


@dataclass
class HomeAssistantConfig:
    """Home Assistant integration configuration."""

    discovery: bool = True
    discovery_prefix: str = "homeassistant"
    state_file: str = "/var/lib/penguin-metrics/registered_sensors.json"

    @classmethod
    def from_block(cls, block: Block | None) -> "HomeAssistantConfig":
        """Create HomeAssistantConfig from a parsed 'homeassistant' block."""
        if block is None:
            return cls()

        return cls(
            discovery=bool(block.get_value("discovery", True)),
            discovery_prefix=block.get_value("discovery_prefix", "homeassistant"),
            state_file=block.get_value(
                "state_file", "/var/lib/penguin-metrics/registered_sensors.json"
            ),
        )


@dataclass
class HomeAssistantSensorConfig:
    """
    Home Assistant sensor overrides.

    Allows overriding any Home Assistant discovery fields for sensors.
    Fields are passed directly to the discovery payload.

    Example:
        homeassistant {
            name "Custom Name";
            icon "mdi:custom-icon";
            unit_of_measurement "custom_unit";
            device_class "power";
            state_class "measurement";
            entity_category "diagnostic";
            enabled_by_default false;
        }
    """

    # Common fields (for convenience and validation)
    name: str | None = None
    icon: str | None = None
    unit_of_measurement: str | None = None
    device_class: str | None = None
    state_class: str | None = None
    entity_category: str | None = None
    enabled_by_default: bool | None = None

    # Arbitrary fields (for any other HA discovery fields)
    extra_fields: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_block(cls, block: Block | None) -> "HomeAssistantSensorConfig":
        """Create HomeAssistantSensorConfig from a parsed 'homeassistant' block."""
        if block is None:
            return cls()

        # Known fields
        name = block.get_value("name")
        icon = block.get_value("icon")
        unit_of_measurement = block.get_value("unit_of_measurement")
        device_class = block.get_value("device_class")
        state_class = block.get_value("state_class")
        entity_category = block.get_value("entity_category")
        enabled_by_default = block.get_value("enabled_by_default")

        # Convert enabled_by_default to bool if present
        if enabled_by_default is not None:
            enabled_by_default = bool(enabled_by_default)

        # Collect all other directives as extra fields
        extra_fields: dict[str, Any] = {}
        known_fields = {
            "name",
            "icon",
            "unit_of_measurement",
            "device_class",
            "state_class",
            "entity_category",
            "enabled_by_default",
        }

        for directive in block.directives:
            if directive.name not in known_fields:
                # Store as string if single value, list if multiple
                if len(directive.values) == 1:
                    extra_fields[directive.name] = directive.values[0]
                else:
                    extra_fields[directive.name] = directive.values

        return cls(
            name=name,
            icon=icon,
            unit_of_measurement=unit_of_measurement,
            device_class=device_class,
            state_class=state_class,
            entity_category=entity_category,
            enabled_by_default=enabled_by_default,
            extra_fields=extra_fields,
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
class ProcessDefaultsConfig:
    """Default settings for process collectors."""

    cpu: bool = True
    memory: bool = True
    smaps: bool | None = None  # None = use global smaps setting
    disk: bool = False
    disk_rate: bool = False
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
            disk=bool(block.get_value("disk", False)),
            disk_rate=bool(block.get_value("disk_rate", False)),
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
    disk: bool = False
    disk_rate: bool = False

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
            disk=bool(block.get_value("disk", False)),
            disk_rate=bool(block.get_value("disk_rate", False)),
        )


@dataclass
class ContainerDefaultsConfig:
    """Default settings for container collectors."""

    cpu: bool = True
    memory: bool = True
    network: bool = False
    network_rate: bool = False
    disk: bool = False
    disk_rate: bool = False
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
            network_rate=bool(block.get_value("network_rate", False)),
            disk=bool(block.get_value("disk", False)),
            disk_rate=bool(block.get_value("disk_rate", False)),
            state=bool(block.get_value("state", True)),
            health=bool(block.get_value("health", False)),
            uptime=bool(block.get_value("uptime", False)),
        )


@dataclass
class BatteryDefaultsConfig:
    """Default settings for battery collectors."""

    capacity: bool = True
    voltage: bool = True
    current: bool = True
    power: bool = True
    health: bool = True
    energy_now: bool = True
    energy_full: bool = True
    energy_full_design: bool = True
    cycles: bool = False
    temperature: bool = False
    time_to_empty: bool = False
    time_to_full: bool = False
    present: bool = False
    technology: bool = False
    voltage_max: bool = False
    voltage_min: bool = False
    voltage_max_design: bool = False
    voltage_min_design: bool = False
    constant_charge_current: bool = False
    constant_charge_current_max: bool = False
    charge_full_design: bool = False

    @classmethod
    def from_block(cls, block: Block | None) -> "BatteryDefaultsConfig":
        if block is None:
            return cls()
        defaults = cls()  # Get class defaults
        return cls(
            capacity=bool(block.get_value("capacity", defaults.capacity)),
            voltage=bool(block.get_value("voltage", defaults.voltage)),
            current=bool(block.get_value("current", defaults.current)),
            power=bool(block.get_value("power", defaults.power)),
            health=bool(block.get_value("health", defaults.health)),
            energy_now=bool(block.get_value("energy_now", defaults.energy_now)),
            energy_full=bool(block.get_value("energy_full", defaults.energy_full)),
            energy_full_design=bool(
                block.get_value("energy_full_design", defaults.energy_full_design)
            ),
            cycles=bool(block.get_value("cycles", defaults.cycles)),
            temperature=bool(block.get_value("temperature", defaults.temperature)),
            time_to_empty=bool(block.get_value("time_to_empty", defaults.time_to_empty)),
            time_to_full=bool(block.get_value("time_to_full", defaults.time_to_full)),
            present=bool(block.get_value("present", defaults.present)),
            technology=bool(block.get_value("technology", defaults.technology)),
            voltage_max=bool(block.get_value("voltage_max", defaults.voltage_max)),
            voltage_min=bool(block.get_value("voltage_min", defaults.voltage_min)),
            voltage_max_design=bool(
                block.get_value("voltage_max_design", defaults.voltage_max_design)
            ),
            voltage_min_design=bool(
                block.get_value("voltage_min_design", defaults.voltage_min_design)
            ),
            constant_charge_current=bool(
                block.get_value("constant_charge_current", defaults.constant_charge_current)
            ),
            constant_charge_current_max=bool(
                block.get_value("constant_charge_current_max", defaults.constant_charge_current_max)
            ),
            charge_full_design=bool(
                block.get_value("charge_full_design", defaults.charge_full_design)
            ),
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
class DiskDefaultsConfig:
    """Default settings for disk collectors."""

    total: bool = True
    used: bool = True
    free: bool = True
    percent: bool = True

    @classmethod
    def from_block(cls, block: Block | None) -> "DiskDefaultsConfig":
        if block is None:
            return cls()
        return cls(
            total=bool(block.get_value("total", True)),
            used=bool(block.get_value("used", True)),
            free=bool(block.get_value("free", True)),
            percent=bool(block.get_value("percent", True)),
        )


@dataclass
class DefaultsConfig:
    """Default settings inherited by collectors."""

    update_interval: float = 10.0  # seconds
    smaps: bool = False

    # Per-source-type defaults
    # Note: system defaults removed - system block appears only once
    process: ProcessDefaultsConfig = field(default_factory=ProcessDefaultsConfig)
    service: ServiceDefaultsConfig = field(default_factory=ServiceDefaultsConfig)
    container: ContainerDefaultsConfig = field(default_factory=ContainerDefaultsConfig)
    battery: BatteryDefaultsConfig = field(default_factory=BatteryDefaultsConfig)
    custom: CustomDefaultsConfig = field(default_factory=CustomDefaultsConfig)
    disk: DiskDefaultsConfig = field(default_factory=DiskDefaultsConfig)

    @classmethod
    def from_block(cls, block: Block | None) -> "DefaultsConfig":
        """Create DefaultsConfig from a parsed 'defaults' block."""
        if block is None:
            return cls()

        interval = block.get_value("update_interval", 10.0)
        if isinstance(interval, str):
            interval = 10.0

        return cls(
            update_interval=float(interval),
            smaps=bool(block.get_value("smaps", False)),
            # system defaults removed - system block appears only once
            process=ProcessDefaultsConfig.from_block(block.get_block("process")),
            service=ServiceDefaultsConfig.from_block(block.get_block("service")),
            container=ContainerDefaultsConfig.from_block(block.get_block("container")),
            battery=BatteryDefaultsConfig.from_block(block.get_block("battery")),
            custom=CustomDefaultsConfig.from_block(block.get_block("custom")),
            disk=DiskDefaultsConfig.from_block(block.get_block("disk")),
        )


@dataclass
class AutoDiscoveryConfig:
    """
    Unified auto-discovery configuration.

    Used by: temperatures, batteries, containers, services

    Example:
        temperatures {
            auto on;
            thermal on;   # /sys/class/thermal (default: on)
            hwmon off;    # psutil hwmon sensors (default: on)
            filter "soc_*";
            exclude "test*";
        }
    """

    enabled: bool = False
    filters: list[str] = field(default_factory=list)  # Include only matching (glob patterns)
    excludes: list[str] = field(default_factory=list)  # Exclude matching (glob patterns)
    # Temperature-specific: source "thermal" or "hwmon" (default: thermal)
    source: str = "thermal"

    # Device reference for auto-discovered sensors
    device_ref: str | None = None
    # Optional override of update interval
    update_interval: float | None = None
    # Extra boolean options to override per-source defaults (e.g., current off)
    options: dict[str, bool] = field(default_factory=dict)

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

        # Temperature source option (default: thermal)
        source = block.get_value("source", "thermal")
        if source not in ("thermal", "hwmon"):
            source = "thermal"

        # Device reference for auto-discovered sensors
        device_ref = block.get_value("device")

        # Optional update interval override
        update_interval_raw = block.get_value("update_interval")
        update_interval: float | None
        if update_interval_raw is None:
            update_interval = None
        else:
            try:
                update_interval = float(update_interval_raw)
            except Exception:
                update_interval = None

        # Collect extra boolean options (used to override per-source defaults)
        reserved = {"auto", "filter", "exclude", "source", "device", "update_interval"}
        options: dict[str, bool] = {}
        for directive in block.directives:
            if directive.name in reserved:
                continue
            val = directive.value
            if isinstance(val, bool):
                options[directive.name] = val
            elif isinstance(val, str):
                options[directive.name] = val.lower() in ("on", "true", "yes", "1")

        return cls(
            enabled=enabled,
            filters=filters,
            excludes=excludes,
            source=source,
            device_ref=device_ref,
            update_interval=update_interval,
            options=options,
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

    def bool_override(self, name: str) -> bool | None:
        """Return boolean override if specified in auto-discovery block."""
        return self.options.get(name)


@dataclass
class SystemConfig:
    """System-wide metrics configuration."""

    name: str = "system"  # Optional, used for device name only
    device_ref: str | None = None  # Device template name or "system"/"auto"/"none"

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

        interval = block.get_value("update_interval")
        if interval is None:
            interval = defaults.update_interval

        # Helper to get value with hardcoded defaults (system appears only once)
        def get_bool(name: str, default: bool) -> bool:
            val = block.get_value(name)
            return bool(val) if val is not None else default

        # Parse device reference (string: template name or "system"/"auto"/"none")
        device_ref = block.get_value("device")

        return cls(
            name=name,
            device_ref=device_ref,
            cpu=get_bool("cpu", True),
            cpu_per_core=get_bool("cpu_per_core", False),
            memory=get_bool("memory", True),
            swap=get_bool("swap", True),
            load=get_bool("load", True),
            uptime=get_bool("uptime", True),
            gpu=get_bool("gpu", False),
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
    match: ProcessMatchConfig | None = None
    device_ref: str | None = None  # Device template name or "system"/"auto"/"none"
    sensor_prefix: str | None = None
    ha_config: HomeAssistantSensorConfig | None = None  # HA sensor overrides

    # Metrics flags
    cpu: bool = True
    memory: bool = True
    smaps: bool | None = None  # None = use defaults
    disk: bool = False
    disk_rate: bool = False
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

        # Parse device reference (string: template name or "system"/"auto"/"none")
        device_ref = block.get_value("device")

        # Parse homeassistant block for sensor overrides
        ha_block = block.get_block("homeassistant")
        ha_config = HomeAssistantSensorConfig.from_block(ha_block)

        return cls(
            name=name,
            match=ProcessMatchConfig.from_directive(block.get_directive("match")),
            device_ref=device_ref,
            sensor_prefix=block.get_value("sensor_prefix"),
            ha_config=ha_config,
            cpu=get_bool("cpu", pd.cpu),
            memory=get_bool("memory", pd.memory),
            smaps=smaps,
            disk=get_bool("disk", pd.disk),
            disk_rate=get_bool("disk_rate", pd.disk_rate),
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
    def from_defaults(
        cls, name: str, match: "ProcessMatchConfig", defaults: DefaultsConfig
    ) -> "ProcessConfig":
        """Create ProcessConfig from defaults (for auto-discovery)."""
        pd = defaults.process
        return cls(
            name=name,
            match=match,
            cpu=pd.cpu,
            memory=pd.memory,
            smaps=pd.smaps,
            disk=pd.disk,
            disk_rate=pd.disk_rate,
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
    match: ServiceMatchConfig | None = None
    device_ref: str | None = None  # Device template name or "system"/"auto"/"none"
    ha_config: HomeAssistantSensorConfig | None = None  # HA sensor overrides

    # Metrics flags
    cpu: bool = True
    memory: bool = True
    smaps: bool | None = None
    state: bool = True
    restart_count: bool = False
    disk: bool = False
    disk_rate: bool = False

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

        # Parse device reference (string: template name or "system"/"auto"/"none")
        device_ref = block.get_value("device")

        # Parse homeassistant block for sensor overrides
        ha_block = block.get_block("homeassistant")
        ha_config = HomeAssistantSensorConfig.from_block(ha_block)

        return cls(
            name=name,
            match=ServiceMatchConfig.from_directive(block.get_directive("match")),
            device_ref=device_ref,
            ha_config=ha_config,
            cpu=get_bool("cpu", svd.cpu),
            memory=get_bool("memory", svd.memory),
            smaps=smaps,
            state=get_bool("state", svd.state),
            restart_count=get_bool("restart_count", svd.restart_count),
            disk=get_bool("disk", svd.disk),
            disk_rate=get_bool("disk_rate", svd.disk_rate),
            update_interval=float(interval) if interval else None,
        )

    def should_use_smaps(self, defaults: DefaultsConfig) -> bool:
        """Determine if smaps should be used (respecting defaults)."""
        if self.smaps is not None:
            return self.smaps
        return defaults.smaps

    @classmethod
    def from_defaults(
        cls, name: str, match: "ServiceMatchConfig", defaults: DefaultsConfig
    ) -> "ServiceConfig":
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
            disk=svd.disk,
            disk_rate=svd.disk_rate,
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
    match: ContainerMatchConfig | None = None
    device_ref: str | None = None  # Device template name or "system"/"auto"/"none"
    ha_config: HomeAssistantSensorConfig | None = None  # HA sensor overrides
    auto_discover: bool = False

    # Metrics flags
    cpu: bool = True
    memory: bool = True
    network: bool = False
    network_rate: bool = False  # Network speed (KB/s)
    disk: bool = False
    disk_rate: bool = False  # Disk speed (KB/s)
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

        # Parse device reference (string: template name or "system"/"auto"/"none")
        device_ref = block.get_value("device")

        # Parse homeassistant block for sensor overrides
        ha_block = block.get_block("homeassistant")
        ha_config = HomeAssistantSensorConfig.from_block(ha_block)

        return cls(
            name=name,
            match=ContainerMatchConfig.from_directive(block.get_directive("match")),
            device_ref=device_ref,
            ha_config=ha_config,
            auto_discover=bool(block.get_value("auto_discover", False)),
            cpu=get_bool("cpu", cd.cpu),
            memory=get_bool("memory", cd.memory),
            network=get_bool("network", cd.network),
            network_rate=get_bool("network_rate", cd.network_rate),
            disk=get_bool("disk", cd.disk),
            disk_rate=get_bool("disk_rate", cd.disk_rate),
            state=get_bool("state", cd.state),
            health=get_bool("health", cd.health),
            uptime=get_bool("uptime", cd.uptime),
            update_interval=float(interval) if interval else None,
        )

    @classmethod
    def from_defaults(
        cls, name: str, match: "ContainerMatchConfig", defaults: DefaultsConfig
    ) -> "ContainerConfig":
        """Create ContainerConfig from defaults (for auto-discovery)."""
        cd = defaults.container
        return cls(
            name=name,
            match=match,
            cpu=cd.cpu,
            memory=cd.memory,
            network=cd.network,
            network_rate=cd.network_rate,
            disk=cd.disk,
            disk_rate=cd.disk_rate,
            state=cd.state,
            health=cd.health,
            uptime=cd.uptime,
            update_interval=defaults.update_interval,
        )


@dataclass
class TemperatureConfig:
    """Temperature sensor configuration."""

    name: str
    zone: str | None = None  # Thermal zone name (e.g., "soc-thermal", "thermal_zone0")
    hwmon: str | None = None  # Hwmon sensor name (e.g., "soc_thermal_sensor0")
    path: str | None = None  # Direct path to temp file
    device_ref: str | None = None  # Device template name or "system"/"auto"/"none"
    ha_config: HomeAssistantSensorConfig | None = None  # HA sensor overrides
    update_interval: float | None = None

    @classmethod
    def from_defaults(cls, name: str, defaults: DefaultsConfig) -> "TemperatureConfig":
        """Create TemperatureConfig from defaults (for auto-discovery)."""
        return cls(
            name=name,
            update_interval=defaults.update_interval,
        )

    @classmethod
    def from_block(cls, block: Block, defaults: DefaultsConfig) -> "TemperatureConfig":
        """Create TemperatureConfig from a parsed 'temperature' block."""
        name = block.name or "temperature"

        interval = block.get_value("update_interval")
        if interval is None:
            interval = defaults.update_interval

        # Parse device reference (string: template name or "system"/"auto"/"none")
        device_ref = block.get_value("device")

        # Parse homeassistant block for sensor overrides
        ha_block = block.get_block("homeassistant")
        ha_config = HomeAssistantSensorConfig.from_block(ha_block)

        return cls(
            name=name,
            zone=block.get_value("zone"),
            hwmon=block.get_value("hwmon"),
            path=block.get_value("path"),
            device_ref=device_ref,
            ha_config=ha_config,
            update_interval=float(interval) if interval else None,
        )


@dataclass
class BatteryConfig:
    """Battery monitoring configuration."""

    name: str
    path: str | None = None
    battery_name: str | None = None  # BAT0, BAT1, etc.
    device_ref: str | None = None  # Device template name or "system"/"auto"/"none"
    ha_config: HomeAssistantSensorConfig | None = None  # HA sensor overrides

    # Metrics flags
    capacity: bool = True
    voltage: bool = True
    current: bool = True
    power: bool = True
    health: bool = True
    energy_now: bool = True
    energy_full: bool = True
    energy_full_design: bool = True
    cycles: bool = False
    temperature: bool = False
    time_to_empty: bool = False
    time_to_full: bool = False
    present: bool = False
    technology: bool = False
    voltage_max: bool = False
    voltage_min: bool = False
    voltage_max_design: bool = False
    voltage_min_design: bool = False
    constant_charge_current: bool = False
    constant_charge_current_max: bool = False
    charge_full_design: bool = False

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

        # Parse device reference (string: template name or "system"/"auto"/"none")
        device_ref = block.get_value("device")

        # Parse homeassistant block for sensor overrides
        ha_block = block.get_block("homeassistant")
        ha_config = HomeAssistantSensorConfig.from_block(ha_block)

        return cls(
            name=name,
            path=block.get_value("path"),
            battery_name=block.get_value("name"),  # the battery name like BAT0
            device_ref=device_ref,
            ha_config=ha_config,
            capacity=get_bool("capacity", bd.capacity),
            voltage=get_bool("voltage", bd.voltage),
            current=get_bool("current", bd.current),
            power=get_bool("power", bd.power),
            health=get_bool("health", bd.health),
            energy_now=get_bool("energy_now", bd.energy_now),
            energy_full=get_bool("energy_full", bd.energy_full),
            energy_full_design=get_bool("energy_full_design", bd.energy_full_design),
            cycles=get_bool("cycles", bd.cycles),
            temperature=get_bool("temperature", bd.temperature),
            time_to_empty=get_bool("time_to_empty", bd.time_to_empty),
            time_to_full=get_bool("time_to_full", bd.time_to_full),
            present=get_bool("present", bd.present),
            technology=get_bool("technology", bd.technology),
            voltage_max=get_bool("voltage_max", bd.voltage_max),
            voltage_min=get_bool("voltage_min", bd.voltage_min),
            voltage_max_design=get_bool("voltage_max_design", bd.voltage_max_design),
            voltage_min_design=get_bool("voltage_min_design", bd.voltage_min_design),
            constant_charge_current=get_bool("constant_charge_current", bd.constant_charge_current),
            constant_charge_current_max=get_bool(
                "constant_charge_current_max", bd.constant_charge_current_max
            ),
            charge_full_design=get_bool("charge_full_design", bd.charge_full_design),
            update_interval=float(interval) if interval else None,
        )

    @classmethod
    def from_defaults(cls, name: str, defaults: DefaultsConfig) -> "BatteryConfig":
        """Create BatteryConfig from defaults (for auto-discovery)."""
        bd = defaults.battery
        return cls(
            name=name,
            battery_name=name,
            capacity=bd.capacity,
            voltage=bd.voltage,
            current=bd.current,
            power=bd.power,
            health=bd.health,
            energy_now=bd.energy_now,
            energy_full=bd.energy_full,
            energy_full_design=bd.energy_full_design,
            cycles=bd.cycles,
            temperature=bd.temperature,
            time_to_empty=bd.time_to_empty,
            time_to_full=bd.time_to_full,
            present=bd.present,
            technology=bd.technology,
            voltage_max=bd.voltage_max,
            voltage_min=bd.voltage_min,
            voltage_max_design=bd.voltage_max_design,
            voltage_min_design=bd.voltage_min_design,
            constant_charge_current=bd.constant_charge_current,
            constant_charge_current_max=bd.constant_charge_current_max,
            charge_full_design=bd.charge_full_design,
            update_interval=defaults.update_interval,
        )


@dataclass
class ACPowerConfig:
    """External AC power supply (mains) monitoring configuration.

    Reads the 'online' attribute from /sys/class/power_supply/<device_name>/online.
    """

    name: str  # Block name: collector ID and MQTT topic (e.g. "main", "axp22x-ac")
    device_name: str | None = None  # Sysfs device name (e.g. axp22x-ac). If not set, name is used
    path: str | None = None  # Optional full path; overrides device_name when set
    device_ref: str | None = None  # Device template or "system"/"auto"/"none"
    ha_config: HomeAssistantSensorConfig | None = None
    update_interval: float | None = None

    @classmethod
    def from_block(cls, block: Block, defaults: DefaultsConfig) -> "ACPowerConfig":
        """Create ACPowerConfig from a parsed 'ac_power' block."""
        name = block.name or "ac"
        device_name = block.get_value("name")  # Optional: sysfs device name (like battery "name")

        interval = block.get_value("update_interval")
        if interval is None:
            interval = defaults.update_interval

        # Parse device reference (string: template name or "system"/"auto"/"none")
        device_ref = block.get_value("device")

        # Parse homeassistant block for sensor overrides
        ha_block = block.get_block("homeassistant")
        ha_config = HomeAssistantSensorConfig.from_block(ha_block)

        return cls(
            name=name,
            device_name=device_name,
            path=block.get_value("path"),
            device_ref=device_ref,
            ha_config=ha_config,
            update_interval=float(interval) if interval else None,
        )

    @classmethod
    def from_defaults(cls, name: str, defaults: DefaultsConfig) -> "ACPowerConfig":
        """Create ACPowerConfig from defaults (for auto-discovery)."""
        return cls(
            name=name,
            update_interval=defaults.update_interval,
        )


@dataclass
class CustomSensorConfig:
    """Custom command/script sensor configuration."""

    name: str  # Sensor ID, used for MQTT topics
    command: str | None = None
    script: str | None = None
    device_ref: str | None = None  # Device template name or "system"/"auto"/"none"
    ha_config: HomeAssistantSensorConfig | None = None  # HA sensor overrides

    # Output parsing
    type: str = "number"  # number, string, json
    unit: str | None = None
    scale: float = 1.0

    # Home Assistant (deprecated, use ha_config instead)
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

        # Parse device reference (string: template name or "system"/"auto"/"none")
        device_ref = block.get_value("device")

        # Parse homeassistant block for sensor overrides
        ha_block = block.get_block("homeassistant")
        ha_config = HomeAssistantSensorConfig.from_block(ha_block)

        return cls(
            name=name,
            command=block.get_value("command"),
            script=block.get_value("script"),
            device_ref=device_ref,
            ha_config=ha_config,
            type=type_str,
            unit=block.get_value("unit"),
            scale=float(block.get_value("scale", 1.0)),
            device_class=block.get_value("device_class"),  # Legacy
            state_class=block.get_value("state_class"),  # Legacy
            update_interval=float(interval) if interval else None,
            timeout=timeout,
        )


@dataclass
class CustomBinarySensorConfig:
    """Custom binary sensor configuration (on/off states)."""

    name: str  # Sensor ID, used for MQTT topics
    command: str | None = None
    script: str | None = None
    device_ref: str | None = None  # Device template name or "system"/"auto"/"none"
    ha_config: HomeAssistantSensorConfig | None = None  # HA sensor overrides

    # Value source
    value_source: str = "returncode"  # "returncode" or "output"
    invert: bool = False  # Invert the value (ON ↔ OFF)

    # Settings
    update_interval: float | None = None
    timeout: float = 5.0

    @classmethod
    def from_block(cls, block: Block, defaults: DefaultsConfig) -> "CustomBinarySensorConfig":
        """Create CustomBinarySensorConfig from a parsed 'custom_binary' block."""
        name = block.name or "custom_binary"

        interval = block.get_value("update_interval")
        if interval is None:
            interval = defaults.update_interval

        # Get value_source (default: returncode)
        value_source = block.get_value("value_source", "returncode")
        if value_source not in ("returncode", "output"):
            value_source = "returncode"

        # Get timeout
        timeout_val = block.get_value("timeout")
        timeout = float(timeout_val) if timeout_val is not None else 5.0

        # Parse device reference (string: template name or "system"/"auto"/"none")
        device_ref = block.get_value("device")

        # Parse homeassistant block for sensor overrides
        ha_block = block.get_block("homeassistant")
        ha_config = HomeAssistantSensorConfig.from_block(ha_block)

        return cls(
            name=name,
            command=block.get_value("command"),
            script=block.get_value("script"),
            device_ref=device_ref,
            ha_config=ha_config,
            value_source=value_source,
            invert=bool(block.get_value("invert", False)),
            update_interval=float(interval) if interval else None,
            timeout=timeout,
        )


@dataclass
class DiskConfig:
    """Disk space monitoring configuration."""

    name: str
    path: str | None = None  # Device name: sda1, nvme0n1p1
    mountpoint: str | None = None  # Mount point: /, /home
    device_ref: str | None = None  # Device template name or "system"/"auto"/"none"
    ha_config: HomeAssistantSensorConfig | None = None  # HA sensor overrides

    # Metrics flags
    total: bool = True
    used: bool = True
    free: bool = True
    percent: bool = True

    # Settings
    update_interval: float | None = None

    @classmethod
    def from_block(cls, block: Block, defaults: DefaultsConfig) -> "DiskConfig":
        """Create DiskConfig from a parsed 'disk' block."""
        name = block.name or "disk"
        dd = defaults.disk  # Disk-specific defaults

        interval = block.get_value("update_interval")
        if interval is None:
            interval = defaults.update_interval

        def get_bool(name: str, dd_val: bool) -> bool:
            val = block.get_value(name)
            return bool(val) if val is not None else dd_val

        # Parse device reference (string: template name or "system"/"auto"/"none")
        device_ref = block.get_value("device")

        # Parse homeassistant block for sensor overrides
        ha_block = block.get_block("homeassistant")
        ha_config = HomeAssistantSensorConfig.from_block(ha_block)

        return cls(
            name=name,
            path=block.get_value("path"),
            mountpoint=block.get_value("mountpoint"),
            device_ref=device_ref,
            ha_config=ha_config,
            total=get_bool("total", dd.total),
            used=get_bool("used", dd.used),
            free=get_bool("free", dd.free),
            percent=get_bool("percent", dd.percent),
            update_interval=float(interval) if interval else None,
        )

    @classmethod
    def from_defaults(cls, name: str, path: str, defaults: DefaultsConfig) -> "DiskConfig":
        """Create DiskConfig from defaults (for auto-discovery)."""
        dd = defaults.disk
        return cls(
            name=name,
            path=path,
            total=dd.total,
            used=dd.used,
            free=dd.free,
            percent=dd.percent,
            update_interval=defaults.update_interval,
        )


@dataclass
class Config:
    """Complete application configuration."""

    mqtt: MQTTConfig = field(default_factory=MQTTConfig)
    homeassistant: HomeAssistantConfig = field(default_factory=HomeAssistantConfig)
    defaults: DefaultsConfig = field(default_factory=DefaultsConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    # Global settings
    auto_refresh_interval: float = 0  # seconds, 0 = disabled

    # Device templates for grouping sensors
    device_templates: dict[str, DeviceConfig] = field(default_factory=dict)

    # Auto-discovery settings (plural blocks: temperatures, batteries, etc.)
    auto_temperatures: AutoDiscoveryConfig = field(default_factory=AutoDiscoveryConfig)
    auto_batteries: AutoDiscoveryConfig = field(default_factory=AutoDiscoveryConfig)
    auto_containers: AutoDiscoveryConfig = field(default_factory=AutoDiscoveryConfig)
    auto_services: AutoDiscoveryConfig = field(default_factory=AutoDiscoveryConfig)
    auto_processes: AutoDiscoveryConfig = field(default_factory=AutoDiscoveryConfig)
    auto_disks: AutoDiscoveryConfig = field(default_factory=AutoDiscoveryConfig)
    auto_ac_powers: AutoDiscoveryConfig = field(default_factory=AutoDiscoveryConfig)

    # Manual collectors (singular blocks: temperature, battery, etc.)
    system: list[SystemConfig] = field(default_factory=list)
    processes: list[ProcessConfig] = field(default_factory=list)
    services: list[ServiceConfig] = field(default_factory=list)
    containers: list[ContainerConfig] = field(default_factory=list)
    temperatures: list[TemperatureConfig] = field(default_factory=list)
    batteries: list[BatteryConfig] = field(default_factory=list)
    ac_power: list[ACPowerConfig] = field(default_factory=list)
    disks: list[DiskConfig] = field(default_factory=list)
    custom: list[CustomSensorConfig] = field(default_factory=list)
    binary_sensors: list[CustomBinarySensorConfig] = field(default_factory=list)

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

    @classmethod
    def from_document(cls, doc: ConfigDocument) -> "Config":
        """Create Config from a parsed ConfigDocument."""
        config = cls()

        # Parse top-level directives
        refresh = doc.get_value("auto_refresh_interval", 0)
        if isinstance(refresh, str):
            refresh = 0
        config.auto_refresh_interval = float(refresh)

        # Parse global blocks
        config.mqtt = MQTTConfig.from_block(doc.get_block("mqtt"))
        config.homeassistant = HomeAssistantConfig.from_block(doc.get_block("homeassistant"))
        config.defaults = DefaultsConfig.from_block(doc.get_block("defaults"))
        config.logging = LoggingConfig.from_block(doc.get_block("logging"))

        # Parse device templates (device "name" { ... })
        topic_prefix = config.mqtt.topic_prefix
        for block in doc.get_blocks("device"):
            if block.name:
                template_name = block.name
                device_config = DeviceConfig.from_block(block)
                # Generate identifier based on template name
                sanitized_name = cls._sanitize_id(template_name)
                identifier = f"penguin_metrics_{topic_prefix}_device_{sanitized_name}"
                device_config.identifiers = [identifier]
                # Set name if not specified
                if "name" not in device_config.extra_fields:
                    device_config.extra_fields["name"] = template_name
                config.device_templates[template_name] = device_config

        # Parse auto-discovery blocks (plural names)
        config.auto_temperatures = AutoDiscoveryConfig.from_block(doc.get_block("temperatures"))
        config.auto_batteries = AutoDiscoveryConfig.from_block(doc.get_block("batteries"))
        config.auto_containers = AutoDiscoveryConfig.from_block(doc.get_block("containers"))
        config.auto_services = AutoDiscoveryConfig.from_block(doc.get_block("services"))
        config.auto_processes = AutoDiscoveryConfig.from_block(doc.get_block("processes"))
        config.auto_disks = AutoDiscoveryConfig.from_block(doc.get_block("disks"))
        config.auto_ac_powers = AutoDiscoveryConfig.from_block(doc.get_block("ac_powers"))

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

        for block in doc.get_blocks("ac_power"):
            config.ac_power.append(ACPowerConfig.from_block(block, config.defaults))

        for block in doc.get_blocks("disk"):
            config.disks.append(DiskConfig.from_block(block, config.defaults))

        for block in doc.get_blocks("custom"):
            config.custom.append(CustomSensorConfig.from_block(block, config.defaults))

        for block in doc.get_blocks("custom_binary"):
            config.binary_sensors.append(
                CustomBinarySensorConfig.from_block(block, config.defaults)
            )

        return config
