---
description: >
  Loop-engineered live debug agent for HSD sightings. Applies Karpathy/Osmani
  Loop Engineering: role separation (Planner/Generator/Evaluator), contract
  negotiation before log collection, configurable autonomy (supervised →
  autonomous), state on disk, adversarial evaluation.
triggers:
  - loop-debug HSD
  - loop debug
  - contract debug
  - autonomous debug
  - debug with contract
tools:
  - DebugAssistantAgentTool
  - Co-Design HSD MCP
  - NGA MCP
---

# Loop-Engineered Live Debug

Drives an iterative debug loop with **role separation** and **contract negotiation**
— the Planner proposes hypotheses and defines what evidence would confirm/disconfirm
each; the Generator collects the most discriminating log; the Evaluator (adversarial)
grades evidence against the contract and decides continue/stop/restart.

## Architecture

```
┌─ PLANNER ──────────────────────────────────────────────────┐
│ Parse HSD → 3-5 hypotheses → contract.md                    │
│ (what proves/disproves each hypothesis)                     │
└────────────────────────────────────────────────────────────-┘
         │
         ▼
┌─ INNER LOOP ───────────────────────────────────────────────┐
│                                                             │
│  ┌─ GENERATOR ─────────────────────────────────────────┐   │
│  │ Read contract → pick highest-discrimination log      │   │
│  │ → collect via adapter → write evidence.md            │   │
│  └─────────────────────────────────────────────────────-┘   │
│         │                                                   │
│         ▼                                                   │
│  ┌─ EVALUATOR (adversarial) ───────────────────────────┐   │
│  │ "The hypothesis is WRONG — prove it"                 │   │
│  │ Grade discrimination → CONTINUE / STOP / RESTART     │   │
│  └─────────────────────────────────────────────────────-┘   │
│         │                                                   │
│         ▼                                                   │
│  [autonomy check: pause or continue?]                       │
│                                                             │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─ REPORT ───────────────────────────────────────────────────┐
│ Root cause + evidence chain + HTML/Markdown report           │
└─────────────────────────────────────────────────────────────┘
```

## Invocation

```
@loop-debug HSD <hsd_id> [--mode supervised|semi_autonomous|autonomous]
                          [--execution ssh|local|manual|auto]
                          [--server <host>] [--max-iterations 10]
```

## Phases

### Phase 0: Bootstrap

1. Parse HSD ID and fetch context via Co-Design HSD MCP
2. Retrieve similar closed HSDs (RAG — same component/accelerator)
3. Load log taxonomy
4. Initialize session directory + SQLite + state files
5. Create `session_init.json` with loop config

### Phase 1: Contract Negotiation (Planner)

1. Call GENI as **Planner** (creative, divergent stance):
   - Input: HSD context + initial logs + similar HSDs + log taxonomy
   - Output: 3-5 hypotheses + contract (confirm/disconfirm criteria per hypothesis)
2. Write `hypotheses.md` and `contract.md` to disk
3. Present contract to user for review (all modes pause here on first run)
4. User can: approve, add context, or ask planner to revise

### Phase 2: Inner Loop (Generator → Evaluator)

Repeats until STOP/RESTART/max_iterations:

**Generator step:**
1. Call GENI as **Generator** (focused, efficient stance):
   - Reads contract + evidence + hypotheses + taxonomy
   - Picks the ONE category with highest discrimination value
   - Returns specific commands to run
2. Execute commands via adapter (manual/local/ssh/auto)
3. Append findings to `evidence.md`
4. Persist full log output to `<timestamp>_<category>.log`

**Evaluator step:**
1. Call GENI as **Evaluator** (adversarial stance: "hypothesis is WRONG"):
   - Reads contract + all evidence + hypotheses
   - Scores discrimination power of each evidence item
   - Checks: does evidence narrow hypotheses? Does it match contract criteria?
2. Returns verdict:
   - **CONTINUE**: evidence insufficient, loop continues
   - **STOP**: confidence ≥ threshold (default 0.85) + disconfirming check passed
   - **RESTART**: stuck for N iterations, hypothesis tree exhausted
3. Updates `hypotheses.md` with revised confidence scores

**Autonomy check:**
- `supervised`: pause after EVERY evaluator verdict
- `semi_autonomous`: pause every 3 iterations
- `autonomous`: pause only on STOP or RESTART

### Phase 3: Report

On STOP verdict:
1. Generate final root cause report (HTML + Markdown) using existing template
2. Write evidence chain linking each iteration to the conclusion
3. Present to user

On RESTART:
1. Present evaluator's failure reasoning to user
2. User confirms restart or stops
3. Planner re-invoked with "previous hypotheses failed because: ..."
4. Inner loop resumes with fresh hypotheses (evidence preserved)

## State Files (on disk, crash-recoverable)

| File | Purpose |
|------|---------|
| `session.db` | SQLite — iteration records (backward-compatible with existing schema) |
| `loop_checkpoint.json` | Full loop state — resume point after crash |
| `hypotheses.md` | Current hypothesis set with confidence bars |
| `contract.md` | Per-hypothesis: what confirms, what disconfirms |
| `evidence.md` | All collected evidence with context |
| `progress.md` | What's done, what's next, current iteration |
| `log.md` | Append-only audit trail of all role actions |

## Autonomy Modes

| Mode | Behavior | Use When |
|------|----------|----------|
| `supervised` | Pause after every iteration | First use, unfamiliar component |
| `semi_autonomous` | Run 3 iterations, then pause | Trusted components, short sessions |
| `autonomous` | Run until STOP/RESTART | Well-understood failures, overnight |

## Key Design Principles

1. **Maker/checker split**: Generator NEVER grades. Evaluator NEVER recommends.
2. **Contract before collection**: Every log is collected for a specific discriminating purpose.
3. **Adversarial evaluation**: Evaluator is told "hypothesis is wrong" — catches sycophancy.
4. **Disk-first state**: Agent can crash and recover by reading 3 files.
5. **Graceful restart**: Stuck loops discard hypotheses, not evidence.
6. **Configurable autonomy**: Start supervised, graduate as trust builds.

## Integration Points

- Uses existing `live_debug_runner.py` adapters (Manual/Local/SSH/Auto)
- Uses existing SQLite schema (extended with loop-specific columns)
- Uses existing `log_taxonomy.md` for category definitions
- Uses existing `live_debug_report_template.html` for final reports
- GENI DebugAssistantAgentTool serves all three roles (different system prompts)
