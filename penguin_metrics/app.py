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

from .config.loader import ConfigLoader, ConfigError
from .config.schema import Config
from .collectors.base import Collector, CollectorResult
from .collectors.system import SystemCollector
from .collectors.temperature import TemperatureCollector
from .collectors.process import ProcessCollector
from .collectors.battery import BatteryCollector
from .collectors.service import ServiceCollector
from .collectors.container import ContainerCollector
from .collectors.custom import CustomCollector
from .collectors.gpu import GPUCollector
from .mqtt.client import MQTTClient
from .mqtt.homeassistant import HomeAssistantDiscovery
from .logging import get_logger, setup_logging, LogConfig


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
        self._shutdown_event = asyncio.Event()
    
    def _create_collectors(self) -> list[Collector]:
        """Create all configured collectors."""
        collectors: list[Collector] = []
        topic_prefix = self.config.mqtt.topic_prefix
        
        # System collectors
        for sys_config in self.config.system:
            collectors.append(SystemCollector(
                config=sys_config,
                defaults=self.config.defaults,
                topic_prefix=topic_prefix,
            ))
            
            # Add temperature collector if enabled
            if sys_config.temperature:
                collectors.append(TemperatureCollector(
                    config=sys_config,
                    defaults=self.config.defaults,
                    topic_prefix=topic_prefix,
                ))
            
            # Add GPU collector if enabled
            if sys_config.gpu:
                collectors.append(GPUCollector(
                    config=sys_config,
                    defaults=self.config.defaults,
                    topic_prefix=topic_prefix,
                ))
        
        # Standalone temperature collectors
        for temp_config in self.config.temperatures:
            collectors.append(TemperatureCollector(
                config=temp_config,
                defaults=self.config.defaults,
                topic_prefix=topic_prefix,
            ))
        
        # Process collectors
        for proc_config in self.config.processes:
            collectors.append(ProcessCollector(
                config=proc_config,
                defaults=self.config.defaults,
                topic_prefix=topic_prefix,
            ))
        
        # Service collectors (systemd)
        for svc_config in self.config.services:
            collectors.append(ServiceCollector(
                config=svc_config,
                defaults=self.config.defaults,
                topic_prefix=topic_prefix,
            ))
        
        # Container collectors (Docker)
        for cont_config in self.config.containers:
            collectors.append(ContainerCollector(
                config=cont_config,
                defaults=self.config.defaults,
                topic_prefix=topic_prefix,
            ))
        
        # Battery collectors
        for bat_config in self.config.batteries:
            collectors.append(BatteryCollector(
                config=bat_config,
                defaults=self.config.defaults,
                topic_prefix=topic_prefix,
            ))
        
        # Custom collectors
        for custom_config in self.config.custom:
            collectors.append(CustomCollector(
                config=custom_config,
                defaults=self.config.defaults,
                topic_prefix=topic_prefix,
            ))
        
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
                    logger.debug(f"Registered {len(collector.sensors)} sensors for {collector.name}")
            
            except Exception as e:
                logger.error(f"Failed to initialize collector {collector.name}: {e}")
    
    async def _run_collector(self, collector: Collector) -> None:
        """Run a single collector loop."""
        logger.info(f"Starting collector: {collector.name} (interval: {collector.update_interval}s)")
        
        while self._running:
            try:
                result = await collector.safe_collect()
                
                # Publish metrics (only if collector is available)
                if result.available:
                    for metric in result.metrics:
                        # Get topic from collector (allows custom topic structures)
                        topic = collector.metric_topic(metric.sensor_id, self.config.mqtt.topic_prefix)
                        
                        value = metric.value
                        if isinstance(value, float):
                            value = round(value, 2)
                        
                        await self.mqtt.publish_data(topic, value)
                else:
                    # Source not found - publish state as unavailable
                    topic = f"{self.config.mqtt.topic_prefix}/{collector.SOURCE_TYPE}/{collector.name}/state"
                    await self.mqtt.publish_data(topic, "not_found")
                
                if not result.available:
                    logger.warning(f"Collector {collector.name} unavailable: {result.error}")
            
            except Exception as e:
                logger.error(f"Error in collector {collector.name}: {e}")
            
            await asyncio.sleep(collector.update_interval)
    
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
        self.collectors = self._create_collectors()
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
        
        logger.info("Penguin Metrics started successfully")
        
        # Wait for shutdown
        await self._shutdown_event.wait()
        
        # Cleanup
        await self.stop()
    
    async def stop(self) -> None:
        """Stop the application."""
        logger.info("Stopping Penguin Metrics")
        
        self._running = False
        
        # Cancel collector tasks
        for task in self._tasks:
            task.cancel()
        
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        
        self._tasks.clear()
        
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

