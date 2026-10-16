@echo off
setlocal enableextensions
rem Builds the separate AI Assistant installer and portable .exe. Run from anywhere on a Windows PC.
rem Needs: Node.js 20 or newer. Run as administrator the first time (or turn on Windows "Developer Mode") so electron-builder can unpack its tools.
cd /d "%~dp0\.."

where node >nul 2>nul
if errorlevel 1 (
  echo Node.js 20 or newer is required. Install it from https://nodejs.org and run this again.
  exit /b 1
)

echo [1/4] Building the assistant interface...
pushd assistant-ui
call npm install
if errorlevel 1 goto :fail
call npm run build
if errorlevel 1 goto :fail
popd

echo [2/4] Preparing the desktop shell...
node scripts\stage-electron.mjs assistant
if errorlevel 1 goto :fail
pushd electron
call npm ci
if errorlevel 1 goto :fail

echo [3/4] Packaging (this downloads Electron the first time)...
call npx electron-builder --config electron-builder.assistant.yml --win --publish never
if errorlevel 1 goto :fail
popd

echo [4/4] Done. Your files are in the "dist-installer" folder:
dir /b dist-installer\AIAssistant*.exe
echo.
echo   AIAssistant-Setup-*.exe       installs on a PC
echo   AIAssistant-*-portable.exe    runs from any folder or USB drive, keeps its data next to itself
exit /b 0

:fail
echo.
echo Build failed. Scroll up to see the first error.
exit /b 1
