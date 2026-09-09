"""Source provenance and promotion-gate regressions."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.source_provenance import inventory_entry, quality_report  # noqa: E402


class TestSourceProvenance(unittest.TestCase):
    def test_inventory_marks_unknown_as_zero_trust(self):
        entry = inventory_entry("app/decoders/mca_codes_database.json")
        self.assertEqual(entry["trust"], "UNKNOWN")
        self.assertEqual(entry["score"], 0)

    def test_authoritative_bank_map_is_recorded(self):
        entry = inventory_entry("app/decoders/bank_mapping_cwf.json")
        self.assertEqual(entry["trust"], "AUTHORITATIVE")
        self.assertEqual(entry["score"], 100)
        self.assertNotEqual(entry["source_document"], "UNKNOWN")

    def test_all_json_resources_have_inventory_rows(self):
        report = quality_report(ROOT)
        self.assertEqual(report["missing_inventory"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
