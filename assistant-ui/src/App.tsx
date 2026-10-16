import { useCallback, useEffect, useState } from "react";
import { api } from "./lib/api";
import type { Conversation } from "./lib/types";
import Chat from "./views/Chat";
import Create from "./views/Create";
import Files from "./views/Files";
import Settings from "./views/Settings";
import { Analyze, Compare, ImageGen, Resume } from "./views/Tools";
import { Button, errText } from "./ui";

type View = "chat" | "create" | "resume" | "compare" | "analyze" | "image" | "files" | "settings";
const NAV: { id: View; label: string; icon: string }[] = [
  { id: "chat", label: "Chat", icon: "💬" }, { id: "create", label: "Create files", icon: "📄" }, { id: "resume", label: "Resume ATS", icon: "✅" },
  { id: "compare", label: "Compare files", icon: "⇄" }, { id: "analyze", label: "Analyse file", icon: "📊" }, { id: "image", label: "Images", icon: "🖼" },
  { id: "files", label: "Files", icon: "🗂" }, { id: "settings", label: "Settings", icon: "⚙" },
];

export default function App() {
  const [view, setView] = useState<View>("chat");
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
      <aside className="side" aria-label="Main">
        <div className="brand"><span className="logo" aria-hidden="true">✦</span><strong>AI Assistant</strong></div>
        <Button onClick={() => { setCurrent(null); setView("chat"); }}>＋ New chat</Button>
        <nav className="nav" aria-label="Tools">
          {NAV.map((n) => (<button key={n.id} className="nav-item" aria-current={view === n.id ? "page" : undefined} onClick={() => setView(n.id)}><span aria-hidden="true">{n.icon}</span>{n.label}</button>))}
        </nav>
        <div className="side-title">Recent chats</div>
        <div className="convs">
          {convs.length === 0 && <p className="hint" style={{ padding: "0 12px" }}>No chats yet.</p>}
          {convs.map((c) => (
            <div key={c.id} className="conv" data-active={current === c.id && view === "chat"}>
              <button className="conv-main truncate" onClick={() => { setCurrent(c.id); setView("chat"); }} title={c.title}>{c.title}</button>
              {confirm === c.id ? (<><button className="btn btn--sm btn--danger" onClick={() => void remove(c.id)}>Delete</button><button className="btn btn--sm btn--ghost" onClick={() => setConfirm(null)}>Keep</button></>)
                : <button className="conv-del" aria-label={`Delete chat ${c.title}`} onClick={() => setConfirm(c.id)}>×</button>}
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
