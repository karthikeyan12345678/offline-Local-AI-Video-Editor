import { useState } from "react";
import { AppProvider, useApp } from "./lib/store";
import { Icon, I } from "./ds";
import Generate from "./views/Generate";
import Library from "./views/Library";
import Editor from "./views/Editor";
import Settings from "./views/Settings";
import MotionControl from "./views/MotionControl";
import Setup from "./views/Setup";
import { JobCard } from "./views/shared";
import { useUpdateCheck } from "./views/Updates";
import type { Asset } from "./lib/types";
import { token } from "./lib/api";

type View = "generate" | "library" | "editor" | "motion" | "settings";
const NAV: { id: View; label: string; icon: string }[] = [
  { id: "generate", label: "Make video", icon: I.sparkle }, { id: "library", label: "Library", icon: I.folder },
  { id: "editor", label: "Editor", icon: I.film }, { id: "motion", label: "Motion control", icon: I.wand },
  { id: "settings", label: "Settings", icon: I.gear },
];

function Shell() {
  const { ready, connectionLost, jobs, toasts, needsSetup, system } = useApp();
  const [view, setView] = useState<View>("generate");
  const [visited, setVisited] = useState<Set<View>>(new Set(["generate"]));
  const [skipSetup, setSkipSetup] = useState(false);
  const [queue, setQueue] = useState<Asset[]>([]);
  const upd = useUpdateCheck(ready);
  const hasUpdate = !!upd.info && (upd.info.app_update || upd.info.modules_update);

  const go = (v: View) => { setView(v); setVisited((s) => new Set(s).add(v)); };
  const shownJobs = jobs.filter((j) => j.status === "queued" || j.status === "running").slice(0, 4);

  if (!ready) {
    return <div className="center-screen" role="status">{connectionLost ? <div className="stack gap center-text"><Icon d={I.alert} size={24} /><h2>Can’t reach the app</h2><p>Close this window and open VK Editor again.</p></div> : <><span className="spinner" /><span>Starting…</span></>}</div>;
  }
  if (needsSetup && !skipSetup && system) return <Setup onSkip={() => setSkipSetup(true)} />;

  return (
    <div className="shell">
      <nav className="nav" aria-label="Main">
        <div className="brand"><img src="/logo.png" alt="" width={28} height={28} style={{ borderRadius: 7 }} /><span className="w-semibold">VK Editor</span></div>
        <ul>
          {NAV.map((n) => (
            <li key={n.id}><button type="button" className="nav-item" aria-current={view === n.id ? "page" : undefined} onClick={() => go(n.id)}><Icon d={n.icon} />{n.label}{n.id === "settings" && hasUpdate ? <span className="upd-dot" title="An update is available" aria-label="update available" /> : null}</button></li>
          ))}
          <li><button type="button" className="nav-item" title="Chat, create PDF/PPT/Word/CSV/Excel, compare files, resume ATS check, images, analytics (opens in its own window)"
            onClick={() => window.open(`/assistant-app/?t=${encodeURIComponent(token)}`, "_blank")}><Icon d={I.sparkle} />AI Assistant</button></li>
        </ul>
        <div className="nav-jobs stack gap" aria-label="Running tasks">{shownJobs.map((j) => <JobCard key={j.id} job={j} />)}</div>
      </nav>
      <div className="content">
        {connectionLost && <p className="banner" role="alert"><Icon d={I.alert} size={14} /> Lost contact with the app. If it was closed, open it again.</p>}
        <div hidden={view !== "generate"}>{visited.has("generate") && <Generate goLibrary={() => go("library")} goSettings={() => go("settings")} />}</div>
        <div hidden={view !== "library"}>{visited.has("library") && <Library onEdit={(a) => { setQueue((q) => [...q, a]); go("editor"); }} />}</div>
        <div hidden={view !== "editor"} className="fill">{visited.has("editor") && <Editor queue={queue} onQueueDone={() => setQueue([])} visible={view === "editor"} />}</div>
        <div hidden={view !== "motion"}>{visited.has("motion") && <MotionControl goLibrary={() => go("library")} />}</div>
        <div hidden={view !== "settings"}>{visited.has("settings") && <Settings />}</div>
      </div>
      <div className="toasts" aria-live="polite">{toasts.map((t) => <div key={t.id} className={`toast${t.error ? " toast--error" : ""}`} role={t.error ? "alert" : "status"}>{t.text}</div>)}</div>
    </div>
  );
}

export default function App() {
  return <AppProvider><Shell /></AppProvider>;
}
