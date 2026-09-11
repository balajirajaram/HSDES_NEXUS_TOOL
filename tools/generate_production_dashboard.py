"""Generate an auditable NEXUS production-readiness dashboard."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.source_provenance import quality_report  # noqa: E402
from tools.rca_benchmark import _load_cases  # noqa: E402


METRIC_TARGETS = {
    "owner_accuracy": 85.0,
    "bank_accuracy": 95.0,
    "socket_accuracy": 95.0,
    "false_confirmed_rca": 0.0,
    "comment_influence": 0.0,
    "kb_contamination": 0.0,
}


def main() -> int:
    cases = _load_cases(ROOT / "golden_cases")
    provenance = quality_report(ROOT)
    metrics = {name: None for name in METRIC_TARGETS}
    failures = []
    if len(cases) < 30:
        failures.append(f"qualified golden cases {len(cases)}/30")
    if provenance["missing_inventory"]:
        failures.append(f"source inventory coverage {provenance['coverage_percent']:.1f}%")
    if provenance["unknown_trust"]:
        failures.append(f"unknown-trust resources {len(provenance['unknown_trust'])}")
    result = {
        "generated_date": str(date.today()),
        "golden_cases": {"qualified": len(cases), "required": 30},
        "metrics": metrics,
        "source_provenance": {
            "coverage_percent": provenance["coverage_percent"],
            "unknown_trust": provenance["unknown_trust"],
            "missing_inventory": provenance["missing_inventory"],
        },
        "production_status": "APPROVED" if not failures else "NOT APPROVED",
        "failures": failures,
        "note": "Metrics are null until a qualified corpus has been benchmarked.",
    }
    output = ROOT / "output" / "benchmark_results.json"
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    dashboard = ROOT / "docs" / "production_readiness.md"
    lines = [
        "# NEXUS Production Readiness",
        "",
        f"Generated: {result['generated_date']}",
        "",
        f"**Production Status: {result['production_status']}**",
        "",
        f"Golden Cases: {len(cases)}/30 qualified",
        "",
        "| Metric | Result | Target |",
        "|---|---:|---:|",
    ]
    for name, target in METRIC_TARGETS.items():
        value = metrics[name]
        shown = "n/a" if value is None else f"{value:.1f}%"
        suffix = "0%" if target == 0 else f"> {target:.0f}%"
        lines.append(f"| {name.replace('_', ' ').title()} | {shown} | {suffix} |")
    lines += ["", "## Failing Gates", ""]
    if failures:
        lines.extend(f"- {failure}" for failure in failures)
    else:
        lines.append("- None")
    lines += ["", "Source provenance:",
              f"- Inventory coverage: {provenance['coverage_percent']:.1f}%",
              f"- Unknown-trust resources: {len(provenance['unknown_trust'])}",
              "", "Machine-readable results: `output/benchmark_results.json`", ""]
    dashboard.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["production_status"] == "APPROVED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
