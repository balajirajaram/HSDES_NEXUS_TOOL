#!/usr/bin/env python3
"""Unit tests for src/pythonsv_debug_runner.py (mocked transport, no live target)."""

import json
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

import pythonsv_debug_runner as pdr  # noqa: E402


class FakeTransport:
    """Transport stub that returns a scripted TransportResult."""

    def __init__(self, result: pdr.TransportResult):
        self._result = result
        self.last_command = None

    def run(self, command: str) -> pdr.TransportResult:
        self.last_command = command
        return self._result


def _probe_stdout(payload: dict) -> str:
    return f"noise\n{pdr.RESULT_BEGIN}\n{json.dumps(payload)}\n{pdr.RESULT_END}\ntail"


# ─── Access mode resolution ─────────────────────────────────────────────────────

class TestAccessMode(unittest.TestCase):
    def test_svos_forces_oob(self):
        t = pdr.PythonSVTarget(host="h", product="dmr", target_os="svos")
        self.assertEqual(t.resolve_access_mode(), pdr.ACCESS_OOB)

    def test_uefi_forces_oob(self):
        t = pdr.PythonSVTarget(host="h", product="dmr", target_os="uefi")
        self.assertEqual(t.resolve_access_mode(), pdr.ACCESS_OOB)

    def test_linux_auto_defaults_oob(self):
        t = pdr.PythonSVTarget(host="h", product="dmr", target_os="linux")
        self.assertEqual(t.resolve_access_mode(), pdr.ACCESS_OOB)

    def test_explicit_inband_preserved(self):
        t = pdr.PythonSVTarget(host="h", product="dmr", target_os="linux",
                               access_mode=pdr.ACCESS_INBAND)
        self.assertEqual(t.resolve_access_mode(), pdr.ACCESS_INBAND)


# ─── Transport selection ────────────────────────────────────────────────────────

class TestMakeTransport(unittest.TestCase):
    def test_windows_host_auto_winrm(self):
        t = pdr.PythonSVTarget(host="h", product="dmr", target_os="windows")
        self.assertIsInstance(pdr.make_transport(t), pdr.WinRMTransport)

    def test_linux_host_auto_ssh(self):
        t = pdr.PythonSVTarget(host="h", product="dmr", target_os="linux")
        self.assertIsInstance(pdr.make_transport(t), pdr.SSHTransport)

    def test_explicit_ssh(self):
        t = pdr.PythonSVTarget(host="h", product="dmr", target_os="windows",
                               transport="ssh")
        self.assertIsInstance(pdr.make_transport(t), pdr.SSHTransport)


# ─── Result extraction ──────────────────────────────────────────────────────────

class TestExtractResult(unittest.TestCase):
    def test_extracts_payload(self):
        out = _probe_stdout({"a": 1})
        self.assertEqual(pdr._extract_result(out), {"a": 1})

    def test_missing_sentinels_returns_none(self):
        self.assertIsNone(pdr._extract_result("just some output"))

    def test_bad_json_returns_none(self):
        out = f"{pdr.RESULT_BEGIN}\nnot json\n{pdr.RESULT_END}"
        self.assertIsNone(pdr._extract_result(out))


# ─── Gate evaluation (pure) ─────────────────────────────────────────────────────

class TestEvaluateGates(unittest.TestCase):
    def _target(self, **kw):
        base = dict(host="h", product="dmr", target_os="linux")
        base.update(kw)
        return pdr.PythonSVTarget(**base)

    def _status(self, gates, gid):
        return next(g.status for g in gates if g.id == gid)

    def test_transport_down_blocks_all(self):
        gates = pdr.evaluate_gates(self._target(), probe=None, transport_ok=False)
        self.assertEqual(self._status(gates, "G1"), pdr.GATE_BLOCK)
        self.assertTrue(all(g.status == pdr.GATE_BLOCK for g in gates))

    def test_transport_up_no_probe_unknowns(self):
        gates = pdr.evaluate_gates(self._target(), probe=None, transport_ok=True)
        self.assertEqual(self._status(gates, "G1"), pdr.GATE_PASS)
        self.assertEqual(self._status(gates, "G2"), pdr.GATE_UNKNOWN)

    def test_healthy_probe_all_pass(self):
        probe = {"pysv_version": "1.2.3", "product": "dmr",
                 "sockets": ["socket0", "socket1"],
                 "access_probe": "sv.socket0 present", "unlock": True, "errors": []}
        gates = pdr.evaluate_gates(self._target(), probe, transport_ok=True)
        for gid in ("G1", "G2", "G3", "G4", "G5", "G6"):
            self.assertIn(self._status(gates, gid), (pdr.GATE_PASS,))

    def test_product_mismatch_blocks_g3(self):
        probe = {"pysv_version": "1.2.3", "product": "gnr",
                 "sockets": ["socket0"], "access_probe": "sv.socket0 present",
                 "unlock": True, "errors": []}
        gates = pdr.evaluate_gates(self._target(product="dmr"), probe, transport_ok=True)
        self.assertEqual(self._status(gates, "G3"), pdr.GATE_BLOCK)

    def test_no_pysv_blocks_g2(self):
        probe = {"pysv_version": None, "product": "dmr", "sockets": [],
                 "access_probe": None, "unlock": None, "errors": ["pysv import: x"]}
        gates = pdr.evaluate_gates(self._target(), probe, transport_ok=True)
        self.assertEqual(self._status(gates, "G2"), pdr.GATE_BLOCK)

    def test_no_jtag_blocks_g4(self):
        probe = {"pysv_version": "1.0", "product": "dmr", "sockets": [],
                 "access_probe": None, "unlock": True, "errors": []}
        gates = pdr.evaluate_gates(self._target(), probe, transport_ok=True)
        self.assertEqual(self._status(gates, "G4"), pdr.GATE_BLOCK)

    def test_locked_target_warns_g6(self):
        probe = {"pysv_version": "1.0", "product": "dmr", "sockets": ["socket0"],
                 "access_probe": "sv.socket0 present", "unlock": False, "errors": []}
        gates = pdr.evaluate_gates(self._target(), probe, transport_ok=True)
        self.assertEqual(self._status(gates, "G6"), pdr.GATE_WARN)


