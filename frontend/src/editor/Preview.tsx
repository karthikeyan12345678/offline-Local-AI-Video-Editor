import { useEffect, useRef } from "react";
import { fontFileUrl, mediaUrl } from "../lib/api";
import type { Asset, Clip, Project, TextOverlay } from "../lib/types";
import { DrawCapture, DrawingsLayer, type PenSettings } from "./Draw";
import type { Shape } from "../lib/types";
import { cssFilter, cssTransform, itemPose, layout, objectFit, type Placed, type Pose } from "./model";
import { KeyedVideo, LayerView } from "./Layers";
import type { Selection } from "./Inspector";

interface Props {
  project: Project; asset: (id: string) => Asset | undefined; time: number; playing: boolean;
  onTick: (t: number) => void; onEnd: () => void;
  pen?: PenSettings | null; editingId?: string | null; onShape?: (s: Shape) => void;
  sel?: Selection; onSelect?: (s: Selection) => void; onPose?: (kind: "layer" | "text" | "image", id: string, patch: Partial<Pose>) => void;
}


const clamp01 = (v: number) => Math.min(1, Math.max(0, v));
const easeOut = (p: number) => 1 - Math.pow(1 - p, 3);

/** Where to place the video so a window that follows a person fills the frame (same maths as the renderer). */
function followBox(c: Clip, a: Asset, canvas: { width: number; height: number }, srcTime: number): { w: number; h: number; x0: number; y0: number } | null {
  const f = c.follow;
  if (!f || f.keys.length === 0 || c.rotate !== 0 || !a.width || !a.height) return null;
  const keys = f.keys;
  let cx = keys[0][1], cy = keys[0][2];
  if (srcTime >= keys[keys.length - 1][0]) { cx = keys[keys.length - 1][1]; cy = keys[keys.length - 1][2]; }
  else if (srcTime > keys[0][0]) {
    let lo = 0, hi = keys.length - 1;
    while (hi - lo > 1) { const m = (lo + hi) >> 1; if (keys[m][0] <= srcTime) lo = m; else hi = m; }
    const k = (srcTime - keys[lo][0]) / Math.max(1e-6, keys[hi][0] - keys[lo][0]);
    cx = keys[lo][1] + (keys[hi][1] - keys[lo][1]) * k; cy = keys[lo][2] + (keys[hi][2] - keys[lo][2]) * k;
  }
  if (c.flip_h) cx = 1 - cx;
  if (c.flip_v) cy = 1 - cy;
  const A = canvas.width / canvas.height, S = a.width / a.height;
  let w = S > A ? A / S : 1, h = S > A ? 1 : S / A;
  w /= f.zoom; h /= f.zoom;
  return { w, h, x0: Math.min(1 - w, Math.max(0, cx - w / 2)), y0: Math.min(1 - h, Math.max(0, cy - h / 2)) };
}

const fontCss = (fonts: string[]) => fonts.map((id) =>
  `@font-face{font-family:"ltx-${id}";font-weight:400;src:url("${fontFileUrl(id, false)}")}@font-face{font-family:"ltx-${id}";font-weight:700;src:url("${fontFileUrl(id, true)}")}`).join("");

