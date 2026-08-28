"""
Append triage responses for a batch of HSDs to responses.jsonl.

Usage:
  python write_batch_responses.py                    # auto-detects latest run folder
  python write_batch_responses.py run_20260501_213643  # explicit run folder name

To add new batches:
  1. Append new entries to the BATCH dict below (see existing entries for format)
  2. Run the script — already-written HSDs are automatically skipped (idempotent)
  3. Update RUN_FOLDER_NAME below if targeting a specific run (or leave None for auto)
"""
import json, sys
from pathlib import Path

# Set to a specific folder name (e.g. "run_20260501_213643") to override auto-detect.
# Leave as None to always use the latest run_* folder.
RUN_FOLDER_NAME = None

OUTPUT_DIR = Path(__file__).parent / "output"

def _resolve_run_dir():
    if RUN_FOLDER_NAME:
        return OUTPUT_DIR / RUN_FOLDER_NAME
    # Accept explicit arg: `python write_batch_responses.py run_YYYYMMDD_HHMMSS`
    if len(sys.argv) > 1:
        return OUTPUT_DIR / sys.argv[1]
    # Auto-detect: latest run_* folder that contains triage_prompts.jsonl
    candidates = sorted(
        [d for d in OUTPUT_DIR.glob("run_*") if (d / "triage_prompts.jsonl").exists()],
        reverse=True
    )
    if not candidates:
        raise FileNotFoundError(f"No run_* folder with triage_prompts.jsonl found in {OUTPUT_DIR}")
    return candidates[0]

RUN_DIR = _resolve_run_dir()
PROMPTS_FILE = RUN_DIR / "triage_prompts.jsonl"
RESPONSES_FILE = RUN_DIR / "responses.jsonl"
print(f"Run folder: {RUN_DIR}")

# Load all prompts
records = []
with open(PROMPTS_FILE, encoding="utf-8") as f:
    for line in f:
        records.append(json.loads(line.strip()))

