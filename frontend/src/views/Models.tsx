import { useState } from "react";
import { api } from "../lib/api";
import { fmtBytes, isDownloading } from "../lib/format";

export function fmtEta(sec: number): string {
  if (!isFinite(sec) || sec <= 0) return "";
  if (sec < 45) return "less than a minute left";
  const m = Math.round(sec / 60);
  if (m < 60) return `about ${m} min left`;
  return `about ${Math.floor(m / 60)} h ${m % 60} min left`;
}
import { useApp } from "../lib/store";
import { Button, Progress, I } from "../ds";
import type { ModelRow } from "../lib/types";

export function ModelCard({ m }: { m: ModelRow }) {
  const { refreshModels, toast, system } = useApp();
  const [size, setSize] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const d = m.download;
  const running = isDownloading(d.status);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try { await fn(); await refreshModels(); } catch (e) { toast((e as Error).message, true); } finally { setBusy(false); }
  };
  const probe = () => act(async () => setSize((await api.probe(m.id)).bytes));
  const free = system?.disk_free_gb ?? 0;
  const tooBig = size !== null && size / 1024 ** 3 > free;

  return (
    <div className="card stack gap">
      <div className="row between gap">
        <div className="stack">
          <h3>{m.label}</h3>
          <p className="text-sm">{m.note}</p>
        </div>
        {m.installed ? <span className="badge badge--accent"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3"><path d={I.check} /></svg>Installed · {fmtBytes(m.installed_bytes)}</span> : <span className="badge">Not installed</span>}
      </div>
      {running && (
        <div className="stack">
          <Progress value={d.total ? d.done / d.total : 0} indeterminate={!d.total} />
          <div className="row between text-xs"><span className="truncate">{d.current || "Preparing…"}</span><span className="mono">{fmtBytes(d.done)} / {d.total ? fmtBytes(d.total) : "?"}{d.speed ? ` · ${fmtBytes(d.speed)}/s` : ""}{d.speed > 0 && d.total ? ` · ${fmtEta((d.total - d.done) / d.speed)}` : ""}</span></div>
        </div>
      )}
      {d.status === "error" && <p className="error-text" role="alert">{d.error}</p>}
      {size !== null && !m.installed && !running && <p className="text-sm">Download size: <b>{fmtBytes(size)}</b>{tooBig ? ` — more than the ${free} GB free on this drive.` : ""}</p>}
      <div className="row gap wrap">
        {running ? (
          <Button variant="secondary" small onClick={() => act(() => api.cancelDownload(m.id))}>Pause download</Button>
        ) : !m.installed ? (
          <>
            <Button small icon={I.download} busy={busy} disabled={tooBig} onClick={() => act(() => api.download(m.id))}>{d.status === "cancelled" || d.status === "error" ? "Resume download" : "Download"}</Button>
            {size === null && <Button variant="ghost" small busy={busy} onClick={probe}>Check size</Button>}
          </>
        ) : (
          <Button variant="ghost" small icon={I.trash} onClick={() => { if (confirm(`Delete ${m.label}? You can download it again later.`)) act(() => api.deleteModel(m.id)); }}>Delete</Button>
        )}
      </div>
    </div>
  );
}

export function ModelList() {
  const { models } = useApp();
  return <div className="stack gap">{models.map((m) => <ModelCard key={m.id} m={m} />)}</div>;
}
