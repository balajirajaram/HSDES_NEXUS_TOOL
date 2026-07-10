#!/usr/bin/env python3
"""
pythonsv_debug_runner.py
═══════════════════════════════════════════════════════════════════════════════
PythonSV Debug-flow execution engine for BugScout.

Purpose
-------
Drives the DEBUG flow: PythonSV is used to *collect debug data* or *run diagnostic
code* on a target SUT (live, hung, or crashed). The agent/skill generates the
``sv.*`` command bundle on the fly (via MCP register lookups); this runner is the
execution + readiness engine that:

  1. Verifies PythonSV access end-to-end BEFORE any user command runs
     (readiness gate G1-G6), and blocks on hard failures.
  2. Wraps a generated read-only ``sv.*`` command bundle into a headless PythonSV
     driver script.
  3. Dispatches the driver to the PythonSV *host* (e.g. a NUC) over WinRM or SSH,
     captures stdout + a JSON result payload, and returns collected data.

Separation of concerns
-----------------------
  - GENERATION (NL intent -> validated ``sv.*`` bundle) is performed by the agent
    which has MCP access. This runner only *executes* a bundle it is handed.
  - This runner is stdlib-only and transport-mockable so the readiness and driver
    logic can be unit-tested without a live target.

Debug flow is READ-ONLY by default and produces DATA + findings, not a verdict.

Entry point:
  python pythonsv_debug_runner.py readiness --host <nuc> --os <linux|windows|svos|uefi> --product dmr
  python pythonsv_debug_runner.py collect  --host <nuc> --bundle bundle.json
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).parent.resolve()
OUTPUT_BASE = SCRIPT_DIR / "output"
DEFAULT_TIMEOUT = 120

# Sentinel line the headless driver prints around its JSON result payload so the
# runner can extract structured data from mixed PythonSV console output.
RESULT_BEGIN = "===PYSV_RESULT_BEGIN==="
RESULT_END = "===PYSV_RESULT_END==="


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Target configuration ──────────────────────────────────────────────────────

# Access model for reaching the target silicon from the PythonSV host.
#   oob    : out-of-band JTAG/DCI (ipccli.baseaccess + OpenIPC/ITP, XDP/MIPI probe).
#            Works for ANY target OS incl. SVOS/UEFI/hung/crashed. Register level.
#   inband : PythonSV talks through the running target OS (only when OS alive).
ACCESS_OOB = "oob"
ACCESS_INBAND = "inband"
ACCESS_AUTO = "auto"

# Target OS families. SVOS/UEFI cannot be reached in-band -> force OOB.
_OS_FORCES_OOB = {"svos", "uefi"}


@dataclass
class PythonSVTarget:
    """Everything needed to reach and validate a PythonSV host + its SUT."""

    host: str                      # PythonSV host (e.g. NUC) reachable from runner
    product: str                   # e.g. "dmr", "gnr" -> selects pysv project
    target_os: str = "linux"       # linux | windows | svos | uefi
    access_mode: str = ACCESS_AUTO  # oob | inband | auto
    transport: str = "auto"        # winrm | ssh | auto
    user: str = ""                 # transport user
    required_pysv_version: str = ""  # optional expected version (G3 compare)
    pythonsv_root: str = ""        # host path to pysv project root (optional)

    def resolve_access_mode(self) -> str:
        """Resolve auto access mode from the target OS."""
        if self.access_mode != ACCESS_AUTO:
            return self.access_mode
        if self.target_os.lower() in _OS_FORCES_OOB:
            return ACCESS_OOB
        # Live OS: prefer OOB for register-level debug reliability, but inband is
        # valid when the OS is up. Default to OOB (works crashed or alive).
        return ACCESS_OOB


# ─── Transport adapters ────────────────────────────────────────────────────────

@dataclass
class TransportResult:
    ok: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    error: str = ""


class SSHTransport:
    """Run commands / scripts on the host over SSH (Linux or OpenSSH Windows)."""

    name = "ssh"

    def __init__(self, host: str, user: str = "", timeout: int = DEFAULT_TIMEOUT):
        self.host = host
        self.user = user
        self.timeout = timeout

    def run(self, command: str) -> TransportResult:
        target = f"{self.user}@{self.host}" if self.user else self.host
        ssh_cmd = [
            "ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=10", target, command,
        ]
        try:
            proc = subprocess.run(
                ssh_cmd, capture_output=True, text=True, timeout=self.timeout
            )
            return TransportResult(
                ok=proc.returncode == 0,
                stdout=proc.stdout,
                stderr=proc.stderr,
                exit_code=proc.returncode,
            )
        except subprocess.TimeoutExpired:
            return TransportResult(ok=False, error=f"ssh timeout after {self.timeout}s")
        except Exception as exc:  # pragma: no cover - defensive
            return TransportResult(ok=False, error=f"ssh error: {exc}")


class WinRMTransport:
    """Run commands / scripts on a Windows host over WinRM via local PowerShell.

    The runner shells out to PowerShell ``Invoke-Command`` so the exit code is
    captured INSIDE the remote session (a bare ``$LASTEXITCODE`` outside the
    session always returns 0).
    """

    name = "winrm"

    def __init__(
        self,
        host: str,
        user: str = "",
        password: str = "",
        port: int = 5985,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self.host = host
        self.user = user
        self.password = password
        self.port = port
        self.timeout = timeout

    def _build_ps(self, command: str) -> str:
        # Escape single quotes for the PowerShell single-quoted here-usage.
        remote = command.replace("'", "''")
        cred = ""
        args = f"-ComputerName {self.host} -Port {self.port} -Authentication Negotiate"
        if self.user:
            cred = (
                f"$pw = ConvertTo-SecureString '{self.password}' -AsPlainText -Force; "
                f"$cred = New-Object System.Management.Automation.PSCredential("
                f"'{self.user}', $pw); "
            )
            args += " -Credential $cred"
        return (
            f"{cred}"
            f"$s = New-PSSession {args}; "
            f"$r = Invoke-Command -Session $s -ScriptBlock {{ "
            f"$out = (& cmd /c '{remote}' 2>&1 | Out-String); "
            f"@{{ output = $out; exit_code = $LASTEXITCODE }} }}; "
            f"Remove-PSSession $s; "
            f"Write-Output $r.output; "
            f"exit $r.exit_code"
        )

    def run(self, command: str) -> TransportResult:
        ps = self._build_ps(command)
        try:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                capture_output=True, text=True, timeout=self.timeout,
            )
            return TransportResult(
                ok=proc.returncode == 0,
                stdout=proc.stdout,
                stderr=proc.stderr,
                exit_code=proc.returncode,
            )
        except subprocess.TimeoutExpired:
            return TransportResult(ok=False, error=f"winrm timeout after {self.timeout}s")
        except Exception as exc:  # pragma: no cover - defensive
            return TransportResult(ok=False, error=f"winrm error: {exc}")


def make_transport(target: PythonSVTarget, password: str = "") -> Any:
    """Return the transport for a target. ``auto`` picks WinRM for Windows hosts."""
    choice = target.transport.lower()
    if choice == "ssh":
        return SSHTransport(host=target.host, user=target.user)
    if choice == "winrm":
        return WinRMTransport(host=target.host, user=target.user, password=password)
    # auto: Windows target host -> WinRM, otherwise SSH.
    if target.target_os.lower() == "windows":
        return WinRMTransport(host=target.host, user=target.user, password=password)
    return SSHTransport(host=target.host, user=target.user)


# ─── Readiness gate (G1-G6) ────────────────────────────────────────────────────

# Gate outcomes.
GATE_PASS = "PASS"
GATE_BLOCK = "BLOCK"     # hard stop: cannot run user commands
GATE_WARN = "WARN"       # advisory, not blocking
GATE_UNKNOWN = "UNKNOWN"  # could not determine (e.g. dry-run)


@dataclass
class GateResult:
    id: str
    name: str
    status: str
    detail: str = ""


@dataclass
class ReadinessReport:
    target_host: str
    product: str
    target_os: str
    access_mode: str
    gates: list[GateResult] = field(default_factory=list)
    generated_at: str = field(default_factory=_now_iso)

    @property
    def blocked(self) -> bool:
        return any(g.status == GATE_BLOCK for g in self.gates)

    @property
    def ready(self) -> bool:
        """Ready only if no hard blocks. WARN/UNKNOWN are surfaced but non-fatal."""
        return not self.blocked

    def to_dict(self) -> dict:
        d = asdict(self)
        d["blocked"] = self.blocked
        d["ready"] = self.ready
        return d


# PythonSV bootstrap probe. Emitted to the host, run inside the pysv env. Prints a
# JSON blob describing version, connected sockets, unlock, and access. Read-only.
def _readiness_probe_script(target: PythonSVTarget) -> str:
    access = target.resolve_access_mode()
    return f"""
