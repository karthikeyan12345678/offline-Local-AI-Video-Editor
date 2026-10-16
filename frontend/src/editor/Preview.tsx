import { useEffect, useRef } from "react";
import { mediaUrl } from "../lib/api";
import type { Asset, Project } from "../lib/types";
import { cssFilter, cssTransform, layout, objectFit, type Placed } from "./model";

interface Props {
  project: Project; asset: (id: string) => Asset | undefined; time: number; playing: boolean;
  onTick: (t: number) => void; onEnd: () => void;
}

/**
 * Live preview: plays the original files directly and approximates colour effects with CSS.
 * Blur, sharpen, denoise, vignette and transitions are only exact in a rendered preview.
 */
export default function Preview({ project, asset, time, playing, onTick, onEnd }: Props) {
  const { items, total } = layout(project, asset);
  const videoRef = useRef<HTMLVideoElement>(null);
  const audioRefs = useRef(new Map<string, HTMLAudioElement>());
  const timeRef = useRef(time);
  timeRef.current = time;
  const live = useRef({ items, total, project, asset });
  live.current = { items, total, project, asset };

  const active: Placed | undefined = [...items].reverse().find((i) => time >= i.start - 1e-6 && time < i.start + i.dur) ?? (time >= total ? items[items.length - 1] : undefined);
  const a = active ? asset(active.clip.asset_id) : undefined;
  const isVideo = a?.kind === "video";
  const containerRef = useRef<HTMLDivElement>(null);

  // Keep the <video> element on the right frame of the right clip.
  useEffect(() => {
    const v = videoRef.current;
    if (!v || !active || !isVideo) return;
    const c = active.clip;
    const end = a!.duration;
    const local = Math.min(Math.max(0, time - active.start), active.dur);
    const target = c.reverse ? Math.min((c.trim_out > 0 ? Math.min(c.trim_out, end) : end), end) - local * c.speed : c.trim_in + local * c.speed;
    const drift = Math.abs(v.currentTime - target);
    if (!playing || drift > 0.25 || c.reverse) { try { v.currentTime = Math.max(0, target); } catch { /* not ready yet */ } }
    v.playbackRate = Math.min(16, Math.max(0.0625, c.speed));
    v.muted = c.muted || !a!.has_audio;
    v.volume = Math.min(1, c.volume * project.master_volume);
    if (playing && !c.reverse) { if (v.paused) v.play().catch(() => {}); } else if (!v.paused) v.pause();
  }, [active?.clip.id, a?.id, time, playing, isVideo]); // eslint-disable-line react-hooks/exhaustive-deps

  // The clock. Real time drives the playhead; media follows it.
  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    let last = performance.now();
    const loop = (now: number) => {
      const dt = (now - last) / 1000; last = now;
      const next = timeRef.current + dt;
      if (next >= live.current.total) { onTick(live.current.total); onEnd(); return; }
      onTick(next);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [playing, onTick, onEnd]);

  // Background audio tracks.
  useEffect(() => {
    for (const ac of project.audio) {
      const el = audioRefs.current.get(ac.id);
      const as = asset(ac.asset_id);
      if (!el || !as) continue;
      const len = Math.max(0.05, (ac.trim_out > 0 ? Math.min(ac.trim_out, as.duration) : as.duration) - ac.trim_in);
      const inside = time >= ac.start && time < ac.start + len;
      let vol = ac.volume * project.master_volume;
      if (ac.fade_in > 0 && time - ac.start < ac.fade_in) vol *= Math.max(0, (time - ac.start) / ac.fade_in);
      if (ac.fade_out > 0 && ac.start + len - time < ac.fade_out) vol *= Math.max(0, (ac.start + len - time) / ac.fade_out);
      el.volume = Math.min(1, Math.max(0, vol));
      if (playing && inside) {
        const want = ac.trim_in + (time - ac.start);
        if (el.paused || Math.abs(el.currentTime - want) > 0.3) { try { el.currentTime = want; } catch { /* ignore */ } }
        if (el.paused) el.play().catch(() => {});
      } else if (!el.paused) el.pause();
      else if (!playing && inside) { try { el.currentTime = ac.trim_in + (time - ac.start); } catch { /* ignore */ } }
    }
  }, [time, playing, project.audio, project.master_volume]); // eslint-disable-line react-hooks/exhaustive-deps

  const { width, height, background } = project.canvas;
  const clip = active?.clip;
  const sc = 1; // blur is px at preview size; close enough for a preview

  // Fades on the clip itself (and the start/end of a cross-dissolve are not simulated).
  let opacity = 1;
  if (clip && active) {
    const local = time - active.start;
    if (clip.fade_in > 0 && local < clip.fade_in) opacity = Math.min(opacity, local / clip.fade_in);
    if (clip.fade_out > 0 && active.dur - local < clip.fade_out) opacity = Math.min(opacity, (active.dur - local) / clip.fade_out);
  }

  return (
    <div className="stage-wrap">
      <div ref={containerRef} className="stage" style={{ aspectRatio: `${width} / ${height}`, background }}>
        {clip && a && (
          <div className="stage-media" style={{ opacity }}>
            {a.kind === "video" ? (
              <video ref={videoRef} key={a.id} src={mediaUrl(a.id)} playsInline preload="auto" style={{ objectFit: objectFit(clip), filter: cssFilter(clip, sc), transform: cssTransform(clip) }} />
            ) : a.kind === "image" ? (
              <img src={mediaUrl(a.id)} alt="" style={{ objectFit: objectFit(clip), filter: cssFilter(clip, sc), transform: cssTransform(clip) }} />
            ) : null}
            {clip.vignette && <div className="vignette" />}
          </div>
        )}
        {project.texts.filter((t) => time >= t.start && time < t.start + t.duration).map((t) => {
          let o = 1;
          if (t.fade_in > 0 && time - t.start < t.fade_in) o = (time - t.start) / t.fade_in;
          if (t.fade_out > 0 && t.start + t.duration - time < t.fade_out) o = Math.min(o, (t.start + t.duration - time) / t.fade_out);
          const rgb = t.box ? `rgba(0,0,0,${t.box_opacity})` : "transparent";
          return <div key={t.id} className="stage-text" style={{ left: `${t.x * 100}%`, top: `${t.y * 100}%`, fontSize: `${t.size}cqh`, color: t.color, fontWeight: t.bold ? 700 : 400, background: rgb, opacity: o }}>{t.text}</div>;
        })}
        {!clip && <div className="stage-empty">Add a clip from the Media panel to start.</div>}
      </div>
      {project.audio.map((ac) => { const as = asset(ac.asset_id); return as ? <audio key={ac.id} preload="auto" src={mediaUrl(as.id)} ref={(el) => { if (el) audioRefs.current.set(ac.id, el); else audioRefs.current.delete(ac.id); }} /> : null; })}
    </div>
  );
}
