# Debug Log Taxonomy

Defines the complete set of debug log categories available for HSD triage and root cause
analysis. Organized by domain with specific collection commands and trigger conditions.

This taxonomy is referenced by the GENI MCP prompt in Phase 4 of skill.md.
When extending to new domains, add a new section following the same structure.

---

## Domain: Accelerator (DSA / IAA / QAT)

### 1. register_dump

**Description**: Full register state capture of accelerator configuration and status registers.

**Collection Commands**:
```python
# DSA registers
sv.socket0.imh0.acc.acc_0.dsa.show()
sv.socket0.imh0.acc.acc_0.dsa.opcap0.show()
sv.socket0.imh0.acc.acc_0.dsa.opcap1.show()
sv.socket0.imh0.acc.acc_0.dsa.opcap2.show()
sv.socket0.imh0.acc.acc_0.dsa.gencap.show()
sv.socket0.imh0.acc.acc_0.dsa.cmdcap.show()

# IAA registers
sv.socket0.imh0.acc.acc_0.iaa.show()
sv.socket0.imh0.acc.acc_0.iaa.gencap.show()
sv.socket0.imh0.acc.acc_0.iaa.opcap0.show()

# QAT/CPM registers
sv.socket0.imh0.acc.acc_0.cpm.show()
```

**When to collect**: Always on first triage pass. Provides baseline device state.

---

### 2. perfmon_counters

**Description**: Performance monitoring counters that track data flow through the accelerator
pipeline — reads, writes, processed bytes, stalls.

**Collection Commands**:
```python
# DSA perfmon
sv.socket0.imh0.acc.acc_0.dsa.showsearch("cntr")
sv.socket0.imh0.acc.acc_0.dsa.cntrcfg_0.show()   # EV_CL_READ config
sv.socket0.imh0.acc.acc_0.dsa.cntrcfg_1.show()   # EV_CL_PROCESSED config
sv.socket0.imh0.acc.acc_0.dsa.cntrcfg_2.show()   # EV_CL_WRITE config
sv.socket0.imh0.acc.acc_0.dsa.cntrcfg_3.show()   # configurable
sv.socket0.imh0.acc.acc_0.dsa.cntrcfg_4.show()
sv.socket0.imh0.acc.acc_0.dsa.cntrcfg_5.show()
sv.socket0.imh0.acc.acc_0.dsa.cntrcfg_6.show()
sv.socket0.imh0.acc.acc_0.dsa.cntrcfg_7.show()
sv.socket0.imh0.acc.acc_0.dsa.cntrdata_0.show()  # counter values
sv.socket0.imh0.acc.acc_0.dsa.cntrdata_1.show()
sv.socket0.imh0.acc.acc_0.dsa.cntrdata_2.show()
sv.socket0.imh0.acc.acc_0.dsa.cntrdata_3.show()
sv.socket0.imh0.acc.acc_0.dsa.cntrdata_4.show()
sv.socket0.imh0.acc.acc_0.dsa.cntrdata_5.show()
sv.socket0.imh0.acc.acc_0.dsa.cntrdata_6.show()
sv.socket0.imh0.acc.acc_0.dsa.cntrdata_7.show()

# IAA perfmon
sv.socket0.imh0.acc.acc_0.iaa.showsearch("cntr")
```

**When to collect**: Hang scenarios, performance issues, data flow stalls, unexpected idle state.

---

### 3. swerror_dump

**Description**: Software error registers that capture descriptor-level failure information
including error codes, work queue indices, operation types, and addresses.

**Collection Commands**:
```python
# DSA software errors
sv.socket0.imh0.acc.acc_0.dsa.swerror0.show()   # valid, overflow, err_code, wq_index
sv.socket0.imh0.acc.acc_0.dsa.swerror1.show()   # batch_index, error_info
sv.socket0.imh0.acc.acc_0.dsa.swerror2.show()   # fault address

# IAA software errors
sv.socket0.imh0.acc.acc_0.iaa.swerror0.show()
sv.socket0.imh0.acc.acc_0.iaa.swerror1.show()
sv.socket0.imh0.acc.acc_0.iaa.swerror2.show()

# Error interpretation
# SWERROR0 fields: valid:1, overflow:1, desc_valid:1, wq_index_valid:1,
#                  batch:1, rw:1, priv:1, err_info_valid:1,
#                  err_code:8, wq_index:8, operation:8, pasid:20
# SWERROR1 fields: batch_index:16, error_info:32
# SWERROR2 fields: fault_address:64
```

