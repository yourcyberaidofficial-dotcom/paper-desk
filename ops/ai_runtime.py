"""Host measurement for the local model. This module does not download anything."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


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


def host_facts():
    memory = _meminfo()
    total = memory.get("MemTotal")
    available = memory.get("MemAvailable")
    cores = os.cpu_count() or 1
    disk = shutil.disk_usage("/")
    gpu = Path("/dev/nvidia0").exists() or Path("/proc/driver/nvidia/version").exists()
    # Published GGUF sizes, not a download. q4_K_M 9B is larger than this host.
    comfortable_9b = bool(gpu and (total or 0) >= 16 * 1024**3) or (total or 0) >= 32 * 1024**3
    return {
        "ram_bytes": total,
        "available_ram_bytes": available,
        "cpu_cores": cores,
        "gpu_present": gpu,
        "disk_free_bytes": disk.free,
        "model_installed": False,
        "download_attempted": False,
        "selected_model": None,
        "candidate": "qwen3.5:9b-q4_K_M",
        "compared_with": ["qwen3.5:4b-q4_K_M", "qwen3.5:2b-q4_K_M"],
        "comfortable_for_primary": comfortable_9b,
        "decision": "not_installed",
        "reason": (
            "This host is not a dedicated inference machine. "
            "The 9B Q4 candidate is not installed. A smaller model was not selected in its place."
        ),
        "recommendation": (
            "Use a private host with at least 32 GB RAM, or a GPU with at least 8 GB VRAM, "
            "4 CPU cores, and 20 GB free disk. Bind Ollama to loopback or an RFC1918 address. "
            "Point OLLAMA_BASE_URL at that address and set OLLAMA_MODEL only after the weights are local."
        ),
    }
