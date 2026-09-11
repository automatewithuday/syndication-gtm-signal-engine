import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gtm_signal_engine.engine import analyze_account


class EngineTests(unittest.TestCase):
    def test_example_produces_ranked_opportunities_and_evidence(self):
        payload = json.loads((ROOT / "examples" / "account.json").read_text())
        result = analyze_account(payload)
        self.assertEqual(4, len(result["opportunities"]))
        self.assertGreater(len(result["evidence"]), 0)
        self.assertEqual(1, result["metrics"]["gated_asset_count"])
        self.assertTrue(all(item["gap"] is None for item in result["opportunities"]))
        self.assertTrue(all(item["trigger"] is None for item in result["opportunities"]))
        self.assertTrue(all(item["total"] is None for item in result["opportunities"]))

    def test_only_approved_attributable_gap_evidence_scores(self):
        payload = json.loads((ROOT / "examples" / "account.json").read_text())
        payload["account"]["external_signals"]["gap_evidence"] = {
            "retargeting": [{
                "position": "supports_gap", "review_status": "approved", "confidence": 0.9,
                "url": "https://northstar.example/evidence", "excerpt": "We need to improve retargeting.",
            }]
        }
        result = analyze_account(payload)
        retargeting = next(item for item in result["opportunities"] if item["channel"] == "retargeting")
        self.assertEqual(90.0, retargeting["gap"])
        self.assertEqual("https://northstar.example/evidence", retargeting["evidence"][0]["url"])


if __name__ == "__main__":
    unittest.main()
