"""Create one fresh, commit-stamped NEXUS release evidence bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_capture(args: list[str]) -> tuple[int, str]:
    proc = subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    return proc.returncode, (proc.stdout + proc.stderr)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                          text=True, encoding="utf-8", errors="replace").stdout.strip()


def config_fingerprint() -> str:
    keys = ("HSDES_AUTH_MODE", "HSDES_BASE_URL", "LLM_BASE_URL", "LLM_MODEL",
            "SUT_SSH_USER", "SUT_SSH_DOMAIN", "SUT_SSH_PORT",
            "AUTOHSD_ALLOW_SSH_COLLECTION")
    values = []
    for key in keys:
        value = __import__("os").environ.get(key, "")
        values.append(f"{key}={value}")
    return hashlib.sha256("\n".join(values).encode()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Create canonical NEXUS release evidence")
    parser.add_argument("--output-root", type=Path, default=ROOT / "release_evidence")
    args = parser.parse_args()
    stamp = time.strftime("%Y%m%d_%H%M%S")
    commit = git("rev-parse", "HEAD") or "UNKNOWN"
    branch = git("branch", "--show-current") or "UNKNOWN"
    dirty = bool(git("status", "--porcelain"))
    out = args.output_root / f"{stamp}_{commit[:12]}"
    out.mkdir(parents=True, exist_ok=False)
    test_code, test_output = run_capture([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"])
    (out / "unittest_results.txt").write_text(test_output, encoding="utf-8")
    summary = re.search(r"Ran\s+(\d+)\s+tests?.*\n(OK|FAILED.*)", test_output, re.S)
    test_count = int(summary.group(1)) if summary else None
    provenance_code, provenance_output = run_capture([sys.executable, "tools/verify_decoders.py", "--strict"])
    unknown = re.findall(r"UNKNOWN\s+(.+)", provenance_output)
    provenance = {"exit_code": provenance_code, "status": "PASS" if provenance_code == 0 else "FAIL",
                  "unknown_trust": unknown, "output": provenance_output[-5000:]}
    (out / "provenance_results.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    integration_code, integration_output = run_capture([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_autohsd_integration.py"])
    integration = {"exit_code": integration_code, "status": "PASS" if integration_code == 0 else "FAIL",
                   "output": integration_output[-5000:]}
    (out / "autohsd_integration_results.json").write_text(json.dumps(integration, indent=2), encoding="utf-8")
    golden = []
    for path in (ROOT / "golden_cases").rglob("*.json"):
        if path.name.startswith("_"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            evidence = data.get("evidence") or {}
            if str(data.get("validation_level", "")).upper() in {"LEVEL_3_REPRODUCED", "LEVEL_4_FIX_VALIDATED"} and evidence.get("validated_by") and evidence.get("validation_source"):
                golden.append(str(path.relative_to(ROOT)))
        except Exception:
            pass
    reference_count = 0
    reference_path = ROOT / "reference_corpus.csv"
    if reference_path.exists():
        reference_count = max(0, len(reference_path.read_text(encoding="utf-8").splitlines()) - 1)
    benchmark = {"status": "NOT_RUN", "qualified_golden_cases": len(golden),
                 "reference_cases": reference_count, "reason": "Canonical release gate does not run live benchmark automatically."}
    (out / "benchmark_results.json").write_text(json.dumps(benchmark, indent=2), encoding="utf-8")
    blockers = []
    if test_code != 0: blockers.append("tests failed")
    if provenance_code != 0: blockers.append(f"unknown provenance resources: {len(unknown)}")
    if len(golden) < 30: blockers.append(f"qualified Golden Cases: {len(golden)}/30")
    if integration_code != 0: blockers.append("AutoHSD integration tests failed")
    readiness = ["# NEXUS Release Readiness", "", f"Status: {'NOT APPROVED' if blockers else 'APPROVED'}", "",
                 f"Git branch: {branch}", f"Commit: {commit}", f"Dirty tree: {dirty}",
                 f"Python: {platform.python_version()}", f"Tests: {test_count if test_count is not None else 'unknown'} (exit {test_code})",
                 f"Provenance: {provenance['status']}", f"Reference cases: {reference_count}",
                 f"Strict Golden cases: {len(golden)}/30", f"AutoHSD integration: {integration['status']}",
                 "HSD post-gate: evaluated by existing _post_gate in integration/test paths", "",
                 "## Blockers"] + [f"- {item}" for item in blockers]
    (out / "production_readiness.md").write_text("\n".join(readiness) + "\n", encoding="utf-8")
    manifest = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "git_branch": branch,
                "commit_hash": commit, "dirty_worktree": dirty, "python_version": platform.python_version(),
                "config_fingerprint": config_fingerprint(), "test_count": test_count,
                "test_exit_code": test_code, "provenance": provenance, "reference_case_count": reference_count,
                "strict_golden_case_count": len(golden), "autohsd_integration": integration,
                "hsd_post_gate": "existing analyzer._post_gate; no write performed", "blockers": blockers}
    (out / "release_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Release evidence: {out}")
    print(f"Status: {'NOT APPROVED' if blockers else 'APPROVED'}")
    print(f"Tests: {test_count}; Golden: {len(golden)}/30; Provenance: {provenance['status']}")
    return 0 if not blockers else 1


if __name__ == "__main__":
    raise SystemExit(main())
