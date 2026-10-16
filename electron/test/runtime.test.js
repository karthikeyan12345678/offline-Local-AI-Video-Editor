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
    assert.match(await page.text(), /LTX Portable Studio/);
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
