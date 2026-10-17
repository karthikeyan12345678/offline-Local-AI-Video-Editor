"""LTX-Video 2B on small GPUs, via Hugging Face diffusers.

How a 4 GB card is made to work (the "Lite" profile):

1. The 4.7B-parameter T5 text encoder never touches the GPU. It runs on the CPU
   once per prompt, its output is cached on disk, and it is freed straight away.
2. The 2B transformer's weights are stored as 8-bit floats (about 2 GB) and
   upcast layer by layer while computing. If that still does not fit, whole
   blocks are streamed to the GPU one group at a time, and as a last resort one
   layer at a time.
3. The VAE decodes in tiles so the decode step stays small.
4. Sizes are capped by a token budget (see profiles.py) so activations stay small.

Every step that can fail for lack of memory falls through to the next, more
frugal strategy automatically.
"""

from __future__ import annotations

import gc
import hashlib
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np

from ..catalog import BASE_ID, DISTILLED_TIMESTEPS, MODELS, ModelSpec, base_dir
from ..config import Paths, SettingsStore
from ..downloads import DownloadManager
from ..jobs import JobCancelled, JobContext, UserFacingError
from ..profiles import Profile, pick_profile
from ..system import SystemInfo
from .base import GenRequest, write_video

log = logging.getLogger("ltxps.engine")

MAX_PROMPT_TOKENS = 128
MODE_ORDER = ("none", "model", "group", "sequential")


def condition_pipeline_available() -> bool:
    try:
        from diffusers import LTXConditionPipeline  # noqa: F401
        from diffusers.pipelines.ltx.pipeline_ltx_condition import LTXVideoCondition  # noqa: F401
    except Exception:  # noqa: BLE001 - older diffusers
        return False
    return True


class NanOutput(Exception):
    """The model produced NaN/blank frames (typical of fp16 on some GPUs)."""


@dataclass(frozen=True)
class MemoryPlan:
    device: str  # cuda | cpu
    dtype: str  # bf16 | fp16 | fp32
    fp8: bool
    mode: str  # none | model | group | sequential
    tiling: bool

    @property
    def key(self) -> tuple:
        return (self.device, self.dtype, self.fp8, self.mode)

    def describe(self) -> str:
        if self.device == "cpu":
            return f"CPU ({self.dtype})"
        parts = []
        if self.fp8:
            parts.append("8-bit weights")
        parts.append(
            {
                "none": "all on GPU",
                "model": "CPU offload per stage",
                "group": "streamed block groups",
                "sequential": "streamed layers",
            }[self.mode]
        )
        return f"{' + '.join(parts)} ({self.dtype})"


def build_plans(profile: Profile, system: SystemInfo, compute_dtype: str = "auto", memory_mode: str = "auto") -> list[MemoryPlan]:
    """Ordered strategies to try, most capable first."""
    gpu = system.gpu
    usable = gpu.available and gpu.arch_supported is not False and profile.id != "cpu"
    if not usable:
        dtype = compute_dtype if compute_dtype != "auto" else "bf16"
        return [MemoryPlan("cpu", dtype, False, "none", True)]

    cap = gpu.compute_capability or (0, 0)
    if compute_dtype != "auto":
        dtypes = [compute_dtype]
    elif cap[0] >= 8:
        dtypes = ["bf16"]
    else:
        dtypes = ["fp16", "bf16"]  # bf16 is emulated and slow before Ampere, so try fp16 first

    start = memory_mode if memory_mode in MODE_ORDER else profile.memory_mode
    plans: list[MemoryPlan] = []
    for mode in MODE_ORDER[MODE_ORDER.index(start):]:
        fp8 = profile.fp8_storage and mode in ("model", "group")
        for dtype in dtypes:
            plans.append(MemoryPlan("cuda", dtype, fp8, mode, profile.vae_tiling or mode != "none"))
    return plans


def fixed_scheduler_class():
    """The distilled model only works with its published 8-step schedule.

    LTXPipeline always hands the scheduler its own sigmas (and rejects custom
    `timesteps`), so this scheduler ignores whatever it is given.
    """
    from diffusers import FlowMatchEulerDiscreteScheduler

    class FixedTimestepScheduler(FlowMatchEulerDiscreteScheduler):
        fixed_timesteps = DISTILLED_TIMESTEPS

        def set_timesteps(self, num_inference_steps=None, device=None, sigmas=None, mu=None, timesteps=None):  # type: ignore[override]
            super().set_timesteps(device=device, timesteps=list(self.fixed_timesteps))

    return FixedTimestepScheduler


def is_oom(exc: BaseException) -> bool:
    try:
        import torch

        if isinstance(exc, torch.cuda.OutOfMemoryError):
            return True
    except ImportError:
        pass
    msg = str(exc).lower()
    return "out of memory" in msg or "cuda error: out of memory" in msg or "cublas_status_alloc_failed" in msg


