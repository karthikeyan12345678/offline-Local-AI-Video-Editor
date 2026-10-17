import { useEffect, useState } from "react";
import { Button, Field, Slider, Tabs, I } from "../ds";
import { IS_WEB, api } from "../lib/api";
import { uid } from "../lib/format";
import type { Asset, AudioClip, Clip, Drawing, Effect, ImageOverlay, Project, TextOverlay } from "../lib/types";
import { animLabel, groupBy, useCatalog } from "./catalog";
import FontPicker from "./FontPicker";
import { CANVAS_PRESETS, TEXT_STYLES, itemPose, itemRest, layout, newAudio, newText, sourceEnd } from "./model";
import { useAI } from "./useAI";
import { ChromaControls, KeyframeControls, LayerPanel } from "./LayerPanel";

export type Selection = { type: "clip" | "text" | "audio" | "draw" | "image" | "layer"; id: string } | null;
type Commit = (fn: (p: Project) => Project, key?: string) => void;

function GroupSelect({ id, label, value, items, onChange }: { id: string; label: string; value: string; items: { id: string; label: string; group?: string }[]; onChange: (v: string) => void }) {
  const groups = groupBy(items);
  return (
    <select id={id} className="select" aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}>
      {groups.length === 1 && !groups[0][0] ? groups[0][1].map((i) => <option key={i.id} value={i.id}>{i.label}</option>)
        : groups.map(([g, list]) => <optgroup key={g} label={g}>{list.map((i) => <option key={i.id} value={i.id}>{i.label}</option>)}</optgroup>)}
    </select>
  );
}

const pct = (v: number) => `${Math.round(v)}`;
const sec = (v: number) => `${v.toFixed(2)} s`;

export default function Inspector({ project, sel, asset, commit, onDelete, time, onSeek = () => {}, onAddBackground = () => {} }: { project: Project; sel: Selection; asset: (id: string) => Asset | undefined; commit: Commit; onDelete: () => void; time: number; onSeek?: (t: number) => void; onAddBackground?: () => void }) {
  if (sel?.type === "clip") { const c = project.clips.find((x) => x.id === sel.id); if (c) return <ClipPanel key={c.id} clip={c} index={project.clips.findIndex((x) => x.id === c.id)} count={project.clips.length} a={asset(c.asset_id)} project={project} asset={asset} commit={commit} onDelete={onDelete} onAddBackground={onAddBackground} />; }
  if (sel?.type === "layer") { const i = project.layers.findIndex((x) => x.id === sel.id); const l = project.layers[i]; if (l) return <LayerPanel key={l.id} layer={l} index={i} a={asset(l.asset_id)} time={time} commit={commit} onDelete={onDelete} onSeek={onSeek} onAddBackground={onAddBackground} />; }
  if (sel?.type === "text") { const t = project.texts.find((x) => x.id === sel.id); if (t) return <TextPanel key={t.id} t={t} commit={commit} onDelete={onDelete} time={time} onSeek={onSeek} />; }
  if (sel?.type === "audio") { const t = project.audio.find((x) => x.id === sel.id); if (t) return <AudioPanel key={t.id} ac={t} a={asset(t.asset_id)} commit={commit} onDelete={onDelete} />; }
  if (sel?.type === "draw") { const d = project.drawings.find((x) => x.id === sel.id); if (d) return <DrawPanel key={d.id} d={d} commit={commit} onDelete={onDelete} />; }
  if (sel?.type === "image") { const im = (project.images ?? []).find((x) => x.id === sel.id); if (im) return <ImagePanel key={im.id} im={im} a={asset(im.asset_id)} commit={commit} onDelete={onDelete} time={time} onSeek={onSeek} />; }
  return <ProjectPanel project={project} asset={asset} commit={commit} time={time} />;
}

function ProjectPanel({ project, asset, commit, time }: { project: Project; asset: (id: string) => Asset | undefined; commit: Commit; time: number }) {
  const idx = CANVAS_PRESETS.findIndex((p) => p.width === project.canvas.width && p.height === project.canvas.height);
  return (
    <div className="stack gap">
      <h3>Project</h3>
      <Field label="Name" htmlFor="pn"><input id="pn" className="input" value={project.name} maxLength={80} onChange={(e) => commit((p) => ({ ...p, name: e.target.value }), "name")} /></Field>
      <Field label="Video size" htmlFor="cs">
        <select id="cs" className="select" value={idx} onChange={(e) => { const p = CANVAS_PRESETS[Number(e.target.value)]; if (p) commit((pr) => ({ ...pr, canvas: { ...pr.canvas, width: p.width, height: p.height } })); }}>
          {idx < 0 && <option value={-1}>Custom · {project.canvas.width}×{project.canvas.height}</option>}
          {CANVAS_PRESETS.map((p, i) => <option key={p.label} value={i}>{p.label}</option>)}
        </select>
      </Field>
      <Field label="Frames per second" htmlFor="cf">
        <select id="cf" className="select" value={project.canvas.fps} onChange={(e) => commit((p) => ({ ...p, canvas: { ...p.canvas, fps: Number(e.target.value) } }))}>
          {[12, 24, 25, 30, 48, 60].map((f) => <option key={f} value={f}>{f}</option>)}
        </select>
      </Field>
      <Field label="Background colour" hint="Shows around clips that don’t fill the frame."><input className="color-input" type="color" value={project.canvas.background} aria-label="Background colour" onChange={(e) => commit((p) => ({ ...p, canvas: { ...p.canvas, background: e.target.value.toUpperCase() } }), "bg")} /></Field>
      <Slider label="Master volume" value={project.master_volume} min={0} max={2} step={0.05} onChange={(v) => commit((p) => ({ ...p, master_volume: v }), "mv")} format={(v) => `${Math.round(v * 100)}%`} />
      <label className="check"><input type="checkbox" checked={project.master_normalize} onChange={(e) => commit((p) => ({ ...p, master_normalize: e.target.checked }))} />Even out the loudness of the whole video</label>
      <label className="check"><input type="checkbox" checked={project.duck_music} onChange={(e) => commit((p) => ({ ...p, duck_music: e.target.checked }))} />Lower the music while someone speaks</label>
      {project.duck_music && <Slider label="How much to lower" value={project.duck_amount} min={0} max={1} step={0.05} onChange={(v) => commit((p) => ({ ...p, duck_amount: v }), "da")} format={(v) => `${Math.round(v * 100)}%`} />}
      {!IS_WEB && <ProjectAI project={project} asset={asset} commit={commit} time={time} />}
      <p className="hint">Select a clip, text or audio block on the timeline to edit it.</p>
    </div>
  );
}

