"use strict";
/** Turns the many small steps of first-run setup into one honest progress bar with speed and time left. */

const fmtBytes = (n) => {
  if (!isFinite(n) || n < 0) return "";
  if (n >= 1024 ** 3) return (n / 1024 ** 3).toFixed(1) + " GB";
  if (n >= 1024 ** 2) return (n / 1024 ** 2).toFixed(0) + " MB";
  return Math.max(1, Math.round(n / 1024)) + " KB";
};

const fmtEta = (sec) => {
  if (!isFinite(sec) || sec < 0) return "";
  if (sec < 45) return "less than a minute";
  const m = Math.round(sec / 60);
  if (m < 60) return `about ${m} minute${m === 1 ? "" : "s"}`;
  const h = Math.floor(m / 60), r = m % 60;
  return `about ${h} h ${r} min`;
};

/** pip (with --progress-bar raw) prints "Progress 1234 of 5678" and "Downloading name-1.0.whl (2.5 MB)". */
function parsePipLine(line) {
  let m = /^Progress (\d+) of (\d+)/.exec(line);
  if (m) return { done: Number(m[1]), total: Number(m[2]) };
  m = /^Downloading (\S+) \(([\d.]+) ?(kB|KB|MB|GB)\)/.exec(line);
  if (m) {
    const mult = { kB: 1024, KB: 1024, MB: 1024 ** 2, GB: 1024 ** 3 }[m[3]];
    return { file: m[1], size: Number(m[2]) * mult };
  }
  m = /^(Installing collected packages|Successfully installed)/.exec(line);
  if (m) return { installing: true };
  return null;
}

class SetupProgress {
  /** steps: [{ id, label, weight }] — weights only need to be proportional to how long each step usually takes. */
  constructor(steps, now = () => Date.now()) {
    this.steps = steps.map((s) => ({ ...s, state: "waiting", fraction: 0 }));
    this.now = now;
    this.t0 = now();
    this.samples = [];
    this.cur = null;
    this.bytes = { done: 0, total: 0 };
    this.cum = 0;
  }

  begin(id) {
    for (const s of this.steps) { if (s.state === "active") { s.state = "done"; s.fraction = 1; } }
    this.cur = this.steps.find((s) => s.id === id) || null;
    if (this.cur) { this.cur.state = "active"; this.cur.fraction = 0; }
    this.samples = [];
    this.bytes = { done: 0, total: 0 };
  }

  finish(id) { const s = this.steps.find((x) => x.id === id); if (s) { s.state = "done"; s.fraction = 1; } }

  skip(id) { const s = this.steps.find((x) => x.id === id); if (s) { s.state = "skipped"; s.fraction = 1; } }

  /** Bytes of the file being downloaded now (a step may download several files one after another). */
  file(done, total) {
    const b = this.bytes;
    this.cum += done >= b.done ? done - b.done : done; // a smaller number means pip moved on to the next file
    b.done = done; b.total = total;
    const t = this.now();
    this.samples.push([t, this.cum]);
    while (this.samples.length > 2 && t - this.samples[0][0] > 6000) this.samples.shift();
    if (this.cur && total) this.cur.fraction = Math.max(this.cur.fraction, Math.min(0.98, done / total));
  }

  set(fraction) { if (this.cur) this.cur.fraction = Math.max(this.cur.fraction, Math.min(0.99, fraction)); }

  get speed() {
    const s = this.samples;
    if (s.length < 2) return 0;
    const dt = (s[s.length - 1][0] - s[0][0]) / 1000;
    return dt > 0.5 ? (s[s.length - 1][1] - s[0][1]) / dt : 0;
  }

  get fraction() {
    const total = this.steps.reduce((a, s) => a + s.weight, 0) || 1;
    const done = this.steps.reduce((a, s) => a + s.weight * (s.state === "done" || s.state === "skipped" ? 1 : s.state === "active" ? s.fraction : 0), 0);
    return Math.min(1, done / total);
  }

  /** Seconds left, from the pace so far; null until there is enough to go on. */
  get eta() {
    const f = this.fraction, el = (this.now() - this.t0) / 1000;
    if (f < 0.04 || el < 8) return null;
    return (el / f) * (1 - f);
  }

  detail() {
    const parts = [];
    const b = this.bytes;
    if (this.cur && b.total > 0) parts.push(`${fmtBytes(b.done)} of ${fmtBytes(b.total)}`);
    const sp = this.speed;
    if (sp > 50 * 1024) parts.push(`${fmtBytes(sp)}/s`);
    const e = this.eta;
    if (e !== null) parts.push(`${fmtEta(e)} left`);
    return parts.join(" · ");
  }

  snapshot() {
    return { steps: this.steps.map((s) => ({ id: s.id, label: s.label, state: s.state })), eta: this.eta, speed: this.speed };
  }
}

module.exports = { SetupProgress, parsePipLine, fmtBytes, fmtEta };
