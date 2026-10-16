"use strict";
const { app, BrowserWindow, Menu, shell, ipcMain, dialog } = require("electron");
const fs = require("fs");
const path = require("path");
const rt = require("./runtime");
const { productFor, uiDirFor } = require("./products");

// ---------------------------------------------------------------- product (video studio or the separate AI Assistant)
const product = productFor(require("./package.json"), process.argv, process.env);
const TITLE = product.title;

// ---------------------------------------------------------------- locations
const resourcesDir = app.isPackaged ? process.resourcesPath : path.join(__dirname, "..");
const backendDir = app.isPackaged ? path.join(resourcesDir, "backend") : path.join(__dirname, "..", "backend");
const uiDir = uiDirFor(product, { packaged: app.isPackaged, resourcesDir, root: path.join(__dirname, "..") });
// The video studio also carries the assistant as a second window.
const assistantUiDir = product.id === "studio" ? (app.isPackaged ? path.join(resourcesDir, "assistant-ui") : path.join(__dirname, "..", "assistant-ui", "dist")) : undefined;
const requirementsFile = path.join(backendDir, product.requirements);

/** Portable build: everything (settings, models, videos, runtime) lives next to the .exe so the folder can be copied to another PC. */
function resolveDataDir() {
  if (process.env.LTXPS_DATA_DIR) return process.env.LTXPS_DATA_DIR;
  if (process.env.PORTABLE_EXECUTABLE_DIR) return path.join(process.env.PORTABLE_EXECUTABLE_DIR, product.portableFolder);
  const base = process.env.LOCALAPPDATA || app.getPath("appData");
  return path.join(base, product.dataFolder);
}
const dataDir = resolveDataDir();
const logFile = path.join(dataDir, "logs", "shell.log");
function log(line) {
  try { fs.mkdirSync(path.dirname(logFile), { recursive: true }); fs.appendFileSync(logFile, `${new Date().toISOString()} ${line}\n`); } catch (_) { /* logging must never crash the app */ }
}

// ---------------------------------------------------------------- state
let splash = null, win = null, backend = null, starting = false, quitting = false;
let status = { stage: "Starting…", fraction: null, detail: "", firstRun: false, error: null };

function setStatus(patch) {
  status = { ...status, ...patch };
  if (splash && !splash.isDestroyed()) splash.webContents.send("status", status);
}

function showSplash() {
  if (splash && !splash.isDestroyed()) return;
  splash = new BrowserWindow({
    width: 600, height: 420, resizable: false, minimizable: true, maximizable: false, show: false, autoHideMenuBar: true, title: TITLE, backgroundColor: product.background,
    webPreferences: { preload: path.join(__dirname, "preload.js"), contextIsolation: true, sandbox: true, nodeIntegration: false },
  });
  splash.removeMenu();
  // The splash page links the shared design tokens from <resources>/design.
  splash.loadFile(path.join(__dirname, product.splash));
  splash.webContents.once("did-finish-load", () => { splash.webContents.send("status", status); splash.show(); });
  splash.on("closed", () => { splash = null; if (!win && !quitting) app.quit(); });
}

// ---------------------------------------------------------------- main window
function openMain(info) {
  const origin = new URL(info.url).origin;
  win = new BrowserWindow({
    width: 1440, height: 900, minWidth: product.minWidth, minHeight: product.minHeight, show: false, title: TITLE, backgroundColor: product.background,
    webPreferences: { contextIsolation: true, sandbox: true, nodeIntegration: false, webSecurity: true },
  });
  // The only extra window ever allowed is the assistant, served by our own backend.
  win.webContents.setWindowOpenHandler(({ url }) => {
    try {
      const u = new URL(url);
      if (product.id === "studio" && u.origin === origin && u.pathname.startsWith("/assistant-app/")) {
        return { action: "allow", overrideBrowserWindowOptions: { width: 1280, height: 860, minWidth: 900, minHeight: 600, title: "AI Assistant", backgroundColor: "#2C2C2A", autoHideMenuBar: true, webPreferences: { contextIsolation: true, sandbox: true, nodeIntegration: false } } };
      }
    } catch (_) { /* not a valid URL: deny below */ }
    return { action: "deny" };
  });
  win.webContents.on("will-navigate", (e, url) => { if (new URL(url).origin !== origin) { e.preventDefault(); } });
  win.once("ready-to-show", () => { win.show(); if (splash && !splash.isDestroyed()) splash.destroy(); });
  win.on("closed", () => { win = null; app.quit(); });
  win.loadURL(info.url);
}

