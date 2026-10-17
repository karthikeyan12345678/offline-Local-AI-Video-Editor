// The AI Assistant without a server. Same requests as the desktop app's API, answered in the browser:
//  - data lives in IndexedDB (store.ts)
//  - chat and pictures go straight from the browser to the AI service the person chose (llm.ts, images.ts)
//  - documents, resume check, compare and analyse run the real Python code in Pyodide (py.ts + bridge.py)
/* eslint-disable @typescript-eslint/no-explicit-any */
import { PRESETS, complete, currentConfig, listModels, streamComplete, LLMError, type Msg } from "../../../shared/web/llm";
import { addHistory } from "../../../shared/web/history";
import { ApiError } from "../lib/errors";
import type { Card, FileRef } from "../lib/types";
import type { StreamEvent } from "../lib/api";
import * as S from "./store";
import { ToolError, dropInputs, getPy, onEngineProgress, pcall, putFile, takeFile } from "./py";
import { IMAGE_PROVIDERS, ImageError, activeProvider, generateImage } from "./images";
import { own, publicSettings, updateSettings } from "./settings";

const IMAGE_EXT = [".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"];
const DOC_EXT = [".csv", ".docx", ".htm", ".html", ".json", ".log", ".md", ".pdf", ".pptx", ".tsv", ".txt", ".xlsx"];
const FORMATS = ["pdf", "docx", "pptx", "csv", "xlsx"];
const MIME: Record<string, string> = { pdf: "application/pdf", docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document", pptx: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", csv: "text/csv", md: "text/markdown", png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg", webp: "image/webp", gif: "image/gif", bmp: "image/bmp", txt: "text/plain" };
const SYSTEM_BASE = "You are a careful, practical assistant inside a web app. Answer directly and accurately. If you are unsure, say so. Keep replies as short as the request allows.";
const MAX_UPLOAD = 150 * 1024 * 1024;

// ---------------------------------------------------------------- file links (blob: URLs, made before the data is handed to the screen)
const urls = new Map<string, string>();
export const fileUrl = (id: string): string => urls.get(id) ?? "";
async function link(ids: Iterable<string>): Promise<void> {
  for (const id of ids) {
    if (urls.has(id)) continue;
    const f = await S.getFile(id);
    if (f) urls.set(id, URL.createObjectURL(f.blob));
  }
}
const idsIn = (cards: Card[]): string[] => cards.flatMap((c) => [(c as any).file?.id, (c as any).report?.id].filter(Boolean));
const typed = (bytes: Uint8Array | Blob | string, kind: string): Blob => new Blob([bytes as BlobPart], { type: MIME[kind] ?? "application/octet-stream" });
const safeName = (n: string) => (n.replace(/\\/g, "/").split("/").pop() ?? "file").replace(/[^\w .()+-]+/g, "_").replace(/^[ .]+|[ .]+$/g, "").slice(0, 120) || "file";

import { detectIntent } from "./intent";

const deriveTitle = (text: string): string => {
  const t = text.trim().replace(/^\/\w+\s*/, "").replace(/\s+/g, " ");
  return t.length > 48 ? t.slice(0, 48) + "…" : t || "New chat";
};

// ---------------------------------------------------------------- chat model helpers
const cfgReady = (): boolean => { const c = currentConfig(); return !!(c.provider && c.base_url && c.model && (!PRESETS[c.provider]?.needs_key || c.api_key)); };

async function constants(): Promise<{ doc_prompts: Record<string, string>; tailor_prompt: string }> { return pcall("constants"); }

const stripFence = (t: string): string => { const m = /^```(?:markdown|md)?\s*\n([\s\S]*?)\n```\s*$/.exec(t.trim()); return m ? m[1].trim() : t.trim(); };

/** Asks the chat AI to improve a short idea; the built-in recipe is used when no AI is ready (same as the desktop). */
async function enhance(prompt: string, kind: "image" | "video", signal?: AbortSignal): Promise<{ prompt: string; how: string }> {
  let ai = "";
  if (cfgReady() && prompt.trim().length >= 3 && prompt.trim().length <= 600) {
    try {
      const sys = await pcall<{ image: string; video: string }>("enhance_systems");
      ai = (await complete(currentConfig(), [{ role: "user", content: prompt }], kind === "image" ? sys.image : sys.video, false, { max_tokens: 300, temperature: 0.8, signal })).trim();
    } catch (e) { if ((e as Error).name === "AbortError") throw e; ai = ""; }
  }
  const r = await pcall<{ prompt: string; how: string }>("enhance_prompt", prompt, kind, ai);
  return { prompt: r.prompt, how: r.how };
}

// ---------------------------------------------------------------- the chat turn
type Emit = (e: StreamEvent) => void;
const fileCard = (f: FileRef, note: string, warnings: string[], theme: any): Card => ({ type: "file", file: f, note, warnings: warnings ?? [], theme: theme ?? null });

async function loadFiles(ids: string[]): Promise<{ meta: FileRef; blob: Blob; path: string }[]> {
  const out = [];
  for (const id of ids) { const f = await S.getFile(id); if (f) out.push({ ...f, path: "" }); }
  return out;
}
async function stage(files: { meta: FileRef; blob: Blob; path: string }[]): Promise<void> { for (const f of files) f.path = await putFile(f.meta.id, f.meta.name, f.blob); }

async function saveOut(origin: string, name: string, path: string, kind: string): Promise<FileRef> {
  const f = await S.addFile(origin, name, typed(await takeFile(path), kind), kind);
  await link([f.id]);
  return f;
}

function estimate(elapsed: number, provider: string): number {
  const tau = ({ horde: 45, pollinations: 18 } as Record<string, number>)[provider] ?? 20;
  return 0.92 * (1 - Math.exp(-elapsed / tau));
}

const need = (files: unknown[], n: number, what: string) => { if (files.length < n) throw new Error(`Attach ${n} file${n > 1 ? "s" : ""} first (use the paperclip) to ${what}.`); };

export async function webStream(body: { conversation_id: string; text: string; file_ids: string[]; options: Record<string, any> }, onEvent: Emit, signal: AbortSignal): Promise<void> {
  const cid = body.conversation_id, options = body.options ?? {};
  const conv = await S.getConversation(cid);
  if (!conv) { onEvent({ event: "error", data: { message: "That chat no longer exists. Start a new one." } }); return; }
  const text = (body.text ?? "").trim();
  if (!text && !body.file_ids.length) { onEvent({ event: "error", data: { message: "Type a message or attach a file first." } }); return; }
  if (conv.title === "New chat" && text) await S.renameConversation(cid, deriveTitle(text));
  const files = await loadFiles(body.file_ids);
  let intent = detectIntent(text, files.length);
  if (!text && files.length) intent = { kind: "chat", text: "Summarise this file." };
  const earlier = await S.rawMessages(cid);
  const userMsg = await S.addMessage(cid, "user", text, [], files.map((f) => f.meta.id));
  onEvent({ event: "start", data: { message_id: userMsg.id, intent: intent.kind, title: (await S.getConversation(cid))?.title ?? "" } });
  onEngineProgress((t) => onEvent({ event: "status", data: { text: t } }));

  let reply = "", cards: Card[] = [];
  const delta = (t: string) => onEvent({ event: "delta", data: { text: t } });
  const status = (t: string) => onEvent({ event: "status", data: { text: t } });
  try {
    if (FORMATS.includes(intent.kind)) ({ reply, cards } = await doDocument(intent, text, files, options, delta, status, signal));
    else if (intent.kind === "ats") { ({ reply, cards } = await doAts(intent, files, options)); delta(reply); }
    else if (intent.kind === "tailor") ({ reply, cards } = await doTailor(intent, files, options, delta, status, signal));
    else if (intent.kind === "compare") { ({ reply, cards } = await doCompare(files)); delta(reply); }
    else if (intent.kind === "analyze") { ({ reply, cards } = await doAnalyze(files)); delta(reply); }
    else if (intent.kind === "image") { ({ reply, cards } = await doImage(intent.text || text, options, onEvent, signal)); delta(reply); }
    else if (intent.kind === "design") { ({ reply, cards } = await doDesign(intent.text || text, options)); delta(reply); }
    else reply = await doChat(earlier, intent.text || text, files, delta, signal);
  } catch (exc) {
    if ((exc as Error).name === "AbortError") { onEngineProgress(null); await dropInputs().catch(() => undefined); return; }
    const known = exc instanceof LLMError || exc instanceof ImageError || exc instanceof ToolError || exc instanceof Error;
    const msg = known && (exc instanceof LLMError || exc instanceof ImageError || exc instanceof ToolError || (exc as Error).message.startsWith("Attach ") || (exc as Error).message.startsWith("Say what") || (exc as Error).message.startsWith("I need"))
      ? (exc as Error).message : `Something went wrong while doing that (${(exc as Error).name}: ${String((exc as Error).message).slice(0, 160)}).`;
    await S.addMessage(cid, "assistant", "⚠ " + msg, [{ type: "error", message: msg }]);
    onEvent({ event: "error", data: { message: msg } });
    return;
  } finally { onEngineProgress(null); await dropInputs().catch(() => undefined); }
  await link(idsIn(cards));
  for (const c of cards) onEvent({ event: "card", data: c });
  const saved = await S.addMessage(cid, "assistant", reply, cards);
  onEvent({ event: "done", data: { message_id: saved.id } });
}

async function doChat(earlier: { role: string; content: string }[], text: string, files: { meta: FileRef; blob: Blob; path: string }[], delta: (t: string) => void, signal: AbortSignal): Promise<string> {
  let prompt = text;
  if (files.length) {
    await stage(files);
    const r = await pcall<{ text: string; errors: string[] }>("context", JSON.stringify(files.map((f) => ({ id: f.meta.id, name: f.meta.name, path: f.path }))), 14000);
    for (const e of r.errors) delta(`_${e}_\n\n`);
    if (r.text) prompt = `${r.text}\n\n---\n${text}`;
  }
  const msgs: Msg[] = earlier.filter((m) => (m.role === "user" || m.role === "assistant") && m.content).map((m) => ({ role: m.role as "user" | "assistant", content: m.content }));
  msgs.push({ role: "user", content: prompt });
  let total = 0; const keep: Msg[] = [];
  for (const m of [...msgs].reverse()) { total += m.content.length; if (total > 24000 && keep.length) break; keep.push(m); }
  keep.reverse();
  const extra = own().system_prompt.trim();
  return streamComplete(currentConfig(), keep, SYSTEM_BASE + (extra ? "\n" + extra : ""), delta, { max_tokens: 4096, temperature: 0.6, signal });
}

async function doDocument(intent: { kind: string; text: string }, text: string, files: { meta: FileRef; blob: Blob; path: string }[], options: Record<string, any>,
  delta: (t: string) => void, status: (t: string) => void, signal: AbortSignal): Promise<{ reply: string; cards: Card[] }> {
  const fmt = intent.kind, request = intent.text || text;
  await stage(files);
  const refFiles = files.filter((f) => /\.(pdf|docx|pptx|md|txt)$/i.test(f.meta.name));
  let prof: { name: string; [k: string]: any } | null = null, refTheme: string | null = null;
  if (refFiles.length && ["pdf", "docx", "pptx"].includes(fmt)) {
    try { const r = await pcall<{ profile: any; theme: string | null }>("ref_profile", refFiles[0].path); prof = r.profile; refTheme = r.theme; }
    catch (e) { if (e instanceof ToolError) delta(`_${e.message} I will use the standard professional style instead._\n\n`); else throw e; }
  }
  let ctx = "";
  if (files.length) ctx = (await pcall<{ text: string }>("context", JSON.stringify(files.map((f) => ({ id: f.meta.id, name: f.meta.name, path: f.path }))), 10000)).text;
  const looks = (await pcall<{ value: boolean }>("looks_md", request)).value;
  let md: string;
  if (looks) { md = request; delta("Using the content you pasted.\n\n"); }
  else {
    if (!request) throw new Error(`Say what the ${fmt.toUpperCase()} should contain, for example “/${fmt} a one-page project status report”.`);
    status("Writing the content…");
    let prompt = `${(await constants()).doc_prompts[fmt]}\nOutput only the Markdown, with no commentary.\n\nRequest: ${request}`;
    if (prof) {
      status(`Studying “${prof.name}” for its structure and style…`);
      prompt += "\n\n" + (await pcall<{ text: string }>("ref_instructions", JSON.stringify(prof), fmt)).text;
      ctx = "";
    }
    if (ctx) prompt += `\n\nUse this material:\n${ctx}`;
    md = stripFence(await complete(currentConfig(), [{ role: "user", content: prompt }], SYSTEM_BASE, false, { max_tokens: 4096, temperature: 0.6, signal }));
    if (!md.trim()) throw new LLMError("The model returned no content. Try again or choose another model.");
  }
  status("Building the file…");
  const theme = options.theme || (prof ? refTheme : null) || "";
  const made = await pcall<{ file: { path: string; name: string }; warnings: string[]; theme: any }>("make_doc", fmt, md, request, theme, own().default_theme, "");
  const f = await saveOut("generated", made.file.name, made.file.path, fmt);
  let reply = `Your ${fmt.toUpperCase()} is ready: **${f.name}**.` + (prof ? ` It follows the structure${theme === "reference" ? " and colours" : ""} of ${prof.name}.` : "");
  if (made.warnings.length) reply += " Note: " + made.warnings.join(" ");
  void addHistory("assistant", `Made ${fmt.toUpperCase()}: ${f.name}`, request.slice(0, 120));
  return { reply, cards: [fileCard(f, "Draft the AI wrote; check facts before sharing.", made.warnings, made.theme), { type: "markdown", text: md }] };
}

async function doAts(intent: { text: string }, files: { meta: FileRef; blob: Blob; path: string }[], options: Record<string, any>): Promise<{ reply: string; cards: Card[] }> {
  need(files, 1, "check a resume");
  await stage(files);
  let jd: string = options.job_description || intent.text.replace(/\b(check|score|ats|my|resume|against|for|this)\b/gi, " ").trim();
  jd = jd.split(/\s+/).filter(Boolean).length >= 12 ? jd : "";
  const r = (await pcall<{ result: any }>("ats_file", files[0].path, jd)).result;
  void addHistory("assistant", `Resume check: ${files[0].meta.name}`, `${Math.round(r.score)}/100`);
  return { reply: `ATS estimate for **${files[0].meta.name}**: **${Math.round(r.score)}/100 (${r.level})**.` + (r.has_job_description ? "" : " Paste a job description to see which of its keywords are missing."), cards: [{ type: "ats", result: r }] };
}

async function doTailor(intent: { text: string }, files: { meta: FileRef; blob: Blob; path: string }[], options: Record<string, any>,
  delta: (t: string) => void, status: (t: string) => void, signal: AbortSignal): Promise<{ reply: string; cards: Card[] }> {
  need(files, 1, "tailor a resume");
  await stage(files);
  const low = intent.text.toLowerCase();
  const fmt = /\b(word|docx?)\b/.test(low) && !/\bpdf\b/.test(low) ? "docx" : "pdf";
  const ti = await pcall<{ resume: { id: string; name: string; path: string }; resume_text: string; jd: string }>("tailor_inputs", JSON.stringify(files.map((f) => ({ id: f.meta.id, name: f.meta.name, path: f.path }))), intent.text, options.job_description || "");
  let before: any = null;
  try { before = (await pcall<{ result: any }>("ats_resume", ti.resume.path, ti.jd)).result; } catch { /* e.g. a table file */ }
  const k = (await constants()).tailor_prompt;
  const cfg = currentConfig();
  status("Reading the job description and your resume…");
  const kw = (await pcall<{ keywords: { keyword: string }[] }>("ats_keywords", ti.jd)).keywords.slice(0, 30).map((w) => w.keyword).join(", ");
  status("Rewriting your resume for this job…");
  let md = stripFence(await complete(cfg, [{ role: "user", content: `${k}\n\nKEY TERMS IN THE JOB (use the ones the resume supports): ${kw}\n\nJOB DESCRIPTION:\n${ti.jd.slice(0, 7000)}\n\nRESUME:\n${ti.resume_text.slice(0, 9000)}` }], SYSTEM_BASE, false, { max_tokens: 4096, temperature: 0.4, signal }));
  if (!md.trim()) throw new LLMError("The model returned no content. Try again or choose another model.");
  let best: { f: FileRef; after: any; meta: any } | null = null;
  for (let attempt = 0; attempt < 2; attempt++) {
    status(attempt === 0 ? "Building the file and checking its ATS score…" : "Improving the keyword match…");
    const made = await pcall<{ file: { path: string; name: string }; warnings: string[]; theme: any }>("make_doc", fmt, md, "resume cv", options.theme || "", own().default_theme, "");
    const py = await getPy();
    const copy = "/work/in/tailored-" + attempt + "." + fmt;
    py.FS.writeFile(copy, py.FS.readFile(made.file.path));
    const after = (await pcall<{ result: any }>("ats_resume", copy, ti.jd)).result;
    const f = await saveOut("generated", made.file.name, made.file.path, fmt);
    if (!best || after.score > best.after.score) { if (best) await S.deleteFile(best.f.id); best = { f, after, meta: made }; } else await S.deleteFile(f.id); // keep only the better file
    const miss = (after.categories.keywords?.missing ?? []).map((m: { keyword: string }) => m.keyword).slice(0, 12);
    if (after.score >= 90 || attempt === 1 || !miss.length) break;
    const md2 = stripFence(await complete(cfg, [{ role: "user", content: `${k}\n\nHere is a draft. Improve it: these job terms are still missing, add each one ONLY where the original resume really supports it (as a skill or inside a bullet): ${miss.join(", ")}. Do not add anything the original resume does not support.\n\nDRAFT:\n${md}\n\nORIGINAL RESUME:\n${ti.resume_text.slice(0, 9000)}` }], SYSTEM_BASE, false, { max_tokens: 4096, temperature: 0.4, signal }));
    if (md2.trim()) md = md2;
  }
  const { f, after, meta } = best!;
  after.before_score = before ? before.score : null;
  const left = (after.categories.keywords?.missing ?? []).map((m: { keyword: string }) => m.keyword).slice(0, 10);
  let reply = `Your tailored resume is ready: **${f.name}**. ATS estimate: ` + (before ? `**${Math.round(before.score)} → ${Math.round(after.score)}/100**.` : `**${Math.round(after.score)}/100**.`);
  if (left.length) reply += " Job terms left out because your resume does not show them: " + left.join(", ") + ". Add them only if they are true for you.";
  delta(reply);
  void addHistory("assistant", `Tailored resume: ${f.name}`, `${Math.round(after.score)}/100`);
  return { reply, cards: [fileCard(f, "Rewritten from your resume and the job description. Check every line is true before you send it.", meta.warnings, meta.theme), { type: "ats", result: after }] };
}

async function doCompare(files: { meta: FileRef; blob: Blob; path: string }[]): Promise<{ reply: string; cards: Card[] }> {
  need(files, 2, "compare them");
  await stage(files);
  const r = await pcall<{ result: any; markdown: string; headline: string }>("compare_pair", files[0].path, files[1].path);
  const rep = await S.addFile("generated", `comparison-${files[0].meta.id}-${files[1].meta.id}.md`, typed(r.markdown, "md"), "md");
  void addHistory("assistant", `Compared ${files[0].meta.name} and ${files[1].meta.name}`);
  return { reply: r.headline, cards: [{ type: "compare", result: r.result, report: rep }] };
}

async function doAnalyze(files: { meta: FileRef; blob: Blob; path: string }[]): Promise<{ reply: string; cards: Card[] }> {
  need(files, 1, "analyse it");
  await stage(files);
  const r = (await pcall<{ result: any }>("analyze", files[0].path)).result;
  void addHistory("assistant", `Analysed ${files[0].meta.name}`);
  return { reply: r.headline, cards: [{ type: "analytics", result: r }] };
}

async function doDesign(text: string, options: Record<string, any>): Promise<{ reply: string; cards: Card[] }> {
  const picks = (await pcall<{ themes: any[] }>("design", text, options.doc_type || "document")).themes;
  const top = picks[0];
  return { reply: `Best match: **${top.name}** (${top.reasons.slice(0, 2).join("; ")}).`, cards: [{ type: "themes", themes: picks, request: text }] };
}

const slug = (p: string) => p.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40) || "image";

