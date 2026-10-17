import { useState } from "react";
import { config } from "../../../shared/web/config";
import { currentProfile } from "../../../shared/web/account";
import { isGoogleConfigured, signInGuest, signInWithGoogle } from "../../../shared/web/auth";
import { go } from "./route";
import "./site.css";

const SHOTS = [
  { id: "editor", tab: "Editor", src: "img/editor.webp", alt: "The VK Editor timeline with a video, effects and the free online AI chat", cap: "Cut, add text, filters, effects and sounds. Tell the chat what you want and it edits for you." },
  { id: "assistant", tab: "AI Assistant", src: "img/assistant.webp", alt: "The AI Assistant chat that makes documents, slides and spreadsheets", cap: "Chat, then get a PDF, slides, Word, Excel or CSV file. Check a resume, compare files, make images." },
  { id: "motion", tab: "Motion control", src: "img/motion.webp", alt: "Motion control: a character picture follows the moves of a reference video", cap: "Give a character picture and a video of someone moving. The character does the same moves." },
] as const;

const FEATURES = [
  { t: "Text to video", d: "Describe a scene in words. A free cloud GPU makes the clip." },
  { t: "Picture to video", d: "Bring a photo to life with motion and camera moves." },
  { t: "Continue a clip", d: "Take the last frame of a clip and make the next few seconds." },
  { t: "Motion control", d: "A character picture copies the moves of any reference video." },
  { t: "AI Assistant", d: "Chat, and make PDF, PowerPoint, Word, Excel and CSV files. Resume check, compare, analyse, images." },
  { t: "Full video editor", d: "Timeline, layers, green screen, masks, keyframes, 51 looks, 34 effects, 38 sounds, export to MP4." },
];

const STEPS = [
  { t: "Sign in with Google", d: "One click. Your projects and history are saved under your account." },
  { t: "Make or open a project", d: "Start new, or pick up an old one from your Home page." },
  { t: "Generate, edit, export", d: "Make clips, put them on the timeline, press Export for an MP4." },
];

const FREE: [string, string, string][] = [
  ["Editor, effects, sounds, export", "Free, no limit", "Runs in your browser. Files stay on your computer."],
  ["Chat that edits for you", "Free with a free key", "You create a key at Groq, Gemini or similar. Renews daily."],
  ["AI video (text, picture, continue, motion)", "Free, a few minutes a day", "Uses free Hugging Face GPU time (about 5 minutes a day with a free account). Shared GPUs can queue."],
  ["Sign-in, projects, history", "Free", "Saved in your browser, plus an optional private copy in your own Google Drive."],
  ["No limits, no queue", "Run it on your computer", "Download the free desktop version below."],
];

const FAQ: [string, string][] = [
  ["Do I have to pay for anything?", "No. Every part uses a free plan. Free plans have daily limits that renew, and the site shows what is left."],
  ["Where are my videos kept?", "In your browser, on your computer. They are never uploaded to this site. Only when you press Generate does the picture or clip you chose go to the free GPU Space."],
  ["Why do I sign in with Google?", "So your projects and history are kept per account. The site asks for your name, email and a private app folder in your Drive. It can not see your other Drive files."],
  ["Can I use it without Google?", "Yes, choose guest mode. Your work stays in this browser only and there is no cloud copy."],
  ["Why is AI video limited?", "A video model needs a strong graphics card. A website has none, so the site borrows free shared GPUs. For no limits, run the desktop version on your own computer."],
  ["Is my key safe?", "Keys you paste are stored only in your browser and sent only to the service you chose. They are never in the site's code or on GitHub."],
];

