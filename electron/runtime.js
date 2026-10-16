"use strict";
/**
 * Finds, installs and starts the Python backend.
 * Pure Node (no Electron imports) so it can be tested without a window.
 *
 * Layout under <dataDir>/runtime/:
 *   python/        embedded CPython (Windows) + site-packages
 *   ready.json     written when setup finished: { version, torch, requirements }
 */
const fs = require("fs");
const path = require("path");
const https = require("https");
const crypto = require("crypto");
const { spawn, spawnSync } = require("child_process");

const IS_WIN = process.platform === "win32";
const PY_VERSION = "3.12.8";
const PY_EMBED_URL = `https://www.python.org/ftp/python/${PY_VERSION}/python-${PY_VERSION}-embed-amd64.zip`;
const GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py";
const SETUP_FORMAT = 1; // bump to force every PC to reinstall its runtime

const pythonExe = (dir) => (IS_WIN ? path.join(dir, "python.exe") : path.join(dir, "bin", "python3"));
const { SetupProgress, parsePipLine } = require("./progress");
const sha = (buf) => crypto.createHash("sha256").update(buf).digest("hex").slice(0, 16);

/** PyTorch wheel indexes to try, best first, for a GPU of this compute capability. */
function torchCandidates(gpu) {
  if (!gpu) return ["cpu"];
  const cc = gpu.major * 10 + gpu.minor;
  // Newer builds drop old architectures, so older cards must try older builds first.
  let tags = cc >= 75 ? ["cu130", "cu128", "cu126", "cu124"] : ["cu126", "cu118"];
  // A build made for a newer CUDA than the driver supports installs fine but cannot run, so skip those.
  if (gpu.driver) {
    const fits = tags.filter((t) => Number(t.slice(2, -1) + "." + t.slice(-1)) <= gpu.driver);
    if (fits.length) tags = fits;
  }
  return tags;
}

/** Parses `nvidia-smi --query-gpu=name,compute_cap,memory.total --format=csv,noheader,nounits`. */
function parseNvidiaSmi(text) {
  const best = { name: "", major: 0, minor: 0, mem: -1 };
  for (const line of String(text).split(/\r?\n/)) {
    const parts = line.split(",").map((s) => s.trim());
    if (parts.length < 3) continue;
    const m = /^(\d+)\.(\d+)$/.exec(parts[1]);
    const mem = Number(parts[2]);
    if (!m || !isFinite(mem)) continue;
    if (mem > best.mem) Object.assign(best, { name: parts[0], major: Number(m[1]), minor: Number(m[2]), mem });
  }
  return best.mem >= 0 ? best : null;
}

/** "CUDA Version: 12.6" from the header of plain `nvidia-smi`, as a number (12.6), or 0 when unknown. */
function parseDriverCuda(text) {
  const m = /CUDA Version:\s*(\d+)\.(\d+)/.exec(String(text));
  return m ? Number(`${m[1]}.${m[2]}`) : 0;
}

function detectGpu() {
  try {
    const r = spawnSync("nvidia-smi", ["--query-gpu=name,compute_cap,memory.total", "--format=csv,noheader,nounits"], { encoding: "utf8", timeout: 15000, windowsHide: true });
    if (r.status === 0) {
      const g = parseNvidiaSmi(r.stdout);
      if (g) {
        try { g.driver = parseDriverCuda(spawnSync("nvidia-smi", [], { encoding: "utf8", timeout: 15000, windowsHide: true }).stdout); } catch (_) { g.driver = 0; }
      }
      return g;
    }
  } catch (_) { /* no NVIDIA driver */ }
  return null;
}

/** The embedded Python ignores PYTHONPATH when a ._pth file exists, so the backend folder is listed in it. */
function writePth(pythonDir, backendDir) {
  const pth = fs.readdirSync(pythonDir).find((f) => /^python\d+\._pth$/.test(f));
  if (!pth) return false;
  const zip = pth.replace("._pth", ".zip");
  const lines = [zip, ".", "Lib\\site-packages", backendDir, "", "import site", ""];
  fs.writeFileSync(path.join(pythonDir, pth), lines.join("\r\n"));
  return true;
}

