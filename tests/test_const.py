"""
Tests for constants.
"""

from penguin_metrics.const import APP_NAME, APP_URL, APP_VERSION


def test_constants():
    """Test that constants are defined."""
    assert APP_NAME == "Penguin Metrics"
    assert APP_VERSION == "0.0.1"
    assert APP_URL == "https://github.com/clusterm/penguin-metrics"
