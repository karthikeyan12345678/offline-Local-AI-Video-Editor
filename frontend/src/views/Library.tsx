import { useMemo, useRef, useState } from "react";
import { api, mediaUrl } from "../lib/api";
import { fmtDuration } from "../lib/format";
import { saveAs } from "../lib/save";
import { useApp } from "../lib/store";
import { Button, Dialog, Empty, Field, Tabs, I } from "../ds";
import { Thumb } from "./shared";
import type { Asset, ToolInfo } from "../lib/types";
import { useEffect } from "react";

type Filter = "all" | "video" | "image" | "audio";
const PARAMS: Record<string, { key: string; label: string; min: number; max: number; def: number; step?: number }[]> = {
  upscale: [{ key: "factor", label: "Enlarge by", min: 1.5, max: 3, def: 2, step: 0.5 }],
  loop: [{ key: "times", label: "Repeat how many times", min: 2, max: 20, def: 3 }],
  interpolate: [{ key: "fps", label: "Target frames per second", min: 24, max: 120, def: 48 }],
  to_gif: [{ key: "width", label: "Width in pixels", min: 120, max: 960, def: 480, step: 20 }, { key: "fps", label: "Frames per second", min: 4, max: 20, def: 12 }],
};

export default function Library({ onEdit }: { onEdit: (a: Asset) => void }) {
  const { assets, refreshAssets, toast, watchJob } = useApp();
  const [filter, setFilter] = useState<Filter>("all");
  const [sel, setSel] = useState<Asset | null>(null);
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [uploading, setUploading] = useState(0);
  const [drag, setDrag] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [selecting, setSelecting] = useState(false);
  const toggle = (id: string) => setPicked((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const deletePicked = async () => {
    if (!picked.size || !confirm(`Delete ${picked.size} item${picked.size > 1 ? "s" : ""} from the library? The files are removed from disk.`)) return;
    let failed = 0;
    for (const id of picked) { try { await api.deleteAsset(id); } catch { failed++; } }
    setPicked(new Set()); setSelecting(false); await refreshAssets();
    toast(failed ? `${failed} item${failed > 1 ? "s" : ""} could not be deleted.` : "Deleted.", failed > 0);
  };
  useEffect(() => { api.tools().then(setTools).catch(() => {}); }, []);

  const items = useMemo(() => assets.filter((a) => filter === "all" || a.kind === filter), [assets, filter]);
  const current = sel ? assets.find((a) => a.id === sel.id) ?? null : null;

  const addFiles = async (files: FileList | File[]) => {
    for (const f of Array.from(files)) {
      setUploading((n) => n + 1);
      try { await api.upload(f); } catch (e) { toast(`${f.name}: ${(e as Error).message}`, true); } finally { setUploading((n) => n - 1); }
    }
    await refreshAssets();
  };

  return (
    <main className="page stack gap-lg" onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)} onDrop={(e) => { e.preventDefault(); setDrag(false); if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files); }}>
      <div className="row between gap wrap">
        <h1>Library</h1>
        <div className="row gap wrap">
          <Tabs label="Filter" value={filter} onChange={setFilter} options={[{ id: "all", label: "All" }, { id: "video", label: "Videos" }, { id: "image", label: "Pictures" }, { id: "audio", label: "Audio" }]} />
          <Button variant="secondary" active={selecting} onClick={() => { setSelecting(!selecting); setPicked(new Set()); }}>{selecting ? "Cancel select" : "Select"}</Button>
          <Button icon={I.upload} busy={uploading > 0} onClick={() => fileRef.current?.click()}>Add files</Button>
          <input ref={fileRef} type="file" hidden multiple accept="video/*,image/*,audio/*,.mkv,.webm,.mov,.gif" onChange={(e) => { if (e.target.files) addFiles(e.target.files); e.target.value = ""; }} />
        </div>
      </div>
      {selecting && (
        <div className="selbar row gap wrap" role="toolbar" aria-label="Selection">
          <span className="text-sm w-medium">{picked.size} selected</span>
          <Button variant="secondary" small onClick={() => setPicked(new Set(items.map((a) => a.id)))}>Select all shown</Button>
          <Button variant="secondary" small disabled={!picked.size} onClick={() => setPicked(new Set())}>Clear</Button>
          <Button small icon={I.trash} disabled={!picked.size} onClick={deletePicked}>Delete selected</Button>
        </div>
      )}
      {drag && <div className="dropzone" role="status">Drop files to add them</div>}
      {items.length === 0 ? (
        <Empty icon={I.folder} title={assets.length ? "Nothing in this filter" : "Your library is empty"}>Generated videos appear here. Drag videos, pictures and music anywhere into this window, or press Add files.</Empty>
      ) : (
        <ul className="grid-assets" aria-label="Library items">
          {items.map((a) => (
            <li key={a.id}>
              <button type="button" className={`tile${picked.has(a.id) ? " tile--picked" : ""}`} onClick={() => (selecting ? toggle(a.id) : setSel(a))} aria-label={selecting ? `Select ${a.name}` : `Open ${a.name}`} aria-pressed={selecting ? picked.has(a.id) : undefined}>
                {selecting && <span className={`pick-tick${picked.has(a.id) ? " pick-tick--on" : ""}`} aria-hidden="true">{picked.has(a.id) ? "✓" : ""}</span>}
                <Thumb asset={a} />
                <span className="stack tile-meta">
                  <span className="text-sm w-medium truncate">{a.name}</span>
                  <span className="text-xs">{a.kind}{a.duration ? ` · ${fmtDuration(a.duration)}` : ""}{a.width ? ` · ${a.width}×${a.height}` : ""}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {current && <AssetDialog asset={current} tools={tools} onClose={() => setSel(null)} onEdit={() => onEdit(current)} watchJob={watchJob} />}
    </main>
  );
}

function AssetDialog({ asset, tools, onClose, onEdit, watchJob }: { asset: Asset; tools: ToolInfo[]; onClose: () => void; onEdit: () => void; watchJob: ReturnType<typeof useApp>["watchJob"] }) {
  const { toast, refreshAssets } = useApp();
  const [name, setName] = useState(asset.name);
  const [tool, setTool] = useState<ToolInfo | null>(null);
  const [vals, setVals] = useState<Record<string, number>>({});
  const applicable = tools.filter((t) => t.accepts.includes(asset.kind));

  const run = async (t: ToolInfo, params: Record<string, number>) => {
    try {
      const j = await api.runTool(t.id, asset.id, params);
      watchJob(j, (d) => { if (d.status === "done") toast(`${t.label} finished. The result is in your library.`); });
      toast(`${t.label} started. Progress is shown in the side bar.`);
      setTool(null); onClose();
    } catch (e) { toast((e as Error).message, true); }
  };
  const pick = (t: ToolInfo) => {
    const p = PARAMS[t.id];
    if (!p) return run(t, {});
    setVals(Object.fromEntries(p.map((x) => [x.key, x.def]))); setTool(t);
  };
  const rename = async () => { if (name.trim() && name !== asset.name) { try { await api.renameAsset(asset.id, name.trim()); await refreshAssets(); } catch (e) { toast((e as Error).message, true); } } };

  return (
    <Dialog title={asset.name} onClose={onClose}>
      {asset.kind === "video" && <video className="player" src={mediaUrl(asset.id)} controls playsInline />}
      {asset.kind === "image" && <img className="player" src={mediaUrl(asset.id)} alt={asset.name} />}
      {asset.kind === "audio" && <audio src={mediaUrl(asset.id)} controls style={{ width: "100%" }} />}
      <Field label="Name" htmlFor="nm"><input id="nm" className="input" value={name} onChange={(e) => setName(e.target.value)} onBlur={rename} onKeyDown={(e) => { if (e.key === "Enter") rename(); }} /></Field>
      {asset.meta.prompt != null && <p className="text-sm"><b>Prompt:</b> {String(asset.meta.prompt)}</p>}
      {tool ? (
        <div className="card stack gap">
          <h3>{tool.label}</h3><p className="text-sm">{tool.description}</p>
          {PARAMS[tool.id].map((p) => (
            <Field key={p.key} label={`${p.label}: ${vals[p.key]}`}><input className="range" type="range" min={p.min} max={p.max} step={p.step ?? 1} value={vals[p.key]} onChange={(e) => setVals({ ...vals, [p.key]: Number(e.target.value) })} /></Field>
          ))}
          <div className="row gap"><Button onClick={() => run(tool, vals)}>Start</Button><Button variant="ghost" onClick={() => setTool(null)}>Back</Button></div>
        </div>
      ) : (
        <div className="stack">
          <h3>Quick tools</h3>
          <div className="row gap wrap">{applicable.map((t) => <Button key={t.id} variant="secondary" small title={t.description} onClick={() => pick(t)}>{t.label}</Button>)}</div>
        </div>
      )}
      <div className="row between gap wrap">
        <div className="row gap">
          {asset.kind !== "image" || true ? <Button icon={I.film} onClick={onEdit}>Add to editor</Button> : null}
          <Button variant="secondary" onClick={() => void saveAs(mediaUrl(asset.id, "download"), asset.name)}>Save as…</Button>
        </div>
        <Button variant="ghost" icon={I.trash} onClick={async () => { if (confirm("Delete this item from the library? The file is removed from disk.")) { try { await api.deleteAsset(asset.id); await refreshAssets(); onClose(); } catch (e) { toast((e as Error).message, true); } } }}>Delete</Button>
      </div>
    </Dialog>
  );
}