function download(url, dest, onProgress, redirects = 5) {
  return new Promise((resolve, reject) => {
    const part = dest + ".part";
    const req = https.get(url, { headers: { "User-Agent": "LTXPortableStudio" } }, (res) => {
      if ([301, 302, 303, 307, 308].includes(res.statusCode) && res.headers.location && redirects > 0) {
        res.resume();
        return resolve(download(new URL(res.headers.location, url).toString(), dest, onProgress, redirects - 1));
      }
      if (res.statusCode !== 200) { res.resume(); return reject(new Error(`Download failed (${res.statusCode}) for ${url}`)); }
      const total = Number(res.headers["content-length"] || 0);
      let got = 0;
      const out = fs.createWriteStream(part);
      res.on("data", (c) => { got += c.length; onProgress && onProgress(got, total); });
      res.pipe(out);
      out.on("finish", () => out.close(() => { fs.renameSync(part, dest); resolve(dest); }));
      out.on("error", reject);
      res.on("error", reject);
    });
    req.setTimeout(60000, () => req.destroy(new Error("The download stalled. Check your internet connection.")));
    req.on("error", reject);
  });
}

/** Runs a command, streaming each output line to `onLine`. Rejects with the tail of the output on failure. */
function run(cmd, args, { onLine, cwd, env } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, args, { cwd, env: { ...process.env, PYTHONUTF8: "1", PIP_DISABLE_PIP_VERSION_CHECK: "1", ...env }, windowsHide: true });
    const tail = [];
    let buf = "";
    const feed = (d) => {
      buf += d.toString();
      let i;
      while ((i = buf.search(/[\r\n]/)) >= 0) {
        const line = buf.slice(0, i).trim();
        buf = buf.slice(i + 1);
        if (!line) continue;
        tail.push(line); if (tail.length > 30) tail.shift();
        onLine && onLine(line);
      }
    };
    child.stdout.on("data", feed);
    child.stderr.on("data", feed);
    child.on("error", reject);
    child.on("close", (code) => (code === 0 ? resolve(tail.join("\n")) : reject(new Error(`${path.basename(cmd)} exited with code ${code}\n${tail.slice(-8).join("\n")}`))));
  });
}

/** pip with raw progress: feeds bytes into the tracker and keeps the plain lines for the log. */
function pipLine(tracker, report, stage, extra) {
  return (line) => {
    const p = parsePipLine(line);
    if (p && p.total) { tracker.file(p.done, p.total); report(stage, tracker.fraction, tracker.detail(), tracker.snapshot()); return; }
    if (p && p.file) { report(stage, tracker.fraction, `Getting ${p.file.split("-")[0]} (${(p.size / 1048576).toFixed(0)} MB)`, tracker.snapshot()); return; }
    if (p && p.installing) { tracker.set(0.9); report(stage, tracker.fraction, "Installing…", tracker.snapshot()); return; }
    if (extra) extra(line);
  };
}

const MANIFEST_URL = process.env.LTXPS_UPDATE_URL || "https://raw.githubusercontent.com/karthikeyan12345678/ai-assistant-studio/main/update-manifest.json";

/** Newest tested module versions from the project's update manifest, or null when offline (the bundled list is then used). */
function fetchManifest(url = MANIFEST_URL, timeoutMs = 6000) {
  return new Promise((resolve) => {
    try {
      const req = https.get(url, { headers: { "User-Agent": "VKEditor" }, timeout: timeoutMs }, (res) => {
        if (res.statusCode !== 200) { res.resume(); return resolve(null); }
        let body = "";
        res.setEncoding("utf8");
        res.on("data", (c) => { body += c; if (body.length > 200000) req.destroy(); });
        res.on("end", () => { try { resolve(JSON.parse(body)); } catch { resolve(null); } });
      });
      req.on("timeout", () => req.destroy());
      req.on("error", () => resolve(null));
    } catch { resolve(null); }
  });
}

/** Same requirements, but every package the manifest lists is moved to the manifest's tested version. */
function liveRequirements(text, manifest) {
  const want = new Map();
  for (const m of (manifest && Array.isArray(manifest.modules)) ? manifest.modules : []) {
    if (m && /^[A-Za-z0-9_.-]+$/.test(m.name || "") && /^\d+(\.\d+){0,3}$/.test(m.version || "")) want.set(String(m.name).toLowerCase().replace(/[-_.]+/g, "-"), m.version);
  }
  return text.split(/\r?\n/).map((line) => {
    const m = line.match(/^([A-Za-z0-9_.-]+)==([\w.+-]+)(.*)$/);
    const v = m && want.get(m[1].toLowerCase().replace(/[-_.]+/g, "-"));
    return v ? `${m[1]}==${v}${m[3]}` : line;
  }).join("\n");
}

