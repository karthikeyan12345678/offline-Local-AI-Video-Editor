// Settings the person who hosts the site can change WITHOUT rebuilding: edit public/config.js (it is loaded before the app).
// None of these values is secret. A Google "client ID" is public by design; there is no client secret anywhere in this site.
export interface SiteConfig {
  /** OAuth 2.0 Web client ID from console.cloud.google.com (empty = Google sign-in is not set up yet; guest mode is offered instead). */
  googleClientId: string;
  /** true = the workspace needs a Google sign-in (guest mode is only offered while googleClientId is empty). */
  requireLogin: boolean;
  /** The GitHub page where people download the program for their own computer. */
  localRepo: string;
  /** This website's own repository. */
  webRepo: string;
  /** Name shown in the header. */
  siteName: string;
}

declare global { interface Window { VK_CONFIG?: Partial<SiteConfig> } }

const DEFAULTS: SiteConfig = {
  googleClientId: "",
  requireLogin: true,
  localRepo: "https://github.com/karthikeyan12345678/offline-Local-AI-Video-Editor",
  webRepo: "https://github.com/karthikeyan12345678/vk-editor-web",
  siteName: "VK Editor",
};

export function config(): SiteConfig {
  const env = ((import.meta as unknown as { env?: Record<string, string | undefined> }).env ?? {});
  const fromEnv: Partial<SiteConfig> = env.VITE_GOOGLE_CLIENT_ID ? { googleClientId: env.VITE_GOOGLE_CLIENT_ID } : {};
  const c = { ...DEFAULTS, ...fromEnv, ...(typeof window !== "undefined" ? window.VK_CONFIG ?? {} : {}) };
  c.googleClientId = ((typeof window !== "undefined" ? window.VK_CONFIG?.googleClientId : "") || fromEnv.googleClientId || "").trim();
  return c;
}
