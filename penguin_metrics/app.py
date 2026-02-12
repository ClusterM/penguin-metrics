"""
Main application orchestrator.

Handles:
- Configuration loading
- Collector management
- MQTT publishing
- Graceful shutdown
"""

import asyncio
import signal
from typing import Any

from .collectors.ac_power import ACPowerCollector
from .collectors.base import Collector
from .collectors.battery import BatteryCollector
from .collectors.container import ContainerCollector
from .collectors.custom import CustomCollector
from .collectors.custom_binary import CustomBinarySensorCollector
from .collectors.disk import DiskCollector
from .collectors.gpu import GPUCollector
from .collectors.process import ProcessCollector
from .collectors.service import ServiceCollector
from .collectors.system import SystemCollector
from .collectors.temperature import TemperatureCollector
from .config.loader import ConfigLoader
from .config.schema import Config
from .logging import LogConfig, get_logger, setup_logging
from .models.device import Device
from .mqtt.client import MQTTClient
from .mqtt.homeassistant import HomeAssistantDiscovery

logger = get_logger("app")


class Application:
    """
    Main application class.

    Orchestrates collectors, MQTT client, and Home Assistant integration.
    """

    def __init__(self, config: Config):
        """
        Initialize application.

        Args:
            config: Application configuration
        """
        self.config = config

        # MQTT client
        self.mqtt = MQTTClient(
            config.mqtt,
            availability_topic=f"{config.mqtt.topic_prefix}/status",
        )

        # Home Assistant discovery
        self.ha = HomeAssistantDiscovery(
            self.mqtt,
            config.homeassistant,
            state_file=config.homeassistant.state_file,
        )

        # Collectors
        self.collectors: list[Collector] = []

        # State
        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._collector_tasks: dict[str, asyncio.Task] = {}  # collector_id -> task
        self._shutdown_event = asyncio.Event()
        self._refresh_task: asyncio.Task | None = None

    async def _create_collectors(self) -> list[Collector]:
        """Create all configured collectors."""
        collectors: list[Collector] = []
        topic_prefix = self.config.mqtt.topic_prefix

        # Track manually configured names to avoid duplicates with auto-discovery
        manual_temps: set[str] = set()
        manual_batteries: set[str] = set()
        manual_containers: set[str] = set()
        manual_services: set[str] = set()

        # Get device templates from config
        device_templates = self.config.device_templates

        # System collectors - create first to get system device for temperatures/GPU
        system_device: Device | None = None
        for sys_config in self.config.system:
            system_collector = SystemCollector(
                config=sys_config,
                defaults=self.config.defaults,
                topic_prefix=topic_prefix,
                device_templates=device_templates,
            )
            collectors.append(system_collector)

            # Get system device for temperature/GPU sensors (use first system)
            if system_device is None:
                system_device = system_collector.create_device()

            # Add GPU collector if enabled - uses system device
            if sys_config.gpu:
                collectors.append(
                    GPUCollector(
                        config=sys_config,
                        defaults=self.config.defaults,
                        topic_prefix=topic_prefix,
                        parent_device=system_device,
                        device_templates=device_templates,
                    )
                )

        # Standalone temperature collectors (manual) - part of system device by default
        for temp_config in self.config.temperatures:
            manual_temps.add(temp_config.name)
            collectors.append(
                TemperatureCollector(
                    config=temp_config,
                    defaults=self.config.defaults,
                    topic_prefix=topic_prefix,
                    parent_device=system_device,
                    device_templates=device_templates,
                )
            )

        # Auto-discover temperatures - always use system device
        auto_temps = self._auto_discover_temperatures(manual_temps, topic_prefix, system_device)
        if auto_temps:
            logger.info(f"Auto-discovered {len(auto_temps)} temperature sensors")
        collectors.extend(auto_temps)

        # Process collectors (manual)
        manual_processes: set[str] = set()
        for proc_config in self.config.processes:
            manual_processes.add(proc_config.name)
            collectors.append(
                ProcessCollector(
                    config=proc_config,
                    defaults=self.config.defaults,
                    topic_prefix=topic_prefix,
                    device_templates=device_templates,
                    parent_device=system_device,
                )
            )

        # Auto-discover processes
        auto_processes = self._auto_discover_processes(
            manual_processes, topic_prefix, system_device
        )
        if auto_processes:
            logger.info(f"Auto-discovered {len(auto_processes)} processes")
        collectors.extend(auto_processes)

        # Service collectors (manual)
        for svc_config in self.config.services:
            manual_services.add(svc_config.name)
            collectors.append(
                ServiceCollector(
                    config=svc_config,
                    defaults=self.config.defaults,
                    topic_prefix=topic_prefix,
                    device_templates=device_templates,
                    parent_device=system_device,
                )
            )

        # Auto-discover services
        auto_services = self._auto_discover_services(manual_services, topic_prefix, system_device)
        if auto_services:
            logger.info(f"Auto-discovered {len(auto_services)} services")
        collectors.extend(auto_services)

        # Container collectors (manual)
        for cont_config in self.config.containers:
            manual_containers.add(cont_config.name)
            collectors.append(
                ContainerCollector(
                    config=cont_config,
                    defaults=self.config.defaults,
                    topic_prefix=topic_prefix,
                    device_templates=device_templates,
                    parent_device=system_device,
                )
            )

        # Auto-discover containers
        auto_containers = await self._auto_discover_containers(
            manual_containers, topic_prefix, system_device
        )
        if auto_containers:
            logger.info(f"Auto-discovered {len(auto_containers)} containers")
        collectors.extend(auto_containers)

        # Battery collectors (manual) - part of system device by default
        for bat_config in self.config.batteries:
            manual_batteries.add(bat_config.name)
            collectors.append(
                BatteryCollector(
                    config=bat_config,
                    defaults=self.config.defaults,
                    topic_prefix=topic_prefix,
                    parent_device=system_device,
                    device_templates=device_templates,
                )
            )

        # Auto-discover batteries - always use system device
        auto_batteries = self._auto_discover_batteries(
            manual_batteries, topic_prefix, system_device
        )
        if auto_batteries:
            logger.info(f"Auto-discovered {len(auto_batteries)} batteries")
        collectors.extend(auto_batteries)

        # AC power (external power supply) - part of system device by default
        manual_ac_power: set[str] = set()
        for ac_config in self.config.ac_power:
            manual_ac_power.add(ac_config.name)
            collectors.append(
                ACPowerCollector(
                    config=ac_config,
                    defaults=self.config.defaults,
                    topic_prefix=topic_prefix,
                    parent_device=system_device,
                    device_templates=device_templates,
                )
            )

        # Auto-discover AC power supplies - always use system device
        auto_ac_power = self._auto_discover_ac_power(manual_ac_power, topic_prefix, system_device)
        if auto_ac_power:
            logger.info(f"Auto-discovered {len(auto_ac_power)} AC power supplies")
        collectors.extend(auto_ac_power)

        # Disk collectors (manual) - part of system device by default
        manual_disks: set[str] = set()
        for disk_config in self.config.disks:
            manual_disks.add(disk_config.name)
            collectors.append(
                DiskCollector(
                    config=disk_config,
                    defaults=self.config.defaults,
                    topic_prefix=topic_prefix,
                    parent_device=system_device,
                    device_templates=device_templates,
                )
            )

        # Auto-discover disks - always use system device
        auto_disks = self._auto_discover_disks(manual_disks, topic_prefix, system_device)
        if auto_disks:
            logger.info(f"Auto-discovered {len(auto_disks)} disks")
        collectors.extend(auto_disks)

        # Custom collectors
        for custom_config in self.config.custom:
            collectors.append(
                CustomCollector(
                    config=custom_config,
                    defaults=self.config.defaults,
                    topic_prefix=topic_prefix,
                    device_templates=device_templates,
                    parent_device=system_device,
                )
            )

        # Custom binary sensor collectors
        for binary_config in self.config.binary_sensors:
            collectors.append(
                CustomBinarySensorCollector(
                    config=binary_config,
                    defaults=self.config.defaults,
                    topic_prefix=topic_prefix,
                    device_templates=device_templates,
                    parent_device=system_device,
                )
            )

        return collectors

    def _auto_discover_temperatures(
        self, exclude: set[str], topic_prefix: str, parent_device: Device | None = None
    ) -> list[Collector]:
        """Auto-discover temperature sensors."""
        from .collectors.temperature import discover_hwmon_sensors, discover_thermal_zones

        auto_cfg = self.config.auto_temperatures
        if not auto_cfg.enabled:
            return []

        collectors: list[Collector] = []
        device_templates = self.config.device_templates

        def apply_overrides(config_obj: Any) -> None:
            """Apply bool and interval overrides from auto-discovery block."""
            for key, val in auto_cfg.options.items():
                if hasattr(config_obj, key):
                    setattr(config_obj, key, val)
            if auto_cfg.update_interval is not None and hasattr(config_obj, "update_interval"):
                config_obj.update_interval = auto_cfg.update_interval

        if auto_cfg.source == "thermal":
            # Discover thermal zones from /sys/class/thermal
            for zone in discover_thermal_zones():
                name = zone.type if zone.type != zone.name else zone.name
                if name in exclude:
                    continue
                if not auto_cfg.matches(name):
                    continue

                from .config.schema import TemperatureConfig

                config = TemperatureConfig.from_defaults(name=name, defaults=self.config.defaults)
                config.zone = zone.name
                config.device_ref = auto_cfg.device_ref  # Use auto-discovery device_ref
                apply_overrides(config)
                collectors.append(
                    TemperatureCollector(
                        config=config,
                        defaults=self.config.defaults,
                        topic_prefix=topic_prefix,
                        parent_device=parent_device,
                        device_templates=device_templates,
                    )
                )
                logger.debug(f"Auto-discovered thermal zone: {name}")

        elif auto_cfg.source == "hwmon":
            # Discover hwmon sensors via psutil
            for sensor in discover_hwmon_sensors():
                name = f"{sensor.chip}_{sensor.label}".lower().replace(" ", "_")
                if name in exclude:
                    continue
                if not auto_cfg.matches(name):
                    continue

                from .config.schema import TemperatureConfig

                config = TemperatureConfig.from_defaults(name=name, defaults=self.config.defaults)
                config.hwmon = name
                config.device_ref = auto_cfg.device_ref  # Use auto-discovery device_ref
                apply_overrides(config)
                collectors.append(
                    TemperatureCollector(
                        config=config,
                        defaults=self.config.defaults,
                        topic_prefix=topic_prefix,
                        parent_device=parent_device,
                        device_templates=device_templates,
                    )
                )
                logger.debug(f"Auto-discovered hwmon sensor: {name}")

        if collectors:
            logger.debug(f"Found {len(collectors)} temperature sensors")

        return collectors

    def _auto_discover_batteries(
        self, exclude: set[str], topic_prefix: str, parent_device: Device | None = None
    ) -> list[Collector]:
        """Auto-discover battery devices."""
        from .collectors.battery import discover_batteries

        auto_cfg = self.config.auto_batteries
        if not auto_cfg.enabled:
            return []

        collectors: list[Collector] = []
        device_templates = self.config.device_templates

        for battery in discover_batteries():
            name = battery.name  # BAT0, BAT1, etc.
            if name in exclude:
                continue
            if not auto_cfg.matches(name):
                continue

            from .config.schema import BatteryConfig

            config = BatteryConfig.from_defaults(name=name, defaults=self.config.defaults)
            config.device_ref = auto_cfg.device_ref  # Use auto-discovery device_ref
            # Apply per-metric overrides from auto-discovery block
            for key, val in auto_cfg.options.items():
                if hasattr(config, key):
                    setattr(config, key, val)
            if auto_cfg.update_interval is not None:
                config.update_interval = auto_cfg.update_interval
            collectors.append(
                BatteryCollector(
                    config=config,
                    defaults=self.config.defaults,
                    topic_prefix=topic_prefix,
                    parent_device=parent_device,
                    device_templates=device_templates,
                )
            )
            logger.debug(f"Auto-discovered battery: {name}")

        if collectors:
            logger.debug(f"Found {len(collectors)} batteries")

        return collectors

    def _auto_discover_ac_power(
        self, exclude: set[str], topic_prefix: str, parent_device: Device | None = None
    ) -> list[Collector]:
        """Auto-discover external power supplies (non-battery)."""
        from .collectors.ac_power import discover_ac_power

        auto_cfg = self.config.auto_ac_powers
        if not auto_cfg.enabled:
            return []

        collectors: list[Collector] = []
        device_templates = self.config.device_templates

        for ps in discover_ac_power():
            name = ps.name
            if name in exclude:
                continue
            if not auto_cfg.matches(name) and not auto_cfg.matches(ps.type):
                continue

            from .config.schema import ACPowerConfig

            config = ACPowerConfig.from_defaults(name=name, defaults=self.config.defaults)
            # For auto-discovery, always point to the concrete path we found
            config.path = str(ps.path)
            # Apply auto-discovery device_ref and overrides (if any)
            config.device_ref = auto_cfg.device_ref
            if auto_cfg.update_interval is not None:
                config.update_interval = auto_cfg.update_interval

            collectors.append(
                ACPowerCollector(
                    config=config,
                    defaults=self.config.defaults,
                    topic_prefix=topic_prefix,
                    parent_device=parent_device,
                    device_templates=device_templates,
                )
            )
            logger.debug(f"Auto-discovered AC power supply: {name} (type={ps.type})")

        if collectors:
            logger.debug(f"Found {len(collectors)} AC power supplies")

        return collectors

    def _auto_discover_disks(
        self, exclude: set[str], topic_prefix: str, parent_device: Device | None = None
    ) -> list[Collector]:
        """Auto-discover disk partitions."""
        from .collectors.disk import discover_disks

        auto_cfg = self.config.auto_disks
        if not auto_cfg.enabled:
            return []

        collectors: list[Collector] = []
        device_templates = self.config.device_templates

        for disk in discover_disks():
            name = disk.name  # sda1, nvme0n1p1, etc.
            if name in exclude:
                continue
            if not auto_cfg.matches(name):
                continue

            from .config.schema import DiskConfig

            config = DiskConfig.from_defaults(
                name=name,
                path=name,
                defaults=self.config.defaults,
            )
            # Apply auto-discovery device_ref
            config.device_ref = auto_cfg.device_ref
            # Apply overrides from auto-discovery block
            for key, val in auto_cfg.options.items():
                if hasattr(config, key):
                    setattr(config, key, val)
            if auto_cfg.update_interval is not None:
                config.update_interval = auto_cfg.update_interval
            collectors.append(
                DiskCollector(
                    config=config,
                    defaults=self.config.defaults,
                    topic_prefix=topic_prefix,
                    parent_device=parent_device,
                    device_templates=device_templates,
                )
            )
            logger.debug(f"Auto-discovered disk: {name} ({disk.mountpoint})")

        if collectors:
            logger.debug(f"Found {len(collectors)} disks")

        return collectors

    async def _auto_discover_containers(
        self, exclude: set[str], topic_prefix: str, parent_device: Device | None = None
    ) -> list[Collector]:
        """Auto-discover Docker containers."""
        from .utils.docker_api import DockerClient

        auto_cfg = self.config.auto_containers
        if not auto_cfg.enabled:
            return []

        collectors: list[Collector] = []
        docker = DockerClient()
        device_templates = self.config.device_templates

        if not docker.available:
            logger.warning("Docker not available for auto-discovery")
            return []

        try:
            containers = await docker.list_containers(all=False)  # Only running containers
        except Exception as e:
            logger.warning(f"Failed to list containers: {e}")
            return []

        for container in containers:
            name = container.name
            if name in exclude:
                continue
            if not auto_cfg.matches(name):
                continue

            from .config.schema import ContainerConfig, ContainerMatchConfig, ContainerMatchType

            config = ContainerConfig.from_defaults(
                name=name,
                match=ContainerMatchConfig(type=ContainerMatchType.NAME, value=name),
                defaults=self.config.defaults,
            )
            # Apply auto-discovery device_ref and overrides
            config.device_ref = auto_cfg.device_ref
            for key, val in auto_cfg.options.items():
                if hasattr(config, key):
                    setattr(config, key, val)
            if auto_cfg.update_interval is not None:
                config.update_interval = auto_cfg.update_interval
            collectors.append(
                ContainerCollector(
                    config=config,
                    defaults=self.config.defaults,
                    topic_prefix=topic_prefix,
                    device_templates=device_templates,
                    parent_device=parent_device,
                )
            )
            logger.debug(f"Auto-discovered container: {name}")

        if collectors:
            logger.debug(f"Found {len(collectors)} containers")

        return collectors

    def _auto_discover_services(
        self, exclude: set[str], topic_prefix: str, parent_device: Device | None = None
    ) -> list[Collector]:
        """Auto-discover systemd services."""
        import subprocess

        auto_cfg = self.config.auto_services
        if not auto_cfg.enabled:
            return []

        # Require filter for services (too many otherwise)
        if not auto_cfg.filters:
            logger.warning(
                "Service auto-discovery requires a filter pattern. "
                "Use 'filter \"docker*\";' for specific services, or 'filter \"*\";' for ALL services."
            )
            return []

        collectors: list[Collector] = []
        device_templates = self.config.device_templates

        try:
            # Get list of all services
            result = subprocess.run(
                ["systemctl", "list-units", "--type=service", "--no-legend", "--all"],
                capture_output=True,
                text=True,
                timeout=10,
            )

            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue

                parts = line.split()
                if not parts:
                    continue

                # Skip status symbols (● for failed services)
                unit_name = parts[0]
                if unit_name in ("●", "○", "×") or not unit_name.endswith(".service"):
                    # Try next part if first is a status symbol
                    if len(parts) > 1 and parts[1].endswith(".service"):
                        unit_name = parts[1]
                    else:
                        continue
                name = unit_name.replace(".service", "")

                if name in exclude:
                    continue
                if not auto_cfg.matches(unit_name) and not auto_cfg.matches(name):
                    continue

                from .config.schema import ServiceConfig, ServiceMatchConfig, ServiceMatchType

                config = ServiceConfig.from_defaults(
                    name=name,
                    match=ServiceMatchConfig(type=ServiceMatchType.UNIT, value=unit_name),
                    defaults=self.config.defaults,
                )
                # Apply auto-discovery device_ref and overrides
                config.device_ref = auto_cfg.device_ref
                for key, val in auto_cfg.options.items():
                    if hasattr(config, key):
                        setattr(config, key, val)
                if auto_cfg.update_interval is not None:
                    config.update_interval = auto_cfg.update_interval
                collectors.append(
                    ServiceCollector(
                        config=config,
                        defaults=self.config.defaults,
                        topic_prefix=topic_prefix,
                        device_templates=device_templates,
                        parent_device=parent_device,
                    )
                )
                logger.debug(f"Auto-discovered service: {name}")

        except Exception as e:
            logger.warning(f"Failed to list services: {e}")

        if collectors:
            logger.debug(f"Found {len(collectors)} services")

        return collectors

    def _auto_discover_processes(
        self, exclude: set[str], topic_prefix: str, parent_device: Device | None = None
    ) -> list[Collector]:
        """Auto-discover running processes."""
        import psutil

        auto_cfg = self.config.auto_processes
        if not auto_cfg.enabled:
            return []

        # Require filter for processes (thousands in system!)
        if not auto_cfg.filters:
            logger.warning(
                "Process auto-discovery requires a filter pattern (thousands of processes in system!). "
                "Use 'filter \"python*\";' for specific processes, or 'filter \"*\";' for ALL (dangerous!)."
            )
            return []

        collectors: list[Collector] = []
        device_templates = self.config.device_templates

        try:
            for proc in psutil.process_iter(["pid", "name", "cmdline"]):
                try:
                    name = proc.info["name"]
                    if not name:
                        continue

                    # Check filter/exclude
                    if name in exclude:
                        continue
                    if not auto_cfg.matches(name):
                        continue

                    # Create unique collector name
                    collector_name = f"{name}_{proc.info['pid']}"

                    from .config.schema import ProcessConfig, ProcessMatchConfig, ProcessMatchType

                    config = ProcessConfig.from_defaults(
                        name=collector_name,
                        match=ProcessMatchConfig(
                            type=ProcessMatchType.PID, value=str(proc.info["pid"])
                        ),
                        defaults=self.config.defaults,
                    )
                    # Apply auto-discovery device_ref and overrides
                    config.device_ref = auto_cfg.device_ref
                    for key, val in auto_cfg.options.items():
                        if hasattr(config, key):
                            setattr(config, key, val)
                    if auto_cfg.update_interval is not None:
                        config.update_interval = auto_cfg.update_interval
                    collectors.append(
                        ProcessCollector(
                            config=config,
                            defaults=self.config.defaults,
                            topic_prefix=topic_prefix,
                            device_templates=device_templates,
                            parent_device=parent_device,
                        )
                    )
                    logger.debug(f"Auto-discovered process: {collector_name}")

                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

        except Exception as e:
            logger.warning(f"Failed to list processes: {e}")

        if collectors:
            logger.debug(f"Found {len(collectors)} processes")

        return collectors

    async def _initialize_collectors(self) -> None:
        """Initialize all collectors and register sensors."""
        for collector in self.collectors:
            try:
                await collector.initialize()
                logger.info(f"Initialized collector: {collector.name}")

                # Register sensors with Home Assistant
                if self.config.homeassistant.discovery:
                    await self.ha.register_sensors(collector.sensors)
                    logger.debug(
                        f"Registered {len(collector.sensors)} sensors for {collector.name}"
                    )

            except Exception as e:
                logger.error(f"Failed to initialize collector {collector.name}: {e}")

    async def _run_collector(self, collector: Collector) -> None:
        """Run a single collector loop."""
        logger.info(
            f"Starting collector [{collector.SOURCE_TYPE}]: {collector.name} (interval: {collector.update_interval}s)"
        )

        while self._running:
            try:
                result = await collector.safe_collect()

                # Get source topic (single JSON per source)
                topic = collector.source_topic(self.config.mqtt.topic_prefix)

                # Publish JSON data
                await self.mqtt.publish_json(topic, result.to_json_dict())

                if not result.available:
                    logger.warning(f"Collector {collector.name} unavailable: {result.error}")

            except Exception as e:
                logger.error(f"Error in collector {collector.name}: {e}")

            await asyncio.sleep(collector.update_interval)

    async def _auto_refresh_loop(self, interval: float) -> None:
        """Periodically check for new/removed auto-discovered sources."""
        logger.debug(f"Auto-refresh loop started (interval: {interval}s)")

        while self._running:
            await asyncio.sleep(interval)

            if not self._running:
                break

            try:
                await self._refresh_auto_discovered()
            except Exception as e:
                logger.error(f"Error during auto-refresh: {e}")

    async def _refresh_auto_discovered(self) -> None:
        """Check for new/removed services, containers, and processes."""
        topic_prefix = self.config.mqtt.topic_prefix

        # Get manually configured IDs (these should not be auto-removed)
        manual_ids: set[str] = set()
        for svc_cfg in self.config.services:
            manual_ids.add(svc_cfg.name)
        for cont_cfg in self.config.containers:
            manual_ids.add(cont_cfg.name)
        for proc_cfg in self.config.processes:
            manual_ids.add(proc_cfg.name)

        # Get system device from first system collector (if any)
        system_device = None
        for collector in self.collectors:
            if collector.SOURCE_TYPE == "system" and collector.device:
                system_device = collector.device
                break

        # Discover current services
        new_services = self._auto_discover_services(manual_ids, topic_prefix, system_device)
        new_service_ids = {c.collector_id for c in new_services}

        # Discover current containers
        new_containers = await self._auto_discover_containers(
            manual_ids, topic_prefix, system_device
        )
        new_container_ids = {c.collector_id for c in new_containers}

        # Discover current processes
        new_processes = self._auto_discover_processes(manual_ids, topic_prefix, system_device)
        new_process_ids = {c.collector_id for c in new_processes}

        # Find auto-discovered collectors that are currently running
        auto_service_ids = {
            c.collector_id
            for c in self.collectors
            if c.SOURCE_TYPE == "service" and c.collector_id not in manual_ids
        }
        auto_container_ids = {
            c.collector_id
            for c in self.collectors
            if c.SOURCE_TYPE == "docker" and c.collector_id not in manual_ids
        }
        auto_process_ids = {
            c.collector_id
            for c in self.collectors
            if c.SOURCE_TYPE == "process" and c.collector_id not in manual_ids
        }

        # Find new and removed
        added_services = new_service_ids - auto_service_ids
        removed_services = auto_service_ids - new_service_ids
        added_containers = new_container_ids - auto_container_ids
        removed_containers = auto_container_ids - new_container_ids
        added_processes = new_process_ids - auto_process_ids
        removed_processes = auto_process_ids - new_process_ids

        # Add new collectors
        for collector in new_services:
            if collector.collector_id in added_services:
                await self._add_collector(collector)
                logger.info(f"Auto-discovered new service: {collector.name}")

        for collector in new_containers:
            if collector.collector_id in added_containers:
                await self._add_collector(collector)
                logger.info(f"Auto-discovered new container: {collector.name}")

        for collector in new_processes:
            if collector.collector_id in added_processes:
                await self._add_collector(collector)
                logger.info(f"Auto-discovered new process: {collector.name}")

        # Remove old collectors
        for collector_id in removed_services:
            await self._remove_collector(collector_id)
            logger.info(f"Removed disappeared service: {collector_id}")

        for collector_id in removed_containers:
            await self._remove_collector(collector_id)
            logger.info(f"Removed disappeared container: {collector_id}")

        for collector_id in removed_processes:
            await self._remove_collector(collector_id)
            logger.info(f"Removed disappeared process: {collector_id}")

    async def _add_collector(self, collector: Collector) -> None:
        """Add and start a new collector."""
        try:
            await collector.initialize()

            # Register sensors
            if self.config.homeassistant.discovery:
                await self.ha.register_sensors(collector.sensors)

            # Add to list
            self.collectors.append(collector)

            # Start task
            task = asyncio.create_task(self._run_collector(collector))
            self._tasks.append(task)
            self._collector_tasks[collector.collector_id] = task

            # Save state
            self.ha._save_state()

        except Exception as e:
            logger.error(f"Failed to add collector {collector.name}: {e}")

    async def _remove_collector(self, collector_id: str) -> None:
        """Stop and remove a collector."""
        # Find collector
        collector = None
        for c in self.collectors:
            if c.collector_id == collector_id:
                collector = c
                break

        if not collector:
            return

        # Cancel task
        task = self._collector_tasks.get(collector_id)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            self._tasks.remove(task)
            del self._collector_tasks[collector_id]

        # Remove sensors from Home Assistant
        if self.config.homeassistant.discovery:
            for sensor in collector.sensors:
                topic = f"{self.ha.discovery_prefix}/sensor/{sensor.unique_id}/config"
                await self.mqtt.publish(topic, "", qos=1, retain=True)

        # Remove from list
        self.collectors.remove(collector)

        # Update state file
        self.ha._registered_sensors -= {s.unique_id for s in collector.sensors}
        self.ha._save_state()

    def _setup_signal_handlers(self) -> None:
        """Setup signal handlers for graceful shutdown."""
        loop = asyncio.get_running_loop()

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._signal_handler)

    def _signal_handler(self) -> None:
        """Handle shutdown signals."""
        logger.info("Received shutdown signal")
        self._shutdown_event.set()

    async def start(self) -> None:
        """Start the application."""
        logger.info("Starting Penguin Metrics")

        # Create collectors
        self.collectors = await self._create_collectors()
        logger.info(f"Created {len(self.collectors)} collectors")

        # Start MQTT client
        await self.mqtt.start()

        # Wait for MQTT connection
        connected = await self.mqtt.wait_connected(timeout=30.0)
        if not connected:
            logger.error("Failed to connect to MQTT broker")
            await self.mqtt.stop()
            return

        # Initialize collectors and register sensors
        await self._initialize_collectors()

        # Cleanup stale sensors and save state
        await self.ha.finalize_registration()

        # Setup signal handlers
        self._setup_signal_handlers()

        # Start collector tasks
        self._running = True
        for collector in self.collectors:
            task = asyncio.create_task(self._run_collector(collector))
            self._tasks.append(task)
            self._collector_tasks[collector.collector_id] = task

        # Start auto-refresh task if enabled
        refresh_interval = self.config.auto_refresh_interval
        if refresh_interval > 0:
            self._refresh_task = asyncio.create_task(self._auto_refresh_loop(refresh_interval))
            logger.info(
                f"Auto-refresh enabled: checking for new/removed sources every {refresh_interval}s"
            )

        logger.info("Penguin Metrics started successfully")

        # Wait for shutdown
        await self._shutdown_event.wait()

        # Cleanup
        await self.stop()

    async def stop(self) -> None:
        """Stop the application."""
        logger.info("Stopping Penguin Metrics")

        self._running = False

        # Cancel refresh task
        if self._refresh_task:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass

        # Cancel collector tasks
        for task in self._tasks:
            task.cancel()

        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        self._tasks.clear()
        self._collector_tasks.clear()

        # Note: LWT (Last Will and Testament) automatically publishes offline status
        # to {prefix}/status when connection is lost, making all sensors unavailable

        # Stop MQTT client
        await self.mqtt.stop()

        logger.info("Penguin Metrics stopped")

    async def run(self) -> None:
        """Run the application until shutdown."""
        try:
            await self.start()
        except KeyboardInterrupt:
            pass
        except Exception as e:
            logger.error(f"Application error: {e}")
            raise


