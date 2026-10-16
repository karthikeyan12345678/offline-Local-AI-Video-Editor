"use strict";
const { contextBridge, ipcRenderer } = require("electron");

// The splash page can only do these four things.
contextBridge.exposeInMainWorld("splash", {
  onStatus: (cb) => ipcRenderer.on("status", (_e, s) => cb(s)),
  retry: () => ipcRenderer.send("retry"),
  openLog: () => ipcRenderer.send("open-log"),
  quit: () => ipcRenderer.send("quit"),
});
