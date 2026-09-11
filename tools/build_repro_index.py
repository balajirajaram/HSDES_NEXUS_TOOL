"""Build the derived historical-repro index from validated Golden Cases."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.repro_signature_extractor import extract_repro_signature
from tools.rca_benchmark import _load_cases

_LEVEL_RANK = {"LEVEL_4_FIX_VALIDATED": 2, "LEVEL_3_REPRODUCED": 1}


def _sort_key(row: Dict[str, Any]) -> tuple[int, int, str, str]:
    return (
        -int(row.get("hit_count", 0)),
        -_LEVEL_RANK.get(str(row.get("evidence_tier", "")).upper(), 0),
        str(row.get("tool_name", "")),
        str(row.get("subtest_or_mode", "")),
    )


def build_repro_index(cases: list[Dict[str, Any]]) -> Dict[str, Any]:
    grouped: Dict[tuple[str, str, str], Dict[tuple[str, str, str], Dict[str, Any]]] = {}
    tool_names = set()

    for case in cases:
        signature = extract_repro_signature(case)
        owner = str(signature.get("owning_ip") or "UNKNOWN").strip() or "UNKNOWN"
        mechanism = str(signature.get("failure_mechanism") or "other").strip() or "other"
        platform = str(signature.get("platform") or case.get("platform") or "UNKNOWN").strip() or "UNKNOWN"

        tool_name = str(signature.get("tool_name") or "unclassified")
        subtest = str(signature.get("subtest_or_mode") or "unclassified")
        context = signature.get("trigger_context") or ["unknown"]
        context_key = ",".join(str(item) for item in context)

        bucket = grouped.setdefault((owner, mechanism, platform), {})
        key = (tool_name, subtest, context_key)
        row = bucket.setdefault(
            key,
            {
                "tool_name": tool_name,
                "subtest_or_mode": subtest,
                "trigger_context": list(context),
                "hit_count": 0,
                "evidence_tier": "LEVEL_3_REPRODUCED",
                "source_hsd_ids": [],
            },
        )
        row["hit_count"] += 1

        level = str(case.get("validation_level") or "").upper()
        if _LEVEL_RANK.get(level, 0) > _LEVEL_RANK.get(str(row.get("evidence_tier", "")).upper(), 0):
            row["evidence_tier"] = level

        hsd_id = str(case.get("hsd_id") or "")
        if hsd_id and hsd_id not in row["source_hsd_ids"]:
            row["source_hsd_ids"].append(hsd_id)

        tool_names.add(tool_name)

    entries = []
    recommendation_count = 0
    for (owner, mechanism, platform), recs in sorted(grouped.items()):
        rows = sorted(recs.values(), key=_sort_key)
        recommendation_count += len(rows)
        entries.append(
            {
                "owning_ip": owner,
                "failure_mechanism": mechanism,
                "platform": platform,
                "recommendations": rows,
            }
        )

    return {
        "schema_version": 2,
        "source": "validated Golden Corpus",
        "case_count": len(cases),
        "entry_count": len(entries),
        "recommendation_count": recommendation_count,
        "tool_name_count": len(tool_names),
        "tool_names": sorted(tool_names),
        "entries": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build historical reproduction index")
    parser.add_argument("--corpus", type=Path, default=Path("golden_cases"))
    parser.add_argument("--output", type=Path, default=Path("app/knowledge/repro_index.json"))
    args = parser.parse_args()

    cases = _load_cases(args.corpus)
    index = build_repro_index(cases)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "cases": index["case_count"],
                "entries": index["entry_count"],
                "recommendations": index["recommendation_count"],
                "tool_name_count": index["tool_name_count"],
                "output": str(args.output),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
