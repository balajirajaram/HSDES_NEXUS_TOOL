"""Qualification-only benchmark for the exploratory Reference Corpus."""

from __future__ import annotations

import argparse
import asyncio
import csv
import html
import re
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ["HSD_ID", "ExpectedOwner", "PredictedOwner", "OwnerMatch",
          "ExpectedRootCause", "PredictedRootCause", "RcaSimilarity",
          "EvidenceCoverage", "Confidence", "PassFail"]


def _rows(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]+", (value or "").lower()))


def _similarity(expected: str, predicted: str) -> str:
    left, right = _tokens(expected), _tokens(predicted)
    if not left or not right:
        return "n/a"
    return f"{100 * len(left & right) / len(left | right):.1f}%"


def _match(expected: str, predicted: str) -> str:
    if not (expected or "").strip():
        return "n/a"
    if not (predicted or "").strip():
        return "FAIL"
    left, right = expected.lower().strip(), predicted.lower().strip()
    return "PASS" if left in right or right in left else "FAIL"


def _coverage(reference: Dict[str, str], own: Dict[str, Any]) -> str:
    pairs = [("Owner", reference.get("Owner"), own.get("owning_ip")),
             ("Platform", reference.get("Platform"), own.get("platform")),
             ("RootCause", reference.get("Root_Cause"), own.get("root_cause")),
             ("Bank", reference.get("Bank", ""), own.get("bank")),
             ("Socket", reference.get("Socket", ""), own.get("socket")),
             ("MCACOD", reference.get("MCACOD", ""), own.get("mcacod")),
             ("MSCOD", reference.get("MSCOD", ""), own.get("mscod"))]
    labeled = [(expected, predicted) for _, expected, predicted in pairs if (expected or "").strip()]
    if not labeled:
        return "n/a"
    return f"{100 * sum(bool((predicted or '').strip()) for expected, predicted in labeled) / len(labeled):.1f}%"


async def _run_case(reference: Dict[str, str], fetch_attachments: bool) -> Dict[str, str]:
    from app.analyzer import analyze, extract_ownership
    hsd_id = str(reference.get("HSD_ID", ""))
    try:
        result = await analyze(hsd_id, "Reference Corpus qualification benchmark",
                               fetch_attachments=fetch_attachments)
        own = extract_ownership(result)
        own["root_cause"] = own.get("root_cause", "")
        own["platform"] = own.get("platform", "")
        checks = [_match(reference.get("Owner", ""), own.get("owning_ip", "")),
                  _match(reference.get("Platform", ""), own.get("platform", "")),
                  _match(reference.get("Root_Cause", ""), own.get("root_cause", "")),
                  _match(reference.get("Bank", ""), own.get("bank", "")),
                  _match(reference.get("Socket", ""), own.get("socket", "")),
                  _match(reference.get("MCACOD", ""), own.get("mcacod", "")),
                  _match(reference.get("MSCOD", ""), own.get("mscod", ""))]
        failures = [check for check in checks if check == "FAIL"]
        false_attr = bool(own.get("owning_ip")) and checks[0] == "FAIL"
        return {
            "HSD_ID": hsd_id, "ExpectedOwner": reference.get("Owner", ""),
            "PredictedOwner": own.get("owning_ip", ""), "OwnerMatch": checks[0],
            "ExpectedRootCause": reference.get("Root_Cause", ""),
            "PredictedRootCause": own.get("root_cause", ""),
            "RcaSimilarity": _similarity(reference.get("Root_Cause", ""), own.get("root_cause", "")),
            "EvidenceCoverage": _coverage(reference, own),
            "Confidence": f"{own.get('confidence', 0)}%",
            "PassFail": "FAIL" if failures or false_attr else "PASS",
        }
    except Exception as exc:
        return {"HSD_ID": hsd_id, "ExpectedOwner": reference.get("Owner", ""),
                "PredictedOwner": f"ERROR: {exc}", "OwnerMatch": "ERROR",
                "ExpectedRootCause": reference.get("Root_Cause", ""),
                "PredictedRootCause": "", "RcaSimilarity": "n/a",
                "EvidenceCoverage": "n/a", "Confidence": "n/a", "PassFail": "ERROR"}


