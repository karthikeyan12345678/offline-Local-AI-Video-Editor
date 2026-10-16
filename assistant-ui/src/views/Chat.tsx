import { useCallback, useEffect, useRef, useState } from "react";
import { api, streamChat, ApiError } from "../lib/api";
import type { Card, FileRef, Message } from "../lib/types";
import { RenderCard } from "../cards";
import { Banner, Button, Markdown, Spinner, errText } from "../ui";

const STARTERS: { label: string; text: string }[] = [
  { label: "Create a PDF", text: "/pdf " }, { label: "Make slides", text: "/ppt " }, { label: "Write a Word doc", text: "/doc " },
  { label: "Make a CSV", text: "/csv " }, { label: "Make an Excel file", text: "/xlsx " }, { label: "Generate an image", text: "/image " },
  { label: "Suggest a design", text: "/design " },
];

export default function Chat({ conversationId, onConversation, onTitle, goSettings }: { conversationId: string | null; onConversation: (id: string) => void; onTitle: () => void; goSettings: () => void }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [text, setText] = useState("");
  const [files, setFiles] = useState<FileRef[]>([]);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [live, setLive] = useState("");
  const [liveCards, setLiveCards] = useState<Card[]>([]);
  const [error, setError] = useState("");
  const [uploading, setUploading] = useState(false);
  const abort = useRef<AbortController | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const area = useRef<HTMLTextAreaElement>(null);
  const skipLoad = useRef<string | null>(null);

  useEffect(() => {
    if (!conversationId) { setMessages([]); return; }
    if (skipLoad.current === conversationId) { skipLoad.current = null; return; }
    let live = true;
    api.conversation(conversationId).then((c) => live && setMessages(c.messages)).catch((e) => live && setError(errText(e)));
    return () => { live = false; };
  }, [conversationId]);

  useEffect(() => { bottom.current?.scrollIntoView({ block: "end" }); }, [messages, live, liveCards, status]);

  const attach = useCallback(async (list: FileList | null) => {
    if (!list) return;
    setUploading(true); setError("");
    try {
      const added: FileRef[] = [];
      for (const f of Array.from(list)) added.push(await api.upload(f));
      setFiles((cur) => [...cur, ...added].slice(0, 8));
    } catch (e) { setError(errText(e)); } finally { setUploading(false); if (fileInput.current) fileInput.current.value = ""; }
  }, []);

  const send = useCallback(async (override?: string) => {
    const body = (override ?? text).trim();
    if ((!body && files.length === 0) || busy) return;
    setError(""); setBusy(true); setLive(""); setLiveCards([]); setStatus("");
    let cid = conversationId;
    try {
      if (!cid) { cid = (await api.newConversation()).id; skipLoad.current = cid; onConversation(cid); }
    } catch (e) { setError(errText(e)); setBusy(false); return; }
    const sentFiles = files;
    setMessages((m) => [...m, { id: "tmp-" + Date.now(), role: "user", content: body, cards: [], files: sentFiles, created: Date.now() / 1000 }]);
    setText(""); setFiles([]);
    const ctl = new AbortController();
    abort.current = ctl;
    let acc = "";
    const cards: Card[] = [];
    let failed = "";
    try {
      await streamChat({ conversation_id: cid, text: body, file_ids: sentFiles.map((f) => f.id), options: {} }, (ev) => {
        if (ev.event === "delta") { acc += ev.data.text; setLive(acc); setStatus(""); }
        else if (ev.event === "status") setStatus(ev.data.text);
        else if (ev.event === "card") { cards.push(ev.data); setLiveCards([...cards]); }
        else if (ev.event === "error") failed = ev.data.message;
        else if (ev.event === "start") onTitle();
      }, ctl.signal);
    } catch (e) { failed = e instanceof ApiError ? e.message : errText(e); }
    abort.current = null;
    // Reload from the server so what is shown is exactly what was saved.
    try { const c = await api.conversation(cid); setMessages(c.messages); } catch { if (acc) setMessages((m) => [...m, { id: "a-" + Date.now(), role: "assistant", content: acc, cards, files: [], created: Date.now() / 1000 }]); }
    setLive(""); setLiveCards([]); setStatus(""); setBusy(false); onTitle();
    if (failed) setError(failed);
    area.current?.focus();
  }, [text, files, busy, conversationId, onConversation, onTitle]);

  const stop = () => abort.current?.abort();
  const needsSetup = /model|Settings|Cannot reach|API key/i.test(error);

  return (
    <div className="chat">
      <div className="messages" role="log" aria-live="polite" aria-label="Conversation">
        {messages.length === 0 && !busy && (
          <div className="welcome">
            <h1>What would you like to work on?</h1>
            <p className="muted">Chat, or create PDF, PowerPoint, Word, CSV and Excel files. Attach a resume to check its ATS score, attach two files to compare them, or attach data to analyse it.</p>
            <div className="chips" style={{ justifyContent: "center", marginTop: 16 }}>
              {STARTERS.map((s) => <button key={s.label} className="chip" onClick={() => { setText(s.text); area.current?.focus(); }}>{s.label}</button>)}
            </div>
          </div>
        )}
        {messages.map((m) => (
          <div key={m.id} className={`msg msg--${m.role}`}>
            {m.files.length > 0 && <div className="chips">{m.files.map((f) => <span key={f.id} className="chip">📎 {f.name}</span>)}</div>}
            {m.role === "user" ? <p className="user-text">{m.content}</p> : m.content.startsWith("⚠") ? null : <Markdown text={m.content} />}
            {m.cards.map((c, i) => <RenderCard key={i} card={c} />)}
          </div>
        ))}
        {busy && (
          <div className="msg msg--assistant">
            {live ? <Markdown text={live} /> : <p className="muted row"><Spinner /> {status || "Thinking…"}</p>}
            {status && live && <p className="hint row"><Spinner /> {status}</p>}
            {liveCards.map((c, i) => <RenderCard key={i} card={c} />)}
          </div>
        )}
        <div ref={bottom} />
      </div>
      <div className="composer-wrap">
        {error && <Banner kind="error" onClose={() => setError("")}>{error} {needsSetup && <Button variant="secondary" size="sm" onClick={goSettings}>Open settings</Button>}</Banner>}
        {files.length > 0 && <div className="chips" style={{ marginBottom: 8 }}>{files.map((f) => (
          <span key={f.id} className="chip">📎 <span className="truncate" style={{ maxWidth: 180 }}>{f.name}</span>
            <button className="chip-x" aria-label={`Remove ${f.name}`} onClick={() => setFiles(files.filter((x) => x.id !== f.id))}>×</button></span>))}</div>}
        <div className="composer">
          <input ref={fileInput} type="file" hidden multiple onChange={(e) => void attach(e.target.files)} />
          <Button variant="ghost" size="icon" aria-label="Attach files" busy={uploading} onClick={() => fileInput.current?.click()}>＋</Button>
          <textarea ref={area} className="composer-input" rows={1} value={text} placeholder="Message, or type / for a command like /pdf or /ppt"
            aria-label="Message" onChange={(e) => { setText(e.target.value); e.target.style.height = "auto"; e.target.style.height = Math.min(200, e.target.scrollHeight) + "px"; }}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send(); } }} />
          {busy ? <Button variant="secondary" onClick={stop}>Stop</Button> : <Button onClick={() => void send()} disabled={!text.trim() && files.length === 0}>Send</Button>}
        </div>
        <p className="hint" style={{ textAlign: "center", marginTop: 8 }}>AI can make mistakes. Check important facts before you share a file.</p>
      </div>
    </div>
  );
}
