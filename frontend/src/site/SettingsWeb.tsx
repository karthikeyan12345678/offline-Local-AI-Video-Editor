import { useEffect, useState } from "react";
import { Button, Tabs } from "../ds";
import WebAI from "../web/WebAI";
import QuotaMeter from "../web/QuotaMeter";
import { webCall } from "../web/backend";
import { DEFAULT_SPACES, loadHF, saveHF } from "../web/hf";
import { currentProfile } from "../../../shared/web/account";
import { config } from "../../../shared/web/config";
import { reconnectDrive, signOut } from "../../../shared/web/auth";
import { syncNow } from "../../../shared/web/drive";

type Tab = "gpu" | "chat" | "account" | "data";

function GpuSettings() {
  const [c, setC] = useState(loadHF());
  const [token, setToken] = useState("");
  const [msg, setMsg] = useState("");
  const [st, setSt] = useState<{ ltx: { text: string; ok: boolean }; animate: { text: string; ok: boolean } } | null>(null);
  const [busy, setBusy] = useState(false);
  const save = () => {
    const n = saveHF({ ...(token.trim() ? { token: token.trim() } : {}), ltx: c.ltx.trim() || DEFAULT_SPACES.ltx, animate: c.animate.trim() || DEFAULT_SPACES.animate });
    setC(n); setToken(""); setMsg("Saved in this browser.");
  };
  const check = async () => { setBusy(true); try { setSt(await webCall("GET", "/web/hf/status")); } finally { setBusy(false); } };
  return (
    <div className="stack gap">
      <div className="card stack gap">
        <h2>Free GPU for AI video</h2>
        <p className="text-sm">Text to video, picture to video, continue a clip and motion control run on <b>Hugging Face Spaces</b>: free graphics cards (“ZeroGPU”) that Hugging Face shares. A free Hugging Face account gets about <b>5 minutes of GPU time a day</b> (2 minutes with no account), and it renews by itself about 24 hours after you first used it. The numbers are Hugging Face’s and can change.</p>
        <ol className="text-sm">
          <li>Create a free account at <a href="https://huggingface.co/join" target="_blank" rel="noreferrer">huggingface.co/join</a>.</li>
          <li>Open <a href="https://huggingface.co/settings/tokens" target="_blank" rel="noreferrer">Settings → Access Tokens</a> → <b>Create new token</b> → type <b>Read</b> → copy it (it starts with <code>hf_</code>).</li>
          <li>Paste it below and press Save. It stays in this browser only and is sent only to Hugging Face.</li>
        </ol>
        <label className="field"><span>Hugging Face token {c.token && <em className="text-xs">(a token is saved; type a new one to replace it)</em>}</span>
          <input className="input" type="password" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)} placeholder="hf_…" /></label>
        <details><summary className="text-sm">Choose other Spaces (advanced)</summary>
          <div className="stack gap" style={{ marginTop: 8 }}>
            <label className="field"><span>Text, picture and continue (LTX video)</span><input className="input" value={c.ltx} onChange={(e) => setC({ ...c, ltx: e.target.value })} placeholder={DEFAULT_SPACES.ltx} /></label>
            <label className="field"><span>Motion control (Wan 2.2 Animate)</span><input className="input" value={c.animate} onChange={(e) => setC({ ...c, animate: e.target.value })} placeholder={DEFAULT_SPACES.animate} /></label>
            <p className="text-xs muted">Spaces are run by other people and can be paused or changed. If one stops working, paste another with the same inputs here (a duplicate of the Space on your own free account works too).</p>
          </div></details>
        {msg && <p className="text-sm" role="status">{msg}</p>}
        <div className="row gap wrap"><Button onClick={save}>Save</Button><Button variant="secondary" busy={busy} onClick={() => void check()}>Check the Spaces are awake</Button></div>
        {st && <ul className="text-sm"><li><b>Video:</b> {st.ltx.text}</li><li><b>Motion control:</b> {st.animate.text}</li></ul>}
      </div>
      <div className="card stack gap"><h2>Free GPU time (estimate)</h2><QuotaMeter provider="zerogpu" editable /><p className="text-xs muted">Counted from the jobs this browser sent. The real balance is on <a href="https://huggingface.co/settings/billing" target="_blank" rel="noreferrer">your Hugging Face billing page</a>.</p></div>
    </div>
  );
}