**When to collect**: Any descriptor failure, operation error, completion record with non-zero status.

---

### 4. pcie_aer

**Description**: PCIe Advanced Error Reporting registers — uncorrectable, correctable, and
root error status for the accelerator's PCIe function.

**Collection Commands**:
```python
# PCIe AER status registers
sv.socket0.imh0.acc.acc_0.dsa.ppaercs.show()      # correctable error status
sv.socket0.imh0.acc.acc_0.dsa.ppaerucsts.show()   # uncorrectable error status
sv.socket0.imh0.acc.acc_0.dsa.ppaerucsev.show()   # uncorrectable severity
sv.socket0.imh0.acc.acc_0.dsa.ppaerrootsts.show() # root error status

# QAT/CPM PCIe AER
sv.socket0.imh0.acc.acc_0.cpm.ppaercs.show()
sv.socket0.imh0.acc.acc_0.cpm.ppaerucsts.show()
```

**When to collect**: Advisory Non-Fatal errors, device not responding, link errors, AER interrupts.

---

### 5. dmesg_kernel

**Description**: Kernel message buffer filtered for accelerator-related messages including
driver load, device initialization, error reports, and MCE events.

**Collection Commands**:
```bash
# General accelerator kernel messages
dmesg | grep -i "dsa\|iax\|qat\|cpm\|idxd"

# Driver initialization
dmesg | grep -i "svDeviceInit"

# Machine Check Exceptions
dmesg | grep -i "mce\|machine check"

# IOMMU/VT-d related
dmesg | grep -i "iommu\|dmar\|vtd"

# PCIe errors
dmesg | grep -i "AER\|pcie.*error"

# Full timestamped dump
dmesg -T > /tmp/dmesg_full.log
```

**When to collect**: Driver failures, device not found, module load errors, system-level errors.

---

### 6. failvect_trace

**Description**: FAILVECT memory comparison dumps from Arden comparators showing address,
expected vs. observed data, target range, and TLP type for DMA verification failures.

**Collection Commands**:
```
# Captured automatically by test framework (rocket/atlas)
# Look for <FAILVECT> sections in test output logs

# Key fields in FAILVECT:
# Target Name  : ARDEN_MEM_SOCKET0_...
# ID           : <target_id>
# Path         : /sv/socket0/imh0/bus1/...
# Base Address : 0x...
# Errors from Arden Ramless Error Registers:
# Address  Expected  Observed  TgtRng  TLP Type
```

**When to collect**: Data corruption, DMA write mismatches, memory compare failures, CXL data integrity issues.

---

### 7. descriptor_status

**Description**: Completion record and descriptor state showing operation result, status codes,
bytes completed, and fault information.

**Collection Commands**:
```python
# Read completion record from memory (address from descriptor submission)
# Completion record fields:
#   status: 0x00=success, 0x01=page_fault, 0x03=batch_error, etc.
#   result: bytes completed
#   fault_info: page fault address if applicable

# Work descriptor inspection
sv.socket0.imh0.acc.acc_0.dsa.showsearch("desc")

# Batch descriptor array inspection (if batch:1 in SWERROR)
# Read batch descriptor addresses from completion record
```

**When to collect**: Operation failures, partial completions, page faults, batch errors.

---

### 8. wq_state

**Description**: Work queue configuration and runtime state including queue depth, priority,
occupancy, and PASID/group assignment.