async def run(references: List[Dict[str, str]], fetch_attachments: bool, concurrency: int) -> List[Dict[str, str]]:
    semaphore = asyncio.Semaphore(concurrency)
    async def bounded(reference):
        async with semaphore:
            return await _run_case(reference, fetch_attachments)
    return await asyncio.gather(*(bounded(reference) for reference in references))


def write_dashboard(rows: List[Dict[str, str]], path: Path) -> None:
    def pct(values):
        values = [v for v in values if v in {"PASS", "FAIL"}]
        return "n/a" if not values else f"{100 * values.count('PASS') / len(values):.1f}%"
    owner = pct([r["OwnerMatch"] for r in rows])
    similarities = [float(r["RcaSimilarity"].rstrip("%")) for r in rows if r["RcaSimilarity"] != "n/a"]
    coverage = [float(r["EvidenceCoverage"].rstrip("%")) for r in rows if r["EvidenceCoverage"] != "n/a"]
    false_attr = sum(r["OwnerMatch"] == "FAIL" and bool(r["PredictedOwner"]) for r in rows)
    valid_owner_labels = [r for r in rows if r["ExpectedOwner"].strip()]
    owner_note = ("Reference Owner values are HSD article owners, not validated RCA owning IPs; "
                  "owner accuracy is not production-interpretable until normalized RCA labels exist."
                  if valid_owner_labels else "No expected RCA owner labels are available.")
    lines = ["<!doctype html><meta charset=utf-8><title>Reference Benchmark</title>",
             "<style>body{font:14px system-ui;max-width:1100px;margin:2rem auto}table{border-collapse:collapse;width:100%}th,td{border:1px solid #e6e6e6;padding:.4rem}th{background:#f5f5f5}</style>",
             "<h1>NEXUS Reference Corpus Benchmark</h1>",
             "<p><b>Status:</b> qualification-only; this does not approve or promote Golden Cases.</p>",
             "<table><tr><th>Metric</th><th>Result</th></tr>",
             f"<tr><td>Owner Accuracy</td><td>{owner}</td></tr>",
             f"<tr><td>RCA Similarity</td><td>{sum(similarities)/len(similarities):.1f}%</td></tr>" if similarities else "<tr><td>RCA Similarity</td><td>n/a</td></tr>",
             f"<tr><td>Evidence Coverage</td><td>{sum(coverage)/len(coverage):.1f}%</td></tr>" if coverage else "<tr><td>Evidence Coverage</td><td>n/a</td></tr>",
             f"<tr><td>False Attribution Count</td><td>{false_attr}</td></tr>",
             "<tr><td>Confidence Calibration</td><td>n/a - no validated expected confidence labels</td></tr>",
             f"<tr><td>Cases</td><td>{len(rows)}</td></tr></table>",
             f"<p><b>Interpretation limitation:</b> {html.escape(owner_note)}</p>",
             "<h2>Case Results</h2><table><tr>" + "".join(f"<th>{html.escape(field)}</th>" for field in FIELDS) + "</tr>"]
    for row in rows:
        lines.append("<tr>" + "".join(f"<td>{html.escape(str(row.get(field, '')))}</td>" for field in FIELDS) + "</tr>")
    lines.append("</table>")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark NEXUS against Reference Corpus")
    parser.add_argument("--reference", type=Path, default=ROOT / "reference_corpus.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "reference_benchmark_results.csv")
    parser.add_argument("--dashboard", type=Path, default=ROOT / "reference_benchmark_dashboard.html")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--no-attachments", action="store_true")
    parser.add_argument("--concurrency", type=int, default=3)
    args = parser.parse_args()
    references = _rows(args.reference)[:max(1, args.limit)]
    results = asyncio.run(run(references, not args.no_attachments, max(1, args.concurrency)))
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS); writer.writeheader(); writer.writerows(results)
    write_dashboard(results, args.dashboard)
    print(f"Reference cases benchmarked: {len(results)}")
    print("Qualification-only benchmark; Golden Cases were not modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
