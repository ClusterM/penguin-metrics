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

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
import re


@dataclass
class SmapsInfo:
    """Memory information from /proc/PID/smaps."""
    
    # Core metrics (in bytes)
    pss: int = 0            # Proportional Set Size
    uss: int = 0            # Unique Set Size (Private_Clean + Private_Dirty)
    rss: int = 0            # Resident Set Size
    swap: int = 0           # Swapped memory
    swap_pss: int = 0       # Proportional swap
    
    # Detailed breakdown
    shared_clean: int = 0
    shared_dirty: int = 0
    private_clean: int = 0
    private_dirty: int = 0
    referenced: int = 0
    anonymous: int = 0
    
    # Size metrics
    size: int = 0           # Virtual memory size
    
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
# Matches: "Pss: 123 kB" or "Pss_Dirty: 45 kB" or "Shared_Clean: 100 kB"
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
        # smaps_rollup may have fields like "Pss_Dirty" which become "pss_dirty"
        if field == "pss" or field.startswith("pss_"):
            # In rollup, "Pss" is the main value, "Pss_Dirty", "Pss_Anon" etc are details
            # We only care about total PSS
            if field == "pss":
                info.pss += value_bytes
        elif field == "rss":
            info.rss += value_bytes
        elif field == "size":
            info.size += value_bytes
        elif field == "swap":
            info.swap += value_bytes
        elif field == "swappss" or field == "swap_pss":
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
        use_rollup: Use smaps_rollup (faster but may be less accurate for PSS)
                   Default False - use full smaps for accuracy
    
    Returns:
        SmapsInfo with memory metrics, or None if unavailable
    
    Note:
        smaps_rollup can give inaccurate PSS values in some cases.
        Full smaps is more accurate but slower for processes with many VMAs.
    """
    if use_rollup:
        return parse_smaps_rollup(pid)
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

