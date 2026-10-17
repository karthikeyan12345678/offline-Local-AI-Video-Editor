// Picture engines, from the browser. The same engines and fall-back order as the desktop Assistant (the one that needs a graphics card on your PC is left out).
/* eslint-disable @typescript-eslint/no-explicit-any */
import { own } from "./settings";

export const IMAGE_PROVIDERS: Record<string, { name: string; needs_key: boolean; base_url: string; model: string; help: string }> = {
  horde: { name: "AI Horde (free, online, no logo)", needs_key: false, base_url: "https://aihorde.net/api/v2", model: "", help: "Free community service. No account, no watermark. Pictures can take from 20 seconds to a few minutes when it is busy." },
  pollinations: { name: "Pollinations (free, online, may add a small logo)", needs_key: false, base_url: "https://image.pollinations.ai", model: "flux", help: "Quick, but the free tier may stamp a logo and limit how many pictures you can make." },
  huggingface: { name: "FLUX on Hugging Face (free token, sharp detail)", needs_key: true, base_url: "https://router.huggingface.co/hf-inference/models", model: "black-forest-labs/FLUX.1-schnell",
    help: "Free monthly credits. Make a token at huggingface.co/settings/tokens (allow “Inference”). FLUX makes far more detailed pictures than the quick engines." },
  together: { name: "FLUX on Together AI (free model, sharp detail)", needs_key: true, base_url: "https://api.together.xyz/v1", model: "black-forest-labs/FLUX.1-schnell-Free", help: "Free FLUX model with a free key from api.together.ai. Very detailed pictures." },
  openai: { name: "OpenAI: DALL·E 3 / GPT Image (paid)", needs_key: true, base_url: "https://api.openai.com/v1", model: "gpt-image-1", help: "Paid per picture. Set the model to gpt-image-1 (best detail) or dall-e-3." },
};
const SIZES: Record<string, [number, number]> = { square: [1024, 1024], landscape: [1280, 720], portrait: [768, 1152] };
const NEGATIVE = "blurry, out of focus, low resolution, lowres, jpeg artifacts, deformed, bad anatomy, extra fingers, extra limbs, disfigured, watermark, text, logo, oversaturated";

export class ImageError extends Error {}
interface Cfg { provider: string; base_url: string; api_key: string; model: string }
export interface MadeImage { blob: Blob; width: number; height: number; provider: string; watermark: boolean; fallback_reason: string }

function config(): Cfg {
  const o = own().image; let prov = String(o.provider || "horde");
  if (prov === "pollinations" && !o.chosen) prov = "horde";
  if (!IMAGE_PROVIDERS[prov]) prov = "horde";
  return cfgFor(prov);
}
function cfgFor(prov: string): Cfg {
  const p = IMAGE_PROVIDERS[prov], mine = (own().image[prov] as Record<string, string> | undefined) ?? {};
  return { provider: prov, base_url: (mine.base_url || p.base_url).replace(/\/+$/, ""), api_key: mine.api_key ?? "", model: mine.model || p.model };
}
export const activeProvider = () => config().provider;

const sleep = (ms: number, s?: AbortSignal) => new Promise<void>((res, rej) => { const t = setTimeout(res, ms); s?.addEventListener("abort", () => { clearTimeout(t); rej(new DOMException("aborted", "AbortError")); }, { once: true }); });
const aborted = (e: unknown) => (e as Error)?.name === "AbortError";

async function net(url: string, init: RequestInit, what: string): Promise<Response> {
  try { return await fetch(url, init); } catch (e) { if (aborted(e)) throw e; throw new ImageError(`Cannot reach ${what}. Check your internet connection (or the service may not allow browser use).`); }
}

