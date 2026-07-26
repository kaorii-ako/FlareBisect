"""GPU/VRAM detection and local-model sizing.

Best-effort across NVIDIA (nvidia-smi), AMD (rocm-smi), Apple Silicon
(unified memory via sysctl), and Windows (WMI via PowerShell). Falls back to
"no GPU" if nothing is found, which still yields a usable (small) model
recommendation instead of an error.
"""

from __future__ import annotations

import json
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass

# (vram_gb_ceiling, ollama_tag, description) - first tier whose ceiling exceeds
# the detected VRAM wins. Sizes assume 4-bit quantization with headroom for context.
MODEL_TIERS: list[tuple[float, str, str]] = [
    (3.0, "qwen2.5:0.5b", "tiny CPU-friendly model (~0.4GB)"),
    (6.0, "llama3.2:3b", "small, fast model (~2GB)"),
    (10.0, "llama3.1:8b", "solid general-purpose model (~5GB)"),
    (16.0, "qwen2.5:14b", "stronger reasoning (~9GB)"),
    (40.0, "qwen2.5:32b", "large, high-quality model (~18GB)"),
]
FALLBACK_MODEL: tuple[str, str] = ("llama3.1:70b", "flagship-scale model (~40GB), needs serious VRAM")


@dataclass
class GPUInfo:
    vendor: str  # "nvidia", "amd", "apple", "unknown", "none"
    name: str
    vram_gb: float


def _run(cmd: list[str]) -> str | None:
    if not shutil.which(cmd[0]):
        return None
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return result.stdout.strip()


def _detect_nvidia() -> GPUInfo | None:
    out = _run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
    if not out:
        return None
    try:
        name, mib = (part.strip() for part in out.splitlines()[0].split(","))
        return GPUInfo(vendor="nvidia", name=name, vram_gb=round(float(mib) / 1024, 1))
    except ValueError:
        return None


def _detect_amd() -> GPUInfo | None:
    out = _run(["rocm-smi", "--showproductname", "--showmeminfo", "vram"])
    if not out:
        return None
    vram_match = re.search(r"VRAM Total Memory \(B\):\s*(\d+)", out)
    if not vram_match:
        return None
    name_match = re.search(r"Card series:\s*(.+)", out)
    vram_gb = round(int(vram_match.group(1)) / (1024 ** 3), 1)
    name = name_match.group(1).strip() if name_match else "AMD GPU"
    return GPUInfo(vendor="amd", name=name, vram_gb=vram_gb)


def _detect_apple_silicon() -> GPUInfo | None:
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        return None
    mem_out = _run(["sysctl", "-n", "hw.memsize"])
    if not mem_out:
        return None
    try:
        total_gb = int(mem_out) / (1024 ** 3)
    except ValueError:
        return None
    # Unified memory is shared with the OS and other apps, so only a fraction
    # is realistically usable for model weights.
    usable_gb = round(total_gb * 0.7, 1)
    name = _run(["sysctl", "-n", "machdep.cpu.brand_string"]) or "Apple Silicon"
    return GPUInfo(vendor="apple", name=name, vram_gb=usable_gb)


def _detect_windows_wmi() -> GPUInfo | None:
    if platform.system() != "Windows":
        return None
    out = _run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_VideoController | Select-Object -First 1 Name,AdapterRAM | ConvertTo-Json",
        ]
    )
    if not out:
        return None
    try:
        data = json.loads(out)
    except ValueError:
        return None
    name = data.get("Name") or "GPU"
    ram = data.get("AdapterRAM")
    if not ram:
        return None
    vendor = "nvidia" if "nvidia" in name.lower() else "amd" if ("amd" in name.lower() or "radeon" in name.lower()) else "unknown"
    return GPUInfo(vendor=vendor, name=name, vram_gb=round(int(ram) / (1024 ** 3), 1))


def detect_gpu() -> GPUInfo:
    for detector in (_detect_nvidia, _detect_amd, _detect_apple_silicon, _detect_windows_wmi):
        info = detector()
        if info:
            return info
    return GPUInfo(vendor="none", name="no dedicated GPU detected", vram_gb=0.0)


def recommend_model_with_desc(vram_gb: float) -> tuple[str, str]:
    for ceiling, model, desc in MODEL_TIERS:
        if vram_gb < ceiling:
            return model, desc
    return FALLBACK_MODEL


def recommend_model(vram_gb: float) -> str:
    return recommend_model_with_desc(vram_gb)[0]


def ollama_available() -> bool:
    return shutil.which("ollama") is not None


def pull_model(model: str) -> None:
    if not ollama_available():
        raise RuntimeError("ollama not found on PATH - install it from https://ollama.com first")
    subprocess.run(["ollama", "pull", model], check=True)
