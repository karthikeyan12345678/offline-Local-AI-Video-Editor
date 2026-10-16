import { useRef, useState, type PointerEvent as RPE } from "react";
import { mediaUrl } from "../lib/api";
import { clamp } from "../lib/format";
import type { Asset, Project } from "../lib/types";
import { audioLength, layout } from "./model";
import type { Selection } from "./Inspector";

type Commit = (fn: (p: Project) => Project, key?: string) => void;
interface Props {
  project: Project; asset: (id: string) => Asset | undefined; time: number; onSeek: (t: number) => void;
  sel: Selection; onSelect: (s: Selection) => void; commit: Commit; zoom: number; total: number; onAdd?: () => void;
}

const LABEL_W = 84;

/** Runs `move` for every pointer move until release. `done` receives the final dx and whether the pointer really moved. */
function drag(e: RPE, move: (dx: number) => void, done?: (dx: number, moved: boolean) => void) {
  e.preventDefault(); e.stopPropagation();
  const x0 = e.clientX;
  let moved = false;
  const mv = (ev: PointerEvent) => { const dx = ev.clientX - x0; if (Math.abs(dx) > 3) moved = true; if (moved) move(dx); };
  const up = (ev: PointerEvent) => { window.removeEventListener("pointermove", mv); window.removeEventListener("pointerup", up); done?.(ev.clientX - x0, moved); };
  window.addEventListener("pointermove", mv);
  window.addEventListener("pointerup", up);
}

