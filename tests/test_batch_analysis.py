import asyncio
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import main  # noqa: E402


class TestBatchAnalysis(unittest.TestCase):

    def test_duplicate_ids_are_deduplicated(self):
        self.assertEqual(
            main._dedupe_batch_ids(["14028507593", "14028507593", "https://hsdes.intel.com/article/21044871638"]),
            ["14028507593", "21044871638"],
        )

    def test_three_ids_stream_individual_results_and_keep_weak_as_draft(self):
        request = type("Request", (), {"session": {}})()
        analyze_results = {
            "14028507593": {"report_markdown": "report-1"},
            "21044871638": {"report_markdown": "report-2"},
            "15019342741": {"report_markdown": "report-3"},
        }
        ownership = {
            "14028507593": {"verdict": "LIKELY ROOT CAUSE", "confidence": 78, "owning_ip": "Core"},
            "21044871638": {"verdict": "WORKING HYPOTHESIS", "confidence": 35, "owning_ip": "Core"},
            "15019342741": {"verdict": "CONFIRMED ROOT CAUSE", "confidence": 90, "owning_ip": "Core"},
        }

        async def run():
            with patch.object(main, "_kerberos", return_value=True), \
                 patch.object(main, "analyze", new=AsyncMock(side_effect=lambda hsd_id, *args, **kwargs: analyze_results[hsd_id])), \
                 patch.object(main, "extract_ownership", side_effect=lambda result: next(value for key, value in ownership.items() if analyze_results[key] is result)), \
                 patch.object(main, "_save_report", return_value=("report.md", "report.html")), \
                 patch.object(main, "update_hsd_report", new=AsyncMock(side_effect=[
                     {"ok": True, "dry_run": True, "draft_only": True, "gate": {"allow": True}},
                     {"ok": True, "dry_run": True, "draft_only": True, "gate": {"allow": False}, "reason": "weak result"},
                     {"ok": True, "dry_run": False, "gate": {"allow": True}},
                 ])):
                response = await main.api_batch_analyze(
                    request,
                    main.BatchAnalyzeRequest(hsd_ids=list(analyze_results)),
                )
                lines = []
                async for line in response.body_iterator:
                    lines.append(json.loads(line))
                return lines

        lines = asyncio.run(run())
        completed = [line for line in lines if line["status"] in ("Done", "Failed")]
        self.assertEqual([line["hsd_id"] for line in completed], list(analyze_results))
        self.assertEqual([line["action"] for line in completed], ["Draft", "Draft", "Posted"])
        self.assertEqual(sum(line["status"] == "Analyzing" for line in lines), 3)

    def test_failed_id_is_streamed_with_reason(self):
        request = type("Request", (), {"session": {}})()

        async def run():
            with patch.object(main, "_kerberos", return_value=True), \
                 patch.object(main, "analyze", new=AsyncMock(side_effect=RuntimeError("HSDES unavailable"))):
                response = await main.api_batch_analyze(
                    request, main.BatchAnalyzeRequest(hsd_ids=["14028507593"])
                )
                return [json.loads(line) async for line in response.body_iterator]

        lines = asyncio.run(run())
        self.assertEqual(lines[-1]["status"], "Failed")
        self.assertIn("HSDES unavailable", lines[-1]["reason"])


if __name__ == "__main__":
    unittest.main(verbosity=2)