// The video engine in the browser: Pyodide runs the same Python editor engine as the desktop app,
// ffmpeg.wasm does the encoding. Both load on first use and are cached by the browser afterwards.
/* eslint-disable @typescript-eslint/no-explicit-any */

const base = (p: string) => new URL("engine/" + p, document.baseURI).href;

const scripts = new Map<string, Promise<void>>();
function loadScript(src: string): Promise<void> {
  let p = scripts.get(src);
  if (!p) {
    p = new Promise<void>((resolve, reject) => {
      const s = document.createElement("script");
      s.src = src; s.async = true;
      s.onload = () => resolve();
      s.onerror = () => { scripts.delete(src); reject(new Error("Could not load part of the editor engine. Check your internet connection and reload the page.")); };
      document.head.appendChild(s);
    });
    scripts.set(src, p);
  }
  return p;
}

// ---------------------------------------------------------------- ffmpeg.wasm
export interface FF {
  exec(args: string[], timeout?: number): Promise<number>;
  writeFile(path: string, data: Uint8Array | string): Promise<boolean>;
  readFile(path: string): Promise<Uint8Array | string>;
  deleteFile(path: string): Promise<boolean>;
  createDir(path: string): Promise<boolean>;
  mount(type: string, opts: { blobs?: { name: string; data: Blob }[]; files?: File[] }, point: string): Promise<boolean>;
  unmount(point: string): Promise<boolean>;
  terminate(): void;
  load(cfg: { coreURL: string; wasmURL: string }): Promise<boolean>;
  on(ev: "log" | "progress", cb: (e: any) => void): void;
}

let ffp: Promise<FF> | null = null;
let logSink: ((line: string) => void) | null = null;
export const setLogSink = (fn: ((line: string) => void) | null) => { logSink = fn; };

export function getFF(): Promise<FF> {
  if (!ffp) {
    ffp = (async () => {
      await loadScript(base("ffmpeg/ffmpeg.js"));
      const ff: FF = new (window as any).FFmpegWASM.FFmpeg();
      ff.on("log", ({ message }: { message: string }) => { logSink?.(message); });
      await ff.load({ coreURL: base("ffmpeg/ffmpeg-core.js"), wasmURL: base("ffmpeg/ffmpeg-core.wasm") });
      return ff;
    })();
    ffp.catch(() => { ffp = null; });
  }
  return ffp;
}

/** Stops whatever ffmpeg is doing; the next call starts a fresh copy. */
export async function cancelFF(): Promise<void> {
  const p = ffp; ffp = null;
  try { (await p)?.terminate(); } catch { /* already gone */ }
}

export async function ffRun(args: string[], onLine?: (l: string) => void): Promise<{ rc: number; text: string }> {
  const ff = await getFF();
  const lines: string[] = [];
  setLogSink((l) => { lines.push(l); onLine?.(l); });
  try {
    const rc = await ff.exec(args);
    return { rc, text: lines.join("\n") };
  } finally { setLogSink(null); }
}

export interface MediaInfo { duration: number; hasAudio: boolean; hasVideo: boolean; width: number; height: number; fps: number }

/** Reads a file's streams with ffmpeg without copying it into memory (the file is mounted). */
export async function probeWithFF(blob: Blob, name: string): Promise<MediaInfo> {
  const ff = await getFF();
  const dir = "/probe";
  try { await ff.createDir(dir); } catch { /* exists */ }
  await ff.mount("WORKERFS", { blobs: [{ name, data: blob }] }, dir);
  try {
    const { text } = await ffRun(["-hide_banner", "-i", `${dir}/${name}`]);
    const d = /Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)/.exec(text);
    const v = /Stream #\S+.*Video:.*?(\d{2,5})x(\d{2,5})/.exec(text);
    const fps = /(\d+(?:\.\d+)?)\s*fps/.exec(text);
    return {
      duration: d ? Number(d[1]) * 3600 + Number(d[2]) * 60 + Number(d[3]) : 0,
      hasAudio: /Stream #\S+.*Audio:/.test(text), hasVideo: !!v,
      width: v ? Number(v[1]) : 0, height: v ? Number(v[2]) : 0, fps: fps ? Number(fps[1]) : 0,
    };
  } finally { try { await ff.unmount(dir); } catch { /* ignore */ } }
}

// ---------------------------------------------------------------- Pyodide + the Python editor engine
let pyp: Promise<any> | null = null;
const MODULES = ["__init__", "effects", "audiofx", "soundfx", "fonts", "project", "textimage", "drawimage", "render", "chat", "media"];

