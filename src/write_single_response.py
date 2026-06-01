"""
Write a single HSD triage response to responses.jsonl.
Usage: python write_single_response.py
Reads HSD_RESPONSE dict at bottom, appends to latest run's responses.jsonl.
"""
import json, sys
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent / "output"

def _resolve_run_dir():
    if len(sys.argv) > 1:
        return OUTPUT_DIR / sys.argv[1]
    candidates = sorted(
        [d for d in OUTPUT_DIR.glob("run_*") if (d / "triage_prompts.jsonl").exists()],
        reverse=True
    )
    if not candidates:
        raise FileNotFoundError("No run folder found")
    return candidates[0]

RUN_DIR = _resolve_run_dir()
PROMPTS_FILE = RUN_DIR / "triage_prompts.jsonl"
RESPONSES_FILE = RUN_DIR / "responses.jsonl"

# Load all prompts
ALL_PROMPTS = {}
with open(PROMPTS_FILE, encoding="utf-8") as f:
    for line in f:
        rec = json.loads(line.strip())
        ALL_PROMPTS[rec["hsd_id"]] = rec["parsed"]

# Load already-done IDs
done_ids = set()
if RESPONSES_FILE.exists():
    with open(RESPONSES_FILE, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                done_ids.add(json.loads(line.strip())["hsd_id"])

def write_response(hsd_id, phase2, phase3, phase4, phase5):
    """Append one response record."""
    if hsd_id in done_ids:
        print(f"  SKIP {hsd_id} (already written)")
        return False
    parsed = ALL_PROMPTS.get(hsd_id)
    if not parsed:
        print(f"  ERROR: {hsd_id} not in prompts")
        return False
    record = {
        "hsd_id": hsd_id,
        "parsed": parsed,
        "phase2_nga": phase2,
        "phase3_verify": phase3,
        "phase4_recommend": phase4,
        "phase5_validate": phase5,
    }
    with open(RESPONSES_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    done_ids.add(hsd_id)
    print(f"  WRITTEN {hsd_id} (total: {len(done_ids)})")
    return True

# ═══ HSD RESPONSES — append new entries below ═══════════════════════════════

# HSD 1: 14027624081 — DSA evntcap_5 incorrect default
write_response("14027624081",
    phase2={
        "testcase_name": "DSA register default validation (evntcap_5 vs GNR)",
        "testcase_command": "sv.socket0.imh0.acc.acc_0.dsa.evntcap_5.show() — manual DRM check",
        "testcase_parameters": "DMR A0, DSA, evntcap_5 register default comparison vs GNR bugeco 22020669707",
        "testcase_domain_focus": "DSA event capability register default verification — GNR to DMR delta validation"
    },
    phase3={
        "verified_problem_statement": "DSA evntcap_5 register on DMR A0 has incorrect default value 0x40F (matching GNR) instead of expected DMR value 0x3FC0F. The register reset state loads a hardwired default from RTL that was not updated from GNR to DMR.",
        "verified_root_cause": "Unupdated RTL default for evntcap_5 register — silicon definition cloned from GNR without updating default values for DMR. Static default value issue, not runtime.",
        "verified_fix": "Sighting rejected as not_a_defect. Default value may be updated in future stepping, or software does not depend on this default at runtime.",
        "architectural_element": "DSA perfmon discovery/enumeration (PERFEVNTCAP_REG), Event Capability Register evntcap_5 (events[27:0], RO/V)",
        "failure_registers": ["evntcap_5", "opcap0"],
        "adjacent_subsystems": ["hw.iax (also affected per component_affected)", "sw.driver (perfmon enumeration consumed by drivers)", "vt.accelerator (triage routing)"]
    },
    phase4={
        "tier1": [
            {"category": "register_dump", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.show()"], "reveals": "Full DSA register state including all defaults after reset", "relevance": "Determines if issue is isolated to evntcap_5 or systemic"},
            {"category": "event_capabilities", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.evntcap_0.show() through evntcap_5.show()", "sv.socket0.imh0.acc.acc_0.dsa.opcap0.show()"], "reveals": "Full family of event capability default values", "relevance": "Detects pattern of GNR defaults across multiple capability registers"}
        ],
        "tier2": [
            {"category": "swerror_dump", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.swerror0.show()"], "reveals": "Latent errors in DSA triggered by mis-init", "relevance": "Check if wrong capabilities cause downstream errors"},
            {"category": "dmesg_kernel", "commands": ["dmesg | grep -i 'dsa|idxd|evntcap'"], "reveals": "Kernel/driver perspective on wrong defaults", "relevance": "Driver may detect or mask wrong register values"}
        ],
        "tier3": [
            {"category": "perfmon_counters", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('cntr')"], "reveals": "Counter config affected by wrong event capabilities", "relevance": "Wrong evntcap may prevent certain events from being monitored"},
            {"category": "pcie_aer", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.ppaercs.show()"], "reveals": "PCIe errors during test flow", "relevance": "Rules out PCIe config issues"}
        ],
        "beyond_sme": [
            {"description": "Status Scope acc_stack with MAX_CAPTURE", "commands": ["status_scope.run(collectors=['namednodes'], analyzers=['dsa'], run_params={'ADAPTIVE': 0})"], "why": "Captures every DSA register for comprehensive delta analysis"},
            {"description": "BIOS/IFWI revision and DSA setup knobs", "commands": ["Capture full BIOS config"], "why": "Register defaults may be overridden by firmware"},
            {"description": "GNR register dump comparison", "commands": ["Same register reads on GNR platform"], "why": "Confirms DMR value is genuinely wrong vs GNR reference"}
        ]
    },
    phase5={
        "how_testcase_encounters_defect": "Direct — test reads evntcap_5 after reset and compares to expected DMR value, immediately detecting incorrect GNR default",
        "root_cause_domain": "accelerator (DSA perfmon)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "register_dump and event_capabilities (Tier 1) directly expose the incorrect default on first read after reset. 1-2 iterations to root cause.",
        "iteration_savings": "3"
    }
)

# HSD 4: 14027589950 — QAT pysces accel_verify_job failure on DSA path
write_response("14027589950",
    phase2={
        "testcase_name": "dmr-ap_vv_a0_acc_fdu1a_0017",
        "testcase_command": "N/A (no TestStepExecution/SubstitutedCommand in NGA query; pysces/supercollider based)",
        "testcase_parameters": "DMR X1 A0 VV, QAT pysces, FDU1A system, rerunIndex=4, station=gmzp301002s0099",
        "testcase_domain_focus": "QAT pysces accelerator validation on DMR X1 A0 — runs accel_verify_job on DSA path with 130 synced apps, exercises multi-accelerator resource coordination"
    },
    phase3={
        "verified_problem_statement": "QAT pysces test fails with 'No free test card found' followed by accel_verify_job(/sv/socket0/imh0/bus0/local-dsa-00) Verify failed. Docker and memicals processes do not release resources gracefully, requiring SIGTERM.",
        "verified_root_cause": "Test infrastructure resource exhaustion — all accelerator test cards occupied by previous hung/incomplete jobs. Pysces cannot allocate a free card for the 130-app synchronized test. DSA verify job fails because resource allocation is blocked before test can execute.",
        "verified_fix": "Fix resource cleanup in test orchestration — ensure Docker/memicals/pysces processes release test card resources. May also need system reset or manual resource cleanup between runs.",
        "architectural_element": "Pysces test card allocator, Docker/memicals container lifecycle, DSA accel_verify_job validation agent",
        "failure_registers": ["DSA SWERROR0 (check for pending errors)", "DSA WQ state (/sys/class/dsa/dsa0/wq*/state)"],
        "adjacent_subsystems": ["QAT/CPM", "Docker containers", "memicals process", "test card resource manager"]
    },
    phase4={
        "tier1": [
            {"category": "swerror_dump", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.swerror0.show()"], "reveals": "DSA software error state at failure time", "relevance": "Shows if DSA had pending errors blocking new jobs"},
            {"category": "wq_state", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.wqcfg_0.show()", "cat /sys/class/dsa/dsa0/wq*/state"], "reveals": "Work queue occupancy and configuration", "relevance": "Confirms if WQs are stuck occupied preventing new allocations"},
            {"category": "dmesg_kernel", "commands": ["dmesg | grep -i 'dsa|qat|idxd|accel|error'"], "reveals": "Kernel errors during accelerator operation", "relevance": "Shows driver-level resource allocation failures"},
            {"category": "descriptor_status", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('desc')"], "reveals": "Pending/completed descriptor state", "relevance": "Stuck descriptors explain resource exhaustion"}
        ],
        "tier2": [
            {"category": "register_dump", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.show()", "sv.socket0.imh0.acc.acc_0.cpm.show()"], "reveals": "Full DSA/CPM register state", "relevance": "Shows device health and configuration at failure"},
            {"category": "perfmon_counters", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('cntr')"], "reveals": "Queue utilization and throughput", "relevance": "Identifies resource bottleneck"},
            {"category": "platform_topology", "commands": ["sv.socket0.imh0.acc.show()"], "reveals": "Available accelerator instances", "relevance": "Confirms which devices are present and reachable"}
        ],
        "tier3": [
            {"category": "pcie_aer", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.ppaerucsts.show()"], "reveals": "PCIe errors on DSA path", "relevance": "PCIe errors could compound resource failures"},
            {"category": "interrupt_state", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.intcause.show()"], "reveals": "Pending interrupts", "relevance": "Missed completion interrupts cause resource leaks"}
        ],
        "beyond_sme": [
            {"description": "Pysces test card allocation log", "commands": ["Check pysces orchestration log for card allocation/release events"], "why": "Direct evidence of which cards are held and by which process"},
            {"description": "Docker/container status", "commands": ["docker ps -a", "check memicals process state"], "why": "Shows hung containers preventing resource release"},
            {"description": "Status Scope accelerator stack dump", "commands": ["status_scope.run(collectors=['namednodes'], analyzers=['acc_stack'])"], "why": "Comprehensive accelerator health check across DSA/IAA/CPM"}
        ]
    },
    phase5={
        "how_testcase_encounters_defect": "Direct — test requests test card allocation which fails due to resource exhaustion before test logic can execute",
        "root_cause_domain": "val.env (test infrastructure resource management)",
        "domain_relationship": "same-domain (val.env.content test failing due to val.env resource issue)",
        "recommendation_accuracy": "low — hardware/register logs won't surface infra resource exhaustion; need orchestration logs",
        "recommendation_rationale": "Root cause is test infrastructure (pysces card allocation, Docker cleanup) not silicon. Register dumps would show DSA is healthy. The key diagnostic is pysces orchestration and container lifecycle logs, which are beyond the standard taxonomy.",
        "iteration_savings": "1"
    }
)

# HSD 3: 14027597200 — Missing DSA/IAX SV nodes, svDeviceInit not supporting dsa_iax
write_response("14027597200",
    phase2={
        "testcase_name": "N/A (no NGA test run linked; SVOS driver initialization issue)",
        "testcase_command": "N/A (no rocket/atlas invocation; failure during SVOS module load)",
        "testcase_parameters": "DMR A0 VV, Kernel 6.19, SVOS Master, FDU1/FDU5 systems",
        "testcase_domain_focus": "SVOS driver initialization for DSA/IAX/CPM accelerators — validates device enumeration and SV node creation during module load"
    },
    phase3={
        "verified_problem_statement": "DSA, IAX, and CPM SV nodes are missing on FDU1 and FDU5 systems. SVOS driver init_module reports 'count of zero' meaning no enabled devices were discovered during enumeration. svDeviceInit fails for dsa_iax, cpm, and oobmsm-punit.",
        "verified_root_cause": "Devices not present in PCI config space due to fuse/BIOS configuration. CAPID registers (IMH CAPID3[15:0], CAPID5[3:0], CBB CAPID0[3:0]) control device availability. If devices are fused off or BIOS knobs disable accelerator enumeration, driver cannot find them.",
        "verified_fix": "Verify BIOS knobs enable DSA/IAX/CPM. Check CAPID/DEVEN registers for fuse-off state. If fused off, need IFWI changes to enable BIOSKnob for accelerators.",
        "architectural_element": "PCI device enumeration path, CAPID fuse registers, BIOS DEVEN register, SVOS device tree population",
        "failure_registers": ["IMH CAPID3[15:0]", "IMH CAPID5[3:0]", "CBB CAPID0[3:0]", "DEVEN register"],
        "adjacent_subsystems": ["BIOS/IFWI firmware", "PCI config space", "SVOS device tree", "oobmsm-punit"]
    },
    phase4={
        "tier1": [
            {"category": "dmesg_kernel", "commands": ["dmesg | grep -i 'dsa|iax|qat|cpm|idxd|svDeviceInit'"], "reveals": "Direct kernel/driver errors during init, module load failures", "relevance": "Shows exactly which devices failed and why count is zero"},
            {"category": "platform_topology", "commands": ["sv.sockets.show()", "sv.socket0.imh0.acc.show()", "sv.socket0.imh0.acc.acc_0.show()"], "reveals": "Which accelerator instances are present vs missing", "relevance": "Confirms device presence/absence at hardware level"},
            {"category": "register_dump", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.show()", "sv.socket0.imh0.acc.acc_0.iaa.show()"], "reveals": "DSA/IAA config register state", "relevance": "Shows if device is reachable or returns all-Fs (absent)"},
            {"category": "pcie_aer", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.ppaerucsts.show()"], "reveals": "PCIe errors during device access", "relevance": "UR errors indicate device is disabled/absent"}
        ],
        "tier2": [
            {"category": "firmware_log", "commands": ["BIOS serial log / TraceHub NPK output"], "reveals": "BIOS device enumeration and knob settings", "relevance": "Shows if BIOS enabled/disabled accelerators"},
            {"category": "punit_mailbox", "commands": ["sv.sockets.uncore.oobmsm_punit.show()"], "reveals": "Power unit state and device enable status", "relevance": "Confirms if punit disabled device via ForcePGPOK"},
            {"category": "memory_map", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('bar')", "cat /proc/iomem"], "reveals": "BAR allocation and MMIO regions", "relevance": "Missing BARs confirm device not enumerated"}
        ],
        "tier3": [
            {"category": "mce_log", "commands": ["mcelog --client", "dmesg | grep -i 'mce|machine check'"], "reveals": "Hardware errors that may correlate with missing devices", "relevance": "Uncorrectable errors could disable device"},
            {"category": "vtd_context", "commands": ["dmesg | grep -i 'iommu|dmar|vtd'"], "reveals": "IOMMU configuration that may block device visibility", "relevance": "VT-d misconfiguration can prevent device access"}
        ],
        "beyond_sme": [
            {"description": "CAPID/Fuse register dump", "commands": ["Read IMH CAPID3, CAPID5; CBB CAPID0 via PythonSV"], "why": "Directly shows if DSA/IAX/CPM are fused off on this part"},
            {"description": "lspci device enumeration", "commands": ["lspci -nn | grep '0b25'", "ls -l /sys/bus/dsa/devices/"], "why": "Confirms if Linux sees the PCI device at all"},
            {"description": "BIOS knob verification", "commands": ["Check BIOS setup: Socket Config > IIO > Accelerator Enable"], "why": "Most common root cause is BIOS knob not enabled for accelerators"}
        ]
    },
    phase5={
        "how_testcase_encounters_defect": "Direct — SVOS module load attempts to enumerate DSA/IAX devices and fails because devices are not present in PCI config space",
        "root_cause_domain": "platform.config (BIOS/fuse — device not enabled/enumerated)",
        "domain_relationship": "adjacent (test is sw.driver but root cause is platform config/fuse)",
        "recommendation_accuracy": "high — dmesg_kernel + platform_topology + CAPID register dump directly surface the root cause",
        "recommendation_rationale": "CAPID/DEVEN registers directly show fuse-off or BIOS-disable state. dmesg confirms driver sees zero devices. Known pattern from DMR A0 PO where IAA missing due to BIOS issue (pre-sighting 14025785454). Logs would immediately identify whether fuse or BIOS knob is the issue.",
        "iteration_savings": "3"
    }
)

# HSD 2: 14027599823 — QAT P2P CPM to CXL manual failure
write_response("14027599823",
    phase2={
        "testcase_name": "dmr-ap_vv_a0_acc_fdu4a_0058 (silicon_cpm_p2p_pcie)",
        "testcase_command": "rocket -M 120 --atlas \"--hw dram,cpmqat,vtd,pcietc -v cpmqat_focus_tests[i=p2p]\" -l 60 -L all",
        "testcase_parameters": "DMR A0 VV, QAT/CPM P2P, hw: dram+cpmqat+vtd+pcietc, goal: P2P_traffic_from_CPM_to_CXL_silicon, milestone: DMR_IMH2_A0_TI",
        "testcase_domain_focus": "CPM/QAT P2P PCIe traffic to CXL silicon — validates PCIe/CXL path for CPM workloads with dram, VTd, and pcietc subsystems"
    },
    phase3={
        "verified_problem_statement": "QAT P2P traffic from CPM to CXL silicon test was failed manually because the EV buffer size is insufficient to transfer the book file. This is a test environment/infrastructure limitation, not a silicon defect.",
        "verified_root_cause": "EV buffer size too small for book file transfer during CPM P2P test. The EV buffer (embedded SRAM, typically 8KB) used for pattern matching during P2P validation cannot accommodate the required data payload.",
        "verified_fix": "Test needs reconstruction with larger/different EV buffer configuration. No silicon fix required.",
        "architectural_element": "EV buffer (embedded SRAM for P2P traffic pattern validation), CPM/QAT P2P PCIe path to CXL",
        "failure_registers": ["tl_prt_trans_cnt (0x50700C)", "CPM telemetry status registers"],
        "adjacent_subsystems": ["CXL fabric", "PCIe root port", "VT-d IOMMU", "DRAM subsystem"]
    },
    phase4={
        "tier1": [
            {"category": "register_dump", "commands": ["sv.socket0.imh0.acc.acc_0.cpm.show()"], "reveals": "CPM/QAT hardware state and configuration", "relevance": "Detects misconfiguration in CPM P2P path"},
            {"category": "swerror_dump", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.swerror0.show()"], "reveals": "SW/FW error traces", "relevance": "Determines if firmware or testbench issue blocks traffic"},
            {"category": "pcie_aer", "commands": ["sv.socket0.imh0.acc.acc_0.cpm.ppaercs.show()", "sv.socket0.imh0.acc.acc_0.cpm.ppaerucsts.show()"], "reveals": "PCIe link-level errors between CPM and CXL", "relevance": "Checks for interconnect faults"},
            {"category": "dmesg_kernel", "commands": ["dmesg | grep -i 'qat|cpm|cxl|buffer'"], "reveals": "Kernel events, driver failures", "relevance": "Flags device enumeration or buffer allocation issues"}
        ],
        "tier2": [
            {"category": "memory_map", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('bar')"], "reveals": "Buffer placement and size limitations", "relevance": "Checks mismatch in DMA buffer sizing"},
            {"category": "perfmon_counters", "commands": ["sv.socket0.imh0.acc.acc_0.cpm.showsearch('cntr')"], "reveals": "Utilization, stalls, backpressure", "relevance": "Identifies resource pressure or bottlenecks"},
            {"category": "link_state", "commands": ["sv.socket0.imh0.acc.acc_0.cpm.showsearch('lnk')"], "reveals": "CXL/PCIe link state", "relevance": "Confirms link up and proper configuration"}
        ],
        "tier3": [
            {"category": "descriptor_status", "commands": ["sv.socket0.imh0.acc.acc_0.cpm.showsearch('desc')"], "reveals": "DMA descriptor transfer state", "relevance": "Pinpoints stuck or failed transactions"},
            {"category": "vtd_context", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('vtd')"], "reveals": "Address translation configuration", "relevance": "Exposes possible translation faults"}
        ],
        "beyond_sme": [
            {"description": "EV buffer configuration dump from Cambria test framework", "commands": ["Check EV buffer allocation size in test config"], "why": "Direct visibility into buffer sizing that caused the failure"},
            {"description": "CPM telemetry via PMT API", "commands": ["Read tl_prt_trans_cnt, tl_max_rd_lat registers"], "why": "Shows partial transaction counts indicating buffer overflow"}
        ]
    },
    phase5={
        "how_testcase_encounters_defect": "Direct — test initiates P2P transfer from CPM to CXL requiring book file, EV buffer size insufficient, causing transfer failure",
        "root_cause_domain": "val.env (test infrastructure — EV buffer sizing)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "Root cause is test environment (EV buffer config), not silicon. Register/PCIe logs would show no hardware error. memory_map and EV buffer config check most directly relevant. Recommended logs useful for ruling out HW issues but buffer config inspection is the real diagnostic.",
        "iteration_savings": "2"
    }
)

# HSD 5: 14027589949 — QAT PCIe AER Advisory Non Fatal Error
write_response("14027589949",
    phase2={
        "testcase_name": "dmr-ap_vv_a0_acc_DDU1_0060",
        "testcase_command": "N/A (TestStepExecution not available in NGA query)",
        "testcase_parameters": "DMR X1 A0 VV, QAT, station: ba00302ecos0024, rerunIndex: 1",
        "testcase_domain_focus": "DMR X1 A0 VV QAT/CPM accelerator validation — exercises QAT operations with PCIe AER error checking"
    },
    phase3={
        "verified_problem_statement": "QAT/CPM device generates PCIe AER Advisory Non Fatal Error during accelerator test. ppaercs register reports the error. Error occurs during QAT initialization/operation flow after ME firmware is already loaded.",
        "verified_root_cause": "PCIe protocol anomaly on QAT/CPM device — likely Poisoned TLP, unsupported request, or bad TLP at the PCIe interface. Advisory Non Fatal errors are recoverable but signal a line-level protocol issue. CPM DID 0x4948 with RID 0x0 suggests default/placeholder requester ID.",
        "verified_fix": "Investigate PCIe AER source — check ppaercs and ppaerucsts for specific error bits. Verify CPM RID assignment is correct. Check if Advisory Non Fatal is expected benign behavior or indicates real protocol violation.",
        "architectural_element": "PCIe AER capability structure, RASIP (Root-1) error aggregation, QAT/CPM PCIe endpoint",
        "failure_registers": ["ppaercs (correctable error status)", "ppaerucsts (uncorrectable error status)", "ppaerucsev (uncorrectable severity)"],
        "adjacent_subsystems": ["RASIP Root-1 error handler", "PCIe Root Port/RCEC", "IOMCA (IO Machine Check)", "OOBMSM telemetry"]
    },
    phase4={
        "tier1": [
            {"category": "pcie_aer", "commands": ["sv.socket0.imh0.acc.acc_0.cpm.ppaercs.show()", "sv.socket0.imh0.acc.acc_0.cpm.ppaerucsts.show()", "sv.socket0.imh0.acc.acc_0.cpm.ppaerucsev.show()"], "reveals": "PCIe AER error type, severity, source", "relevance": "Direct root cause for the reported Advisory Non Fatal Error"},
            {"category": "register_dump", "commands": ["sv.socket0.imh0.acc.acc_0.cpm.show()"], "reveals": "QAT/CPM device internal state and configuration", "relevance": "Shows device state at time of error"},
            {"category": "dmesg_kernel", "commands": ["dmesg | grep -i 'aer|pcie.*error|qat|cpm|idxd'"], "reveals": "Kernel-level device/driver error reporting", "relevance": "Timeline and context for AER event"},
            {"category": "swerror_dump", "commands": ["sv.socket0.imh0.acc.acc_0.cpm.showsearch('swerror')"], "reveals": "Software error registers with descriptor-level failure info", "relevance": "Cross-layer QAT driver/firmware error context"}
        ],
        "tier2": [
            {"category": "firmware_log", "commands": ["BMC SEL logs", "ME/PMC crashlogs"], "reveals": "Firmware involvement in recovery or reset", "relevance": "ME FW already loaded — check for firmware-side errors"},
            {"category": "link_state", "commands": ["sv.socket0.imh0.acc.acc_0.cpm.showsearch('lnk')", "lspci -vv -s <QAT BDF>"], "reveals": "PCIe link speed/width and training state", "relevance": "Transient link issues could trigger AER"},
            {"category": "vtd_context", "commands": ["sv.socket0.imh0.acc.acc_0.cpm.showsearch('vtd')"], "reveals": "IOMMU/VT-d translation state", "relevance": "Translation faults could cause unsupported requests"}
        ],
        "tier3": [
            {"category": "mce_log", "commands": ["mcelog --client", "dmesg | grep -i 'mce|machine check'"], "reveals": "Correlated hardware errors", "relevance": "Broad coverage of platform faults"},
            {"category": "perfmon_counters", "commands": ["sv.socket0.imh0.acc.acc_0.cpm.showsearch('cntr')"], "reveals": "QAT utilization and error rates", "relevance": "Identifies spikes or unusual patterns"}
        ],
        "beyond_sme": [
            {"description": "RASIP Root-1 error log dump", "commands": ["Check RASIP error aggregation registers for QAT/CPM sideband AER messages"], "why": "Shows full error escalation path from device to system"},
            {"description": "QAT telemetry via PMT", "commands": ["Read CPM telemetry counters"], "why": "Correlates AER with operational state"}
        ]
    },
    phase5={
        "how_testcase_encounters_defect": "Direct — QAT test exercises CPM/QAT device operations which trigger PCIe AER Advisory Non Fatal Error during normal accelerator validation flow",
        "root_cause_domain": "hw.pcie (PCIe protocol anomaly on QAT/CPM endpoint)",
        "domain_relationship": "same-domain (QAT test directly exercises the QAT/CPM PCIe path where error occurs)",
        "recommendation_accuracy": "high — pcie_aer registers directly capture the error type and source; register_dump shows device state",
        "recommendation_rationale": "AER registers (ppaercs, ppaerucsts) directly identify the error type. dmesg provides timeline. register_dump shows configuration state. These are the standard diagnostic path for PCIe AER errors and would immediately surface whether this is a real protocol violation or expected benign behavior.",
        "iteration_savings": "2"
    }
)

print(f"\nDone. Responses file: {RESPONSES_FILE}")
if RESPONSES_FILE.exists():
    with open(RESPONSES_FILE, encoding="utf-8") as f:
        count = sum(1 for line in f if line.strip())
    print(f"Total responses: {count}")
