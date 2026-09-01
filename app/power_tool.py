"""Unified launcher for Auto HSD + BugScout OptionD workflows.

Examples:
  python -m app.power_tool serve --reload
  python -m app.power_tool summarize 16030948515 "UPI degradation hang"
  python -m app.power_tool batch-learn --product GNR --limit 50
  python -m app.power_tool optiond prepare --input C:\\temp\\input.csv
  python -m app.power_tool optiond runs
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import List

from .bugscout_bridge import list_bugscout_runs

REPO_ROOT = Path(__file__).resolve().parents[1]
OPTIOND_ROOT = REPO_ROOT / "option-d-copilot"
OPTIOND_SRC = OPTIOND_ROOT / "src"


def _script(path: str) -> str:
    p = OPTIOND_SRC / path
    if not p.exists():
        raise FileNotFoundError(f"Missing OptionD script: {p}")
    return str(p)


def _run(cmd: List[str], cwd: Path | None = None) -> int:
    proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None)
    return int(proc.returncode)


def _cmd_serve(args: argparse.Namespace) -> int:
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        args.host,
        "--port",
        str(args.port),
    ]
    if args.reload:
        cmd.append("--reload")
    return _run(cmd, cwd=REPO_ROOT)


def _cmd_summarize(args: argparse.Namespace) -> int:
    cmd = [sys.executable, "-m", "app.summarize", args.hsd_id]
    if args.symptoms:
        cmd.append(args.symptoms)
    if args.log:
        cmd.extend(["--log", args.log])
    if args.no_attachments:
        cmd.append("--no-attachments")
    if args.no_transferred:
        cmd.append("--no-transferred")
    return _run(cmd, cwd=REPO_ROOT)


def _cmd_batch_learn(args: argparse.Namespace) -> int:
    cmd = [sys.executable, "-m", "app.batch_learn", "--limit", str(args.limit)]
    if args.product:
        cmd.extend(["--product", args.product])
    if args.query_id:
        cmd.extend(["--query-id", args.query_id])
    if args.ids:
        cmd.extend(["--ids", *args.ids])
    return _run(cmd, cwd=REPO_ROOT)


def _cmd_optiond(args: argparse.Namespace) -> int:
    action = args.optiond_action

    if action == "prepare":
        cmd = [
            sys.executable,
            _script("parse_and_triage.py"),
            "--mode",
            "prepare",
            "--input",
            args.input,
        ]
        return _run(cmd, cwd=OPTIOND_SRC)

    if action == "finalize":
        cmd = [
            sys.executable,
            _script("parse_and_triage.py"),
            "--mode",
            "finalize",
            "--responses",
            args.responses,
        ]
        if args.output_dir:
            cmd.extend(["--output-dir", args.output_dir])
        return _run(cmd, cwd=OPTIOND_SRC)

    if action == "report":
        cmd = [
            sys.executable,
            _script("parse_and_triage.py"),
            "--mode",
            "report",
            "--input",
            args.input,
        ]
        if args.output_dir:
            cmd.extend(["--output-dir", args.output_dir])
        return _run(cmd, cwd=OPTIOND_SRC)

    if action == "live-debug":
        cmd = [
            sys.executable,
            _script("parse_and_triage.py"),
            "--mode",
            "live-debug",
            "--hsd-id",
            args.hsd_id,
            "--execution-mode",
            args.execution_mode,
            "--max-iterations",
            str(args.max_iterations),
        ]
        if args.server:
            cmd.extend(["--server", args.server])
        if args.ssh_user:
            cmd.extend(["--ssh-user", args.ssh_user])
        if getattr(args, "nuc_host", ""):
            cmd.extend(["--nuc-host", args.nuc_host])
        if getattr(args, "nuc_user", ""):
            cmd.extend(["--nuc-user", args.nuc_user])
        if args.initial_logs:
            cmd.extend(["--initial-logs", args.initial_logs])
        return _run(cmd, cwd=OPTIOND_SRC)

    if action == "crashdump":
        cmd = [
            sys.executable,
            _script("parse_and_triage.py"),
            "--mode",
            "crashdump",
            "--input",
            args.input,
        ]
        if args.output_dir:
            cmd.extend(["--output-dir", args.output_dir])
        return _run(cmd, cwd=OPTIOND_SRC)

    if action == "patch-fields":
        cmd = [sys.executable, _script("patch_fields.py")]
        if args.run_dir:
            cmd.extend(["--run-dir", args.run_dir])
        mode_flags = [args.identify, args.apply, args.finalize, args.all]
        if sum(1 for x in mode_flags if x) != 1:
            raise SystemExit("Choose exactly one of --identify | --apply | --finalize | --all")
        if args.identify:
            cmd.append("--identify")
        elif args.apply:
            cmd.append("--apply")
        elif args.finalize:
            cmd.append("--finalize")
        else:
            cmd.append("--all")
        return _run(cmd, cwd=OPTIOND_SRC)

    if action == "write-single":
        cmd = [sys.executable, _script("write_single_response.py")]
        if args.run_folder:
            cmd.append(args.run_folder)
        return _run(cmd, cwd=OPTIOND_SRC)

    if action == "write-batch":
        cmd = [sys.executable, _script("write_batch_responses.py")]
        if args.run_folder:
            cmd.append(args.run_folder)
        return _run(cmd, cwd=OPTIOND_SRC)

    if action == "qat-r2v2-report":
        cmd = [sys.executable, _script("gen_qat_r2v2_report.py")]
        return _run(cmd, cwd=OPTIOND_SRC)

    if action == "ui-mode":
        cmd = [
            sys.executable,
            _script("ui_mode.py"),
            "--host",
            args.host,
            "--port",
            str(args.port),
        ]
        if args.no_browser:
            cmd.append("--no-browser")
        return _run(cmd, cwd=OPTIOND_SRC)

    if action == "runs":
        data = list_bugscout_runs(limit=max(1, args.limit))
        print(json.dumps(data, indent=2))
        return 0

    raise SystemExit(f"Unsupported optiond action: {action}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Unified Auto HSD + OptionD power tool")
    sub = p.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="Run the unified FastAPI web app")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--reload", action="store_true")
    p_serve.set_defaults(func=_cmd_serve)

    p_sum = sub.add_parser("summarize", help="Run one HSD analysis and save markdown/HTML report")
    p_sum.add_argument("hsd_id")
    p_sum.add_argument("symptoms", nargs="?", default="")
    p_sum.add_argument("--log", default="")
    p_sum.add_argument("--no-attachments", action="store_true")
    p_sum.add_argument("--no-transferred", action="store_true")
    p_sum.set_defaults(func=_cmd_summarize)

    p_bl = sub.add_parser("batch-learn", help="Learn many HSDs into KB")
    p_bl.add_argument("--product", default="")
    p_bl.add_argument("--query-id", default="")
    p_bl.add_argument("--ids", nargs="*")
    p_bl.add_argument("--limit", type=int, default=100)
    p_bl.set_defaults(func=_cmd_batch_learn)

    p_opt = sub.add_parser("optiond", help="Run OptionD utilities from one entrypoint")
    opt_sub = p_opt.add_subparsers(dest="optiond_action", required=True)

    p_prepare = opt_sub.add_parser("prepare", help="parse_and_triage prepare mode")
    p_prepare.add_argument("--input", required=True)

    p_finalize = opt_sub.add_parser("finalize", help="parse_and_triage finalize mode")
    p_finalize.add_argument("--responses", required=True)
    p_finalize.add_argument("--output-dir", default="")

    p_report = opt_sub.add_parser("report", help="parse_and_triage report mode")
    p_report.add_argument("--input", required=True)
    p_report.add_argument("--output-dir", default="")

    p_live = opt_sub.add_parser("live-debug", help="parse_and_triage live-debug mode")
    p_live.add_argument("--hsd-id", required=True)
    p_live.add_argument("--execution-mode", choices=["manual", "local", "ssh", "auto", "nuc-pythonsv"], default="manual")
    p_live.add_argument("--server", default="")
    p_live.add_argument("--ssh-user", default="")
    p_live.add_argument("--nuc-host", default="", help="NUC hostname for nuc-pythonsv mode (default: NUC_HOST env)")
    p_live.add_argument("--nuc-user", default="", help="NUC username for nuc-pythonsv mode (default: NUC_USER env)")
    p_live.add_argument("--max-iterations", type=int, default=10)
    p_live.add_argument("--initial-logs", default="")

    p_crash = opt_sub.add_parser("crashdump", help="parse_and_triage crashdump mode")
    p_crash.add_argument("--input", required=True)
    p_crash.add_argument("--output-dir", default="")

    p_patch = opt_sub.add_parser("patch-fields", help="Run patch_fields workflow")
    p_patch.add_argument("--run-dir", default="")
    p_patch.add_argument("--identify", action="store_true")
    p_patch.add_argument("--apply", action="store_true")
    p_patch.add_argument("--finalize", action="store_true")
    p_patch.add_argument("--all", action="store_true")

    p_ws = opt_sub.add_parser("write-single", help="Append one response into responses.jsonl")
    p_ws.add_argument("--run-folder", default="")

    p_wb = opt_sub.add_parser("write-batch", help="Append batch responses into responses.jsonl")
    p_wb.add_argument("--run-folder", default="")

    opt_sub.add_parser("qat-r2v2-report", help="Generate QAT r2v2 session report")

    p_ui = opt_sub.add_parser("ui-mode", help="Launch OptionD UI mode dashboard")
    p_ui.add_argument("--host", default="127.0.0.1")
    p_ui.add_argument("--port", type=int, default=8765)
    p_ui.add_argument("--no-browser", action="store_true")

    p_runs = opt_sub.add_parser("runs", help="List discovered OptionD run folders and sessions")
    p_runs.add_argument("--limit", type=int, default=30)

    p_opt.set_defaults(func=_cmd_optiond)

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        rc = args.func(args)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
