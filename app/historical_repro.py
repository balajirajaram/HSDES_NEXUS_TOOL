"""Read-only historical reproduction matching over Golden Case fixtures."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Iterable, List

_LEVEL_RANK = {"LEVEL_4_FIX_VALIDATED": 2, "LEVEL_3_REPRODUCED": 1}
_MATCH_FIELDS = ("mcacod", "mscod", "bank", "socket")


def load_cases(root: Path) -> List[Dict[str, Any]]:
    cases: List[Dict[str, Any]] = []
    for path in sorted(root.rglob("*.json")):
        if path.name.startswith("_"):
            continue
        try:
            data = __import__("json").loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        evidence = data.get("evidence") or {}
        if (data.get("hsd_id") and data.get("expected_owner") and
                str(data.get("validation_level", "")).upper() in _LEVEL_RANK and
                evidence.get("validated_by") and evidence.get("validation_source")):
            data["_file"] = str(path.relative_to(root))
            cases.append(data)
    return cases


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _owner(case: Dict[str, Any]) -> str:
    return str(case.get("expected_owner") or case.get("owner") or case.get("domain") or "")


def _case_text(case: Dict[str, Any]) -> str:
    expected = case.get("expected") or {}
    return " ".join(str(case.get(key) or "") for key in
                     ("title", "notes", "description")) + " " + str(expected.get("root_cause") or "")


def _workload(case: Dict[str, Any]) -> str:
    title = str(case.get("title") or case.get("workload") or case.get("test_name") or "").strip()
    if title:
        return title
    notes = str(case.get("notes") or "").strip()
    return notes or "Historical workload not recorded in fixture"


def _failure_class(case_or_signature: Dict[str, Any]) -> str:
    text = " ".join(str(case_or_signature.get(key) or "") for key in
                     ("title", "notes", "description", "keywords", "failure_class")).lower()
    for label, pattern in (("tor_timeout", r"tor[_ -]?timeout|3[- ]strike"),
                           ("kernel_panic", r"kernel panic|oops|call trace"),
                           ("ierr_mce", r"ierr|mce|machine check"),
                           ("poison", r"poison|mcacod")):
        if re.search(pattern, text):
            return label
    return _norm(case_or_signature.get("mcacod")) + ":" + _norm(case_or_signature.get("mscod"))


def _resolution(case: Dict[str, Any]) -> str:
    evidence = case.get("evidence") or {}
    return str(evidence.get("validation_source") or case.get("resolution") or
               case.get("notes") or "Resolution not recorded")


def _field_matches(signature: Dict[str, Any], case: Dict[str, Any]) -> List[str]:
    matched: List[str] = []
    for field in _MATCH_FIELDS:
        wanted = _norm(signature.get(field))
        if wanted and wanted == _norm(case.get("expected_" + field)):
            matched.append(field)
    return matched


def match_historical_repro(signature: Dict[str, Any], cases: Iterable[Dict[str, Any]]) -> Dict[str, Any] | None:
    """Return the best historical match, or None below the minimum threshold."""
    platform = _norm(signature.get("platform"))
    owner = _norm(signature.get("owner") or signature.get("owning_ip") or signature.get("component_nature"))
    failure_class = _failure_class(signature)
    ranked: List[tuple[int, Dict[str, Any]]] = []
    for case in cases:
        case_platform = _norm(case.get("platform"))
        case_owner = _norm(_owner(case))
        fields = _field_matches(signature, case)
        if platform and owner and case_platform == platform and case_owner == owner and len(fields) == sum(bool(_norm(signature.get(f))) for f in _MATCH_FIELDS):
            confidence = "EXACT"
            score = 300 + len(fields) * 10
        elif platform and owner and case_platform == platform and case_owner == owner:
            confidence = "PARTIAL"
            score = 200 + len(fields) * 5
        elif owner and case_owner == owner and _failure_class(case) == failure_class:
            confidence = "CROSS_PLATFORM_ANALOG"
            score = 100 + len(fields) * 2
        else:
            continue
        score += _LEVEL_RANK.get(str(case.get("validation_level", "")).upper(), 0) * 3
        score += 2 if case.get("bugeco_id") else 0
        ranked.append((score, {"case": case, "confidence": confidence, "matched_fields": fields}))
    if not ranked:
        return None
    _, selected = max(ranked, key=lambda item: item[0])
    case = selected["case"]
    return {
        "suggested_repro_test": _workload(case),
        "hsd_id": str(case["hsd_id"]),
        "platform": case.get("platform", "UNKNOWN"),
        "owner": _owner(case),
        "confidence": selected["confidence"],
        "matched_fields": selected["matched_fields"],
        "match_basis": "+".join((["platform", "owner"] if selected["confidence"] != "CROSS_PLATFORM_ANALOG" else ["owner", "failure_class"]) + selected["matched_fields"]),
        "resolution": _resolution(case),
        "evidence_tier": case.get("validation_level", "UNKNOWN"),
        "bugeco_id": case.get("bugeco_id", ""),
    }


def render_section(match: Dict[str, Any] | None) -> str:
    header = "## Suggested Reproduction / Historical Match"
    note = "Historical reference — not used in confidence or verdict calculation."
    if not match:
        return f"{header}\n\n{note}\n\nNo sufficiently similar historical case found in the Golden Corpus.\n"
    bugeco = f"\n\n  Bugeco ID: {match['bugeco_id']}" if match.get("bugeco_id") else ""
    return (f"{header}\n\n{note}\n\n"
            f"Suggested Repro Test:\n  {match['suggested_repro_test']}\n\n"
            f"Matched Historical Case:\n  HSD {match['hsd_id']}, Platform {match['platform']}, Owner {match['owner']}\n\n"
            f"Match Confidence:\n  {match['confidence']}\n\n"
            f"Match Basis:\n  {match['match_basis']}\n\n"
            f"Historical Resolution:\n  {match['resolution']}\n\n"
            f"Evidence Tier:\n  {match['evidence_tier']}{bugeco}\n")
