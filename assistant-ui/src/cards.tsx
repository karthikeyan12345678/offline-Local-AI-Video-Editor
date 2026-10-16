import { useState } from "react";
import { DownloadLink, Markdown } from "./ui";
import { fileUrl } from "./lib/api";
import type { AnalyticsResult, AtsResult, Card, Column, CompareResult, FileRef, Segment, TableDiff, TextDiffItem, ThemeInfo } from "./lib/types";

export function Swatches({ colors }: { colors: Record<string, string> }) {
  const keys = ["bg", "surface", "text", "accent", "heading", "muted", "paper"].filter((k) => colors[k]).slice(0, 5);
  const list = keys.length ? keys.map((k) => colors[k]) : Object.values(colors).slice(0, 5);
  return <span className="swatches" aria-hidden="true">{list.map((c, i) => <i key={i} style={{ background: c }} />)}</span>;
}

export function ThemeTile({ t, selected, onPick }: { t: ThemeInfo; selected?: boolean; onPick?: (id: string) => void }) {
  return (
    <button className="tile" aria-pressed={selected} onClick={() => onPick?.(t.id)} title={t.description}>
      <Swatches colors={t.colors} />
      <span className="tile-name truncate">{t.name}</span>
      <span className="hint truncate">{t.category}{t.dark ? " · dark" : ""}</span>
      {t.reasons && t.reasons.length > 0 && <span className="hint tile-why">{t.reasons[0]}</span>}
    </button>
  );
}

export function FileCard({ card }: { card: Extract<Card, { type: "file" }> }) {
  return (
    <div className="card result">
      <div className="row">
        <span className="file-ico" aria-hidden="true">{card.file.kind.toUpperCase().slice(0, 4)}</span>
        <div style={{ flex: 1, minWidth: 0 }}><h3 className="truncate">{card.file.name}</h3>{card.note && <p className="hint">{card.note}</p>}</div>
        <DownloadLink file={card.file} />
      </div>
      {card.theme && <div className="row hint" style={{ marginTop: 8 }}><Swatches colors={card.theme.colors} /> Design: <strong>{card.theme.name}</strong> · {card.theme.reasons?.[0]}</div>}
      {card.warnings.map((w, i) => <p key={i} className="hint warn">Note: {w}</p>)}
    </div>
  );
}

function Gauge({ score, level }: { score: number; level: string }) {
  const r = 52, c = 2 * Math.PI * r;
  return (
    <div className="gauge" role="img" aria-label={`Score ${Math.round(score)} out of 100, ${level}`}>
      <svg viewBox="0 0 130 130" width="128" height="128">
        <circle cx="65" cy="65" r={r} fill="none" stroke="var(--overlay-3)" strokeWidth="10" />
        <circle cx="65" cy="65" r={r} fill="none" stroke="var(--color-accent)" strokeWidth="10" strokeLinecap="round" strokeDasharray={c} strokeDashoffset={c * (1 - score / 100)} transform="rotate(-90 65 65)" />
      </svg>
      <div className="gauge-n"><strong>{Math.round(score)}</strong><span className="hint">{level}</span></div>
    </div>
  );
}

