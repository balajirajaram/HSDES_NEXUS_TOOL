"""Build consensus candidates from graph nodes and discovered evidence."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ["hsd_id", "platform", "owner", "root_cause", "related_case_count",
          "owner_agreement", "rca_agreement", "validation_signals", "consensus_score",
          "suggested_tier", "blockers", "recommendation"]


def _rows(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def build(graph: Dict, evidence_path: Path) -> List[Dict[str, str]]:
    evidence = defaultdict(list)
    if evidence_path.exists():
        for row in _rows(evidence_path):
            evidence[row.get("hsd_id", "")].append(row)
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    related = defaultdict(set)
    for edge in edges:
        if len(edge) >= 3 and edge[2] == "shared_signature":
            related[str(edge[0])].add(str(edge[1])); related[str(edge[1])].add(str(edge[0]))
    rows = []
    for node in nodes:
        node_id = str(node.get("id", ""))
        peers = related.get(node_id, set())
        peer_nodes = [item for item in nodes if str(item.get("id")) in peers]
        owners = {str(item.get("owner", "")).lower() for item in peer_nodes if item.get("owner")}
        roots = {str(item.get("root_cause", "")).strip().lower() for item in peer_nodes if item.get("root_cause")}
        signals = evidence.get(node_id, [])
        independent = [item for item in signals if item.get("independent") == "Yes"]
        owner_agreement = len(owners) <= 1
        rca_agreement = len(roots) <= 1
        score = min(100, len(peers) * 5 + len(owners) * 10 + len(roots) * 10 + len(independent) * 20)
        blockers = []
        if not owner_agreement: blockers.append("OWNER_DISAGREEMENT")
        if not rca_agreement: blockers.append("RCA_DISAGREEMENT")
        if str(node.get("platform", "UNKNOWN")) == "UNKNOWN":
            blockers.append("PLATFORM_UNRESOLVED")
        if blockers:
            tier = "SILVER" if score > 60 else "BRONZE"
        else:
            tier = ("PLATINUM" if score > 90 and any(x.get("evidence_type") == "FIX_VALIDATION" for x in signals)
                    else "GOLD" if score > 75 else "SILVER" if score > 60 else "BRONZE")
        rows.append({"hsd_id": node_id, "platform": str(node.get("platform", "UNKNOWN")),
                     "owner": str(node.get("owner", "")), "root_cause": str(node.get("root_cause", "")),
                     "related_case_count": str(len(peers)), "owner_agreement": "Yes" if owner_agreement else "No",
                     "rca_agreement": "Yes" if rca_agreement else "No", "validation_signals": str(len(signals)),
                     "consensus_score": str(score), "suggested_tier": tier,
                     "blockers": ";".join(blockers),
                     "recommendation": "REVIEW" if blockers else "RANK_ONLY"})
    return sorted(rows, key=lambda row: (-int(row["consensus_score"]), row["hsd_id"]))


def main() -> int:
    parser = argparse.ArgumentParser(description="Build RCA consensus candidates")
    parser.add_argument("--graph", type=Path, default=ROOT / "rca_knowledge_graph.json")
    parser.add_argument("--evidence", type=Path, default=ROOT / "discovered_validation_evidence.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "consensus_candidates.csv")
    args = parser.parse_args()
    rows = build(json.loads(args.graph.read_text(encoding="utf-8")), args.evidence)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS); writer.writeheader(); writer.writerows(rows)
    print(f"Consensus candidates: {len(rows)}")
    print("Consensus is ranking evidence, not authoritative validation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
