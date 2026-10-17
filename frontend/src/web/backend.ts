// The browser replacement for the desktop app's local server: the same /api calls, answered inside the page.
// Files, projects and settings stay in this browser. Nothing is uploaded except what you send to an AI service you chose.
/* eslint-disable @typescript-eslint/no-explicit-any */
import { ApiError } from "../lib/api";
import type { Asset, AssetKind, Job } from "../lib/types";
import { cancelFF, ensureFonts, ffRun, getFF, getPy, probeWithFF, pyCall, setLogSink } from "./engine";
import { idb, persist } from "../../../shared/web/idb";
import { complete, currentConfig, encodeImage, listModels, LLMError, loadSaved, PRESETS, savePatch, type Msg } from "../../../shared/web/llm";
import { blobOf, forget, hydrate, kindOf, probe, saveThumb } from "./media";
import { makeVideo, motionControl, type Helpers, type Made } from "./gen";
import { loadHF, saveHF, spaceStatus } from "./hf";
import { addHistory, noteProjectEdit } from "../../../shared/web/history";
import { markProjectDeleted } from "../../../shared/web/drive";

const rel = (p: string) => new URL(p, document.baseURI).href;
const uid = () => (crypto.randomUUID?.() ?? String(Date.now()) + Math.random().toString(16).slice(2)).replace(/-/g, "").slice(0, 12);
const NOT_HERE = "This part needs a graphics card and is only in the desktop version. In the browser you can edit, add sounds and text, and export.";

let started = false;
async function start(): Promise<void> { if (!started) { started = true; void persist(); } }

// ---------------------------------------------------------------- assets
type Rec = Asset & { ext: string; probed?: boolean };
let cache: Rec[] | null = null;
async function records(): Promise<Rec[]> {
  if (!cache) {
    cache = (await idb.all<Rec>("assets")).sort((a, b) => b.created - a.created);
    await Promise.all(cache.map(hydrate));
  }
  return cache;
}
async function putAsset(r: Rec): Promise<void> {
  await idb.put("assets", r.id, r);
  const c = await records();
  const i = c.findIndex((x) => x.id === r.id);
  if (i >= 0) c[i] = r; else c.unshift(r);
}
const pub = (r: Rec): Asset => { const { ext: _e, probed: _p, ...a } = r; void _e; void _p; return a; };

async function addFile(blob: Blob, name: string, kind: AssetKind, source: string, extra: Partial<Rec> = {}, id = uid()): Promise<Rec> {
  const info = await probe(blob, kind).catch(() => ({ duration: 0, width: 0, height: 0, thumb: "" }));
  const ext = (name.split(".").pop() || (blob.type.split("/")[1] ?? "bin")).toLowerCase().replace(/[^a-z0-9]/g, "") || "bin";
  await idb.put("blobs", id, blob);
  await saveThumb(id, info.thumb);
  const r: Rec = { id, kind, name, thumb: !!info.thumb, duration: info.duration, width: info.width, height: info.height, fps: 24, has_audio: kind === "audio" || kind === "video", source, meta: {}, created: Date.now() / 1000, ext, probed: kind === "image", ...extra };
  await putAsset(r);
  await hydrate(r);
  return r;
}

/** Streams and exact length come from ffmpeg (once per file). The export waits for this. */
async function ensureProbed(r: Rec): Promise<Rec> {
  if (r.probed || r.kind === "image") return r;
  const blob = await blobOf(r.id);
  if (!blob) return r;
  try {
    const m = await probeWithFF(blob, `${r.id}.${r.ext}`);
    r.has_audio = m.hasAudio; if (m.duration > 0) r.duration = m.duration; if (m.fps) r.fps = m.fps;
    if (m.width && m.height) { r.width = m.width; r.height = m.height; }
  } catch { /* keep the browser's numbers */ }
  r.probed = true;
  await putAsset(r);
  return r;
}

