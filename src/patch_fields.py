#!/usr/bin/env python3
"""
patch_fields.py
══════════════════════════════════════════════════════════════════════════════
Targeted field patcher for an existing triage run.

Reads responses.jsonl, identifies HSDs where phase0_hsd data is missing or
incomplete, then waits for the agent to call the HSD MCP tool to enrich them.

This script does NOT call MCPs itself — it is a helper that:
1. Identifies which HSDs need phase0_hsd enrichment
2. Provides the list and prompts to the agent for MCP calls
3. Once the agent populates PHASE0_RESULTS below, writes them to responses.jsonl
4. Re-runs finalize + report

Usage (two-pass workflow):
  Pass 1 — Identify gaps:
    python patch_fields.py --run-dir output/run_20260502_120716 --identify

  Pass 2 — After agent fills PHASE0_RESULTS, apply patches:
    python patch_fields.py --run-dir output/run_20260502_120716 --apply

  Combined finalize + report after patching:
    python patch_fields.py --run-dir output/run_20260502_120716 --finalize
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
csv.field_size_limit(10 * 1024 * 1024)

# ─── AGENT: POPULATE THIS DICT ───────────────────────────────────────────────
# After running --identify, the agent should call Co-Design HSD MCP for each
# listed HSD ID and populate entries here, then run --apply.
#
# Format per entry:
#   "<hsd_id>": {
#     "hsd_component":   "hw.dsa",          # resolved component
#     "hsd_root_cause":  "clean text ...",  # plain-English root cause
#     "hsd_fix":         "fix applied ...", # fix description
#     "hsd_actual_logs": "dmesg, MCE ...",  # debug data actually collected
#     "hsd_status":      "complete",
#     "hsd_conclusion":  "hw.bug"
#   }
PHASE0_RESULTS: dict[str, dict] = {
    "13013986760": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "Transfer-size handling incorrect in test: used xfer_size directly instead of xfer_size/sizeof(itype), causing opcode 0x1A failures with largest transfer size.",
        "hsd_fix":         "Fix calculation to use xfer_size/sizeof(itype) (PR idxd-config#12; commit b5e98e1041e5f90798485b92f3dca62be3758cf9).",
        "hsd_actual_logs": "NGA testResult link; WQs failing to log completion records.",
        "hsd_conclusion":  "",
    },
    "14021823464": {
        "hsd_component":   "platform.operating_system.linux.centos",
        "hsd_root_cause":  "Feature request: IAA_CRYPTO support not yet merged into DMR 6.7 kernel at the time.",
        "hsd_fix":         "IAA_Crypto included in later CentOS kernel (CentOS Kernel 6.8.1.1-1).",
        "hsd_actual_logs": "Kernel version and missing feature statement.",
        "hsd_conclusion":  "",
    },
    "14021823505": {
        "hsd_component":   "platform.simics.platform",
        "hsd_root_cause":  "Simics/tool issue affecting DSA memcpy/memmove verification (opcode test mismatch) observed on kernel 6.7; not reproducible on newer Simics build.",
        "hsd_fix":         "Not reproducible on DMR-6.0 2024ww10.3.",
        "hsd_actual_logs": "dsa_test verbose output: memcpy mismatch (memcmp rc 34), memory result verify failed -6.",
        "hsd_conclusion":  "",
    },
    "14021836063": {
        "hsd_component":   "val.env.tool",
        "hsd_root_cause":  "SVOS shipping older SAD9 driver than CentOS; driver version mismatch.",
        "hsd_fix":         "Not specified.",
        "hsd_actual_logs": "apt-cache policy output showing installed SAD driver version 9.388 on SVOS.",
        "hsd_conclusion":  "sw.bug",
    },
    "14021876991": {
        "hsd_component":   "sw.driver",
        "hsd_root_cause":  "PCIe UE detected - external TL error during Rocket PCIe tests; root cause not specified in ticket fields.",
        "hsd_fix":         "Not specified.",
        "hsd_actual_logs": "RTM.log: ardenrand unregister/verify failures; attached logs referenced.",
        "hsd_conclusion":  "sw.bug",
    },
    "14021959459": {
        "hsd_component":   "val.vp.simics",
        "hsd_root_cause":  "QAT FMOD integration into latest DMR VP Simics image; root cause not specified in ticket fields.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Not provided.",
        "hsd_conclusion":  "sw.arch",
    },
    "14022136667": {
        "hsd_component":   "platform.driver.qat",
        "hsd_root_cause":  "Environment/ingredient mismatch: QAT5.1 Windows driver supports single-signed ROM only while default Simics CPM ROM moved to dual-signed; mismatch prevents firmware load, causing Windows device power failure/yellow-bang.",
        "hsd_fix":         "Use cpm51_singleSign.rom; align Simics release/ROM, driver version, and FW binaries; driver qat5.1.w.5.1.0-00014_6 with correct single-signed ROM.",
        "hsd_actual_logs": "Simics logs; Windows device manager behavior; win2022_QAT_simics.zip, Failure_UCC_FMOD-0.92.5.zip; FCU signature verification failures.",
        "hsd_conclusion":  "",
    },
    "14022217283": {
        "hsd_component":   "platform.driver.dsa",
        "hsd_root_cause":  "Incorrect implementation of PASID behavior in DMR Simics CPU model (PASID MSR/PASID spec handling), leading to VT-d/PASID table issues and DSA multi-WQ hangs/timeouts.",
        "hsd_fix":         "Simics CPU model update (fixed in DMR Simics 2024ww38.3.00_46).",
        "hsd_actual_logs": "dmesg: repeated There's no HPT table for the pasid and VT-d faults (fault reason 0x59); ww19-failure.zip, WW34_Intel_next_6.11.zip, DSA_fix.log.",
        "hsd_conclusion":  "",
    },
    "14022366956": {
        "hsd_component":   "val.env.tool",
        "hsd_root_cause":  "IAA compress-with-dictionary test failed with AECS format error (error 0x2d) indicating software/modeling bug leading to analytics error status.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "oakstream logs and iaxrand.logs.",
        "hsd_conclusion":  "sw.bug",
    },
    "14022555397": {
        "hsd_component":   "platform.simics.platform",
        "hsd_root_cause":  "cpa_sample_code compression failures caused by running Static deflate test when device did not support Static Huffman capability.",
        "hsd_fix":         "Skip Static deflate test when Static Huffman not supported; run only dynamic deflate on DMR.",
        "hsd_actual_logs": "Not provided.",
        "hsd_conclusion":  "",
    },
    "14022982239": {
        "hsd_component":   "val.vp.simics",
        "hsd_root_cause":  "IAA defeature logic change in VP-SIMICS did not update OPCAP0 when DEFTR5 was programmed, preventing enabling memory-move opcode.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Not provided.",
        "hsd_conclusion":  "sw.bug",
    },
    "14023448207": {
        "hsd_component":   "val.vp.simics",
        "hsd_root_cause":  "VP-SIMICS did not reflect programming of IAA DEFTR3 override into DEV3EXTCAP.EXTCAPID; new DMR feature not modeled/propagated correctly.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Not provided.",
        "hsd_conclusion":  "sw.arch",
    },
    "14023472574": {
        "hsd_component":   "platform.simics.platform",
        "hsd_root_cause":  "Simics crashed (UNKNOWN EXCEPTION/segfault) during QAT FLR due to Simics platform issue triggered by FLR handling.",
        "hsd_fix":         "Simics platform fix (commit c50ed74316d76bd7057181555a87a46d6c3298f0) to address random crashes during FLR.",
        "hsd_actual_logs": "Attached Simics logs bundle: dmr_qat_unknown_exception_flr.zip.",
        "hsd_conclusion":  "",
    },
    "14023498612": {
        "hsd_component":   "platform.simics.platform",
        "hsd_root_cause":  "STV test binary failed: required test-code dependencies/symbols missing, so readThreadInfo command was not available.",
        "hsd_fix":         "Install additional missing dependencies for test code.",
        "hsd_actual_logs": "Referenced log bundle: stv_error_readThreadInfo.zip.",
        "hsd_conclusion":  "",
    },
    "14025355540": {
        "hsd_component":   "val.env.tool",
        "hsd_root_cause":  "dsa_test lacked batch support for DSA3 opcodes; missing tool capability.",
        "hsd_fix":         "Added batch support for additional DSA3 operations in referenced stable branch.",
        "hsd_actual_logs": "No debug logs; feature gap request with reference to stable branch update.",
        "hsd_conclusion":  "",
    },
    "14025366493": {
        "hsd_component":   "sw.driver",
        "hsd_root_cause":  "QAT Provider in OpenSSL keygen path failed to initialize keygen context for certificate requests (openssl req -new/-newkey); qatengine worked fine.",
        "hsd_fix":         "Fix to QAT Provider software.",
        "hsd_actual_logs": "Logs and execution notes attached.",
        "hsd_conclusion":  "",
    },
    "14025785454": {
        "hsd_component":   "hw.fuse",
        "hsd_root_cause":  "Incorrect CAPID8 fuse programming prevented IAA enumeration even when BIOS knobs were enabled; DSA/CPM enumerated but not IAA.",
        "hsd_fix":         "Override CAPID8 fuse values (ACC_0 programmed to expected value) so IAA enumerates and shows up in SV nodes.",
        "hsd_actual_logs": "Accelerator register dump comparisons with BIOS knobs enabled vs disabled; observation that IAA not enumerated until CAPID override.",
        "hsd_conclusion":  "no_root_cause",
    },
    "14025818604": {
        "hsd_component":   "bios",
        "hsd_root_cause":  "Configuration tracking: accelerators not enabled until IFWI/BIOS knob settings were confirmed enabled in specified BKC/IFWI build.",
        "hsd_fix":         "Validated that referenced BKC/IFWI image includes accelerator BIOS knobs enabled.",
        "hsd_actual_logs": "BIOS team response and BKC/IFWI image/version verification in comments.",
        "hsd_conclusion":  "no_root_cause",
    },
    "14025833391": {
        "hsd_component":   "hw.dsa",
        "hsd_root_cause":  "IAA/DSA error injection while running admin disable command can halt device such that command-completion interrupt is not reported, causing Linux IDXD/accel-config to hang waiting for completion.",
        "hsd_fix":         "Debug driver changes; action to track as driver-flow issue; perform FLR / check status/interrupt-cause instead of waiting indefinitely.",
        "hsd_actual_logs": "DSA/IAA register dumps before/after error injection; kernel dyndbg for idxd; dmesg logs; setpci/ITP pcicfg experiments; FLR via Linux and PythonSV sideband; PENQ alternate errinj stimulus logs.",
        "hsd_conclusion":  "no_root_cause.rejected",
    },
    "14025905353": {
        "hsd_component":   "hw.cpm",
        "hsd_root_cause":  "Admin message base address must be programmed before loading firmware; FW caches admin message base address on first read, so programming it late causes me_status_get timeout failure.",
        "hsd_fix":         "Program required admin register before FW load; document requirement in CPM/QAT register spec.",
        "hsd_actual_logs": "CTX numbers after FW load; driver steps: mailbox/admin buffer address setup, timeout waiting for response.",
        "hsd_conclusion":  "doc",
    },
    "14025921116": {
        "hsd_component":   "hw.cpm",
        "hsd_root_cause":  "Spec/expectation mismatch: PRS Stopped bit behavior undefined when Enable=1 per PCIe spec; CPM RTL does not clear stop bit on enable, so test expecting it to clear is invalid for DMR.",
        "hsd_fix":         "No HW change for DMR; documentation/spec clarification recommended.",
        "hsd_actual_logs": "PCIe spec discussion and observed RTL behavior from mail thread in comments.",
        "hsd_conclusion":  "doc",
    },
    "14025967580": {
        "hsd_component":   "hw.iax",
        "hsd_root_cause":  "Documentation issue: HAS incorrectly stated IPICTL-based ERRINJCTL injection stimulus; IPICTL tags all outgoing reads (not just descriptor reads), so injection can hit other completions.",
        "hsd_fix":         "HAS documentation updated (cloned to doc ticket fix_id=14025981201).",
        "hsd_actual_logs": "ERRINJCTL=0xe1 usage description; observed behavior during disable device/WQ admin command.",
        "hsd_conclusion":  "doc",
    },
    "14025968370": {
        "hsd_component":   "fw.cpm",
        "hsd_root_cause":  "QAT behavior after ~32 batched ENQCMD descriptors pointing to firmware-side handling issue; FW not reading from request descriptor in failing case; no definitive root cause identified.",
        "hsd_fix":         "No fix recorded (ticket merged/rejected).",
        "hsd_actual_logs": "CPM CSR dumps; driver logs; SAL logs; transactor logs on indirect/hybrid FPGA; batched descriptor run logs (batched.log) and descriptor request/response dumps.",
        "hsd_conclusion":  "no_root_cause.rejected",
    },
    "14025991026": {
        "hsd_component":   "hw.dsa",
        "hsd_root_cause":  "Linux driver bug: on boot it only clears DSA/IAA DEVSTS on one PCI segment, leaving stale DEVSTS bits on the other segment (varies by kernel version).",
        "hsd_fix":         "Linux driver update needed to clear stale registers on boot across all segments.",
        "hsd_actual_logs": "PythonSV reads of devsts per segment (segment0 vs segment1); lspci output showing both segments; kernel version comparisons.",
        "hsd_conclusion":  "sw.bug",
    },
    "14025998125": {
        "hsd_component":   "sw.driver",
        "hsd_root_cause":  "Platform/PM readiness issue on cold boot: device not ready to accept/authenticate FW reliably with PO workaround; FW auth failures during cold boot on ESXi.",
        "hsd_fix":         "Introduce delay after SSM reset in ESXi QAT driver (available in driver build 3.1.3.22).",
        "hsd_actual_logs": "ESXi dmesg: authentication errors (FCU_STATUS=0x5) during boot; unload/rebind makes FW load succeed; 3.1.3.22 install log confirming no auth issues.",
        "hsd_conclusion":  "",
    },
    "14025998683": {
        "hsd_component":   "val.env.tool",
        "hsd_root_cause":  "Running trustmate test_wac_agent_to_func_reg_positive_write() causes subsequent PythonSV iosfsbRspError requiring power-cycle reset; environment/tool bug.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Described behavior: trustmate test causes iosfsbRspError; power-cycle required; logs attached.",
        "hsd_conclusion":  "env.bug",
    },
    "14026004873": {
        "hsd_component":   "sw.driver",
        "hsd_root_cause":  "Driver regression after adding initial QAT 5.1w support: SYM and wireless crypto share ring type; driver incorrectly mapped SYM threads like wireless case during initial device configuration, leading to segfaults in SYM workloads.",
        "hsd_fix":         "Engineering build with fix for SYM service HW arbiter setup; verified with QAT driver 3.1.5.24-DMR-QAT-PRE-ALPHA.",
        "hsd_actual_logs": "ESXi install/load logs; cipher_sample passes but cpa_sample_code segfaults; engineering build resolves issue.",
        "hsd_conclusion":  "",
    },
    "14026024415": {
        "hsd_component":   "val.env.tool",
        "hsd_root_cause":  "TMAN/PCIetc EV buffer flow: cannot allocate Arden EV memory target / BlockTrk target; environment/tool bug.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Test failure log: cannot allocate Arden EV memory target / BlockTrk target; attachments referenced.",
        "hsd_conclusion":  "env.bug",
    },
    "14026030387": {
        "hsd_component":   "hw.iax",
        "hsd_root_cause":  "Two scenarios where RTL does not set INTCAUSE.CommandCompletion: (1) device transitions to HALT while admin command is processing, or (2) admin command submitted after device is already in HALT.",
        "hsd_fix":         "No fix captured (wont_validate).",
        "hsd_actual_logs": "PythonSV register sequence: parity injection via ERRINJCTL; cmdcpl bit not set while CMDSTATUS indicates completion-with-error; intcause.show() dump.",
        "hsd_conclusion":  "hw.bug",
    },
    "14026047337": {
        "hsd_component":   "hw.iax",
        "hsd_root_cause":  "When accelerator transitions to HALT while admin command is in progress (e.g., parity error pending), RTL updates CMDSTATUS but does not set INTCAUSE.CommandCompletion, so software may think command hung.",
        "hsd_fix":         "No RTL fix; disposition rejected in DMR with errata and clone. Workaround: host/driver can poll CMDSTATUS since it updates correctly.",
        "hsd_actual_logs": "PythonSV register reads/writes: gensts, swerror*, cmdstatus, intcause.show(), perrstslog, errinjctl - demonstrating missing cmdcpl bit despite completion status.",
        "hsd_conclusion":  "hw.bug",
    },
    "14026147117": {
        "hsd_component":   "hw.dsa",
        "hsd_root_cause":  "With relaxed ordering enabled, an Mpush write scenario allows a read to bypass a prior write (out-of-order), violating spec and causing data corruption seen as incorrect data pattern in DSA sandstone test.",
        "hsd_fix":         "BIOS workaround (fix_ip=bios, fix_id=14026111032). Mitigations: disable DSA relaxed ordering or keep transfer length < 8K.",
        "hsd_actual_logs": "Sandstone/hammer-unified telemetry entry: failing seed, cpu, ucode, failing byte mismatch at dsa_fill.c:258.",
        "hsd_conclusion":  "hw.bug",
    },
    "14026147322": {
        "hsd_component":   "hw.iax",
        "hsd_root_cause":  "IAA data miscompare in sandstone; memcmp_offset could not locate difference; no root cause identified, rejected.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Sandstone telemetry entry and failing signature for IAX data-miscompare.",
        "hsd_conclusion":  "no_root_cause.rejected",
    },
    "14026158045": {
        "hsd_component":   "val.env.automation",
        "hsd_root_cause":  "PCIe remove/rescan automation: devices still present after removal (not all devices were removed); script/content issue.",
        "hsd_fix":         "Fixed in accel configuration scripts (commit b86f254adaee08a4790f52edc81ecddbbee44b6c).",
        "hsd_actual_logs": "Kayak/SSH debug output: loop 1, Devices found after removal: 2; script exit code 3; NGA testResult links.",
        "hsd_conclusion":  "",
    },
    "14026178339": {
        "hsd_component":   "val.env.execution",
        "hsd_root_cause":  "NGA run logs incomplete: run aborted around 2-hour whole-cycle timeout; timeout parameters mis-set.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Described behavior: rocket log not complete; tests not executed; timeout settings mentioned.",
        "hsd_conclusion":  "",
    },
    "14026198585": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "IAA compression auto mode showed data mismatches (e.g., expected 0x6f vs observed 0x5f) during decompression path; marked cannot reproduce.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Raw descriptor dump; address/byte comparison table with FAIL markers; command line and NGA logs path.",
        "hsd_conclusion":  "",
    },
    "14026198752": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "Type conversion operations (inter-domain int and standalone float) failed verify phase (FAILVECT) while completion records reported success; marked cannot reproduce.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "FAILVECT descriptor numbers for INT and FLOAT cases; NGA testline/testResult links and rocket commands.",
        "hsd_conclusion":  "",
    },
    "14026198936": {
        "hsd_component":   "val.env.execution",
        "hsd_root_cause":  "System discovery failed: unsupported/invalid Arden device/vendor IDs leading to Unknown arden id! rid = 0xf.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Atlas log: Skipping Arden Device ID not supported / Vendor ID invalid; AcreError Unknown arden id! rid = 0xf.",
        "hsd_conclusion":  "",
    },
    "14026200668": {
        "hsd_component":   "val.env.configuration",
        "hsd_root_cause":  "Inter-domain copy test: source/destination data mismatch during verify even though completion record showed success; marked cannot reproduce.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Mismatch dump with addresses/bytes; completion record status 0x1 (Success); NGA testResult link.",
        "hsd_conclusion":  "",
    },
    "14026211428": {
        "hsd_component":   "val.env.tool",
        "hsd_root_cause":  "Atlas/ACRE script error (KeyError: 3) due to bad arguments; DRAM usage error in atlas.log attributed to script arguments.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Atlas exception KeyError: 3; rocket command line; NGA testline link.",
        "hsd_conclusion":  "",
    },
    "14026382931": {
        "hsd_component":   "val.env.tool",
        "hsd_root_cause":  "Docker pull step failed: Docker daemon not running (cannot connect to /var/run/docker.sock).",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Failure text: Cannot connect to the Docker daemon; docker pull command shown.",
        "hsd_conclusion":  "",
    },
    "14026385355": {
        "hsd_component":   "val.env.automation",
        "hsd_root_cause":  "NGA flow post-step TPostTest_PreTestFailChk fails even though rocket accelerator tests pass; NgaHelper/automation issue; rejected as not a defect.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Cleanup path to execution logs; NgaHelper log referenced.",
        "hsd_conclusion":  "",
    },
    "14026466314": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "PRS tests failed due to wrong PRS flags/configuration when randomizing descriptor page fault handling, causing perfmon HW vs SW count mismatch.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Atlas/rocket error from dsa_policy.c showing perfmon counter mismatch; NGA testResult links.",
        "hsd_conclusion":  "",
    },
    "14026466867": {
        "hsd_component":   "val.env.automation",
        "hsd_root_cause":  "System hang during DSA ELEMENT_WISE_PRS test; no root cause determined.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Hang signature: MokaHangdump failure; NGA result link.",
        "hsd_conclusion":  "no_root_cause",
    },
    "14026487968": {
        "hsd_component":   "val.env.configuration",
        "hsd_root_cause":  "PRS targets/configs not being generated: missing/incorrect VTd base variant configuration for QAT; needs PRS targets and PRS options enabled.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Problem statement and rocket command in description.",
        "hsd_conclusion":  "sw.bug",
    },
    "14026492816": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "IFWI regression caused fatal machine check / QAT DEVHALT during cpa_sample_code (kernel panic or hang).",
        "hsd_fix":         "IFWI regression resolved in WW50 release.",
        "hsd_actual_logs": "Kernel panic/MCE/QAT DEVHALT dmesg excerpt; attached logs referenced.",
        "hsd_conclusion":  "",
    },
    "14026506052": {
        "hsd_component":   "sw.application",
        "hsd_root_cause":  "Config generation failed: ARAM BAR not programmed for CXL target cxl-05, causing exception in arden_get_target_sizes.",
        "hsd_fix":         "Retest with WW50.4 release.",
        "hsd_actual_logs": "NGA test result link (rocket run + result).",
        "hsd_conclusion":  "env.bug",
    },
    "14026508246": {
        "hsd_component":   "val.env.configuration",
        "hsd_root_cause":  "System hang during QAT test execution prevented complete NGA logs; environment hang blocked test conclusion.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "NGA: TargetHang_Communicator; ITP error: Unable to access a disabled core; Moka could not collect data; Axon link.",
        "hsd_conclusion":  "env.bug",
    },
    "14026533264": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "System hang during SV module unmount/mount sequence (umountsv/mountsv), blocking QAT testing; svos/svfs depends on CPM for mount operations.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Command sequence that triggers hang: echo blacklist lines, killmax, umountsv, rmmodsvos2, mountsv; NGA failure link.",
        "hsd_conclusion":  "env.bug",
    },
    "14026536280": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "Cannot reproduce: inter-domain Fill SASS reported SWERROR err_code 0x1b (completion record address not 32-byte aligned).",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "SWERROR dump: err_code=0x1b, wq_index=0xd, operation=0xff, pasid=0x34cca; DSA target info tables; early end before phase Verify 2; rocket command and NGA link.",
        "hsd_conclusion":  "no_root_cause.rejected",
    },
    "14026542532": {
        "hsd_component":   "hw.big_core",
        "hsd_root_cause":  "Cannot reproduce machine check errors in MLC while running DSA content; no root cause identified.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Command line and NGA result link only.",
        "hsd_conclusion":  "no_root_cause.rejected",
    },
    "14026543468": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "Cannot reproduce: PRS dualcast flow reported SWERROR err_code 0x22 (address translation error) while completion status appeared as 0x0 (unknown).",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "SWERROR dump: err_code=0x22; DSA target info table; descriptor/completion record decode; raw completion record (all zeros); rocket command and NGA link.",
        "hsd_conclusion":  "no_root_cause.rejected",
    },
    "14026553474": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "Cannot reproduce: PRS scenario hit VT-d error - failure to correct PTE based on page request descriptor; possibly invalid GVA/GPA not in domain list.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Kernel log: vtdProcessPageRequestDesc: unsuccessful in correcting the PTE ... possibly due to an invalid GVA/GPA not in domain list; faultingAddress values; rocket command.",
        "hsd_conclusion":  "no_root_cause.rejected",
    },
    "14026559709": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "Cannot reproduce: ATS invalidations + PRS failing with 0x0 SW completion status while HW hwerror register shows 0x1000.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Register dumps (prssts, prsreqcap, prsreqalloc, hwerror=0x1000); SWERROR dump: err_code=0x0; Completion record status Error: 0x0; rocket command and NGA link.",
        "hsd_conclusion":  "no_root_cause.rejected",
    },
    "14026577326": {
        "hsd_component":   "val.env.tool",
        "hsd_root_cause":  "Test failure due to scripting/tooling issue: ACRE script bad arguments causing KeyError: 3; ticket rejected/merged.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "atlas.log: Exception (KeyError): 3; command line provided; NGA link.",
        "hsd_conclusion":  "no_root_cause.rejected",
    },
    "14026579612": {
        "hsd_component":   "val.env.configuration",
        "hsd_root_cause":  "NGA rocket logs incomplete because run was aborted around 2-hour whole-cycle timeout; timeout settings not set correctly.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Narrative indicating rocket log not complete and run aborted after ~2 hours.",
        "hsd_conclusion":  "env.bug",
    },
    "14026584382": {
        "hsd_component":   "hw.punit",
        "hsd_root_cause":  "Cannot reproduce machine check errors in MLC, PUNIT, CB06 while running DSA content; no root cause identified.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Command line and NGA/FDU5 result link only.",
        "hsd_conclusion":  "no_root_cause.rejected",
    },
    "14026584582": {
        "hsd_component":   "hw.iax",
        "hsd_root_cause":  "Not a bug: MCE seen when issuing 64B CPU read to IAA/DSA config space at specified address; rejected as not a defect.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Kernel MCE/panic snippet: bank/code be2000140100113a, ADDR 0x100000e00000, Kernel panic - not syncing: Fatal machine check.",
        "hsd_conclusion":  "not_a_bug",
    },
    "14026598028": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "ECDH key generation failures with OpenSSL speed tests using QAT Provider API: QAT engine/package content needs compliance updates.",
        "hsd_fix":         "QAT Engine package updates to comply with QAT Provider API requirements.",
        "hsd_actual_logs": "Log file qat_provider_openssl_ecdh_async_jobs_failures.log attached (not retrievable).",
        "hsd_conclusion":  "",
    },
    "14026598567": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "RSA failures with OpenSSL speed tests using QAT Provider API: content/package issue in QAT engine/BKC ingredients.",
        "hsd_fix":         "Resolved by updates to QAT Engine package (qatengine) and BKC WW50 ingredients.",
        "hsd_actual_logs": "Log file qat_provider_openssl_rsa2048_failures.log attached (not retrievable).",
        "hsd_conclusion":  "",
    },
    "14026616021": {
        "hsd_component":   "val.env.configuration",
        "hsd_root_cause":  "CPM devices not showing up in SVOS during pre-test (software/configuration issue).",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Statement that devices were not showing up.",
        "hsd_conclusion":  "sw.bug",
    },
    "14026616073": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "CPM NGA test fails: docker reports No free test card found (environment/resource allocation issue).",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Error string: No free test card found; command line shown.",
        "hsd_conclusion":  "env.bug",
    },
    "14026616153": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "IAA compression mode performance mode failure: iaxrand data verify mismatch/unregister errors; rejected as cannot reproduce.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "RTM/iaxrand output: errcode 144 data verify mismatch and errcode 78 unregister errors.",
        "hsd_conclusion":  "no_root_cause.rejected",
    },
    "14026616262": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "iax_remove_deflate_base.py workaround script incorrectly removed DEFLATE completely instead of just the base.",
        "hsd_fix":         "Fix already pushed.",
        "hsd_actual_logs": "Failure marker reference in description.",
        "hsd_conclusion":  "env.bug",
    },
    "14026616375": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "IAA PRS test with AD set shows multiple RTM unregister errors and iaxrand data verify mismatches (environment/content issue).",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Extensive RTM output: process exit codes and data verify mismatch lines.",
        "hsd_conclusion":  "env.bug",
    },
    "14026616507": {
        "hsd_component":   "val.env.execution",
        "hsd_root_cause":  "Docker pull of dmr image failing during CPM test; rejected as cannot reproduce.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Docker issue causing CPM test failure; no concrete logs.",
        "hsd_conclusion":  "no_root_cause.rejected",
    },
    "14026616546": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "IAA test fails: AcreError base name iaxrand.prog_props not found in generated cfg (environment/config generation issue).",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Python backtrace and AcreError message with file paths and call stack.",
        "hsd_conclusion":  "env.bug",
    },
    "14026620470": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "QAT service chaining test reports failed jobs with response status flag 0x80; response descriptor byte 5 is 0x0 (insufficient error info).",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "parti command output and FW verifier/debug/INFO lines: jobs stats, OBC match, status flags.",
        "hsd_conclusion":  "sw.bug",
    },
    "14026626024": {
        "hsd_component":   "val.env.automation",
        "hsd_root_cause":  "Rocket test passed but NGA reporting showed failure for HCleanUp_Axon_Inventory; environment reporting/automation issue.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Testline failure indicator text in description.",
        "hsd_conclusion":  "env.bug",
    },
    "14026668250": {
        "hsd_component":   "val.env.automation",
        "hsd_root_cause":  "Ticket rejected as not a defect; test failures attributed to TPostTest_ProjectEnd errors.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Multiple NGA test result links; no additional debug artifacts.",
        "hsd_conclusion":  "not_a_bug",
    },
    "14026679112": {
        "hsd_component":   "val.env.automation",
        "hsd_root_cause":  "Tests failing due to TPostTest_PreTestFailChk FLEXCON-ERROR (flexcon_security, mcheck); no root cause identified.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "NGA test result link; FLEXCON-ERROR flexcon_security mcheck failure noted.",
        "hsd_conclusion":  "no_root_cause",
    },
    "14026683472": {
        "hsd_component":   "sw.application",
        "hsd_root_cause":  "Config file generation fails: AcreError indicating ARAM BAR is not programmed for cxl-07 (arden_get_target_sizes).",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "AcreError/exception text in description; NGA test result link.",
        "hsd_conclusion":  "sw.bug",
    },
    "14026683520": {
        "hsd_component":   "sw.application",
        "hsd_root_cause":  "ivman failed to add ETSEG_MEM_LOW memory to VT-d domain (ioctl invalid argument), leading to setup failure; classified as software bug.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "ivman log: configuration banner, domain IDs, vtdAddMemoryToDomain ioctl failure with addresses/sizes; rocket command line and NGA links.",
        "hsd_conclusion":  "sw.bug",
    },
    "14026683541": {
        "hsd_component":   "val.env.tool",
        "hsd_root_cause":  "Event log/error injection flow inconsistency: EVL/SWERROR detected 0x12, but completion record returned 0x0 (unknown status); treated as environment/tool bug.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "EVL/SWERROR messages, descriptor dumps, completion record dumps, DSA interrupt info, NGA link.",
        "hsd_conclusion":  "env.bug",
    },
    "14026683542": {
        "hsd_component":   "sw.application",
        "hsd_root_cause":  "Acre/Atlas failed to create PCIe EV targets: Could not find PCIE; concluded not a bug.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Python traceback from acre.py: Exception Could not find PCIE; rocket command line and NGA result link.",
        "hsd_conclusion":  "not_a_bug",
    },
    "14026683560": {
        "hsd_component":   "hw.punit",
        "hsd_root_cause":  "Machine check errors observed during DSA content in MLC, PUNIT, CBB0 CCF, CCF3, CBO4; rejected as cannot reproduce.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Rocket command line and NGA result link.",
        "hsd_conclusion":  "no_root_cause.rejected",
    },
    "14026683622": {
        "hsd_component":   "val.env.configuration",
        "hsd_root_cause":  "DSA test reported SWERROR err_code 0x12 (non-zero reserved field) and completion record status issues; treated as environment/configuration bug.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "SWERROR register dump values, error code 0x12, rocket command line, NGA result link.",
        "hsd_conclusion":  "env.bug",
    },
    "14026746548": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "No free test card found during concurrent accelerator run; rejected as cannot reproduce.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Rocket command line and NGA failure link.",
        "hsd_conclusion":  "no_root_cause.rejected",
    },
    "14026753468": {
        "hsd_component":   "doc.has",
        "hsd_root_cause":  "Documentation error in DSA 3.0 spec Section 5.5: incorrectly states flag bits 5,6,15 are reserved; bit 5 is repurposed as Cache Control 3.",
        "hsd_fix":         "DSA EAS document fix applied.",
        "hsd_actual_logs": "No debug logs (documentation issue); spec references and proposed corrected sentence.",
        "hsd_conclusion":  "doc",
    },
    "14026766087": {
        "hsd_component":   "val.env.tool",
        "hsd_root_cause":  "IAA/DSA PRS count verification failed: perfmon HW vs SW count mismatch by 1; treated as environment/tool issue.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Failing call-site logs (iax_verify_perfmon_counts/iax_verify_status), rocket command line and properties snippet for PRS error injection.",
        "hsd_conclusion":  "env.bug",
    },
    "14026810657": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "Environment/content issue: Supercollider/PCIe handle access failed (getPcieHandle failed to read PCIE DID), causing test to exit with status 4.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Supercollider log: seed, command generation, Failed to read PCIE DID error; NGA links.",
        "hsd_conclusion":  "env.bug",
    },
    "14026811349": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "No root cause identified for flexcon errors seen for security content (SGX/TDX/SAF) running ACC content.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "NGA test result links only.",
        "hsd_conclusion":  "no_root_cause",
    },
    "14026822165": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "CXL LCD address aliasing mechanism not understood by DSA/IAA when using CXLHDM targets, leading to mismatch in dualcast operation.",
        "hsd_fix":         "Ran on FDU1 with Montage cards using rmw workarounds; issue did not reproduce in rerun.",
        "hsd_actual_logs": "High-level problem statement and NGA test result link only.",
        "hsd_conclusion":  "env.bug",
    },
    "14026828275": {
        "hsd_component":   "val.env.execution",
        "hsd_root_cause":  "Flexcon sheet had incorrect notation for pxp11 port, causing registers not found in namednodes due to incorrect flexcon mapping.",
        "hsd_fix":         "Updated flexcon sheet notation (ww3.1).",
        "hsd_actual_logs": "pysvext/moka Register not found in namednodes errors for socket0...pxp11... registers; NGA results links.",
        "hsd_conclusion":  "env.bug",
    },
    "14026836921": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "IAA P2M test failing: environment/content bug causing TMAN target selector unable to add pid to TMAN target for PCIe-to-DRAM P2M traffic.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "TMAN/Target Selector errors; rocket command line (iax_focus_tests[i=P2M]).",
        "hsd_conclusion":  "env.bug",
    },
    "14026841963": {
        "hsd_component":   "val.env.tool",
        "hsd_root_cause":  "DSA + IAX + PCIe + MSIx test fails with Unable to init telemetry error.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Failure summary: Unable to init telemetry; rocket command line and NGA link.",
        "hsd_conclusion":  "",
    },
    "14026876637": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "Flexcon_mem failing with MRDIMM DQ CRC, JedecIt, and Command Address Parity check failures on FDU5.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Flexcon_mem error snippets: MRDIMM DQ CRC, JedecIt, Command Address Parity checks failed; NGA link.",
        "hsd_conclusion":  "",
    },
    "14026877551": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "Flexcon_mem failing with Mem Size and AMAP errors on FDU6.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Flexcon_mem error snippets: Mem Size and Amap checks failed; NGA link.",
        "hsd_conclusion":  "",
    },
    "14026885969": {
        "hsd_component":   "sw.application",
        "hsd_root_cause":  "tman parser error: mmcfg is not a valid address during DSA validation run.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "tman output: ERROR - mmcfg is not a valid address; rocket command line and NGA link.",
        "hsd_conclusion":  "",
    },
    "14026908999": {
        "hsd_component":   "hw.dsa",
        "hsd_root_cause":  "DSA gather copy returns 0x1A error after timeout for sglsize 2 and 4: RTL requires completing all source reads before handshake, can exhaust internal completion-buffer allocations.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "dsa_test_v2 invocation with parameters; symptom: timeout then 0x1A error for sglsize 2 and 4 at specific lengths.",
        "hsd_conclusion":  "",
    },
    "14026910498": {
        "hsd_component":   "val.env.configuration",
        "hsd_root_cause":  "Post Test failed during HCleanUp_Axon_Inventory step.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Host post-test failure log: HCleanUp_Axon_Inventory Axon upload/info and content-types uploaded.",
        "hsd_conclusion":  "",
    },
    "14026910895": {
        "hsd_component":   "val.env.configuration",
        "hsd_root_cause":  "QAT power gating enabling script error; duplicate/rejected ticket.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Same power_gating_enable_qat.py failure summary.",
        "hsd_conclusion":  "",
    },
    "14026911451": {
        "hsd_component":   "val.env.automation",
        "hsd_root_cause":  "QAT power gating enabling script error during automation run.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Command line: python3 power_gating_enable_qat.py and rocket invocation.",
        "hsd_conclusion":  "",
    },
    "14026912504": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "QAT ARB validation requires DAM-disabled IFWI; with current setup behavior differed from expectations.",
        "hsd_fix":         "Use DAM-disabled IFWI to validate QAT ARB flow.",
        "hsd_actual_logs": "Sysfs read/write steps and observed values; log file qat_arb_test_logs.txt referenced.",
        "hsd_conclusion":  "",
    },
    "14026942339": {
        "hsd_component":   "val.env.execution",
        "hsd_root_cause":  "PCIe flexcon failure for PXP3 port on FDU7: ControllerSpeed and Speed checks failed.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Flexcon error snippets: ControllerSpeed and Speed checks failed for tag S0_PXP3_Port0.",
        "hsd_conclusion":  "",
    },
    "14026970419": {
        "hsd_component":   "hw.iax",
        "hsd_root_cause":  "HW defect in the accelerator sampling logic: data_poison is captured one cycle too early, so only the first 64B of poisoned memory is detected; poison beyond first 64B is missed.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Repro steps using Linux EINJ sysfs paths; observed vs expected behavior for poisoned memory reads.",
        "hsd_conclusion":  "",
    },
    "14026973320": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "All accelerators + supercollider test failed due to supercollider error status 3 on FDM200 config; cannot allocate target space.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Supercollider console output: FAILED with status 3; setNewBlkTgt: can't allocate target space to fit Thread78 (MBkRd) in Target[224].",
        "hsd_conclusion":  "",
    },
    "14026973887": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "DSA + IAA max transfer size test failed due to TMAN timeout error.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "tman timeout message; NGA test result link.",
        "hsd_conclusion":  "",
    },
    "14026974756": {
        "hsd_component":   "val.env.configuration",
        "hsd_root_cause":  "MCE during combined accelerators + supercollider IDI stress; likely hardware hang.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Axon record-viewer link and NGA failure link referenced.",
        "hsd_conclusion":  "",
    },
    "14026976037": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "QAT AEAD test failed during setup: DMA pool memory allocation failed (No such device or address), preventing test execution.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Parti logs: CpmRingConfig::setup() exception: CSadPoolAllocator::Allocate failed, rc=-1, errno=6 No such device or address.",
        "hsd_conclusion":  "",
    },
    "14026984328": {
        "hsd_component":   "val.env.execution",
        "hsd_root_cause":  "PCIe/CXL flexcon failure for PXP11/12 port on FDU4; ticket merged with no root cause documented.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Only NGA test result/failure links referenced.",
        "hsd_conclusion":  "",
    },
    "14026988973": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "Flexcon_uxi failure; no root cause documented in ticket.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Only NGA links referenced.",
        "hsd_conclusion":  "",
    },
    "14026989052": {
        "hsd_component":   "val.env.configuration",
        "hsd_root_cause":  "PythonSV register access issues (VID/DID read as 0, type read as 0xFF) impacting Flexcon CXL/PCIe checks; suspected link training/presence/EDSFF issues on specific ports.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Flexcon log: VID/DID check failures (VID=0x0000 vs 0x8086), type check failure (Type-153 vs expected Type-3), presence check observations.",
        "hsd_conclusion":  "",
    },
    "14026989106": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "Flexcon_rdt failure; ticket merged with no root cause documented.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Only NGA links referenced.",
        "hsd_conclusion":  "",
    },
    "14026997858": {
        "hsd_component":   "hw.pcie",
        "hsd_root_cause":  "PCIe protocol errors including Unsupported Request and MCTP order issues reported by pcietc.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "pcietc output: Uncorrectable Error (Unsupported Request), Device Status unsupported request detected, Protocol Errors; PCIETC_PROTOCOL_ERROR.",
        "hsd_conclusion":  "",
    },
    "14027018841": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "pcietc data verification failed with pattern mismatch (PCIETC_VERIFY_PATTERN_MISMATCH) indicating memory target data corruption during verification.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "pcietc error output with corrupted memTgt dump; fastpath_upstream_verify failure with PCIETC_VERIFY_PATTERN_MISMATCH.",
        "hsd_conclusion":  "",
    },
    "14027018947": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "PCIe completion timeout and protocol errors during pcietc run; mctp_bcast workaround applied but timeout persists.",
        "hsd_fix":         "mctp_bcast workaround applied.",
        "hsd_actual_logs": "pcietc output: Uncorrectable Error (Completion Timeout), Device Status non-fatal error, Protocol Errors; pcietc_common_card_verify() failure with PCIETC_PROTOCOL_ERROR.",
        "hsd_conclusion":  "",
    },
    "14027066700": {
        "hsd_component":   "hw.iax",
        "hsd_root_cause":  "IAA/IAX engine hang during random nightly automation; suspected correlation to back-to-back descriptors with source page faults causing hang.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "HWERROR.active=1, CMDSTATUS.active=1, event log entries indicating DWQ WQ full condition.",
        "hsd_conclusion":  "",
    },
    "14027067185": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "Config generation failed due to unhandled CXL HDM attribute value (KeyError: 8) in DRAM dynamic CXL creation code/path mapping.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Python backtrace from acre.py and dram.py: Exception (KeyError): 8 during dram_create_dynamic_cxl path/attribute lookup.",
        "hsd_conclusion":  "",
    },
    "14027067222": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "DSA descriptor template/config generation references a non-existent path (desc_types.DELTA), causing chooser/config parsing to fail.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Test console/backtrace showing chooser reference_init / ch_rand_init failures and config parse failure (Unable to find referenced path desc_types.DELTA; Key errors in chooser initialization).",
        "hsd_conclusion":  "",
    },
    "14027067274": {
        "hsd_component":   "hw.scf.ubr",
        "hsd_root_cause":  "Hardware bug: hang associated with HW.MCE.HAMVF error during DSA PCIe element-wise test.",
        "hsd_fix":         "None documented.",
        "hsd_actual_logs": "Axon record-viewer link for TargetHang; failure context: event TargetHang and data_collection_recovery failed.",
        "hsd_conclusion":  "hw.bug",
    },
    "14027067334": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "Test infrastructure/resource issue: No free test card found for PCIe test; merged/rejected.",
        "hsd_fix":         "None documented.",
        "hsd_actual_logs": "RTM output: pcietcrand exited errcode 1 No free test card found.",
        "hsd_conclusion":  "no_root_cause.rejected",
    },
    "14027067531": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "DSA perfmon HW vs SW count mismatch (hw_counts=7 vs sw_counts=16); merged/rejected with no documented root cause.",
        "hsd_fix":         "None documented.",
        "hsd_actual_logs": "Console logs from dsa_verify_perfmon_counts showing counter mismatch; PMON counter dump.",
        "hsd_conclusion":  "no_root_cause.rejected",
    },
    "14027067691": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "Test/config mismatch: mixed mode enabled while PASID set to No leading to unsupported plugin/initialization failure.",
        "hsd_fix":         "None documented.",
        "hsd_actual_logs": "RTM logs: scatter_gather plugin not supported, target selector init failures; atlas command line.",
        "hsd_conclusion":  "no_root_cause",
    },
    "14027093118": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "Environment bug: Memory Move (Batched) operation failing due to data mismatch errors in verify phase for PCIe-to-PCIe batched mem move.",
        "hsd_fix":         "None documented.",
        "hsd_actual_logs": "Test command line and mismatch errors in verify phase.",
        "hsd_conclusion":  "env.bug",
    },
    "14027102637": {
        "hsd_component":   "hw.iax",
        "hsd_root_cause":  "Suspected invalidation-queue address misconfiguration triggered by IAA read to IOMMU BAR; dmesg reports invalidation queue errors infinitely; rejected/no root cause documented.",
        "hsd_fix":         "None documented.",
        "hsd_actual_logs": "/proc/cmdline; narrative of infinite dmesg invalidation queue errors.",
        "hsd_conclusion":  "no_root_cause.rejected",
    },
    "14027150156": {
        "hsd_component":   "val.env.configuration",
        "hsd_root_cause":  "Cannot reproduce; CXL_HW_UNEXPECTED_CHECK and CXL_HW_PRESENCE_CHECK in flexcon; no root cause documented.",
        "hsd_fix":         "None documented.",
        "hsd_actual_logs": "Only NGA result/failure links referenced.",
        "hsd_conclusion":  "no_root_cause.rejected",
    },
    "14027150648": {
        "hsd_component":   "val.env.configuration",
        "hsd_root_cause":  "Cannot reproduce; CXL_HW_UNEXPECTED_CHECK and Card_presence error in flexcon; no root cause documented.",
        "hsd_fix":         "None documented.",
        "hsd_actual_logs": "Only NGA result/failure links referenced.",
        "hsd_conclusion":  "no_root_cause.rejected",
    },
    "14027158895": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "Register default value mismatch: DEFTR3 (DSA/IAA) and DEFTR22 (DSA) programmed values differ from spec; rejected as no root cause.",
        "hsd_fix":         "None documented.",
        "hsd_actual_logs": "Register programmed vs spec value deltas for DEFTR3 and DEFTR22.",
        "hsd_conclusion":  "no_root_cause.rejected",
    },
    "14027163809": {
        "hsd_component":   "hw.iaa",
        "hsd_root_cause":  "Ticket closed as not a bug; IAA+ADR Blockfill test failed, ADR region readback all 0.",
        "hsd_fix":         "None documented.",
        "hsd_actual_logs": "Test procedure and result reported (ADR region readback all 0).",
        "hsd_conclusion":  "not_a_bug",
    },
    "14027176222": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "RTM config parse error: rtm.cfg used wrong/unknown config file format, causing test failure.",
        "hsd_fix":         "None documented.",
        "hsd_actual_logs": "RTM console output: Unknown config file format for rtm.cfg and Unable to parse rtm config file.",
        "hsd_conclusion":  "no_root_cause",
    },
    "14027203704": {
        "hsd_component":   "fw.cpm",
        "hsd_root_cause":  "Ticket closed as not a bug; invalid response seen in response descriptor every 32 jobs (Compression, decompression, Crypto) but not a defect.",
        "hsd_fix":         "None documented.",
        "hsd_actual_logs": "Repro summary and pass/fail descriptor-count observations; no explicit sysdbg/debug log artifacts.",
        "hsd_conclusion":  "not_a_bug",
    },
    "14027223286": {
        "hsd_component":   "val.env.configuration",
        "hsd_root_cause":  "PostTest failure caused by upstream PreTest Flexcon port/link presence failures on PXP9/PXP11 and expected CXL endpoint on IMH1/PXP9; PostTest failure is a symptom, not the root issue.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Flexcon.log, ExeLog.log, flexcon_verbose_pid*.report.json; LTSSM states (DET_SLEEP/DET_QUIET); NGA helper logs.",
        "hsd_conclusion":  "rejected",
    },
    "14027261180": {
        "hsd_component":   "hw.dsa",
        "hsd_root_cause":  "DSA does not generate completion record or event log writes when Invalid Request response is received for PRS (duplicate of 14027270401).",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Repro details/command line; observation about missing EVL/completion record writes; dmesg capturing IR for completion-record write.",
        "hsd_conclusion":  "rejected",
    },
    "14027270390": {
        "hsd_component":   "hw.dsa",
        "hsd_root_cause":  "RTL resource/flow-control issue: DSA waits to complete all read requests before handshaking to processing block after source reads; can exhaust internal completion-buffer allocations causing gather copy to return 0x1A error after timeout.",
        "hsd_fix":         "Rejected/marked as false positive for DMR; no workaround documented.",
        "hsd_actual_logs": "Repro command line (dsa_test_v2), scenario description, EVL vs SWERR behavior notes, sysdbg notes with planned debug steps.",
        "hsd_conclusion":  "",
    },
    "14027270401": {
        "hsd_component":   "hw.dsa",
        "hsd_root_cause":  "DSA does not generate completion record or event log writes when Invalid Request response is received for PRS; when EVL disabled SWERROR shows 0x1A.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Repro details and dsa_test_v2 command line; observations about missing EVL/completion record writes; dmesg capturing IR for completion-record write.",
        "hsd_conclusion":  "rejected",
    },
    "14027286159": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "Global reset script failure during QAT validation: MCA detected during ResetSV.py execution, timeout waiting for events.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "ResetSV.py execution log; timeout events; MCA register reads (ml2_cr_mc3_status, punit ras gpsb mc_status), error source logs, post code state.",
        "hsd_conclusion":  "",
    },
    "14027289733": {
        "hsd_component":   "sw.application",
        "hsd_root_cause":  "Thread-safety bug in external zlib-ng library (cpu_check_features) led to sporadic verification mismatches when AVX/SSE2 enabled.",
        "hsd_fix":         "Use zlib-ng with PR#1442 included (zlib-ng 2.1.0-beta1) which resolves the issue.",
        "hsd_actual_logs": "MCA dumps, mc_status.correrrorstatusind threshold indication, debug steps/commands (cd.mca_dump_dmr, cd.mca_decode), QAT validation test context.",
        "hsd_conclusion":  "",
    },
    "14027319973": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "Validation content/config issue: test variant name SG_CXL2CXL is not a valid/recognized test name in dsa_focus_tests, causing an exception.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Python stack trace: Exception: Invalid focus test name SG_CXL2CXL! and rocket command line.",
        "hsd_conclusion":  "",
    },
    "14027360894": {
        "hsd_component":   "val.env.tool",
        "hsd_root_cause":  "Validation tool issue: DSArand test cannot inject error code 0x18 (misaligned_desc_addr).",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Repro command line: rocket -M 5 --atlas \"--hw dram,dsa -v dsa_focus_tests[i=[batch,swerror_enable],error_code=misaligned_desc_addr]\".",
        "hsd_conclusion":  "",
    },
    "14027376512": {
        "hsd_component":   "hw.dsa",
        "hsd_root_cause":  "DSA RTL error-handling gap: gather copy descriptors with transfer size larger than configured WQ max transfer size are not reliably detected/rejected; RTL should check for out-of-range size and return error to software.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "dsa_test_v2 command lines, verbose output, descriptor dump, completion record status=Success, WQCFG confirmation via sv.* register reads.",
        "hsd_conclusion":  "",
    },
    "14027389776": {
        "hsd_component":   "hw.qat",
        "hsd_root_cause":  "CPM fMod content issue: CPM model/firmware did not correctly support SSM_DMA operation, leading to Simics error problem in getting slice type and workload hang.",
        "hsd_fix":         "Update CPM fMod to correctly handle SSM_DMA operation.",
        "hsd_actual_logs": "Simics error log: missing slice type; uart log, simics log, dmesg log attached; firmware md5sums, lsmod/modinfo, kernel cmdline.",
        "hsd_conclusion":  "",
    },
    "14027419708": {
        "hsd_component":   "hw.dsa",
        "hsd_root_cause":  "Hardware deadlock in DSA Reduce/Reduce-with-dual-cast for large transfer sizes due to translation request arbitration starvation: Src1 can consume all shared translation queue slots, starving Src2; Reduce requires both, so progress halts.",
        "hsd_fix":         "Workaround: restrict Reduce/ReduceDC transfer size (<=448KB trusted, 256KB untrusted); disable Reduce opcodes for untrusted SW. Future fix: alternate Src1/Src2 filling of translation queue.",
        "hsd_actual_logs": "DSA perfmon counter dumps in hung state (cntrcfg/cntrdata including EV_CL_READ/PROCESSED/WRITE); transfer-size experiments showing pass/fail points; sysdbg_notes.",
        "hsd_conclusion":  "hw.bug",
    },
    "14027421268": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "QAT authentication job timed out; actor/ring entered unstable state and service loop stopped, with incomplete job dequeues.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Workload logs: job timeout, unstable actor/ring state, director statistics (passed/failed jobs, throughput).",
        "hsd_conclusion":  "env.bug",
    },
    "14027460514": {
        "hsd_component":   "val.env.tool",
        "hsd_root_cause":  "Ticket closed as not a bug: FAILVECT mismatch report (expected vs observed) deemed not a defect.",
        "hsd_fix":         "No fix; rejected as not a defect.",
        "hsd_actual_logs": "FAILVECT output: Arden Ramless Error Registers table with address/expected/observed and rocket/atlas command.",
        "hsd_conclusion":  "not_a_bug",
    },
    "14027589429": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "Not available in ticket: description contains only an NGA link with no failure details.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "No debug data/logs; only NGA test result link.",
        "hsd_conclusion":  "sw.bug",
    },
    "14027589949": {
        "hsd_component":   "val.env.automation",
        "hsd_root_cause":  "PCIe AER advisory non-fatal error reported by ppaercs during QAT setup, causing FW start to abort and device setup failure.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Console logs from qat_internal.c / optsmgr.c: ppaercs advisory non-fatal error, Device reported error before calling legacy start. Aborting, and subsequent device setup/cleanup failures.",
        "hsd_conclusion":  "sw.bug",
    },
    "14027589950": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "Test infrastructure failure: pysces reported no free test card found, leading to accel_verify_job verify failure.",
        "hsd_fix":         "Not specified (environment/resource availability issue).",
        "hsd_actual_logs": "pysces/RTM output: No free test card found; accel_verify_job verification failure; NGA test result link.",
        "hsd_conclusion":  "sw.bug",
    },
    "14027597200": {
        "hsd_component":   "sw.driver",
        "hsd_root_cause":  "Driver/module initialization issue: dsa/iax modules show count of zero and svDeviceInit reports not supporting dsa_iax, resulting in missing SV nodes.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "dmesg: cpm and dsa_iax module messages including init_module: count of zero! and svDeviceInit: not supporting dsa_iax.",
        "hsd_conclusion":  "sw.bug",
    },
    "14027599823": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "EV buffer too small to transfer the book file during CPM P2P test; manual test needed rerun after reconstruction.",
        "hsd_fix":         "Change to use a larger buffer; rerun after reconstruction.",
        "hsd_actual_logs": "No logs included beyond description; NGA test result link present.",
        "hsd_conclusion":  "sw.bug",
    },
    "14027624081": {
        "hsd_component":   "hw.dsa",
        "hsd_root_cause":  "Ticket closed as not a bug: the observed Eventcap_5 default value (0x40F) matches the expected default for GNR; expectation of 0x3FC0F was rejected.",
        "hsd_fix":         "No fix; rejected as not a defect.",
        "hsd_actual_logs": "Register reads: opcap0 and evntcap_5 readbacks (evntcap_5 = 0x0000040f).",
        "hsd_conclusion":  "not_a_bug",
    },
    "15017777226": {
        "hsd_component":   "platform.simics.platform",
        "hsd_root_cause":  "Simics/model issue triggered by enabling OS-native AER (pcie_ports=native) causing DSA/IAA devices to enter HALTED state during idxd init.",
        "hsd_fix":         "Fix delivered in DMR Simics 2025ww28.3.00_46; verified no halt with WW29.3.00_45.",
        "hsd_actual_logs": "dmesg: idxd ... Device is HALTED after reboot; Simics logs with DSA log-level=4, UART logs; validation after fix: no HALT.",
        "hsd_conclusion":  "",
    },
    "15018147145": {
        "hsd_component":   "sw.driver",
        "hsd_root_cause":  "Incorrect firmware selection for IMH2: driver attempting to load IMH1 firmware name/alias, causing init message failure and probe error (-14).",
        "hsd_fix":         "Use correct IMH2 firmware for HW version; overwrite expected FW file with IMH2 FW; BKC/kernel patch for FW naming/selection.",
        "hsd_actual_logs": "dmesg: Failed to send init message, device reset, probe error -14; modinfo output; md5sums of firmware binaries; multiple BKC-version comparisons.",
        "hsd_conclusion":  "",
    },
    "15018552625": {
        "hsd_component":   "val.env.automation",
        "hsd_root_cause":  "EVF Elastic database did not have CPU QDF populated for some DMR AP systems, causing Kayak accelerator library to KeyError on cpu.features.qdf and fail decoding.",
        "hsd_fix":         "Workaround: manually determine QDF (via BMC/PythonSV) and manually set accelerator device counts in content_configuration.yaml; long-term: EVF team records QDF in database.",
        "hsd_actual_logs": "Python traceback: KeyError: qdf in modules_utils.py; list of failing systems; EVF API CPU JSON showing missing qdf/features.",
        "hsd_conclusion":  "",
    },
    "15018702005": {
        "hsd_component":   "val.env.automation",
        "hsd_root_cause":  "IAX opcode 0x42 test: failure messages in log but test case incorrectly reports PASS (result-check logic issue in automation).",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Kayak automation log: ./Setup_Randomize_IAX_Conf.sh -o 0x42; Failure msg in log. Run IDXD workload failed; IAX Opcode 66 test failed Eventhough passing.",
        "hsd_conclusion":  "",
    },
    "15018759390": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "QAT Rate Limiting DECOMP test: cpa_sample_code reports no available crypto/compression instances after configuring devices for decomp; content issue.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "cpa_sample_code output: qaeMemInit started; icp_sal_userStartMultiProcess started; There are no crypto instances; There are no compression instances; No tests were executed.",
        "hsd_conclusion":  "",
    },
    "15018922198": {
        "hsd_component":   "val.env.automation",
        "hsd_root_cause":  "DSA testflow_batch_opcode 0x13 failure: non-success descriptor completion (compl[0]=0x0000000a00000105); script issue identified.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Repro steps, failure signature compl[0]=0x0000000a00000105, log file BKC_WW04_0x13opcode_failure_DSA_testflow_batch_opcode_random_L.log.",
        "hsd_conclusion":  "",
    },
    "16023756164": {
        "hsd_component":   "platform.documentation.other",
        "hsd_root_cause":  "Test content/procedure issue: using wrong/outdated branch of accel-random-config-and-test scripts caused DSA opcode setup failure.",
        "hsd_fix":         "Use latest main branch of accel-random-config-and-test repo.",
        "hsd_actual_logs": "DMR_DSA_opcode_test_fail logs and dmesg; passes after script branch correction.",
        "hsd_conclusion":  "",
    },
    "16023759053": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "Root cause not determinable from retrieved data.",
        "hsd_fix":         "Not determinable.",
        "hsd_actual_logs": "Not determinable.",
        "hsd_conclusion":  "",
    },
    "16024715383": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "Kernel timing/compatibility issue affecting QAT service restart on CentOS kernel 6.9-2.7-4; fixed in kernel 6.9.0-dmr.bkc.6.9.3.6.5.",
        "hsd_fix":         "Use kernel 6.9.0-dmr.bkc.6.9.3.6.5.x86_64 (BKC#06).",
        "hsd_actual_logs": "CentOSQAT_check simics/uart logs; BKC#05 FAIL and BKC#06 PASS logs.",
        "hsd_conclusion":  "",
    },
    "16025676064": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "Root cause not determinable from retrieved data.",
        "hsd_fix":         "Not determinable.",
        "hsd_actual_logs": "Not determinable from retrieved data.",
        "hsd_conclusion":  "",
    },
    "16025723266": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "Intermittent qat.service start failure on CentOS 6.11-1.3.2 kernel; missing SHAC reset during initialization causes failure.",
        "hsd_fix":         "Perform SHAC reset during QAT device initialization. Workaround: reboot and start qat.service immediately after boot.",
        "hsd_actual_logs": "BKC11_ACC_CentOS uart/simics logs; Simics configuration file test_config_Acc_Linux.simics.",
        "hsd_conclusion":  "",
    },
    "16026354661": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "QAT compression instances not found because SHAC needed reset during QAT device initialization.",
        "hsd_fix":         "Perform SHAC reset during QAT device initialization.",
        "hsd_actual_logs": "Console output: No compression instances found; logs: QAT_BKC16_compression_DC and Simics log.",
        "hsd_conclusion":  "",
    },
    "16026995209": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "IAA test failures with compl[0]=0x1e0a/0x0f0a; root cause not determinable from retrieved data.",
        "hsd_fix":         "Not determinable.",
        "hsd_actual_logs": "Numerous iaa_test logs showing compl[0]=0x1e0a / 0x0f0a.",
        "hsd_conclusion":  "",
    },
    "16027275757": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "Simics regression caused kernel warning/call trace when reloading idxd/iaa_crypto modules; not reproduced on older Simics; fixed in later Simics drop.",
        "hsd_fix":         "Update to Simics version where regression is fixed.",
        "hsd_actual_logs": "Kernel call trace and warning logs during modprobe idxd; regression matrix comparing Simics versions; uart/simics logs.",
        "hsd_conclusion":  "",
    },
    "16027417452": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "CentOS Stream 10 environment/library packaging mismatch: accel-config-test/iaa_test binary not compatible/installed, causing non-success completion status (compl[0]=0x16) for opcodes 0x42/0x43.",
        "hsd_fix":         "Install accel-config-test (or use accel-config v4.1.8); passes with 2025WW22 DMR CentOS.",
        "hsd_actual_logs": "Test output logs: compl[0]=0x16 for multiple WQs/opcodes; passes after installing accel-config-test.",
        "hsd_conclusion":  "",
    },
    "16027457977": {
        "hsd_component":   "sw.driver",
        "hsd_root_cause":  "QAT user-space memory initialization failed when hugepages enabled: code created temp file under /dev/hugepages/qat, causing mkstemp failure and subsequent mmap/ring initialization errors.",
        "hsd_fix":         "Remove logic creating temp file under /dev/hugepages/qat; create under /dev/hugepages/ instead.",
        "hsd_actual_logs": "Terminal output: mkstemp failure, mmap failure, ADF_UIO_PROXY errors; terminal + dmesg logs attached.",
        "hsd_conclusion":  "",
    },
    "16027630298": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "QAT stateless compression sample failed under sm_on configuration; root cause not stated in ticket.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Referenced logs: FAIL_QAT_Compression_sm_on_uart and oakstream.simics.log.",
        "hsd_conclusion":  "",
    },
    "16027647768": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "QAT service failed to start after switching from sm_on (SVM/uq setup) to sm_off and rebooting; root cause not stated in ticket.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "systemctl status qat; sysfs qat state/cfg_services checks.",
        "hsd_conclusion":  "",
    },
    "16027891803": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "Content/procedure issue: configuring QAT via sysfs then restarting qat.service resets UACCE/ring_queue_mode settings; correct flow is /etc/sysconfig/qat.",
        "hsd_fix":         "Update test steps to configure via /etc/sysconfig/qat.",
        "hsd_actual_logs": "Console transcript: sysfs configuration (state/cfg_services/uacce/ring_queue_mode); systemctl restart qat results in uacce=off; /etc/sysconfig/qat restart keeps uacce enabled.",
        "hsd_conclusion":  "",
    },
    "16028592669": {
        "hsd_component":   "val.env.automation",
        "hsd_root_cause":  "Windows collateral setup failure: required parent directory not created before downloading PowerShell MSI, causing FileNotFoundError.",
        "hsd_fix":         "Track as NGA/Kayak/DevOps issue; framework should ensure directory creation.",
        "hsd_actual_logs": "NGA/Kayak stack trace: FileNotFoundError for PowerShell MSI path; RuntimeError about collateral download.",
        "hsd_conclusion":  "",
    },
    "16028741807": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "IMH2 Simics hash_sample fails: device configured in wireless mode but hash_sample uses SHA256 (non-wireless algorithm); test requires non-wireless mode.",
        "hsd_fix":         "Configure device for non-wireless mode (setpci -d :4948 0x2cc.l=0x40 or Simics cfg write) and reload driver modules.",
        "hsd_actual_logs": "Logs from BKC#39/#40 showing hash_sample failure (-1); setpci/cfg_space steps; attached debug logs demonstrating fix.",
        "hsd_conclusion":  "",
    },
    "16028742119": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "IMH2 Simics device in wireless mode; DC services require non-wireless configuration (CPM 5.1w feature split); test fails with wireless mode.",
        "hsd_fix":         "Configure device for non-wireless mode; then DC services enable and compression test passes.",
        "hsd_actual_logs": "BKC run logs across multiple versions showing DC enable failures; non-wireless configuration resolves issue.",
        "hsd_conclusion":  "",
    },
    "16029011214": {
        "hsd_component":   "val.env.automation",
        "hsd_root_cause":  "Automation script: SSH/Paramiko timeout while running md5sum on large CentOS image during collateral setup/download flow.",
        "hsd_fix":         "Fixed in automation code (PR referenced).",
        "hsd_actual_logs": "Kayak/Paramiko stack trace: PipeTimeout/TimeoutError during stdout read while executing md5sum.",
        "hsd_conclusion":  "",
    },
    "16029013188": {
        "hsd_component":   "val.env.automation",
        "hsd_root_cause":  "Automation script: BDF fetching/binding logic did not include PCI segment value, causing vfio bind/verify failures for second segment device.",
        "hsd_fix":         "Updated Kayak scripts to include segment in B:D:F (multiple PRs referenced).",
        "hsd_actual_logs": "Kayak automation logs: vfio-pci remove_id/new_id operations, lspci output, echo: write error: No such device, RuntimeError: Fail to load device to vfio-pci driver.",
        "hsd_conclusion":  "",
    },
    "16029018274": {
        "hsd_component":   "val.env.tool",
        "hsd_root_cause":  "dsa_test tool issue: batch size 1 not supported/handled correctly (invalid num descs: 1).",
        "hsd_fix":         "Update dsa_test to check Batch1Support and enforce minimum batch size; workaround in accel-random-config-and-test; verified WW50 DMR CentOS.",
        "hsd_actual_logs": "Setup_Randomize_DSA_Conf.sh invocation logs; per-WQ logs: [error] invalid num descs: 1; batch size 2 passes.",
        "hsd_conclusion":  "",
    },
    "16029052219": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "Incorrect SGL dump and uninitialized/uncleared buffer usage causing failures for opcodes 0x1b/0x1d/0x1e when descriptor count > 1.",
        "hsd_fix":         "Update to dump correct SGL content and memset/initialize buffer (PR idxd-config#11; commit b5e98e1041e5f90798485b92f3dca62be3758cf9).",
        "hsd_actual_logs": "Attached terminal logs; dsa_test commands for multiple opcodes and descriptor counts.",
        "hsd_conclusion":  "",
    },
    "16029066696": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "Missing device ID support in SPDK for new DMR DSA/IAA PCI device IDs, preventing idxd binding to vfio-pci.",
        "hsd_fix":         "Add new DMR DSA/IAA device IDs in SPDK framework.",
        "hsd_actual_logs": "Attached terminal logs; expected vs actual SPDK setup.sh binding output.",
        "hsd_conclusion":  "",
    },
    "16029161498": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "Test was dumping incorrect SGL content and using uninitialized/uncleared buffer, causing opcode 0x1B failures in batch mode.",
        "hsd_fix":         "Update to dump correct SGL content and memset/initialize buffer before use (commit b5e98e1041e5f90798485b92f3dca62be3758cf9).",
        "hsd_actual_logs": "Terminal output: per-WQ log files, completion record status 0x0000000a00000105 for failing descriptors.",
        "hsd_conclusion":  "",
    },
    "16029241563": {
        "hsd_component":   "val.env.automation",
        "hsd_root_cause":  "Script bug: code writes integer to sysfs but treats it as string later; AttributeError: int object has no attribute split during KPT enable verification.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Python traceback: AttributeError in qat_provider_linux_intree.py during modify_kpt_config; NGA test result link.",
        "hsd_conclusion":  "",
    },
    "16029241765": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "Dictionary compression sample failed: required dictionary file missing/unreadable (Cannot open file /lib/firmware/calgary_4kb.dict); content issue.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "dc_dict_sample stdout/stderr: missing file message and qaeMemFree NULL pointer; NGA test result link.",
        "hsd_conclusion":  "",
    },
    "16029241858": {
        "hsd_component":   "val.env.automation",
        "hsd_root_cause":  "QAT SRIOV rate limiting script check failed: QAT PF BDF 0000:0f:00.0 was not present (QAT Device with address does not exist), so SLA capacity parsing failed.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "rl.py cap_rem output: device does not exist; Python exception; NGA test result links.",
        "hsd_conclusion":  "",
    },
    "16029241880": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "socwatch first run failed during QAT power management validation; platform/environment issue impacting data collection.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Assertion traceback showing Socwatch first run failure; NGA test result link.",
        "hsd_conclusion":  "",
    },
    "16029243363": {
        "hsd_component":   "val.env.automation",
        "hsd_root_cause":  "IAA crypto zswap VM test completed but IAA crypto stats showed zero compression/decompression calls, triggering assertion failure; script issue.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Python assertion traceback from test run; NGA test result link.",
        "hsd_conclusion":  "",
    },
    "16029243446": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "DSA mega test run: DSA parameter generation failed (DSA protocol status failed / failed to generate parameter G) causing megaTestAll failure; content issue.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "megaTestAll session output and file/line references; NGA test result link.",
        "hsd_conclusion":  "",
    },
    "16029243535": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "Test precondition not met: test asserts QAT devices must be >2 but system has exactly 2; test fails assertion.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Assertion failure traceback showing device-count check; NGA test result link.",
        "hsd_conclusion":  "",
    },
    "16029253410": {
        "hsd_component":   "val.env.automation",
        "hsd_root_cause":  "In guest VM, QAT device enumeration/count did not match expected, raising ValueError: Please reverify the QAT device count Provided and in VM.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Python traceback from test/qat provider device counting; NGA test result link.",
        "hsd_conclusion":  "",
    },
    "16029254833": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "Compression test failed with Unrecoverable error: stateless overflow when using random data as input corpus; input buffer sizing/random corpus compatibility issue.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "cpa_sample_code output: stateless overflow errors and stack/file references; NGA test result link.",
        "hsd_conclusion":  "",
    },
    "16029255798": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "ccm_sample reports AES-CCM algorithm chaining not supported on Instance and exits non-zero, causing UCS-AEAD integration test failure; content expectation mismatch.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Command output for gcm_sample/ccm_sample including failure text; NGA test result link.",
        "hsd_conclusion":  "",
    },
    "16029268179": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "KPT RSA sample execution: VFIO device open failed (/dev/vfio/45) leading to user proxy initialization failure; content issue.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Console outputs from systemctl/qat steps and kpt_rsa_sample output; logs attached.",
        "hsd_conclusion":  "",
    },
    "16029322007": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "QAT Data Plane API megatest fails when using >8 threads or combined thread masks; passes with single thread/mask; test/content behavior issue.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Megatest output: checkAndUpdateInstMask(): DPInstance(1) In Use by DP/TRAD; megaTestAll_delegate(): validation failed, status: -1; TMS FAILED.",
        "hsd_conclusion":  "",
    },
    "16029389608": {
        "hsd_component":   "val.env.automation",
        "hsd_root_cause":  "DSA legacy opcode 0x13 (DIF insert) test reports page-fault/unsuccessful completions under block-on-fault disabled; script/test issue.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "dsa_test run output: per-WQ completion record debug lines with non-success status, compl[0]=0x0000000000060083/0x0000100000060083.",
        "hsd_conclusion":  "",
    },
    "16029489884": {
        "hsd_component":   "val.env.automation",
        "hsd_root_cause":  "Package dependency/version conflict while installing libguestfs on CentOS (libguestfs-man-pages-uk requires specific version; conflicts with repos).",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "yum output showing dependency/conflict details; NGA test result links.",
        "hsd_conclusion":  "",
    },
    "16029529765": {
        "hsd_component":   "val.env.automation",
        "hsd_root_cause":  "virt-customize/libguestfs fails: SELinux security driver model not available when running as root under qemu:qemu.",
        "hsd_fix":         "Workaround: set LIBGUESTFS_BACKEND=direct, or avoid running as root, or adjust permissions/parent directories for qemu user.",
        "hsd_actual_logs": "virt-customize stderr: unsupported configuration: Security driver model selinux is not available; Python stack trace from automation framework.",
        "hsd_conclusion":  "",
    },
    "16029579061": {
        "hsd_component":   "val.env.automation",
        "hsd_root_cause":  "Script issue in VM DMA test: not all threads completed successfully after second reset cycle (304/320 passed).",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "dmatest output: per-channel summaries, Threads Passed: 304 / Total Threads: 320; NGA result link.",
        "hsd_conclusion":  "",
    },
    "16029735044": {
        "hsd_component":   "val.env.automation",
        "hsd_root_cause":  "Automation script fails: git checkout of specified SPDK commit fails during collateral download (GitError while cloning/checking out).",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Automation log: clone, checkout branch, checkout commit SHA, stack trace ending at git checkout failure.",
        "hsd_conclusion":  "",
    },
    "16029796902": {
        "hsd_component":   "sw.driver",
        "hsd_root_cause":  "SR-IOV mode support missing in QAT driver version used; Windows Device Manager shows yellow bang. Fixed in driver version 5.1.0-00093.",
        "hsd_fix":         "Support enabled in driver version 5.1.0-00093.",
        "hsd_actual_logs": "Windows Device Manager yellow bang observation.",
        "hsd_conclusion":  "",
    },
    "16029819724": {
        "hsd_component":   "val.env.automation",
        "hsd_root_cause":  "Automation script missing required VC check steps in QAT status check test.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "NGA test result link only; no raw log content.",
        "hsd_conclusion":  "",
    },
    "16029836258": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "Unclear requirements/criteria: rate-limiting throughput expectation not clearly defined; QAT VM throughput did not meet criteria on ESXi 3-VM setup.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Throughput measurements and test setup steps (ESXi, 3 VMs, QAT driver/params, cpa_sample_code runs).",
        "hsd_conclusion":  "",
    },
    "16029922465": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "Design/requirements change: VC/TC mapping in QAT driver 6.18 is correct per CPM5.1 SWAS POR; 6.14 behavior was incorrect and fixed via upstreamed QAT driver change.",
        "hsd_fix":         "TC/VC configuration updated to match SWAS POR; test case updated to expect VC0=0x7F and VC1=0x80.",
        "hsd_actual_logs": "PCIe VC capability dump via lspci -vvv showing TC/VC=7f (VC0) and TC/VC=80 (VC1); regression matrix 6.14 PASS vs 6.18 FAIL.",
        "hsd_conclusion":  "",
    },
    "16030007209": {
        "hsd_component":   "val.env.automation",
        "hsd_root_cause":  "Windows QAT automation fails while installing PowerShell 7 v7.6.0-rc.1; script concludes installed version does not match/verify correctly.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Python automation log: RuntimeError: Not install PowerShell7 with version v7.6.0-rc.1 correctly.",
        "hsd_conclusion":  "",
    },
    "16030078778": {
        "hsd_component":   "val.env.automation",
        "hsd_root_cause":  "Automation script issue: SSH connection timed out on 2S systems because the script did not wait long enough for SUT to come up (system reachable 4-5 minutes later).",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Kayak/paramiko SSH logs: connection attempts and TimeoutError (WinError 10060); log files referenced.",
        "hsd_conclusion":  "",
    },
    "16030097390": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "Known PCIe AER stability issue on device 0000:01:00.0 causing CentOS accelerator script failures; tracked as environmental issue.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "NGA links for QAT hash test and QAT status check; no raw logs beyond references.",
        "hsd_conclusion":  "",
    },
    "18043352398": {
        "hsd_component":   "fw.cpm",
        "hsd_root_cause":  "Memory corruption when using multiple flat buffers per SGL in compression+encryption chaining test (Zstd + AES-CTR).",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "Request/response captured in log referenced by resource 18043352399.",
        "hsd_conclusion":  "",
    },
    "18043412175": {
        "hsd_component":   "fw.cpm",
        "hsd_root_cause":  "QAT firmware used incorrect hardcoded SB Port ID for DRNG communication; firmware always read 0 from DRNG causing non-unique results / ECDSA collisions.",
        "hsd_fix":         "Change hardcoded Port ID value in CPM firmware.",
        "hsd_actual_logs": "FW observation: DRNG read returned 0; application error logs in description.",
        "hsd_conclusion":  "",
    },
    "18043800050": {
        "hsd_component":   "fw.ocode",
        "hsd_root_cause":  "Telemetry aggregator structure offset/address question; concluded not a bug.",
        "hsd_fix":         "Not provided.",
        "hsd_actual_logs": "MMIO/BAR addresses and offsets for telemetry aggregator structure.",
        "hsd_conclusion":  "not_a_bug",
    },
    "22019670393": {
        "hsd_component":   "platform.simics.platform",
        "hsd_root_cause":  "Simics PASID capability support parameter was disabled for the DMR platform, causing translation requests to use the wrong PASID value and leading to IOMMU faults / bad DMA translations during IAA opcode tests.",
        "hsd_fix":         "Simics fix: re-enable/correct the parameter defining PASID capability support so translations use the correct PASID value.",
        "hsd_actual_logs": "Simics log excerpts showing IOMMU \"PML4E ... not presented\" and IAA read/write errors; iaa_test output showing \"memory result verify failed\"; dmesg DMAR faults with \"Present bit ... is clear\" and PASID table/root/context entry dumps.",
        "hsd_conclusion":  None,
    },
    "22019958183": {
        "hsd_component":   "sw.env",
        "hsd_root_cause":  "Simics/ACC tooling (AcreError): Could not determine the pciexbar/mmcfg_rule with a DMR craff image and Simics Silver 2024ww16.3.11_40. Root cause not further specified in retrieved fields.",
        "hsd_fix":         "Not specified.",
        "hsd_actual_logs": "Error text in description: \"Exception (AcreError): Could not determine the pciexbar/mmcfg_rule.\"",
        "hsd_conclusion":  "sw.bug",
    },
    "22020262458": {
        "hsd_component":   "platform.simics.platform",
        "hsd_root_cause":  "Known Simics QAT in-tree driver test failures requiring multiple workarounds; underlying issue addressed by updated driver support in newer in-tree driver version (0.8.2).",
        "hsd_fix":         "Use QAT in-tree driver 0.8.2 (included in a later BKC kernel); earlier workarounds: load single-signed ROM, BME workaround via UEFI mm writes, apply kernel timing patch, rebuild QAT driver with DC service flags.",
        "hsd_actual_logs": "Workaround procedure and references captured in ticket description.",
        "hsd_conclusion":  None,
    },
    "22020262749": {
        "hsd_component":   None,
        "hsd_root_cause":  "IDXD driver in the CentOS BKC did not include support for the newer DSA/IAA device IDs (DIDs) introduced in later DMR Simics VP releases, so the driver failed to enumerate the devices.",
        "hsd_fix":         "Patch the IDXD driver to add support for the new DIDs; confirmed resolved in a later DMR BKC kernel release where idxd binds to the new devices.",
        "hsd_actual_logs": "lspci showing devices with DID 1212/1216; observation that /sys/bus/dsa/devices was empty; later confirmation logs with uname -r and lspci -k showing \"Kernel driver in use: idxd\" for DID 1216.",
        "hsd_conclusion":  None,
    },
    "22020498859": {
        "hsd_component":   None,
        "hsd_root_cause":  "Kernel/IOMMU handling bug when IOMMU reports a device fault for a bad IOPF setup (present bit clear in first-level paging entry), leading to warnings and device becoming unusable.",
        "hsd_fix":         "Kernel fix: \"iommu: Handle iommu faults for a bad iopf setup\" (fixed in 6.11.x).",
        "hsd_actual_logs": "dmesg call traces and DMAR fault dumps while running DSA DIF insert opcode 0x13 with BOF enabled; comparison that issue not observed on kernel 6.11.x; command outputs from dsa_test runs.",
        "hsd_conclusion":  "Resolved by kernel change; no longer reproducible on updated kernel.",
    },
    "22020708911": {
        "hsd_component":   None,
        "hsd_root_cause":  "Feature request / enablement gap: dsa_test initially supported only a subset of DSA3 opcodes; additional opcode tests and kernel regressions (SGL-related) needed to be addressed for full validation coverage.",
        "hsd_fix":         "Opcode test support added/merged into internal branches; kernel-side regression fixes for gather ops were prepared/merged upstream and submitted to BKC; opcodes 0x18-0x1C pass with identified steps.",
        "hsd_actual_logs": "dsa_test verbose logs showing failures for gather ops with completion status 0x14 and debug prints about SGL format/size.",
        "hsd_conclusion":  None,
    },
    "22020720289": {
        "hsd_component":   None,
        "hsd_root_cause":  "Perf monitoring implementation issue (Simics/firmware side): DSA3 Operations2 counters were exposed/overlapped via Category 3, causing multiple operations to be counted in the same counter instead of using Category 5 as intended.",
        "hsd_fix":         "Workaround and later Simics fix to use/verify the correct category/register behavior; additional workaround added for event_category=0x5.",
        "hsd_actual_logs": "perf stat command outputs for dsa_test runs showing counts on event=0x800 with event_category=0x3 (and later verification with event_category=0x5).",
        "hsd_conclusion":  None,
    },
    "22021253702": {
        "hsd_component":   None,
        "hsd_root_cause":  "Feature request: accel-config-test package was omitted from the CentOS Stream 10 BKC artifacts during CS9->CS10 migration even though base repos did not provide accel-config-test.",
        "hsd_fix":         "BKC maintainer planned to re-add/provide accel-config-test in a subsequent weekly release and later update to an internal stable branch for DSA3 support.",
        "hsd_actual_logs": "Terminal output showing `dnf install accel-config-test` failing with \"No match for argument: accel-config-test\"; uname -r shown for the affected kernel.",
        "hsd_conclusion":  None,
    },
    "22021391206": {
        "hsd_component":   "val.env.simics",
        "hsd_root_cause":  "Unknown from retrieved fields. Ticket text indicates initial false failure from incorrect expected values, and then potential incorrect observed results for floating-point gather-reduce in simulation.",
        "hsd_fix":         "Not provided in retrieved fields.",
        "hsd_actual_logs": "Not provided in retrieved fields.",
        "hsd_conclusion":  "hw.bug",
    },
    "22021545516": {
        "hsd_component":   None,
        "hsd_root_cause":  "QAT power management / reset sequencing issue causing FW authentication failures (FCU_STATUS=0x03) on A0 PO; requires allowing SSM reset to complete before FW authentication.",
        "hsd_fix":         "Add delay to allow SSM reset completion before FW authentication. Workaround: use unsigned driver + unsigned FW; modified driver clearing SSM_PM_ENABLE during init used as mitigation; later fix released in DMR Power-On release notes.",
        "hsd_actual_logs": "dmesg excerpts showing QAT authentication error (FCU_STATUS=0x3) and device resets; ESXi logs (fw load failing); reproduction steps including unload/reload of QAT drivers.",
        "hsd_conclusion":  "Workaround/driver change available; issue resolved in later release ingredients.",
    },
    "22021545692": {
        "hsd_component":   None,
        "hsd_root_cause":  "QAT power management / reset sequencing behavior affecting compression path (device hang/unresponsive) on A0 PO; need delay to allow SSM reset completion before FW authentication, with PM behavior implicated.",
        "hsd_fix":         "Workarounds: disabling PM fuses (set enable_pm=0); driver workaround: write SSM_PM_ENABLE CSR = 0 after FLR/before FW auth; later fix released in DMR Power-On release notes; verified good with WW47 ingredients.",
        "hsd_actual_logs": "Unsigned QAT driver SSH/console logs; sc system log showing hang; request dump with one compression request; logs with cryptomgr.notests; multiple experiment notes.",
        "hsd_conclusion":  "Workaround/driver change used to unblock; later release ingredients verified.",
    },
    "22021545728": {
        "hsd_component":   None,
        "hsd_root_cause":  "QAT power management flow issue causing RSA key generation errors on A0 when running sample code; tied to QAT PM sub-IP behavior.",
        "hsd_fix":         "Delay allowing SSM reset to complete before FW authentication; modified driver clearing ssm_pm_enable; disabling PM fuse(s) and/or using signed FW avoided issue; later fix released and verified.",
        "hsd_actual_logs": "Console logs including dmesg; unsigned driver logs after reboot; reproduction on two unfused systems; workload run details and later verification details.",
        "hsd_conclusion":  "Resolved/verified with newer software ingredients; PM-related mitigation/fix applied.",
    },
    "22021545870": {
        "hsd_component":   None,
        "hsd_root_cause":  "Driver/content issue: enabling 3 QAT services triggered kernel crypto self-tests (LKCF/cryptomgr_test) that led to a general protection fault/panic in the intel_qat path; did not occur when self-tests were disabled.",
        "hsd_fix":         "Fix aligned with later BKC drops; interim workaround: avoid configuring 3 services on one device (split across devices) or disable driver self-tests.",
        "hsd_actual_logs": "Kernel panic trace in description (RIP in qat_alg_callback), plus references to serial logs, dmesg, ssh logs.",
        "hsd_conclusion":  None,
    },
    "22021548093": {
        "hsd_component":   "val.env.tool",
        "hsd_root_cause":  "Verification-phase logic flagging a valid scenario as failure in some inter-domain compare tests.",
        "hsd_fix":         "CCS fix to verification phase for inter-domain compare tests.",
        "hsd_actual_logs": "Manual debug; description of mismatch after ~9m58s.",
        "hsd_conclusion":  "env.bug",
    },
    "22021548133": {
        "hsd_component":   "hw.cpm",
        "hsd_root_cause":  "Spec ambiguity: expectation that PRS status flags clear when PRS transitions to enabled; behavior deemed ambiguous; no HW implementation change required.",
        "hsd_fix":         "Documentation clarification recommended; cloned to another bug for tracking doc/spec update; no HW change.",
        "hsd_actual_logs": "Not specified.",
        "hsd_conclusion":  "doc",
    },
    "22021595403": {
        "hsd_component":   "val.env.tool",
        "hsd_root_cause":  "Result-field mismatch issue and misalignment issue in configs for inter-domain tests.",
        "hsd_fix":         "Update configs to fix misalignment; result-field mismatch scenario addressed.",
        "hsd_actual_logs": "Manual debug.",
        "hsd_conclusion":  "env.bug",
    },
    "22021595447": {
        "hsd_component":   "val.env.tool",
        "hsd_root_cause":  "Inter-domain fill transfer_size miswritten in descriptor memory (LS digit dropped).",
        "hsd_fix":         "CCS fix for inter-domain fill transfer-size miswrite.",
        "hsd_actual_logs": "Manual debug; descriptor/transfer_size observation examples included in description.",
        "hsd_conclusion":  "env.bug",
    },
    "22021653767": {
        "hsd_component":   "sw.driver",
        "hsd_root_cause":  "Windows QAT driver initialization failed: missing/invalid configuration data (failure to get Bank0CoreAffinity) causing SAL service init failure and driver D0Entry failure.",
        "hsd_fix":         "Driver fix verified in engineering build QAT5.1.W.5.1.0-00086; integrated in BKC with QAT5.1.W.5.1.0-00093.",
        "hsd_actual_logs": "TraceView logs: SalCtr_InstInit / SalCtrl_ServiceInit / adf_dev_init_locked failures; AdfEvtDeviceD0Entry failures.",
        "hsd_conclusion":  "",
    },
    "22021717860": {
        "hsd_component":   "hw.cpm",
        "hsd_root_cause":  "DVP IP integration strap for minimum wait time parameter is set too short in CPM integration, forcing use of command throttling normally only needed for step-down clock crossings; leads to VRC controller timeout in SHIFT_READ.",
        "hsd_fix":         "Post-silicon workaround: use worst-case VRC_SPEED and known workable VRC_READ_SPEED; rejected for DMR; cloned to Coral for fix.",
        "hsd_actual_logs": "Post-silicon experiments across vrc_speed/vrc_read_speed combinations and observed TIMEOUT/OK matrix; waveform-based failure mechanism described.",
        "hsd_conclusion":  "hw.bug",
    },
    "22021721831": {
        "hsd_component":   "hw.big_core",
        "hsd_root_cause":  "No root cause determined (ticket rejected as cannot reproduce).",
        "hsd_fix":         "None (cannot reproduce).",
        "hsd_actual_logs": "MCA dump showing multiple machine check banks (IFU/DCU/DTLB/MLC) with detailed MC_STATUS/ADDR/MISC output.",
        "hsd_conclusion":  "no_root_cause.rejected",
    },
    "22021814162": {
        "hsd_component":   None,
        "hsd_root_cause":  "Test/tool timeout issue (umwait timeout / memcpy desc timeout) when running largest transfer size; longer runtime on low core-count CPUs required increased timeout.",
        "hsd_fix":         "Increase default timeout (use -t 300000); scripts updated to default timeout 300000.",
        "hsd_actual_logs": "Logs showing umwait timeout and memcpy descriptor timeout; retest results showing pass with timeout=300000.",
        "hsd_conclusion":  "Closed as fixed via test change (timeout increase).",
    },
    "22021889147": {
        "hsd_component":   "board.test_card",
        "hsd_root_cause":  "LCD test card aborts transactions when there is a PASID prefix; when ATS is enabled the platform does not send a PASID prefix. LCD FW needs EXTTLMSKREG0.DATFU set to disable AT field check on the card.",
        "hsd_fix":         "Mitigation/workaround: remove Arden targets for DSA memory-move operation; FW change required on LCD card to set EXTTLMSKREG0.DATFU.",
        "hsd_actual_logs": "Manual debug; observation that removing Arden targets allows test to run for 10 minutes.",
        "hsd_conclusion":  "board.bug",
    },
    "22021896735": {
        "hsd_component":   "hw.punit",
        "hsd_root_cause":  "No root cause determined (ticket rejected as cannot reproduce).",
        "hsd_fix":         "None (cannot reproduce).",
        "hsd_actual_logs": "No debug tools/logs specified in retrieved fields.",
        "hsd_conclusion":  "no_root_cause.rejected",
    },
    "22021897495": {
        "hsd_component":   None,
        "hsd_root_cause":  "Automation/script update needed to enable BIOS knob for Performance Isolation Mode in test automation.",
        "hsd_fix":         "Update automation/test case to enable Performance Isolation Mode from BIOS setup (PR referenced in comments).",
        "hsd_actual_logs": "Manual runs of ./dsa_test_numactl.sh showing an error with knob enabled/disabled.",
        "hsd_conclusion":  "Test updated; failure expected on 1-socket X1, should pass on 2-socket X1.",
    },
    "22021911928": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "Test reports DSA SWERROR err_code=0x10 (unsupported operation code) for REDUCE_WITH_DUALCAST with integer data, with completion record showing \"Unknown operation status code\" and verify mismatches.",
        "hsd_fix":         "Not specified in the ticket.",
        "hsd_actual_logs": "SWERROR register dump, completion record dump, raw descriptor dump, DSA target info table, mismatch details.",
        "hsd_conclusion":  None,
    },
    "22021935474": {
        "hsd_component":   "val.env.tool",
        "hsd_root_cause":  "Descriptor_all test reports SWERROR valid=0, \"unknown operation status code\", plus analytics data mismatches.",
        "hsd_fix":         "Not specified in the ticket.",
        "hsd_actual_logs": "NGA testlines and full NGA testResult logs referenced in the description.",
        "hsd_conclusion":  None,
    },
    "22021935491": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "IAA steering tags test fails with completion record status 0x11 \"Invalid flags\"; deflate verification notes a failed compression with invalid flags=0x8000.",
        "hsd_fix":         "Not specified in the ticket.",
        "hsd_actual_logs": "Completion record status messages and deflate_verify output.",
        "hsd_conclusion":  "no_root_cause.wont_do",
    },
    "22021935524": {
        "hsd_component":   "hw.virtualization",
        "hsd_root_cause":  "IAA test reports SWERROR err_code=0x22 indicating an address translation error during ATS/PRS handling (e.g., UR/CA/CTO on ATS translation request or PRS response failure).",
        "hsd_fix":         "Test initiates FLR when gensts indicates FLR needed; no other fix/workaround specified.",
        "hsd_actual_logs": "Completion record failure messages, SWERROR register dump, gensts/FLR sequence logs.",
        "hsd_conclusion":  None,
    },
    "22021971451": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "Moka failure observed in post-test with CPM; ticket was later marked cannot reproduce.",
        "hsd_fix":         "Not specified in the ticket.",
        "hsd_actual_logs": "NGA testResult links and the failing command line (pysces).",
        "hsd_conclusion":  "no_root_cause.cannot_reproduce",
    },
    "22021972507": {
        "hsd_component":   "sw.application",
        "hsd_root_cause":  "Feature/support request to enable CXL-IO targets for Rocket accelerator coverage (not a failure root cause).",
        "hsd_fix":         "Enable/support CXL-IO targets in Rocket for DSA/IAA flows.",
        "hsd_actual_logs": "Command lines/expected targets included in description (no debug logs).",
        "hsd_conclusion":  None,
    },
    "22021973248": {
        "hsd_component":   "val.env.automation",
        "hsd_root_cause":  "Unexpected reboot of the target station during the silicon_dsa_all_types_ims step.",
        "hsd_fix":         "Not specified in the ticket.",
        "hsd_actual_logs": "Rocket command line and NGA testResult link; failure state \"UnexpectedReboot\".",
        "hsd_conclusion":  None,
    },
    "22021975263": {
        "hsd_component":   "val.env.automation",
        "hsd_root_cause":  "Test timed out on station an004022bms2293.",
        "hsd_fix":         "Not specified in the ticket.",
        "hsd_actual_logs": "Rocket command line and NGA failure-management link.",
        "hsd_conclusion":  None,
    },
    "22021993817": {
        "hsd_component":   "sw.application",
        "hsd_root_cause":  "SVOS/VTD run fails because shared memory creation/connection fails (\"No such file or directory\"), leading to TMAN failing to connect/init semaphores for targets.",
        "hsd_fix":         "Not specified in the ticket.",
        "hsd_actual_logs": "Console log excerpt showing shared memory/TMAN errors.",
        "hsd_conclusion":  "no_root_cause.filed_by_mistake",
    },
    "22022043076": {
        "hsd_component":   None,
        "hsd_root_cause":  "DSA_WQ_OPCFG test failed after ~105 minutes runtime; failure signature not clear; cannot reproduce.",
        "hsd_fix":         "Replicate manually to capture clearer failure signature.",
        "hsd_actual_logs": "NGA failure-management link and Rocket command line.",
        "hsd_conclusion":  "no_root_cause.cannot_reproduce",
    },
    "22022043611": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "Test failure because a DSA \"drain\" operation was executed inside a batch, which is not allowed.",
        "hsd_fix":         "Modify the variant so drain executes outside of the batch.",
        "hsd_actual_logs": "NGA failure-management link and Rocket command line.",
        "hsd_conclusion":  None,
    },
    "22022044164": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "DSA test reports completion record status error \"0x0 (Unknown operation status code)\" during mem move / overlapping buffers / PRS scenarios.",
        "hsd_fix":         "Not specified in the ticket.",
        "hsd_actual_logs": "NGA testResult link and Rocket command line.",
        "hsd_conclusion":  None,
    },
    "22022044340": {
        "hsd_component":   "val.env.test",
        "hsd_root_cause":  "Test failure due to timeout.",
        "hsd_fix":         "Update/increase timeout settings.",
        "hsd_actual_logs": "Brief description provided; no specific logs detailed.",
        "hsd_conclusion":  None,
    },
    "22022089619": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "CXL-IO targets show data mismatches when used as DSA/IAA source/destination (errors reported from \"Arden Ramless Error Registers\" during MemWr).",
        "hsd_fix":         "Not specified in the ticket.",
        "hsd_actual_logs": "Failure vectors with expected/observed data from Arden Ramless Error Registers for DSA and IAA cases; failing logs on attachments.",
        "hsd_conclusion":  None,
    },
    "22022090434": {
        "hsd_component":   "val.env.configuration",
        "hsd_root_cause":  "Hardware hang/deadlock: HAMVF was waiting on snoop responses from caching agents (CBB Cbo or IMH SCA), leading to Cbo timeouts and stalled memory responses; dependency chain suggests a deadlock involving HAMVF, SCA, and Cbo.",
        "hsd_fix":         None,
        "hsd_actual_logs": "AXON summary/report data including HAMVF analyzer, SCA analyzer (stuck tracker entries), Timeout analyzer (CBO timeouts), Error analyzer (MLC 3-strike errors / Cbo timeouts correlation), and UBR analyzer recommendations.",
        "hsd_conclusion":  "env.bug",
    },
    "22022090533": {
        "hsd_component":   "val.env.content",
        "hsd_root_cause":  "Test failure due to PCIe protocol error reported by pcieTC_global_checkProtocolErrors (PCIETC_PROTOCOL_ERROR) during DSA/IAA + supercollider IDI/Lock stress on FDU3.",
        "hsd_fix":         None,
        "hsd_actual_logs": "Failure signature log showing errorCheckPciLibAgent(card1) and PCIETC_PROTOCOL_ERROR.",
        "hsd_conclusion":  "env.bug",
    },
    "22022165024": {
        "hsd_component":   "val.env.tool",
        "hsd_root_cause":  "SWERROR verification mismatch reported by the test tooling (SWERROR fields/WQ index did not match expected); dispositioned as not a bug.",
        "hsd_fix":         None,
        "hsd_actual_logs": "Tool output including SWERROR register dump (err_code 0x1b, wq_index 0xe, operation 0x52, etc.) and verification messages.",
        "hsd_conclusion":  "not_a_bug",
    },
    "22022165090": {
        "hsd_component":   "val.env.test",
        "hsd_root_cause":  "Test environment scripting failure: Python AttributeError (\"NoneType\" object has no attribute \"count\") in cfgfile.py tbl_operate called from iax_focus_tests.py during M2P flow.",
        "hsd_fix":         None,
        "hsd_actual_logs": "Python backtrace from acre.py through acrelib.py and iax_focus_tests.py to cfgfile.py tbl_operate.",
        "hsd_conclusion":  "env.bug",
    },
    "22022165209": {
        "hsd_component":   "hw.scf",
        "hsd_root_cause":  "No root cause determined (ticket rejected). MCE while running IAX_Lock_Stress_Supercollider.",
        "hsd_fix":         None,
        "hsd_actual_logs": "NGA failure reference and Axon record-viewer link; no debug-tools field populated.",
        "hsd_conclusion":  "no_root_cause.rejected",
    },
    "22022165213": {
        "hsd_component":   "hw.scf",
        "hsd_root_cause":  "MCE observed while running IAX_Lock_Stress_Supercollider; no additional root-cause details provided.",
        "hsd_fix":         None,
        "hsd_actual_logs": "NGA failure reference and Axon record-viewer link; no debug-tools field populated.",
        "hsd_conclusion":  "env.bug",
    },
    "22022199057": {
        "hsd_component":   "hw.dsa",
        "hsd_root_cause":  "RTL error-handling gap in DSA: gather copy (0x1C) does not detect transfer size > WQ max-transfer-size and incorrectly completes successfully instead of returning invalid transfer size (0x13).",
        "hsd_fix":         "No fix delivered for DMR: issue rejected for DMR and tagged for errata review; software workaround under discussion.",
        "hsd_actual_logs": "Full repro procedure and dsa_test_v2 verbose output showing WQ configured with max transfer size = 1, descriptor submission, and completion record reporting success; WQCFG confirmation snippet.",
        "hsd_conclusion":  "hw.bug",
    },
    "22022204843": {
        "hsd_component":   "val.env.tool",
        "hsd_root_cause":  "Environment bug during rocket setup/rtm flow: scatter_gather plugin not supported yet, with subsequent failures/segfault (signal 11).",
        "hsd_fix":         "Not specified.",
        "hsd_actual_logs": "Large rocket/rtm setup log excerpt plus dsarand report showing \"scatter_gather not supported yet\" messages and early exit/segfault (signal 11).",
        "hsd_conclusion":  "env.bug",
    },
    "22022204908": {
        "hsd_component":   "val.env.tool",
        "hsd_root_cause":  "Cannot reproduce. scatter_gather plugin not supported yet; TMAN unable to allocate/add targets during initialization.",
        "hsd_fix":         "Not specified.",
        "hsd_actual_logs": "Console/log snippet showing \"scatter_gather not supported yet\", followed by TMAN/target selector initialization errors.",
        "hsd_conclusion":  "no_root_cause.rejected",
    },
    "22022205087": {
        "hsd_component":   "val.env.tool",
        "hsd_root_cause":  "UBR credit loss / TOR timeout style error; root cause not further specified. Ticket conclusion indicates environment bug classification.",
        "hsd_fix":         "Not specified.",
        "hsd_actual_logs": "Links in description to an Axon log record and a test result page.",
        "hsd_conclusion":  "env.bug",
    },
}
# ─────────────────────────────────────────────────────────────────────────────


def load_responses(path: Path) -> list[dict]:
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records


def save_responses(path: Path, records: list[dict]):
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".jsonl", dir=path.parent)
    os.close(tmp_fd)
    with open(tmp_path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    shutil.move(tmp_path, path)


def needs_phase0(record: dict) -> bool:
    """Return True if this record needs Phase 0 HSD MCP enrichment."""
    p0 = record.get("phase0_hsd", {})
    if not p0:
        return True
    # Missing key fields
    if not p0.get("hsd_root_cause", "").strip():
        return True
    return False


def cmd_identify(run_dir: Path):
    resp_path = run_dir / "responses.jsonl"
    if not resp_path.exists():
        print(f"ERROR: {resp_path} not found")
        sys.exit(1)

    records = load_responses(resp_path)
    gaps = [(r.get("hsd_id") or r.get("parsed", {}).get("hsd_id", ""), r) for r in records if needs_phase0(r)]

    print(f"Total records:       {len(records)}")
    print(f"Need phase0_hsd:     {len(gaps)}")
    print()

    if not gaps:
        print("✅ All records already have phase0_hsd data.")
        return

    print("HSDs requiring Phase 0 HSD MCP enrichment:")
    print("─" * 60)
    for hsd_id, rec in gaps:
        parsed = rec.get("parsed", {})
        component = parsed.get("component", "(blank)")
        arc = parsed.get("actual_root_cause", "")[:80] or "(empty)"
        print(f"  {hsd_id}  component={component!r}  actual_root_cause={arc!r}")
    print()
    print("─" * 60)
    print()
    print("Agent instructions:")
    print("For each HSD ID above, call Co-Design HSD MCP:")
    print()
    print('  codesign-ask-hsd-agent: "Get details for HSD <id>. Return:')
    print("    hsd_component, hsd_root_cause, hsd_fix, hsd_actual_logs,")
    print('    hsd_status, hsd_conclusion as structured JSON."')
    print()
    print("Then populate PHASE0_RESULTS in this script and run:")
    print("  python patch_fields.py --run-dir <run_dir> --apply")


def cmd_apply(run_dir: Path):
    resp_path = run_dir / "responses.jsonl"
    if not resp_path.exists():
        print(f"ERROR: {resp_path} not found")
        sys.exit(1)

    if not PHASE0_RESULTS:
        print("ERROR: PHASE0_RESULTS is empty. Populate it first (run --identify to get the list).")
        sys.exit(1)

    records = load_responses(resp_path)
    patched = 0
    skipped = 0

    for rec in records:
        hsd_id = rec.get("hsd_id") or rec.get("parsed", {}).get("hsd_id", "")
        if hsd_id in PHASE0_RESULTS:
            rec["phase0_hsd"] = PHASE0_RESULTS[hsd_id]
            patched += 1
        else:
            skipped += 1

    save_responses(resp_path, records)
    print(f"Patched:   {patched}")
    print(f"Unchanged: {skipped}")
    print(f"Saved:     {resp_path}")


def cmd_finalize(run_dir: Path):
    resp_path = run_dir / "responses.jsonl"
    csv_path = run_dir / "triage_results.csv"

    print("Re-running finalize...")
    r = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "parse_and_triage.py"),
         "--mode", "finalize",
         "--responses", str(resp_path),
         "--output-dir", str(run_dir)],
        cwd=str(SCRIPT_DIR)
    )
    if r.returncode != 0:
        print("ERROR: finalize failed")
        sys.exit(1)

    print("\nRe-running report...")
    r = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "parse_and_triage.py"),
         "--mode", "report",
         "--input", str(csv_path),
         "--output-dir", str(run_dir)],
        cwd=str(SCRIPT_DIR)
    )
    if r.returncode != 0:
        print("ERROR: report failed")
        sys.exit(1)

    # Quick emptiness check on key fields
    print("\nField fill rates after patch:")
    check_cols = ["component", "actual_root_cause", "actual_logs_collected",
                  "verified_root_cause", "beyond_sme_recommendations"]
    with open(csv_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    total = len(rows)
    for col in check_cols:
        filled = sum(1 for r in rows if r.get(col, "").strip())
        pct = filled / total * 100
        flag = " ✅" if pct >= 90 else " ⚠️  below 90%"
        print(f"  {col:<40} {filled}/{total} ({pct:.1f}%){flag}")


def _resolve_run_dir(arg: str | None) -> Path:
    if arg:
        p = Path(arg)
        if not p.is_absolute():
            p = SCRIPT_DIR / p
        return p
    # Auto-detect latest
    runs = sorted((SCRIPT_DIR / "output").glob("run_*"), key=lambda d: d.name, reverse=True)
    if not runs:
        print("ERROR: No run_* folders found under output/")
        sys.exit(1)
    return runs[0]


def main():
    parser = argparse.ArgumentParser(description="Patch phase0_hsd fields in an existing triage run.")
    parser.add_argument("--run-dir", help="Run folder path (default: latest output/run_*)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--identify", action="store_true", help="List HSDs needing Phase 0 enrichment")
    group.add_argument("--apply", action="store_true", help="Apply PHASE0_RESULTS to responses.jsonl")
    group.add_argument("--finalize", action="store_true", help="Re-run finalize + report after patching")
    group.add_argument("--all", action="store_true", help="Apply then finalize in one step")
    args = parser.parse_args()

    run_dir = _resolve_run_dir(args.run_dir)
    print(f"Run dir: {run_dir}\n")

    if args.identify:
        cmd_identify(run_dir)
    elif args.apply:
        cmd_apply(run_dir)
    elif args.finalize:
        cmd_finalize(run_dir)
    elif args.all:
        cmd_apply(run_dir)
        cmd_finalize(run_dir)


if __name__ == "__main__":
    main()
