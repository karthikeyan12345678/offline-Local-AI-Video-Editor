import { useEffect, useMemo, useState } from "react";
import { api, mediaUrl, type SoundOptions } from "../lib/api";
import { fmtDuration } from "../lib/format";
import { useApp } from "../lib/store";
import { Button, Field, Slider, Tabs, I } from "../ds";
import { AssetPicker } from "./shared";

type Mode = "t2v" | "i2v" | "extend";

export default function Generate({ goLibrary, goSettings }: { goLibrary: () => void; goSettings: () => void }) {
  const { limits, settings, system, jobs, watchJob, toast, models, asset } = useApp();
  const [mode, setMode] = useState<Mode>("t2v");
  const [prompt, setPrompt] = useState("");
  const [negative, setNegative] = useState("");
  const [resIdx, setResIdx] = useState(0);
  const [aspect, setAspect] = useState<"16:9" | "9:16" | "1:1" | "4:5">("16:9");
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [now, setNow] = useState(Date.now());
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
  const [soundOn, setSoundOn] = useState(true);
  const [narration, setNarration] = useState("");
  const [voice, setVoice] = useState("");
  const [voices, setVoices] = useState<string[]>([]);
  const [ambience, setAmbience] = useState("auto");
  const [ambs, setAmbs] = useState<{ id: string; label: string }[]>([]);
  const [music, setMusic] = useState(false);
  const [level, setLevel] = useState(0.5);
  useEffect(() => { api.voices().then((v) => setVoices(v.voices)).catch(() => {}); api.ambiences().then((a) => setAmbs(a.ambiences)).catch(() => {}); }, []);

  const model = useMemo(() => limits?.models.find((m) => m.id === (modelId ?? limits.default_model)), [limits, modelId]);
  if (!limits || !settings || !system) return null;
  const prof = limits.profile;
  const res = prof.resolutions[Math.min(resIdx, prof.resolutions.length - 1)];
  const r32 = (n: number) => Math.max(64, Math.round(n / 32) * 32);
  const short = Math.min(res.width, res.height), long = Math.max(res.width, res.height);
  const [width, height] = aspect === "16:9" ? [long, short] : aspect === "9:16" ? [short, long] : aspect === "1:1" ? [short, short] : [r32(short * 0.8), short];
  const nFrames = unlock ? (frames ?? prof.default_frames) : Math.min(frames ?? prof.default_frames, prof.max_frames);
  const fps = limits.fps;
  const installed = models.some((m) => m.id === model?.id && m.installed);
  const baseOk = models.some((m) => m.kind === "base" && m.installed);
  const modelsReady = !system.requires_models || (installed && baseOk);
  const job = jobs.find((j) => j.id === jobId) ?? null;
  const active = !!job && (job.status === "queued" || job.status === "running");
  const result = resultId ? asset(resultId) : undefined;

  const dl = models.filter((m) => (m.id === model?.id || m.kind === "base") && !m.installed);
  const dlTotal = dl.reduce((a, m) => a + (m.download.total || 0), 0), dlDone = dl.reduce((a, m) => a + (m.download.done || 0), 0);
  const downloading = dl.some((m) => m.download.status === "downloading" || m.download.status === "running");
  const dlPct = dlTotal > 0 ? Math.floor((dlDone / dlTotal) * 100) : 0;
  const blocked = !modelsReady ? (downloading ? `Models are downloading (${dlPct}%). Generate unlocks when they finish.` : "Models are not installed yet. Download them first, then Generate unlocks.") : null;

  useEffect(() => { if (!active) return; const t = setInterval(() => setNow(Date.now()), 500); return () => clearInterval(t); }, [active]);

  const missing = mode === "i2v" && !imageId ? "Pick a starting picture below." : mode === "extend" && !sourceId ? "Pick the clip to continue below." : !prompt.trim() ? "Describe what should happen." : null;

  const submit = async () => {
    if (missing || !model) return;
    setSubmitting(true); setResultId(null); setStartedAt(Date.now()); setNow(Date.now());
    const body = {
      prompt: prompt.trim(), negative_prompt: negative.trim(), width, height, frames: nFrames, seed: seed.trim() === "" ? -1 : Number(seed),
      sound: soundOn ? ({ narration: narration.trim(), voice, rate: 0, ambience, music, level } as SoundOptions) : undefined,
      model_id: model.id, steps: model.distilled ? undefined : (steps ?? model.default_steps), guidance: model.distilled ? undefined : (guidance ?? model.default_guidance), unlock_limits: unlock,
    };
    try {
      const j = mode === "extend"
        ? await api.extend({ ...body, mode: "i2v", source_asset_id: sourceId! })
        : await api.generate({ ...body, mode: mode === "i2v" ? "i2v" : "t2v", image_asset_id: mode === "i2v" ? imageId ?? undefined : undefined });
      setJobId(j.id);
      watchJob(j, (done) => { if (done.status === "done" && done.result?.asset_id) setResultId(done.result.asset_id); const w = done.result?.warnings as string[] | undefined; if (w?.length) toast(w[0], true); });
    } catch (e) { toast((e as Error).message, true); } finally { setSubmitting(false); }
  };

  const elapsed = startedAt ? Math.max(job?.elapsed ?? 0, (now - startedAt) / 1000) : 0;
  const phase = (job?.phase || "").toLowerCase();
  const last = soundOn ? 4 : 3;
  const stage = !job || job.status === "queued" ? 0 : /librar|sav|writ/.test(phase) && job.progress >= 0.98 ? last : soundOn && /sound|voice|record|background/.test(phase) ? 3 : job.progress >= 0.95 && !soundOn ? last : /load|prepar|download/.test(phase) || job.progress === 0 ? 1 : 2;
  const STAGES = soundOn ? ["Queued", "Loading models", "Generating", "Sound & voice", "Saving"] : ["Queued", "Loading models", "Generating", "Saving"];
  const ASPECTS: { id: typeof aspect; label: string; sub: string }[] = [{ id: "16:9", label: "16:9", sub: "YouTube" }, { id: "9:16", label: "9:16", sub: "Shorts · Reels" }, { id: "1:1", label: "1:1", sub: "Square" }, { id: "4:5", label: "4:5", sub: "Feed" }];

  return (
    <main className="page gen">
      <div className="gen-head row between gap wrap">
        <div className="stack"><h1>Make a video</h1><p className="text-sm">{system.gpu.available ? `${system.gpu.name} · ${system.gpu.vram_gb} GB` : "Running on this PC"} · {prof.label} settings</p></div>
        <Tabs label="What to start from" value={mode} onChange={(m) => { setMode(m); setResultId(null); }} options={[{ id: "t2v", label: "Text" }, { id: "i2v", label: "Picture" }, { id: "extend", label: "Continue" }]} />
      </div>

      {system.torch && !system.gpu.available && (
        <div className="notice" role="note"><span>Your graphics card is not switched on, so videos are small and slow. </span><button type="button" className="linklike" onClick={goSettings}>Open Settings to fix it</button></div>
      )}

      <section className="gen-stage" aria-label="Result" aria-live="polite">
        {active && job ? (
          <div className="run card stack gap-lg">
            <div className="row between gap"><div className="stack"><span className="w-medium">Creating your video</span><span className="text-sm run-sub">{width}×{height} · {(nFrames / fps).toFixed(1)} s · {aspect}</span></div>
              <Button variant="secondary" small onClick={() => api.cancelJob(job.id).catch((e) => toast(e.message, true))}>Cancel</Button></div>
            <div className="run-timer"><span className="mono run-clock">{fmtDuration(elapsed)}</span><span className="text-sm">elapsed{job.eta != null ? ` · about ${fmtDuration(job.eta)} left` : " · estimating time…"}</span></div>
            <div className="bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(job.progress * 100)} aria-label="Video progress"><i className={job.progress === 0 ? "indet" : ""} style={{ width: `${Math.max(job.progress * 100, job.progress === 0 ? 30 : 2)}%` }} /></div>
            <ol className="flow" aria-label="Steps">{STAGES.map((n, i) => <li key={n} className={i < stage ? "done" : i === stage ? "now" : ""}><b>{i < stage ? "✓" : i + 1}</b><span>{n}</span></li>)}</ol>
            <p className="text-xs run-sub">{job.phase || "Working…"} · {Math.round(job.progress * 100)}%{!system.gpu.available ? " · On the processor this is slow; the first run also loads the model." : ""}</p>
          </div>
        ) : result ? (
          <div className="stack gap">
            <video className="player" src={mediaUrl(result.id)} controls autoPlay loop playsInline />
            <div className="row between gap wrap">
              <span className="text-sm">{result.width}×{result.height} · {fmtDuration(result.duration)} · seed {String(result.meta.seed ?? "?")}</span>
              <div className="row gap wrap">
                <Button variant="secondary" small onClick={() => { setMode("extend"); setSourceId(result.id); setResultId(null); }}>Continue this clip</Button>
                <a className="btn btn--secondary btn--sm" href={mediaUrl(result.id, "download")} download>Save a copy</a>
                <Button variant="ghost" small onClick={goLibrary}>Open library</Button>
              </div>
            </div>
          </div>
        ) : (
          <div className="empty gen-empty"><svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d={I.film} /></svg><h3>What will you create?</h3><p className="text-sm">Describe a scene below. Finished videos are saved in your Library.</p></div>
        )}
        {job?.status === "error" && <p className="error-text" role="alert">{job.error}</p>}
      </section>

      <section className="composer" aria-label="Video settings">
        {mode === "i2v" && <Field label="Starting picture"><AssetPicker kind="image" value={imageId} onChange={setImageId} label="Starting picture" /></Field>}
        {mode === "extend" && <Field label="Clip to continue" hint="Its last frame becomes the first frame of the new clip."><AssetPicker kind="video" value={sourceId} onChange={setSourceId} label="Clip to continue" /></Field>}
        <label className="sr-only" htmlFor="prompt">{mode === "t2v" ? "What should the video show?" : "What should happen?"}</label>
        <textarea id="prompt" className="composer-text" rows={3} value={prompt} maxLength={4000} onChange={(e) => setPrompt(e.target.value)} placeholder="A lighthouse on a cliff at dawn, waves rolling in, the camera slowly pushes forward." />
        <div className="composer-bar">
          <div className="gchips" role="radiogroup" aria-label="Video shape">
            {ASPECTS.map((a) => <button key={a.id} type="button" role="radio" aria-checked={aspect === a.id} className={`gchip${aspect === a.id ? " gchip--on" : ""}`} onClick={() => setAspect(a.id)} title={a.sub}><span>{a.label}</span><small>{a.sub}</small></button>)}
          </div>
          <button type="button" className={`gchip${soundOn ? " gchip--on" : ""}`} aria-pressed={soundOn} onClick={() => setSoundOn(!soundOn)} title="Add a voice and background sound to the new video"><span>{soundOn ? "Sound on" : "Sound off"}</span><small>Voice · ambience</small></button>
          <button type="button" className="gchip" aria-expanded={showAdvanced} onClick={() => setShowAdvanced(!showAdvanced)}><span>{width}×{height} · {(nFrames / fps).toFixed(1)} s</span><small>Options ▾</small></button>
          <span className="grow" />
          <Button icon={I.sparkle} busy={submitting} disabled={!!missing || active || !modelsReady} onClick={submit}>{active ? "Generating…" : "Generate"}</Button>
        </div>
        {(blocked || missing) && (
          <div className="why row gap wrap" role="status">
            <span className={blocked ? "why-block" : ""}>{blocked ?? missing}</span>
            {blocked && <Button variant="secondary" small onClick={goSettings}>{downloading ? "See downloads" : "Download models"}</Button>}
            {blocked && downloading && <div className="bar bar--thin" aria-hidden="true"><i style={{ width: `${dlPct}%` }} /></div>}
          </div>
        )}
        {soundOn && (
          <div className="pop stack gap" aria-label="Sound and voice">
            <div className="row gap wrap center-v"><b className="text-sm">Sound &amp; voice</b><span className="text-xs run-sub">Made on this PC and mixed into the video when it finishes.</span></div>
            <Field label="Voice-over (optional)" htmlFor="narr" hint="Words a voice speaks over the video. Keep it short enough for the length of the clip.">
              <textarea id="narr" className="input" rows={2} maxLength={3000} value={narration} onChange={(e) => setNarration(e.target.value)} placeholder="The lighthouse stands alone as the morning sun rises over the sea." />
            </Field>
            <div className="grid-2">
              <Field label="Voice" htmlFor="voice"><select id="voice" className="select" value={voice} onChange={(e) => setVoice(e.target.value)} disabled={!narration.trim() || voices.length === 0}><option value="">{voices.length ? "Default voice" : "No voice found on this PC"}</option>{voices.map((v) => <option key={v} value={v}>{v}</option>)}</select></Field>
              <Field label="Background sound" htmlFor="amb"><select id="amb" className="select" value={ambience} onChange={(e) => setAmbience(e.target.value)}><option value="auto">Automatic (matches your prompt)</option>{ambs.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}</select></Field>
            </div>
            <div className="row gap wrap center-v">
              <label className="check"><input type="checkbox" checked={music} onChange={(e) => setMusic(e.target.checked)} />Add soft music</label>
              <Slider label="Sound volume" value={Math.round(level * 100)} min={0} max={100} step={5} onChange={(v) => setLevel(v / 100)} format={(v) => `${v}%`} />
            </div>
          </div>
        )}
        {showAdvanced && (
          <div className="pop stack gap">
            <div className="grid-2">
              <Field label="Quality size" htmlFor="res">
                <select id="res" className="select" value={resIdx} onChange={(e) => setResIdx(Number(e.target.value))}>
                  {prof.resolutions.map((r, i) => <option key={r.label} value={i}>{r.label}</option>)}
                </select>
              </Field>
              <Slider label="Length" value={nFrames} min={9} max={unlock ? 257 : prof.max_frames} step={8} onChange={setFrames} format={(f) => `${(f / fps).toFixed(1)} s`} />
            </div>
            <Field label="Avoid (optional)" htmlFor="neg"><input id="neg" className="input" value={negative} onChange={(e) => setNegative(e.target.value)} placeholder="blurry, distorted, text, watermark" disabled={!!model?.distilled} /></Field>
            {model?.distilled && <p className="hint">The fast model ignores “avoid” text.</p>}
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
            <Field label="Seed" htmlFor="seed" hint="Empty = new result each time."><input id="seed" className="input" inputMode="numeric" value={seed} onChange={(e) => setSeed(e.target.value.replace(/\D/g, ""))} placeholder="Random" /></Field>
            <label className="check"><input type="checkbox" checked={unlock} onChange={(e) => setUnlock(e.target.checked)} />Allow sizes and lengths beyond what this PC can handle</label>
          </div>
        )}
      </section>
    </main>
  );
}
