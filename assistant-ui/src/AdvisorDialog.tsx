import { useEffect, useState } from "react";

interface Row { id: string; name: string; model: string; why: string; url?: string; how?: string; size?: string; free?: boolean }
export interface Advice { pc: string; local: Row; free_online: Row[]; paid: Row[]; best: Row; picture: string; tip: string; current: { ready: boolean; name: string; model: string }; video?: { local: string; cloud: string; device: string } }

function Pick({ r, best, onPick, label }: { r: Row; best: boolean; onPick: (id: string, model: string) => void; label: string }) {
  return (
    <div className={`adv-row${best ? " adv-row--best" : ""}`}>
      <div className="adv-text">
        <b>{r.name}{best ? "  ·  best for your PC" : ""}</b>
        <span className="adv-sub">{r.model}{r.size ? ` · ${r.size}` : ""}</span>
        <span className="adv-why">{r.why}</span>
        {r.how && <code className="adv-how">{r.how}</code>}
        {r.url && <span className="adv-sub">Get a key: {r.url}</span>}
      </div>
      <button type="button" className={best ? "adv-btn adv-btn--on" : "adv-btn"} onClick={() => onPick(r.id, r.model)}>{label}</button>
    </div>
  );
}

/** Pop-up that says which AI suits this PC: one on this computer, a free online one, and the best paid one. */
export default function AdvisorDialog({ load, onPick, onClose }: { load: () => Promise<Advice>; onPick: (id: string, model: string) => void; onClose: () => void }) {
  const [a, setA] = useState<Advice | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => { load().then(setA).catch(() => setErr("Could not read this PC. Pick a provider from the list instead.")); }, [load]);
  useEffect(() => { const k = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); }; window.addEventListener("keydown", k); return () => window.removeEventListener("keydown", k); }, [onClose]);
  return (
    <div className="adv-veil" role="dialog" aria-modal="true" aria-label="Choose the best AI for this PC" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="adv">
        <div className="adv-head"><h2>Which AI should I use?</h2><button type="button" className="adv-x" aria-label="Close" onClick={onClose}>✕</button></div>
        {!a && !err && <p>Checking your PC…</p>}
        {err && <p role="alert">{err}</p>}
        {a && (
          <>
            <p className="adv-pc">Your PC: <b>{a.pc}</b></p>
            {a.current.ready && <p className="adv-sub">Now connected: {a.current.name} ({a.current.model}).</p>}
            <h3>Runs on this PC (free, private, works offline)</h3>
            <Pick r={a.local} best={a.best.id === a.local.id} onPick={onPick} label="Use this" />
            <h3>Free online (needs internet and a free key)</h3>
            {a.free_online.map((r) => <Pick key={r.id} r={r} best={a.best.id === r.id} onPick={onPick} label="Use this" />)}
            <h3>Paid, best quality</h3>
            {a.paid.map((r) => <Pick key={r.id} r={r} best={a.best.id === r.id} onPick={onPick} label="Use this" />)}
            <p className="adv-sub">Pictures on this PC: {a.picture}.</p>
            {a.video && <p className="adv-sub">Videos: {a.video.local} Or {a.video.cloud}</p>}
            <p className="adv-sub">{a.tip}</p>
          </>
        )}
        <div className="adv-foot"><button type="button" className="adv-btn" onClick={onClose}>Not now</button></div>
      </div>
    </div>
  );
}
