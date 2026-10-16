import { useCallback, useEffect, useRef, useState } from "react";
import { api, mediaUrl, type AssistantInfo, type ChatMsg, type ChatStatus, type ChatTask } from "../lib/api";
import { useApp } from "../lib/store";
import { Button, Icon, I } from "../ds";
import { uid } from "../lib/format";
import { layout, newText, upgradeProject } from "./model";
import { useAI } from "./useAI";
import type { Asset, Project, TextOverlay } from "../lib/types";

interface Bubble { id: string; role: "user" | "assistant"; text: string; images?: string[]; notes?: string[]; error?: boolean }

const IDEAS = ["Make it vertical for a phone", "Add a fade between all clips", "Make it look cinematic", "Add the title “My Trip” at the start", "Slow everything down a little"];

/** The "Setup" mini form: pick an AI provider, paste a key if it needs one. */
function Setup({ status, onReady }: { status: ChatStatus | null; onReady: () => void }) {
  const [info, setInfo] = useState<AssistantInfo | null>(null);
  const [provider, setProvider] = useState("ollama");
  const [model, setModel] = useState("");
  const [key, setKey] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api.llmInfo().then(setInfo).catch(() => {});
    api.llmSettings().then((s) => { setProvider(s.provider || "ollama"); setModel(s.providers?.[s.provider]?.model ?? ""); }).catch(() => {});
  }, []);
  const preset = info?.providers[provider];
  const save = async () => {
    setBusy(true); setMsg("");
    try {
      const patch: Record<string, string> = { model: model || preset?.model || "" };
      if (key) patch.api_key = key;
      await api.saveLlm({ provider, providers: { [provider]: patch } });
      const t = await api.llmTest();
      if (t && (t as { ok?: boolean }).ok === false) throw new Error("The AI did not answer.");
      onReady();
    } catch (e) { setMsg(e instanceof Error ? e.message : "That did not work."); } finally { setBusy(false); }
  };
  return (
    <div className="chat-setup stack gap">
      <b>Connect an AI helper</b>
      <p className="text-sm">{status?.why === "key" ? "This AI needs a key (a password for the service)." : "The chat needs an AI brain. Pick one — free choices are marked."}</p>
      <label className="field"><span>Which AI?</span>
        <select className="select" value={provider} onChange={(e) => { setProvider(e.target.value); setModel(""); setMsg(""); }}>
          {info && Object.entries(info.providers).map(([id, p]) => <option key={id} value={id}>{p.name}</option>)}
        </select></label>
      {preset && <p className="text-xs">{preset.help}</p>}
      {preset?.needs_key && <label className="field"><span>Key</span><input className="input" type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} placeholder="paste your key here" /></label>}
      <label className="field"><span>Model name (optional)</span><input className="input" value={model} onChange={(e) => setModel(e.target.value)} placeholder={preset?.model || ""} /></label>
      <p className="text-xs">To understand your reference pictures, choose a model that can see images (for example Gemini, GPT-4o or Claude). Others still work with words only.</p>
      {msg && <p className="error text-sm" role="alert">{msg}</p>}
      <Button busy={busy} onClick={save}>Save and test</Button>
    </div>
  );
}

