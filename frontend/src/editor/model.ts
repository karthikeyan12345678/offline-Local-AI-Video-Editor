import { clamp, uid } from "../lib/format";
import type { Asset, AudioClip, Clip, Drawing, ImageOverlay, Project, Shape, TextOverlay } from "../lib/types";

export const TEXT_SAMPLE = "Aa வணக்கம் नमस्ते";

export const CANVAS_PRESETS: { label: string; width: number; height: number }[] = [
  { label: "Widescreen 16:9 · 1280×720", width: 1280, height: 720 }, { label: "Full HD 16:9 · 1920×1080", width: 1920, height: 1080 },
  { label: "Standard 4:3 · 1024×768", width: 1024, height: 768 }, { label: "Square 1:1 · 1080×1080", width: 1080, height: 1080 },
  { label: "Vertical 9:16 · 720×1280", width: 720, height: 1280 }, { label: "Small 16:9 · 854×480", width: 854, height: 480 },
];

export const newProject = (): Project => ({
  id: uid() + uid(), name: "Untitled project", canvas: { width: 1280, height: 720, fps: 24, background: "#000000" }, clips: [], texts: [], audio: [], drawings: [], images: [], master_volume: 1,
  duck_music: false, duck_amount: 0.6, master_normalize: false,
});

const clipDefaults = (): Omit<Clip, "id" | "asset_id"> => ({
  trim_in: 0, trim_out: 0, image_duration: 3, speed: 1, reverse: false, volume: 1, muted: false, fade_in: 0, fade_out: 0,
  fit: "fit", zoom: 1, pan_x: 0, pan_y: 0, rotate: 0, flip_h: false, flip_v: false,
  adjust: { brightness: 0, contrast: 0, saturation: 0, gamma: 1, hue: 0 }, preset: "none", blur: 0, sharpen: 0, vignette: false, denoise: false,
  transition: { type: "none", duration: 0.5 },
  motion: "none", motion_strength: 0.5, effects: [], follow: null, audio_fx: "none", pitch: 0, bass: 0, treble: 0, denoise_audio: false, normalize_audio: false,
});
export const newClip = (a: Asset): Clip => ({ id: uid(), asset_id: a.id, ...clipDefaults() });

const textDefaults = (): Omit<TextOverlay, "id"> => ({
  text: "Your text", start: 0, duration: 3, x: 0.5, y: 0.85, size: 6, color: "#FFFFFF", bold: true, box: true, box_opacity: 0.5, fade_in: 0.4, fade_out: 0.4,
  font: "", italic: false, uppercase: false, align: "center", letter_spacing: 0, line_spacing: 1.25, color2: null, stroke: 0, stroke_color: "#000000",
  shadow: 0, shadow_color: "#000000", glow: 0, glow_color: "#FFFFFF", box_color: "#000000", rotation: 0, opacity: 1, anim_in: "fade", anim_out: "fade",
});
export const newText = (start: number): TextOverlay => ({ id: uid(), ...textDefaults(), start });

const audioDefaults = (): Omit<AudioClip, "id" | "asset_id" | "start"> => ({
  trim_in: 0, trim_out: 0, volume: 1, fade_in: 0, fade_out: 0, fx: "none", pitch: 0, bass: 0, treble: 0, denoise: false, normalize: false, loop: false, is_music: true,
});
export const newAudio = (a: Asset, start: number, extra: Partial<AudioClip> = {}): AudioClip => ({ id: uid(), asset_id: a.id, start, ...audioDefaults(), ...extra });

export const newImageOverlay = (asset_id: string, start: number, duration = 4): ImageOverlay => ({ id: uid(), asset_id, start, duration, x: 0.5, y: 0.5, size: 0.25, rotation: 0, opacity: 1, fade_in: 0.2, fade_out: 0.2, anim_in: "fade", anim_out: "fade" });
export const newDrawing = (start: number, duration = 4): Drawing => ({ id: uid(), start, duration, shapes: [], opacity: 1, fade_in: 0.3, fade_out: 0.3, anim_in: "fade", anim_out: "fade" });
export const newShape = (s: Partial<Shape> & Pick<Shape, "type" | "points">): Shape => ({ color: "#FF3B30", width: 0.8, opacity: 1, filled: false, fill_color: null, fill_opacity: 0.25, ...s });