async function launch() {
  if (starting) return;
  starting = true;
  setStatus({ error: null, stage: "Starting…", fraction: null, detail: "" });
  showSplash();
  try {
    fs.mkdirSync(dataDir, { recursive: true });
    let py = rt.findPython({ resourcesDir, dataDir, requirementsFile });
    if (!py) {
      setStatus({ firstRun: true });
      py = await rt.setupRuntime({ dataDir, backendDir, requirementsFile, needTorch: product.needTorch, minFreeGb: product.minFreeGb, report: (stage, fraction, detail, extra) => { log(`setup: ${stage} ${detail || ""}`); setStatus({ stage, fraction, detail, steps: extra && extra.steps ? extra.steps : status.steps }); } });
    } else if (!py.bundled) {
      rt.writePth(py.dir, backendDir); // the app folder may have moved since last run
    } else if (py.dir.startsWith(resourcesDir)) {
      try { rt.writePth(py.dir, backendDir); } catch (_) { /* read-only install: bundled build already has the path set */ }
    }
    setStatus({ firstRun: false, stage: `Starting the ${product.engineName}`, fraction: null, detail: "Loading libraries — the first start after installing can take a minute." });
    backend = await rt.startBackend({ python: py.python, backendDir, uiDir, dataDir, mode: product.mode, assistantUiDir, onLog: (l) => log(`backend: ${l}`) });
    backend.child.on("exit", (code) => { log(`backend exited ${code}`); if (!quitting) { dialog.showErrorBox(TITLE, `The ${product.engineName} stopped unexpectedly (code ${code}). The app will close. Details: ${logFile}`); app.quit(); } });
    openMain(backend);
  } catch (err) {
    log(`launch failed: ${err.stack || err}`);
    setStatus({ error: String(err.message || err) });
    showSplash();
  } finally {
    starting = false;
  }
}

function repairRuntime() {
  const choice = dialog.showMessageBoxSync({ type: "question", buttons: ["Repair", "Cancel"], defaultId: 0, cancelId: 1, title: "Repair runtime",
    message: product.needTorch ? "Reinstall PyTorch and the app’s libraries?" : "Reinstall the app’s libraries?", detail: "Your videos, library and downloaded models are kept. This needs an internet connection and takes several minutes." });
  if (choice !== 0) return;
  try { fs.rmSync(path.join(dataDir, "runtime", "ready.json"), { force: true }); } catch (_) { /* nothing to remove */ }
  quitting = true; rt.killTree(backend && backend.child);
  app.relaunch(); app.exit(0);
}

let assistantWin = null;
function openAssistant() {
  if (!backend) return;
  if (assistantWin && !assistantWin.isDestroyed()) { if (assistantWin.isMinimized()) assistantWin.restore(); assistantWin.focus(); return; }
  const origin = new URL(backend.url).origin;
  assistantWin = new BrowserWindow({ width: 1280, height: 860, minWidth: 900, minHeight: 600, title: "AI Assistant", backgroundColor: "#2C2C2A", autoHideMenuBar: true,
    webPreferences: { contextIsolation: true, sandbox: true, nodeIntegration: false, webSecurity: true } });
  assistantWin.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  assistantWin.webContents.on("will-navigate", (e, url) => { if (new URL(url).origin !== origin) e.preventDefault(); });
  assistantWin.on("closed", () => { assistantWin = null; });
  assistantWin.loadURL(`${origin}/assistant-app/?t=${encodeURIComponent(backend.token)}`);
}

function buildMenu() {
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    { label: "File", submenu: [
      { label: "Open data folder", click: () => shell.openPath(dataDir) },
      { label: product.outputLabel, click: () => shell.openPath(path.join(dataDir, product.outputFolder)) },
      { type: "separator" }, { role: "quit" },
    ] },
    ...(product.id === "studio" ? [{ label: "Tools", submenu: [{ label: "Open AI Assistant (chat, PDF, PPT, Word, CSV, resume check…)", accelerator: "CmdOrCtrl+Shift+A", click: openAssistant }] }] : []),
    { label: "View", submenu: [{ role: "reload" }, { role: "togglefullscreen" }, { role: "resetZoom" }, { role: "zoomIn" }, { role: "zoomOut" }] },
    { label: "Help", submenu: [
      { label: "Open log file", click: () => shell.openPath(path.join(dataDir, "logs", "studio.log")) },
      { label: "Repair runtime…", click: repairRuntime },
      { type: "separator" }, { label: `Data folder: ${dataDir}`, enabled: false },
    ] },
  ]));
}

// ---------------------------------------------------------------- lifecycle
if (!app.requestSingleInstanceLock()) { app.quit(); } else {
  app.on("second-instance", () => { const w = win || splash; if (w) { if (w.isMinimized()) w.restore(); w.focus(); } });
  app.on("before-quit", () => { quitting = true; rt.killTree(backend && backend.child); });
  app.on("window-all-closed", () => app.quit());
  ipcMain.on("retry", () => launch());
  ipcMain.on("open-log", () => shell.openPath(logFile));
  ipcMain.on("quit", () => app.quit());
  app.whenReady().then(() => { buildMenu(); return launch(); });
}
