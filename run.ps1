# Auto HSD Analyser - one-command launcher (Windows PowerShell)
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

# Warm up the HSDES Kerberos ticket so the very first analysis authenticates.
# Entra/VPN logins often lack an on-prem TGT until a service ticket is requested;
# this mints it up-front (no password) and avoids the daily HSDES 401.
Write-Host "Checking HSDES Kerberos ticket..." -ForegroundColor Cyan
$null = & klist get HTTP/hsdes-api.intel.com 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "  HSDES ticket ready (Kerberos SSO)." -ForegroundColor Green
} else {
    Write-Host "  Could not get an HSDES Kerberos ticket. HSDES reads may return 401." -ForegroundColor Yellow
    Write-Host "  Fix: connect the Intel VPN, then lock (Win+L) and unlock, and re-run ./run.ps1" -ForegroundColor Yellow
}

# Auto-refresh the Axon token (Kerberos SSO - no password needed) so Axon
# SVTools failure signatures are fetched automatically on every analysis.
Write-Host "Refreshing Axon token..." -ForegroundColor Cyan
try {
    & powershell -ExecutionPolicy Bypass -File ".\refresh_axon_token.ps1" 2>$null
    if ($LASTEXITCODE -ne 0) { throw "non-zero exit" }
} catch {
    Write-Host "  (Axon token refresh skipped - set AXON_GENI_TOKEN manually in .env if needed)" -ForegroundColor Yellow
}

$env:PYTHONPATH = (Get-Location).Path
Write-Host "Starting Auto HSD Analyser at http://127.0.0.1:8000 ..." -ForegroundColor Green
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir app