export default function ChatPanel({ project, commit, asset, onClose, onOpenAsset }: {
  project: Project; commit: (fn: (p: Project) => Project, key?: string) => void; asset: (id: string) => Asset | undefined; onClose: () => void; onOpenAsset: (a: Asset) => void;
}) {
  const { refreshAssets, toast } = useApp();
  const ai = useAI();
  const [status, setStatus] = useState<ChatStatus | null>(null);
  const [bubbles, setBubbles] = useState<Bubble[]>([]);
  const [text, setText] = useState("");
  const [pics, setPics] = useState<Asset[]>([]);
  const [busy, setBusy] = useState("");
  const [setup, setSetup] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  const file = useRef<HTMLInputElement>(null);
  const projectRef = useRef(project);
  projectRef.current = project;

  const check = useCallback(() => api.chatStatus().then((s) => { setStatus(s); setSetup(!s.ready); }).catch(() => setStatus({ ready: false, why: "offline" })), []);
  useEffect(() => { check(); }, [check]);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [bubbles, busy]);

  const add = (b: Omit<Bubble, "id">) => setBubbles((x) => [...x, { id: uid(), ...b }]);

  const attach = async (files: FileList | null) => {
    if (!files) return;
    for (const f of Array.from(files).slice(0, 4 - pics.length)) {
      if (!/\.(png|jpe?g|webp)$/i.test(f.name)) { toast("Please choose a PNG or JPG picture.", true); continue; }
      try { const a = await api.upload(f); setPics((p) => [...p, a].slice(0, 4)); } catch (e) { toast(e instanceof Error ? e.message : "Upload failed.", true); }
    }
    refreshAssets();
    if (file.current) file.current.value = "";
  };

  /** Long jobs the AI asked for (captions, tracking, a new AI video…). Each reports back into the chat. */
  const runTask = async (t: ChatTask, refId: string | undefined): Promise<string> => {
    const cur = projectRef.current;
    const clips = cur.clips.filter((c) => !t.clips || t.clips.includes(c.id));
    if (t.name === "generate_video") {
      const long = 512, w = project.canvas.width >= project.canvas.height;
      const ratio = project.canvas.width / project.canvas.height;
      const short = Math.max(256, Math.round((long / Math.max(ratio, 1 / ratio)) / 32) * 32);
      const body = { mode: t.use_reference && refId ? "i2v" as const : "t2v" as const, prompt: t.prompt ?? "", negative_prompt: "", width: w ? long : short, height: w ? short : long, frames: 49, seed: -1, unlock_limits: false, ...(t.use_reference && refId ? { image_asset_id: refId } : {}) };
      const job = await api.generate(body);
      const r = await ai.wait(job);
      await refreshAssets();
      const made = r.asset_id as string | undefined;
      if (made) {
        const a = (await api.assets()).find((x) => x.id === made);
        if (a) { onOpenAsset(a); return "Your new AI video is ready and was added to the timeline."; }
      }
      return "Your new AI video is ready in the Library.";
    }
    if (t.name === "voiceover") { const voice = (await api.voices().catch(() => ({ voices: [] as string[] }))).voices[0] ?? "";
      const r = await ai.speak(t.text ?? "", voice, 1); await refreshAssets(); return r.asset_id ? "The voice-over is in your Library — drag it to the sound track." : "Voice-over created."; }
    if (t.name === "beat_cut") return "Cutting to the beat needs a music track: add music, select it and use “Cut to the beat” in the Sound tab.";
    let done = 0; const notes: string[] = [];
    for (const clip of clips) {
      const a = asset(clip.asset_id);
      if (!a) continue;
      const req = { asset_id: a.id, trim_in: clip.trim_in, trim_out: clip.trim_out };
      if (t.name === "follow_person") {
        const r = await ai.run("follow", req);
        commit((p) => ({ ...p, clips: p.clips.map((c) => c.id === clip.id ? { ...c, follow: { keys: r.keys, zoom: 1.2 }, fit: "fill" } : c) }));
      } else if (t.name === "auto_enhance") {
        const adj = await api.enhance(req);
        commit((p) => ({ ...p, clips: p.clips.map((c) => c.id === clip.id ? { ...c, adjust: adj } : c) }));
      } else if (t.name === "captions") {
        const r = await ai.run("captions", { ...req, options: { model: "base", language: t.language ?? "" } });
        const segs = r.segments as { start: number; end: number; text: string }[];
        const t0 = layout(projectRef.current, asset).items.find((i) => i.clip.id === clip.id)?.start ?? 0;
        const made = segs.map((sg) => ({ ...newText(Math.max(0, t0 + (sg.start - clip.trim_in) / clip.speed)), text: sg.text.length > 44 ? sg.text.replace(/(.{20,44})\s/, "$1\n") : sg.text, size: 5, y: 0.88, box: true, box_opacity: 0.6, bold: false, font: "poppins", duration: Math.max(0.5, (sg.end - sg.start) / clip.speed), fade_in: 0.1, fade_out: 0.1 } as TextOverlay));
        commit((p) => ({ ...p, texts: [...p.texts, ...made] }));
        notes.push(`${made.length} subtitles`);
      } else if (t.name === "cut_silence" || t.name === "scene_split") {
        const r = await ai.run(t.name === "cut_silence" ? "silence" : "scenes", t.name === "cut_silence" ? { ...req, options: { noise_db: -35, min_silence: 0.6 } } : req);
        let ranges: [number, number][] = [];
        if (t.name === "cut_silence") ranges = (r.keep as [number, number][]) ?? [];
        else {
          const endT = clip.trim_out || a.duration;
          const pts = [clip.trim_in, ...(r.cuts as number[]).filter((c) => c > clip.trim_in + 0.3 && c < endT - 0.3), endT];
          ranges = pts.slice(0, -1).map((v, i) => [v, pts[i + 1]] as [number, number]);
        }
        if (ranges.length > 1 || (ranges.length === 1 && t.name === "cut_silence")) {
          commit((p) => ({ ...p, clips: p.clips.flatMap((c) => c.id !== clip.id ? [c] : ranges.map((rg, i) => ({ ...c, id: i === 0 ? c.id : uid(), trim_in: rg[0], trim_out: rg[1], transition: i === ranges.length - 1 ? c.transition : { type: "none", duration: c.transition.duration } }))) }));
        }
      }
      done++;
    }
    return `Done for ${done} clip${done === 1 ? "" : "s"}${notes.length ? ` (${notes.join(", ")})` : ""}.`;
  };

  const send = async (override?: string) => {
    const words = (override ?? text).trim();
    if ((!words && !pics.length) || busy) return;
    const sentPics = pics;
    const content = words || "Use these pictures as a reference.";
    const history: ChatMsg[] = [...bubbles.filter((b) => !b.error).slice(-8).map((b) => ({ role: b.role, content: b.text } as ChatMsg)), { role: "user", content, image_ids: sentPics.map((p) => p.id) }];
    add({ role: "user", text: content, images: sentPics.map((p) => p.id) });
    setText(""); setPics([]); setBusy("Thinking…");
    try {
      const r = await api.chat(history, projectRef.current);
      if (r.changed) commit(() => upgradeProject({ ...r.project, id: projectRef.current.id, name: projectRef.current.name }));
      add({ role: "assistant", text: r.reply || (r.changed ? "Done." : "OK."), notes: [...r.applied, ...r.skipped.map((s) => "Skipped — " + s)] });
      for (const t of r.tasks) {
        setBusy(t.name === "generate_video" ? "Making your AI video… this can take a few minutes" : "Working on it…");
        try { add({ role: "assistant", text: await runTask(t, sentPics[0]?.id) }); }
        catch (e) { add({ role: "assistant", text: e instanceof Error ? e.message : "That did not work.", error: true }); }
      }
    } catch (e) {
      add({ role: "assistant", text: e instanceof Error ? e.message : "That did not work.", error: true });
      check();
    } finally { setBusy(""); }
  };

  return (
    <aside className="chat" aria-label="Chat with the AI editor">
      <header className="chat-head row between center-v">
        <b><Icon d={I.sparkle} /> Chat editor</b>
        <span className="row gap">
          <Button variant="ghost" small onClick={() => setSetup((s) => !s)}>AI settings</Button>
          <Button variant="ghost" small icon={I.x} label="Close chat" onClick={onClose} />
        </span>
      </header>
      {setup ? <Setup status={status} onReady={() => { setSetup(false); check(); }} /> : (
        <>
          <div className="chat-log" role="log" aria-live="polite">
            {bubbles.length === 0 && (
              <div className="chat-hello stack gap">
                <p>Tell me what you want, and I will edit the video. You can also add reference pictures (PNG or JPG) — I can match their look or turn them into a video.</p>
                <div className="row wrap gap">{IDEAS.map((i) => <button key={i} type="button" className="chip" onClick={() => send(i)}>{i}</button>)}</div>
              </div>
            )}
            {bubbles.map((b) => (
              <div key={b.id} className={`bubble bubble--${b.role}${b.error ? " bubble--error" : ""}`}>
                {b.images && <div className="row gap wrap">{b.images.map((id) => <img key={id} className="bubble-img" alt="Reference" src={mediaUrl(id, "thumb")} />)}</div>}
                <p>{b.text}</p>
                {b.notes && b.notes.length > 0 && <ul className="bubble-notes">{b.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
              </div>
            ))}
            {busy && <div className="bubble bubble--assistant"><p><span className="spinner" aria-hidden /> {busy}</p></div>}
            <div ref={end} />
          </div>
          {bubbles.some((b) => b.notes?.length) && <p className="text-xs chat-undo">Changed something you don’t like? Press Ctrl+Z to undo.</p>}
          {pics.length > 0 && (
            <div className="row gap chat-pics">
              {pics.map((p) => <span key={p.id} className="chat-pic"><img alt={p.name} src={mediaUrl(p.id, "thumb")} /><button type="button" aria-label={`Remove ${p.name}`} onClick={() => setPics((x) => x.filter((y) => y.id !== p.id))}>×</button></span>)}
            </div>
          )}
          <form className="chat-input row gap" onSubmit={(e) => { e.preventDefault(); send(); }}>
            <input ref={file} type="file" accept="image/png,image/jpeg,image/webp" multiple hidden onChange={(e) => attach(e.target.files)} />
            <Button variant="ghost" icon={I.upload} label="Add reference pictures (PNG or JPG)" onClick={() => file.current?.click()} disabled={pics.length >= 4} />
            <textarea className="textarea grow" rows={2} aria-label="Message" placeholder="e.g. make it vertical, add a fade, put “Hello” at the start…" value={text} maxLength={4000}
              onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} />
            <Button type="submit" busy={!!busy} disabled={!text.trim() && !pics.length}>Send</Button>
          </form>
        </>
      )}
    </aside>
  );
}
