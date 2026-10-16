import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type SetupPlan } from "../lib/api";
import { fmtBytes } from "../lib/format";
import { useApp } from "../lib/store";
import { Button, Icon, I, Progress } from "../ds";
import { fmtEta } from "./Models";

const mbps = (bytesPerSec: number) => `${((bytesPerSec * 8) / 1e6).toFixed(1)} Mb/s`;

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
    const running = d ? ["running", "queued"].includes(d.status) : false;
    const total = installed ? m!.installed_bytes : d?.total || it.approx_bytes;
    const done = installed ? total : d?.done ?? 0;
    return { it, m, d, installed, running, total, done, failed: d?.status === "error" };
  }), [plan, models]);

  if (!plan) return null;
  const all = rows.reduce((a, r) => a + r.total, 0), have = rows.reduce((a, r) => a + Math.min(r.done, r.total), 0);
  const speed = rows.reduce((a, r) => a + (r.running ? r.d?.speed ?? 0 : 0), 0);
  const left = Math.max(0, all - have);
  const working = rows.some((r) => r.running);
  const finished = rows.every((r) => r.installed);

  const go = async () => {
    setBusy(true);
    try { await api.setupInstall(); await refreshModels(); await load(); } catch (e) { toast((e as Error).message, true); } finally { setBusy(false); }
  };

  return (
    <section className="card stack gap" aria-labelledby="smart">
      <div className="stack">
        <h2 id="smart">{finished ? "Everything is installed ✓" : "Install everything for this PC"}</h2>
        <p className="text-sm">{finished ? "All the AI parts for your computer are ready. You can start making videos." : `We looked at your computer (${plan.summary}) and chose the best parts for it. One click installs them all.`}</p>
      </div>
      <ul className="smart-list">
        {rows.map(({ it, installed, running, d, total, done, failed }) => (
          <li key={it.id} className="smart-row">
            <span className={`dot ${installed ? "dot--ok" : "dot--warn"}`} aria-hidden="true">{installed ? <Icon d={I.check} size={12} /> : running ? <span className="spinner" /> : null}</span>
            <div className="stack grow">
              <span className="w-medium">{it.label}</span>
              {!compact && <span className="text-xs">{it.why}</span>}
              {running && <Progress value={total ? Math.min(1, done / total) : 0} indeterminate={!d?.total} />}
              {failed && <span className="error-text text-xs" role="alert">{d?.error}</span>}
            </div>
            <span className="text-xs mono smart-size">{installed ? "Installed" : running ? `${fmtBytes(done)} / ${fmtBytes(total)}` : d?.status === "queued" ? "Waiting" : `about ${fmtBytes(it.approx_bytes)}`}</span>
          </li>
        ))}
      </ul>
      {!finished && (
        <div className="stack">
          <Progress value={all ? have / all : 0} indeterminate={working && !have} />
          <div className="row between wrap text-sm">
            <span><b>{all ? Math.round((have / all) * 100) : 0}%</b> · {fmtBytes(have)} of {fmtBytes(all)}</span>
            <span>{working ? `${speed ? `${fmtBytes(speed)}/s (${mbps(speed)})` : "measuring speed…"}${speed > 0 ? ` · ${fmtEta(left / speed) || "almost done"}` : ""}` : `Download size: about ${fmtBytes(plan.missing_bytes)}`}</span>
          </div>
          {!plan.enough_disk && <p className="error-text text-sm" role="alert">This drive has {plan.disk_free_gb} GB free but about {plan.need_gb} GB is needed. Free some space first.</p>}
          <div className="row gap wrap">
            <Button icon={I.download} busy={busy || working} disabled={!plan.enough_disk} onClick={go}>{working ? "Installing… keep this window open" : rows.some((r) => r.failed || r.d?.status === "cancelled") ? "Continue installing" : "Install everything (one click)"}</Button>
            {working && <span className="text-xs">You can close the app any time; it continues where it stopped.</span>}
          </div>
        </div>
      )}
    </section>
  );
}
