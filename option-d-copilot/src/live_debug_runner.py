#!/usr/bin/env python3
"""
live_debug_runner.py
═══════════════════════════════════════════════════════════════════════════════
Live Debug Session manager for HSD triage.

Responsibilities:
  - SQL session state (create / read / update iterations)
  - Execution adapters: ManualAdapter, LocalAdapter, SSHAdapter, AutoAdapter
  - Log ingestion and normalization
  - Per-iteration state persistence (JSON + SQL)
  - Report generation: Markdown + HTML (using live_debug_report_template.html)

Entry point:  called from parse_and_triage.py --mode live-debug
              or directly:  python live_debug_runner.py --hsd-id <id> [options]

Usage (standalone):
  python live_debug_runner.py --hsd-id 14027419708
  python live_debug_runner.py --hsd-id 14027419708 --execution-mode ssh --server mylab.intel.com
  python live_debug_runner.py --hsd-id 14027419708 --initial-logs initial_logs.json
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).parent.resolve()
REPO_ROOT = SCRIPT_DIR.parent
OUTPUT_BASE = REPO_ROOT / "output"
LEGACY_OUTPUT_BASE = SCRIPT_DIR / "output"
LIVE_DEBUG_TEMPLATE_PATH = REPO_ROOT / "templates" / "live_debug_report_template.html"
TEMPLATE_VERSION = "live_debug_report_template.html v1.0"

# ─── Session State (SQLite via standard library) ───────────────────────────────

def _get_db_path(session_id: str) -> Path:
    """Return path to the SQLite DB for this session."""
    return OUTPUT_BASE / f"live_debug_{session_id}" / "session.db"


def _resolve_existing_db_path(session_id: str) -> Path:
    """Find an existing session DB in the current or legacy output layout."""
    primary = _get_db_path(session_id)
    if primary.exists():
        return primary

    legacy = LEGACY_OUTPUT_BASE / f"live_debug_{session_id}" / "session.db"
    if legacy.exists():
        logger.info("Using legacy session output path for %s", session_id)
        return legacy

    return primary


def init_session_db(db_path: Path) -> None:
    """Create the SQLite session database and tables if they don't exist."""
    import sqlite3
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS live_debug_sessions (
                session_id      TEXT PRIMARY KEY,
                hsd_id          TEXT NOT NULL,
                title           TEXT,
                component       TEXT,
                execution_mode  TEXT,
                server          TEXT,
                initial_logs_json TEXT,
                status          TEXT DEFAULT 'active',
                created_at      TEXT,
                updated_at      TEXT
            );

            CREATE TABLE IF NOT EXISTS live_debug_iterations (
                session_id      TEXT NOT NULL,
                iteration       INTEGER NOT NULL,
                hypothesis_json TEXT,   -- JSON: [{statement, confidence}, ...]
                logs_requested  TEXT,   -- JSON: [{category, commands:[]}]
                logs_collected  TEXT,   -- JSON: [{category, content_snippet, full_path}]
                geni_analysis   TEXT,
                next_steps      TEXT,   -- JSON: [{step, rationale, commands:[]}]
                user_input      TEXT,
                concluded_at    TEXT,
                PRIMARY KEY (session_id, iteration)
            );
        """)

        # Keep older session databases forward-compatible if the column was added later.
        existing_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(live_debug_sessions)")
        }
        if "initial_logs_json" not in existing_columns:
            conn.execute("ALTER TABLE live_debug_sessions ADD COLUMN initial_logs_json TEXT")


def create_session(db_path: Path, session_id: str, hsd_id: str,
                   execution_mode: str, server: str = "",
                   initial_logs: list[dict] | None = None) -> None:
    """Insert a new session record."""
    import sqlite3
    now = _now_iso()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO live_debug_sessions
               (session_id, hsd_id, execution_mode, server, initial_logs_json,
                status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 'active', ?, ?)""",
            (
                session_id,
                hsd_id,
                execution_mode,
                server,
                json.dumps(initial_logs or [], ensure_ascii=False),
                now,
                now,
            ),
        )


def update_session(db_path: Path, session_id: str, **fields: Any) -> None:
    """Update arbitrary fields on the session record."""
    import sqlite3
    fields["updated_at"] = _now_iso()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [session_id]
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            f"UPDATE live_debug_sessions SET {set_clause} WHERE session_id = ?",
            values,
        )