/** True when a graphics card exists but the installed PyTorch is the processor-only build and we have not already tried for this driver. */
function gpuUpgradeWanted(info, gpu) {
  if (!info || !IS_WIN || info.torch !== "cpu") return false;
  const g = gpu === undefined ? detectGpu() : gpu;
  if (!g) return false;
  return !info.gpuTried || info.gpuTried.driver !== g.driver || info.gpuTried.name !== g.name;
}

function readyInfo(runtimeDir) {
  try { return JSON.parse(fs.readFileSync(path.join(runtimeDir, "ready.json"), "utf8")); } catch (_) { return null; }
}

/**
 * Returns { python, bundled } for a usable interpreter, or null if setup is needed.
 * Order: explicit override (dev), interpreter bundled in the installer, interpreter set up on first run.
 */
function findPython({ resourcesDir, dataDir, requirementsFile, env = process.env }) {
  if (env.LTXPS_PYTHON && fs.existsSync(env.LTXPS_PYTHON)) return { python: env.LTXPS_PYTHON, bundled: true, dir: path.dirname(env.LTXPS_PYTHON) };
  const bundled = path.join(resourcesDir, "python");
  if (fs.existsSync(pythonExe(bundled))) return { python: pythonExe(bundled), bundled: true, dir: bundled };
  const runtimeDir = path.join(dataDir, "runtime");
  const info = readyInfo(runtimeDir);
  const py = pythonExe(path.join(runtimeDir, "python"));
  if (info && info.format === SETUP_FORMAT && info.requirements === sha(fs.readFileSync(requirementsFile)) && fs.existsSync(py)) {
    if (info.forceGpu || gpuUpgradeWanted(info)) return null; // go through setup again: it keeps what works and only fetches the GPU build
    return { python: py, bundled: false, dir: path.dirname(py), info };
  }
  return null;
}

