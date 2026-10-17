# VK Editor — the "explain it like I'm 10" guide

Two parts: **A. How YOU put it on GitHub and share it** and **B. What the person you share it with does**.

---

## A. For you (the maker)

Think of **GitHub** as a big shared folder on the internet, and a **Release** as a shop shelf in that folder where people can download your finished app.

### One-time: put the files on GitHub
1. Open **PowerShell** in your project folder (`F:\LTXPortableStudio-source 2\app`): in File Explorer click the address bar, type `powershell`, press Enter.
2. Copy these lines, one block at a time, pressing Enter after each:
   ```powershell
   git add -A
   git commit -m "VK Editor 1.2.3: drawing, AI chat editor, auto setup, updates"
   git push
   ```
   (If `assistant-ui\package-lock.json` still exists, delete it first — it breaks the Windows build.)
3. Go to your repository page → **Actions** tab. A yellow circle means "the robot is building your app". Wait until it turns into a green tick (about 15–25 minutes).

### Make the download page (the "Release")
1. In PowerShell type these two lines (the `v1.2.3` must match the version in `electron/package.json`):
   ```powershell
   git tag v1.2.3
   git push origin v1.2.3
   ```
2. Wait for the robot again (Actions tab). When it is green, open your repository → right side → **Releases**. You will see **v1.2.3** with the files:
   - `VKEditor-Setup-1.2.3.exe` — normal installer
   - `VKEditor-1.2.3-portable.exe` — runs from any folder, nothing to install
   - `AIAssistant-…exe` — the separate AI Assistant app
3. **Share this one link** with anyone: `https://github.com/karthikeyan12345678/offline-Local-AI-Video-Editor/releases/latest`
   (The repository must be **Public** for strangers to download. In a private repository only people you invite can.)

### When you make a new version
1. Change the version number (example `1.2.3`) in `electron/package.json`, `frontend/package.json`, `backend/ltxps/__init__.py`.
2. Refresh the "what is new" list so users get the update button (it reads the version you set in step 1):
   ```powershell
   python scripts\make_update_manifest.py "What is new in 1.2.3"
   ```
3. `git add -A`, `git commit -m "1.2.3"`, `git push`, then `git tag v1.2.3` and `git push origin v1.2.3`.

---

## B. For the person you share it with

1. Download **VKEditor-Setup-….exe** (or the *portable* one) from the link you were sent.
2. Double-click it. Windows may say **"Windows protected your PC"** → click **More info** → **Run anyway**. (This appears for every new app that is not paid-signed; it is normal.)
3. **First start = automatic setup.** A window shows each step with a tick, the **speed**, how much is downloaded and the **time left**. You do not need to know what Node, npm or Python are — everything is installed for you. Keep the PC on and connected to the internet. It can take 10–40 minutes, once.
4. On the Welcome screen press **Install everything (one click)**. The app checked your PC and chose the best video model, captions model and picture-maker for it. You see the total size, the speed (MB/s and Mb/s) and the time left. Close the app any time; it carries on where it stopped.
5. Make videos in **Make video**, then edit in **Editor**:
   - **Draw** button: pen, highlighter, line, arrow, circle, box on the picture.
   - **AI chat** button: type what you want ("make it vertical", "add a fade", "put the title My Trip"), or add a PNG/JPG picture as a reference. The AI edits the timeline; press **Ctrl+Z** to undo.
   - For the chat, press **Use the free online AI** in the chat's AI settings for the easiest start, or open **AI settings** in the chat box once and pick an AI (Ollama is free and runs on your PC; Gemini/OpenRouter/Groq have free keys).
6. **Drag and drop** videos, pictures or music into the editor window. **Projects** keeps every draft: open, rename, make a copy or delete. In the **AI chat**, the bin button deletes the whole chat.
7. **Pictures from words:** open **AI Assistant → Images**. After the one-click install it uses the picture model on your own PC.
8. **Updates:** when the PC is online and something new exists, the **Settings** button gets a dot. Open **Settings → Updates → Update AI modules**. It downloads only what changed. **Settings → AI modules and versions** lists every module with its version; choose an older version (the ones used before are listed) or any other version and press Install.

### If something goes wrong
- Stuck on setup → close the app and open it again. It continues where it stopped.
- "No internet" → connect and reopen.
- Windows antivirus blocks it → choose "Allow" (the app is not signed yet).


**Reinstalling?** A fresh install always fetches the newest tested module versions from the internet first, and your models and projects stay in the data folder.

