"""
Entry point for Penguin Metrics.

Usage:
    python -m penguin_metrics /path/to/config.conf
    python -m penguin_metrics --help
"""

import argparse
import asyncio
import sys
from pathlib import Path

from . import __version__
from .app import run_app
from .config.loader import ConfigError, ConfigLoader
from .logging import LogConfig, get_logger, setup_logging

logger = get_logger("main")


def validate_config(config_path: str) -> int:
    """Validate configuration file and print warnings."""
    try:
        loader = ConfigLoader()
        config = loader.load_file(config_path)

        warnings = loader.validate(config)

        if warnings:
            print(f"Configuration warnings ({len(warnings)}):")
            for warning in warnings:
                print(f"  - {warning}")

        # Print summary
        print("\nConfiguration summary:")
        print(f"  MQTT: {config.mqtt.host}:{config.mqtt.port}")
        print(
            f"  Home Assistant Discovery: {'enabled' if config.homeassistant.discovery else 'disabled'}"
        )
        print(f"  Logging level: {config.logging.level}")
        if config.logging.file:
            print(f"  Log file: {config.logging.file}")
        print(f"  System collectors: {len(config.system)}")
        print(f"  Process monitors: {len(config.processes)}")
        print(f"  Service monitors: {len(config.services)}")
        print(f"  Container monitors: {len(config.containers)}")
        print(f"  Battery monitors: {len(config.batteries)}")
        print(f"  AC power monitors: {len(config.ac_power)}")
        print(f"  Disk monitors: {len(config.disks)}")
        print(f"  Network interfaces: {len(config.networks)}")
        print(f"  Custom sensors: {len(config.custom)}")

        print("\nConfiguration is valid!")
        return 0

    except ConfigError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 1


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        prog="penguin-metrics",
        description="Linux system telemetry service for Home Assistant via MQTT",
    )

    parser.add_argument(
        "config",
        nargs="?",
        default="/etc/penguin-metrics/config.conf",
        help="Path to configuration file (default: /etc/penguin-metrics/config.conf)",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging (INFO level)",
    )

    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Enable debug logging (DEBUG level)",
    )

    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Quiet mode (only errors)",
    )

    parser.add_argument(
        "--log-file",
        metavar="PATH",
        help="Write logs to file",
    )

    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colored output",
    )

    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate configuration and exit",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    args = parser.parse_args()

    # Check config file exists
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Configuration file not found: {config_path}", file=sys.stderr)
        return 1

    # Check if user explicitly specified log level via CLI
    cli_log_override = args.debug or args.verbose or args.quiet or args.no_color or args.log_file

    # Setup initial logging (before config is loaded)
    # Use minimal logging until config is loaded, unless CLI overrides
    initial_config = LogConfig()
    if args.debug:
        initial_config.console_level = "debug"
    elif args.verbose:
        initial_config.console_level = "info"
    elif args.quiet:
        initial_config.console_level = "error"
    else:
        initial_config.console_level = "warning"  # Minimal during startup

    if args.no_color:
        initial_config.console_colors = False

    setup_logging(initial_config)

    # Validate only
    if args.validate:
        return validate_config(str(config_path))

    # Build CLI override config only if user explicitly requested it
    cli_log_config = None
    if cli_log_override:
        cli_log_config = LogConfig()
        if args.debug:
            cli_log_config.console_level = "debug"
        elif args.verbose:
            cli_log_config.console_level = "info"
        elif args.quiet:
            cli_log_config.console_level = "error"
        else:
            cli_log_config.console_level = "info"  # Default if only --no-color or --log-file

        if args.no_color:
            cli_log_config.console_colors = False

        if args.log_file:
            cli_log_config.file_enabled = True
            cli_log_config.file_path = args.log_file

    # Run application
    try:
        asyncio.run(run_app(str(config_path), cli_log_config=cli_log_config))
        return 0
    except ConfigError as e:
        logger.error(f"Configuration error: {e}")
        return 1
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 0
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
