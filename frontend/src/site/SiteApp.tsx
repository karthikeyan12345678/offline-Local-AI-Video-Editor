import { lazy, Suspense, useState } from "react";
import { currentProfile } from "../../../shared/web/account";
import { isGoogleConfigured, signInGuest, signInWithGoogle } from "../../../shared/web/auth";
import { startAutoSync } from "../../../shared/web/drive";
import { addHistory } from "../../../shared/web/history";
import { go, useRoute } from "./route";
import Landing from "./Landing";
import Guide from "./Guide";
import "./site.css";

const Workspace = lazy(() => import("./Workspace"));

function Gate() {
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const google = async () => {
    setErr(""); setBusy(true);
    try { await signInWithGoogle(); location.reload(); } catch (e) { setErr(e instanceof Error ? e.message : "Sign-in failed."); setBusy(false); }
  };
  return (
    <div className="gate"><div className="gate-card">
      <h1>Sign in to open your workspace</h1>
      <p>Your projects and history are saved under your Google account. Google asks you to allow your name, email and a private app folder in your Drive.</p>
      {err && <p className="err" role="alert">{err}</p>}
      {isGoogleConfigured() && <button type="button" className="primary" disabled={busy} onClick={() => void google()}>{busy ? "Opening Google…" : "Sign in with Google"}</button>}
      <button type="button" className="second" onClick={() => { signInGuest(); location.reload(); }}>Continue as guest</button>
      <button type="button" className="second" onClick={() => go("")}>Back</button>
      <p>Guest mode keeps your work in this browser only.</p>
    </div></div>
  );
}

function Authed({ view }: { view?: string }) {
  const [started] = useState(() => { startAutoSync(); try { if (!sessionStorage.getItem("vk_signed")) { sessionStorage.setItem("vk_signed", "1"); void addHistory("sign_in", "Opened the workspace"); } } catch { /* ignore */ } return true; });
  void started;
  return <Suspense fallback={<div className="gate" role="status">Loading…</div>}><Workspace start={view} /></Suspense>;
}

export default function SiteApp() {
  const r = useRoute();
  const me = currentProfile();
  if (r[0] === "guide") return <Guide />;
  if (r[0] !== "app") return <Landing />;
  if (!me) return <Gate />;
  return <Authed view={r[1]} />;
}
