import { useCallback, useEffect, useState } from "react";
import { api } from "./lib/api";
import type { Conversation } from "./lib/types";
import Chat from "./views/Chat";
import Create from "./views/Create";
import Files from "./views/Files";
import Settings from "./views/Settings";
import { Analyze, Compare, ImageGen, Resume } from "./views/Tools";
import { Ico, errText } from "./ui";
import Tour, { type TourStep } from "./Tour";

type View = "chat" | "create" | "resume" | "compare" | "analyze" | "image" | "files" | "settings";
const NAV: { id: View; label: string; icon: string }[] = [
  { id: "create", label: "Create files", icon: "doc" }, { id: "resume", label: "Resume ATS", icon: "check" },
  { id: "compare", label: "Compare files", icon: "compare" }, { id: "analyze", label: "Analyse file", icon: "chart" }, { id: "image", label: "Images", icon: "image" },
  { id: "files", label: "Files", icon: "folder" }, { id: "settings", label: "Settings", icon: "gear" },
];

const doneTour = () => { try { return localStorage.getItem("aia_tour_done") === "1"; } catch { return true; } };

export default function App() {
  const [view, setView] = useState<View>("chat");
  const [tour, setTour] = useState(() => !doneTour());
  const finishTour = () => { setTour(false); setView("chat"); try { localStorage.setItem("aia_tour_done", "1"); } catch { /* ignore */ } };
  const STEPS: TourStep[] = [
    { title: "Welcome to AI Assistant", body: "This takes 30 seconds. It shows where everything is. You can skip it now and start it again later from Settings." },
    { target: "chat", title: "Chat", body: "Ask anything. Type / for a command: /pdf, /ppt, /doc, /xlsx, /csv make a file, /image draws a picture.", go: () => setView("chat") },
    { target: "create", title: "Create files", body: "Describe a PDF, slides, Word, Excel or CSV file and download it, with a design you can pick.", go: () => setView("create") },
    { target: "resume", title: "Resume ATS", body: "Add your resume (PDF, Word, CSV) and a job description. It scores the match and can rewrite the resume for that job.", go: () => setView("resume") },
    { target: "image", title: "Images", body: "Describe a picture. Your short idea is first rewritten into a detailed prompt, so the picture has more detail. Better engines (FLUX, DALL·E) are in Settings.", go: () => setView("image") },
    { target: "settings", title: "Settings and keys", body: "Pick the AI that answers: one on this PC, a free online key (Groq, Gemini) or your paid Claude key. Press “Help me choose” to see the best one for your computer. Keys stay on this PC.", go: () => setView("settings") },
    { title: "You are ready", body: "Start by typing a message in Chat. Settings has a “Take the tour” button if you want this again." },
  ];
  const [convs, setConvs] = useState<Conversation[]>([]);
  const [current, setCurrent] = useState<string | null>(null);
  const [err, setErr] = useState("");
  const [confirm, setConfirm] = useState<string | null>(null);

  const refresh = useCallback(() => { api.conversations().then(setConvs).catch((e) => setErr(errText(e))); }, []);
  useEffect(refresh, [refresh]);

  const remove = async (id: string) => {
    try { await api.deleteConversation(id); if (current === id) setCurrent(null); setConfirm(null); refresh(); } catch (e) { setErr(errText(e)); }
  };

  return (
    <div className="shell">
      {tour && <Tour steps={STEPS} onDone={finishTour} />}
      <aside className="side" aria-label="Main">
        <div className="brand"><span className="logo" aria-hidden="true"><Ico name="spark" size={20} /></span><strong>AI Assistant</strong></div>
        <button type="button" className="newchat" onClick={() => { setCurrent(null); setView("chat"); }}><Ico name="plus" size={18} />New chat</button>
        <nav className="nav" aria-label="Tools">
          <button className="nav-item" data-tour="chat" aria-current={view === "chat" ? "page" : undefined} onClick={() => setView("chat")}><Ico name="chat" />Chat</button>
          {NAV.map((n) => (<button key={n.id} className="nav-item" data-tour={n.id} aria-current={view === n.id ? "page" : undefined} onClick={() => setView(n.id)}><Ico name={n.icon} />{n.label}</button>))}
        </nav>
        <div className="side-title">Recents</div>
        <div className="convs">
          {convs.length === 0 && <p className="hint" style={{ padding: "0 12px" }}>No chats yet.</p>}
          {convs.map((c) => (
            <div key={c.id} className="conv" data-active={current === c.id && view === "chat"}>
              <button className="conv-main truncate" onClick={() => { setCurrent(c.id); setView("chat"); }} title={c.title}>{c.title}</button>
              {confirm === c.id ? (<><button className="btn btn--sm btn--danger" onClick={() => void remove(c.id)}>Delete</button><button className="btn btn--sm btn--ghost" onClick={() => setConfirm(null)}>Keep</button></>)
                : <button className="conv-del" aria-label={`Delete chat ${c.title}`} onClick={() => setConfirm(c.id)}><Ico name="x" size={14} /></button>}
            </div>))}
        </div>
        {err && <p className="hint" role="alert">{err}</p>}
      </aside>
      <main className="main">
        <div hidden={view !== "chat"} className="fill">
          <Chat conversationId={current} onConversation={(id) => setCurrent(id)} onTitle={refresh} goSettings={() => setView("settings")} />
        </div>
        {view === "create" && <Create />}
        {view === "resume" && <Resume />}
        {view === "compare" && <Compare />}
        {view === "analyze" && <Analyze />}
        {view === "image" && <ImageGen />}
        {view === "files" && <Files />}
        {view === "settings" && <Settings />}
      </main>
    </div>
  );
}
