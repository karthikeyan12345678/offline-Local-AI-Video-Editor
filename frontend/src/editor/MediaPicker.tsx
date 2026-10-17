import { useEffect, useMemo, useRef, useState } from "react";
import { mediaUrl } from "../lib/api";
import { fmtDuration } from "../lib/format";
import { Button, Icon, I } from "../ds";
import { Thumb } from "../views/shared";
import type { Asset } from "../lib/types";

type Cat = "all" | "video" | "image" | "voice" | "sound" | "upload";
const CATS: { id: Cat; label: string; icon: string }[] = [
  { id: "all", label: "All", icon: "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z" }, { id: "video", label: "Videos", icon: I.film }, { id: "image", label: "Images", icon: I.image },
  { id: "voice", label: "Voices", icon: "M12 4a3 3 0 0 1 3 3v5a3 3 0 0 1-6 0V7a3 3 0 0 1 3-3zM6 11a6 6 0 0 0 12 0M12 17v3" }, { id: "sound", label: "Sound & music", icon: I.music }, { id: "upload", label: "Uploads", icon: I.upload },
];
const isVoice = (a: Asset) => a.kind === "audio" && (a.meta?.tool === "tts" || /voice/i.test(a.name));
const inCat = (a: Asset, c: Cat) => c === "all" || (c === "video" && a.kind === "video") || (c === "image" && a.kind === "image") || (c === "voice" && isVoice(a)) || (c === "sound" && a.kind === "audio" && !isVoice(a)) || (c === "upload" && a.source === "import");

/** Flow-style media picker: categories on the left, search and sort on top, a big preview on the right.
 *  mode "timeline" adds the chosen file to the video; mode "reference" only lets you pick pictures for the AI chat. */
export default function MediaPicker({ assets, mode, projectName, onPick, onUpload, onClose }: {
  assets: Asset[]; mode: "timeline" | "reference" | "layer"; projectName: string; onPick: (a: Asset) => void; onUpload: (f: FileList) => void; onClose: () => void;
}) {
  const [cat, setCat] = useState<Cat>(mode === "reference" ? "image" : "all");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<"recent" | "name" | "long">("recent");
  const [cur, setCur] = useState<Asset | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const file = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const away = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) onClose(); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    const t = setTimeout(() => document.addEventListener("mousedown", away), 0);
    document.addEventListener("keydown", esc);
    return () => { clearTimeout(t); document.removeEventListener("mousedown", away); document.removeEventListener("keydown", esc); };
  }, [onClose]);

  const items = useMemo(() => {
    const list = assets.filter((a) => inCat(a, cat) && (!q.trim() || a.name.toLowerCase().includes(q.trim().toLowerCase())));
    return [...list].sort((a, b) => sort === "name" ? a.name.localeCompare(b.name) : sort === "long" ? b.duration - a.duration : b.created - a.created);
  }, [assets, cat, q, sort]);
  const ok = (a: Asset) => mode === "timeline" || (mode === "layer" ? a.kind !== "audio" : a.kind === "image");

  return (
    <div className="mp" ref={box} role="dialog" aria-label="Choose media">
      <div className="mp-top">
        <span className="mp-proj" title="The project you are editing">{projectName || "Untitled project"}</span>
        <label className="mp-search"><Icon d="M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM21 21l-5-5" size={16} /><input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search assets" aria-label="Search assets" /></label>
        <select className="mp-sort" aria-label="Sort" value={sort} onChange={(e) => setSort(e.target.value as typeof sort)}><option value="recent">Recent</option><option value="name">Name</option><option value="long">Longest</option></select>
        <Button variant="ghost" small icon={I.x} label="Close" onClick={onClose} />
      </div>
      <div className="mp-body">
        <nav className="mp-nav" aria-label="Categories">
          {CATS.map((c) => <button key={c.id} type="button" className={`mp-cat${cat === c.id ? " on" : ""}`} aria-pressed={cat === c.id} onClick={() => setCat(c.id)}><Icon d={c.icon} size={18} />{c.label}</button>)}
          <span className="grow" />
          <input ref={file} type="file" hidden multiple accept={mode === "reference" ? "image/png,image/jpeg,image/webp" : "video/*,image/*,audio/*,.mkv,.webm,.mov,.gif"} onChange={(e) => { if (e.target.files?.length) onUpload(e.target.files); e.target.value = ""; }} />
          <button type="button" className="mp-upload" onClick={() => file.current?.click()}><Icon d={I.upload} size={18} />Upload media</button>
        </nav>
        <div className="mp-grid" role="listbox" aria-label="Assets">
          {items.length === 0 ? (
            <div className="mp-empty"><svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M12 21v-7M12 14c-3 0-5-2-5-5 3 0 5 2 5 5zM12 14c3 0 5-2 5-5-3 0-5 2-5 5zM12 8a2 2 0 1 0 0-.01" /></svg><p>No assets found.</p></div>
          ) : items.map((a) => (
            <button key={a.id} type="button" role="option" aria-selected={cur?.id === a.id} className={`mp-tile${cur?.id === a.id ? " on" : ""}${ok(a) ? "" : " dim"}`} disabled={!ok(a)} title={ok(a) ? a.name : "Only pictures can be used as a reference"}
              onClick={() => setCur(a)} onDoubleClick={() => ok(a) && onPick(a)}>
              <Thumb asset={a} /><span className="text-xs truncate">{a.name}</span>{a.duration > 0 && <span className="mp-dur text-xs mono">{fmtDuration(a.duration)}</span>}
            </button>
          ))}
        </div>
        <aside className="mp-prev" aria-label="Preview">
          {cur ? (
            <>
              <div className="mp-media">
                {cur.kind === "video" ? <video src={mediaUrl(cur.id)} controls muted playsInline /> : cur.kind === "audio" ? <audio src={mediaUrl(cur.id)} controls /> : <img src={mediaUrl(cur.id)} alt={cur.name} />}
              </div>
              <b className="truncate">{cur.name}</b>
              <span className="text-xs">{cur.kind}{cur.width ? ` · ${cur.width}×${cur.height}` : ""}{cur.duration ? ` · ${fmtDuration(cur.duration)}` : ""}{cur.has_audio && cur.kind === "video" ? " · has sound" : ""}</span>
              <Button icon={I.plus} disabled={!ok(cur)} onClick={() => onPick(cur)}>{mode === "timeline" ? "Add to timeline" : mode === "layer" ? "Add as layer" : "Use as reference"}</Button>
            </>
          ) : <p className="text-sm mp-hint">{mode === "timeline" ? "Pick a video, picture or sound to preview it. Double-click to add it to the timeline." : mode === "layer" ? "Pick a video or picture to play on top of your video at the same time. Double-click to add it." : "Pick a picture for the AI to look at. Double-click to attach it."}</p>}
        </aside>
      </div>
    </div>
  );
}
