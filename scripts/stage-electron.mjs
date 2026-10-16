// Copies the design tokens of one product next to the desktop shell so its splash screen uses them.
// Usage: node scripts/stage-electron.mjs [studio|assistant]
import { cpSync, mkdirSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const product = process.argv[2] === "assistant" ? "assistant" : "studio";
const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const dest = join(root, "electron", "design");
rmSync(dest, { recursive: true, force: true });
mkdirSync(dest, { recursive: true });
const src = join(root, "shared", product === "assistant" ? "design-claude" : "design");
for (const f of ["tokens.css", "components.css"]) cpSync(join(src, f), join(dest, f));
console.log(`staged ${product} design tokens ->`, dest);
