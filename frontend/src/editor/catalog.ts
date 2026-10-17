import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { Catalog } from "../lib/types";

let cached: Catalog | null = null;
let pending: Promise<Catalog> | null = null;

const EMPTY: Catalog = { transitions: [{ id: "none", label: "None (hard cut)", group: "Basic" }], looks: [{ id: "none", label: "None" }], effects: [], masks: [{ id: "none", label: "No mask" }], motions: [{ id: "none", label: "None" }], audio_fx: [{ id: "none", label: "None", group: "Basic" }], fonts: [], text_anim_in: ["none", "fade"], text_anim_out: ["none", "fade"], whisper: [] };

export function refreshCatalog(): Promise<Catalog> {
  pending = api.catalog().then((c) => (cached = c));
  return pending;
}

/** The lists of transitions, looks, effects, fonts and so on, as the running app offers them. */
export function useCatalog(): Catalog {
  const [c, setC] = useState<Catalog>(cached ?? EMPTY);
  useEffect(() => {
    if (cached) return;
    (pending ?? refreshCatalog()).then(setC).catch(() => {});
  }, []);
  return c;
}

export function groupBy<T extends { group?: string }>(items: T[]): [string, T[]][] {
  const out = new Map<string, T[]>();
  for (const i of items) { const g = i.group ?? ""; if (!out.has(g)) out.set(g, []); out.get(g)!.push(i); }
  return [...out.entries()];
}

const LABELS: Record<string, string> = {
  none: "None", fade: "Fade", slide_up: "Slide up", slide_down: "Slide down", slide_left: "Slide from right", slide_right: "Slide from left",
  zoom: "Zoom", pop: "Pop (bounce)", reveal: "Wipe reveal", bounce: "Drop and bounce", typewriter: "Typewriter", flicker: "Flicker (neon sign)", drop: "Fall away",
};
export const animLabel = (id: string) => LABELS[id] ?? id;
