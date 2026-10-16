import { useApp } from "../lib/store";
import { Button, Icon, I } from "../ds";
import { ModelList } from "./Models";
import SmartInstall from "./SmartInstall";

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
  const { system, limits } = useApp();
  if (!system || !limits) return null;
  const g = system.gpu;

  return (
    <main className="page narrow stack gap-lg">
      <div className="row gap center-v">
        <img src="/logo.png" alt="" width={56} height={56} style={{ borderRadius: 14 }} />
        <div className="stack">
          <h1>Welcome to VK Editor</h1>
          <p>Make videos from words or pictures, then edit them. Everything runs on this PC. Nothing is uploaded.</p>
        </div>
      </div>

      <SmartInstall />

      <section className="card stack gap" aria-labelledby="chk">
        <h2 id="chk">Your PC</h2>
        <Check ok={g.available && g.arch_supported !== false} title={g.available ? `${g.name} · ${g.vram_gb} GB video memory` : "No NVIDIA graphics card found"}
          detail={g.available ? (g.problem ?? `Using the “${limits.profile.label}” settings: up to ${limits.profile.max_frames} frames at ${limits.profile.max_side}px.`) : "Videos can still be made on the processor, but very slowly. Editing works normally."} />
        <Check ok={system.ffmpeg} title="Video tools" detail={system.ffmpeg ? "Ready." : "ffmpeg was not found. Editing and exporting will not work."} />
        <Check ok={system.disk_free_gb >= 15} title={`${system.disk_free_gb} GB free on this drive`} detail="The AI parts are large. Videos you make need space too." />
        <Check ok={!system.low_ram} title={`${system.ram_gb} GB of memory`} detail={system.low_ram ? "Less than 12 GB. Generation may be slow or fail; close other programs first." : "Enough for the lowest-memory mode."} />
        {system.warnings.map((w) => <Check key={w} ok={false} title="Note" detail={w} />)}
      </section>

      <details className="card">
        <summary className="w-medium">Advanced: choose each model yourself</summary>
        <div className="stack gap" style={{ marginTop: "var(--space-6)" }}>
          <p className="text-sm">Most people never need this. You can also copy the app’s data folder to another PC to skip the download there.</p>
          <ModelList />
        </div>
      </details>
      <div className="row"><Button variant="ghost" onClick={onSkip}>Skip for now — I only want to edit</Button></div>
    </main>
  );
}
