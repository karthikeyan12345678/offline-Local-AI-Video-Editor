// Who is using this browser. A Google sign-in gives a name, e-mail and picture; the projects and history of each person
// are kept in their own browser database. (There is no server, so this is a local profile, not a security boundary:
// anyone who can open this browser profile can open its data. The Drive copy, if allowed, is private to the Google account.)
export interface Profile { sub: string; name: string; email: string; picture: string; guest?: boolean; driveOk?: boolean }
const KEY = "vk_account_v1";

export function currentProfile(): Profile | null {
  try {
    const p = JSON.parse(localStorage.getItem(KEY) ?? "null");
    if (p && typeof p.sub === "string" && p.sub) return p as Profile;
  } catch { /* storage blocked */ }
  return null;
}
export function saveProfile(p: Profile | null): void {
  try { if (p) localStorage.setItem(KEY, JSON.stringify(p)); else localStorage.removeItem(KEY); } catch { /* ignore */ }
}
/** Name of this person's own browser database. Guests share one database. */
export function dbName(p: Profile | null = currentProfile()): string {
  return p && !p.guest ? `vkeditor-web-${p.sub.replace(/[^a-zA-Z0-9_-]/g, "")}` : "vkeditor-web";
}
