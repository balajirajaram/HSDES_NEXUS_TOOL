"""Unified smoke test for the merged Auto HSD + OptionD tool.

Runs fast, non-destructive checks:
- CLI help wiring for unified entrypoint
- Core read-only API endpoints
- Validation behavior for required fields
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.main import app


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def _run_cli(cmd: Sequence[str], cwd: Path) -> tuple[bool, str]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    return proc.returncode == 0, out


def _fmt_allowed(values: Iterable[int]) -> str:
    uniq = sorted(set(values))
    return "/".join(str(v) for v in uniq)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run unified smoke checks")
    parser.add_argument("--strict", action="store_true", help="Fail if any warning occurs")
    args = parser.parse_args()

    repo_root = REPO_ROOT
    py = sys.executable

    results: list[CheckResult] = []

    # CLI checks
    ok, out = _run_cli([py, "-m", "app.power_tool", "--help"], repo_root)
    results.append(
        CheckResult(
            name="CLI: app.power_tool --help",
            ok=ok and "Unified Auto HSD + OptionD power tool" in out,
            detail="ok" if ok else out.splitlines()[-1] if out else "failed",
        )
    )

    ok, out = _run_cli([py, "-m", "app.power_tool", "optiond", "--help"], repo_root)
    results.append(
        CheckResult(
            name="CLI: app.power_tool optiond --help",
            ok=ok and "patch-fields" in out and "ui-mode" in out,
            detail="ok" if ok else out.splitlines()[-1] if out else "failed",
        )
    )

    # API checks through TestClient (no server process needed)
    client = TestClient(app)

    def expect_get(path: str, allowed: Sequence[int] = (200,)) -> None:
        r = client.get(path)
        ok_local = r.status_code in allowed
        results.append(
            CheckResult(
                name=f"GET {path}",
                ok=ok_local,
                detail=f"status={r.status_code}, expected={_fmt_allowed(allowed)}",
            )
        )

    def expect_post(path: str, payload: dict, allowed: Sequence[int]) -> None:
        r = client.post(path, json=payload)
        ok_local = r.status_code in allowed
        results.append(
            CheckResult(
                name=f"POST {path}",
                ok=ok_local,
                detail=f"status={r.status_code}, expected={_fmt_allowed(allowed)}",
            )
        )

    # Read-only endpoint health
    expect_get("/api/health")
    expect_get("/api/products")
    expect_get("/api/bugscout/features")
    expect_get("/api/bugscout/runs")
    expect_get("/api/kb")

    # Required-field validation checks
    expect_post("/api/bugscout/batch-prepare", {"input_csv": ""}, (400,))
    expect_post("/api/bugscout/batch-finalize", {"responses_jsonl": ""}, (400,))
    expect_post("/api/bugscout/batch-report", {"input_csv": ""}, (400,))
    expect_post("/api/bugscout/live-debug-report", {"session_id": ""}, (400,))
    expect_post("/api/bugscout/log-index", {"file_path": ""}, (400,))
    expect_post("/api/bugscout/handbook-search", {"query": "", "top_k": 4}, (400,))

    # These endpoints may be auth-gated when not in Kerberos mode
    # (401 expected), but can also fail early on input checks (400).
    expect_post("/api/analyze", {"hsd_id": "", "symptoms": ""}, (400,))
    expect_post("/api/batch_learn", {}, (400, 401))

    passed = sum(1 for r in results if r.ok)
    failed = len(results) - passed

    print("\nUnified smoke test results")
    print("=" * 34)
    for r in results:
        mark = "PASS" if r.ok else "FAIL"
        print(f"[{mark}] {r.name} -> {r.detail}")

    print("=" * 34)
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")

    if failed > 0:
        return 1

    # Placeholder for future non-blocking warnings if needed.
    warnings = 0
    if args.strict and warnings > 0:
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