async function addSound(soundId: string): Promise<Rec> {
  const id = "snd-" + soundId;
  const have = (await records()).find((a) => a.id === id);
  if (have) return have;
  const list = await (await fetch(rel("data/sounds.json"))).json();
  const s = (list.sounds as { id: string; label: string; duration: number }[]).find((x) => x.id === soundId);
  if (!s) throw new ApiError("There is no such sound.", 404);
  const r = await fetch(rel(`data/sounds/${soundId}.mp3`));
  if (!r.ok) throw new ApiError("That sound could not be loaded. Check your internet connection.", 502);
  const blob = new Blob([await r.arrayBuffer()], { type: "audio/mpeg" });
  await idb.put("blobs", id, blob);
  const rec: Rec = { id, kind: "audio", name: s.label, thumb: false, duration: s.duration, width: 0, height: 0, fps: 0, has_audio: true, source: "sound", meta: { sound: soundId }, created: Date.now() / 1000, ext: "mp3", probed: true };
  await putAsset(rec); await hydrate(rec);
  return rec;
}

// ---------------------------------------------------------------- jobs
const jobs = new Map<string, Job>();
const cancels = new Map<string, () => void>();
function newJob(kind: string, title: string): Job {
  const j: Job = { id: uid(), kind, title, lane: "media", status: "running", progress: 0, phase: "Starting", result: null, error: null, created: Date.now() / 1000, elapsed: 0, eta: null };
  jobs.set(j.id, j);
  return j;
}
const listJobs = (): Job[] => {
  const now = Date.now() / 1000;
  return [...jobs.values()].map((j) => (j.status === "running" || j.status === "queued" ? { ...j, elapsed: now - j.created } : j)).sort((a, b) => b.created - a.created);
};