function ProjectAI({ project, asset, commit, time }: { project: Project; asset: (id: string) => Asset | undefined; commit: Commit; time: number }) {
  const ai = useAI();
  const [busy, setBusy] = useState<string | null>(null);
  const [every, setEvery] = useState(2);
  const [words, setWords] = useState("");
  const [voice, setVoice] = useState("");
  const [voices, setVoices] = useState<string[]>([]);
  const [rate, setRate] = useState(0);
  useEffect(() => { api.voices().then((v) => setVoices(v.voices)).catch(() => {}); }, []);
  const guard = async (name: string, fn: () => Promise<void>) => { setBusy(name); try { await fn(); } catch (e) { ai.toast((e as Error).message, true); } finally { setBusy(null); } };

  const music = project.audio[0];
  const musicAsset = music ? asset(music.asset_id) : undefined;

  const cutToMusic = () => guard("beat", async () => {
    if (!music || !musicAsset) return;
    const r = await ai.run("beats", { asset_id: music.asset_id });
    const beats: number[] = (r.beats as number[]).filter((b) => b >= music.trim_in);
    if (beats.length < every + 1) throw new Error("Not enough beats found in this music.");
    const sources = project.clips.filter((c) => asset(c.asset_id));
    if (!sources.length) throw new Error("Add some clips first. They will be cut to the beat.");
    const musicEnd = music.trim_out > 0 ? music.trim_out : musicAsset.duration;
    const start = beats[0];
    const cursor = new Map<string, number>();
    const out: Clip[] = [];
    let k = 0;
    for (let i = 0; i + every < beats.length && beats[i + every] <= musicEnd + 0.01 && out.length < 300; i += every) {
      const d = beats[i + every] - beats[i];
      const src = sources[k++ % sources.length];
      const sa = asset(src.asset_id)!;
      const piece: Clip = { ...src, id: uid(), transition: { type: "none", duration: src.transition.duration }, fade_in: 0, fade_out: 0, speed: 1, reverse: false };
      if (sa.kind === "image") piece.image_duration = d;
      else {
        const lo = src.trim_in, hi = sourceEnd(src, sa);
        let at = cursor.get(src.id) ?? lo;
        if (at + d > hi) at = lo;
        if (hi - lo < d) { piece.speed = Math.min(4, Math.max(0.25, (hi - lo) / d)); piece.trim_in = lo; piece.trim_out = hi; cursor.set(src.id, lo); out.push(piece); continue; }
        piece.trim_in = at; piece.trim_out = at + d;
        cursor.set(src.id, at + d);
      }
      out.push(piece);
    }
    if (!out.length) throw new Error("Could not build a beat-cut from this music.");
    commit((p) => ({ ...p, clips: out, audio: p.audio.map((x, i) => (i === 0 ? { ...x, start: 0, trim_in: start } : x)) }));
    ai.toast(`Cut ${out.length} pieces to ${r.bpm} BPM. Undo with Ctrl+Z if you prefer the old order.`, false);
  });

  const voiceOver = () => guard("voice", async () => {
    const r = await ai.speak(words, voice, rate);
    const a = asset(r.asset_id);
    if (!a) throw new Error("The voice-over could not be added.");
    commit((p) => ({ ...p, audio: [...p.audio, newAudio(a, Math.max(0, time), { is_music: false })] }));
    ai.toast("Voice-over added to the timeline at the playhead.", false);
  });

  return (
    <div className="stack gap card card--muted">
      <h3>AI tools ✨</h3>
      <div className="stack gap aicard">
        <b className="text-sm">Cut clips to the music beat</b>
        <p className="text-xs">Finds the beat of the first music block and re-cuts your clips so every cut lands on the beat.</p>
        <Field label="Cut every" htmlFor="ev"><select id="ev" className="select" value={every} onChange={(e) => setEvery(Number(e.target.value))}>{[1, 2, 4, 8].map((n) => <option key={n} value={n}>{n} beat{n > 1 ? "s" : ""}</option>)}</select></Field>
        <Button small variant="secondary" icon={I.music} busy={busy === "beat"} disabled={!music || project.clips.length === 0} onClick={cutToMusic}>Auto-cut to music</Button>
        {!music && <p className="text-xs">Add a music file from the Media panel first.</p>}
      </div>
      <div className="stack gap aicard">
        <b className="text-sm">Voice-over</b>
        <p className="text-xs">Type words; a voice installed on this PC reads them. Added at the playhead.</p>
        <textarea className="textarea" rows={3} aria-label="Words to speak" maxLength={2000} placeholder="வணக்கம், இது என் வீடியோ…" value={words} onChange={(e) => setWords(e.target.value)} />
        {voices.length > 0 && <select className="select" aria-label="Voice" value={voice} onChange={(e) => setVoice(e.target.value)}><option value="">Default voice</option>{voices.map((v) => <option key={v} value={v}>{v}</option>)}</select>}
        <Slider label="Speed" value={rate} min={-5} max={5} step={1} onChange={setRate} format={(v) => (v === 0 ? "normal" : v > 0 ? `+${v}` : `${v}`)} />
        <Button small variant="secondary" icon={I.wand} busy={busy === "voice"} disabled={!words.trim()} onClick={voiceOver}>Create voice-over</Button>
      </div>
    </div>
  );
}

