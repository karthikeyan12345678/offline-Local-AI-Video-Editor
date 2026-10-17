"""Exercises the real LtxvEngine code path with tiny random-weight components on CPU."""

import types
from pathlib import Path

import numpy as np
import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("diffusers")

from conftest import needs_ffmpeg  # noqa: E402
from ltxps.catalog import BASE_ID, DISTILLED_TIMESTEPS, MODELS  # noqa: E402
from ltxps.config import Paths, SettingsStore  # noqa: E402
from ltxps.editor.media import probe  # noqa: E402
from ltxps.engine.base import GenRequest  # noqa: E402
from ltxps.engine.ltxv import LtxvEngine, MemoryPlan, NanOutput, build_plans, fixed_scheduler_class, is_oom  # noqa: E402
from ltxps.jobs import Job, JobCancelled, JobContext, UserFacingError  # noqa: E402
from ltxps.profiles import PROFILES, pick_profile  # noqa: E402
from ltxps.system import GpuInfo, SystemInfo  # noqa: E402

pytestmark = needs_ffmpeg


def system(vram_mb=0, cap=(8, 6), available=True, arch_ok=True) -> SystemInfo:
    gpu = GpuInfo(available=available and vram_mb > 0, name="Test GPU", vram_mb=vram_mb, compute_capability=cap, arch_supported=arch_ok)
    return SystemInfo(os="test", cpu_count=4, ram_mb=16000, gpu=gpu, torch_version="x", cuda_version=None, ffmpeg="ffmpeg")


# ------------------------------------------------------------------ strategy selection
def test_four_gb_card_gets_lite_profile_with_8bit_weights_first():
    s = system(4096)
    prof = pick_profile(s)
    assert prof.id == "lite"
    plans = build_plans(prof, s)
    assert plans[0].mode == "model" and plans[0].fp8 and plans[0].dtype == "bf16"
    assert [p.mode for p in plans] == ["model", "group", "sequential"]


def test_pre_ampere_card_tries_fp16_before_emulated_bf16():
    s = system(4096, cap=(7, 5))
    plans = build_plans(pick_profile(s), s)
    assert [(p.mode, p.dtype) for p in plans[:2]] == [("model", "fp16"), ("model", "bf16")]


def test_sequential_offload_never_uses_8bit_storage():
    s = system(4096)
    assert all(not p.fp8 for p in build_plans(pick_profile(s), s) if p.mode == "sequential")


def test_big_card_runs_everything_on_gpu_and_can_still_escalate():
    s = system(24576)
    prof = pick_profile(s)
    assert prof.id == "quality"
    assert [p.mode for p in build_plans(prof, s)] == ["none", "model", "group", "sequential"]


def test_user_override_of_memory_mode_skips_lighter_modes():
    s = system(24576)
    assert [p.mode for p in build_plans(pick_profile(s), s, memory_mode="group")] == ["group", "sequential"]


def test_no_gpu_or_unsupported_arch_falls_back_to_cpu():
    for s in (system(0), system(8192, arch_ok=False)):
        prof = pick_profile(s)
        assert prof.id == "cpu"
        assert [p.device for p in build_plans(prof, s)] == ["cpu"]


