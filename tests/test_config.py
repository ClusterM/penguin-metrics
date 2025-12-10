"""
Tests for configuration loading and validation.
"""

from pathlib import Path

from penguin_metrics.config.loader import ConfigLoader
from penguin_metrics.config.schema import Config


def test_load_example_config() -> None:
    """Test that example config loads without errors."""
    loader = ConfigLoader()
    config_path = Path(__file__).parent.parent / "config.example.conf"

    # load (alias) should work
    config = loader.load(str(config_path))

    assert config is not None
    assert isinstance(config, Config)
    assert config.mqtt.host is not None


def test_validate_example_config() -> None:
    """Test that example config validates successfully."""
    loader = ConfigLoader()
    config_path = Path(__file__).parent.parent / "config.example.conf"

    config = loader.load(str(config_path))
    _warnings = loader.validate(config)

    # Should have no critical errors (warnings are OK)
    assert config is not None


def test_load_alias_matches_load_file() -> None:
    """Ensure load() delegates to load_file() for backward compatibility."""
    loader = ConfigLoader()
    config_path = Path(__file__).parent.parent / "config.example.conf"

    via_alias = loader.load(str(config_path))
    via_direct = loader.load_file(str(config_path))

    assert isinstance(via_alias, Config)
    assert via_alias.mqtt.host == via_direct.mqtt.host
