"""End-to-end log triage for a fresh HSD (little/no human triage yet).

Decodes the logs typically attached to a new sighting — SOL / BIOS serial logs,
PythonSV register & MCA dumps, and BIOS POST codes — using the bundled Intel
decoder databases so the review is deterministic and needs no LLM:

  - EWL (124 major / 412 minor), RC-Fatal (49/449), IPSD, MCHECK (496)  -> BIOS/SOL
  - MCA (712 bank-specific MSCOD/MCACOD decodes)                        -> SOL RAS + PythonSV
  - BIOS POST / checkpoint codes                                        -> boot progress

The decoder modules + JSON databases live in ``app/decoders/`` and were pulled
from the intel-prompt-plugin ``bios-log-analyzer``, ``mca-log-analyzer`` and
``bios-post-code-decoder`` skills. This module wraps them and synthesizes ranked,
evidence-based hypotheses so manual triage/debug effort is minimized.
"""

import contextlib
import io
import os
import re
import sys
from typing import Any, Dict, List, Optional

_DEC_DIR = os.path.join(os.path.dirname(__file__), "decoders")
if _DEC_DIR not in sys.path:
    sys.path.insert(0, _DEC_DIR)

# Lazily-built, stdout-silenced decoder singletons (they print load banners).
_D: Dict[str, Any] = {}


def _decoders() -> Optional[Dict[str, Any]]:
    if _D:
        return _D
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            from decode_ewl import EWLDecoder
            from mca_decoder import MCADecoder
            import decode_post_code as pc
            _D["ewl"] = EWLDecoder()
            _D["mca"] = MCADecoder()
            _D["pc"] = pc
            _D["post_db"] = pc.load_database()
    except Exception:
        return None
    return _D


# --- log classification ---------------------------------------------------
_PYSV_RE = re.compile(
    r"sv\.socket|pythonsv|python\s*sv|\bitp\.|nd_cbos_sum_mca|debug\.error\.show_errors|"
    r"\.read\(\)|ktilk_ph_ctr|biosscratchpad", re.I)
_SOL_RE = re.compile(
    r"POST (?:code|progress)|progress code|Enhanced warning|RC_FATAL|RC FATAL|"
    r"MCheck|Major Warning Code|checkpoint|\bDXE\b|\bPEI\b|serial", re.I)

# PythonSV UBOX IERR/MCerr table row produced by pysvtools ip.show_mca_status
# e.g. |0|0|socket0.io0.uncore.ubox|Ierr|First|0x1|0x1|compute0|0x4800|compute0:core_coregp.0.cpucore.0|0x212edd028|Ierr logged…|
_IERR_ROW = re.compile(
    r"\|\s*(\d+)\s*\|\s*\d+\s*\|[^|]*ubox[^|]*\|\s*(Ierr|MCerr)\s*\|\s*(\w+)\s*"
    r"\|[^|]*\|[^|]*\|[^|]*\|[^|]*\|\s*([^|]+?)\s*\|\s*(0x[0-9A-Fa-f]+|)\s*\|([^|]*)\|",
    re.I)


def _parse_ierr_table(text: str) -> List[Dict[str, Any]]:
    """Extract IERR/MCerr entries from PythonSV UBOX error tables."""
    rows: List[Dict[str, Any]] = []
    seen: set = set()
    for m in _IERR_ROW.finditer(text):
        skt, err_type, priority = m.group(1), m.group(2).upper(), m.group(3)
        source_unit = m.group(4).strip()
        address = m.group(5).strip()
        note = m.group(6).strip()
        key = f"{skt}:{err_type}:{source_unit}"
        if key in seen:
            continue
        seen.add(key)
        rows.append({"socket": skt, "type": err_type, "priority": priority,
                     "source_unit": source_unit, "address": address, "note": note})
    return rows[:12]


def classify_log(text: str) -> str:
    if _PYSV_RE.search(text or ""):
        return "pythonsv"
    if _SOL_RE.search(text or ""):
        return "sol"
    return "generic"


def _first(summary_md: str, label: str) -> str:
    """Pull the first '**<label>:** ...' value out of a decoder markdown summary."""
    m = re.search(rf"\*\*{re.escape(label)}:\*\*\s*(.+)", summary_md or "")
    return m.group(1).strip() if m else ""


