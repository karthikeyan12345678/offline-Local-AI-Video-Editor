import { Fragment, useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError, fileUrl } from "./lib/api";
import type { FileRef } from "./lib/types";

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 ** 2).toFixed(1)} MB`;
}
export const errText = (e: unknown) => (e instanceof ApiError || e instanceof Error ? e.message : "Something went wrong.");

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
