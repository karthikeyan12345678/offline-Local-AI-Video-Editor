import { useEffect, useRef, useState } from "react";
import { Button } from "../ds";
import { PLATFORM_PRESETS, presetFor } from "./model";
import type { Project } from "../lib/types";

// One-click video formats for YouTube, Shorts, Reels and Instagram. Existing clips are kept and fitted to the new frame.
export default function FormatMenu({ project, commit }: { project: Project; commit: (fn: (p: Project) => Project, key?: string) => void }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", away); document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", esc); };
  }, [open]);
  const cur = presetFor(project.canvas.width, project.canvas.height);
  const fill = project.clips.length > 0 && project.clips.every((c) => c.fit === "fill");
  const apply = (id: string) => {
    const p = PLATFORM_PRESETS.find((x) => x.id === id); if (!p) return;
    commit((pr) => ({ ...pr, canvas: { ...pr.canvas, width: p.width, height: p.height, fps: p.fps } }));
    setOpen(false);
  };
  return (
    <div className="fmt-menu" ref={box}>
      <Button variant="secondary" small aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}>{cur ? cur.label : `${project.canvas.width}×${project.canvas.height}`} ▾</Button>
      {open && (
        <div className="fmt-pop" role="menu" aria-label="Video format">
          {PLATFORM_PRESETS.map((p) => (
            <button key={p.id} type="button" role="menuitemradio" aria-checked={cur?.id === p.id} className={`fmt-item${cur?.id === p.id ? " on" : ""}`} onClick={() => apply(p.id)}>
              <span className={`fmt-shape s${p.width > p.height ? "w" : p.width < p.height ? "t" : "q"}`} aria-hidden="true" />
              <span><b>{p.label}</b><small>{p.hint}</small></span>
            </button>
          ))}
          <label className="fmt-fill"><input type="checkbox" checked={fill} onChange={(e) => commit((pr) => ({ ...pr, clips: pr.clips.map((c) => ({ ...c, fit: e.target.checked ? "fill" : "fit" })) }))} />Fill the frame (crop edges, no black bars)</label>
        </div>
      )}
    </div>
  );
}
