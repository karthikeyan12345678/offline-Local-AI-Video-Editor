import { IS_WEB } from "../lib/env";
import { useState } from "react";
import { api } from "../lib/api";
import type { AnalyticsResult, AtsResult, FileRef } from "../lib/types";
import { AnalyticsView, AtsView, CompareView, ImageView } from "../cards";
import { Banner, Button, FilePicker, TimedProgress, useAsync } from "../ui";
import type { CompareResult } from "../lib/types";

const RESUME_TYPES = ".pdf,.docx,.txt,.md";

export function Resume() {
  const [files, setFiles] = useState<FileRef[]>([]);
  const [jd, setJd] = useState("");
  const run = useAsync<AtsResult>();
  return (
    <div className="page">
      <header><h1>Resume ATS check</h1><p className="muted">See how well an applicant tracking system can read your resume, and how closely it matches a job description. The score is an estimate from common checks, not any company’s real system.</p></header>
      <div className="two">
        <FilePicker label="Your resume" files={files} onChange={(f) => { setFiles(f); run.reset(); }} accept={RESUME_TYPES} hint="PDF, Word (.docx) or text. A text-based PDF works best." />
        <div className="field"><label htmlFor="jd">Job description (recommended)</label>
          <textarea id="jd" className="textarea" style={{ minHeight: 160 }} value={jd} onChange={(e) => setJd(e.target.value)} placeholder="Paste the job posting here to see which of its keywords your resume is missing." /></div>
      </div>
      <div className="row"><Button busy={run.busy} disabled={!files.length} onClick={() => void run.run(() => api.ats(files[0].id, jd))}>Check my resume</Button></div>
      {run.error && <Banner kind="error">{run.error}</Banner>}
      {run.data && <div className="card"><AtsView r={run.data} /></div>}
    </div>
  );
}

export function Compare() {
  const [a, setA] = useState<FileRef[]>([]);
  const [b, setB] = useState<FileRef[]>([]);
  const run = useAsync<{ result: CompareResult; report: FileRef }>();
  return (
    <div className="page">
      <header><h1>Compare files</h1><p className="muted">Find what changed between two versions. Works with PDF, Word, PowerPoint, Excel, CSV and text, and you can compare different formats (for example a Word file against its PDF).</p></header>
      <div className="two">
        <FilePicker label="Original file" files={a} onChange={(f) => { setA(f); run.reset(); }} />
        <FilePicker label="New file" files={b} onChange={(f) => { setB(f); run.reset(); }} />
      </div>
      <div className="row"><Button busy={run.busy} disabled={!a.length || !b.length} onClick={() => void run.run(() => api.compare(a[0].id, b[0].id))}>Compare</Button></div>
      {run.error && <Banner kind="error">{run.error}</Banner>}
      {run.data && <div className="card"><CompareView r={run.data.result} report={run.data.report} /></div>}
    </div>
  );
}

export function Analyze() {
  const [files, setFiles] = useState<FileRef[]>([]);
  const run = useAsync<AnalyticsResult>();
  return (
    <div className="page">
      <header><h1>Analyse a file</h1><p className="muted">Upload a spreadsheet, CSV, document or PDF to get statistics, data-quality warnings and plain-language findings. Everything is calculated on {IS_WEB ? "this browser" : "this PC"}.</p></header>
      <FilePicker label="File to analyse" files={files} onChange={(f) => { setFiles(f); run.reset(); }} hint="CSV, Excel, Word, PDF, PowerPoint or text." />
      <div className="row"><Button busy={run.busy} disabled={!files.length} onClick={() => void run.run(() => api.analyze(files[0].id))}>Analyse</Button></div>
      {run.error && <Banner kind="error">{run.error}</Banner>}
      {run.data && <div className="card"><AnalyticsView r={run.data} /></div>}
    </div>
  );
}

const SHAPES = [{ id: "square", label: "Square" }, { id: "landscape", label: "Wide" }, { id: "portrait", label: "Tall" }];
const IDEAS = ["A calm mountain lake at sunrise, soft watercolor", "Minimal flat logo of a fox, orange and cream", "Isometric illustration of a tiny server room"];

export function ImageGen() {
  const [prompt, setPrompt] = useState("");
  const [shape, setShape] = useState("square");
  const [gallery, setGallery] = useState<{ file: FileRef; prompt: string; width: number; height: number }[]>([]);
  const run = useAsync<unknown>();
  const go = () => void run.run(async () => { const r = await api.image(prompt, shape); setGallery((g) => [r, ...g]); return r; });
  return (
    <div className="page">
      <header><h1>Generate images</h1><p className="muted">Describe the picture. The image engine is chosen in Settings (a free online service, your own API, or a model on {IS_WEB ? "the desktop app" : "this PC"}).</p></header>
      <div className="field"><label htmlFor="ip">Describe the image</label>
        <textarea id="ip" className="textarea" value={prompt} onChange={(e) => setPrompt(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && prompt.trim().length > 2) go(); }} placeholder="A lighthouse at sunset, oil painting" />
        <div className="chips">{IDEAS.map((i) => <button key={i} className="chip" onClick={() => setPrompt(i)}>{i}</button>)}</div></div>
      <div className="field"><span className="label">Shape</span><div className="chips" role="group" aria-label="Shape">{SHAPES.map((s) => <button key={s.id} className="chip" aria-pressed={shape === s.id} onClick={() => setShape(s.id)}>{s.label}</button>)}</div></div>
      <div className="row"><Button busy={run.busy} disabled={prompt.trim().length < 3} onClick={go}>{run.busy ? "Generating…" : "Generate"}</Button></div>
      <TimedProgress active={run.busy} tau={25} text="Making your picture…" label="Making your picture" />
      {run.error && <Banner kind="error">{run.error}</Banner>}
      <div className="gallery">{gallery.map((g) => <ImageView key={g.file.id} {...g} />)}</div>
    </div>
  );
}
