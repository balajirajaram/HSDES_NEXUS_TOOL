# Auto HSD Analyser — Option D (Run locally in GitHub Copilot)

The **zero-setup, zero-token** way to use the HSD Analyser. Every engineer runs it
**inside VS Code with GitHub Copilot (GHCP)** on their own laptop. Because Copilot uses
each person's **own** Intel MCP authentication, there is **nothing to share** — no
tokens, no server, no deployment.

This folder contains only the agent prompt and this guide.

```
option-d-copilot/
├─ .github/prompts/auto-hsd-analyser.prompt.md   ← auto-discovered by VS Code
├─ auto-hsd-analyser.prompt.md                    ← same file, for easy viewing
└─ README.md                                       ← you are here
```

---

## What each user needs (one-time)

1. **VS Code** (latest).
2. **GitHub Copilot + Copilot Chat** extensions, signed in with an account that has
   Copilot enabled at Intel.
3. The **Intel MCP tools** that back the analysis, available in Copilot Chat:
   - `codesign-debug-search-in-memories` / `codesign-debug-store-memory` (the KB)
   - `codesign-ask-hsd-agent` and/or `HSDIndexTool` (HSDES access)

   These come from the Intel Geni / co-design Copilot plugin. If a teammate doesn't
   have them, they install the same plugin you use (see your team's Geni onboarding),
   then run the `acquire-tokens` step once so `HSDIndexTool` can authenticate **as
   them**.

No HSDES token is copied or shared — each person authenticates through their own
Copilot session.

---

## Install the prompt (pick one)

### Option 1 — Use this folder as the workspace (simplest)
1. Open the `option-d-copilot` folder in VS Code (`File ▸ Open Folder…`).
2. VS Code auto-discovers `.github/prompts/auto-hsd-analyser.prompt.md`.
3. Done — skip to **Run it**.

### Option 2 — Add it to your own project
Copy the prompt into your repo's prompt folder:
```powershell
New-Item -ItemType Directory -Force .github\prompts | Out-Null
Copy-Item path\to\option-d-copilot\.github\prompts\auto-hsd-analyser.prompt.md .github\prompts\
```

### Option 3 — Make it available in every workspace (personal)
Copy it to your VS Code user prompts folder so it's always available:
```powershell
Copy-Item .github\prompts\auto-hsd-analyser.prompt.md "$env:APPDATA\Code\User\prompts\"
```

---

## Run it

1. Open **Copilot Chat** (`Ctrl+Alt+I`).
2. Set the chat mode to **Agent** (dropdown at the top of the chat box).
3. Type:
   ```
   /auto-hsd-analyser
   ```
   (or open the `.prompt.md` file and press the ▶ **Run** button).
4. Enter the two inputs when prompted:
   - **HSD ID** — e.g. `1234567890`
   - **Symptoms** — e.g. `UPI CRC error, MCE bank 5, GNR B0, bucket=upi_link_retrain`

The agent produces the full A–H triage report (target-HSD summary, KB recall, similar
HSDs, ranked root causes, PythonSV debug plan, data-to-collect, learning summary,
known-issue verdict) and writes the case back into the learning KB.

---

## Why this needs no shared token
- Copilot's MCP servers run **locally, inside each user's VS Code**, authenticated as
  that user.
- The prompt calls those tools; every user's queries hit HSDES/KB **as themselves**.
- Result: same capability as the hosted web tool, but nothing to distribute or secure.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `/auto-hsd-analyser` doesn't appear | Ensure the file is in a discovered prompts location (Option 1/2/3). Reload VS Code. |
| "Tool not found" / no HSDES data | The Intel Geni/co-design MCP plugin isn't installed or not authenticated. Install it and run the `acquire-tokens` step. |
| Auth errors on `HSDIndexTool` | Tokens expired — re-run `acquire-tokens`. |
| Report has no similar HSDs | KB is empty and/or HSDES returned nothing; try richer symptom terms (unit, bucket, MCE bank, stepping). |

---

## Sharing this with the team
Just point teammates at this folder (or the repo) and this README. Each person installs
Copilot + the Intel MCP plugin once, drops in the prompt, and runs `/auto-hsd-analyser`.

Intel Internal Use Only.