async function openaiImages(c: Cfg, prompt: string, size: [number, number], sig?: AbortSignal): Promise<Blob> {
  const ratio = size[0] / size[1];
  const wanted = ratio > 1.2 ? "1536x1024" : ratio < 0.85 ? "1024x1536" : "1024x1024";
  const body: Record<string, any> = { model: c.model, prompt, n: 1, size: wanted };
  if (c.model === "dall-e-3") { body.size = ({ "1536x1024": "1792x1024", "1024x1536": "1024x1792" } as any)[wanted] ?? wanted; body.quality = "hd"; body.response_format = "b64_json"; }
  else if (c.model.startsWith("dall-e")) body.response_format = "b64_json";
  else if (c.model.startsWith("gpt-image")) body.quality = "high";
  if (c.base_url.includes("together")) { delete body.size; Object.assign(body, { width: Math.min(1024, size[0]), height: Math.min(1024, size[1]), steps: 4, response_format: "b64_json" }); if (!c.model.toLowerCase().includes("flux")) body.negative_prompt = NEGATIVE; }
  const r = await net(c.base_url + "/images/generations", { method: "POST", signal: sig, headers: { "content-type": "application/json", ...(c.api_key ? { authorization: `Bearer ${c.api_key}` } : {}) }, body: JSON.stringify(body) }, c.base_url);
  if (r.status === 401 || r.status === 403) throw new ImageError("The image service did not accept the API key. Check it in Settings.");
  if (r.status === 429) throw new ImageError("The image service says you have hit its limit. Wait and retry.");
  if (!r.ok) { let m = ""; try { m = (await r.json()).error?.message ?? ""; } catch { /* ignore */ } throw new ImageError(`The image service refused the request (${r.status}). ${m}`.trim()); }
  let item: any; try { item = (await r.json()).data[0]; } catch { throw new ImageError("The image service sent an answer this app does not understand."); }
  if (item.b64_json) return new Blob([Uint8Array.from(atob(item.b64_json), (ch) => ch.charCodeAt(0))]);
  if (item.url) { try { return await (await fetch(item.url, { signal: sig })).blob(); } catch { throw new ImageError("The picture was made but could not be downloaded."); } }
  throw new ImageError("The image service returned no picture.");
}

async function huggingface(c: Cfg, prompt: string, size: [number, number], sig?: AbortSignal): Promise<Blob> {
  if (!c.api_key) throw new ImageError("Add your free Hugging Face token in Settings (huggingface.co/settings/tokens).");
  const model = c.model || "black-forest-labs/FLUX.1-schnell";
  const params: Record<string, any> = { width: Math.min(1024, Math.floor(size[0] / 16) * 16), height: Math.min(1024, Math.floor(size[1] / 16) * 16), num_inference_steps: model.includes("schnell") ? 4 : 30 };
  if (!model.toLowerCase().includes("flux")) params.negative_prompt = NEGATIVE;
  const r = await net(`${(c.base_url || IMAGE_PROVIDERS.huggingface.base_url).replace(/\/+$/, "")}/${model}`, { method: "POST", signal: sig, headers: { authorization: `Bearer ${c.api_key}`, accept: "image/png", "content-type": "application/json" }, body: JSON.stringify({ inputs: prompt, parameters: params }) }, "Hugging Face");
  if (r.status === 401 || r.status === 403) throw new ImageError("Hugging Face did not accept the token. Make one with the “Inference” permission and paste it in Settings.");
  if (r.status === 402 || r.status === 429) throw new ImageError("The free Hugging Face credits for this month are used up, or you are going too fast. Wait, or switch engine.");
  if (r.status === 503) throw new ImageError("The Hugging Face model is waking up. Try again in a minute.");
  if (!r.ok) throw new ImageError(`Hugging Face refused the request (${r.status}). ${(await r.text()).slice(0, 160)}`.trim());
  return r.blob();
}

async function pollinations(c: Cfg, prompt: string, size: [number, number], sig?: AbortSignal): Promise<Blob> {
  const q = new URLSearchParams({ width: String(size[0]), height: String(size[1]), nologo: "true", model: c.model || "flux", enhance: "true", negative: NEGATIVE });
  const url = `${c.base_url || IMAGE_PROVIDERS.pollinations.base_url}/prompt/${encodeURIComponent(prompt)}?${q}`;
  let last = "";
  for (let i = 0; i < 3; i++) {
    const r = await net(url, { signal: sig }, "the free image service");
    if (r.status === 429 || r.status >= 500) { last = `The free service is busy (${r.status}).`; await sleep(3000 + i * 5000, sig); continue; }
    if (!r.ok) throw new ImageError(`The free image service refused the request (${r.status}).`);
    return r.blob();
  }
  throw new ImageError(last + " Try again in a minute, or switch to another image engine in Settings.");
}

