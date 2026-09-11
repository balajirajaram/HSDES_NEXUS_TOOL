"""Rank historical consensus candidates without certifying or promoting them."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ["HSD_ID", "Platform", "Owner", "RootCause", "EvidenceScore",
          "ValidationScore", "ConsensusScore", "GoldenScore", "SuggestedTier",
          "Confidence", "Blockers", "Recommendation"]


def rows(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def rank(consensus: List[Dict[str, str]], evidence: List[Dict[str, str]]) -> List[Dict[str, str]]:
    ev_by_id: Dict[str, List[Dict[str, str]]] = {}
    for item in evidence:
        ev_by_id.setdefault(item.get("hsd_id", ""), []).append(item)
    result = []
    for item in consensus:
        hsd = item.get("hsd_id", "")
        signals = ev_by_id.get(hsd, [])
        evidence_score = min(50, int(item.get("related_case_count") or 0) * 5
                             + (10 if item.get("owner") else 0)
                             + (10 if item.get("root_cause") else 0))
        validation_score = sum(20 for signal in signals if signal.get("independent") == "Yes")
        consensus_score = int(item.get("consensus_score") or 0)
        blockers = [x for x in (item.get("blockers") or "").split(";") if x]
        golden_score = evidence_score + min(40, validation_score) + min(30, consensus_score // 3)
        if blockers:
            golden_score -= 30
        tier = "PLATINUM" if golden_score > 90 and not blockers else "GOLD" if golden_score > 75 and not blockers else "SILVER" if golden_score > 60 else "BRONZE"
        result.append({
            "HSD_ID": hsd, "Platform": item.get("platform", "UNKNOWN"),
            "Owner": item.get("owner", ""), "RootCause": item.get("root_cause", ""),
            "EvidenceScore": str(evidence_score), "ValidationScore": str(validation_score),
            "ConsensusScore": str(consensus_score), "GoldenScore": str(golden_score),
            "SuggestedTier": tier, "Confidence": str(max(0, min(100, golden_score))),
            "Blockers": ";".join(blockers),
            "Recommendation": "REVIEW" if blockers else "RANK_ONLY",
        })
    return sorted(result, key=lambda row: (-int(row["GoldenScore"]), row["HSD_ID"]))


def write(path: Path, data: List[Dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS); writer.writeheader(); writer.writerows(data)


def main() -> int:
    parser = argparse.ArgumentParser(description="Rank historical HSD consensus candidates")
    parser.add_argument("--consensus", type=Path, default=ROOT / "consensus_candidates.csv")
    parser.add_argument("--evidence", type=Path, default=ROOT / "discovered_validation_evidence.csv")
    parser.add_argument("--output-dir", type=Path, default=ROOT)
    args = parser.parse_args()
    ranked = rank(rows(args.consensus), rows(args.evidence))
    write(args.output_dir / "historical_golden_candidates.csv", ranked)
    write(args.output_dir / "historical_top_500.csv", ranked[:500])
    write(args.output_dir / "historical_top_100.csv", ranked[:100])
    write(args.output_dir / "historical_top_50.csv", ranked[:50])
    write(args.output_dir / "historical_gold_recommended.csv", [r for r in ranked if r["SuggestedTier"] == "GOLD"])
    write(args.output_dir / "historical_platinum_recommended.csv", [r for r in ranked if r["SuggestedTier"] == "PLATINUM"])
    print(f"Historical candidates: {len(ranked)}")
    print(f"Top 500/100/50: {min(500,len(ranked))}/{min(100,len(ranked))}/{min(50,len(ranked))}")
    print("Ranking only; no Golden Cases or benchmarks created.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
