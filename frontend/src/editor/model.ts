import { clamp, uid } from "../lib/format";
import type { Asset, AudioClip, Chroma, Clip, Drawing, Ease, ImageOverlay, Key, Layer, Project, Shape, TextOverlay } from "../lib/types";

export const TEXT_SAMPLE = "Aa வணக்கம் नमस्ते";

export const CANVAS_PRESETS: { label: string; width: number; height: number }[] = [
  { label: "Widescreen 16:9 · 1280×720", width: 1280, height: 720 }, { label: "Full HD 16:9 · 1920×1080", width: 1920, height: 1080 },
  { label: "Standard 4:3 · 1024×768", width: 1024, height: 768 }, { label: "Square 1:1 · 1080×1080", width: 1080, height: 1080 },
  { label: "Vertical 9:16 · 720×1280", width: 720, height: 1280 }, { label: "Small 16:9 · 854×480", width: 854, height: 480 },
];

// Platform formats shown in the editor's Format menu and the export dialog.
export type PlatformPreset = { id: string; label: string; hint: string; width: number; height: number; fps: number; maxSeconds?: number };
export const PLATFORM_PRESETS: PlatformPreset[] = [
  { id: "youtube", label: "YouTube 16:9", hint: "1920×1080 · 30 fps", width: 1920, height: 1080, fps: 30 },
  { id: "shorts", label: "YouTube Shorts 9:16", hint: "1080×1920 · up to 3 min", width: 1080, height: 1920, fps: 30, maxSeconds: 180 },
  { id: "reels", label: "Instagram Reels 9:16", hint: "1080×1920 · up to 90 s", width: 1080, height: 1920, fps: 30, maxSeconds: 90 },
  { id: "insta-feed", label: "Instagram Feed 4:5", hint: "1080×1350", width: 1080, height: 1350, fps: 30, maxSeconds: 60 },
  { id: "square", label: "Square 1:1", hint: "1080×1080", width: 1080, height: 1080, fps: 30 },
];
export const presetFor = (w: number, h: number) => PLATFORM_PRESETS.find((p) => p.width === w && p.height === h);

export const newProject = (): Project => ({
  id: uid() + uid(), name: "Untitled project", canvas: { width: 1280, height: 720, fps: 24, background: "#000000" }, clips: [], texts: [], audio: [], drawings: [], images: [], layers: [], master_volume: 1,
  duck_music: false, duck_amount: 0.6, master_normalize: false,
});

export const chromaDefaults = (): Chroma => ({ enabled: false, color: "#00B140", similarity: 0.3, blend: 0.1, spill: true });

const clipDefaults = (): Omit<Clip, "id" | "asset_id"> => ({
  trim_in: 0, trim_out: 0, image_duration: 3, speed: 1, reverse: false, volume: 1, muted: false, fade_in: 0, fade_out: 0,
  fit: "fit", zoom: 1, pan_x: 0, pan_y: 0, rotate: 0, flip_h: false, flip_v: false,
  adjust: { brightness: 0, contrast: 0, saturation: 0, gamma: 1, hue: 0 }, preset: "none", blur: 0, sharpen: 0, vignette: false, denoise: false,
  transition: { type: "none", duration: 0.5 },
  motion: "none", motion_strength: 0.5, effects: [], follow: null, audio_fx: "none", pitch: 0, bass: 0, treble: 0, denoise_audio: false, normalize_audio: false,
  chroma: chromaDefaults(),
});
export const newClip = (a: Asset): Clip => ({ id: uid(), asset_id: a.id, ...clipDefaults() });

const textDefaults = (): Omit<TextOverlay, "id"> => ({
  text: "Your text", start: 0, duration: 3, x: 0.5, y: 0.85, size: 6, color: "#FFFFFF", bold: true, box: true, box_opacity: 0.5, fade_in: 0.4, fade_out: 0.4,
  font: "", italic: false, uppercase: false, align: "center", letter_spacing: 0, line_spacing: 1.25, color2: null, stroke: 0, stroke_color: "#000000",
  shadow: 0, shadow_color: "#000000", glow: 0, glow_color: "#FFFFFF", box_color: "#000000", rotation: 0, opacity: 1, anim_in: "fade", anim_out: "fade", keys: [],
});
export const newText = (start: number): TextOverlay => ({ id: uid(), ...textDefaults(), start });

