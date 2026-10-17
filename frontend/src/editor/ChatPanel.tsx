import { useCallback, useEffect, useRef, useState } from "react";
import { IS_WEB, api, mediaUrl, type AssistantInfo, type ChatMsg, type ChatStatus, type ChatTask } from "../lib/api";
import { useApp } from "../lib/store";
import { Button, Icon, I } from "../ds";
import { uid } from "../lib/format";
import { layout, newText, upgradeProject } from "./model";
import { useAI } from "./useAI";
import MediaPicker from "./MediaPicker";
import AdvisorDialog from "./AdvisorDialog";
import type { Asset, Project, TextOverlay } from "../lib/types";

interface Bubble { id: string; role: "user" | "assistant"; text: string; images?: string[]; notes?: string[]; error?: boolean; result?: "changed" | "same" | "later"; focus?: number | null; undone?: boolean }

/** Shows what the AI is doing right now, with a running clock, so the person always sees that something is happening. */
function Working({ label, pics }: { label: string; pics: boolean }) {
  const [s, setS] = useState(0);
  useEffect(() => { const t = setInterval(() => setS((x) => x + 1), 1000); return () => clearInterval(t); }, []);
  const steps = label ? [label] : ["Sending your message…", ...(pics ? ["Looking at your pictures…"] : []), "The AI is working out the edits…", "Still working — slow computers and free AIs can take up to a minute…"];
  const at = label ? 0 : Math.min(steps.length - 1, s < 2 ? 0 : s < 5 && pics ? 1 : s < 40 ? steps.length - 2 : steps.length - 1);
  return (
    <div className="bubble bubble--assistant" role="status"><p><span className="spinner" aria-hidden /> {steps[at]} <span className="text-xs mono">{s}s</span></p></div>
  );
}

const IDEAS = ["Draw a circle on something, then: “remove this”", "Put a cap on the person’s head", "Make it vertical for a phone", "Add a fade between all clips", "Make it look cinematic", "Add the title “My Trip” at the start", "Slow everything down a little", "Remove the green screen from the top layer", "Put the logo in the top-right corner", "Make the title fly from left to right", "Add a second video layer behind the main one", "Add a whoosh at 2 seconds", "Put the second layer in a heart shape", "Add a light leak and the Blockbuster look", "Add soft rain in the background"];

/** The "Setup" mini form: pick an AI provider, paste a key if it needs one. */
function Setup({ status, onReady }: { status: ChatStatus | null; onReady: () => void }) {
  const [info, setInfo] = useState<AssistantInfo | null>(null);
  const [providerState, setProvider] = useState(IS_WEB ? "groq" : "ollama");
  const [model, setModel] = useState("");
  const [key, setKey] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [adv, setAdv] = useState(() => { if (IS_WEB) return false; try { return sessionStorage.getItem("vk_adv_seen") !== "1"; } catch { return true; } });
  useEffect(() => { if (adv) { try { sessionStorage.setItem("vk_adv_seen", "1"); } catch { /* ignore */ } } }, [adv]);
  useEffect(() => {
    api.llmInfo().then(setInfo).catch(() => {});
    api.llmSettings().then((s) => { setProvider(s.provider || (IS_WEB ? "groq" : "ollama")); setModel(s.providers?.[s.provider]?.model ?? ""); }).catch(() => {});
  }, []);
  const preset = info?.providers[providerState];
  const provider = providerState;
  const save = async (force?: string) => {
    const provider = force ?? providerState;
    setBusy(true); setMsg("");
    try {
      const patch: Record<string, string> = { model: (force ? "" : model) || info?.providers[provider]?.model || "" };
      if (key) patch.api_key = key;
      await api.saveLlm({ provider, providers: { [provider]: patch } });
      if (provider === "ollama" || provider === "lmstudio") {  // use a model that is really installed
        const found = (await api.llmModels().catch(() => ({ models: [] as string[] }))).models;
        if (found.length && !found.includes(patch.model)) { await api.saveLlm({ provider, providers: { [provider]: { model: found[0] } } }); setModel(found[0]); }
        else if (!found.length) throw new Error(provider === "ollama" ? "Ollama is not running or has no model yet. Install Ollama, run “ollama pull llama3.2”, or choose the free online AI above." : "No model is loaded in LM Studio yet.");
      }
      const t = await api.llmTest();
      if (t && (t as { ok?: boolean }).ok === false) throw new Error("The AI did not answer.");
      onReady();
    } catch (e) { setMsg(e instanceof Error ? e.message : "That did not work."); } finally { setBusy(false); }
  };
  return (
    <div className="chat-setup stack gap">
      {adv && <AdvisorDialog load={api.advice} onClose={() => setAdv(false)} onPick={(id, m) => { setAdv(false); setProvider(id); setModel(m); setKey(""); setMsg(""); if (id === "pollinations") setTimeout(() => void save("pollinations"), 0); }} />}
      <b>Connect an AI helper</b>
      {!IS_WEB && <Button variant="secondary" onClick={() => setAdv(true)}>Which AI is best for my PC?</Button>}
      <Button variant="secondary" onClick={() => { setProvider("pollinations"); setModel(""); setKey(""); setTimeout(() => void save("pollinations"), 0); }}>Use the free online AI (easiest)</Button>
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
      <Button busy={busy} onClick={() => save()}>Save and test</Button>
    </div>
  );
}

