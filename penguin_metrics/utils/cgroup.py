"""
Utilities for reading cgroup metrics.

Supports both cgroup v1 and v2 hierarchies.

cgroup v2 paths:
- /sys/fs/cgroup/{path}/cpu.stat
- /sys/fs/cgroup/{path}/memory.current
- /sys/fs/cgroup/{path}/memory.stat

cgroup v1 paths:
- /sys/fs/cgroup/cpu/{path}/cpuacct.usage
- /sys/fs/cgroup/memory/{path}/memory.usage_in_bytes
"""

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

# Cgroup mount points
CGROUP_V2_ROOT = Path("/sys/fs/cgroup")
CGROUP_V1_CPU = Path("/sys/fs/cgroup/cpu")
CGROUP_V1_MEMORY = Path("/sys/fs/cgroup/memory")


@dataclass
class CgroupStats:
    """Statistics from a cgroup."""

    # CPU stats
    cpu_usage_usec: int = 0  # Total CPU time in microseconds
    cpu_user_usec: int = 0  # User CPU time
    cpu_system_usec: int = 0  # System CPU time

    # Memory stats (in bytes)
    memory_current: int = 0  # Current memory usage
    memory_max: int = 0  # Memory limit (0 = unlimited)
    memory_swap: int = 0  # Swap usage
    memory_cache: int = 0  # Page cache
    memory_rss: int = 0  # RSS (anon + file mapped)

    # I/O stats (in bytes, summed across all devices)
    io_read_bytes: int = 0  # Total bytes read
    io_write_bytes: int = 0  # Total bytes written

    # Process count
    pids_current: int = 0

    @property
    def memory_mb(self) -> float:
        """Memory usage in MB."""
        return self.memory_current / (1024 * 1024)

    @property
    def cpu_usage_sec(self) -> float:
        """CPU usage in seconds."""
        return self.cpu_usage_usec / 1_000_000


def _read_file(path: Path, default: str = "") -> str:
    """Read a file, returning default on error."""
    try:
        return path.read_text().strip()
    except Exception:
        return default


def _read_int(path: Path, default: int = 0) -> int:
    """Read an integer from a file."""
    content = _read_file(path)
    if not content:
        return default
    try:
        return int(content)
    except ValueError:
        return default


def _parse_key_value(content: str) -> dict[str, int]:
    """Parse key-value pairs from cgroup stat files."""
    result = {}
    for line in content.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            try:
                result[parts[0]] = int(parts[1])
            except ValueError:
                pass
    return result


def detect_cgroup_version() -> int:
    """
    Detect cgroup version in use.

    Returns:
        2 for cgroup v2, 1 for cgroup v1, 0 if unknown
    """
    # Check for unified cgroup v2
    if (CGROUP_V2_ROOT / "cgroup.controllers").exists():
        return 2

    # Check for cgroup v1
    if CGROUP_V1_CPU.exists() or CGROUP_V1_MEMORY.exists():
        return 1

    return 0


def get_process_cgroup(pid: int) -> str | None:
    """
    Get cgroup path for a process.

    Args:
        pid: Process ID

    Returns:
        Cgroup path (relative), or None if not found
    """
    cgroup_file = Path(f"/proc/{pid}/cgroup")

    try:
        content = cgroup_file.read_text()
    except Exception:
        return None

    cgroup_version = detect_cgroup_version()

    if cgroup_version == 2:
        # cgroup v2: single unified hierarchy
        # Format: 0::/path
        for line in content.splitlines():
            if line.startswith("0::"):
                return line[3:]
        return None

    elif cgroup_version == 1:
        # cgroup v1: multiple hierarchies
        # Look for cpu or memory controller
        for line in content.splitlines():
            parts = line.split(":")
            if len(parts) >= 3:
                controllers = parts[1]
                path = parts[2]
                if "cpu" in controllers or "memory" in controllers:
                    return path
        return None

    return None


def get_cgroup_stats_v2(cgroup_path: str) -> CgroupStats:
    """
    Get cgroup statistics from cgroup v2.

    Args:
        cgroup_path: Relative cgroup path

    Returns:
        CgroupStats with metrics
    """
    stats = CgroupStats()

    # Remove leading slash if present
    if cgroup_path.startswith("/"):
        cgroup_path = cgroup_path[1:]

    cg_dir = CGROUP_V2_ROOT / cgroup_path

    if not cg_dir.exists():
        return stats

    # CPU stats
    cpu_stat = _read_file(cg_dir / "cpu.stat")
    if cpu_stat:
        cpu_data = _parse_key_value(cpu_stat)
        stats.cpu_usage_usec = cpu_data.get("usage_usec", 0)
        stats.cpu_user_usec = cpu_data.get("user_usec", 0)
        stats.cpu_system_usec = cpu_data.get("system_usec", 0)

    # Memory current
    stats.memory_current = _read_int(cg_dir / "memory.current")

    # Memory max
    max_content = _read_file(cg_dir / "memory.max")
    if max_content and max_content != "max":
        try:
            stats.memory_max = int(max_content)
        except ValueError:
            pass

    # Memory stat
    mem_stat = _read_file(cg_dir / "memory.stat")
    if mem_stat:
        mem_data = _parse_key_value(mem_stat)
        stats.memory_cache = mem_data.get("file", 0)
        stats.memory_rss = mem_data.get("anon", 0) + mem_data.get("file_mapped", 0)

    # Swap
    stats.memory_swap = _read_int(cg_dir / "memory.swap.current")

    # PIDs
    stats.pids_current = _read_int(cg_dir / "pids.current")

    # I/O stats (sum across all devices)
    io_stat = _read_file(cg_dir / "io.stat")
    if io_stat:
        for line in io_stat.splitlines():
            # Format: "253:0 rbytes=1234 wbytes=5678 rios=... wios=... dbytes=... dios=..."
            for part in line.split():
                if part.startswith("rbytes="):
                    try:
                        stats.io_read_bytes += int(part[7:])
                    except ValueError:
                        pass
                elif part.startswith("wbytes="):
                    try:
                        stats.io_write_bytes += int(part[7:])
                    except ValueError:
                        pass

    return stats