const audioDefaults = (): Omit<AudioClip, "id" | "asset_id" | "start"> => ({
  trim_in: 0, trim_out: 0, volume: 1, fade_in: 0, fade_out: 0, fx: "none", pitch: 0, bass: 0, treble: 0, denoise: false, normalize: false, loop: false, is_music: true,
});
export const newAudio = (a: Asset, start: number, extra: Partial<AudioClip> = {}): AudioClip => ({ id: uid(), asset_id: a.id, start, ...audioDefaults(), ...extra });

export const newImageOverlay = (asset_id: string, start: number, duration = 4): ImageOverlay => ({ id: uid(), asset_id, start, duration, x: 0.5, y: 0.5, size: 0.25, rotation: 0, opacity: 1, fade_in: 0.2, fade_out: 0.2, anim_in: "fade", anim_out: "fade", keys: [] });
export const newDrawing = (start: number, duration = 4): Drawing => ({ id: uid(), start, duration, shapes: [], opacity: 1, fade_in: 0.3, fade_out: 0.3, anim_in: "fade", anim_out: "fade" });
export const newShape = (s: Partial<Shape> & Pick<Shape, "type" | "points">): Shape => ({ color: "#FF3B30", width: 0.8, opacity: 1, filled: false, fill_color: null, fill_opacity: 0.25, ...s });

