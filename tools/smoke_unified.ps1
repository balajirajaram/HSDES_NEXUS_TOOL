# Unified smoke test launcher (Windows PowerShell)
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if (Test-Path .venv\Scripts\python.exe) {
    $py = ".venv\Scripts\python.exe"
} else {
    $py = "python"
}

& $py .\tools\smoke_unified.py @args
exit $LASTEXITCODE
