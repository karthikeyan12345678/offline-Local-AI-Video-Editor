// Browser tests for the website: run `npm run build:web`, then `node e2e/site.e2e.mjs` (needs: npm i -D playwright, and ffmpeg on the PATH).
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { CLIENT_ID, PROFILE, files, installMocks, makeFiles } from "./mocks.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const dist = join(here, "..", "dist-web");
const PORT = 4179, BASE = `http://127.0.0.1:${PORT}/`;
const exe = ["/opt/pw-browsers/chromium-1194/chrome-linux/chrome"].find(existsSync);
const shots = process.env.SHOTS || "";

let pass = 0; const fails = [];
const ok = (cond, name, extra = "") => { if (cond) { pass++; console.log("  ok  ", name); } else { fails.push(name); console.log("  FAIL", name, extra); } };
const step = (s) => console.log("\n" + s);

const server = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1", "--directory", dist], { stdio: "ignore" });
await new Promise((r) => setTimeout(r, 800));
makeFiles();

const browser = await chromium.launch({ executablePath: exe, args: ["--no-sandbox"] });
const ctx = await browser.newContext({ viewport: { width: 1360, height: 860 }, acceptDownloads: true });
const state = await installMocks(ctx);
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|favicon/.test(m.text())) errors.push(m.text()); });
const shot = async (n) => { if (shots) await page.screenshot({ path: join(shots, n + ".png") }); };