export function AtsView({ r }: { r: AtsResult }) {
  const kw = r.categories.keywords;
  const sev = { high: "High", medium: "Medium", low: "Low" } as const;
  return (
    <div className="result">
      <div className="row" style={{ gap: 24, alignItems: "center", flexWrap: "wrap" }}>
        <Gauge score={r.score} level={r.level} />
        <div style={{ flex: 1, minWidth: 220 }}>
          <h3>{r.file}</h3>
          {r.before_score != null && <p className="ats-delta"><span className="num">{Math.round(r.before_score)}</span> → <strong className="num">{Math.round(r.score)}</strong> / 100 <span className="hint">after tailoring{r.score > r.before_score ? ` (+${Math.round(r.score - r.before_score)})` : ""}</span></p>}
          <p className="hint">{r.words.toLocaleString()} words · {r.has_job_description ? "scored against the job description" : "general score (no job description given)"}</p>
          <div className="bars">
            {Object.entries(r.categories).map(([k, c]) => (
              <div key={k} className="bar-row"><span className="text-sm">{c.label}</span>
                <div className="meter" role="meter" aria-valuemin={0} aria-valuemax={c.max} aria-valuenow={c.score} aria-label={c.label}><span style={{ width: `${(c.score / c.max) * 100}%` }} /></div>
                <span className="text-sm num">{c.score}/{c.max}</span></div>
            ))}
          </div>
        </div>
      </div>
      {kw?.matched && kw.missing && (
        <div className="cols">
          <div><h3>Found in your resume ({kw.matched.length})</h3><div className="chips">{kw.matched.map((m) => <span className="badge" key={m.keyword}>{m.keyword}</span>)}</div></div>
          <div><h3>Missing from your resume ({kw.missing.length})</h3>{kw.missing.length === 0 ? <p className="hint">Nothing important is missing.</p> :
            <div className="chips">{kw.missing.map((m) => <span className="badge badge--outline" key={m.keyword}>{m.keyword}</span>)}</div>}</div>
        </div>
      )}
      {kw?.skills_found && <div><h3>Skills detected</h3><div className="chips">{kw.skills_found.map((s) => <span className="badge" key={s}>{s}</span>)}</div></div>}
      {r.issues.length > 0 && (
        <div><h3>What to fix ({r.issues.length})</h3>
          <ol className="issues">{r.issues.map((i, n) => (
            <li key={n}><span className={`badge sev sev--${i.severity}`}>{sev[i.severity]}</span> <span>{i.message}</span><p className="hint">Fix: {i.fix}</p></li>
          ))}</ol></div>
      )}
      <p className="hint">{r.disclaimer}</p>
    </div>
  );
}

function Segs({ segs }: { segs: Segment[] }) {
  return <>{segs.map((s, i) => s.t === "equal" ? <span key={i}>{s.x}</span> : s.t === "ins" ? <ins key={i}>{s.x}</ins> : <del key={i}>{s.x}</del>)}</>;
}