async function runExport(job: Job, project: any, opts: any): Promise<void> {
  const t0 = Date.now();
  const set = (p: number, phase: string) => { job.progress = Math.max(0, Math.min(1, p)); job.phase = phase; if (p > 0.03) job.eta = ((Date.now() - t0) / 1000) * (1 - p) / p; };
  let cancelled = false;
  cancels.set(job.id, () => { cancelled = true; void cancelFF(); });
  try {
    set(0.01, "Loading the video engine (first time only)");
    const refs = new Set<string>([...project.clips, ...project.audio, ...project.images, ...project.layers].map((x: any) => x.asset_id));
    const recs: Rec[] = [];
    for (const id of refs) {
      const r = (await records()).find((a) => a.id === id);
      if (!r) throw new ApiError("A file used by this project is no longer in the library.", 422);
      recs.push(await ensureProbed(r));
    }
    const [py, ff, catalog] = await Promise.all([getPy(), getFF(), fetch(rel("data/catalog.json")).then((r) => r.json())]);
    await ensureFonts(py, project.texts ?? [], catalog.fonts);
    set(0.03, "Preparing");
    const inDir = "/in", outDir = "/out", wd = "/wd";
    for (const d of [inDir, outDir, wd]) { try { await ff.createDir(d); } catch { /* exists */ } }
    try { await ff.unmount(inDir); } catch { /* not mounted */ }
    const blobs = await Promise.all(recs.map(async (r) => ({ name: `${r.id}.${r.ext}`, data: (await blobOf(r.id)) as Blob })));
    await ff.mount("WORKERFS", { blobs }, inDir);
    const assets = Object.fromEntries(recs.map((r) => [r.id, { path: `${inDir}/${r.id}.${r.ext}`, kind: r.kind, duration: r.duration, has_audio: r.has_audio, width: r.width, height: r.height }]));
    const ext: string = opts.format ?? "mp4";
    const out = `${outDir}/export.${ext}`;
    const plan = JSON.parse(await pyCall("plan_export", JSON.stringify(project), JSON.stringify(assets), JSON.stringify(opts), out, wd));
    if (plan.error) throw new ApiError(plan.error, 422);
    for (const f of plan.files as string[]) {
      const dir = f.slice(0, f.lastIndexOf("/"));
      let acc = "";
      for (const part of dir.split("/").filter(Boolean)) { acc += "/" + part; try { await ff.createDir(acc); } catch { /* exists */ } }
      await ff.writeFile(f, py.FS.readFile(f));
    }
    set(0.05, "Rendering");
    const total = Math.max(0.1, plan.total);
    const { rc, text } = await ffRun(["-y", ...(plan.args[0] === "ffmpeg" ? plan.args.slice(1) : plan.args)], (line) => {
      const m = /time=(\d+):(\d+):(\d+(?:\.\d+)?)/.exec(line);
      if (m) { const t = Number(m[1]) * 3600 + Number(m[2]) * 60 + Number(m[3]); set(0.05 + 0.93 * Math.min(1, t / total), `Rendering ${Math.round(Math.min(1, t / total) * 100)}%`); }
    });
    if (cancelled) { job.status = "cancelled"; job.phase = "Cancelled"; return; }
    if (rc !== 0) throw new ApiError("The video could not be made. " + (text.split("\n").filter((l) => /error|invalid|no such|unable/i.test(l)).slice(-2).join(" ") || "Try a smaller size or fewer effects."), 500);
    const data = (await ff.readFile(out)) as Uint8Array;
    const mime = ext === "webm" ? "video/webm" : ext === "gif" ? "image/gif" : "video/mp4";
    const blob = new Blob([data.slice().buffer], { type: mime });
    await ff.deleteFile(out).catch(() => undefined);
    for (const f of plan.files as string[]) await ff.deleteFile(f).catch(() => undefined);
    try { await ff.unmount(inDir); } catch { /* ignore */ }
    const made = await addFile(blob, `${project.name || "Video"}${opts.preview ? " (preview)" : ""}.${ext}`, "video", opts.preview ? "preview" : "export", { has_audio: !!opts.include_audio, probed: true, meta: { warnings: plan.warnings } });
    job.result = { asset_id: made.id, warnings: plan.warnings };
    job.progress = 1; job.phase = "Done"; job.status = "done";
    if (!opts.preview) void addHistory("export", project.name || "Video", `${ext.toUpperCase()} · ${Math.round(plan.total)} s`, made.id);
  } catch (e) {
    if (cancelled) { job.status = "cancelled"; job.phase = "Cancelled"; return; }
    job.status = "error"; job.error = e instanceof Error ? e.message : "The export failed.";
  } finally { cancels.delete(job.id); setLogSink(null); job.elapsed = (Date.now() - t0) / 1000; }
}


// ---------------------------------------------------------------- AI video on free Hugging Face GPUs (text, picture, continue, motion control)
async function runGen(job: Job, kind: "video" | "motion", make: (h: Helpers) => Promise<Made>): Promise<void> {
  const t0 = Date.now();
  const fns: (() => void)[] = [];
  const signal = { cancelled: false, on: (f: () => void) => { fns.push(f); } };
  cancels.set(job.id, () => { signal.cancelled = true; fns.forEach((f) => f()); });
  try {
    const made = await make({
      mustAsset, blobOf: (id) => blobOf(id), signal,
      stage: (s) => { job.phase = s.phase; job.progress = Math.max(job.progress, Math.min(0.97, s.fraction)); },
    });
    if (signal.cancelled) { job.status = "cancelled"; job.phase = "Cancelled"; return; }
    job.phase = "Saving to your library"; job.progress = 0.98;
    const rec = await addFile(made.blob, made.name, "video", "generated", { meta: made.meta, probed: false });
    job.result = { asset_id: rec.id };
    job.progress = 1; job.phase = "Done"; job.status = "done";
    void addHistory(kind, made.name.replace(/\.mp4$/, ""), `${made.meta.space ?? ""}`, rec.id);
  } catch (e) {
    if (signal.cancelled) { job.status = "cancelled"; job.phase = "Cancelled"; return; }
    job.status = "error"; job.error = e instanceof Error ? e.message : "The video could not be made.";
  } finally { cancels.delete(job.id); job.elapsed = (Date.now() - t0) / 1000; }
}

