import { useEffect, useState } from "react";
import { api, mediaUrl, type MotionSettings } from "../lib/api";
import { useApp } from "../lib/store";
import { useAI } from "../editor/useAI";
import { Button, Empty, Field, I } from "../ds";
import MediaSlot from "./MediaSlot";
import { saveAs } from "../lib/save";

/** Motion Control: one character picture + one motion video -> the character performs that motion (through the person's own fal.ai key). */
export default function MotionControl({ goLibrary }: { goLibrary: () => void }) {
  const { asset, refreshAssets, toast } = useApp();
  const ai = useAI();
  const [img, setImg] = useState("");
  const [vid, setVid] = useState("");
  const [orientation, setOrientation] = useState<"image" | "video">("video");
  const [mode, setMode] = useState<"std" | "pro">("std");
  const [keep, setKeep] = useState(true);
  const [prompt, setPrompt] = useState("");
  const [cfg, setCfg] = useState<MotionSettings | null>(null);
  const [key, setKey] = useState("");
  const [engine, setEngine] = useState<"cloud" | "local">("cloud");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState("");
  useEffect(() => { api.motionSettings().then((c) => { setCfg(c); setMode(c.mode); }).catch(() => {}); }, []);

  const v = vid ? asset(vid) : undefined;
  const limit = orientation === "image" ? 10 : 30;
  const tooLong = !!v && v.duration > limit + 0.05;
  const tooShort = !!v && v.duration < 2.9;

  const saveKey = async () => {
    try { setCfg(await api.saveMotionSettings({ fal_key: key, mode })); setKey(""); toast("Key saved on this PC."); } catch (e) { toast(e instanceof Error ? e.message : "Could not save.", true); }
  };
  const go = async () => {
    setBusy(true); setResult("");
    try {
      const r = await ai.wait(engine === "local" ? await api.motionLocal({ image_asset_id: img, video_asset_id: vid }) : await api.motionRun({ image_asset_id: img, video_asset_id: vid, orientation, mode, prompt, keep_sound: keep }));
      await refreshAssets();
      setResult((r.asset_id as string) ?? "");
      toast(engine === "local" ? "Your quick preview is ready." : "Your motion-control video is ready.");
    } catch (e) { toast(e instanceof Error ? e.message : "That did not work.", true); }
    finally { setBusy(false); }
  };

  return (
    <main className="page motion mc">
      <div className="mc-head row between gap wrap">
        <div className="stack"><h1>Motion control</h1><p className="text-sm muted">Give a character picture and a video of someone moving. The character repeats the movement.</p></div>
        {cfg?.has_key ? <span className="gchip gchip--static"><span>fal.ai key saved</span><small className="mono">{cfg.key_hint} · <button type="button" className="linklike" onClick={() => setCfg({ ...cfg, has_key: false })}>change</button></small></span> : null}
      </div>
      {engine === "cloud" && !cfg?.has_key && (
        <div className="mc-key card row gap wrap center-v" aria-labelledby="mc-key">
          <div className="stack grow"><b id="mc-key" className="text-sm">Connect your fal.ai key</b><span className="text-xs muted">Get one at fal.ai → Dashboard → Keys and add a little credit. It stays in your data folder and is sent only to fal.ai.</span></div>
          <input className="input mc-key-input" type="password" autoComplete="off" aria-label="fal.ai key" value={key} onChange={(e) => setKey(e.target.value)} placeholder="paste your key" />
          <Button small disabled={key.trim().length < 8} onClick={saveKey}>Save key</Button>
        </div>
      )}
      <div className="stack" style={{ marginBottom: 12 }}>
        <div className="seg" role="radiogroup" aria-label="Motion engine">
          <button type="button" role="radio" aria-checked={engine === "cloud"} className={engine === "cloud" ? "on" : ""} onClick={() => setEngine("cloud")} title="Realistic. Uses your fal.ai key and credit.">Realistic (Kling, online)</button>
          <button type="button" role="radio" aria-checked={engine === "local"} className={engine === "local" ? "on" : ""} onClick={() => setEngine("local")} title="Free, on this PC, no key. Rough puppet-style preview.">Quick preview (free, on this PC)</button>
        </div>
        {engine === "local" && <span className="text-xs muted">Free and private: MediaPipe finds the body and bends your picture to follow the movement. It is a rough preview (the picture is stretched, not re-drawn). First use downloads a small 6 MB body-finder file. For a realistic result use Kling.</span>}
      </div>
      <div className="mc-grid">
        <section className="mc-in card stack gap" aria-label="Inputs">
          <div className="mc-slots">
            <div className="stack"><MediaSlot kind="image" value={img || null} onChange={(id) => setImg(id ?? "")} label="Character picture" hint="One person, head to toe works best" /></div>
            <div className="stack"><MediaSlot kind="video" value={vid || null} onChange={(id) => setVid(id ?? "")} label="Motion video" hint={`3 to ${limit} seconds, one person moving`} />
              {tooLong && <p className="error-text text-xs" role="alert">This video is {v!.duration.toFixed(0)} s. Trim it to {limit} s or less in the Editor, or switch to “follow the video”.</p>}
              {tooShort && <p className="error-text text-xs" role="alert">This video is shorter than 3 seconds.</p>}</div>
          </div>
          {engine === "cloud" && <>
          <Field label="Extra instructions (optional)" hint="For example: a sunny beach in the background, wearing a red jacket.">
            <textarea className="input" rows={2} maxLength={500} value={prompt} onChange={(e) => setPrompt(e.target.value)} />
          </Field>
          <div className="mc-opts">
            <div className="stack"><span className="text-xs muted">Direction</span>
              <div className="seg" role="radiogroup" aria-label="Camera and body direction">
                <button type="button" role="radio" aria-checked={orientation === "video"} className={orientation === "video" ? "on" : ""} onClick={() => setOrientation("video")} title="Character turns and moves like the video, up to 30 s">Follow video</button>
                <button type="button" role="radio" aria-checked={orientation === "image"} className={orientation === "image" ? "on" : ""} onClick={() => setOrientation("image")} title="Keep the picture’s direction, up to 10 s">Keep picture</button>
              </div></div>
            <div className="stack"><span className="text-xs muted">Quality</span>
              <div className="seg" role="radiogroup" aria-label="Quality">
                <button type="button" role="radio" aria-checked={mode === "std"} className={mode === "std" ? "on" : ""} onClick={() => { setMode("std"); api.saveMotionSettings({ mode: "std" }).catch(() => {}); }}>Standard</button>
                <button type="button" role="radio" aria-checked={mode === "pro"} className={mode === "pro" ? "on" : ""} onClick={() => { setMode("pro"); api.saveMotionSettings({ mode: "pro" }).catch(() => {}); }} title="Sharper, costs more">Pro</button>
              </div></div>
            <label className="check"><input type="checkbox" checked={keep} onChange={(e) => setKeep(e.target.checked)} />Keep the video’s sound</label>
          </div>
          </>}
          <Button icon={I.sparkle} busy={busy} disabled={(engine === "cloud" && !cfg?.has_key) || !img || !vid || (engine === "cloud" && tooLong) || tooShort} onClick={go}>Generate</Button>
          {engine === "cloud" && !cfg?.has_key ? <p className="text-xs muted">Connect your fal.ai key first.</p> : (!img || !vid) ? <p className="text-xs muted">Add a character picture and a motion video.</p> : null}
        </section>
        <aside className="mc-out card stack gap" aria-label="Result" aria-live="polite">
          {result ? <><video className="player" controls autoPlay loop src={mediaUrl(result)} /><div className="row gap"><Button small variant="secondary" icon={I.download} onClick={() => saveAs(mediaUrl(result, "download"), "motion-control.mp4")}>Save as…</Button><Button small variant="secondary" onClick={goLibrary}>Open in Library</Button><Button small variant="ghost" onClick={() => setResult("")}>Clear</Button></div></>
            : busy ? <div className="mc-wait stack gap center-v"><div className="bar" role="progressbar" aria-label="Working"><i className="indet" style={{ width: "30%" }} /></div><b>Creating your video…</b><span className="text-sm muted">This takes about a minute or two. Keep this window open.</span></div>
            : <Empty icon={I.film} title="Your video appears here">Add the picture and the motion video, then press Generate.</Empty>}
        </aside>
      </div>
    </main>
  );
}
