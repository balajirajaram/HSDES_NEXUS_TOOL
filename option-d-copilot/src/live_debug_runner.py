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
import base64
import json
import logging
import os
import re
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


NUC_WINRM_SETUP_STEPS = (
    "SSH to the NUC was not reachable, and WinRM is not ready yet.\n"
    "To enable the WinRM path, run these ONCE on the NUC in an elevated PowerShell, "
    "then retry:\n"
    "  winrm quickconfig -force\n"
    "  Enable-PSRemoting -Force\n"
    "  Set-Item WSMan:\\localhost\\Service\\AllowUnencrypted $true\n"
    "  Set-Item WSMan:\\localhost\\Service\\Auth\\Basic $true\n"
    "  New-NetFirewallRule -DisplayName 'WinRM 5985' -Direction Inbound "
    "-LocalPort 5985 -Protocol TCP -Action Allow"
)

# Init preamble prepended to every PythonSV run (unless the user opts out):
# unlocks a locked part and refreshes the namednodes tree, so `sv` / `ipc` are
# ready and register access works without the user typing this each time.
NUC_PYTHONSV_PREAMBLE = (
    "import ipccli\n"
    "ipc = ipccli.baseaccess()\n"
    "try:\n"
    "    ipc.unlock()\n"
    "except Exception as _e:\n"
    "    print('[init] ipc.unlock skipped:', _e)\n"
    "import namednodes\n"
    "sv = namednodes.sv\n"
    "sv.refresh()\n"
)


def clean_pythonsv_output(text: str) -> str:
    """Strip PythonSV boot noise (EOL banner, version table, per-IP init lines,
    IPC handshake, SyntaxWarnings) so the response is readable. Collapses the
    many 'Initialized <ip>' lines into a single summary."""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    _noise = re.compile(
        r"SyntaxWarning|if arg is 'self'|Using XDPA|"
        r"Error while Accessing special Endpoint|In case of any issues|"
        r"please include the following table|Connecting to IPC API|"
        r"Initializing IPC API|IPC-CLI:|OpenIPC", re.I)
    init_ips: list[str] = []
    out: list[str] = []
    for raw in text.split("\n"):
        s = raw.rstrip()
        stripped = s.strip()
        # ASCII banner box (END-OF-LIFE notice etc.)
        if re.fullmatch(r"\*+", stripped) or (stripped.startswith("*") and stripped.endswith("*")):
            continue
        # Version table rows / rules
        if re.fullmatch(r"[=|\-]{3,}", stripped) or re.fullmatch(r"\|.*\|", stripped):
            continue
        m = re.fullmatch(r"Initialized\s+(\S+)", stripped)
        if m:
            init_ips.append(m.group(1))
            continue
        if _noise.search(stripped):
            continue
        out.append(s)
    cleaned = "\n".join(out)
    if init_ips:
        cleaned += (f"\n[init] {len(init_ips)} IP components initialized: "
                    f"{', '.join(init_ips)}")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned


