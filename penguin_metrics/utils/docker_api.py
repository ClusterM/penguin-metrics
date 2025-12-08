"""
Docker API client via Unix socket.

Provides async access to Docker API without requiring the docker-py package.
Uses standard library only (asyncio streams).
"""

import asyncio
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator
from urllib.parse import quote


DOCKER_SOCKET = "/var/run/docker.sock"


class DockerError(Exception):
    """Exception for Docker API errors."""
    
    def __init__(self, status: int, message: str):
        self.status = status
        super().__init__(f"Docker API error {status}: {message}")


@dataclass
class ContainerInfo:
    """Docker container information."""
    
    id: str
    name: str
    image: str
    state: str  # running, exited, paused, etc.
    status: str  # Human-readable status
    created: int = 0
    started_at: str = ""
    health: str | None = None  # healthy, unhealthy, starting, none
    labels: dict[str, str] = field(default_factory=dict)
    
    @property
    def short_id(self) -> str:
        """Get short container ID (12 chars)."""
        return self.id[:12]
    
    @property
    def is_running(self) -> bool:
        """Check if container is running."""
        return self.state == "running"


@dataclass
class ContainerStats:
    """Docker container statistics."""
    
    # CPU stats
    cpu_percent: float = 0.0
    cpu_system: int = 0
    cpu_total: int = 0
    
    # Memory stats (in bytes)
    memory_usage: int = 0
    memory_limit: int = 0
    memory_percent: float = 0.0
    memory_cache: int = 0
    
    # Network stats (in bytes)
    network_rx_bytes: int = 0
    network_tx_bytes: int = 0
    
    # Block I/O stats (in bytes)
    block_read: int = 0
    block_write: int = 0
    
    # PIDs
    pids: int = 0
    
    @property
    def memory_usage_mb(self) -> float:
        """Memory usage in MB."""
        return self.memory_usage / (1024 * 1024)
    
    @property
    def memory_limit_mb(self) -> float:
        """Memory limit in MB."""
        return self.memory_limit / (1024 * 1024)


