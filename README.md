# Auto HSD Analyser — RDT & UPI (GNR / SRF / CWF)

A self-learning post-silicon **HSD-ES triage assistant** for Intel GNR (Granite Rapids),
SRF (Sierra Forest) and CWF (Clearwater Forest). It packages an expert silicon-debug
agent prompt that:

- Recalls previously resolved cases from a persistent **Learned Knowledge Base (KB)** first.
- Falls back to the **HSDES database** when the KB has no confident match.
- **Writes back** every new finding into the KB so the model keeps improving.
- Produces a structured triage report: target-HSD summary, similar cases, ranked
  root-cause hypotheses, and an ordered PythonSV debug plan.

> Scope: RDT (Resource Director Technology) and UPI (Ultra Path Interconnect) failure
> signatures on GNR / SRF / CWF, stepping-aware.

---

## Repository layout

| Path | Purpose |
|------|---------|
| [prompts/auto-hsd-analyser.prompt.md](prompts/auto-hsd-analyser.prompt.md) | The runnable VS Code Copilot prompt (agent mode). |
| [docs/AGENT_SPEC.md](docs/AGENT_SPEC.md) | The full, human-readable agent specification. |
| [docs/SHARING.md](docs/SHARING.md) | How to publish and share this repo with others. |
| [docs/KB_SCHEMA.md](docs/KB_SCHEMA.md) | The Knowledge-Base entry schema used by the self-learning loop. |
| [CONTRIBUTING.md](CONTRIBUTING.md) | How teammates add cases and improve the prompt. |
| [LICENSE](LICENSE) | Intel internal-use notice. |

---

## Quick start (VS Code + GitHub Copilot)

1. Clone the repo (see [docs/SHARING.md](docs/SHARING.md)).
2. Open the folder in VS Code with GitHub Copilot Chat enabled.
3. In Copilot Chat, run the prompt file:
   ```
   /auto-hsd-analyser
   ```
   or open [prompts/auto-hsd-analyser.prompt.md](prompts/auto-hsd-analyser.prompt.md)
   and press the **Run** (▶) button.
4. Provide the two inputs when prompted:
   - **HSD ID** — the target ticket to triage.
   - **Symptoms** — key terms (unit, bucket, MCE bank, RIP, signal, error string, stepping).

The agent will emit the Markdown report described in [docs/AGENT_SPEC.md](docs/AGENT_SPEC.md)
(sections A–H).

---

## Required tools / MCP servers

The prompt expects the following to be available in the environment:

- `codesign-debug-search-in-memories` / `codesign-debug-store-memory` — the KB (memory) layer.
- `codesign-ask-hsd-agent` and/or `HSDIndexTool` — HSDES access.
- PythonSV runtime for executing the suggested register-access commands.

If a tool is unavailable, the agent will state the limitation instead of fabricating results.

---

## Guardrails

- Never invents HSD IDs, register names, root causes, or commands.
- HSDES is the source of truth; conflicting KB entries are corrected and re-tagged.
- Every KB entry is tagged **confirmed** vs **hypothesis**, with provenance + timestamp.
- Entries stay GNR/SRF/CWF-scoped and stepping-aware — no blind cross-application.

---

## Status

Seed corpus. The KB grows automatically as cases are triaged. See
[CONTRIBUTING.md](CONTRIBUTING.md) to add curated cases manually.