async def run_app(config_path: str, cli_log_config: LogConfig | None = None) -> None:
    """
    Load configuration and run the application.

    Args:
        config_path: Path to configuration file
        cli_log_config: Logging config from CLI args (overrides file config)
    """
    # Load configuration
    loader = ConfigLoader()
    config = loader.load_file(config_path)

    # Setup logging from config file (unless CLI overrides)
    if cli_log_config is None:
        log_config = LogConfig(
            console_level=config.logging.level,
            console_colors=config.logging.colors,
            file_enabled=config.logging.file is not None,
            file_path=config.logging.file or "/var/log/penguin-metrics/penguin-metrics.log",
            file_level=config.logging.file_level,
            file_max_bytes=config.logging.file_max_size * 1024 * 1024,
            file_backup_count=config.logging.file_keep,
            format=config.logging.format,
        )
        setup_logging(log_config)
    else:
        # CLI args override file config, but merge file settings if not specified
        if not cli_log_config.file_enabled and config.logging.file:
            cli_log_config.file_enabled = True
            cli_log_config.file_path = config.logging.file
            cli_log_config.file_level = config.logging.file_level
            cli_log_config.file_max_bytes = config.logging.file_max_size * 1024 * 1024
            cli_log_config.file_backup_count = config.logging.file_keep
        setup_logging(cli_log_config)

    logger.info(f"Loaded configuration from {config_path}")
    logger.debug(f"MQTT: {config.mqtt.host}:{config.mqtt.port}")
    logger.debug(f"Topic prefix: {config.mqtt.topic_prefix}")

    # Validate configuration
    warnings = loader.validate(config)
    for warning in warnings:
        logger.warning(f"Config warning: {warning}")

    # Create and run application
    app = Application(config)
    await app.run()
