import { webMediaUrl } from "../web/media";
import { webFontUrl } from "../web/fonts";
import type { Estimate, Usage, UpdateInfo, Adjust, Asset, Catalog, ExportOptions, Job, Limits, ModelRow, Project, Settings, SystemInfo, ToolInfo } from "./types";

function readToken(): string {
  try {
    const fromUrl = new URLSearchParams(location.search).get("t");
    if (fromUrl) {
      sessionStorage.setItem("ltxps_token", fromUrl);
      history.replaceState(null, "", location.pathname); // keep the token out of the address bar
      return fromUrl;
    }
    return sessionStorage.getItem("ltxps_token") ?? "";
  } catch {
    return new URLSearchParams(location.search).get("t") ?? "";
  }
}
export const token = readToken();

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

function messageFrom(body: unknown, status: number): string {
  const d = (body as { detail?: unknown } | null)?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d) && d.length) {
    const first = d[0] as { loc?: unknown[]; msg?: string };
    const field = first.loc ? String(first.loc[first.loc.length - 1]) : "";
    return `${field ? field + ": " : ""}${first.msg ?? "Invalid value"}`;
  }
  if (status === 401) return "This window lost its connection to the app. Close it and open the app again.";
  return `Request failed (${status}).`;
}

export const IS_WEB = import.meta.env.VITE_WEB === "1";

async function call<T>(method: string, path: string, body?: unknown, form?: FormData): Promise<T> {
  if (IS_WEB) return (await import("../web/backend")).webCall(method, path, body, form) as Promise<T>;
  let res: Response;
  try {
    res = await fetch("/api" + path, {
      method,
      headers: { Authorization: `Bearer ${token}`, ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
      body: form ?? (body !== undefined ? JSON.stringify(body) : undefined),
    });
  } catch {
    throw new ApiError("Can't reach the app. It may have closed.", 0);
  }
  let data: unknown = null;
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok) throw new ApiError(messageFrom(data, res.status), res.status);
  return data as T;
}

export interface SoundInfo { id: string; label: string; group: string; duration: number }
export interface SoundList { groups: string[]; sounds: SoundInfo[] }
export const soundUrl = (id: string) => IS_WEB ? new URL(`data/sounds/${id}.mp3`, document.baseURI).href : `/api/editor/sounds/${id}/file?t=${encodeURIComponent(token)}`;
export const mediaUrl = (id: string, what: "file" | "thumb" | "download" = "file") => IS_WEB ? webMediaUrl(id, what) : `/api/assets/${id}/${what}?t=${encodeURIComponent(token)}`;

export type Persona = "auto" | "girl" | "boy" | "woman" | "man" | "old_woman" | "old_man";
export const PERSONAS: { id: Persona; label: string }[] = [
  { id: "auto", label: "Automatic (from the picture and words)" }, { id: "woman", label: "Woman (middle age)" }, { id: "man", label: "Man (middle age)" },
  { id: "old_woman", label: "Old woman" }, { id: "old_man", label: "Old man" }, { id: "girl", label: "Girl (child)" }, { id: "boy", label: "Boy (child)" },
];
export interface SoundOptions { narration: string; voice: string; rate: number; ambience: string; music: boolean; level: number; persona?: Persona }
export interface GenerateBody {
  mode: "t2v" | "i2v"; prompt: string; negative_prompt: string; width: number; height: number; frames: number;
  steps?: number; guidance?: number; seed: number; model_id?: string; image_asset_id?: string; end_image_asset_id?: string; unlock_limits: boolean; sound?: SoundOptions;
}

export const fontSampleUrl = (font: string, text: string, bold = false, height = 44) =>
  `/api/editor/fonts/sample?font=${encodeURIComponent(font)}&text=${encodeURIComponent(text)}&bold=${bold}&height=${height}&t=${encodeURIComponent(token)}`;
export const fontFileUrl = (font: string, bold = false) => IS_WEB ? webFontUrl(font, bold) : `/api/editor/fonts/${encodeURIComponent(font)}/file?bold=${bold}&t=${encodeURIComponent(token)}`;

export interface AIRequest { asset_id: string; trim_in?: number; trim_out?: number; options?: Record<string, unknown> }

