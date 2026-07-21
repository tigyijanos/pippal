# PipPal — one-shot setup for Windows.
#
# Downloads the Piper binary, the default voice (en_US-ljspeech-high), and
# installs the Python dependencies. Safe to re-run; skips files that
# already exist.

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = $PSScriptRoot

function Resolve-PipPalDataRoot {
    if ($env:PIPPAL_DATA_DIR) {
        return $env:PIPPAL_DATA_DIR
    }
    $localAppData = $env:LOCALAPPDATA
    if (-not $localAppData) {
        $localAppData = Join-Path $env:USERPROFILE 'AppData\Local'
    }
    return Join-Path $localAppData 'PipPal'
}

Write-Host "PipPal setup" -ForegroundColor Cyan
Write-Host "Working directory: $root"

# --- Piper binary ---
$piperExe = Join-Path $root 'piper\piper.exe'
if (-not (Test-Path $piperExe)) {
    Write-Host "Downloading Piper binary..." -ForegroundColor Yellow
    $zip = Join-Path $root 'piper_temp.zip'
    Invoke-WebRequest `
        -Uri 'https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_windows_amd64.zip' `
        -OutFile $zip
    Expand-Archive -Force $zip -DestinationPath $root
    Remove-Item $zip
    Write-Host "Piper installed at: $piperExe" -ForegroundColor Green
} else {
    Write-Host "Piper already installed."
}

# --- Default voice ---
$dataRoot = Resolve-PipPalDataRoot
$voicesDir = Join-Path $dataRoot 'voices'
New-Item -ItemType Directory -Force -Path $voicesDir | Out-Null
$voiceOnnx = Join-Path $voicesDir 'en_US-ljspeech-high.onnx'
$voiceJson = Join-Path $voicesDir 'en_US-ljspeech-high.onnx.json'
if (-not (Test-Path $voiceOnnx)) {
    Write-Host "Downloading default voice (en_US-ljspeech-high, ~120 MB)..." -ForegroundColor Yellow
    Invoke-WebRequest `
        -Uri 'https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ljspeech/high/en_US-ljspeech-high.onnx' `
        -OutFile $voiceOnnx
    Invoke-WebRequest `
        -Uri 'https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ljspeech/high/en_US-ljspeech-high.onnx.json' `
        -OutFile $voiceJson
    Write-Host "Voice installed at: $voiceOnnx" -ForegroundColor Green
} else {
    Write-Host "Default voice already installed."
}

# --- Python dependencies ---
$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) {
    Write-Warning "Python not found on PATH. Install Python 3.11+ then re-run."
    exit 1
}
Write-Host "Installing Python dependencies..." -ForegroundColor Yellow
& $python -m pip install --quiet --user keyboard pyperclip pystray Pillow pywebview

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host "Run with:    pythonw reader_app_web.py"
Write-Host "Autostart:   create a Startup shortcut to start_server.vbs (see README)"
Write-Host "Core setup: Piper engine + default voice are ready."
