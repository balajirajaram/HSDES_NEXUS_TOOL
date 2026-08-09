---
name: mcp-enrichment
description: |
  Pre-enrichment pipeline for BugScout blind analysis. Runs three MCP phases BEFORE
  dispatching evidence to BugScout, injecting structured platform context without leaking
  root cause or resolution data.
  
  Phase 1 (Platform Identity): CPUID → CoDesign spec → platform name, subsystem list,
    errata domains, FIVR/VR topology, key architectural blocks.
  Phase 2 (Register Annotation): Platform + MCA symptom → remote code repo → MCA bank to
    subsystem mapping, relevant MSR addresses and register names.
  Phase 3 (HSD Pattern Match): Key observable signals → HSD MCP → top-5 symptom-similar
    sightings with title + observable symptoms only (root cause, resolution, analysis fields
    are redacted). Repro HSDs are excluded by their IDs.

  Use when: BugScout is about to perform blind analysis and platform context is available.
  DO NOT USE FOR: live debug sessions where the HSD is already known, or when HSD data
  should be withheld entirely (Phase A evaluation runs).
---

# MCP Pre-Enrichment Pipeline for BugScout

## Purpose

Addresses three structural gaps in BugScout blind analysis:
- **Gap A** — No platform architecture context (FIVR vs external VR, C-state microarch)
- **Gap B** — No register semantics (MCA bank → subsystem mapping, RASIP address)
- **Gap C** — No historical pattern reference (similar symptoms in prior sightings)

Estimated accuracy improvement: 75% → ~90% for silicon RAS/MCA failures.

## Evaluation Methodology Rule

> **CRITICAL:** This skill is used for Phase B (augmented) evaluation ONLY.
> Phase A (baseline) runs must receive raw evidence with NO enrichment.
> Repro HSDs must be listed in `exclude_hsd_ids` — they are ground truth labels,
> never pattern-match inputs for BugScout.
> Phase B evaluation must use a DIFFERENT repro case from the one in `exclude_hsd_ids`
> to prevent circular scoring.

---

## Inputs

| Parameter | Source | Example |
|---|---|---|
| `cpuid_family` | Evidence / `/proc/cpuinfo` | `19` |
| `cpuid_model` | Evidence / `/proc/cpuinfo` | `1` |
| `cpuid_stepping` | Evidence / `/proc/cpuinfo` | `0` |
| `key_signals` | Extracted from evidence | `["IERR after idle", "SEL voltage lower critical", "stressapptest preceded event"]` |
| `exclude_hsd_ids` | Caller-provided repro HSD list | `["15018590736"]` |
| `mca_banks_observed` | From evidence (if any) | `[5, 31]` (or empty `[]`) |

---

## Phase 1 — Platform Identity

**MCP:** `codesign-ask-specs-and-wikis`

**Query construction:**
```
"DMR Diamond Rapids Family {cpuid_family} Model {cpuid_model} Stepping {cpuid_stepping}
 platform architecture overview: subsystems, power delivery topology (FIVR vs external VR),
 MCA domains, RAS architecture, key errata domains for A0 stepping"
```

**Extract and structure:**
- Platform name (e.g., "DMR A0 — Diamond Rapids")
- Key subsystem list: `[RASIP, IMH, FIVR, QAT, DSA, IAA, TDX, IOMMU, PCIe]`
- Power delivery note: "FIVR = CPU-internal VR, not visible to IPMI SEL; faults only in MCA banks"
- Errata domains active on this stepping: `[MCA/RAS, TDX, Accelerator, Memory]`

**Output block injected into BugScout context:**
```
=== PLATFORM CONTEXT (pre-enrichment, read-only facts) ===
Platform: DMR A0 (Diamond Rapids, Family 19 Model 1 Step 0)
Subsystems: RASIP | IMH-EDAC | FIVR | QAT (6xxx) | DSA (IDXD v300) | IAA | TDX | IOMMU
Power delivery: FIVR = CPU-integrated VR. IPMI SEL monitors only external platform VRs.
  FIVR faults are NOT in SEL — they surface only in MCA bank registers.
Errata domains (A0): MCA/RAS, TDX (TME-required), Accelerator (DSA/IAA/QAT), Memory (1-DIMM)
=== END PLATFORM CONTEXT ===
```

---

## Phase 2 — Register Annotation

**MCP:** `codesign-ask-remote-code-repo`

**Trigger:** Only if `mca_banks_observed` is non-empty OR Phase 1 found relevant MCA domains.

