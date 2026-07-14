# GNR / SRF / CWF — Debug Command Library (all domains)

Command catalog for the `hsd-triage` and `live-debug` skills. Use it to turn a hypothesis
into a concrete **next-step data-collection plan**. Commands are grouped by **domain** and by
**failure class**. Paths marked `<...>` are placeholders — confirm the exact register path for
the target project/stepping before running (see "Confirming a register path" at the bottom).

> Conventions
> - **PythonSV** (a.k.a. `sv` / pysv): `sv.sockets`, `sv.socket0`, `sv.socket0.uncore`, etc.
> - **cscripts / ITP / IPC**: `ipccli`, `itp`, `cscripts` — for halt/JTAG-based access.
> - **OS**: run on the SUT (Linux/SVOS) — `dmesg`, `rdmsr`, `mcelog`, `cpuid`, `lspci`.
> - **BMC / platform**: `ipmitool`, POST/checkpoint capture, power control.
> - Always record: project, **stepping** (gnr-b0 / srf-a0 / cwf-a0), ucode/IFWI/BIOS rev,
>   socket/cluster, and the exact command output.

---

## 0. Universal first-pass (any HSD, any domain)

```python
# PythonSV — connect and snapshot
import pysv ; sv = pysv.get_sv()           # or: from pysv import sv
sv.refresh()                               # rebuild the target model
sv.sockets.taps.pinstatus                  # power/pin state (are sockets alive?)
sv.socket0.uncore.pcode_mailbox_status()   # punit/pcode alive?  (path varies by project)
```

```bash
# OS (SUT) — quick health + error surface
dmesg -T | tail -n 200
dmesg -T | grep -iE 'mce|machine check|hardware error|panic|oops|hung|watchdog|throttl'
journalctl -k -b | tail -n 300
cat /var/log/mcelog 2>/dev/null ; mcelog --client 2>/dev/null
rdmsr -a 0x1A2   # TEMPERATURE_TARGET (example) ; use -a for all CPUs
```

```bash
# BMC / platform — is it a boot/hang case?
ipmitool sel elist | tail -n 50           # system event log
ipmitool sdr elist | grep -iE 'temp|power|fault'
# POST / checkpoint code at hang (platform-specific): read BMC postcode buffer / port 80h
```

**RPT extraction (pre-silicon / triage runs):** from `*.rpt` / `*.rpt.gz`
`BUCKET NAME:` → bucket · `CLUSTER:` → cluster · `-stepping` in `TRIAGE CMD-LINE:` → stepping
· `TEST RES PATH:` → failure_path.

---

## 1. RAS / MCA / MCE (machine-check — applies to every domain)

```bash
# OS — decode machine-check banks
mcelog --dump-raw 2>/dev/null
rdmsr -a 0x179     # IA32_MCG_CAP  (number of banks)
rdmsr -a 0x17A     # IA32_MCG_STATUS
# For each bank N: STATUS=0x401+4N, ADDR=0x402+4N, MISC=0x403+4N, CTL=0x400+4N
for N in $(seq 0 31); do echo "bank $N"; rdmsr -a $((0x401 + 4*N)); done
```

```python
# PythonSV — structured MCA decode across all banks
sv.sockets.uncore.mca.dump()                       # all machine-check banks (path varies)
sv.socket0.core0.thread0.arch.mca.dump()           # core banks
# Key fields to record from MCi_STATUS: VAL, UC, PCC, EN, MISCV, ADDRV, poison, MCACOD, MSCOD
sv.socket0.uncore.mca.decode_last()                # if a decode helper exists
```

Classify: **SRAR** (recoverable action required), **SRAO** (action optional), **UCNA**
(uncorrected no-action), **CE** (corrected). Decode the **highest-severity, PCC=1** bank first,
then map bank → domain (see §2 map).

---

## 2. Bank → domain quick map (RAS)

| Bank group | Domain | Go to |
|---|---|---|
| IFU / DCU / DTLB / MLC core banks | **Core** | §3 |
| CHA / LLC banks | **CHA / Uncore** | §4 |
| IMC / memory-controller banks | **IMC / Memory** | §5 |
| M2MEM / mesh / M3 banks | **Fabric / Mesh** | §6 |
| UPI / KTI link banks | **UPI / KTI** | §7 |
| IIO / PCIe / CXL banks | **IIO / PCIe / CXL** | §8 |
| Punit / Pcode / PM banks | **Power / PM** | §9 |

---

## 3. Core

```python
sv.socket0.core0.thread0.arch.rip                       # last IP
sv.socket0.core0.thread0.arch.cr_state()                # control regs
sv.socket0.core0. threads.arch.mca.dump()               # per-thread MCA
sv.socket0.core0.ml3_cr_pic_status                      # local APIC / interrupt state (path varies)
sv.socket0.cores.pma.c_state                            # per-core C-state (hang: stuck in Cx?)
```
```bash
rdmsr -p <cpu> 0x1D9    # IA32_DEBUGCTL      | cpuid -1        # topology/features
```

## 4. CHA / Uncore / LLC

```python
sv.socket0.uncore.cha.dump()                            # CHA credit/occupancy/error state
sv.socket0.uncore.cha0.tor_occupancy                    # TOR (table-of-requests) — hang: stuck entries?
sv.socket0.uncore.cha.llc_ways                          # CAT/LLC allocation (RDT)
sv.socket0.uncore.ubox.ncevents                         # uncore error events
```

## 5. IMC / Memory (DDR5 / HBM)

