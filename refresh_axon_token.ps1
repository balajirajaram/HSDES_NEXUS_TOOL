#!/usr/bin/env powershell
<#
.SYNOPSIS
    Auto-refresh Axon token and add it to .env so the Auto HSD Analyser
    fetches Axon SVTools failure signatures without needing the axon CLI binary.

.DESCRIPTION
    Uses the same Kerberos-based token endpoint as the acquire-tokens skill.
    Runs on demand or from a scheduled task. Token valid for 30 min.

.EXAMPLE
    .\refresh_axon_token.ps1               # updates .env in the current folder
    .\refresh_axon_token.ps1 -EnvFile .env # explicit path
#>
param(
    [string]$EnvFile = ".env"
)

$ErrorActionPreference = "Stop"

# ---- Acquire the token (Kerberos negotiate - same method as acquire-tokens skill) ----
Write-Host "Fetching Axon token from axon.intel.com ..." -ForegroundColor Cyan
try {
    $resp = Invoke-WebRequest `
        -Uri "https://axon.intel.com/api/v1/token" `
        -UseDefaultCredentials `
        -Method POST `
        -ContentType "application/json" `
        -Body '{}' `
        -TimeoutSec 20 `
        -UseBasicParsing
    $json   = $resp.Content | ConvertFrom-Json
    $token  = if ($json.token)        { $json.token }
              elseif ($json.access_token) { $json.access_token }
              else                       { $json.axonToken }
} catch {
    # Fallback: GET with negotiate
    try {
        $resp = Invoke-WebRequest `
            -Uri "https://axon.intel.com/api/v1/token" `
            -UseDefaultCredentials `
            -Method GET `
            -TimeoutSec 20 `
            -UseBasicParsing
        $json  = $resp.Content | ConvertFrom-Json
        $token = if ($json.token)        { $json.token }
                 elseif ($json.access_token) { $json.access_token }
                 else                       { $json.axonToken }
    } catch {
        Write-Error "Failed to fetch token: $_"
        exit 1
    }
}

if (-not $token) {
    Write-Error "Token response did not contain a token value. Response: $($resp.Content)"
    exit 1
}
Write-Host "Token acquired (length $($token.Length))" -ForegroundColor Green

# ---- Update .env ----
$envPath = Resolve-Path $EnvFile -ErrorAction SilentlyContinue
if (-not $envPath) { $envPath = $EnvFile }

$content = if (Test-Path $envPath) { Get-Content $envPath -Raw } else { "" }

if ($content -match '(?m)^AXON_GENI_TOKEN=.*$') {
    $content = $content -replace '(?m)^AXON_GENI_TOKEN=.*$', "AXON_GENI_TOKEN=$token"
} else {
    $content += "`nAXON_GENI_TOKEN=$token`n"
}

Set-Content -Path $envPath -Value $content -Encoding UTF8
Write-Host "AXON_GENI_TOKEN written to $envPath" -ForegroundColor Green
Write-Host "Token valid for ~30 min. Re-run this script when it expires." -ForegroundColor Yellow
