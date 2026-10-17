import { useEffect, useState } from "react";
import { fmtWait, limitFor, meter, setLimit, UNITS } from "../../../shared/web/quota";

/** Requests used in the last 6 / 12 / 24 hours, and when each window renews. Counted in this browser only. */
export default function QuotaMeter({ provider, editable = false }: { provider: string; editable?: boolean }) {
  const [, tick] = useState(0);
  useEffect(() => {
    const on = () => tick((n) => n + 1);
    window.addEventListener("vk-quota", on);
    const t = setInterval(on, 30000);
    return () => { window.removeEventListener("vk-quota", on); clearInterval(t); };
  }, []);
  const rows = provider === "zerogpu" ? meter(provider).filter((r) => r.hours === 24) : meter(provider); // the free GPU has one daily pot
  const day = limitFor(provider);
  return (
    <div className="stack gap" aria-label="Free usage meter">
      {rows.map((r) => {
        const pct = r.limit ? Math.min(100, Math.round((r.used / r.limit) * 100)) : 0;
        return (
          <div key={r.hours} className="meter">
            <span>{r.hours} h</span>
            <div className={`meter-bar${pct >= 100 ? " meter-bar--out" : pct >= 80 ? " meter-bar--warn" : ""}`} role="progressbar" aria-valuemin={0} aria-valuemax={r.limit || undefined} aria-valuenow={r.used}>
              <span style={{ width: `${r.limit ? pct : r.used ? 8 : 0}%` }} />
            </div>
            <span className="text-xs">{r.limit ? `${r.used} / ${r.limit}${UNITS[provider] ? " " + UNITS[provider] : ""} used` : `${r.used}${UNITS[provider] ? " " + UNITS[provider] : ""} used`}{r.renewsInMs != null && (r.limit ? r.left === 0 : false) ? ` · back in ${fmtWait(r.renewsInMs)}` : r.renewsInMs != null ? ` · oldest renews in ${fmtWait(r.renewsInMs)}` : ""}</span>
          </div>
        );
      })}
      {editable && (
        <label className="field"><span>{provider === "zerogpu" ? "Free GPU seconds per day (about 300 with a free Hugging Face account; 0 = don’t count)" : "Free requests per day (check your provider’s page and type your own number; 0 = don’t count)"}</span>
          <input className="input" type="number" min={0} value={day} onChange={(e) => setLimit(provider, Number(e.target.value) || 0)} /></label>
      )}
    </div>
  );
}