async function makePicture(prompt: string, shape: string, emit: Emit | null, signal: AbortSignal): Promise<{ file: FileRef; width: number; height: number; provider: string; watermark: boolean; fallback_reason: string }> {
  let note = "Starting the picture engine…";
  const t0 = Date.now();
  const provider = activeProvider();
  const timer = emit ? setInterval(() => { const el = (Date.now() - t0) / 1000; emit({ event: "progress", data: { fraction: Math.round(estimate(el, provider) * 1000) / 1000, elapsed: Math.round(el * 10) / 10, text: note, estimated: true } }); }, 400) : 0;
  try {
    const img = await generateImage(prompt, shape, (t) => { note = t; }, signal);
    const name = `${new Date().toISOString().replace(/[-:T]/g, "").slice(0, 14)}-${slug(prompt)}.png`;
    const file = await S.addFile("generated", name, img.blob, "png");
    await link([file.id]);
    emit?.({ event: "progress", data: { fraction: 1, elapsed: Math.round((Date.now() - t0) / 100) / 10, text: "Done", estimated: false } });
    return { file, width: img.width, height: img.height, provider: img.provider, watermark: img.watermark, fallback_reason: img.fallback_reason };
  } finally { if (timer) clearInterval(timer); }
}

async function doImage(promptIn: string, options: Record<string, any>, emit: Emit, signal: AbortSignal): Promise<{ reply: string; cards: Card[] }> {
  let prompt = promptIn, how = "none";
  if (options.enhance !== false) {
    emit({ event: "progress", data: { fraction: 0.02, elapsed: 0, text: "Writing a detailed description of your idea…", estimated: true } });
    ({ prompt, how } = await enhance(promptIn, "image", signal));
  }
  const out = await makePicture(prompt, options.shape || "square", emit, signal);
  let msg = how === "ai" || how === "recipe" ? (prompt !== promptIn ? ` I expanded your idea for more detail: “${prompt}”` : "") : "";
  if (out.watermark) msg += " The free fallback service may add a small logo; pick another engine in Settings for logo-free pictures.";
  if (out.fallback_reason) msg = ` Made by a backup free engine because the first one failed: ${out.fallback_reason}` + msg;
  void addHistory("assistant", `Made an image`, promptIn.slice(0, 120));
  return { reply: `Here is your image (${out.width}×${out.height}).${msg}`, cards: [{ type: "image", file: out.file, prompt, width: out.width, height: out.height, provider: out.provider }] };
}

