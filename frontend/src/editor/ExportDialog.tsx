import { useEffect, useRef, useState } from "react";
import { api, mediaUrl } from "../lib/api";
import { useApp } from "../lib/store";
import { Button, Dialog, Field } from "../ds";
import { JobCard } from "../views/shared";
import type { ExportOptions, Project } from "../lib/types";
import { presetFor } from "./model";
import { saveAs } from "../lib/save";

export default function ExportDialog({ project, seconds = 0, onClose }: { project: Project; seconds?: number; onClose: () => void }) {
  const { jobs, watchJob, toast } = useApp();
  const [opts, setOpts] = useState<ExportOptions>({ format: "mp4", quality: "medium", include_audio: true, preview: false, fps: project.canvas.fps, width: project.canvas.width, height: project.canvas.height });
  const [jobId, setJobId] = useState<string | null>(null);
  const [outId, setOutId] = useState<string | null>(null);
  const asked = useRef<string | null>(null);
  const fileName = `${(project.name || "video").replace(/[\\/:*?"<>|]+/g, " ").trim() || "video"}.${opts.format === "gif" ? "gif" : opts.format === "webm" ? "webm" : "mp4"}`;
  // In the desktop app the Save As window opens as soon as the export is ready, so the person always chooses the place.
  useEffect(() => { if (outId && asked.current !== outId && /Electron\//.test(navigator.userAgent)) { asked.current = outId; void saveAs(mediaUrl(outId, "download"), fileName); } }, [outId, fileName]);
  const [busy, setBusy] = useState(false);
  const job = jobs.find((j) => j.id === jobId);
  const active = !!job && (job.status === "queued" || job.status === "running");
  const scale = opts.width && project.canvas.width ? opts.width / project.canvas.width : 1;

  const start = async () => {
    setBusy(true); setOutId(null);
    try {
      const j = await api.exportProject(project, { ...opts, height: Math.round(project.canvas.height * scale / 2) * 2, width: Math.round(project.canvas.width * scale / 2) * 2 });
      setJobId(j.id);
      watchJob(j, (d) => { if (d.status === "done" && d.result?.asset_id) setOutId(d.result.asset_id); });
    } catch (e) { toast((e as Error).message, true); } finally { setBusy(false); }
  };

  const plat = presetFor(project.canvas.width, project.canvas.height);
  const tooLong = plat?.maxSeconds && seconds > plat.maxSeconds ? `${plat.label} allows about ${plat.maxSeconds} seconds; this video is ${Math.round(seconds)} s.` : "";

  return (
    <Dialog title="Export video" onClose={onClose} footer={<><Button variant="ghost" onClick={onClose}>{outId ? "Close" : "Cancel"}</Button>{!outId && <Button icon="M12 4v12M7 11l5 5 5-5M5 20h14" busy={busy} disabled={active || project.clips.length === 0} onClick={start}>Export</Button>}</>}>
      {plat && <p className="text-sm export-for">Exporting for <b>{plat.label}</b> ({project.canvas.width}×{project.canvas.height}). Change it from the Format menu in the editor.</p>}
      {tooLong && <p className="text-sm warn" role="alert">{tooLong}</p>}
      <Field label="Format" htmlFor="fmt">
        <select id="fmt" className="select" value={opts.format} onChange={(e) => setOpts({ ...opts, format: e.target.value as ExportOptions["format"] })}>
          <option value="mp4">MP4 — plays everywhere</option><option value="webm">WebM — for websites</option><option value="gif">GIF — animated picture, no sound</option>
        </select>
      </Field>
      <div className="grid-2">
        <Field label="Size" htmlFor="sz">
          <select id="sz" className="select" value={opts.width} onChange={(e) => setOpts({ ...opts, width: Number(e.target.value) })}>
            {[1, 0.75, 0.5, 0.25].map((f) => { const w = Math.round(project.canvas.width * f / 2) * 2; const h = Math.round(project.canvas.height * f / 2) * 2; return <option key={f} value={w}>{w}×{h}{f === 1 ? " (project size)" : ""}</option>; })}
          </select>
        </Field>
        <Field label="Quality" htmlFor="q">
          <select id="q" className="select" value={opts.quality} onChange={(e) => setOpts({ ...opts, quality: e.target.value as ExportOptions["quality"] })} disabled={opts.format === "gif"}>
            <option value="low">Small file</option><option value="medium">Balanced</option><option value="high">Best quality</option>
          </select>
        </Field>
      </div>
      <Field label="Frames per second" htmlFor="efps"><select id="efps" className="select" value={opts.fps} onChange={(e) => setOpts({ ...opts, fps: Number(e.target.value) })}>{[12, 24, 25, 30, 48, 60].map((f) => <option key={f} value={f}>{f}</option>)}</select></Field>
      <label className="check"><input type="checkbox" checked={opts.include_audio && opts.format !== "gif"} disabled={opts.format === "gif"} onChange={(e) => setOpts({ ...opts, include_audio: e.target.checked })} />Include sound</label>
      {job && <JobCard job={job} />}
      {outId && (
        <div className="stack gap">
          <video className="player" src={mediaUrl(outId)} controls playsInline />
          <div className="row gap"><Button onClick={() => void saveAs(mediaUrl(outId, "download"), fileName)}>Save to my computer…</Button><span className="text-sm">Also in your Library.</span></div>
        </div>
      )}
      {(job?.result?.warnings as string[] | undefined)?.map((w) => <p key={w} className="text-sm">Note: {w}</p>)}
    </Dialog>
  );
}
