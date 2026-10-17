import { useCallback, useEffect, useState } from "react";
import { useApp } from "../lib/store";
import { Button, Icon, I } from "../ds";
import { webCall } from "../web/backend";
import { currentProfile } from "../../../shared/web/account";
import { listHistory, clearHistory, type HistoryItem, type HistoryType } from "../../../shared/web/history";
import { syncNow } from "../../../shared/web/drive";
import { driveReady, reconnectDrive } from "../../../shared/web/auth";

interface ProjectRow { id: string; name: string; updated: number }
const ICON: Record<HistoryType, string> = { sign_in: I.check, project_new: I.plus, project_edit: I.film, export: I.download, video: I.sparkle, motion: I.wand, assistant: I.text, import: I.upload };
const LABEL: Record<HistoryType, string> = { sign_in: "Signed in", project_new: "New project", project_edit: "Edited project", export: "Exported video", video: "Made a video", motion: "Motion control", assistant: "Assistant file", import: "Imported" };
const FILTERS: { id: string; label: string; types: HistoryType[] | null }[] = [
  { id: "all", label: "Everything", types: null }, { id: "projects", label: "Projects", types: ["project_new", "project_edit"] },
  { id: "videos", label: "AI videos", types: ["video", "motion"] }, { id: "exports", label: "Exports", types: ["export"] }, { id: "assistant", label: "Assistant", types: ["assistant"] },
];

