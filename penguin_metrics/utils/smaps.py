"""
Parser for /proc/PID/smaps to get accurate memory metrics.

Provides:
- PSS (Proportional Set Size): Memory fairly attributed to process
- USS (Unique Set Size): Private memory only used by this process
- Swap: Memory swapped out
- Shared: Shared memory
- Referenced: Recently accessed memory

Note: Reading smaps of other processes requires root or CAP_SYS_PTRACE.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SmapsInfo:
    """Memory information from /proc/PID/smaps."""

    # Core metrics (in bytes)
    pss: int = 0  # Proportional Set Size
    uss: int = 0  # Unique Set Size (Private_Clean + Private_Dirty)
    rss: int = 0  # Resident Set Size
    swap: int = 0  # Swapped memory
    swap_pss: int = 0  # Proportional swap

    # Detailed breakdown
    shared_clean: int = 0
    shared_dirty: int = 0
    private_clean: int = 0
    private_dirty: int = 0
    referenced: int = 0
    anonymous: int = 0

    # PSS breakdown (from smaps_rollup)
    pss_anon: int = 0  # PSS for anonymous memory
    pss_file: int = 0  # PSS for file-backed mappings
    pss_shmem: int = 0  # PSS for shared memory

    # Size metrics
    size: int = 0  # Virtual memory size

    @property
    def shared(self) -> int:
        """Total shared memory."""
        return self.shared_clean + self.shared_dirty

    @property
    def private(self) -> int:
        """Total private memory (same as USS)."""
        return self.private_clean + self.private_dirty

    @property
    def pss_mb(self) -> float:
        """PSS in megabytes."""
        return self.pss / (1024 * 1024)

    @property
    def uss_mb(self) -> float:
        """USS in megabytes."""
        return self.uss / (1024 * 1024)

    @property
    def rss_mb(self) -> float:
        """RSS in megabytes."""
        return self.rss / (1024 * 1024)

    @property
    def swap_mb(self) -> float:
        """Swap in megabytes."""
        return self.swap / (1024 * 1024)

    @property
    def memory_real_mb(self) -> float:
        """
        Real memory usage excluding file-backed mappings.

        Formula: (Anonymous + SwapPss) / 1024
        This excludes mmap'd files that can be evicted from RAM.
        """
        return (self.anonymous + self.swap_pss) / (1024 * 1024)

    @property
    def memory_real_pss_mb(self) -> float:
        """
        Real PSS memory usage excluding file-backed mappings.

        Formula: (Pss_Anon + Pss_Shm + SwapPss) / 1024
        This excludes mmap'd files (Pss_File) that can be evicted from RAM.

        Falls back to regular PSS if breakdown not available (from full smaps).
        """
        if self.pss_anon > 0 or self.pss_shmem > 0:
            # We have breakdown from smaps_rollup
            return (self.pss_anon + self.pss_shmem + self.swap_pss) / (1024 * 1024)
        else:
            # Fallback: use regular PSS (from full smaps, which doesn't have breakdown)
            # This is less accurate but better than nothing
            return self.pss_mb

    @property
    def memory_real_uss_mb(self) -> float:
        """
        Real USS memory usage excluding file-backed mappings.

        Formula: Anonymous / 1024
        This excludes mmap'd files that can be evicted from RAM.
        Only counts anonymous memory (heap, stack) that actually uses RAM.
        """
        return self.anonymous / (1024 * 1024)

    def __add__(self, other: "SmapsInfo") -> "SmapsInfo":
        """Add two SmapsInfo objects (for aggregating multiple processes)."""
        return SmapsInfo(
            pss=self.pss + other.pss,
            uss=self.uss + other.uss,
            rss=self.rss + other.rss,
            swap=self.swap + other.swap,
            swap_pss=self.swap_pss + other.swap_pss,
            shared_clean=self.shared_clean + other.shared_clean,
            shared_dirty=self.shared_dirty + other.shared_dirty,
            private_clean=self.private_clean + other.private_clean,
            private_dirty=self.private_dirty + other.private_dirty,
            referenced=self.referenced + other.referenced,
            anonymous=self.anonymous + other.anonymous,
            size=self.size + other.size,
            pss_anon=self.pss_anon + other.pss_anon,
            pss_file=self.pss_file + other.pss_file,
            pss_shmem=self.pss_shmem + other.pss_shmem,
        )

    def to_dict(self) -> dict[str, int | float]:
        """Convert to dictionary with both bytes and MB values."""
        return {
            "pss": self.pss,
            "pss_mb": round(self.pss_mb, 2),
            "uss": self.uss,
            "uss_mb": round(self.uss_mb, 2),
            "rss": self.rss,
            "rss_mb": round(self.rss_mb, 2),
            "swap": self.swap,
            "swap_mb": round(self.swap_mb, 2),
            "shared": self.shared,
            "private": self.private,
            "referenced": self.referenced,
            "anonymous": self.anonymous,
        }


# Regex patterns for parsing smaps
# Matches: "Pss: 123 kB" or "Pss_Dirty: 45 kB" or "SwapPss: 0 kB" or "Shared_Clean: 100 kB"
_SMAPS_FIELD_PATTERN = re.compile(r"^([A-Za-z_]+):\s+(\d+)\s*kB", re.IGNORECASE)


def _parse_smaps_content(content: str) -> SmapsInfo:
    """
    Parse smaps content and return aggregated metrics.

    Args:
        content: Raw content of /proc/PID/smaps

    Returns:
        SmapsInfo with aggregated memory metrics
    """
    info = SmapsInfo()

    for line in content.splitlines():
        match = _SMAPS_FIELD_PATTERN.match(line)
        if not match:
            continue

        field = match.group(1).lower()
        value_kb = int(match.group(2))
        value_bytes = value_kb * 1024

        # Handle both smaps and smaps_rollup formats
        # smaps_rollup has fields like "Pss_Anon", "Pss_File", "Pss_Shmem"
        if field == "pss":
            info.pss += value_bytes
        elif field == "pss_anon":
            info.pss_anon += value_bytes
        elif field == "pss_file":
            info.pss_file += value_bytes
        elif field == "pss_shmem":
            info.pss_shmem += value_bytes
        elif field == "rss":
            info.rss += value_bytes
        elif field == "size":
            info.size += value_bytes
        elif field == "swap":
            info.swap += value_bytes
        elif field == "swappss" or field == "swap_pss" or field == "swappss":
            info.swap_pss += value_bytes
        elif field == "shared_clean":
            info.shared_clean += value_bytes
        elif field == "shared_dirty":
            info.shared_dirty += value_bytes
        elif field == "private_clean":
            info.private_clean += value_bytes
        elif field == "private_dirty":
            info.private_dirty += value_bytes
        elif field == "referenced":
            info.referenced += value_bytes
        elif field == "anonymous":
            info.anonymous += value_bytes

    # USS = Private_Clean + Private_Dirty
    info.uss = info.private_clean + info.private_dirty

    return info


def parse_smaps(pid: int) -> SmapsInfo | None:
    """
    Parse /proc/PID/smaps for a process.

    Args:
        pid: Process ID

    Returns:
        SmapsInfo with memory metrics, or None if unavailable

    Note:
        Returns None if:
        - Process doesn't exist
        - Permission denied (need root or CAP_SYS_PTRACE)
        - smaps file is unavailable
    """
    smaps_path = Path(f"/proc/{pid}/smaps")

    try:
        content = smaps_path.read_text()
        return _parse_smaps_content(content)
    except FileNotFoundError:
        # Process doesn't exist
        return None
    except PermissionError:
        # Need elevated privileges
        return None
    except Exception:
        # Other errors (process died, etc.)
        return None


def parse_smaps_rollup(pid: int) -> SmapsInfo | None:
    """
    Parse /proc/PID/smaps_rollup for a process (faster, less detailed).

    smaps_rollup is a kernel feature (4.14+) that provides pre-aggregated
    totals, avoiding the need to parse the full smaps file.

    Args:
        pid: Process ID

    Returns:
        SmapsInfo with memory metrics, or None if unavailable
    """
    rollup_path = Path(f"/proc/{pid}/smaps_rollup")

    try:
        content = rollup_path.read_text()
        return _parse_smaps_content(content)
    except FileNotFoundError:
        # Try full smaps as fallback
        return parse_smaps(pid)
    except PermissionError:
        return None
    except Exception:
        return None


def get_process_memory(pid: int, use_rollup: bool = False) -> SmapsInfo | None:
    """
    Get memory information for a process.

    Args:
        pid: Process ID
        use_rollup: Use smaps_rollup for breakdown (Pss_Anon, Pss_Shm, etc.)
                   If False, tries rollup first for breakdown, then falls back to full smaps

    Returns:
        SmapsInfo with memory metrics, or None if unavailable

    Note:
        smaps_rollup provides breakdown (Pss_Anon, Pss_Shm) needed for memory_real_pss.
        If rollup unavailable, falls back to full smaps (less accurate for real PSS).
    """
    if use_rollup:
        return parse_smaps_rollup(pid)

    # Try rollup first for breakdown, fallback to full smaps
    rollup_info = parse_smaps_rollup(pid)
    if rollup_info and (rollup_info.pss_anon > 0 or rollup_info.pss_shmem > 0):
        # We have breakdown from rollup
        return rollup_info

    # Fallback to full smaps (no breakdown, but more accurate total PSS)
    return parse_smaps(pid)


def aggregate_smaps(pids: list[int]) -> SmapsInfo:
    """
    Aggregate smaps info for multiple processes.

    Args:
        pids: List of process IDs

    Returns:
        Combined SmapsInfo for all processes
    """
    total = SmapsInfo()

    for pid in pids:
        info = get_process_memory(pid)
        if info:
            total = total + info

    return total


def iter_all_smaps() -> Iterator[tuple[int, SmapsInfo]]:
    """
    Iterate over smaps for all accessible processes.

    Yields:
        Tuples of (pid, SmapsInfo) for each process

    Note:
        Requires root to see all processes.
    """
    proc = Path("/proc")

    for entry in proc.iterdir():
        if not entry.is_dir():
            continue

        try:
            pid = int(entry.name)
        except ValueError:
            continue

        info = get_process_memory(pid)
        if info:
            yield pid, info
