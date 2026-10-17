// Optional: a private copy of the project list and history in the person's own Google Drive ("app data" folder).
// Only the small project descriptions and the history list go there. Videos, pictures and sounds never leave the computer.
// The folder is hidden, belongs to this site only, and can be removed in Google Account → Third-party connections.
import { idb } from "./idb";
import type { HistoryItem } from "./history";
import { getToken } from "./auth";

const NAME = "vkeditor-account.json";
const API = "https://www.googleapis.com/drive/v3";
const UPLOAD = "https://www.googleapis.com/upload/drive/v3";

interface ProjectRec { id: string; updated?: number; [k: string]: unknown }
interface Bundle { v: 1; saved: number; projects: Record<string, ProjectRec>; deleted: Record<string, number>; history: HistoryItem[] }

export interface SyncResult { ok: boolean; message: string; needsReconnect?: boolean }

async function api(token: string, url: string, init: RequestInit = {}): Promise<Response> {
  const res = await fetch(url, { ...init, headers: { ...(init.headers ?? {}), Authorization: `Bearer ${token}` } });
  if (res.status === 401) throw new Error("expired");
  if (res.status === 403) throw new Error("Google Drive refused. Make sure the Google Drive API is switched on for your Google Cloud project, and that you allowed the Drive permission when signing in.");
  if (!res.ok) throw new Error(`Google Drive answered ${res.status}.`);
  return res;
}

async function findFile(token: string): Promise<string | null> {
  const q = encodeURIComponent(`name='${NAME}' and trashed=false`);
  const r = await api(token, `${API}/files?spaces=appDataFolder&q=${q}&fields=files(id,modifiedTime)&pageSize=1`);
  const j = await r.json();
  return j.files?.[0]?.id ?? null;
}

async function readRemote(token: string, id: string): Promise<Bundle | null> {
  const r = await api(token, `${API}/files/${id}?alt=media`);
  try { const b = await r.json(); return b && b.v === 1 ? (b as Bundle) : null; } catch { return null; }
}

async function writeRemote(token: string, id: string | null, b: Bundle): Promise<void> {
  const body = JSON.stringify(b);
  if (id) { await api(token, `${UPLOAD}/files/${id}?uploadType=media`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body }); return; }
  const boundary = "vk" + Math.random().toString(16).slice(2);
  const meta = JSON.stringify({ name: NAME, parents: ["appDataFolder"], mimeType: "application/json" });
  const multi = `--${boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n${meta}\r\n--${boundary}\r\nContent-Type: application/json\r\n\r\n${body}\r\n--${boundary}--`;
  await api(token, `${UPLOAD}/files?uploadType=multipart`, { method: "POST", headers: { "Content-Type": `multipart/related; boundary=${boundary}` }, body: multi });
}

async function readLocal(): Promise<Bundle> {
  const projects: Record<string, ProjectRec> = {};
  const keys = (await idb.all<ProjectRec>("projects"));
  for (const p of keys) if (p?.id) projects[p.id] = p;
  const deleted = (await idb.get<Record<string, number>>("meta", "tombstones")) ?? {};
  const history = await idb.all<HistoryItem>("history");
  return { v: 1, saved: Date.now() / 1000, projects, deleted, history };
}

/** Last write wins per project; a deletion wins over an older copy; the history is the union of both sides (newest 500). */
export function merge(a: Bundle | null, b: Bundle): Bundle {
  const deleted: Record<string, number> = { ...(a?.deleted ?? {}) };
  for (const [k, v] of Object.entries(b.deleted)) deleted[k] = Math.max(deleted[k] ?? 0, v);
  const projects: Record<string, ProjectRec> = {};
  for (const src of [a?.projects ?? {}, b.projects]) {
    for (const [id, p] of Object.entries(src)) {
      const have = projects[id];
      if (!have || (p.updated ?? 0) > (have.updated ?? 0)) projects[id] = p;
    }
  }
  for (const [id, ts] of Object.entries(deleted)) if (projects[id] && (projects[id].updated ?? 0) <= ts) delete projects[id];
  const seen = new Map<string, HistoryItem>();
  for (const h of [...(a?.history ?? []), ...b.history]) seen.set(h.id, h);
  const history = [...seen.values()].sort((x, y) => y.ts - x.ts).slice(0, 500);
  return { v: 1, saved: Date.now() / 1000, projects, deleted, history };
}

async function writeLocal(m: Bundle): Promise<void> {
  const have = await idb.all<ProjectRec>("projects");
  const known = new Map(have.map((p) => [p.id, p]));
  for (const [id, p] of Object.entries(m.projects)) if ((known.get(id)?.updated ?? -1) < (p.updated ?? 0)) await idb.put("projects", id, p);
  for (const id of known.keys()) if (!m.projects[id]) await idb.del("projects", id);
  await idb.put("meta", "tombstones", m.deleted);
  const mine = new Set((await idb.all<HistoryItem>("history")).map((h) => h.id));
  for (const h of m.history) if (!mine.has(h.id)) await idb.put("history", h.id, h);
}

export async function markProjectDeleted(id: string): Promise<void> {
  const t = (await idb.get<Record<string, number>>("meta", "tombstones")) ?? {};
  t[id] = Date.now() / 1000;
  await idb.put("meta", "tombstones", t);
  window.dispatchEvent(new Event("vk-dirty"));
}

let running: Promise<SyncResult> | null = null;
export function syncNow(): Promise<SyncResult> {
  if (running) return running;
  running = (async (): Promise<SyncResult> => {
    const token = getToken();
    if (!token) return { ok: false, needsReconnect: true, message: "Reconnect to Google to sync (press “Reconnect Drive”)." };
    try {
      const id = await findFile(token);
      const remote = id ? await readRemote(token, id) : null;
      const merged = merge(remote, await readLocal());
      await writeLocal(merged);
      await writeRemote(token, id, merged);
      window.dispatchEvent(new Event("vk-history")); window.dispatchEvent(new Event("vk-synced"));
      try { localStorage.setItem("vk_last_sync", String(Date.now())); } catch { /* ignore */ }
      return { ok: true, message: `Synced ${Object.keys(merged.projects).length} project(s) and ${merged.history.length} history item(s) with your Google Drive.` };
    } catch (e) {
      const m = e instanceof Error ? e.message : "Sync failed.";
      return m === "expired" ? { ok: false, needsReconnect: true, message: "Your Google session ended. Press “Reconnect Drive”." } : { ok: false, message: m };
    }
  })().finally(() => { running = null; });
  return running;
}

let timer: number | undefined;
/** After any change, copy to Drive 20 seconds later (if the person is connected). */
export function startAutoSync(): void {
  window.addEventListener("vk-dirty", () => {
    if (!getToken()) return;
    window.clearTimeout(timer);
    timer = window.setTimeout(() => { void syncNow(); }, 20_000);
  });
}
