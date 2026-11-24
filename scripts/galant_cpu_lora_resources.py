"""Non-invasive CPU LoRA capacity checks (no model imports, no data reads)."""
from __future__ import annotations

from pathlib import Path
import os
import shutil

MIB = 1024 ** 2
GIB = 1024 ** 3
MIN_FREE_HOST_MB = 6000
MIN_FREE_CGROUP_MB = 4300
MIN_FREE_DISK_MB = 7000
PAUSE_HOST_MB = 1800
PAUSE_CGROUP_RATIO = 0.87


def _read_int(path):
    try:
        raw = Path(path).read_text(encoding="ascii").strip()
        return None if raw == "max" else int(raw)
    except (FileNotFoundError, PermissionError, ValueError, OSError):
        return None


def host_mem_available_mb() -> int:
    try:
        for row in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            if row.startswith("MemAvailable:"):
                return int(row.split()[1]) // 1024
    except (FileNotFoundError, PermissionError, ValueError, OSError):
        pass
    return 0


def process_memory_mb() -> float | None:
    try:
        for row in Path("/proc/self/status").read_text(encoding="ascii").splitlines():
            if row.startswith("VmRSS:"):
                return round(int(row.split()[1]) / 1024, 1)
    except (FileNotFoundError, PermissionError, ValueError, OSError):
        pass
    return None


def inactive_file_bytes(path="/sys/fs/cgroup/memory.stat") -> int:
    """Only count inactive file pages reported by cgroup v2; never anonymous RAM."""
    try:
        for line in Path(path).read_text(encoding="ascii").splitlines():
            name, value = line.split()
            if name == "inactive_file":
                return max(0, int(value))
    except (OSError, ValueError):
        pass
    return 0


def snapshot(storage: str | Path) -> dict:
    """Report measured capacity only. Unknown values are never filled with estimates."""
    limit = _read_int("/sys/fs/cgroup/memory.max")
    current = _read_int("/sys/fs/cgroup/memory.current")
    try:
        disk = shutil.disk_usage(storage)
        free_disk_mb = disk.free // MIB
    except (OSError, FileNotFoundError):
        free_disk_mb = None
    cpus = os.cpu_count()
    reclaimable_mb = available_mb = working_set_mb = None
    if limit is not None and current is not None:
        cgroup_free_mb = max(0, limit - current) // MIB
        cgroup_limit_mb = limit // MIB
        # File-cache charges persist after a trainer exits. The kernel can
        # reclaim inactive file pages under pressure. Do not count these as
        # resident anonymous model memory; keep the hard cgroup limit intact.
        reclaimable = min(current, inactive_file_bytes())
        working_set = max(0, current - reclaimable)
        reclaimable_mb = reclaimable // MIB
        working_set_mb = working_set // MIB
        available_mb = max(0, limit - working_set) // MIB
    else:
        cgroup_free_mb = cgroup_limit_mb = None
    return {
        "host_free_mb": host_mem_available_mb(),
        "cgroup_limit_mb": cgroup_limit_mb,
        "cgroup_free_mb": cgroup_free_mb,
        "cgroup_used_mb": current // MIB if current is not None else None,
        "cgroup_reclaimable_mb": reclaimable_mb,
        "cgroup_available_mb": available_mb,
        "cgroup_working_set_mb": working_set_mb,
        "disk_free_mb": free_disk_mb,
        "logical_cpu_count": cpus,
        "process_rss_mb": process_memory_mb(),
    }


def capacity_gate(measured: dict, *, require_cgroup: bool = True) -> dict:
    """Use conservative limits to reserve RAM for live GALANT services."""
    blockers = []
    host = measured.get("host_free_mb")
    if not isinstance(host, (int, float)) or host < MIN_FREE_HOST_MB:
        blockers.append("host_ram_reserve")
    limit = measured.get("cgroup_limit_mb")
    free = measured.get("cgroup_available_mb")
    if free is None:
        free = measured.get("cgroup_free_mb")
    if require_cgroup:
        if not isinstance(limit, (int, float)) or limit < 4800:
            blockers.append("dedicated_cgroup_limit_missing")
        if not isinstance(free, (int, float)) or free < MIN_FREE_CGROUP_MB:
            blockers.append("cgroup_memory_headroom")
    disk = measured.get("disk_free_mb")
    if not isinstance(disk, (int, float)) or disk < MIN_FREE_DISK_MB:
        blockers.append("disk_space")
    return {"ready": not blockers, "blockers": blockers,
            "snapshot": measured,
            "caution": "Preflight only: a memory-safe start does not guarantee the model will fit."}


def should_pause(measured: dict) -> bool:
    """Pause on detected RAM pressure, without touching Messenger/production."""
    host = measured.get("host_free_mb")
    limit = measured.get("cgroup_limit_mb")
    used = measured.get("cgroup_working_set_mb")
    if used is None:
        used = measured.get("cgroup_used_mb")
    if host is None or host < PAUSE_HOST_MB:
        return True
    if limit and used is not None and used / limit > PAUSE_CGROUP_RATIO:
        return True
    return False
