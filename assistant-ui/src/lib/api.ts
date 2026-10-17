import { ApiError } from "./errors";
import { IS_WEB } from "./env";
import * as W from "../web/shim";
import type { AnalyticsResult, AtsResult, Card, CompareResult, Conversation, FileRef, Info, Message, SettingsData, ThemeInfo } from "./types";

function readToken(): string {
  try {
    const fromUrl = new URLSearchParams(location.search).get("t");
    if (fromUrl) {
      sessionStorage.setItem("aia_token", fromUrl);
      history.replaceState(null, "", location.pathname); // keep the token out of the address bar
      return fromUrl;
    }
    return sessionStorage.getItem("aia_token") ?? "";
  } catch {
    return new URLSearchParams(location.search).get("t") ?? "";
  }
}
export const token = readToken();

export { ApiError };

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
  if (IS_WEB) return W.webCall(method, path, body, form) as Promise<T>;
  let res: Response;
  try {
    res = await fetch("/api/assistant" + path, {
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

export const fileUrl = (id: string, inline = false) => IS_WEB ? W.fileUrl(id) : `/api/assistant/files/${id}/download?t=${encodeURIComponent(token)}${inline ? "&inline=true" : ""}`;

export type StreamEvent =
  | { event: "start"; data: { message_id: string; intent: string; title: string } }
  | { event: "status"; data: { text: string } }
  | { event: "progress"; data: { fraction: number; elapsed: number; text: string; estimated: boolean } }
  | { event: "delta"; data: { text: string } }
  | { event: "card"; data: Card }
  | { event: "done"; data: { message_id: string } }
  | { event: "error"; data: { message: string } };

/** Reads the server-sent events of one chat turn. */
export async function streamChat(body: { conversation_id: string; text: string; file_ids: string[]; options: Record<string, unknown> },
                                 onEvent: (e: StreamEvent) => void, signal: AbortSignal): Promise<void> {
  if (IS_WEB) return W.webStream(body, onEvent, signal);
  let res: Response;
  try {
    res = await fetch("/api/assistant/chat", { method: "POST", signal, headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify(body) });
  } catch (e) {
    if ((e as Error).name === "AbortError") return;
    throw new ApiError("Can't reach the app. It may have closed.", 0);
  }
  if (!res.ok || !res.body) {
    let d: unknown = null;
    try { d = await res.json(); } catch { /* ignore */ }
    throw new ApiError(messageFrom(d, res.status), res.status);
  }
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i: number;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const block = buf.slice(0, i);
        buf = buf.slice(i + 2);
        let ev = "message", data = "";
        for (const line of block.split("\n")) {
          if (line.startsWith("event:")) ev = line.slice(6).trim();
          else if (line.startsWith("data:")) data += line.slice(5).trim();
        }
        if (data) {
          try { onEvent({ event: ev, data: JSON.parse(data) } as StreamEvent); } catch { /* ignore a malformed block */ }
        }
      }
    }
  } catch (e) {
    if ((e as Error).name !== "AbortError") throw new ApiError("The connection was interrupted.", 0);
  }
}

export const api = {
  advice: () => call<import("../AdvisorDialog").Advice>("GET", "/ai/advice"),
  enhancePrompt: (prompt: string, kind: "image" | "video") => call<{ prompt: string; how: string }>("POST", "/prompt/enhance", { prompt, kind }),
  info: () => call<Info>("GET", "/info"),
  settings: () => call<SettingsData>("GET", "/settings"),
  saveSettings: (patch: unknown) => call<SettingsData>("PUT", "/settings", patch),
  testLlm: () => call<{ ok: boolean; reply: string }>("POST", "/settings/test", {}),
  models: () => call<{ models: string[] }>("GET", "/models"),
  conversations: () => call<Conversation[]>("GET", "/conversations"),
  newConversation: () => call<Conversation>("POST", "/conversations"),
  conversation: (id: string) => call<Conversation & { messages: Message[] }>("GET", `/conversations/${id}`),
  rename: (id: string, title: string) => call<{ ok: boolean }>("PATCH", `/conversations/${id}`, { title }),
  deleteConversation: (id: string) => call<{ ok: boolean }>("DELETE", `/conversations/${id}`),
  upload: (file: File) => { const f = new FormData(); f.append("file", file); return call<FileRef>("POST", "/files", undefined, f); },
  files: (origin?: string) => call<FileRef[]>("GET", "/files" + (origin ? `?origin=${origin}` : "")),
  deleteFile: (id: string) => call<{ ok: boolean }>("DELETE", `/files/${id}`),
  themes: (purpose = "", docType = "document") => call<{ themes: ThemeInfo[]; recommended: ThemeInfo[] }>("GET", `/themes?purpose=${encodeURIComponent(purpose)}&doc_type=${docType}&limit=8`),
  create: (b: { format: string; markdown: string; title?: string; theme?: string | null; purpose?: string }) =>
    call<{ file: FileRef; warnings: string[]; theme: { id: string; name: string; colors: Record<string, string>; reasons: string[] } }>("POST", "/tools/create", b),
  ats: (file_id: string, job_description: string) => call<AtsResult>("POST", "/tools/ats", { file_id, job_description }),
  compare: (file_a: string, file_b: string) => call<{ result: CompareResult; report: FileRef }>("POST", "/tools/compare", { file_a, file_b }),
  analyze: (file_id: string) => call<AnalyticsResult>("POST", "/tools/analyze", { file_id }),
  image: (prompt: string, shape: string) => call<{ file: FileRef; width: number; height: number; prompt: string; provider: string }>("POST", "/tools/image", { prompt, shape }),
};
