import { clamp, uid } from "../lib/format";
import type { Asset, AudioClip, Clip, Project, TextOverlay } from "../lib/types";

export const TRANSITIONS: [string, string][] = [
  ["none", "None (hard cut)"], ["fade", "Cross-fade"], ["dissolve", "Dissolve"], ["fadeblack", "Fade through black"], ["fadewhite", "Fade through white"],
  ["wipeleft", "Wipe left"], ["wiperight", "Wipe right"], ["wipeup", "Wipe up"], ["wipedown", "Wipe down"],
  ["slideleft", "Slide left"], ["slideright", "Slide right"], ["slideup", "Slide up"], ["slidedown", "Slide down"],
  ["circleopen", "Circle open"], ["circleclose", "Circle close"], ["radial", "Radial"], ["pixelize", "Pixelate"],
];
export const PRESETS: [string, string][] = [["none", "None"], ["bw", "Black and white"], ["sepia", "Sepia"], ["vintage", "Vintage"], ["cool", "Cool"], ["warm", "Warm"], ["faded", "Faded"], ["dramatic", "Dramatic"], ["negative", "Negative"]];
export const CANVAS_PRESETS: { label: string; width: number; height: number }[] = [
  { label: "Widescreen 16:9 · 1280×720", width: 1280, height: 720 }, { label: "Full HD 16:9 · 1920×1080", width: 1920, height: 1080 },
  { label: "Standard 4:3 · 1024×768", width: 1024, height: 768 }, { label: "Square 1:1 · 1080×1080", width: 1080, height: 1080 },
  { label: "Vertical 9:16 · 720×1280", width: 720, height: 1280 }, { label: "Small 16:9 · 854×480", width: 854, height: 480 },
];

export const newProject = (): Project => ({ id: uid() + uid(), name: "Untitled project", canvas: { width: 1280, height: 720, fps: 24, background: "#000000" }, clips: [], texts: [], audio: [], master_volume: 1 });

export const newClip = (a: Asset): Clip => ({
  id: uid(), asset_id: a.id, trim_in: 0, trim_out: 0, image_duration: 3, speed: 1, reverse: false, volume: 1, muted: false, fade_in: 0, fade_out: 0,
  fit: "fit", zoom: 1, pan_x: 0, pan_y: 0, rotate: 0, flip_h: false, flip_v: false,
  adjust: { brightness: 0, contrast: 0, saturation: 0, gamma: 1, hue: 0 }, preset: "none", blur: 0, sharpen: 0, vignette: false, denoise: false,
  transition: { type: "none", duration: 0.5 },
});
export const newText = (start: number): TextOverlay => ({ id: uid(), text: "Your text", start, duration: 3, x: 0.5, y: 0.85, size: 6, color: "#FFFFFF", bold: true, box: true, box_opacity: 0.5, fade_in: 0.3, fade_out: 0.3 });
export const newAudio = (a: Asset, start: number): AudioClip => ({ id: uid(), asset_id: a.id, start, trim_in: 0, trim_out: 0, volume: 1, fade_in: 0, fade_out: 0 });

/** Seconds of source a clip uses. */
export function sourceEnd(c: Clip, a: Asset | undefined): number {
  if (!a) return c.trim_in + 1;
  if (a.kind === "image") return c.image_duration;
  const end = c.trim_out > 0 ? c.trim_out : a.duration;
  return a.duration > 0 ? Math.min(end, a.duration) : end;
}
export function clipDuration(c: Clip, a: Asset | undefined): number {
  if (a?.kind === "image") return c.image_duration;
  return Math.max(0.05, sourceEnd(c, a) - c.trim_in) / c.speed;
}
export function audioLength(c: AudioClip, a: Asset | undefined): number {
  const dur = a?.duration ?? 0;
  const end = c.trim_out > 0 ? Math.min(c.trim_out, dur || c.trim_out) : dur;
  return Math.max(0.05, end - c.trim_in);
}

