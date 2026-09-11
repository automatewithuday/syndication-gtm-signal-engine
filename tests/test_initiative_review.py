import json
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gtm_signal_engine.initiative_review import (
    export_trigger_profile,
    ingest_initiative_candidates,
    list_initiative_candidates,
    review_initiative_candidate,
)
from gtm_signal_engine.syndication_scoring import load_scoring_config
from gtm_signal_engine.trigger_scoring import score_business_trigger, score_business_trigger_run


class InitiativeReviewTests(unittest.TestCase):
    def make_run(self, directory, *, source_date=True):
        run_dir = Path(directory) / "run"
        normalized = run_dir / "normalized"
        normalized.mkdir(parents=True)
        text = "We launched Project Reach, a campaign for finance leaders."
        page = {
            "url": "https://example.com/press/project-reach",
            "text": text,
            "main_text": text,
            "links": [],
            "content_hash": "f" * 64,
            "observed_at": "2026-09-11T00:00:00+00:00",
        }
        candidate = {
            "candidate_id": "initiative-1",
            "signal_type": "public_campaign_launch",
            "trigger_relevance": "direct",
            "review_status": "pending",
            "url": page["url"],
            "excerpt": text,
            "matched_text": "launched Project Reach, a campaign",
            "observed_at": page["observed_at"],
            "content_sha256": page["content_hash"],
            "source_date": ({
                "value": "2026-09-01T00:00:00+00:00",
                "source": "meta.article:published_time",
                "confidence": 0.98,
            } if source_date else None),
            "method": "scrapling_saved_page_candidate",
            "extractor_version": "initiative_candidate_rules_v2",
        }
        (run_dir / "manifest.json").write_text(json.dumps({
            "run_id": "initiative-run",
            "seed_url": "https://example.com/",
            "provider": "ScraplingFetcher",
        }))
        (normalized / "pages.jsonl").write_text(json.dumps(page) + "\n")
        (normalized / "initiative_candidates.jsonl").write_text(json.dumps(candidate) + "\n")
        return run_dir, page

    def test_approval_exports_source_date_and_scores_reviewed_trigger(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _ = self.make_run(directory)
            database = Path(directory) / "review.sqlite3"
            self.assertEqual(1, ingest_initiative_candidates(run_dir, database)["inserted"])
            review_initiative_candidate(
                "initiative-1", decision="approve", reviewer="qa@example.com",
                notes="Current first-party campaign launch.", database_path=database,
                strength="confirmed", confidence=0.92,
            )
            exported = export_trigger_profile(
                run_dir, account_name="Example", database_path=database
            )
            profile = json.loads(Path(exported["output"]).read_text())
            self.assertEqual("2026-09-01T00:00:00+00:00", profile["observations"][0]["source_date"]["value"])
            result = score_business_trigger_run(
                run_dir, Path(exported["output"]), as_of=date(2026, 9, 11)
            )
            self.assertEqual(70.0, result["component"]["score"])
            self.assertEqual("provisional_pass", result["component"]["status"])
            self.assertEqual(10, result["component"]["factors"][0]["age_days"])

    def test_rejection_survives_reingestion(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _ = self.make_run(directory)
            database = Path(directory) / "review.sqlite3"
            ingest_initiative_candidates(run_dir, database)
            review_initiative_candidate(
                "initiative-1", decision="reject", reviewer="qa@example.com",
                notes="Not a material initiative.", database_path=database,
            )
            ingest_initiative_candidates(run_dir, database)
            self.assertEqual("rejected", list_initiative_candidates(database)[0]["review_status"])

    def test_approval_is_bound_to_exact_run_content(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _ = self.make_run(directory)
            database = Path(directory) / "review.sqlite3"
            ingest_initiative_candidates(run_dir, database)
            review_initiative_candidate(
                "initiative-1", decision="approve", reviewer="qa@example.com",
                notes="Verified current launch.", database_path=database,
                strength="confirmed", confidence=0.9,
            )
            later_run = Path(directory) / "later-run"
            shutil.copytree(run_dir, later_run)
            manifest = json.loads((later_run / "manifest.json").read_text())
            manifest["run_id"] = "initiative-run-later"
            (later_run / "manifest.json").write_text(json.dumps(manifest))
            page = json.loads((later_run / "normalized" / "pages.jsonl").read_text())
            page["content_hash"] = "e" * 64
            (later_run / "normalized" / "pages.jsonl").write_text(json.dumps(page) + "\n")
            candidate = json.loads((later_run / "normalized" / "initiative_candidates.jsonl").read_text())
            candidate["content_sha256"] = "e" * 64
            (later_run / "normalized" / "initiative_candidates.jsonl").write_text(json.dumps(candidate) + "\n")
            ingest_initiative_candidates(later_run, database)
            self.assertEqual("pending", list_initiative_candidates(database)[0]["review_status"])
            later = export_trigger_profile(later_run, account_name="Example", database_path=database)
            self.assertEqual(0, later["approved_observations"])
            original = export_trigger_profile(run_dir, account_name="Example", database_path=database)
            self.assertEqual(1, original["approved_observations"])

    def test_unknown_date_caps_freshness_and_confidence(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir, page = self.make_run(directory, source_date=False)
            profile = {
                "account": {"name": "Example", "domain": "example.com"},
                "kind": "business_trigger",
                "observations": [{
                    "signal_type": "new_channel_or_team_launch",
                    "trigger_relevance": "adjacent",
                    "strength": "confirmed",
                    "confidence": 0.95,
                    "url": page["url"],
                    "excerpt": page["text"],
                    "observed_at": page["observed_at"],
                    "method": "scrapling_saved_page",
                    "content_sha256": page["content_hash"],
                }],
            }
            config, _, _ = load_scoring_config()
            component = score_business_trigger(profile, {page["url"]: page}, config, as_of=date(2026, 9, 11))
            self.assertEqual(40.0, component["score"])
            self.assertEqual(0.65, component["confidence"])
            self.assertEqual("review", component["status"])

    def test_tampered_excerpt_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir, page = self.make_run(directory)
            profile = {
                "account": {"name": "Example", "domain": "example.com"},
                "kind": "business_trigger",
                "observations": [{
                    "signal_type": "public_campaign_launch", "trigger_relevance": "direct",
                    "strength": "confirmed", "confidence": 0.9, "url": page["url"],
                    "excerpt": "Invented launch claim", "observed_at": page["observed_at"],
                    "method": "scrapling_saved_page", "content_sha256": page["content_hash"],
                }],
            }
            config, _, _ = load_scoring_config()
            with self.assertRaisesRegex(ValueError, "excerpt is not present"):
                score_business_trigger(profile, {page["url"]: page}, config, as_of=date(2026, 9, 11))

    def test_future_source_date_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            _, page = self.make_run(directory)
            profile = {
                "account": {"name": "Example", "domain": "example.com"},
                "kind": "business_trigger",
                "observations": [{
                    "signal_type": "public_campaign_launch", "trigger_relevance": "direct",
                    "strength": "confirmed", "confidence": 0.9, "url": page["url"],
                    "excerpt": page["text"], "observed_at": page["observed_at"],
                    "method": "scrapling_saved_page", "content_sha256": page["content_hash"],
                    "source_date": {
                        "value": "2026-09-12T00:00:00+00:00", "source": "meta.article:published_time",
                        "confidence": 0.98,
                    },
                }],
            }
            config, _, _ = load_scoring_config()
            with self.assertRaisesRegex(ValueError, "after the scoring as_of"):
                score_business_trigger(profile, {page["url"]: page}, config, as_of=date(2026, 9, 11))


if __name__ == "__main__":
    unittest.main()
