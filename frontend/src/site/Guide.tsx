import { config } from "../../../shared/web/config";
import { currentProfile } from "../../../shared/web/account";
import { go } from "./route";
import "./site.css";

const TOC: [string, string][] = [
  ["start", "Quick start"], ["account", "Sign in and your history"], ["video", "Text, picture and continue"], ["motion", "Motion control"], ["assistant", "AI Assistant"],
  ["editor", "The editor"], ["free", "Free limits explained"], ["keys", "Free AI keys"], ["local", "Run it on your computer"], ["fix", "If something goes wrong"], ["privacy", "Privacy"],
];

export default function Guide() {
  const c = config();
  const me = currentProfile();
  const dl = `${c.localRepo}/releases/latest`;
  const top = (id: string) => (e: React.MouseEvent) => { e.preventDefault(); document.getElementById(id)?.scrollIntoView({ behavior: "smooth" }); };
  return (
    <div className="landing">
      <header className="l-head">
        <a className="l-brand" href="#/"><img src="logo.png" alt="" width={32} height={32} /><span>{c.siteName}</span></a>
        <nav className="l-nav" aria-label="Guide sections">{TOC.slice(0, 5).map(([id, t]) => <a key={id} href={`#${id}`} onClick={top(id)}>{t}</a>)}</nav>
        <button type="button" className="l-btn l-btn--light" onClick={() => go(me ? "app/home" : "")}>{me ? "Open my workspace" : "Back to the start"}</button>
      </header>
      <main className="l-guide">
        <aside className="l-toc" aria-label="On this page"><b>On this page</b><ul>{TOC.map(([id, t]) => <li key={id}><a href={`#${id}`} onClick={top(id)}>{t}</a></li>)}</ul></aside>
        <article>
          <h1>User guide</h1>
          <p className="l-sub">Everything on this website is free. This page explains each part and the honest limits.</p>

          <section id="start"><h2>Quick start</h2>
            <ol><li><b>Sign in with Google</b> on the start page (or choose guest mode).</li>
              <li>On <b>Home</b>, press <b>New project</b> or <b>Make a video</b>.</li>
              <li>Describe a scene in <b>Make video</b> and press <b>Generate</b>. A free cloud GPU makes it.</li>
              <li>Press <b>Edit this video</b> to put it on the timeline. Add text, filters, sounds. Press <b>Export</b> for an MP4.</li>
              <li>Come back any time: <b>Home</b> lists your old projects and a history of everything you made.</li></ol></section>

          <section id="account"><h2>Sign in and your history</h2>
            <p>Sign-in uses your Google account. The website asks for your name, email and picture, and for a <b>private app folder</b> in your Google Drive (it can not see your other Drive files). There is no password to remember and no server that stores your videos.</p>
            <ul><li><b>Projects:</b> Home lists old projects; <b>Open</b> continues one, <b>New project</b> starts a blank one.</li>
              <li><b>History:</b> every AI video, motion video, export, resume check or document is listed with the time. Use the filters to find things.</li>
              <li><b>Google Drive copy:</b> the project list and history are copied to your hidden Drive folder, so a new computer shows them after you sign in. Videos, pictures and sounds are <b>never</b> copied; they stay on the computer where you added them.</li>
              <li><b>Guest mode:</b> no Google. Everything stays in this browser only.</li>
              <li><b>Shared computer?</b> Sign out in Settings, then Account. Signing out does not delete files; use Settings, then Data to delete them.</li></ul></section>

          <section id="video"><h2>Text to video, picture to video, continue a clip</h2>
            <p>Open <b>Make video</b> and pick what to start from:</p>
            <ul><li><b>Text:</b> describe the subject, the action and the camera, for example “A lighthouse on a cliff at dawn, waves rolling in, the camera slowly pushes forward.”</li>
              <li><b>Picture:</b> choose a start picture (upload, or from your library) and describe the movement.</li>
              <li><b>Continue:</b> choose a clip. Its last picture becomes the first picture of the next few seconds. Chain several to build a longer story.</li></ul>
            <p>Choose a shape (YouTube, Shorts and Reels, square, feed) and <b>Fast</b> (saves free GPU time) or <b>Better</b> (sharper, uses more). The progress bar shows your place in the free queue.</p>
            <p className="l-note">Short clips of 2 to 5 seconds are the sweet spot. A longer clip uses more of your free GPU minutes.</p></section>

          <section id="motion"><h2>Motion control</h2>
            <p>A character picture repeats the movement of a person in a video.</p>
            <ol><li>Add a <b>character picture</b> (a clear picture of one person or character).</li>
              <li>Add a <b>motion video</b> of 3 to 30 seconds. Trim long ones in the editor first.</li>
              <li>Choose <b>Pose Retarget</b> (the character copies the moves, keeping your picture’s background) or <b>Character Swap</b> (the character replaces the person in the video).</li>
              <li>Choose <b>Low Res</b> (faster) or <b>Medium Res</b>, and how many seconds to make. Press <b>Generate</b>.</li></ol></section>

          <section id="assistant"><h2>AI Assistant</h2>
            <p>Open <b>AI Assistant</b>. It runs in your browser. Type a message, or start with a command:</p>
            <div className="l-table-wrap"><table className="l-table"><thead><tr><th scope="col">Type</th><th scope="col">You get</th></tr></thead><tbody>
              <tr><th scope="row">/pdf a one-page project report</th><td>A designed PDF</td></tr>
              <tr><th scope="row">/ppt a pitch for a bakery</th><td>A PowerPoint deck with notes</td></tr>
              <tr><th scope="row">/doc, /xlsx, /csv</th><td>A Word file, an Excel file, a CSV table</td></tr>
              <tr><th scope="row">/image a red fox in snow</th><td>A picture (free engine, no logo)</td></tr>
              <tr><th scope="row">Attach a resume, then “check my resume”</th><td>An ATS score with fixes</td></tr>
              <tr><th scope="row">Attach resume + job text, “tailor my resume”</th><td>A rewritten resume and a before and after score</td></tr>
              <tr><th scope="row">Attach two files, “compare these”</th><td>What changed, with a report</td></tr>
              <tr><th scope="row">Attach a data file, “analyse this”</th><td>Statistics and plain findings</td></tr></tbody></table></div>
            <p>Writing needs a chat AI. Pick a free one in <b>Settings</b> (see “Free AI keys” below). Building files, the resume check, compare and analyse run inside your browser.</p></section>

          <section id="editor"><h2>The editor</h2>
            <ul><li><b>Import</b> videos, pictures and sounds, or drag files into the window. Click one to put it on the timeline.</li>
              <li>Drag the ends of a block to trim. Press <b>S</b> to split.</li>
              <li>Left tabs: Audio (38 free sounds), Text (14 styles), Effects, Filters, Transitions. Fine-tune on the right under <b>Details</b>.</li>
              <li>Layers give picture-in-picture, green screen and masks. <b>◆ Key</b> adds keyframes.</li>
              <li>The chat box at the bottom edits for you: “make it vertical”, “add the title My Trip”.</li>
              <li><b>Export</b> makes MP4, WebM or GIF. It runs in your browser and takes roughly 10 to 15 times the video length. Keep the tab open.</li></ul></section>

          <section id="free"><h2>Free limits explained</h2>
            <div className="l-table-wrap"><table className="l-table"><thead><tr><th scope="col">Part</th><th scope="col">Free allowance</th></tr></thead><tbody>
              <tr><th scope="row">Editor and export</th><td>No limit. Uses your computer.</td></tr>
              <tr><th scope="row">AI video and motion control</th><td>Hugging Face free GPU time: about 5 minutes a day with a free account token, about 2 minutes without. It renews about 24 hours after you first used it. The meter on the Make video page shows your estimate.</td></tr>
              <tr><th scope="row">Chat and the Assistant</th><td>Your own free key from Groq, Gemini and others; each has a daily allowance that renews.</td></tr>
              <tr><th scope="row">Pictures</th><td>AI Horde: free, may queue. Hugging Face FLUX or Together: free token.</td></tr></tbody></table></div>
            <p className="l-note">Numbers come from the providers and change. Free GPUs are shared, so you can wait in a queue, and a Space can be asleep or paused by its owner. For no limits, run the desktop version.</p></section>

          <section id="keys"><h2>Free AI keys (2 minutes each)</h2>
            <ol><li><b>Hugging Face token</b> (for video): <a href="https://huggingface.co/join" target="_blank" rel="noreferrer">create a free account</a>, then <a href="https://huggingface.co/settings/tokens" target="_blank" rel="noreferrer">Settings, Access Tokens, New token, type Read</a>. Paste it in this site’s Settings, Free GPU video.</li>
              <li><b>Chat key</b>: <a href="https://console.groq.com/keys" target="_blank" rel="noreferrer">Groq</a> (fast) or <a href="https://aistudio.google.com/apikey" target="_blank" rel="noreferrer">Google Gemini</a>. Paste it in Settings, AI chat, then Save and test.</li></ol>
            <p className="l-note">Keys stay in this browser only and go only to the service they belong to. Never paste a key into an issue, a chat or a screenshot. If one leaks, delete it on the provider’s website and make a new one.</p></section>

          <section id="local"><h2>Run it on your computer</h2>
            <p>No daily limit and no queue. It is free and open source in its own repository.</p>
            <ol><li>Open <a href={dl} target="_blank" rel="noreferrer">the download page</a> and get the Windows installer.</li>
              <li>Double-click it. If Windows warns, choose <b>More info</b>, then <b>Run anyway</b>.</li>
              <li>The first start installs the AI parts by itself (about 5 to 10 GB, needs internet once).</li>
              <li>Prefer to run from source? The <a href={c.localRepo} target="_blank" rel="noreferrer">repository README</a> has the commands.</li></ol></section>

          <section id="fix"><h2>If something goes wrong</h2>
            <div className="l-table-wrap"><table className="l-table"><thead><tr><th scope="col">You see</th><th scope="col">Do this</th></tr></thead><tbody>
              <tr><th scope="row">“Your free GPU time is used up”</th><td>Wait for the time shown (it renews by itself), add a free Hugging Face token, or use the desktop version.</td></tr>
              <tr><th scope="row">The queue is long or stuck</th><td>Try again in a few minutes, or switch to Fast quality. Settings, Free GPU video, “Check the Spaces are awake”.</td></tr>
              <tr><th scope="row">“Space is paused” or “changed its inputs”</th><td>The Space’s owner changed it. Paste another Space name in Settings, Free GPU video, Advanced.</td></tr>
              <tr><th scope="row">Google sign-in window does not open</th><td>Allow pop-ups for this site and turn off ad blockers for it.</td></tr>
              <tr><th scope="row">Chat says the key is not accepted</th><td>Open Settings, AI chat, paste the key again and press Save and test.</td></tr>
              <tr><th scope="row">Export is slow or stops</th><td>Use 720p and shorter clips. Close other tabs. A laptop with 8 GB of memory handles a few minutes of video.</td></tr>
              <tr><th scope="row">Files vanished</th><td>Private windows and “clear site data” erase browser storage. Export what you want to keep.</td></tr></tbody></table></div></section>

          <section id="privacy"><h2>Privacy</h2>
            <ul><li>Your videos, pictures and sounds stay in your browser. The site has no server and no database.</li>
              <li>Only what you send on purpose leaves your computer: chat messages to the AI you chose, and pictures or clips to the Hugging Face Space when you press Generate.</li>
              <li>Google sign-in gives this site your name, email and picture, and a private Drive folder for the project list and history. Remove access any time in your Google Account, Security, Third-party connections.</li></ul></section>
        </article>
      </main>
      <footer className="l-foot"><p>Made by <b>Karthikeyan V</b></p>
        <p className="l-links"><a href="https://karthikeyanv.netlify.app" target="_blank" rel="noreferrer">Portfolio</a><a href="https://www.linkedin.com/in/karthikeyan-v-8a203a195" target="_blank" rel="noreferrer">LinkedIn</a><a href="https://github.com/karthikeyan12345678" target="_blank" rel="noreferrer">GitHub</a><a href={c.webRepo} target="_blank" rel="noreferrer">Website source</a></p></footer>
    </div>
  );
}
