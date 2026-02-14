"""
Configuration loader with file reading and validation.
"""

from pathlib import Path
from typing import Any

from .lexer import LexerError
from .parser import Block, ConfigDocument, ParseError, parse_config, parse_config_file
from .schema import Config


class ConfigError(Exception):
    """Exception raised for configuration errors."""

    pass


class ConfigLoader:
    """
    Loads and validates configuration from files or strings.

    Usage:
        loader = ConfigLoader()
        config = loader.load_file("/etc/penguin-metrics/config.conf")
        # or
        config = loader.load_string(config_text)
    """

    def __init__(self) -> None:
        self.last_document: ConfigDocument | None = None

    def load_file(self, path: str | Path) -> Config:
        """
        Load configuration from a file.

        Args:
            path: Path to the configuration file

        Returns:
            Validated Config object

        Raises:
            ConfigError: If file cannot be read or parsed
        """
        path = Path(path)

        if not path.exists():
            raise ConfigError(f"Configuration file not found: {path}")

        if not path.is_file():
            raise ConfigError(f"Not a file: {path}")

        try:
            document = parse_config_file(path)
            self.last_document = document
            return Config.from_document(document)
        except (LexerError, ParseError) as e:
            raise ConfigError(f"Failed to parse configuration: {e}") from e
        except Exception as e:
            raise ConfigError(f"Failed to load configuration: {e}") from e

    # Backwards compatibility alias for older callers/tests
    def load(self, path: str | Path) -> Config:
        """
        Alias for load_file to maintain backward compatibility.

        Args:
            path: Path to the configuration file

        Returns:
            Validated Config object
        """
        return self.load_file(path)

    def load_string(
        self,
        source: str,
        filename: str = "<string>",
        base_path: str | Path | None = None,
    ) -> Config:
        """
        Load configuration from a string.

        Args:
            source: Configuration source text
            filename: Filename for error messages
            base_path: Base path for resolving includes

        Returns:
            Validated Config object

        Raises:
            ConfigError: If configuration cannot be parsed
        """
        if base_path is not None:
            base_path = Path(base_path)

        try:
            document = parse_config(source, filename, base_path)
            self.last_document = document
            return Config.from_document(document)
        except (LexerError, ParseError) as e:
            raise ConfigError(f"Failed to parse configuration: {e}") from e
        except Exception as e:
            raise ConfigError(f"Failed to load configuration: {e}") from e

    # Known top-level directives (not in blocks)
    KNOWN_TOP_LEVEL = {"auto_refresh_interval"}

    # Valid sub-block types inside auto_discovery { ... }
    _AUTO_DISCOVERY_SUB_BLOCKS = {
        "temperatures",
        "batteries",
        "containers",
        "services",
        "processes",
        "disks",
        "ac_powers",
        "networks",
        "fans",
    }

    # Known directives for each block type
    KNOWN_DIRECTIVES = {
        "mqtt": {
            "host",
            "port",
            "username",
            "password",
            "client_id",
            "topic_prefix",
            "qos",
            "retain",
            "keepalive",
        },
        "homeassistant": {
            "discovery",
            "discovery_prefix",
            "state_file",
        },
        "defaults": {
            "update_interval",
            "smaps",
            "system",
            "process",
            "service",
            "container",
            "battery",
            "custom",
            "disk",
            "network",
        },
        "logging": {
            "level",
            "file",
            "file_level",
            "file_max_size",
            "file_keep",
            "colors",
            "format",
        },
        "system": {
            "device",
            "display_name",
            "cpu",
            "cpu_per_core",
            "memory",
            "swap",
            "load",
            "uptime",
            "gpu",
            "disk_io",
            "disk_io_rate",
            "cpu_freq",
            "process_count",
            "boot_time",
            "update_interval",
        },
        "process": {
            "device",
            "display_name",
            "match",
            "sensor_prefix",
            "cpu",
            "memory",
            "smaps",
            "disk",
            "disk_rate",
            "fds",
            "threads",
            "aggregate",
            "update_interval",
        },
        "service": {
            "device",
            "display_name",
            "match",
            "cpu",
            "memory",
            "smaps",
            "state",
            "restart_count",
            "disk",
            "disk_rate",
            "update_interval",
        },
        "container": {
            "device",
            "display_name",
            "match",
            "auto_discover",
            "cpu",
            "memory",
            "network",
            "network_rate",
            "disk",
            "disk_rate",
            "state",
            "health",
            "uptime",
            "update_interval",
        },
        "temperature": {"match", "device", "display_name", "update_interval"},
        "ac_power": {"match", "device", "display_name", "update_interval"},
        "battery": {
            "device",
            "display_name",
            "match",
            "capacity",
            "voltage",
            "current",
            "power",
            "health",
            "energy_now",
            "energy_full",
            "energy_full_design",
            "cycles",
            "temperature",
            "time_to_empty",
            "time_to_full",
            "update_interval",
            "present",
            "technology",
            "voltage_max",
            "voltage_min",
            "voltage_max_design",
            "voltage_min_design",
            "constant_charge_current",
            "constant_charge_current_max",
            "charge_full_design",
        },
        "custom": {
            "device",
            "display_name",
            "command",
            "script",
            "type",
            "unit",
            "scale",
            "device_class",
            "state_class",
            "update_interval",
            "timeout",
        },
        "custom_binary": {
            "device",
            "display_name",
            "command",
            "script",
            "value_source",
            "invert",
            "update_interval",
            "timeout",
        },
        "disks": {"auto", "filter", "exclude", "device", "update_interval"},
        "disk": {
            "match",
            "device",
            "display_name",
            "total",
            "used",
            "free",
            "percent",
            "update_interval",
        },
        "network": {
            "match",
            "device",
            "display_name",
            "bytes",
            "packets",
            "errors",
            "drops",
            "rate",
            "packets_rate",
            "isup",
            "speed",
            "mtu",
            "duplex",
            "rssi",
            "update_interval",
        },
        "fan": {"match", "device", "display_name", "update_interval"},
        "device": {"name", "manufacturer", "model", "hw_version", "sw_version", "identifiers"},
        "match": {
            # process
            "name",
            "pattern",
            "pid",
            "pidfile",
            "cmdline",
            # service
            "unit",
            # container
            "image",
            "label",
            # disk
            "mountpoint",
            "uuid",
            # temperature
            "zone",
            "hwmon",
            # battery, ac_power, temperature
            "path",
        },
    }

    # Home Assistant sensor override block (nested inside collectors)
    KNOWN_HA_SENSOR_DIRECTIVES = {
        "name",
        "icon",
        "unit_of_measurement",
        "device_class",
        "state_class",
        "entity_category",
        "enabled_by_default",
        # Allow any other fields (will be in extra_fields)
    }

    def validate(self, config: Config) -> list[str]:
        """
        Validate configuration and return list of warnings.

        Args:
            config: Configuration to validate

        Returns:
            List of warning messages (empty if no issues)
        """
        warnings = []

        # Check for unknown directives in the parsed document
        if self.last_document:
            warnings.extend(self._check_unknown_directives(self.last_document))

        # Check MQTT configuration
        if not config.mqtt.host:
            warnings.append("MQTT host is not configured")

        # Check for duplicate names (topic collisions)
        all_names: dict[str, list[str]] = {}

        for sys in config.system:
            all_names.setdefault(sys.name, []).append(f"system:{sys.name}")

        for proc in config.processes:
            all_names.setdefault(proc.name, []).append(f"process:{proc.name}")

        for svc in config.services:
            all_names.setdefault(svc.name, []).append(f"service:{svc.name}")

        for cont in config.containers:
            all_names.setdefault(cont.name, []).append(f"container:{cont.name}")

        for fan in config.fans:
            all_names.setdefault(fan.name, []).append(f"fan:{fan.name}")

        for dup_name, sources in all_names.items():
            if len(sources) > 1:
                warnings.append(f"Duplicate name '{dup_name}' used by: {', '.join(sources)}")

        def warn_missing_match(items: list[Any], label: str) -> None:
            for entry in items:
                if getattr(entry, "match", None) is None:
                    warnings.append(f"{label} '{entry.name}' has no match configuration")

        warn_missing_match(config.processes, "Process")
        warn_missing_match(config.services, "Service")
        warn_missing_match(config.containers, "Container")
        warn_missing_match(config.disks, "Disk")
        warn_missing_match(config.temperatures, "Temperature")
        warn_missing_match(config.batteries, "Battery")
        warn_missing_match(config.ac_power, "AC power")
        warn_missing_match(config.fans, "Fan")
        warn_missing_match(config.networks, "Network")

        # Check custom sensors
        for custom in config.custom:
            if not custom.command and not custom.script:
                warnings.append(f"Custom sensor '{custom.name}' has no command or script")

        # Validate device_ref values
        reserved_device_refs = {"system", "auto", "none"}
        template_names = set(config.device_templates.keys())

        def validate_device_ref(device_ref: str | None, source_type: str, source_name: str) -> None:
            if device_ref is None:
                return  # Default behavior, valid
            if device_ref in reserved_device_refs:
                return  # Reserved keyword, valid
            if device_ref in template_names:
                return  # Valid template reference
            warnings.append(
                f"{source_type} '{source_name}' references unknown device template '{device_ref}'"
            )

        for sys in config.system:
            validate_device_ref(sys.device_ref, "System", sys.name)
        for proc in config.processes:
            validate_device_ref(proc.device_ref, "Process", proc.name)
        for svc in config.services:
            validate_device_ref(svc.device_ref, "Service", svc.name)
        for cont in config.containers:
            validate_device_ref(cont.device_ref, "Container", cont.name)
        for temp in config.temperatures:
            validate_device_ref(temp.device_ref, "Temperature", temp.name)
        for batt in config.batteries:
            validate_device_ref(batt.device_ref, "Battery", batt.name)
        for ac in config.ac_power:
            validate_device_ref(ac.device_ref, "AC power", ac.name)
        for disk in config.disks:
            validate_device_ref(disk.device_ref, "Disk", disk.name)
        for net in config.networks:
            validate_device_ref(net.device_ref, "Network", net.name)
        for fan in config.fans:
            validate_device_ref(fan.device_ref, "Fan", fan.name)
        for custom in config.custom:
            validate_device_ref(custom.device_ref, "Custom", custom.name)

        # Validate auto-discovery device_refs
        validate_device_ref(
            config.auto_temperatures.device_ref,
            "auto_discovery.temperatures",
            "temperatures",
        )
        validate_device_ref(
            config.auto_batteries.device_ref,
            "auto_discovery.batteries",
            "batteries",
        )
        validate_device_ref(
            config.auto_containers.device_ref,
            "auto_discovery.containers",
            "containers",
        )
        validate_device_ref(
            config.auto_services.device_ref,
            "auto_discovery.services",
            "services",
        )
        validate_device_ref(
            config.auto_processes.device_ref,
            "auto_discovery.processes",
            "processes",
        )
        validate_device_ref(
            config.auto_disks.device_ref,
            "auto_discovery.disks",
            "disks",
        )
        validate_device_ref(
            config.auto_ac_powers.device_ref,
            "auto_discovery.ac_powers",
            "ac_powers",
        )
        validate_device_ref(
            config.auto_networks.device_ref,
            "auto_discovery.networks",
            "networks",
        )
        validate_device_ref(
            config.auto_fans.device_ref,
            "auto_discovery.fans",
            "fans",
        )

        return warnings

    def _check_unknown_directives(self, document: ConfigDocument) -> list[str]:
        """Check for unknown directives in parsed document."""
        warnings = []

        def check_block(block: Block, parent_path: str = "") -> None:
            block_path = f"{parent_path}{block.type}" if parent_path else block.type

            # Special handling for blocks that allow extra fields:
            # - homeassistant (nested): allow any directives (they go to extra_fields)
            # - device: allow any directives (they go to extra_fields)
            known: set[str] | None
            if block.type == "homeassistant" and parent_path:
                # Nested homeassistant block inside collector - allow any directives
                known = None  # None means allow all
            elif block.type == "device":
                # Device blocks allow any directives (extra_fields for HA device)
                known = None
            elif block.type == "auto_discovery":
                # Container block for auto-discovery — no directives, only sub-blocks
                known = set()
            elif block.type in self._AUTO_DISCOVERY_SUB_BLOCKS:
                # Auto-discovery sub-blocks allow arbitrary boolean overrides and update_interval
                known = None
            else:
                known = self.KNOWN_DIRECTIVES.get(block.type, set())

            if known is not None:  # Only validate if we have a known set
                for directive in block.directives:
                    if directive.name not in known:
                        warnings.append(
                            f"Unknown directive '{directive.name}' in {block_path} block (line {directive.line})"
                        )

            for nested in block.blocks:
                check_block(nested, f"{block_path}.")

        for block in document.blocks:
            check_block(block)

        # Check top-level directives
        for directive in document.directives:
            if directive.name not in self.KNOWN_TOP_LEVEL:
                warnings.append(
                    f"Unknown top-level directive '{directive.name}' (line {directive.line})"
                )

        return warnings


def load_config(path: str | Path) -> Config:
    """
    Convenience function to load configuration from a file.

    Args:
        path: Path to the configuration file

    Returns:
        Validated Config object
    """
    loader = ConfigLoader()
    return loader.load_file(path)
