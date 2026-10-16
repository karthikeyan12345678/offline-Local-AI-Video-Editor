"""HTTP API. Thin: validation and wiring only; work happens in services and jobs."""

import random
import re
import shutil
import time
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .. import __version__
from ..catalog import BASE_ID, MODELS
from ..db import Asset, new_id
from ..editor import ops
from ..editor.media import FfmpegError, run_ffmpeg
from ..editor.project import ExportOptions, Project
from ..editor.render import AssetRef, PlanError, build_plan
from ..engine.base import GenRequest
from ..jobs import JobContext, UserFacingError
from ..library import SUPPORTED, safe_name
from ..profiles import PROFILES, LimitError, pick_profile, validate_request
from ..state import AppState


def make_router(state: AppState) -> APIRouter:
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
        return {"items": rows, "endpoint": state.settings.get().hf_endpoint}

    def known_item(item_id: str) -> str:
        if item_id != BASE_ID and item_id not in MODELS:
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