class DockerClient:
    """
    Async Docker API client using Unix socket.
    
    Provides methods for listing containers and getting stats.
    """
    
    def __init__(self, socket_path: str = DOCKER_SOCKET):
        """
        Initialize Docker client.
        
        Args:
            socket_path: Path to Docker Unix socket
        """
        self.socket_path = socket_path
    
    @property
    def available(self) -> bool:
        """Check if Docker socket is available."""
        return Path(self.socket_path).exists()
    
    async def _request(
        self,
        method: str,
        path: str,
        query: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        """
        Send HTTP request to Docker API.
        
        Args:
            method: HTTP method
            path: API path
            query: Query parameters
        
        Returns:
            Tuple of (status, headers, body)
        """
        # Build URL with query string
        if query:
            query_str = "&".join(f"{k}={quote(str(v))}" for k, v in query.items())
            path = f"{path}?{query_str}"
        
        # Build request
        request = f"{method} {path} HTTP/1.1\r\n"
        request += "Host: localhost\r\n"
        request += "Connection: close\r\n"
        request += "\r\n"
        
        # Connect to Unix socket
        reader, writer = await asyncio.open_unix_connection(self.socket_path)
        
        try:
            # Send request
            writer.write(request.encode())
            await writer.drain()
            
            # Read response
            response = await reader.read()
            
            # Parse response
            parts = response.split(b"\r\n\r\n", 1)
            header_section = parts[0].decode()
            body = parts[1] if len(parts) > 1 else b""
            
            # Parse status line
            header_lines = header_section.split("\r\n")
            status_match = re.match(r"HTTP/\d\.\d (\d+)", header_lines[0])
            status = int(status_match.group(1)) if status_match else 0
            
            # Parse headers
            headers = {}
            for line in header_lines[1:]:
                if ": " in line:
                    key, value = line.split(": ", 1)
                    headers[key.lower()] = value
            
            # Handle chunked encoding
            if headers.get("transfer-encoding") == "chunked":
                body = self._decode_chunked(body)
            
            return status, headers, body
        
        finally:
            writer.close()
            await writer.wait_closed()
    
    def _decode_chunked(self, data: bytes) -> bytes:
        """Decode chunked transfer encoding."""
        result = []
        pos = 0
        
        while pos < len(data):
            # Find chunk size line
            line_end = data.find(b"\r\n", pos)
            if line_end == -1:
                break
            
            # Parse chunk size
            size_str = data[pos:line_end].decode()
            try:
                chunk_size = int(size_str, 16)
            except ValueError:
                break
            
            if chunk_size == 0:
                break
            
            # Read chunk data
            chunk_start = line_end + 2
            chunk_end = chunk_start + chunk_size
            result.append(data[chunk_start:chunk_end])
            
            # Move past chunk and trailing CRLF
            pos = chunk_end + 2
        
        return b"".join(result)
    
    async def _get_json(self, path: str, query: dict[str, str] | None = None) -> Any:
        """
        GET request returning JSON.
        
        Args:
            path: API path
            query: Query parameters
        
        Returns:
            Parsed JSON response
        """
        status, headers, body = await self._request("GET", path, query)
        
        if status >= 400:
            try:
                error = json.loads(body)
                message = error.get("message", body.decode())
            except Exception:
                message = body.decode()
            raise DockerError(status, message)
        
        if not body:
            return None
        
        return json.loads(body)
    
    async def list_containers(
        self,
        all: bool = False,
        filters: dict[str, list[str]] | None = None,
    ) -> list[ContainerInfo]:
        """
        List Docker containers.
        
        Args:
            all: Include stopped containers
            filters: Filter containers (name, label, etc.)
        
        Returns:
            List of ContainerInfo
        """
        query: dict[str, str] = {}
        if all:
            query["all"] = "true"
        if filters:
            query["filters"] = json.dumps(filters)
        
        data = await self._get_json("/containers/json", query)
        
        containers = []
        for item in data:
            name = item.get("Names", ["/unknown"])[0].lstrip("/")
            
            # Get health status
            health = None
            state = item.get("State", "unknown")
            status_str = item.get("Status", "")
            
            if "Health" in status_str:
                if "healthy" in status_str.lower():
                    health = "healthy"
                elif "unhealthy" in status_str.lower():
                    health = "unhealthy"
                elif "starting" in status_str.lower():
                    health = "starting"
            
            containers.append(ContainerInfo(
                id=item.get("Id", ""),
                name=name,
                image=item.get("Image", ""),
                state=state,
                status=status_str,
                created=item.get("Created", 0),
                labels=item.get("Labels", {}),
                health=health,
            ))
        
        return containers
    
    async def get_container(self, container_id: str) -> ContainerInfo | None:
        """
        Get container info by ID or name.
        
        Args:
            container_id: Container ID or name
        
        Returns:
            ContainerInfo or None if not found
        """
        try:
            data = await self._get_json(f"/containers/{container_id}/json")
        except DockerError as e:
            if e.status == 404:
                return None
            raise
        
        state = data.get("State", {})
        config = data.get("Config", {})
        
        # Get health status
        health = None
        if "Health" in state:
            health = state["Health"].get("Status")
        
        name = data.get("Name", "/unknown").lstrip("/")
        
        return ContainerInfo(
            id=data.get("Id", ""),
            name=name,
            image=config.get("Image", ""),
            state=state.get("Status", "unknown"),
            status=state.get("Status", ""),
            created=0,
            started_at=state.get("StartedAt", ""),
            health=health,
            labels=config.get("Labels", {}),
        )
    
    async def get_stats(self, container_id: str, stream: bool = False) -> ContainerStats:
        """
        Get container statistics.
        
        Args:
            container_id: Container ID or name
            stream: If False, get one-shot stats
        
        Returns:
            ContainerStats
        """
        query = {"stream": "false"} if not stream else {}
        
        data = await self._get_json(f"/containers/{container_id}/stats", query)
        
        stats = ContainerStats()
        
        # CPU stats
        cpu_stats = data.get("cpu_stats", {})
        precpu_stats = data.get("precpu_stats", {})
        
        cpu_delta = cpu_stats.get("cpu_usage", {}).get("total_usage", 0) - \
                    precpu_stats.get("cpu_usage", {}).get("total_usage", 0)
        system_delta = cpu_stats.get("system_cpu_usage", 0) - \
                       precpu_stats.get("system_cpu_usage", 0)
        
        if system_delta > 0:
            num_cpus = len(cpu_stats.get("cpu_usage", {}).get("percpu_usage", [])) or 1
            stats.cpu_percent = (cpu_delta / system_delta) * num_cpus * 100.0
        
        stats.cpu_total = cpu_stats.get("cpu_usage", {}).get("total_usage", 0)
        stats.cpu_system = cpu_stats.get("system_cpu_usage", 0)
        
        # Memory stats
        mem_stats = data.get("memory_stats", {})
        stats.memory_usage = mem_stats.get("usage", 0)
        stats.memory_limit = mem_stats.get("limit", 0)
        stats.memory_cache = mem_stats.get("stats", {}).get("cache", 0)
        
        if stats.memory_limit > 0:
            stats.memory_percent = (stats.memory_usage / stats.memory_limit) * 100.0
        
        # Network stats
        networks = data.get("networks", {})
        for iface, net_stats in networks.items():
            stats.network_rx_bytes += net_stats.get("rx_bytes", 0)
            stats.network_tx_bytes += net_stats.get("tx_bytes", 0)
        
        # Block I/O
        blkio = data.get("blkio_stats", {})
        for entry in blkio.get("io_service_bytes_recursive", []) or []:
            if entry.get("op") == "read":
                stats.block_read += entry.get("value", 0)
            elif entry.get("op") == "write":
                stats.block_write += entry.get("value", 0)
        
        # PIDs
        stats.pids = data.get("pids_stats", {}).get("current", 0)
        
        return stats
    
    async def ping(self) -> bool:
        """
        Check if Docker daemon is responsive.
        
        Returns:
            True if daemon is responding
        """
        try:
            status, _, _ = await self._request("GET", "/_ping")
            return status == 200
        except Exception:
            return False

