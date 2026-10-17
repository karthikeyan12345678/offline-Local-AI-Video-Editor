import type { CSSProperties } from "react";

/**
 * The preview of a layer's shape mask. The shapes are drawn in the same units the exporter uses (the short side of the picture is 2 units),
 * so what you see here matches the exported video. Edge softness ("feather") is only applied on export.
 */
let heart: [number, number][] | null = null;
function heartPoints(): [number, number][] {
  if (heart) return heart;
  const f = (u: number, v: number) => { const x = u * 1.25, y = -v * 1.25 + 0.25; return Math.pow(x * x + y * y - 1, 3) - x * x * Math.pow(y, 3); };
  const pts: [number, number][] = [];
  const cu = 0, cv = 0;
  for (let k = 0; k < 72; k++) {
    const a = (k / 72) * Math.PI * 2, du = Math.cos(a), dv = Math.sin(a);
    let lo = 0, hi = 2.5;
    for (let i = 0; i < 28; i++) { const mid = (lo + hi) / 2; if (f(cu + du * mid, cv + dv * mid) <= 0) lo = mid; else hi = mid; }
    pts.push([cu + du * lo, cv + dv * lo]);
  }
  return (heart = pts);
}
const poly = (pts: [number, number][]) => "M" + pts.map((p) => `${p[0].toFixed(4)} ${p[1].toFixed(4)}`).join("L") + "Z";
const ellipse = (a: number, b: number) => `M${-a} 0A${a} ${b} 0 1 0 ${a} 0A${a} ${b} 0 1 0 ${-a} 0Z`;

export function shapePath(mask: string, a: number, b: number): string | null {
  switch (mask) {
    case "circle": return ellipse(1, 1);
    case "ellipse": return ellipse(a, b);
    case "diamond": return poly([[0, -b], [a, 0], [0, b], [-a, 0]]);
    case "rounded": { const r = 0.35; return `M${-a + r} ${-b}H${a - r}A${r} ${r} 0 0 1 ${a} ${-b + r}V${b - r}A${r} ${r} 0 0 1 ${a - r} ${b}H${-a + r}A${r} ${r} 0 0 1 ${-a} ${b - r}V${-b + r}A${r} ${r} 0 0 1 ${-a + r} ${-b}Z`; }
    case "heart": return poly(heartPoints());
    case "star": return poly(Array.from({ length: 10 }, (_, k) => { const ang = -Math.PI / 2 + (k * Math.PI) / 5, r = k % 2 === 0 ? 1 : 0.42; return [Math.cos(ang) * r, Math.sin(ang) * r] as [number, number]; }));
    case "hexagon": return poly([[1.1547, 0], [0.5774, 1], [-0.5774, 1], [-1.1547, 0], [-0.5774, -1], [0.5774, -1]]);
    default: return null;
  }
}

/** CSS that cuts a layer into its shape. `w` and `h` are the picture's size (only the shape of the box matters). */
export function maskStyle(mask: string, invert: boolean, w: number, h: number): CSSProperties {
  if (!mask || mask === "none") return {};
  const m = Math.max(1, Math.min(w, h)), a = (w || 16) / (w && h ? m : 9), b = (h || 9) / (w && h ? m : 9);
  if (mask === "half_left") return { clipPath: invert ? "inset(0 0 0 50%)" : "inset(0 50% 0 0)" };
  if (mask === "half_top") return { clipPath: invert ? "inset(50% 0 0 0)" : "inset(0 0 50% 0)" };
  if (mask === "blinds") {
    const g = invert ? "linear-gradient(#000 25%, transparent 25%, transparent 75%, #000 75%)" : "linear-gradient(transparent 25%, #000 25%, #000 75%, transparent 75%)";
    return { WebkitMaskImage: g, maskImage: g, WebkitMaskSize: "100% 12.5%", maskSize: "100% 12.5%" };
  }
  const d = shapePath(mask, a, b);
  if (!d) return {};
  const pad = 2 + Math.max(a, b);
  const full = invert ? `M${-a - pad} ${-b - pad}H${a + pad}V${b + pad}H${-a - pad}Z` : "";
  const svg = `<svg xmlns='http://www.w3.org/2000/svg' viewBox='${-a} ${-b} ${2 * a} ${2 * b}' preserveAspectRatio='none'><path fill='black' fill-rule='evenodd' d='${full}${d}'/></svg>`;
  const url = `url("data:image/svg+xml;utf8,${encodeURIComponent(svg)}")`;
  return { WebkitMaskImage: url, maskImage: url, WebkitMaskSize: "100% 100%", maskSize: "100% 100%", WebkitMaskRepeat: "no-repeat", maskRepeat: "no-repeat" };
}
