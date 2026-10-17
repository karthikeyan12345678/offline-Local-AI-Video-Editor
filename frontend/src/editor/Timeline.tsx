import { useEffect, useLayoutEffect, useRef, useState, type PointerEvent as RPE, type ReactNode } from "react";
import { mediaUrl } from "../lib/api";
import { clamp } from "../lib/format";
import type { Asset, Key, Project } from "../lib/types";
import { audioLength, cutPoints, layerDuration, layout, packLanes } from "./model";
import type { Selection } from "./Inspector";

type Commit = (fn: (p: Project) => Project, key?: string) => void;
interface Props {
  project: Project; asset: (id: string) => Asset | undefined; time: number; onSeek: (t: number) => void;
  sel: Selection; onSelect: (s: Selection) => void; commit: Commit; zoom: number; total: number; onAdd?: () => void; onAddLayer?: () => void;
  onZoom: (z: number) => void; viewportRef?: (el: HTMLDivElement | null) => void;
}

const LABEL_W = 96;
const BLOCK_H = 34;
const PAD = 7;
export const MIN_ZOOM = 4;
export const MAX_ZOOM = 900;

/** Runs `move` for every pointer move until release. `done` receives the final dx and whether the pointer really moved. */
function drag(e: RPE, move: (dx: number, ev: PointerEvent) => void, done?: (dx: number, moved: boolean) => void) {
  e.preventDefault(); e.stopPropagation();
  const x0 = e.clientX;
  let moved = false;
  const mv = (ev: PointerEvent) => { const dx = ev.clientX - x0; if (Math.abs(dx) > 3 || Math.abs(ev.clientY - e.clientY) > 6) moved = true; if (moved) move(dx, ev); };
  const up = (ev: PointerEvent) => { window.removeEventListener("pointermove", mv); window.removeEventListener("pointerup", up); done?.(ev.clientX - x0, moved); };
  window.addEventListener("pointermove", mv);
  window.addEventListener("pointerup", up);
}

type Kind = "text" | "audio" | "draw" | "image" | "layer";
const fmtTick = (s: number) => {
  const m = Math.floor(s / 60), r = s - m * 60;
  return `${m}:${(r < 10 ? "0" : "") + (Number.isInteger(r) ? r.toFixed(0) : r.toFixed(r * 10 % 1 === 0 ? 1 : 2))}`;
};
const STEPS = [0.04, 0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300];

function Row({ label, sub, lanes, lane, onBg, children, className = "", width, onSelect }: { label: string; sub?: string; lanes: number; lane?: string; onBg?: (e: RPE) => void; children: ReactNode; className?: string; width: number; onSelect: (s: Selection) => void }) {
  return (
    <div className={`tl-row ${className}`}>
      <div className="tl-label text-xs w-medium"><span>{label}{sub && <small className="tl-sub">{sub}</small>}</span></div>
      <div className="tl-lane" data-lane={lane} style={{ width, height: lanes * (BLOCK_H + 4) + PAD * 2 - 4 }} onPointerDown={onBg ?? ((e) => { if (e.target === e.currentTarget) onSelect(null); })}>{children}</div>
    </div>
  );
}

