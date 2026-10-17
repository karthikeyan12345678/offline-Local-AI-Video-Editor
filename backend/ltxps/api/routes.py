"""HTTP API. Thin: validation and wiring only; work happens in services and jobs."""

import random
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from .. import __version__
from ..catalog import AUX, BASE_ID, MODELS
from ..db import Asset, new_id
from ..editor import ai, audiofx, budget as budget_mod, chat as editor_chat, effects, fonts, inpaint, localmotion, motion, ops, soundfx, soundtrack, voicecast
from ..editor.media import FfmpegError, run_ffmpeg
from ..editor.project import TEXT_ANIM_IN, TEXT_ANIM_OUT, ExportOptions, Project
from ..editor.render import AssetRef, PlanError, build_plan
from .. import finish, updates
from ..system import ffmpeg_path
from ..engine.base import GenRequest
from dataclasses import replace as dc_replace
from ..assistant import enhance as prompt_enhance
from ..jobs import JobContext, UserFacingError
from ..assistant import llm, service as assistant_service
from ..library import SUPPORTED, safe_name
from ..estimate import estimate as estimate_seconds
from ..profiles import PROFILES, LimitError, pick_profile, snap_frames, snap_side, validate_request
from .. import usage
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
        time_limit_min: int | None = Field(None, ge=0, le=720)
        tour_done: bool | None = None
        sharpen_output: bool | None = None
        auto_enhance: bool | None = None
        ai_upscale: bool | None = None

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

    @router.get("/estimate")
    def estimate_route(width: int = Query(512, ge=64, le=2048), height: int = Query(320, ge=64, le=2048), frames: int = Query(49, ge=9, le=513),
                       model_id: str = "", steps: int | None = Query(None, ge=1, le=100), end_image: bool = False) -> dict[str, Any]:
        info = state.system()
        st = state.settings.get()
        model = MODELS.get(model_id or st.default_model) or next(iter(MODELS.values()))
        est = estimate_seconds(info, pick_profile(info, st.profile), model, snap_side(width), snap_side(height), snap_frames(frames), steps,
                               has_end_image=end_image, keep_loaded_ready=False)
        out = est.to_json()
        out["limit_seconds"] = (st.time_limit_min or 0) * 60 or None
        return out

    @router.get("/usage")
    def usage_route(job_id: str = "") -> dict[str, Any]:
        s = usage.sample()
        job = state.jobs.get(job_id) if job_id else None
        if job and job.status == "running" and job.started:
            s["why_slow"] = usage.diagnose(s, time.time() - job.started, job.expected or None)
        return s

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
        present = g.available or g.vram_mb > 0
        usable = bool(g.available and g.arch_supported is not False)
        kw: dict[str, Any] = dict(ram_gb=round(info.ram_mb / 1024, 1), vram_gb=round(g.vram_mb / 1024, 1) if present else 0, gpu_ok=present, gpu_usable=usable, gpu_name=g.name if present else "",
                                  disk_free_gb=state.disk_free_gb(), default_model=state.settings.get().default_model, is_installed=state.downloads.is_installed, torch_version=info.torch_version)
        # Real sizes from the model server (cached, looked up in parallel); the built-in estimates are used when offline.
        ids = [it["id"] for it in build_setup_plan(**kw)["items"] if not it["installed"]]
        sizes: dict[str, int] = {}
        if ids:
            from concurrent.futures import ThreadPoolExecutor, wait

            def probe(i: str) -> None:
                try:
                    sizes[i] = state.downloads.probe_size(i)
                except Exception:  # noqa: BLE001 - offline or blocked: keep the estimate
                    pass

            ex = ThreadPoolExecutor(max_workers=len(ids))
            wait([ex.submit(probe, i) for i in ids], timeout=8)
            ex.shutdown(wait=False, cancel_futures=True)
        return build_setup_plan(**kw, sizes=sizes)

    @router.get("/setup/plan")
    def get_setup_plan() -> dict[str, Any]:
        return setup_plan()

    @router.post("/setup/install")
    def run_setup_install() -> dict[str, Any]:
        plan = setup_plan()
        for it in plan["items"]:
            if not it["installed"] and state.downloads.state(it["id"]).status not in ("probing", "downloading"):
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
    class SoundBody(BaseModel):
        """Sound and voice added after a video is made (or to an existing video)."""
        narration: str = Field("", max_length=3000)
        voice: str = ""
        rate: int = Field(0, ge=-10, le=10)
        ambience: str = "auto"  # auto | none | waves | rain | wind | fire | city | night | space | calm
        music: bool = False
        level: float = Field(0.5, ge=0, le=1)
        persona: Literal["auto", "girl", "boy", "woman", "man", "old_woman", "old_man"] = "auto"  # who is speaking: shapes the voice (child, middle age, old)

    def resolve_persona(persona: str, text: str, image: Path | None) -> str:
        """The speaker to use: the one chosen; otherwise what the picture shows (when a picture-reading AI is connected), otherwise what the words say."""
        if persona in voicecast.PERSONAS:
            return persona
        seen = None
        if image is not None and assistant is not None:
            seen = voicecast.persona_from_vision(lambda q: assistant_service.ask_about_image(assistant, image, q))
        return voicecast.choose("auto", text, seen)

    def add_sound(video: Path, name: str, prompt: str, s: SoundBody, ctx: JobContext | None = None, image: Path | None = None) -> dict[str, Any] | None:
        """Mixes sound into `video` in place (the silent file is replaced). Returns what was added; never raises, so a sound problem cannot lose the video."""
        if not (s.narration.strip() or s.ambience != "none" or s.music):
            return None
        tmp = video.with_name(video.stem + "_sound.mp4")
        try:
            persona = resolve_persona(s.persona, s.narration + " " + prompt, image) if s.narration.strip() else ""
            r = soundtrack.build(video, tmp, prompt=prompt, narration=s.narration, voice=s.voice, rate=s.rate, ambience=s.ambience, music=s.music, level=s.level, persona=persona,
                                 work=state.paths.renders, on_status=(lambda m: ctx.update(0.98, m)) if ctx else None)
            tmp.replace(video)
            return r
        except (ai.AIError, FfmpegError, OSError) as exc:
            tmp.unlink(missing_ok=True)
            return {"error": str(exc), "warnings": ["Your video was made but the sound could not be added: " + str(exc)]}

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
        end_image_asset_id: str | None = None
        unlock_limits: bool = False
        sound: SoundBody | None = None
        enhance: bool | None = None  # None = follow the setting "Write a detailed prompt automatically"

    def build_request(body: GenerateBody, image_path: Path | None, end_image_path: Path | None = None) -> GenRequest:
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
            fps=body.fps or st.output_fps, steps=steps, guidance=guidance, seed=seed, model_id=model_id, image_path=image_path, end_image_path=end_image_path,
        )

    def better_prompt(text: str, kind: str = "video") -> tuple[str, str]:
        if assistant is None:
            return prompt_enhance.enhance(text, kind, None)
        return assistant_service.enhance_prompt(assistant, text, kind)

    def submit_generation(req: GenRequest, title: str, extra_meta: dict[str, Any], sound: SoundBody | None = None, enhance: bool | None = None) -> dict[str, Any]:
        def run(ctx: JobContext) -> dict[str, Any]:
            nonlocal req, extra_meta
            if (state.settings.get().auto_enhance if enhance is None else enhance):
                ctx.update(0.005, "Writing a detailed prompt")
                try:
                    detailed, how = better_prompt(req.prompt, "video")
                except Exception:  # noqa: BLE001 - a prompt helper must never stop a video from being made
                    detailed, how = req.prompt, "none"
                if how != "none" and detailed.strip() and detailed != req.prompt:
                    extra_meta = {**extra_meta, "prompt_original": req.prompt, "prompt_how": how}
                    req = dc_replace(req, prompt=detailed)
            if not req.negative_prompt.strip() and req.model_id != "ltxv-2b-distilled":
                req = dc_replace(req, negative_prompt=prompt_enhance.NEGATIVE_VIDEO)
            out = state.paths.outputs / f"{time.strftime('%Y%m%d-%H%M%S')}_{new_id()[:6]}_{safe_name(req.prompt)[:30]}.mp4"
            ctx.update(0.01, "Starting")
            limit = (state.settings.get().time_limit_min or 0) * 60
            watchdog = None
            if limit:
                def trip() -> None:
                    ctx.job.note = (f"Stopped after {limit // 60} minutes. This size is too much for this PC. "
                                    "Try a smaller size or shorter length, the Lite profile, or make it in the cloud (Motion control).")
                    ctx.job.cancel.set()
                watchdog = threading.Timer(limit, trip)
                watchdog.daemon = True
                watchdog.start()
            try:
                info = dict(state.engine.generate(req, out, ctx))
            finally:
                if watchdog:
                    watchdog.cancel()
            engine_warnings = list(info.pop("warnings", []))
            st_now = state.settings.get()
            if st_now.sharpen_output and not ctx.cancel.is_set():
                fin: dict[str, Any] = {"sharpened": False}
                if st_now.ai_upscale:
                    ctx.update(0.9, "Adding fine detail with the AI upscaler")
                    fin = finish.ai_upscale(out, ffmpeg_path(), state.paths.root / "tools", on_status=lambda m: ctx.update(0.92, m), cancel=ctx.cancel)
                if not fin.get("sharpened") and not ctx.cancel.is_set():
                    ctx.update(0.93, "Sharpening the video")
                    fin = {**finish.sharpen(out, ffmpeg_path()), **({"ai_note": fin.get("reason")} if fin.get("reason") else {})}
                if fin.get("sharpened"):
                    info["finish"] = fin
            sound_info = None
            if sound is not None:
                ctx.update(0.95, "Adding sound and voice")
                sound_info = add_sound(out, title, req.prompt, sound, ctx, Path(req.image_path) if getattr(req, "image_path", None) else None)
            ctx.update(0.99, "Adding to your library")
            asset = state.library.register(
                out, "generated", name=title,
                meta={
                    "prompt": req.prompt, "negative_prompt": req.negative_prompt, "seed": req.seed, "model": req.model_id,
                    "steps": req.steps, "guidance": req.guidance, "mode": req.mode, "frames": req.frames, **info, **extra_meta,
                    **({"sound": {k: v for k, v in sound_info.items() if k != "warnings"}} if sound_info else {}),
                },
            )
            return {"asset_id": asset.id, "warnings": engine_warnings + (sound_info or {}).get("warnings", [])}

        job = state.jobs.submit("generate", title, run, lane="gpu")
        try:
            info_now = state.system()
            st_now = state.settings.get()
            mdl = MODELS.get(req.model_id) or MODELS[st_now.default_model]
            job.expected = estimate_seconds(info_now, pick_profile(info_now, st_now.profile), mdl, req.width, req.height, req.frames, req.steps,
                                            has_end_image=bool(req.end_image_path)).seconds
        except (KeyError, ValueError, TypeError):
            job.expected = 0.0
        return job.to_json()

    def title_of(prompt: str) -> str:
        t = re.sub(r"\s+", " ", prompt).strip()
        return (t[:48] + "…") if len(t) > 48 else t

    @router.post("/generate")
    def generate(body: GenerateBody) -> dict[str, Any]:
        image_path = end_path = None
        if body.mode == "i2v":
            asset = state.db.get_asset(body.image_asset_id or "")
            if asset is None or asset.kind != "image":
                raise HTTPException(422, "Choose an image from your library as the starting frame.")
            image_path = Path(asset.path)
            if body.end_image_asset_id:
                end = state.db.get_asset(body.end_image_asset_id)
                if end is None or end.kind != "image":
                    raise HTTPException(422, "The ending picture must be an image from your library.")
                end_path = Path(end.path)
        req = build_request(body, image_path, end_path)
        meta = {"image_asset_id": body.image_asset_id} if image_path else {}
        if end_path:
            meta["end_image_asset_id"] = body.end_image_asset_id
        return submit_generation(req, title_of(body.prompt), meta, body.sound, body.enhance)

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
        end_path = None
        if body.end_image_asset_id:
            end = state.db.get_asset(body.end_image_asset_id)
            if end is None or end.kind != "image":
                raise HTTPException(422, "The ending picture must be an image from your library.")
            end_path = Path(end.path)
        req = build_request(body, frame, end_path)
        return submit_generation(req, "Continues: " + title_of(body.prompt), {"continues": src.id}, body.sound, body.enhance)

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
        for ref in [c.asset_id for c in project.clips] + [a.asset_id for a in project.audio] + [i.asset_id for i in project.images] + [ly.asset_id for ly in project.layers]:
            if ref in assets:
                continue
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
            "looks": [{"id": i, "label": effects.PRESET_LABELS.get(i, i), "group": effects.LOOK_GROUP.get(i, "Other")} for i in effects.FILTER_PRESETS],
            "effects": [{"id": i, "label": l, "group": effects.EFFECT_GROUP.get(i, "Other")} for i, l in effects.EFFECT_INFO],
            "masks": [{"id": i, "label": l} for i, l in effects.MASK_INFO],
            "motions": [{"id": i, "label": l} for i, l in effects.MOTION_INFO],
            "audio_fx": [{"id": i, "label": l, "group": g} for i, l, g in audiofx.AUDIO_FX_INFO],
            "fonts": [{"id": f.id, "label": f.label, "category": f.category, "scripts": list(f.scripts), "bold": bool(f.bold) or f.variable} for f in fonts.catalog().values()],
            "text_anim_in": list(TEXT_ANIM_IN),
            "text_anim_out": list(TEXT_ANIM_OUT),
            "whisper": [{"id": a.id, "label": a.label, "installed": state.downloads.is_installed(a.id)} for a in AUX.values()],
        }

    # ------------------------------------------------------------------ editor: built-in sound effects
    sounds_dir = state.paths.root / "sounds"

    def sound_asset(sound_id: str) -> Asset:
        """The library entry for a built-in sound (made on first use, then reused)."""
        if sound_id not in soundfx.SOUNDS:
            raise HTTPException(404, "There is no such sound.")
        try:
            file = soundfx.ensure(sound_id, sounds_dir)
        except RuntimeError as exc:
            raise HTTPException(500, str(exc)) from exc
        for a in state.db.list_assets(source="sound"):
            if (a.meta or {}).get("sound") == sound_id and Path(a.path).exists():
                return a
        return state.library.register(file, "sound", soundfx.SOUNDS[sound_id][0], {"sound": sound_id})

    @router.get("/editor/sounds")
    def editor_sounds() -> dict[str, Any]:
        return {"groups": soundfx.GROUP_ORDER, "sounds": soundfx.catalog()}

    @router.get("/editor/sounds/{sound_id}/file")
    def editor_sound_file(sound_id: str) -> FileResponse:
        if sound_id not in soundfx.SOUNDS:
            raise HTTPException(404, "There is no such sound.")
        try:
            return FileResponse(soundfx.ensure(sound_id, sounds_dir), media_type="audio/wav")
        except RuntimeError as exc:
            raise HTTPException(500, str(exc)) from exc

    @router.post("/editor/sounds/{sound_id}/add")
    def editor_sound_add(sound_id: str) -> dict[str, Any]:
        return sound_asset(sound_id).to_json()

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

    class InpaintBody(AIBody):
        prompt: str = Field(min_length=3, max_length=400)
        mode: Literal["patch", "track"] = "patch"
        part: Literal["", "head", "face"] = ""
        shapes: list[dict[str, Any]] = Field(default_factory=list, max_length=40)

    @router.post("/editor/ai/inpaint")
    def ai_inpaint(body: InpaintBody) -> dict[str, Any]:
        a, start, dur = ai_asset(body, ("video", "image"))
        mdir = state.paths.models / "image-inpaint"
        if not state.downloads.is_installed("image-inpaint"):
            raise HTTPException(409, "Install the object editor first: open the Models page and download “Object editor: AI inpainting” (about 2.2 GB, one time).")

        def run(ctx: JobContext) -> dict[str, Any]:
            if a.kind == "image":
                png = state.paths.renders / f"{new_id()}_aiedit.png"
                r = inpaint.edit_image(str(a.path), png, prompt=body.prompt, shapes=body.shapes, part=body.part, model_dir=mdir, on_progress=lambda p, m: ctx.update(p, m))
                made = state.library.register(png, "edit", f"{a.name} · AI edit", {"tool": "inpaint", "from": a.id, "prompt": body.prompt})
                return {"asset_id": made.id, **r}
            dest = state.paths.renders / f"{new_id()}_aiedit.mp4"
            r = inpaint.edit_video(str(a.path), start, dur, dest, prompt=body.prompt, shapes=body.shapes, part=body.part, mode=body.mode, model_dir=mdir,
                                   on_progress=lambda p, m: ctx.update(p, m), cancel=ctx.cancel)
            made = state.library.register(dest, "edit", f"{a.name} · AI edit", {"tool": "inpaint", "from": a.id, "prompt": body.prompt})
            return {"asset_id": made.id, **r}

        return ai_job("ai", f"AI edit: {a.name}", run)

    # ------------------------------------------------------------------ motion control (online model)
    motion_settings = motion.MotionSettings(state.paths.root / "motion.json")
    budget = budget_mod.Budget(state.paths.root / "budget.json")

    class BudgetBody(BaseModel):
        limit_usd: float | None = Field(None, ge=0, le=1000)
        window_hours: Literal[6, 12, 24] | None = None

    @router.get("/budget")
    def budget_get() -> dict[str, Any]:
        return budget.status()

    @router.post("/budget")
    def budget_set(body: BudgetBody) -> dict[str, Any]:
        try:
            return budget.set(body.limit_usd, body.window_hours)
        except budget_mod.BudgetError as exc:
            raise HTTPException(422, str(exc)) from exc

    def reserve_online(usd: float, what: str) -> str:
        try:
            return budget.reserve(usd, what)
        except budget_mod.BudgetError as exc:
            raise HTTPException(402, str(exc)) from exc

    class MotionSettingsBody(BaseModel):
        fal_key: str | None = Field(None, max_length=300)
        mode: Literal["std", "pro"] | None = None

    @router.get("/motion/settings")
    def motion_get() -> dict[str, Any]:
        return motion_settings.public()

    @router.post("/motion/settings")
    def motion_set(body: MotionSettingsBody) -> dict[str, Any]:
        try:
            motion_settings.update(body.fal_key, body.mode, verify=motion.check_key)
        except motion.MotionError as exc:
            raise HTTPException(422, str(exc)) from exc
        return motion_settings.public()

    @router.post("/motion/test")
    def motion_test() -> dict[str, Any]:
        key = str(motion_settings.get().get("fal_key", ""))
        if not key:
            return {"ok": False, "message": "No key saved yet."}
        bad = motion.check_key(key)
        return {"ok": bad is None, "message": bad or "fal.ai accepts this key."}

    class MotionBody(BaseModel):
        image_asset_id: str
        video_asset_id: str
        orientation: Literal["image", "video"] = "video"
        mode: Literal["std", "pro"] = "std"
        prompt: str = Field("", max_length=500)
        keep_sound: bool = True
        narration: str = Field("", max_length=1500)  # optional voice-over spoken over the result
        persona: Literal["auto", "girl", "boy", "woman", "man", "old_woman", "old_man"] = "auto"
        voice: str = ""

    def finish_motion(dest: Path, reference: Path, character: Path, keep_sound: bool, narration: str, persona: str, voice: str, ctx: JobContext) -> dict[str, Any]:
        """The reference video's own sound goes onto the result; an optional voice-over is added in a voice that fits the person in the picture."""
        out: dict[str, Any] = {}
        if keep_sound:
            ctx.update(0.95, "Adding the sound of your reference video")
            out["sound"] = finish.attach_reference_audio(dest, reference, ffmpeg_path())
        if narration.strip():
            ctx.update(0.97, "Recording the voice-over")
            tmp = dest.with_name(dest.stem + "_vo.mp4")
            try:
                who = resolve_persona(persona, narration, character)
                r = soundtrack.build(dest, tmp, prompt=narration, narration=narration, voice=voice, ambience="none", music=False, level=0.5, keep_original=True,
                                     work=state.paths.renders, persona=who)
                tmp.replace(dest)
                out["voice"] = {"persona": who, "warnings": r.get("warnings", [])}
            except (ai.AIError, FfmpegError, OSError) as exc:
                tmp.unlink(missing_ok=True)
                out["voice"] = {"error": str(exc), "warnings": ["The voice-over could not be added: " + str(exc)]}
        return out

    @router.post("/motion/run")
    def motion_run(body: MotionBody) -> dict[str, Any]:
        img, vid = asset_or_404(body.image_asset_id), asset_or_404(body.video_asset_id)
        if img.kind != "image":
            raise HTTPException(422, "The character must be a picture.")
        if vid.kind != "video":
            raise HTTPException(422, "The motion reference must be a video.")
        key = str(motion_settings.get().get("fal_key", ""))
        if not key:
            raise HTTPException(409, "Add your fal.ai key first (Motion Control page → Connect).")
        ticket = reserve_online(motion.motion_cost(vid.duration, body.mode), "Motion control")

        def run(ctx: JobContext) -> dict[str, Any]:
          try:
            dest = state.paths.renders / f"{new_id()}_motion.mp4"
            r = motion.run(key, Path(img.path), Path(vid.path), dest, orientation=body.orientation, mode=body.mode, prompt=body.prompt, keep_sound=body.keep_sound,
                           video_seconds=vid.duration, on_progress=lambda p, m: ctx.update(p, m), cancel=ctx.cancel)
            extra = finish_motion(dest, Path(vid.path), Path(img.path), body.keep_sound, body.narration, body.persona, body.voice, ctx)
            made = state.library.register(dest, "edit", f"Motion control · {img.name}", {"tool": "motion_control", "image": img.id, "video": vid.id})
            return {"asset_id": made.id, **r, **extra, "warnings": (extra.get("voice") or {}).get("warnings", [])}
          except BaseException:
            budget.refund(ticket)
            raise

        return ai_job("ai", f"Motion control: {img.name}", run)

    class CloudVideoBody(BaseModel):
        prompt: str = Field(min_length=3, max_length=2000)
        start_asset_id: str | None = None
        end_asset_id: str | None = None
        duration: Literal[6, 8, 10] = 6
        resolution: Literal["720p", "1080p", "1440p", "2160p", "4k"] = "1080p"
        aspect_ratio: Literal["16:9", "9:16"] = "16:9"
        audio: bool = True
        engine: Literal["ltx", "omni"] = "ltx"
        narration: str = Field("", max_length=1500)  # optional voice-over added on this PC, in a voice that fits the person
        persona: Literal["auto", "girl", "boy", "woman", "man", "old_woman", "old_man"] = "auto"
        voice: str = ""

    @router.get("/cloud-video/cost")
    def cloud_video_cost(duration: int = 6, resolution: str = "1080p", engine: str = "ltx") -> dict[str, Any]:
        prices = motion.ENGINES.get(engine, motion.ENGINES["ltx"])["prices"]
        return {"usd": motion.video_cost(duration, resolution, engine), "per_second": prices.get(resolution, min(prices.values()))}

    @router.get("/cloud-video/engines")
    def cloud_video_engines() -> dict[str, Any]:
        return {k: {"label": v["label"], "prices": v["prices"]} for k, v in motion.ENGINES.items()}

    @router.post("/cloud-video")
    def cloud_video(body: CloudVideoBody) -> dict[str, Any]:
        start = asset_or_404(body.start_asset_id) if body.start_asset_id else None
        end = asset_or_404(body.end_asset_id) if body.end_asset_id else None
        for a in (start, end):
            if a is not None and a.kind != "image":
                raise HTTPException(422, "Start and end must be pictures.")
        key = str(motion_settings.get().get("fal_key", ""))
        if not key:
            raise HTTPException(409, "Add your fal.ai key first (Motion control page → Connect).")
        ticket = reserve_online(motion.video_cost(body.duration, body.resolution, body.engine), "Online video")

        def run(ctx: JobContext) -> dict[str, Any]:
          try:
            dest = state.paths.renders / f"{new_id()}_cloud.mp4"
            prompt = body.prompt
            if state.settings.get().auto_enhance:
                ctx.update(0.01, "Writing a detailed prompt")
                try:
                    detailed, how = better_prompt(prompt, "video")
                    if how != "none" and detailed.strip():
                        prompt = detailed
                except Exception:  # noqa: BLE001 - a prompt helper must never stop a video from being made
                    pass
            r = motion.run_video(key, prompt, dest, image=Path(start.path) if start else None, end_image=Path(end.path) if end else None, duration=body.duration,
                                 resolution=body.resolution, aspect_ratio=body.aspect_ratio, audio=body.audio, engine=body.engine,
                                 on_progress=lambda p, m: ctx.update(p, m), cancel=ctx.cancel)
            warnings: list[str] = []
            if body.narration.strip():
                ctx.update(0.97, "Recording the voice-over")
                tmp = dest.with_name(dest.stem + "_vo.mp4")
                try:
                    who = resolve_persona(body.persona, body.narration + " " + body.prompt, Path(start.path) if start else None)
                    sr = soundtrack.build(dest, tmp, prompt=body.prompt, narration=body.narration, voice=body.voice, ambience="none", music=False, level=0.5,
                                          keep_original=True, work=state.paths.renders, persona=who)
                    tmp.replace(dest)
                    warnings = list(sr.get("warnings", []))
                except (ai.AIError, FfmpegError, OSError) as exc:
                    tmp.unlink(missing_ok=True)
                    warnings = ["The voice-over could not be added: " + str(exc)]
            made = state.library.register(dest, "generated", "Online video · " + body.prompt[:40], {"tool": "cloud_video", "model": r["model"], "prompt": prompt, "prompt_original": body.prompt})
            return {"asset_id": made.id, **r, "warnings": warnings}
          except BaseException:
            budget.refund(ticket)
            raise

        return ai_job("ai", "Sharp cloud video", run)

    class LocalMotionBody(BaseModel):
        image_asset_id: str
        video_asset_id: str
        engine: Literal["mediapipe", "tensorflow"] = "mediapipe"
        keep_sound: bool = True
        narration: str = Field("", max_length=1500)
        persona: Literal["auto", "girl", "boy", "woman", "man", "old_woman", "old_man"] = "auto"
        voice: str = ""

    def make_detector(engine: str = "mediapipe") -> Any:  # a seam the tests replace
        folder = state.paths.root / "models" / "pose"
        if engine == "tensorflow":
            return localmotion.tensorflow_detector(localmotion.ensure_movenet(folder))
        return localmotion.mediapipe_detector(localmotion.ensure_model(folder))

    @router.get("/motion/local/status")
    def motion_local_status() -> dict[str, Any]:
        import importlib.util

        return {"mediapipe": importlib.util.find_spec("mediapipe") is not None, "tensorflow": localmotion.tensorflow_available()}

    @router.post("/motion/local/install-tensorflow")
    def motion_install_tensorflow() -> dict[str, Any]:
        def go(ctx: JobContext, on_line) -> dict[str, Any]:
            updates.pip_install(["tensorflow>=2.16,<3"], on_line, ctx.cancel)
            return {"restart": True}

        return install_job("Install TensorFlow", go)

    @router.post("/motion/local")
    def motion_local(body: LocalMotionBody) -> dict[str, Any]:
        img, vid = asset_or_404(body.image_asset_id), asset_or_404(body.video_asset_id)
        if img.kind != "image":
            raise HTTPException(422, "The character must be a picture.")
        if vid.kind != "video":
            raise HTTPException(422, "The motion reference must be a video.")

        def run(ctx: JobContext) -> dict[str, Any]:
            ctx.update(0.02, "Loading the body finder")
            detect = make_detector(body.engine)
            dest = state.paths.renders / f"{new_id()}_localmotion.mp4"
            r = localmotion.run(Path(img.path), Path(vid.path), dest, detect, on_progress=lambda p, m: ctx.update(p, m), cancel=ctx.cancel)
            extra = finish_motion(dest, Path(vid.path), Path(img.path), body.keep_sound, body.narration, body.persona, body.voice, ctx)
            made = state.library.register(dest, "edit", f"Quick motion preview · {img.name}", {"tool": "motion_local", "image": img.id, "video": vid.id})
            return {"asset_id": made.id, **r, **extra, "warnings": (extra.get("voice") or {}).get("warnings", [])}

        return ai_job("ai", f"Quick motion preview: {img.name}", run)

    @router.get("/editor/ai/voices")
    def ai_voices() -> dict[str, Any]:
        return {"voices": ai.tts_voices()}

    class SpeakBody(BaseModel):
        text: str = Field(min_length=1, max_length=5000)
        voice: str = ""
        rate: int = Field(0, ge=-10, le=10)
        persona: Literal["auto", "girl", "boy", "woman", "man", "old_woman", "old_man"] = "auto"

    @router.post("/editor/ai/speak")
    def ai_speak(body: SpeakBody) -> dict[str, Any]:
        def run(ctx: JobContext) -> dict[str, Any]:
            dest = state.paths.renders / f"{new_id()}_voice.wav"
            ctx.update(0.2, "Speaking")
            who = resolve_persona(body.persona, body.text, None) if body.persona != "auto" or voicecast.persona_from_text(body.text) else ""
            soundtrack.speak_as(body.text, dest, who, body.voice, body.rate)
            made = state.library.register(dest, "edit", "Voice-over: " + body.text[:40], {"tool": "tts"})
            return {"asset_id": made.id}

        return ai_job("ai", "Voice-over", run)

    class SoundtrackBody(SoundBody):
        asset_id: str
        prompt: str = Field("", max_length=4000)  # what the scene shows; picks the background sound when ambience is "auto"

    @router.get("/editor/ai/ambiences")
    def ai_ambiences() -> dict[str, Any]:
        return {"ambiences": [{"id": i, "label": soundtrack.LABELS[i]} for i in [*soundtrack.AMBIENCES, "none"]]}

    @router.post("/editor/ai/soundtrack")
    def ai_soundtrack(body: SoundtrackBody) -> dict[str, Any]:
        a = state.db.get_asset(body.asset_id)
        if a is None or a.kind != "video":
            raise HTTPException(422, "Choose a video from your library.")

        def run(ctx: JobContext) -> dict[str, Any]:
            dest = state.paths.renders / f"{new_id()}_sound.mp4"
            ctx.update(0.1, "Preparing sound")
            r = soundtrack.build(Path(a.path), dest, prompt=body.prompt or str(a.meta.get("prompt", "")) or a.name, narration=body.narration, voice=body.voice, rate=body.rate,
                                 persona=resolve_persona(body.persona, body.narration + " " + (body.prompt or str(a.meta.get("prompt", "")) or a.name), None) if body.narration.strip() else "",
                                 ambience=body.ambience, music=body.music, level=body.level, work=state.paths.renders, on_status=lambda m: ctx.update(0.6, m))
            made = state.library.register(dest, "edit", f"{a.name} · with sound", {"tool": "soundtrack", "from": a.id, **{k: v for k, v in r.items() if k != "warnings"}})
            return {"asset_id": made.id, "warnings": r["warnings"]}

        return ai_job("ai", f"Sound and voice: {a.name}", run)

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
        attached = [i for m in body.messages[-1:] for i in m.image_ids if i in assets and assets[i].kind == "image"]
        system = editor_chat.system_prompt(editor_chat.describe(body.project, names, durations), library, n_img > 0, [names[i] for i in attached])
        base = {**cfg.__dict__, "temperature": 0.2, "max_tokens": 2048}

        def ask(extra: list[dict[str, Any]], json_mode: bool) -> str:
            return llm.complete(llm.LLMConfig(**{**base, "json_mode": json_mode}), msgs + extra, system)

        try:
            try:
                text = ask([], cfg.style == "openai" and cfg.provider not in ("ollama", "lmstudio"))
            except llm.LLMError as exc:
                if cfg.style == "openai" and any(w in str(exc).lower() for w in ("response_format", "json")):
                    text = ask([], False)  # this server has no JSON mode
                else:
                    raise
            parsed = editor_chat.parse_answer(text)
            if not parsed["ok"] or (not parsed["actions"] and editor_chat.looks_like_edit_request(body.messages[-1].content)):
                retry = [{"role": "assistant", "content": text[:1500]},
                         {"role": "user", "content": 'Answer again with ONLY the JSON object {"reply": "...", "actions": [...]}. Every action needs a "do" field. If the request needs a change to the video, include the action(s) now.'}]
                again = editor_chat.parse_answer(ask(retry, False))
                if again["ok"] and (again["actions"] or not parsed["ok"]):
                    parsed = again
        except llm.LLMError as exc:
            raise HTTPException(502, str(exc)) from exc
        made: list[str] = []

        def sound_for_chat(sound_id: str) -> Asset:
            a = sound_asset(sound_id)
            made.append(a.id)
            assets[a.id] = a
            return a

        ctx = {"attached": attached, "assets": assets, "face": ai.face_at, "sound": sound_for_chat}
        out = editor_chat.apply_actions(body.project, parsed["actions"], names, ctx)
        changed = bool(out["applied"]) and out["project"].model_dump() != body.project.model_dump()
        return {"reply": parsed["reply"], "project": out["project"].model_dump(), "applied": out["applied"], "skipped": out["skipped"], "tasks": out["tasks"], "changed": changed,
                "focus": out["focus"], "understood": parsed["ok"], "new_assets": made}

    @router.get("/ai/advice")
    def ai_advice() -> dict[str, Any]:
        if assistant is None:
            raise HTTPException(503, "The assistant is not available.")
        info = state.system()
        g = info.gpu
        out = assistant_service.advice(assistant, round(info.ram_mb / 1024, 1), g.vram_gb if g.available else 0.0, g.name, bool(g.available and g.arch_supported is not False))
        out["video"] = video_advice(info)
        return out

    class PromptBody(BaseModel):
        prompt: str = Field(min_length=1, max_length=2000)
        kind: Literal["image", "video"] = "video"

    @router.post("/prompt/enhance")
    def prompt_enhance(body: PromptBody) -> dict[str, Any]:
        if assistant is None:
            from ..assistant import enhance as _enh
            better, how = _enh.enhance(body.prompt, body.kind, None)
        else:
            better, how = assistant_service.enhance_prompt(assistant, body.prompt, body.kind)
        return {"prompt": better, "how": how}

    def video_advice(info) -> dict[str, Any]:
        st = state.settings.get()
        prof = pick_profile(info, st.profile)
        model = MODELS.get(st.default_model) or next(iter(MODELS.values()))
        est = estimate_seconds(info, prof, model, prof.default_width, prof.default_height, prof.default_frames)
        local = (f"{prof.default_width}x{prof.default_height}, {(prof.default_frames - 1) / st.output_fps:.0f} s with the {prof.label} profile: about {round(est.seconds / 60) or 1} min"
                 if est.device == "gpu" else "No usable graphics card: local videos are tiny and slow.")
        return {"local": local, "device": est.device, "cloud": "Sharp cloud video through fal.ai (your own key): about a minute or two per clip, pay per use, your own key stays on this PC.",
                "profile": prof.label}

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
