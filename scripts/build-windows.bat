@echo off
setlocal enableextensions
rem Builds the Windows installer and the portable .exe. Run from anywhere on a Windows PC.
rem Needs: Node.js 20 or newer. Right-click > "Run as administrator" the first time (electron-builder needs it to unpack its signing tools),
rem or turn on Windows "Developer Mode".
cd /d "%~dp0\.."

where node >nul 2>nul
if errorlevel 1 (
  echo Node.js 20 or newer is required. Install it from https://nodejs.org and run this again.
  exit /b 1
)

echo [1/4] Building the interface...
pushd frontend
call npm ci
if errorlevel 1 goto :fail
call npm run build
if errorlevel 1 goto :fail
popd
pushd assistant-ui
call npm install
if errorlevel 1 goto :fail
call npm run build
if errorlevel 1 goto :fail
popd

echo [2/4] Preparing the desktop shell...
node scripts\stage-electron.mjs studio
if errorlevel 1 goto :fail
pushd electron
call npm ci
if errorlevel 1 goto :fail

echo [3/4] Packaging (this downloads Electron the first time)...
if /i "%~1"=="-offline" goto :offline
call npx electron-builder --win --publish never
if errorlevel 1 goto :fail
popd
goto :finish

:offline
if not exist "..\python-bundle\python.exe" (
  echo python-bundle not found. Run scripts\prepare-python.ps1 first.
  goto :fail
)
call npx electron-builder --win --dir --publish never
if errorlevel 1 goto :fail
popd
echo Copying the offline Python runtime into the app...
robocopy python-bundle "dist-installer\win-unpacked\resources\python" /E /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto :fail
tar -a -c -f "dist-installer\LTXPortableStudio-offline.zip" -C dist-installer win-unpacked
if errorlevel 1 goto :fail
echo Offline bundle: dist-installer\LTXPortableStudio-offline.zip  (unzip anywhere and run "LTX Portable Studio.exe")
exit /b 0

:finish

echo [4/4] Done. Your files are in the "dist-installer" folder:
dir /b dist-installer\*.exe
echo.
echo   LTXPortableStudio-Setup-*.exe     installs on a PC
echo   LTXPortableStudio-*-portable.exe  runs from any folder or USB drive, keeps its data next to itself
exit /b 0

:fail
echo.
echo Build failed. Scroll up to see the first error.
exit /b 1
