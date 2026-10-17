import { useState } from "react";
import { groupBy } from "./catalog";
import { Button, Field, Slider, Tabs, I } from "../ds";
import type { Asset, Chroma, Ease, Key, Layer, Project } from "../lib/types";
import { useCatalog } from "./catalog";
import { layerDuration, layerPose, upsertKey, type Pose } from "./model";

type Commit = (fn: (p: Project) => Project, key?: string) => void;
const pctf = (v: number) => `${Math.round(v * 100)}%`;
const sec = (v: number) => `${v.toFixed(2)} s`;

/** Remove a green or blue screen so whatever is behind shows through. Works on a clip or on a layer. */
export function ChromaControls({ chroma, onChange, onAddBackground }: { chroma: Chroma; onChange: (c: Chroma, key?: string) => void; onAddBackground?: () => void }) {
  return (
    <div className="stack gap">
      <label className="check"><input type="checkbox" checked={chroma.enabled} onChange={(e) => onChange({ ...chroma, enabled: e.target.checked })} />Remove the green or blue screen</label>
      <p className="hint">Use this for a person filmed in front of a green or blue sheet. The sheet becomes see-through, so a picture or video behind it shows instead.</p>
      {chroma.enabled && (
        <>
          <Field label="Colour to remove">
            <div className="row gap center-v wrap">
              <Button small variant="secondary" active={chroma.color === "#00B140"} onClick={() => onChange({ ...chroma, color: "#00B140" })}>Green screen</Button>
              <Button small variant="secondary" active={chroma.color === "#0047BB"} onClick={() => onChange({ ...chroma, color: "#0047BB" })}>Blue screen</Button>
              <input className="color-input" type="color" aria-label="Any other colour to remove" value={chroma.color} onChange={(e) => onChange({ ...chroma, color: e.target.value.toUpperCase() }, "cc")} />
            </div>
          </Field>
          <Slider label="How much to remove" value={chroma.similarity} min={0.05} max={0.8} step={0.01} onChange={(v) => onChange({ ...chroma, similarity: v }, "cs")} format={pctf} />
          <Slider label="Soft edges" value={chroma.blend} min={0} max={0.5} step={0.01} onChange={(v) => onChange({ ...chroma, blend: v }, "cb")} format={pctf} />
          <label className="check"><input type="checkbox" checked={chroma.spill} onChange={(e) => onChange({ ...chroma, spill: e.target.checked })} />Clean the green or blue glow left on hair and edges</label>
          <p className="hint">If green is still showing, raise <b>How much to remove</b>. If the person starts to disappear, lower it. The preview is close; the exported video is exact.</p>
          {onAddBackground && <Button variant="secondary" small icon={I.image} onClick={onAddBackground}>Choose a background to show behind</Button>}
        </>
      )}
    </div>
  );
}

const EASES: { id: Ease; label: string }[] = [{ id: "smooth", label: "Smooth" }, { id: "linear", label: "Straight" }, { id: "hold", label: "Jump" }];

