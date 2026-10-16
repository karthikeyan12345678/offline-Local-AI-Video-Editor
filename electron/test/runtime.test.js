"use strict";
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawnSync } = require("child_process");
const rt = require("../runtime");

const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), "ltxps-"));
const PY = process.env.LTXPS_PYTHON;
const BACKEND = path.join(__dirname, "..", "..", "backend");

test("parses nvidia-smi and picks the card with the most memory", () => {
  const out = "NVIDIA GeForce GTX 1650, 7.5, 4096\nNVIDIA GeForce RTX 3060, 8.6, 12288\n";
  assert.deepStrictEqual(rt.parseNvidiaSmi(out), { name: "NVIDIA GeForce RTX 3060", major: 8, minor: 6, mem: 12288 });
  assert.strictEqual(rt.parseNvidiaSmi(""), null);
  assert.strictEqual(rt.parseNvidiaSmi("garbage, N/A, [N/A]"), null);
});

test("old graphics cards start with older PyTorch builds, no GPU gets the CPU build", () => {
  assert.deepStrictEqual(rt.torchCandidates(null), ["cpu"]);
  assert.strictEqual(rt.torchCandidates({ major: 6, minor: 1 })[0], "cu126");
  assert.strictEqual(rt.torchCandidates({ major: 7, minor: 5 })[0], "cu130");
  assert.ok(!rt.torchCandidates({ major: 8, minor: 9 }).includes("cpu"));
});

test("writePth lists the backend folder because embedded Python ignores PYTHONPATH", () => {
  const d = tmp();
  fs.writeFileSync(path.join(d, "python312._pth"), "python312.zip\n.\n#import site\n");
  assert.ok(rt.writePth(d, "C:\\App\\resources\\backend"));
  const text = fs.readFileSync(path.join(d, "python312._pth"), "utf8");
  assert.match(text, /C:\\App\\resources\\backend/);
  assert.match(text, /^import site$/m);
  assert.match(text, /Lib\\site-packages/);
  assert.strictEqual(rt.writePth(tmp(), "x"), false);
});

test("findPython needs a matching ready marker and falls back to setup otherwise", () => {
  const data = tmp(), res = tmp();
  const req = path.join(tmp(), "requirements.txt");
  fs.writeFileSync(req, "a==1\n");
  assert.strictEqual(rt.findPython({ resourcesDir: res, dataDir: data, requirementsFile: req, env: {} }), null);
  const pyDir = path.join(data, "runtime", "python");
  const exe = rt.pythonExe(pyDir);
  fs.mkdirSync(path.dirname(exe), { recursive: true }); fs.writeFileSync(exe, "");
  fs.writeFileSync(path.join(data, "runtime", "ready.json"), JSON.stringify({ format: rt.SETUP_FORMAT, requirements: rt.sha(Buffer.from("a==1\n")) }));
  assert.strictEqual(rt.findPython({ resourcesDir: res, dataDir: data, requirementsFile: req, env: {} }).python, exe);
  fs.writeFileSync(req, "a==2\n"); // new app version with different libraries -> reinstall
  assert.strictEqual(rt.findPython({ resourcesDir: res, dataDir: data, requirementsFile: req, env: {} }), null);
  assert.strictEqual(rt.findPython({ resourcesDir: res, dataDir: data, requirementsFile: req, env: { LTXPS_PYTHON: exe } }).python, exe);
});

test("an offline-bundled interpreter wins over first-run setup", () => {
  const res = tmp();
  const exe = rt.pythonExe(path.join(res, "python"));
  fs.mkdirSync(path.dirname(exe), { recursive: true }); fs.writeFileSync(exe, "");
  const req = path.join(tmp(), "r.txt"); fs.writeFileSync(req, "x");
  const r = rt.findPython({ resourcesDir: res, dataDir: tmp(), requirementsFile: req, env: {} });
  assert.ok(r.bundled && r.python === exe);
});

