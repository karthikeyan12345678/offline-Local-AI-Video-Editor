// Talks to a free (or your own) AI service straight from the browser. The key stays in this browser's storage only.
import { recordUse } from "./quota";

export interface Preset { name: string; style: "openai" | "anthropic"; base_url: string; needs_key: boolean; model: string; help: string; free?: boolean }

/** Free-first list. "Free" = a no-card free plan exists (third-party information; check the provider for current limits). */
export const PRESETS: Record<string, Preset> = {
  groq: { name: "Groq (free plan)", style: "openai", base_url: "https://api.groq.com/openai/v1", needs_key: true, model: "llama-3.3-70b-versatile", free: true,
    help: "Free plan, fast. Create a key at console.groq.com/keys (no card needed). About 1,000 requests a day, renewing." },
  gemini: { name: "Google Gemini (free plan)", style: "openai", base_url: "https://generativelanguage.googleapis.com/v1beta/openai", needs_key: true, model: "gemini-2.5-flash", free: true,
    help: "Free plan, can also read pictures. Create a key at aistudio.google.com/apikey (no card needed). Daily limit renews." },
  openrouter: { name: "OpenRouter (free models)", style: "openai", base_url: "https://openrouter.ai/api/v1", needs_key: true, model: "meta-llama/llama-3.3-70b-instruct:free", free: true,
    help: "Many free models. Create a key at openrouter.ai/keys. The free models have a small daily limit." },
  cerebras: { name: "Cerebras (free plan)", style: "openai", base_url: "https://api.cerebras.ai/v1", needs_key: true, model: "llama-3.3-70b", free: true,
    help: "Free plan, very fast. Create a key at cloud.cerebras.ai." },
  github: { name: "GitHub Models (free)", style: "openai", base_url: "https://models.github.ai/inference", needs_key: true, model: "openai/gpt-4o-mini", free: true,
    help: "Free with a GitHub account. Create a token at github.com/settings/tokens with the “models” permission." },
  pollinations: { name: "Free online AI (no key)", style: "openai", base_url: "https://text.pollinations.ai/openai", needs_key: false, model: "openai", free: true,
    help: "No key and no sign-up, but it can be slow or busy. What you type is sent to a public service." },
  ollama: { name: "Ollama (on your computer)", style: "openai", base_url: "http://127.0.0.1:11434/v1", needs_key: false, model: "llama3.2", free: true,
    help: "Free and private. Install Ollama, run “ollama pull llama3.2”, and start it with OLLAMA_ORIGINS=* so this page may talk to it." },
  custom: { name: "Other (OpenAI-compatible)", style: "openai", base_url: "", needs_key: false, model: "", help: "Any service that speaks the OpenAI chat API." },
  openai: { name: "OpenAI (paid)", style: "openai", base_url: "https://api.openai.com/v1", needs_key: true, model: "gpt-4o-mini", help: "Paid. platform.openai.com." },
  anthropic: { name: "Anthropic Claude (paid)", style: "anthropic", base_url: "https://api.anthropic.com", needs_key: true, model: "claude-sonnet-5-5", help: "Paid, pay per use. console.anthropic.com → API keys." },
};

const KEY = "vk_llm_v1";
export interface Saved { provider: string; providers: Record<string, { base_url?: string; model?: string; api_key?: string }> }

export function loadSaved(): Saved {
  try { const s = JSON.parse(localStorage.getItem(KEY) ?? "null"); if (s && typeof s === "object") return { provider: s.provider ?? "", providers: s.providers ?? {} }; } catch { /* ignore */ }
  return { provider: "", providers: {} };
}
export function savePatch(patch: { provider?: string; providers?: Record<string, { base_url?: string; model?: string; api_key?: string }> }): Saved {
  const s = loadSaved();
  if (patch.provider) s.provider = patch.provider;
  for (const [k, v] of Object.entries(patch.providers ?? {})) s.providers[k] = { ...s.providers[k], ...v };
  try { localStorage.setItem(KEY, JSON.stringify(s)); } catch { /* ignore */ }
  window.dispatchEvent(new Event("vk-llm"));
  return s;
}

export interface Config { provider: string; style: "openai" | "anthropic"; base_url: string; model: string; api_key: string }
export function currentConfig(): Config {
  const s = loadSaved();
  const provider = s.provider || "";
  const p = PRESETS[provider] ?? PRESETS.custom;
  const mine = s.providers[provider] ?? {};
  return { provider, style: p.style, base_url: (mine.base_url || p.base_url).replace(/\/+$/, ""), model: mine.model || p.model, api_key: mine.api_key ?? "" };
}

