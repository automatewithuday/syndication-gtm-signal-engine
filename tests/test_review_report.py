import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gtm_signal_engine.review_report import build_account_review


class ReviewReportTests(unittest.TestCase):
    def make_run(self, directory):
        run_dir = Path(directory)
        normalized = run_dir / "normalized"
        normalized.mkdir()
        pages_path = normalized / "pages.jsonl"
        pages_path.write_text(json.dumps({
            "url": "https://example.com/", "text": "Evidence", "main_text": "Evidence",
            "links": [], "content_hash": "a" * 64, "observed_at": "2026-09-11T00:00:00+00:00",
        }) + "\n")
        assets_path = normalized / "assets.jsonl"
        assets_path.write_text("{}\n")
        pages_hash = hashlib.sha256(pages_path.read_bytes()).hexdigest()
        assets_hash = hashlib.sha256(assets_path.read_bytes()).hexdigest()
        (run_dir / "manifest.json").write_text(json.dumps({
            "run_id": "review-run", "seed_url": "https://example.com/",
            "provider": "ScraplingFetcher", "status": "partial", "incomplete": True,
            "pages_collected": 1, "errors": [],
        }))
        (normalized / "classification_summary.json").write_text(json.dumps({
            "page_families": {"homepage": 1}, "asset_types": {}, "gating_types": {},
        }))
        (normalized / "asset_summary.json").write_text(json.dumps({
            "asset_count": 1, "dated_asset_count": 1, "freshness_windows": {"within_90_days": 1},
            "substantial": {"yes": 1}, "syndication_suitability": {"suitable": 1},
        }))
        (normalized / "account_fit.json").write_text(json.dumps({
            "input": {"pages_sha256": pages_hash}, "component": {"score": 80},
        }))
        (normalized / "channel_gap.json").write_text(json.dumps({
            "input": {"pages_sha256": pages_hash}, "component": {"score": None},
        }))
        components = {
            "fit": {"score": 80, "confidence": 0.9, "state": "observed", "status": "provisional_pass", "factors": [], "reasons": [], "risks": []},
            "readiness": {"score": 70, "state": "observed", "factors": [], "reasons": [], "risks": []},
            "gap": {"score": None, "confidence": 0, "state": "unknown", "status": "insufficient_evidence", "evidence": [], "reasons": [], "risks": []},
            "trigger": {"score": 30, "confidence": 0.7, "state": "possible", "status": "review", "reasons": [], "risks": []},
        }
        (normalized / "syndication_score.json").write_text(json.dumps({
            "input": {"run_id": "review-run", "assets_sha256": assets_hash},
            "components": components, "total": None, "confidence": 0.7,
            "qualification": {"opportunity_status": "insufficient_evidence", "blockers": ["gap"]},
            "scoring_version": "content_syndication_v2", "snapshot_id": "snapshot",
        }))
        return run_dir

    def test_builds_json_and_markdown_with_unknown_gap(self):
        with tempfile.TemporaryDirectory() as directory:
            result = build_account_review(self.make_run(directory), account_name="Example")
            self.assertTrue(Path(result["json"]).exists())
            self.assertTrue(Path(result["markdown"]).exists())
            self.assertIsNone(result["report"]["components"]["gap"]["score"])
            self.assertIn("null weighted total", result["report"]["interpretation"])
            markdown = Path(result["markdown"]).read_text(encoding="utf-8")
            self.assertIn("## Fit evidence", markdown)
            self.assertIn("## Reviewed initiative evidence", markdown)

    def test_rejects_stale_fit_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self.make_run(directory)
            fit_path = run_dir / "normalized" / "account_fit.json"
            fit = json.loads(fit_path.read_text())
            fit["input"]["pages_sha256"] = "stale"
            fit_path.write_text(json.dumps(fit))
            with self.assertRaisesRegex(ValueError, "fit score does not match"):
                build_account_review(run_dir, account_name="Example")


if __name__ == "__main__":
    unittest.main()
