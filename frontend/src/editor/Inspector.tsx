import { useState } from "react";
import { Button, Field, Slider, Tabs, I } from "../ds";
import type { Asset, AudioClip, Clip, Project, TextOverlay } from "../lib/types";
import { CANVAS_PRESETS, PRESETS, TRANSITIONS } from "./model";

export type Selection = { type: "clip" | "text" | "audio"; id: string } | null;
type Commit = (fn: (p: Project) => Project, key?: string) => void;

const pct = (v: number) => `${Math.round(v)}`;
const sec = (v: number) => `${v.toFixed(2)} s`;

export default function Inspector({ project, sel, asset, commit, onDelete }: { project: Project; sel: Selection; asset: (id: string) => Asset | undefined; commit: Commit; onDelete: () => void }) {
  if (sel?.type === "clip") { const c = project.clips.find((x) => x.id === sel.id); if (c) return <ClipPanel key={c.id} clip={c} index={project.clips.findIndex((x) => x.id === c.id)} count={project.clips.length} a={asset(c.asset_id)} commit={commit} onDelete={onDelete} />; }
  if (sel?.type === "text") { const t = project.texts.find((x) => x.id === sel.id); if (t) return <TextPanel key={t.id} t={t} commit={commit} onDelete={onDelete} />; }
  if (sel?.type === "audio") { const t = project.audio.find((x) => x.id === sel.id); if (t) return <AudioPanel key={t.id} ac={t} a={asset(t.asset_id)} commit={commit} onDelete={onDelete} />; }
  return <ProjectPanel project={project} commit={commit} />;
}

function ProjectPanel({ project, commit }: { project: Project; commit: Commit }) {
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
      <p className="hint">Select a clip, text or audio block on the timeline to edit it.</p>
    </div>
  );
}

function ClipPanel({ clip, index, count, a, commit, onDelete }: { clip: Clip; index: number; count: number; a: Asset | undefined; commit: Commit; onDelete: () => void }) {
  const [tab, setTab] = useState<"clip" | "picture" | "color" | "fx">("clip");
  const set = (patch: Partial<Clip>, key?: string) => commit((p) => ({ ...p, clips: p.clips.map((c) => (c.id === clip.id ? { ...c, ...patch } : c)) }), key ? `${clip.id}:${key}` : undefined);
  const adj = (patch: Partial<Clip["adjust"]>, key: string) => set({ adjust: { ...clip.adjust, ...patch } }, key);
  const isImage = a?.kind === "image";
  const hasAudio = !!a?.has_audio;
  const srcLen = a?.duration ?? 0;
  return (
    <div className="stack gap">
      <div className="row between gap"><h3 className="truncate">{a?.name ?? "Clip"}</h3><Button variant="ghost" small icon={I.trash} label="Delete clip" onClick={onDelete} /></div>
      <Tabs label="Clip settings" value={tab} onChange={setTab} options={[{ id: "clip", label: "Clip" }, { id: "picture", label: "Picture" }, { id: "color", label: "Colour" }, { id: "fx", label: "Effects" }]} />
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
                <select className="select" aria-label="Transition type" value={clip.transition.type} onChange={(e) => set({ transition: { ...clip.transition, type: e.target.value } })}>
                  {TRANSITIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
                {clip.transition.type !== "none" && <Slider label="Length" value={clip.transition.duration} min={0.1} max={3} step={0.1} onChange={(v) => set({ transition: { ...clip.transition, duration: v } }, "td")} format={sec} />}
              </>
            )}
          </div>
        </>
      )}
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
          <Field label="Filter" htmlFor="pre"><select id="pre" className="select" value={clip.preset} onChange={(e) => set({ preset: e.target.value })}>{PRESETS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>
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
          <Slider label="Blur" value={clip.blur} min={0} max={30} step={0.5} onChange={(v) => set({ blur: v }, "bl")} />
          <Slider label="Sharpen" value={clip.sharpen} min={0} max={5} step={0.1} onChange={(v) => set({ sharpen: v }, "sh")} />
          <label className="check"><input type="checkbox" checked={clip.vignette} onChange={(e) => set({ vignette: e.target.checked })} />Darken the corners (vignette)</label>
          <label className="check"><input type="checkbox" checked={clip.denoise} onChange={(e) => set({ denoise: e.target.checked })} />Reduce grain and noise</label>
          <p className="hint">Sharpen, noise reduction and exact blur show up in “Render preview” and the exported file, not in the live preview.</p>
        </>
      )}
    </div>
  );
}

