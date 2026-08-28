# Install BugScout Skills and Agent — Windows
# Run from PowerShell (as the user, not Administrator), from within the BugScout repo:
#   .\scripts\install.ps1
#
# This installs directly from THIS local checkout (no git clone/pull of a remote copy),
# so any local edits (e.g. to agents/ or .copilot/skills/) are picked up immediately.

$ErrorActionPreference = "Stop"

$SKILLS_BASE = "$env:USERPROFILE\.copilot\skills"
$AGENTS_BASE = "$env:USERPROFILE\.copilot\agents"
$DEST        = Resolve-Path "$PSScriptRoot\.."

Write-Host "==> Installing BugScout Unified Agent" -ForegroundColor Cyan
Write-Host "    Source: $DEST"

# Create directories
foreach ($dir in @($SKILLS_BASE, $AGENTS_BASE)) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        Write-Host "    Created: $dir"
    }
}

# Install BugScout skills under ~/.copilot/skills/<name>
$SKILLS = @(
    "hsd-triage",
    "live-debug",
    "pythonsv-debug",
    "log-search",
    "crash-parser",
    "handbook-rag",
    "handbook-kb-builder"
)

foreach ($skill in $SKILLS) {
    $src = "$DEST\.copilot\skills\$skill"
    $dst = "$SKILLS_BASE\$skill"
    if (Test-Path $src) {
        if (Test-Path $dst) { Remove-Item $dst -Recurse -Force }
        Copy-Item $src $dst -Recurse -Force
        Write-Host "    Skill installed: $SKILLS_BASE\$skill\SKILL.md"
    } else {
        Write-Host "    WARNING: Skill directory not found: $src" -ForegroundColor Yellow
    }
}
Write-Host "==> Skills installed to: $SKILLS_BASE"

# Install only the single BugScout agent
$agentFile = "$DEST\agents\bugscout.agent.md"
if (Test-Path $agentFile) {
    Copy-Item $agentFile "$AGENTS_BASE\bugscout.agent.md" -Force
    Write-Host "    Agent installed: $AGENTS_BASE\bugscout.agent.md"
} else {
    Write-Host "    WARNING: Agent file not found: $agentFile" -ForegroundColor Yellow
}
Write-Host "==> Agent installed to: $AGENTS_BASE"

# Install Python dependencies if requirements exist
if (Test-Path "$DEST\requirements.txt") {
    Write-Host "==> Installing Python dependencies..."
    python -m pip install -r "$DEST\requirements.txt" --quiet
    Write-Host "    Python deps installed."
}

Write-Host ""
Write-Host "==> BugScout installation complete." -ForegroundColor Green
Write-Host ""
Write-Host "    Next steps:"
Write-Host "    1. In VS Code Chat, open the Set Agent menu and select 'bugscout'."
Write-Host "    2. Invoke BugScout capabilities by skill name in prompt text, for example:"
Write-Host "         - 'run hsd-triage for HSD 22022566949'"
Write-Host "         - 'live-debug HSD 22022566949 using SSH on server <host> as user <user>'"
Write-Host "         - 'use log-search on <path-to-log> for keywords timeout,error'"
Write-Host ""