export class LLMError extends Error {}

export interface Msg { role: "user" | "assistant"; content: string; images?: { media_type: string; data: string }[] }

function explain(cfg: Config, status: number, body: string): LLMError {
  const name = PRESETS[cfg.provider]?.name ?? cfg.provider;
  let detail = "";
  try { const j = JSON.parse(body); const e = j.error ?? j; detail = typeof e === "string" ? e : e.message ?? ""; } catch { detail = body.slice(0, 200); }
  if (status === 401 || status === 403) return new LLMError(`${name} did not accept the key. Open the AI settings, check the key and try again.`);
  if (status === 404) return new LLMError(`${name} does not know the model “${cfg.model}”. Pick another model name in the AI settings.`);
  if (status === 429) return new LLMError(`${name} says the free limit is used up for now. It renews on its own (see the meter), or switch to another free AI.`);
  if (status === 402) return new LLMError(`${name} needs credit on the account.`);
  if (status >= 500) return new LLMError(`${name} had a server problem (${status}). Try again shortly. ${detail.slice(0, 160)}`.trim());
  return new LLMError(`${name} refused the request (${status}). ${detail.slice(0, 200)}`.trim());
}

function content(cfg: Config, m: Msg): unknown {
  if (!m.images?.length) return m.content;
  if (cfg.style === "anthropic") return [...m.images.map((i) => ({ type: "image", source: { type: "base64", media_type: i.media_type, data: i.data } })), { type: "text", text: m.content }];
  return [{ type: "text", text: m.content }, ...m.images.map((i) => ({ type: "image_url", image_url: { url: `data:${i.media_type};base64,${i.data}` } }))];
}

function headers(cfg: Config): Record<string, string> {
  if (cfg.style === "anthropic") {
    return { "content-type": "application/json", "anthropic-version": "2023-06-01", "anthropic-dangerous-direct-browser-access": "true", ...(cfg.api_key ? { "x-api-key": cfg.api_key } : {}) };
  }
  return { "content-type": "application/json", ...(cfg.api_key ? { authorization: `Bearer ${cfg.api_key}` } : {}) };
}

export interface Opts { max_tokens?: number; temperature?: number; signal?: AbortSignal }

function build(cfg: Config, messages: Msg[], system: string, jsonMode: boolean, o: Opts, stream: boolean): { url: string; body: Record<string, unknown> } {
  const msgs = messages.filter((m) => m.content);
  const max_tokens = o.max_tokens ?? 2048, temperature = o.temperature ?? 0.2;
  if (cfg.style === "anthropic") {
    const merged: { role: string; content: unknown }[] = [];
    for (const m of msgs) {
      const last = merged[merged.length - 1];
      if (last && last.role === m.role && typeof last.content === "string" && !m.images?.length) last.content += "\n\n" + m.content;
      else merged.push({ role: m.role, content: content(cfg, m) });
    }
    while (merged.length && merged[0].role !== "user") merged.shift();
    return { url: cfg.base_url + "/v1/messages", body: { model: cfg.model, max_tokens, temperature, messages: merged, ...(system ? { system } : {}), ...(stream ? { stream: true } : {}) } };
  }
  const body: Record<string, unknown> = { model: cfg.model, temperature, max_tokens, messages: [...(system ? [{ role: "system", content: system }] : []), ...msgs.map((m) => ({ role: m.role, content: content(cfg, m) }))], ...(stream ? { stream: true } : {}) };
  if (jsonMode) body.response_format = { type: "json_object" };
  return { url: cfg.base_url + "/chat/completions", body };
}

function check(cfg: Config): void {
  if (!cfg.provider) throw new LLMError("Choose an AI first (AI settings).");
  if (!cfg.base_url) throw new LLMError("No server address is set. Open the AI settings and choose a provider.");
  if (!cfg.model) throw new LLMError("No model is chosen. Open the AI settings and type a model name.");
}

function netError(cfg: Config): LLMError {
  const local = /^http:\/\/(127\.|localhost)/.test(cfg.base_url);
  return new LLMError(local ? "Can't reach the program on your computer. Start it, and allow this website (Ollama: OLLAMA_ORIGINS=*)." : `Can't reach ${PRESETS[cfg.provider]?.name ?? cfg.provider}. Check your internet connection (or the service may not allow browser use).`);
}

