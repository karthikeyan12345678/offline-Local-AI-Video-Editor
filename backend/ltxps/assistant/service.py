"""Ties the assistant together: state, intent detection, and the streamed chat turn."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from . import analytics, ats, compare, images, llm, reference
from .documents import FORMATS, build_file, parse_markdown
from .extract import ExtractError, extract
from .store import AssistantSettings, AssistantStore
from .themes import get_theme, recommend

FORMAT_WORDS = {"pdf": "pdf", "ppt": "pptx", "pptx": "pptx", "powerpoint": "pptx", "slides": "pptx", "deck": "pptx", "presentation": "pptx", "doc": "docx", "docx": "docx",
                "word": "docx", "csv": "csv", "xlsx": "xlsx", "excel": "xlsx", "spreadsheet": "xlsx"}
COMMANDS = {"pdf": "pdf", "ppt": "pptx", "pptx": "pptx", "slides": "pptx", "doc": "docx", "docx": "docx", "word": "docx", "csv": "csv", "xlsx": "xlsx", "excel": "xlsx",
            "ats": "ats", "resume": "ats", "image": "image", "img": "image", "draw": "image", "compare": "compare", "diff": "compare", "analyze": "analyze", "analyse": "analyze",
            "analytics": "analyze", "design": "design", "theme": "design"}

DOC_PROMPTS = {
    "pdf": "Write a professional, well-structured document in Markdown. Use one # title and a one-line subtitle, then a short '## Summary' (3 to 5 lines), then clear ## sections in a logical order with short paragraphs, bullet lists and a table where numbers or comparisons help, and finish with '## Next steps' or '## Conclusion'. Be specific and concrete, no filler.",
    "docx": "Write a professional, well-structured document in Markdown. Use one # title and a one-line subtitle, then a short '## Summary' (3 to 5 lines), then clear ## sections in a logical order with short paragraphs, bullet lists and a table where numbers or comparisons help, and finish with '## Next steps' or '## Conclusion'. Be specific and concrete, no filler.",
    "pptx": ("Write a slide deck in Markdown. Start with '# Title' then a line of subtitle text. Each slide is a '## Slide title' followed by 3 to 5 short bullets "
             "(max 12 words each) or one small table. Add a line 'Notes: ...' with speaker notes under each slide. Use 6 to 12 slides. Use '# Section' alone for a section divider."),
    "csv": "Produce ONLY one Markdown table with a header row and realistic data rows. No prose before or after the table.",
    "xlsx": "Produce Markdown tables with a header row and data rows (one table per sheet, each preceded by a '## Sheet name' heading). No other prose.",
}
SYSTEM_BASE = ("You are a careful, practical assistant inside a desktop app. Answer directly and accurately. If you are unsure, say so. "
               "Keep replies as short as the request allows.")


def looks_like_markdown(t: str) -> bool:
    lines = [l for l in t.splitlines() if l.strip()]
    marks = sum(1 for l in lines if re.match(r"^\s*(#{1,4}\s|[-*]\s|\d+[.)]\s|\|.*\|)", l))
    return len(lines) >= 4 and marks >= 3


def strip_fence(t: str) -> str:
    t = t.strip()
    m = re.match(r"^```(?:markdown|md)?\s*\n(.*?)\n```\s*$", t, re.S)
    return m.group(1).strip() if m else t


@dataclass
class Intent:
    kind: str  # chat | pdf | docx | pptx | csv | xlsx | ats | image | compare | analyze | design
    text: str  # the request with any leading command removed


def detect_intent(text: str, n_files: int) -> Intent:
    t = text.strip()
    m = re.match(r"^/(\w+)\s*(.*)$", t, re.S)
    if m and m.group(1).lower() in COMMANDS:
        return Intent(COMMANDS[m.group(1).lower()], m.group(2).strip())
    low = t.lower()
    if re.search(r"\b(generate|create|make|draw|paint|render|produce)\b.{0,25}\b(image|picture|photo|illustration|logo|poster|artwork|wallpaper)\b", low) and n_files == 0:
        return Intent("image", t)
    if n_files >= 2 and re.search(r"\b(compare|difference|differences|diff|what changed|which is better)\b", low):
        return Intent("compare", t)
    if n_files >= 1 and re.search(r"\b(ats|resume score|resume check|check (my )?resume|applicant tracking)\b", low):
        return Intent("ats", t)
    if n_files >= 1 and re.search(r"\b(analy[sz]e|analytics|statistics|stats|profile this|summari[sz]e the data|insights?)\b", low):
        return Intent("analyze", t)
    m2 = re.search(r"\b(create|make|generate|build|write|prepare|export|convert|produce|draft)\b.{0,40}?\b(pdf|pptx?|powerpoint|slides?|deck|presentation|docx?|word|csv|xlsx|excel|spreadsheet)\b", low)
    if m2:
        return Intent(FORMAT_WORDS[m2.group(2)], t)
    if re.search(r"\b(best|recommend|suggest|which)\b.{0,25}\b(design|theme|style|template|palette)\b", low):
        return Intent("design", t)
    return Intent("chat", t)


@dataclass
class AssistantState:
    root: Path
    store: AssistantStore
    settings: AssistantSettings
    token: str
    models_root: Path | None = None  # set by the studio so the downloaded picture model can be found

    @property
    def uploads(self) -> Path:
        return self.root / "uploads"

    @property
    def generated(self) -> Path:
        return self.root / "files"

    @property
    def pictures(self) -> Path:
        return self.root / "images"

    def llm_config(self) -> llm.LLMConfig:
        raw = self.settings.raw()
        return llm.config_from(raw.get("provider", "ollama"), raw.get("providers", {}))

    def image_config(self) -> images.ImageConfig:
        saved = self.settings.raw().get("image", {})
        cfg = images.image_config_from(saved)
        mdir = self.models_root / "image-sd-turbo" if self.models_root else None
        ready = bool(mdir and (mdir / ".complete.json").exists()) if mdir else False
        if ready:
            cfg.local_dir = str(mdir)
            if not saved.get("chosen"):  # nobody picked an engine by hand: use the one that is now on this PC
                cfg.provider = "local"
        return cfg


def build_assistant_state(root: Path, token: str) -> AssistantState:
    root.mkdir(parents=True, exist_ok=True)
    for d in ("uploads", "files", "images", "logs"):
        (root / d).mkdir(exist_ok=True)
    return AssistantState(root, AssistantStore(root / "assistant.sqlite3"), AssistantSettings(root / "assistant-settings.json"), token)


def sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def file_card(f: dict[str, Any], note: str = "", warnings: list[str] | None = None, theme: dict | None = None) -> dict[str, Any]:
    return {"type": "file", "file": f, "note": note, "warnings": warnings or [], "theme": theme}


def attachment_context(state: AssistantState, ids: list[str], limit: int = 14000) -> tuple[str, list[str]]:
    parts, errs = [], []
    for fid in ids:
        f = state.store.get_file(fid)
        if not f:
            continue
        try:
            ex = extract(f["path"])
        except ExtractError as e:
            errs.append(str(e))
            continue
        body = ex.text
        if ex.tables and ex.kind in {"csv", "xlsx", "tsv"}:
            t = ex.tables[0]
            body = f"Columns: {', '.join(map(str, t['columns']))}\nRows: {len(t['rows'])}\nFirst rows:\n" + "\n".join(" | ".join(map(str, r)) for r in t["rows"][:25])
        parts.append(f"[Attached file: {f['name']}]\n{body[: limit // max(1, len(ids))]}")
    return "\n\n".join(parts), errs


def history_for_llm(state: AssistantState, cid: str, new_user: str, max_chars: int = 24000) -> list[dict[str, str]]:
    msgs = [{"role": m["role"], "content": m["content"]} for m in state.store.messages(cid) if m["role"] in ("user", "assistant") and m["content"]]
    msgs.append({"role": "user", "content": new_user})
    total, keep = 0, []
    for m in reversed(msgs):
        total += len(m["content"])
        if total > max_chars and keep:
            break
        keep.append(m)
    return list(reversed(keep))


def derive_title(text: str) -> str:
    t = re.sub(r"^/\w+\s*", "", text.strip())
    t = re.sub(r"\s+", " ", t)
    return (t[:48] + "…") if len(t) > 48 else (t or "New chat")


def _register_generated(state: AssistantState, path: Path, kind: str) -> dict[str, Any]:
    return state.store.add_file("generated", path.name, path, kind)


def make_document(state: AssistantState, fmt: str, md: str, request: str, theme_id: str | None, title: str = "") -> tuple[dict[str, Any], dict[str, Any]]:
    doc = parse_markdown(md, title=title)
    chosen = theme_id or None
    reco = None
    if not chosen:
        base = state.settings.raw().get("default_theme", "claude")
        picks = recommend(request, fmt, limit=1) if request.strip() else []
        reco = picks[0] if picks else None
        chosen = reco["id"] if reco and reco["score"] >= 2.5 else base
    res = build_file(fmt, doc, state.generated, (doc.title or title or "document")[:60], chosen)
    f = _register_generated(state, Path(res.path), fmt)
    th = get_theme(chosen)
    info = {"id": th.id, "name": th.name, "colors": th.colors, "reasons": (reco or {}).get("reasons", []) if reco and reco["id"] == chosen else ["chosen by you" if theme_id else "your default theme"]}
    return f, {"warnings": res.warnings, "theme": info, "pages": res.pages}


def run_turn(state: AssistantState, cid: str, text: str, file_ids: list[str], options: dict[str, Any]) -> Iterator[str]:
    """One chat turn as server-sent events: delta (text pieces), card (results), done, error."""
    conv = state.store.get_conversation(cid)
    if not conv:
        yield sse("error", {"message": "That chat no longer exists. Start a new one."})
        return
    text = text.strip()
    if not text and not file_ids:
        yield sse("error", {"message": "Type a message or attach a file first."})
        return
    if conv["title"] == "New chat" and text:
        state.store.rename(cid, derive_title(text))
    files = [f for f in (state.store.get_file(i) for i in file_ids) if f]
    intent = detect_intent(text, len(files))
    if not text and files:
        intent = Intent("chat", "Summarise this file.")
    user_msg = state.store.add_message(cid, "user", text, files=[f["id"] for f in files])
    yield sse("start", {"message_id": user_msg["id"], "intent": intent.kind, "title": state.store.get_conversation(cid)["title"]})
    cards: list[dict[str, Any]] = []
    reply = ""
    try:
        if intent.kind in FORMATS:
            reply, cards = yield from _do_document(state, cid, intent, text, files, options)
        elif intent.kind == "ats":
            reply, cards = _do_ats(state, intent, files, options)
            yield sse("delta", {"text": reply})
        elif intent.kind == "compare":
            reply, cards = _do_compare(state, files)
            yield sse("delta", {"text": reply})
        elif intent.kind == "analyze":
            reply, cards = _do_analyze(state, files)
            yield sse("delta", {"text": reply})
        elif intent.kind == "image":
            reply, cards = _do_image(state, intent.text or text, options)
            yield sse("delta", {"text": reply})
        elif intent.kind == "design":
            reply, cards = _do_design(intent.text or text, options)
            yield sse("delta", {"text": reply})
        else:
            reply = yield from _do_chat(state, cid, intent.text or text, files)
    except (llm.LLMError, images.ImageError, ExtractError, ValueError) as exc:
        msg = str(exc)
        state.store.add_message(cid, "assistant", "⚠ " + msg, [{"type": "error", "message": msg}])
        yield sse("error", {"message": msg})
        return
    except Exception:  # noqa: BLE001 - a clear message for the person, full detail in the log
        import logging

        logging.getLogger("ltxps.assistant").exception("assistant turn failed")
        msg = "Something went wrong while doing that. Details were saved to the log file."
        state.store.add_message(cid, "assistant", "⚠ " + msg, [{"type": "error", "message": msg}])
        yield sse("error", {"message": msg})
        return
    for c in cards:
        yield sse("card", c)
    saved = state.store.add_message(cid, "assistant", reply, cards)
    yield sse("done", {"message_id": saved["id"]})


def _do_chat(state: AssistantState, cid: str, text: str, files: list[dict]) -> Iterator[str]:
    ctx, errs = attachment_context(state, [f["id"] for f in files])
    for e in errs:
        yield sse("delta", {"text": f"_{e}_\n\n"})
    prompt = (f"{ctx}\n\n---\n{text}" if ctx else text)
    cfg = state.llm_config()
    system = SYSTEM_BASE + ("\n" + state.settings.raw().get("system_prompt", "")).rstrip()
    out = ""
    for piece in llm.stream_chat(cfg, history_for_llm(state, cid, prompt), system):
        out += piece
        yield sse("delta", {"text": piece})
    return out


def _do_document(state: AssistantState, cid: str, intent: Intent, text: str, files: list[dict], options: dict[str, Any]) -> Iterator[str]:
    fmt = intent.kind
    request = intent.text or text
    ref_files = [f for f in files if Path(f["name"]).suffix.lower() in (".pdf", ".docx", ".pptx", ".md", ".txt")]
    ref_prof: dict[str, Any] | None = None
    if ref_files and fmt in ("pdf", "docx", "pptx"):
        try:
            ref_prof = reference.profile(ref_files[0]["path"])
        except ExtractError as e:
            yield sse("delta", {"text": f"_{e} I will use the standard professional style instead._\n\n"})
    ctx, _ = attachment_context(state, [f["id"] for f in files], 10000)
    if looks_like_markdown(request):
        md = request
        yield sse("delta", {"text": "Using the content you pasted.\n\n"})
    else:
        if not request:
            raise ValueError(f"Say what the {fmt.upper()} should contain, for example “/{fmt} a one-page project status report”.")
        cfg = state.llm_config()
        yield sse("status", {"text": "Writing the content…"})
        prompt = f"{DOC_PROMPTS[fmt]}\nOutput only the Markdown, with no commentary.\n\nRequest: {request}"
        if ref_prof:
            yield sse("status", {"text": f"Studying “{ref_prof['name']}” for its structure and style…"})
            prompt += "\n\n" + reference.instructions(ref_prof, fmt)
            ctx = ""  # the reference teaches the form, not the content
        if ctx:
            prompt += f"\n\nUse this material:\n{ctx}"
        md = strip_fence(llm.complete(cfg, [{"role": "user", "content": prompt}], SYSTEM_BASE))
        if not md.strip():
            raise llm.LLMError("The model returned no content. Try again or choose another model.")
    yield sse("status", {"text": "Building the file…"})
    theme_id = options.get("theme")
    if ref_prof and not theme_id:
        th = reference.theme_from(ref_prof)
        theme_id = th.id if th else None
    f, meta = make_document(state, fmt, md, request, theme_id)
    reply = f"Your {fmt.upper()} is ready: **{f['name']}**." + (f" It follows the structure{' and colours' if theme_id == 'reference' else ''} of {ref_prof['name']}." if ref_prof else "")
    if meta["warnings"]:
        reply += " Note: " + " ".join(meta["warnings"])
    yield sse("delta", {"text": reply})
    return reply, [file_card(f, "Draft the AI wrote; check facts before sharing.", meta["warnings"], meta["theme"]), {"type": "markdown", "text": md}]


def _need_files(files: list[dict], n: int, what: str) -> None:
    if len(files) < n:
        raise ValueError(f"Attach {n} file{'s' if n > 1 else ''} first (use the paperclip) to {what}.")


def _do_ats(state: AssistantState, intent: Intent, files: list[dict], options: dict[str, Any]) -> tuple[str, list[dict]]:
    _need_files(files, 1, "check a resume")
    jd = options.get("job_description") or re.sub(r"(?i)\b(check|score|ats|my|resume|against|for|this)\b", " ", intent.text).strip()
    jd = jd if len(jd.split()) >= 12 else ""
    r = ats.check_file(files[0]["path"], jd)
    reply = f"ATS estimate for **{files[0]['name']}**: **{r['score']:.0f}/100 ({r['level']})**." + ("" if r["has_job_description"] else " Paste a job description to see which of its keywords are missing.")
    return reply, [{"type": "ats", "result": r}]


def _do_compare(state: AssistantState, files: list[dict]) -> tuple[str, list[dict]]:
    _need_files(files, 2, "compare them")
    r = compare.compare_files(files[0]["path"], files[1]["path"])
    md = compare.to_markdown(r)
    out = state.generated / f"comparison-{files[0]['id']}-{files[1]['id']}.md"
    out.write_text(md, encoding="utf-8")
    f = _register_generated(state, out, "md")
    return compare.headline(r), [{"type": "compare", "result": r, "report": f}]


def _do_analyze(state: AssistantState, files: list[dict]) -> tuple[str, list[dict]]:
    _need_files(files, 1, "analyse it")
    r = analytics.analyze_file(files[0]["path"])
    return r["headline"], [{"type": "analytics", "result": r}]


def _do_image(state: AssistantState, prompt: str, options: dict[str, Any]) -> tuple[str, list[dict]]:
    cfg = state.image_config()
    out = images.generate_image(cfg, prompt, state.pictures, options.get("shape", "square"), options.get("seed"), hf_endpoint=options.get("hf_endpoint", ""))
    f = state.store.add_file("generated", out["name"], Path(out["path"]), "png")
    note = " The free fallback service adds a small logo; install the on-this-PC picture model (Install everything) for logo-free pictures with no limits." if out.get("watermark") else ""
    return f"Here is your image ({out['width']}×{out['height']}).{note}", [{"type": "image", "file": f, "prompt": prompt, "width": out["width"], "height": out["height"], "provider": out["provider"]}]


def _do_design(text: str, options: dict[str, Any]) -> tuple[str, list[dict]]:
    picks = recommend(text, options.get("doc_type", "document"), limit=5)
    top = picks[0]
    return f"Best match: **{top['name']}** ({'; '.join(top['reasons'][:2])}).", [{"type": "themes", "themes": picks, "request": text}]