import json, sys
report = {{"pysv_version": None, "product": None, "sockets": [],
          "unlock": None, "access_probe": None, "errors": []}}
try:
    import pysv  # noqa
    report["pysv_version"] = getattr(pysv, "__version__", "unknown")
except Exception as exc:
    report["errors"].append("pysv import: %s" % exc)
try:
    import ipccli
    itp = ipccli.baseaccess()
    if "{access}" == "{ACCESS_OOB}":
        try:
            itp.forcereconfig()
        except Exception as exc:
            report["errors"].append("forcereconfig: %s" % exc)
except Exception as exc:
    report["errors"].append("ipccli baseaccess: %s" % exc)
try:
    from namednodes import sv
    _ = sv.socket0
    report["access_probe"] = "sv.socket0 present"
    try:
        report["sockets"] = [s.name for s in sv.sockets]
    except Exception:
        report["sockets"] = ["socket0"]
    report["product"] = getattr(sv, "product", None) or "{target.product}"
except Exception as exc:
    report["errors"].append("sv.socket0: %s" % exc)
print("{RESULT_BEGIN}")
print(json.dumps(report))
print("{RESULT_END}")
"""


def _extract_result(stdout: str) -> dict | None:
    """Pull the JSON payload printed between the result sentinels."""
    if RESULT_BEGIN not in stdout or RESULT_END not in stdout:
        return None
    chunk = stdout.split(RESULT_BEGIN, 1)[1].split(RESULT_END, 1)[0].strip()
    try:
        return json.loads(chunk)
    except json.JSONDecodeError:
        return None


def evaluate_gates(target: PythonSVTarget, probe: dict | None,
                   transport_ok: bool) -> list[GateResult]:
    """Map a probe payload + transport status onto the G1-G6 gate results.

    Pure function: no I/O, fully unit-testable.
    """
    gates: list[GateResult] = []
    access = target.resolve_access_mode()

    # G1 - host reachable via transport.
    gates.append(GateResult(
        "G1", "host reachable",
        GATE_PASS if transport_ok else GATE_BLOCK,
        "transport connected" if transport_ok else "transport unreachable",
    ))
    if not transport_ok or probe is None:
        # Nothing else can be determined without a live probe.
        for gid, name in [("G2", "pythonsv env"), ("G3", "version/platform match"),
                          ("G4", "jtag/probe connectivity"), ("G5", "access mode"),
                          ("G6", "unlock status")]:
            status = GATE_UNKNOWN if transport_ok else GATE_BLOCK
            gates.append(GateResult(gid, name, status,
                                    "probe unavailable" if transport_ok
                                    else "host unreachable"))
        return gates

    errors = probe.get("errors", [])

    # G2 - PythonSV env loaded (pysv importable).
    if probe.get("pysv_version"):
        gates.append(GateResult("G2", "pythonsv env", GATE_PASS,
                                f"pysv {probe['pysv_version']}"))
    else:
        gates.append(GateResult("G2", "pythonsv env", GATE_BLOCK,
                                "pysv not importable on host"))

    # G3 - correct product package + version for target platform.
    detected = (probe.get("product") or "").lower()
    want = target.product.lower()
    if detected and detected != want:
        gates.append(GateResult("G3", "version/platform match", GATE_BLOCK,
                                f"host product '{detected}' != target '{want}'"))
    elif target.required_pysv_version and probe.get("pysv_version") not in (
            target.required_pysv_version, None):
        gates.append(GateResult(
            "G3", "version/platform match",
            GATE_PASS if probe["pysv_version"] == target.required_pysv_version
            else GATE_WARN,
            f"pysv {probe.get('pysv_version')} (want {target.required_pysv_version})",
        ))
    else:
        gates.append(GateResult("G3", "version/platform match", GATE_PASS,
                                f"product {want}"))

    # G4 - JTAG/probe connectivity host -> SUT (sv.socket0 present).
    if probe.get("access_probe") and probe.get("sockets"):
        gates.append(GateResult("G4", "jtag/probe connectivity", GATE_PASS,
                                f"sockets: {', '.join(probe['sockets'])}"))
    else:
        remediation = ("re-seat XDP/MIPI/USB, itp.forcereconfig(), swap XDP/CCA"
                       if access == ACCESS_OOB else "confirm target OS reachable")
        gates.append(GateResult("G4", "jtag/probe connectivity", GATE_BLOCK,
                                f"sv.socket0 not reachable ({remediation})"))

    # G5 - access mode resolved for target OS.
    gates.append(GateResult("G5", "access mode", GATE_PASS,
                            f"{access} (os={target.target_os})"))

    # G6 - unlock / permission status (report, never bypass).
    unlock = probe.get("unlock")
    if unlock is False:
        gates.append(GateResult("G6", "unlock status", GATE_WARN,
                                "target not unlocked; protected regs may be blocked"))
    else:
        gates.append(GateResult("G6", "unlock status",
                                GATE_PASS if unlock else GATE_UNKNOWN,
                                "unlocked" if unlock else "unlock state unknown"))

    if errors:
        # Attach probe errors to the report via G2 detail without masking status.
        gates[1].detail += f" | probe notes: {'; '.join(errors)[:200]}"
    return gates


def run_readiness_gate(
    target: PythonSVTarget,
    transport: Any,
    host_python: str = "python",
) -> ReadinessReport:
    """Execute the readiness probe on the host and evaluate G1-G6."""
    probe_src = _readiness_probe_script(target)
    # Run the probe by piping the script to the host python via stdin-safe -c is
    # brittle; instead base64 the source to survive transport quoting.
    import base64
    b64 = base64.b64encode(probe_src.encode("utf-8")).decode("ascii")
    command = (
        f'{host_python} -c "import base64,sys;'
        f"exec(base64.b64decode('{b64}').decode('utf-8'))\""
    )
    result = transport.run(command)
    probe = _extract_result(result.stdout) if result.ok else None
    gates = evaluate_gates(target, probe, transport_ok=result.ok)
    return ReadinessReport(
        target_host=target.host,
        product=target.product,
        target_os=target.target_os,
        access_mode=target.resolve_access_mode(),
        gates=gates,
    )


# ─── Debug command bundle + headless driver ────────────────────────────────────

@dataclass
class DebugBundle:
    """A generated, read-only PythonSV collection request.

    ``reads`` are ``sv.*`` expressions to evaluate and return. ``named`` are
    named collectors (e.g. ``status_scope``) to invoke. The agent produces this
    from NL intent via MCP register lookup + VeWiki validation.
    """

    intent: str
    reads: list[str] = field(default_factory=list)
    named: list[str] = field(default_factory=list)
    read_only: bool = True

    @classmethod
    def from_dict(cls, d: dict) -> "DebugBundle":
        return cls(
            intent=d.get("intent", ""),
            reads=list(d.get("reads", [])),
            named=list(d.get("named", [])),
            read_only=bool(d.get("read_only", True)),
        )


def build_debug_driver(bundle: DebugBundle) -> str:
    """Wrap a read-only bundle into a headless PythonSV driver script.

    The driver assumes ``sv`` is already connected (readiness gate passed). It
    performs NO ``sv.refresh()`` (slow; must be done once before, per DMR BKM)
    and prints a JSON payload of collected values.
    """
    if not bundle.read_only:
        raise ValueError("Debug flow is read-only; refuse to build a writing driver")
    reads = json.dumps(bundle.reads)
    named = json.dumps(bundle.named)
    return f"""
