"""
Entry point for Penguin Metrics.

Usage:
    python -m penguin_metrics /path/to/config.conf
    python -m penguin_metrics --help
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from . import __version__
from .app import run_app
from .config.loader import ConfigLoader, ConfigError


def setup_logging(verbose: bool = False, debug: bool = False) -> None:
    """Configure logging."""
    if debug:
        level = logging.DEBUG
    elif verbose:
        level = logging.INFO
    else:
        level = logging.WARNING
    
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    
    # Reduce noise from libraries
    logging.getLogger("aiomqtt").setLevel(logging.WARNING)
    logging.getLogger("paho").setLevel(logging.WARNING)


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
        print(f"\nConfiguration summary:")
        print(f"  MQTT: {config.mqtt.host}:{config.mqtt.port}")
        print(f"  Home Assistant Discovery: {'enabled' if config.homeassistant.discovery else 'disabled'}")
        print(f"  System collectors: {len(config.system)}")
        print(f"  Process monitors: {len(config.processes)}")
        print(f"  Service monitors: {len(config.services)}")
        print(f"  Container monitors: {len(config.containers)}")
        print(f"  Battery monitors: {len(config.batteries)}")
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
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    
    parser.add_argument(
        "-d", "--debug",
        action="store_true",
        help="Enable debug logging",
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
    
    # Setup logging
    setup_logging(verbose=args.verbose, debug=args.debug)
    
    # Validate only
    if args.validate:
        return validate_config(str(config_path))
    
    # Run application
    try:
        asyncio.run(run_app(str(config_path)))
        return 0
    except ConfigError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    except Exception as e:
        logging.exception("Fatal error")
        return 1


if __name__ == "__main__":
    sys.exit(main())

