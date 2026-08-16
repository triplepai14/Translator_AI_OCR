# Build TranslatorAIOCR-Setup.exe
# 1) PyInstaller -> dist\TranslatorAIOCR\  2) Inno Setup -> dist\TranslatorAIOCR-Setup.exe
# Run from the repo root: powershell -ExecutionPolicy Bypass -File installer\build.ps1

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

& ".venv\Scripts\pyinstaller.exe" --noconfirm --clean --windowed `
    --name TranslatorAIOCR `
    --icon "installer\icon.ico" `
    --add-data "icon.png;." `
    --collect-all ctranslate2 `
    --collect-all rapidocr_onnxruntime `
    --collect-all meikiocr `
    --collect-all uiautomation `
    --collect-all windows_capture `
    --collect-binaries onnxruntime `
    --copy-metadata translator-ai-ocr `
    --copy-metadata huggingface_hub `
    --exclude-module nvidia `
    "installer\launcher.py"

if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$iscc = "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $iscc)) { $iscc = "$env:ProgramFiles(x86)\Inno Setup 6\ISCC.exe" }
if (-not (Test-Path $iscc)) { $iscc = "ISCC.exe" }

& $iscc "installer\setup.iss"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }

Write-Host "Installer at dist\TranslatorAIOCR-Setup.exe"