try {
  step("1. Landing page");
  await page.goto(BASE);
  await page.waitForSelector("h1");
  ok((await page.textContent("h1")).includes("AI video"), "headline shown");
  ok(await page.locator("img[alt*='timeline']").isVisible(), "banner screenshot (editor) shown");
  await page.getByRole("tab", { name: "AI Assistant" }).click();
  ok(await page.locator("img[alt*='AI Assistant'], img[alt*='documents']").first().isVisible(), "banner switches to the assistant screenshot");
  await page.getByRole("tab", { name: "Motion control" }).click();
  ok(await page.locator("img[alt*='Motion control']").isVisible(), "banner switches to motion control");
  const dl = await page.getByRole("link", { name: /Download from GitHub/ }).getAttribute("href");
  ok(dl === "https://github.com/karthikeyan12345678/offline-Local-AI-Video-Editor/releases/latest", "download button goes to the local repo releases", dl);
  ok(await page.getByRole("link", { name: /Read the guide and source/ }).getAttribute("href") === "https://github.com/karthikeyan12345678/offline-Local-AI-Video-Editor", "guide link goes to the local repo");
  await shot("01-landing");

  step("2. Sign in with Google (mocked)");
  await page.getByRole("button", { name: "Sign in with Google" }).first().click();
  await page.waitForSelector("text=Good", { timeout: 20000 }).catch(() => undefined);
  await page.waitForFunction(() => location.hash.startsWith("#/app"), null, { timeout: 20000 });
  await page.waitForSelector(".shell", { timeout: 30000 });
  ok(true, "signed in and workspace opened");
  ok((await page.textContent(".nav-account")).includes(PROFILE.name), "account chip shows the Google name");
  ok(await page.evaluate(() => Object.keys(localStorage).includes("vk_account_v1")), "profile saved for this browser");
  const stored = await page.evaluate(() => JSON.stringify(localStorage));
  ok(!stored.includes("fake-token"), "the Google access token is not written to storage");
  await shot("02-home");

  step("3. Home: new project, projects list, history");
  await page.getByRole("button", { name: /New project/i }).first().click();
  await page.getByRole("button", { name: /^Export/ }).first().waitFor({ timeout: 15000 });
  await shot("03-editor");
  ok(true, "New project opens the editor");
  await page.locator(".nav-item", { hasText: "Home" }).click();
  await page.waitForTimeout(500);
  const homeText = await page.locator("main, .page").first().innerText();
  ok(/New project/i.test(homeText), "history lists the new project");

  const nav = async (name) => { await page.locator(".nav-item", { hasText: name }).first().click(); await page.waitForTimeout(250); };
  const waitText = (t, timeout = 30000) => page.getByText(t, { exact: false }).first().waitFor({ timeout });

  step("4. Settings: free GPU token");
  await nav("Settings");
  await page.getByLabel(/Hugging Face token/).fill("hf_faketesttoken123");
  await page.getByRole("button", { name: "Save", exact: true }).first().click();
  await waitText("Saved in this browser");
  const hf = await page.evaluate(() => JSON.parse(localStorage.getItem("vk_hf_v1") || "{}"));
  ok(hf.token === "hf_faketesttoken123", "token saved in browser storage");
  await page.getByRole("button", { name: /Check the Spaces are awake/ }).click();
  await waitText("Awake and ready");
  ok(true, "Space status check works");
  await shot("04-settings-gpu");

  step("5. Text to video");
  await nav("Make video");
  await page.getByRole("tab", { name: "Text" }).click();
  await page.locator("textarea").first().fill("A lighthouse on a cliff at dawn");
  await page.getByRole("button", { name: "Generate" }).click();
  await page.getByRole("button", { name: "Edit this video" }).waitFor({ timeout: 60000 });
  let call = state.spaceCalls.at(-1);
  ok(call?.api === "text_to_video" && call.space === "ltx", "text_to_video endpoint called on the video Space", JSON.stringify(call));
  ok(JSON.stringify(call?.data).includes("A lighthouse on a cliff at dawn"), "the prompt reached the Space");
  ok(await page.locator("video").first().isVisible(), "result video is shown");
  await shot("05-text-video");

  step("6. Picture to video");
  await page.getByRole("tab", { name: "Picture" }).click();
  await page.locator(".slot input[type=file]").first().setInputFiles(files.image);
  await page.waitForSelector(".slot-filled", { timeout: 20000 });
  await page.locator("textarea").first().fill("The red square slowly zooms in");
  await page.getByRole("button", { name: "Generate" }).click();
  await page.getByRole("button", { name: "Edit this video" }).waitFor({ timeout: 60000 });
  call = state.spaceCalls.at(-1);
  ok(call?.api === "image_to_video", "image_to_video endpoint called", JSON.stringify(call));
  ok(JSON.stringify(call?.data).includes("gradio"), "the start picture was uploaded to the Space");
  await shot("06-picture-video");

  step("7. Continue a clip");
  await page.getByRole("tab", { name: "Continue" }).click();
  await page.getByRole("button", { name: "From library" }).first().click();
  await page.locator(".slot-pop button, .slot-pop .pick, .slot-pop [role=option]").first().click().catch(async () => { await page.locator(".slot-pop *").filter({ hasText: /Text to video/ }).first().click(); });
  await page.waitForSelector(".slot-filled", { timeout: 20000 });
  await page.locator("textarea").first().fill("The waves keep rolling");
  const before = state.spaceCalls.length;
  await page.getByRole("button", { name: "Generate" }).click();
  await page.getByRole("button", { name: "Edit this video" }).waitFor({ timeout: 90000 });
  ok(state.spaceCalls.length === before + 1 && state.spaceCalls.at(-1).api === "image_to_video", "continue sends the last frame as a picture (image_to_video)");
  await shot("07-continue");

  step("8. Quota message");
  state.quotaError = true;
  await page.getByRole("tab", { name: "Text" }).click();
  await page.locator("textarea").first().fill("Another try");
  await page.getByRole("button", { name: "Generate" }).click();
  await waitText("used up for now", 30000);
  const body = await page.locator("body").innerText();
  ok(/0:07:21/.test(body), "GPU quota error explains when it comes back");
  state.quotaError = false;
  await shot("08-quota");

  step("9. Motion control");
  await nav("Motion control");
  await page.locator(".mc-slots input[type=file], .slots input[type=file]").nth(0).setInputFiles(files.image);
  await page.locator(".mc-slots input[type=file], .slots input[type=file]").nth(1).setInputFiles(files.video);
  await page.waitForFunction(() => document.querySelectorAll(".slot-filled").length >= 2, null, { timeout: 30000 });
  await page.getByRole("button", { name: "Generate" }).click();
  await page.getByRole("button", { name: "Edit this video" }).waitFor({ timeout: 90000 });
  call = state.spaceCalls.at(-1);
  ok(call?.api === "animate_scene" && call.space === "anim", "animate_scene called on the motion Space", JSON.stringify(call)?.slice(0, 200));
  ok(JSON.stringify(call?.data).includes("Pose Retarget"), "default mode Pose Retarget sent");
  await shot("09-motion");

  step("10. Library and editor hand-off");
  await nav("Library");
  await page.waitForTimeout(500);
  const lib = await page.locator("main, .page").first().innerText();
  ok(/Text to video/.test(lib) && /Motion control/.test(lib), "generated videos are in the library", lib.slice(0, 200));
  await shot("10-library");
  await nav("Motion control");
  await page.getByRole("button", { name: "Edit this video" }).first().click();
  await page.waitForTimeout(3500);
  await nav("Home");
  await page.waitForTimeout(800);
  ok(await page.locator(".home-projects li").count() >= 1, "editing a generated video saves a project that Home lists", await page.locator("main").first().innerText());
  await shot("10b-home-projects");

  step("11. History on Home");
  await nav("Home");
  await page.waitForTimeout(600);
  const hist = await page.locator(".home-history").innerText();
  ok(/Made a video/.test(hist) && /Motion control/.test(hist), "history lists the AI videos", hist.slice(0, 300));
  await shot("11-home-history");

  step("12. AI Assistant (runs in the browser)");
  await page.evaluate(() => localStorage.setItem("aia_tour_done", "1"));
  await nav("AI Assistant");
  const fr = page.frameLocator(".assistant-frame");
  const fnav = (t) => fr.locator(".nav-item").filter({ hasText: new RegExp("^\\s*" + t + "\\s*$") }).first().click();
  await fr.locator(".nav-item", { hasText: "Settings" }).first().waitFor({ timeout: 20000 });
  await fnav("Settings");
  await fr.locator("#prov").selectOption("groq");
  await fr.locator("#key").fill("gsk_faketestkey_for_the_browser_test");
  await fr.getByRole("button", { name: "Save and test" }).click();
  await fr.getByText("Connected.").first().waitFor({ timeout: 20000 });
  ok(true, "assistant settings: key saved and the connection test passes");
  const llmSaved = await page.evaluate(() => JSON.parse(localStorage.getItem("vk_llm_v1") || "{}"));
  ok(llmSaved.provider === "groq" && llmSaved.providers?.groq?.api_key?.startsWith("gsk_"), "the chat key is kept in browser storage (shared with the editor chat)");
  await shot("12-assistant-settings");

  await fnav("Chat");
  const sendChat = async (txt) => { await fr.getByLabel("Message").fill(txt); await fr.getByRole("button", { name: "Send" }).click(); };
  await sendChat("Say hello please");
  await fr.getByText("I am a test model").first().waitFor({ timeout: 30000 });
  ok(state.llmCalls.at(-1)?.stream === true, "chat answer is streamed");
  await shot("12b-assistant-chat");

  await sendChat("/pdf a one-page project status report");
  await fr.getByText("Your PDF is ready").first().waitFor({ timeout: 120000 });
  const dl1 = page.waitForEvent("download");
  await fr.getByRole("link", { name: /Download/ }).last().click();
  const d1 = await dl1;
  const pdfPath = await d1.path();
  const { readFileSync } = await import("node:fs");
  ok(readFileSync(pdfPath).subarray(0, 5).toString() === "%PDF-", "the generated PDF downloads and is a real PDF", d1.suggestedFilename());
  await shot("12c-assistant-pdf");

  await sendChat("/ppt a short deck about project status");
  await fr.getByText("Your PPTX is ready").first().waitFor({ timeout: 120000 });
  const dl2 = page.waitForEvent("download");
  await fr.getByRole("link", { name: /Download/ }).last().click();
  const d2 = await dl2;
  ok(readFileSync(await d2.path()).subarray(0, 2).toString() === "PK", "the PowerPoint downloads and is a real .pptx", d2.suggestedFilename());
  await sendChat("/xlsx a sales table");
  await fr.getByText("Your XLSX is ready").first().waitFor({ timeout: 120000 });
  await sendChat("/doc a project brief");
  await fr.getByText("Your DOCX is ready").first().waitFor({ timeout: 120000 });
  await sendChat("/csv a small table");
  await fr.getByText("Your CSV is ready").first().waitFor({ timeout: 120000 });
  ok(true, "Excel, Word and CSV files are made too");

  await fr.locator("input[type=file]").first().setInputFiles(files.resume);
  await fr.locator(".chip", { hasText: "resume.txt" }).first().waitFor({ timeout: 20000 }).catch(() => undefined);
  await sendChat("check my resume against this job: " + "We are looking for a backend engineer with Python SQL Docker Kubernetes testing communication teamwork ownership and production experience");
  await fr.getByText("ATS estimate for").first().waitFor({ timeout: 60000 });
  ok(true, "resume ATS check from chat");
  await shot("12d-assistant-ats");

  await fr.locator("input[type=file]").first().setInputFiles([files.resume, files.jd]);
  await page.waitForTimeout(800);
  await sendChat("tailor my resume to this job description");
  await fr.getByText("Your tailored resume is ready").first().waitFor({ timeout: 180000 });
  ok(true, "resume tailoring (AI rewrite + file + new ATS score)");
  await shot("12e-assistant-tailor");

  await sendChat("/image a lighthouse at sunset");
  await fr.locator("img[src^='blob:']").last().waitFor({ timeout: 90000 });
  ok(state.hordeCalls >= 1, "image request went to the free picture engine");
  const imgOk = await fr.locator("img[src^='blob:']").last().evaluate((el) => el.complete && el.naturalWidth > 0);
  ok(imgOk, "the picture is shown");
  await shot("12f-assistant-image");

  await fnav("Compare files");
  const inputs = fr.locator("input[type=file]");
  await inputs.nth(await inputs.count() - 2).setInputFiles(files.csv);
  await inputs.nth(await inputs.count() - 1).setInputFiles(files.csv2);
  await page.waitForTimeout(600);
  await fr.getByRole("button", { name: "Compare", exact: true }).click();
  await fr.getByText(/similar|identical|changed|added|removed/i).locator("visible=true").first().waitFor({ timeout: 60000 });
  ok(true, "compare two files");
  await shot("12g-assistant-compare");

  await fnav("Analyse file");
  await inputs.nth(await inputs.count() - 1).setInputFiles(files.csv);
  await page.waitForTimeout(600);
  await fr.getByRole("button", { name: "Analyse", exact: true }).click();
  await fr.getByText(/4 rows|rows/i).locator("visible=true").first().waitFor({ timeout: 60000 });
  ok(true, "analyse a data file");

  await fnav("Files");
  await page.waitForTimeout(600);
  const filesText = await fr.locator("main").innerText();
  console.log("FILES>>", filesText.replace(/\n+/g, " | ").slice(0, 500));
  ok(/\.pdf/.test(filesText) && /\.pptx/.test(filesText), "Files list shows what was made");
  await nav("Home");
  await page.waitForTimeout(600);
  const ht = await page.locator(".home-history").innerText();
  console.log("HISTORY>>", ht.replace(/\n+/g, " | ").slice(0, 600));
  ok(/Assistant file|Made PDF|Made PPTX/i.test(ht), "assistant work shows up in the history");

  step("13. Drive copy (mocked) and no secrets leave the browser");
  await page.getByRole("button", { name: /Sync now|Reconnect Drive and sync/ }).click();
  await page.waitForFunction(() => /Synced|Last synced|synced \d|Could not|refused|expired/i.test(document.body.innerText.replace("Not synced in this session yet.", "")), null, { timeout: 30000 });
  console.log("SYNC>>", await page.locator("[role=status]").allInnerTexts());
  ok(!!state.drive && state.driveWrites >= 1, "projects and history were copied to Drive");
  const driveTxt = JSON.stringify(state.drive);
  ok(!/gsk_|hf_fake|fake-token/.test(driveTxt), "no key or token is in the Drive copy");
  ok(Object.keys(state.drive?.projects ?? {}).length >= 1 && (state.drive?.history?.length ?? 0) >= 1, "Drive copy holds projects and history");

  step("14. Sign in on a second computer: old projects and history come back");
  const ctx2 = await browser.newContext({ viewport: { width: 1360, height: 860 } });
  const state2 = await installMocks(ctx2);
  state2.drive = state.drive;
  const p2 = await ctx2.newPage();
  await p2.goto(BASE);
  await p2.getByRole("button", { name: "Sign in with Google" }).first().click();
  await p2.waitForSelector(".shell", { timeout: 30000 });
  await p2.waitForFunction(() => /Untitled|New project|Edited project|Made/.test(document.body.innerText), null, { timeout: 30000 });
  ok(true, "history and project list restored from Drive");
  await p2.screenshot({ path: shots ? join(shots, "14-second-computer.png") : undefined }).catch(() => undefined);
  await ctx2.close();

  step("15. Sign out and guest mode");
  await nav("Settings");
  await page.getByRole("tab", { name: "Account" }).click();
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.waitForSelector("h1", { timeout: 20000 });
  await page.waitForFunction(() => !localStorage.getItem("vk_account_v1"), null, { timeout: 10000 });
  ok(true, "sign out returns to the landing page and clears the profile");
  await page.getByRole("button", { name: /Try as a guest/ }).click();
  await page.waitForSelector(".shell", { timeout: 30000 });
  ok((await page.textContent(".nav-account")).includes("Guest"), "guest mode opens a workspace");

  step("16. Secrets scan of the built site");
  const { readdirSync, statSync } = await import("node:fs");
  const hits = [];
  const walk = (d) => { for (const n of readdirSync(d)) { const f = join(d, n); const st = statSync(f); if (st.isDirectory()) walk(f); else if (/\.(js|css|html|json|mjs|py|txt|md)$/.test(n) && st.size < 20e6) { const t = readFileSync(f, "utf8"); const m = /(hf_[A-Za-z0-9]{30,}|gsk_[A-Za-z0-9]{30,}|AIza[0-9A-Za-z_-]{35}|sk-ant-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9]{40,}|ghp_[A-Za-z0-9]{30,}|GOCSPX-[A-Za-z0-9_-]{20,})/.exec(t); if (m) hits.push(f + ": " + m[0].slice(0, 12) + "…"); } } };
  walk(dist);
  ok(hits.length === 0, "no API key or secret appears anywhere in the built site", hits.join("; "));
} catch (e) {
  fails.push("exception: " + (e?.stack || e)); console.log("EXCEPTION", e?.stack || e);
  if (shots) await page.screenshot({ path: join(shots, "failure.png") }).catch(() => undefined);
}
console.log("\npage errors:", errors.length ? errors : "none");
ok(errors.length === 0, "no page errors");
console.log(`\n${pass} passed, ${fails.length} failed`, fails);
await browser.close(); server.kill();
process.exit(fails.length ? 1 : 0);
