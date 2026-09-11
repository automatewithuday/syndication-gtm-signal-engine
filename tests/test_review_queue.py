import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gtm_signal_engine.channel_gap import score_channel_gap
from gtm_signal_engine.review_queue import (
    export_gap_profile,
    ingest_gap_candidates,
    list_gap_candidates,
    review_gap_candidate,
)
from gtm_signal_engine.syndication_scoring import load_scoring_config


class ReviewQueueTests(unittest.TestCase):
    def make_run(self, directory):
        run_dir = Path(directory) / "run"
        normalized = run_dir / "normalized"
        normalized.mkdir(parents=True)
        page = {
            "url": "https://example.com/careers",
            "text": "We plan to expand content distribution this quarter.",
            "main_text": "We plan to expand content distribution this quarter.",
            "links": [],
            "content_hash": "d" * 64,
            "observed_at": "2026-09-11T00:00:00+00:00",
        }
        candidate = {
            "candidate_id": "candidate-1",
            "signal_type": "explicit_expansion_intent",
            "suggested_polarity": "supports_gap",
            "review_status": "pending",
            "url": page["url"],
            "excerpt": "We plan to expand content distribution this quarter.",
            "matched_text": "We plan to expand content distribution",
            "observed_at": page["observed_at"],
            "content_sha256": page["content_hash"],
            "source_date": {
                "value": "2026-09-01T00:00:00+00:00",
                "source": "meta.article:published_time",
                "confidence": 0.98
            },
            "method": "scrapling_saved_page_candidate",
            "extractor_version": "gap_candidate_rules_v1",
        }
        (run_dir / "manifest.json").write_text(json.dumps({
            "run_id": "review-run",
            "seed_url": "https://example.com/",
            "provider": "ScraplingFetcher",
        }))
        (normalized / "pages.jsonl").write_text(json.dumps(page) + "\n")
        (normalized / "gap_candidates.jsonl").write_text(json.dumps(candidate) + "\n")
        return run_dir, page

    def test_rejection_survives_reingestion(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _ = self.make_run(directory)
            database = Path(directory) / "review.sqlite3"
            first = ingest_gap_candidates(run_dir, database)
            self.assertEqual(1, first["inserted"])
            review_gap_candidate(
                "candidate-1", decision="reject", reviewer="qa@example.com",
                notes="Directory copy, not an account initiative.", database_path=database,
            )
            second = ingest_gap_candidates(run_dir, database)
            self.assertEqual(1, second["seen_again"])
            rows = list_gap_candidates(database)
            self.assertEqual("rejected", rows[0]["review_status"])

    def test_approval_exports_run_bound_scoreable_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir, page = self.make_run(directory)
            database = Path(directory) / "review.sqlite3"
            ingest_gap_candidates(run_dir, database)
            review_gap_candidate(
                "candidate-1", decision="approve", reviewer="qa@example.com",
                notes="First-person current expansion statement.", database_path=database,
                strength="confirmed", confidence=0.92,
            )
            result = export_gap_profile(
                run_dir, account_name="Example", database_path=database
            )
            profile = json.loads(Path(result["output"]).read_text())
            self.assertEqual(1, result["approved_observations"])
            self.assertEqual("scrapling_saved_page", profile["observations"][0]["method"])
            self.assertEqual("2026-09-01T00:00:00+00:00", profile["observations"][0]["source_date"]["value"])
            config, _, _ = load_scoring_config(ROOT / "config" / "content_syndication_scoring.v2.json")
            component = score_channel_gap(profile, {page["url"]: page}, config)
            self.assertEqual(35.0, component["score"])
            self.assertEqual("review", component["status"])

            later_run = Path(directory) / "later-run"
            shutil.copytree(run_dir, later_run)
            manifest = json.loads((later_run / "manifest.json").read_text())
            manifest["run_id"] = "review-run-later"
            (later_run / "manifest.json").write_text(json.dumps(manifest))
            later_page = json.loads((later_run / "normalized" / "pages.jsonl").read_text())
            later_page["content_hash"] = "e" * 64
            (later_run / "normalized" / "pages.jsonl").write_text(json.dumps(later_page) + "\n")
            later_candidate = json.loads((later_run / "normalized" / "gap_candidates.jsonl").read_text())
            later_candidate["content_sha256"] = "e" * 64
            (later_run / "normalized" / "gap_candidates.jsonl").write_text(json.dumps(later_candidate) + "\n")
            ingest_gap_candidates(later_run, database)
            self.assertEqual("pending", list_gap_candidates(database)[0]["review_status"])
            replay = export_gap_profile(run_dir, account_name="Example", database_path=database)
            self.assertEqual(1, replay["approved_observations"])

    def test_approval_requires_strength_and_confidence(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _ = self.make_run(directory)
            database = Path(directory) / "review.sqlite3"
            ingest_gap_candidates(run_dir, database)
            with self.assertRaisesRegex(ValueError, "require confirmed"):
                review_gap_candidate(
                    "candidate-1", decision="approve", reviewer="qa@example.com",
                    notes="Looks valid.", database_path=database,
                )


if __name__ == "__main__":
    unittest.main()
