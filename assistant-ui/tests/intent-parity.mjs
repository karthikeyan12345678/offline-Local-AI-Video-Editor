// Checks that the browser's intent detection (src/web/intent.ts) answers exactly like the Python original on many sentences.
// Run: node tests/intent-parity.mjs   (needs the website built once: cd ../frontend && npm run build:web, for the Pyodide files)
import { build } from "esbuild";
import { readFileSync, readdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..", "..");
const tmp = mkdtempSync(join(tmpdir(), "intent-"));
await build({ entryPoints: [join(here, "..", "src", "web", "intent.ts")], bundle: true, format: "esm", outfile: join(tmp, "intent.mjs"), logLevel: "error" });
const { detectIntent } = await import(pathToFileURL(join(tmp, "intent.mjs")).href);

// Pyodide (a copy outside any "type": "module" folder, because its loader is CommonJS)
import { cpSync } from "node:fs";
const pyo = join(tmp, "pyo");
cpSync(join(root, "frontend", "public", "engine", "pyodide"), pyo, { recursive: true });
const req = createRequire(import.meta.url);
const { loadPyodide } = req(join(pyo, "pyodide.js"));
const py = await loadPyodide({ indexURL: pyo + "/" });
await py.loadPackage(["pydantic", "pillow"]);
for (const w of ["typing_extensions-4.11.0-py3-none-any.whl", "lxml-5.2.1-cp312-cp312-pyodide_2024_0_wasm32.whl", "et_xmlfile-2.0.0-py3-none-any.whl", "xlsxwriter-3.2.9-py3-none-any.whl", "openpyxl-3.1.5-py2.py3-none-any.whl", "pypdf-6.20.1-py3-none-any.whl", "python_docx-1.2.0-py3-none-any.whl", "python_pptx-1.0.2-py3-none-any.whl", "charset_normalizer-3.5.2-py3-none-any.whl", "reportlab-5.0.1-py3-none-any.whl"])
  await py.loadPackage("file://" + join(root, "frontend", "web", "wheels", w));
py.FS.mkdirTree("/py/ltxps/assistant"); py.FS.mkdirTree("/work/out");
py.FS.writeFile("/py/ltxps/__init__.py", '__version__ = "web"\n');
const src = join(root, "backend", "ltxps", "assistant");
for (const f of readdirSync(src)) if (/\.(py|json)$/.test(f)) py.FS.writeFile("/py/ltxps/assistant/" + f, readFileSync(join(src, f)));
py.runPython(readFileSync(join(root, "assistant-ui", "web", "bridge.py"), "utf8"));
const detect = py.globals.get("detect");

const cases = [
  ["hello there", 0], ["/pdf a status report", 0], ["/PPT pitch for a bakery", 0], ["/slides pitch", 0], ["/doc brief", 0], ["/word brief", 0], ["/csv table of cities", 0], ["/excel budget", 0], ["/xlsx", 0],
  ["/ats check this", 1], ["/resume", 1], ["/image a red fox", 0], ["/draw a cat", 0], ["/compare these", 2], ["/analyse", 1], ["/analyze data", 1], ["/design a pitch deck", 0], ["/unknown thing", 0],
  ["create a pdf about cats", 0], ["make a powerpoint presentation on solar power", 0], ["please generate an excel spreadsheet of expenses", 0], ["write a word document about onboarding", 0], ["build a deck for investors", 0],
  ["make a slide about cats", 0], ["draft a docx letter", 0], ["export this as csv", 0], ["convert my notes to pdf", 0],
  ["draw a picture of a dragon", 0], ["generate an image of a lighthouse", 0], ["make a logo for a bakery", 0], ["create a poster of a concert", 0], ["create an image of a cat", 1],
  ["compare these two files", 2], ["what changed between them", 2], ["which is better", 2], ["compare", 1], ["difference between the two", 3],
  ["tailor my resume to this job description", 1], ["customize my cv for this role", 1], ["optimize my resume for the ats and the jd", 2], ["rewrite my resume to match the job posting", 1], ["update the resume for this role", 1],
  ["check my resume", 1], ["what is my resume score", 1], ["applicant tracking check", 1], ["ats", 1],
  ["analyse this data", 1], ["give me insights", 1], ["summarize the data", 1], ["profile this file", 1], ["statistics please", 1],
  ["what is the best design for a bank report", 0], ["recommend a theme for a kids party", 0], ["suggest a style", 0], ["which template should I use", 0],
  ["tell me a joke", 0], ["explain photosynthesis", 0], ["summarise this", 1], ["translate to tamil", 1], ["what is a pdf", 0], ["I like slides", 0],
  ["Make me a PDF of the notes", 0], ["CREATE A XLSX", 0], ["write a csv of 5 rows", 0],
];
let bad = 0;
for (const [text, n] of cases) {
  const a = detectIntent(text, n), b = JSON.parse(detect(text, n));
  if (!b.ok) { console.log("python error for", JSON.stringify(text), b.error); bad++; continue; }
  if (a.kind !== b.kind || a.text !== b.text) { bad++; console.log("DIFFERENT:", JSON.stringify(text), n, "\n   browser:", a, "\n   python: ", { kind: b.kind, text: b.text }); }
}
console.log(`${cases.length - bad}/${cases.length} sentences give the same answer in the browser and in Python`);
process.exit(bad ? 1 : 0);
