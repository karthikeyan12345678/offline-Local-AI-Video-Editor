import { useMemo, useState } from "react";
import { api, mediaUrl } from "../lib/api";
import { fmtDuration } from "../lib/format";
import { useApp } from "../lib/store";
import { Button, Field, Slider, Tabs, I } from "../ds";
import { AssetPicker, JobCard } from "./shared";

type Mode = "t2v" | "i2v" | "extend";

export default function Generate({ goLibrary, goSettings }: { goLibrary: () => void; goSettings: () => void }) {
  const { limits, settings, system, jobs, watchJob, toast, models, asset } = useApp();
  const [mode, setMode] = useState<Mode>("t2v");
  const [prompt, setPrompt] = useState("");
  const [negative, setNegative] = useState("");
  const [resIdx, setResIdx] = useState(0);
  const [portrait, setPortrait] = useState(false);
  const [frames, setFrames] = useState<number | null>(null);
  const [seed, setSeed] = useState("");
  const [modelId, setModelId] = useState<string | null>(null);
  const [steps, setSteps] = useState<number | null>(null);
  const [guidance, setGuidance] = useState<number | null>(null);
  const [unlock, setUnlock] = useState(false);
  const [imageId, setImageId] = useState<string | null>(null);
  const [sourceId, setSourceId] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [resultId, setResultId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);

  const model = useMemo(() => limits?.models.find((m) => m.id === (modelId ?? limits.default_model)), [limits, modelId]);
  if (!limits || !settings || !system) return null;
  const prof = limits.profile;
  const res = prof.resolutions[Math.min(resIdx, prof.resolutions.length - 1)];
  const width = portrait ? res.height : res.width;
  const height = portrait ? res.width : res.height;
  const nFrames = unlock ? (frames ?? prof.default_frames) : Math.min(frames ?? prof.default_frames, prof.max_frames);
  const fps = limits.fps;
  const installed = models.some((m) => m.id === model?.id && m.installed);
  const baseOk = models.some((m) => m.kind === "base" && m.installed);
  const modelsReady = !system.requires_models || (installed && baseOk);
  const job = jobs.find((j) => j.id === jobId) ?? null;
  const active = !!job && (job.status === "queued" || job.status === "running");
  const result = resultId ? asset(resultId) : undefined;

  const missing = mode === "i2v" && !imageId ? "Pick a starting picture below." : mode === "extend" && !sourceId ? "Pick the clip to continue below." : !prompt.trim() ? "Describe what should happen." : null;

  const submit = async () => {
    if (missing || !model) return;
    setSubmitting(true); setResultId(null);
    const body = {
      prompt: prompt.trim(), negative_prompt: negative.trim(), width, height, frames: nFrames, seed: seed.trim() === "" ? -1 : Number(seed),
      model_id: model.id, steps: model.distilled ? undefined : (steps ?? model.default_steps), guidance: model.distilled ? undefined : (guidance ?? model.default_guidance), unlock_limits: unlock,
    };
    try {
      const j = mode === "extend"
        ? await api.extend({ ...body, mode: "i2v", source_asset_id: sourceId! })
        : await api.generate({ ...body, mode: mode === "i2v" ? "i2v" : "t2v", image_asset_id: mode === "i2v" ? imageId ?? undefined : undefined });
      setJobId(j.id);
      watchJob(j, (done) => { if (done.status === "done" && done.result?.asset_id) setResultId(done.result.asset_id); });
    } catch (e) { toast((e as Error).message, true); } finally { setSubmitting(false); }
  };

  return (
    <main className="page two-col">
      <section className="stack gap-lg" aria-label="Video settings">
        <div className="stack"><h1>Make a video</h1><p className="text-sm">Using {prof.label} settings for {system.gpu.available ? `${system.gpu.name} (${system.gpu.vram_gb} GB)` : "this PC"}. {prof.description}</p></div>

        <Tabs label="What to start from" value={mode} onChange={(m) => { setMode(m); setResultId(null); }} options={[{ id: "t2v", label: "From text" }, { id: "i2v", label: "From a picture" }, { id: "extend", label: "Continue a clip" }]} />

        {mode === "i2v" && <Field label="Starting picture"><AssetPicker kind="image" value={imageId} onChange={setImageId} label="Starting picture" /></Field>}
        {mode === "extend" && <Field label="Clip to continue" hint="The last frame of this clip becomes the first frame of the new one. Add both to the Editor to join them."><AssetPicker kind="video" value={sourceId} onChange={setSourceId} label="Clip to continue" /></Field>}

        <Field label={mode === "t2v" ? "What should the video show?" : "What should happen?"} htmlFor="prompt" hint="Describe the subject, the motion and the light in 1–3 sentences. English works best.">
          <textarea id="prompt" className="textarea" rows={4} value={prompt} maxLength={4000} onChange={(e) => setPrompt(e.target.value)} placeholder="A lighthouse on a cliff at dawn, waves rolling in, the camera slowly pushes forward." />
        </Field>

        <div className="grid-2">
          <Field label="Size" htmlFor="res">
            <div className="row gap">
              <select id="res" className="select" value={resIdx} onChange={(e) => setResIdx(Number(e.target.value))}>
                {prof.resolutions.map((r, i) => <option key={r.label} value={i}>{r.label} · {portrait ? `${r.height}×${r.width}` : `${r.width}×${r.height}`}</option>)}
              </select>
              <Button variant="secondary" active={portrait} onClick={() => setPortrait(!portrait)} aria-pressed={portrait}>Tall</Button>
            </div>
          </Field>
          <Slider label="Length" value={nFrames} min={9} max={unlock ? 257 : prof.max_frames} step={8} onChange={setFrames} format={(f) => `${(f / fps).toFixed(1)} s · ${f} frames`} />
        </div>

        <button type="button" className="linklike" aria-expanded={showAdvanced} onClick={() => setShowAdvanced(!showAdvanced)}>{showAdvanced ? "Hide" : "Show"} advanced options</button>
        {showAdvanced && (
          <div className="card stack gap">
            <Field label="Avoid (optional)" htmlFor="neg"><input id="neg" className="input" value={negative} onChange={(e) => setNegative(e.target.value)} placeholder="blurry, distorted, text, watermark" disabled={!!model?.distilled} /></Field>
            {model?.distilled && <p className="hint">The fast model ignores “avoid” text. Switch to the standard model to use it.</p>}
            <Field label="Model" htmlFor="model">
              <select id="model" className="select" value={model?.id} onChange={(e) => setModelId(e.target.value)}>
                {limits.models.map((m) => <option key={m.id} value={m.id}>{m.label}{models.find((x) => x.id === m.id)?.installed ? "" : " (not installed)"}</option>)}
              </select>
            </Field>
            {model && !model.distilled && (
              <div className="grid-2">
                <Slider label="Quality steps" value={steps ?? model.default_steps} min={model.min_steps} max={model.max_steps} onChange={setSteps} />
                <Slider label="Follow the prompt" value={guidance ?? model.default_guidance} min={1} max={10} step={0.5} onChange={setGuidance} />
              </div>
            )}
            <Field label="Seed" htmlFor="seed" hint="Leave empty for a new result each time. Reuse a seed to repeat a result.">
              <input id="seed" className="input" inputMode="numeric" value={seed} onChange={(e) => setSeed(e.target.value.replace(/\D/g, ""))} placeholder="Random" />
            </Field>
            <label className="check"><input type="checkbox" checked={unlock} onChange={(e) => setUnlock(e.target.checked)} />Allow sizes and lengths beyond what this PC can handle (may run out of memory)</label>
          </div>
        )}

        <div className="stack">
          <div className="row gap wrap">
            <Button icon={I.sparkle} busy={submitting} disabled={!!missing || active || !modelsReady} onClick={submit}>{active ? "Generating…" : "Generate video"}</Button>
            {!modelsReady && <Button variant="secondary" onClick={goSettings}>Download models first</Button>}
          </div>
          {missing && <p className="hint">{missing}</p>}
          <p className="hint">First video on a 4 GB card can take several minutes while the model loads; later ones are faster. Estimated clip: {width}×{height}, {(nFrames / fps).toFixed(1)} s.</p>
        </div>
      </section>

      <aside className="stack gap" aria-label="Result">
        {job && <JobCard job={job} />}
        {result ? (
          <div className="card stack gap">
            <video className="player" src={mediaUrl(result.id)} controls autoPlay loop playsInline />
            <div className="row between gap wrap">
              <span className="text-sm">{result.width}×{result.height} · {fmtDuration(result.duration)} · seed {String(result.meta.seed ?? "?")}</span>
              <div className="row gap">
                <Button variant="secondary" small onClick={() => { setMode("extend"); setSourceId(result.id); setResultId(null); }}>Continue this clip</Button>
                <a className="btn btn--secondary btn--sm" href={mediaUrl(result.id, "download")} download>Save a copy</a>
                <Button variant="ghost" small onClick={goLibrary}>Open library</Button>
              </div>
            </div>
          </div>
        ) : !job && (
          <div className="empty"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d={I.film} /></svg><h3>Your video will appear here</h3><p className="text-sm">Finished videos are also saved in the Library.</p></div>
        )}
      </aside>
    </main>
  );
}
