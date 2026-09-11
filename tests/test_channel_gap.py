import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gtm_signal_engine.channel_gap import score_channel_gap, score_channel_gap_run
from gtm_signal_engine.syndication_scoring import load_scoring_config


class ChannelGapTests(unittest.TestCase):
    def setUp(self):
        self.config, _, _ = load_scoring_config(ROOT / "config" / "content_syndication_scoring.v2.json")
        self.page = {
            "url": "https://example.com/marketing-plan",
            "text": "We are expanding content distribution and hiring a demand generation partner this quarter.",
            "main_text": "We are expanding content distribution and hiring a demand generation partner this quarter.",
            "observed_at": "2026-09-10T00:00:00+00:00",
            "content_hash": "a" * 64,
        }

    def observation(self, signal_type, excerpt, *, polarity="supports_gap", confidence=0.9):
        return {
            "signal_type": signal_type,
            "polarity": polarity,
            "strength": "confirmed",
            "confidence": confidence,
            "url": self.page["url"],
            "excerpt": excerpt,
            "observed_at": self.page["observed_at"],
            "method": "scrapling_saved_page",
            "content_sha256": self.page["content_hash"],
        }

    def profile(self, observations):
        return {
            "account": {"name": "Example", "domain": "example.com"},
            "channel": "content_syndication",
            "observations": observations,
        }

    def test_no_observation_stays_unknown(self):
        result = score_channel_gap(self.profile([]), {self.page["url"]: self.page}, self.config)
        self.assertIsNone(result["score"])
        self.assertEqual("insufficient_evidence", result["status"])

    def test_two_verified_positive_signal_types_can_provisionally_pass(self):
        observations = [
            self.observation("explicit_expansion_intent", "expanding content distribution"),
            self.observation("active_partner_or_hiring_search", "hiring a demand generation partner"),
        ]
        result = score_channel_gap(self.profile(observations), {self.page["url"]: self.page}, self.config)
        self.assertEqual(55.0, result["score"])
        self.assertEqual("provisional_pass", result["status"])

    def test_active_success_evidence_contradicts_gap(self):
        observation = self.observation(
            "documented_syndication_success",
            "expanding content distribution",
            polarity="contradicts_gap",
        )
        result = score_channel_gap(self.profile([observation]), {self.page["url"]: self.page}, self.config)
        self.assertEqual(0.0, result["score"])
        self.assertEqual("disqualified", result["status"])
        self.assertEqual("contradicted", result["state"])

    def test_excerpt_must_exist_in_saved_scrapling_page(self):
        observation = self.observation("explicit_expansion_intent", "words not on the page")
        with self.assertRaisesRegex(ValueError, "excerpt is not present"):
            score_channel_gap(self.profile([observation]), {self.page["url"]: self.page}, self.config)

    def test_signal_polarity_must_match_its_configured_meaning(self):
        observation = self.observation(
            "documented_syndication_success",
            "expanding content distribution",
            polarity="supports_gap",
        )
        with self.assertRaisesRegex(ValueError, "polarity does not match"):
            score_channel_gap(self.profile([observation]), {self.page["url"]: self.page}, self.config)

    def test_run_rejects_non_scrapling_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            (run_dir / "normalized").mkdir()
            (run_dir / "manifest.json").write_text(json.dumps({
                "provider": "OtherFetcher", "seed_url": "https://example.com/", "run_id": "run"
            }))
            (run_dir / "normalized" / "pages.jsonl").write_text(json.dumps(self.page) + "\n")
            profile_path = run_dir / "profile.json"
            profile_path.write_text(json.dumps(self.profile([])))
            with self.assertRaisesRegex(ValueError, "requires a ScraplingFetcher run"):
                score_channel_gap_run(run_dir, profile_path, ROOT / "config" / "content_syndication_scoring.v2.json")

    def test_run_rejects_profile_for_another_domain(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            (run_dir / "normalized").mkdir()
            (run_dir / "manifest.json").write_text(json.dumps({
                "provider": "ScraplingFetcher", "seed_url": "https://another.example/", "run_id": "run"
            }))
            (run_dir / "normalized" / "pages.jsonl").write_text(json.dumps(self.page) + "\n")
            profile_path = run_dir / "profile.json"
            profile_path.write_text(json.dumps(self.profile([])))
            with self.assertRaisesRegex(ValueError, "domain does not match"):
                score_channel_gap_run(run_dir, profile_path, ROOT / "config" / "content_syndication_scoring.v2.json")


if __name__ == "__main__":
    unittest.main()
