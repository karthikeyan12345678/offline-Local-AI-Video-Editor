"""How long will this video take on THIS computer? A rough, honest estimate from the graphics card, memory and the size asked for.

The numbers are deliberately simple (effective speed per hardware tier) and are meant to be right within a factor of about two.
They exist so the person sees "about 4 minutes" or "about 2 hours, lower the size" BEFORE pressing Generate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .catalog import ModelSpec
from .profiles import Profile, tokens_for
from .system import SystemInfo

PARAMS = 2.0e9  # both LTX-Video 2B models
LAYERS, DIM = 28, 2048
LIMIT_SECONDS = 30 * 60

# effective sustained TFLOPS of the whole pipeline (not the box number) by how the model is run
SPEED_TFLOPS = {"quality": 22.0, "balanced": 9.0, "lite": 3.2, "cpu": 0.04}
# fixed costs in seconds: read the weights from disk, encode the prompt (T5 on the CPU), a little start-up
LOAD_S = {"quality": 25, "balanced": 40, "lite": 55, "cpu": 70}
TEXT_S = {"quality": 12, "balanced": 18, "lite": 28, "cpu": 60}
VAE_PIXELS_PER_S = {"quality": 9e6, "balanced": 5e6, "lite": 2.2e6, "cpu": 6e4}


@dataclass
class Estimate:
    seconds: float
    low: float
    high: float
    device: str
    band: str  # fast | ok | slow | too_long
    notes: list[str] = field(default_factory=list)
    tips: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {"seconds": round(self.seconds), "low": round(self.low), "high": round(self.high), "device": self.device, "band": self.band,
                "notes": self.notes, "tips": self.tips, "limit_seconds": LIMIT_SECONDS}


def _seconds(system: SystemInfo, profile: Profile, model: ModelSpec, width: int, height: int, frames: int, steps: int | None,
             has_end_image: bool, keep_loaded_ready: bool) -> tuple[float, bool, list[str]]:
    gpu = system.gpu
    on_gpu = gpu.available and gpu.arch_supported is not False and profile.id != "cpu"
    tier = profile.id if on_gpu else "cpu"
    n_steps = steps or model.default_steps
    passes = 1 if model.distilled else 2  # guidance runs the model twice per step
    tokens = tokens_for(width, height, frames)
    flops_step = 2 * PARAMS * tokens * passes + 4 * LAYERS * (tokens ** 2) * DIM * passes
    notes: list[str] = []
    penalty = 1.0
    # A card whose memory is nearly full spills into system RAM and slows down a lot (Windows does this silently).
    if on_gpu and gpu.vram_mb and gpu.vram_mb < 8000 and tier != "lite":
        penalty = 4.0
        notes.append("This graphics card has less than 8 GB, so the Balanced profile would spill into slow shared memory. Use Lite.")
    if on_gpu and system.ram_mb and system.ram_mb < 12000:
        penalty *= 1.4
        notes.append("Low system memory slows the model loading and the CPU offload.")
    sampling = n_steps * flops_step / (SPEED_TFLOPS[tier] * 1e12) * penalty
    decode = (width * height * frames) / VAE_PIXELS_PER_S[tier]
    overhead = (0 if keep_loaded_ready else LOAD_S[tier]) + TEXT_S[tier]
    if has_end_image:
        sampling *= 1.15
        overhead += 8
    return sampling + decode + overhead, on_gpu, notes


def estimate(system: SystemInfo, profile: Profile, model: ModelSpec, width: int, height: int, frames: int, steps: int | None = None,
             *, has_end_image: bool = False, keep_loaded_ready: bool = False) -> Estimate:
    total, on_gpu, notes = _seconds(system, profile, model, width, height, frames, steps, has_end_image, keep_loaded_ready)
    tips: list[str] = []
    if not on_gpu:
        notes.append("No usable NVIDIA graphics card was found, so this runs on the CPU. That is many times slower.")
        tips.append("Open Settings > This PC: if it shows a graphics problem, use Help > Repair runtime.")
    if total > LIMIT_SECONDS:
        notes.append("This is over the 30 minute limit.")
        for w, h, f in _smaller(profile, width, height, frames):
            alt, _, _ = _seconds(system, profile, model, w, h, f, steps, has_end_image, keep_loaded_ready)
            if alt <= LIMIT_SECONDS * 0.5:
                tips.append(f"Try {w}x{h} for {(f - 1) / 24:.1f} s: about {_fmt(alt)}.")
                break
        if model.id != "ltxv-2b-distilled":
            tips.append("Use the LTX-Video 2B Distilled model: it needs 8 steps instead of 30 and no guidance pass.")
        tips.append("Or press “Sharp cloud video” to make it online with your fal.ai key: about a minute or two.")
    band = "too_long" if total > LIMIT_SECONDS else "slow" if total > 600 else "ok" if total > 120 else "fast"
    return Estimate(total, total * 0.6, total * 1.8, "gpu" if on_gpu else "cpu", band, notes, tips)


def _smaller(profile: Profile, width: int, height: int, frames: int):
    sizes = sorted({(w, h) for _, w, h in profile.resolutions}, key=lambda s: s[0] * s[1])
    for frames_try in (frames, 33, 25, 17):
        if frames_try > frames:
            continue
        for w, h in sizes:
            if w * h <= width * height:
                yield w, h, frames_try


def _fmt(seconds: float) -> str:
    s = int(round(seconds))
    if s < 90:
        return f"{s} seconds"
    if s < 5400:
        return f"{round(s / 60)} minutes"
    return f"{s / 3600:.1f} hours"