/** Streams the answer piece by piece (server-sent events). Returns the whole text. */
export async function streamComplete(cfg: Config, messages: Msg[], system: string, onDelta: (t: string) => void, o: Opts = {}): Promise<string> {
  check(cfg);
  const { url, body } = build(cfg, messages, system, false, o, true);
  let res: Response;
  try { res = await fetch(url, { method: "POST", headers: headers(cfg), body: JSON.stringify(body), signal: o.signal }); }
  catch (e) { if ((e as Error).name === "AbortError") return ""; throw netError(cfg); }
  recordUse(cfg.provider);
  if (!res.ok) throw explain(cfg, res.status, await res.text());
  if (!res.body) { const t = await res.text(); onDelta(t); return t; }
  const reader = res.body.getReader(), dec = new TextDecoder();
  let buf = "", all = "";
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i: number;
      while ((i = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, i).trim(); buf = buf.slice(i + 1);
        if (!line.startsWith("data:")) continue;
        const d = line.slice(5).trim();
        if (!d || d === "[DONE]") continue;
        try {
          const j = JSON.parse(d);
          const piece: string = cfg.style === "anthropic" ? (j.type === "content_block_delta" ? j.delta?.text ?? "" : "") : j.choices?.[0]?.delta?.content ?? "";
          if (piece) { all += piece; onDelta(piece); }
        } catch { /* a partial line */ }
      }
    }
  } catch (e) { if ((e as Error).name !== "AbortError") throw new LLMError("The connection to the AI was interrupted. Try again."); }
  if (!all && !o.signal?.aborted) throw new LLMError("The AI returned an empty answer. Try again or choose another model.");
  return all;
}

export async function complete(cfg: Config, messages: Msg[], system: string, jsonMode = false, o: Opts = {}): Promise<string> {
  check(cfg);
  const { url, body } = build(cfg, messages, system, jsonMode, o, false);
  let res: Response;
  try {
    res = await fetch(url, { method: "POST", headers: headers(cfg), body: JSON.stringify(body), signal: o.signal });
  } catch {
    const local = /^http:\/\/(127\.|localhost)/.test(cfg.base_url);
    throw new LLMError(local ? "Can't reach the program on your computer. Start it, and allow this website (Ollama: OLLAMA_ORIGINS=*)." : `Can't reach ${PRESETS[cfg.provider]?.name ?? cfg.provider}. Check your internet connection (or the service may not allow browser use).`);
  }
  recordUse(cfg.provider);
  const raw = await res.text();
  if (!res.ok) throw explain(cfg, res.status, raw);
  let data: any; // eslint-disable-line @typescript-eslint/no-explicit-any
  try { data = JSON.parse(raw); } catch { throw new LLMError("The AI sent something unreadable. Try again."); }
  const text: string = cfg.style === "anthropic"
    ? (data.content ?? []).map((b: { text?: string }) => b.text ?? "").join("")
    : data.choices?.[0]?.message?.content ?? "";
  if (!text) throw new LLMError("The AI returned an empty answer. Try again or choose another model.");
  return text;
}

export async function listModels(cfg: Config): Promise<string[]> {
  if (cfg.style !== "openai" || !cfg.base_url) return [];
  try {
    const r = await fetch(cfg.base_url + "/models", { headers: headers(cfg) });
    if (!r.ok) return [];
    const j = await r.json();
    return (j.data ?? j.models ?? []).map((m: { id?: string; name?: string }) => m.id ?? m.name ?? "").filter(Boolean);
  } catch { return []; }
}

/** A picture shrunk to at most 1024 px and sent as JPEG, for models that can see. */
export async function encodeImage(blob: Blob, max = 1024): Promise<{ media_type: string; data: string }> {
  const bmp = await createImageBitmap(blob);
  const sc = Math.min(1, max / Math.max(bmp.width, bmp.height));
  const c = document.createElement("canvas"); c.width = Math.round(bmp.width * sc); c.height = Math.round(bmp.height * sc);
  c.getContext("2d")?.drawImage(bmp, 0, 0, c.width, c.height);
  const url = c.toDataURL("image/jpeg", 0.85);
  return { media_type: "image/jpeg", data: url.slice(url.indexOf(",") + 1) };
}