// ---------------------------------------------------------------- the request router (same paths as the desktop API)
const fail = (msg: string, status = 400): never => { throw new ApiError(msg, status); };

function wrap<T>(fn: () => Promise<T>): Promise<T> {
  return fn().catch((e) => {
    if (e instanceof ApiError) throw e;
    if (e instanceof LLMError || e instanceof ImageError || e instanceof ToolError) throw new ApiError(e.message, 400);
    throw new ApiError(`Something went wrong (${(e as Error).message ?? e}).`, 500);
  });
}

async function advice(): Promise<any> {
  const row = (id: string, why: string, url?: string, how?: string) => ({ id, name: PRESETS[id].name, model: PRESETS[id].model, why, ...(url ? { url } : {}), ...(how ? { how } : {}) });
  const cur = currentConfig();
  const free = [row("groq", "Fastest free option. No card needed; about 1,000 requests a day, renewing.", "console.groq.com/keys"), row("gemini", "Free plan; can also read pictures.", "aistudio.google.com/apikey"),
    row("openrouter", "Many free models; small daily limit.", "openrouter.ai/keys"), row("pollinations", "No key and no sign-up, but slower and sometimes busy.")];
  return { pc: "Your web browser (the AI runs on the service you choose, not on your computer)", local: row("ollama", "Private and unlimited if you run it yourself.", undefined, "Install Ollama, run: ollama pull llama3.2, and start it with OLLAMA_ORIGINS=*"),
    free_online: free, paid: [row("anthropic", "Strongest answers; pay per use.", "console.anthropic.com")], best: free[0],
    picture: "Pictures: AI Horde is free and has no logo. FLUX on Hugging Face (free token) is sharper.", tip: "Press the choice, paste the key in Settings, then “Save and test”.",
    current: { ready: cfgReady(), name: PRESETS[cur.provider]?.name ?? "none", model: cur.model } };
}

