export type AssetKind = "video" | "image" | "audio";

export interface Asset {
  id: string; kind: AssetKind; name: string; thumb: boolean; duration: number;
  width: number; height: number; fps: number; has_audio: boolean; source: string;
  meta: Record<string, unknown>; created: number;
}

export interface Job {
  id: string; kind: string; title: string; lane: string;
  status: "queued" | "running" | "done" | "error" | "cancelled";
  progress: number; phase: string; // eslint-disable-next-line @typescript-eslint/no-explicit-any
  result: Record<string, any> | null;
  error: string | null; created: number; elapsed: number; eta: number | null; expected?: number; note?: string;
}

export interface Estimate { seconds: number; low: number; high: number; device: "gpu" | "cpu"; band: "fast" | "ok" | "slow" | "too_long"; notes: string[]; tips: string[]; limit_seconds: number | null }
export interface Usage { cpu: number | null; ram_used_gb: number | null; ram_total_gb: number | null; gpu: number | null; vram_used_gb: number | null; vram_total_gb: number | null; gpu_temp_c?: number | null; why_slow?: string | null }

export interface SystemInfo {
  version: string; os: string; cpu_count: number; ram_gb: number;
  gpu: { available: boolean; name: string; vram_gb: number; compute_capability: number[] | null; arch_supported: boolean; problem: string | null };
  torch: string | null; ffmpeg: boolean; warnings: string[]; profile: string; disk_free_gb: number;
  data_dir: string; requires_models: boolean; low_ram: boolean;
}

export interface Settings {
  profile: string; memory_mode: string; hf_endpoint: string; default_model: string;
  compute_dtype: string; keep_loaded: boolean; output_fps: number; time_limit_min: number; tour_done: boolean; sharpen_output: boolean; auto_enhance: boolean; ai_upscale: boolean;
}

export interface Limits {
  profile: {
    id: string; label: string; description: string; max_frames: number; max_side: number; max_tokens: number;
    default_width: number; default_height: number; default_frames: number;
    resolutions: { label: string; width: number; height: number }[];
  };
  profiles: { id: string; label: string; description: string }[];
  models: { id: string; label: string; note: string; distilled: boolean; default_steps: number; default_guidance: number; min_steps: number; max_steps: number }[];
  default_model: string; fps: number;
}

export interface ModelRow {
  id: string; label: string; note: string; kind: "base" | "model" | "captions" | "image"; installed: boolean; installed_bytes: number;
  download: { status: string; total: number; done: number; speed: number; current: string; error: string | null };
}

export interface ToolInfo { id: string; label: string; description: string; accepts: AssetKind[] }

// ---- editor document (mirrors backend/ltxps/editor/project.py) ----
export interface Adjust { brightness: number; contrast: number; saturation: number; gamma: number; hue: number }
export interface Transition { type: string; duration: number }
export interface Effect { type: string; amount: number }
export interface Chroma { enabled: boolean; color: string; similarity: number; blend: number; spill: boolean }
export type Ease = "smooth" | "linear" | "hold";
export interface Key { t: number; x: number; y: number; size: number; rotation: number; opacity: number; ease: Ease }
export interface Follow { keys: [number, number, number][]; zoom: number }
export interface Clip {
  id: string; asset_id: string; trim_in: number; trim_out: number; image_duration: number; speed: number; reverse: boolean;
  volume: number; muted: boolean; fade_in: number; fade_out: number; fit: "fit" | "fill" | "stretch"; zoom: number; pan_x: number; pan_y: number;
  rotate: 0 | 90 | 180 | 270; flip_h: boolean; flip_v: boolean; adjust: Adjust; preset: string; blur: number; sharpen: number;
  vignette: boolean; denoise: boolean; transition: Transition;
  motion: string; motion_strength: number; effects: Effect[]; follow: Follow | null;
  audio_fx: string; pitch: number; bass: number; treble: number; denoise_audio: boolean; normalize_audio: boolean;
  chroma: Chroma;
}
export interface TextOverlay {
  id: string; text: string; start: number; duration: number; x: number; y: number; size: number; color: string;
  bold: boolean; box: boolean; box_opacity: number; fade_in: number; fade_out: number;
  font: string; italic: boolean; uppercase: boolean; align: "left" | "center" | "right"; letter_spacing: number; line_spacing: number;
  color2: string | null; stroke: number; stroke_color: string; shadow: number; shadow_color: string; glow: number; glow_color: string;
  box_color: string; rotation: number; opacity: number; anim_in: string; anim_out: string; keys: Key[];
}
export interface AudioClip {
  id: string; asset_id: string; start: number; trim_in: number; trim_out: number; volume: number; fade_in: number; fade_out: number;
  fx: string; pitch: number; bass: number; treble: number; denoise: boolean; normalize: boolean; loop: boolean; is_music: boolean;
}
export type ShapeType = "pen" | "highlight" | "line" | "arrow" | "rect" | "ellipse";
export interface Shape { type: ShapeType; points: [number, number][]; color: string; width: number; opacity: number; filled: boolean; fill_color: string | null; fill_opacity: number }
export interface Drawing { id: string; start: number; duration: number; shapes: Shape[]; opacity: number; fade_in: number; fade_out: number; anim_in: string; anim_out: string }
export interface ImageOverlay { id: string; asset_id: string; start: number; duration: number; x: number; y: number; size: number; rotation: number; opacity: number; fade_in: number; fade_out: number; anim_in: string; anim_out: string; keys: Key[] }
export interface Layer {
  id: string; asset_id: string; track: number; behind: boolean; start: number; trim_in: number; trim_out: number; image_duration: number; speed: number; volume: number; muted: boolean;
  x: number; y: number; size: number; rotation: number; opacity: number; fade_in: number; fade_out: number; adjust: Adjust; preset: string; blur: number; effects: Effect[]; chroma: Chroma; mask: string; mask_feather: number; mask_invert: boolean; keys: Key[];
}
export interface Project {
  id: string; name: string; canvas: { width: number; height: number; fps: number; background: string };
  clips: Clip[]; texts: TextOverlay[]; audio: AudioClip[]; drawings: Drawing[]; images: ImageOverlay[]; layers: Layer[]; master_volume: number;
  duck_music: boolean; duck_amount: number; master_normalize: boolean;
}
export interface Catalog {
  transitions: { id: string; label: string; group: string }[];
  looks: { id: string; label: string; group?: string }[];
  effects: { id: string; label: string; group?: string }[];
  masks: { id: string; label: string }[];
  motions: { id: string; label: string }[];
  audio_fx: { id: string; label: string; group: string }[];
  fonts: { id: string; label: string; category: string; scripts: string[]; bold: boolean }[];
  text_anim_in: string[]; text_anim_out: string[];
  whisper: { id: string; label: string; installed: boolean }[];
}
export interface ExportOptions { format: "mp4" | "webm" | "gif"; width?: number; height?: number; fps?: number; quality: "low" | "medium" | "high"; include_audio: boolean; preview: boolean }

export interface UpdateInfo {
  current: string; latest: string; app_update: boolean; download_url: string; notes: string; modules_update: boolean;
  modules: { name: string; label: string; installed: string | null; latest: string; update: boolean; missing: boolean }[];
}
