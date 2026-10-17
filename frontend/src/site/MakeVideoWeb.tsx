import { useEffect, useState } from "react";
import { mediaUrl } from "../lib/api";
import { fmtDuration } from "../lib/format";
import { useApp } from "../lib/store";
import { Button, Slider, Tabs, I } from "../ds";
import MediaSlot from "../views/MediaSlot";
import { saveAs } from "../lib/save";
import { webCall } from "../web/backend";
import QuotaMeter from "../web/QuotaMeter";
import { loadHF } from "../web/hf";
import type { Job } from "../lib/types";
import type { Asset } from "../lib/types";

type Mode = "t2v" | "i2v" | "extend";
const ASPECTS = [{ id: "16:9", sub: "YouTube" }, { id: "9:16", sub: "Shorts · Reels" }, { id: "1:1", sub: "Square" }, { id: "4:5", sub: "Feed" }];

/** Text to video, picture to video and "continue this clip", made on a free Hugging Face GPU. */
export default function MakeVideoWeb({ goLibrary, goSettings, goEditor }: { goLibrary: () => void; goSettings: () => void; goEditor: (a: Asset) => void }) {
  const { jobs, watchJob, toast, asset } = useApp();
  const [mode, setMode] = useState<Mode>("t2v");
  const [prompt, setPrompt] = useState("");
  const [negative, setNegative] = useState("");
  const [aspect, setAspect] = useState("16:9");
  const [quality, setQuality] = useState<"fast" | "good">("fast");
  const [seconds, setSeconds] = useState(3);
  const [seed, setSeed] = useState("");
  const [imageId, setImageId] = useState<string | null>(null);
  const [sourceId, setSourceId] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [resultId, setResultId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [more, setMore] = useState(false);
  const [hasToken, setHasToken] = useState(() => !!loadHF().token);
  useEffect(() => { const on = () => setHasToken(!!loadHF().token); window.addEventListener("vk-hf", on); return () => window.removeEventListener("vk-hf", on); }, []);

  const job: Job | null = jobs.find((j) => j.id === jobId) ?? null;
  const active = !!job && (job.status === "queued" || job.status === "running");
  const result = resultId ? asset(resultId) : undefined;
  const missing = mode === "i2v" && !imageId ? "Pick a starting picture." : mode === "extend" && !sourceId ? "Pick the clip to continue." : mode !== "i2v" && !prompt.trim() ? "Describe what should happen." : null;

  const go = async () => {
    if (missing) return;
    setBusy(true); setResultId(null);
    try {
      const j = await webCall("POST", "/web/video", { mode, prompt, negative, aspect, quality, seconds, seed: seed.trim() === "" ? null : Number(seed), image_asset_id: imageId, source_asset_id: sourceId }) as Job;
      setJobId(j.id);
      watchJob(j, (d) => { if (d.status === "done" && d.result?.asset_id) setResultId(d.result.asset_id as string); });
    } catch (e) { toast((e as Error).message, true); } finally { setBusy(false); }
  };
  const cancel = () => { if (job) void webCall("POST", `/jobs/${job.id}/cancel`).catch(() => undefined); };

  return (
    <main className="page gen">
      <div className="gen-head row between gap wrap">
        <div className="stack"><h1>Make a video</h1><p className="text-sm muted">Runs on a free GPU from Hugging Face · nothing to install · your pictures are sent only to that Space</p></div>
        <Tabs label="What to start from" value={mode} onChange={(m) => { setMode(m); setResultId(null); }} options={[{ id: "t2v", label: "Text" }, { id: "i2v", label: "Picture" }, { id: "extend", label: "Continue" }]} />
      </div>

      {!hasToken && (
        <div className="notice" role="note"><span>No Hugging Face token yet: you get a smaller free GPU allowance. A free account gives more, and it renews every day. </span><button type="button" className="linklike" onClick={goSettings}>Add a free token</button></div>
      )}

      <section className="gen-stage" aria-label="Result" aria-live="polite">
        {active && job ? (
          <div className="run card stack gap-lg" role="status">
            <div className="row between gap"><div className="stack"><span className="w-medium">Creating your video</span><span className="text-sm run-sub">{aspect} · {seconds} s · {quality === "good" ? "better quality" : "fast"}</span></div>
              <Button variant="secondary" small onClick={cancel}>Cancel</Button></div>
            <div className="bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(job.progress * 100)} aria-label="Video progress"><i className={job.progress < 0.04 ? "indet" : ""} style={{ width: `${Math.max(job.progress * 100, job.progress < 0.04 ? 30 : 2)}%` }} /></div>
            <p className="text-sm">{job.phase || "Working…"} · {fmtDuration(job.elapsed)}</p>
            <p className="text-xs run-sub">Free GPUs are shared, so you may wait in a queue. Keep this tab open.</p>
          </div>
        ) : result ? (
          <div className="stack gap">
            <video className="player" src={mediaUrl(result.id)} controls autoPlay loop playsInline />
            <div className="row between gap wrap">
              <span className="text-sm">{result.width}×{result.height} · {fmtDuration(result.duration)}{result.meta?.seed != null ? ` · seed ${String(result.meta.seed)}` : ""}</span>
              <div className="row gap wrap">
                <Button small onClick={() => goEditor(result)}>Edit this video</Button>
                <Button variant="secondary" small onClick={() => { setMode("extend"); setSourceId(result.id); setResultId(null); }}>Continue this clip</Button>
                <Button variant="secondary" small onClick={() => void saveAs(mediaUrl(result.id, "download"), `${result.name.replace(/\.[^.]+$/, "")}.mp4`)}>Save as…</Button>
                <Button variant="ghost" small onClick={goLibrary}>Open library</Button>
              </div>
            </div>
          </div>
        ) : (
          <div className="empty gen-empty"><svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d={I.film} /></svg><h3>What will you create?</h3><p className="text-sm">Describe a scene below. Finished videos are saved in your Library and in your history.</p></div>
        )}
        {job?.status === "error" && <p className="error-text" role="alert">{job.error}</p>}
      </section>

      <section className="composer" aria-label="Video settings">
        {mode === "i2v" && <div className="slots"><MediaSlot kind="image" value={imageId} onChange={setImageId} label="Start picture" hint="The first frame of the video" compact /></div>}
        {mode === "extend" && <div className="slots"><MediaSlot kind="video" value={sourceId} onChange={setSourceId} label="Clip to continue" hint="Its last picture starts the new clip" compact /></div>}
        <label className="sr-only" htmlFor="prompt">What should happen?</label>
        <textarea id="prompt" className="composer-text" rows={3} value={prompt} maxLength={2000} onChange={(e) => setPrompt(e.target.value)}
          placeholder={mode === "t2v" ? "A lighthouse on a cliff at dawn, waves rolling in, the camera slowly pushes forward." : mode === "i2v" ? "Describe the movement: the woman turns and smiles, wind moves her hair." : "What happens next? The boat drifts toward the shore as the sun sets."} />
        <div className="composer-bar">
          <div className="gchips" role="radiogroup" aria-label="Video shape">
            {ASPECTS.map((a) => <button key={a.id} type="button" role="radio" aria-checked={aspect === a.id} className={`gchip${aspect === a.id ? " gchip--on" : ""}`} onClick={() => setAspect(a.id)} title={a.sub}><span>{a.id}</span><small>{a.sub}</small></button>)}
          </div>
          <div className="gchips" role="radiogroup" aria-label="Quality">
            <button type="button" role="radio" aria-checked={quality === "fast"} className={`gchip${quality === "fast" ? " gchip--on" : ""}`} onClick={() => setQuality("fast")} title="Smaller picture, quicker, uses less free GPU time"><span>Fast</span><small>saves GPU time</small></button>
            <button type="button" role="radio" aria-checked={quality === "good"} className={`gchip${quality === "good" ? " gchip--on" : ""}`} onClick={() => setQuality("good")} title="Bigger and sharper, uses more free GPU time"><span>Better</span><small>sharper</small></button>
          </div>
          <button type="button" className="gchip" aria-expanded={more} onClick={() => setMore(!more)}><span>{seconds} s</span><small>Options ▾</small></button>
          <span className="grow" />
          <Button icon={I.sparkle} busy={busy} disabled={!!missing || active} onClick={go}>{active ? "Generating…" : "Generate"}</Button>
        </div>
        {missing && <div className="why row gap wrap" role="status"><span>{missing}</span></div>}
        {more && (
          <div className="pop stack gap">
            <Slider label="Length" value={seconds} min={1} max={8} step={1} onChange={setSeconds} format={(v) => `${v} s`} />
            <label className="field"><span>Avoid (optional)</span><input className="input" value={negative} onChange={(e) => setNegative(e.target.value)} placeholder="blurry, distorted, text, watermark" /></label>
            <label className="field"><span>Seed (empty = new result each time)</span><input className="input" inputMode="numeric" value={seed} onChange={(e) => setSeed(e.target.value.replace(/\D/g, ""))} placeholder="Random" /></label>
            <p className="hint">Longer and sharper videos use more of your free GPU time. Add voice, music and sound effects afterwards in the Editor (38 free sounds).</p>
          </div>
        )}
      </section>

      <section className="card stack gap" aria-label="Free GPU time">
        <div className="row between gap wrap"><b className="text-sm">Free GPU time (this browser’s estimate)</b><button type="button" className="linklike text-sm" onClick={goSettings}>AI settings</button></div>
        <QuotaMeter provider="zerogpu" />
        <p className="text-xs muted">Hugging Face gives a free account about 5 minutes of GPU time a day (2 minutes with no account) and renews it about 24 hours after you first used it. The real number is kept by Hugging Face.</p>
      </section>
    </main>
  );
}
