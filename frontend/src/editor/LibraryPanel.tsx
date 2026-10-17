import { useMemo, useRef, useState, type ReactNode } from "react";
import { fontFileUrl } from "../lib/api";
import { Button, Icon, I } from "../ds";
import { Thumb } from "../views/shared";
import type { Asset, Clip } from "../lib/types";
import { groupBy, useCatalog } from "./catalog";
import { cssFilter, TEXT_STYLES, type TextStyle } from "./model";

export type LibTab = "media" | "audio" | "text" | "effects" | "filters" | "transitions";
const TABS: { id: LibTab; label: string; icon: string }[] = [
  { id: "media", label: "Media", icon: I.film }, { id: "audio", label: "Audio", icon: I.music ?? I.play }, { id: "text", label: "Text", icon: I.text },
  { id: "effects", label: "Effects", icon: I.sparkle }, { id: "filters", label: "Filters", icon: I.wand }, { id: "transitions", label: "Transitions", icon: I.skipBack },
];

interface Props {
  tab: LibTab; onTab: (t: LibTab) => void;
  assets: Asset[]; onAdd: (a: Asset) => void; onLayer: (a: Asset) => void; onUpload: (f: FileList) => void;
  audioPanel: ReactNode;
  onText: (s?: TextStyle) => void;
  /** What a look/effect/transition would change right now, e.g. "Clip 2". Null when nothing can be changed. */
  target: string | null;
  currentLook: string; currentEffects: string[]; currentTransition: string;
  onLook: (id: string) => void; onEffect: (id: string) => void; onTransition: (id: string) => void;
}

const SWATCH: Clip = { adjust: { brightness: 0, contrast: 0, saturation: 0, gamma: 1, hue: 0 }, preset: "none", blur: 0 } as Clip;

/** A little picture with a colourful scene, so a filter's colour change is visible before you apply it. */
function Swatch({ look }: { look: string }) {
  return <div className="swatch-scene" style={{ filter: cssFilter({ ...SWATCH, preset: look }, 0.3) }} aria-hidden="true"><span /><i /></div>;
}

function Tile({ label, on, onClick, children, hint }: { label: string; on?: boolean; onClick: () => void; children: ReactNode; hint?: string }) {
  return (
    <button type="button" className={`tile${on ? " tile--on" : ""}`} aria-pressed={on} onClick={onClick} title={hint ?? label}>
      <span className="tile-art">{children}</span><span className="tile-label">{label}</span>
    </button>
  );
}