export default function ChatPanel({ project, commit, asset, onOpenAsset, onUndo, onSeek }: {
  project: Project; commit: (fn: (p: Project) => Project, key?: string) => void; asset: (id: string) => Asset | undefined; onOpenAsset: (a: Asset) => void; onUndo: () => void; onSeek: (t: number) => void;
}) {
  const { refreshAssets, toast, assets } = useApp();
  const ai = useAI();
  const [status, setStatus] = useState<ChatStatus | null>(null);
  const storeKey = `vk_chat_${project.id}`;
  const [bubbles, setBubbles] = useState<Bubble[]>(() => { try { return JSON.parse(localStorage.getItem(storeKey) ?? "[]") as Bubble[]; } catch { return []; } });
  useEffect(() => { try { localStorage.setItem(storeKey, JSON.stringify(bubbles.slice(-60))); } catch { /* private mode */ } }, [bubbles, storeKey]);
  const [text, setText] = useState("");
  const [pics, setPics] = useState<Asset[]>([]);
  const [busy, setBusy] = useState("");
  const [waiting, setWaiting] = useState<{ label: string; pics: boolean } | null>(null);
  const [setup, setSetup] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  const file = useRef<HTMLInputElement>(null);
  const projectRef = useRef(project);
  projectRef.current = project;

  const check = useCallback(() => api.chatStatus().then((s) => { setStatus(s); setSetup(IS_WEB ? false : !s.ready); }).catch(() => setStatus({ ready: false, why: "offline" })), []);
  useEffect(() => { const on = () => { void check(); }; window.addEventListener("vk-llm", on); return () => window.removeEventListener("vk-llm", on); }, [check]);
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
      const lim = await api.limits().catch(() => null);
      const long = Math.min(lim?.profile.max_side ?? 512, 640), w = project.canvas.width >= project.canvas.height;
      const ratio = project.canvas.width / project.canvas.height;
      const short = Math.max(256, Math.round((long / Math.max(ratio, 1 / ratio)) / 32) * 32);
      const body = { mode: t.use_reference && refId ? "i2v" as const : "t2v" as const, prompt: t.prompt ?? "", negative_prompt: "", width: w ? long : short, height: w ? short : long, frames: 49, seed: -1, unlock_limits: false, ...(t.narration || (t.ambience && t.ambience !== "none") || t.music ? { sound: { narration: t.narration ?? "", voice: "", rate: 0, ambience: t.ambience ?? "auto", music: !!t.music, level: 0.5, persona: t.persona ?? "auto" } } : {}), ...(t.use_reference && refId ? { image_asset_id: refId } : {}) };
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
    if (t.name === "ai_edit") {
      const clip = clips[0];
      const a = clip && asset(clip.asset_id);
      if (!clip || !a) throw new Error("I could not find the clip to edit.");
      if (a.kind === "image") {
        const r = await ai.wait(await api.inpaint({ asset_id: a.id, prompt: t.prompt ?? "", mode: "patch", part: t.part ?? "", shapes: t.shapes ?? [] }));
        await refreshAssets();
        const made = r.asset_id as string | undefined;
        if (!made) throw new Error("The edited picture was not created.");
        commit((p) => ({ ...p, clips: p.clips.map((c) => c.id === clip.id ? { ...c, asset_id: made } : c), drawings: p.drawings.filter((d) => !(t.drawing_ids ?? []).includes(d.id)) }));
        return "Done. The marked place on the picture was repainted with AI. Use Undo if you do not like it.";
      }
      const span = (clip.trim_out || a.duration) - clip.trim_in;
      const len = Math.min(span, 8);
      const job = await api.inpaint({ asset_id: a.id, trim_in: clip.trim_in, trim_out: clip.trim_in + len, prompt: t.prompt ?? "", mode: t.mode ?? "patch", part: t.part ?? "", shapes: t.shapes ?? [] });
      const r = await ai.wait(job);
      await refreshAssets();
      const made = r.asset_id as string | undefined;
      if (!made) throw new Error("The edited video was not created.");
      const cut = span > len + 0.2;
      commit((p) => ({
        ...p,
        clips: p.clips.flatMap((c) => c.id !== clip.id ? [c] : [{ ...c, asset_id: made, trim_in: 0, trim_out: 0, transition: cut ? { type: "none", duration: c.transition.duration } : c.transition },
          ...(cut ? [{ ...c, id: uid(), trim_in: c.trim_in + len, effects: [...c.effects] }] : [])]),
        drawings: p.drawings.filter((d) => !(t.drawing_ids ?? []).includes(d.id)),
      }));
      return `Done. The marked place was repainted with AI${cut ? ` for the first ${len.toFixed(0)} seconds of the clip (the rest is a separate clip)` : ""}. Use Undo if you do not like it.`;
    }
    if (t.name === "soundtrack") {
      let n = 0;
      for (const clip of clips) {
        const a = asset(clip.asset_id);
        if (!a || a.kind !== "video") continue;
        const r = await ai.wait(await api.soundtrack({ asset_id: a.id, prompt: a.name, narration: t.narration ?? "", ambience: t.ambience ?? "auto", music: !!t.music, level: 0.5, persona: t.persona }));
        await refreshAssets();
        const made = r.asset_id as string | undefined;
        if (made) { commit((p) => ({ ...p, clips: p.clips.map((c) => c.id === clip.id ? { ...c, asset_id: made } : c) })); n++; }
        const w = r.warnings as string[] | undefined; if (w?.length) toast(w[0], true);
      }
      return n ? `Done. Sound and voice were added to ${n} clip${n > 1 ? "s" : ""}. Use Undo if you do not like it.` : "I could only add sound to video clips.";
    }
    if (t.name === "voiceover") { const voice = (await api.voices().catch(() => ({ voices: [] as string[] }))).voices[0] ?? "";
      const r = await ai.speak(t.text ?? "", voice, 1, t.persona); await refreshAssets(); return r.asset_id ? "The voice-over is in your Library — drag it to the sound track." : "Voice-over created."; }
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
    setText(""); setPics([]); setBusy("Thinking…"); setWaiting({ label: "", pics: sentPics.length > 0 });
    try {
      const r = await api.chat(history, projectRef.current);
      if (r.new_assets?.length) await refreshAssets();
      setWaiting({ label: "Putting the edits on your video…", pics: false });
      if (r.changed) commit(() => upgradeProject({ ...r.project, id: projectRef.current.id, name: projectRef.current.name }));
      const skipped = r.skipped.map((s) => "Not done — " + s);
      const result: Bubble["result"] = r.changed ? "changed" : r.tasks.length ? "later" : "same";
      const fallback = r.changed ? "Done." : r.understood === false ? "I could not read the AI’s answer. Please try again, or pick a smarter AI in “AI settings”." : "I did not change anything.";
      add({ role: "assistant", text: r.reply || fallback, notes: [...r.applied, ...skipped], result, focus: r.focus ?? null });
      if (r.changed && r.focus != null) onSeek(r.focus);
      for (const t of r.tasks) {
        setBusy("x"); setWaiting({ label: t.name === "generate_video" ? "Making your AI video… this can take a few minutes" : t.name === "ai_edit" ? "Repainting your video with AI… about a minute per second of video on a graphics card" : "Working on it…", pics: false });
        try { add({ role: "assistant", text: await runTask(t, sentPics[0]?.id) }); }
        catch (e) { add({ role: "assistant", text: e instanceof Error ? e.message : "That did not work.", error: true }); }
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "That did not work.";
      add({ role: "assistant", text: msg, error: true });
      if (/model|ollama|key|server|connect|not running|choose an ai/i.test(msg)) setSetup(true);
      check();
    } finally { setBusy(""); setWaiting(null); }
  };

  const [logOpen, setLogOpen] = useState(false);
  const [picker, setPicker] = useState(false);
  const showLog = logOpen;
  useEffect(() => { if (busy || setup) setLogOpen(true); }, [busy, setup]);

  const upload = async (files: FileList) => { await attach(files); };

  return (
    <section className="fx-prompt" aria-label="Chat with the AI editor">
      {showLog && (
        <div className="fx-log" role="region" aria-label="Conversation">
          <header className="chat-head row between center-v">
            <b><Icon d={I.sparkle} /> Chat editor</b>
            <span className="row gap">
              <Button variant="ghost" small icon={I.trash} label="Delete this chat" disabled={bubbles.length === 0} onClick={() => { if (confirm("Delete this whole chat? Your video is not changed.")) { setBubbles([]); try { localStorage.removeItem(storeKey); } catch { /* ignore */ } } }} />
              <Button variant="ghost" small onClick={() => setSetup((s) => !s)}>AI settings</Button>
              <Button variant="ghost" small icon={I.x} label="Hide the conversation" onClick={() => { setLogOpen(false); setSetup(false); }} />
            </span>
          </header>
          {setup ? <Setup status={status} onReady={() => { setSetup(false); check(); }} /> : (
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
                {b.error && <Button small variant="secondary" onClick={() => setSetup(true)}>Fix AI settings</Button>}
                {b.result === "changed" && <p className="bubble-done"><Icon d={I.check} size={14} /> Done — your video was changed{b.focus != null ? ` (shown at ${b.focus.toFixed(1)} s)` : ""}.</p>}
                {b.result === "same" && !b.error && <p className="bubble-same">Nothing on the video changed. Try describing it in other words, or attach a picture and say where it should go.</p>}
                {b.notes && b.notes.length > 0 && <ul className="bubble-notes">{b.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
                {b.result === "changed" && <div className="row gap">{!b.undone && <Button small variant="secondary" icon={I.undo} onClick={() => { onUndo(); setBubbles((x) => x.map((y) => y.id === b.id ? { ...y, undone: true } : y)); }}>Undo this change</Button>}{b.undone && <span className="text-xs">Undone.</span>}{b.focus != null && <Button small variant="ghost" onClick={() => onSeek(b.focus as number)}>Show me</Button>}</div>}
              </div>
            ))}
              {busy && waiting && <Working label={waiting.label} pics={waiting.pics} />}
              <div ref={end} />
            </div>
          )}
        </div>
      )}
      {picker && <MediaPicker assets={assets} mode="reference" projectName={project.name} onClose={() => setPicker(false)} onUpload={upload} onPick={(a) => { setPics((x) => x.some((y) => y.id === a.id) ? x : [...x, a].slice(0, 4)); setPicker(false); }} />}
      <form className="fx-bar" onSubmit={(e) => { e.preventDefault(); send(); }}>
        {pics.length > 0 && (
          <div className="row gap chat-pics">
            {pics.map((p) => <span key={p.id} className="chat-pic"><img alt={p.name} src={mediaUrl(p.id, "thumb")} /><button type="button" aria-label={`Remove ${p.name}`} onClick={() => setPics((x) => x.filter((y) => y.id !== p.id))}>×</button></span>)}
          </div>
        )}
        <textarea className="fx-text" rows={IS_WEB ? 1 : 2} aria-label="Message" placeholder="Describe how to edit this video…" value={text} maxLength={4000}
          onFocus={() => setLogOpen(true)} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} />
        <div className="fx-row">
          <button type="button" className="fx-round" aria-label="Add reference pictures" title="Add reference pictures" disabled={pics.length >= 4} onClick={() => setPicker((v) => !v)}>+</button>
          {bubbles.length > 0 && !logOpen && <button type="button" className="gchip" onClick={() => setLogOpen(true)}><span>Show conversation</span><small>{bubbles.length} messages</small></button>}
          <span className="grow" />
          <button type="button" className="gchip" onClick={() => { setLogOpen(true); setSetup(true); }} title="Choose which AI edits your video"><span><Icon d={I.sparkle} size={14} /> {status?.ready ? (status.name || status.provider || "AI helper") : "Set up AI"}</span><small>{status?.ready ? (status.model || "ready") : "needed to chat"}</small></button>
          <button type="submit" className="fx-send" aria-label="Send" disabled={(!text.trim() && !pics.length) || !!busy}>{busy ? <span className="spinner" /> : "→"}</button>
        </div>
      </form>
    </section>
  );
}
