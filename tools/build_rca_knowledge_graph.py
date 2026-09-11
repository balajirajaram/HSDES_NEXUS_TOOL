"""Build a deterministic RCA knowledge graph from exported HSDES records.

This mines relationships; it does not certify RCA or promote Golden Cases.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]


def _platform(record: Dict[str, Any]) -> str:
    text = " ".join(str(record.get(key) or "") for key in
                    ("platform", "product_found", "family_affected", "title"))
    match = re.search(r"(?i)\b(GNR|SRF|CWF|DMR|COR)\b", text)
    return match.group(1).upper() if match else "UNKNOWN"


def _text(record: Dict[str, Any]) -> str:
    return " ".join(str(record.get(k) or "") for k in (
        "title", "description", "comments", "root_cause", "root_cause_summary",
        "fix_description", "resolution", "tag"))


def _tokens(text: str) -> List[str]:
    return sorted(set(re.findall(r"(?i)\b(?:mcacod|mscod)\s*[:=]?\s*0x[0-9a-f]+|HW\.[A-Z0-9_.-]+|\b(?:upi|pcie|cxl|imc|punit|ccf|cha|memory|mca)\b", text)))


def build(payload: Any) -> Dict[str, Any]:
    records = payload.get("articles", payload) if isinstance(payload, dict) else payload
    records = [r for r in records or [] if isinstance(r, dict)]
    nodes = []
    indexes = defaultdict(list)
    for record in records:
        node_id = str(record.get("id") or record.get("hsd_id") or "")
        if not node_id:
            continue
        text = _text(record)
        node = {
            "id": node_id,
            "platform": _platform(record),
            "status": record.get("status", ""),
            "owner": record.get("owner", ""),
            "root_cause": record.get("root_cause") or record.get("root_cause_summary") or "",
            "signature_tokens": _tokens(text),
            "attachments": record.get("attachments") or [],
            "transferred_id": record.get("transferred_id") or record.get("transferredId") or "",
            "duplicate_id": record.get("merge_id") or record.get("duplicate_id") or "",
            "related_ids": record.get("related_ids") or [],
        }
        nodes.append(node)
        for token in node["signature_tokens"]:
            indexes[("signature", token)].append(node_id)
        if node["owner"]:
            indexes[("owner", str(node["owner"]).lower())].append(node_id)
        if node["platform"] != "UNKNOWN":
            indexes[("platform", str(node["platform"]).lower())].append(node_id)
    edges = set()
    for node in nodes:
        for key in ("transferred_id", "duplicate_id"):
            target = str(node.get(key) or "")
            if target:
                edges.add((node["id"], target, key))
        for token in node["signature_tokens"]:
            for other in indexes[("signature", token)]:
                if other != node["id"]:
                    edges.add(tuple(sorted((node["id"], other))) + ("shared_signature",))
    return {"schema_version": "1.0", "node_count": len(nodes),
            "edge_count": len(edges), "nodes": nodes,
            "edges": [list(edge) for edge in sorted(edges)]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build RCA knowledge graph")
    parser.add_argument("--input", type=Path, default=ROOT / "hsdes_candidates.json")
    parser.add_argument("--output", type=Path, default=ROOT / "rca_knowledge_graph.json")
    args = parser.parse_args()
    graph = build(json.loads(args.input.read_text(encoding="utf-8")))
    args.output.write_text(json.dumps(graph, indent=2), encoding="utf-8")
    print(f"Nodes: {graph['node_count']}; edges: {graph['edge_count']}")
    print("Mining graph only; no Golden Cases created.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
