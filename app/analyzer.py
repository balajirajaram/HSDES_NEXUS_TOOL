"""Orchestrates the self-learning triage loop — DOMAIN-AGNOSTIC.

Works for ANY Intel server-platform HSD (silicon RAS/UPI/MCA, memory, PCIe/CXL,
power / S-states, BIOS/IFWI/BMC/boot, OS/driver, manageability, etc.) — it is
NOT tied to any single unit or domain.

Flow (runs on every request):
  Step 0 RECALL      -> KB search + confidence
  Step 1 DECIDE      -> High = KB-first; else source fallback
  Step 2 INVESTIGATE -> read target HSD (fully) + similar HSDs
  Step 3 WRITE-BACK  -> upsert KB entry (confirmed vs hypothesis)
  Step 4 REPORT      -> A-H markdown report

Reads via the configured reader (MCP reader if enabled, else HSDES REST). Uses
the LLM when configured; otherwise a deterministic OFFLINE report. Never
fabricates HSD IDs, register names, or commands.
"""

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from .config import config
from .hsdes_client import HSDESClient
from .kb_store import KBStore, normalize_terms
from .llm_client import llm
from .log_analyzer import analyze_log
from .comment_analyzer import analyze_comments
from .knowledge_base import match_knowledge, lookup_bios_code
from .products import detect_product, master_queries, product_display
from .transferred_sync import sync_transferred, extract_axon_uuids, canonical_axon_url
from .mcp_enrich import enrich as mcp_enrich, enrichment_enabled
from .log_triage import extract_post_codes, triage_logs
from .axon_record import fetch_axon_records

kb = KBStore(config.KB_DB_PATH)


def _short(text: Any, n: int = 140) -> str:
    """Collapse whitespace/newlines and truncate for clean table display."""
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    return (s[:n] + "…") if len(s) > n else s


# We are Intel — drop "contact your Intel representative" guidance from decoded
# MCA-DB actions before they surface in the report's next-steps sections.
def _strip_intel_contact(text: Any) -> str:
    s = str(text or "")
    s = re.sub(r"[.;,]?\s*(?:and\s+)?contact your Intel representative[^.]*\.?",
               "", s, flags=re.IGNORECASE)
    s = re.sub(r"[.;,]?\s*Contact your OEM debug team\s*/\s*Intel representative\.?",
               "", s, flags=re.IGNORECASE)
    return re.sub(r"\s{2,}", " ", s).strip(" .;,")


# ---- Precise root-cause narrowing from decoded MCA evidence ---------------
# A 3-strike / WDTimeout is a forward-progress SYMPTOM, not a root cause; a bare
# "timeout → replace CPU" line is not actionable. These helpers turn the decoded
# bank / IP / MCACOD / MSCOD / recovery-class / first-IERR facts into a narrowed
# statement that names the real failing IP (or, for a 3-strike, the ranked
# blocker to trace) plus IP-specific next reads.
_THREE_STRIKE_RE = re.compile(
    r"3.?strike|three.?strike|wd\s*timeout|watchdog|internal.?timer|internal_timer|e101",
    re.IGNORECASE)


