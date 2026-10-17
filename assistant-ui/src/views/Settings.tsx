import { IS_WEB } from "../lib/env";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { Info, SettingsData, ThemeInfo } from "../lib/types";
import { Banner, Button, Spinner, errText } from "../ui";
import AdvisorDialog from "../AdvisorDialog";

export default function Settings() {
  const [info, setInfo] = useState<Info | null>(null);
  const [s, setS] = useState<SettingsData | null>(null);
  const [themes, setThemes] = useState<ThemeInfo[]>([]);
  const [key, setKey] = useState("");
  const [imgKey, setImgKey] = useState("");
  const [models, setModels] = useState<string[]>([]);
  const [msg, setMsg] = useState<{ kind: "info" | "error"; text: string } | null>(null);
  const [busy, setBusy] = useState("");
  const [adv, setAdv] = useState(false);

  useEffect(() => { void Promise.all([api.info(), api.settings(), api.themes()]).then(([i, st, t]) => { setInfo(i); setS(st); setThemes(t.themes); }).catch((e) => setMsg({ kind: "error", text: errText(e) })); }, []);
  if (!info || !s) return <div className="page">{msg ? <Banner kind="error">{msg.text}</Banner> : <Spinner />}</div>;

  const prov = s.provider;
  const preset = info.providers[prov];
  const cur = s.providers[prov] ?? {};
  const img = (s.image.provider as string) ?? "horde";
  const imgPreset = info.image_providers[img];
  const imgCur = (s.image[img] ?? {}) as { base_url?: string; model?: string; api_key_hint?: string };
  const patchProv = (p: Partial<{ base_url: string; model: string }>) => setS({ ...s, providers: { ...s.providers, [prov]: { ...cur, ...p } } });
  const patchImg = (p: Partial<{ base_url: string; model: string }>) => setS({ ...s, image: { ...s.image, [img]: { ...imgCur, ...p } } });

  const save = async (): Promise<boolean> => {
    setBusy("save"); setMsg(null);
    try {
      const patch = {
        provider: prov, default_theme: s.default_theme, system_prompt: s.system_prompt,
        providers: { [prov]: { base_url: cur.base_url ?? preset.base_url, model: cur.model ?? preset.model, ...(key ? { api_key: key } : {}) } },
        image: { provider: img, [img]: { base_url: imgCur.base_url ?? imgPreset.base_url, model: imgCur.model ?? imgPreset.model, ...(imgKey ? { api_key: imgKey } : {}) } },
      };
      setS(await api.saveSettings(patch)); setKey(""); setImgKey("");
      setMsg({ kind: "info", text: "Settings saved." });
      return true;
    } catch (e) { setMsg({ kind: "error", text: errText(e) }); return false; } finally { setBusy(""); }
  };
  const test = async () => { if (!(await save())) return; setBusy("test"); try { const r = await api.testLlm(); setMsg({ kind: "info", text: `Connected. The model replied: “${r.reply}”` }); } catch (e) { setMsg({ kind: "error", text: errText(e) }); } finally { setBusy(""); } };
  const loadModels = async () => { if (!(await save())) return; setBusy("models"); try { const r = await api.models(); setModels(r.models); setMsg({ kind: "info", text: `${r.models.length} models found.` }); } catch (e) { setMsg({ kind: "error", text: errText(e) }); } finally { setBusy(""); } };

  return (
    <div className="page">
      <header><h1>Settings</h1><p className="muted">Choose which AI answers your chat and which engine makes images. Keys are stored on {IS_WEB ? "this browser" : "this PC"} only and are never shown again after saving.</p></header>
      {msg && <Banner kind={msg.kind} onClose={() => setMsg(null)}>{msg.text}</Banner>}
      {adv && <AdvisorDialog load={api.advice} onClose={() => setAdv(false)} onPick={(id, model) => { setS({ ...s, provider: id, providers: { ...s.providers, [id]: { ...(s.providers[id] ?? {}), model } } }); setKey(""); setModels([]); setAdv(false); setMsg({ kind: "info", text: info.providers[id]?.needs_key ? `Selected ${info.providers[id].name}. Paste your key below, then press “Save and test”.` : `Selected ${info.providers[id]?.name ?? id}. Press “Save and test”.` }); }} />}
      <section className="card stack">
        <div className="row between"><h2>Chat model</h2><Button variant="secondary" onClick={() => setAdv(true)}>Help me choose the best AI for my PC</Button></div>
        <div className="field"><label htmlFor="prov">Provider</label>
          <select id="prov" className="select" value={prov} onChange={(e) => { setS({ ...s, provider: e.target.value }); setKey(""); setModels([]); }}>
            {Object.entries(info.providers).map(([id, p]) => <option key={id} value={id}>{p.name}</option>)}</select>
          <span className="hint">{preset.help}</span></div>
        <div className="two">
          <div className="field"><label htmlFor="url">Server address</label><input id="url" className="input" value={cur.base_url ?? preset.base_url} onChange={(e) => patchProv({ base_url: e.target.value })} /></div>
          <div className="field"><label htmlFor="model">Model</label>
            <input id="model" className="input" list="models" value={cur.model ?? preset.model} onChange={(e) => patchProv({ model: e.target.value })} />
            <datalist id="models">{models.map((m) => <option key={m} value={m} />)}</datalist></div>
        </div>
        <div className="field"><label htmlFor="key">API key {preset.needs_key ? "" : "(optional)"}</label>
          <input id="key" className="input" type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} placeholder={cur.api_key_hint ? `Saved: ${cur.api_key_hint} (leave blank to keep)` : preset.needs_key ? "Paste your key" : "Not needed for most local servers"} /></div>
        <div className="row"><Button busy={busy === "save"} onClick={() => void save()}>Save</Button><Button variant="secondary" busy={busy === "test"} onClick={() => void test()}>Save and test</Button><Button variant="secondary" busy={busy === "models"} onClick={() => void loadModels()}>List models</Button></div>
      </section>
      <section className="card stack">
        <h2>Image engine</h2>
        <div className="field"><label htmlFor="iprov">Engine</label>
          <select id="iprov" className="select" value={img} onChange={(e) => setS({ ...s, image: { ...s.image, provider: e.target.value } })}>
            {Object.entries(info.image_providers).map(([id, p]) => <option key={id} value={id}>{p.name}</option>)}</select>
          <span className="hint">{imgPreset.help}</span></div>
        {img === "local" && !info.local_image.available && <Banner>{info.local_image.reason}</Banner>}
        {img !== "local" && <>
          <div className="two">
            <div className="field"><label htmlFor="iurl">Server address</label><input id="iurl" className="input" value={imgCur.base_url ?? imgPreset.base_url} onChange={(e) => patchImg({ base_url: e.target.value })} /></div>
            <div className="field"><label htmlFor="imodel">Model</label><input id="imodel" className="input" value={imgCur.model ?? imgPreset.model} onChange={(e) => patchImg({ model: e.target.value })} /></div>
          </div>
          {imgPreset.needs_key && <div className="field"><label htmlFor="ikey">API key</label><input id="ikey" className="input" type="password" autoComplete="off" value={imgKey} onChange={(e) => setImgKey(e.target.value)} placeholder={imgCur.api_key_hint ? `Saved: ${imgCur.api_key_hint} (leave blank to keep)` : "Paste your key"} /></div>}</>}
        <div className="row"><Button busy={busy === "save"} onClick={() => void save()}>Save</Button></div>
      </section>
      <section className="card stack">
        <h2>Files and behaviour</h2>
        <div className="field"><label htmlFor="dt">Default design for new files</label>
          <select id="dt" className="select" value={s.default_theme} onChange={(e) => setS({ ...s, default_theme: e.target.value })}>{themes.map((t) => <option key={t.id} value={t.id}>{t.name} ({t.category})</option>)}</select></div>
        <div className="field"><label htmlFor="sp">Extra instructions for the assistant (optional)</label>
          <textarea id="sp" className="textarea" value={s.system_prompt} onChange={(e) => setS({ ...s, system_prompt: e.target.value })} placeholder="For example: Answer in British English. Keep replies short." /></div>
        <div className="row"><Button busy={busy === "save"} onClick={() => void save()}>Save</Button></div>
      </section>
      <div className="row"><Button variant="secondary" onClick={() => { try { localStorage.removeItem("aia_tour_done"); } catch { /* ignore */ } location.reload(); }}>Take the tour</Button></div>
      <p className="hint">AI Assistant {info.version} · {info.themes} designs · File creation, comparison, resume check and analysis run fully on {IS_WEB ? "this browser" : "this PC"}; only chat and (optionally) image requests go to the service you choose.</p>
    </div>
  );
}