const live = PY ? test : test.skip;
live("starts the real backend, serves the UI and stops when the parent goes away", async () => {
  const data = tmp();
  const info = await rt.startBackend({ python: PY, backendDir: BACKEND, uiDir: path.join(BACKEND, "..", "frontend", "dist"), dataDir: data, extraEnv: { LTXPS_ENGINE: "fake", LTXPS_FAKE_VRAM_MB: "4096" }, token: "t0k" });
  try {
    const health = await fetch(`http://127.0.0.1:${info.port}/api/health`, { headers: { Authorization: "Bearer t0k" } });
    assert.strictEqual(health.status, 200);
    const page = await fetch(info.url);
    assert.match(await page.text(), /VK Editor/);
    assert.strictEqual((await fetch(`http://127.0.0.1:${info.port}/api/system`)).status, 401);
  } finally { rt.killTree(info.child); }
});

live("the backend exits by itself when its parent process dies", async () => {
  const data = tmp();
  // A throw-away parent that launches the backend, prints its pid, then is killed.
  const script = `
    const rt = require(${JSON.stringify(path.join(__dirname, "..", "runtime"))});
    rt.startBackend({ python: process.env.LTXPS_PYTHON, backendDir: ${JSON.stringify(BACKEND)}, dataDir: ${JSON.stringify(data)}, extraEnv: { LTXPS_ENGINE: "fake" } })
      .then((i) => { console.log("CHILD " + i.child.pid); });`;
  const parent = require("child_process").spawn(process.execPath, ["-e", script], { env: process.env });
  const pid = await new Promise((resolve, reject) => {
    let out = "";
    parent.stdout.on("data", (d) => { out += d; const m = /CHILD (\d+)/.exec(out); if (m) resolve(Number(m[1])); });
    setTimeout(() => reject(new Error("no child pid")), 60000);
  });
  parent.kill("SIGKILL");
  const alive = () => { try { process.kill(pid, 0); return true; } catch { return false; } };
  const end = Date.now() + 15000;
  while (alive() && Date.now() < end) await new Promise((r) => setTimeout(r, 300));
  assert.ok(!alive(), "backend kept running after its parent died");
});

const { productFor, uiDirFor, PRODUCTS } = require("../products");
test("the shell picks the product from --product, the environment, then package.json", () => {
  assert.strictEqual(productFor({}, [], {}).id, "studio");
  assert.strictEqual(productFor({ product: "assistant" }, [], {}).id, "assistant");
  assert.strictEqual(productFor({ product: "assistant" }, ["--product=studio"], {}).id, "studio");
  assert.strictEqual(productFor({}, [], { LTXPS_PRODUCT: "assistant" }).id, "assistant");
  assert.strictEqual(productFor({ product: "nope" }, [], {}).id, "studio");
});

test("the assistant has its own data folder, requirements and no PyTorch", () => {
  const a = PRODUCTS.assistant, s = PRODUCTS.studio;
  assert.notStrictEqual(a.dataFolder, s.dataFolder);
  assert.notStrictEqual(a.portableFolder, s.portableFolder);
  assert.strictEqual(a.needTorch, false);
  assert.strictEqual(a.requirements, "requirements-assistant.txt");
  assert.ok(fs.existsSync(path.join(BACKEND, a.requirements)));
  assert.ok(fs.existsSync(path.join(__dirname, "..", a.splash)));
  assert.ok(a.minFreeGb < s.minFreeGb);
  assert.strictEqual(uiDirFor(a, { packaged: false, resourcesDir: "/r", root: "/p" }), path.join("/p", "assistant-ui", "dist"));
  assert.strictEqual(uiDirFor(a, { packaged: true, resourcesDir: "/r", root: "/p" }), path.join("/r", "ui"));
});

test("both electron-builder configs ship every file the shell requires", () => {
  const files = (name) => fs.readFileSync(path.join(__dirname, "..", name), "utf8");
  for (const cfg of ["electron-builder.yml", "electron-builder.assistant.yml"]) {
    const t = files(cfg);
    for (const f of ["main.js", "runtime.js", "products.js", "preload.js", "splash.js"]) assert.match(t, new RegExp(`- ${f.replace(".", "\\.")}`), `${cfg} is missing ${f}`);
  }
  assert.match(files("electron-builder.assistant.yml"), /product: assistant/);
  assert.match(files("electron-builder.assistant.yml"), /requirements-assistant\.txt/);
  assert.match(files("electron-builder.yml"), /assistant-ui/);
});

