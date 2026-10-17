// A running list of what happened in this account: projects made, videos exported or generated, files the assistant created.
// Kept in this person's own browser database and, when they allowed it, copied to their private Google Drive app folder.
import { idb } from "./idb";

export type HistoryType = "sign_in" | "project_new" | "project_edit" | "export" | "video" | "motion" | "assistant" | "import";
export interface HistoryItem { id: string; ts: number; type: HistoryType; title: string; detail?: string; ref?: string }

const uid = () => (crypto.randomUUID?.() ?? String(Date.now()) + Math.random().toString(16).slice(2)).replace(/-/g, "").slice(0, 12);

export async function addHistory(type: HistoryType, title: string, detail?: string, ref?: string): Promise<void> {
  try {
    const item: HistoryItem = { id: uid(), ts: Date.now() / 1000, type, title: title.slice(0, 160), ...(detail ? { detail: detail.slice(0, 300) } : {}), ...(ref ? { ref } : {}) };
    await idb.put("history", item.id, item);
    for (const w of new Set<Window>([window, window.parent])) { try { w.dispatchEvent(new Event("vk-history")); w.dispatchEvent(new Event("vk-dirty")); } catch { /* another origin */ } } // the Assistant runs in a frame; tell the page around it too
  } catch { /* history is a nicety; never block the real work */ }
}

export async function listHistory(limit = 300): Promise<HistoryItem[]> {
  try { return (await idb.all<HistoryItem>("history")).sort((a, b) => b.ts - a.ts).slice(0, limit); } catch { return []; }
}

/** Records "edited" at most once every 30 minutes per project, so autosave does not flood the list. */
export async function noteProjectEdit(id: string, name: string): Promise<void> {
  try {
    const last = await idb.get<number>("meta", "edit:" + id);
    const now = Date.now();
    if (last && now - last < 30 * 60_000) return;
    await idb.put("meta", "edit:" + id, now);
    await addHistory("project_edit", name || "Untitled project", undefined, id);
  } catch { /* ignore */ }
}

export async function clearHistory(): Promise<void> {
  const all = await idb.all<HistoryItem>("history");
  await Promise.all(all.map((h) => idb.del("history", h.id)));
  window.dispatchEvent(new Event("vk-history"));
  window.dispatchEvent(new Event("vk-dirty"));
}
