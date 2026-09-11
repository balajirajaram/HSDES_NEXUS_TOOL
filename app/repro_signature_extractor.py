"""Repro signature extraction from ticket/case text.

This module powers the derived Golden-Corpus repro index. It intentionally
stays read-only and deterministic.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "app" / "knowledge" / "repro_tool_registry.json"
LEGACY_REGISTRY_PATH = ROOT / "app" / "knowledge" / "stress_tool_registry.json"

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
    candidates = [path] if path else [REGISTRY_PATH, LEGACY_REGISTRY_PATH]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return {"tools": [], "triggers": [], "fallback_tool": "unclassified"}


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


def _entry_patterns(entry: Dict[str, Any]) -> list[str]:
    aliases = entry.get("aliases") or []
    patterns = entry.get("patterns") or []
    out: list[str] = []
    for alias in aliases:
        out.append(r"\b" + re.escape(str(alias)) + r"\b")
    for pattern in patterns:
        out.append(str(pattern))
    return out


def _extract_tool_and_subtest(title: str, registry: Dict[str, Any]) -> tuple[str, str]:
    text = str(title or "")
    best: tuple[int, int, str, int] | None = None
    for tool in registry.get("tools", []):
        name = str(tool.get("name") or "").strip()
        if not name:
            continue
        for pattern in _entry_patterns(tool):
            match = re.search(pattern, text, re.I)
            if not match:
                continue
            candidate = (match.start(), -(match.end() - match.start()), name, match.end())
            if best is None or candidate < best:
                best = candidate
    if best is None:
        fallback = str(registry.get("fallback_tool") or "unclassified")
        return fallback, "unclassified"

    tool_name = best[2]
    tail = text[best[3]:]
    tail = re.sub(r"^[\s:;,.()\[\]{}]+", "", tail)
    tail = re.sub(r"^[-_/]+", "", tail)
    tokens: list[str] = []
    for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9_/-]{1,64}", tail):
        low = token.lower()
        if low in {
            "during", "while", "with", "without", "and", "or", "seed", "testing",
            "test", "tests", "workload", "workloads", "on", "in", "of", "the",
        }:
            if tokens:
                break
            continue
        tokens.append(token)
        if len(tokens) >= 3:
            break
    if not tokens:
        return tool_name, "unclassified"
    subtest = "-".join(tokens).strip("-_/ ")
    if not subtest or subtest.lower() == tool_name.lower():
        return tool_name, "unclassified"
    return tool_name, subtest


def _extract_trigger_context(title: str, registry: Dict[str, Any]) -> list[str]:
    text = str(title or "")
    contexts: list[str] = []
    for trigger in registry.get("triggers", []):
        name = str(trigger.get("name") or "").strip()
        if not name:
            continue
        patterns = _entry_patterns(trigger)
        if name == "instruction_class":
            found = [label for label in ("AMX", "APX", "AVX512")
                     if re.search(r"\b" + re.escape(label) + r"\b", text, re.I)]
            if found:
                contexts.extend([f"instruction_class:{label}" for label in found])
            continue
        if any(re.search(pattern, text, re.I) for pattern in patterns):
            contexts.append(name)
    seen = set()
    uniq = []
    for ctx in contexts:
        if ctx not in seen:
            seen.add(ctx)
            uniq.append(ctx)
    return uniq or ["unknown"]


def extract_stress_vector(source: Any, registry: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Extract tool name, mode/subtest, and trigger context from title text."""
    registry = registry or load_registry()
    case = source if isinstance(source, dict) else {"description": source}
    workload = str(case.get("title") or case.get("workload") or case.get("test_name") or "").strip()
    if not workload:
        workload = str(case.get("notes") or case.get("description") or "").strip()
    if not workload:
        workload = "unclassified workload"
    tool_name, subtest = _extract_tool_and_subtest(workload, registry)
    triggers = _extract_trigger_context(workload, registry)
    return {
        "tool_name": tool_name,
        "subtest_or_mode": subtest,
        "trigger_context": triggers,
        "workload_description": workload,
    }


def extract_failure_mechanism(source: Dict[str, Any]) -> str:
    """Prefer existing mechanism fields; fallback to deterministic text cues."""
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
    owner = (owning_ip or str(source.get("owning_ip") or source.get("expected_owner")
                               or expected.get("owner") or source.get("owner")
                               or source.get("domain") or "")).strip()
    return {
        "owning_ip": owner,
        "failure_mechanism": extract_failure_mechanism(source),
        "platform": platform or str(source.get("platform") or ""),
        **extract_stress_vector(source),
        "mcacod": source.get("expected_mcacod") or expected.get("mcacod"),
        "mscod": source.get("expected_mscod") or expected.get("mscod"),
        "bank": source.get("expected_bank") or expected.get("bank"),
        "socket": source.get("expected_socket") or expected.get("socket"),
    }
