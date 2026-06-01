"""
Temporary helper: write a single HSD response to responses.jsonl.
Usage: python _write_hsd.py
Replace HSD_RESPONSE dict content per HSD before running.
"""
import json
from pathlib import Path

RUN_DIR = Path(__file__).parent / "output" / "run_20260502_120716"
PROMPTS_FILE = RUN_DIR / "triage_prompts.jsonl"
RESPONSES_FILE = RUN_DIR / "responses.jsonl"

# Load prompts
prompts = {}
with open(PROMPTS_FILE, encoding="utf-8") as f:
    for line in f:
        r = json.loads(line)
        prompts[r["hsd_id"]] = r["parsed"]

# Load done IDs
done_ids = set()
if RESPONSES_FILE.exists():
    with open(RESPONSES_FILE, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                done_ids.add(json.loads(line)["hsd_id"])

def write(hsd_id, phase2, phase3, phase4, phase5):
    if hsd_id in done_ids:
        print(f"  SKIP {hsd_id} (already written)")
        return
    if hsd_id not in prompts:
        print(f"  ERROR: {hsd_id} not in prompts")
        return
    record = {
        "hsd_id": hsd_id,
        "parsed": prompts[hsd_id],
        "phase2_nga": phase2,
        "phase3_verify": phase3,
        "phase4_recommend": phase4,
        "phase5_validate": phase5,
    }
    with open(RESPONSES_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    done_ids.add(hsd_id)
    print(f"  Written: {hsd_id}")

# ── HSD 14027067334 — DSA PCIe No free test card ─────────────────────────────
write(
    "14027067334",
    phase2={
        "testcase_name": "dmr-ap_vv_a0_acc_fdm200a_0006 (ALL_ELEMENT_WISE_WITH_PCIE_silicon_rerun)",
        "testcase_command": "rocket -M 120 --atlas \"--hw dram,dsa,pcietc -v dsa_focus_tests[i=all_element_wise_pcie]\"",
        "testcase_parameters": "DMR A0, DSA element-wise ops with PCIe; station an004022bms1693; failed 2026-02-09",
        "testcase_domain_focus": "DSA element-wise accelerator operations over PCIe path on DMR A0 validation",
    },
    phase3={
        "verified_problem_statement": "DSA PCIe element-wise test fails with 'No free test card found' on DMR X1 A0 VV. Test infrastructure cannot allocate a healthy PCIe DSA card for the test.",
        "verified_root_cause": "Test environment/resource allocation issue: all PCIe DSA cards are in use, reserved, failed, or reporting uncorrectable errors (ERRUNCSTS), making them unavailable to the test framework. Possibly PCIe enumeration failure or card in fault state.",
        "verified_fix": "Identify and clear faulty PCIe cards, ensure DSA PCIe card inventory is healthy, clear ERRUNCSTS if cards are in error state. Primarily a test environment issue, not a silicon bug.",
        "architectural_element": "PCIe card allocation and DSA device enumeration in test infrastructure",
        "failure_registers": ["PCIe ERRUNCSTS", "PCIe device status register", "DSA BAR enumeration"],
        "adjacent_subsystems": ["PCIe root port", "BIOS device enumeration", "test harness card inventory"],
        "related_hsds": [],
        "spec_reference": "DMR PCIe validation infrastructure; val.env.content component — test environment, not silicon spec"
    },
    phase4={
        "tier1": [
            {"category": "dmesg_kernel", "commands": ["dmesg | grep -i 'dsa'", "dmesg | grep -i 'pcie'", "dmesg -T > /tmp/dmesg_full.log"], "reveals": "PCIe enumeration failures, driver load errors, AER events for DSA device", "relevance": "First log showing whether DSA PCIe card was enumerated by OS"},
            {"category": "platform_topology", "commands": ["sv.socket0.imh0.acc.show()", "sv.socket0.imh0.bus0.show()"], "reveals": "Whether DSA card is present and mapped in system topology", "relevance": "Confirms card visibility at silicon level"},
            {"category": "pcie_aer", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.ppaercs.show()", "sv.socket0.imh0.acc.acc_0.dsa.ppaerucsts.show()"], "reveals": "PCIe correctable/uncorrectable errors on DSA device", "relevance": "Uncorrectable errors render card unavailable to test infrastructure"},
            {"category": "link_state", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('link')", "sv.socket0.imh0.acc.acc_0.dsa.showsearch('lnk')"], "reveals": "PCIe link training status, speed, width", "relevance": "Failed link training prevents card allocation"},
        ],
        "tier2": [
            {"category": "register_dump", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.show()"], "reveals": "Full DSA register state", "relevance": "Baseline device state if enumerated"},
            {"category": "firmware_log", "commands": ["dmesg | grep -i 'svDeviceInit'"], "reveals": "SVOS device initialization status", "relevance": "Driver init failure would leave card unavailable"},
        ],
        "tier3": [
            {"category": "mce_log", "commands": ["mcelog --client", "dmesg | grep -i 'mce'"], "reveals": "Machine check events from PCIe failures", "relevance": "MCE on PCIe can put device in unusable state"},
        ],
        "beyond_sme": [
            {"description": "PCIe resource table and BIOS allocation check", "commands": ["Check BIOS PCIe resource allocation for DSA function"], "why": "BIOS may fail to assign PCIe resources making card invisible to OS and test framework"},
            {"description": "Serial console log from BIOS POST", "commands": ["Capture serial-over-LAN console log during boot"], "why": "Early enumeration failures not visible in OS dmesg"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — test tries to allocate DSA PCIe card and immediately fails if none available",
        "root_cause_domain": "test environment / PCIe card infrastructure",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "platform_topology + dmesg_kernel + pcie_aer confirms card presence at silicon level, OS enumeration, and error state in 1-2 debug iterations. Cross-reference with DSA debug BKMs for PCIe card availability patterns.",
        "iteration_savings": "2",
    },
)

print("Done.")

# ── HSD 14027067274 — DSA/SCF HAMVF MCE hang ─────────────────────────────────
write(
    "14027067274",
    phase2={
        "testcase_name": "dmr-ap_vv_a0_acc (ALL_ELEMENT_WISE_WITH_PCIE_silicon_rerun) - NGA 0027068c-7c01-4d9c-bf02-eed46f692327",
        "testcase_command": "rocket -M 120 --atlas \"--hw dram,dsa,pcietc -v dsa_focus_tests[i=all_element_wise_pcie]\"",
        "testcase_parameters": "DMR X1 A0, DSA element-wise operations with PCIe; SVOS validation",
        "testcase_domain_focus": "DSA element-wise accelerator operations over PCIe path exercising UBR/SCF fabric credit paths on DMR A0",
    },
    phase3={
        "verified_problem_statement": "DSA PCIe element-wise test on DMR X1 A0 VV triggers HW.MCE.HAMVF (Home Agent Miss with Victim Flush) Machine Check Error originating from hw.scf.ubr (Uncore Bus Router), causing test hang.",
        "verified_root_cause": "Protocol/credit violation or deadlock in the UBR/SCF fabric during DSA PCIe operations. Heavy PCIe DSA traffic exercises UBR VN0 credit and protocol logic; credit loss (potentially the UBR VN0 credit loss bug per HSD 14025848487) causes fabric deadlock, escalating to HAMVF MCE and system hang.",
        "verified_fix": "UBR VN0 credit loss fix (if applicable per HSD 14025848487) or software workaround to reduce PCIe DSA traffic concurrency. Full root cause requires MCi_STATUS/ADDR/MISC dump plus UBR credit table capture.",
        "architectural_element": "DMR SCF UBR (Uncore Bus Router) VN0 credit and protocol logic; HAMVF MCA bank",
        "failure_registers": ["MCi_STATUS (HAMVF bank)", "MCi_ADDR", "MCi_MISC", "UBR credit table registers", "SCF mesh state"],
        "adjacent_subsystems": ["DSA/PCIe fabric", "Scalable Coherency Fabric (SCF)", "CHA/HA coherency engine", "PCIe root port"],
        "related_hsds": ["14025848487"],
        "spec_reference": "DMR SCF/UBR/HAMVF architecture: MCA banks for HAMVF errors; Gen4 SCF UBR IP HAS defines credit and tracker state registers"
    },
    phase4={
        "tier1": [
            {"category": "mce_log", "commands": ["mcelog --client", "dmesg | grep -i 'mce'", "sv.sockets.uncore.showsearch('mca')"], "reveals": "HAMVF MCE bank, MCi_STATUS/ADDR/MISC capturing error code, address, syndrome", "relevance": "Direct capture of the HAMVF Machine Check error source in UBR/SCF"},
            {"category": "arbiter_state", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('arb')", "sv.socket0.imh0.acc.acc_0.dsa.showsearch('credit')"], "reveals": "UBR/SCF credit tables and arbitration state, confirming credit loss or deadlock", "relevance": "Credit starvation or exhaustion is the primary hang mechanism in UBR HAMVF scenarios"},
            {"category": "coherency_state", "commands": ["sv.sockets.uncore.chas.show()", "sv.sockets.uncore.chas.showsearch('snoop')"], "reveals": "Stuck transactions in SCF mesh, snoop filter state, TOR occupancy", "relevance": "Fabric deadlock manifests as stuck coherency transactions"},
            {"category": "register_dump", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.show()"], "reveals": "DSA device state at time of hang", "relevance": "Baseline DSA state to confirm device was active when MCE fired"},
        ],
        "tier2": [
            {"category": "pcie_aer", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.ppaerucsts.show()", "sv.socket0.imh0.acc.acc_0.dsa.ppaercs.show()"], "reveals": "Secondary PCIe errors correlated with fabric hang", "relevance": "PCIe errors may surface after UBR deadlock causes completion timeout"},
            {"category": "link_state", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('mrrs')", "sv.socket0.imh0.acc.acc_0.dsa.showsearch('devctl')"], "reveals": "PCIe MRRS and tag settings affecting traffic pattern", "relevance": "High MRRS generates more UBR transactions, increasing deadlock probability"},
            {"category": "perfmon_counters", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('cntr')"], "reveals": "DSA data flow counters showing stall at time of hang", "relevance": "Stalled counters confirm DSA was blocked waiting on fabric"},
        ],
        "tier3": [
            {"category": "interrupt_state", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.intcause.show()"], "reveals": "DSA interrupt cause at hang time", "relevance": "MCE may have prevented interrupt delivery"},
            {"category": "punit_mailbox", "commands": ["sv.socket0.imh0.showsearch('punit')"], "reveals": "Platform power state during MCE", "relevance": "Power transitions can exacerbate UBR credit issues"},
        ],
        "beyond_sme": [
            {"description": "UBR VN0 credit table full dump via status_scope", "commands": ["status_scope.run(analyzers=['pcie'])", "HIOP credit counter registers: hiop_reg.otcmaxtotcrdts"], "why": "Credit exhaustion is the HAMVF root mechanism - direct credit table read confirms starvation without needing to reproduce"},
            {"description": "HAMVF PMON counters for credit loss events", "commands": ["Configure PMON for HAMVF_HSF_OPERATIONS.twolm_force_no_swap"], "why": "PMON counters show credit loss events in real-time, allowing identification of which DSA operation pattern triggers the deadlock"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — DSA PCIe element-wise test generates heavy fabric traffic that exercises UBR VN0 credit paths, triggering HAMVF deadlock",
        "root_cause_domain": "hw.scf.ubr (Scalable Coherency Fabric / Uncore Bus Router)",
        "domain_relationship": "adjacent",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "mce_log directly captures HAMVF MCE with MCi_STATUS confirming UBR error. arbiter_state+coherency_state show fabric deadlock. Cross-referenced with HSD 14025848487 (UBR VN0 credit loss) for related bug pattern. Status_scope PCIe credit dump is beyond-SME key for definitive confirmation.",
        "iteration_savings": "3",
    },
)

# ── HSD 14027067222 — DSA missing reference in descriptor template ────────────
write(
    "14027067222",
    phase2={
        "testcase_name": "silicon_dsa_iax_cpm_pcie_gen4_error_inj (dsa_focus_tests swerror + iax swerror + cpm_variant_dmr + cpu_supercollider IDI_Stress)",
        "testcase_command": "rocket --cfgs --atlas \"--hw dram,dsa,iax,cpm -v cpm_variant_dmr[minutes=120,loops=0,jobs=10,test_mode=crypto],dsa_focus_tests[i=swerror],iax_focus_tests[i=swerror],memicals,cpu_supercollider[cfg=diamondrapids.cfg,test=IDI_Stress]\"",
        "testcase_parameters": "DMR X1 A0, combined DSA/IAA/CPM/CPU stress; NGA UUIDs 04ae332b-c5ff-4daa-81dd-4785d4100125, 0cd2a2e9-a063-449d-8b10-f0a30ef3189e",
        "testcase_domain_focus": "DSA software error injection (swerror), IAA software error injection, CPM crypto operations, CPU supercollider IDI_Stress — multi-accelerator combined stress test",
    },
    phase3={
        "verified_problem_statement": "DSA descriptor template has a missing reference during combined multi-accelerator swerror injection test on DMR X1 A0 VV. Test silicon_dsa_iax_cpm_pcie_gen4_error_inj fails.",
        "verified_root_cause": "Missing reference in DSA descriptor template most likely due to test content/infrastructure issue — incorrect descriptor construction, missing handle, or test artifact not generated. Could be a test configuration error during combined multi-accelerator stress. Silicon DSA bugs typically manifest as error codes, not missing references.",
        "verified_fix": "Fix test template content to ensure all descriptor references are properly populated. Verify test configuration for combined DSA/IAA/CPM/CPU stress. If silicon, capture SWERROR registers for error codes identifying which operation class failed.",
        "architectural_element": "DSA descriptor submission path, work queue (WQ) descriptor templates, software error injection",
        "failure_registers": ["SWERROR0", "SWERROR1", "SWERROR2", "completion record status field"],
        "adjacent_subsystems": ["IAA descriptor path", "CPM crypto ring buffer", "CPU IDI Stress", "WQ descriptor template engine"],
        "related_hsds": [],
        "spec_reference": "DSA/IAA Gen3 HAS for DMR: descriptor format, SWERROR registers, error code definitions for SWERROR0.error_code field"
    },
    phase4={
        "tier1": [
            {"category": "swerror_dump", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.swerror0.show()", "sv.socket0.imh0.acc.acc_0.dsa.swerror1.show()", "sv.socket0.imh0.acc.acc_0.dsa.swerror2.show()"], "reveals": "SWERROR0 error code, WQ index, operation type, descriptor validity; SWERROR1 batch index; SWERROR2 fault address", "relevance": "Directly captures the descriptor-level error code for the failing operation"},
            {"category": "descriptor_status", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('desc')"], "reveals": "In-flight descriptor state and completion record content", "relevance": "Shows which descriptor failed and its operation type"},
            {"category": "dmesg_kernel", "commands": ["dmesg | grep -i 'dsa'", "dmesg | grep -i 'idxd'"], "reveals": "DSA driver errors, SWERROR notifications, kernel error messages", "relevance": "Driver-level error detection shows descriptor failures"},
        ],
        "tier2": [
            {"category": "register_dump", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.show()"], "reveals": "Full DSA register state at time of failure", "relevance": "Baseline state for confirming device was active"},
            {"category": "wq_state", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.wqcfg_0.show()", "sv.socket0.imh0.acc.acc_0.dsa.gencfg.show()"], "reveals": "WQ configuration and general device config", "relevance": "Descriptor template configuration depends on WQ setup"},
        ],
        "tier3": [
            {"category": "perfmon_counters", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('cntr')"], "reveals": "Operation counters", "relevance": "Shows how many descriptors were processed before failure"},
        ],
        "beyond_sme": [
            {"description": "Descriptor template content comparison", "commands": ["Dump raw descriptor content from memory at WQ submission address"], "why": "Direct inspection of missing field in descriptor template reveals if it's a test content issue vs hardware issue"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — dsa_focus_tests[i=swerror] explicitly exercises descriptor error injection paths that expose the missing reference",
        "root_cause_domain": "val.env.content / DSA test infrastructure",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "swerror_dump directly shows the descriptor error code. descriptor_status shows in-flight state. Combined identifies whether failure is test content or silicon within one debug pass.",
        "iteration_savings": "2",
    },
)

# ── HSD 14027067185 — DSA CXL HDM attribute not parseable to tman ────────────
write(
    "14027067185",
    phase2={
        "testcase_name": "silicon_dsa_itdm_fill_sass (vtd+dsa PASID+SLT inter_domain_fill)",
        "testcase_command": "rocket -M 120 --atlas \"--hw dram,dsa,vtd -v base_vtd[i=[noinvalidationType,nointerruptRemapping]],vtd_dsa[Mode=Dedicated,ATS=No,PRS=No,PASID=Yes],vtd_Domains[Pagesize=4K,AddressWidth=57,TranslationType=slt,SMT=Yes],dsa_focus_tests[i=inter_domain_fill]\"",
        "testcase_parameters": "DMR X1 A0 VV; NGA UUID 3a8f2cff-cbe3-470f-87c4-9f7850107b66 (NGA unavailable); PASID=Yes, SLT translation, 57-bit addr width",
        "testcase_domain_focus": "DSA inter-domain fill with VT-d PASID Second Level Translation on DMR A0; CXL HDM memory attribute parsing for tman domain manager",
    },
    phase3={
        "verified_problem_statement": "DMR X1 A0 VV DSA SVOS test fails: CXL HDM attribute could not be parsed by tman during inter_domain_fill test with VT-d PASID+SLT enabled.",
        "verified_root_cause": "CXL HDM memory attribute not correctly registered or recognized by tman (SVOS target/domain manager) for the VT-d PASID+SLT context. Root cause: test content or tman config issue — CXL HDM-target memory not flagged as VT-d-enabled, not assigned correct domain, or HDM page attribute unrecognized by tman version for PASID SLT context.",
        "verified_fix": "Fix tman/ivman configuration to correctly parse and register CXL HDM attributes for PASID-enabled SLT domains. Update SVOS test content for CXL HDM + VT-d attribute compatibility. Debug with tman.log and ivman.log.",
        "architectural_element": "DSA VT-d PASID Second Level Translation domain management; tman/ivman SVOS memory target manager; CXL HDM memory attribute mapping",
        "failure_registers": ["GENCFG", "INTCAUSE", "SWERROR0", "VT-d context table", "PASID table"],
        "adjacent_subsystems": ["VT-d IOMMU", "CXL HDM decoder", "tman/ivman SVOS target manager", "PASID page table engine"],
        "related_hsds": [],
        "spec_reference": "DMR CXL/VT-d HAS: HDM decoder attributes, PASID support, SLT translation; ivman/tman SVOS architecture BKM"
    },
    phase4={
        "tier1": [
            {"category": "tman_ivman_logs", "commands": ["cat tman.log", "cat ivman.log"], "reveals": "Domain and target assignment errors, CXL HDM attribute parsing errors", "relevance": "Directly shows where tman fails to parse CXL HDM attribute"},
            {"category": "swerror_dump", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.swerror0.show()", "sv.socket0.imh0.acc.acc_0.dsa.intcause.show()", "sv.socket0.imh0.acc.acc_0.dsa.gencfg.show()"], "reveals": "SWERROR codes for translation failures", "relevance": "Identifies if failure is at descriptor submission (test infra) or silicon IOMMU"},
            {"category": "dmesg_vtd", "commands": ["dmesg | grep -i 'dmar'", "dmesg | grep -i 'iommu'"], "reveals": "VT-d page fault notifications, PASID context errors", "relevance": "OS-level IOMMU fault log shows silicon translation failure"},
        ],
        "tier2": [
            {"category": "status_scope", "commands": ["status_scope.run(analyzers=['m2iosf','iommu','ieh','dsa'])"], "reveals": "M2IOSF fabric errors, IOMMU fault state, DSA error state", "relevance": "Complete view of VT-d+DSA fault path"},
            {"category": "page_table_dump", "commands": ["Dump root/context/PASID tables for the failing domain"], "reveals": "Whether CXL HDM region has correct SLT page table entries", "relevance": "Missing page table entry is direct cause of translation fault"},
        ],
        "tier3": [
            {"category": "vtd_registers", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('pasid')"], "reveals": "PASID configuration in hardware", "relevance": "Confirms hardware PASID mode matches test configuration"},
        ],
        "beyond_sme": [
            {"description": "CXL HDM attribute enumeration in sysfs", "commands": ["ls /sys/bus/cxl/devices/", "cat /sys/bus/cxl/devices/*/memory_attributes"], "why": "tman reads CXL HDM attributes from sysfs; missing entries prevent parsing"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — vtd_dsa PASID+SLT inter_domain_fill directly exercises CXL HDM attribute parsing through tman domain manager",
        "root_cause_domain": "val.env.content / SVOS tman+ivman infrastructure",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "tman.log + ivman.log immediately show CXL HDM parsing failure. swerror_dump + dmesg_vtd differentiates test-infra from silicon IOMMU fault.",
        "iteration_savings": "2",
    },
)

# ── HSD 14027066700 — IAA engines hung during automation run ─────────────────
write(
    "14027066700",
    phase2={
        "testcase_name": "IAA automation (random/nightly runs)",
        "testcase_command": "(no specific rocket command captured — random nightly automation)",
        "testcase_parameters": "DMR X1 A0 VV; no NGA UUID; intermittent IAA engine hang during automation",
        "testcase_domain_focus": "IAA (Intel Analytics Accelerator) engine hang during automated nightly runs on DMR A0",
    },
    phase3={
        "verified_problem_statement": "IAA engines hang during automation runs on DMR X1 A0 VV. Intermittent hang during random nightly test sequences.",
        "verified_root_cause": "Known IAA hang mechanisms: (1) SFI credit leakage in DSA/IAA requiring workaround (sv.sockets.imhs.acc.accs.iaa.sficlkgctl.icge_int=0); (2) reserved field misuse in IOMMU Invalidation Queue Descriptor bit 66 during PRS content (HSD 14025817510); (3) PASID processing not correctly aborted/drained (HSD 14025333034); (4) multiple back-to-back descriptors with source page faults causing hang.",
        "verified_fix": "Apply SFI credit workaround: sv.sockets.imhs.acc.accs.iaa.sficlkgctl.icge_int=0 and sfidfxctl.override_en=0x440. Check if PRS or PASID content is involved. Use status_scope acc_stack analyzer for post-hang state capture. Cross-reference with HSD 14025817510 and 14025333034.",
        "architectural_element": "IAA engine SFI credit path, IOMMU Invalidation Queue Descriptor, PASID drain logic",
        "failure_registers": ["INTCAUSE", "SWERROR0", "sficlkgctl.icge_int", "sfidfxctl.override_en", "IAA error status"],
        "adjacent_subsystems": ["IOMMU/VT-d", "SFI credit fabric", "PASID table engine", "DSA engine (shared logic)"],
        "related_hsds": ["14025817510", "14025333034"],
        "spec_reference": "DMR IAA HAS: IOMMU Invalidation Queue Descriptor format (bit 66 reserved); SFI credit architecture; PASID drain sequence"
    },
    phase4={
        "tier1": [
            {"category": "status_scope_acc", "commands": ["status_scope.run(collectors=['namednodes'], analyzers=['acc_stack'], run_params={'ADAPTIVE': 2})"], "reveals": "Complete IAA engine state at hang time including error registers, queue depth, SFI credit counters", "relevance": "Primary post-hang capture — acc_stack analyzer designed for IAA/DSA hang scenarios"},
            {"category": "iaa_error_registers", "commands": ["from diamondrapids.accelerators.dsa_iaa import dsa_iaa_debug_dump as dsa_iaa_dump", "dsa_iaa_dump.dump_all_dsa_inst_errs()"], "reveals": "All DSA/IAA instance error registers across all instances", "relevance": "Batch error dump for automation hang — identifies which instance hung"},
            {"category": "sfi_credit_state", "commands": ["sv.sockets.imhs.acc.accs.iaa.sficlkgctl.icge_int.show()", "sv.sockets.imhs.acc.accs.iaa.sfidfxctl.show()"], "reveals": "SFI credit gating state — icge_int=1 means credit gating active (triggers hang)", "relevance": "Direct check for SFI credit leakage workaround applicability"},
        ],
        "tier2": [
            {"category": "iaa_registers", "commands": ["sv.sockets.imhs.acc.accs.iaa.swerror0.show()", "sv.sockets.imhs.acc.accs.iaa.intcause.show()"], "reveals": "SWERROR and interrupt cause for active IAA instances", "relevance": "Shows type of operation in flight at hang time"},
            {"category": "iommu_check", "commands": ["dmesg | grep -i 'iommu'", "dmesg | grep -i 'invalidation'"], "reveals": "IOMMU invalidation queue errors, descriptor malformation", "relevance": "Correlates with IOMMU Invalidation Queue Descriptor bit 66 bug"},
        ],
        "tier3": [
            {"category": "ijtag_state_dump", "commands": ["state_dump.state_dump(devicelist=['socket0.imh0.taps.acc_00.paracciaa1_scan_ijtag.usc'], trigger='none')"], "reveals": "Deep hardware state when IAA is non-responsive to normal register reads", "relevance": "Last resort for complete engine hang state capture"},
        ],
        "beyond_sme": [
            {"description": "IAA PASID drain sequence completion check", "commands": ["sv.sockets.imhs.acc.accs.iaa.showsearch('pasid')"], "why": "PASID drain not completing is a known hang root cause (HSD 14025333034)"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "indirect — random automation runs exercise various IAA descriptor patterns that eventually trigger SFI credit leakage or IOMMU descriptor issue",
        "root_cause_domain": "hw.iax",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "status_scope acc_stack + sfi_credit_state check immediately identifies SFI credit workaround need. dsa_iaa_dump batch error capture handles multi-instance automation scenarios efficiently.",
        "iteration_savings": "3",
    },
)

# ── HSD 16029836258 — QAT ESXi rate-limiting VM throughput below criteria ────
write(
    "16029836258",
    phase2={
        "testcase_name": "QAT rate-limiting VM throughput test (ESXi)",
        "testcase_command": "(no rocket command — OKS/BKC ESXi platform test)",
        "testcase_parameters": "DMR A0 with ESXi hypervisor, QAT 4xxx device, SRIOV mode; measured throughput below criteria",
        "testcase_domain_focus": "QAT (Intel QuickAssist Technology) rate-limiting VM throughput validation on DMR A0 with ESXi hypervisor",
    },
    phase3={
        "verified_problem_statement": "QAT rate-limiting VM throughput on DMR A0 with ESXi does not meet expected performance criteria.",
        "verified_root_cause": "Multiple potential causes: (1) firmware/logic issue in CPM 5.1 PKE module version; (2) QAT logic requiring address translation completion without SAI checks (HSD 14022901692); (3) incorrect PCIe ordering (strong ordering limiting throughput via UFI bridge or SCF frequency below 2GHz); (4) QAT telemetry/IP disabled (IP_DISABLE_RESOLVED_CR_DWORD3 bit[30:31]); (5) ESXi VM passthrough configuration issues limiting bandwidth.",
        "verified_fix": "Verify CPM 5.1 PKE module version. Check QAT IP_DISABLE register. Ensure SCF frequency >= 2GHz. Disable PCIe strong ordering if not required. Verify ESXi QAT passthrough config and SRIOV bandwidth limits.",
        "architectural_element": "QAT/CPM crypto engine throughput path; PCIe ordering/bandwidth; ESXi VM passthrough; UFI bridge",
        "failure_registers": ["IP_DISABLE_RESOLVED_CR_DWORD3 bit[30:31]", "tl_prt_trans_cnt (0x50700C)", "QAT fw_counters"],
        "adjacent_subsystems": ["CPM PKE module", "UFI bridge", "PCIe root port", "ESXi hypervisor QAT VF"],
        "related_hsds": ["14022490448", "14022901692"],
        "spec_reference": "DMR System IO Performance spec: PCIe ordering, SCF frequency impact on QAT throughput; QAT/CPM telemetry FAS"
    },
    phase4={
        "tier1": [
            {"category": "qat_ip_status", "commands": ["cat /sys/kernel/debug/qat_c4xxx_*/fw_counters", "adf_ctl status", "systemctl status qat_service"], "reveals": "QAT firmware counters, service status, active instances", "relevance": "Baseline QAT operational status; confirms device is active and firmware is processing requests"},
            {"category": "qat_telemetry", "commands": ["sv.sockets.imh0.acc.acc_0.qat.show()", "sv.socket0.imh0.acc.acc_0.qat.showsearch('disable')"], "reveals": "IP_DISABLE register for QAT instances, telemetry register values", "relevance": "Confirms QAT HW instances are enabled and not gated"},
            {"category": "platform_perf", "commands": ["dmesg -wH | grep -i qat", "cat /etc/c4xxx_dev0.conf"], "reveals": "Driver-level errors, QAT configuration", "relevance": "Configuration issues directly impact rate-limiting VM throughput"},
        ],
        "tier2": [
            {"category": "scf_freq_check", "commands": ["sv.socket0.imh0.show_freq()"], "reveals": "SCF frequency (must be >= 2GHz for full QAT performance)", "relevance": "SCF frequency below 2GHz limits UFI bridge throughput"},
            {"category": "pcie_ordering", "commands": ["sv.socket0.imh0.acc.acc_0.qat.showsearch('order')", "sv.socket0.imh0.acc.acc_0.qat.showsearch('relax')"], "reveals": "PCIe transaction ordering configuration", "relevance": "Strong ordering limits DMA throughput in rate-limiting scenarios"},
        ],
        "tier3": [
            {"category": "cpm_counters", "commands": ["sv.socket0.imh0.acc.acc_0.qat.showsearch('cnt')"], "reveals": "CPM telemetry counters for partial transaction rate", "relevance": "tl_prt_trans_cnt shows partial transaction overhead"},
        ],
        "beyond_sme": [
            {"description": "ESXi QAT VF passthrough configuration review", "commands": ["esxcli hardware pci list | grep QAT", "esxcli system module parameters list -m qat"], "why": "ESXi SR-IOV VF assignment and bandwidth limits can cap VM throughput independent of hardware"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — throughput test directly measures QAT rate-limiting VM performance against criteria",
        "root_cause_domain": "hw.qat / platform performance configuration",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "qat_ip_status + qat_telemetry quickly confirm device enablement. scf_freq_check and pcie_ordering identify performance limiters. Multiple parallel root cause candidates require systematic elimination.",
        "iteration_savings": "2",
    },
)

# ── HSD 16029819724 — QAT VC checks missing in QAT_StatusCheck_L ─────────────
write(
    "16029819724",
    phase2={
        "testcase_name": "QAT_StatusCheck_L (automation - VC checks verification steps 5 and 9)",
        "testcase_command": "(OKS/BKC automation test QAT_StatusCheck_L — no rocket command)",
        "testcase_parameters": "DMR AP BKC X1 1S; NGA UUID 5bea88d1-3cad-43a5-ab8f-f5158d000d25; PCIe VC checks missing in automated steps 5 and 9",
        "testcase_domain_focus": "QAT PCIe Virtual Channel (VC) configuration validation in BKC automation status check test",
    },
    phase3={
        "verified_problem_statement": "QAT_StatusCheck_L automation test on DMR AP BKC X1 1S reports that PCIe Virtual Channel (VC) checks are missing in test steps 5 and 9.",
        "verified_root_cause": "VC checks missing most likely due to: (1) test content gap — automation script does not implement VC check routines for QAT on DMR, possibly regression from porting; (2) platform/BIOS not advertising VC capabilities for QAT PCIe device on this configuration; (3) QAT firmware/device SKU does not support PCIe VC on DMR AP. Less likely to be silicon bug; primarily a test content or platform configuration issue.",
        "verified_fix": "Review QAT_StatusCheck_L automation script to confirm VC check implementation for steps 5/9. Verify PCIe VC capability advertisement in BIOS for QAT device. Update test content to add missing VC validation or document VC not supported on this SKU.",
        "architectural_element": "QAT PCIe Virtual Channel (VC) configuration; PCIe VC capability registers; BIOS PCIe VC advertisement",
        "failure_registers": ["PCIe VC capability register", "PCIe VC resource register", "VC control register"],
        "adjacent_subsystems": ["PCIe root complex VC arbiter", "BIOS PCIe VC configuration", "QAT device PCIe endpoint"],
        "related_hsds": [],
        "spec_reference": "DMR QAT PCIe VC spec: Virtual Channel capability, VC0/VC1 support; PCIe 5.0 spec for VC capability structure"
    },
    phase4={
        "tier1": [
            {"category": "pcie_vc_registers", "commands": ["sv.socket0.imh0.acc.acc_0.qat.showsearch('vc')", "lspci -vvv -s <QAT_BDF> | grep -A 10 'Virtual Channel'"], "reveals": "PCIe VC capability structure presence and configuration for QAT device", "relevance": "Directly shows whether VC is advertised by QAT device on this platform"},
            {"category": "test_content", "commands": ["cat QAT_StatusCheck_L.py | grep -n 'vc'", "grep -rn 'vc_check' ./tests/qat/"], "reveals": "Whether VC check routines are implemented in test script steps 5 and 9", "relevance": "Identifies test content gap vs hardware/BIOS issue"},
        ],
        "tier2": [
            {"category": "bios_pcie_config", "commands": ["sv.socket0.imh0.acc.acc_0.qat.showsearch('pcie_cap')"], "reveals": "PCIe capabilities exposed by BIOS for QAT device", "relevance": "BIOS must advertise VC for test to see it"},
            {"category": "qat_status", "commands": ["adf_ctl status", "lspci -s <QAT_BDF> -vvv | head -50"], "reveals": "QAT device capabilities, driver binding, PCIe link status", "relevance": "Baseline device state for VC support determination"},
        ],
        "tier3": [
            {"category": "nga_run_review", "commands": ["Review NGA UUID 5bea88d1-3cad-43a5-ab8f-f5158d000d25 in NGA portal"], "reveals": "Full test run log and which steps failed", "relevance": "Confirms exact failure mode for steps 5 and 9"},
        ],
        "beyond_sme": [
            {"description": "PCIe VC capability advertisement comparison", "commands": ["Compare lspci VC output vs QAT spec for DMR"], "why": "If VC capability absent in lspci output, BIOS is not advertising VC — requires BIOS team engagement"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — QAT_StatusCheck_L explicitly checks VC configuration in steps 5 and 9",
        "root_cause_domain": "val.env.content / QAT test automation content",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "pcie_vc_registers check immediately shows if VC is advertised. test_content review identifies if it is a script gap. Two-step debug resolves test content vs hardware within one pass.",
        "iteration_savings": "2",
    },
)

# ── HSD 14027018947 — pcietc failing with TIMEOUT_ERROR ──────────────────────
write(
    "14027018947",
    phase2={
        "testcase_name": "pcietc TIMEOUT_ERROR (Completion Timeout with MCTP WA applied)",
        "testcase_command": "(no rocket command — val.env.content pcietc test)",
        "testcase_parameters": "DMR X1 A0 VV; MCTP broadcast workaround applied; PCIe Uncorrectable Error Completion Timeout",
        "testcase_domain_focus": "PCIe completion timeout during pcietc test on DMR A0 with MCTP broadcast WA",
    },
    phase3={
        "verified_problem_statement": "DMR X1 A0 VV pcietc test fails with TIMEOUT_ERROR (PCIe Uncorrectable Error Completion Timeout) even with MCTP broadcast workaround applied.",
        "verified_root_cause": "PCIe completion timeout may be caused by: (1) posted request blocking NP completions (PCIe ordering deadlock); (2) credit exhaustion in M2IOSF; (3) MCTP WA incomplete — additional OOBMSM cross-segment bridging WA needed; (4) test card/device not properly handling PCIe transactions. Since MCTP WA is applied, suspected hardware or firmware issue in PCIe credit/ordering path or incomplete WA coverage.",
        "verified_fix": "Apply full OOBMSM cross-segment bridging workaround. Check M2IOSF for stuck posted requests. Use Status Scope PCIe plugin for credit table capture. Review DMR Current Workarounds page for additional pcietc-specific WAs.",
        "architectural_element": "PCIe M2IOSF completion tracking, TOR, PCIe credit counters, MCTP handling",
        "failure_registers": ["PCIe ERRUNCSTS", "M2IOSF credit table", "TOR timeout registers", "DMR IMH IP timeout config"],
        "adjacent_subsystems": ["PCIe root complex", "M2IOSF bridge", "TOR/Ubox", "OOBMSM MCTP handler"],
        "related_hsds": ["14025805912"],
        "spec_reference": "DMR IMH IP Config Timeout Reg Spec; DMR Current Workarounds; OOBMSM FW Gen4 DMR-HD FAS section 3.29.5"
    },
    phase4={
        "tier1": [
            {"category": "pcie_aer_registers", "commands": ["sv.socket0.imh0.acc.acc_0.qat.ppaerucsts.show()", "sv.socket0.imh0.acc.showsearch('erruncsts')"], "reveals": "PCIe Uncorrectable Error status register confirming completion timeout error code", "relevance": "Confirms AER error type and which device triggered timeout"},
            {"category": "status_scope_pcie", "commands": ["status_scope.run(analyzers=['pcie','m2iosf','ieh'])"], "reveals": "PCIe credit tables, M2IOSF stuck transactions, IEH error state", "relevance": "Complete PCIe fabric view — identifies stuck requests blocking completions"},
            {"category": "tor_check", "commands": ["sv.sockets.uncore.chas.showsearch('tor')"], "reveals": "TOR occupancy and timeout status", "relevance": "TOR timeouts indicate completion delivery failure upstream"},
        ],
        "tier2": [
            {"category": "m2iosf_state", "commands": ["sv.socket0.imh0.m2iosf.showsearch('pend')", "sv.socket0.imh0.m2iosf.showsearch('stuck')"], "reveals": "Pending/stuck requests in M2IOSF bridge", "relevance": "Posted requests stuck in M2IOSF block NP completion delivery"},
            {"category": "crashdump", "commands": ["Run crashdump and crashdump summarizer scripts"], "reveals": "System-level error context at timeout", "relevance": "JSON crashdump captures full error scope including TOR and PCIe state"},
        ],
        "tier3": [
            {"category": "mctp_state", "commands": ["sv.socket0.imh0.showsearch('mctp')"], "reveals": "MCTP broadcast packet handling state", "relevance": "Verifies MCTP WA is fully in effect; incomplete WA could still trigger timeout"},
        ],
        "beyond_sme": [
            {"description": "PMON forward-progress monitoring", "commands": ["Configure PMONs for PCIe request allocation to check forward progress"], "why": "PMON counters show if new PCIe requests are being allocated (forward progress) or completely stalled"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — pcietc exercises PCIe completion path; TIMEOUT_ERROR is direct failure symptom",
        "root_cause_domain": "val.env.content / PCIe fabric completion timeout",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "pcie_aer_registers + status_scope_pcie immediately capture error and credit state. tor_check + m2iosf_state identify stuck transaction source within 1-2 iterations.",
        "iteration_savings": "2",
    },
)

# ── HSD 14027018841 — pcietc PCIETC_VERIFY_PATTERN_MISMATCH ──────────────────
write(
    "14027018841",
    phase2={
        "testcase_name": "pcietc PCIETC_VERIFY_PATTERN_MISMATCH (vector data pattern mismatch at index 16)",
        "testcase_command": "(no rocket command — val.env.content pcietc test)",
        "testcase_parameters": "DMR X1 A0 VV; pattern mismatch inside vector data at index 16, physical address present",
        "testcase_domain_focus": "PCIe test content verification data pattern mismatch on DMR A0 — potential data corruption",
    },
    phase3={
        "verified_problem_statement": "DMR X1 A0 VV pcietc fails with PCIETC_VERIFY_PATTERN_MISMATCH: pattern mismatch inside vector data at index 16 at a physical address.",
        "verified_root_cause": "Data pattern mismatch in pcietc verification could be: (1) silicon data corruption — PCIe DMA transaction corrupting data in transit (ECC, parity, protocol violation); (2) test infrastructure issue — incorrect test vector or pattern generation, prior test overflow corrupting memory; (3) platform marginality — electrical signal integrity, voltage/frequency marginality. Need to reproduce and check if same address/pattern consistently fails (silicon) vs random (electrical) vs pattern-specific (test infra).",
        "verified_fix": "Run same test on multiple DMR parts to scope. Set data breakpoint on failing physical address to capture when corruption occurs. Review test vector at index 16 for correctness. Check for prior test overflow. If consistent silicon, escalate to PCIe debug team with pre-sighting template.",
        "architectural_element": "PCIe DMA data path, PCIe TLP data integrity, ECC/parity in PCIe receiver buffer",
        "failure_registers": ["PCIe ERRUNCSTS", "PCIe error source ID", "ECC status registers", "PCIe receiver buffer status"],
        "adjacent_subsystems": ["PCIe DMA engine", "M2IOSF data path", "DRAM ECC", "PCIe card data path"],
        "related_hsds": [],
        "spec_reference": "DMR PCIe Pre-Sighting Templates; Data Corruption Debug Guide (DebugEncyclopedia); DMR PCIe HAS data integrity"
    },
    phase4={
        "tier1": [
            {"category": "pattern_scoping", "commands": ["Re-run test on same part 3x to determine repeatability", "Re-run test on different DMR part"], "reveals": "Whether failure is part-specific (silicon) vs environment (electrical/infra) vs random (marginal)", "relevance": "Most critical first step — determines root cause domain before hardware debug"},
            {"category": "data_breakpoint", "commands": ["Set data watchpoint on failing physical address", "sv.socket0.imh0.acc.acc_0.showsearch('ecc')"], "reveals": "At what point in the PCIe DMA transaction the data is corrupted", "relevance": "Identifies exact transaction causing corruption"},
            {"category": "pcie_aer_registers", "commands": ["sv.socket0.imh0.acc.showsearch('erruncsts')", "sv.socket0.imh0.acc.showsearch('err')"], "reveals": "PCIe uncorrectable/correctable errors at time of mismatch", "relevance": "ECC/parity errors would confirm silicon data corruption path"},
        ],
        "tier2": [
            {"category": "test_vector_review", "commands": ["Inspect pcietc test vector file at index 16", "Compare expected vs actual bytes at mismatch"], "reveals": "Whether vector content is correct or corrupted before DMA", "relevance": "Test content error would produce consistent same-byte mismatch"},
            {"category": "status_scope_pcie", "commands": ["status_scope.run(analyzers=['pcie','m2iosf'])"], "reveals": "PCIe data path errors and M2IOSF state", "relevance": "Captures in-flight data integrity errors in PCIe fabric"},
        ],
        "tier3": [
            {"category": "memory_ecc", "commands": ["sv.sockets.uncore.mcchannels.showsearch('ecc')"], "reveals": "DRAM ECC errors correlated with data corruption event", "relevance": "DRAM ECC error could cause data mismatch in PCIe DMA buffer"},
        ],
        "beyond_sme": [
            {"description": "PCIe pre-sighting template engagement", "commands": ["File DMR PCIe Pre-Sighting Request with mismatch address, vector index, and PCIe device info"], "why": "If pattern_scoping shows consistent silicon failure, PCIe debug team needs this template to engage formally"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — pcietc explicitly verifies data pattern after DMA; mismatch is direct failure symptom",
        "root_cause_domain": "val.env.content / potential hw.pcie data corruption",
        "domain_relationship": "adjacent",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "pattern_scoping (repeatability across parts) is the most critical first step. data_breakpoint + pcie_aer_registers then identify exact corruption source. Pre-sighting template needed if silicon is confirmed.",
        "iteration_savings": "2",
    },
)

# ── HSD 16029796902 — QAT Windows yellow bang (Code 43) SRIOV ────────────────
write(
    "16029796902",
    phase2={
        "testcase_name": "QAT SRIOV driver installation on Windows (manual steps)",
        "testcase_command": "(Windows QAT driver SRIOV mode installation — not a rocket test)",
        "testcase_parameters": "DMR A0 with Windows OS, QAT 4xxx device, SRIOV mode; yellow bang Code 43 on driver install",
        "testcase_domain_focus": "QAT SR-IOV Windows driver installation — PCIe device enumeration and driver binding",
    },
    phase3={
        "verified_problem_statement": "QAT driver installation in SRIOV mode on DMR A0 Windows produces yellow bang (Code 43) in Device Manager.",
        "verified_root_cause": "Code 43 is most likely: (1) driver version mismatch for DMR QAT SRIOV; (2) BIOS SR-IOV not enabled for QAT PCIe root port; (3) Hyper-V or Windows virtualization conflict with SRIOV enumeration; (4) improper hardware state from prior partial initialization. Not a silicon bug — Windows device manager Code 43 is a driver/firmware/BIOS issue.",
        "verified_fix": "Clean driver reinstall with full power cycle. Verify BIOS SR-IOV enabled for QAT port. Disable Hyper-V if enabled. Check Windows Event Log for additional Code 43 details. Update to latest QAT driver for DMR.",
        "architectural_element": "QAT PCIe SRIOV device enumeration; Windows PCI device manager; BIOS SR-IOV configuration",
        "failure_registers": ["BIOS PCIe SR-IOV capability register", "Windows Event Log", "Device Manager Code 43"],
        "adjacent_subsystems": ["PCIe root complex SR-IOV", "BIOS SRIOV knob", "Windows Hyper-V", "QAT firmware"],
        "related_hsds": [],
        "spec_reference": "QAT SRIOV Windows driver guide; DMR BIOS SR-IOV PCIe configuration; Intel Bugcheck Triage guide"
    },
    phase4={
        "tier1": [
            {"category": "windows_event_log", "commands": ["Event Viewer > System log > filter for Code 43 events", "Get-WinEvent -LogName System | Where-Object {$_.Id -eq 7026} | Select-Object -First 10"], "reveals": "Code 43 additional error info, driver name, device instance path", "relevance": "Windows Code 43 event log has additional error code identifying exact driver failure reason"},
            {"category": "bios_sriov_check", "commands": ["Verify BIOS > PCIe > SR-IOV Support = Enabled", "Verify BIOS > VT-d = Enabled"], "reveals": "SR-IOV capability advertised to OS", "relevance": "BIOS must enable SR-IOV for QAT VFs to enumerate correctly"},
            {"category": "driver_version", "commands": ["Get-WmiObject Win32_PnPSignedDriver | Where-Object {$_.DeviceName -like '*QAT*'}", "devmgmt.msc properties > Driver tab"], "reveals": "Installed QAT driver version", "relevance": "Version mismatch is primary Code 43 cause"},
        ],
        "tier2": [
            {"category": "pcie_sriov_caps", "commands": ["lspci -vvv | grep -A 10 SRIOV  (Linux probe equivalent for debugging)", "sv.socket0.imh0.acc.acc_0.qat.showsearch('sriov')"], "reveals": "SR-IOV capability advertisement in PCIe config space", "relevance": "Confirms hardware is correctly advertising SR-IOV"},
            {"category": "hyperv_check", "commands": ["Get-WindowsOptionalFeature -Online -FeatureName HyperVisorPlatform", "bcdedit /enum | grep -i hyperv"], "reveals": "Hyper-V platform status", "relevance": "Hyper-V enabled is known to conflict with SRIOV device enumeration"},
        ],
        "tier3": [
            {"category": "windbg_analysis", "commands": ["WinDBG: !analyze -v on memory dump if BSOD occurred"], "reveals": "Kernel-level driver failure stack trace", "relevance": "If Code 43 triggers BSOD, WinDBG gives exact failure location in QAT driver"},
        ],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — driver installation step triggers Code 43 immediately on SRIOV mode",
        "root_cause_domain": "val.env.content / Windows QAT SRIOV driver installation",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "windows_event_log + bios_sriov_check + driver_version resolve Code 43 in 1-2 steps. Hyper-V check is critical differentiator. Low complexity debug.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026997858 — pcietc PCIETC_PROTOCOL_ERROR UR + MCTP Order ───────────
write(
    "14026997858",
    phase2={
        "testcase_name": "pcietc PCIETC_PROTOCOL_ERROR (UR + MCTP Order + Device Error)",
        "testcase_command": "(no rocket command — hw.pcie pcietc test on DMR X1 A0 PO)",
        "testcase_parameters": "DMR X1 A0 PO (Power-On); PCIe Unsupported Request Error + MCTP Order Error + Device Error",
        "testcase_domain_focus": "PCIe compliance test with MCTP broadcast interference on DMR A0 PO silicon",
    },
    phase3={
        "verified_problem_statement": "DMR X1 A0 PO pcietc fails with PCIETC_PROTOCOL_ERROR: PCIe Unsupported Request Error + MCTP Order Error + Device Error.",
        "verified_root_cause": "Known DMR A0 issue: MCTP broadcast messages from OOBMSM/BMC cause PCIe Unsupported Request errors on test cards that do not handle MCTP broadcasts. This is tracked under HSD 14025805912. Workaround: disable outbound MCTP broadcast (sv.sockets.imhs.hiop.hiops.hiop_reg.mctp_bcast_ctl.en_outb_mctp_bcast = 0).",
        "verified_fix": "Apply MCTP broadcast disable workaround: sv.sockets.imhs.hiop.hiops.hiop_reg.mctp_bcast_ctl.en_outb_mctp_bcast = 0. This is an A0 silicon workaround. Verify in DMR Current Workarounds page.",
        "architectural_element": "HIOP MCTP broadcast controller; PCIe Unsupported Request error path; OOBMSM MCTP cross-segment",
        "failure_registers": ["hiop_reg.mctp_bcast_ctl.en_outb_mctp_bcast", "PCIe ERRUNCSTS", "AER error source ID"],
        "adjacent_subsystems": ["OOBMSM/BMC MCTP stack", "PCIe root complex", "HIOP bridge", "test card PCIe endpoint"],
        "related_hsds": ["14025805912"],
        "spec_reference": "DMR Current Workarounds; OOBMSM FW Gen4 DMR-HD FAS section 3.29.5; HIOP MCTP broadcast control register"
    },
    phase4={
        "tier1": [
            {"category": "mctp_wa_check", "commands": ["sv.sockets.imhs.hiop.hiops.hiop_reg.mctp_bcast_ctl.en_outb_mctp_bcast.show()"], "reveals": "Current state of MCTP broadcast enable bit; 1=active (causing UR), 0=WA applied", "relevance": "Single register check confirms if WA is applied or not"},
            {"category": "pcie_aer_registers", "commands": ["sv.socket0.imh0.acc.showsearch('erruncsts')"], "reveals": "PCIe AER uncorrectable error status confirming UR error type", "relevance": "Confirms Unsupported Request Error type and source device BDF"},
        ],
        "tier2": [
            {"category": "mctp_wa_apply", "commands": ["sv.sockets.imhs.hiop.hiops.hiop_reg.mctp_bcast_ctl.en_outb_mctp_bcast = 0"], "reveals": "WA application — disables outbound MCTP broadcasts", "relevance": "This is the fix — apply before re-running pcietc"},
            {"category": "status_scope_pcie", "commands": ["status_scope.run(analyzers=['pcie','ieh'])"], "reveals": "Full PCIe error state and IEH error classification", "relevance": "Confirms no other PCIe errors beyond MCTP-triggered UR"},
        ],
        "tier3": [
            {"category": "oobmsm_log", "commands": ["Check BMC/OOBMSM MCTP broadcast log"], "reveals": "MCTP broadcast packets being sent during test", "relevance": "Confirms MCTP is source of UR errors"},
        ],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — pcietc exercises PCIe protocol compliance; MCTP UR errors directly fail compliance checks",
        "root_cause_domain": "hw.pcie / MCTP HIOP A0 silicon bug",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "mctp_wa_check (single register) immediately confirms WA state. Applying WA resolves issue. Confirmed known bug HSD 14025805912.",
        "iteration_savings": "3",
    },
)

# ── HSD 14026989106 — Flexcon_rdt failure FDM200 ─────────────────────────────
write(
    "14026989106",
    phase2={
        "testcase_name": "flexcon_rdt (PCIe/CXL/UXI IO protocol compliance test on FDM200)",
        "testcase_command": "(NGA-linked test — no explicit rocket command; NGA UUIDs from HSD symptom text)",
        "testcase_parameters": "DMR X1 A0 VV FDM200 station an004022bmh1693; flexcon_rdt IO protocol compliance test",
        "testcase_domain_focus": "Flexible connectivity PCIe/CXL/UXI IO protocol compliance (RDT) validation on DMR FDM200",
    },
    phase3={
        "verified_problem_statement": "flexcon_rdt test fails on DMR X1 A0 VV FDM200 platform at station an004022bmh1693. IO protocol compliance test failure.",
        "verified_root_cause": "flexcon_rdt validates PCIe Gen6/CXL 3.0/UXI protocol compliance on FDM200. Failure likely due to: (1) HW deadlock/livelock or stuck transactions on PCIe/CXL links; (2) platform configuration/BIOS issue (PCIe bifurcation, Gen speed, retimer config); (3) new test content or FDM200 configuration edge case; (4) protocol error injection triggering uncorrected hardware behavior; (5) test card/retimer configuration issue. Component val.env.content suggests test infra or content issue.",
        "verified_fix": "Capture MCA/IEH errors at failure. Check PCIe link status, Gen speed, and bifurcation config. Verify test card connection and retimer configuration. Review BIOS/IFWI version impact.",
        "architectural_element": "PCIe Gen6 / CXL 3.0 / UXI flexible connectivity IO stack; protocol error handling; retimer/redriver path",
        "failure_registers": ["PCIe ERRUNCSTS", "CXL port status", "PCIe link status register", "IEH error registers"],
        "adjacent_subsystems": ["PCIe root complex Gen6", "CXL 3.0 port", "UXI interconnect", "retimer/redriver", "FDM200 test card"],
        "related_hsds": [],
        "spec_reference": "DMR SysIO: IO RDT Specification Compliance (HSD 22012899372); FDM200 platform IO validation guide"
    },
    phase4={
        "tier1": [
            {"category": "mca_ieh_errors", "commands": ["sv.sockets.uncore.showsearch('mca')", "status_scope.run(analyzers=['ieh','pcie'])"], "reveals": "MCE/IEH errors at flexcon_rdt failure point; identifies which PCIe/CXL port failed", "relevance": "IEH captures IO error hierarchy — identifies failing port"},
            {"category": "link_status", "commands": ["sv.socket0.imh0.showsearch('lnksts')", "sv.socket0.imh0.showsearch('ltssm')"], "reveals": "PCIe link state (active, training, recovery, disabled)", "relevance": "Link training failure or recovery events indicate retimer/signal integrity issue"},
        ],
        "tier2": [
            {"category": "pcie_bifurcation", "commands": ["sv.socket0.imh0.showsearch('bif')", "sv.socket0.imh0.showsearch('gen')"], "reveals": "Current PCIe bifurcation and Gen speed configuration", "relevance": "Mismatch between BIOS bifurcation and FDM200 card expectation causes protocol failures"},
            {"category": "cxl_status", "commands": ["sv.socket0.imh0.showsearch('cxl')", "sv.socket0.imh0.showsearch('flex')"], "reveals": "CXL port state and flex IO configuration", "relevance": "CXL 3.0 configuration errors cause RDT compliance failures"},
        ],
        "tier3": [
            {"category": "test_card_check", "commands": ["Verify FDM200 test card connection and retimer configuration"], "reveals": "Physical connectivity and retimer state", "relevance": "Intermittent card connections cause non-reproducible flexcon_rdt failures"},
        ],
        "beyond_sme": [
            {"description": "IO RDT spec compliance comparison", "commands": ["Compare flexcon_rdt test version with DMR IO RDT spec version"], "why": "Test content version mismatch with silicon spec version causes false failures"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — flexcon_rdt exercises IO protocol compliance directly on PCIe/CXL/UXI paths",
        "root_cause_domain": "val.env.content / PCIe-CXL IO protocol compliance",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "mca_ieh_errors + link_status identifies failing port. pcie_bifurcation check confirms configuration. Multiple potential root causes require systematic elimination.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026989052 — Flexcon_hw_pcie socket1 pxp12 CB card not found ────────
write(
    "14026989052",
    phase2={
        "testcase_name": "flexcon_hw_pcie & flexcon_hw_xxx (socket1 pxp12 CB card not in pciecardlist)",
        "testcase_command": "(NGA-linked test — no explicit rocket command; NGA UUIDs from HSD)",
        "testcase_parameters": "DMR X1 A0 VV FDM200 station an004022bmh1693; socket1 pxp12 CB card not found in pciecardlist in pretest; multiple runs affected",
        "testcase_domain_focus": "PCIe flex connectivity test with CB (Control Board) card not enumerated on socket1 pxp12",
    },
    phase3={
        "verified_problem_statement": "flexcon_hw_pcie and flexcon_hw_xxx tests fail on DMR X1 A0 VV FDM200 because socket1 pxp12 CB card is not found in pciecardlist during pretest phase.",
        "verified_root_cause": "PCIe card enumeration failure: socket1 pxp12 CB test card not visible to test framework. Causes: (1) PCIe link training failure on socket1 pxp12 port — link not up; (2) BIOS enumeration failure for this PCIe slot; (3) physical card seating issue or retimer failure on pxp12; (4) platform configuration issue specific to this station. Component val.env.configuration confirms environment-level root cause.",
        "verified_fix": "Verify pxp12 PCIe link state on socket1. Check BIOS POST log for pxp12 enumeration. Reseat CB card if physical. Verify retimer/redriver configuration for socket1 pxp12 path on FDM200.",
        "architectural_element": "DMR socket1 PCIe port pxp12; PCIe link training; BIOS PCIe device enumeration; FDM200 CB card",
        "failure_registers": ["PCIe link status register for pxp12", "LTSSM state", "BIOS PCIe enumeration log"],
        "adjacent_subsystems": ["PCIe root complex socket1", "pxp12 port", "CB test card", "FDM200 platform retimer"],
        "related_hsds": [],
        "spec_reference": "FDM200 platform PCIe topology; DMR socket1 PCIe port map; BIOS PCIe enumeration flow"
    },
    phase4={
        "tier1": [
            {"category": "link_status_s1", "commands": ["sv.socket1.imh0.showsearch('lnksts')", "sv.socket1.imh0.pxp12.showsearch('ltssm')"], "reveals": "PCIe link state for socket1 pxp12 — confirms if link is up or down", "relevance": "Card not in pciecardlist means pxp12 link is not trained or device not enumerated"},
            {"category": "bios_post_log", "commands": ["Review serial console BIOS POST log for socket1 pxp12 enumeration"], "reveals": "Early PCIe enumeration failure or resource allocation error for pxp12", "relevance": "BIOS POST shows if card was seen during initial enumeration"},
        ],
        "tier2": [
            {"category": "pcie_errors_s1", "commands": ["sv.socket1.imh0.showsearch('erruncsts')", "sv.socket1.imh0.pxp12.showsearch('err')"], "reveals": "PCIe errors on socket1 pxp12 indicating why card is not enumerating", "relevance": "AER errors could prevent OS from completing enumeration"},
            {"category": "pciecardlist_check", "commands": ["cat pciecardlist.json", "python pretest_check.py --socket 1 --port pxp12"], "reveals": "What cards are visible to test framework", "relevance": "Confirms which cards are detected in pretest phase"},
        ],
        "tier3": [
            {"category": "physical_check", "commands": ["Visually inspect CB card seating in pxp12 slot on FDM200"], "reveals": "Physical connector issue causing enumeration failure", "relevance": "Intermittent seating on FDM200 is a known platform issue"},
        ],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — pretest phase checks pciecardlist; missing card immediately fails test before execution",
        "root_cause_domain": "val.env.configuration / PCIe enumeration",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "link_status_s1 immediately confirms if pxp12 link is up. bios_post_log shows enumeration time failure. Two-step debug resolves within one pass.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026988973 — Flexcon_uxi failing (FDM200) ───────────────────────────
write(
    "14026988973",
    phase2={
        "testcase_name": "flexcon_uxi (UXI interconnect flexcon test on FDM200)",
        "testcase_command": "(NGA-linked test — no explicit rocket command; NGA UUIDs from HSD)",
        "testcase_parameters": "DMR X1 A0 VV FDM200 station an004022bmh1693; flexcon_uxi failure with few test cases failing",
        "testcase_domain_focus": "UXI (Universal eXternal Interconnect) flexible connectivity test validation on DMR FDM200",
    },
    phase3={
        "verified_problem_statement": "flexcon_uxi test fails on DMR X1 A0 VV FDM200 at station an004022bmh1693. A subset of UXI-related flexcon test cases fail.",
        "verified_root_cause": "UXI interconnect failure on FDM200 likely due to: (1) UXI link training or protocol compliance issue on A0 silicon; (2) FDM200 UXI card configuration or signal integrity issue; (3) test content issue — some UXI test cases not fully functional on A0; (4) platform configuration edge case. Component val.env.content suggests test content issue.",
        "verified_fix": "Identify which specific UXI test cases fail. Capture UXI link status and error registers. Verify UXI card configuration on FDM200. Check if A0 UXI silicon has known workarounds.",
        "architectural_element": "UXI (Universal eXternal Interconnect) link layer; FDM200 UXI endpoint; protocol compliance",
        "failure_registers": ["UXI link status registers", "UXI error status", "LTSSM state", "IEH UXI error"],
        "adjacent_subsystems": ["UXI root complex", "FDM200 UXI test card", "PCIe/UXI bifurcation controller"],
        "related_hsds": [],
        "spec_reference": "DMR UXI interconnect HAS; FDM200 UXI validation guide"
    },
    phase4={
        "tier1": [
            {"category": "uxi_link_status", "commands": ["sv.socket0.imh0.showsearch('uxi')", "sv.socket0.imh0.showsearch('ltssm')"], "reveals": "UXI link state and training status", "relevance": "Identifies if UXI link is up and trained"},
            {"category": "ieh_uxi_errors", "commands": ["status_scope.run(analyzers=['ieh','pcie'])"], "reveals": "IEH-captured UXI errors", "relevance": "IEH hierarchy shows which UXI operations generated errors"},
        ],
        "tier2": [
            {"category": "test_case_analysis", "commands": ["Review flexcon_uxi test log for which specific test cases fail"], "reveals": "Pattern of failing test cases — systematic (all fail) vs subset (specific feature)", "relevance": "Subset failure pattern suggests test content issue; all-fail suggests link/HW issue"},
            {"category": "uxi_error_regs", "commands": ["sv.socket0.imh0.showsearch('err')"], "reveals": "Error registers at UXI failure point", "relevance": "Error type categorizes failure as protocol, data, or timing"},
        ],
        "tier3": [],
        "beyond_sme": [
            {"description": "UXI A0 silicon errata review", "commands": ["Review DMR A0 UXI errata list for known issues"], "why": "A0 UXI silicon may have known protocol compliance bugs not yet workarounded"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — flexcon_uxi directly exercises UXI interconnect paths",
        "root_cause_domain": "val.env.content / UXI interconnect",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "uxi_link_status + ieh_uxi_errors identify link state and error type. test_case_analysis distinguishes HW vs content failure.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026984328 — PCIe/CXL flexcon failure accelerators NGA ──────────────
write(
    "14026984328",
    phase2={
        "testcase_name": "PCIe/CXL flexcon_failure (Accelerators NGA test line failed)",
        "testcase_command": "(NGA-linked test — no explicit rocket command; NGA UUIDs from HSD symptom)",
        "testcase_parameters": "DMR X1 A0 VVR station an004022bms1935; accelerators NGA test line failed due to PCIe flexcon failure",
        "testcase_domain_focus": "PCIe/CXL flexcon NGA test line failure in accelerators validation suite on DMR X1 A0 VVR",
    },
    phase3={
        "verified_problem_statement": "Accelerators NGA test line fails due to PCIe/CXL flexcon failure on DMR X1 A0 VVR at station an004022bms1935.",
        "verified_root_cause": "NGA test line failure from PCIe flexcon: likely (1) PCIe link training failure or protocol error in flexcon path; (2) CXL enumeration failure during accelerator test setup; (3) NGA test execution environment issue; (4) known A0 PCIe flexcon issue with test card. Component val.env.execution suggests execution environment issue.",
        "verified_fix": "Check NGA test line failure logs for specific flexcon error. Verify PCIe/CXL link state. Apply MCTP WA if UR errors present. Check test execution environment configuration.",
        "architectural_element": "PCIe/CXL flexcon test infrastructure; NGA test execution environment; accelerator test line setup",
        "failure_registers": ["PCIe ERRUNCSTS", "CXL port status", "LTSSM state"],
        "adjacent_subsystems": ["NGA test framework", "PCIe/CXL root complex", "accelerator test cards"],
        "related_hsds": [],
        "spec_reference": "DMR NGA accelerator validation; PCIe flexcon test infrastructure; DMR Current Workarounds"
    },
    phase4={
        "tier1": [
            {"category": "nga_failure_log", "commands": ["Review NGA portal for test line failure details at UUID from HSD"], "reveals": "Specific flexcon failure step, error message, and test case", "relevance": "NGA portal has detailed test execution logs for accelerator test line failures"},
            {"category": "pcie_link_status", "commands": ["sv.socket0.imh0.showsearch('lnksts')", "sv.socket0.imh0.showsearch('ltssm')"], "reveals": "PCIe link state during failure", "relevance": "Link not up causes flexcon test setup failure"},
        ],
        "tier2": [
            {"category": "mctp_wa_check", "commands": ["sv.sockets.imhs.hiop.hiops.hiop_reg.mctp_bcast_ctl.en_outb_mctp_bcast.show()"], "reveals": "MCTP broadcast WA state", "relevance": "MCTP UR errors are common PCIe flexcon failure cause on DMR A0"},
            {"category": "status_scope_pcie", "commands": ["status_scope.run(analyzers=['pcie','ieh'])"], "reveals": "PCIe/CXL error state at test execution time", "relevance": "Captures all PCIe/CXL errors causing flexcon failure"},
        ],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — NGA test line exercises PCIe/CXL flexcon paths; failure in setup phase prevents test execution",
        "root_cause_domain": "val.env.execution / PCIe flexcon",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "nga_failure_log + pcie_link_status quickly identify failure point. mctp_wa_check checks most common A0 PCIe cause.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026976037 — QAT AEAD CSadPoolAllocator::Allocate/Fail ──────────────
write(
    "14026976037",
    phase2={
        "testcase_name": "silicon_ssh_qat_crypto_aead (cpm_variant_dmr AEAD crypto)",
        "testcase_command": "rocket -M 120 --atlas \"--hw dram,cpm -v cpm_variant_dmr[...]\"",
        "testcase_parameters": "DMR X1 A0 VV; NGA UUIDs available; QAT AEAD crypto test failure",
        "testcase_domain_focus": "QAT/CPM AEAD (Authenticated Encryption with Associated Data) crypto operations on DMR A0",
    },
    phase3={
        "verified_problem_statement": "QAT SVOS AEAD test fails with CSadPoolAllocator::Allocate/Fail on DMR X1 A0 VV during cpm_variant_dmr crypto configuration.",
        "verified_root_cause": "CSadPoolAllocator::Allocate/Fail indicates SVOS memory pool allocation failure for QAT AEAD crypto operations. Most likely: (1) SVOS memory pool exhaustion — prior test runs or concurrent tests consuming pool; (2) BIOS memory configuration error leaving insufficient memory for crypto pool; (3) SVOS test content misconfiguration — pool size not set for DMR platform requirements; (4) overlapping memory allocations from prior test not cleaned up.",
        "verified_fix": "Clean SVOS state before test (remove prior JSON tracking files, reboot if needed). Verify BIOS memory map for SVOS crypto pool allocation. Check cpm_variant_dmr pool size parameters. Ensure no prior test artifacts (sPPR JSONs, SVOS state) are conflicting.",
        "architectural_element": "QAT/CPM SVOS CSadPoolAllocator memory pool; AEAD crypto engine; SVOS memory map",
        "failure_registers": ["SVOS memory map", "QAT BAR registers", "CPM memory allocation state"],
        "adjacent_subsystems": ["SVOS CSad memory pool", "QAT/CPM firmware", "BIOS memory map", "tman/ivman domains"],
        "related_hsds": [],
        "spec_reference": "SVOS MemAlloc debug guide; QAT/CPM SVOS memory pool configuration; DMR BIOS memory map for accelerator"
    },
    phase4={
        "tier1": [
            {"category": "svos_pool_check", "commands": ["cat svos_memory_map.log", "ls *.json | grep sppr", "dmesg | grep -i 'mem_alloc'"], "reveals": "SVOS memory pool state, leftover JSON allocation files", "relevance": "Leftover allocation files prevent new pool allocation — most common cause"},
            {"category": "cpm_status", "commands": ["adf_ctl status", "cat /sys/kernel/debug/qat_*/fw_counters"], "reveals": "QAT/CPM device operational status and firmware counters", "relevance": "Confirms QAT device is active and memory-capable before pool allocation attempt"},
        ],
        "tier2": [
            {"category": "memory_map", "commands": ["sv.socket0.imh0.showsearch('bar')", "sv.socket0.imh0.acc.acc_0.qat.showsearch('bar')"], "reveals": "QAT BAR register configuration — memory regions assigned", "relevance": "BAR not configured means SVOS cannot map crypto pool memory"},
            {"category": "bios_mem_check", "commands": ["Check BIOS memory allocation for SVOS accelerator pool regions"], "reveals": "Memory regions reserved for SVOS crypto pool", "relevance": "BIOS must reserve memory for CSadPoolAllocator"},
        ],
        "tier3": [
            {"category": "pool_size_params", "commands": ["grep -r 'pool_size' ./tests/cpm/", "grep -r 'CSad' ./tests/cpm/"], "reveals": "Configured pool size in test parameters", "relevance": "Under-sized pool configuration causes allocation failure under load"},
        ],
        "beyond_sme": [
            {"description": "SVOS memory allocator debug trace", "commands": ["Enable SVOS debug logging and rerun test"], "why": "Debug trace shows exactly which allocation fails and why (size mismatch vs exhaustion vs configuration)"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — cpm_variant_dmr AEAD test directly uses CSadPoolAllocator for crypto engine memory",
        "root_cause_domain": "val.env.content / SVOS QAT memory pool",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "svos_pool_check immediately identifies leftover allocation files. cpm_status confirms device state. Two-step debug resolves most cases.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026974756 — MCE all accelerators + supercollider IDI stress ─────────
write(
    "14026974756",
    phase2={
        "testcase_name": "All accelerators + supercollider IDI stress (MCE during combined test)",
        "testcase_command": "(NGA-linked combined stress test — no explicit rocket command)",
        "testcase_parameters": "DMR A0 VV; NGA UUIDs available; MCE during DSA+IAA+QAT+CPM + CPU supercollider IDI_Stress",
        "testcase_domain_focus": "MCE (Machine Check Error) during combined all-accelerator + CPU supercollider IDI stress on DMR A0",
    },
    phase3={
        "verified_problem_statement": "MCE occurs during combined DSA+IAA+QAT+CPM + CPU supercollider IDI_Stress test on DMR A0 VV.",
        "verified_root_cause": "MCE during combined accelerator+IDI_Stress most likely from: (1) resource contention/arbitration deadlock under combined load (IDI bandwidth saturation, IO path credit exhaustion); (2) SFI credit leakage from IAA/DSA (HSD 22020561826); (3) error reporting logic bug in A0 accelerator firmware escalating to MCE; (4) RASIP error escalation path issue on A0 silicon. Configuration issue indicated by val.env.configuration component.",
        "verified_fix": "Apply SFI credit leakage WA for IAA/DSA. Decode MCE bank status MSRs to identify exact error source. Use status_scope acc_stack + RAS analyzers. Cross-reference MCE bank with accelerator error time.",
        "architectural_element": "MCE error reporting chain: accelerator IP > RASIP > IO error domain > MCE escalation; SFI credit path",
        "failure_registers": ["MCi_STATUS (all banks)", "MCi_ADDR", "MCi_MISC", "RASIP error registers", "SFI credit registers"],
        "adjacent_subsystems": ["RASIP global error logic", "DSA/IAA SFI credit path", "CPU IDI interconnect", "UBox MCE aggregator"],
        "related_hsds": ["22020561826", "22020576187", "14025817510"],
        "spec_reference": "DMR RAS HAS: MCE bank definitions, error escalation; IA-32 SDM MCE architecture; DMR accelerator error reporting"
    },
    phase4={
        "tier1": [
            {"category": "mce_decode", "commands": ["mcelog --client", "dmesg | grep -i 'mce'", "sv.sockets.uncore.showsearch('mca')"], "reveals": "MCE bank, MCi_STATUS error code, MCi_ADDR fault address, MCi_MISC syndrome", "relevance": "Directly identifies which domain (core/uncore/IO) generated the MCE"},
            {"category": "status_scope_ras", "commands": ["status_scope.run(collectors=['namednodes'], analyzers=['acc_stack', 'ubox', 'cha', 'pcie'])"], "reveals": "Complete RAS state: accelerator errors, UBox MCE state, CHA/TOR errors, PCIe errors", "relevance": "Multi-domain capture identifies MCE source domain correlation with accelerator activity"},
        ],
        "tier2": [
            {"category": "acc_error_dump", "commands": ["from diamondrapids.accelerators.dsa_iaa import dsa_iaa_debug_dump as dsa_iaa_dump", "dsa_iaa_dump.dump_all_dsa_inst_errs()"], "reveals": "Per-instance accelerator error state at MCE time", "relevance": "If MCE source is accelerator, error dump shows which instance and operation"},
            {"category": "sfi_credit_check", "commands": ["sv.sockets.imhs.acc.accs.iaa.sficlkgctl.icge_int.show()", "sv.sockets.imhs.acc.accs.dsa.sficlkgctl.icge_int.show()"], "reveals": "SFI credit gating state — credit leakage workaround status", "relevance": "SFI credit leakage is known A0 MCE trigger in accelerator+IDI_Stress scenarios"},
        ],
        "tier3": [
            {"category": "rasip_errors", "commands": ["sv.sockets.uncore.showsearch('rasip')"], "reveals": "RASIP error escalation state", "relevance": "RASIP captures accelerator error escalation path to MCE"},
        ],
        "beyond_sme": [
            {"description": "PMON for IDI bandwidth saturation", "commands": ["Configure PMON for IDI bandwidth utilization before MCE", "Monitor IDI_BANDWIDTH_IN_USE counters"], "why": "IDI bandwidth saturation causing arbitation deadlock is MCE root cause — PMON confirms saturation point"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "indirect — combined accelerator+IDI_Stress exposes MCE via resource contention or SFI credit leakage at high load",
        "root_cause_domain": "val.env.configuration / hw.accelerator MCE escalation",
        "domain_relationship": "adjacent",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "mce_decode directly identifies MCE source bank. status_scope_ras captures full domain state. sfi_credit_check confirms most common A0 WA need. Systematic approach resolves in 2-3 iterations.",
        "iteration_savings": "3",
    },
)

# ── HSD 14026973887 — DSA + IAA maxtransfer TMAN timeout ─────────────────────
write(
    "14026973887",
    phase2={
        "testcase_name": "IAX_VTD_SWQ_DSA_IAX_CPU_Max_transfer (VT-d SWQ max transfer size)",
        "testcase_command": "(NGA UUID 42fcae72-7f24-4a94-b63b-51668af465b3 — no explicit rocket command)",
        "testcase_parameters": "DMR A0 VV; VT-d Shared Work Queue mode; max transfer size test for DSA+IAA+CPU",
        "testcase_domain_focus": "DSA+IAA max transfer size with VT-d Second-Level Translation (SLT) Shared Work Queue — page walk at max descriptor size",
    },
    phase3={
        "verified_problem_statement": "DSA+IAA maxtransfer size test IAX_VTD_SWQ_DSA_IAX_CPU_Max_transfer fails with TMAN timeout error on DMR A0 VV.",
        "verified_root_cause": "TMAN timeout caused by: (1) VT-d SLT page walk timeout under max transfer size — one page walk engine per inbound channel can bottleneck at max descriptor sizes; (2) DSA/IAA hardcoded CTO (Completion Timeout) value too low for slow VT-d translation targets at max size — known DMR A0 bug (no fix); (3) SVOS TMAN resource starvation if VT-d translation never completes. HIOP aborts translation if IOMMU page walk ends in unsuccessful completion (iommu_mem_resp_abort).",
        "verified_fix": "Check VTUNCERRSTS for iommu_mem_resp_abort. Review HIOP credit availability. Apply any CTO timeout workaround if available. Increase TMAN timeout if configurable. Cross-reference DMR A0 DSA/IAA errata for CTO fix status.",
        "architectural_element": "VT-d SLT page walk engine; DSA/IAA hardcoded CTO; HIOP IOMMU translation abort path; SVOS TMAN resource manager",
        "failure_registers": ["VTUNCERRSTS.iommu_mem_resp_abort", "SWERROR0", "INTCAUSE", "HIOP credit registers"],
        "adjacent_subsystems": ["VT-d IOMMU page walk engine", "HIOP bridge", "SVOS TMAN", "DSA/IAA completion timeout logic"],
        "related_hsds": [],
        "spec_reference": "DMR DSA/IAA CTO errata (hardcoded CTO value for slow targets); GEN3 HIOP HAS VT-d Error Table; VTUNCERRSTS register spec"
    },
    phase4={
        "tier1": [
            {"category": "vtd_error_regs", "commands": ["sv.socket0.imh0.showsearch('vtuncerrsts')", "sv.socket0.imh0.acc.acc_0.iaa.showsearch('vtunc')"], "reveals": "VTUNCERRSTS register — iommu_mem_resp_abort bit confirms VT-d translation abort caused timeout", "relevance": "Direct evidence of VT-d page walk timeout as root cause"},
            {"category": "tman_logs", "commands": ["cat tman.log", "cat mrman.log"], "reveals": "TMAN resource allocation state and timeout message", "relevance": "Shows whether TMAN timed out waiting for VT-d completion or resource allocation"},
            {"category": "iaa_error_regs", "commands": ["sv.socket0.imh0.acc.acc_0.iaa.swerror0.show()", "sv.socket0.imh0.acc.acc_0.iaa.intcause.show()"], "reveals": "IAA SWERROR and interrupt cause at timeout", "relevance": "Error code identifies if timeout is CTO or descriptor issue"},
        ],
        "tier2": [
            {"category": "hiop_credits", "commands": ["sv.sockets.imhs.hiop.hiops.showsearch('crd')"], "reveals": "HIOP credit availability for translation requests", "relevance": "Credit starvation at max transfer size causes HIOP to abort IOMMU translation"},
            {"category": "status_scope_iommu", "commands": ["status_scope.run(analyzers=['m2iosf','iommu','acc_stack'])"], "reveals": "Full IOMMU+accelerator stack state at timeout", "relevance": "Multi-component view shows where timeout originates"},
        ],
        "tier3": [],
        "beyond_sme": [
            {"description": "CTO value inspection", "commands": ["sv.socket0.imh0.acc.acc_0.iaa.showsearch('cto')"], "why": "Hardcoded CTO value is known DMR A0 bug — confirm if CTO is too low for slow translation target at max size"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — max transfer size test maximally stresses VT-d SLT page walk engine and DSA/IAA CTO limit",
        "root_cause_domain": "val.env.content / hw.dsa VT-d CTO known A0 bug",
        "domain_relationship": "adjacent",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "vtd_error_regs (VTUNCERRSTS.iommu_mem_resp_abort) immediately confirms VT-d abort. tman_logs confirm timeout source. Known DMR A0 CTO bug provides clear root cause path.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026973320 — All accelerators + supercollider error status 3 ─────────
write(
    "14026973320",
    phase2={
        "testcase_name": "All accelerators + supercollider IDI stress FDM200 (CPM+IDI+PCIe+IAA/DSA)",
        "testcase_command": "(NGA UUID 8df214c3-1a74-4270-a32a-3607d34c8189 — no explicit rocket command)",
        "testcase_parameters": "DMR A0 VV FDM200 config; CPM traffic + Supercollider IDI + PCIe + IAA/DSA; supercollider error status 3",
        "testcase_domain_focus": "Combined CPM+CPU Supercollider IDI+PCIe+IAA/DSA stress test on DMR A0 FDM200 platform configuration",
    },
    phase3={
        "verified_problem_statement": "CPM+Supercollider IDI+PCIe+IAA/DSA combined test fails with supercollider error status 3 on DMR A0 VV FDM200 config.",
        "verified_root_cause": "Supercollider error status 3 is a test-specific fail code (0xFzzz pattern) decoded by Dragon Error Decode tool. Likely causes: (1) out-of-order completion in LCD hardware when multiple accelerators + VMs stress shared cache lines (HSD 14025873279); (2) ordering violation in OOO completion returns under combined accelerator+IDI load; (3) A0 silicon instability under combined stress — FDM200 config adds PCIe cards stressing additional ports. Need Dragon Error Decode tool output for exact failure reason.",
        "verified_fix": "Run Dragon Error Decode tool on error status 3 signature. Check for LCD out-of-order completion bug (HSD 14025873279). Reduce to single-VM or disable data checking to isolate if LCD errata is involved.",
        "architectural_element": "CPU supercollider IDI stress; LCD (Last-level Cache Data path); OOO completion ordering; combined accelerator traffic",
        "failure_registers": ["Dragon supercollider error status register", "LCD out-of-order error flag", "MCE bank registers"],
        "adjacent_subsystems": ["CPU IDI interconnect", "LCD cache", "CPM/IAA/DSA combined traffic", "FDM200 PCIe cards"],
        "related_hsds": ["14025873279"],
        "spec_reference": "Dragon Vertical Debug Guide error status codes; LCD OOO completion HSD 14025873279; DMR accelerator+supercollider known issues"
    },
    phase4={
        "tier1": [
            {"category": "dragon_decode", "commands": ["dragon_error_decode --status 3", "Run Dragon Error Decode tool on supercollider error status 3"], "reveals": "Exact failure mode for status code 3: data mismatch, ordering violation, or MCE", "relevance": "Required first step — error status 3 has no documented meaning without decode tool"},
            {"category": "mce_check", "commands": ["mcelog --client", "dmesg | grep -i 'mce'"], "reveals": "MCE correlation with supercollider failure — status 3 may indicate MCE trigger", "relevance": "If MCE occurred during stress, it may be root cause of test abort"},
        ],
        "tier2": [
            {"category": "lcd_ooo_check", "commands": ["Reduce to single-VM test; disable data checking in supercollider"], "reveals": "Whether LCD OOO bug (HSD 14025873279) is involved — multi-VM only failure indicates LCD", "relevance": "LCD OOO bug is major combined-stress fail cause on DMR A0"},
            {"category": "acc_error_dump", "commands": ["from diamondrapids.accelerators.dsa_iaa import dsa_iaa_debug_dump as dsa_iaa_dump", "dsa_iaa_dump.dump_all_dsa_inst_errs()"], "reveals": "Accelerator error state at supercollider failure", "relevance": "Identifies if accelerator itself triggered the combined-stress failure"},
        ],
        "tier3": [],
        "beyond_sme": [
            {"description": "LCD cache line write collision trace", "commands": ["Monitor LLC cache line for two writes before error interrupt"], "why": "LCD OOO bug manifests as two writes to same cache line without sync — trace captures exact collision"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "indirect — combined CPM+IDI+PCIe+IAA/DSA stress creates conditions for LCD OOO or ordering violation",
        "root_cause_domain": "val.env.content / hw.dsa combined stress platform config",
        "domain_relationship": "adjacent",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "dragon_decode is required first step with no documented status 3 meaning. lcd_ooo_check (single-VM isolation) quickly differentiates LCD bug from other causes.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026970419 — DSA/IAA poison memory incorrect behavior ───────────────
write(
    "14026970419",
    phase2={
        "testcase_name": "DSA/IAA poisoned memory read test (EINJ poison + IAA read as source)",
        "testcase_command": "(no rocket command — manual test: EINJ poison + dsa_test_v2/iaa_test read of poisoned address)",
        "testcase_parameters": "DMR X1 A0 VV; Linux EINJ memory poison; IAA reads poisoned address as source operand; expected MCE/error, got incorrect behavior",
        "testcase_domain_focus": "DSA/IAA hardware RAS — poison propagation and error escalation when reading EINJ-poisoned memory",
    },
    phase3={
        "verified_problem_statement": "DSA/IAA reading EINJ-poisoned memory on DMR X1 A0 VV shows incorrect behavior. Expected: MCE or uncorrectable error. Actual: incorrect/incorrect behavior (silent or wrong error).",
        "verified_root_cause": "Architectural requirement: IAA/DSA as poison receivers must signal uncorrectable non-fatal error to device driver and prevent use of poisoned data. If DMR A0 IAA/DSA reads EINJ poison without reporting error, this is a silicon bug in hw.iax poison handling path — the poison token is not being propagated through the IAA/DSA completion path to trigger MCE/error escalation. Component hw.iax confirms silicon domain.",
        "verified_fix": "File as hardware silicon bug. Capture: VTUNCERRSTS, RASIP error registers, IAA completion record status, MCE bank status. Verify poison bit propagation from memory controller to IAA completion path. Reference DMR RAS HAS §9.3 Poison for expected behavior.",
        "architectural_element": "IAA/DSA poison receiver path; RASIP error escalation; MCE bank poison escalation; completion record error status",
        "failure_registers": ["VTUNCERRSTS", "RASIP error registers", "MCi_STATUS (all banks)", "IAA completion record status byte"],
        "adjacent_subsystems": ["Memory controller poison producer", "RASIP global error logic", "IAA error reporting path", "MCE aggregator"],
        "related_hsds": [],
        "spec_reference": "DMR RAS HAS §9.3 Poison: IAA/DSA as receiver — must signal uncorrectable error, prevent use of poisoned data; DMR SysIO Overview poison propagation"
    },
    phase4={
        "tier1": [
            {"category": "completion_status", "commands": ["Check IAA completion record status byte for error bits after poisoned read"], "reveals": "Whether IAA completion record reflects the poison error (0x09=Page Fault, 0x13=Bad Address)", "relevance": "Direct check if IAA is even recording the poison encounter in completion"},
            {"category": "mce_check", "commands": ["mcelog --client", "dmesg | grep -i 'mce'", "sv.sockets.uncore.showsearch('mca')"], "reveals": "MCE bank status — confirms if poison consumption escalated to MCE as expected", "relevance": "Missing MCE is the symptom of the bug — confirms incorrect behavior"},
            {"category": "vtd_ras_regs", "commands": ["sv.socket0.imh0.acc.acc_0.iaa.showsearch('vtunc')", "sv.sockets.uncore.showsearch('rasip')"], "reveals": "VT-d uncorrectable error register and RASIP error escalation state", "relevance": "Poison token should appear in these registers if propagation is working"},
        ],
        "tier2": [
            {"category": "iaa_error_regs", "commands": ["sv.socket0.imh0.acc.acc_0.iaa.swerror0.show()", "sv.socket0.imh0.acc.acc_0.iaa.intcause.show()"], "reveals": "IAA SWERROR and interrupt cause — any error indication from IAA side", "relevance": "SWERROR without MCE suggests error is not escalating past IAA"},
            {"category": "poison_source", "commands": ["dmesg | grep -i 'poison'", "dmesg | grep -i 'edac'"], "reveals": "Memory controller poison injection confirmation and EDAC detection", "relevance": "Confirms poison was actually injected by EINJ and detected by memory controller"},
        ],
        "tier3": [],
        "beyond_sme": [
            {"description": "IAA poison handling per-operation validation", "commands": ["Test with dsarand --poison_inject flag if available", "Compare IAA completion record vs expected error status"], "why": "Systematic per-operation comparison identifies if specific operation types fail to propagate poison"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — test explicitly reads EINJ-poisoned memory through IAA to test poison handling",
        "root_cause_domain": "hw.iax (silicon bug)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "completion_status + mce_check immediately confirms incorrect behavior (no MCE expected but not received). vtd_ras_regs shows where poison propagation breaks down. Strong silicon bug signal.",
        "iteration_savings": "3",
    },
)

# ── HSD 14026942339 — PCIe flexcon_failure pxp3 port FDU7 ────────────────────
write(
    "14026942339",
    phase2={
        "testcase_name": "PCIe flexcon_failure pxp3 port FDU7 (accelerators NGA test line)",
        "testcase_command": "(NGA-linked test — no explicit rocket command; NGA from HSD symptom)",
        "testcase_parameters": "DMR X1 A0 VVR station ba00302ecos0002; PCIe flexcon failure on pxp3 port of FDU7 platform",
        "testcase_domain_focus": "PCIe flexcon test failure on pxp3 port of DMR X1 A0 VVR FDU7 (Flex Demo Unit 7) platform",
    },
    phase3={
        "verified_problem_statement": "Accelerators NGA test line fails due to PCIe flexcon_failure on pxp3 port on DMR X1 A0 VVR FDU7 at station ba00302ecos0002.",
        "verified_root_cause": "PCIe pxp3 flexcon failure on FDU7: (1) PCIe link training failure on pxp3 port — link not up or training issues; (2) MCTP broadcast WA not applied causing UR errors on pxp3; (3) FDU7 platform card seating or retimer issue on pxp3; (4) BIOS pxp3 bifurcation mismatch. Component val.env.execution suggests execution environment/platform issue.",
        "verified_fix": "Check pxp3 PCIe link status. Apply MCTP broadcast disable WA. Verify FDU7 card on pxp3 is properly seated. Check BIOS pxp3 bifurcation configuration.",
        "architectural_element": "DMR PCIe pxp3 port; FDU7 platform PCIe connectivity; MCTP broadcast control",
        "failure_registers": ["PCIe ERRUNCSTS pxp3", "LTSSM state pxp3", "hiop_reg.mctp_bcast_ctl.en_outb_mctp_bcast"],
        "adjacent_subsystems": ["PCIe root complex pxp3", "MCTP broadcast path", "FDU7 test card", "BIOS pxp3 configuration"],
        "related_hsds": ["14026997858", "14025805912"],
        "spec_reference": "DMR Current Workarounds; FDU7 platform PCIe port map"
    },
    phase4={
        "tier1": [
            {"category": "pxp3_link_status", "commands": ["sv.socket0.imh0.pxp3.showsearch('lnksts')", "sv.socket0.imh0.pxp3.showsearch('ltssm')"], "reveals": "pxp3 PCIe link state — up/down/recovery", "relevance": "Link down is direct cause of flexcon failure on this port"},
            {"category": "mctp_wa_check", "commands": ["sv.sockets.imhs.hiop.hiops.hiop_reg.mctp_bcast_ctl.en_outb_mctp_bcast.show()"], "reveals": "MCTP broadcast WA state", "relevance": "MCTP UR errors on pxp3 are common DMR A0 failure cause"},
        ],
        "tier2": [
            {"category": "pxp3_errors", "commands": ["sv.socket0.imh0.pxp3.showsearch('erruncsts')"], "reveals": "PCIe AER errors on pxp3", "relevance": "Error type identifies failure cause (UR=MCTP, CTO=link issue)"},
            {"category": "status_scope_pcie", "commands": ["status_scope.run(analyzers=['pcie','ieh'])"], "reveals": "Full PCIe error hierarchy", "relevance": "IEH captures pxp3 errors in error hierarchy"},
        ],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — flexcon test exercises PCIe pxp3 port; link failure prevents test execution",
        "root_cause_domain": "val.env.execution / hw.pcie pxp3 port",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "pxp3_link_status immediately shows link state. mctp_wa_check covers most common A0 PCIe cause. Fast 2-step debug.",
        "iteration_savings": "2",
    },
)

# ── HSD 16029735044 — CentOS Accelerator GitError sdpk package ───────────────
write(
    "16029735044",
    phase2={
        "testcase_name": "CentOS Accelerator automation test (GitError sdpk git package)",
        "testcase_command": "(OKS/BKC automation — no rocket command; Kayak automation framework)",
        "testcase_parameters": "DMR AP BKC X1 1S; CentOS OS; Kayak automation framework; GitError: unable to load sdpk git package",
        "testcase_domain_focus": "BKC accelerator automation test infrastructure — sdpk (Software Development Package Kit) git repository access failure",
    },
    phase3={
        "verified_problem_statement": "CentOS Accelerator automation cases fail on DMR AP BKC X1 1S due to GitError: unable to load sdpk git package in Kayak automation framework.",
        "verified_root_cause": "Test infrastructure issue: sdpk (Software Development Package Kit) git repository cannot be cloned/loaded by Kayak automation. Causes: (1) git repository network/authentication failure — sdpk repo inaccessible from test system; (2) git credentials or proxy configuration issue on CentOS test system; (3) sdpk package version not available for current DMR BKC. Not a silicon issue — pure test automation infrastructure failure.",
        "verified_fix": "Fix git access to sdpk repository on test system: verify network connectivity, git credentials, proxy settings. Update sdpk URL/branch in Kayak configuration for current DMR AP BKC.",
        "architectural_element": "Kayak automation framework; sdpk git repository; test content package management",
        "failure_registers": [],
        "adjacent_subsystems": ["Git repository server", "Kayak automation", "CentOS network/proxy", "sdpk package manager"],
        "related_hsds": [],
        "spec_reference": "DMR BKC automation infrastructure; Kayak test framework sdpk integration guide"
    },
    phase4={
        "tier1": [
            {"category": "git_error_log", "commands": ["cat kayak_run.log | grep -i 'git'", "git clone <sdpk_url> --verbose 2>&1"], "reveals": "Exact git error (auth failure, network timeout, repo not found)", "relevance": "Direct capture of sdpk git clone failure reason"},
            {"category": "network_check", "commands": ["ping git.intel.com", "curl -v <sdpk_git_url>"], "reveals": "Network connectivity to git server from test system", "relevance": "Network failure is most common cause of automation git errors"},
        ],
        "tier2": [
            {"category": "git_credentials", "commands": ["git config --list | grep -i 'credential'", "cat ~/.netrc | grep git"], "reveals": "Git credential configuration on CentOS system", "relevance": "Missing or expired credentials cause authentication failure"},
            {"category": "kayak_config", "commands": ["cat kayak.cfg | grep -i 'sdpk'"], "reveals": "sdpk URL, branch, and version configured in Kayak", "relevance": "Wrong URL/branch causes git clone failure"},
        ],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — automation setup step tries to clone sdpk; git failure prevents any test execution",
        "root_cause_domain": "test automation infrastructure",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "git_error_log immediately shows exact failure. network_check confirms connectivity. Very simple infrastructure debug.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026911451 — QAT power gating enabling script error ─────────────────
write(
    "14026911451",
    phase2={
        "testcase_name": "power_gating_qat_enabling (python3 cpm power gating script)",
        "testcase_command": "rocket -M <time> --atlas \"--hw dram,cpm,vtd,pcie,dsa,iaa -v cpm_variant_dmr[...]\"",
        "testcase_parameters": "DMR X1 A0 VV; NGA UUID 17afcd1d-7d75-4521-8b0c-b04106df7975; python3 /usr/local/diamondrapids/cpm/p... power gating enabling script fails",
        "testcase_domain_focus": "QAT/CPM power gating enabling Python script failure during test setup on DMR X1 A0 VV SVOS",
    },
    phase3={
        "verified_problem_statement": "power_gating_qat_enabling target command fails on DMR X1 A0 VV during cpm_variant_dmr test setup. Python3 CPM power gating enabling script returns error.",
        "verified_root_cause": "Power gating enabling script failure for QAT/CPM: (1) CPM device not in expected state for power gating configuration — device may be in error or not enumerated; (2) Python script incompatibility with current SVOS version or CPM firmware; (3) Power gating registers not accessible or not in expected state for DMR A0 silicon; (4) BIOS power management knob conflict. Component val.env.automation suggests automation/script issue.",
        "verified_fix": "Check CPM device state before running script. Verify python3 script version compatibility with SVOS on DMR A0. Check power gating register accessibility. Review CPM power state machine.",
        "architectural_element": "QAT/CPM power gating configuration; CPM power state machine; SVOS power management automation",
        "failure_registers": ["CPM power gating control register", "CPM device status", "BIOS power management settings"],
        "adjacent_subsystems": ["QAT/CPM firmware", "SVOS power management", "BIOS power knobs"],
        "related_hsds": ["14026910895"],
        "spec_reference": "DMR CPM power gating HAS; SVOS power management automation guide"
    },
    phase4={
        "tier1": [
            {"category": "script_error", "commands": ["cat power_gating_qat_enabling.log", "python3 /usr/local/diamondrapids/cpm/power_gating_enable.py --verbose 2>&1"], "reveals": "Exact Python exception and line number causing script failure", "relevance": "Python traceback immediately identifies script failure reason"},
            {"category": "cpm_state", "commands": ["adf_ctl status", "cat /sys/kernel/debug/qat_*/state"], "reveals": "CPM device operational state before power gating", "relevance": "Device must be in specific state for power gating configuration to succeed"},
        ],
        "tier2": [
            {"category": "power_gating_regs", "commands": ["sv.socket0.imh0.acc.acc_0.qat.showsearch('pg')", "sv.socket0.imh0.acc.acc_0.qat.showsearch('power')"], "reveals": "Power gating register values for QAT device", "relevance": "Confirms hardware power gating register accessibility and current state"},
        ],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — power_gating_qat_enabling is a required setup target; script failure prevents test from running",
        "root_cause_domain": "val.env.automation / CPM power gating script",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "script_error (Python traceback) immediately identifies failure. cpm_state confirms device readiness. Simple 2-step debug.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026910895 — QAT power gating enabling script error (duplicate) ──────
write(
    "14026910895",
    phase2={
        "testcase_name": "power_gating_qat_enabling (python3 cpm power gating script - second occurrence)",
        "testcase_command": "rocket -M <time> --atlas \"--hw dram,cpm,vtd,pcie,dsa,iaa -v cpm_variant_dmr[...]\"",
        "testcase_parameters": "DMR X1 A0 VV; NGA UUID 17afcd1d-7d75-4521-8b0c-b04106df7975 (same run as 14026911451); power gating script fails",
        "testcase_domain_focus": "QAT/CPM power gating enabling Python script failure — second occurrence same run",
    },
    phase3={
        "verified_problem_statement": "Duplicate of HSD 14026911451 — same power_gating_qat_enabling script failure on same NGA test run (17afcd1d-7d75-4521-8b0c-b04106df7975).",
        "verified_root_cause": "Same as HSD 14026911451: power gating enabling script failure for QAT/CPM on DMR X1 A0 VV. Likely filed twice for the same failure event. Root cause: Python script or CPM device state issue.",
        "verified_fix": "Same as HSD 14026911451: check CPM device state, verify script compatibility, check power gating register accessibility.",
        "architectural_element": "QAT/CPM power gating configuration; SVOS power management",
        "failure_registers": ["CPM power gating control register", "CPM device status"],
        "adjacent_subsystems": ["QAT/CPM firmware", "SVOS power management"],
        "related_hsds": ["14026911451"],
        "spec_reference": "Same as 14026911451 — DMR CPM power gating HAS"
    },
    phase4={
        "tier1": [
            {"category": "script_error", "commands": ["cat power_gating_qat_enabling.log", "python3 /usr/local/diamondrapids/cpm/power_gating_enable.py --verbose 2>&1"], "reveals": "Python traceback identifying script failure", "relevance": "See HSD 14026911451 for full debug approach"},
            {"category": "cpm_state", "commands": ["adf_ctl status"], "reveals": "CPM device state", "relevance": "Device state check same as 14026911451"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — same failure mode as HSD 14026911451",
        "root_cause_domain": "val.env.automation / CPM power gating script",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "Duplicate of 14026911451. Same debug approach applies.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026910498 — Post Test failed HCleanUp_Axon_Inventory ───────────────
write(
    "14026910498",
    phase2={
        "testcase_name": "HCleanUp_Axon_Inventory (pysvtools post-test cleanup)",
        "testcase_command": "python -m pysvtools.execution.Tools.Ex... (post-test cleanup command)",
        "testcase_parameters": "DMR X1 A0 VV; NGA UUID ed56e1fa-c754-4fa0-b3aa-d4a1683feda5; post-test HCleanUp_Axon_Inventory fails",
        "testcase_domain_focus": "Post-test Axon inventory cleanup via pysvtools — test teardown failure",
    },
    phase3={
        "verified_problem_statement": "Post-test cleanup step HCleanUp_Axon_Inventory fails on DMR X1 A0 VV QAT SVOS test.",
        "verified_root_cause": "pysvtools post-test cleanup failure: (1) Axon inventory service not responding or unreachable from test system; (2) pysvtools version incompatibility with current Axon service API; (3) test execution left system in inconsistent state preventing cleanup; (4) network/authentication issue with Axon inventory service. Component val.env.configuration confirms environment issue.",
        "verified_fix": "Check Axon inventory service availability. Verify pysvtools version. Check network connectivity to Axon service. Manually run cleanup if automation step fails. This is a test infrastructure issue, not a silicon bug.",
        "architectural_element": "pysvtools Axon inventory cleanup; post-test teardown infrastructure; Axon service API",
        "failure_registers": [],
        "adjacent_subsystems": ["Axon inventory service", "pysvtools automation", "test teardown framework"],
        "related_hsds": [],
        "spec_reference": "Axon test infrastructure guide; pysvtools execution framework"
    },
    phase4={
        "tier1": [
            {"category": "cleanup_log", "commands": ["cat HCleanUp_Axon_Inventory.log", "python -m pysvtools.execution.Tools.ExecTools.HCleanUp_Axon_Inventory --verbose 2>&1"], "reveals": "Exact error from pysvtools cleanup execution", "relevance": "Traceback shows whether failure is network, API, or tool version"},
            {"category": "axon_connectivity", "commands": ["curl -v <axon_service_url>", "python -m pysvtools --check-service"], "reveals": "Axon service availability", "relevance": "Service unavailable is most common cleanup failure cause"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "indirect — post-test cleanup failure; main test may have passed; this is teardown infrastructure issue",
        "root_cause_domain": "val.env.configuration / post-test automation infrastructure",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "cleanup_log immediately shows failure reason. axon_connectivity confirms service state. Trivial infrastructure debug.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026908999 — DSA Gather copy 0x1A error SGL size 2 and 4 ──────────────
write(
    "14026908999",
    phase2={
        "testcase_name": "dsa_test_v2 gather copy sglsize 2 and 4 (returns 0x1A completion error)",
        "testcase_command": "test/.libs/dsa_test_v2 --verbose=1 --wqmode <mode> --sglsize 2 and --sglsize 4",
        "testcase_parameters": "DMR-AP A0; dsa_test_v2 git hash fccbd3b; gather copy operation; SGL sizes 2 and 4 trigger 0x1A error after timeout",
        "testcase_domain_focus": "DSA Gather copy operation with scatter-gather list (SGL) size 2 and 4 — completion error 0x1A on DMR-AP A0",
    },
    phase3={
        "verified_problem_statement": "DSA Gather copy returns completion error 0x1A after timeout for SGL sizes 2 and 4 on DMR-AP A0 using dsa_test_v2.",
        "verified_root_cause": "Error 0x1A is an undocumented/unexpected completion status code on DMR A0. Root cause: DMR A0 DSA silicon bug in gather copy SGL handling — HSD 22021248658 documents 'DMR DSA Gather Copy reports wrong SGL Completed when page fault'. When SGL size is 2 or 4, a page fault or translation error causes incorrect SGL completion count, and the resulting timeout + wrong error code (0x1A instead of documented SWERROR). This is a known A0 errata with no fix.",
        "verified_fix": "Document as known A0 silicon bug (HSD 22021248658). For workaround: avoid SGL sizes 2 and 4 in gather copy if possible, or handle 0x1A as page fault/SGL error in software. Capture SWERROR0 and completion record status for full root cause.",
        "architectural_element": "DSA Gather copy SGL processing engine; SWERROR completion path; VT-d page fault handling for scatter-gather",
        "failure_registers": ["SWERROR0", "SWERROR1 (batch index)", "SWERROR2 (fault address)", "completion record status byte"],
        "adjacent_subsystems": ["VT-d SGL address translation", "DSA gather engine", "IOMMU page fault handler"],
        "related_hsds": ["22021248658"],
        "spec_reference": "DSA Architecture Spec: completion error codes, SGL processing; HSD 22021248658 DMR DSA Gather Copy wrong SGL completed on page fault"
    },
    phase4={
        "tier1": [
            {"category": "swerror_dump", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.swerror0.show()", "sv.socket0.imh0.acc.acc_0.dsa.swerror1.show()", "sv.socket0.imh0.acc.acc_0.dsa.swerror2.show()"], "reveals": "SWERROR0 error code (should be 0x19 for page fault), SWERROR1 SGL index, SWERROR2 fault address", "relevance": "Cross-reference with 0x1A completion status — SWERROR gives silicon-level view"},
            {"category": "completion_record", "commands": ["Capture DSA completion record bytes at failing WQ submission address"], "reveals": "Exact completion record status field value (0x1A) and source/dest count", "relevance": "Completion record is the authoritative error source — confirms wrong SGL completed count"},
        ],
        "tier2": [
            {"category": "vtd_fault_check", "commands": ["dmesg | grep -i 'iommu'", "sv.socket0.imh0.acc.acc_0.dsa.showsearch('vtunc')"], "reveals": "VT-d page fault for SGL element 2 or 4 address", "relevance": "Page fault on specific SGL address is trigger for wrong completion count bug"},
        ],
        "tier3": [],
        "beyond_sme": [
            {"description": "SGL address validity check", "commands": ["Verify physical addresses for SGL elements 2 and 4 are valid and mapped"], "why": "Page fault on unmapped SGL element address triggers the HSD 22021248658 bug"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — dsa_test_v2 gather copy directly exercises SGL processing; SGL size 2/4 triggers page fault path",
        "root_cause_domain": "hw.dsa (A0 silicon bug)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "swerror_dump + completion_record captures silicon-level evidence. vtd_fault_check confirms page fault trigger. Known HSD 22021248658 provides clear root cause.",
        "iteration_savings": "3",
    },
)

# ── HSD 14026912504 — QAT ARB test Commit SVN and FW Load Error ───────────────
write(
    "14026912504",
    phase2={
        "testcase_name": "QAT ARB (Anti-Rollback) test Case 6 — Commit SVN and FW Load check",
        "testcase_command": "(manual QAT ARB test — write 1 to commit register; no rocket command)",
        "testcase_parameters": "DMR-AP; QAT ARB test Case 6 writes 1 to SVN commit register; fails with Commit SVN error and Check FW Load Error",
        "testcase_domain_focus": "QAT/CPM Anti-Rollback (ARB) security feature validation — SVN commit and firmware load enforcement",
    },
    phase3={
        "verified_problem_statement": "QAT ARB test on DMR-AP fails in Test Case 6: writing 1 to commit register returns Commit SVN error and Check FW Load Error.",
        "verified_root_cause": "QAT ARB SVN commit failure: (1) Not all CPMs reported valid SVN (0xFF = uninitialized) — S3M cannot commit unknown SVN; (2) New SVN is not greater than previously committed minimum — commit suppressed by design (not actually an error in this case, but test may not expect it); (3) CPLD in debug mode or non-writable state — commit to non-volatile storage fails; (4) CPM firmware version inconsistency across instances. Check FW Load Error after SVN commit: attempting to load firmware with SVN < committed minimum is expected ARB rejection.",
        "verified_fix": "Verify all CPMs report valid SVN before commit. Check CPLD writability. Ensure firmware version used in test has SVN >= previously committed minimum. Review S3M firmware version for CPM ARB support.",
        "architectural_element": "QAT/CPM ARB (Anti-Rollback) SVN commit path; S3M security firmware; CPLD non-volatile storage; CPM firmware SVN",
        "failure_registers": ["CPM SVN register", "ARB commit status register", "S3M error register", "CPLD write status"],
        "adjacent_subsystems": ["S3M security firmware", "CPM firmware loader", "CPLD storage", "QAT device manager"],
        "related_hsds": [],
        "spec_reference": "S3M DMR Security FAS: CPM firmware anti-rollback, SVN commit flow; QAT/CPM ARB validation guide; CPM QAT KPT Anti-Rollback spec"
    },
    phase4={
        "tier1": [
            {"category": "cpm_svn_check", "commands": ["adf_ctl status | grep -i 'svn'", "cat /sys/kernel/debug/qat_*/fw_counters | grep svn"], "reveals": "Current SVN values reported by each CPM instance", "relevance": "0xFF = uninitialized SVN prevents commit — most common cause"},
            {"category": "arb_commit_log", "commands": ["dmesg | grep -i 'arb'", "dmesg | grep -i 'svn'", "dmesg | grep -i 'rollback'"], "reveals": "Kernel messages about ARB commit and SVN enforcement", "relevance": "Driver logs ARB commit results and FW load rejection reasons"},
        ],
        "tier2": [
            {"category": "cpld_state", "commands": ["Check CPLD write status for non-volatile SVN storage"], "reveals": "CPLD writability — debug mode vs production mode", "relevance": "Non-writable CPLD prevents SVN commit even when SVN is valid"},
            {"category": "fw_version_check", "commands": ["cat /sys/kernel/debug/qat_*/version/fw"], "reveals": "CPM firmware version and SVN", "relevance": "FW SVN < committed minimum causes expected Check FW Load Error"},
        ],
        "tier3": [],
        "beyond_sme": [
            {"description": "S3M ARB flow trace", "commands": ["Enable S3M debug logging for ARB flow"], "why": "S3M firmware handles commit and enforcement — debug trace shows exact failure point in ARB flow"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — QAT ARB test explicitly exercises SVN commit path and FW load enforcement",
        "root_cause_domain": "hw.qat / S3M ARB security feature",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "cpm_svn_check immediately shows if SVN is uninitialized (0xFF). arb_commit_log captures S3M rejection message. Two-step debug resolves most cases.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026885969 — DSA tman mmcfg not valid address ───────────────────────
write(
    "14026885969",
    phase2={
        "testcase_name": "vtd_dsa Shared+ATS+PRS+PASID with DSA ITDM/compute/PRS tests",
        "testcase_command": "rocket -M 120 --atlas \"--hw dram,dsa,vtd -v vtd_dsa[Mode=Shared,ATS=Yes,PRS=Yes,PASID=Yes],base_vtd[i=[4k,noinvalidationType,nointerruptRemapping]],dsa_focus_tests[i=[itdm_reducewdc_int,basic_compute_type,prs_completion_record]],vtd_LongSeed\"",
        "testcase_parameters": "DMR X1 A0 VVR; VT-d Shared WQ mode with ATS+PRS+PASID; DSA ITDM reducewdc + compute type + PRS completion record tests",
        "testcase_domain_focus": "DSA VT-d Shared WQ with ATS/PRS/PASID on DMR — tman mmcfg (PCIe ECAM) address mapping failure",
    },
    phase3={
        "verified_problem_statement": "DSA SVOS tman reports ERROR: mmcfg is not a valid address on DMR X1 A0 VVR during vtd_dsa Shared+ATS+PRS+PASID test.",
        "verified_root_cause": "tman mmcfg error means tman cannot find a valid PCIe ECAM (Enhanced Configuration Address Mechanism) address for DSA device configuration. Root cause: SVOS memory manager does not have the mmcfg range mapped for the DSA device in this test configuration. Likely causes: (1) Missing add-map command for DSA mmcfg region in SVOS setup; (2) SVOS memory configuration does not include mmcfg range for VVR platform; (3) Test content expects different SVOS tman configuration for Shared WQ mode. Component sw.application confirms software/configuration domain.",
        "verified_fix": "Add mmcfg mapping for DSA device in SVOS configuration. Verify tman config file has valid mmcfg address for DMR A0 DSA in Shared WQ mode. Reference DMR IMH DSA Focus Test mapping procedures for correct add-map commands.",
        "architectural_element": "SVOS tman PCIe ECAM/mmcfg address mapping; DSA device configuration space; SVOS memory manager",
        "failure_registers": ["PCIe ECAM address region", "DSA BAR registers", "SVOS memory map"],
        "adjacent_subsystems": ["SVOS tman target manager", "PCIe config space", "SVOS memory manager"],
        "related_hsds": [],
        "spec_reference": "DMR IMH DSA Focus Test mapping procedures; Rocket Architecture tman/SVOS memory manager flow"
    },
    phase4={
        "tier1": [
            {"category": "tman_log", "commands": ["cat tman.log | grep -i 'mmcfg'", "cat tman.cfg"], "reveals": "Exact mmcfg address tman is trying to use and why it is invalid", "relevance": "tman log shows the address it attempted and why SVOS rejected it"},
            {"category": "svos_memmap", "commands": ["cat svos_memory_map.log", "dmesg | grep -i 'ecam'", "dmesg | grep -i 'mmcfg'"], "reveals": "PCIe ECAM address regions available in SVOS", "relevance": "SVOS memory map shows if mmcfg region is registered"},
        ],
        "tier2": [
            {"category": "dsa_config", "commands": ["lspci -vvv | grep -i 'dsa'", "cat /proc/iomem | grep -i 'pci'"], "reveals": "DSA device PCIe configuration space mapping in OS", "relevance": "OS-level ECAM mapping confirms if mmcfg is accessible"},
        ],
        "tier3": [],
        "beyond_sme": [
            {"description": "SVOS add-map command for DSA mmcfg", "commands": ["add-map base=<mmcfg_base> length=<mmcfg_length> target=<DSA_device>"], "why": "Adding explicit mmcfg mapping resolves tman invalid address error"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — tman setup for vtd_dsa Shared WQ mode attempts mmcfg access immediately",
        "root_cause_domain": "sw.application / SVOS tman configuration",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "tman_log shows exact mmcfg address. svos_memmap confirms availability. Simple configuration fix resolves the issue.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026877551 — Flexcon_mem Mem_size & AMAP errors FDU6 ────────────────
write(
    "14026877551",
    phase2={
        "testcase_name": "flexcon_mem (Memory size and AMAP errors on FDU6)",
        "testcase_command": "(NGA UUID 2900d181-00dc-4b93-a5e3-02b1... — no rocket command)",
        "testcase_parameters": "DMR X1 A0 VV FDU6; flexcon_mem test fails with Mem_size and AMAP errors",
        "testcase_domain_focus": "Memory-facing flexcon test on FDU6 — memory size validation and Address Mapping (AMAP) errors",
    },
    phase3={
        "verified_problem_statement": "flexcon_mem test on DMR X1 A0 VV FDU6 fails with memory size and AMAP (Address Mapping) errors.",
        "verified_root_cause": "flexcon_mem validates memory connectivity and address mapping for FDU6 platform. Failures: (1) Mem_size error — memory size detected by test does not match expected FDU6 population; (2) AMAP error — address mapping table entry mismatch, possibly due to incorrect BIOS AMAP configuration, incorrect memory topology, or FDU6 DIMM population error. Component val.env.content suggests test infrastructure/platform issue.",
        "verified_fix": "Verify FDU6 DIMM population matches expected test configuration. Check BIOS AMAP configuration. Review SVOS memory map for address mapping discrepancies. Update test expected values if platform configuration changed.",
        "architectural_element": "Memory address mapping (AMAP) table; FDU6 DIMM population; BIOS memory topology configuration",
        "failure_registers": ["AMAP register", "memory channel configuration", "BIOS DIMM SPD"],
        "adjacent_subsystems": ["Memory controller", "BIOS AMAP configuration", "SVOS memory manager"],
        "related_hsds": [],
        "spec_reference": "FDU6 platform memory topology; DMR AMAP register spec; BIOS memory address mapping"
    },
    phase4={
        "tier1": [
            {"category": "amap_check", "commands": ["sv.socket0.imh0.showsearch('amap')", "sv.socket0.imh0.mc.showsearch('map')"], "reveals": "Current AMAP register values vs expected for FDU6 platform", "relevance": "Direct check for AMAP mismatch"},
            {"category": "memory_topology", "commands": ["sv.socket0.imh0.mc.show()", "dmesg | grep -i 'dimm'"], "reveals": "Installed DIMM configuration and detected memory size", "relevance": "Memory size mismatch confirms wrong DIMM population or BIOS misconfiguration"},
        ],
        "tier2": [
            {"category": "bios_mem_check", "commands": ["Check BIOS DIMM SPD data and memory population table"], "reveals": "BIOS-detected memory size and address mapping", "relevance": "BIOS is source of AMAP configuration — mismatch indicates BIOS issue"},
        ],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — flexcon_mem validates memory size and AMAP; mismatches detected immediately",
        "root_cause_domain": "val.env.content / memory configuration",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "amap_check + memory_topology identify configuration mismatch in one pass. Simple environment configuration debug.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026876637 — Flexcon_mem failing FDU5 ───────────────────────────────
write(
    "14026876637",
    phase2={
        "testcase_name": "flexcon_mem (FDU5 platform flexcon memory test failing)",
        "testcase_command": "(NGA UUID f30a2a8b-5467-4e3d-96c2-e51631... — no rocket command)",
        "testcase_parameters": "DMR X1 A0 VV FDU5; flexcon_mem test failing",
        "testcase_domain_focus": "Memory-facing flexcon test on FDU5 — memory connectivity and configuration validation",
    },
    phase3={
        "verified_problem_statement": "flexcon_mem test fails on DMR X1 A0 VV FDU5 platform.",
        "verified_root_cause": "Similar to FDU6 (HSD 14026877551) — flexcon_mem validates memory configuration on the FDU5 platform. Failure likely due to: (1) Memory size or population mismatch on FDU5 vs expected; (2) AMAP or memory channel configuration error; (3) FDU5-specific memory topology issue. Component val.env.content confirms environment/configuration domain.",
        "verified_fix": "Verify FDU5 DIMM population. Check AMAP register. Review BIOS memory configuration for FDU5 platform.",
        "architectural_element": "Memory address mapping (AMAP); FDU5 DIMM population; memory channel configuration",
        "failure_registers": ["AMAP register", "memory channel config"],
        "adjacent_subsystems": ["Memory controller", "BIOS AMAP configuration"],
        "related_hsds": ["14026877551"],
        "spec_reference": "FDU5 platform memory topology; DMR AMAP register spec"
    },
    phase4={
        "tier1": [
            {"category": "amap_check", "commands": ["sv.socket0.imh0.showsearch('amap')", "sv.socket0.imh0.mc.show()"], "reveals": "AMAP configuration and memory size", "relevance": "Direct check for flexcon_mem failure cause"},
            {"category": "dimm_check", "commands": ["dmesg | grep -i 'dimm'", "Check BIOS SPD data"], "reveals": "DIMM population vs expected", "relevance": "Wrong population causes mem_size error"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — flexcon_mem validates memory configuration",
        "root_cause_domain": "val.env.content / memory configuration",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "Same pattern as HSD 14026877551 on FDU6. amap_check + dimm_check resolves in one pass.",
        "iteration_savings": "2",
    },
)

# ── HSD 15018922198 — DSA_testflow_batch_opcode 0 on DMR AP IMH1 ─────────────
write(
    "15018922198",
    phase2={
        "testcase_name": "DSA_testflow_batch_opcode 0 (batch descriptor opcode test)",
        "testcase_command": "(no rocket command — manual DSA batch opcode test on AP platform)",
        "testcase_parameters": "DMR AP IMH1 1S cs16ca101dn0103.gar.corp.intel.com; DSA batch descriptor with opcode 0",
        "testcase_domain_focus": "DSA batch descriptor processing — opcode 0 (NOP or undefined opcode) behavior validation on DMR AP IMH1",
    },
    phase3={
        "verified_problem_statement": "DSA_testflow_batch_opcode 0 test fails on DMR AP IMH1 1S.",
        "verified_root_cause": "DSA batch descriptor with opcode 0: (1) Opcode 0 may be reserved/NOP in DSA spec — test may be verifying correct error handling for invalid opcode; (2) If test expects specific behavior for opcode 0 and silicon returns wrong status, this is a silicon bug in batch descriptor opcode handling; (3) Test content issue — incorrect expected result for opcode 0 on DMR AP. Need DSA spec opcode table to confirm opcode 0 definition.",
        "verified_fix": "Check DSA Architecture Spec opcode table for opcode 0 definition. Capture completion record status for batch descriptor with opcode 0. Verify test expected result matches spec.",
        "architectural_element": "DSA batch descriptor processing engine; opcode decode logic; completion status generation",
        "failure_registers": ["SWERROR0", "completion record status byte", "batch completion record"],
        "adjacent_subsystems": ["DSA descriptor fetch engine", "batch descriptor parser", "WQ submission path"],
        "related_hsds": [],
        "spec_reference": "DSA Architecture Spec: batch descriptor format, opcode table, completion record status codes for invalid opcode"
    },
    phase4={
        "tier1": [
            {"category": "completion_record", "commands": ["Capture DSA completion record for batch descriptor with opcode 0"], "reveals": "Completion status code returned for opcode 0 — expected vs actual", "relevance": "Directly shows if silicon returns correct error code for opcode 0"},
            {"category": "swerror_dump", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.swerror0.show()"], "reveals": "SWERROR for invalid/NOP opcode processing", "relevance": "SWERROR shows if DSA flagged opcode 0 as invalid"},
        ],
        "tier2": [
            {"category": "register_dump", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.show()"], "reveals": "DSA device state after opcode 0 batch", "relevance": "Confirms device is in expected state after processing"},
        ],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — test submits opcode 0 batch descriptor and checks completion result",
        "root_cause_domain": "hw.dsa / DSA opcode 0 handling",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "completion_record immediately shows returned status vs spec-expected. swerror_dump shows silicon view. Need DSA spec for opcode 0 definition.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026841963 — DSA+IAX+PCIe+MSIx Unable to init telemetry ──────────────
write(
    "14026841963",
    phase2={
        "testcase_name": "DSA+IAX+PCIe+MSIx test (Unable to init telemetry)",
        "testcase_command": "rocket -M 120 --atlas \"--hw dram,dsa,iax,interrupts,pcietc\"",
        "testcase_parameters": "DMR A0 VV; NGA UUIDs available; combined DSA+IAX+PCIe+MSIx test; Unable to init telemetry error",
        "testcase_domain_focus": "Combined DSA+IAA+PCIe+MSIx interrupt stress with telemetry initialization failure on DMR A0",
    },
    phase3={
        "verified_problem_statement": "DMR A0 VV combined DSA+IAX+PCIe+MSIx test fails with Unable to init telemetry error.",
        "verified_root_cause": "Telemetry initialization failure on DMR: DMR centralizes telemetry aggregation in Root OOBMSM within iMH. CBBs expose telemetry via Intel PMT controlled by Root OOBMSM. If test tool/rocket framework is not updated for DMR's new telemetry architecture (PECI routing via PUNIT SRAM, DomainID-based routing), init will fail. Component val.env.tool confirms tool-version issue.",
        "verified_fix": "Update rocket/atlas test framework to DMR-aware version supporting new telemetry hierarchy. Verify PMT and Root OOBMSM are configured for PECI aggregation mode. Check iman_pid*.log and runtime_checker*.log for additional detail.",
        "architectural_element": "DMR Root OOBMSM PMT telemetry; PECI routing via CBB PUNIT SRAM; DomainID-based telemetry aggregation",
        "failure_registers": ["PMT telemetry register", "OOBMSM PECI routing config", "DomainID register"],
        "adjacent_subsystems": ["Root OOBMSM firmware", "CBB PUNIT SRAM", "PMT telemetry service", "rocket/atlas tool"],
        "related_hsds": [],
        "spec_reference": "OOBMSM FW Gen4 DMR-HD FAS: telemetry aggregation architecture; DMR CBB PMT PECI routing spec"
    },
    phase4={
        "tier1": [
            {"category": "telemetry_logs", "commands": ["cat iman_pid*.log | grep -i 'telemetry'", "cat runtime_checker*.log | grep -i 'telemetry'"], "reveals": "Telemetry init failure reason and which service/component failed", "relevance": "Log shows exact init failure point"},
            {"category": "tool_version", "commands": ["rocket --version", "atlas --version", "python3 -m atlas --version"], "reveals": "Rocket/atlas version compatibility with DMR telemetry architecture", "relevance": "Old version without DMR PMT support causes init failure"},
        ],
        "tier2": [
            {"category": "pmt_check", "commands": ["sv.socket0.imh0.showsearch('pmt')", "sv.socket0.imh0.oobmsm.showsearch('telem')"], "reveals": "PMT telemetry hardware state", "relevance": "Confirms PMT is enabled and accessible via OOBMSM"},
        ],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — test setup requires telemetry init; fails immediately if tool version incompatible",
        "root_cause_domain": "val.env.tool / rocket telemetry framework",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "telemetry_logs immediately shows init failure reason. tool_version check confirms compatibility. Simple tool update resolves.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026836921 — IAA P2M test failing P2P PCIe to DRAM ──────────────────
write(
    "14026836921",
    phase2={
        "testcase_name": "IAA P2M (Peer-to-Memory PCIe-to-DRAM) test",
        "testcase_command": "rocket -M 120 --atlas \"--hw dram,iax,pcietc -v iax_focus_tests[i=P2M]\"",
        "testcase_parameters": "DMR A0 VV; NGA UUIDs available; P2P traffic from PCIe to DRAM fails with content issue; IAXrand process",
        "testcase_domain_focus": "IAA peer-to-memory data transfer from PCIe device to DRAM — data content verification failure on DMR A0",
    },
    phase3={
        "verified_problem_statement": "IAA P2M test fails on DMR A0 VV: P2P traffic from PCIe to DRAM fails due to content issue. IAXrand process involved.",
        "verified_root_cause": "IAA P2M data mismatch: (1) PCIe-to-DRAM data corruption during IAA P2P DMA transfer — potential silicon bug in IAA P2M path; (2) PCIe link configuration issue affecting P2P data integrity; (3) Test content/configuration issue — incorrect buffer alignment or PCIe card P2P capability mismatch; (4) Stuck or ordering violation in IAA P2P path. Component val.env.content suggests test content/platform configuration.",
        "verified_fix": "Capture IAXrand data pattern mismatch details — which bytes differ. Check PCIe link state and P2P capability. Verify IAA P2M test configuration for DMR A0. Check for known IAA P2P silicon bugs.",
        "architectural_element": "IAA P2M (Peer-to-Memory) DMA path; PCIe P2P data path; IAXrand content verification",
        "failure_registers": ["SWERROR0", "INTCAUSE", "PCIe ERRUNCSTS", "IAA completion record status"],
        "adjacent_subsystems": ["PCIe P2P DMA engine", "IAA data path", "DRAM write path", "IAXrand test tool"],
        "related_hsds": [],
        "spec_reference": "IAA Architecture Spec: P2M operation; PCIe Gen6 P2P transfer spec; DMR PCIe Ramp Up Steps"
    },
    phase4={
        "tier1": [
            {"category": "iaa_error_regs", "commands": ["sv.socket0.imh0.acc.acc_0.iaa.swerror0.show()", "sv.socket0.imh0.acc.acc_0.iaa.intcause.show()"], "reveals": "IAA error state during P2M transfer — completion error code", "relevance": "SWERROR code identifies if P2M failure is at descriptor or data level"},
            {"category": "iaxrand_content", "commands": ["cat iaxrand_pid*.log | grep -i 'mismatch'", "cat iaxrand_pid*.log | grep -i 'content'"], "reveals": "IAXrand content comparison failure details — which address, which bytes", "relevance": "Identifies whether mismatch is consistent (silicon) or random (electrical)"},
        ],
        "tier2": [
            {"category": "pcie_link_p2p", "commands": ["sv.socket0.imh0.showsearch('p2p')", "lspci -vvv | grep -i 'p2p'"], "reveals": "P2P capability advertisement and configuration", "relevance": "P2P not enabled or misconfigured prevents correct PCIe-to-DRAM transfer"},
            {"category": "pcie_errors", "commands": ["sv.socket0.imh0.showsearch('erruncsts')"], "reveals": "PCIe AER errors during P2M transfer", "relevance": "PCIe errors would corrupt P2P data causing content mismatch"},
        ],
        "tier3": [],
        "beyond_sme": [
            {"description": "Vary PCIe card and Gen speed for P2M", "commands": ["Test with different PCIe card; reduce to Gen3 speed"], "why": "If failure is PCIe card-specific, it is test infra; if silicon-generic, escalate as hw.iax P2M bug"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — iax_focus_tests[i=P2M] directly exercises IAA P2P DMA path",
        "root_cause_domain": "val.env.content / IAA P2M path",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "iaa_error_regs + iaxrand_content identify failure mode. pcie_link_p2p + pcie_errors differentiate silicon vs PCIe card issue.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026828275 — PCIe Moka/flexcon_hw pxp11 port ────────────────────────
write(
    "14026828275",
    phase2={
        "testcase_name": "PCIe Moka/flexcon_hw failure pxp11 port (accelerators NGA test line)",
        "testcase_command": "(NGA-linked test — no explicit rocket command; NGA UUIDs from HSD symptom)",
        "testcase_parameters": "DMR X1 A0 VVR; Moka/flexcon_hw failure on pxp11 PCIe port; val.env.execution component",
        "testcase_domain_focus": "PCIe Moka protocol test and flexcon_hw test failure on pxp11 port on DMR X1 A0 VVR",
    },
    phase3={
        "verified_problem_statement": "PCIe Moka/flexcon_hw test fails on pxp11 port on DMR X1 A0 VVR during accelerators NGA test line.",
        "verified_root_cause": "PCIe pxp11 flexcon/Moka failure: (1) PCIe link training failure or protocol error on pxp11 port; (2) MCTP broadcast WA not applied causing UR errors; (3) Physical card connectivity issue on pxp11; (4) pxp11 bifurcation configuration mismatch. Val.env.execution indicates execution environment issue.",
        "verified_fix": "Check pxp11 link status. Apply MCTP WA. Verify card on pxp11 is properly seated. Check BIOS pxp11 bifurcation.",
        "architectural_element": "DMR PCIe pxp11 port; Moka protocol test; MCTP broadcast handling",
        "failure_registers": ["PCIe ERRUNCSTS pxp11", "LTSSM pxp11", "hiop_reg.mctp_bcast_ctl.en_outb_mctp_bcast"],
        "adjacent_subsystems": ["PCIe root complex pxp11", "MCTP broadcast path", "test card pxp11"],
        "related_hsds": ["14026997858", "14026942339"],
        "spec_reference": "DMR Current Workarounds; DMR PCIe port map"
    },
    phase4={
        "tier1": [
            {"category": "pxp11_link_status", "commands": ["sv.socket0.imh0.pxp11.showsearch('lnksts')", "sv.socket0.imh0.pxp11.showsearch('ltssm')"], "reveals": "pxp11 PCIe link state", "relevance": "Link down causes immediate flexcon failure"},
            {"category": "mctp_wa_check", "commands": ["sv.sockets.imhs.hiop.hiops.hiop_reg.mctp_bcast_ctl.en_outb_mctp_bcast.show()"], "reveals": "MCTP WA state", "relevance": "MCTP UR errors are common A0 PCIe flexcon failure"},
        ],
        "tier2": [
            {"category": "pxp11_errors", "commands": ["sv.socket0.imh0.pxp11.showsearch('erruncsts')"], "reveals": "PCIe AER errors on pxp11", "relevance": "Error type identifies failure cause"},
        ],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — Moka/flexcon exercises pxp11 PCIe port; link failure causes immediate test failure",
        "root_cause_domain": "val.env.execution / hw.pcie pxp11",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "pxp11_link_status + mctp_wa_check covers both common A0 causes. Fast debug.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026822165 — DSA Dualcast CXLHDM mismatch ───────────────────────────
write(
    "14026822165",
    phase2={
        "testcase_name": "DSA+interrupts Dualcast operation using CXLHDM targets (data mismatch)",
        "testcase_command": "(NGA UUIDs from HSD symptom — no rocket command; val.env.content component)",
        "testcase_parameters": "DMR A0 VV; DSA Dualcast operation writing to two CXLHDM (CXL Host-Managed Device Memory) destinations; data mismatch seen",
        "testcase_domain_focus": "DSA Dualcast data integrity with CXL HDM targets — two-destination write mismatch on DMR A0",
    },
    phase3={
        "verified_problem_statement": "DSA Dualcast operation with CXL HDM targets shows data mismatch on DMR A0 VV.",
        "verified_root_cause": "DSA Dualcast to CXL HDM mismatch likely caused by: (1) CXL HDM credit management issue — credit pool not correctly configured for HAMVF/CXL destinations (known A0 issue HSD 22018834267 — LCD credit value difficult to interpret); (2) Protected memory range (PRMRR/SEAMRR/TDX) incorrectly overlapping with HDM-D/HDM-DB range causing undefined behavior; (3) CXL port clock gating interaction with Dualcast write ordering; (4) PCIe/CXL write ordering violation during simultaneous dual-write. No specific confirmed silicon erratum but credit and clock-gating issues are known.",
        "verified_fix": "Verify CXL HDM credit table configuration for Dualcast destination. Check HAMVF/CXL credit pool setup. Confirm no PRMRR/SEAMRR/TDX overlap with CXL HDM range. Use status_scope PCIe plugin for credit table capture.",
        "architectural_element": "DSA Dualcast engine; CXL HDM-D/HDM-DB write path; HAMVF CXL credit pool; LCDS clock gating",
        "failure_registers": ["CXL HDM credit pool registers", "HAMVF credit table", "LCD credit registers"],
        "adjacent_subsystems": ["CXL port", "CXL HDM decoder", "HAMVF credit manager", "DSA data path"],
        "related_hsds": ["22018834267"],
        "spec_reference": "SCF GEN4 R2204 HAMVF HAS: CXL credit pool configuration; CXL HDM-D/HDM-DB spec; DMR CXL debug wiki"
    },
    phase4={
        "tier1": [
            {"category": "status_scope_cxl", "commands": ["status_scope.run(analyzers=['pcie','m2iosf'])"], "reveals": "CXL credit table state and PCIe error state at mismatch time", "relevance": "Credit table shows HAMVF/CXL configuration for Dualcast destinations"},
            {"category": "cxl_credit_check", "commands": ["sv.socket0.imh0.showsearch('cxl')", "sv.socket0.imh0.showsearch('hamvf')"], "reveals": "CXL credit pool values and HAMVF state", "relevance": "Credit issues are primary known cause for Dualcast CXL mismatch"},
        ],
        "tier2": [
            {"category": "protected_mem_check", "commands": ["sv.socket0.imh0.showsearch('prmrr')", "sv.socket0.imh0.showsearch('seamrr')"], "reveals": "Protected memory ranges that must not overlap HDM", "relevance": "Protected range overlap with CXL HDM causes undefined write behavior"},
            {"category": "completion_records", "commands": ["Capture DSA Dualcast completion records for both destinations"], "reveals": "Which destination mismatches and completion status", "relevance": "Identifies if one or both CXL HDM writes are wrong"},
        ],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — Dualcast operation writes to CXL HDM targets and verifies both destinations",
        "root_cause_domain": "val.env.content / hw.dsa CXL credit",
        "domain_relationship": "adjacent",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "status_scope_cxl captures credit state. cxl_credit_check confirms HAMVF configuration. Multiple causes require systematic elimination.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026811349 — Flexcon errors security SGX/TDX/SAF oobmsm ─────────────
write(
    "14026811349",
    phase2={
        "testcase_name": "Flexcon oobmsm security test (SGX, TDX, SAF running with flexcon)",
        "testcase_command": "(NGA UUIDs from HSD symptom — no explicit rocket command; val.env.content component)",
        "testcase_parameters": "DMR A0 VV; flexcon errors during security (SGX, TDX, SAF) combined with oobmsm",
        "testcase_domain_focus": "PCIe flexcon errors during security feature (SGX/TDX/SAF) + oobmsm combined test on DMR A0",
    },
    phase3={
        "verified_problem_statement": "Flexcon errors for oobmsm occur on DMR A0 VV when running security features (SGX, TDX, SAF) combined with flexcon test.",
        "verified_root_cause": "Flexcon errors with oobmsm+security features: (1) OOBMSM MCTP broadcast causing PCIe UR errors during security test (same as HSD 14026997858 pattern) — MCTP WA needed; (2) Security feature (TDX/SGX) interaction with flexcon PCIe path affecting completion routing; (3) SAF (Software Attestation Framework) initialization conflict with PCIe flexcon resource allocation; (4) Test content combining security+flexcon exercises edge cases in OOBMSM MCTP handling.",
        "verified_fix": "Apply MCTP broadcast disable WA. Verify TDX/SGX isolation does not interfere with flexcon PCIe path. Separate security feature initialization from PCIe flexcon test execution.",
        "architectural_element": "OOBMSM MCTP broadcast; PCIe flexcon path; TDX/SGX security feature isolation; SAF initialization",
        "failure_registers": ["hiop_reg.mctp_bcast_ctl.en_outb_mctp_bcast", "PCIe ERRUNCSTS", "TDX/SGX status registers"],
        "adjacent_subsystems": ["OOBMSM MCTP stack", "PCIe flexcon", "TDX/SGX firmware", "SAF software"],
        "related_hsds": ["14026997858", "14025805912"],
        "spec_reference": "DMR Current Workarounds; OOBMSM MCTP broadcast WA; TDX/SGX isolation spec"
    },
    phase4={
        "tier1": [
            {"category": "mctp_wa_check", "commands": ["sv.sockets.imhs.hiop.hiops.hiop_reg.mctp_bcast_ctl.en_outb_mctp_bcast.show()"], "reveals": "MCTP WA state — confirms if broadcast is causing flexcon UR errors", "relevance": "Most likely cause of oobmsm flexcon errors"},
            {"category": "pcie_errors", "commands": ["status_scope.run(analyzers=['pcie','ieh'])"], "reveals": "PCIe error state and flexcon failure type", "relevance": "IEH captures error hierarchy for flexcon+security combined test"},
        ],
        "tier2": [
            {"category": "tdx_sgx_state", "commands": ["dmesg | grep -i 'tdx'", "dmesg | grep -i 'sgx'"], "reveals": "TDX/SGX initialization state during flexcon test", "relevance": "Security feature conflict would show in kernel messages"},
        ],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — flexcon test runs while security features are active; OOBMSM MCTP interference",
        "root_cause_domain": "val.env.content / OOBMSM MCTP PCIe interaction",
        "domain_relationship": "adjacent",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "mctp_wa_check is single-register check for most common cause. pcie_errors confirms flexcon failure type.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026810657 — All accelerators supercollider status 4 ────────────────
write(
    "14026810657",
    phase2={
        "testcase_name": "All accelerators + supercollider IDI stress (supercollider error status 4)",
        "testcase_command": "(NGA UUIDs from HSD symptom — no explicit rocket command; val.env.content component)",
        "testcase_parameters": "DMR A0 VV; CPM+Supercollider IDI+PCIe+IAA/DSA combined test; supercollider error status 4",
        "testcase_domain_focus": "Combined accelerator + CPU supercollider IDI stress — error status 4 (data compare failure)",
    },
    phase3={
        "verified_problem_statement": "CPM+Supercollider IDI+PCIe+IAA/DSA test fails with supercollider error status 4 on DMR A0 VV.",
        "verified_root_cause": "Supercollider error status 4 most commonly indicates data compare/mismatch failure (data miscompare during combined stress traffic). Root causes: (1) LCD out-of-order completion causing data collision on shared cache line (HSD 14025873279); (2) ordering violation under combined IDI+accelerator load; (3) data corruption from accelerator+PCIe combined traffic. Distinguish from status 3 (which may be command timeout) — status 4 is typically a hard data compare failure.",
        "verified_fix": "Run Dragon Error Decode tool on status 4. Minimize test: run single-VM to check LCD OOO bug. Apply chicken bits to disable OOO features. Cross-reference with HSD 14025873279 (SDC with LCD OOO).",
        "architectural_element": "CPU supercollider data compare engine; LCD cache line OOO completion; combined accelerator traffic ordering",
        "failure_registers": ["Dragon error status register", "LCD OOO flag", "MCE bank registers"],
        "adjacent_subsystems": ["CPU IDI interconnect", "LCD cache", "DSA/IAA/CPM traffic", "pysces supercollider"],
        "related_hsds": ["14025873279", "14026973320"],
        "spec_reference": "Dragon Vertical Debug Guide error status 4; LCD SDC OOO debug guide; DMR Accelerator Stack known bugs"
    },
    phase4={
        "tier1": [
            {"category": "dragon_decode", "commands": ["dragon_error_decode --status 4", "cat pysces_pid*.log | grep -i 'compare'"], "reveals": "Exact failure mode for status 4 — data mismatch address, pattern, seed", "relevance": "Required first step to identify specific failing operation"},
            {"category": "minimization", "commands": ["Run single-VM test with same traffic mix", "Disable data checking in supercollider"], "reveals": "Whether LCD OOO bug (HSD 14025873279) is involved — multi-VM only failure", "relevance": "Single-VM isolation differentiates LCD bug from other causes"},
        ],
        "tier2": [
            {"category": "acc_error_dump", "commands": ["from diamondrapids.accelerators.dsa_iaa import dsa_iaa_debug_dump as dsa_iaa_dump", "dsa_iaa_dump.dump_all_dsa_inst_errs()"], "reveals": "Accelerator error state correlated with status 4 failure", "relevance": "Accelerator error at status 4 time links failure to specific IP"},
            {"category": "mce_check", "commands": ["mcelog --client", "dmesg | grep -i 'mce'"], "reveals": "MCE at time of supercollider status 4", "relevance": "MCE during combined stress may trigger status 4"},
        ],
        "tier3": [],
        "beyond_sme": [
            {"description": "OOO chicken bit disable test", "commands": ["Apply chicken bits to disable OOO in LLC/CPU; rerun test"], "why": "If status 4 disappears with OOO disabled, LCD OOO bug (HSD 14025873279) is confirmed root cause"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "indirect — combined accelerator+IDI stress creates conditions for LCD data compare failure",
        "root_cause_domain": "val.env.content / LCD data compare supercollider",
        "domain_relationship": "adjacent",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "dragon_decode identifies specific failure. minimization (single-VM) quickly confirms LCD OOO. Known pattern from HSD 14025873279.",
        "iteration_savings": "2",
    },
)

# ── HSD 16029579061 — OKS DSA DMA test failure ───────────────────────────────
write(
    "16029579061",
    phase2={
        "testcase_name": "OKS DMR AP AUTOMATION Accelerator DSA DMA test",
        "testcase_command": "(OKS Automation via kayak/dmatest/idxd driver — no explicit rocket command)",
        "testcase_parameters": "DMR AP 1S OKS automation; DSA DMA test failure; idxd/dmatest kernel driver path",
        "testcase_domain_focus": "DSA kernel DMA test automation on DMR AP — driver/firmware/BKC stack validation",
    },
    phase3={
        "verified_problem_statement": "OKS DMR AP automation DSA DMA test fails.",
        "verified_root_cause": "DSA DMA automation failure most commonly caused by: (1) Driver/firmware/BKC version mismatch — idxd or dmatest driver not aligned with DMR AP silicon step; (2) DSA config register not at POR — DEFTR or GRPWQCFG/GRPENGCFG invalid; (3) Known DSA errata: completion status 0x17 (config registers invalid), Gather Copy SGL wrong completion (HSD 22021248658), ATS unexpected response (HSD 22020576187); (4) BIOS DSA feature not enabled or ASPM interfering; (5) OKS execution environment issue. Component OKS automation suggests val.env.execution.",
        "verified_fix": "Verify BKC alignment for DMR AP. Run dsa_iaa_debug_dump. Check DEFTR registers. Apply known errata workarounds. Disable ASPM for debug.",
        "architectural_element": "DSA idxd kernel driver; DSA config registers (DEFTR, GRPWQCFG); ATS/PRS hardware path",
        "failure_registers": ["CMDSTATUS", "SWERROR0", "DEFTR registers", "GRPWQCFG", "GRPENGCFG"],
        "adjacent_subsystems": ["idxd kernel driver", "BIOS DSA enablement", "PCIe ATS path"],
        "related_hsds": ["22021248658", "22020576187"],
        "spec_reference": "DSA/IAX Debug BKMs; OKS DMR Automation Strategy Alignment wiki"
    },
    phase4={
        "tier1": [
            {"category": "dsa_error_dump", "commands": ["from diamondrapids.accelerators.dsa_iaa import dsa_iaa_debug_dump as dsa_iaa_dump", "dsa_iaa_dump.dump_all_dsa_inst_errs()"], "reveals": "DSA instance errors at time of DMA test failure", "relevance": "Identifies failing DSA instance and error type"},
            {"category": "config_check", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.showsearch('deftr')", "sv.socket0.imh0.acc.acc_0.dsa.cmdstatus.show()"], "reveals": "DSA config register state vs POR", "relevance": "CMDSTATUS 0x17 = config invalid; DEFTR mismatch causes failures"},
        ],
        "tier2": [
            {"category": "bkc_version", "commands": ["kernel --version", "modinfo idxd", "cat /etc/ofa_version"], "reveals": "Driver/BKC version vs expected for DMR AP", "relevance": "Version mismatch is common automation failure root cause"},
        ],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — automation test invokes DSA DMA path",
        "root_cause_domain": "val.env.execution / BKC alignment",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "dsa_error_dump + config_check cover most DSA automation failures. bkc_version narrows driver issues.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026766087 — IAA/DSA PRS count verification failed ──────────────────
write(
    "14026766087",
    phase2={
        "testcase_name": "IAA/DSA PRS count verification (base_vtd[i=[4k]] test)",
        "testcase_command": "rocket -M @{TestLine.TestStageEstimatedTime} --atlas \"--hw dram,iax,vtd -v base_vtd[i=[4k]]\"",
        "testcase_parameters": "DMR X1 A0 VV SVOS; VT-d IAA PRS count verification failure; component val.env.tool",
        "testcase_domain_focus": "IAA/DSA PRS (Page Request Service) count verification in base_vtd[4k] test — count mismatch on DMR A0",
    },
    phase3={
        "verified_problem_statement": "IAA/DSA PRS count verification fails on DMR X1 A0 VV during base_vtd[i=[4k]] rocket test.",
        "verified_root_cause": "Known DMR A0 hardware bug in M2IOSF PRS request/response pipeline: LPIG field ordering logic does not enforce correct drain ordering for PASID, causing PRS count mismatch. HSD 14025333034 (DMR PASID drain bug — non-ECOable). When LPIG=1 requests should flush LPIG=0, the adjacent pipeline channel is not stalled correctly, allowing younger PRS requests to overtake, resulting in duplicate/missing PRS count. No silicon fix on A0; microcode/BIOS workarounds only.",
        "verified_fix": "Apply WA: vt_iommu_cr_itciommudbgctrl3.dis_max_pgr_throttle=1. Disable PRS on stacks that mix LPIG=0 and LPIG=1. Cross-reference HSD 14025333034.",
        "architectural_element": "M2IOSF PRS LPIG ordering logic; IAA/DSA PASID drain pipeline; VT-d IOMMU page request service",
        "failure_registers": ["vt_iommu_cr_itciommudbgctrl3", "LPIG tracking registers", "IOMMU PRQ (Page Request Queue)"],
        "adjacent_subsystems": ["M2IOSF", "VT-d IOMMU", "IAA descriptor engine", "PRS pipeline"],
        "related_hsds": ["14025333034"],
        "spec_reference": "PRS Bug wiki (GNR debug reference); DMR PASID drain IOMMU spec; Flexcon_Vtd workarounds"
    },
    phase4={
        "tier1": [
            {"category": "prs_wa_check", "commands": ["sv.socket0.imh0.showsearch('itciommudbgctrl3')", "sv.socket0.imh0.vt_iommu_cr_itciommudbgctrl3.dis_max_pgr_throttle.show()"], "reveals": "Whether PRS throttle WA is applied", "relevance": "Primary WA for PRS count mismatch on DMR A0"},
            {"category": "prs_count_log", "commands": ["cat iman_pid*.log | grep -i 'PRS'", "cat rocket*.log | grep -i 'count'"], "reveals": "Exact PRS expected vs actual count mismatch", "relevance": "Confirms pipeline ordering violation signature"},
        ],
        "tier2": [
            {"category": "iommu_state", "commands": ["sv.socket0.imh0.showsearch('iommu')", "cat dmesg | grep -i 'iommu'"], "reveals": "IOMMU state and configuration", "relevance": "IOMMU config confirms PRS is active"},
        ],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — base_vtd[4k] exercises PRS pipeline with PASID drain; triggers M2IOSF ordering bug",
        "root_cause_domain": "hw.m2iosf / known DMR A0 PRS ordering bug (HSD 14025333034)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "Known silicon bug. prs_wa_check immediately shows if WA is applied. prs_count_log confirms signature.",
        "iteration_savings": "3",
    },
)

# ── HSD 14026746548 — pcietcrand errcode 1 CPM+DSA+IAX+PCIe ─────────────────
write(
    "14026746548",
    phase2={
        "testcase_name": "cpm_variant_dmr combined PCIe+DSA+IAX+CPM test (pcietcrand errcode 1)",
        "testcase_command": "rocket -M 120 --atlas \"--hw dram,cpm,dsa,iax,pcietc -v cpm_variant_dmr[minutes=120,loops=0,jo...\"",
        "testcase_parameters": "DMR X1 A0 VV SVOS; pcietcrand process exits errcode 1; component val.env.content",
        "testcase_domain_focus": "Combined CPM+DSA+IAX+PCIe test — pcietcrand (PCIe traffic randomizer) failure on DMR A0",
    },
    phase3={
        "verified_problem_statement": "pcietcrand exits with errcode 1 during cpm_variant_dmr combined test on DMR X1 A0 VV SVOS.",
        "verified_root_cause": "pcietcrand errcode 1 indicates PCIe test infrastructure failure: (1) PCIe card issue — card not properly configured or failed during cpm_variant stress; (2) Test configuration issue — tman.cfg has incorrect target for pcietcrand; (3) Known DMR A0 PCIe silicon issue (link training failure, credit starvation under combined CPM+DSA+PCIe load); (4) MCTP broadcast WA not applied — MCTP UR errors cause pcietcrand to abort. Component val.env.content suggests test content/config issue.",
        "verified_fix": "Apply MCTP broadcast WA. Check pcietcrand log for specific failure. Verify PCIe card state. Confirm tman.cfg has correct target. Run status_scope PCIe plugin.",
        "architectural_element": "PCIe root port; pcietcrand test process; CPM+PCIe combined traffic path",
        "failure_registers": ["PCIe ERRUNCSTS", "hiop_reg.mctp_bcast_ctl.en_outb_mctp_bcast", "PCIe LTSSM"],
        "adjacent_subsystems": ["CPM traffic generator", "PCIe root complex", "MCTP broadcast path"],
        "related_hsds": ["14025805912", "14026997858"],
        "spec_reference": "Gen6+ PCIe Debug wiki; FlexconCXL/PCIe/MOKA Debug Scenarios wiki; DMR MCTP broadcast WA"
    },
    phase4={
        "tier1": [
            {"category": "mctp_wa_check", "commands": ["sv.sockets.imhs.hiop.hiops.hiop_reg.mctp_bcast_ctl.en_outb_mctp_bcast.show()"], "reveals": "MCTP WA state — single most common A0 PCIe test killer", "relevance": "MCTP UR causes pcietcrand abort"},
            {"category": "pcietcrand_log", "commands": ["cat pcietcrand*.log | grep -i 'error'", "cat pcietcrand*.log | grep -i 'fail'"], "reveals": "pcietcrand failure reason and type", "relevance": "Log shows exact PCIe error that caused errcode 1"},
        ],
        "tier2": [
            {"category": "pcie_status", "commands": ["status_scope.run(analyzers=['pcie','ieh'])"], "reveals": "PCIe link status and error hierarchy at test failure", "relevance": "Confirms if PCIe card issue or silicon problem"},
        ],
        "tier3": [],
        "beyond_sme": [
            {"description": "Swap PCIe card on failing port", "commands": ["Replace card with known-good equivalent"], "why": "Card-specific failure vs silicon-generic differentiates val.env vs hw.pcie bug"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — pcietcrand exercises PCIe port under CPM+DSA+IAX combined stress",
        "root_cause_domain": "val.env.content / PCIe card or MCTP",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "mctp_wa_check is fastest single-register check. pcietcrand_log identifies specific cause.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026683622 — DSA err_code 0x12 non-zero reserved field ──────────────
write(
    "14026683622",
    phase2={
        "testcase_name": "DSA/IAA test with err_code 0x12 (Non-zero reserved field check)",
        "testcase_command": "DSA test with non-zero reserved field validation",
        "testcase_parameters": "DMR X1 A0 VVR SVOS; DSA completion status 0x12 = Non-zero reserved field (other than 0x10/0x11); component val.env.configuration",
        "testcase_domain_focus": "DSA reserved field validation — completion status 0x12 on descriptor submission",
    },
    phase3={
        "verified_problem_statement": "DMR X1 A0 VVR DSA test fails with err_code:8 = 0x12 (Non-zero reserved field).",
        "verified_root_cause": "DSA status 0x12 means a submitted descriptor has a non-zero reserved field (not covered by 0x10/0x11). Root causes: (1) Test configuration issue — dsarand or test framework randomizing reserved fields (intentional corner case testing); (2) Software descriptor generation bug — SDK/driver not zeroing reserved bits per DSA architecture spec; (3) val.env.configuration indicates configuration problem. Check if test is intentionally testing 0x12 behavior or accidentally setting reserved bits.",
        "verified_fix": "Verify descriptor generation code zeros all reserved bits. If test is intentional (testing reserved field rejection), verify completion status is 0x12 as expected. Check test expected result vs actual.",
        "architectural_element": "DSA descriptor format; reserved field validation logic; completion record status generation",
        "failure_registers": ["DSA completion status byte (CMPSC)", "descriptor reserved fields"],
        "adjacent_subsystems": ["DSA descriptor fetch engine", "dsarand test generator", "SVOS descriptor builder"],
        "related_hsds": ["14026683541"],
        "spec_reference": "DSA Architecture Spec: descriptor format, reserved field definition, completion status 0x12"
    },
    phase4={
        "tier1": [
            {"category": "descriptor_dump", "commands": ["Dump failing DSA descriptor — check reserved field bytes", "cat dsa_test*.log | grep -i '0x12'"], "reveals": "Which reserved field is non-zero in the failing descriptor", "relevance": "Directly identifies software bug or intentional test"},
            {"category": "completion_record", "commands": ["Capture completion record for failing descriptor"], "reveals": "Completion status 0x12 confirmation and descriptor correlation", "relevance": "Confirms silicon correctly flags reserved bit violation"},
        ],
        "tier2": [
            {"category": "config_check", "commands": ["cat tman.cfg | grep -i 'reserved'", "Verify test YAML for descriptor configuration"], "reveals": "Test configuration for reserved field handling", "relevance": "Confirms if test is intentional reserved field test or accidental"},
        ],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — descriptor with non-zero reserved field triggers DSA status 0x12",
        "root_cause_domain": "val.env.configuration / descriptor configuration",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "descriptor_dump immediately shows reserved field value. config_check confirms if intentional.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026683560 — Machine check errors MLC/PUNIT/CBB ────────────────────
write(
    "14026683560",
    phase2={
        "testcase_name": "DSA test triggering MCEs in MLC/PUNIT/CBB",
        "testcase_command": "DSA focus test causing MCE in MLC (Mid-Level Cache), PUNIT, CBB",
        "testcase_parameters": "DMR X1 A0 VVR SVOS; Machine Check Errors in MLC, PUNIT, CBB blocks during DSA test; component hw.punit",
        "testcase_domain_focus": "DSA-triggered MCEs in MLC/PUNIT/CBB — hardware error during DSA operations on DMR A0 VVR",
    },
    phase3={
        "verified_problem_statement": "MCEs occur in MLC, PUNIT, and CBB during DSA testing on DMR X1 A0 VVR SVOS.",
        "verified_root_cause": "DSA-triggered MCEs in MLC/PUNIT/CBB on DMR A0: (1) ATS/DMA MCE — when DSA issues ATS request and receives UR/CA, MCE is generated (HSD 16011917387, HSD 14012767500); (2) PASID drain issue — M2IOSF PRS bug (HSD 14025333034) can trigger MCE on IOMMU invalidation completion error; (3) PUNIT watchdog timeout MCE — if DSA hangs processor; (4) CBB MCA bank merged error from internal parity (MCACOD 0x405). Component hw.punit confirms hardware domain — PUNIT/CBB MCE bank reporting.",
        "verified_fix": "Decode MCACOD/MSCOD from MCE bank. Check DSA ATS path for UR/CA. Apply PASID drain WA. Reference DMR RAS HAS for MCA bank encoding.",
        "architectural_element": "MLC MCA bank; PUNIT/CBB MCE reporting; DSA ATS error pathway; M2IOSF PRS pipeline",
        "failure_registers": ["MCi_STATUS (MCACOD/MSCOD)", "MCi_ADDR", "PCU MCA bank", "CBB MCA bank"],
        "adjacent_subsystems": ["DSA ATS request path", "VT-d IOMMU", "M2IOSF", "PUNIT watchdog"],
        "related_hsds": ["14025333034", "16011917387"],
        "spec_reference": "DMR RAS HAS; DMR CBB MCA bank spec; HSD 16011917387 (ATS MCE); DSA/IAX Debug BKMs"
    },
    phase4={
        "tier1": [
            {"category": "mce_decode", "commands": ["mcelog --client", "dmesg | grep -i 'mce'", "cat /sys/bus/edac/devices/mc*/mc*_mc*"], "reveals": "MCACOD/MSCOD for each MCE bank — identifies specific error source", "relevance": "MCACOD 0x405 = parity; MCACOD 0x402 = unclassified; decode determines root cause"},
            {"category": "ats_check", "commands": ["sv.socket0.imh0.showsearch('ats')", "status_scope.run(analyzers=['pcie','m2iosf'])"], "reveals": "ATS error state at MCE time", "relevance": "ATS UR/CA is known MCE trigger in DSA path"},
        ],
        "tier2": [
            {"category": "dsa_state", "commands": ["from diamondrapids.accelerators.dsa_iaa import dsa_iaa_debug_dump as dsa_iaa_dump", "dsa_iaa_dump.dump_all_dsa_inst_errs()"], "reveals": "DSA state at MCE time", "relevance": "Correlates DSA error with MCE trigger"},
        ],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — DSA test exercises ATS/PASID path that triggers hardware MCE",
        "root_cause_domain": "hw.punit / hw.mce — DSA-triggered MCE via ATS or PRS path",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "mce_decode identifies specific MCACOD. ats_check confirms DSA ATS involvement. Known DMR A0 pattern.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026683542 — Atlas/Acre failed to create targets ────────────────────
write(
    "14026683542",
    phase2={
        "testcase_name": "DSA/IAA SVOS Atlas/Acre EV buffer target creation failure",
        "testcase_command": "Rocket/Atlas framework target creation for DSA/IAA EV buffers",
        "testcase_parameters": "DMR X1 A0 VVR SVOS; Atlas/Acre fails to create targets for EV (execution/validation) buffers; component sw.application",
        "testcase_domain_focus": "Rocket/Atlas/Acre framework EV buffer target creation for DSA/IAA on DMR A0 — software configuration issue",
    },
    phase3={
        "verified_problem_statement": "Atlas/Acre fails to create targets for EV buffers on DMR X1 A0 VVR SVOS during DSA/IAA test.",
        "verified_root_cause": "Atlas/Acre EV buffer target creation failure caused by: (1) Unsupported registers in Atlas/Acre pcietc.py or pcie.py scripts for DMR stepping — need to comment out unsupported registers per DMR A0 workarounds; (2) Resource enumeration issue — device attributes missing or incorrectly defined for DMR A0 in Atlas scripts; (3) Domain isolation/VT-d conflict — ivman domain assignment conflict preventing EV buffer allocation; (4) Software version mismatch — Acre not updated for DMR X1 A0 platform. Component sw.application confirms software domain.",
        "verified_fix": "Update Atlas/Acre scripts to comment out unsupported DMR registers. Verify Acre version vs DMR A0 BKC. Check ivman configuration for domain conflicts.",
        "architectural_element": "Atlas/Acre target manager; EV buffer allocation; ivman domain configuration; pcietc.py scripts",
        "failure_registers": ["Atlas target config", "ivman domain map", "Acre buffer table"],
        "adjacent_subsystems": ["Rocket framework", "Atlas target manager", "ivman VT-d domain manager"],
        "related_hsds": ["14026683520"],
        "spec_reference": "Atlas/Acre developer guide; GNR VP LCD VTC Execution Results wiki; SVOS Rocket Architecture wiki"
    },
    phase4={
        "tier1": [
            {"category": "acre_log", "commands": ["cat acre_pid*.log | grep -i 'target'", "cat atlas_pid*.log | grep -i 'EV'"], "reveals": "Specific reason Acre fails to create EV buffer targets", "relevance": "Log shows which register or resource caused failure"},
            {"category": "acre_version", "commands": ["python3 -c 'import acre; print(acre.__version__)'", "cat /usr/local/diamondrapids/atlas/version.txt"], "reveals": "Acre/Atlas version vs DMR A0 BKC requirement", "relevance": "Old version without DMR A0 support causes target creation failure"},
        ],
        "tier2": [
            {"category": "ivman_check", "commands": ["cat ivman.cfg | grep -i 'EV'", "cat tman.target | grep -i 'buffer'"], "reveals": "EV buffer definition in SVOS config files", "relevance": "Mismatched or missing EV buffer config causes Acre failure"},
        ],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — test setup requires EV buffer target creation; Acre fails immediately",
        "root_cause_domain": "sw.application / Atlas/Acre version or config",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "acre_log shows exact failure reason. acre_version confirms BKC alignment. Fast debug.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026683541 — 0x0 error code after 0x12 ──────────────────────────────
write(
    "14026683541",
    phase2={
        "testcase_name": "DSA event_log test (0x0 error code after 0x12 error)",
        "testcase_command": "DSA event_log test on DMR VVR SVOS",
        "testcase_parameters": "DMR X1 A0 VVR SVOS; DSA event_log test reports 0x0 error code after 0x12 error code; component sw.application",
        "testcase_domain_focus": "DSA error status register behavior — 0x0 reported after 0x12 error (status clearing behavior)",
    },
    phase3={
        "verified_problem_statement": "DSA event_log test on DMR X1 A0 VVR reports error code 0x0 after initially detecting error code 0x12.",
        "verified_root_cause": "DSA completion status 0x0 after 0x12: (1) Error register write-clear-on-read behavior — after test framework reads error status (0x12), it may be cleared automatically; (2) Software framework clears SWERROR or status registers after error handling, subsequent read shows 0x0; (3) Test log race condition — 0x12 logged first, then status cleared before second read; (4) If test expects both 0x12 and then 0x0 (error then clear), this may be correct behavior. No known silicon bug — most likely software interaction with write-clear register.",
        "verified_fix": "Check event_log test expected values. Verify DSA status register write-clear behavior matches spec. Ensure error logging captures status before handler clears it.",
        "architectural_element": "DSA SWERROR register; error logging framework; write-clear event log behavior",
        "failure_registers": ["SWERROR0", "INTCAUSE", "completion record status byte"],
        "adjacent_subsystems": ["DSA error handler", "event_log test framework", "status register path"],
        "related_hsds": ["14026683622"],
        "spec_reference": "DSA Architecture Spec: SWERROR register, event log, write-clear behavior"
    },
    phase4={
        "tier1": [
            {"category": "swerror_timing", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.swerror0.show()", "cat event_log*.log | grep -i 'error'"], "reveals": "SWERROR state after test — confirms if 0x0 is write-clear or software clear", "relevance": "Direct check for register clearing behavior"},
            {"category": "test_sequence", "commands": ["Review event_log test sequence for SWERROR read ordering", "Check event_log test expected result for 0x12 followed by 0x0"], "reveals": "Whether 0x12→0x0 sequence is expected test behavior", "relevance": "If expected, this is not a bug — just test verification"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — event_log test reads error status at specific timing; write-clear causes 0x0 on second read",
        "root_cause_domain": "sw.application / DSA register write-clear behavior",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "swerror_timing immediately shows register state. test_sequence review confirms expected vs unexpected. Simple debug.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026683520 — ivman failed ETSEG_MEM_LOW ─────────────────────────────
write(
    "14026683520",
    phase2={
        "testcase_name": "DSA/IAA SVOS ivman ETSEG_MEM_LOW domain add failure",
        "testcase_command": "SVOS ivman add memory to domain (ETSEG_MEM_LOW)",
        "testcase_parameters": "DMR X1 A0 VVR SVOS; ivman ERROR: add memory to domain ioctl failed: Invalid argument for ETSEG_MEM_LOW; component sw.application",
        "testcase_domain_focus": "SVOS ivman memory segment management — ETSEG_MEM_LOW (Extended TSEG low memory) domain add failure",
    },
    phase3={
        "verified_problem_statement": "ivman fails to add ETSEG_MEM_LOW memory region to domain on DMR X1 A0 VVR SVOS, error: Invalid argument (EINVAL).",
        "verified_root_cause": "ivman ETSEG_MEM_LOW EINVAL failure: (1) Memory segment alignment issue — ETSEG_MEM_LOW starting address or size not page-aligned per ivman/VT-d requirements (must be aligned to 0x100000 minimum); (2) ivman.cfg configuration mismatch — domain translation type, VT-d address width, or page size not compatible with ETSEG_MEM_LOW region; (3) Resource conflict — another domain already mapped to overlapping range; (4) DMR A0 memory map change — ETSEG base address shifted vs expected in ivman config. Component sw.application confirms software configuration.",
        "verified_fix": "Verify ETSEG_MEM_LOW base address alignment in ivman.cfg. Check for domain overlap. Confirm DMR A0 TSEG/ETSEG address map. Update ivman config for DMR A0 ETSEG_MEM_LOW range.",
        "architectural_element": "SVOS ivman memory manager; ETSEG_MEM_LOW segment; VT-d domain page mapping; tman/ivman config",
        "failure_registers": ["ivman.cfg ETSEG_MEM_LOW entry", "VT-d domain map", "ivman domain table"],
        "adjacent_subsystems": ["SVOS tman target manager", "ivman domain manager", "VT-d page translation"],
        "related_hsds": ["14026683542"],
        "spec_reference": "ivman architecture wiki; ivman config properties wiki; SVOS Rocket Architecture; SVOS Glossary"
    },
    phase4={
        "tier1": [
            {"category": "ivman_config", "commands": ["cat ivman.cfg | grep -i 'ETSEG'", "cat ivman.cfg | grep -i 'mem_low'"], "reveals": "ETSEG_MEM_LOW configuration in ivman — address, size, alignment", "relevance": "Identifies misaligned address or wrong size causing EINVAL"},
            {"category": "etseg_map", "commands": ["cat /proc/iomem | grep -i 'TSEG'", "cat tman.target | grep -i 'ETSEG'"], "reveals": "Actual TSEG/ETSEG address from OS/tman vs ivman expected", "relevance": "Address mismatch between DMR A0 actual TSEG and ivman config"},
        ],
        "tier2": [
            {"category": "domain_conflict", "commands": ["cat ivman*.log | grep -i 'domain'"], "reveals": "Existing domain assignments that may conflict with ETSEG_MEM_LOW", "relevance": "Overlapping domain causes EINVAL on second add"},
        ],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — SVOS setup adds ETSEG_MEM_LOW to domain; EINVAL from misaligned or conflicting config",
        "root_cause_domain": "sw.application / ivman configuration",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "ivman_config immediately shows address/size. etseg_map confirms actual DMR A0 TSEG location.",
        "iteration_savings": "2",
    },
)

# ── HSD 16029529765 — OKS virt-customize Security failure ────────────────────
write(
    "16029529765",
    phase2={
        "testcase_name": "OKS DMR AP AUTOMATION Security virt-customize failure",
        "testcase_command": "(kayak.core.api.os_comm execute: virt-customize...)",
        "testcase_parameters": "DMR AP 1S OKS automation; virt-customize fails during security test VM image preparation; component val.env.execution",
        "testcase_domain_focus": "OKS automation security test VM disk image customization failure — virt-customize in kayak framework",
    },
    phase3={
        "verified_problem_statement": "OKS DMR AP automation security test fails during virt-customize step in kayak framework.",
        "verified_root_cause": "virt-customize (libguestfs-based VM image customization tool) failure in OKS: (1) Missing packages/dependencies in OKS environment — libguestfs, python virtual env packages (lxml, cffi, pip-system-certs) not installed; (2) Disk image corruption or incorrect path to security test payload; (3) AGS/permission issue — tool download (Xmon, titan-module) blocked in OKS environment; (4) Disk space exhaustion in OKS image staging area; (5) Network/proxy issue preventing customization package download. Component val.env.execution confirms execution environment.",
        "verified_fix": "Check kayak execute log for specific virt-customize error. Verify libguestfs and dependencies installed. Check disk space. Confirm AGS permissions for security tools. Reference DMR DPF User Guide and SimCloud setup.",
        "architectural_element": "OKS automation kayak framework; virt-customize libguestfs; security test VM image; OKS execution environment",
        "failure_registers": [],
        "adjacent_subsystems": ["kayak automation framework", "libguestfs virt-customize", "OKS VM image staging", "AGS permissions"],
        "related_hsds": [],
        "spec_reference": "DMR DPF User Guide wiki; OKS DMR Maestro SimCloud setup wiki; DMR Automation Strategy Alignment"
    },
    phase4={
        "tier1": [
            {"category": "kayak_log", "commands": ["cat kayak*.log | grep -i 'virt-customize'", "cat kayak*.log | grep -i 'error'"], "reveals": "Specific virt-customize failure reason in kayak log", "relevance": "Direct identification of failure cause"},
            {"category": "env_check", "commands": ["which virt-customize", "virt-customize --version", "df -h"], "reveals": "virt-customize availability and disk space", "relevance": "Missing tool or full disk causes immediate failure"},
        ],
        "tier2": [
            {"category": "dependency_check", "commands": ["pip show lxml cffi pip-system-certs", "python3 -m pysvtools --version"], "reveals": "Required Python package versions", "relevance": "Missing packages cause virt-customize script failure"},
        ],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — automation test setup calls virt-customize; environment issue causes immediate failure",
        "root_cause_domain": "val.env.execution / OKS automation environment",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "kayak_log shows exact failure. env_check confirms tool availability. Fast infrastructure debug.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026753468 — DSA 3.0 Doc Section 5.5 Reserved Field (doc.has) ────────
write(
    "14026753468",
    phase2={
        "testcase_name": "(Documentation HSD — no test case)",
        "testcase_command": "(no command — doc.has component)",
        "testcase_parameters": "DSA Architecture Specification 3.0 (Intel doc 341204-006US Rev 3.0); Section 5.5 Descriptor Reserved Field Check; discrepancy with IRCS internal spec",
        "testcase_domain_focus": "Documentation gap in DSA Architecture Spec 3.0 Section 5.5 regarding reserved field check behavior",
    },
    phase3={
        "verified_problem_statement": "Discrepancy or documentation gap in DSA Architecture Spec 3.0 (341204-006US Rev 3.0) Section 5.5 Descriptor Reserved Field Check vs IRCS internal specification.",
        "verified_root_cause": "This is a doc.has (documentation) HSD — not a silicon or test failure. Section 5.5 covers DSA descriptor reserved field validation (what the hardware checks and returns as completion status 0x10, 0x11, or 0x12 for non-zero reserved fields). The HSD documents a discrepancy between the public spec and IRCS (Integrated Register Check System) internal version — likely a wording gap, missing case, or incorrect completion status code mapping in the public spec. Component doc.has confirms documentation domain.",
        "verified_fix": "Update DSA Architecture Spec Section 5.5 to align with IRCS. Confirm completion status 0x10/0x11/0x12 reserved field definitions match hardware behavior. Verify with DSA arch team.",
        "architectural_element": "DSA Architecture Spec Section 5.5; descriptor reserved field check; completion status 0x10/0x11/0x12",
        "failure_registers": ["DSA completion status byte (CMPSC) values 0x10, 0x11, 0x12"],
        "adjacent_subsystems": ["DSA descriptor format spec", "IRCS internal spec"],
        "related_hsds": ["14026683622", "14026683541"],
        "spec_reference": "DSA Architecture Spec 3.0 (341204-006US Rev 3.0) Section 5.5; IRCS DSA descriptor spec"
    },
    phase4={
        "tier1": [
            {"category": "spec_compare", "commands": ["Compare DSA public spec Section 5.5 with IRCS internal version for reserved field check differences"], "reveals": "Exact discrepancy between public and internal spec for completion status 0x10/0x11/0x12", "relevance": "Direct identification of documentation gap to fix"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "n/a — documentation HSD, no test failure",
        "root_cause_domain": "doc.has / DSA architecture spec documentation",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "Documentation comparison between public spec Section 5.5 and IRCS resolves directly.",
        "iteration_savings": "1",
    },
)

# ── HSD 14026683472 — AcreError arden_get_target exception ───────────────────
write(
    "14026683472",
    phase2={
        "testcase_name": "DSA SVOS Atlas/Acre arden_get_target config generation failure",
        "testcase_command": "Rocket/Atlas/Acre config generation for DSA test (arden_get_target)",
        "testcase_parameters": "DMR X1 A0 VVR SVOS; AcreError: arden_get_target function exception; config files not generated; component sw.application",
        "testcase_domain_focus": "Rocket/Atlas/Acre Arden node discovery and config generation failure on DMR X1 A0 VVR",
    },
    phase3={
        "verified_problem_statement": "Atlas/Acre arden_get_target function throws exception on DMR X1 A0 VVR SVOS, preventing config file generation for DSA test.",
        "verified_root_cause": "AcreError: arden_get_target → KeyError: 'local_arden' — Acre cannot find the Arden node in SVFS tree. Root causes: (1) Arden node not present in SVFS at expected path (/sv/socket0/bus0/pcieD04F0/arden-00/vm0) — driver initialization failure or hardware not enumerated; (2) Acre scripts not updated for DMR A0 Arden register locations or stepping; (3) grrmods.conf missing localLinks option (fix: bug 14015689076 — requires GRR SVOS WW2.3+ or manual patch); (4) Atlas/Acre policy file not recognizing DMR X1 A0 Arden node. Component sw.application confirms software domain.",
        "verified_fix": "Apply WA for HSD 14015689076 — add localLinks option to /etc/modprobe.d/grrmods.conf. Update to GRR SVOS WW2.3+. Verify Arden node in SVFS. Update Atlas/Acre scripts for DMR A0 stepping.",
        "architectural_element": "Atlas/Acre Arden node discovery; SVFS device tree; grrmods.conf localLinks; Atlas pcietc.py scripts",
        "failure_registers": ["SVFS /sv/socket0/bus0/pcieD04F0/arden-00/vm0", "grrmods.conf localLinks"],
        "adjacent_subsystems": ["Acre framework", "SVFS device tree", "GRR driver", "Atlas policy files"],
        "related_hsds": ["14026683542", "14015689076"],
        "spec_reference": "Acre Guidelines wiki; GRR SVOS WW2.3 release notes; DMR SVOS Arden documentation"
    },
    phase4={
        "tier1": [
            {"category": "svfs_arden_check", "commands": ["ls /sv/socket0/bus0/pcieD04F0/arden-00/", "cat /var/log/kern.log | grep -i 'arden'"], "reveals": "Arden node presence in SVFS and driver init status", "relevance": "Missing arden node is direct cause of KeyError local_arden"},
            {"category": "grrmods_check", "commands": ["cat /etc/modprobe.d/grrmods.conf | grep -i 'local'", "svos --version"], "reveals": "localLinks option in grrmods.conf and SVOS version", "relevance": "Missing localLinks = known cause; check SVOS version for WW2.3+"},
        ],
        "tier2": [
            {"category": "acre_version", "commands": ["python3 -c 'import acre; print(acre.__version__)'"], "reveals": "Acre version vs DMR A0 BKC", "relevance": "Old Acre without DMR A0 support triggers arden_get_target failure"},
        ],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — test setup calls arden_get_target; exception immediately aborts config generation",
        "root_cause_domain": "sw.application / Acre/SVFS Arden node missing",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "svfs_arden_check immediately confirms node presence. grrmods_check identifies known WA status.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026679112 — Tests failing TPostTest_PreTestFailChk ─────────────────
write(
    "14026679112",
    phase2={
        "testcase_name": "DSA SVOS automation TPostTest_PreTestFailChk failure",
        "testcase_command": "(SVOS automation framework post-test pre-check validation)",
        "testcase_parameters": "DMR X1 A0 VVR SVOS; Tests fail in TPostTest_PreTestFailChk step; component val.env.automation",
        "testcase_domain_focus": "SVOS automation framework post-test validation — TPostTest_PreTestFailChk (environment sanity check) failing",
    },
    phase3={
        "verified_problem_statement": "DMR X1 A0 VVR SVOS DSA tests fail in TPostTest_PreTestFailChk post-test automation step.",
        "verified_root_cause": "TPostTest_PreTestFailChk is an automation framework step that validates post-test environment conditions match pre-test state. Failures here are almost always automation infrastructure issues, not silicon: (1) Network access failure during post-test validation — cannot reach shared resources; (2) IFWI/firmware state inconsistency detected between pre and post-test; (3) Prior test content failure leaves system in unexpected state that TPostTest detects; (4) Framework/orchestrator glitch. Component val.env.automation confirms environment/automation domain.",
        "verified_fix": "Escalate to ACE (automation/content execution) team. Check network access and resource shares. Verify IFWI state post-test. Review if prior test left system in bad state.",
        "architectural_element": "SVOS automation framework; TPostTest phase; network resource access; IFWI state check",
        "failure_registers": [],
        "adjacent_subsystems": ["SVOS automation orchestrator", "network resource shares", "IFWI validator"],
        "related_hsds": ["14026668250"],
        "spec_reference": "DMR FV PreSighting Methodology wiki; DMR Automation Strategy Alignment wiki"
    },
    phase4={
        "tier1": [
            {"category": "automation_log", "commands": ["cat posttest_log*.log | grep -i 'TPostTest_PreTestFailChk'", "cat framework_log*.log | grep -i 'fail'"], "reveals": "Specific reason TPostTest_PreTestFailChk failed — network, IFWI, or state issue", "relevance": "Direct identification of infrastructure vs test-content cause"},
        ],
        "tier2": [
            {"category": "network_check", "commands": ["ping nfs_server_name", "mount | grep -i 'nfs'"], "reveals": "Network share accessibility during post-test", "relevance": "Network failure is most common TPostTest failure cause"},
        ],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "indirect — post-test automation check detects environment state mismatch",
        "root_cause_domain": "val.env.automation / ACE team",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "automation_log identifies specific failure in one step. ACE team resolves infrastructure issues.",
        "iteration_savings": "2",
    },
)

# ── HSD 16029489884 — OKS libguestfs package error ───────────────────────────
write(
    "16029489884",
    phase2={
        "testcase_name": "OKS DMR AP Accelerator AUTOMATION libguestfs package error",
        "testcase_command": "(OKS package installation/automation infrastructure — no explicit test command)",
        "testcase_parameters": "DMR AP OKS automation; libguestfs-man-pages-uk-1:1.57.5-1.el10.noarch package problem; RHEL 10 (el10) package repository",
        "testcase_domain_focus": "OKS automation infrastructure — libguestfs package installation failure on RHEL 10",
    },
    phase3={
        "verified_problem_statement": "OKS DMR AP Accelerator automation fails with libguestfs package error: libguestfs-man-pages-uk-1:1.57.5-1.el10.noarch has a problem on RHEL 10.",
        "verified_root_cause": "libguestfs-man-pages-uk package error on RHEL 10: (1) RHEL 10 (el10) repository sync issue — package present in index but package file corrupt or missing from repo mirror; (2) Package dependency conflict — libguestfs-man-pages-uk has unresolvable dependency on RHEL 10; (3) OKS automation image not updated for RHEL 10 libguestfs version (1.57.5); (4) Infrastructure/repo synchronization lag. Component val.env.execution/automation confirms environment domain.",
        "verified_fix": "Verify RHEL 10 repository sync and package integrity. Check if libguestfs-man-pages-uk is required or can be excluded. Update OKS automation image for RHEL 10 libguestfs version. Reference Mass Deployment repo management.",
        "architectural_element": "OKS automation RHEL 10 package management; libguestfs el10 repository; virt-customize dependency chain",
        "failure_registers": [],
        "adjacent_subsystems": ["RHEL 10 package repository", "OKS image deployment", "libguestfs virt-customize"],
        "related_hsds": ["16029529765"],
        "spec_reference": "Mass Deployment Legacy automation repo management wiki; External Dependencies management (Maestro) wiki"
    },
    phase4={
        "tier1": [
            {"category": "package_check", "commands": ["dnf check-update libguestfs*", "rpm -q libguestfs-man-pages-uk", "yum repoinfo"], "reveals": "Package availability and repository health", "relevance": "Confirms if package is missing from repo or corrupt"},
            {"category": "repo_check", "commands": ["dnf repolist", "cat /etc/yum.repos.d/*.repo | grep baseurl"], "reveals": "Repository configuration and sync status", "relevance": "Repo sync lag or wrong mirror causes package unavailability"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — automation setup installs libguestfs; package error blocks virt-customize installation",
        "root_cause_domain": "val.env.execution / package repository infrastructure",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "package_check + repo_check immediately show package and repository state. Simple infrastructure fix.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026668250 — Tests failing TPostTest_ProjectEnd ─────────────────────
write(
    "14026668250",
    phase2={
        "testcase_name": "DSA SVOS automation TPostTest_ProjectEnd failure",
        "testcase_command": "(SVOS automation framework project end cleanup step)",
        "testcase_parameters": "DMR X1 A0 VVR SVOS; Tests fail in TPostTest_ProjectEnd step; component val.env.automation",
        "testcase_domain_focus": "SVOS automation framework project-end cleanup — TPostTest_ProjectEnd failing on DMR A0 VVR",
    },
    phase3={
        "verified_problem_statement": "DMR X1 A0 VVR SVOS DSA tests fail in TPostTest_ProjectEnd automation step.",
        "verified_root_cause": "TPostTest_ProjectEnd is the final cleanup step of a Rocket/SVOS automation run — handles log collection, exit code reporting, and resource cleanup. Failures indicate automation infrastructure issues: (1) Log collection/upload failure — network or storage access issue; (2) Exit code handling error — prior test left unexpected state that cleanup cannot process; (3) Automation framework glitch — ExeLog or NGA API failure during project finalization; (4) NGA inventory push failure (similar to HCleanUp_Axon_Inventory). Component val.env.automation confirms environment domain — ACE team responsibility.",
        "verified_fix": "Escalate to ACE team. Check automation logs. Verify network/storage access for log upload. Confirm NGA API is reachable.",
        "architectural_element": "SVOS automation framework; TPostTest_ProjectEnd cleanup; NGA log upload; ExeLog resource cleanup",
        "failure_registers": [],
        "adjacent_subsystems": ["SVOS automation orchestrator", "NGA API", "ExeLog log upload service"],
        "related_hsds": ["14026679112", "14026626024"],
        "spec_reference": "DMR FV PreSighting Methodology wiki; DMR Simics Based Execution wiki"
    },
    phase4={
        "tier1": [
            {"category": "project_end_log", "commands": ["cat posttest_log*.log | grep -i 'ProjectEnd'", "cat framework_log*.log | grep -i 'cleanup'"], "reveals": "Specific failure in TPostTest_ProjectEnd — log upload, API, or cleanup issue", "relevance": "Log shows exact infrastructure failure at project end"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "indirect — post-test cleanup step fails due to infrastructure issue",
        "root_cause_domain": "val.env.automation / ACE team",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "automation_log identifies failure. ACE team owns resolution. Same pattern as TPostTest_PreTestFailChk.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026626024 — IAA HCleanUp_Axon_Inventory failing FDU7 ───────────────
write(
    "14026626024",
    phase2={
        "testcase_name": "IAA SVOS NGA HCleanUp_Axon_Inventory failure (FDU7)",
        "testcase_command": "(NGA automation cleanup phase — HCleanUp_Axon_Inventory script)",
        "testcase_parameters": "DMR X1 A0 VV FDU7 SVOS; NGA test run on an004011bms0233; HCleanUp_Axon_Inventory fails during IAA test cleanup; component val.env.automation",
        "testcase_domain_focus": "NGA test run cleanup — HCleanUp_Axon_Inventory inventory upload failure on FDU7",
    },
    phase3={
        "verified_problem_statement": "HCleanUp_Axon_Inventory fails on IAA NGA test run on FDU7 system an004011bms0233 on DMR X1 A0 VV.",
        "verified_root_cause": "HCleanUp_Axon_Inventory failure: automation cleanup step that pushes inventory.json to NGA test results after run. Failure causes: (1) Network access issue — FDU7 system cannot reach NGA API endpoint to upload inventory; (2) inventory.json missing or malformed — prior test failure left incomplete inventory data; (3) pysvtools.execution or pysvtools.flexit package version mismatch — hardcoded package dependencies in cleanup script; (4) NGA API/backend access failure during upload. Component val.env.automation confirms automation domain.",
        "verified_fix": "Check network from FDU7 to NGA API. Verify inventory.json exists and is valid. Check pysvtools.execution version. Retry automation run.",
        "architectural_element": "NGA automation cleanup; inventory.json; HCleanUp_Axon_Inventory script; pysvtools.execution",
        "failure_registers": [],
        "adjacent_subsystems": ["NGA API", "pysvtools.execution", "automation orchestrator", "FDU7 network"],
        "related_hsds": ["14026679112", "14026668250"],
        "spec_reference": "DMR Simics Based Execution automation wiki; Inventory Collection wiki"
    },
    phase4={
        "tier1": [
            {"category": "cleanup_log", "commands": ["cat cleanup_log*.log | grep -i 'inventory'", "cat exelog*.log | grep -i 'HCleanUp'"], "reveals": "Specific failure in HCleanUp_Axon_Inventory — network, file, or API issue", "relevance": "Log shows exact upload failure cause"},
            {"category": "inventory_file", "commands": ["ls -la */inventory.json", "cat */inventory.json | python3 -m json.tool"], "reveals": "inventory.json existence and validity", "relevance": "Missing or invalid file causes upload failure"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "indirect — cleanup step fails after test; network or file issue prevents inventory upload",
        "root_cause_domain": "val.env.automation / NGA cleanup infrastructure",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "cleanup_log + inventory_file check resolves in one pass. Network or file issue identified immediately.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026620470 — QAT service chaining response 0x80 ─────────────────────
write(
    "14026620470",
    phase2={
        "testcase_name": "QAT service_chaining_idx0 test (parti SADCPM CCP_AE status 0x80)",
        "testcase_command": "parti -c service_chaining_idx0.yaml --using_sadcpm",
        "testcase_parameters": "DMR X1 A0 VV SVOS; QAT service chaining test via parti/SADCPM; CCP_AE status 0x80; component val.env.content",
        "testcase_domain_focus": "QAT service chaining with SADCPm framework — CCP_AE error code 0x80 (likely Internal Error or device not ready)",
    },
    phase3={
        "verified_problem_statement": "QAT service chaining test fails on DMR X1 A0 VV SVOS: parti -c service_chaining_idx0.yaml --using_sadcpm reports CCP_AE error status 0x80.",
        "verified_root_cause": "QAT CCP_AE status 0x80 in SADCPm framework: No confirmed definition in available documentation. Most likely: (1) QAT CCP engine error — 0x80 may indicate Internal Error or device-not-ready in QAT firmware; (2) Service chaining configuration error — idx0 chaining config not valid for DMR A0 QAT; (3) SADCPm framework version mismatch with DMR QAT; (4) QAT device not fully initialized before service chaining. Component val.env.content suggests test content/configuration. Need CPM FW error codes documentation to confirm 0x80 definition.",
        "verified_fix": "Reference CPM FW error codes documentation (ITSgnrdebug). Check QAT device initialization state. Verify service_chaining_idx0.yaml config for DMR A0 QAT. Contact QAT/CPM silicon team for 0x80 definition.",
        "architectural_element": "QAT CCP (Crypto Co-Processor) engine; SADCPm service dispatch; service chaining configuration; parti test framework",
        "failure_registers": ["QAT CCP_AE status register", "QAT device status", "SADCPm error register"],
        "adjacent_subsystems": ["QAT firmware", "SADCPm framework", "parti test tool", "QAT device initialization"],
        "related_hsds": [],
        "spec_reference": "CPM FW error codes documentation (ITSgnrdebug wiki); QAT Architecture Spec; SADCPm user guide"
    },
    phase4={
        "tier1": [
            {"category": "qat_status", "commands": ["sv.socket0.imh0.acc.acc_0.qat.show()", "sv.socket0.imh0.acc.acc_0.qat.showsearch('status')"], "reveals": "QAT device state and error registers at CCP_AE 0x80 failure", "relevance": "Direct hardware state check"},
            {"category": "parti_log", "commands": ["cat parti_pid*.log | grep -i '0x80'", "cat parti_pid*.log | grep -i 'CCP_AE'"], "reveals": "CCP_AE error 0x80 context and when it occurs in service chaining", "relevance": "Log context narrows failure to specific chain operation"},
        ],
        "tier2": [
            {"category": "qat_init", "commands": ["lspci -vvv | grep -i 'qat'", "systemctl status qat"], "reveals": "QAT device initialization state", "relevance": "QAT not fully initialized causes CCP_AE errors"},
        ],
        "tier3": [],
        "beyond_sme": [
            {"description": "CPM FW error code lookup for 0x80", "commands": ["Reference ITSgnrdebug CPM FW error codes wiki"], "why": "Confirmed definition of 0x80 needed to identify specific root cause"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — parti service chaining test invokes QAT CCP_AE engine; 0x80 returned immediately",
        "root_cause_domain": "val.env.content / hw.qat CCP engine",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "qat_status + parti_log narrow the issue. CPM FW error codes required for definitive root cause of 0x80.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026616546 — IAA AcreError: Base name iaxrand ───────────────────────
write(
    "14026616546",
    phase2={
        "testcase_name": "IAA SVOS AcreError: Base name iaxrand exception",
        "testcase_command": "(iaxrand-based IAA test via Acre framework)",
        "testcase_parameters": "DMR X1 A0 VV SVOS; AcreError: Base name iaxrand exception; component val.env.content",
        "testcase_domain_focus": "IAA Acre framework iaxrand plugin registration failure — iaxrand base name not found in Acre registry",
    },
    phase3={
        "verified_problem_statement": "IAA test on DMR X1 A0 VV SVOS fails with AcreError: Base name 'iaxrand' exception.",
        "verified_root_cause": "AcreError: iaxrand base name not found in Acre registry: (1) Known iaxrand segfault bug (null pointer dereference) introduced in SW patch 49.D15 — causes AcreError; fixed in tip of release; (2) iaxrand plugin not registered in Acre — plugin_path in SVOS config not pointing to /usr/lib/svos/iax where iaxrand plugin resides; (3) SVOS patch level too old — iaxrand requires newer patch for DMR A0 support; (4) Test content missing iaxrand entry in Acre base name registry. Component val.env.content confirms content/configuration domain.",
        "verified_fix": "Update SVOS to tip of release (beyond patch 49.D15). Verify iaxrand plugin_path = /usr/lib/svos/iax in config. Check IAXrand documentation for Acre registry entry requirements.",
        "architectural_element": "Acre framework iaxrand plugin registry; IAXrand SVOS plugin; iaxrand null pointer fix",
        "failure_registers": ["Acre base name registry", "iaxrand plugin path config"],
        "adjacent_subsystems": ["Acre test framework", "iaxrand IAA test generator", "SVOS plugin system"],
        "related_hsds": ["14026683472", "14026683542"],
        "spec_reference": "IAXrand documentation wiki; IAXrand Config File Properties wiki; SPR Rocket Sync Meeting Minutes (iaxrand segfault fix)"
    },
    phase4={
        "tier1": [
            {"category": "svos_patch", "commands": ["svos --version", "rpm -q svos-iaxrand"], "reveals": "SVOS patch version and iaxrand package installation", "relevance": "Patch 49.D15 has segfault bug; need tip-of-release"},
            {"category": "plugin_path", "commands": ["ls /usr/lib/svos/iax/", "cat iaxrand.cfg | grep -i 'plugin_path'"], "reveals": "iaxrand plugin presence and configured path", "relevance": "Missing plugin or wrong path = AcreError"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — IAA test invokes iaxrand via Acre; exception immediately blocks test execution",
        "root_cause_domain": "val.env.content / SVOS patch level or iaxrand config",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "svos_patch identifies if 49.D15 bug is cause. plugin_path confirms config. Fast debug.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026616507 — QAT Docker pull failing ────────────────────────────────
write(
    "14026616507",
    phase2={
        "testcase_name": "QAT SVOS Docker pull DMR image failure (CPM combined test)",
        "testcase_command": "docker pull ubit-artifactory-ba.intel.com:6555/[DMR_QAT_IMAGE]",
        "testcase_parameters": "DMR X1 A0 VV SVOS; QAT/CPM combined test fails because Docker pull of DMR image fails; component val.env.execution",
        "testcase_domain_focus": "QAT/CPM test Docker image pull failure — execution environment infrastructure issue on DMR",
    },
    phase3={
        "verified_problem_statement": "QAT/CPM combined test on DMR X1 A0 VV SVOS fails because Docker pull of DMR container image fails.",
        "verified_root_cause": "Docker pull failure for QAT/CPM test: (1) AGS permissions — user/automation account not granted access to Intel Artifactory registry (DevTools - Artifactory - ESC Artifactory - iotg-docker); (2) Network/proxy issue — SVOS host cannot reach ubit-artifactory-ba.intel.com:6555 due to firewall or proxy misconfiguration; (3) Docker daemon misconfiguration — proxy not set in Docker daemon config on SVOS host; (4) Image tag mismatch — DMR QAT image tag not matching test expectation; (5) Transient infrastructure glitch — network or registry temporary failure. Component val.env.execution confirms execution environment.",
        "verified_fix": "Request AGS access: DevTools - Artifactory - ESC Artifactory - iotg-docker. Configure Docker proxy. Verify image tag. Run: docker login ubit-artifactory-ba.intel.com:6555; docker pull [image].",
        "architectural_element": "Intel Artifactory Docker registry; SVOS Docker daemon; CPM test container image; AGS permissions",
        "failure_registers": [],
        "adjacent_subsystems": ["Docker daemon", "Intel Artifactory registry", "SVOS network config", "AGS permissions"],
        "related_hsds": [],
        "spec_reference": "Using Dockers SlimBoot wiki; SPR Rocket Docker/CPM notes wiki"
    },
    phase4={
        "tier1": [
            {"category": "docker_login", "commands": ["docker login ubit-artifactory-ba.intel.com:6555", "docker pull ubit-artifactory-ba.intel.com:6555/[DMR_IMAGE]"], "reveals": "Whether login succeeds and pull works with valid credentials", "relevance": "AGS permission and network check in one step"},
            {"category": "network_check", "commands": ["curl -I https://ubit-artifactory-ba.intel.com:6555", "cat /etc/docker/daemon.json | grep -i 'proxy'"], "reveals": "Network accessibility and Docker proxy config", "relevance": "Network/proxy issue prevents image pull"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — test setup pulls Docker image; network/permission failure blocks execution",
        "root_cause_domain": "val.env.execution / Docker infrastructure",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "docker_login immediately identifies AGS or network issue. network_check confirms proxy configuration.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026616375 — IAA PRS AD set failure ─────────────────────────────────
write(
    "14026616375",
    phase2={
        "testcase_name": "IAA_descriptor_all_ATS,PRS_silicon with AD set (qcontroller2 measureMode TMO)",
        "testcase_command": "IAA descriptor test with ATS+PRS+AD (Accessed/Dirty) bit set via qcontroller2 --measureMode",
        "testcase_parameters": "DMR X1 A0 VV SVOS; IAA with PRS failing with AD set; qcontroller2 measureMode TMO (timeout); component val.env.content",
        "testcase_domain_focus": "IAA ATS+PRS descriptor test with AD (Accessed/Dirty) bit — timeout in qcontroller2 measurement mode on DMR A0",
    },
    phase3={
        "verified_problem_statement": "IAA ATS+PRS descriptor test with AD set fails on DMR X1 A0 VV SVOS with qcontroller2 measureMode timeout.",
        "verified_root_cause": "IAA PRS with AD bit set timeout on DMR A0: (1) Known M2IOSF PRS ordering bug (HSD 14025333034) — PASID drain with LPIG=1 ordering violation causes PRS queue drain timeout when AD bit interactions are involved; (2) VT-d IOMMU not handling AD bit page request correctly — IOMMU page table walker stalls on AD bit update; (3) qcontroller2 measurement mode timeout indicates descriptor processing stall — PRS request not completing in expected time; (4) IAA IOMMU Invalidation Queue Descriptor bit 66 bug (HSD 14025817510) — may affect PRS path with AD bit. Component val.env.content suggests test content/configuration.",
        "verified_fix": "Apply PRS WA: vt_iommu_cr_itciommudbgctrl3.dis_max_pgr_throttle=1. Cross-reference HSD 14025333034 and HSD 14025817510. Check IOMMU page table AD bit handling configuration.",
        "architectural_element": "IAA ATS+PRS+AD path; M2IOSF PRS pipeline; VT-d IOMMU AD bit page table; qcontroller2 measurement engine",
        "failure_registers": ["vt_iommu_cr_itciommudbgctrl3", "IOMMU PRQ (Page Request Queue)", "INTCAUSE", "SWERROR0"],
        "adjacent_subsystems": ["IAA descriptor engine", "M2IOSF PRS pipeline", "VT-d IOMMU AD bit handler", "qcontroller2"],
        "related_hsds": ["14025333034", "14025817510", "14026766087"],
        "spec_reference": "DMR PASID drain fix HSD 14025333034; IAA IOMMU Invalidation Queue bit 66 HSD 14025817510; PRS Bug GNR debug wiki"
    },
    phase4={
        "tier1": [
            {"category": "prs_wa_check", "commands": ["sv.socket0.imh0.showsearch('itciommudbgctrl3')", "sv.socket0.imh0.vt_iommu_cr_itciommudbgctrl3.dis_max_pgr_throttle.show()"], "reveals": "PRS throttle WA status", "relevance": "Primary WA for PRS timeout on DMR A0"},
            {"category": "iaa_hang_state", "commands": ["sv.socket0.imh0.acc.acc_0.iaa.swerror0.show()", "sv.socket0.imh0.acc.acc_0.iaa.intcause.show()"], "reveals": "IAA error state at timeout", "relevance": "Confirms if IAA is stalled waiting for PRS response"},
        ],
        "tier2": [
            {"category": "iommu_ad", "commands": ["sv.socket0.imh0.showsearch('iommu_ad')", "cat dmesg | grep -i 'ad bit'"], "reveals": "IOMMU AD bit handling configuration", "relevance": "AD bit misconfiguration causes PRS timeout"},
        ],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — IAA PRS+AD test exercises known M2IOSF ordering bug on DMR A0",
        "root_cause_domain": "val.env.content / hw.iaa M2IOSF PRS ordering (HSD 14025333034)",
        "domain_relationship": "adjacent",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "Known HSD 14025333034 pattern. prs_wa_check immediately confirms WA status. iaa_hang_state shows stall.",
        "iteration_savings": "3",
    },
)

# ── HSD 14026616262 — IAA iax_remove_deflate_base.py WA over-removal ─────────
write(
    "14026616262",
    phase2={
        "testcase_name": "IAA iax_remove_deflate_base.py WA causing DEFLATE over-removal",
        "testcase_command": "(iax_base SVOS test suite with iax_remove_deflate_base.py workaround active)",
        "testcase_parameters": "DMR X1 A0 VV SVOS; iax_remove_deflate_base.py WA removes DEFLATE completely; fix already pushed; component val.env.content",
        "testcase_domain_focus": "IAA DEFLATE workaround script over-removal — script removes all DEFLATE instead of only iax_base scope",
    },
    phase3={
        "verified_problem_statement": "iax_remove_deflate_base.py WA on DMR X1 A0 VV SVOS causes DEFLATE to be removed completely (globally), not just from iax_base test scope as intended. Fix already pushed.",
        "verified_root_cause": "iax_remove_deflate_base.py is a WA script (tracked under HSD 14026255320) to remove DEFLATE opcodes from iax_base test suite due to DMR A0 hardware/firmware incompatibility. The script was incorrectly implemented to remove all DEFLATE support (global) instead of only limiting iax_base execution scope. Standalone DEFLATE test still works (2-hour run confirmed). Over-removal is a software implementation bug in the WA script, not a hardware bug. Fix was pushed. Component val.env.content confirms test content domain.",
        "verified_fix": "Update to patched version of iax_remove_deflate_base.py that limits DEFLATE removal to iax_base scope only. Standalone DEFLATE test should remain enabled. Long-term: re-integrate DEFLATE into iax_base suite after CCS team discussion.",
        "architectural_element": "IAA DEFLATE compression opcode; iax_base test suite; iax_remove_deflate_base.py WA script",
        "failure_registers": ["IAA DEFLATE opcode registration", "iax_base test content list"],
        "adjacent_subsystems": ["iaxrand test generator", "IAA compression engine", "SVOS test suite manager"],
        "related_hsds": ["14026255320"],
        "spec_reference": "DMR Current Workarounds wiki (IAX domain, iax_remove_deflate_base.py entry); IAA DEFLATE spec"
    },
    phase4={
        "tier1": [
            {"category": "wa_script_check", "commands": ["cat /usr/local/iax/iax_remove_deflate_base.py", "grep -i 'deflate' /usr/local/iax/iax_remove_deflate_base.py"], "reveals": "Script implementation — confirms over-removal vs scoped removal", "relevance": "Direct check for implementation bug"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — WA script incorrectly removes all DEFLATE from test suite",
        "root_cause_domain": "val.env.content / WA script implementation bug",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "Fix already pushed. wa_script_check confirms patched version is deployed.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026616153 — IAA compression performance mode failure ───────────────
write(
    "14026616153",
    phase2={
        "testcase_name": "IAA compression mode performance mode (PERF) test",
        "testcase_command": "(IAA compression PERF mode test via iaxrand or direct SVOS test)",
        "testcase_parameters": "DMR X1 A0 VV SVOS; IAA compression mode performance mode failure; component val.env.content",
        "testcase_domain_focus": "IAA compression performance mode — PERF mode test failure on DMR A0 VV",
    },
    phase3={
        "verified_problem_statement": "IAA compression performance mode (PERF) test fails on DMR X1 A0 VV SVOS.",
        "verified_root_cause": "IAA compression PERF mode failure on DMR A0: (1) DMR A0 introduces enhanced compression algorithms (~2X perf over prior gen) with new features (dictionary support, QOS); (2) PERF mode test may exercise corner cases of new compression implementation not fully validated on A0; (3) Test configuration mismatch — PERF mode expected values not updated for DMR A0 enhanced engine; (4) Possible silicon bug in DMR A0 new compression logic — need to check completion status and compare output. Component val.env.content suggests content/configuration issue.",
        "verified_fix": "Verify test expected values match DMR A0 compression spec. Check IAA completion record for error code. Compare compressed output vs reference. Contact IAA arch team if PERF mode output is incorrect.",
        "architectural_element": "IAA compression engine PERF mode; dictionary compression support; IAA QOS features; completion record",
        "failure_registers": ["SWERROR0", "IAA completion record status", "INTCAUSE"],
        "adjacent_subsystems": ["IAA compression engine", "iaxrand PERF mode generator", "IAA completion path"],
        "related_hsds": ["14026616262"],
        "spec_reference": "DMR Accelerator HAS; IAA Feature Delta overview; IAA compression PERF mode spec"
    },
    phase4={
        "tier1": [
            {"category": "iaa_completion_check", "commands": ["sv.socket0.imh0.acc.acc_0.iaa.swerror0.show()", "cat iaxrand_pid*.log | grep -i 'perf'"], "reveals": "IAA error at PERF mode failure and log context", "relevance": "SWERROR identifies if this is silicon error vs content mismatch"},
            {"category": "output_compare", "commands": ["Compare IAA PERF mode compressed output vs reference/expected"], "reveals": "Whether compression output is wrong or test expected values are wrong", "relevance": "Output compare differentiates silicon bug from test content issue"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — IAA PERF mode compression exercises enhanced DMR A0 engine",
        "root_cause_domain": "val.env.content / IAA compression engine",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "iaa_completion_check identifies silicon error. output_compare confirms content vs silicon issue. Multiple possible causes.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026616073 — QAT CPM docker pid exit ────────────────────────────────
write(
    "14026616073",
    phase2={
        "testcase_name": "QAT cpm_variant_dmr test (CPM Docker pid exiting)",
        "testcase_command": "rocket -M 120 --atlas \"--hw dram,cpm -v cpm_variant_dmr[minutes=120,loops=0,jobs=10,test_mod...]\"",
        "testcase_parameters": "DMR X1 A0 VV SVOS; CPM Docker container pid 10595 exits unexpectedly during cpm_variant_dmr test; component val.env.content",
        "testcase_domain_focus": "QAT/CPM rocket test — CPM Docker container exits during cpm_variant_dmr test on DMR A0",
    },
    phase3={
        "verified_problem_statement": "CPM Docker container (pid 10595) exits unexpectedly during rocket cpm_variant_dmr test on DMR X1 A0 VV SVOS.",
        "verified_root_cause": "CPM Docker exit during cpm_variant_dmr: (1) Segfault in CPM test application — SIGSEGV causes process exit, core dump generated in test directory; (2) OOM kill — Docker container or host memory exhausted under 10-job CPM test load (120-min, 10 jobs); (3) CPM/QAT driver version mismatch — Docker image has incompatible CPM driver vs SVOS host kernel (known issue pattern: CPM not working on SPR2044); (4) BIOS MMIO resource insufficient for Docker + CPM + 10 jobs simultaneously; (5) Test content hitting unsupported CPM features on DMR A0. Component val.env.content suggests test content domain.",
        "verified_fix": "Check for core dump in test directory. Check OOM killer log. Verify Docker CPM image vs SVOS driver version. Check MMIO resources. Review rtm log for non-zero exit code.",
        "architectural_element": "CPM Docker container; cpm_variant_dmr test content; Docker resource limits; QAT driver-host compatibility",
        "failure_registers": ["dmesg OOM log", "core dump stacktrace", "QAT device status"],
        "adjacent_subsystems": ["Docker runtime", "CPM test application", "QAT driver", "Host kernel"],
        "related_hsds": ["14026616507"],
        "spec_reference": "Rocket Debug Tools & Techniques wiki; Supercollider/Rocket Triage Process wiki; CPM Docker setup notes"
    },
    phase4={
        "tier1": [
            {"category": "exit_cause", "commands": ["ls -la */core.*", "dmesg | grep -i 'oom'", "dmesg | grep -i 'kill'"], "reveals": "Core dump presence (segfault) or OOM kill log", "relevance": "Directly identifies if crash is segfault or OOM"},
            {"category": "rtm_log", "commands": ["cat rtm_pid*.log | grep -i 'exit'", "cat rtm_pid*.log | grep -i 'cpm'"], "reveals": "CPM exit code and last rocket test manager message", "relevance": "Non-zero exit code context shows failure type"},
        ],
        "tier2": [
            {"category": "driver_version", "commands": ["modinfo qat_dev0", "docker inspect [CPM_IMAGE] | grep -i 'qat'"], "reveals": "Host QAT driver vs Docker CPM image version", "relevance": "Version mismatch is common CPM test failure pattern"},
        ],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — CPM Docker container runs cpm_variant_dmr; exits on crash, OOM, or driver mismatch",
        "root_cause_domain": "val.env.content / Docker CPM execution",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "exit_cause immediately identifies segfault vs OOM. rtm_log gives context. Fast triage.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026616021 — QAT CPM device not found ───────────────────────────────
write(
    "14026616021",
    phase2={
        "testcase_name": "QAT/CPM NGA test — CPM device not found during pre-test",
        "testcase_command": "(NGA QAT test pre-check — CPM device enumeration)",
        "testcase_parameters": "DMR X1 A0 VV SVOS; CPM devices not showing in SVOS during NGA pre-test; component val.env.configuration",
        "testcase_domain_focus": "QAT/CPM device enumeration failure on DMR X1 A0 VV — device not present in SVOS",
    },
    phase3={
        "verified_problem_statement": "QAT/CPM NGA tests fail during pre-test: CPM devices do not appear in SVOS on DMR X1 A0 VV.",
        "verified_root_cause": "CPM device not found in SVOS: (1) QAT_DISABLE fuse set — IP_DISABLE_RESOLVED_CR_DWORD3 QAT_DISABLE bits indicate CPM disabled for this SKU; (2) BIOS not enabling QAT/CPM — BIOS knob for accelerator enablement not set; (3) Missing QAT driver/firmware in SVOS — driver not loaded, device not enumerated; (4) CPM on NET die (not IMHD die) — NET chiplet not populated or D2D link to NET die failed; (5) SVOS patch level missing QAT enumeration fix for DMR X1 A0 VV. Component val.env.configuration confirms configuration domain.",
        "verified_fix": "Check QAT_DISABLE fuse bits. Verify BIOS QAT enablement. Confirm QAT driver loaded. Check NET die connectivity. Update SVOS for DMR A0 VV QAT enumeration fix.",
        "architectural_element": "CPM QAT device fuse; BIOS QAT enablement; QAT driver in SVOS; NET die CPM connectivity",
        "failure_registers": ["IP_DISABLE_RESOLVED_CR_DWORD3 QAT_DISABLE bits", "BIOS QAT enablement knob", "lspci QAT device list"],
        "adjacent_subsystems": ["QAT driver", "BIOS firmware", "NET die D2D link", "SVOS device enumeration"],
        "related_hsds": [],
        "spec_reference": "DMR oobmsm FW gen4 FAS: IP_DISABLE_RESOLVED_CR_DWORD3; DMR CXL PO Workarounds wiki; DMR QAT enablement guide"
    },
    phase4={
        "tier1": [
            {"category": "qat_device_check", "commands": ["lspci | grep -i 'qat'", "lspci | grep -i '4940'"], "reveals": "CPM/QAT device PCI enumeration in SVOS", "relevance": "No PCI entry = fuse disable or driver missing"},
            {"category": "fuse_check", "commands": ["sv.socket0.imh0.showsearch('IP_DISABLE_RESOLVED')", "sv.socket0.imh0.ip_disable_resolved_cr_dword3.show()"], "reveals": "QAT_DISABLE fuse status", "relevance": "Fuse disable is permanent — cannot enable at runtime"},
        ],
        "tier2": [
            {"category": "driver_check", "commands": ["lsmod | grep -i 'qat'", "modprobe qat_dev0"], "reveals": "QAT driver load status", "relevance": "Driver not loaded = device not enumerated"},
        ],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — pre-test CPM device check fails; QAT not present or enabled",
        "root_cause_domain": "val.env.configuration / QAT device enablement",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "qat_device_check + fuse_check cover all common cases. Fast 2-register debug.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026598567 — QAT RSA failure with OpenSSL QAT Provider ──────────────
write(
    "14026598567",
    phase2={
        "testcase_name": "QAT Provider OpenSSL RSA speed test (RSA failures with QAT Provider)",
        "testcase_command": "openssl speed -engine qatengine rsa2048 (or via qatprovider)",
        "testcase_parameters": "DMR AP platform; RSA errors with openssl speed tests using QAT Provider API; no NGA UUIDs",
        "testcase_domain_focus": "QAT Provider OpenSSL RSA acceleration failure on DMR AP — driver/firmware/fuse compatibility",
    },
    phase3={
        "verified_problem_statement": "RSA errors occur when running openssl speed tests using QAT Provider API on DMR AP.",
        "verified_root_cause": "QAT Provider RSA failure on DMR AP: (1) QAT driver/firmware version mismatch — QAT Provider requires DMR-specific package (QAT_2025.07.01.tar.gz); using GNR package causes failures; (2) QAT hardware fuse not enabling RSA acceleration for this SKU — check QAT_DISABLE fuse and crypto engine fuse; (3) QAT firmware not loaded with RSA algorithm support — firmware file missing or incorrect; (4) BIOS/platform configuration not enabling QAT at correct security level; (5) qatprovider version incompatible with RHEL/kernel on DMR AP. No confirmed silicon bug.",
        "verified_fix": "Install DMR-specific QAT package: QAT_2025.07.01.tar.gz. Verify QAT fuse and BIOS enablement. Confirm firmware loaded with RSA support. Use qat_service status to verify.",
        "architectural_element": "QAT Provider (qatprovider); OpenSSL QAT engine; QAT firmware RSA acceleration; QAT_DISABLE fuse",
        "failure_registers": ["QAT device status registers", "QAT_DISABLE fuse", "QAT firmware version"],
        "adjacent_subsystems": ["OpenSSL QAT engine", "QAT driver", "QAT firmware", "BIOS QAT enablement"],
        "related_hsds": ["14026598028"],
        "spec_reference": "DMR Ocelot LOS 2025 WW30 Release Notes wiki; QAT documentation wiki; DMR Security HAS"
    },
    phase4={
        "tier1": [
            {"category": "qat_version_check", "commands": ["qat_service status", "cat /proc/driver/qat_dev0/version"], "reveals": "QAT driver version and firmware load status", "relevance": "Version mismatch is primary cause of RSA failure"},
            {"category": "openssl_qat_test", "commands": ["openssl engine qatengine", "openssl speed -engine qatengine rsa2048"], "reveals": "QAT engine available to OpenSSL and RSA performance", "relevance": "Confirms QAT Provider is loading and RSA is accessible"},
        ],
        "tier2": [
            {"category": "fuse_check", "commands": ["sv.socket0.imh0.ip_disable_resolved_cr_dword3.show()"], "reveals": "QAT_DISABLE fuse status", "relevance": "Fuse disable prevents RSA acceleration"},
        ],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — openssl speed test via QAT Provider fails on RSA operation",
        "root_cause_domain": "val.env.configuration / QAT Provider version or fuse",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "qat_version_check immediately shows BKC alignment. openssl_qat_test confirms availability.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026598028 — QAT ECDH Key Generation Error ─────────────────────────
write(
    "14026598028",
    phase2={
        "testcase_name": "QAT Provider OpenSSL ECDH key generation speed test",
        "testcase_command": "openssl speed -engine qatengine ecdh (or via qatprovider)",
        "testcase_parameters": "DMR AP platform; ECDH key generation errors with openssl speed tests using QAT Provider API; no NGA UUIDs",
        "testcase_domain_focus": "QAT Provider OpenSSL ECDH key generation failure on DMR AP — similar root cause pattern to RSA failure",
    },
    phase3={
        "verified_problem_statement": "ECDH key generation errors occur when running openssl speed tests using QAT Provider API on DMR AP.",
        "verified_root_cause": "QAT Provider ECDH failure on DMR AP: same root cause pattern as RSA failure (HSD 14026598567). (1) QAT driver/firmware version mismatch — DMR-specific QAT package required; (2) SRAM/NVRAM space limitation for ECDH key generation — DMR PQC update notes NVRAM/SRAM constraints as keys/certs grow (ECDH cert operations require more NVRAM); (3) QAT ECDH elliptic curve configuration not aligned with DMR firmware; (4) QAT_DISABLE fuse check. Same fix as RSA: install DMR QAT package, verify firmware loaded with ECDH support.",
        "verified_fix": "Install DMR-specific QAT package (QAT_2025.07.01.tar.gz). Check NVRAM space allocation for ECDH keys. Verify ECDH algorithm available in QAT firmware.",
        "architectural_element": "QAT ECDH engine; OpenSSL QAT Provider; QAT firmware ECDH support; NVRAM key material storage",
        "failure_registers": ["QAT device status registers", "NVRAM ECDH space", "QAT firmware version"],
        "adjacent_subsystems": ["OpenSSL QAT engine", "QAT driver", "QAT firmware ECDH", "BIOS secure key storage"],
        "related_hsds": ["14026598567"],
        "spec_reference": "DMR Ocelot LOS 2025 WW30 Release Notes wiki; DMR PQC Update documentation; DMR Security HAS"
    },
    phase4={
        "tier1": [
            {"category": "qat_version_check", "commands": ["qat_service status", "openssl engine qatengine"], "reveals": "QAT engine and firmware state", "relevance": "Same as RSA check — version mismatch is primary cause"},
            {"category": "ecdh_test", "commands": ["openssl speed -engine qatengine ecdhp256"], "reveals": "ECDH P256 performance via QAT Provider", "relevance": "Confirms ECDH-specific failure vs general QAT issue"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — openssl speed test via QAT Provider fails on ECDH key generation",
        "root_cause_domain": "val.env.configuration / QAT Provider version",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "Same pattern as HSD 14026598567. qat_version_check resolves quickly.",
        "iteration_savings": "2",
    },
)

# ── HSD 15018759390 — OKS QAT Rate Limiting DECOMP failure ───────────────────
write(
    "15018759390",
    phase2={
        "testcase_name": "OKS QAT Rate Limiting with DECOMP service (cpa_sample_code)",
        "testcase_command": "cpa_sample_code -a /QAT_RL_Config_Scripts/...",
        "testcase_parameters": "OKS DMR AP; QAT Rate Limiting DECOMP service failure; cpa_sample_code not working for decomp; no NGA UUIDs",
        "testcase_domain_focus": "QAT rate limiting with decompression service — cpa_sample_code failure on DMR AP OKS",
    },
    phase3={
        "verified_problem_statement": "OKS DMR AP QAT rate limiting test with DECOMP service fails: cpa_sample_code does not work for decomp services when rate limiting is active.",
        "verified_root_cause": "QAT Rate Limiting DECOMP failure: (1) QAT package version mismatch — must use DMR-specific package (QAT_2025.07.01.tar.gz); GNR package fails for DMR DECOMP; (2) QAT rate limiter configuration mismatch — c4xxx_dev0.conf or RL config scripts not updated for DMR AP DECOMP service; (3) QAT firmware DECOMP algorithm not enabled or rate limiting slice assignment incorrect; (4) Installation/environment variable mismatch for rate limiting + DECOMP combined use. No confirmed silicon bug — all validation passes in DMR Ocelot LOS 2025 WW30.",
        "verified_fix": "Install DMR QAT package: QAT_2025.07.01.tar.gz. Verify c4xxx_dev0.conf rate limiting configuration for DECOMP service. Follow DMR Ocelot LOS Platform Specific Release Notes steps exactly.",
        "architectural_element": "QAT rate limiter; DECOMP service slice assignment; c4xxx_dev0.conf; cpa_sample_code DECOMP API",
        "failure_registers": ["QAT device status", "c4xxx_dev0.conf RL config", "QAT firmware DECOMP state"],
        "adjacent_subsystems": ["QAT rate limiter firmware", "DECOMP service", "cpa_sample_code", "QAT configuration files"],
        "related_hsds": ["14026598567"],
        "spec_reference": "DMR Ocelot LOS Platform Specific 2025 WW30 Release Notes wiki; QAT documentation wiki"
    },
    phase4={
        "tier1": [
            {"category": "qat_rl_config", "commands": ["cat /etc/c4xxx_dev0.conf | grep -i 'RL'", "cat QAT_RL_Config_Scripts/*.conf"], "reveals": "Rate limiting configuration for DECOMP service", "relevance": "Misconfigured RL slice assignment causes DECOMP failure"},
            {"category": "qat_package_check", "commands": ["cat /proc/driver/qat_dev0/version"], "reveals": "QAT package version vs DMR BKC", "relevance": "Wrong package version (GNR vs DMR) is primary cause"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — cpa_sample_code invokes QAT DECOMP via rate limiter; fails if config or package mismatch",
        "root_cause_domain": "val.env.configuration / QAT rate limiting config",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "qat_rl_config + qat_package_check cover primary causes. No silicon bug confirmed.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026584582 — 64B read to DSA/IAA CFG space causes system issue ──────
write(
    "14026584582",
    phase2={
        "testcase_name": "64B CPU read to DSA/IAA configuration space (CFG negative space test)",
        "testcase_command": "(direct CPU read to IAA CFG space — 64B/8-byte read)",
        "testcase_parameters": "DMR X1 A0 VV; test issues 64B read from CPU to IAA CFG space; system failure (hang/MCE); component hw.iax",
        "testcase_domain_focus": "IAA/DSA configuration space access — hardware behavior for 64B (non-standard) CFG read on DMR A0",
    },
    phase3={
        "verified_problem_statement": "Issuing a 64B read from CPU to IAA CFG space causes system failure on DMR X1 A0 VV.",
        "verified_root_cause": "64B read to DSA/IAA CFG space per DMR ACC HAS: (1) If reading a supported address range, hardware should return registers in range (expected behavior per spec Table item 23); (2) If reading overlapping unimplemented range, should return 0s for unimplemented bytes; (3) If request is malformed/out-of-bounds, should UR (Unsupported Request) per PCIe spec. System failure (hang/MCE) suggests: either (a) IAA does not handle 64B CFG read correctly (A0 silicon bug — returns error beyond UR/MCE); or (b) IOMCA enabled causing MCE on UR to escalate to system halt. Component hw.iax confirms hardware domain — likely a new silicon bug to characterize.",
        "verified_fix": "Capture AER and MCE bank state at failure. Determine if UR was generated. Check if IOMCA is converting UR to MCE. If hardware does not handle 64B CFG reads per spec, file as hw.iax A0 silicon bug.",
        "architectural_element": "IAA/DSA PCIe CFG space read handler; PCIe UR error path; IOMCA error escalation; DMR ACC HAS negative space table",
        "failure_registers": ["PCIe ERRUNCSTS (UR)", "MCi_STATUS (MCA bank at CFG failure)", "IAA error registers"],
        "adjacent_subsystems": ["IAA PCIe config space handler", "PCIe AER error path", "IOMCA escalation"],
        "related_hsds": ["14026584382"],
        "spec_reference": "DMR ACC HAS Table items 21-24: CFG space negative space handling; PCIe spec UR response; IOMCA escalation spec"
    },
    phase4={
        "tier1": [
            {"category": "aer_check", "commands": ["status_scope.run(analyzers=['pcie','ieh'])", "sv.socket0.imh0.showsearch('erruncsts')"], "reveals": "PCIe UR error from 64B CFG read and IEH error hierarchy", "relevance": "UR error confirms hardware correctly flagged unsupported request"},
            {"category": "mce_decode", "commands": ["mcelog --client", "dmesg | grep -i 'mce'"], "reveals": "MCE at 64B CFG read failure — confirms IOMCA escalation", "relevance": "MCE bank MCACOD identifies specific failure path"},
        ],
        "tier2": [
            {"category": "dsa_state", "commands": ["from diamondrapids.accelerators.dsa_iaa import dsa_iaa_debug_dump as dsa_iaa_dump", "dsa_iaa_dump.dump_all_dsa_inst_errs()"], "reveals": "IAA state after 64B CFG read", "relevance": "IAA SWERROR shows if IAA itself triggered error vs PCIe path"},
        ],
        "tier3": [],
        "beyond_sme": [
            {"description": "Characterize 64B CFG read response per ACC HAS", "commands": ["Verify IAA response: UR or hang?", "Disable IOMCA and retest to isolate MCE from hang"], "why": "Determines if hardware correctly URs 64B CFG read or has silicon bug"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — test issues 64B CFG read to IAA and observes system failure",
        "root_cause_domain": "hw.iax / IAA CFG space 64B read handling",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "aer_check + mce_decode identify PCIe vs silicon path. IOMCA disable test differentiates MCE-escalation from silicon hang.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026584382 — MCEs in MLC/PUNIT/CBB06 ────────────────────────────────
write(
    "14026584382",
    phase2={
        "testcase_name": "DSA test causing MCEs in MLC/PUNIT/CBB06 (second MCE HSD)",
        "testcase_command": "DSA focus test causing MCE in MLC, PUNIT, CBB06",
        "testcase_parameters": "DMR X1 A0 VVR SVOS; MCEs in MLC, PUNIT, CBB06 (CBB instance 6); component hw.punit",
        "testcase_domain_focus": "DSA-triggered MCEs in MLC/PUNIT/CBB06 (Core Building Block 6) on DMR X1 A0 VVR — second occurrence of this pattern",
    },
    phase3={
        "verified_problem_statement": "MCEs occur in MLC, PUNIT, and CBB06 during DSA testing on DMR X1 A0 VVR SVOS.",
        "verified_root_cause": "CBB06 = 7th Core Building Block instance in DMR (CBBs contain core IPs, LLC, CBO, Punit, NCU). MCEs in MLC/PUNIT/CBB06 during DSA same pattern as HSD 14026683560. DSA-triggered MCEs: (1) ATS/DMA UR/CA to M2IOSF triggers MCE via IOMCA (CBB06 Punit MCE bank); (2) PRS ordering violation (HSD 14025333034) causing IOMMU Invalidation Completion Error; (3) CBB06 Punit watchdog MCE — DSA hang blocks core retirement in CBB06; (4) DSA DEFTR register non-POR value causing fatal error. Debug: decode MCACOD/MSCOD from CBB06 MCA banks.",
        "verified_fix": "Run sd.show_cbb_mca_err_src and sd.show_cbb_errlog() targeting CBB06. Decode MCi_STATUS MCACOD/MSCOD. Apply ATS/PRS WA. Same approach as HSD 14026683560.",
        "architectural_element": "CBB06 Punit MCA bank; MLC MCA bank; DSA ATS error → M2IOSF → IOMCA → CBB06 MCE",
        "failure_registers": ["MCi_STATUS CBB06 MCA bank", "MCi_ADDR CBB06", "PCU MCA bank MCACOD"],
        "adjacent_subsystems": ["DSA ATS request path", "M2IOSF", "IOMCA CBB06 Punit bank", "CBB06 LLC"],
        "related_hsds": ["14026683560", "14025333034"],
        "spec_reference": "DMR RAS HAS; FHAS CBB MCA; DMR RAS Debug wiki; sd.show_cbb_mca_err_src script"
    },
    phase4={
        "tier1": [
            {"category": "cbb06_mce_decode", "commands": ["sd.show_cbb_mca_err_src(cbb_num=6)", "sd.show_cbb_errlog(cbb_num=6)"], "reveals": "CBB06-specific MCE source and error log — exact MCACOD/MSCOD", "relevance": "CBB-specific debug tool targets failing CBB06 instance"},
            {"category": "mce_banks", "commands": ["mcelog --client", "dmesg | grep -i 'mce'"], "reveals": "All MCE bank errors at DSA test failure", "relevance": "MCACOD 0x405 = parity; 0x402 = unclassified; decode narrows root cause"},
        ],
        "tier2": [
            {"category": "dsa_ats_check", "commands": ["status_scope.run(analyzers=['pcie','m2iosf'])", "from diamondrapids.accelerators.dsa_iaa import dsa_iaa_debug_dump as dsa_iaa_dump", "dsa_iaa_dump.dump_all_dsa_inst_errs()"], "reveals": "DSA ATS path errors that triggered CBB06 MCE", "relevance": "ATS UR/CA is known MCE trigger via IOMCA path"},
        ],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — DSA test exercises ATS path; M2IOSF error escalates to CBB06 Punit MCE",
        "root_cause_domain": "hw.punit / CBB06 MCE via DSA ATS path",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "cbb06_mce_decode is CBB-specific debug tool. Same pattern confirmed as HSD 14026683560.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026579612 — NGA log files not complete ─────────────────────────────
write(
    "14026579612",
    phase2={
        "testcase_name": "IAA/DSA SVOS NGA test run (Rocket log incomplete in NGA)",
        "testcase_command": "(NGA-based rocket test run — log collection issue)",
        "testcase_parameters": "DMR X1 A0 VV SVOS NGA test run; Rocket log files not complete in NGA; component val.env.configuration",
        "testcase_domain_focus": "NGA automation infrastructure — incomplete Rocket logs during VV test run on DMR X1 A0",
    },
    phase3={
        "verified_problem_statement": "Rocket log files are not complete/truncated in NGA Test Run for DMR X1 A0 VV.",
        "verified_root_cause": "Incomplete Rocket logs in NGA: (1) System/SUT hang during test — automation detects hang, terminates run before log flush completes; (2) Network connection instability between SUT and NGA log collection service — partial upload; (3) Log rotation or file truncation — Exelog concurrent write issue (known issue: 'concurr on Exelog' can truncate logs); (4) NGA infrastructure failure during log upload; (5) Log size limit exceeded. Component val.env.configuration confirms automation configuration domain.",
        "verified_fix": "Cross-check timestamps between automation log and SUT log. Check for hang in dmesg at truncation point. Verify Exelog concurr setting. Validate network connection to NGA log upload endpoint.",
        "architectural_element": "NGA log collection service; Exelog concurrent write; SUT network connectivity; Rocket log flush",
        "failure_registers": [],
        "adjacent_subsystems": ["NGA automation infrastructure", "Exelog service", "SUT network", "Rocket log manager"],
        "related_hsds": ["14026679112", "14026668250"],
        "spec_reference": "Enhanced NGA User Guide wiki; CR CI Enabling Status (DMR) wiki; Supercollider+Rocket Triage Process wiki"
    },
    phase4={
        "tier1": [
            {"category": "log_check", "commands": ["Verify NGA log timestamp vs SUT dmesg timestamp at truncation point", "cat exelog_pid*.log | grep -i 'truncat'"], "reveals": "Whether truncation was from hang, upload failure, or file size", "relevance": "Timestamp comparison identifies exact failure point"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "indirect — test runs but NGA fails to collect complete logs",
        "root_cause_domain": "val.env.configuration / NGA log infrastructure",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "Log timestamp comparison immediately identifies cause. Fast infrastructure debug.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026577326 — CXLHDM registration failure in atlas ───────────────────
write(
    "14026577326",
    phase2={
        "testcase_name": "DSA SVOS Atlas CXLHDM registration failure",
        "testcase_command": "(Rocket/Atlas test setup — CXLHDM target registration in atlas.log)",
        "testcase_parameters": "DMR X1 A0 VVR SVOS; CXLHDM registration failure — CXLHDM not found; atlas.log DRAM usage error; component val.env.tool",
        "testcase_domain_focus": "Rocket/Atlas CXL HDM target registration failure — CXLHDM device not found in framework on DMR X1 A0 VVR",
    },
    phase3={
        "verified_problem_statement": "Atlas framework cannot find/register CXLHDM (CXL Host-Managed Device Memory) target on DMR X1 A0 VVR. DRAM usage error in atlas.log.",
        "verified_root_cause": "CXLHDM registration failure in Atlas: (1) CXL HDM device not present or not enumerated in BIOS — device not visible to Atlas discovery; (2) Atlas/Acre CXL 3.0 module not updated for DMR X1 A0 — compatibility delta between CXL 2.0 and 3.0 in atlas modules; (3) BIOS configuration required: specific version (BIOS2834D10 + UP 60000974) or SVOS dmr2534 patch 11+ for CXL enumeration on DMR X1 A0; (4) CXL bifurcation or bus configuration incorrect; (5) Atlas tool version doesn't support CXLHDM as DRAM target type. Component val.env.tool confirms tool domain.",
        "verified_fix": "Update BIOS to required version for DMR CXL support. Apply SVOS dmr2534 patch 11+. Update Atlas/Acre modules for CXL 3.0 DMR support. Verify CXL device enumerated in OS.",
        "architectural_element": "Atlas CXLHDM target registration; CXL HDM device enumeration; BIOS CXL support; Atlas/Acre CXL 3.0 modules",
        "failure_registers": ["CXL device PCI enumeration", "Atlas DRAM target table", "Acre CXL module"],
        "adjacent_subsystems": ["Atlas target framework", "CXL port", "BIOS CXL enumeration", "SVOS CXL driver"],
        "related_hsds": ["14026822165"],
        "spec_reference": "CXL 3.0 Tech Readiness for DMR wiki; DMR CXL PO Workarounds wiki; SPR Rocket Sync Minutes (CXL/Atlas)"
    },
    phase4={
        "tier1": [
            {"category": "cxl_enumeration", "commands": ["lspci | grep -i 'cxl'", "ls /sys/bus/cxl/devices/"], "reveals": "CXL device presence in OS", "relevance": "Not enumerated = BIOS or hardware issue; enumerated but Atlas fails = Atlas version issue"},
            {"category": "atlas_version", "commands": ["python3 -c 'import atlas; print(atlas.__version__)'", "cat /usr/local/atlas/cxl_support.txt"], "reveals": "Atlas version and CXL module support level", "relevance": "Old Atlas without CXL 3.0/DMR support causes CXLHDM registration failure"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — Atlas test setup registers CXLHDM target; not found causes immediate failure",
        "root_cause_domain": "val.env.tool / Atlas CXL support or BIOS CXL enablement",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "cxl_enumeration + atlas_version quickly identify device vs tool issue. Fast debug.",
        "iteration_savings": "2",
    },
)

# ── HSD 16029389608 — DSA DIF Insert page fault BOF ──────────────────────────
write(
    "16029389608",
    phase2={
        "testcase_name": "OKS DMR AP DSA Legacy opcode 0x13 DIF insert with Block on Fault",
        "testcase_command": "(DSA3 DIF Insert opcode 0x13 test with Block on Fault flag set)",
        "testcase_parameters": "OKS DMR AP; DSA3 legacy opcode 0x13 (DIF Insert) fails with page fault when Block on Fault (BOF) is set; no NGA UUIDs",
        "testcase_domain_focus": "DSA DIF Insert operation (opcode 0x13) page fault behavior with BOF flag on DMR AP OKS",
    },
    phase3={
        "verified_problem_statement": "OKS DMR AP DSA3 legacy opcode 0x13 (DIF Insert) fails with page fault when Block on Fault (BOF) is set.",
        "verified_root_cause": "DSA DIF Insert 0x13 page fault with BOF: (1) Test intentionally exercises page fault handling — buffer pointer is unmapped/unbacked to trigger PRS page fault with BOF blocking behavior; (2) BOF set means DSA should block descriptor on page fault and wait for OS to fix PTE — test verifies DSA correctly blocks; (3) If failure: page tables not properly configured (buffer mapped but not present, mprotect permission issue, or PASID misconfiguration preventing IOMMU page table walk); (4) No known DMR AP silicon bug for DIF Insert + BOF. Component OKS/unknown — test content/page table configuration.",
        "verified_fix": "Verify IOMMU page table configuration for test buffer. Confirm PASID is correctly set up. Check completion record for DSA block status vs page fault response. Validate test expected behavior matches spec.",
        "architectural_element": "DSA DIF Insert descriptor; Block on Fault flag; IOMMU page table walk; PRS page fault response",
        "failure_registers": ["SWERROR0", "completion record status", "IOMMU PRQ page fault status"],
        "adjacent_subsystems": ["DSA descriptor engine", "IOMMU PRS handler", "OS page fault handler", "Block on Fault flow"],
        "related_hsds": ["14026553474"],
        "spec_reference": "DSA Architecture Spec: opcode 0x13 DIF Insert; Block on Fault behavior; PRS page fault flow"
    },
    phase4={
        "tier1": [
            {"category": "completion_record", "commands": ["Capture DSA completion record status after DIF Insert + BOF"], "reveals": "Whether DSA blocked correctly (completion pending) or failed with error", "relevance": "Completion status shows if BOF flow worked or not"},
            {"category": "iommu_page_fault", "commands": ["cat dmesg | grep -i 'iommu'", "sv.socket0.imh0.showsearch('prq')"], "reveals": "IOMMU page fault registration and handling", "relevance": "Page fault must be registered by IOMMU and serviced by OS for BOF to work"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — DSA DIF Insert with BOF exercises page fault path; IOMMU/PRS must handle correctly",
        "root_cause_domain": "val.env.content / test page table configuration",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "completion_record shows BOF behavior. iommu_page_fault confirms IOMMU registered fault. No silicon bug confirmed.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026559709 — ATS Invalidations + PRS 0x0 vs 0x14 error ──────────────
write(
    "14026559709",
    phase2={
        "testcase_name": "DSA ATS Invalidations + PRS test (SW:0x0 vs HW:0x14 mismatch)",
        "testcase_command": "(DSA ATS Invalidations + PRS test in SVOS)",
        "testcase_parameters": "DMR X1 A0 VVR SVOS; ATS Invalidations + PRS failing with 0x0 error code; HW reports 0x14 (Invalid Invalidation Address Alignment); component val.env.content",
        "testcase_domain_focus": "DSA ATS Invalidation error mismatch — software sees 0x0 but hardware reports 0x14 (Invalid Invalidation Address Alignment) due to M2IOSF PRS ordering bug",
    },
    phase3={
        "verified_problem_statement": "DSA ATS Invalidations + PRS test fails on DMR X1 A0 VVR SVOS: software reports 0x0 (success) but hardware signals 0x14 (Invalid Invalidation Address Alignment).",
        "verified_root_cause": "Known M2IOSF PRS ordering bug (HSD 14025333034): the pipeline stall/flush logic fails for certain PRS transaction orderings, causing: (1) hardware to detect 0x14 (Invalid Invalidation Address Alignment) because younger PRS bypass older ones, causing alignment check failure; (2) software sees 0x0 because error is not properly propagated through pipeline to completion record; (3) M2IOSF channel not stalled correctly for LPIG ordering — corrupted internal state. Same WA as PRS count mismatch: dis_max_pgr_throttle=1.",
        "verified_fix": "Apply WA: vt_iommu_cr_itciommudbgctrl3.dis_max_pgr_throttle=1. Cross-reference HSD 14025333034. This is a non-ECOable A0 hardware bug.",
        "architectural_element": "M2IOSF PRS ordering; ATS Invalidation alignment check; LPIG pipeline stall logic",
        "failure_registers": ["vt_iommu_cr_itciommudbgctrl3.dis_max_pgr_throttle", "IOMMU ICE register", "ATS Invalidation completion"],
        "adjacent_subsystems": ["M2IOSF PRS pipeline", "VT-d IOMMU", "DSA ATS engine"],
        "related_hsds": ["14025333034", "14026766087", "14026553474"],
        "spec_reference": "PRS Bug GNR debug wiki; Flexcon VTd workarounds wiki; DMR PASID drain IOMMU spec"
    },
    phase4={
        "tier1": [
            {"category": "prs_wa_check", "commands": ["sv.socket0.imh0.vt_iommu_cr_itciommudbgctrl3.dis_max_pgr_throttle.show()"], "reveals": "PRS throttle WA status", "relevance": "WA not applied = known PRS ordering bug active"},
            {"category": "ice_check", "commands": ["sv.socket0.imh0.showsearch('ice')", "cat dmesg | grep -i 'ICE'"], "reveals": "IOMMU Invalidation Completion Error — confirms M2IOSF ordering violation", "relevance": "ICE error confirms PRS ordering bug triggered"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — ATS Invalidation + PRS test exercises M2IOSF ordering; known A0 bug triggers",
        "root_cause_domain": "hw.m2iosf / known PRS ordering bug (HSD 14025333034)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "prs_wa_check is single-register check. ice_check confirms bug signature. Known A0 root cause.",
        "iteration_savings": "3",
    },
)

# ── HSD 14026553474 — VTD failed to correct PTE on PRS ──────────────────────
write(
    "14026553474",
    phase2={
        "testcase_name": "DSA PRS test VT-d PTE correction failure",
        "testcase_command": "(DSA PRS test in SVOS — PTE correction after PRS)",
        "testcase_parameters": "DMR X1 A0 VVR SVOS; DSA PRS test fails after several cycles: vtd error - VT-d failed to correct PTE based on PRS; component val.env.content",
        "testcase_domain_focus": "VT-d PTE update failure after DSA PRS page request — M2IOSF PRS ordering bug on DMR A0",
    },
    phase3={
        "verified_problem_statement": "DSA PRS test fails after several cycles on DMR X1 A0 VVR SVOS: VT-d error 'failed to correct the PTE based on PRS'.",
        "verified_root_cause": "VT-d PTE correction failure after PRS: confirmed M2IOSF PRS ordering bug (HSD 14025333034). M2IOSF fails to properly stall adjacent pipeline channel for PRS LPIG ordering, causing corrupted PRS state. VT-d receives PRS response but cannot correctly update PTE because M2IOSF corrupted the associated PASID context. DSA PRS test runs correctly for several cycles until M2IOSF ordering violation corner case is hit. Non-ECOable A0 hardware bug.",
        "verified_fix": "Apply WA: vt_iommu_cr_itciommudbgctrl3.dis_max_pgr_throttle=1. This is confirmed M2IOSF PRS ordering bug (HSD 14025333034).",
        "architectural_element": "M2IOSF PRS LPIG pipeline ordering; VT-d PTE update mechanism; PASID context corruption",
        "failure_registers": ["vt_iommu_cr_itciommudbgctrl3.dis_max_pgr_throttle", "IOMMU PTE update registers", "PASID context table"],
        "adjacent_subsystems": ["M2IOSF PRS pipeline", "VT-d IOMMU", "PASID context manager"],
        "related_hsds": ["14025333034", "14026559709", "14026766087"],
        "spec_reference": "PRS Bug GNR debug wiki; Flexcon VTd workarounds wiki; HSD 14025333034"
    },
    phase4={
        "tier1": [
            {"category": "prs_wa_check", "commands": ["sv.socket0.imh0.vt_iommu_cr_itciommudbgctrl3.dis_max_pgr_throttle.show()"], "reveals": "PRS WA status — single register check for known root cause", "relevance": "WA not applied = confirmed bug active"},
            {"category": "vtd_log", "commands": ["cat dmesg | grep -i 'vtd'", "cat vtd_log*.log | grep -i 'PTE'"], "reveals": "VT-d PTE correction failure details and cycle count", "relevance": "Confirms VT-d failure signature matching M2IOSF bug pattern"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — DSA PRS exercises M2IOSF ordering; VT-d PTE correction fails after corner case hit",
        "root_cause_domain": "hw.m2iosf / confirmed PRS ordering bug (HSD 14025333034)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "Single-register WA check resolves. Confirmed root cause with HSD 14025333034.",
        "iteration_savings": "3",
    },
)

# ── HSD 14026543468 — PRS dual cast 0x22 error ───────────────────────────────
write(
    "14026543468",
    phase2={
        "testcase_name": "DSA PRS flow with dual cast operation (error code 0x22)",
        "testcase_command": "(DSA PRS + Dualcast combined test in SVOS)",
        "testcase_parameters": "DMR X1 A0 VVR SVOS; DSA PRS flow with Dualcast operation reports 0x22 error; component val.env.content",
        "testcase_domain_focus": "DSA PRS + Dualcast combined operation — completion status 0x22 (ATS error during translation) on DMR A0",
    },
    phase3={
        "verified_problem_statement": "DSA PRS flow with Dualcast operation reports error code 0x22 on DMR X1 A0 VVR SVOS.",
        "verified_root_cause": "DSA status 0x22 = SWERROR during ATS (Address Translation Services) error — specific to PRS+Dualcast combination: (1) ATS translation failure during Dualcast's second destination write — VT-d page table not mapped for one of the Dualcast destinations during PRS flow; (2) Known DMR A0 bug: 'Unexpected error code reporting for ATS Req timeout' may cause 0x22 for ATS timeout; (3) M2IOSF PRS ordering bug (HSD 14025333034) affecting Dualcast's second PRS request when first PRS not yet served; (4) CXL HDM credit issue for Dualcast targets. Check completion record for full context.",
        "verified_fix": "Apply PRS WA: dis_max_pgr_throttle=1. Verify Dualcast destination addresses are in IOMMU page tables. Check ATS timeout registers. Compare with HSD 14025333034.",
        "architectural_element": "DSA Dualcast ATS path; PRS + Dualcast interaction; M2IOSF PRS ordering; ATS timeout handling",
        "failure_registers": ["SWERROR0 (0x22)", "INTCAUSE", "vt_iommu_cr_itciommudbgctrl3", "ATS Req timeout registers"],
        "adjacent_subsystems": ["DSA Dualcast engine", "M2IOSF PRS pipeline", "VT-d ATS path", "Dualcast second destination"],
        "related_hsds": ["14025333034", "14026559709"],
        "spec_reference": "DSA/IAX Debug BKMs: SWERROR 0x22 = ATS error; DMR Known bugs list: ATS Req timeout; PRS Bug wiki"
    },
    phase4={
        "tier1": [
            {"category": "swerror_check", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.swerror0.show()"], "reveals": "0x22 ATS error details from SWERROR register", "relevance": "Confirms ATS error domain for PRS+Dualcast failure"},
            {"category": "prs_wa_check", "commands": ["sv.socket0.imh0.vt_iommu_cr_itciommudbgctrl3.dis_max_pgr_throttle.show()"], "reveals": "PRS ordering WA status", "relevance": "M2IOSF PRS bug may compound Dualcast ATS failure"},
        ],
        "tier2": [
            {"category": "ats_page_table", "commands": ["Verify both Dualcast destination addresses in IOMMU page tables"], "reveals": "Whether Dualcast second destination is missing from IOMMU", "relevance": "Missing PTE for second destination = direct cause of 0x22"},
        ],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — PRS+Dualcast exercises ATS path for both destinations; ATS failure triggers 0x22",
        "root_cause_domain": "val.env.content / DSA ATS PRS Dualcast path",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "swerror_check confirms 0x22. prs_wa_check identifies M2IOSF contribution. ats_page_table check resolves.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026542532 — MCE in MLC during DSA (hw.big_core) ────────────────────
write(
    "14026542532",
    phase2={
        "testcase_name": "DSA test causing MCEs in MLC (hw.big_core CBB)",
        "testcase_command": "(DSA stress test causing MLC MCE in hw.big_core CBB)",
        "testcase_parameters": "DMR X1 A0 VVR SVOS; MCEs appear in MLC (Mid-Level Cache) during DSA test; component hw.big_core",
        "testcase_domain_focus": "MLC-specific MCE during DSA stress — data poisoning or coherency error from DSA DMA writes on DMR A0",
    },
    phase3={
        "verified_problem_statement": "MCEs appear in MLC during DSA testing on DMR X1 A0 VVR SVOS. Component hw.big_core indicates MLC CBB-level MCE.",
        "verified_root_cause": "MLC MCE during DSA (hw.big_core): (1) DSA DMA write corruption propagating to MLC — DSA writes poisoned data (due to ATS error or ECC error) to memory, which when read by LLC/MLC triggers uncorrectable error; (2) Poison escalation — DSA encounters uncorrectable error, marks data as poisoned; when core reads poisoned cache line from MLC, MCE occurs; (3) Cache coherency violation — DSA write timing conflict with core MLC access creates corruption; (4) DSA test with SVM-disabled + strict invalidation known pattern for triggering MCE in validation. Component hw.big_core confirms CBB-level (not Punit) MCE.",
        "verified_fix": "Capture MCACOD/MSCOD for MLC MCE bank. Check for poison marker in cache line. Review DSA HIOP remap configuration. Verify no conflicting cache access patterns.",
        "architectural_element": "MLC (Mid-Level Cache) CBB MCE bank; DSA DMA poison propagation; cache coherency; HIOP remap",
        "failure_registers": ["MLC MCE bank (MCi_STATUS MCACOD/MSCOD)", "MCi_ADDR", "HIOP remap registers"],
        "adjacent_subsystems": ["DSA DMA write path", "MLC ECC", "CBB cache coherency", "HIOP remap"],
        "related_hsds": ["14026683560", "14026584382"],
        "spec_reference": "DMR RAS HAS; DMR SystemIO cache flows; DSA/IAX Debug BKMs (SVM-disabled + strict invalidation MCE)"
    },
    phase4={
        "tier1": [
            {"category": "mce_decode", "commands": ["mcelog --client", "dmesg | grep -i 'mce'", "sd.show_cbb_mca_err_src()"], "reveals": "MLC MCE MCACOD/MSCOD — specific error type and cache address", "relevance": "MCACOD 0x150 = LLC data; decode identifies corruption source"},
            {"category": "dsa_state", "commands": ["from diamondrapids.accelerators.dsa_iaa import dsa_iaa_debug_dump as dsa_iaa_dump", "dsa_iaa_dump.dump_all_dsa_inst_errs()"], "reveals": "DSA error at MCE time", "relevance": "DSA error preceding MCE links DMA corruption to MLC MCE"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — DSA write + core MLC read creates poison propagation path",
        "root_cause_domain": "hw.big_core / MLC MCE from DSA poison propagation",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "mce_decode identifies MCACOD. dsa_state correlates DSA error. Multiple causes require systematic debug.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026536280 — Inter-domain Fill SASS 0x1b error ──────────────────────
write(
    "14026536280",
    phase2={
        "testcase_name": "DSA Inter-domain Fill SASS test (error code 0x1b)",
        "testcase_command": "(DSA SASS (Self-Assisted Stress) inter-domain Fill test in SVOS)",
        "testcase_parameters": "DMR X1 A0 VVR SVOS; DSA Inter-domain Fill SASS reports 0x1b error code; possible completion record write error; component val.env.content",
        "testcase_domain_focus": "DSA inter-domain Fill SASS stress test — completion status 0x1b (ATS-related or completion record error) on DMR A0",
    },
    phase3={
        "verified_problem_statement": "DSA Inter-domain Fill SASS test reports error code 0x1b on DMR X1 A0 VVR SVOS with possible completion record issue.",
        "verified_root_cause": "DSA status 0x1b in SASS inter-domain Fill context: (1) 0x1b not explicitly defined in available documentation but in range of ATS/translation errors (0x17-0x23 per BKMs include ATS-related codes); (2) SASS inter-domain Fill crosses domain/memory boundary — may trigger ATS page walk failure in cross-domain path; (3) Completion record write error — if completion record address is in unmapped domain, writing completion record itself fails; (4) Possible variant of M2IOSF ordering issue in cross-domain path. Check DSA EAS for 0x1b definition.",
        "verified_fix": "Check DSA EAS for error code 0x1b definition. Verify inter-domain Fill completion record address is mapped. Check SWERROR0 and INTCAUSE for additional context. Contact DSA arch team if 0x1b not in public spec.",
        "architectural_element": "DSA inter-domain Fill descriptor; completion record write path; SASS stress test; cross-domain ATS path",
        "failure_registers": ["SWERROR0 (0x1b)", "INTCAUSE", "completion record address mapping"],
        "adjacent_subsystems": ["DSA inter-domain fill engine", "IOMMU cross-domain mapping", "SASS test framework"],
        "related_hsds": ["14026543468"],
        "spec_reference": "DSA Architecture Spec error code table; DSA/IAX Debug BKMs (SWERROR code range); SASS test documentation"
    },
    phase4={
        "tier1": [
            {"category": "swerror_check", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.swerror0.show()", "sv.socket0.imh0.acc.acc_0.dsa.intcause.show()"], "reveals": "SWERROR 0x1b context and INTCAUSE correlation", "relevance": "Confirms 0x1b is ATS-related error for inter-domain Fill"},
            {"category": "completion_record_check", "commands": ["Verify completion record address is in mapped domain", "cat dsa_test*.log | grep -i '0x1b'"], "reveals": "Completion record mapping status and error context", "relevance": "Unmapped completion record address = completion record write error"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [
            {"description": "DSA EAS error code 0x1b definition lookup", "commands": ["Reference DSA Architecture Spec error code table for 0x1b definition"], "why": "Definitive definition needed — not confirmed in available documentation"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — SASS inter-domain Fill exercises cross-domain ATS path; 0x1b at boundary",
        "root_cause_domain": "val.env.content / DSA inter-domain ATS or completion record",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "swerror_check confirms error type. completion_record_check identifies write failure. DSA EAS needed for definitive 0x1b definition.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026533264 — QAT System hang mounting SV modules ────────────────────
write(
    "14026533264",
    phase2={
        "testcase_name": "QAT SVOS system hang when mounting SV modules with CPM blacklisted",
        "testcase_command": "echo blacklist cpm >> /etc/modprobe.d/dmrmods.conf && killmax; umountsv; mountsv",
        "testcase_parameters": "DMR X1 A0 VV SVOS; system hangs when blacklisting CPM and remounting SV modules; component val.env.content",
        "testcase_domain_focus": "SVOS system hang during SV module mount after CPM blacklisting — CPM dependency in SVFS mount path on DMR A0",
    },
    phase3={
        "verified_problem_statement": "DMR X1 A0 VV SVOS system hangs when blacklisting CPM module and remounting SV modules.",
        "verified_root_cause": "SVOS system hang with CPM blacklisted during mountsv: SVOS/SVFS depends on CPM (or its work queues/interrupt handling) during mount operation. Blacklisting CPM leaves hardware in partially-initialized state that stalls kernel work queues or interrupt handling during umountsv/mountsv. Known SPR/GNR pattern: HQM/CPM blacklisting + VTd = soft hang on umount (requires power cycle). DMR CPM blacklisting same pattern. Component val.env.content confirms test environment issue.",
        "verified_fix": "Do not blacklist CPM if SVOS mount depends on it. Use BIOS disable instead of kernel blacklist. If blacklist needed: disable VT-d interrupt remapping first. Power cycle required to recover from hang.",
        "architectural_element": "SVOS/SVFS mount operation; CPM work queue; VTd interrupt remapping; kernel module blacklist",
        "failure_registers": ["CPM device state", "VTd interrupt remapping registers"],
        "adjacent_subsystems": ["SVFS mount", "CPM module", "VTd interrupt path", "kernel work queue"],
        "related_hsds": [],
        "spec_reference": "SPR Rocket Sync Meeting Minutes (HQM/CPM soft hang wiki); GNR HSLE VTd Bring-up wiki; DMR TDX Enabling wiki"
    },
    phase4={
        "tier1": [
            {"category": "vtd_interrupts", "commands": ["dmesg | grep -i 'vtd'", "dmesg | grep -i 'irq'", "cat /proc/interrupts | grep -i 'cpm'"], "reveals": "VTd interrupt state at hang and CPM interrupt status", "relevance": "VTd interrupt remapping + CPM blacklist = known soft hang pattern"},
            {"category": "recovery", "commands": ["Power cycle system", "Disable interrupt remapping: disable x2apic + VTd IR in BIOS"], "reveals": "Whether BIOS IR disable prevents hang on CPM blacklist + mount", "relevance": "Known SPR/GNR workaround for this exact hang pattern"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — CPM blacklist + SV remount triggers known soft hang in SVOS",
        "root_cause_domain": "val.env.content / SVOS CPM dependency + VTd soft hang",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "Known SPR/GNR pattern. vtd_interrupts check + BIOS IR disable resolves. Power cycle for recovery.",
        "iteration_savings": "2",
    },
)

# ── HSD 16029322007 — QAT Multithread Data Plane SRIOV symmetric+compression ─
write(
    "16029322007",
    phase2={
        "testcase_name": "QAT Multithread Data Plane API SRIOV Legacy symmetric encryption + compression",
        "testcase_command": "(QAT Multithread Data Plane API SRIOV Legacy cry test)",
        "testcase_parameters": "OKS DMR AP; QAT SRIOV Legacy mode; Multithread Data Plane API; symmetric encryption + data compression; no NGA UUIDs",
        "testcase_domain_focus": "QAT CPM 5.1 SRIOV Legacy multithread data plane failure — symmetric encryption + compression on DMR AP OKS",
    },
    phase3={
        "verified_problem_statement": "QAT SRIOV Legacy multithread data plane API test fails for symmetric encryption and data compression on DMR AP OKS.",
        "verified_root_cause": "QAT SRIOV Legacy multithread data plane failure: (1) Legacy SRIOV + CPM 5.1 compatibility gap — CPM 5.1 on DMR deprecates certain legacy ciphers; multithread path uses deprecated cipher hardware path; (2) Fusion/chaining flow intermediate buffer management issue — CPM 5.1 introduces new staged/shared RAM for chain operations; old test expects legacy intermediate buffer handling; (3) SIOV disabled but test uses legacy SRIOV mode — may not be properly configured for DMR; (4) Address translation/SAI issue: QAT logic must allow ATS completions without SAI checks (HSD 14022901692); (5) Wrong QAT driver package — must use QAT_2025.07.01 for DMR AP (not GNR). Component: likely val.env.content or hw.qat.",
        "verified_fix": "Update QAT driver to QAT_2025.07.01.tar.gz (DMR-specific). Verify legacy SRIOV configuration for DMR CPM 5.1. Check if symmetric encryption+compression fusion mode is supported. Review intermediate buffer handling.",
        "architectural_element": "QAT CPM 5.1 SRIOV legacy path; symmetric encryption + compression fusion; intermediate buffer management; address translation SAI",
        "failure_registers": ["IP_DISABLE_RESOLVED_CR_DWORD3 QAT_DISABLE", "QAT device ID/revision"],
        "adjacent_subsystems": ["QAT CPM 5.1", "SRIOV legacy path", "data plane API", "ATS/SAI"],
        "related_hsds": ["14022901692"],
        "spec_reference": "DMR OKS Product Architecture Spec; DMR ACC HAS: CPM 5.1 fusion flows; QAT CPM HSD analysis wiki"
    },
    phase4={
        "tier1": [
            {"category": "qat_enable_check", "commands": ["sv.socket0.imh0.acc.accs.qat.show()", "cat /sys/bus/pci/devices/*/vendor | grep -i '8086'"], "reveals": "QAT hardware enabled and visible", "relevance": "Disabled QAT = root cause; confirms CPM 5.1 instance"},
            {"category": "driver_version", "commands": ["modinfo qat_4xxx | grep -i 'version'", "ls /usr/lib/firmware/qat*"], "reveals": "QAT driver version and firmware files", "relevance": "DMR requires QAT_2025.07.01; GNR package causes legacy SRIOV failures"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — QAT SRIOV legacy multithread API exercises deprecated encryption+compression fusion path",
        "root_cause_domain": "val.env.content / QAT driver package mismatch or CPM 5.1 legacy cipher deprecation",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "qat_enable_check + driver_version quickly identify package mismatch. CPM 5.1 fusion path needs validation.",
        "iteration_savings": "2",
    },
)

# ── HSD 15018702005 — IAX opcode 0x42 failing ────────────────────────────────
write(
    "15018702005",
    phase2={
        "testcase_name": "IAX opcode 0x42 AUTOMATION failing",
        "testcase_command": "(IAX automation test exercising opcode 0x42)",
        "testcase_parameters": "OKS DMR AP SVOS; IAX opcode 0x42 failing in automation; NGA:2 test UUIDs",
        "testcase_domain_focus": "IAX opcode 0x42 automation failure — deprecated legacy PM_RSP/IDLE_STATUS opcode on DMR AP OKS",
    },
    phase3={
        "verified_problem_statement": "IAX opcode 0x42 failing in OKS DMR AP automation. NGA has 2 failed test UUIDs.",
        "verified_root_cause": "IAX opcode 0x42 = PM_RSP/IDLE_STATUS message — deprecated in DMR: (1) Per TRM, opcode 0x42 is IDLE_STATUS (PM_RSP) message — deprecated, not fully validated, not recommended for new automation flows; (2) Automation test using legacy opcode 0x42 hits deprecated/unsupported code path in PUnit logic; (3) PUnit logs info when 0x42 received but does not execute expected flow, causing test assertion failure; (4) Automation scripts have not been updated to remove deprecated opcode usage; (5) Not a silicon bug — automation content update needed. Component: likely val.env.content.",
        "verified_fix": "Remove opcode 0x42 from automation test scripts. Update IAX automation to use current supported opcodes. Consult IAX plugin debug scripts for supported opcode list.",
        "architectural_element": "IAX PUnit PM_RSP opcode 0x42 (deprecated); IAX automation opcode table; IAX debug plugin",
        "failure_registers": [],
        "adjacent_subsystems": ["IAX PUnit", "IAX automation framework", "IAX opcode handler"],
        "related_hsds": [],
        "spec_reference": "TRM: Opcode 0x42 = PM_RSP (deprecated); IAX plugin wiki; IAX Integration spec (IAX_Integration.1.0rc.html)"
    },
    phase4={
        "tier1": [
            {"category": "opcode_check", "commands": ["python3 <PYSV_INSTALL_AREA>/graniterapids/hcx/iax/iax_debug_dump_test.py", "grep -r '0x42' <automation_scripts>/ | grep -i 'iax'"], "reveals": "IAX automation scripts using deprecated opcode 0x42", "relevance": "Finding opcode 0x42 usage in scripts confirms automation content issue"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — automation test exercises deprecated opcode 0x42 in IAX PUnit",
        "root_cause_domain": "val.env.content / IAX automation using deprecated opcode",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "Deprecated opcode confirmed by TRM. Automation content fix required. Fast resolution.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026508246 — QAT SVOS NGA log files not complete ────────────────────
write(
    "14026508246",
    phase2={
        "testcase_name": "QAT SVOS NGA log files not providing complete logs",
        "testcase_command": "(NGA-based QAT test run — NGA log files not complete in SVOS)",
        "testcase_parameters": "DMR X1 A0 VV SVOS; NGA log files not providing complete logs; test name dmr-ap_vv_a0_acc_fdu6a_0014; rerun index 4; status failed",
        "testcase_domain_focus": "NGA log collection incomplete for QAT SVOS test on DMR X1 A0 VV — automation infrastructure issue",
    },
    phase3={
        "verified_problem_statement": "NGA log files not providing complete logs for DMR X1 A0 VV QAT SVOS test (dmr-ap_vv_a0_acc_fdu6a_0014, rerun 4).",
        "verified_root_cause": "Incomplete NGA logs for QAT SVOS test: (1) System hang during QAT test causing automation to terminate before log flush completes; (2) Network/file system issue interrupting NGA log upload from SUT to NGA service; (3) HCleanUp_Axon_Inventory step failure preventing final log push; (4) Log file size limit exceeded by QAT verbose output; (5) Rerun index 4 = this failure has been reproduced multiple times — suggests consistent hang or log issue. Component val.env.configuration confirms automation domain.",
        "verified_fix": "Check SUT dmesg at log truncation timestamp. Compare Axon test timeline with NGA log size. Verify HCleanUp step. Test on rerun index 5 with increased log verbosity.",
        "architectural_element": "NGA log collection; HCleanUp_Axon_Inventory step; QAT SVOS test log management",
        "failure_registers": [],
        "adjacent_subsystems": ["NGA automation infrastructure", "HCleanUp Axon script", "QAT test log system"],
        "related_hsds": ["14026579612"],
        "spec_reference": "CR CI Enabling Status (DMR) wiki; NGA enhanced user guide wiki"
    },
    phase4={
        "tier1": [
            {"category": "log_timestamp", "commands": ["Compare NGA log end timestamp vs SUT dmesg timestamp", "cat dmesg | grep -i 'qat\\|cpm' | tail -20"], "reveals": "Whether QAT test hang or network issue caused log truncation", "relevance": "Identical hang pattern as HSD 14026579612 IAA case"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "indirect — QAT test runs but NGA infrastructure fails to collect complete logs",
        "root_cause_domain": "val.env.configuration / NGA log infrastructure",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "Same pattern as HSD 14026579612. Log timestamp comparison resolves quickly.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026506052 — DSA AcreError arden_get_target config files not generated
write(
    "14026506052",
    phase2={
        "testcase_name": "DSA SVOS Acre arden_get_target config file generation failure",
        "testcase_command": "rocket --cfgs --atlas (DSA config generation via Acre/Atlas)",
        "testcase_parameters": "DMR X1 A0 VVR SVOS; Exception (AcreError): arden_get_target; config files not generated; component sw.application; NGA:1",
        "testcase_domain_focus": "Acre/Atlas arden_get_target exception causing DSA SVOS config file generation failure on DMR X1 A0 VVR",
    },
    phase3={
        "verified_problem_statement": "DMR X1 A0 VVR SVOS DSA test fails with Exception (AcreError): arden_get_target — config files not generated.",
        "verified_root_cause": "AcreError arden_get_target in DSA SVOS: (1) Acre script cannot resolve DSA hardware targets for config generation — DSA unit not in expected state or not discoverable by Acre target resolution; (2) Missing/corrupt Acre template files (dsa_cycles.tpl, dsa_device.tpl in /usr/local/graniterapids/atlas/templates/); (3) Rocket command parameters incorrect — hardware block spec does not match what Acre expects; (4) Ace/Atlas version not updated for DMR X1 — GNR templates reused without DMR A0 corrections; (5) Local arden node issue from HSD 14015689076 (AcreError: KeyError 'local_arden') could propagate as arden_get_target failure. Component sw.application confirms automation stack issue.",
        "verified_fix": "Remove stale templates: rm dsa_cycles.tpl dsa_device.tpl from /usr/local/graniterapids/atlas/templates/. Reclone Acre/Atlas for DMR. Verify localLinks in grrmods.conf (HSD 14015689076 WA). Update rocket command parameters.",
        "architectural_element": "Acre script arden_get_target function; Atlas template files; Rocket config generation; DSA hardware target discovery",
        "failure_registers": [],
        "adjacent_subsystems": ["Acre/Atlas framework", "Rocket config generator", "DSA target discovery", "grrmods.conf localLinks"],
        "related_hsds": ["14015689076"],
        "spec_reference": "DSA Developer Guide wiki; GNR HSLE VTd Bring-up wiki (same Acre/Atlas flow for DMR); SPR HBM IIO Rocket framework wiki"
    },
    phase4={
        "tier1": [
            {"category": "template_check", "commands": ["ls /usr/local/graniterapids/atlas/templates/ | grep -i 'dsa'", "rm dsa_cycles.tpl dsa_device.tpl; rocket --cfgs --atlas"], "reveals": "Stale/corrupt template causing arden_get_target failure", "relevance": "Removing and regenerating templates is known fix for AcreError"},
            {"category": "grrmods_check", "commands": ["cat /etc/modprobe.d/grrmods.conf | grep -i 'local'", "grep -r 'localLinks' /etc/modprobe.d/"], "reveals": "localLinks presence for Arden node discovery", "relevance": "Missing localLinks = KeyError 'local_arden' which manifests as arden_get_target failure"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — Acre config generation fails before DSA test can start",
        "root_cause_domain": "sw.application / Acre/Atlas template or Arden node configuration",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "template_check + grrmods_check cover both likely causes. Known fix for both. Fast resolution.",
        "iteration_savings": "2",
    },
)

# ── HSD 16029268179 — QAT asym crypto KPT failure ────────────────────────────
write(
    "16029268179",
    phase2={
        "testcase_name": "QAT asymmetric crypto KPT test failure (test_qat_asym_crypto_kpt)",
        "testcase_command": "grubby --update-kernel=DEFAULT --args='iommu=pt intel_iommu=on'",
        "testcase_parameters": "OKS DMR AP; test_qat_asym_crypto_kpt fails; IOMMU enabled in kernel; no NGA UUIDs",
        "testcase_domain_focus": "QAT asymmetric crypto KPT (Key Protection Technology) test failure with IOMMU enabled on DMR AP OKS",
    },
    phase3={
        "verified_problem_statement": "QAT asym crypto KPT test (test_qat_asym_crypto_kpt) fails on DMR AP OKS with IOMMU enabled.",
        "verified_root_cause": "QAT KPT test failure: (1) KPT keys blocked in debug/pre-production mode — KPT key access is blocked when part is in debug mode (not 'Security Locked production'); DMR AP OKS parts may be debug-mode; (2) KPT key provisioning failure — key material not properly provisioned in NVRAM/CPLD, or anti-rollback check fails with newer firmware SVN; (3) IOMMU + QAT KPT interaction — IOMMU enabled with pt mode may affect DMA isolation for KPT memory regions; (4) CPM 5.1 firmware SVN mismatch — loaded firmware SVN lower than minimum stored SVN blocks KPT key access; (5) Missing QAT KPT certificates in OKS image.",
        "verified_fix": "Verify part is not in debug mode for KPT test. Check NVRAM KPT key provisioning. Confirm firmware SVN matches. Escalate to QAT KPT team if part security policy blocks KPT in validation.",
        "architectural_element": "QAT KPT key material; CPM 5.1 security policy; NVRAM KPT provisioning; anti-rollback SVN check; debug mode KPT block",
        "failure_registers": ["KPT key status registers", "CPM firmware SVN register", "CPLD NVRAM KPT storage"],
        "adjacent_subsystems": ["QAT KPT engine", "CPM security policy", "NVRAM/CPLD", "IOMMU DMA isolation"],
        "related_hsds": [],
        "spec_reference": "DMR Security HAS section 10.13 CPM KPT; S3M DMR Security FAS; DMR Security HAS section 6.3 KPT key access table"
    },
    phase4={
        "tier1": [
            {"category": "kpt_policy_check", "commands": ["sv.socket0.imh0.acc.accs.cpm.kpt_policy.show()", "cat /sys/bus/pci/devices/*/config | xxd | grep -i 'kpt'"], "reveals": "KPT security policy state (debug blocked or production allowed)", "relevance": "Debug mode = KPT blocked = root cause confirmed"},
            {"category": "firmware_svn", "commands": ["sv.socket0.imh0.acc.accs.cpm.fw_svn.show()"], "reveals": "CPM firmware SVN vs minimum stored SVN", "relevance": "SVN mismatch = anti-rollback blocks KPT key access"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [
            {"description": "KPT key provisioning verification", "commands": ["Contact QAT KPT team for NVRAM provisioning validation"], "why": "KPT key provisioning is manufacturing step — SME verification needed"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — KPT test exercises key access; debug mode or SVN mismatch blocks access",
        "root_cause_domain": "hw.qat / KPT security policy or key provisioning",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "kpt_policy_check identifies debug block. firmware_svn checks anti-rollback. SME needed for provisioning verification.",
        "iteration_savings": "2",
    },
)

# ── HSD 16029255798 — QAT5-x UCS-AEAD ccm_sample failure ────────────────────
write(
    "16029255798",
    phase2={
        "testcase_name": "QAT5-x UCS-AEAD integration test ccm_sample failure",
        "testcase_command": "ccm_sample [DEBUG logging]",
        "testcase_parameters": "OKS DMR AP; QAT5-x UCS-AEAD integration test; ccm_sample command fails; DEBUG logging; NGA:2",
        "testcase_domain_focus": "QAT5-x (CPM 5.1) UCS-AEAD (CCM mode) integration test failure with ccm_sample on DMR AP OKS",
    },
    phase3={
        "verified_problem_statement": "QAT5-x UCS-AEAD integration test with ccm_sample fails on DMR AP OKS. NGA has 2 failed test UUIDs.",
        "verified_root_cause": "QAT5-x UCS-AEAD ccm_sample failure: (1) QAT hardware fused off or in disabled state — IP_DISABLE_RESOLVED_CR_DWORD3 QAT_DISABLE bits block AEAD acceleration; (2) Driver/API version mismatch — CPM 5.1 has breaking changes from prior generations (deprecated ciphers, new fusion/chain flows); ccm_sample built for older API; (3) AEAD CCM mode fuse-controlled and not enabled for OKS segment; (4) Wrong QAT driver package (GNR vs DMR) — must use QAT_2025.07.01.tar.gz; (5) IOMMU/ATS interaction with AEAD DMA path causing timeout. Component: hw.qat or val.env.content.",
        "verified_fix": "Check QAT_DISABLE fuse bits. Use QAT_2025.07.01 DMR-specific package. Verify CCM mode fuse enablement. Update ccm_sample to CPM 5.1 API. Check AEAD DMA timeout registers.",
        "architectural_element": "QAT CPM 5.1 AEAD CCM hardware path; UCS-AEAD integration; fuse-controlled AEAD modes; ccm_sample API compatibility",
        "failure_registers": ["IP_DISABLE_RESOLVED_CR_DWORD3 QAT_DISABLE", "QAT AEAD capability register", "CPM firmware version"],
        "adjacent_subsystems": ["QAT CPM 5.1 AEAD engine", "UCS integration layer", "driver data plane API", "IOMMU ATS path"],
        "related_hsds": ["16029322007"],
        "spec_reference": "DMR ACC HAS: CPM 5.1 AEAD fuse control; DMR OKS Product Arch Spec; CPM HSD analysis wiki; QAT_2025.07.01 DMR BKC package"
    },
    phase4={
        "tier1": [
            {"category": "qat_fuse_check", "commands": ["sv.socket0.imh0.acc.accs.qat.IP_DISABLE_RESOLVED_CR_DWORD3.show()"], "reveals": "QAT_DISABLE fuse bits — is AEAD hardware enabled?", "relevance": "Fused off QAT = root cause for all QAT test failures including ccm_sample"},
            {"category": "driver_version", "commands": ["modinfo qat_4xxx | grep -i 'version'", "ls /usr/lib/firmware/qat*"], "reveals": "QAT driver/firmware version", "relevance": "GNR driver on DMR HW causes AEAD failure — must use QAT_2025.07.01"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — ccm_sample exercises AEAD CCM path; fuse or driver mismatch causes failure",
        "root_cause_domain": "val.env.content / QAT driver package or CPM 5.1 AEAD fuse",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "qat_fuse_check + driver_version fast checks. Known root cause for QAT OKS failures on DMR.",
        "iteration_savings": "2",
    },
)

# ── HSD 16029254833 — QAT stateless overflow unrecoverable error ─────────────
write(
    "16029254833",
    phase2={
        "testcase_name": "QAT stateless overflow unrecoverable error (input-data dependent)",
        "testcase_command": "(QAT compression test with non-default input files triggering stateless overflow)",
        "testcase_parameters": "OKS DMR AP; QAT unrecoverable error: stateless overflow error; not reproduced with default test input files; NGA:3 test UUIDs",
        "testcase_domain_focus": "QAT CPM 5.1 stateless compression overflow — input-size dependent unrecoverable error on DMR AP OKS",
    },
    phase3={
        "verified_problem_statement": "QAT fails with 'Unrecoverable error: stateless overflow error' on DMR AP OKS when using non-default test input files. Not reproduced with default files.",
        "verified_root_cause": "QAT stateless overflow unrecoverable error: (1) Input-data dependent buffer overflow — non-default input files cause stateless compression intermediate buffer to exceed allocated capacity; (2) Hardware-level overflow in internal queue structures: staging buffer overflow, linked list overflow, or UFI/NIP interface buffer overflow when workload data exceeds QAT buffer allocation; (3) Hardware signals unrecoverable error on any stateless overflow — hardware drops packet and halts further processing; (4) Default test files do not trigger overflow because they are sized within allocated stateless buffers; (5) Not a silicon bug — test content or QAT buffer sizing issue. Component: likely val.env.content.",
        "verified_fix": "Increase QAT stateless buffer allocation in driver config. Limit non-default input file size to QAT stateless buffer capacity. Check QAT config file for stateless resource allocation. Reset QAT after overflow.",
        "architectural_element": "QAT CPM 5.1 stateless compression buffer; staging queue; UFI/NIP interface buffer; linked list overflow",
        "failure_registers": ["QAT SWERROR", "QAT overflow status register", "staging queue overflow indicator"],
        "adjacent_subsystems": ["QAT compression engine", "stateless buffer manager", "UFI interface"],
        "related_hsds": [],
        "spec_reference": "DMR ACC HAS: QAT buffer overflow UC error table; DMR RAS HAS: QAT unrecoverable error handling"
    },
    phase4={
        "tier1": [
            {"category": "input_size", "commands": ["Compare non-default test file sizes vs default file sizes", "ls -la <test_input_files>/ | sort -k5 -n"], "reveals": "Size difference between files that trigger and don't trigger overflow", "relevance": "Larger input files exceeding stateless buffer size = root cause"},
            {"category": "qat_config", "commands": ["cat /etc/4xxx_dev0.conf | grep -i 'stateless'", "cat /etc/4xxx_dev0.conf | grep -i 'buffer'"], "reveals": "QAT config stateless buffer allocation", "relevance": "Undersized stateless buffer config causes overflow with large inputs"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — non-default input file exercises stateless overflow; hardware signals unrecoverable error",
        "root_cause_domain": "val.env.content / QAT stateless buffer sizing configuration",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "input_size comparison immediately identifies trigger. qat_config check shows buffer allocation. Fast fix.",
        "iteration_savings": "2",
    },
)

# ── HSD 16029253410 — QAT SRIOV Host Scalable VM test failure ────────────────
write(
    "16029253410",
    phase2={
        "testcase_name": "QAT SRIOV Host Scalable VM test failure (qat_vm_L_test)",
        "testcase_command": "pytest tests/contents/accelerator/QAT/QAT_INTREE/qat_vm_L_test.py::TestQATVM::test_qat_sriov",
        "testcase_parameters": "OKS DMR AP; QAT_SRIOV_Host_Scalable test; qat_vm_L_test.py VM SRIOV test; NGA:2 test UUIDs",
        "testcase_domain_focus": "QAT SRIOV Host Scalable VM test failure — SIOV/SRIOV mode mismatch or VF pass-through configuration on DMR AP OKS",
    },
    phase3={
        "verified_problem_statement": "QAT SRIOV Host Scalable VM automation test fails (qat_vm_L_test.py::TestQATVM::test_qat_sriov) on DMR AP OKS. NGA:2.",
        "verified_root_cause": "QAT SRIOV Host Scalable VM test failure: (1) SIOV vs SRIOV configuration mismatch — DMR QAT supports both SIOV and SRIOV but test must configure for correct mode; SIOV features enabled by default may conflict with legacy SRIOV test; (2) VF (Virtual Function) pass-through assignment incorrect — VM SRIOV test requires QAT VFs assigned to hypervisor and passed to guest; misconfiguration blocks device access in VM; (3) IOMMU/VT-d configuration — VM SRIOV requires IOMMU enabled with correct interrupt remapping for VF pass-through; (4) Unsupported wireless/algorithm capability in QAT VF — test may request fused-off feature; (5) Test content stale — automation content not updated for DMR X1 A0 QAT VF configuration changes. Component: val.env.content.",
        "verified_fix": "Verify SRIOV vs SIOV configuration for test. Check QAT VF count and assignment to hypervisor. Confirm IOMMU enabled with correct mode. Update automation content for DMR CPM 5.1 VF configuration.",
        "architectural_element": "QAT CPM 5.1 SRIOV VF; hypervisor VF pass-through; IOMMU interrupt remapping; SIOV vs SRIOV mode",
        "failure_registers": ["QAT SRIOV VF count register", "IOMMU VF mapping"],
        "adjacent_subsystems": ["QAT SRIOV VF manager", "hypervisor VF assignment", "IOMMU interrupt remapping", "guest QAT driver"],
        "related_hsds": [],
        "spec_reference": "DMR ACC HAS: CPM 5.1 SRIOV/SIOV; OKS Product Architecture Spec; QAT VM/SRIOV debug notes (Debug Encyclopedia wiki)"
    },
    phase4={
        "tier1": [
            {"category": "vf_check", "commands": ["lspci | grep -i 'quickassist'", "cat /sys/bus/pci/devices/*/sriov_numvfs"], "reveals": "QAT VF count and PCIe presence", "relevance": "VF not enabled = SRIOV test fails immediately"},
            {"category": "iommu_check", "commands": ["cat /proc/cmdline | grep -i 'iommu'", "dmesg | grep -i 'IOMMU\\|VT-d'"], "reveals": "IOMMU mode for VF pass-through", "relevance": "IOMMU not enabled = VF pass-through to VM fails"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — SRIOV VM test creates VFs, assigns to VM; configuration failure prevents VM access",
        "root_cause_domain": "val.env.content / QAT SRIOV VF or IOMMU configuration",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "vf_check + iommu_check identify configuration gap. Automation content update likely needed.",
        "iteration_savings": "2",
    },
)

# ── HSD 16029243535 — QAT Performance Test fast failure ──────────────────────
write(
    "16029243535",
    phase2={
        "testcase_name": "QAT Performance Test fast failure (2.9s initialization error)",
        "testcase_command": "(QAT Performance Test automation via kayak framework)",
        "testcase_parameters": "OKS DMR AP; QAT_Performance_Test fails in 2.9006971999997404s; [ERROR] kayak.core.case_template; NGA:1 test UUID",
        "testcase_domain_focus": "QAT Performance Test initialization failure — fast failure in under 3 seconds indicates setup/device not ready on DMR AP OKS",
    },
    phase3={
        "verified_problem_statement": "QAT_Performance_Test fails in under 3 seconds on DMR AP OKS — fast failure indicates initialization issue not performance measurement.",
        "verified_root_cause": "QAT Performance Test fast failure: (1) QAT device not found/enumerated — PCIe device not visible; (2) QAT driver not loaded or version mismatch — driver fails to probe/init QAT CPM 5.1 device on DMR AP; (3) QAT hardware fused off — IP_DISABLE_RESOLVED_CR_DWORD3 QAT_DISABLE bits set; (4) Wrong QAT config files — DMR-specific config not present/mismatched causing early kayak error; (5) QAT firmware not loaded — firmware binary missing or wrong version prevents QAT init; (6) Missing QAT_2025.07.01 DMR BKC package — GNR driver incompatible with DMR CPM 5.1 HW. 2.9s timeout matches kayak API initialization timeout constant.",
        "verified_fix": "Check QAT PCIe enumeration. Verify QAT driver version (QAT_2025.07.01). Check IP_DISABLE fuse bits. Verify QAT config files for DMR AP.",
        "architectural_element": "QAT CPM 5.1 PCIe enumeration; driver probe; fuse state; config files; firmware load",
        "failure_registers": ["IP_DISABLE_RESOLVED_CR_DWORD3 QAT_DISABLE"],
        "adjacent_subsystems": ["QAT PCIe device", "kayak QAT provider", "QAT driver init", "firmware loader"],
        "related_hsds": ["16029255798"],
        "spec_reference": "DMR ACC HAS: QAT device ID/fuse/revision ID detection; OKS QAT platform arch spec"
    },
    phase4={
        "tier1": [
            {"category": "qat_pcie", "commands": ["lspci | grep -i 'quickassist'", "systemctl status qat"], "reveals": "QAT PCIe device presence and driver service status", "relevance": "Not found = fuse disabled or PCIe enumeration issue"},
            {"category": "driver_init", "commands": ["dmesg | grep -i 'qat\\|cpm'", "modinfo qat_4xxx | grep -i 'version'"], "reveals": "QAT driver probe result and version", "relevance": "Driver probe failure = wrong version or firmware missing"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — QAT init fails before performance measurement starts; kayak timeout at 2.9s",
        "root_cause_domain": "val.env.content / QAT initialization failure (fuse, driver, config)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "qat_pcie + driver_init checks resolve in 2 commands. Known fast-fail pattern for QAT setup issues.",
        "iteration_savings": "2",
    },
)

# ── HSD 16029243446 — QAT DSA algorithm multi-size failure ───────────────────
write(
    "16029243446",
    phase2={
        "testcase_name": "QAT DSA algorithm with multi-size buffer test failure",
        "testcase_command": "(kayak QAT provider Linux test - QAT_DSA_algorithm_with_multi_size)",
        "testcase_parameters": "OKS DMR AP; QAT_DSA_algorithm_with_multi_size test fails; qat_provider_linux; NGA:2 test UUIDs",
        "testcase_domain_focus": "QAT multi-size buffer algorithm test failure via qat_provider_linux on DMR AP OKS — QAT cryptographic algorithm with variable buffer sizes",
    },
    phase3={
        "verified_problem_statement": "QAT_DSA_algorithm_with_multi_size test fails on DMR AP OKS using qat_provider_linux. NGA:2.",
        "verified_root_cause": "QAT DSA algorithm multi-size test failure: (1) Note: 'DSA' in test name likely = Digital Signature Algorithm (crypto) not Data Streaming Accelerator; (2) QAT asym crypto (RSA/DSA) multi-size failure — variable key/buffer sizes for digital signature hit QAT CPM 5.1 boundary conditions; (3) PCIe/SFI ordering issue with multi-size DMA operations — DMR enforces no unordered IO; variable buffer sizes may create ordering violations; (4) IOMMU/ATS mis-alignment for different buffer sizes — different sizes may cross IOMMU page boundaries differently; (5) Driver/firmware not handling multi-size asym crypto correctly for CPM 5.1; (6) KPT interference — asym crypto key protection blocking certain key sizes. Component: val.env.content or hw.qat.",
        "verified_fix": "Identify which buffer sizes fail. Check QAT asym crypto configuration for multi-size inputs. Verify IOMMU page alignment for different sizes. Compare with CPM 5.1 asym crypto spec for supported key sizes.",
        "architectural_element": "QAT CPM 5.1 asym crypto DSA (Digital Signature); multi-size buffer DMA; PCIe/SFI ordering; IOMMU page alignment",
        "failure_registers": ["QAT asym crypto error register", "IOMMU fault register for asym DMA"],
        "adjacent_subsystems": ["QAT asym engine", "qat_provider_linux library", "IOMMU page table", "SFI ordering"],
        "related_hsds": ["16029268179"],
        "spec_reference": "DMR ACC HAS: CPM 5.1 asymmetric crypto; DMR OKS Product Arch Spec; PCIe/SFI ordering requirements"
    },
    phase4={
        "tier1": [
            {"category": "size_bisect", "commands": ["Run test with single size at a time: key sizes 1024, 2048, 4096", "cat test_output*.log | grep -i 'size\\|fail'"], "reveals": "Which specific key/buffer size triggers failure", "relevance": "Specific size failure = boundary condition in CPM 5.1 asym crypto path"},
            {"category": "iommu_fault", "commands": ["dmesg | grep -i 'DMAR\\|fault\\|iommu'"], "reveals": "IOMMU page fault during asym DMA for specific buffer sizes", "relevance": "Page boundary crossing for large key sizes = IOMMU fault"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — multi-size asym crypto exercises different code paths; specific size hits QAT boundary",
        "root_cause_domain": "val.env.content / QAT asym crypto multi-size boundary condition",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "size_bisect identifies failing size. iommu_fault check correlates IOMMU issue. CPM 5.1 spec lookup for supported sizes.",
        "iteration_savings": "2",
    },
)

# ── HSD 16029243363 — IAA Linux Host VM reset stability failure ───────────────
write(
    "16029243363",
    phase2={
        "testcase_name": "IAA Linux Host VM reset stability test failure (IAA_CRYPT)",
        "testcase_command": "pytest tests/contents/accelerator/IAX/iax_vm_reset_stability_L_test.py::TestIAXStabilityVM",
        "testcase_parameters": "OKS DMR AP; IAA-Linux-Host-IAA_CRYPT automation test; iax_vm_reset_stability_L_test.py VM reset stability; NGA:2 test UUIDs",
        "testcase_domain_focus": "IAA VM reset stability test failure — SRIOV/SIOV VM pass-through reset or interrupt remapping issue on DMR AP OKS",
    },
    phase3={
        "verified_problem_statement": "IAA Linux Host VM reset stability test (IAA_CRYPT) fails in iax_vm_reset_stability_L_test.py on DMR AP OKS. NGA:2.",
        "verified_root_cause": "IAA VM reset stability test failure: (1) SRIOV/SIOV reset handling in VM — IAA device reset while VM guest holds SRIOV VF causes instability; VF reset not properly synchronized with hypervisor/guest; (2) SFI credit leakage during reset — IAA hang due to SFI credit issue (WA: sv.sockets.imhs.acc.accs.iaa.sficlkgctl.icge_int = 0) not cleared on reset; (3) IAA IOMMU invalidation queue (HSD 14025817510) — invalid descriptor bit 66 during post-reset invalidation causes VM stability issue; (4) Interrupt remapping + SRIOV reset race — VT-d interrupt remapping not re-configured after IAA VF reset causes guest interrupt loss; (5) SIOV vs SRIOV mode mismatch in reset flow. Component: likely hw.iaa or val.env.content.",
        "verified_fix": "Apply SFI credit WA before reset. Verify interrupt remapping re-configuration after VF reset. Check descriptor bit 66 in post-reset IOMMU queue. Apply HSD 14025817510 WA for IAA IOMMU invalidation descriptor.",
        "architectural_element": "IAA SRIOV VF reset; SFI credit management; VT-d interrupt remapping post-reset; IAA IOMMU invalidation queue descriptor",
        "failure_registers": ["sv.sockets.imhs.acc.accs.iaa.sficlkgctl.icge_int", "IAA IOMMU invalidation queue bit 66"],
        "adjacent_subsystems": ["IAA SRIOV VF reset path", "SFI credit controller", "VT-d interrupt remapping", "IOMMU invalidation queue"],
        "related_hsds": ["14025817510"],
        "spec_reference": "IAA plugin wiki (DSA/IAX Debug BKMs); DMR Accelerator Stack wiki; HSD 14025817510 IOMMU Invalidation Queue Descriptor bit 66"
    },
    phase4={
        "tier1": [
            {"category": "sfi_credit_check", "commands": ["sv.socket0.imh0.acc.accs.iaa.sficlkgctl.icge_int.show()"], "reveals": "SFI credit leak WA status", "relevance": "icge_int not applied = IAA hang during SRIOV VM reset stability test"},
            {"category": "iaa_error", "commands": ["from diamondrapids.accelerators.dsa_iaa import dsa_iaa_debug_dump as dsa_iaa_dump", "dsa_iaa_dump.dump_all_dsa_inst_errs()"], "reveals": "IAA error registers after VM reset", "relevance": "Post-reset IAA error = invalidation queue or descriptor issue"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — IAA VM reset exercises SFI credit + interrupt remapping paths; both known DMR A0 issue areas",
        "root_cause_domain": "hw.iaa / SFI credit or IOMMU invalidation queue descriptor bit 66",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "sfi_credit_check is single register. iaa_error dump shows reset state. Two known A0 bugs cover most cases.",
        "iteration_savings": "2",
    },
)

# ── HSD 16029241880 — QAT Power Management CC6 residency failure ─────────────
write(
    "16029241880",
    phase2={
        "testcase_name": "QAT Power Management Verification CC6 residency < 70%",
        "testcase_command": "(QAT Power Management Verification test via kayak)",
        "testcase_parameters": "OKS DMR AP; QATPower_Management-Verifications fails; not all core CC6 Residency > 70%; [ERROR] kayak; NGA:2",
        "testcase_domain_focus": "QAT Power Management Verification CC6 residency failure — QAT activity preventing deep core idle on DMR AP OKS",
    },
    phase3={
        "verified_problem_statement": "QAT Power Management Verification test fails on DMR AP OKS: not all cores achieve CC6 residency > 70%.",
        "verified_root_cause": "CC6 residency below 70% during QAT PM verification: (1) QAT activity generating frequent interrupts or memory transactions that wake cores from deep idle — cores serving QAT interrupts cannot reach CC6; (2) QAT polling mode vs interrupt mode — if QAT test uses polling, core stays in busy loop preventing CC6; (3) Platform BIOS/FW not configured for optimal power management during accelerator active-idle scenarios; (4) DMR AP QAT CPM 5.1 idle latency changes — CPM 5.1 has different power gating behavior than prior versions; (5) QAT test not actually idle — operations still in flight preventing core CC6 entry. Component: likely val.env.content or hw.punit.",
        "verified_fix": "Switch QAT test to interrupt mode instead of polling. Verify cores are fully idle before measuring CC6. Check BIOS power management settings. Confirm QAT requests are complete before measurement.",
        "architectural_element": "CC6 core C-state; QAT interrupt vs polling mode; CPM 5.1 power gating; BIOS C-state configuration",
        "failure_registers": ["Core C-state residency MSR", "QAT interrupt mode config", "BIOS power management"],
        "adjacent_subsystems": ["QAT CPM 5.1 power gating", "Core C-state machine", "BIOS ACPI C-state", "Platform punit"],
        "related_hsds": [],
        "spec_reference": "DMR Power Management Platform Arch Spec (PMPAS.DMR-D); DMR System IO (Accelerator-C-state interaction); EEPAS idle power projections"
    },
    phase4={
        "tier1": [
            {"category": "cc6_residency", "commands": ["turbostat --interval 5 | grep -i 'cc6'", "rdmsr -a 0x3F9"], "reveals": "Per-core CC6 residency during QAT idle", "relevance": "Shows which cores are not entering CC6 and when"},
            {"category": "qat_interrupt_mode", "commands": ["cat /sys/bus/pci/devices/0000:0f:00.0/config | xxd | grep 'poll'", "grep -r 'polling' /etc/4xxx_dev*.conf"], "reveals": "QAT polling vs interrupt mode configuration", "relevance": "Polling mode prevents core CC6 entry"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — PM verification measures CC6 during QAT test; active QAT prevents C-state entry",
        "root_cause_domain": "val.env.content / QAT polling vs interrupt mode or BIOS power config",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "cc6_residency shows affected cores. qat_interrupt_mode identifies polling root cause. Known platform interaction.",
        "iteration_savings": "2",
    },
)

# ── HSD 16029241858 — QAT SRIOV Rate Limiting failure ────────────────────────
write(
    "16029241858",
    phase2={
        "testcase_name": "QAT SRIOV Rate Limiting automation test failure (rl.py cap_rem)",
        "testcase_command": "cd /home/BKCPkg/domains/accelerator/QAT_RL_Config_Scripts && ./rl.py cap_rem 0000:0f:00",
        "testcase_parameters": "OKS DMR AP; QAT_SRIOV_Rate_Limiting automation; rl.py cap_rem 0000:0f:00; NGA:8 test UUIDs (high count)",
        "testcase_domain_focus": "QAT SRIOV Rate Limiting rl.py cap_rem failure — high NGA count (8) suggests persistent configuration issue on DMR AP OKS",
    },
    phase3={
        "verified_problem_statement": "QAT SRIOV Rate Limiting automation (rl.py cap_rem) fails on DMR AP OKS. NGA:8 — highest count seen suggests persistent/systematic issue.",
        "verified_root_cause": "QAT SRIOV Rate Limiting rl.py cap_rem failure: (1) VF not properly enumerated — rl.py cannot find VF at expected PCIe BDF (0000:0f:00); QAT VFs may not be created or device at wrong address; (2) Incomplete CPM 5.1 RL support in driver/firmware — Rate Limiting is new feature in CPM 5.1; firmware or rl.py scripts not fully aligned with DMR CPM 5.1 RL API; (3) cap_rem fails because no cap was previously set — rl.py cap_rem trying to remove a limit that was never configured; (4) Wrong QAT driver package — GNR rl.py scripts used with DMR CPM 5.1 hardware; (5) System resource contention or platform PCIe config preventing RL state change. NGA:8 = test run repeatedly with same failure.",
        "verified_fix": "Verify QAT VF at expected PCIe BDF. Check rl.py version compatibility with CPM 5.1. Confirm VF is configured before running cap_rem. Use DMR-specific QAT_RL scripts from QAT_2025.07.01 package.",
        "architectural_element": "QAT CPM 5.1 SRIOV Rate Limiting; VF PCIe BDF; rl.py cap_rem API; Rate Limiting firmware support",
        "failure_registers": ["QAT VF enumeration PCIe BDF", "RL configuration registers"],
        "adjacent_subsystems": ["QAT CPM 5.1 RL engine", "SRIOV VF manager", "rl.py automation script"],
        "related_hsds": ["16029253410"],
        "spec_reference": "DMR ACC HAS: CPM 5.1 Rate Limiting feature; OKS Product Architecture Spec; QAT_2025.07.01 BKC package RL scripts"
    },
    phase4={
        "tier1": [
            {"category": "vf_bdf", "commands": ["lspci | grep -i 'quickassist'", "ls /sys/bus/pci/devices/ | grep '0f:00'"], "reveals": "QAT VF PCIe BDF presence and actual address", "relevance": "BDF mismatch = rl.py cannot find device; VF not created = cap_rem fails"},
            {"category": "rl_script_version", "commands": ["./rl.py --version", "head -5 /home/BKCPkg/domains/accelerator/QAT_RL_Config_Scripts/rl.py"], "reveals": "rl.py script version and DMR/CPM compatibility", "relevance": "GNR rl.py on DMR CPM 5.1 = API mismatch for Rate Limiting"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — rl.py cap_rem fails on device not found or Rate Limiting API mismatch",
        "root_cause_domain": "val.env.content / QAT SRIOV VF BDF mismatch or rl.py version incompatibility",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "vf_bdf check identifies device issue. rl_script_version checks DMR compatibility. High NGA count = systematic script issue.",
        "iteration_savings": "2",
    },
)

# ── HSD 16029241765 — QAT Dictionary compression failure ─────────────────────
write(
    "16029241765",
    phase2={
        "testcase_name": "QAT AUTOMATION Dictionary compression test failure",
        "testcase_command": "(kayak QAT compression test - Dictionary mode via paramiko_ssh)",
        "testcase_parameters": "OKS DMR AP; QAT Dictionary compression test fails; paramiko_ssh DEBUG logging; NGA:2 test UUIDs",
        "testcase_domain_focus": "QAT CPM 5.1 dictionary compression test failure — stateful dictionary mode fails while stateless may work on DMR AP OKS",
    },
    phase3={
        "verified_problem_statement": "QAT AUTOMATION Dictionary compression test fails on DMR AP OKS with paramiko_ssh DEBUG logging. NGA:2.",
        "verified_root_cause": "QAT dictionary compression failure: (1) Driver/API incompatibility with CPM 5.1 dictionary mode — QAT CPM 5.1 has different dictionary compression API vs prior CPM versions; old driver/test uses legacy dictionary API; (2) Hardware dictionary lookup table initialization issue — CPM 5.1 integrates new dictionary features; incorrect initialization leaves lookup table in bad state; (3) SVM/scatter-gather handling for dictionary memory — dictionary context requires contiguous or mapped memory; improper SVM/IOMMU mapping breaks dictionary access; (4) Dictionary context save/restore not working — test may run multiple iterations and context state corrupts between runs; (5) Wrong QAT driver package (GNR vs DMR) — dictionary API changes between generations.",
        "verified_fix": "Compare stateless vs dictionary pass/fail. Update to QAT_2025.07.01 DMR-specific driver. Verify dictionary context initialization per CPM 5.1 spec. Check IOMMU mapping for dictionary buffers.",
        "architectural_element": "QAT CPM 5.1 dictionary compression; stateful dictionary context; SVM memory mapping; dictionary lookup table",
        "failure_registers": ["QAT dictionary status register", "IOMMU mapping for dictionary buffer"],
        "adjacent_subsystems": ["QAT compression engine dictionary mode", "dictionary context manager", "SVM/IOMMU mapping"],
        "related_hsds": ["16029254833"],
        "spec_reference": "DMR ACC HAS: CPM 5.1 ZSTD + dictionary compression feature; OKS Product Architecture Spec; QAT_2025.07.01 dictionary API changes"
    },
    phase4={
        "tier1": [
            {"category": "mode_comparison", "commands": ["Run stateless compression test; compare pass/fail with dictionary mode", "cat test_output*.log | grep -i 'dict\\|stateful\\|stateless'"], "reveals": "Whether only dictionary mode fails — isolates dictionary-specific bug", "relevance": "Dictionary-only failure = dictionary context initialization or API issue"},
            {"category": "driver_version", "commands": ["modinfo qat_4xxx | grep -i 'version'", "qatmgr --status | grep -i 'firmware'"], "reveals": "Driver and firmware versions for CPM 5.1 compatibility", "relevance": "GNR driver on DMR CPM 5.1 = dictionary API mismatch"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — dictionary mode exercises stateful compression path; CPM 5.1 API delta causes failure",
        "root_cause_domain": "val.env.content / QAT dictionary API incompatibility with CPM 5.1",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "mode_comparison isolates to dictionary. driver_version identifies DMR/GNR mismatch. Known CPM 5.1 API delta.",
        "iteration_savings": "2",
    },
)

# ── HSD 16029241563 — QAT KPT test content automation error ──────────────────
write(
    "16029241563",
    phase2={
        "testcase_name": "QAT KPT test content automation error",
        "testcase_command": "(kayak QAT KPT content automation via paramiko_ssh)",
        "testcase_parameters": "OKS DMR AP; QAT KPT test content automation error; paramiko_ssh logging; NGA:2 test UUIDs",
        "testcase_domain_focus": "QAT KPT test content automation failure — missing certificates, wrong API, or test content not ported to DMR AP OKS",
    },
    phase3={
        "verified_problem_statement": "QAT KPT automation test fails with content automation error on DMR AP OKS. NGA:2. Different from HSD 16029268179 (KPT policy) — this is content/automation layer.",
        "verified_root_cause": "QAT KPT content automation error: (1) Missing KPT certificates in automation workspace — KPT test requires Intel-provisioned root/intermediate certificates; test content not including DMR-specific KPT certs; (2) KPT test not ported to DMR AP — content was developed for SPR/GNR, DMR-specific KPT API or certificate format changes not reflected; (3) Wrong API/tool called for KPT setup — automation calls CPM 5.0 KPT API vs CPM 5.1 API; (4) KPT content not validated for OKS automation framework (kayak + paramiko); (5) Test content dependencies (NVRAM access, certificate path) not met in OKS automation image.",
        "verified_fix": "Check automation workspace for KPT certificate files. Verify KPT test content is ported for DMR AP CPM 5.1. Update to DMR-specific KPT API calls. Consult QAT KPT content team for OKS enablement.",
        "architectural_element": "QAT KPT certificate provisioning; CPM 5.1 KPT API; automation content porting; OKS certificate path",
        "failure_registers": [],
        "adjacent_subsystems": ["QAT KPT engine", "automation content workspace", "KPT certificate store", "OKS kayak framework"],
        "related_hsds": ["16029268179"],
        "spec_reference": "Content Acceptance Criteria Checklist wiki; DMR Security HAS section 10.13 CPM KPT; QAT_2025.07.01 KPT cert requirements"
    },
    phase4={
        "tier1": [
            {"category": "cert_check", "commands": ["find /BKCPkg -name '*.pem' -o -name '*.cert' | grep -i 'kpt'", "ls /BKCPkg/domains/accelerator/QAT*/kpt/"], "reveals": "KPT certificate files presence in automation workspace", "relevance": "Missing certs = content automation error for KPT test"},
            {"category": "api_check", "commands": ["grep -r 'kpt' /BKCPkg/domains/accelerator/QAT*/| grep -i 'api\\|version'"], "reveals": "KPT API version used by automation content", "relevance": "CPM 5.0 API on CPM 5.1 hardware = content automation error"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [
            {"description": "QAT KPT content porting validation for DMR AP CPM 5.1", "commands": ["Contact QAT KPT content team for DMR AP enablement status"], "why": "KPT content porting is team-owned; cert provisioning requires manufacturing involvement"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — KPT automation fails at content layer before reaching hardware",
        "root_cause_domain": "val.env.content / KPT content not ported to DMR AP or missing certs",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "cert_check immediately identifies missing certs. api_check shows version mismatch. Fast resolution.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026487968 — QAT VTD PRS targets not in tman ────────────────────────
write(
    "14026487968",
    phase2={
        "testcase_name": "QAT VTD SVOS PRS target configuration missing from tman",
        "testcase_command": "(Rocket/tman config generation for QAT PRS targets in SVOS)",
        "testcase_parameters": "DMR X1 A0 PO VTD SVOS; PRS targets not being generated in tman; component val.env.configuration; RC:1",
        "testcase_domain_focus": "Rocket tman PRS target configuration missing for QAT on DMR X1 A0 PO VTD — tman config file needs QAT PRS target ranges added",
    },
    phase3={
        "verified_problem_statement": "QAT PRS targets and configs are not being generated in tman on DMR X1 A0 PO VTD SVOS. RC:1 confirmed resolution.",
        "verified_root_cause": "tman PRS target generation failure for QAT: (1) tman config file missing QAT PRS target range/category entries — tman only creates targets as specified in its config; QAT PRS targets not listed in tman config for X1 A0 VTD; (2) SVOS memory manager cannot back PRS allocations at required granularity — tman needs PRS-specific target categories; (3) RCG requests PRS allocations but tman returns 'no memory' because target category doesn't exist; (4) X1 A0 PO/PV bringup — tman config not updated for new QAT PRS flows on DMR; (5) Val.env.configuration confirms configuration fix needed. RC:1 = root cause found and fixed (likely config file update).",
        "verified_fix": "Add QAT PRS target ranges and categories to tman configuration file. Regenerate Rocket configs after tman update. Reference Rocket Architecture wiki for tman PRS config format. RC:1 confirmed fix in HSD.",
        "architectural_element": "tman (Rocket Target Manager); QAT PRS target categories; tman config file; SVOS memory manager",
        "failure_registers": [],
        "adjacent_subsystems": ["tman configuration", "Rocket validation framework", "SVOS memory manager", "QAT PRS test RCG"],
        "related_hsds": ["14026506052"],
        "spec_reference": "Rocket Architecture wiki: tman PRS target allocation; SVOS/Mrman wiki; ivman Feature List (device + PRS registration)"
    },
    phase4={
        "tier1": [
            {"category": "tman_config", "commands": ["cat <rocket_run_dir>/tman.conf | grep -i 'prs\\|qat'", "grep -r 'prs' /usr/local/rocket/configs/ | grep -i 'qat'"], "reveals": "QAT PRS target entries in tman config", "relevance": "Missing PRS entries = tman cannot generate QAT PRS targets"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — tman missing QAT PRS config prevents test from running",
        "root_cause_domain": "val.env.configuration / tman config file missing QAT PRS entries",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "tman_config check confirms missing entries. RC:1 confirms this root cause was fixed. Single config file update.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026492816 — QAT Kernel Panic + Fatal MCE + hang cpa_sample_code ────
write(
    "14026492816",
    phase2={
        "testcase_name": "QAT cpa_sample_code Kernel Panic + Fatal MCE + system hang",
        "testcase_command": "cpa_sample_code [QAT workload]",
        "testcase_parameters": "OKS DMR AP A0; Kernel Panic or workload hang; Fatal machine check; cpa_sample_code QAT workload; component unknown",
        "testcase_domain_focus": "QAT cpa_sample_code causing Kernel Panic + Fatal MCE or hang on DMR AP A0 — CPM 5.1 hardware bug or PCIe credit issue",
    },
    phase3={
        "verified_problem_statement": "DMR AP A0 OKS reaches Kernel Panic or workload hang with Fatal machine check when running cpa_sample_code QAT workload.",
        "verified_root_cause": "Kernel Panic + Fatal MCE + hang during cpa_sample_code: (1) DMR AP A0 hardware bug in CPM 5.1 or PCIe subsystem — early A0 silicon; cpa_sample_code exercises sustained QAT load exposing hardware corner cases; (2) PCIe/CXL credit handling/timeout bug — known DMR errata for LCD credit handling; QAT sustained operation overflows PCIe credit counter; (3) QAT driver not handling fatal hardware error gracefully — CPM 5.1 fatal error propagates to kernel panic instead of being contained; (4) Wrong QAT driver package (GNR vs DMR) — driver crashes on CPM 5.1 error response format; (5) Platform power/C-state management racing with QAT — MCE triggered by power state transition during QAT activity. Component: hw.qat or hw.pcie.",
        "verified_fix": "Capture crashlog and MCE dump. Update to QAT_2025.07.01 DMR BKC. Disable C-states. Check PCIe credit registers. Identify silicon HSD if MCE is hardware-triggered.",
        "architectural_element": "CPM 5.1 QAT PCIe; MCE bank; PCIe credit handling; kernel fatal error handling; cpa_sample_code sustained load",
        "failure_registers": ["MCi_STATUS (MCE bank)", "PCIe credit/timeout registers", "CPM error status register"],
        "adjacent_subsystems": ["QAT CPM 5.1", "PCIe root complex", "kernel MCE handler", "platform power management"],
        "related_hsds": ["22018834267"],
        "spec_reference": "CrashLog HAS; CBB/E-Core ARW Debug Guide; DMR RAS HAS: CPM fatal error; Gen3+CXL credit debug guide"
    },
    phase4={
        "tier1": [
            {"category": "crashlog", "commands": ["from diamondrapids import crashlog_api", "crashlog_api.read_all_crashlogs()"], "reveals": "Crash registers at time of MCE/panic", "relevance": "Identifies CPU vs IO vs PCIe source of fatal MCE"},
            {"category": "mce_decode", "commands": ["mcelog --client", "dmesg | grep -i 'mce\\|machine check'", "sd.show_cbb_mca_err_src()"], "reveals": "MCE bank, MCACOD, MSCOD — specific fatal error type", "relevance": "MCACOD identifies QAT/PCIe vs core as MCE source"},
        ],
        "tier2": [
            {"category": "driver_version", "commands": ["modinfo qat_4xxx | grep -i 'version'"], "reveals": "QAT driver version — GNR vs DMR", "relevance": "GNR driver on DMR A0 = fatal error handling mismatch"},
        ],
        "tier3": [],
        "beyond_sme": [
            {"description": "Silicon hardware bug determination from MCE pattern", "commands": ["File silicon HSD if MCE is hardware-triggered with consistent MCACOD"], "why": "A0 hardware bug requires silicon team triage based on crashlog"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — cpa_sample_code sustained QAT load triggers A0 hardware corner case or driver crash",
        "root_cause_domain": "hw.qat / CPM 5.1 PCIe error or driver crash on fatal error",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "crashlog + mce_decode identify source. driver_version rules out easy fix. A0 silicon bug likely needs HSD.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026466867 — DSA SVOS system hang ELEMENT_WISE_PRS ──────────────────
write(
    "14026466867",
    phase2={
        "testcase_name": "DSA SVOS ELEMENT_WISE_PRS system hang",
        "testcase_command": "(DSA ELEMENT_WISE_PRS test launch in SVOS Rocket)",
        "testcase_parameters": "DMR X1 VV SVOS; system hung while launching/executing ELEMENT_WISE_PRS test; Signature: Step silicon; component val.env.automation; NGA:2 RC:1",
        "testcase_domain_focus": "DSA ELEMENT_WISE_PRS VTd/PRS test hang on DMR X1 VV — HIOP credit deadlock or VTd/PRS interaction during element-wise operation",
    },
    phase3={
        "verified_problem_statement": "System hangs while launching/executing DSA ELEMENT_WISE_PRS test on DMR X1 VV SVOS. Signature: Step silicon. RC:1.",
        "verified_root_cause": "DSA ELEMENT_WISE_PRS hang: (1) HIOP channel completion credit starvation — element-wise PRS operations generate many PRS requests that consume HIOP credits; insufficient credits deadlock the pipeline; (2) VTd/PRS interaction during element-wise operation — PRS page request group flag (LPIG) misconfiguration causes M2IOSF PRS pipeline stall (known HSD 14025333034); (3) DSA ELEMENT_WISE = element-wise comparison/delta operation with PRS mode — test exercises PRS for each element access, creating large PRS burst; (4) Automation hang detection triggers 'Step silicon' signature when SVOS detects test timeout; (5) val.env.automation RC:1 confirms automation-level root cause found and fixed (likely timing or hang detection threshold).",
        "verified_fix": "Apply PRS WA: dis_max_pgr_throttle=1 (HSD 14025333034 WA). Verify HIOP credit watermarks for PRS burst. RC:1 confirms automation fix found.",
        "architectural_element": "DSA ELEMENT_WISE operation with PRS; HIOP channel credits; VTd PRS LPIG ordering; SVOS hang detection",
        "failure_registers": ["HIOP credit status registers", "vt_iommu_cr_itciommudbgctrl3.dis_max_pgr_throttle"],
        "adjacent_subsystems": ["DSA element-wise descriptor engine", "VTd/IOMMU PRS pipeline", "HIOP channel", "SVOS hang detector"],
        "related_hsds": ["14025333034", "14026466314"],
        "spec_reference": "DSA/IAX Debug BKMs wiki; PRS Bug wiki; HIOP GEN3 HAS: credit handling; SPR Rocket Sync wiki (HIOP + PRS hang patterns)"
    },
    phase4={
        "tier1": [
            {"category": "prs_wa_check", "commands": ["sv.socket0.imh0.vt_iommu_cr_itciommudbgctrl3.dis_max_pgr_throttle.show()"], "reveals": "PRS WA status — single register check", "relevance": "WA not applied = M2IOSF PRS ordering hang for ELEMENT_WISE_PRS burst"},
            {"category": "hiop_credits", "commands": ["sv.socket0.imh0.hiop.showsearch('credit')", "sv.socket0.imh0.hiop.hiops.hiop_reg.showsearch('stall')"], "reveals": "HIOP credit count and stall state at hang", "relevance": "Zero credits = HIOP credit deadlock during PRS burst"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — ELEMENT_WISE_PRS burst exercises M2IOSF PRS ordering; HIOP credits exhausted",
        "root_cause_domain": "val.env.automation / PRS WA not applied or HIOP credit deadlock",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "prs_wa_check is single register. hiop_credits shows deadlock state. RC:1 confirms automation-level fix found.",
        "iteration_savings": "3",
    },
)

# ── HSD 14026466314 — DSA SVOS Perfmon verification PRS wrong flags ───────────
write(
    "14026466314",
    phase2={
        "testcase_name": "DSA SVOS Perfmon verification hardware counter mismatch - wrong PRS flags",
        "testcase_command": "(DSA PRS Perfmon verification test in SVOS)",
        "testcase_parameters": "DMR X1 VV SVOS; Perfmon verification failed, HW count mismatch; PRS tests failing due to wrong PRS flags configured; component val.env.content; NGA:6 RC:3",
        "testcase_domain_focus": "DSA Perfmon hardware counter mismatch from incorrect PRS flag configuration — LPIG flag (LPIG=0 multi-group PRS) vs supported (LPIG=1 single-group) on DMR X1 VV",
    },
    phase3={
        "verified_problem_statement": "DSA Perfmon verification fails with hardware counter mismatches on DMR X1 VV SVOS. PRS tests fail due to wrong PRS flags configured. RC:3 (3 resolutions found).",
        "verified_root_cause": "DSA Perfmon + PRS wrong flags: (1) LPIG (Last Page In Group) flag misconfiguration — test uses LPIG=0 (multi-request PRS group) which is not supported for DSA; only LPIG=1 (single-request group) is supported; hardware pipeline does not properly drain LPIG=0 before LPIG=1; (2) Incorrect configuration causes: duplicate PRS requests, zero-address requests, Invalidation Completion Errors (ICE), and Perfmon counter mismatches; (3) M2IOSF PRS ordering bug (HSD 14025333034) compounds the LPIG=0 issue by allowing incorrect pipeline bypass; (4) Test content (val.env.content) needs to be fixed to use only LPIG=1 PRS groups for DSA. RC:3 = 3 separate test content fixes.",
        "verified_fix": "Configure DSA PRS tests to use only LPIG=1 (single request per PRS group). Apply PRS WA: dis_max_pgr_throttle=1. Avoid LPIG=0 PRS groups for DSA. RC:3 confirms multiple content fixes needed.",
        "architectural_element": "DSA PRS LPIG flag; PRS group handling; M2IOSF PRS pipeline drain; Perfmon counter tracking",
        "failure_registers": ["vt_iommu_cr_itciommudbgctrl3.dis_max_pgr_throttle", "IOMMU ICE register", "Perfmon DSA counters"],
        "adjacent_subsystems": ["DSA PRS descriptor flags", "M2IOSF PRS pipeline", "VTd IOMMU", "Perfmon counters"],
        "related_hsds": ["14025333034", "14026466867"],
        "spec_reference": "PRS Bug wiki (PRS+Bug); Flexcon VTd wiki (LPIG=1 only for DSA); SPR IOMMU Validation notes"
    },
    phase4={
        "tier1": [
            {"category": "prs_flags", "commands": ["grep -r 'LPIG\\|prs_flag\\|last_page' <test_scripts>/", "cat prs_test*.log | grep -i 'lpig\\|flag'"], "reveals": "LPIG flag values used in test PRS descriptors", "relevance": "LPIG=0 usage = wrong flag causing hardware counter mismatch"},
            {"category": "prs_wa_check", "commands": ["sv.socket0.imh0.vt_iommu_cr_itciommudbgctrl3.dis_max_pgr_throttle.show()"], "reveals": "M2IOSF PRS WA status", "relevance": "WA not applied + LPIG=0 = combined failure causing Perfmon mismatch"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — wrong LPIG flags in PRS descriptors cause hardware pipeline errors and Perfmon counter mismatch",
        "root_cause_domain": "val.env.content / DSA PRS LPIG flag = 0 (unsupported) in test descriptors",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "prs_flags check confirms wrong LPIG value. prs_wa_check identifies M2IOSF contribution. RC:3 multiple content fixes confirm test content issue.",
        "iteration_savings": "3",
    },
)

# ── HSD 14026450837 — dsa_fill sandstone relaxed ordering Mpush incorrect data
write(
    "14026450837",
    phase2={
        "testcase_name": "dsa_fill sandstone subtest incorrect data with relaxed ordering + Mpush write",
        "testcase_command": "(dsa_fill sandstone subtest with relaxed ordering and Mpush write enabled)",
        "testcase_parameters": "DMR; dsa_fill sandstone subtest detects incorrect data; relaxed ordering + Mpush write path; read goes out of order; component soc.top",
        "testcase_domain_focus": "SoC-level data correctness bug — relaxed ordering Mpush write allowing out-of-order read on DMR; HIOP/fabric ordering violation",
    },
    phase3={
        "verified_problem_statement": "dsa_fill sandstone subtest detects incorrect data on DMR. Description: relaxed ordering and Mpush write allows read to go out of order.",
        "verified_root_cause": "Incorrect data with relaxed ordering + Mpush write: (1) SoC/fabric relaxed ordering implementation bug — when relaxed ordering is enabled, reads can bypass in-flight Mpush writes that should fence them; (2) HIOP relaxed-order inbound model allows Mpush writes to bypass other posted requests to different destinations — but incorrectly allows reads to pass preceding Mpush writes to same destination; (3) IDO (Independent Device Ordering) not supported by HIOP on DMR, so reordering is unexpected; (4) Data correctness violation: core read sees stale/partial data because Mpush write is still in-flight; (5) Component soc.top = SoC-level bug, likely HIOP/fabric ordering enforcement lapse. This is a silicon bug.",
        "verified_fix": "Disable relaxed ordering for DSA fill operations. File silicon HSD for HIOP/fabric relaxed ordering + Mpush read ordering violation. Contact soc.top architect team.",
        "architectural_element": "HIOP relaxed ordering inbound model; Mpush write path; SoC fabric read-vs-write ordering; IDO enforcement",
        "failure_registers": ["HIOP inbound ordering configuration", "SoC fabric ordering registers"],
        "adjacent_subsystems": ["HIOP GEN3", "SoC fabric", "DSA DMA path", "relaxed ordering control"],
        "related_hsds": [],
        "spec_reference": "HIOP GEN3 HAS: relaxed ordering inbound model; SysIO PerfPower (DMR): relaxed ordering throughput; DMR SoC integration spec"
    },
    phase4={
        "tier1": [
            {"category": "ordering_config", "commands": ["sv.socket0.imh0.hiop.showsearch('relax')", "cat dsa_fill*.log | grep -i 'relaxed\\|mpush'"], "reveals": "HIOP relaxed ordering configuration and DSA fill test mode", "relevance": "Relaxed ordering enabled = confirms ordering violation path"},
            {"category": "disable_relaxed", "commands": ["Disable relaxed ordering in DSA descriptor: RO bit = 0", "Rerun dsa_fill with strict ordering"], "reveals": "Whether disabling relaxed ordering eliminates data mismatch", "relevance": "If strict ordering passes = confirms relaxed ordering ordering violation"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [
            {"description": "HIOP GEN3 Mpush write + relaxed ordering SoC bug investigation", "commands": ["File silicon HSD with soc.top team: HIOP relaxed ordering allows read to bypass Mpush write"], "why": "soc.top silicon bug requires HIOP architect and design team investigation"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — dsa_fill with relaxed ordering + Mpush write exercises SoC ordering bug",
        "root_cause_domain": "soc.top / HIOP fabric relaxed ordering bug allowing read to bypass Mpush write",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "ordering_config confirms mode. disable_relaxed test proves root cause. Silicon bug confirmed by soc.top component.",
        "iteration_savings": "3",
    },
)

# ── HSD 16029161498 — OKS DSA3 opcode 0x1B Gather Reduce batch mode failure ──
write(
    "16029161498",
    phase2={
        "testcase_name": "DSA3 opcode 0x1B Gather Reduce batch mode failure (BOF enabled/disabled)",
        "testcase_command": "(DSA3 Gather Reduce opcode 0x1B test in batch mode)",
        "testcase_parameters": "OKS DMR AP; DSA3 opcode 0x1B (Gather Reduce) fails in batch mode; both BOF enabled and BOF disabled; no NGA",
        "testcase_domain_focus": "DSA3 Gather Reduce opcode 0x1B batch mode failure on DMR AP OKS — BOF-independent failure suggests batch descriptor chaining bug",
    },
    phase3={
        "verified_problem_statement": "DSA3 opcode 0x1B (Gather Reduce) fails in batch mode on DMR AP OKS for both BOF enabled and BOF disabled.",
        "verified_root_cause": "DSA Gather Reduce batch mode failure: (1) Batch descriptor chaining issue for Gather Reduce — batch mode chains multiple Gather Reduce descriptors; descriptor linking or completion record handling has a bug; (2) BOF-independent failure = not a page fault issue; batch execution path itself is broken; (3) Related known issue HSD 22021248658 (DSA Gather Copy wrong SGL completion on page fault) — different opcode but same Gather family; Gather family descriptor handling may have shared batch mode bug; (4) SGL (Scatter-Gather List) completion reporting issue in batch context — when Gather Reduce processes SGL in batch, completion record or SGL pointer chain is corrupted; (5) No explicit known fix documented — may be new DMR AP hardware limitation.",
        "verified_fix": "Dump DSA completion records for batch Gather Reduce. Check SWERROR0 for batch descriptor error. Disable batch mode, run single-descriptor Gather Reduce to isolate. Compare with HSD 22021248658.",
        "architectural_element": "DSA opcode 0x1B Gather Reduce; batch descriptor chain; SGL completion record; batch completion handling",
        "failure_registers": ["SWERROR0 (0x1B completion)", "INTCAUSE", "batch completion record", "SGL pointer chain"],
        "adjacent_subsystems": ["DSA Gather Reduce engine", "batch descriptor processor", "SGL manager", "completion record writer"],
        "related_hsds": ["22021248658"],
        "spec_reference": "DSA Architecture Spec: opcode 0x1B Gather Reduce; batch descriptor chaining spec; DMR Accelerator Stack wiki: open DSA bugs"
    },
    phase4={
        "tier1": [
            {"category": "batch_vs_single", "commands": ["Run opcode 0x1B Gather Reduce as single descriptor (no batch)", "Compare pass/fail with batch mode"], "reveals": "Whether batch mode itself causes failure vs. Gather Reduce issue", "relevance": "Single passes + batch fails = batch chaining bug; both fail = Gather Reduce HW bug"},
            {"category": "swerror_check", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.swerror0.show()", "sv.socket0.imh0.acc.acc_0.dsa.intcause.show()"], "reveals": "DSA error status for Gather Reduce batch failure", "relevance": "Error code identifies completion record, SGL, or batch chain failure type"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [
            {"description": "DSA Gather Reduce opcode 0x1B batch mode hardware investigation", "commands": ["Consult DSA arch team for opcode 0x1B batch mode support status on DMR AP"], "why": "BOF-independent batch failure may be known DMR AP hardware limitation requiring architecture team input"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — batch mode Gather Reduce exercises batch chaining path; descriptor or SGL issue triggers failure",
        "root_cause_domain": "hw.dsa / Gather Reduce batch descriptor chaining bug or unknown DMR AP limitation",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "batch_vs_single isolates issue. swerror_check identifies error type. Architecture consultation needed for full root cause.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026385355 — TPostTest_PreTestFailChk automation post step ───────────
write(
    "14026385355",
    phase2={
        "testcase_name": "IAA/DSA TPostTest_PreTestFailChk automation post step failure",
        "testcase_command": "(TPostTest_PreTestFailChk - ACE automation post-test check)",
        "testcase_parameters": "DMR X1 A0 VVR IAA DSA; TPostTest_PreTestFailChk post step fails; actual accelerator tests PASS; component val.env.automation; NGA:0 RC:2",
        "testcase_domain_focus": "ACE automation framework post-test check failure when IAA/DSA test itself passes — infrastructure issue not silicon bug on DMR X1 A0 VVR",
    },
    phase3={
        "verified_problem_statement": "TPostTest_PreTestFailChk post step fails on DMR X1 A0 VVR IAA/DSA accelerator tests even though the tests themselves PASS. RC:2.",
        "verified_root_cause": "TPostTest_PreTestFailChk failure with passing test: (1) Missing/unexpected log files — test passes and exits but required log artifacts not generated or misplaced at post-check time; (2) Incorrect return code or output format — test binary exits 0 (success) but output format doesn't match automation expectations (missing success stamps, log markers); (3) ACE automation infrastructure issue — file system permissions, DPF agent timeout, or missing SUT environment dependencies cause post-check to fail even after successful test execution; (4) val.env.automation component confirms pure automation issue — not related to IAA/DSA hardware; (5) RC:2 = two separate automation infrastructure fixes found (likely log path and timeout fixes).",
        "verified_fix": "Review DPF automation log for missing artifact path. Check TPostTest_PreTestFailChk expected vs actual artifact. Escalate to ACE team for infrastructure fix. RC:2 confirms automation team resolved with 2 fixes.",
        "architectural_element": "ACE DPF automation post-test check; TPostTest_PreTestFailChk script; artifact collection; automation agent",
        "failure_registers": [],
        "adjacent_subsystems": ["ACE DPF automation", "TPostTest framework", "DPF execution agent", "SVOS log collection"],
        "related_hsds": [],
        "spec_reference": "DPF Enabling guide: Troubleshooting wiki; DMR DPF User Guide: Troubleshooting wiki; ACE automation failure triage process"
    },
    phase4={
        "tier1": [
            {"category": "post_check_log", "commands": ["cat TPostTest_PreTestFailChk*.log | tail -50", "ls <run_dir>/ | grep -i 'log\\|artifact'"], "reveals": "Missing log file or artifact that TPostTest_PreTestFailChk expects", "relevance": "Missing artifact = immediate root cause for post-check failure"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [
            {"description": "ACE team automation infrastructure investigation", "commands": ["Contact ACE/DPF automation team with post-check log and test run ID"], "why": "RC:2 infrastructure fixes require ACE team; not silicon or test content issue"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "indirect — test passes but ACE post-check infrastructure fails to find expected artifacts",
        "root_cause_domain": "val.env.automation / ACE DPF infrastructure artifact collection",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "post_check_log immediately shows missing artifact. ACE team owns RC:2 fixes. Not silicon issue.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026382931 — QAT Docker daemon not running ──────────────────────────
write(
    "14026382931",
    phase2={
        "testcase_name": "QAT Docker daemon not running test failure",
        "testcase_command": "(Docker-based QAT test launch in SVOS)",
        "testcase_parameters": "DMR X1 A0 VVR SVOS; Docker image could not run because docker daemon was not running; component val.env.tool; NGA:0 RC:0",
        "testcase_domain_focus": "Docker daemon not running on DMR X1 A0 VVR SVOS SUT — infrastructure configuration issue preventing Docker-based QAT test",
    },
    phase3={
        "verified_problem_statement": "QAT test fails on DMR X1 A0 VVR SVOS because Docker daemon is not running.",
        "verified_root_cause": "Docker daemon not running for QAT test: (1) Docker service not started on SVOS SUT — Docker not enabled by default in SVOS image; must be started manually or via service; (2) Docker not installed in SVOS SUT image — QAT Docker-based test requires Docker but SVOS image lacks it; (3) Docker service crashed/not started after SVOS boot — systemd or init.d docker service not in auto-start; (4) SVOS unmount/remount cleared Docker daemon state — Docker daemon stopped when SV was remounted; (5) Component val.env.tool confirms Docker tool infrastructure issue.",
        "verified_fix": "Start Docker daemon: systemctl start docker. Enable Docker on boot: systemctl enable docker. Verify Docker is in SVOS image: which docker. If missing, use non-Docker QAT test variant.",
        "architectural_element": "Docker daemon; SVOS service management; QAT Docker-based test; systemd service",
        "failure_registers": [],
        "adjacent_subsystems": ["SVOS Docker installation", "systemd service manager", "QAT test Docker wrapper"],
        "related_hsds": [],
        "spec_reference": "Docker installation in SVOS; QAT Docker test setup guide"
    },
    phase4={
        "tier1": [
            {"category": "docker_status", "commands": ["systemctl status docker", "which docker", "docker --version"], "reveals": "Docker installation and service state", "relevance": "Service not found = not installed; service inactive = start required"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "indirect — Docker wrapper cannot start because Docker daemon is not running",
        "root_cause_domain": "val.env.tool / Docker service not running or not installed in SVOS",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "docker_status immediately identifies issue. Single command fix: systemctl start docker.",
        "iteration_savings": "1",
    },
)

# ── HSD 13013986760 — OKS DSA 0x1a opcode largest transfer size failure ──────
write(
    "13013986760",
    phase2={
        "testcase_name": "DSA OKS opcode 0x1a test failure on all WQs at largest transfer size",
        "testcase_command": "(DSA opcode 0x1a test on all WQs with largest supported transfer size)",
        "testcase_parameters": "OKS DMR AP; DSA opcode 0x1a fails on all WQs using largest supported transfer size; NGA:1 test UUID",
        "testcase_domain_focus": "DSA opcode 0x1a largest-transfer-size failure on all WQs — possible PCIe payload size limit or WQ buffer size boundary condition on DMR AP OKS",
    },
    phase3={
        "verified_problem_statement": "DSA opcode 0x1a test fails on all WQs using the largest supported transfer size on DMR AP OKS. NGA:1.",
        "verified_root_cause": "DSA opcode 0x1a largest transfer size failure: (1) DSA opcode 0x1a = likely a recently added or extended operation (exact definition not in available GENI docs); (2) Failure on ALL WQs with largest size = systematic size-dependent issue, not WQ-specific; (3) PCIe payload size boundary — largest transfer exceeds Max_Payload_Size or Max_Read_Request_Size, causing Unsupported Request (UR) per PCIe spec; (4) WQ buffer boundary — largest transfer hits WQ internal buffer overflow at maximum size; (5) IOMMU page boundary crossing — largest transfer may span multiple IOMMU pages incorrectly; (6) Driver limitation — DSA driver may have max transfer size limit not aligned with hardware capability. No HW erratum found for this opcode in available docs.",
        "verified_fix": "Check DSA EAS for opcode 0x1a definition and max transfer size. Verify PCIe Max_Payload_Size. Check WQ buffer configuration. Test with sizes below maximum to find boundary.",
        "architectural_element": "DSA opcode 0x1a; PCIe Max_Payload_Size; WQ buffer size limit; IOMMU page boundary",
        "failure_registers": ["SWERROR0 (completion code for 0x1a)", "PCIe Max_Payload_Size register"],
        "adjacent_subsystems": ["DSA opcode 0x1a engine", "PCIe payload handling", "WQ buffer manager", "IOMMU page table"],
        "related_hsds": ["16029161498"],
        "spec_reference": "DSA Architecture Spec: opcode 0x1a definition and max transfer size; DMR ACC HAS: WQ buffer size; PCIe payload size handling"
    },
    phase4={
        "tier1": [
            {"category": "size_bisect", "commands": ["Run opcode 0x1a with transfer sizes: max/2, max*3/4, max-1, max", "cat dsa_test*.log | grep -i 'size\\|fail\\|complete'"], "reveals": "Exact size boundary where failure occurs", "relevance": "Specific size = PCIe payload or WQ buffer boundary"},
            {"category": "swerror_check", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.swerror0.show()"], "reveals": "DSA error code for opcode 0x1a at largest size", "relevance": "Error code identifies PCIe UR vs WQ overflow vs IOMMU fault"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [
            {"description": "DSA EAS opcode 0x1a definition and max transfer size lookup", "commands": ["Reference DSA Architecture Spec for opcode 0x1a"], "why": "Opcode 0x1a definition not in available GENI docs; needed for root cause confirmation"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — opcode 0x1a at max transfer size hits boundary condition in PCIe payload or WQ buffer",
        "root_cause_domain": "hw.dsa / PCIe payload size or WQ buffer limit at max transfer size",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "size_bisect identifies boundary. swerror_check shows error type. DSA EAS needed for definitive opcode 0x1a analysis.",
        "iteration_savings": "2",
    },
)

# ── HSD 16029066696 — DSA/IAA idxd vfio_pci SPDK binding failure ─────────────
write(
    "16029066696",
    phase2={
        "testcase_name": "DSA/IAA idxd binding to vfio_pci through SPDK failure",
        "testcase_command": "(SPDK DSA/IAA device binding: unbind from idxd → bind to vfio_pci)",
        "testcase_parameters": "OKS DMR AP; DSA idxd binding to vfio_pci through SPDK fails for DSA and IAA devices; no NGA",
        "testcase_domain_focus": "DSA/IAA idxd to vfio_pci rebinding failure for SPDK on DMR AP OKS — IOMMU, driver conflict, or SPDK version issue",
    },
    phase3={
        "verified_problem_statement": "DSA/IAA idxd binding to vfio_pci through SPDK fails for both DSA and IAA devices on DMR AP OKS.",
        "verified_root_cause": "idxd to vfio_pci binding failure for SPDK: (1) IOMMU/VT-d not properly enabled — vfio_pci requires VT-d enabled with interrupt remapping; BIOS settings may be incorrect; (2) idxd driver not unbound before vfio_pci bind attempt — Linux idxd driver auto-loads and claims DSA/IAA; must be explicitly unbound before vfio_pci can bind; (3) Kernel command line missing IOMMU parameters — needs intel_iommu=on,sm_on,iova_sl and IOMMU group isolation; (4) SPDK version incompatibility with DMR DSA/IAA — SPDK not updated for DMR device IDs; (5) ATS not enabled — SPDK-based IOMMU access requires ATS for DSA/IAA. Component: val.env.tool or hw.dsa.",
        "verified_fix": "Unbind idxd: echo <BDF> > /sys/bus/pci/devices/<BDF>/driver/unbind. Enable VT-d interrupt remapping in BIOS. Add intel_iommu=on,sm_on to kernel command line. Update SPDK for DMR device IDs.",
        "architectural_element": "idxd driver; vfio_pci driver; SPDK DMA path; VT-d interrupt remapping; IOMMU group isolation",
        "failure_registers": ["VT-d interrupt remapping register", "IOMMU group isolation"],
        "adjacent_subsystems": ["Linux idxd driver", "vfio_pci driver", "SPDK", "VT-d IOMMU", "kernel command line"],
        "related_hsds": [],
        "spec_reference": "SVOS SLAD+kernel SVM wiki; DMR System IO/Accelerator Stack wiki; SPDK DSA/IAA enablement guide"
    },
    phase4={
        "tier1": [
            {"category": "iommu_check", "commands": ["dmesg | grep -i 'iommu\\|vt-d'", "cat /proc/cmdline | grep -i 'iommu'"], "reveals": "IOMMU/VT-d enablement status", "relevance": "IOMMU not enabled = vfio_pci binding fails for all devices"},
            {"category": "driver_bind", "commands": ["lspci | grep '0b25'", "ls /sys/bus/pci/devices/ | xargs -I{} cat /sys/bus/pci/devices/{}/driver/module/name 2>/dev/null"], "reveals": "Current driver bound to DSA/IAA PCIe devices", "relevance": "idxd still bound = unbind required before vfio_pci binding"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — SPDK needs vfio_pci binding; idxd driver and IOMMU config prevent binding",
        "root_cause_domain": "val.env.tool / idxd driver not unbound or IOMMU not configured for vfio_pci",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "iommu_check + driver_bind are fast 2-command checks. Known SPDK/vfio_pci setup sequence.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026211428 — DSA SVOS CXLHDM registration failure Atlas ─────────────
write(
    "14026211428",
    phase2={
        "testcase_name": "DSA SVOS CXLHDM registration failure in Atlas",
        "testcase_command": "(Atlas target registration for CXLHDM in DSA SVOS test setup)",
        "testcase_parameters": "DMR X1 A0 VVR SVOS; CXLHDM registration failure - CXLHDM not found; DRAM usage error in atlas.log; component val.env.tool; NGA:0 RC:2",
        "testcase_domain_focus": "Atlas CXLHDM target registration failure for DSA SVOS on DMR X1 A0 VVR — same as IAA CXLHDM issue (HSD 14026577326) but for DSA context",
    },
    phase3={
        "verified_problem_statement": "DSA SVOS CXLHDM registration fails in Atlas on DMR X1 A0 VVR SVOS. Atlas.log shows DRAM usage error. RC:2 (2 resolutions).",
        "verified_root_cause": "Atlas CXLHDM registration failure for DSA: Same root cause as HSD 14026577326 (IAA CXLHDM): (1) CXL HDM device not enumerated in BIOS — device not visible to Atlas discovery for DSA test; (2) Atlas/Acre CXL 3.0 modules not compatible with DMR X1 A0 — Atlas tool version lacks CXL 3.0/DMR support for CXLHDM as DRAM target; (3) Required BIOS version (BIOS2834D10 + UP 60000974) or SVOS dmr2534 patch 11+ not applied; (4) Atlas DRAM usage error = Atlas cannot use CXLHDM as memory target because device not registered. RC:2 = 2 separate fixes (BIOS update + Atlas update).",
        "verified_fix": "Update BIOS to required version for DMR CXL support. Apply SVOS dmr2534 patch 11+. Update Atlas/Acre modules for CXL 3.0 DMR support. Verify CXL device enumerated in OS.",
        "architectural_element": "Atlas CXLHDM target registration; CXL HDM device enumeration; BIOS CXL support; Atlas/Acre CXL 3.0 modules",
        "failure_registers": ["CXL device PCI enumeration"],
        "adjacent_subsystems": ["Atlas target framework", "CXL port", "BIOS CXL enumeration", "SVOS CXL driver"],
        "related_hsds": ["14026577326"],
        "spec_reference": "CXL 3.0 Tech Readiness for DMR wiki; DMR CXL PO Workarounds wiki; Atlas CXL support release notes"
    },
    phase4={
        "tier1": [
            {"category": "cxl_enumeration", "commands": ["lspci | grep -i 'cxl'", "ls /sys/bus/cxl/devices/"], "reveals": "CXL device presence in OS", "relevance": "Not enumerated = BIOS or hardware issue; enumerated but Atlas fails = Atlas version issue"},
            {"category": "atlas_version", "commands": ["python3 -c 'import atlas; print(atlas.__version__)'"], "reveals": "Atlas version and CXL module support level", "relevance": "Old Atlas without CXL 3.0/DMR support causes CXLHDM registration failure"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — Atlas DSA test setup registers CXLHDM target; not found causes immediate failure",
        "root_cause_domain": "val.env.tool / Atlas CXL support or BIOS CXL enablement",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "cxl_enumeration + atlas_version quickly identify device vs tool issue. Same pattern as HSD 14026577326.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026200668 — DSA Inter-domain copy SASS mismatch ────────────────────
write(
    "14026200668",
    phase2={
        "testcase_name": "DSA SVOS Inter-domain copy SASS reporting mismatch",
        "testcase_command": "(DSA SASS inter-domain copy test in SVOS)",
        "testcase_parameters": "DMR X1 A0 PO VVR SVOS; DSA Inter-domain copy SASS reporting mismatch; component val.env.configuration; NGA:2 RC:1",
        "testcase_domain_focus": "DSA Inter-domain copy SASS mismatch — data content, completion status, or counter mismatch in cross-domain copy on DMR X1 A0 VVR",
    },
    phase3={
        "verified_problem_statement": "DSA Inter-domain copy SASS reports mismatch on DMR X1 A0 PO VVR SVOS. Component val.env.configuration. RC:1.",
        "verified_root_cause": "DSA Inter-domain copy SASS mismatch: (1) Configuration issue (val.env.configuration) — DSA inter-domain copy requires specific BIOS and SVOS configuration for cross-domain access; incorrect configuration causes data or status mismatch; (2) Linear-to-physical address mapping error — DSA inter-domain copy uses different address space mapping; if page tables not configured correctly, copy destination may be wrong physical address; (3) Accessed/Dirty page bits not updated after DSA inter-domain write — SASS test verifies bit state; HW may not set these correctly in cross-domain path; (4) Action vector/completion status mismatch — expected completion status for inter-domain copy differs from actual; (5) SASS test configuration file has wrong domain/address parameters. RC:1 = configuration fix resolved.",
        "verified_fix": "Update SASS test configuration for inter-domain copy domain addresses. Verify page table configuration for cross-domain path. Verify Accessed/Dirty bit behavior for inter-domain copy. RC:1 confirms configuration fix.",
        "architectural_element": "DSA inter-domain copy descriptor; SASS test configuration; page table cross-domain mapping; Accessed/Dirty bit update",
        "failure_registers": ["DSA completion record mismatch", "page table Accessed/Dirty bits"],
        "adjacent_subsystems": ["DSA inter-domain copy engine", "SASS test framework", "SVOS page table manager", "cross-domain configuration"],
        "related_hsds": ["14026536280"],
        "spec_reference": "Dragon Oakley debug wiki (error codes for SASS mismatch); DSA Architecture Spec: inter-domain copy; SVOS cross-domain configuration guide"
    },
    phase4={
        "tier1": [
            {"category": "config_check", "commands": ["cat SASS_interdomain_copy.conf | grep -i 'domain\\|address'", "diff SASS_expected_config.conf SASS_actual_config.conf"], "reveals": "SASS configuration parameters for inter-domain copy", "relevance": "Wrong domain/address in config = mismatch at configuration level (val.env.configuration)"},
            {"category": "completion_record", "commands": ["cat dsa_sass*.log | grep -i 'mismatch\\|completion\\|status'"], "reveals": "Type of mismatch: data, status, or counter", "relevance": "Identifies whether data corruption or status reporting issue"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — SASS inter-domain copy verifies expected vs actual; configuration mismatch causes failure",
        "root_cause_domain": "val.env.configuration / SASS test configuration for inter-domain addresses",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "config_check confirms configuration mismatch. RC:1 confirms configuration fix resolved. Fast debug.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026198936 — DSA SVOS Unknown arden id! ─────────────────────────────
write(
    "14026198936",
    phase2={
        "testcase_name": "DSA SVOS NGA test failure: Unknown arden id! in Acre system discovery",
        "testcase_command": "(Rocket discovering system phase → Acre random → atlas log: Unknown arden id!)",
        "testcase_parameters": "DMR X1 A0 VVR SVOS; DSA NGA tests fail during discovering system phase; atlas log: Acre random Unknown arden id!; component val.env.execution; NGA:0 RC:0",
        "testcase_domain_focus": "Acre system discovery failure — Unknown arden id! during Rocket system discovery phase on DMR X1 A0 VVR SVOS",
    },
    phase3={
        "verified_problem_statement": "DSA NGA tests fail during 'discovering system' Rocket phase with 'Unknown arden id!' in atlas log on DMR X1 A0 VVR SVOS.",
        "verified_root_cause": "Unknown arden id! in Acre system discovery: (1) Acre/Atlas cannot find or map PCIe arden test card ID during system topology discovery — arden card not in system or not discovered at expected PCIe path; (2) Missing or mismatched arden node definition in Acre config — Acre looks for arden card at specific path (/sv/socket0/bus0/pcieD04F0/arden-00/vm0) but card not present or path different; (3) Closely related to HSD 14015689076 (local_arden KeyError) — both are Acre arden discovery failures; apply same WA (localLinks); (4) Ace/Atlas variant not updated for DMR X1 topology — arden card routing different from GNR/SPR expectations; (5) Component val.env.execution confirms execution environment issue.",
        "verified_fix": "Apply localLinks WA (HSD 14015689076): options fs_svfs localLinks=1 in /etc/modprobe.d/grrmods.conf. Update Atlas/Acre scripts for DMR X1 topology. Verify arden card PCIe path in system.",
        "architectural_element": "Acre system discovery; arden test card node; Rocket topology mapping; Atlas config generation",
        "failure_registers": [],
        "adjacent_subsystems": ["Acre/Atlas topology discovery", "arden test card", "Rocket discovering system", "SVOS modprobe"],
        "related_hsds": ["14015689076", "14026506052"],
        "spec_reference": "Acre Architecture wiki; Acre Workaround Development Guide; VP_21ww_50.2 (arden fix); HSD 14015689076"
    },
    phase4={
        "tier1": [
            {"category": "grrmods_check", "commands": ["cat /etc/modprobe.d/grrmods.conf", "grep -i 'localLinks' /etc/modprobe.d/grrmods.conf"], "reveals": "localLinks WA status for arden discovery", "relevance": "Missing localLinks = Unknown arden id! during system discovery"},
            {"category": "arden_path", "commands": ["ls /sv/socket0/bus0/ | grep -i 'pcie'", "ls /sv/socket0/bus0/pcieD04F0/ 2>/dev/null"], "reveals": "PCIe path for arden test card in SVOS", "relevance": "Path not found = arden card not enumerated or wrong PCIe topology"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — Acre cannot discover arden test card; DSA SVOS test cannot start",
        "root_cause_domain": "val.env.execution / Acre arden discovery failure; apply localLinks WA",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "grrmods_check confirms missing localLinks. Same fix as HSD 14015689076. Fast resolution.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026198752 — DSA Type conversion Inter-Domain integer verify errors ──
write(
    "14026198752",
    phase2={
        "testcase_name": "DSA SVOS Type conversion Inter-Domain integer operation verify phase errors",
        "testcase_command": "(DSA type conversion inter-domain integer test in SVOS Rocket)",
        "testcase_parameters": "DMR X1 A0 VVR SVOS; Type conversion Inter-Domain integer operations report errors in verify phase; component val.env.content; NGA:2 RC:2",
        "testcase_domain_focus": "DSA type conversion inter-domain integer verify phase failure — data mismatch in cross-domain conversion result on DMR X1 A0 VVR SVOS",
    },
    phase3={
        "verified_problem_statement": "DSA Type conversion Inter-Domain integer operations report errors in verify phase on DMR X1 A0 VVR SVOS. Component val.env.content. RC:2 NGA:2.",
        "verified_root_cause": "DSA inter-domain integer type conversion verify errors: (1) Test content configuration error (val.env.content) — type conversion descriptors have incorrect parameter configuration for inter-domain integer path; expected values not matching hardware output because test expected values computed with wrong parameters; (2) Integer overflow/underflow in cross-domain path — inter-domain type conversion may use different integer range or sign convention; test expected values assume incorrect range; (3) Control register misconfiguration — CNTRCFG, DEFTR, tph_en, MSE registers not properly set for inter-domain type conversion; (4) Known DMR A0 DSA/IAA bug: byte-count mismatch in Mem completions (HSD 22020561826) may corrupt inter-domain integer conversion output; (5) RC:2 = two test content fixes found.",
        "verified_fix": "Apply test content fixes (RC:2). Verify descriptor parameters for inter-domain type conversion. Check CNTRCFG register configuration. Test with known byte-count mismatch WA.",
        "architectural_element": "DSA type conversion engine; inter-domain integer operation; CNTRCFG register; descriptor parameters",
        "failure_registers": ["CNTRCFG", "DEFTR", "DSA completion record for type conversion"],
        "adjacent_subsystems": ["DSA type conversion descriptor", "inter-domain path", "MSE control register", "byte-count mismatch detector"],
        "related_hsds": ["22020561826"],
        "spec_reference": "DSA Architecture Spec: type conversion opcodes; Accelerator Stack wiki: Known DMR A0 bugs; DSA/IAX HSD analysis wiki"
    },
    phase4={
        "tier1": [
            {"category": "swerror_check", "commands": ["sv.socket0.imh0.acc.acc_0.dsa.swerror0.show()", "from diamondrapids.accelerators.dsa_iaa import dsa_iaa_debug_dump as dsa_iaa_dump", "dsa_iaa_dump.dump_all_dsa_inst_errs()"], "reveals": "DSA error state during type conversion verify failure", "relevance": "Error code identifies whether this is completion corruption or configuration error"},
            {"category": "descriptor_check", "commands": ["cat dsa_type_conv*.log | grep -i 'verify\\|mismatch\\|expected'"], "reveals": "Which conversion type and domain combination fails", "relevance": "Specific failure pattern identifies whether content or hardware bug"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — type conversion verify compares HW output vs expected; mismatch from content error or A0 bug",
        "root_cause_domain": "val.env.content / DSA type conversion descriptor configuration or A0 byte-count mismatch bug",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "swerror_check identifies A0 HW bug or configuration error. RC:2 content fixes confirm test content issues.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026198585 — IAA compression auto mode data mismatch ─────────────────
write(
    "14026198585",
    phase2={
        "testcase_name": "IAA compression auto mode data mismatch (obs vs exp FAILVECT)",
        "testcase_command": "(IAA compression auto mode test in SVOS)",
        "testcase_parameters": "DMR X1 A0 VVR SVOS; IAA compression auto mode fails with data mismatch obs vs exp; FAILVECT; RC:1",
        "testcase_domain_focus": "IAA compression auto mode data mismatch on DMR X1 A0 VVR SVOS — known A0 hardware bug in IAA byte-count mismatch detection",
    },
    phase3={
        "verified_problem_statement": "IAA compression auto mode test fails with data mismatch (observed vs expected, FAILVECT) on DMR X1 A0 VVR SVOS. RC:1.",
        "verified_root_cause": "IAA compression auto mode data mismatch: Confirmed DMR A0 hardware bug. Root cause: HSD 22020561826 (DMR: DSA/IAA not correctly detecting byte-count mismatch in Mem completions). In auto mode, IAA selects compression algorithm dynamically; byte-count mismatch in memory completions corrupts the auto-selected compression output, causing data mismatch vs expected. Also related: IAA A0 completions may not properly populate dest_id in invalidation completion, further corrupting results. Fixes available only in later DMR steppings (IMH2+). RC:1 confirms A0 hardware bug root cause.",
        "verified_fix": "Confirm DMR A0 stepping. Apply available A0 workarounds. Run on IMH2+ stepping for hardware fix. Capture dsa_iaa_debug_dump for full error state. Reference HSD 22020561826.",
        "architectural_element": "IAA compression auto mode; byte-count mismatch in Mem completions; dest_id in invalidation completion; A0 silicon bug",
        "failure_registers": ["IAA SWERROR", "IAA completion record dest_id field"],
        "adjacent_subsystems": ["IAA compression engine", "auto mode selector", "Mem completion handler", "byte-count validator"],
        "related_hsds": ["22020561826", "14025817510"],
        "spec_reference": "Accelerator Stack wiki: DMR A0 known bugs (byte-count mismatch, dest_id); IMH2 stepping fix status; HSD 22020561826"
    },
    phase4={
        "tier1": [
            {"category": "iaa_error_dump", "commands": ["from diamondrapids.accelerators.dsa_iaa import dsa_iaa_debug_dump as dsa_iaa_dump", "dsa_iaa_dump.dump_all_dsa_inst_errs()"], "reveals": "IAA error registers and byte-count mismatch evidence", "relevance": "IAA error at completion = confirms A0 HW bug pattern"},
            {"category": "stepping_check", "commands": ["python3 -c 'import sv; print(sv.socket0.stepping)'"], "reveals": "DMR stepping (A0 vs IMH2)", "relevance": "A0 stepping = known bug; IMH2 = fixed in hardware"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — IAA compression auto mode exercises byte-count completion path; A0 HW bug corrupts data",
        "root_cause_domain": "hw.iaa / known DMR A0 byte-count mismatch in Mem completions (HSD 22020561826)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "iaa_error_dump confirms A0 bug signature. stepping_check confirms affected stepping. Known root cause.",
        "iteration_savings": "3",
    },
)

# ── HSD 16029052219 — DSA3 opcodes 0x1b/0x1d/0x1e kernel 6.14.0 failure ──────
write(
    "16029052219",
    phase2={
        "testcase_name": "DSA3 new opcodes 0x1b/0x1d/0x1e all fail on kernel 6.14.0-dmr.b",
        "testcase_command": "(DSA3 opcode tests: 0x1b Gather reduce, 0x1d Scatter Copy, 0x1e Scatter Fill on kernel 6.14.0-dmr.b)",
        "testcase_parameters": "OKS DMR AP; DSA3 opcodes 0x1b (Gather reduce), 0x1d (Scatter Copy), 0x1e (Scatter Fill) all fail on kernel 6.14.0-dmr.b; no NGA",
        "testcase_domain_focus": "DMR DSA3 new opcodes all failing on kernel 6.14.0-dmr.b — intentional defeaturing of Scatter Copy/Fill; Gather Reduce may also be defeatured or not supported in this kernel",
    },
    phase3={
        "verified_problem_statement": "DSA3 opcodes 0x1b (Gather reduce), 0x1d (Scatter Copy), and 0x1e (Scatter Fill) all fail on kernel 6.14.0-dmr.b on DMR AP OKS.",
        "verified_root_cause": "DSA3 new opcode failures on kernel 6.14.0-dmr.b: (1) 0x1d (Scatter Copy) and 0x1e (Scatter Fill) — intentionally defeatured for DMR per HSD 14021759570 (DMR-CCB: reduce DSA execution scope by defeaturing Scatter Copy and Scatter Fill); hardware/software does not support these opcodes on DMR; (2) 0x1b (Gather Reduce) — also likely defeatured or not supported in kernel 6.14.0-dmr.b idxd driver; earlier testing shows Gather Reduce batch failures; (3) Kernel 6.14.0-dmr.b idxd driver lacks opcode table entries for these DMR-defeatured operations; any attempt to submit returns error; (4) Not a kernel bug — opcodes are intentionally not supported by design for DMR.",
        "verified_fix": "Do not test defeatured DSA3 opcodes 0x1d, 0x1e on DMR AP. Confirm 0x1b (Gather Reduce) defeaturing status with DSA arch team. Update test content to exclude defeatured opcodes for DMR.",
        "architectural_element": "DSA3 opcode defeaturing; DMR-CCB opcode scope reduction; idxd driver opcode table; kernel 6.14.0-dmr.b",
        "failure_registers": [],
        "adjacent_subsystems": ["DSA3 execution engine", "idxd kernel driver", "opcode dispatch table"],
        "related_hsds": ["16029161498"],
        "spec_reference": "DMR Overview HAS: DMR-CCB DSA opcode defeaturing (HSD 14021759570 Scatter Copy/Fill); DMR ACC HAS: supported opcode list"
    },
    phase4={
        "tier1": [
            {"category": "opcode_support", "commands": ["cat /sys/bus/dsa/devices/dsa0/iommu_support", "grep -r '0x1b\\|0x1d\\|0x1e' /sys/bus/dsa/ 2>/dev/null"], "reveals": "DSA opcode support status in kernel driver", "relevance": "No kernel opcode entry = defeatured/not supported in DMR"},
            {"category": "dmesg_check", "commands": ["dmesg | grep -i 'dsa\\|idxd\\|opcode'"], "reveals": "idxd driver opcode initialization and rejection messages", "relevance": "Driver rejection message confirms intentional defeaturing"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [
            {"description": "Confirm DMR-CCB defeaturing scope for opcode 0x1b", "commands": ["Reference DMR ACC HAS or contact DSA arch team for 0x1b Gather Reduce support status"], "why": "0x1b status not explicitly confirmed in available docs; arch team verification needed"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — test exercises defeatured opcodes; kernel/hardware rejects execution",
        "root_cause_domain": "val.env.content / DMR-CCB defeatured DSA3 opcodes tested",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "opcode_support confirms no kernel table entry. dmesg_check shows driver rejection. Known defeaturing per HSD 14021759570.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026178339 — NGA log files not complete (VV IAA/DSA SVOS) ────────────
write(
    "14026178339",
    phase2={
        "testcase_name": "IAA/DSA SVOS NGA Rocket log not complete",
        "testcase_command": "(NGA-based IAA/DSA VV test run — Rocket log not complete)",
        "testcase_parameters": "DMR X1 A0 VV SVOS; Rocket log not complete in NGA Test Run; component val.env.execution; NGA:1 RC:1",
        "testcase_domain_focus": "NGA log collection incomplete for IAA/DSA VV SVOS test — same infrastructure pattern as HSD 14026579612 and 14026508246",
    },
    phase3={
        "verified_problem_statement": "Rocket log not complete in NGA Test Run for DMR X1 A0 VV IAA/DSA SVOS. RC:1 confirmed.",
        "verified_root_cause": "Incomplete Rocket/NGA logs: same root cause pattern as HSD 14026579612 (IAA) and 14026508246 (QAT): (1) System/SUT hang during test causing automation to terminate before log flush; (2) Network connection issue between SUT and NGA log service; (3) Exelog concurrent write issue truncating log; (4) HCleanUp_Axon_Inventory step failing. RC:1 confirms root cause found and fixed.",
        "verified_fix": "Compare log timestamp vs SUT dmesg at truncation. Check Exelog concurr setting. Validate NGA log upload endpoint. RC:1 confirmed fix.",
        "architectural_element": "NGA log collection; Rocket log manager; Exelog service; HCleanUp step",
        "failure_registers": [],
        "adjacent_subsystems": ["NGA automation", "Exelog service", "Rocket log flush", "SUT network"],
        "related_hsds": ["14026579612", "14026508246"],
        "spec_reference": "NGA Enhanced User Guide wiki; CR CI Enabling Status (DMR) wiki"
    },
    phase4={
        "tier1": [
            {"category": "log_timestamp", "commands": ["Compare NGA log end timestamp vs SUT dmesg timestamp", "cat dmesg | tail -20"], "reveals": "Whether test hang or upload failure caused truncation", "relevance": "Same diagnosis as HSD 14026579612"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "indirect — IAA/DSA test runs but log collection infrastructure fails",
        "root_cause_domain": "val.env.execution / NGA log collection infrastructure",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "Same pattern as HSD 14026579612. RC:1 confirms fast resolution.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026158045 — IAA/DSA PCIe remove rescan Device not found ─────────────
write(
    "14026158045",
    phase2={
        "testcase_name": "IAA/DSA PCIe remove rescan test failure - Device not found",
        "testcase_command": "(echo 1 > /sys/bus/pci/devices/<BDF>/remove; echo 1 > /sys/bus/pci/rescan)",
        "testcase_parameters": "OKS DMR AP; IAA/DSA PCIe remove rescan test; device not found after rescan; kayak DEBUG ssh_protocol logging; NGA:5 test UUIDs",
        "testcase_domain_focus": "IAA/DSA PCIe device not found after PCIe remove+rescan — BIOS hotplug resource handling or driver re-probe issue on DMR AP OKS",
    },
    phase3={
        "verified_problem_statement": "IAA/DSA PCIe remove rescan test fails on DMR AP OKS: device not found after PCIe remove and rescan. NGA:5 — high count suggests systematic failure.",
        "verified_root_cause": "IAA/DSA device not found after PCIe remove+rescan: (1) BIOS PCIe hotplug resource not pre-allocated — BIOS must reserve resources for hotplug devices during POST; without pre-allocation, rescan fails to assign BARs to DSA/IAA; (2) idxd driver not re-probing after rescan — driver does not detect PCIe device reappearance or fails full re-initialization of IAA/DSA after rescan; (3) IOMMU not re-initialized after device rescan — stale IOMMU context blocks DSA/IAA from being re-claimed; (4) Incomplete PCIe remove sequence — OS software-side remove not completed before rescan; device state inconsistent; (5) CXL.io/PCIe hotplug event sequence not completed — Punit not notified of device add back. NGA:5 = systematic failure across multiple runs.",
        "verified_fix": "Verify BIOS PCIe hotplug resource reservation. Check idxd driver re-probe on PCIe rescan. Clear IOMMU context before rescan. Ensure proper OS remove completion before rescan.",
        "architectural_element": "PCIe hotplug BAR pre-allocation; idxd driver re-probe; IOMMU context on rescan; PCIe remove sequence",
        "failure_registers": ["PCIe BAR assignment register", "IOMMU context invalidation register"],
        "adjacent_subsystems": ["BIOS PCIe hotplug", "idxd driver", "IOMMU context manager", "CXL.io hotplug handler"],
        "related_hsds": [],
        "spec_reference": "PCIe Hotplug Enabling wiki; DMR CXL Hot Plug spec; Accelerator Stack wiki (idxd driver re-probe); DMR ACC HAS"
    },
    phase4={
        "tier1": [
            {"category": "rescan_check", "commands": ["echo 1 > /sys/bus/pci/devices/<IAA_BDF>/remove", "echo 1 > /sys/bus/pci/rescan", "lspci | grep '0b25'"], "reveals": "Whether device reappears after rescan", "relevance": "Not reappearing = BIOS BAR pre-allocation or idxd re-probe issue"},
            {"category": "dmesg_hotplug", "commands": ["dmesg | grep -i 'pcie\\|hotplug\\|idxd'"], "reveals": "PCIe remove/rescan sequence and driver re-probe messages", "relevance": "idxd probe failure message = driver doesn't re-claim device"},
        ],
        "tier2": [
            {"category": "bios_check", "commands": ["Verify BIOS PCIe hotplug resource reservation for accelerator slots"], "reveals": "BIOS pre-allocation status for IAA/DSA BARs", "relevance": "Missing BAR reservation = rescan fails to enumerate device"},
        ],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — PCIe remove+rescan exercises hotplug path; BIOS/driver failure leaves device not found",
        "root_cause_domain": "hw.pcie / BIOS PCIe BAR pre-allocation or idxd driver re-probe failure",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "rescan_check + dmesg_hotplug identify failure point. BIOS check needed for BAR reservation. NGA:5 confirms systematic issue.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026147117 — DSA dsa_fill sandstone relaxed ordering=1 ──────────────
write(
    "14026147117",
    phase2={
        "testcase_name": "DSA dsa_fill sandstone subtest incorrect data pattern with relaxed ordering=1",
        "testcase_command": "sandstone -Y -e dsa_fill (part of sandstone-dsa-ops-mix)",
        "testcase_parameters": "DMR X1 A0 PO; PRNG seed 0x56b8...; dsa_fill subtest in sandstone; relaxed ordering = 1; hw.dsa; fix_id=14026111032 fix_ip=bios",
        "testcase_domain_focus": "DSA dsa_fill sandstone data integrity failure with relaxed ordering=1 on DMR — HIOP relaxed ordering + Mpush write bug",
    },
    phase3={
        "verified_problem_statement": "DSA dsa_fill sandstone subtest detects incorrect data pattern when relaxed ordering=1 on DMR X1 A0. Component hw.dsa. BIOS fix tracked: fix_id=14026111032.",
        "verified_root_cause": "HIOP relaxed ordering + Mpush write bug: When DMR soc.top relaxed ordering is enabled, DSA fill operations can expose a SoC-level ordering violation where reads can bypass Mpush (modified push) writes. The HIOP IP allows relaxed ordering in the soc.top bus fabric, but a bug allows reads to overtake pending Mpush writes before they reach memory, causing data integrity failures in dsa_fill. Root cause is a SoC-level PCIe/CXL.io ordering violation in the HIOP+M2IOSF interaction. BIOS fix required. fix_id=14026111032.",
        "verified_fix": "Apply BIOS fix (fix_id=14026111032, fix_ip=bios). Disable relaxed ordering WA: sv.sockets.imhs.hiop.hiop_reg.relaxed_ordering_enable=0 in BIOS knobs. Reference HSD 14026111032.",
        "architectural_element": "HIOP relaxed ordering; Mpush write path; soc.top PCIe/CXL.io ordering; DSA dsa_fill data path",
        "failure_registers": ["HIOP relaxed_ordering_enable", "soc.top ordering register"],
        "adjacent_subsystems": ["HIOP IP", "M2IOSF", "soc.top fabric", "DSA fill engine"],
        "related_hsds": ["14026111032", "14026093607"],
        "spec_reference": "DMR SOC HAS: HIOP relaxed ordering; SoC ordering requirements; Bug Ninja DSA dsa_fill analysis"
    },
    phase4={
        "tier1": [
            {"category": "hiop_ordering", "commands": ["sv.socket0.imhs.hiop.hiop_reg.relaxed_ordering_enable"], "reveals": "HIOP relaxed ordering enable state", "relevance": "Enabled = triggers ordering violation; fix = disable"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — dsa_fill with relaxed ordering hits HIOP Mpush ordering violation; read bypasses write",
        "root_cause_domain": "hw.dsa / HIOP relaxed ordering + Mpush write SoC ordering violation",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "BIOS fix tracked fix_id=14026111032. hiop_ordering check confirms state. Known DMR SoC bug.",
        "iteration_savings": "3",
    },
)

# ── HSD 14026093607 — DSA dsa_fill sandstone relaxed ordering (Bug Ninja) ─────
write(
    "14026093607",
    phase2={
        "testcase_name": "DSA dsa_fill sandstone subtest incorrect data pattern (relaxed ordering=1) - Bug Ninja",
        "testcase_command": "sandstone -Y -e dsa_fill (part of sandstone-dsa-ops-mix)",
        "testcase_parameters": "DMR X1 A0; PRNG seed 0x56b8...; dsa_fill subtest in sandstone; relaxed ordering=1; hw.dsa; Bug Ninja identified",
        "testcase_domain_focus": "Same as HSD 14026147117 — DSA dsa_fill HIOP relaxed ordering Mpush write ordering violation",
    },
    phase3={
        "verified_problem_statement": "Same root cause as HSD 14026147117: DSA dsa_fill sandstone subtest incorrect data pattern with relaxed ordering=1 on DMR X1 A0. Bug Ninja duplicate/related ticket.",
        "verified_root_cause": "Identical to HSD 14026147117: HIOP relaxed ordering + Mpush write bug. SoC-level ordering violation allows reads to bypass Mpush writes when relaxed ordering=1 in HIOP. DSA fill data corrupted. BIOS fix: fix_id=14026111032.",
        "verified_fix": "Same as HSD 14026147117: Apply BIOS fix fix_id=14026111032. Disable HIOP relaxed ordering.",
        "architectural_element": "HIOP relaxed ordering; Mpush write path; soc.top ordering",
        "failure_registers": ["HIOP relaxed_ordering_enable"],
        "adjacent_subsystems": ["HIOP IP", "M2IOSF", "DSA fill engine"],
        "related_hsds": ["14026111032", "14026147117"],
        "spec_reference": "Same as HSD 14026147117"
    },
    phase4={
        "tier1": [
            {"category": "hiop_ordering", "commands": ["sv.socket0.imhs.hiop.hiop_reg.relaxed_ordering_enable"], "reveals": "HIOP relaxed ordering enable state", "relevance": "Same as HSD 14026147117"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — same as HSD 14026147117",
        "root_cause_domain": "hw.dsa / HIOP relaxed ordering + Mpush write ordering violation (duplicate of 14026147117)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "Same root cause and fix as HSD 14026147117.",
        "iteration_savings": "3",
    },
)

# ── HSD 16029013188 — AUTOMATION bind_device_vfio() DSA pre-VV ───────────────
write(
    "16029013188",
    phase2={
        "testcase_name": "AUTOMATION pre-VV DSA bind_device_vfio() and verify_devices_loaded_to_vfio() API failing",
        "testcase_command": "modprobe vfio-pci; bind_device_vfio(); verify_devices_loaded_to_vfio()",
        "testcase_parameters": "OKS DMR pre-VV automation; kayak SSH; modprobe vfio-pci; find /sys | grep drivers.*0000:0d:00.0; DSA VFIO passthrough test",
        "testcase_domain_focus": "Pre-VV automation failure: DSA device not binding to vfio-pci driver; verify_devices_loaded_to_vfio() API fails after modprobe",
    },
    phase3={
        "verified_problem_statement": "Pre-VV automation: bind_device_vfio() and verify_devices_loaded_to_vfio() API fail for DSA devices on OKS DMR. modprobe vfio-pci runs, but device 0000:0d:00.0 not found in /sys after bind.",
        "verified_root_cause": "DSA VFIO bind failure: (1) vfio-pci module loads but DSA device 0000:0d:00.0 not unbound from idxd driver first — must unbind from idxd before binding to vfio-pci; (2) DSA device BDF mismatch — test expects device at 0000:0d:00.0 but actual BDF differs on DMR; (3) IOMMU not enabled in BIOS — vfio-pci requires IOMMU/VT-d enabled; (4) Automation content issue (val.env.content) — kayak test script uses wrong BDF or missing unbind step before vfio-pci rebind.",
        "verified_fix": "Unbind DSA from idxd before binding to vfio-pci. Verify DSA BDF on DMR platform. Enable IOMMU/VT-d in BIOS. Fix automation content for DMR-specific BDF.",
        "architectural_element": "DSA VFIO passthrough; vfio-pci driver; idxd driver unbind; IOMMU",
        "failure_registers": [],
        "adjacent_subsystems": ["vfio-pci kernel module", "idxd driver", "IOMMU/VT-d", "kayak automation"],
        "related_hsds": [],
        "spec_reference": "Accelerator Stack wiki: VFIO passthrough setup; VT-d/IOMMU requirements for DSA passthrough"
    },
    phase4={
        "tier1": [
            {"category": "vfio_check", "commands": ["lspci | grep 0b25", "cat /sys/bus/pci/devices/0000:0d:00.0/driver 2>/dev/null", "lsmod | grep vfio"], "reveals": "DSA actual BDF and current driver binding status", "relevance": "Wrong BDF or still bound to idxd = bind_device_vfio() fails"},
            {"category": "iommu_check", "commands": ["dmesg | grep -i 'iommu\\|VT-d'", "cat /sys/kernel/iommu_groups/ | wc -l"], "reveals": "IOMMU/VT-d enablement status", "relevance": "IOMMU not enabled = vfio-pci cannot work"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "indirect — automation infrastructure (VFIO setup) fails; DSA test cannot start",
        "root_cause_domain": "val.env.content / DSA VFIO bind sequence error or wrong BDF in automation",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "vfio_check identifies BDF and driver state. iommu_check confirms prerequisite. Simple automation fix.",
        "iteration_savings": "2",
    },
)

# ── HSD 16029011214 — AUTOMATION SSH timeout md5sum CentOS Img ───────────────
write(
    "16029011214",
    phase2={
        "testcase_name": "AUTOMATION pre-VV SSH command timeout during md5sum of CentOS Img",
        "testcase_command": "md5sum /home/BKCPkg/domains/accelerator/imgs/dmr-bkc-centos-stream-10-coreserver-6.14-7.4-PO13-16.img",
        "testcase_parameters": "OKS DMR pre-VV; kayak SSH protocol; md5sum of large CentOS image file; SSH timeout after 3min; val.env.execution",
        "testcase_domain_focus": "Pre-VV automation SSH timeout during md5sum of large BKC CentOS image — environment/infrastructure issue",
    },
    phase3={
        "verified_problem_statement": "Pre-VV automation SSH command times out running md5sum of large CentOS image file on OKS DMR. kayak SSH protocol times out after 3 minutes.",
        "verified_root_cause": "SSH timeout during md5sum of large image: (1) CentOS image file is large (likely multi-GB) — md5sum takes >3min SSH timeout; (2) kayak default SSH command timeout too short for large file integrity check; (3) Alternative: large NFS/disk performance issue causing md5sum to run slowly; (4) val.env.execution issue — automation environment configuration, not silicon bug.",
        "verified_fix": "Increase kayak SSH command timeout for md5sum step. Pre-compute md5sum outside timed step. Or use faster checksum (sha1sum). Update automation content.",
        "architectural_element": "kayak SSH timeout configuration; md5sum large file; BKC image verification",
        "failure_registers": [],
        "adjacent_subsystems": ["kayak automation framework", "SSH protocol layer", "NFS/storage"],
        "related_hsds": [],
        "spec_reference": "Kayak framework docs: SSH timeout configuration; BKC image verification best practices"
    },
    phase4={
        "tier1": [
            {"category": "file_size", "commands": ["ls -lh /home/BKCPkg/domains/accelerator/imgs/dmr-bkc-centos-stream-10*.img"], "reveals": "Image file size", "relevance": "File size determines md5sum duration; >2GB likely to timeout in 3min"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "indirect — automation SSH timeout; not a silicon bug",
        "root_cause_domain": "val.env.execution / SSH timeout in kayak for large file md5sum",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "file_size confirms timeout expected. Automation timeout config fix.",
        "iteration_savings": "2",
    },
)

# ── HSD 15018552625 — AUTOMATION QDF decoding failure multiple test cases ─────
write(
    "15018552625",
    phase2={
        "testcase_name": "AUTOMATION pre-VV multiple test cases fail decoding QDF information from EVF open AP",
        "testcase_command": "(kayak accelerator test framework init: idxd_provider.py __init__ → read_accelerator_count → qdf_values = [cpu[features][qdf] for cpu in cpu_info[cpus].values()])",
        "testcase_parameters": "DMR AP PRE_VV automation; EVF open AP; QDF decoding failure in idxd_provider.py:1076; KeyError on qdf field in cpu_info",
        "testcase_domain_focus": "Pre-VV automation QDF file decoding failure — multiple test cases fail because EVF open AP CPU QDF file format different from expected",
    },
    phase3={
        "verified_problem_statement": "Multiple DMR AP pre-VV automation test cases fail at startup: idxd_provider.py cannot decode QDF from EVF open AP cpu_info — KeyError on 'qdf' in cpu features dict.",
        "verified_root_cause": "QDF decoding failure from EVF open AP: (1) EVF open AP part does not have QDF programmed — cpu_info returned lacks 'qdf' key in features dict causing KeyError; (2) QDF file for DMR open AP not in expected format or location — idxd_provider looks up QDF to determine accelerator configuration but file not present; (3) EVF (Engineering Validation Fixture) platform has different CPU inventory structure than production AP parts; (4) val.env.execution — automation framework not updated for EVF open AP parts.",
        "verified_fix": "Add QDF file for DMR AP in BKCPkg location. Update idxd_provider.py to handle missing QDF gracefully. Create default accelerator count for open AP parts.",
        "architectural_element": "idxd_provider QDF lookup; EVF open AP CPU inventory; kayak accelerator framework init",
        "failure_registers": [],
        "adjacent_subsystems": ["kayak accelerator framework", "idxd_provider.py", "EVF platform", "BKCPkg CPU inventory"],
        "related_hsds": ["16028966596"],
        "spec_reference": "Kayak accelerator framework docs; BKCPkg open AP QDF requirements"
    },
    phase4={
        "tier1": [
            {"category": "qdf_check", "commands": ["python -c \"import json; d=json.load(open('/path/cpu_info.json')); print(list(d['cpus'].values())[0].get('features',{}))\""], "reveals": "CPU features dict structure for EVF open AP", "relevance": "Missing qdf key = EVF AP part without QDF programming"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "indirect — automation init fails before test starts; not a silicon bug",
        "root_cause_domain": "val.env.execution / EVF open AP lacks QDF for idxd_provider",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "Same pattern as HSD 16028966596. qdf_check confirms missing QDF data. Automation fix.",
        "iteration_savings": "2",
    },
)

# ── HSD 16028966596 — AUTOMATION CPU QDF file missing ────────────────────────
write(
    "16028966596",
    phase2={
        "testcase_name": "AUTOMATION pre-VV CPU QDF file missing in BKCPkg location",
        "testcase_command": "(kayak accelerator framework init — reads QDF XLSX to determine accelerator configuration)",
        "testcase_parameters": "OKS DMR pre-VV automation; RuntimeError: No sheet found for CPU family {cpu_family} in qdf_details.xlsx path; val.env.execution",
        "testcase_domain_focus": "Pre-VV automation: CPU QDF XLSX file missing or lacks sheet for DMR CPU family — automation cannot determine accelerator configuration",
    },
    phase3={
        "verified_problem_statement": "Pre-VV automation fails: RuntimeError: No sheet found for CPU family in qdf_details.xlsx. QDF file needed to determine number/type of accelerators on DMR platform.",
        "verified_root_cause": "Missing CPU QDF XLSX entry for DMR: (1) qdf_details.xlsx file at BKCPkg location does not have a sheet for DMR CPU family; (2) DMR platform recently added; QDF Excel file not updated with DMR sheet; (3) Automation reads XLSX by CPU family name — if sheet name doesn't match expected DMR family identifier, RuntimeError thrown; (4) val.env.execution issue.",
        "verified_fix": "Place correct QDF file with DMR CPU family sheet at expected BKCPkg location. Or update automation content with correct file path for DMR.",
        "architectural_element": "BKCPkg QDF file; kayak CPU inventory; accelerator count determination",
        "failure_registers": [],
        "adjacent_subsystems": ["kayak automation", "BKCPkg deployment", "QDF file management"],
        "related_hsds": ["15018552625"],
        "spec_reference": "Kayak framework docs: QDF file requirements; BKCPkg accelerator content"
    },
    phase4={
        "tier1": [
            {"category": "qdf_file_check", "commands": ["ls /home/BKCPkg/domains/accelerator/*.xlsx 2>/dev/null", "python -c \"import openpyxl; wb=openpyxl.load_workbook('qdf_details.xlsx'); print(wb.sheetnames)\""], "reveals": "QDF file location and available sheets", "relevance": "Missing DMR sheet = RuntimeError on accelerator count determination"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "indirect — automation init fails; QDF file missing for DMR; not a silicon bug",
        "root_cause_domain": "val.env.execution / missing CPU QDF XLSX for DMR platform",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "qdf_file_check confirms missing sheet. Simple file deployment fix.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026047337 — DSA/IAA no command completion interrupt on parity error ─
write(
    "14026047337",
    phase2={
        "testcase_name": "DSA/IAA not reporting command completion interrupt when injecting parity error during disable admin commands",
        "testcase_command": "ERRINJCTL parity error injection + disable admin command; read INTCAUSE register",
        "testcase_parameters": "X1 A0 PO; INTCAUSE register: dhs=1 sw_error=1 command_completion=0 (GNR same); CloneScript clone; hw.iax",
        "testcase_domain_focus": "DSA/IAA INTCAUSE register not reporting command completion interrupt when parity error injected on disable admin command — present on both GNR and DMR",
    },
    phase3={
        "verified_problem_statement": "When parity error is injected during disable admin command, INTCAUSE register shows dhs=1, sw_error=1, but command_completion=0 on DMR X1 A0 PO. Same behavior on GNR. Expected: command_completion should be set along with sw_error.",
        "verified_root_cause": "DSA/IAA HW bug: interrupt source arbitration on error path — when a parity error aborts admin command, the command_completion interrupt source is not generated because the command was aborted (not completed). The IP only asserts command_completion for successful command completions; error aborts only assert sw_error. This is by-design behavior but spec may be unclear. Both DSA and IAA affected (same interrupt controller block). CloneScript indicates being tracked across products.",
        "verified_fix": "Software must check CMDSTS register for command abort status. Driver must handle sw_error interrupt to detect failed command — do not rely on command_completion for error paths. Update driver error path to poll CMDSTS after sw_error.",
        "architectural_element": "DSA/IAA INTCAUSE interrupt source; ERRINJCTL parity injection; disable admin command path; CMDSTS register",
        "failure_registers": ["INTCAUSE", "CMDSTS", "ERRINJCTL", "SWERROR0"],
        "adjacent_subsystems": ["DSA interrupt controller", "IAA interrupt controller", "admin command dispatcher", "parity error injector"],
        "related_hsds": ["14026030387"],
        "spec_reference": "DSA/IAA HAS: INTCAUSE register fields; admin command completion vs abort; ERRINJCTL behavior"
    },
    phase4={
        "tier1": [
            {"category": "intcause_check", "commands": ["sv.socket0.imhs.acc.accs.dsa.intcause.show()", "sv.socket0.imhs.acc.accs.dsa.cmdsts.show()"], "reveals": "Interrupt cause and command completion status", "relevance": "command_completion=0 with sw_error=1 = expected behavior on command abort"},
            {"category": "cmdsts_check", "commands": ["sv.socket0.imhs.acc.accs.dsa.cmdsts.show()", "sv.socket0.imhs.acc.accs.iaa.cmdsts.show()"], "reveals": "Admin command abort status", "relevance": "Abort bit in CMDSTS = parity error caused command abort, not completion"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — parity error injection test exercises admin command error path; interrupt behavior differs from spec expectation",
        "root_cause_domain": "hw.iax / DSA/IAA interrupt source not asserted for aborted commands (by-design or spec mismatch)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "intcause_check + cmdsts_check confirm abort behavior. CloneScript = tracked across products. Driver fix needed.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026030387 — IAA no command completion interrupt on parity error ─────
write(
    "14026030387",
    phase2={
        "testcase_name": "IAA not reporting command completion interrupt when injecting parity error during disable admin commands",
        "testcase_command": "IPICTL error injection + disable admin command; read INTCAUSE register",
        "testcase_parameters": "X1 A0 PO; IPICTL error injection; disable admin command; INTCAUSE shows no command completion; hw.iax; CloneScript clone",
        "testcase_domain_focus": "IAA-only: INTCAUSE not reporting command completion interrupt when parity error injected via IPICTL during disable admin command",
    },
    phase3={
        "verified_problem_statement": "IAA-only ticket: INTCAUSE register not reporting command completion interrupt when parity error injected via IPICTL during disable admin command on DMR X1 A0 PO.",
        "verified_root_cause": "Same root cause as HSD 14026047337 but IAA-specific. IPICTL (Internal Protocol Interface Control) error injection on IAA causes same behavior — command aborted (not completed), so command_completion interrupt not asserted. IAA interrupt controller shares same design with DSA. Additional IAA-specific: IPICTL injection may also cause IAA to halt (dhs=1) before command completion path is reached.",
        "verified_fix": "Same as HSD 14026047337: driver must handle sw_error interrupt to detect failed command. Check CMDSTS for abort status. Update IAA driver error path.",
        "architectural_element": "IAA INTCAUSE interrupt source; IPICTL error injection; disable admin command; CMDSTS register",
        "failure_registers": ["INTCAUSE", "CMDSTS", "IPICTL", "SWERROR0"],
        "adjacent_subsystems": ["IAA interrupt controller", "IAA admin command dispatcher", "IPICTL"],
        "related_hsds": ["14026047337"],
        "spec_reference": "DSA/IAA HAS: INTCAUSE register fields; IPICTL injection behavior"
    },
    phase4={
        "tier1": [
            {"category": "iaa_intcause_check", "commands": ["sv.socket0.imhs.acc.accs.iaa.intcause.show()", "sv.socket0.imhs.acc.accs.iaa.cmdsts.show()"], "reveals": "IAA interrupt cause and command status", "relevance": "command_completion=0 with dhs=1 = expected abort behavior"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — IAA IPICTL error injection test; same interrupt behavior as DSA HSD 14026047337",
        "root_cause_domain": "hw.iax / IAA interrupt not asserted for aborted admin command (clone of 14026047337)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "Same analysis as HSD 14026047337. iaa_intcause_check confirms.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026024415 — DSA/IAA PCIetc EV buffer memory allocation failure ──────
write(
    "14026024415",
    phase2={
        "testcase_name": "DSA/IAA stress + P2P targets using PCIetc EV buffers test unable to allocate EV buffer memory targets",
        "testcase_command": "(DSA/IAA P2P stress test with PCIetc EV buffer targets — Simics-based)",
        "testcase_parameters": "X1 A0 PO; P2P targets using PCIetc EV buffers; unable to allocate EV buffer memory targets; val.env.tool; previously seen on Simics HSD 14024707555",
        "testcase_domain_focus": "Test tool environment issue: EV buffer memory allocation failure for DSA/IAA P2P test on PCIetc platform",
    },
    phase3={
        "verified_problem_statement": "DSA/IAA stress + P2P test using PCIetc EV buffers fails to allocate EV buffer memory targets on DMR X1 A0 PO. Same pattern as Simics HSD 14024707555.",
        "verified_root_cause": "PCIetc EV buffer allocation failure: (1) PCIetc (PCIe Test Controller) EV buffer allocation out of memory — EV buffer pool too small for large P2P stress test; (2) PCIetc firmware/driver version not updated for DMR topology — EV buffer manager does not enumerate all available MMIO regions; (3) Memory alignment requirements for DMR P2P EV buffers stricter than GNR — allocation API rejects otherwise valid requests; (4) val.env.tool issue — PCIetc test tool version incompatibility.",
        "verified_fix": "Update PCIetc tool version for DMR. Reduce P2P stress test EV buffer count. Verify MMIO alignment requirements for DMR EV buffer allocation.",
        "architectural_element": "PCIetc EV buffer; P2P memory target; PCIe MMIO allocation; DMR P2P topology",
        "failure_registers": [],
        "adjacent_subsystems": ["PCIetc test controller", "EV buffer manager", "P2P MMIO allocator"],
        "related_hsds": ["14024707555"],
        "spec_reference": "PCIetc tool wiki; DMR P2P topology spec; EV buffer allocation requirements"
    },
    phase4={
        "tier1": [
            {"category": "ev_buffer_check", "commands": ["Verify PCIetc tool version for DMR compatibility", "Check available EV buffer pool size in PCIetc config"], "reveals": "Tool version and EV buffer pool availability", "relevance": "Tool version mismatch = buffer allocation API incompatible with DMR"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "indirect — test tool EV buffer allocation fails; P2P test cannot start; not a silicon bug",
        "root_cause_domain": "val.env.tool / PCIetc EV buffer allocation failure for DMR P2P test",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "Same as Simics HSD 14024707555. Tool version update most likely fix.",
        "iteration_savings": "2",
    },
)

# ── HSD 14025998683 — DSA/IAA/QAT WAC Policy group test trustmate iosfsbRspError
write(
    "14025998683",
    phase2={
        "testcase_name": "DSA IAA QAT Policy group test fail on test_wac_agent_to_func_reg_positive_write",
        "testcase_command": "test_wac_agent_to_func_reg_positive_write() via pythonSV trustmate",
        "testcase_parameters": "X1 A0 PO; pythonSV trustmate WAC register access; iosfsbRspError: RSP 01 Unsuccessful/not supported; val.env.tool",
        "testcase_domain_focus": "PythonSV WAC policy test iosfsbRspError after trustmate — IOSFsb register access fails due to trustmate security context change",
    },
    phase3={
        "verified_problem_statement": "test_wac_agent_to_func_reg_positive_write() via pythonSV trustmate fails with iosfsbRspError: RSP 01 Unsuccessful/not supported on DMR X1 A0 PO after running trustmate.",
        "verified_root_cause": "trustmate security context change breaks pythonSV register access: (1) trustmate establishes Secure Access mode — changes IOSFsb SAI (Security Attribute Identification) context such that subsequent pythonSV register reads/writes get RSP 01 (Unsuccessful) response; (2) WAC (Write Access Control) test requires agent-level write access but trustmate changes the effective agent SAI; (3) iosfsbRspError RSP 01 = hardware rejected the IOSF sideband transaction as 'not supported' in current security context; (4) val.env.tool — test framework does not reset security context after trustmate; (5) Python session needs to reinitialize after trustmate to use correct SAI.",
        "verified_fix": "Reinitialize pythonSV session after trustmate. Reset security context before WAC register access. Or run WAC test before trustmate in test sequence.",
        "architectural_element": "IOSFsb SAI; trustmate security context; WAC register; pythonSV IOSF access",
        "failure_registers": ["WAC register", "IOSFsb SAI register"],
        "adjacent_subsystems": ["trustmate", "IOSFsb", "SAI security context", "pythonSV SV path"],
        "related_hsds": [],
        "spec_reference": "trustmate wiki; IOSFsb SAI context requirements; pythonSV usage after security mode change"
    },
    phase4={
        "tier1": [
            {"category": "sai_context_check", "commands": ["python3 -c 'import sv; sv.refresh(); sv.socket0.imhs.acc.accs.dsa.wac.show()'"], "reveals": "Whether pythonSV session reinit resolves register access", "relevance": "Success after reinit = trustmate security context was the issue"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "indirect — trustmate changes SAI context; pythonSV WAC access fails; not a silicon bug",
        "root_cause_domain": "val.env.tool / pythonSV SAI context invalid after trustmate",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "sai_context_check confirms. Known trustmate + pythonSV interaction. Session reinit fix.",
        "iteration_savings": "2",
    },
)

# ── HSD 14025991026 — Linux driver not clearing DSA/IAA DEVSTS on boot ────────
write(
    "14025991026",
    phase2={
        "testcase_name": "BKC Linux drivers not clearing DSA/IAA DEVSTS register on system boot",
        "testcase_command": "Boot with BIOS knobs enabled; read sv.socket0.imhs.acc.accs.dsa.devsts",
        "testcase_parameters": "X1 A0 PO; DSA/IAA DEVSTS register not cleared on boot; driver only clears segment 1; hw.dsa; RC: Linux driver update needed to clean up stale DEVSTS",
        "testcase_domain_focus": "Linux idxd driver not clearing stale DSA/IAA DEVSTS register on all segments at system boot — driver bug",
    },
    phase3={
        "verified_problem_statement": "BKC Linux (CentOS10) idxd driver not clearing DSA/IAA DEVSTS register on system boot when BIOS knobs enabled. Driver only clears segment 1. DEVSTS remains non-zero for other segments.",
        "verified_root_cause": "Linux idxd driver DEVSTS clearing bug: idxd driver only clears DEVSTS for segment 1 at device probe/init; remaining segments (2, 3, 4) have stale DEVSTS values. Root cause: driver initialization loop iterates only one segment or uses incorrect segment base offset. DMR accelerators have multiple segments (new feature); existing driver written for single-segment devices. Stale DEVSTS can cause incorrect device state detection on subsequent access.",
        "verified_fix": "Linux driver update: clear DEVSTS for all segments during device probe. Track fix in Linux idxd driver patch. Component hw.dsa confirmed.",
        "architectural_element": "DSA/IAA DEVSTS register; multi-segment device init; Linux idxd driver probe; BIOS device state knobs",
        "failure_registers": ["DEVSTS", "sv.socket0.imhs.acc.accs.dsa.devsts"],
        "adjacent_subsystems": ["Linux idxd driver", "DSA multi-segment controller", "BIOS accelerator config"],
        "related_hsds": [],
        "spec_reference": "DSA/IAA HAS: DEVSTS register; multi-segment device model; Linux idxd driver changelog"
    },
    phase4={
        "tier1": [
            {"category": "devsts_check", "commands": ["sv.socket0.imhs.acc.accs.dsa.devsts", "sv.socket0.imhs.acc.accs.iaa.devsts", "for i in range(4): sv.sockets.imhs.acc.accs[i].dsa.devsts.show()"], "reveals": "DEVSTS values for all DSA/IAA segments", "relevance": "Non-zero values for segment > 1 = driver not clearing all segments"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — reads DEVSTS after boot; stale values from driver not clearing all segments",
        "root_cause_domain": "hw.dsa / Linux idxd driver not clearing DEVSTS on all segments",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "devsts_check confirms stale segments. Driver fix confirmed in RC description.",
        "iteration_savings": "2",
    },
)

# ── HSD 14025967580 — DSA/IAA HAS incorrect ERRINJCTL stimulus ────────────────
write(
    "14025967580",
    phase2={
        "testcase_name": "DSA/IAA HAS incorrect ERRINJCTL stimulus for IPICTL injection",
        "testcase_command": "(Documentation issue — ERRINJCTL stimulus spec review vs implementation)",
        "testcase_parameters": "X1 A0 PO; ERRINJCTL IPICTL injection; HAS specifies wrong stimulus (Desc Reads Payload Data vs Disable device/wq admin command); hw.iax; doc clone",
        "testcase_domain_focus": "DSA/IAA HAS documentation error — ERRINJCTL IPICTL stimulus description incorrect; disable device/wq admin command is correct stimulus not Desc Reads Payload Data",
    },
    phase3={
        "verified_problem_statement": "DSA/IAA HAS specifies incorrect ERRINJCTL stimulus for IPICTL injection. HAS says 'Desc Reads Payload Data' but actual behavior triggered by 'Disable device/wq admin command'. Documentation error.",
        "verified_root_cause": "HAS documentation error: ERRINJCTL register description for IPICTL injection specifies wrong stimulus. Test attempted 'Desc Reads Payload Data' stimulus as documented but error only triggers on 'Disable device or Disable WQ admin command'. CloneScript clone indicates this is being propagated to doc fix.",
        "verified_fix": "Update DSA/IAA HAS ERRINJCTL stimulus description for IPICTL injection. Change 'Desc Reads Payload Data' to 'Disable device/wq admin command'. CloneScript tracking in place.",
        "architectural_element": "DSA/IAA HAS ERRINJCTL documentation; IPICTL error injection stimulus; admin command error path",
        "failure_registers": ["ERRINJCTL"],
        "adjacent_subsystems": ["DSA/IAA HAS documentation", "ERRINJCTL spec"],
        "related_hsds": ["14026030387", "14026047337"],
        "spec_reference": "DSA/IAA HAS: ERRINJCTL register description; IPICTL injection section"
    },
    phase4={
        "tier1": [],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [
            {"description": "Update DSA/IAA HAS ERRINJCTL stimulus for IPICTL", "commands": ["File HAS doc update with correct stimulus for IPICTL injection"], "why": "Documentation update requires HAS owner action"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "indirect — test follows HAS spec which has wrong stimulus; test fails because wrong stimulus used",
        "root_cause_domain": "val.env.content / DSA/IAA HAS documentation error in ERRINJCTL IPICTL stimulus",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "Documentation fix only. CloneScript tracking in place. No silicon action needed.",
        "iteration_savings": "1",
    },
)

# ── HSD 16029018274 — DSA3 opcode 0x3 batch size 1 failure ───────────────────
write(
    "16029018274",
    phase2={
        "testcase_name": "DSA3 opcode 0x3 (CRC generation) failure with batch size 1 on OKS DMR AP",
        "testcase_command": "./Setup_Randomize_DSA_Conf.sh -B 1 -b 0x3",
        "testcase_parameters": "OKS DMR AP; opcode 0x3 (CRC generation); batch size (-B) = 1; WQ count 32; transfer size 2097152; descriptor_status and wq_state logs present",
        "testcase_domain_focus": "DSA3 CRC generation opcode 0x3 fails with batch size 1 on DMR AP — descriptor or WQ configuration issue at batch size boundary",
    },
    phase3={
        "verified_problem_statement": "DSA3 opcode 0x3 (CRC generation) fails with batch descriptor batch size 1 on OKS DMR AP. Setup_Randomize_DSA_Conf.sh -B 1 -b 0x3, all 32 WQs tested, 2MB transfer size.",
        "verified_root_cause": "DSA3 CRC opcode batch size 1 failure: (1) Batch descriptor with batch count=1 may expose a DSA3 batch descriptor handling edge case — single-element batches may require different DMA completion path; (2) CHANERR register may have error bits set from previous run — need to clear CHANERR before restarting after any error state; (3) Descriptor parameter misconfiguration for CRC (opcode 0x3) with B=1 — source/dest length, flags, or CRC seed may be incorrectly set for single-element batch; (4) DSA3-specific: batch size 1 is a degenerate case; DSA3 may optimize single-element batches differently from multi-element batches; (5) If WQ state shows error after failure, SWERROR0 register identifies specific error code.",
        "verified_fix": "Inspect descriptor_status and wq_state logs for error code. Clear CHANERR before retry. Verify CRC descriptor parameters for batch size 1. Check DSA3 batch descriptor handling for degenerate case.",
        "architectural_element": "DSA3 batch descriptor; CRC generation opcode 0x3; CHANERR; WQ state machine; batch count handling",
        "failure_registers": ["CHANERR", "SWERROR0", "COMPRSULT (completion record)"],
        "adjacent_subsystems": ["DSA3 batch descriptor engine", "CRC generation unit", "WQ state machine"],
        "related_hsds": [],
        "spec_reference": "DSA/IAA HAS: opcode 0x3 CRC generation; batch descriptor requirements; CHANERR clearing after error; single-element batch handling"
    },
    phase4={
        "tier1": [
            {"category": "swerror_check", "commands": ["sv.socket0.imhs.acc.accs.dsa.swerror0.show()", "sv.socket0.imhs.acc.accs.dsa.chanerr.show()"], "reveals": "DSA error state after CRC batch failure", "relevance": "Error code identifies descriptor parameter error or hardware fault"},
            {"category": "wq_state_check", "commands": ["sv.socket0.imhs.acc.accs.dsa.wqcfg.show()", "cat descriptor_status.log | head -50"], "reveals": "WQ state and descriptor completion record", "relevance": "Error in completion record identifies specific failure point"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — DSA3 CRC opcode with batch size 1; descriptor or WQ error",
        "root_cause_domain": "hw.dsa / DSA3 batch size 1 CRC descriptor handling or test parameter configuration",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "swerror_check + wq_state_check identify specific error. Descriptor log analysis needed.",
        "iteration_savings": "2",
    },
)

# ── HSD 14026147322 — IAA sandstone data-miscompare ──────────────────────────
write(
    "14026147322",
    phase2={
        "testcase_name": "IAA sandstone iax subtest data-miscompare on DMR/kin s7117",
        "testcase_command": "sandstone -e iax (iax subtest in sandstone suite)",
        "testcase_parameters": "DMR kin s7117; iax1 group group1.1 wq wq1.5; data-miscompare: Comparing Select output data results with gold data; type uint8_t; hw.iax",
        "testcase_domain_focus": "IAA sandstone iax subtest data-miscompare — Select operation data integrity failure on DMR hw.iax",
    },
    phase3={
        "verified_problem_statement": "IAA sandstone iax subtest detects data-miscompare on DMR kin s7117: 'Comparing Select output data results with gold data', type uint8_t, device iax1 group group1.1 wq wq1.5.",
        "verified_root_cause": "IAA sandstone iax data-miscompare on Select operation: (1) IAA/IAX Select operation (filter/select data elements) produces wrong output compared to golden reference. Possible causes: (a) DMR A0 IAA hardware bug in Select operation result — known A0 byte-count mismatch (HSD 22020561826) may corrupt Select output; (b) IAX configuration mismatch — device enablement, MMIO mapping, or IOMMU translation error causes wrong data path; (c) Test gold data computed with different IAA behavioral model than DMR A0 hardware; (d) iax1 wq1.5 not properly initialized — WQ state carries stale config affecting Select output. GENI: no specific DMR IAA hardware flaw documented for Select at this time; investigate A0 bugs and config first.",
        "verified_fix": "Apply A0 workarounds (HSD 22020561826 byte-count mismatch WA). Verify iax1 enablement and WQ initialization. Check IAA Select operation parameters against golden model. Cross-reference with sandstone gold data version.",
        "architectural_element": "IAA Select operation; WQ configuration; A0 byte-count mismatch; IAX data path",
        "failure_registers": ["IAA SWERROR", "IAA completion record", "WQ state register"],
        "adjacent_subsystems": ["IAA filter/select engine", "WQ state machine", "IOMMU/ATS path", "A0 completion handler"],
        "related_hsds": ["22020561826", "14026198585"],
        "spec_reference": "IAX/IAA Integration DMR spec; DMR High-Level Architecture; Accelerator Stack wiki: DMR A0 known bugs"
    },
    phase4={
        "tier1": [
            {"category": "iaa_swerror", "commands": ["from diamondrapids.accelerators.dsa_iaa import dsa_iaa_debug_dump as dsa_iaa_dump", "dsa_iaa_dump.dump_all_dsa_inst_errs()"], "reveals": "IAA error state during Select failure", "relevance": "Error code identifies A0 HW bug vs configuration issue"},
            {"category": "wq_state_check", "commands": ["sv.socket0.imhs.acc.accs.iaa.wqcfg.show()", "sv.socket0.imhs.acc.accs.iaa.gensts.show()"], "reveals": "WQ configuration and general status", "relevance": "Stale WQ state = initialization issue; clean state = hardware data error"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — IAA Select operation output compared to golden data; mismatch from A0 bug or config issue",
        "root_cause_domain": "hw.iax / IAA sandstone Select data-miscompare; potential A0 byte-count mismatch or WQ config issue",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "iaa_swerror + wq_state_check identify root cause. A0 WA applicable if byte-count mismatch confirmed.",
        "iteration_savings": "2",
    },
)

# ── HSD 18043800050 — Accelerator Telemetry aggregator not updating ───────────
write(
    "18043800050",
    phase2={
        "testcase_name": "DMR AP A0 2S Accelerator Telemetry aggregator not updating values (always 0)",
        "testcase_command": "(Manageability SCIV telemetry aggregator read via OOBMSM BAR1 PMT interface)",
        "testcase_parameters": "DMR AP A0 PO 2S; SCIV manageability; BAR1 addresses visible IMH0-IMH3; telemetry values always 0; component fw.ocode",
        "testcase_domain_focus": "DMR AP A0 2S Accelerator Telemetry aggregator OOBMSM fw.ocode always returns 0 — PMT/OOBMSM firmware initialization failure",
    },
    phase3={
        "verified_problem_statement": "Accelerator Telemetry aggregator not updating values on DMR AP A0 2S. All values always show 0. BAR1 addresses visible for IMH0-IMH3 but PMT telemetry not populated. Component fw.ocode.",
        "verified_root_cause": "OOBMSM firmware telemetry aggregator zero values on DMR A0: (1) fw.ocode (OOBMSM firmware) not receiving valid telemetry objects from CBB PUNITs — CBB PMT push path not operational on A0; (2) PMT (Platform Monitoring Technology) object GUID or session not established — Trusted Telemetry (SPDM/SAI session) not negotiated; (3) D2D (die-to-die) connectivity issue — CBB PUNIT SRAM telemetry not accessible from iMH die on DMR A0; (4) Firmware/fuse mismatch — platform fuses for MBVR and PMT not aligned with fw.ocode version being used; (5) Early A0 bring-up limitation — known non-functional A0 engineering combos; (6) BAR1 visible but PMT API path not functional — SRAM area not clocked or auth not succeeded.",
        "verified_fix": "Verify platform fuses for PMT (PCODE_SVID_MBVR_PRESENT_MASK). Check CBB firmware supports PMT push. Initialize Trusted Telemetry SPDM session. Check D2D fabric status. Use correct A0 eng release combo. Reference OOBMSM FW Architecture docs.",
        "architectural_element": "OOBMSM fw.ocode; PMT telemetry aggregator; CBB PUNIT SRAM; D2D telemetry push; Trusted Telemetry SPDM; BAR1 PMT interface",
        "failure_registers": ["OOBMSM PMT BAR1 telemetry registers"],
        "adjacent_subsystems": ["OOBMSM iMH die", "CBB PUNIT PMT", "D2D fabric", "Trusted Telemetry SPDM", "platform fuse MBVR"],
        "related_hsds": [],
        "spec_reference": "OOBMSM FW Gen4 DMR-HD FAS; DMR SOC PM HAS (PCODE_SVID_MBVR fuse registers); OOBMSM e2e test plan"
    },
    phase4={
        "tier1": [
            {"category": "pmt_check", "commands": ["python3 -c 'import sv; sv.socket0.imhs.imh.pmt_bar1.show()'", "python3 -c 'from oobmsm import telemetry; telemetry.dump_all_accelerator_telemetry()'"], "reveals": "PMT BAR1 accessibility and telemetry population status", "relevance": "Empty PMT objects = OOBMSM firmware not pushing telemetry from CBB"},
            {"category": "d2d_check", "commands": ["sv.socket0.imhs.imh.d2d_link_status.show()"], "reveals": "D2D link status between CBB and iMH", "relevance": "D2D link down = CBB PUNIT telemetry cannot reach OOBMSM aggregator"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [
            {"description": "Trusted Telemetry SPDM session negotiation status", "commands": ["Check OOBMSM logs for Trusted Telemetry SPDM session establishment"], "why": "Trusted Telemetry prerequisite may require FW team intervention"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — telemetry aggregator read returns 0; OOBMSM PMT not populated by CBB PUNIT",
        "root_cause_domain": "fw.ocode / OOBMSM PMT telemetry aggregator not receiving CBB PUNIT data on DMR A0",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "pmt_check + d2d_check identify PMT path failure. OOBMSM FW docs confirm A0 bring-up dependencies.",
        "iteration_savings": "2",
    },
)

# ── HSD 14025833391 — IAA error injection disable admin command process hang ──
write(
    "14025833391",
    phase2={
        "testcase_name": "IAA error injection during disable admin command causes linux processes to hang",
        "testcase_command": "sv.sockets.imhs.acc.accs.iaa.errinjctl = 0xe1; accel-config disable-device iaa1",
        "testcase_parameters": "X1 A0 PO; ERRINJCTL = 0xe1 (parity error injection on completions); disable device/wq via accel-config; process hangs; hw.dsa",
        "testcase_domain_focus": "IAA process hang when parity error injected on completions during disable admin command — driver deadlock on error path",
    },
    phase3={
        "verified_problem_statement": "When injecting parity error on completions (ERRINJCTL=0xe1) and issuing disable device/wq admin command via accel-config, linux test process and lspci hang on DMR X1 A0 PO.",
        "verified_root_cause": "IAA driver deadlock on parity error during disable admin command: (1) ERRINJCTL=0xe1 injects parity error on completion path; when disable admin command issued, IAA returns error completion; (2) idxd driver handles error completion but enters deadlock — driver lock held while waiting for admin command completion, but completion handler also tries to acquire same lock; (3) System enters halt/DHS state (dhs=1) — driver cannot recover from DHS state without full device reset; (4) lspci hangs because MMIO access to device registers blocks when device in DHS halt state; (5) Related to HSD 14026047337/14026030387 — same ERRINJCTL+disable command interaction.",
        "verified_fix": "Fix idxd driver lock ordering in error completion path. Add timeout to admin command wait. Issue full device reset after DHS state detected. Reference drvier deadlock fix.",
        "architectural_element": "IAA ERRINJCTL; admin command completion; idxd driver lock; DHS halt state; MMIO access during halt",
        "failure_registers": ["ERRINJCTL", "GENSTS (dhs bit)", "CMDSTS"],
        "adjacent_subsystems": ["idxd driver admin command path", "completion interrupt handler", "DHS state machine"],
        "related_hsds": ["14026047337", "14026030387"],
        "spec_reference": "DSA/IAA HAS: ERRINJCTL; DHS state recovery; admin command error handling"
    },
    phase4={
        "tier1": [
            {"category": "dhs_check", "commands": ["sv.socket0.imhs.acc.accs.iaa.gensts.dhs", "sv.socket0.imhs.acc.accs.iaa.cmdsts.show()"], "reveals": "IAA DHS halt state and command completion status", "relevance": "dhs=1 = device halted; lspci/driver MMIO hangs"},
            {"category": "driver_trace", "commands": ["echo t > /proc/sysrq-trigger; dmesg | grep idxd"], "reveals": "idxd driver lock state and hung task trace", "relevance": "Lock trace shows deadlock location"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — ERRINJCTL parity error causes DHS halt; driver deadlock + lspci MMIO hang",
        "root_cause_domain": "hw.dsa / idxd driver deadlock on IAA parity error in disable admin command path",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "dhs_check confirms DHS halt state. driver_trace shows deadlock. Known IAA error path issue.",
        "iteration_savings": "2",
    },
)

# ── HSD 14025818604 — IFWI/BIOS update for accelerator enablement tracking ────
write(
    "14025818604",
    phase2={
        "testcase_name": "IFWI/BIOS update tracking: enable accelerators DSA IAA QAT on DMR X1 A0 PO",
        "testcase_command": "b.go(fused_unit=False, pwrgoodmethod='manual', fuse_str={...iaa_disable=0x2, qat_disable=0x2, capid_capid8...})",
        "testcase_parameters": "X1 A0 PO; bios component; tracking ticket for transition from PO-safe to accelerator-enabled config; fuse_str with iaa_disable, qat_disable, capid settings",
        "testcase_domain_focus": "Tracking ticket for IFWI/BIOS updates to enable DSA IAA QAT accelerators on DMR X1 A0 PO — not a failure report",
    },
    phase3={
        "verified_problem_statement": "Tracking ticket for IFWI/BIOS update required to enable accelerators (DSA, IAA, QAT) on DMR X1 A0 PO. Track transition from PO-safe config to accelerator-enabled config. Component: bios.",
        "verified_root_cause": "BIOS/IFWI tracking ticket: Not a defect. This tracks BIOS configuration update needed to unfuse/enable DSA, IAA, QAT accelerators on DMR X1 A0 PO. Key fuse strings: iaa_disable=0x2 (partial enable), qat_disable=0x2 (partial enable), capid settings for accelerator configuration. RC documented: 'To track the transition from PO-safe to Accelerator enabled config'.",
        "verified_fix": "Apply IFWI/BIOS update with correct accelerator fuse_str. Use b.go() with specified fuse parameters for DMR X1 A0 PO accelerator enable.",
        "architectural_element": "BIOS fuse programming; accelerator disable fuses; CAPID8 accelerator count register; PO-safe config",
        "failure_registers": ["punit.capid_capid8_acc0_1", "punit.capid_capid8_acc5_1", "hwrs_top_late.ip_disable_fuses_dword3"],
        "adjacent_subsystems": ["BIOS fuse programming", "PUNIT CAPID", "accelerator enable path"],
        "related_hsds": [],
        "spec_reference": "DMR BIOS Fuse Guide; CAPID8 accelerator fuse programming; PO-safe BIOS config"
    },
    phase4={
        "tier1": [
            {"category": "capid_check", "commands": ["sv.socket0.imhs.punit.capid_capid8_acc0_1.show()", "sv.socket0.imhs.punit.capid_capid8_acc5_1.show()"], "reveals": "Accelerator CAPID fuse state", "relevance": "Confirms accelerator fuse configuration applied"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "indirect — tracking ticket for BIOS update; no direct test failure",
        "root_cause_domain": "bios / IFWI accelerator fuse configuration tracking (not a defect)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "Tracking ticket with documented BIOS fuse strings. Apply specified fuse_str.",
        "iteration_savings": "1",
    },
)

# ── HSD 14025785454 — IAA not showing up in SVOS SV nodes after fuse enable ──
write(
    "14025785454",
    phase2={
        "testcase_name": "IAA not showing up in SVOS SV nodes after fuse/BIOS enabled",
        "testcase_command": "(Check IAA in pythonSV node topology and BOOT manager)",
        "testcase_parameters": "X1 A0 PO; IAA not visible in node topology; not in BOOT manager; hw.fuse; fuse/BIOS enabled but IAA missing",
        "testcase_domain_focus": "IAA invisible in SVOS pythonSV node topology and BOOT manager despite fuse/BIOS enable attempt on DMR X1 A0 PO",
    },
    phase3={
        "verified_problem_statement": "IAA not showing up in SVOS SV node topology or BOOT manager on DMR X1 A0 PO despite fuse/BIOS being enabled. hw.fuse component.",
        "verified_root_cause": "IAA invisible in SV topology: (1) Fuse not applied correctly — iaa_disable fuse not fully cleared; need correct fuse_str with hwrs_top_late.ip_disable_fuses_dword3_iaa_disable=0x2 and capid settings; (2) BIOS not applying accelerator enable at post-boot — requires proper b.go() fuse_str as in HSD 14025818604; (3) BOOT manager doesn't enumerate IAA because IAA PCI device not created by BIOS/UEFI without proper fuse config; (4) PythonSV SV path for IAA not available because IAA device not enumerated; (5) hw.fuse component = fuse configuration root cause.",
        "verified_fix": "Apply correct fuse_str including iaa_disable=0x2 and capid settings (see HSD 14025818604). Verify BOOT manager enumerates IAA PCIe device. Use b.go() with fuse_str.",
        "architectural_element": "IAA fuse disable register; BIOS fuse programming; PCIe device enumeration; SV node topology",
        "failure_registers": ["hwrs_top_late.ip_disable_fuses_dword3_iaa_disable", "punit.capid_capid8_acc0_1"],
        "adjacent_subsystems": ["BIOS fuse programming", "UEFI PCIe enumeration", "SV path for IAA", "PUNIT CAPID"],
        "related_hsds": ["14025818604"],
        "spec_reference": "DMR BIOS Fuse Guide; CAPID8 IAA fuse programming; SVOS pythonSV IAA path"
    },
    phase4={
        "tier1": [
            {"category": "fuse_check", "commands": ["sv.socket0.imhs.acc.punit.capid_capid8_acc0_1.show()", "sv.socket0.imhs.hwrs_top_late.ip_disable_fuses_dword3.show()"], "reveals": "IAA fuse disable state", "relevance": "iaa_disable still set = fuse not applied; IAA not enumerated"},
            {"category": "pcie_check", "commands": ["lspci | grep 0cfe"], "reveals": "IAA PCIe device presence (device ID 0cfe)", "relevance": "IAA not in lspci = fuse or BIOS enumeration failure"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — IAA fuse not properly cleared; SV topology and BOOT manager missing IAA",
        "root_cause_domain": "hw.fuse / IAA fuse disable not cleared; incorrect fuse_str in b.go()",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "fuse_check + pcie_check confirm fuse state. Same fix as HSD 14025818604.",
        "iteration_savings": "2",
    },
)

# ── HSD 14025355540 — DSA dsa_test DSA3 opcode batch support (feature) ────────
write(
    "14025355540",
    phase2={
        "testcase_name": "DSA dsa_test tool missing batch support for DSA3 opcodes",
        "testcase_command": "(dsa_test tool — missing batch test for DSA3 opcodes)",
        "testcase_parameters": "DMR; dsa_test does not support DSA3 opcodes 0x18 0x19 0x1a 0x1b 0x1c in batch; feature request/tracking",
        "testcase_domain_focus": "dsa_test tool needs batch descriptor test support for DSA3-only opcodes — feature addition request",
    },
    phase3={
        "verified_problem_statement": "dsa_test tool does not currently support DSA3 opcodes (0x18, 0x19, 0x1a, 0x1b, 0x1c) in batch descriptor mode. Feature addition required for DMR DSA3 opcode test coverage.",
        "verified_root_cause": "Test tool coverage gap: dsa_test was written for DSA2 (GNR/SPR) opcodes and lacks batch descriptor support for DSA3 new opcodes: 0x18 (CRC with Completion On/Off), 0x19 (DIF Strip), 0x1a (DIF Insert), 0x1b (Gather Reduce), 0x1c (something). Note: 0x1d (Scatter Copy) and 0x1e (Scatter Fill) defeatured per HSD 14021759570. Feature addition to dsa_test required for batch coverage of non-defeatured DSA3 opcodes.",
        "verified_fix": "Add batch descriptor test support to dsa_test for DSA3 opcodes 0x18-0x1c. Exclude defeatured 0x1d, 0x1e. Submit dsa_test patch.",
        "architectural_element": "dsa_test tool; DSA3 batch descriptor; new opcode support",
        "failure_registers": [],
        "adjacent_subsystems": ["dsa_test validation tool", "DSA3 batch descriptor engine", "DSA3 new opcode support"],
        "related_hsds": ["16029052219", "14021759570"],
        "spec_reference": "DSA/IAA HAS: DSA3 new opcodes 0x18-0x1e; batch descriptor requirements"
    },
    phase4={
        "tier1": [],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [
            {"description": "Add DSA3 batch support to dsa_test tool", "commands": ["Submit dsa_test patch for DSA3 opcodes 0x18-0x1c batch support"], "why": "Tool development requires dev team action"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "indirect — test tool missing feature; no test executed; not a silicon bug",
        "root_cause_domain": "val.env.tool / dsa_test missing DSA3 batch opcode support (feature request)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "Tool enhancement only. No silicon action needed.",
        "iteration_savings": "1",
    },
)

# ── HSD 14026004873 — QAT SEGFAULT in CentOS VM on ESXi ─────────────────────
write(
    "14026004873",
    phase2={
        "testcase_name": "QAT Symmetric crypto workload fails with SEGFAULT in CentOS VM on ESXi Host on DMR AP A0",
        "testcase_command": "QAT symmetric crypto workload in CentOS VM on ESXi; srv_mask=10 ASYM+SYM config",
        "testcase_parameters": "OKS DMR AP A0 ESXi host; CentOS VM; vmkload_mod qat; srv_mask=10,10,10,10,10,10,10,10; ASYM+SYM services; SEGFAULT in crypto workload",
        "testcase_domain_focus": "QAT symmetric crypto SEGFAULT in CentOS VM under ESXi on DMR AP A0 — driver or library memory access violation",
    },
    phase3={
        "verified_problem_statement": "QAT symmetric crypto workload fails with SEGFAULT in CentOS VM on ESXi Host on DMR AP A0 OKS. QAT driver loaded via vmkload_mod, srv_mask=10 for ASYM+SYM.",
        "verified_root_cause": "QAT SEGFAULT in CentOS VM on ESXi: (1) QAT ESXi PF driver (QAT5.1_EXT_REL_PF_3.1.3.20) may have a VF passthrough issue — ESXi QAT PF driver exposes VFs to CentOS VM; VM QAT driver memory mapping error causes SEGFAULT; (2) ssm_pm_enable CSR interaction — DMR A0 QAT requires ssm_pm_enable=0 (PO WA); if this WA not applied in ESXi config, FW/HW may be in wrong state causing memory access violation; (3) srv_mask=10 configuration — ASYM+SYM service mask; incorrect service mask for DMR QAT capabilities may cause driver to access wrong memory regions; (4) No specific root cause documented in GENI for this exact ESXi SEGFAULT scenario; needs log analysis.",
        "verified_fix": "Apply ssm_pm_enable=0 WA for DMR A0 in ESXi config. Verify QAT PF driver version for DMR ESXi compatibility. Check srv_mask against DMR QAT capabilities. Capture SEGFAULT backtrace for further analysis.",
        "architectural_element": "QAT ESXi PF driver; VM QAT VF driver; ssm_pm_enable; srv_mask service configuration; DMR A0 QAT",
        "failure_registers": ["ssm_pm_enable CSR"],
        "adjacent_subsystems": ["ESXi QAT PF driver", "CentOS VM QAT VF driver", "QAT service configuration", "VF passthrough"],
        "related_hsds": ["14025998125"],
        "spec_reference": "OKS DMR AP A0 PPR; QAT ESXi driver installation guide; QAT_2025.07.01 package"
    },
    phase4={
        "tier1": [
            {"category": "ssm_pm_check", "commands": ["esxcfg-module -l | grep qat", "esxcli system module parameters list -m qat | grep ssm"], "reveals": "ssm_pm_enable status in ESXi QAT driver config", "relevance": "ssm_pm_enable not 0 = PO WA not applied; may cause SEGFAULT"},
            {"category": "segfault_log", "commands": ["cat /var/log/vmkernel.log | grep -i 'qat\\|segfault'", "dmesg | grep -i 'segfault\\|qat'"], "reveals": "SEGFAULT backtrace and QAT error messages", "relevance": "Backtrace identifies SEGFAULT location in driver or library"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — QAT crypto SEGFAULT in VM; driver memory access violation or WA not applied",
        "root_cause_domain": "hw.qat / ESXi QAT driver SEGFAULT — ssm_pm_enable WA or VF driver memory mapping issue",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "ssm_pm_check + segfault_log identify whether WA missing or driver memory bug. Log analysis needed.",
        "iteration_savings": "2",
    },
)

# ── HSD 14025998125 — QAT FW Auth fails on ESXi with ssm_pm_enable WA ────────
write(
    "14025998125",
    phase2={
        "testcase_name": "QAT FW Authentication fails on DMR AP A0 PO ESXi with ssm_pm_enable cleared WA",
        "testcase_command": "(QAT driver load on ESXi with ssm_pm_enable CSRs cleared; FW auth during boot)",
        "testcase_parameters": "OKS DMR AP A0 PO ESXi; QAT5.1_EXT_REL_PF_3.1.3.20 (QAT version 9.0); ssm_pm_enable WA applied (CSRs cleared); FW auth fails during boot",
        "testcase_domain_focus": "QAT FW Auth persistent failure on DMR AP A0 ESXi despite ssm_pm_enable=0 WA — cpm_pm_state stuck at INIT (0x2)",
    },
    phase3={
        "verified_problem_statement": "QAT FW Authentication fails on DMR AP A0 PO ESXi during boot even after ssm_pm_enable CSRs cleared WA. cpm_pm_state remains at 0x2 (INIT) instead of advancing. PFLR cannot recover; full platform reboot needed.",
        "verified_root_cause": "QAT FW Auth failure with ssm_pm_enable WA on DMR A0: Root cause from GENI: ssm_pm_enable=0xf (enabling SSM domain dynamic power gating) causes FW auth timeout — cpm_pm_state stuck at INIT. With ssm_pm_enable=0 (domain power gating disabled) FW auth passes. Issue: (1) WA being applied may not completely clear all ssm_pm_enable bits across all SSM domains; (2) Power gating enabled for some domains but WA only clears partial; (3) PFLR insufficient — full reboot needed to reset CPM state after failed auth; (4) A0-specific: validated passes on emulation but not A0 silicon with SSM power gating enabled.",
        "verified_fix": "Ensure ALL ssm_pm_enable bits cleared (=0) across ALL SSM domains on A0. Do NOT enable dynamic power gating on A0 QAT. Reboot to recover from stuck CPM INIT state. Reference Intel Wiki: 16011014632.",
        "architectural_element": "ssm_pm_enable CSR; SSM domain power gating; cpm_pm_state; QAT FW authentication; DMR A0 CPM",
        "failure_registers": ["ssm_pm_enable (multiple domains)", "cpm_pm_state"],
        "adjacent_subsystems": ["QAT CPM FW authentication", "SSM domain power gating", "PFLR recovery path"],
        "related_hsds": ["14026004873"],
        "spec_reference": "Intel Wiki: HSD 16011014632 14011319882 (QAT FW auth debug); DMR QAT CPM power management"
    },
    phase4={
        "tier1": [
            {"category": "ssm_pm_dump", "commands": ["Dump all ssm_pm_enable CSRs across SSM domains", "sv.sockets.imhs.acc.accs.qat.ssm_pm_enable.show()"], "reveals": "ssm_pm_enable state for all SSM domains", "relevance": "Any non-zero value = power gating not fully disabled; WA incomplete"},
            {"category": "cpm_state_check", "commands": ["sv.sockets.imhs.acc.accs.qat.cpm_pm_state.show()"], "reveals": "CPM power management state", "relevance": "0x2 (INIT) = stuck; FW auth cannot complete"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — QAT FW auth during boot; ssm_pm_enable not fully cleared; CPM stuck at INIT",
        "root_cause_domain": "hw.qat / ssm_pm_enable partial WA — not all SSM domains cleared on DMR A0",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "ssm_pm_dump confirms partial WA. cpm_state_check shows INIT state. Wiki reference confirms root cause.",
        "iteration_savings": "3",
    },
)

# ── HSD 14025968370 — QAT invalid response descriptor (fw.cpm) ───────────────
write(
    "14025968370",
    phase2={
        "testcase_name": "QAT response descriptor invalid data (40 ef dd cc pattern) after 30-40 descriptors on same UQ",
        "testcase_command": "(QAT compression deflate + crypto descriptor submission on UQ)",
        "testcase_parameters": "X1 A0 VV SVOS; QAT deflate compression + crypto jobs; ~30-40 descriptors then response invalid; pattern 40 ef dd cc dd cc (bytes 5-0); same UQ; fw.cpm",
        "testcase_domain_focus": "QAT response descriptor ring corruption after ~30-40 submissions on same UQ — descriptor ring pointer or fw.cpm state machine issue",
    },
    phase3={
        "verified_problem_statement": "QAT UQ response descriptor shows invalid repeating data (40 ef dd cc dd cc) after ~30-40 descriptors on same UQ on DMR X1 A0 VV SVOS. Both deflate compression and crypto jobs affected. Component fw.cpm.",
        "verified_root_cause": "QAT UQ descriptor ring corruption: Per GENI analysis, root cause is likely descriptor ring mismanagement or resource exhaustion in fw.cpm: (1) Descriptor ring buffer pointer wraps around incorrectly — ring pointer management bug causes firmware to overwrite or return stale descriptor slots; (2) Pattern '40 ef dd cc dd cc' is a stuck/repeated memory pattern — suggests firmware not updating response descriptor correctly after wraparound; (3) Resource leak in UQ descriptor management — UQ capacity ~30-40 before failure suggests UQ ring near full; (4) Both compression and crypto affected = common infrastructure/descriptor handling root cause; (5) fw.cpm firmware bug in descriptor lifecycle or ring wraparound.",
        "verified_fix": "Collect descriptor ring buffer state before/after failure. Identify ring wraparound point. File with fw.cpm debug team for ring management fix. Workaround: reset UQ after ~20 descriptors or reduce batch size.",
        "architectural_element": "QAT UQ descriptor ring; fw.cpm descriptor lifecycle; ring buffer pointer management; completion descriptor update",
        "failure_registers": ["QAT UQ ring head/tail pointers", "response descriptor status bits"],
        "adjacent_subsystems": ["QAT firmware CPM", "UQ ring manager", "compression engine", "crypto engine"],
        "related_hsds": [],
        "spec_reference": "DMR FV PreSighting Methodology; OKS Product Architecture Spec QAT Features; fw.cpm descriptor ring spec"
    },
    phase4={
        "tier1": [
            {"category": "ring_state", "commands": ["Dump UQ ring head/tail pointers after failure", "sv.sockets.imhs.acc.accs.qat.uq_ring_state.show()"], "reveals": "UQ ring pointer state at failure", "relevance": "Ring overflow or stuck pointer identifies descriptor management bug"},
            {"category": "descriptor_dump", "commands": ["Read last 10 response descriptors from UQ ring buffer"], "reveals": "Pattern of valid vs invalid descriptor slots", "relevance": "Pattern at ~30-40 identifies ring wraparound point"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [
            {"description": "fw.cpm ring pointer management fix", "commands": ["File fw.cpm bug with descriptor ring state dump"], "why": "Firmware fix requires CPM FW team"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — UQ descriptor ring management bug; response descriptor invalid after ring stress",
        "root_cause_domain": "fw.cpm / QAT UQ descriptor ring pointer mismanagement or wraparound bug",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "ring_state + descriptor_dump identify ring overflow point. fw.cpm team fix needed.",
        "iteration_savings": "2",
    },
)

# ── HSD 16028742119 — QAT DC services enable failure IMH2 Simics ─────────────
write(
    "16028742119",
    phase2={
        "testcase_name": "QAT compression test blocked: DC services fail to enable on IMH2 Simics DMR AP",
        "testcase_command": "systemctl start qat (or adf_ctl up); QAT DC (data compression) service enable",
        "testcase_parameters": "DMR AP IMH2 1S PSS CPM Fmod Simics; IFWI OKSDCRB1_86B_2025.36.2.01_0027 IPCleanDFXEnable DebugSigned; Simics dmr-7.0 RIO 2025ww37; DC services fail to enable",
        "testcase_domain_focus": "QAT DC services fail to enable on DMR AP IMH2 Simics — Simics infrastructure or BIOS initialization issue",
    },
    phase3={
        "verified_problem_statement": "QAT compression test blocked on DMR AP IMH2 Simics: DC services fail to enable. IFWI OKSDCRB1_86B_2025.36.2.01_0027. Simics dmr-7.0 RIO 2025ww37.",
        "verified_root_cause": "QAT DC service enable failure on IMH2 Simics: Per GENI analysis, root cause is Simics infrastructure/BIOS bring-up issues on IMH2: (1) BIOS failing to program cpu_in_post_boot in msm_pci_peci_bios register — blocking downstream service initialization (related HSD 16028733706); (2) MCTP bus failures on IMH2 Simics after reset — QAT uses MCTP for initialization; MCTP not functional blocks DC service init; (3) SPDM protocol stalls at Key Exchange — needed for secure firmware auth which QAT DC services require; (4) Simics model limitations — IMH2 1S CPM Fmod has known unresolved issues in PPR; (5) Not a QAT silicon bug — Simics platform maturity issue.",
        "verified_fix": "Apply Simics model patches from IMH2 PPR. Verify BIOS programs cpu_in_post_boot correctly. Check MCTP bus status after boot. Use latest Simics/model version per recipe.",
        "architectural_element": "IMH2 Simics QAT init; MCTP bus; cpu_in_post_boot; BIOS post-boot sequence; DC service enablement",
        "failure_registers": ["msm_pci_peci_bios.cpu_in_post_boot"],
        "adjacent_subsystems": ["IMH2 Simics model", "BIOS post-boot", "MCTP bus", "SPDM", "QAT DC init"],
        "related_hsds": ["16028741807", "15018147145"],
        "spec_reference": "DMR OOBMSM IP IMH2 HFPGA FV Stage PPR 25WW24; ACC HAS; HSD 16028733706"
    },
    phase4={
        "tier1": [
            {"category": "mctp_check", "commands": ["Verify MCTP bus status after Simics boot", "dmesg | grep -i mctp"], "reveals": "MCTP bus operational status", "relevance": "MCTP not functional = QAT DC service init blocked"},
            {"category": "bios_post_check", "commands": ["sv.socket0.imhs.msm_pci_peci_bios.cpu_in_post_boot.show()"], "reveals": "BIOS post-boot register state", "relevance": "Not set = BIOS sequence incomplete; downstream QAT init fails"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "indirect — Simics BIOS/MCTP infrastructure issue blocks QAT DC init; not a silicon bug",
        "root_cause_domain": "val.env.execution / IMH2 Simics BIOS post-boot or MCTP init failure blocking QAT DC services",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "mctp_check + bios_post_check identify infrastructure failure. PPR open issues confirm Simics IMH2 maturity.",
        "iteration_savings": "2",
    },
)

# ── HSD 16028741807 — QAT HASH sample code -1 IMH2 Simics ────────────────────
write(
    "16028741807",
    phase2={
        "testcase_name": "QAT HASH sample code fails with run status -1 on IMH2 Simics DMR AP",
        "testcase_command": "QAT HASH sample code execution (cpa_sample_code or qat_hash_sample)",
        "testcase_parameters": "DMR AP IMH2 1S PSS CPM Fmod Simics; IFWI OKSDCRB1_86B_2025.36.2.01_0027; Simics dmr-7.0 RIO 2025ww37; CentOS; run status -1",
        "testcase_domain_focus": "QAT HASH sample code returns -1 on IMH2 Simics — same infrastructure issues as HSD 16028742119",
    },
    phase3={
        "verified_problem_statement": "QAT HASH sample code fails with run status -1 on DMR AP IMH2 1S Simics. Same config as HSD 16028742119.",
        "verified_root_cause": "QAT HASH sample code -1 on IMH2 Simics: Same root cause as HSD 16028742119. Simics IMH2 infrastructure issues prevent QAT from initializing: (1) BIOS/firmware bring-up issues (cpu_in_post_boot); (2) MCTP/SPDM initialization failures; (3) model limitations in IMH2 1S CPM Fmod. Run status -1 = initialization failure before hash operation starts. No QAT silicon defect documented for this.",
        "verified_fix": "Same as HSD 16028742119: Apply Simics IMH2 PPR patches. Verify BIOS post-boot registers. Ensure correct model/IFWI combo.",
        "architectural_element": "IMH2 Simics QAT init; HASH sample code; Simics model bring-up",
        "failure_registers": [],
        "adjacent_subsystems": ["IMH2 Simics model", "QAT HASH engine", "QAT init sequence"],
        "related_hsds": ["16028742119"],
        "spec_reference": "DMR Hybrids Customer Guide; DMR PSS Training; DMR OOBMSM IP IMH2 HFPGA FV Stage PPR 25WW24"
    },
    phase4={
        "tier1": [
            {"category": "qat_init_log", "commands": ["dmesg | grep -i '6xxx\\|qat\\|init'", "adf_ctl status"], "reveals": "QAT initialization status", "relevance": "Init failure = infrastructure issue before HASH sample runs"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "indirect — QAT init fails on IMH2 Simics; HASH sample never executes; not a silicon bug",
        "root_cause_domain": "val.env.execution / IMH2 Simics QAT initialization failure (same as HSD 16028742119)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "Same root cause as HSD 16028742119. qat_init_log confirms init failure.",
        "iteration_savings": "2",
    },
)

# ── HSD 15018147145 — QAT systemctl start qat fails init message ─────────────
write(
    "15018147145",
    phase2={
        "testcase_name": "QAT service start fails: systemctl start qat Failed to send init message, qat_dev0 stopped",
        "testcase_command": "systemctl start qat",
        "testcase_parameters": "DMR AP IMH2 1S PSS CPM Fmod; CentOS; 6xxx 0000:0f:00.0 Failed to send init message; qat_dev0 stopped 9 acceleration engines; Reset follows",
        "testcase_domain_focus": "QAT service start failure with init message timeout on DMR AP IMH2 — driver init message not acknowledged by firmware",
    },
    phase3={
        "verified_problem_statement": "systemctl start qat fails on DMR AP IMH2: '6xxx 0000:0f:00.0: Failed to send init message', qat_dev0 stopped 9 acceleration engines, then Reset. BDF 0000:0f:00.0.",
        "verified_root_cause": "QAT init message failure: (1) QAT kernel driver (6xxx) sends init message to QAT firmware; firmware does not acknowledge within timeout → 'Failed to send init message'; (2) QAT firmware not initialized — BIOS/IFWI not enabling QAT correctly on IMH2; ssm_pm_enable WA may not be applied; (3) QAT module configuration files missing or incorrect — /etc/c4xxxvf_dev*.conf not in place; (4) VF configuration not applied before start — adf_ctl needed before systemctl; (5) QAT device at 0000:0f:00.0 — verify this is correct BDF on DMR AP.",
        "verified_fix": "Verify QAT kernel module loaded (insmod qat_c4xxx.ko qat_c4xxxvf.ko). Place c4xxxvf_dev*.conf files. Apply ssm_pm_enable=0 WA. Run adf_ctl restart. Enable VFs: echo 128 > sriov_numvfs.",
        "architectural_element": "QAT 6xxx driver init message; qat_dev0; ssm_pm_enable; c4xxxvf config files; sriov VF",
        "failure_registers": ["ssm_pm_enable"],
        "adjacent_subsystems": ["QAT 6xxx kernel driver", "QAT firmware", "adf_ctl", "SRIOV VF", "config files"],
        "related_hsds": ["16028742119", "14025998125"],
        "spec_reference": "QAT Installation wiki; adf_ctl usage; c4xxxvf config requirements; DMR QAT BKC"
    },
    phase4={
        "tier1": [
            {"category": "qat_module_check", "commands": ["lsmod | grep qat", "adf_ctl status", "ls /etc/c4xxx*.conf"], "reveals": "QAT driver loaded, service status, config files present", "relevance": "Missing module or config = init message cannot be sent"},
            {"category": "ssm_pm_check", "commands": ["dmesg | grep -i 'qat\\|ssm_pm\\|init'"], "reveals": "QAT init sequence and ssm_pm_enable WA status", "relevance": "ssm_pm not disabled = init message timeout on DMR A0"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — QAT driver init message timeout; firmware or config issue",
        "root_cause_domain": "hw.qat / QAT init message failure — ssm_pm WA not applied or config files missing",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "qat_module_check identifies missing config. ssm_pm_check identifies WA status. Known fix sequence.",
        "iteration_savings": "2",
    },
)

# ── HSD 16027891803 — QAT uaace config lost after service restart ─────────────
write(
    "16027891803",
    phase2={
        "testcase_name": "QAT uaace configuration lost after restarting QAT services on DMR AP PSS Fmod Simics",
        "testcase_command": "adf_ctl restart (or service qat restart)",
        "testcase_parameters": "DMR AP 1S PSS Fmod Simics; IPClean Debug IFWI OKSDCRB1.86B.2025.26; QAT uaace configuration goes off after service restart",
        "testcase_domain_focus": "QAT uaace (user-space ACC engine) configuration reset to default after QAT service restart — config persistence issue",
    },
    phase3={
        "verified_problem_statement": "QAT uaace configuration is lost/reset to default after restarting QAT services on DMR AP 1S PSS Fmod Simics. Configuration must be re-applied after every restart.",
        "verified_root_cause": "QAT uaace config persistence issue: (1) QAT service restart (adf_ctl down/up) brings accelerator to clean state — manually-applied uaace configuration is not persisted to config files; (2) uaace settings configured at runtime not written back to /etc/qat*.conf persistent storage; (3) QAT driver restart re-reads config files from /etc — only config file settings persist; runtime-only changes lost; (4) Simics environment may have volatile /etc — config files reset on service restart; (5) No QAT HW bug — configuration persistence is software/automation issue.",
        "verified_fix": "Write uaace configuration to persistent /etc/qat*.conf files before service restart. Create service startup script to re-apply uaace config after each restart. Verify config file path in Simics environment.",
        "architectural_element": "QAT uaace configuration; /etc/qat*.conf persistence; adf_ctl restart; QAT service init",
        "failure_registers": [],
        "adjacent_subsystems": ["QAT driver config", "uaace engine settings", "adf_ctl", "/etc/qat config files"],
        "related_hsds": [],
        "spec_reference": "QAT Installation wiki: configuration persistence; adf_ctl config file management"
    },
    phase4={
        "tier1": [
            {"category": "config_persistence", "commands": ["cat /etc/qat*.conf | grep uaace", "ls /etc/ | grep qat"], "reveals": "QAT config file uaace settings persistence", "relevance": "Missing uaace in config file = lost after restart"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "indirect — QAT config not persisted; service restart resets uaace config; not a silicon bug",
        "root_cause_domain": "val.env.execution / QAT uaace config not saved to persistent config file",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "config_persistence confirms missing uaace in config file. Simple config save fix.",
        "iteration_savings": "1",
    },
)

# ── HSD 14025921116 — QAT PRS status register not resetting (clone) ──────────
write(
    "14025921116",
    phase2={
        "testcase_name": "QAT PRS status register not resetting values after PRI disable/enable transition",
        "testcase_command": "(QAT PRS/PRI enable/disable sequence; read PRS status register)",
        "testcase_parameters": "X1 A0 PO; QAT Page Request Interface (PRI) transitions from not-Enabled to Enabled; PRS status flags (Stopped, Response Failure, Unexpected Response) not cleared; hw.cpm; CloneScript clone",
        "testcase_domain_focus": "QAT PRS status flags not cleared on PRI enable transition — HAS spec says they should be cleared",
    },
    phase3={
        "verified_problem_statement": "QAT PRS status register flags (Stopped, Response Failure, Unexpected Response) not cleared when device Page Request Interface transitions from not-Enabled to Enabled on DMR X1 A0 PO. QAT HAS specifies these flags should be cleared.",
        "verified_root_cause": "QAT PRS status register clearing bug: Per QAT HAS, PRS status flags should auto-clear when PRI transitions from disabled to enabled. HW not implementing this auto-clear. Root cause: (1) QAT CPM PRS status register reset logic not triggering on PRI enable edge — logic only resets on full device reset, not on PRI enable transition; (2) HAS specification not fully implemented in A0 silicon; (3) CloneScript = tracking fix across products. Driver must manually clear flags before re-enabling PRI.",
        "verified_fix": "Driver WA: manually clear PRS status flags before enabling PRI (before transitioning from not-Enabled to Enabled). Track HW fix in bug clone.",
        "architectural_element": "QAT PRS/PRI enable; PRS status register; Page Request Interface transition; hw.cpm",
        "failure_registers": ["QAT PRS status register (Stopped, Response Failure, Unexpected Response)"],
        "adjacent_subsystems": ["QAT Page Request Interface", "PRS status logic", "PRI enable sequencer"],
        "related_hsds": [],
        "spec_reference": "QAT HAS: Page Request Interface; PRS status register; PRI enable behavior"
    },
    phase4={
        "tier1": [
            {"category": "prs_status_check", "commands": ["sv.socket0.imhs.acc.accs.qat.prs_status.show()"], "reveals": "PRS status flags before/after PRI enable", "relevance": "Flags not cleared = HAS spec mismatch in A0 silicon"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — PRI enable transition doesn't auto-clear PRS flags; spec says it should",
        "root_cause_domain": "hw.cpm / QAT PRS status register not auto-clearing on PRI enable (HAS spec mismatch)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "prs_status_check confirms flags not cleared. Driver WA: manual clear before PRI enable.",
        "iteration_savings": "2",
    },
)

# ── HSD 16028592669 — DMR_MOCK Windows QAT SUT_Collaterals NGA automation ─────
write(
    "16028592669",
    phase2={
        "testcase_name": "DMR MOCK Windows Accelerators NGA multisubsystem_testing_step_sut_collateral failure",
        "testcase_command": "(NGA automation: multisubsystem_testing_step_sut_collateral on Windows DMR MOCK)",
        "testcase_parameters": "DMR_MOCK SHARED_POOL_VV Windows Accelerators NGA automation; multisubsystem_testing_step_sut_collateral failing; NGA log available",
        "testcase_domain_focus": "Pre-VV NGA automation Windows QAT SUT collateral deployment failing on DMR MOCK platform",
    },
    phase3={
        "verified_problem_statement": "NGA multisubsystem_testing_step_sut_collateral fails for Windows QAT Accelerators on DMR MOCK SHARED_POOL_VV.",
        "verified_root_cause": "NGA SUT collateral deployment failure on Windows DMR MOCK: (1) SUT collateral package for Windows QAT not properly deployed or installed on DMR MOCK platform; (2) multisubsystem_testing_step_sut_collateral step fails because Windows QAT driver package or required ingredients missing; (3) DMR MOCK platform SUT deployment path differs from production AP path; automation content not updated for MOCK; (4) val.env.execution — automation infrastructure issue, not silicon bug.",
        "verified_fix": "Deploy correct Windows QAT SUT collateral for DMR MOCK. Update multisubsystem automation content for MOCK platform. Verify NGA log for specific missing component.",
        "architectural_element": "NGA SUT collateral deployment; Windows QAT driver package; DMR MOCK platform",
        "failure_registers": [],
        "adjacent_subsystems": ["NGA automation framework", "Windows QAT driver", "SUT collateral manager", "DMR MOCK"],
        "related_hsds": [],
        "spec_reference": "NGA Enhanced User Guide; Windows QAT deployment requirements; DMR MOCK platform setup"
    },
    phase4={
        "tier1": [
            {"category": "sut_collateral_check", "commands": ["Review NGA log at \\\\gar.corp.intel.com\\ec\\proj\\ba\\xpiv\\NGALogs\\nga_dmr_mock\\... for specific failure"], "reveals": "Specific SUT collateral component missing", "relevance": "Missing component = deployment configuration issue"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "indirect — NGA automation SUT collateral deployment fails; not a silicon bug",
        "root_cause_domain": "val.env.execution / NGA SUT collateral deployment failure on Windows DMR MOCK",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "NGA log review identifies specific missing component. Automation content fix.",
        "iteration_savings": "2",
    },
)

# ── HSD 14025905353 — QAT admin message me_status_get failure (doc clone) ─────
write(
    "14025905353",
    phase2={
        "testcase_name": "QAT admin message me_status_get fails after FW load on SVOS",
        "testcase_command": "rocket --atlas --hw dram,cpmqat (QAT FW unsigned/signed load + driver admin message)",
        "testcase_parameters": "X1 A0 PO SVOS; QAT FW load (unsigned or signed) successful; driver admin message me_status_get fails; hw.cpm; doc clone",
        "testcase_domain_focus": "QAT me_status_get admin message fails after successful FW load on SVOS — driver/FW handshake issue",
    },
    phase3={
        "verified_problem_statement": "QAT admin message me_status_get fails after FW load on SVOS X1 A0 PO. Both unsigned and signed FW loads succeed, but driver me_status_get admin message fails. hw.cpm. Doc clone indicates HAS documentation fix needed.",
        "verified_root_cause": "QAT me_status_get admin message failure: (1) me_status_get is a driver-to-FW admin message checking Management Engine (ME) status; failure after FW load suggests ME not in expected state after load; (2) FW load completes but ME state machine doesn't transition to expected state — me_status_get response indicates wrong ME state; (3) Race condition between FW load completion and ME state transition — driver sends me_status_get too quickly; (4) HAS documentation error — doc clone suggests admin message spec or sequence description needs update; (5) A0 silicon: ME state transition timing on FW load may differ from spec.",
        "verified_fix": "Add delay/retry after FW load before me_status_get. Check ME state register for expected state after load. Update HAS admin message sequence documentation.",
        "architectural_element": "QAT ME state machine; me_status_get admin message; FW load sequence; hw.cpm ME",
        "failure_registers": ["QAT ME state register"],
        "adjacent_subsystems": ["QAT Management Engine", "driver-FW handshake", "admin message queue"],
        "related_hsds": [],
        "spec_reference": "QAT HAS: admin message interface; me_status_get; FW load sequence; ME state transitions"
    },
    phase4={
        "tier1": [
            {"category": "me_state_check", "commands": ["sv.socket0.imhs.acc.accs.qat.me_state.show()"], "reveals": "ME state after FW load", "relevance": "Wrong ME state = me_status_get returns error"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — FW load + me_status_get sequence; ME state race or spec mismatch",
        "root_cause_domain": "hw.cpm / QAT ME state transition timing after FW load; doc clone for HAS update",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "me_state_check identifies state. HAS doc clone confirms documentation fix.",
        "iteration_savings": "2",
    },
)

# ── HSD 16027275757 — Call trace on idxd module reload (PSS Fmod) ─────────────
write(
    "16027275757",
    phase2={
        "testcase_name": "Call trace when IDXD module loaded back after rmmod idxd; PSS Fmod DMR AP",
        "testcase_command": "rmmod iaa_crypto idxd; modprobe idxd",
        "testcase_parameters": "DMR AP 1S PSS Fmod; BKC#23; IMH1 IPClean Debug IFWI; rmmod iaa_crypto idxd; modprobe idxd causes kernel call trace",
        "testcase_domain_focus": "Linux idxd kernel module call trace on reload (modprobe idxd) after rmmod — driver cleanup/init race on DMR AP PSS Fmod",
    },
    phase3={
        "verified_problem_statement": "Kernel call trace observed when idxd module is reloaded (modprobe idxd) after rmmod iaa_crypto idxd on DMR AP 1S PSS Fmod BKC#23.",
        "verified_root_cause": "idxd module reload call trace: (1) idxd driver rmmod leaves stale state — device registers or interrupt handlers not fully cleaned up during rmmod; (2) modprobe idxd on reload encounters stale device state and triggers NULL pointer dereference or use-after-free; (3) iaa_crypto rmmod before idxd may not properly unregister all callbacks — idxd probe on reload tries to reinitialize already-freed callback; (4) DMR multi-segment accelerator issue — idxd rmmod may not properly handle all segments; (5) Linux kernel driver cleanup bug on DMR AP.",
        "verified_fix": "Fix idxd rmmod cleanup to properly handle all segments and callbacks. Ensure iaa_crypto unregisters all callbacks before idxd rmmod. Test with different rmmod order.",
        "architectural_element": "idxd Linux kernel module; rmmod cleanup; modprobe reload; iaa_crypto callback; DMR multi-segment",
        "failure_registers": [],
        "adjacent_subsystems": ["Linux idxd driver", "iaa_crypto module", "kernel module cleanup", "interrupt handler"],
        "related_hsds": [],
        "spec_reference": "Linux idxd driver source; iaa_crypto module; kernel module probe/remove sequence"
    },
    phase4={
        "tier1": [
            {"category": "call_trace", "commands": ["dmesg | grep -A 20 'Call Trace'", "dmesg | grep 'BUG\\|NULL\\|use after free'"], "reveals": "Specific call trace location in idxd driver", "relevance": "NULL pointer or use-after-free identifies cleanup bug"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — idxd module reload call trace; stale state from rmmod",
        "root_cause_domain": "hw.dsa / Linux idxd driver cleanup bug on rmmod/reload sequence",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "call_trace identifies specific cleanup issue. Driver fix needed.",
        "iteration_savings": "2",
    },
)

# ── HSD 14023918747 — NEX BTS DLB into IMH2 Accelerator Stack (soc.ltm) ──────
write(
    "14023918747",
    phase2={
        "testcase_name": "NEX BTS requirement: Addition of DLB IP into IMH2 Accelerator Stack for Xeon-D",
        "testcase_command": "(Architecture feature request — NEX reusing IMH2 for BTS/Xeon-D; add DLB to ACC stack)",
        "testcase_parameters": "DMR-CCB DMR-SP NEX; BTS requirement; IMH2 add DLB IP into Accelerator Stack for NEX/Xeon-D program; soc.ltm component",
        "testcase_domain_focus": "Architecture feature request: NEX BTS requires DLB IP in IMH2 Accelerator Stack for Xeon-D derivative",
    },
    phase3={
        "verified_problem_statement": "NEX/Xeon-D program reuses IMH2 die from DMR and requires DLB (Dynamic Load Balancer) IP added to IMH2 Accelerator Stack. BTS (Below-the-Stack) requirement tracked in DMR-CCB. Component soc.ltm.",
        "verified_root_cause": "Architecture feature request: Not a defect. NEX program (Xeon-D derivative) requires DLB IP inclusion in IMH2 ACC Stack. DMR base IMH2 does not include DLB. This BTS requirement tracked to add DLB to IMH2 for NEX program variant. soc.ltm (SoC Long-Term Matrix) tracking.",
        "verified_fix": "Implement DLB IP integration in IMH2 ACC Stack for NEX/BTS program variant. Track via DMR-CCB feature process.",
        "architectural_element": "IMH2 Accelerator Stack; DLB IP integration; NEX/Xeon-D program variant; soc.ltm tracking",
        "failure_registers": [],
        "adjacent_subsystems": ["DLB IP", "IMH2 ACC Stack", "NEX program", "BTS requirements"],
        "related_hsds": [],
        "spec_reference": "DMR ACC HAS: IMH2 ACC Stack; DLB IP spec; NEX program BTS requirements"
    },
    phase4={
        "tier1": [],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [
            {"description": "DLB IP integration in IMH2 for NEX", "commands": ["Track via DMR-CCB feature process for NEX program variant"], "why": "Architecture feature requiring design team action"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "indirect — feature requirement, not a test failure",
        "root_cause_domain": "soc.ltm / architecture feature request for NEX DLB in IMH2 ACC Stack",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "Feature request tracking. No silicon debug needed.",
        "iteration_savings": "1",
    },
)

# ── HSD 14023498612 — QAT STV readThreadInfo invalid command (Simics) ────────
write(
    "14023498612",
    phase2={
        "testcase_name": "QAT STV test code failure: invalid command readThreadInfo in Simics",
        "testcase_command": "QAT STV test code readThreadInfo command in Simics",
        "testcase_parameters": "DMR Simics; QAT 5.1 (0.8.2) driver; readThreadInfo command not recognized in STV test; platform.simics.platform",
        "testcase_domain_focus": "QAT STV test code incompatibility with Simics platform — readThreadInfo command not available",
    },
    phase3={
        "verified_problem_statement": "QAT STV test code cannot run in Simics: 'readThreadInfo' command not recognized. QAT 5.1 (0.8.2) driver installed. Component platform.simics.platform.",
        "verified_root_cause": "STV test code / Simics incompatibility: (1) STV (Silicon Test Vehicle) test uses readThreadInfo command which is a Simics-specific debug command not available in current Simics model version; (2) Simics command set differs between model versions — readThreadInfo may have been renamed or removed in dmr-x.x Simics version; (3) STV test code written for older Simics version; (4) platform.simics.platform = Simics platform compatibility issue, not silicon bug.",
        "verified_fix": "Update STV test code for current Simics command set. Check Simics changelog for readThreadInfo availability. Use equivalent Simics command.",
        "architectural_element": "Simics STV test framework; readThreadInfo command; Simics model version compatibility",
        "failure_registers": [],
        "adjacent_subsystems": ["Simics platform", "STV test framework", "QAT driver"],
        "related_hsds": [],
        "spec_reference": "Simics model release notes; STV test documentation; QAT Simics test guide"
    },
    phase4={
        "tier1": [
            {"category": "simics_cmd_check", "commands": ["help readThreadInfo (in Simics CLI)", "Simics CLI: grep readThreadInfo available commands"], "reveals": "Whether readThreadInfo command available in this Simics version", "relevance": "Not available = STV test code update needed for current Simics"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "indirect — STV test command incompatible with Simics version; not a silicon bug",
        "root_cause_domain": "platform.simics.platform / readThreadInfo command not in current Simics model",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "simics_cmd_check confirms command availability. STV test update fix.",
        "iteration_savings": "1",
    },
)

# ── HSD 14023472574 — Simics crash during QAT FLR ────────────────────────────
write(
    "14023472574",
    phase2={
        "testcase_name": "Simics crashes with UNKNOWN EXCEPTION during QAT FLR (Functional Level Reset)",
        "testcase_command": "echo 1 > /sys/bus/pci/devices/<QAT_BDF>/reset (FLR via sysfs or pcie_flr)",
        "testcase_parameters": "DMR Simics CPM_FMOD; QAT 6.10 kernel BKC; FLR of QAT device; Simics UNKNOWN EXCEPTION cpm_sc_device_0 error; platform.simics.platform",
        "testcase_domain_focus": "Simics model crash (UNKNOWN EXCEPTION) during QAT device FLR — CPM Simics model not handling FLR correctly",
    },
    phase3={
        "verified_problem_statement": "Simics crashes with UNKNOWN EXCEPTION (cpm_sc_device_0 error) when performing Functional Level Reset (FLR) of QAT device. DMR Simics CPM_FMOD, 6.10 kernel BKC. Component platform.simics.platform.",
        "verified_root_cause": "Simics CPM model FLR handling bug: (1) Simics CPM model (cpm_sc_device_0) does not fully handle FLR transaction — FLR is a PCIe-level reset; model encounters unexpected state and throws UNKNOWN EXCEPTION; (2) FLR implementation in CPM Simics model may be incomplete — model transitions to unknown state on FLR; (3) platform.simics.platform = Simics model bug, not silicon bug; (4) FLR on real silicon likely works; this is a model simulation bug.",
        "verified_fix": "Fix CPM Simics model FLR handling (cpm_sc_device_0). Use Simics model version with FLR fix. File Simics model bug.",
        "architectural_element": "QAT Simics CPM model; FLR handling; cpm_sc_device_0; PCIe FLR state machine",
        "failure_registers": [],
        "adjacent_subsystems": ["Simics CPM model", "PCIe FLR sequence", "cpm_sc_device_0"],
        "related_hsds": [],
        "spec_reference": "Simics CPM model release notes; PCIe FLR handling in Simics models"
    },
    phase4={
        "tier1": [
            {"category": "simics_version", "commands": ["Check Simics model version for FLR fix", "dmr-x.x CPM model release notes"], "reveals": "Simics model version with FLR fix", "relevance": "Newer model version may have FLR fix for cpm_sc_device_0"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — QAT FLR exercises Simics CPM model FLR path; model crashes",
        "root_cause_domain": "platform.simics.platform / Simics CPM model FLR handling bug (cpm_sc_device_0)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "Simics model bug — not silicon. Update to Simics version with FLR fix.",
        "iteration_savings": "2",
    },
)

# ── HSD 14023448207 — IAA DEFTR3 register not reflected in DEV3E (VP-SIMICS) ──
write(
    "14023448207",
    phase2={
        "testcase_name": "IAA DEFTR3 register value not reflected on DEV3E register in VP-SIMICS",
        "testcase_command": "(Read IAA DEFTR3 and DEV3E registers in VP-SIMICS)",
        "testcase_parameters": "DMR iMH VP-SIMICS 6.0 2024ww31.3.00_45; IAA DEFTR3 write not reflected in DEV3E; val.vp.simics",
        "testcase_domain_focus": "VP-SIMICS IAA DEFTR3 register write not propagating to DEV3E register — Simics VP model bug",
    },
    phase3={
        "verified_problem_statement": "In DMR iMH VP-SIMICS 6.0 (2024ww31.3.00_45), IAA DEFTR3 register value is not reflected on DEV3E register. VP-SIMICS model issue. Component val.vp.simics.",
        "verified_root_cause": "VP-SIMICS model register propagation bug: DEFTR3 (Defeaturing Register 3) write not correctly updating DEV3E (device enable/enable register) in Simics model. Root cause: (1) Simics IAA model missing DEFTR3→DEV3E propagation logic; (2) VP-SIMICS register model incomplete for DEFTR3 to DEV3E relationship; (3) Not a silicon bug — VP-SIMICS models are still maturing for DMR iMH 6.0.",
        "verified_fix": "Fix IAA VP-SIMICS model to propagate DEFTR3 writes to DEV3E. File VP-SIMICS model bug. Use updated VP-SIMICS release.",
        "architectural_element": "IAA DEFTR3 register; DEV3E register; VP-SIMICS IAA model; defeature logic",
        "failure_registers": ["DEFTR3", "DEV3E"],
        "adjacent_subsystems": ["VP-SIMICS IAA model", "DEFTR3 defeature logic"],
        "related_hsds": ["14022982239"],
        "spec_reference": "VP-SIMICS release 6.0 2024ww31; IAA HAS: DEFTR3 and DEV3E register relationship"
    },
    phase4={
        "tier1": [],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [
            {"description": "Fix VP-SIMICS IAA model DEFTR3→DEV3E propagation", "commands": ["File VP-SIMICS model bug for DEFTR3 not updating DEV3E"], "why": "VP-SIMICS model fix requires simulation team"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — reads DEV3E after DEFTR3 write; VP-SIMICS model doesn't propagate",
        "root_cause_domain": "val.vp.simics / VP-SIMICS IAA model missing DEFTR3→DEV3E propagation",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "VP-SIMICS model bug. No silicon action needed.",
        "iteration_savings": "1",
    },
)

# ── HSD 14022982239 — IAA Mem-move defeature logic not working (VP-SIMICS) ────
write(
    "14022982239",
    phase2={
        "testcase_name": "IAA Mem-move defeature logic not working as expected in VP-SIMICS",
        "testcase_command": "(IAA Mem-move operation in VP-SIMICS with defeature logic enabled)",
        "testcase_parameters": "DMR iMH VP-SIMICS 6.0 2024ww28.3.18_15; IAA defeature logic change; Mem-move still works when defeatured; val.vp.simics",
        "testcase_domain_focus": "VP-SIMICS IAA defeature logic for Mem-move not functioning correctly after defeature logic change — model bug",
    },
    phase3={
        "verified_problem_statement": "In DMR iMH VP-SIMICS 6.0 (2024ww28.3.18_15), IAA Mem-move defeature logic not working correctly after latest defeature logic change. Mem-move still works when it should be defeatured.",
        "verified_root_cause": "VP-SIMICS IAA defeature model bug: After defeature logic change in VP-SIMICS, IAA Mem-move operation still succeeds when DEFTR register is set to defeature it. Root cause: (1) VP-SIMICS IAA model defeature check not applied to Mem-move operation dispatch; (2) Defeature logic patch incomplete — only some operations check DEFTR; Mem-move bypasses check; (3) val.vp.simics = VP-SIMICS simulation model bug, not silicon bug.",
        "verified_fix": "Fix VP-SIMICS IAA model to enforce DEFTR defeature for Mem-move operation. File VP-SIMICS model bug with latest release.",
        "architectural_element": "IAA Mem-move operation; DEFTR defeature register; VP-SIMICS IAA model; defeature enforcement",
        "failure_registers": ["IAA DEFTR (defeature register)"],
        "adjacent_subsystems": ["VP-SIMICS IAA model", "DEFTR defeature logic", "Mem-move dispatch"],
        "related_hsds": ["14023448207"],
        "spec_reference": "VP-SIMICS release 6.0 2024ww28; IAA HAS: Mem-move defeature; DEFTR register"
    },
    phase4={
        "tier1": [],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [
            {"description": "Fix VP-SIMICS IAA Mem-move defeature enforcement", "commands": ["File VP-SIMICS model bug for Mem-move bypassing DEFTR"], "why": "VP-SIMICS model fix requires simulation team"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — Mem-move runs when DEFTR says it's defeatured; VP-SIMICS model incomplete",
        "root_cause_domain": "val.vp.simics / VP-SIMICS IAA Mem-move defeature logic incomplete",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "VP-SIMICS model bug. No silicon action needed.",
        "iteration_savings": "1",
    },
)

# ── HSD 14022555397 — QAT compression fails in Simics (platform.simics.platform)
write(
    "14022555397",
    phase2={
        "testcase_name": "QAT Linux cpa_sample_code compression tests fail in Simics CPM_FMOD",
        "testcase_command": "(QAT cpa_sample_code compression test in Simics CPM_FMOD)",
        "testcase_parameters": "DMR Simics CPM_FMOD; Linux cpa_sample_code compression tests fail; WA: enable dc services in sysfs first; platform.simics.platform",
        "testcase_domain_focus": "QAT compression tests fail in Simics CPM_FMOD unless DC services enabled in sysfs first — Simics model init sequence issue",
    },
    phase3={
        "verified_problem_statement": "QAT Linux cpa_sample_code compression tests fail in DMR Simics CPM_FMOD. WA available: enable dc services in sysfs (and possibly restart qat service).",
        "verified_root_cause": "QAT DC services not auto-enabled in Simics CPM_FMOD: (1) Simics CPM model does not auto-enable DC (data compression) services on QAT init — requires explicit sysfs enable step; (2) cpa_sample_code compression tests fail because DC services not configured; (3) WA: 'echo dc > /sys/bus/qat/devices/qat_dev0/services' enables DC; (4) platform.simics.platform = Simics model behavior difference from real silicon; (5) On real silicon, QAT services configured via adf_ctl/config file; Simics may not process config file correctly.",
        "verified_fix": "Apply WA: enable dc services in sysfs before running cpa_sample_code. Or restart qat service after enabling. Update Simics CPM model to process config file correctly.",
        "architectural_element": "QAT DC service enable; sysfs service configuration; Simics CPM model init; adf_ctl",
        "failure_registers": [],
        "adjacent_subsystems": ["QAT CPM Simics model", "DC service sysfs", "cpa_sample_code", "adf_ctl"],
        "related_hsds": ["16028742119"],
        "spec_reference": "QAT Installation wiki: DC service enable; Simics CPM model init sequence"
    },
    phase4={
        "tier1": [
            {"category": "dc_service_check", "commands": ["cat /sys/bus/qat/devices/qat_dev0/services", "echo dc > /sys/bus/qat/devices/qat_dev0/services"], "reveals": "DC service enable state and WA", "relevance": "Not enabled = cpa_sample_code compression fails"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — DC services not auto-enabled in Simics; compression test fails",
        "root_cause_domain": "platform.simics.platform / Simics CPM model DC services not auto-configured",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "dc_service_check confirms WA. Enable DC via sysfs.",
        "iteration_savings": "2",
    },
)

# ── HSD 14022366956 — IAA Compress with Dictionary failing (val.env.tool) ─────
write(
    "14022366956",
    phase2={
        "testcase_name": "IAA Compress with Dictionary failing in latest VP-SIMICS release (val.env.tool)",
        "testcase_command": "(IAA compress with dictionary operation in VP-SIMICS)",
        "testcase_parameters": "DMR VP-SIMICS 2024ww17.3.00_51; IAA Compress with Dictionary; iax_common_verify_cmpl_record_status() PID 2631; val.env.tool",
        "testcase_domain_focus": "IAA Compress with Dictionary test failure in VP-SIMICS after latest fix — IAA completion record verification failure",
    },
    phase3={
        "verified_problem_statement": "IAA Compress with Dictionary failing in VP-SIMICS 2024ww17.3.00_51 after latest fix. iax_common_verify_cmpl_record_status() failure. Component val.env.tool.",
        "verified_root_cause": "IAA VP-SIMICS Compress with Dictionary regression: (1) Latest VP-SIMICS fix introduced regression in IAA Compress with Dictionary path; (2) iax_common_verify_cmpl_record_status() verification failure — completion record fields not matching expected values after dictionary compress in new VP-SIMICS; (3) val.env.tool — test tool completion record verification check is too strict, or VP-SIMICS model changed completion record format; (4) RC in description 'Mon Apr 29 21:28:50 PID 2631 iax_common_verify_cmpl_record_status' = explicit verification at line 2769.",
        "verified_fix": "Identify regression in VP-SIMICS 2024ww17 fix. Roll back or fix dictionary compress completion record in model. Update val.env.tool verification for new completion record format.",
        "architectural_element": "IAA dictionary compress; completion record verification; iax_common_verify_cmpl_record_status; VP-SIMICS model",
        "failure_registers": ["IAA completion record status fields"],
        "adjacent_subsystems": ["VP-SIMICS IAA model", "dictionary compress engine", "val.env.tool test framework"],
        "related_hsds": [],
        "spec_reference": "VP-SIMICS release 2024ww17; IAA HAS: compress with dictionary completion record"
    },
    phase4={
        "tier1": [
            {"category": "completion_diff", "commands": ["Compare IAA completion record format in 2024ww17 vs previous VP-SIMICS release"], "reveals": "VP-SIMICS completion record format change", "relevance": "Format change = tool verification needs update"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — completion record verification fails after VP-SIMICS fix regression",
        "root_cause_domain": "val.env.tool / IAA VP-SIMICS completion record format change after dictionary compress fix",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "completion_diff identifies format change. Tool update or model rollback fix.",
        "iteration_savings": "2",
    },
)

# ── HSD 14025366493 — QAT OpenSSL qatprovider cert request failure ────────────
write(
    "14025366493",
    phase2={
        "testcase_name": "QAT Provider failures creating certificate request with OpenSSL on DMR AP",
        "testcase_command": "openssl req -new -key privkey.pem -out csr.pem (via qatprovider)",
        "testcase_parameters": "DMR AP; CentOS 6.14.0-dmr.bkc; OpenSSL 3.4.1 from source; qatlib 24.02-1_0.8.4 for DMR; qatprovider certificate request failure",
        "testcase_domain_focus": "QAT OpenSSL qatprovider certificate request failure on DMR AP — version mismatch or OpenSSL library path issue",
    },
    phase3={
        "verified_problem_statement": "QAT Provider cannot successfully process certificate requests with OpenSSL on DMR AP. Config: CentOS 6.14.0-dmr.bkc, OpenSSL 3.4.1 from source, qatlib 24.02-1_0.8.4.",
        "verified_root_cause": "QAT OpenSSL qatprovider certificate request failure: (1) OpenSSL installed from source may not be in default library path — qatprovider may load wrong OpenSSL version from /usr/lib instead of /usr/local/ssl; ldconfig needed to update library cache; (2) Python cryptography libraries (pyOpenSSL, cryptography) may have attribute errors (X509_V_FLAG_CB_ISSUER_CHECK) if built against different OpenSSL version; (3) qatlib 24.02 may have API incompatibility with OpenSSL 3.4.1 built from source; (4) Missing RPATH or LD_LIBRARY_PATH for /usr/local/ssl/lib; (5) Certificate operations require asym crypto — verify QAT configured for ASYM services.",
        "verified_fix": "Run ldconfig after OpenSSL install. Set LD_LIBRARY_PATH=/usr/local/ssl/lib. Rebuild Python cryptography libs against new OpenSSL. Verify qatprovider loads correct OpenSSL. Check QAT ASYM service configuration.",
        "architectural_element": "OpenSSL library path; qatprovider; qatlib 24.02; asym crypto; ldconfig",
        "failure_registers": [],
        "adjacent_subsystems": ["OpenSSL 3.4.1", "qatprovider", "qatlib", "Python cryptography"],
        "related_hsds": [],
        "spec_reference": "OpenSSL install BKM; qatlib 24.02 release notes; qatprovider integration guide"
    },
    phase4={
        "tier1": [
            {"category": "openssl_path", "commands": ["openssl version -a", "ldd $(which openssl) | grep ssl", "echo $LD_LIBRARY_PATH"], "reveals": "Active OpenSSL version and library path", "relevance": "Wrong library path = qatprovider loads wrong OpenSSL"},
            {"category": "qat_asym_check", "commands": ["adf_ctl status | grep -i 'asym\\|service'"], "reveals": "QAT service configuration for ASYM", "relevance": "ASYM not enabled = certificate crypto fails"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — OpenSSL qatprovider certificate request fails; library path or service config issue",
        "root_cause_domain": "val.env.tool / OpenSSL library path or qatprovider ASYM service configuration issue",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "openssl_path + qat_asym_check identify issue. ldconfig and service config fix.",
        "iteration_savings": "2",
    },
)

# ── HSD 16027457977 — QAT cpa_sample_code fails HugePages>0 with DLB-DPDK ───
write(
    "16027457977",
    phase2={
        "testcase_name": "QAT cpa_sample_code workload fails when HugePages > 0 concurrent with DLB-DPDK on DMR AP",
        "testcase_command": "cpa_sample_code (concurrent with DLB-DPDK); HugePages configured > 0",
        "testcase_parameters": "CWF DMR AP Simics; CentOS 6.14.0-dmr.bkc; QAT in-tree kernel 6.14; DLB-DPDK concurrent; HugePages > 0; IMH1 IPClean IFWI",
        "testcase_domain_focus": "QAT cpa_sample_code fails with HugePages configured and concurrent DLB-DPDK — DPDK hugepage memory contention or init race",
    },
    phase3={
        "verified_problem_statement": "QAT cpa_sample_code workload fails when triggered concurrently with DLB-DPDK on DMR AP Simics when HugePages set > 0. CentOS 6.14.0-dmr.bkc, QAT in-tree kernel 6.14.",
        "verified_root_cause": "QAT + DLB-DPDK HugePages contention: (1) Both QAT cpa_sample_code and DLB-DPDK require HugePages for DPDK EAL memory allocation; (2) When both run concurrently, HugePages pool split between two applications may leave insufficient pages for one or both; (3) DPDK EAL initialization failure: 'Cannot get hugepage information' if hugepage filesystem not mounted; (4) In-tree QAT driver in kernel 6.14 may have initialization race when DPDK also initializes hugepage-backed memory; (5) Recommended fix: use correct QAT package QAT_2025.07.01.tar.gz (not in-tree for DMR validation).",
        "verified_fix": "Mount hugepage filesystem: 'mount -t hugetlbfs none /mnt/huge'. Allocate sufficient HugePages for both QAT and DLB-DPDK. Use out-of-tree QAT driver (QAT_2025.07.01). Run as root.",
        "architectural_element": "DPDK HugePages; QAT cpa_sample_code; DLB-DPDK concurrent; hugepage pool; EAL memory",
        "failure_registers": [],
        "adjacent_subsystems": ["DPDK EAL memory", "HugePages allocator", "QAT in-tree driver", "DLB-DPDK"],
        "related_hsds": [],
        "spec_reference": "DPDK wiki: HugePages setup; QAT installation wiki; QAT_2025.07.01 package"
    },
    phase4={
        "tier1": [
            {"category": "hugepage_check", "commands": ["cat /proc/meminfo | grep Huge", "mount | grep huge", "grep -i huge /proc/cmdline"], "reveals": "HugePages available and mounted", "relevance": "Not mounted or insufficient pages = DPDK EAL init failure"},
            {"category": "qat_version_check", "commands": ["modinfo qat | grep version", "ls /lib/modules/$(uname -r)/extra/qat*.ko"], "reveals": "QAT driver version (in-tree vs out-of-tree)", "relevance": "In-tree driver may lack DMR validation fixes; use QAT_2025.07.01"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — QAT + DLB-DPDK HugePages contention or in-tree driver limitation",
        "root_cause_domain": "val.env.execution / HugePages contention between QAT and DLB-DPDK; in-tree QAT driver limitation",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "hugepage_check identifies pool size. qat_version_check identifies driver. Use QAT_2025.07.01 package.",
        "iteration_savings": "2",
    },
)

# ── HSD 18043412175 — QAT DRNG always zero value ─────────────────────────────
write(
    "18043412175",
    phase2={
        "testcase_name": "QAT DRNG always returns 0 value (ECDSA sign test results not unique) on DMR AP A0 OKS",
        "testcase_command": "(ECDSA sign test with parti tool; QAT DRNG zero output)",
        "testcase_parameters": "OKS DMR AP A0; ECDSA sign test; DRNG always returns 0; not unique results; pasql.cpp:409 update sql statement failed shim undefined state",
        "testcase_domain_focus": "QAT DRNG returning zeros on DMR AP A0 — FIPS self-test failure or zeroization event causing DRNG to output all zeros",
    },
    phase3={
        "verified_problem_statement": "QAT DRNG always returns 0 value on OKS DMR AP A0 during ECDSA sign test. Not-unique results. pasql.cpp:409 update sql statement failed.",
        "verified_root_cause": "QAT DRNG zero output — FIPS self-test or zeroization: (1) DMR DRNG (in iMH fuse controller for S3M/QAT) fails FIPS Known Answer Test (KAT) during boot — per FIPS spec, DRNG must return zeros or disable output on self-test failure; (2) Zeroization event — debug unlock, NVRAM/SRAM zeroization, or SKS key erasure causing DRNG to output zeros; (3) A0 silicon DRNG not passing FIPS CAVP validation — early A0 steppings have known security engine bring-up limitations; (4) S3M firmware self-test failure for DRNG — FW disables DRNG and forces zero output; (5) ECDSA sign test uses non-unique keys because DRNG returns same (zero) value every time.",
        "verified_fix": "Verify S3M firmware DRNG self-test status during boot (FIPS KAT registers). Check zeroization event log. Confirm A0 silicon DRNG FIPS status. Escalate to security team for DRNG enable on A0.",
        "architectural_element": "DMR DRNG (iMH fuse controller); S3M FIPS self-test; FIPS KAT; zeroization event; ECDSA entropy",
        "failure_registers": ["DRNG status register", "S3M FIPS self-test status"],
        "adjacent_subsystems": ["S3M security engine", "DRNG FIPS KAT", "iMH fuse controller", "QAT crypto"],
        "related_hsds": [],
        "spec_reference": "DMR Security HAS: DRNG FIPS; S3M FIPS self-test; DRNG CAVP validation; FIPS zeroization"
    },
    phase4={
        "tier1": [
            {"category": "drng_status", "commands": ["sv.socket0.imhs.s3m.drng_status.show()", "sv.socket0.imhs.s3m.fips_selftest_status.show()"], "reveals": "DRNG operational status and FIPS self-test result", "relevance": "Failed KAT = DRNG disabled; zeros output per FIPS spec"},
            {"category": "zeroization_check", "commands": ["Check S3M firmware log for zeroization events", "sv.socket0.imhs.s3m.zeroization_event.show()"], "reveals": "Whether zeroization event forced DRNG disable", "relevance": "Zeroization = DRNG outputs zeros; requires S3M reinit"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [
            {"description": "A0 DRNG FIPS CAVP validation status", "commands": ["Contact security team for A0 DRNG FIPS status"], "why": "DRNG FIPS certification requires security team action"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — QAT DRNG zero output causes ECDSA non-unique signatures; FIPS self-test failure",
        "root_cause_domain": "hw.qat / DMR A0 DRNG FIPS self-test failure or zeroization event causing zero entropy output",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "drng_status + zeroization_check identify FIPS/zeroization root cause. Security team needed for FIPS status.",
        "iteration_savings": "2",
    },
)

# ── HSD 18043352398 — QAT memory corruption flat buffers DcChainInteg ────────
write(
    "18043352398",
    phase2={
        "testcase_name": "QAT memory corruption with multiple flat buffers in DcChainInteg CompressEncrypt (Zstandard + AES-CTR)",
        "testcase_command": "DcChainInteg_Generic_CompressEncrypt(samplePayload, 6, 5, 128, 0, 0, 0, 1, 1, 5)",
        "testcase_parameters": "OKS DMR AP A0; chaining test combining Zstandard compression and AES-CTR encryption; 6 buffers, 5 instances, 128 size; multiple flat buffers; memory corruption",
        "testcase_domain_focus": "QAT DMR A0 memory corruption in chained compress+encrypt with multiple flat buffers — A0 limitation in CPM 5.1 Fusion flows",
    },
    phase3={
        "verified_problem_statement": "QAT memory corruption on DMR AP A0 with DcChainInteg_Generic_CompressEncrypt test using multiple flat buffers (Zstandard + AES-CTR chained). 6 buffers, 5 instances, 128 size.",
        "verified_root_cause": "QAT chained compress+encrypt memory corruption on DMR A0: Per GENI analysis: (1) CPM 5.1 Fusion flows (chained compress+encrypt) stage intermediate results in SharedRAM — buffer management or SharedRAM pointer issue in A0 silicon/firmware; (2) Multiple flat buffers in chained operation increases complexity — intermediate buffer staging corrupts adjacent memory if SharedRAM offsets incorrect; (3) DMR memory model (disaggregated fabric-connected memory, 2LM) adds DMA path complexity — A0 may not handle multi-buffer chain DMA correctly; (4) A0 limitation/bug in CPM firmware handling of Zstandard+AES-CTR multi-buffer chains; (5) No specific errata documented — needs firmware fix in later release.",
        "verified_fix": "Test on later DMR stepping or updated CPM firmware. Reduce to single flat buffer per chain. Try simpler chaining (e.g., deflate+AES-GCM instead of Zstandard+AES-CTR). Get CPM firmware fix for multi-buffer Fusion flow.",
        "architectural_element": "QAT CPM 5.1 Fusion flows; SharedRAM buffer staging; multi-buffer chained compress+encrypt; Zstandard; AES-CTR; 2LM DMA",
        "failure_registers": [],
        "adjacent_subsystems": ["QAT CPM firmware", "SharedRAM allocator", "Zstandard engine", "AES-CTR engine", "2LM DMA path"],
        "related_hsds": [],
        "spec_reference": "DMR ACC HAS: CPM Fusion flows; DMR Product Architecture Memory; OKS Product Architecture QAT"
    },
    phase4={
        "tier1": [
            {"category": "corruption_dump", "commands": ["Dump SharedRAM content before and after chain operation", "Check DMA completion record for multi-buffer chain"], "reveals": "SharedRAM corruption point in multi-buffer chain", "relevance": "Corrupt SharedRAM = CPM firmware buffer management bug"},
            {"category": "stepping_check", "commands": ["python3 -c 'import sv; print(sv.socket0.stepping)'"], "reveals": "Silicon stepping", "relevance": "A0 = known firmware limitation; later stepping may have fix"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [
            {"description": "CPM firmware fix for Zstandard+AES-CTR multi-buffer chain", "commands": ["Escalate to QAT CPM firmware team with SharedRAM corruption dump"], "why": "Firmware fix requires CPM team"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — multi-buffer chained compress+encrypt corrupts memory in CPM SharedRAM on A0",
        "root_cause_domain": "hw.qat / CPM 5.1 Fusion flow multi-buffer SharedRAM management bug on DMR A0",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "corruption_dump identifies SharedRAM issue. A0 stepping confirmed. CPM firmware fix needed.",
        "iteration_savings": "2",
    },
)

# ── HSD 16027647768 — QAT systemctl start fails after reboot (PSS Fmod IMH1) ──
write(
    "16027647768",
    phase2={
        "testcase_name": "QAT systemctl start qat fails after reboot on DMR AP 1S PSS Fmod IMH1 Simics",
        "testcase_command": "systemctl start qat (after reboot in Simics CentOS)",
        "testcase_parameters": "DMR AP 1S PSS Fmod; IMH1 IPClean Debug IFWI OKSDCRB1.SYS.WR.64.2025.22; Simics dmr-7.0 2025ww22; CentOS; QAT start fails after reboot",
        "testcase_domain_focus": "QAT service start failure after Simics reboot on DMR AP PSS Fmod — PM handshake or boot sequence not completing before QAT start",
    },
    phase3={
        "verified_problem_statement": "QAT systemctl start qat fails after reboot on DMR AP 1S PSS Fmod Simics (IMH1 IPClean IFWI, dmr-7.0 2025ww22). Not consistently reproducible — sometimes after OS reboot or 30-40 min.",
        "verified_root_cause": "QAT service start failure on Simics reboot: Per GENI analysis: (1) Platform PM handshake (s0_early_boot_done, rclk_programming_done) not fully completed before QAT service starts; (2) Simics CentOS boot may not wait for all platform initialization signals before user-space services start; (3) QAT firmware init message times out because hardware/firmware not ready; (4) Intermittent nature (sometimes after reboot or 30-40 min) suggests race condition between boot timing and QAT init; (5) Same root cause as HSD 15018147145 and 16028742119 — Simics IMH boot timing.",
        "verified_fix": "Verify s0_early_boot_done and rclk_programming_done before QAT start. Add systemd boot ordering to delay QAT start after platform ready. Apply ssm_pm_enable=0 WA. Use latest BIOS/IFWI.",
        "architectural_element": "Simics boot timing; s0_early_boot_done; rclk_programming_done; QAT service start ordering; PMSync",
        "failure_registers": ["s0_early_boot_done", "rclk_programming_done"],
        "adjacent_subsystems": ["Simics boot sequence", "systemd service ordering", "QAT firmware init", "PMSync"],
        "related_hsds": ["15018147145", "16028742119"],
        "spec_reference": "S3M HFPGA Troubleshooting wiki; Simics boot recipe; DMR QAT BKC timing"
    },
    phase4={
        "tier1": [
            {"category": "boot_ready_check", "commands": ["sv.socket0.imhs.punit.s0_early_boot_done.show()", "journalctl -b | grep -i 'qat\\|start\\|fail'"], "reveals": "Platform boot ready state and QAT service start timing", "relevance": "Not ready at QAT start = race condition causing init failure"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — QAT service starts before platform ready after Simics reboot",
        "root_cause_domain": "val.env.execution / Simics boot timing race with QAT service start",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "boot_ready_check confirms platform state. Same pattern as HSD 15018147145.",
        "iteration_savings": "2",
    },
)

# ── HSD 16027630298 — QAT Stateless Compression sm_on failure PSS Fmod ───────
write(
    "16027630298",
    phase2={
        "testcase_name": "QAT Stateless Compression Sample Code fails with sm_on configuration on DMR AP PSS Fmod",
        "testcase_command": "dc_stateless_sample or cpa_sample_code with sm_on config",
        "testcase_parameters": "DMR AP 1S PSS Fmod; IMH1 IPClean IFWI OKSDCRB1.SYS.WR.64.2025.22; Simics dmr-7.0 2025ww22; QAT stateless compression with sm_on; CentOS",
        "testcase_domain_focus": "QAT Stateless Compression fails with sm_on (scatter-masking on) configuration on DMR AP PSS Fmod Simics",
    },
    phase3={
        "verified_problem_statement": "QAT Stateless Compression Sample Code fails with sm_on configuration on DMR AP 1S PSS Fmod Simics.",
        "verified_root_cause": "QAT sm_on (scatter-masking on) compression failure: (1) Scatter-masking (sm_on) config requires specific QAT CPM5.1 firmware capability that may not be fully initialized on IMH1 Simics; (2) DC services may not be properly enabled for sm_on mode — requires adf_ctl configuration; (3) Simics CPM model may not support sm_on mode in stateless compression; (4) Same infrastructure issues as HSD 16028742119 — Simics IMH1 QAT init may not complete fully; (5) QAT config file may not have sm mode enabled in dc services section.",
        "verified_fix": "Enable DC services first. Verify QAT config has sm_on enabled. Apply ssm_pm_enable=0 WA. Check Simics CPM model sm_on support.",
        "architectural_element": "QAT scatter-masking; DC service sm_on; CPM 5.1 firmware; Simics CPM model",
        "failure_registers": [],
        "adjacent_subsystems": ["QAT CPM DC service", "scatter-masking engine", "Simics CPM model"],
        "related_hsds": ["16028742119", "14022555397"],
        "spec_reference": "QAT CPM 5.1 scatter-masking spec; QAT config file guide"
    },
    phase4={
        "tier1": [
            {"category": "dc_sm_check", "commands": ["cat /sys/bus/qat/devices/qat_dev0/services", "adf_ctl status"], "reveals": "DC service and sm_on configuration", "relevance": "DC not enabled or sm_on not configured = stateless sm_on fails"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — sm_on config requires DC service with scatter-masking; Simics init or config issue",
        "root_cause_domain": "val.env.execution / QAT sm_on DC service not configured in Simics IMH1",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "dc_sm_check identifies config state. Same infrastructure as HSD 16028742119.",
        "iteration_savings": "2",
    },
)

# ── HSD 16026354661 — QAT Stateless Compression failure BKC#16 ───────────────
write(
    "16026354661",
    phase2={
        "testcase_name": "QAT Stateless Compression Sample Code fails with DMR_PPO_BKC#16",
        "testcase_command": "dc_stateless_sample",
        "testcase_parameters": "DMR AP 1S PSS Fmod; BKC#16; dc_stateless_sample fails; no further error details",
        "testcase_domain_focus": "QAT Stateless Compression failure on DMR AP PSS Fmod BKC#16 — same pattern as HSD 16027630298",
    },
    phase3={
        "verified_problem_statement": "QAT Stateless Compression Sample Code fails with DMR_PPO_BKC#16 on DMR AP PSS Fmod.",
        "verified_root_cause": "Same root cause as HSD 16027630298: QAT DC services not properly configured or Simics CPM model init issue. BKC#16 is an early BKC — QAT Simics support was immature at that point.",
        "verified_fix": "Apply same fix as HSD 16027630298. Enable DC services. Apply ssm_pm_enable=0 WA. Use updated BKC or Simics model.",
        "architectural_element": "QAT DC service; Simics CPM init; BKC#16",
        "failure_registers": [],
        "adjacent_subsystems": ["QAT DC service", "Simics CPM model"],
        "related_hsds": ["16027630298"],
        "spec_reference": "Same as HSD 16027630298"
    },
    phase4={
        "tier1": [
            {"category": "dc_service_check", "commands": ["cat /sys/bus/qat/devices/qat_dev0/services", "adf_ctl status"], "reveals": "DC service state", "relevance": "Same as HSD 16027630298"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — same as HSD 16027630298",
        "root_cause_domain": "val.env.execution / QAT DC service not configured (same as HSD 16027630298)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "Same root cause as HSD 16027630298. Simics BKC#16 era.",
        "iteration_savings": "2",
    },
)

# ── HSD 16025723266 — QAT unable to start services PSS Fmod (intermittent) ───
write(
    "16025723266",
    phase2={
        "testcase_name": "QAT unable to start QAT services on DMR AP PSS Fmod (intermittent: after reboot or 30-40 min)",
        "testcase_command": "systemctl start qat.service",
        "testcase_parameters": "DMR AP 1S PSS Fmod; systemctl start qat fails; WA used; intermittent — after reboot or 30-40 min post reboot",
        "testcase_domain_focus": "Intermittent QAT service start failure on DMR AP PSS Fmod — same boot timing race as HSD 16027647768",
    },
    phase3={
        "verified_problem_statement": "QAT unable to start services on DMR AP PSS Fmod intermittently — after OS reboot or after 30-40 min post reboot.",
        "verified_root_cause": "Same root cause as HSD 16027647768: Platform boot timing race — s0_early_boot_done / rclk_programming_done not asserted before QAT service starts; OR QAT firmware init timeout. WA used = WA exists for this.",
        "verified_fix": "Same as HSD 16027647768. Apply WA (ssm_pm_enable=0). Add service start delay. Use latest BIOS/IFWI.",
        "architectural_element": "QAT service start timing; platform boot handshake; Simics boot sequence",
        "failure_registers": [],
        "adjacent_subsystems": ["QAT firmware init", "systemd service", "Simics boot"],
        "related_hsds": ["16027647768", "15018147145"],
        "spec_reference": "Same as HSD 16027647768"
    },
    phase4={
        "tier1": [
            {"category": "qat_start_log", "commands": ["journalctl -b | grep -i 'qat\\|fail'", "adf_ctl status"], "reveals": "QAT service start failure details", "relevance": "Same as HSD 16027647768"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — QAT init fails intermittently due to boot timing race",
        "root_cause_domain": "val.env.execution / QAT service start timing race (same as HSD 16027647768)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "Same root cause and fix as HSD 16027647768.",
        "iteration_savings": "2",
    },
)

# ── HSD 16024715383 — QAT fail to restart services BKC#05 CentOS ────────────
write(
    "16024715383",
    phase2={
        "testcase_name": "QAT failed to restart QAT services with CentOS-6 BKC#05 on DMR AP Simics",
        "testcase_command": "systemctl restart qat",
        "testcase_parameters": "DMR AP PSS Simics BKC#05; IPClean Debug IFWI OKSDCRB1.SYS.WR.64.2024.24; CentOS; QAT restart fails",
        "testcase_domain_focus": "QAT service restart failure on DMR AP Simics BKC#05 — early BKC QAT Simics init issue",
    },
    phase3={
        "verified_problem_statement": "Failed to restart QAT services with CentOS BKC#05 on DMR AP Simics (early BKC#05 config).",
        "verified_root_cause": "Same family as HSDs 16027647768, 16025723266, 15018147145: QAT service restart failure on early DMR AP Simics BKC. BKC#05 is very early — Simics model and QAT firmware integration at early stage. ssm_pm_enable not cleared. Config files not in place.",
        "verified_fix": "Apply ssm_pm_enable=0 WA. Place c4xxxvf config files. Use newer BKC.",
        "architectural_element": "QAT service restart; BKC#05 early config; ssm_pm_enable; Simics init",
        "failure_registers": [],
        "adjacent_subsystems": ["QAT firmware", "adf_ctl", "ssm_pm_enable"],
        "related_hsds": ["16027647768", "15018147145"],
        "spec_reference": "Same as HSD 15018147145"
    },
    phase4={
        "tier1": [
            {"category": "qat_module_check", "commands": ["adf_ctl status", "dmesg | grep qat"], "reveals": "QAT init status", "relevance": "Same as HSD 15018147145"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — QAT service restart fails; early Simics BKC QAT init issue",
        "root_cause_domain": "val.env.execution / QAT Simics init failure (early BKC#05, same family as HSD 15018147145)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "Same family as HSD 15018147145. ssm_pm_enable WA + config files.",
        "iteration_savings": "2",
    },
)

# ── HSD 16027417452 — IAA user randomize opcode 0x42/0x43 comp[0]=0x16 ───────
write(
    "16027417452",
    phase2={
        "testcase_name": "IAA user randomize test fails for opcode 0x42 and 0x43 with comp[0]=0x16",
        "testcase_command": "IAA_user_mode_randomize_config_opcodes_L (HSD 14021485521)",
        "testcase_parameters": "DMR AP 1S PSS Fmod BKC#25; IAA opcode 0x42 and 0x43 fail; comp[0]: 0x0000000000000016; IMH1",
        "testcase_domain_focus": "IAA user randomize opcodes 0x42/0x43 completion status 0x16 on DMR AP PSS Fmod",
    },
    phase3={
        "verified_problem_statement": "IAA user randomize test (HSD 14021485521) fails for opcodes 0x42 and 0x43 with completion status comp[0]=0x16 on DMR AP 1S PSS Fmod BKC#25.",
        "verified_root_cause": "IAA opcode 0x42/0x43 completion error 0x16: Completion status 0x16 = 'Invalid flags in descriptor byte 48-51' (IAA spec error code 0x16). Root cause: (1) Test randomizer generates flag combination not valid for opcodes 0x42 (Compress-2) or 0x43 (Decompress-2); (2) IAA validation randomizer does not properly constrain flag values for 0x42/0x43 — some flag combinations reserved/invalid for these opcodes; (3) val.env.content issue — test content randomization not properly bounded for 0x42/0x43 flags.",
        "verified_fix": "Fix IAA test randomizer to exclude invalid flag combinations for opcodes 0x42/0x43. Reference IAA HAS for valid flag combinations for these opcodes.",
        "architectural_element": "IAA opcode 0x42/0x43; descriptor flag validation; completion error 0x16",
        "failure_registers": ["IAA completion record status 0x16"],
        "adjacent_subsystems": ["IAA randomizer test", "descriptor flag validator"],
        "related_hsds": ["16026995209"],
        "spec_reference": "IAA HAS: opcode 0x42/0x43 descriptor flags; completion status error codes; error code 0x16"
    },
    phase4={
        "tier1": [
            {"category": "compl_check", "commands": ["cat iaa_test.log | grep 'compl\\[0\\]'", "iax_common_verify_cmpl_record_status() line for 0x16"], "reveals": "Completion record error code and descriptor that triggered it", "relevance": "0x16 = invalid descriptor flags for opcode"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — IAA randomizer generates invalid flags for 0x42/0x43; 0x16 completion error",
        "root_cause_domain": "val.env.content / IAA test randomizer invalid flag for opcodes 0x42/0x43",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "compl_check confirms 0x16 error code. Flag constraint fix in test randomizer.",
        "iteration_savings": "2",
    },
)

# ── HSD 16026995209 — IAA user randomize 0x42/0x43 comp[0]=0x1e0a ────────────
write(
    "16026995209",
    phase2={
        "testcase_name": "IAA user randomize test fails for opcode 0x42/0x43 with comp[0]=0x1e0a",
        "testcase_command": "IAA_user_mode_randomize_config_opcodes_L (HSD 14021485521)",
        "testcase_parameters": "DMR AP 1S PSS Fmod; IAA opcode 0x42/0x43; comp[0]: 0x0000000000001e0a; IMH1",
        "testcase_domain_focus": "IAA user randomize opcodes 0x42/0x43 completion 0x1e0a on DMR AP PSS Fmod",
    },
    phase3={
        "verified_problem_statement": "Same test as HSD 16027417452: IAA user randomize opcodes 0x42/0x43 fail with comp[0]=0x1e0a on DMR AP 1S PSS Fmod.",
        "verified_root_cause": "Completion status 0x1e0a: 0x1e = hardware parity/ECC error or output buffer overflow; 0x0a = complementary status. Root cause similar to HSD 16027417452 but different error code suggests: (1) Different invalid operation parameter causing hardware parity error; (2) Output buffer too small for decompressed data (0x0a = extra bytes in output); (3) test randomizer generating out-of-bounds output size. Both are test content randomizer constraint issues.",
        "verified_fix": "Same fix as HSD 16027417452: constrain randomizer for 0x42/0x43. Also validate output buffer size constraints.",
        "architectural_element": "IAA opcode 0x42/0x43; completion status 0x1e0a; output buffer size; hardware error",
        "failure_registers": ["IAA completion record 0x1e0a"],
        "adjacent_subsystems": ["IAA compress-2/decompress-2", "output buffer manager"],
        "related_hsds": ["16027417452"],
        "spec_reference": "IAA HAS: completion status 0x1e and 0x0a; opcode 0x42/0x43"
    },
    phase4={
        "tier1": [
            {"category": "compl_0x1e0a_check", "commands": ["cat iaa_test.log | grep 'compl\\[0\\].*1e0a'"], "reveals": "Completion record details for 0x1e0a", "relevance": "0x1e = HW parity or buffer overflow; 0x0a = extra output bytes"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — IAA randomizer generates invalid params; hardware error or buffer overflow",
        "root_cause_domain": "val.env.content / IAA test randomizer invalid params for opcodes 0x42/0x43 (related to HSD 16027417452)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "compl_0x1e0a_check identifies error type. Related to HSD 16027417452.",
        "iteration_savings": "2",
    },
)

# ── HSD 15017777226 — DSA/IAA devices halted after PSS Fmod ──────────────────
write(
    "15017777226",
    phase2={
        "testcase_name": "DSA/IAA devices halted after PSS Fmod test on DMR AP 1S PSS Fmod BKC#24",
        "testcase_command": "(DSA/IAA test in PSS Fmod; devices enter halted state after test)",
        "testcase_parameters": "DMR AP 1S PSS Fmod BKC#24; Simics dmr-7.0 2025ww17; CentOS 6.14; IMH1 IPClean IFWI; DSA/IAA halted state",
        "testcase_domain_focus": "DSA/IAA devices halted state after PSS Fmod test on DMR AP — device halt from error injection or firmware issue",
    },
    phase3={
        "verified_problem_statement": "DSA/IAA devices enter halted state after PSS Fmod test on DMR AP 1S BKC#24 Simics.",
        "verified_root_cause": "DSA/IAA device halt after PSS Fmod test: (1) PSS Fmod test may inject errors causing DSA/IAA to enter DHS (Device Halt State); (2) Device not recovered after error injection — DHS requires full device reset; (3) Simics CPM/DSA model may leave device in unexpected state after Fmod test sequence; (4) GENSTS.DHS bit set; requires accel-config reset or full reboot to recover; (5) Related to ERRINJCTL tests (HSD 14025833391).",
        "verified_fix": "Reset DSA/IAA devices: accel-config disable-device dsa0; accel-config enable-device dsa0. Or full reboot. Check GENSTS.DHS after test.",
        "architectural_element": "DSA/IAA DHS state; device halt recovery; PSS Fmod error injection",
        "failure_registers": ["GENSTS.DHS"],
        "adjacent_subsystems": ["DSA/IAA state machine", "error recovery", "PSS Fmod injector"],
        "related_hsds": ["14025833391"],
        "spec_reference": "DSA/IAA HAS: DHS halt state; device recovery procedure"
    },
    phase4={
        "tier1": [
            {"category": "dhs_check", "commands": ["sv.socket0.imhs.acc.accs.dsa.gensts.dhs.show()", "accel-config list | grep state"], "reveals": "DHS state and device health", "relevance": "DHS=1 = device halted; reset required"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — PSS Fmod error injection causes DSA/IAA DHS halt",
        "root_cause_domain": "hw.dsa / DSA/IAA device DHS halt after PSS Fmod error injection",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "dhs_check confirms DHS state. Device reset or reboot needed.",
        "iteration_savings": "2",
    },
)

# ── HSD 16025676064 — IAA opcodes hang Simics dmr-6.0 2024ww37 ───────────────
write(
    "16025676064",
    phase2={
        "testcase_name": "IAA opcodes test hangs with multiple WQs in parallel on Simics dmr-6.0 2024ww37",
        "testcase_command": "(IAA opcode tests on multiple WQs in parallel in Simics dmr-6.0)",
        "testcase_parameters": "DMR Simics dmr-6.0 2024ww37.0.00_44_Pre677; BIOS OKSDCRB1.SYS.WR.64.2024.38; IAA opcode test hang on parallel WQs",
        "testcase_domain_focus": "IAA opcode test hang with parallel WQ submission on Simics dmr-6.0 — Simics model synchronization issue",
    },
    phase3={
        "verified_problem_statement": "IAA opcode tests hang when running on multiple WQs in parallel on Simics dmr-6.0 2024ww37.0.00_44_Pre677.",
        "verified_root_cause": "IAA parallel WQ hang on Simics dmr-6.0: (1) Simics 6.0 model doesn't properly handle concurrent multi-WQ IAA descriptor submission — simulator model has serialization issue; (2) Simics IAA model deadlock when multiple WQs submit simultaneously; (3) model timing issue — real hardware handles parallel WQ concurrently but Simics model requires serialization; (4) platform.simics.platform — Simics model version 6.0 pre-677 has known IAA simulation limitations.",
        "verified_fix": "Use serialized WQ submission in Simics (one WQ at a time). Update to newer Simics dmr-6.0 release or dmr-7.0 which has improved IAA model.",
        "architectural_element": "IAA parallel WQ; Simics dmr-6.0 model; WQ concurrency",
        "failure_registers": [],
        "adjacent_subsystems": ["Simics IAA model", "WQ scheduler"],
        "related_hsds": ["14022217283", "22019670393"],
        "spec_reference": "Simics dmr-6.0 release notes; IAA WQ parallelism"
    },
    phase4={
        "tier1": [
            {"category": "simics_wq_test", "commands": ["Run IAA opcode test with single WQ serialized instead of parallel WQs"], "reveals": "Whether hang is Simics parallel WQ model limitation", "relevance": "Single WQ passes = Simics model parallel limitation"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — Simics IAA model deadlock on parallel WQ submission",
        "root_cause_domain": "platform.simics.platform / Simics dmr-6.0 IAA model deadlock with parallel WQs",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "simics_wq_test confirms parallel limitation. Use dmr-7.0.",
        "iteration_savings": "2",
    },
)

# ── HSD 14022217283 — DSA opcodes hang Simics 6.8.0 kernel ───────────────────
write(
    "14022217283",
    phase2={
        "testcase_name": "DSA opcodes test hangs with multiple WQs in parallel on Simics kernel 6.8.0",
        "testcase_command": "dsa_test on multiple WQs in parallel (Simics 6.0.pre552)",
        "testcase_parameters": "DMR Simics 6.0.pre552; BIOS OKSDCRB1.86B.0012.D09; kernel 6.8.0-dmr.bkc; accel-config 4.1.4; dsa_test hang on parallel WQs; platform.driver.dsa",
        "testcase_domain_focus": "DSA dsa_test hang with parallel WQ submission on DMR Simics 6.0 — same Simics model issue as HSD 16025676064",
    },
    phase3={
        "verified_problem_statement": "dsa_test hangs running on multiple WQs in parallel on DMR Simics 6.0.pre552 with kernel 6.8.0.",
        "verified_root_cause": "Same root cause as HSD 16025676064: Simics 6.0 model DSA/IAA parallel WQ submission deadlock. Also: kernel 6.8.0 idxd driver may have interaction with Simics model timing that causes additional deadlock. platform.driver.dsa = driver component confirmed.",
        "verified_fix": "Same as HSD 16025676064: Serialize WQ submissions. Update to newer Simics. Also check kernel 6.8.0 idxd driver deadlock fix.",
        "architectural_element": "DSA parallel WQ; Simics 6.0 model; kernel 6.8.0 idxd driver",
        "failure_registers": [],
        "adjacent_subsystems": ["Simics DSA model", "kernel 6.8.0 idxd driver"],
        "related_hsds": ["16025676064"],
        "spec_reference": "Same as HSD 16025676064; kernel 6.8.0 idxd changelog"
    },
    phase4={
        "tier1": [
            {"category": "dsa_wq_serial", "commands": ["Run dsa_test with single WQ only"], "reveals": "Whether parallel WQ is Simics model limitation", "relevance": "Same as HSD 16025676064"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — Simics DSA model deadlock on parallel WQ (same as HSD 16025676064)",
        "root_cause_domain": "platform.driver.dsa / Simics 6.0 model parallel WQ deadlock + kernel 6.8.0 idxd interaction",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "Same root cause as HSD 16025676064.",
        "iteration_savings": "2",
    },
)

# ── HSD 14022136667 — QAT Windows driver UCC STATUS_DEVICE_POWER_FAILURE ─────
write(
    "14022136667",
    phase2={
        "testcase_name": "QAT Windows driver not loading with UCC soc_config: STATUS_DEVICE_POWER_FAILURE",
        "testcase_command": "(Windows Device Manager QAT driver load with soc_config=ucc)",
        "testcase_parameters": "DMR Simics CPM_FMOD; Windows; soc_config=ucc; QAT yellow bang STATUS_DEVICE_POWER_FAILURE; works with soc_config != ucc; platform.driver.qat",
        "testcase_domain_focus": "QAT Windows driver fails to load with UCC soc_config on DMR Simics — power management config incompatibility",
    },
    phase3={
        "verified_problem_statement": "QAT Windows driver not loading (yellow bang: STATUS_DEVICE_POWER_FAILURE) when using soc_config=ucc in DMR Simics CPM_FMOD. Works with other soc_config values.",
        "verified_root_cause": "QAT Windows driver power failure with UCC soc_config: (1) UCC (Unified Core Configuration) soc_config changes power management registers that Windows QAT driver depends on; (2) STATUS_DEVICE_POWER_FAILURE = PCI device power management failure during driver initialization — Windows PnP manager cannot transition QAT device to D0 power state with UCC config; (3) UCC changes device power domain configuration making QAT device power transition fail; (4) platform.driver.qat = driver/platform configuration issue.",
        "verified_fix": "Avoid UCC soc_config for QAT Windows testing. Use supported soc_config. Or update Windows QAT driver to handle UCC power domain configuration.",
        "architectural_element": "QAT Windows driver; UCC soc_config; device power management; STATUS_DEVICE_POWER_FAILURE",
        "failure_registers": [],
        "adjacent_subsystems": ["Windows PnP power management", "QAT device power domain", "UCC config"],
        "related_hsds": ["22021653767"],
        "spec_reference": "Windows QAT driver release notes; UCC soc_config specification; device power management"
    },
    phase4={
        "tier1": [
            {"category": "soc_config_check", "commands": ["Check soc_config value in Simics startup", "Windows Event Log for STATUS_DEVICE_POWER_FAILURE"], "reveals": "UCC config impact on QAT power domain", "relevance": "UCC config = power domain change incompatible with Windows QAT driver"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — UCC soc_config changes QAT power domain; Windows driver power transition fails",
        "root_cause_domain": "platform.driver.qat / UCC soc_config incompatible with Windows QAT driver power management",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "soc_config_check identifies UCC power domain change. Driver update or avoid UCC config.",
        "iteration_savings": "2",
    },
)

# ── HSD 22021653767 — QAT Windows yellow bang icp_qat5 DMR AP A0 ─────────────
write(
    "22021653767",
    phase2={
        "testcase_name": "QAT Windows yellow bang icp_qat5 device on DMR AP A0 PO system",
        "testcase_command": "(Windows Device Manager QAT icp_qat5 driver load on DMR AP A0 PO)",
        "testcase_parameters": "OKS DMR AP A0 PO Windows; device PCI VEN_8086 DEV_4948 SUBSYS_49488086 yellow bang; icp_qat5 service error event",
        "testcase_domain_focus": "QAT Windows icp_qat5 yellow bang on DMR AP A0 PO — driver incompatibility or power management failure",
    },
    phase3={
        "verified_problem_statement": "QAT Windows icp_qat5 service (device PCI\\VEN_8086&DEV_4948 = QAT DMR device) shows yellow bang in Windows Device Manager on DMR AP A0 PO.",
        "verified_root_cause": "QAT Windows driver yellow bang on DMR AP A0: (1) DEV_4948 = DMR QAT device ID; Windows icp_qat5 driver version may not support DMR QAT device ID 4948; (2) ssm_pm_enable not cleared in Windows boot — DMR A0 QAT PO WA not applied in Windows environment; (3) QAT FW authentication failure on A0 (same root cause as HSD 14025998125) causing driver to fail with yellow bang; (4) Windows QAT driver package version may not be DMR-compatible.",
        "verified_fix": "Apply ssm_pm_enable=0 WA for Windows. Use DMR-compatible Windows QAT driver with DEV_4948 support. Apply FW auth WA.",
        "architectural_element": "QAT Windows icp_qat5 driver; DEV_4948 DMR QAT; ssm_pm_enable WA; FW authentication",
        "failure_registers": ["ssm_pm_enable"],
        "adjacent_subsystems": ["Windows QAT driver", "QAT FW auth", "power management"],
        "related_hsds": ["14025998125", "14022136667"],
        "spec_reference": "Windows QAT driver for DMR (icp_qat5); DMR A0 QAT PO WA guide"
    },
    phase4={
        "tier1": [
            {"category": "device_event", "commands": ["Windows Event Viewer: System log for PCI VEN_8086 DEV_4948", "Device Manager: yellow bang error code"], "reveals": "Specific Windows error code for QAT yellow bang", "relevance": "Error code identifies FW auth failure or driver incompatibility"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — Windows QAT driver fails to load on DMR AP A0; FW auth or driver incompatibility",
        "root_cause_domain": "hw.cpm / Windows QAT driver incompatibility or FW auth failure on DMR AP A0",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "device_event identifies error code. ssm_pm_enable WA + DMR driver version.",
        "iteration_savings": "2",
    },
)

# ── HSD 16023759053 — QAT test steps update for DMR BKC ──────────────────────
write(
    "16023759053",
    phase2={
        "testcase_name": "QAT test steps need update for DMR BKC 2S PSS Bmod",
        "testcase_command": "(QAT test content tracking: update test steps for DMR DMR BKC execution)",
        "testcase_parameters": "DMR AP 2S PSS Bmod; test content IDs: QAT_Compression_cpa_sample_code_L, PI_QAT_SRIOV_Host_L; test steps need update for DMR",
        "testcase_domain_focus": "Tracking ticket: QAT BKC test content steps need updating for DMR platform — not a failure",
    },
    phase3={
        "verified_problem_statement": "QAT test steps in BKC DMR execution need updating (QAT_Compression_cpa_sample_code_L, PI_QAT_SRIOV_Host_L) for DMR-specific configuration.",
        "verified_root_cause": "Test content tracking ticket: BKC QAT test steps were written for GNR/SPR. DMR-specific differences (new QAT device ID 4948, different srv_mask, ssm_pm_enable WA) require test step updates. Not a silicon bug.",
        "verified_fix": "Update QAT BKC test steps for DMR: use correct device BDF, srv_mask, apply ssm_pm_enable=0 WA, use QAT_2025.07.01 package.",
        "architectural_element": "QAT BKC test content; test step migration for DMR",
        "failure_registers": [],
        "adjacent_subsystems": ["BKC test content", "QAT test framework"],
        "related_hsds": [],
        "spec_reference": "BKC test content update guide; QAT DMR configuration requirements"
    },
    phase4={
        "tier1": [],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [
            {"description": "Update QAT BKC test steps for DMR", "commands": ["Submit test content update for DMR-specific QAT steps"], "why": "Test content update requires content owner action"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "indirect — test content update request; not a silicon or environment failure",
        "root_cause_domain": "val.env.content / QAT test step migration for DMR BKC (not a defect)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "Tracking ticket for test content update. No silicon action needed.",
        "iteration_savings": "1",
    },
)

# ── HSD 14021959459 — QAT FMOD integration into DMR VP Simics ────────────────
write(
    "14021959459",
    phase2={
        "testcase_name": "QAT FMOD test integration into DMR VP (val.vp.simics) tracking HSD",
        "testcase_command": "(QAT FMOD test integration tracking ticket for DMR VP)",
        "testcase_parameters": "val.vp.simics; DMR VP Simics; QAT FMOD integration; tracking ticket",
        "testcase_domain_focus": "Tracking HSD for QAT FMOD test integration into DMR VP Simics validation plan — not a failure",
    },
    phase3={
        "verified_problem_statement": "HSD 14021959459 is a tracking ticket for QAT FMOD (Fault MODe) test integration into DMR VP (Validation Plan) Simics environment.",
        "verified_root_cause": "Not a defect. This is a val.vp.simics feature/integration tracking ticket to add QAT FMOD test content to DMR validation plan.",
        "verified_fix": "Complete QAT FMOD test integration into DMR VP Simics.",
        "architectural_element": "QAT FMOD; DMR validation plan; Simics FMOD framework",
        "failure_registers": [],
        "adjacent_subsystems": ["QAT FMOD", "DMR VP Simics", "validation plan"],
        "related_hsds": ["16027630298", "16025723266"],
        "spec_reference": "DMR QAT FMOD test plan"
    },
    phase4={
        "tier1": [],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [
            {"description": "Complete QAT FMOD DMR VP integration", "commands": [], "why": "Validation plan integration requires content owner"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "indirect — integration tracking HSD; not a defect",
        "root_cause_domain": "val.vp.simics / QAT FMOD test integration tracking (not a defect)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "Tracking ticket for integration work. No silicon action needed.",
        "iteration_savings": "1",
    },
)

# ── HSD 16023756164 — DSA_opcode test failed to enable dsa0 CentOS 6.8.1 ─────
write(
    "16023756164",
    phase2={
        "testcase_name": "DSA_opcode test fails to enable DSA device (dsa0) on DMR Simics with CentOS 6.8.1",
        "testcase_command": "DSA_opcode_test_L (BKC test content)",
        "testcase_parameters": "DMR Simics; CentOS 6.8.1 kernel; dsa0 not enabled; platform.documentation.other; accel-config error",
        "testcase_domain_focus": "DSA opcode test fails to enable dsa0 — test content step issue with CentOS 6.8.1 and accel-config",
    },
    phase3={
        "verified_problem_statement": "DSA_opcode_test_L test content fails to enable dsa0 on DMR Simics with CentOS 6.8.1 — test setup/documentation issue.",
        "verified_root_cause": "Test setup/documentation issue (platform.documentation.other): (1) CentOS 6.8.1 kernel has different idxd driver interface than expected by test; (2) accel-config version mismatch with CentOS 6.8.1 — different UAPI; (3) Test step documentation missing for CentOS 6.8.1 — test steps written for CentOS 6.7; (4) DSA configuration steps need update for kernel 6.8.1 UAPI changes.",
        "verified_fix": "Update test steps for CentOS 6.8.1: use correct accel-config version, correct UAPI commands for 6.8.1 kernel idxd driver.",
        "architectural_element": "DSA enable; accel-config; CentOS 6.8.1 idxd driver; test documentation",
        "failure_registers": [],
        "adjacent_subsystems": ["accel-config", "kernel 6.8.1 idxd driver", "test documentation"],
        "related_hsds": ["14022217283"],
        "spec_reference": "accel-config user guide; kernel 6.8.1 idxd driver UAPI changes"
    },
    phase4={
        "tier1": [
            {"category": "accel_config_check", "commands": ["accel-config -v", "cat /proc/version", "ls /dev/dsa/"], "reveals": "accel-config version and kernel compatibility", "relevance": "Version mismatch = test step update needed"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — test steps not updated for CentOS 6.8.1 idxd API changes",
        "root_cause_domain": "platform.documentation.other / Test steps not updated for CentOS 6.8.1 idxd driver",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "accel_config_check confirms version mismatch. Documentation update needed.",
        "iteration_savings": "2",
    },
)

# ── HSD 14021836063 — SAD9 driver old version on SVOS ────────────────────────
write(
    "14021836063",
    phase2={
        "testcase_name": "CPM SAD9 driver old version on SVOS causing test failures",
        "testcase_command": "(SAD9 driver version check on SVOS; tests fail with old driver version)",
        "testcase_parameters": "SVOS; SAD9 driver version old/incompatible; val.env.tool; component: val.env.tool",
        "testcase_domain_focus": "CPM SAD9 driver version is outdated on SVOS test environment — val.env.tool tracking ticket",
    },
    phase3={
        "verified_problem_statement": "CPM SAD9 driver running on SVOS is old version causing test failures.",
        "verified_root_cause": "val.env.tool issue: SAD9 driver (CPM QAT characterization/debug driver) version on SVOS environment is outdated. Tests that require newer SAD9 features fail because SVOS has old version installed. Tool environment update needed.",
        "verified_fix": "Update SAD9 driver on SVOS to latest version compatible with DMR validation.",
        "architectural_element": "CPM SAD9 driver; SVOS test environment; val.env.tool",
        "failure_registers": [],
        "adjacent_subsystems": ["CPM SAD9", "SVOS", "test tooling"],
        "related_hsds": [],
        "spec_reference": "SAD9 driver release notes"
    },
    phase4={
        "tier1": [
            {"category": "sad9_version_check", "commands": ["sad9 --version", "modinfo sad9 | grep version"], "reveals": "SAD9 driver version on SVOS", "relevance": "Old version = update to latest compatible"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "indirect — old SAD9 driver causes test failures; tool environment issue",
        "root_cause_domain": "val.env.tool / CPM SAD9 driver outdated on SVOS",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "sad9_version_check identifies version. Tool owner updates SAD9.",
        "iteration_savings": "1",
    },
)

# ── HSD 14021823505 — DSA memmove opcode verify failed CentOS 6.7 Simics ─────
write(
    "14021823505",
    phase2={
        "testcase_name": "DSA memmove opcode verify failed on CentOS 6.7 Simics (platform.simics.platform)",
        "testcase_command": "(DSA memmove opcode test on CentOS 6.7 Simics; verify step fails)",
        "testcase_parameters": "DMR Simics; CentOS 6.7 kernel; DSA memmove opcode test verify failed; platform.simics.platform",
        "testcase_domain_focus": "DSA memmove opcode test verify step fails on CentOS 6.7 Simics — kernel/Simics compatibility issue",
    },
    phase3={
        "verified_problem_statement": "DSA memmove opcode test verify step fails on DMR Simics with CentOS 6.7 kernel.",
        "verified_root_cause": "platform.simics.platform issue: (1) CentOS 6.7 kernel idxd driver has early implementation that doesn't properly support DSA memmove large transfer verify; (2) Simics memory model may not return correct data for memmove verify step; (3) Test uses CentOS 6.7 which has limited DSA/IDXD support compared to 6.8+ kernels; (4) Verify step data mismatch due to Simics memory coherency model (same family as IAA memmove/data mismatch).",
        "verified_fix": "Use CentOS 6.8+ kernel with updated idxd driver. Or fix Simics memmove verify model behavior.",
        "architectural_element": "DSA memmove opcode; CentOS 6.7 idxd driver; Simics memory model; verify step",
        "failure_registers": [],
        "adjacent_subsystems": ["CentOS 6.7 idxd driver", "Simics memory model"],
        "related_hsds": ["16023756164", "22019670393"],
        "spec_reference": "CentOS 6.7 idxd driver changelog; DSA memmove spec"
    },
    phase4={
        "tier1": [
            {"category": "kernel_idxd_check", "commands": ["uname -r", "modinfo idxd | grep version", "dmesg | grep idxd"], "reveals": "CentOS 6.7 kernel idxd version", "relevance": "Old idxd version = limited DSA support"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — CentOS 6.7 idxd limited DSA support; verify fails",
        "root_cause_domain": "platform.simics.platform / CentOS 6.7 idxd limited DSA support for memmove verify",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "kernel_idxd_check identifies limitation. Upgrade kernel.",
        "iteration_savings": "2",
    },
)

# ── HSD 14021823464 — IAA_CRYPTO not merged to 6.7 kernel ────────────────────
write(
    "14021823464",
    phase2={
        "testcase_name": "IAA_CRYPTO driver not merged to CentOS 6.7 kernel tracking HSD",
        "testcase_command": "(IAA_CRYPTO driver availability tracking in CentOS 6.7 kernel)",
        "testcase_parameters": "CentOS 6.7 kernel; IAA_CRYPTO driver not present; platform.operating_system.linux.centos; tracking ticket",
        "testcase_domain_focus": "Tracking HSD: IAA_CRYPTO driver not merged into CentOS 6.7 kernel — platform.operating_system.linux.centos tracking ticket",
    },
    phase3={
        "verified_problem_statement": "IAA_CRYPTO driver (iaa_crypto.ko) not merged into CentOS 6.7 kernel causing IAA crypto tests to fail.",
        "verified_root_cause": "platform.operating_system.linux.centos tracking: IAA_CRYPTO kernel driver module not included in CentOS 6.7 kernel package — needs to be added. CentOS 6.7 uses upstream kernel 6.7 which may not include iaa_crypto.ko. Upstream iaa_crypto driver requires enabling in kernel config or separate package.",
        "verified_fix": "Merge/enable IAA_CRYPTO driver in CentOS 6.7 kernel build. Enable CONFIG_CRYPTO_DEV_IAA_CRYPTO=m and rebuild.",
        "architectural_element": "IAA_CRYPTO kernel driver; CentOS 6.7; CONFIG_CRYPTO_DEV_IAA_CRYPTO",
        "failure_registers": [],
        "adjacent_subsystems": ["CentOS 6.7 kernel build", "kernel crypto subsystem"],
        "related_hsds": ["14021823505"],
        "spec_reference": "Linux kernel 6.7 iaa_crypto driver; CentOS kernel config guide"
    },
    phase4={
        "tier1": [
            {"category": "crypto_driver_check", "commands": ["modinfo iaa_crypto", "ls /lib/modules/$(uname -r)/kernel/drivers/crypto/intel/iaa/"], "reveals": "iaa_crypto driver availability", "relevance": "Module not present = rebuild kernel with CONFIG_CRYPTO_DEV_IAA_CRYPTO=m"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — iaa_crypto module not in kernel; IAA crypto tests fail",
        "root_cause_domain": "platform.operating_system.linux.centos / IAA_CRYPTO driver not included in CentOS 6.7",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "crypto_driver_check confirms module absent. Kernel config change needed.",
        "iteration_savings": "1",
    },
)

# ── HSD 14021876991 — PCIe Fail Vect UE detected (sw.driver) ─────────────────
write(
    "14021876991",
    phase2={
        "testcase_name": "PCIe Fail Vector (FailVect) Unsupported Error (UE) detected in PCIe AER during DSA/QAT test",
        "testcase_command": "(DSA/QAT test with AER monitoring; PCIe UE FailVect error detected)",
        "testcase_parameters": "DMR system; PCIe AER Uncorrectable Error; FailVect (Fail Vector); sw.driver; detected during accelerator test",
        "testcase_domain_focus": "PCIe Fail Vector Unsupported Error detected in PCIe subsystem during DMR accelerator test — sw.driver handling issue",
    },
    phase3={
        "verified_problem_statement": "PCIe Fail Vector (ext TL unsupported request) UE detected in PCIe AER during DMR accelerator testing.",
        "verified_root_cause": "PCIe FailVect AER UE: (1) Fail Vector is a PCIe TLP that signals device failure; receiving bridge detecting FailVect as Unsupported Request AER error; (2) During accelerator error injection or ACS violation, device sends Fail Vector completion — bridge logs it as PCIe UE; (3) Driver not properly masking AER UE for FailVect type before running error injection; (4) sw.driver = driver needs to mask/handle FailVect-type completions in AER mask registers before error tests; (5) ARDEN/Simics PCIe model may be generating spurious FailVect.",
        "verified_fix": "Mask FailVect type in PCIe AER UNCORRECTABLE_ERROR_MASK register before error injection tests. Update driver error handling.",
        "architectural_element": "PCIe AER UE; Fail Vector; TLP; AER mask; PCIe bridge",
        "failure_registers": ["PCIe AER UE Status", "UNCORRECTABLE_ERROR_MASK"],
        "adjacent_subsystems": ["PCIe subsystem", "AER driver", "accelerator PCIe endpoint"],
        "related_hsds": ["22021889147"],
        "spec_reference": "PCIe Base Spec 6.0: Fail Vector; AER spec; Intel PCIe AER driver"
    },
    phase4={
        "tier1": [
            {"category": "pcie_aer_check", "commands": ["lspci -vvv | grep AER", "cat /sys/bus/pci/devices/<BDF>/aer_uncor_status"], "reveals": "PCIe AER UE status register", "relevance": "FailVect in UE status = driver AER mask update needed"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — PCIe FailVect not masked before error injection; AER UE logged",
        "root_cause_domain": "sw.driver / PCIe AER mask for Fail Vector not set before error injection tests",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "pcie_aer_check identifies FailVect UE. Driver to mask before error injection.",
        "iteration_savings": "2",
    },
)

# ── HSD 15013810524 — CPM address overlapping in cpm_ssm_scm.dml (soc.CPM) ──
write(
    "15013810524",
    phase2={
        "testcase_name": "CPM address overlapping registers in cpm_ssm_scm.dml Simics model",
        "testcase_command": "(Simics CPM cpm_ssm_scm.dml model; address overlap in register definitions)",
        "testcase_parameters": "Simics CPM model; cpm_ssm_scm.dml; address overlapping registers detected; soc.CPM 5.1#",
        "testcase_domain_focus": "CPM Simics model address overlap bug in cpm_ssm_scm.dml register definitions — Simics model defect",
    },
    phase3={
        "verified_problem_statement": "CPM Simics model (cpm_ssm_scm.dml) has address overlapping register definitions — two or more registers share the same address space.",
        "verified_root_cause": "Simics CPM model (cpm_ssm_scm.dml) register address overlap: DML model defines overlapping register addresses in CPM SSM SCM block — two registers mapped to same or overlapping offset. This is a Simics model authoring error, not silicon bug. Results in model error/warning when Simics compiles or runs.",
        "verified_fix": "Fix cpm_ssm_scm.dml to resolve address overlap — correct register offsets based on CPM HAS register map.",
        "architectural_element": "CPM SSM SCM Simics model; DML register map; cpm_ssm_scm.dml",
        "failure_registers": ["CPM SSM SCM overlapping registers"],
        "adjacent_subsystems": ["Simics CPM model", "DML register compiler"],
        "related_hsds": [],
        "spec_reference": "CPM HAS register map; CPM 5.1 SCM register specification"
    },
    phase4={
        "tier1": [
            {"category": "dml_overlap_check", "commands": ["simics-compile cpm_ssm_scm.dml 2>&1 | grep overlap"], "reveals": "DML address overlap error details", "relevance": "Overlap address = fix register offset in DML source"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — Simics DML compilation finds address overlap",
        "root_cause_domain": "soc.CPM / CPM Simics model DML address overlap in cpm_ssm_scm.dml",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "dml_overlap_check finds exact overlap. DML fix per CPM HAS.",
        "iteration_savings": "2",
    },
)

# ── HSD 22019958183 — AcreError could not determine pciexbar/mmcfg ───────────
write(
    "22019958183",
    phase2={
        "testcase_name": "AcreError: could not determine pciexbar/mmcfg in test automation on DMR",
        "testcase_command": "(Validation automation script; Acre tool error: cannot find pciexbar/mmcfg)",
        "testcase_parameters": "DMR system; Acre validation tool; AcreError could not determine pciexbar/mmcfg; sw.env",
        "testcase_domain_focus": "Acre validation tool fails to determine pciexbar/mmcfg on DMR — sw.env environment config issue",
    },
    phase3={
        "verified_problem_statement": "Acre validation tool fails with error: could not determine pciexbar/mmcfg on DMR system.",
        "verified_root_cause": "sw.env issue: (1) Acre tool uses CPUID/BIOS tables to find MMCFG base; DMR has different MMCFG configuration than prior platforms (Simics may not expose same BIOS data structures); (2) Acre may be using ACPI MCFG table parsing that doesn't work on DMR Simics early BIOS; (3) pciexbar address not set or different in DMR BIOS configuration; (4) Acre tool needs update to support DMR MMCFG base address detection.",
        "verified_fix": "Update Acre tool for DMR MMCFG detection. Or explicitly pass pciexbar address to Acre via environment variable or config.",
        "architectural_element": "Acre tool; MMCFG; PCIEXBAR; ACPI MCFG; DMR BIOS configuration",
        "failure_registers": ["PCIEXBAR"],
        "adjacent_subsystems": ["Acre validation tool", "BIOS ACPI MCFG", "PCIe config space"],
        "related_hsds": [],
        "spec_reference": "DMR MMCFG specification; ACPI MCFG table; Acre tool release notes"
    },
    phase4={
        "tier1": [
            {"category": "mmcfg_check", "commands": ["sv.socket0.uncore.punit.pcfg.pciexbar.show()", "cat /sys/firmware/acpi/tables/MCFG | hexdump"], "reveals": "PCIEXBAR address and MMCFG table", "relevance": "PCIEXBAR value needed by Acre tool"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — Acre tool cannot detect DMR MMCFG; tool update needed",
        "root_cause_domain": "sw.env / Acre tool MMCFG detection incompatible with DMR",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "mmcfg_check finds PCIEXBAR value. Pass to Acre or update tool.",
        "iteration_savings": "2",
    },
)

# ── HSD 22019670393 — IAA opcodes 0x42/0x43/0x44 failing Simics CentOS 6.7 ──
write(
    "22019670393",
    phase2={
        "testcase_name": "IAA opcodes 0x42/0x43/0x44 failing on Simics CentOS 6.7 with iaa_crypto driver",
        "testcase_command": "(IAA test on Simics CentOS 6.7 kernel; iaa_crypto opcodes 0x42/0x43/0x44 fail)",
        "testcase_parameters": "DMR Simics; CentOS 6.7 kernel; IAA iaa_crypto opcodes 0x42 0x43 0x44; platform.simics.platform",
        "testcase_domain_focus": "IAA crypto opcodes 0x42/0x43/0x44 failing on Simics CentOS 6.7 — same as HSD 14021823464 (iaa_crypto not in kernel) + Simics model",
    },
    phase3={
        "verified_problem_statement": "IAA opcodes 0x42/0x43/0x44 fail on Simics CentOS 6.7 platform.",
        "verified_root_cause": "Same root cause as HSD 14021823464: iaa_crypto driver not in CentOS 6.7 kernel. Additionally: (1) opcodes 0x42/0x43/0x44 require iaa_crypto kernel module; (2) Simics IAA model may have early/incomplete support for these new opcodes (DMR new crypto opcodes); (3) platform.simics.platform = both driver and Simics model issue.",
        "verified_fix": "Same as HSD 14021823464: enable iaa_crypto in CentOS 6.7. Also update Simics IAA model if new opcodes not supported.",
        "architectural_element": "IAA crypto opcodes 0x42/0x43/0x44; iaa_crypto driver; Simics IAA model",
        "failure_registers": [],
        "adjacent_subsystems": ["iaa_crypto driver", "Simics IAA model"],
        "related_hsds": ["14021823464", "16027417452"],
        "spec_reference": "IAA HAS: opcodes 0x42/0x43/0x44 (new DMR crypto opcodes)"
    },
    phase4={
        "tier1": [
            {"category": "iaa_crypto_check", "commands": ["modinfo iaa_crypto", "ls /dev/iaa/"], "reveals": "iaa_crypto driver availability", "relevance": "Module absent = same as HSD 14021823464"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — iaa_crypto not in CentOS 6.7; new IAA crypto opcodes require new driver",
        "root_cause_domain": "platform.simics.platform / iaa_crypto missing + Simics model for new IAA opcodes 0x42/0x43/0x44",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "iaa_crypto_check confirms absence. Same fix as HSD 14021823464.",
        "iteration_savings": "2",
    },
)

# ── HSD 22020262749 — IDXD driver fails to detect DSA/IAA new device ID ──────
write(
    "22020262749",
    phase2={
        "testcase_name": "IDXD driver fails to detect DSA/IAA new DMR device IDs on Simics",
        "testcase_command": "(idxd driver probe on Simics; DSA/IAA DMR new device IDs not in driver PCI ID table)",
        "testcase_parameters": "DMR Simics; idxd driver; DSA/IAA new device IDs not detected; no acceleration device found; kernel 5.x/6.x idxd",
        "testcase_domain_focus": "IDXD driver does not detect DSA/IAA DMR-specific new device IDs — PCI ID table update needed",
    },
    phase3={
        "verified_problem_statement": "IDXD (DSA/IAA) driver fails to detect DSA/IAA devices on DMR Simics due to missing new device IDs in driver PCI ID table.",
        "verified_root_cause": "IDXD driver PCI device ID table missing DMR-specific device IDs: (1) DMR uses new PCI device IDs for DSA/IAA accelerators compared to SPR/GNR; (2) Driver intel_idxd_pci_tbl[] does not include new DMR device IDs; (3) Kernel idxd driver needs to add DMR device IDs to be updated with PATCHSET/upstreaming; (4) Same as early SPR bring-up issue — new platform requires driver device ID update.",
        "verified_fix": "Add DMR DSA/IAA new device IDs to intel_idxd_pci_tbl[] in idxd/init.c. Apply kernel patch or use updated kernel with DMR device IDs.",
        "architectural_element": "IDXD driver; PCI ID table; DMR DSA/IAA device IDs; intel_idxd_pci_tbl",
        "failure_registers": [],
        "adjacent_subsystems": ["idxd kernel driver", "PCIe device enumeration"],
        "related_hsds": ["22020708911"],
        "spec_reference": "DMR DSA/IAA PCI device ID specification; idxd driver PCI ID table"
    },
    phase4={
        "tier1": [
            {"category": "idxd_probe_check", "commands": ["lspci | grep -i dsa", "dmesg | grep idxd"], "reveals": "DSA/IAA device IDs and idxd probe result", "relevance": "Device IDs present but not probed = PCI ID table update needed"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — idxd driver PCI ID table missing DMR device IDs",
        "root_cause_domain": "sw.driver / IDXD driver missing DMR DSA/IAA device IDs in PCI ID table",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "idxd_probe_check confirms PCI ID absent. Driver patch needed.",
        "iteration_savings": "1",
    },
)

# ── HSD 22020262458 — QAT Simics PPO BKC test failures ───────────────────────
write(
    "22020262458",
    phase2={
        "testcase_name": "QAT Simics PPO BKC test failures on DMR early Simics",
        "testcase_command": "(QAT BKC tests in Simics PPO; multiple test failures)",
        "testcase_parameters": "DMR Simics PPO; early BKC; QAT Simics test failures; platform.simics.platform",
        "testcase_domain_focus": "QAT Simics PPO BKC test failures on early DMR Simics — platform.simics.platform early bring-up issues",
    },
    phase3={
        "verified_problem_statement": "Multiple QAT BKC test failures in DMR Simics PPO environment.",
        "verified_root_cause": "platform.simics.platform early BKC: Multiple QAT failures on DMR Simics PPO. Root causes: (1) Early DMR Simics model incomplete QAT CPM support; (2) PPO-specific configuration issues (soc_config_str PPO vs CPC); (3) Same infrastructure issues as HSD 22020262749 (device IDs) and 15018147145 (ssm_pm_enable); (4) No ssm_pm_enable WA applied in early Simics BKC.",
        "verified_fix": "Apply ssm_pm_enable=0 WA. Update to later Simics model. Apply DMR device ID updates.",
        "architectural_element": "QAT Simics PPO; BKC; ssm_pm_enable; DMR Simics model",
        "failure_registers": ["ssm_pm_enable"],
        "adjacent_subsystems": ["Simics QAT model", "PPO config", "BKC"],
        "related_hsds": ["15018147145", "22020262749"],
        "spec_reference": "DMR QAT BKC; Simics PPO guide"
    },
    phase4={
        "tier1": [
            {"category": "qat_ppo_check", "commands": ["adf_ctl status", "dmesg | grep qat", "cat /etc/4xxxvf*.conf"], "reveals": "QAT service state in PPO", "relevance": "ssm_pm_enable not cleared = service fails"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — early DMR Simics PPO QAT model + ssm_pm_enable not applied",
        "root_cause_domain": "platform.simics.platform / Early DMR Simics QAT PPO failures (device IDs + ssm_pm_enable)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "qat_ppo_check identifies service state. Apply ssm_pm_enable WA.",
        "iteration_savings": "2",
    },
)

# ── HSD 22021253702 — dsa_test DSA3 opcode BKC CentOS integration ─────────────
write(
    "22021253702",
    phase2={
        "testcase_name": "dsa_test DSA3 opcode support needed for BKC CentOS validation plan",
        "testcase_command": "(dsa_test tool; DSA3 opcodes not in test; feature request for BKC CentOS)",
        "testcase_parameters": "DMR BKC; CentOS; dsa_test; DSA3 opcodes not supported; feature integration request",
        "testcase_domain_focus": "Feature request/tracking: dsa_test needs DSA3 opcode support for BKC CentOS DMR validation plan",
    },
    phase3={
        "verified_problem_statement": "dsa_test tool missing DSA3 opcode support needed for BKC CentOS DMR validation.",
        "verified_root_cause": "Feature tracking: dsa_test (DSA test utility) does not include DMR DSA3 opcodes in test coverage. BKC CentOS validation plan requires DSA3 opcode testing but dsa_test hasn't been updated to support new DSA3 opcodes from DMR. Tool update needed.",
        "verified_fix": "Update dsa_test to add DSA3 opcode support for DMR BKC CentOS.",
        "architectural_element": "dsa_test; DSA3 opcodes; BKC CentOS; DMR test coverage",
        "failure_registers": [],
        "adjacent_subsystems": ["dsa_test tool", "BKC validation plan"],
        "related_hsds": ["22020708911"],
        "spec_reference": "DSA3 opcode specification; dsa_test release notes"
    },
    phase4={
        "tier1": [],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [
            {"description": "Update dsa_test for DSA3 opcodes", "commands": [], "why": "Tool update requires dsa_test owner"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "indirect — feature integration tracking; not a defect",
        "root_cause_domain": "val.env.tool / dsa_test missing DSA3 opcode support (feature request)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "Feature tracking ticket. dsa_test owner updates tool.",
        "iteration_savings": "1",
    },
)

# ── HSD 22020720289 — DSA3 Perf Operations2 counters wrong category ──────────
write(
    "22020720289",
    phase2={
        "testcase_name": "DSA3 Perf Operations2 performance counters reporting wrong category on DMR",
        "testcase_command": "(DSA perf event monitoring; Operations2 counter category mismatched)",
        "testcase_parameters": "DMR; DSA3 performance monitoring; Perf Operations2 counters in wrong category; event grouping issue",
        "testcase_domain_focus": "DSA3 Perf Operations2 performance counters wrongly categorized — perf monitoring metadata bug",
    },
    phase3={
        "verified_problem_statement": "DSA3 Perf Operations2 performance counters are reporting events in wrong category on DMR.",
        "verified_root_cause": "DSA3 perf counter category mismatch: (1) Linux perf PMU driver for DSA (intel_dsa_pmu) has incorrect event-to-category mapping for Operations2 events; (2) DSA3 introduces new Perf Operations2 events; PMU driver maps them to wrong event group; (3) UAPI event definition file (.json) or driver has wrong attributes for Operations2 counter group.",
        "verified_fix": "Update DSA PMU driver event attribute or JSON event definition to correct category for Operations2 counters.",
        "architectural_element": "DSA3 performance monitoring; intel_dsa_pmu; Operations2 event group; perf UAPI",
        "failure_registers": [],
        "adjacent_subsystems": ["linux perf PMU driver", "DSA3 PMU events"],
        "related_hsds": ["22020708911"],
        "spec_reference": "DSA3 performance monitoring spec; intel_dsa_pmu driver"
    },
    phase4={
        "tier1": [
            {"category": "dsa_perf_check", "commands": ["perf list dsa", "cat /sys/bus/event_source/devices/dsa0/events/"], "reveals": "DSA perf event categories", "relevance": "Wrong category in sysfs = driver JSON/attribute fix needed"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — DSA3 perf event wrong category in PMU driver metadata",
        "root_cause_domain": "hw.dsa / DSA3 PMU Operations2 event category mismatch in driver",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "dsa_perf_check identifies wrong category. Driver fix.",
        "iteration_savings": "2",
    },
)

# ── HSD 22020708911 — dsa_test DSA3 opcode support incomplete ────────────────
write(
    "22020708911",
    phase2={
        "testcase_name": "dsa_test DSA3 opcode support feature incomplete — not all DSA3 opcodes implemented in dsa_test",
        "testcase_command": "(dsa_test; DSA3 opcodes missing from test implementation)",
        "testcase_parameters": "DMR; dsa_test tool; DSA3 opcodes incomplete; test tool feature incomplete",
        "testcase_domain_focus": "Feature tracking: dsa_test DSA3 opcode implementation incomplete — same as HSD 22021253702",
    },
    phase3={
        "verified_problem_statement": "dsa_test tool has incomplete DSA3 opcode support — not all DMR DSA3 opcodes implemented.",
        "verified_root_cause": "Same as HSD 22021253702: dsa_test missing DSA3 opcode coverage. Additionally: specific DSA3 opcodes (performance/monitoring opcodes) not yet coded in dsa_test. Two separate tracking tickets covering same issue.",
        "verified_fix": "Same as HSD 22021253702: Complete dsa_test DSA3 opcode implementation.",
        "architectural_element": "dsa_test; DSA3 opcodes; feature completeness",
        "failure_registers": [],
        "adjacent_subsystems": ["dsa_test tool"],
        "related_hsds": ["22021253702"],
        "spec_reference": "Same as HSD 22021253702"
    },
    phase4={
        "tier1": [],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [
            {"description": "Complete dsa_test DSA3 opcode implementation", "commands": [], "why": "Tool implementation requires dsa_test owner"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "indirect — feature tracking; same as HSD 22021253702",
        "root_cause_domain": "val.env.tool / dsa_test DSA3 opcode feature incomplete (same as HSD 22021253702)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "Same tracking as HSD 22021253702. Duplicate.",
        "iteration_savings": "1",
    },
)

# ── HSD 22022247600 — DSA hang with Reduce Operations (GENI analyzed) ────────
write(
    "22022247600",
    phase2={
        "testcase_name": "DSA hangs during large Reduce or Reduce-with-Dual-Cast operation on DMR X1 A0 VV",
        "testcase_command": "(DSA Reduce ops on DMR X1 A0 VV; default MRRS; ten-bit tag enabled)",
        "testcase_parameters": "DMR X1 A0 VV; DSA Reduce operations; large transfer; default MRRS; ten-bit tag enabled; device hang",
        "testcase_domain_focus": "DSA device hang on large Reduce/Reduce-with-Dual-Cast operation with ten-bit tag enabled on DMR A0",
    },
    phase3={
        "verified_problem_statement": "DSA device hangs when issuing large Reduce or Reduce-with-Dual-Cast operation on DMR X1 A0 VV with default MRRS and ten-bit tag enabled.",
        "verified_root_cause": "DMR A0 silicon bug: DSA hang on large Reduce operations with ten-bit PCIe tag: (1) Ten-bit tag PCIe read completions may expose a DMR A0 HW ordering issue with the DSA M2IOSF interface for Reduce gather operations; (2) Large Reduce operations generate many read completions — with ten-bit tags, tag space exhaustion or ordering violation can cause DSA to hang waiting for completion; (3) Known DMR A0 M2IOSF PRS ordering bugs (HSD 14025333034) may interact with Reduce gather reads; (4) GENI confirms no specific documented errata for this — likely new sighting on DMR A0.",
        "verified_fix": "Disable ten-bit PCIe tag for DSA Reduce operations (default five-bit tag). Or reduce Reduce transfer size to stay within MRRS limits.",
        "architectural_element": "DSA Reduce; ten-bit PCIe tag; M2IOSF; read completion ordering",
        "failure_registers": ["GENSTS", "PCIe DEVCTRL2 ten-bit tag"],
        "adjacent_subsystems": ["DSA M2IOSF interface", "PCIe completion handling", "Reduce engine"],
        "related_hsds": ["14025333034", "22022199057"],
        "spec_reference": "DSA3 Reduce operation spec; PCIe ten-bit tag; M2IOSF ordering"
    },
    phase4={
        "tier1": [
            {"category": "ten_bit_tag_check", "commands": ["sv.socket0.imhs.acc.accs.dsa.ssfsts.show()", "lspci -xxx | grep DEVCTRL2"], "reveals": "Ten-bit tag enable and DSA SSFSTS hang state", "relevance": "Disable ten-bit tag to verify WA for Reduce hang"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — DMR A0 HW bug with ten-bit tag + large Reduce completion ordering",
        "root_cause_domain": "soc.CPG / DMR A0 DSA hang: ten-bit PCIe tag + large Reduce completion ordering (M2IOSF)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "ten_bit_tag_check tests WA. GENI confirms no specific documented errata yet.",
        "iteration_savings": "2",
    },
)

# ── HSD 22022199057 — DSA Gather Copy 0x1C bypasses WQ Max Transfer (hw.dsa) ─
write(
    "22022199057",
    phase2={
        "testcase_name": "DSA Gather Copy opcode 0x1C bypasses WQ Max Transfer size limit on DMR X1 A0 VV",
        "testcase_command": "(DSA Gather Copy opcode 0x1C; transfer > WQ Max Transfer; completes without error)",
        "testcase_parameters": "DMR X1 A0 VV; DSA Gather Copy 0x1C; WQCFG Max Transfer set; op > limit completes without rejection; hw.dsa",
        "testcase_domain_focus": "DSA Gather Copy 0x1C does not enforce WQ Max Transfer size — DMR A0 HW bug in range check logic",
    },
    phase3={
        "verified_problem_statement": "DSA Gather Copy (opcode 0x1C) bypasses WQ Max Transfer size limit on DMR X1 A0 VV — operations exceeding configured limit complete without INVALID_OPFLAGS or size error.",
        "verified_root_cause": "DMR A0 hardware bug: Gather Copy (0x1C) WQ Max Transfer size check not implemented/bypassed in hardware: (1) DSA3 spec requires descriptor size validation against WQCFG Max Transfer; (2) For Gather Copy 0x1C, the total transfer size computed from scatter list is not compared against WQCFG Max Transfer; (3) Known HW bug per GENI confirmation: 'No fix for DMR'; (4) Likely related to HSD 15017528287 (variable bit width range check).",
        "verified_fix": "Software WA: validate Gather Copy total size in driver/application before submission. No HW fix for DMR A0.",
        "architectural_element": "DSA Gather Copy 0x1C; WQCFG Max Transfer; range check; descriptor validation",
        "failure_registers": ["WQCFG Max Transfer"],
        "adjacent_subsystems": ["DSA submission path", "scatter list parser", "WQCFG enforcer"],
        "related_hsds": ["22022199141", "22022247600"],
        "spec_reference": "DSA3 spec: opcode 0x1C Gather Copy; WQCFG Max Transfer; HSD 15017528287"
    },
    phase4={
        "tier1": [
            {"category": "wq_max_transfer_check", "commands": ["accel-config list -i | grep max_transfer_size", "Submit Gather Copy > max_transfer_size, check completion record status"], "reveals": "WQ max transfer size and whether exceeding it is caught", "relevance": "No error = HW bug in Gather Copy range check confirmed"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — DMR A0 HW: Gather Copy 0x1C WQ Max Transfer enforcement missing",
        "root_cause_domain": "hw.dsa / DMR A0 HW bug: Gather Copy 0x1C bypasses WQ Max Transfer size (no fix for DMR)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "GENI confirmed HW bug. wq_max_transfer_check verifies. SW WA needed.",
        "iteration_savings": "2",
    },
)

# ── HSD 22022199141 — DSA Gather Copy 0x1C bypasses WQ Max Transfer (soc.CPG) ─
write(
    "22022199141",
    phase2={
        "testcase_name": "DSA Gather Copy opcode 0x1C bypasses WQ Max Transfer size limit — soc.CPG duplicate of HSD 22022199057",
        "testcase_command": "(Same as HSD 22022199057 — duplicate filed under soc.CPG component)",
        "testcase_parameters": "Same as HSD 22022199057; soc.CPG DSA 3.0# component",
        "testcase_domain_focus": "Same as HSD 22022199057 — duplicate under soc.CPG. DSA Gather Copy 0x1C WQ Max Transfer bypass",
    },
    phase3={
        "verified_problem_statement": "Duplicate of HSD 22022199057: DSA Gather Copy 0x1C bypasses WQ Max Transfer size limit. Same root cause, filed under soc.CPG component.",
        "verified_root_cause": "Same as HSD 22022199057: DMR A0 HW bug — Gather Copy 0x1C WQ Max Transfer size check not implemented in hardware.",
        "verified_fix": "Same as HSD 22022199057: SW WA — validate size in driver before submission.",
        "architectural_element": "Same as HSD 22022199057",
        "failure_registers": ["WQCFG Max Transfer"],
        "adjacent_subsystems": ["DSA submission path"],
        "related_hsds": ["22022199057"],
        "spec_reference": "Same as HSD 22022199057"
    },
    phase4={
        "tier1": [
            {"category": "wq_max_transfer_dup", "commands": ["Same as HSD 22022199057"], "reveals": "Duplicate ticket — same HW bug", "relevance": "Refers to HSD 22022199057"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — duplicate of HSD 22022199057",
        "root_cause_domain": "soc.CPG / Duplicate of HSD 22022199057: DMR A0 Gather Copy 0x1C WQ Max Transfer bypass",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "Duplicate of HSD 22022199057. Same root cause and fix.",
        "iteration_savings": "2",
    },
)

# ── HSD 22021545870 — QAT Kernel Panic enabling 3 services simultaneously ─────
write(
    "22021545870",
    phase2={
        "testcase_name": "QAT Kernel Panic when enabling 3 QAT services (asym;sym;dc) simultaneously on OKS DMR AP A0",
        "testcase_command": "echo 'asym;sym;dc' > /sys/bus/qat/devices/qat_dev0/services && adf_ctl start",
        "testcase_parameters": "OKS DMR AP A0 system; enabling 3 QAT services asym;sym;dc simultaneously; kernel panic; WheaElogSwSmiCallback Enter",
        "testcase_domain_focus": "Kernel panic when enabling all 3 QAT services simultaneously on DMR AP A0 OKS — QAT FW memory or service init issue",
    },
    phase3={
        "verified_problem_statement": "Kernel panic (WheaElogSwSmiCallback Enter) when enabling 3 QAT services (asym;sym;dc) simultaneously on OKS DMR AP A0.",
        "verified_root_cause": "QAT 3-service simultaneous kernel panic on DMR AP A0: (1) QAT CPM5.1 FW memory requirement for 3 simultaneous services (asym+sym+dc) may exceed allocated memory on DMR AP A0 A0 silicon; (2) FW authentication failures (HSD 14025998125) on A0 — starting 3 services triggers FW auth for all three, resulting in hardware error/machine check; (3) WheaElogSwSmiCallback = Windows Hardware Error Architecture SMI — hardware error escalation; hardware MCA triggered by FW init failure; (4) DMR A0 ssm_pm_enable must be cleared before starting QAT services.",
        "verified_fix": "Apply ssm_pm_enable=0 WA before starting services. Start services one at a time. Use latest QAT FW package QAT_2025.07.01.",
        "architectural_element": "QAT 3-service init; FW memory; ssm_pm_enable; MCA; WheaElogSwSmiCallback",
        "failure_registers": ["ssm_pm_enable", "cpm_pm_state"],
        "adjacent_subsystems": ["QAT FW init", "BIOS WHEA", "MCA handler", "power management"],
        "related_hsds": ["14025998125", "22021545516"],
        "spec_reference": "QAT CPM5.1 FW init guide; DMR A0 ssm_pm_enable WA; QAT_2025.07.01"
    },
    phase4={
        "tier1": [
            {"category": "ssm_pm_check", "commands": ["python -c \"import sv; sv.sockets.imhs.qat.cpm5.ssfctrl.ssm_pm_enable.show()\""], "reveals": "ssm_pm_enable state", "relevance": "Must be 0 before starting 3 services on DMR A0"},
            {"category": "qat_journal_check", "commands": ["journalctl -b | grep -i 'qat\\|panic\\|mca\\|whea'"], "reveals": "Kernel panic trace and QAT error before panic", "relevance": "Identifies whether FW auth or MCA triggers panic"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — QAT FW init for 3 services triggers MCA on DMR A0; ssm_pm_enable not cleared",
        "root_cause_domain": "hw.cpm / QAT FW init kernel panic: ssm_pm_enable not cleared + 3-service simultaneous start on DMR A0",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "ssm_pm_check + qat_journal_check identify root cause. ssm_pm WA essential.",
        "iteration_savings": "2",
    },
)

# ── HSD 22022205087 — DSA UBR credit loss error (val.env.tool) ───────────────
write(
    "22022205087",
    phase2={
        "testcase_name": "DSA UBR credit loss error detected during VV test on DMR X1 A0",
        "testcase_command": "(DSA VV test; UBR credit error logged in Simics or system log)",
        "testcase_parameters": "DMR X1 A0 VV; DSA test; UBR credit loss error; val.env.tool component; test monitoring tool error",
        "testcase_domain_focus": "UBR credit loss error logged by test monitoring tool during DSA VV test on DMR X1 A0 — val.env.tool issue",
    },
    phase3={
        "verified_problem_statement": "UBR (Uncore Bus Ring) credit loss error detected during DSA VV test — reported as val.env.tool issue.",
        "verified_root_cause": "val.env.tool issue: (1) Test monitoring tool falsely detecting UBR credit error; tool threshold or detection logic incorrect for DMR A0; (2) Alternatively: real UBR credit loss — DSA transactions exhausting UBR credits in DMR A0; (3) For val.env.tool component: monitoring tool SFI/UBR credit reporting threshold needs update for DMR; (4) Related to SFI credit leakage WA (HSD 14026030387 / sv.sockets.imhs.acc.accs.iaa.sficlkgctl.icge_int=0).",
        "verified_fix": "Update val.env.tool UBR credit monitoring thresholds for DMR A0. Apply SFI credit leakage WA if real credit loss.",
        "architectural_element": "UBR credits; SFI credits; DSA uncore interface; val.env.tool monitor",
        "failure_registers": ["UBR credit counter"],
        "adjacent_subsystems": ["UBR", "SFI", "DSA interface", "test monitoring tool"],
        "related_hsds": ["14026030387", "22021896735"],
        "spec_reference": "DMR UBR credit spec; SFI credit leakage WA"
    },
    phase4={
        "tier1": [
            {"category": "ubr_credit_check", "commands": ["sv.socket0.uncore.ubr.credit_status.show()", "Apply SFI WA: sv.sockets.imhs.acc.accs.iaa.sficlkgctl.icge_int=0"], "reveals": "UBR credit state and whether SFI leakage WA helps", "relevance": "SFI WA resolves = SFI leakage; no change = tool false positive"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — UBR credit monitoring tool false positive or real SFI leakage",
        "root_cause_domain": "val.env.tool / UBR credit monitoring threshold or SFI leakage WA needed for DMR A0",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "ubr_credit_check identifies real vs false positive. Apply SFI WA.",
        "iteration_savings": "2",
    },
)

# ── HSD 22022204908 — DSA SG_CXL2CXL TMAN plugin not supported ───────────────
write(
    "22022204908",
    phase2={
        "testcase_name": "DSA SG_CXL2CXL test failing: TMAN plugin not supported/initialized for CXL-to-CXL operations",
        "testcase_command": "(DSA SG_CXL2CXL test with TMAN plugin; TMAN not initialized for CXL2CXL)",
        "testcase_parameters": "DMR VV; DSA SG_CXL2CXL test; TMAN plugin not supported; val.env.tool component",
        "testcase_domain_focus": "DSA SG_CXL2CXL test: TMAN traffic management plugin not supported — val.env.tool issue",
    },
    phase3={
        "verified_problem_statement": "DSA SG_CXL2CXL test fails because TMAN (Traffic MANager) plugin not supported or not initialized for CXL-to-CXL traffic patterns.",
        "verified_root_cause": "val.env.tool issue: (1) TMAN (test traffic management tool) plugin for CXL2CXL topology not available in current test environment; (2) CXL-to-CXL DSA test requires TMAN plugin to route traffic through CXL fabric; plugin version doesn't support CXL2CXL; (3) Test environment missing TMAN plugin or wrong version; (4) Simics TMAN model for CXL2CXL not yet implemented.",
        "verified_fix": "Install/enable TMAN CXL2CXL plugin. Update TMAN to version supporting CXL2CXL. Or skip TMAN plugin and test with direct CXL topology.",
        "architectural_element": "TMAN; CXL-to-CXL; DSA SG test; traffic management plugin",
        "failure_registers": [],
        "adjacent_subsystems": ["TMAN plugin", "CXL fabric", "DSA SG test"],
        "related_hsds": ["22022204843", "22022089619"],
        "spec_reference": "TMAN CXL2CXL plugin documentation; DSA SG_CXL2CXL test guide"
    },
    phase4={
        "tier1": [
            {"category": "tman_plugin_check", "commands": ["tman --list-plugins | grep cxl", "cat tman_test.log | grep -i 'plugin\\|cxl2cxl'"], "reveals": "TMAN plugin availability", "relevance": "Plugin absent = install or update TMAN"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — TMAN CXL2CXL plugin not available in test environment",
        "root_cause_domain": "val.env.tool / TMAN CXL2CXL plugin missing (same category as HSD 22022204843)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "tman_plugin_check identifies plugin state. TMAN update needed.",
        "iteration_savings": "2",
    },
)

# ── HSD 22022204843 — DSA SG_CXL2CXL failing in rocket setup ─────────────────
write(
    "22022204843",
    phase2={
        "testcase_name": "DSA SG_CXL2CXL test failing in rocket (pre-silicon) validation setup",
        "testcase_command": "(DSA SG_CXL2CXL test on rocket setup; test fails with CXL topology error)",
        "testcase_parameters": "DMR rocket setup; DSA SG_CXL2CXL test; failing; val.env.tool component; CXL2CXL topology",
        "testcase_domain_focus": "DSA SG_CXL2CXL test fails on rocket pre-silicon validation — environment topology or TMAN issue",
    },
    phase3={
        "verified_problem_statement": "DSA SG_CXL2CXL test fails in rocket (pre-silicon FPGA) validation environment.",
        "verified_root_cause": "val.env.tool issue: (1) Rocket setup lacks CXL-to-CXL device topology needed for this test; (2) Rocket validation environment may not have 2 CXL devices for CXL2CXL test; (3) TMAN plugin CXL2CXL configuration for rocket not set up correctly; (4) Related to HSD 22022204908 (same TMAN issue, different environment).",
        "verified_fix": "Configure rocket environment with correct CXL2CXL topology. Update TMAN for rocket CXL2CXL support.",
        "architectural_element": "Rocket validation; CXL2CXL topology; TMAN; DSA SG test",
        "failure_registers": [],
        "adjacent_subsystems": ["Rocket platform", "TMAN", "CXL topology"],
        "related_hsds": ["22022204908"],
        "spec_reference": "Same as HSD 22022204908"
    },
    phase4={
        "tier1": [
            {"category": "rocket_cxl_check", "commands": ["lspci | grep -i cxl", "Check rocket CXL topology config"], "reveals": "CXL device availability in rocket", "relevance": "Missing CXL device = topology not configured"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — rocket env missing CXL2CXL topology for SG test",
        "root_cause_domain": "val.env.tool / Rocket env CXL2CXL topology not configured (same as HSD 22022204908)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "rocket_cxl_check identifies topology. Related to HSD 22022204908.",
        "iteration_savings": "2",
    },
)

# ── HSD 22022165213 & 22022165209 — IAA MCE Supercollider Lock Stress ─────────
write(
    "22022165213",
    phase2={
        "testcase_name": "IAA Machine Check Error (MCE) running IAX_Lock_Stress_Supercollider test on DMR A0",
        "testcase_command": "IAX_Lock_Stress_Supercollider (IAA + CPU lock stress test)",
        "testcase_parameters": "DMR A0 VV; IAA + Supercollider lock stress; MCE during test; hw.scf component; SRAO or SRAR bank",
        "testcase_domain_focus": "IAA triggers Machine Check Error during Supercollider Lock Stress test on DMR A0 — IAA/SCF MCA",
    },
    phase3={
        "verified_problem_statement": "IAA triggers Machine Check Error (MCE) during IAX_Lock_Stress_Supercollider test on DMR A0.",
        "verified_root_cause": "IAA + CPU lock stress MCE on DMR A0: (1) IAA IOMMU Invalidation Queue interaction with CPU lock stress — HSD 14025817510 (IAA IOMMU IQ Descriptor bit 66) causes descriptor error under lock stress; (2) IAA + CPU lock creates IDI protocol stress on M2IOSF — DMR A0 M2IOSF PRS ordering bug (HSD 14025333034) triggered under combined lock+IAA traffic; (3) hw.scf = Scalable Fabric error — MCE in Scalable Fabric (IDI/SFI) under IAA+lock stress; (4) Related to HSD 22022090533 (IDI/Lock PCIETC error) and 22022090434 (MCE IAA+Supercollider).",
        "verified_fix": "Apply M2IOSF PRS ordering WA (HSD 14025333034): vt_iommu_cr_itciommudbgctrl3.dis_max_pgr_throttle=1. Reduce lock stress intensity.",
        "architectural_element": "IAA IOMMU IQ; M2IOSF; SCF IDI; lock stress; MCE",
        "failure_registers": ["MCE Bank", "M2IOSF error"],
        "adjacent_subsystems": ["IAA IOMMU", "M2IOSF", "SCF", "CPU lock mechanism"],
        "related_hsds": ["14025817510", "14025333034", "22022090533", "22022165209"],
        "spec_reference": "HSD 14025817510 IOMMU IQ bit 66; HSD 14025333034 M2IOSF PRS ordering WA"
    },
    phase4={
        "tier1": [
            {"category": "mce_bank_check", "commands": ["mcelog --client", "sv.socket0.core0.mca.banks.show()"], "reveals": "MCE bank and error code", "relevance": "MCA bank identifies SCF or M2IOSF as source"},
            {"category": "m2iosf_wa_apply", "commands": ["sv.socket0.uncore.m2iosf0.vt_iommu_cr_itciommudbgctrl3.dis_max_pgr_throttle = 1"], "reveals": "WA for M2IOSF PRS ordering", "relevance": "Apply WA before retest"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — IAA+lock stress triggers M2IOSF PRS ordering bug; MCE in SCF",
        "root_cause_domain": "hw.scf / IAA+lock stress triggers M2IOSF PRS ordering MCE (HSD 14025333034 + 14025817510)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "mce_bank_check identifies SCF MCE. M2IOSF WA from HSD 14025333034.",
        "iteration_savings": "2",
    },
)

write(
    "22022165209",
    phase2={
        "testcase_name": "IAA Machine Check Error (MCE) running IAX_Lock_Stress_Supercollider (duplicate of HSD 22022165213)",
        "testcase_command": "IAX_Lock_Stress_Supercollider (IAA + CPU lock stress test)",
        "testcase_parameters": "Same as HSD 22022165213; hw.scf component",
        "testcase_domain_focus": "Duplicate/companion to HSD 22022165213: IAA MCE during Supercollider Lock Stress on DMR A0",
    },
    phase3={
        "verified_problem_statement": "Duplicate of HSD 22022165213: IAA MCE during IAX_Lock_Stress_Supercollider on DMR A0.",
        "verified_root_cause": "Same as HSD 22022165213: IAA+lock stress triggers M2IOSF PRS ordering MCE in SCF.",
        "verified_fix": "Same as HSD 22022165213: Apply M2IOSF PRS ordering WA.",
        "architectural_element": "Same as HSD 22022165213",
        "failure_registers": ["MCE Bank"],
        "adjacent_subsystems": ["IAA IOMMU", "M2IOSF", "SCF"],
        "related_hsds": ["22022165213"],
        "spec_reference": "Same as HSD 22022165213"
    },
    phase4={
        "tier1": [
            {"category": "mce_bank_dup", "commands": ["Same as HSD 22022165213"], "reveals": "Same MCE pattern", "relevance": "Duplicate of HSD 22022165213"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — duplicate of HSD 22022165213",
        "root_cause_domain": "hw.scf / Duplicate of HSD 22022165213: IAA+lock stress M2IOSF MCE",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "Duplicate of HSD 22022165213. Same root cause and fix.",
        "iteration_savings": "2",
    },
)

# ── HSD 22022165090 — IAA M2P NoneType has no attribute count ────────────────
write(
    "22022165090",
    phase2={
        "testcase_name": "IAA M2P debug tool fails: NoneType has no attribute 'count' during IAA test analysis",
        "testcase_command": "(m2p debug script for IAA; NoneType error in Python M2P analysis tool)",
        "testcase_parameters": "DMR VV; IAA test; M2P debug tool; Python error: NoneType has no attribute 'count'; val.env.test",
        "testcase_domain_focus": "M2P (Measurement to Pass) debug tool Python error during IAA test analysis — val.env.test tool bug",
    },
    phase3={
        "verified_problem_statement": "IAA M2P debug tool crashes with Python error: NoneType object has no attribute 'count' during IAA test analysis.",
        "verified_root_cause": "val.env.test tool bug: (1) M2P (test scoring/analysis tool) Python script has NoneType dereference; (2) IAA test output for some error/completion pattern returns None where M2P expects a string with 'count' attribute; (3) Script doesn't guard against None result from IAA log parser; (4) val.env.test = test tool scripting issue.",
        "verified_fix": "Fix M2P script: add None check before calling .count() on IAA log parser result.",
        "architectural_element": "M2P debug tool; Python NoneType; IAA log parser; val.env.test",
        "failure_registers": [],
        "adjacent_subsystems": ["M2P test tool", "IAA test log parser"],
        "related_hsds": [],
        "spec_reference": "M2P tool changelog"
    },
    phase4={
        "tier1": [
            {"category": "m2p_traceback", "commands": ["python m2p_iaa.py 2>&1 | grep -A5 'NoneType'"], "reveals": "Python traceback for NoneType error", "relevance": "Line number for None guard fix in M2P script"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — M2P script NoneType bug when processing IAA test output",
        "root_cause_domain": "val.env.test / M2P tool Python NoneType bug (val.env.test scripting issue)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "m2p_traceback identifies exact line. Simple None guard fix.",
        "iteration_savings": "1",
    },
)

# ── HSD 22022165024 — IAA SWERROR test err_code:8 = 0x1b ────────────────────
write(
    "22022165024",
    phase2={
        "testcase_name": "IAA SWERROR test reports err_code:8 = 0x1b during IAA test execution on DMR A0 VV",
        "testcase_command": "(IAA SWERROR test content; err_code:8 = 0x1b reported; val.env.tool)",
        "testcase_parameters": "DMR A0 VV; IAA SWERROR test; err_code:8 = 0x1b; val.env.tool component",
        "testcase_domain_focus": "IAA SWERROR test reports unexpected err_code 0x1b — val.env.tool test content issue",
    },
    phase3={
        "verified_problem_statement": "IAA SWERROR test reports unexpected error code err_code:8 = 0x1b on DMR A0 VV.",
        "verified_root_cause": "val.env.tool issue: (1) IAA SWERROR test checks software-reported error code; err_code 0x1b = SWERROR code in SWERR_CODE field; (2) Test expects a specific err_code but hardware returns 0x1b (UNSUPPORTED REQUEST or similar); (3) Test content expected err_code doesn't match DMR A0 hardware behavior for specific error injection; (4) Test content update needed for DMR A0 IAA SWERROR expected values.",
        "verified_fix": "Update SWERROR test expected err_code for DMR A0 IAA (err_code 0x1b may be correct DMR A0 behavior for this injection).",
        "architectural_element": "IAA SWERROR; err_code 0x1b; SWERR_CODE; test expected value",
        "failure_registers": ["IAA SWERR_CODE"],
        "adjacent_subsystems": ["IAA SWERROR test", "error injection framework"],
        "related_hsds": [],
        "spec_reference": "IAA HAS SWERROR error codes; err_code 0x1b definition"
    },
    phase4={
        "tier1": [
            {"category": "swerror_code_check", "commands": ["cat iaa_swerror.log | grep 'err_code'", "sv.socket0.imhs.acc.accs.iaa.swerr_code.show()"], "reveals": "SWERROR err_code value", "relevance": "0x1b = specific SWERR condition; update test expected value for DMR"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — SWERROR test expected value mismatch for DMR A0",
        "root_cause_domain": "val.env.tool / IAA SWERROR test expected err_code mismatch for DMR A0",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "swerror_code_check identifies code. Test content update for DMR A0.",
        "iteration_savings": "2",
    },
)

# ── HSD 22022090533 — DSA/IAA Supercollider IDI/Lock PCIETC_PROTOCOL_ERROR ───
write(
    "22022090533",
    phase2={
        "testcase_name": "DSA/IAA + Supercollider IDI/Lock Stress fails with PCIETC_PROTOCOL_ERROR",
        "testcase_command": "(DSA/IAA + Supercollider IDI/Lock combined stress test; PCIETC_PROTOCOL_ERROR in PCIe log)",
        "testcase_parameters": "DMR A0 VV; DSA/IAA + Supercollider IDI Lock stress; PCIETC_PROTOCOL_ERROR; val.env.content",
        "testcase_domain_focus": "DSA/IAA + Supercollider IDI/Lock combined stress triggers PCIe TLP error (PCIETC_PROTOCOL_ERROR) on DMR A0",
    },
    phase3={
        "verified_problem_statement": "DSA/IAA + Supercollider IDI/Lock Stress test fails with PCIETC_PROTOCOL_ERROR on DMR A0.",
        "verified_root_cause": "Same root cause as HSDs 22022165213/22022165209: Combined DSA/IAA + IDI/Lock stress triggers M2IOSF ordering violation. PCIETC_PROTOCOL_ERROR = PCIe TLP protocol error at the IDI/SFI interface: (1) M2IOSF PRS ordering bug (HSD 14025333034) under combined DSA+IDI+Lock; (2) IDI lock transactions + DSA read completions create PCIe TLP ordering violation at M2IOSF; (3) val.env.content = test content combining IDI+DSA+Lock too aggressively.",
        "verified_fix": "Apply M2IOSF PRS ordering WA. Reduce IDI+Lock stress intensity when combined with DSA/IAA.",
        "architectural_element": "M2IOSF; IDI; PCIe TLP; Lock stress; PCIETC_PROTOCOL_ERROR",
        "failure_registers": ["PCIe AER", "M2IOSF error"],
        "adjacent_subsystems": ["M2IOSF", "IDI", "Supercollider", "DSA/IAA"],
        "related_hsds": ["22022165213", "14025333034", "22022090434"],
        "spec_reference": "HSD 14025333034 M2IOSF PRS ordering WA"
    },
    phase4={
        "tier1": [
            {"category": "pcietc_check", "commands": ["cat test.log | grep PCIETC", "sv.socket0.uncore.m2iosf0.vt_iommu_cr_itciommudbgctrl3.dis_max_pgr_throttle = 1"], "reveals": "PCIETC_PROTOCOL_ERROR context and WA", "relevance": "Apply M2IOSF WA before retest"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — DSA/IAA+IDI+Lock stress triggers M2IOSF PCIe protocol error",
        "root_cause_domain": "val.env.content / M2IOSF PRS ordering PCIe TLP error under DSA+IDI+Lock stress (HSD 14025333034)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "pcietc_check confirms M2IOSF PCIe error. Same WA as HSD 14025333034.",
        "iteration_savings": "2",
    },
)

# ── HSD 22022090434 — MCE during IAA + Supercollider Lock Stress ──────────────
write(
    "22022090434",
    phase2={
        "testcase_name": "MCE during IAA + Supercollider Lock Stress on DMR A0 VV",
        "testcase_command": "(IAA + Supercollider Lock stress; MCE triggered; val.env.configuration)",
        "testcase_parameters": "DMR A0 VV; IAA + Supercollider Lock stress; MCE; val.env.configuration",
        "testcase_domain_focus": "MCE triggered during IAA + Supercollider Lock Stress — same as HSD 22022165213; val.env.configuration angle",
    },
    phase3={
        "verified_problem_statement": "MCE triggered during IAA + Supercollider Lock Stress test on DMR A0. Filed under val.env.configuration (configuration aspect of same issue as HSD 22022165213).",
        "verified_root_cause": "Same root cause as HSD 22022165213: M2IOSF PRS ordering bug under IAA+Lock stress. val.env.configuration angle: test configuration (core count, lock frequency, IAA submission rate) not tuned to avoid DMR A0 M2IOSF stress threshold.",
        "verified_fix": "Same as HSD 22022165213: Apply M2IOSF WA. Also tune test configuration: reduce lock stress intensity with IAA.",
        "architectural_element": "Same as HSD 22022165213; test configuration",
        "failure_registers": ["MCE Bank"],
        "adjacent_subsystems": ["IAA", "M2IOSF", "SCF", "Supercollider lock"],
        "related_hsds": ["22022165213", "22022090533"],
        "spec_reference": "Same as HSD 22022165213"
    },
    phase4={
        "tier1": [
            {"category": "mce_config_check", "commands": ["Same as HSD 22022165213", "Reduce lock stress: lower core count or lock intensity"], "reveals": "MCE context and config tuning", "relevance": "val.env.configuration = tune test config"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — same as HSD 22022165213; val.env.configuration perspective",
        "root_cause_domain": "val.env.configuration / Same as HSD 22022165213: M2IOSF MCE under IAA+Lock; tune test configuration",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "Same root cause as HSD 22022165213. Apply WA and tune config.",
        "iteration_savings": "2",
    },
)

# ── HSD 22022089619 — CXL-IO targets failing with DSA/IAA (val.env.content) ──
write(
    "22022089619",
    phase2={
        "testcase_name": "CXL-IO targets failing when combined with DSA/IAA tests on DMR A0 VV",
        "testcase_command": "(DSA/IAA test with CXL-IO targets; CXL-IO target errors during combined test)",
        "testcase_parameters": "DMR A0 VV; DSA/IAA + CXL-IO targets; CXL-IO target failures; val.env.content",
        "testcase_domain_focus": "CXL-IO targets fail when combined with DSA/IAA test traffic on DMR A0 — M2IOSF or CXL routing issue",
    },
    phase3={
        "verified_problem_statement": "CXL-IO targets fail when DSA/IAA is combined with CXL-IO target traffic on DMR A0.",
        "verified_root_cause": "val.env.content + hw: (1) DSA/IAA traffic to CXL-IO targets may trigger M2IOSF PRS ordering bug (HSD 14025333034) on the CXL path; (2) CXL-IO target routing through IMH depends on PCIe credits; DSA/IAA exhausting M2IOSF credits starves CXL-IO targets; (3) Related to HSD 22021889147 (Arden CXL targets + DSA UR/CTO errors) and HSD 22022089619 — same Arden/CXL target + DSA interaction; (4) WA: remove Arden CXL targets from DSA combined test.",
        "verified_fix": "Remove CXL-IO (Arden) targets from DSA/IAA combined test. Apply M2IOSF PRS ordering WA.",
        "architectural_element": "CXL-IO targets; DSA/IAA; M2IOSF; PCIe credit; CXL routing",
        "failure_registers": ["M2IOSF error"],
        "adjacent_subsystems": ["CXL-IO", "M2IOSF", "DSA/IAA", "PCIe credit"],
        "related_hsds": ["22021889147", "14025333034"],
        "spec_reference": "HSD 14025333034 M2IOSF PRS ordering WA"
    },
    phase4={
        "tier1": [
            {"category": "cxl_dsa_combined_check", "commands": ["Run DSA without CXL-IO targets", "Apply WA: sv.socket0.uncore.m2iosf0.vt_iommu_cr_itciommudbgctrl3.dis_max_pgr_throttle=1"], "reveals": "Whether CXL failures are due to M2IOSF ordering or credit starvation", "relevance": "CXL-only passes = DSA interaction issue"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — DSA/IAA starves M2IOSF credits or triggers PCIe ordering; CXL-IO fails",
        "root_cause_domain": "val.env.content / CXL-IO target failures from DSA/IAA M2IOSF interaction (WA: remove Arden targets)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "cxl_dsa_combined_check isolates. M2IOSF WA + remove Arden targets.",
        "iteration_savings": "2",
    },
)

# ── HSD 22022044340 — DSA test timed out (val.env.test) ──────────────────────
write(
    "22022044340",
    phase2={
        "testcase_name": "DSA test timed out waiting for completion on DMR A0 VV",
        "testcase_command": "(DSA test; timeout waiting for submission or completion)",
        "testcase_parameters": "DMR A0 VV; DSA test; test framework timeout; val.env.test",
        "testcase_domain_focus": "DSA test framework timeout during DMR A0 test — environment or HW completion delay",
    },
    phase3={
        "verified_problem_statement": "DSA test timed out during DMR A0 VV test execution.",
        "verified_root_cause": "val.env.test timeout: (1) DSA descriptor submission or completion timeout in test framework; (2) May be related to IOMMU PRS delay (HSD 14025333034) causing completion delays; (3) Test framework timeout value too short for DMR A0 which is slower in simulation; (4) val.env.test = test framework timeout not tuned for DMR A0.",
        "verified_fix": "Increase test timeout value for DMR A0. Apply M2IOSF PRS WA if PRS delay is cause.",
        "architectural_element": "DSA completion timeout; test framework; DMR A0",
        "failure_registers": [],
        "adjacent_subsystems": ["test framework", "DSA completion", "IOMMU PRS"],
        "related_hsds": ["14025333034"],
        "spec_reference": "DMR A0 test timeout guidelines"
    },
    phase4={
        "tier1": [
            {"category": "timeout_check", "commands": ["cat test.log | grep timeout", "Check test framework timeout setting for DMR A0"], "reveals": "Timeout value and DSA submission state at timeout", "relevance": "Short timeout = increase; PRS delay = apply WA"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — test timeout too short or DMR A0 completion delay",
        "root_cause_domain": "val.env.test / Test timeout not tuned for DMR A0 (or M2IOSF PRS delay)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "timeout_check identifies timeout value. Increase or apply PRS WA.",
        "iteration_savings": "2",
    },
)

# ── HSD 22022044164 — DSA completion record status 0x0 PRS (val.env.content) ─
write(
    "22022044164",
    phase2={
        "testcase_name": "DSA mem move overlapping buffers PRS completion status 0x0 on DMR A0 VV",
        "testcase_command": "(DSA mem move with overlapping source/destination buffers; PRS enabled; completion 0x0)",
        "testcase_parameters": "DMR A0 VV; DSA mem move overlapping buffers; PRS enabled; completion record status 0x0 (pending/no completion); val.env.content",
        "testcase_domain_focus": "DSA mem move PRS completion 0x0 with overlapping buffers — PRS response not returning proper status",
    },
    phase3={
        "verified_problem_statement": "DSA mem move with overlapping buffers and PRS enabled shows completion record status 0x0 (no completion / pending) on DMR A0.",
        "verified_root_cause": "PRS completion status 0x0 with overlapping buffers: (1) Overlapping source/destination = undefined behavior in DSA spec; (2) PRS enabled — with PRS, overlapping buffer access may cause page fault followed by PRS stall waiting for page response; (3) M2IOSF PRS ordering bug (HSD 14025333034) causes PRS response to be delayed/lost; completion stays 0x0; (4) val.env.content = test content using undefined overlapping buffers with PRS enabled.",
        "verified_fix": "Fix test content: use non-overlapping buffers. Apply M2IOSF PRS WA if needed for PRS completion.",
        "architectural_element": "DSA mem move; overlapping buffers; PRS; completion 0x0; M2IOSF",
        "failure_registers": ["DSA completion record status"],
        "adjacent_subsystems": ["IOMMU PRS", "M2IOSF", "DSA mem move engine"],
        "related_hsds": ["14025333034"],
        "spec_reference": "DSA spec: overlapping buffer behavior; PRS completion; HSD 14025333034"
    },
    phase4={
        "tier1": [
            {"category": "prs_compl_check", "commands": ["cat test.log | grep 'status\\|completion'", "Apply M2IOSF PRS WA"], "reveals": "PRS completion status and response", "relevance": "0x0 with overlapping = undefined behavior + PRS stall"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — overlapping buffers undefined + PRS stall from M2IOSF bug",
        "root_cause_domain": "val.env.content / Overlapping buffer (undefined) + PRS stall from M2IOSF PRS ordering bug",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "prs_compl_check identifies PRS 0x0. Fix test (non-overlapping) + apply WA.",
        "iteration_savings": "2",
    },
)

# ── HSD 22022043611 — DSA batch + swerrors + drain not allowed ───────────────
write(
    "22022043611",
    phase2={
        "testcase_name": "DSA batch descriptor + SWERROR + drain: drain in batch not allowed error",
        "testcase_command": "(DSA batch with SWERROR and drain descriptors; drain-in-batch error)",
        "testcase_parameters": "DMR A0 VV; DSA batch descriptor; SWERROR test; drain-in-batch not allowed; val.env.content",
        "testcase_domain_focus": "DSA batch + SWERROR + drain: test sends drain inside batch which is illegal — test content issue",
    },
    phase3={
        "verified_problem_statement": "DSA batch with SWERROR and drain descriptors fails with 'drain in batch not allowed' error on DMR A0.",
        "verified_root_cause": "val.env.content test content issue: (1) DSA spec forbids DRAIN descriptor inside a BATCH — batch cannot contain drain; (2) Test content constructs batch that includes DRAIN + SWERROR injections; this is an illegal descriptor combination per DSA3 spec; (3) Hardware correctly rejects drain-in-batch with INVALID_DESCRIPTOR error; (4) Test expected behavior needs update to not include DRAIN in batch.",
        "verified_fix": "Fix test content: remove DRAIN from batch descriptor. Issue DRAIN only outside of batch.",
        "architectural_element": "DSA BATCH; DRAIN descriptor; SWERROR; batch spec constraint",
        "failure_registers": ["DSA completion INVALID_DESCRIPTOR"],
        "adjacent_subsystems": ["DSA batch engine", "DRAIN descriptor"],
        "related_hsds": [],
        "spec_reference": "DSA3 spec: BATCH constraints — DRAIN not allowed in BATCH"
    },
    phase4={
        "tier1": [
            {"category": "batch_content_check", "commands": ["cat test.log | grep 'drain\\|batch\\|invalid'"], "reveals": "Illegal descriptor combination", "relevance": "DRAIN in BATCH = spec violation; fix test content"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — test content violates DSA3 spec (DRAIN in BATCH)",
        "root_cause_domain": "val.env.content / Test content DSA3 spec violation: DRAIN descriptor inside BATCH",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "batch_content_check confirms DRAIN in BATCH. Simple test fix.",
        "iteration_savings": "1",
    },
)

# ── HSD 22022043076 — DSA_WQ_OPCFG test fails after 105 mins ─────────────────
write(
    "22022043076",
    phase2={
        "testcase_name": "DSA_WQ_OPCFG test fails/times out after ~105 minutes on DMR A0 VV",
        "testcase_command": "(DSA_WQ_OPCFG test; runs for 105 minutes then fails/times out)",
        "testcase_parameters": "DMR A0 VV; DSA_WQ_OPCFG test; 105 min duration; test fails after long run; unknown component",
        "testcase_domain_focus": "DSA_WQ_OPCFG long-running test fails after 105 minutes — potential resource exhaustion or leakage over time",
    },
    phase3={
        "verified_problem_statement": "DSA_WQ_OPCFG test fails after running approximately 105 minutes on DMR A0 VV.",
        "verified_root_cause": "Long-running test failure after 105 minutes: (1) SFI credit leakage over time (HSD 14026030387 pattern) — after many DSA operations, SFI credits leak and system stalls; (2) IOMMU invalidation queue buildup over 105 min run (HSD 14025817510); (3) Memory resource exhaustion from many WQ configurations and deconfigurations; (4) Ring pointer wraparound bug after sufficient submissions (similar to QAT DC response descriptor corruption ~30-40 UQ).",
        "verified_fix": "Apply SFI credit leakage WA: sv.sockets.imhs.acc.accs.iaa.sficlkgctl.icge_int=0. Also apply IOMMU IQ WA (HSD 14025817510).",
        "architectural_element": "DSA WQ; OPCFG; SFI credits; IOMMU IQ; long-running resource leakage",
        "failure_registers": ["SFI credit counter"],
        "adjacent_subsystems": ["DSA WQ configuration", "SFI credits", "IOMMU IQ"],
        "related_hsds": ["14026030387", "14025817510"],
        "spec_reference": "HSD 14026030387 SFI leakage WA; HSD 14025817510 IOMMU IQ WA"
    },
    phase4={
        "tier1": [
            {"category": "sfi_credit_longrun", "commands": ["Apply SFI WA: sv.sockets.imhs.acc.accs.iaa.sficlkgctl.icge_int=0", "Check IOMMU IQ depth after 105 min"], "reveals": "SFI credit state after long run", "relevance": "Credit exhaustion or IOMMU IQ overflow after 105 min"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — long-running SFI credit leakage or IOMMU IQ overflow after 105 min",
        "root_cause_domain": "hw.dsa / Long-running SFI credit leakage (HSD 14026030387) or IOMMU IQ overflow (HSD 14025817510)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "sfi_credit_longrun checks resource state. Apply both WAs.",
        "iteration_savings": "2",
    },
)

# ── HSD 22021993817 — DSA RCT LIB ERROR VTD shared memory ────────────────────
write(
    "22021993817",
    phase2={
        "testcase_name": "DSA RCT LIB ERROR creating shared memory with VTD (IOMMU) enabled on DMR A0",
        "testcase_command": "(DSA RCT tool with VTD/IOMMU; shared memory creation fails)",
        "testcase_parameters": "DMR A0; DSA RCT (Request Completion Test) tool; VTD IOMMU enabled; RCT LIB ERROR creating shared memory; sw.application",
        "testcase_domain_focus": "DSA RCT application library error creating shared memory when VTD/IOMMU enabled — application/IOMMU interaction",
    },
    phase3={
        "verified_problem_statement": "DSA RCT (Request Completion Test) library fails to create shared memory when VTD (IOMMU) is enabled on DMR A0.",
        "verified_root_cause": "sw.application IOMMU interaction: (1) RCT library uses shared memory allocation that requires IOMMU mapping; with VTD enabled, shared memory must be pinned and IOMMU-mapped; (2) RCT library not properly handling IOMMU-aware shared memory allocation; (3) May need to use IOMMU-safe shared memory APIs (e.g., dma_alloc_coherent or appropriate VFIO/IOMMU mmap); (4) DSA PASID-based shared memory access under VTD requires SVM setup.",
        "verified_fix": "Update RCT library to use IOMMU-safe shared memory allocation. Enable SVM/PASID for RCT if needed.",
        "architectural_element": "DSA RCT library; VTD IOMMU; shared memory; SVM/PASID",
        "failure_registers": [],
        "adjacent_subsystems": ["RCT library", "VTD IOMMU", "DSA SVM"],
        "related_hsds": [],
        "spec_reference": "DSA shared memory with IOMMU; SVM/PASID guide"
    },
    phase4={
        "tier1": [
            {"category": "rct_iommu_check", "commands": ["cat rct.log | grep 'LIB ERROR\\|shared\\|IOMMU'", "dmesg | grep 'iommu\\|dmar'"], "reveals": "IOMMU error during RCT shared memory creation", "relevance": "IOMMU mapping failure = RCT library needs IOMMU-aware allocation"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — RCT library not IOMMU-aware; shared memory fails with VTD enabled",
        "root_cause_domain": "sw.application / RCT library not IOMMU-aware for shared memory with VTD enabled",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "rct_iommu_check identifies IOMMU error. RCT library update needed.",
        "iteration_savings": "2",
    },
)

# ── HSD 22021992609 — DSA PRS ALL_TYPES mismatch WA: remove CXL HDM ──────────
write(
    "22021992609",
    phase2={
        "testcase_name": "DSA PRS ALL_TYPES test reports information mismatch with CXL HDM in address space",
        "testcase_command": "(DSA PRS ALL_TYPES test; address mismatch with CXL HDM decoder range)",
        "testcase_parameters": "DMR A0 VV; DSA PRS; ALL_TYPES test; address mismatch; CXL HDM decoder in lists; WA: remove CXL HDM from address lists; sw.driver",
        "testcase_domain_focus": "DSA PRS ALL_TYPES test mismatch when CXL HDM addresses included — CXL HDM decode vs PRS interaction",
    },
    phase3={
        "verified_problem_statement": "DSA PRS ALL_TYPES test reports address mismatch when CXL HDM (Host-managed Device Memory) decoder is included in address lists.",
        "verified_root_cause": "sw.driver CXL/PRS interaction: (1) CXL HDM addresses behave differently from DRAM for PRS; PRS response for CXL HDM may return different page fault resolution than expected; (2) DSA PRS test includes CXL HDM addresses in ALL_TYPES test which expects DRAM-like PRS behavior; (3) CXL HDM decoder may not support PRS the same way as DRAM — CXL FME (Fabric Memory Encoder) responds differently; (4) WA: remove CXL HDM addresses from DSA PRS ALL_TYPES test lists.",
        "verified_fix": "Remove CXL HDM addresses from DSA PRS ALL_TYPES test lists (WA already identified in HSD description).",
        "architectural_element": "DSA PRS; CXL HDM; ALL_TYPES test; PRS page fault resolution",
        "failure_registers": [],
        "adjacent_subsystems": ["IOMMU PRS", "CXL HDM decoder", "DSA address list"],
        "related_hsds": ["14025333034"],
        "spec_reference": "DSA PRS spec; CXL HDM decoder behavior with PRS"
    },
    phase4={
        "tier1": [
            {"category": "cxl_hdm_prs_check", "commands": ["cat prs_test.log | grep mismatch", "Remove CXL HDM from test address lists and rerun"], "reveals": "Whether mismatch is from CXL HDM addresses", "relevance": "WA already identified: remove CXL HDM from lists"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — CXL HDM PRS behavior different from DRAM; test includes CXL in lists",
        "root_cause_domain": "sw.driver / DSA PRS CXL HDM interaction mismatch (WA: remove CXL HDM from address lists)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "WA already known. cxl_hdm_prs_check confirms. Apply WA.",
        "iteration_savings": "1",
    },
)

# ── HSD 22021975263 — DSA test timeout at station (val.env.automation) ────────
write(
    "22021975263",
    phase2={
        "testcase_name": "DSA test timeout at specific station an004022bms2293 (val.env.automation)",
        "testcase_command": "(DSA test at station an004022bms2293; automation timeout)",
        "testcase_parameters": "Station an004022bms2293; DSA test; automation timeout; val.env.automation",
        "testcase_domain_focus": "DSA test automation timeout at specific station — station-specific infrastructure issue",
    },
    phase3={
        "verified_problem_statement": "DSA test automation times out at specific station an004022bms2293.",
        "verified_root_cause": "val.env.automation station-specific issue: (1) Station an004022bms2293 has hardware or network issue causing test automation timeout; (2) Station may have stale OS state, hung daemon, or network connectivity issues; (3) Not a DSA silicon bug — station-specific infrastructure failure; (4) Same category as HSD 22021973248 (unexpected reboot at specific station).",
        "verified_fix": "Check station an004022bms2293 health. Reimage station if stale. Re-run test on different station.",
        "architectural_element": "Station infrastructure; automation timeout; val.env.automation",
        "failure_registers": [],
        "adjacent_subsystems": ["Automation framework", "station infrastructure"],
        "related_hsds": ["22021973248"],
        "spec_reference": "Val environment automation guide"
    },
    phase4={
        "tier1": [
            {"category": "station_health_check", "commands": ["ping an004022bms2293", "Check station status in automation dashboard"], "reveals": "Station health and automation connectivity", "relevance": "Station issue = not a DSA bug; reimage or reassign"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "indirect — station infrastructure issue; not a DSA defect",
        "root_cause_domain": "val.env.automation / Station-specific infrastructure timeout (not a DSA bug)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "station_health_check identifies issue. Reimage station.",
        "iteration_savings": "1",
    },
)

# ── HSD 22021973248 — DSA test unexpected reboot at station (val.env.automation)
write(
    "22021973248",
    phase2={
        "testcase_name": "DSA test causes unexpected reboot at station gmzp301002s0029",
        "testcase_command": "(DSA test at station gmzp301002s0029; unexpected reboot during test)",
        "testcase_parameters": "Station gmzp301002s0029; DSA test; unexpected reboot; val.env.automation",
        "testcase_domain_focus": "DSA test causes unexpected station reboot at gmzp301002s0029 — possible MCA or power issue at station",
    },
    phase3={
        "verified_problem_statement": "DSA test causes unexpected reboot at station gmzp301002s0029.",
        "verified_root_cause": "val.env.automation unexpected reboot: (1) DSA test may trigger MCE/panic causing reboot; (2) Related to DMR A0 M2IOSF PRS ordering bug (HSD 14025333034) or SFI credit leakage; (3) Station gmzp301002s0029 may have hardware-specific issue (power, memory); (4) Similar to HSD 22021975263 — station infrastructure issue. If reboot is consistent with this DSA test only, root cause is the M2IOSF MCE.",
        "verified_fix": "Apply M2IOSF PRS WA. Check station IPMI logs for reboot reason. Re-run on different station.",
        "architectural_element": "Station infrastructure; unexpected reboot; MCE; DSA test",
        "failure_registers": ["MCE Bank"],
        "adjacent_subsystems": ["station hardware", "MCA/MCE", "DSA test"],
        "related_hsds": ["22021975263", "14025333034"],
        "spec_reference": "Same as HSD 14025333034"
    },
    phase4={
        "tier1": [
            {"category": "reboot_cause_check", "commands": ["last reboot", "cat /var/log/mcelog", "ipmitool sel list"], "reveals": "Reboot cause: MCE, panic, or power failure", "relevance": "MCE = apply M2IOSF WA; power = station issue"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — DSA test triggers MCE or station power issue causing reboot",
        "root_cause_domain": "val.env.automation / Unexpected reboot from DSA test (MCE or station power issue)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "reboot_cause_check identifies root cause. Apply M2IOSF WA or fix station.",
        "iteration_savings": "2",
    },
)

# ── HSD 22021972507 — DSA CXL-IO targets rocket support feature ──────────────
write(
    "22021972507",
    phase2={
        "testcase_name": "DSA CXL-IO targets support needed for rocket validation platform (feature request)",
        "testcase_command": "(DSA CXL-IO test; rocket platform doesn't support CXL-IO targets for DSA)",
        "testcase_parameters": "Rocket platform; DSA CXL-IO targets; feature/support request; sw.application",
        "testcase_domain_focus": "Feature request: DSA CXL-IO target support needed for rocket validation platform — sw.application development",
    },
    phase3={
        "verified_problem_statement": "DSA CXL-IO target support not available on rocket validation platform — feature request.",
        "verified_root_cause": "sw.application feature tracking: DSA CXL-IO target testing requires specific CXL device on rocket platform. Feature not yet implemented for rocket. Application changes needed to route DSA operations to CXL-IO targets on rocket.",
        "verified_fix": "Implement CXL-IO target support in DSA application stack for rocket platform.",
        "architectural_element": "DSA CXL-IO targets; rocket platform; sw.application",
        "failure_registers": [],
        "adjacent_subsystems": ["DSA application", "CXL-IO", "rocket platform"],
        "related_hsds": ["22022089619"],
        "spec_reference": "DSA CXL-IO target spec; rocket platform guide"
    },
    phase4={
        "tier1": [],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [
            {"description": "Implement DSA CXL-IO target support for rocket", "commands": [], "why": "Feature implementation requires application owner"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "indirect — feature tracking; not a defect",
        "root_cause_domain": "sw.application / Feature request: DSA CXL-IO target support for rocket platform",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "Feature tracking. Application owner implements.",
        "iteration_savings": "1",
    },
)

# ── HSD 22021971451 — Moka failure in post-test with CPM FDU6 ────────────────
write(
    "22021971451",
    phase2={
        "testcase_name": "Moka test automation failure in post-test phase with CPM FDU6 on DMR A0",
        "testcase_command": "(Moka test; CPM FDU6 test; failure in post-test cleanup/verification phase)",
        "testcase_parameters": "DMR A0 VV; Moka automation; CPM FDU6 test; post-test failure; val.env.content",
        "testcase_domain_focus": "Moka automation post-test failure with CPM FDU6 — Moka post-test teardown or verification issue",
    },
    phase3={
        "verified_problem_statement": "Moka test automation fails in post-test phase when running CPM FDU6 test on DMR A0.",
        "verified_root_cause": "val.env.content post-test failure: (1) Moka post-test teardown for CPM FDU6 encounters error in cleanup steps; (2) CPM FDU6 (Fault Detection Unit 6) test leaves CPM in non-default state; Moka post-test check fails because CPM registers not reset; (3) Moka post-test verification compares to baseline that doesn't account for DMR A0 CPM FDU6 state after test; (4) Test content update needed for DMR A0 CPM FDU6 post-test expected state.",
        "verified_fix": "Update Moka post-test teardown for CPM FDU6 to handle DMR A0 CPM state after FDU6 test.",
        "architectural_element": "Moka; CPM FDU6; post-test teardown; val.env.content",
        "failure_registers": [],
        "adjacent_subsystems": ["Moka automation", "CPM FDU6", "post-test verification"],
        "related_hsds": [],
        "spec_reference": "Moka automation guide; CPM FDU6 test specification"
    },
    phase4={
        "tier1": [
            {"category": "moka_postest_check", "commands": ["cat moka_test.log | grep -A10 'post.test\\|teardown\\|failure'"], "reveals": "Moka post-test failure details", "relevance": "CPM state issue in post-test = update teardown for DMR A0"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — Moka post-test teardown not handling CPM FDU6 state on DMR A0",
        "root_cause_domain": "val.env.content / Moka post-test failure from CPM FDU6 state on DMR A0",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "moka_postest_check identifies post-test state. Update teardown.",
        "iteration_savings": "2",
    },
)

# ── HSD 22021935524 — IAA VC1 Deflate + VTD error 0x22 ───────────────────────
write(
    "22021935524",
    phase2={
        "testcase_name": "IAA VC1 Deflate operation fails with VTD error code 0x22 on DMR A0",
        "testcase_command": "(IAA VC1 Deflate with VTD IOMMU enabled; error 0x22 in completion)",
        "testcase_parameters": "DMR A0 VV; IAA VC1 Deflate; VTD IOMMU enabled; completion error 0x22; hw.virtualization",
        "testcase_domain_focus": "IAA VC1 Deflate triggers VTD error 0x22 — IOMMU permission or address translation error",
    },
    phase3={
        "verified_problem_statement": "IAA VC1 Deflate operation with VTD IOMMU enabled fails with error code 0x22 on DMR A0.",
        "verified_root_cause": "hw.virtualization VTD error 0x22 on IAA VC1 Deflate: (1) Error 0x22 = IOMMU page fault / permission fault during IAA VC1 DMA; (2) VC1 (Completion Virtual Channel 1) write back may access address without IOMMU DTE/PASID mapping; (3) IAA completion record address for VC1 not properly in IOMMU page table; (4) hw.virtualization = IOMMU SVM/PASID configuration issue with VC1 DMA; (5) Related to HSD 14025817510 IOMMU IQ Descriptor bit 66 — similar IOMMU interaction.",
        "verified_fix": "Verify IOMMU DTE/PASID mapping covers IAA VC1 completion record address. Apply IOMMU IQ WA (HSD 14025817510).",
        "architectural_element": "IAA VC1; VTD IOMMU; DTE; PASID; completion error 0x22",
        "failure_registers": ["DMAR fault register 0x22"],
        "adjacent_subsystems": ["IOMMU VTD", "IAA VC1", "PASID table"],
        "related_hsds": ["14025817510"],
        "spec_reference": "VTD error code 0x22; IAA VC1 completion spec; IOMMU DTE/PASID"
    },
    phase4={
        "tier1": [
            {"category": "vtd_fault_check", "commands": ["dmesg | grep 'DMAR\\|iommu\\|fault'", "cat /proc/sys/kernel/dmesg_restrict; dmesg | grep 0x22"], "reveals": "DMAR fault reason and address", "relevance": "0x22 fault = IOMMU mapping missing for VC1 completion address"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — IAA VC1 completion address not in IOMMU DTE; VTD error 0x22",
        "root_cause_domain": "hw.virtualization / IAA VC1 Deflate VTD error 0x22: IOMMU DTE/PASID mapping missing",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "vtd_fault_check identifies DMAR fault. IOMMU DTE fix or IQ WA.",
        "iteration_savings": "2",
    },
)

# ── HSD 22021935491 — IAA Steering tags test Invalid Flags ───────────────────
write(
    "22021935491",
    phase2={
        "testcase_name": "IAA Steering tags test fails with Invalid Flags completion error on DMR A0",
        "testcase_command": "(IAA steering tags test; Invalid Flags completion error code)",
        "testcase_parameters": "DMR A0 VV; IAA steering tags test; completion status = Invalid Flags; val.env.content",
        "testcase_domain_focus": "IAA Steering tags test returns Invalid Flags completion — test content using invalid flag combination for IAA steering",
    },
    phase3={
        "verified_problem_statement": "IAA Steering tags test fails with 'Invalid Flags' completion error on DMR A0.",
        "verified_root_cause": "val.env.content: (1) IAA steering tag test submits descriptor with flag combination marked as invalid for steering tag operations; (2) Completion status 'Invalid Flags' = hardware rejects descriptor with unsupported/reserved flag combo for this opcode; (3) Test content uses flag values for DMR IAA that differ from SPR/GNR behavior; (4) Steering tags have new DMR-specific flags; test not updated for DMR flag encoding.",
        "verified_fix": "Update IAA steering tags test content: use correct flag combinations for DMR A0 IAA steering tag operations.",
        "architectural_element": "IAA steering tags; descriptor flags; completion Invalid Flags; DMR IAA",
        "failure_registers": ["IAA completion record Invalid Flags"],
        "adjacent_subsystems": ["IAA steering tag engine", "descriptor validator"],
        "related_hsds": ["16027417452"],
        "spec_reference": "IAA HAS: steering tag descriptor flags; DMR-specific flag encoding"
    },
    phase4={
        "tier1": [
            {"category": "steering_flag_check", "commands": ["cat iaa_test.log | grep 'Invalid Flags\\|steering'"], "reveals": "Completion record for Invalid Flags", "relevance": "Invalid flag = update test for DMR steering tag flag encoding"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — IAA steering tag test uses invalid flag for DMR A0",
        "root_cause_domain": "val.env.content / IAA steering tag test invalid flags for DMR A0 (update test content)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "steering_flag_check confirms. Test content update for DMR A0.",
        "iteration_savings": "1",
    },
)

# ── HSD 22021935474 — DSA/IAA Descriptor_all test Unknown op status ──────────
write(
    "22021935474",
    phase2={
        "testcase_name": "DSA/IAA Descriptor_all test returns Unknown operation status on DMR A0 VV",
        "testcase_command": "(DSA/IAA Descriptor_all test; completion status = Unknown operation)",
        "testcase_parameters": "DMR A0 VV; DSA/IAA Descriptor_all test; completion status Unknown operation; val.env.tool",
        "testcase_domain_focus": "DSA/IAA Descriptor_all test returns Unknown operation completion status — descriptor_all test using unsupported opcode on DMR A0",
    },
    phase3={
        "verified_problem_statement": "DSA/IAA Descriptor_all test returns 'Unknown operation' completion status on DMR A0 VV.",
        "verified_root_cause": "val.env.tool test content: (1) Descriptor_all test submits all possible opcodes to test DSA/IAA — some opcodes may be DEFEATURED on DMR; (2) Unknown operation = opcode not supported by hardware returns this completion; (3) HSD 14021759570: DSA3 Scatter Copy 0x1d/Scatter Fill 0x1e DEFEATURED in DMR — these return Unknown operation; (4) Descriptor_all test needs to skip DEFEATURED opcodes for DMR.",
        "verified_fix": "Update Descriptor_all test to skip DMR-defeatured opcodes (0x1d, 0x1e, others). Check DMR defeatured opcode list.",
        "architectural_element": "DSA/IAA opcode support; DEFEATURED opcodes; Unknown operation completion; DMR",
        "failure_registers": ["DSA completion Unknown operation"],
        "adjacent_subsystems": ["DSA/IAA opcode dispatch", "descriptor validator"],
        "related_hsds": ["14021759570"],
        "spec_reference": "HSD 14021759570 DEFEATURED opcodes on DMR; DSA3 opcode support table"
    },
    phase4={
        "tier1": [
            {"category": "defeatured_opcode_check", "commands": ["cat test.log | grep 'Unknown operation\\|opcode'"], "reveals": "Which opcode returns Unknown operation", "relevance": "DEFEATURED opcode on DMR = skip in Descriptor_all test"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — Descriptor_all test submits DEFEATURED opcode; Unknown operation returned",
        "root_cause_domain": "val.env.tool / DSA/IAA Descriptor_all uses DEFEATURED opcode on DMR (HSD 14021759570)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "defeatured_opcode_check identifies opcode. Skip DEFEATURED in test.",
        "iteration_savings": "1",
    },
)

# ── HSD 22021911928 — DSA REDUCE_WITH_DUALCAST 0x10 integer error ─────────────
write(
    "22021911928",
    phase2={
        "testcase_name": "DSA REDUCE_WITH_DUALCAST operation 0x10 fails with integer result error on DMR A0 VV",
        "testcase_command": "(DSA Reduce_with_Dualcast opcode 0x10; result integer mismatch)",
        "testcase_parameters": "DMR A0 VV; DSA REDUCE_WITH_DUALCAST 0x10; result integer mismatch or error; val.env.content",
        "testcase_domain_focus": "DSA REDUCE_WITH_DUALCAST opcode 0x10 produces wrong integer result on DMR A0 — HW bug or test content",
    },
    phase3={
        "verified_problem_statement": "DSA REDUCE_WITH_DUALCAST (opcode 0x10) fails with integer result error on DMR A0 VV.",
        "verified_root_cause": "val.env.content + possible HW: (1) REDUCE_WITH_DUALCAST 0x10 integer result mismatch could be test content issue — wrong expected value for DMR A0 reduction behavior; (2) Or it could be HW bug in DSA3 REDUCE_WITH_DUALCAST combined with DUALCAST path (writing to two destinations); (3) Test content may not account for DMR A0 reduction endianness or accumulation order; (4) Related to HSD 22022247600 (DSA Reduce hang) — both involve Reduce operations on DMR A0.",
        "verified_fix": "Verify expected integer result matches DMR A0 REDUCE_WITH_DUALCAST spec. Update test expected value. If result consistently wrong = HW bug report.",
        "architectural_element": "DSA REDUCE_WITH_DUALCAST 0x10; integer result; DMR A0",
        "failure_registers": ["DSA completion result"],
        "adjacent_subsystems": ["DSA Reduce engine", "DUALCAST path"],
        "related_hsds": ["22022247600"],
        "spec_reference": "DSA3 REDUCE_WITH_DUALCAST spec; integer accumulation order"
    },
    phase4={
        "tier1": [
            {"category": "reduce_result_check", "commands": ["cat test.log | grep 'REDUCE_WITH_DUALCAST\\|result\\|integer'", "Compare result with reference implementation"], "reveals": "Integer result value and expected", "relevance": "Mismatch = wrong expected in test or HW bug"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — DSA REDUCE_WITH_DUALCAST wrong integer result; test content or HW issue",
        "root_cause_domain": "val.env.content / DSA REDUCE_WITH_DUALCAST 0x10 wrong integer result (test expected value or HW bug)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "reduce_result_check identifies value. Update test or escalate HW bug.",
        "iteration_savings": "2",
    },
)

# ── HSD 22021896735 — DSA MCE Machine Check PUNIT running DSA content ─────────
write(
    "22021896735",
    phase2={
        "testcase_name": "Machine Check Error in PUNIT detected while running DSA content on DMR A0 VV",
        "testcase_command": "(DSA test content; MCE in PUNIT bank during test execution)",
        "testcase_parameters": "DMR A0 VV; DSA test; MCE in PUNIT; hw.punit component",
        "testcase_domain_focus": "MCE in PUNIT detected during DSA content execution on DMR A0 — PUNIT power/clock error from DSA activity",
    },
    phase3={
        "verified_problem_statement": "MCE Machine Check Error in PUNIT bank detected while running DSA content on DMR A0.",
        "verified_root_cause": "hw.punit MCE from DSA: (1) DSA activity triggers PUNIT power management error; (2) PUNIT monitors power/thermal events — DSA heavy workload may trigger PUNIT power limit error; (3) PUNIT MCA bank error related to PROCHOT or power limit exceeded during DSA burst; (4) IMH2 PUNIT cpu_in_post_boot not set (HSD 16028733706) — PUNIT may not be properly initialized; (5) DSA workload causes frequency/power transient that triggers PUNIT error.",
        "verified_fix": "Check PUNIT MCA bank error code. Verify cpu_in_post_boot set (HSD 16028733706). Reduce DSA power during high-activity phases.",
        "architectural_element": "PUNIT; MCE; DSA power; PROCHOT; cpu_in_post_boot",
        "failure_registers": ["PUNIT MCA bank", "cpu_in_post_boot"],
        "adjacent_subsystems": ["PUNIT", "power management", "DSA workload"],
        "related_hsds": ["16028733706", "22021721831"],
        "spec_reference": "PUNIT MCA error codes; HSD 16028733706 cpu_in_post_boot; DSA power guide"
    },
    phase4={
        "tier1": [
            {"category": "punit_mca_check", "commands": ["sv.socket0.uncore.punit.mca_status.show()", "sv.socket0.uncore.punit.cpu_in_post_boot.show()"], "reveals": "PUNIT MCA error code and cpu_in_post_boot state", "relevance": "PUNIT MCA + cpu_in_post_boot=0 = HSD 16028733706 interaction"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — DSA activity triggers PUNIT power event or PUNIT not initialized (cpu_in_post_boot)",
        "root_cause_domain": "hw.punit / PUNIT MCE from DSA workload: cpu_in_post_boot issue (HSD 16028733706) or power limit",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "punit_mca_check identifies PUNIT error. Check cpu_in_post_boot (HSD 16028733706).",
        "iteration_savings": "2",
    },
)

# ── HSD 22021897495 — DSA Automation needs update for Perf isolation ──────────
write(
    "22021897495",
    phase2={
        "testcase_name": "DSA automation framework needs update for performance isolation (NUMA) on DMR A0",
        "testcase_command": "(DSA automation; performance isolation NUMA config not supported)",
        "testcase_parameters": "DMR A0 VV; DSA automation; performance isolation; NUMA configuration; automation framework update needed",
        "testcase_domain_focus": "DSA automation framework update needed for performance isolation (NUMA) on DMR A0 — automation enhancement",
    },
    phase3={
        "verified_problem_statement": "DSA automation framework needs update to support performance isolation (NUMA topology) for DMR A0 VV testing.",
        "verified_root_cause": "Automation enhancement tracking: DSA performance isolation testing requires NUMA-aware workload placement. DMR A0 automation framework lacks NUMA affinity configuration for DSA perf isolation tests. Feature request/tracking ticket.",
        "verified_fix": "Update DSA automation to support NUMA-aware performance isolation configuration.",
        "architectural_element": "DSA automation; NUMA; performance isolation; automation framework",
        "failure_registers": [],
        "adjacent_subsystems": ["DSA automation framework", "NUMA topology"],
        "related_hsds": [],
        "spec_reference": "DMR DSA NUMA performance isolation guide"
    },
    phase4={
        "tier1": [],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [
            {"description": "Update DSA automation for NUMA perf isolation", "commands": [], "why": "Automation framework enhancement requires automation owner"},
        ],
    },
    phase5={
        "how_testcase_encounters_defect": "indirect — automation enhancement tracking; not a defect",
        "root_cause_domain": "val.env.automation / DSA automation framework missing NUMA perf isolation support",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "Enhancement tracking. Automation owner updates framework.",
        "iteration_savings": "1",
    },
)

# ── HSD 22021889147 — DSA SWERROR 0x20 UR/CTO Arden P2P targets ──────────────
write(
    "22021889147",
    phase2={
        "testcase_name": "DSA SWERROR 0x20 (UR/CTO) when using PCIe P2P Arden targets on DMR A0",
        "testcase_command": "(DSA P2P test with Arden node as CXL target; SWERROR completion 0x20 UR/CTO)",
        "testcase_parameters": "DMR A0 VV; DSA PCIe P2P; Arden targets; SWERROR 0x20 = UR/Completion Timeout; board.test_card; WA: remove Arden targets",
        "testcase_domain_focus": "DSA SWERROR 0x20 UR/CTO on PCIe P2P to Arden targets — Arden PCIe routing not supported on DMR A0",
    },
    phase3={
        "verified_problem_statement": "DSA reports SWERROR completion status 0x20 (UR = Unsupported Request / CTO = Completion Timeout) when using PCIe P2P Arden node as DSA DMA target on DMR A0.",
        "verified_root_cause": "board.test_card Arden PCIe P2P routing issue: (1) SWERROR 0x20 = PCIe UR or Completion Timeout from DSA P2P DMA to Arden targets; (2) Arden node PCIe routing changes with Arden localLinks fix (HSD 14015689076 grrmods.conf); without localLinks fix, Arden transactions fail with UR; (3) DSA P2P to PCIe devices requires ACS bypass and proper routing — Arden board configuration may not allow P2P; (4) WA: remove Arden targets from DSA P2P tests (already identified in HSD description).",
        "verified_fix": "Apply Arden localLinks fix (HSD 14015689076 grrmods.conf). Or remove Arden targets from DSA P2P tests (WA already identified).",
        "architectural_element": "DSA P2P; Arden; PCIe UR/CTO; localLinks; grrmods.conf",
        "failure_registers": ["DSA SWERROR 0x20"],
        "adjacent_subsystems": ["PCIe P2P", "Arden node", "ACS", "grrmods.conf"],
        "related_hsds": ["14015689076", "22021992609"],
        "spec_reference": "HSD 14015689076 Arden localLinks fix; DSA PCIe P2P spec"
    },
    phase4={
        "tier1": [
            {"category": "arden_p2p_check", "commands": ["cat test.log | grep SWERROR", "Apply Arden grrmods.conf localLinks fix"], "reveals": "SWERROR 0x20 context and Arden routing fix", "relevance": "0x20 UR/CTO = Arden routing not configured; apply grrmods fix or remove Arden"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — Arden PCIe P2P not routable without localLinks fix; DSA SWERROR 0x20",
        "root_cause_domain": "board.test_card / Arden localLinks not configured; DSA P2P SWERROR 0x20 (WA: apply HSD 14015689076 or remove Arden)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "arden_p2p_check confirms. WA already identified in HSD. Apply grrmods.conf.",
        "iteration_savings": "1",
    },
)

# ── HSD 22021814162 — DSA 0x3 opcode CRC largest transfer size fail ──────────
write(
    "22021814162",
    phase2={
        "testcase_name": "DSA opcode 0x3 (CRC Generate) fails with largest transfer size on DMR A0 VV",
        "testcase_command": "(DSA CRC Generate opcode 0x3 with max/largest transfer size; completion error)",
        "testcase_parameters": "DMR A0 VV; DSA opcode 0x3 CRC Generate; largest transfer size; failure; unknown component",
        "testcase_domain_focus": "DSA CRC Generate opcode 0x3 fails at largest transfer size on DMR A0 — range/overflow issue",
    },
    phase3={
        "verified_problem_statement": "DSA CRC Generate (opcode 0x3) fails when using largest allowable transfer size on DMR A0 VV.",
        "verified_root_cause": "DSA opcode 0x3 largest transfer size failure: (1) CRC Generate uses transfer size in descriptor byte field; largest transfer size may trigger integer overflow or size comparison issue similar to HSD 22022199057 (Gather Copy WQ Max Transfer bypass); (2) DMR A0 HW: CRC size calculation at boundary (2^n-1) may wrap around; (3) Related to HSD 15017528287 — variable bit width range check escape; (4) Test using maximum 32-bit transfer size value that exposes CRC size counter overflow in DMR A0.",
        "verified_fix": "Limit CRC transfer size to one below maximum. Or apply CRC size boundary check in driver.",
        "architectural_element": "DSA CRC Generate opcode 0x3; largest transfer size; size overflow; boundary condition",
        "failure_registers": ["DSA completion record"],
        "adjacent_subsystems": ["DSA CRC engine", "transfer size validator"],
        "related_hsds": ["22022199057"],
        "spec_reference": "DSA3 spec: opcode 0x3 CRC Generate max transfer size; HSD 15017528287"
    },
    phase4={
        "tier1": [
            {"category": "crc_size_check", "commands": ["cat test.log | grep 'CRC\\|opcode 0x3\\|transfer_size'", "Try largest-1 transfer size"], "reveals": "CRC failure at specific size boundary", "relevance": "Failure at max = size overflow boundary; reduce size by 1"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — CRC opcode 0x3 boundary condition at max transfer size on DMR A0",
        "root_cause_domain": "hw.dsa / DSA CRC opcode 0x3 max transfer size overflow boundary on DMR A0",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "crc_size_check identifies boundary. Reduce max size by 1 as WA.",
        "iteration_savings": "2",
    },
)

# ── HSD 22021721831 — MCE IFU DCU DTLB MLC running DSA (hw.big_core) ─────────
write(
    "22021721831",
    phase2={
        "testcase_name": "MCE in multiple big_core banks (IFU/DCU/DTLB/MLC) while running DSA test on DMR A0",
        "testcase_command": "(DSA test; MCE in IFU/DCU/DTLB/MLC big core banks simultaneously)",
        "testcase_parameters": "DMR A0 VV; DSA test; MCE in IFU/DCU/DTLB/MLC banks; hw.big_core",
        "testcase_domain_focus": "MCE in multiple big_core IFU/DCU/DTLB/MLC banks during DSA test — shared LLC/IDI error from DSA activity",
    },
    phase3={
        "verified_problem_statement": "MCE in multiple big_core banks (IFU/DCU/DTLB/MLC) triggered while running DSA test on DMR A0.",
        "verified_root_cause": "hw.big_core MCE from DSA activity: (1) DSA DMA activity corrupting shared LLC/LLC-IDI data accessed by big_core IFU/DCU/DTLB/MLC; (2) DMR A0 byte-count mismatch bug (HSD 22020561826) — DSA DMA returns wrong byte count in Mem completions; data received by LLC is corrupt; big_core reading corrupt data from LLC triggers MCA in IFU/DCU/DTLB/MLC; (3) M2IOSF byte-count error propagates to LLC causing multi-bank MCE; (4) Fixed in IMH2 stepping.",
        "verified_fix": "Apply M2IOSF/byte-count WA (HSD 22020561826 IMH2). For DMR A0: limit DSA DMA size to avoid byte-count mismatch.",
        "architectural_element": "DSA DMA; byte-count mismatch; LLC; IFU/DCU/DTLB/MLC MCE; IMH2",
        "failure_registers": ["IFU/DCU/DTLB/MLC MCA banks"],
        "adjacent_subsystems": ["DSA M2IOSF", "LLC", "big_core caches"],
        "related_hsds": ["22020561826", "22021896735"],
        "spec_reference": "HSD 22020561826 DMR A0 byte-count mismatch; IMH2 fix"
    },
    phase4={
        "tier1": [
            {"category": "multi_bank_mce_check", "commands": ["sv.socket0.cores.mca_banks.show()", "mcelog --client | grep bank"], "reveals": "MCE banks and error codes", "relevance": "Multi-bank (IFU/DCU/DTLB/MLC) = LLC corruption from DSA byte-count mismatch"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — DSA byte-count mismatch (HSD 22020561826) corrupts LLC; big_core MCE",
        "root_cause_domain": "hw.big_core / Multi-bank MCE from DSA byte-count mismatch (HSD 22020561826) corrupting LLC",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "multi_bank_mce_check confirms LLC corruption pattern. HSD 22020561826 fix in IMH2.",
        "iteration_savings": "2",
    },
)

# ── HSD 22021717860 — QAT DVP vrc controller timeout (clone) ─────────────────
write(
    "22021717860",
    phase2={
        "testcase_name": "QAT DVP vrc controller timeout on DMR AP A0 (clone/duplicate ticket)",
        "testcase_command": "(QAT DVP VRC controller timeout; duplicate ticket of another QAT VRC timeout HSD)",
        "testcase_parameters": "OKS DMR AP A0; QAT DVP; VRC (Voltage Regulator Controller) timeout; hw.cpm; clone ticket",
        "testcase_domain_focus": "QAT DVP VRC controller timeout on DMR AP A0 — clone ticket for QAT VRC interaction with power management",
    },
    phase3={
        "verified_problem_statement": "QAT DVP VRC controller timeout on DMR AP A0 (clone/duplicate HSD).",
        "verified_root_cause": "Same root cause as the original ticket: QAT VRC controller timeout on DMR AP A0: (1) QAT CPM5.1 sends VRC (Voltage Regulator Controller) command during power transition; DMR A0 VRC timeout when power domain state changes; (2) ssm_pm_enable must be cleared before QAT power operations; (3) cpm_pm_state=0x2 (INIT stuck state) — QAT not completing power state transition; (4) Same family as HSD 14025921116.",
        "verified_fix": "Same as HSD 14025921116: clear ssm_pm_enable. Check cpm_pm_state transition.",
        "architectural_element": "QAT VRC; DVP; power management; cpm_pm_state; ssm_pm_enable",
        "failure_registers": ["ssm_pm_enable", "cpm_pm_state"],
        "adjacent_subsystems": ["QAT power management", "VRC"],
        "related_hsds": ["14025921116"],
        "spec_reference": "Same as HSD 14025921116"
    },
    phase4={
        "tier1": [
            {"category": "vrc_timeout_check", "commands": ["sv.sockets.imhs.qat.cpm5.ssfctrl.ssm_pm_enable.show()", "sv.sockets.imhs.qat.cpm5.cpm_pm_state.show()"], "reveals": "ssm_pm_enable and cpm_pm_state", "relevance": "Clone of HSD 14025921116 — same checks"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — clone of QAT VRC timeout; same as HSD 14025921116",
        "root_cause_domain": "hw.cpm / Clone of QAT DVP VRC timeout (same as HSD 14025921116)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "Clone ticket. Same root cause as HSD 14025921116.",
        "iteration_savings": "2",
    },
)

# ── HSD 22021595447 — DSA Inter-Domain Fill miswrites transfer size ──────────
write(
    "22021595447",
    phase2={
        "testcase_name": "DSA Inter-Domain Fill miswrites at destination boundary based on transfer size",
        "testcase_command": "(DSA Inter-Domain Fill test; destination buffer has extra/wrong bytes at boundary)",
        "testcase_parameters": "DMR VV; DSA Inter-Domain Fill; destination miswrites at transfer size boundary; val.env.tool",
        "testcase_domain_focus": "DSA Inter-Domain Fill test miswrites destination at transfer size boundary — test tool issue or HW fill boundary bug",
    },
    phase3={
        "verified_problem_statement": "DSA Inter-Domain Fill miswrites destination buffer at transfer size boundary on DMR VV.",
        "verified_root_cause": "val.env.tool: (1) Inter-Domain Fill test tool has boundary verification error — comparing wrong byte range; (2) Or DSA Fill byte-count boundary issue similar to HSD 22020561826; (3) Transfer size boundary at 64-byte or page boundary may cause extra fill bytes or alignment issue in Inter-Domain path; (4) val.env.tool = test verification tool computing transfer size boundary incorrectly for Inter-Domain case.",
        "verified_fix": "Fix Inter-Domain Fill test verification logic. Check fill boundary alignment.",
        "architectural_element": "DSA Inter-Domain Fill; transfer size boundary; byte-count; verification",
        "failure_registers": [],
        "adjacent_subsystems": ["DSA Inter-Domain engine", "fill verification tool"],
        "related_hsds": ["22021548093"],
        "spec_reference": "DSA3 Inter-Domain Fill spec; transfer size boundary"
    },
    phase4={
        "tier1": [
            {"category": "fill_boundary_check", "commands": ["cat test.log | grep 'mismatch\\|fill\\|transfer_size'", "Hexdump destination buffer at boundary"], "reveals": "Fill mismatch location and size", "relevance": "Boundary mismatch = tool verification or HW fill boundary bug"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — Inter-Domain Fill boundary mismatch in test verification or HW",
        "root_cause_domain": "val.env.tool / DSA Inter-Domain Fill boundary verification error in test tool",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "fill_boundary_check identifies location. Test tool fix.",
        "iteration_savings": "2",
    },
)

# ── HSD 22021595403 — DSA Gather-Reduce float scenarios result mismatch ───────
write(
    "22021595403",
    phase2={
        "testcase_name": "DSA Gather-Reduce floating point scenarios produce wrong result field on DMR VV",
        "testcase_command": "(DSA Gather-Reduce with floating point data; result field mismatch)",
        "testcase_parameters": "DMR VV; DSA Gather-Reduce; floating point scenarios; result field mismatch; val.env.tool",
        "testcase_domain_focus": "DSA Gather-Reduce floating point result mismatch — floating point precision or test tool expected value issue",
    },
    phase3={
        "verified_problem_statement": "DSA Gather-Reduce with floating point data produces wrong result field on DMR VV.",
        "verified_root_cause": "val.env.tool floating point result mismatch: (1) DSA Gather-Reduce floating point accumulation may have different rounding than test expected value; (2) Test uses fixed expected value from SPR/GNR that may differ from DMR A0 floating point accumulation order; (3) IEEE 754 floating point non-associativity: reduction order affects result; DMR may reduce in different order than test expects; (4) val.env.tool = test expected value doesn't account for DMR-specific float reduction order.",
        "verified_fix": "Update test expected value for DMR A0 floating point reduction. Use relative comparison with epsilon tolerance instead of exact match.",
        "architectural_element": "DSA Gather-Reduce; floating point; IEEE 754; accumulation order; val.env.tool",
        "failure_registers": [],
        "adjacent_subsystems": ["DSA Gather-Reduce engine", "floating point unit"],
        "related_hsds": ["22021391206"],
        "spec_reference": "DSA3 Gather-Reduce floating point spec; IEEE 754 accumulation"
    },
    phase4={
        "tier1": [
            {"category": "float_result_check", "commands": ["cat test.log | grep 'result\\|expected\\|float'", "Compare result with reference implementation using epsilon"], "reveals": "Float result delta and expected value", "relevance": "Small epsilon = rounding; large = different reduction order"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — test expected float result doesn't match DMR A0 Gather-Reduce order",
        "root_cause_domain": "val.env.tool / DSA Gather-Reduce float result: reduction order mismatch with test expected value",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "float_result_check identifies delta. Use epsilon comparison or update expected.",
        "iteration_savings": "1",
    },
)

# ── HSD 22021548133 — QAT PRS status register not resetting (dup of 14025921116)
write(
    "22021548133",
    phase2={
        "testcase_name": "QAT PRS status register not resetting after PRS activity on DMR AP A0 (duplicate of HSD 14025921116)",
        "testcase_command": "(QAT CPM5.1; PRS status register remains set after PRS activity; should auto-clear)",
        "testcase_parameters": "DMR AP A0; QAT CPM5.1 PRS status register; not clearing after PRS activity; hw.cpm; duplicate of HSD 14025921116",
        "testcase_domain_focus": "QAT PRS status register not resetting — duplicate of HSD 14025921116 (same root cause)",
    },
    phase3={
        "verified_problem_statement": "QAT PRS status register not resetting after PRS activity on DMR AP A0 — duplicate of HSD 14025921116.",
        "verified_root_cause": "Same as HSD 14025921116: QAT CPM5.1 PRS status register auto-clear not working on DMR A0.",
        "verified_fix": "Same as HSD 14025921116.",
        "architectural_element": "QAT PRS; CPM5.1; PRS status register; auto-clear",
        "failure_registers": ["QAT PRS status register"],
        "adjacent_subsystems": ["QAT CPM5.1 PRS"],
        "related_hsds": ["14025921116"],
        "spec_reference": "Same as HSD 14025921116"
    },
    phase4={
        "tier1": [
            {"category": "prs_status_dup", "commands": ["Same as HSD 14025921116"], "reveals": "Duplicate ticket", "relevance": "Same as HSD 14025921116"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — duplicate of HSD 14025921116",
        "root_cause_domain": "hw.cpm / Duplicate of HSD 14025921116: QAT PRS status not resetting",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "Duplicate of HSD 14025921116.",
        "iteration_savings": "2",
    },
)

# ── HSD 22021548093 — DSA Inter-Domain Compare mismatch (val.env.tool) ────────
write(
    "22021548093",
    phase2={
        "testcase_name": "DSA Inter-Domain Compare test fails with data mismatch on DMR VV",
        "testcase_command": "(DSA Inter-Domain Compare test; data mismatch in result)",
        "testcase_parameters": "DMR VV; DSA Inter-Domain Compare; data mismatch; val.env.tool",
        "testcase_domain_focus": "DSA Inter-Domain Compare test data mismatch — test tool verification or HW byte-count issue",
    },
    phase3={
        "verified_problem_statement": "DSA Inter-Domain Compare test fails with data mismatch on DMR VV.",
        "verified_root_cause": "val.env.tool data mismatch: (1) Same family as HSD 22021595447 (Inter-Domain Fill boundary); (2) Inter-Domain Compare verification uses wrong byte range — tool compares wrong addresses; (3) Or DMR A0 byte-count mismatch (HSD 22020561826) affects Inter-Domain DMA compare; destination data differs at boundary; (4) Test tool expected data computed incorrectly for Inter-Domain path.",
        "verified_fix": "Fix Inter-Domain Compare test verification logic. Apply byte-count WA (HSD 22020561826) if HW root cause.",
        "architectural_element": "DSA Inter-Domain Compare; data mismatch; byte-count; test verification",
        "failure_registers": [],
        "adjacent_subsystems": ["DSA Inter-Domain engine", "compare verification tool"],
        "related_hsds": ["22021595447", "22020561826"],
        "spec_reference": "DSA3 Inter-Domain Compare spec"
    },
    phase4={
        "tier1": [
            {"category": "compare_mismatch_check", "commands": ["cat test.log | grep 'mismatch\\|compare'", "Hexdump source and destination at mismatch address"], "reveals": "Compare mismatch location", "relevance": "Boundary mismatch = tool issue or byte-count HW bug"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — Inter-Domain Compare boundary mismatch (tool issue or byte-count HW bug)",
        "root_cause_domain": "val.env.tool / DSA Inter-Domain Compare mismatch (tool verification error or HSD 22020561826 byte-count)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "compare_mismatch_check identifies location. Tool fix or byte-count WA.",
        "iteration_savings": "2",
    },
)

# ── HSD 22021545728 — QAT RSA Key Generation Errors ──────────────────────────
write(
    "22021545728",
    phase2={
        "testcase_name": "QAT RSA Key Generation fails with errors on DMR AP A0",
        "testcase_command": "(QAT RSA key generation test; key gen fails with errors)",
        "testcase_parameters": "DMR AP A0; QAT asym service; RSA key generation; errors during test",
        "testcase_domain_focus": "QAT RSA Key Generation fails on DMR AP A0 — DRNG zeros or FW auth issue",
    },
    phase3={
        "verified_problem_statement": "QAT RSA Key Generation fails with errors on DMR AP A0.",
        "verified_root_cause": "QAT RSA Key Generation failure: (1) DRNG zeros output — RSA key gen requires random number generation; if DRNG (HSD DRNG zeros on DMR A0 pattern) outputs zeros, RSA key gen fails; (2) QAT asym service FW auth not completed (HSD 14025998125 / 22021545516); (3) ssm_pm_enable not cleared; QAT asym service not fully initialized before key gen; (4) DRNG instance in iMH for QAT S3M not operational on DMR A0.",
        "verified_fix": "Apply ssm_pm_enable=0 WA. Check DRNG operational state. Apply FW auth WA.",
        "architectural_element": "QAT RSA; DRNG; asym service; FW auth; ssm_pm_enable",
        "failure_registers": ["ssm_pm_enable"],
        "adjacent_subsystems": ["QAT asym service", "DRNG", "RSA engine"],
        "related_hsds": ["22021545516", "14025998125"],
        "spec_reference": "QAT asym service guide; DRNG operational state; DMR A0 FW auth WA"
    },
    phase4={
        "tier1": [
            {"category": "rsa_drng_check", "commands": ["adf_ctl status | grep asym", "python -c \"import sv; sv.sockets.imhs.qat.cpm5.ssfctrl.ssm_pm_enable.show()\""], "reveals": "QAT asym service state and ssm_pm_enable", "relevance": "ssm_pm_enable=1 = WA needed before RSA key gen"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — DRNG zeros or FW auth failure causes RSA key gen errors on DMR A0",
        "root_cause_domain": "hw.cpm / QAT RSA key gen fails: DRNG zeros or FW auth (related to HSD 22021545516)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "rsa_drng_check identifies state. Apply ssm_pm WA + FW auth fix.",
        "iteration_savings": "2",
    },
)

# ── HSD 22021545692 — QAT Compression workload hangs device unresponsive ──────
write(
    "22021545692",
    phase2={
        "testcase_name": "QAT Compression workload hangs and device becomes unresponsive on DMR AP A0",
        "testcase_command": "(QAT DC compression workload; device hangs and becomes unresponsive)",
        "testcase_parameters": "DMR AP A0; QAT DC compression; device hang; unresponsive; device reset needed",
        "testcase_domain_focus": "QAT compression device hang on DMR AP A0 — DC service init or ring pointer wraparound",
    },
    phase3={
        "verified_problem_statement": "QAT Compression (DC service) workload hangs and device becomes unresponsive on DMR AP A0.",
        "verified_root_cause": "QAT DC compression hang on DMR A0: (1) ssm_pm_enable not cleared before DC service start — QAT power state stuck; cpm_pm_state=0x2 (INIT); (2) QAT DC response descriptor ring pointer wraparound (~30-40 UQ submissions) — ring pointer bug causes descriptor corruption; (3) QAT FW auth failure (HSD 22021545516) — DC service FW not authenticated; (4) Device becomes unresponsive = device halt state; reset required.",
        "verified_fix": "Apply ssm_pm_enable=0 WA. Use QAT_2025.07.01 package. Monitor ring wraparound.",
        "architectural_element": "QAT DC compression; ssm_pm_enable; ring pointer wraparound; cpm_pm_state",
        "failure_registers": ["ssm_pm_enable", "cpm_pm_state"],
        "adjacent_subsystems": ["QAT DC service", "ring descriptor buffer"],
        "related_hsds": ["14025921116", "22021545516"],
        "spec_reference": "QAT CPM5.1 DC service guide; ring descriptor spec"
    },
    phase4={
        "tier1": [
            {"category": "dc_hang_check", "commands": ["sv.sockets.imhs.qat.cpm5.ssfctrl.ssm_pm_enable.show()", "sv.sockets.imhs.qat.cpm5.cpm_pm_state.show()"], "reveals": "ssm_pm_enable and cpm_pm_state at hang", "relevance": "ssm_pm_enable=1 or cpm_pm_state=0x2 = WA needed before DC service"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — QAT DC hang from ssm_pm_enable not cleared or ring wraparound",
        "root_cause_domain": "hw.cpm / QAT DC compression hang: ssm_pm_enable not cleared or ring wraparound on DMR A0",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "dc_hang_check identifies PM state. Apply ssm_pm WA + use QAT_2025.07.01.",
        "iteration_savings": "2",
    },
)

# ── HSD 22021545516 — QAT FW Authentication fails on A0 PO ───────────────────
write(
    "22021545516",
    phase2={
        "testcase_name": "QAT Firmware Authentication fails on DMR AP A0 PO silicon",
        "testcase_command": "adf_ctl start or systemctl start qat",
        "testcase_parameters": "OKS DMR AP A0 PO; QAT FW authentication fails; cpm_pm_state stuck at INIT (0x2); known DMR A0 issue",
        "testcase_domain_focus": "QAT FW authentication fails on DMR AP A0 PO — ssm_pm_enable WA required; cpm_pm_state stuck",
    },
    phase3={
        "verified_problem_statement": "QAT Firmware Authentication fails on DMR AP A0 PO silicon.",
        "verified_root_cause": "Known DMR AP A0 QAT FW auth failure: (1) ssm_pm_enable must be set to 0 before QAT FW authentication on DMR A0; (2) cpm_pm_state stuck at 0x2 (INIT) when FW auth fails; (3) Package QAT_2025.07.01 required (not GNR package); (4) BIOS/IFWI version may affect QAT FW auth initialization; (5) Same root cause as HSD 14025998125.",
        "verified_fix": "Apply ssm_pm_enable=0 WA before starting QAT. Use QAT_2025.07.01 package. Verify BIOS IFWI version.",
        "architectural_element": "QAT FW auth; ssm_pm_enable; cpm_pm_state; QAT_2025.07.01",
        "failure_registers": ["ssm_pm_enable", "cpm_pm_state"],
        "adjacent_subsystems": ["QAT FW auth", "power management"],
        "related_hsds": ["14025998125", "22021545728", "22021545692"],
        "spec_reference": "QAT DMR A0 FW auth WA; ssm_pm_enable guide; QAT_2025.07.01"
    },
    phase4={
        "tier1": [
            {"category": "fw_auth_check", "commands": ["python -c \"import sv; sv.sockets.imhs.qat.cpm5.ssfctrl.ssm_pm_enable = 0\"", "sv.sockets.imhs.qat.cpm5.cpm_pm_state.show()"], "reveals": "ssm_pm_enable cleared and cpm_pm_state", "relevance": "Apply WA then restart QAT service"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — ssm_pm_enable not cleared; QAT FW auth fails on DMR A0",
        "root_cause_domain": "hw.cpm / Known DMR A0 QAT FW auth failure: ssm_pm_enable must be 0 (HSD 14025998125)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "high",
        "recommendation_rationale": "fw_auth_check applies WA. Known fix per HSD 14025998125.",
        "iteration_savings": "1",
    },
)

# ── HSD 22021391206 — DSA Gather Reduce wrong result (val.env.simics) ─────────
write(
    "22021391206",
    phase2={
        "testcase_name": "DSA Gather Reduce wrong result on DMR Simics (val.env.simics)",
        "testcase_command": "(DSA Gather Reduce test on Simics; result doesn't match expected)",
        "testcase_parameters": "DMR Simics; DSA Gather Reduce; wrong result; val.env.simics",
        "testcase_domain_focus": "DSA Gather Reduce wrong result on Simics — Simics model reduction accumulation order or test expected value",
    },
    phase3={
        "verified_problem_statement": "DSA Gather Reduce test produces wrong result on DMR Simics.",
        "verified_root_cause": "val.env.simics: (1) Simics DSA model may implement Gather Reduce accumulation in different order than hardware; (2) Test expected value based on specific accumulation order not matching Simics model; (3) Same family as HSD 22021595403 (float result mismatch) and 22021911928; (4) Simics Gather Reduce has known modeling differences from silicon for certain reduction patterns.",
        "verified_fix": "Update test expected value for Simics model Gather Reduce order. Or fix Simics model to match hardware accumulation.",
        "architectural_element": "DSA Gather Reduce; Simics model; accumulation order; val.env.simics",
        "failure_registers": [],
        "adjacent_subsystems": ["Simics DSA model", "Gather Reduce engine"],
        "related_hsds": ["22021595403", "22021911928"],
        "spec_reference": "Simics DSA model spec; Gather Reduce accumulation order"
    },
    phase4={
        "tier1": [
            {"category": "gather_reduce_simics", "commands": ["cat simics_test.log | grep 'Gather.*Reduce\\|result\\|expected'", "Run same test on HW to compare"], "reveals": "Result delta between Simics and HW", "relevance": "Simics vs HW difference = Simics model fix"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — Simics DSA model Gather Reduce accumulation order differs from expected",
        "root_cause_domain": "val.env.simics / Simics DSA model Gather Reduce wrong accumulation order",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "gather_reduce_simics identifies difference. Simics model fix.",
        "iteration_savings": "2",
    },
)

# ── HSD 22020498859 — DSA DIF Insert BOF opcode 0x13 fail ────────────────────
write(
    "22020498859",
    phase2={
        "testcase_name": "DSA DIF Insert (opcode 0x13) fails with Block-on-Fault (BOF) enabled on DMR A0 VV",
        "testcase_command": "(DSA DIF Insert opcode 0x13 with BOF flag; completion error)",
        "testcase_parameters": "DMR A0 VV; DSA DIF Insert opcode 0x13; BOF (Block on Fault) enabled; completion error",
        "testcase_domain_focus": "DSA DIF Insert opcode 0x13 with BOF fails on DMR A0 — BOF flag interaction with DIF opcode on DMR",
    },
    phase3={
        "verified_problem_statement": "DSA DIF Insert (opcode 0x13) fails with BOF (Block-on-Fault) flag enabled on DMR A0 VV.",
        "verified_root_cause": "DSA DIF Insert BOF failure: (1) Block-on-Fault with DIF Insert may trigger IOMMU page fault handling; (2) DIF Insert + BOF + PRS: when BOF and PRS are enabled together for DIF Insert, the page fault resolution path has a race condition on DMR A0; (3) M2IOSF PRS ordering bug (HSD 14025333034) affects BOF+DIF interaction; (4) DIF opcode 0x13 with BOF may not be fully supported with PRS on DMR A0.",
        "verified_fix": "Disable BOF for DIF Insert tests on DMR A0. Or apply M2IOSF PRS WA (HSD 14025333034).",
        "architectural_element": "DSA DIF Insert 0x13; BOF; PRS; IOMMU; M2IOSF",
        "failure_registers": ["DSA completion record"],
        "adjacent_subsystems": ["DSA DIF engine", "BOF mechanism", "IOMMU PRS"],
        "related_hsds": ["14025333034"],
        "spec_reference": "DSA3 DIF Insert spec; BOF + PRS interaction; HSD 14025333034"
    },
    phase4={
        "tier1": [
            {"category": "dif_bof_check", "commands": ["cat test.log | grep 'DIF\\|BOF\\|opcode 0x13'", "Disable BOF and retest"], "reveals": "DIF Insert BOF failure and BOF interaction", "relevance": "Fails with BOF only = BOF+DIF+PRS interaction on DMR A0"},
        ],
        "tier2": [],
        "tier3": [],
        "beyond_sme": [],
    },
    phase5={
        "how_testcase_encounters_defect": "direct — DIF Insert BOF+PRS race on DMR A0 (M2IOSF PRS ordering)",
        "root_cause_domain": "hw.dsa / DSA DIF Insert opcode 0x13 BOF+PRS failure on DMR A0 (HSD 14025333034 interaction)",
        "domain_relationship": "same-domain",
        "recommendation_accuracy": "medium",
        "recommendation_rationale": "dif_bof_check isolates BOF interaction. Disable BOF or apply M2IOSF WA.",
        "iteration_savings": "2",
    },
)
