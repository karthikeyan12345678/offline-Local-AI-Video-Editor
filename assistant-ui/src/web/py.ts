// The assistant's Python toolbox (documents, resume check, compare, analyse, themes) running in the browser with Pyodide.
// The Python files are the same ones the desktop app uses; web/bridge.py only swaps the parts that need a server.
/* eslint-disable @typescript-eslint/no-explicit-any */

const engine = (p: string) => new URL("../engine/" + p, document.baseURI).href;

const MODULES = ["__init__", "analytics", "ats", "compare", "documents", "enhance", "extract", "images", "llm", "reference", "service", "store", "themes"];
const WHEELS = ["typing_extensions-4.11.0-py3-none-any.whl", "lxml-5.2.1-cp312-cp312-pyodide_2024_0_wasm32.whl", "et_xmlfile-2.0.0-py3-none-any.whl",
  "xlsxwriter-3.2.9-py3-none-any.whl", "openpyxl-3.1.5-py2.py3-none-any.whl", "pypdf-6.20.1-py3-none-any.whl", "python_docx-1.2.0-py3-none-any.whl",
  "python_pptx-1.0.2-py3-none-any.whl", "charset_normalizer-3.5.2-py3-none-any.whl", "reportlab-5.0.1-py3-none-any.whl"];

function loadScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = src; s.async = true;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error("Could not load the file engine. Check your internet connection and reload the page."));
    document.head.appendChild(s);
  });
}

export type Progress = (text: string) => void;
let progress: Progress | null = null;
export const onEngineProgress = (fn: Progress | null) => { progress = fn; };

let pyp: Promise<any> | null = null;
export function getPy(): Promise<any> {
  if (!pyp) {
    pyp = (async () => {
      progress?.("Starting the file engine (first time only, about 30 MB)…");
      await loadScript(engine("pyodide/pyodide.js"));
      const py = await (window as any).loadPyodide({ indexURL: engine("pyodide/") });
      await py.loadPackage(["pydantic", "pillow"]);
      for (const w of WHEELS) await py.loadPackage(engine("pyodide/" + w));
      py.FS.mkdirTree("/py/ltxps/assistant");
      py.FS.mkdirTree("/work/in");
      py.FS.mkdirTree("/work/out");
      py.FS.writeFile("/py/ltxps/__init__.py", '__version__ = "web"\n');
      await Promise.all([...MODULES.map((m) => `${m}.py`), "themes.json"].map(async (f) => {
        const r = await fetch(engine(`py/ltxps/assistant/${f}`));
        if (!r.ok) throw new Error("Part of the file engine is missing from this site.");
        py.FS.writeFile(`/py/ltxps/assistant/${f}`, new Uint8Array(await r.arrayBuffer()));
      }));
      py.runPython(await (await fetch(engine("py/bridge.py"))).text());
      return py;
    })();
    pyp.catch(() => { pyp = null; });
  }
  return pyp;
}

export class ToolError extends Error {}

/** Calls a bridge function. Throws ToolError with a readable message when the tool says no. */
export async function pcall<T = Record<string, any>>(fn: string, ...args: (string | number)[]): Promise<T> {
  const py = await getPy();
  const f = py.globals.get(fn);
  let out: string;
  try { out = f(...args); } finally { f.destroy?.(); }
  const r = JSON.parse(out);
  if (!r.ok) throw new ToolError(r.error || "That did not work.");
  return r as T;
}

const safe = (n: string) => n.replace(/[^\w.()+-]+/g, "_").slice(0, 100) || "file";

/** Puts a file where the Python code can open it (returns the path). */
export async function putFile(id: string, name: string, blob: Blob): Promise<string> {
  const py = await getPy();
  const path = `/work/in/${id}-${safe(name)}`;
  py.FS.writeFile(path, new Uint8Array(await blob.arrayBuffer()));
  return path;
}

/** Reads a file the Python code made, then removes it. */
export async function takeFile(path: string): Promise<Uint8Array> {
  const py = await getPy();
  const data = py.FS.readFile(path) as Uint8Array;
  try { py.FS.unlink(path); } catch { /* ignore */ }
  return new Uint8Array(data);
}

export async function dropInputs(): Promise<void> {
  const py = await getPy();
  for (const n of py.FS.readdir("/work/in") as string[]) if (n !== "." && n !== "..") { try { py.FS.unlink("/work/in/" + n); } catch { /* ignore */ } }
}
