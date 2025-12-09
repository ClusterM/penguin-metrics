"""
Pytest configuration and fixtures.
"""
import pytest


@pytest.fixture
def example_config_path(tmp_path):
    """Path to example config file."""
    # This will be used when we have actual config tests
    return tmp_path / "config.conf"

