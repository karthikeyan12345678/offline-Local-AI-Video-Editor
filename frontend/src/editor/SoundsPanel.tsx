import { useEffect, useRef, useState } from "react";
import { api, soundUrl, type SoundInfo, type SoundList } from "../lib/api";
import { Button, Icon, I } from "../ds";
import type { Asset } from "../lib/types";

/** The free built-in sound effects: press ▶ to hear one, press + to put it on the timeline at the playhead. */
export default function SoundsPanel({ onAdd }: { onAdd: (a: Asset, s: SoundInfo) => void }) {
  const [list, setList] = useState<SoundList | null>(null);
  const [err, setErr] = useState("");
  const [group, setGroup] = useState("all");
  const [playing, setPlaying] = useState("");
  const [busy, setBusy] = useState("");
  const audio = useRef<HTMLAudioElement | null>(null);

  useEffect(() => { api.sounds().then(setList).catch((e) => setErr(e instanceof Error ? e.message : "Could not load the sounds.")); }, []);
  useEffect(() => () => { audio.current?.pause(); }, []);

  const hear = (s: SoundInfo) => {
    if (playing === s.id) { audio.current?.pause(); setPlaying(""); return; }
    audio.current?.pause();
    const a = new Audio(soundUrl(s.id));
    audio.current = a;
    a.onended = () => setPlaying((p) => (p === s.id ? "" : p));
    a.onerror = () => { setPlaying(""); setErr("Could not play that sound."); };
    setErr(""); setPlaying(s.id);
    a.play().catch(() => setPlaying(""));
  };
  const add = async (s: SoundInfo) => {
    setBusy(s.id); setErr("");
    try { onAdd(await api.soundAdd(s.id), s); } catch (e) { setErr(e instanceof Error ? e.message : "Could not add that sound."); } finally { setBusy(""); }
  };

  if (!list) return <p className="text-sm">{err || "Loading sounds…"}</p>;
  const shown = list.sounds.filter((s) => group === "all" || s.group === group);
  return (
    <div className="stack gap">
      <p className="hint">Free sounds made inside the app: no download, no copyright. Press ▶ to listen and + to put it on the timeline where the playhead is.</p>
      <select className="select select--sm" aria-label="Kind of sound" value={group} onChange={(e) => setGroup(e.target.value)}>
        <option value="all">All sounds</option>
        {list.groups.map((g) => <option key={g} value={g}>{g}</option>)}
      </select>
      {err && <p className="error-text" role="alert">{err}</p>}
      <ul className="sounds">
        {shown.map((s) => (
          <li key={s.id} className={playing === s.id ? "sound sound--on" : "sound"}>
            <button type="button" className="sound-play" aria-label={playing === s.id ? `Stop ${s.label}` : `Listen to ${s.label}`} aria-pressed={playing === s.id} onClick={() => hear(s)}><Icon d={playing === s.id ? I.pause : I.play} /></button>
            <span className="stack sound-name"><span className="text-sm truncate">{s.label}</span><span className="text-xs">{s.group} · {s.duration.toFixed(1)} s</span></span>
            <Button small variant="secondary" icon={I.plus} label={`Add ${s.label} to the timeline`} disabled={busy === s.id} onClick={() => void add(s)} />
          </li>
        ))}
      </ul>
    </div>
  );
}