export interface ChatMsg { role: "user" | "assistant"; content: string; image_ids?: string[] }
export interface ChatTask { name: string; clips?: string[]; language?: string; every?: number; text?: string; prompt?: string; use_reference?: boolean; mode?: "patch" | "track"; part?: "" | "head" | "face"; shapes?: unknown[]; drawing_ids?: string[]; narration?: string; ambience?: string; music?: boolean; persona?: Persona }
export interface InpaintRequest extends AIRequest { prompt: string; mode: "patch" | "track"; part: "" | "head" | "face"; shapes: unknown[] }
export interface ChatResult { reply: string; project: Project; applied: string[]; skipped: string[]; tasks: ChatTask[]; changed: boolean; focus?: number | null; understood?: boolean; new_assets?: string[] }
export interface ChatStatus { ready: boolean; provider?: string; name?: string; model?: string; why?: string }
export interface LLMPreset { name: string; style: string; base_url: string; needs_key: boolean; model: string; help: string }
export interface AssistantInfo { providers: Record<string, LLMPreset> }
export interface AssistantSettings { provider: string; providers: Record<string, { base_url?: string; model?: string; api_key_hint?: string }> }

export interface SetupItem { id: string; label: string; why: string; approx_bytes: number; size_known?: boolean; installed: boolean }
export interface SetupPlan { gpu: { name: string; vram_gb: number; present: boolean; usable: boolean; needs_gpu_build: boolean }; engine: { installed: boolean; version: string; kind: string }; items: SetupItem[]; missing_bytes: number; disk_free_gb: number; enough_disk: boolean; need_gb: number; summary: string }
export interface ModuleRow { name: string; label: string; installed: string | null; recommended: string | null; previous: string[] }

export interface MotionSettings { has_key: boolean; key_hint: string; mode: "std" | "pro"; source?: string }
export interface MotionRequest { image_asset_id: string; video_asset_id: string; orientation: "image" | "video"; mode: "std" | "pro"; prompt: string; keep_sound: boolean; narration?: string; persona?: Persona }

export interface BudgetStatus { limit_usd: number; window_hours: 6 | 12 | 24; spent_usd: number; left_usd: number; enabled: boolean; renews_in: string; windows: number[] }

