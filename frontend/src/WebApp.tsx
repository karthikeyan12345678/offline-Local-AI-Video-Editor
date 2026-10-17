import { useEffect, useState } from "react";
import { AppProvider, useApp } from "./lib/store";
import { Icon, I } from "./ds";
import Editor from "./views/Editor";
import Library from "./views/Library";
import WebAI from "./web/WebAI";
import { api } from "./lib/api";
import type { Asset } from "./lib/types";

type View = "editor" | "library" | "ai" | "about";

function Shell() {
  const { ready, connectionLost, toasts, toast, refreshAssets } = useApp();
  const [view, setView] = useState<View>("editor");
  const [queue, setQueue] = useState<Asset[]>([]);
  const [over, setOver] = useState(false);

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

  if (!ready) return <div className="center-screen" role="status">{connectionLost ? "The browser storage is not available. Allow site data for this page (or leave private mode) and reload." : "Starting…"}</div>;
  const nav = (id: View, label: string) => <button type="button" className="navbtn" aria-current={view === id ? "page" : undefined} onClick={() => setView(id)}>{label}</button>;
  return (
    <div className="web-shell">
      <header className="web-top">
        <div className="brand"><img src="logo.png" alt="" width={24} height={24} style={{ borderRadius: 6 }} /><span>VK Editor</span></div>
        {nav("editor", "Editor")}{nav("library", "My files")}{nav("ai", "AI & free credits")}{nav("about", "Help")}
        <span className="grow" />
        <span className="text-xs" style={{ opacity: .7 }}><Icon d={I.check} size={12} /> Free · runs in your browser · files stay on this device</span>
      </header>
      <main className="web-main">
        <div hidden={view !== "editor"} className="fill"><Editor queue={queue} onQueueDone={() => setQueue([])} visible={view === "editor"} /></div>
        {view === "library" && <div className="web-page"><Library onEdit={(a) => { setQueue((q) => [...q, a]); setView("editor"); }} /></div>}
        {view === "ai" && <WebAI />}
        {view === "about" && <About />}
      </main>
      {over && <div className="drop-veil" role="status">Drop to add</div>}
      <div className="toasts" aria-live="polite">{toasts.map((t) => <div key={t.id} className={`toast${t.error ? " toast--error" : ""}`} role={t.error ? "alert" : "status"}>{t.text}</div>)}</div>
    </div>
  );
}

function About() {
  return (
    <div className="web-page stack gap">
      <h1>Help</h1>
      <div className="card stack gap">
        <h2>Four steps</h2>
        <ol className="text-sm"><li><b>Import</b> a video, picture or song (Media tab), or drag files into the window.</li><li>Click a thumbnail to put it on the <b>timeline</b>. Drag the ends to trim, press <b>S</b> to split.</li><li>Use the left tabs: <b>Audio</b> (38 sounds), <b>Text</b>, <b>Effects</b>, <b>Filters</b>, <b>Transitions</b>. Tweak details on the right.</li><li>Press <b>Export</b>. The video is made inside your browser and saved to your computer.</li></ol>
      </div>
      <div className="card stack gap">
        <h2>Good to know</h2>
        <ul className="text-sm">
          <li>Everything is free and private: your files never leave this device. Only chat messages go to the AI service you choose.</li>
          <li>Exporting runs in the browser, so it is slower than the desktop app (roughly 10 to 15 times the length of the video for a 720p clip). Keep this tab open while it renders.</li>
          <li>Your work is saved automatically in this browser. Clearing site data erases it, so export finished videos.</li>
          <li>Making new AI video (text to video) needs a graphics card and is not part of the website version.</li>
        </ul>
      </div>
    </div>
  );
}

export default function WebApp() {
  return <AppProvider><Shell /></AppProvider>;
}