# --- root-cause evidence extraction (MCA bank / status / addr / misc, RC-Fatal
#     agent, socket, BIOS module) — feeds the report's "Missing Evidence" audit ---
_MC_ADDR_RE = re.compile(
    r"(?i)\b(?:IA32_)?MC(?:i|\d+)?_?ADDR\b\s*[:=]?\s*(0x[0-9A-Fa-f]{3,16})")
_MC_MISC_RE = re.compile(
    r"(?i)\b(?:IA32_)?MC(?:i|\d+)?_?MISC\b\s*[:=]?\s*(0x[0-9A-Fa-f]{3,16})")
# RC-Fatal / EWL source agent, e.g. "Agent = IIO Stack 0", "Source Agent: UPI0"
_RC_AGENT_RE = re.compile(
    r"(?i)\b(?:source\s+agent|agent|origin(?:ator)?|raised\s+by)\b\s*[:=]\s*"
    r"([A-Za-z][A-Za-z0-9 _./-]{2,40})")
_SOCKET_RE = re.compile(r"(?i)\bsocket\s*([0-9])\b|\bSKT([0-9])\b|\bS([0-9])\.(?:io|uncore)")


def _nonzero_hex(v: str) -> bool:
    try:
        return int(v, 16) != 0
    except (TypeError, ValueError):
        return False


def _extract_evidence(text: str, recs: List[Dict[str, Any]],
                      codes: List[Dict[str, Any]], post: Optional[Dict[str, Any]],
                      ierr_rows: List[Dict[str, Any]], product: str = "") -> Dict[str, Any]:
    """Pull the concrete hardware/firmware facts a GNR debug engineer needs to move
    from a generic triage line to a near-root-cause hypothesis. Only reports a field
    when it is actually present in the evidence — never guesses."""
    ev: Dict[str, Any] = {}

    # 1. MCA bank number(s) — decoded records carry a resolved bank when known.
    banks = sorted({str(r.get("bank")) for r in (recs or [])
                    if r.get("bank") not in (None, "", "Unknown")})
    if banks:
        ev["mca_banks"] = banks
        # Name each failing bank for the detected product (GNR uses its own map).
        try:
            from .decoders.bank_map import bank_label
            units = {b: bank_label(b, product) for b in banks}
            units = {b: u for b, u in units.items() if u}
            if units:
                ev["bank_units"] = units
        except Exception:
            pass

    # 2. MC_STATUS / MCACOD / MSCOD — prefer the record that best represents the
    #    fatal error: a real bank number + nonzero MCACOD/MSCOD, then DB match.
    def _rec_score(r: Dict[str, Any]) -> int:
        bank_ok = 1 if r.get("bank") not in (None, "", "Unknown") else 0
        mscod = r.get("mscod") if isinstance(r.get("mscod"), int) else 0
        mcacod = r.get("mcacod") if isinstance(r.get("mcacod"), int) else 0
        code_ok = 1 if (mscod or mcacod) else 0
        return bank_ok * 2 + code_ok * 2 + (1 if r.get("matches") else 0)

    matched = max(recs, key=_rec_score) if recs else None
    if matched:
        st = matched.get("status")
        mscod = matched.get("mscod")
        mcacod = matched.get("mcacod")
        # Decode meaning: prefer a DB match, else the '*_decoded:' hint in context.
        decode = ""
        if matched.get("matches"):
            m0 = matched["matches"][0]
            decode = (m0.get("decode") or m0.get("Decode") or "").strip()
        if not decode:
            cm = re.search(r"(?i)MSCOD_decoded:\s*([^,|\"]+)", matched.get("context", "") or "")
            if cm:
                decode = cm.group(1).strip().strip('"').strip()
        _bank = str(matched.get("bank")) if matched.get("bank") not in (None, "") else None
        _unit = ""
        if _bank is not None:
            try:
                from .decoders.bank_map import bank_label
                _unit = bank_label(_bank, product)
            except Exception:
                _unit = ""
        ev["mc_status"] = {
            "status": st if isinstance(st, str) else (hex(st) if isinstance(st, int) else None),
            "mscod": f"0x{mscod:04X}" if isinstance(mscod, int) else mscod,
            "mcacod": f"0x{mcacod:04X}" if isinstance(mcacod, int) else mcacod,
            "bank": _bank,
            "bank_unit": _unit,
            "decode": decode,
        }
        # Status flag bits (VAL/OVER/UC/EN/MISCV/ADDRV/PCC) from a 64-bit MCi_STATUS.
        raw = matched.get("status")
        sval = None
        if isinstance(raw, int):
            sval = raw
        elif isinstance(raw, str):
            try:
                sval = int(raw, 16)
            except ValueError:
                sval = None
        if isinstance(sval, int):
            ev["status_flags"] = {
                "VAL": bool(sval & (1 << 63)), "OVER": bool(sval & (1 << 62)),
                "UC": bool(sval & (1 << 61)), "EN": bool(sval & (1 << 60)),
                "MISCV": bool(sval & (1 << 59)), "ADDRV": bool(sval & (1 << 58)),
                "PCC": bool(sval & (1 << 57)),
            }

    # 3 & 4. MC_ADDR / MC_MISC — only if a valid nonzero value is logged.
    addr = next((m.group(1) for m in _MC_ADDR_RE.finditer(text) if _nonzero_hex(m.group(1))), "")
    if addr:
        ev["mc_addr"] = addr
    misc = next((m.group(1) for m in _MC_MISC_RE.finditer(text) if _nonzero_hex(m.group(1))), "")
    if misc:
        ev["mc_misc"] = misc

    # 5. RC-Fatal / EWL source agent — from an RC_FATAL/MCHECK code's context.
    for c in (codes or []):
        if c.get("type") in ("RC_FATAL", "MCHECK"):
            am = _RC_AGENT_RE.search(c.get("context", "") or "")
            if am:
                ev["rc_fatal_agent"] = am.group(1).strip()
                break

    # 6. BIOS module / phase at failure — the last decoded POST checkpoint's meaning.
    if post and post.get("codes"):
        last = post["codes"][-1]
        ev["bios_module"] = (last.get("description") or last.get("macro") or "").strip()

    # 8. Socket(s) implicated — from the IERR table plus any "socketN" mentions.
    sockets = {r.get("socket") for r in (ierr_rows or []) if r.get("socket") not in (None, "")}
    for m in _SOCKET_RE.finditer(text):
        sockets.add(next(g for g in m.groups() if g))
    sockets.discard(None)
    if sockets:
        ev["sockets"] = sorted(str(s) for s in sockets)

    return ev


