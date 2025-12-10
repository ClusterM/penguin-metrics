"""
Pytest configuration and fixtures.
"""

from pathlib import Path

import pytest


@pytest.fixture
def example_config_path(tmp_path: Path) -> Path:
    """Path to example config file."""
    # This will be used when we have actual config tests
    return tmp_path / "config.conf"
