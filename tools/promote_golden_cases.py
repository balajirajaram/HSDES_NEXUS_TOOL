"""Promote explicitly approved candidates into golden_cases/.

This is the only command in the candidate workflow allowed to write a golden
case. It fails closed on missing approval, Level 3/4 provenance, unresolved
contradiction, decoder ambiguity, or missing expected owner.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
VALID_LEVELS = {"LEVEL_3_REPRODUCED", "LEVEL_4_FIX_VALIDATED"}


def _load_rows(path: Path) -> Dict[str, Dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return {str(row.get("hsd_id", "")): row for row in csv.DictReader(handle)}


def _decision_rows(path: Path):
    with path.open(newline="", encoding="utf-8") as handle:
        yield from csv.DictReader(handle)


def promote(decisions: Path, candidates: Path, output_root: Path) -> list[Path]:
    candidate_rows = _load_rows(candidates)
    written = []
    for decision in _decision_rows(decisions):
        hsd_id = str(decision.get("hsd_id", "")).strip()
        row = candidate_rows.get(hsd_id)
        if not row:
            raise ValueError(f"{hsd_id}: not found in candidate CSV")
        if str(decision.get("decision", "")).upper() != "APPROVE":
            continue
        if row.get("approval_status") != "PREQUALIFIED":
            raise ValueError(f"{hsd_id}: candidate is not PREQUALIFIED")
        level = str(decision.get("validation_level", "")).upper()
        validator = str(decision.get("validated_by", "")).strip()
        validation_source = str(decision.get("validation_source", "")).strip()
        if level not in VALID_LEVELS:
            raise ValueError(f"{hsd_id}: approval requires Level 3 or Level 4")
        if not validator or not validation_source:
            raise ValueError(f"{hsd_id}: validator and validation_source are required")
        if row.get("rejection_reasons"):
            critical = {"ACTIVE_OWNERSHIP_CONTRADICTION", "DECODER_AMBIGUITY",
                        "ROOT_CAUSE_COMMENT_ONLY"}
            reasons = set(filter(None, row["rejection_reasons"].split(";")))
            if reasons & critical:
                raise ValueError(f"{hsd_id}: critical rejection reason remains: {reasons & critical}")
        platform = row.get("platform", "UNKNOWN").upper()
        if platform not in {"GNR", "CWF", "DMR", "COR"}:
            raise ValueError(f"{hsd_id}: unsupported platform {platform}")
        expected = {
            "owner": decision.get("expected_owner", row.get("owner", "")),
            "reporting_ip": decision.get("expected_reporting_ip", ""),
            "originating_ip": decision.get("expected_originating_ip", ""),
            "bank": decision.get("expected_bank", ""),
            "socket": decision.get("expected_socket", ""),
            "mcacod": decision.get("expected_mcacod", ""),
            "mscod": decision.get("expected_mscod", ""),
            "verdict": decision.get("expected_verdict", ""),
            "root_cause": decision.get("root_cause", row.get("root_cause_summary", "")),
        }
        if not expected["owner"]:
            raise ValueError(f"{hsd_id}: expected owner is required")
        package: Dict[str, Any] = {
            "hsd_id": hsd_id,
            "platform": platform,
            "domain": row.get("domain", "Other"),
            "validation_level": level,
            "expected": expected,
            "evidence": {
                "source": decision.get("evidence_source", "HSDES candidate package"),
                "validated_by": validator,
                "validation_source": validation_source,
                "fix_validated": level == "LEVEL_4_FIX_VALIDATED",
                "source_references": [x for x in decision.get("source_references", "").split(";") if x],
            },
            "expected_owner": expected["owner"],
            "expected_reporting_ip": expected["reporting_ip"],
            "expected_first_error": expected["originating_ip"],
            "expected_bank": expected["bank"],
            "expected_socket": expected["socket"],
            "expected_mcacod": expected["mcacod"],
            "expected_mscod": expected["mscod"],
            "expected_verdict": expected["verdict"],
            "min_confidence": 0,
            "notes": expected["root_cause"],
        }
        destination = output_root / platform / f"{hsd_id}.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")
        written.append(destination)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="Promote approved Golden Case candidates")
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, default=ROOT / "golden_candidates.csv")
    parser.add_argument("--output-root", type=Path, default=ROOT / "golden_cases")
    args = parser.parse_args()
    written = promote(args.decisions, args.candidates, args.output_root)
    print(f"Promoted {len(written)} approved case(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
