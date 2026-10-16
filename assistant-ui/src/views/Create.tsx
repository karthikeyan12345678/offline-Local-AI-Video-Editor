import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import type { FileRef, ThemeInfo } from "../lib/types";
import { ThemeTile, FileCard } from "../cards";
import { Banner, Button, useAsync } from "../ui";

const FORMATS = [
  { id: "pdf", label: "PDF", sample: "# Project status report\n\n## Summary\n\nThe project is on track. Key milestones were met this month.\n\n## Highlights\n\n- Beta released to 50 users\n- Cost is 4% under budget\n\n## Risks\n\n| Risk | Owner | Status |\n| --- | --- | --- |\n| Vendor delay | Priya | Watching |\n| Staffing | Arun | Mitigated |\n" },
  { id: "pptx", label: "PowerPoint", sample: "# Q3 review\nTeam update\n\n## Where we are\n- Revenue up 12%\n- Two launches shipped\nNotes: Open with the revenue number.\n\n## What is next\n- Hire 3 engineers\n- Start the pilot\n- Review budget in October\n" },
  { id: "docx", label: "Word", sample: "# Meeting notes\n\n## Decisions\n\n1. Launch on 14 March\n2. Freeze scope on 1 March\n\n## Actions\n\n| Action | Owner | Due |\n| --- | --- | --- |\n| Draft launch email | Meera | 5 Mar |\n" },
  { id: "csv", label: "CSV", sample: "| name | team | score |\n| --- | --- | --- |\n| Asha | Data | 91 |\n| Ravi | Cloud | 84 |\n| Meena | Design | 88 |\n" },
  { id: "xlsx", label: "Excel", sample: "## Sales\n\n| month | units | revenue |\n| --- | --- | --- |\n| Jan | 120 | 4500.5 |\n| Feb | 135 | 5120 |\n| Mar | 150 | 5800 |\n" },
] as const;

export default function Create() {
  const [fmt, setFmt] = useState<(typeof FORMATS)[number]["id"]>("pdf");
  const [md, setMd] = useState<string>(FORMATS[0].sample);
  const [title, setTitle] = useState("");
  const [purpose, setPurpose] = useState("");
  const [theme, setTheme] = useState<string>("");
  const [all, setAll] = useState<ThemeInfo[]>([]);
  const [reco, setReco] = useState<ThemeInfo[]>([]);
  const [filter, setFilter] = useState("");
  const [loadErr, setLoadErr] = useState("");
  const run = useAsync<{ file: FileRef; warnings: string[]; theme: { id: string; name: string; colors: Record<string, string>; reasons: string[] } }>();

  useEffect(() => { api.themes().then((r) => setAll(r.themes)).catch((e) => setLoadErr(String(e.message ?? e))); }, []);
  useEffect(() => {
    if (!purpose.trim()) { setReco([]); return; }
    const t = setTimeout(() => { api.themes(purpose, fmt).then((r) => setReco(r.recommended)).catch(() => setReco([])); }, 350);
    return () => clearTimeout(t);
  }, [purpose, fmt]);

  const shown = useMemo(() => all.filter((t) => !filter || (t.name + " " + t.category).toLowerCase().includes(filter.toLowerCase())).slice(0, 60), [all, filter]);
  const sample = FORMATS.find((f) => f.id === fmt)!.sample;

  return (
    <div className="page">
      <header><h1>Create a file</h1><p className="muted">Write or paste your content in simple Markdown, pick a design, and download a finished file. To have the AI write the content for you, use the chat (for example “/ppt a pitch for a bakery”).</p></header>
      {loadErr && <Banner kind="error">{loadErr}</Banner>}
      <div className="field"><span className="label">File type</span>
        <div className="chips" role="group" aria-label="File type">{FORMATS.map((f) => (
          <button key={f.id} className="chip" aria-pressed={fmt === f.id} onClick={() => { if (md.trim() === "" || FORMATS.some((x) => x.sample === md)) setMd(f.sample); setFmt(f.id); run.reset(); }}>{f.label}</button>))}</div></div>
      <div className="two">
        <div className="field"><label htmlFor="md">Content (Markdown)</label>
          <textarea id="md" className="textarea mono" style={{ minHeight: 320 }} value={md} onChange={(e) => setMd(e.target.value)} spellCheck={false} />
          <span className="hint">Use # for the title, ## for sections or slides, - for bullets and | tables |. {fmt === "csv" || fmt === "xlsx" ? "Tables become rows and columns." : ""}
            <button className="link" onClick={() => setMd(sample)}>Insert an example</button></span></div>
        <div className="stack">
          <div className="field"><label htmlFor="title">File name (optional)</label><input id="title" className="input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Taken from the title" /></div>
          <div className="field"><label htmlFor="purpose">What is it for? (picks a design for you)</label>
            <input id="purpose" className="input" value={purpose} onChange={(e) => setPurpose(e.target.value)} placeholder="e.g. investor pitch for a fintech startup" /></div>
          {reco.length > 0 && <div className="field"><span className="label">Best matches</span><div className="tiles tiles--tight">{reco.slice(0, 4).map((t) => <ThemeTile key={t.id} t={t} selected={theme === t.id} onPick={setTheme} />)}</div></div>}
          <div className="field"><label htmlFor="tf">All designs ({all.length}) {theme && <>· chosen: <strong>{all.find((t) => t.id === theme)?.name}</strong> <button className="link" onClick={() => setTheme("")}>use automatic</button></>}</label>
            <input id="tf" className="input" placeholder="Search designs, e.g. dark, finance, editorial" value={filter} onChange={(e) => setFilter(e.target.value)} /></div>
        </div>
      </div>
      <div className="tiles tiles--scroll">{shown.map((t) => <ThemeTile key={t.id} t={t} selected={theme === t.id} onPick={setTheme} />)}</div>
      <div className="row">
        <Button busy={run.busy} disabled={!md.trim()} onClick={() => void run.run(() => api.create({ format: fmt, markdown: md, title, theme: theme || null, purpose }))}>Create {FORMATS.find((f) => f.id === fmt)!.label} file</Button>
      </div>
      {run.error && <Banner kind="error">{run.error}</Banner>}
      {run.data && <FileCard card={{ type: "file", file: run.data.file, note: "", warnings: run.data.warnings, theme: run.data.theme }} />}
    </div>
  );
}
