import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gtm_signal_engine.external_signals import (
    RecordedApifyAdvertisingAdapter,
    RecordedDeeplineEnrichmentAdapter,
    RecordedScraplingSearchAdapter,
    normalize_apify_ads,
    normalize_deepline_technologies,
    parse_campaign_url,
    normalize_scrapling_serp_results,
)


class ExternalSignalTests(unittest.TestCase):
    def test_campaign_url_preserves_observed_and_extracts_tracking(self):
        parsed = parse_campaign_url(
            "https://Example.com/offer/?utm_source=LinkedIn&utm_campaign=q3&li_fat_id=abc#form"
        )
        self.assertEqual(
            "https://Example.com/offer/?utm_source=LinkedIn&utm_campaign=q3&li_fat_id=abc#form",
            parsed.observed_url,
        )
        self.assertEqual("https://example.com/offer", parsed.canonical_url)
        self.assertEqual({"utm_campaign": "q3", "utm_source": "LinkedIn"}, parsed.utm_parameters)
        self.assertEqual({"li_fat_id": "abc"}, parsed.click_identifiers)

    def test_apify_fixture_normalizes_without_raw_provider_shape(self):
        payload = json.loads((ROOT / "tests/fixtures/providers/apify_ads.json").read_text())
        result = normalize_apify_ads(payload, observed_at="2026-09-11T00:00:00+00:00")
        normalized = result[0].to_dict()
        self.assertEqual("linkedin", normalized["platform"])
        self.assertEqual("https://example.com/guides/ops", normalized["destination"]["canonical_url"])
        self.assertNotIn("ad_archive_id", normalized)
        self.assertEqual("apify_recorded_payload", normalized["method"])

    def test_deepline_fixture_retains_detection_limitation(self):
        payload = json.loads((ROOT / "tests/fixtures/providers/deepline_technologies.json").read_text())
        result = normalize_deepline_technologies(payload, observed_at="2026-09-11T00:00:00+00:00")
        normalized = result[0].to_dict()
        self.assertEqual("tag_management", normalized["category"])
        self.assertTrue(normalized["limitations"])
        self.assertEqual("deepline_recorded_payload", normalized["method"])

    def test_saved_scrapling_serp_preserves_result_and_canonical_urls(self):
        results = normalize_scrapling_serp_results(
            [{"url": "https://example.com/campaign?utm_source=search", "title": "Campaign", "excerpt": "Launch"}],
            query="site:example.com campaign", source_url="https://search.example/results?q=campaign",
            observed_at="2026-09-11T00:00:00+00:00",
        )
        self.assertEqual("https://example.com/campaign?utm_source=search", results[0].result_url)
        self.assertEqual("https://example.com/campaign", results[0].canonical_url)
        self.assertEqual("scrapling_saved_serp", results[0].method)

    def test_recorded_adapters_return_provider_results_and_raw_pointer(self):
        ads = json.loads((ROOT / "tests/fixtures/providers/apify_ads.json").read_text())
        ad_result = RecordedApifyAdvertisingAdapter(
            ads, observed_at="2026-09-11T00:00:00+00:00", raw_payload_location="raw/apify.json"
        ).find_ads("example.com")
        self.assertEqual(2, len(ad_result.records))
        self.assertEqual("raw/apify.json", ad_result.raw_payload_location)

        tech = json.loads((ROOT / "tests/fixtures/providers/deepline_technologies.json").read_text())
        tech_result = RecordedDeeplineEnrichmentAdapter(
            tech, observed_at="2026-09-11T00:00:00+00:00", raw_payload_location="raw/deepline.json"
        ).enrich_account("example.com")
        self.assertEqual("deepline_recorded", tech_result.provider)

        search_result = RecordedScraplingSearchAdapter(
            [{"url": "https://example.com/campaign", "title": "Campaign"}],
            source_url="https://search.example/results", observed_at="2026-09-11T00:00:00+00:00",
            raw_payload_location="raw/serp.html",
        ).search_pages("example.com", "site:example.com campaign")
        self.assertEqual(1, len(search_result.records))


if __name__ == "__main__":
    unittest.main()
