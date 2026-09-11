"""Periodic non-destructive NEXUS health and feature checker.

Usage:
  python tools/nexus_auto_check.py
  python tools/nexus_auto_check.py --url http://127.0.0.1:8000 --strict

It checks the running API plus local qualification artifacts and tests. It never
executes SUT commands, writes HSDES, promotes Golden Cases, or runs analysis on
live HSDs.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check_url(base: str, path: str, method: str = "GET", body: dict | None = None) -> tuple[bool, str]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(base.rstrip("/") + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            return response.status < 500, f"HTTP {response.status}"
    except urllib.error.HTTPError as exc:
        # Validation endpoints intentionally return 400; auth may return 401.
        return exc.code in {400, 401, 404}, f"HTTP {exc.code}"
    except Exception as exc:
        return False, str(exc)


def run_command(args: list[str]) -> tuple[bool, str]:
    process = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    return process.returncode == 0, (process.stdout + process.stderr).strip()[-500:]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run periodic NEXUS self-checks")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    checks: list[tuple[str, bool, str]] = []

    for path in ("/api/health", "/api/me", "/api/products", "/api/kb"):
        ok, detail = check_url(args.url, path)
        checks.append((f"API {path}", ok, detail))
    for path, body in (("/api/analyze", {"hsd_id": "", "symptoms": ""}),
                       ("/api/autohsd/triage", {"hsd_id": ""}),
                       ("/api/hsd/update", {"hsd_id": ""}),
                       ("/api/chat", {"messages": []})):
        ok, detail = check_url(args.url, path, "POST", body)
        checks.append((f"API validation {path}", ok, detail))

    local_commands = [
        ([sys.executable, "-m", "py_compile", "tools/nexus_auto_check.py"], "local checker compile"),
        ([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"], "full regression suite"),
    ]
    for command, label in local_commands:
        ok, detail = run_command(command)
        checks.append((label, ok, detail))

    artifact_checks = {
        "release checklist": ROOT / "docs" / "NEXUS_RELEASE_GATE.md",
        "candidate pipeline": ROOT / "tools" / "build_golden_candidates.py",
        "AutoHSD profile generator": ROOT / "tools" / "generate_autohsd_profile.py",
        "enterprise design": ROOT / "docs" / "enterprise_agent_design.md",
    }
    for label, path in artifact_checks.items():
        checks.append((f"Artifact {label}", path.exists(), str(path.relative_to(ROOT))))

    failed = 0
    print("NEXUS automatic self-check")
    print("=" * 30)
    for name, ok, detail in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")
        failed += not ok
    print("=" * 30)
    print(f"Passed: {len(checks) - failed}")
    print(f"Failed: {failed}")
    if not args.strict:
        return 0
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
