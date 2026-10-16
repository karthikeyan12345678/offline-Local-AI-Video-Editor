import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type SetupPlan } from "../lib/api";
import { fmtBytes, isDownloading } from "../lib/format";
import { useApp } from "../lib/store";
import { Button, Icon, I, Progress } from "../ds";
import { fmtEta } from "./Models";

const mbps = (bytesPerSec: number) => `${((bytesPerSec * 8) / 1e6).toFixed(1)} Mb/s`;
type Shell = { vk?: { turnOnGpu: () => Promise<{ ok: boolean; message?: string }> } };

/** Shows the graphics card and, when PyTorch cannot use it yet, a one-click fix (the desktop app does the work). */
function GpuRow({ plan }: { plan: SetupPlan }) {
  const { toast } = useApp();
  const g = plan.gpu;
  const shell = (window as unknown as Shell).vk;
  if (!g.present) return <p className="text-sm">No NVIDIA graphics card was found, so videos are made on the processor. This works but is slow.</p>;
  if (g.usable) return <p className="text-sm"><b>✓ {g.name} · {g.vram_gb} GB</b> is switched on and used for video making.</p>;
  return (
    <div className="card card--muted stack gap" role="status">
      <b>Your graphics card ({g.name}, {g.vram_gb} GB) is found but not switched on yet</b>
      <p className="text-sm">The AI engine is running on the processor, which is many times slower. One click installs the graphics-card version of PyTorch (about 2.5 GB, once). Everything already installed is kept.</p>
      {shell ? <Button icon={I.sparkle} onClick={async () => { const r = await shell.turnOnGpu(); if (!r.ok && r.message && r.message !== "Cancelled.") toast(r.message, true); }}>Turn on my graphics card</Button>
        : <p className="text-xs">In the VK Editor desktop app use the menu <b>Help → Turn on graphics card (GPU)</b>.</p>}
    </div>
  );
}

/** One button that downloads everything this PC needs, with total size, speed and time left. */
export default function SmartInstall({ compact = false }: { compact?: boolean }) {
  const { models, refreshModels, toast } = useApp();
  const [plan, setPlan] = useState<SetupPlan | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => api.setupPlan().then(setPlan).catch(() => {}), []);
  useEffect(() => { void load(); }, [load]);

  const rows = useMemo(() => (plan?.items ?? []).map((it) => {
    const m = models.find((x) => x.id === it.id);
    const d = m?.download;
    const installed = !!m?.installed;
    const running = isDownloading(d?.status);
    const total = installed ? m!.installed_bytes : d?.total || it.approx_bytes;
    const done = installed ? total : d?.done ?? 0;
    return { it, m, d, installed, running, total, done, failed: d?.status === "error" };
  }), [plan, models]);

  const working = rows.some((r) => r.running);
  // keep the numbers moving while anything downloads
  useEffect(() => {
    if (!working && !busy) return;
    const t = setInterval(() => { void refreshModels(); }, 1000);
    return () => clearInterval(t);
  }, [working, busy, refreshModels]);
  useEffect(() => { if (!working) void load(); }, [working, load]); // real sizes appear once a download is under way

  if (!plan) return <section className="card" aria-busy="true"><p className="text-sm">Looking at your computer…</p></section>;
  const todo = rows.filter((r) => !r.installed);
  const all = todo.reduce((a, r) => a + r.total, 0), have = todo.reduce((a, r) => a + Math.min(r.done, r.total), 0);
  const speed = rows.reduce((a, r) => a + (r.running ? r.d?.speed ?? 0 : 0), 0);
  const left = Math.max(0, all - have);
  const finished = todo.length === 0;
  const started = todo.some((r) => r.done > 0 || r.running || r.d?.status === "cancelled");
  const pct = all ? Math.min(100, Math.floor((have / all) * 100)) : 0;

  const go = async () => {
    setBusy(true);
    try { await api.setupInstall(); await refreshModels(); } catch (e) { toast((e as Error).message, true); } finally { setBusy(false); }
  };

  return (
    <section className="card stack gap" aria-labelledby="smart">
      <div className="stack">
        <h2 id="smart">{finished ? "Everything is installed ✓" : "Install everything for this PC"}</h2>
        <p className="text-sm">{finished ? "All the AI parts for your computer are ready. Nothing is downloaded again." : `We looked at your computer (${plan.summary}) and chose the best parts for it. One click installs them all.`}</p>
      </div>
      <GpuRow plan={plan} />
      <ul className="smart-list">
        {plan.engine.installed && (
          <li className="smart-row">
            <span className="dot dot--ok" aria-hidden="true"><Icon d={I.check} size={12} /></span>
            <div className="stack grow"><span className="w-medium">AI engine (PyTorch {plan.engine.version})</span>{!compact && <span className="text-xs">Already installed — it is never downloaded again.</span>}</div>
            <span className="text-xs mono smart-size">Installed</span>
          </li>
        )}
        {rows.map(({ it, installed, running, d, total, done, failed }) => (
          <li key={it.id} className="smart-row">
            <span className={`dot ${installed ? "dot--ok" : "dot--warn"}`} aria-hidden="true">{installed ? <Icon d={I.check} size={12} /> : running ? <span className="spinner" /> : null}</span>
            <div className="stack grow">
              <span className="w-medium">{it.label}</span>
              {!compact && <span className="text-xs">{it.why}</span>}
              {running && <Progress value={d?.total ? Math.min(1, done / total) : 0} indeterminate={!d?.total} />}
              {running && <span className="text-xs">{d?.total ? `${Math.floor((done / total) * 100)}%` : "Looking up the files…"}{d?.speed ? ` · ${fmtBytes(d.speed)}/s` : ""}{d?.current ? ` · ${d.current.split("/").pop()}` : ""}</span>}
              {failed && <span className="error-text text-xs" role="alert">{d?.error || "The download stopped."} Press “Continue installing”.</span>}
              {!running && !installed && !failed && done > 0 && <span className="text-xs">Paused at {Math.floor((done / Math.max(1, total)) * 100)}% — it continues from here.</span>}
            </div>
            <span className="text-xs mono smart-size">{installed ? "Installed" : running ? `${fmtBytes(done)} / ${fmtBytes(total)}` : `${it.size_known ? "" : "about "}${fmtBytes(total)}`}</span>
          </li>
        ))}
      </ul>
      {!finished && (
        <div className="stack">
          <Progress value={all ? have / all : 0} indeterminate={working && !have} />
          <div className="row between wrap text-sm" aria-live="polite">
            <span><b>{pct}%</b> · {fmtBytes(have)} of {fmtBytes(all)}</span>
            <span>{working ? (speed > 0 ? `${fmtBytes(speed)}/s (${mbps(speed)}) · ${fmtEta(left / speed) || "almost done"}` : "measuring speed…") : `${started ? `${fmtBytes(left)} left` : `Download size: ${fmtBytes(all)}`}`}</span>
          </div>
          {!plan.enough_disk && <p className="error-text text-sm" role="alert">This drive has {plan.disk_free_gb} GB free but about {plan.need_gb} GB is needed. Free some space first.</p>}
          <div className="row gap wrap">
            <Button icon={I.download} busy={busy || working} disabled={!plan.enough_disk} onClick={go}>{working ? "Installing… keep this window open" : started ? "Continue installing" : "Install everything (one click)"}</Button>
            {working && <span className="text-xs">You can close the app any time; it continues where it stopped.</span>}
          </div>
        </div>
      )}
    </section>
  );
}
