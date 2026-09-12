import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gtm_signal_engine.paid_gap import discover_paid_gap_candidates
from gtm_signal_engine.paid_gap_review import (
    export_paid_gap_profile,
    ingest_paid_gap_candidates,
    review_paid_gap_candidate,
)


class PaidGapTests(unittest.TestCase):
    def make_run(self, directory: str) -> Path:
        run_dir = Path(directory)
        normalized = run_dir / "normalized"
        normalized.mkdir()
        (run_dir / "manifest.json").write_text(json.dumps({
            "run_id": "paid-gap-run", "seed_url": "https://example.com/",
            "provider": "ScraplingFetcher",
        }))
        text = (
            "We plan to expand retargeting to re-engage more site visitors. "
            "Our current manual retargeting workflow is a bottleneck."
        )
        (normalized / "pages.jsonl").write_text(json.dumps({
            "url": "https://example.com/news/growth", "text": text, "main_text": text,
            "links": [], "content_hash": "a" * 64,
            "observed_at": "2026-09-12T00:00:00+00:00",
        }) + "\n")
        (normalized / "external_profile.json").write_text(json.dumps({
            "schema_version": "1.0", "domain": "example.com", "technologies": [],
            "ads": [], "gap_observations": [],
        }))
        return run_dir

    def test_discover_review_and_export_exact_saved_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self.make_run(directory)
            database = run_dir / "review.sqlite3"
            summary = discover_paid_gap_candidates(run_dir)
            self.assertEqual(2, summary["candidate_count"])
            ingest_paid_gap_candidates(run_dir, database)
            candidates = [
                json.loads(line) for line in
                (run_dir / "normalized/paid_gap_candidates.jsonl").read_text().splitlines()
            ]
            for candidate in candidates:
                review_paid_gap_candidate(
                    candidate["candidate_id"], decision="approve", reviewer="tester",
                    notes="claim and channel are explicit", strength="confirmed", confidence=0.9,
                    database_path=database,
                )
            result = export_paid_gap_profile(
                run_dir, account_name="Example", database_path=database
            )
            self.assertEqual(2, result["approved_observations"])
            profile = json.loads((run_dir / "normalized/external_profile.json").read_text())
            self.assertEqual(2, len(profile["gap_observations"]))
            self.assertTrue(all(item["method"] == "scrapling_saved_page" for item in profile["gap_observations"]))

    def test_absence_stays_no_candidates_not_negative_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self.make_run(directory)
            (run_dir / "normalized/pages.jsonl").write_text(json.dumps({
                "url": "https://example.com/", "text": "Welcome", "main_text": "Welcome",
                "links": [], "content_hash": "b" * 64,
                "observed_at": "2026-09-12T00:00:00+00:00",
            }) + "\n")
            summary = discover_paid_gap_candidates(run_dir)
            self.assertEqual(0, summary["candidate_count"])
            self.assertEqual("no_candidates", summary["review_status"])


if __name__ == "__main__":
    unittest.main()
