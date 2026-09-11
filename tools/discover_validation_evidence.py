"""Discover validation signals across the exported RCA knowledge graph."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ["hsd_id", "evidence_type", "evidence_source", "evidence_text",
          "confidence", "validation_level", "independent"]
PATTERNS = [
    ("FIX_VALIDATION", r"fix validated|verified with latest|issue not seen|workaround verified|fixed in"),
    ("REPRODUCTION", r"reproduced|reproducible|repro"),
    ("PASS_FAIL_EXPERIMENT", r"a/b|a-b|passing.*failing|before.*after"),
    ("ENGINEER_AGREEMENT", r"agreed|confirmed by|reviewed by|team consensus"),
    ("CLOSURE_SIGNAL", r"verified|resolved|implemented|closed|complete"),
]


def discover(graph: Dict) -> List[Dict[str, str]]:
    nodes = {str(node.get("id")): node for node in graph.get("nodes", [])}
    adjacency: Dict[str, List[str]] = {key: [] for key in nodes}
    for edge in graph.get("edges", []):
        if len(edge) >= 2:
            left, right = str(edge[0]), str(edge[1])
            adjacency.setdefault(left, []).append(right)
            adjacency.setdefault(right, []).append(left)
    rows = []
    for node_id, node in nodes.items():
        text = " ".join(str(node.get(k) or "") for k in ("root_cause", "status", "platform"))
        for connected in adjacency.get(node_id, []):
            text += " " + " ".join(str(nodes.get(connected, {}).get(k) or "") for k in ("root_cause", "status"))
        for evidence_type, pattern in PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if not match:
                continue
            independent = evidence_type in {"FIX_VALIDATION", "REPRODUCTION", "PASS_FAIL_EXPERIMENT"}
            rows.append({
                "hsd_id": node_id,
                "evidence_type": evidence_type,
                "evidence_source": "RCA knowledge graph",
                "evidence_text": re.sub(r"\s+", " ", text[max(0, match.start()-100):match.end()+180])[:500],
                "confidence": "0.70" if independent else "0.40",
                "validation_level": "LEVEL_4_FIX_VALIDATED" if evidence_type == "FIX_VALIDATION" else "LEVEL_3_REPRODUCED" if independent else "UNVALIDATED",
                "independent": "Yes" if independent else "No",
            })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover validation evidence from RCA graph")
    parser.add_argument("--graph", type=Path, default=ROOT / "rca_knowledge_graph.json")
    parser.add_argument("--output", type=Path, default=ROOT / "discovered_validation_evidence.csv")
    args = parser.parse_args()
    rows = discover(json.loads(args.graph.read_text(encoding="utf-8")))
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS); writer.writeheader(); writer.writerows(rows)
    print(f"Discovered validation signals: {len(rows)}")
    print("Signals are advisory; no Golden Cases created.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
