import { useEffect, useRef, useState } from "react";
import { api, mediaUrl } from "../lib/api";
import { fmtDuration } from "../lib/format";
import { useApp } from "../lib/store";
import { Icon, I } from "../ds";
import { Thumb } from "./shared";

/** One picture or video slot: drop a file, upload, choose from the library, replace, or remove it with the × button. */
export default function MediaSlot({ kind, value, onChange, label, hint, compact = false }: {
  kind: "image" | "video"; value: string | null; onChange: (id: string | null) => void; label: string; hint?: string; compact?: boolean;
}) {
  const { assets, asset, refreshAssets, toast } = useApp();
  const [open, setOpen] = useState(false);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const file = useRef<HTMLInputElement>(null);
  const cur = value ? asset(value) : undefined;
  const items = assets.filter((a) => a.kind === kind).sort((a, b) => b.created - a.created);

  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", away); document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", esc); };
  }, [open]);

  const take = async (files: FileList | File[] | null) => {
    const f = files && Array.from(files).find((x) => x.type.startsWith(kind + "/") || (kind === "video" && /\.(mkv|webm|mov)$/i.test(x.name)));
    if (!f) { if (files && files.length) toast(`Please choose a ${kind}.`, true); return; }
    setBusy(true);
    try { const a = await api.upload(f); await refreshAssets(); onChange(a.id); setOpen(false); } catch (e) { toast((e as Error).message, true); } finally { setBusy(false); }
  };

  return (
    <div className={`slot${compact ? " slot--compact" : ""}${over ? " slot--over" : ""}`} ref={box}
      onDragOver={(e) => { if (e.dataTransfer.types.includes("Files")) { e.preventDefault(); e.stopPropagation(); setOver(true); } }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { if (e.dataTransfer.files.length) { e.preventDefault(); e.stopPropagation(); setOver(false); void take(e.dataTransfer.files); } }}>
      <input ref={file} type="file" hidden accept={kind === "image" ? "image/png,image/jpeg,image/webp" : "video/*,.mkv,.webm,.mov"} onChange={(e) => { void take(e.target.files); e.target.value = ""; }} />
      {cur ? (
        <div className="slot-filled">
          <div className="slot-media">
            {kind === "video" ? <video src={mediaUrl(cur.id)} muted playsInline preload="metadata" controls={!compact} /> : <Thumb asset={cur} />}
            <button type="button" className="slot-x" aria-label={`Remove ${label}`} title="Remove" onClick={() => onChange(null)}><Icon d={I.x} size={14} /></button>
          </div>
          <div className="slot-info"><span className="slot-label">{label}</span><span className="slot-name truncate" title={cur.name}>{cur.name}{kind === "video" ? ` · ${fmtDuration(cur.duration)}` : ""}</span>
            <span className="row gap"><button type="button" className="slot-link" onClick={() => file.current?.click()} disabled={busy}>{busy ? "Uploading…" : "Upload another"}</button><button type="button" className="slot-link" onClick={() => setOpen(!open)} aria-expanded={open}>From library</button></span></div>
        </div>
      ) : (
        <div className="slot-empty">
          <Icon d={kind === "image" ? I.image : I.film} size={22} />
          <span className="slot-label">{label}</span>
          {hint && <span className="text-xs slot-hint">{hint}</span>}
          <span className="row gap center-v"><button type="button" className="slot-btn" onClick={() => file.current?.click()} disabled={busy}><Icon d={I.upload} size={14} />{busy ? "Uploading…" : "Upload"}</button>
            <button type="button" className="slot-btn slot-btn--ghost" onClick={() => setOpen(!open)} aria-expanded={open}>From library</button></span>
          <span className="text-xs slot-hint">or drop a file here</span>
        </div>
      )}
      {open && (
        <div className="slot-pop" role="listbox" aria-label={`${label} library`}>
          {items.length === 0 ? <p className="text-sm slot-hint">No {kind}s in your library yet. Upload one.</p> : items.map((a) => (
            <button key={a.id} type="button" role="option" aria-selected={value === a.id} className={`slot-tile${value === a.id ? " on" : ""}`} onClick={() => { onChange(a.id); setOpen(false); }} title={a.name}>
              <Thumb asset={a} /><span className="text-xs truncate">{a.name}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
