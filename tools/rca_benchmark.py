"""RCA regression benchmark — scores NEXUS ownership accuracy against the
engineer-validated corpus in golden_cases/.

Usage:
  python -m tools.rca_benchmark
  python tools/rca_benchmark.py --no-attachments --dir golden_cases/CHA

For each golden case it runs analyze(), extracts the detected owning IP / first
error / verdict / confidence, compares against the validated expectation, and
prints a PASS/FAIL table plus the five accuracy metrics. Add validated HSDs to
golden_cases/ (one JSON each) — see golden_cases/README.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.analyzer import analyze, extract_ownership  # noqa: E402


def _load_cases(root: Path) -> List[Dict[str, Any]]:
    cases: List[Dict[str, Any]] = []
    for path in sorted(root.rglob("*.json")):
        if path.name.startswith("_"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"  skip {path.name}: {exc}")
            continue
        if data.get("hsd_id") and data.get("expected_owner"):
            data["_file"] = str(path.relative_to(root))
            cases.append(data)
    return cases


def _match(expected: str, detected: str) -> bool:
    """Case-insensitive owner match (substring either direction)."""
    e, d = (expected or "").strip().lower(), (detected or "").strip().lower()
    if not e:
        return True
    if not d:
        return False
    return e in d or d in e


async def _score_case(case: Dict[str, Any], fetch_attachments: bool) -> Dict[str, Any]:
    hsd_id = str(case["hsd_id"])
    result = await analyze(hsd_id, f"RCA benchmark: {case.get('notes','')}",
                           fetch_attachments=fetch_attachments)
    own = extract_ownership(result)
    owner_ok = _match(case["expected_owner"], own["owning_ip"])
    fe_expected = case.get("expected_first_error", "")
    fe_ok = _match(fe_expected, own["first_error"]) if fe_expected else None
    v_expected = (case.get("expected_verdict") or "").upper()
    verdict_ok = (v_expected in (own["verdict"] or "").upper()) if v_expected else None
    min_conf = int(case.get("min_confidence") or 0)
    conf_ok = (own["confidence"] >= min_conf) if min_conf else None
    # Overconfidence = tool says CONFIRMED but the owner is wrong.
    overconfident = ("CONFIRMED" in (own["verdict"] or "").upper()) and not owner_ok
    # False attribution = named a specific (non-empty) owner that is wrong.
    false_attr = bool(own["owning_ip"]) and not owner_ok
    passed = owner_ok and (fe_ok is not False) and (verdict_ok is not False) and (conf_ok is not False)
    return {
        "hsd_id": hsd_id, "file": case.get("_file", ""),
        "expected_owner": case["expected_owner"], "detected_owner": own["owning_ip"],
        "owner_ok": owner_ok, "fe_ok": fe_ok, "verdict_ok": verdict_ok, "conf_ok": conf_ok,
        "verdict": own["verdict"], "confidence": own["confidence"],
        "overconfident": overconfident, "false_attr": false_attr, "passed": passed,
    }


async def run(dir_path: str, fetch_attachments: bool) -> int:
    root = (REPO_ROOT / dir_path) if not Path(dir_path).is_absolute() else Path(dir_path)
    if not root.exists():
        print(f"No such directory: {root}")
        return 2
    cases = _load_cases(root)
    if not cases:
        print(f"No golden cases found under {root}. Add JSON cases (see README).")
        return 0
    print(f"Running {len(cases)} golden case(s) from {root} "
          f"({'with' if fetch_attachments else 'without'} attachments)\n")
    rows = []
    for case in cases:
        try:
            rows.append(await _score_case(case, fetch_attachments))
        except Exception as exc:
            rows.append({"hsd_id": str(case["hsd_id"]), "file": case.get("_file", ""),
                         "expected_owner": case["expected_owner"], "detected_owner": f"ERROR: {exc}",
                         "owner_ok": False, "fe_ok": None, "verdict_ok": None, "conf_ok": None,
                         "verdict": "", "confidence": 0, "overconfident": False,
                         "false_attr": False, "passed": False})

    print(f"{'HSD':<14}{'Expected':<10}{'Detected':<12}{'Owner':<7}{'Verdict':<20}{'Conf':<6}{'Result'}")
    print("-" * 78)
    for r in rows:
        print(f"{r['hsd_id']:<14}{r['expected_owner']:<10}{str(r['detected_owner'])[:11]:<12}"
              f"{'PASS' if r['owner_ok'] else 'FAIL':<7}{str(r['verdict'])[:19]:<20}"
              f"{str(r['confidence'])+'%':<6}{'PASS' if r['passed'] else 'FAIL'}")

    n = len(rows)
    owner_acc = 100 * sum(1 for r in rows if r["owner_ok"]) / n
    fe_rows = [r for r in rows if r["fe_ok"] is not None]
    fe_acc = (100 * sum(1 for r in fe_rows if r["fe_ok"]) / len(fe_rows)) if fe_rows else None
    overconf = 100 * sum(1 for r in rows if r["overconfident"]) / n
    false_attr = 100 * sum(1 for r in rows if r["false_attr"]) / n
    passed = sum(1 for r in rows if r["passed"])

    print("\n=== Metrics ===")
    print(f"Owning-IP accuracy      : {owner_acc:5.1f}%   (target > 80-85%)")
    print(f"First-error accuracy    : " + (f"{fe_acc:5.1f}%   (target > 90%)" if fe_acc is not None else "  n/a   (no labels)"))
    print(f"Overconfidence rate     : {overconf:5.1f}%   (target ~0%)")
    print(f"False-attribution rate  : {false_attr:5.1f}%   (target < 10%)")
    print(f"Cases passed            : {passed}/{n}")
    return 0 if passed == n else 1


def main() -> None:
    ap = argparse.ArgumentParser(description="NEXUS RCA regression benchmark")
    ap.add_argument("--dir", default="golden_cases", help="corpus directory")
    ap.add_argument("--no-attachments", action="store_true",
                    help="skip HSDES attachment fetch (faster, ticket-text only)")
    args = ap.parse_args()
    rc = asyncio.run(run(args.dir, fetch_attachments=not args.no_attachments))
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
