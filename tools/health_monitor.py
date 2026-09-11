"""Single-shot unattended NEXUS health watchdog.

Run with: .venv\\Scripts\\python.exe -m tools.health_monitor
The monitor writes timestamped JSON/Markdown reports and exits 0 for HEALTHY or
DEGRADED, 1 for CRITICAL. It never writes HSDES and never runs SUT commands.
"""

from __future__ import annotations

import csv
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "health_reports"
TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"

SAFETY_TESTS = [
    ("comment-only root cause", "tests.test_evidence_isolation.TestEvidenceIsolation.test_1_comment_only_root_cause_never_confirmed"),
    ("comment confidence isolation", "tests.test_evidence_isolation.TestEvidenceIsolation.test_12_comment_does_not_change_machine_verdict_or_confidence"),
    ("comment-only KB eligibility", "tests.test_evidence_isolation.TestEvidenceIsolation.test_kb_comment_only_is_unvalidated_and_ineligible"),
    ("UC/PCC fatality", "tests.test_evidence_isolation.TestEvidenceIsolation.test_8_uc_pcc_never_corrected"),
    ("ownership conflict gate", "tests.test_decoder_correctness.TestOwnershipConflict.test_punit_vs_ccf_emits_conflict_and_blocks"),
    ("decoder ambiguity gate", "tests.test_p0_release_gate.TestDecoderAmbiguity.test_known_0402_4a00_is_explicitly_ambiguous"),
    ("write-disable force gate", "tests.test_autohsd_integration.TestAutoHsdClosedLoop.test_force_true_cannot_bypass_write_disabled"),
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _module(name: str, status: str, details: Iterable[str], started: float) -> Dict[str, Any]:
    return {"module_name": name, "status": status, "details": list(details),
            "duration_seconds": round(time.monotonic() - started, 3)}


def _run_subprocess(args: List[str], timeout: int = 180) -> Tuple[int, str, bool]:
    try:
        proc = subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
        return proc.returncode, (proc.stdout + proc.stderr), False
    except subprocess.TimeoutExpired as exc:
        output = ((exc.stdout or "") + (exc.stderr or "")) if isinstance(exc.stdout, str) else ""
        return 124, output + "\nTIMEOUT", True
    except Exception as exc:
        return 125, f"{type(exc).__name__}: {exc}", False


def _parse_requirements() -> List[Tuple[str, str]]:
    requirements = ROOT / "requirements.txt"
    result = []
    for raw in requirements.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        package = re.split(r"[<>=!~;\[]", line, maxsplit=1)[0].strip()
        if package:
            result.append((package, {
                "python-dotenv": "dotenv", "pywinrm": "winrm",
                "requests-kerberos": "requests_kerberos",
                "requests-negotiate-sspi": "requests_negotiate_sspi",
                "uvicorn": "uvicorn", "fastapi": "fastapi",
            }.get(package, package.replace("-", "_"))))
    return result


def check_environment() -> Dict[str, Any]:
    started = time.monotonic(); details: List[str] = []; status = "PASS"
    expected = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    current = Path(sys.executable).resolve()
    if expected.exists() and current != expected.resolve():
        status = "FAIL"; details.append(f"Interpreter mismatch: {current} != {expected.resolve()}")
    else:
        details.append(f"Interpreter: {current}")
    missing = []
    for package, module_name in _parse_requirements():
        try:
            importlib.import_module(module_name)
        except Exception as exc:
            missing.append(f"{package} ({type(exc).__name__})")
    if missing:
        status = "FAIL"; details.append("Missing imports: " + ", ".join(missing))
    else:
        details.append(f"Required imports available: {len(_parse_requirements())}")
    usage = shutil.disk_usage(ROOT)
    free_gb = usage.free / (1024 ** 3)
    details.append(f"Free disk: {free_gb:.2f} GiB")
    if free_gb < 1:
        status = "FAIL"; details.append("Less than 1 GiB free for reports")
    return _module("environment_sanity", status, details, started)


class _NamedResult(unittest.TestResult):
    def __init__(self):
        super().__init__()
        self.successes: List[str] = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.successes.append(str(test))


def _suite_result(names: Iterable[str] | None = None, discover_all: bool = False):
    suite = unittest.TestSuite()
    loader = unittest.defaultTestLoader
    if discover_all:
        suite = loader.discover(str(ROOT / "tests"), pattern="test_*.py")
    else:
        for name in names or []:
            suite.addTests(loader.loadTestsFromName(name))
    result = _NamedResult()
    suite.run(result)
    failures = [str(test) for test, _ in result.failures]
    errors = [str(test) for test, _ in result.errors]
    return (not failures and not errors, failures + errors, result.testsRun,
            len(failures), len(errors), result.successes)


def check_regression() -> Dict[str, Any]:
    started = time.monotonic()
    try:
        ok, failures, runs, failed, errors, successes = _suite_result(discover_all=True)
        details = [f"tests={runs}", f"failed={failed}", f"errors={errors}"]
        details.extend(f"PASS: {name}" for name in successes)
        details.extend(f"FAIL: {name}" for name in failures)
        return _module("regression_suite", "PASS" if ok else "FAIL", details, started)
    except Exception as exc:
        return _module("regression_suite", "FAIL", [f"{type(exc).__name__}: {exc}"], started)


def check_provenance() -> Dict[str, Any]:
    started = time.monotonic()
    try:
        from app.source_provenance import quality_report
        report = quality_report(ROOT)
        trust_counts: Dict[str, int] = {}
        inventory = json.loads((ROOT / "app/knowledge/source_inventory.json").read_text(encoding="utf-8"))
        for entry in inventory.get("entries", []):
            trust = str(entry.get("trust", "UNKNOWN"))
            trust_counts[trust] = trust_counts.get(trust, 0) + 1
        unknown = report["unknown_trust"]
        details = [f"resources={len(report['resources'])}", f"coverage={report['coverage_percent']:.1f}%",
                   f"trust_counts={trust_counts}", f"unknown={unknown or 'none'}"]
        status = "PASS" if not report["missing_inventory"] and not unknown else "FAIL"
        return _module("source_provenance", status, details, started)
    except Exception as exc:
        return _module("source_provenance", "FAIL", [f"{type(exc).__name__}: {exc}"], started)


def check_golden() -> Dict[str, Any]:
    started = time.monotonic(); malformed = []; parsed = []
    root = ROOT / "golden_cases"
    for path in sorted(root.rglob("*.json")):
        if path.name.startswith("_"):
            continue
        try:
            parsed.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception as exc:
            malformed.append(f"{path.relative_to(ROOT)}: {exc}")
    try:
        from tools.rca_benchmark import _load_cases
        qualified = _load_cases(root)
        platforms: Dict[str, int] = {}; levels: Dict[str, int] = {}
        for case in qualified:
            platforms[str(case.get("platform", "UNKNOWN"))] = platforms.get(str(case.get("platform", "UNKNOWN")), 0) + 1
            level = str(case.get("validation_level", "UNKNOWN")); levels[level] = levels.get(level, 0) + 1
        details = [f"files={len(parsed) + len(malformed)}", f"parsed={len(parsed)}",
                   f"malformed_count={len(malformed)}", f"malformed={malformed or 'none'}", f"qualified={len(qualified)}",
                   f"platforms={platforms}", f"levels={levels}"]
        return _module("golden_corpus_integrity", "PASS" if not malformed else "WARN", details, started)
    except Exception as exc:
        return _module("golden_corpus_integrity", "FAIL", [f"{type(exc).__name__}: {exc}", *malformed], started)


def check_named_tests() -> Dict[str, Any]:
    started = time.monotonic(); details = []; failed = False
    for label, test_name in SAFETY_TESTS:
        ok, failures, runs, _, _, successes = _suite_result([test_name])
        details.append(f"{label}: {'PASS' if ok else 'FAIL'} ({test_name})")
        if not ok:
            failed = True; details.extend(failures)
    return _module("safety_invariants", "FAIL" if failed else "PASS", details, started)


def check_autohsd() -> Dict[str, Any]:
    started = time.monotonic()
    ok, failures, runs, failed, errors, successes = _suite_result(["tests.test_autohsd_integration"])
    details = [f"tests={runs}", f"failed={failed}", f"errors={errors}"] + ([f"failure: {x}" for x in failures] if failures else [])
    details.extend(f"PASS: {name}" for name in successes)
    return _module("autohsd_integration", "PASS" if ok else "FAIL", details, started)


def check_benchmark() -> Dict[str, Any]:
    started = time.monotonic()
    code, output, timed_out = _run_subprocess(
        [sys.executable, "-m", "tools.rca_benchmark", "--dir", "golden_cases", "--no-attachments"], 120)
    completed = not timed_out
    cases = re.search(r"Running (\d+) golden case", output)
    insufficient = re.search(r"Insufficient evidence\s+:\s+(\d+)/(\d+)", output)
    actionable = re.search(r"Actionable owner preds\s+:\s+(\d+)/(\d+)", output)
    buckets = re.search(r"Outcome buckets\s+:\s*(.+)", output)
    details = [f"completed_within_timeout={'Y' if completed else 'N'}",
               f"cases={cases.group(1) if cases else 'unknown'}",
               f"insufficient_evidence={insufficient.group(1) if insufficient else 'unknown'}",
               f"actionable_predictions={actionable.group(1) if actionable else 'unknown'}"]
    if buckets:
        details.append("outcome_buckets=" + buckets.group(1).strip())
    if actionable and actionable.group(1) == "0":
        details.append("WARNING: actionable predictions = 0")
    return _module("benchmark_sanity", "WARN" if code or (actionable and actionable.group(1) == "0") else "PASS", details, started)


def check_api() -> Dict[str, Any]:
    started = time.monotonic(); base = "http://127.0.0.1:8000"
    try:
        request = urllib.request.Request(base + "/api/health")
        with urllib.request.urlopen(request, timeout=3) as response:
            details = [f"API running: HTTP {response.status}"]
        for path in ("/api/me", "/api/products"):
            try:
                with urllib.request.urlopen(base + path, timeout=3) as response:
                    details.append(f"{path}: HTTP {response.status}")
            except Exception as exc:
                details.append(f"{path}: {type(exc).__name__}")
        return _module("live_api_health", "PASS", details, started)
    except Exception as exc:
        return _module("live_api_health", "SKIPPED", [f"API not running: {type(exc).__name__}"], started)


def check_hygiene() -> Dict[str, Any]:
    started = time.monotonic()
    code, output, _ = _run_subprocess(["git", "status", "--short"], 30)
    lines = [line for line in output.splitlines() if line.strip()]
    write_enabled = os.getenv("HSDES_WRITE_ENABLED", "false").lower() == "true"
    details = [f"dirty_files={len(lines)}", f"HSDES_WRITE_ENABLED={'true' if write_enabled else 'false'}"]
    if write_enabled:
        details.append("WARNING: real HSDES posting is enabled in this environment")
    return _module("repo_hygiene", "WARN" if write_enabled else "PASS", details, started)


def _previous() -> Dict[str, Any] | None:
    path = REPORT_DIR / "latest_health.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def compare(previous: Dict[str, Any] | None, current: Dict[str, Any]) -> List[str]:
    if not previous:
        return ["BASELINE RUN — no comparison available"]
    regressions = []
    old_modules = {m["module_name"]: m for m in previous.get("modules", [])}
    for module in current.get("modules", []):
        old = old_modules.get(module["module_name"])
        if old and old.get("status") in {"PASS", "HEALTHY"} and module.get("status") in {"FAIL", "CRITICAL"}:
            regressions.append(f"REGRESSION: {module['module_name']} changed {old['status']} -> {module['status']}")
    old_golden = next((m for m in previous.get("modules", []) if m["module_name"] == "golden_corpus_integrity"), None)
    new_golden = next((m for m in current.get("modules", []) if m["module_name"] == "golden_corpus_integrity"), None)
    def count(detail_list, prefix):
        for item in detail_list or []:
            if item.startswith(prefix):
                match = re.search(r"(\d+)", item)
                if match: return int(match.group(1))
        return None
    old_q = count((old_golden or {}).get("details"), "qualified=")
    new_q = count((new_golden or {}).get("details"), "qualified=")
    if old_q is not None and new_q is not None and new_q < old_q:
        regressions.append(f"REGRESSION: qualified Golden Cases decreased from {old_q} to {new_q}")
    def malformed_count(module):
        for item in (module or {}).get("details", []):
            if item.startswith("malformed_count="):
                match = re.search(r"(\d+)", item)
                return int(match.group(1)) if match else 0
        return 0
    old_malformed = malformed_count(old_golden)
    new_malformed = malformed_count(new_golden)
    if new_malformed > old_malformed:
        regressions.append(f"REGRESSION: malformed Golden Case files increased from {old_malformed} to {new_malformed}")
    return regressions or ["No regressions detected compared with previous run"]


def overall_status(modules: List[Dict[str, Any]], regressions: List[str]) -> str:
    critical_modules = {"safety_invariants", "regression_suite"}
    if regressions and any(item.startswith("REGRESSION") for item in regressions):
        return "CRITICAL"
    if any(m["module_name"] in critical_modules and m["status"] == "FAIL" for m in modules):
        return "CRITICAL"
    if any(m["module_name"] == "autohsd_integration" and m["status"] == "FAIL" for m in modules):
        return "DEGRADED"
    if any(m["module_name"] == "source_provenance" and any("unknown=" in d and "none" not in d for d in m["details"]) for m in modules):
        return "DEGRADED"
    if any(m["module_name"] == "benchmark_sanity" and m["status"] == "WARN" for m in modules):
        return "DEGRADED"
    return "HEALTHY"


def render_markdown(report: Dict[str, Any]) -> str:
    lines = [f"# NEXUS Health Monitor — {report['timestamp']}", "", f"OVERALL: {report['overall_status']}", ""]
    lines.append("## Regression Comparison")
    lines.extend(f"- {item}" for item in report["regressions"])
    lines.extend(["", "## Module Summary", "", "| Module | Status | Duration | Findings |", "|---|---|---:|---|"])
    for module in report["modules"]:
        lines.append(f"| {module['module_name']} | {module['status']} | {module['duration_seconds']}s | {'; '.join(module['details'])} |")
    lines.extend(["", "## Exit Contract", "", "- Exit code `0`: HEALTHY or DEGRADED.", "- Exit code `1`: CRITICAL."])
    return "\n".join(lines) + "\n"


def run() -> int:
    previous = _previous()
    modules = [check_environment(), check_regression(), check_provenance(), check_golden(),
               check_named_tests(), check_autohsd(), check_benchmark(), check_api(), check_hygiene()]
    timestamp = _now().strftime(TIMESTAMP_FORMAT)
    regressions = compare(previous, {"modules": modules})
    report = {"timestamp": timestamp, "overall_status": overall_status(modules, regressions),
              "modules": modules, "regressions": regressions, "interpreter": sys.executable}
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REPORT_DIR / f"{timestamp}_health.json"
    md_path = REPORT_DIR / f"{timestamp}_health.md"
    json_text = json.dumps(report, indent=2) + "\n"
    json_path.write_text(json_text, encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    (REPORT_DIR / "latest_health.json").write_text(json_text, encoding="utf-8")
    if report["overall_status"] == "CRITICAL":
        failures = [d for m in modules if m["status"] == "FAIL" for d in m["details"]]
        (REPORT_DIR / f"ALERT_{timestamp}.txt").write_text("\n".join(failures) + "\n", encoding="utf-8")
        print("+" + "=" * 68 + "+")
        print("| CRITICAL: NEXUS health monitor detected a failure or regression. |")
        print("+" + "=" * 68 + "+")
    print(f"OVERALL: {report['overall_status']}")
    print(f"JSON: {json_path}")
    print(f"MARKDOWN: {md_path}")
    return 1 if report["overall_status"] == "CRITICAL" else 0


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