function TextPanel({ t, commit, onDelete }: { t: TextOverlay; commit: Commit; onDelete: () => void }) {
  const set = (patch: Partial<TextOverlay>, key?: string) => commit((p) => ({ ...p, texts: p.texts.map((x) => (x.id === t.id ? { ...x, ...patch } : x)) }), key ? `${t.id}:${key}` : undefined);
  const empty = t.text.trim() === "";
  return (
    <div className="stack gap">
      <div className="row between"><h3>Text</h3><Button variant="ghost" small icon={I.trash} label="Delete text" onClick={onDelete} /></div>
      <Field label="Words" htmlFor="tt" error={empty ? "Text can’t be empty — it won’t be exported." : null}><textarea id="tt" className="textarea" rows={3} value={t.text} maxLength={500} aria-invalid={empty} onChange={(e) => set({ text: e.target.value }, "t")} /></Field>
      <div className="grid-2">
        <Field label="Appears at (s)" htmlFor="ts"><input id="ts" className="input" type="number" min={0} step={0.1} value={Number(t.start.toFixed(2))} onChange={(e) => set({ start: Math.max(0, Number(e.target.value) || 0) }, "ts")} /></Field>
        <Field label="Stays for (s)" htmlFor="td"><input id="td" className="input" type="number" min={0.1} step={0.1} value={Number(t.duration.toFixed(2))} onChange={(e) => set({ duration: Math.max(0.1, Number(e.target.value) || 0.1) }, "td")} /></Field>
      </div>
      <Slider label="Size" value={t.size} min={2} max={20} step={0.5} onChange={(v) => set({ size: v }, "sz")} />
      <Slider label="Left / right position" value={t.x} min={0} max={1} step={0.01} onChange={(v) => set({ x: v }, "x")} format={(v) => `${Math.round(v * 100)}%`} />
      <Slider label="Up / down position" value={t.y} min={0} max={1} step={0.01} onChange={(v) => set({ y: v }, "y")} format={(v) => `${Math.round(v * 100)}%`} />
      <div className="row gap wrap">
        <Field label="Colour"><input className="color-input" type="color" aria-label="Text colour" value={t.color} onChange={(e) => set({ color: e.target.value.toUpperCase() }, "c")} /></Field>
        <label className="check"><input type="checkbox" checked={t.bold} onChange={(e) => set({ bold: e.target.checked })} />Bold</label>
        <label className="check"><input type="checkbox" checked={t.box} onChange={(e) => set({ box: e.target.checked })} />Dark box behind</label>
      </div>
      {t.box && <Slider label="Box darkness" value={t.box_opacity} min={0} max={1} step={0.05} onChange={(v) => set({ box_opacity: v }, "bo")} format={(v) => `${Math.round(v * 100)}%`} />}
      <div className="grid-2">
        <Slider label="Fade in" value={t.fade_in} min={0} max={3} step={0.1} onChange={(v) => set({ fade_in: v }, "fi")} format={sec} />
        <Slider label="Fade out" value={t.fade_out} min={0} max={3} step={0.1} onChange={(v) => set({ fade_out: v }, "fo")} format={sec} />
      </div>
    </div>
  );
}

function AudioPanel({ ac, a, commit, onDelete }: { ac: AudioClip; a: Asset | undefined; commit: Commit; onDelete: () => void }) {
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
    </div>
  );
}
