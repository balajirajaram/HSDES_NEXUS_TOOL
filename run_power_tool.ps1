# Unified Auto HSD + OptionD launcher (Windows PowerShell)
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
    Write-Host "Created .env from template." -ForegroundColor Yellow
}

$env:PYTHONPATH = (Get-Location).Path

if ($args.Count -eq 0) {
    Write-Host "No command provided. Showing unified help..." -ForegroundColor Yellow
    python -m app.power_tool --help
    exit $LASTEXITCODE
}

python -m app.power_tool @args
exit $LASTEXITCODE