# Load already processed HSD IDs
done_ids = set()
if RESPONSES_FILE.exists():
    with open(RESPONSES_FILE, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                done_ids.add(json.loads(line.strip())["hsd_id"])

print(f"Already processed: {len(done_ids)} HSDs")
print(f"Total records: {len(records)}")

# ── BATCH RESPONSES ──────────────────────────────────────────────────────────
# Each entry: hsd_id → responses dict (phase2_nga, phase3_verify, phase4_recommend, phase5_validate)
# Format matches pilot batch responses in responses.jsonl

BATCH = {}

# ── Record 6: 14027589429 — QAT MCE/Target Hang ──────────────────────────────
BATCH["14027589429"] = {
    "phase2_nga": {
        "testcase_name": "silicon_ssh_qat_mce_hang (DMR VV)",
        "testcase_command": "NGA UUID f9ce8705-72d9-4930-9794-7c4bf7bec922",
        "testcase_parameters": "QAT/CPM on DMR X1 A0, SVOS validation",
        "testcase_domain_focus": "QAT accelerator Machine Check Error and target hang detection"
    },
    "phase3_verify": {
        "verified_problem_statement": "QAT/CPM device on DMR X1 A0 triggers Machine Check Error with Target Hang Communicator event. MCE originates from uncore QAT IP and is delivered by CPU, resulting in system hang.",
        "verified_root_cause": "Hardware deadlock, credit starvation, or firmware/driver error preventing forward progress on QAT accelerator. Possible causes: PCIe credit starvation leading to communicator hang, MCE originating from uncore IPs during CPM operation. CPU logs 3-strike machine check. Could also involve Pcode machine check associated with QAT power state transition.",
        "verified_fix": "Root cause unknown (HSD status: complete). Investigate CPM ring buffer state, PCIe credit table, and MCA bank registers to identify exact hang source.",
        "architectural_element": "QAT/CPM uncore IP, PCIe credit arbiter, MCA uncore bank",
        "failure_registers": ["ppaercs", "ppaerucsts", "MCA_STATUS", "MCA_ADDR", "CPM status regs", "PCIe LTSSM"],
        "adjacent_subsystems": ["PCIe root port", "IMH interconnect", "Punit power controller", "MCTP communicator"]
    },
    "phase4_recommend": {
        "tier1": [
            {"category": "mce_log", "commands": ["mcelog --client", "dmesg | grep -i 'mce\\|machine check\\|hardware error'", "sv.sockets.uncore.showsearch('mca')"], "reveals": "Exact MCA bank, status, address registers showing which uncore IP fired the MCE", "relevance": "Direct cause of the Machine Check Error with Target Hang"},
            {"category": "register_dump", "commands": ["sv.socket0.imh0.acc.acc_0.cpm.show()"], "reveals": "Full QAT/CPM register state at hang time", "relevance": "Baseline CPM state to identify which phase of operation hung"},
            {"category": "pcie_aer", "commands": ["sv.socket0.imh0.acc.acc_0.cpm.ppaercs.show()", "sv.socket0.imh0.acc.acc_0.cpm.ppaerucsts.show()", "sv.socket0.imh0.acc.acc_0.cpm.ppaerucsev.show()"], "reveals": "PCIe error type associated with the hang", "relevance": "Target Hang Communicator events often correlate with PCIe uncorrectable errors"},
            {"category": "firmware_log", "commands": ["sv.socket0.imh0.acc.acc_0.cpm.showsearch('fw')", "sv.socket0.imh0.acc.acc_0.cpm.showsearch('me')"], "reveals": "QAT ME firmware state and load completion", "relevance": "FW handoff issues can cause MCE if ME enters error state"},
            {"category": "dmesg_kernel", "commands": ["dmesg | grep -i 'qat\\|cpm\\|mce\\|machine check\\|AER'"], "reveals": "Kernel perspective on QAT MCE and target hang", "relevance": "Shows driver-level error detection sequence"}
        ],
        "tier2": [
            {"category": "perfmon_counters", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('cntr')"], "reveals": "PCIe credit and latency counters", "relevance": "Credit starvation shows as stalled counters before hang"},
            {"category": "link_state", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('lnk')", "sv.socket0.imh0.acc.acc_0.dsa.showsearch('devctl')"], "reveals": "PCIe link state and device control settings", "relevance": "Link degradation or timeout could precede MCE"},
            {"category": "punit_mailbox", "commands": ["sv.socket0.imh0.showsearch('punit')", "sv.sockets.uncore.oobmsm_punit.show()"], "reveals": "Punit state for QAT power management", "relevance": "Punit power state issues can generate machine checks"}
        ],
        "tier3": [
            {"category": "interrupt_state", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('msix')"], "reveals": "MSI-X vector configuration", "relevance": "MCE signaling path through interrupt vectors"},
            {"category": "platform_topology", "commands": ["sv.sockets.uncore.showsearch('mce')"], "reveals": "Platform MCA bank topology", "relevance": "Identifies which uncore bank reported the error"}
        ],
        "beyond_sme": [
            {"description": "PCIe credit table dump (status_scope plugin)", "commands": ["Use status_scope PCIe plugin to dump credit counters"], "why": "Credit exhaustion is invisible to standard register dumps but directly visible in credit table"},
            {"description": "MCTP packet counters", "commands": ["Read MCTP count registers for packet discrepancies"], "why": "Target Hang Communicator MCE often correlates with MCTP packet mismatch"},
            {"description": "S3M decoded FW messages", "commands": ["Check S3M for QAT interrupt handling state"], "why": "FW interrupt handling issues not visible in standard registers may cause target hang"}
        ]
    },
    "phase5_validate": {
        "how_testcase_encounters_defect": "direct — QAT validation test exercises QAT operations that trigger the MCE hang condition",
        "root_cause_domain": "QAT/CPM hardware (PCIe credit/MCE)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high — mce_log + pcie_aer + register_dump would identify the MCA bank, error source, and PCIe error type in first pass",
        "recommendation_rationale": "mce_log directly reads MCA bank registers that identify the exact IP that fired the MCE. pcie_aer shows correlated PCIe errors. firmware_log shows ME state. Combined Tier 1 gives complete first-pass picture. MCTP counters are the beyond-SME key for Target Hang Communicator specifically.",
        "iteration_savings": "3"
    }
}

# ── Record 7: 14027549787 — DSA Reduce hang (SysDebug FWD, cloned from 14027419708) ──
BATCH["14027549787"] = {
    "phase2_nga": {
        "testcase_name": "DSA Reduce / Reduce with Dualcast operation (large transfer)",
        "testcase_command": "not available (SysDebug forward of 14027419708)",
        "testcase_parameters": "Transfer size >448KB, 16 concurrent Reduce with dual cast ops",
        "testcase_domain_focus": "DSA data streaming — Reduce and Reduce with Dualcast operations accessing multi-source translation queues"
    },
    "phase3_verify": {
        "verified_problem_statement": "DSA hangs when issuing large Reduce or Reduce with Dualcast operations (>448KB). Arbiter deadlock in translation request queue causes total stall — no completion record generated.",
        "verified_root_cause": "Temporal starvation in translation request arbitration between Src1, Src2, Dst1, Dst2 DMA streams. Arbiter slightly favors Src1; combined Src1+Src2 translation queue limited to 112 entries (448KB). Src1 can occupy all 112 slots, starving Src2. Since Reduce requires both Src1 AND Src2 to proceed, deadlock results — Src2 waits for Src1 to free a slot, Src1 never frees because it needs Src2 for forward progress.",
        "verified_fix": "Software workaround: limit Reduce/ReduceDC transfer size to ≤448KB for trusted software; clear WQ OPCFG bits 25+26 to disable Reduce ops for untrusted WQs; or set WQ Max Transfer Size to 18 (256KB). Silicon fix required for future projects: Src1/Src2 must fill translation queue in alternating fashion.",
        "architectural_element": "DSA internal translation request arbiter (Src1/Src2/Dst1/Dst2 streams), per-stream translation queue (combined 112-entry limit)",
        "failure_registers": ["arbiter state registers via showsearch('arb')", "showsearch('src')", "showsearch('queue')", "showsearch('credit')", "wqcfg OPCFG bits 25:26"],
        "adjacent_subsystems": ["VT-d/IOMMU translation queues", "DSA DMA engine", "PCIe link (MRRS/TBTRE)"]
    },
    "phase4_recommend": {
        "tier1": [
            {"category": "arbiter_state", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('arb')", "sv.socket0.imh0.acc.acc_0.dsa.showsearch('src')", "sv.socket0.imh0.acc.acc_0.dsa.showsearch('queue')", "sv.socket0.imh0.acc.acc_0.dsa.showsearch('credit')"], "reveals": "Translation request queue occupancy per DMA stream (Src1, Src2, Dst1, Dst2)", "relevance": "Directly shows whether Src1 holds all 112 entries, confirming arbiter deadlock"},
            {"category": "link_state", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('mrrs')", "sv.socket0.imh0.acc.acc_0.dsa.showsearch('tbtr')", "sv.socket0.imh0.acc.acc_0.dsa.showsearch('devctl')"], "reveals": "MRRS and Ten-Bit Tag settings affecting hang reproducibility", "relevance": "MRRS=0 (128B) and TBTRE=0 makes deadlock ~100% reproducible with single descriptor"},
            {"category": "wq_state", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.wqcfg_0.show()", "sv.socket0.imh0.acc.acc_0.dsa.wqcfg_1.show()", "sv.socket0.imh0.acc.acc_0.dsa.wqcfg_2.show()", "sv.socket0.imh0.acc.acc_0.dsa.wqcfg_3.show()"], "reveals": "WQ OPCFG bits 25:26 (Reduce enable) and WQ Max Transfer Size", "relevance": "WQ configuration determines whether Reduce ops are allowed and at what size"},
            {"category": "perfmon_counters", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('cntr')", "sv.socket0.imh0.acc.acc_0.dsa.cntrdata_0.show()"], "reveals": "Data flow counters — reads processed vs pending", "relevance": "Shows stalled src1/src2 read processing confirming translation queue exhaustion"}
        ],
        "tier2": [
            {"category": "descriptor_status", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('desc')"], "reveals": "In-flight descriptor state and completion status", "relevance": "No completion record confirms total DSA stall"},
            {"category": "vtd_context", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('pasid')", "sv.socket0.imh0.acc.acc_0.dsa.showsearch('prq')"], "reveals": "PASID and page request queue state", "relevance": "Translation request queue feeds through VT-d; stall may show in PRQ depth"},
            {"category": "register_dump", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.show()"], "reveals": "Full DSA register state at hang time", "relevance": "Baseline state to confirm device is hung (no activity)"}
        ],
        "tier3": [
            {"category": "interrupt_state", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.intcause.show()"], "reveals": "Pending interrupt cause", "relevance": "Hung state may leave pending interrupt"},
            {"category": "pcie_aer", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.ppaerucsts.show()"], "reveals": "PCIe uncorrectable errors from hang", "relevance": "Timeout on completion may escalate to PCIe error"}
        ],
        "beyond_sme": [
            {"description": "Per-stream translation queue depth snapshot", "commands": ["Internal DSA FIFO depth readout for Src1/Src2 translation queues"], "why": "The root cause is fundamentally about queue occupancy imbalance — direct per-stream counter would immediately confirm which stream is starved"},
            {"description": "Reduce operation descriptor replay with MRRS=0 and TBTRE=0", "commands": ["Set devctl.mrrs=0 and devctl.tbtre=0, then issue single Reduce >448KB"], "why": "Makes deadlock 100% reproducible to collect live hang state"}
        ]
    },
    "phase5_validate": {
        "how_testcase_encounters_defect": "direct — Test explicitly issues large Reduce operations that exceed the 448KB arbiter limit, directly triggering the deadlock",
        "root_cause_domain": "DSA internal translation request arbiter",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high — arbiter_state + link_state(MRRS/TBTRE) + wq_state would confirm deadlock condition and reproducibility factor in first pass",
        "recommendation_rationale": "arbiter_state showsearch('src') and showsearch('queue') would show Src1 holding all 112 slots. link_state MRRS/TBTRE shows the configuration making it reproducible. wq_state shows whether SW workaround is applied. Complete root cause identification in single debug pass.",
        "iteration_savings": "4"
    }
}

# ── Record 8: 14027460514 — DSA SG_CXL2CXL FAILVECT ─────────────────────────
BATCH["14027460514"] = {
    "phase2_nga": {
        "testcase_name": "SG_CXL2CXL scatter-gather DMA to CXL memory",
        "testcase_command": "rocket --cfgs --atlas \"--hw dram,dsa,pcietc -v dsa_focus_tests[i=[SG_CXL2CXL,sgl_no_props],debug=[dsa_1,wq_1]]\"",
        "testcase_parameters": "SG_CXL2CXL with sgl_no_props, debug=[dsa_1,wq_1], HW: dram+dsa+pcietc",
        "testcase_domain_focus": "DSA scatter-gather (SGL) DMA operations targeting CXL memory (LOCALCXL00_UC_MEDIUM)"
    },
    "phase3_verify": {
        "verified_problem_statement": "DSA scatter-gather (SG_CXL2CXL) produces FAILVECT data mismatch on ARDEN_MEM_SOCKET0_BUS1_DEV2_FUNC0_LOCALCXL00_UC_MEDIUM at base address 0x1210c0800000. 1 error detected in the target range.",
        "verified_root_cause": "Data corruption on CXL memory target during DSA SGL DMA write. Root cause involves CXL HDM decoder misconfiguration, BI snoop filter coherency mismatch, or address aliasing in the hierarchical memory map. CXL HDM-DB requires BIEnable and correct decoder type bits [13:12]=10; if mismatched, stale host cachelines are not invalidated causing mismatch. Status: rejected (val.env.tool component).",
        "verified_fix": "Check HDM decoder configuration for LOCALCXL00 — verify BIEnable, volatile/non-volatile settings, and decoder type. Confirm CXL HDM snoop filter state. Verify BIOS/OS correctly programs HDM decoders. Status: rejected, likely test environment/tool issue.",
        "architectural_element": "CXL HDM decoder, BI snoop filter, DSA DMA engine, CXL coherency protocol",
        "failure_registers": ["CXL HDM decoder regs (BIEnable, decoder type [13:12])", "snoop filter state", "DSA descriptor completion status", "PCIe AER (poison TLP)", "HAMVF NXM handling"],
        "adjacent_subsystems": ["CXL root port", "CXL HDM snoop filter", "host cache coherency agent", "VT-d/IOMMU for SGL"]
    },
    "phase4_recommend": {
        "tier1": [
            {"category": "failvect_trace", "commands": ["Look for <FAILVECT> in test output — ARDEN_MEM_SOCKET0_BUS1_DEV2_FUNC0_LOCALCXL00_UC_MEDIUM", "Address/Expected/Observed/TLP Type comparison"], "reveals": "Exact address offset, expected vs observed data, and TLP type of the mismatch", "relevance": "Already present — shows exactly which DMA write produced wrong data"},
            {"category": "memory_map", "commands": ["sv.socket0.imh0.bus1.pciExpress2.cxl-01.show()", "sv.socket0.imh0.bus1.pciExpress2.cxl-01.global.show()", "sv.socket0.imh0.bus1.pciExpress2.cxl-01.showsearch('hdm')"], "reveals": "CXL HDM decoder state including BIEnable, decoder type, and address range", "relevance": "HDM misconfiguration is the primary silicon cause of CXL DMA data corruption"},
            {"category": "coherency_state", "commands": ["sv.socket0.imh0.bus1.pciExpress2.cxl-01.showsearch('coh')", "sv.socket0.imh0.bus1.pciExpress2.cxl-01.showsearch('bias')", "sv.sockets.uncore.chas.showsearch('snoop')"], "reveals": "CXL bias mode and host snoop filter state", "relevance": "Stale host cachelines not invalidated due to BI misconfiguration causes read-back data mismatch"},
            {"category": "register_dump", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.show()", "sv.socket0.imh0.acc.acc_0.dsa.swerror0.show()"], "reveals": "DSA operation completion and error state", "relevance": "Shows whether DSA reported success while data was wrong (coherency issue) or flagged an error"}
        ],
        "tier2": [
            {"category": "descriptor_status", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('desc')"], "reveals": "SGL descriptor chain state and completion codes", "relevance": "Shows if scatter-gather list was processed correctly"},
            {"category": "vtd_context", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('ats')", "sv.socket0.imh0.acc.acc_0.dsa.showsearch('pasid')"], "reveals": "ATS translation results for CXL memory addresses", "relevance": "Wrong ATS translation could route DMA to wrong physical address"},
            {"category": "pcie_aer", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.ppaerucsts.show()"], "reveals": "PCIe uncorrectable errors including poison TLP detection", "relevance": "CXL data corruption may generate poison TLP error"}
        ],
        "tier3": [
            {"category": "link_state", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('lnk')"], "reveals": "CXL link health during transfer", "relevance": "Link errors could cause data corruption"},
            {"category": "perfmon_counters", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('cntr')"], "reveals": "DMA bytes read/written and error events", "relevance": "Partial transfer with wrong count could explain single-error FAILVECT"},
            {"category": "wq_state", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.wqcfg_0.show()"], "reveals": "WQ PASID and group assignment for SGL test", "relevance": "Wrong PASID could route to different address space"}
        ],
        "beyond_sme": [
            {"description": "CXL HDM decoder BIEnable and decoder type validation", "commands": ["sv.socket0.imh0.bus1.pciExpress2.cxl-01.showsearch('hdm')", "Check HDM decoder bits [13:12] for HDM-DB (0b10) vs HDM-D (0b00)"], "why": "BIEnable=0 or wrong decoder type means host cache not snooped — primary CXL coherency corruption mechanism"},
            {"description": "CDAT (Coherent Device Attribute Table) structure", "commands": ["Check CDAT DSIS structure for volatile/non-volatile classification of LOCALCXL00_UC_MEDIUM"], "why": "CDAT misconfiguration causes OS to classify CXL memory incorrectly, affecting coherency protocol selection"},
            {"description": "NDR/DRS response log from CXL endpoint", "commands": ["Check CXL endpoint NDR/DRS protocol logs"], "why": "Protocol-level response mismatch is invisible to host-side registers but reveals the exact coherency failure point"}
        ]
    },
    "phase5_validate": {
        "how_testcase_encounters_defect": "direct — Test explicitly exercises DSA SGL DMA to CXL memory (SG_CXL2CXL), directly triggering the CXL path that produces the mismatch",
        "root_cause_domain": "CXL HDM decoder / coherency configuration",
        "domain_relationship": "adjacent",
        "recommendation_accuracy": "high — failvect_trace + memory_map(HDM decoder) + coherency_state would identify CXL configuration mismatch causing DMA corruption in first pass",
        "recommendation_rationale": "failvect_trace already present showing mismatch. memory_map HDM decoder dump + coherency_state bias/snoop shows whether BIEnable is correctly set. These three together either confirm CXL HDM misconfiguration (silicon path) or redirect to test environment (rejected HSD).",
        "iteration_savings": "2"
    }
}

# ── Record 9: 14027421268 — QAT Auth job timeout ──────────────────────────────
BATCH["14027421268"] = {
    "phase2_nga": {
        "testcase_name": "silicon_ssh_qat_alldesc — CPM variant DMR all-descriptor test",
        "testcase_command": "rocket -M @{TestLine.TestStageEstimatedTime} --atlas \"--hw dram,cpm -v cpm_variant_dmr[minutes=X,jobs=10,test_mode=all_desc]\"",
        "testcase_parameters": "HW: dram+cpm, 10 concurrent jobs, test_mode=all_desc, NGA UUIDs: 214a8b36, 7070cc59",
        "testcase_domain_focus": "QAT/CPM authentication descriptor validation — all descriptor types including auth/crypto under concurrent load"
    },
    "phase3_verify": {
        "verified_problem_statement": "QAT authentication job timed out during all_desc test with 10 concurrent jobs. Auth job never received completion response within the expected timeout window, causing test failure.",
        "verified_root_cause": "QAT auth job timeout with 10 concurrent jobs suggests crypto pipeline stall, ring buffer overflow, or ME microengine resource exhaustion. The CPM ring buffer may reach capacity under 10 concurrent jobs causing new submissions to timeout. Alternatively, ME firmware may stall on auth descriptor processing. HSD status: complete.",
        "verified_fix": "Root cause resolved (status: complete). Likely a firmware update or test parameter adjustment (reducing concurrency or timeout extension).",
        "architectural_element": "QAT/CPM ring buffer, ME (MicroEngine) crypto pipeline, auth descriptor queue",
        "failure_registers": ["CPM ring buffer occupancy registers", "sv.socket0.imh0.acc.acc_0.cpm.showsearch('me')", "sv.socket0.imh0.acc.acc_0.cpm.showsearch('fw')", "ppaercs", "ppaerucsts"],
        "adjacent_subsystems": ["QAT firmware MEs", "PCIe DMA for ring buffer", "punit power state", "VT-d for PASID"]
    },
    "phase4_recommend": {
        "tier1": [
            {"category": "firmware_log", "commands": ["sv.socket0.imh0.acc.acc_0.cpm.showsearch('fw')", "sv.socket0.imh0.acc.acc_0.cpm.showsearch('me')", "grep 'combinedTxpMgr\\|srvActor\\|srvDirector' <QAT test output>"], "reveals": "ME firmware state, ring buffer processing status, and auth service state", "relevance": "Auth timeout most commonly caused by ME stall or ring buffer overflow — FW logs show which ME is stalled"},
            {"category": "register_dump", "commands": ["sv.socket0.imh0.acc.acc_0.cpm.show()"], "reveals": "Full QAT/CPM register state at timeout", "relevance": "Baseline state to determine if device is still operational or fully stalled"},
            {"category": "swerror_dump", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.swerror0.show()", "sv.socket0.imh0.acc.acc_0.dsa.swerror1.show()"], "reveals": "Descriptor-level error codes if auth job was rejected before timeout", "relevance": "Auth failure may leave error code in SWERROR registers even on CPM"},
            {"category": "dmesg_kernel", "commands": ["dmesg | grep -i 'qat\\|cpm\\|timeout\\|auth'"], "reveals": "Kernel-level QAT timeout messages and driver error codes", "relevance": "QAT driver typically logs ring pair timeout with specific ring and ME ID"}
        ],
        "tier2": [
            {"category": "perfmon_counters", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('cntr')"], "reveals": "In-flight request counts and processing stalls", "relevance": "10 concurrent jobs may exhaust ring pairs — counters show parallelism and stall conditions"},
            {"category": "pcie_aer", "commands": ["sv.socket0.imh0.acc.acc_0.cpm.ppaercs.show()", "sv.socket0.imh0.acc.acc_0.cpm.ppaerucsts.show()"], "reveals": "PCIe errors accompanying the timeout", "relevance": "Completion timeout may escalate to PCIe CTO (Completion Timeout) AER error"},
            {"category": "wq_state", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.wqcfg_0.show()"], "reveals": "Work queue occupancy under 10-job load", "relevance": "WQ overflow could cause auth descriptor rejection before timeout"}
        ],
        "tier3": [
            {"category": "punit_mailbox", "commands": ["sv.socket0.imh0.showsearch('punit')"], "reveals": "Power state transitions during QAT operation", "relevance": "Power gating during low-power state could interrupt ME operation"},
            {"category": "vtd_context", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('pasid')"], "reveals": "PASID assignment for QAT ring buffers", "relevance": "PASID configuration affects address space for 10 concurrent job processes"},
            {"category": "link_state", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('lnk')"], "reveals": "PCIe link state", "relevance": "Link degradation under load could cause completion timeouts"}
        ],
        "beyond_sme": [
            {"description": "QAT ring pair state dump (ring head/tail pointers)", "commands": ["Check ring pair head/tail pointers for stalled rings"], "why": "Ring buffer overflow is invisible to standard AER/SWERROR registers — ring head=tail on a full ring confirms the timeout root cause"},
            {"description": "ME microengine per-thread utilization", "commands": ["Query ME thread utilization registers for 10 concurrent auth operations"], "why": "Thread exhaustion on auth ME (typically ME_0/1/2 for auth service) would show 100% utilization with queued requests unable to start"},
            {"description": "QAT crypto pipeline completion queue depth", "commands": ["Check CPM completion ring empty indicator"], "why": "If completion ring is full, new completions cannot be written and in-flight jobs timeout waiting for empty slot"}
        ]
    },
    "phase5_validate": {
        "how_testcase_encounters_defect": "stress — 10 concurrent auth jobs creates load conditions that exhaust either ring pairs or ME threads, triggering timeout",
        "root_cause_domain": "QAT/CPM ring buffer / ME crypto pipeline",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high — firmware_log(ME state) + register_dump(CPM) + dmesg_kernel(driver timeout log) would identify which ring pair or ME stalled in first pass",
        "recommendation_rationale": "QAT driver logs ring pair timeout with ME ID and ring index in dmesg. firmware_log shows ME operational state. Combined with register_dump showing CPM is alive but stalled, root cause (ring overflow vs ME stall vs FW bug) is identifiable without iterative hardware debugging.",
        "iteration_savings": "2"
    }
}

# ── Record 10: 14027419708 — DSA Reduce hang (original, full root cause) ─────
BATCH["14027419708"] = {
    "phase2_nga": {
        "testcase_name": "DSA Reduce / Reduce with Dualcast (large transfer, single socket)",
        "testcase_command": "not available (platform team direct silicon test)",
        "testcase_parameters": "Transfer size >448KB, 16 concurrent Reduce with dual cast ops, MRRS=0, TBTRE=0 for high reproducibility",
        "testcase_domain_focus": "DSA data streaming — Reduce and Reduce with Dualcast operations, multi-source translation arbitration"
    },
    "phase3_verify": {
        "verified_problem_statement": "DSA hangs completely when issuing large Reduce or Reduce with Dualcast operations. No activity and no completion record. Default MRRS/TBTRE requires 16+ concurrent ops. MRRS=0+TBTRE=0 causes hang ~100% with single descriptor >448KB.",
        "verified_root_cause": "Silicon bug: Temporal starvation in translation request arbitration (hw.bug, hw.dsa, dmr-a0). Round-robin arbiter manages translation requests for Src1/Src2/Dst1/Dst2 DMA streams. Combined Src1+Src2 queue limited to 112 entries (112×4096B = 448KB). Arbiter slightly favors Src1 — pushing rate imbalanced but popping rate 50/50. Src1 can fill all 112 slots, permanently blocking Src2. Since Reduce requires both Src1 AND Src2 to proceed, deadlock results. Errata required, PRQ gating yes, silicon fix in future project, SW WA via transfer size limiting.",
        "verified_fix": "SW WA: limit Reduce/ReduceDC to ≤448KB for trusted SW; clear WQ OPCFG bits 25+26 to disable Reduce for untrusted WQs; or set WQ Max Transfer Size=18 (256KB). Silicon root fix: alternate Src1/Src2 filling in alternating fashion. Errata published, PRQ gating, not ECO-able.",
        "architectural_element": "DSA internal translation request arbiter — Src1/Src2/Dst1/Dst2 per-stream queues with combined 112-entry limit",
        "failure_registers": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('arb')", "showsearch('src')", "showsearch('queue')", "showsearch('credit')", "WQ OPCFG bits 25:26", "devctl.mrrs", "devctl.tbtre"],
        "adjacent_subsystems": ["VT-d IOTLB (translation queue feeds)", "DSA DMA engine (Reduce opcode)", "PCIe link (MRRS/TBTRE affect queue fill rate)"]
    },
    "phase4_recommend": {
        "tier1": [
            {"category": "arbiter_state", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('arb')", "sv.socket0.imh0.acc.acc_0.dsa.showsearch('src')", "sv.socket0.imh0.acc.acc_0.dsa.showsearch('outstanding')", "sv.socket0.imh0.acc.acc_0.dsa.showsearch('credit')"], "reveals": "Per-stream translation queue occupancy — Src1 at 112, Src2 at 0 confirms deadlock", "relevance": "The only register that directly shows the arbiter deadlock: Src1 holding all entries"},
            {"category": "link_state", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('mrrs')", "sv.socket0.imh0.acc.acc_0.dsa.showsearch('tbtr')", "sv.socket0.imh0.acc.acc_0.dsa.showsearch('devctl')"], "reveals": "MRRS and TBTRE settings — lower values increase per-request slot usage making deadlock more likely", "relevance": "MRRS=0 makes every cache line a separate translation request consuming slots faster"},
            {"category": "wq_state", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.wqcfg_0.show()", "sv.socket0.imh0.acc.acc_0.dsa.wqcfg_1.show()"], "reveals": "WQ OPCFG bits 25:26 (Reduce enable) and Maximum Transfer Size field", "relevance": "Shows whether SW WA is applied (bits 25:26 cleared) or Reduce is still enabled"}
        ],
        "tier2": [
            {"category": "perfmon_counters", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.cntrdata_0.show()", "sv.socket0.imh0.acc.acc_0.dsa.cntrdata_1.show()"], "reveals": "Zero throughput on stalled counters confirms DSA is fully hung", "relevance": "EV_CL_PROCESSED=0 while EV_CL_READ>0 confirms data ingested but no processing"},
            {"category": "descriptor_status", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('desc')"], "reveals": "In-flight Reduce descriptor state and completion record", "relevance": "no completion record (zero/empty) directly matches reported symptom"},
            {"category": "vtd_context", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('pasid')", "sv.socket0.imh0.acc.acc_0.dsa.showsearch('prq')"], "reveals": "PASID and page request service state", "relevance": "Outstanding page requests may back up if Translation Queue is full"}
        ],
        "tier3": [
            {"category": "register_dump", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.show()"], "reveals": "Full DSA register state at hang", "relevance": "Global state capture to rule out other issues"},
            {"category": "pcie_aer", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.ppaerucsts.show()"], "reveals": "PCIe errors escalated from hang timeout", "relevance": "Hung state may eventually generate completion timeout AER error"}
        ],
        "beyond_sme": [
            {"description": "Real-time per-stream translation queue depth monitoring", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('src1')", "sv.socket0.imh0.acc.acc_0.dsa.showsearch('src2')"], "why": "Direct Src1 vs Src2 queue depth comparison is the definitive proof of the deadlock mechanism"},
            {"description": "Reduce opcode descriptor with known transfer size at deadlock boundary", "commands": ["Submit single Reduce descriptor at exactly 449KB with MRRS=0, TBTRE=0"], "why": "Controlled reproduction at exact 449KB confirms 448KB boundary hypothesis and allows live-hang register capture"}
        ]
    },
    "phase5_validate": {
        "how_testcase_encounters_defect": "direct — Platform test explicitly issues Reduce/ReduceDC operations at sizes exceeding the 448KB arbiter limit to characterize the deadlock",
        "root_cause_domain": "DSA internal translation request arbiter (silicon bug hw.dsa)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high — arbiter_state + link_state(MRRS/TBTRE) + wq_state would pinpoint the exact cause, configuration impact, and WA status in a single debug pass",
        "recommendation_rationale": "arbiter_state directly shows Src1 queue saturation. link_state MRRS/TBTRE explains why reproducibility varies. wq_state OPCFG bits 25:26 shows WA application. This is the ideal first-pass debug set — all three Tier 1 logs together provide complete root cause identification without iteration. Errata and WA are documented.",
        "iteration_savings": "5"
    }
}

# ════════════════════════════════════════════════════════════════════════════
# BATCH 3 — Records 11-18
# ════════════════════════════════════════════════════════════════════════════

# ── Record 11: 14027410037 — DSA Gather copy 0x1A / completion buffer exhaustion
BATCH["14027410037"] = {
    "phase2_nga": {
        "testcase_name": "DSA Gather Copy (0x1C) large SGL transfer — sglsize 2 and 4",
        "testcase_command": "not available (SysDebug forward of field validation test)",
        "testcase_parameters": "DSA Gather Copy opcode 0x1C, sglsize=2 and sglsize=4",
        "testcase_domain_focus": "DSA data streaming — Gather Copy SGL operations exercising multi-source read path and completion buffer allocation"
    },
    "phase3_verify": {
        "verified_problem_statement": "DSA Gather Copy (0x1C) returns error 0x1A (Internal Error) after timeout for sglsize 2 and 4. All internal completion buffer slots are exhausted, preventing remaining read requests from completing.",
        "verified_root_cause": "DSA base partition requires a handshake with the processing block partition after all source data is read. RTL requires ALL read requests to complete before sending the handshake. For large sglsize, DSA exhausts all internal completion buffer allocations — it cannot acquire new slots because existing reads are waiting for the handshake that depends on completing those same reads. Classic circular dependency / resource deadlock.",
        "verified_fix": "hw.bug conclusion on hw.dsa for release package.dmrap-ucc-x1-a0. Errata filed. Silicon workaround: limit Gather Copy sglsize or reduce outstanding read count per descriptor batch.",
        "architectural_element": "DSA base partition / processing block partition handshake, completion buffer allocator",
        "failure_registers": ["sv.socket0.imh0.acc.acc_0.dsa.swerror0.show()", "sv.socket0.imh0.acc.acc_0.dsa.swerror1.show()", "arbiter state showsearch('queue')", "showsearch('credit')", "perfmon cntrdata_0 (EV_CL_READ stalled)"],
        "adjacent_subsystems": ["DSA processing block partition", "completion buffer allocator", "internal read request queue", "VT-d translation queue"]
    },
    "phase4_recommend": {
        "tier1": [
            {"category": "arbiter_state", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('queue')", "sv.socket0.imh0.acc.acc_0.dsa.showsearch('credit')", "sv.socket0.imh0.acc.acc_0.dsa.showsearch('outstanding')"], "reveals": "Completion buffer occupancy — all slots taken, no new allocations possible", "relevance": "Directly shows the circular resource exhaustion causing the 0x1A error"},
            {"category": "swerror_dump", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.swerror0.show()", "sv.socket0.imh0.acc.acc_0.dsa.swerror1.show()", "sv.socket0.imh0.acc.acc_0.dsa.swerror2.show()"], "reveals": "Error code 0x1A (Internal Error), WQ index, and operation type", "relevance": "err_code=0x1A directly identifies completion buffer exhaustion failure mode"},
            {"category": "perfmon_counters", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.cntrdata_0.show()", "sv.socket0.imh0.acc.acc_0.dsa.cntrdata_1.show()"], "reveals": "EV_CL_READ stalled vs EV_CL_PROCESSED zero — confirms reads issued but not completing", "relevance": "Shows read-stall pattern: reads inflight but no processing due to buffer exhaustion"},
            {"category": "register_dump", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.show()", "sv.socket0.imh0.acc.acc_0.dsa.gencap.show()"], "reveals": "DSA general capability including completion buffer depth", "relevance": "GENCAP shows max completion buffer size for cross-reference"}
        ],
        "tier2": [
            {"category": "wq_state", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.wqcfg_0.show()", "sv.socket0.imh0.acc.acc_0.dsa.wqcfg_1.show()"], "reveals": "WQ configuration and Max Transfer Size for Gather Copy", "relevance": "Shows if SW WA configuration is present"},
            {"category": "descriptor_status", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('desc')"], "reveals": "In-flight Gather Copy descriptor state", "relevance": "Shows number of outstanding source reads from the Gather list"},
            {"category": "vtd_context", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('pasid')", "sv.socket0.imh0.acc.acc_0.dsa.showsearch('prq')"], "reveals": "PASID and page request state for Gather source addresses", "relevance": "Each Gather source requires a translation — high sglsize amplifies translation queue pressure"}
        ],
        "tier3": [
            {"category": "tlb_pressure", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('tlb')", "sv.socket0.imh0.acc.acc_0.dsa.showsearch('inval')"], "reveals": "IOTLB pressure from multiple Gather source addresses", "relevance": "High sglsize amplifies IOTLB miss rate contributing to completion stall"},
            {"category": "link_state", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('mrrs')", "sv.socket0.imh0.acc.acc_0.dsa.showsearch('devctl')"], "reveals": "MRRS affects completion buffer entries per source read", "relevance": "Small MRRS multiplies completion buffer usage per Gather source"}
        ],
        "beyond_sme": [
            {"description": "DSA completion buffer allocation counter (base vs processing block)", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('cmpl')", "sv.socket0.imh0.acc.acc_0.dsa.showsearch('buf')"], "why": "Direct buffer count readout immediately quantifies the resource starvation"},
            {"description": "Gather Copy with sglsize=1 (passing) vs sglsize=2 (failing)", "commands": ["Test sglsize=1 to confirm pass, sglsize=2 to find exact deadlock threshold"], "why": "Binary search identifies exact completion buffer capacity limit for SW workaround value"}
        ]
    },
    "phase5_validate": {
        "how_testcase_encounters_defect": "direct — test explicitly issues Gather Copy with sglsize 2 and 4, directly exercising the completion buffer path that exhausts",
        "root_cause_domain": "DSA internal completion buffer allocator / base-to-processing-block handshake",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high — swerror_dump (err_code 0x1A) + arbiter_state (buffer occupancy) + perfmon (stalled reads) identify circular dependency in first pass",
        "recommendation_rationale": "swerror0 error code 0x1A is unambiguous. arbiter_state queue/credit shows full buffer. perfmon shows EV_CL_READ stalled. Three logs together give complete root cause without iteration.",
        "iteration_savings": "3"
    }
}

# ── Record 12: 16030097390 — QAT PCIe AER (platform infra, not silicon) ──────
BATCH["16030097390"] = {
    "phase2_nga": {
        "testcase_name": "QAT_Hash_test, QAT device feature validation (DMR AP IMH1 1S BKC)",
        "testcase_command": "NGA UUIDs: 45958e01-e247-4808-8507-44dcab1aae7a, 5bd589f5-957e-4e10-b407-ced39624c228",
        "testcase_parameters": "DMR AP BKC, IMH1, 1S, CentOS, QAT NGA Kayak automation",
        "testcase_domain_focus": "QAT hash and crypto feature validation via CentOS Accelerator automation scripts"
    },
    "phase3_verify": {
        "verified_problem_statement": "PCIe AER event on QAT device 0000:01:00.0 causes CentOS Accelerator script failures and blocks NGA Kayak automation. Concurrent sighting 16029877187 reports AER on multiple infrastructure PCIe devices (AST1150, USB, Ethernet) on each boot.",
        "verified_root_cause": "Platform-level PCIe AER from infrastructure devices (AST1150/USB/Ethernet) incidentally affects QAT validation. AER events from infrastructure PCIe devices propagate through Root Complex Event Collector (RCEC) affecting all downstream PCIe devices including QAT. RASIP/IEH centrally collects these errors. NOT a QAT silicon defect. Root AER source is infrastructure PCIe, correlated with sighting 16029877187.",
        "verified_fix": "Root cause resolved (status: complete). Fix: suppress infrastructure PCIe AER events (or resolve underlying infrastructure device issue from 16029877187) to unblock QAT automation.",
        "architectural_element": "PCIe Root Complex Event Collector (RCEC), RASIP/IEH error handler, infrastructure PCIe devices (AST1150, USB, Ethernet)",
        "failure_registers": ["ppaercs (QAT endpoint AER correctable)", "ppaerucsts (QAT endpoint AER uncorrectable)", "AER ERRSRCID in RCEC", "MCi_STATUS (MCACOD=0x0E0B generic IO error)", "MCi_MISC (PCIe Requester ID)"],
        "adjacent_subsystems": ["PCIe RCEC", "DMR RASIP/IEH", "infrastructure devices (AST1150 BMC, USB, Ethernet)", "QAT/CPM 0000:01:00.0"]
    },
    "phase4_recommend": {
        "tier1": [
            {"category": "pcie_aer", "commands": ["sv.socket0.imh0.acc.acc_0.cpm.ppaercs.show()", "sv.socket0.imh0.acc.acc_0.cpm.ppaerucsts.show()", "sv.socket0.imh0.acc.acc_0.cpm.ppaerucsev.show()"], "reveals": "QAT endpoint AER error type — correctable vs uncorrectable", "relevance": "Distinguishes whether QAT is the AER source or victim"},
            {"category": "dmesg_kernel", "commands": ["dmesg | grep -i 'AER\\|pcie.*error\\|qat\\|cpm\\|0000:01:00'", "dmesg -T | grep -A5 'AER'"], "reveals": "Kernel AER handler messages including source device identification", "relevance": "OS AER handler logs ERRSRCID — shows whether QAT or infrastructure device triggered AER"},
            {"category": "mce_log", "commands": ["dmesg | grep -i 'mce\\|machine check\\|hardware error'", "sv.sockets.uncore.showsearch('mca')"], "reveals": "MCA bank registers — MCi_MISC contains PCIe Requester ID if IOMCA enabled", "relevance": "MCACOD=0x0E0B in MCi_STATUS + Requester ID in MCi_MISC identifies exact PCIe device that caused AER"}
        ],
        "tier2": [
            {"category": "register_dump", "commands": ["sv.socket0.imh0.acc.acc_0.cpm.show()"], "reveals": "QAT/CPM device health post-AER", "relevance": "Confirms device still functional (infrastructure AER) vs truly failed (QAT silicon)"},
            {"category": "platform_topology", "commands": ["sv.sockets.show()", "sv.socket0.imh0.bus0.show()"], "reveals": "Platform PCIe topology — all devices including infrastructure", "relevance": "Shows PCIe device relationships including infrastructure vs QAT"},
            {"category": "firmware_log", "commands": ["sv.socket0.imh0.acc.acc_0.cpm.showsearch('fw')"], "reveals": "QAT firmware state post-AER", "relevance": "AER may disrupt QAT FW if function reset triggered"}
        ],
        "tier3": [
            {"category": "link_state", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('lnk')"], "reveals": "PCIe link state after AER event", "relevance": "AER with function reset causes link re-training"},
            {"category": "punit_mailbox", "commands": ["sv.socket0.imh0.showsearch('punit')"], "reveals": "Power state at time of AER", "relevance": "Power state transitions on boot can generate infrastructure AER"}
        ],
        "beyond_sme": [
            {"description": "AER ERRSRCID from RCEC registers", "commands": ["Read RCEC AER ERRSRCID to identify exact PCIe Requester ID of AER source"], "why": "ERRSRCID directly identifies whether QAT or infrastructure device generated AER — resolves silicon vs infra in one register read"},
            {"description": "BMC/BIOS RASIP error log", "commands": ["Access BMC SEL log and BIOS error log for RASIP AER entries"], "why": "RASIP logs infrastructure AER events not visible to OS — shows boot-time AER sources before CentOS loads"}
        ]
    },
    "phase5_validate": {
        "how_testcase_encounters_defect": "side-effect — QAT test is a victim; PCIe AER from infrastructure devices causes automation script to fail before QAT testing begins",
        "root_cause_domain": "Platform infrastructure PCIe (AST1150/USB/Ethernet AER on boot)",
        "domain_relationship": "cross-domain",
        "recommendation_accuracy": "high — pcie_aer ERRSRCID + dmesg AER handler + MCi_MISC Requester ID distinguish QAT silicon from infrastructure AER in first pass",
        "recommendation_rationale": "AER ERRSRCID in RCEC directly identifies which device generated the AER. dmesg AER handler confirms from SW perspective. Together resolve QAT silicon vs platform infrastructure root cause, potentially redirecting to sighting 16029877187.",
        "iteration_savings": "3"
    }
}

# ── Record 13: 14027390099 — DSA Gather Copy WQ MaxXferSize bypass ────────────
BATCH["14027390099"] = {
    "phase2_nga": {
        "testcase_name": "DSA Gather Copy (0x1C) WQ Max Transfer Size enforcement test",
        "testcase_command": "not available (X1 A0 VV test)",
        "testcase_parameters": "DSA WQ configured with MaxXferSize=1, Gather Copy sglsize > MaxXferSize",
        "testcase_domain_focus": "DSA WQ enforcement — WQ Max Transfer Size check for Gather Copy (opcode 0x1C). Logs already present: register_dump, descriptor_status, wq_state"
    },
    "phase3_verify": {
        "verified_problem_statement": "DSA Gather Copy (0x1C) completes successfully when WQ MaxXferSize=1 and transfer size > 1. Expected: completion record error 0x13 (Invalid Transfer Size). Actual: descriptor completes with success.",
        "verified_root_cause": "DSA Gather Copy (opcode 0x1C) bypasses the WQ MaxXferSize check in the descriptor check pipeline. Transfer size validation for Gather Copy does not apply the WQ maximum transfer size limit — silicon RTL oversight. Status: rejected (errata candidate alongside 14027376512).",
        "verified_fix": "Errata filed for DMR. SW workaround: do not rely on WQ MaxXferSize enforcement for Gather Copy. Use host-side validation before descriptor submission. No ECO.",
        "architectural_element": "DSA descriptor check pipeline — WQ MaxXferSize enforcement for Gather Copy opcode",
        "failure_registers": ["sv.socket0.imh0.acc.acc_0.dsa.wqcfgd0.show()", "sv.socket0.imh0.acc.acc_0.dsa.wqcfg_0.show()", "sv.socket0.imh0.acc.acc_0.dsa.swerror0.show()"],
        "adjacent_subsystems": ["DSA descriptor check engine", "WQ configuration registers", "WQ Max Transfer Size enforcer"]
    },
    "phase4_recommend": {
        "tier1": [
            {"category": "wq_state", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.wqcfg_0.show()", "sv.socket0.imh0.acc.acc_0.dsa.wqcfgd0.show()"], "reveals": "WQ Max Transfer Size field confirming restriction is configured", "relevance": "Already present — confirms WQ is configured with MaxXferSize=1 as intended"},
            {"category": "descriptor_status", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('desc')"], "reveals": "Completion record status — 0x00 (success) when 0x13 (InvalidXferSize) expected", "relevance": "Already present — directly shows bypass: success completion when error expected"},
            {"category": "swerror_dump", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.swerror0.show()", "sv.socket0.imh0.acc.acc_0.dsa.swerror1.show()"], "reveals": "SWERROR0 error code — empty confirms MaxXferSize check was skipped", "relevance": "Absence of error code 0x13 in SWERROR confirms the check was bypassed in descriptor pipeline"}
        ],
        "tier2": [
            {"category": "register_dump", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.show()", "sv.socket0.imh0.acc.acc_0.dsa.opcap0.show()", "sv.socket0.imh0.acc.acc_0.dsa.opcap1.show()"], "reveals": "Full DSA register state and operation capabilities", "relevance": "Already present — baseline confirming Gather Copy support"},
            {"category": "event_capabilities", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.evntcap_0.show()", "sv.socket0.imh0.acc.acc_0.dsa.evntcap_1.show()"], "reveals": "Capability flags for descriptor check enforcement", "relevance": "Confirms which capability flags control MaxXferSize check"}
        ],
        "tier3": [
            {"category": "perfmon_counters", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.cntrdata_0.show()"], "reveals": "Operation count increment — confirms completion despite expected rejection", "relevance": "Non-zero counter confirms bypass by showing successful operation increment"}
        ],
        "beyond_sme": [
            {"description": "Cross-opcode MaxXferSize comparison: MOV (0x03) vs Gather Copy (0x1C)", "commands": ["Run same MaxXferSize test with MOV opcode — should fail with 0x13"], "why": "Differentiates opcode-specific bypass from global MaxXferSize check failure — essential for errata scope"},
            {"description": "Descriptor check pipeline trace for opcode 0x1C", "commands": ["Internal trace of descriptor validation path for Gather Copy opcode"], "why": "RTL may have missing check specifically for 0x1C — trace shows which check stage is absent"}
        ]
    },
    "phase5_validate": {
        "how_testcase_encounters_defect": "direct — test explicitly configures WQ MaxXferSize=1 and submits Gather Copy above limit",
        "root_cause_domain": "DSA descriptor check pipeline (Gather Copy MaxXferSize bypass)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high — wq_state + descriptor_status (already present) confirm bypass in first pass; swerror_dump absence of 0x13 is definitive",
        "recommendation_rationale": "All Tier 1 logs already present (register_dump, descriptor_status, wq_state). swerror0 showing no 0x13 error code is definitive confirmation. Root cause immediately identifiable from existing artifacts.",
        "iteration_savings": "2"
    }
}

# ── Record 14: 14027389776 — QAT DC Stateless slice type 18 (Simics model gap)
BATCH["14027389776"] = {
    "phase2_nga": {
        "testcase_name": "dc_stateless_multi_op_sample — QAT DC Stateless compression (Simics)",
        "testcase_command": "dc_stateless_multi_op_sample (standalone, with bkc.py Simics startup script)",
        "testcase_parameters": "DMR Simics dmr-rio-7/2026ww10.5.00_03, vfio-pci 0000:0f:01.0, QAT DC stateless compression",
        "testcase_domain_focus": "QAT/CPM data compression — DC Stateless Multi-Op using cpaDcCompressData2 via VFIO passthrough in Simics"
    },
    "phase3_verify": {
        "verified_problem_statement": "QAT DC Stateless compression hangs in DMR Simics. CPM Simics model rejects CPP command type 8 targeting slice type 18 (number 0 does not exist), causing dc_stateless_multi_op_sample to hang after cpaDcInitSession.",
        "verified_root_cause": "DMR CPM Simics model does not support slice type 18 for CPP command type 8 (DC compression operation). The Simics CPM functional model is missing the RTL implementation of slice type 18, which is a specific internal processing slice required for DC stateless compression. This is a Simics model completeness/configuration issue — NOT a silicon defect. Slice type 18 may be a DMR CPM feature not yet modeled, or a configuration not enabled in the Simics model.",
        "verified_fix": "Root cause resolved (status: complete). Fix: update DMR CPM Simics model to add slice type 18 support, or update bkc.py config to enable it. Firmware revision check recommended.",
        "architectural_element": "QAT/CPM Simics functional model — CPP command dispatch to slice types",
        "failure_registers": ["Simics log: cpm_sc_device_0 error output", "sv.socket0.imh0.acc.acc_0.cpm.showsearch('fw')", "sv.socket0.imh0.acc.acc_0.cpm.showsearch('me')", "dmesg.log (attached)", "oakstream_rio.simics.log (attached)"],
        "adjacent_subsystems": ["QAT firmware ME", "CPP command router", "DC compression slice", "vfio-pci passthrough", "Simics CPM model"]
    },
    "phase4_recommend": {
        "tier1": [
            {"category": "firmware_log", "commands": ["sv.socket0.imh0.acc.acc_0.cpm.showsearch('fw')", "sv.socket0.imh0.acc.acc_0.cpm.showsearch('me')", "grep 'slice\\|cpm_sc\\|CPP\\|fetch_descriptor' <simics.log>"], "reveals": "CPM ME firmware state and CPP command processing — slice type 18 support", "relevance": "Simics log already shows 'slice type 18 does not exist' — firmware/model logs confirm which DMR CPM version supports this slice"},
            {"category": "dmesg_kernel", "commands": ["dmesg | grep -i 'qat\\|cpm\\|vfio\\|pci.*0f:01'", "cat dmesg.log"], "reveals": "Kernel messages for vfio-pci bind and QAT driver init", "relevance": "Already attached — shows device reset sequence before hang"},
            {"category": "register_dump", "commands": ["sv.socket0.imh0.acc.acc_0.cpm.show()"], "reveals": "CPM/QAT register state post-hang", "relevance": "Baseline state to confirm device error after cpaDcInitSession"}
        ],
        "tier2": [
            {"category": "swerror_dump", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.swerror0.show()"], "reveals": "CPM software error code from failed DC init", "relevance": "Error code identifies whether failure is in descriptor submission or execution"},
            {"category": "vtd_context", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('pasid')"], "reveals": "vfio-pci PASID and IOMMU state", "relevance": "VFIO passthrough PASID misconfiguration could cause command routing failure"},
            {"category": "pcie_aer", "commands": ["sv.socket0.imh0.acc.acc_0.cpm.ppaercs.show()", "sv.socket0.imh0.acc.acc_0.cpm.ppaerucsts.show()"], "reveals": "PCIe AER from CPM model error escalation", "relevance": "Simics CPM model error may generate PCIe AER"}
        ],
        "tier3": [
            {"category": "platform_topology", "commands": ["sv.socket0.imh0.acc.acc_0.show()"], "reveals": "CPM instance topology in Simics model", "relevance": "Confirms correct CPM instance is targeted by vfio-pci"}
        ],
        "beyond_sme": [
            {"description": "CPM Simics model version vs CPP slice type 18 support matrix", "commands": ["Check dmr-rio Simics model version against CPM slice type 18 support"], "why": "Slice type 18 support is model-version-specific — model version immediately resolves whether this is a missing feature or misconfiguration"},
            {"description": "bkc.py CPM configuration dump", "commands": ["Inspect bkc.py for CPM slice enable parameters"], "why": "Slice type 18 may exist in model but require explicit enable via bkc.py — common pattern in Simics CPM setup"}
        ]
    },
    "phase5_validate": {
        "how_testcase_encounters_defect": "direct — dc_stateless_multi_op_sample calls cpaDcCompressData2 which triggers CPP command type 8 to slice type 18",
        "root_cause_domain": "QAT/CPM Simics model — slice type 18 not implemented/enabled",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high — Simics log already shows exact error; firmware_log + model version check resolve root cause in first pass",
        "recommendation_rationale": "Simics log 'slice type 18 number 0 does not exist' is definitive. firmware_log (ME state) + model version comparison distinguishes model incompleteness vs misconfiguration. Dmesg already attached. Root cause identifiable from existing artifacts.",
        "iteration_savings": "2"
    }
}

# ── Record 15: 16030078778 — IAA/QAT SSH timeout on 2S (test infra) ──────────
BATCH["16030078778"] = {
    "phase2_nga": {
        "testcase_name": "IAA_user_mode_randomize_config_opcodes_L, QAT_device_enumeration_and_driver_verify_L (multiple)",
        "testcase_command": "NGA UUIDs: a189d215, d2b180f3, 2707c3ee, 47c0243f, d9f83824 — Kayak automation",
        "testcase_parameters": "DMR AP BKC X1 2S platform, CentOS, Kayak automation via SSH",
        "testcase_domain_focus": "IAA and QAT feature validation via CentOS Accelerator scripts — SSH-based test execution on 2S platform"
    },
    "phase3_verify": {
        "verified_problem_statement": "CentOS Accelerator scripts fail on 2S DMR with 'Timeout at 24, test did not start' for multiple IAA and QAT tests. Automation script does not wait for SUT to fully boot on 2S before attempting SSH.",
        "verified_root_cause": "Test automation infrastructure issue: Kayak automation SSH retry timeout insufficient for 2S platforms. 2S DMR takes longer to boot (memory init for 2 sockets) than 1S. Script's SSH connection attempt times out (24 sec) before SUT SSH daemon is ready. NOT a silicon defect.",
        "verified_fix": "Root cause resolved (status: complete). Fix: increase SSH connect timeout in Kayak for 2S platform configuration, or add SUT-ready polling before SSH attempt.",
        "architectural_element": "Kayak test automation framework — SSH connection timeout for 2S platform",
        "failure_registers": [],
        "adjacent_subsystems": ["Kayak automation framework", "SSH connection layer", "2S DMR boot sequence", "CentOS platform scripts"]
    },
    "phase4_recommend": {
        "tier1": [
            {"category": "dmesg_kernel", "commands": ["dmesg -T > /tmp/dmesg_full.log", "dmesg | grep -i 'ssh\\|connect\\|timeout'"], "reveals": "SUT boot completion timestamp and SSH daemon start time", "relevance": "Shows exact time SUT is SSH-ready vs when Kayak attempts connection — quantifies the timeout gap"},
            {"category": "platform_topology", "commands": ["sv.sockets.show()", "sv.socket1.imh0.show()"], "reveals": "2S topology enumeration time — confirms slower 2S boot path", "relevance": "2S memory initialization shows additional time vs 1S"}
        ],
        "tier2": [
            {"category": "register_dump", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.show()", "sv.socket0.imh0.acc.acc_0.iaa.show()"], "reveals": "Device state when SSH eventually connects — confirms hardware healthy", "relevance": "Verifies timeout is infrastructure-only; accelerators functional after longer boot"},
            {"category": "dmesg_kernel", "commands": ["dmesg | grep -i 'sshd\\|openssh'"], "reveals": "SSH daemon start time", "relevance": "Confirms sshd not yet running when Kayak connected"}
        ],
        "tier3": [],
        "beyond_sme": [
            {"description": "Kayak platform profile: 1S vs 2S SSH_TIMEOUT parameter", "commands": ["Compare Kayak platform config for 1S (passing) vs 2S (failing) SSH_TIMEOUT"], "why": "Direct config diff immediately identifies missing timeout parameter without hardware analysis"},
            {"description": "2S DMR boot timeline measurement", "commands": ["Measure time from power-on to sshd-ready on 2S DMR"], "why": "Provides exact timeout value for Kayak config fix — empirical data for workaround"}
        ]
    },
    "phase5_validate": {
        "how_testcase_encounters_defect": "side-effect — tests fail before starting due to infrastructure timeout; DSA/IAA silicon never exercised",
        "root_cause_domain": "Test automation infrastructure (Kayak SSH timeout for 2S)",
        "domain_relationship": "cross-domain",
        "recommendation_accuracy": "high — dmesg boot timeline + Kayak config comparison immediately identify automation timeout gap",
        "recommendation_rationale": "Pure infrastructure issue. dmesg shows SUT-ready time; Kayak config shows SSH timeout value. Gap between them is the fix. No silicon analysis required.",
        "iteration_savings": "2"
    }
}

# ── Record 16: 14027376512 — DSA Gather Copy WQ bypass clone (errata) ─────────
BATCH["14027376512"] = {
    "phase2_nga": {
        "testcase_name": "DSA Gather Copy (0x1C) WQ Max Transfer Size bypass — Pre-Sighting errata clone",
        "testcase_command": "not available (Pre-Sighting to Sighting clone of 14027390099)",
        "testcase_parameters": "Same as 14027390099: WQ MaxXferSize=1, Gather Copy exceeds limit",
        "testcase_domain_focus": "DSA WQ MaxTransferSize enforcement for Gather Copy (opcode 0x1C) — errata tracking clone for hw.dsa"
    },
    "phase3_verify": {
        "verified_problem_statement": "Clone of 14027390099: DSA Gather Copy bypasses WQ Max Transfer Size check. This clone is used for errata tracking on hw.dsa component.",
        "verified_root_cause": "Same as 14027390099: DSA Gather Copy (0x1C) descriptor check pipeline does not apply WQ MaxXferSize limit. Conclusion: errata candidate on hw.dsa for DMR A0. Decision: reject FP (False Positive from validation perspective) while DSA team evaluates software workaround feasibility.",
        "verified_fix": "03/25/2026: Moved from open to reject state. 03/20/2026: Rejecting DSA Gather/Copy bugs for DMR (reject FP). Tag for errata review. SW workaround options under discussion. No ECO-able fix.",
        "architectural_element": "DSA descriptor check pipeline — WQ MaxXferSize enforcement for Gather Copy opcode 0x1C",
        "failure_registers": ["sv.socket0.imh0.acc.acc_0.dsa.wqcfgd0.show()", "sv.socket0.imh0.acc.acc_0.dsa.swerror0.show()", "descriptor completion record (status=0x00 when 0x13 expected)"],
        "adjacent_subsystems": ["DSA descriptor check engine", "WQ configuration registers", "errata documentation system"]
    },
    "phase4_recommend": {
        "tier1": [
            {"category": "wq_state", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.wqcfg_0.show()", "sv.socket0.imh0.acc.acc_0.dsa.wqcfgd0.show()"], "reveals": "WQ MaxXferSize field confirming restriction configured", "relevance": "Primary log — confirms WQ configured with MaxXferSize=1, proving bypass is DSA behavior issue"},
            {"category": "descriptor_status", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('desc')"], "reveals": "Completion record status = 0x00 (success) instead of 0x13", "relevance": "Already present — definitive proof of bypass"},
            {"category": "swerror_dump", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.swerror0.show()"], "reveals": "Absence of 0x13 confirms MaxXferSize check skipped", "relevance": "No SWERROR is the evidence — the check did not fire"}
        ],
        "tier2": [
            {"category": "register_dump", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.show()", "sv.socket0.imh0.acc.acc_0.dsa.opcap1.show()"], "reveals": "DSA baseline and operation capabilities", "relevance": "Already present — establishes baseline for errata documentation"},
            {"category": "event_capabilities", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.evntcap_0.show()", "sv.socket0.imh0.acc.acc_0.dsa.evntcap_1.show()"], "reveals": "Capability flags for descriptor check enforcement", "relevance": "Shows which flags control MaxXferSize check — useful for errata scope"}
        ],
        "tier3": [],
        "beyond_sme": [
            {"description": "Opcode sweep: all opcodes with MaxXferSize exceeded", "commands": ["Test MOV, Copy, Fill, Gather Copy, Scatter Copy, Reduce all with MaxXferSize exceeded"], "why": "Errata documentation requires knowing which opcodes bypass the check — comprehensive sweep establishes errata scope"},
            {"description": "Trusted vs untrusted WQ MaxXferSize behavior", "commands": ["Test with privileged vs non-privileged WQ MaxXferSize enforcement"], "why": "SW WA feasibility depends on enforcement for untrusted WQs — determines errata severity"}
        ]
    },
    "phase5_validate": {
        "how_testcase_encounters_defect": "direct — same test setup as 14027390099, direct reproduction of Gather Copy MaxXferSize bypass",
        "root_cause_domain": "DSA descriptor check pipeline (Gather Copy MaxXferSize bypass — errata)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high — existing logs (register_dump, descriptor_status, wq_state already present) are sufficient; errata documentation complete",
        "recommendation_rationale": "All critical logs already present from 14027390099. Opcode sweep (beyond-SME) is the highest-value remaining action for errata scope definition.",
        "iteration_savings": "1"
    }
}

# ── Record 17: 14027360894 — DSA error 0x18 injection (test tool gap) ────────
BATCH["14027360894"] = {
    "phase2_nga": {
        "testcase_name": "dsa_focus_tests[i=[batch,swerror_enable],error_code=misaligned_desc_addr]",
        "testcase_command": "rocket -M 5 --atlas \"--hw dram,dsa -v dsa_focus_tests[i=[batch,swerror_enable],error_code=misaligned_desc_addr]\"",
        "testcase_parameters": "error_injection: batch + swerror_enable + error_code=misaligned_desc_addr (0x18 = Misaligned Descriptor Address)",
        "testcase_domain_focus": "DSA error injection validation — DSArand framework error code injection for batch+swerror_enable, targeting error 0x18 (Misaligned Descriptor Address)"
    },
    "phase3_verify": {
        "verified_problem_statement": "DSArand test framework cannot inject error code 0x18 (Misaligned Descriptor Address) in batch+swerror_enable mode. The requested error injection is silently ignored.",
        "verified_root_cause": "Test framework gap (component: val.env.tool): DSArand does not implement error 0x18 injection for batch+swerror_enable combination. Error 0x18 requires explicit descriptor address misalignment; DSArand auto-generates aligned descriptors making 0x18 injection impossible without explicit misalignment support. NOT a silicon defect.",
        "verified_fix": "Root cause resolved (status: complete). Fix: update DSArand to support explicit descriptor address misalignment for 0x18 injection, or document 0x18 as not injectable in batch+swerror_enable mode.",
        "architectural_element": "DSArand error injection framework — descriptor address alignment control for error 0x18",
        "failure_registers": ["sv.socket0.imh0.acc.acc_0.dsa.swerror0.show() (expected 0x18, actual: no error)", "descriptor completion record alignment check"],
        "adjacent_subsystems": ["DSArand descriptor generator", "Atlas test framework", "DSA descriptor check pipeline (opcode error path)"]
    },
    "phase4_recommend": {
        "tier1": [
            {"category": "swerror_dump", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.swerror0.show()", "sv.socket0.imh0.acc.acc_0.dsa.swerror1.show()"], "reveals": "What error code (if any) DSA reported — confirms 0x18 was not generated", "relevance": "If swerror0 shows different or no error, confirms injection framework failed to create 0x18 condition"},
            {"category": "descriptor_status", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('desc')"], "reveals": "Batch descriptor array addresses — check alignment of descriptor addresses", "relevance": "Already present — misaligned_desc_addr requires batch descriptor address to be misaligned; shows if DSArand created misaligned address"},
            {"category": "register_dump", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.show()"], "reveals": "DSA device state post-injection attempt", "relevance": "Baseline confirms device processed normally (no error), ruling out DSA silicon issue"}
        ],
        "tier2": [
            {"category": "wq_state", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.wqcfg_0.show()"], "reveals": "WQ configuration for batch mode", "relevance": "Batch mode requirements may conflict with misaligned descriptor injection"},
            {"category": "dmesg_kernel", "commands": ["dmesg | grep -i 'dsa\\|idxd'"], "reveals": "idxd driver messages about batch descriptor processing", "relevance": "Driver may swallow error injection attempts before reaching DSA hardware"}
        ],
        "tier3": [],
        "beyond_sme": [
            {"description": "Manual injection with explicit misaligned batch descriptor address", "commands": ["Construct batch descriptor with address at non-64B-aligned offset, submit directly"], "why": "Bypasses DSArand to prove silicon CAN generate 0x18 — isolates gap to test tool rather than silicon"},
            {"description": "DSArand error code support matrix for batch+swerror_enable", "commands": ["Review DSArand documentation for supported error_code values in this mode"], "why": "Documentation may explicitly list 0x18 as unsupported — avoids unnecessary silicon investigation"}
        ]
    },
    "phase5_validate": {
        "how_testcase_encounters_defect": "direct — test explicitly attempts 0x18 error injection but framework cannot generate required condition",
        "root_cause_domain": "Test framework (DSArand val.env.tool — missing 0x18 injection)",
        "domain_relationship": "cross-domain",
        "recommendation_accuracy": "high — swerror_dump absence of 0x18 + manual injection proof confirm test tool gap in first pass",
        "recommendation_rationale": "swerror0 shows what error DSA generated. No 0x18 = DSArand failed to create misalignment. Manual injection with explicitly misaligned address proves silicon CAN generate 0x18. Together distinguish tool gap from silicon defect.",
        "iteration_savings": "2"
    }
}

# ── Record 18: 14027325371 — DSA card presence_check failures (NGA flexcon) ──
BATCH["14027325371"] = {
    "phase2_nga": {
        "testcase_name": "DSA VV tests — CXL and PCIe flexcon plugin presence check (TPostTest_PreTestFailChk)",
        "testcase_command": "NGA UUIDs: 72a0a351-9df4-42aa-a120-b78c50089645, bdc52a61-1f32-4542-9439-5745b1befaa8",
        "testcase_parameters": "DMR A0 VV, CXL and PCIe flexcon plugins, TPostTest_PreTestFailChk state in NGA",
        "testcase_domain_focus": "DSA VV test infrastructure — NGA flexcon CXL/PCIe card presence checks in TPostTest_PreTestFailChk state blocking DSA execution"
    },
    "phase3_verify": {
        "verified_problem_statement": "DSA VV tests in NGA report card presence_check failures from CXL and PCIe flexcon plugins in TPostTest_PreTestFailChk state. Tests blocked from running due to pre/post test card presence validation failures.",
        "verified_root_cause": "Component: val.env.automation — NGA flexcon plugins (CXL and PCIe) report card presence failures for DMR A0. Flexcon plugin's card presence detection does not correctly identify CXL/PCIe cards on DMR A0 platform, or NGA platform profile expected card configurations do not match actual lab setup. Test automation/infrastructure issue, NOT a DSA silicon defect.",
        "verified_fix": "Root cause resolved (status: complete). Fix: update NGA platform profile expected card configurations for DMR A0, or update CXL/PCIe flexcon plugin presence check logic for DMR A0 topology.",
        "architectural_element": "NGA flexcon plugins (CXL, PCIe), TPostTest_PreTestFailChk framework state, card presence check logic",
        "failure_registers": [],
        "adjacent_subsystems": ["NGA Kayak automation", "flexcon CXL plugin", "flexcon PCIe plugin", "DMR A0 lab PCIe/CXL topology"]
    },
    "phase4_recommend": {
        "tier1": [
            {"category": "platform_topology", "commands": ["sv.sockets.show()", "sv.socket0.imh0.bus0.show()", "sv.socket0.imh0.bus1.show()"], "reveals": "Actual PCIe/CXL device topology on DMR A0", "relevance": "Flexcon compares actual topology vs expected — showing actual topology reveals the mismatch source"},
            {"category": "dmesg_kernel", "commands": ["dmesg | grep -i 'pcie\\|cxl\\|AER\\|link'"], "reveals": "PCIe and CXL device enumeration at boot", "relevance": "Shows which PCIe/CXL cards were actually enumerated vs what flexcon expects"}
        ],
        "tier2": [
            {"category": "memory_map", "commands": ["sv.socket0.imh0.bus1.pciExpress2.cxl-01.show()"], "reveals": "CXL device presence and status", "relevance": "Confirms whether CXL device is enumerated in expected state"},
            {"category": "link_state", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('lnk')"], "reveals": "PCIe link state for flexcon card", "relevance": "Link down/degraded would cause presence check failure"}
        ],
        "tier3": [],
        "beyond_sme": [
            {"description": "NGA platform profile for DMR A0 vs actual lab inventory", "commands": ["Compare NGA platform profile expected card list vs lspci -nn output on target"], "why": "Flexcon uses NGA platform profile to validate card presence — profile vs inventory mismatch is root cause, visible from direct comparison"},
            {"description": "flexcon plugin verbose logging for CXL/PCIe", "commands": ["Enable verbose logging in CXL/PCIe flexcon plugins to see which card ID failed"], "why": "Default NGA logs show failure state but not which specific card ID failed — verbose mode identifies exact mismatch for fix"}
        ]
    },
    "phase5_validate": {
        "how_testcase_encounters_defect": "side-effect — DSA tests blocked by infrastructure card presence check; DSA silicon never exercised",
        "root_cause_domain": "NGA automation infrastructure (flexcon plugin / platform profile mismatch)",
        "domain_relationship": "cross-domain",
        "recommendation_accuracy": "high — platform_topology readout + NGA platform profile comparison immediately identify card inventory mismatch",
        "recommendation_rationale": "Pure infrastructure issue. Actual PCIe/CXL topology from sv matches against NGA expected profile. Mismatch is the fix target. No silicon analysis required.",
        "iteration_savings": "2"
    }
}

# ── Batch 4 — records 19-40 ───────────────────────────────────────────────────
BATCH.update({
    "14027319973": {
        "phase2_nga": {"test_name": "dsa_focus_tests[i=SG_CXL2CXL]", "command": "rocket -M @{TestLine.TestStageEstimatedTime} --atlas \"--hw dram,dsa,pcietc -v dsa_focus_tests[i=SG_CXL2CXL]\"", "domain": "DSA scatter-gather CXL2CXL DMA", "parameters": "focus variant SG_CXL2CXL", "pass_fail_history": "not available", "artifacts": []},
        "phase3_verify": {"verified_problem_statement": "Test framework raises Exception: 'Invalid focus test name SG_CXL2CXL!' at dsa_focus_tests.py line 4122 because the focus variant name is not registered in the DMR atlas variant dictionary.", "verified_root_cause": "val.env.content — the SG_CXL2CXL focus variant was not added to the dsa_focus_tests.py variant registry for DMR; test content is missing the variant entry", "verified_fix": "Add SG_CXL2CXL to the dsa_focus_tests variant registry in /usr/local/diamondrapids/atlas/variants/dsa_focus_tests.py", "architectural_element": "none (test content error)", "failure_registers": [], "adjacent_subsystems": ["atlas test framework", "dsa_focus_tests variant registry"]},
        "phase4_recommend": {"tier1": [{"category": "dmesg_kernel", "commands": ["dmesg | grep -i 'dsa'"], "reveals": "device state at test failure", "relevance": "confirm device is present before test invocation"}], "tier2": [], "tier3": [], "beyond_sme": []},
        "phase5_validate": {"how_testcase_encounters_defect": "direct — test explicitly invokes a named focus variant that does not exist in the registry", "root_cause_domain": "test content / atlas variant registry", "domain_relationship": "same-domain", "recommendation_accuracy": "low — standard logs do not help; test content fix is required", "recommendation_rationale": "Fix is to add variant name to dsa_focus_tests.py, not to collect HW logs.", "iteration_savings": "1"}
    },
    "14027289733": {
        "phase2_nga": {"test_name": "QAT comp_enc / hash_compress DynamicDeflate", "command": "not available", "domain": "QAT compression + core AVX/SSE2 verification", "parameters": "zlib-ng with AVX or SSE2 enabled", "pass_fail_history": "sporadic; not reproducible with AVX/SSE2 disabled", "artifacts": []},
        "phase3_verify": {"verified_problem_statement": "Sporadic result mismatches during QAT compression validation where zlib-ng (used as SW reference) produces incorrect output when AVX or SSE2 is enabled. QAT accelerator output is correct; the bug is in the CPU-side verification library.", "verified_root_cause": "zlib-ng 2.x bug: silent data corruption in AVX/SSE2 code path (PR#1442). mc_status.correrrorstatusind set in MCA dumps confirms ECC correctable error interaction with AVX vector operations.", "verified_fix": "Upgrade to zlib-ng >= 2.1.0-beta1 which includes PR#1442 fix.", "architectural_element": "CPU core AVX/SSE2 execution + zlib-ng software", "failure_registers": ["ml2_cr_mc3_status"], "adjacent_subsystems": ["QAT CPM", "DRAM memory controller", "MCA logging"]},
        "phase4_recommend": {"tier1": [{"category": "mce_log", "commands": ["mcelog --client", "sv.sockets.uncore.showsearch('mca')"], "reveals": "correrrorstatusind set confirms correctable ECC error during AVX execution", "relevance": "was already collected and identified the MCA involvement"}], "tier2": [{"category": "register_dump", "commands": ["sv.socket0.imh0.acc.acc_0.cpm.show()"], "reveals": "QAT device state — expected clean", "relevance": "rule out QAT as source of corruption"}], "tier3": [], "beyond_sme": [{"description": "Run same test with AVX/SSE2 disabled in zlib-ng to isolate CPU vs QAT", "commands": ["ZLIB_DISABLE_AVX=1 <test_cmd>"], "why": "toggles the failing code path without changing QAT config"}]},
        "phase5_validate": {"how_testcase_encounters_defect": "side-effect — QAT test uses zlib-ng as SW reference comparator; CPU-side library bug causes false mismatch", "root_cause_domain": "sw.application (zlib-ng library)", "domain_relationship": "cross-domain", "recommendation_accuracy": "high — mce_log collection immediately points to CPU-side error, not QAT", "recommendation_rationale": "MCA dump showing correrrorstatusind + disabling AVX reproduces/resolves issue; narrows to library bug.", "iteration_savings": "3"}
    },
    "14027286159": {
        "phase2_nga": {"test_name": "CPM_Global_Reset_silicon", "command": "python %PythonSvRoot%\\diamondrapids\\reset\\framework\\scripts\\resetSV.py -t global_cf9 -i 1", "domain": "QAT global CF9 reset flow", "parameters": "global reset type: global_cf9", "pass_fail_history": "not available", "artifacts": ["c20545a7-b1b8-4819-9934-8d87606d80da"]},
        "phase3_verify": {"verified_problem_statement": "Global CF9 reset script fails with MCA_FOUND and TARGET_EVENTS_TIMEOUT_ERROR. Multiple MCA/RAS registers latched error state during or after reset, blocking test completion.", "verified_root_cause": "MCA triggered during CPM global reset sequence — likely a QAT/CPM internal reset flow leaves a machine check source uncleared; RASIP error handler detects lingering MCA source post-reset.", "verified_fix": "Pending — MCA source needs identification via RASIP and PUNIT registers.", "architectural_element": "QAT CPM reset arbiter, RASIP MCA error handler, PUNIT reset FSM", "failure_registers": ["sv.socket0.cbb0.base.sncu_top.sncdecs.ncu_mca_err_log", "sv.socket0.imh0.rasip.root_ras.rasip_regs_block.rasip_reg_msg_mem_rasip_error_handler_domain.reg_mca_err_src_log", "sv.socket0.imh0.punit.ras.gpsb.mc_status", "sv.socket0.cbb0.compute0.module2.ml2_cr_mc3_status", "sv.socket0.imh0.hwrs.gpsb.hwrs_cmd_current_index"], "adjacent_subsystems": ["RASIP", "PUNIT", "CBB NCU", "QAT CPM firmware"]},
        "phase4_recommend": {"tier1": [{"category": "mce_log", "commands": ["sv.socket0.imh0.rasip.root_ras.rasip_regs_block.rasip_reg_msg_mem_rasip_error_handler_domain.reg_mca_err_src_log.show()", "sv.socket0.cbb0.base.sncu_top.sncdecs.ncu_mca_err_log.show()", "sv.socket0.imh0.punit.ras.gpsb.mc_status.show()"], "reveals": "which MCA bank/source triggered the machine check at reset", "relevance": "MCA error is the direct failure symptom"}, {"category": "firmware_log", "commands": ["sv.socket0.imh0.acc.acc_0.cpm.showsearch('fw')", "sv.socket0.imh0.acc.acc_0.cpm.showsearch('me')"], "reveals": "CPM firmware state post-reset", "relevance": "QAT ME may fail to complete shutdown before reset, leaving stale state"}], "tier2": [{"category": "register_dump", "commands": ["sv.socket0.imh0.acc.acc_0.cpm.show()"], "reveals": "QAT device state", "relevance": "confirm device is in expected post-reset state"}], "tier3": [], "beyond_sme": [{"description": "Capture HWRS reset sequencer current index before/after reset", "commands": ["sv.socket0.imh0.hwrs.gpsb.hwrs_cmd_current_index.show()", "sv.socket0.imh1.hwrs.gpsb.hwrs_cmd_current_index.show()"], "why": "shows which reset step was in progress when MCA fired"}]},
        "phase5_validate": {"how_testcase_encounters_defect": "direct — test exercises QAT global reset path that triggers the MCA", "root_cause_domain": "hw/fw QAT reset sequence + MCA handling", "domain_relationship": "adjacent", "recommendation_accuracy": "high — tier1 MCA source registers were already shown to contain relevant state", "recommendation_rationale": "MCA source log and RASIP registers directly identify which bank triggered; HWRS index shows reset step. This would have resolved in 1 pass.", "iteration_savings": "3"}
    },
    "14027270401": {
        "phase2_nga": {"test_name": "DSA PRS (Page Request Service) error handling", "command": "not available", "domain": "DSA IOMMU PRS flow — completion record/EVL write on IOMMU Invalid Request response", "parameters": "IOMMU returns Invalid Request for PRS; EVL enabled", "pass_fail_history": "not available", "artifacts": []},
        "phase3_verify": {"verified_problem_statement": "When IOMMU responds with Invalid Request (IR) to a DSA PRS, DSA fails to write completion record or Event Log (EVL) entry. SWERROR shows error code 0x1A only when EVL is disabled.", "verified_root_cause": "DSA silicon bug: upon receiving IOMMU IR for PRS, the internal write path to EVL/completion record is gated by an incorrect condition — the IR response causes the write-enable to be suppressed, leaving descriptors silently incomplete.", "verified_fix": "Pending silicon fix — tracked in 14027270401 as DSA internal mishandling of IR response separate from IOMMU IR root cause.", "architectural_element": "DSA descriptor completion write path, EVL write arbiter, PRS response handler", "failure_registers": ["dsa.swerror0", "dsa.swerror1", "dsa.swerror2"], "adjacent_subsystems": ["IOMMU/VT-d", "DSA PRS engine", "EVL buffer"]},
        "phase4_recommend": {"tier1": [{"category": "swerror_dump", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.swerror0.show()", "sv.socket0.imh0.acc.acc_0.dsa.swerror1.show()", "sv.socket0.imh0.acc.acc_0.dsa.swerror2.show()"], "reveals": "error code 0x1A confirms IOMMU IR received; overflow bit shows EVL write was attempted but not delivered", "relevance": "directly captures the DSA error state"}, {"category": "vtd_context", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('prs')", "sv.socket0.imh0.acc.acc_0.dsa.showsearch('prq')"], "reveals": "PRS queue state and IOMMU IR response status", "relevance": "shows whether IOMMU IR was properly signaled to DSA"}], "tier2": [{"category": "descriptor_status", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('desc')"], "reveals": "descriptor completion state — expected to be stuck in-flight", "relevance": "shows incomplete descriptor when EVL write suppressed"}], "tier3": [], "beyond_sme": []},
        "phase5_validate": {"how_testcase_encounters_defect": "direct — test specifically exercises IOMMU PRS Invalid Request response handling", "root_cause_domain": "hw.dsa (DSA EVL write path on IOMMU IR)", "domain_relationship": "same-domain", "recommendation_accuracy": "high — swerror + vtd_context + descriptor_status combination directly identifies the stuck descriptor and missing EVL write", "recommendation_rationale": "swerror0 with valid=1 and err_code=0x1A, combined with empty EVL, is the diagnostic signature.", "iteration_savings": "2"}
    },
    "14027270390": {
        "phase2_nga": {"test_name": "DSA Gather Copy sglsize=2/4 large length", "command": "not available", "domain": "DSA Gather Copy (0x1C) — IOMMU CR write path with multi-element SGLs", "parameters": "sglsize=0x2, length > 0x2CFFF; sglsize=0x4, length above threshold", "pass_fail_history": "not reproducible with sglsize=0x1", "artifacts": []},
        "phase3_verify": {"verified_problem_statement": "Two related issues: (1) IOMMU returns Invalid Request when DSA writes completion record for Gather Copy with sglsize>1 and large length — IOMMU should accept this as valid. (2) DSA fails to write EVL on receiving IR; SWERROR shows 0x1A only when EVL disabled. Internal completion buffer exhausted when IR received.", "verified_root_cause": "Issue 1: DSA generates an incorrect PASID or address for the completion record write when sglsize>1, causing IOMMU to return IR. Issue 2: Same EVL write suppression bug as 14027270401. Cloned to 14027410037 (soc.top). Rejected as FP — tagged for errata review.", "verified_fix": "Under errata review — possible software workaround (limit sglsize or length). Hardware fix tracked in soc.top.", "architectural_element": "DSA Gather Copy engine, completion record write path, PASID translation logic", "failure_registers": ["dsa.swerror0", "dsa.swerror1", "dsa.swerror2"], "adjacent_subsystems": ["IOMMU/VT-d PRS", "DSA completion buffer", "EVL write path"]},
        "phase4_recommend": {"tier1": [{"category": "swerror_dump", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.swerror0.show()", "sv.socket0.imh0.acc.acc_0.dsa.swerror2.show()"], "reveals": "err_code=0x1A (IOMMU IR), fault_address for completion record write", "relevance": "directly captures the IOMMU IR trigger address — compare against expected CR address"}, {"category": "vtd_context", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('pasid')", "sv.socket0.imh0.acc.acc_0.dsa.showsearch('ats')"], "reveals": "PASID table entry validity for completion record address", "relevance": "IOMMU IR implies PASID entry missing/invalid for this address range"}], "tier2": [{"category": "wq_state", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.wqcfg_0.show()"], "reveals": "max transfer size configuration", "relevance": "rule out WQ config as contributing factor"}], "tier3": [], "beyond_sme": [{"description": "Compare completion buffer occupancy at hang point vs normal", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('compbuf')", "sv.socket0.imh0.acc.acc_0.dsa.showsearch('cbuf')"], "why": "buffer exhaustion is the observed symptom; count shows how many pending CRs are waiting"}]},
        "phase5_validate": {"how_testcase_encounters_defect": "direct — Gather Copy with sglsize=2/4 directly triggers the IOMMU IR condition", "root_cause_domain": "hw.dsa PASID/CR write path (errata candidate)", "domain_relationship": "same-domain", "recommendation_accuracy": "high — swerror fault_address + vtd_context PASID state immediately localize the incorrect address generation", "recommendation_rationale": "fault_address in SWERROR2 vs expected CR address reveals the PASID mismatch; would have been found in first pass.", "iteration_savings": "4"}
    },
    "16030007209": {
        "phase2_nga": {"test_name": "QAT Windows BKC setup — PowerShell7 v7.6.0-rc.1 install", "command": "not available (automation framework)", "domain": "QAT Windows platform setup / collateral download", "parameters": "PowerShell7 v7.6.0-rc.1", "pass_fail_history": "WW10 regression", "artifacts": []},
        "phase3_verify": {"verified_problem_statement": "Automation framework fails to download PowerShell7 v7.6.0-rc.1 collateral during SUT installation. RuntimeError raised when collateral tag not found in content configuration YAML.", "verified_root_cause": "val.env.automation — the content configuration YAML file does not have the PowerShell7 v7.6.0-rc.1 tag entry. Either the tag name changed in the new release or the YAML was not updated when the RC version was released.", "verified_fix": "Update content configuration YAML to include PowerShell7 v7.6.0-rc.1 tag, or pin to the last known-good stable tag.", "architectural_element": "none (automation content config)", "failure_registers": [], "adjacent_subsystems": ["content configuration YAML", "SUT installation automation", "collateral download service"]},
        "phase4_recommend": {"tier1": [{"category": "dmesg_kernel", "commands": ["cat /etc/os-release", "powershell --version"], "reveals": "current installed PowerShell version and OS configuration", "relevance": "confirms whether installation partially succeeded"}], "tier2": [], "tier3": [], "beyond_sme": []},
        "phase5_validate": {"how_testcase_encounters_defect": "direct — setup script hits missing collateral tag during install", "root_cause_domain": "val.env.automation (content config YAML)", "domain_relationship": "cross-domain", "recommendation_accuracy": "low — no HW logs needed; fix is to update YAML content config", "recommendation_rationale": "Pure automation/config issue. No silicon analysis required.", "iteration_savings": "1"}
    },
    "14027261180": {
        "phase2_nga": {"test_name": "DSA PRS Invalid Request error handling (original sighting)", "command": "not available", "domain": "DSA IOMMU PRS flow — EVL/completion record write on IR", "parameters": "IOMMU IR for PRS; EVL enabled", "pass_fail_history": "not available", "artifacts": []},
        "phase3_verify": {"verified_problem_statement": "Original sighting for DSA not writing EVL/completion record on IOMMU PRS Invalid Request. Superseded by 14027270401 for DSA internal tracking.", "verified_root_cause": "Same as 14027270401 — DSA silicon mishandles IOMMU IR, fails to write EVL or completion record. SWERROR shows 0x1A only when EVL disabled.", "verified_fix": "Rejected — tracked in 14027270401 and 14027270390 for root cause + errata.", "architectural_element": "DSA EVL write path, PRS response handler", "failure_registers": ["dsa.swerror0"], "adjacent_subsystems": ["IOMMU/VT-d", "EVL buffer"]},
        "phase4_recommend": {"tier1": [{"category": "swerror_dump", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.swerror0.show()"], "reveals": "error code 0x1A confirms IR received", "relevance": "primary indicator"}, {"category": "vtd_context", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('prs')"], "reveals": "PRS queue state", "relevance": "confirm IR response path"}], "tier2": [], "tier3": [], "beyond_sme": []},
        "phase5_validate": {"how_testcase_encounters_defect": "direct — tests IOMMU PRS IR path", "root_cause_domain": "hw.dsa", "domain_relationship": "same-domain", "recommendation_accuracy": "high", "recommendation_rationale": "Duplicate of 14027270401; same diagnostic path.", "iteration_savings": "2"}
    },
    "14027232974": {
        "phase2_nga": {"test_name": "DSA/IAA poisoned memory source operation", "command": "not available", "domain": "DSA/IAA operation on DRAM-poisoned source data", "parameters": "double-bit parity error injected into DRAM; IAA operation uses poisoned data", "pass_fail_history": "not available", "artifacts": []},
        "phase3_verify": {"verified_problem_statement": "When IAA reads poisoned DRAM data, the accelerator sampling logic captures the data_poison SFI EOP signal one cycle too early. This causes data_poison to be latched only during the first data cycle, not for the entire multi-cycle transfer.", "verified_root_cause": "hw.iax RTL bug — accelerator sampling logic latches data_poison only on first data cycle. Root cause confirmed: RTL defect in accelerator sampling logic. Fix tracked in hw.iax, release package.dmrap-ucc-x1-a0.", "verified_fix": "RTL fix in hw.iax for data_poison sampling: capture SFI EOP data_poison for all data cycles, not just the first.", "architectural_element": "IAA data receive path, SFI EOP data_poison signal sampling logic", "failure_registers": ["iaa.swerror0", "iaa.swerror1"], "adjacent_subsystems": ["HIOP SFI interface", "DRAM memory controller", "PCIe TLP EP bit handling"]},
        "phase4_recommend": {"tier1": [{"category": "swerror_dump", "commands": ["sv.socket0.imh0.acc.acc_0.iaa.swerror0.show()", "sv.socket0.imh0.acc.acc_0.iaa.swerror1.show()"], "reveals": "IAA error state when accessing poisoned data", "relevance": "shows whether poison was detected/reported"}, {"category": "descriptor_status", "commands": ["sv.socket0.imh0.acc.acc_0.iaa.showsearch('desc')"], "reveals": "completion record status for IAA operation on poisoned source", "relevance": "expected to show incorrect/missing poison status in completion record"}], "tier2": [{"category": "mce_log", "commands": ["dmesg | grep -i 'mce'"], "reveals": "DRAM uncorrectable error report", "relevance": "confirms double-bit parity error was detected"}], "tier3": [], "beyond_sme": [{"description": "SFI EOP data_poison signal trace — internal signal visible only via RTL simulation or scan capture", "commands": ["not available via PythonSV (internal signal)"], "why": "directly shows the off-by-one cycle latching bug; was the key to root cause in RTL analysis"}]},
        "phase5_validate": {"how_testcase_encounters_defect": "direct — injects DRAM parity error and uses poisoned data as IAA source", "root_cause_domain": "hw.iax (RTL data_poison sampling)", "domain_relationship": "same-domain", "recommendation_accuracy": "medium — swerror + descriptor_status would show incorrect behavior but not the cycle-level latching bug; RTL debug needed for final root cause", "recommendation_rationale": "Field validation can identify incorrect poison handling via completion record mismatch; RTL team needed to identify the exact cycle.", "iteration_savings": "2"}
    },
    "14027223286": {
        "phase2_nga": {"test_name": "IDE/Flexcon port-presence validation (PXP9/PXP11)", "command": "not available", "domain": "val.env.configuration — PCIe/CXL flexcon port presence check post-test", "parameters": "FDU3 node, PXP9/PXP11 upstream ports", "pass_fail_history": "2 executions in 2026ww10.1_vv_ide_68b_flit_mode fail", "artifacts": []},
        "phase3_verify": {"verified_problem_statement": "PostTest TPostTest_PreTestFailChk fails because upstream PreTest flexcon port-presence checks on PXP9/PXP11 already failed. Device topology mismatch between NGA platform profile and actual FDU3 hardware configuration.", "verified_root_cause": "val.env.configuration — FDU3 platform does not have PCIe/CXL cards present on PXP9/PXP11 ports; NGA platform profile expects them. Rejected as infrastructure configuration issue.", "verified_fix": "Update NGA platform profile for FDU3 to reflect actual port availability.", "architectural_element": "none (platform configuration)", "failure_registers": [], "adjacent_subsystems": ["NGA platform profile", "flexcon plugin", "PCIe topology"]},
        "phase4_recommend": {"tier1": [{"category": "platform_topology", "commands": ["sv.socket0.imh0.bus0.show()", "sv.socket0.imh0.bus1.show()"], "reveals": "actual PCIe bus topology", "relevance": "compare against NGA expected profile"}], "tier2": [], "tier3": [], "beyond_sme": []},
        "phase5_validate": {"how_testcase_encounters_defect": "direct — presence check tests the exact ports that are misconfigured", "root_cause_domain": "val.env.configuration", "domain_relationship": "cross-domain", "recommendation_accuracy": "high", "recommendation_rationale": "Platform topology readout immediately shows port absence.", "iteration_savings": "1"}
    },
    "14027203704": {
        "phase2_nga": {"test_name": "QAT compression/crypto descriptor loop (deflate/crypto)", "command": "not available", "domain": "QAT descriptor submission — invalid response after N jobs", "parameters": "every 32 jobs, invalid response in response descriptor", "pass_fail_history": "not available", "artifacts": []},
        "phase3_verify": {"verified_problem_statement": "After every 32 QAT crypto or compression jobs, an invalid response descriptor appears. Indicates a ring buffer or response queue wrap condition.", "verified_root_cause": "fw.cpm — QAT firmware response ring likely has a 32-entry wrap bug; on overflow/wrap the ring pointer is not correctly updated, producing a stale or zeroed response descriptor.", "verified_fix": "Rejected — likely a known firmware issue tracked separately or a known ring size limitation.", "architectural_element": "QAT CPM response ring buffer, firmware ring management", "failure_registers": [], "adjacent_subsystems": ["QAT CPM firmware", "ring buffer manager", "QAT driver"]},
        "phase4_recommend": {"tier1": [{"category": "firmware_log", "commands": ["sv.socket0.imh0.acc.acc_0.cpm.showsearch('ring')", "sv.socket0.imh0.acc.acc_0.cpm.showsearch('rsp')"], "reveals": "ring buffer state and response queue pointers", "relevance": "shows wrap/overflow condition at job 32 boundary"}], "tier2": [{"category": "register_dump", "commands": ["sv.socket0.imh0.acc.acc_0.cpm.show()"], "reveals": "QAT device state", "relevance": "baseline for ring size and pointer configuration"}], "tier3": [], "beyond_sme": []},
        "phase5_validate": {"how_testcase_encounters_defect": "direct — loops exactly past 32-job ring boundary", "root_cause_domain": "fw.cpm (ring buffer wrap)", "domain_relationship": "same-domain", "recommendation_accuracy": "medium — firmware log would show ring state but internal ring pointer may not be visible externally", "recommendation_rationale": "Ring wrap at 32 is a strong indicator; firmware team needed for internal trace.", "iteration_savings": "2"}
    },
    "14027176222": {
        "phase2_nga": {"test_name": "DSA command format validation", "command": "not available", "domain": "DSA descriptor command format", "parameters": "wrong command format submitted to DSA", "pass_fail_history": "not available", "artifacts": []},
        "phase3_verify": {"verified_problem_statement": "DSA test submits descriptor with incorrect command format. Test framework reports wrong command format error.", "verified_root_cause": "val.env.content — test script constructs DSA descriptor with incorrect opcode or command field layout. Content fix needed.", "verified_fix": "Update test script to use correct DSA command format per spec.", "architectural_element": "none (test content)", "failure_registers": ["dsa.swerror0"], "adjacent_subsystems": ["DSA command parser"]},
        "phase4_recommend": {"tier1": [{"category": "swerror_dump", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.swerror0.show()"], "reveals": "invalid operation code or descriptor format error", "relevance": "DSA reports format error in SWERROR0 operation field"}], "tier2": [], "tier3": [], "beyond_sme": []},
        "phase5_validate": {"how_testcase_encounters_defect": "direct — test submits malformed descriptor", "root_cause_domain": "val.env.content", "domain_relationship": "same-domain", "recommendation_accuracy": "high", "recommendation_rationale": "SWERROR0 operation field directly identifies invalid opcode.", "iteration_savings": "1"}
    },
    "14027163809": {
        "phase2_nga": {"test_name": "IAA + ADR Blockfill test", "command": "not available", "domain": "IAA Blockfill operation with ADR (Asynchronous DRAM Refresh)", "parameters": "DMR-UCC-X1 A0 PO silicon; Q7YL QDF", "pass_fail_history": "not available", "artifacts": []},
        "phase3_verify": {"verified_problem_statement": "IAA Blockfill test fails. Rejected — likely ADR interaction or test environment issue.", "verified_root_cause": "Unknown (rejected ticket). Possible ADR timing or IAA Blockfill descriptor edge case.", "verified_fix": "Rejected — not pursued.", "architectural_element": "IAA Blockfill engine, ADR subsystem", "failure_registers": [], "adjacent_subsystems": ["ADR", "IAA DMA engine"]},
        "phase4_recommend": {"tier1": [{"category": "swerror_dump", "commands": ["sv.socket0.imh0.acc.acc_0.iaa.swerror0.show()"], "reveals": "IAA error code for Blockfill failure", "relevance": "identifies descriptor-level failure cause"}, {"category": "register_dump", "commands": ["sv.socket0.imh0.acc.acc_0.iaa.gencap.show()"], "reveals": "IAA capability configuration", "relevance": "verify Blockfill is supported and enabled"}], "tier2": [], "tier3": [], "beyond_sme": []},
        "phase5_validate": {"how_testcase_encounters_defect": "direct — exercises IAA Blockfill with ADR", "root_cause_domain": "unknown (rejected)", "domain_relationship": "same-domain", "recommendation_accuracy": "medium", "recommendation_rationale": "swerror0 would identify descriptor failure; ADR interaction needs timing analysis.", "iteration_savings": "1"}
    },
    "14027158895": {
        "phase2_nga": {"test_name": "DSA/IAA DEFTR3/DEFTR22 register value verification", "command": "not available", "domain": "DSA/IAA default register value validation", "parameters": "DEFTR3 for DSA and IAA; DEFTR22 for DSA", "pass_fail_history": "not available", "artifacts": []},
        "phase3_verify": {"verified_problem_statement": "DSA DEFTR3 and IAA DEFTR3, plus DSA DEFTR22, show different values than specified in the hardware spec. May be a GNR→DMR delta not captured in test golden values.", "verified_root_cause": "val.env.content — test golden reference values are copied from GNR spec; DMR has different defaults. Test content needs update to use DMR-specific expected values.", "verified_fix": "Rejected — update test expected values from DMR HAS/register spec.", "architectural_element": "DSA/IAA DEFTR register file", "failure_registers": ["dsa.deftr3", "iaa.deftr3", "dsa.deftr22"], "adjacent_subsystems": []},
        "phase4_recommend": {"tier1": [{"category": "event_capabilities", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('deftr')", "sv.socket0.imh0.acc.acc_0.iaa.showsearch('deftr')"], "reveals": "actual DEFTR register values", "relevance": "compare against DMR spec defaults to identify delta"}], "tier2": [], "tier3": [], "beyond_sme": []},
        "phase5_validate": {"how_testcase_encounters_defect": "direct — compares register read against expected value from spec", "root_cause_domain": "val.env.content (wrong golden reference)", "domain_relationship": "same-domain", "recommendation_accuracy": "high — register dump immediately shows actual vs expected", "recommendation_rationale": "One register read resolves the issue.", "iteration_savings": "1"}
    },
    "16029922465": {
        "phase2_nga": {"test_name": "QAT TC/VC mapping verification", "command": "not available", "domain": "QAT PCIe TC-VC mapping configuration", "parameters": "VC0 TC/VC map: observed 0x7F instead of 0xFF; VC1: observed 0x80 instead of 0x00", "pass_fail_history": "not available", "artifacts": []},
        "phase3_verify": {"verified_problem_statement": "QAT device shows incorrect TC-VC mapping: VC0 TC map is 0x7F (TC0-6) instead of 0xFF (TC0-7), and VC1 has 0x80 instead of 0x00. This can cause traffic class 7 to be routed incorrectly.", "verified_root_cause": "Incorrect default value in QAT CPM TC-VC map register. Either a firmware initialization omission or a hardware default issue. Needs comparison against DMR QAT HAS spec.", "verified_fix": "Program correct TC-VC map via CPM register write; update firmware initialization sequence.", "architectural_element": "QAT CPM PCIe VC arbiter, TC-VC map register", "failure_registers": ["cpm.vcmap_vc0", "cpm.vcmap_vc1"], "adjacent_subsystems": ["PCIe root complex VC routing", "QAT firmware init"]},
        "phase4_recommend": {"tier1": [{"category": "register_dump", "commands": ["sv.socket0.imh0.acc.acc_0.cpm.showsearch('vc')", "sv.socket0.imh0.acc.acc_0.cpm.showsearch('tc')"], "reveals": "TC-VC mapping register values", "relevance": "directly shows the incorrect mapping"}, {"category": "firmware_log", "commands": ["sv.socket0.imh0.acc.acc_0.cpm.showsearch('fw')"], "reveals": "firmware initialization state", "relevance": "may show if TC-VC init was skipped"}], "tier2": [{"category": "pcie_aer", "commands": ["sv.socket0.imh0.acc.acc_0.cpm.ppaercs.show()"], "reveals": "any PCIe errors from TC7 mis-routing", "relevance": "shows downstream impact of wrong TC-VC map"}], "tier3": [], "beyond_sme": []},
        "phase5_validate": {"how_testcase_encounters_defect": "direct — reads and compares TC-VC register values", "root_cause_domain": "hw/fw QAT CPM TC-VC initialization", "domain_relationship": "same-domain", "recommendation_accuracy": "high — register dump directly shows the misconfiguration", "recommendation_rationale": "Single register read resolves. Firmware team needs to fix init sequence.", "iteration_savings": "2"}
    },
    "14027150648": {
        "phase2_nga": {"test_name": "val.env.configuration flexcon_hw_cxl/pcie (FDU3 gmzp301001s0096)", "command": "not available", "domain": "CXL/PCIe card presence validation", "parameters": "FDU3 node gmzp301001s0096", "pass_fail_history": "rejected", "artifacts": []},
        "phase3_verify": {"verified_problem_statement": "flexcon_hw_cxl fails with CXL_HW_UNEXPECTED_CHECK; flexcon_hw_pcie fails with Card_presence error on FDU3 node. Platform configuration mismatch.", "verified_root_cause": "val.env.configuration — CXL/PCIe card not present or seating issue on FDU3 node gmzp301001s0096; NGA platform profile mismatch. Rejected.", "verified_fix": "Verify physical card presence/seating on FDU3; update NGA platform profile.", "architectural_element": "none (platform config)", "failure_registers": [], "adjacent_subsystems": ["flexcon plugin", "NGA platform profile"]},
        "phase4_recommend": {"tier1": [{"category": "platform_topology", "commands": ["sv.socket0.imh0.bus1.show()"], "reveals": "actual CXL/PCIe device enumeration", "relevance": "shows whether device is present on the bus"}], "tier2": [], "tier3": [], "beyond_sme": []},
        "phase5_validate": {"how_testcase_encounters_defect": "direct — card presence check", "root_cause_domain": "val.env.configuration", "domain_relationship": "cross-domain", "recommendation_accuracy": "high", "recommendation_rationale": "Bus topology readout immediately confirms card absence.", "iteration_savings": "1"}
    },
    "14027150156": {
        "phase2_nga": {"test_name": "val.env.configuration flexcon_hw_cxl (FDU4)", "command": "not available", "domain": "CXL card presence validation (FDU4)", "parameters": "FDU4 nodes an004011bms1883 and ba00302ecos0023", "pass_fail_history": "rejected", "artifacts": []},
        "phase3_verify": {"verified_problem_statement": "flexcon_hw_cxl fails on FDU4 nodes — CXL card not present or misconfigured. Same pattern as 14027150648 on different FDU.", "verified_root_cause": "val.env.configuration — same infrastructure issue as 14027150648. Rejected.", "verified_fix": "Update NGA platform profile for FDU4 nodes.", "architectural_element": "none (platform config)", "failure_registers": [], "adjacent_subsystems": ["flexcon plugin", "NGA platform profile"]},
        "phase4_recommend": {"tier1": [{"category": "platform_topology", "commands": ["sv.socket0.imh0.bus1.show()"], "reveals": "CXL device present/absent", "relevance": "confirms card presence"}], "tier2": [], "tier3": [], "beyond_sme": []},
        "phase5_validate": {"how_testcase_encounters_defect": "direct", "root_cause_domain": "val.env.configuration", "domain_relationship": "cross-domain", "recommendation_accuracy": "high", "recommendation_rationale": "Platform topology resolves immediately.", "iteration_savings": "1"}
    },
    "14027134688": {
        "phase2_nga": {"test_name": "DSA/IAA poisoned memory operation (clone 1)", "command": "not available", "domain": "DSA/IAA DMA on DRAM-poisoned source", "parameters": "double-bit parity error injected", "pass_fail_history": "rejected (clone)", "artifacts": []},
        "phase3_verify": {"verified_problem_statement": "Clone of original sighting 14027098156 for poisoned memory incorrect behavior. Same RTL bug as 14027232974.", "verified_root_cause": "hw.iax RTL — data_poison SFI EOP signal captured one cycle early in accelerator sampling logic. Same as 14027232974.", "verified_fix": "RTL fix in hw.iax.", "architectural_element": "IAA SFI data_poison sampling logic", "failure_registers": ["iaa.swerror0"], "adjacent_subsystems": ["HIOP SFI", "DRAM MC"]},
        "phase4_recommend": {"tier1": [{"category": "swerror_dump", "commands": ["sv.socket0.imh0.acc.acc_0.iaa.swerror0.show()"], "reveals": "IAA error state on poisoned data access", "relevance": "shows whether poison was detected"}], "tier2": [], "tier3": [], "beyond_sme": []},
        "phase5_validate": {"how_testcase_encounters_defect": "direct", "root_cause_domain": "hw.iax RTL", "domain_relationship": "same-domain", "recommendation_accuracy": "medium", "recommendation_rationale": "Same as 14027232974.", "iteration_savings": "2"}
    },
    "14027116554": {
        "phase2_nga": {"test_name": "DSA/IAA poisoned memory operation (clone 2)", "command": "not available", "domain": "DSA/IAA DMA on DRAM-poisoned source", "parameters": "double-bit parity error injected", "pass_fail_history": "rejected (clone)", "artifacts": []},
        "phase3_verify": {"verified_problem_statement": "Second clone of 14027098156 poisoned memory sighting. Same RTL bug as 14027232974 and 14027134688.", "verified_root_cause": "hw.iax RTL — data_poison SFI EOP sampled one cycle early. Same as 14027232974.", "verified_fix": "RTL fix in hw.iax.", "architectural_element": "IAA SFI data_poison sampling logic", "failure_registers": ["iaa.swerror0"], "adjacent_subsystems": ["HIOP SFI", "DRAM MC"]},
        "phase4_recommend": {"tier1": [{"category": "swerror_dump", "commands": ["sv.socket0.imh0.acc.acc_0.iaa.swerror0.show()"], "reveals": "IAA error state", "relevance": "poison detection state"}], "tier2": [], "tier3": [], "beyond_sme": []},
        "phase5_validate": {"how_testcase_encounters_defect": "direct", "root_cause_domain": "hw.iax RTL", "domain_relationship": "same-domain", "recommendation_accuracy": "medium", "recommendation_rationale": "Same as 14027232974.", "iteration_savings": "2"}
    },
    "14027102637": {
        "phase2_nga": {"test_name": "IAA IOMMU BAR read — invalidation queue error", "command": "not available", "domain": "IAA IOMMU register BAR access", "parameters": "reading IOMMU Bar triggers invalidation queue error", "pass_fail_history": "rejected", "artifacts": []},
        "phase3_verify": {"verified_problem_statement": "IAA reading IOMMU BAR results in invalidation queue error. Indicates an IOMMU register access sequencing issue or misaligned BAR read from IAA.", "verified_root_cause": "hw.iax — IAA issues an IOMMU register read that triggers invalidation queue error. Rejected ticket, likely a test environment or configuration issue.", "verified_fix": "Rejected — not pursued.", "architectural_element": "IAA IOMMU interface, invalidation queue", "failure_registers": ["iaa.showsearch('inval')"], "adjacent_subsystems": ["IOMMU/VT-d invalidation queue", "IAA address translation"]},
        "phase4_recommend": {"tier1": [{"category": "vtd_context", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('inval')", "sv.socket0.imh0.bus0.showsearch('iommu')"], "reveals": "invalidation queue state at error", "relevance": "directly shows the queue error condition"}, {"category": "swerror_dump", "commands": ["sv.socket0.imh0.acc.acc_0.iaa.swerror0.show()"], "reveals": "IAA error code for the BAR access failure", "relevance": "shows IOMMU error response to IAA"}], "tier2": [], "tier3": [], "beyond_sme": []},
        "phase5_validate": {"how_testcase_encounters_defect": "direct — reads IOMMU BAR triggering the error", "root_cause_domain": "hw.iax / IOMMU", "domain_relationship": "adjacent", "recommendation_accuracy": "high", "recommendation_rationale": "vtd_context + swerror directly identify invalidation queue trigger.", "iteration_savings": "2"}
    },
    "14027093118": {
        "phase2_nga": {"test_name": "DSA Memory Move Batched operation", "command": "not available", "domain": "DSA Memory Move (Batched) descriptor", "parameters": "batch descriptor with Memory Move operations", "pass_fail_history": "complete", "artifacts": []},
        "phase3_verify": {"verified_problem_statement": "DSA Memory Move (Batched) operation fails with mismatch error. Destination data does not match source after batched operation.", "verified_root_cause": "val.env.content issue or hw.dsa batch descriptor handling. No root cause documented in HSD.", "verified_fix": "Pending investigation.", "architectural_element": "DSA batch descriptor processor, Memory Move engine", "failure_registers": ["dsa.swerror0", "dsa.swerror1"], "adjacent_subsystems": ["DSA batch engine", "DMA write path"]},
        "phase4_recommend": {"tier1": [{"category": "swerror_dump", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.swerror0.show()", "sv.socket0.imh0.acc.acc_0.dsa.swerror1.show()"], "reveals": "batch_index and error_info for failed descriptor in batch", "relevance": "swerror1 batch_index identifies which element in the batch failed"}, {"category": "descriptor_status", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('desc')"], "reveals": "completion records for each batch element", "relevance": "shows per-element result and status"}], "tier2": [{"category": "failvect_trace", "commands": ["grep -A5 'FAILVECT' test_output.log"], "reveals": "memory comparison of src vs dst for the failing element", "relevance": "mismatch type (error) suggests data was written incorrectly"}], "tier3": [], "beyond_sme": []},
        "phase5_validate": {"how_testcase_encounters_defect": "direct — batched Memory Move exercises the batch processor", "root_cause_domain": "hw.dsa batch engine or val.env.content", "domain_relationship": "same-domain", "recommendation_accuracy": "high — swerror batch_index + failvect exactly identifies which element and address failed", "recommendation_rationale": "batch_index in SWERROR1 + FAILVECT address is a complete diagnostic. Would resolve in one pass.", "iteration_savings": "3"}
    },
    "14027067691": {
        "phase2_nga": {"test_name": "DSA Mixed mode test with PASID disabled", "command": "not available (rocket/atlas based)", "domain": "DSA PASID mixed-mode operation", "parameters": "Mixed mode enabled, PASID set to No", "pass_fail_history": "complete", "artifacts": []},
        "phase3_verify": {"verified_problem_statement": "DSA Mixed mode test fails when PASID is set to No. Mixed mode operation with PASID disabled may violate DSA descriptor submission requirements.", "verified_root_cause": "val.env.content — test configuration enables mixed mode without PASID but DSA spec requires PASID for certain operations in mixed mode. No root cause documented.", "verified_fix": "Pending — may require test config fix or silicon investigation.", "architectural_element": "DSA WQ/PASID configuration, mixed mode arbiter", "failure_registers": ["dsa.wqcfg_0", "dsa.gencfg"], "adjacent_subsystems": ["PASID table", "DSA WQ"]},
        "phase4_recommend": {"tier1": [{"category": "wq_state", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.wqcfg_0.show()", "sv.socket0.imh0.acc.acc_0.dsa.gencfg.show()"], "reveals": "WQ mode (shared/dedicated/mixed) and PASID enable state", "relevance": "verifies mixed mode + PASID config is as expected"}, {"category": "swerror_dump", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.swerror0.show()"], "reveals": "error code for the failing descriptor", "relevance": "identifies whether failure is PASID-related or operation-related"}], "tier2": [], "tier3": [], "beyond_sme": []},
        "phase5_validate": {"how_testcase_encounters_defect": "direct — exercises DSA mixed mode with PASID disabled", "root_cause_domain": "val.env.content or hw.dsa PASID handling", "domain_relationship": "same-domain", "recommendation_accuracy": "high — wq_state + swerror0 immediately show mode config and error type", "recommendation_rationale": "WQ config + error code resolves in one pass.", "iteration_savings": "2"}
    },
    "14027067531": {
        "phase2_nga": {"test_name": "DSA perfmon counter verification", "command": "not available", "domain": "DSA performance monitoring counter accuracy", "parameters": "DSA operation workload + perfmon counter read", "pass_fail_history": "rejected", "artifacts": []},
        "phase3_verify": {"verified_problem_statement": "DSA perfmon counters show mismatch between expected and actual values. Counter values do not match the number of operations processed.", "verified_root_cause": "val.env.content — likely incorrect event configuration (cntrcfg) or wrong counter selected for the workload. No silicon bug identified. Rejected.", "verified_fix": "Rejected — update test to use correct cntrcfg event code for the operation being measured.", "architectural_element": "DSA perfmon counter units", "failure_registers": ["dsa.cntrcfg_0", "dsa.cntrdata_0"], "adjacent_subsystems": []},
        "phase4_recommend": {"tier1": [{"category": "perfmon_counters", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.cntrcfg_0.show()", "sv.socket0.imh0.acc.acc_0.dsa.cntrdata_0.show()"], "reveals": "configured event and counter value", "relevance": "directly shows if event code is correct for the workload"}], "tier2": [], "tier3": [], "beyond_sme": []},
        "phase5_validate": {"how_testcase_encounters_defect": "direct — reads perfmon counters after operation", "root_cause_domain": "val.env.content (wrong event config)", "domain_relationship": "same-domain", "recommendation_accuracy": "high — cntrcfg event code check resolves immediately", "recommendation_rationale": "One register read of cntrcfg confirms correct/incorrect event selection.", "iteration_savings": "1"}
    }
})

# ── Write responses ───────────────────────────────────────────────────────────
written = 0
skipped = 0
with open(RESPONSES_FILE, "a", encoding="utf-8") as f:
    for rec in records:
        hsd_id = rec["hsd_id"]
        if hsd_id in done_ids:
            skipped += 1
            continue
        if hsd_id not in BATCH:
            continue
        out = {
            "hsd_id": hsd_id,
            "parsed": rec["parsed"],
            "responses": BATCH[hsd_id]
        }
        f.write(json.dumps(out, ensure_ascii=False) + "\n")
        done_ids.add(hsd_id)
        print(f"  Written: {hsd_id}")
        written += 1

print(f"\nDone. Written={written}, Skipped={skipped}, Total processed={len(done_ids)}")
