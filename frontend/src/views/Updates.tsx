import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import { useApp } from "../lib/store";
import { Button, I } from "../ds";
import type { UpdateInfo } from "../lib/types";

/** Looks for a newer app and newer AI modules; updating modules is one button. */
export function useUpdateCheck(auto: boolean) {
  const [info, setInfo] = useState<UpdateInfo | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const check = useCallback(async () => {
    setBusy(true); setError("");
    try { setInfo(await api.updates()); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }, []);
  useEffect(() => { if (auto) void check(); }, [auto, check]);
  return { info, error, busy, check };
}

export default function UpdatesCard() {
  const { watchJob, toast } = useApp();
  const { info, error, busy, check } = useUpdateCheck(true);
  const [installing, setInstalling] = useState(false);
  const [restart, setRestart] = useState(false);

  const install = async () => {
    setInstalling(true);
    try {
      const j = await api.updateModules();
      watchJob(j, (d) => {
        setInstalling(false);
        if (d.status === "done") { setRestart(!!d.result?.restart); toast(d.result?.restart ? "AI modules updated. Close and open the app again to use them." : "Everything is already up to date."); void check(); }
      });
    } catch (e) { setInstalling(false); toast((e as Error).message, true); }
  };

  return (
    <section className="card stack gap" aria-labelledby="upd">
      <div className="row between gap"><h2 id="upd">Updates</h2><Button variant="secondary" small busy={busy} onClick={check}>Check now</Button></div>
      {error && <p className="text-sm" role="status">{error}</p>}
      {info && (
        <>
          <p className="text-sm">You have version <b>{info.current}</b>.{info.app_update ? <> Version <b>{info.latest}</b> is available. {info.notes}</> : " This is the newest version."}</p>
          {info.app_update && <a className="btn" href={info.download_url} target="_blank" rel="noreferrer">Download the new version</a>}
          {info.modules.length > 0 && (
            <details>
              <summary className="text-sm">AI modules ({info.modules.filter((m) => m.update).length} can be updated)</summary>
              <ul className="text-xs">{info.modules.map((m) => <li key={m.name}>{m.name}: {m.installed ?? "not installed"} → {m.latest}{m.update ? " (update)" : " ✓"}</li>)}</ul>
            </details>
          )}
          <div className="row gap wrap">
            <Button icon={I.download} busy={installing} disabled={!info.modules_update} onClick={install}>{info.modules_update ? "Update AI modules" : "AI modules are up to date"}</Button>
          </div>
          {restart && <p className="text-sm" role="status">Updated. Close VK Editor and open it again to finish.</p>}
        </>
      )}
    </section>
  );
}
