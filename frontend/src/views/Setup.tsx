import { api } from "../lib/api";
import { useApp } from "../lib/store";
import { Button, Icon, I } from "../ds";
import { ModelList } from "./Models";

function Check({ ok, title, detail }: { ok: boolean; title: string; detail: string }) {
  return (
    <div className="row gap start">
      <span className={`dot ${ok ? "dot--ok" : "dot--warn"}`} aria-hidden="true"><Icon d={ok ? I.check : I.alert} size={12} /></span>
      <div className="stack"><span className="w-medium">{title}</span><span className="text-sm">{detail}</span></div>
      <span className="sr-only">{ok ? "OK" : "Needs attention"}</span>
    </div>
  );
}

export default function Setup({ onSkip }: { onSkip: () => void }) {
  const { system, limits, models, toast, refreshModels } = useApp();
  if (!system || !limits) return null;
  const g = system.gpu;
  const base = models.find((m) => m.kind === "base");
  const chosen = models.find((m) => m.id === limits.default_model);

  const startAll = async () => {
    try {
      for (const m of [base, chosen]) if (m && !m.installed && !["running", "queued"].includes(m.download.status)) await api.download(m.id);
      await refreshModels();
    } catch (e) { toast((e as Error).message, true); }
  };

  return (
    <main className="page narrow stack gap-lg">
      <div className="stack">
        <h1>Welcome to LTX Portable Studio</h1>
        <p>Make short videos from text or pictures on this PC, then edit them. Nothing is uploaded; everything runs here.</p>
      </div>
      <section className="card stack gap" aria-labelledby="chk">
        <h2 id="chk">This PC</h2>
        <Check ok={g.available && g.arch_supported} title={g.available ? `${g.name} · ${g.vram_gb} GB video memory` : "No NVIDIA graphics card found"}
          detail={g.available ? (g.problem ?? `Using the “${limits.profile.label}” settings: up to ${limits.profile.max_frames} frames at ${limits.profile.max_side}px.`) : "Videos can still be made on the processor, but very slowly. Editing works normally."} />
        <Check ok={system.ffmpeg} title="Video tools" detail={system.ffmpeg ? "Ready." : "ffmpeg was not found. Editing and exporting will not work."} />
        <Check ok={system.disk_free_gb >= 15} title={`${system.disk_free_gb} GB free on this drive`} detail="The model files are large; press “Check size” on each below to see exactly how much. Videos you make need space too." />
        <Check ok={!system.low_ram} title={`${system.ram_gb} GB of memory`} detail={system.low_ram ? "Less than 12 GB. Generation may be slow or fail; close other programs first." : "Enough for the lowest-memory mode."} />
        {system.warnings.map((w) => <Check key={w} ok={false} title="Note" detail={w} />)}
      </section>
      <section className="stack gap" aria-labelledby="mdl">
        <div className="stack"><h2 id="mdl">Download the model files</h2><p className="text-sm">One time only. They are saved in the app’s data folder; copy that folder to another PC to skip the download there.</p></div>
        <ModelList />
        <div className="row gap">
          <Button icon={I.download} onClick={startAll}>Download everything needed</Button>
          <Button variant="ghost" onClick={onSkip}>Skip — I only want to edit</Button>
        </div>
      </section>
    </main>
  );
}
