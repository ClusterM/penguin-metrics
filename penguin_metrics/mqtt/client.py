"""
MQTT client wrapper using aiomqtt.

Features:
- Automatic reconnection
- Last Will and Testament (LWT) for availability
- QoS configuration
- Batch publishing support
"""

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator
import uuid

import aiomqtt

from ..config.schema import MQTTConfig
from ..logging import get_logger


logger = get_logger("mqtt.client")


class MQTTClient:
    """
    Async MQTT client wrapper with reconnection support.
    
    Uses aiomqtt for async MQTT communication with automatic
    reconnection on connection loss.
    """
    
    def __init__(
        self,
        config: MQTTConfig,
        availability_topic: str | None = None,
    ):
        """
        Initialize MQTT client.
        
        Args:
            config: MQTT configuration
            availability_topic: Topic for availability messages (LWT)
        """
        self.config = config
        self.availability_topic = availability_topic or f"{config.topic_prefix}/status"
        
        # Connection state
        self._client: aiomqtt.Client | None = None
        self._connected = False
        self._reconnect_interval = 5.0
        self._max_reconnect_interval = 60.0
        
        # Client ID
        self._client_id = config.client_id or f"penguin_metrics_{uuid.uuid4().hex[:8]}"
        
        # Message queue for offline buffering
        self._message_queue: asyncio.Queue[tuple[str, str, int, bool]] = asyncio.Queue(maxsize=1000)
        
        # Background tasks
        self._publisher_task: asyncio.Task | None = None
        self._running = False
    
    @property
    def connected(self) -> bool:
        """Check if client is connected."""
        return self._connected
    
    @property
    def topic_prefix(self) -> str:
        """Get configured topic prefix."""
        return self.config.topic_prefix
    
    def _create_client(self) -> aiomqtt.Client:
        """Create a new aiomqtt client instance."""
        # Build will message for availability (LWT)
        will = aiomqtt.Will(
            topic=self.availability_topic,
            payload="offline",
            qos=1,
            retain=self.config.should_retain_status(),
        )
        
        return aiomqtt.Client(
            hostname=self.config.host,
            port=self.config.port,
            username=self.config.username,
            password=self.config.password,
            identifier=self._client_id,
            keepalive=self.config.keepalive,
            will=will,
        )
    
    async def connect(self) -> None:
        """
        Connect to MQTT broker.
        
        Raises:
            aiomqtt.MqttError: If connection fails
        """
        logger.debug(f"Connecting to MQTT broker {self.config.host}:{self.config.port}")
        logger.debug(f"Client ID: {self._client_id}")
        
        self._client = self._create_client()
        await self._client.__aenter__()
        self._connected = True
        
        # Publish online status
        await self._publish_raw(
            self.availability_topic,
            "online",
            qos=1,
            retain=self.config.should_retain_status(),
        )
        
        logger.info(f"Connected to MQTT broker at {self.config.host}:{self.config.port}")
        logger.debug(f"Availability topic: {self.availability_topic}")
    
    async def disconnect(self) -> None:
        """Disconnect from MQTT broker."""
        if self._client and self._connected:
            try:
                # Publish offline status before disconnecting
                await self._publish_raw(
                    self.availability_topic,
                    "offline",
                    qos=1,
                    retain=self.config.should_retain_status(),
                )
            except Exception:
                pass
            
            try:
                await self._client.__aexit__(None, None, None)
            except Exception:
                pass
            
            self._connected = False
            self._client = None
            logger.info("Disconnected from MQTT broker")
    
    async def _publish_raw(
        self,
        topic: str,
        payload: str,
        qos: int = 1,
        retain: bool = False,
    ) -> None:
        """Publish a message directly (internal use)."""
        if self._client and self._connected:
            logger.debug(f"Publishing to {topic}: {payload[:100]}{'...' if len(payload) > 100 else ''}")
            await self._client.publish(topic, payload, qos=qos, retain=retain)
    
    async def publish(
        self,
        topic: str,
        payload: Any,
        qos: int | None = None,
        retain: bool | None = None,
        is_status: bool = False,
    ) -> None:
        """
        Publish a message to a topic.
        
        Args:
            topic: MQTT topic
            payload: Message payload (will be JSON encoded if not string)
            qos: QoS level (default from config)
            retain: Retain flag (None = use config mode)
            is_status: If True, this is a status/availability message
        """
        if qos is None:
            qos = self.config.qos
        
        # Determine retain based on mode if not explicitly set
        if retain is None:
            if is_status:
                retain = self.config.should_retain_status()
            else:
                retain = self.config.should_retain_data()
        
        # Convert payload to string
        if isinstance(payload, str):
            payload_str = payload
        elif isinstance(payload, (int, float)):
            payload_str = str(payload)
        elif isinstance(payload, bool):
            payload_str = "true" if payload else "false"
        else:
            payload_str = json.dumps(payload)
        
        # Add to queue
        try:
            self._message_queue.put_nowait((topic, payload_str, qos, retain))
        except asyncio.QueueFull:
            logger.warning("Message queue full, dropping message")
    
    async def publish_data(
        self,
        topic: str,
        payload: Any,
        qos: int | None = None,
    ) -> None:
        """
        Publish data (respects retain mode for data).
        
        Args:
            topic: MQTT topic
            payload: Message payload
            qos: QoS level
        """
        await self.publish(topic, payload, qos, is_status=False)
    
    async def publish_status(
        self,
        topic: str,
        payload: str,
        qos: int | None = None,
    ) -> None:
        """
        Publish status/availability (respects retain mode for status).
        
        Args:
            topic: MQTT topic  
            payload: Status payload (online/offline)
            qos: QoS level
        """
        await self.publish(topic, payload, qos, is_status=True)
    
    async def publish_json(
        self,
        topic: str,
        data: dict[str, Any],
        qos: int | None = None,
        retain: bool | None = None,
    ) -> None:
        """
        Publish a JSON message to a topic.
        
        Args:
            topic: MQTT topic
            data: Dictionary to encode as JSON
            qos: QoS level
            retain: Retain flag
        """
        await self.publish(topic, data, qos, retain)
    
    async def _publisher_loop(self) -> None:
        """Background task to publish queued messages."""
        reconnect_interval = self._reconnect_interval
        
        while self._running:
            try:
                if not self._connected:
                    try:
                        await self.connect()
                        reconnect_interval = self._reconnect_interval
                    except Exception as e:
                        logger.error(f"Failed to connect to MQTT: {e}")
                        await asyncio.sleep(reconnect_interval)
                        reconnect_interval = min(
                            reconnect_interval * 2,
                            self._max_reconnect_interval,
                        )
                        continue
                
                # Process messages from queue
                try:
                    topic, payload, qos, retain = await asyncio.wait_for(
                        self._message_queue.get(),
                        timeout=1.0,
                    )
                    await self._publish_raw(topic, payload, qos, retain)
                except asyncio.TimeoutError:
                    continue
                except aiomqtt.MqttError as e:
                    logger.error(f"MQTT error: {e}")
                    self._connected = False
                    # Re-queue the message
                    try:
                        self._message_queue.put_nowait((topic, payload, qos, retain))
                    except asyncio.QueueFull:
                        pass
            
            except Exception as e:
                logger.error(f"Publisher loop error: {e}")
                self._connected = False
                await asyncio.sleep(1.0)
    
    async def start(self) -> None:
        """Start the MQTT client background tasks."""
        self._running = True
        self._publisher_task = asyncio.create_task(self._publisher_loop())
        logger.info("MQTT client started")
    
    async def stop(self) -> None:
        """Stop the MQTT client."""
        self._running = False
        
        if self._publisher_task:
            self._publisher_task.cancel()
            try:
                await self._publisher_task
            except asyncio.CancelledError:
                pass
        
        await self.disconnect()
        logger.info("MQTT client stopped")
    
    @asynccontextmanager
    async def session(self) -> AsyncIterator["MQTTClient"]:
        """Context manager for MQTT session."""
        await self.start()
        try:
            yield self
        finally:
            await self.stop()
    
    async def wait_connected(self, timeout: float = 30.0) -> bool:
        """
        Wait for connection to be established.
        
        Args:
            timeout: Maximum time to wait in seconds
        
        Returns:
            True if connected, False if timeout
        """
        start = asyncio.get_event_loop().time()
        while not self._connected:
            if asyncio.get_event_loop().time() - start > timeout:
                return False
            await asyncio.sleep(0.1)
        return True

