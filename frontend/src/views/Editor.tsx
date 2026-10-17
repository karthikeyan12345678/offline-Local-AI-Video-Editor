import SoundsPanel from "../editor/SoundsPanel";
import LibraryPanel, { type LibTab } from "../editor/LibraryPanel";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api, mediaUrl } from "../lib/api";
import { clamp, fmtTime, uid } from "../lib/format";
import { useApp } from "../lib/store";
import { Button, Dialog, Icon, I, Tabs } from "../ds";
import Preview from "../editor/Preview";
import Timeline, { MAX_ZOOM, MIN_ZOOM } from "../editor/Timeline";
import Inspector, { type Selection } from "../editor/Inspector";
import ExportDialog from "../editor/ExportDialog";
import FormatMenu from "../editor/FormatMenu";
import { cutPoints, itemPose, itemRest, layerDuration, layerPose, layout, newAudio, newClip, newDrawing, newLayer, newProject, newText, splitAt, upgradeProject, upsertKey, type Pose } from "../editor/model";
import { COLORS, TOOLS, type PenSettings } from "../editor/Draw";
import { useHistory } from "../editor/useHistory";
import ChatPanel from "../editor/ChatPanel";
import MediaPicker from "../editor/MediaPicker";
import { JobCard } from "./shared";
import type { Asset, Clip, Project, Shape } from "../lib/types";

const KEY = "ltxps_project";
const remembered = () => { try { return localStorage.getItem(KEY); } catch { return null; } };
const TOUR = "ltxps_tour_done";
const tourDone = () => { try { return localStorage.getItem(TOUR) === "1"; } catch { return false; } };
const remember = (id: string) => { try { localStorage.setItem(KEY, id); } catch { /* private mode */ } };

