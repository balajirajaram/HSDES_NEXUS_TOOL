# Auto HSD Analyser (Option C — SSO) launcher
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
    Write-Host "Created .env - fill in OIDC_* (SSO app registration) before signing in." -ForegroundColor Yellow
}

$env:PYTHONPATH = (Get-Location).Path
Write-Host "Starting Auto HSD Analyser (SSO) at http://127.0.0.1:8100 ..." -ForegroundColor Green
python -m uvicorn app.main:app --host 127.0.0.1 --port 8100 --reload
