"""Build a non-authoritative Reference Corpus from historical mining results.

Reference cases are useful for exploratory benchmarking, but they are not
Golden Cases and must not satisfy the production qualification gate.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
FIELDS = [
    "HSD_ID", "Platform", "Owner", "Root_Cause", "EvidenceScore",
    "ConsensusScore", "ValidationSignals", "AttachmentQuality", "ClosureQuality",
    "Confidence", "ReferenceRank", "ReferenceStatus", "Limitations",
]


def _read(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def build(mining_path: Path, consensus_path: Path, evidence_path: Path) -> List[Dict[str, str]]:
    mining = {row.get("HSD_ID", row.get("hsd_id", "")): row for row in _read(mining_path)}
    consensus = {row.get("hsd_id", ""): row for row in _read(consensus_path)}
    signals: Dict[str, int] = {}
    if evidence_path.exists():
        for row in _read(evidence_path):
            signals[row.get("hsd_id", "")] = signals.get(row.get("hsd_id", ""), 0) + 1
    result = []
    for hsd_id, row in mining.items():
        if not hsd_id:
            continue
        c = consensus.get(hsd_id, {})
        evidence_score = int(row.get("EvidenceScore", row.get("evidence_score", 0)) or 0)
        consensus_score = int(row.get("ConsensusScore", c.get("consensus_score", 0)) or 0)
        validation_count = signals.get(hsd_id, 0)
        attachment_quality = 10 if "ATTACHMENTS" in (row.get("evidence_found", "")) else 0
        closure_quality = 10 if c.get("status", "").lower() in {"complete", "verified", "implemented", "closed"} else 0
        confidence = min(100, evidence_score + min(30, consensus_score // 3)
                        + min(20, validation_count * 5) + attachment_quality + closure_quality)
        limitations = ["REFERENCE_ONLY"]
        if row.get("Blockers") or c.get("blockers"):
            limitations.append("BLOCKERS_PRESENT")
        if row.get("Platform", row.get("platform", "")) == "UNKNOWN":
            limitations.append("PLATFORM_UNRESOLVED")
        result.append({
            "HSD_ID": hsd_id,
            "Platform": row.get("Platform", row.get("platform", "UNKNOWN")),
            "Owner": row.get("Owner", row.get("owner", "")),
            "Root_Cause": row.get("RootCause", row.get("root_cause", "")),
            "EvidenceScore": str(evidence_score),
            "ConsensusScore": str(consensus_score),
            "ValidationSignals": str(validation_count),
            "AttachmentQuality": str(attachment_quality),
            "ClosureQuality": str(closure_quality),
            "Confidence": str(confidence),
            "ReferenceRank": "",
            "ReferenceStatus": "REFERENCE_ONLY",
            "Limitations": ";".join(limitations),
        })
    result.sort(key=lambda item: (-int(item["Confidence"]), item["HSD_ID"]))
    for index, item in enumerate(result, 1):
        item["ReferenceRank"] = str(index)
    return result


def write(path: Path, rows: List[Dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader(); writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build exploratory Reference Corpus")
    parser.add_argument("--mining", type=Path, default=ROOT / "historical_golden_candidates.csv")
    parser.add_argument("--consensus", type=Path, default=ROOT / "consensus_candidates.csv")
    parser.add_argument("--evidence", type=Path, default=ROOT / "discovered_validation_evidence.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "reference_corpus.csv")
    parser.add_argument("--top", type=int, default=50)
    args = parser.parse_args()
    rows = build(args.mining, args.consensus, args.evidence)
    write(args.output, rows[:max(1, args.top)])
    print(f"Reference cases written: {min(len(rows), max(1, args.top))}")
    print("Reference-only mode: no Golden Cases created and no production qualification credit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
