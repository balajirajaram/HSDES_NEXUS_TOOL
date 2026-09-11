"""Build the derived stress-vector index from validated Golden Cases."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from app.repro_signature_extractor import extract_repro_signature
from tools.rca_benchmark import _load_cases

_LEVEL_RANK = {"LEVEL_4_FIX_VALIDATED": 2, "LEVEL_3_REPRODUCED": 1}


def build_library(cases: list[Dict[str, Any]]) -> Dict[str, Any]:
    grouped: Dict[tuple[str, str, str], Dict[tuple[str, str, str], Dict[str, Any]]] = {}
    for case in cases:
        signature = extract_repro_signature(case)
        key = (signature["owning_ip"], signature["failure_mechanism"], signature["platform"])
        vector_key = (signature["tool_name"], signature["subtest_or_mode"], ",".join(signature["trigger_context"]))
        bucket = grouped.setdefault(key, {})
        item = bucket.setdefault(vector_key, {
            "tool_name": signature["tool_name"],
            "subtest_or_mode": signature["subtest_or_mode"],
            "trigger_context": signature["trigger_context"],
            "hit_count": 0,
            "evidence_tier": "LEVEL_3_REPRODUCED",
            "source_hsd_ids": [],
        })
        item["hit_count"] += 1
        if _LEVEL_RANK.get(str(case.get("validation_level", "")), 0) > _LEVEL_RANK.get(item["evidence_tier"], 0):
            item["evidence_tier"] = str(case["validation_level"])
        hsd_id = str(case.get("hsd_id"))
        if hsd_id not in item["source_hsd_ids"]:
            item["source_hsd_ids"].append(hsd_id)

    entries = []
    for (owner, mechanism, platform), vectors in sorted(grouped.items()):
        entries.append({
            "owning_ip": owner,
            "failure_mechanism": mechanism,
            "platform": platform,
            "vectors": sorted(vectors.values(), key=lambda item: (-item["hit_count"], item["tool_name"])),
        })
    return {"schema_version": "1.0", "source": "validated Golden Corpus", "entries": entries}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the derived stress-vector library")
    parser.add_argument("--corpus", type=Path, default=Path("golden_cases"))
    parser.add_argument("--output", type=Path,
                        default=Path("app/knowledge/stress_vector_library.json"))
    args = parser.parse_args()
    cases = _load_cases(args.corpus)
    library = build_library(cases)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(library, indent=2) + "\n", encoding="utf-8")
    vector_count = sum(len(entry["vectors"]) for entry in library["entries"])
    print(json.dumps({"cases": len(cases), "signature_entries": len(library["entries"]),
                      "vector_entries": vector_count, "output": str(args.output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