def interpret_pythonsv_output(text: str) -> list:
    """Detect known PythonSV / silicon states and return short, plain-English
    notes so the user immediately understands SUT state vs. tool problems."""
    notes: list[str] = []
    if not text:
        return notes
    low = text.lower()
    m = re.search(r"Discovered:\s*([^\r\n]+)", text)
    if m:
        notes.append(f"Discovered part: {m.group(1).strip()}")
    if any(k in low for k in ("is locked", "requires unlock", "run ipc.unlock")):
        notes.append("Part was LOCKED — the init preamble auto-runs ipc.unlock().")
    if "not out of reset" in low or "reset phase not_set" in low:
        notes.append("SUT is NOT out of reset — uncore/PCU not enumerated yet; only "
                     "cores/IPC are available.")
    if "bring up hasnt started" in low or "bring up hasn't started" in low:
        notes.append("Pcode bring-up has not started — uncore/pcudata registers are "
                     "unavailable.")
    if "unknown attribute uncore" in low:
        notes.append("`uncore` is not present (part locked / not fully enumerated). "
                     "Unlock + sv.refresh(), or wait for bring-up.")
    if any(k in low for k in ("port in use", "unable_to_connect", "could not reserve port")):
        notes.append("IPC port busy — another PythonSV/OpenIPC session may be attached. "
                     "Close it, then reconnect.")
    if "could not load pcie" in low:
        notes.append("PCIe IP failed to load — consistent with an early-reset / locked state.")
    # Undefined interactive helpers (dimminfo, itp, mcscan, ...) — they aren't
    # auto-loaded in a non-interactive process; the module must be imported.
    undefined = []
    for nm in re.findall(r"NameError: name '([^']+)' is not defined", text):
        if nm not in undefined:
            undefined.append(nm)
    if undefined:
        names = ", ".join(f"`{n}`" for n in undefined)
        notes.append(f"{names} not defined — these are PythonSV interactive helpers that "
                     f"a plain session doesn't auto-load. Import the module first "
                     f"(e.g. `from <project>... import {undefined[0]}`), then call it.")
    missing_mod = re.findall(r"ModuleNotFoundError: No module named '([^']+)'", text)
    if missing_mod:
        mods = ", ".join(f"`{m}`" for m in dict.fromkeys(missing_mod))
        notes.append(f"Missing module(s) {mods} — a user/console tool expects the "
                     f"interactive PythonSV sys.path. Add the project dir to sys.path "
                     f"(e.g. C:\\pythonsv\\<project>) before importing it.")
    if "no ping" in low or "did not respond" in low:
        notes.append("SUT OS communicator did not respond (No ping) — silicon is reachable "
                     "via ITP, but OS-level helpers won't work until the SUT is up.")
    if not undefined and not missing_mod and "traceback (most recent call last)" in low:
        notes.append("A PythonSV command raised an exception (see output) — usually a "
                     "usage/topology mismatch on this part, not a tool error.")
    return notes


