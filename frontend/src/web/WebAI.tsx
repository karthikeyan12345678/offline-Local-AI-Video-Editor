import { useEffect, useState } from "react";
import { Button } from "../ds";
import { complete, currentConfig, listModels, loadSaved, PRESETS, savePatch } from "../../../shared/web/llm";
import QuotaMeter from "./QuotaMeter";

/** Choose the free AI that powers the chat, paste its key (kept only in this browser) and watch the free quota. */
export default function WebAI() {
  const saved = loadSaved();
  const [provider, setProvider] = useState(saved.provider || "groq");
  const [model, setModel] = useState(saved.providers[saved.provider || "groq"]?.model ?? "");
  const [key, setKey] = useState("");
  const [base, setBase] = useState(saved.providers[saved.provider || "groq"]?.base_url ?? "");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [models, setModels] = useState<string[]>([]);
  const p = PRESETS[provider];
  const have = !!loadSaved().providers[provider]?.api_key;

  useEffect(() => { const s = loadSaved().providers[provider]; setModel(s?.model ?? ""); setBase(s?.base_url ?? ""); setKey(""); setMsg(null); setModels([]); }, [provider]);

  const save = async (test: boolean) => {
    setBusy(true); setMsg(null);
    try {
      savePatch({ provider, providers: { [provider]: { model: model || p.model, ...(base ? { base_url: base } : {}), ...(key ? { api_key: key.trim() } : {}) } } });
      setKey("");
      if (test) { const r = await complete(currentConfig(), [{ role: "user", content: "Reply with the single word OK." }], ""); setMsg({ ok: true, text: `Works. The AI answered: ${r.slice(0, 60)}` }); }
      else setMsg({ ok: true, text: "Saved in this browser." });
    } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "That did not work." }); } finally { setBusy(false); }
  };

  return (
    <div className="web-page stack gap">
      <h1>AI helper and free credits</h1>
      <p>The chat in the editor (“make it vertical”, “add a title”, “remove the background”) needs an AI. These services have a <b>free plan with no card</b>, and the allowance <b>renews on its own</b>. Pick one, create a free key on its website, paste it here.</p>
      <div className="card stack gap">
        <label className="field"><span>Which AI?</span>
          <select className="select" value={provider} onChange={(e) => setProvider(e.target.value)}>
            {Object.entries(PRESETS).map(([id, x]) => <option key={id} value={id}>{x.free ? "★ " : ""}{x.name}</option>)}
          </select></label>
        <p className="text-sm">{p.free && <span className="free-badge">free</span>} {p.help}</p>
        {p.needs_key && <label className="field"><span>Key {have && <em className="text-xs">(a key is saved in this browser; type a new one to replace it)</em>}</span>
          <input className="input" type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} placeholder="paste your key here" /></label>}
        <label className="field"><span>Model name</span>
          <input className="input" list="web-models" value={model} onChange={(e) => setModel(e.target.value)} placeholder={p.model} />
          <datalist id="web-models">{models.map((m) => <option key={m} value={m} />)}</datalist></label>
        {(provider === "custom" || provider === "ollama") && <label className="field"><span>Server address</span><input className="input" value={base} onChange={(e) => setBase(e.target.value)} placeholder={p.base_url || "https://…/v1"} /></label>}
        {msg && <p role={msg.ok ? "status" : "alert"} className={msg.ok ? "text-sm" : "error text-sm"}>{msg.text}</p>}
        <div className="row gap wrap">
          <Button busy={busy} onClick={() => save(true)}>Save and test</Button>
          <Button variant="secondary" disabled={busy} onClick={async () => { savePatch({ provider, providers: { [provider]: { ...(key ? { api_key: key.trim() } : {}) } } }); setModels(await listModels(currentConfig())); }}>Load model list</Button>
        </div>
        <p className="text-xs">Your key is stored only in this browser (never in the website’s files, never on GitHub). It is sent only to the AI service you chose. Anyone using this same browser profile can use it, so don’t save a key on a shared computer.</p>
      </div>

      <div className="card stack gap">
        <h2>Free usage meter</h2>
        <p className="text-sm">Counts the requests this browser made to <b>{p.name}</b> in the last 6, 12 and 24 hours and shows when they come back. The numbers are a guide, because the real limit is kept by the provider.</p>
        <QuotaMeter provider={provider} editable />
      </div>

      <div className="card stack gap">
        <h2>About fal.ai and paid video AI</h2>
        <p className="text-sm">fal.ai (the cloud video generator used by the desktop version) does <b>not</b> have a free plan that renews. A new account gets a one-time credit at most, and every video after that costs money, so it is left out of the browser version. Creating a fal.ai key is free, but using it spends credit.</p>
        <p className="text-sm">Making brand-new AI video needs a powerful graphics card, which a website on GitHub or Netlify does not have. Editing, effects, sounds, text, captions by hand and the AI chat all work here for free.</p>
      </div>
    </div>
  );
}
