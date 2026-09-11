import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gtm_signal_engine.external_signals import normalize_apify_ads, normalize_deepline_technologies
from gtm_signal_engine.paid_channel_scoring import score_paid_channel_run, score_paid_channels


class PaidChannelScoringTests(unittest.TestCase):
    def setUp(self):
        ads_payload = json.loads((ROOT / "tests/fixtures/providers/apify_ads.json").read_text())
        tech_payload = json.loads((ROOT / "tests/fixtures/providers/deepline_technologies.json").read_text())
        self.profile = {
            "ads": [item.to_dict() for item in normalize_apify_ads(ads_payload, observed_at="2026-09-11T00:00:00+00:00")],
            "technologies": [item.to_dict() for item in normalize_deepline_technologies(tech_payload, observed_at="2026-09-11T00:00:00+00:00")],
            "gap_observations": [],
        }
        self.summary = {"substantial": {"yes": 20}, "asset_types": {"case_study": 10, "guide": 10}}
        self.config = json.loads((ROOT / "config/paid_channel_scoring.v2.json").read_text())

    def test_scores_readiness_but_keeps_unobserved_gap_unknown(self):
        result = score_paid_channels(self.profile, self.summary, self.config)
        self.assertGreater(result["channels"]["retargeting"]["readiness"]["score"], 0)
        self.assertIsNone(result["channels"]["retargeting"]["gap"]["score"])
        self.assertEqual("insufficient_evidence", result["channels"]["programmatic"]["gap"]["status"])

    def test_only_approved_positive_gap_evidence_scores(self):
        self.profile["gap_observations"] = [{
            "channel": "retargeting", "position": "supports_gap", "url": "https://example.com/source",
            "excerpt": "We need to improve retargeting.", "observed_at": "2026-09-11T00:00:00+00:00",
            "confidence": 0.9, "review_status": "approved",
        }]
        result = score_paid_channels(self.profile, self.summary, self.config)
        self.assertEqual(90.0, result["channels"]["retargeting"]["gap"]["score"])

    def test_irrelevant_infrastructure_does_not_count_as_paid_technology(self):
        self.profile["technologies"] = [{
            "technology": "Example CDN", "category": "cdn", "state": "detected", "confidence": 0.9,
        }]
        result = score_paid_channels(self.profile, self.summary, self.config)
        self.assertEqual(0, result["metrics"]["relevant_technology_detections"]["retargeting"])
        self.assertEqual(0, result["metrics"]["relevant_technology_detections"]["programmatic"])
        retargeting_factor = next(
            item for item in result["channels"]["retargeting"]["readiness"]["factors"]
            if item["id"] == "observable_technology"
        )
        self.assertEqual(0.0, retargeting_factor["points"])

    def test_channel_specific_category_markers_select_relevant_technology(self):
        self.profile["technologies"] = [{
            "technology": "Example DSP", "category": "Demand-side Platform", "state": "detected",
            "confidence": 0.9,
        }]
        result = score_paid_channels(self.profile, self.summary, self.config)
        self.assertEqual(0, result["metrics"]["relevant_technology_detections"]["retargeting"])
        self.assertEqual(1, result["metrics"]["relevant_technology_detections"]["programmatic"])

    def test_run_persists_versioned_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            (run_dir / "normalized").mkdir()
            (run_dir / "normalized/asset_summary.json").write_text(json.dumps(self.summary))
            profile = run_dir / "external.json"
            profile.write_text(json.dumps(self.profile))
            result = score_paid_channel_run(run_dir, profile, ROOT / "config/paid_channel_scoring.v2.json")
            self.assertEqual("paid_channels_v2", result["scoring_version"])
            self.assertTrue((run_dir / "normalized/paid_channel_scores.json").exists())

    def test_installed_share_directory_is_a_default_config_fallback(self):
        from gtm_signal_engine import paid_channel_scoring

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            share = root / "share/gtm-signal-engine"
            share.mkdir(parents=True)
            expected = share / "paid_channel_scoring.v2.json"
            expected.write_bytes((ROOT / "config/paid_channel_scoring.v2.json").read_bytes())
            with patch.object(paid_channel_scoring.Path, "cwd", return_value=root / "elsewhere"), \
                 patch.object(paid_channel_scoring, "DEFAULT_CONFIG_PATH", root / "missing.json"), \
                 patch.object(paid_channel_scoring.sys, "prefix", str(root)):
                self.assertEqual(expected, paid_channel_scoring._default_config())


if __name__ == "__main__":
    unittest.main()
