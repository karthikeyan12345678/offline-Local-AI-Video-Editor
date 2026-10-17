"""HTTP API for the Assistant (chat, file tools, settings)."""

import re
import shutil
from pathlib import Path
from functools import lru_cache
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from .. import __version__
from ..assistant import analytics, ats, compare, images, llm
from ..assistant.documents import FORMATS
from ..assistant.extract import SUPPORTED, ExtractError
from ..assistant import service
from ..assistant.service import AssistantState, make_document, run_turn
from ..assistant.themes import catalog, get_theme, recommend

MAX_UPLOAD = 150 * 1024 * 1024
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
MEDIA = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp"}


def safe_name(name: str) -> str:
    base = Path(name.replace("\\", "/")).name
    base = re.sub(r"[^\w .()+-]+", "_", base, flags=re.UNICODE).strip(" .")
    return base[:120] or "file"


class ChatBody(BaseModel):
    conversation_id: str
    text: str = Field("", max_length=60000)
    file_ids: list[str] = Field(default_factory=list, max_length=8)
    options: dict[str, Any] = Field(default_factory=dict)


class CreateBody(BaseModel):
    format: str
    markdown: str = Field(min_length=1, max_length=400000)
    title: str = ""
    theme: str | None = None
    purpose: str = ""


class AtsBody(BaseModel):
    file_id: str
    job_description: str = Field("", max_length=30000)


class CompareBody(BaseModel):
    file_a: str
    file_b: str


class AnalyzeBody(BaseModel):
    file_id: str


class ImageBody(BaseModel):
    prompt: str = Field(max_length=2000)
    shape: str = "square"
    seed: int | None = None


@lru_cache(maxsize=1)
def hardware() -> tuple[float, float, str, bool]:
    """(RAM GB, VRAM GB, graphics card name, usable) of this PC, looked up once."""
    from ..system import detect_system

    info = detect_system()
    g = info.gpu
    return round(info.ram_mb / 1024, 1), g.vram_gb if g.available else 0.0, g.name, bool(g.available and g.arch_supported is not False)


class RenameBody(BaseModel):
    title: str = Field(min_length=1, max_length=120)


