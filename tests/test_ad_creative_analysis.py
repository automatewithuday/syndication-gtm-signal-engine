import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gtm_signal_engine.ad_creative_analysis import analyze_ad_creatives, classify_creative


CONFIG = json.loads((ROOT / "config/ad_creative_analysis.v1.json").read_text())


class AdCreativeAnalysisTests(unittest.TestCase):
    def _run_dir(self, root: Path) -> Path:
        run_dir = root / "run"
        (run_dir / "normalized").mkdir(parents=True)
        (run_dir / "raw").mkdir()
        return run_dir

    def _write_account(self, run_dir: Path) -> None:
        linkedin_envelope = {
            "toolResponse": {"rawV2": {
                "total_ads": 318,
                "continuation_token": "next-page",
                "is_last_page": False,
                "ads": [{
                    "ad_id": "li-1",
                    "creative_type": "SPONSORED_VIDEO",
                    "type": "video",
                    "advertiser": {"name": "Example"},
                    "commentary": {"text": "HR leaders can simplify payroll and improve employee retention."},
                    "headline": {"title": "See the guide", "description": "Promoted"},
                    "image": {"url": "https://images.example/creative.jpg"},
                    "view_details_link": "https://www.linkedin.com/ad-library/detail/li-1",
                    "destinationUrl": None,
                }],
            }},
        }
        google_envelope = {
            "toolResponse": {"rawV2": {
                "total_ad_count": 44,
                "ads": [{
                    "creative_id": "g-1", "advertiser_name": "Example LLC",
                    "format": "Video", "variants": [{"content": "[REDACTED]"}],
                    "original_url": "https://adstransparency.google.com/creative/g-1",
                }],
            }},
        }
        linkedin_bytes = json.dumps(linkedin_envelope).encode()
        google_bytes = json.dumps(google_envelope).encode()
        (run_dir / "raw/linkedin.json").write_bytes(linkedin_bytes)
        (run_dir / "raw/google.json").write_bytes(google_bytes)

        import hashlib
        status = {
            "domain": "example.com",
            "platforms": {
                "linkedin": {
                    "status": "partial", "incomplete": True,
                    "provider_total_records": 318, "returned_records": 1,
                    "raw": {"response": "raw/linkedin.json"},
                    "sha256": {"response": hashlib.sha256(linkedin_bytes).hexdigest()},
                },
                "google": {
                    "status": "partial", "incomplete": True,
                    "provider_total_records": 44, "returned_records": 1,
                    "raw": {"response": "raw/google.json"},
                    "sha256": {"response": hashlib.sha256(google_bytes).hexdigest()},
                },
                "meta": {"status": "inconclusive", "incomplete": True},
            },
        }
        profile = {
            "domain": "example.com", "technologies": [], "gap_observations": [],
            "ads": [
                {
                    "platform": "linkedin", "provider_record_id": "li-1",
                    "creative_text": "HR leaders can simplify payroll and improve employee retention. See the guide",
                    "destination": None,
                    "source_url": "https://www.linkedin.com/ad-library/detail/li-1",
                    "first_seen_at": None, "last_seen_at": None,
                    "observed_at": "2026-09-12T00:00:00+00:00", "confidence": 0.9,
                    "method": "deepline_adyntel_linkedin_v1",
                    "normalizer_version": "adyntel_ads_normalizer_v1",
                },
                {
                    "platform": "google", "provider_record_id": "g-1",
                    "creative_text": "[REDACTED]", "destination": None,
                    "source_url": "https://adstransparency.google.com/creative/g-1",
                    "first_seen_at": "2026-01-01", "last_seen_at": "2026-09-01",
                    "observed_at": "2026-09-12T00:00:00+00:00", "confidence": 0.9,
                    "method": "deepline_adyntel_google_v1",
                    "normalizer_version": "adyntel_ads_normalizer_v1",
                },
                {
                    "platform": "meta", "provider_record_id": "fallback-1",
                    "creative_text": "Apify fallback", "destination": None,
                    "source_url": "https://facebook.com/ads/library?id=fallback-1",
                    "observed_at": "2026-09-12T00:00:00+00:00", "confidence": 0.8,
                    "method": "apify_recorded_payload",
                },
            ],
        }
        (run_dir / "normalized/adyntel_collection.json").write_text(json.dumps(status))
        (run_dir / "normalized/external_profile.json").write_text(json.dumps(profile))

    def test_classifies_funnel_offer_audience_and_theme_from_evidence(self):
        result = classify_creative(
            "HR leaders can simplify payroll and improve employee retention. See the guide",
            CONFIG,
        )
        self.assertEqual("usable", result["text_quality"])
        self.assertEqual("consideration", result["funnel_stage"]["label"])
        self.assertIn("guide_or_report", [item["label"] for item in result["offer_types"]])
        self.assertIn("hr_and_people", [item["label"] for item in result["audiences"]])
        self.assertIn("employee_retention_and_productivity", [
            item["label"] for item in result["messaging_themes"]
        ])
        self.assertTrue(result["funnel_stage"]["matched_patterns"])

    def test_redacted_text_remains_unknown(self):
        result = classify_creative("[REDACTED]", CONFIG)
        self.assertEqual("redacted", result["text_quality"])
        self.assertEqual("unknown", result["funnel_stage"]["label"])
        self.assertEqual([], result["messaging_themes"])

    def test_analyzes_saved_raw_records_and_preserves_partial_coverage(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = self._run_dir(Path(temporary))
            self._write_account(run_dir)
            result = analyze_ad_creatives(run_dir, ROOT / "config/ad_creative_analysis.v1.json")

            self.assertEqual(2, len(result["creatives"]))
            self.assertEqual(318, result["platforms"]["linkedin"]["provider_total_ads"])
            self.assertEqual(1, result["platforms"]["linkedin"]["ads_inspected"])
            self.assertEqual(0.31, result["platforms"]["linkedin"]["sample_coverage_percent"])
            self.assertEqual("low", result["platforms"]["linkedin"]["sample_confidence"])
            self.assertEqual("very_high", result["platforms"]["linkedin"]["inventory_level"])
            self.assertEqual("redacted", result["creatives"][1]["classification"]["text_quality"])
            self.assertEqual("recently_observed", result["creatives"][1]["creative_activity"]["state"])
            self.assertEqual(["video"], result["creatives"][0]["creative_formats"])
            self.assertEqual("not_performed", result["creatives"][0]["visual_analysis"]["status"])
            self.assertEqual(["google", "linkedin"], result["scoring_inputs"]["observed_ad_platforms"])
            self.assertEqual("unknown", result["platforms"]["meta"]["inventory_level"])
            self.assertTrue((run_dir / "normalized/ad_creative_analysis.json").is_file())

    def test_rejects_changed_raw_payload(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = self._run_dir(Path(temporary))
            self._write_account(run_dir)
            (run_dir / "raw/linkedin.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "hash does not match"):
                analyze_ad_creatives(run_dir, ROOT / "config/ad_creative_analysis.v1.json")


if __name__ == "__main__":
    unittest.main()