function ClipPanel({ clip, index, count, a, project, asset, commit, onDelete, onAddBackground }: { clip: Clip; index: number; count: number; a: Asset | undefined; project: Project; asset: (id: string) => Asset | undefined; commit: Commit; onDelete: () => void; onAddBackground: () => void }) {
  const [tab, setTab] = useState<"clip" | "picture" | "screen" | "color" | "fx" | "sound" | "ai">("clip");
  const cat = useCatalog();
  const set = (patch: Partial<Clip>, key?: string) => commit((p) => ({ ...p, clips: p.clips.map((c) => (c.id === clip.id ? { ...c, ...patch } : c)) }), key ? `${clip.id}:${key}` : undefined);
  const adj = (patch: Partial<Clip["adjust"]>, key: string) => set({ adjust: { ...clip.adjust, ...patch } }, key);
  const isImage = a?.kind === "image";
  const hasAudio = !!a?.has_audio;
  const srcLen = a?.duration ?? 0;
  return (
    <div className="stack gap">
      <div className="row between gap"><h3 className="truncate">{a?.name ?? "Clip"}</h3><Button variant="ghost" small icon={I.trash} label="Delete clip" onClick={onDelete} /></div>
      <Tabs label="Clip settings" value={tab} onChange={setTab} options={[{ id: "clip", label: "Clip" }, { id: "picture", label: "Picture" }, { id: "screen", label: "Green screen" }, { id: "color", label: "Colour" }, { id: "fx", label: "Effects" }, { id: "sound", label: "Sound", disabled: isImage || !hasAudio }, { id: "ai", label: "AI ✨" }]} />
      {tab === "clip" && (
        <>
          {isImage ? (
            <Slider label="Show for" value={clip.image_duration} min={0.5} max={30} step={0.5} onChange={(v) => set({ image_duration: v }, "id")} format={sec} />
          ) : (
            <>
              <div className="grid-2">
                <Field label="Start at (s)" htmlFor="ti"><input id="ti" className="input" type="number" min={0} max={srcLen} step={0.1} value={Number(clip.trim_in.toFixed(2))} onChange={(e) => set({ trim_in: Math.max(0, Math.min(Number(e.target.value) || 0, (clip.trim_out || srcLen) - 0.1)) }, "ti")} /></Field>
                <Field label="End at (s)" htmlFor="to" hint={`Clip is ${srcLen.toFixed(1)} s long`}><input id="to" className="input" type="number" min={0} max={srcLen} step={0.1} value={Number((clip.trim_out || srcLen).toFixed(2))} onChange={(e) => { const v = Number(e.target.value) || 0; set({ trim_out: v >= srcLen - 0.01 ? 0 : Math.max(clip.trim_in + 0.1, v) }, "to"); }} /></Field>
              </div>
              <Slider label="Speed" value={clip.speed} min={0.25} max={4} step={0.05} onChange={(v) => set({ speed: v }, "sp")} format={(v) => `${v.toFixed(2)}×`} />
              <label className="check"><input type="checkbox" checked={clip.reverse} onChange={(e) => set({ reverse: e.target.checked })} />Play backwards</label>
            </>
          )}
          {hasAudio && (
            <>
              <label className="check"><input type="checkbox" checked={clip.muted} onChange={(e) => set({ muted: e.target.checked })} />Mute this clip’s sound</label>
              <Slider label="Volume" value={clip.volume} min={0} max={2} step={0.05} disabled={clip.muted} onChange={(v) => set({ volume: v }, "vol")} format={(v) => `${Math.round(v * 100)}%`} />
            </>
          )}
          <div className="grid-2">
            <Slider label="Fade in" value={clip.fade_in} min={0} max={5} step={0.1} onChange={(v) => set({ fade_in: v }, "fi")} format={sec} />
            <Slider label="Fade out" value={clip.fade_out} min={0} max={5} step={0.1} onChange={(v) => set({ fade_out: v }, "fo")} format={sec} />
          </div>
          <div className="stack gap card card--muted">
            <h3>Transition to next clip</h3>
            {index >= count - 1 ? <p className="hint">The last clip has no next clip.</p> : (
              <>
                <GroupSelect id="trn" label="Transition type" value={clip.transition.type} items={cat.transitions} onChange={(v) => set({ transition: { ...clip.transition, type: v } })} />
                {clip.transition.type !== "none" && <Slider label="Length" value={clip.transition.duration} min={0.1} max={3} step={0.1} onChange={(v) => set({ transition: { ...clip.transition, duration: v } }, "td")} format={sec} />}
                <Button variant="ghost" small onClick={() => commit((p) => ({ ...p, clips: p.clips.map((c, i) => (i < p.clips.length - 1 ? { ...c, transition: { ...clip.transition } } : c)) }))}>Use this transition between all clips</Button>
              </>
            )}
          </div>
        </>
      )}
      {tab === "screen" && <ChromaControls chroma={clip.chroma} onChange={(chroma, key) => set({ chroma }, key)} onAddBackground={onAddBackground} />}
      {tab === "picture" && (
        <>
          <Field label="Fit in frame" htmlFor="fit">
            <select id="fit" className="select" value={clip.fit} onChange={(e) => set({ fit: e.target.value as Clip["fit"] })}>
              <option value="fit">Fit (black bars if needed)</option><option value="fill">Fill (crop edges)</option><option value="stretch">Stretch</option>
            </select>
          </Field>
          <Slider label="Zoom" value={clip.zoom} min={1} max={4} step={0.05} onChange={(v) => set({ zoom: v }, "z")} format={(v) => `${v.toFixed(2)}×`} />
          <Slider label="Move left / right" value={clip.pan_x} min={-1} max={1} step={0.05} disabled={clip.zoom === 1} onChange={(v) => set({ pan_x: v }, "px")} format={(v) => v.toFixed(2)} />
          <Slider label="Move up / down" value={clip.pan_y} min={-1} max={1} step={0.05} disabled={clip.zoom === 1} onChange={(v) => set({ pan_y: v }, "py")} format={(v) => v.toFixed(2)} />
          <div className="row gap wrap">
            <Button variant="secondary" small onClick={() => set({ rotate: ((clip.rotate + 90) % 360) as Clip["rotate"] })}>Rotate 90° ({clip.rotate}°)</Button>
            <Button variant="secondary" small active={clip.flip_h} onClick={() => set({ flip_h: !clip.flip_h })}>Flip left/right</Button>
            <Button variant="secondary" small active={clip.flip_v} onClick={() => set({ flip_v: !clip.flip_v })}>Flip up/down</Button>
          </div>
        </>
      )}
      {tab === "color" && (
        <>
          <Field label="Look" htmlFor="pre"><GroupSelect id="pre" label="Look" value={clip.preset} items={cat.looks} onChange={(v) => set({ preset: v })} /></Field>
          <Slider label="Brightness" value={clip.adjust.brightness} min={-100} max={100} onChange={(v) => adj({ brightness: v }, "b")} format={pct} />
          <Slider label="Contrast" value={clip.adjust.contrast} min={-100} max={100} onChange={(v) => adj({ contrast: v }, "c")} format={pct} />
          <Slider label="Colour strength" value={clip.adjust.saturation} min={-100} max={100} onChange={(v) => adj({ saturation: v }, "s")} format={pct} />
          <Slider label="Gamma" value={clip.adjust.gamma} min={0.3} max={3} step={0.05} onChange={(v) => adj({ gamma: v }, "g")} format={(v) => v.toFixed(2)} />
          <Slider label="Hue shift" value={clip.adjust.hue} min={-180} max={180} onChange={(v) => adj({ hue: v }, "h")} format={(v) => `${v}°`} />
          <Button variant="ghost" small onClick={() => set({ adjust: { brightness: 0, contrast: 0, saturation: 0, gamma: 1, hue: 0 }, preset: "none" })}>Reset colour</Button>
        </>
      )}
      {tab === "fx" && (
        <>
          <Field label="Camera motion" htmlFor="mo" hint="Slow zoom, pan or shake added to the picture.">
            <GroupSelect id="mo" label="Camera motion" value={clip.motion} items={cat.motions} onChange={(v) => set({ motion: v })} />
          </Field>
          {clip.motion !== "none" && <Slider label="Motion strength" value={clip.motion_strength} min={0} max={1} step={0.05} onChange={(v) => set({ motion_strength: v }, "ms")} format={(v) => `${Math.round(v * 100)}%`} />}
          <div className="stack gap card card--muted">
            <div className="row between"><h3>Effects</h3><span className="text-xs">{clip.effects.length}/6</span></div>
            {clip.effects.map((e: Effect, i) => (
              <div key={i} className="stack">
                <div className="row gap">
                  <select className="select" aria-label={`Effect ${i + 1}`} value={e.type} onChange={(ev) => set({ effects: clip.effects.map((x, j) => (j === i ? { ...x, type: ev.target.value } : x)) })}>
                    {groupBy(cat.effects).map(([g, list]) => <optgroup key={g} label={g}>{list.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}</optgroup>)}
                  </select>
                  <Button variant="ghost" small icon={I.trash} label="Remove effect" onClick={() => set({ effects: clip.effects.filter((_, j) => j !== i) })} />
                </div>
                <Slider label="Amount" value={e.amount} min={0} max={1} step={0.05} onChange={(v) => set({ effects: clip.effects.map((x, j) => (j === i ? { ...x, amount: v } : x)) }, `fx${i}`)} format={(v) => `${Math.round(v * 100)}%`} />
              </div>
            ))}
            {clip.effects.length < 6 && cat.effects.length > 0 && <Button variant="secondary" small icon={I.plus} onClick={() => set({ effects: [...clip.effects, { type: cat.effects[0].id, amount: 0.5 }] })}>Add effect</Button>}
          </div>
          <Slider label="Blur" value={clip.blur} min={0} max={30} step={0.5} onChange={(v) => set({ blur: v }, "bl")} />
          <Slider label="Sharpen" value={clip.sharpen} min={0} max={5} step={0.1} onChange={(v) => set({ sharpen: v }, "sh")} />
          <label className="check"><input type="checkbox" checked={clip.vignette} onChange={(e) => set({ vignette: e.target.checked })} />Darken the corners (vignette)</label>
          <label className="check"><input type="checkbox" checked={clip.denoise} onChange={(e) => set({ denoise: e.target.checked })} />Reduce grain and noise</label>
          <p className="hint">Looks, effects, motion, sharpen and noise reduction are exact in “Render preview” and the exported file; the live preview only approximates colour.</p>
        </>
      )}
      {tab === "sound" && (
        <>
          <Field label="Sound effect" htmlFor="afx"><GroupSelect id="afx" label="Sound effect" value={clip.audio_fx} items={cat.audio_fx} onChange={(v) => set({ audio_fx: v })} /></Field>
          <Slider label="Pitch" value={clip.pitch} min={-12} max={12} step={1} onChange={(v) => set({ pitch: v }, "pi")} format={(v) => `${v > 0 ? "+" : ""}${v} semitones`} />
          <Slider label="Bass" value={clip.bass} min={-12} max={12} step={1} onChange={(v) => set({ bass: v }, "ba")} format={(v) => `${v > 0 ? "+" : ""}${v} dB`} />
          <Slider label="Treble" value={clip.treble} min={-12} max={12} step={1} onChange={(v) => set({ treble: v }, "tr")} format={(v) => `${v > 0 ? "+" : ""}${v} dB`} />
          <label className="check"><input type="checkbox" checked={clip.denoise_audio} onChange={(e) => set({ denoise_audio: e.target.checked })} />Remove background noise</label>
          <label className="check"><input type="checkbox" checked={clip.normalize_audio} onChange={(e) => set({ normalize_audio: e.target.checked })} />Even out the loudness</label>
        </>
      )}
      {tab === "ai" && <ClipAI clip={clip} a={a} project={project} asset={asset} commit={commit} set={set} />}
    </div>
  );
}

