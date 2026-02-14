"""
Custom command/script sensor collector.

Executes user-defined commands or scripts and parses the output
as sensor values.

Supports:
- Shell commands
- Script files
- Output types: number, string, json
- Scaling and unit conversion
"""

import asyncio
import json
from typing import Any

from ..config.schema import CustomSensorConfig, DefaultsConfig, DeviceConfig
from ..models.device import Device, create_device_from_ref
from ..models.sensor import DeviceClass, Sensor, StateClass
from .base import Collector, CollectorResult, build_sensor


class CustomCollector(Collector):
    SOURCE_TYPE = "custom"
    """
    Collector for custom command/script sensors.

    Executes a command or script and parses the output as a sensor value.
    """

    def __init__(
        self,
        config: CustomSensorConfig,
        defaults: DefaultsConfig,
        topic_prefix: str = "penguin_metrics",
        device_templates: dict[str, DeviceConfig] | None = None,
        parent_device: Device | None = None,
    ):
        """
        Initialize custom collector.

        Args:
            config: Custom sensor configuration
            defaults: Default settings
            topic_prefix: MQTT topic prefix
            device_templates: Device template definitions
            parent_device: System device (for device_ref="system")
        """
        super().__init__(
            name=config.name,
            collector_id=config.name,  # name is the ID, used for MQTT topics
            update_interval=config.update_interval or defaults.update_interval,
        )

        self.config = config
        self.defaults = defaults
        self.topic_prefix = topic_prefix
        self.device_templates = device_templates or {}
        self.parent_device = parent_device

        # Build command
        if config.script:
            self._command: str | None = config.script
        elif config.command:
            self._command = config.command
        else:
            self._command = None

        self._last_value: Any = None
        self._last_error: str | None = None

    def create_device(self) -> Device | None:
        """Create device for custom sensor."""
        return create_device_from_ref(
            device_ref=self.config.device_ref,
            source_type=self.SOURCE_TYPE,
            collector_id=self.collector_id,
            topic_prefix=self.topic_prefix,
            default_name=f"Custom: {self.config.label}",
            manufacturer="Penguin Metrics",
            model="Custom Sensor",
            parent_device=self.parent_device,
            device_templates=self.device_templates,
        )

    def create_sensors(self) -> list[Sensor]:
        """Create sensor for custom command."""
        device = self.device

        # Determine device class
        device_class: DeviceClass | str | None = None
        if self.config.device_class:
            try:
                device_class = DeviceClass(self.config.device_class)
            except ValueError:
                device_class = self.config.device_class

        # Determine state class
        state_class: StateClass | str | None = None
        if self.config.state_class:
            try:
                state_class = StateClass(self.config.state_class)
            except ValueError:
                state_class = self.config.state_class

        sensor = build_sensor(
            source_type="custom",
            source_name=self.collector_id,  # Use collector_id for MQTT topic
            metric_name="value",
            display_name=self.config.label,
            device=device,
            topic_prefix=self.topic_prefix,
            unit=self.config.unit
            or (self.config.ha_config.unit_of_measurement if self.config.ha_config else None),
            device_class=device_class
            or (self.config.ha_config.device_class if self.config.ha_config else None),
            state_class=state_class
            or (self.config.ha_config.state_class if self.config.ha_config else None),
            icon="mdi:cog-outline",
            ha_config=self.config.ha_config,
        )

        return [sensor]

    async def _execute_command(self) -> tuple[str, str, int]:
        """
        Execute the command and return output.

        Returns:
            Tuple of (stdout, stderr, return_code)
        """
        if not self._command:
            return "", "No command configured", 1

        try:
            proc = await asyncio.create_subprocess_shell(
                self._command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=self.config.timeout,
                )
            except TimeoutError:
                proc.kill()
                await proc.wait()
                return "", "Command timed out", -1

            return (
                stdout.decode().strip(),
                stderr.decode().strip(),
                proc.returncode or 0,
            )

        except Exception as e:
            return "", str(e), -1

    def _parse_output(self, output: str) -> Any:
        """
        Parse command output based on configured type.

        Args:
            output: Command stdout

        Returns:
            Parsed value
        """
        output_type = self.config.type.lower()

        if output_type == "number":
            # Try to parse as number
            try:
                value = float(output)
                value *= self.config.scale
                return value
            except ValueError:
                # Try to extract first number from output
                import re

                match = re.search(r"[-+]?\d*\.?\d+", output)
                if match:
                    value = float(match.group())
                    value *= self.config.scale
                    return value
                raise ValueError(f"Cannot parse number from: {output}") from None

        elif output_type == "string":
            return output

        elif output_type == "json":
            data = json.loads(output)
            # If JSON is a simple value, return it
            if isinstance(data, (int, float, str, bool)):
                return data
            # Otherwise return as-is (will be JSON encoded)
            return data

        else:
            return output

    async def collect(self) -> CollectorResult:
        """Collect custom sensor value."""
        result = CollectorResult()

        if not self._command:
            result.set_error("No command configured")
            return result

        # Execute command
        stdout, stderr, returncode = await self._execute_command()

        if returncode != 0:
            error_msg = stderr or f"Command failed with code {returncode}"
            self._last_error = error_msg
            result.set_unavailable("error")
            return result

        if not stdout:
            result.set_error("Command produced no output")
            return result

        # Parse output
        try:
            value = self._parse_output(stdout)
            self._last_value = value
            self._last_error = None

            if isinstance(value, float):
                value = round(value, 4)

            result.set("value", value)
            result.set_state("online")

        except Exception as e:
            self._last_error = str(e)
            result.set_error(f"Parse error: {e}")

        return result