/** Fill in fields that projects saved by an older version don't have. */
export function upgradeProject(p: Partial<Project>): Project {
  const base = newProject();
  return {
    ...base, ...p, canvas: { ...base.canvas, ...p.canvas },
    clips: (p.clips ?? []).map((c) => ({ ...clipDefaults(), ...c, adjust: { ...clipDefaults().adjust, ...c.adjust }, transition: { ...clipDefaults().transition, ...c.transition }, chroma: { ...chromaDefaults(), ...c.chroma } })) as Clip[],
    texts: (p.texts ?? []).map((t) => ({ ...textDefaults(), ...t, keys: t.keys ?? [] })) as TextOverlay[],
    audio: (p.audio ?? []).map((a) => ({ ...audioDefaults(), ...a })) as AudioClip[],
    drawings: (p.drawings ?? []) as Drawing[],
    images: (p.images ?? []).map((i) => ({ ...i, keys: i.keys ?? [] })) as ImageOverlay[],
    layers: (p.layers ?? []).map((l) => ({ ...layerDefaults(), ...l, adjust: { ...clipDefaults().adjust, ...l.adjust }, chroma: { ...chromaDefaults(), ...l.chroma } })) as Layer[],
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
    cinematic: "contrast(1.12) saturate(1.1) hue-rotate(-6deg)", noir: "grayscale(1) contrast(1.3)", cyberpunk: "saturate(1.5) hue-rotate(20deg) contrast(1.15)", sunset: "sepia(.35) saturate(1.4) hue-rotate(-12deg)",
    golden: "sepia(.4) saturate(1.3) brightness(1.05)", moody: "contrast(1.2) saturate(.8) brightness(.95)", pastel: "saturate(.75) brightness(1.1) contrast(.9)", vivid: "saturate(1.6) contrast(1.1)",
    matte: "contrast(.9) saturate(.9) brightness(1.05)", bleach: "saturate(.55) contrast(1.35)", crossprocess: "contrast(1.2) hue-rotate(10deg) saturate(1.3)", polaroid: "sepia(.2) saturate(1.15) contrast(.95) brightness(1.05)",
    hdr: "contrast(1.25) saturate(1.3)", night: "brightness(.85) saturate(.85) hue-rotate(15deg) contrast(1.15)", duotone_blue: "grayscale(1) sepia(1) hue-rotate(180deg) saturate(3)", duotone_pink: "grayscale(1) sepia(1) hue-rotate(290deg) saturate(3)",
    blockbuster: "contrast(1.18) saturate(1.2) hue-rotate(-8deg)", film_warm: "sepia(.2) saturate(1.1) contrast(1.06)", film_cool: "saturate(1.05) hue-rotate(10deg) contrast(1.05)", film_fade: "contrast(.88) saturate(.85) brightness(1.06)",
    tungsten: "sepia(.45) saturate(1.2)", day_for_night: "brightness(.7) hue-rotate(25deg) saturate(.7) contrast(1.2)", dreamy: "brightness(1.05) saturate(1.1) contrast(.92) blur(.4px)", romantic: "sepia(.15) saturate(1.1) brightness(1.04) hue-rotate(-8deg)",
    horror: "saturate(.4) contrast(1.3) brightness(.85) hue-rotate(40deg)", scifi: "saturate(.85) hue-rotate(20deg) contrast(1.2)", autumn: "sepia(.4) saturate(1.3) hue-rotate(-10deg)", winter: "saturate(.8) brightness(1.04) hue-rotate(12deg)",
    tropical: "saturate(1.45) contrast(1.08)", summer: "sepia(.15) saturate(1.3) brightness(1.04)", retro_80s: "saturate(1.35) contrast(1.12) hue-rotate(-14deg)", retro_90s: "contrast(.98) saturate(.9) sepia(.15)",
    anime: "saturate(1.5) contrast(1.15) brightness(1.03)", high_key: "brightness(1.2) contrast(.9) saturate(.9)", low_key: "brightness(.8) contrast(1.25)", clean_bright: "brightness(1.05) contrast(1.08) saturate(1.12)",
    foodie: "saturate(1.35) contrast(1.1) sepia(.1)", portrait_soft: "saturate(.95) contrast(.94) brightness(1.03) blur(.3px)", sky_blue: "saturate(1.25) hue-rotate(8deg) contrast(1.08)", forest_green: "saturate(1.3) hue-rotate(-6deg) contrast(1.08)",
    moonlight: "brightness(.85) saturate(.5) hue-rotate(20deg) contrast(1.15)", grayscale_soft: "grayscale(1) contrast(.94) brightness(1.03)", sin_red: "grayscale(.8) contrast(1.3) sepia(.3) hue-rotate(-30deg)",
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


// ---------------------------------------------------------------- layers and keyframes
const layerDefaults = (): Omit<Layer, "id" | "asset_id"> => ({
  track: 1, behind: false, start: 0, trim_in: 0, trim_out: 0, image_duration: 4, speed: 1, volume: 1, muted: false, x: 0.5, y: 0.5, size: 0.5, rotation: 0, opacity: 1,
  fade_in: 0, fade_out: 0, adjust: { brightness: 0, contrast: 0, saturation: 0, gamma: 1, hue: 0 }, preset: "none", blur: 0, effects: [], chroma: chromaDefaults(), mask: "none", mask_feather: 0.1, mask_invert: false, keys: [],
});
/** A second video or picture on its own track. A green-screen clip (or one placed behind) fills the frame; anything else starts as a small picture-in-picture. */
export const newLayer = (a: Asset, start: number, extra: Partial<Layer> = {}): Layer => ({ id: uid(), asset_id: a.id, ...layerDefaults(), start, ...extra });
export const layerDuration = (l: Layer, a: Asset | undefined): number => {
  if (!a) return 3;
  if (a.kind === "image") return l.image_duration;
  const end = l.trim_out > 0 ? Math.min(l.trim_out, a.duration || l.trim_out) : a.duration;
  return Math.max(0.05, end - l.trim_in) / l.speed;
};

export interface Pose { x: number; y: number; size: number; rotation: number; opacity: number }
type Keyed = { start: number; keys: Key[] };
const smooth = (p: number) => p * p * (3 - 2 * p);
/** Where an item is and how it looks `rel` seconds after it starts, blending its keyframes exactly like the renderer does. */
export function poseAt(rest: Pose, keys: Key[] | undefined, rel: number): Pose {
  if (!keys || keys.length === 0) return rest;
  const ks = [...keys].sort((a, b) => a.t - b.t);
  const pick = (k: Key): Pose => ({ x: k.x, y: k.y, size: k.size, rotation: k.rotation, opacity: k.opacity });
  if (rel <= ks[0].t) return pick(ks[0]);
  if (rel >= ks[ks.length - 1].t) return pick(ks[ks.length - 1]);
  for (let i = 0; i < ks.length - 1; i++) {
    const a = ks[i], b = ks[i + 1];
    if (rel >= a.t && rel <= b.t) {
      const span = Math.max(1e-6, b.t - a.t);
      let p = (rel - a.t) / span;
      if (a.ease === "hold") p = 0; else if (a.ease !== "linear") p = smooth(p);
      const mix = (u: number, v: number) => u + (v - u) * p;
      return { x: mix(a.x, b.x), y: mix(a.y, b.y), size: mix(a.size, b.size), rotation: mix(a.rotation, b.rotation), opacity: mix(a.opacity, b.opacity) };
    }
  }
  return pick(ks[ks.length - 1]);
}
export const layerPose = (l: Layer, time: number): Pose => poseAt({ x: l.x, y: l.y, size: l.size, rotation: l.rotation, opacity: l.opacity }, l.keys, time - l.start);
/** Keyframes for text and pictures only move them (x and y); everything else stays as set. */
export const itemRest = (it: TextOverlay | ImageOverlay): Pose => ({ x: it.x, y: it.y, size: "size" in it ? (it.size as number) : 0.5, rotation: it.rotation, opacity: it.opacity });
export const itemPose = (it: TextOverlay | ImageOverlay, time: number): Pose => {
  const rest = itemRest(it);
  const p = poseAt(rest, it.keys, time - it.start);
  return { ...rest, x: p.x, y: p.y };
};
/** Add a key at `rel` seconds, or replace the one already there. */
export function upsertKey(keys: Key[], rel: number, pose: Pose, ease: Ease = "smooth"): Key[] {
  const t = Math.max(0, Math.round(rel * 1000) / 1000);
  const old = keys.find((k) => Math.abs(k.t - t) < 0.02);
  const next = keys.filter((k) => Math.abs(k.t - t) >= 0.02);
  next.push({ t, ...pose, ease: old?.ease ?? ease });
  return next.sort((a, b) => a.t - b.t);
}
export const keyed = (it: Keyed) => it.keys.length > 0;

/** Every moment worth jumping to: the start and end of each clip, layer, text, picture and keyframe. */
export function cutPoints(p: Project, asset: (id: string) => Asset | undefined): number[] {
  const { items, total } = layout(p, asset);
  const pts = new Set<number>([0, total]);
  items.forEach((i) => { pts.add(i.start); pts.add(i.start + i.dur); });
  p.layers.forEach((l) => { pts.add(l.start); pts.add(l.start + layerDuration(l, asset(l.asset_id))); l.keys.forEach((k) => pts.add(l.start + k.t)); });
  p.texts.forEach((t) => { pts.add(t.start); pts.add(t.start + t.duration); t.keys.forEach((k) => pts.add(t.start + k.t)); });
  p.images.forEach((t) => { pts.add(t.start); pts.add(t.start + t.duration); t.keys.forEach((k) => pts.add(t.start + k.t)); });
  p.drawings.forEach((t) => { pts.add(t.start); pts.add(t.start + t.duration); });
  return [...pts].filter((v) => v >= 0).map((v) => Math.round(v * 1000) / 1000).sort((a, b) => a - b);
}

/** Stack blocks that overlap in time onto separate lines so every one stays visible. Returns each id's line and the number of lines. */
export function packLanes(items: { id: string; start: number; end: number }[]): { lane: Record<string, number>; count: number } {
  const lane: Record<string, number> = {};
  const ends: number[] = [];
  for (const it of [...items].sort((a, b) => a.start - b.start || a.end - b.end)) {
    let k = ends.findIndex((e) => e <= it.start + 1e-6);
    if (k < 0) { k = ends.length; ends.push(0); }
    ends[k] = it.end;
    lane[it.id] = k;
  }
  return { lane, count: Math.max(1, ends.length) };
}

export const clampT = (t: number, total: number) => clamp(t, 0, Math.max(0, total));