/** Keyframes: remember where something is at one moment; add two or more and it glides between them. */
export function KeyframeControls({ keys, start, length, time, pose, onSeek, onChange, what }: {
  keys: Key[]; start: number; length: number; time: number; pose: Pose; onSeek: (t: number) => void; onChange: (keys: Key[]) => void; what: string;
}) {
  const sorted = [...keys].sort((a, b) => a.t - b.t);
  const rel = time - start;
  const inside = rel >= -0.001 && rel <= length + 0.001;
  const near = sorted.find((k) => Math.abs(k.t - rel) < 0.02);
  const prev = [...sorted].reverse().find((k) => k.t < rel - 0.02);
  const next = sorted.find((k) => k.t > rel + 0.02);
  return (
    <div className="stack gap">
      <p className="text-sm">A <b>keyframe</b> remembers where {what} is at one moment. Add two or more, and it glides from one to the next by itself.</p>
      <ol className="steps-mini text-sm">
        <li>Move the red playhead to a moment.</li>
        <li>Press <b>◆ Add keyframe</b>.</li>
        <li>Move the playhead, then <b>drag it in the preview</b> to a new place. A new keyframe is made for you.</li>
      </ol>
      <div className="row gap wrap">
        <Button small disabled={!inside} onClick={() => onChange(upsertKey(keys, Math.max(0, Math.min(length, rel)), pose))}>{near ? "◆ Update keyframe here" : "◆ Add keyframe here"}</Button>
        <Button small variant="secondary" disabled={!prev} onClick={() => prev && onSeek(start + prev.t)} label="Go to the keyframe before this moment">◀ Previous</Button>
        <Button small variant="secondary" disabled={!next} onClick={() => next && onSeek(start + next.t)} label="Go to the keyframe after this moment">Next ▶</Button>
      </div>
      {!inside && <p className="hint">The playhead is outside this item. Move it inside to add a keyframe.</p>}
      {sorted.length === 0 ? <p className="hint">No keyframes yet. It stays where you put it.</p> : (
        <ul className="kf-list">
          {sorted.map((k, i) => (
            <li key={i} className={Math.abs(k.t - rel) < 0.02 ? "on" : ""}>
              <button type="button" className="linklike mono" onClick={() => onSeek(start + k.t)} title="Go to this keyframe">{(start + k.t).toFixed(2)} s</button>
              <select className="select select--sm" aria-label="How it moves to the next keyframe" value={k.ease} onChange={(e) => onChange(sorted.map((q) => (q === k ? { ...q, ease: e.target.value as Ease } : q)))}>
                {EASES.map((e) => <option key={e.id} value={e.id}>{e.label}</option>)}
              </select>
              <Button variant="ghost" small icon={I.trash} label="Delete this keyframe" onClick={() => onChange(sorted.filter((q) => q !== k))} />
            </li>
          ))}
        </ul>
      )}
      {sorted.length > 0 && <Button variant="secondary" small onClick={() => onChange([])}>Remove all keyframes</Button>}
    </div>
  );
}

