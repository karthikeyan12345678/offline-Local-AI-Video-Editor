"""Which model files the app needs and where they come from."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

BASE_REPO = "Lightricks/LTX-Video"
# Text encoder (T5-XXL), tokenizer and scheduler config. The transformer and VAE
# come from the single-file checkpoint, so the 0.9.0 weights in the repo are skipped.
BASE_PATTERNS = ("model_index.json", "scheduler/*", "tokenizer/*", "text_encoder/*")
BASE_ID = "ltxv-base"

# Official 0.9.6 distilled schedule (configs/ltxv-2b-0.9.6-distilled.yaml in LTX-Video).
DISTILLED_TIMESTEPS = (1000.0, 993.7, 987.5, 981.2, 975.0, 909.4, 725.0, 421.9)


@dataclass(frozen=True)
class ModelSpec:
    id: str
    label: str
    note: str
    repo: str
    checkpoint: str
    # diffusers needs the model config next to the weights. It normally fetches it
    # from the Hub on every load; we download it once so the app works offline.
    config_repo: str
    distilled: bool
    default_steps: int
    default_guidance: float
    min_steps: int
    max_steps: int

    def root(self, models_root: Path) -> Path:
        return models_root / self.id

    def checkpoint_path(self, models_root: Path) -> Path:
        return self.root(models_root) / self.checkpoint

    def config_dir(self, models_root: Path) -> Path:
        return self.root(models_root) / "config"


MODELS: dict[str, ModelSpec] = {
    "ltxv-2b-distilled": ModelSpec(
        id="ltxv-2b-distilled",
        label="LTX-Video 2B Distilled (0.9.6)",
        note="Fast: 8 steps, no guidance pass. Recommended for 4 GB GPUs.",
        repo=BASE_REPO,
        checkpoint="ltxv-2b-0.9.6-distilled-04-25.safetensors",
        config_repo="Lightricks/LTX-Video-0.9.5",  # diffusers detects 0.9.6 weights as the 0.9.5 architecture
        distilled=True,
        default_steps=8,
        default_guidance=1.0,
        min_steps=8,
        max_steps=8,
    ),
    "ltxv-2b-091": ModelSpec(
        id="ltxv-2b-091",
        label="LTX-Video 2B (0.9.1)",
        note="Slower, uses guidance. Fallback if the distilled model misbehaves on your GPU.",
        repo=BASE_REPO,
        checkpoint="ltx-video-2b-v0.9.1.safetensors",
        config_repo="diffusers/LTX-Video-0.9.1",
        distilled=False,
        default_steps=30,
        default_guidance=3.0,
        min_steps=10,
        max_steps=50,
    ),
}


CONFIG_PATTERNS = ("transformer/config.json", "vae/config.json")


def base_dir(models_root: Path) -> Path:
    return models_root / "ltx-video-base"