export default function Timeline({ project, asset, time, onSeek, sel, onSelect, commit, zoom, total, onAdd, onAddLayer, onZoom, viewportRef }: Props) {
  const { items } = layout(project, asset);
  const [ghost, setGhost] = useState<{ id: string; dx: number } | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const anchor = useRef<{ t: number; px: number } | null>(null);
  const live = useRef({ zoom, onZoom });
  live.current = { zoom, onZoom };

  const layerEnd = Math.max(0, ...project.layers.map((l) => l.start + layerDuration(l, asset(l.asset_id))));
  const textEnd = Math.max(0, ...project.texts.map((t) => t.start + t.duration), ...project.drawings.map((d) => d.start + d.duration), ...project.images.map((d) => d.start + d.duration));
  const audioEnd = Math.max(0, ...project.audio.map((a) => a.start + audioLength(a, asset(a.asset_id))));
  const span = Math.max(total, textEnd, audioEnd, layerEnd, 10) + 5;
  const width = span * zoom;
  const step = STEPS.find((s) => s * zoom >= 76) ?? 300;

  useEffect(() => { viewportRef?.(scrollRef.current); return () => viewportRef?.(null); }, [viewportRef]);

  // Scroll wheel = zoom (around the mouse). Shift or a sideways swipe = scroll left/right. Alt = scroll up/down.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const wheel = (e: WheelEvent) => {
      const box = el.getBoundingClientRect();
      if (e.clientX - box.left < LABEL_W) return; // over the track names: normal scrolling
      if (e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)) { e.preventDefault(); el.scrollLeft += e.shiftKey ? e.deltaY : e.deltaX; return; }
      if (e.altKey) return;
      e.preventDefault();
      const z0 = live.current.zoom;
      const z1 = clamp(z0 * Math.exp(-e.deltaY * 0.0016), MIN_ZOOM, MAX_ZOOM);
      if (Math.abs(z1 - z0) < 1e-6) return;
      const px = e.clientX - box.left;
      anchor.current = { t: (px + el.scrollLeft - LABEL_W) / z0, px };
      live.current.onZoom(z1);
    };
    el.addEventListener("wheel", wheel, { passive: false });
    return () => el.removeEventListener("wheel", wheel);
  }, []);
  // After a zoom, keep the moment under the mouse (or the playhead) where it was.
  useLayoutEffect(() => {
    const el = scrollRef.current, a = anchor.current;
    if (!el || !a) return;
    anchor.current = null;
    el.scrollLeft = Math.max(0, a.t * zoom + LABEL_W - a.px);
  }, [zoom]);

  const seekFrom = (e: RPE) => {
    const box = scrollRef.current!.getBoundingClientRect();
    const at = (ev: { clientX: number }) => clamp((ev.clientX - box.left + scrollRef.current!.scrollLeft - LABEL_W) / zoom, 0, Math.max(total, 0));
    onSeek(at(e));
    const mv = (ev: PointerEvent) => onSeek(at(ev));
    const up = () => { window.removeEventListener("pointermove", mv); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", mv); window.addEventListener("pointerup", up);
  };

  /** Pull a start time onto the playhead or a neighbouring edge when it is within a few pixels. */
  const snapper = (excludeId: string) => {
    const others = { ...project, clips: project.clips, layers: project.layers.filter((l) => l.id !== excludeId), texts: project.texts.filter((l) => l.id !== excludeId), images: project.images.filter((l) => l.id !== excludeId), drawings: project.drawings.filter((l) => l.id !== excludeId) };
    const pts = [...cutPoints(others, asset), time];
    return (start: number, length: number) => {
      const tol = 8 / zoom;
      let best = start, d = tol;
      for (const p of pts) {
        for (const cand of [p, p - length]) { const dd = Math.abs(cand - start); if (dd < d) { d = dd; best = cand; } }
      }
      return Math.max(0, best);
    };
  };

  // ---- video clips
  const moveClip = (e: RPE, id: string, start: number, w: number) => {
    onSelect({ type: "clip", id });
    drag(e, (dx) => setGhost({ id, dx }), (dx, moved) => {
      setGhost(null);
      if (!moved) return;
      const center = start * zoom + dx + w / 2;
      commit((p) => {
        const { items: its } = layout(p, asset);
        const others = its.filter((i) => i.clip.id !== id);
        const to = others.filter((i) => (i.start + i.dur / 2) * zoom < center).length;
        const clip = p.clips.find((c) => c.id === id)!;
        const next = others.map((i) => i.clip);
        next.splice(to, 0, clip);
        return next.every((c, i) => c === p.clips[i]) ? p : { ...p, clips: next };
      });
    });
  };
  const trimClip = (e: RPE, id: string, side: "l" | "r") => {
    const c0 = project.clips.find((c) => c.id === id)!;
    const a = asset(c0.asset_id);
    if (!a) return;
    onSelect({ type: "clip", id });
    const end0 = c0.trim_out > 0 ? Math.min(c0.trim_out, a.duration) : a.duration;
    drag(e, (dx) => {
      commit((p) => ({
        ...p,
        clips: p.clips.map((c) => {
          if (c.id !== id) return c;
          if (a.kind === "image") return side === "r" ? { ...c, image_duration: clamp(c0.image_duration + dx / zoom, 0.3, 120) } : c;
          const ds = (dx / zoom) * c0.speed;
          const editsStart = (side === "l") !== c0.reverse; // reversed clips show their source back to front
          if (editsStart) {
            const sign = side === "l" ? 1 : -1; // right edge of a reversed clip moves the source start backwards
            return { ...c, trim_in: clamp(c0.trim_in + sign * ds, 0, end0 - 0.1) };
          }
          const sign = side === "r" ? 1 : -1;
          const v = clamp(end0 + sign * ds, c0.trim_in + 0.1, a.duration);
          return { ...c, trim_out: v >= a.duration - 0.01 ? 0 : v };
        }),
      }), `${id}:trim`);
    });
  };

  const startOf = (kind: Kind, id: string) => (kind === "layer" ? project.layers.find((t) => t.id === id)!.start : kind === "image" ? project.images.find((t) => t.id === id)!.start : kind === "text" ? project.texts.find((t) => t.id === id)!.start : kind === "draw" ? project.drawings.find((t) => t.id === id)!.start : project.audio.find((t) => t.id === id)!.start);
  const lengthOf = (kind: Kind, id: string) => {
    if (kind === "layer") { const l = project.layers.find((t) => t.id === id)!; return layerDuration(l, asset(l.asset_id)); }
    if (kind === "image") return project.images.find((t) => t.id === id)!.duration;
    if (kind === "text") return project.texts.find((t) => t.id === id)!.duration;
    if (kind === "draw") return project.drawings.find((t) => t.id === id)!.duration;
    const ac = project.audio.find((t) => t.id === id)!;
    return audioLength(ac, asset(ac.asset_id));
  };
  const setStart = (p: Project, kind: Kind, id: string, start: number): Project => {
    const at = <T extends { id: string }>(list: T[], patch: Partial<T>) => list.map((t) => (t.id === id ? { ...t, ...patch } : t));
    return kind === "layer" ? { ...p, layers: at(p.layers, { start }) } : kind === "image" ? { ...p, images: at(p.images, { start }) } : kind === "text" ? { ...p, texts: at(p.texts, { start }) } : kind === "draw" ? { ...p, drawings: at(p.drawings, { start }) } : { ...p, audio: at(p.audio, { start }) };
  };

  // ---- blocks: move = change start (snaps), right edge = change length. Layers can also change track by dragging up or down.
  const moveBlock = (e: RPE, kind: Kind, id: string) => {
    onSelect({ type: kind, id });
    const orig = startOf(kind, id);
    const len = lengthOf(kind, id);
    const snap = snapper(id);
    drag(e, (dx, ev) => {
      const start = snap(Math.max(0, orig + dx / zoom), len);
      let trackPatch: { track: number; behind: boolean } | null = null;
      if (kind === "layer") {
        const lane = document.elementsFromPoint(ev.clientX, ev.clientY).find((n) => (n as HTMLElement).dataset?.lane) as HTMLElement | undefined;
        if (lane) { const [side, n] = (lane.dataset.lane as string).split(":"); trackPatch = { track: clamp(Number(n), 1, 8), behind: side === "b" }; }
      }
      commit((p) => {
        const q = setStart(p, kind, id, start);
        return trackPatch ? { ...q, layers: q.layers.map((l) => (l.id === id ? { ...l, ...trackPatch } : l)) } : q;
      }, `${id}:move`);
    });
  };
  const resizeBlock = (e: RPE, kind: Kind, id: string, side: "l" | "r" = "r") => {
    onSelect({ type: kind, id });
    const snap = snapper(id);
    const s0 = startOf(kind, id), len0 = lengthOf(kind, id);
    const endSnap = (t: number) => snap(t - 0.0001, 0);
    if (kind === "layer") {
      const l0 = project.layers.find((t) => t.id === id)!;
      const a = asset(l0.asset_id);
      if (!a) return;
      drag(e, (dx) => commit((p) => ({ ...p, layers: p.layers.map((l) => {
        if (l.id !== id) return l;
        if (a.kind === "image") {
          if (side === "r") return { ...l, image_duration: Math.max(0.2, endSnap(s0 + len0 + dx / zoom) - s0) };
          const ns = clamp(snap(s0 + dx / zoom, 0), 0, s0 + len0 - 0.2);
          return { ...l, start: ns, image_duration: s0 + len0 - ns };
        }
        const end0 = l0.trim_out > 0 ? Math.min(l0.trim_out, a.duration) : a.duration;
        if (side === "r") {
          const want = clamp(endSnap(s0 + len0 + dx / zoom) - s0, 0.2 / l0.speed, (a.duration - l0.trim_in) / l0.speed);
          const out = l0.trim_in + want * l0.speed;
          return { ...l, trim_out: out >= a.duration - 0.01 ? 0 : out };
        }
        const shift = clamp(snap(s0 + dx / zoom, 0) - s0, -l0.trim_in / l0.speed, (end0 - l0.trim_in) / l0.speed - 0.2);
        return { ...l, start: s0 + shift, trim_in: l0.trim_in + shift * l0.speed };
      }) }), `${id}:len`));
      return;
    }
    if (kind === "image" || kind === "draw" || kind === "text") {
      const key = kind === "image" ? "images" : kind === "draw" ? "drawings" : "texts";
      drag(e, (dx) => commit((p) => ({ ...p, [key]: (p[key] as { id: string; start: number; duration: number }[]).map((t) => {
        if (t.id !== id) return t;
        if (side === "r") return { ...t, duration: Math.max(0.2, endSnap(s0 + len0 + dx / zoom) - s0) };
        const ns = clamp(snap(s0 + dx / zoom, 0), 0, s0 + len0 - 0.2);
        return { ...t, start: ns, duration: s0 + len0 - ns };
      }) }) as Project, `${id}:len`));
      return;
    }
    const ac = project.audio.find((t) => t.id === id)!;
    const a = asset(ac.asset_id);
    if (!a) return;
    const o = audioLength(ac, a);
    drag(e, (dx) => commit((p) => ({ ...p, audio: p.audio.map((t) => {
      if (t.id !== id) return t;
      const want = clamp(o + dx / zoom, 0.2, a.duration - t.trim_in);
      return { ...t, trim_out: want >= a.duration - t.trim_in - 0.01 ? 0 : t.trim_in + want };
    }) }), `${id}:len`));
  };

  const ticks: number[] = [];
  for (let s = 0; s <= span + 1e-6; s += step) ticks.push(Math.round(s * 1000) / 1000);

  // ---- lanes
  const lanesOf = <T extends { id: string; start: number }>(list: T[], len: (t: T) => number) => packLanes(list.map((t) => ({ id: t.id, start: t.start, end: t.start + len(t) })));
  const textLanes = lanesOf(project.texts, (t) => t.duration);
  const drawLanes = lanesOf(project.drawings, (t) => t.duration);
  const picLanes = lanesOf(project.images, (t) => t.duration);
  const audioLanes = lanesOf(project.audio, (t) => audioLength(t, asset(t.asset_id)));
  const frontMax = Math.max(0, ...project.layers.filter((l) => !l.behind).map((l) => l.track));
  const backMax = Math.max(0, ...project.layers.filter((l) => l.behind).map((l) => l.track));
  const frontRows = Array.from({ length: Math.min(8, frontMax + 1) }, (_, i) => Math.min(8, frontMax + 1) - i); // highest on top, plus one empty row to drop into
  const backRows = Array.from({ length: backMax }, (_, i) => i + 1);

  const keysDots = (keys: Key[], start: number, onPick: (t: number) => void) => keys.map((k, i) => (
    <span key={i} className="kf" style={{ left: k.t * zoom - 6 }} title={`Keyframe at ${(start + k.t).toFixed(2)} s`} onPointerDown={(e) => { e.stopPropagation(); onPick(start + k.t); }} />
  ));

  const rp = { width, onSelect };
  const topOf = (k: number) => PAD + k * (BLOCK_H + 4);
  const blockClick = (kind: Kind, id: string) => (e: React.KeyboardEvent) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect({ type: kind, id }); } };

  return (
    <div className="timeline" ref={scrollRef} role="group" aria-label="Timeline. Scroll the mouse wheel to zoom, hold Shift to scroll sideways.">
      <div className="tl-inner" style={{ width: width + LABEL_W }}>
        <div className="tl-row tl-ruler" onPointerDown={seekFrom} role="slider" aria-label="Playhead position" aria-valuemin={0} aria-valuemax={Math.round(total)} aria-valuenow={Math.round(time)} tabIndex={-1}>
          <div className="tl-label" />
          <div className="tl-lane" style={{ width }}>{ticks.map((s) => <span key={s} className="tick text-xs mono" style={{ left: s * zoom }}>{fmtTick(s)}</span>)}</div>
        </div>

        {/* layers drawn on top of the main video: highest first */}
        {frontRows.map((n) => {
          const here = project.layers.filter((l) => !l.behind && l.track === n);
          const packed = lanesOf(here, (l) => layerDuration(l, asset(l.asset_id)));
          return (
            <Row {...rp} key={`f${n}`} label={`Track ${n}`} sub={here.length === 0 ? "empty" : "on top"} lanes={packed.count} lane={`f:${n}`} className="tl-row--layer">
              {here.length === 0 && n === 1 && project.layers.length === 0 && <span className="tl-hint text-xs" style={{ left: 12 }}>Layers: a second video or picture that plays at the same time goes here →</span>}
              {here.length === 0 && n === 1 && onAddLayer && <button type="button" className="tl-add tl-add--layer" aria-label="Add a layer: a second video or picture at the same time" title="Add a layer" style={{ left: project.layers.length === 0 ? 460 : 12 }} onPointerDown={(e) => e.stopPropagation()} onClick={onAddLayer}>+</button>}
              {here.map((l) => {
                const a = asset(l.asset_id);
                const w = Math.max(8, layerDuration(l, a) * zoom);
                const on = sel?.type === "layer" && sel.id === l.id;
                return (
                  <div key={l.id} className={`block block--layer${on ? " block--on" : ""}`} style={{ left: l.start * zoom, width: w, top: topOf(packed.lane[l.id]), height: BLOCK_H, bottom: "auto", backgroundImage: a?.thumb ? `url(${mediaUrl(a.id, "thumb")})` : undefined }}
                    onPointerDown={(e) => moveBlock(e, "layer", l.id)} tabIndex={0} role="button" aria-pressed={on} aria-label={`Layer ${project.layers.indexOf(l) + 1}: ${a?.name ?? "missing"}`} onKeyDown={blockClick("layer", l.id)}>
                    <span className="block-label text-xs truncate">L{project.layers.indexOf(l) + 1} · {l.chroma.enabled ? "🟩 " : ""}{a?.name ?? "Missing file"}</span>
                    {keysDots(l.keys, l.start, (t) => { onSelect({ type: "layer", id: l.id }); onSeek(t); })}
                    <span className="handle handle--l" onPointerDown={(e) => resizeBlock(e, "layer", l.id, "l")} aria-hidden="true" />
                    <span className="handle handle--r" onPointerDown={(e) => resizeBlock(e, "layer", l.id, "r")} aria-hidden="true" />
                  </div>
                );
              })}
            </Row>
          );
        })}

        <div className="tl-row">
          <div className="tl-label text-xs w-medium"><span>Video<small className="tl-sub">main</small></span></div>
          <div className="tl-lane tl-lane--video" style={{ width }} onPointerDown={(e) => { if (e.target === e.currentTarget) { onSelect(null); seekFrom(e); } }}>
            {onAdd && <button type="button" className="tl-add" aria-label="Add media to the timeline" title="Add media" style={{ left: items.reduce((m, it) => Math.max(m, (it.start + it.dur) * zoom), 0) + 12 }} onPointerDown={(e) => e.stopPropagation()} onClick={onAdd}>+</button>}
            {items.map(({ clip, start, dur }, i) => {
              const a = asset(clip.asset_id);
              const w = Math.max(8, dur * zoom);
              const on = sel?.type === "clip" && sel.id === clip.id;
              const dx = ghost?.id === clip.id ? ghost.dx : 0;
              return (
                <div key={clip.id} className={`block block--clip${on ? " block--on" : ""}${dx ? " block--drag" : ""}`} style={{ left: start * zoom + dx, width: w, zIndex: dx ? 5 : i + 1, backgroundImage: a?.thumb ? `url(${mediaUrl(a.id, "thumb")})` : undefined }}
                  onPointerDown={(e) => moveClip(e, clip.id, start, w)} tabIndex={0} role="button" aria-pressed={on} aria-label={`Clip ${i + 1}: ${a?.name ?? "missing media"}`}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect({ type: "clip", id: clip.id }); } }}>
                  <span className="block-label text-xs truncate">{clip.chroma.enabled ? "🟩 " : ""}{a?.name ?? "Missing file"}{clip.speed !== 1 ? ` · ${clip.speed}×` : ""}{clip.reverse ? " · ⟲" : ""}</span>
                  {clip.transition.type !== "none" && i < items.length - 1 && <span className="block-tag text-xs">↔ {clip.transition.type}</span>}
                  <span className="handle handle--l" onPointerDown={(e) => trimClip(e, clip.id, "l")} aria-hidden="true" style={a?.kind === "image" ? { display: "none" } : undefined} />
                  <span className="handle handle--r" onPointerDown={(e) => trimClip(e, clip.id, "r")} aria-hidden="true" />
                </div>
              );
            })}
          </div>
        </div>

        {/* layers placed behind the main video (they show where a green screen was removed) */}
        {backRows.map((n) => {
          const here = project.layers.filter((l) => l.behind && l.track === n);
          const packed = lanesOf(here, (l) => layerDuration(l, asset(l.asset_id)));
          return (
            <Row {...rp} key={`b${n}`} label={`Back ${n}`} sub="behind video" lanes={packed.count} lane={`b:${n}`} className="tl-row--layer">
              {here.map((l) => {
                const a = asset(l.asset_id);
                const on = sel?.type === "layer" && sel.id === l.id;
                return (
                  <div key={l.id} className={`block block--layer block--back${on ? " block--on" : ""}`} style={{ left: l.start * zoom, width: Math.max(8, layerDuration(l, a) * zoom), top: topOf(packed.lane[l.id]), height: BLOCK_H, bottom: "auto", backgroundImage: a?.thumb ? `url(${mediaUrl(a.id, "thumb")})` : undefined }}
                    onPointerDown={(e) => moveBlock(e, "layer", l.id)} tabIndex={0} role="button" aria-pressed={on} aria-label={`Layer ${project.layers.indexOf(l) + 1} (behind): ${a?.name ?? "missing"}`} onKeyDown={blockClick("layer", l.id)}>
                    <span className="block-label text-xs truncate">L{project.layers.indexOf(l) + 1} · {a?.name ?? "Missing file"}</span>
                    {keysDots(l.keys, l.start, (t) => { onSelect({ type: "layer", id: l.id }); onSeek(t); })}
                    <span className="handle handle--l" onPointerDown={(e) => resizeBlock(e, "layer", l.id, "l")} aria-hidden="true" />
                    <span className="handle handle--r" onPointerDown={(e) => resizeBlock(e, "layer", l.id, "r")} aria-hidden="true" />
                  </div>
                );
              })}
            </Row>
          );
        })}

        <Row {...rp} label="Text" lanes={textLanes.count}>
          {project.texts.map((t) => {
            const on = sel?.type === "text" && sel.id === t.id;
            return (
              <div key={t.id} className={`block block--text${on ? " block--on" : ""}`} style={{ left: t.start * zoom, width: Math.max(8, t.duration * zoom), top: topOf(textLanes.lane[t.id]), height: BLOCK_H, bottom: "auto" }} onPointerDown={(e) => moveBlock(e, "text", t.id)} tabIndex={0} role="button" aria-pressed={on} aria-label={`Text: ${t.text}`} onKeyDown={blockClick("text", t.id)}>
                <span className="block-label text-xs truncate">{t.text}</span>
                {keysDots(t.keys, t.start, (x) => { onSelect({ type: "text", id: t.id }); onSeek(x); })}
                <span className="handle handle--l" onPointerDown={(e) => resizeBlock(e, "text", t.id, "l")} aria-hidden="true" />
                <span className="handle handle--r" onPointerDown={(e) => resizeBlock(e, "text", t.id)} aria-hidden="true" />
              </div>
            );
          })}
        </Row>

        <Row {...rp} label="Draw" lanes={drawLanes.count}>
          {project.drawings.map((d) => {
            const on = sel?.type === "draw" && sel.id === d.id;
            return (
              <div key={d.id} className={`block block--draw${on ? " block--on" : ""}`} style={{ left: d.start * zoom, width: Math.max(8, d.duration * zoom), top: topOf(drawLanes.lane[d.id]), height: BLOCK_H, bottom: "auto" }} onPointerDown={(e) => moveBlock(e, "draw", d.id)} tabIndex={0} role="button" aria-pressed={on} aria-label={`Drawing with ${d.shapes.length} shapes`} onKeyDown={blockClick("draw", d.id)}>
                <span className="block-label text-xs truncate">✎ {d.shapes.length} shape{d.shapes.length === 1 ? "" : "s"}</span>
                <span className="handle handle--l" onPointerDown={(e) => resizeBlock(e, "draw", d.id, "l")} aria-hidden="true" />
                <span className="handle handle--r" onPointerDown={(e) => resizeBlock(e, "draw", d.id)} aria-hidden="true" />
              </div>
            );
          })}
        </Row>

        <Row {...rp} label="Picture" lanes={picLanes.count}>
          {project.images.map((im) => {
            const on = sel?.type === "image" && sel.id === im.id;
            return (
              <div key={im.id} className={`block block--image${on ? " block--on" : ""}`} style={{ left: im.start * zoom, width: Math.max(8, im.duration * zoom), top: topOf(picLanes.lane[im.id]), height: BLOCK_H, bottom: "auto" }} onPointerDown={(e) => moveBlock(e, "image", im.id)} tabIndex={0} role="button" aria-pressed={on} aria-label={`Picture: ${asset(im.asset_id)?.name ?? ""}`} onKeyDown={blockClick("image", im.id)}>
                <span className="block-label text-xs truncate">🖼 {asset(im.asset_id)?.name ?? "Picture"}</span>
                {keysDots(im.keys, im.start, (x) => { onSelect({ type: "image", id: im.id }); onSeek(x); })}
                <span className="handle handle--l" onPointerDown={(e) => resizeBlock(e, "image", im.id, "l")} aria-hidden="true" />
                <span className="handle handle--r" onPointerDown={(e) => resizeBlock(e, "image", im.id)} aria-hidden="true" />
              </div>
            );
          })}
        </Row>

        <Row {...rp} label="Audio" lanes={audioLanes.count}>
          {project.audio.map((ac) => {
            const a = asset(ac.asset_id);
            const on = sel?.type === "audio" && sel.id === ac.id;
            return (
              <div key={ac.id} className={`block block--audio${on ? " block--on" : ""}`} style={{ left: ac.start * zoom, width: Math.max(8, audioLength(ac, a) * zoom), top: topOf(audioLanes.lane[ac.id]), height: BLOCK_H, bottom: "auto" }} onPointerDown={(e) => moveBlock(e, "audio", ac.id)} tabIndex={0} role="button" aria-pressed={on} aria-label={`Audio: ${a?.name ?? "missing"}`} onKeyDown={blockClick("audio", ac.id)}>
                <span className="block-label text-xs truncate">{a?.name ?? "Missing file"}</span>
                <span className="handle handle--r" onPointerDown={(e) => resizeBlock(e, "audio", ac.id)} aria-hidden="true" />
              </div>
            );
          })}
        </Row>

        <div className="playhead" style={{ left: LABEL_W + time * zoom }} aria-hidden="true" />
      </div>
    </div>
  );
}
