import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, mediaUrl } from "../lib/api";
import { clamp, fmtTime } from "../lib/format";
import { useApp } from "../lib/store";
import { Button, Dialog, Icon, I } from "../ds";
import Preview from "../editor/Preview";
import Timeline from "../editor/Timeline";
import Inspector, { type Selection } from "../editor/Inspector";
import ExportDialog from "../editor/ExportDialog";
import { layout, newAudio, newClip, newProject, newText, splitAt } from "../editor/model";
import { useHistory } from "../editor/useHistory";
import { Thumb, JobCard } from "./shared";
import type { Asset, Project } from "../lib/types";

const KEY = "ltxps_project";
const remembered = () => { try { return localStorage.getItem(KEY); } catch { return null; } };
const remember = (id: string) => { try { localStorage.setItem(KEY, id); } catch { /* private mode */ } };

export default function Editor({ queue, onQueueDone, visible }: { queue: Asset[]; onQueueDone: () => void; visible: boolean }) {
  const { asset, assets, jobs, watchJob, toast } = useApp();
  const h = useHistory<Project>(useMemo(newProject, []));
  const project = h.value;
  const [sel, setSel] = useState<Selection>(null);
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [zoom, setZoom] = useState(60);
  const [exporting, setExporting] = useState(false);
  const [projects, setProjects] = useState<{ id: string; name: string }[] | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [saveState, setSaveState] = useState<"saved" | "saving" | "error">("saved");
  const [rendered, setRendered] = useState<string | null>(null);
  const [previewJob, setPreviewJob] = useState<string | null>(null);
  const [bin, setBin] = useState<"all" | "video" | "image" | "audio">("all");
  const dirty = useRef(false);

  const { total } = layout(project, asset);
  useEffect(() => { if (!visible) setPlaying(false); }, [visible]);

  // ---- load the last project once
  useEffect(() => {
    const id = remembered();
    if (!id) { setLoaded(true); return; }
    api.loadProject(id).then((p) => h.reset({ ...newProject(), ...p, canvas: { ...newProject().canvas, ...p.canvas } })).catch(() => {}).finally(() => setLoaded(true));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ---- autosave (debounced). Skips until the user actually changed something.
  const first = useRef(true);
  useEffect(() => {
    if (!loaded) return;
    if (first.current) { first.current = false; return; }
    dirty.current = true; setSaveState("saving"); setRendered(null);
    const t = setTimeout(() => api.saveProject(project.id, project).then(() => { remember(project.id); dirty.current = false; setSaveState("saved"); }).catch(() => setSaveState("error")), 900);
    return () => clearTimeout(t);
  }, [project, loaded]);

  const commit = h.commit;
  const mutate = useCallback((fn: (p: Project) => Project, key?: string) => commit(fn, key), [commit]);

  // ---- adding media
  const addAsset = useCallback((a: Asset) => {
    if (a.kind === "audio") { commit((p) => { const n = newAudio(a, 0); return { ...p, audio: [...p.audio, n] }; }); return; }
    commit((p) => {
      const clip = newClip(a);
      const first = p.clips.length === 0 && a.width > 0;
      const canvas = first ? { ...p.canvas, width: a.width - (a.width % 2), height: a.height - (a.height % 2), fps: a.fps > 0 ? Math.round(clamp(a.fps, 12, 60)) : p.canvas.fps } : p.canvas;
      return { ...p, canvas, clips: [...p.clips, clip] };
    });
  }, [commit]);

  useEffect(() => {
    if (!queue.length || !loaded) return;
    queue.forEach(addAsset);
    onQueueDone();
  }, [queue, loaded]); // eslint-disable-line react-hooks/exhaustive-deps

  const addText = () => { const t = newText(clamp(time, 0, Math.max(0, total))); commit((p) => ({ ...p, texts: [...p.texts, t] })); setSel({ type: "text", id: t.id }); };

  // ---- actions on the selection
  const remove = useCallback(() => {
    if (!sel) return;
    commit((p) => ({ ...p, clips: sel.type === "clip" ? p.clips.filter((c) => c.id !== sel.id) : p.clips, texts: sel.type === "text" ? p.texts.filter((c) => c.id !== sel.id) : p.texts, audio: sel.type === "audio" ? p.audio.filter((c) => c.id !== sel.id) : p.audio }));
    setSel(null);
  }, [sel, commit]);
  const duplicate = () => {
    if (!sel) return;
    commit((p) => {
      if (sel.type === "clip") { const i = p.clips.findIndex((c) => c.id === sel.id); if (i < 0) return p; const copy = { ...p.clips[i], id: Math.random().toString(36).slice(2, 10) }; const clips = [...p.clips]; clips.splice(i + 1, 0, copy); return { ...p, clips }; }
      if (sel.type === "text") { const t = p.texts.find((x) => x.id === sel.id); return t ? { ...p, texts: [...p.texts, { ...t, id: Math.random().toString(36).slice(2, 10), start: t.start + t.duration }] } : p; }
      const a = p.audio.find((x) => x.id === sel.id);
      return a ? { ...p, audio: [...p.audio, { ...a, id: Math.random().toString(36).slice(2, 10), start: a.start + 1 }] } : p;
    });
  };
  const split = useCallback(() => {
    const next = splitAt(project, time, asset);
    if (!next) { toast("Move the playhead inside a clip (not at its very edge) to split it.", true); return; }
    commit(next);
  }, [project, time, asset, commit, toast]);

  // ---- keyboard
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (el.closest("input, textarea, select, [contenteditable]") || el.closest("[role=dialog]")) return;
      const mod = e.ctrlKey || e.metaKey;
      if (mod && e.key.toLowerCase() === "z") { e.preventDefault(); e.shiftKey ? h.redo() : h.undo(); }
      else if (mod && e.key.toLowerCase() === "y") { e.preventDefault(); h.redo(); }
      else if (e.key === " " && el.tagName !== "BUTTON") { e.preventDefault(); togglePlay(); }
      else if (e.key.toLowerCase() === "s" && !mod) { e.preventDefault(); split(); }
      else if (e.key === "Delete" || e.key === "Backspace") { if (sel) { e.preventDefault(); remove(); } }
      else if (e.key === "ArrowLeft") { e.preventDefault(); setTime((t) => clamp(t - (e.shiftKey ? 1 : 1 / project.canvas.fps), 0, total)); }
      else if (e.key === "ArrowRight") { e.preventDefault(); setTime((t) => clamp(t + (e.shiftKey ? 1 : 1 / project.canvas.fps), 0, total)); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const togglePlay = () => {
    if (total <= 0) return;
    if (!playing && time >= total - 0.05) setTime(0);
    setPlaying((p) => !p);
  };
  const onTick = useCallback((t: number) => setTime(t), []);
  const onEnd = useCallback(() => setPlaying(false), []);

  // ---- rendered preview (exact result from ffmpeg)
  const renderPreview = async () => {
    try {
      setPlaying(false);
      const j = await api.exportProject(project, { format: "mp4", quality: "low", include_audio: true, preview: true });
      setPreviewJob(j.id);
      watchJob(j, (d) => { if (d.status === "done" && d.result?.asset_id) setRendered(d.result.asset_id); setPreviewJob(null); });
    } catch (e) { toast((e as Error).message, true); }
  };
  const pj = jobs.find((j) => j.id === previewJob);

  const openProjects = async () => { try { setProjects(await api.projects()); } catch (e) { toast((e as Error).message, true); } };
  const loadProject = async (id: string) => {
    try { const p = await api.loadProject(id); first.current = true; h.reset({ ...newProject(), ...p, canvas: { ...newProject().canvas, ...p.canvas } }); remember(id); setSel(null); setTime(0); setRendered(null); setProjects(null); } catch (e) { toast((e as Error).message, true); }
  };
  const startNew = () => { first.current = true; const p = newProject(); h.reset(p); remember(p.id); setSel(null); setTime(0); setRendered(null); setProjects(null); };

  const binItems = assets.filter((a) => bin === "all" || a.kind === bin);
  const missing = project.clips.filter((c) => !asset(c.asset_id)).length + project.audio.filter((c) => !asset(c.asset_id)).length;
  const selectedTextClip = sel?.type === "clip";

  return (
    <div className="editor">
      <div className="ed-bar row gap wrap" role="toolbar" aria-label="Editor tools">
        <Button variant="ghost" small icon={I.undo} label="Undo (Ctrl+Z)" disabled={!h.canUndo} onClick={h.undo} />
        <Button variant="ghost" small icon={I.redo} label="Redo (Ctrl+Y)" disabled={!h.canRedo} onClick={h.redo} />
        <span className="vr" />
        <Button variant="ghost" small icon={I.scissors} onClick={split} label="Split at playhead (S)">Split</Button>
        <Button variant="ghost" small icon={I.dup} onClick={duplicate} disabled={!sel}>Duplicate</Button>
        <Button variant="ghost" small icon={I.trash} onClick={remove} disabled={!sel}>Delete</Button>
        <Button variant="ghost" small icon={I.text} onClick={addText}>Add text</Button>
        <span className="vr" />
        <Button variant="ghost" small icon={I.zoomOut} label="Zoom timeline out" onClick={() => setZoom((z) => clamp(z / 1.5, 8, 300))} />
        <Button variant="ghost" small icon={I.zoomIn} label="Zoom timeline in" onClick={() => setZoom((z) => clamp(z * 1.5, 8, 300))} />
        <span className="grow" />
        <span className="text-xs" aria-live="polite">{saveState === "saving" ? "Saving…" : saveState === "error" ? "Couldn’t save — check disk space" : "All changes saved"}</span>
        <Button variant="secondary" small icon={I.folder} onClick={openProjects}>Projects</Button>
        <Button variant="secondary" small icon={I.wand} onClick={renderPreview} busy={!!pj} disabled={project.clips.length === 0}>Render preview</Button>
        <Button small icon={I.download} onClick={() => setExporting(true)} disabled={project.clips.length === 0}>Export</Button>
      </div>

      {missing > 0 && <p className="banner" role="alert"><Icon d={I.alert} size={14} /> {missing} item{missing > 1 ? "s" : ""} on the timeline use files that were deleted from the Library. Remove them before exporting.</p>}

      <div className="ed-main">
        <aside className="ed-side stack gap" aria-label="Media">
          <div className="row between"><h3>Media</h3>
            <select className="select select--sm" aria-label="Filter media" value={bin} onChange={(e) => setBin(e.target.value as typeof bin)}><option value="all">All</option><option value="video">Videos</option><option value="image">Pictures</option><option value="audio">Audio</option></select>
          </div>
          {binItems.length === 0 ? <p className="text-sm">Nothing here yet. Generate a video or add files in the Library.</p> : (
            <ul className="bin">
              {binItems.map((a) => (
                <li key={a.id}>
                  <button type="button" className="bin-item" onClick={() => addAsset(a)} title={`Add “${a.name}” to the timeline`}>
                    <Thumb asset={a} />
                    <span className="stack"><span className="text-sm truncate">{a.name}</span><span className="text-xs">{a.kind}{a.duration ? ` · ${a.duration.toFixed(1)} s` : ""}</span></span>
                    <Icon d={I.plus} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </aside>

        <section className="ed-center stack gap" aria-label="Preview">
          {rendered ? (
            <div className="stage-wrap">
              <video className="player" src={mediaUrl(rendered)} controls autoPlay playsInline style={{ aspectRatio: `${project.canvas.width} / ${project.canvas.height}`, maxHeight: "100%" }} />
              <div className="row between gap"><span className="text-sm">Showing the rendered preview — exact colours, effects and transitions.</span><Button variant="secondary" small onClick={() => setRendered(null)}>Back to live preview</Button></div>
            </div>
          ) : (
            <>
              <Preview project={project} asset={asset} time={time} playing={playing} onTick={onTick} onEnd={onEnd} />
              <div className="row gap center-v">
                <Button variant="ghost" icon={I.skipBack} label="Back to start" onClick={() => { setPlaying(false); setTime(0); }} />
                <Button icon={playing ? I.pause : I.play} label={playing ? "Pause (Space)" : "Play (Space)"} onClick={togglePlay} disabled={total <= 0} />
                <span className="mono text-sm" aria-live="off">{fmtTime(time)} / {fmtTime(total)}</span>
              </div>
            </>
          )}
          {pj && <JobCard job={pj} />}
        </section>

        <aside className="ed-side ed-inspector" aria-label="Settings for the selection">
          <Inspector project={project} sel={sel} asset={asset} commit={mutate} onDelete={remove} />
          {selectedTextClip && <p className="hint">Tip: Press S to split at the playhead, drag the ends of a clip to trim, drag a clip sideways to reorder.</p>}
        </aside>
      </div>

      <Timeline project={project} asset={asset} time={time} onSeek={(t) => { setTime(t); }} sel={sel} onSelect={setSel} commit={mutate} zoom={zoom} total={total} />

      {exporting && <ExportDialog project={project} onClose={() => setExporting(false)} />}
      {projects && (
        <Dialog title="Projects" onClose={() => setProjects(null)} footer={<Button onClick={startNew} icon={I.plus}>New project</Button>}>
          {projects.length === 0 ? <p className="text-sm">No saved projects yet. Your work is saved automatically.</p> : (
            <ul className="plist">
              {projects.map((p) => (
                <li key={p.id} className="row between gap">
                  <button type="button" className="linklike" onClick={() => loadProject(p.id)}>{p.name}{p.id === project.id ? " (open)" : ""}</button>
                  <Button variant="ghost" small icon={I.trash} label={`Delete ${p.name}`} disabled={p.id === project.id} onClick={async () => { await api.deleteProject(p.id).catch((e) => toast(e.message, true)); setProjects(await api.projects()); }} />
                </li>
              ))}
            </ul>
          )}
        </Dialog>
      )}
    </div>
  );
}
