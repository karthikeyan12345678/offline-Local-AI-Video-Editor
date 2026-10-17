// Conversations, messages and files of the AI Assistant, kept in this browser (IndexedDB, one database per signed-in account).
import { idb } from "../../../shared/web/idb";
import type { Card, Conversation, FileRef, Message } from "../lib/types";

interface Index { convs: Conversation[]; files: FileRef[] }
interface StoredMsg { id: string; role: "user" | "assistant"; content: string; cards: Card[]; files: string[]; created: number }

const IDX = "ast:index";
const rid = () => Array.from(crypto.getRandomValues(new Uint8Array(6)), (b) => b.toString(16).padStart(2, "0")).join("");
const now = () => Date.now() / 1000;

let cache: Index | null = null;
async function index(): Promise<Index> {
  if (!cache) cache = (await idb.get<Index>("meta", IDX)) ?? { convs: [], files: [] };
  return cache;
}
async function save(): Promise<void> { if (cache) await idb.put("meta", IDX, cache); }

export async function listConversations(): Promise<Conversation[]> {
  return [...(await index()).convs].sort((a, b) => b.updated - a.updated).slice(0, 200);
}
export async function createConversation(title = "New chat"): Promise<Conversation> {
  const ix = await index();
  const c: Conversation = { id: rid(), title, created: now(), updated: now() };
  ix.convs.push(c); await save();
  return c;
}
export async function getConversation(id: string): Promise<Conversation | null> { return (await index()).convs.find((c) => c.id === id) ?? null; }
export async function renameConversation(id: string, title: string): Promise<boolean> {
  const c = await getConversation(id); if (!c) return false;
  c.title = title.trim().slice(0, 120) || "Chat"; await save(); return true;
}
export async function deleteConversation(id: string): Promise<boolean> {
  const ix = await index(); const had = ix.convs.some((c) => c.id === id);
  ix.convs = ix.convs.filter((c) => c.id !== id); await save(); await idb.del("meta", "ast:msgs:" + id);
  return had;
}

async function stored(cid: string): Promise<StoredMsg[]> { return (await idb.get<StoredMsg[]>("meta", "ast:msgs:" + cid)) ?? []; }
export async function addMessage(cid: string, role: "user" | "assistant", content: string, cards: Card[] = [], files: string[] = []): Promise<StoredMsg> {
  const m: StoredMsg = { id: rid(), role, content, cards, files, created: now() };
  const list = await stored(cid); list.push(m);
  await idb.put("meta", "ast:msgs:" + cid, list);
  const c = await getConversation(cid); if (c) { c.updated = now(); await save(); }
  return m;
}
export async function rawMessages(cid: string): Promise<StoredMsg[]> { return stored(cid); }
export async function messages(cid: string): Promise<Message[]> {
  const ix = await index();
  return (await stored(cid)).map((m) => ({ ...m, files: m.files.map((i) => ix.files.find((f) => f.id === i)).filter((f): f is FileRef => !!f).map(({ id, name, kind, size }) => ({ id, name, kind, size })) }));
}

export async function addFile(origin: string, name: string, blob: Blob, kind: string): Promise<FileRef> {
  const ix = await index();
  const f: FileRef = { id: rid(), origin, name, kind, size: blob.size, created: now() };
  await idb.put("blobs", "ast:" + f.id, blob);
  ix.files.push(f); await save();
  return f;
}
export async function getFile(id: string): Promise<{ meta: FileRef; blob: Blob } | null> {
  const meta = (await index()).files.find((f) => f.id === id); if (!meta) return null;
  const blob = await idb.get<Blob>("blobs", "ast:" + id); if (!blob) return null;
  return { meta, blob };
}
export async function listFiles(origin?: string): Promise<FileRef[]> {
  return (await index()).files.filter((f) => !origin || f.origin === origin).sort((a, b) => (b.created ?? 0) - (a.created ?? 0)).slice(0, 300);
}
export async function deleteFile(id: string): Promise<boolean> {
  const ix = await index(); const had = ix.files.some((f) => f.id === id);
  ix.files = ix.files.filter((f) => f.id !== id); await save(); await idb.del("blobs", "ast:" + id);
  return had;
}
