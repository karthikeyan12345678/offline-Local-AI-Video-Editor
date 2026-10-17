import { useEffect, useRef, type CSSProperties, type RefObject } from "react";
import { mediaUrl } from "../lib/api";
import type { Asset, Chroma, Layer } from "../lib/types";
import { cssFilter, layerDuration, layerPose, type Pose } from "./model";
import { maskStyle } from "./masks";

const hex = (c: string) => [parseInt(c.slice(1, 3), 16), parseInt(c.slice(3, 5), 16), parseInt(c.slice(5, 7), 16)];
const cbcr = (r: number, g: number, b: number) => [128 - 0.168736 * r - 0.331264 * g + 0.5 * b, 128 + 0.5 * r - 0.418688 * g - 0.081312 * b];

/**
 * A video whose screen colour (green, blue…) is made see-through while it plays. Used for the live preview only; the exported
 * video is keyed by ffmpeg, so edges can look a little different there.
 */
export function KeyedVideo({ src, chroma, videoRef, style, className, onReady }: { src: string; chroma: Chroma; videoRef: RefObject<HTMLVideoElement>; style?: CSSProperties; className?: string; onReady?: () => void }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const last = useRef({ t: -1, k: "" });
  useEffect(() => {
    let raf = 0;
    const [kr, kg, kb] = hex(chroma.color);
    const [kcb, kcr] = cbcr(kr, kg, kb);
    const keyIsGreen = kg >= kr && kg >= kb, keyIsBlue = kb > kr && kb > kg;
    const sim = chroma.similarity, bl = Math.max(0.001, chroma.blend);
    const sig = `${chroma.color}${chroma.similarity}${chroma.blend}${chroma.spill}`;
    const draw = () => {
      raf = requestAnimationFrame(draw);
      const v = videoRef.current, c = canvas.current;
      if (!v || !c || v.readyState < 2 || !v.videoWidth) return;
      if (last.current.t === v.currentTime && last.current.k === sig) return;
      last.current = { t: v.currentTime, k: sig };
      const w = Math.min(560, v.videoWidth), h = Math.max(2, Math.round((w * v.videoHeight) / v.videoWidth));
      if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
      const ctx = c.getContext("2d", { willReadFrequently: true });
      if (!ctx) return;
      ctx.drawImage(v, 0, 0, w, h);
      const img = ctx.getImageData(0, 0, w, h), d = img.data;
      for (let i = 0; i < d.length; i += 4) {
        const r = d[i], g = d[i + 1], b = d[i + 2];
        const cb = 128 - 0.168736 * r - 0.331264 * g + 0.5 * b, cr = 128 + 0.5 * r - 0.418688 * g - 0.081312 * b;
        const dist = Math.hypot(cb - kcb, cr - kcr) / 255;
        const a = dist <= sim * 0.8 ? 0 : dist >= sim * 0.8 + bl ? 1 : (dist - sim * 0.8) / bl;
        d[i + 3] = Math.round(a * 255);
        if (chroma.spill && a > 0) {
          if (keyIsGreen) d[i + 1] = Math.min(g, (r + b) / 2 + 12);
          else if (keyIsBlue) d[i + 2] = Math.min(b, (r + g) / 2 + 12);
        }
      }
      ctx.putImageData(img, 0, 0);
      onReady?.();
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [chroma.color, chroma.similarity, chroma.blend, chroma.spill, videoRef, onReady]);
  return (
    <>
      <video ref={videoRef} src={src} playsInline preload="auto" className="keyed-src" />
      <canvas ref={canvas} className={className} style={style} />
    </>
  );
}

interface LayerViewProps {
  layer: Layer; asset: Asset; time: number; playing: boolean; masterVolume: number; selected: boolean; index: number;
  onSelect: () => void; onPose: (patch: Partial<Pose>) => void; stage: RefObject<HTMLDivElement>; interactive: boolean;
}

/** One layer on the stage: plays its own file in step with the timeline, follows its keyframes, and can be dragged and resized with the mouse. */
export function LayerView({ layer, asset, time, playing, masterVolume, selected, index, onSelect, onPose, stage, interactive }: LayerViewProps) {
  const vref = useRef<HTMLVideoElement>(null);
  const isVideo = asset.kind === "video";
  const pose = layerPose(layer, time);
  const dur = layerDuration(layer, asset);
  const local = Math.min(Math.max(0, time - layer.start), dur);

  useEffect(() => {
    const v = vref.current;
    if (!v || !isVideo) return;
    const target = layer.trim_in + local * layer.speed;
    if (!playing || Math.abs(v.currentTime - target) > 0.3) { try { v.currentTime = Math.max(0, target); } catch { /* not ready */ } }
    v.playbackRate = Math.min(16, Math.max(0.0625, layer.speed));
    v.muted = layer.muted || !asset.has_audio;
    v.volume = Math.min(1, Math.max(0, layer.volume * masterVolume));
    if (playing) { if (v.paused) v.play().catch(() => {}); } else if (!v.paused) v.pause();
  }, [time, playing, layer.trim_in, layer.speed, layer.muted, layer.volume, masterVolume, isVideo, asset.has_audio]); // eslint-disable-line react-hooks/exhaustive-deps

  let opacity = pose.opacity;
  const age = time - layer.start;
  if (layer.fade_in > 0 && age < layer.fade_in) opacity *= Math.max(0, age / layer.fade_in);
  if (layer.fade_out > 0 && dur - age < layer.fade_out) opacity *= Math.max(0, (dur - age) / layer.fade_out);

  const startDrag = (e: React.PointerEvent, mode: "move" | "size") => {
    if (!interactive) return;
    e.preventDefault(); e.stopPropagation();
    onSelect();
    const box = stage.current?.getBoundingClientRect();
    if (!box) return;
    const x0 = e.clientX, y0 = e.clientY, p0 = pose;
    const move = (ev: PointerEvent) => {
      const dx = (ev.clientX - x0) / box.width, dy = (ev.clientY - y0) / box.height;
      if (mode === "move") onPose({ x: Math.round((p0.x + dx) * 1000) / 1000, y: Math.round((p0.y + dy) * 1000) / 1000 });
      else onPose({ size: Math.max(0.03, Math.min(3, Math.round((p0.size + 2 * dx) * 1000) / 1000)) });
    };
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  const filter = cssFilter({ adjust: layer.adjust, preset: layer.preset, blur: layer.blur } as never, 1);
  const media: CSSProperties = { width: "100%", height: "auto", display: "block", filter: filter === "none" ? undefined : filter, ...maskStyle(layer.mask, layer.mask_invert, asset.width, asset.height) };
  const url = mediaUrl(asset.id);
  return (
    <div className={`stage-layer${selected ? " stage-layer--on" : ""}${interactive ? " stage-layer--live" : ""}`} aria-label={`Layer ${index + 1}: ${asset.name}`}
      style={{ left: `${pose.x * 100}%`, top: `${pose.y * 100}%`, width: `${pose.size * 100}%`, opacity, transform: `translate(-50%,-50%) rotate(${pose.rotation}deg)`, zIndex: layer.behind ? layer.track - 10 : layer.track }}
      onPointerDown={(e) => startDrag(e, "move")}>
      {isVideo
        ? (layer.chroma.enabled ? <KeyedVideo src={url} chroma={layer.chroma} videoRef={vref} style={media} /> : <video ref={vref} src={url} playsInline preload="auto" style={media} />)
        : <img src={url} alt="" style={media} draggable={false} />}
      {selected && interactive && <span className="stage-handle" onPointerDown={(e) => startDrag(e, "size")} title="Drag to resize" aria-hidden="true" />}
    </div>
  );
}
