"""RCA regression benchmark — scores NEXUS ownership accuracy against the
engineer-validated corpus in golden_cases/.

Usage:
  python -m tools.rca_benchmark
  python tools/rca_benchmark.py --no-attachments --dir golden_cases/CHA

For each golden case it runs analyze(), extracts the detected owning IP / first
error / verdict / confidence, compares against the validated expectation, and
prints a PASS/FAIL table plus the accuracy metrics. ``--offline`` is a
fixture-only audit mode: it makes no HSDES, attachment, MCP, Axon, or LLM calls
and reports predictions as unavailable. ``--no-attachments`` selects the same
offline mode for backwards-compatible bounded runs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.analyzer import analyze, extract_ownership, normalize_owner_group  # noqa: E402

CASE_TIMEOUT_SECONDS = 30


def _load_cases(root: Path) -> List[Dict[str, Any]]:
    cases: List[Dict[str, Any]] = []
    for path in sorted(root.rglob("*.json")):
        if path.name.startswith("_"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"  skip {path.name}: {exc}")
            continue
        evidence = data.get("evidence") or {}
        validation_level = str(data.get("validation_level") or "").upper()
        has_provenance = bool(evidence.get("validated_by") and
                      evidence.get("validation_source"))
        if (data.get("hsd_id") and "expected_owner" in data
            and validation_level in {"LEVEL_3_REPRODUCED", "LEVEL_4_FIX_VALIDATED"}
            and has_provenance):
            data["_file"] = str(path.relative_to(root))
            cases.append(data)
    return cases


def _match(expected: str, detected: str) -> bool:
    """Case-insensitive owner match (substring either direction)."""
    e, d = (expected or "").strip().lower(), (detected or "").strip().lower()
    if not e:
        return True
    if not d:
        return False
    return e in d or d in e


# Abstraction-level owner comparison for the report's normalized_owner_accuracy
# metric. The synonym table itself lives in app.analyzer (shared with the
# ownership-conflict detectors) — this module only adds the substring-match
# wrapper needed for benchmark comparison. This does NOT change verdict/
# confidence scoring — it is a reporting-only comparison, applied strictly
# after strict_owner_accuracy is computed and printed alongside it.
def _normalized_match(expected: str, detected: str) -> bool:
    """Abstraction-aware owner match: normalize both sides to their owning
    group before comparing, so "IFU (Core)" matches an expected "Core"."""
    return _match(normalize_owner_group(expected), normalize_owner_group(detected))


def _normalized_owner_ok(expected: str, detected: str) -> Any:
    """Return the abstraction-aware equivalent of owner_ok, preserving None
    for cases without an owner label."""
    return _normalized_match(expected, detected) if expected else None


def _optional_match(expected: Any, detected: Any) -> Any:
    """Return None for an unlabeled field, otherwise compare normalized text."""
    if expected in (None, "", []):
        return None
    return _match(str(expected), str(detected or ""))


_BANK_TOKEN_PATTERN = re.compile(
    r"(?i)(?:McBank\s*=\s*0x[0-9a-f]+|Bank\s*#?\s*\d+|MC\d{1,2}_(?:STATUS|ADDR|MISC|CTL))"
)


def _nearby_bank_token(raw_text: str, status_hex: str, window: int = 200) -> str | None:
    """Return the bank label textually adjacent to *this specific* status value
    in the original source text (e.g. "Bank 8: ba00...405"), rather than an
    unrelated bank mention from a different event elsewhere in the ticket.

    A status value can legitimately be repeated multiple times in an
    aggregated ticket (e.g. a BIOS/PythonSV trace line followed later by a
    raw kernel `mce:` line for the same event). We scan EVERY occurrence of
    the status value and pick the bank token with the smallest textual
    distance to any occurrence, rather than only checking the first one.
    """
    needle = re.sub(r"(?i)^0x", "", str(status_hex or "")).lower()
    if not needle:
        return None
    lowered = raw_text.lower()
    best_token: str | None = None
    best_distance: int | None = None
    idx = 0
    while True:
        pos = lowered.find(needle, idx)
        if pos < 0:
            break
        start = max(0, pos - window)
        matches = list(_BANK_TOKEN_PATTERN.finditer(raw_text[start:pos]))
        if matches:
            match = matches[-1]
            distance = pos - (start + match.end())
            if best_distance is None or distance < best_distance:
                best_distance = distance
                best_token = match.group(0)
        idx = pos + 1
    return best_token


_STATUS_HEX_PATTERN = re.compile(r"(?<![0-9a-fx])(?:0x)?[0-9a-f]{12,16}(?![0-9a-f])", re.I)


def _bank_id_from_token(token: str) -> str | None:
    """Normalize a matched bank token (e.g. \"Bank 8\", \"McBank = 0x3\") to a
    comparable bank-number string, so we can tell whether a ticket mentions
    one bank or genuinely multiple distinct banks."""
    match = re.search(r"McBank\s*=\s*0x([0-9a-f]+)", token, re.I)
    if match:
        return str(int(match.group(1), 16))
    match = re.search(r"Bank\s*#?\s*(\d+)", token, re.I)
    if match:
        return match.group(1)
    match = re.search(r"MC(\d{1,2})_", token, re.I)
    if match:
        return match.group(1)
    return None


def _distinct_bank_count(raw_text: str) -> int:
    tokens = _BANK_TOKEN_PATTERN.findall(raw_text)
    ids = {bid for bid in (_bank_id_from_token(t) for t in tokens) if bid is not None}
    return len(ids)


def _synthesized_bank_status_block(raw_text: str) -> str:
    """Build a `Bank X` / `MC_STATUS: 0x...` line pair for each *unique* status
    hex found in raw_text, each paired with the bank token nearest to THAT
    specific status occurrence (not a single de-duplicated block of every bank
    mention in the ticket). This gives the decoder clean structured lines to
    work with while preserving per-status bank provenance.
    """
    status_hexes = _STATUS_HEX_PATTERN.findall(raw_text)
    lines: list[str] = []
    seen: set[str] = set()
    for status_hex in status_hexes:
        key = status_hex.lower()
        if key in seen:
            continue
        seen.add(key)
        bank_token = _nearby_bank_token(raw_text, status_hex)
        if bank_token:
            lines.append(bank_token)
        lines.append(f"MC_STATUS: {status_hex}")
    return "\n".join(lines)


def _blanket_bank_context_block(raw_text: str) -> str:
    """Original safe behavior: hoist every distinct bank token, de-duplicated
    in first-occurrence order. Only correct when the ticket references a
    SINGLE bank (no ambiguity about which status it belongs to)."""
    tokens = _BANK_TOKEN_PATTERN.findall(raw_text)
    return "\n".join(dict.fromkeys(tokens))


def _fixture_machine_input(case: Dict[str, Any]) -> tuple[Dict[str, Any] | None, str, str]:
    """Build analyzer input only from explicit raw fixture evidence."""
    title = str(case.get("title") or "")
    description = str(case.get("description") or "")
    evidence = case.get("machine_evidence") or {}
    log_text = str(case.get("log_text") or case.get("evidence_text") or "")
    raw_text = "\n".join(part for part in (title, description) if part)
    # Only switch to per-status proximity matching when the ticket genuinely
    # references MULTIPLE distinct banks. For the common single-bank case,
    # bank identity is unambiguous everywhere in the text, so the original
    # blanket hoist (harmless there) is kept to avoid regressing cases whose
    # bank token isn't textually adjacent to a status value at all (e.g. a
    # standalone "McBank = 0x3" trace line far from any hex status).
    multi_bank = _distinct_bank_count(raw_text) > 1
    if not log_text and isinstance(evidence, dict):
        events = evidence.get("mca_events") or []
        first_errors = evidence.get("first_error") or evidence.get("first_errors") or []
        blanket_tokens = list(dict.fromkeys(_BANK_TOKEN_PATTERN.findall(raw_text)))
        lines = []
        for event in events if isinstance(events, list) else [events]:
            if isinstance(event, dict):
                status = event.get("status") or event.get("mc_status")
                if status:
                    if multi_bank:
                        # Only attach a bank label found next to THIS status
                        # value, not the first/last bank mention anywhere.
                        bank_token = _nearby_bank_token(raw_text, status)
                    else:
                        bank_token = blanket_tokens[0] if blanket_tokens else None
                    if bank_token:
                        lines.append(bank_token)
                    lines.append(f"MC_STATUS: {status}")
            elif event:
                lines.append(str(event))
        for item in first_errors if isinstance(first_errors, list) else [first_errors]:
            lines.append(f"IERR source={item.get('source_unit', item) if isinstance(item, dict) else item}")
        log_text = "\n".join(lines)
    parseable = re.search(
        r"0x[0-9a-f]{6,}|mcacod\s*[:=]|mscod\s*[:=]|mc.?bank|ierr|caterr|mcerr",
        raw_text, re.I)
    if not log_text and not parseable:
        return None, "", ""
    target = {
        "id": str(case["hsd_id"]), "title": title,
        "description": description, "full_text": raw_text,
        "comments": [], "comments_structured": [],
    }
    if parseable and not log_text:
        synth_block = (
            _synthesized_bank_status_block(raw_text) if multi_bank
            else _blanket_bank_context_block(raw_text)
        )
        log_text = (synth_block + "\n" if synth_block else "") + raw_text
        target["evidence_source"] = "reconstructed_from_hsd_title"
    elif log_text:
        synth_block = (
            _synthesized_bank_status_block(raw_text) if multi_bank
            else _blanket_bank_context_block(raw_text)
        )
        if synth_block:
            log_text = synth_block + "\n" + log_text
        target["evidence_source"] = case.get("evidence_source", "fixture_raw_evidence")
    return target, log_text, target.get("evidence_source", "fixture_raw_evidence")


async def _score_case(case: Dict[str, Any], fetch_attachments: bool) -> Dict[str, Any]:
    hsd_id = str(case["hsd_id"])
    result = await analyze(hsd_id, f"RCA benchmark: {case.get('notes','')}",
                           fetch_attachments=fetch_attachments)
    own = extract_ownership(result)
    expected_owner = (case.get("expected_owner") or "").strip()
    owner_ok = _match(expected_owner, own["owning_ip"]) if expected_owner else None
    reporting_ok = _optional_match(case.get("expected_reporting_ip"), own["reporting_ip"])
    bank_ok = _optional_match(case.get("expected_bank"), own["bank"])
    socket_ok = _optional_match(case.get("expected_socket"), own["socket"])
    mcacod_ok = _optional_match(case.get("expected_mcacod"), own["mcacod"])
    mscod_ok = _optional_match(case.get("expected_mscod"), own["mscod"])
    decoder_ok = _optional_match(case.get("expected_decoder_state"), own["decoder_state"])
    fe_expected = case.get("expected_first_error", "")
    fe_ok = _match(fe_expected, own["first_error"]) if fe_expected else None
    v_expected = (case.get("expected_verdict") or "").upper()
    verdict_ok = (v_expected in (own["verdict"] or "").upper()) if v_expected else None
    min_conf = int(case.get("min_confidence") or 0)
    conf_ok = (own["confidence"] >= min_conf) if min_conf else None
    # Overconfidence = tool says CONFIRMED but the owner is wrong.
    overconfident = ("CONFIRMED" in (own["verdict"] or "").upper()
                     and owner_ok is False)
    # False attribution = named a specific (non-empty) owner that is wrong.
    false_attr = bool(own["owning_ip"]) and owner_ok is False
    # Contradiction miss = corpus says a contradiction exists but the tool didn't flag it.
    exp_contra = bool(case.get("expected_contradiction"))
    contra_miss = exp_contra and not own.get("contradiction")
    field_checks = (owner_ok, reporting_ok, bank_ok, socket_ok, mcacod_ok,
                    mscod_ok, decoder_ok, fe_ok, verdict_ok, conf_ok)
    normalized_owner_ok = _normalized_owner_ok(expected_owner, own["owning_ip"])
    normalized_field_checks = (normalized_owner_ok, reporting_ok, bank_ok, socket_ok,
                               mcacod_ok, mscod_ok, decoder_ok, fe_ok, verdict_ok, conf_ok)
    passed = all(check is not False for check in field_checks)
    passed_normalized = all(check is not False for check in normalized_field_checks)
    return {
        "hsd_id": hsd_id, "file": case.get("_file", ""),
        "expected_owner": expected_owner, "detected_owner": own["owning_ip"],
        "owner_ok": owner_ok, "normalized_owner_ok": normalized_owner_ok,
        "fe_ok": fe_ok, "verdict_ok": verdict_ok, "conf_ok": conf_ok,
        "reporting_ok": reporting_ok, "bank_ok": bank_ok, "socket_ok": socket_ok,
        "mcacod_ok": mcacod_ok, "mscod_ok": mscod_ok, "decoder_ok": decoder_ok,
        "detected_reporting_ip": own["reporting_ip"], "detected_bank": own["bank"],
        "detected_socket": own["socket"], "detected_mcacod": own["mcacod"],
        "detected_mscod": own["mscod"], "detected_decoder_state": own["decoder_state"],
        "verdict": own["verdict"], "confidence": own["confidence"],
        "overconfident": overconfident, "false_attr": false_attr,
        "false_confirmed": overconfident,
        "named_owner": bool(own["owning_ip"]), "exp_contra": exp_contra,
        "contra_miss": contra_miss, "passed": passed,
        "passed_normalized": passed_normalized,
    }


async def _score_fixture_case(case: Dict[str, Any]) -> Dict[str, Any]:
    target, log_text, evidence_source = _fixture_machine_input(case)
    if target is None:
        return {"hsd_id": str(case["hsd_id"]), "file": case.get("_file", ""),
                "expected_owner": (case.get("expected_owner") or "").strip(),
                "detected_owner": "", "owner_ok": None, "normalized_owner_ok": None, "fe_ok": None,
                "verdict_ok": None, "conf_ok": None, "reporting_ok": None,
                "bank_ok": None, "socket_ok": None, "mcacod_ok": None,
                "mscod_ok": None, "decoder_ok": None, "verdict": "INSUFFICIENT_EVIDENCE",
                "confidence": 0, "overconfident": False, "false_attr": False,
                "false_confirmed": False, "named_owner": False, "exp_contra": False,
                "contra_miss": None, "passed": False, "passed_normalized": False,
                "insufficient_evidence": True,
                "evidence_source": "none", "outcome_bucket": "INSUFFICIENT_EVIDENCE",
                "outcome_reason": "No title/description/log_text/machine_evidence source available in fixture"}
    result = await analyze(str(case["hsd_id"]), f"RCA benchmark: {case.get('notes', '')}",
                           log_text=log_text, fetch_attachments=False,
                           target_override=target, offline_mode=True)
    scored = await _score_result(case, result)
    scored["evidence_source"] = evidence_source
    scored["insufficient_evidence"] = False
    decoded_evidence = ((result.get("log_findings") or {}).get("decoded") or {}).get("evidence") or {}
    mc_status = (decoded_evidence.get("mc_status") or {}).get("status") or ""
    bank_units = decoded_evidence.get("bank_units") or {}
    if scored["named_owner"]:
        scored["outcome_bucket"] = "ACTIONABLE"
        scored["outcome_reason"] = "Analyzer/decoder produced a named owning_ip"
    elif bank_units:
        scored["outcome_bucket"] = "MAPPING_GAP"
        scored["outcome_reason"] = "Decoded bank identity exists but no owner was extracted from the bank map"
    elif mc_status and mc_status.lower() not in {"0x0", "0"}:
        scored["outcome_bucket"] = "NO_BANK_PROVENANCE"
        scored["outcome_reason"] = "Non-zero MC status decoded, but no bank identity was present for map lookup"
    else:
        scored["outcome_bucket"] = "NO_OWNERSHIP_SIGNAL"
        scored["outcome_reason"] = "No non-zero MC status, bank identity, or first-error source unit produced"
    return scored


async def _score_result(case: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    own = extract_ownership(result)
    expected_owner = (case.get("expected_owner") or "").strip()
    owner_ok = _match(expected_owner, own["owning_ip"]) if expected_owner else None
    reporting_ok = _optional_match(case.get("expected_reporting_ip"), own["reporting_ip"])
    bank_ok = _optional_match(case.get("expected_bank"), own["bank"])
    socket_ok = _optional_match(case.get("expected_socket"), own["socket"])
    mcacod_ok = _optional_match(case.get("expected_mcacod"), own["mcacod"])
    mscod_ok = _optional_match(case.get("expected_mscod"), own["mscod"])
    decoder_ok = _optional_match(case.get("expected_decoder_state"), own["decoder_state"])
    fe_expected = case.get("expected_first_error", "")
    fe_ok = _match(fe_expected, own["first_error"]) if fe_expected else None
    v_expected = (case.get("expected_verdict") or "").upper()
    verdict_ok = (v_expected in (own["verdict"] or "").upper()) if v_expected else None
    min_conf = int(case.get("min_confidence") or 0)
    conf_ok = own["confidence"] >= min_conf if min_conf else None
    overconfident = "CONFIRMED" in (own["verdict"] or "").upper() and owner_ok is False
    false_attr = bool(own["owning_ip"]) and owner_ok is False
    exp_contra = bool(case.get("expected_contradiction"))
    contra_miss = exp_contra and not own.get("contradiction")
    checks = (owner_ok, reporting_ok, bank_ok, socket_ok, mcacod_ok, mscod_ok,
              decoder_ok, fe_ok, verdict_ok, conf_ok)
    normalized_owner_ok = _normalized_owner_ok(expected_owner, own["owning_ip"])
    normalized_checks = (normalized_owner_ok, reporting_ok, bank_ok, socket_ok,
                         mcacod_ok, mscod_ok, decoder_ok, fe_ok, verdict_ok, conf_ok)
    return {"hsd_id": str(case["hsd_id"]), "file": case.get("_file", ""),
            "expected_owner": expected_owner, "detected_owner": own["owning_ip"],
            "owner_ok": owner_ok, "normalized_owner_ok": normalized_owner_ok,
            "fe_ok": fe_ok, "verdict_ok": verdict_ok,
            "conf_ok": conf_ok, "reporting_ok": reporting_ok, "bank_ok": bank_ok,
            "socket_ok": socket_ok, "mcacod_ok": mcacod_ok, "mscod_ok": mscod_ok,
            "decoder_ok": decoder_ok, "detected_reporting_ip": own["reporting_ip"],
            "detected_bank": own["bank"], "detected_socket": own["socket"],
            "detected_mcacod": own["mcacod"], "detected_mscod": own["mscod"],
            "detected_decoder_state": own["decoder_state"], "verdict": own["verdict"],
            "confidence": own["confidence"], "overconfident": overconfident,
            "false_attr": false_attr, "false_confirmed": overconfident,
            "named_owner": bool(own["owning_ip"]), "exp_contra": exp_contra,
            "contra_miss": contra_miss,
            "passed": all(check is not False for check in checks),
            "passed_normalized": all(check is not False for check in normalized_checks)}


def _offline_score_case(case: Dict[str, Any]) -> Dict[str, Any]:
    """Return an auditable no-inference result without contacting any service."""
    expected_owner = (case.get("expected_owner") or "").strip()
    labeled_fields = {
        "fe_ok": bool(case.get("expected_first_error")),
        "bank_ok": case.get("expected_bank") not in (None, "", []),
        "socket_ok": case.get("expected_socket") not in (None, "", []),
        "mcacod_ok": case.get("expected_mcacod") not in (None, "", []),
        "mscod_ok": case.get("expected_mscod") not in (None, "", []),
    }
    return {
        "hsd_id": str(case["hsd_id"]), "file": case.get("_file", ""),
        "expected_owner": expected_owner, "detected_owner": "",
        "owner_ok": False if expected_owner else None,
        "normalized_owner_ok": False if expected_owner else None,
        "fe_ok": False if labeled_fields["fe_ok"] else None,
        "verdict_ok": None, "conf_ok": None,
        "reporting_ok": None, "bank_ok": False if labeled_fields["bank_ok"] else None,
        "socket_ok": False if labeled_fields["socket_ok"] else None,
        "mcacod_ok": False if labeled_fields["mcacod_ok"] else None,
        "mscod_ok": False if labeled_fields["mscod_ok"] else None,
        "decoder_ok": None, "detected_reporting_ip": "", "detected_bank": "",
        "detected_socket": "", "detected_mcacod": "", "detected_mscod": "",
        "detected_decoder_state": "", "verdict": "UNAVAILABLE", "confidence": 0,
        "overconfident": False, "false_attr": False, "false_confirmed": False,
        "named_owner": False, "exp_contra": bool(case.get("expected_contradiction")),
        "contra_miss": None, "passed": False, "passed_normalized": False, "offline": True,
    }


async def run(dir_path: str, fetch_attachments: bool, offline: bool = False,
              timeout_seconds: int = CASE_TIMEOUT_SECONDS,
              normalized_pass: bool = False) -> int:
    root = (REPO_ROOT / dir_path) if not Path(dir_path).is_absolute() else Path(dir_path)
    if not root.exists():
        print(f"No such directory: {root}")
        return 2
    cases = _load_cases(root)
    if not cases:
        print(f"No golden cases found under {root}. Add JSON cases (see README).")
        return 0
    mode = "offline fixture-only" if offline else ("with" if fetch_attachments else "without") + " attachments"
    print(f"Running {len(cases)} golden case(s) from {root} ({mode})\n")
    rows = []
    timed_out: List[str] = []
    for case in cases:
        try:
            if offline:
                rows.append(await asyncio.wait_for(
                    _score_fixture_case(case), timeout=timeout_seconds))
            else:
                rows.append(await asyncio.wait_for(
                    _score_case(case, fetch_attachments), timeout=timeout_seconds))
        except asyncio.TimeoutError:
            timed_out.append(str(case["hsd_id"]))
            rows.append({"hsd_id": str(case["hsd_id"]), "file": case.get("_file", ""),
                         "expected_owner": case["expected_owner"], "detected_owner": "TIMEOUT",
                         "owner_ok": False, "normalized_owner_ok": False,
                         "fe_ok": None, "verdict_ok": None, "conf_ok": None,
                         "reporting_ok": None, "bank_ok": None, "socket_ok": None,
                         "mcacod_ok": None, "mscod_ok": None, "decoder_ok": None,
                         "verdict": "TIMEOUT", "confidence": 0, "overconfident": False,
                         "false_attr": False, "false_confirmed": False, "named_owner": False,
                         "exp_contra": False, "contra_miss": False, "passed": False,
                         "passed_normalized": False,
                         "outcome_bucket": "TIMEOUT", "outcome_reason": f"Per-case timeout after {timeout_seconds}s"})
        except Exception as exc:
            rows.append({"hsd_id": str(case["hsd_id"]), "file": case.get("_file", ""),
                         "expected_owner": case["expected_owner"], "detected_owner": f"ERROR: {exc}",
                         "owner_ok": False, "normalized_owner_ok": False,
                         "fe_ok": None, "verdict_ok": None, "conf_ok": None,
                         "reporting_ok": None, "bank_ok": None, "socket_ok": None,
                         "mcacod_ok": None, "mscod_ok": None, "decoder_ok": None,
                         "verdict": "", "confidence": 0, "overconfident": False,
                         "false_attr": False, "false_confirmed": False, "named_owner": False, "exp_contra": False,
                         "contra_miss": False, "passed": False, "passed_normalized": False,
                         "insufficient_evidence": False, "error": f"{type(exc).__name__}: {exc}",
                         "outcome_bucket": "ERROR", "outcome_reason": f"{type(exc).__name__}: {exc}"})

    print(f"{'HSD':<14}{'Expected':<10}{'Detected':<12}{'Owner':<7}{'Verdict':<20}{'Conf':<6}{'Result'}")
    print("-" * 78)
    for r in rows:
        print(f"{r['hsd_id']:<14}{r['expected_owner']:<10}{str(r['detected_owner'])[:11]:<12}"
              f"{'PASS' if r['owner_ok'] else 'FAIL':<7}{str(r['verdict'])[:19]:<20}"
              f"{str(r['confidence'])+'%':<6}{'PASS' if r['passed'] else 'FAIL'}")
    if args_verbose:
        print("\n=== Verbose Outcome Diagnostics ===")
        print("HSD_ID\tPlatform\tOutcome_Bucket\tReason")
        for r in rows:
            platform = "UNKNOWN"
            try:
                platform = json.loads((root / r["file"]).read_text(encoding="utf-8")).get("platform", "UNKNOWN")
            except Exception:
                pass
            print(f"{r['hsd_id']}\t{platform}\t{r.get('outcome_bucket', 'UNCLASSIFIED')}\t{r.get('outcome_reason', 'No diagnostic reason recorded')}")

    n = len(rows)
    owner_rows = [r for r in rows if r["owner_ok"] is not None]
    owner_acc = (100 * sum(1 for r in owner_rows if r["owner_ok"]) / len(owner_rows)
                 if owner_rows else None)
    fe_rows = [r for r in rows if r["fe_ok"] is not None]
    fe_acc = (100 * sum(1 for r in fe_rows if r["fe_ok"]) / len(fe_rows)) if fe_rows else None
    overconf = 100 * sum(1 for r in rows if r["overconfident"]) / n
    false_attr = 100 * sum(1 for r in rows if r["false_attr"]) / n
    false_confirmed = sum(1 for r in rows if r.get("false_confirmed", False))
    # Precision = correct / (cases where the tool named an owner). Recall = correct / all.
    named = [r for r in owner_rows if r["named_owner"]]
    precision = (100 * sum(1 for r in named if r["owner_ok"]) / len(named)) if named else None
    recall = (100 * sum(1 for r in owner_rows if r["owner_ok"]) / len(owner_rows)
              if owner_rows else None)
    contra_cases = [r for r in rows if r["exp_contra"]]
    contra_miss = (100 * sum(1 for r in contra_cases if r["contra_miss"]) / len(contra_cases)) if contra_cases else None
    passed = sum(1 for r in rows if r["passed"])
    passed_normalized = sum(1 for r in rows if r.get("passed_normalized", False))
    insufficient = sum(1 for r in rows if r.get("insufficient_evidence"))
    errors = [r for r in rows if r.get("error")]
    predicted = n - insufficient - len(timed_out) - len(errors)
    actionable = [r for r in rows if r.get("named_owner")]

    def accuracy(field: str) -> Any:
        labeled = [r for r in rows if r[field] is not None]
        return (100 * sum(1 for r in labeled if r[field]) / len(labeled)
                if labeled else None)

    bank_acc = accuracy("bank_ok")
    socket_acc = accuracy("socket_ok")
    normalized_owner_ok = [_normalized_match(r["expected_owner"], r["detected_owner"]) for r in actionable]

    print("\n=== Metrics ===")
    print("Owning-IP accuracy (strict)     : " +
            (f"{(100 * sum(1 for r in actionable if r['owner_ok']) / len(actionable)):5.1f}%   "
             f"({sum(1 for r in actionable if r['owner_ok'])}/{len(actionable)} actionable predictions, literal string match)"
             if actionable else "  n/a   (no actionable owner predictions)"))
    print("Owning-IP accuracy (normalized)  : " +
            (f"{(100 * sum(normalized_owner_ok) / len(actionable)):5.1f}%   "
             f"({sum(normalized_owner_ok)}/{len(actionable)} actionable predictions, abstraction-aware synonym match)"
             if actionable else "  n/a   (no actionable owner predictions)"))
    print(f"Ownership precision     : " + (f"{precision:5.1f}%   (correct / named)" if precision is not None else "  n/a"))
    print("Ownership recall        : " +
          (f"{recall:5.1f}%   (correct / labeled cases)" if recall is not None else "  n/a"))
    print("Bank accuracy           : " + (f"{bank_acc:5.1f}%" if bank_acc is not None else "  n/a"))
    print("Socket accuracy         : " + (f"{socket_acc:5.1f}%" if socket_acc is not None else "  n/a"))
    print(f"First-error accuracy    : " + (f"{fe_acc:5.1f}%   (target > 90%)" if fe_acc is not None else "  n/a   (no labels)"))
    print(f"Overconfidence rate     : {overconf:5.1f}%   (target ~0%)")
    print(f"False-attribution rate  : {false_attr:5.1f}%   (target < 10%)")
    print(f"False-attribution count : {sum(1 for r in rows if r['false_attr'])}")
    print(f"False Confirmed RCA count: {false_confirmed}")
    print(f"Confidence calibration  : {sum(1 for r in rows if r['overconfident'])}/{n} overconfident cases")
    print(f"Contradiction miss rate : " + (f"{contra_miss:5.1f}%   (target < 5%)" if contra_miss is not None else "  n/a   (no labels)"))
    print(f"Cases passed (strict)     : {passed}/{n}")
    print(f"Cases passed (normalized) : {passed_normalized}/{n}")
    print(f"Actual predictions      : {predicted}/{n}")
    print(f"Actionable owner preds  : {len(actionable)}/{n}")
    print(f"Insufficient evidence   : {insufficient}/{n}")
    print(f"Analyzer errors         : {len(errors)}/{n}")
    if errors:
        print("Analyzer error cases    : " + ", ".join(
            f"{r['hsd_id']} ({r['error']})" for r in errors))
    print(f"Timed-out cases         : {', '.join(timed_out) if timed_out else 'none'}")
    buckets = Counter(r.get("outcome_bucket", "UNCLASSIFIED") for r in rows)
    print("Outcome buckets          : " + ", ".join(f"{key}={value}" for key, value in sorted(buckets.items())))
    return 0 if (passed_normalized == n if normalized_pass else passed == n) else 1


def main() -> None:
    ap = argparse.ArgumentParser(description="NEXUS RCA regression benchmark")
    ap.add_argument("--dir", default="golden_cases", help="corpus directory")
    ap.add_argument("--no-attachments", action="store_true",
                    help="run fixture-only offline mode with no live network calls")
    ap.add_argument("--offline", action="store_true",
                    help="run fixture-only mode with no HSDES, LLM, or attachment calls")
    ap.add_argument("--normalized-pass", action="store_true",
                    help="use abstraction-aware owner matching for the process exit code; strict scoring remains reported")
    ap.add_argument("--timeout", type=int, default=CASE_TIMEOUT_SECONDS,
                    help=f"per-case live analysis timeout in seconds (default: {CASE_TIMEOUT_SECONDS})")
    ap.add_argument("--verbose", action="store_true",
                    help="print one diagnostic outcome bucket and reason per case")
    args = ap.parse_args()
    global args_verbose
    args_verbose = args.verbose
    offline = args.offline or args.no_attachments
    rc = asyncio.run(run(args.dir, fetch_attachments=not args.no_attachments and not offline,
                         offline=offline, timeout_seconds=args.timeout,
                         normalized_pass=args.normalized_pass))
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
