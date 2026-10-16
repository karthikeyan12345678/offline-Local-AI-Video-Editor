"""HTTP API. Thin: validation and wiring only; work happens in services and jobs."""

import random
import re
import shutil
import time
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from .. import __version__
from ..catalog import AUX, BASE_ID, MODELS
from ..db import Asset, new_id
from ..editor import ai, audiofx, chat as editor_chat, effects, fonts, ops
from ..editor.media import FfmpegError, run_ffmpeg
from ..editor.project import TEXT_ANIM_IN, TEXT_ANIM_OUT, ExportOptions, Project
from ..editor.render import AssetRef, PlanError, build_plan
from .. import updates
from ..engine.base import GenRequest
from ..jobs import JobContext, UserFacingError
from ..assistant import llm
from ..library import SUPPORTED, safe_name
from ..profiles import PROFILES, LimitError, pick_profile, validate_request
from ..setup_plan import build_plan as build_setup_plan
from ..state import AppState


def make_router(state: AppState, assistant: Any = None) -> APIRouter:
    def auth(request: Request) -> None:
        supplied = request.headers.get("authorization", "").removeprefix("Bearer ").strip() or request.query_params.get("t", "")
        if supplied != state.token:
            raise HTTPException(401, "Not authorised")

    router = APIRouter(prefix="/api", dependencies=[Depends(auth)])

    # ------------------------------------------------------------------ system
    @router.get("/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "version": __version__}

    @router.get("/system")
    def system(refresh: bool = False) -> dict[str, Any]:
        info = state.system(refresh)
        st = state.settings.get()
        profile = pick_profile(info, st.profile)
        gpu = info.gpu
        return {
            "version": __version__,
            "os": info.os,
            "cpu_count": info.cpu_count,
            "ram_gb": round(info.ram_mb / 1024, 1),
            "gpu": {
                "available": gpu.available,
                "name": gpu.name,
                "vram_gb": gpu.vram_gb,
                "compute_capability": list(gpu.compute_capability) if gpu.compute_capability else None,
                "arch_supported": gpu.arch_supported,
                "problem": gpu.problem,
            },
            "torch": info.torch_version,
            "ffmpeg": bool(info.ffmpeg),
            "warnings": info.warnings,
            "profile": profile.id,
            "disk_free_gb": state.disk_free_gb(),
            "data_dir": str(state.paths.root),
            "requires_models": state.requires_models,
            "low_ram": 0 < info.ram_mb < 12000,
        }

    @router.get("/settings")
    def get_settings() -> dict[str, Any]:
        return vars(state.settings.get())

    class SettingsPatch(BaseModel):
        profile: Literal["auto", "cpu", "lite", "balanced", "quality"] | None = None
        memory_mode: Literal["auto", "none", "model", "group", "sequential"] | None = None
        hf_endpoint: str | None = Field(None, pattern=r"^https?://[^\s]+$")
        default_model: str | None = None
        compute_dtype: Literal["auto", "bf16", "fp16", "fp32"] | None = None
        keep_loaded: bool | None = None
        output_fps: int | None = Field(None, ge=8, le=60)

    @router.put("/settings")
    def put_settings(patch: SettingsPatch) -> dict[str, Any]:
        data = patch.model_dump(exclude_none=True)
        if "default_model" in data and data["default_model"] not in MODELS:
            raise HTTPException(422, "Unknown model")
        if "hf_endpoint" in data:
            data["hf_endpoint"] = data["hf_endpoint"].rstrip("/")
        updated = vars(state.settings.update(data))
        state.engine.unload()
        return updated

    @router.get("/limits")
    def limits() -> dict[str, Any]:
        info = state.system()
        st = state.settings.get()
        prof = pick_profile(info, st.profile)
        return {
            "profile": {
                "id": prof.id, "label": prof.label, "description": prof.description,
                "max_frames": prof.max_frames, "max_side": prof.max_side, "max_tokens": prof.max_tokens,
                "default_width": prof.default_width, "default_height": prof.default_height, "default_frames": prof.default_frames,
                "resolutions": [{"label": l, "width": w, "height": h} for l, w, h in prof.resolutions],
            },
            "profiles": [{"id": p.id, "label": p.label, "description": p.description} for p in PROFILES.values()],
            "models": [
                {"id": m.id, "label": m.label, "note": m.note, "distilled": m.distilled, "default_steps": m.default_steps,
                 "default_guidance": m.default_guidance, "min_steps": m.min_steps, "max_steps": m.max_steps}
                for m in MODELS.values()
            ],
            "default_model": st.default_model,
            "fps": st.output_fps,
        }

    # ------------------------------------------------------------------ models
    def model_row(item_id: str, label: str, note: str, kind: str) -> dict[str, Any]:
        dl = state.downloads.state(item_id)
        return {
            "id": item_id, "label": label, "note": note, "kind": kind,
            "installed": state.downloads.is_installed(item_id),
            "installed_bytes": state.downloads.installed_bytes(item_id),
            "download": {"status": dl.status, "total": dl.total, "done": dl.done, "speed": dl.speed, "current": dl.current, "error": dl.error},
        }

    @router.get("/models")
    def list_models() -> dict[str, Any]:
        rows = [model_row(BASE_ID, "Text encoder and tokenizer", "Shared by all LTX-Video models. Required.", "base")]
        rows += [model_row(m.id, m.label, m.note, "model") for m in MODELS.values()]
        rows += [model_row(a.id, a.label, a.note, a.kind) for a in AUX.values()]
        return {"items": rows, "endpoint": state.settings.get().hf_endpoint}

    def setup_plan() -> dict[str, Any]:
        info = state.system()
        g = info.gpu
        gpu_ok = bool(g.available and g.arch_supported is not False)
        return build_setup_plan(ram_gb=round(info.ram_mb / 1024, 1), vram_gb=round(g.vram_mb / 1024, 1) if g.available else 0, gpu_ok=gpu_ok,
                                disk_free_gb=state.disk_free_gb(), default_model=state.settings.get().default_model, is_installed=state.downloads.is_installed)

    @router.get("/setup/plan")
    def get_setup_plan() -> dict[str, Any]:
        return setup_plan()

    @router.post("/setup/install")
    def run_setup_install() -> dict[str, Any]:
        plan = setup_plan()
        for it in plan["items"]:
            if not it["installed"] and state.downloads.state(it["id"]).status not in ("running", "queued"):
                state.downloads.start(it["id"])
        return plan

    def known_item(item_id: str) -> str:
        if item_id != BASE_ID and item_id not in MODELS and item_id not in AUX:
            raise HTTPException(404, "Unknown model")
        return item_id

    @router.post("/models/{item_id}/probe")
    def probe_model(item_id: str) -> dict[str, Any]:
        known_item(item_id)
        try:
            return {"bytes": state.downloads.probe_size(item_id)}
        except Exception as exc:  # noqa: BLE001 - network failures of any kind become a readable message
            raise HTTPException(502, f"Could not reach the model server: {exc}") from exc

    @router.post("/models/{item_id}/download")
    def download_model(item_id: str) -> dict[str, Any]:
        known_item(item_id)
        state.downloads.start(item_id)
        return model_row(item_id, "", "", "")

    @router.post("/models/{item_id}/cancel")
    def cancel_download(item_id: str) -> dict[str, bool]:
        known_item(item_id)
        state.downloads.cancel(item_id)
        return {"ok": True}

    @router.delete("/models/{item_id}")
    def delete_model(item_id: str) -> dict[str, bool]:
        known_item(item_id)
        state.engine.unload()
        state.downloads.delete(item_id)
        return {"ok": True}

    # ------------------------------------------------------------------ generation
    class GenerateBody(BaseModel):
        mode: Literal["t2v", "i2v"] = "t2v"
        prompt: str = Field(min_length=1, max_length=4000)
        negative_prompt: str = Field("", max_length=2000)
        width: int = Field(512, ge=64, le=2048)
        height: int = Field(320, ge=64, le=2048)
        frames: int = Field(49, ge=9, le=513)
        fps: int | None = Field(None, ge=8, le=60)
        steps: int | None = Field(None, ge=1, le=100)
        guidance: float | None = Field(None, ge=1, le=10)
        seed: int = -1
        model_id: str | None = None
        image_asset_id: str | None = None
        unlock_limits: bool = False

    def build_request(body: GenerateBody, image_path: Path | None) -> GenRequest:
        st = state.settings.get()
        model_id = body.model_id or st.default_model
        spec = MODELS.get(model_id)
        if spec is None:
            raise HTTPException(422, "Unknown model")
        profile = pick_profile(state.system(), st.profile)
        try:
            w, h, f = validate_request(profile, body.width, body.height, body.frames, body.unlock_limits)
        except LimitError as exc:
            raise HTTPException(422, str(exc)) from exc
        steps = spec.default_steps if spec.distilled else min(max(body.steps or spec.default_steps, spec.min_steps), spec.max_steps)
        guidance = spec.default_guidance if spec.distilled else (body.guidance or spec.default_guidance)
        seed = body.seed if body.seed >= 0 else random.randint(0, 2**31 - 1)
        return GenRequest(
            mode=body.mode, prompt=body.prompt.strip(), negative_prompt=body.negative_prompt.strip(), width=w, height=h, frames=f,
            fps=body.fps or st.output_fps, steps=steps, guidance=guidance, seed=seed, model_id=model_id, image_path=image_path,
        )

    def submit_generation(req: GenRequest, title: str, extra_meta: dict[str, Any]) -> dict[str, Any]:
        def run(ctx: JobContext) -> dict[str, Any]:
            out = state.paths.outputs / f"{time.strftime('%Y%m%d-%H%M%S')}_{new_id()[:6]}_{safe_name(req.prompt)[:30]}.mp4"
            ctx.update(0.01, "Starting")
            info = state.engine.generate(req, out, ctx)
            ctx.update(0.97, "Adding to your library")
            asset = state.library.register(
                out, "generated", name=title,
                meta={
                    "prompt": req.prompt, "negative_prompt": req.negative_prompt, "seed": req.seed, "model": req.model_id,
                    "steps": req.steps, "guidance": req.guidance, "mode": req.mode, "frames": req.frames, **info, **extra_meta,
                },
            )
            return {"asset_id": asset.id}

        job = state.jobs.submit("generate", title, run, lane="gpu")
        return job.to_json()

    def title_of(prompt: str) -> str:
        t = re.sub(r"\s+", " ", prompt).strip()
        return (t[:48] + "…") if len(t) > 48 else t

    @router.post("/generate")
    def generate(body: GenerateBody) -> dict[str, Any]:
        image_path = None
        if body.mode == "i2v":
            asset = state.db.get_asset(body.image_asset_id or "")
            if asset is None or asset.kind != "image":
                raise HTTPException(422, "Choose an image from your library as the starting frame.")
            image_path = Path(asset.path)
        req = build_request(body, image_path)
        return submit_generation(req, title_of(body.prompt), {"image_asset_id": body.image_asset_id} if image_path else {})

    class ExtendBody(GenerateBody):
        source_asset_id: str
        mode: Literal["t2v", "i2v"] = "i2v"
        image_asset_id: str | None = None

    @router.post("/generate/extend")
    def extend(body: ExtendBody) -> dict[str, Any]:
        """Continues a clip: its last frame becomes the starting image for a new clip."""
        src = state.db.get_asset(body.source_asset_id)
        if src is None or src.kind != "video":
            raise HTTPException(422, "Choose a video from your library to continue.")
        frame = state.paths.imports / f"{new_id()}_lastframe.png"
        try:
            ops.run_tool("extract_frame", src, {"time": "last"}, frame)
        except (ops.ToolError, FfmpegError) as exc:
            raise HTTPException(422, str(exc)) from exc
        body.mode = "i2v"
        req = build_request(body, frame)
        return submit_generation(req, "Continues: " + title_of(body.prompt), {"continues": src.id})

    # ------------------------------------------------------------------ jobs
    @router.get("/jobs")
    def list_jobs() -> list[dict[str, Any]]:
        return [j.to_json() for j in state.jobs.list()]

    @router.get("/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        job = state.jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "Unknown job")
        return job.to_json()

    @router.post("/jobs/{job_id}/cancel")
    def cancel_job(job_id: str) -> dict[str, bool]:
        return {"ok": state.jobs.cancel(job_id)}

    # ------------------------------------------------------------------ assets
    @router.get("/assets")
    def list_assets(kind: str | None = None, source: str | None = None) -> list[dict[str, Any]]:
        items = state.db.list_assets(kind=kind, source=source)
        if source is None:
            items = [a for a in items if a.source != "preview"]
        return [a.to_json() for a in items]

    @router.post("/assets/upload")
    async def upload(file: UploadFile = File(...)) -> dict[str, Any]:
        name = file.filename or "upload"
        ext = Path(name).suffix.lower()
        if ext not in SUPPORTED:
            raise HTTPException(422, f"'{ext or 'This file type'}' is not a supported video, audio or image format.")
        dest = state.paths.imports / f"{new_id()}_{safe_name(name)}{ext}"
        with open(dest, "wb") as fh:
            while chunk := await file.read(1024 * 1024):
                fh.write(chunk)
        try:
            asset = state.library.register(dest, "import", Path(name).stem)
        except UserFacingError as exc:
            dest.unlink(missing_ok=True)
            raise HTTPException(422, str(exc)) from exc
        return asset.to_json()

    def asset_or_404(asset_id: str) -> Asset:
        a = state.db.get_asset(asset_id)
        if a is None or not Path(a.path).exists():
            raise HTTPException(404, "That file is no longer available.")
        return a

    @router.get("/assets/{asset_id}/file")
    def asset_file(asset_id: str) -> FileResponse:
        a = asset_or_404(asset_id)
        return FileResponse(a.path)  # Starlette serves HTTP Range requests, so seeking works

    @router.get("/assets/{asset_id}/thumb")
    def asset_thumb(asset_id: str) -> FileResponse:
        a = state.db.get_asset(asset_id)
        if a is None or not a.thumb or not Path(a.thumb).exists():
            raise HTTPException(404, "No thumbnail")
        return FileResponse(a.thumb, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})

    @router.get("/assets/{asset_id}/download")
    def asset_download(asset_id: str) -> FileResponse:
        a = asset_or_404(asset_id)
        ext = Path(a.path).suffix
        return FileResponse(a.path, filename=f"{safe_name(a.name)}{ext}")

    class RenameBody(BaseModel):
        name: str = Field(min_length=1, max_length=120)

    @router.patch("/assets/{asset_id}")
    def rename_asset(asset_id: str, body: RenameBody) -> dict[str, bool]:
        asset_or_404(asset_id)
        state.db.rename_asset(asset_id, body.name.strip())
        return {"ok": True}

    @router.delete("/assets/{asset_id}")
    def delete_asset(asset_id: str) -> dict[str, bool]:
        return {"ok": state.library.remove(asset_id)}

    # ------------------------------------------------------------------ editor
    @router.get("/editor/tools")
    def tool_list() -> list[dict[str, Any]]:
        return [{"id": t.id, "label": t.label, "description": t.description, "accepts": list(t.accepts)} for t in ops.TOOLS.values()]

    class ToolBody(BaseModel):
        asset_id: str
        params: dict[str, Any] = Field(default_factory=dict)

    @router.post("/editor/tools/{tool}")
    def run_tool(tool: str, body: ToolBody) -> dict[str, Any]:
        spec = ops.TOOLS.get(tool)
        if spec is None:
            raise HTTPException(404, "Unknown tool")
        asset = asset_or_404(body.asset_id)
        if asset.kind not in spec.accepts:
            raise HTTPException(422, f"'{spec.label}' works on {' or '.join(spec.accepts)} files.")

        def run(ctx: JobContext) -> dict[str, Any]:
            dest = state.paths.renders / f"{new_id()}_{tool}.{ops.output_ext(tool, body.params)}"
            ctx.update(0.02, f"{spec.label}…")
            try:
                ops.run_tool(tool, asset, body.params, dest, lambda p: ctx.update(p), ctx.cancel)
            except ops.ToolError as exc:
                raise UserFacingError(str(exc)) from exc
            made = state.library.register(dest, "edit", f"{asset.name} · {spec.label.lower()}", {"tool": tool, "from": asset.id})
            return {"asset_id": made.id}

        return state.jobs.submit("tool", f"{spec.label}: {asset.name}", run, lane="media").to_json()

    class ExportBody(BaseModel):
        project: Project
        options: ExportOptions = Field(default_factory=ExportOptions)

    @router.post("/editor/export")
    def export(body: ExportBody) -> dict[str, Any]:
        project, opts = body.project, body.options
        assets: dict[str, AssetRef] = {}
        for ref in [c.asset_id for c in project.clips] + [a.asset_id for a in project.audio]:
            a = state.db.get_asset(ref)
            if a is None or not Path(a.path).exists():
                raise HTTPException(422, "A file used by this project is no longer in the library.")
            assets[ref] = AssetRef(Path(a.path), a.kind, a.duration, a.has_audio, a.width, a.height)

        label = "Preview" if opts.preview else "Export"
        title = f"{label}: {project.name}"
        ext = opts.format

        def run(ctx: JobContext) -> dict[str, Any]:
            out = state.paths.renders / f"{new_id()}_{safe_name(project.name)}.{ext}"
            work = state.paths.cache / f"render_{new_id()}"
            try:
                plan = build_plan(project, assets, opts, out, work)
            except PlanError as exc:
                raise UserFacingError(str(exc)) from exc
            ctx.update(0.01, "Rendering")
            run_ffmpeg(plan.args, plan.total, lambda p: ctx.update(0.01 + 0.98 * p, f"Rendering {int(p * 100)}%"), ctx.cancel)
            shutil.rmtree(work, ignore_errors=True)
            made = state.library.register(
                out, "preview" if opts.preview else "export", f"{project.name}" + (" (preview)" if opts.preview else ""),
                {"warnings": plan.warnings},
            )
            return {"asset_id": made.id, "warnings": plan.warnings}

        return state.jobs.submit("export", title, run, lane="media").to_json()

    # ------------------------------------------------------------------ editor: catalog and fonts
    @router.get("/editor/catalog")
    def editor_catalog() -> dict[str, Any]:
        return {
            "transitions": [{"id": i, "label": l, "group": g} for i, l, g in effects.TRANSITION_INFO],
            "looks": [{"id": i, "label": effects.PRESET_LABELS.get(i, i)} for i in effects.FILTER_PRESETS],
            "effects": [{"id": i, "label": l} for i, l in effects.EFFECT_INFO],
            "motions": [{"id": i, "label": l} for i, l in effects.MOTION_INFO],
            "audio_fx": [{"id": i, "label": l, "group": g} for i, l, g in audiofx.AUDIO_FX_INFO],
            "fonts": [{"id": f.id, "label": f.label, "category": f.category, "scripts": list(f.scripts), "bold": bool(f.bold) or f.variable} for f in fonts.catalog().values()],
            "text_anim_in": list(TEXT_ANIM_IN),
            "text_anim_out": list(TEXT_ANIM_OUT),
            "whisper": [{"id": a.id, "label": a.label, "installed": state.downloads.is_installed(a.id)} for a in AUX.values()],
        }

    @router.get("/editor/fonts/sample")
    def font_sample(font: str = "", text: str = Query("Aa Abc", max_length=60), bold: bool = False, height: int = Query(44, ge=16, le=120)) -> Response:
        import io

        buf = io.BytesIO()
        fonts.sample_png(font, text, bold, height).save(buf, "PNG")
        return Response(buf.getvalue(), media_type="image/png", headers={"Cache-Control": "max-age=86400"})

    @router.get("/editor/fonts/{font_id}/file")
    def font_file(font_id: str, bold: bool = False) -> FileResponse:
        e = fonts.catalog().get(font_id)
        if e is None:
            raise HTTPException(404, "Unknown font")
        return FileResponse(e.path(bold), media_type="font/ttf", headers={"Cache-Control": "max-age=86400"})

    # ------------------------------------------------------------------ editor: AI
    class AIBody(BaseModel):
        asset_id: str
        trim_in: float = Field(0, ge=0)
        trim_out: float = Field(0, ge=0)  # 0 = to the end
        options: dict[str, Any] = Field(default_factory=dict)

    def ai_asset(body: AIBody, kinds: tuple[str, ...]) -> tuple[Asset, float, float]:
        a = asset_or_404(body.asset_id)
        if a.kind not in kinds:
            raise HTTPException(422, f"This works on {' or '.join(kinds)} files.")
        end = body.trim_out if body.trim_out > 0 else a.duration
        end = min(end, a.duration) if a.duration > 0 else end
        return a, body.trim_in, max(0.1, end - body.trim_in)

    def ai_job(kind: str, title: str, fn) -> dict[str, Any]:
        def run(ctx: JobContext) -> dict[str, Any]:
            try:
                return fn(ctx)
            except (ai.AIError, FfmpegError) as exc:
                if ctx.cancel.is_set():
                    raise
                raise UserFacingError(str(exc)) from exc

        return state.jobs.submit(kind, title, run, lane="media").to_json()

    @router.post("/editor/ai/follow")
    def ai_follow(body: AIBody) -> dict[str, Any]:
        a, start, dur = ai_asset(body, ("video",))
        return ai_job("ai", f"Follow person: {a.name}", lambda ctx: ai.follow_person(str(a.path), start, dur, lambda p: ctx.update(p, f"Tracking {int(p * 100)}%"), ctx.cancel))

    @router.post("/editor/ai/silence")
    def ai_silence(body: AIBody) -> dict[str, Any]:
        a, start, dur = ai_asset(body, ("video", "audio"))
        o = body.options

        def run(ctx: JobContext) -> dict[str, Any]:
            ctx.update(0.1, "Listening")
            r = ai.silence_cuts(str(a.path), a.duration or dur, float(o.get("noise_db", -35)), float(o.get("min_silence", 0.6)), cancel=ctx.cancel)
            keep = [[max(s, start), min(e, start + dur)] for s, e in r["keep"] if e > start and s < start + dur]
            return {**r, "keep": [k for k in keep if k[1] - k[0] > 0.15]}

        return ai_job("ai", f"Find silences: {a.name}", run)

    @router.post("/editor/ai/scenes")
    def ai_scenes(body: AIBody) -> dict[str, Any]:
        a, start, dur = ai_asset(body, ("video",))
        thr = float(body.options.get("threshold", 0.35))
        return ai_job("ai", f"Find scenes: {a.name}", lambda ctx: ai.scene_cuts(str(a.path), a.duration, thr, cancel=ctx.cancel))

    @router.post("/editor/ai/beats")
    def ai_beats(body: AIBody) -> dict[str, Any]:
        a, _, _ = ai_asset(body, ("audio", "video"))
        return ai_job("ai", f"Find the beat: {a.name}", lambda ctx: ai.beat_times(str(a.path)))

    @router.post("/editor/ai/enhance")
    def ai_enhance(body: AIBody) -> dict[str, Any]:
        a, start, dur = ai_asset(body, ("video", "image"))
        try:
            if a.kind == "image":
                return ai.auto_enhance(str(a.path), 0.0, 1.0)
            return ai.auto_enhance(str(a.path), start + dur / 2, a.duration)
        except (ai.AIError, FfmpegError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post("/editor/ai/captions")
    def ai_captions(body: AIBody) -> dict[str, Any]:
        a, start, dur = ai_asset(body, ("video", "audio"))
        size = str(body.options.get("model", "base"))
        if f"whisper-{size}" not in AUX:
            raise HTTPException(422, "Unknown captions model.")
        mdir = state.paths.models / f"whisper-{size}"
        if not state.downloads.is_installed(f"whisper-{size}"):
            raise HTTPException(409, f"Download the captions model 'Whisper {size}' first (Models page).")
        lang = str(body.options.get("language", "")) or None
        return ai_job("ai", f"Captions: {a.name}", lambda ctx: ai.transcribe(str(a.path), mdir, lang, lambda p: ctx.update(p, f"Listening {int(p * 100)}%"), ctx.cancel, start, dur))

    @router.get("/editor/ai/voices")
    def ai_voices() -> dict[str, Any]:
        return {"voices": ai.tts_voices()}

    class SpeakBody(BaseModel):
        text: str = Field(min_length=1, max_length=5000)
        voice: str = ""
        rate: int = Field(0, ge=-10, le=10)

    @router.post("/editor/ai/speak")
    def ai_speak(body: SpeakBody) -> dict[str, Any]:
        def run(ctx: JobContext) -> dict[str, Any]:
            dest = state.paths.renders / f"{new_id()}_voice.wav"
            ctx.update(0.2, "Speaking")
            ai.speak(body.text, dest, body.voice, body.rate)
            made = state.library.register(dest, "edit", "Voice-over: " + body.text[:40], {"tool": "tts"})
            return {"asset_id": made.id}

        return ai_job("ai", "Voice-over", run)

    # ------------------------------------------------------------------ editor: chat
    class ChatMsg(BaseModel):
        role: Literal["user", "assistant"]
        content: str = Field(max_length=6000)
        image_ids: list[str] = Field(default_factory=list, max_length=4)

    class ChatBody(BaseModel):
        messages: list[ChatMsg] = Field(min_length=1, max_length=30)
        project: Project

    @router.post("/editor/chat")
    def editor_chat_turn(body: ChatBody) -> dict[str, Any]:
        if assistant is None:
            raise HTTPException(503, "The chat helper is not available in this build.")
        cfg = assistant.llm_config()
        assets = {a.id: a for a in state.db.list_assets()}
        names = {i: a.name for i, a in assets.items()}
        durations = {i: a.duration for i, a in assets.items()}
        library = [a.name for a in assets.values() if a.kind in ("video", "audio", "image")]
        msgs: list[dict[str, Any]] = []
        n_img = 0
        last = len(body.messages) - 1
        for k, m in enumerate(body.messages):
            row: dict[str, Any] = {"role": m.role, "content": m.content}
            if m.role == "user" and k >= last - 1:  # pictures only travel with the newest messages
                imgs = []
                for iid in m.image_ids:
                    a = assets.get(iid)
                    if a and a.kind == "image" and Path(a.path).exists():
                        imgs.append(editor_chat.encode_image(Path(a.path)))
                if imgs:
                    row["images"] = imgs
                    n_img += len(imgs)
            msgs.append(row)
        system = editor_chat.system_prompt(editor_chat.describe(body.project, names, durations), library, n_img > 0)
        try:
            text = llm.complete(llm.LLMConfig(**{**cfg.__dict__, "temperature": 0.2, "max_tokens": 2048}), msgs, system)
        except llm.LLMError as exc:
            raise HTTPException(502, str(exc)) from exc
        parsed = editor_chat.parse_answer(text)
        out = editor_chat.apply_actions(body.project, parsed["actions"], names)
        return {"reply": parsed["reply"], "project": out["project"].model_dump(), "applied": out["applied"], "skipped": out["skipped"], "tasks": out["tasks"],
                "changed": bool(out["applied"]) and out["project"].model_dump() != body.project.model_dump()}

    @router.get("/editor/chat/status")
    def editor_chat_status() -> dict[str, Any]:
        if assistant is None:
            return {"ready": False, "why": "unavailable"}
        cfg = assistant.llm_config()
        p = llm.PRESETS.get(cfg.provider, {})
        needs = bool(p.get("needs_key")) and not cfg.api_key
        return {"ready": bool(cfg.base_url and cfg.model) and not needs, "provider": cfg.provider, "name": p.get("name", cfg.provider), "model": cfg.model,
                "why": "key" if needs else ("model" if not cfg.model else "")}

    # ------------------------------------------------------------------ updates
    @router.get("/updates")
    def updates_check() -> dict[str, Any]:
        try:
            return updates.check()
        except updates.UpdateError as exc:
            raise HTTPException(502, str(exc)) from exc

    history_file = state.paths.root / "module-history.json"

    def install_job(title: str, specs_fn) -> dict[str, Any]:
        def run(ctx: JobContext) -> dict[str, Any]:
            ctx.update(0.05, "Getting ready")
            seen = {"n": 0}

            def on_line(line: str) -> None:
                seen["n"] += 1
                ctx.update(min(0.9, 0.1 + seen["n"] / 400), line[:90])

            try:
                return specs_fn(ctx, on_line)
            except updates.UpdateError as exc:
                raise UserFacingError(str(exc)) from exc

        return state.jobs.submit("update", title, run, lane="media").to_json()

    @router.post("/updates/modules")
    def updates_install() -> dict[str, Any]:
        def go(ctx: JobContext, on_line) -> dict[str, Any]:
            before = {n: updates.installed_version(n) for n in updates.UPDATABLE}
            out = updates.update_modules(on_line=on_line, cancel=ctx.cancel)
            for n, v in before.items():
                if n in out.get("updated", []):
                    updates.remember_version(history_file, n, v)
            return out

        return install_job("Update AI modules", go)

    @router.get("/updates/modules")
    def updates_table() -> dict[str, Any]:
        rec: dict[str, str] = {}
        online = True
        try:
            for m in updates.fetch_manifest(updates.manifest_url()).get("modules", []):
                if isinstance(m, dict) and "name" in m and "version" in m:
                    rec[updates._norm(str(m["name"]))] = str(m["version"])
        except updates.UpdateError:
            online = False
        return {"online": online, "modules": updates.module_table(updates.read_history(history_file), recommended=rec)}

    @router.get("/updates/modules/{name}/versions")
    def updates_versions(name: str) -> dict[str, Any]:
        try:
            updates.valid_install(name, "1.0")
            return {"versions": updates.pypi_versions(name)}
        except updates.UpdateError as exc:
            raise HTTPException(502, str(exc)) from exc

    class PickBody(BaseModel):
        name: str = Field(max_length=60)
        version: str = Field(max_length=20)

    @router.post("/updates/modules/install")
    def updates_pick(body: PickBody) -> dict[str, Any]:
        try:
            spec = updates.valid_install(body.name, body.version)
        except updates.UpdateError as exc:
            raise HTTPException(422, str(exc)) from exc

        def go(ctx: JobContext, on_line) -> dict[str, Any]:
            before = updates.installed_version(body.name)
            updates.pip_install([spec], on_line, ctx.cancel)
            updates.remember_version(history_file, body.name, before)
            return {"updated": [body.name], "restart": True}

        return install_job(f"Install {body.name} {body.version}", go)

    # ------------------------------------------------------------------ projects
    @router.get("/projects")
    def list_projects() -> list[dict[str, Any]]:
        return state.db.list_projects()

    @router.get("/projects/{project_id}")
    def get_project(project_id: str) -> dict[str, Any]:
        data = state.db.get_project(project_id)
        if data is None:
            raise HTTPException(404, "Project not found")
        return data

    @router.put("/projects/{project_id}")
    def save_project(project_id: str, project: Project) -> dict[str, Any]:
        project.id = project_id
        state.db.save_project(project_id, project.name, project.model_dump())
        return {"ok": True}

    @router.delete("/projects/{project_id}")
    def delete_project(project_id: str) -> dict[str, bool]:
        state.db.delete_project(project_id)
        return {"ok": True}

    return router
