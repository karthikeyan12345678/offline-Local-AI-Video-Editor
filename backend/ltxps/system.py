"""Hardware detection.

Works with or without PyTorch installed, so the UI can still explain what is
missing (for example while the runtime is being set up on a new PC).
"""

from __future__ import annotations

import ctypes
import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass, field


@dataclass
class GpuInfo:
    available: bool = False
    name: str = ""
    vram_mb: int = 0
    compute_capability: tuple[int, int] | None = None
    arch_supported: bool | None = None  # None = unknown (torch missing)
    problem: str = ""

    @property
    def vram_gb(self) -> float:
        return round(self.vram_mb / 1024, 1)


@dataclass
class SystemInfo:
    os: str
    cpu_count: int
    ram_mb: int
    gpu: GpuInfo
    torch_version: str | None
    cuda_version: str | None
    ffmpeg: str | None
    warnings: list[str] = field(default_factory=list)


def ram_mb() -> int:
    try:
        if os.name == "nt":

            class MemStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MemStatus()
            stat.dwLength = ctypes.sizeof(MemStatus)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))  # type: ignore[attr-defined]
            return int(stat.ullTotalPhys // (1024 * 1024))
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) // 1024
    except (OSError, ValueError, AttributeError):
        pass
    return 0


def _nvidia_smi() -> GpuInfo | None:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "--query-gpu=name,memory.total,compute_cap", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout.strip()
        if not out:
            return None
        # Several GPUs: use the one with the most memory.
        best: GpuInfo | None = None
        for line in out.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 3:
                continue
            cc = re.match(r"(\d+)\.(\d+)", parts[2])
            info = GpuInfo(
                available=True,
                name=parts[0],
                vram_mb=int(float(parts[1])),
                compute_capability=(int(cc.group(1)), int(cc.group(2))) if cc else None,
            )
            if best is None or info.vram_mb > best.vram_mb:
                best = info
        return best
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def arch_is_supported(arch_list: list[str], capability: tuple[int, int]) -> bool:
    """True if this torch build can run kernels on a GPU of this compute capability.

    NVIDIA machine code is compatible upward inside one major generation: an sm_86 build runs on an sm_89 card (RTX 40-series), an
    sm_80 build on sm_86, and so on. Recent CUDA 13 wheels list sm_86 and sm_90 but no sm_89, so an exact match would wrongly call
    those cards unusable and push the studio onto the CPU."""
    major, minor = capability
    cc = major * 10 + minor
    for arch in arch_list:
        m = re.fullmatch(r"sm_(\d+)([a-z]?)", arch)
        if not m:
            continue
        v, suffix = int(m.group(1)), m.group(2)
        if v == cc:
            return True
        if not suffix and v // 10 == major and v < cc:  # same generation, older minor: binary compatible
            return True
    # PTX (compute_XX) is forward compatible with newer GPUs.
    for arch in arch_list:
        m = re.fullmatch(r"compute_(\d+)[a-z]?", arch)
        if m and int(m.group(1)) <= cc:
            return True
    return False


def kernel_runs(torch_module) -> bool:
    """Prove it: run a tiny kernel on the GPU. Used when the arch list alone says 'no', so a good card is never rejected on a technicality."""
    try:
        t = torch_module
        x = t.ones(16, device="cuda", dtype=t.float16) * 2
        return bool(float(x.sum().item()) == 32.0)
    except Exception:  # noqa: BLE001 - any failure means the kernels really are missing
        return False


def ffmpeg_path() -> str | None:
    env = os.environ.get("LTXPS_FFMPEG")
    if env and os.path.exists(env):
        return env
    try:
        import imageio_ffmpeg  # type: ignore

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:  # noqa: BLE001 - optional dependency, any failure means "not there"
        pass
    return shutil.which("ffmpeg")


def detect_system() -> SystemInfo:
    warnings: list[str] = []
    torch_version: str | None = None
    cuda_version: str | None = None
    gpu = GpuInfo()

    fake_vram = os.environ.get("LTXPS_FAKE_VRAM_MB")
    if fake_vram:
        gpu = GpuInfo(available=True, name="Simulated GPU", vram_mb=int(fake_vram), compute_capability=(8, 6), arch_supported=True)
    else:
        try:
            import torch  # type: ignore

            torch_version = torch.__version__
            cuda_version = torch.version.cuda
            if torch.cuda.is_available():
                best_idx, best_mem = 0, -1
                for idx in range(torch.cuda.device_count()):
                    mem = torch.cuda.get_device_properties(idx).total_memory
                    if mem > best_mem:
                        best_idx, best_mem = idx, mem
                props = torch.cuda.get_device_properties(best_idx)
                cap = (props.major, props.minor)
                supported = arch_is_supported(list(torch.cuda.get_arch_list()), cap) or kernel_runs(torch)
                gpu = GpuInfo(
                    available=True,
                    name=props.name,
                    vram_mb=int(props.total_memory // (1024 * 1024)),
                    compute_capability=cap,
                    arch_supported=supported,
                )
                if not supported:
                    gpu.problem = (
                        f"The installed PyTorch build has no kernels for this GPU (compute {cap[0]}.{cap[1]}). "
                        "Use the menu Help > Repair runtime to install the matching build."
                    )
                    warnings.append(gpu.problem)
            else:
                smi = _nvidia_smi()
                if smi:
                    gpu = smi
                    gpu.available = False
                    gpu.problem = (
                        "An NVIDIA GPU was found but this PyTorch build cannot use it. "
                        "Update the NVIDIA driver, or use the menu Help > Repair runtime."
                    )
                    warnings.append(gpu.problem)
        except ImportError:
            smi = _nvidia_smi()
            if smi:
                gpu = smi
            warnings.append("The AI runtime (PyTorch) is not installed yet.")

    ffmpeg = ffmpeg_path()
    if not ffmpeg:
        warnings.append("ffmpeg was not found. Video editing and export are unavailable.")

    return SystemInfo(
        os=f"{platform.system()} {platform.release()}",
        cpu_count=os.cpu_count() or 1,
        ram_mb=ram_mb(),
        gpu=gpu,
        torch_version=torch_version,
        cuda_version=cuda_version,
        ffmpeg=ffmpeg,
        warnings=warnings,
    )
