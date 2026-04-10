$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RootDir

$VenvDir = Join-Path $RootDir ".venv"
if (-not (Test-Path $VenvDir)) {
    python -m venv $VenvDir
}

$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r requirements.txt
& $VenvPython -m pip install pyinstaller

& $VenvPython -m PyInstaller local-ci.spec --noconfirm

Write-Host "Build complete: dist/local-ci.exe"