def triage_logs(text: str, product: str = "") -> Optional[Dict[str, Any]]:
    """Decode every recognizable failure in the combined log text and synthesize
    ranked, evidence-based hypotheses. Returns None when nothing is decodable."""
    if not text or not text.strip():
        return None
    dec = _decoders()
    if not dec:
        return None

    out: Dict[str, Any] = {"kinds": [], "bios": None, "mca": None,
                           "post": None, "hypotheses": [], "top_severity": None}
    out["kinds"] = sorted({classify_log(chunk) for chunk in text.split("### attachment")
                           if chunk.strip()}) or [classify_log(text)]

    # --- BIOS / SOL: EWL + IPSD + RC-Fatal + MCHECK ---
    try:
        codes = dec["ewl"].parse_log(text)
    except Exception:
        codes = []
    if codes:
        with contextlib.redirect_stdout(io.StringIO()):
            summary = dec["ewl"].generate_summary(codes)
        # Count only genuine errors; exclude BENIGN (known expected/informational)
        # hits so a clean boot that merely logs e.g. tpm2_no_device or a zero-value
        # BootGuard ACM status dump is never reported as a BIOS fault. `fatal` is
        # driven by real fatal code types (RC-Fatal / MCHECK), not a regex over the
        # summary text (which contains the word "fatal" even when the count is 0).
        error_codes = [c for c in codes if c.get("type") not in ("BENIGN",)]
        fatal_codes = [c for c in error_codes if c.get("type") in ("RC_FATAL", "MCHECK")]
        out["bios"] = {
            "count": len(error_codes),
            "benign_count": len(codes) - len(error_codes),
            "summary_md": summary,
            "fatal": bool(fatal_codes),
            "headline": _first(summary, "Description") or _first(summary, "Name"),
        }

    # --- MCA: SOL RAS lines + PythonSV MCi_STATUS tables ---
    try:
        recs = dec["mca"].parse_log(text)
    except Exception:
        recs = []
    if recs:
        with contextlib.redirect_stdout(io.StringIO()):
            msum = dec["mca"].generate_summary(recs)
        _action = _first(msum, "Action")
        if _action.strip().lower() in ("n/a", "none", "na", ""):
            _action = ""
        out["mca"] = {
            "count": len(recs),
            "summary_md": msum,
            "uncorrected": bool(re.search(r"\bUC\b|uncorrected|\bUCNA\b", msum)),
            "headline": _first(msum, "Decode"),
            "action": _action,
        }

    # --- BIOS POST / checkpoint codes ---
    # Only decode POST codes from genuine checkpoint lines, so a bare "0xNN" in an
    # MCA/RC/register line is never mis-read as a POST code.
    try:
        pc = dec["pc"]
        post_lines = "\n".join(
            ln for ln in text.splitlines()
            if re.search(r"\bpost\b|progress code|checkpoint|\bPC[-:\s]", ln, re.I))
        found = pc.search_in_log(post_lines, dec["post_db"]) if post_lines.strip() else []
        decoded = [d for d in (pc.decode_code(c, dec["post_db"]) for c in found) if d]
    except Exception:
        decoded = []
    if decoded:
        out["post"] = {"codes": decoded[:12]}

    # --- PythonSV IERR / UBOX error table parser ---
    try:
        out["ierr_table"] = _parse_ierr_table(text)
    except Exception:
        out["ierr_table"] = []

    # --- concrete root-cause evidence (bank/status/addr/misc, RC agent, socket) ---
    try:
        out["evidence"] = _extract_evidence(text, recs, codes, out.get("post"),
                                            out.get("ierr_table") or [], product)
    except Exception:
        out["evidence"] = {}

    # --- Boot / Golden-Flow stage mapping (HSLE Debug Agent logic) ---
    try:
        from .boot_flow import analyze_boot_flow
        out["boot_flow"] = analyze_boot_flow(text, decoded)
    except Exception:
        out["boot_flow"] = None

    # --- severity + ranked hypotheses (zero-triage synthesis) ---
    hyps: List[Dict[str, str]] = []
    if out["mca"] and out["mca"]["uncorrected"]:
        hyps.append({"severity": "fatal",
                     "text": f"Uncorrected machine-check (MCA): {out['mca']['headline'] or 'see decode'}."
                             + (f" Action: {out['mca']['action']}" if out['mca'].get('action') else "")})
    if out["bios"] and out["bios"]["count"] and out["bios"]["fatal"]:
        hyps.append({"severity": "fatal",
                     "text": f"BIOS RC-Fatal / EWL error during firmware init: "
                             f"{out['bios']['headline'] or 'see decode'}."})
    if out["mca"] and not out["mca"]["uncorrected"]:
        hyps.append({"severity": "high",
                     "text": f"Corrected machine-check (MCA): {out['mca']['headline'] or 'see decode'}."})
    if out["bios"] and out["bios"]["count"] and not out["bios"]["fatal"]:
        hyps.append({"severity": "medium",
                     "text": f"BIOS warning(s) logged: {out['bios']['headline'] or 'see decode'}."})
    if out["post"]:
        last = out["post"]["codes"][-1]
        hyps.append({"severity": "info",
                     "text": f"Boot reached POST `{last.get('code','')}` "
                             f"({last.get('description') or last.get('macro','')}) — "
                             "inspect the phase right after this checkpoint."})
    out["hypotheses"] = hyps
    _rank = {"fatal": 3, "high": 2, "medium": 1, "info": 0}
    out["top_severity"] = max((h["severity"] for h in hyps),
                              key=lambda s: _rank.get(s, 0), default=None)
    return out if (out["bios"] or out["mca"] or out["post"]) else None
