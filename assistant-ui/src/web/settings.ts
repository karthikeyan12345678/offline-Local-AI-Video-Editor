// Settings of the web Assistant. The chat AI and its key are shared with the editor's chat (same browser storage); the rest is kept here.
import { PRESETS, loadSaved, savePatch } from "../../../shared/web/llm";
import type { SettingsData } from "../lib/types";

const KEY = "vk_ast_v1";
export interface ImgSaved { provider: string; chosen?: boolean; [id: string]: unknown }
interface Own { default_theme: string; system_prompt: string; image: ImgSaved }
const DEF: Own = { default_theme: "claude", system_prompt: "", image: { provider: "horde" } };

export function own(): Own {
  try { const s = JSON.parse(localStorage.getItem(KEY) ?? "null"); if (s && typeof s === "object") return { ...DEF, ...s, image: { ...DEF.image, ...(s.image ?? {}) } }; } catch { /* ignore */ }
  return { ...DEF, image: { ...DEF.image } };
}
function put(o: Own): void { try { localStorage.setItem(KEY, JSON.stringify(o)); } catch { /* ignore */ } }

const mask = (k?: string) => (!k ? "" : k.length > 8 ? "•".repeat(8) + k.slice(-4) : "•".repeat(k.length));

export function publicSettings(): SettingsData {
  const sv = loadSaved(), o = own();
  const providers: SettingsData["providers"] = {};
  for (const [id, v] of Object.entries(sv.providers)) providers[id] = { base_url: v.base_url, model: v.model, api_key_hint: mask(v.api_key) };
  const image: Record<string, unknown> & { provider: string } = { provider: o.image.provider };
  for (const [id, v] of Object.entries(o.image)) if (v && typeof v === "object") { const { api_key, ...rest } = v as Record<string, string>; image[id] = { ...rest, api_key_hint: mask(api_key) }; }
  return { provider: sv.provider || "pollinations", default_theme: o.default_theme, system_prompt: o.system_prompt, providers, image };
}

type Patch = { provider?: string; default_theme?: string; system_prompt?: string; providers?: Record<string, { base_url?: string; model?: string; api_key?: string }>; image?: Record<string, unknown> };
export function updateSettings(p: Patch): void {
  const o = own();
  if (typeof p.default_theme === "string") o.default_theme = p.default_theme;
  if (typeof p.system_prompt === "string") o.system_prompt = p.system_prompt;
  if (p.provider || p.providers) {
    const providers: Record<string, { base_url?: string; model?: string; api_key?: string }> = {};
    for (const [id, v] of Object.entries(p.providers ?? {})) {
      const cur: { base_url?: string; model?: string; api_key?: string } = {};
      if (typeof v.base_url === "string") cur.base_url = v.base_url.trim();
      if (typeof v.model === "string") cur.model = v.model.trim();
      if (typeof v.api_key === "string" && v.api_key && !v.api_key.startsWith("•")) cur.api_key = v.api_key.trim();
      providers[id] = cur;
    }
    savePatch({ ...(p.provider ? { provider: p.provider } : {}), providers });
  }
  if (p.image) {
    if (typeof p.image.provider === "string") { o.image.provider = p.image.provider; o.image.chosen = true; }
    for (const [id, v] of Object.entries(p.image)) {
      if (!v || typeof v !== "object") continue;
      const cur = (o.image[id] as Record<string, string> | undefined) ?? {};
      const n = v as Record<string, string>;
      if (typeof n.base_url === "string") cur.base_url = n.base_url.trim();
      if (typeof n.model === "string") cur.model = n.model.trim();
      if (typeof n.api_key === "string" && n.api_key && !n.api_key.startsWith("•")) cur.api_key = n.api_key.trim();
      o.image[id] = cur;
    }
  }
  put(o);
}

export const chatProviders = () => PRESETS;