// ---------------------------------------------------------------- smart edits that run on ffmpeg / the canvas (free, no AI model needed)
async function scan(r: Rec, args: string[]): Promise<string> {
  const ff = await getFF();
  const dir = "/scan";
  try { await ff.createDir(dir); } catch { /* exists */ }
  try { await ff.unmount(dir); } catch { /* not mounted */ }
  const blob = await blobOf(r.id);
  if (!blob) throw new ApiError("The file is missing.", 422);
  await ff.mount("WORKERFS", { blobs: [{ name: `${r.id}.${r.ext}`, data: blob }] }, dir);
  try {
    const { rc, text } = await ffRun(["-hide_banner", "-nostats", "-i", `${dir}/${r.id}.${r.ext}`, ...args, "-f", "null", "-"]);
    if (rc !== 0) throw new ApiError("This file could not be analysed.", 422);
    return text;
  } finally { try { await ff.unmount(dir); } catch { /* ignore */ } }
}

function startJob(kind: string, title: string, fn: (set: (p: number, phase: string) => void) => Promise<Record<string, any>>): Job {
  const job = newJob(kind, title);
  const t0 = Date.now();
  void fn((p, phase) => { job.progress = p; job.phase = phase; })
    .then((res) => { job.result = res; job.progress = 1; job.phase = "Done"; job.status = "done"; })
    .catch((e) => { job.status = "error"; job.error = e instanceof Error ? e.message : "That did not work."; })
    .finally(() => { job.elapsed = (Date.now() - t0) / 1000; });
  return job;
}

async function silenceJob(body: any): Promise<Job> {
  const r = await ensureProbed(await mustAsset(body.asset_id));
  const o = body.options ?? {};
  return startJob("ai", `Find silences: ${r.name}`, async (set) => {
    set(0.1, "Listening");
    const out = await scan(r, ["-vn", "-af", `silencedetect=noise=${Number(o.noise_db ?? -35)}dB:d=${Number(o.min_silence ?? 0.6)}`]);
    const dur = r.duration, pad = 0.12;
    const starts = [...out.matchAll(/silence_start: (-?[\d.]+)/g)].map((m) => Number(m[1]));
    const ends = [...out.matchAll(/silence_end: ([\d.]+)/g)].map((m) => Number(m[1]));
    const sil = starts.map((s, i) => [Math.max(0, s), Math.min(dur, ends[i] ?? dur)] as [number, number]);
    let keep: [number, number][] = [];
    let cursor = 0;
    for (const [s, e] of sil) { const a = cursor, b = Math.min(dur, s + pad); if (b - a > 0.15) keep.push([a, b]); cursor = Math.max(0, e - pad); }
    if (dur - cursor > 0.15) keep.push([cursor, dur]);
    if (!keep.length) keep = [[0, dur]];
    const start = Number(body.trim_in ?? 0), end = start + (body.trim_out > 0 ? body.trim_out - start : dur - start);
    const inside = keep.map(([s, e]) => [Math.max(s, start), Math.min(e, end)] as [number, number]).filter(([s, e]) => e > s && e - s > 0.15);
    return { keep: inside, silences: sil, removed: Math.max(0, dur - keep.reduce((n, [a, b]) => n + b - a, 0)) };
  });
}

async function scenesJob(body: any): Promise<Job> {
  const r = await ensureProbed(await mustAsset(body.asset_id));
  return startJob("ai", `Find scenes: ${r.name}`, async (set) => {
    set(0.1, "Looking for cuts");
    const out = await scan(r, ["-an", "-vf", "select='gt(scene,0.35)',showinfo"]);
    const cuts = [...new Set([...out.matchAll(/pts_time:([\d.]+)/g)].map((m) => Math.round(Number(m[1]) * 1000) / 1000))].sort((a, b) => a - b).filter((c) => c > 0.3 && c < r.duration - 0.3);
    const merged: number[] = [];
    for (const c of cuts) if (!merged.length || c - merged[merged.length - 1] >= 0.5) merged.push(c);
    return { cuts: merged };
  });
}

