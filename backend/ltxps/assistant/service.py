"""Ties the assistant together: state, intent detection, and the streamed chat turn."""

from __future__ import annotations

import json
import math
import re
import shutil
import sys
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterator

from . import analytics, ats, compare, enhance, images, llm, reference
from .documents import FORMATS, build_file, parse_markdown
from .extract import ExtractError, extract
from .store import AssistantSettings, AssistantStore
from .themes import get_theme, recommend

FORMAT_WORDS = {"pdf": "pdf", "ppt": "pptx", "pptx": "pptx", "powerpoint": "pptx", "slides": "pptx", "slide": "pptx", "deck": "pptx", "presentation": "pptx", "doc": "docx", "docx": "docx",
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
    if n_files >= 1 and re.search(r"\b(tailor|tailoring|customi[sz]e|optimi[sz]e|rewrite|rework|revamp|improve|update|fix|adapt|align|match)\b.{0,80}\b(resume|cv|pdf|doc|docx|file|jd|job description|ats)\b|\b(resume|cv)\b.{0,60}\b(jd|job description|ats|tailor)", low) and re.search(r"\b(tailor\w*|jd|job description|ats|job posting|role)\b", low):
        return Intent("tailor", t)
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
        elif intent.kind == "tailor":
            reply, cards = yield from _do_tailor(state, intent, files, options)
        elif intent.kind == "compare":
            reply, cards = _do_compare(state, files)
            yield sse("delta", {"text": reply})
        elif intent.kind == "analyze":
            reply, cards = _do_analyze(state, files)
            yield sse("delta", {"text": reply})
        elif intent.kind == "image":
            reply, cards = yield from _do_image(state, intent.text or text, options)
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
        msg = f"Something went wrong while doing that ({type(sys.exc_info()[1]).__name__}: {str(sys.exc_info()[1])[:160]}). Details were saved to the log file."
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


JD_NAME = re.compile(r"(?i)\b(jd|job|description|posting|vacancy|role|opening)\b")
RESUME_SECTIONS = re.compile(r"(?im)^\s*(work experience|experience|professional experience|employment|education|skills|projects|certifications|summary|profile)\s*:?\s*$")
JD_WORDS = re.compile(r"(?i)\b(responsibilities|requirements|qualifications|we are looking|you will|what you.ll do|about the role|job description|preferred)\b")
TAILOR_PROMPT = (
    "You are an expert resume writer who knows how applicant tracking systems (ATS) read resumes. Rewrite the RESUME so it fits the JOB DESCRIPTION and scores as high as possible, "
    "while staying completely truthful.\n"
    "Rules:\n"
    "- Use ONLY facts that are in the resume. Never invent employers, titles, dates, degrees, tools, numbers or achievements. Keep every date, company, title and school exactly as given.\n"
    "- Use the job description's own wording for skills and duties that the resume really supports (for example write 'Kubernetes' if the resume shows it, in the same form the job uses).\n"
    "- Start from this structure, in Markdown: '# Full Name', one line of contact details separated by ' | ', then '## Summary' (2 to 3 lines aimed at this job), '## Skills' (a plain comma-separated list of the relevant skills, job keywords first), "
    "'## Experience' (for each role '### Job title, Company' then a line with dates and location, then 3 to 6 bullets that start with a strong verb, put the most relevant first, keep real numbers if the resume has them), "
    "'## Education', and '## Certifications' or '## Projects' only if the resume has them.\n"
    "- Single column, plain text only: no tables, no images, no emojis, no icons, no columns. Standard section names only.\n"
    "- Keep it to what fits on one or two pages. Output only the Markdown, no commentary.")


def _tailor_inputs(state: AssistantState, files: list[dict], text: str, options: dict[str, Any]) -> tuple[dict, str, str]:
    """Works out which attachment is the resume and where the job description is (a second file, the message, or the options)."""
    exs = []
    for f in files:
        try:
            exs.append((f, extract(f["path"])))
        except ExtractError as e:
            raise ValueError(str(e)) from e
    resume = jd_file = None
    if len(exs) >= 2:
        for f, ex in exs:
            if JD_NAME.search(Path(f["name"]).stem) and jd_file is None:
                jd_file = (f, ex)
        if jd_file is None:
            scored = sorted(exs, key=lambda fe: len(RESUME_SECTIONS.findall(fe[1].text)) - len(JD_WORDS.findall(fe[1].text)))
            jd_file = scored[0]
        resume = next((fe for fe in exs if fe is not jd_file), exs[0])
    else:
        resume = exs[0]
    jd = options.get("job_description") or ""
    if not jd and jd_file:
        jd = jd_file[1].text
    if not jd:
        jd = re.sub(r"(?i)^/\w+\s*", "", text).strip()
        if len(jd.split()) < 25:
            jd = ""
    if not jd.strip() or len(jd.split()) < 12:
        raise ValueError("I need the job description to tailor to. Attach it as a second file, or paste it in the message together with your request.")
    rtext = resume[1].text
    if resume[1].kind in {"csv", "xlsx", "tsv"} and resume[1].tables:
        t = resume[1].tables[0]
        rtext = "\n".join(" | ".join(map(str, r)) for r in [t["columns"], *t["rows"][:200]])
    return resume[0], rtext, jd


def _do_tailor(state: AssistantState, intent: Intent, files: list[dict], options: dict[str, Any]) -> Iterator[str]:
    _need_files(files, 1, "tailor a resume")
    low = intent.text.lower()
    fmt = "docx" if re.search(r"\b(word|docx?)\b", low) and not re.search(r"\bpdf\b", low) else "pdf"
    rf, rtext, jd = _tailor_inputs(state, files, intent.text, options)
    before = None
    try:
        before = ats.check_resume(extract(rf["path"]), jd)
    except Exception:  # noqa: BLE001 - e.g. a table file; the tailored file is still scored below
        pass
    cfg = state.llm_config()
    yield sse("status", {"text": "Reading the job description and your resume…"})
    want = ats.jd_keywords(jd)
    kw_line = ", ".join(w["keyword"] for w in want[:30])
    prompt = f"{TAILOR_PROMPT}\n\nKEY TERMS IN THE JOB (use the ones the resume supports): {kw_line}\n\nJOB DESCRIPTION:\n{jd[:7000]}\n\nRESUME:\n{rtext[:9000]}"
    yield sse("status", {"text": "Rewriting your resume for this job…"})
    md = strip_fence(llm.complete(cfg, [{"role": "user", "content": prompt}], SYSTEM_BASE))
    if not md.strip():
        raise llm.LLMError("The model returned no content. Try again or choose another model.")
    best = None
    for attempt in range(2):
        yield sse("status", {"text": "Building the file and checking its ATS score…" if attempt == 0 else "Improving the keyword match…"})
        f, meta = make_document(state, fmt, md, "resume cv", options.get("theme"), "")
        after = ats.check_resume(extract(state.store.get_file(f["id"])["path"]), jd)
        if best is None or after["score"] > best[1]["score"]:
            best = (f, after, meta, md)
        miss = [m["keyword"] for m in after["categories"]["keywords"].get("missing", [])][:12]
        if after["score"] >= 90 or attempt == 1 or not miss:
            break
        prompt2 = (f"{TAILOR_PROMPT}\n\nHere is a draft. Improve it: these job terms are still missing, add each one ONLY where the original resume really supports it (as a skill or inside a bullet): {', '.join(miss)}. "
                   f"Do not add anything the original resume does not support.\n\nDRAFT:\n{md}\n\nORIGINAL RESUME:\n{rtext[:9000]}")
        md2 = strip_fence(llm.complete(cfg, [{"role": "user", "content": prompt2}], SYSTEM_BASE))
        if md2.strip():
            md = md2
    f, after, meta, md = best
    after["before_score"] = before["score"] if before else None
    left = [m["keyword"] for m in after["categories"]["keywords"].get("missing", [])][:10]
    reply = f"Your tailored resume is ready: **{f['name']}**. ATS estimate: " + (f"**{before['score']:.0f} → {after['score']:.0f}/100**." if before else f"**{after['score']:.0f}/100**.")
    if left:
        reply += " Job terms left out because your resume does not show them: " + ", ".join(left) + ". Add them only if they are true for you."
    yield sse("delta", {"text": reply})
    return reply, [file_card(f, "Rewritten from your resume and the job description. Check every line is true before you send it.", meta["warnings"], meta["theme"]), {"type": "ats", "result": after}]


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


def estimate_fraction(elapsed: float, provider: str) -> float:
    """A smooth estimate (never 100% until the picture really exists), tuned per engine: it slows down as it approaches 92%."""
    tau = {"local": 8.0, "horde": 45.0, "pollinations": 18.0}.get(provider, 20.0)
    return 0.92 * (1 - math.exp(-elapsed / tau))


def _do_image(state: AssistantState, prompt: str, options: dict[str, Any]) -> Iterator[str]:
    """Makes the picture on a worker thread and streams progress events (an estimate plus the engine's real status text) until it is done."""
    cfg = state.image_config()
    box: dict[str, Any] = {}
    note = {"text": "Starting the picture engine…"}
    how = "none"
    idea = prompt
    if options.get("enhance", True):
        yield sse("progress", {"fraction": 0.02, "elapsed": 0.0, "text": "Writing a detailed description of your idea…", "estimated": True})
        prompt, how = enhance_prompt(state, prompt, "image")

    def work() -> None:
        try:
            box["out"] = images.generate_image(cfg, prompt, state.pictures, options.get("shape", "square"), options.get("seed"), hf_endpoint=options.get("hf_endpoint", ""),
                                               on_status=lambda t: note.update(text=t))
        except BaseException as exc:  # noqa: BLE001 - re-raised below on the request thread
            box["err"] = exc

    t0 = time.monotonic()
    th = threading.Thread(target=work, daemon=True)
    th.start()
    while th.is_alive():
        th.join(0.4)
        el = time.monotonic() - t0
        yield sse("progress", {"fraction": round(estimate_fraction(el, cfg.provider), 3), "elapsed": round(el, 1), "text": note["text"], "estimated": True})
    if "err" in box:
        raise box["err"]
    out = box["out"]
    yield sse("progress", {"fraction": 1.0, "elapsed": round(time.monotonic() - t0, 1), "text": "Done", "estimated": False})
    f = state.store.add_file("generated", out["name"], Path(out["path"]), "png")
    msg = f" I expanded your idea for more detail: “{prompt}”" if how in ("ai", "recipe") and prompt != idea else ""
    msg += " The free fallback service adds a small logo; install the on-this-PC picture model (Install everything) for logo-free pictures with no limits." if out.get("watermark") else ""
    if out.get("fallback_reason"):
        msg = f" Made by the free online engine because the one on this PC failed: {out['fallback_reason']}" + msg
    return f"Here is your image ({out['width']}×{out['height']}).{msg}", [{"type": "image", "file": f, "prompt": prompt, "width": out["width"], "height": out["height"], "provider": out["provider"]}]


def enhance_prompt(state: AssistantState, prompt: str, kind: str) -> tuple[str, str]:
    """A richer prompt from the connected chat model, or the built-in recipe when none is reachable."""
    cfg = state.llm_config()
    preset = llm.PRESETS.get(cfg.provider, {})
    ask = None
    if cfg.base_url and (not preset.get("needs_key") or cfg.api_key):
        short = replace(cfg, timeout=25.0, max_tokens=300, temperature=0.8)

        def ask(system: str, user: str) -> str:  # noqa: E306 - closure over the short-timeout config
            return llm.complete(short, [{"role": "user", "content": user}], system)
    return enhance.enhance(prompt, kind, ask)


def ask_about_image(state: AssistantState, image_path: Path, question: str) -> str:
    """Shows one picture to the connected chat model (if it can see pictures) and returns its short answer. Raises when no model is ready."""
    import base64
    import io

    from PIL import Image

    cfg = state.llm_config()
    preset = llm.PRESETS.get(cfg.provider, {})
    if not (cfg.base_url and cfg.model) or (preset.get("needs_key") and not cfg.api_key):
        raise llm.LLMError("No chat model is connected.")
    im = Image.open(image_path).convert("RGB")
    im.thumbnail((640, 640))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    short = replace(cfg, timeout=40.0, max_tokens=80, temperature=0.0)
    msg = {"role": "user", "content": question, "images": [{"media_type": "image/jpeg", "data": base64.b64encode(buf.getvalue()).decode()}]}
    return llm.complete(short, [msg], "")


def advice(state: AssistantState, ram_gb: float, vram_gb: float, gpu_name: str, gpu_ok: bool) -> dict[str, Any]:
    """Best local model, best free online service and best paid one for this PC, marking which ones already have a key saved."""
    from ..advisor import advise

    saved = state.settings.raw().get("providers", {})
    configured = {pid: bool(isinstance(v, dict) and v.get("api_key")) for pid, v in saved.items()}
    configured["pollinations"] = False  # works with no key but is never "connected" on purpose
    out = advise(ram_gb, vram_gb, gpu_name, gpu_ok, configured)
    cur = state.llm_config()
    preset = llm.PRESETS.get(cur.provider, {})
    out["current"] = {"provider": cur.provider, "name": preset.get("name", cur.provider), "model": cur.model,
                      "ready": bool(cur.base_url and cur.model) and (not preset.get("needs_key") or bool(cur.api_key))}
    return out


def _do_design(text: str, options: dict[str, Any]) -> tuple[str, list[dict]]:
    picks = recommend(text, options.get("doc_type", "document"), limit=5)
    top = picks[0]
    return f"Best match: **{top['name']}** ({'; '.join(top['reasons'][:2])}).", [{"type": "themes", "themes": picks, "request": text}]
