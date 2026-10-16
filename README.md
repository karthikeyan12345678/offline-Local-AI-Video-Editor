# LTX Portable Studio + AI Assistant

Two Windows apps from one project:

1. **LTX Portable Studio**: local video generator and editor for 4 GB graphics cards (below).
2. **AI Assistant**: a separate chat app with file creation (PDF, PowerPoint, Word, CSV, Excel), file comparison, a design picker, a resume ATS checker, image generation and file analytics. It also opens from the Studio (*AI Assistant* in the sidebar, or Ctrl+Shift+A).

A local video generator and editor for Windows that is tuned for **4 GB graphics cards**. Type a description (or give it a picture), get a short video, then cut, join, colour, caption and export it. Everything runs on your PC; nothing is uploaded.

```
frontend/        React + TypeScript interface of the video studio (ChatGPT-style design system)
assistant-ui/    React + TypeScript interface of the AI Assistant (Claude dark design system)
backend/         Python: FastAPI server, LTX-Video engine, ffmpeg editor, downloader, and ltxps/assistant (documents, themes, compare, ATS, analytics, chat, images)
electron/        Windows desktop shell for both products: starts the backend, installs the runtime on first run
shared/design/         Design tokens + component CSS of the studio
shared/design-claude/  Design tokens + component CSS of the assistant (see its README for the decisions made)
scripts/         build-windows.bat (studio), build-assistant.bat (assistant), prepare-python.ps1, stage-electron.mjs
```

## AI Assistant

Separate app, own `.exe`, own data folder (`AIAssistantData` next to the portable exe, or `%LOCALAPPDATA%\AIAssistantPortable`). It needs no PyTorch: the first start installs about 150 MB of libraries.

| Feature | How | Where it runs |
| --- | --- | --- |
| Chat | Pick a provider in *Settings*: Ollama or LM Studio on this PC (free, private), OpenRouter, NVIDIA NIM, Groq, Gemini, OpenAI, Anthropic, or a running **free-claude-code** proxy (default `http://127.0.0.1:8082`) | the provider you choose |
| Create PDF / PowerPoint / Word / CSV / Excel | `/pdf`, `/ppt`, `/doc`, `/csv`, `/xlsx` in chat (the AI writes the content), or *Create files* (you paste Markdown, no AI needed) | this PC |
| Best design | 145 design themes taken from the Open Design catalogue. A rule-based recommender ranks them for your purpose and explains why; every theme is checked for readable contrast | this PC |
| Compare files | PDF, Word, PowerPoint, Excel, CSV, text, in any combination; paragraph/slide/page diffs with word-level changes; tables matched by key column; downloadable report | this PC |
| Resume ATS check | Score out of 100 from file readability, contact details, sections, writing quality, dates and keywords (against a pasted job description when given) with a fix list | this PC |
| Image generation | Free Pollinations service, any OpenAI-compatible images API, or Stable Diffusion Turbo on this PC (only in the Studio, which includes PyTorch) | the engine you choose |
| File analytics | Column statistics, outliers, missing values, duplicates, correlations, date ranges, text readability | this PC |

Build it with `scripts\build-assistant.bat` or the GitHub workflow (artifact *AIAssistant-windows*: `AIAssistant-Setup-1.0.0.exe` and `AIAssistant-1.0.0-portable.exe`). Develop it with `cd assistant-ui && npm ci && npm run dev` and `python -m ltxps --mode assistant --port 8766`.

**Limits to know about**
- The ATS score is an estimate from common ATS checks, not any vendor's real system.
- PDF output of Tamil, Hindi and other Indian scripts is not shaped correctly (reportlab limitation); the app warns you. Use Word (.docx) for those languages.
- Answer quality, speed and cost depend on the chat model you pick. Small local models write weaker documents.
- Image requests to Pollinations or an API leave your PC; chat requests go to the provider you chose. Everything else stays local.
- The free-claude-code proxy is a separate program you run yourself (AGPL licence); this app only talks to it over HTTP and contains none of its code.

## LTX Portable Studio: what it can do

- **Make video**: from text, from a picture, or continue a clip from its last frame.
- **Library**: every generated or imported video, picture and sound; quick tools (smooth motion, upscale, stabilise, loop, boomerang, extract frame/audio, remove audio, GIF, convert).
- **Editor**: multi-clip timeline, trim by dragging, split, reorder, duplicate, undo/redo, speed 0.25–4×, reverse, fades, transitions (17 kinds), crop/zoom/pan, rotate/flip, brightness/contrast/colour/gamma/hue, filters, blur/sharpen/vignette/denoise, text overlays, background music tracks, master volume, project autosave, rendered preview, export to MP4, WebM or GIF.

## How it fits in 4 GB

It does **not** use LTX-2 (22 B parameters; far too large). It uses **LTX-Video 2B** with these measures:

- the text encoder runs on the CPU and its output is cached on disk, so repeating or tweaking a prompt is instant;
- the video model is stored as 8-bit weights and moved to the GPU in small blocks (or layer by layer if needed);
- the picture decoder works on tiles;
- if the card runs out of memory the app retries with a lower-memory mode by itself;
- sizes and lengths that would not fit are refused with an explanation. *Lite* profile (under 6 GB): up to 97 frames, with a size × length budget (for example 512×320 for the full 97 frames, or about 704 px on the long side for shorter clips). Bigger cards unlock larger profiles.

