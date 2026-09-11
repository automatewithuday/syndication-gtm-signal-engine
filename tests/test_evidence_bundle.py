import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gtm_signal_engine.evidence_bundle import export_evidence_bundle


class EvidenceBundleTests(unittest.TestCase):
    def make_run(self, root: Path, status: str = "qualified") -> Path:
        run = root / "run"
        (run / "normalized").mkdir(parents=True)
        score = {
            "snapshot_id": "snap", "channel": "content_syndication", "scoring_version": "v1",
            "components": {}, "total": 82.0, "confidence": 0.8,
            "qualification": {"opportunity_status": status, "blockers": [] if status == "qualified" else ["gap"]},
        }
        review = {
            "account": {"name": "Example", "domain": "example.com"},
            "run": {"run_id": "run-1"}, "components": {},
            "overall": {"snapshot_id": "snap"}, "signals": {"gap": [{"url": "https://example.com/evidence"}]},
            "interpretation": "Evidence-bound.",
        }
        (run / "normalized/syndication_score.json").write_text(json.dumps(score))
        (run / "normalized/account_review.json").write_text(json.dumps(review))
        return run

    def test_exports_only_qualified_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "bundle.json"
            result = export_evidence_bundle(self.make_run(root), output)
            self.assertEqual("snap", result["snapshot_id"])
            self.assertEqual("https://example.com/evidence", json.loads(output.read_text())["evidence"]["gap"][0]["url"])

    def test_refuses_unqualified_account(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "requires a qualified account"):
                export_evidence_bundle(self.make_run(root, "insufficient_evidence"), root / "bundle.json")


if __name__ == "__main__":
    unittest.main()
