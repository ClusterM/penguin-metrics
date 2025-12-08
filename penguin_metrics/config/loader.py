"""
Configuration loader with file reading and validation.
"""

from pathlib import Path
from typing import Union

from .parser import parse_config, parse_config_file, ConfigDocument, ParseError
from .lexer import LexerError
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
    
    def load_file(self, path: Union[str, Path]) -> Config:
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
        base_path: Union[str, Path, None] = None,
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
    
    def validate(self, config: Config) -> list[str]:
        """
        Validate configuration and return list of warnings.
        
        Args:
            config: Configuration to validate
        
        Returns:
            List of warning messages (empty if no issues)
        """
        warnings = []
        
        # Check MQTT configuration
        if not config.mqtt.host:
            warnings.append("MQTT host is not configured")
        
        # Check for duplicate IDs
        all_ids: dict[str, list[str]] = {}
        
        for sys in config.system:
            id_val = sys.id or sys.name
            all_ids.setdefault(id_val, []).append(f"system:{sys.name}")
        
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


def load_config(path: Union[str, Path]) -> Config:
    """
    Convenience function to load configuration from a file.
    
    Args:
        path: Path to the configuration file
    
    Returns:
        Validated Config object
    """
    loader = ConfigLoader()
    return loader.load_file(path)

