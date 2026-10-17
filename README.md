<div align="center">

# 🎬 VK Editor — desktop edition (offline, local AI)

### Make AI videos on your own computer, edit them, and chat with an AI helper. No daily limits, no queue.

[![Download for Windows](https://img.shields.io/badge/⬇_Download-VK_Editor_for_Windows-72E528?style=for-the-badge&labelColor=1a1a1a)](https://github.com/karthikeyan12345678/offline-Local-AI-Video-Editor/releases/latest)

**Just want to try it without installing?** Use the free website instead: [vk-editor-web](https://github.com/karthikeyan12345678/vk-editor-web) (sign in with Google, runs in the browser, limited free GPU time).

Made by [Karthikeyan V](https://karthikeyanv.netlify.app) · [LinkedIn](https://www.linkedin.com/in/karthikeyan-v-8a203a195) · [GitHub](https://github.com/karthikeyan12345678)

</div>

---

## ⬇️ Download and install (Windows)

1. Open the **[Releases page](https://github.com/karthikeyan12345678/offline-Local-AI-Video-Editor/releases/latest)**.
2. Under **Assets**, download one file:
   - `VKEditor-Setup-….exe` for a normal install, or
   - `VKEditor-…-portable.exe` to run from any folder with no install.
   - `AIAssistant-….exe` is the separate AI Assistant app (optional).
3. Double-click it. If Windows says *Windows protected your PC*, choose **More info, then Run anyway** (the app is not code-signed).
4. The first start installs the AI parts by itself and shows the time left. It needs internet **once** and about **5 to 10 GB** of disk space.
5. Open **Make video**, type a scene, press **Generate**.

If the Releases page is empty, the author has not published a version yet; use the [website](https://github.com/karthikeyan12345678/vk-editor-web) or build it yourself (below).

### Computer you need

| | Minimum | Better |
| --- | --- | --- |
| System | Windows 10 or 11, 64-bit | same |
| Graphics card | NVIDIA with 8 GB video memory | 12 GB or more (RTX 3060 and up) |
| Memory | 16 GB | 32 GB |
| Disk | 15 GB free | SSD with 30 GB free |

Without a suitable NVIDIA card, video generation is very slow or unavailable; the editor and the Assistant still work. Use the website's free cloud GPU instead.

## ✨ What is inside

- **Text to video, picture to video, continue a clip** on your own graphics card.
- **Motion control** (pose retarget and character swap).
- **Editor:** multi-track timeline, layers, green screen, masks, keyframes, 51 looks, 34 effects, 59 transitions, 38 sounds, 68 fonts (Tamil, Hindi and more), chat editing, MP4 / WebM / GIF export.
- **AI Assistant:** chat, PDF, PowerPoint, Word, Excel and CSV files, resume check and tailoring, compare documents, analyse data, pictures.
- Works offline after the first install, except the optional online chat AI.

## 🔐 Keys and privacy

- Your videos stay on your computer.
- Any chat or image key you paste is saved only on your computer (in the app's data folder `LTXStudioData`). It is never part of this repository or of a release file.
- Never commit keys, `.env` files or `LTXStudioData`. `.gitignore` blocks them. If a key was ever exposed, delete it at the provider and create a new one.
- Everything in this project is free. No paid key is needed.

## 🛠 Run from source (developers)

You need Python 3.12, Node 22 and, for AI video, an NVIDIA GPU with current drivers.

```bash
git clone https://github.com/karthikeyan12345678/offline-Local-AI-Video-Editor.git
cd offline-Local-AI-Video-Editor

# 1. backend
cd backend
python -m venv .venv && .venv\Scripts\activate        # Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest tests -q                              # optional: run the tests
cd ..

# 2. interfaces
cd frontend && npm install && npm run build && cd ..
cd assistant-ui && npm install && npm run build && cd ..

# 3. desktop shell
cd electron && npm install && npm start
```

Build the Windows installers yourself: push a tag such as `v1.2.14` (GitHub Actions builds them and attaches them to a Release), or open **Actions, Build Windows apps, Run workflow**. More in [docs/DESKTOP.md](docs/DESKTOP.md) and [docs/SHARE-GUIDE.md](docs/SHARE-GUIDE.md).

## 🌐 Website version

The browser edition lives in its own repository: **[vk-editor-web](https://github.com/karthikeyan12345678/vk-editor-web)**. Same editor, Google sign-in, saved projects and history, free cloud GPU for video.

## ⚠️ Good to know

Personal project, free for everyone, no guarantee. AI can make mistakes; check results before sharing. Fonts and models keep their own licences.