def get_cgroup_stats_v1(cgroup_path: str) -> CgroupStats:
    """
    Get cgroup statistics from cgroup v1.

    Args:
        cgroup_path: Relative cgroup path

    Returns:
        CgroupStats with metrics
    """
    stats = CgroupStats()

    # Remove leading slash if present
    if cgroup_path.startswith("/"):
        cgroup_path = cgroup_path[1:]

    # CPU stats
    cpu_dir = CGROUP_V1_CPU / cgroup_path
    if cpu_dir.exists():
        # cpuacct.usage is in nanoseconds
        usage_ns = _read_int(cpu_dir / "cpuacct.usage")
        stats.cpu_usage_usec = usage_ns // 1000

        # User/system breakdown
        stat_content = _read_file(cpu_dir / "cpuacct.stat")
        if stat_content:
            for line in stat_content.splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    # Values are in USER_HZ (usually 100)
                    ticks = int(parts[1])
                    usec = ticks * 10000  # Convert to microseconds
                    if parts[0] == "user":
                        stats.cpu_user_usec = usec
                    elif parts[0] == "system":
                        stats.cpu_system_usec = usec

    # Memory stats
    mem_dir = CGROUP_V1_MEMORY / cgroup_path
    if mem_dir.exists():
        stats.memory_current = _read_int(mem_dir / "memory.usage_in_bytes")
        stats.memory_max = _read_int(mem_dir / "memory.limit_in_bytes")
        stats.memory_swap = (
            _read_int(mem_dir / "memory.memsw.usage_in_bytes") - stats.memory_current
        )

        # Memory stat
        mem_stat = _read_file(mem_dir / "memory.stat")
        if mem_stat:
            mem_data = _parse_key_value(mem_stat)
            stats.memory_cache = mem_data.get("cache", 0)
            stats.memory_rss = mem_data.get("rss", 0)

    return stats


def get_cgroup_stats(cgroup_path: str) -> CgroupStats:
    """
    Get cgroup statistics (auto-detects cgroup version).

    Args:
        cgroup_path: Relative cgroup path

    Returns:
        CgroupStats with metrics
    """
    version = detect_cgroup_version()

    if version == 2:
        return get_cgroup_stats_v2(cgroup_path)
    elif version == 1:
        return get_cgroup_stats_v1(cgroup_path)
    else:
        return CgroupStats()


def get_systemd_service_cgroup(unit_name: str) -> str | None:
    """
    Get cgroup path for a systemd service.

    Args:
        unit_name: Systemd unit name (e.g., "docker.service")

    Returns:
        Cgroup path, or None if not found
    """
    # Systemd uses predictable cgroup paths:
    # /sys/fs/cgroup/system.slice/{unit_name}

    if not unit_name.endswith(".service"):
        unit_name = f"{unit_name}.service"

    # cgroup v2
    v2_path = f"system.slice/{unit_name}"
    if (CGROUP_V2_ROOT / v2_path).exists():
        return v2_path

    # cgroup v1
    v1_path = f"system.slice/{unit_name}"
    if (CGROUP_V1_CPU / v1_path).exists() or (CGROUP_V1_MEMORY / v1_path).exists():
        return v1_path

    return None


def get_cgroup_pids(cgroup_path: str) -> list[int]:
    """
    Get list of PIDs in a cgroup.

    Args:
        cgroup_path: Relative cgroup path

    Returns:
        List of process IDs
    """
    version = detect_cgroup_version()

    if cgroup_path.startswith("/"):
        cgroup_path = cgroup_path[1:]

    pids = []

    if version == 2:
        procs_file = CGROUP_V2_ROOT / cgroup_path / "cgroup.procs"
    else:
        procs_file = CGROUP_V1_CPU / cgroup_path / "cgroup.procs"
        if not procs_file.exists():
            procs_file = CGROUP_V1_MEMORY / cgroup_path / "cgroup.procs"

    try:
        content = procs_file.read_text()
        for line in content.splitlines():
            try:
                pids.append(int(line.strip()))
            except ValueError:
                pass
    except Exception:
        pass

    return pids


def iter_cgroup_children(cgroup_path: str) -> Iterator[str]:
    """
    Iterate over child cgroups.

    Args:
        cgroup_path: Parent cgroup path

    Yields:
        Child cgroup paths
    """
    version = detect_cgroup_version()

    if cgroup_path.startswith("/"):
        cgroup_path = cgroup_path[1:]

    if version == 2:
        parent = CGROUP_V2_ROOT / cgroup_path
    else:
        parent = CGROUP_V1_CPU / cgroup_path

    if not parent.exists():
        return

    for child in parent.iterdir():
        if child.is_dir() and not child.name.startswith("."):
            yield f"{cgroup_path}/{child.name}"