**Collection Commands**:
```python
# DSA work queue configuration
sv.socket0.imh0.acc.acc_0.dsa.wqcfg_0.show()
sv.socket0.imh0.acc.acc_0.dsa.wqcfg_1.show()
sv.socket0.imh0.acc.acc_0.dsa.wqcfg_2.show()
sv.socket0.imh0.acc.acc_0.dsa.wqcfg_3.show()

# Group configuration
sv.socket0.imh0.acc.acc_0.dsa.grpcfg_0.show()
sv.socket0.imh0.acc.acc_0.dsa.grpcfg_1.show()

# General configuration
sv.socket0.imh0.acc.acc_0.dsa.gencfg.show()

# Engine configuration
sv.socket0.imh0.acc.acc_0.dsa.engcfg_0.show()
sv.socket0.imh0.acc.acc_0.dsa.engcfg_1.show()
sv.socket0.imh0.acc.acc_0.dsa.engcfg_2.show()
sv.socket0.imh0.acc.acc_0.dsa.engcfg_3.show()
```

**When to collect**: WQ overflow, descriptor rejection, priority inversion, PASID conflicts.

---

### 9. vtd_context

**Description**: VT-d / IOMMU state including invalidation queue status, page table entries,
PASID table, and ATS (Address Translation Service) configuration.

**Collection Commands**:
```python
# VT-d registers for DSA
sv.socket0.imh0.acc.acc_0.dsa.showsearch("vtd")
sv.socket0.imh0.acc.acc_0.dsa.showsearch("ats")
sv.socket0.imh0.acc.acc_0.dsa.showsearch("pasid")
sv.socket0.imh0.acc.acc_0.dsa.showsearch("prs")

# IOMMU context
sv.socket0.imh0.bus0.showsearch("iommu")

# Page request service status
sv.socket0.imh0.acc.acc_0.dsa.showsearch("prq")
```

**When to collect**: Page faults, PASID errors, ATS failures, invalidation timeouts, DMA to wrong address.

---

### 10. memory_map

**Description**: MMIO BAR regions, CXL HDM decoder state, and physical address mapping
for accelerator-accessible memory regions.

**Collection Commands**:
```python
# BAR configuration
sv.socket0.imh0.acc.acc_0.dsa.showsearch("bar")

# CXL memory regions (if CXL involved)
sv.socket0.imh0.bus1.pciExpress2.cxl-01.show()
sv.socket0.imh0.bus1.pciExpress2.cxl-01.global.show()

# HDM decoder state
sv.socket0.imh0.bus1.pciExpress2.cxl-01.showsearch("hdm")

# System address map
sv.sockets.uncore.memss.mcs.chs.showsearch("addr")
```

**When to collect**: CXL address errors, BAR misconfiguration, P2P traffic issues, address decode failures.

---

### 11. firmware_log

**Description**: QAT/CPM microengine firmware load status, device configuration,
and runtime firmware state.

**Collection Commands**:
```python
# QAT firmware load status
# Look for in QAT initialization logs:
#   qat_load_me: ME_N FW is already loaded
#   qat_start_me: Device reported error
#   accel_do_fw_loading: start me failed

# CPM device configuration
sv.socket0.imh0.acc.acc_0.cpm.showsearch("fw")
sv.socket0.imh0.acc.acc_0.cpm.showsearch("me")

# QAT ring buffer state
# Look in test output for:
#   combinedTxpMgr / srvActor / srvDirector logs
```

**When to collect**: QAT initialization failures, FW load errors, crypto service timeouts, ME state issues.

---

### 12. punit_mailbox

**Description**: Platform power management unit registers including P-state, power gating,
and accelerator power state transitions.

**Collection Commands**:
```python
# Punit registers
sv.socket0.imh0.showsearch("punit")
sv.sockets.uncore.oobmsm_punit.show()

# Power state
sv.socket0.imh0.acc.acc_0.dsa.showsearch("pwr")
sv.socket0.imh0.acc.acc_0.dsa.showsearch("idle")
```

**When to collect**: Device not responding after idle, power state transition failures, clock gating issues.

---

### 13. arbiter_state

**Description**: Internal request arbiter state for DMA engines, translation request paths,
and resource allocation fairness counters.

