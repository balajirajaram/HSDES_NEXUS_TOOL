"""Generic stress-vector and failure-signature extraction for repro matching."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "app" / "knowledge" / "stress_tool_registry.json"

_FAILURE_PATTERNS = (
    ("3-strike", re.compile(r"3[- ]strike|watchdog|wdtimeout|internal timer", re.I)),
    ("TOR_TIMEOUT", re.compile(r"tor[_ -]?timeout|tor timeout", re.I)),
    ("parity", re.compile(r"parity", re.I)),
    ("poison", re.compile(r"poison", re.I)),
    ("FRC", re.compile(r"\bFRC\b|forward recovery", re.I)),
    ("IERR/CATERR", re.compile(r"IERR|CATERR|MCERR", re.I)),
    ("kernel_panic", re.compile(r"kernel panic|kernel oops|call trace", re.I)),
    ("soft_lockup", re.compile(r"soft lockup|hung task", re.I)),
    ("coredump/segfault", re.compile(r"coredump|core dump|segfault|segmentation fault", re.I)),
)


def load_registry(path: Optional[Path] = None) -> Dict[str, Any]:
    registry_path = path or REGISTRY_PATH
    return json.loads(registry_path.read_text(encoding="utf-8"))


def _text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_text(item) for item in value)
    return str(value or "")


def _case_text(case: Dict[str, Any]) -> str:
    expected = case.get("expected") or {}
    return " ".join(_text(case.get(key)) for key in
                     ("title", "description", "notes", "workload", "test_name", "keywords")) + " " + _text(expected.get("root_cause"))


def _first_registry_match(text: str, entries: list[Dict[str, Any]]) -> str:
    for entry in entries:
        if any(re.search(pattern, text, re.I) for pattern in entry.get("patterns", [])):
            return str(entry.get("name") or "")
    return ""


def extract_stress_vector(source: Any, registry: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Extract a generic stress vector from any ticket/case text."""
    registry = registry or load_registry()
    case = source if isinstance(source, dict) else {"description": source}
    text = _case_text(case)
    tool_name = _first_registry_match(text, registry.get("tools", [])) or "unclassified"
    subtest = _first_registry_match(text, registry.get("subtests", [])) or "unknown"
    triggers = [str(entry.get("name")) for entry in registry.get("triggers", [])
                if any(re.search(pattern, text, re.I) for pattern in entry.get("patterns", []))]
    workload = str(case.get("title") or case.get("workload") or case.get("test_name") or "").strip()
    if not workload:
        workload = str(case.get("notes") or case.get("description") or "").strip()
    if not workload:
        workload = "unclassified workload"
    return {
        "tool_name": tool_name,
        "subtest_or_mode": subtest,
        "trigger_context": triggers or ["unknown"],
        "workload_description": workload,
    }


def extract_failure_mechanism(source: Dict[str, Any]) -> str:
    """Prefer an existing computed mechanism; use text only for corpus indexing."""
    for key in ("failure_mechanism", "mechanism", "expected_failure_mechanism"):
        if source.get(key):
            return str(source[key])
    text = _case_text(source)
    for mechanism, pattern in _FAILURE_PATTERNS:
        if pattern.search(text):
            return mechanism
    return "other"


def extract_repro_signature(source: Dict[str, Any], owning_ip: str = "",
                            platform: str = "") -> Dict[str, Any]:
    expected = source.get("expected") or {}
    return {
        "owning_ip": owning_ip or str(source.get("expected_owner") or source.get("owner") or source.get("domain") or ""),
        "failure_mechanism": extract_failure_mechanism(source),
        "platform": platform or str(source.get("platform") or ""),
        **extract_stress_vector(source),
        "mcacod": source.get("expected_mcacod") or expected.get("mcacod"),
        "mscod": source.get("expected_mscod") or expected.get("mscod"),
        "bank": source.get("expected_bank") or expected.get("bank"),
        "socket": source.get("expected_socket") or expected.get("socket"),
    }
