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
   git commit -m "VK Editor 1.2.2: drawing, AI chat editor, auto setup, updates"
   git push
   ```
   (If `assistant-ui\package-lock.json` still exists, delete it first — it breaks the Windows build.)
3. Go to your repository page → **Actions** tab. A yellow circle means "the robot is building your app". Wait until it turns into a green tick (about 15–25 minutes).

### Make the download page (the "Release")
1. In PowerShell type these two lines (the `v1.2.2` must match the version in `electron/package.json`):
   ```powershell
   git tag v1.2.2
   git push origin v1.2.2
   ```
2. Wait for the robot again (Actions tab). When it is green, open your repository → right side → **Releases**. You will see **v1.2.2** with the files:
   - `VKEditor-Setup-1.2.2.exe` — normal installer
   - `VKEditor-1.2.2-portable.exe` — runs from any folder, nothing to install
   - `AIAssistant-…exe` — the separate AI Assistant app
3. **Share this one link** with anyone: `https://github.com/karthikeyan12345678/ai-assistant-studio/releases/latest`
   (The repository must be **Public** for strangers to download. In a private repository only people you invite can.)

### When you make a new version
1. Change the version number (example `1.2.2`) in `electron/package.json`, `frontend/package.json`, `backend/ltxps/__init__.py`.
2. Refresh the "what is new" list so users get the update button (it reads the version you set in step 1):
   ```powershell
   python scripts\make_update_manifest.py "What is new in 1.2.2"
   ```
3. `git add -A`, `git commit -m "1.2.2"`, `git push`, then `git tag v1.2.2` and `git push origin v1.2.2`.

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
