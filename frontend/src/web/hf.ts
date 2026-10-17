// Free GPU video through Hugging Face "Spaces". The video models run on Hugging Face's free ZeroGPU graphics cards,
// not on this site. A free Hugging Face account gets a few minutes of GPU time per day that renews on its own.
// The token you paste is kept in this browser only and is sent only to Hugging Face.
/* eslint-disable @typescript-eslint/no-explicit-any */
import { Client, handle_file } from "@gradio/client";
import { recordUse } from "../../../shared/web/quota";

export const DEFAULT_SPACES = { ltx: "Lightricks/ltx-video-distilled", animate: "alexnasa/Wan2.2-Animate-ZEROGPU" } as const;
const KEY = "vk_hf_v1";

export interface HFConfig { token: string; ltx: string; animate: string }
export function loadHF(): HFConfig {
  try { const s = JSON.parse(localStorage.getItem(KEY) ?? "null"); if (s) return { token: s.token ?? "", ltx: s.ltx || DEFAULT_SPACES.ltx, animate: s.animate || DEFAULT_SPACES.animate }; } catch { /* ignore */ }
  return { token: "", ltx: DEFAULT_SPACES.ltx, animate: DEFAULT_SPACES.animate };
}
export function saveHF(patch: Partial<HFConfig>): HFConfig {
  const c = { ...loadHF(), ...patch };
  try { localStorage.setItem(KEY, JSON.stringify(c)); } catch { /* ignore */ }
  window.dispatchEvent(new Event("vk-hf"));
  return c;
}

export class HFError extends Error {}

export type Stage = { phase: string; fraction: number };

