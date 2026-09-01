"""Bridge to BugScout workflows shipped in option-d-copilot/src.

This module exposes selected BugScout capabilities to the FastAPI app without
duplicating logic:
  - crashdump parsing
  - handbook retrieval
  - cached log indexing/search
  - live-debug session bootstrap
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
BUGSCOUT_ROOT = REPO_ROOT / "option-d-copilot"
BUGSCOUT_SRC = BUGSCOUT_ROOT / "src"
BUGSCOUT_OUTPUT = BUGSCOUT_ROOT / "output"


def _ensure_bugscout_path() -> None:
    src = str(BUGSCOUT_SRC)
    if src not in sys.path:
        sys.path.insert(0, src)


def _parse_and_triage_script() -> Path:
    script = BUGSCOUT_SRC / "parse_and_triage.py"
    if not script.exists():
        raise FileNotFoundError("BugScout parse_and_triage.py was not found.")
    return script


def _run_bugscout_cli(args: List[str]) -> str:
    proc = subprocess.run(
        args,
        cwd=str(BUGSCOUT_SRC),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    if proc.returncode != 0:
        raise RuntimeError(output or "BugScout command failed.")
    return output


def _extract_line_value(output: str, label: str) -> str:
    m = re.search(rf"{re.escape(label)}:\s*([^\n\r]+)", output)
    return m.group(1).strip() if m else ""


def feature_status() -> Dict[str, Any]:
    return {
        "repo_root": str(REPO_ROOT),
        "bugscout_root": str(BUGSCOUT_ROOT),
        "bugscout_src": str(BUGSCOUT_SRC),
        "available": {
            "crashdump": (BUGSCOUT_SRC / "crashdump_router.py").exists(),
            "handbook_rag": (BUGSCOUT_SRC / "handbook_rag.py").exists(),
            "log_search": (BUGSCOUT_SRC / "cache_log_search" / "searcher.py").exists(),
            "live_debug": (BUGSCOUT_SRC / "parse_and_triage.py").exists(),
        },
    }


def parse_crashdump_file(input_path: str, output_dir: Optional[str] = None) -> Dict[str, Any]:
    _ensure_bugscout_path()
    from crashdump_router import route_crashdump  # type: ignore

    src = Path(input_path)
    if not src.exists() or not src.is_file():
        raise FileNotFoundError(f"Crashdump input file not found: {input_path}")
    return route_crashdump(str(src), output_dir)


def handbook_search(query: str, top_k: int = 4) -> List[Dict[str, Any]]:
    _ensure_bugscout_path()
    from handbook_rag import HandbookRAG  # type: ignore

    rag = HandbookRAG.from_default_root()
    return rag.retrieve(query, top_k=top_k)


def cache_log_index(file_path: str) -> Dict[str, Any]:
    _ensure_bugscout_path()
    from cache_log_search import get_cache_info, index  # type: ignore

    src = Path(file_path)
    if not src.exists() or not src.is_file():
        raise FileNotFoundError(f"Log file not found: {file_path}")
    cache_path = index(src)
    info = get_cache_info(src)
    return {
        "cache_path": str(cache_path),
        "cache_info": info or {},
    }


def cache_log_search(file_path: str, keywords: List[str], lines: int = 60,
                     section: Optional[str] = None) -> List[Dict[str, Any]]:
    _ensure_bugscout_path()
    from cache_log_search import search  # type: ignore

    src = Path(file_path)
    if not src.exists() or not src.is_file():
        raise FileNotFoundError(f"Log file not found: {file_path}")
    return search(src, keywords, lines=lines, section=section)


def list_cached_logs() -> Dict[str, Any]:
    _ensure_bugscout_path()
    from cache_log_search import list_cached_files  # type: ignore

    return list_cached_files()


def bugscout_prepare_batch(input_csv: str) -> Dict[str, Any]:
    script = _parse_and_triage_script()
    src = Path(input_csv)
    if not src.exists() or not src.is_file():
        raise FileNotFoundError(f"Input CSV not found: {input_csv}")

    output = _run_bugscout_cli([
        sys.executable,
        str(script),
        "--mode",
        "prepare",
        "--input",
        str(src),
    ])
    run_dir = _extract_line_value(output, "Run folder")
    prompts_path = _extract_line_value(output, "Output")
    return {
        "run_dir": run_dir,
        "prompts_jsonl": prompts_path,
        "console": output,
    }


def bugscout_finalize_batch(responses_jsonl: str, output_dir: Optional[str] = None) -> Dict[str, Any]:
    script = _parse_and_triage_script()
    responses = Path(responses_jsonl)
    if not responses.exists() or not responses.is_file():
        raise FileNotFoundError(f"Responses JSONL not found: {responses_jsonl}")

    cmd = [
        sys.executable,
        str(script),
        "--mode",
        "finalize",
        "--responses",
        str(responses),
    ]
    if output_dir:
        cmd.extend(["--output-dir", output_dir])

    output = _run_bugscout_cli(cmd)
    run_dir = _extract_line_value(output, "Run folder")
    result_csv = _extract_line_value(output, "Output")
    return {
        "run_dir": run_dir,
        "results_csv": result_csv,
        "console": output,
    }


def bugscout_render_report(input_csv: str, output_dir: Optional[str] = None) -> Dict[str, Any]:
    script = _parse_and_triage_script()
    src = Path(input_csv)
    if not src.exists() or not src.is_file():
        raise FileNotFoundError(f"Input CSV not found: {input_csv}")

    cmd = [
        sys.executable,
        str(script),
        "--mode",
        "report",
        "--input",
        str(src),
    ]
    if output_dir:
        cmd.extend(["--output-dir", output_dir])

    output = _run_bugscout_cli(cmd)
    run_dir = _extract_line_value(output, "Run folder")
    report_html = _extract_line_value(output, "Output")
    return {
        "run_dir": run_dir,
        "report_html": report_html,
        "console": output,
    }


def bugscout_render_live_debug_report(session_id: str) -> Dict[str, Any]:
    runner = BUGSCOUT_SRC / "live_debug_runner.py"
    if not runner.exists():
        raise FileNotFoundError("BugScout live_debug_runner.py was not found.")
    if not session_id.strip():
        raise ValueError("session_id is required")

    output = _run_bugscout_cli([
        sys.executable,
        str(runner),
        "--hsd-id",
        "placeholder",
        "--report-only",
        session_id.strip(),
    ])
    out_dir = _extract_line_value(output, "Reports generated in")
    html_path = _extract_line_value(output, "HTML")
    md_path = _extract_line_value(output, "Markdown")
    json_path = _extract_line_value(output, "JSON")
    return {
        "session_id": session_id.strip(),
        "output_dir": out_dir,
        "html": html_path,
        "markdown": md_path,
        "json": json_path,
        "console": output,
    }


def list_bugscout_runs(limit: int = 30) -> Dict[str, Any]:
    runs: List[Dict[str, Any]] = []
    if BUGSCOUT_OUTPUT.exists():
        for run in sorted(BUGSCOUT_OUTPUT.glob("run_*"), key=lambda p: p.name, reverse=True)[:limit]:
            runs.append({
                "name": run.name,
                "path": str(run),
                "prompts_jsonl": str(run / "triage_prompts.jsonl") if (run / "triage_prompts.jsonl").exists() else "",
                "results_csv": str(run / "triage_results.csv") if (run / "triage_results.csv").exists() else "",
                "report_html": str(run / "triage_report.html") if (run / "triage_report.html").exists() else "",
            })

    live_debug: List[Dict[str, Any]] = []
    if BUGSCOUT_OUTPUT.exists():
        for session_dir in sorted(BUGSCOUT_OUTPUT.glob("live_debug_*"), key=lambda p: p.name, reverse=True)[:limit]:
            live_debug.append({
                "name": session_dir.name,
                "path": str(session_dir),
                "session_init": str(session_dir / "session_init.json") if (session_dir / "session_init.json").exists() else "",
                "session_db": str(session_dir / "session.db") if (session_dir / "session.db").exists() else "",
                "report_html": str(session_dir / "session_report.html") if (session_dir / "session_report.html").exists() else "",
                "report_md": str(session_dir / "session_report.md") if (session_dir / "session_report.md").exists() else "",
                "session_json": str(session_dir / "session_data.json") if (session_dir / "session_data.json").exists() else "",
            })

    return {"batch_runs": runs, "live_debug_sessions": live_debug}


def start_live_debug_session(hsd_id: str, execution_mode: str = "manual", server: str = "",
                             ssh_user: str = "", max_iterations: int = 10,
                             initial_logs_json: Optional[str] = None,
                             nuc_host: str = "", nuc_user: str = "") -> Dict[str, Any]:
    parser_script = _parse_and_triage_script()

    cmd = [
        sys.executable,
        str(parser_script),
        "--mode", "live-debug",
        "--hsd-id", str(hsd_id),
        "--execution-mode", execution_mode,
        "--max-iterations", str(max_iterations),
    ]
    if server:
        cmd.extend(["--server", server])
    if ssh_user:
        cmd.extend(["--ssh-user", ssh_user])
    if nuc_host:
        cmd.extend(["--nuc-host", nuc_host])
    if nuc_user:
        cmd.extend(["--nuc-user", nuc_user])
    if initial_logs_json:
        init_path = Path(initial_logs_json)
        if not init_path.exists() or not init_path.is_file():
            raise FileNotFoundError(f"Initial logs JSON file not found: {initial_logs_json}")
        cmd.extend(["--initial-logs", str(init_path)])

    output = _run_bugscout_cli(cmd)

    session_id = ""
    out_dir = ""
    m_sid = re.search(r"Session ID:\s*([^\n\r]+)", output)
    if m_sid:
        session_id = m_sid.group(1).strip()
    m_out = re.search(r"Output folder:\s*([^\n\r]+)", output)
    if m_out:
        out_dir = m_out.group(1).strip()

    session_init = ""
    if out_dir:
        maybe = Path(out_dir) / "session_init.json"
        if maybe.exists():
            session_init = str(maybe)

    result: Dict[str, Any] = {
        "session_id": session_id,
        "output_dir": out_dir,
        "session_init": session_init,
        "console": output,
    }

    # Surface the NUC PythonSV connectivity probe result for the UI.
    if execution_mode == "nuc-pythonsv":
        m_json = re.search(r"NUC_PROBE_JSON:\s*(\{.*\})", output)
        if m_json:
            try:
                result["nuc_probe"] = json.loads(m_json.group(1))
            except Exception:
                result["nuc_probe"] = {}
        m_conn = re.search(r"NUC connectivity:\s*([^\n\r]+)", output)
        m_psv = re.search(r"PythonSV folder:\s*([^\n\r]+)", output)
        m_tx = re.search(r"NUC transport:\s*([^\n\r]+)", output)
        result["nuc_connectivity"] = m_conn.group(1).strip() if m_conn else "UNKNOWN"
        result["pythonsv_folder"] = m_psv.group(1).strip() if m_psv else "UNKNOWN"
        result["nuc_transport"] = m_tx.group(1).strip() if m_tx else "UNKNOWN"

    return result


def nuc_pythonsv(action: str, nuc_host: str = "", nuc_user: str = "",
                 pythonsv_path: str = "", commands: Optional[List[str]] = None,
                 password: str = "", auto_init: bool = True) -> Dict[str, Any]:
    """Standalone PythonSV-over-NUC helper for the PythonSV tab.

    action='probe' -> connectivity + PythonSV-path check (SSH then WinRM).
    action='run'   -> run the given PythonSV commands on the NUC. When auto_init
                      is set, an unlock + sv.refresh preamble runs first.
    Password is provided per-connection (UI) or falls back to NUC_PASSWORD env;
    it is used only for this call and never logged or stored.
    """
    _ensure_bugscout_path()
    import live_debug_runner as ldr  # type: ignore

    if action == "probe":
        return ldr.run_nuc_pythonsv_probe(
            nuc_host=nuc_host, nuc_user=nuc_user, pythonsv_path=pythonsv_path,
            password=password)

    if action == "run":
        cmds = [c for c in (commands or []) if str(c).strip()]
        if not cmds:
            raise ValueError("commands are required for action 'run'.")
        adapter = ldr.NUCPythonSVAdapter(
            host=nuc_host or os.getenv("NUC_HOST", ""),
            user=nuc_user or os.getenv("NUC_USER", ""),
            pythonsv_path=pythonsv_path or os.getenv("NUC_PYTHONSV_PATH", r"C:\pythonsv"),
            password=password,
        )
        raw = adapter.run(cmds, with_preamble=auto_init)
        return {
            "transport": adapter.transport_used,
            "auto_init": auto_init,
            "output": ldr.clean_pythonsv_output(raw),
            "raw_output": raw,
            "notes": ldr.interpret_pythonsv_output(raw),
        }

    raise ValueError("action must be 'probe' or 'run'.")