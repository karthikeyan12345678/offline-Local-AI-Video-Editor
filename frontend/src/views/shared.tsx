import { api, mediaUrl } from "../lib/api";
import { fmtDuration } from "../lib/format";
import { useApp } from "../lib/store";
import { Button, Icon, Progress, I } from "../ds";
import type { Asset, Job } from "../lib/types";

export function Thumb({ asset, className = "" }: { asset: Asset; className?: string }) {
  const icon = asset.kind === "audio" ? I.music : asset.kind === "image" ? I.image : I.film;
  return asset.thumb ? <img className={`thumb ${className}`} src={mediaUrl(asset.id, "thumb")} alt="" loading="lazy" draggable={false} /> : <div className={`thumb thumb--empty ${className}`}><Icon d={icon} size={24} /></div>;
}

export function JobCard({ job }: { job: Job }) {
  const { toast } = useApp();
  const active = job.status === "queued" || job.status === "running";
  return (
    <div className="card stack gap" role="status" aria-live="polite">
      <div className="row between gap">
        <span className="w-medium truncate">{job.title}</span>
        {active ? <Button variant="secondary" small onClick={() => api.cancelJob(job.id).catch((e) => toast(e.message, true))}>Cancel</Button> : <span className="badge">{job.status === "done" ? "Done" : job.status === "cancelled" ? "Cancelled" : "Failed"}</span>}
      </div>
      {active && (
        <>
          <Progress value={job.progress} indeterminate={job.status === "queued" || job.progress === 0} />
          <div className="row between text-xs"><span>{job.status === "queued" ? "Waiting for the previous job…" : job.phase || "Working…"}</span><span className="mono">{Math.round(job.progress * 100)}%{job.eta != null ? ` · about ${fmtDuration(job.eta)} left` : ""}</span></div>
        </>
      )}
      {job.status === "error" && <p className="error-text" role="alert"><Icon d={I.alert} size={14} />{job.error}</p>}
    </div>
  );
}

export function AssetPicker({ kind, value, onChange, label }: { kind: "image" | "video"; value: string | null; onChange: (id: string) => void; label: string }) {
  const { assets } = useApp();
  const items = assets.filter((a) => a.kind === kind);
  if (!items.length) return <div className="empty"><Icon d={kind === "image" ? I.image : I.film} size={24} /><p className="text-sm">No {kind}s in your library yet. Add one in the Library tab{kind === "video" ? " or generate one first" : ""}.</p></div>;
  return (
    <div className="picker" role="radiogroup" aria-label={label}>
      {items.map((a) => (
        <button key={a.id} type="button" role="radio" aria-checked={value === a.id} className={`pick${value === a.id ? " pick--on" : ""}`} onClick={() => onChange(a.id)} title={a.name}>
          <Thumb asset={a} />
          <span className="text-xs truncate">{a.name}</span>
        </button>
      ))}
    </div>
  );
}
