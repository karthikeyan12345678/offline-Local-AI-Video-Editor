import { useEffect, useState } from "react";
import { AppProvider, useApp } from "../lib/store";
import { Icon, I } from "../ds";
import Editor from "../views/Editor";
import Library from "../views/Library";
import { JobCard } from "../views/shared";
import { api } from "../lib/api";
import type { Asset } from "../lib/types";
import Home from "./Home";
import MakeVideoWeb from "./MakeVideoWeb";
import MotionWeb from "./MotionWeb";
import SettingsWeb from "./SettingsWeb";
import AssistantFrame from "./AssistantFrame";
import { currentProfile } from "../../../shared/web/account";
import { go as navigate } from "./route";
import { config } from "../../../shared/web/config";
import "./workspace.css";

export type View = "home" | "make" | "library" | "editor" | "motion" | "assistant" | "settings" | "help";
const NAV: { id: View; label: string; icon: string }[] = [
  { id: "home", label: "Home", icon: I.check }, { id: "make", label: "Make video", icon: I.sparkle }, { id: "library", label: "Library", icon: I.folder },
  { id: "editor", label: "Editor", icon: I.film }, { id: "motion", label: "Motion control", icon: I.wand }, { id: "assistant", label: "AI Assistant", icon: I.text },
  { id: "settings", label: "Settings", icon: I.gear },
];
const isView = (v: string | undefined): v is View => !!v && [...NAV.map((n) => n.id), "help"].includes(v);

function Shell({ view, setView }: { view: View; setView: (v: View) => void }) {
  const { ready, connectionLost, jobs, toasts, toast, refreshAssets } = useApp();
  const [queue, setQueue] = useState<Asset[]>([]);
  const [visited, setVisited] = useState<Set<View>>(new Set([view]));
  const [over, setOver] = useState(false);
  const me = currentProfile();
  const goTo = (v: View) => { setVisited((s) => new Set(s).add(v)); setView(v); };
  useEffect(() => { setVisited((s) => (s.has(view) ? s : new Set(s).add(view))); }, [view]);
  const toEditor = (a: Asset) => { setQueue((q) => [...q, a]); goTo("editor"); };

  useEffect(() => {
    const hasFiles = (e: DragEvent) => !!e.dataTransfer && Array.from(e.dataTransfer.types).includes("Files");
    const dragOver = (e: DragEvent) => { if (hasFiles(e)) { e.preventDefault(); setOver(true); } };
    const clear = () => setOver(false);
    const drop = async (e: DragEvent) => {
      setOver(false);
      if (!hasFiles(e) || e.defaultPrevented) return;
      e.preventDefault();
      const files = Array.from(e.dataTransfer?.files ?? []);
      if (view === "editor") { window.dispatchEvent(new CustomEvent("vk-drop-files", { detail: files })); return; }
      for (const f of files) { try { await api.upload(f); } catch (err) { toast(`${f.name}: ${(err as Error).message}`, true); } }
      await refreshAssets(); toast(`Added ${files.length} file${files.length > 1 ? "s" : ""} to your Library.`);
    };
    window.addEventListener("dragover", dragOver); window.addEventListener("dragleave", clear); window.addEventListener("drop", drop); window.addEventListener("dragend", clear);
    return () => { window.removeEventListener("dragover", dragOver); window.removeEventListener("dragleave", clear); window.removeEventListener("drop", drop); window.removeEventListener("dragend", clear); };
  }, [view, toast, refreshAssets]);

  if (!ready) return <div className="center-screen" role="status">{connectionLost ? "The browser storage is not available. Allow site data for this page (or leave private mode) and reload." : <><span className="spinner" /><span>Starting…</span></>}</div>;
  const shownJobs = jobs.filter((j) => j.status === "queued" || j.status === "running").slice(0, 4);
  return (
    <div className="shell shell--web">
      <nav className="nav" aria-label="Main">
        <a className="brand" href="#/" title="Back to the home page"><img src="logo.png" alt="" width={28} height={28} style={{ borderRadius: 7 }} /><span className="w-semibold">{config().siteName}</span></a>
        <ul>
          {NAV.map((n) => <li key={n.id}><button type="button" className="nav-item" aria-current={view === n.id ? "page" : undefined} onClick={() => goTo(n.id)}><Icon d={n.icon} />{n.label}</button></li>)}
          <li><button type="button" className="nav-item" aria-current={view === "help" ? "page" : undefined} onClick={() => goTo("help")}><Icon d={I.alert} />Help</button></li>
        </ul>
        <div className="nav-jobs stack gap" aria-label="Running tasks">{shownJobs.map((j) => <JobCard key={j.id} job={j} />)}</div>
        <button type="button" className="nav-account" onClick={() => goTo("settings")} title="Account and settings">
          {me?.picture ? <img className="avatar avatar--sm" src={me.picture} alt="" width={28} height={28} referrerPolicy="no-referrer" /> : <span className="avatar avatar--sm avatar--blank" aria-hidden="true">{(me?.name ?? "G").slice(0, 1)}</span>}
          <span className="stack"><b className="text-sm truncate">{me?.name ?? "Guest"}</b><span className="text-xs muted truncate">{me?.guest ? "Guest mode" : me?.email}</span></span>
        </button>
      </nav>
      <div className="content">
        {connectionLost && <p className="banner" role="alert"><Icon d={I.alert} size={14} /> The browser storage stopped answering. Reload the page.</p>}
        <div hidden={view !== "home"}>{visited.has("home") && <Home go={(v) => goTo(v as View)} />}</div>
        <div hidden={view !== "make"}>{visited.has("make") && <MakeVideoWeb goLibrary={() => goTo("library")} goSettings={() => goTo("settings")} goEditor={toEditor} />}</div>
        <div hidden={view !== "library"}>{visited.has("library") && <Library onEdit={toEditor} />}</div>
        <div hidden={view !== "editor"} className="fill"><Editor queue={queue} onQueueDone={() => setQueue([])} visible={view === "editor"} /></div>
        <div hidden={view !== "motion"}>{visited.has("motion") && <MotionWeb goLibrary={() => goTo("library")} goSettings={() => goTo("settings")} goEditor={toEditor} />}</div>
        <div hidden={view !== "assistant"} className="fill">{visited.has("assistant") && <AssistantFrame />}</div>
        <div hidden={view !== "settings"}>{visited.has("settings") && <SettingsWeb />}</div>
        <div hidden={view !== "help"}>{visited.has("help") && <Help />}</div>
      </div>
      {over && <div className="drop-veil" role="status">Drop to add to your Library</div>}
      <div className="toasts" aria-live="polite">{toasts.map((t) => <div key={t.id} className={`toast${t.error ? " toast--error" : ""}`} role={t.error ? "alert" : "status"}>{t.text}</div>)}</div>
    </div>
  );
}

