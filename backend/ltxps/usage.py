"""Live load of the computer: CPU, memory, graphics card and its memory. No extra packages: it asks Windows / Linux / nvidia-smi directly."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from typing import Any

_lock = threading.Lock()
_last_cpu: tuple[float, float] | None = None  # (busy, total)
_gpu_cache: tuple[float, dict[str, Any]] = (0.0, {})


def _cpu_times() -> tuple[float, float] | None:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        idle, kernel, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
        if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):  # type: ignore[attr-defined]
            return None

        def val(f: wintypes.FILETIME) -> float:
            return float((f.dwHighDateTime << 32) | f.dwLowDateTime)

        total = val(kernel) + val(user)  # kernel time already includes idle
        return total - val(idle), total
    try:
        with open("/proc/stat", encoding="utf-8") as fh:
            parts = [float(x) for x in fh.readline().split()[1:8]]
        total = sum(parts)
        return total - parts[3] - parts[4], total
    except (OSError, ValueError, IndexError):
        return None


def cpu_percent() -> float | None:
    global _last_cpu
    now = _cpu_times()
    if now is None:
        return None
    with _lock:
        prev, _last_cpu = _last_cpu, now
    if prev is None or now[1] <= prev[1]:
        return None
    return round(max(0.0, min(100.0, (now[0] - prev[0]) / (now[1] - prev[1]) * 100)), 1)


def memory() -> tuple[float, float] | None:
    """(used_gb, total_gb) of system memory."""
    try:
        if os.name == "nt":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            ms = MS()
            ms.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))  # type: ignore[attr-defined]
            return (ms.ullTotalPhys - ms.ullAvailPhys) / 2**30, ms.ullTotalPhys / 2**30
        info: dict[str, float] = {}
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                k, _, v = line.partition(":")
                info[k] = float(v.split()[0]) / 1048576
        return info["MemTotal"] - info.get("MemAvailable", 0.0), info["MemTotal"]
    except (OSError, ValueError, KeyError, AttributeError):
        return None


def gpu() -> dict[str, Any]:
    """Graphics card load and memory from nvidia-smi, cached for one second."""
    global _gpu_cache
    with _lock:
        stamp, data = _gpu_cache
        if time.time() - stamp < 1.0:
            return data
    out: dict[str, Any] = {}
    try:
        flags = 0x08000000 if os.name == "nt" else 0  # no console window flashing
        res = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=3, creationflags=flags)
        line = (res.stdout or "").strip().splitlines()[0]
        p = [x.strip() for x in line.split(",")]
        out = {"util": float(p[0]), "vram_used_gb": round(float(p[1]) / 1024, 2), "vram_total_gb": round(float(p[2]) / 1024, 2)}
        if len(p) > 3 and p[3].replace(".", "").isdigit():
            out["temp_c"] = float(p[3])
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        out = {}
    with _lock:
        _gpu_cache = (time.time(), out)
    return out


def sample() -> dict[str, Any]:
    mem = memory()
    g = gpu()
    return {
        "cpu": cpu_percent(),
        "ram_used_gb": round(mem[0], 1) if mem else None,
        "ram_total_gb": round(mem[1], 1) if mem else None,
        "gpu": g.get("util"),
        "vram_used_gb": g.get("vram_used_gb"),
        "vram_total_gb": g.get("vram_total_gb"),
        "gpu_temp_c": g.get("temp_c"),
    }


def diagnose(s: dict[str, Any], elapsed: float, expected: float | None) -> str | None:
    """A plain-words reason when a job runs far longer than it should, from the numbers above."""
    if elapsed < 120:
        return None
    gpu_util, vram_used, vram_total = s.get("gpu"), s.get("vram_used_gb"), s.get("vram_total_gb")
    ram_used, ram_total = s.get("ram_used_gb"), s.get("ram_total_gb")
    if vram_total and vram_used and vram_used / vram_total > 0.93 and ram_total and ram_used and ram_used / ram_total > 0.8:
        return "The graphics memory is full and Windows is borrowing system memory, which is very slow. Choose the Lite profile in Settings, or a smaller size."
    if gpu_util is not None and gpu_util < 15 and (s.get("cpu") or 0) > 60:
        return "The work is running on the CPU, not the graphics card. Open Settings > This PC and use Help > Repair runtime if it shows a graphics problem."
    if gpu_util is not None and gpu_util < 15:
        return "The graphics card is idle: the app is probably loading files from disk or waiting on the CPU (prompt encoding). The first video after start-up is the slowest."
    if expected and elapsed > expected * 2.5:
        return "This is running much longer than the estimate. Try a smaller size or a shorter length."
    return None