const ago = (ts: number) => {
  const s = Math.max(1, Date.now() / 1000 - ts);
  if (s < 90) return "just now"; if (s < 5400) return `${Math.round(s / 60)} min ago`; if (s < 129600) return `${Math.round(s / 3600)} h ago`;
  return new Date(ts * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short", year: s > 3.2e7 ? "numeric" : undefined });
};

/** The person's own page: new project, old projects, and a history of everything they made. */
export default function Home({ go }: { go: (view: string) => void }) {
  const { toast } = useApp();
  const me = currentProfile();
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [hist, setHist] = useState<HistoryItem[]>([]);
  const [filter, setFilter] = useState("all");
  const [sync, setSync] = useState<{ busy: boolean; text: string; ok: boolean }>({ busy: false, text: "", ok: true });
  const [, tick] = useState(0);

  const load = useCallback(async () => {
    setProjects((await webCall("GET", "/projects")) as ProjectRow[]);
    setHist(await listHistory());
  }, []);
  useEffect(() => { void load(); const on = () => void load(); window.addEventListener("vk-history", on); window.addEventListener("vk-synced", on); return () => { window.removeEventListener("vk-history", on); window.removeEventListener("vk-synced", on); }; }, [load]);

  const openProject = (id: string) => { go("editor"); setTimeout(() => window.dispatchEvent(new CustomEvent("vk-open-project", { detail: id })), 60); };
  const newProject = () => { go("editor"); setTimeout(() => window.dispatchEvent(new Event("vk-new-project")), 60); };
  const remove = async (p: ProjectRow) => { if (!confirm(`Delete “${p.name || "Untitled"}” for good? (Videos in your library stay.)`)) return; await webCall("DELETE", `/projects/${p.id}`); await load(); };

  const doSync = async () => {
    setSync({ busy: true, text: "", ok: true });
    if (!driveReady()) {
      try { if (!(await reconnectDrive())) { setSync({ busy: false, ok: false, text: "Google Drive permission was not given. Sign out and sign in again, and tick the Drive box." }); return; } }
      catch (e) { setSync({ busy: false, ok: false, text: e instanceof Error ? e.message : "Could not reconnect." }); return; }
    }
    const r = await syncNow();
    setSync({ busy: false, text: r.message, ok: r.ok }); tick((n) => n + 1);
    if (r.ok) toast("Projects and history synced."); else toast(r.message, true);
  };

  const shown = hist.filter((h) => { const f = FILTERS.find((x) => x.id === filter); return !f?.types || f.types.includes(h.type); });
  const first = (me?.name || "there").split(" ")[0];
  const lastSync = (() => { try { return Number(localStorage.getItem("vk_last_sync") || 0); } catch { return 0; } })();

  return (
    <main className="page home">
      <div className="row gap center-v wrap home-hello">
        {me?.picture ? <img className="avatar" src={me.picture} alt="" width={48} height={48} referrerPolicy="no-referrer" /> : <span className="avatar avatar--blank" aria-hidden="true">{first.slice(0, 1).toUpperCase()}</span>}
        <div className="stack grow"><h1>Hi, {first}</h1><p className="text-sm muted">{me?.guest ? "Guest mode: your work stays in this browser only. Sign in with Google to keep projects and history under your account." : `${me?.email} · your projects and history are saved to this account`}</p></div>
      </div>

      <section className="home-actions" aria-label="Start something">
        <button type="button" className="home-tile" onClick={newProject}><Icon d={I.plus} size={22} /><b>New project</b><span>Open an empty timeline in the Editor</span></button>
        <button type="button" className="home-tile" onClick={() => go("make")}><Icon d={I.sparkle} size={22} /><b>Make a video</b><span>Text, picture or continue a clip</span></button>
        <button type="button" className="home-tile" onClick={() => go("motion")}><Icon d={I.wand} size={22} /><b>Motion control</b><span>Make a character move like a video</span></button>
        <button type="button" className="home-tile" onClick={() => go("assistant")}><Icon d={I.text} size={22} /><b>AI Assistant</b><span>Chat, PDF, slides, Word, Excel, resume ATS</span></button>
      </section>

      <section className="stack gap" aria-labelledby="proj-h">
        <div className="row between gap wrap"><h2 id="proj-h">Your projects</h2><span className="text-sm muted">{projects.length} saved</span></div>
        {projects.length === 0 ? <div className="card text-sm">No projects yet. Press <b>New project</b>, or make a video and press “Edit this video”.</div> : (
          <ul className="home-projects">
            {projects.map((p) => (
              <li key={p.id} className="card row between gap center-v">
                <div className="stack"><b className="truncate">{p.name || "Untitled project"}</b><span className="text-xs muted">Last changed {ago(p.updated)}</span></div>
                <div className="row gap"><Button small onClick={() => openProject(p.id)}>Open</Button><Button small variant="ghost" icon={I.trash} label={`Delete ${p.name || "project"}`} onClick={() => void remove(p)} /></div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="stack gap" aria-labelledby="hist-h">
        <div className="row between gap wrap"><h2 id="hist-h">History</h2>
          <div className="gchips" role="group" aria-label="Filter history">{FILTERS.map((f) => <button key={f.id} type="button" className={`gchip${filter === f.id ? " gchip--on" : ""}`} aria-pressed={filter === f.id} onClick={() => setFilter(f.id)}><span>{f.label}</span></button>)}</div></div>
        {shown.length === 0 ? <div className="card text-sm">Nothing here yet. Things you make show up in this list.</div> : (
          <ol className="home-history">
            {shown.slice(0, 80).map((h) => (
              <li key={h.id} className="row gap center-v"><span className="hist-ico" aria-hidden="true"><Icon d={ICON[h.type] ?? I.check} size={15} /></span>
                <div className="stack grow"><span className="text-sm"><b>{LABEL[h.type] ?? h.type}</b> · {h.title}</span>{h.detail && <span className="text-xs muted truncate">{h.detail}</span>}</div>
                <span className="text-xs muted">{ago(h.ts)}</span></li>
            ))}
          </ol>
        )}
        {hist.length > 0 && <div><Button small variant="ghost" onClick={async () => { if (confirm("Clear the whole history list? Your projects and files are not touched.")) { await clearHistory(); await load(); } }}>Clear history</Button></div>}
      </section>

      {!me?.guest && (
        <section className="card stack gap" aria-labelledby="sync-h">
          <h2 id="sync-h">Google Drive copy</h2>
          <p className="text-sm">{me?.driveOk ? "Your project list and history are copied to a hidden, private folder in your own Google Drive, so you see them on any computer you sign in on. Videos, pictures and sounds never leave this computer." : "Drive permission was not given, so projects and history stay in this browser only. Sign out and sign in again and tick the Drive box to turn the copy on."}</p>
          {me?.driveOk && <div className="row gap center-v wrap"><Button small variant="secondary" busy={sync.busy} onClick={() => void doSync()}>{driveReady() ? "Sync now" : "Reconnect Drive and sync"}</Button>
            <span className="text-xs muted" role="status">{sync.text || (lastSync ? `Last synced ${new Date(lastSync).toLocaleString()}` : "Not synced in this session yet.")}</span></div>}
        </section>
      )}
    </main>
  );
}
