import { useEffect, useState } from "react";
import { useApp } from "../lib/store";
import { Button, Field } from "../ds";
import { ModelList } from "./Models";
import UpdatesCard, { ModulesCard } from "./Updates";
import SmartInstall from "./SmartInstall";

function LookCard() {
  const [look, setLook] = useState<string>(() => document.documentElement.dataset.look === "studio" ? "studio" : "classic");
  const pick = (v: "classic" | "studio") => {
    setLook(v);
    if (v === "studio") document.documentElement.dataset.look = "studio"; else delete document.documentElement.dataset.look;
    try { localStorage.setItem("vk_look", v); } catch { /* ignore */ }
  };
  return (
    <section className="card stack gap" aria-labelledby="look">
      <h2 id="look">Look</h2>
      <div className="row gap wrap">
        <Button variant={look === "classic" ? "primary" : "secondary"} small onClick={() => pick("classic")}>Classic (light)</Button>
        <Button variant={look === "studio" ? "primary" : "secondary"} small onClick={() => pick("studio")}><span className="look-swatch" />Studio (dark, default)</Button>
      </div>
    </section>
  );
}

const MEMORY = [
  ["auto", "Automatic (recommended)"], ["none", "Keep everything on the GPU (fastest, needs lots of VRAM)"], ["model", "Move whole parts to the GPU as needed"],
  ["group", "Move small blocks as needed (low VRAM)"], ["sequential", "Move layer by layer (lowest VRAM, slowest)"],
];

export default function Settings() {
  const { system, limits, settings, setSettings, toast } = useApp();
  const [endpoint, setEndpoint] = useState("");
  useEffect(() => { if (settings) setEndpoint(settings.hf_endpoint); }, [settings]);
  if (!system || !limits || !settings) return null;
  const g = system.gpu;
  const endpointBad = !/^https?:\/\/\S+$/.test(endpoint);

  return (
    <main className="page narrow stack gap-lg">
      <h1>Settings</h1>

      <LookCard />
      <UpdatesCard />
      <ModulesCard />
      <SmartInstall compact />

      <section className="card stack gap" aria-labelledby="sys">
        <h2 id="sys">This PC</h2>
        <dl className="kv text-sm">
          <dt>Graphics card</dt><dd>{g.name ? `${g.name} · ${g.vram_gb} GB${g.available ? " (switched on)" : " (found, not switched on — see the install card above)"}` : "None detected"}</dd>
          <dt>Memory</dt><dd>{system.ram_gb} GB</dd>
          <dt>Free disk space</dt><dd>{system.disk_free_gb} GB</dd>
          <dt>Torch</dt><dd>{system.torch ?? "not installed"}</dd>
          <dt>Data folder</dt><dd className="mono">{system.data_dir}</dd>
          <dt>Version</dt><dd>{system.version}</dd>
        </dl>
        {g.problem && <p className="error-text" role="alert">{g.problem}</p>}
        {system.warnings.map((w) => <p key={w} className="text-sm">{w}</p>)}
      </section>

      <section className="card stack gap" aria-labelledby="gen">
        <h2 id="gen">Generation</h2>
        <Field label="Hardware profile" htmlFor="profile" hint={limits.profiles.find((p) => p.id === (settings.profile === "auto" ? limits.profile.id : settings.profile))?.description}>
          <select id="profile" className="select" value={settings.profile} onChange={(e) => setSettings({ profile: e.target.value })}>
            <option value="auto">Automatic — currently “{limits.profile.label}”</option>
            {limits.profiles.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
          </select>
        </Field>
        <Field label="Memory saving" htmlFor="mem" hint="If generation stops with an out-of-memory message, the app retries with a lower-memory mode by itself.">
          <select id="mem" className="select" value={settings.memory_mode} onChange={(e) => setSettings({ memory_mode: e.target.value })}>
            {MEMORY.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </Field>
        <Field label="Number precision" htmlFor="dt" hint="Leave on automatic unless you see black or broken frames.">
          <select id="dt" className="select" value={settings.compute_dtype} onChange={(e) => setSettings({ compute_dtype: e.target.value })}>
            <option value="auto">Automatic</option><option value="bf16">bf16</option><option value="fp16">fp16</option><option value="fp32">fp32 (slow)</option>
          </select>
        </Field>
        <Field label="Default model" htmlFor="dm">
          <select id="dm" className="select" value={settings.default_model} onChange={(e) => setSettings({ default_model: e.target.value })}>
            {limits.models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
          </select>
        </Field>
        <Field label="Frames per second of new videos" htmlFor="fps">
          <input id="fps" className="input" type="number" min={8} max={60} value={settings.output_fps} onChange={(e) => setSettings({ output_fps: Number(e.target.value) || 24 })} />
        </Field>
        <label className="check"><input type="checkbox" checked={settings.keep_loaded} onChange={(e) => setSettings({ keep_loaded: e.target.checked })} />Keep the model in memory between videos (faster next time, uses more memory)</label>
      </section>

      <section className="stack gap" aria-labelledby="mod">
        <h2 id="mod">Models</h2>
        <Field label="Download server" htmlFor="ep" error={endpointBad ? "Enter a web address starting with https://" : null}
          hint="Change this only if huggingface.co is blocked on your network. A mirror such as https://hf-mirror.com works.">
          <div className="row gap">
            <input id="ep" className="input" value={endpoint} aria-invalid={endpointBad} onChange={(e) => setEndpoint(e.target.value)} />
            <Button variant="secondary" disabled={endpointBad || endpoint === settings.hf_endpoint} onClick={() => { setSettings({ hf_endpoint: endpoint }); toast("Download server saved."); }}>Save</Button>
          </div>
        </Field>
        <ModelList />
      </section>
    </main>
  );
}