function ClipAI({ clip, a, project, asset, commit, set }: { clip: Clip; a: Asset | undefined; project: Project; asset: (id: string) => Asset | undefined; commit: Commit; set: (patch: Partial<Clip>, key?: string) => void }) {
  const ai = useAI();
  const cat = useCatalog();
  const [busy, setBusy] = useState<string | null>(null);
  const [model, setModel] = useState("whisper-base");
  const [lang, setLang] = useState("");
  const [info, setInfo] = useState("");
  const isVideo = a?.kind === "video";
  const req = { asset_id: clip.asset_id, trim_in: clip.trim_in, trim_out: clip.trim_out };
  const guard = async (name: string, fn: () => Promise<void>) => { setBusy(name); setInfo(""); try { await fn(); } catch (e) { ai.toast((e as Error).message, true); } finally { setBusy(null); } };

  const replaceWithRanges = (ranges: [number, number][]) => commit((p) => ({
    ...p, clips: p.clips.flatMap((c) => c.id !== clip.id ? [c] : ranges.map((r, i) => ({
      ...c, id: i === 0 ? c.id : uid(), trim_in: r[0], trim_out: r[1],
      transition: i === ranges.length - 1 ? c.transition : { type: "none", duration: c.transition.duration },
      fade_in: i === 0 ? c.fade_in : 0, fade_out: i === ranges.length - 1 ? c.fade_out : 0,
    }))),
  }));
  const end = a ? sourceEnd(clip, a) : 0;

  const follow = () => guard("follow", async () => {
    const r = await ai.run("follow", req);
    set({ follow: { keys: r.keys, zoom: clip.follow?.zoom ?? 1.2 }, fit: "fill" });
    setInfo(r.found >= 0.5 ? `Tracked a face in ${Math.round(r.found * 100)}% of the clip.` : "Few faces were visible, so the camera follows movement instead. Check the preview.");
  });
  const silence = () => guard("silence", async () => {
    const r = await ai.run("silence", { ...req, options: { noise_db: -35, min_silence: 0.6 } });
    const keep = r.keep as [number, number][];
    if (r.removed < 0.3) { setInfo("No silent parts found."); return; }
    replaceWithRanges(keep);
    setInfo(`Removed ${Number(r.removed).toFixed(1)} s of silence. Undo with Ctrl+Z.`);
  });
  const scenes = () => guard("scenes", async () => {
    const r = await ai.run("scenes", req);
    const cuts = (r.cuts as number[]).filter((c) => c > clip.trim_in + 0.3 && c < end - 0.3);
    if (!cuts.length) { setInfo("No scene changes found."); return; }
    const pts = [clip.trim_in, ...cuts, end];
    replaceWithRanges(pts.slice(0, -1).map((v, i) => [v, pts[i + 1]] as [number, number]));
    setInfo(`Split into ${pts.length - 1} scenes.`);
  });
  const enhance = () => guard("enhance", async () => { const adj = await api.enhance(req); set({ adjust: adj }); setInfo("Brightness, contrast and colour adjusted. Fine-tune in the Colour tab."); });
  const captions = () => guard("captions", async () => {
    const r = await ai.run("captions", { ...req, options: { model: model.replace("whisper-", ""), language: lang } });
    const segs = r.segments as { start: number; end: number; text: string }[];
    if (!segs.length) { setInfo("No speech was found."); return; }
    const t0 = layout(project, asset).items.find((i) => i.clip.id === clip.id)?.start ?? 0;
    const style = TEXT_STYLES.find((x) => x.id === "subtitle")!.patch;
    const made = segs.map((sg) => {
      const t = newText(Math.max(0, t0 + (sg.start - clip.trim_in) / clip.speed));
      const words = sg.text.length > 44 ? sg.text.replace(/(.{20,44})\s/, "$1\n") : sg.text;
      return { ...t, ...style, text: words, duration: Math.max(0.5, (sg.end - sg.start) / clip.speed), fade_in: 0.1, fade_out: 0.1, anim_in: "fade", anim_out: "fade" } as TextOverlay;
    });
    commit((p) => ({ ...p, texts: [...p.texts, ...made] }));
    setInfo(`Added ${made.length} subtitles${r.language ? ` (language: ${r.language})` : ""}. Edit any of them on the timeline.`);
  });

  if (!a) return <p className="hint">This clip’s file is missing.</p>;
  const installed = cat.whisper.find((w) => w.id === model)?.installed ?? false;
  return (
    <div className="stack gap">
      {isVideo && !IS_WEB && (
        <div className="stack gap aicard">
          <b className="text-sm">Follow the person</b>
          <p className="text-xs">Keeps a person in frame by moving a crop window with them, for example turning a wide video into a vertical one that follows the speaker.</p>
          <div className="row gap wrap">
            <Button small variant="secondary" icon={I.sparkle} busy={busy === "follow"} onClick={follow}>{clip.follow ? "Track again" : "Track person"}</Button>
            {clip.follow && <Button small variant="ghost" onClick={() => set({ follow: null })}>Remove tracking</Button>}
          </div>
          {clip.follow && <Slider label="Zoom on person" value={clip.follow.zoom} min={1} max={3} step={0.05} onChange={(v) => set({ follow: { ...clip.follow!, zoom: v } }, "fz")} format={(v) => `${v.toFixed(2)}×`} />}
          {clip.follow && <p className="text-xs">Tip: set the project size to Vertical 9:16 for a phone video. The Picture tab’s zoom and move are replaced while tracking is on.</p>}
        </div>
      )}
      {!IS_WEB && <div className="stack gap aicard">
        <b className="text-sm">Auto captions</b>
        <p className="text-xs">Listens to the speech and adds subtitles you can restyle. Runs on this PC.</p>
        <div className="stack gap">
          <select className="select" aria-label="Captions model" value={model} onChange={(e) => setModel(e.target.value)}>{cat.whisper.map((w) => <option key={w.id} value={w.id}>{w.label.replace("Captions model: ", "")}{w.installed ? "" : " (not downloaded)"}</option>)}</select>
          <select className="select" aria-label="Spoken language" value={lang} onChange={(e) => setLang(e.target.value)}>
            <option value="">Detect language</option><option value="en">English</option><option value="ta">Tamil</option><option value="hi">Hindi</option><option value="te">Telugu</option><option value="kn">Kannada</option><option value="ml">Malayalam</option><option value="bn">Bengali</option>
          </select>
        </div>
        <Button small variant="secondary" icon={I.text} busy={busy === "captions"} disabled={!installed || !a.has_audio} onClick={captions}>Create captions</Button>
        {!installed && <p className="text-xs">Download this captions model first: Models page → “{cat.whisper.find((w) => w.id === model)?.label ?? "Captions model"}”. “Small” understands Tamil and Hindi best.</p>}
        {!a.has_audio && <p className="text-xs">This clip has no sound.</p>}
      </div>}
      <div className="stack gap aicard">
        <b className="text-sm">Smart edits</b>
        <div className="row gap wrap">
          <Button small variant="secondary" busy={busy === "silence"} disabled={!a.has_audio} onClick={silence}>Cut out silences</Button>
          {isVideo && <Button small variant="secondary" busy={busy === "scenes"} onClick={scenes}>Split at scene changes</Button>}
          <Button small variant="secondary" busy={busy === "enhance"} onClick={enhance}>Auto-enhance colour</Button>
        </div>
      </div>
      {info && <p className="text-sm" role="status">{info}</p>}
    </div>
  );
}