# ─── Readiness report semantics ─────────────────────────────────────────────────

class TestReadinessReport(unittest.TestCase):
    def test_blocked_when_any_block(self):
        r = pdr.ReadinessReport("h", "dmr", "linux", "oob",
                                gates=[pdr.GateResult("G1", "x", pdr.GATE_BLOCK)])
        self.assertTrue(r.blocked)
        self.assertFalse(r.ready)

    def test_ready_when_only_warn(self):
        r = pdr.ReadinessReport("h", "dmr", "linux", "oob",
                                gates=[pdr.GateResult("G6", "x", pdr.GATE_WARN)])
        self.assertFalse(r.blocked)
        self.assertTrue(r.ready)


# ─── Driver build ───────────────────────────────────────────────────────────────

class TestBuildDriver(unittest.TestCase):
    def test_read_only_bundle_builds(self):
        b = pdr.DebugBundle(intent="x", reads=["sv.socket0.foo"], named=["status_scope"])
        driver = pdr.build_debug_driver(b)
        self.assertIn("sv.socket0.foo", driver)
        self.assertIn(pdr.RESULT_BEGIN, driver)

    def test_writing_bundle_refused(self):
        b = pdr.DebugBundle(intent="x", reads=[], read_only=False)
        with self.assertRaises(ValueError):
            pdr.build_debug_driver(b)


# ─── Runner readiness + collect (mocked transport) ──────────────────────────────

class TestDebugRunner(unittest.TestCase):
    def _target(self):
        return pdr.PythonSVTarget(host="h", product="dmr", target_os="linux")

    def test_readiness_pass(self):
        payload = {"pysv_version": "1.0", "product": "dmr", "sockets": ["socket0"],
                   "access_probe": "sv.socket0 present", "unlock": True, "errors": []}
        tr = pdr.TransportResult(ok=True, stdout=_probe_stdout(payload), exit_code=0)
        runner = pdr.DebugRunner(self._target(), FakeTransport(tr))
        report = runner.readiness()
        self.assertTrue(report.ready)

    def test_readiness_block_on_unreachable(self):
        tr = pdr.TransportResult(ok=False, error="timeout")
        runner = pdr.DebugRunner(self._target(), FakeTransport(tr))
        self.assertTrue(runner.readiness().blocked)

    def test_collect_returns_data(self):
        payload = {"intent": "x", "reads": {"sv.socket0.foo": "0x1"},
                   "named": {}, "errors": []}
        tr = pdr.TransportResult(ok=True, stdout=_probe_stdout(payload), exit_code=0)
        runner = pdr.DebugRunner(self._target(), FakeTransport(tr))
        b = pdr.DebugBundle(intent="x", reads=["sv.socket0.foo"])
        result = runner.collect(b)
        self.assertTrue(result.ok)
        self.assertEqual(result.data["reads"]["sv.socket0.foo"], "0x1")

    def test_collect_exec_failure(self):
        tr = pdr.TransportResult(ok=False, error="exec failed")
        runner = pdr.DebugRunner(self._target(), FakeTransport(tr))
        result = runner.collect(pdr.DebugBundle(intent="x", reads=["sv.socket0.foo"]))
        self.assertFalse(result.ok)

    def test_collect_no_payload(self):
        tr = pdr.TransportResult(ok=True, stdout="no sentinels here", exit_code=0)
        runner = pdr.DebugRunner(self._target(), FakeTransport(tr))
        result = runner.collect(pdr.DebugBundle(intent="x", reads=["sv.socket0.foo"]))
        self.assertFalse(result.ok)
        self.assertIn("no result payload", result.error)


if __name__ == "__main__":
    unittest.main(verbosity=2)
