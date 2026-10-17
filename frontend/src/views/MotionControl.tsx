import { useEffect, useState } from "react";
import { api, mediaUrl, PERSONAS, type MotionSettings, type Persona } from "../lib/api";
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
  const [narration, setNarration] = useState("");
  const [persona, setPersona] = useState<Persona>("auto");
  const [cfg, setCfg] = useState<MotionSettings | null>(null);
  const [key, setKey] = useState("");
  const [engine, setEngine] = useState<"cloud" | "local">("cloud");
  const [pose, setPose] = useState<"mediapipe" | "tensorflow">("mediapipe");
  const [have, setHave] = useState<{ mediapipe: boolean; tensorflow: boolean } | null>(null);
  const [installing, setInstalling] = useState(false);
  useEffect(() => { api.motionLocalStatus().then(setHave).catch(() => {}); }, []);
  const installTf = async () => {
    setInstalling(true);
    try { await ai.wait(await api.installTensorflow()); setHave(await api.motionLocalStatus()); toast("TensorFlow installed. Close and reopen the app once, then press Generate."); }
    catch (e) { toast(e instanceof Error ? e.message : "Could not install.", true); } finally { setInstalling(false); }
  };
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
      const r = await ai.wait(engine === "local" ? await api.motionLocal({ image_asset_id: img, video_asset_id: vid, engine: pose, keep_sound: keep, narration: narration.trim() || undefined, persona }) : await api.motionRun({ image_asset_id: img, video_asset_id: vid, orientation, mode, prompt, keep_sound: keep, narration: narration.trim() || undefined, persona }));
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
        {cfg?.has_key ? <span className="gchip gchip--static"><span>fal.ai key saved{cfg.source === "file" ? " (from fal.key)" : cfg.source === "env" ? " (from FAL_KEY)" : ""}</span><small className="mono">{cfg.key_hint} · <button type="button" className="linklike" onClick={async () => { try { const r = await api.motionTest(); toast(r.message, !r.ok); } catch (e) { toast(e instanceof Error ? e.message : "Could not test.", true); } }}>test</button> · <button type="button" className="linklike" onClick={() => setCfg({ ...cfg, has_key: false })}>change</button></small></span> : null}
      </div>
      {engine === "cloud" && !cfg?.has_key && (
        <div className="mc-key card row gap wrap center-v" aria-labelledby="mc-key">
          <div className="stack grow"><b id="mc-key" className="text-sm">Connect your fal.ai key</b><span className="text-xs muted">1) Sign in at fal.ai  2) Dashboard → Keys → Create key (preset “API”)  3) add a little credit under Billing  4) paste the whole key here once. It is saved in your data folder and sent only to fal.ai. You can also put it in a file named fal.key in your LTXStudioData folder.</span></div>
          <input className="input mc-key-input" type="password" autoComplete="off" aria-label="fal.ai key" value={key} onChange={(e) => setKey(e.target.value)} placeholder="paste your key" />
          <Button small disabled={key.trim().length < 8} onClick={saveKey}>Save key</Button>
        </div>
      )}
      <div className="stack" style={{ marginBottom: 12 }}>
        <div className="seg" style={{ alignSelf: "flex-start" }} role="radiogroup" aria-label="Motion engine">
          <button type="button" role="radio" aria-checked={engine === "cloud"} className={engine === "cloud" ? "on" : ""} onClick={() => setEngine("cloud")} title="Realistic. Uses your fal.ai key and credit.">Realistic (online)</button>
          <button type="button" role="radio" aria-checked={engine === "local"} className={engine === "local" ? "on" : ""} onClick={() => setEngine("local")} title="Free, on this PC, no key. Rough puppet-style preview.">Quick preview (free, on this PC)</button>
        </div>
        {engine === "local" && (
          <div className="seg" style={{ alignSelf: "flex-start" }} role="radiogroup" aria-label="Body tracking engine">
            <button type="button" role="radio" aria-checked={pose === "mediapipe"} className={pose === "mediapipe" ? "on" : ""} onClick={() => setPose("mediapipe")} title="Google MediaPipe (TensorFlow Lite models inside). Small and fast.">MediaPipe</button>
            <button type="button" role="radio" aria-checked={pose === "tensorflow"} className={pose === "tensorflow" ? "on" : ""} onClick={() => setPose("tensorflow")} title="TensorFlow with the MoveNet model from Google.">TensorFlow (MoveNet)</button>
          </div>
        )}
        {engine === "local" && pose === "tensorflow" && have && !have.tensorflow && (
          <div className="row gap wrap center-v"><span className="text-xs muted">TensorFlow is not installed yet (about 350 MB, once).</span><Button small variant="secondary" busy={installing} onClick={installTf}>Install TensorFlow</Button></div>
        )}
        {engine === "local" && <span className="text-xs muted">Free and private: The body is found in your picture and in the video, the person is cut out, and the arms and legs turn like real limbs while the background stays still. It is still a preview: the picture is moved, not re-drawn. First use downloads a small body-finder file. For a realistic result use the online option.</span>}
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
          </div>
          </>}
          <div className="stack gap">
            <label className="check"><input type="checkbox" checked={keep} onChange={(e) => setKeep(e.target.checked)} />Put the sound of the motion video on the result</label>
            <Field label="Voice-over (optional)" hint="Words a voice speaks over the result. The voice is chosen to fit the person: woman, man, old or child.">
              <textarea className="input" rows={2} maxLength={1500} value={narration} onChange={(e) => setNarration(e.target.value)} />
            </Field>
            {narration.trim() && <Field label="Who is speaking"><select className="select" value={persona} onChange={(e) => setPersona(e.target.value as Persona)}>{PERSONAS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}</select></Field>}
          </div>
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
