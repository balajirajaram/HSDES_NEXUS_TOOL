---
title: ACD / Crash Log Debug Handbook
platform: GNR / DMR / OKS
source: Oak_Stream_RAS_PAS.md (v1.2), GNR_DMR_Reset_blocking.md (v0.95), DMR-AI_RAS_Specification_0.md
crawled_at: 2026-03-27
---

# ACD / Crash Log Debug Handbook

Sourced from Intel platform RAS PAS documentation and GNR/DMR reset-blocking specifications.

---

## Overview

Intel provides two complementary crash-data collection technologies:

| Technology | Acronym | Who collects | Trigger | Data volume |
|---|---|---|---|---|
| Crash Log | CL | CPU silicon + S3M | IERR or MCERR (any) | Small, always available |
| Autonomous Crash Dump | ACD | BMC firmware | CATERR# hold (IERR only) | Large, pre-AWR only |

**ACD** gathers a larger data set than Crash Log but requires BMC firmware to be the
collection agent. ACD is a **pre-AWR only** flow — it must complete before the platform
issues a warm reset.

**Crash Log** is always available (even on BMC-less platforms) and covers CPU state, IBL
resets, and S3M crash records after IERR or MCERR.

---

## ACD Trigger Flow

### 1. CATERR# Detection

| Signal | Type | Platform action |
|---|---|---|
| CATERR# hold | IERR | CPLD passes to BMC → BMC triggers ACD |
| CATERR# pulse | MCERR | ACD not triggered (Crash Log only) |

### 2. BMC / CPLD Interaction

```
CATERR# hold detected
    → CPLD: pass CATERR# hold through to BMC
    → BMC: trigger ACD (collect crash data via OOBMSM)
    → BMC: assert CLIP = ERR2# (do NOT request reset yet)
    → ACD collection completes or WDT expires
    → BMC: assert xxRESET_N to recover platform
```

**Key constraint**: PLTRST_SYNC# de-assertion and GBL_RST_WARN# assertion are **ignored**
while CATERR# is held, preventing unexpected resets during error harvesting.

### 3. Reset Blocking

During ACD collection, the platform **blocks all non-platform-initiated resets**:

