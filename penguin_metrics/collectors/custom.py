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
from pathlib import Path
from typing import Any

from .base import Collector, CollectorResult
from ..models.device import Device
from ..models.sensor import Sensor, DeviceClass, StateClass, create_sensor
from ..config.schema import CustomSensorConfig, DefaultsConfig


class CustomCollector(Collector):
    """
    Collector for custom command/script sensors.
    
    Executes a command or script and parses the output as a sensor value.
    """
    
    def __init__(
        self,
        config: CustomSensorConfig,
        defaults: DefaultsConfig,
        topic_prefix: str = "penguin_metrics",
    ):
        """
        Initialize custom collector.
        
        Args:
            config: Custom sensor configuration
            defaults: Default settings
            topic_prefix: MQTT topic prefix
        """
        super().__init__(
            name=config.name,
            collector_id=config.id or config.name,
            update_interval=config.update_interval or defaults.update_interval,
        )
        
        self.config = config
        self.defaults = defaults
        self.topic_prefix = topic_prefix
        
        # Build command
        if config.script:
            self._command = config.script
        elif config.command:
            self._command = config.command
        else:
            self._command = None
        
        self._last_value: Any = None
        self._last_error: str | None = None
    
    def create_device(self) -> Device:
        """Create device for custom sensor."""
        device_config = self.config.device
        
        return Device(
            identifiers=[f"penguin_metrics_custom_{self.collector_id}"],
            name=device_config.name or f"Custom: {self.config.name}",
            manufacturer=device_config.manufacturer,
            model="Custom Sensor",
        )
    
    def create_sensors(self) -> list[Sensor]:
        """Create sensor for custom command."""
        device = self.device
        
        # Determine device class
        device_class = None
        if self.config.device_class:
            try:
                device_class = DeviceClass(self.config.device_class)
            except ValueError:
                device_class = self.config.device_class
        
        # Determine state class
        state_class = None
        if self.config.state_class:
            try:
                state_class = StateClass(self.config.state_class)
            except ValueError:
                state_class = self.config.state_class
        
        sensor = create_sensor(
            source_id=self.collector_id,
            metric_name="value",
            display_name=self.config.name,
            device=device,
            topic_prefix=self.topic_prefix,
            unit=self.config.unit,
            device_class=device_class,
            state_class=state_class,
            icon="mdi:cog-outline",
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
            except asyncio.TimeoutError:
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
                raise ValueError(f"Cannot parse number from: {output}")
        
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
            result.set_error(error_msg)
            return result
        
        if not stdout:
            result.set_error("Command produced no output")
            return result
        
        # Parse output
        try:
            value = self._parse_output(stdout)
            self._last_value = value
            self._last_error = None
            
            # Format value for metric
            if isinstance(value, float):
                value = round(value, 4)
            
            result.add_metric(f"{self.collector_id}_value", value)
        
        except Exception as e:
            self._last_error = str(e)
            result.set_error(f"Parse error: {e}")
        
        return result