export default function LibraryPanel(p: Props) {
  const cat = useCatalog();
  const [q, setQ] = useState("");
  const [bin, setBin] = useState<"all" | "video" | "image" | "audio">("all");
  const pick = useRef<HTMLInputElement>(null);
  const match = (s: string) => s.toLowerCase().includes(q.trim().toLowerCase());
  const items = useMemo(() => p.assets.filter((a) => (bin === "all" || a.kind === bin) && match(a.name)), [p.assets, bin, q]); // eslint-disable-line react-hooks/exhaustive-deps
  const hint = p.target ? <p className="lib-target text-xs">Applies to <b>{p.target}</b></p> : <p className="lib-target lib-target--none text-xs">Add a video to the timeline, then pick one.</p>;
  const search = <input className="input input--sm" type="search" placeholder="Search…" aria-label="Search" value={q} onChange={(e) => setQ(e.target.value)} />;

  return (
    <aside className="fx-lib" aria-label="Library">
      <div className="lib-rail" role="tablist" aria-label="Library sections">
        {TABS.map((t) => (
          <button key={t.id} type="button" role="tab" aria-selected={p.tab === t.id} className={`lib-tab${p.tab === t.id ? " on" : ""}`} onClick={() => p.onTab(t.id)}>
            <Icon d={t.icon} size={20} /><span>{t.label}</span>
          </button>
        ))}
      </div>
      <div className="lib-body" role="tabpanel">
        {p.tab === "media" && (
          <div className="stack gap">
            <input ref={pick} type="file" hidden multiple accept="video/*,image/*,audio/*,.mkv,.webm,.mov,.gif" onChange={(e) => { if (e.target.files) p.onUpload(e.target.files); e.target.value = ""; }} />
            <button type="button" className="import" onClick={() => pick.current?.click()}><Icon d={I.upload} size={22} /><b>Import</b><span className="text-xs">Click, or drag files into the window</span></button>
            <div className="row gap">{search}
              <select className="select select--sm" aria-label="Show" value={bin} onChange={(e) => setBin(e.target.value as typeof bin)}><option value="all">All</option><option value="video">Video</option><option value="image">Pictures</option><option value="audio">Audio</option></select></div>
            {items.length === 0 ? <p className="text-sm">{p.assets.length ? "Nothing matches." : "Your files appear here. Import a video, picture or song to begin."}</p> : (
              <ul className="media-grid">
                {items.map((a) => (
                  <li key={a.id}>
                    <button type="button" className="media-card" onClick={() => p.onAdd(a)} title={`Add “${a.name}” to the timeline`}>
                      <Thumb asset={a} /><span className="media-dur">{a.duration ? `${a.duration.toFixed(1)}s` : a.kind}</span><span className="media-add"><Icon d={I.plus} size={16} /></span>
                    </button>
                    <span className="media-name text-xs truncate">{a.name}</span>
                    {a.kind !== "audio" && <button type="button" className="bin-layer" onClick={() => p.onLayer(a)} title={`Add “${a.name}” on top of the video`}>+ Layer</button>}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
        {p.tab === "audio" && p.audioPanel}
        {p.tab === "text" && (
          <div className="stack gap">
            <Button icon={I.text} onClick={() => p.onText()}>Add default text</Button>
            <style>{TEXT_STYLES.map((s) => (s.patch.font ? `@font-face{font-family:"ltx-${s.patch.font}";src:url("${fontFileUrl(s.patch.font, !!s.patch.bold)}")}` : "")).join("")}</style>
            <div className="tile-grid">
              {TEXT_STYLES.map((s) => (
                <Tile key={s.id} label={s.label} onClick={() => p.onText(s)} hint={`Add a “${s.label}” title at the playhead`}>
                  <span className="text-sample" style={{
                    fontFamily: s.patch.font ? `"ltx-${s.patch.font}", system-ui` : "system-ui", fontWeight: s.patch.bold ? 700 : 400, color: s.patch.color ?? "#fff",
                    textTransform: s.patch.uppercase ? "uppercase" : "none", background: s.patch.box ? `${s.patch.box_color ?? "#000"}` : "transparent",
                    WebkitTextStroke: s.patch.stroke ? `1px ${s.patch.stroke_color ?? "#000"}` : undefined, textShadow: s.patch.glow ? `0 0 8px ${s.patch.glow_color ?? "#fff"}` : s.patch.shadow ? "1px 2px 3px #000a" : undefined,
                  }}>{s.label.length > 12 ? "Aa" : s.label}</span>
                </Tile>
              ))}
            </div>
          </div>
        )}
        {p.tab === "filters" && (
          <div className="stack gap">{hint}{search}
            {groupBy(cat.looks.filter((l) => match(l.label))).map(([g, list]) => (
              <section key={g} className="stack"><h4 className="lib-h">{g || "Looks"}</h4>
                <div className="tile-grid">{list.map((l) => <Tile key={l.id} label={l.label} on={p.currentLook === l.id && l.id !== "none"} onClick={() => p.onLook(l.id)}><Swatch look={l.id} /></Tile>)}</div></section>
            ))}
          </div>
        )}
        {p.tab === "effects" && (
          <div className="stack gap">{hint}{search}
            {groupBy(cat.effects.filter((l) => match(l.label))).map(([g, list]) => (
              <section key={g} className="stack"><h4 className="lib-h">{g || "Effects"}</h4>
                <div className="tile-grid">{list.map((l) => <Tile key={l.id} label={l.label} on={p.currentEffects.includes(l.id)} onClick={() => p.onEffect(l.id)} hint={p.currentEffects.includes(l.id) ? "Click to remove" : "Click to add"}><span className="fx-icon"><Icon d={I.sparkle} size={22} /></span></Tile>)}</div></section>
            ))}
          </div>
        )}
        {p.tab === "transitions" && (
          <div className="stack gap"><p className="lib-target text-xs">{p.target ? <>Plays between <b>{p.target}</b> and the next clip</> : "Add two clips, then pick one."}</p>{search}
            {groupBy(cat.transitions.filter((l) => match(l.label))).map(([g, list]) => (
              <section key={g} className="stack"><h4 className="lib-h">{g || "Transitions"}</h4>
                <div className="tile-grid">{list.map((l) => <Tile key={l.id} label={l.label} on={p.currentTransition === l.id && l.id !== "none"} onClick={() => p.onTransition(l.id)}><span className="trn-art"><b /><i /></span></Tile>)}</div></section>
            ))}
          </div>
        )}
      </div>
    </aside>
  );
}