function Help() {
  const c = config();
  return (
    <main className="page narrow stack gap">
      <h1>Help</h1>
      <div className="card stack gap"><h2>Five steps</h2>
        <ol className="text-sm"><li><b>Make video</b>: describe a scene (or give a picture, or a clip to continue). A free GPU makes it. Add your free Hugging Face token in Settings for more daily time.</li>
          <li><b>Library</b>: everything you made or added. Drag files into the window to add more.</li>
          <li><b>Editor</b>: cut, add text, filters, effects, transitions and sounds. Press <b>Export</b> to save an MP4.</li>
          <li><b>Motion control</b>: a character picture + a video of someone moving.</li>
          <li><b>AI Assistant</b>: chat, make PDF / slides / Word / Excel / CSV files, check or tailor a resume, compare files, analyse data, make images.</li></ol></div>
      <div className="card stack gap"><h2>Good to know</h2>
        <ul className="text-sm">
          <li>Everything on this site is free. AI video uses free GPU time from Hugging Face (a few minutes a day, renewing). Chat uses a free AI key you create yourself.</li>
          <li>Free GPUs are shared: you may wait in a queue, and a Space can be asleep or paused by its owner.</li>
          <li>Exporting runs inside your browser and takes roughly 10 to 15 times the length of the video.</li>
          <li>Need no queue and no daily limit? <a href={c.localRepo} target="_blank" rel="noreferrer">Run VK Editor on your own computer</a> (free download).</li>
        </ul></div>
      <div className="row gap"><a className="linklike" href="#/guide">Open the full user guide</a><button type="button" className="linklike" onClick={() => navigate("")}>Back to the home page</button></div>
    </main>
  );
}

export default function Workspace({ start }: { start?: string }) {
  const [view, setViewState] = useState<View>(isView(start) ? start : "home");
  const setView = (v: View) => { setViewState(v); if (location.hash !== `#/app/${v}`) history.replaceState(null, "", `#/app/${v}`); };
  useEffect(() => { if (isView(start)) setViewState(start); }, [start]);
  return <AppProvider><Shell view={view} setView={setView} /></AppProvider>;
}
