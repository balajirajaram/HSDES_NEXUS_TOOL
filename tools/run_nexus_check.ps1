param(
    [string]$Url = "http://127.0.0.1:8000",
    [switch]$Strict
)

$ErrorActionPreference = "Stop"
$python = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
$args = @((Join-Path $PSScriptRoot "nexus_auto_check.py"), "--url", $Url)
if ($Strict) { $args += "--strict" }
& $python @args
exit $LASTEXITCODE
