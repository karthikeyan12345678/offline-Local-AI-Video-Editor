// Sign in with Google, in the browser only (Google Identity Services "token" flow, no server and no client secret).
// One consent screen gives: the name / e-mail / picture, and permission for this site's private Drive folder.
import { config } from "./config";
import { currentProfile, saveProfile, type Profile } from "./account";

const DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.appdata";
const SCOPE = `openid email profile ${DRIVE_SCOPE}`;

/* eslint-disable @typescript-eslint/no-explicit-any */
declare global { interface Window { google?: any } }

let gsi: Promise<void> | null = null;
export function loadGsi(): Promise<void> {
  if (window.google?.accounts?.oauth2) return Promise.resolve();
  if (!gsi) {
    gsi = new Promise<void>((resolve, reject) => {
      const s = document.createElement("script");
      s.src = "https://accounts.google.com/gsi/client"; s.async = true; s.defer = true;
      s.onload = () => resolve();
      s.onerror = () => { gsi = null; reject(new Error("Could not reach Google. Check your internet connection (or an ad blocker) and try again.")); };
      document.head.appendChild(s);
    });
  }
  return gsi;
}

let token: { value: string; exp: number } | null = null;
/** The Drive access token, while it is still valid (it lasts about an hour and is never saved to disk). */
export function getToken(): string | null { return token && Date.now() < token.exp - 30_000 ? token.value : null; }
export const isGoogleConfigured = (): boolean => !!config().googleClientId;
export const driveReady = (): boolean => !!getToken();

function request(prompt: "" | "select_account" | "consent"): Promise<{ access_token: string; expires_in: number; scope: string }> {
  return new Promise((resolve, reject) => {
    const client = window.google.accounts.oauth2.initTokenClient({
      client_id: config().googleClientId, scope: SCOPE,
      callback: (r: any) => (r.error ? reject(new Error(r.error_description || r.error)) : resolve(r)),
      error_callback: (e: any) => reject(new Error(e?.type === "popup_closed" ? "The Google window was closed before you finished." : e?.type === "popup_failed_to_open" ? "Your browser blocked the Google window. Allow pop-ups for this site and try again." : (e?.message || "Google sign-in failed."))),
    });
    client.requestAccessToken({ prompt });
  });
}

/** Must be called from a click. Opens Google's own window; returns the signed-in profile. */
export async function signInWithGoogle(): Promise<Profile> {
  if (!isGoogleConfigured()) throw new Error("Google sign-in is not set up on this site yet (the owner has to add a Google client ID; see the README).");
  await loadGsi();
  const r = await request("select_account");
  const res = await fetch("https://www.googleapis.com/oauth2/v3/userinfo", { headers: { Authorization: `Bearer ${r.access_token}` } });
  if (!res.ok) throw new Error("Google signed you in but did not share your profile. Try again.");
  const u = await res.json();
  if (!u.sub) throw new Error("Google did not return an account id.");
  const driveOk = !!window.google.accounts.oauth2.hasGrantedAllScopes?.(r, DRIVE_SCOPE);
  const p: Profile = { sub: String(u.sub), name: u.name || u.email || "You", email: u.email || "", picture: u.picture || "", driveOk };
  token = driveOk ? { value: r.access_token, exp: Date.now() + (r.expires_in || 3600) * 1000 } : null;
  saveProfile(p);
  return p;
}

/** Gets a fresh Drive token for the person who is already signed in (also needs a click). */
export async function reconnectDrive(): Promise<boolean> {
  const p = currentProfile();
  if (!p || p.guest || !isGoogleConfigured()) return false;
  await loadGsi();
  const r = await request("");
  if (!window.google.accounts.oauth2.hasGrantedAllScopes?.(r, DRIVE_SCOPE)) return false;
  token = { value: r.access_token, exp: Date.now() + (r.expires_in || 3600) * 1000 };
  saveProfile({ ...p, driveOk: true });
  return true;
}

export function signInGuest(): Profile {
  const p: Profile = { sub: "guest", name: "Guest", email: "", picture: "", guest: true };
  saveProfile(p);
  return p;
}

export function signOut(): void {
  try { if (token) window.google?.accounts?.oauth2?.revoke?.(token.value, () => undefined); } catch { /* ignore */ }
  token = null;
  saveProfile(null);
}
