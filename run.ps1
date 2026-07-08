# Auto HSD Analyser — one-command launcher (Windows PowerShell)
$ErrorActionPreference = "Stop"

if (-not (Test-Path .venv)) {
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    python -m venv .venv
}

. .\.venv\Scripts\Activate.ps1

Write-Host "Installing dependencies..." -ForegroundColor Cyan
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt

if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    Write-Host "Created .env from template. Edit it to add HSDES_API_TOKEN and LLM_* for full mode." -ForegroundColor Yellow
}

$env:PYTHONPATH = (Get-Location).Path
Write-Host "Starting Auto HSD Analyser at http://127.0.0.1:8000 ..." -ForegroundColor Green
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
