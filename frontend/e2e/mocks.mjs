// Fake Google sign-in, fake Google Drive, fake free-GPU Hugging Face Spaces and fake AI services for the browser tests.
// Nothing here talks to the real services, and no real key is used anywhere.
import { execFileSync } from "node:child_process";
import { readFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

export const CLIENT_ID = "test-client.apps.googleusercontent.com";
export const PROFILE = { sub: "1234567890", name: "Test Person", email: "test.person@example.com", picture: "" };

const dir = mkdtempSync(join(tmpdir(), "vk-e2e-"));
export const files = {
  video: join(dir, "motion.webm"), result: join(dir, "result.webm"), image: join(dir, "character.png"), resume: join(dir, "resume.txt"), jd: join(dir, "jd.txt"), csv: join(dir, "data.csv"), csv2: join(dir, "data2.csv"),
};
export function makeFiles() {
  const ff = (args) => execFileSync("ffmpeg", ["-y", "-loglevel", "error", ...args]);
  ff(["-f", "lavfi", "-i", "testsrc=size=320x240:rate=15:duration=3", "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-pix_fmt", "yuv420p", "-c:v", "libvpx", "-b:v", "300k", "-c:a", "libopus", "-shortest", files.video]);
  ff(["-f", "lavfi", "-i", "testsrc2=size=320x240:rate=15:duration=2", "-pix_fmt", "yuv420p", "-c:v", "libvpx", "-b:v", "300k", files.result]);
  ff(["-f", "lavfi", "-i", "color=c=red:size=256x256", "-frames:v", "1", files.image]);
  const { writeFileSync } = await_fs();
  writeFileSync(files.resume, "Jane Doe\njane@example.com | 555-0100\n\nSummary\nBackend engineer with Python and SQL experience.\n\nExperience\nSoftware Engineer, Acme Corp, 2019-2024\n- Built Python APIs serving 1M requests a day\n- Reduced SQL query time by 40 percent\n\nEducation\nBSc Computer Science, State University\n\nSkills\nPython, SQL, Docker\n");
  writeFileSync(files.jd, "We are looking for a backend engineer. Responsibilities: build Python services, design SQL schemas, deploy with Docker and Kubernetes, write tests. Requirements: 3 years of Python, SQL, Docker, Kubernetes, communication skills, teamwork and ownership of production systems.\n");
  writeFileSync(files.csv, "region,sales,units\nNorth,100,10\nSouth,250,22\nEast,175,15\nWest,90,8\n");
  writeFileSync(files.csv2, "region,sales,units\nNorth,120,12\nSouth,250,22\nEast,175,15\nCentral,60,5\n");
}
import * as fs from "node:fs";
const await_fs = () => fs;

const fakeGsi = `
window.google = { accounts: { oauth2: {
  initTokenClient: (cfg) => ({ requestAccessToken: (o) => { window.__gsi = (window.__gsi || 0) + 1; setTimeout(() => cfg.callback({ access_token: "fake-token", expires_in: 3600, scope: cfg.scope }), 30); } }),
  hasGrantedAllScopes: () => true, revoke: (t, cb) => cb && cb({}),
} } };`;

function gradioConfig(root, apis) {
  const comps = [], deps = [];
  let cid = 1;
  for (const [name, params] of Object.entries(apis)) {
    const ins = params.map((p) => { const id = cid++; comps.push({ id, type: "textbox", props: { label: p, value: "", name: "textbox" }, api_info: { type: "string" }, example_inputs: "a" }); return id; });
    const out = cid++; comps.push({ id: out, type: "video", props: { label: "out", name: "video" }, api_info: { type: "object" } });
    deps.push({ id: deps.length, targets: [[ins[0] ?? out, "click"]], inputs: ins, outputs: [out], backend_fn: true, js: null, queue: null, api_name: name, scroll_to_output: false, show_progress: "full", batch: false, max_batch_size: 4, cancels: [],
      types: { continuous: false, generator: false }, collects_event_data: false, trigger_after: null, trigger_only_on_success: false, trigger_mode: "once", show_api: true, zerogpu: true, rendered_in: null });
  }
  const cfg = { version: "5.9.1", mode: "blocks", app_id: 1, api_prefix: "/gradio_api", protocol: "sse_v3", enable_queue: true, auth_required: false, max_file_size: null, root, space_id: null, show_api: true, is_colab: false,
    stylesheets: [], theme: "default", title: "fake", components: comps, dependencies: deps, layout: { id: 0, children: comps.map((c) => ({ id: c.id })) } };
  const info = { named_endpoints: Object.fromEntries(Object.entries(apis).map(([n, params]) => [`/${n}`, { parameters: params.map((p) => ({ label: p, parameter_name: p, parameter_has_default: false, parameter_default: null, type: { type: "string" }, python_type: { type: "str", description: "" }, component: "Textbox" })), returns: [{ label: "out", type: { type: "object" }, python_type: { type: "dict", description: "" }, component: "Video" }], show_api: true }])), unnamed_endpoints: {} };
  return { cfg, info };
}

const LTX = { text_to_video: ["prompt", "negative_prompt", "input_image_filepath", "input_video_filepath", "height_ui", "width_ui", "mode", "duration_ui", "ui_frames_to_use", "seed_ui", "randomize_seed", "ui_guidance_scale", "improve_texture_flag"],
  image_to_video: ["prompt", "negative_prompt", "input_image_filepath", "input_video_filepath", "height_ui", "width_ui", "mode", "duration_ui", "ui_frames_to_use", "seed_ui", "randomize_seed", "ui_guidance_scale", "improve_texture_flag"] };
const ANIM = { animate_scene: ["input_video", "max_duration_s", "edited_frame", "rc_str", "resolution_choice"] };

/** @param {import('playwright').BrowserContext} ctx */
export async function installMocks(ctx, opts = {}) {
  const state = { gsi: 0, drive: null, driveWrites: 0, spaceCalls: [], llmCalls: [], hordeCalls: 0, quotaError: !!opts.quotaError };
  const result = readFileSync(files.result);
  const json = (route, body, status = 200, headers = {}) => route.fulfill({ status, contentType: "application/json", headers: { "access-control-allow-origin": "*", ...headers }, body: JSON.stringify(body) });

  await ctx.route("**/config.js", (r) => r.fulfill({ contentType: "text/javascript", body: opts.noGoogle ? "window.VK_CONFIG={};" : `window.VK_CONFIG={googleClientId:"${CLIENT_ID}"};` }));
  await ctx.route("https://accounts.google.com/gsi/client", (r) => r.fulfill({ contentType: "text/javascript", body: fakeGsi }));
  await ctx.route("https://www.googleapis.com/oauth2/v3/userinfo", (r) => json(r, PROFILE));
  // ---- Drive (appDataFolder)
  await ctx.route("https://www.googleapis.com/drive/v3/files?**", (r) => json(r, { files: state.drive ? [{ id: "drivefile1", modifiedTime: new Date().toISOString() }] : [] }));
  await ctx.route("https://www.googleapis.com/drive/v3/files/drivefile1?alt=media", (r) => json(r, state.drive));
  await ctx.route("https://www.googleapis.com/upload/drive/v3/files**", (r) => {
    const req = r.request(), body = req.postData() ?? "";
    state.driveWrites++;
    try {
      if (req.method() === "PATCH") state.drive = JSON.parse(body);
      else {
        const boundary = /boundary=(.+)$/.exec(req.headers()["content-type"] ?? "")[1];
        const parts = body.split("--" + boundary).filter((x) => x.includes("\r\n\r\n"));
        state.drive = JSON.parse(parts[1].split("\r\n\r\n").slice(1).join("\r\n\r\n").trim());
      }
    } catch (e) { state.driveParseError = String(e); }
    return json(r, { id: "drivefile1" });
  });
  // ---- Hugging Face Spaces (Gradio protocol)
  const hosts = { "ltx": ["Lightricks/ltx-video-distilled", LTX], "anim": ["alexnasa/Wan2.2-Animate-ZEROGPU", ANIM] };
  for (const [sub, [id]] of Object.entries(hosts)) {
    await ctx.route(`https://huggingface.co/api/spaces/${id}/host`, (r) => json(r, { host: `https://${sub}.hf.space`, subdomain: sub }));
  }
  await ctx.route(/https:\/\/huggingface\.co\/api\/spaces\/[^/]+\/[^/]+$/, (r) => json(r, { runtime: { stage: "RUNNING", hardware: { current: "zero-a10g" } } }));
  let sessions = {};
  await ctx.route(/https:\/\/(ltx|anim)\.hf\.space\/.*/, async (r) => {
    const u = new URL(r.request().url()), sub = u.hostname.split(".")[0], root = `https://${sub}.hf.space`;
    const apis = sub === "ltx" ? LTX : ANIM, { cfg, info } = gradioConfig(root, apis);
    if (r.request().method() === "OPTIONS") return r.fulfill({ status: 204, headers: { "access-control-allow-origin": "*", "access-control-allow-headers": "*", "access-control-allow-methods": "*" } });
    if (u.pathname === "/config") return json(r, cfg);
    if (u.pathname === "/gradio_api/info" || u.pathname === "/info") return json(r, info);
    if (u.pathname === "/gradio_api/upload") return json(r, ["/tmp/gradio/up/" + Math.random().toString(16).slice(2) + ".bin"]);
    if (u.pathname === "/gradio_api/queue/join") {
      const j = JSON.parse(r.request().postData() ?? "{}");
      state.spaceCalls.push({ space: sub, fn_index: j.fn_index, api: Object.keys(apis)[j.fn_index], data: j.data });
      sessions[j.session_hash] = j;
      return json(r, { event_id: "ev" + state.spaceCalls.length });
    }
    if (u.pathname === "/gradio_api/queue/data") {
      const id = "ev" + state.spaceCalls.length, ev = (o) => `data: ${JSON.stringify({ event_id: id, ...o })}\n\n`;
      if (state.quotaError) {
        return r.fulfill({ status: 200, contentType: "text/event-stream", headers: { "access-control-allow-origin": "*" },
          body: ev({ msg: "process_completed", success: false, output: { error: "You have exceeded your GPU quota (60s requested vs. 12s left). Try again in 0:07:21" } }) });
      }
      const out = sub === "ltx" ? [{ video: { path: "/tmp/gradio/r.webm", url: `${root}/gradio_api/file=/tmp/gradio/r.webm`, orig_name: "r.webm", meta: { _type: "gradio.FileData" } }, subtitles: null }, 1234]
        : [{ video: { path: "/tmp/gradio/r.webm", url: `${root}/gradio_api/file=/tmp/gradio/r.webm`, orig_name: "r.webm", meta: { _type: "gradio.FileData" } }, subtitles: null }];
      return r.fulfill({ status: 200, contentType: "text/event-stream", headers: { "access-control-allow-origin": "*" },
        body: ev({ msg: "estimation", rank: 0, queue_size: 1, rank_eta: 1 }) + ev({ msg: "process_starts", eta: 2 }) + ev({ msg: "process_completed", success: true, output: { data: out }, title: null }) });
    }
    if (u.pathname.startsWith("/gradio_api/file=")) return r.fulfill({ status: 200, contentType: "video/webm", headers: { "access-control-allow-origin": "*" }, body: result });
    return r.fulfill({ status: 404, body: "{}" });
  });
  // ---- chat AI (a Groq-shaped service)
  await ctx.route("https://api.groq.com/openai/v1/chat/completions", async (r) => {
    const body = JSON.parse(r.request().postData() ?? "{}");
    const all = (body.messages ?? []).map((m) => (typeof m.content === "string" ? m.content : "")).join("\n");
    state.llmCalls.push({ stream: !!body.stream, text: all.slice(-400), system: (body.messages?.[0]?.role === "system" ? body.messages[0].content : "").slice(0, 80) });
    let reply = "Hello! I am a test model. You said something.";
    const isTailor = /You are an expert resume writer/.test(all);
    if (!isTailor && (/Output only the Markdown/.test(all) || /slide deck in Markdown/.test(all))) reply = "# Project Status\n\nA one-page status report.\n\n## Summary\n\nEverything is on track.\n\n## Milestones\n\n| Milestone | Status |\n|---|---|\n| Design | Done |\n| Build | In progress |\n\n- Risk: schedule\n- Next: ship\n\n## Next steps\n\nShip the beta.";
    else if (/You are an expert resume writer/.test(all)) reply = "# Jane Doe\n\njane@example.com | 555-0100\n\n## Summary\n\nBackend engineer focused on Python, SQL and Docker.\n\n## Skills\n\nPython, SQL, Docker, Kubernetes\n\n## Experience\n\n### Software Engineer, Acme Corp\n\n2019-2024\n\n- Built Python APIs serving 1M requests a day\n- Reduced SQL query time by 40 percent\n\n## Education\n\nBSc Computer Science, State University";
    else if (/prompts for AI picture generators/.test(all) || /PICTURE|picture generators/.test(body.messages?.[0]?.content ?? "")) reply = "A detailed lighthouse at sunset, warm light, calm sea, watercolor style, soft clouds, wide shot";
    if (body.stream) {
      const parts = reply.match(/.{1,12}/gs) ?? [reply];
      return r.fulfill({ status: 200, contentType: "text/event-stream", headers: { "access-control-allow-origin": "*" },
        body: parts.map((p) => `data: ${JSON.stringify({ choices: [{ delta: { content: p } }] })}\n\n`).join("") + "data: [DONE]\n\n" });
    }
    return json(r, { choices: [{ message: { content: reply } }] });
  });
  await ctx.route("https://api.groq.com/openai/v1/models", (r) => json(r, { data: [{ id: "llama-3.3-70b-versatile" }, { id: "llama-3.1-8b-instant" }] }));
  // ---- picture engine (AI Horde): returns a real little PNG
  const png = execFileSync("ffmpeg", ["-loglevel", "error", "-f", "lavfi", "-i", "gradients=size=128x128:duration=1:rate=1", "-frames:v", "1", "-f", "image2pipe", "-c:v", "png", "-"]);
  await ctx.route("https://aihorde.net/api/v2/**", (r) => {
    const u = r.request().url(), m = r.request().method();
    if (m === "OPTIONS") return r.fulfill({ status: 204, headers: { "access-control-allow-origin": "*", "access-control-allow-headers": "*", "access-control-allow-methods": "*" } });
    if (u.endsWith("/generate/async")) { state.hordeCalls++; return json(r, { id: "job1" }); }
    if (u.includes("/generate/check/")) return json(r, { done: true, queue_position: 0, wait_time: 0 });
    if (u.includes("/generate/status/") && m === "GET") return json(r, { generations: [{ img: png.toString("base64"), censored: false }] });
    return json(r, {});
  });
  return state;
}
