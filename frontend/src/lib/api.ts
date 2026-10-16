import type { UpdateInfo, Adjust, Asset, Catalog, ExportOptions, Job, Limits, ModelRow, Project, Settings, SystemInfo, ToolInfo } from "./types";

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

async function call<T>(method: string, path: string, body?: unknown, form?: FormData): Promise<T> {
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

export const mediaUrl = (id: string, what: "file" | "thumb" | "download" = "file") => `/api/assets/${id}/${what}?t=${encodeURIComponent(token)}`;

export interface GenerateBody {
  mode: "t2v" | "i2v"; prompt: string; negative_prompt: string; width: number; height: number; frames: number;
  steps?: number; guidance?: number; seed: number; model_id?: string; image_asset_id?: string; unlock_limits: boolean;
}

export const fontSampleUrl = (font: string, text: string, bold = false, height = 44) =>
  `/api/editor/fonts/sample?font=${encodeURIComponent(font)}&text=${encodeURIComponent(text)}&bold=${bold}&height=${height}&t=${encodeURIComponent(token)}`;
export const fontFileUrl = (font: string, bold = false) => `/api/editor/fonts/${encodeURIComponent(font)}/file?bold=${bold}&t=${encodeURIComponent(token)}`;

export interface AIRequest { asset_id: string; trim_in?: number; trim_out?: number; options?: Record<string, unknown> }

export interface ChatMsg { role: "user" | "assistant"; content: string; image_ids?: string[] }
export interface ChatTask { name: string; clips?: string[]; language?: string; every?: number; text?: string; prompt?: string; use_reference?: boolean }
export interface ChatResult { reply: string; project: Project; applied: string[]; skipped: string[]; tasks: ChatTask[]; changed: boolean; focus?: number | null; understood?: boolean }
export interface ChatStatus { ready: boolean; provider?: string; name?: string; model?: string; why?: string }
export interface LLMPreset { name: string; style: string; base_url: string; needs_key: boolean; model: string; help: string }
export interface AssistantInfo { providers: Record<string, LLMPreset> }
export interface AssistantSettings { provider: string; providers: Record<string, { base_url?: string; model?: string; api_key_hint?: string }> }

export interface SetupItem { id: string; label: string; why: string; approx_bytes: number; size_known?: boolean; installed: boolean }
export interface SetupPlan { gpu: { name: string; vram_gb: number; present: boolean; usable: boolean; needs_gpu_build: boolean }; engine: { installed: boolean; version: string; kind: string }; items: SetupItem[]; missing_bytes: number; disk_free_gb: number; enough_disk: boolean; need_gb: number; summary: string }
export interface ModuleRow { name: string; label: string; installed: string | null; recommended: string | null; previous: string[] }

export const api = {
  setupPlan: () => call<SetupPlan>("GET", "/setup/plan"),
  setupInstall: () => call<SetupPlan>("POST", "/setup/install"),
  moduleTable: () => call<{ online: boolean; modules: ModuleRow[] }>("GET", "/updates/modules"),
  moduleVersions: (name: string) => call<{ versions: string[] }>("GET", `/updates/modules/${encodeURIComponent(name)}/versions`),
  installModule: (name: string, version: string) => call<Job>("POST", "/updates/modules/install", { name, version }),

  chat: (messages: ChatMsg[], project: Project) => call<ChatResult>("POST", "/editor/chat", { messages, project }),
  chatStatus: () => call<ChatStatus>("GET", "/editor/chat/status"),
  llmInfo: () => call<AssistantInfo>("GET", "/assistant/info"),
  llmSettings: () => call<AssistantSettings>("GET", "/assistant/settings"),
  saveLlm: (patch: unknown) => call<AssistantSettings>("PUT", "/assistant/settings", patch),
  llmModels: () => call<{ models: string[] }>("GET", "/assistant/models"),
  llmTest: () => call<{ ok?: boolean; reply?: string }>("POST", "/assistant/settings/test", {}),

  updates: () => call<UpdateInfo>("GET", "/updates"),
  updateModules: () => call<Job>("POST", "/updates/modules"),
  catalog: () => call<Catalog>("GET", "/editor/catalog"),
  ai: (what: "follow" | "silence" | "scenes" | "beats" | "captions", b: AIRequest) => call<Job>("POST", `/editor/ai/${what}`, b),
  enhance: (b: AIRequest) => call<Adjust>("POST", "/editor/ai/enhance", b),
  voices: () => call<{ voices: string[] }>("GET", "/editor/ai/voices"),
  speak: (text: string, voice: string, rate: number) => call<Job>("POST", "/editor/ai/speak", { text, voice, rate }),
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
