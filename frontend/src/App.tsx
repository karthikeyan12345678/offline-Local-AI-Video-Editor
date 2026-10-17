import { useEffect, useRef, useState } from "react";
import { AppProvider, useApp } from "./lib/store";
import { Icon, I } from "./ds";
import Generate from "./views/Generate";
import Library from "./views/Library";
import Editor from "./views/Editor";
import Tour, { type TourStep } from "./Tour";
import Settings from "./views/Settings";
import MotionControl from "./views/MotionControl";
import Setup from "./views/Setup";
import { JobCard } from "./views/shared";
import { useUpdateCheck } from "./views/Updates";
import type { Asset } from "./lib/types";
import { api, token } from "./lib/api";

type View = "generate" | "library" | "editor" | "motion" | "settings";
const NAV: { id: View; label: string; icon: string }[] = [
  { id: "generate", label: "Make video", icon: I.sparkle }, { id: "library", label: "Library", icon: I.folder },
  { id: "editor", label: "Editor", icon: I.film }, { id: "motion", label: "Motion control", icon: I.wand },
  { id: "settings", label: "Settings", icon: I.gear },
];

function useRefValue<T>(v: T) { const r = useRef(v); r.current = v; return r; }

function Shell() {
  const { ready, connectionLost, jobs, toasts, needsSetup, system, settings, setSettings } = useApp();
  const [view, setView] = useState<View>("generate");
  const [visited, setVisited] = useState<Set<View>>(new Set(["generate"]));
  const [skipSetup, setSkipSetup] = useState(false);
  const [queue, setQueue] = useState<Asset[]>([]);
  const upd = useUpdateCheck(ready);
  const hasUpdate = !!upd.info && (upd.info.app_update || upd.info.modules_update);

  const { refreshAssets, toast } = useApp();
  const [overDrop, setOverDrop] = useState(false);
  const viewRef = useRefValue(view);

  // Dropping files ANYWHERE in the window adds them (a view's own handler runs first; this catches every other spot, so the app never tries to open the file itself).
  useEffect(() => {
    const hasFiles = (e: DragEvent) => !!e.dataTransfer && Array.from(e.dataTransfer.types).includes("Files");
    const over = (e: DragEvent) => { if (hasFiles(e)) { e.preventDefault(); setOverDrop(true); } };
    const leave = (e: DragEvent) => { if (!e.relatedTarget) setOverDrop(false); };
    // A slot or page may stop the drop from bubbling, so the veil is also cleared in the capture phase, on drag end, and if no dragover arrives for a moment.
    const clear = () => setOverDrop(false);
    let idle: number | undefined;
    const keepAlive = (e: DragEvent) => { if (hasFiles(e)) { window.clearTimeout(idle); idle = window.setTimeout(clear, 600); } };
    const drop = async (e: DragEvent) => {
      setOverDrop(false);
      if (!hasFiles(e)) return;
      if (e.defaultPrevented) return; // a page (Library, Editor) already took the files
      e.preventDefault();
      const files = Array.from(e.dataTransfer?.files ?? []);
      if (!files.length) return;
      if (viewRef.current === "editor") { window.dispatchEvent(new CustomEvent("vk-drop-files", { detail: files })); return; }
      for (const f of files) { try { await api.upload(f); } catch (err) { toast(`${f.name}: ${(err as Error).message}`, true); } }
      await refreshAssets();
      toast(`Added ${files.length} file${files.length > 1 ? "s" : ""} to your Library.`);
    };
    window.addEventListener("dragover", over); window.addEventListener("dragover", keepAlive); window.addEventListener("dragleave", leave); window.addEventListener("drop", drop);
    window.addEventListener("drop", clear, true); window.addEventListener("dragend", clear, true); window.addEventListener("blur", clear);
    return () => {
      window.clearTimeout(idle);
      window.removeEventListener("dragover", over); window.removeEventListener("dragover", keepAlive); window.removeEventListener("dragleave", leave); window.removeEventListener("drop", drop);
      window.removeEventListener("drop", clear, true); window.removeEventListener("dragend", clear, true); window.removeEventListener("blur", clear);
    };
  }, [refreshAssets, toast, viewRef]);

  const [tourOn, setTourOn] = useState(false);
  useEffect(() => { if (settings && !settings.tour_done && !(needsSetup && !skipSetup)) setTourOn(true); }, [settings?.tour_done, !!settings, needsSetup, skipSetup]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { const on = () => setTourOn(true); window.addEventListener("vk-tour", on); return () => window.removeEventListener("vk-tour", on); }, []);
  const finishTour = () => { setTourOn(false); setView("generate"); void setSettings({ tour_done: true }); };
  const TOUR: TourStep[] = [
    { title: "Welcome to VK Editor", body: "A 30-second tour of where everything is. Everything runs on your PC; nothing is uploaded unless you pick an online service. You can skip now and replay it from Settings." },
    { target: "generate", title: "Make video", body: "Describe a scene (or add a start and end picture), press “Improve prompt” for more detail, and check the time estimate under the buttons before you press Generate. The meters below show your CPU, GPU, memory and graphics memory live.", go: () => setView("generate") },
    { target: "library", title: "Library", body: "Everything you make or drop into the window lives here. Drag files anywhere to add them.", go: () => setView("library") },
    { target: "editor", title: "Editor", body: "Cut, add text, captions, music and effects. The chat panel understands plain words like “make it vertical” or “add a title”.", go: () => setView("editor") },
    { target: "motion", title: "Motion control", body: "Give a character picture and a video of someone moving; the character repeats the movement. This runs in the cloud with your own fal.ai key, saved only on this PC.", go: () => setView("motion") },
    { target: "settings", title: "Settings", body: "Check This PC (a graphics warning shows here), choose the Lite profile for a 4 to 7 GB card, set the time limit, and update the AI modules.", go: () => setView("settings") },
    { target: "assistant", title: "AI Assistant", body: "Opens in its own window: chat, PDF/slides/Word/Excel files, resume ATS check and tailoring, images. Its Settings page has “Help me choose the best AI for my PC”." },
    { title: "You are ready", body: "Start with Make video. If a video would take too long on your PC, the estimate tells you before you start." },
  ];
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
            <li key={n.id}><button type="button" className="nav-item" data-tour={n.id} aria-current={view === n.id ? "page" : undefined} onClick={() => go(n.id)}><Icon d={n.icon} />{n.label}{n.id === "settings" && hasUpdate ? <span className="upd-dot" title="An update is available" aria-label="update available" /> : null}</button></li>
          ))}
          <li><button type="button" className="nav-item" data-tour="assistant" title="Chat, create PDF/PPT/Word/CSV/Excel, compare files, resume ATS check, images, analytics (opens in its own window)"
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
      {tourOn && <Tour steps={TOUR} onDone={finishTour} />}
      {overDrop && <div className="drop-veil" role="status">Drop to add to your Library</div>}
      <div className="toasts" aria-live="polite">{toasts.map((t) => <div key={t.id} className={`toast${t.error ? " toast--error" : ""}`} role={t.error ? "alert" : "status"}>{t.text}</div>)}</div>
    </div>
  );
}

export default function App() {
  return <AppProvider><Shell /></AppProvider>;
}
