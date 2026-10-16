<#
  OPTIONAL. Builds an offline Python runtime (embedded Python + PyTorch + all libraries) in .\python-bundle
  so the app can start without downloading anything the first time.

  Usage (PowerShell, from the project folder):
      .\scripts\prepare-python.ps1 -Torch cu128      # or cu126, cu130, cpu
  Then run:  .\scripts\build-windows.bat -offline
  The result is large (4-6 GB), so it is shipped as a .zip, not as an installer.
  PyTorch builds differ per graphics-card generation: a bundle made with cu128 may not run on an old GTX 10-series card.
#>
param([string]$Torch = "cu128", [string]$PythonVersion = "3.12.8")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$dest = Join-Path $root "python-bundle"
$tmp = Join-Path $env:TEMP "ltxps-bundle"
New-Item -ItemType Directory -Force $tmp | Out-Null
if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }

Write-Host "Downloading Python $PythonVersion ..."
$zip = Join-Path $tmp "python-embed.zip"
Invoke-WebRequest "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip" -OutFile $zip
Expand-Archive $zip -DestinationPath $dest -Force

$pth = Get-ChildItem $dest -Filter "python*._pth" | Select-Object -First 1
# "..\backend" is relative to python.exe's folder: <resources>\python -> <resources>\backend
Set-Content $pth.FullName -Value @(($pth.BaseName + ".zip"), ".", "Lib\site-packages", "..\backend", "", "import site") -Encoding ASCII

Write-Host "Installing pip ..."
$getpip = Join-Path $tmp "get-pip.py"
Invoke-WebRequest "https://bootstrap.pypa.io/get-pip.py" -OutFile $getpip
& "$dest\python.exe" $getpip --no-warn-script-location
if ($LASTEXITCODE -ne 0) { throw "pip setup failed" }

Write-Host "Installing PyTorch ($Torch) ..."
& "$dest\python.exe" -m pip install --no-warn-script-location torch --index-url "https://download.pytorch.org/whl/$Torch"
if ($LASTEXITCODE -ne 0) { throw "PyTorch install failed" }

Write-Host "Installing the app's libraries ..."
& "$dest\python.exe" -m pip install --no-warn-script-location -r (Join-Path $root "backend\requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Library install failed" }

Write-Host "Done: $dest"