**Query construction (per platform from Phase 1):**
```
"DMR A0 MCA bank to subsystem mapping: which MCA bank number corresponds to
 RASIP error handler domain? What MSR addresses read RASIP MCA status/address
 registers? What is reg_mca_err_src_log address?"
```

**Extract and structure:**
- MCA bank number → subsystem name table
- Key MSR addresses for symptom-relevant subsystems
- Register names for common diagnostic reads

**Output block injected:**
```
=== REGISTER ANNOTATION (pre-enrichment) ===
MCA Bank Map (DMR A0):
  Bank 0–7:   Core (per-core errors)
  Bank 8–11:  Uncore (LLC, ring)
  Bank 12–19: IMC (memory controller, per channel)
  Bank 31:    RASIP error handler domain
    MSR 0x419: MCA_STATUS_RASIP — check MC31_STATUS
    MSR 0x41A: MCA_ADDR_RASIP — fault address
    reg_mca_err_src_log: RASIP_REGS_BLOCK offset 0x...
FIVR fault signature: MC31_STATUS[61]=1 (ADDRV), MCACOD=0x0001, MSCOD platform-defined
=== END REGISTER ANNOTATION ===
```

---

## Phase 3 — HSD Pattern Match (Signal-Only, Root Cause Redacted)

**MCP:** `codesign-ask-hsd-agent`

**Exclusion:** Always exclude `exclude_hsd_ids` from results. Also exclude any ticket whose
`linked_article` or `duplicate_of` fields reference an excluded ID.

**Allowed output fields (whitelist):**
- `id` (HSD number — for reference only)
- `title` (truncated to remove root cause language if present)
- `symptom` / `description` (observable behavior only)
- `component` / `domain`

**Blocked output fields (never pass to BugScout):**
- `root_cause`
- `resolution`
- `analysis`
- `fix_version` / `fix_stepping`
- Any comment containing "root cause is" / "caused by" / "fix is"

**Query construction:**
```
"Find DMR sightings with symptoms matching: {key_signals}
 tenant: sighting_central.sighting, server_platf_ae.bug
 Return: id, title, symptom only. Exclude: {exclude_hsd_ids} and all linked/duplicate tickets."
```

**Output block injected:**
```
=== HISTORICAL PATTERN REFERENCE (symptoms only — no root cause) ===
Similar sightings found for signals: {key_signals}

1. HSD XXXXXXXXX — [DMR] IERR after thermal recovery idle period
   Symptom: System asserts IERR 2–6 hours after sustained CPU load followed by idle.
   Domain: CPU / MCA

2. HSD XXXXXXXXX — [DMR A0] Voltage Lower Critical SEL events under load
   Symptom: IPMI SEL records voltage brownout events on sensors 0x46-0x4e.
   Domain: Platform / Power

[Excluded: 15018590736 and linked tickets — repro HSD, treated as ground truth label]
=== END HISTORICAL PATTERN REFERENCE ===
```

---

## Integration with BugScout live-debug skill

Add a new optional parameter to `live-debug`:

```
--enrichment-mode  none | phase-a | phase-b
```

| Value | Behavior |
|---|---|
| `none` | No enrichment — pure blind analysis (Phase A baseline) |
| `phase-a` | Raw evidence only — emit `[PHASE-A]` tag in report for scoring |
| `phase-b` | Run all 3 enrichment phases, inject context blocks, emit `[PHASE-B]` tag |

Default: `none` (backwards compatible — existing sessions unchanged).

When `phase-b` is active:
1. Extract CPUID from evidence or system snapshot
2. Run Phase 1 → Phase 2 → Phase 3 in sequence
3. Prepend all context blocks to the BugScout evidence payload
4. Tag the session report with enrichment provenance

---

## Bias Prevention Checklist

Before every Phase B run, verify:
- [ ] `exclude_hsd_ids` contains all HSD IDs used to design the repro script
- [ ] Phase 3 results have been filtered through the field whitelist (no root_cause fields)
- [ ] The evaluation case is NOT the same HSD that was reproduced (or if same, Phase 3 is skipped)
- [ ] Report clearly labels whether it is Phase A or Phase B so scores are not mixed

---

## Files

| File | Purpose |
|---|---|
| `SKILL.md` | This file — skill specification |
| `mcp_enrichment.py` | Python implementation (Phase 1/2/3 orchestrator) |
| `field_whitelist.py` | HSD field extraction with root-cause redaction |
| `context_block_builder.py` | Builds structured context injection blocks |
