"""
Logging configuration for Penguin Metrics.

Features:
- Multiple log levels (debug, info, warning, error)
- Console output with optional colors
- File output with rotation
- Per-module log level configuration
- Structured logging format
"""

import logging
import logging.handlers
import sys
from dataclasses import dataclass
from pathlib import Path


# ANSI color codes for console output
class Colors:
    """ANSI color codes."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    # Foreground colors
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    # Bright foreground colors
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"


# Log level colors
LEVEL_COLORS = {
    logging.DEBUG: Colors.DIM + Colors.CYAN,
    logging.INFO: Colors.GREEN,
    logging.WARNING: Colors.YELLOW,
    logging.ERROR: Colors.RED,
    logging.CRITICAL: Colors.BOLD + Colors.BRIGHT_RED,
}

# Component colors for logger names
COMPONENT_COLORS = {
    "config": Colors.MAGENTA,
    "mqtt": Colors.BLUE,
    "collector": Colors.CYAN,
    "app": Colors.GREEN,
    "homeassistant": Colors.BRIGHT_BLUE,
}


class ColoredFormatter(logging.Formatter):
    """
    Formatter that adds ANSI colors to log output.

    Colors are applied based on log level and component name.
    """

    def __init__(
        self,
        fmt: str | None = None,
        datefmt: str | None = None,
        use_colors: bool = True,
    ):
        super().__init__(fmt, datefmt)
        self.use_colors = use_colors

    def format(self, record: logging.LogRecord) -> str:
        # Save original values
        original_levelname = record.levelname
        original_name = record.name
        original_msg = record.msg

        if self.use_colors:
            # Color the level name
            level_color = LEVEL_COLORS.get(record.levelno, "")
            record.levelname = f"{level_color}{record.levelname:8}{Colors.RESET}"

            # Color the component name
            component_color = ""
            for key, color in COMPONENT_COLORS.items():
                if key in record.name.lower():
                    component_color = color
                    break

            if component_color:
                record.name = f"{component_color}{record.name}{Colors.RESET}"

            # Color error/warning messages
            if record.levelno >= logging.ERROR:
                record.msg = f"{Colors.RED}{record.msg}{Colors.RESET}"
            elif record.levelno >= logging.WARNING:
                record.msg = f"{Colors.YELLOW}{record.msg}{Colors.RESET}"

        result = super().format(record)

        # Restore original values
        record.levelname = original_levelname
        record.name = original_name
        record.msg = original_msg

        return result


class PlainFormatter(logging.Formatter):
    """Plain formatter without colors for file output."""

    def format(self, record: logging.LogRecord) -> str:
        # Ensure consistent level name width
        record.levelname = f"{record.levelname:8}"
        return super().format(record)


@dataclass
class LogConfig:
    """Logging configuration."""

    # Console settings
    console_level: str = "INFO"
    console_colors: bool = True

    # File settings
    file_enabled: bool = False
    file_path: str = "/var/log/penguin-metrics/penguin-metrics.log"
    file_level: str = "DEBUG"
    file_max_bytes: int = 10 * 1024 * 1024  # 10 MB
    file_backup_count: int = 5

    # Format
    format: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    date_format: str = "%Y-%m-%d %H:%M:%S"

    # Per-module levels (module_name -> level)
    module_levels: dict[str, str] | None = None


def get_log_level(level_str: str) -> int:
    """Convert string log level to logging constant."""
    levels = {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warning": logging.WARNING,
        "warn": logging.WARNING,
        "error": logging.ERROR,
        "critical": logging.CRITICAL,
    }
    return levels.get(level_str.lower(), logging.INFO)


def setup_logging(config: LogConfig | None = None) -> None:
    """
    Configure logging for the application.

    Args:
        config: Logging configuration (uses defaults if None)
    """
    if config is None:
        config = LogConfig()

    # Get root logger for penguin_metrics
    root_logger = logging.getLogger("penguin_metrics")
    root_logger.setLevel(logging.DEBUG)  # Capture all, filter at handlers

    # Remove existing handlers
    root_logger.handlers.clear()

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(get_log_level(config.console_level))

    # Use colored formatter if colors enabled and stdout is a TTY
    use_colors = config.console_colors and hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
    console_formatter = ColoredFormatter(
        fmt=config.format,
        datefmt=config.date_format,
        use_colors=use_colors,
    )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # File handler
    if config.file_enabled:
        # Ensure log directory exists
        log_path = Path(config.file_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.handlers.RotatingFileHandler(
            config.file_path,
            maxBytes=config.file_max_bytes,
            backupCount=config.file_backup_count,
        )
        file_handler.setLevel(get_log_level(config.file_level))

        file_formatter = PlainFormatter(
            fmt=config.format,
            datefmt=config.date_format,
        )
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)

    # Apply per-module levels
    if config.module_levels:
        for module_name, level_str in config.module_levels.items():
            module_logger = logging.getLogger(f"penguin_metrics.{module_name}")
            module_logger.setLevel(get_log_level(level_str))

    # Reduce noise from external libraries
    logging.getLogger("aiomqtt").setLevel(logging.WARNING)
    logging.getLogger("paho").setLevel(logging.WARNING)


def setup_logging_from_args(
    verbose: bool = False,
    debug: bool = False,
    log_file: str | None = None,
) -> None:
    """
    Setup logging from command-line arguments.

    Args:
        verbose: Enable INFO level logging
        debug: Enable DEBUG level logging
        log_file: Optional log file path
    """
    config = LogConfig()

    if debug:
        config.console_level = "DEBUG"
    elif verbose:
        config.console_level = "INFO"
    else:
        config.console_level = "WARNING"

    if log_file:
        config.file_enabled = True
        config.file_path = log_file

    setup_logging(config)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger for a component.

    Args:
        name: Component name (will be prefixed with penguin_metrics)

    Returns:
        Logger instance
    """
    if name.startswith("penguin_metrics"):
        return logging.getLogger(name)
    return logging.getLogger(f"penguin_metrics.{name}")


# Convenience loggers for common components
class Loggers:
    """Pre-configured loggers for common components."""

    @staticmethod
    def app() -> logging.Logger:
        return get_logger("app")

    @staticmethod
    def config() -> logging.Logger:
        return get_logger("config")

    @staticmethod
    def mqtt() -> logging.Logger:
        return get_logger("mqtt")

    @staticmethod
    def collector(name: str = "") -> logging.Logger:
        if name:
            return get_logger(f"collectors.{name}")
        return get_logger("collectors")

    @staticmethod
    def homeassistant() -> logging.Logger:
        return get_logger("homeassistant")
