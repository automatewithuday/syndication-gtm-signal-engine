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
        self.v3_config = json.loads((ROOT / "config/paid_channel_scoring.v3.json").read_text())
        self.creative_analysis = {
            "analysis_version": "ad_creative_analysis_v1",
            "scoring_inputs": {
                "provider_total_ads": 250,
                "observed_platform_diversity": 3,
                "ads_inspected": 30,
                "analyzable_ads": 20,
                "creative_format_diversity": 4,
                "messaging_theme_diversity": 5,
            },
            "platforms": {
                "linkedin": {
                    "provider_status": "partial", "ads_inspected": 10,
                    "sample_confidence": "medium",
                    "creative_activity_states": {"unknown": 10},
                    "funnel_stages": {"awareness": 8, "consideration": 2},
                },
                "meta": {
                    "provider_status": "partial", "ads_inspected": 10,
                    "sample_confidence": "high",
                    "creative_activity_states": {"active": 10},
                    "funnel_stages": {"awareness": 4, "consideration": 6},
                },
                "google": {
                    "provider_status": "partial", "ads_inspected": 10,
                    "sample_confidence": "medium",
                    "creative_activity_states": {"recently_observed": 10},
                    "funnel_stages": {},
                },
            },
        }

    def test_scores_readiness_but_keeps_unobserved_gap_unknown(self):
        result = score_paid_channels(self.profile, self.summary, self.config)
        self.assertGreater(result["channels"]["retargeting"]["readiness"]["score"], 0)
        self.assertIsNone(result["channels"]["retargeting"]["gap"]["score"])
        self.assertEqual("insufficient_evidence", result["channels"]["programmatic"]["gap"]["status"])

    def test_ad_without_destination_counts_as_activity_but_not_tracking(self):
        undirected = dict(self.profile["ads"][0])
        undirected["provider_record_id"] = "ad-without-destination"
        undirected["destination"] = None
        self.profile["ads"] = [undirected]
        result = score_paid_channels(self.profile, self.summary, self.config)
        self.assertEqual(1, result["metrics"]["ads"])
        self.assertEqual(0, result["metrics"]["tracked_destinations"])

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

    def test_v3_scores_creative_inputs_and_traces_factor_sources(self):
        result = score_paid_channels(
            self.profile, self.summary, self.v3_config, self.creative_analysis
        )
        factors = {
            item["id"]: item
            for item in result["channels"]["programmatic"]["readiness"]["factors"]
        }
        self.assertEqual(250, factors["ad_inventory"]["observed"])
        self.assertEqual(15.0, factors["ad_inventory"]["points"])
        self.assertEqual("normalized/ad_creative_analysis.json", factors["ad_inventory"]["source"])
        self.assertEqual(20, factors["current_or_recent_creatives"]["observed"])
        self.assertEqual("observed", factors["tracked_destinations"]["state"])
        self.assertGreaterEqual(
            result["channels"]["programmatic"]["readiness"]["evidence_coverage"], 0.75
        )

    def test_v3_keeps_missing_creative_factors_unknown_instead_of_zero(self):
        result = score_paid_channels(self.profile, self.summary, self.v3_config)
        factors = result["channels"]["retargeting"]["readiness"]["factors"]
        inventory = next(item for item in factors if item["id"] == "ad_inventory")
        self.assertEqual("unknown", inventory["state"])
        self.assertIsNone(inventory["observed"])
        self.assertIsNone(inventory["points"])
        self.assertEqual("review", result["channels"]["retargeting"]["readiness"]["status"])

    def test_v3_does_not_convert_mixed_historical_and_unknown_activity_to_zero(self):
        analysis = json.loads(json.dumps(self.creative_analysis))
        analysis["platforms"]["meta"]["creative_activity_states"] = {"unknown": 10}
        analysis["platforms"]["google"]["creative_activity_states"] = {"historical": 10}
        result = score_paid_channels(self.profile, self.summary, self.v3_config, analysis)
        factor = next(
            item for item in result["channels"]["retargeting"]["readiness"]["factors"]
            if item["id"] == "current_or_recent_creatives"
        )
        self.assertEqual("unknown", factor["state"])
        self.assertIsNone(factor["points"])

    def test_v3_keeps_missing_destinations_unknown_for_partial_samples(self):
        profile = json.loads(json.dumps(self.profile))
        for ad in profile["ads"]:
            ad["destination"] = None
        result = score_paid_channels(profile, self.summary, self.v3_config, self.creative_analysis)
        factor = next(
            item for item in result["channels"]["retargeting"]["readiness"]["factors"]
            if item["id"] == "tracked_destinations"
        )
        self.assertEqual("unknown", factor["state"])
        self.assertIsNone(factor["points"])

    def test_v3_run_snapshots_creative_analysis(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            (run_dir / "normalized").mkdir()
            (run_dir / "normalized/asset_summary.json").write_text(json.dumps(self.summary))
            (run_dir / "normalized/ad_creative_analysis.json").write_text(
                json.dumps(self.creative_analysis)
            )
            profile = run_dir / "normalized/external_profile.json"
            profile.write_text(json.dumps(self.profile))
            result = score_paid_channel_run(
                run_dir, profile, ROOT / "config/paid_channel_scoring.v3.json"
            )
            self.assertEqual("paid_channels_v3", result["scoring_version"])
            self.assertIsNotNone(result["input"]["creative_analysis_sha256"])

    def _paid_gap(self, signal_type, *, position="supports_gap", confidence=0.9):
        return {
            "channel": "retargeting", "position": position,
            "signal_type": signal_type, "strength": "confirmed",
            "url": "https://example.com/source", "excerpt": "Explicit channel claim.",
            "observed_at": "2026-09-11T00:00:00+00:00", "confidence": confidence,
            "review_status": "approved", "method": "scrapling_saved_page",
            "content_sha256": "a" * 64,
        }

    def test_v3_requires_two_distinct_supporting_gap_signal_types(self):
        profile = json.loads(json.dumps(self.profile))
        profile["gap_observations"] = [self._paid_gap("explicit_expansion_intent")]
        result = score_paid_channels(profile, self.summary, self.v3_config, self.creative_analysis)
        gap = result["channels"]["retargeting"]["gap"]
        self.assertEqual("review", gap["status"])
        self.assertEqual(31.5, gap["score"])

        profile["gap_observations"].append(self._paid_gap("documented_distribution_bottleneck"))
        result = score_paid_channels(profile, self.summary, self.v3_config, self.creative_analysis)
        self.assertEqual("provisional_pass", result["channels"]["retargeting"]["gap"]["status"])

    def test_v3_approved_contradiction_disqualifies_gap(self):
        profile = json.loads(json.dumps(self.profile))
        profile["gap_observations"] = [self._paid_gap(
            "documented_channel_success", position="contradicts_gap"
        )]
        result = score_paid_channels(profile, self.summary, self.v3_config, self.creative_analysis)
        gap = result["channels"]["retargeting"]["gap"]
        self.assertEqual("disqualified", gap["status"])
        self.assertEqual(0.0, gap["score"])

    def test_installed_share_directory_is_a_default_config_fallback(self):
        from gtm_signal_engine import paid_channel_scoring

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            share = root / "share/gtm-signal-engine"
            share.mkdir(parents=True)
            expected = share / "paid_channel_scoring.v3.json"
            expected.write_bytes((ROOT / "config/paid_channel_scoring.v3.json").read_bytes())
            with patch.object(paid_channel_scoring.Path, "cwd", return_value=root / "elsewhere"), \
                 patch.object(paid_channel_scoring, "DEFAULT_CONFIG_PATH", root / "missing.json"), \
                 patch.object(paid_channel_scoring.sys, "prefix", str(root)):
                self.assertEqual(expected, paid_channel_scoring._default_config())


if __name__ == "__main__":
    unittest.main()
