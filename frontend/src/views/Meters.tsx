import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { Usage } from "../lib/types";

function Meter({ label, pct, text }: { label: string; pct: number | null; text: string }) {
  const v = pct == null ? 0 : Math.max(0, Math.min(100, pct));
  return (
    <div className="meter" title={`${label}: ${text}`}>
      <div className="row between"><span className="text-xs">{label}</span><span className="text-xs mono">{text}</span></div>
      <div className={`bar bar--thin${v > 90 ? " bar--hot" : ""}`} role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(v)}><i style={{ width: `${pct == null ? 0 : Math.max(v, 2)}%` }} /></div>
    </div>
  );
}

/** Live CPU, graphics card, memory and graphics memory of this PC, refreshed every two seconds. */
export default function Meters({ jobId = "", compact = false }: { jobId?: string; compact?: boolean }) {
  const [u, setU] = useState<Usage | null>(null);
  useEffect(() => {
    let live = true;
    const tick = () => api.usage(jobId).then((x) => { if (live) setU(x); }).catch(() => {});
    tick();
    const t = setInterval(tick, 2000);
    return () => { live = false; clearInterval(t); };
  }, [jobId]);
  if (!u) return null;
  const f = (n: number | null | undefined, unit = "") => (n == null ? "n/a" : `${Math.round(n)}${unit}`);
  const pct = (a: number | null, b: number | null) => (a != null && b ? (a / b) * 100 : null);
  return (
    <div className={`meters${compact ? " meters--compact" : ""}`} aria-label="This PC right now">
      <div className="meters-grid">
        <Meter label="CPU" pct={u.cpu} text={f(u.cpu, "%")} />
        <Meter label="GPU" pct={u.gpu} text={f(u.gpu, "%")} />
        <Meter label="Memory (RAM)" pct={pct(u.ram_used_gb, u.ram_total_gb)} text={u.ram_used_gb == null ? "n/a" : `${u.ram_used_gb.toFixed(1)} / ${u.ram_total_gb?.toFixed(1)} GB`} />
        <Meter label="Graphics memory (VRAM)" pct={pct(u.vram_used_gb ?? null, u.vram_total_gb ?? null)} text={u.vram_used_gb == null ? "no GPU" : `${u.vram_used_gb.toFixed(1)} / ${u.vram_total_gb?.toFixed(1)} GB`} />
      </div>
      {u.why_slow && <p className="meters-why" role="status"><b>Why it is slow:</b> {u.why_slow}</p>}
    </div>
  );
}
