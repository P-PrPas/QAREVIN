"""Read-only host preflight; never changes other workloads or host limits."""
from pathlib import Path


def preflight(job_memory_mib: int, reserve_mib: int = 1024) -> dict:
    if job_memory_mib <= 0 or reserve_mib < 256:
        raise ValueError("invalid resource budget")
    values = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, amount = line.split(":", 1)
        values[key] = int(amount.strip().split()[0]) // 1024
    available = values["MemAvailable"]
    return {
        "available_mib": available,
        "required_mib": job_memory_mib + reserve_mib,
        "ready": available >= job_memory_mib + reserve_mib,
    }