export default function Timeline({ project, asset, time, onSeek, sel, onSelect, commit, zoom, total, onAdd }: Props) {
  const { items } = layout(project, asset);
  const [ghost, setGhost] = useState<{ id: string; dx: number } | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const textEnd = Math.max(0, ...project.texts.map((t) => t.start + t.duration), ...project.drawings.map((d) => d.start + d.duration), ...(project.images ?? []).map((d) => d.start + d.duration));
  const audioEnd = Math.max(0, ...project.audio.map((a) => a.start + audioLength(a, asset(a.asset_id))));
  const span = Math.max(total, textEnd, audioEnd, 10) + 5;
  const width = span * zoom;
  const step = zoom >= 120 ? 1 : zoom >= 60 ? 2 : zoom >= 30 ? 5 : 10;

  const seekFrom = (e: RPE) => {
    const box = scrollRef.current!.getBoundingClientRect();
    const at = (ev: { clientX: number }) => clamp((ev.clientX - box.left + scrollRef.current!.scrollLeft - LABEL_W) / zoom, 0, total);
    onSeek(at(e));
    const mv = (ev: PointerEvent) => onSeek(at(ev));
    const up = () => { window.removeEventListener("pointermove", mv); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", mv); window.addEventListener("pointerup", up);
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

  // ---- text + audio blocks (move = change start, right edge = change length)
  const moveBlock = (e: RPE, kind: "text" | "audio" | "draw" | "image", id: string) => {
    onSelect({ type: kind, id });
    const orig = kind === "image" ? project.images.find((t) => t.id === id)!.start : kind === "text" ? project.texts.find((t) => t.id === id)!.start : kind === "draw" ? project.drawings.find((t) => t.id === id)!.start : project.audio.find((t) => t.id === id)!.start;
    drag(e, (dx) => commit((p) => kind === "image"
      ? { ...p, images: p.images.map((t) => (t.id === id ? { ...t, start: Math.max(0, orig + dx / zoom) } : t)) }
      : kind === "text"
      ? { ...p, texts: p.texts.map((t) => (t.id === id ? { ...t, start: Math.max(0, orig + dx / zoom) } : t)) }
      : kind === "draw"
        ? { ...p, drawings: p.drawings.map((t) => (t.id === id ? { ...t, start: Math.max(0, orig + dx / zoom) } : t)) }
        : { ...p, audio: p.audio.map((t) => (t.id === id ? { ...t, start: Math.max(0, orig + dx / zoom) } : t)) }, `${id}:move`));
  };
  const resizeBlock = (e: RPE, kind: "text" | "audio" | "draw" | "image", id: string) => {
    onSelect({ type: kind, id });
    if (kind === "image") {
      const o = project.images.find((t) => t.id === id)!.duration;
      drag(e, (dx) => commit((p) => ({ ...p, images: p.images.map((t) => (t.id === id ? { ...t, duration: Math.max(0.2, o + dx / zoom) } : t)) }), `${id}:len`));
    } else if (kind === "draw") {
      const o = project.drawings.find((t) => t.id === id)!.duration;
      drag(e, (dx) => commit((p) => ({ ...p, drawings: p.drawings.map((t) => (t.id === id ? { ...t, duration: Math.max(0.2, o + dx / zoom) } : t)) }), `${id}:len`));
    } else if (kind === "text") {
      const o = project.texts.find((t) => t.id === id)!.duration;
      drag(e, (dx) => commit((p) => ({ ...p, texts: p.texts.map((t) => (t.id === id ? { ...t, duration: Math.max(0.2, o + dx / zoom) } : t)) }), `${id}:len`));
    } else {
      const ac = project.audio.find((t) => t.id === id)!;
      const a = asset(ac.asset_id);
      if (!a) return;
      const o = audioLength(ac, a);
      drag(e, (dx) => commit((p) => ({ ...p, audio: p.audio.map((t) => {
        if (t.id !== id) return t;
        const want = clamp(o + dx / zoom, 0.2, a.duration - t.trim_in);
        return { ...t, trim_out: want >= a.duration - t.trim_in - 0.01 ? 0 : t.trim_in + want };
      }) }), `${id}:len`));
    }
  };

  const ticks: number[] = [];
  for (let s = 0; s <= span; s += step) ticks.push(s);

  return (
    <div className="timeline" ref={scrollRef} role="group" aria-label="Timeline">
      <div className="tl-inner" style={{ width: width + LABEL_W }}>
        <div className="tl-row tl-ruler" onPointerDown={seekFrom} role="slider" aria-label="Playhead position" aria-valuemin={0} aria-valuemax={Math.round(total)} aria-valuenow={Math.round(time)} tabIndex={-1}>
          <div className="tl-label" />
          <div className="tl-lane" style={{ width }}>{ticks.map((s) => <span key={s} className="tick text-xs mono" style={{ left: s * zoom }}>{Math.floor(s / 60)}:{String(s % 60).padStart(2, "0")}</span>)}</div>
        </div>

        <div className="tl-row">
          <div className="tl-label text-xs w-medium">Video</div>
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
                  <span className="block-label text-xs truncate">{a?.name ?? "Missing file"}{clip.speed !== 1 ? ` · ${clip.speed}×` : ""}{clip.reverse ? " · ⟲" : ""}</span>
                  {clip.transition.type !== "none" && i < items.length - 1 && <span className="block-tag text-xs">↔ {clip.transition.type}</span>}
                  <span className="handle handle--l" onPointerDown={(e) => trimClip(e, clip.id, "l")} aria-hidden="true" style={a?.kind === "image" ? { display: "none" } : undefined} />
                  <span className="handle handle--r" onPointerDown={(e) => trimClip(e, clip.id, "r")} aria-hidden="true" />
                </div>
              );
            })}
          </div>
        </div>

        <div className="tl-row">
          <div className="tl-label text-xs w-medium">Text</div>
          <div className="tl-lane" style={{ width }} onPointerDown={(e) => { if (e.target === e.currentTarget) onSelect(null); }}>
            {project.texts.map((t) => {
              const on = sel?.type === "text" && sel.id === t.id;
              return (
                <div key={t.id} className={`block block--text${on ? " block--on" : ""}`} style={{ left: t.start * zoom, width: Math.max(8, t.duration * zoom) }} onPointerDown={(e) => moveBlock(e, "text", t.id)} tabIndex={0} role="button" aria-pressed={on} aria-label={`Text: ${t.text}`}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect({ type: "text", id: t.id }); } }}>
                  <span className="block-label text-xs truncate">{t.text}</span>
                  <span className="handle handle--r" onPointerDown={(e) => resizeBlock(e, "text", t.id)} aria-hidden="true" />
                </div>
              );
            })}
          </div>
        </div>

        <div className="tl-row">
          <div className="tl-label text-xs w-medium">Draw</div>
          <div className="tl-lane" style={{ width }} onPointerDown={(e) => { if (e.target === e.currentTarget) onSelect(null); }}>
            {project.drawings.map((d) => {
              const on = sel?.type === "draw" && sel.id === d.id;
              return (
                <div key={d.id} className={`block block--draw${on ? " block--on" : ""}`} style={{ left: d.start * zoom, width: Math.max(8, d.duration * zoom) }} onPointerDown={(e) => moveBlock(e, "draw", d.id)} tabIndex={0} role="button" aria-pressed={on} aria-label={`Drawing with ${d.shapes.length} shapes`}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect({ type: "draw", id: d.id }); } }}>
                  <span className="block-label text-xs truncate">✎ {d.shapes.length} shape{d.shapes.length === 1 ? "" : "s"}</span>
                  <span className="handle handle--r" onPointerDown={(e) => resizeBlock(e, "draw", d.id)} aria-hidden="true" />
                </div>
              );
            })}
          </div>
        </div>

        <div className="tl-row">
          <div className="tl-label text-xs w-medium">Picture</div>
          <div className="tl-lane" style={{ width }} onPointerDown={(e) => { if (e.target === e.currentTarget) onSelect(null); }}>
            {(project.images ?? []).map((im) => {
              const on = sel?.type === "image" && sel.id === im.id;
              return (
                <div key={im.id} className={`block block--image${on ? " block--on" : ""}`} style={{ left: im.start * zoom, width: Math.max(8, im.duration * zoom) }} onPointerDown={(e) => moveBlock(e, "image", im.id)} tabIndex={0} role="button" aria-pressed={on} aria-label={`Picture: ${asset(im.asset_id)?.name ?? ""}`}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect({ type: "image", id: im.id }); } }}>
                  <span className="block-label text-xs truncate">🖼 {asset(im.asset_id)?.name ?? "Picture"}</span>
                  <span className="handle handle--r" onPointerDown={(e) => resizeBlock(e, "image", im.id)} aria-hidden="true" />
                </div>
              );
            })}
          </div>
        </div>

        <div className="tl-row">
          <div className="tl-label text-xs w-medium">Audio</div>
          <div className="tl-lane" style={{ width }} onPointerDown={(e) => { if (e.target === e.currentTarget) onSelect(null); }}>
            {project.audio.map((ac) => {
              const a = asset(ac.asset_id);
              const on = sel?.type === "audio" && sel.id === ac.id;
              return (
                <div key={ac.id} className={`block block--audio${on ? " block--on" : ""}`} style={{ left: ac.start * zoom, width: Math.max(8, audioLength(ac, a) * zoom) }} onPointerDown={(e) => moveBlock(e, "audio", ac.id)} tabIndex={0} role="button" aria-pressed={on} aria-label={`Audio: ${a?.name ?? "missing"}`}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect({ type: "audio", id: ac.id }); } }}>
                  <span className="block-label text-xs truncate">{a?.name ?? "Missing file"}</span>
                  <span className="handle handle--r" onPointerDown={(e) => resizeBlock(e, "audio", ac.id)} aria-hidden="true" />
                </div>
              );
            })}
          </div>
        </div>

        <div className="playhead" style={{ left: LABEL_W + time * zoom }} aria-hidden="true" />
      </div>
    </div>
  );
}