def _mc_evidence(decoded: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    ev = (decoded or {}).get("evidence") or {}
    return ev if isinstance(ev, dict) else {}


def _is_three_strike(mcs: Dict[str, Any]) -> bool:
    if not mcs:
        return False
    blob = " ".join(str(mcs.get(k, "")) for k in ("decode", "mscod", "mcacod"))
    if _THREE_STRIKE_RE.search(blob):
        return True
    return ("0400" in str(mcs.get("mcacod", ""))
            and "e101" in str(mcs.get("mscod", "")).lower())


# Placeholder tokens that mean "no first-error source was actually captured".
_NO_SOURCE = {"", "none", "n/a", "na", "unknown", "-", "—"}


def _recovery_str(recovery: Any) -> str:
    """Render an MCA recovery-class value (str or dict) as one readable line."""
    if not recovery:
        return ""
    if isinstance(recovery, str):
        return recovery.strip()
    if isinstance(recovery, dict):
        parts = []
        if recovery.get("os_action"):
            parts.append(str(recovery["os_action"]).strip())
        if recovery.get("lmce"):
            parts.append(f"LMCE: {str(recovery['lmce']).strip()}")
        if recovery.get("reboot"):
            parts.append(f"reboot: {str(recovery['reboot']).strip()}")
        return " · ".join(parts) if parts else ""
    return str(recovery).strip()


def _ierr_has_source(row: Dict[str, Any]) -> bool:
    """True only when an IERR/MCERR row names a real captured source (not a
    placeholder 'None' / 'No error logged' row)."""
    if not isinstance(row, dict):
        return False
    src = str(row.get("source_unit") or "").strip().lower()
    note = str(row.get("note") or "").strip().lower()
    if src in _NO_SOURCE:
        return False
    if "no error" in note or "not logged" in note:
        return False
    return True


def _is_poison_consumption(mcs: Dict[str, Any]) -> bool:
    """True when the MCA is a poison CONSUMPTION at a core cache unit (DCU/MLC/IFU/
    DTLB). The consuming unit is the VICTIM; the poison originated upstream."""
    if not mcs:
        return False
    decode = str(mcs.get("decode") or "").lower()
    unit = str(mcs.get("bank_unit") or "").upper()
    if "poison" in decode and unit in {"DCU", "MLC", "IFU", "DTLB"}:
        return True
    # MCACOD 0x0134 = DCU load poison consumption.
    return unit in {"DCU", "MLC", "IFU", "DTLB"} and "0134" in str(mcs.get("mcacod", ""))


# Intel SDM MCi_STATUS architectural bits (bit -> flag).
_MCI_STATUS_BITS = [(63, "VAL"), (62, "OVER"), (61, "UC"), (60, "EN"),
                    (59, "MISCV"), (58, "ADDRV"), (57, "PCC"), (56, "S"), (55, "AR")]


def classify_mca_status(status: Any) -> Dict[str, Any]:
    """Single source of truth for MCA severity/recovery from a 64-bit MCi_STATUS.
    Rule: UC=1 & PCC=1 => UNCORRECTED_FATAL (never 'corrected'). All report
    sections must consume this rather than re-deriving fatality."""
    try:
        val = int(str(status), 16) if not isinstance(status, int) else status
    except (TypeError, ValueError):
        return {"flags": {}, "severity": "unknown", "recovery_class": "unknown",
                "is_corrected": False, "is_uncorrected": False, "is_fatal": False,
                "valid": False}
    flags = {name: bool((val >> bit) & 1) for bit, name in _MCI_STATUS_BITS}
    uc, pcc, en, s, ar = (flags["UC"], flags["PCC"], flags["EN"], flags["S"], flags["AR"])
    if not flags["VAL"]:
        sev, corrected, uncorrected, fatal = "invalid", False, False, False
    elif uc and pcc:
        sev, corrected, uncorrected, fatal = "UNCORRECTED_FATAL", False, True, True
    elif uc:
        sev, corrected, uncorrected, fatal = "UNCORRECTED", False, True, False
    else:
        sev, corrected, uncorrected, fatal = "CORRECTED", True, False, False
    if not uc:
        recovery = "corrected — no OS action"
    elif pcc:
        recovery = "UCR/fatal — context corrupt, not recoverable (reset expected)"
    elif s and ar:
        recovery = "SRAR — software recoverable action required"
    elif s and not ar:
        recovery = "SRAO — software recoverable action optional"
    else:
        recovery = "UCNA — uncorrected no action (deferred)"
    return {"flags": flags, "severity": sev, "recovery_class": recovery,
            "is_corrected": corrected, "is_uncorrected": uncorrected,
            "is_fatal": fatal, "valid": True}


def mci_register_addrs(bank: Any) -> Dict[str, Any]:
    """IA32_MCi_* MSR addresses for a bank: CTL/STATUS/ADDR/MISC = 0x400/1/2/3 + 4*bank."""
    try:
        b = int(bank)
    except (TypeError, ValueError):
        return {"bank": bank, "MCi_CTL": None, "MCi_STATUS": None,
                "MCi_ADDR": None, "MCi_MISC": None}
    base = 0x400 + 4 * b
    return {"bank": b,
            "MCi_CTL": f"0x{base:X}", "MCi_STATUS": f"0x{base + 1:X}",
            "MCi_ADDR": f"0x{base + 2:X}", "MCi_MISC": f"0x{base + 3:X}"}


def _norm_ip(unit: str) -> str:
    """Normalise an IP/unit name for comparison (alpha prefix only)."""
    return re.sub(r"[^a-z]", "", str(unit or "").lower())[:4]


def _specific_root_cause(decoded: Optional[Dict[str, Any]],
                         target: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Narrowed, evidence-grounded root-cause line, or None when nothing decoded."""
    ev = _mc_evidence(decoded)
    mcs = ev.get("mc_status") or {}
    if not mcs or not mcs.get("status"):
        return None
    sockets = ev.get("sockets") or []
    skt = f"Socket {sockets[0]}" if sockets else "the failing socket"
    bank = mcs.get("bank")
    unit = (mcs.get("bank_unit")
            or (ev.get("bank_units") or {}).get(str(bank))
            or "the logged IP")
    where = (f"{skt} MCA bank {bank} (**{unit}**)"
             if bank not in (None, "") else f"{skt} — **{unit}**")
    ierr = [r for r in (decoded.get("ierr_table") or []) if _ierr_has_source(r)]
    first = ierr[0] if ierr else {}

    if _is_poison_consumption(mcs):
        rc = (f"A **poison-consumption** machine check was logged in {where} "
              f"(MCACOD {mcs.get('mcacod','?')}, MSCOD {mcs.get('mscod','?')} — "
              f"{_short(mcs.get('decode',''), 120)}). The {unit} is the **consumer/VICTIM**, "
              f"not the origin — poison is created upstream and consumed here on a load. "
              f"Locate the **poison SOURCE**: read MC_ADDR (ADDRV) to map the poisoned "
              f"address, then check the memory (IMC UE / patrol scrub) and IO/CXL (poisoned "
              f"completion / AER) paths. A `NO_iMC_MCA` signature means it is NOT an ordinary "
              f"DDR UE — trace the uncore/mesh/CXL read-return path.")
        if first.get("source_unit"):
            rc += (f" First IERR/MCERR captured from **{first['source_unit']}**"
                   + (f" @ `{first['address']}`" if first.get("address") else "") + ".")
        return rc

    if _is_three_strike(mcs):
        rc = (f"A **3-strike core watchdog timeout** (MCACOD INTERNAL_TIMER / "
              f"MSCOD THREE_STRIKE) was logged in {where}. This is the **trigger, not "
              f"the root cause** — the core stopped retiring because an upstream "
              f"transaction never completed. Narrow to the real forward-progress "
              f"blocker on {skt}, ranked: (1) CHA/TOR request timeout (stuck LLC/snoop), "
              f"(2) UPI credit starvation / link degrade, (3) IMC/DDR read stall "
              f"(no data return), (4) mesh/IDI credit stall or a hung uncore IP.")
        if first.get("source_unit"):
            rc += (f" First IERR/MCERR was captured from **{first['source_unit']}** on "
                   f"Socket {first.get('socket', '?')}"
                   + (f" @ `{first['address']}`" if first.get("address") else "")
                   + " — begin the trace there.")
        return rc

    decode = (mcs.get("decode") or "").strip()
    rc = f"Uncorrected machine-check logged in {where}"
    codebits = []
    if mcs.get("mcacod"):
        codebits.append(f"MCACOD {mcs['mcacod']}")
    if mcs.get("mscod"):
        codebits.append(f"MSCOD {mcs['mscod']}")
    if codebits:
        rc += " — " + ", ".join(codebits)
    if decode:
        rc += f" ({_short(decode, 160)})"
    _rec = _recovery_str(mcs.get("recovery"))
    if _rec:
        rc += f"; recovery class **{_rec}**"
    flags = ev.get("status_flags") or {}
    fset = [k for k in ("PCC", "UC", "OVER", "EN") if flags.get(k)]
    if fset:
        rc += f"; status flags {', '.join(fset)}"
    rc += f". Failing IP = **{unit}** on {skt}"
    if ev.get("mc_addr"):
        rc += f"; MC_ADDR `{ev['mc_addr']}`"
    if first.get("source_unit"):
        rc += (f". First IERR/MCERR from **{first['source_unit']}**"
               + (f" @ `{first['address']}`" if first.get("address") else ""))
    return rc + "."


# ---- POST-code explanation + hardware-vs-progress verdict -----------------
# A POST code is a BIOS firmware PROGRESS checkpoint, not an error code. It only
# signals a hardware/boot failure when the boot STALLS at it (never advances);
# if the log shows later checkpoints, the code is just an informational milestone.
def _post_phase(code_int: Optional[int]) -> str:
    if code_int is None:
        return ""
    if code_int <= 0x10:
        return "SEC (early CPU / microcode / cache-as-RAM / uncore bring-up, before memory training)"
    if code_int <= 0x2F:
        return "PEI (memory reference code / KTI-UPI training, DRAM bring-up)"
    if code_int <= 0x7F:
        return "PEI→DXE (silicon init, RC completion)"
    if code_int <= 0xBF:
        return "DXE / BDS (driver dispatch, boot device selection)"
    return "late BDS / OS hand-off"


def _post_verdict(decoded: Optional[Dict[str, Any]],
                  target: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Explain the last decoded POST checkpoint and state whether it is a hardware
    failure or just boot progress, using whether the boot advanced past it."""
    dp = (decoded or {}).get("post") or {}
    codes = dp.get("codes") or []
    if not codes:
        return None
    last = codes[-1]
    code = last.get("code", "")
    try:
        cint = int(str(code), 16)
    except (TypeError, ValueError):
        cint = last.get("code_int")
    desc = last.get("description") or last.get("macro") or ""
    phase = _post_phase(cint)
    boot = (decoded or {}).get("boot_flow") or {}
    target_text = str((target or {}).get("full_text") or "")
    narrative_recovery = bool(re.search(
        r"boot(?:ed|ing)\s+(?:up\s+)?to\s+EDK|power\s*cycle.*boot|"
        r"boot(?:ed|ing).*OS|upto\s+EDK", target_text, re.I))
    advanced = bool(boot.get("reached_os")) or len(codes) > 1 or narrative_recovery
    source = "HSD description/comments" if target_text else "attached logs"

    line = (f"**POST `{code}`** = `{last.get('macro', '')}` — {desc}. "
            f"Phase: {phase}. A POST code is a **BIOS firmware progress checkpoint, "
            f"not an error code**.")
    if advanced:
        return (line + f" Source: {source}. Verdict: **NOT a hardware failure** — the boot logged "
                "checkpoint(s) after this point, so it is an informational progress "
                "milestone, not the stall point.")
    if cint is not None and cint <= 0x10:
        cause = ("this is very early SEC (CPU/BSP-select/microcode/cache-as-RAM/uncore, "
                 "pre-memory) — a genuine stall here points to CPU/socket/VR/BSP-selection "
                 "or microcode bring-up; confirm with IERR/CATERR + a BMC port-80 capture "
                 "before calling it a hardware fault")
    elif cint is not None and cint <= 0x2F:
        cause = ("this is PEI memory/UPI training — a stall here points to DIMM/channel "
                 "training or UPI link bring-up; check MRC/KTI logs and DIMM population")
    else:
        cause = "inspect the BIOS module/driver dispatched right after this checkpoint"
    return (line + f" Source: {source}. Verdict: **boot did not advance past `{code}`** — {cause}. "
            "It is a hardware failure ONLY IF a HW error (MCA/IERR/CATERR) is also "
            "captured at this point; otherwise treat it as a firmware/config hang.")


def _historical_repro_section(platform: str, target: Optional[Dict[str, Any]],
                              log_findings: Optional[Dict[str, Any]]) -> str:
    """Build the additive historical-repro section without changing RCA state."""
    from pathlib import Path
    from .historical_repro import load_cases, match_historical_repro, render_section

    target = target or {}
    decoded = (log_findings or {}).get("decoded") or {}
    evidence = decoded.get("evidence") or {}
    mca = evidence.get("mc_status") or {}
    signature = {
        "platform": platform,
        "owner": target.get("component") or target.get("suspect_area") or "",
        "mcacod": mca.get("mcacod"),
        "mscod": mca.get("mscod"),
        "bank": mca.get("bank"),
        "socket": (evidence.get("sockets") or [None])[0],
        "keywords": " ".join(str(target.get(key) or "") for key in
                               ("title", "description", "full_text")),
    }
    root = Path(__file__).resolve().parents[1] / "golden_cases"
    return render_section(match_historical_repro(signature, load_cases(root)))


def _repro_vector_section(platform: str, target: Optional[Dict[str, Any]],
                          log_findings: Optional[Dict[str, Any]],
                          report_md: str) -> str:
    """Append ranked stress vectors as research context only."""
    from .repro_recommender import recommend_repro_vectors
    from .repro_signature_extractor import extract_failure_mechanism

    ownership = extract_ownership({"report_markdown": report_md,
                                   "log_findings": log_findings or {}})
    target = dict(target or {})
    decoded = (log_findings or {}).get("decoded") or {}
    labels = " ".join(str(item.get("label", "")) for item in
                      (log_findings or {}).get("signatures", []))
    target["keywords"] = " ".join(filter(None, [target.get("title", ""),
                                                   target.get("description", ""), labels]))
    mechanism = (decoded.get("failure_mechanism") or
                 target.get("failure_mechanism") or extract_failure_mechanism(target))
    recommendations = recommend_repro_vectors(
        ownership.get("owning_ip", ""), mechanism, platform or "", top_n=5)
    lines = ["## Suggested Reproduction Vectors", "",
             "Historical reference only -- not used in confidence or verdict calculation.", ""]
    if not recommendations:
        lines.append("No historical reproduction vector found.")
        return "\n".join(lines) + "\n"
    for index, recommendation in enumerate(recommendations, 1):
        lines.extend([
            f"### Recommendation {index}",
            f"- **Tool:** {recommendation.get('tool_name', 'unclassified')}",
            f"- **Subtest / mode:** {recommendation.get('subtest_or_mode', 'unknown')}",
            f"- **Trigger context:** {', '.join(recommendation.get('trigger_context', []))}",
            f"- **Match:** {recommendation.get('match_type')}",
            f"- **Hit count:** {recommendation.get('hit_count', 0)}",
            f"- **Evidence tier:** {recommendation.get('evidence_tier', 'UNKNOWN')}",
            f"- **Source HSDs:** {', '.join(recommendation.get('source_hsd_ids', []))}",
            "",
        ])
    return "\n".join(lines)


def _specific_next_steps(decoded: Optional[Dict[str, Any]]) -> List[str]:
    """IP-specific next reads derived from the decoded bank/unit."""
    ev = _mc_evidence(decoded)
    mcs = ev.get("mc_status") or {}
    if not mcs or not mcs.get("status"):
        return []
    bank = mcs.get("bank")
    unit = (mcs.get("bank_unit") or "").lower()
    sockets = ev.get("sockets") or []
    skt = sockets[0] if sockets else "N"
    steps: List[str] = []
    try:
        b = int(str(bank))
        steps.append(f"Dump the failing bank on Socket {skt}: `rdmsr 0x{b*4+0x401:X}` "
                     f"(MC{b}_STATUS), `0x{b*4+0x402:X}` (MC{b}_ADDR), "
                     f"`0x{b*4+0x403:X}` (MC{b}_MISC).")
    except (TypeError, ValueError):
        pass
    if _is_three_strike(mcs):
        steps.append("3-strike = forward-progress timeout — trace the BLOCKER, not the core: "
                     "read CHA TOR state (`sv.socketN.uncore.cha.tor_*` for stuck/pending "
                     "entries), then UPI link/credit status, then IMC/DDR pending reads, then "
                     "mesh/IDI credits.")
        steps.append("Capture ACD / crashdump for TOR + the timed-out core's RIP; correlate its "
                     "last request with the pending uncore transaction (CHA/UPI/IMC) that never "
                     "returned.")
    else:
        if "upi" in unit or "kti" in unit:
            steps.append("UPI/KTI bank: read per-link ktilk phy/LL error+status and CRC/retry "
                         "counters on both link partners; check for L0p-exit / phy-reset events.")
        elif "cha" in unit or "llc" in unit:
            steps.append("CHA/LLC bank: read CHA TOR timeout + SAD/target decode; identify the "
                         "target (memory vs IO) that failed to return.")
        elif any(k in unit for k in ("imc", "ddr", "mcchan", "m2mem", "b2cmi")):
            steps.append("Memory bank: read IMC retry/CRC and the failing DIMM/rank from MC_ADDR; "
                         "check DDR training margins on that channel.")
        elif any(k in unit for k in ("ubox", "punit", "pcu")):
            steps.append("UBOX/PUnit bank: read the ubox IERR/MCerr logging registers and the "
                         "PUnit mailbox status for the first-error source.")
        steps.append("Confirm the decoded MCACOD/MSCOD against the product EDS-R bank→IP table "
                     "before dispositioning.")
    return steps 


def _collect_sources(target: Optional[Dict[str, Any]], recall: Dict[str, Any],
                     similar: List[Dict[str, Any]], log_findings: Optional[Dict[str, Any]],
                     transferred: Optional[Dict[str, Any]], mcp_sources: List[str],
                     axon_records: Optional[List[Dict[str, Any]]],
                     platform: str) -> List[Dict[str, str]]:
    """Assemble the reference materials that genuinely contributed to this
    analysis, so the report can cite where each failure-decode and next-step
    came from. Only sources actually consulted for this ticket are listed."""
    sources: List[Dict[str, str]] = []
    decoded = (log_findings or {}).get("decoded") or {}

    if decoded.get("bios"):
        sources.append({
            "name": "BIOS EWL / RC-Fatal / MCHECK decoder databases",
            "kind": "Decoder DB",
            "detail": "Enhanced Warning Log, RC-Fatal and MCHECK code tables used to decode BIOS/SOL serial failures.",
            "ref": "app/decoders/ewl_codes_database.json · rc_fatal_errors_database.json · mcheck_codes_database.json",
        })
    if decoded.get("mca"):
        _mca_prov = []
        try:
            from .source_provenance import provenance_for
            _mca_prov = [provenance_for("app/decoders/mca_codes_database.json")]
        except Exception:
            pass
        sources.append({
            "name": "MCA (Machine Check Architecture) code database",
            "kind": "Decoder DB",
            "detail": "Bank-specific MSCOD/MCACOD decode of MCi_STATUS from SOL RAS and PythonSV register dumps.",
            "ref": "app/decoders/mca_codes_database.json",
            "trust": (_mca_prov[0].get("trust", "UNKNOWN") if _mca_prov else "UNKNOWN"),
            "trust_score": str(_mca_prov[0].get("score", 0) if _mca_prov else 0),
            "source_document": (_mca_prov[0].get("source_document", "UNKNOWN")
                                if _mca_prov else "UNKNOWN"),
        })
    _ev = decoded.get("evidence") or {}
    if _ev.get("bank_units"):
        # Name the source from the resolver so GNR / SRF / DMR are cited correctly.
        _src_name = "MCA bank map"
        _src_ref = "app/decoders/bank_mapping.json"
        try:
            from .decoders.bank_map import bank_component
            _first_bank = next(iter(_ev["bank_units"].keys()))
            _info = bank_component(_first_bank, platform) or {}
            _src_name = _info.get("source") or _src_name
            if "GNR" in _src_name:
                _src_ref = "app/decoders/bank_mapping_gnr.json"
            elif "SRF" in _src_name:
                _src_ref = "app/decoders/bank_mapping_srf.json"
            elif "CWF" in _src_name:
                _src_ref = "app/decoders/bank_mapping_cwf.json"
        except Exception:
            pass
        sources.append({
            "name": _src_name,
            "kind": "Bank map",
            "detail": "Maps the failing MCA bank number to its silicon unit "
                      f"({', '.join(f'{b}->{u}' for b, u in list(_ev['bank_units'].items())[:4])}).",
            "ref": _src_ref,
            "trust": "AUTHORITATIVE" if _src_ref != "app/decoders/bank_mapping.json" else "UNKNOWN",
            "trust_score": "100" if _src_ref != "app/decoders/bank_mapping.json" else "0",
            "source_document": _src_name,
        })
    if decoded.get("post"):
        sources.append({
            "name": "BIOS POST / checkpoint code database",
            "kind": "Decoder DB",
            "detail": "Boot-progress checkpoint decode locating the last successful POST stage.",
            "ref": "app/decoders/post_codes_database.json",
        })
    if decoded.get("ierr_table"):
        sources.append({
            "name": "PythonSV UBOX IERR/MCerr table decoder",
            "kind": "Decoder",
            "detail": "First/second IERR/MCerr capture decode from PythonSV ubox error tables.",
            "ref": "app/log_triage.py",
        })

    matches = recall.get("matches") or []
    if matches:
        sources.append({
            "name": "Self-learning Knowledge Base",
            "kind": "Knowledge Base",
            "detail": f"{len(matches)} prior case(s) matched (confidence: {recall.get('confidence', '—')}); root cause and resolution reused where applicable.",
            "ref": config.KB_DB_PATH,
        })

    if similar:
        mqs = master_queries(platform) if platform else []
        detail = f"{len(similar)} similar HSD(s) compared for known-issue / resolution context."
        if mqs:
            detail += f" Master queries: {', '.join(str(q) for q in mqs)}."
        sources.append({
            "name": f"{product_display(platform) or platform or 'Product'} HSDES master-query corpus",
            "kind": "HSDES corpus",
            "detail": detail,
            "ref": "HSDES REST (hsdes-api.intel.com)",
        })

    if transferred and transferred.get("transferred_to"):
        sources.append({
            "name": f"Transferred sub-team HSD {transferred.get('transferred_to')}",
            "kind": "HSDES ticket",
            "detail": "Root cause, fix ingredient/revision and status pulled from the sub-team ticket this sighting was transferred to.",
            "ref": f"HSD {transferred.get('transferred_to')}",
        })

    for s in (mcp_sources or []):
        sources.append({
            "name": f"{s} (MCP)",
            "kind": "External agent",
            "detail": "Internal Geni / Co-Design HSDES agent queried for additional ticket grounding.",
            "ref": s,
        })

    if axon_records:
        sources.append({
            "name": "Axon SVTools failure recordings",
            "kind": "Axon",
            "detail": f"{len(axon_records)} linked recording(s) decoded for failure signatures.",
            "ref": "Axon (SVTools)",
        })

    # Product spec corpus (EDS-R / Error-Arch/RAS / SOC guide-HAS) — cite the
    # verified Tier-1 docs for the detected product, but only when an MCA/RAS
    # decode was actually produced (keeps the citation relevant, not noise).
    if platform and (decoded.get("mca") or _ev.get("bank_units")):
        try:
            from .products import spec_corpus, product_display as _pd
            for doc in (spec_corpus(platform) or {}).get("tier1", []):
                url = (doc.get("url") or "").strip()
                if not url:
                    continue
                sources.append({
                    "name": doc.get("title", "Spec"),
                    "kind": doc.get("type", "Spec"),
                    "detail": f"Authoritative {_pd(platform) or platform} spec for "
                              "MCA/RAS bank->IP ownership and MSCOD/MCACOD decode.",
                    "ref": url,
                })
        except Exception:
            pass

    return sources


def _render_sources_md(sources: List[Dict[str, str]]) -> str:
    """Render the reference-source list as a Markdown section for the report."""
    if not sources:
        return ""
    lines = [
        "",
        "## Reference Sources",
        "",
        "Documents and datasets consulted to decode the failure signatures and derive the next steps:",
        "",
        "| # | Source | Type | How it was used | Reference | Trust |",
        "|---|--------|------|-----------------|-----------|-------|",
    ]
    for i, s in enumerate(sources, 1):
        name = str(s.get("name", "")).replace("|", "\\|")
        kind = str(s.get("kind", "")).replace("|", "\\|")
        detail = _short(s.get("detail", ""), 160).replace("|", "\\|")
        ref = str(s.get("ref", "")).replace("|", "\\|")
        trust = str(s.get("trust", "UNKNOWN")).replace("|", "\\|")
        score = str(s.get("trust_score", "0"))
        lines.append(f"| {i} | {name} | {kind} | {detail} | `{ref}` | {trust} ({score}) |")
    lines.append("")
    return "\n".join(lines)

SYSTEM_PROMPT = """You are a Principal Xeon Platform Validation / RAS debug engineer.
Your task is NOT to summarize logs — it is to RECONSTRUCT FAILURE CAUSALITY for an Intel
server-platform HSD (GNR/SRF/CWF today; DMR/COR next). You cover CPU/silicon RAS
(MCA/MCE/IERR/CATERR/3-strike), UPI/coherency, CHA/SCF/mesh, memory (DDR/MRC), IO
(PCIe/CXL), power/Sx, BIOS/IFWI/BMC and boot/hang/reset, OS/driver.

HARD RULE: Never produce a generic recommendation ("Update BIOS", "Collect more logs",
"Verify microcode", "re-run") UNLESS it is directly supported by the evidence in this
ticket. Do not jump from a signature (e.g. MCACOD=0x400 / WDTimeout / TOR_TIMEOUT) to a
conclusion without first establishing the timeline, the owning IP, and cause-vs-noise.
NEVER fabricate HSD IDs, register names, values, banks, or commands. If a fact is not in
the provided data, say so and list it under Required Missing Data.

You are given: the target HSD (title/description/comments), KB matches, similar HSDs,
decoded attached-log findings (MCA banks, MCACOD/MSCOD, status flags, IERR/MCERR source,
POST codes, boot flow), the comment investigation, and optional transferred-ticket findings.

Work through these steps IN ORDER and emit them as the report sections below.

STEP 1 — FAILURE TIMELINE: identify FIRST_EVENT, SECONDARY_EVENTS (propagated), and
FINAL_FAILURE (last observable symptom). Order by time, not by log position.

STEP 2 — FAILURE OWNER (IP): map every error to Core / CHA / UBOX / SCF / UPI / MC / PCIe /
Firmware / BIOS. For every MCA report Bank, MCACOD, MSCOD, Socket, Die, IP, and explain what
each code means (from the provided decode).

STEP 3 — CAUSE vs NOISE: label every observation ROOT_CAUSE, SUPPORTING_EVIDENCE, or
INCIDENTAL. Never treat WHEA spam, PCIe retries, or machine-check aftermaths as primary
without proof.

STEP 4 — CORRELATION: correlate PythonSV / StatusScope / MCA / serial / BMC / HSD-comment
evidence into a causal chain (e.g. CHA TOR_TIMEOUT -> SCF timeout -> MCERR -> CPU error ->
node hang). Only assert a link when evidence supports it; otherwise mark it hypothesised.

STEP 5 — COMPETING HYPOTHESES: give Hypothesis A/B/C, each with Evidence For and Evidence
Against. Rank them.

STEP 6 — CONFIDENCE: calibrate 95-100% Confirmed / 80-94% Strong / 60-79% Likely /
<60% Insufficient evidence.

STEP 7 — REQUIRED MISSING DATA: list the exact items needed to raise confidence
(MC_STATUS, MC_MISC, MCA bank owner, crashdump register, StatusScope output, first-IERR
socket/die) and WHY each is needed.

STEP 8 — VERDICT: Root Cause + reasoning chain + confidence + the single next validation
experiment.

MCA DEEP ANALYSIS (mandatory when any MCA is present): for every MCA decode MCACOD, decode
MSCOD, identify the bank owner, map to IP, determine fatality, determine first reported
socket and die, and whether the error propagated. Classify as PRIMARY_ERROR,
SECONDARY_ERROR, or VICTIM_ERROR. A 3-strike / WDTimeout / INTERNAL_TIMER is a
forward-progress SYMPTOM, not a root cause — find the transaction/IP that blocked progress
(CHA TOR, UPI credits, IMC/DDR, mesh) and say which failed first.

SELF-REVIEW (do this before finalizing; if any answer is unsatisfactory, rewrite the RCA):
1) What evidence would DISPROVE my root cause? 2) Could another IP own this failure?
3) Did I confuse symptom with cause? 4) Did I use a KB match without evidence?
5) Would a senior RAS architect accept this RCA?

Produce the report in Markdown with EXACTLY these sections, in this order:

# Root Cause Analysis — HSD <id>
Metadata table: Date, Platform/Family, Component/Domain, Status/Priority, Owner.

## Artifacts Under Analysis
Ticket, number of comments parsed, attachment/log files scanned (name each), log lines.

## Failure Timeline
FIRST_EVENT / SECONDARY_EVENTS / FINAL_FAILURE (as a small table where possible).

## MCA Deep Analysis
Per-MCA table (Bank | MCACOD | MSCOD | Socket | Die | IP | Meaning | Fatality | Class), then
PRIMARY_ERROR / SECONDARY_ERROR / VICTIM_ERROR. If no valid MCA, say so.

## Failure Owner (IP)
The owning IP with the evidence that assigns ownership.

## Cause vs Noise
Bulleted classification (ROOT_CAUSE / SUPPORTING_EVIDENCE / INCIDENTAL).

## Correlation & Causal Chain
The evidence-backed chain (or the best hypothesised chain, clearly labelled).

## Competing Hypotheses
Hypothesis A/B/C, each with Evidence For / Evidence Against, ranked.

## Root Cause & Confidence
Primary root cause labelled **confirmed from data** vs **hypothesis**, the reasoning chain,
and a confidence % using the bands above.

## Required Missing Data
Exact items needed + why each is needed.

## Recommended Fix / Next Validation Experiment
NUMBERED, concrete, evidence-tied steps (exact PythonSV reads / revision A-B / BKC update /
re-validate). End with a bold **Expected result:** line. Do NOT include generic steps unless
evidence supports them.

## Self-Review
Answer the 5 self-review questions briefly; confirm the RCA survives them.

## Appendix
Similar-HSDs table (ID | Source: KB/HSDES | Similarity reason | Root cause | Status), KB
recall detail. Only cite HSD IDs and Axon links ACTUALLY present in the provided data.

Return a SINGLE JSON object (no prose outside it) with keys:
  "report_markdown": string  (the full RCA report in the section order above)
  "kb_entry": object matching this schema:
    {
      "signature": {"family","platform","stepping","domain","component","error_string",
                    "key_terms":[...]},
      "similar_hsds": [{"id","why_matched"}],
      "root_cause": {"text","confidence":"confirmed|hypothesis"},
      "debug_steps": ["..."],
      "resolution": {"text","source_hsd"},
      "provenance": {"source":"KB|HSDES|MCP","timestamp","confidence_tag":"High|Medium|Low"}
    }
Store only confirmed/observed content in kb_entry. Tag unproven items as hypothesis.
"""

# Broad platform tag list (extend freely). Used only as a label, not a filter.
_PLATFORMS = [
    "GNR AP", "GNR-AP", "GNR", "SRF", "CWF", "SPR", "EMR", "ICX", "CLX",
    "Eagle Stream", "Birch Stream", "Mountain Stream", "Diamond Rapids", "DMR",
]

# Domain hint library: keyword -> (domain label, [representative commands]).
_DOMAIN_HINTS: List[Tuple[str, str, List[str]]] = [
    (r"\bupi|ktil|kti\b|coheren|link\s*retrain",
     "UPI / coherency",
     ["`sv.socket0.upi.upi<port>.ktilk_ph_ctr_status.read()`  # confirm reg via tab-complete",
      "If CRC/retry counters set -> link-integrity path; else protocol/transaction path."]),
    (r"\brdt|rmid|clos|\bmba\b|qos|cmt|mbm",
     "RDT / QoS (RAS)",
     ["`sv.socket0.uncore.rdt.<reg>.read()`  # confirm path for your stepping",
      "Counter mismatch -> RMID/CLOS mapping; else enforcement path."]),
    (r"\bmca|mce|machine\s*check|ierr|caterr|mcerr|\bmsmi\b",
     "RAS / MCA",
     ["`sv.socket0.uncore.mca_bank<N>.status.read()` then decode MCACOD/MSCOD/RIP",
      "Bank + RIP identify the failing unit."]),
    (r"\bddr|dimm|memory|mrc|\btrain|rank|\bce\b|\bue\b|patrol\s*scrub",
     "Memory",
     ["Grep MRC/BIOS log for training step + channel/rank; capture DIMM SPD/config.",
      "Correlate CE/UE address to channel/rank/bank."]),
    (r"pcie|\bcxl\b|ltssm|link\s*train|lane|aer|retimer",
     "IO / PCIe / CXL",
     ["OS: `lspci -vvv` (Windows: check Device Manager / PnP); inspect LTSSM state + AER.",
      "Degraded width/speed -> equalization/retimer; AER errors -> correctable vs fatal."]),
    (r"\bs3\b|\bs4\b|\bs5\b|\bsx\b|hibernat|suspend|resume|\bacpi\b|sleep|\bdpmo\b|power\s*state",
     "Power / Sleep-state (Sx)",
     ["OS: `powercfg /a` (S-states available?), `powercfg /lastwake`, `powercfg /waketimers`.",
      "PythonSV/PMC: `pmc.Sx_check()`; inspect PMC SLP_Sx status registers.",
      "Kernel-Power events: Get-WinEvent System | where Id -in 41,42,107,187."]),
    (r"bios|ifwi|\bbmc\b|cpld|\bpost\b|\bboot|\bhang|\breset|coldboot|\bsbsp\b|\bs3m\b|softstrap",
     "BIOS / firmware / boot-hang",
     ["Capture serial/BIOS boot log; find last successful POST/checkpoint before hang.",
      "PythonSV: `sv.socket0.uncore.ubox.ncdecs.biosscratchpad<N>_cfg...read()` for progress.",
      "Compare firmware/ucode/IFWI/BMC revisions across passing vs failing runs."]),
    (r"windows|linux|driver|\bos\b|bsod|\bhang\b|watchdog|\bwhea\b",
     "OS / driver",
     ["Collect OS event/kernel logs; note OS build and driver versions.",
      "A/B the OS build (passing vs failing) to isolate OS vs firmware."]),
]


def _detect_platform(text: str) -> Optional[str]:
    # Product registry (products.json) drives detection — extensible to DMR/COR
    # without code changes. Falls back to the inline platform list.
    p = detect_product(text)
    if p:
        return product_display(p)
    t = (text or "").upper()
    for name in _PLATFORMS:
        if name.upper() in t:
            return name
    return None


def _detect_domains(text: str) -> List[Tuple[str, List[str]]]:
    """Return domains ranked by how strongly they appear (match frequency),
    strongest first, so the report focuses on the dominant domain(s)."""
    t = (text or "").lower()
    scored: List[Tuple[int, str, List[str]]] = []
    for pattern, label, cmds in _DOMAIN_HINTS:
        n = len(re.findall(pattern, t))
        if n:
            scored.append((n, label, cmds))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [(label, cmds) for _, label, cmds in scored]


_RC_PAT = re.compile(
    r"(root[\s_-]?cause|caused by|due to|because of|\brca\b|culprit|isolated to)", re.I)
_FIX_PAT = re.compile(
    r"(fixed in|fix\s*[:=]|resolution\s*[:=]|resolved by|work[\s-]?around|\bw/?a\b|"
    r"mitigat|bkm|patched|corrected)", re.I)


def _extract_findings(target: Optional[Dict[str, Any]],
                      comment_findings: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """Deterministically pull root-cause / resolution text. The ticket's COMMENT
    THREAD is the primary source (that's where debug converges); ticket fields
    and phrase-matching are fallbacks."""
    if not target:
        return {"root_cause": "", "resolution": "", "confidence": "hypothesis"}
    rec = target.get("raw", {}) or {}

    def gf(*names: str) -> str:
        for n in names:
            for k, v in rec.items():
                if v and (k == n or k.endswith("." + n)):
                    return str(v)
        return ""

    def is_prose(s: str) -> bool:
        # Skip code / logs / URLs so we capture human explanation, not snippets.
        if any(tok in s for tok in ("def ", "self.", "{", "}", "=>", "::", "http",
                                    ".py", "</", "/>", "import ", "()")):
            return False
        alpha = sum(c.isalpha() or c.isspace() for c in s)
        return len(s) >= 12 and alpha / max(1, len(s)) >= 0.65

    text = target.get("full_text", "") or ""
    rc_lines: List[str] = []
    fix_lines: List[str] = []
    for chunk in re.split(r"[\n.;]", text):
        s = chunk.strip()
        if not is_prose(s):
            continue
        if _RC_PAT.search(s) and len(rc_lines) < 2:
            rc_lines.append(s)
        if _FIX_PAT.search(s) and len(fix_lines) < 2:
            fix_lines.append(s)

    # Comment-mined findings take precedence — they reflect where debug converged.
    cf = comment_findings or {}
    root_cause = cf.get("root_cause") or " ".join(rc_lines) or gf(
        "fix_description", "executive_summary")
    resolution = cf.get("workaround") or " ".join(fix_lines) or gf(
        "closed_reason", "status_reason")
    status = (target.get("status") or "").lower()
    # A comment claim (even one that also proposes a fix) is a human observation,
    # not validated proof — it must not grade the finding 'confirmed' on its own.
    confirmed = (status in ("closed", "complete", "verified")
                 and bool(root_cause or resolution))
    return {
        "root_cause": root_cause[:400],
        "resolution": resolution[:400],
        "confidence": "confirmed" if confirmed else "hypothesis",
    }


async def analyze(hsd_id: str, symptoms: str,
                  hsdes_token: Optional[str] = None,
                  username: Optional[str] = None,
                  password: Optional[str] = None,
                  log_text: Optional[str] = None,
                  fetch_attachments: bool = False,
                  follow_transferred: bool = True,
                  reference_hsd_ids: Optional[List[str]] = None,
                  target_override: Optional[Dict[str, Any]] = None,
                  offline_mode: bool = False) -> Dict[str, Any]:
    def _normalize_ref_ids(ids: Optional[List[str]], self_id: str) -> List[str]:
        out: List[str] = []
        seen: set = set()
        for raw in (ids or []):
            rid = re.sub(r"\D", "", str(raw or "").strip())
            if not rid or rid == self_id or rid in seen:
                continue
            seen.add(rid)
            out.append(rid)
        return out

    def _extract_clone_ref_ids(tgt: Optional[Dict[str, Any]], self_id: str) -> List[str]:
        text = (tgt or {}).get("full_text", "") or ""
        if not text:
            return []
        hits: List[str] = []
        pats = [
            r"clon(?:e|ed|ing)?[^0-9]{0,80}(1[56]\d{8,9})",
            r"parent\s+record[^0-9]{0,80}(1[56]\d{8,9})",
            r"original\s+hsd[^0-9]{0,80}(1[56]\d{8,9})",
        ]
        for p in pats:
            hits.extend(re.findall(p, text, re.I))
        return _normalize_ref_ids(hits, self_id)

    def _has_strong_log_evidence(findings: Optional[Dict[str, Any]]) -> bool:
        if not findings:
            return False
        if findings.get("mca_decode"):
            return True
        sigs = findings.get("signatures") or []
        fatal = sum(int(s.get("count", 0)) for s in sigs if str(s.get("severity", "")).lower() == "fatal")
        high = sum(int(s.get("count", 0)) for s in sigs if str(s.get("severity", "")).lower() == "high")
        return fatal >= 2 or (fatal >= 1 and high >= 3)

    client = HSDESClient(hsdes_token, username, password)
    # Text we reason over = typed symptoms (target text is added after fetch).
    platform = _detect_platform(f"{symptoms} {hsd_id}")

    # Step 0 - RECALL (domain-agnostic: no family filter; exclude self-match)
    recall = kb.search(symptoms, exclude_id=hsd_id)

    # Step 2 - INVESTIGATE
    target = target_override if target_override is not None else await client.get_article(hsd_id)
    # Discover REAL file attachments via the HSDES attachments API (SOL zips,
    # PythonSV dumps, crashdump JSON), falling back to inline resource links.
    attachment_meta: List[Dict[str, Any]] = []
    if target and not target.get("error") and not offline_mode:
        try:
            _tenant = str((target.get("raw") or {}).get("tenant") or "server_platf")
            attachment_meta = await client.list_attachments(hsd_id, tenant=_tenant)
        except Exception:
            attachment_meta = []
    if not attachment_meta and target:
        attachment_meta = [{"id": rid, "name": ""}
                           for rid in client.attachment_ids(target)]
    attachments = [a["id"] for a in attachment_meta]

    reference_hsds: List[Dict[str, Any]] = []

    # Read the comment thread like a human analyst — this is where debug converges.
    comment_source: List[Dict[str, str]] = list((target or {}).get("comments_structured", [])) if target else []
    comment_findings = analyze_comments(comment_source) if comment_source else None

    # Optional MCP enrichment: also ask the Geni + Co-Design HSDES agents and fold
    # their answers into the ticket context (grounds the report in every source).
    mcp_sources: List[str] = []
    if target and not target.get("error") and not offline_mode and enrichment_enabled():
        try:
            # Pass ticket text + typed symptoms so need-based sources (BIOS/S3M,
            # kernel-crash, Redfish) are only queried when the evidence is relevant.
            _ctx = " ".join(filter(None, [
                target.get("title", ""),
                target.get("full_text", "") or target.get("description", ""),
            ]))
            mcp_context = await mcp_enrich(hsd_id, symptoms, context_text=_ctx,
                                           product=detect_product(_ctx) or "")
        except Exception:
            mcp_context = []
        if mcp_context:
            extra = "\n\n".join(
                f"### {c['source']} (MCP)\n{c['text']}" for c in mcp_context)
            target = dict(target)
            target["full_text"] = (
                (target.get("full_text", "") or "")
                + "\n\n== EXTERNAL SOURCES (MCP) ==\n" + extra).strip()
            mcp_sources = [c["source"] for c in mcp_context]

    # Transferred-ticket sync is decided later by the auto-orchestrator.
    transferred = None

    # Logs: any pasted log + (optionally) the logs already attached to the ticket.
    combined_log = log_text or ""
    fetched = 0
    attach_files: List[str] = []
    if fetch_attachments and attachments:
        atext = await client.fetch_attachment_text(target, attachments=attachment_meta)
        if atext:
            combined_log = (combined_log + "\n" + atext).strip()
            fetched = len(attachments)
            # Reduce each marker to "<resource_id>:<basename>" then de-duplicate,
            # so multi-member zips / long paths don't show repeated entries.
            clean_files: List[str] = []
            for f in re.findall(r"### attachment ([^\n]+)", atext):
                f = f.strip()
                if ":" in f:
                    rid, name = f.split(":", 1)
                    name = re.split(r"[\\/]", name.strip())[-1]
                    f = f"{rid.strip()}:{name}"
                clean_files.append(f)
            attach_files = list(dict.fromkeys(clean_files))

    # Axon: fetch linked recordings (CLI) and fold their log content into the
    # decode + metadata into the report, so Axon evidence is triaged too.
    axon_records: List[Dict[str, Any]] = []
    axon_uuids = sorted(extract_axon_uuids((target or {}).get("full_text", "") or ""))
    if axon_uuids and target and not target.get("error") and not offline_mode:
        try:
            axon_records = await fetch_axon_records(axon_uuids)
        except Exception:
            axon_records = []
        for rec in axon_records:
            for i, ctext in enumerate(rec.get("log_texts", []) or []):
                combined_log = (combined_log + f"\n### attachment axon:{rec['uuid'][:8]}#{i}\n"
                                + ctext).strip()
        if target is not None:
            target = dict(target)
            target["axon_records"] = axon_records
            # Collect SVTools failure signatures from Axon for precise root cause
            axon_sigs: List[str] = []
            for rec in axon_records:
                sigs_str = rec.get("svtools_signatures") or ""
                if sigs_str:
                    axon_sigs.extend(s.strip() for s in sigs_str.split(";") if s.strip())
            if axon_sigs:
                target["axon_svtools_signatures"] = axon_sigs
            # Even without CLI/Geni, surface known SVTools sigs from the Axon URL
            # if the ticket description/comments already contain them (e.g. from
            # a PythonSV Axon paste).  Nothing extra needed — already in full_text.

    log_findings = analyze_log(combined_log) if combined_log.strip() else None
    # End-to-end decode of SOL / PythonSV / POST logs via the bundled Intel
    # decoder databases (EWL / RC-Fatal / MCHECK / MCA / POST) — attached to the
    # findings so a fresh HSD with logs is triaged without manual effort.
    if log_findings is not None:
        try:
            log_findings["decoded"] = triage_logs(combined_log, product=platform)
        except Exception:
            log_findings["decoded"] = None
    # POST codes are often recorded in the HSD narrative rather than in the
    # attached console logs; retain them with explicit ticket-text provenance.
    if target and not target.get("error"):
        ticket_post = extract_post_codes(target.get("full_text") or "")
        if ticket_post:
            if log_findings is None:
                log_findings = {"lines_scanned": 0, "signatures": [], "decoded": {}}
            if not log_findings.get("decoded"):
                log_findings["decoded"] = {}
            post = log_findings["decoded"].setdefault("post", {"codes": []})
            post["codes"] = ticket_post + [c for c in post.get("codes", [])
                                            if c.get("code") not in {x.get("code") for x in ticket_post}]
            log_findings["decoded"]["post_source"] = "HSD description/comments"
    # Auto depth orchestration (no user knobs):
    # 1) KB recall, 2) current-ticket logs/comments, 3) clones/similar/transferred only if needed.
    top_match = (recall.get("matches") or [{}])[0]
    kb_known = (recall.get("confidence") == "High") and bool(
        top_match.get("root_cause") or top_match.get("resolution"))
    comment_known = bool((comment_findings or {}).get("root_cause"))
    log_known = _has_strong_log_evidence(log_findings)
    auto_history = not (kb_known or comment_known or log_known)

    if auto_history and target and not target.get("error") and not offline_mode:
        merged_ref_ids = _normalize_ref_ids(reference_hsd_ids, str(hsd_id))
        auto_ref_ids = _extract_clone_ref_ids(target, str(hsd_id))
        merged_ref_ids = _normalize_ref_ids(merged_ref_ids + auto_ref_ids, str(hsd_id))
        if merged_ref_ids and client.enabled:
            for rid in merged_ref_ids[:5]:
                try:
                    ref = await client.get_article(rid)
                except Exception:
                    ref = None
                if not ref or ref.get("error"):
                    continue
                reference_hsds.append(ref)

        if target and reference_hsds:
            target = dict(target)
            summaries: List[Dict[str, Any]] = []
            ref_blocks: List[str] = []
            merged_comments: List[Dict[str, str]] = list((target or {}).get("comments_structured", []))
            for ref in reference_hsds:
                rid = str(ref.get("id") or "")
                rtitle = str(ref.get("title") or "")
                rdesc = str(ref.get("description") or "")
                rcomments = list(ref.get("comments") or [])
                summaries.append({
                    "id": rid,
                    "title": rtitle,
                    "status": ref.get("status") or "",
                    "owner": ref.get("owner") or "",
                    "comment_count": len(rcomments),
                })
                ref_blocks.append(
                    "\n\n".join(filter(None, [
                        f"REFERENCE HSD: {rid}",
                        f"TITLE: {rtitle}" if rtitle else "",
                        f"DESCRIPTION:\n{rdesc}" if rdesc else "",
                        ("COMMENTS:\n" + "\n".join(rcomments)) if rcomments else "",
                    ]))
                )
                for c in (ref.get("comments_structured") or []):
                    cc = dict(c)
                    cc["author"] = f"{cc.get('author', '')}@HSD{rid}".strip("@")
                    merged_comments.append(cc)
            target["reference_hsds"] = summaries
            target["full_text"] = (
                (target.get("full_text", "") or "")
                + "\n\n== REFERENCE HSD THREADS (auto clone enrichment) ==\n"
                + "\n\n".join(ref_blocks)
            ).strip()
            comment_findings = analyze_comments(merged_comments) if merged_comments else comment_findings
            if comment_findings:
                comment_findings = dict(comment_findings)
                comment_findings["reference_hsds_used"] = [str(r.get("id") or "") for r in reference_hsds]

    blob = f"{symptoms} " + (target.get("full_text") or target.get("description") or ""
                             if target else "")
    if log_findings:
        blob += " " + " ".join(s["label"] for s in log_findings["signatures"])
    if not platform:
        platform = _detect_platform(blob)
    similar: List[Dict[str, Any]] = []
    if auto_history and recall["confidence"] != "High":
        similar = await client.search_similar(symptoms)

    if auto_history and follow_transferred and target and not target.get("error") and not offline_mode:
        try:
            transferred = await sync_transferred(client, target)
        except Exception:
            transferred = None

    # Step 4 - REPORT
    if llm.enabled and not offline_mode:
        report_md, kb_entry = await _llm_report(
            hsd_id, symptoms, platform, recall, target, similar, client.enabled,
            log_findings, comment_findings, transferred
        )
    else:
        report_md, kb_entry = _offline_report(
            hsd_id, symptoms, platform, recall, target, similar, client.enabled,
            log_findings, attachments, fetched, attach_files, comment_findings,
            transferred, fetch_attempted=fetch_attachments
        )

    # Historical reproduction is a read-only research aid. Keep it outside the
    # report inputs used for confidence, verdict, KB validation, and post gating.
    report_md = (report_md or "").rstrip() + "\n\n" + _historical_repro_section(
        platform, target, log_findings)
    report_md = (report_md or "").rstrip() + "\n\n" + _repro_vector_section(
        platform, target, log_findings, report_md)

    # Step 3 - WRITE-BACK
    _kb_state, _kb_eligible = _kb_validation_state(log_findings, comment_findings)
    if isinstance(kb_entry, dict):
        kb_entry["validation_state"] = _kb_state
        kb_entry["eligible_for_root_cause_recall"] = _kb_eligible
        # A comment-only (unvalidated) entry must never be stored as a confirmed cause.
        if not _kb_eligible and isinstance(kb_entry.get("root_cause"), dict):
            if kb_entry["root_cause"].get("confidence") == "confirmed":
                kb_entry["root_cause"]["confidence"] = "hypothesis"
    kb_action = kb.upsert(kb_entry) if kb_entry else {"action": "skipped"}

    # Provenance — the reference materials this analysis actually drew on, so the
    # report can show WHERE each failure-decode and next-step came from.
    sources = _collect_sources(
        target, recall, similar, log_findings, transferred,
        mcp_sources, axon_records, platform,
    )
    sources_md = _render_sources_md(sources)
    if sources_md:
        report_md = (report_md or "").rstrip() + "\n" + sources_md

    return {
        "mode": "llm" if llm.enabled else "offline",
        "hsdes_enabled": client.enabled,
        "family": platform,          # kept key name for UI compatibility
        "kb_recall": recall,
        "target": target,
        "similar": similar,
        "attachments": attachments,
        "attachments_fetched": fetched,
        "attachment_files": attach_files,
        "log_findings": log_findings,
        "comment_findings": comment_findings,
        "reference_hsds_used": [str(r.get("id") or "") for r in reference_hsds],
        "history_mode": auto_history,
        "transferred_sync": transferred,
        "mcp_sources": mcp_sources,
        "sources": sources,
        "axon_records": axon_records,
        "kb_action": kb_action,
        "report_markdown": report_md,
    }


def _md_section(md: str, header: str) -> str:
    """Return the body of a '## <header>' section from a report, or ''."""
    i = md.find(header)
    if i < 0:
        return ""
    j = md.find("\n## ", i + len(header))
    return md[i:(j if j >= 0 else len(md))].strip()


def _md_line(section: str, key: str) -> str:
    """Pull the value after a bold '**key:**' bullet within a section (the colon
    may sit inside or outside the bold markers)."""
    m = re.search(r"\*\*" + re.escape(key) + r":?\*\*[:：]?\s*(.+)", section)
    return _strip_md(m.group(1).strip()) if m else ""


def _strip_md(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    return text.strip()


def build_hsd_comment(result: Dict[str, Any]) -> str:
    """Condensed, HSDES-ready HTML RCA comment (verdict, owning IP, confidence,
    next steps) built from an analyze() result. Safe to post to the ticket thread."""
    md = result.get("report_markdown") or ""
    target = result.get("target") or {}
    hsd_id = str(target.get("id") or "")
    lf = result.get("log_findings") or {}
    decoded = lf.get("decoded") or {}
    mcs = (decoded.get("evidence") or {}).get("mc_status") or {}

    verdict_sec = _md_section(md, "## Engineer Verdict Audit")
    vtype = _md_line(verdict_sec, "Verdict type") or "see report"

    conf_sec = _md_section(md, "## Root-Cause Confidence")
    _cm = re.search(r"(\d{1,3})\s*%", conf_sec)
    conf_pct = _cm.group(1) if _cm else ""

    # Owning IP / primary error from the MCA Ownership section.
    own_sec = _md_section(md, "## MCA Ownership Analysis")
    primary = _md_line(own_sec, "PRIMARY_ERROR")
    owning_ip = mcs.get("bank_unit") or ""
    poison = _is_poison_consumption(mcs)

    # Ownership confidence band + suggested routing from the evidence ladder.
    ladder_sec = _md_section(md, "## Ownership Evidence Ladder")
    own_conf_full = _md_line(ladder_sec, "Ownership Confidence")
    own_conf = own_conf_full.split("—")[0].strip() if own_conf_full else ""
    suggested = _md_line(ladder_sec, "Suggested owner / routing") or _suggested_team(owning_ip)
    suggested = re.sub(r"\s*_\(.*?\)_\s*$", "", suggested).strip()
    owner_proven = "CONFIRMED" in vtype.upper() or own_conf.upper().startswith("HIGH")

    # RCA completeness + comment-thread cause (for the manager status indicator).
    _sm = re.search(r"RCA completeness:\s*(\d{1,3})\s*%", _md_section(md, "## RCA Scorecard"))
    completeness = _sm.group(1) if _sm else ""
    cf_root = (result.get("comment_findings") or {}).get("root_cause")

    # Present (✓) vs missing (✗) evidence — from the Verdict Audit, with the
    # Required-Missing-Data table as a fallback.
    def _split(s):
        return [x.strip() for x in re.split(r",|·|;", s or "")
                if x.strip() and x.strip().lower() not in ("_none_", "none")]
    present_items = _split(_md_line(verdict_sec, "Evidence directly proving root cause"))
    missing_items = _split(_md_line(verdict_sec, "Evidence missing"))
    if not missing_items:
        missing_items = re.findall(r"\|\s*\d+\s*\|\s*([^|]+?)\s*\|",
                                   _md_section(md, "## Required Missing Data"))

    # Highest-value next step from the Engineer Playbook.
    pb_sec = _md_section(md, "## Engineer Playbook")
    next_action = _md_line(pb_sec, "Highest-value next action")
    pb_command = _md_line(pb_sec, "Command")
    pb_gain = _md_line(pb_sec, "Confidence gain")
    pb_expected = _md_line(pb_sec, "Expected evidence")
    if not pb_expected:
        _exp, _cap = [], False
        for ln in pb_sec.splitlines():
            if "Expected outcomes" in ln:
                _cap = True
                continue
            if _cap:
                s = ln.strip()
                if s.startswith("- **"):
                    break
                cleaned = re.sub(r"^[\-•├└│\s]+", "", s)
                if cleaned:
                    _exp.append(cleaned)
        pb_expected = "; ".join(_exp[:3])

    mca_line = ""
    if mcs.get("status"):
        mca_line = (f"MCA bank {mcs.get('bank','?')} ({owning_ip}) "
                    f"{mcs.get('mcacod','')}/{mcs.get('mscod','')}").strip()

    # Manager-facing status indicator. A comment-thread claim (Tier-3) never marks
    # the ticket 'Root Cause Identified' on its own — only hardware ownership does.
    if owner_proven:
        status = "🟢 Root Cause Identified"
    elif mcs.get("status") or primary:
        status = "🟡 Investigation In Progress"
    else:
        status = "🔴 Insufficient Evidence"

    def esc(s):
        return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    R = []
    R.append("<b>NEXUS Automated Root-Cause Analysis</b>")
    R.append(f"<b>Status: {esc(status)}</b>"
             + (f" &middot; <b>RCA completeness {completeness}%</b>" if completeness else ""))
    R.append("<i>Auto-generated by HSDES NEXUS — deterministic decode of the ticket + "
             "attached logs. Verify before closing.</i>")

    R.append("<br/><b>Decoded Failure</b><ul>")
    if mca_line:
        R.append(f"<li>MCA Bank {esc(mcs.get('bank','?'))} ({esc(owning_ip or '?')}) — "
                 f"MCACOD {esc(mcs.get('mcacod','?'))} / MSCOD {esc(mcs.get('mscod','?'))}</li>")
        if mcs.get("decode"):
            R.append(f"<li>{esc(mcs['decode'])}</li>")
    else:
        R.append("<li>No decoded MCA — see full report.</li>")
    R.append("</ul>")

    R.append("<b>Ownership</b><ul>")
    R.append(f"<li>Current owner: {esc(owning_ip if (owner_proven and owning_ip) else 'Unknown')}</li>")
    if poison and owning_ip:
        R.append(f"<li>Victim: {esc(owning_ip)} (consumed the poison)</li>")
    if not owner_proven:
        src = ("Memory / IO-CXL / Uncore (read-return path)" if poison
               else (primary or "not yet proven"))
        R.append(f"<li>Suspected source: {esc(src)}</li>")
    if own_conf:
        R.append(f"<li>Ownership confidence: {esc(own_conf)}</li>")
    if suggested:
        R.append(f"<li>Suggested routing: {esc(suggested)}</li>")
    R.append("</ul>")

    R.append(f"<b>Verdict:</b> {esc(vtype)}"
             + (f" &middot; <b>Confidence {conf_pct}%</b>" if conf_pct else ""))

    if present_items or missing_items:
        R.append("<b>Why not higher?</b><ul>")
        for p in present_items[:5]:
            R.append(f"<li>&#10003; {esc(p)}</li>")
        for m in missing_items[:5]:
            R.append(f"<li>&#10007; {esc(m.strip())}</li>")
        R.append("</ul>")

    if next_action or pb_command:
        R.append("<b>Highest-Value Next Step</b><ul>")
        if next_action:
            R.append(f"<li>{esc(next_action)}</li>")
        if pb_command:
            R.append(f"<li>Command: <code>{esc(pb_command)}</code></li>")
        if pb_expected:
            R.append(f"<li>Expected: {esc(pb_expected)}</li>")
        if pb_gain:
            R.append(f"<li>Confidence gain: {esc(pb_gain)}</li>")
        R.append("</ul>")

    if hsd_id:
        R.append(f"<i>Full report: output/hsd_{esc(hsd_id)}_*.html / .md</i>")
    return "\n".join(R)


def _exec_summary_md(md: str) -> str:
    """One-screen Executive Summary (markdown bullets) built from the report's own
    gold sections — leads the report so an engineer/manager gets the answer fast."""
    verdict = _md_line(_md_section(md, "## Engineer Verdict Audit"), "Verdict type")
    conf_sec = _md_section(md, "## Root-Cause Confidence")
    _cm = re.search(r"(\d{1,3})\s*%", conf_sec)
    conf = _cm.group(1) if _cm else ""
    _sm = re.search(r"RCA completeness:\s*(\d{1,3})\s*%", _md_section(md, "## RCA Scorecard"))
    completeness = _sm.group(1) if _sm else ""

    ladder = _md_section(md, "## Ownership Evidence Ladder")
    own_conf = (_md_line(ladder, "Ownership Confidence").split("—")[0].strip())
    routing = re.sub(r"\s*_\(.*?\)_\s*$", "", _md_line(ladder, "Suggested owner / routing")).strip()
    owner_proven = "CONFIRMED" in verdict.upper() or own_conf.upper().startswith("HIGH")

    own_sec = _md_section(md, "## MCA Ownership Analysis")
    owner_line, unit = "", ""
    _row = re.search(r"\|\s*([^|]+?)\s*\|\s*(0x[0-9a-fA-F]+|—)\s*\|\s*(0x[0-9a-fA-F]+|—)\s*\|\s*([^|]+?)\s*\|",
                     own_sec)
    if _row:
        bank, mcacod, mscod, unit = (g.strip() for g in _row.groups())
        owner_line = f"MCA Bank {bank} ({unit}) — MCACOD {mcacod} / MSCOD {mscod}"
    primary = _md_line(own_sec, "PRIMARY_ERROR")

    va = _md_section(md, "## Engineer Verdict Audit")

    def _split(s):
        return [x.strip() for x in re.split(r",|·|;", s or "")
                if x.strip() and x.strip().lower() not in ("_none_", "none")]
    present = _split(_md_line(va, "Evidence directly proving root cause"))
    missing = _split(_md_line(va, "Evidence missing"))
    if not missing:
        missing = re.findall(r"\|\s*\d+\s*\|\s*([^|]+?)\s*\|",
                             _md_section(md, "## Required Missing Data"))

    pb = _md_section(md, "## Engineer Playbook")
    next_action = _md_line(pb, "Highest-value next action")
    cmd = _md_line(pb, "Command")
    gain = _md_line(pb, "Confidence gain")

    if not (verdict or owner_line or next_action):
        return ""  # nothing decoded — skip the exec summary

    if owner_proven:
        status = "🟢 Root Cause Identified"
    elif owner_line or primary:
        status = "🟡 Investigation In Progress"
    else:
        status = "🔴 Insufficient Evidence"
    if owner_proven:
        owner_disp = (f"{unit} (route: {routing})" if (unit and routing)
                      else unit or routing or "see report")
    else:
        owner_disp = f"Unknown — suspected routing {routing}" if routing else "Unknown"

    E = ["## Executive Summary", ""]
    E.append(f"**RCA Status:** {status}"
             + (f" — RCA completeness {completeness}%" if completeness else ""))
    E.append("")
    if owner_line:
        E.append(f"- **Failure:** {owner_line}")
    if verdict:
        E.append(f"- **Verdict:** {verdict}" + (f" — Confidence {conf}%" if conf else ""))
    E.append(f"- **Owner / routing:** {owner_disp}"
             + (f" · Ownership confidence {own_conf}" if own_conf else ""))
    if present or missing:
        _p = " ".join(f"✓ {x}" for x in present[:4])
        _m = " ".join(f"✗ {x.strip()}" for x in missing[:4])
        E.append(f"- **Why not higher?** {_p}" + (f"  —  {_m}" if _m else ""))
    if next_action:
        E.append(f"- **Highest-value next step:** {next_action}")
        if cmd:
            E.append(f"  - Command: `{cmd}`")
        if gain:
            E.append(f"  - Confidence gain: {gain}")
    E.append("")
    E.append("---")
    E.append("")
    return "\n".join(E)


def _prepend_exec_summary(md: str) -> str:
    summary = _exec_summary_md(md)
    return (summary + "\n" + md) if summary else md



def extract_ownership(result: Dict[str, Any]) -> Dict[str, Any]:
    """Pull the machine-readable ownership verdict from an analyze() result for
    benchmarking: owning IP, first-error source, verdict type, confidence %,
    ownership-confidence band, and suggested team."""
    md = result.get("report_markdown") or ""
    lf = result.get("log_findings") or {}
    ev = (lf.get("decoded") or {}).get("evidence") or {}
    mcs = ev.get("mc_status") or {}
    ierr = [r for r in ((lf.get("decoded") or {}).get("ierr_table") or [])
            if _ierr_has_source(r)]
    first_error = (ierr[0].get("source_unit") if ierr else "") or ""
    owning_ip = mcs.get("bank_unit") or first_error or ""
    verdict = _md_line(_md_section(md, "## Engineer Verdict Audit"), "Verdict type")
    ladder = _md_section(md, "## Ownership Evidence Ladder")
    own_conf = _md_line(ladder, "Ownership Confidence")
    conf_sec = _md_section(md, "## Root-Cause Confidence")
    m = re.search(r"(\d{1,3})\s*%", conf_sec)
    return {
        "owning_ip": owning_ip,
        "reporting_ip": mcs.get("bank_unit", "") or "",
        "bank": str(mcs.get("bank", "")) if mcs.get("bank") not in (None, "") else "",
        "socket": ((ev.get("socket_provenance") or {}).get("resolved_socket")
                   or (ev.get("sockets") or [""])[0]),
        "mcacod": mcs.get("mcacod", "") or "",
        "mscod": mcs.get("mscod", "") or "",
        "decoder_state": (mcs.get("decoder_ambiguity") or {}).get("state", ""),
        "first_error": first_error,
        "verdict": verdict,
        "confidence": int(m.group(1)) if m else 0,
        "ownership_confidence": own_conf,
        "suggested_team": _suggested_team(owning_ip),
        "contradiction": "## Contradiction Detector" in md,
    }


async def update_hsd_report(hsd_id: str, symptoms: str = "Automated triage",
                            dry_run: bool = True,
                            result: Optional[Dict[str, Any]] = None,
                            fetch_attachments: bool = True,
                            force: bool = False) -> Dict[str, Any]:
    """Run (or reuse) an analysis and post the condensed RCA as a ticket comment.
    When dry_run=True (default) nothing is written — the exact comment + payload
    are returned for review. A validation gate blocks auto-posting weak verdicts
    (WORKING HYPOTHESIS, or confidence < 70% with an unproven owner) unless
    force=True; a gated result returns the draft comment instead of posting."""
    hsd_id = re.sub(r"\D", "", str(hsd_id))
    if result is None:
        result = await analyze(hsd_id, symptoms, fetch_attachments=fetch_attachments)
    comment = build_hsd_comment(result)
    client = HSDESClient()
    meta = await client._article_meta(hsd_id)
    payload = client.build_comment_payload(hsd_id, comment, meta.get("tenant", "server_platf"))
    gate = _post_gate(result)
    if dry_run:
        return {"ok": True, "dry_run": True, "hsd_id": hsd_id,
                "comment_html": comment, "payload": payload,
                "gate": gate, "hsdes_enabled": client.enabled}
    if os.getenv("HSDES_WRITE_ENABLED", "false").lower() != "true":
        return {"ok": True, "dry_run": True, "draft_only": True, "hsd_id": hsd_id,
                "reason": "HSDES_WRITE_ENABLED is not set to true",
                "comment_html": comment, "payload": payload, "gate": gate,
                "hsdes_enabled": client.enabled}
    if not force and not gate["allow"]:
        return {"ok": False, "dry_run": False, "gated": True, "hsd_id": hsd_id,
                "reason": gate["reason"], "gate": gate,
                "comment_html": comment, "payload": payload}
    if not client.enabled:
        return {"ok": False, "dry_run": False, "hsd_id": hsd_id,
                "error": "HSDES not enabled (no auth configured)", "comment_html": comment}
    posted = await client.add_comment(hsd_id, comment, meta=meta)
    return {"ok": posted.get("ok", False), "dry_run": False, "hsd_id": hsd_id,
            "comment_html": comment, "payload": payload, "gate": gate,
            "error": posted.get("error"), "response": posted.get("response")}


def _post_gate(result: Dict[str, Any]) -> Dict[str, Any]:
    """Validation gate (Rec 6): auto-post only when the conclusion is strong.
    Allow if verdict is CONFIRMED/LIKELY with a proven owner, OR confidence >= 70%.
    Block WORKING HYPOTHESIS / low-confidence unproven-owner conclusions, AND block
    ANY report with an unresolved contradiction (draft-only until resolved, even at
    >= 70% confidence)."""
    md = result.get("report_markdown") or ""
    verdict = _md_line(_md_section(md, "## Engineer Verdict Audit"), "Verdict type").upper()
    ladder = _md_section(md, "## Ownership Evidence Ladder")
    owner_conf = _md_line(ladder, "Ownership Confidence").upper()
    conf_sec = _md_section(md, "## Root-Cause Confidence")
    m = re.search(r"(\d{1,3})\s*%", conf_sec)
    conf_pct = int(m.group(1)) if m else 0
    # The Contradiction Detector section is emitted ONLY when a contradiction was
    # found, so its presence is the signal (robust to emoji encoding).
    contradiction = "## Contradiction Detector" in md
    ambiguity = "AMBIGUOUS_DECODER" in md
    owner_proven = "CONFIRMED" in verdict or owner_conf.startswith("HIGH")
    if contradiction or ambiguity:
        return {"allow": False, "verdict": verdict, "confidence": conf_pct,
                "contradiction": contradiction, "ambiguity": ambiguity,
                "reason": "auto-post blocked — unresolved decoder ambiguity or contradiction; "
                          "draft only until resolved"}
    if owner_proven or conf_pct >= 70:
        return {"allow": True, "verdict": verdict, "confidence": conf_pct,
                "contradiction": False,
                "reason": "strong conclusion (proven owner or confidence ≥ 70%)"}
    reason = ("verdict is WORKING HYPOTHESIS" if "HYPOTHESIS" in verdict
              else f"confidence {conf_pct}% < 70% and owner not proven")
    return {"allow": False, "verdict": verdict, "confidence": conf_pct,
            "contradiction": False,
            "reason": f"auto-post blocked — {reason}; posting as draft for review"}



async def _llm_report(hsd_id, symptoms, platform, recall, target, similar,
                      hsdes_enabled, log_findings=None,
                      comment_findings=None, transferred=None) -> Tuple[str, Dict[str, Any]]:
    context = {
        "input": {"hsd_id": hsd_id, "symptoms": symptoms, "platform": platform},
        "kb_recall": recall,
        "target_hsd": target,
        "similar_hsds": similar,
        "attached_log_findings": log_findings,
        "comment_investigation": comment_findings,
        "transferred_ticket_sync": transferred,
    }
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "CONTEXT:\n" + json.dumps(context, indent=2)},
    ]
    raw = await llm.chat(messages)
    parsed = _extract_json(raw)
    if parsed and "report_markdown" in parsed:
        return parsed["report_markdown"], parsed.get("kb_entry") or _fallback_entry(
            hsd_id, symptoms, platform, target, hsdes_enabled, comment_findings
        )
    return raw, _fallback_entry(hsd_id, symptoms, platform, target, hsdes_enabled,
                                comment_findings)


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n|\n```$", "", text).strip()
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


def _kb_validation_state(log_findings: Optional[Dict[str, Any]],
                         comment_findings: Optional[Dict[str, Any]]) -> Tuple[str, bool]:
    """KB validation state (Part 10): a self-analyzed ticket is never stored as a
    validated root cause. Comment claims are UNVALIDATED; machine-decoded evidence
    is at most MACHINE_SUPPORTED. Only curated/fix-validated outcomes (set out of
    band) are eligible for root-cause recall. Returns (state, eligible)."""
    lf = log_findings or {}
    ev = (lf.get("decoded") or {}).get("evidence") or {}
    mcs = ev.get("mc_status") or {}
    ierr = [r for r in ((lf.get("decoded") or {}).get("ierr_table") or [])
            if _ierr_has_source(r)]
    has_machine = bool(mcs.get("status")) or (lf.get("lines_scanned") or 0) > 0
    owner_proven = bool(ierr) and not _is_poison_consumption(mcs)
    cf = comment_findings or {}
    if not has_machine:
        state = "OBSERVATION_ONLY"
    elif owner_proven:
        state = "MACHINE_SUPPORTED"
    elif cf.get("root_cause"):
        state = "UNVALIDATED_HYPOTHESIS"
    elif mcs.get("status"):
        state = "MACHINE_SUPPORTED"
    else:
        state = "OBSERVATION_ONLY"
    # Nothing produced by automated analysis alone is eligible for validated
    # root-cause recall — that requires curation or fix/repro validation.
    eligible = state in ("VALIDATED_ROOT_CAUSE", "FIX_VALIDATED", "CURATED_GOLDEN_CASE")
    return state, eligible


def _fallback_entry(hsd_id, symptoms, platform, target, hsdes_enabled,
                    comment_findings=None) -> Dict[str, Any]:
    from time import gmtime, strftime
    target = target or {}
    ticket_text = target.get("full_text") or target.get("description") or ""
    error_string = (symptoms + ("\n" + ticket_text if ticket_text else "")).strip()
    domains = [d for d, _ in _detect_domains(error_string)]
    findings = _extract_findings(target, comment_findings)
    return {
        "signature": {
            "family": platform or target.get("family") or "",
            "platform": platform or target.get("family") or "",
            "stepping": target.get("stepping", ""),
            "domain": ", ".join(domains[:3]),
            "component": target.get("component", ""),
            "error_string": error_string[:2000],
            "key_terms": normalize_terms(f"{symptoms} {target.get('title', '')}"),
        },
        "similar_hsds": [],
        "root_cause": {"text": findings["root_cause"], "confidence": findings["confidence"]},
        "debug_steps": [],
        "resolution": {"text": findings["resolution"],
                       "source_hsd": hsd_id if target.get("title") else ""},
        "provenance": {
            "source": "HSDES" if hsdes_enabled else "KB",
            "timestamp": strftime("%Y-%m-%dT%H:%M:%SZ", gmtime()),
            "confidence_tag": "Medium" if target.get("full_text") else "Low",
        },
    }


_VALID_FIXED_REASONS = {"fix_available", "implemented", "validated", "verified",
                        "fix_integrated", "fix_in_validation"}


def _validate_root_cause(cf: Optional[Dict[str, Any]],
                         target: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Grade HOW trustworthy the extracted root cause is — instead of trusting the
    words 'root cause'. Checks provenance (HSDES field vs pasted comment vs AI
    analysis), workflow corroboration, a recorded fix, and author authority, then
    returns a verdict (VALIDATED / PLAUSIBLE / UNVALIDATED HYPOTHESIS) + how to
    validate it."""
    cf = cf or {}
    rc = cf.get("root_cause") or ""
    if not rc:
        return None
    rec = (target or {}).get("raw", {}) or {}

    def gf(*names: str) -> str:
        for n in names:
            for k, v in rec.items():
                if v and (k == n or k.endswith("." + n)):
                    return str(v)
        return ""

    source = cf.get("root_cause_source") or "comment_statement"
    status = ((target or {}).get("status") or "").lower()
    reason = gf("reason").lower()
    owner = ((target or {}).get("owner") or "").lower()
    rc_author = (cf.get("root_cause_author") or "").lower()
    field_rc = gf("root_cause", "fix_description")
    fix_id = gf("fix_id", "fix_build")

    provenance_key = "hsdes_field" if field_rc else source
    _PROV = {
        "hsdes_field": "HSDES structured root_cause / fix_description field (engineer-filled)",
        "labeled_section": "a labeled 'ROOT CAUSE' section pasted into a comment",
        "ai_analysis": "a pasted AI/tool analysis in a comment (a hypothesis, not confirmed)",
        "resolution": "a closure / resolution statement in the comment thread",
        "comment_statement": "an engineer's statement in the comment thread",
    }

    checks: List[tuple] = []
    score = 0
    if field_rc:
        checks.append(("Root cause is filled in the HSDES structured field", True))
        score += 2
    else:
        checks.append(("HSDES structured root_cause field is EMPTY — the claim lives "
                       "only in a comment", False))
    if status in ("closed", "complete", "verified", "resolved") or reason in _VALID_FIXED_REASONS:
        checks.append((f"Ticket workflow corroborates it (status/reason: "
                       f"{status or reason})", True))
        score += 2
    else:
        checks.append((f"Ticket is still '{status or 'open'}' — the workflow has not "
                       "confirmed a root cause", False))
    if fix_id:
        checks.append((f"A fix ingredient / revision is recorded ({fix_id})", True))
        score += 1
    else:
        checks.append(("No fix ingredient / revision recorded yet", False))
    if rc_author and owner and (rc_author in owner or owner in rc_author):
        checks.append((f"Stated by the ticket owner ({cf.get('root_cause_author')})", True))
        score += 1
    elif rc_author:
        checks.append((f"Stated by {cf.get('root_cause_author')} — not the ticket owner", False))
    if provenance_key == "ai_analysis":
        checks.append(("Source is an AI/tool analysis — treat as an unvalidated hypothesis",
                       False))
        score -= 1
    if cf.get("workaround"):
        checks.append(("A candidate fix / workaround is proposed (not yet proven)", True))

    if field_rc and score >= 3:
        verdict = "VALIDATED"
    elif provenance_key == "ai_analysis" or score <= 1:
        verdict = "UNVALIDATED HYPOTHESIS"
    else:
        verdict = "PLAUSIBLE — needs confirmation"

    todo: List[str] = []
    if provenance_key == "ai_analysis":
        todo.append("Treat the pasted AI analysis as a hypothesis — have the owning "
                    "engineer confirm or reject it.")
    if not field_rc:
        todo.append("Ask the owner to record the confirmed cause in the HSDES "
                    "`root_cause` field once proven.")
    todo.append("Reproduce the failure and confirm the claimed mechanism on hardware "
                "(check the exact registers / values / structures named in the cause).")
    if cf.get("workaround"):
        todo.append("Apply the proposed fix and re-run the benchmark/test to prove the "
                    "measured delta actually closes.")

    return {"verdict": verdict, "provenance": _PROV.get(provenance_key, provenance_key),
            "provenance_key": provenance_key, "checks": checks, "score": score, "todo": todo}


def _render_investigation_timeline(L: List[str], cf: Dict[str, Any]) -> None:
    """Concise summary of the comment thread (NOT a full reproduction): a compact
    per-comment timeline, the few decisive pieces of evidence, the converged root
    cause and the disposition."""
    narrative = (cf or {}).get("narrative") or []
    if not narrative:
        return
    _KIND_ICON = {"root_cause": "🎯", "workaround": "🛠️", "finding": "🔎",
                  "action": "🔧", "next_step": "➡️", "note": "•"}
    L.append("## Investigation Summary (from ticket comments)")
    L.append("")
    # Compact timeline — one line per comment.
    for ev in narrative:
        dg = ev.get("digest") or {}
        icon = _KIND_ICON.get(ev.get("kind"), "•")
        who = _short(ev.get("author", ""), 18)
        tag = f" ({dg['tag']})" if dg.get("tag") else ""
        L.append(f"{ev['seq']}. {icon} **{who}{tag}:** {_short(ev.get('text', ''), 200)}")
    L.append("")

    # Only the decisive evidence, aggregated + de-duplicated across the thread.
    regs: List[str] = []
    cmds: List[str] = []
    n_exp = 0
    for ev in narrative:
        dg = ev.get("digest") or {}
        for r in dg.get("registers", []):
            if r not in regs:
                regs.append(r)
        for c in dg.get("commands", []):
            if c not in cmds:
                cmds.append(c)
        n_exp += len(dg.get("experiments", []))
    if regs or cmds or n_exp:
        L.append("**Key evidence:**")
        if regs:
            L.append("- Register / state: " + " · ".join(f"`{_short(r, 60)}`" for r in regs[:5]))
        if cmds:
            L.append("- Repro: " + " · ".join(f"`{_short(c, 70)}`" for c in cmds[:2]))
        if n_exp:
            L.append(f"- {n_exp} pass/fail experiment(s) recorded (full matrix in appendix).")
        L.append("")

    if cf.get("root_cause"):
        who = cf.get("root_cause_author") or "ticket"
        L.append(f"**Engineer observation (per {who}, from comment thread — NOT independently "
                 f"verified):** {_short(cf['root_cause'], 400)}")
        L.append("- _Evidence type: human claim (Tier-3). Treated as an investigation signal, "
                 "not proof of root cause — confidence contribution: 0% until hardware evidence "
                 "validates it._")
        L.append("")
    disp = f"**📌 Disposition:** {cf.get('status_hint', 'unknown')}"
    if cf.get("handoff_team"):
        disp += f" — next owner: **{_short(cf['handoff_team'], 40)}**"
    L.append(disp)
    L.append("")


# Ticket statuses that mean the sighting is already dispositioned (not an active crash).
_RESOLVED_STATUSES = {
    "rejected", "closed", "duplicate", "implemented", "complete", "completed",
    "verified", "fixed", "resolved", "wont-fix", "won't fix", "not_a_bug", "invalid",
}
# Title/subject cues that a ticket is functional / reporting / config — not a hardware crash.
_FUNCTIONAL_HINTS = re.compile(
    r"not displaying|display|info table|dimm info|enumerat|non[- ]?por|population|"
    r"down[- ]?clock|downclocking|frequenc|\b\d{3,4}\s*mts\b|reporting|cosmetic|"
    r"boots successfully|knob|mapped out|does not show|not shown|incorrectly shown",
    re.I)


def _mca_is_incidental(target: Optional[Dict[str, Any]],
                       log_findings: Optional[Dict[str, Any]],
                       cf: Optional[Dict[str, Any]]) -> Tuple[bool, str]:
    """Decide whether a decoded MCA is incidental background telemetry rather than
    the ticket's real subject. True when the system booted to OS AND (the ticket is
    already dispositioned OR its subject is a functional/config/display topic), and
    no hardware root cause converged in the comment thread."""
    decoded = (log_findings or {}).get("decoded") or {}
    if not decoded.get("mca"):
        return (False, "")
    if not (decoded.get("boot_flow") or {}).get("reached_os"):
        return (False, "")
    if (cf or {}).get("root_cause"):
        return (False, "")  # comments already converged — handled on that path
    status = str((target or {}).get("status") or "").strip().lower()
    title = str((target or {}).get("title") or "")
    reasons: List[str] = []
    if status in _RESOLVED_STATUSES:
        reasons.append(f"ticket status '{status}'")
    if _FUNCTIONAL_HINTS.search(title):
        reasons.append("subject is a functional/config/display topic")
    if not reasons:
        return (False, "")
    return (True, " + ".join(reasons))


def _demoted_primary_line(target: Optional[Dict[str, Any]], cf: Optional[Dict[str, Any]]) -> str:
    """Lead line when the MCA is demoted: disposition + reported subject + last
    recorded conclusion from the comment thread (if any)."""
    status = str((target or {}).get("status") or "").strip().lower()
    title = _short(str((target or {}).get("title") or ""), 220)
    parts: List[str] = []
    if status:
        parts.append(f"Ticket dispositioned as **{status}**.")
    parts.append(f"Reported subject: {title}.")
    last_step = ((cf or {}).get("next_steps") or [None])[-1]
    if last_step:
        parts.append(f"Last thread note: {_short(last_step, 200)}.")
    parts.append("The decoded machine-check is **incidental background telemetry** "
                 "(system booted to OS) — not the reported failure.")
    return " ".join(parts)


def _render_debug_summary(L: List[str], hsd_id: str, target: Dict[str, Any],
                          log_findings: Optional[Dict[str, Any]],
                          cf: Dict[str, Any], rc_validation: Optional[Dict[str, Any]],
                          symptoms: str) -> None:
    """HSLE-Debug-Agent-style structured summary: RESULT + boot/stage progress +
    Symptom / Data Analysis / Metrics / Evidence / Hypothesis / Conclusion /
    Next Actions — driven by the decoded log evidence."""
    lf = log_findings or {}
    decoded = lf.get("decoded") or {}
    boot = decoded.get("boot_flow")
    sigs = lf.get("signatures", []) or []
    if not (decoded.get("mca") or decoded.get("bios") or decoded.get("post") or sigs or boot):
        return  # nothing decoded — the plain Findings Summary already covers it

    def tv(k, d="?"):
        return target.get(k) if target.get(k) else d

    # When the comment thread has already converged on a root cause, the broad
    # log-scan signatures (WHEA/MCA/PCIe from a verbose serial log) are incidental
    # background telemetry — lead with the real cause, not the noise.
    has_comment_rc = bool(cf.get("root_cause"))
    mca_demoted, demote_why = _mca_is_incidental(target, log_findings, cf)
    # Both cases mean the decoded MCA is background telemetry, not the headline.
    mca_incidental = has_comment_rc or mca_demoted

    # ---- RESULT line ----
    fail_where = ""
    if boot and boot.get("failing_stage"):
        fail_where = f"stopped before {boot['failing_stage']['label']}"
    elif boot and boot.get("last_reached"):
        fail_where = f"last reached {boot['last_reached']['label']}"
    top_fatal = next((s for s in sigs if s["severity"] == "fatal"), sigs[0] if sigs else None)
    sig_txt = (f"{top_fatal['label']} (x{top_fatal['count']})" if top_fatal else "")
    if has_comment_rc:
        result = " · ".join(filter(None, ["**FAIL**", fail_where,
                                          "root cause converged in comment thread"])) or "**REVIEW**"
    elif mca_demoted:
        _disp = str(tv('status', '')).strip().lower()
        result = " · ".join(filter(None, [
            "**REVIEW**", fail_where or "booted to OS",
            f"dispositioned ({_disp})" if _disp else "functional/config subject",
            "decoded MCA is incidental"]))
    else:
        result = " · ".join(filter(None, ["**FAIL**", fail_where, sig_txt])) or "**REVIEW**"

    L.append("## 🔧 Debug Summary")
    L.append(f"**RESULT:** {result}")
    L.append("")

    # ---- Boot / Stage Progress (Golden Flow) ----
    if boot and boot.get("stages"):
        L.append("### Boot / Stage Progress")
        L.append("| Stage | Status | Evidence |")
        L.append("|-------|--------|----------|")
        last_key = (boot.get("last_reached") or {}).get("key")
        fail_key = (boot.get("failing_stage") or {}).get("key")
        for s in boot["stages"]:
            if s["reached"]:
                mark = "✅ reached"
                if s["key"] == last_key:
                    mark = "✅ last reached"
            elif s["key"] == fail_key:
                mark = "❌ **did not start**"
            else:
                mark = "— not reached"
            ev_cell = _short(s.get("evidence", ""), 40).replace("|", "\\|") or "—"
            L.append(f"| {s['label']} | {mark} | {ev_cell} |")
        if boot.get("failure_markers"):
            L.append("")
            L.append(f"**Failure markers in log:** {', '.join(boot['failure_markers'])}")
        L.append("")

    # ---- Symptom ----
    L.append("### Symptom")
    L.append(f"- {_short(tv('title',''), 200)}")
    if symptoms:
        L.append(f"- Reported: {_short(symptoms, 160)}")
    L.append("")

    # ---- Data Analysis & Metrics ----
    L.append("### Data Analysis & Metrics")
    L.append(f"- **Log volume:** {lf.get('lines_scanned', 0):,} lines scanned")
    if sigs:
        _noise = (" — ⚠️ incidental background telemetry, NOT the reported failure"
                  if mca_incidental else "")
        L.append("- **Log keyword mentions** (raw count of matching log lines across the whole "
                 "log — inflated by verbose PythonSV/serial register dumps; **not** distinct "
                 "hardware events): " + " · ".join(
            f"{s['label']} (x{s['count']})" for s in sigs[:5]) + _noise)
    if decoded.get("mca"):
        mc = decoded["mca"]
        L.append(f"- **MCA:** {mc['count']} status value(s), "
                 f"{'UNCORRECTED' if mc['uncorrected'] else 'corrected'} — "
                 f"{mc.get('headline') or 'see appendix'}")
    if decoded.get("bios") and decoded["bios"].get("count"):
        bd = decoded["bios"]
        L.append(f"- **BIOS log codes:** {bd['count']} ({'FATAL' if bd['fatal'] else 'warning'})")
    if decoded.get("post"):
        last = decoded["post"]["codes"][-1]
        L.append(f"- **Last POST checkpoint:** `{last.get('code','')}` "
                 f"({last.get('description') or last.get('macro','')})")
        _pv = _post_verdict(decoded, target)
        if _pv:
            L.append(f"- **POST-code meaning &amp; HW verdict:** {_pv}")
    L.append("")

    # ---- Evidence ----
    ev: List[str] = []
    _ierr_ev = (decoded.get("ierr_table") or []) if decoded else []
    for row in _ierr_ev[:4]:
        ev.append(f"PythonSV UBOX: Socket{row['socket']} **{row['type']}** {row['priority']} "
                  f"← `{row['source_unit']}`"
                  + (f" @ `{row['address']}`" if row.get("address") else ""))
    for d in (lf.get("mca_decode") or [])[:1]:
        ev.append(f"MCA `{d['status']}` → {d.get('mcacod_text','?')} "
                  f"(flags {', '.join(d['flags']) or 'none'})")
    for e in (lf.get("evidence") or [])[:2]:
        for ln in e.get("lines", [])[:1]:
            ev.append(f"{e['category']}: `{_short(ln, 90)}`")
    if decoded and decoded.get("mca") and decoded["mca"].get("action"):
        _mca_act = _strip_intel_contact(decoded["mca"]["action"])
        if _mca_act:
            ev.append(f"Recommended action (MCA DB): {_short(_mca_act, 160)}")
    _axon_sigs_ev = (target.get("axon_svtools_signatures") or []) if target else []
    if _axon_sigs_ev:
        ev.append(f"Axon SVTools: {' · '.join(_axon_sigs_ev[:3])}")
    if ev:
        L.append("### Evidence")
        for e in ev:
            L.append(f"- {e}")
        L.append("")

    # ---- Hypothesis / Root Cause ----
    L.append("### Hypothesis / Root Cause")
    # Priority: a converged engineer statement in the comment thread is the
    # authoritative cause; precise PythonSV IERR / Axon SVTools corroborate it;
    # broad decoded MCA is only a fallback when nothing else converged.
    ierr_rows = (decoded.get("ierr_table") or []) if decoded else []
    axon_sigs = (target.get("axon_svtools_signatures") or []) if target else []
    if cf.get("root_cause"):
        tag = rc_validation["verdict"] if rc_validation else "reported"
        L.append(f"- (**converged from comment thread**, {tag}) {_short(cf['root_cause'], 320)}")
    elif mca_demoted:
        L.append(f"- (**reported subject / disposition** — {demote_why}) "
                 f"{_demoted_primary_line(target, cf)}")
    _spec_rc = None
    if not cf.get("root_cause") and not mca_demoted:
        _spec_rc = _specific_root_cause(decoded, target)
        if _spec_rc:
            L.append(f"- (**narrowed from decoded evidence**) {_spec_rc}")
    if ierr_rows:
        first_ierr = ierr_rows[0]
        L.append(f"- (**IERR from PythonSV UBOX table**) "
                 f"Socket {first_ierr['socket']} — {first_ierr['type']} {first_ierr['priority']} "
                 f"from **{first_ierr['source_unit']}**"
                 + (f" @ `{first_ierr['address']}`" if first_ierr.get("address") else ""))
    if axon_sigs:
        L.append("- (**Axon SVTools failure signatures from the linked recording:**)")
        for s in axon_sigs[:5]:
            L.append(f"  - `{s}`")
    if not cf.get("root_cause") and not ierr_rows and not axon_sigs and not _spec_rc:
        if mca_demoted:
            pass  # already led with the disposition/subject line above
        elif decoded and decoded.get("hypotheses"):
            top = decoded["hypotheses"][0]
            L.append(f"- (evidence-based, {top['severity']}) {_short(top['text'], 260)}")
        else:
            L.append("- Not yet determined — collect stronger runtime evidence (see Next Actions).")
    L.append("")

    # ---- Conclusion ----
    L.append("### Conclusion")
    concl = []
    if boot and boot.get("failing_stage"):
        concl.append(f"Boot did not progress past **{boot['last_reached']['label']}** "
                     f"(next expected: {boot['failing_stage']['label']}).")
    elif boot and boot.get("reached_os"):
        concl.append("System **booted to OS** — this is a **runtime / post-boot** failure, "
                     "not a boot hang.")
    if decoded.get("mca") and decoded["mca"]["uncorrected"]:
        if has_comment_rc:
            concl.append(f"An uncorrected machine-check was also decoded "
                         f"({decoded['mca'].get('headline','')}) — this is **hardware evidence**. "
                         "The comment thread proposes a cause (see the engineer observation "
                         "above), but that is an unverified human claim; correlate it against "
                         "this MCA before concluding — the MCA may be the real failure or a "
                         "related symptom.")
        elif mca_demoted:
            concl.append(f"An uncorrected machine-check was decoded "
                         f"({decoded['mca'].get('headline','')}), but it is **incidental "
                         "background telemetry** — this ticket is a "
                         f"{'dispositioned' if str(tv('status','')).strip().lower() in _RESOLVED_STATUSES else 'functional/config'} "
                         "item (see reported subject above), not a machine-check crash.")
        else:
            concl.append(f"An **uncorrected machine-check** was decoded "
                         f"({decoded['mca'].get('headline','')}), consistent with the reported failure.")
    if not concl:
        concl.append("Failure isolated to the dominant decoded signature; confirm on hardware.")
    for c in concl:
        L.append(f"- {c}")
    L.append("")

    # ---- Next Actions ----
    L.append("### Next Actions")
    na: List[str] = []
    # Lead with IP-specific reads derived from the decoded bank/unit; the generic
    # MCA-DB action is kept only as a labelled reference.
    for s in _specific_next_steps(decoded):
        na.append(s)
    if decoded.get("mca") and decoded["mca"].get("action"):
        _dbact = _strip_intel_contact(decoded["mca"]["action"])
        if _dbact:
            na.append(f"(MCA-DB reference) {_short(_dbact, 160)}")
    if boot and boot.get("failing_stage"):
        na.append(f"Inspect the BIOS/firmware path entering "
                  f"{boot['failing_stage']['label']} (right after the last checkpoint).")
    if decoded.get("bios") and decoded["bios"]["fatal"]:
        na.append("Decode the FATAL BIOS/RC error(s) in Appendix A3 and map to the failing IP.")
    na.append("Confirm the decoded root cause on hardware; capture MCA bank + RIP.")
    for i, s in enumerate(dict.fromkeys([x for x in na if x and x.strip()]), 1):
        L.append(f"{i}. {s}")
    L.append("")
    L.append("---")
    L.append("")


def _render_transferred(L: List[str], transferred: Optional[Dict[str, Any]]) -> None:
    """Render the transferred-ticket sync block (sub-team findings + a prepared,
    ready-to-post update comment) into the report line buffer ``L``."""
    if not transferred or not transferred.get("summaries"):
        return
    L.append("## 🔁 Transferred-Ticket Sync")
    L.append("")
    L.append("This sighting references a sub-team ticket. Latest findings pulled "
             "from the transferred ticket(s) below — review, then post the "
             "prepared comment back on this sighting.")
    L.append("")
    L.append("| Transferred HSD | Status | Fix? | Domain | Ingredient / Revision |")
    L.append("|-----------------|--------|------|--------|-----------------------|")
    for s in transferred["summaries"]:
        if s.get("error"):
            L.append(f"| {s.get('id','?')} | _fetch error_ | — | — | — |")
            continue
        fix = "✅" if s.get("fixed") else "—"
        status = _short(f"{s.get('status','?')} ({s.get('reason','?')})", 40)
        dom = _short(s.get("domain") or "—", 24)
        ing = _short(s.get("ingredient") or "—", 30)
        L.append(f"| {s.get('id','?')} | {status} | {fix} | {dom} | {ing} |")
    L.append("")
    for s in transferred["summaries"]:
        if s.get("error"):
            continue
        if s.get("root_cause"):
            L.append(f"- **{s['id']} root cause:** {_short(s['root_cause'], 300)}")
        if s.get("new_axon_uuids"):
            L.append(f"- **{s['id']} new Axon recording(s):** "
                     + ", ".join(s["new_axon_uuids"][:4]))
    L.append("")
    for s in transferred["summaries"]:
        cm = s.get("comment_markdown")
        if not cm:
            continue
        L.append(f"<details><summary>📋 Prepared update comment for sighting "
                 f"(from {s['id']}) — copy &amp; post on HSDES</summary>")
        L.append("")
        L.append("```markdown")
        L.append(cm)
        L.append("```")
        L.append("")
        L.append("</details>")
        L.append("")


def _extract_versions(target: Dict[str, Any]) -> Dict[str, str]:
    """Best-effort pull of BIOS / uCode / IFWI / BMC versions from the ticket text.
    Only accepts version-like tokens (must contain a digit and not be a bare column
    header word), so a headerless spec table doesn't yield label words as values."""
    text = (target or {}).get("full_text", "") or (target or {}).get("description", "") or ""
    _bad = {"microcode", "ucode", "stepping", "biosversion", "bmcversion", "bmc",
            "kernel", "version", "qdf", "memory", "config", "cpld", "pipeline",
            "ttf", "node", "bios", "ifwi", "details", "affected", "system"}
    pats = {
        "BIOS": r"(?i)bios[\s_]*version\s*[:=]?\s*([A-Za-z0-9][A-Za-z0-9._\-]{5,})",
        "uCode": r"(?i)(?:microcode|ucode)\s*[:=]?\s*(0x[0-9A-Fa-f]+|[0-9][0-9A-Za-z._\-]{2,})",
        "IFWI": r"(?i)ifwi(?:\s*version)?\s*[:=]?\s*([0-9A-Za-z][0-9A-Za-z._\-]{3,})",
        "BMC": r"(?i)bmc\s*version\s*[:=]?\s*([0-9A-Za-z][0-9A-Za-z._\-]{3,})",
    }
    out: Dict[str, str] = {}
    for label, pat in pats.items():
        for m in re.finditer(pat, text):
            val = m.group(1).strip()
            if val.lower() in _bad or not re.search(r"\d", val):
                continue  # skip label-word / non-version captures
            out[label] = val
            break
    return out


def _audit_root_cause_evidence(target: Dict[str, Any],
                               log_findings: Optional[Dict[str, Any]],
                               recall: Dict[str, Any],
                               similar: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Audit the 10 evidence items that separate a generic triage line from an
    engineer-grade root cause. Each item carries the concrete commands to collect
    it. Item: {label, present, detail, collect, commands}."""
    lf = log_findings or {}
    decoded = lf.get("decoded") or {}
    ev = decoded.get("evidence") or {}
    mca = decoded.get("mca") or {}
    versions = _extract_versions(target)
    axon_sigs = (target or {}).get("axon_svtools_signatures") or []
    sim = similar or []
    _socket_info = ev.get("socket_provenance") or {}
    _socket = _socket_info.get("resolved_socket")
    _sv_socket = f"socket{_socket}" if _socket is not None else "socket<N>  # resolve from socket provenance"

    # Resolve the implicated MCA bank so MC_ADDR/MC_MISC MSR offsets are exact.
    bank_n: Optional[int] = None
    for b in (ev.get("mca_banks") or []):
        try:
            bank_n = int(b)
            break
        except (TypeError, ValueError):
            continue
    if bank_n is None:
        _b = str((ev.get("mc_status") or {}).get("bank") or "")
        if _b.isdigit():
            bank_n = int(_b)

    def item(label, present, detail="", collect="", commands=None):
        return {"label": label, "present": bool(present),
                "detail": detail if present else "", "collect": collect,
                "commands": [] if present else (commands or [])}

    audit: List[Dict[str, Any]] = []

    # 1. MCA bank number
    banks = ev.get("mca_banks") or []
    audit.append(item("MCA Bank Number", banks,
                      ("bank(s) " + ", ".join(banks)) if banks else "",
                      "enumerate the machine-check banks and identify the raising IP block",
                      ["rdmsr -a 0x179  # IA32_MCG_CAP → bank count (OS)",
                       "for N in $(seq 0 31); do echo bank $N; rdmsr -a $((0x401+4*N)); done",
                       "sv.sockets.uncore.mca.dump()  # PythonSV — all banks"]))

    # 2. MC_STATUS / MCACOD / MSCOD (+ flags)
    mcs = ev.get("mc_status") or {}
    have_status = bool(mca) or bool(mcs.get("mscod") or mcs.get("mcacod"))
    flags = ev.get("status_flags") or {}
    flag_txt = (" · flags " + " ".join(k for k, v in flags.items() if v)) if flags else ""
    detail2 = ""
    if have_status:
        detail2 = (" ".join(filter(None, [
            f"bank {mcs.get('bank')}" if mcs.get("bank") else "",
            f"MCACOD {mcs.get('mcacod')}" if mcs.get("mcacod") else "",
            f"MSCOD {mcs.get('mscod')}" if mcs.get("mscod") else "",
            f"= {mcs.get('decode')}" if mcs.get("decode") else (
                f"= {mca.get('headline')}" if mca.get("headline") else ""),
        ])).strip() + flag_txt)
    _sbank = f"$((0x401+4*{bank_n}))" if bank_n is not None else "0x401+4*N"
    audit.append(item("MC_STATUS / MCACOD / MSCOD", have_status, detail2,
                      "capture the full 64-bit MCi_STATUS (VAL/UC/PCC/ADDRV/MISCV + MCACOD/MSCOD)",
                      [f"rdmsr -a {_sbank}  # MC{bank_n if bank_n is not None else 'N'}_STATUS (OS)",
                       f"sv.{_sv_socket}.uncore.mca.dump()  # PythonSV — decode MCACOD/MSCOD + flags"]))

    # 3. MC_ADDR
    _addr = f"0x{0x402 + 4*bank_n:X}" if bank_n is not None else "0x402+4*N"
    audit.append(item("MC_ADDR (transaction address)", ev.get("mc_addr"),
                      ev.get("mc_addr", ""),
                      "read MCi_ADDR when ADDRV=1 to locate the offending address/transaction",
                      [f"rdmsr -a {_addr}  # MC{bank_n if bank_n is not None else 'N'}_ADDR (OS)",
                       f"sv.{_sv_socket}.uncore.mca.dump()  # PythonSV — MCi_ADDR field"]))

    # 4. MC_MISC
    _misc = f"0x{0x403 + 4*bank_n:X}" if bank_n is not None else "0x403+4*N"
    audit.append(item("MC_MISC (transaction detail)", ev.get("mc_misc"),
                      ev.get("mc_misc", ""),
                      "read MCi_MISC when MISCV=1 for request type / source / channel hints",
                      [f"rdmsr -a {_misc}  # MC{bank_n if bank_n is not None else 'N'}_MISC (OS)",
                       f"sv.{_sv_socket}.uncore.mca.dump()  # PythonSV — MCi_MISC field"]))

    # 5. RC-Fatal source agent
    audit.append(item("RC-Fatal / EWL Source Agent", ev.get("rc_fatal_agent"),
                      ev.get("rc_fatal_agent", ""),
                      "capture the RC-Fatal 'Agent =' / originating IP (e.g. IIO Stack 0, UPI Agent 0)",
                      ["grep -iE 'RC_FATAL|FATAL ERROR|Agent *=|MajorCode|MinorCode' <bios_serial.log>",
                       "python -m app.decoders.decode_ewl --log <bios_serial.log>"]))

    # 6. BIOS module / phase at failure
    audit.append(item("BIOS Module / Phase at Failure", ev.get("bios_module"),
                      ev.get("bios_module", ""),
                      "map the failing POST checkpoint to the BIOS phase + module (DXE / CpuSv / Host Interface)",
                      ["capture the POST/checkpoint code at the hang (BMC postcode buffer / port 80h)",
                       "grep -iE 'POST|checkpoint|DXE|PEI|BDS' <bios_serial.log> | tail -40"]))

    # 7. Versions
    audit.append(item("BIOS / uCode / IFWI / BMC Versions", versions,
                      ", ".join(f"{k}={v}" for k, v in versions.items()) if versions else "",
                      "record BIOS / uCode / IFWI / BMC versions to enable regression (first-fail) detection",
                      ["rdmsr 0x8B  # IA32_BIOS_SIGN_ID → uCode rev (OS)",
                       "dmidecode -t bios  # BIOS version",
                       "ipmitool mc info  # BMC + firmware/IFWI rev",
                       "cat /proc/cpuinfo | grep -m1 microcode"]))

    # 8. Socket information
    sockets = ev.get("sockets") or []
    audit.append(item("Socket Information", sockets,
                      ("socket(s) " + ", ".join(sockets)) if sockets else "",
                      "note which socket(s) fail — a socket-localized pattern points at CPU/board vs firmware",
                      ["sv.sockets  # enumerate sockets",
                                             (f"sv.{_sv_socket}.uncore.mca.dump()  # selected by socket provenance"
                                                if _socket is not None else
                                                "sv.sockets.uncore.mca.dump()  # resolve socket before reading; no Socket 0 default")]))

    # 9. Historical signature match
    hist = bool(axon_sigs) or recall.get("confidence") in ("High", "Medium") or bool(sim)
    hist_detail = ""
    if axon_sigs:
        hist_detail = f"Axon SVTools: {axon_sigs[0]}"
    elif recall.get("confidence") in ("High", "Medium"):
        hist_detail = f"KB match ({recall.get('confidence')} confidence)"
    elif sim:
        hist_detail = f"{len(sim)} similar HSD(s)"

    audit.append(item("Historical Signature Match", hist, hist_detail,
                      "search prior HSDs on MCACOD+MSCOD+bank+POST+RC-agent for a known-issue match",
                      ["query HSDES on MCACOD+MSCOD+bank+POST+RC-agent",
                       "query Axon for the same SVTools signature"]))

    # 10. Pass vs Fail configuration comparison (not derivable from a single failing log)
    audit.append(item("Pass vs Fail Configuration Comparison", False, "",
                      "A/B the ucode/BIOS/IFWI/OS + knobs between a passing and the failing run",
                      ["XmlCli: dump BIOS knobs on a passing and the failing run, then diff",
                       "record ucode/BIOS/IFWI/OS build IDs for both runs and compare"]))

    return audit


def _render_missing_evidence(L: List[str], audit: List[Dict[str, Any]]) -> None:
    """Report the concrete evidence decoded from the logs, then recommend the
    specific data still worth collecting to firm up the root cause. Presented as
    report prose + bullets (not a pass/fail checklist)."""
    if not audit:
        return
    have = [a for a in audit if a["present"]]
    missing = [a for a in audit if not a["present"]]

    L.append("## Root-Cause Evidence")
    L.append(f"Decoded **{len(have)} of {len(audit)}** of the key hardware/firmware facts "
             "needed to pin an engineer-grade root cause.")
    L.append("")

    if have:
        L.append("### Evidence on hand (decoded from the attached logs / Axon)")
        for a in have:
            detail = a["detail"] or "captured"
            L.append(f"- **{a['label']}:** {detail}")
        L.append("")

    if missing:
        L.append("### Recommended data to collect to confirm the root cause")
        L.append("The following would move this from a strong hypothesis toward a "
                 "confirmed root cause — capture and attach each item using the commands shown:")
        L.append("")
        for i, a in enumerate(missing, 1):
            L.append(f"{i}. **{a['label']}** — {a['collect']}.")
            for cmd in a.get("commands", []):
                L.append(f"    - `{cmd}`")
        L.append("")


def _confidence_band(score: int) -> str:
    if score >= 95:
        return f"**Confirmed ({score}%)**"
    if score >= 80:
        return f"**Strong evidence ({score}%)**"
    if score >= 60:
        return f"**Likely ({score}%)**"
    return f"**Insufficient evidence ({score}%)**"


# IP-branch guide for the first-error provenance + debug decision tree. Maps the
# owning IP keyword to (label, next-check, status_scope command, expected register).
_IP_BRANCH: List[Tuple[str, str, str, str, str]] = [
    ("cha", "CHA / LLC (TOR)",
     "read the TOR entry owner → it routes to the real blocker (PXP→PCIe, UPI→fabric, IMC→memory)",
     "status_scope.run(analyzers=['cha','upi','pcie'])",
     "CHA TOR owner register — which agent holds the stuck entry"),
    ("upi", "UPI / KTI (fabric)",
     "read per-link CRC/retry + credit state on both link partners",
     "status_scope.run(analyzers=['upi'])  # + sv.socketN.uncore.upi.upi<port>.ktilk_*",
     "UPI link status + retry/credit counters (L0p-exit / phy-reset events)"),
    ("kti", "UPI / KTI (fabric)",
     "read per-link CRC/retry + credit state on both link partners",
     "status_scope.run(analyzers=['upi'])",
     "UPI link status + retry/credit counters"),
    ("imc", "IMC / DDR (memory)",
     "read IMC pending reads + retry/CRC and the failing DIMM/rank",
     "status_scope.run(analyzers=['imc'])  # + sv.socketN.uncore.mc*.dump()",
     "IMC pending transaction + failing rank/channel"),
    ("ddr", "IMC / DDR (memory)",
     "read IMC pending reads + retry/CRC and the failing DIMM/rank",
     "status_scope.run(analyzers=['imc'])",
     "IMC pending transaction + failing rank/channel"),
    ("pcie", "PXP / PCIe (IO)",
     "read the PCIe/PXP link + AER + credit backpressure state",
     "status_scope.run(analyzers=['pcie'])",
     "PCIe LTSSM + AER + credit/backpressure registers"),
    ("pxp", "PXP / PCIe (IO)",
     "read the PCIe/PXP link + AER + credit backpressure state",
     "status_scope.run(analyzers=['pcie'])",
     "PCIe LTSSM + AER + credit/backpressure registers"),
    ("ubox", "UBOX / IEH",
     "read the ubox IERR/MCerr logging registers for the first-error source",
     "sv.socketN.uncore.ubox.ncevents.ierrloggingreg",
     "UBOX first IERR/MCERR source + logged agent"),
    ("punit", "PUnit / PCU (power)",
     "read the PUnit mailbox + global status for the first-error source",
     "sv.socketN.uncore.punit.* (mailbox/global status)",
     "PUnit mailbox status + reset/throttle cause"),
]


def _ip_branch(unit: str) -> Optional[Tuple[str, str, str, str, str]]:
    u = (unit or "").lower()
    for key, label, check, cmd, expect in _IP_BRANCH:
        if key in u:
            return (key, label, check, cmd, expect)
    return None


# Owning-IP → suggested triage team (routes the ticket to reduce triage latency).
_OWNER_TEAM: List[Tuple[str, str]] = [
    ("cha", "CHA / Mesh (Uncore) team"),
    ("mesh", "CHA / Mesh (Uncore) team"),
    ("upi", "Fabric team (UPI/KTI)"),
    ("kti", "Fabric team (UPI/KTI)"),
    ("pcie", "PV.Domain.IO (PCIe/PXP)"),
    ("pxp", "PV.Domain.IO (PCIe/PXP)"),
    ("cxl", "PV.Domain.IO (CXL)"),
    ("imc", "RAS / Memory team"),
    ("ddr", "RAS / Memory team"),
    ("memory", "RAS / Memory team"),
    ("m2m", "RAS / Memory team"),
    ("b2cmi", "RAS / Memory team"),
    ("dcu", "Core team (L1/L2 cache)"),
    ("mlc", "Core team (L1/L2 cache)"),
    ("ifu", "Core team (front-end)"),
    ("dtlb", "Core team (TLB)"),
    ("ubox", "Uncore / UBOX team"),
    ("punit", "Power Management / PUnit team"),
    ("pcu", "Power Management / PUnit team"),
]


def _suggested_team(unit: str) -> str:
    u = (unit or "").lower()
    for key, team in _OWNER_TEAM:
        if key in u:
            return team
    return ""


def _render_causality_sections(L: List[str], target: Dict[str, Any],
                               log_findings: Optional[Dict[str, Any]],
                               recall: Dict[str, Any],
                               comment_findings: Optional[Dict[str, Any]],
                               evidence_audit: List[Dict[str, Any]]) -> None:
    """Deterministic, engineer-grade causality sections built ONLY from decoded
    artifacts (no LLM): Failure Timeline, MCA Ownership, Cause vs Noise, Competing
    Hypotheses, Confidence, Required Missing Data (with impact), Evidence Ranking."""
    lf = log_findings or {}
    decoded = lf.get("decoded") or {}
    if not decoded and not (comment_findings or {}).get("root_cause"):
        return
    ev = decoded.get("evidence") or {}
    mcs = ev.get("mc_status") or {}
    # Keep only IERR/MCERR rows that name a real captured source; drop placeholder
    # "None" / "No error logged" rows so they never read as a proven first error.
    ierr = [r for r in (decoded.get("ierr_table") or []) if _ierr_has_source(r)]
    mca = decoded.get("mca") or {}
    boot = decoded.get("boot_flow") or {}
    flags = ev.get("status_flags") or {}
    sockets = ev.get("sockets") or []
    sigs = lf.get("signatures") or []
    cf = comment_findings or {}
    three_strike = _is_three_strike(mcs)
    poison = _is_poison_consumption(mcs)
    first_ierr = ierr[0] if ierr else {}
    skt = f"Socket {sockets[0]}" if sockets else (
        f"Socket {first_ierr.get('socket')}" if first_ierr.get("socket") else "the failing socket")

    # Provenance / capture flags used by the scorecard and confidence ceilings.
    txt = (target.get("full_text") or "")
    have_owning_ip = bool(mcs.get("bank_unit") or first_ierr.get("source_unit"))
    have_first_error = bool(first_ierr.get("source_unit"))
    # A TOR "dump" means the stuck-entry owner was actually captured — NOT the
    # bare TOR_TIMEOUT symptom string.
    have_tor_dump = bool(re.search(r"tor[_\s]*(owner|dump|entry|valid|state)", txt, re.I))
    have_crashdump = "crashdump" in txt.lower()
    have_reg_evidence = bool(mcs.get("status"))
    reproducible = bool(re.search(r"reproduc|100%\s*repro|consistently\s*fail", txt, re.I))
    fix_validated = bool(cf.get("workaround") and re.search(
        r"validated|resolved|no\s*repro|passes|fixed", txt, re.I))
    # A comment-thread claim is a Tier-3 human OBSERVATION, not proof of root cause;
    # 'root cause identified' requires hardware ownership evidence.
    have_root_cause = bool(have_first_error and (have_crashdump or have_tor_dump) and not poison)

    # ---------- RCA Scorecard (manager-friendly, top of report) ----------
    _present = sum(1 for a in evidence_audit if a.get("present"))
    _total = len(evidence_audit) or 1
    completeness = int(100 * _present / _total)
    def _ck(b):
        return "✅" if b else "❌"
    L.append("## RCA Scorecard")
    L.append("| Check | Status |")
    L.append("|-------|--------|")
    L.append(f"| Root cause identified | {_ck(have_root_cause)} |")
    L.append(f"| First error located | {_ck(have_first_error)} |")
    L.append(f"| Owning IP determined | {_ck(have_owning_ip)} |")
    L.append(f"| Reproducible | {_ck(reproducible)} |")
    L.append(f"| Fix validated | {_ck(fix_validated)} |")
    L.append(f"| Additional data needed | {_ck(_present < _total)} |")
    L.append("")
    L.append(f"**RCA completeness: {completeness}%** ({_present}/{_total} key evidence items decoded).")
    L.append("")

    # ---------- Failure Timeline ----------
    L.append("## Failure Timeline")
    tl: List[Tuple[str, str, str]] = []  # (stage, event, source)
    if first_ierr.get("source_unit"):
        tl.append(("FIRST_EVENT",
                   f"{first_ierr.get('type','IERR')} ({first_ierr.get('priority','First')}) from "
                   f"**{first_ierr['source_unit']}** on Socket {first_ierr.get('socket','?')}"
                   + (f" @ `{first_ierr['address']}`" if first_ierr.get("address") else ""),
                   "PythonSV UBOX IERR/MCerr table"))
    elif poison:
        tl.append(("FIRST_EVENT",
                   "poison CREATED upstream (memory UE / IO-CXL / uncore) — source not captured",
                   "MCA decode (inferred)"))
    elif mcs.get("status"):
        tl.append(("FIRST_EVENT",
                   f"MCA logged in bank {mcs.get('bank','?')} ({mcs.get('bank_unit','?')})",
                   "MCA decode"))
    if mcs.get("status"):
        _dec = _short(mcs.get("decode") or mca.get("headline") or "machine-check", 120)
        if poison:
            prop = (f"poison CONSUMED at bank {mcs.get('bank','?')} "
                    f"({mcs.get('bank_unit','?')}) on a load — {_dec} — _victim, not origin_")
        else:
            prop = f"MCA bank {mcs.get('bank','?')} ({mcs.get('bank_unit','?')}) — {_dec}"
        tl.append(("PROPAGATION", prop, "MCA decode"))
    if three_strike:
        tl.append(("PROPAGATION",
                   "forward progress stalled → core watchdog fired → 3-strike / Internal Timer "
                   "(MCACOD 0x400) — _symptom, not origin_", "MCA decode (inferred chain)"))
    _final = ""
    if boot.get("reached_os"):
        _final = "Runtime / post-boot failure (system had reached OS)"
    elif boot.get("failing_stage"):
        _final = f"Boot stopped before {boot['failing_stage'].get('label','?')}"
    _title = _short(target.get("title", ""), 80)
    if not _final and _title:
        _final = _title
    if _final:
        tl.append(("FINAL_FAILURE", _final, "boot flow / ticket"))
    if tl:
        L.append("| Stage | Event | Source |")
        L.append("|-------|-------|--------|")
        for stage, event, src in tl:
            L.append(f"| **{stage}** | {event.replace('|', '\\|')} | {src} |")
    else:
        L.append("- Timeline could not be reconstructed — no ordered hardware events decoded.")
    L.append("")

    # ---------- MCA Ownership Analysis ----------
    if mcs.get("status") or (ev.get("mca_banks")):
        L.append("## MCA Ownership Analysis")
        L.append("| Bank | MCACOD | MSCOD | Owning IP | Socket | Fatality | Class |")
        L.append("|------|--------|-------|-----------|--------|----------|-------|")
        # Central fatality classification (UC & PCC => uncorrected fatal, never corrected).
        _cls = classify_mca_status(mcs.get("status"))
        fatal = _cls["severity"] if _cls.get("valid") else (
            "FATAL" if (flags.get("UC") and flags.get("PCC")) else
            "uncorrected" if flags.get("UC") else "corrected")
        recov = _recovery_str(mcs.get("recovery"))
        if recov:
            fatal = f"{_cls['severity']} · {recov}" if _cls.get("valid") else recov
        # 3-strike Internal Timer AND poison consumption are VICTIM/symptom, not
        # the origin; a real IP/source fault is PRIMARY.
        cls = ("SECONDARY (symptom)" if three_strike
               else "VICTIM (consumer)" if poison else "PRIMARY")
        L.append(f"| {mcs.get('bank','?')} | {mcs.get('mcacod','—')} | {mcs.get('mscod','—')} | "
                 f"{mcs.get('bank_unit','—')} | {sockets[0] if sockets else '?'} | {fatal} | {cls} |")
        if three_strike and first_ierr.get("source_unit"):
            L.append(f"| — | — | — | {first_ierr['source_unit']} | {first_ierr.get('socket','?')} | "
                     f"first error | **PRIMARY (origin)** |")
        elif poison:
            L.append("| — | — | — | poison source (upstream) | — | "
                     "origin unproven | **PRIMARY (origin)** |")
        L.append("")
        if three_strike:
            L.append("- **PRIMARY_ERROR:** the transaction/IP that blocked forward progress "
                     f"({first_ierr.get('source_unit') or 'CHA TOR / UPI / IMC — capture to confirm'}).")
            L.append("- **SECONDARY_ERROR:** 3-strike / Internal Timer (0x400) — the watchdog "
                     "reaction to the stall.")
            L.append("- **VICTIM_ERROR:** the core that could not retire (reported the machine check).")
        elif poison:
            L.append(f"- **PRIMARY_ERROR:** the upstream agent that CREATED the poison "
                     f"(memory UE / IO-CXL poisoned completion / uncore read-return) — not yet proven.")
            L.append(f"- **VICTIM_ERROR:** {mcs.get('bank_unit') or 'the core cache unit'} "
                     f"consumed the poison on a load ({mcs.get('mcacod','?')}/{mcs.get('mscod','?')}).")
            L.append("- **Next:** read MC_ADDR (ADDRV) to map the poisoned address; a `NO_iMC_MCA` "
                     "signature rules out an ordinary DDR UE — trace the mesh/CXL/IO read path.")
        else:
            L.append(f"- **PRIMARY_ERROR:** {mcs.get('bank_unit') or 'the logged bank'} "
                     f"({mcs.get('mcacod','?')}/{mcs.get('mscod','?')}).")
        L.append("")

    # ---------- First-Error Provenance & Debug Decision Tree ----------
    _prov_unit = first_ierr.get("source_unit") or mcs.get("bank_unit") or ""
    branch = _ip_branch(_prov_unit)
    if branch:
        _key, _label, _check, _cmd, _expect = branch
        L.append("## First-Error Provenance & Debug Decision Tree")
        # Ownership confidence: strong only when the first-error source is explicit.
        own_conf = "high" if have_first_error else "low (bank-derived, not first-error proven)"
        own_reasons = []
        if have_first_error:
            own_reasons.append("explicit first IERR/MCerr source in the UBOX table")
        if mcs.get("bank_unit"):
            own_reasons.append(f"MCA bank maps to {mcs['bank_unit']}")
        L.append(f"- **Primary IP:** {_prov_unit} ({_label})")
        L.append(f"- **Ownership confidence:** {own_conf}"
                 + (f" — {'; '.join(own_reasons)}" if own_reasons else ""))
        L.append("")
        if "cha" in _key:
            L.append("A CHA TOR_TIMEOUT names the *victim queue*, not the origin. Resolve the TOR "
                     "entry owner to route to the real blocker:")
            L.append("")
            L.append("```")
            L.append(f"Observed:  {_prov_unit} TOR_TIMEOUT")
            L.append("Next check: TOR entry owner")
            L.append("  ├─ owner = PXP / PCIe  → IO branch (backpressure / AER / credits)")
            L.append("  ├─ owner = UPI / KTI   → fabric branch (credit starvation / link degrade)")
            L.append("  └─ owner = IMC / DDR   → memory branch (read stall / deadlock)")
            L.append(f"Command:   {_cmd}")
            L.append(f"Expected:  {_expect}")
            L.append("```")
        else:
            L.append("```")
            L.append(f"Observed:  first error from {_prov_unit}")
            L.append(f"Next check: {_check}")
            L.append(f"Command:   {_cmd}")
            L.append(f"Expected:  {_expect}")
            L.append("```")
        L.append("")
    elif poison:
        # Core cache units (DCU/MLC/IFU/DTLB) are not fabric IPs; poison consumption
        # needs its own provenance branch that routes to the poison SOURCE.
        _vic = mcs.get("bank_unit") or "core cache"
        L.append("## First-Error Provenance & Debug Decision Tree")
        L.append(f"- **Reporting IP:** {_vic} (poison **consumer / victim**, not the origin)")
        L.append("- **Ownership confidence:** low — the poison *source* is not captured; "
                 "the consuming unit only proves *where* poison was read, not *who* created it.")
        L.append("")
        L.append("A DCU/MLC load-poison consumption names the *consumer*, not the origin. "
                 "Trace the poison source:")
        L.append("")
        L.append("```")
        L.append(f"Observed:  {_vic} load-poison consumption ({mcs.get('mcacod','?')}/{mcs.get('mscod','?')})")
        L.append("Next check: MC_ADDR (ADDRV) → poisoned physical address")
        L.append("  ├─ iMC MCA present  → memory branch (DDR UE / patrol scrub creating poison)")
        L.append("  ├─ NO_iMC_MCA       → uncore/mesh/CXL read-return path (not a DDR UE)")
        L.append("  ├─ CXL/PCIe AER     → IO branch (poisoned completion from device)")
        L.append("  └─ UCNA depository  → prior deferred/uncorrected source that seeded poison")
        L.append("Command:   check IMC banks + UCNA list; map MC_ADDR to channel/rank or MMIO region")
        L.append("Expected:  a source MCA (IMC UE / CXL AER) OR an unlogged mesh path")
        L.append("```")
        L.append("")

    # ---------- Ownership Evidence Ladder (trust calibration) ----------
    if mcs.get("status") or ierr or have_owning_ip:
        _ss = "statusscope" in txt.lower()
        _sig = bool(sigs)
        _hist = recall.get("confidence") in ("High", "Medium")
        _kb = bool(recall.get("matches"))
        L.append("## Ownership Evidence Ladder")
        def _tick(b):
            return "✓" if b else "·"
        L.append(f"- **Level 1 — Direct:** {_tick(have_first_error)} first-error register (UBOX IERR/MCerr)  |  "
                 f"{_tick(have_tor_dump)} TOR owner register")
        L.append(f"- **Level 2 — Strong:** {_tick(have_crashdump)} crashdump owner  |  "
                 f"{_tick(_ss)} StatusScope corroboration")
        L.append(f"- **Level 3 — Supporting:** {_tick(_sig)} log signatures  |  "
                 f"{_tick(_hist)} historical pattern")
        L.append(f"- **Level 4 — Weak:** {_tick(_kb)} KB similarity")
        # Derive confidence strictly from the highest evidence level present.
        if have_first_error or have_tor_dump:
            _lvl, _oconf, _why = 1, "HIGH", "explicit first-error / TOR owner register"
        elif have_crashdump or _ss:
            _lvl, _oconf, _why = 2, "MEDIUM-HIGH", "crashdump / StatusScope corroboration (no first-error register yet)"
        elif _sig or _hist:
            _lvl, _oconf, _why = 3, "MEDIUM", "log-signature / historical pattern only — owner inferred, not proven"
        elif _kb:
            _lvl, _oconf, _why = 4, "LOW", "KB similarity only"
        else:
            _lvl, _oconf, _why = 0, "INSUFFICIENT", "no ownership evidence captured"
        if poison and _lvl == 1 and not have_first_error:
            _oconf, _why = "MEDIUM", "poison consumer captured, but the source owner is not proven"
        L.append(f"- **Ownership Confidence:** {_oconf} — determined from "
                 + (f"Level-{_lvl} evidence ({_why})." if _lvl else f"{_why}."))
        _team = _suggested_team(mcs.get("bank_unit") or (first_ierr.get("source_unit") or ""))
        if _team:
            _proven = have_first_error or have_tor_dump
            L.append(f"- **Suggested owner / routing:** {_team}"
                     + ("" if _proven else " _(tentative — owner not yet proven)_"))
        L.append("")

    # ---------- Cause vs Noise ----------
    L.append("## Cause vs Noise")
    root_items, support_items, noise_items = [], [], []
    if cf.get("root_cause"):
        root_items.append(f"Comment-thread converged cause: {_short(cf['root_cause'], 160)}")
    if three_strike and first_ierr.get("source_unit"):
        root_items.append(f"First error from **{first_ierr['source_unit']}** — the forward-progress blocker")
    elif poison:
        root_items.append(f"Upstream **poison SOURCE** (unproven) — the {mcs.get('bank_unit','core')} "
                          f"only CONSUMED the poison ({mcs.get('mcacod','')}/{mcs.get('mscod','')})".strip())
    elif mcs.get("status"):
        root_items.append(f"MCA bank {mcs.get('bank','?')} ({mcs.get('bank_unit','?')}) "
                          f"{mcs.get('mcacod','')} {mcs.get('mscod','')}".strip())
    if flags:
        support_items.append("MCi_STATUS flags: " + " ".join(k for k, v in flags.items() if v))
    if ev.get("mc_addr"):
        support_items.append(f"MC_ADDR `{ev['mc_addr']}`")
    _rec = _recovery_str(mcs.get("recovery"))
    if _rec:
        support_items.append(f"recovery class {_rec}")
    if poison and mcs.get("bank_unit"):
        support_items.append(f"{mcs['bank_unit']} is the poison CONSUMER (victim), not the origin")
    if boot.get("reached_os"):
        support_items.append("system reached OS (runtime failure, not boot hang)")
    for s in sigs:
        lab = str(s.get("label", ""))
        if s.get("count", 0) >= 50 and any(k in lab.lower() for k in ("whea", "pcie", "retry", "mce")):
            noise_items.append(f"{lab} (x{s['count']}) — raw log-line count, machine-check "
                               "aftermath / telemetry, not a distinct event")
    if three_strike:
        noise_items.append("3-strike / WDTimeout itself — a symptom of the stall, not the origin")
    for label, items in (("ROOT_CAUSE", root_items), ("SUPPORTING_EVIDENCE", support_items),
                         ("INCIDENTAL_TELEMETRY", noise_items)):
        L.append(f"**{label}:**")
        if items:
            for it in items:
                L.append(f"- {it}")
        else:
            L.append("- _none identified_")
        L.append("")

    # ---------- Competing Hypotheses ----------
    L.append("## Competing Hypotheses")
    hyps: List[Tuple[str, List[str], List[str]]] = []
    if three_strike:
        blocker = first_ierr.get("source_unit") or "CHA TOR / SCF"
        hyps.append((f"Forward-progress stall in **{blocker}** → watchdog 3-strike",
                     [f"first error from {blocker}" if first_ierr.get("source_unit") else
                      "3-strike is a stall symptom (MCACOD 0x400)",
                      "core watchdog / Internal Timer decoded"],
                     ["no TOR/credit dump captured to prove which IP stalled first"]))
        hyps.append(("UPI link degrade / credit starvation (multi-socket stall)",
                     ["UPI implicated in signatures" if any("upi" in str(s.get("label","")).lower()
                       for s in sigs) else "UPI is a common forward-progress blocker"],
                     ["no per-link UPI CRC/retry or credit evidence in the logs"]))
        hyps.append(("IMC / DDR read stall (no data return)",
                     ["memory path can stall CHA and trip the watchdog"],
                     ["no IMC retry/CRC or DIMM/rank evidence captured"]))
    elif mcs.get("status"):
        unit = mcs.get("bank_unit") or "the logged IP"
        hyps.append((f"Fault in **{unit}** ({mcs.get('mcacod','?')}/{mcs.get('mscod','?')})",
                     [f"MCA decoded to {unit}", "status flags present" if flags else
                      "MCACOD/MSCOD decoded"],
                     ["MC_ADDR/MC_MISC not captured" if not ev.get("mc_addr") else
                      "single occurrence — recurrence not shown"]))
        hyps.append(("Upstream IP that fed the error (victim vs source ambiguity)",
                     ["machine checks often log at the victim, not the source"],
                     ["first-error socket/die ordering not captured"]))
        hyps.append(("Config / firmware / BKC-specific behaviour",
                     ["would explain a systematic, reproducible failure"],
                     ["no A/B revision comparison in the ticket"]))
    else:
        hyps.append(("Insufficient decoded evidence to rank hypotheses",
                     ["ticket text / comments only"],
                     ["no valid MCA / IERR / register capture attached"]))
    for i, (name, fors, againsts) in enumerate(hyps[:3], 1):
        letter = chr(ord("A") + i - 1)
        L.append(f"**Hypothesis {letter}: {name}**")
        L.append("- Evidence for: " + ("; ".join(fors) if fors else "—"))
        L.append("- Evidence against: " + ("; ".join(againsts) if againsts else "—"))
        L.append("")

    # ---------- Contradiction Detector ----------
    sig_text = " ".join(str(s.get("label", "")).lower() for s in sigs)
    contradictions: List[str] = []
    lead = hyps[0][0].lower() if hyps else ""
    if "upi" in lead:
        conflicts = []
        if "upi" not in sig_text and "kti" not in sig_text:
            conflicts.append("no UPI/KTI error signature in the logs")
        if "retry" not in sig_text and "crc" not in txt.lower():
            conflicts.append("no UPI retry/CRC escalation captured")
        if conflicts:
            contradictions.append("Leading hypothesis names **UPI**, but: " + "; ".join(conflicts))
    if "imc" in lead or "ddr" in lead or "memory" in lead:
        if not any(k in sig_text for k in ("ddr", "dimm", "imc", "memory", "ce", "ue")):
            contradictions.append("Leading hypothesis names **memory/IMC**, but no DDR/DIMM/IMC "
                                  "error signature is present")
    if "pcie" in lead or "pxp" in lead:
        if "pcie" not in sig_text and "aer" not in sig_text:
            contradictions.append("Leading hypothesis names **PCIe/PXP**, but no PCIe/AER "
                                  "signature is present")
    if three_strike and not have_first_error:
        contradictions.append("A 3-strike is decoded but the **first-error source is not "
                              "captured** — origin attribution is unproven (do not name a "
                              "specific IP as root cause yet)")
    # OWNERSHIP_EVIDENCE_CONFLICT: the first-error source IP differs from the
    # reporting MCA bank owner — reporting IP is not the originating IP.
    _fe_unit = (first_ierr.get("source_unit") or "").strip()
    _bank_unit = (mcs.get("bank_unit") or "").strip()
    ownership_conflict = bool(
        _fe_unit and _bank_unit and _norm_ip(_fe_unit) and _norm_ip(_bank_unit)
        and _norm_ip(_fe_unit) != _norm_ip(_bank_unit))
    if ownership_conflict:
        contradictions.append(
            f"**OWNERSHIP_EVIDENCE_CONFLICT** — first-error source (**{_fe_unit}**) differs "
            f"from the reporting MCA bank owner (**{_bank_unit}**); the originating IP is "
            "unresolved (reporting IP ≠ first-error source). Reconcile before naming an owner")
    decoder_ambiguity = bool((mcs.get("decoder_ambiguity") or {}).get("state"))
    _decoder_sources = mcs.get("source_provenance") or []
    provenance_unknown = bool(_decoder_sources) and any(
        str(s.get("trust", "UNKNOWN")) == "UNKNOWN" for s in _decoder_sources)
    if provenance_unknown:
        contradictions.append(
            "**SOURCE_PROVENANCE_UNKNOWN** — one or more decoder databases lack an "
            "audited authoritative source; RCA cannot be promoted beyond WORKING HYPOTHESIS")
    if decoder_ambiguity:
        _candidates = ", ".join((mcs.get("decoder_ambiguity") or {}).get("candidates", []))
        contradictions.append(
            f"**AMBIGUOUS_DECODER** — MCACOD/MSCOD has competing interpretations: {_candidates}; "
            "do not confirm an owner or cause until the platform/IP decode is resolved")
    if contradictions:
        L.append("## Contradiction Detector")
        for c in contradictions:
            L.append(f"- ⚠️ {c}.")
        L.append("")

    # ---------- Confidence (with ceiling rules) ----------
    present = sum(1 for a in evidence_audit if a.get("present"))
    total = len(evidence_audit) or 1
    score = 30 + int(60 * present / total)
    if have_reg_evidence:
        score += 15  # direct register evidence (Tier-1)
    # A comment-thread root cause is a Tier-3 human OBSERVATION — it never raises
    # confidence on its own; only independent hardware evidence can.
    cf_rc = bool(cf.get("root_cause"))
    # Confidence ceilings — RCA systems must not read overconfident.
    ceilings: List[Tuple[int, str]] = []
    if cf_rc and not (have_first_error or have_tor_dump):
        if have_reg_evidence and have_crashdump:
            ceilings.append((80, "root cause is a comment-thread claim corroborated by MCA + "
                                 "crashdump, but ownership is not register-proven"))
        else:
            ceilings.append((60, "root cause is an unverified comment-thread claim with no "
                                 "matching hardware evidence"))
    if not have_tor_dump and ("cha" in (first_ierr.get("source_unit", "").lower()
                                        + mcs.get("bank_unit", "").lower())):
        ceilings.append((70, "no TOR dump to prove the stuck-entry owner"))
    if not have_owning_ip:
        ceilings.append((60, "owning IP not determined"))
    if poison:
        ceilings.append((70, "poison source not identified — only the consuming unit was captured"))
    if decoder_ambiguity:
        ceilings.append((65, "decoder ambiguity remains unresolved for the MCA code pair"))
    if provenance_unknown:
        ceilings.append((60, "decoder source provenance is not fully audited"))
    if not have_crashdump:
        ceilings.append((75, "no crashdump attached"))
    if contradictions:
        ceilings.append((65, "unresolved contradiction(s) with the leading hypothesis"))
    if str(target.get("evidence_source", "")).startswith("reconstructed_from_"):
        ceilings.append((35, "source evidence was reconstructed from HSD text, not an original log or crashdump"))
    cap = min([c for c, _ in ceilings], default=100)
    capped = min(score, cap)
    L.append("## Root-Cause Confidence")
    L.append(f"{_confidence_band(capped)} — based on {present}/{total} key hardware/firmware "
             "facts decoded"
             + (" (a comment-thread claim is noted but NOT counted toward confidence)"
                if cf_rc else "") + ".")
    if ceilings and cap < score:
        _why = next(w for c, w in ceilings if c == cap)
        L.append(f"- **Ceiling applied:** capped at {cap}% — {_why}. Raising it requires that data.")
    L.append("")

    # ---------- Engineer Verdict Audit (prevents over-interpretation) ----------
    direct = []
    if mcs.get("bank_unit"):
        direct.append("MCA bank owner known")
    if have_first_error:
        direct.append("first-error source known")
    if have_tor_dump:
        direct.append("TOR entry owner captured")
    if have_crashdump:
        direct.append("crashdump present")
    indirect = []
    if (lf.get("lines_scanned") or 0) > 0:
        indirect.append("serial/console log correlation")
    if "statusscope" in txt.lower():
        indirect.append("StatusScope correlation")
    if recall.get("matches"):
        indirect.append(f"KB similarity ({len(recall['matches'])} case(s))")
    missing_key = []
    if not have_tor_dump and "cha" in (str(first_ierr.get("source_unit", ""))
                                       + str(mcs.get("bank_unit", ""))).lower():
        missing_key.append("TOR owner dump")
    if not have_crashdump:
        missing_key.append("crashdump")
    if not ev.get("mc_addr"):
        missing_key.append("MC_ADDR/MC_MISC")
    if poison:
        missing_key.append("poison source trace (MC_ADDR → IMC UE / CXL AER / uncore path)")
    # Verdict type: proven ownership vs likely vs hypothesis.
    # Poison consumption never proves the origin — the consumer is only the victim.
    ownership_proven = (have_first_error and (have_tor_dump or have_crashdump)
                        and not poison and not ownership_conflict and not decoder_ambiguity
                        and not provenance_unknown)
    # A comment-thread claim is an OBSERVATION, never proof — it can never set CONFIRMED
    # and never lifts the verdict on its own; it is only noted in the reason.
    _cf_note = ("; a comment-thread claim exists but is NOT independently verified by "
                "hardware evidence" if cf.get("root_cause") else "")
    if ownership_proven:
        vtype, vreason = "CONFIRMED ROOT CAUSE", (
            "owning IP proven by first-error source plus a TOR/crashdump capture")
    elif poison:
        vtype, vreason = "WORKING HYPOTHESIS", (
            f"poison was CONSUMED at {mcs.get('bank_unit','the core cache')} (victim); the "
            "upstream poison SOURCE that is the true root cause is not yet identified" + _cf_note)
    elif (have_owning_ip and not contradictions and not decoder_ambiguity
          and not provenance_unknown
          and not (three_strike and not have_first_error)):
        vtype, vreason = "LIKELY ROOT CAUSE", (
            "owning IP identified from decoded MCA, but direct ownership (TOR owner / "
            "first-error register) not yet proven" + _cf_note)
    else:
        vtype, vreason = "WORKING HYPOTHESIS", (
            "origin not proven" + (" — active contradiction(s)" if contradictions else
            " — first-error source not captured" if three_strike else " — insufficient evidence")
            + _cf_note)
    L.append("## Engineer Verdict Audit")
    L.append("- **Evidence directly proving root cause:** "
             + (", ".join(direct) if direct else "_none_"))
    L.append("- **Evidence indirectly supporting root cause:** "
             + (", ".join(indirect) if indirect else "_none_"))
    L.append("- **Evidence missing:** " + (", ".join(missing_key) if missing_key else "_none_"))
    L.append(f"- **Verdict type:** **{vtype}**")
    L.append(f"- **Reason:** {vreason}.")
    L.append("")

    # ---------- Required Missing Data (with impact) ----------
    missing = [a for a in evidence_audit if not a.get("present")]
    if missing:
        L.append("## Required Missing Data")
        L.append("| # | Missing artifact | Why it matters | Expected confidence impact |")
        L.append("|---|------------------|----------------|----------------------------|")
        for i, a in enumerate(missing, 1):
            why = _short(a.get("collect", ""), 90).replace("|", "\\|")
            L.append(f"| {i} | {a['label']} | {why} | +5–15% (moves toward confirmed) |")
        L.append("")

    # ---------- Evidence Ranking ----------
    L.append("## Evidence Ranking")
    l1, l2, l3 = [], [], []
    if mcs.get("status") or mca:
        l1.append("MCA decode (bank/MCACOD/MSCOD/flags)")
    if ierr:
        l1.append("PythonSV UBOX IERR/MCerr table")
    if any("statusscope" in str(a.get("label", "")).lower() for a in evidence_audit):
        l1.append("StatusScope")
    txt = (target.get("full_text") or "")
    if "statusscope" in txt.lower():
        l1.append("StatusScope capture (in ticket)")
    if "crashdump" in txt.lower():
        l1.append("Crashdump")
    if (lf.get("lines_scanned") or 0) > 0:
        l2.append(f"Serial / console logs ({lf.get('lines_scanned'):,} lines scanned)")
    if "bmc" in txt.lower() or "sel" in txt.lower():
        l2.append("BMC / SEL log")
    if (recall.get("matches")):
        l3.append(f"KB similarity ({len(recall['matches'])} prior case(s), {recall.get('confidence')})")
    L.append("- **Level 1 — explicit hardware evidence:** "
             + (", ".join(l1) if l1 else "_none captured — highest-value gap_"))
    L.append("- **Level 2 — log-derived evidence:** " + (", ".join(l2) if l2 else "_none_"))
    L.append("- **Level 3 — inferred evidence:** " + (", ".join(l3) if l3 else "_none_"))
    L.append("")

    # ---------- Engineer Playbook (what to check next) ----------
    _pb_unit = first_ierr.get("source_unit") or mcs.get("bank_unit") or ""
    pb = _ip_branch(_pb_unit)
    if pb:
        _key, _label, _check, _cmd, _expect = pb
        L.append("## Engineer Playbook — What to Check Next")
        if "cha" in _key:
            L.append(f"- **Highest-value next action:** capture the {_pb_unit} TOR entry owner.")
            L.append(f"- **Command:** `{_cmd}`")
            L.append("- **Expected outcomes:**")
            L.append("  - owner = **PXP / PCIe** → follow the PCIe flow (backpressure / AER / credits)")
            L.append("  - owner = **UPI / KTI** → follow the fabric flow (credit starvation / link degrade)")
            L.append("  - owner = **IMC / DDR** → follow the memory flow (read stall / deadlock)")
            L.append("- **Confidence gain:** proving the TOR owner lifts the verdict from "
                     "*LIKELY* to *CONFIRMED* and typically +15–25%.")
        else:
            L.append(f"- **Highest-value next action:** {_check} for **{_pb_unit}**.")
            L.append(f"- **Command:** `{_cmd}`")
            L.append(f"- **Expected evidence:** {_expect}.")
            L.append("- **Confidence gain:** direct ownership evidence lifts the verdict toward "
                     "*CONFIRMED* (+15–25%).")
        L.append("")
    elif poison:
        _vic = mcs.get("bank_unit") or "core cache"
        L.append("## Engineer Playbook — What to Check Next")
        L.append(f"- **Highest-value next action:** trace the poison SOURCE — read MC_ADDR (ADDRV) "
                 f"from the {_vic} bank and map the poisoned physical address.")
        L.append("- **Command:** dump IMC MCA banks + UCNA depository; map MC_ADDR to channel/rank "
                 "(memory) or MMIO region (IO/CXL).")
        L.append("- **Expected outcomes:**")
        L.append("  - **iMC MCA present** → memory branch (DDR UE / patrol scrub created the poison)")
        L.append("  - **NO_iMC_MCA** → uncore/mesh/CXL read-return path (not an ordinary DDR UE)")
        L.append("  - **CXL/PCIe AER** → IO branch (device sent a poisoned completion)")
        L.append("- **Also confirm:** latest microcode/BIOS (poison-handling errata can turn a "
                 "recoverable SRAR into a fatal kernel panic).")
        L.append("- **Confidence gain:** identifying the source lifts the verdict from "
                 "*WORKING HYPOTHESIS* to *CONFIRMED* (+20–30%).")
        L.append("")

    L.append("---")
    L.append("")


def _offline_report(hsd_id, symptoms, platform, recall, target, similar,
                    hsdes_enabled, log_findings=None, attachments=None,
                    attachments_fetched=0, attach_files=None,
                    comment_findings=None, transferred=None,
                    fetch_attempted=False) -> Tuple[str, Dict[str, Any]]:
    target = target or {}
    attachments = attachments or []
    attach_files = attach_files or []
    cf = comment_findings or {}
    plat = platform or "unknown platform"
    blob = f"{symptoms} " + (target.get("full_text") or target.get("description") or "")
    if log_findings:
        blob += " " + " ".join(s["label"] for s in log_findings["signatures"])
    domains = _detect_domains(blob)[:3]  # focus on the dominant domain(s)

    def tval(k, default="_not available_"):
        return target[k] if target.get(k) else default

    findings = _extract_findings(target, comment_findings)
    rc_validation = _validate_root_cause(cf, target)
    # Evidence-completeness audit — the 10 hardware/firmware facts that move a
    # generic triage line toward an engineer-grade root cause.
    evidence_audit = _audit_root_cause_evidence(target, log_findings, recall, similar)

    def _known_verdict() -> str:
        if cf.get("root_cause"):
            return "Root cause identified in ticket comments"
        if recall["confidence"] in ("High", "Medium"):
            return "Likely known issue"
        if findings.get("confidence") == "confirmed":
            return "Likely known (confirmed in ticket history)"
        return "Likely new sighting"

    def _exec_confidence() -> int:
        score = 20
        if target and not target.get("error"):
            score += 20
        score += {"High": 30, "Medium": 20, "Low": 10, "None": 0}.get(
            recall.get("confidence", "None"), 0)
        if cf.get("root_cause"):
            score += 20
        if cf.get("workaround"):
            score += 10
        elif findings.get("resolution"):
            score += 5
        if log_findings and log_findings.get("signatures"):
            score += 10
        # Evidence completeness lifts confidence a few points per key fact present,
        # so a fully-instrumented failing log reads higher than a generic one.
        score += 2 * sum(1 for a in evidence_audit if a["present"])
        score = min(97, score)
        if str(target.get("evidence_source", "")).startswith("reconstructed_from_"):
            score = min(score, 35)
        return score


    top_sig = None
    if log_findings and log_findings.get("signatures"):
        top_sig = log_findings["signatures"][0]

    # Suspected area: prefer the attachment-derived mechanism, else ticket field.
    suspected_area = (log_findings or {}).get("suspected_area", "") if log_findings else ""
    if not suspected_area:
        rec = target.get("raw", {}) or {}
        for k, v in rec.items():
            if k.endswith("suspect_area") and v and str(v).lower() != "unknown":
                suspected_area = str(v)
                break

    # Failure point: prefer the comment-derived root cause (human conclusion),
    # then the log timeline's first fatal event, then nothing.
    if cf.get("root_cause"):
        failure_point = _short(cf["root_cause"], 200)
    else:
        failure_point = "Not found from current evidence"
        for ev in (log_findings or {}).get("timeline", []):
            if ev.get("failure_point"):
                detail = _short(ev.get("text", ""), 140)
                failure_point = (f"{ev.get('label', 'failure')} — {detail}"
                                 if detail else ev.get("label", "failure"))
                break

    # Next action: continue from the LAST recorded next-step, else evidence-led.
    if cf.get("next_steps"):
        next_action = f"Continue: {_short(cf['next_steps'][-1], 160)}"
    elif cf.get("root_cause"):
        next_action = "Confirm the comment-identified root cause on hardware, then verify the workaround."
    elif top_sig:
        next_action = "Start with attached-log failure signature and MCA/trace decode."
    else:
        next_action = "Start with dominant domain checks and collect stronger runtime evidence."

    L: List[str] = []
    from time import strftime
    ttitle = _short(tval("title", ""), 130)
    n_comments = len((target.get("comments") or [])) if target else 0

    # ---------- NICK-style RCA header + metadata ----------
    L.append(f"# Root Cause Analysis — HSD {hsd_id}")
    L.append("")
    if ttitle and ttitle != "_not available_":
        L.append(f"**{ttitle}**")
        L.append("")
    L.append("| Field | Value |")
    L.append("|-------|-------|")
    L.append(f"| **Date** | {strftime('%Y-%m-%d')} |")
    _family = tval('family', '')
    _component = tval('component', '')
    _domains_txt = ', '.join(d for d, _ in domains) or 'general'
    _comp_cell = f"{_component} · {_domains_txt}" if _component else _domains_txt
    L.append(f"| **Platform / Family** | {plat}{' / ' + _family if _family else ''} |")
    L.append(f"| **Component / Domain** | {_comp_cell} |")
    L.append(f"| **Status / Priority** | {tval('status','—')} / {tval('priority','—')} |")
    L.append(f"| **Owner** | {tval('owner','—')} |")
    L.append(f"| **Analyser mode** | Automated (offline log + ticket analysis) |")
    L.append("")

    # Robustness guard: the ticket lists attachments but none were scanned this run
    # (transient HSDES download failure) — flag it so a thin report isn't mistaken
    # for a clean one.
    _lines_scanned = (log_findings or {}).get("lines_scanned", 0) if log_findings else 0
    if fetch_attempted and attachments and (attachments_fetched == 0 or _lines_scanned == 0):
        L.append(f"> ⚠️ **Attachment fetch incomplete** — this ticket lists "
                 f"{len(attachments)} attachment(s) but none were downloaded/scanned this run "
                 "(transient HSDES fetch failure). The evidence below is based only on the "
                 "ticket text + comments and is therefore incomplete. **Re-run the analysis** "
                 "to pull the attached logs before trusting the confidence score.")
        L.append("")

    # ---------- Artifacts under analysis ----------
    L.append("## Artifacts Under Analysis")
    L.append(f"- **Ticket:** HSD {hsd_id} — {ttitle}")
    if target.get("error"):
        L.append(f"- **Ticket fetch status:** unavailable from the current session ({target['error']})")
        L.append("- **Reason:** HSDES article/attachments could not be read with the active auth/session, so the tool did not inspect the ticket body or attachment set.")
    else:
        L.append(f"- **Comment thread:** {n_comments} comment(s) parsed")
    if attachments:
        note = (f"{attachments_fetched} downloaded &amp; scanned"
                if attachments_fetched else "not fetched — enable auto-fetch")
        L.append(f"- **Attachments:** {len(attachments)} on ticket ({note})")
        for f in (attach_files or [])[:8]:
            L.append(f"  - `{_short(f, 70)}`")
    if log_findings:
        L.append(f"- **Log volume analysed:** {log_findings.get('lines_scanned', 0)} line(s)")
    _mcp_src = target.get("mcp_sources") or []
    if _mcp_src:
        L.append(f"- **External sources queried:** {', '.join(_mcp_src)} (via MCP)")
    L.append("")

    # HSLE-Debug-Agent-style structured summary (Result / Stage Progress /
    # Symptom / Data / Evidence / Hypothesis / Conclusion / Next Actions).
    _render_debug_summary(L, hsd_id, target, log_findings, cf, rc_validation, symptoms)

    # Deterministic engineer-grade causality sections (no LLM required):
    # Timeline -> MCA Ownership -> Cause vs Noise -> Competing Hypotheses ->
    # Confidence -> Required Missing Data -> Evidence Ranking.
    _render_causality_sections(L, target, log_findings, recall, cf, evidence_audit)

    # Human-triage investigation timeline straight from the comment thread —
    # visible in the main body (not buried in the appendix) with full detail.
    _render_investigation_timeline(L, cf)

    # Explicit auth/session status in the main summary so the user can immediately
    # tell the difference between a truly empty ticket and a failed HSDES fetch.
    if target.get("error"):
        L.append("**Session status:** auth/session issue — re-run with valid HSDES access to fetch the article and attached logs.")
        L.append("")

    # ---------- Findings summary (quick 4-part overview) ----------
    sigs = (log_findings or {}).get("signatures", []) if log_findings else []
    decoded = (log_findings or {}).get("decoded") if log_findings else None
    # Real Axon recordings actually linked in the ticket (no synthetic search URLs).
    axon_links = sorted(extract_axon_uuids(target.get("full_text", "") or ""))

    L.append("---")
    L.append("")
    L.append("<details><summary>📎 Appendix — full detail (findings, methodology, decoded logs, "
             "KB, similar HSDs, references) · click to expand</summary>")
    L.append("")
    L.append(f"## Findings Summary  ·  confidence {_exec_confidence()}%")
    L.append("")

    # 1. Failure signature (attached logs & analysis)
    L.append("**1. Failure signature — from attached logs & analysis**")
    if sigs:
        L.append("- **Log keyword mentions** (raw matching lines, not distinct events): "
                 + " · ".join(f"{s['label']} (x{s['count']})" for s in sigs[:4]))
        if cf.get("root_cause"):
            L.append("- ⚠️ These broad log signatures are **incidental background telemetry** "
                     "from the verbose serial log — the actual failure is the converged root "
                     "cause in the Investigation Summary above, not these signatures.")
        for d in (log_findings.get("mca_decode") or [])[:1]:
            L.append(f"- **MCA decode:** `{d['status']}` → {d.get('mcacod_text','?')} "
                     f"(flags {', '.join(d['flags']) or 'none'})")
        if log_findings.get("last_checkpoint"):
            L.append(f"- **Last good checkpoint:** `{log_findings['last_checkpoint']}`")
        if suspected_area:
            L.append(f"- **Suspected area:** {suspected_area}")
    elif target.get("error"):
        L.append("- HSDES article / attachment access failed in this session "
                 f"({target['error']}); the tool could not inspect the actual ticket log payload. "
                 "This should not be interpreted as 'no logs attached' — it is 'logs not accessible from current auth/session'.")
    elif attachments:
        L.append(f"- {len(attachments)} attachment(s) on ticket — not fetched "
                 "(enable auto-fetch to scan logs).")
    else:
        L.append("- No logs attached to this ticket; analysis based on the "
                 "ticket description + comment thread.")
    # Deterministic decode of SOL / PythonSV / POST logs (Intel decoder DBs).
    if decoded:
        if decoded.get("mca"):
            mc = decoded["mca"]
            L.append(f"- **MCA decode ({'uncorrected' if mc['uncorrected'] else 'corrected'}, "
                     f"x{mc['count']}):** {mc.get('headline') or 'see appendix'}")
        if decoded.get("bios") and decoded["bios"].get("count"):
            bd = decoded["bios"]
            L.append(f"- **BIOS log decode ({'FATAL' if bd['fatal'] else 'warning'}, "
                     f"x{bd['count']}):** {bd.get('headline') or 'see appendix'}")
        elif decoded.get("bios") and decoded["bios"].get("benign_count"):
            bd = decoded["bios"]
            L.append(f"- **BIOS log decode:** no error codes; "
                     f"{bd['benign_count']} known expected/informational message(s) only.")
        if decoded.get("post"):
            last = decoded["post"]["codes"][-1]
            L.append(f"- **Last POST checkpoint:** `{last.get('code','')}` "
                     f"({last.get('description') or last.get('macro','')})")
            _pv = _post_verdict(decoded, target)
            if _pv:
                L.append(f"- **POST-code meaning &amp; HW verdict:** {_pv}")
    L.append("")

    # 2. Proposed root cause
    L.append("**2. Proposed root cause**")
    if cf.get("root_cause"):
        who = cf.get("root_cause_author") or "ticket"
        tag = (rc_validation["verdict"] if rc_validation else "reported")
        L.append(f"- (**{tag}**, per **{who}**) {_short(cf['root_cause'], 300)}")
        if rc_validation:
            L.append(f"- Source: {rc_validation['provenance']}")
        if suspected_area:
            L.append(f"- Mechanism/area: {suspected_area}")
    elif suspected_area:
        L.append(f"- (from logs) {suspected_area}")
    elif sigs:
        L.append(f"- (hypothesis) {sigs[0]['label']} on {plat} — see evidence below.")
    else:
        L.append("- Not yet determined from available data — see next steps.")
    if cf.get("workaround"):
        L.append(f"- **Workaround / fix:** {_short(cf['workaround'], 200)}")
    L.append("")

    # Linked Axon recordings — ONLY when the ticket actually contains Axon URLs.
    if axon_links:
        _arecs = {r["uuid"]: r for r in (target.get("axon_records") or [])}
        L.append("**Linked Axon recording(s):**")
        for u in axon_links[:6]:
            rec = _arecs.get(u)
            if rec and rec.get("available"):
                meta = " · ".join(filter(None, [
                    f"platform {rec['platform']}" if rec.get("platform") else "",
                    f"stepping {rec['stepping']}" if rec.get("stepping") else "",
                    f"plugin {rec['plugin']}" if rec.get("plugin") else "",
                    f"{len(rec.get('content_files') or [])} content file(s)"
                    if rec.get("content_files") else ""]))
                L.append(f"- {canonical_axon_url(u)} — **fetched** ({meta or 'record downloaded'})")
            elif rec:
                sigs_str = rec.get("svtools_signatures") or ""
                sigs_list = [s.strip() for s in sigs_str.split(";") if s.strip()]
                if sigs_list:
                    L.append(f"- {canonical_axon_url(u)} — **SVTools failure signatures** (via Geni):")
                    for sig in sigs_list[:6]:
                        L.append(f"  - `{sig}`")
                else:
                    L.append(f"- {canonical_axon_url(u)} — _not fetched. "
                             "Set `AXON_GENI_TOKEN` in `.env` (run acquire-tokens → axon) "
                             "to auto-fetch SVTools failure signatures._")
            else:
                L.append(f"- {canonical_axon_url(u)}")
        L.append("")

    # 3. Next steps
    L.append("**3. Proposed next steps**")
    ns: List[str] = []
    if cf.get("root_cause"):
        ns.append("Confirm the identified root cause on hardware "
                  + (f"(check {', '.join((cf.get('breadcrumbs') or {}).get('register', [])[:2])})"
                     if (cf.get('breadcrumbs') or {}).get('register') else ""))
    if cf.get("next_steps"):
        ns.append(_short(cf["next_steps"][-1], 150))
    if sigs:
        ns.append(f"Corroborate the top log signature ({sigs[0]['label']}) and decode the MCA bank.")
    if axon_links:
        ns.append("Review the linked Axon recording(s) above.")
    if cf.get("workaround"):
        ns.append("Validate the workaround and track the permanent fix.")
    if not cf.get("root_cause") and not sigs:
        ns.append("Collect serial/BIOS/OS logs + revisions (ucode/BIOS/IFWI/OS) and re-run.")
    for i, s in enumerate(dict.fromkeys([x for x in ns if x and x.strip()]), 1):
        L.append(f"{i}. {s}")
    L.append("")

    # ================= NICK-style RCA body =================
    # ---- Analysis Methodology ----
    L.append("## Analysis Methodology")
    meth: List[str] = []
    meth.append(f"Read HSD {hsd_id} in full (title, description, {n_comments} comment(s)) and "
                "reconstructed the investigation narrative from the comment thread.")
    if log_findings:
        src = "attached ticket resources" if attachments_fetched else "the provided log"
        meth.append(f"Scanned {log_findings.get('lines_scanned', 0)} log line(s) from {src} for "
                    "known failure signatures, MCA status words, and an ordered event timeline.")
    meth.append(f"Recalled the self-learning KB (best score {recall.get('best_score', 0)}, "
                f"{recall['confidence']} confidence) and queried HSDES for similar tickets.")
    if axon_links:
        meth.append(f"Reviewed the {len(axon_links)} Axon recording(s) linked in the ticket.")
    if transferred and transferred.get("summaries"):
        meth.append("Followed the transferred sub-team ticket(s) and pulled their latest "
                    "root-cause / fix status back into this report.")
    if target.get("mcp_sources"):
        meth.append("Queried the " + " and ".join(target["mcp_sources"])
                    + " agent(s) over MCP and folded their findings into the ticket context.")
    for m in meth:
        L.append(f"- {m}")
    L.append("")

    # ---- Root Cause ----
    L.append("## Root Cause")
    dom_label = ", ".join(d for d, _ in domains) or "unclassified"
    _mca_demoted, _demote_why = _mca_is_incidental(target, log_findings, cf)
    if cf.get("root_cause"):
        who = cf.get("root_cause_author") or "ticket"
        tag = (rc_validation["verdict"] if rc_validation else "reported")
        L.append(f"**Primary ({tag}, per {who}):** {_short(cf['root_cause'], 400)}")
        if suspected_area:
            L.append("")
            L.append(f"- **Mechanism / suspected area:** {suspected_area}")
    elif _mca_demoted:
        L.append(f"**Primary (reported subject / disposition — {_demote_why}):** "
                 f"{_demoted_primary_line(target, cf)}")
        if decoded and decoded.get("hypotheses"):
            L.append("")
            L.append("Decoded log telemetry (incidental — for reference only):")
            for h in decoded["hypotheses"][:3]:
                L.append(f"- ({h['severity']}) {h['text']}")
    elif _specific_root_cause(decoded, target):
        L.append(f"**Primary (narrowed from decoded evidence):** "
                 f"{_specific_root_cause(decoded, target)}")
        if decoded and decoded.get("hypotheses"):
            L.append("")
            L.append("Supporting decoded findings:")
            for h in decoded["hypotheses"][:3]:
                L.append(f"- ({h['severity']}) {h['text']}")
    elif decoded and decoded.get("hypotheses"):
        top = decoded["hypotheses"][0]
        L.append(f"**Primary (evidence-based, from decoded logs — {top['severity']}):** "
                 f"{top['text']}")
        if len(decoded["hypotheses"]) > 1:
            L.append("")
            L.append("Further decoded findings:")
            for h in decoded["hypotheses"][1:4]:
                L.append(f"- ({h['severity']}) {h['text']}")
    elif suspected_area:
        L.append(f"**Primary (derived from logs):** {suspected_area}")
    elif sigs:
        L.append(f"**Primary (hypothesis):** {sigs[0]['label']} on {plat} — {dom_label} path. "
                 "See supporting evidence in the appendix.")
    else:
        L.append("**Primary:** Not yet determined from available evidence — see the recommended "
                 "fix / next steps to collect stronger runtime data.")
    ev_lines: List[str] = []
    if decoded and decoded.get("mca"):
        mc = decoded["mca"]
        ev_lines.append(f"decoded MCA ({'uncorrected' if mc['uncorrected'] else 'corrected'}): "
                        f"{mc.get('headline') or 'see appendix'}")
    if decoded and decoded.get("bios"):
        ev_lines.append(f"decoded BIOS log: {decoded['bios'].get('headline') or 'see appendix'}")
    for d in (log_findings or {}).get("mca_decode", [])[:1]:
        ev_lines.append(f"MCA `{d['status']}` → {d.get('mcacod_text', '?')} "
                        f"(flags {', '.join(d['flags']) or 'none'})")
    if (log_findings or {}).get("last_checkpoint"):
        ev_lines.append(f"last good checkpoint `{log_findings['last_checkpoint']}`")
    for m in recall["matches"][:1]:
        r = _short(m.get("root_cause"), 120)
        if r and r != "—":
            ev_lines.append(f"KB precedent: {r}")
    if ev_lines:
        L.append("")
        L.append("**Supporting evidence:**")
        for e in ev_lines:
            L.append(f"- {e}")
    L.append("")
    L.append("**Alternative hypotheses:**")
    L.append(f"1. {dom_label} issue on {plat} consistent with the reported signature "
             f"({'KB match found' if recall['matches'] else 'no prior KB match'}).")
    L.append("2. Config / firmware / OS-build-specific behaviour — A/B the relevant revision "
             "(ucode / BIOS / IFWI / OS) between passing and failing runs.")
    L.append("")

    # ---- Root Cause Validation (provenance + trust verdict) ----
    if rc_validation:
        _V_ICON = {"VALIDATED": "✅", "PLAUSIBLE — needs confirmation": "🟡",
                   "UNVALIDATED HYPOTHESIS": "⚠️"}
        icon = _V_ICON.get(rc_validation["verdict"], "•")
        L.append("## Root Cause Validation")
        L.append(f"**Verdict:** {icon} **{rc_validation['verdict']}**")
        L.append(f"**Where it came from:** {rc_validation['provenance']}.")
        L.append("")
        L.append("| Check | Result |")
        L.append("|-------|--------|")
        for label, ok in rc_validation["checks"]:
            L.append(f"| {label} | {'✅ yes' if ok else '❌ no'} |")
        L.append("")
        L.append("**To validate this root cause:**")
        for i, t in enumerate(rc_validation["todo"], 1):
            L.append(f"{i}. {t}")
        L.append("")

    # ---- Secondary Observations ----
    sec: List[str] = []
    for s in sigs[1:4]:
        sec.append(f"Additional log signature: {s['label']} ({s['severity']}, x{s['count']}, "
                   f"{s['domain']}).")
    for label, _c in domains[1:3]:
        sec.append(f"Secondary domain in play: {label}.")
    if cf.get("tried"):
        sec.append("Already-tried paths (do not repeat): "
                   + "; ".join(_short(t, 60) for t in cf["tried"][:4]) + ".")
    if sec:
        L.append("## Secondary Observations")
        for i, s in enumerate(sec, 1):
            L.append(f"{i}. {s}")
        L.append("")

    # ---- Missing Evidence for Root Cause Determination ----
    _render_missing_evidence(L, evidence_audit)

    # ---- Recommended Fix ----
    L.append("## Recommended Fix")
    fix_steps: List[str] = []
    _has_transferred_fix = bool(transferred and any(
        s.get("fixed") for s in (transferred or {}).get("summaries", [])))
    if transferred and transferred.get("summaries"):
        for s in transferred["summaries"]:
            if s.get("fixed"):
                fix_steps.append(f"Adopt the sub-team fix from HSD {s['id']}: update the "
                                 f"**{s.get('domain') or 'responsible'}** ingredient to "
                                 f"`{s.get('ingredient')}` in the platform BKC.")
    if cf.get("workaround"):
        fix_steps.append(f"Apply / validate the recorded workaround: {_short(cf['workaround'], 180)}.")
    if cf.get("root_cause"):
        regs = (cf.get("breadcrumbs") or {}).get("register", [])[:3]
        fix_steps.append("Confirm the identified root cause on hardware"
                         + (f" (read {', '.join(regs)})" if regs else "") + ".")
    # IP-specific reads derived from the decoded bank/unit — the precise,
    # narrowed next steps (replaces generic 'replace processor' guidance).
    for s in _specific_next_steps(decoded):
        fix_steps.append(s)
    if sigs:
        fix_steps.append(f"Corroborate the top log signature ({sigs[0]['label']}) and decode the "
                         "flagged MCA bank / trace.")
    if not cf.get("root_cause") and not sigs:
        fix_steps.append("Collect serial/BIOS/OS logs + revisions (ucode/BIOS/IFWI/OS) and re-run "
                         "to capture stronger evidence.")
    if axon_links:
        fix_steps.append("Review the Axon recording(s) linked in the ticket for the failing sequence.")
    fix_steps.append("File / update the sighting with the findings.")
    for i, s in enumerate(dict.fromkeys([x for x in fix_steps if x and x.strip()]), 1):
        L.append(f"{i}. {s}")
    L.append("")
    if cf.get("root_cause") or _has_transferred_fix:
        L.append("**Expected result:** applying the fix above resolves the reported failure; "
                 "re-validate the failing scenario to confirm closure.")
    else:
        L.append("**Expected result:** the collected evidence isolates the failing domain and "
                 "confirms (or refutes) the leading hypothesis, unblocking a targeted fix.")
    L.append("")

    # Transferred-ticket sync (sub-team findings pulled back to this sighting).
    _render_transferred(L, transferred)

    L.append("> **OFFLINE mode** — deterministic report from KB + ticket data. "
             "Configure `LLM_BASE_URL` / `LLM_API_KEY` for full LLM reasoning.")
    L.append("")

    L.append("## A. Target HSD summary")
    if target and not target.get("error"):
        L.append(f"- **ID:** {hsd_id}")
        L.append(f"- **Title:** {tval('title')}")
        L.append(f"- **Platform / Family:** {plat} / {tval('family')}")
        L.append(f"- **Component:** {tval('component')}")
        L.append(f"- **Status:** {tval('status')}  |  **Priority:** {tval('priority')}")
        L.append(f"- **Owner:** {tval('owner')}")
        desc = target.get("description") or ""
        if desc:
            L.append(f"- **Description:** {desc if len(desc) <= 600 else desc[:600] + '…'}")
        if target.get("comments") is not None:
            L.append(f"- **Comments read:** {len(target.get('comments') or [])}")
        if attachments:
            fetched_note = (f" ({attachments_fetched} fetched & scanned)"
                            if attachments_fetched else " (not fetched — pass fetch_attachments)")
            L.append(f"- **Attachments on ticket:** {len(attachments)}{fetched_note}")
    else:
        reason = (target.get("error") if target
                  else "no reader token/credential supplied for this request")
        L.append(f"- **ID:** {hsd_id}")
        L.append(f"- Ticket data unavailable ({reason}).")
    L.append(f"- **Detected domain(s):** {', '.join(d for d, _ in domains) or 'general'}")
    L.append(f"- **Reported signature (input):** {symptoms}")
    L.append("")

    # Investigation narrative reconstructed from the comment thread — this is the
    # crystal-clear "what happened, in order" that a human analyst reads first.
    if cf and cf.get("narrative"):
        _KIND_ICON = {
            "ROOT CAUSE": "🎯", "WORKAROUND / FIX": "🛠️", "OBSERVED": "🔎",
            "TRIED": "🔧", "NEXT STEP": "➡️", "NOTE": "•",
        }
        from .comment_analyzer import _LABELS
        L.append(f"## A1. Investigation narrative (from {cf.get('count', 0)} comments)")
        L.append("")
        L.append("| # | Who | Kind | What they reported |")
        L.append("|---|-----|------|--------------------|")
        for ev in cf["narrative"]:
            label = _LABELS.get(ev["kind"], "NOTE")
            icon = _KIND_ICON.get(label, "•")
            who = _short(ev["author"], 18)
            what = _short(ev["text"], 150).replace("|", "\\|")
            L.append(f"| {ev['seq']} | {who} | {icon} {label} | {what} |")
        L.append("")

        if cf.get("root_cause"):
            who = cf.get("root_cause_author") or "ticket"
            L.append(f"- **Engineer observation ({who}, from comment thread — unverified):** {_short(cf['root_cause'], 320)}")
        if cf.get("workaround"):
            L.append(f"- **🛠️ Workaround / fix:** {_short(cf['workaround'], 240)}")
        if cf.get("tried"):
            L.append(f"- **Already tried (do not repeat):**")
            for t in cf["tried"][:6]:
                L.append(f"  - {_short(t, 150)}")
        if cf.get("next_steps"):
            L.append(f"- **Recorded next steps:**")
            for n in cf["next_steps"][:5]:
                L.append(f"  - {_short(n, 150)}")
        # Technical breadcrumbs pulled from the thread
        crumbs = cf.get("breadcrumbs") or {}
        if crumbs:
            _CRUMB_LABEL = {"register": "Registers", "code_site": "Code sites",
                            "socket_port": "Socket/Port", "bios_build": "BIOS builds",
                            "upi_signal": "UPI/UPLR"}
            L.append(f"- **Technical breadcrumbs:**")
            for k, items in crumbs.items():
                L.append(f"  - *{_CRUMB_LABEL.get(k, k)}:* "
                         f"{', '.join('`' + _short(i, 40) + '`' for i in items[:8])}")
        L.append(f"- **Investigation status:** {cf.get('status_hint', 'unknown')}")
        L.append("")

    # Attached-log analysis (only when logs were provided).
    if log_findings:
        L.append("## A2. Attached log analysis")
        if attachments:
            L.append(f"- **Attachments on ticket:** {len(attachments)} — "
                     f"**{attachments_fetched} downloaded & scanned**")
            if attach_files:
                L.append(f"- **Files extracted:** {', '.join(_short(f, 60) for f in attach_files[:8])}")
        L.append(f"- **Lines scanned:** {log_findings['lines_scanned']}")
        if log_findings.get("last_checkpoint"):
            L.append(f"- **Last good checkpoint:** `{log_findings['last_checkpoint']}`")
        # Suspected area + smoking-gun evidence pulled straight from the attachment.
        if log_findings.get("suspected_area"):
            L.append(f"- **🎯 Suspected area (derived from attachment):** "
                     f"{log_findings['suspected_area']}")
        evid = log_findings.get("evidence") or []
        if evid:
            L.append("")
            L.append("**Root-cause evidence extracted from the attachment "
                     "(smoking-gun lines):**")
            L.append("")
            L.append("| Category | Hits | Representative log line |")
            L.append("|----------|------|-------------------------|")
            for e in evid:
                for i, ln in enumerate(e["lines"]):
                    cat = e["category"] if i == 0 else ""
                    cnt = str(e["count"]) if i == 0 else ""
                    line = _short(ln, 120).replace("|", "\\|")
                    L.append(f"| {cat} | {cnt} | `{line}` |")
            L.append("")
        # Sequence of events (timeline)
        timeline = log_findings.get("timeline") or []
        if timeline:
            L.append("")
            L.append("**Sequence of events (from logs, in order):**")
            L.append("")
            L.append("| # | Timestamp | Event | Detail |")
            L.append("|---|-----------|-------|--------|")
            for i, ev in enumerate(timeline, 1):
                mark = " ⟵ **failure point**" if ev.get("failure_point") else ""
                cnt = f" (x{ev['count']})" if ev.get("count", 1) > 1 else ""
                detail = _short(ev["text"], 90).replace("|", "\\|")
                L.append(f"| {i} | {ev['ts'] or '—'} | {ev['label']}{cnt}{mark} | `{detail}` |")
        if log_findings["signatures"]:
            L.append("")
            L.append("**Failure signatures detected:**")
            L.append("")
            L.append("| Signature | Severity | Count | Domain | Example |")
            L.append("|-----------|----------|-------|--------|---------|")
            for s in log_findings["signatures"][:8]:
                ex = _short((s.get("examples") or [""])[0], 80).replace("|", "\\|")
                L.append(f"| {s['label']} | {s['severity']} | {s['count']} | "
                         f"{s['domain']} | `{ex}` |")
        else:
            L.append("- No known failure signatures matched in the log.")
        # MCA decode (MCi_STATUS -> flags, MCACOD, MSCOD)
        for d in (log_findings.get("mca_decode") or []):
            L.append(f"- **MCA decode:** status `{d['status']}` "
                     f"flags [{', '.join(d['flags']) or 'none'}] "
                     f"MCACOD `{d['mcacod']}` = {d.get('mcacod_text','?')}; "
                     f"MSCOD `{d['mscod']}` (model-specific) — {d['severity']}")
        L.append("")
    elif attachments:
        # Logs exist on the ticket but weren't fetched — make that explicit.
        L.append("## A2. Attached log analysis")
        L.append(f"- **{len(attachments)} attachment(s) on the ticket were NOT downloaded.** "
                 "Enable **Auto-fetch attachments** (UI) or `--fetch-attachments` (CLI) to "
                 "extract and analyze them.")
        L.append("")

    # Decoded log evidence — deterministic Intel decoder DBs (EWL/RC-Fatal/MCHECK/MCA/POST).
    if decoded:
        L.append("## A3. Decoded log evidence (Intel decoder databases)")
        L.append(f"*Log types detected: {', '.join(decoded.get('kinds') or ['generic'])}. "
                 "Decoded with the bundled EWL / RC-Fatal / MCHECK / MCA / POST databases.*")
        L.append("")
        if decoded.get("mca"):
            L.append("### MCA (Machine Check) decode")
            L.append(decoded["mca"]["summary_md"])
            L.append("")
        if decoded.get("bios"):
            L.append("### BIOS / SOL serial-log decode")
            L.append(decoded["bios"]["summary_md"])
            L.append("")
        if decoded.get("post"):
            L.append("### BIOS POST / checkpoint codes")
            L.append("| Code | Macro | Meaning |")
            L.append("|------|-------|---------|")
            for c in decoded["post"]["codes"]:
                L.append(f"| `{c.get('code','')}` | {c.get('macro','')} | "
                         f"{_short(c.get('description',''), 80)} |")
            L.append("")
            _pv = _post_verdict(decoded, target)
            if _pv:
                L.append(_pv)
                L.append("")

    L.append("## B. KB recall result")
    L.append(f"- **Confidence:** {recall['confidence']} (best score {recall['best_score']})")
    if recall["matches"]:
        for m in recall["matches"]:
            L.append(f"  - `{m.get('sig_key','')}` — root cause: "
                     f"{_short(m.get('root_cause')) or '_none recorded_'} "
                     f"(score {m.get('match_score')})")
    else:
        L.append("- No matching learned cases yet — this will seed the KB.")
    L.append("")

    L.append("## C. Similar HSDs")
    L.append("| ID | Source | Similarity reason | Root cause | Status |")
    L.append("|----|--------|-------------------|------------|--------|")
    for m in recall["matches"]:
        L.append(f"| {m.get('source_hsd') or '—'} | KB | terms: "
                 f"{', '.join(m.get('matched_terms', []))} | {_short(m.get('root_cause')) or '—'} "
                 f"| {m.get('confidence_tag','—')} |")
    for s in similar:
        L.append(f"| {s.get('id','')} | HSDES | keyword match | — | {s.get('status','')} |")
    if not recall["matches"] and not similar:
        L.append("| — | — | no matches | — | — |")
    L.append("")

    # How the most similar prior issues were resolved (root cause / fix).
    L.append("### How similar issues were resolved")
    any_res = False
    for m in recall["matches"]:
        res = _short(m.get("resolution") or m.get("root_cause"), 180)
        if res and res != "—":
            src = m.get("source_hsd") or m.get("sig_key", "")
            L.append(f"- **{src}:** {res}")
            any_res = True
    if not any_res:
        L.append("- _No recorded root cause / resolution among the similar cases yet._")
    L.append("")

    L.append("## D. Ranked root-cause hypotheses")
    dom_label = ", ".join(d for d, _ in domains) or "unclassified"
    rank = 1
    if cf.get("root_cause"):
        who = cf.get("root_cause_author") or "ticket"
        tag = "confirmed-in-ticket" if cf.get("workaround") else "leading, from comments"
        L.append(f"{rank}. *({tag})* {_short(cf['root_cause'], 320)} "
                 f"— stated by **{who}** in the comment thread.")
        rank += 1
    L.append(f"{rank}. *(hypothesis)* {dom_label} issue on {plat} consistent with the reported "
             f"signature. Evidence: ticket text; {'KB match' if recall['matches'] else 'no prior KB match'}.")
    rank += 1
    L.append(f"{rank}. *(hypothesis)* Config / firmware / OS-build specific behavior — A/B the "
             "relevant revision (ucode/BIOS/IFWI/OS) before deeper isolation.")
    L.append("")

    L.append("## E. Detailed next debug steps")
    step = 1
    # If the ticket comments already recorded a converged root cause + next step,
    # continue from there instead of restarting the investigation.
    if cf.get("root_cause"):
        L.append(f"{step}. **Confirm the comment-identified root cause on hardware.** "
                 f"{_short(cf['root_cause'], 200)}")
        crumbs = cf.get("breadcrumbs") or {}
        if crumbs.get("register"):
            L.append(f"   - Read the cited register(s): "
                     f"{', '.join('`' + r + '`' for r in crumbs['register'][:4])}.")
        if crumbs.get("socket_port"):
            L.append(f"   - Focus on: {', '.join(crumbs['socket_port'][:4])}.")
        if crumbs.get("code_site"):
            L.append(f"   - Inspect code path near: "
                     f"{', '.join('`' + c + '`' for c in crumbs['code_site'][:3])}.")
        step += 1
        if cf.get("next_steps"):
            L.append(f"{step}. **Continue the recorded plan:** "
                     f"{_short(cf['next_steps'][-1], 180)}")
            step += 1
        if cf.get("workaround"):
            L.append(f"{step}. **Validate the workaround** and track the real fix: "
                     f"{_short(cf['workaround'], 180)}")
            step += 1
    # Log-driven step when attached logs revealed something concrete.
    if log_findings and log_findings.get("signatures"):
        top = log_findings["signatures"][0]
        L.append(f"{step}. **From attached logs — {top['label']}** ({top['severity']}, "
                 f"x{top['count']}). Corroborate against the root cause above.")
        mca = (log_findings.get("mca_decode") or [])
        if mca:
            d = mca[0]
            L.append(f"   - Decode the flagged MCA bank: read `MCi_STATUS`/`MCi_ADDR`; "
                     f"status `{d['status']}` = {d.get('mcacod_text','?')} "
                     f"(flags {', '.join(d['flags']) or 'none'}).")
            L.append("   - `sv.socket<N>.uncore.mca_bank<B>.status.read()` "
                     "# confirm bank B from the log line")
        if log_findings.get("last_checkpoint"):
            L.append(f"   - Last checkpoint before failure: `{log_findings['last_checkpoint']}` "
                     "— inspect the code path right after it.")
        step += 1
    # Domain checks only when we DON'T already have a converged root cause.
    if not cf.get("root_cause"):
        if domains:
            for label, cmds in domains:
                L.append(f"{step}. **{label}** — check the domain-specific state first.")
                for c in cmds:
                    L.append(f"   - {c}")
                step += 1
        else:
            L.append(f"{step}. **Identify the failing domain** from the ticket signature, then "
                     "read that subsystem's status/log.")
            step += 1
        L.append(f"{step}. **Isolate by revision** — A/B ucode / BIOS / IFWI / BMC / OS build "
                 "between passing and failing runs.")
        step += 1
    if cf.get("tried"):
        L.append(f"{step}. **Skip already-tried paths** (recorded in comments): "
                 + "; ".join(_short(t, 60) for t in cf["tried"][:4]) + ".")
    L.append("")

    L.append("## F. Data to request/collect")
    L.append("- Full logs (serial/BIOS/OS/RPT), failing config/test, cluster/system id")
    L.append("- Revisions: silicon stepping, ucode, BIOS/IFWI, BMC/CPLD, OS build")
    L.append("- Domain specifics (MCA bank+RIP, DIMM/channel, PCIe lane, Sx target, etc.)")
    L.append("")

    L.append("## G. Learning summary")
    if cf.get("root_cause"):
        conf = "High" if cf.get("workaround") else "Medium"
    else:
        conf = "Medium" if target.get("full_text") else "Low"
    tag = "root-cause captured from comments" if cf.get("root_cause") else "signature captured"
    L.append(f"- KB entry created/updated for this signature, tagged **{conf}** ({tag}).")
    L.append("")

    L.append("## H. Known-issue verdict")
    if cf.get("root_cause") and cf.get("workaround"):
        L.append("- **Root-caused in ticket** — root cause + workaround recorded in comments "
                 "(section A1). Verify the fix lands before closing.")
    elif cf.get("root_cause"):
        L.append("- **Root cause identified** in ticket comments (section A1) — not yet "
                 "verified/fixed. Confirm on hardware.")
    elif recall["confidence"] in ("High", "Medium"):
        L.append("- **Likely known** — see KB matches in section C. Verify before closing.")
    else:
        L.append("- **Likely new sighting** — no confident KB match found.")
    L.append("")

    # I. Reference knowledge — auto-linked debug wiki pages + BIOS code areas.
    kb_blob = " ".join(filter(None, [
        symptoms,
        (log_findings or {}).get("suspected_area", "") if log_findings else "",
        " ".join(s["label"] for s in (log_findings or {}).get("signatures", [])),
        cf.get("root_cause", ""),
        " ".join(" ".join(v) for v in (cf.get("breadcrumbs") or {}).values()),
        target.get("full_text", "")[:2000],
    ]))
    knowledge = match_knowledge(kb_blob, domains=[d for d, _ in domains])
    if knowledge:
        L.append("## I. Reference knowledge & auto-suggested next steps")
        L.append("*(from the built-in Debug Knowledge Pack — real Intel debug wikis + "
                 "BIOS/firmware code areas, matched to this failure)*")
        L.append("")
        for k in knowledge:
            L.append(f"### {k['title']}")
            if k.get("summary"):
                L.append(f"{k['summary']}")
            if k.get("wiki_links"):
                L.append("- **Debug wiki pages:**")
                for w in k["wiki_links"]:
                    L.append(f"  - {w}")
            if k.get("code_paths"):
                L.append("- **BIOS / firmware code areas:**")
                for c in k["code_paths"]:
                    L.append(f"  - {c}")
            if k.get("debug_steps"):
                L.append("- **Suggested next steps:**")
                for i, s in enumerate(k["debug_steps"], 1):
                    L.append(f"  {i}. {s}")
            L.append("")

        # Optional: live BIOS-source snippets for the exact code sites in the logs.
        code_sites = ((cf.get("breadcrumbs") or {}).get("code_site") or [])
        bios = lookup_bios_code(code_sites) if code_sites else []
        if bios:
            L.append("### BIOS source at the exact code sites (from local checkout)")
            for b in bios:
                if b.get("found"):
                    L.append(f"- **{b['site']}** ({b.get('path','')}):")
                    L.append("```c")
                    L.append(b["snippet"])
                    L.append("```")
                else:
                    L.append(f"- **{b['site']}** — file not found in BIOS_REPO_PATH.")
            L.append("")
        elif code_sites and not config.BIOS_REPO_PATH:
            L.append(f"> ℹ️ Code sites seen in logs ({', '.join(code_sites[:4])}) — set "
                     "`BIOS_REPO_PATH` to a local BIOS checkout to auto-pull the source here.")
            L.append("")

    # J. Axon recordings — ONLY real recordings actually linked in the ticket.
    if axon_links:
        _arecs = {r["uuid"]: r for r in (target.get("axon_records") or [])}
        L.append("## J. Axon recordings linked in the ticket")
        for u in axon_links:
            rec = _arecs.get(u)
            L.append(f"- {canonical_axon_url(u)}")
            if rec and rec.get("available"):
                for k in ("platform", "stepping", "plugin", "config"):
                    if rec.get(k):
                        L.append(f"  - **{k.capitalize()}:** {_short(rec[k], 100)}")
                if rec.get("content_files"):
                    L.append(f"  - **Content files (decoded above):** "
                             f"{', '.join(rec['content_files'][:8])}")
            elif rec:
                L.append(f"  - _not fetched: {rec.get('note','')}_")
        L.append("")

    L.append("</details>")

    return _prepend_exec_summary("\n".join(L)), _fallback_entry(
        hsd_id, symptoms, platform, target, hsdes_enabled, comment_findings)
