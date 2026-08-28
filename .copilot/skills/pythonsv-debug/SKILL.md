---
name: pythonsv-debug
description: |
  Agentic PythonSV debug-data collection agent. The user describes — in plain English —
  what silicon state to inspect or what diagnostic to run; the agent generates the
  read-only PythonSV (sv.*) commands ON THE FLY using MCP register lookups, verifies
  PythonSV access to the target first, executes on the PythonSV host, and returns the
  collected DATA. Iterative and human-in-the-loop. Produces DATA + findings, never a
  pass/fail verdict.
  Use when asked to "collect debug data", "run a pythonsv diagnostic", "read <register>
  via pythonsv", "check silicon state", "pythonsv debug", or "inspect the SUT with pythonsv".
  Target may be ANY OS (linux, windows, svos, uefi) reached over OOB JTAG or in-band.
---

# PythonSV Debug Data Collection Agent

## Trigger

Say any of the following — all parameters are **optional** and expressed in plain English:

```
collect debug data on <host> for <what to check>
pythonsv debug on <host>, read <registers / state>
run a pythonsv diagnostic on <host> for <symptom>
check silicon state on <host> via pythonsv
inspect the SUT on <host> with pythonsv
```

Session parameters can be included inline using natural language:

| Parameter | NLP example | Default |
|-----------|-------------|---------|
| **PythonSV host** (required) | `"on host 10.138.178.77"` / `"on NUC mylab"` | — |
| **Product / package** | `"product dmr"` / `"for GNR"` | inferred, else ask |
| **Target OS** | `"target is linux"` / `"svos"` / `"windows"` / `"uefi"` | `linux` |
| **Access mode** | `"over JTAG"` (oob) / `"in-band"` | `auto` (oob) |
| **Transport** | `"via winrm"` / `"via ssh"` | `auto` (winrm for Windows host) |
| **User** | `"as user fv_ecouser"` | — |

**Full examples:**

```
collect debug data on host 10.138.178.77 product dmr, target svos over JTAG, read core0 machine check banks

pythonsv debug on NUC 10.138.178.77 as user fv_ecouser via winrm, product dmr, check UPI link status

run a pythonsv diagnostic on 10.138.178.77 for a hung SUT, dump the crash status scope
```

The agent **extracts all parameters from the prompt** before starting Phase PD-0.

## What This Skill Does

Drives an **iterative, read-only debug-data collection loop** where PythonSV is used to
inspect silicon state or run diagnostic code. Unlike the validation flow (agentic-VALOR),
this skill:

1. **Verifies PythonSV access end-to-end BEFORE accepting any command** (readiness gate).
2. Turns a plain-English request into **read-only `sv.*` commands generated on the fly**
   via MCP register/spec lookups (never invents register paths).
3. **Executes** the generated bundle on the PythonSV host and **returns the DATA**.
4. **Presents findings** and waits for the next instruction — repeat.

It NEVER emits a pass/fail verdict and defaults to **read-only** collection.

---

## Inputs

| Field | NLP phrase | Backend flag | Default |
|-------|-----------|--------------|---------|
| `host` | `"on host <ip/name>"` (required) | `--host` | — |
| `product` | `"product dmr"` | `--product` | inferred |
| `target_os` | `"target is <os>"` | `--os` | `linux` |
| `access_mode` | `"over JTAG"` / `"in-band"` | `--access-mode` | `auto` |
| `transport` | `"via winrm/ssh"` | `--transport` | `auto` |
| `user` | `"as user <name>"` | `--user` | — |
| `required_version` | `"pysv version <x>"` | `--required-version` | — |

Backend: `src/pythonsv_debug_runner.py`.

---

## AUTONOMOUS EXECUTION INSTRUCTIONS

When triggered, execute phases **PD-0 → PD-3** in order.
**HARD STOP after PD-1 (readiness): present the readiness summary and REQUIRE explicit
user confirmation before accepting any collection instruction.**
Then loop PD-2 → PD-3, stopping after each collection to present data and wait for the
next instruction.

**Guard rails (non-negotiable):**
- **Never invent `sv.*` paths.** Every register/field path MUST come from an MCP lookup
  (`CodeWithRegistersTool`, co-design specs) and be validated (`VeWikiTool`) before use.
- **Read-only by default.** Do NOT generate writes (`sv.*.write(...)`, `store`, config
  changes) unless the user explicitly asks AND confirms; a write requires a restore/teardown plan.
- **Never bypass unlock/permission (RED COVER / UKP).** Report unlock state; if a read is
  blocked by permission, surface it — do not attempt to circumvent.