def make_assistant_router(a: AssistantState) -> APIRouter:
    def auth(request: Request) -> None:
        supplied = request.headers.get("authorization", "").removeprefix("Bearer ").strip() or request.query_params.get("t", "")
        if supplied != a.token:
            raise HTTPException(401, "Not authorised")

    r = APIRouter(prefix="/api/assistant", dependencies=[Depends(auth)])

    def file_or_404(fid: str) -> dict[str, Any]:
        f = a.store.get_file(fid)
        if not f or not Path(f["path"]).exists():
            raise HTTPException(404, "That file is no longer available. Attach it again.")
        return f

    @r.get("/info")
    def info() -> dict[str, Any]:
        ok, why = images.local_available()
        return {"version": __version__, "formats": list(FORMATS), "providers": llm.PRESETS, "image_providers": images.IMAGE_PROVIDERS,
                "local_image": {"available": ok, "reason": why}, "supported_uploads": sorted(SUPPORTED | IMAGE_EXT), "themes": len(catalog())}

    # ---------------------------------------------------------------- advice and prompt help
    @r.get("/ai/advice")
    def ai_advice() -> dict[str, Any]:
        ram, vram, name, ok = hardware()
        return service.advice(a, ram, vram, name, ok)

    class EnhanceBody(BaseModel):
        prompt: str = Field(min_length=1, max_length=2000)
        kind: Literal["image", "video"] = "image"

    @r.post("/prompt/enhance")
    def prompt_enhance(body: EnhanceBody) -> dict[str, Any]:
        better, how = service.enhance_prompt(a, body.prompt, body.kind)
        return {"prompt": better, "how": how}

    # ---------------------------------------------------------------- settings
    @r.get("/settings")
    def get_settings() -> dict[str, Any]:
        d = a.settings.public()
        d["image"]["provider"] = a.image_config().provider  # what will really be used (the on-this-PC model once it is installed)
        return d

    @r.put("/settings")
    def put_settings(patch: dict[str, Any]) -> dict[str, Any]:
        a.settings.update(patch)
        return a.settings.public()

    @r.post("/settings/test")
    def test_llm(body: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            return llm.test_connection(a.llm_config())
        except llm.LLMError as e:
            raise HTTPException(400, str(e))

    @r.get("/models")
    def models() -> dict[str, Any]:
        try:
            return {"models": llm.list_models(a.llm_config())}
        except llm.LLMError as e:
            raise HTTPException(400, str(e))

    # ---------------------------------------------------------------- chats
    @r.get("/conversations")
    def conversations() -> list[dict[str, Any]]:
        return a.store.list_conversations()

    @r.post("/conversations")
    def new_conversation() -> dict[str, Any]:
        return a.store.create_conversation()

    @r.get("/conversations/{cid}")
    def conversation(cid: str) -> dict[str, Any]:
        c = a.store.get_conversation(cid)
        if not c:
            raise HTTPException(404, "Chat not found")
        msgs = a.store.messages(cid)
        for m in msgs:
            m["files"] = [{k: f[k] for k in ("id", "name", "kind", "size")} for f in (a.store.get_file(i) for i in m["files"]) if f]
        return {**c, "messages": msgs}

    @r.patch("/conversations/{cid}")
    def rename(cid: str, body: RenameBody) -> dict[str, Any]:
        if not a.store.rename(cid, body.title):
            raise HTTPException(404, "Chat not found")
        return {"ok": True}

    @r.delete("/conversations/{cid}")
    def delete_conversation(cid: str) -> dict[str, Any]:
        if not a.store.delete_conversation(cid):
            raise HTTPException(404, "Chat not found")
        return {"ok": True}

    @r.post("/chat")
    def chat(body: ChatBody) -> StreamingResponse:
        gen = run_turn(a, body.conversation_id, body.text, body.file_ids, body.options)
        return StreamingResponse(gen, media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ---------------------------------------------------------------- files
    @r.post("/files")
    async def upload(file: UploadFile = File(...)) -> dict[str, Any]:
        name = safe_name(file.filename or "file")
        ext = Path(name).suffix.lower()
        if ext not in SUPPORTED | IMAGE_EXT:
            raise HTTPException(415, f"“{ext or name}” files are not supported. Use PDF, Word, PowerPoint, Excel, CSV, text or an image.")
        dest = a.uploads / f"{len(list(a.uploads.iterdir())):05d}-{name}"
        size = 0
        with dest.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD:
                    out.close()
                    dest.unlink(missing_ok=True)
                    raise HTTPException(413, "That file is larger than 150 MB.")
                out.write(chunk)
        if size == 0:
            dest.unlink(missing_ok=True)
            raise HTTPException(400, "That file is empty.")
        return a.store.add_file("upload", name, dest, ext.lstrip("."))

    @r.get("/files")
    def files(origin: str | None = Query(None)) -> list[dict[str, Any]]:
        return a.store.list_files(origin)

    @r.get("/files/{fid}/download")
    def download(fid: str, inline: bool = False) -> FileResponse:
        f = file_or_404(fid)
        p = Path(f["path"])
        mt = MEDIA.get(p.suffix.lower())
        return FileResponse(p, media_type=mt if inline and mt else "application/octet-stream", filename=f["name"], content_disposition_type="inline" if inline and mt else "attachment")

    @r.delete("/files/{fid}")
    def delete_file(fid: str) -> dict[str, Any]:
        if not a.store.delete_file(fid):
            raise HTTPException(404, "File not found")
        return {"ok": True}

    # ---------------------------------------------------------------- tools
    @r.get("/themes")
    def themes(purpose: str = "", doc_type: str = "document", limit: int = 8) -> dict[str, Any]:
        items = [t.to_json() for t in catalog().values()]
        return {"themes": items, "recommended": recommend(purpose, doc_type, limit=max(1, min(limit, 20))) if purpose.strip() else []}

    @r.post("/tools/create")
    def create(body: CreateBody) -> dict[str, Any]:
        fmt = body.format.lower()
        if fmt not in FORMATS:
            raise HTTPException(400, f"Choose one of: {', '.join(FORMATS)}")
        try:
            f, meta = make_document(a, fmt, body.markdown, body.purpose or body.title, body.theme, body.title)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"file": f, **meta}

    @r.post("/tools/ats")
    def tool_ats(body: AtsBody) -> dict[str, Any]:
        f = file_or_404(body.file_id)
        try:
            return ats.check_file(f["path"], body.job_description)
        except (ExtractError, ValueError) as e:
            raise HTTPException(400, str(e))

    @r.post("/tools/compare")
    def tool_compare(body: CompareBody) -> dict[str, Any]:
        fa, fb = file_or_404(body.file_a), file_or_404(body.file_b)
        try:
            res = compare.compare_files(fa["path"], fb["path"])
        except (ExtractError, ValueError) as e:
            raise HTTPException(400, str(e))
        out = a.generated / f"comparison-{fa['id']}-{fb['id']}.md"
        out.write_text(compare.to_markdown(res), encoding="utf-8")
        return {"result": res, "report": a.store.add_file("generated", out.name, out, "md")}

    @r.post("/tools/analyze")
    def tool_analyze(body: AnalyzeBody) -> dict[str, Any]:
        f = file_or_404(body.file_id)
        try:
            return analytics.analyze_file(f["path"])
        except (ExtractError, ValueError) as e:
            raise HTTPException(400, str(e))

    @r.post("/tools/image")
    def tool_image(body: ImageBody) -> dict[str, Any]:
        try:
            out = images.generate_image(a.image_config(), body.prompt, a.pictures, body.shape, body.seed)
        except images.ImageError as e:
            raise HTTPException(400, str(e))
        f = a.store.add_file("generated", out["name"], Path(out["path"]), "png")
        return {"file": f, **{k: out[k] for k in ("width", "height", "prompt", "provider")}}

    return r


def make_assistant_health_router(token: str) -> APIRouter:
    """/api/health for the stand-alone assistant (the desktop shell polls it)."""

    def auth(request: Request) -> None:
        supplied = request.headers.get("authorization", "").removeprefix("Bearer ").strip() or request.query_params.get("t", "")
        if supplied != token:
            raise HTTPException(401, "Not authorised")

    r = APIRouter(prefix="/api", dependencies=[Depends(auth)])

    @r.get("/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "version": __version__, "product": "assistant"}

    return r