function TextPanel({ t, commit, onDelete, time, onSeek }: { t: TextOverlay; commit: Commit; onDelete: () => void; time: number; onSeek: (t: number) => void }) {
  const cat = useCatalog();
  const [tab, setTab] = useState<"text" | "style" | "move">("text");
  const set = (patch: Partial<TextOverlay>, key?: string) => commit((p) => ({ ...p, texts: p.texts.map((x) => (x.id === t.id ? { ...x, ...patch } : x)) }), key ? `${t.id}:${key}` : undefined);
  const empty = t.text.trim() === "";
  const col = (label: string, v: string, on: (c: string) => void) => <Field label={label}><input className="color-input" type="color" aria-label={label} value={v} onChange={(e) => on(e.target.value.toUpperCase())} /></Field>;
  return (
    <div className="stack gap">
      <div className="row between"><h3>Text</h3><Button variant="ghost" small icon={I.trash} label="Delete text" onClick={onDelete} /></div>
      <Tabs label="Text settings" value={tab} onChange={setTab} options={[{ id: "text", label: "Text" }, { id: "style", label: "Style" }, { id: "move", label: "Motion" }]} />
      {tab === "text" && (
        <>
          <Field label="Words" htmlFor="tt" error={empty ? "Text can’t be empty — it won’t be exported." : null}><textarea id="tt" className="textarea" rows={3} value={t.text} maxLength={500} aria-invalid={empty} onChange={(e) => set({ text: e.target.value }, "t")} /></Field>
          <div className="grid-2">
            <Field label="Appears at (s)" htmlFor="ts"><input id="ts" className="input" type="number" min={0} step={0.1} value={Number(t.start.toFixed(2))} onChange={(e) => set({ start: Math.max(0, Number(e.target.value) || 0) }, "ts")} /></Field>
            <Field label="Stays for (s)" htmlFor="td"><input id="td" className="input" type="number" min={0.1} step={0.1} value={Number(t.duration.toFixed(2))} onChange={(e) => set({ duration: Math.max(0.1, Number(e.target.value) || 0.1) }, "td")} /></Field>
          </div>
          <Field label="Font"><FontPicker value={t.font} bold={t.bold} onChange={(f) => set({ font: f })} /></Field>
          <Slider label="Size" value={t.size} min={2} max={30} step={0.5} onChange={(v) => set({ size: v }, "sz")} />
          <div className="row gap wrap">
            <label className="check"><input type="checkbox" checked={t.bold} onChange={(e) => set({ bold: e.target.checked })} />Bold</label>
            <label className="check"><input type="checkbox" checked={t.italic} onChange={(e) => set({ italic: e.target.checked })} />Italic</label>
            <label className="check"><input type="checkbox" checked={t.uppercase} onChange={(e) => set({ uppercase: e.target.checked })} />CAPITALS</label>
          </div>
          <div className="row gap" role="group" aria-label="Alignment">
            {(["left", "center", "right"] as const).map((al) => <Button key={al} variant="secondary" small active={t.align === al} onClick={() => set({ align: al })}>{al === "left" ? "Left" : al === "right" ? "Right" : "Centre"}</Button>)}
          </div>
          <Slider label="Left / right position" value={t.x} min={0} max={1} step={0.01} onChange={(v) => set({ x: v }, "x")} format={(v) => `${Math.round(v * 100)}%`} />
          <Slider label="Up / down position" value={t.y} min={0} max={1} step={0.01} onChange={(v) => set({ y: v }, "y")} format={(v) => `${Math.round(v * 100)}%`} />
        </>
      )}
      {tab === "style" && (
        <>
          <b className="text-sm">One-click styles</b>
          <div className="stylegrid">
            {TEXT_STYLES.map((st) => <button type="button" key={st.id} className="stylebtn" onClick={() => set(st.patch)}>{st.label}</button>)}
          </div>
          <div className="row gap wrap">
            {col("Colour", t.color, (c) => set({ color: c }, "c"))}
            <label className="check"><input type="checkbox" checked={t.color2 !== null} onChange={(e) => set({ color2: e.target.checked ? "#FFC107" : null })} />Gradient</label>
            {t.color2 !== null && col("Bottom colour", t.color2, (c) => set({ color2: c }, "c2"))}
          </div>
          <Slider label="Outline" value={t.stroke} min={0} max={20} step={0.5} onChange={(v) => set({ stroke: v }, "st")} format={(v) => (v ? `${v}` : "off")} />
          {t.stroke > 0 && col("Outline colour", t.stroke_color, (c) => set({ stroke_color: c }, "sc"))}
          <Slider label="Shadow" value={t.shadow} min={0} max={1} step={0.05} onChange={(v) => set({ shadow: v }, "sh")} format={(v) => (v ? `${Math.round(v * 100)}%` : "off")} />
          {t.shadow > 0 && col("Shadow colour", t.shadow_color, (c) => set({ shadow_color: c }, "shc"))}
          <Slider label="Glow" value={t.glow} min={0} max={1} step={0.05} onChange={(v) => set({ glow: v }, "gl")} format={(v) => (v ? `${Math.round(v * 100)}%` : "off")} />
          {t.glow > 0 && col("Glow colour", t.glow_color, (c) => set({ glow_color: c }, "glc"))}
          <label className="check"><input type="checkbox" checked={t.box} onChange={(e) => set({ box: e.target.checked })} />Box behind the words</label>
          {t.box && <><Slider label="Box darkness" value={t.box_opacity} min={0} max={1} step={0.05} onChange={(v) => set({ box_opacity: v }, "bo")} format={(v) => `${Math.round(v * 100)}%`} />{col("Box colour", t.box_color, (c) => set({ box_color: c }, "bc"))}</>}
          <Slider label="Letter spacing" value={t.letter_spacing} min={-0.1} max={1} step={0.01} onChange={(v) => set({ letter_spacing: v }, "ls")} format={(v) => v.toFixed(2)} />
          <Slider label="Line spacing" value={t.line_spacing} min={0.8} max={2.5} step={0.05} onChange={(v) => set({ line_spacing: v }, "lh")} format={(v) => v.toFixed(2)} />
          <Slider label="Tilt" value={t.rotation} min={-45} max={45} step={1} onChange={(v) => set({ rotation: v }, "rot")} format={(v) => `${v}°`} />
          <Slider label="See-through" value={1 - t.opacity} min={0} max={0.9} step={0.05} onChange={(v) => set({ opacity: 1 - v }, "op")} format={(v) => `${Math.round(v * 100)}%`} />
          <p className="hint">Tamil, Hindi and other Indian scripts switch to a matching font automatically if the chosen font can’t draw them.</p>
        </>
      )}
      {tab === "move" && (
        <>
          <Field label="Comes in" htmlFor="ain"><select id="ain" className="select" value={t.anim_in} onChange={(e) => set({ anim_in: e.target.value })}>{cat.text_anim_in.map((a) => <option key={a} value={a}>{animLabel(a)}</option>)}</select></Field>
          <Slider label="Coming-in time" value={t.fade_in} min={0} max={3} step={0.1} disabled={t.anim_in === "none"} onChange={(v) => set({ fade_in: v }, "fi")} format={sec} />
          <Field label="Goes out" htmlFor="aout"><select id="aout" className="select" value={t.anim_out} onChange={(e) => set({ anim_out: e.target.value })}>{cat.text_anim_out.map((a) => <option key={a} value={a}>{animLabel(a)}</option>)}</select></Field>
          <Slider label="Going-out time" value={t.fade_out} min={0} max={3} step={0.1} disabled={t.anim_out === "none"} onChange={(v) => set({ fade_out: v }, "fo")} format={sec} />
          <p className="hint">Animations show exactly in “Render preview” and the exported file; the live preview shows fades and slides roughly.</p>
          <h4 className="kf-title">◆ Move across the screen</h4>
          <KeyframeControls what="this text" keys={t.keys} start={t.start} length={t.duration} time={time} pose={{ ...itemRest(t), x: itemPose(t, time).x, y: itemPose(t, time).y }} onSeek={onSeek} onChange={(keys) => set({ keys })} />
        </>
      )}
    </div>
  );
}