## What is new in 1.2.4

- **Pictures without a logo.** The AI Assistant now uses the free AI Horde service by default (no watermark, no account; it may queue for a minute or two). If you installed "Install everything", the model on your PC is used instead: private, no limits, no logo. The old Pollinations service is only a last-resort backup and the reply tells you when it was used (it adds a small logo and has quotas).
- **Documents that copy your file.** Attach a PDF, Word or PowerPoint file and ask `/pdf`, `/doc` or `/ppt` for something new. The AI follows that file's section order, length and tone, and the document uses its main colour and font.
- **AI object edits in the chat editor.** Mark a place with the Draw tool (box, circle or scribble) and say "remove this hill", "remove the person", "change the hill to a snowy mountain". Or say "put a white cap on his head" (it finds the face). It repaints the video frames with an inpainting model (Models page → "Object editor: AI inpainting", about 2.2 GB, graphics card needed). Up to 8 seconds per clip per request. Still camera: fast "patch" mode. Moving person or camera: slower "track" mode, which may flicker a little. Undo restores the original.
- Not included: Kling-style "Motion Control" (a character picture driven by a motion video). It needs a model far bigger than a 6 GB card can run.

## What is new in 1.2.5

- **Motion control** (new page in the left menu): choose a character picture and a video of someone moving; Kling 2.6 makes the character perform that movement. It runs in the cloud through your own fal.ai key (Dashboard → Keys; add a little credit). The motion video must be 3–30 s (3–10 s if you keep the picture's direction). Nothing is sent until you press the button.
- **Kling Studio look**: Settings → Look → "Kling Studio" (dark with Kling's green).
- **AI edits work on pictures too.** A picture on the timeline can now be repainted (mark the place with Draw, then "change the hill to a snowy mountain"). The object-editor model must be installed first (Models page).
- **Pictures in the AI Assistant**: if the model on your PC fails, the free online engine is used automatically and the reply says why.

## 1.2.6
- Fixed the "Access was refused (401)" error when downloading "Object editor: AI inpainting": it now uses the open Stable Diffusion inpainting repository. Press "Resume download" again after updating.

## 1.2.7
- **Object editor (AI inpainting)** no longer crashes on newer `diffusers` (`enable_vae_slicing` error); the same fix covers the local picture maker.
- **Studio look** is now the default (dark, green accent, Google Sans type). "Classic (light)" is still in Settings → Look. The Kling name is gone from the app.
- **Library**: Select → pick several (or Select all) → Delete selected. Deleted files can be uploaded again.
- **Drag and drop** works anywhere in the window, plus an "Add files" button in the Library and the editor's Media panel. If dropping still does nothing, the app is probably running as administrator (Windows blocks drops into elevated windows): untick "Run as administrator" in the exe's Properties → Compatibility.
- **Make a video** redesigned: result stage on top, prompt bar at the bottom, shape chips (16:9, 9:16, 1:1, 4:5), live timer, progress bar, time left and stage flow. When Generate is greyed out the reason is written next to it (models still downloading with %, or prompt missing).
- **Formats**: editor Format menu for YouTube 16:9, YouTube Shorts, Instagram Reels, Instagram Feed 4:5 and Square, "Fill the frame", length warnings at export, and chat commands ("make it for Reels").

## 1.2.8
- **Editor redesigned in the Google Flow style** (nothing removed): project title and format menu on top, big centred preview with a round play button, a floating tool strip (Split, Duplicate, Delete, Add text, Draw, Add media, zoom), a full-width thumbnail timeline with a **+** at its end, and a right panel with **Settings / Media / History** tabs (Hide panel in the top bar).
- **AI chat is now a prompt bar** at the bottom ("Describe how to edit this video…"): **+** attaches reference pictures from a Flow-style media picker (All, Videos, Images, Voices, Sound & music, Uploads, search, sort, preview, Upload media), the chip shows which AI is connected, the round arrow sends. The conversation opens above the bar; Undo, Delete chat and AI settings are still there.
- **History tab**: every edit is a step; click one to jump back or forward.
- **Sound and voice while generating**: on Make video, "Sound on" adds a voice-over (the voices installed in Windows), a background sound that matches your prompt (sea, rain, wind, fire, city, night, space or calm music) and optional soft music. Also in chat: "make a video of … with a voice saying …" and "add rain sound to this clip".
  The background sounds are synthesised on this PC (not AI-generated recordings); the voice is the Windows voice, so quality depends on the voices you have installed (Settings → Time & language → Speech).

## 1.2.9
- **Make video**: **Start picture** and **End picture** slots (the video begins on one and finishes on the other). Every picture or video has a round **×** to remove it, **Upload another**, **From library**, and you can drop a file on it. **Minimise view** shrinks the page to a small progress bar and the prompt. The Voice & sound options are folded away until you press "Voice & sound". If the installed video library cannot end on a picture, the video still uses the start picture and says so.
- **Motion control** redesigned: inputs on the left (character picture and motion video, each with ×, upload and drop), the result on the right, short Direction and Quality switches.
- **AI Assistant** has a new look (warm dark paper, serif headings, line icons, a rounded message box with round attach and send buttons). **Pictures show a progress bar** with the time passed.
- **Tailor my resume**: attach a resume (PDF, Word, text or CSV) and a job description (a second file or pasted in the message) and say "tailor my resume to this JD with high ATS score". You get a new PDF (or Word file if you ask) that only uses facts from your resume, plus the ATS score before and after and the job terms that could not be added honestly.
- **Saving always asks where**: every export and "Save as…" opens the Save As window in the desktop app, and a finished export opens it automatically.

## 1.2.10
- **Faster videos on 6 GB graphics cards (RTX 4050, 3050, 2060…)**: these cards now use the Lite profile (8-bit weights). Before, the full-size weights filled the 6 GB and Windows quietly moved the overflow into normal RAM, which made each step take minutes. The profile names now read Lite (4-7 GB) and Balanced (8-11 GB).
- The log file now records which memory strategy and graphics card each video used.

## 1.2.11 – why videos took hours, and what is new
- **Your graphics card was wrongly rejected.** Settings showed "no kernels for this GPU (compute 8.9)". The check wanted an exact `sm_89` match, but the CUDA 13 PyTorch build ships `sm_86` and `sm_90`, which an RTX 40-series card runs fine. The app then used the CPU, which is why a 4-second clip took hours. The check now follows NVIDIA's real compatibility rule and also runs a tiny kernel on the card to prove it works.
- **Time estimate before you press Generate**, from your graphics card, memory and the chosen size, with tips when it would be too slow. Generate is switched off above your time limit (Settings, default 30 minutes; "Allow sizes and lengths beyond…" overrides it). A running video that passes the limit stops with an explanation.
- **Live meters** for CPU, GPU, memory and graphics memory on the Make video page. A video that runs far too long shows why (graphics memory full, running on the CPU, or the card idle).
- **Drop overlay** ("Drop to add to your Library") no longer stays on the screen after you drop a file into a picture or video slot.
- **fal.ai key**: you can paste the bare key, `Key abc:def`, or a whole JSON line; the app cleans it. A broken saved key is repaired on read. Network errors now say what really happened (cannot connect, upload too slow, key refused). A big motion video is shrunk before it is uploaded.
- **Improve prompt** button on Make video and an automatic detail boost for pictures in the AI Assistant (written by your AI if one is connected, otherwise by a built-in recipe).
- **Better picture engines**: FLUX on Hugging Face (free token), FLUX on Together AI (free model), OpenAI DALL·E 3 / GPT Image (paid, high quality). Midjourney has no public API, so it cannot be connected.
- **"Which AI is best for my PC?"** pop-up in both apps: the best model to run on the PC (Ollama), the best free online service (Groq, Gemini, OpenRouter) and the best paid one (Claude, `claude-sonnet-5-5`).
- **First-run tour** with Skip, in both apps. Replay it from Settings > Take the tour.

## 1.2.12 – fixes and free local motion
- **"Expected all tensors to be on the same device"** when making a video (start + end picture) is fixed. Now that the graphics card is used, the written prompt data was left on the CPU; it is moved to the card before the model runs.
- **fal.ai "did not accept the key"**: the box held the example words `PASTE_YOUR_KEY_HERE`. The app now says so, and refuses example text. Paste your real key (fal.ai > Dashboard > Keys). Never put a real key in the README, a screenshot or GitHub.
- **Motion control, free quick preview (MediaPipe)**: choose "Quick preview (free, on this PC)". MediaPipe finds the body in the picture and in the video, and the picture is bent to follow the movement. It is a rough puppet-style preview, not Kling quality. First use downloads a 6 MB body-finder file (`pose_landmarker_lite.task`) into `LTXStudioData/models/pose`; if there is no internet, download it once and put it in that folder. Existing installs get MediaPipe from Settings > Updates (modules).
- Updated README with the new features.
