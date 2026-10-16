import { useEffect, useRef, type ButtonHTMLAttributes, type ReactNode } from "react";

export const Icon = ({ d, size = 16 }: { d: string; size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d={d} />
  </svg>
);

export const I = {
  play: "M6 4l14 8-14 8z", pause: "M8 4v16M16 4v16", plus: "M12 5v14M5 12h14", trash: "M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3",
  scissors: "M6 6a3 3 0 1 0 0 .01M6 18a3 3 0 1 0 0 .01M8.5 8.5L20 20M8.5 15.5L20 4", undo: "M9 14L4 9l5-5M4 9h10a6 6 0 0 1 0 12h-3",
  redo: "M15 14l5-5-5-5M20 9H10a6 6 0 0 0 0 12h3", download: "M12 4v12M7 11l5 5 5-5M5 20h14", upload: "M12 16V4M7 9l5-5 5 5M5 20h14",
  x: "M6 6l12 12M18 6L6 18", film: "M4 4h16v16H4zM8 4v16M16 4v16M4 9h4M16 9h4M4 15h4M16 15h4", sparkle: "M12 3l2.2 5.8L20 11l-5.8 2.2L12 19l-2.2-5.8L4 11l5.8-2.2z",
  folder: "M3 6h6l2 2h10v11H3z", gear: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19 12l2-1-2-4-2 1-2-1-.5-2.2h-4L10 7 8 8 6 7 4 11l2 1v2l-2 1 2 4 2-1 2 1 .5 2.2h4L14 19l2-1 2 1 2-4-2-1z",
  alert: "M12 3l10 18H2zM12 10v5M12 18v.01", check: "M5 12l5 5 9-10", split: "M12 3v18M8 7l-4 5 4 5M16 7l4 5-4 5",
  text: "M5 6V4h14v2M12 4v16M9 20h6", music: "M9 18V5l11-2v13M9 18a3 3 0 1 1-6 0 3 3 0 0 1 6 0zM20 16a3 3 0 1 1-6 0 3 3 0 0 1 6 0z",
  image: "M4 5h16v14H4zM4 16l5-5 4 4 3-3 4 4M9 9.5a1 1 0 1 0 0 .01", dup: "M8 8h12v12H8zM4 16V4h12", skipBack: "M6 5v14M20 5L9 12l11 7z",
  zoomIn: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM21 21l-5-5M11 8v6M8 11h6", zoomOut: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM21 21l-5-5M8 11h6",
  wand: "M15 4l5 5L8 21l-5-5zM13 6l5 5", chev: "M9 6l6 6-6 6",
};

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost"; small?: boolean; icon?: string; busy?: boolean; active?: boolean; label?: string };
export function Button({ variant = "primary", small, icon, busy, active, label, children, className = "", ...rest }: BtnProps) {
  const cls = ["btn", variant === "secondary" && "btn--secondary", variant === "ghost" && "btn--ghost", small && "btn--sm", !children && icon && "btn--icon", active && "btn--active", className].filter(Boolean).join(" ");
  return (
    <button type="button" {...rest} className={cls} aria-busy={busy || undefined} aria-label={label ?? rest["aria-label"]} title={label ?? rest.title} disabled={rest.disabled || busy}>
      {busy ? <span className="spinner" /> : icon ? <Icon d={icon} /> : null}
      {children}
    </button>
  );
}

export function Field({ label, hint, error, children, htmlFor }: { label: string; hint?: ReactNode; error?: string | null; children: ReactNode; htmlFor?: string }) {
  return (
    <div className="field">
      <label className="label" htmlFor={htmlFor}>{label}</label>
      {children}
      {error ? <span className="error-text" role="alert"><Icon d={I.alert} size={14} />{error}</span> : hint ? <span className="hint muted">{hint}</span> : null}
    </div>
  );
}

export function Slider({ label, value, min, max, step = 1, onChange, format, disabled }: { label: string; value: number; min: number; max: number; step?: number; onChange: (v: number) => void; format?: (v: number) => string; disabled?: boolean }) {
  const id = useRef(`s${Math.random().toString(36).slice(2, 8)}`).current;
  return (
    <div className="field">
      <div className="row between">
        <label className="label" htmlFor={id}>{label}</label>
        <span className="text-xs mono">{format ? format(value) : value}</span>
      </div>
      <input id={id} className="range" type="range" min={min} max={max} step={step} value={value} disabled={disabled} onChange={(e) => onChange(Number(e.target.value))} onDoubleClick={() => undefined} />
    </div>
  );
}

export function Progress({ value, indeterminate }: { value?: number; indeterminate?: boolean }) {
  return (
    <div className={`progress${indeterminate ? " progress--indeterminate" : ""}`} role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={indeterminate ? undefined : Math.round((value ?? 0) * 100)}>
      <span style={indeterminate ? undefined : { width: `${Math.round((value ?? 0) * 100)}%` }} />
    </div>
  );
}

export function Dialog({ title, onClose, children, footer }: { title: string; onClose: () => void; children: ReactNode; footer?: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLElement>("input,select,textarea,button")?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("keydown", onKey); prev?.focus(); };
  }, [onClose]);
  return (
    <div className="overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="dialog" role="dialog" aria-modal="true" aria-label={title} ref={ref}>
        <div className="row between"><h2>{title}</h2><Button variant="ghost" small icon={I.x} label="Close" onClick={onClose} /></div>
        {children}
        {footer && <div className="row end gap">{footer}</div>}
      </div>
    </div>
  );
}

export function Empty({ icon, title, children }: { icon: string; title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <Icon d={icon} size={24} />
      <h3>{title}</h3>
      {children && <p className="text-sm muted">{children}</p>}
    </div>
  );
}

export function Tabs<T extends string>({ value, options, onChange, label }: { value: T; options: { id: T; label: string; disabled?: boolean }[]; onChange: (v: T) => void; label: string }) {
  return (
    <div className="tabs" role="tablist" aria-label={label}>
      {options.map((o) => (
        <button key={o.id} type="button" role="tab" className="tab" aria-selected={value === o.id} disabled={o.disabled} onClick={() => onChange(o.id)}>{o.label}</button>
      ))}
    </div>
  );
}