**Collection Commands**:
```python
# DSA internal arbiter (translation request arbitration)
sv.socket0.imh0.acc.acc_0.dsa.showsearch("arb")
sv.socket0.imh0.acc.acc_0.dsa.showsearch("src")

# Request queue occupancy
sv.socket0.imh0.acc.acc_0.dsa.showsearch("req")
sv.socket0.imh0.acc.acc_0.dsa.showsearch("queue")

# Per-engine outstanding transactions
sv.socket0.imh0.acc.acc_0.dsa.showsearch("outstanding")
sv.socket0.imh0.acc.acc_0.dsa.showsearch("credit")
```

**When to collect**: Hang scenarios (especially with multi-source operations like Reduce),
starvation, deadlock, unfair resource allocation, large transfer failures.

---

### 14. tlb_pressure

**Description**: Translation lookaside buffer state including hit/miss rates, eviction
patterns, and IOTLB invalidation state.

**Collection Commands**:
```python
# IOTLB state
sv.socket0.imh0.acc.acc_0.dsa.showsearch("tlb")
sv.socket0.imh0.acc.acc_0.dsa.showsearch("iotlb")

# Translation cache statistics (if available via perfmon)
# Configure cntrcfg for TLB-related events:
#   EV_TLB_HIT, EV_TLB_MISS, EV_TLB_FLUSH

# Invalidation queue depth
sv.socket0.imh0.acc.acc_0.dsa.showsearch("inval")
```

**When to collect**: Performance degradation with address translation, large working sets,
frequent PASID switches, invalidation-related hangs.

---

### 15. interrupt_state

**Description**: MSI-X vector configuration, interrupt cause registers, and interrupt
masking state.

**Collection Commands**:
```python
# Interrupt cause
sv.socket0.imh0.acc.acc_0.dsa.intcause.show()
sv.socket0.imh0.acc.acc_0.iaa.intcause.show()

# MSI-X configuration
sv.socket0.imh0.acc.acc_0.dsa.showsearch("msix")
sv.socket0.imh0.acc.acc_0.dsa.showsearch("int")

# Interrupt masking
sv.socket0.imh0.acc.acc_0.dsa.showsearch("mask")
```

**When to collect**: Missing completions, interrupt storms, completion not delivered to SW.

---

### 16. event_capabilities

**Description**: Event capability registers defining supported operations, maximum transfer
sizes, and feature configurations (evntcap registers).

**Collection Commands**:
```python
# DSA event capabilities
sv.socket0.imh0.acc.acc_0.dsa.evntcap_0.show()
sv.socket0.imh0.acc.acc_0.dsa.evntcap_1.show()
sv.socket0.imh0.acc.acc_0.dsa.evntcap_2.show()
sv.socket0.imh0.acc.acc_0.dsa.evntcap_3.show()
sv.socket0.imh0.acc.acc_0.dsa.evntcap_4.show()
sv.socket0.imh0.acc.acc_0.dsa.evntcap_5.show()

# Operation capabilities
sv.socket0.imh0.acc.acc_0.dsa.opcap0.show()
sv.socket0.imh0.acc.acc_0.dsa.opcap1.show()
```

**When to collect**: Default value mismatches, capability register verification, feature enablement issues, GNR→DMR register delta validation.

---

## Domain: Common (Cross-Domain Logs)

### 17. mce_log

**Description**: Machine Check Exception logs capturing hardware error telemetry including
bank, status, address, and miscellaneous registers.

**Collection Commands**:
```bash
# MCE log extraction
mcelog --client
cat /var/log/mcelog

# From dmesg
dmesg | grep -i "mce\|machine check\|hardware error"

# Via PythonSV
sv.sockets.uncore.showsearch("mca")
sv.sockets.uncore.showsearch("mce")
```

**When to collect**: System hangs, target hang communicator events, uncorrectable errors, resets.

---

### 18. platform_topology

**Description**: System topology including socket/IMH/bus layout, device enumeration,
and accelerator instance discovery.

**Collection Commands**:
```python
# Socket topology
sv.sockets.show()
sv.socket0.imh0.show()
sv.socket0.imh1.show()

# Accelerator enumeration
sv.socket0.imh0.acc.show()
sv.socket0.imh0.acc.acc_0.show()

# Bus topology
sv.socket0.imh0.bus0.show()
sv.socket0.imh0.bus1.show()

# SVOS device initialization status
# dmesg | grep "svDeviceInit"
```