function textNode(t: TextOverlay, time: number, drag?: { on: boolean; start: (e: React.PointerEvent) => void }) {
  const pose = itemPose(t, time);
  const inP = t.anim_in !== "none" && t.fade_in > 0 ? clamp01((time - t.start) / t.fade_in) : 1;
  const outP = t.anim_out !== "none" && t.fade_out > 0 ? clamp01((time - (t.start + t.duration - t.fade_out)) / t.fade_out) : 0;
  const ei = easeOut(inP), eo = outP * outP * outP;
  let dx = 0, dy = 0, scale = 1, alpha = 1, clip: string | undefined;
  const fadeIn = ["fade", "slide_up", "slide_down", "slide_left", "slide_right", "zoom"].includes(t.anim_in);
  const fadeOut = ["fade", "slide_up", "slide_down", "slide_left", "slide_right", "zoom"].includes(t.anim_out);
  if (fadeIn) alpha *= inP;
  if (fadeOut) alpha *= 1 - outP;
  if (t.anim_in === "slide_up") dy += 9 * (1 - ei); else if (t.anim_in === "slide_down") dy -= 9 * (1 - ei);
  else if (t.anim_in === "slide_left") dx += 12 * (1 - ei); else if (t.anim_in === "slide_right") dx -= 12 * (1 - ei);
  else if (t.anim_in === "zoom") scale *= 0.6 + 0.4 * ei;
  else if (t.anim_in === "pop") scale *= 1 + 2.70158 * Math.pow(inP - 1, 3) + 1.70158 * Math.pow(inP - 1, 2);
  else if (t.anim_in === "reveal") clip = `inset(0 ${(1 - inP) * 100}% 0 0)`;
  else if (t.anim_in === "bounce") { const b = (x: number) => (x < 0.363636 ? 7.5625 * x * x : x < 0.727273 ? 7.5625 * Math.pow(x - 0.545455, 2) + 0.75 : x < 0.909091 ? 7.5625 * Math.pow(x - 0.818182, 2) + 0.9375 : 7.5625 * Math.pow(x - 0.954545, 2) + 0.984375); dy -= 28 * (1 - b(inP)); alpha *= clamp01(inP / 0.4); }
  else if (t.anim_in === "typewriter") { const n = Math.max(1, ...t.text.split("\n").map((l) => l.length)); clip = `inset(0 ${(1 - Math.floor(inP * n) / n) * 100}% 0 0)`; }
  else if (t.anim_in === "flicker" && inP < 1) alpha *= Math.sin(time * 113) * Math.sin(time * 37) + inP * 1.7 - 0.85 > 0 ? 1 : 0;
  if (t.anim_out === "slide_up") dy -= 9 * eo; else if (t.anim_out === "slide_down") dy += 9 * eo;
  else if (t.anim_out === "slide_left") dx -= 12 * eo; else if (t.anim_out === "slide_right") dx += 12 * eo;
  else if (t.anim_out === "zoom") scale *= 1 + 0.35 * eo;
  else if (t.anim_out === "drop") { dy += 22 * outP * outP; alpha *= 1 - outP; }
  else if (t.anim_out === "flicker" && outP > 0) alpha *= Math.sin(time * 113) * Math.sin(time * 37) + 0.85 - outP * 1.7 > 0 ? 1 : 0;

  const fam = t.font ? `"ltx-${t.font}", ` : "";
  const em = (v: number) => `${v}em`;
  const shadows: string[] = [];
  if (t.glow > 0) { const r = 0.12 + 0.3 * t.glow; shadows.push(`0 0 ${em(r)} ${t.glow_color}`, `0 0 ${em(r * 2)} ${t.glow_color}`); }
  if (t.shadow > 0) { const o = 0.04 + 0.06 * t.shadow; shadows.push(`${em(o)} ${em(o)} ${em(0.03 + 0.08 * t.shadow)} ${t.shadow_color}`); }
  const grad = t.color2 ? { backgroundImage: `linear-gradient(${t.color}, ${t.color2})`, WebkitBackgroundClip: "text", backgroundClip: "text", color: "transparent", WebkitTextFillColor: "transparent" } : { color: t.color };
  const inner: React.CSSProperties = {
    fontFamily: `${fam}"Noto Sans Tamil", "Nirmala UI", system-ui, sans-serif`, fontWeight: t.bold ? 700 : 400, fontStyle: t.italic ? "italic" : "normal",
    textTransform: t.uppercase ? "uppercase" : "none", letterSpacing: `${t.letter_spacing}em`, lineHeight: t.line_spacing / 1.25 * 1.2, textAlign: t.align,
    textShadow: shadows.join(", ") || undefined, ...grad,
    ...(t.stroke > 0 && !t.color2 ? { WebkitTextStroke: `${(t.stroke / 100) * 2}em ${t.stroke_color}`, paintOrder: "stroke fill" as const } : {}),
  };
  const box = t.box && t.box_opacity > 0;
  const hex = t.box_color.replace("#", "");
  const boxBg = box ? `rgba(${parseInt(hex.slice(0, 2), 16)},${parseInt(hex.slice(2, 4), 16)},${parseInt(hex.slice(4, 6), 16)},${t.box_opacity})` : "transparent";
  return (
    <div key={t.id} className={`stage-text${drag?.on ? " stage-text--live" : ""}`} onPointerDown={drag?.on ? drag.start : undefined} style={{
      left: `${pose.x * 100}%`, top: `${pose.y * 100}%`, fontSize: `${t.size}cqh`, background: boxBg, opacity: alpha * t.opacity, clipPath: clip, ...(drag?.on ? { pointerEvents: "auto" as const, cursor: "move" } : {}),
      transform: `translate(calc(-50% + ${dx}cqw), calc(-50% + ${dy}cqh)) rotate(${t.rotation}deg) scale(${Math.max(0, scale)})`,
    }}>{t.color2 && t.stroke > 0 ? <span style={{ position: "relative", display: "inline-block" }}><span aria-hidden style={{ ...inner, position: "absolute", inset: 0, backgroundImage: "none", WebkitTextFillColor: t.stroke_color, color: t.stroke_color, WebkitTextStroke: `${(t.stroke / 100) * 2}em ${t.stroke_color}` }}>{t.text}</span><span style={{ ...inner, position: "relative" }}>{t.text}</span></span> : <span style={inner}>{t.text}</span>}</div>
  );
}