/** First-run install. `report(stage, fraction|null, detail, extra)` feeds the splash screen; fraction is for the whole setup. */
async function setupRuntime({ dataDir, backendDir, requirementsFile, report: rawReport, signal = { cancelled: false }, needTorch = true, minFreeGb = 8 }) {
  if (!IS_WIN) throw new Error("Automatic runtime setup is only available on Windows. Use LTXPS_PYTHON to point at a Python with the requirements installed.");
  const runtimeDir = path.join(dataDir, "runtime");
  const pyDir = path.join(runtimeDir, "python");
  const tmp = path.join(runtimeDir, "tmp");
  fs.mkdirSync(tmp, { recursive: true });
  // The portable .exe unpacks into a temporary folder that Windows may delete while setup runs.
  // Keep our own copy of the package list so a long setup (or a retry) never loses it.
  const reqText = fs.readFileSync(requirementsFile);
  const reqSha = sha(reqText);
  requirementsFile = path.join(runtimeDir, "requirements.base.txt");
  fs.writeFileSync(requirementsFile, reqText);
  const check = () => { if (signal.cancelled) throw new Error("Setup cancelled."); };
  const tracker = new SetupProgress([
    { id: "check", label: "Checking your computer", weight: 2 },
    { id: "python", label: "Getting the engine (Python)", weight: 6 },
    { id: "pip", label: "Getting the installer tool", weight: 2 },
    ...(needTorch ? [{ id: "torch", label: "Getting the AI brain (PyTorch)", weight: 50 }] : []),
    { id: "libs", label: "Getting the helper libraries", weight: needTorch ? 40 : 90 },
  ]);
  const report = (stage, fraction, detail, extra) => rawReport(stage, tracker.fraction, detail, extra || tracker.snapshot());

  tracker.begin("check");
  report("Checking this PC", null, "");
  const gpu = needTorch ? detectGpu() : null;
  const free = (() => { try { const s = fs.statfsSync(runtimeDir); return s.bavail * s.bsize; } catch (_) { return Infinity; } })();
  if (free < minFreeGb * 1024 ** 3) throw new Error(`Not enough free disk space for setup: about ${minFreeGb} GB are needed, ${(free / 1024 ** 3).toFixed(1)} GB are free.`);

  // 1. Python
  tracker.begin("python");
  if (!fs.existsSync(pythonExe(pyDir))) {
    const zip = path.join(tmp, "python-embed.zip");
    report("Downloading Python", 0, "");
    await download(PY_EMBED_URL, zip, (g, t) => { tracker.file(g, t); report("Downloading Python", null, tracker.detail()); });
    check();
    report("Unpacking Python", null, "");
    fs.rmSync(pyDir, { recursive: true, force: true });
    await run("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", `Expand-Archive -LiteralPath '${zip}' -DestinationPath '${pyDir}' -Force`]);
  }
  writePth(pyDir, backendDir);
  const py = pythonExe(pyDir);

  // 2. pip
  tracker.begin("pip");
  const hasPip = spawnSync(py, ["-m", "pip", "--version"], { windowsHide: true }).status === 0;
  if (!hasPip) {
    check();
    const getPip = path.join(tmp, "get-pip.py");
    report("Downloading the package installer", null, "");
    await download(GET_PIP_URL, getPip);
    report("Installing the package installer", null, "");
    await run(py, [getPip, "--no-warn-script-location"], { onLine: (l) => report("Installing the package installer", null, l.slice(0, 100)) });
  }

  // 3. PyTorch: try builds until one can really use this GPU (the AI Assistant does not need it)
  let chosen = needTorch ? null : "none";
  let gpuTried = null;
  if (needTorch) tracker.begin("torch");
  // Never download PyTorch again when a working one exists. Only a missing GPU build is fetched, once per driver.
  const previous = readyInfo(runtimeDir);
  const upgradeOnly = !!(needTorch && previous && previous.torch === "cpu" && gpu && (previous.forceGpu || gpuUpgradeWanted(previous, gpu)));
  if (needTorch && previous && previous.format === SETUP_FORMAT && previous.torch && previous.torch !== "none" && fs.existsSync(py) && hasPip) {
    const probe = spawnSync(py, ["-c", "import torch"], { windowsHide: true, timeout: 120000 });
    if (probe.status === 0 && !upgradeOnly) { chosen = previous.torch; gpuTried = previous.gpuTried || null; tracker.skip("torch"); report("PyTorch is already installed — keeping it", null, ""); }
  }
  const candidates = needTorch && !chosen ? torchCandidates(gpu) : [];
  let lastError = "";
  const torchArgs = (tag) => ["-m", "pip", "install", "--upgrade", "--force-reinstall", "--no-warn-script-location", "--progress-bar", "raw", "torch", "--index-url", `https://download.pytorch.org/whl/${tag}`];
  for (const tag of candidates) {
    check();
    const label = tag === "cpu" ? "Downloading PyTorch (processor only)" : `Downloading PyTorch for your graphics card (${tag})`;
    report(label, null, "This is the biggest download (2–3 GB). Please keep the window open.");
    try {
      await run(py, torchArgs(tag), { onLine: pipLine(tracker, report, label) });
    } catch (e) { lastError = e.message; continue; }
    report("Testing the graphics card", null, "");
    const r = spawnSync(py, ["-m", "ltxps.selfcheck"], { encoding: "utf8", windowsHide: true, timeout: 180000 });
    let res = null;
    try { res = JSON.parse(String(r.stdout).trim().split(/\r?\n/).pop()); } catch (_) { /* fall through */ }
    if (tag === "cpu" || (res && res.cuda && res.arch_ok)) { chosen = tag; break; }
    lastError = `PyTorch ${tag} cannot run on this graphics card${res && res.error ? ` (${res.error})` : ""}.`;
  }
  if (gpu && needTorch) gpuTried = { driver: gpu.driver || 0, name: gpu.name, ok: !!chosen && chosen !== "cpu", error: chosen && chosen !== "cpu" ? "" : lastError.slice(0, 300), when: new Date().toISOString() };
  if (!chosen) {
    if (upgradeOnly) { chosen = "cpu"; report("Your graphics card could not be switched on", null, "The processor-only PyTorch stays installed. You can try again from Help → Turn on graphics card."); }
    else if (gpu) { chosen = "cpu"; const label = "Downloading PyTorch (processor only)"; report(label, null, "No GPU build worked; falling back to the processor."); await run(py, torchArgs("cpu"), { onLine: pipLine(tracker, report, label) }); }
    else throw new Error(lastError || "Could not install PyTorch.");
  }

  // Remember the finished PyTorch step right now: if a later step fails, "Try again" must never download it again.
  try { fs.writeFileSync(path.join(runtimeDir, "ready.json"), JSON.stringify({ format: SETUP_FORMAT, torch: chosen, gpuTried, requirements: "pending", when: new Date().toISOString(), gpu }, null, 2)); } catch (_) { /* best effort */ }

  // 4. everything else
  check();
  tracker.begin("libs");
  const libsLabel = "Downloading the helper libraries";
  report(libsLabel, null, "");
  // Re-installing later always gets the newest tested versions, not the ones frozen into this download.
  let reqFile = requirementsFile;
  const live = await fetchManifest();
  if (live) {
    try { reqFile = path.join(runtimeDir, "requirements.live.txt"); fs.writeFileSync(reqFile, liveRequirements(fs.readFileSync(requirementsFile, "utf8"), live)); } catch { reqFile = requirementsFile; }
  }
  await run(py, ["-m", "pip", "install", "--no-warn-script-location", "--progress-bar", "raw", "-r", reqFile], { onLine: pipLine(tracker, report, libsLabel) });
  tracker.finish("libs");
  report("All done", null, "Starting the app…");

  fs.writeFileSync(path.join(runtimeDir, "ready.json"), JSON.stringify({ format: SETUP_FORMAT, torch: chosen, gpuTried, requirements: reqSha, when: new Date().toISOString(), gpu }, null, 2));
  fs.rmSync(tmp, { recursive: true, force: true });
  return { python: py, bundled: false, dir: pyDir };
}