**When to collect**: Device not found, module load failures, topology discovery issues, multi-socket problems.

---

### 19. coherency_state

**Description**: Cache coherency protocol state relevant to accelerator DMA operations,
including snoop filter state, CXL.cache, and home agent tracking.

**Collection Commands**:
```python
# Home agent / CHA state
sv.sockets.uncore.chas.show()
sv.sockets.uncore.chas.showsearch("snoop")

# CXL coherency (if CXL target involved)
sv.socket0.imh0.bus1.pciExpress2.cxl-01.showsearch("coh")

# Bias/ownership state
sv.socket0.imh0.bus1.pciExpress2.cxl-01.showsearch("bias")
```

**When to collect**: Data corruption with concurrent CPU/device access, CXL.mem coherency failures, stale data reads.

---

### 20. link_state

**Description**: PCIe link training status, link width/speed, and electrical state.

**Collection Commands**:
```python
# PCIe link status
sv.socket0.imh0.acc.acc_0.dsa.showsearch("link")
sv.socket0.imh0.acc.acc_0.dsa.showsearch("lnk")

# Max Read Request Size (MRRS) — important for DSA hang scenarios
sv.socket0.imh0.acc.acc_0.dsa.showsearch("mrrs")
sv.socket0.imh0.acc.acc_0.dsa.showsearch("devctl")

# Ten-Bit Tag Requester Enable (TBTRE)
sv.socket0.imh0.acc.acc_0.dsa.showsearch("tbtr")
sv.socket0.imh0.acc.acc_0.dsa.showsearch("tag")
```

**When to collect**: Reduced bandwidth, completion timeouts, link retraining events, tag exhaustion.

---

## Domain: Custom Tools & Scripts

For testcases that do NOT use PythonSV directly — custom Python scripts, shell-based test
frameworks, proprietary tools, or direct hardware access utilities.

### 21. test_framework_verbose_log

**Description**: Verbose/debug-level output from the test framework itself (rocket, atlas,
custom Python harness). Contains test phase transitions, subtask results, error messages,
and timing information not visible in standard output.

**Collection Commands** (enable BEFORE running the test):
```bash
# Rocket / Atlas — increase verbosity
rocket -v <testcase> --loglevel debug 2>&1 | tee /tmp/rocket_verbose.log

# Custom Python test script — standard logging
python my_test.py --verbose --log-level DEBUG 2>&1 | tee /tmp/test_verbose.log

# Generic: capture both stdout and stderr with timestamps
script -q -c "<your command>" /tmp/test_session.log
unbuffer <your command> 2>&1 | ts '[%Y-%m-%d %H:%M:%.S]' | tee /tmp/test_timed.log
```

**When to collect**: Always for the first live debug iteration. Reveals which test phase
failed, error codes thrown by the framework, and exact failure timestamp for correlating
with hardware logs.

---

### 22. kernel_tracing

**Description**: Linux kernel trace events (ftrace/perf) capturing driver-level activity,
interrupt handling, DMA request dispatch, and completion callbacks during the test run.

**Collection Commands** (enable BEFORE test run, disable and collect after):
```bash
# Enable ftrace for DSA/IDXD driver
echo 1 > /sys/kernel/debug/tracing/tracing_on
echo 'idxd:*' > /sys/kernel/debug/tracing/set_event
echo 'dma:*' >> /sys/kernel/debug/tracing/set_event
echo 'iommu:*' >> /sys/kernel/debug/tracing/set_event

# Run your test here...

# Collect trace
cat /sys/kernel/debug/tracing/trace > /tmp/kernel_trace.log
echo 0 > /sys/kernel/debug/tracing/tracing_on

# Alternative: perf trace for syscall-level view
perf trace -e 'dma*,iommu*' -- <your command> 2>&1 | tee /tmp/perf_trace.log
```

**When to collect**: Driver crashes, DMA completion timeouts, interrupt storms, unexpected
kernel panics. Especially useful when the failure is inside the driver rather than hardware.

---

### 23. driver_debug_flags

