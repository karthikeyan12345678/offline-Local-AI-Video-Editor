import { useMemo, useState } from "react";
import FontSample from "./FontSample";
import { useCatalog } from "./catalog";

const SCRIPT_SAMPLE: Record<string, string> = { tamil: "வணக்கம் தமிழ்", devanagari: "नमस्ते हिन्दी", telugu: "తెలుగు నమస్కారం", kannada: "ಕನ್ನಡ ನಮಸ್ಕಾರ", malayalam: "മലയാളം നമസ്കാരം", bengali: "বাংলা নমস্কার" };
const sampleFor = (label: string, scripts: string[]) => { const s = scripts.find((x) => SCRIPT_SAMPLE[x]); return s ? SCRIPT_SAMPLE[s] : label; };

/** Search-and-pick list of the bundled fonts, each drawn in its own letters. */
export default function FontPicker({ value, bold, onChange }: { value: string; bold: boolean; onChange: (id: string) => void }) {
  const { fonts } = useCatalog();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("All");
  const cats = useMemo(() => ["All", ...Array.from(new Set(fonts.map((f) => f.category)))], [fonts]);
  const shown = useMemo(() => fonts.filter((f) => (cat === "All" || f.category === cat) && f.label.toLowerCase().includes(q.toLowerCase())), [fonts, cat, q]);
  const current = fonts.find((f) => f.id === value);
  return (
    <div className="stack gap fontpick">
      <button type="button" className="select fontpick-current" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        {current ? <FontSample id={current.id} label={current.label} text={sampleFor(current.label, current.scripts)} bold={bold} height={36} /> : <span>Automatic</span>}
        <span className="text-xs">{current ? current.category : "pick a font"} ▾</span>
      </button>
      {open && (
        <div className="fontpick-panel stack gap">
          <input className="input" type="search" placeholder="Search fonts…" aria-label="Search fonts" value={q} onChange={(e) => setQ(e.target.value)} />
          <div className="row gap wrap" role="group" aria-label="Font category">
            {cats.map((c) => <button type="button" key={c} className={`chip${c === cat ? " chip--on" : ""}`} aria-pressed={c === cat} onClick={() => setCat(c)}>{c}</button>)}
          </div>
          <ul className="fontlist" role="listbox" aria-label="Fonts">
            <li><button type="button" role="option" aria-selected={value === ""} className={`fontrow${value === "" ? " on" : ""}`} onClick={() => { onChange(""); setOpen(false); }}>Automatic (best for the language)</button></li>
            {shown.map((f) => (
              <li key={f.id}>
                <button type="button" role="option" aria-selected={f.id === value} className={`fontrow${f.id === value ? " on" : ""}`} onClick={() => { onChange(f.id); setOpen(false); }} title={f.label}>
                  <FontSample id={f.id} label={f.label} text={sampleFor(f.label, f.scripts)} bold={bold} height={40} />
                  <span className="text-xs">{f.label}</span>
                </button>
              </li>
            ))}
            {shown.length === 0 && <li className="text-sm">No fonts match.</li>}
          </ul>
        </div>
      )}
    </div>
  );
}