export interface Placed { clip: Clip; start: number; dur: number; overlap: number }
/** Where each clip sits on the timeline. Mirrors the renderer: a transition overlaps the clip with the one before it. */
export function layout(p: Project, asset: (id: string) => Asset | undefined): { items: Placed[]; total: number } {
  const items: Placed[] = [];
  let cursor = 0;
  let prev: Placed | null = null;
  for (const clip of p.clips) {
    const dur = clipDuration(clip, asset(clip.asset_id));
    let overlap = 0;
    if (prev && prev.clip.transition.type !== "none") overlap = Math.max(0, Math.min(prev.clip.transition.duration, prev.dur * 0.5, dur * 0.5));
    const start = cursor - overlap;
    const placed = { clip, start, dur, overlap };
    items.push(placed);
    cursor = start + dur;
    prev = placed;
  }
  return { items, total: cursor };
}

/** Split the clip under `t`. Returns null when `t` is not inside a clip, or too close to an edge. */
export function splitAt(p: Project, t: number, asset: (id: string) => Asset | undefined): Project | null {
  const { items } = layout(p, asset);
  const idx = items.findIndex((i) => t > i.start + 0.1 && t < i.start + i.dur - 0.1);
  if (idx < 0) return null;
  const { clip, start, dur } = items[idx];
  const a = asset(clip.asset_id);
  const off = t - start;
  const first: Clip = { ...clip, id: uid(), transition: { type: "none", duration: clip.transition.duration }, fade_out: 0 };
  const second: Clip = { ...clip, id: uid(), fade_in: 0 };
  if (a?.kind === "image") {
    first.image_duration = off;
    second.image_duration = dur - off;
  } else {
    const end = sourceEnd(clip, a);
    if (!clip.reverse) {
      const cut = clip.trim_in + off * clip.speed;
      first.trim_out = cut; second.trim_in = cut;
    } else {
      const cut = end - off * clip.speed; // the timeline-first part is the later part of the source
      first.trim_in = cut; first.trim_out = end; second.trim_in = clip.trim_in; second.trim_out = cut;
    }
  }
  const clips = [...p.clips];
  clips.splice(idx, 1, first, second);
  return { ...p, clips };
}

export function cssFilter(c: Clip, scale: number): string {
  const f: string[] = [];
  const a = c.adjust;
  if (a.brightness) f.push(`brightness(${1 + a.brightness / 100})`);
  if (a.contrast) f.push(`contrast(${1 + a.contrast / 100})`);
  if (a.saturation) f.push(`saturate(${Math.max(0, 1 + a.saturation / 100)})`);
  if (a.hue) f.push(`hue-rotate(${a.hue}deg)`);
  if (a.gamma !== 1) f.push(`brightness(${Math.pow(1 / a.gamma, 0.6).toFixed(3)})`);
  const preset: Record<string, string> = {
    bw: "grayscale(1)", sepia: "sepia(1)", vintage: "sepia(.4) contrast(.9) saturate(.9)", cool: "hue-rotate(-10deg) saturate(1.1)", warm: "sepia(.25) saturate(1.2)",
    faded: "contrast(.85) saturate(.8) brightness(1.1)", dramatic: "contrast(1.3) saturate(1.15)", negative: "invert(1)",
  };
  if (preset[c.preset]) f.push(preset[c.preset]);
  if (c.blur) f.push(`blur(${(c.blur * scale).toFixed(2)}px)`);
  return f.join(" ") || "none";
}
export function cssTransform(c: Clip): string {
  const sx = (c.flip_h ? -1 : 1) * c.zoom;
  const sy = (c.flip_v ? -1 : 1) * c.zoom;
  return `translate(${(-c.pan_x * (c.zoom - 1) * 50).toFixed(2)}%, ${(-c.pan_y * (c.zoom - 1) * 50).toFixed(2)}%) rotate(${c.rotate}deg) scale(${sx}, ${sy})`;
}
export const objectFit = (c: Clip) => (c.fit === "fit" ? "contain" : c.fit === "fill" ? "cover" : "fill");

export const clampT = (t: number, total: number) => clamp(t, 0, Math.max(0, total));
