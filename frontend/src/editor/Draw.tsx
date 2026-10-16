import { useRef, useState, type PointerEvent as RPE } from "react";
import type { Drawing, Shape, ShapeType } from "../lib/types";
import { newShape } from "./model";

export interface PenSettings { tool: ShapeType; color: string; width: number; filled: boolean }
export const TOOLS: { id: ShapeType; label: string }[] = [
  { id: "pen", label: "Pen" }, { id: "highlight", label: "Highlighter" }, { id: "line", label: "Line" },
  { id: "arrow", label: "Arrow" }, { id: "ellipse", label: "Circle" }, { id: "rect", label: "Box" },
];
export const COLORS = ["#FF3B30", "#FFCC00", "#34C759", "#0A84FF", "#FFFFFF", "#000000", "#FF2D95", "#FF9500"];

const clamp01 = (v: number) => Math.min(1, Math.max(0, v));

/** Ramer–Douglas–Peucker: keeps the look of a hand-drawn line with far fewer points. */
export function simplify(pts: [number, number][], eps = 0.0015): [number, number][] {
  if (pts.length < 3) return pts;
  const keep = new Array(pts.length).fill(false);
  keep[0] = keep[pts.length - 1] = true;
  const stack: [number, number][] = [[0, pts.length - 1]];
  while (stack.length) {
    const [a, b] = stack.pop()!;
    let dmax = 0, idx = -1;
    const [x1, y1] = pts[a], [x2, y2] = pts[b];
    const len = Math.hypot(x2 - x1, y2 - y1) || 1e-9;
    for (let i = a + 1; i < b; i++) {
      const d = Math.abs((y2 - y1) * pts[i][0] - (x2 - x1) * pts[i][1] + x2 * y1 - y2 * x1) / len;
      if (d > dmax) { dmax = d; idx = i; }
    }
    if (idx >= 0 && dmax > eps) { keep[idx] = true; stack.push([a, idx], [idx, b]); }
  }
  return pts.filter((_, i) => keep[i]);
}

function ShapeSvg({ s, W, H }: { s: Shape; W: number; H: number }) {
  const pts = s.points.map(([x, y]) => [x * W, y * H] as [number, number]);
  if (!pts.length) return null;
  const sw = (H * s.width) / 100 * (s.type === "highlight" ? 3 : 1);
  const op = s.type === "highlight" ? 0.4 : s.opacity;
  const common = { stroke: s.color, strokeWidth: sw, strokeOpacity: op, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, fill: "none" };
  if (s.type === "pen" || s.type === "highlight") {
    if (pts.length === 1) return <circle cx={pts[0][0]} cy={pts[0][1]} r={sw / 2} fill={s.color} fillOpacity={op} />;
    return <polyline {...common} points={pts.map((p) => p.join(",")).join(" ")} />;
  }
  const a = pts[0], b = pts[pts.length - 1];
  if (s.type === "line" || s.type === "arrow") {
    const ang = Math.atan2(b[1] - a[1], b[0] - a[0]);
    const size = Math.max(sw * 3.2, 14 * (H / 720));
    const head = [-1, 1].map((k) => { const t = ang + Math.PI + (k * 28 * Math.PI) / 180; return `${b[0] + size * Math.cos(t)},${b[1] + size * Math.sin(t)}`; });
    return <g><line {...common} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} />{s.type === "arrow" && <polyline {...common} points={`${head[0]} ${b[0]},${b[1]} ${head[1]}`} />}</g>;
  }
  const x = Math.min(a[0], b[0]), y = Math.min(a[1], b[1]), w = Math.abs(a[0] - b[0]), h = Math.abs(a[1] - b[1]);
  const fill = s.filled ? { fill: s.fill_color ?? s.color, fillOpacity: s.fill_opacity } : {};
  return s.type === "rect" ? <rect {...common} {...fill} x={x} y={y} width={w} height={h} rx={Math.min(sw, w / 4, h / 4)} /> : <ellipse {...common} {...fill} cx={x + w / 2} cy={y + h / 2} rx={w / 2} ry={h / 2} />;
}

/** The drawings that are on screen at `time` (and always the one being edited). */
export function DrawingsLayer({ drawings, time, W, H, editingId }: { drawings: Drawing[]; time: number; W: number; H: number; editingId: string | null }) {
  const shown = drawings.filter((d) => d.id === editingId || (time >= d.start && time < d.start + d.duration));
  if (!shown.length) return null;
  return (
    <svg className="draw-svg" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden="true">
      {shown.map((d) => {
        let o = d.opacity;
        if (d.id !== editingId) {
          if (d.anim_in !== "none" && d.fade_in > 0 && time - d.start < d.fade_in) o *= Math.max(0, (time - d.start) / d.fade_in);
          if (d.anim_out !== "none" && d.fade_out > 0 && d.start + d.duration - time < d.fade_out) o *= Math.max(0, (d.start + d.duration - time) / d.fade_out);
        }
        return <g key={d.id} opacity={o}>{d.shapes.map((s, i) => <ShapeSvg key={i} s={s} W={W} H={H} />)}</g>;
      })}
    </svg>
  );
}

/** Transparent sheet over the picture that turns mouse or touch drags into shapes. */
export function DrawCapture({ pen, W, H, onShape }: { pen: PenSettings; W: number; H: number; onShape: (s: Shape) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const [live, setLive] = useState<Shape | null>(null);
  const pts = useRef<[number, number][]>([]);

  const at = (e: RPE): [number, number] => {
    const r = ref.current!.getBoundingClientRect();
    return [clamp01((e.clientX - r.left) / r.width), clamp01((e.clientY - r.top) / r.height)];
  };
  const make = (points: [number, number][]) => newShape({ type: pen.tool, points, color: pen.color, width: pen.width, filled: pen.filled && (pen.tool === "rect" || pen.tool === "ellipse") });
  const down = (e: RPE) => { e.preventDefault(); (e.target as HTMLElement).setPointerCapture(e.pointerId); pts.current = [at(e)]; setLive(make(pts.current)); };
  const move = (e: RPE) => {
    if (!pts.current.length) return;
    const p = at(e);
    if (pen.tool === "pen" || pen.tool === "highlight") {
      const last = pts.current[pts.current.length - 1];
      if (Math.hypot(p[0] - last[0], p[1] - last[1]) < 0.002) return;
      pts.current = [...pts.current, p];
    } else pts.current = [pts.current[0], p];
    setLive(make(pts.current));
  };
  const up = () => {
    if (!pts.current.length) return;
    let p = pts.current;
    if (pen.tool === "pen" || pen.tool === "highlight") p = simplify(p);
    const tiny = pen.tool !== "pen" && pen.tool !== "highlight" && (p.length < 2 || Math.hypot(p[1][0] - p[0][0], p[1][1] - p[0][1]) < 0.01);
    if (!tiny) onShape(make(p));
    pts.current = []; setLive(null);
  };
  return (
    <div ref={ref} className="draw-capture" onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up} role="application" aria-label="Drawing area. Drag to draw.">
      {live && <svg className="draw-svg" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden="true"><ShapeSvg s={live} W={W} H={H} /></svg>}
    </div>
  );
}