class NUCPythonSVAdapter:
    """Run PythonSV / sideband commands on a lab NUC that retains ITP/PythonSV
    access to a SUT (Server Under Test) that is itself hung or unreachable.

    The NUC is a **Windows** host. Two transports are supported and, by default,
    tried in order: **SSH** first (OpenSSH server), then **WinRM** as a fallback
    when SSH is not reachable. Override with ``NUC_TRANSPORT`` = ``auto`` (default)
    / ``ssh`` / ``winrm``. PythonSV lives at ``pythonsv_path``. Credentials come
    ONLY from the environment (``NUC_PASSWORD``) and are NEVER logged, echoed to
    the UI, or written to disk; any occurrence in output is masked.
    """

    def __init__(self, host: str, user: str = "", pythonsv_path: str = r"C:\pythonsv",
                 password: str = ""):
        self.host = host
        raw_user = user or os.getenv("NUC_USER", "")
        # SSH / WinRM-NTLM to a Windows local account use the bare account name;
        # strip a ".\" / "./" (local-machine) prefix that auth stacks reject.
        self.user = re.sub(r"^\.[\\/]+", "", raw_user.strip())
        self.pythonsv_path = pythonsv_path or os.getenv("NUC_PYTHONSV_PATH", r"C:\pythonsv")
        self.preferred = os.getenv("NUC_TRANSPORT", "auto").lower()   # auto|ssh|winrm
        self.ssh_port = int(os.getenv("NUC_SSH_PORT", "22"))
        # WinRM transport tuning (all optional; sensible Windows defaults).
        self.winrm_transport = os.getenv("NUC_WINRM_TRANSPORT", "ntlm")
        self.winrm_scheme = os.getenv("NUC_WINRM_SCHEME", "http")
        self.winrm_port = os.getenv("NUC_WINRM_PORT",
                                    "5986" if self.winrm_scheme == "https" else "5985")
        # Password: prefer the value passed for this connection (e.g. typed in the
        # UI), else fall back to the NUC_PASSWORD env. Kept in memory only — never
        # logged, echoed, or written to disk; masked in all output.
        self._password = password or os.getenv("NUC_PASSWORD", "")
        self.transport_used = ""
        if not self.host:
            raise ValueError("NUC host is required (set NUC_HOST or pass --nuc-host).")
        if not self._password:
            raise ValueError(
                "NUC password is required. Enter it in the PythonSV tab (or set "
                "NUC_PASSWORD). It is used only for this connection and never stored."
            )

    def _mask(self, text: str) -> str:
        if self._password and text:
            return text.replace(self._password, "***")
        return text

    def _transport_order(self) -> list[str]:
        if self.preferred == "ssh":
            return ["ssh"]
        if self.preferred == "winrm":
            return ["winrm"]
        return ["ssh", "winrm"]

    # --- SSH transport (OpenSSH on the Windows NUC; default shell is cmd.exe) ---
    def _ssh_client(self) -> Any:
        import paramiko  # type: ignore
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(self.host, port=self.ssh_port, username=self.user,
                       password=self._password, timeout=15)
        return client

    def _python_oneliner(self, script_text: str) -> str:
        """Wrap a multi-line PythonSV script into a single `python -c` call.

        Base64-encoding avoids all shell quoting/newline issues AND runs every
        line in ONE process, so imports and the PythonSV/IPC session persist
        across lines (mirroring an interactive PythonSV console).
        """
        b64 = base64.b64encode(script_text.encode("utf-8")).decode("ascii")
        return (f"python -c \"import base64;exec(base64.b64decode('{b64}')"
                f".decode('utf-8'))\"")

    def _ssh_run_all(self, commands: list[str]) -> str:
        client = self._ssh_client()
        try:
            script_text = "\n".join(str(c) for c in commands)
            wrapped = f'cd /d "{self.pythonsv_path}" && {self._python_oneliner(script_text)}'
            logger.info("NUC PythonSV (ssh) %s: running %d line(s) in one session",
                        self.host, len(commands))
            # PythonSV/IPC init can take a while — allow a generous timeout.
            _in, out, err = client.exec_command(wrapped, timeout=900)
            text = (out.read().decode("utf-8", "replace")
                    + err.read().decode("utf-8", "replace"))
        finally:
            client.close()
        return text

    # --- WinRM transport (PowerShell remoting) ---
    def _winrm_session(self) -> Any:
        import winrm  # type: ignore
        endpoint = f"{self.winrm_scheme}://{self.host}:{self.winrm_port}/wsman"
        # Long timeouts so PythonSV init (which can take minutes) doesn't get cut.
        return winrm.Session(
            endpoint,
            auth=(self.user, self._password),
            transport=self.winrm_transport,
            server_cert_validation="ignore",
            read_timeout_sec=920,
            operation_timeout_sec=900,
        )

    def _winrm_run_all(self, commands: list[str]) -> str:
        session = self._winrm_session()
        script_text = "\n".join(str(c) for c in commands)
        ps = f'Set-Location -Path "{self.pythonsv_path}"; {self._python_oneliner(script_text)}'
        logger.info("NUC PythonSV (winrm) %s: running %d line(s) in one session",
                    self.host, len(commands))
        r = session.run_ps(ps)
        return ((r.std_out or b"") + (r.std_err or b"")).decode("utf-8", "replace")

    def run(self, commands: list[str], context: str = "", with_preamble: bool = True) -> str:
        cmds = list(commands)
        if with_preamble:
            # Prepend unlock + sv.refresh so register access just works.
            cmds = NUC_PYTHONSV_PREAMBLE.splitlines() + cmds
        errors: list[str] = []
        for transport in self._transport_order():
            try:
                out = (self._ssh_run_all(cmds) if transport == "ssh"
                       else self._winrm_run_all(cmds))
                self.transport_used = transport
                return self._mask(f"[transport: {transport}]\n{out}")
            except ImportError as exc:
                errors.append(f"{transport}: driver missing ({exc})")
            except Exception as exc:
                errors.append(f"{transport}: {self._mask(str(exc))}")
        msg = ("[NUC PythonSV ERROR] Could not reach NUC via "
               + " then ".join(self._transport_order()) + ".\n" + "\n".join(errors))
        if "winrm" in self._transport_order():
            msg += "\n\n" + NUC_WINRM_SETUP_STEPS
        return self._mask(msg)

    def probe(self) -> dict:
        """Verify the NUC is reachable (SSH → WinRM) and PythonSV exists.

        Returns ``connected`` / ``transport`` / ``pythonsv_present`` plus, when no
        transport works and WinRM was in play, ``winrm_setup_required`` + the
        prerequisite steps so the UI can prompt the user.
        """
        errors: list[str] = []
        for transport in self._transport_order():
            try:
                if transport == "ssh":
                    client = self._ssh_client()
                    lines: list[str] = []
                    present = False
                    try:
                        checks = [
                            ("hostname", "hostname"),
                            ("pythonsv-path",
                             f'if exist "{self.pythonsv_path}" (echo FOUND) else (echo MISSING)'),
                        ]
                        for label, cmd in checks:
                            _in, out, err = client.exec_command(cmd, timeout=30)
                            text = (out.read().decode("utf-8", "replace")
                                    + err.read().decode("utf-8", "replace")).strip()
                            lines.append(f"[{label}] {text}")
                            if label == "pythonsv-path" and "FOUND" in text:
                                present = True
                    finally:
                        client.close()
                    self.transport_used = "ssh"
                    return {"connected": True, "transport": "ssh",
                            "pythonsv_present": present,
                            "output": self._mask("\n".join(lines)),
                            "winrm_setup_required": False}

                session = self._winrm_session()
                lines = []
                present = False
                checks_ps = [
                    ("hostname", "[System.Net.Dns]::GetHostName()"),
                    ("pythonsv-path",
                     f"if (Test-Path -Path '{self.pythonsv_path}') {{ 'FOUND' }} else {{ 'MISSING' }}"),
                ]
                for label, script in checks_ps:
                    r = session.run_ps(script)
                    text = ((r.std_out or b"") + (r.std_err or b"")).decode("utf-8", "replace").strip()
                    lines.append(f"[{label}] {text}")
                    if label == "pythonsv-path" and "FOUND" in text:
                        present = True
                self.transport_used = "winrm"
                return {"connected": True, "transport": "winrm",
                        "pythonsv_present": present,
                        "output": self._mask("\n".join(lines)),
                        "winrm_setup_required": False}
            except ImportError as exc:
                errors.append(f"{transport}: driver missing ({exc})")
            except Exception as exc:
                errors.append(f"{transport}: {self._mask(str(exc))}")

        winrm_needed = "winrm" in self._transport_order()
        out = ("Could not reach NUC via " + " then ".join(self._transport_order())
               + ".\n" + "\n".join(errors))
        result = {"connected": False, "transport": "", "pythonsv_present": False,
                  "output": self._mask(out), "winrm_setup_required": winrm_needed}
        if winrm_needed:
            result["winrm_setup_steps"] = NUC_WINRM_SETUP_STEPS
        return result


