"""Rank HSD candidates for Golden Corpus discovery.

This agent mines and ranks evidence; it does not certify truth or write
Golden Cases. Promotion remains explicitly human-approved and fail-closed.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
FIELDS = [
    "hsd_id", "platform", "owner", "root_cause", "evidence_score",
    "validation_score", "golden_score", "suggested_tier", "confidence",
    "evidence_found", "validation_found", "blockers", "recommendation",
]


def _rows(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _evidence_rows(path: Path) -> Dict[str, List[Dict[str, str]]]:
    if not path.exists():
        return {}
    result: Dict[str, List[Dict[str, str]]] = {}
    for row in _rows(path):
        result.setdefault(row.get("hsd_id", ""), []).append(row)
    return result


def mine(candidates: List[Dict[str, str]], evidence_path: Path) -> List[Dict[str, str]]:
    evidence_by_id = _evidence_rows(evidence_path)
    results = []
    for row in candidates:
        hsd_id = row.get("hsd_id", "")
        evidence = evidence_by_id.get(hsd_id, [])
        types = {item.get("evidence_type", "") for item in evidence}
        blockers = set()
        rejection = set(filter(None, (row.get("rejection_reasons") or "").split(";")))
        if row.get("platform") == "UNKNOWN":
            blockers.add("PLATFORM_CONFLICT")
        if "OWNER_OR_PLATFORM_UNRESOLVED" in rejection or not row.get("owner", "").strip():
            blockers.add("OWNERSHIP_UNRESOLVED")
        if "DECODER_AMBIGUITY" in rejection:
            blockers.add("DECODER_AMBIGUITY")
        if "OWNERSHIP_CONTRADICTION" in rejection:
            blockers.add("OWNERSHIP_CONFLICT")
        if "ROOT_CAUSE_COMMENT_ONLY" in rejection:
            blockers.add("COMMENT_ONLY_RCA")
        root_cause = bool(row.get("root_cause_summary", "").strip())
        attachment = row.get("attachments_present") == "Yes"
        owner_known = bool(row.get("owner", "").strip())
        evidence_score = 0
        evidence_found = []
        if root_cause:
            evidence_score += 20; evidence_found.append("ROOT_CAUSE")
        if attachment:
            evidence_score += 10; evidence_found.append("ATTACHMENTS")
        if owner_known:
            evidence_score += 10; evidence_found.append("OWNER")
        for field, label in (("bank", "BANK"), ("socket", "SOCKET"),
                             ("mcacod", "MCACOD"), ("mscod", "MSCOD")):
            if row.get(field, "").strip():
                evidence_score += 10; evidence_found.append(label)
        validation_score = 0
        validation_found = []
        if "REPRODUCTION" in types:
            validation_score += 25; validation_found.append("REPRODUCTION")
        if "PASS_FAIL_EXPERIMENT" in types:
            validation_score += 20; validation_found.append("PASS_FAIL_EXPERIMENT")
        if "FIX_VALIDATION" in types:
            validation_score += 30; validation_found.append("FIX_VALIDATION")
        if "ENGINEER_AGREEMENT" in types:
            validation_score += 15; validation_found.append("ENGINEER_AGREEMENT")
        if "RELATED_VALIDATED_CASE" in types:
            validation_score += 5; validation_found.append("RELATED_VALIDATED_CASE")
        golden_score = evidence_score + validation_score
        if blockers:
            golden_score -= 30 * len(blockers)
        if golden_score > 90:
            tier = "PLATINUM"
        elif golden_score > 75:
            tier = "GOLD"
        elif golden_score > 60:
            tier = "SILVER"
        else:
            tier = "BRONZE"
        # Score is a discovery signal, never a validation certificate.
        confidence = max(0, min(100, golden_score))
        recommendation = "REVIEW" if blockers else "RANK_ONLY"
        results.append({
            "hsd_id": hsd_id, "platform": row.get("platform", ""),
            "owner": row.get("owner", ""), "root_cause": row.get("root_cause_summary", ""),
            "evidence_score": str(evidence_score), "validation_score": str(validation_score),
            "golden_score": str(golden_score), "suggested_tier": tier,
            "confidence": str(confidence), "evidence_found": ";".join(evidence_found),
            "validation_found": ";".join(validation_found),
            "blockers": ";".join(sorted(blockers)),
            "recommendation": recommendation,
        })
    return sorted(results, key=lambda row: (-int(row["golden_score"]), row["hsd_id"]))


def write(path: Path, rows: List[Dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader(); writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Rank Golden Case discovery candidates")
    parser.add_argument("--candidates", type=Path, default=ROOT / "golden_candidates.csv")
    parser.add_argument("--evidence", type=Path, default=ROOT / "validation_evidence.csv")
    parser.add_argument("--output-dir", type=Path, default=ROOT)
    args = parser.parse_args()
    rows = mine(_rows(args.candidates), args.evidence)
    write(args.output_dir / "golden_mining_results.csv", rows)
    write(args.output_dir / "gold_recommended.csv", [r for r in rows if r["suggested_tier"] == "GOLD"])
    write(args.output_dir / "platinum_recommended.csv", [r for r in rows if r["suggested_tier"] == "PLATINUM"])
    write(args.output_dir / "top_50_golden_candidates.csv", rows[:50])
    print(f"Mined candidates: {len(rows)}")
    print(f"Gold-ranked: {sum(r['suggested_tier'] == 'GOLD' for r in rows)}")
    print(f"Platinum-ranked: {sum(r['suggested_tier'] == 'PLATINUM' for r in rows)}")
    print("Ranking only: no Golden Cases were created or promoted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