/** Fill in fields that projects saved by an older version don't have. */
export function upgradeProject(p: Partial<Project>): Project {
  const base = newProject();
  return {
    ...base, ...p, canvas: { ...base.canvas, ...p.canvas },
    clips: (p.clips ?? []).map((c) => ({ ...clipDefaults(), ...c, adjust: { ...clipDefaults().adjust, ...c.adjust }, transition: { ...clipDefaults().transition, ...c.transition } })) as Clip[],
    texts: (p.texts ?? []).map((t) => ({ ...textDefaults(), ...t })) as TextOverlay[],
    audio: (p.audio ?? []).map((a) => ({ ...audioDefaults(), ...a })) as AudioClip[],
    drawings: (p.drawings ?? []) as Drawing[],
    images: (p.images ?? []) as ImageOverlay[],
  };
}

export interface TextStyle { id: string; label: string; patch: Partial<TextOverlay> }
/** One-click looks for text. They only change style, never the words or timing. */
export const TEXT_STYLES: TextStyle[] = [
  { id: "clean", label: "Clean", patch: { font: "montserrat", bold: true, color: "#FFFFFF", color2: null, stroke: 0, shadow: 0.3, glow: 0, box: false, italic: false, uppercase: false, letter_spacing: 0, rotation: 0 } },
  { id: "subtitle", label: "Subtitle", patch: { font: "poppins", bold: false, color: "#FFFFFF", color2: null, stroke: 0, shadow: 0, glow: 0, box: true, box_color: "#000000", box_opacity: 0.6, uppercase: false, size: 5, y: 0.88 } },
  { id: "impact", label: "Impact", patch: { font: "anton", bold: false, color: "#FFFFFF", color2: null, stroke: 8, stroke_color: "#000000", shadow: 0.5, glow: 0, box: false, uppercase: true, letter_spacing: 0.02, size: 9 } },
  { id: "neon", label: "Neon", patch: { font: "orbitron", bold: true, color: "#FFFFFF", color2: null, stroke: 0, shadow: 0, glow: 0.9, glow_color: "#00E5FF", box: false, uppercase: true, letter_spacing: 0.06 } },
  { id: "gold", label: "Gold", patch: { font: "playfair", bold: true, color: "#FFE680", color2: "#B8860B", stroke: 3, stroke_color: "#3B2A00", shadow: 0.5, glow: 0.2, glow_color: "#FFD54A", box: false, italic: false } },
  { id: "fire", label: "Fire", patch: { font: "bebas", bold: false, color: "#FFF176", color2: "#E53935", stroke: 4, stroke_color: "#4E0000", shadow: 0.4, glow: 0.6, glow_color: "#FF6D00", box: false, uppercase: true, size: 10 } },
  { id: "comic", label: "Comic", patch: { font: "bangers", bold: false, color: "#FFEB3B", color2: null, stroke: 9, stroke_color: "#000000", shadow: 0.6, glow: 0, box: false, rotation: -4, uppercase: true, letter_spacing: 0.03, size: 9 } },
  { id: "retro", label: "Retro", patch: { font: "pressstart", bold: false, color: "#FF4081", color2: "#7C4DFF", stroke: 0, shadow: 0.7, shadow_color: "#1A237E", glow: 0, box: false, size: 4 } },
  { id: "script", label: "Script", patch: { font: "pacifico", bold: false, color: "#FFFFFF", color2: null, stroke: 0, shadow: 0.5, glow: 0.2, glow_color: "#FF80AB", box: false, size: 8 } },
  { id: "typewriter", label: "Typewriter", patch: { font: "specialelite", bold: false, color: "#222222", color2: null, stroke: 0, shadow: 0, glow: 0, box: true, box_color: "#F5F0E1", box_opacity: 0.95, size: 5 } },
  { id: "cinema", label: "Cinematic", patch: { font: "cinzel", bold: true, color: "#F5F5F5", color2: null, stroke: 0, shadow: 0.4, glow: 0, box: false, uppercase: true, letter_spacing: 0.25, size: 6 } },
  { id: "tamil", label: "தமிழ் Title", patch: { font: "notosanstamil", bold: true, color: "#FFFFFF", color2: "#FFC107", stroke: 4, stroke_color: "#000000", shadow: 0.4, glow: 0, box: false, uppercase: false, size: 8 } },
  { id: "hindi", label: "हिन्दी Title", patch: { font: "notosansdevanagari", bold: true, color: "#FFFFFF", color2: "#FF9800", stroke: 4, stroke_color: "#000000", shadow: 0.4, glow: 0, box: false, uppercase: false, size: 8 } },
  { id: "lower", label: "Lower third", patch: { font: "oswald", bold: true, color: "#FFFFFF", color2: null, stroke: 0, shadow: 0, glow: 0, box: true, box_color: "#D50000", box_opacity: 0.9, uppercase: true, x: 0.2, y: 0.82, align: "left", size: 5 } },
];

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