/**
 * Live preview: plays the original files directly and approximates colour effects with CSS.
 * Blur, sharpen, denoise, vignette and transitions are only exact in a rendered preview.
 */
export default function Preview({ project, asset, time, playing, onTick, onEnd, pen = null, editingId = null, onShape, sel = null, onSelect, onPose }: Props) {
  const { items, total } = layout(project, asset);
  const videoRef = useRef<HTMLVideoElement>(null);
  const audioRefs = useRef(new Map<string, HTMLAudioElement>());
  const timeRef = useRef(time);
  timeRef.current = time;
  const live = useRef({ items, total, project, asset });
  live.current = { items, total, project, asset };

  const active: Placed | undefined = [...items].reverse().find((i) => time >= i.start - 1e-6 && time < i.start + i.dur) ?? (time >= total ? items[items.length - 1] : undefined);
  const a = active ? asset(active.clip.asset_id) : undefined;
  const isVideo = a?.kind === "video";
  const containerRef = useRef<HTMLDivElement>(null);
  const interactive = !pen && !!onPose;
  /** Press on a text or picture and drag it; keyframed items store the move as a keyframe at the playhead. */
  const dragItem = (kind: "text" | "image", id: string, x: number, y: number) => (e: React.PointerEvent) => {
    if (!interactive) return;
    e.preventDefault(); e.stopPropagation();
    onSelect?.({ type: kind, id });
    const box = containerRef.current?.getBoundingClientRect();
    if (!box) return;
    const x0 = e.clientX, y0 = e.clientY;
    const move = (ev: PointerEvent) => onPose!(kind, id, { x: Math.round((x + (ev.clientX - x0) / box.width) * 1000) / 1000, y: Math.round((y + (ev.clientY - y0) / box.height) * 1000) / 1000 });
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", up);
  };
  const layerTime = time;
  const shownLayers = project.layers.map((l, i) => ({ l, i })).filter(({ l }) => { const a = asset(l.asset_id); return a && layerTime >= l.start - 1e-6 && layerTime < l.start + (a.kind === "image" ? l.image_duration : Math.max(0.05, ((l.trim_out > 0 ? Math.min(l.trim_out, a.duration || l.trim_out) : a.duration) - l.trim_in) / l.speed)); });
  const renderLayer = ({ l, i }: { l: Project["layers"][number]; i: number }) => (
    <LayerView key={l.id} layer={l} asset={asset(l.asset_id)!} time={time} playing={playing} masterVolume={project.master_volume} index={i} stage={containerRef} interactive={interactive}
      selected={sel?.type === "layer" && sel.id === l.id} onSelect={() => onSelect?.({ type: "layer", id: l.id })} onPose={(patch) => onPose?.("layer", l.id, patch)} />
  );

  // Keep the <video> element on the right frame of the right clip.
  useEffect(() => {
    const v = videoRef.current;
    if (!v || !active || !isVideo) return;
    const c = active.clip;
    const end = a!.duration;
    const local = Math.min(Math.max(0, time - active.start), active.dur);
    const target = c.reverse ? Math.min((c.trim_out > 0 ? Math.min(c.trim_out, end) : end), end) - local * c.speed : c.trim_in + local * c.speed;
    const drift = Math.abs(v.currentTime - target);
    if (!playing || drift > 0.25 || c.reverse) { try { v.currentTime = Math.max(0, target); } catch { /* not ready yet */ } }
    v.playbackRate = Math.min(16, Math.max(0.0625, c.speed));
    v.muted = c.muted || !a!.has_audio;
    v.volume = Math.min(1, c.volume * project.master_volume);
    if (playing && !c.reverse) { if (v.paused) v.play().catch(() => {}); } else if (!v.paused) v.pause();
  }, [active?.clip.id, a?.id, time, playing, isVideo]); // eslint-disable-line react-hooks/exhaustive-deps

  // The clock. Real time drives the playhead; media follows it.
  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    let last = performance.now();
    const loop = (now: number) => {
      const dt = (now - last) / 1000; last = now;
      const next = timeRef.current + dt;
      if (next >= live.current.total) { onTick(live.current.total); onEnd(); return; }
      onTick(next);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [playing, onTick, onEnd]);

  // Background audio tracks.
  useEffect(() => {
    for (const ac of project.audio) {
      const el = audioRefs.current.get(ac.id);
      const as = asset(ac.asset_id);
      if (!el || !as) continue;
      const len = Math.max(0.05, (ac.trim_out > 0 ? Math.min(ac.trim_out, as.duration) : as.duration) - ac.trim_in);
      const inside = time >= ac.start && (ac.loop || time < ac.start + len);
      el.loop = ac.loop;
      let vol = ac.volume * project.master_volume;
      if (ac.fade_in > 0 && time - ac.start < ac.fade_in) vol *= Math.max(0, (time - ac.start) / ac.fade_in);
      if (ac.fade_out > 0 && ac.start + len - time < ac.fade_out) vol *= Math.max(0, (ac.start + len - time) / ac.fade_out);
      el.volume = Math.min(1, Math.max(0, vol));
      if (playing && inside) {
        const want = ac.trim_in + (ac.loop ? (time - ac.start) % len : time - ac.start);
        if (el.paused || Math.abs(el.currentTime - want) > 0.3) { try { el.currentTime = want; } catch { /* ignore */ } }
        if (el.paused) el.play().catch(() => {});
      } else if (!el.paused) el.pause();
      else if (!playing && inside) { try { el.currentTime = ac.trim_in + (time - ac.start); } catch { /* ignore */ } }
    }
  }, [time, playing, project.audio, project.master_volume]); // eslint-disable-line react-hooks/exhaustive-deps

  const usedFonts = Array.from(new Set(project.texts.map((t) => t.font).filter(Boolean))).sort();
  const { width, height, background } = project.canvas;
  const clip = active?.clip;
  const sc = 1; // blur is px at preview size; close enough for a preview

  // Fades on the clip itself (and the start/end of a cross-dissolve are not simulated).
  let opacity = 1;
  if (clip && active) {
    const local = time - active.start;
    if (clip.fade_in > 0 && local < clip.fade_in) opacity = Math.min(opacity, local / clip.fade_in);
    if (clip.fade_out > 0 && active.dur - local < clip.fade_out) opacity = Math.min(opacity, (active.dur - local) / clip.fade_out);
  }

  return (
    <div className="stage-wrap">
      {usedFonts.length > 0 && <style>{fontCss(usedFonts)}</style>}
      <div ref={containerRef} className="stage" style={{ aspectRatio: `${width} / ${height}`, background, ["--ar" as string]: String(width / height) }}>
        {shownLayers.filter(({ l }) => l.behind).sort((p, q) => p.l.track - q.l.track).map(renderLayer)}
        {clip && a && (() => {
          const local = Math.max(0, time - (active?.start ?? 0));
          const fb = followBox(clip, a, project.canvas, clip.trim_in + local * clip.speed);
          const mediaStyle: React.CSSProperties = { objectFit: fb ? ("fill" as const) : objectFit(clip), filter: cssFilter(clip, sc), transform: fb ? "none" : cssTransform(clip) };
          const frame: React.CSSProperties | undefined = fb ? { position: "absolute", width: `${100 / fb.w}%`, height: `${100 / fb.h}%`, left: `${(-fb.x0 / fb.w) * 100}%`, top: `${(-fb.y0 / fb.h) * 100}%` } : undefined;
          const el = a.kind === "video"
            ? (clip.chroma?.enabled ? <KeyedVideo key={a.id} src={mediaUrl(a.id)} chroma={clip.chroma} videoRef={videoRef} style={mediaStyle} /> : <video ref={videoRef} key={a.id} src={mediaUrl(a.id)} playsInline preload="auto" style={mediaStyle} />)
            : a.kind === "image" ? <img src={mediaUrl(a.id)} alt="" style={mediaStyle} /> : null;
          return (
            <div className="stage-media" style={{ opacity, overflow: "hidden" }}>
              {frame ? <div style={frame}>{el}</div> : el}
              {clip.vignette && <div className="vignette" />}
            </div>
          );
        })()}
        {shownLayers.filter(({ l }) => !l.behind).sort((p, q) => p.l.track - q.l.track).map(renderLayer)}
        {project.texts.filter((t) => time >= t.start && time < t.start + t.duration).map((t) => textNode(t, time, { on: interactive, start: dragItem("text", t.id, itemPose(t, time).x, itemPose(t, time).y) }))}
        <DrawingsLayer drawings={project.drawings} time={time} W={width} H={height} editingId={editingId} />
        {(project.images ?? []).filter((im) => time >= im.start && time < im.start + im.duration).map((im) => {
          const a = asset(im.asset_id);
          if (!a) return null;
          let o = im.opacity;
          if (im.anim_in !== "none" && im.fade_in > 0 && time - im.start < im.fade_in) o *= Math.max(0, (time - im.start) / im.fade_in);
          if (im.anim_out !== "none" && im.fade_out > 0 && im.start + im.duration - time < im.fade_out) o *= Math.max(0, (im.start + im.duration - time) / im.fade_out);
          const ip = itemPose(im, time);
          return <img key={im.id} className={`stage-overlay-img${interactive ? " stage-overlay-img--live" : ""}${sel?.type === "image" && sel.id === im.id ? " stage-overlay-img--on" : ""}`} alt="" draggable={false} src={mediaUrl(a.id)} onPointerDown={dragItem("image", im.id, ip.x, ip.y)} style={{ left: `${ip.x * 100}%`, top: `${ip.y * 100}%`, width: `${im.size * 100}%`, opacity: o, transform: `translate(-50%,-50%) rotate(${im.rotation}deg)` }} />;
        })}
        {pen && onShape && <DrawCapture pen={pen} W={width} H={height} onShape={onShape} />}
        {!clip && <div className="stage-empty">Add a clip from the Media panel to start.</div>}
      </div>
      {project.audio.map((ac) => { const as = asset(ac.asset_id); return as ? <audio key={ac.id} preload="auto" src={mediaUrl(as.id)} ref={(el) => { if (el) audioRefs.current.set(ac.id, el); else audioRefs.current.delete(ac.id); }} /> : null; })}
    </div>
  );
}
