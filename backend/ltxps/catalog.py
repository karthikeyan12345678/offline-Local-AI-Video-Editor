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


# Speech-to-text models for automatic captions (faster-whisper format, ~75 MB / 145 MB / 480 MB).
@dataclass(frozen=True)
class AuxSpec:
    id: str
    label: str
    note: str
    repo: str
    patterns: tuple[str, ...]
    kind: str = "captions"


WHISPER_PATTERNS = ("config.json", "model.bin", "tokenizer.json", "vocabulary.*", "preprocessor_config.json")
AUX: dict[str, AuxSpec] = {
    f"whisper-{size}": AuxSpec(f"whisper-{size}", f"Captions model: Whisper {size}", note, f"Systran/faster-whisper-{size}", WHISPER_PATTERNS)
    for size, note in (
        ("tiny", "Fastest, English and simple speech (about 75 MB)."),
        ("base", "Good balance for clear speech (about 145 MB)."),
        ("small", "Best accuracy for Tamil, Hindi and other languages; slower (about 480 MB)."),
    )
}


# Picture-making model used by the AI Assistant's "Images" page (runs on this PC, no account, works offline afterwards).
# Only the fp16 files are fetched, about 2.6 GB in total.
IMAGE_PATTERNS = ("model_index.json", "scheduler/*.json", "tokenizer/*", "unet/config.json", "unet/diffusion_pytorch_model.fp16.safetensors",
                  "vae/config.json", "vae/diffusion_pytorch_model.fp16.safetensors", "text_encoder/config.json", "text_encoder/model.fp16.safetensors")
AUX["image-sd-turbo"] = AuxSpec("image-sd-turbo", "Picture maker: Stable Diffusion Turbo", "Makes pictures on this PC in a few seconds. Used by the AI Assistant's Images page (about 2.6 GB).",
                                "stabilityai/sd-turbo", IMAGE_PATTERNS, kind="image")

# Object editor used by the chat editor ("remove the hill", "put a cap on him"): Stable Diffusion 1.5 inpainting, fp16 files only (about 2.2 GB).
INPAINT_PATTERNS = ("model_index.json", "scheduler/*.json", "tokenizer/*", "feature_extractor/*", "unet/config.json", "unet/diffusion_pytorch_model.fp16.safetensors",
                    "vae/config.json", "vae/diffusion_pytorch_model.fp16.safetensors", "text_encoder/config.json", "text_encoder/model.fp16.safetensors")
AUX["image-inpaint"] = AuxSpec("image-inpaint", "Object editor: AI inpainting", "Lets the chat editor remove, change or add things inside your video (a hill, a person, a cap, shoes). About 2.2 GB.",
                               "stable-diffusion-v1-5/stable-diffusion-inpainting", INPAINT_PATTERNS, kind="image")

# Rough download sizes, shown before the real size is known.
APPROX_BYTES = {"ltxv-base": 9_500_000_000, "ltxv-2b-distilled": 4_300_000_000, "ltxv-2b-091": 4_700_000_000, "whisper-tiny": 75_000_000,
                "whisper-base": 145_000_000, "whisper-small": 480_000_000, "image-sd-turbo": 2_600_000_000, "image-inpaint": 2_200_000_000}
