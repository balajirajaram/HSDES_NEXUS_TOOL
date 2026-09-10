"""Offline closed-loop AutoHSD integration tests; no HSDES or real SSH."""

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import analyzer  # noqa: E402
from app import node_triage as nt  # noqa: E402


class FakeClient:
    async def get_article(self, hsd_id):
        return {"id": hsd_id, "title": "[CWF] [cs17ca101ms0408] Node hang", "description": "Socket 1"}


class TestAutoHsdClosedLoop(unittest.TestCase):
    def test_reachable_collection_creates_before_after_and_dry_run(self):
        initial = {"report_markdown": "initial", "ownership": {}, "extracted_ownership": {}}
        final = {"report_markdown": "final", "ownership": {}, "extracted_ownership": {}}
        node = {"reachable": True, "host": "cs17ca101ms0408.deacluster.intel.com",
                "profiles": ["tor_timeout"], "combined": "MCA status", "logs": {"dmesg": "MCA"},
                "command_audit": [{"name": "dmesg", "return_code": 0}]}
        update = {"comment_html": "draft", "posted": None}
        with tempfile.TemporaryDirectory() as tmp, patch("app.hsdes_client.HSDESClient", return_value=FakeClient()), \
             patch.object(analyzer, "analyze", new=AsyncMock(side_effect=[initial, final])), \
             patch.object(nt, "collect_node_logs", new=AsyncMock(return_value=node)), \
             patch.object(analyzer, "update_hsd_report", new=AsyncMock(return_value=update)), \
             patch.object(analyzer, "_post_gate", return_value={"allow": False, "reason": "test"}):
            with patch.dict("os.environ", {"AUTOHSD_RUN_ROOT": tmp, "AUTOHSD_ALLOW_SSH_COLLECTION": "true"}):
                result = asyncio.run(nt.triage_auto_hsd_end_to_end("16031734105", dry_run=True))
                self.assertTrue(result["ok"])
                self.assertFalse(result["posted"])
                run_dir = Path(result["run_dir"])
                for name in ("initial_report.md", "collection_plan.json", "command_audit.jsonl",
                         "final_report.md", "before_after.json", "hsd_comment_preview.html", "run_manifest.json"):
                    self.assertTrue((run_dir / name).exists(), name)

    def test_unreachable_node_is_not_posted(self):
        node = {"reachable": False, "host": "cs17ca101ms0408.deacluster.intel.com",
                "error": "DNS failure", "command_audit": []}
        initial = {"report_markdown": "initial", "ownership": {}, "extracted_ownership": {}}
        with tempfile.TemporaryDirectory() as tmp, patch("app.hsdes_client.HSDESClient", return_value=FakeClient()), \
             patch.object(analyzer, "analyze", new=AsyncMock(return_value=initial)), \
             patch.object(nt, "collect_node_logs", new=AsyncMock(return_value=node)), \
             patch.object(analyzer, "update_hsd_report", new=AsyncMock(return_value={"posted": None, "comment_html": "draft"})), \
             patch.object(analyzer, "_post_gate", return_value={"allow": False}):
            with patch.dict("os.environ", {"AUTOHSD_RUN_ROOT": tmp}):
                result = asyncio.run(nt.triage_auto_hsd_end_to_end("16031734105", dry_run=True))
        self.assertEqual(result["before_after"]["node_status"], "UNAVAILABLE")
        self.assertFalse(result["posted"])

    def test_profile_commands_are_read_only(self):
        dangerous = ("reboot", "shutdown", " reset", "rm -", "apt install", "systemctl stop", "wrmsr")
        for commands in nt._PROFILE_CMDS.values():
            for _, command in commands:
                self.assertFalse(any(token in command.lower() for token in dangerous), command)


if __name__ == "__main__":
    unittest.main(verbosity=2)