- OS warm reset (PLTRST_SYNC# de-assertion) → ignored while CATERR# held
- LT.RESET from uCode → suppressed
- S3M resets → routed to CATERR only

This prevents ACD interruption. The watchdog timer (WDT) acts as a final failsafe.

---

## Crash Log Overview

### Collection Scope (per IERR or MCERR)

- All CPU Crash Log records (cores, TOR, uncore)
- S3M Crash Log record (IBL, reset context, PCH-equivalent data)

### Key Registers

```
OOBMSM Gen3 → CrashLog HW Engine
    Telemetry API → extract crash log records
    Converged Crash Log HAS → decode fields
```

**Reference**: BHS Platform Debug Specification → `goto/PlatformDebugSpec.BHS#crashlog`

---

## Error Register Collection

### MCA Banks

Collected by ACD via OOBMSM sideband path:

| Bank range | Subsystem |
|---|---|
| 0–3 | IFU / DCU (core) |
| 4–5 | MLC |
| 6–7 | LLC / CHA |
| 8–9 | UPI |
| 10–13 | IMC |
| 14–15 | IIO / PCIe |

**For each bank collect:**
- MCI_STATUS (bits: UC=61, PCC=52, EN=55, OVER=62, VALID=63)
- MCI_ADDR
- MCI_MISC

### iMC Error Registers (DMR / OKS)

> **Note (DMR-AI RAS Specification §9)**: Crashlog and ACD need to collect iMC error
> registers and MCA banks from the CBB via OOBMSM. A new path must be available to read
> these registers. This is an **open work item** as of v0.

iMC registers to collect:
- `CORRERRORSTATUS` — corrected error threshold/count
- `CORRERRSTATUS2` — corrected error count per DIMM slot
- `UCERRORSTATUS` — uncorrected error details
- `MCERRCOUNTDOWN` — error countdown register

---

## Debug Steps — ACD Triage

### Step 1: Identify the Error Type

```
UC bit (MCI_STATUS[61]) = 0  → CORRECTED
UC bit = 1, PCC = 0          → UNCORRECTED (recoverable)
UC bit = 1, PCC = 1          → FATAL (IERR)
```

If IERR: ACD was likely triggered. If MCERR: ACD may or may not have run.

### Step 2: Identify the Bank and Subsystem

Read primary bank (highest severity first):

```python
# BugScout crashdump_router._subsystem_from_bank(bank_id)
# Mapping: 0-3→core, 4-5→mlc, 6-7→llc, 8-9→upi, 10-13→imc, 14-15→iio
```

Cross-reference with component from HSD to confirm subsystem alignment.

### Step 3: Decode the Crash Signature

```
Signature format: <PLATFORM>_MCA_Bank<N>_<ERROR_TYPE>_<SUBSYSTEM>
Example: DMR_MCA_Bank10_FATAL_IMC
```

Search the KB for matching entries:

```python
# BugScout: HandbookRAG.from_default_root().retrieve(signature, top_k=5)
```

### Step 4: Verify Against Arch Spec via MCP

**GENI MCP** (`DebugAssistantAgentTool`):
```
For HSD {hsd_id}, component {component}:
Given crash signature: {signature}
Given primary bank: {bank_id} ({subsystem})
Given error type: {error_type}

1. Does this bank/subsystem combination match the reported symptom?
2. What register state would confirm this failure at time of crash?
3. Is this consistent with known {platform} ACD root causes?
4. What debug steps from the ACD handbook apply here?
```

**Co-Design Specs MCP** (`codesign-ask-specs-and-wikis`):
```
For {platform}, component {component}:
Verify whether {subsystem} failures with {error_type} classification
at MCA Bank {bank_id} are architecturally expected.
Reference: Platform Debug Architecture specification (OKS_PDS_main.html).
```

### Step 5: Match Against Known Failure Patterns

| Pattern | Primary Bank | Subsystem | Root Cause |
|---|---|---|---|
| DSA/IAA hang | 10–13 (IMC) or 14 (IIO) | IMC or PCIe | Translation queue starvation, completion buffer exhaustion |
| UBR VN0 credit loss | 5 (UPI/SCF) | UPI | VN credit counter overflow; HAMVF timeout cascade |
| QAT segfault | 0–3 (core) | IFU/DCU | MSI-X/VFIO mapping + iommufd BAR alignment |
| M2IOSF ordering | 6–7 (LLC) | M2IOSF | tph_mapping_wr_ic + PCIe relaxed ordering |

### Step 6: Collect Additional Evidence

If the crash signature points to a specific subsystem, collect:

```bash
# Core/MCA state
cd.mca_dump_dmr           # full MCA register dump
cd.mca_decode             # decoded MCA error strings
sv.sockets.uncore.m2iosf.show()

# IMC / memory
sv.socket0.imc.show()

# PCIe / IIO
lspci -vvv
dmesg | grep -i 'aer\|iommu\|vfio'

# Platform event log
ipmitool sel list
ipmitool sdr list
```

---

## ACD vs Crash Log — When to Use Which

| Scenario | Recommended path |
|---|---|
| IERR on platform with BMC | Use ACD — larger data set |
| MCERR without IERR | Use Crash Log first |
| BMC-less platform | Use Crash Log only |
| Need TOR state | ACD (CL may bridge gap for 3-strike) |
| Need all-core state | ACD |
| Quick triage baseline | Crash Log |

---

## Common Root Causes in ACD-Captured Failures (DMR Accelerators)

### DSA Hang — Translation Queue Arbitration Deadlock

- **Trigger**: Src1 fills all 112 translation queue entries; Src2 blocked; Reduce requires both → deadlock
- **Workaround**: Limit Reduce/ReduceDC to ≤448KB; clear WQ OPCFG bits 25+26
- **MCA signature**: IIO bank, FATAL or UNCORRECTED
- **Collect**: `sv.sockets.uncore.iio.dsa.tlb_queue_depth`, `sv.sockets.uncore.iio.dsa.wq_opcfg`

### UBR VN0 Credit Loss

- **Trigger**: VN credit counters wrap; HAMVF timeout; MCE cascade
- **BIOS WA**: `EnableSpecificUbrVnCreditWa=1` (partial mitigation)
- **MCA signature**: UPI bank, corrected or uncorrected
- **Collect**: `sv.sockets.uncore.upi.vn_credit_count`, PCU debug registers

### SFI Poison Passthrough (>64B)

- **Trigger**: Poison only detected in first 64B chunk; remainder silent
- **WA**: Disable SFI poison passthrough; use MCA containment
- **MCA signature**: SCF/SFI bank
- **Collect**: `sv.sockets.uncore.sfi.poison_status`, MCI_STATUS for SCF bank

### DSA Gather Copy Completion Buffer Exhaustion

- **Trigger**: Completion buffer fills; no descriptor completion
- **WA**: Use `sglsize=1` for Gather Copy (A0 erratum, no HW fix)
- **MCA signature**: IIO bank, hang (no MCA — requires live register capture)
- **Collect**: DSA completion record status, `sv.sockets.uncore.iio.dsa.compl_buf_count`

---

## References

- Oak Stream RAS PAS (v1.2) — Section 6.7.4.1 (Crash Log), Section 6.7.4.2 (ACD)
- GNR/DMR Reset Blocking Specification (v0.95) — Section 1.1–1.2
- DMR-AI RAS Specification (v0) — Section 9 Error Harvesting
- BHS Platform Debug Specification → `goto/PlatformDebugSpec.BHS`
- Converged Crash Log Technology HAS
- OOBMSM Gen3 HAS (CrashLog HW Engine)