import json
from namednodes import sv
data = {{"intent": {json.dumps(bundle.intent)}, "reads": {{}}, "named": {{}},
        "errors": []}}
for expr in {reads}:
    try:
        data["reads"][expr] = repr(eval(expr))
    except Exception as exc:
        data["errors"].append("read %s: %s" % (expr, exc))
for coll in {named}:
    try:
        fn = eval(coll)
        data["named"][coll] = repr(fn() if callable(fn) else fn)
    except Exception as exc:
        data["errors"].append("named %s: %s" % (coll, exc))
print("{RESULT_BEGIN}")
print(json.dumps(data))
print("{RESULT_END}")
"""


@dataclass
class CollectResult:
    ok: bool
    intent: str
    data: dict = field(default_factory=dict)
    stdout: str = ""
    error: str = ""
    collected_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict:
        return asdict(self)


class DebugRunner:
    """Execution engine for the Debug flow (readiness + collection)."""

    def __init__(self, target: PythonSVTarget, transport: Any,
                 host_python: str = "python"):
        self.target = target
        self.transport = transport
        self.host_python = host_python

    def readiness(self) -> ReadinessReport:
        return run_readiness_gate(self.target, self.transport, self.host_python)

    def collect(self, bundle: DebugBundle) -> CollectResult:
        """Execute a read-only collection bundle on the host and return data."""
        driver = build_debug_driver(bundle)
        import base64
        b64 = base64.b64encode(driver.encode("utf-8")).decode("ascii")
        command = (
            f'{self.host_python} -c "import base64;'
            f"exec(base64.b64decode('{b64}').decode('utf-8'))\""
        )
        result = self.transport.run(command)
        if not result.ok:
            return CollectResult(ok=False, intent=bundle.intent,
                                 stdout=result.stdout,
                                 error=result.error or result.stderr or "exec failed")
        payload = _extract_result(result.stdout)
        if payload is None:
            return CollectResult(ok=False, intent=bundle.intent,
                                 stdout=result.stdout,
                                 error="no result payload returned")
        return CollectResult(ok=True, intent=bundle.intent, data=payload,
                             stdout=result.stdout)


# ─── CLI ───────────────────────────────────────────────────────────────────────

def _target_from_args(args: argparse.Namespace) -> PythonSVTarget:
    return PythonSVTarget(
        host=args.host,
        product=args.product,
        target_os=args.os,
        access_mode=args.access_mode,
        transport=args.transport,
        user=args.user or "",
        required_pysv_version=args.required_version or "",
    )


def _print_readiness(report: ReadinessReport) -> None:
    print(f"\nReadiness - host={report.target_host} product={report.product} "
          f"os={report.target_os} access={report.access_mode}")
    print("-" * 64)
    for g in report.gates:
        print(f"  [{g.status:<7}] {g.id} {g.name}: {g.detail}")
    print("-" * 64)
    print(f"  RESULT: {'READY' if report.ready else 'BLOCKED'}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PythonSV Debug-flow runner")
    sub = parser.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--host", required=True, help="PythonSV host (e.g. NUC)")
    common.add_argument("--product", required=True, help="e.g. dmr, gnr")
    common.add_argument("--os", default="linux",
                        choices=["linux", "windows", "svos", "uefi"])
    common.add_argument("--access-mode", default=ACCESS_AUTO,
                        choices=[ACCESS_OOB, ACCESS_INBAND, ACCESS_AUTO])
    common.add_argument("--transport", default="auto",
                        choices=["winrm", "ssh", "auto"])
    common.add_argument("--user", default="")
    common.add_argument("--password", default="",
                        help="WinRM password (prefer env/secret store)")
    common.add_argument("--required-version", default="")
    common.add_argument("--host-python", default="python")

    p_ready = sub.add_parser("readiness", parents=[common],
                             help="Run the G1-G6 readiness gate")
    p_ready.add_argument("--json", action="store_true")

    p_collect = sub.add_parser("collect", parents=[common],
                               help="Run a read-only collection bundle")
    p_collect.add_argument("--bundle", required=True,
                           help="Path to a bundle JSON {intent, reads[], named[]}")
    p_collect.add_argument("--json", action="store_true")
    p_collect.add_argument("--skip-readiness", action="store_true",
                           help="Skip the readiness gate (NOT recommended)")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    target = _target_from_args(args)
    transport = make_transport(target, password=args.password)
    runner = DebugRunner(target, transport, host_python=args.host_python)

    if args.cmd == "readiness":
        report = runner.readiness()
        if args.json:
            print(json.dumps(report.to_dict(), indent=2))
        else:
            _print_readiness(report)
        return 0 if report.ready else 2

    if args.cmd == "collect":
        if not args.skip_readiness:
            report = runner.readiness()
            _print_readiness(report)
            if report.blocked:
                print("BLOCKED: readiness gate failed; refusing to run collection.")
                return 2
        bundle = DebugBundle.from_dict(
            json.loads(Path(args.bundle).read_text(encoding="utf-8"))
        )
        result = runner.collect(bundle)
        if args.json:
            print(json.dumps(result.to_dict(), indent=2))
        else:
            print(f"\nCollect — intent: {result.intent}")
            print(f"  ok={result.ok}")
            if result.error:
                print(f"  error: {result.error}")
            for k, v in result.data.get("reads", {}).items():
                print(f"  {k} = {v}")
        return 0 if result.ok else 1

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