async function horde(c: Cfg, prompt: string, size: [number, number], onStatus: (t: string) => void, sig?: AbortSignal): Promise<Blob> {
  const base = (c.base_url || IMAGE_PROVIDERS.horde.base_url).replace(/\/+$/, "");
  const head = { apikey: c.api_key || "0000000000", "Client-Agent": "VKEditor:1:vkeditor-web", "content-type": "application/json" };
  const dim = (n: number) => Math.max(256, Math.min(768, Math.floor((n > 768 ? n / 2 : n) / 64) * 64));
  const body: Record<string, any> = { prompt: prompt + " ### blurry, watermark, text, logo, deformed, low quality", nsfw: false, censor_nsfw: true, r2: false, shared: false,
    params: { width: dim(size[0]), height: dim(size[1]), steps: 32, n: 1, sampler_name: "k_euler_a", cfg_scale: 7.5, post_processing: ["GFPGAN"] } };
  if (c.model) body.models = [c.model];
  const r = await net(base + "/generate/async", { method: "POST", signal: sig, headers: head, body: JSON.stringify(body) }, "the free image service (AI Horde)");
  if (r.status === 429) throw new ImageError("The free image service says too many requests are waiting from your network. Wait a minute and retry.");
  if (!r.ok) { let m = ""; try { m = String((await r.json()).message ?? ""); } catch { /* ignore */ } throw new ImageError(`The free image service refused the request (${r.status}). ${m}`.trim()); }
  let job: string; try { job = (await r.json()).id; } catch { throw new ImageError("The free image service sent an answer this app does not understand."); }
  const started = Date.now();
  try {
    for (;;) {
      if (Date.now() - started > 420_000) throw new ImageError("The free image service is very busy right now. Try again in a few minutes, or pick another engine in Settings.");
      await sleep(3000, sig);
      const ck = await net(`${base}/generate/check/${job}`, { headers: head, signal: sig }, "the free image service");
      if (!ck.ok) continue;
      const info = await ck.json();
      if (info.faulted) throw new ImageError("The free image service could not make that picture. Reword it and try again.");
      onStatus(`Waiting in the free queue… position ${info.queue_position ?? "?"}, about ${info.wait_time ?? "?"} s`);
      if (info.done) break;
    }
    const st = await (await net(`${base}/generate/status/${job}`, { headers: head, signal: sig }, "the free image service")).json();
    const g = (st.generations ?? [])[0];
    if (!g) throw new ImageError("The free image service finished without a picture. Try again.");
    if (g.censored) throw new ImageError("The free image service blocked that prompt. Reword it.");
    const img: string = g.img ?? "";
    if (img.startsWith("http")) return await (await fetch(img, { signal: sig })).blob();
    return new Blob([Uint8Array.from(atob(img), (ch) => ch.charCodeAt(0))]);
  } finally { void fetch(`${base}/generate/status/${job}`, { method: "DELETE", headers: head }).catch(() => undefined); }
}

/** Decodes whatever came back and re-saves it as PNG (also proves it really is a picture). */
async function toPng(raw: Blob): Promise<{ blob: Blob; width: number; height: number }> {
  let bmp: ImageBitmap;
  try { bmp = await createImageBitmap(raw); } catch { throw new ImageError("The service did not return a picture. It may be busy or may have refused the prompt. Try again or reword it."); }
  const c = document.createElement("canvas"); c.width = bmp.width; c.height = bmp.height;
  c.getContext("2d")!.drawImage(bmp, 0, 0);
  const blob = await new Promise<Blob | null>((res) => c.toBlob(res, "image/png"));
  if (!blob) throw new ImageError("The picture could not be saved. Try a smaller size.");
  return { blob, width: bmp.width, height: bmp.height };
}

export async function generateImage(prompt: string, shape: string, onStatus: (t: string) => void, sig?: AbortSignal): Promise<MadeImage> {
  prompt = prompt.trim();
  if (prompt.length < 3) throw new ImageError("Describe the picture you want, for example “a lighthouse at sunset, watercolor”.");
  if (prompt.length > 1500) throw new ImageError("That description is too long. Keep it under about 1,500 characters.");
  const size = SIZES[shape] ?? SIZES.square, cfg = config();
  const order = [cfg.provider];
  if (cfg.provider === "horde" || cfg.provider === "pollinations") order.push(...["horde", "pollinations"].filter((p) => p !== cfg.provider));
  if (cfg.provider === "huggingface" || cfg.provider === "together") order.push("horde", "pollinations");
  let used = "", raw: Blob | null = null; const errors: string[] = [];
  for (const prov of [...new Set(order)]) {
    try {
      const c = prov === cfg.provider ? cfg : cfgFor(prov);
      raw = prov === "huggingface" ? await huggingface(c, prompt, size, sig)
        : prov === "openai" || prov === "together" ? (c.base_url ? await openaiImages(c, prompt, size, sig) : (() => { throw new ImageError("No image server address is set. Open Settings."); })())
        : prov === "horde" ? await horde(c, prompt, size, onStatus, sig)
        : await pollinations(c, prompt, size, sig);
      used = prov; break;
    } catch (e) {
      if (aborted(e)) throw e;
      if (!(e instanceof ImageError)) throw e;
      errors.push(e.message);
      if (prov === cfg.provider && cfg.provider === "openai") break; // chosen on purpose: say why it failed
    }
  }
  if (!used || !raw) throw new ImageError(errors.length === 1 ? errors[0] : errors[0] + " (The backup engine also failed: " + errors[errors.length - 1] + ")");
  const png = await toPng(raw);
  return { ...png, provider: used, watermark: used === "pollinations", fallback_reason: errors.length && used !== cfg.provider ? errors[0] : "" };
}