async function enhanceNow(body: any): Promise<Record<string, number>> {
  const r = await mustAsset(body.asset_id);
  const blob = await blobOf(r.id);
  if (!blob) throw new ApiError("The file is missing.", 422);
  const url = URL.createObjectURL(blob);
  try {
    const c = document.createElement("canvas"); c.width = 320; c.height = Math.max(1, Math.round((320 * (r.height || 9)) / (r.width || 16)));
    const g = c.getContext("2d", { willReadFrequently: true })!;
    if (r.kind === "image") { const im = new Image(); im.src = url; await im.decode(); g.drawImage(im, 0, 0, c.width, c.height); }
    else {
      const v = document.createElement("video"); v.muted = true; v.src = url; await new Promise<void>((res, rej) => { v.onloadeddata = () => res(); v.onerror = () => rej(new Error("The video could not be read.")); });
      const at = Number(body.trim_in ?? 0) + (Math.max(0.2, (body.trim_out > 0 ? body.trim_out : r.duration) - Number(body.trim_in ?? 0)) / 2);
      v.currentTime = Math.min(at, Math.max(0, r.duration - 0.1)); await new Promise<void>((res) => { v.onseeked = () => res(); });
      g.drawImage(v, 0, 0, c.width, c.height);
    }
    const px = g.getImageData(0, 0, c.width, c.height).data;
    const luma: number[] = []; let sat = 0;
    for (let i = 0; i < px.length; i += 4) {
      const R = px[i] / 255, G = px[i + 1] / 255, B = px[i + 2] / 255;
      luma.push(0.299 * R + 0.587 * G + 0.114 * B);
      const mx = Math.max(R, G, B), mn = Math.min(R, G, B); sat += (mx - mn) / (mx + 1e-6);
    }
    luma.sort((a, b) => a - b);
    const pct = (q: number) => luma[Math.min(luma.length - 1, Math.floor((q / 100) * luma.length))];
    const p2 = pct(2), p50 = pct(50), p98 = pct(98); sat /= luma.length;
    const clip = (x: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, x));
    const spread = Math.max(0.05, p98 - p2);
    const contrast = clip((0.88 / spread - 1) * 55, -20, 60), brightness = clip((0.46 - p50) * 70, -30, 40);
    const gamma = p50 < 0.35 ? clip(Math.log(Math.max(0.05, Math.min(0.95, p50))) / Math.log(0.46), 1, 1.6) : 1;
    const saturation = clip((0.38 - sat) * 120, -10, 40);
    const r1 = (x: number) => Math.round(x * 10) / 10;
    return { brightness: r1(brightness * (gamma !== 1 ? 0.6 : 1)), contrast: r1(contrast), saturation: r1(saturation), gamma: Math.round(gamma * 100) / 100, hue: 0 };
  } finally { URL.revokeObjectURL(url); }
}

async function mustAsset(id: string): Promise<Rec> {
  const r = (await records()).find((a) => a.id === id);
  if (!r) throw new ApiError("That file is no longer in the library.", 422);
  return r;
}