**Description**: IDXD/DSA/IAA/QAT driver dynamic debug output. Linux kernel dynamic debug
lets you enable per-file or per-function log messages in the driver without recompiling.

**Collection Commands** (enable BEFORE test run):
```bash
# Enable IDXD driver debug messages
echo 'module idxd +p' > /sys/kernel/debug/dynamic_debug/control
echo 'module idxd +f' >> /sys/kernel/debug/dynamic_debug/control

# Enable QAT driver debug
echo 'module qat_c62x +p' > /sys/kernel/debug/dynamic_debug/control

# View active debug rules
cat /sys/kernel/debug/dynamic_debug/control | grep -E 'idxd|qat|iommu'

# Collect after test
dmesg -T | grep -E 'idxd|iommu|dmar|qat' > /tmp/driver_debug.log
```

**When to collect**: Driver initialization failures, WQ configuration errors, IOMMU
submission failures, completion record delivery issues.

---

### 24. tool_specific_log

**Description**: Logs produced by the specific custom tool or Python script used in the
testcase. Location and format depend on the tool — the agent infers the path from the
test command and any `--log-dir`, `--output`, `-o`, or similar flags.

**Collection Commands** (tool-specific — agent generates based on testcase context):
```bash
# Generic pattern: find log files created/modified during test window
find /tmp /var/log /home -newer /tmp/test_start_marker -name "*.log" 2>/dev/null

# Create a start-time marker before running the test:
touch /tmp/test_start_marker
<run your test>
find / -newer /tmp/test_start_marker -name "*.log" -o -name "*.txt" 2>/dev/null | grep -v proc

# Check common output directories
ls -lt /tmp/*.log /var/log/*.log ~/results/*.log 2>/dev/null | head -20
```

**When to collect**: Always when the testcase uses a custom tool. The agent uses GENI to
determine the expected output paths from the tool name and command-line flags.

---

### 25. hardware_event_log

**Description**: Hardware event / machine check logs from the BMC, BIOS NVRAM, or SEL
(System Event Log). Captures hardware-level errors that may precede the software failure.

**Collection Commands**:
```bash
# IPMI System Event Log
ipmitool sel list > /tmp/sel_dump.log
ipmitool sel elist > /tmp/sel_detail.log   # with descriptions

# ipmitool sensor dump (for thermal/power anomalies)
ipmitool sensor list > /tmp/ipmi_sensors.log

# BIOS/UEFI error log (if accessible)
efibootmgr -v 2>&1 | grep -i error

# From OS: hardware error driver
cat /sys/firmware/efi/efivars/ErrInfo-*/  2>/dev/null || true
```

**When to collect**: System resets during test, unexpected thermal shutdowns, uncorrectable
hardware errors (MCE), power-related failures, or any event where hardware state may have
changed mid-test.

---

### 26. network_fabric_log

**Description**: For tests involving remote DMA (RDMA), network fabric, or CXL interconnects:
logs from the fabric layer (IB verbs, CXL link status, ROCE counters).

**Collection Commands**:
```bash
# InfiniBand / RDMA
ibstat 2>/dev/null | tee /tmp/ibstat.log
ibv_devinfo 2>/dev/null | tee /tmp/ibv_devinfo.log
cat /sys/class/infiniband/*/ports/*/state 2>/dev/null

# RoCE / Ethernet fabric counters
ethtool -S <iface> 2>/dev/null | grep -i 'err\|drop\|miss\|retry'

# CXL link status (Linux 6.x+)
ls /sys/bus/cxl/devices/ 2>/dev/null
cat /sys/bus/cxl/devices/*/firmware_version 2>/dev/null
```

**When to collect**: Tests involving remote memory, CXL.mem accesses, RDMA operations, or
any scenario where data traverses a fabric link. Cross-domain data integrity failures.

---

## Interpretation Guide

How to read collected logs to confirm or reject failure hypotheses. Use these patterns
alongside the log taxonomy collection commands above.

### register_dump

