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

/** Every AI module: what is installed, the recommended version, older ones used before, and any other version on request. */
export function ModulesCard() {
  const { watchJob, toast } = useApp();
  const [rows, setRows] = useState<import("../lib/api").ModuleRow[] | null>(null);
  const [online, setOnline] = useState(true);
  const [pick, setPick] = useState<Record<string, string>>({});
  const [more, setMore] = useState<Record<string, string[]>>({});
  const [busy, setBusy] = useState("");
  const load = useCallback(() => api.moduleTable().then((r) => { setRows(r.modules); setOnline(r.online); }).catch(() => {}), []);
  useEffect(() => { void load(); }, [load]);
  if (!rows) return null;

  const showAll = async (name: string) => {
    setBusy(name);
    try { setMore({ ...more, [name]: (await api.moduleVersions(name)).versions }); } catch (e) { toast((e as Error).message, true); } finally { setBusy(""); }
  };
  const install = async (name: string) => {
    const v = pick[name];
    if (!v) return;
    setBusy(name);
    try {
      const j = await api.installModule(name, v);
      watchJob(j, (d) => { setBusy(""); toast(d.status === "done" ? `${name} ${v} installed. Close and open the app again to use it.` : d.error ?? "That did not work.", d.status !== "done"); void load(); });
    } catch (e) { setBusy(""); toast((e as Error).message, true); }
  };

  return (
    <section className="card stack gap" aria-labelledby="mods">
      <div className="stack"><h2 id="mods">AI modules and versions</h2>
        <p className="text-sm">These are the helper parts the app uses. You never have to touch them: “Update AI modules” above keeps them current. If a new version causes a problem, pick an older one here.</p>
        {!online && <p className="text-xs" role="status">You are offline, so the recommended versions are not shown.</p>}</div>
      <ul className="mod-list">
        {rows.map((r) => {
          const options = Array.from(new Set([...(r.recommended ? [r.recommended] : []), ...r.previous, ...(more[r.name] ?? [])])).filter((v) => v !== r.installed);
          return (
            <li key={r.name} className="mod-row">
              <div className="stack grow"><span className="w-medium">{r.label}</span><span className="text-xs mono">{r.name} · {r.installed ? `version ${r.installed}` : "not installed"}{r.recommended ? ` · recommended ${r.recommended}${r.installed === r.recommended ? " ✓" : ""}` : ""}</span></div>
              <select className="select mod-select" aria-label={`Version of ${r.label}`} value={pick[r.name] ?? ""} onChange={(e) => setPick({ ...pick, [r.name]: e.target.value })}>
                <option value="">Choose a version…</option>
                {options.map((v) => <option key={v} value={v}>{v}{v === r.recommended ? " (recommended)" : r.previous.includes(v) ? " (used before)" : ""}</option>)}
              </select>
              <Button variant="ghost" small busy={busy === r.name && !more[r.name]} onClick={() => showAll(r.name)} disabled={!!more[r.name]}>{more[r.name] ? "All shown" : "Show all"}</Button>
              <Button small variant="secondary" busy={busy === r.name} disabled={!pick[r.name]} onClick={() => install(r.name)}>Install</Button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