// ---------------------------------------------------------------- chat
async function chatTurn(body: { messages: { role: "user" | "assistant"; content: string; image_ids?: string[] }[]; project: any }): Promise<any> {
  const cfg = currentConfig();
  const all = await records();
  const assets = Object.fromEntries(all.map((a) => [a.id, { name: a.name, kind: a.kind, duration: a.duration, width: a.width, height: a.height, has_audio: a.has_audio }]));
  const last = body.messages.length - 1;
  const msgs: Msg[] = [];
  let nImg = 0;
  for (let k = 0; k < body.messages.length; k++) {
    const m = body.messages[k];
    const row: Msg = { role: m.role, content: m.content };
    if (m.role === "user" && k >= last - 1) {
      const imgs = [];
      for (const iid of m.image_ids ?? []) { const a = all.find((x) => x.id === iid); const b = a && a.kind === "image" ? await blobOf(iid) : undefined; if (b) imgs.push(await encodeImage(b)); }
      if (imgs.length) { row.images = imgs; nImg += imgs.length; }
    }
    msgs.push(row);
  }
  const attached = (body.messages[last].image_ids ?? []).filter((i) => all.some((a) => a.id === i && a.kind === "image"));
  const system: string = (await pyCall("chat_prompt", JSON.stringify(body.project), JSON.stringify(assets), JSON.stringify(attached), nImg > 0))
    + '\n\nBROWSER VERSION: these task types are NOT available here and must never be used: captions, follow_person, beat_cut, voiceover, generate_video, soundtrack, ai_edit. The tasks cut_silence, scene_split and auto_enhance do work. If the person asks for something that needs an unavailable task, say in the reply that it needs the desktop app, and offer the closest thing that works here (for example a text overlay instead of captions).';
  const jsonMode = cfg.style === "openai" && !["ollama", "lmstudio"].includes(cfg.provider);
  const ask = (extra: Msg[], json: boolean) => complete(cfg, [...msgs, ...extra], system, json);
  let parsed: any;
  try {
    let text: string;
    try { text = await ask([], jsonMode); } catch (e) {
      if (e instanceof LLMError && cfg.style === "openai" && /response_format|json/i.test(e.message)) text = await ask([], false); else throw e;
    }
    parsed = JSON.parse(await pyCall("chat_parse", text));
    const edit = await pyCall("chat_wants_edit", body.messages[last].content);
    if (!parsed.ok || (!parsed.actions.length && edit)) {
      const retry: Msg[] = [{ role: "assistant", content: text.slice(0, 1500) }, { role: "user", content: 'Answer again with ONLY the JSON object {"reply": "...", "actions": [...]}. Every action needs a "do" field. If the request needs a change to the video, include the actions that make it.' }];
      const again = JSON.parse(await pyCall("chat_parse", await ask(retry, false)));
      if (again.ok && (again.actions.length || !parsed.ok)) parsed = again;
    }
  } catch (e) {
    if (e instanceof LLMError) throw new ApiError(e.message, 502);
    throw e;
  }
  const out = JSON.parse(await pyCall("chat_apply", JSON.stringify(body.project), JSON.stringify(parsed.actions), JSON.stringify(assets), JSON.stringify(attached)));
  for (const id of out.new_assets as string[]) await addSound(id.replace(/^snd-/, ""));
  return { reply: parsed.reply, project: out.project, applied: out.applied, skipped: out.skipped, tasks: out.tasks, changed: out.changed, focus: out.focus, understood: parsed.ok, new_assets: out.new_assets };
}

// ---------------------------------------------------------------- settings
const SKEY = "vk_web_settings";
const defaultSettings = { profile: "web", memory_mode: "", hf_endpoint: "", default_model: "", compute_dtype: "", keep_loaded: false, output_fps: 24, time_limit_min: 0, tour_done: false, sharpen_output: false, auto_enhance: false, ai_upscale: false };
const readSettings = () => { try { return { ...defaultSettings, ...JSON.parse(localStorage.getItem(SKEY) ?? "{}") }; } catch { return { ...defaultSettings }; } };

const staticJson = async (p: string) => { const r = await fetch(rel(p)); if (!r.ok) throw new ApiError("Part of the site is missing. Reload the page.", 502); return r.json(); };
const assistantSettings = () => { const s = loadSaved(); return { provider: s.provider, providers: Object.fromEntries(Object.entries(s.providers).map(([k, v]) => [k, { base_url: v.base_url, model: v.model, api_key_hint: v.api_key ? "…" + v.api_key.slice(-4) : "" }])) }; };