const spaceKey = (id: string) => id.trim().replace(/^https?:\/\/huggingface\.co\/spaces\//, "").replace(/\/+$/, "");

/** Is the Space awake? (Free Spaces go to sleep and need a few minutes to start.) */
export async function spaceStatus(id: string): Promise<{ stage: string; hardware: string; ok: boolean; text: string }> {
  const sp = spaceKey(id);
  try {
    const r = await fetch(`https://huggingface.co/api/spaces/${sp}`);
    if (r.status === 404) return { stage: "NOT_FOUND", hardware: "", ok: false, text: "This Space does not exist (or is private). Check the name in AI settings." };
    if (!r.ok) return { stage: "UNKNOWN", hardware: "", ok: false, text: `Hugging Face answered ${r.status}.` };
    const j = await r.json();
    const stage: string = j.runtime?.stage ?? "UNKNOWN";
    const hardware: string = j.runtime?.hardware?.current ?? j.runtime?.hardware?.requested ?? "";
    const text = stage === "RUNNING" ? "Awake and ready." : stage === "SLEEPING" ? "Asleep. It wakes when you press Make; the first start can take a few minutes." : stage === "PAUSED" || stage === "STOPPED" ? "The owner paused this Space. Pick another one in AI settings." : stage === "RUNTIME_ERROR" || stage === "BUILD_ERROR" ? "This Space is broken right now. Try again later or pick another." : `Status: ${stage}.`;
    return { stage, hardware, ok: stage === "RUNNING" || stage === "SLEEPING" || stage === "BUILDING" || stage === "RUNNING_BUILDING" || stage === "APP_STARTING", text };
  } catch { return { stage: "OFFLINE", hardware: "", ok: false, text: "Cannot reach Hugging Face. Check your internet connection." }; }
}

function friendly(msg: string): string {
  const m = /(\d+:\d{2}:\d{2})/.exec(msg);
  if (/quota|exceeded your|zerogpu|gpu limit/i.test(msg)) return `Your free GPU time on Hugging Face is used up for now${m ? `. It comes back in about ${m[1]} (hours:minutes:seconds)` : " (it renews on its own, about 24 hours after you first used it)"}. A free Hugging Face token gives more time than none: add one in AI settings.`;
  if (/queue.*full|too many/i.test(msg)) return "The free GPU queue is full right now. Try again in a few minutes.";
  if (/sleeping|starting|building/i.test(msg)) return "The Space is starting up. Try again in a minute or two.";
  if (/timeout|timed out|time limit/i.test(msg)) return "The free GPU stopped the job because it took too long. Try a shorter video or a smaller size.";
  if (/nsfw|safety|blocked/i.test(msg)) return "The Space refused this request (its safety filter). Change the prompt or picture.";
  return msg.length > 260 ? msg.slice(0, 260) + "…" : msg;
}

async function connect(space: string, token: string, onStage: (s: Stage) => void): Promise<Client> {
  const sp = spaceKey(space);
  if (!/^[\w.-]+\/[\w.-]+$/.test(sp)) throw new HFError("The Space name must look like owner/name. Check AI settings.");
  onStage({ phase: "Connecting to the free GPU Space", fraction: 0.02 });
  try {
    return await Client.connect(sp, {
      ...(token ? { token: token as `hf_${string}` } : {}),
      record_history: false,
      status_callback: (s: any) => { if (s?.status === "sleeping" || s?.status === "starting" || s?.status === "building") onStage({ phase: "Waking up the free GPU Space (a few minutes the first time)", fraction: 0.03 }); },
    } as any);
  } catch (e) {
    const t = e instanceof Error ? e.message : String(e);
    throw new HFError(/paused|stopped/i.test(t) ? "This Space is paused by its owner. Pick another one in AI settings." : /not found|404/i.test(t) ? "This Space was not found. Check the name in AI settings." : `Could not connect to the Space. ${friendly(t)}`);
  }
}

async function needParams(client: Client, endpoint: string, names: string[]): Promise<void> {
  let info: any;
  try { info = await client.view_api(); } catch { return; } // cannot inspect: try anyway
  const ep = info?.named_endpoints?.[endpoint];
  if (!ep) throw new HFError(`This Space has no “${endpoint}” function (the owner changed it). Choose another Space in AI settings, or use the desktop version.`);
  const have = new Set((ep.parameters ?? []).map((p: any) => p.parameter_name));
  const missing = names.filter((n) => !have.has(n));
  if (missing.length) throw new HFError(`This Space changed its inputs (missing: ${missing.join(", ")}). Choose another Space in AI settings, or use the desktop version.`);
}

export const fileFor = (blob: Blob, name: string): File => new File([blob], name, { type: blob.type || "application/octet-stream" });

interface RunOpts { space: string; endpoint: string; params: string[]; payload: Record<string, unknown>; onStage: (s: Stage) => void; signal?: { cancelled: boolean; on?: (fn: () => void) => void } }

function pickFile(v: any): { url: string; name: string } | null {
  if (!v) return null;
  if (typeof v === "string") return /^https?:/.test(v) ? { url: v, name: "video.mp4" } : null;
  const f = v.video ?? v;
  const url = f.url ?? (f.path ? `${f.root ?? ""}/gradio_api/file=${f.path}` : "");
  return url ? { url, name: f.orig_name || f.name || "video.mp4" } : null;
}

/** Sends one job to a Space and waits for the file it returns. Reports queue position and progress. Counts free GPU seconds in the meter. */
export async function runSpace(o: RunOpts): Promise<{ blob: Blob; data: any[]; seconds: number }> {
  const cfg = loadHF();
  const client = await connect(o.space, cfg.token, o.onStage);
  await needParams(client, o.endpoint, o.params);
  o.onStage({ phase: "Waiting for a free GPU", fraction: 0.05 });
  const sub: any = (client as any).submit(o.endpoint, o.payload, undefined, undefined, true); // the 5th argument asks for status events (queue place, progress, errors) too, not only the final data
  o.signal?.on?.(() => { void sub.cancel?.(); });
  let started = 0, out: any[] | null = null;
  try {
    for await (const ev of sub as AsyncIterable<any>) {
      if (o.signal?.cancelled) break;
      if (ev.type === "status") {
        if (ev.stage === "error") throw new HFError(friendly(typeof ev.message === "string" && ev.message ? ev.message : ev.title || "The Space reported an error."));
        if (ev.stage === "pending") o.onStage({ phase: ev.position != null ? `In the free queue: place ${ev.position + 1}${ev.eta ? `, about ${Math.round(ev.eta)} s` : ""}` : "Waiting for a free GPU", fraction: 0.06 });
        if (ev.stage === "generating") {
          if (!started) started = Date.now();
          const pd = (ev.progress_data ?? []).find((p: any) => typeof p.progress === "number");
          const f = pd ? pd.progress : ev.eta ? Math.min(0.95, (Date.now() - started) / 1000 / (((Date.now() - started) / 1000) + ev.eta)) : 0.4;
          o.onStage({ phase: pd?.desc ? `Making it: ${pd.desc}` : "Making it on the free GPU", fraction: 0.1 + 0.8 * Math.max(0, Math.min(1, f)) });
        }
      } else if (ev.type === "data") out = ev.data;
    }
  } catch (e) {
    if (e instanceof HFError) throw e;
    const m = e instanceof Error ? e.message : typeof e === "object" && e ? JSON.stringify(e).slice(0, 300) : String(e);
    throw new HFError(friendly(m));
  }
  if (o.signal?.cancelled) throw new HFError("Cancelled.");
  if (!out) throw new HFError("The Space finished without sending a video. Try again.");
  const seconds = started ? Math.max(1, Math.round((Date.now() - started) / 1000)) : 0;
  if (seconds) recordUse("zerogpu", Date.now(), Math.min(seconds, 600));
  const first = (out as any[]).map(pickFile).find(Boolean);
  if (!first) throw new HFError("The Space did not return a video file.");
  o.onStage({ phase: "Downloading the video", fraction: 0.95 });
  let res = await fetch(first.url).catch(() => null);
  if ((!res || res.status === 401 || res.status === 403) && cfg.token) res = await fetch(first.url, { headers: { Authorization: `Bearer ${cfg.token}` } }).catch(() => null);
  if (!res || !res.ok) throw new HFError("The video was made but could not be downloaded from Hugging Face. Try again.");
  const blob = new Blob([await res.arrayBuffer()], { type: res.headers.get("content-type")?.startsWith("video/") ? res.headers.get("content-type")! : "video/mp4" });
  return { blob, data: out, seconds };
}

export { handle_file };