export const api = {
  budget: () => call<BudgetStatus>("GET", "/budget"),
  setBudget: (b: { limit_usd?: number; window_hours?: 6 | 12 | 24 }) => call<BudgetStatus>("POST", "/budget", b),
  estimate: (q: { width: number; height: number; frames: number; model_id?: string; steps?: number; end_image?: boolean }) =>
    call<Estimate>("GET", `/estimate?width=${q.width}&height=${q.height}&frames=${q.frames}&model_id=${encodeURIComponent(q.model_id ?? "")}${q.steps ? `&steps=${q.steps}` : ""}&end_image=${q.end_image ? "true" : "false"}`),
  usage: (jobId = "") => call<Usage>("GET", `/usage?job_id=${encodeURIComponent(jobId)}`),
  motionSettings: () => call<MotionSettings>("GET", "/motion/settings"),
  saveMotionSettings: (b: { fal_key?: string; mode?: "std" | "pro" }) => call<MotionSettings>("POST", "/motion/settings", b),
  motionRun: (b: MotionRequest) => call<Job>("POST", "/motion/run", b),
  motionTest: () => call<{ ok: boolean; message: string }>("POST", "/motion/test"),
  motionLocal: (b: { image_asset_id: string; video_asset_id: string; engine?: "mediapipe" | "tensorflow"; keep_sound?: boolean; narration?: string; persona?: Persona }) => call<Job>("POST", "/motion/local", b),
  motionLocalStatus: () => call<{ mediapipe: boolean; tensorflow: boolean }>("GET", "/motion/local/status"),
  installTensorflow: () => call<Job>("POST", "/motion/local/install-tensorflow"),
  cloudVideo: (b: { prompt: string; start_asset_id?: string; end_asset_id?: string; duration: 6 | 8 | 10; resolution: string; aspect_ratio: "16:9" | "9:16"; audio: boolean; engine?: "ltx" | "omni"; narration?: string; persona?: Persona }) => call<Job>("POST", "/cloud-video", b),
  setupPlan: () => call<SetupPlan>("GET", "/setup/plan"),
  setupInstall: () => call<SetupPlan>("POST", "/setup/install"),
  moduleTable: () => call<{ online: boolean; modules: ModuleRow[] }>("GET", "/updates/modules"),
  moduleVersions: (name: string) => call<{ versions: string[] }>("GET", `/updates/modules/${encodeURIComponent(name)}/versions`),
  installModule: (name: string, version: string) => call<Job>("POST", "/updates/modules/install", { name, version }),

  chat: (messages: ChatMsg[], project: Project) => call<ChatResult>("POST", "/editor/chat", { messages, project }),
  advice: () => call<import("../editor/AdvisorDialog").Advice>("GET", "/ai/advice"),
  enhancePrompt: (prompt: string, kind: "image" | "video") => call<{ prompt: string; how: string }>("POST", "/prompt/enhance", { prompt, kind }),
  chatStatus: () => call<ChatStatus>("GET", "/editor/chat/status"),
  llmInfo: () => call<AssistantInfo>("GET", "/assistant/info"),
  llmSettings: () => call<AssistantSettings>("GET", "/assistant/settings"),
  saveLlm: (patch: unknown) => call<AssistantSettings>("PUT", "/assistant/settings", patch),
  llmModels: () => call<{ models: string[] }>("GET", "/assistant/models"),
  llmTest: () => call<{ ok?: boolean; reply?: string }>("POST", "/assistant/settings/test", {}),

  updates: () => call<UpdateInfo>("GET", "/updates"),
  updateModules: () => call<Job>("POST", "/updates/modules"),
  catalog: () => call<Catalog>("GET", "/editor/catalog"),
  sounds: () => call<SoundList>("GET", "/editor/sounds"),
  soundAdd: (id: string) => call<Asset>("POST", `/editor/sounds/${id}/add`),
  ai: (what: "follow" | "silence" | "scenes" | "beats" | "captions", b: AIRequest) => call<Job>("POST", `/editor/ai/${what}`, b),
  inpaint: (b: InpaintRequest) => call<Job>("POST", "/editor/ai/inpaint", b),
  enhance: (b: AIRequest) => call<Adjust>("POST", "/editor/ai/enhance", b),
  voices: () => call<{ voices: string[] }>("GET", "/editor/ai/voices"),
  ambiences: () => call<{ ambiences: { id: string; label: string }[] }>("GET", "/editor/ai/ambiences"),
  soundtrack: (b: Partial<SoundOptions> & { asset_id: string; prompt?: string }) => call<Job>("POST", "/editor/ai/soundtrack", b),
  speak: (text: string, voice: string, rate: number, persona?: Persona) => call<Job>("POST", "/editor/ai/speak", { text, voice, rate, persona: persona ?? "auto" }),
  system: (refresh = false) => call<SystemInfo>("GET", `/system${refresh ? "?refresh=true" : ""}`),
  settings: () => call<Settings>("GET", "/settings"),
  saveSettings: (p: Partial<Settings>) => call<Settings>("PUT", "/settings", p),
  limits: () => call<Limits>("GET", "/limits"),
  models: () => call<{ items: ModelRow[]; endpoint: string }>("GET", "/models"),
  probe: (id: string) => call<{ bytes: number }>("POST", `/models/${id}/probe`),
  download: (id: string) => call<ModelRow>("POST", `/models/${id}/download`),
  cancelDownload: (id: string) => call<{ ok: boolean }>("POST", `/models/${id}/cancel`),
  deleteModel: (id: string) => call<{ ok: boolean }>("DELETE", `/models/${id}`),
  generate: (b: GenerateBody) => call<Job>("POST", "/generate", b),
  extend: (b: GenerateBody & { source_asset_id: string }) => call<Job>("POST", "/generate/extend", b),
  jobs: () => call<Job[]>("GET", "/jobs"),
  cancelJob: (id: string) => call<{ ok: boolean }>("POST", `/jobs/${id}/cancel`),
  assets: () => call<Asset[]>("GET", "/assets"),
  upload: (file: File) => { const f = new FormData(); f.append("file", file); return call<Asset>("POST", "/assets/upload", undefined, f); },
  renameAsset: (id: string, name: string) => call<{ ok: boolean }>("PATCH", `/assets/${id}`, { name }),
  deleteAsset: (id: string) => call<{ ok: boolean }>("DELETE", `/assets/${id}`),
  tools: () => call<ToolInfo[]>("GET", "/editor/tools"),
  runTool: (tool: string, asset_id: string, params: Record<string, unknown> = {}) => call<Job>("POST", `/editor/tools/${tool}`, { asset_id, params }),
  exportProject: (project: Project, options: ExportOptions) => call<Job>("POST", "/editor/export", { project, options }),
  projects: () => call<{ id: string; name: string; updated?: number }[]>("GET", "/projects"),
  loadProject: (id: string) => call<Project>("GET", `/projects/${id}`),
  saveProject: (id: string, p: Project) => call<{ ok: boolean }>("PUT", `/projects/${id}`, p),
  deleteProject: (id: string) => call<{ ok: boolean }>("DELETE", `/projects/${id}`),
};
