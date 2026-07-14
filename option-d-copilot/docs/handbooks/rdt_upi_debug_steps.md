# RDT / UPI Debug Handbook — GNR / SRF / CWF

Grounding reference for the `handbook-rag` skill. Sections are ranked by keyword overlap
with `{cluster}` + `{failure_class}` + symptom terms. Keep each pattern short and factual;
cite the source HSD. **HSDES is the source of truth** — correct a pattern if HSDES contradicts it.

---

## UPI degradation via KitPortDisable — system hang
**Cluster:** upi · **Class:** hang · **Family:** GNR (AP/SP), applies to multi-socket 2S–8S.
**Symptom:** System HUNG after degrading a UPI link via BIOS knobs
`Cpu*P*KitPortDisable` and cold reboot; often 100% reproducible; recovers only after
several power-cycles. Hang post codes seen across sightings: `0xA3`, `0xA7`, `23`.
**Likely root cause:** A degradation topology that disables a UPI link which must remain
always-enabled (especially **UPI0**). On GNR, UPI0 disable is a **DFx-only** knob;
production BIOS does not support disabling UPI0. If a socket loses all active links, or
UPI0 is disabled, the fabric fails to train and the system hangs.
**Confirmed analog:** HSD 16024158116 (GNR-AP B0) — boot hang at PC 0xA3 when UPI stack
disabled via BIOS knobs; fix = keep ≥1 UPI link active / do not disable UPI0
(tracking: 14020755652 "lift UPI0 always-enabled restriction").
**Related (mostly rejected / no-RC):** 16025091446 (UPI PHY DRIFT BUFFER ALARM),
15013554206 (PC 23 endless reset), 22016429791 (POST A7), 15015890816 (8S degrade hang).
**First checks:**
1. Capture exact hang **post code**.
2. Map disabled ports → physical links; confirm **UPI0 not disabled** and ≥1 link active per socket.
3. `sv.socket<N>.upi.<phy_status_reg>.read()` — look for DRIFT BUFFER ALARM / not-trained.

---

## UPI link CRC / retrain storm
**Cluster:** upi · **Class:** crc/link.
**Symptom:** Repeated UPI CRC errors, link retrain / L0p transitions, correctable-error
floods, or bandwidth degradation logged in MCA UPI/KTI banks.
**First checks:** decode UPI/KTI MCA bank `MCi_STATUS`; read UPI PHY status and per-lane
error counters; check cabling/PCB rework history; compare against known-good stepping.
**PythonSV:** `sv.socket<N>.upi.<link>.status.read()`, per-lane CRC counters, PHY eye margins.

---

## UPI credit loss / VN0 deadlock
**Cluster:** upi · **Class:** hang.
**Symptom:** Traffic stalls with no CRC errors; a socket stops making forward progress;
VN0 credits appear exhausted; possible 3-strike/watchdog timeout.
**First checks:** read UPI credit counters (VN0/VNA) both directions; check for stuck
outstanding requests at CHA; capture MCA before reset.

---

## MCE / MCA machine-check (RDT scope)
**Cluster:** core/imc/cha/upi · **Class:** mce/mca.
**Signature fields:** `MCi_STATUS` (VAL/UC/PCC/poison, MCACOD/MSCOD), `MCi_ADDR` (when
ADDRV set), bank number → subsystem (see `crash-parser` bank map).
**First checks:** decode the highest-severity bank first; classify SRAR/SRAO/UCNA;
correlate `RIP`/instruction pointer with the failing flow; check poison propagation path.

---

## Init failure / degradation topology
**Cluster:** system/upi · **Class:** init-failure.
**Symptom:** Boot stops at a specific POST/PC after a topology or IP-disable knob change
(UPI, core, mem, HCA, FlexBus). May only boot after multiple power-cycles.
**First checks:** diff working vs failing topology; re-enable one IP at a time to bisect the
offending knob; confirm the knob is production-supported vs DFx-only (cf. 16024158116).

---

*Seeded 2026-07 from live triage of HSD 16030948515 ([GNR AP][2S] system HUNG after UPI
degradation via KitPortDisable). Extend with new confirmed patterns as the KB grows.*