| Register Field | Anomalous Value | Hypothesis to Confirm |
|---|---|---|
| `GENSTS.event_int` | 1 | Unhandled interrupt pending |
| `SWERROR0.valid` | 1 | Active descriptor error — read SWERROR0–2 fully |
| `SWERROR0.err_code` | 0x06 | Page fault — check vtd_context |
| `SWERROR0.err_code` | 0x13 | Invalid request — check descriptor config |
| `ARBCFG.credit` | 0 | Arbiter starvation — check arbiter_state |
| `GENSTS.halt` | 1 | Device halted — check SWERROR + intcause |
| Any `opcap` all-zero | — | Capability register incorrect default |

### swerror_dump

- `SWERROR0.valid = 1` → a descriptor failure occurred; the remaining fields decode the failure
- `SWERROR0.overflow = 1` → multiple errors since last clear; only first captured
- `err_code = 0x00` + `valid = 0` → no error; look elsewhere (not a descriptor error)
- `SWERROR1.batch_index` non-zero → failure inside a batch descriptor; check batch element
- `SWERROR2.fault_address` → use this with vtd_context to trace the page fault path

### dmesg_kernel / driver_debug_flags

- `idxd: desc error` → driver caught a descriptor completion error; matches swerror_dump
- `iommu: DMAR: DRHD` fault → IOMMU translation failure; check vtd_context
- `idxd: wq X is not enabled` → WQ not configured; check wq_state
- `Failed to allocate MSI vector` → interrupt resource issue; check interrupt_state
- `timeout waiting for device` → driver gave up on response; check punit_mailbox + link_state
- Absence of `svDeviceInit` messages → device not enumerated; check platform_topology

### perfmon_counters

- `cntrdata_N = 0` when test ran → counter not started or wrong event selected
- `EV_TLB_MISS` high relative to `EV_TLB_HIT` → TLB pressure; check tlb_pressure
- `EV_CL_READ` high but `EV_CL_PROCESSED` low → pipeline stall between read and process
- Counters frozen mid-test (no increment after halt) → engine stopped; confirms hang

### pcie_aer

- `ppaercs` non-zero → correctable error (advisory); log category but usually not fatal
- `ppaerucsts` non-zero → uncorrectable error; likely caused or accompanied the failure
- `ppaerrootsts.aer_int` = 1 → AER interrupt triggered; cross-check with interrupt_state
- All-zero → PCIe layer is clean; root cause is above the link level

### vtd_context / vtd_fault

- Page fault `FAULT_REASON = 0x05` → present-bit clear in page table; software bug
- Page fault `FAULT_REASON = 0x06` → non-canonical address; descriptor has wrong address
- `IQ_STATUS.iq_overflow` → IOMMU invalidation queue full; indicates high TLB eviction rate
- `ATS_CTRL.ats_en = 0` → ATS disabled; if test needs ATS this is a config error

### failvect_trace

- Compare `Expected` vs `Observed` columns byte-by-byte; any mismatch = data corruption
- `TLP Type = MRd` → read data mismatch (stale data from cache or wrong address decode)
- `TLP Type = MWr` → write data mismatch (DMA wrote wrong data or to wrong location)
- `Base Address` + `Address offset` → compute full fault address; cross-check with memory_map

### test_framework_verbose_log / tool_specific_log

- Look for the LAST error line before `FAIL` or exit code — this is the proximate cause
- Timestamps let you correlate with kernel and hardware logs (align clocks if needed)
- `ret = -N` or `errno = N` in test output → map to errno.h; e.g. `-16 = EBUSY`, `-22 = EINVAL`
- Exit code `124` → test was killed by timeout wrapper; suggests hang not crash

---

## Taxonomy Extension Guide

To add a new domain (e.g., Memory, I/O, Compute):

1. Create a new `## Domain: <Name>` section
2. For each log category, provide:
   - **Category number and name** (sequential across all domains)
   - **Description**: What this log captures
   - **Collection Commands**: Exact PythonSV paths or shell commands
   - **When to collect**: Symptom conditions that warrant this log
3. Add interpretation patterns to the **Interpretation Guide** section above
4. Keep the structure consistent — the GENI MCP prompt parses this file
5. Categories should be actionable (specific commands, not vague guidance)

