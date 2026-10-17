import { useEffect, useState } from "react";

export interface TourStep { target?: string; title: string; body: string; go?: () => void }

/** A short guided tour: highlights one part of the screen at a time. Skip works at every step (button or Escape). */
export default function Tour({ steps, onDone }: { steps: TourStep[]; onDone: () => void }) {
  const [i, setI] = useState(0);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const step = steps[i];
  useEffect(() => { step.go?.(); }, [step]);
  useEffect(() => {
    const measure = () => {
      const el = step.target ? document.querySelector<HTMLElement>(`[data-tour="${step.target}"]`) : null;
      setRect(el ? el.getBoundingClientRect() : null);
    };
    const t = setTimeout(measure, 60);
    window.addEventListener("resize", measure);
    return () => { clearTimeout(t); window.removeEventListener("resize", measure); };
  }, [step]);
  useEffect(() => { const k = (e: KeyboardEvent) => { if (e.key === "Escape") onDone(); if (e.key === "ArrowRight") setI((n) => Math.min(steps.length - 1, n + 1)); if (e.key === "ArrowLeft") setI((n) => Math.max(0, n - 1)); }; window.addEventListener("keydown", k); return () => window.removeEventListener("keydown", k); }, [onDone, steps.length]);
  const last = i === steps.length - 1;
  const pad = 6;
  const card: React.CSSProperties = rect
    ? { left: Math.min(window.innerWidth - 340, rect.right + 16), top: Math.max(12, Math.min(window.innerHeight - 260, rect.top - 10)) }
    : { left: "50%", top: "50%", transform: "translate(-50%,-50%)" };
  return (
    <div className="tour" role="dialog" aria-modal="true" aria-label="Guided tour">
      {rect ? <div className="tour-spot" style={{ left: rect.left - pad, top: rect.top - pad, width: rect.width + pad * 2, height: rect.height + pad * 2 }} /> : <div className="tour-dim" />}
      <div className="tour-card" style={card}>
        <div className="tour-top"><span className="tour-count">Step {i + 1} of {steps.length}</span><button type="button" className="tour-skip" onClick={onDone}>Skip tour</button></div>
        <h3>{step.title}</h3>
        <p>{step.body}</p>
        <div className="tour-dots" aria-hidden="true">{steps.map((_, n) => <i key={n} className={n === i ? "on" : ""} />)}</div>
        <div className="tour-nav">
          <button type="button" className="adv-btn" onClick={() => setI(i - 1)} disabled={i === 0}>Back</button>
          <button type="button" className="adv-btn adv-btn--on" onClick={() => (last ? onDone() : setI(i + 1))} autoFocus>{last ? "Finish" : "Next"}</button>
        </div>
      </div>
    </div>
  );
}