export default function Landing() {
  const c = config();
  const [shot, setShot] = useState(0);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const me = currentProfile();
  const s = SHOTS[shot];
  const dl = `${c.localRepo}/releases/latest`;

  const start = async () => {
    setErr("");
    if (me) { go("app/home"); return; }
    setBusy(true);
    try { await signInWithGoogle(); go("app/home"); location.reload(); }
    catch (e) { setErr(e instanceof Error ? e.message : "Sign-in failed."); }
    finally { setBusy(false); }
  };
  const guest = () => { signInGuest(); go("app/home"); location.reload(); };

  return (
    <div className="landing">
      <header className="l-head">
        <a className="l-brand" href="#/"><img src="logo.png" alt="" width={32} height={32} /><span>{c.siteName}</span></a>
        <nav className="l-nav" aria-label="Page sections">
          <a href="#features" onClick={(e) => { e.preventDefault(); document.getElementById("features")?.scrollIntoView({ behavior: "smooth" }); }}>Features</a>
          <a href="#free" onClick={(e) => { e.preventDefault(); document.getElementById("free")?.scrollIntoView({ behavior: "smooth" }); }}>Is it free?</a>
          <a href="#local" onClick={(e) => { e.preventDefault(); document.getElementById("local")?.scrollIntoView({ behavior: "smooth" }); }}>Download</a>
          <a href="#faq" onClick={(e) => { e.preventDefault(); document.getElementById("faq")?.scrollIntoView({ behavior: "smooth" }); }}>FAQ</a>
          <a href="#/guide">Guide</a>
        </nav>
        <button type="button" className="l-btn l-btn--light" onClick={() => void start()} disabled={busy}>{me ? "Open my workspace" : "Sign in with Google"}</button>
      </header>

      <main>
        <section className="l-hero">
          <p className="l-eyebrow">Free AI video studio</p>
          <h1>Make, continue and edit AI video in your browser</h1>
          <p className="l-lead">Text to video, picture to video, clip continue, motion control and an AI assistant, with a full editor. Sign in with Google and your projects and history are waiting next time.</p>
          <div className="l-cta">
            <button type="button" className="l-btn l-btn--blue" onClick={() => void start()} disabled={busy}>{busy ? "Opening Google…" : me ? "Open my workspace" : "Sign in with Google"}</button>
            <a className="l-btn l-btn--ghost" href={dl} target="_blank" rel="noreferrer">Download for your computer</a>
          </div>
          {!me && <p className="l-small">{isGoogleConfigured() ? <>No account? <button type="button" className="l-link" onClick={guest}>Try as a guest</button> (saved in this browser only)</> : <>Google sign-in is not set up on this copy yet. <button type="button" className="l-link" onClick={guest}>Continue as a guest</button></>}</p>}
          {err && <p className="l-error" role="alert">{err}</p>}

          <div className="l-banner">
            <div className="l-tabs" role="tablist" aria-label="Product screenshots">
              {SHOTS.map((x, i) => <button key={x.id} type="button" role="tab" id={`tab-${x.id}`} aria-selected={i === shot} aria-controls="shot-panel" className="l-tab" onClick={() => setShot(i)}>{x.tab}</button>)}
            </div>
            <figure id="shot-panel" role="tabpanel" aria-labelledby={`tab-${s.id}`} className="l-shot">
              <img src={s.src} alt={s.alt} width={1600} height={900} />
              <figcaption>{s.cap}</figcaption>
            </figure>
          </div>
        </section>

        <section id="features" className="l-sec">
          <h2>Everything in one place</h2>
          <ul className="l-grid">{FEATURES.map((f) => <li key={f.t} className="l-card"><h3>{f.t}</h3><p>{f.d}</p></li>)}</ul>
        </section>

        <section className="l-sec l-sec--grey">
          <h2>How it works</h2>
          <ol className="l-steps">{STEPS.map((x, i) => <li key={x.t}><span className="l-num" aria-hidden="true">{i + 1}</span><h3>{x.t}</h3><p>{x.d}</p></li>)}</ol>
        </section>

        <section id="free" className="l-sec">
          <h2>Is it really free?</h2>
          <p className="l-sub">The honest answer, part by part.</p>
          <div className="l-table-wrap"><table className="l-table"><thead><tr><th scope="col">Part</th><th scope="col">Cost</th><th scope="col">How</th></tr></thead>
            <tbody>{FREE.map((r) => <tr key={r[0]}><th scope="row">{r[0]}</th><td>{r[1]}</td><td>{r[2]}</td></tr>)}</tbody></table></div>
        </section>

        <section id="local" className="l-sec l-sec--dark">
          <h2>Run it on your own computer</h2>
          <p className="l-sub">No daily limit and no queue. The desktop version is free and open source in its own repository.</p>
          <ol className="l-local">
            <li>Open the download page and get the Windows installer.</li>
            <li>Double-click it. If Windows warns, choose More info, then Run anyway.</li>
            <li>The first start installs the AI parts by itself (about 5 to 10 GB).</li>
          </ol>
          <div className="l-cta">
            <a className="l-btn l-btn--light" href={dl} target="_blank" rel="noreferrer">Download from GitHub</a>
            <a className="l-btn l-btn--ghost" href={c.localRepo} target="_blank" rel="noreferrer">Read the guide and source</a>
            <a className="l-btn l-btn--ghost" href="#/guide">Website user guide</a>
          </div>
        </section>

        <section id="faq" className="l-sec">
          <h2>Questions</h2>
          <div className="l-faq">{FAQ.map(([q, a]) => <details key={q}><summary>{q}</summary><p>{a}</p></details>)}</div>
        </section>
      </main>

      <footer className="l-foot">
        <p>Made by <b>Karthikeyan V</b></p>
        <p className="l-links"><a href="https://karthikeyanv.netlify.app" target="_blank" rel="noreferrer">Portfolio</a><a href="https://www.linkedin.com/in/karthikeyan-v-8a203a195" target="_blank" rel="noreferrer">LinkedIn</a><a href="https://github.com/karthikeyan12345678" target="_blank" rel="noreferrer">GitHub</a><a href={c.webRepo} target="_blank" rel="noreferrer">Website source</a></p>
        <p className="l-small">Free, personal project, no guarantee. AI can make mistakes.</p>
      </footer>
    </div>
  );
}