export async function webCall(method: string, path: string, body?: any, form?: FormData): Promise<any> {
  await start();
  const [p] = path.split("?");
  let m: RegExpExecArray | null;
  const is = (me: string, re: RegExp) => method === me && (m = re.exec(p)) !== null;

  if (is("GET", /^\/system$/)) return { version: "1.2.14", os: "browser", cpu_count: navigator.hardwareConcurrency || 4, ram_gb: (navigator as any).deviceMemory || 4, gpu: { available: false, name: "", vram_gb: 0, compute_capability: null, arch_supported: false, problem: null }, torch: null, ffmpeg: true, warnings: [], profile: "web", disk_free_gb: 0, data_dir: "This browser", requires_models: false, low_ram: false };
  if (is("GET", /^\/limits$/)) return { profile: { id: "web", label: "Browser", description: "", max_frames: 0, max_side: 1920, max_tokens: 0, default_width: 1280, default_height: 720, default_frames: 0, resolutions: [] }, profiles: [], models: [], default_model: "", fps: 24 };
  if (is("GET", /^\/settings$/)) return readSettings();
  if (is("PUT", /^\/settings$/)) { const s = { ...readSettings(), ...body }; try { localStorage.setItem(SKEY, JSON.stringify(s)); } catch { /* ignore */ } return s; }
  if (is("GET", /^\/models$/)) return { items: [], endpoint: "" };
  if (is("GET", /^\/usage$/)) return { cpu: null, ram_used_gb: null, ram_total_gb: null, gpu: null, vram_used_gb: null, vram_total_gb: null };

  if (is("GET", /^\/jobs$/)) return listJobs();
  if (is("POST", /^\/jobs\/([^/]+)\/cancel$/)) { cancels.get(m![1])?.(); return { ok: true }; }

  if (is("GET", /^\/assets$/)) return (await records()).map(pub);
  if (is("POST", /^\/assets\/upload$/)) {
    const file = form?.get("file") as File | null;
    if (!file) throw new ApiError("No file was chosen.", 422);
    const kind = kindOf(file);
    if (!kind) throw new ApiError("This kind of file is not supported. Use a video (MP4, WebM, MOV), a song (MP3, WAV) or a picture (PNG, JPG).", 422);
    try { return pub(await addFile(file, file.name, kind, "upload")); } catch (e) { throw new ApiError(e instanceof Error ? e.message : "The file could not be added.", 422); }
  }
  if (is("PATCH", /^\/assets\/([^/]+)$/)) { const r = (await records()).find((a) => a.id === m![1]); if (r) { r.name = String(body?.name ?? r.name); await putAsset(r); } return { ok: true }; }
  if (is("DELETE", /^\/assets\/([^/]+)$/)) { const id = m![1]; await idb.del("assets", id); await idb.del("blobs", id); await idb.del("blobs", id + ":thumb"); forget(id); cache = (await records()).filter((a) => a.id !== id); return { ok: true }; }

  if (is("GET", /^\/editor\/catalog$/)) return staticJson("data/catalog.json");
  if (is("GET", /^\/editor\/sounds$/)) return staticJson("data/sounds.json");
  if (is("POST", /^\/editor\/sounds\/([^/]+)\/add$/)) return pub(await addSound(m![1]));
  if (is("GET", /^\/editor\/tools$/)) return [];
  if (is("GET", /^\/editor\/ai\/(voices|ambiences)$/)) return m![1] === "voices" ? { voices: [] } : { ambiences: [] };

  if (is("POST", /^\/editor\/ai\/silence$/)) return silenceJob(body);
  if (is("POST", /^\/editor\/ai\/scenes$/)) return scenesJob(body);
  if (is("POST", /^\/editor\/ai\/enhance$/)) return enhanceNow(body);

  if (is("POST", /^\/editor\/export$/)) {
    const job = newJob("export", `${body.options?.preview ? "Preview" : "Export"}: ${body.project?.name ?? "Video"}`);
    void runExport(job, body.project, body.options ?? {});
    return job;
  }

  if (is("POST", /^\/web\/video$/)) {
    const job = newJob("video", `${body.mode === "extend" ? "Continue" : body.mode === "i2v" ? "Picture to video" : "Text to video"}: ${String(body.prompt ?? "").slice(0, 40) || "clip"}`);
    void runGen(job, "video", (h) => makeVideo(h, body));
    return job;
  }
  if (is("POST", /^\/web\/motion$/)) {
    const job = newJob("motion", "Motion control");
    void runGen(job, "motion", (h) => motionControl(h, body));
    return job;
  }
  if (is("GET", /^\/web\/hf$/)) { const c = loadHF(); return { has_token: !!c.token, ltx: c.ltx, animate: c.animate }; }
  if (is("PUT", /^\/web\/hf$/)) { const c = saveHF({ ...(body.token !== undefined ? { token: String(body.token).trim() } : {}), ...(body.ltx ? { ltx: String(body.ltx).trim() } : {}), ...(body.animate ? { animate: String(body.animate).trim() } : {}) }); return { has_token: !!c.token, ltx: c.ltx, animate: c.animate }; }
  if (is("GET", /^\/web\/hf\/status$/)) { const c = loadHF(); const [a, b] = await Promise.all([spaceStatus(c.ltx), spaceStatus(c.animate)]); return { ltx: a, animate: b }; }

  if (is("POST", /^\/editor\/chat$/)) return chatTurn(body);
  if (is("GET", /^\/editor\/chat\/status$/)) {
    const c = currentConfig(); const pr = PRESETS[c.provider];
    if (!c.provider) return { ready: false, why: "provider" };
    const needs = !!pr?.needs_key && !c.api_key;
    return { ready: !!c.base_url && !!c.model && !needs, provider: c.provider, name: pr?.name ?? c.provider, model: c.model, why: needs ? "key" : !c.model ? "model" : "" };
  }
  if (is("GET", /^\/assistant\/info$/)) return { providers: Object.fromEntries(Object.entries(PRESETS).map(([k, v]) => [k, v])) };
  if (is("GET", /^\/assistant\/settings$/)) return assistantSettings();
  if (is("PUT", /^\/assistant\/settings$/)) { savePatch(body ?? {}); return assistantSettings(); }
  if (is("GET", /^\/assistant\/models$/)) return { models: await listModels(currentConfig()) };
  if (is("POST", /^\/assistant\/settings\/test$/)) {
    try { const r = await complete(currentConfig(), [{ role: "user", content: "Reply with the single word OK." }], ""); return { ok: true, reply: r.slice(0, 80) }; }
    catch (e) { throw new ApiError(e instanceof Error ? e.message : "The AI did not answer.", 502); }
  }
  if (is("GET", /^\/ai\/advice$/)) return { video: "", local: "", cloud: "", providers: [] };

  if (is("GET", /^\/projects$/)) return (await idb.all<any>("projects")).map((p) => ({ id: p.id, name: p.name, updated: p.updated ?? 0 })).sort((a, b) => b.updated - a.updated);
  if (is("GET", /^\/projects\/([^/]+)$/)) { const p = await idb.get<any>("projects", m![1]); if (!p) throw new ApiError("That project was not found.", 404); return p; }
  if (is("PUT", /^\/projects\/([^/]+)$/)) {
    const id = m![1];
    const had = await idb.get<any>("projects", id);
    await idb.put("projects", id, { ...body, id, updated: Date.now() / 1000 });
    if (!had) void addHistory("project_new", body?.name || "Untitled project", undefined, id); else void noteProjectEdit(id, body?.name || "Untitled project");
    window.dispatchEvent(new Event("vk-dirty"));
    return { ok: true };
  }
  if (is("DELETE", /^\/projects\/([^/]+)$/)) { await idb.del("projects", m![1]); await markProjectDeleted(m![1]); return { ok: true }; }

  throw new ApiError(NOT_HERE, 501);
}
