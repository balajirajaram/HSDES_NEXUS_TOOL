#!/usr/bin/env bash
# Install BugScout Skills and Agent — Linux / macOS
# Run from within the BugScout repo: bash scripts/install.sh
#
# This installs directly from THIS local checkout (no git clone/pull of a remote copy),
# so any local edits (e.g. to agents/ or .copilot/skills/) are picked up immediately.

set -euo pipefail

SKILLS_BASE="${HOME}/.copilot/skills"
AGENTS_BASE="${HOME}/.copilot/agents"
DEST="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Installing BugScout Unified Agent"
echo "    Source: ${DEST}"

# Create directories
mkdir -p "${SKILLS_BASE}" "${AGENTS_BASE}"

# Install BugScout skills under ~/.copilot/skills/<name>
for skill in hsd-triage live-debug pythonsv-debug log-search crash-parser handbook-rag handbook-kb-builder; do
    src="${DEST}/.copilot/skills/${skill}"
    dst="${SKILLS_BASE}/${skill}"
    if [ -d "${src}" ]; then
        rm -rf "${dst}"
        cp -r "${src}" "${dst}"
        echo "    Skill installed: ${SKILLS_BASE}/${skill}/SKILL.md"
    else
        echo "    WARNING: Skill directory not found: ${src}"
    fi
done
echo "==> Skills installed to: ${SKILLS_BASE}"

# Install only the single BugScout agent
agent_file="${DEST}/agents/bugscout.agent.md"
if [ -f "${agent_file}" ]; then
    cp "${agent_file}" "${AGENTS_BASE}/bugscout.agent.md"
    echo "    Agent installed: ${AGENTS_BASE}/bugscout.agent.md"
else
    echo "    WARNING: Agent file not found: ${agent_file}"
fi
echo "==> Agent installed to: ${AGENTS_BASE}"

# Install Python dependencies if requirements exist
if [ -f "${DEST}/requirements.txt" ]; then
    echo "==> Installing Python dependencies..."
    if command -v python3 &>/dev/null; then
        python3 -m pip install -r "${DEST}/requirements.txt" --quiet
        echo "    Python deps installed."
    else
        echo "    WARNING: python3 not found. Install deps manually: pip install -r requirements.txt"
    fi
fi

echo ""
echo "==> BugScout installation complete."
echo ""
echo "    Next steps:"
echo "    1. In VS Code Chat, open the Set Agent menu and select 'bugscout'."
echo "    2. Invoke BugScout capabilities by skill name in prompt text, for example:"
echo "         - 'run hsd-triage for HSD 22022566949'"
echo "         - 'live-debug HSD 22022566949 using SSH on server <host> as user <user>'"
echo "         - 'use log-search on <path-to-log> for keywords timeout,error'"
echo ""