def write_iteration(db_path: Path, session_id: str, iteration: int,
                    data: dict) -> None:
    """Upsert a single iteration record."""
    import sqlite3
    now = _now_iso()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO live_debug_iterations
               (session_id, iteration, hypothesis_json, logs_requested,
                logs_collected, geni_analysis, next_steps, user_input, concluded_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                iteration,
                json.dumps(data.get("hypotheses", []), ensure_ascii=False),
                json.dumps(data.get("logs_requested", []), ensure_ascii=False),
                json.dumps(data.get("logs_collected", []), ensure_ascii=False),
                data.get("geni_analysis", ""),
                json.dumps(data.get("next_steps", []), ensure_ascii=False),
                data.get("user_input", ""),
                now,
            ),
        )


def load_session(db_path: Path, session_id: str) -> dict:
    """Load full session + all iterations from the DB."""
    import sqlite3
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        session_row = conn.execute(
            "SELECT * FROM live_debug_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if not session_row:
            raise ValueError(f"Session {session_id!r} not found in {db_path}")

        iter_rows = conn.execute(
            "SELECT * FROM live_debug_iterations WHERE session_id = ? ORDER BY iteration",
            (session_id,),
        ).fetchall()

    session = dict(session_row)
    session["initial_logs_collected"] = _safe_json(session.pop("initial_logs_json", "[]"))
    iterations = []
    for r in iter_rows:
        it = dict(r)
        it["hypotheses"]    = _safe_json(it.pop("hypothesis_json", "[]"))
        it["logs_requested"] = _safe_json(it.pop("logs_requested", "[]"))
        it["logs_collected"] = _safe_json(it.pop("logs_collected", "[]"))
        it["next_steps"]    = _safe_json(it.pop("next_steps", "[]"))
        it["timestamp"]     = it.pop("concluded_at", "")
        iterations.append(it)

    return {"session": session, "iterations": iterations}


# ─── Execution Adapters ────────────────────────────────────────────────────────

class ManualAdapter:
    """Print commands for the user to run; collect output by paste/file path."""

    def run(self, commands: list[str], context: str = "") -> str:
        print(f"\n{'─'*60}")
        if context:
            print(f"[Context] {context}")
        print("Run the following commands on the target system:\n")
        for cmd in commands:
            print(f"  {cmd}")
        print(f"\n{'─'*60}")
        print("Paste the output below (end with a line containing only 'END'):")
        lines = []
        while True:
            try:
                line = input()
            except EOFError:
                break
            if line.strip() == "END":
                break
            lines.append(line)
        return "\n".join(lines)


class LocalAdapter:
    """Run commands as local subprocesses."""

    def run(self, commands: list[str], context: str = "") -> str:
        outputs = []
        for cmd in commands:
            logger.info("Running locally: %s", cmd)
            try:
                result = subprocess.run(
                    cmd, shell=True, capture_output=True, text=True, timeout=120
                )
                outputs.append(f"$ {cmd}\n{result.stdout}{result.stderr}")
            except subprocess.TimeoutExpired:
                outputs.append(f"$ {cmd}\n[TIMEOUT after 120s]")
            except Exception as exc:
                outputs.append(f"$ {cmd}\n[ERROR: {exc}]")
        return "\n\n".join(outputs)


class SSHAdapter:
    """Run commands over SSH."""

    def __init__(self, host: str, user: str = ""):
        self.host = host
        self.user = user

    def run(self, commands: list[str], context: str = "") -> str:
        outputs = []
        target = f"{self.user}@{self.host}" if self.user else self.host
        for cmd in commands:
            ssh_cmd = ["ssh", "-o", "StrictHostKeyChecking=no", target, cmd]
            logger.info("SSH %s: %s", target, cmd)
            try:
                result = subprocess.run(
                    ssh_cmd, capture_output=True, text=True, timeout=120
                )
                outputs.append(f"$ {cmd}\n{result.stdout}{result.stderr}")
            except subprocess.TimeoutExpired:
                outputs.append(f"$ {cmd}\n[SSH TIMEOUT after 120s]")
            except Exception as exc:
                outputs.append(f"$ {cmd}\n[SSH ERROR: {exc}]")
        return "\n\n".join(outputs)


class AutoAdapter:
    """Try local first; fall back to manual if command fails."""

    def __init__(self):
        self._local = LocalAdapter()
        self._manual = ManualAdapter()

    def run(self, commands: list[str], context: str = "") -> str:
        try:
            result = self._local.run(commands, context)
            if "[ERROR" not in result and "[TIMEOUT" not in result:
                return result
        except Exception:
            pass
        logger.warning("Local execution failed — falling back to manual input.")
        return self._manual.run(commands, context)


def make_adapter(execution_mode: str, server: str = "", ssh_user: str = "") -> Any:
    """Return the appropriate execution adapter for the given mode."""
    mode = execution_mode.lower()
    if mode == "local":
        return LocalAdapter()
    if mode == "ssh":
        if not server:
            raise ValueError("--server is required when --execution-mode is ssh")
        return SSHAdapter(host=server, user=ssh_user)
    if mode == "auto":
        return AutoAdapter()
    return ManualAdapter()  # default


# ─── Log Ingestion ─────────────────────────────────────────────────────────────

def ingest_log_output(raw_output: str, category: str, output_path: Path) -> dict:
    """
    Normalize raw command output into a structured log record.
    Saves full content to a file; returns a summary dict for the session DB.
    """
    # Persist full output to file
    ts = _now_ts()
    log_file = output_path / f"{ts}_{category}.log"
    log_file.write_text(raw_output, encoding="utf-8")

    # Create a short snippet for the DB / report (first 800 chars)
    snippet = raw_output[:800].strip()
    if len(raw_output) > 800:
        snippet += f"\n... [{len(raw_output) - 800} more characters — see {log_file.name}]"

    return {
        "category": category,
        "content_snippet": snippet,
        "full_path": str(log_file),
    }


# ─── Report Generation ─────────────────────────────────────────────────────────

def generate_html_report(session_data: dict, output_path: Path,
                         fix_recommendation: dict | None = None) -> None:
    """
    Render the live debug HTML report using live_debug_report_template.html.

    Args:
        session_data:       dict with keys 'session' and 'iterations' (from load_session)
        output_path:        destination .html file path
        fix_recommendation: optional dict with statement, spec_reference, evidence_chain,
                            similar_fixes keys

    Raises:
        FileNotFoundError: if live_debug_report_template.html is missing from the repo
        ImportError:        if jinja2 is not installed
    """
    try:
        from jinja2 import Environment, BaseLoader, Undefined
    except ImportError as exc:
        raise ImportError(
            "jinja2 is required for report generation. Install: pip install jinja2"
        ) from exc

    if not LIVE_DEBUG_TEMPLATE_PATH.exists():
        raise FileNotFoundError(
            f"Live debug report template not found: {LIVE_DEBUG_TEMPLATE_PATH}\n"
            "Ensure live_debug_report_template.html is present in the templates folder."
        )

    session = session_data["session"]
    iterations = session_data["iterations"]

    # Derive final confidence from last iteration's top hypothesis
    final_confidence: float = 0.0
    if iterations:
        last_hyps = iterations[-1].get("hypotheses", [])
        if last_hyps:
            final_confidence = float(last_hyps[0].get("confidence", 0.0))

    # Derive final hypothesis statement
    final_hypothesis = ""
    if iterations:
        last_hyps = iterations[-1].get("hypotheses", [])
        if last_hyps:
            final_hypothesis = last_hyps[0].get("statement", "")

    # Build template context
    template_context = {
        "session": {
            **session,
            "total_iterations": len(iterations),
            "final_confidence": final_confidence,
            "final_hypothesis": final_hypothesis,
            "started_at": session.get("created_at", "—"),
            "completed_at": session.get("updated_at", "In Progress"),
            "related_hsds": session.get("related_hsds", []),
            "server": session.get("server", ""),
            "initial_logs_collected": session.get("initial_logs_collected", []),
        },
        "iterations": iterations,
        "fix_recommendation": fix_recommendation or {
            "statement": "",
            "spec_reference": "",
            "evidence_chain": [],
            "similar_fixes": [],
        },
        "generated_timestamp": _now_iso(),
        "template_version": TEMPLATE_VERSION,
    }

    template_src = LIVE_DEBUG_TEMPLATE_PATH.read_text(encoding="utf-8")
    env = Environment(loader=BaseLoader(), autoescape=False)
    # Add truncate filter (Jinja2 built-in, ensure available)
    tmpl = env.from_string(template_src)
    html = tmpl.render(**template_context)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    logger.info("HTML report written: %s", output_path)


def generate_markdown_report(session_data: dict, output_path: Path,
                             fix_recommendation: dict | None = None) -> None:
    """
    Render a Markdown debug trail report from session data.
    Complements the HTML report for text-based viewing / git storage.
    """
    session = session_data["session"]
    iterations = session_data["iterations"]
    fix = fix_recommendation or {}

    lines = [
        f"# HSDES NEXUS — Live-Debug — HSD {session.get('hsd_id', '?')}",
        "",
        f"**Title**: {session.get('title', '—')}",
        f"**Component**: {session.get('component', '—')}",
        f"**Execution Mode**: {session.get('execution_mode', '—')}",
        f"**Status**: {session.get('status', '—')}",
        f"**Started**: {session.get('created_at', '—')}",
        f"**Completed**: {session.get('updated_at', '—')}",
        f"**Total Iterations**: {len(iterations)}",
        "",
        "---",
        "",
    ]

    initial_logs = session.get("initial_logs_collected", [])
    if initial_logs:
        lines += ["## Initial Logs", ""]
        for log in initial_logs:
            lines.append(f"- **{log.get('category', 'unknown')}**")
            if log.get("collection_command"):
                lines.append(f"  - Command: {log['collection_command']}")
            if log.get("notes"):
                lines.append(f"  - Notes: {log['notes']}")
            snippet = log.get("content", "") or log.get("content_snippet", "")
            if snippet:
                preview = snippet.splitlines()[:8]
                lines += ["  ```", *[f"  {l}" for l in preview], "  ```"]
        lines += ["", "---", ""]

    # Hypothesis evolution summary
    lines += ["## Hypothesis Evolution", ""]
    lines += ["| Iter | Top Hypothesis | Confidence |", "|------|----------------|------------|"]
    for it in iterations:
        hyps = it.get("hypotheses", [])
        top = hyps[0] if hyps else {}
        conf = int(float(top.get("confidence", 0)) * 100)
        stmt = top.get("statement", "—")[:80]
        lines.append(f"| {it['iteration']} | {stmt} | {conf}% |")
    lines += ["", "---", ""]

    # Per-iteration detail
    lines += ["## Debug Iterations", ""]
    for it in iterations:
        hyps = it.get("hypotheses", [])
        top = hyps[0] if hyps else {}
        conf = int(float(top.get("confidence", 0)) * 100)
        lines += [
            f"### Iteration {it['iteration']}",
            f"*{it.get('timestamp', '')}*",
            "",
            f"**Top Hypothesis ({conf}%)**: {top.get('statement', '—')}",
            "",
        ]

        # Logs collected
        logs = it.get("logs_collected", [])
        if logs:
            lines += ["**Logs Collected**:"]
            for log in logs:
                lines.append(f"- `{log.get('category')}` — {log.get('full_path', '')}")
                snippet = log.get("content_snippet", "").strip()
                if snippet:
                    lines += ["  ```", *[f"  {l}" for l in snippet.split("\n")[:8]], "  ```"]
            lines.append("")

        # GENI analysis
        analysis = it.get("geni_analysis", "")
        if analysis:
            lines += ["**GENI Analysis**:", "", analysis.strip(), ""]

        # Next steps
        steps = it.get("next_steps", [])
        if steps:
            lines += ["**Recommended Next Steps**:"]
            for i, step in enumerate(steps, 1):
                lines.append(f"{i}. **{step.get('step', '')}**")
                if step.get("rationale"):
                    lines.append(f"   > {step['rationale']}")
                cmds = step.get("commands", [])
                if cmds:
                    lines += ["   ```", *[f"   {c}" for c in cmds], "   ```"]
            lines.append("")

        # User input
        user_input = it.get("user_input", "")
        if user_input:
            lines += [f"**User Input**: {user_input}", ""]

        lines.append("---")
        lines.append("")

    # Final root cause
    lines += ["## Final Root Cause", ""]
    if fix.get("statement"):
        lines += [fix["statement"], ""]
    if fix.get("spec_reference"):
        lines += [f"**Spec Reference**: {fix['spec_reference']}", ""]

    chain = fix.get("evidence_chain", [])
    if chain:
        lines += ["**Evidence Chain**:"]
        for ev in chain:
            lines.append(f"- Iter {ev.get('iteration', '?')}: {ev.get('finding', '')}")
        lines.append("")

    lines += [
        "---",
        "",
        f"*Generated by HSDES NEXUS (Live-Debug mode) — {_now_iso()}*",
        f"*Template: {TEMPLATE_VERSION} — project-c3/hsd-triage*",
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Markdown report written: %s", output_path)


def generate_json_session(session_data: dict, output_path: Path,
                          fix_recommendation: dict | None = None) -> None:
    """Write the full session state as a machine-readable JSON file."""
    payload = {
        **session_data,
        "fix_recommendation": fix_recommendation or {},
        "generated_at": _now_iso(),
        "template_version": TEMPLATE_VERSION,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("JSON session written: %s", output_path)


def generate_all_reports(session_id: str, fix_recommendation: dict | None = None) -> None:
    """
    Convenience function: load session from DB and render all three report formats.
    Writes to output/live_debug_<session_id>/:
      - session_report.html
      - session_report.md
      - session_data.json
    """
    db_path = _resolve_existing_db_path(session_id)
    if not db_path.exists():
        raise FileNotFoundError(f"Session DB not found: {db_path}")

    session_data = load_session(db_path, session_id)
    out_dir = db_path.parent

    generate_html_report(session_data, out_dir / "session_report.html", fix_recommendation)
    generate_markdown_report(session_data, out_dir / "session_report.md", fix_recommendation)
    generate_json_session(session_data, out_dir / "session_data.json", fix_recommendation)

    print(f"\n✅ Reports generated in: {out_dir}")
    print(f"   HTML:     {out_dir / 'session_report.html'}")
    print(f"   Markdown: {out_dir / 'session_report.md'}")
    print(f"   JSON:     {out_dir / 'session_data.json'}")


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _now_ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _safe_json(value: str) -> Any:
    try:
        return json.loads(value) if value else []
    except json.JSONDecodeError:
        return []


def make_session_id(hsd_id: str) -> str:
    return f"{hsd_id}_{_now_ts()}"


# ─── CLI Entry Point (standalone use) ─────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="HSD Live Debug session runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--hsd-id", help="HSD ID to debug")
    p.add_argument(
        "--initial-logs", default="",
        help="Path to JSON file with already-collected logs (see live_debug_input.schema.json)",
    )
    p.add_argument(
        "--execution-mode", default="manual",
        choices=["manual", "local", "ssh", "auto"],
        help="How commands are executed (default: manual)",
    )
    p.add_argument("--server", default="", help="SSH hostname (required if --execution-mode ssh)")
    p.add_argument("--ssh-user", default="", help="SSH username (default: current user)")
    p.add_argument(
        "--report-only", default="",
        help="Session ID to re-render reports for (skips debug loop)",
    )
    return p.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    args = _parse_args()

    if args.report_only:
        # Re-render all reports for an existing session
        generate_all_reports(args.report_only)
        return

    if not args.hsd_id:
        raise SystemExit("--hsd-id is required unless --report-only is used")

    hsd_id = args.hsd_id
    session_id = make_session_id(hsd_id)
    db_path = _get_db_path(session_id)
    out_dir = db_path.parent

    # Load initial logs before we persist the session so the DB captures the bootstrap state.
    initial_logs: list[dict] = []
    if args.initial_logs:
        try:
            initial_logs_path = Path(args.initial_logs)
            data = json.loads(initial_logs_path.read_text(encoding="utf-8"))
            initial_logs = data.get("initial_logs_collected", [])
            logger.info("Loaded %d initial log entries from %s", len(initial_logs), initial_logs_path)
        except Exception as exc:
            logger.warning("Could not load --initial-logs: %s", exc)

    logger.info("Starting live debug session %s", session_id)
    init_session_db(db_path)
    create_session(
        db_path, session_id, hsd_id,
        execution_mode=args.execution_mode,
        server=args.server,
        initial_logs=initial_logs,
    )

    adapter = make_adapter(args.execution_mode, args.server, args.ssh_user)

    print(f"\n{'═'*60}")
    print(f"  HSDES NEXUS — Live-Debug Session")
    print(f"  HSD ID:         {hsd_id}")
    print(f"  Session ID:     {session_id}")
    print(f"  Execution mode: {args.execution_mode}")
    print(f"  Output folder:  {out_dir}")
    print(f"{'═'*60}\n")
    print("This session is guided by the live_debug_skill.md agent.")
    print("Use GHCP with the skill active to drive the debug loop.")
    print("Call generate_all_reports() after the session to render reports.")


if __name__ == "__main__":
    main()
