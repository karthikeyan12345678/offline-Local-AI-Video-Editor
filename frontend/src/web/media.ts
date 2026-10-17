// Files the person adds live in IndexedDB; the page shows them through blob: URLs kept here.
import type { Asset, AssetKind } from "../lib/types";
import { idb } from "../../../shared/web/idb";

interface Urls { file: string; thumb: string }
const urls = new Map<string, Urls>();
export const webMediaUrl = (id: string, what: "file" | "thumb" | "download"): string => {
  const u = urls.get(id);
  return !u ? "" : what === "thumb" ? u.thumb : u.file;
};

export async function blobOf(id: string): Promise<Blob | undefined> { return idb.get<Blob>("blobs", id); }

export async function hydrate(a: Asset): Promise<void> {
  if (urls.has(a.id)) return;
  const blob = await blobOf(a.id);
  if (!blob) return;
  const thumb = await idb.get<string>("blobs", a.id + ":thumb");
  urls.set(a.id, { file: URL.createObjectURL(blob), thumb: typeof thumb === "string" ? thumb : "" });
}

export function forget(id: string): void {
  const u = urls.get(id);
  if (u) URL.revokeObjectURL(u.file);
  urls.delete(id);
}

export function kindOf(file: { name: string; type: string }): AssetKind | null {
  const t = file.type;
  if (t.startsWith("video/")) return "video";
  if (t.startsWith("audio/")) return "audio";
  if (t.startsWith("image/")) return "image";
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
  if (["mp4", "mov", "m4v", "webm", "mkv", "avi"].includes(ext)) return "video";
  if (["mp3", "wav", "m4a", "aac", "ogg", "flac", "opus"].includes(ext)) return "audio";
  if (["png", "jpg", "jpeg", "webp", "gif", "bmp"].includes(ext)) return "image";
  return null;
}

const wait = (el: HTMLMediaElement | HTMLImageElement, ok: string, ms = 15000) => new Promise<void>((resolve, reject) => {
  const t = setTimeout(() => reject(new Error("The browser could not read this file.")), ms);
  el.addEventListener(ok, () => { clearTimeout(t); resolve(); }, { once: true });
  el.addEventListener("error", () => { clearTimeout(t); reject(new Error("The browser could not read this file. Try an MP4 (H.264), WebM, MP3 or PNG/JPG.")); }, { once: true });
});

function shrink(src: CanvasImageSource, w: number, h: number): string {
  const max = 160, sc = Math.min(1, max / Math.max(w, h, 1));
  const c = document.createElement("canvas");
  c.width = Math.max(1, Math.round(w * sc)); c.height = Math.max(1, Math.round(h * sc));
  c.getContext("2d")?.drawImage(src, 0, 0, c.width, c.height);
  return c.toDataURL("image/jpeg", 0.7);
}

export interface Probed { duration: number; width: number; height: number; thumb: string }

/** Duration, size and a small preview picture, using the browser's own decoders. */
export async function probe(file: Blob, kind: AssetKind): Promise<Probed> {
  const url = URL.createObjectURL(file);
  try {
    if (kind === "image") {
      const img = new Image(); img.src = url; await wait(img, "load");
      return { duration: 0, width: img.naturalWidth, height: img.naturalHeight, thumb: shrink(img, img.naturalWidth, img.naturalHeight) };
    }
    if (kind === "audio") {
      const a = new Audio(); a.preload = "metadata"; a.src = url; await wait(a, "loadedmetadata");
      return { duration: Number.isFinite(a.duration) ? a.duration : 0, width: 0, height: 0, thumb: "" };
    }
    const v = document.createElement("video"); v.preload = "auto"; v.muted = true; v.playsInline = true; v.src = url;
    await wait(v, "loadeddata");
    const w = v.videoWidth, h = v.videoHeight, d = Number.isFinite(v.duration) ? v.duration : 0;
    let thumb = "";
    try {
      v.currentTime = Math.min(0.5, d / 4);
      await wait(v, "seeked", 4000);
      thumb = shrink(v, w, h);
    } catch { try { thumb = shrink(v, w, h); } catch { /* no preview picture */ } }
    return { duration: d, width: w, height: h, thumb };
  } finally { URL.revokeObjectURL(url); }
}

export async function saveThumb(id: string, thumb: string): Promise<void> { if (thumb) await idb.put("blobs", id + ":thumb", thumb); }