export function webCall(method: string, path: string, body?: unknown, form?: FormData): Promise<any> {
  return wrap(async () => {
    const [p, qs] = path.split("?"); const q = new URLSearchParams(qs ?? "");
    const b = (body ?? {}) as any;
    let m: RegExpExecArray | null;
    if (method === "GET" && p === "/info") {
      const i = await pcall<{ formats: string[]; supported: string[]; themes: number }>("info");
      return { version: "web", formats: i.formats, providers: PRESETS, image_providers: IMAGE_PROVIDERS, local_image: { available: false, reason: "The on-this-PC picture model needs the desktop app." }, supported_uploads: [...DOC_EXT, ...IMAGE_EXT].sort(), themes: i.themes };
    }
    if (method === "GET" && p === "/ai/advice") return advice();
    if (method === "POST" && p === "/prompt/enhance") { const r = await enhance(String(b.prompt ?? ""), b.kind === "video" ? "video" : "image"); return { prompt: r.prompt, how: r.how }; }
    if (method === "GET" && p === "/settings") return publicSettings();
    if (method === "PUT" && p === "/settings") { updateSettings(b); return publicSettings(); }
    if (method === "POST" && p === "/settings/test") { const r = await complete(currentConfig(), [{ role: "user", content: "Reply with the single word: ready" }], "", false, { max_tokens: 16, temperature: 0 }); return { ok: true, reply: r.slice(0, 80) }; }
    if (method === "GET" && p === "/models") return { models: await listModels(currentConfig()) };
    if (p === "/conversations") {
      if (method === "GET") return S.listConversations();
      if (method === "POST") return S.createConversation();
    }
    if ((m = /^\/conversations\/([\w-]+)$/.exec(p))) {
      const id = m[1];
      if (method === "GET") {
        const c = await S.getConversation(id); if (!c) return fail("Chat not found", 404);
        const msgs = await S.messages(id);
        await link(msgs.flatMap((x) => [...idsIn(x.cards), ...x.files.map((f) => f.id)]));
        return { ...c, messages: msgs };
      }
      if (method === "PATCH") { if (!(await S.renameConversation(id, String(b.title ?? "")))) return fail("Chat not found", 404); return { ok: true }; }
      if (method === "DELETE") { if (!(await S.deleteConversation(id))) return fail("Chat not found", 404); return { ok: true }; }
    }
    if (p === "/files" && method === "POST") {
      const file = form?.get("file") as File | null; if (!file) return fail("No file was sent.");
      const name = safeName(file.name), ext = (/\.[^.]+$/.exec(name)?.[0] ?? "").toLowerCase();
      if (![...DOC_EXT, ...IMAGE_EXT].includes(ext)) return fail(`“${ext || name}” files are not supported. Use PDF, Word, PowerPoint, Excel, CSV, text or an image.`, 415);
      if (file.size === 0) return fail("That file is empty.");
      if (file.size > MAX_UPLOAD) return fail("That file is larger than 150 MB.", 413);
      const f = await S.addFile("upload", name, typed(file, ext.slice(1)), ext.slice(1));
      await link([f.id]);
      return f;
    }
    if (p === "/files" && method === "GET") { const l = await S.listFiles(q.get("origin") || undefined); await link(l.map((f) => f.id)); return l; }
    if ((m = /^\/files\/([\w-]+)$/.exec(p)) && method === "DELETE") { const u = urls.get(m[1]); if (u) { URL.revokeObjectURL(u); urls.delete(m[1]); } if (!(await S.deleteFile(m[1]))) return fail("File not found", 404); return { ok: true }; }
    if (method === "GET" && p === "/themes") return pcall("themes", q.get("purpose") ?? "", q.get("doc_type") ?? "document", Number(q.get("limit") ?? 8)).then((r: any) => ({ themes: r.themes, recommended: r.recommended }));
    if (p === "/tools/create" && method === "POST") {
      const fmt = String(b.format ?? "").toLowerCase();
      if (!FORMATS.includes(fmt)) return fail(`Choose one of: ${FORMATS.join(", ")}`);
      if (!String(b.markdown ?? "").trim()) return fail("Write the content first.");
      onEngineProgress(null);
      const made = await pcall<{ file: { path: string; name: string }; warnings: string[]; theme: any; pages?: number }>("make_doc", fmt, b.markdown, b.purpose || b.title || "", b.theme || "", own().default_theme, b.title || "");
      const f = await saveOut("generated", made.file.name, made.file.path, fmt);
      void addHistory("assistant", `Made ${fmt.toUpperCase()}: ${f.name}`);
      return { file: f, warnings: made.warnings, theme: made.theme };
    }
    if (p === "/tools/ats" && method === "POST") {
      const f = await S.getFile(String(b.file_id)); if (!f) return fail("That file is no longer available. Attach it again.", 404);
      const path = await putFile(f.meta.id, f.meta.name, f.blob);
      try { const r = (await pcall<{ result: any }>("ats_file", path, String(b.job_description ?? ""))).result; void addHistory("assistant", `Resume check: ${f.meta.name}`, `${Math.round(r.score)}/100`); return r; } finally { await dropInputs(); }
    }
    if (p === "/tools/compare" && method === "POST") {
      const [a, c] = [await S.getFile(String(b.file_a)), await S.getFile(String(b.file_b))];
      if (!a || !c) return fail("That file is no longer available. Attach it again.", 404);
      const pa = await putFile(a.meta.id, a.meta.name, a.blob), pb = await putFile(c.meta.id, c.meta.name, c.blob);
      try {
        const r = await pcall<{ result: any; markdown: string }>("compare_pair", pa, pb);
        const rep = await S.addFile("generated", `comparison-${a.meta.id}-${c.meta.id}.md`, typed(r.markdown, "md"), "md"); await link([rep.id]);
        void addHistory("assistant", `Compared ${a.meta.name} and ${c.meta.name}`);
        return { result: r.result, report: rep };
      } finally { await dropInputs(); }
    }
    if (p === "/tools/analyze" && method === "POST") {
      const f = await S.getFile(String(b.file_id)); if (!f) return fail("That file is no longer available. Attach it again.", 404);
      const path = await putFile(f.meta.id, f.meta.name, f.blob);
      try { const r = (await pcall<{ result: any }>("analyze", path)).result; void addHistory("assistant", `Analysed ${f.meta.name}`); return r; } finally { await dropInputs(); }
    }
    if (p === "/tools/image" && method === "POST") {
      const out = await makePicture(String(b.prompt ?? ""), b.shape || "square", null, new AbortController().signal);
      void addHistory("assistant", "Made an image", String(b.prompt ?? "").slice(0, 120));
      return { file: out.file, width: out.width, height: out.height, prompt: String(b.prompt ?? ""), provider: out.provider };
    }
    return fail(`Unknown request ${method} ${p}`, 404);
  });
}