function Account() {
  const me = currentProfile();
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <div className="card stack gap">
      <h2>Account</h2>
      <div className="row gap center-v">{me?.picture ? <img className="avatar" src={me.picture} alt="" width={48} height={48} referrerPolicy="no-referrer" /> : <span className="avatar avatar--blank" aria-hidden="true">{(me?.name ?? "G").slice(0, 1)}</span>}
        <div className="stack"><b>{me?.name}</b><span className="text-sm muted">{me?.guest ? "Guest (this browser only)" : me?.email}</span></div></div>
      {!me?.guest && <>
        <p className="text-sm">Signed in with Google. Your projects and history live in a database of this browser that belongs to your account{me?.driveOk ? ", and are copied to a private folder in your Google Drive" : ""}. This is not a password lock: anyone who can open this browser profile can open it, so sign out on shared computers.</p>
        {me?.driveOk && <div className="row gap wrap center-v"><Button variant="secondary" busy={busy} onClick={async () => { setBusy(true); try { if (!(await reconnectDrive())) { setMsg("Drive permission was not given."); } else { const r = await syncNow(); setMsg(r.message); } } catch (e) { setMsg(e instanceof Error ? e.message : "Could not sync."); } finally { setBusy(false); } }}>Reconnect Drive and sync</Button><span className="text-sm" role="status">{msg}</span></div>}
      </>}
      <div><Button variant="secondary" onClick={() => { signOut(); location.hash = "#/"; location.reload(); }}>{me?.guest ? "Leave guest mode" : "Sign out"}</Button></div>
    </div>
  );
}

function Data() {
  const [msg, setMsg] = useState("");
  const wipe = async () => {
    if (!confirm("Delete ALL files, projects and history stored by this website in this browser for this account? This cannot be undone. (Your Google Drive copy is not touched.)")) return;
    const dbs = (await indexedDB.databases?.()) ?? [];
    const me = currentProfile();
    for (const d of dbs) if (d.name && d.name.startsWith("vkeditor-web") && (me?.guest ? d.name === "vkeditor-web" : d.name.endsWith(me?.sub.replace(/[^a-zA-Z0-9_-]/g, "") ?? "∅"))) indexedDB.deleteDatabase(d.name);
    setMsg("Deleted. Reloading…"); setTimeout(() => location.reload(), 800);
  };
  const keys = async () => { try { for (const k of ["vk_llm_v1", "vk_hf_v1", "vk_quota_v1"]) localStorage.removeItem(k); setMsg("All saved keys were removed from this browser."); window.dispatchEvent(new Event("vk-llm")); window.dispatchEvent(new Event("vk-hf")); } catch { setMsg("Could not clear."); } };
  return (
    <div className="card stack gap">
      <h2>Data and privacy</h2>
      <ul className="text-sm"><li>Videos, pictures and sounds you add stay in this browser (IndexedDB). They are never uploaded to this website.</li>
        <li>Only what you send on purpose leaves your computer: chat messages to the AI you chose, and pictures/videos to the Hugging Face Space when you press Generate.</li>
        <li>Keys you paste are saved only in this browser, never in the site’s files or on GitHub.</li></ul>
      {msg && <p className="text-sm" role="status">{msg}</p>}
      <div className="row gap wrap"><Button variant="secondary" onClick={() => void keys()}>Remove my saved keys</Button><Button variant="secondary" onClick={() => void wipe()}>Delete all my data in this browser</Button></div>
      <p className="text-xs muted">Site: {config().webRepo.replace("https://github.com/", "")}</p>
    </div>
  );
}

export default function SettingsWeb({ start = "gpu" as Tab }: { start?: Tab }) {
  const [tab, setTab] = useState<Tab>(start);
  useEffect(() => setTab(start), [start]);
  return (
    <main className="page narrow stack gap">
      <h1>Settings</h1>
      <Tabs label="Settings section" value={tab} onChange={setTab} options={[{ id: "gpu", label: "Free GPU video" }, { id: "chat", label: "AI chat" }, { id: "account", label: "Account" }, { id: "data", label: "Data" }]} />
      {tab === "gpu" && <GpuSettings />}
      {tab === "chat" && <WebAI />}
      {tab === "account" && <Account />}
      {tab === "data" && <Data />}
    </main>
  );
}
