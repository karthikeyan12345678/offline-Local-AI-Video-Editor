"use strict";
/** One desktop shell, two products. `package.json` has a "product" field that electron-builder.assistant.yml sets to "assistant". */
const path = require("path");

const PRODUCTS = {
  studio: {
    id: "studio", title: "VK Editor", mode: "studio", engineName: "video engine",
    dataFolder: "LTXPortableStudio", portableFolder: "LTXStudioData",
    requirements: "requirements.txt", needTorch: true, minFreeGb: 8,
    splash: "splash.html", background: "#FFFFFF", minWidth: 1000, minHeight: 640,
    devUi: ["frontend", "dist"], resourceUi: "ui", outputFolder: "outputs", outputLabel: "Open videos folder",
    setupNote: "First start only: the app is downloading its runtime. Next time it opens in seconds.",
  },
  assistant: {
    id: "assistant", title: "AI Assistant", mode: "assistant", engineName: "assistant",
    dataFolder: "AIAssistantPortable", portableFolder: "AIAssistantData",
    requirements: "requirements-assistant.txt", needTorch: false, minFreeGb: 1.5,
    splash: "splash-assistant.html", background: "#2C2C2A", minWidth: 900, minHeight: 600,
    devUi: ["assistant-ui", "dist"], resourceUi: "ui", outputFolder: "files", outputLabel: "Open created files folder",
    setupNote: "First start only: the app is installing its libraries (about 150 MB). Next time it opens in seconds.",
  },
};

/** Order: --product=… (development), LTXPS_PRODUCT, then the "product" field electron-builder writes into package.json. */
function productFor(pkg, argv = [], env = {}) {
  const arg = argv.find((a) => typeof a === "string" && a.startsWith("--product="));
  const id = (arg && arg.slice(10)) || env.LTXPS_PRODUCT || (pkg && pkg.product);
  return PRODUCTS[id] || PRODUCTS.studio;
}

/** Folder the UI is served from, in a packaged app or from the source tree. */
function uiDirFor(product, { packaged, resourcesDir, root }) {
  return packaged ? path.join(resourcesDir, product.resourceUi) : path.join(root, ...product.devUi);
}

module.exports = { PRODUCTS, productFor, uiDirFor };