```python
sv.socket0.uncore.memss.mc0.dump()                      # memory controller status
sv.socket0.uncore.memss.mc0.ch0.retry_status            # DDR retry / CRC
sv.socket0.uncore.memss.imc.mode_registers             # MR readback
sv.socket0.uncore.memss.thermal                        # DRAM thermal / throttle
```
```bash
dmesg | grep -iE 'edac|memory error|correctable|uncorrectable|dimm|rank'
# EDAC (if enabled):
grep -R . /sys/devices/system/edac/mc/ 2>/dev/null | grep -iE 'ce_count|ue_count'
```

## 6. Fabric / Mesh (M2MEM / M3 / mesh)

```python
sv.socket0.uncore.m2mem.dump()                          # mem-agent credits/occupancy
sv.socket0.uncore.mesh.credits                          # mesh credit counters (deadlock hunt)
sv.socket0.uncore.m3.dump()
```

## 7. UPI / KTI (inter-socket link)

```python
sv.socket0.uncore.upi.upi0.status                       # link up/L0/L0p/init state
sv.socket0.uncore.upi.upi0.phy_status                   # PHY: DRIFT BUFFER ALARM / trained?
sv.socket0.uncore.upi.upi0.crc_err_cnt                  # per-link CRC error counter
sv.socket0.uncore.upi.upi0.credits                      # VN0/VNA credit counters (stall hunt)
sv.sockets.uncore.upi.link_map()                        # port→physical-link mapping
```
```
# BIOS knob check (degradation cases): confirm Cpu*P*KitPortDisable and whether UPI0/link0 disabled
```

## 8. IIO / PCIe / CXL (FlexBus)

```python
sv.socket0.uncore.iio.dump()                            # IIO error/status
sv.socket0.uncore.iio.pcie.port0.ltssm                  # PCIe LTSSM link state
sv.socket0.uncore.iio.cxl.dump()                        # CXL / FlexBus state
```
```bash
lspci -vvv | grep -iE 'LnkSta|CESta|UESta|DevSta'       # PCIe link + AER status
dmesg | grep -iE 'pcieport|aer|cxl|dpc|correctable'
```

## 9. Power / PM / Punit / Thermal

```python
sv.socket0.uncore.punit.dump()                          # pcode/punit status
sv.socket0.uncore.punit.pstate                          # current P-state / ratio
sv.socket0.uncore.punit.cstate_residency                # package/core C-state residency
sv.socket0.uncore.punit.thermal_status                  # PROCHOT / thermal throttle
sv.socket0.uncore.punit.rapl                            # power limits (RAPL)
```
```bash
rdmsr -a 0x198   # IA32_PERF_STATUS | rdmsr -a 0x1B1 # IA32_PACKAGE_THERM_STATUS
turbostat --quiet --interval 1 --num_iterations 5 2>/dev/null
```

## 10. Accelerators (DSA / IAA / QAT / DLB)

```bash
accel-config list 2>/dev/null                           # DSA/IAA device + WQ state
dmesg | grep -iE 'idxd|dsa|iaa|qat|dlb|dmar|iommu|swq|dwq'
cat /sys/bus/dsa/devices/dsa0/state 2>/dev/null
```
```python
sv.socket0.uncore.dsa0.dump()                           # DSA engine/WQ/completion state
sv.socket0.uncore.iaa0.dump()
```

## 11. Security (TDX / SGX / TME-MK)  — if HSD is security-domain

```bash
rdmsr -a 0x981   # IA32_TME_CAPABILITY (example) | dmesg | grep -iE 'tdx|sgx|seam|tme|mktme'
```
```python
sv.socket0.uncore.seamrr                                # SEAMRR / TDX module state (path varies)
```

## 12. Boot / BIOS / Reset (hang / no-boot)

```
# Capture the exact POST/checkpoint code at the hang (BMC postcode buffer / port 80h).
# Compare against known hang codes: 0xA3 / 0xA7 / 0x23 (UPI-degradation family), etc.
```
```python
sv.refresh(); sv.sockets.taps.idcode                    # are TAPs alive after hang?
itp.halt() ; itp.threads[0].state                       # ITP halt to inspect a hung core
```

---

## Failure-class → domain starting point

| Failure class | Start at |
|---|---|
| Hang / no forward progress | §12 boot/POST → §7 UPI credits → §4 CHA TOR → §6 mesh → §3 core C-state |
| MCE / MCA fatal or corrected | §1 + §2 (decode banks, map to domain) |
| CRC / link errors | §7 UPI, §8 PCIe/CXL, §5 DDR retry |
| Data corruption / mismatch | §3 core, §4 CHA/LLC, §5 IMC, poison path in §1 |
| Init / degradation / topology | §12 + §7 (link map) + confirm knob is production vs DFx-only |
| Performance / bandwidth | §9 P-state/thermal, §4 LLC/RDT, §6 mesh credits |
| Thermal / power / throttle | §9 punit/RAPL/thermal + BMC SDR |

---

## Confirming a register path (when unsure)

Do **not** guess a register path in a report. To confirm on the actual target:
```python
sv.socket0.uncore.upi.upi0.show()        # list children of a node
dir(sv.socket0.uncore)                    # enumerate available domains/blocks
sv.search("upi")                          # search the target model for a name (if supported)
sv.socket0.uncore.upi.upi0.<reg>.description   # field description / offset
```
If a helper/decoder exists in the project's cscripts, prefer it (e.g. `upi.printLinkStatus()`).
State clearly in the report which commands are **confirmed** vs **needs path confirmation**.
