"""Read-only ranking engine for historical stress-vector recommendations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
LIBRARY_PATH = ROOT / "app" / "knowledge" / "stress_vector_library.json"
_LEVEL_RANK = {"LEVEL_4_FIX_VALIDATED": 2, "LEVEL_3_REPRODUCED": 1}


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def load_library(path: Optional[Path] = None) -> Dict[str, Any]:
    library_path = path or LIBRARY_PATH
    try:
        return json.loads(library_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"entries": []}


def _flatten(library: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for entry in library.get("entries", []):
        for vector in entry.get("vectors", []):
            rows.append({**vector, "owning_ip": entry.get("owning_ip", ""),
                         "failure_mechanism": entry.get("failure_mechanism", ""),
                         "platform": entry.get("platform", "")})
    return rows


def recommend_repro_vectors(owning_ip: str, failure_mechanism: str,
                            platform: str, top_n: int = 5,
                            library: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Return ranked exact, cross-platform, then same-IP recommendations."""
    owner, mechanism, product = map(_norm, (owning_ip, failure_mechanism, platform))
    exact: List[Dict[str, Any]] = []
    cross: List[Dict[str, Any]] = []
    same_ip: List[Dict[str, Any]] = []
    for row in _flatten(library or load_library()):
        row_owner = _norm(row.get("owning_ip"))
        row_mechanism = _norm(row.get("failure_mechanism"))
        row_platform = _norm(row.get("platform"))
        if row_owner != owner:
            continue
        if row_mechanism == mechanism and row_platform == product:
            match_type, target = "EXACT", exact
        elif row_mechanism == mechanism and row_platform != product:
            match_type, target = "CROSS_PLATFORM_ANALOG", cross
        else:
            match_type, target = "SAME_IP_ONLY", same_ip
        target.append({**row, "match_type": match_type})

    def sort_key(row: Dict[str, Any]) -> tuple[int, int, str]:
        return (-int(row.get("hit_count", 0)), -_LEVEL_RANK.get(str(row.get("evidence_tier", "")), 0), str(row.get("tool_name", "")))

    exact.sort(key=sort_key)
    cross.sort(key=sort_key)
    same_ip.sort(key=sort_key)
    selected = (exact + cross)[:top_n]
    if len(selected) < top_n:
        selected.extend(same_ip[:top_n - len(selected)])
    return selected
