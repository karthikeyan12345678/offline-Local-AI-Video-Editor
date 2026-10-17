// Free-plan meter. Free AI services give a number of requests per day that renews on its own.
// This counts the requests THIS browser made in the last 6, 12 and 24 hours, so you can see how much is left
// and when it comes back. The limits are typical values; edit them to match your own account.
const KEY = "vk_quota_v1";
export const WINDOWS = [6, 12, 24] as const;

export interface QuotaState { hits: Record<string, number[]>; limits: Record<string, number> }

/** Typical free requests per 24 hours. 0 means "no fixed number". Check the provider for your account. */
export const DEFAULT_LIMITS: Record<string, number> = { groq: 1000, gemini: 250, openrouter: 50, cerebras: 1000, github: 150, pollinations: 0, ollama: 0, lmstudio: 0, custom: 0, zerogpu: 300 };
/** What one "use" means for a provider (default: one request). The free Hugging Face GPU is counted in seconds. */
export const UNITS: Record<string, string> = { zerogpu: "s of GPU" };
/** Providers whose allowance is one pot per day (any window may use all of it), not a steady trickle. */
const FIXED_DAY: Record<string, boolean> = { zerogpu: true };

function read(): QuotaState {
  try { const s = JSON.parse(localStorage.getItem(KEY) ?? "null"); if (s && typeof s === "object") return { hits: s.hits ?? {}, limits: s.limits ?? {} }; } catch { /* private mode */ }
  return { hits: {}, limits: {} };
}
function write(s: QuotaState): void { try { localStorage.setItem(KEY, JSON.stringify(s)); } catch { /* ignore */ } }

export function recordUse(provider: string, now = Date.now(), amount = 1): void {
  const s = read();
  const cut = now - 24 * 3600_000;
  const n = Math.max(1, Math.min(1000, Math.round(amount)));
  s.hits[provider] = [...(s.hits[provider] ?? []).filter((t) => t > cut), ...Array.from({ length: n }, () => now)];
  write(s);
  window.dispatchEvent(new Event("vk-quota"));
}

export function setLimit(provider: string, perDay: number): void {
  const s = read(); s.limits[provider] = Math.max(0, Math.round(perDay)); write(s);
  window.dispatchEvent(new Event("vk-quota"));
}

export function limitFor(provider: string): number {
  const s = read();
  return s.limits[provider] ?? DEFAULT_LIMITS[provider] ?? 0;
}

export interface QuotaRow { hours: number; used: number; limit: number; left: number | null; renewsInMs: number | null }

/** For each window: how many requests were used, the share of the daily limit that window may use, and when the oldest one expires. */
export function meter(provider: string, now = Date.now()): QuotaRow[] {
  const s = read();
  const hits = (s.hits[provider] ?? []).filter((t) => t > now - 24 * 3600_000).sort((a, b) => a - b);
  const day = limitFor(provider);
  return WINDOWS.map((h) => {
    const inWin = hits.filter((t) => t > now - h * 3600_000);
    const limit = day ? (FIXED_DAY[provider] ? day : Math.max(1, Math.round((day * h) / 24))) : 0; // fair share of the day for this window (the free GPU has one daily pot)
    return { hours: h, used: inWin.length, limit, left: limit ? Math.max(0, limit - inWin.length) : null, renewsInMs: inWin.length ? inWin[0] + h * 3600_000 - now : null };
  });
}

export function fmtWait(ms: number): string {
  const m = Math.max(1, Math.round(ms / 60000));
  return m >= 90 ? `${Math.round(m / 60)} h` : `${m} min`;
}
