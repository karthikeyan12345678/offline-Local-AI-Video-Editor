"""Browser bridge for the AI Assistant (runs in Pyodide).

The real assistant code (documents, extract, ats, compare, analytics, themes, reference, enhance) runs unchanged.
Only the parts that need a server are replaced: sqlite and httpx are stubbed (the browser keeps the data and does the web requests in TypeScript).
Every function takes and returns JSON text, and reads / writes files under /work.
"""
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, "/py")


def _stub(name):
    try:
        __import__(name)
        return
    except ImportError:
        pass

    class _Any:
        def __init__(self, *a, **k): ...
        def __getattr__(self, _): return _Any()
        def __call__(self, *a, **k): return _Any()

    m = types.ModuleType(name)
    m.__getattr__ = lambda attr: _Any  # type: ignore[attr-defined]
    sys.modules[name] = m


_stub("sqlite3")
_stub("httpx")

from ltxps.assistant import analytics, ats, compare, enhance, reference, service  # noqa: E402
from ltxps.assistant.documents import FORMATS  # noqa: E402
from ltxps.assistant.extract import ExtractError, SUPPORTED, extract  # noqa: E402
from ltxps.assistant.themes import catalog, get_theme, recommend  # noqa: E402

OUT = Path("/work/out")
OUT.mkdir(parents=True, exist_ok=True)


def _ok(**kw):
    return json.dumps({"ok": True, **kw}, ensure_ascii=False, default=str)


def _fail(e):
    return json.dumps({"ok": False, "error": str(e), "kind": type(e).__name__}, ensure_ascii=False)


def guarded(fn):
    def run(*a):
        try:
            return fn(*a)
        except (ExtractError, ValueError) as e:
            return _fail(e)
        except Exception as e:  # noqa: BLE001
            return _fail(f"{type(e).__name__}: {str(e)[:200]}")
    return run


@guarded
def info():
    return _ok(formats=list(FORMATS), supported=sorted(SUPPORTED), themes=len(catalog()))


@guarded
def detect(text, n_files):
    i = service.detect_intent(text, int(n_files))
    return _ok(kind=i.kind, text=i.text)


@guarded
def themes(purpose, doc_type, limit):
    items = [t.to_json() for t in catalog().values()]
    return _ok(themes=items, recommended=recommend(purpose, doc_type, limit=max(1, min(int(limit), 20))) if purpose.strip() else [])


@guarded
def design(text, doc_type):
    picks = recommend(text, doc_type or "document", limit=5)
    return _ok(themes=picks)


@guarded
def make_doc(fmt, md, request, theme_id, default_theme, title):
    """Builds the file. Returns the path of the new file under /work/out and the theme details."""
    store = SimpleNamespace(add_file=lambda origin, name, path, kind: {"path": str(path), "name": name, "kind": kind})
    state = SimpleNamespace(generated=OUT, settings=SimpleNamespace(raw=lambda: {"default_theme": default_theme or "claude"}), store=store)
    f, meta = service.make_document(state, fmt, md, request, theme_id or None, title)
    return _ok(file=f, **meta)


@guarded
def looks_md(t):
    return _ok(value=service.looks_like_markdown(t), stripped=service.strip_fence(t))


@guarded
def context(items_json, limit):
    """items: [{id,name,path}]. The text of the attached files, trimmed for the chat model."""
    items = {i["id"]: i for i in json.loads(items_json)}
    state = SimpleNamespace(store=SimpleNamespace(get_file=lambda fid: items.get(fid)))
    text, errs = service.attachment_context(state, list(items), int(limit))
    return _ok(text=text, errors=errs)


@guarded
def ref_profile(path):
    p = reference.profile(path)
    th = reference.theme_from(p)
    return _ok(profile=p, theme=th.id if th else None)


@guarded
def ref_instructions(profile_json, fmt):
    return _ok(text=reference.instructions(json.loads(profile_json), fmt))


@guarded
def ats_file(path, jd):
    return _ok(result=ats.check_file(path, jd))


@guarded
def ats_resume(path, jd):
    return _ok(result=ats.check_resume(extract(path), jd))


@guarded
def ats_keywords(jd):
    return _ok(keywords=ats.jd_keywords(jd))


@guarded
def tailor_inputs(files_json, text, jd_option):
    files = json.loads(files_json)
    rf, rtext, jd = service._tailor_inputs(None, files, text, {"job_description": jd_option})
    return _ok(resume=rf, resume_text=rtext, jd=jd)


@guarded
def compare_pair(a, b):
    r = compare.compare_files(a, b)
    return _ok(result=r, markdown=compare.to_markdown(r), headline=compare.headline(r))


@guarded
def analyze(path):
    return _ok(result=analytics.analyze_file(path))


@guarded
def enhance_prompt(prompt, kind, ai_text):
    """ai_text is what the chat model answered ("" when none is connected); the recipe is the fallback, exactly as on the desktop."""
    better, how = enhance.enhance(prompt, kind, (lambda s, u: ai_text) if ai_text else None)
    return _ok(prompt=better, how=how)


@guarded
def enhance_systems():
    return _ok(image=enhance.IMAGE_SYSTEM, video=enhance.VIDEO_SYSTEM)


@guarded
def constants():
    return _ok(doc_prompts=service.DOC_PROMPTS, system_base=service.SYSTEM_BASE, tailor_prompt=service.TAILOR_PROMPT)
