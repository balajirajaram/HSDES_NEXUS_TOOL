"""Read-only recommender for historical reproduction tests."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "app" / "knowledge" / "repro_index.json"
_LEVEL_RANK = {"LEVEL_4_FIX_VALIDATED": 2, "LEVEL_3_REPRODUCED": 1}
NO_MATCH_MESSAGE = "No sufficiently similar historical case found in the Golden Corpus"


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def load_index(path: Optional[Path] = None) -> Dict[str, Any]:
    index_path = path or INDEX_PATH
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"entries": []}
    if isinstance(data, dict):
        return data
    return {"entries": []}


def _flatten(index: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for entry in index.get("entries", []):
        owner = entry.get("owning_ip", "")
        mechanism = entry.get("failure_mechanism", "")
        platform = entry.get("platform", "")
        vectors = entry.get("vectors", [])
        if isinstance(vectors, list) and vectors:
            for vec in vectors:
                rows.append({**vec, "owning_ip": owner,
                             "failure_mechanism": mechanism,
                             "platform": platform})
            continue
        recommendations = entry.get("recommendations", [])
        if isinstance(recommendations, list) and recommendations:
            for rec in recommendations:
                rows.append({**rec, "owning_ip": owner,
                             "failure_mechanism": mechanism,
                             "platform": platform})
            continue
        # Backward-compatible fallback for flat index rows.
        if all(k in entry for k in ("tool_name", "subtest_or_mode", "trigger_context")):
            rows.append(copy.deepcopy(entry))
    return rows


def _sort_key(row: Dict[str, Any]) -> tuple[int, int, str, str]:
    return (
        -int(row.get("hit_count", 0)),
        -_LEVEL_RANK.get(str(row.get("evidence_tier", "")).upper(), 0),
        str(row.get("tool_name", "")),
        str(row.get("subtest_or_mode", "")),
    )


def _materialize(rows: List[Dict[str, Any]], match_type: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in sorted(rows, key=_sort_key):
        out.append({
            "tool_name": row.get("tool_name", "unclassified"),
            "subtest_or_mode": row.get("subtest_or_mode", "unclassified"),
            "trigger_context": row.get("trigger_context", ["unknown"]),
            "match_type": match_type,
            "hit_count": int(row.get("hit_count", 0)),
            "evidence_tier": row.get("evidence_tier", "UNKNOWN"),
            "source_hsd_ids": list(row.get("source_hsd_ids", [])),
            "owning_ip": row.get("owning_ip", ""),
            "failure_mechanism": row.get("failure_mechanism", ""),
            "platform": row.get("platform", ""),
        })
    return out


def recommend_repro(owning_ip: str, failure_mechanism: str, platform: str,
                    top_n: int = 3, index: Optional[Dict[str, Any]] = None,
                    min_hit_count: int = 1) -> Dict[str, Any]:
    """Recommend historical repro workloads using exact/cross/same-IP ranking."""
    owner, mechanism, product = map(_norm, (owning_ip, failure_mechanism, platform))
    exact_rows: List[Dict[str, Any]] = []
    cross_rows: List[Dict[str, Any]] = []
    same_ip_rows: List[Dict[str, Any]] = []
    for row in _flatten(index or load_index()):
        row_owner = _norm(row.get("owning_ip"))
        row_mechanism = _norm(row.get("failure_mechanism"))
        row_platform = _norm(row.get("platform"))
        row_tier = str(row.get("evidence_tier", "")).upper()
        if row_owner != owner:
            continue
        if row_tier not in _LEVEL_RANK:
            continue
        if int(row.get("hit_count", 0)) < int(min_hit_count):
            continue
        if row_mechanism == mechanism and row_platform == product:
            exact_rows.append(row)
        elif row_mechanism == mechanism and product and row_platform and row_platform != product:
            cross_rows.append(row)
        else:
            same_ip_rows.append(row)

    exact = _materialize(exact_rows, "EXACT")
    cross = _materialize(cross_rows, "CROSS_PLATFORM_ANALOG")
    same_ip = _materialize(same_ip_rows, "SAME_IP_ONLY")

    selected = (exact + cross)[:max(1, int(top_n))]
    if len(selected) < top_n:
        selected.extend(same_ip[:top_n - len(selected)])
    if not selected:
        return {
            "match_type": "NO_MATCH",
            "message": NO_MATCH_MESSAGE,
            "results": [],
        }
    return {
        "match_type": selected[0].get("match_type", "NO_MATCH"),
        "message": "",
        "results": selected,
    }


def recommend_repro_vectors(owning_ip: str, failure_mechanism: str,
                            platform: str, top_n: int = 5,
                            library: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Backward-compatible helper returning only the ranked result list."""
    result = recommend_repro(
        owning_ip,
        failure_mechanism,
        platform,
        top_n=top_n,
        index=library if isinstance(library, dict) else None,
    )
    return result.get("results", [])


def render_repro_section(result: Dict[str, Any]) -> str:
    lines = [
        "## Suggested Reproduction Test",
        "",
        "Historical reference only -- not used in confidence or verdict calculation.",
        "",
    ]
    rows = list(result.get("results", [])) if isinstance(result, dict) else []
    if not rows:
        lines.append((result or {}).get("message") or NO_MATCH_MESSAGE + " yet.")
        return "\n".join(lines) + "\n"

    for idx, row in enumerate(rows, 1):
        context = row.get("trigger_context") or ["unknown"]
        lines.extend([
            f"### Recommendation {idx}",
            f"- **Test / workload:** {row.get('tool_name', 'unclassified')} {row.get('subtest_or_mode', 'unclassified')}",
            f"- **Match:** {row.get('match_type', 'UNKNOWN')}",
            f"- **Trigger context:** {', '.join(str(x) for x in context)}",
            f"- **Seen in:** {row.get('hit_count', 0)} prior confirmed case(s)",
            f"- **Evidence tier:** {row.get('evidence_tier', 'UNKNOWN')}",
            f"- **Source HSDs:** {', '.join(str(x) for x in (row.get('source_hsd_ids') or []))}",
            "",
        ])
    return "\n".join(lines)