const BRIDGE = `
import json, sys
sys.path.insert(0, "/py")
from pathlib import Path
from types import SimpleNamespace
from ltxps.editor import render, chat, soundfx
from ltxps.editor.render import AssetRef, build_plan, PlanError
from ltxps.editor.project import Project, ExportOptions
render._FFMPEG_MAJOR = 5

def plan_export(project_json, assets_json, options_json, out, work):
    project = Project.model_validate_json(project_json)
    opts = ExportOptions.model_validate_json(options_json)
    assets = {k: AssetRef(Path(v["path"]), v["kind"], float(v["duration"]), bool(v["has_audio"]), int(v["width"]), int(v["height"])) for k, v in json.loads(assets_json).items()}
    Path(work).mkdir(parents=True, exist_ok=True)
    try:
        plan = build_plan(project, assets, opts, Path(out), Path(work))
    except PlanError as exc:
        return json.dumps({"error": str(exc)})
    files = [str(p) for p in Path(work).rglob("*") if p.is_file()]
    return json.dumps({"args": plan.args, "warnings": plan.warnings, "total": plan.total, "files": files})

def _names(assets):
    return {k: v["name"] for k, v in assets.items()}

def chat_prompt(project_json, assets_json, attached_json, has_images):
    assets = json.loads(assets_json); attached = json.loads(attached_json)
    names = _names(assets); durations = {k: float(v["duration"]) for k, v in assets.items()}
    library = [v["name"] for v in assets.values() if v["kind"] in ("video", "audio", "image")]
    return chat.system_prompt(chat.describe(Project.model_validate_json(project_json), names, durations), library, bool(has_images), [names[i] for i in attached if i in names])

def chat_parse(text):
    return json.dumps(chat.parse_answer(text))

def chat_wants_edit(text):
    return bool(chat.looks_like_edit_request(text))

def chat_apply(project_json, actions_json, assets_json, attached_json):
    raw = json.loads(assets_json)
    assets = {k: SimpleNamespace(id=k, name=v["name"], kind=v["kind"], duration=float(v["duration"]), width=int(v["width"]), height=int(v["height"]), has_audio=bool(v["has_audio"])) for k, v in raw.items()}
    names = _names(raw); made = []
    def sound(sid):
        label, group, dur, _r = soundfx.SOUNDS[sid]
        a = SimpleNamespace(id="snd-" + sid, name=label, kind="audio", duration=float(dur), width=0, height=0, has_audio=True)
        assets[a.id] = a; made.append(a.id)
        return a
    project = Project.model_validate_json(project_json)
    out = chat.apply_actions(project, json.loads(actions_json), names, {"attached": json.loads(attached_json), "assets": assets, "sound": sound})
    new = out["project"]
    return json.dumps({"project": json.loads(new.model_dump_json()), "applied": out["applied"], "skipped": out["skipped"], "tasks": out["tasks"],
                       "changed": bool(out["applied"]) and new.model_dump() != project.model_dump(), "focus": out["focus"], "new_assets": made})
`;

export function getPy(): Promise<any> {
  if (!pyp) {
    pyp = (async () => {
      await loadScript(base("pyodide/pyodide.js"));
      const py = await (window as any).loadPyodide({ indexURL: base("pyodide/") });
      await py.loadPackage(["pydantic", "pillow"]);
      py.FS.mkdirTree("/py/ltxps/editor");
      py.FS.writeFile("/py/ltxps/__init__.py", await (await fetch(base("py/ltxps/__init__.py"))).text());
      await Promise.all(MODULES.map(async (m) => {
        const r = await fetch(base(`py/ltxps/editor/${m}.py`));
        if (!r.ok) throw new Error("Part of the editor engine is missing from this site.");
        py.FS.writeFile(`/py/ltxps/editor/${m}.py`, await r.text());
      }));
      // fonts.json lets the engine find the fonts that are copied in on demand (see ensureFonts).
      py.FS.mkdirTree("/py/ltxps/editor/fonts");
      py.FS.writeFile("/py/ltxps/editor/fonts/fonts.json", await (await fetch(new URL("fonts/fonts.json", document.baseURI).href)).text());
      py.runPython(BRIDGE);
      return py;
    })();
    pyp.catch(() => { pyp = null; });
  }
  return pyp;
}

const fontCache = new Set<string>();
async function putFont(py: any, file: string): Promise<void> {
  if (fontCache.has(file)) return;
  const r = await fetch(new URL("fonts/" + encodeURIComponent(file), document.baseURI).href);
  if (!r.ok) return;
  py.FS.writeFile("/py/ltxps/editor/fonts/" + file, new Uint8Array(await r.arrayBuffer()));
  fontCache.add(file);
}

/** Copies the fonts a project's text needs into the engine (the rest are never downloaded). */
export async function ensureFonts(py: any, texts: { text?: string; font?: string; bold?: boolean }[], fonts: { id: string; file: string; file_bold: string }[]): Promise<void> {
  const want = new Set<string>(["montserrat"]);
  let nonLatin = false;
  for (const t of texts) {
    if (t.font) want.add(t.font);
    if (/[^\u0000-ɏ -⁯]/.test(t.text ?? "")) nonLatin = true;
  }
  if (nonLatin) for (const f of fonts) if (f.id.startsWith("notosans")) want.add(f.id);
  for (const f of fonts) if (want.has(f.id)) { await putFont(py, f.file); if (f.file_bold !== f.file) await putFont(py, f.file_bold); }
}

export async function pyCall(fn: string, ...args: unknown[]): Promise<any> {
  const py = await getPy();
  const f = py.globals.get(fn);
  try {
    const r = f(...args);
    return typeof r === "string" ? r : r;
  } finally { f.destroy?.(); }
}
