"""
Home Assistant device model for MQTT Discovery.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _add_via_device_if_needed(
    device: Device, parent_device: Device | None, source_type: str
) -> None:
    """
    Automatically add via_device to device if parent_device exists and it's not system device.

    Args:
        device: Device to add via_device to
        parent_device: Parent device (usually system device)
        source_type: Source type of the collector (to skip system devices)
    """
    # Don't add via_device to system devices
    if source_type == "system":
        return

    # Don't add if no parent device
    if not parent_device:
        return

    # Don't overwrite existing via_device
    if "via_device" in device.extra_fields:
        return

    # Add via_device with parent device's primary identifier
    if device.extra_fields is None:
        device.extra_fields = {}
    device.extra_fields["via_device"] = parent_device.primary_identifier


@dataclass
class Device:
    """
    Represents a Home Assistant device for MQTT Discovery.

    Devices group related sensors together in the HA UI.
    Each device can have multiple sensors attached to it.
    """

    # Required: at least one identifier
    identifiers: list[str] = field(default_factory=list)

    # Device information
    name: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    hw_version: str | None = None
    sw_version: str | None = None

    # Optional
    suggested_area: str | None = None
    configuration_url: str | None = None
    via_device: str | None = None  # Parent device identifier

    # Arbitrary extra fields (for any other HA device fields)
    extra_fields: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Ensure at least one identifier exists."""
        if not self.identifiers and self.name:
            # Use sanitized name as identifier if none provided
            self.identifiers = [self._sanitize_id(self.name)]

    @staticmethod
    def _sanitize_id(value: str) -> str:
        """Sanitize a string for use as an identifier."""
        # Replace spaces and special chars with underscores
        result = []
        for char in value.lower():
            if char.isalnum():
                result.append(char)
            elif char in " -_.":
                result.append("_")

        # Remove consecutive underscores
        sanitized = "".join(result)
        while "__" in sanitized:
            sanitized = sanitized.replace("__", "_")

        return sanitized.strip("_")

    def to_discovery_dict(self) -> dict[str, Any]:
        """
        Convert to dictionary for Home Assistant MQTT Discovery.

        Returns:
            Dictionary suitable for inclusion in discovery payload
        """
        result: dict[str, Any] = {}

        if self.identifiers:
            result["identifiers"] = self.identifiers

        if self.name:
            result["name"] = self.name

        if self.manufacturer:
            result["manufacturer"] = self.manufacturer

        if self.model:
            result["model"] = self.model

        if self.hw_version:
            result["hw_version"] = self.hw_version

        if self.sw_version:
            result["sw_version"] = self.sw_version

        if self.suggested_area:
            result["suggested_area"] = self.suggested_area

        if self.configuration_url:
            result["configuration_url"] = self.configuration_url

        if self.via_device:
            result["via_device"] = self.via_device

        # Apply extra fields
        if self.extra_fields:
            result.update(self.extra_fields)

        return result

    @property
    def primary_identifier(self) -> str:
        """Get the primary (first) identifier."""
        if self.identifiers:
            return self.identifiers[0]
        return "unknown"

    def with_identifier_prefix(self, prefix: str) -> Device:
        """Create a new device with prefixed identifiers."""
        new_ids = [f"{prefix}_{id}" for id in self.identifiers]
        return Device(
            identifiers=new_ids,
            name=self.name,
            manufacturer=self.manufacturer,
            model=self.model,
            hw_version=self.hw_version,
            sw_version=self.sw_version,
            suggested_area=self.suggested_area,
            configuration_url=self.configuration_url,
            via_device=self.via_device,
            extra_fields=self.extra_fields.copy() if self.extra_fields else {},
        )


def create_device(
    source_type: str,
    source_name: str,
    source_id: str | None = None,
    topic_prefix: str = "penguin_metrics",
    manufacturer: str = "Penguin Metrics",
    model: str = "Linux Monitor",
    **kwargs: Any,
) -> Device:
    """
    Factory function to create a device for a metric source.

    Args:
        source_type: Type of source (system, process, service, container, etc.)
        source_name: Human-readable name
        source_id: Unique identifier (generated from name if not provided)
        topic_prefix: MQTT topic prefix (for unique identifier generation)
        manufacturer: Device manufacturer
        model: Device model
        **kwargs: Additional device attributes

    Returns:
        Configured Device instance
    """
    device_id = source_id or Device._sanitize_id(source_name)
    identifier = f"penguin_metrics_{topic_prefix}_{source_type}_{device_id}"

    return Device(
        identifiers=[identifier],
        name=source_name,
        manufacturer=manufacturer,
        model=model,
        **kwargs,
    )