def fit_image(path: Path, width: int, height: int):
    """Center-crops to the target aspect, then resizes."""
    from PIL import Image

    img = Image.open(path).convert("RGB")
    target = width / height
    w, h = img.size
    if w / h > target:
        new_w = round(h * target)
        left = (w - new_w) // 2
        img = img.crop((left, 0, left + new_w, h))
    else:
        new_h = round(w / target)
        top = (h - new_h) // 2
        img = img.crop((0, top, w, top + new_h))
    return img.resize((width, height), Image.LANCZOS)


class LtxvEngine:
    def __init__(
        self,
        paths: Paths,
        settings: SettingsStore,
        downloads: DownloadManager,
        system: Callable[[], SystemInfo],
    ):
        self.paths = paths
        self.settings = settings
        self.downloads = downloads
        self.system = system
        self._pipe: Any = None
        self._pipe_key: tuple | None = None
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- public
    def generate(self, req: GenRequest, out_path: Path, ctx: JobContext) -> dict:
        spec = MODELS.get(req.model_id)
        if spec is None:
            raise UserFacingError(f"Unknown model '{req.model_id}'.")
        for item in (BASE_ID, spec.id):
            if not self.downloads.is_installed(item):
                raise UserFacingError("The AI model files are not downloaded yet. Open Settings > Models and download them first.")

        st = self.settings.get()
        system = self.system()
        profile = pick_profile(system, st.profile)
        plans = build_plans(profile, system, st.compute_dtype, st.memory_mode)

        skip_modes: set[str] = set()
        last_oom: BaseException | None = None
        last_nan = False
        for plan in plans:
            if plan.mode in skip_modes:
                continue
            ctx.check()
            log.info("Generating %sx%s, %s frames, model %s, strategy: %s (GPU: %s)", req.width, req.height, req.frames, spec.id, plan.describe(), system.gpu.name if system.gpu.available else "none")
            try:
                meta = self._run(req, spec, plan, out_path, ctx)
                meta["strategy"] = plan.describe()
                meta["profile"] = profile.id
                return meta
            except (JobCancelled, UserFacingError):
                self._drop_pipeline()
                raise
            except NanOutput:
                last_nan = True
                log.warning("NaN output with %s; trying next precision", plan.describe())
                self._drop_pipeline()
            except MemoryError as exc:
                self._drop_pipeline()
                raise UserFacingError(
                    "The computer ran out of RAM while loading the model. Close other programs, "
                    "or use a lower profile in Settings. At least 12 GB of RAM is recommended."
                ) from exc
            except BaseException as exc:  # noqa: BLE001
                if is_oom(exc):
                    last_oom = exc
                    skip_modes.add(plan.mode)
                    log.warning("Out of GPU memory with %s; escalating", plan.describe())
                    self._drop_pipeline()
                    continue
                self._drop_pipeline()
                raise
            finally:
                if not st.keep_loaded:
                    self._drop_pipeline()

        self._drop_pipeline()
        if last_oom is not None:
            raise UserFacingError(
                "The GPU ran out of memory, even with the most frugal settings. Try a smaller size, fewer frames, "
                "or close other programs that use the GPU."
            )
        if last_nan:
            raise UserFacingError(
                "The model produced blank frames, which usually means this GPU cannot run the chosen precision. "
                "Try Settings > Compute precision, or switch to the 0.9.1 model."
            )
        raise UserFacingError("No usable generation strategy was found for this computer.")

    def unload(self) -> None:
        self._drop_pipeline()

    # ---------------------------------------------------------------- one attempt
    def _run(self, req: GenRequest, spec: ModelSpec, plan: MemoryPlan, out_path: Path, ctx: JobContext) -> dict:
        import torch

        use_cfg = req.guidance > 1.0 and not spec.distilled
        ctx.update(0.03, "Reading your prompt")
        texts = [req.prompt] + ([req.negative_prompt or ""] if use_cfg else [])
        enc = self.encode_prompts(texts, plan, ctx)
        ctx.check()

        ctx.update(0.14, "Loading the video model")
        use_end = req.mode == "i2v" and req.end_image_path is not None and condition_pipeline_available()
        warnings: list[str] = []
        if req.end_image_path is not None and not use_end and req.mode == "i2v":
            warnings.append("This version of the video library cannot end on a picture, so only the starting picture was used.")
        pipe = self._pipeline(spec, plan, "i2v_end" if use_end else req.mode)
        ctx.check()

        steps = len(DISTILLED_TIMESTEPS) if spec.distilled else req.steps
        total_steps = max(1, steps)

        def on_step(_pipe, i, _t, kwargs):
            if ctx.cancel.is_set():
                raise JobCancelled()
            ctx.update(0.2 + 0.68 * (i + 1) / total_steps, f"Creating frames, step {i + 1} of {total_steps}")
            return kwargs

        # The cache stores bf16; the transformer may run in fp16 (pre-Ampere GPUs) or fp32.
        compute = dtype_of(plan.dtype)
        # The cached prompt data lives on the CPU. The pipeline does NOT move embeddings you hand it, so they must already sit on the device the
        # transformer runs on, or the first layer fails with "Expected all tensors to be on the same device".
        dev = torch.device("cuda") if plan.device == "cuda" else torch.device("cpu")

        call: dict[str, Any] = dict(
            prompt_embeds=enc[0][0].to(dev, compute).unsqueeze(0),
            prompt_attention_mask=enc[0][1].to(dev).unsqueeze(0),
            width=req.width,
            height=req.height,
            num_frames=req.frames,
            frame_rate=req.fps,
            num_inference_steps=steps,
            guidance_scale=req.guidance if use_cfg else 1.0,
            generator=torch.Generator("cpu").manual_seed(req.seed),
            output_type="np",
            decode_timestep=0.05,
            decode_noise_scale=0.025,
            callback_on_step_end=on_step,
            max_sequence_length=MAX_PROMPT_TOKENS,
        )
        if use_cfg:
            call["negative_prompt_embeds"] = enc[1][0].to(dev, compute).unsqueeze(0)
            call["negative_prompt_attention_mask"] = enc[1][1].to(dev).unsqueeze(0)
        if req.mode == "i2v":
            if req.image_path is None:
                raise UserFacingError("Choose a starting image for image-to-video.")
            start = fit_image(req.image_path, req.width, req.height)
            if use_end:
                from diffusers.pipelines.ltx.pipeline_ltx_condition import LTXVideoCondition

                call["conditions"] = [
                    LTXVideoCondition(image=start, frame_index=0),
                    LTXVideoCondition(image=fit_image(req.end_image_path, req.width, req.height), frame_index=req.frames - 1),
                ]
            else:
                call["image"] = start

        ctx.update(0.2, "Creating frames")
        try:
            with torch.inference_mode():
                result = pipe(**call)
        except (TypeError, ValueError, KeyError, AttributeError, IndexError) as exc:
            if not use_end:
                raise
            # The end picture could not be used with this library version: continue with the starting picture only.
            log.warning("End-picture generation failed (%s); using only the start picture", exc)
            warnings.append("The ending picture could not be used, so only the starting picture was used.")
            call.pop("conditions", None)
            call["image"] = start
            pipe = self._pipeline(spec, plan, req.mode)
            with torch.inference_mode():
                result = pipe(**call)
        frames = np.asarray(result.frames[0])
        ctx.update(0.94, "Saving the video")

        if not np.isfinite(frames).all() or float(frames.std()) < 1e-4:
            raise NanOutput()
        u8 = (np.clip(frames, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
        write_video((f for f in u8), req.width, req.height, req.fps, out_path)
        return {"warnings": warnings} if warnings else {}

    # ---------------------------------------------------------------- prompts
    def encode_prompts(self, texts: list[str], plan: MemoryPlan, ctx: JobContext) -> list[tuple[Any, Any]]:
        """Returns (embeds[L, D], mask[L]) per text, using the on-disk cache."""
        results: list[tuple[Any, Any] | None] = []
        missing: list[int] = []
        for i, text in enumerate(texts):
            cached = self._cache_get(text)
            results.append(cached)
            if cached is None:
                missing.append(i)
        if missing:
            ctx.update(0.05, "Reading your prompt (first time takes a while)")
            fresh = self._encode_uncached([texts[i] for i in missing], plan)
            for i, pair in zip(missing, fresh):
                results[i] = pair
                self._cache_put(texts[i], pair)
        return [pair for pair in results if pair is not None]

    def _cache_path(self, text: str) -> Path:
        h = hashlib.sha256(f"{MAX_PROMPT_TOKENS}\0{text}".encode("utf-8")).hexdigest()[:40]
        return self.paths.cache / f"prompt_{h}.pt"

    def _cache_get(self, text: str):
        import torch

        p = self._cache_path(text)
        if p.exists():
            try:
                d = torch.load(p, map_location="cpu", weights_only=True)
                return d["embeds"], d["mask"]
            except Exception:  # noqa: BLE001 - corrupt cache entry: recompute
                p.unlink(missing_ok=True)
        return None

    def _cache_put(self, text: str, pair) -> None:
        import torch

        try:
            torch.save({"embeds": pair[0].cpu(), "mask": pair[1].cpu()}, self._cache_path(text))
            # Keep the cache small.
            files = sorted(self.paths.cache.glob("prompt_*.pt"), key=lambda f: f.stat().st_mtime)
            for old in files[:-200]:
                old.unlink(missing_ok=True)
        except OSError as exc:
            log.warning("could not cache prompt embedding: %s", exc)

    def _encode_uncached(self, texts: list[str], plan: MemoryPlan):
        """Runs T5-XXL on the CPU (it is far too big for a small GPU) and frees it."""
        import torch
        from transformers import AutoTokenizer, T5EncoderModel

        root = base_dir(self.paths.models)
        tokenizer = AutoTokenizer.from_pretrained(str(root / "tokenizer"), local_files_only=True)
        encoder = T5EncoderModel.from_pretrained(
            str(root / "text_encoder"), torch_dtype=torch.bfloat16, low_cpu_mem_usage=True, local_files_only=True
        )
        encoder.eval()
        try:
            tok = tokenizer(
                texts, padding="max_length", max_length=MAX_PROMPT_TOKENS, truncation=True, add_special_tokens=True, return_tensors="pt"
            )
            with torch.inference_mode():
                hidden = encoder(tok.input_ids)[0]
            return [(hidden[i].to(torch.bfloat16).clone(), tok.attention_mask[i].bool().clone()) for i in range(len(texts))]
        finally:
            del encoder
            gc.collect()

    # ---------------------------------------------------------------- pipeline
    def load_components(self, spec: ModelSpec, plan: MemoryPlan) -> dict[str, Any]:
        """Loads transformer, VAE and scheduler. Overridden in tests with tiny models."""
        from diffusers import AutoencoderKLLTXVideo, FlowMatchEulerDiscreteScheduler, LTXVideoTransformer3DModel

        dtype = dtype_of(plan.dtype)
        ckpt = spec.checkpoint_path(self.paths.models)
        cfg = str(spec.config_dir(self.paths.models))
        common = dict(torch_dtype=dtype, config=cfg, local_files_only=True)
        transformer = LTXVideoTransformer3DModel.from_single_file(str(ckpt), subfolder="transformer", **common)
        vae = AutoencoderKLLTXVideo.from_single_file(str(ckpt), subfolder="vae", **common)

        sched_cfg = FlowMatchEulerDiscreteScheduler.load_config(str(base_dir(self.paths.models) / "scheduler"))
        if spec.distilled:
            scheduler = fixed_scheduler_class().from_config(sched_cfg, use_dynamic_shifting=False, shift=1.0, shift_terminal=None)
        else:
            scheduler = FlowMatchEulerDiscreteScheduler.from_config(sched_cfg)
        return {"transformer": transformer, "vae": vae, "scheduler": scheduler}

    def _pipeline(self, spec: ModelSpec, plan: MemoryPlan, mode: str):
        key = (spec.id, mode, *plan.key)
        with self._lock:
            if self._pipe is not None and self._pipe_key == key:
                return self._pipe
            self._drop_pipeline_locked()
            self._pipe = self._build(spec, plan, mode)
            self._pipe_key = key
            return self._pipe

    def _build(self, spec: ModelSpec, plan: MemoryPlan, mode: str):
        import torch
        from diffusers import LTXImageToVideoPipeline, LTXPipeline

        comps = self.load_components(spec, plan)
        if mode == "i2v_end":
            from diffusers import LTXConditionPipeline

            cls = LTXConditionPipeline
        else:
            cls = LTXImageToVideoPipeline if mode == "i2v" else LTXPipeline
        pipe = cls(text_encoder=None, tokenizer=None, **comps)

        if plan.fp8:
            pipe.transformer.enable_layerwise_casting(storage_dtype=torch.float8_e4m3fn, compute_dtype=dtype_of(plan.dtype))
        if plan.tiling:
            pipe.vae.enable_tiling()
            pipe.vae.enable_slicing()

        if plan.device == "cpu":
            pipe.to("cpu")
        elif plan.mode == "none":
            pipe.to("cuda")
        elif plan.mode == "model":
            pipe.enable_model_cpu_offload()
        elif plan.mode == "group":
            pipe.enable_group_offload(
                onload_device=torch.device("cuda"),
                offload_device=torch.device("cpu"),
                offload_type="block_level",
                num_blocks_per_group=2,
                use_stream=False,
            )
        else:
            pipe.enable_sequential_cpu_offload()
        return pipe

    def _drop_pipeline(self) -> None:
        with self._lock:
            self._drop_pipeline_locked()

    def _drop_pipeline_locked(self) -> None:
        if self._pipe is None:
            return
        pipe, self._pipe, self._pipe_key = self._pipe, None, None
        try:
            pipe.remove_all_hooks()
        except Exception:  # noqa: BLE001 - not every offload mode installs hooks
            pass
        del pipe
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass


def dtype_of(name: str):
    import torch

    return {"bf16": torch.bfloat16, "fp16": torch.float16, "fp32": torch.float32}[name]
