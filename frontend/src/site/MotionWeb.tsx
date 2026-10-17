import { useEffect, useState } from "react";
import { mediaUrl } from "../lib/api";
import { useApp } from "../lib/store";
import { Button, Empty, Slider, I } from "../ds";
import MediaSlot from "../views/MediaSlot";
import { saveAs } from "../lib/save";
import { webCall } from "../web/backend";
import QuotaMeter from "../web/QuotaMeter";
import { loadHF } from "../web/hf";
import type { Asset, Job } from "../lib/types";

/** Motion control: a character picture + a video of someone moving. Made by Wan 2.2 Animate on a free Hugging Face GPU. */
export default function MotionWeb({ goLibrary, goSettings, goEditor }: { goLibrary: () => void; goSettings: () => void; goEditor: (a: Asset) => void }) {
  const { jobs, watchJob, toast, asset } = useApp();
  const [img, setImg] = useState<string | null>(null);
  const [vid, setVid] = useState<string | null>(null);
  const [mode, setMode] = useState<"Character Swap" | "Pose Retarget">("Pose Retarget");
  const [quality, setQuality] = useState<"Low Res" | "Medium Res">("Low Res");
  const [seconds, setSeconds] = useState(4);
  const [jobId, setJobId] = useState<string | null>(null);
  const [result, setResult] = useState("");
  const [busy, setBusy] = useState(false);
  const [hasToken, setHasToken] = useState(() => !!loadHF().token);
  useEffect(() => { const on = () => setHasToken(!!loadHF().token); window.addEventListener("vk-hf", on); return () => window.removeEventListener("vk-hf", on); }, []);

  const v = vid ? asset(vid) : undefined;
  const tooLong = !!v && v.duration > 30.05;
  const job: Job | null = jobs.find((j) => j.id === jobId) ?? null;
  const active = !!job && (job.status === "queued" || job.status === "running");
  const out = result ? asset(result) : undefined;

  const go = async () => {
    setBusy(true); setResult("");
    try {
      const j = await webCall("POST", "/web/motion", { image_asset_id: img, video_asset_id: vid, mode, quality, seconds }) as Job;
      setJobId(j.id);
      watchJob(j, (d) => { if (d.status === "done" && d.result?.asset_id) { setResult(d.result.asset_id as string); toast("Your motion-control video is ready."); } });
    } catch (e) { toast((e as Error).message, true); } finally { setBusy(false); }
  };

  return (
    <main className="page motion mc">
      <div className="mc-head row between gap wrap">
        <div className="stack"><h1>Motion control</h1><p className="text-sm muted">Give a character picture and a video of someone moving. The character repeats the movement. Free, on a Hugging Face GPU.</p></div>
      </div>
      {!hasToken && <div className="notice" role="note"><span>No Hugging Face token yet: a free account gets more GPU time. </span><button type="button" className="linklike" onClick={goSettings}>Add a free token</button></div>}
      <div className="mc-grid">
        <section className="mc-in card stack gap" aria-label="Inputs">
          <div className="mc-slots">
            <div className="stack"><MediaSlot kind="image" value={img} onChange={setImg} label="Character picture" hint="One person, head to toe works best" /></div>
            <div className="stack"><MediaSlot kind="video" value={vid} onChange={setVid} label="Motion video" hint="A few seconds, one person moving" />
              {tooLong && <p className="error-text text-xs" role="alert">This video is {v!.duration.toFixed(0)} s. Trim it to 30 s or less in the Editor first.</p>}</div>
          </div>
          <div className="mc-opts">
            <div className="stack"><span className="text-xs muted">What should happen</span>
              <div className="seg" role="radiogroup" aria-label="Mode">
                <button type="button" role="radio" aria-checked={mode === "Pose Retarget"} className={mode === "Pose Retarget" ? "on" : ""} onClick={() => setMode("Pose Retarget")} title="The Space’s “Pose Retarget” mode: the character in your picture takes the pose and movement of the person in the video">Make my picture move</button>
                <button type="button" role="radio" aria-checked={mode === "Character Swap"} className={mode === "Character Swap" ? "on" : ""} onClick={() => setMode("Character Swap")} title="The Space’s “Character Swap” mode: your character replaces the person in the video">Put my character in the video</button>
              </div></div>
            <div className="stack"><span className="text-xs muted">Quality</span>
              <div className="seg" role="radiogroup" aria-label="Quality">
                <button type="button" role="radio" aria-checked={quality === "Low Res"} className={quality === "Low Res" ? "on" : ""} onClick={() => setQuality("Low Res")} title="Uses less free GPU time">Standard</button>
                <button type="button" role="radio" aria-checked={quality === "Medium Res"} className={quality === "Medium Res" ? "on" : ""} onClick={() => setQuality("Medium Res")} title="Sharper, uses more free GPU time">Better</button>
              </div></div>
          </div>
          <Slider label="Length to make" value={seconds} min={2} max={20} step={1} onChange={setSeconds} format={(s) => `${s} s`} />
          <p className="hint">Free GPU time is limited (about 5 minutes a day with a free account), so a few seconds at Standard quality is the safe start.</p>
          <Button icon={I.sparkle} busy={busy} disabled={!img || !vid || tooLong || active} onClick={go}>{active ? "Generating…" : "Generate"}</Button>
          {(!img || !vid) && <p className="text-xs muted">Add a character picture and a motion video.</p>}
        </section>
        <aside className="mc-out card stack gap" aria-label="Result" aria-live="polite">
          {out ? <><video className="player" controls autoPlay loop src={mediaUrl(out.id)} /><div className="row gap wrap"><Button small onClick={() => goEditor(out)}>Edit this video</Button><Button small variant="secondary" icon={I.download} onClick={() => void saveAs(mediaUrl(out.id, "download"), "motion-control.mp4")}>Save as…</Button><Button small variant="secondary" onClick={goLibrary}>Open in Library</Button><Button small variant="ghost" onClick={() => setResult("")}>Clear</Button></div></>
            : active && job ? <div className="mc-wait stack gap center-v"><div className="bar" role="progressbar" aria-valuenow={Math.round(job.progress * 100)} aria-valuemin={0} aria-valuemax={100} aria-label="Working"><i className={job.progress < 0.04 ? "indet" : ""} style={{ width: `${Math.max(job.progress * 100, job.progress < 0.04 ? 30 : 2)}%` }} /></div><b>{job.phase || "Creating your video…"}</b><span className="text-sm muted">Free GPUs are shared: you may wait in a queue, then it takes a minute or two. Keep this tab open.</span><Button small variant="secondary" onClick={() => void webCall("POST", `/jobs/${job.id}/cancel`)}>Cancel</Button></div>
            : <Empty icon={I.film} title="Your video appears here">Add the picture and the motion video, then press Generate.</Empty>}
          {job?.status === "error" && <p className="error-text" role="alert">{job.error}</p>}
          <div className="stack gap"><b className="text-sm">Free GPU time (estimate)</b><QuotaMeter provider="zerogpu" /></div>
        </aside>
      </div>
    </main>
  );
}
