"use strict";
const path = require("node:path");

/** Options for the Save As window shown for every download, so the person always chooses where a file goes. */
function saveDialogOptions(filename, downloadsDir) {
  const name = path.basename(String(filename || "video.mp4")) || "video.mp4";
  const ext = path.extname(name).replace(/^\./, "").toLowerCase();
  const filters = ext ? [{ name: ext.toUpperCase() + " file", extensions: [ext] }, { name: "All files", extensions: ["*"] }] : [{ name: "All files", extensions: ["*"] }];
  return { title: "Choose where to save", defaultPath: path.join(downloadsDir, name), filters, buttonLabel: "Save" };
}

/** Never saves silently: leaves the save path unset so Electron opens the dialog with these options. */
function attach(session, downloadsDir) {
  session.on("will-download", (_event, item) => {
    item.setSaveDialogOptions(saveDialogOptions(item.getFilename(), downloadsDir()));
  });
}

module.exports = { saveDialogOptions, attach };
