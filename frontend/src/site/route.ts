import { useEffect, useState } from "react";

/** Tiny hash router, so the site works from any folder on GitHub Pages and Netlify with no server rules. "#/app/editor" -> ["app","editor"]. */
export const parts = (): string[] => location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
export const go = (path: string): void => { location.hash = "#/" + path.replace(/^\/+/, ""); };

export function useRoute(): string[] {
  const [r, setR] = useState(parts);
  useEffect(() => { const on = () => setR(parts()); window.addEventListener("hashchange", on); return () => window.removeEventListener("hashchange", on); }, []);
  return r;
}