function AudioPanel({ ac, a, commit, onDelete }: { ac: AudioClip; a: Asset | undefined; commit: Commit; onDelete: () => void }) {
  const cat = useCatalog();
  const set = (patch: Partial<AudioClip>, key?: string) => commit((p) => ({ ...p, audio: p.audio.map((x) => (x.id === ac.id ? { ...x, ...patch } : x)) }), key ? `${ac.id}:${key}` : undefined);
  const len = a?.duration ?? 0;
  return (
    <div className="stack gap">
      <div className="row between gap"><h3 className="truncate">{a?.name ?? "Audio"}</h3><Button variant="ghost" small icon={I.trash} label="Delete audio" onClick={onDelete} /></div>
      <div className="grid-2">
        <Field label="Starts at (s)" htmlFor="as"><input id="as" className="input" type="number" min={0} step={0.1} value={Number(ac.start.toFixed(2))} onChange={(e) => set({ start: Math.max(0, Number(e.target.value) || 0) }, "as")} /></Field>
        <Field label="Skip first (s)" htmlFor="ai"><input id="ai" className="input" type="number" min={0} max={len} step={0.1} value={Number(ac.trim_in.toFixed(2))} onChange={(e) => set({ trim_in: Math.max(0, Math.min(Number(e.target.value) || 0, len - 0.1)) }, "ai")} /></Field>
      </div>
      <Field label="Stop at (s)" htmlFor="ao" hint={`File is ${len.toFixed(1)} s long`}><input id="ao" className="input" type="number" min={0} max={len} step={0.1} value={Number((ac.trim_out || len).toFixed(2))} onChange={(e) => { const v = Number(e.target.value) || 0; set({ trim_out: v >= len - 0.01 ? 0 : Math.max(ac.trim_in + 0.1, v) }, "ao"); }} /></Field>
      <Slider label="Volume" value={ac.volume} min={0} max={2} step={0.05} onChange={(v) => set({ volume: v }, "v")} format={(v) => `${Math.round(v * 100)}%`} />
      <div className="grid-2">
        <Slider label="Fade in" value={ac.fade_in} min={0} max={10} step={0.1} onChange={(v) => set({ fade_in: v }, "fi")} format={sec} />
        <Slider label="Fade out" value={ac.fade_out} min={0} max={10} step={0.1} onChange={(v) => set({ fade_out: v }, "fo")} format={sec} />
      </div>
      <label className="check"><input type="checkbox" checked={ac.loop} onChange={(e) => set({ loop: e.target.checked })} />Repeat until the video ends</label>
      <label className="check"><input type="checkbox" checked={ac.is_music} onChange={(e) => set({ is_music: e.target.checked })} />This is background music (lowered under speech when “Lower the music” is on)</label>
      <Field label="Sound effect" htmlFor="afx"><GroupSelect id="afx" label="Sound effect" value={ac.fx} items={cat.audio_fx} onChange={(v) => set({ fx: v })} /></Field>
      <Slider label="Pitch" value={ac.pitch} min={-12} max={12} step={1} onChange={(v) => set({ pitch: v }, "pi")} format={(v) => `${v > 0 ? "+" : ""}${v} semitones`} />
      <Slider label="Bass" value={ac.bass} min={-12} max={12} step={1} onChange={(v) => set({ bass: v }, "ba")} format={(v) => `${v > 0 ? "+" : ""}${v} dB`} />
      <Slider label="Treble" value={ac.treble} min={-12} max={12} step={1} onChange={(v) => set({ treble: v }, "tr")} format={(v) => `${v > 0 ? "+" : ""}${v} dB`} />
      <label className="check"><input type="checkbox" checked={ac.denoise} onChange={(e) => set({ denoise: e.target.checked })} />Remove background noise</label>
      <label className="check"><input type="checkbox" checked={ac.normalize} onChange={(e) => set({ normalize: e.target.checked })} />Even out the loudness</label>
    </div>
  );
}

