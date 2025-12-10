"""
Binary sensor collector.

Executes user-defined commands or scripts and interprets the result
as a binary state (ON/OFF).

Supports:
- Shell commands
- Script files
- Value source: returncode (0=ON, non-zero=OFF) or output (parsed as ON/OFF)
- Inversion (ON ↔ OFF)
"""

import asyncio

from ..config.schema import BinarySensorConfig, DefaultsConfig, DeviceConfig
from ..models.device import Device, create_device_from_ref
from ..models.sensor import Sensor, create_sensor
from .base import Collector, CollectorResult, apply_overrides_to_sensors


class BinarySensorCollector(Collector):
    SOURCE_TYPE = "binary_sensor"
    """
    Collector for binary sensors (ON/OFF states).

    Executes a command or script and interprets the result as a binary state.
    """

    def __init__(
        self,
        config: BinarySensorConfig,
        defaults: DefaultsConfig,
        topic_prefix: str = "penguin_metrics",
        device_templates: dict[str, DeviceConfig] | None = None,
        parent_device: Device | None = None,
    ):
        """
        Initialize binary sensor collector.

        Args:
            config: Binary sensor configuration
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

        self._last_value: str | None = None
        self._last_error: str | None = None

    def create_device(self) -> Device | None:
        """Create device for binary sensor."""
        display_name = (
            self.config.ha_config.name
            if self.config.ha_config and self.config.ha_config.name
            else self.config.name
        )
        return create_device_from_ref(
            device_ref=self.config.device_ref,
            source_type=self.SOURCE_TYPE,
            collector_id=self.collector_id,
            topic_prefix=self.topic_prefix,
            default_name=f"Binary Sensor: {display_name}",
            manufacturer="Penguin Metrics",
            model="Binary Sensor",
            parent_device=self.parent_device,
            device_templates=self.device_templates,
        )

    def create_sensors(self) -> list[Sensor]:
        """Create binary sensor."""
        device = self.device

        # Display name: use ha_config.name if specified, otherwise use name (ID)
        display_name = self.config.name
        if self.config.ha_config and self.config.ha_config.name:
            display_name = self.config.ha_config.name

        sensor = create_sensor(
            source_type="binary_sensor",
            source_name=self.collector_id,  # Use collector_id for MQTT topic
            metric_name="state",
            display_name=display_name,  # Human-readable name for HA
            device=device,
            topic_prefix=self.topic_prefix,
            entity_type="binary_sensor",  # This will be used in HA discovery
            icon="mdi:toggle-switch",
        )

        # Apply HA overrides from config (this will override any fields set above)
        apply_overrides_to_sensors([sensor], self.config.ha_config)

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

    def _parse_binary_value(self, returncode: int, output: str) -> str:
        """
        Parse command result as binary value (ON/OFF).

        Args:
            returncode: Command exit code
            output: Command stdout

        Returns:
            "ON" or "OFF"
        """
        if self.config.value_source == "returncode":
            # 0 = ON, non-zero = OFF
            value = "ON" if returncode == 0 else "OFF"
        else:  # output
            # Parse output: look for common ON/OFF patterns
            output_lower = output.lower().strip()
            if output_lower in ("on", "true", "1", "yes", "ok", "online", "up"):
                value = "ON"
            elif output_lower in ("off", "false", "0", "no", "error", "offline", "down"):
                value = "OFF"
            else:
                # Default: non-empty output = ON, empty = OFF
                value = "ON" if output else "OFF"

        # Apply inversion if configured
        if self.config.invert:
            value = "OFF" if value == "ON" else "ON"

        return value

    async def collect(self) -> CollectorResult:
        """Collect binary sensor value."""
        result = CollectorResult()

        if not self._command:
            result.set_error("No command configured")
            return result

        # Execute command
        stdout, stderr, returncode = await self._execute_command()

        # For binary sensors, we always set a state, even if command failed
        # (failed command = OFF, unless inverted)
        binary_value = self._parse_binary_value(returncode, stdout)

        self._last_value = binary_value
        if returncode != 0 and stderr:
            self._last_error = stderr
        else:
            self._last_error = None

        result.set("state", binary_value)
        result.set_state("online")

        return result