export default function Editor({ queue, onQueueDone, visible }: { queue: Asset[]; onQueueDone: () => void; visible: boolean }) {
  const { asset, assets, jobs, watchJob, toast, refreshAssets } = useApp();
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
  const dirty = useRef(false);
  const [panelOpen, setPanelOpen] = useState(() => typeof window === "undefined" || window.innerWidth >= 1200);
  const [tab, setTab] = useState<"settings" | "history">("settings");
  const [libTab, setLibTab] = useState<LibTab>("media");
  const [libOpen, setLibOpen] = useState(true);
  const [picking, setPicking] = useState<false | "timeline" | "layer">(false);
  const [showKeys, setShowKeys] = useState(false);
  const tlEl = useRef<HTMLDivElement | null>(null);
  const pendingScroll = useRef<number | null>(null);
  const behindNext = useRef(false);
  const [tourOff, setTourOff] = useState(tourDone);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(0);
  const [drawing, setDrawing] = useState(false);
  const [pen, setPen] = useState<PenSettings>({ tool: "pen", color: "#FF3B30", width: 0.8, filled: false });

  useEffect(() => { if (sel) setTab("settings"); }, [sel]);
  const { total } = layout(project, asset);
  useEffect(() => { if (!visible) setPlaying(false); }, [visible]);

  // ---- load the last project once
  useEffect(() => {
    const id = remembered();
    if (!id) { setLoaded(true); return; }
    api.loadProject(id).then((p) => h.reset(upgradeProject(p))).catch(() => {}).finally(() => setLoaded(true));
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

  const addText = (style?: { patch: Partial<import("../lib/types").TextOverlay> }) => { const t = { ...newText(clamp(time, 0, Math.max(0, total))), ...(style?.patch ?? {}) }; commit((p) => ({ ...p, texts: [...p.texts, t] })); setSel({ type: "text", id: t.id }); };

  // ---- drawing: strokes go into the selected drawing, or start a new one at the playhead
  const addShape = useCallback((shape: Shape) => {
    const cur = sel?.type === "draw" ? project.drawings.find((d) => d.id === sel.id) : undefined;
    if (cur) { commit((p) => ({ ...p, drawings: p.drawings.map((d) => (d.id === cur.id ? { ...d, shapes: [...d.shapes, shape] } : d)) })); return; }
    const d = { ...newDrawing(clamp(time, 0, Math.max(0, total)), Math.min(4, Math.max(1.5, total - time || 3))), shapes: [shape] };
    commit((p) => ({ ...p, drawings: [...p.drawings, d] }));
    setSel({ type: "draw", id: d.id });
  }, [sel, project.drawings, commit, time, total]);

  // ---- actions on the selection
  const remove = useCallback(() => {
    if (!sel) return;
    commit((p) => ({ ...p, clips: sel.type === "clip" ? p.clips.filter((c) => c.id !== sel.id) : p.clips, texts: sel.type === "text" ? p.texts.filter((c) => c.id !== sel.id) : p.texts, audio: sel.type === "audio" ? p.audio.filter((c) => c.id !== sel.id) : p.audio, drawings: sel.type === "draw" ? p.drawings.filter((c) => c.id !== sel.id) : p.drawings, images: sel.type === "image" ? p.images.filter((c) => c.id !== sel.id) : p.images, layers: sel.type === "layer" ? p.layers.filter((c) => c.id !== sel.id) : p.layers }));
    setSel(null);
  }, [sel, commit]);
  const duplicate = () => {
    if (!sel) return;
    commit((p) => {
      if (sel.type === "clip") { const i = p.clips.findIndex((c) => c.id === sel.id); if (i < 0) return p; const copy = { ...p.clips[i], id: Math.random().toString(36).slice(2, 10) }; const clips = [...p.clips]; clips.splice(i + 1, 0, copy); return { ...p, clips }; }
      if (sel.type === "text") { const t = p.texts.find((x) => x.id === sel.id); return t ? { ...p, texts: [...p.texts, { ...t, id: Math.random().toString(36).slice(2, 10), start: t.start + t.duration }] } : p; }
      if (sel.type === "layer") { const d = p.layers.find((x) => x.id === sel.id); return d ? { ...p, layers: [...p.layers, { ...d, id: Math.random().toString(36).slice(2, 10), start: d.start + 0.5, track: Math.min(8, d.track + 1) }] } : p; }
      if (sel.type === "image") { const d = p.images.find((x) => x.id === sel.id); return d ? { ...p, images: [...p.images, { ...d, id: Math.random().toString(36).slice(2, 10), start: d.start + d.duration }] } : p; }
      if (sel.type === "draw") { const d = p.drawings.find((x) => x.id === sel.id); return d ? { ...p, drawings: [...p.drawings, { ...d, id: Math.random().toString(36).slice(2, 10), start: d.start + d.duration }] } : p; }
      const a = p.audio.find((x) => x.id === sel.id);
      return a ? { ...p, audio: [...p.audio, { ...a, id: Math.random().toString(36).slice(2, 10), start: a.start + 1 }] } : p;
    });
  };
  const split = useCallback(() => {
    const next = splitAt(project, time, asset);
    if (!next) { toast("Move the playhead inside a clip (not at its very edge) to split it.", true); return; }
    commit(next);
  }, [project, time, asset, commit, toast]);

  // ---- layers: a second video or picture that plays at the same time
  const addLayer = useCallback((a: Asset) => {
    if (a.kind === "audio") { addAsset(a); return; }
    const start = clamp(time, 0, Math.max(0, total));
    const dur = a.kind === "image" ? 4 : Math.max(0.5, a.duration || 4);
    const busy = (tr: number) => project.layers.some((l) => !l.behind && l.track === tr && l.start < start + dur && start < l.start + layerDuration(l, asset(l.asset_id)));
    let track = 1;
    while (track < 8 && busy(track)) track += 1;
    const back = behindNext.current;
    behindNext.current = false;
    const layer = back
      ? newLayer(a, 0, { track: 1 + project.layers.filter((l) => l.behind).length, behind: true, x: 0.5, y: 0.5, size: 1 })
      : newLayer(a, start, { track, x: 0.76, y: 0.72, size: 0.38 });
    commit((p) => ({ ...p, layers: [...p.layers, layer] }));
    setSel({ type: "layer", id: layer.id });
  }, [commit, time, total, asset, addAsset, project.layers]);

  const itemOf = (s: Selection) => (!s ? null : s.type === "layer" ? project.layers.find((x) => x.id === s.id) : s.type === "text" ? project.texts.find((x) => x.id === s.id) : s.type === "image" ? project.images.find((x) => x.id === s.id) : null) ?? null;
  const poseNow = (s: Selection): Pose | null => {
    const it = itemOf(s);
    if (!it || !s) return null;
    return s.type === "layer" ? layerPose(it as typeof project.layers[number], time) : { ...itemRest(it as typeof project.texts[number]), x: itemPose(it as typeof project.texts[number], time).x, y: itemPose(it as typeof project.texts[number], time).y };
  };
  /** Remember how the selected layer, text or picture looks right now, as a keyframe at the playhead. */
  const addKeyframe = useCallback(() => {
    const it = itemOf(sel);
    if (!it || !sel || !("start" in it)) { toast("Click a layer, text or picture on the timeline first, then add a keyframe.", true); return; }
    const len = sel.type === "layer" ? layerDuration(it as typeof project.layers[number], asset((it as typeof project.layers[number]).asset_id)) : (it as typeof project.texts[number]).duration;
    const rel = time - it.start;
    if (rel < -0.001 || rel > len + 0.001) { toast("Move the playhead inside this item to add a keyframe.", true); return; }
    const pose = poseNow(sel)!;
    const key = sel.type === "layer" ? "layers" : sel.type === "text" ? "texts" : "images";
    commit((p) => ({ ...p, [key]: (p[key] as { id: string; keys: import("../lib/types").Key[] }[]).map((x) => (x.id === sel.id ? { ...x, keys: upsertKey(x.keys, clamp(rel, 0, len), pose) } : x)) }) as Project);
  }, [sel, time, project, asset, commit, toast]); // eslint-disable-line react-hooks/exhaustive-deps

  /** Drag in the preview. Items with keyframes get a keyframe at the playhead; others simply move. */
  const setPose = useCallback((kind: "layer" | "text" | "image", id: string, patch: Partial<Pose>) => {
    commit((p) => {
      if (kind === "layer") {
        return { ...p, layers: p.layers.map((l) => {
          if (l.id !== id) return l;
          if (l.keys.length === 0) return { ...l, ...patch };
          const len = layerDuration(l, asset(l.asset_id));
          return { ...l, keys: upsertKey(l.keys, clamp(time - l.start, 0, len), { ...layerPose(l, time), ...patch }) };
        }) };
      }
      const key = kind === "text" ? "texts" : "images";
      const list = p[key] as (typeof p.texts[number] | typeof p.images[number])[];
      return { ...p, [key]: list.map((it) => {
        if (it.id !== id) return it;
        const move = { x: patch.x ?? it.x, y: patch.y ?? it.y };
        if (it.keys.length === 0) return { ...it, ...move, ...(kind === "image" && patch.size ? { size: patch.size } : {}) };
        const cur = itemPose(it, time);
        return { ...it, keys: upsertKey(it.keys, clamp(time - it.start, 0, it.duration), { ...itemRest(it), x: patch.x ?? cur.x, y: patch.y ?? cur.y }) };
      }) } as Project;
    }, `${id}:pose`);
  }, [commit, time, asset]);

  // ---- moving around: frames, cuts, zoom
  const stepFrame = useCallback((n: number) => { setPlaying(false); setTime((t) => clamp(Math.round((t + n / project.canvas.fps) * project.canvas.fps) / project.canvas.fps, 0, total)); }, [project.canvas.fps, total]);
  const jumpCut = useCallback((dir: 1 | -1) => {
    setPlaying(false);
    const pts = cutPoints(project, asset).filter((v) => v <= total + 1e-6);
    setTime((t) => (dir > 0 ? pts.find((v) => v > t + 0.01) ?? total : [...pts].reverse().find((v) => v < t - 0.01) ?? 0));
  }, [project, asset, total]);
  const zoomTo = useCallback((z: number) => {
    const el = tlEl.current;
    if (el) pendingScroll.current = 96 + time * zoom - el.scrollLeft; // keep the playhead where it is on screen
    setZoom(clamp(z, MIN_ZOOM, MAX_ZOOM));
  }, [time, zoom]);
  useLayoutEffect(() => {
    const el = tlEl.current;
    if (el && pendingScroll.current !== null) { el.scrollLeft = Math.max(0, 96 + time * zoom - pendingScroll.current); pendingScroll.current = null; }
  }, [zoom]); // eslint-disable-line react-hooks/exhaustive-deps
  const fit = () => { const el = tlEl.current; if (!el) return; setZoom(clamp((el.clientWidth - 96 - 48) / Math.max(total, 2), MIN_ZOOM, MAX_ZOOM)); el.scrollLeft = 0; };

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
      else if (e.key === "ArrowLeft") { e.preventDefault(); if (e.shiftKey) setTime((t) => clamp(t - 1, 0, total)); else stepFrame(-1); }
      else if (e.key === "ArrowRight") { e.preventDefault(); if (e.shiftKey) setTime((t) => clamp(t + 1, 0, total)); else stepFrame(1); }
      else if (e.key === "Home") { e.preventDefault(); setPlaying(false); setTime(0); }
      else if (e.key === "End") { e.preventDefault(); setPlaying(false); setTime(total); }
      else if (e.key === "[" || e.key === "PageUp") { e.preventDefault(); jumpCut(-1); }
      else if (e.key === "]" || e.key === "PageDown") { e.preventDefault(); jumpCut(1); }
      else if (e.key.toLowerCase() === "k" && !mod) { e.preventDefault(); addKeyframe(); }
      else if (e.key.toLowerCase() === "l" && !mod) { e.preventDefault(); setPicking("layer"); }
      else if ((e.key === "=" || e.key === "+") && !mod) { e.preventDefault(); zoomTo(zoom * 1.4); }
      else if (e.key === "-" && !mod) { e.preventDefault(); zoomTo(zoom / 1.4); }
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
    try { const p = await api.loadProject(id); first.current = true; h.reset(upgradeProject(p)); remember(id); setSel(null); setTime(0); setRendered(null); setProjects(null); } catch (e) { toast((e as Error).message, true); }
  };
  const startNew = () => { first.current = true; const p = newProject(); h.reset(p); remember(p.id); setSel(null); setTime(0); setRendered(null); setProjects(null); };

  const dropFiles = async (files: FileList | File[]) => {
    const list = Array.from(files);
    if (!list.length) return;
    setUploading(list.length);
    const added: Asset[] = [];
    for (const f of list) {
      try { added.push(await api.upload(f)); } catch (e) { toast(`${f.name}: ${(e as Error).message}`, true); }
      setUploading((n) => Math.max(0, n - 1));
    }
    await refreshAssets();
    added.forEach((a) => addAsset(a));
    if (added.length) toast(`Added ${added.length} file${added.length > 1 ? "s" : ""} to the timeline.`);
  };

  // The website's Home page asks the editor to open an old project or start a new one.
  useEffect(() => {
    const open = (e: Event) => { void loadProject(String((e as CustomEvent<string>).detail)); };
    const fresh = () => startNew();
    window.addEventListener("vk-open-project", open); window.addEventListener("vk-new-project", fresh);
    return () => { window.removeEventListener("vk-open-project", open); window.removeEventListener("vk-new-project", fresh); };
  }); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const on = (e: Event) => { if (visible) void dropFiles((e as CustomEvent<File[]>).detail); };
    window.addEventListener("vk-drop-files", on);
    return () => window.removeEventListener("vk-drop-files", on);
  }); // eslint-disable-line react-hooks/exhaustive-deps


  // ---- one-click looks, effects and transitions from the left library
  const targetClip = (): Clip | null => {
    if (sel?.type === "clip") return project.clips.find((c) => c.id === sel.id) ?? null;
    const at = layout(project, asset).items.find((it) => time >= it.start && time < it.start + it.dur);
    return at?.clip ?? project.clips[0] ?? null;
  };
  const targetLayer = () => (sel?.type === "layer" ? project.layers.find((l) => l.id === sel.id) ?? null : null);
  const tClip = targetClip(), tLayer = targetLayer();
  const targetName = tLayer ? "the selected layer" : tClip ? `clip ${project.clips.indexOf(tClip) + 1}` : null;
  const patchTarget = (fn: (c: { preset: string; effects: { type: string; amount: number }[]; transition?: { type: string; duration: number } }) => Record<string, unknown>) => {
    if (tLayer) { commit((p) => ({ ...p, layers: p.layers.map((l) => (l.id === tLayer.id ? { ...l, ...fn(l as never) } : l)) })); return; }
    if (!tClip) { toast("Add a video to the timeline first."); return; }
    commit((p) => ({ ...p, clips: p.clips.map((c) => (c.id === tClip.id ? { ...c, ...fn(c as never) } : c)) }));
  };
  const applyLook = (id: string) => patchTarget(() => ({ preset: id }));
  const applyEffect = (id: string) => patchTarget((c) => {
    const has = c.effects.some((e) => e.type === id);
    if (has) return { effects: c.effects.filter((e) => e.type !== id) };
    if (c.effects.length >= 6) { toast("Up to 6 effects per clip. Remove one first.", true); return {}; }
    return { effects: [...c.effects, { type: id, amount: 0.5 }] };
  });
  const applyTransition = (id: string) => {
    if (!tClip) { toast("Add a video to the timeline first."); return; }
    commit((p) => ({ ...p, clips: p.clips.map((c) => (c.id === tClip.id ? { ...c, transition: { type: id, duration: c.transition.duration || 0.6 } } : c)) }));
    if (project.clips.indexOf(tClip) === project.clips.length - 1 && id !== "none") toast("Transitions play between two clips. This is the last clip, so add another after it.");
  };

  const missing = project.clips.filter((c) => !asset(c.asset_id)).length + project.audio.filter((c) => !asset(c.asset_id)).length;
  const selectedTextClip = sel?.type === "clip";

  return (
    <div className="editor fx"
      onDragOver={(e) => { if (e.dataTransfer.types.includes("Files")) { e.preventDefault(); setDragging(true); } }}
      onDragLeave={(e) => { if (e.currentTarget === e.target) setDragging(false); }}
      onDrop={(e) => { if (e.dataTransfer.files.length) { e.preventDefault(); setDragging(false); void dropFiles(e.dataTransfer.files); } }}>
      {(dragging || uploading > 0) && <div className="drop-veil" role="status">{uploading > 0 ? `Adding your files… ${uploading} left` : "Drop videos, pictures or music here"}</div>}
      <header className="fx-top" role="toolbar" aria-label="Project">
        <input className="fx-title" aria-label="Project name" value={project.name} placeholder="Untitled project" maxLength={80} onChange={(e) => commit((p) => ({ ...p, name: e.target.value }), "name")} />
        <FormatMenu project={project} commit={h.commit} />
        <span className="text-xs fx-save" aria-live="polite">{saveState === "saving" ? "Saving…" : saveState === "error" ? "Couldn’t save — check disk space" : "All changes saved"}</span>
        <span className="grow" />
        <Button variant="ghost" small icon={I.undo} label="Undo (Ctrl+Z)" disabled={!h.canUndo} onClick={h.undo} />
        <Button variant="ghost" small icon={I.redo} label="Redo (Ctrl+Y)" disabled={!h.canRedo} onClick={h.redo} />
        <Button variant="ghost" small icon={I.folder} onClick={openProjects}>Projects</Button>
        <Button variant="ghost" small active={libOpen} aria-pressed={libOpen} onClick={() => setLibOpen((v) => !v)}>Library</Button>
        <Button variant="ghost" small active={panelOpen} aria-pressed={panelOpen} onClick={() => setPanelOpen((v) => !v)}>Details</Button>
        <Button variant="secondary" small icon={I.wand} onClick={renderPreview} busy={!!pj} disabled={project.clips.length === 0}>Render preview</Button>
        <Button className="fx-done" small icon={I.download} onClick={() => setExporting(true)} disabled={project.clips.length === 0}>Export</Button>
      </header>

      {missing > 0 && <p className="banner" role="alert"><Icon d={I.alert} size={14} /> {missing} item{missing > 1 ? "s" : ""} on the timeline use files that were deleted from the Library. Remove them before exporting.</p>}

      <div className={`fx-main${panelOpen ? "" : " fx-main--noright"}${libOpen ? "" : " fx-main--noleft"}`}>
        {libOpen && (
          <LibraryPanel tab={libTab} onTab={setLibTab} assets={assets} onAdd={addAsset} onLayer={addLayer} onUpload={(f) => void dropFiles(f)}
            audioPanel={
              <SoundsPanel onAdd={async (a, s) => {
                await refreshAssets();
                const ambient = s.group === "Ambience" || s.group === "Music and loops";
                const at = clamp(time, 0, Math.max(0, total));
                commit((p) => ({ ...p, audio: [...p.audio, newAudio(a, at, { volume: ambient ? 0.5 : 1, loop: ambient, is_music: ambient, fade_in: ambient ? 0.5 : 0, fade_out: ambient ? 1 : 0 })] }));
                toast(`Added “${s.label}” at ${at.toFixed(1)} s.`);
              }} />}
            onText={addText} target={targetName}
            currentLook={tLayer?.preset ?? tClip?.preset ?? "none"} currentEffects={(tLayer?.effects ?? tClip?.effects ?? []).map((e) => e.type)} currentTransition={tClip?.transition.type ?? "none"}
            onLook={applyLook} onEffect={applyEffect} onTransition={applyTransition} />
        )}
        <section className="fx-center" aria-label="Preview">
          {project.clips.length === 0 && !tourOff && (
            <div className="card editor-hint stack gap" role="note">
              <b>New here? Four easy steps</b>
              <ol className="text-sm">
                <li><b>Add</b> a video, picture or song: press <b>Import</b> in the left panel, or drag it into this window.</li>
                <li><b>Change</b> it: pick a <b>Filter</b>, <b>Effect</b>, <b>Text</b> or <b>Sound</b> from the left tabs, or click a block on the timeline and use the Details panel on the right.</li>
                <li><b>Ask the AI</b>: type in the box at the bottom and say what you want, like “make it vertical” or “add the title Hello”.</li>
                <li><b>Save it</b>: press <b>Export</b>. Your work is saved automatically all the time.</li>
              </ol>
              <div className="row"><Button small variant="secondary" onClick={() => { setTourOff(true); try { localStorage.setItem(TOUR, "1"); } catch { /* ignore */ } }}>Got it, hide this</Button></div>
            </div>
          )}
          {rendered ? (
            <div className="stage-wrap">
              <video className="player" src={mediaUrl(rendered)} controls autoPlay playsInline style={{ aspectRatio: `${project.canvas.width} / ${project.canvas.height}`, maxHeight: "100%" }} />
              <div className="row between gap"><span className="text-sm">Showing the rendered preview — exact colours, effects and transitions.</span><Button variant="secondary" small onClick={() => setRendered(null)}>Back to live preview</Button></div>
            </div>
          ) : (
            <>
              {drawing && (
                <div className="drawbar" role="toolbar" aria-label="Drawing tools">
                  {TOOLS.map((t) => <Button key={t.id} variant="secondary" small active={pen.tool === t.id} onClick={() => setPen({ ...pen, tool: t.id })}>{t.label}</Button>)}
                  <span className="vr" />
                  {COLORS.map((c) => <button key={c} type="button" className="swatch" style={{ background: c }} aria-label={`Colour ${c}`} aria-pressed={pen.color === c} onClick={() => setPen({ ...pen, color: c })} />)}
                  <input type="color" aria-label="Custom colour" value={pen.color} onChange={(e) => setPen({ ...pen, color: e.target.value.toUpperCase() })} />
                  <label className="text-xs row gap center-v">Thickness<input type="range" min={0.2} max={4} step={0.1} value={pen.width} onChange={(e) => setPen({ ...pen, width: Number(e.target.value) })} /></label>
                  {(pen.tool === "rect" || pen.tool === "ellipse") && <label className="check"><input type="checkbox" checked={pen.filled} onChange={(e) => setPen({ ...pen, filled: e.target.checked })} />Fill</label>}
                  <Button small variant="ghost" onClick={() => setDrawing(false)}>Done</Button>
                </div>
              )}
              <Preview project={project} asset={asset} time={time} playing={playing} onTick={onTick} onEnd={onEnd} pen={drawing ? pen : null} editingId={drawing && sel?.type === "draw" ? sel.id : null} onShape={addShape} sel={sel} onSelect={setSel} onPose={setPose} />
            </>
          )}
          {pj && <JobCard job={pj} />}
          <div className="fx-transport" role="group" aria-label="Playback">
            <span className="mono text-sm" aria-live="off">{fmtTime(time)}</span>
            <Button variant="ghost" icon={I.skipBack} label="Back to the start (Home)" onClick={() => { setPlaying(false); setTime(0); }} />
            <Button variant="ghost" small label="Previous cut or keyframe ([)" onClick={() => jumpCut(-1)}>⏪</Button>
            <Button variant="ghost" small label="Back one frame (←)" onClick={() => stepFrame(-1)}>◀|</Button>
            <button type="button" className="fx-play" aria-label={playing ? "Pause (Space)" : "Play (Space)"} disabled={total <= 0} onClick={togglePlay}><Icon d={playing ? I.pause : I.play} size={22} /></button>
            <Button variant="ghost" small label="Forward one frame (→)" onClick={() => stepFrame(1)}>|▶</Button>
            <Button variant="ghost" small label="Next cut or keyframe (])" onClick={() => jumpCut(1)}>⏩</Button>
            <Button variant="ghost" small label="Jump to the end (End)" onClick={() => { setPlaying(false); setTime(total); }}>⏭</Button>
            <span className="mono text-sm" aria-live="off">{fmtTime(total)}</span>
          </div>
          <div className="fx-tools" role="toolbar" aria-label="Editor tools">
            <Button variant="ghost" small icon={I.scissors} onClick={split} label="Split at playhead (S)">Split</Button>
            <Button variant="ghost" small icon={I.dup} onClick={duplicate} disabled={!sel} label="Make a copy of the selected block">Copy</Button>
            <Button variant="ghost" small icon={I.trash} onClick={remove} disabled={!sel}>Delete</Button>
            <span className="vr" />
            <Button variant="ghost" small icon={I.text} onClick={() => addText()} label="Add a title or caption at the playhead">Text</Button>
            <Button variant="ghost" small icon={I.wand} active={drawing} onClick={() => { setDrawing((d) => !d); setPlaying(false); }}>Draw</Button>
            <Button variant="ghost" small icon={I.plus} onClick={() => setPicking("timeline")} label="Add a video, picture or song to the main video">Media</Button>
            <Button variant="ghost" small icon={I.film} label="Add a second video or picture that plays at the same time (L)" onClick={() => setPicking("layer")}>Layer</Button>
            <Button variant="ghost" small label="Remember where the selected layer, text or picture is right now (K)" disabled={!sel || !["layer", "text", "image"].includes(sel.type)} onClick={addKeyframe}>◆ Key</Button>
            <span className="vr" />
            <Button variant="ghost" small icon={I.zoomOut} label="Zoom timeline out (-)" onClick={() => zoomTo(zoom / 1.4)} />
            <Button variant="ghost" small icon={I.zoomIn} label="Zoom timeline in (+). You can also scroll the mouse wheel over the timeline." onClick={() => zoomTo(zoom * 1.4)} />
            <Button variant="ghost" small label="Fit the whole video in the window" onClick={fit}>Fit</Button>
            <Button variant="ghost" small label="Keyboard shortcuts" onClick={() => setShowKeys(true)}>⌨</Button>
          </div>
        </section>

        {panelOpen && (
          <aside className="fx-panel" aria-label="Side panel">
            <Tabs label="Panel" value={tab} onChange={setTab} options={[{ id: "settings", label: "Details" }, { id: "history", label: "History" }]} />
            {tab === "settings" && (
              <div className="ed-inspector stack gap">
                <Inspector project={project} sel={sel} asset={asset} commit={mutate} onDelete={remove} time={time} onSeek={(t) => { setPlaying(false); setTime(clamp(t, 0, total)); }} onAddBackground={() => { behindNext.current = true; setPicking("layer"); }} />
                {selectedTextClip && <p className="hint">Tip: Press S to split at the playhead, drag the ends of a clip to trim, drag a clip sideways to reorder.</p>}
              </div>
            )}
            {tab === "history" && (
              <div className="stack gap">
                <h3>Edit history</h3>
                <p className="text-sm">Every change you make is a step. Click one to go back to it, or forward again.</p>
                <ol className="hist" reversed>
                  {[...h.steps].map((st, i) => ({ st, i })).reverse().map(({ st, i }) => (
                    <li key={i}><button type="button" className={`hist-item${i === h.at ? " on" : ""}`} aria-current={i === h.at ? "step" : undefined} onClick={() => h.jump(i)}>
                      <b>{i === 0 ? "Start" : `Step ${i}`}</b><span className="text-xs">{st.clips.length} clip{st.clips.length === 1 ? "" : "s"} · {st.texts.length} text · {st.audio.length} sound · {st.canvas.width}×{st.canvas.height}</span></button></li>
                  ))}
                </ol>
                <Button variant="secondary" small icon={I.folder} onClick={openProjects}>Saved drafts…</Button>
              </div>
            )}
          </aside>
        )}
      </div>

      <Timeline project={project} asset={asset} time={time} onSeek={(t) => { setTime(t); }} sel={sel} onSelect={setSel} commit={mutate} zoom={zoom} total={total} onAdd={() => setPicking("timeline")} onAddLayer={() => setPicking("layer")} onZoom={setZoom} viewportRef={(el) => { tlEl.current = el; }} />

      <ChatPanel project={project} commit={mutate} asset={asset} onOpenAsset={addAsset} onUndo={h.undo} onSeek={(t) => setTime(t)} />
      {picking && <MediaPicker assets={assets} mode={picking === "layer" ? "layer" : "timeline"} projectName={project.name} onClose={() => { behindNext.current = false; setPicking(false); }} onUpload={(f) => void dropFiles(f)} onPick={(a) => { if (picking === "layer") { addLayer(a); toast(`Added “${a.name}” as a layer. Drag it in the preview to place it.`); } else { addAsset(a); toast(`Added “${a.name}” to the timeline.`); } }} />}
      {showKeys && (
        <Dialog title="Keyboard shortcuts" onClose={() => setShowKeys(false)}>
          <ul className="keys-list text-sm">
            {[["Space", "Play or pause"], ["← / →", "One frame back / forward"], ["Shift + ← / →", "One second back / forward"], ["[  /  ]", "Previous / next cut or keyframe"], ["Home / End", "Start / end of the video"], ["S", "Split the clip at the playhead"], ["K", "Add a keyframe to the selected layer, text or picture"], ["L", "Add a layer (second video or picture)"], ["+  /  −", "Zoom the timeline"], ["Mouse wheel on the timeline", "Zoom in and out (Shift + wheel scrolls sideways)"], ["Delete", "Remove the selected block"], ["Ctrl + Z / Ctrl + Y", "Undo / redo"]].map(([k, d]) => <li key={k}><kbd>{k}</kbd><span>{d}</span></li>)}
          </ul>
        </Dialog>
      )}

      {exporting && <ExportDialog seconds={total} project={project} onClose={() => setExporting(false)} />}
      {projects && (
        <Dialog title="Projects and drafts" onClose={() => setProjects(null)} footer={<Button onClick={startNew} icon={I.plus}>New project</Button>}>
          <p className="text-sm">Every project is saved by itself as a draft. Open one to carry on, or make a copy before you try something risky.</p>
          {projects.length === 0 ? <p className="text-sm">No saved projects yet.</p> : (
            <ul className="plist">
              {projects.map((p) => (
                <li key={p.id} className="row between gap wrap">
                  <button type="button" className="linklike" onClick={() => loadProject(p.id)}>{p.name || "Untitled"}{p.id === project.id ? " (open now)" : ""}</button>
                  <span className="row gap">
                    <Button variant="ghost" small onClick={async () => { const n = prompt("New name", p.name); if (!n?.trim()) return; try { const d = await api.loadProject(p.id); await api.saveProject(p.id, { ...d, name: n.trim() }); if (p.id === project.id) commit((x) => ({ ...x, name: n.trim() })); setProjects(await api.projects()); } catch (e) { toast((e as Error).message, true); } }}>Rename</Button>
                    <Button variant="ghost" small onClick={async () => { try { const d = await api.loadProject(p.id); const id = uid() + uid(); await api.saveProject(id, { ...d, id, name: `${p.name || "Untitled"} (copy)` }); setProjects(await api.projects()); toast("Copy saved."); } catch (e) { toast((e as Error).message, true); } }}>Make a copy</Button>
                    <Button variant="ghost" small icon={I.trash} label={`Delete ${p.name}`} disabled={p.id === project.id} onClick={async () => { if (!confirm(`Delete “${p.name || "Untitled"}” for good?`)) return; await api.deleteProject(p.id).catch((e) => toast(e.message, true)); setProjects(await api.projects()); }}>Delete</Button>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Dialog>
      )}
    </div>
  );
}