export function LayerPanel({ layer, index, a, time, commit, onDelete, onSeek, onAddBackground }: {
  layer: Layer; index: number; a: Asset | undefined; time: number; commit: Commit; onDelete: () => void; onSeek: (t: number) => void; onAddBackground: () => void;
}) {
  const [tab, setTab] = useState<"place" | "motion" | "screen" | "look" | "sound">("place");
  const cat = useCatalog();
  const set = (patch: Partial<Layer>, key?: string) => commit((p) => ({ ...p, layers: p.layers.map((l) => (l.id === layer.id ? { ...l, ...patch } : l)) }), key ? `${layer.id}:${key}` : undefined);
  const isImage = a?.kind === "image";
  const len = layerDuration(layer, a);
  const srcLen = a?.duration ?? 0;
  const pose = layerPose(layer, time);
  const keyed = layer.keys.length > 0;
  const adj = (patch: Partial<Layer["adjust"]>, key: string) => set({ adjust: { ...layer.adjust, ...patch } }, key);
  return (
    <div className="stack gap">
      <div className="row between gap"><h3 className="truncate">Layer {index + 1}: {a?.name ?? "missing file"}</h3><Button variant="ghost" small icon={I.trash} label="Delete layer" onClick={onDelete} /></div>
      <Tabs label="Layer settings" value={tab} onChange={setTab} options={[{ id: "place", label: "Place" }, { id: "motion", label: "Motion ◆" }, { id: "screen", label: "Green screen" }, { id: "look", label: "Look" }, { id: "sound", label: "Sound", disabled: isImage || !a?.has_audio }]} />
      {tab === "place" && (
        <>
          <p className="hint">Drag the layer in the preview to move it. Drag its corner to resize.{keyed ? " It has keyframes, so moving it now changes the keyframe at the playhead." : ""}</p>
          <div className="row gap wrap">
            <Button small variant="secondary" onClick={() => set({ x: 0.5, y: 0.5, size: 1, keys: [] })}>Fill the screen</Button>
            <Button small variant="secondary" onClick={() => set({ x: 0.8, y: 0.78, size: 0.3, keys: [] })}>Small corner</Button>
            <Button small variant="secondary" onClick={() => set({ x: 0.5, y: 0.5, size: 0.5, keys: [] })}>Middle</Button>
          </div>
          <Slider label="Left ↔ right" value={keyed ? pose.x : layer.x} min={-0.2} max={1.2} step={0.005} disabled={keyed} onChange={(v) => set({ x: v }, "x")} format={pctf} />
          <Slider label="Up ↕ down" value={keyed ? pose.y : layer.y} min={-0.2} max={1.2} step={0.005} disabled={keyed} onChange={(v) => set({ y: v }, "y")} format={pctf} />
          <Slider label="Size" value={keyed ? pose.size : layer.size} min={0.05} max={2} step={0.005} disabled={keyed} onChange={(v) => set({ size: v }, "z")} format={pctf} />
          <Slider label="Turn" value={keyed ? pose.rotation : layer.rotation} min={-180} max={180} step={1} disabled={keyed} onChange={(v) => set({ rotation: v }, "r")} format={(v) => `${Math.round(v)}°`} />
          <Slider label="See-through" value={1 - (keyed ? pose.opacity : layer.opacity)} min={0} max={0.95} step={0.05} disabled={keyed} onChange={(v) => set({ opacity: 1 - v }, "op")} format={pctf} />
          {keyed && <p className="hint">These sliders are locked while keyframes control this layer. Use the <b>Motion ◆</b> tab.</p>}
          <Field label="Order" hint="A higher layer number sits on top of a lower one.">
            <div className="grid-2">
              <select className="select" aria-label="In front of or behind the main video" value={layer.behind ? "back" : "front"} onChange={(e) => set({ behind: e.target.value === "back" })}>
                <option value="front">In front of the video</option><option value="back">Behind the video</option>
              </select>
              <select className="select" aria-label="Layer number" value={layer.track} onChange={(e) => set({ track: Number(e.target.value) })}>
                {[1, 2, 3, 4, 5, 6, 7, 8].map((n) => <option key={n} value={n}>Layer {n}</option>)}
              </select>
            </div>
          </Field>
          {layer.behind && <p className="hint">Behind the video you only see it where the main video is see-through (after removing a green screen from it).</p>}
          <div className="grid-2">
            <Field label="Appears at (s)" htmlFor="ls"><input id="ls" className="input" type="number" min={0} step={0.1} value={Number(layer.start.toFixed(2))} onChange={(e) => set({ start: Math.max(0, Number(e.target.value) || 0) }, "s")} /></Field>
            {isImage
              ? <Field label="Stays for (s)" htmlFor="ld"><input id="ld" className="input" type="number" min={0.2} step={0.1} value={Number(layer.image_duration.toFixed(2))} onChange={(e) => set({ image_duration: Math.max(0.2, Number(e.target.value) || 0.2) }, "d")} /></Field>
              : <Field label="Plays for (s)" hint={`File is ${srcLen.toFixed(1)} s`}><input className="input" type="number" readOnly value={Number(len.toFixed(2))} aria-label="Length on the timeline" /></Field>}
          </div>
          {!isImage && (
            <>
              <div className="grid-2">
                <Field label="Start in file (s)" htmlFor="lti"><input id="lti" className="input" type="number" min={0} max={srcLen} step={0.1} value={Number(layer.trim_in.toFixed(2))} onChange={(e) => set({ trim_in: Math.max(0, Math.min(Number(e.target.value) || 0, (layer.trim_out || srcLen) - 0.1)) }, "ti")} /></Field>
                <Field label="End in file (s)" htmlFor="lto"><input id="lto" className="input" type="number" min={0} max={srcLen} step={0.1} value={Number((layer.trim_out || srcLen).toFixed(2))} onChange={(e) => { const v = Number(e.target.value) || 0; set({ trim_out: v >= srcLen - 0.01 ? 0 : Math.max(layer.trim_in + 0.1, v) }, "to"); }} /></Field>
              </div>
              <Slider label="Speed" value={layer.speed} min={0.25} max={4} step={0.05} onChange={(v) => set({ speed: v }, "sp")} format={(v) => `${v.toFixed(2)}×`} />
            </>
          )}
          <Slider label="Fade in" value={layer.fade_in} min={0} max={5} step={0.1} onChange={(v) => set({ fade_in: v }, "fi")} format={sec} />
          <Slider label="Fade out" value={layer.fade_out} min={0} max={5} step={0.1} onChange={(v) => set({ fade_out: v }, "fo")} format={sec} />
        </>
      )}
      {tab === "motion" && <KeyframeControls what="this layer and how it looks" keys={layer.keys} start={layer.start} length={len} time={time} pose={pose} onSeek={onSeek} onChange={(keys) => set({ keys })} />}
      {tab === "screen" && <ChromaControls chroma={layer.chroma} onChange={(chroma, key) => set({ chroma }, key)} />}
      {tab === "look" && (
        <>
          <Field label="Colour look" htmlFor="llk">
            <select id="llk" className="select" value={layer.preset} onChange={(e) => set({ preset: e.target.value })}>
              {groupBy(cat.looks).map(([g, list]) => <optgroup key={g} label={g}>{list.map((l) => <option key={l.id} value={l.id}>{l.label}</option>)}</optgroup>)}
            </select>
          </Field>
          <Slider label="Brightness" value={layer.adjust.brightness} min={-100} max={100} onChange={(v) => adj({ brightness: v }, "b")} format={(v) => `${Math.round(v)}`} />
          <Slider label="Contrast" value={layer.adjust.contrast} min={-100} max={100} onChange={(v) => adj({ contrast: v }, "c")} format={(v) => `${Math.round(v)}`} />
          <Slider label="Colour strength" value={layer.adjust.saturation} min={-100} max={100} onChange={(v) => adj({ saturation: v }, "s")} format={(v) => `${Math.round(v)}`} />
          <Slider label="Blur" value={layer.blur} min={0} max={30} step={0.5} onChange={(v) => set({ blur: v }, "bl")} format={(v) => v.toFixed(1)} />
          <div className="row between"><h3>Effects</h3><span className="text-xs">{layer.effects.length}/4</span></div>
          {layer.effects.map((e, i) => (
            <div key={i} className="fx-row">
              <div className="row gap center-v">
                <select className="select" aria-label={`Effect ${i + 1}`} value={e.type} onChange={(ev) => set({ effects: layer.effects.map((x, j) => (j === i ? { ...x, type: ev.target.value } : x)) })}>
                  {groupBy(cat.effects).map(([g, list]) => <optgroup key={g} label={g}>{list.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}</optgroup>)}
                </select>
                <Button variant="ghost" small icon={I.trash} label="Remove effect" onClick={() => set({ effects: layer.effects.filter((_, j) => j !== i) })} />
              </div>
              <Slider label="Amount" value={e.amount} min={0} max={1} step={0.05} onChange={(v) => set({ effects: layer.effects.map((x, j) => (j === i ? { ...x, amount: v } : x)) }, `lfx${i}`)} format={pctf} />
            </div>
          ))}
          {layer.effects.length < 4 && cat.effects.length > 0 && <Button variant="secondary" small icon={I.plus} onClick={() => set({ effects: [...layer.effects, { type: cat.effects[0].id, amount: 0.5 }] })}>Add an effect</Button>}
          <h3>Shape</h3>
          <Field label="Cut into a shape" htmlFor="lmk" hint="Show only a circle, heart, star… of this layer.">
            <select id="lmk" className="select" value={layer.mask} onChange={(e) => set({ mask: e.target.value })}>
              {cat.masks.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
            </select>
          </Field>
          {layer.mask !== "none" && (
            <>
              <Slider label="Soft edge" value={layer.mask_feather} min={0} max={1} step={0.02} onChange={(v) => set({ mask_feather: v }, "mf")} format={pctf} />
              <label className="check"><input type="checkbox" checked={layer.mask_invert} onChange={(e) => set({ mask_invert: e.target.checked })} />Flip it (keep what is outside the shape)</label>
              <p className="hint">The soft edge shows in the exported video; the preview always shows a sharp edge.</p>
            </>
          )}
        </>
      )}
      {tab === "sound" && (
        <>
          <label className="check"><input type="checkbox" checked={layer.muted} onChange={(e) => set({ muted: e.target.checked })} />Mute this layer’s sound</label>
          <Slider label="Volume" value={layer.volume} min={0} max={2} step={0.05} disabled={layer.muted} onChange={(v) => set({ volume: v }, "vol")} format={(v) => `${Math.round(v * 100)}%`} />
        </>
      )}
      <ChangeNote onAddBackground={layer.chroma.enabled ? onAddBackground : undefined} />
    </div>
  );
}

function ChangeNote({ onAddBackground }: { onAddBackground?: () => void }) {
  if (!onAddBackground) return null;
  return <Button variant="secondary" small icon={I.image} onClick={onAddBackground}>Add a background behind everything</Button>;
}
