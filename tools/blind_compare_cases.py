"""Compare NEXUS machine results across comments/KB isolation runs.

Each input JSON maps a run label (A/B/C/D) to a result object containing the
same fields returned by ``extract_ownership``. This utility does not run HSDES;
it makes the isolation comparison auditable once local runs are collected.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

FIELDS = ("owning_ip", "reporting_ip", "bank", "socket", "mcacod", "mscod",
          "confidence", "verdict")
RUNS = {
    "A": "comments_disabled_kb_disabled",
    "B": "comments_enabled_kb_disabled",
    "C": "comments_disabled_kb_enabled",
    "D": "comments_enabled_kb_enabled",
}


def compare(payload: Dict[str, Any]) -> Dict[str, Any]:
    baseline = payload.get("A") or payload.get(RUNS["A"]) or {}
    differences = []
    for label in ("B", "C", "D"):
        current = payload.get(label) or payload.get(RUNS[label]) or {}
        changed = {field: {"A": baseline.get(field), label: current.get(field)}
                   for field in FIELDS if baseline.get(field) != current.get(field)}
        if changed:
            differences.append({"run": label, "changed_fields": changed})
    return {"machine_isolation_pass": not differences,
            "differences": differences,
            "runs_present": sorted(payload.keys())}


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare blind NEXUS isolation runs")
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = compare(json.loads(args.input.read_text(encoding="utf-8")))
    text = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if result["machine_isolation_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