/** Starts the backend and resolves with { child, port, token, url } once it prints its READY line. */
function startBackend({ python, backendDir, uiDir, dataDir, parentPid = process.pid, extraEnv = {}, onLog, timeoutMs = 120000, token, mode = "studio", assistantUiDir }) {
  return new Promise((resolve, reject) => {
    const args = ["-m", "ltxps", "--mode", mode, "--parent-pid", String(parentPid)];
    if (uiDir) args.push("--ui-dir", uiDir);
    if (assistantUiDir && mode === "studio") args.push("--assistant-ui-dir", assistantUiDir);
    const env = { ...process.env, PYTHONUTF8: "1", PYTHONIOENCODING: "utf-8", PYTHONPATH: backendDir, LTXPS_DATA_DIR: dataDir, ...(token ? { LTXPS_TOKEN: token } : {}), ...extraEnv };
    const child = spawn(python, args, { env, cwd: backendDir, windowsHide: true });
    let settled = false;
    let buf = "";
    const tail = [];
    const timer = setTimeout(() => fail(new Error("The app did not start in time.\n" + tail.slice(-8).join("\n"))), timeoutMs);
    const fail = (err) => { if (settled) return; settled = true; clearTimeout(timer); try { child.kill(); } catch (_) { /* already gone */ } reject(err); };
    const feed = (d) => {
      buf += d.toString();
      let i;
      while ((i = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, i).replace(/\r$/, ""); buf = buf.slice(i + 1);
        tail.push(line); if (tail.length > 40) tail.shift();
        onLog && onLog(line);
        if (!settled && line.startsWith("LTXPS_READY ")) {
          try { const info = JSON.parse(line.slice(12)); settled = true; clearTimeout(timer); resolve({ child, port: info.port, token: info.token, url: info.url, ui: info.ui }); } catch (e) { fail(e); }
        }
      }
    };
    child.stdout.on("data", feed);
    child.stderr.on("data", feed);
    child.on("error", fail);
    child.on("exit", (code) => fail(new Error(`The app stopped unexpectedly (code ${code}).\n${tail.slice(-8).join("\n")}`)));
  });
}

function killTree(child) {
  if (!child || child.killed || child.exitCode !== null) return;
  try {
    if (IS_WIN) spawnSync("taskkill", ["/pid", String(child.pid), "/T", "/F"], { windowsHide: true });
    else child.kill("SIGTERM");
  } catch (_) { /* already gone */ }
}

module.exports = { gpuUpgradeWanted, parseDriverCuda, fetchManifest, liveRequirements, SetupProgress, IS_WIN, SETUP_FORMAT, pythonExe, sha, torchCandidates, parseNvidiaSmi, detectGpu, writePth, findPython, setupRuntime, startBackend, killTree, readyInfo };
