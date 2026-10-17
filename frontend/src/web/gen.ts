// The AI video functions of the website. Each one sends the job to a free GPU Space on Hugging Face and returns the finished video.
/* eslint-disable @typescript-eslint/no-explicit-any */
import { ApiError } from "../lib/api";
import { fileFor, handle_file, HFError, loadHF, runSpace, type Stage } from "./hf";

export interface Rec { id: string; name: string; kind: string; duration: number; width: number; height: number }
export interface Helpers {
  mustAsset(id: string): Promise<Rec>;
  blobOf(id: string): Promise<Blob | undefined>;
  stage(s: Stage): void;
  signal: { cancelled: boolean; on(fn: () => void): void };
}
export interface Made { blob: Blob; name: string; meta: Record<string, unknown> }

const snap = (n: number, lo = 256, hi = 1280) => Math.max(lo, Math.min(hi, Math.round(n / 32) * 32));
export const SIZES: Record<string, Record<string, [number, number]>> = {
  fast: { "16:9": [704, 384], "9:16": [384, 704], "1:1": [512, 512], "4:5": [512, 640] },
  good: { "16:9": [1024, 576], "9:16": [576, 1024], "1:1": [768, 768], "4:5": [704, 864] },
};

/** The last picture of a video, as a PNG (the new clip starts from it). */
export async function lastFrame(blob: Blob): Promise<Blob> {
  const url = URL.createObjectURL(blob);
  try {
    const v = document.createElement("video");
    v.muted = true; v.preload = "auto"; v.src = url;
    await new Promise<void>((res, rej) => { v.onloadeddata = () => res(); v.onerror = () => rej(new ApiError("The browser could not read that clip. Use an MP4 (H.264) or WebM.", 422)); });
    v.currentTime = Math.max(0, (Number.isFinite(v.duration) ? v.duration : 1) - 0.05);
    await new Promise<void>((res) => { v.onseeked = () => res(); });
    const c = document.createElement("canvas"); c.width = v.videoWidth; c.height = v.videoHeight;
    c.getContext("2d")!.drawImage(v, 0, 0);
    return await new Promise<Blob>((res, rej) => c.toBlob((b) => (b ? res(b) : rej(new ApiError("The last picture could not be read.", 422))), "image/png"));
  } finally { URL.revokeObjectURL(url); }
}

export interface VideoBody { mode: "t2v" | "i2v" | "extend"; prompt: string; negative?: string; aspect: string; quality: "fast" | "good"; seconds: number; seed?: number | null; image_asset_id?: string; source_asset_id?: string }

/** Text to video, picture to video, and "continue this clip" (the clip's last picture starts the next one). */
export async function makeVideo(h: Helpers, b: VideoBody): Promise<Made> {
  const cfg = loadHF();
  if (!b.prompt.trim() && b.mode !== "i2v") throw new ApiError("Describe what should happen.", 422);
  const [w0, h0] = (SIZES[b.quality] ?? SIZES.fast)[b.aspect] ?? SIZES.fast["16:9"];
  const width = snap(w0), height = snap(h0);
  const seconds = Math.max(0.5, Math.min(8, Number(b.seconds) || 2));
  let image: File | null = null;
  if (b.mode === "i2v") {
    const a = await h.mustAsset(b.image_asset_id ?? "");
    const blob = await h.blobOf(a.id);
    if (a.kind !== "image" || !blob) throw new ApiError("Choose a picture from your library as the first frame.", 422);
    image = fileFor(blob, "start.png");
  } else if (b.mode === "extend") {
    const a = await h.mustAsset(b.source_asset_id ?? "");
    const blob = await h.blobOf(a.id);
    if (a.kind !== "video" || !blob) throw new ApiError("Choose a video from your library to continue.", 422);
    h.stage({ phase: "Taking the last picture of your clip", fraction: 0.01 });
    image = fileFor(await lastFrame(blob), "last-frame.png");
  }
  const fromImage = !!image;
  const endpoint = fromImage ? "/image_to_video" : "/text_to_video";
  const payload: Record<string, unknown> = {
    prompt: b.prompt.trim() || "The scene comes to life with natural, smooth motion",
    negative_prompt: (b.negative ?? "").trim() || "worst quality, inconsistent motion, blurry, jittery, distorted",
    input_image_filepath: image ? handle_file(image) : null,
    input_video_filepath: null,
    height_ui: height, width_ui: width,
    mode: fromImage ? "image-to-video" : "text-to-video",
    duration_ui: seconds,
    ui_frames_to_use: 9,
    seed_ui: b.seed != null && Number.isFinite(b.seed) ? Math.round(b.seed) : 42,
    randomize_seed: !(b.seed != null && Number.isFinite(b.seed)),
    ui_guidance_scale: 1,
    improve_texture_flag: b.quality === "good",
  };
  // input_image_filepath stays null for text-to-video: Gradio treats a missing value as an error unless the Space gave it a default
  const params = ["prompt", "height_ui", "width_ui", "duration_ui", ...(fromImage ? ["input_image_filepath"] : [])];
  const r = await runSpace({ space: cfg.ltx, endpoint, params, payload, onStage: h.stage, signal: h.signal });
  const seed = Array.isArray(r.data) && typeof r.data[1] === "number" ? r.data[1] : null;
  const label = b.mode === "extend" ? "Continues" : b.mode === "i2v" ? "Picture to video" : "Text to video";
  return { blob: r.blob, name: `${label} - ${b.prompt.trim().slice(0, 36) || "clip"}.mp4`, meta: { prompt: b.prompt.trim(), seed, width, height, seconds, space: cfg.ltx, mode: b.mode, gpu_seconds: r.seconds } };
}

export interface MotionBody { image_asset_id: string; video_asset_id: string; mode: "Character Swap" | "Pose Retarget"; quality: "Low Res" | "Medium Res"; seconds: number }

/** Motion control: the character in the picture repeats the movement of the person in the video (Wan 2.2 Animate). */
export async function motionControl(h: Helpers, b: MotionBody): Promise<Made> {
  const cfg = loadHF();
  const img = await h.mustAsset(b.image_asset_id), vid = await h.mustAsset(b.video_asset_id);
  const ib = await h.blobOf(img.id), vb = await h.blobOf(vid.id);
  if (img.kind !== "image" || !ib) throw new ApiError("Add a character picture first.", 422);
  if (vid.kind !== "video" || !vb) throw new ApiError("Add the motion video first.", 422);
  if (vid.duration > 30) throw new ApiError("Use a motion video of 3 to 30 seconds. Trim it in the editor first.", 422);
  const payload = {
    input_video: handle_file(fileFor(vb, "motion.mp4")), max_duration_s: Math.max(2, Math.min(20, Math.round(b.seconds || 2))),
    edited_frame: handle_file(fileFor(ib, "character.png")), rc_str: b.mode, resolution_choice: b.quality,
  };
  const r = await runSpace({ space: cfg.animate, endpoint: "/animate_scene", params: ["input_video", "max_duration_s", "edited_frame", "rc_str", "resolution_choice"], payload, onStage: h.stage, signal: h.signal });
  return { blob: r.blob, name: `Motion control - ${img.name.replace(/\.[^.]+$/, "")}.mp4`, meta: { mode: b.mode, quality: b.quality, space: cfg.animate, gpu_seconds: r.seconds } };
}

export { HFError };
