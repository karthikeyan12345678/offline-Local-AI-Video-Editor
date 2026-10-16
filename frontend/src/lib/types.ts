export type AssetKind = "video" | "image" | "audio";

export interface Asset {
  id: string; kind: AssetKind; name: string; thumb: boolean; duration: number;
  width: number; height: number; fps: number; has_audio: boolean; source: string;
  meta: Record<string, unknown>; created: number;
}

export interface Job {
  id: string; kind: string; title: string; lane: string;
  status: "queued" | "running" | "done" | "error" | "cancelled";
  progress: number; phase: string; result: { asset_id?: string; warnings?: string[] } | null;
  error: string | null; created: number; elapsed: number; eta: number | null;
}

export interface SystemInfo {
  version: string; os: string; cpu_count: number; ram_gb: number;
  gpu: { available: boolean; name: string; vram_gb: number; compute_capability: number[] | null; arch_supported: boolean; problem: string | null };
  torch: string | null; ffmpeg: boolean; warnings: string[]; profile: string; disk_free_gb: number;
  data_dir: string; requires_models: boolean; low_ram: boolean;
}

export interface Settings {
  profile: string; memory_mode: string; hf_endpoint: string; default_model: string;
  compute_dtype: string; keep_loaded: boolean; output_fps: number;
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
  id: string; label: string; note: string; kind: "base" | "model"; installed: boolean; installed_bytes: number;
  download: { status: string; total: number; done: number; speed: number; current: string; error: string | null };
}

export interface ToolInfo { id: string; label: string; description: string; accepts: AssetKind[] }

// ---- editor document (mirrors backend/ltxps/editor/project.py) ----
export interface Adjust { brightness: number; contrast: number; saturation: number; gamma: number; hue: number }
export interface Transition { type: string; duration: number }
export interface Clip {
  id: string; asset_id: string; trim_in: number; trim_out: number; image_duration: number; speed: number; reverse: boolean;
  volume: number; muted: boolean; fade_in: number; fade_out: number; fit: "fit" | "fill" | "stretch"; zoom: number; pan_x: number; pan_y: number;
  rotate: 0 | 90 | 180 | 270; flip_h: boolean; flip_v: boolean; adjust: Adjust; preset: string; blur: number; sharpen: number;
  vignette: boolean; denoise: boolean; transition: Transition;
}
export interface TextOverlay {
  id: string; text: string; start: number; duration: number; x: number; y: number; size: number; color: string;
  bold: boolean; box: boolean; box_opacity: number; fade_in: number; fade_out: number;
}
export interface AudioClip { id: string; asset_id: string; start: number; trim_in: number; trim_out: number; volume: number; fade_in: number; fade_out: number }
export interface Project {
  id: string; name: string; canvas: { width: number; height: number; fps: number; background: string };
  clips: Clip[]; texts: TextOverlay[]; audio: AudioClip[]; master_volume: number;
}
export interface ExportOptions { format: "mp4" | "webm" | "gif"; width?: number; height?: number; fps?: number; quality: "low" | "medium" | "high"; include_audio: boolean; preview: boolean }
