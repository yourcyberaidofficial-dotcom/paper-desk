"""Decide whether this machine may run a private model.

The refusal floor is a safety stop. It is not a measured runtime size for
Qwen. No candidate is downloaded here.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

CANDIDATES = (
    "qwen3.5:9b-q4_K_M",
    "qwen3.5:4b-q4_K_M",
    "qwen3.5:2b-q4_K_M",
)
# A host below this cannot be asked to load a candidate. The number is a
# gate, not a benchmark of model RSS.
REFUSAL_FLOOR_BYTES = 8 * 1024 ** 3


def _meminfo():
    found = {}
    path = Path("/proc/meminfo")
    if not path.is_file():
        return found
    for line in path.read_text(encoding="utf-8").splitlines():
        key, _, rest = line.partition(":")
        number = rest.strip().split()
        if number and number[0].isdigit():
            found[key] = int(number[0]) * 1024
    return found


def inventory():
    memory = _meminfo()
    total = memory.get("MemTotal")
    available = memory.get("MemAvailable")
    swap = memory.get("SwapTotal")
    cores = os.cpu_count() or 1
    disk = shutil.disk_usage("/")
    gpu = Path("/dev/nvidia0").exists() or Path("/proc/driver/nvidia/version").exists()
    vram = None
    suitable = bool(total and total >= REFUSAL_FLOOR_BYTES and cores >= 4 and disk.free >= 20 * 1024 ** 3)
    return {
        "hosts": [
            {
                "id": "this-process-host",
                "always_on_inference": False,
                "dedicated": False,
                "ram_bytes": total,
                "available_ram_bytes": available,
                "swap_bytes": swap,
                "cpu_cores": cores,
                "gpu_present": gpu,
                "vram_bytes": vram,
                "disk_free_bytes": disk.free,
                "suitable": suitable,
                "reason": None if suitable else "below the refusal floor or not a dedicated inference host",
            }
        ],
        "suitable_host_found": False,
        "operational": "BLOCKED",
        "models_present": [],
        "download_attempted": False,
        "selected_model": None,
        "benchmark_status": "NOT TESTED",
        "candidates": list(CANDIDATES),
        "refusal_floor_bytes": REFUSAL_FLOOR_BYTES,
        "note": (
            "No dedicated inference machine is attached. "
            "Model file size is not treated as the runtime RAM requirement. "
            "Do not install a candidate on this host."
        ),
    }
