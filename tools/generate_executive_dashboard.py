"""Generate a measured executive dashboard; unavailable metrics remain n/a."""

from __future__ import annotations

import argparse
import csv
import html
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(newline="", encoding="utf-8") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate executive NEXUS dashboard")
    parser.add_argument("--output", type=Path, default=ROOT / "executive_dashboard.html")
    args = parser.parse_args()
    candidates = count(ROOT / "golden_candidates.csv")
    references = count(ROOT / "reference_corpus.csv")
    graph = ROOT / "rca_knowledge_graph.json"
    mining = count(ROOT / "golden_mining_results.csv")
    html_text = "<!doctype html><meta charset=utf-8><title>NEXUS Executive Dashboard</title>"
    html_text += "<style>body{font:14px system-ui;max-width:1100px;margin:2rem auto}table{border-collapse:collapse;width:100%}th,td{border:1px solid #e6e6e6;padding:.5rem}th{background:#f5f5f5}.status{background:#fff3cd;padding:1rem;font-weight:bold}</style>"
    html_text += "<h1>NEXUS Executive Dashboard</h1><p class=status>Production status: NOT APPROVED. Metrics are evidence-gated.</p>"
    html_text += "<table><tr><th>Measure</th><th>Value</th></tr>"
    metrics = [("HSD candidates analyzed", candidates), ("Reference Corpus cases", references),
               ("RCA graph/mining records", mining), ("Qualified Golden Cases", "0/30"),
               ("Owner Accuracy", "n/a"), ("Bank Accuracy", "n/a"),
               ("Socket Accuracy", "n/a"), ("False Confirmed RCA", "n/a"),
               ("Average RCA time saved", "n/a - telemetry not available"),
               ("Estimated engineer hours saved", "n/a - telemetry not available")]
    for label, value in metrics:
        html_text += f"<tr><td>{html.escape(str(label))}</td><td>{html.escape(str(value))}</td></tr>"
    html_text += "</table><h2>Interpretation</h2><p>NEXUS has a working safety and mining framework. Production qualification requires approved Level 3/4 Golden Cases, complete source provenance, and benchmark measurements.</p>"
    args.output.write_text(html_text, encoding="utf-8")
    print(f"Executive dashboard written: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
