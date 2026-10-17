import { useEffect, useMemo, useState } from "react";
import { api, mediaUrl, PERSONAS, type Persona, type SoundOptions } from "../lib/api";
import { fmtDuration } from "../lib/format";
import { useApp } from "../lib/store";
import { Button, Field, Slider, Tabs, I } from "../ds";
import MediaSlot from "./MediaSlot";
import { saveAs } from "../lib/save";
import Meters from "./Meters";
import type { Estimate } from "../lib/types";

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
  const [endId, setEndId] = useState<string | null>(null);
  const [soundOpen, setSoundOpen] = useState(false);
  const [mini, setMini] = useState(() => { try { return localStorage.getItem("vk_gen_mini") === "1"; } catch { return false; } });
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
  const [persona, setPersona] = useState<Persona>("auto");
  const [engine, setEngine] = useState<"ltx" | "omni">("ltx");
  const [level, setLevel] = useState(0.5);
  useEffect(() => { api.voices().then((v) => setVoices(v.voices)).catch(() => {}); api.ambiences().then((a) => setAmbs(a.ambiences)).catch(() => {}); }, []);

  const [resSet, setResSet] = useState(false);
  useEffect(() => { // start at the size this PC is meant to use, not at the smallest one in the list
    if (!limits || resSet) return;
    const p = limits.profile, i = p.resolutions.findIndex((r) => r.width === p.default_width && r.height === p.default_height);
    if (i >= 0) setResIdx(i);
    setResSet(true);
  }, [limits, resSet]);
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

  const [cloudOpen, setCloudOpen] = useState(false);
  const [cDur, setCDur] = useState<6 | 8 | 10>(6);
  const [cRes, setCRes] = useState<string>("1080p");
  const [cAudio, setCAudio] = useState(true);
  const PRICES: Record<"ltx" | "omni", Record<string, number>> = { ltx: { "1080p": 0.08, "1440p": 0.16, "2160p": 0.32 }, omni: { "720p": 0.10, "1080p": 0.15, "4k": 0.30 } };
  const resOk = cRes in PRICES[engine] ? cRes : "1080p";
  const cloudCost = cDur * PRICES[engine][resOk];
  const makeCloud = async () => {
    if (!prompt.trim()) { toast("Describe what should happen.", true); return; }
    if (mode === "extend") { toast("Cloud video starts from text or a start picture. Switch to Text or Picture.", true); return; }
    if (mode === "i2v" && !imageId) { toast("Pick a starting picture first.", true); return; }
    setSubmitting(true); setResultId(null); setStartedAt(Date.now()); setNow(Date.now());
    try {
      const j = await api.cloudVideo({ prompt: prompt.trim(), start_asset_id: mode === "i2v" ? imageId ?? undefined : undefined, end_asset_id: mode === "i2v" ? endId ?? undefined : undefined,
        duration: cDur, resolution: resOk, aspect_ratio: aspect === "9:16" ? "9:16" : "16:9", audio: cAudio, engine, narration: narration.trim() || undefined, persona });
      setJobId(j.id);
      watchJob(j, (done) => { if (done.status === "done" && done.result?.asset_id) setResultId(done.result.asset_id as string); });
    } catch (e) { toast((e as Error).message, true); } finally { setSubmitting(false); }
  };
  const [improving, setImproving] = useState(false);
  const improve = async () => {
    if (!prompt.trim()) return;
    setImproving(true);
    try { const r = await api.enhancePrompt(prompt.trim(), "video"); setPrompt(r.prompt); toast(r.how === "ai" ? "Your AI rewrote the prompt with more detail." : "Added cinematic detail. Connect an AI in the chat editor for smarter rewrites."); }
    catch (e) { toast((e as Error).message, true); } finally { setImproving(false); }
  };
  const [est, setEst] = useState<Estimate | null>(null);
  useEffect(() => {
    if (!model) return;
    const t = setTimeout(() => { api.estimate({ width, height, frames: nFrames, model_id: model.id, steps: model.distilled ? undefined : (steps ?? model.default_steps), end_image: mode !== "t2v" && !!endId }).then(setEst).catch(() => setEst(null)); }, 250);
    return () => clearTimeout(t);
  }, [width, height, nFrames, model, steps, mode, endId]);
  const fmtEta = (sec: number) => (sec < 90 ? `${Math.round(sec)} seconds` : sec < 5400 ? `${Math.round(sec / 60)} minutes` : `${(sec / 3600).toFixed(1)} hours`);
  const tooLong = !!est && !unlock && est.limit_seconds != null && est.seconds > est.limit_seconds;

  const toggleMini = () => { const v = !mini; setMini(v); try { localStorage.setItem("vk_gen_mini", v ? "1" : "0"); } catch { /* ignore */ } };
  const missing = mode === "i2v" && !imageId ? "Pick a starting picture below." : mode === "extend" && !sourceId ? "Pick the clip to continue below." : !prompt.trim() ? "Describe what should happen." : null;

  const submit = async () => {
    if (missing || !model) return;
    setSubmitting(true); setResultId(null); setStartedAt(Date.now()); setNow(Date.now());
    const body = {
      prompt: prompt.trim(), negative_prompt: negative.trim(), width, height, frames: nFrames, seed: seed.trim() === "" ? -1 : Number(seed),
      sound: soundOn ? ({ narration: narration.trim(), voice, rate: 0, ambience, music, level, persona } as SoundOptions) : undefined,
      model_id: model.id, steps: model.distilled ? undefined : (steps ?? model.default_steps), guidance: model.distilled ? undefined : (guidance ?? model.default_guidance), unlock_limits: unlock,
    };
    try {
      const j = mode === "extend"
        ? await api.extend({ ...body, mode: "i2v", source_asset_id: sourceId!, end_image_asset_id: endId ?? undefined })
        : await api.generate({ ...body, mode: mode === "i2v" ? "i2v" : "t2v", image_asset_id: mode === "i2v" ? imageId ?? undefined : undefined, end_image_asset_id: mode === "i2v" ? endId ?? undefined : undefined });
      setJobId(j.id);
      watchJob(j, (done) => { if (done.status === "done" && done.result?.asset_id) setResultId(done.result.asset_id); const w = done.result?.warnings as string[] | undefined; if (w?.length) toast(w[0], true); });
    } catch (e) { toast((e as Error).message, true); } finally { setSubmitting(false); }
  };

  const elapsed = startedAt ? Math.max(job?.elapsed ?? 0, (now - startedAt) / 1000) : 0;
  const overTime = !!job && job.status === "running" && !!job.expected && elapsed > Math.max(job.expected * 2, 600);
  const phase = (job?.phase || "").toLowerCase();
  const last = soundOn ? 4 : 3;
  const stage = !job || job.status === "queued" ? 0 : /librar|sav|writ/.test(phase) && job.progress >= 0.98 ? last : soundOn && /sound|voice|record|background/.test(phase) ? 3 : job.progress >= 0.95 && !soundOn ? last : /load|prepar|download/.test(phase) || job.progress === 0 ? 1 : 2;
  const STAGES = soundOn ? ["Queued", "Loading models", "Generating", "Sound & voice", "Saving"] : ["Queued", "Loading models", "Generating", "Saving"];
  const ASPECTS: { id: typeof aspect; label: string; sub: string }[] = [{ id: "16:9", label: "16:9", sub: "YouTube" }, { id: "9:16", label: "9:16", sub: "Shorts · Reels" }, { id: "1:1", label: "1:1", sub: "Square" }, { id: "4:5", label: "4:5", sub: "Feed" }];

  return (
    <main className={`page gen${mini ? " gen--mini" : ""}`}>
      <div className="gen-head row between gap wrap">
        <div className="stack"><h1>Make a video</h1><p className="text-sm">{system.gpu.available ? `${system.gpu.name} · ${system.gpu.vram_gb} GB` : "Running on this PC"} · {prof.label} settings</p></div>
        <div className="row gap center-v wrap"><Tabs label="What to start from" value={mode} onChange={(m) => { setMode(m); setResultId(null); }} options={[{ id: "t2v", label: "Text" }, { id: "i2v", label: "Picture" }, { id: "extend", label: "Continue" }]} />
          <button type="button" className="gchip gchip--icon" aria-pressed={mini} onClick={toggleMini} title={mini ? "Show the full view" : "Make this page smaller"}><span>{mini ? "Full view" : "Minimise view"}</span></button></div>
      </div>

      {system.torch && !system.gpu.available && (
        <div className="notice" role="note"><span>Your graphics card is not switched on, so videos are small and slow. </span><button type="button" className="linklike" onClick={goSettings}>Open Settings to fix it</button></div>
      )}

      <section className="gen-stage" aria-label="Result" aria-live="polite">
        {active && job && mini ? (
          <div className="run-mini card" role="status">
            <div className="row between gap center-v"><span className="w-medium truncate">Creating your video · {Math.round(job.progress * 100)}%</span><span className="row gap center-v"><span className="mono text-sm">{fmtDuration(elapsed)}</span><Button variant="secondary" small onClick={() => api.cancelJob(job.id).catch((e) => toast(e.message, true))}>Cancel</Button></span></div>
            <div className="bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(job.progress * 100)} aria-label="Video progress"><i className={job.progress === 0 ? "indet" : ""} style={{ width: `${Math.max(job.progress * 100, job.progress === 0 ? 30 : 2)}%` }} /></div>
            <span className="text-xs run-sub">{job.phase || "Working…"}</span>
          </div>
        ) : active && job ? (
          <div className="run card stack gap-lg">
            <div className="row between gap"><div className="stack"><span className="w-medium">Creating your video</span><span className="text-sm run-sub">{width}×{height} · {(nFrames / fps).toFixed(1)} s · {aspect}</span></div>
              <Button variant="secondary" small onClick={() => api.cancelJob(job.id).catch((e) => toast(e.message, true))}>Cancel</Button></div>
            <div className="run-timer"><span className="mono run-clock">{fmtDuration(elapsed)}</span><span className="text-sm">elapsed{job.eta != null ? ` · about ${fmtDuration(job.eta)} left` : " · estimating time…"}</span></div>
            <div className="bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(job.progress * 100)} aria-label="Video progress"><i className={job.progress === 0 ? "indet" : ""} style={{ width: `${Math.max(job.progress * 100, job.progress === 0 ? 30 : 2)}%` }} /></div>
            <ol className="flow" aria-label="Steps">{STAGES.map((n, i) => <li key={n} className={i < stage ? "done" : i === stage ? "now" : ""}><b>{i < stage ? "✓" : i + 1}</b><span>{n}</span></li>)}</ol>
            <p className="text-xs run-sub">{job.phase || "Working…"} · {Math.round(job.progress * 100)}%{!system.gpu.available ? " · On the processor this is slow; the first run also loads the model." : ""}{job.expected ? ` · expected about ${fmtEta(job.expected)}` : ""}</p>
            {overTime && <div className="over" role="alert"><b>This is taking much longer than expected.</b><span className="text-sm">Normal for this size: about {fmtEta(job.expected ?? 0)}. It will stop by itself after {settings.time_limit_min || "no"} minutes. Watch the numbers below: they show what is slowing it down.</span></div>}
            <Meters jobId={job.id} />
          </div>
        ) : result ? (
          <div className="stack gap">
            <video className={`player${mini ? " player--mini" : ""}`} src={mediaUrl(result.id)} controls autoPlay loop playsInline />
            <div className="row between gap wrap">
              <span className="text-sm">{result.width}×{result.height} · {fmtDuration(result.duration)} · seed {String(result.meta.seed ?? "?")}</span>
              <div className="row gap wrap">
                <Button variant="secondary" small onClick={() => { setMode("extend"); setSourceId(result.id); setResultId(null); }}>Continue this clip</Button>
                <Button variant="secondary" small onClick={() => void saveAs(mediaUrl(result.id, "download"), `${result.name.replace(/\.[^.]+$/, "")}.mp4`)}>Save as…</Button>
                <Button variant="ghost" small onClick={goLibrary}>Open library</Button>
              </div>
            </div>
          </div>
        ) : (
          <div className={`empty gen-empty${mini ? " gen-empty--mini" : ""}`}><svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d={I.film} /></svg><h3>What will you create?</h3><p className="text-sm">Describe a scene below. Finished videos are saved in your Library.</p></div>
        )}
        {job?.status === "error" && <p className="error-text" role="alert">{job.error}</p>}
        {job?.status === "cancelled" && job.note && <p className="error-text" role="alert">{job.note}</p>}
      </section>

      <section className="composer" aria-label="Video settings">
        {mode === "i2v" && (
          <div className="slots">
            <MediaSlot kind="image" value={imageId} onChange={setImageId} label="Start picture" hint="The first frame of the video" compact />
            <MediaSlot kind="image" value={endId} onChange={setEndId} label="End picture (optional)" hint="The video finishes on this picture" compact />
          </div>
        )}
        {mode === "extend" && (
          <div className="slots">
            <MediaSlot kind="video" value={sourceId} onChange={setSourceId} label="Clip to continue" hint="Its last frame starts the new clip" compact />
            <MediaSlot kind="image" value={endId} onChange={setEndId} label="End picture (optional)" hint="The new clip finishes on this picture" compact />
          </div>
        )}
        <label className="sr-only" htmlFor="prompt">{mode === "t2v" ? "What should the video show?" : "What should happen?"}</label>
        <textarea id="prompt" className="composer-text" rows={mini ? 2 : 3} value={prompt} maxLength={4000} onChange={(e) => setPrompt(e.target.value)} placeholder="A lighthouse on a cliff at dawn, waves rolling in, the camera slowly pushes forward." />
        <div className="composer-bar">
          <div className="gchips" role="radiogroup" aria-label="Video shape">
            {ASPECTS.map((a) => <button key={a.id} type="button" role="radio" aria-checked={aspect === a.id} className={`gchip${aspect === a.id ? " gchip--on" : ""}`} onClick={() => setAspect(a.id)} title={a.sub}><span>{a.label}</span><small>{a.sub}</small></button>)}
          </div>
          <button type="button" className={`gchip${soundOn ? " gchip--on" : ""}`} aria-pressed={soundOn} onClick={() => setSoundOn(!soundOn)} title="Add a voice and background sound to the new video"><span>{soundOn ? "Sound on" : "Sound off"}</span><small>Voice · ambience</small></button>
          {soundOn && <button type="button" className="gchip" aria-expanded={soundOpen} onClick={() => setSoundOpen(!soundOpen)}><span>Voice &amp; sound</span><small>{soundOpen ? "Hide ▴" : "Edit ▾"}</small></button>}
          <button type="button" className="gchip" aria-expanded={showAdvanced} onClick={() => setShowAdvanced(!showAdvanced)}><span>{width}×{height} · {(nFrames / fps).toFixed(1)} s</span><small>Options ▾</small></button>
          <button type="button" className="gchip" onClick={() => void improve()} disabled={improving || !prompt.trim()} title="Rewrite your idea as a detailed prompt: subject, camera, light, mood"><span>{improving ? "Improving…" : "Improve prompt"}</span><small>More detail</small></button>
          <button type="button" className={`gchip${cloudOpen ? " gchip--on" : ""}`} aria-expanded={cloudOpen} onClick={() => setCloudOpen(!cloudOpen)} title="Sharp 1080p+ video with sound, made online (your fal.ai key)"><span>Sharp online video</span><small>1080p+ · with sound</small></button>
          <span className="grow" />
          <Button icon={I.sparkle} busy={submitting} disabled={!!missing || active || !modelsReady || tooLong} onClick={submit}>{active ? "Generating…" : "Generate"}</Button>
        </div>
        {est && !active && (
          <div className={`eta eta--${est.band}`} role="status">
            <b>{est.device === "gpu" ? "On your graphics card" : "On the CPU"}: about {fmtEta(est.seconds)}</b>
            <span className="text-xs run-sub">(usually {fmtEta(est.low)} to {fmtEta(est.high)}{est.device === "gpu" && system.gpu.name ? ` on ${system.gpu.name}` : ""})</span>
            {(est.band === "too_long" || est.band === "slow" || est.notes.length > 0) && (
              <ul className="text-xs">{[...est.notes, ...est.tips].map((n) => <li key={n}>{n}</li>)}</ul>
            )}
          </div>
        )}
        {tooLong && <p className="why-block text-sm" role="alert">This would take longer than your {settings.time_limit_min}-minute limit, so Generate is switched off. Pick a smaller size or shorter length, or tick “Allow sizes and lengths beyond what this PC can handle”.</p>}
        {(blocked || missing) && (
          <div className="why row gap wrap" role="status">
            <span className={blocked ? "why-block" : ""}>{blocked ?? missing}</span>
            {blocked && <Button variant="secondary" small onClick={goSettings}>{downloading ? "See downloads" : "Download models"}</Button>}
            {blocked && downloading && <div className="bar bar--thin" aria-hidden="true"><i style={{ width: `${dlPct}%` }} /></div>}
          </div>
        )}
        {cloudOpen && (
          <div className="pop stack gap" aria-label="Sharp online video">
            <div className="row gap wrap center-v"><b className="text-sm">Sharp online video</b><span className="text-xs run-sub">Very large models that a laptop card cannot run. They make crisp video with sound in a minute or two. Uses your fal.ai key (Motion control → Connect). This clip costs about ${cloudCost.toFixed(2)}.</span></div>
            <div className="seg" style={{ alignSelf: "flex-start" }} role="radiogroup" aria-label="Online engine">
              <button type="button" role="radio" aria-checked={engine === "ltx"} className={engine === "ltx" ? "on" : ""} onClick={() => setEngine("ltx")} title="LTX-2.3 by Lightricks: 22 billion parameters, 1080p to 4K, with sound">LTX-2.3</button>
              <button type="button" role="radio" aria-checked={engine === "omni"} className={engine === "omni" ? "on" : ""} onClick={() => setEngine("omni")} title="Gemini Omni Flash 1.1 by Google: strong camera moves, physics and native sound">Gemini Omni Flash 1.1</button>
            </div>
            <div className="grid-2">
              <Field label="Length" htmlFor="cdur"><select id="cdur" className="select" value={cDur} onChange={(e) => setCDur(Number(e.target.value) as 6 | 8 | 10)}><option value={6}>6 seconds</option><option value={8}>8 seconds</option><option value={10}>10 seconds</option></select></Field>
              <Field label="Sharpness" htmlFor="cres"><select id="cres" className="select" value={resOk} onChange={(e) => setCRes(e.target.value)}>{Object.entries(PRICES[engine]).map(([r, p]) => <option key={r} value={r}>{r === "4k" || r === "2160p" ? "4K" : r} (${p.toFixed(2)} per second)</option>)}</select></Field>
            </div>
            {engine === "ltx" && <label className="check"><input type="checkbox" checked={cAudio} onChange={(e) => setCAudio(e.target.checked)} />Let the model make sound too</label>}
            <p className="hint">A voice-over typed under “Voice &amp; sound” is recorded on this PC in a voice that fits the person (woman, man, old, child) and added to the finished video.</p>
            {(aspect === "1:1" || aspect === "4:5") && <p className="hint">Online video supports 16:9 and 9:16 only; 16:9 will be used.</p>}
            <div className="row"><Button icon={I.sparkle} busy={submitting} disabled={active || !prompt.trim()} onClick={makeCloud}>Make it online</Button></div>
          </div>
        )}
        {soundOn && soundOpen && !mini && (
          <div className="pop stack gap" aria-label="Sound and voice">
            <div className="row gap wrap center-v"><b className="text-sm">Sound &amp; voice</b><span className="text-xs run-sub">Made on this PC and mixed into the video when it finishes.</span></div>
            <Field label="Voice-over (optional)" htmlFor="narr" hint="Words a voice speaks over the video. Keep it short enough for the length of the clip.">
              <textarea id="narr" className="input" rows={2} maxLength={3000} value={narration} onChange={(e) => setNarration(e.target.value)} placeholder="The lighthouse stands alone as the morning sun rises over the sea." />
            </Field>
            <div className="grid-2">
              <Field label="Voice" htmlFor="voice"><select id="voice" className="select" value={voice} onChange={(e) => setVoice(e.target.value)} disabled={!narration.trim() || voices.length === 0}><option value="">{voices.length ? "Default voice" : "No voice found on this PC"}</option>{voices.map((v) => <option key={v} value={v}>{v}</option>)}</select></Field>
              <Field label="Who is speaking" htmlFor="persona"><select id="persona" className="select" value={persona} onChange={(e) => setPersona(e.target.value as Persona)}>{PERSONAS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}</select></Field>
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
      {!active && !mini && <Meters compact />}
    </main>
  );
}
