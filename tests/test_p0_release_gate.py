"""P0 production-gate regressions: ambiguity, socket provenance, and banks."""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DECODERS = ROOT / "app" / "decoders"
if str(DECODERS) not in sys.path:
    sys.path.insert(0, str(DECODERS))

from app.decoders import mca_supplement  # noqa: E402
from app.decoders.mca_decoder import MCADecoder  # noqa: E402
from app.log_triage import _extract_evidence  # noqa: E402


class TestDecoderAmbiguity(unittest.TestCase):
    def test_known_0402_4a00_is_explicitly_ambiguous(self):
        result = mca_supplement.decoder_ambiguity(0x0402, 0x4A00, "CCF", "CWF")
        self.assertIsNotNone(result)
        self.assertEqual(result["state"], "AMBIGUOUS_DECODER")
        self.assertEqual(
            result["candidates"],
            ["SAD_NON_CORRUPTING_ERR_OTHER", "ADDR_PARITY_ERROR", "TOR_TIMEOUT"],
        )

    def test_unrelated_code_is_not_marked_ambiguous(self):
        self.assertIsNone(mca_supplement.decoder_ambiguity(0x0412, 0x25, "UPI", "GNR"))


class TestSocketAndBanks(unittest.TestCase):
    def test_socket_provenance_preserves_socket_one_without_default_zero(self):
        text = "reported Socket 1\nIERR source=PUNIT socket 1\n"
        evidence = _extract_evidence(text, [], [], None,
                                     [{"socket": "1", "source_unit": "PUNIT"}], "CWF")
        provenance = evidence["socket_provenance"]
        self.assertEqual(provenance["ticket_socket"], "1")
        self.assertEqual(provenance["first_ierr_socket"], "1")
        self.assertEqual(provenance["resolved_socket"], "1")
        self.assertNotEqual(provenance["resolved_socket"], "0")

    def test_two_banks_are_preserved_in_normalized_evidence(self):
        text = "\n".join([
            "Bank 4: BA0000004A000402",
            "Bank 6: BA00000C4A000402",
        ])
        decoder = MCADecoder()
        records = decoder.parse_log(text)
        self.assertEqual({r["bank"] for r in records}, {4, 6})
        evidence = _extract_evidence(text, records, [], None, [], "CWF")
        self.assertEqual(evidence["mca_banks"], ["4", "6"])
        self.assertEqual({r["bank"] for r in evidence["mca_records"]}, {"4", "6"})


class TestGoldenFixture(unittest.TestCase):
    def test_16031734105_fixture_is_p0_case(self):
        path = ROOT / "golden_cases" / "CWF" / "16031734105.json"
        self.assertTrue(path.exists())
        case = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(case["hsd_id"], "16031734105")
        self.assertTrue(case["expected_contradiction"])
        self.assertEqual(case["expected_socket"], "1")
        self.assertEqual(case["expected_banks"], ["4", "6"])
        self.assertEqual(case["expected_decoder_state"], "AMBIGUOUS_DECODER")


if __name__ == "__main__":
    unittest.main(verbosity=2)