function ImagePanel({ im, a, commit, onDelete, time, onSeek }: { im: ImageOverlay; a: Asset | undefined; commit: Commit; onDelete: () => void; time: number; onSeek: (t: number) => void }) {
  const set = (patch: Partial<ImageOverlay>, key?: string) => commit((p) => ({ ...p, images: p.images.map((x) => (x.id === im.id ? { ...x, ...patch } : x)) }), key ? `${im.id}:${key}` : undefined);
  return (
    <div className="stack gap">
      <div className="row between"><h3>Picture on the video</h3><Button variant="ghost" small icon={I.trash} label="Delete picture" onClick={onDelete} /></div>
      <p className="text-sm">{a?.name ?? "Picture"} — move it with the sliders. To add a new picture, drop a PNG or JPG on the preview or ask the chat editor.</p>
      <Slider label="Left ↔ right" value={im.x} min={0} max={1} step={0.005} onChange={(v) => set({ x: v }, "x")} format={(v) => `${Math.round(v * 100)}%`} />
      <Slider label="Up ↕ down" value={im.y} min={0} max={1} step={0.005} onChange={(v) => set({ y: v }, "y")} format={(v) => `${Math.round(v * 100)}%`} />
      <Slider label="Size" value={im.size} min={0.03} max={1} step={0.005} onChange={(v) => set({ size: v }, "z")} format={(v) => `${Math.round(v * 100)}%`} />
      <Slider label="Turn" value={im.rotation} min={-180} max={180} step={1} onChange={(v) => set({ rotation: v }, "r")} format={(v) => `${Math.round(v)}°`} />
      <Slider label="See-through" value={1 - im.opacity} min={0} max={0.9} step={0.05} onChange={(v) => set({ opacity: 1 - v }, "op")} format={(v) => `${Math.round(v * 100)}%`} />
      <div className="grid-2">
        <Field label="Appears at (s)" htmlFor="is"><input id="is" className="input" type="number" min={0} step={0.1} value={Number(im.start.toFixed(2))} onChange={(e) => set({ start: Math.max(0, Number(e.target.value) || 0) }, "s")} /></Field>
        <Field label="Stays for (s)" htmlFor="id"><input id="id" className="input" type="number" min={0.2} step={0.1} value={Number(im.duration.toFixed(2))} onChange={(e) => set({ duration: Math.max(0.2, Number(e.target.value) || 0.2) }, "d")} /></Field>
      </div>
      <h4 className="kf-title">◆ Move across the screen</h4>
      <KeyframeControls what="this picture" keys={im.keys} start={im.start} length={im.duration} time={time} pose={{ ...itemRest(im), x: itemPose(im, time).x, y: itemPose(im, time).y }} onSeek={onSeek} onChange={(keys) => set({ keys })} />
    </div>
  );
}