Expect minutes, not seconds, per clip on a 4 GB card, and the first video is slowest while the model loads. 16 GB of system RAM is recommended; the app warns below 12 GB.

## Get the .exe

You need a Windows PC (or GitHub) to build it; the Windows installer cannot be produced on Linux or macOS.

**Option A: GitHub (no setup on your PC).** Put this folder in a GitHub repository and push. The workflow in `.github/workflows/build-windows.yml` runs the tests and uploads `LTXPortableStudio-Setup-1.0.0.exe` (installer) and `LTXPortableStudio-1.0.0-portable.exe` as downloadable artifacts.

**Option B: your own PC.** Install Node.js 22, open a terminal as Administrator in this folder and run `scripts\build-windows.bat`. Results appear in `dist-installer\`.

### First start on any PC

The installer is small. On first start the app downloads Python and the right PyTorch build for that PC's graphics card (2–3 GB, one time, needs internet), then you press **Download everything needed** to fetch the model files from Hugging Face. If Hugging Face is blocked, set a mirror in *Settings → Models → Download server*.

### Using it on other PCs

- **Portable .exe**: keeps all data in a `LTXStudioData` folder next to itself. Copy the exe *and that folder* (models included) to a USB drive or another PC. Other PC, other graphics card generation? Use *Help → Repair runtime* once to install the matching PyTorch.
- **Fully offline**: run `scripts\prepare-python.ps1 -Torch cu128` then `scripts\build-windows.bat -offline` to make a zip that already contains Python and PyTorch. PyTorch builds are tied to GPU generations, so make one bundle per generation if your PCs differ.
- To skip the model download on a second PC, copy `<data folder>\models`.

## Develop

```bash
cd backend && pip install torch --index-url https://download.pytorch.org/whl/cpu && pip install -r requirements-dev.txt
python -m pytest tests            # 149 tests, uses tiny fake weights and a fake model server, no GPU needed
LTXPS_ENGINE=fake python -m ltxps --ui-dir ../frontend/dist   # prints the URL; fake engine makes test clips

cd frontend && npm ci && npm run dev      # UI on :5173, proxy to a backend started with --port 8765
cd electron && npm ci && npm start        # desktop shell (set LTXPS_PYTHON to a Python with the requirements)
```

Environment variables: `LTXPS_DATA_DIR` (where data lives), `LTXPS_ENGINE=fake` (no model needed), `LTXPS_FAKE_VRAM_MB=4096` (pretend to have 4 GB), `LTXPS_FFMPEG`, `LTXPS_PYTHON`.

## What is and is not verified

Checked automatically: the editor's ffmpeg renderer against real ffmpeg, the API, the downloader against a local fake Hugging Face server (resume, cancel, errors), the memory-fallback logic with tiny CPU models, the interface in a real browser, the desktop shell starting the backend and stopping it again, the assistant in a real browser against a fake model server (chat streaming, all five file formats re-opened and checked, ATS, compare, analytics, images), and the assistant backend running without PyTorch or NumPy installed.

**Not checked, because it needs hardware or a network this build environment does not have:** answers from a real chat model (only a fake server was used), the real image services (Pollinations, OpenAI, local Stable Diffusion), the free-claude-code proxy, generation on a real GPU (speed, true VRAM use, 8-bit weights on your card), downloading the real model files, and the Windows packaging itself. Expect to adjust the *Lite* limits or memory mode after the first real run. Choose a different memory mode in *Settings* if you see out-of-memory messages.

## Licences

The 145 assistant design themes were derived from Open Design (Apache-2.0); see `backend/ltxps/assistant/THIRD_PARTY.md`.


The app code is yours. The model files are not part of it: check the licence terms of `Lightricks/LTX-Video` and of the T5 text encoder on Hugging Face before commercial use.

## Video editor upgrade

- **Transitions:** 57 ffmpeg transitions (fade, wipe, slide, cover/reveal, shapes, slices, wind, zoom) plus *Random*; one click applies a transition to every cut.
- **Looks, effects, camera motion:** 24 colour looks, 19 stackable effects (RGB split, glitch, VHS, film grain, neon edges, bloom, mirror, …), 11 camera moves (Ken Burns, pans, shake, pulse).
- **Text:** 68 bundled fonts (Latin, display, script, plus Tamil, Hindi, Telugu, Kannada, Malayalam, Bengali), outline, shadow, glow, gradient, box, spacing, tilt, 14 one-click styles, in/out animations (fade, slide, zoom, pop, wipe reveal). Fonts are OFL/Apache licensed (see `backend/ltxps/editor/fonts/README.txt`).
- **Sound:** 25 sound effects (voice clean-up, telephone, robot, reverb, echo, lo-fi, …), pitch, bass/treble, noise removal, loudness, music loop, automatic music ducking under speech.
- **AI (all on this PC):** follow a person with a moving crop (YuNet face model bundled, falls back to movement), auto captions (Whisper via faster-whisper; models are downloaded from the Models page), cut silences, split at scene changes, auto-enhance colour, cut clips to the music beat, text-to-speech voice-over using the PC's own voices.