def test_oom_detection():
    assert is_oom(RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB"))
    assert not is_oom(RuntimeError("shape mismatch"))


# ------------------------------------------------------------------ distilled schedule
def test_distilled_scheduler_ignores_pipeline_sigmas_and_uses_published_schedule():
    from diffusers import FlowMatchEulerDiscreteScheduler

    cls = fixed_scheduler_class()
    sched = cls.from_config(FlowMatchEulerDiscreteScheduler().config, use_dynamic_shifting=False, shift=1.0, shift_terminal=None)
    sched.set_timesteps(30, device="cpu", sigmas=np.linspace(1, 1 / 30, 30), mu=1.15)
    assert len(sched.timesteps) == len(DISTILLED_TIMESTEPS) == 8
    np.testing.assert_allclose(sched.timesteps.numpy(), DISTILLED_TIMESTEPS, rtol=1e-4)
    assert float(sched.sigmas[-1]) == 0.0


# ------------------------------------------------------------------ tiny end-to-end
CAPTION = 32


class StubDownloads:
    def is_installed(self, item_id):
        return True


class TinyEngine(LtxvEngine):
    """Real pipeline + real code paths, random 40k-parameter weights."""

    def load_components(self, spec, plan):
        from diffusers import AutoencoderKLLTXVideo, FlowMatchEulerDiscreteScheduler, LTXVideoTransformer3DModel

        torch.manual_seed(0)
        transformer = LTXVideoTransformer3DModel(
            in_channels=8, out_channels=8, num_attention_heads=2, attention_head_dim=8, cross_attention_dim=16,
            num_layers=2, caption_channels=CAPTION,
        )
        vae = AutoencoderKLLTXVideo(
            in_channels=3, out_channels=3, latent_channels=8, block_out_channels=(8, 8, 8, 8), decoder_block_out_channels=(8, 8, 8, 8),
            layers_per_block=(1, 1, 1, 1, 1), decoder_layers_per_block=(1, 1, 1, 1, 1),
            decoder_inject_noise=(False,) * 5, upsample_residual=(False,) * 4, upsample_factor=(1,) * 4,
            timestep_conditioning=False,
        )
        cfg = FlowMatchEulerDiscreteScheduler().config
        if spec.distilled:
            sched = fixed_scheduler_class().from_config(cfg, use_dynamic_shifting=False, shift=1.0, shift_terminal=None)
        else:
            sched = FlowMatchEulerDiscreteScheduler.from_config(cfg)
        self.loads = getattr(self, "loads", 0) + 1
        dtype = {"bf16": torch.bfloat16, "fp16": torch.float16, "fp32": torch.float32}[plan.dtype]
        return {"transformer": transformer.to(dtype), "vae": vae.to(dtype), "scheduler": sched}

    def _encode_uncached(self, texts, plan):
        self.encodes = getattr(self, "encodes", 0) + len(texts)
        out = []
        for t in texts:
            g = torch.Generator().manual_seed(abs(hash(t)) % 10_000)
            out.append((torch.randn(128, CAPTION, generator=g), torch.ones(128, dtype=torch.bool)))
        return out


@pytest.fixture()
def engine(tmp_path):
    paths = Paths(tmp_path / "data").ensure()
    eng = TinyEngine(paths, SettingsStore(paths.settings_file), StubDownloads(), lambda: system(0))
    eng.settings.update({"compute_dtype": "fp32"})
    return eng


def req(**kw) -> GenRequest:
    d = dict(mode="t2v", prompt="a red fox in snow", negative_prompt="", width=64, height=64, frames=9, fps=8,
             steps=8, guidance=1.0, seed=7, model_id="ltxv-2b-distilled")
    d.update(kw)
    return GenRequest(**d)


def ctx() -> tuple[JobContext, list]:
    job = Job(id="j", kind="generate", title="t", lane="gpu")
    seen = []
    c = JobContext(job)
    orig = c.update
    c.update = lambda progress=None, phase=None: (seen.append((progress, phase)), orig(progress, phase))[1]  # type: ignore[method-assign]
    return c, seen


def test_text_to_video_writes_a_playable_clip_with_requested_frames(engine, tmp_path):
    c, seen = ctx()
    out = tmp_path / "o.mp4"
    meta = engine.generate(req(), out, c)
    info = probe(out)
    assert (info.width, info.height) == (64, 64)
    assert info.duration == pytest.approx(9 / 8, abs=0.15)
    assert meta["strategy"].startswith("CPU")
    steps = [p for p, ph in seen if ph and ph.startswith("Creating frames, step")]
    assert len(steps) == 8 and steps == sorted(steps)  # progress is monotonic and covers all 8 distilled steps


def test_same_seed_is_reproducible_and_different_seed_differs(engine, tmp_path):
    def frames_of(seed, name):
        out = tmp_path / name
        engine.generate(req(seed=seed), out, ctx()[0])
        import subprocess
        from ltxps.system import ffmpeg_path
        raw = subprocess.run([ffmpeg_path(), "-v", "error", "-i", str(out), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
        return np.frombuffer(raw, dtype=np.uint8)

    a, b, c_ = frames_of(1, "a.mp4"), frames_of(1, "b.mp4"), frames_of(2, "c.mp4")
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c_)


def test_prompt_embedding_is_cached_so_the_text_encoder_runs_once(engine, tmp_path):
    engine.generate(req(), tmp_path / "1.mp4", ctx()[0])
    engine.generate(req(seed=99), tmp_path / "2.mp4", ctx()[0])
    assert engine.encodes == 1
    engine.generate(req(prompt="something else"), tmp_path / "3.mp4", ctx()[0])
    assert engine.encodes == 2


def test_image_to_video_uses_the_starting_image(engine, tmp_path, media):
    out = tmp_path / "i2v.mp4"
    engine.generate(req(mode="i2v", image_path=media["image"]), out, ctx()[0])
    assert probe(out).duration > 0.5


def test_image_to_video_without_an_image_is_a_clear_error(engine, tmp_path):
    with pytest.raises(UserFacingError, match="starting image"):
        engine.generate(req(mode="i2v"), tmp_path / "x.mp4", ctx()[0])


def test_non_distilled_model_runs_with_guidance_and_negative_prompt(engine, tmp_path):
    out = tmp_path / "g.mp4"
    engine.generate(req(model_id="ltxv-2b-091", steps=3, guidance=3.0, negative_prompt="blurry"), out, ctx()[0])
    assert engine.encodes == 2  # prompt + negative prompt
    assert probe(out).duration > 0.5


def test_cancel_stops_between_steps_and_leaves_no_output(engine, tmp_path):
    c, _ = ctx()
    orig = c.update

    def cancel_on_step_three(progress=None, phase=None):
        orig(progress, phase)
        if phase and "step 3 of" in phase:
            c.cancel.set()

    c.update = cancel_on_step_three  # type: ignore[method-assign]
    out = tmp_path / "c.mp4"
    with pytest.raises(JobCancelled):
        engine.generate(req(), out, c)
    assert not out.exists()


def test_model_is_reloaded_only_when_needed_if_kept_loaded(engine, tmp_path):
    engine.settings.update({"keep_loaded": True})
    engine.generate(req(), tmp_path / "1.mp4", ctx()[0])
    engine.generate(req(seed=2), tmp_path / "2.mp4", ctx()[0])
    assert engine.loads == 1


def test_pipeline_is_dropped_after_each_job_by_default(engine, tmp_path):
    engine.generate(req(), tmp_path / "1.mp4", ctx()[0])
    engine.generate(req(seed=2), tmp_path / "2.mp4", ctx()[0])
    assert engine.loads == 2 and engine._pipe is None


def test_missing_models_give_an_actionable_error(tmp_path):
    paths = Paths(tmp_path / "d").ensure()

    class Missing:
        def is_installed(self, item_id):
            return item_id != BASE_ID

    eng = TinyEngine(paths, SettingsStore(paths.settings_file), Missing(), lambda: system(0))
    with pytest.raises(UserFacingError, match="Settings > Models"):
        eng.generate(req(), tmp_path / "x.mp4", ctx()[0])


# ------------------------------------------------------------------ fallback chain
class FlakyEngine(TinyEngine):
    """Fails the first attempts in scripted ways, to prove the escalation order."""

    def __init__(self, *a, script, **k):
        super().__init__(*a, **k)
        self.script = list(script)
        self.tried: list[tuple] = []

    def _run(self, req, spec, plan, out_path, ctx):
        self.tried.append((plan.mode, plan.dtype))
        outcome = self.script.pop(0) if self.script else "ok"
        if outcome == "oom":
            raise RuntimeError("CUDA out of memory. Tried to allocate 1 GiB")
        if outcome == "nan":
            raise NanOutput()
        return {}


def gpu_engine(tmp_path, script, cap=(7, 5)):
    paths = Paths(tmp_path / "d").ensure()
    return FlakyEngine(paths, SettingsStore(paths.settings_file), StubDownloads(), lambda: system(4096, cap=cap), script=script)


def test_oom_escalates_to_the_next_memory_mode_without_retrying_the_same_mode(tmp_path):
    eng = gpu_engine(tmp_path, ["oom", "ok"])
    meta = eng.generate(req(), tmp_path / "o.mp4", ctx()[0])
    assert eng.tried == [("model", "fp16"), ("group", "fp16")]
    assert "streamed block groups" in meta["strategy"]


def test_nan_output_retries_the_same_mode_with_bf16(tmp_path):
    eng = gpu_engine(tmp_path, ["nan", "ok"])
    eng.generate(req(), tmp_path / "o.mp4", ctx()[0])
    assert eng.tried == [("model", "fp16"), ("model", "bf16")]


def test_every_strategy_out_of_memory_gives_a_helpful_message(tmp_path):
    eng = gpu_engine(tmp_path, ["oom"] * 10)
    with pytest.raises(UserFacingError, match="ran out of memory"):
        eng.generate(req(), tmp_path / "o.mp4", ctx()[0])
    assert [m for m, _ in eng.tried] == ["model", "group", "sequential"]


def test_persistent_nan_explains_precision(tmp_path):
    eng = gpu_engine(tmp_path, ["nan"] * 10)
    with pytest.raises(UserFacingError, match="blank frames"):
        eng.generate(req(), tmp_path / "o.mp4", ctx()[0])


def test_catalog_has_the_supported_models_and_all_profiles_exist():
    assert set(MODELS) == {"ltxv-2b-distilled", "ltxv-2b-091"}
    assert set(PROFILES) == {"cpu", "lite", "balanced", "quality"}


@pytest.mark.parametrize("dtype", ["bf16", "fp16"])
def test_reduced_precision_with_8bit_weight_storage_matches_cached_embedding_dtype(tmp_path, dtype):
    """Regression: bf16 prompt-cache vs fp16 transformer crashed with 'mat1 and mat2 must have the same dtype'."""
    paths = Paths(tmp_path / "d").ensure()
    eng = TinyEngine(paths, SettingsStore(paths.settings_file), StubDownloads(), lambda: system(0))
    plan = MemoryPlan("cpu", dtype, True, "none", True)
    eng.settings.update({"compute_dtype": dtype, "keep_loaded": True})
    # Force the fp8 path on CPU to exercise enable_layerwise_casting with the real class.
    import ltxps.engine.ltxv as mod

    orig = mod.build_plans
    mod.build_plans = lambda *a, **k: [plan]
    try:
        out = tmp_path / "o.mp4"
        try:
            eng.generate(req(), out, ctx()[0])
        except RuntimeError as exc:
            if "not implemented for" in str(exc) or "not supported" in str(exc).lower():
                pytest.skip(f"this CPU build lacks {dtype} kernels: {exc}")
            raise
        assert probe(out).duration > 0.5
        stored = {str(p.dtype) for p in eng._pipe.transformer.parameters()}
        assert "torch.float8_e4m3fn" in stored  # weights really are stored in 8 bits
    finally:
        mod.build_plans = orig


def test_six_gb_card_gets_the_lite_profile():
    for mb in (6141, 6144, 7000):
        assert pick_profile(system(mb)).id == "lite"
    assert pick_profile(system(8192)).id == "balanced"


# ------------------------------------------------------------------ 1.2.11: GPU arch compatibility and time estimate
def test_rtx40_is_supported_by_a_build_without_sm89():
    from ltxps.system import arch_is_supported

    cu130 = ["sm_75", "sm_80", "sm_86", "sm_90", "sm_100", "sm_120"]
    assert arch_is_supported(cu130, (8, 9))  # RTX 4050/4060/4070/4090 run the sm_86 / sm_80 machine code
    assert arch_is_supported(cu130, (8, 6))
    assert not arch_is_supported(["sm_90", "sm_100"], (8, 9))  # a newer-only build really cannot run an older card
    assert not arch_is_supported(["sm_80"], (7, 5))
    assert arch_is_supported(["sm_80", "compute_80"], (9, 0))  # PTX forward compatibility


def test_estimate_is_minutes_on_gpu_and_hours_on_cpu():
    from ltxps.catalog import MODELS
    from ltxps.estimate import estimate

    m = MODELS["ltxv-2b-distilled"]
    s_gpu = system(6144, cap=(8, 9))
    lite = pick_profile(s_gpu)
    fast = estimate(s_gpu, lite, m, 384, 256, 33)
    assert fast.device == "gpu" and fast.seconds < 600 and fast.band in ("fast", "ok")
    s_cpu = system(0)
    cpu = estimate(s_cpu, pick_profile(s_cpu), m, 384, 256, 33)
    assert cpu.device == "cpu" and cpu.seconds > fast.seconds * 4
    assert any("CPU" in n for n in cpu.notes)
    big = estimate(s_cpu, pick_profile(s_cpu), MODELS["ltxv-2b-091"], 384, 256, 33)
    assert big.band == "too_long" and big.tips


def test_usage_sample_and_diagnosis():
    from ltxps import usage

    s = usage.sample()
    assert {"cpu", "ram_used_gb", "gpu", "vram_used_gb"} <= set(s)
    spill = {"gpu": 40, "cpu": 20, "vram_used_gb": 5.9, "vram_total_gb": 6.0, "ram_used_gb": 21.0, "ram_total_gb": 23.7}
    assert "Lite" in (usage.diagnose(spill, 600, 200) or "")
    cpu_run = {"gpu": 2, "cpu": 95, "vram_used_gb": 0.3, "vram_total_gb": 6.0, "ram_used_gb": 12.0, "ram_total_gb": 23.7}
    assert "CPU" in (usage.diagnose(cpu_run, 600, 200) or "")
    assert usage.diagnose(cpu_run, 30, 200) is None