function DrawPanel({ d, commit, onDelete }: { d: Drawing; commit: Commit; onDelete: () => void }) {
  const cat = useCatalog();
  const set = (patch: Partial<Drawing>, key?: string) => commit((p) => ({ ...p, drawings: p.drawings.map((x) => (x.id === d.id ? { ...x, ...patch } : x)) }), key ? `${d.id}:${key}` : undefined);
  return (
    <div className="stack gap">
      <div className="row between"><h3>Drawing</h3><Button variant="ghost" small icon={I.trash} label="Delete drawing" onClick={onDelete} /></div>
      <p className="text-sm">{d.shapes.length} shape{d.shapes.length === 1 ? "" : "s"}. Press <b>Draw</b> in the toolbar to add more while this is selected.</p>
      <div className="row gap wrap">
        <Button variant="secondary" small disabled={d.shapes.length === 0} onClick={() => set({ shapes: d.shapes.slice(0, -1) })}>Undo last shape</Button>
        <Button variant="secondary" small disabled={d.shapes.length === 0} onClick={() => set({ shapes: [] })}>Clear all</Button>
      </div>
      <div className="grid-2">
        <Field label="Appears at (s)" htmlFor="ds"><input id="ds" className="input" type="number" min={0} step={0.1} value={Number(d.start.toFixed(2))} onChange={(e) => set({ start: Math.max(0, Number(e.target.value) || 0) }, "s")} /></Field>
        <Field label="Stays for (s)" htmlFor="dd"><input id="dd" className="input" type="number" min={0.2} step={0.1} value={Number(d.duration.toFixed(2))} onChange={(e) => set({ duration: Math.max(0.2, Number(e.target.value) || 0.2) }, "d")} /></Field>
      </div>
      <Slider label="See-through" value={1 - d.opacity} min={0} max={0.9} step={0.05} onChange={(v) => set({ opacity: 1 - v }, "op")} format={(v) => `${Math.round(v * 100)}%`} />
      <Field label="Comes in" htmlFor="dain"><select id="dain" className="select" value={d.anim_in} onChange={(e) => set({ anim_in: e.target.value })}>{cat.text_anim_in.map((a) => <option key={a} value={a}>{animLabel(a)}</option>)}</select></Field>
      <Slider label="Coming-in time" value={d.fade_in} min={0} max={3} step={0.1} disabled={d.anim_in === "none"} onChange={(v) => set({ fade_in: v }, "fi")} format={sec} />
      <Field label="Goes out" htmlFor="daout"><select id="daout" className="select" value={d.anim_out} onChange={(e) => set({ anim_out: e.target.value })}>{cat.text_anim_out.map((a) => <option key={a} value={a}>{animLabel(a)}</option>)}</select></Field>
      <Slider label="Going-out time" value={d.fade_out} min={0} max={3} step={0.1} disabled={d.anim_out === "none"} onChange={(v) => set({ fade_out: v }, "fo")} format={sec} />
    </div>
  );
}