function TextDiff({ items }: { items: TextDiffItem[] }) {
  const [all, setAll] = useState(false);
  const shown = all ? items : items.filter((i) => i.type !== "same");
  return (
    <div>
      <label className="check"><input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} /> Show unchanged parts too</label>
      <div className="diff">
        {shown.length === 0 && <p className="hint">No differences.</p>}
        {shown.map((it, n) => (
          <div key={n} className={`d d--${it.type}`}>
            <span className="d-tag">{{ same: "Same", changed: "Changed", added: "Added", removed: "Removed" }[it.type]}</span>
            <div className="d-body">{it.type === "changed" && it.segments ? <Segs segs={it.segments} /> : it.type === "added" ? <ins>{it.b}</ins> : it.type === "removed" ? <del>{it.a}</del> : it.a}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function TableDiffView({ t }: { t: TableDiff }) {
  return (
    <div className="card">
      <h3>{t.name_a === t.name_b ? t.name_a : `${t.name_a} → ${t.name_b}`} <span className="hint">· {Math.round(t.similarity * 100)}% similar · rows matched by {t.matched_by}</span></h3>
      <p className="hint">{t.rows_a} → {t.rows_b} rows · {t.rows_changed} changed ({t.cells_changed} cells) · {t.rows_added} added · {t.rows_removed} removed
        {t.columns_added.length > 0 && ` · new columns: ${t.columns_added.join(", ")}`}{t.columns_removed.length > 0 && ` · removed columns: ${t.columns_removed.join(", ")}`}</p>
      {t.numeric_shifts.length > 0 && <p className="text-sm">{t.numeric_shifts.map((s) => `${s.column}: ${s.total_change >= 0 ? "+" : ""}${s.total_change} in total`).join(" · ")}</p>}
      {t.changes.length > 0 && (
        <div className="table-wrap" style={{ maxHeight: 320 }}>
          <table className="table"><thead><tr><th>Change</th><th>Row</th><th>Details</th></tr></thead><tbody>
            {t.changes.slice(0, 200).map((c, i) => (
              <tr key={i}><td>{{ added_row: "Added", removed_row: "Removed", changed_row: "Changed" }[c.type]}</td><td className="mono">{c.key ?? ""}</td>
                <td>{c.type === "changed_row" ? c.cells!.map((x, j) => <div key={j}>{x.column}: <del>{x.old}</del> → <ins>{x.new}</ins></div>) : Object.entries(c.row ?? {}).map(([k, v]) => `${k}: ${v}`).join(" · ")}</td></tr>
            ))}</tbody></table>
        </div>
      )}
      {t.truncated && <p className="hint">Only the first changes are shown. Download the report for everything.</p>}
    </div>
  );
}

export function CompareView({ r, report }: { r: CompareResult; report?: FileRef }) {
  return (
    <div className="result">
      <div className="row" style={{ flexWrap: "wrap", gap: 16, alignItems: "center" }}>
        <div className="big">{Math.round(r.similarity * 100)}%<span className="hint"> similar</span></div>
        <div style={{ flex: 1, minWidth: 200 }}><h3>{r.identical ? "The two files have the same content." : r.headline}</h3>
          <p className="hint">{r.a.name} ↔ {r.b.name}{r.words ? ` · ${r.words.a} vs ${r.words.b} words` : ""}</p></div>
        {report && <DownloadLink file={report} label="Download report" />}
      </div>
      {r.warnings.map((w, i) => <p key={i} className="hint warn">Note: {w}</p>)}
      {r.diff && <TextDiff items={r.diff.items} />}
      {r.tables?.map((t, i) => <TableDiffView key={i} t={t} />)}
      {(r.sheets_only_in_a?.length ?? 0) > 0 && <p className="hint">Only in the first file: {r.sheets_only_in_a!.join(", ")}</p>}
      {(r.sheets_only_in_b?.length ?? 0) > 0 && <p className="hint">Only in the second file: {r.sheets_only_in_b!.join(", ")}</p>}
    </div>
  );
}

function Histogram({ c }: { c: Column }) {
  const h = c.histogram ?? [];
  const max = Math.max(1, ...h.map((b) => b.count));
  return (
    <div className="hist" role="img" aria-label={`Distribution of ${c.name}`}>
      {h.map((b, i) => <div key={i} className="hist-col" title={`${b.from} to ${b.to}: ${b.count}`}><span style={{ height: `${(b.count / max) * 100}%` }} /></div>)}
    </div>
  );
}

function ColumnCard({ c }: { c: Column }) {
  return (
    <div className="card col">
      <div className="row"><h3 className="truncate" style={{ flex: 1 }}>{c.name}</h3><span className="badge">{c.type}</span></div>
      <p className="hint">{c.count - c.missing} values{c.missing ? ` · ${c.missing} missing (${c.missing_pct}%)` : ""}{c.unique != null ? ` · ${c.unique} unique` : ""}</p>
      {c.type === "number" && <>
        <Histogram c={c} />
        <dl className="stats"><div><dt>Min</dt><dd>{c.min}</dd></div><div><dt>Median</dt><dd>{c.median}</dd></div><div><dt>Mean</dt><dd>{c.mean}</dd></div><div><dt>Max</dt><dd>{c.max}</dd></div></dl>
        {!!c.outliers && <p className="hint">{c.outliers} unusual value(s)</p>}</>}
      {c.type === "date" && <><p className="text-sm">{c.min} → {c.max}</p>
        {c.by_month && <div className="hist">{c.by_month.map((b) => <div key={b.month} className="hist-col" title={`${b.month}: ${b.count}`}><span style={{ height: `${(b.count / Math.max(...c.by_month!.map((x) => x.count))) * 100}%` }} /></div>)}</div>}</>}
      {c.top && <div className="tops">{c.top.slice(0, 5).map((t) => (
        <div key={t.value} className="bar-row"><span className="text-sm truncate">{t.value}</span><div className="meter"><span style={{ width: `${t.pct}%` }} /></div><span className="text-sm num">{t.count}</span></div>))}</div>}
    </div>
  );
}

export function AnalyticsView({ r }: { r: AnalyticsResult }) {
  return (
    <div className="result">
      <h3>{r.headline}</h3>
      {r.warnings.map((w, i) => <p key={i} className="hint warn">Note: {w}</p>)}
      {r.tables.map((t, ti) => (
        <section key={ti} className="stack">
          {r.tables.length > 1 && <h2>{t.name}</h2>}
          <div className="insights">{t.insights.map((i, n) => (
            <div key={n} className={`insight insight--${i.kind}`}><span className="insight-k" aria-hidden="true">{{ warning: "!", finding: "★", info: "i" }[i.kind] ?? "i"}</span><span><span className="sr-only">{i.kind}: </span>{i.message}</span></div>))}</div>
          {t.correlations.length > 0 && <p className="text-sm muted">Related columns: {t.correlations.map((c) => `${c.a} ↔ ${c.b} (${c.r})`).join(" · ")}</p>}
          <div className="grid">{t.profiles.map((c) => <ColumnCard key={c.name} c={c} />)}</div>
          <h3>Preview</h3>
          <div className="table-wrap" style={{ maxHeight: 280 }}><table className="table"><thead><tr>{t.preview.columns.map((c, i) => <th key={i}>{c}</th>)}</tr></thead>
            <tbody>{t.preview.rows.map((row, i) => <tr key={i}>{row.map((c, j) => <td key={j}>{c}</td>)}</tr>)}</tbody></table></div>
        </section>
      ))}
      {r.text && (
        <section className="stack"><h3>Text statistics</h3>
          <dl className="stats"><div><dt>Words</dt><dd>{r.text.words.toLocaleString()}</dd></div><div><dt>Sentences</dt><dd>{r.text.sentences}</dd></div><div><dt>Reading time</dt><dd>{r.text.reading_minutes} min</dd></div><div><dt>Readability</dt><dd>{r.text.readability}</dd></div></dl>
          <div className="chips">{r.text.top_words.map((w) => <span className="badge" key={w.word}>{w.word} · {w.count}</span>)}</div>
          <p className="hint">Readability uses the Flesch scale (higher is easier; 60–70 is plain English).</p>
        </section>
      )}
    </div>
  );
}

export function ImageView({ file, prompt, width, height }: { file: FileRef; prompt: string; width: number; height: number }) {
  return (
    <figure className="image-card">
      <img src={fileUrl(file.id, true)} alt={prompt} width={width} height={height} />
      <figcaption className="row"><span className="hint truncate" style={{ flex: 1 }}>{prompt}</span><DownloadLink file={file} label="Save PNG" /></figcaption>
    </figure>
  );
}

export function RenderCard({ card, onPickTheme }: { card: Card; onPickTheme?: (id: string) => void }) {
  switch (card.type) {
    case "file": return <FileCard card={card} />;
    case "markdown": return <details className="card"><summary>Show the content that was used</summary><Markdown text={card.text} /></details>;
    case "ats": return <div className="card"><AtsView r={card.result} /></div>;
    case "compare": return <div className="card"><CompareView r={card.result} report={card.report} /></div>;
    case "analytics": return <div className="card"><AnalyticsView r={card.result} /></div>;
    case "image": return <ImageView file={card.file} prompt={card.prompt} width={card.width} height={card.height} />;
    case "themes": return <div className="tiles">{card.themes.map((t) => <ThemeTile key={t.id} t={t} onPick={onPickTheme} />)}</div>;
    case "error": return null;
  }
}