- **Platform mismatch = BLOCK.** If the host's PythonSV product/version does not match the
  target platform, stop and report; do not run against a mismatched package.

---

### Phase PD-0 — Session Initialization

**Step PD-0a**: Extract parameters from the user's prompt (host, product, target OS,
access mode, transport, user). Missing `host` → ask. Missing `product` → infer from
context or ask. Resolve access mode from OS: `svos`/`uefi` force **oob** (JTAG); live
`linux`/`windows` default to **oob** but in-band is allowed if requested.

**Step PD-0b**: Choose transport — Windows host → WinRM, otherwise SSH (`auto`).
Credentials come from environment/secret store, never hardcoded.

---

### Phase PD-1 — Readiness Gate (G1-G6) — MANDATORY

Run the readiness gate before any user instruction:

```bash
python src/pythonsv_debug_runner.py readiness \
  --host <host> --product <product> --os <os> \
  --access-mode <auto|oob|inband> --transport <auto|winrm|ssh> [--user <user>] --json
```

The gate checks and reports:

| Gate | Check | Hard BLOCK on failure? |
|------|-------|------------------------|
| **G1** | Host reachable over WinRM/SSH | ✅ |
| **G2** | PythonSV env loads on host (pysv importable, `start<product>.py`) | ✅ |
| **G3** | Correct product package + version for the TARGET platform | ✅ (mismatch) |
| **G4** | JTAG/probe connectivity host→SUT (`ipccli.baseaccess()`, `itp.forcereconfig()`, `sv.socket0`, enumerate sockets/dies) | ✅ |
| **G5** | Access mode resolved for target OS (oob vs in-band) | — |
| **G6** | Unlock / permission status (RED COVER / UKP) reported, never bypassed | ⚠️ WARN |

**On BLOCK**, present the failing gate + remediation (e.g. G4 → re-seat XDP/MIPI/USB,
`itp.forcereconfig()`, swap XDP/CCA cable; G3 → wrong package for platform) and STOP.

**On READY**, present a concise readiness summary and **ask the user to confirm** before
accepting collection instructions. Do not proceed without explicit confirmation.

---

### Phase PD-2 — Generate the Collection Bundle (on the fly)

For each plain-English instruction:

1. **Resolve register/state paths via MCP** (do not guess):
   - `CodeWithRegistersTool` `{exact_question, history_enhanced_query, ip}` for register
     names, fields, and `sv.*` access paths.
   - `codesign-get-spec-sources` / `ask-specs-and-wikis` as fallback for spec detail.
   - `VeWikiTool` `{question}` to **validate** every resolved `sv.*` path (mandatory).
   - Append the **geni-response-footer** verbatim after any Geni MCP tool output.
2. **Build a read-only bundle** JSON:
   ```json
   {
     "intent": "read core0 machine check bank status",
     "reads": ["sv.socket0.uncore.<validated.path>", "..."],
     "named": ["status_scope.run"],
     "read_only": true
   }
   ```
   `reads` = validated `sv.*` expressions; `named` = named collectors (e.g. DMR
   `status_scope`). Only include a write if the user explicitly asked and confirmed a
   restore plan (then `read_only: false` — the runner otherwise refuses).

---

### Phase PD-3 — Execute and Return Data

Run the bundle on the host (readiness is re-checked unless already confirmed this session):

```bash
python src/pythonsv_debug_runner.py collect \
  --host <host> --product <product> --os <os> \
  --transport <auto|winrm|ssh> [--user <user>] \
  --bundle <bundle.json> --json
```

Then:
1. Parse the returned JSON payload (`reads`, `named`, `errors`).
2. **Present the collected DATA** with the resolved paths and any errors — decode fields
   where the register spec gives bit meanings (cite the MCP source).
3. Note anomalies as **observations**, not a verdict.
4. Wait for the next instruction and loop back to PD-2.

---

## Outputs

- Readiness report (G1-G6, READY/BLOCKED) — JSON via `--json` or console table.
- Per-instruction collection result: `{intent, ok, data:{reads,named,errors}}`.
- Iterative findings presented in chat; no pass/fail verdict is produced.

## Rules

- Read-only by default; writes require explicit user request + confirmed restore plan.
- Never invent `sv.*` paths; MCP-resolve and VeWiki-validate every path.
- Never bypass RED COVER / UKP unlock; report permission state.
- Platform/version mismatch (G3) or lost JTAG (G4) → hard BLOCK with remediation.
- Credentials from environment/secret store only; never hardcode or commit them.
- Generalize across target OS: `svos`/`uefi` → OOB JTAG; live OS → OOB or in-band.
