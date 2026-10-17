// Copies the in-browser engine next to the site before it is built:
//  - Pyodide (Python in WebAssembly) and the wheels the video engine needs
//  - ffmpeg.wasm (the video encoder)
//  - the unchanged Python video engine from backend/ltxps/editor (plus a tiny browser stand-in for media.py)
// Nothing here is committed; `npm run build:web` runs it every time.
import { cpSync, existsSync, mkdirSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");
const out = join(root, "public", "engine");
const nm = join(root, "node_modules");
const engineSrc = resolve(root, "..", "backend", "ltxps", "editor");

rmSync(out, { recursive: true, force: true });
for (const d of ["pyodide", "ffmpeg", "py/ltxps/editor"]) mkdirSync(join(out, d), { recursive: true });

for (const f of ["pyodide.js", "pyodide.asm.js", "pyodide.asm.wasm", "python_stdlib.zip"]) cpSync(join(nm, "pyodide", f), join(out, "pyodide", f));
for (const f of readdirSync(join(root, "web", "wheels"))) cpSync(join(root, "web", "wheels", f), join(out, "pyodide", f));

cpSync(join(nm, "@ffmpeg/ffmpeg/dist/umd/ffmpeg.js"), join(out, "ffmpeg", "ffmpeg.js"));
cpSync(join(nm, "@ffmpeg/ffmpeg/dist/umd/814.ffmpeg.js"), join(out, "ffmpeg", "814.ffmpeg.js"));
cpSync(join(nm, "@ffmpeg/core/dist/umd/ffmpeg-core.js"), join(out, "ffmpeg", "ffmpeg-core.js"));
cpSync(join(nm, "@ffmpeg/core/dist/umd/ffmpeg-core.wasm"), join(out, "ffmpeg", "ffmpeg-core.wasm"));

const modules = ["__init__", "effects", "audiofx", "soundfx", "fonts", "project", "textimage", "drawimage", "render", "chat"];
const fontsDir = join(out, "py/ltxps/editor");
for (const m of modules) {
  const src = join(engineSrc, `${m}.py`);
  if (!existsSync(src)) throw new Error(`missing engine module ${src}`);
  cpSync(src, join(fontsDir, `${m}.py`));
}
writeFileSync(join(out, "py/ltxps/__init__.py"), '__version__ = "web"\n');
writeFileSync(join(fontsDir, "media.py"), '"""Browser stand-in for media.py: there is no subprocess, ffmpeg runs in WebAssembly."""\nNO_WINDOW = 0\n\n\ndef require_ffmpeg() -> str:\n    return "ffmpeg"\n');

// The AI Assistant's Python toolbox (documents, resume check, compare, analyse, themes) plus its browser bridge.
const asstSrc = resolve(root, "..", "backend", "ltxps", "assistant");
const asstOut = join(out, "py/ltxps/assistant");
mkdirSync(asstOut, { recursive: true });
for (const m of ["__init__", "analytics", "ats", "compare", "documents", "enhance", "extract", "images", "llm", "reference", "service", "store", "themes"]) cpSync(join(asstSrc, `${m}.py`), join(asstOut, `${m}.py`));
cpSync(join(asstSrc, "themes.json"), join(asstOut, "themes.json"));
cpSync(resolve(root, "..", "assistant-ui", "web", "bridge.py"), join(out, "py", "bridge.py"));
console.log("engine ready in", out);