live("the assistant backend starts without PyTorch libraries and serves its own UI", async () => {
  const data = tmp();
  const info = await rt.startBackend({ python: PY, backendDir: BACKEND, uiDir: path.join(BACKEND, "..", "assistant-ui", "dist"), dataDir: data, mode: "assistant", token: "t0k" });
  try {
    const h = await fetch(`http://127.0.0.1:${info.port}/api/health`, { headers: { Authorization: "Bearer t0k" } });
    assert.strictEqual((await h.json()).product, "assistant");
    assert.match(await (await fetch(info.url)).text(), /AI Assistant/);
    assert.strictEqual((await fetch(`http://127.0.0.1:${info.port}/api/assistant/info`)).status, 401);
    const i = await fetch(`http://127.0.0.1:${info.port}/api/assistant/info`, { headers: { Authorization: "Bearer t0k" } });
    assert.ok((await i.json()).formats.includes("pptx"));
  } finally { rt.killTree(info.child); }
});

test("setup progress combines steps into one bar, with speed and time left", () => {
  const { SetupProgress, parsePipLine, fmtEta, fmtBytes } = require("../progress");
  let t = 0;
  const p = new SetupProgress([{ id: "a", label: "A", weight: 10 }, { id: "b", label: "B", weight: 90 }], () => t);
  p.begin("a"); p.file(5 * 1048576, 10 * 1048576); t = 10000; p.file(10 * 1048576, 10 * 1048576);
  p.begin("b");
  assert.ok(Math.abs(p.fraction - 0.1) < 1e-9);
  t = 20000; p.file(1 * 1048576, 100 * 1048576); t = 30000; p.file(11 * 1048576, 100 * 1048576);
  assert.ok(p.speed > 500 * 1024); // about 1 MB/s
  assert.ok(p.eta > 0);
  assert.match(p.detail(), /11 MB of 100 MB/);
  assert.deepStrictEqual(p.snapshot().steps.map((s) => s.state), ["done", "active"]);
  assert.deepStrictEqual(parsePipLine("Progress 123 of 456"), { done: 123, total: 456 });
  assert.strictEqual(parsePipLine("Downloading torch-2.5.0-cp312-win_amd64.whl (2.5 GB)").file, "torch-2.5.0-cp312-win_amd64.whl");
  assert.strictEqual(parsePipLine("random"), null);
  assert.strictEqual(fmtEta(10), "less than a minute");
  assert.strictEqual(fmtEta(600), "about 10 minutes");
  assert.strictEqual(fmtBytes(2.5 * 1024 ** 3), "2.5 GB");
});

test("a new file in the same step keeps the speed counter moving forward", () => {
  const { SetupProgress } = require("../progress");
  let t = 0;
  const p = new SetupProgress([{ id: "a", label: "A", weight: 1 }], () => t);
  p.begin("a"); p.file(8e6, 8e6); t = 4000; p.file(1e6, 5e6); t = 8000; p.file(5e6, 5e6);
  assert.ok(p.cum >= 13e6 - 1);
});

test("every local file the shell requires is packaged by both builders", () => {
  const root = path.join(__dirname, "..");
  for (const cfg of ["electron-builder.yml", "electron-builder.assistant.yml"]) {
    const listed = fs.readFileSync(path.join(root, cfg), "utf8");
    for (const f of ["main.js", "runtime.js", "progress.js", "products.js", "preload.js"]) {
      const src = fs.readFileSync(path.join(root, f), "utf8");
      for (const m of src.matchAll(/require\("\.\/([\w-]+)"\)/g)) {
        assert.ok(listed.includes(`- ${m[1]}.js`), `${cfg} does not package ${m[1]}.js (needed by ${f})`);
      }
    }
  }
});

test("a fresh install moves pinned libraries to the manifest's newest tested versions", () => {
  const out = rt.liveRequirements("fastapi==0.1.0\nfaster-whisper==1.0.0 ; python_version>'3'\n# note\nopencv_python.headless==1.0\n", {
    modules: [{ name: "faster-whisper", version: "1.2.1" }, { name: "opencv-python-headless", version: "5.0.0.93" }, { name: "evil name", version: "1" }, { name: "fastapi", version: "1; rm" }],
  });
  assert.match(out, /^fastapi==0\.1\.0$/m);                       // unlisted or malformed entries are left alone
  assert.match(out, /^faster-whisper==1\.2\.1 ; python_version>'3'$/m);
  assert.match(out, /^opencv_python\.headless==5\.0\.0\.93$/m);
  assert.strictEqual(rt.liveRequirements("a==1\n", null), "a==1\n");
});
