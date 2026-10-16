import { Fragment, useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError, fileUrl } from "./lib/api";
import type { FileRef } from "./lib/types";

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 ** 2).toFixed(1)} MB`;
}
export const errText = (e: unknown) => (e instanceof ApiError || e instanceof Error ? e.message : "Something went wrong.");

const PATHS: Record<string, string> = {
  chat: "M4 5h16v11H9l-5 4zM8 9h8M8 12h5", doc: "M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6", check: "M12 3l7 3v5c0 5-3 8-7 10-4-2-7-5-7-10V6zM9 12l2 2 4-4",
  compare: "M8 4v16M16 4v16M4 8l4-4 4 4M12 16l4 4 4-4", chart: "M4 20V10M10 20V4M16 20v-8M22 20H2", image: "M4 5h16v14H4zM4 16l5-5 4 4 3-3 4 4M9 9a1 1 0 1 0 0 .01",
  folder: "M3 6h6l2 2h10v11H3z", gear: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19 12a7 7 0 0 0-.1-1.2l2-1.5-2-3.4-2.3 1a7 7 0 0 0-2-1.2L14 3h-4l-.4 2.7a7 7 0 0 0-2 1.2l-2.3-1-2 3.4 2 1.5A7 7 0 0 0 5 12c0 .4 0 .8.1 1.2l-2 1.5 2 3.4 2.3-1a7 7 0 0 0 2 1.2L10 21h4l.4-2.7a7 7 0 0 0 2-1.2l2.3 1 2-3.4-2-1.5c.1-.4.1-.8.1-1.2z",
  plus: "M12 5v14M5 12h14", send: "M12 19V5M6 11l6-6 6 6", stop: "M7 7h10v10H7z", clip: "M20 11l-8 8a5 5 0 0 1-7-7l8-8a3.5 3.5 0 0 1 5 5l-8 8a2 2 0 0 1-3-3l7-7", x: "M6 6l12 12M18 6L6 18",
  spark: "M12 3l2.2 5.8L20 11l-5.8 2.2L12 19l-2.2-5.8L4 11l5.8-2.2z", palette: "M12 3a9 9 0 1 0 0 18c1.5 0 2-1 1.5-2-.6-1.2.2-2.5 1.6-2.5H17a4 4 0 0 0 4-4c0-5-4-9.5-9-9.5zM7.5 11h.01M10 7.5h.01M14.5 7.5h.01",
};
export function Ico({ name, size = 18 }: { name: keyof typeof PATHS | string; size?: number }) {
  return <svg className="ico" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={PATHS[name] ?? ""} /></svg>;
}

/** Progress for work with no exact step count: the bar follows the engine's own estimate and the clock shows real time passed. */
export function ProgressLine({ fraction, text, elapsed, label = "Progress" }: { fraction: number; text?: string; elapsed?: number; label?: string }) {
  const pct = Math.max(2, Math.min(100, Math.round(fraction * 100)));
  return (
    <div className="progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-label={label}>
      <div className="progress-track"><i style={{ width: `${pct}%` }} /></div>
      <div className="progress-meta"><span className="truncate">{text || "Working…"}</span><span className="num">{pct}%{elapsed != null ? ` · ${Math.floor(elapsed)} s` : ""}</span></div>
    </div>
  );
}

/** Same bar for requests that only report when they are finished: a smooth estimate that never reaches 100% on its own. */
export function TimedProgress({ active, tau = 20, text, label }: { active: boolean; tau?: number; text?: string; label?: string }) {
  const [t, setT] = useState(0);
  useEffect(() => {
    if (!active) { setT(0); return; }
    const t0 = Date.now(); const id = setInterval(() => setT((Date.now() - t0) / 1000), 250);
    return () => clearInterval(id);
  }, [active]);
  if (!active) return null;
  return <ProgressLine fraction={0.92 * (1 - Math.exp(-t / tau))} elapsed={t} text={text} label={label} />;
}

export function Spinner() { return <span className="spinner" role="status" aria-label="Working" />; }

export function Banner({ kind = "info", children, onClose }: { kind?: "info" | "error"; children: ReactNode; onClose?: () => void }) {
  return (
    <div className={`banner banner--${kind}`} role={kind === "error" ? "alert" : "status"}>
      <span className="icon" aria-hidden="true">{kind === "error" ? "!" : "i"}</span>
      <div style={{ flex: 1, minWidth: 0 }}>{kind === "error" && <strong>Problem: </strong>}{children}</div>
      {onClose && <button className="btn btn--ghost btn--sm" onClick={onClose} aria-label="Dismiss">Dismiss</button>}
    </div>
  );
}

export function Button({ busy, children, variant, size, ...rest }: React.ButtonHTMLAttributes<HTMLButtonElement> & { busy?: boolean; variant?: "secondary" | "ghost" | "danger"; size?: "sm" | "icon" }) {
  const cls = ["btn", variant && `btn--${variant}`, size && `btn--${size}`].filter(Boolean).join(" ");
  return <button {...rest} className={cls} aria-busy={busy || undefined} disabled={rest.disabled || busy}>{busy && <Spinner />}{children}</button>;
}

export function DownloadLink({ file, label }: { file: FileRef; label?: string }) {
  return <a className="btn btn--secondary btn--sm" href={fileUrl(file.id)} download={file.name}>{label ?? "Download"} <span className="muted">· {file.name.split(".").pop()?.toUpperCase()} · {fmtBytes(file.size)}</span></a>;
}

/** Lets a person drop/choose files and keeps them listed. */
export function FilePicker({ label, files, onChange, max = 1, accept, hint }: { label: string; files: FileRef[]; onChange: (f: FileRef[]) => void; max?: number; accept?: string; hint?: string }) {
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [over, setOver] = useState(false);
  const add = useCallback(async (list: FileList | File[]) => {
    setErr(""); setBusy(true);
    try {
      const next = [...files];
      for (const f of Array.from(list)) {
        if (next.length >= max) { if (max === 1) next.length = 0; else break; }
        next.push(await api.upload(f));
      }
      onChange(next.slice(-max));
    } catch (e) { setErr(errText(e)); } finally { setBusy(false); if (input.current) input.current.value = ""; }
  }, [files, max, onChange]);
  return (
    <div className="field">
      <span className="label" id={`lbl-${label}`}>{label}</span>
      <div className={`drop ${over ? "drop--over" : ""}`} onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
           onDrop={(e) => { e.preventDefault(); setOver(false); void add(e.dataTransfer.files); }}>
        <input ref={input} type="file" hidden multiple={max > 1} accept={accept} onChange={(e) => e.target.files && void add(e.target.files)} aria-labelledby={`lbl-${label}`} />
        {files.length === 0 && <span className="muted">Drop {max > 1 ? "files" : "a file"} here or</span>}
        {files.map((f) => (
          <span key={f.id} className="chip" title={f.name}>
            <span className="truncate" style={{ maxWidth: 200 }}>{f.name}</span>
            <button className="chip-x" aria-label={`Remove ${f.name}`} onClick={() => onChange(files.filter((x) => x.id !== f.id))}>×</button>
          </span>
        ))}
        <Button variant="secondary" size="sm" busy={busy} onClick={() => input.current?.click()}>{files.length ? (max > 1 && files.length < max ? "Add another" : "Replace") : "Choose file"}</Button>
      </div>
      {hint && <span className="hint">{hint}</span>}
      {err && <Banner kind="error">{err}</Banner>}
    </div>
  );
}

/* A small, safe Markdown renderer for chat replies (no raw HTML is ever injected). */
function inline(text: string, key: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*|\[[^\]]+\]\((https?:\/\/[^)\s]+)\))/g;
  let last = 0, m: RegExpExecArray | null, i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const t = m[0];
    if (t.startsWith("**")) out.push(<strong key={`${key}${i++}`}>{t.slice(2, -2)}</strong>);
    else if (t.startsWith("`")) out.push(<code key={`${key}${i++}`} className="mono code-inline">{t.slice(1, -1)}</code>);
    else if (t.startsWith("[")) { const mm = /\[([^\]]+)\]\(([^)]+)\)/.exec(t)!; out.push(<a key={`${key}${i++}`} href={mm[2]} target="_blank" rel="noreferrer noopener">{mm[1]}</a>); }
    else out.push(<em key={`${key}${i++}`}>{t.slice(1, -1)}</em>);
    last = m.index + t.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function Markdown({ text }: { text: string }) {
  const lines = text.replace(/\r/g, "").split("\n");
  const nodes: ReactNode[] = [];
  let i = 0, k = 0;
  while (i < lines.length) {
    const l = lines[i];
    if (l.trim().startsWith("```")) {
      const buf: string[] = []; i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) buf.push(lines[i++]);
      i++;
      nodes.push(<CodeBlock key={k++} code={buf.join("\n")} />);
    } else if (/^\s*\|.*\|\s*$/.test(l) && i + 1 < lines.length && /^\s*\|?\s*:?-+/.test(lines[i + 1])) {
      const cells = (s: string) => s.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      const head = cells(l); i += 2;
      const rows: string[][] = [];
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) rows.push(cells(lines[i++]));
      nodes.push(<div key={k++} className="table-wrap"><table className="table"><thead><tr>{head.map((h, j) => <th key={j}>{inline(h, `h${j}`)}</th>)}</tr></thead>
        <tbody>{rows.map((r, a) => <tr key={a}>{r.map((c, b) => <td key={b}>{inline(c, `c${a}${b}`)}</td>)}</tr>)}</tbody></table></div>);
    } else if (/^\s*([-*•]|\d+[.)])\s+/.test(l)) {
      const ordered = /^\s*\d+[.)]/.test(l);
      const items: string[] = [];
      while (i < lines.length && /^\s*([-*•]|\d+[.)])\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*([-*•]|\d+[.)])\s+/, ""));
      const Tag = ordered ? "ol" : "ul";
      nodes.push(<Tag key={k++}>{items.map((t, j) => <li key={j}>{inline(t, `li${j}`)}</li>)}</Tag>);
    } else if (/^#{1,4}\s/.test(l)) {
      const lvl = l.match(/^#+/)![0].length;
      nodes.push(lvl <= 2 ? <h2 key={k++}>{inline(l.replace(/^#+\s*/, ""), "h")}</h2> : <h3 key={k++}>{inline(l.replace(/^#+\s*/, ""), "h")}</h3>); i++;
    } else if (l.trim() === "") { i++; }
    else {
      const buf: string[] = [];
      while (i < lines.length && lines[i].trim() !== "" && !/^(#{1,4}\s|\s*([-*•]|\d+[.)])\s|\s*\||```)/.test(lines[i])) buf.push(lines[i++]);
      if (!buf.length) buf.push(lines[i++]);
      nodes.push(<p key={k++}>{buf.map((t, j) => <Fragment key={j}>{j > 0 && <br />}{inline(t, `p${j}`)}</Fragment>)}</p>);
    }
  }
  return <div className="md">{nodes}</div>;
}

function CodeBlock({ code }: { code: string }) {
  const [done, setDone] = useState(false);
  return (
    <div className="code">
      <button className="btn btn--ghost btn--sm code-copy" onClick={() => { void navigator.clipboard?.writeText(code).then(() => { setDone(true); setTimeout(() => setDone(false), 1500); }); }}>{done ? "Copied" : "Copy"}</button>
      <pre className="mono"><code>{code}</code></pre>
    </div>
  );
}

export function useAsync<T>() {
  const [state, setState] = useState<{ busy: boolean; error: string; data: T | null }>({ busy: false, error: "", data: null });
  const run = useCallback(async (fn: () => Promise<T>) => {
    setState((s) => ({ ...s, busy: true, error: "" }));
    try { const data = await fn(); setState({ busy: false, error: "", data }); return data; }
    catch (e) { setState((s) => ({ ...s, busy: false, error: errText(e) })); return null; }
  }, []);
  return { ...state, run, reset: () => setState({ busy: false, error: "", data: null }) };
}

export function useEscape(onEsc: () => void) {
  useEffect(() => { const h = (e: KeyboardEvent) => { if (e.key === "Escape") onEsc(); }; window.addEventListener("keydown", h); return () => window.removeEventListener("keydown", h); }, [onEsc]);
}
