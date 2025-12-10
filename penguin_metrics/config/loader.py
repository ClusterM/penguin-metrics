"""
Configuration loader with file reading and validation.
"""

from pathlib import Path

from .lexer import LexerError
from .parser import ConfigDocument, ParseError, parse_config, parse_config_file
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

    def __init__(self):
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
            "device_grouping",
            "device",
            "state_file",
        },
        "defaults": {
            "update_interval",
            "smaps",
            "availability_topic",
            "system",
            "process",
            "service",
            "container",
            "battery",
            "custom",
            "disk",
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
            "id",
            "device",
            "cpu",
            "cpu_per_core",
            "memory",
            "swap",
            "load",
            "uptime",
            "gpu",
            "update_interval",
        },
        "process": {
            "id",
            "device",
            "match",
            "cpu",
            "memory",
            "smaps",
            "io",
            "fds",
            "threads",
            "aggregate",
            "update_interval",
        },
        "service": {
            "id",
            "device",
            "match",
            "cpu",
            "memory",
            "smaps",
            "state",
            "restart_count",
            "update_interval",
        },
        "container": {
            "id",
            "device",
            "match",
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
        "temperature": {"id", "zone", "hwmon", "path", "update_interval"},
        "battery": {
            "id",
            "device",
            "name",
            "path",
            "capacity",
            "status",
            "voltage",
            "current",
            "power",
            "health",
            "cycles",
            "temperature",
            "time_to_empty",
            "time_to_full",
            "update_interval",
        },
        "custom": {
            "id",
            "device",
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
        "temperatures": {"auto", "filter", "exclude", "source"},
        "batteries": {"auto", "filter", "exclude"},
        "containers": {"auto", "filter", "exclude"},
        "services": {"auto", "filter", "exclude"},
        "processes": {"auto", "filter", "exclude"},
        "disks": {"auto", "filter", "exclude"},
        "disk": {
            "id",
            "device",
            "mountpoint",
            "total",
            "used",
            "free",
            "percent",
            "update_interval",
        },
        "device": {"name", "manufacturer", "model", "hw_version", "sw_version", "identifiers"},
        "match": {"name", "pattern", "pid", "pidfile", "cmdline", "unit", "image", "label"},
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

        # Check for duplicate IDs
        all_ids: dict[str, list[str]] = {}

        for sys in config.system:
            # System uses fixed topic, just check for duplicate system blocks
            all_ids.setdefault("system", []).append(f"system:{sys.name}")

        for proc in config.processes:
            id_val = proc.id or proc.name
            all_ids.setdefault(id_val, []).append(f"process:{proc.name}")

        for svc in config.services:
            id_val = svc.id or svc.name
            all_ids.setdefault(id_val, []).append(f"service:{svc.name}")

        for cont in config.containers:
            id_val = cont.id or cont.name
            all_ids.setdefault(id_val, []).append(f"container:{cont.name}")

        for dup_id, sources in all_ids.items():
            if len(sources) > 1:
                warnings.append(f"Duplicate ID '{dup_id}' used by: {', '.join(sources)}")

        # Check process match configurations
        for proc in config.processes:
            if proc.match is None:
                warnings.append(f"Process '{proc.name}' has no match configuration")

        # Check service match configurations
        for svc in config.services:
            if svc.match is None:
                warnings.append(f"Service '{svc.name}' has no match configuration")

        # Check container match configurations
        for cont in config.containers:
            if cont.match is None:
                warnings.append(f"Container '{cont.name}' has no match configuration")

        # Check custom sensors
        for custom in config.custom:
            if not custom.command and not custom.script:
                warnings.append(f"Custom sensor '{custom.name}' has no command or script")

        return warnings

    def _check_unknown_directives(self, document: ConfigDocument) -> list[str]:
        """Check for unknown directives in parsed document."""
        warnings = []

        def check_block(block, parent_path: str = ""):
            block_path = f"{parent_path}{block.type}" if parent_path else block.type
            known = self.KNOWN_DIRECTIVES.get(block.type, set())

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
