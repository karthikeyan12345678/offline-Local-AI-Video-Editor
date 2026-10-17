"""Hardware tiers.

The 4 GB tier is the design target. Limits are expressed as a token budget
(latent positions the transformer attends over) because that, not pixel count
alone, drives memory. tokens = (w/32) * (h/32) * ((frames-1)/8 + 1).
"""

from __future__ import annotations

from dataclasses import dataclass

from .system import SystemInfo


@dataclass(frozen=True)
class Profile:
    id: str
    label: str
    description: str
    max_tokens: int
    max_frames: int
    max_side: int
    default_width: int
    default_height: int
    default_frames: int
    fp8_storage: bool
    memory_mode: str  # model | group | sequential | none
    vae_tiling: bool
    resolutions: tuple[tuple[str, int, int], ...]


PROFILES: dict[str, Profile] = {
    "cpu": Profile(
        id="cpu",
        label="CPU only",
        description="No usable NVIDIA GPU. Works, but a short clip can take a long time.",
        max_tokens=600,
        max_frames=33,
        max_side=384,
        default_width=320,
        default_height=224,
        default_frames=25,
        fp8_storage=False,
        memory_mode="none",
        vae_tiling=True,
        resolutions=(("320 x 224", 320, 224), ("384 x 256", 384, 256)),
    ),
    "lite": Profile(
        id="lite",
        label="Lite (4-7 GB GPU)",
        description="Fits 4 GB cards: 8-bit weight storage, CPU offload and tiled decoding.",
        max_tokens=2300,
        max_frames=97,
        max_side=704,
        default_width=640,
        default_height=384,
        default_frames=49,
        fp8_storage=True,
        memory_mode="model",
        vae_tiling=True,
        resolutions=(
            ("384 x 256 (fastest)", 384, 256),
            ("512 x 320", 512, 320),
            ("576 x 384", 576, 384),
            ("640 x 384", 640, 384),
            ("704 x 416", 704, 416),
            ("320 x 512 (portrait)", 320, 512),
        ),
    ),
    "balanced": Profile(
        id="balanced",
        label="Balanced (8-11 GB GPU)",
        description="Full-precision weights with CPU offload between stages.",
        max_tokens=6500,
        max_frames=161,
        max_side=960,
        default_width=704,
        default_height=480,
        default_frames=97,
        fp8_storage=False,
        memory_mode="model",
        vae_tiling=True,
        resolutions=(
            ("512 x 320", 512, 320),
            ("704 x 480", 704, 480),
            ("768 x 512", 768, 512),
            ("960 x 544", 960, 544),
            ("480 x 704 (portrait)", 480, 704),
        ),
    ),
    "quality": Profile(
        id="quality",
        label="Quality (12 GB+ GPU)",
        description="Largest sizes and longest clips this model supports.",
        max_tokens=14000,
        max_frames=257,
        max_side=1280,
        default_width=768,
        default_height=512,
        default_frames=121,
        fp8_storage=False,
        memory_mode="none",
        vae_tiling=False,
        resolutions=(
            ("704 x 480", 704, 480),
            ("768 x 512", 768, 512),
            ("960 x 544", 960, 544),
            ("1216 x 704", 1216, 704),
            ("512 x 768 (portrait)", 512, 768),
        ),
    ),
}


def pick_profile(system: SystemInfo, preference: str = "auto") -> Profile:
    if preference in PROFILES:
        return PROFILES[preference]
    gpu = system.gpu
    if not gpu.available or gpu.arch_supported is False:
        return PROFILES["cpu"]
    if gpu.vram_mb < 8000:  # 6 GB cards (about 6.1 GB usable) need 8-bit weights: bf16 weights spill into shared RAM and are very slow
        return PROFILES["lite"]
    if gpu.vram_mb < 12000:
        return PROFILES["balanced"]
    return PROFILES["quality"]


def tokens_for(width: int, height: int, frames: int) -> int:
    return (width // 32) * (height // 32) * ((frames - 1) // 8 + 1)


def snap_frames(frames: int) -> int:
    """LTX needs 8k + 1 frames."""
    frames = max(9, int(frames))
    return ((frames - 1) // 8) * 8 + 1


def snap_side(value: int) -> int:
    return max(64, (int(value) // 32) * 32)


class LimitError(ValueError):
    pass


def validate_request(profile: Profile, width: int, height: int, frames: int, unlock: bool = False) -> tuple[int, int, int]:
    """Snap to model constraints, then enforce the tier's limits unless unlocked."""
    w, h, f = snap_side(width), snap_side(height), snap_frames(frames)
    if unlock:
        return w, h, f
    if max(w, h) > profile.max_side:
        raise LimitError(f"The {profile.label} profile supports sides up to {profile.max_side}px (requested {max(w, h)}px).")
    if f > profile.max_frames:
        raise LimitError(f"The {profile.label} profile supports up to {profile.max_frames} frames (requested {f}).")
    tokens = tokens_for(w, h, f)
    if tokens > profile.max_tokens:
        raise LimitError(
            f"{w}x{h} for {f} frames is too large for the {profile.label} profile "
            f"({tokens} of {profile.max_tokens} allowed). Lower the size or the length."
        )
    return w, h, f
