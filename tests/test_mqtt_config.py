"""
Tests for MQTT configuration retain behavior.
"""

from penguin_metrics.config.schema import MQTTConfig, RetainMode


def test_should_retain_status_defaults_to_on() -> None:
    config = MQTTConfig()

    assert config.should_retain() is True
    assert config.should_retain_status() is True


def test_should_retain_status_respects_off() -> None:
    config = MQTTConfig(retain=RetainMode.OFF)

    assert config.should_retain() is False
    assert config.should_retain_status() is False
