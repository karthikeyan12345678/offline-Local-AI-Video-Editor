import { useEffect, useState } from "react";
import { api, mediaUrl, type MotionSettings } from "../lib/api";
import { useApp } from "../lib/store";
import { useAI } from "../editor/useAI";
import { Button, Empty, Field, I } from "../ds";
import { fmtDuration } from "../lib/format";

/** Motion Control: one character picture + one motion video -> the character performs that motion (through the person's own fal.ai key). */
export default function MotionControl({ goLibrary }: { goLibrary: () => void }) {
  const { assets, refreshAssets, toast } = useApp();
  const ai = useAI();
  const pics = assets.filter((a) => a.kind === "image");
  const vids = assets.filter((a) => a.kind === "video");
  const [img, setImg] = useState("");
  const [vid, setVid] = useState("");
  const [orientation, setOrientation] = useState<"image" | "video">("video");
  const [mode, setMode] = useState<"std" | "pro">("std");
  const [keep, setKeep] = useState(true);
  const [prompt, setPrompt] = useState("");
  const [cfg, setCfg] = useState<MotionSettings | null>(null);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState("");
  useEffect(() => { api.motionSettings().then((c) => { setCfg(c); setMode(c.mode); }).catch(() => {}); }, []);

  const v = vids.find((a) => a.id === vid);
  const limit = orientation === "image" ? 10 : 30;
  const tooLong = !!v && v.duration > limit + 0.05;
  const tooShort = !!v && v.duration < 2.9;

  const saveKey = async () => {
    try { setCfg(await api.saveMotionSettings({ fal_key: key, mode })); setKey(""); toast("Key saved on this PC."); } catch (e) { toast(e instanceof Error ? e.message : "Could not save.", true); }
  };
  const go = async () => {
    setBusy(true); setResult("");
    try {
      const r = await ai.wait(await api.motionRun({ image_asset_id: img, video_asset_id: vid, orientation, mode, prompt, keep_sound: keep }));
      await refreshAssets();
      setResult((r.asset_id as string) ?? "");
      toast("Your motion-control video is ready.");
    } catch (e) { toast(e instanceof Error ? e.message : "That did not work.", true); }
    finally { setBusy(false); }
  };

  return (
    <main className="page two-col motion">
      <section className="stack gap">
        <h1>Motion control</h1>
        <p className="muted">Pick a character picture and a video of someone moving. The character performs the same movement. Runs on fal.ai with your own key; about a minute or two per clip.</p>

        <div className="card stack gap" aria-labelledby="mc-key">
          <h2 id="mc-key">1 · Connect</h2>
          {cfg?.has_key ? <p className="text-sm">fal.ai key saved <span className="mono">{cfg.key_hint}</span>. <button type="button" className="linklike" onClick={() => setCfg({ ...cfg, has_key: false })}>Change</button></p> : (
            <>
              <Field label="fal.ai key" hint={<>Get one at fal.ai → Dashboard → Keys, and add a little credit. It is stored only in your data folder and sent only to fal.ai.</>}>
                <input className="input" type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} placeholder="paste your key" />
              </Field>
              <Button small disabled={key.trim().length < 8} onClick={saveKey}>Save key</Button>
            </>
          )}
        </div>

        <div className="card stack gap" aria-labelledby="mc-char">
          <h2 id="mc-char">2 · Character picture</h2>
          <p className="text-sm muted">One person, clearly visible, head to toe works best.</p>
          {pics.length === 0 ? <Empty icon={I.image} title="No pictures yet">Add a picture in the Library first.<br /><Button small variant="secondary" onClick={goLibrary}>Open Library</Button></Empty> : (
            <div className="picker" role="listbox" aria-label="Character picture">
              {pics.map((a) => <button key={a.id} type="button" role="option" aria-selected={img === a.id} className={`pick${img === a.id ? " pick--on" : ""}`} onClick={() => setImg(a.id)}><img className="thumb" src={mediaUrl(a.id, "thumb")} alt="" /><span className="text-xs">{a.name}</span></button>)}
            </div>
          )}
        </div>

        <div className="card stack gap" aria-labelledby="mc-vid">
          <h2 id="mc-vid">3 · Motion video</h2>
          <p className="text-sm muted">The movement to copy: 3 to {limit} seconds. One person moving, full body in view.</p>
          {vids.length === 0 ? <Empty icon={I.film} title="No videos yet">Add a video in the Library first.</Empty> : (
            <div className="picker" role="listbox" aria-label="Motion video">
              {vids.map((a) => <button key={a.id} type="button" role="option" aria-selected={vid === a.id} className={`pick${vid === a.id ? " pick--on" : ""}`} onClick={() => setVid(a.id)}><img className="thumb" src={mediaUrl(a.id, "thumb")} alt="" /><span className="text-xs">{a.name} · {fmtDuration(a.duration)}</span></button>)}
            </div>
          )}
          {tooLong && <p className="error-text" role="alert">This video is {v!.duration.toFixed(0)} s. Trim it to {limit} s or less in the Editor, or switch to “follow the video”.</p>}
          {tooShort && <p className="error-text" role="alert">This video is shorter than 3 seconds.</p>}
        </div>

        <div className="card stack gap" aria-labelledby="mc-opt">
          <h2 id="mc-opt">4 · Options</h2>
          <fieldset className="stack"><legend className="text-sm w-semibold">Camera and body direction</legend>
            <label className="row"><input type="radio" name="ori" checked={orientation === "video"} onChange={() => setOrientation("video")} /> Follow the video (character turns and moves like the video, up to 30 s)</label>
            <label className="row"><input type="radio" name="ori" checked={orientation === "image"} onChange={() => setOrientation("image")} /> Keep the picture’s direction (up to 10 s)</label>
          </fieldset>
          <fieldset className="stack"><legend className="text-sm w-semibold">Quality</legend>
            <label className="row"><input type="radio" name="q" checked={mode === "std"} onChange={() => { setMode("std"); api.saveMotionSettings({ mode: "std" }).catch(() => {}); }} /> Standard (cheaper)</label>
            <label className="row"><input type="radio" name="q" checked={mode === "pro"} onChange={() => { setMode("pro"); api.saveMotionSettings({ mode: "pro" }).catch(() => {}); }} /> Pro (sharper, costs more)</label>
          </fieldset>
          <label className="row"><input type="checkbox" checked={keep} onChange={(e) => setKeep(e.target.checked)} /> Keep the sound of the motion video</label>
          <Field label="Extra instructions (optional)" hint="For example: a sunny beach in the background, wearing a red jacket.">
            <textarea className="input" rows={2} maxLength={500} value={prompt} onChange={(e) => setPrompt(e.target.value)} />
          </Field>
          <Button icon={I.sparkle} busy={busy} disabled={!cfg?.has_key || !img || !vid || tooLong || tooShort} onClick={go}>Make motion-control video</Button>
          {!cfg?.has_key && <p className="text-sm muted">Connect your fal.ai key above first.</p>}
        </div>
      </section>
      <aside className="stack gap">
        <h2>Result</h2>
        {result ? <><video className="player" controls src={mediaUrl(result)} /><div className="row gap"><Button small variant="secondary" icon={I.download} onClick={() => { window.location.href = mediaUrl(result, "download"); }}>Save</Button><Button small variant="secondary" onClick={goLibrary}>Open in Library</Button></div></>
          : <Empty icon={I.film} title="Your video appears here">{busy ? "Working… keep this window open." : "Pick the picture, the motion video, then press the button."}</Empty>}
      </aside>
    </main>
  );
}