def run_nuc_pythonsv_probe(nuc_host: str = "", nuc_user: str = "",
                           pythonsv_path: str = "", password: str = "") -> dict:
    """Build a NUC adapter and run a connectivity + PythonSV-path probe."""
    adapter = NUCPythonSVAdapter(
        host=nuc_host or os.getenv("NUC_HOST", ""),
        user=nuc_user or os.getenv("NUC_USER", ""),
        pythonsv_path=pythonsv_path or os.getenv("NUC_PYTHONSV_PATH", r"C:\pythonsv"),
        password=password,
    )
    return adapter.probe()


def make_adapter(execution_mode: str, server: str = "", ssh_user: str = "",
                 nuc_host: str = "", nuc_user: str = "",
                 pythonsv_path: str = "") -> Any:
    """Return the appropriate execution adapter for the given mode."""
    mode = execution_mode.lower()
    if mode == "local":
        return LocalAdapter()
    if mode == "ssh":
        if not server:
            raise ValueError("--server is required when --execution-mode is ssh")
        return SSHAdapter(host=server, user=ssh_user)
    if mode in ("nuc", "nuc-pythonsv", "pythonsv"):
        host = nuc_host or os.getenv("NUC_HOST", "")
        user = nuc_user or os.getenv("NUC_USER", "")
        path = pythonsv_path or os.getenv("NUC_PYTHONSV_PATH", r"C:\pythonsv")
        return NUCPythonSVAdapter(host=host, user=user, pythonsv_path=path)
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
        choices=["manual", "local", "ssh", "auto", "nuc-pythonsv"],
        help="How commands are executed (default: manual). Use 'nuc-pythonsv' to "
             "drive PythonSV on a lab NUC when the SUT is hung/unreachable.",
    )
    p.add_argument("--server", default="", help="SSH hostname (required if --execution-mode ssh)")
    p.add_argument("--ssh-user", default="", help="SSH username (default: current user)")
    p.add_argument("--nuc-host", default="",
                   help="NUC hostname for nuc-pythonsv mode (default: NUC_HOST env)")
    p.add_argument("--nuc-user", default="",
                   help="NUC username for nuc-pythonsv mode (default: NUC_USER env). "
                        "The NUC password comes only from NUC_PASSWORD in the environment.")
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

    adapter = make_adapter(
        args.execution_mode, args.server, args.ssh_user,
        nuc_host=getattr(args, "nuc_host", ""),
        nuc_user=getattr(args, "nuc_user", ""),
    )

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
