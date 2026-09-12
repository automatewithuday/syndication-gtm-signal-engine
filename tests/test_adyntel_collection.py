import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gtm_signal_engine.adyntel_collection import (
    collect_adyntel_ads,
    normalize_adyntel_ads,
    replay_adyntel_response,
)


def contract(tool_id):
    return {
        "toolId": tool_id, "callable": True, "connected": True,
        "inputSchema": {"jsonSchema": {"properties": {"company_domain": {"type": "string"}}}},
    }


def envelope(payload, job_id="job-1"):
    return {
        "job_id": job_id, "status": "completed",
        "toolResponse": {"rawV2": payload, "raw": payload},
        "billing": {"credits_charged": 0.13, "cost_usd": 0.013},
    }


class FakeRunner:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def run(self, arguments):
        self.calls.append(list(arguments))
        payload = self.payloads.pop(0)
        return subprocess.CompletedProcess(arguments, 0, json.dumps(payload), "")


class AdyntelCollectionTests(unittest.TestCase):
    def _run_dir(self, root):
        run_dir = root / "run"
        (run_dir / "normalized").mkdir(parents=True)
        (run_dir / "manifest.json").write_text(json.dumps({
            "provider": "ScraplingFetcher", "seed_url": "https://example.com/", "run_id": "run",
        }))
        return run_dir

    def test_normalizes_linkedin_and_google_observed_contracts(self):
        linkedin, warnings = normalize_adyntel_ads("linkedin", {"ads": [{
            "ad_id": "li-1", "advertiser": {"name": "A Founder"},
            "commentary": {"text": "A campaign"},
            "headline": {"title": "See the guide"},
            "destinationUrl": "https://example.com/guide?utm_source=linkedin",
            "eu_transparency": {"startDate": "2026-01-01"},
            "view_details_link": "https://www.linkedin.com/ad-library/detail/li-1",
        }]}, observed_at="2026-09-12T00:00:00+00:00")
        google, google_warnings = normalize_adyntel_ads("google", {"ads": [{
            "creative_id": "g-1", "advertiser_name": "EXAMPLE LLC", "format": "Text",
            "start": "2026-02-01", "last_seen": "2026-03-01",
            "original_url": "https://adstransparency.google.com/advertiser/a/creative/g",
            "variants": [{"content": "<img src='creative.png'>"}],
        }]}, observed_at="2026-09-12T00:00:00+00:00")
        self.assertEqual([], warnings)
        self.assertEqual([], google_warnings)
        self.assertEqual("li-1", linkedin[0].provider_record_id)
        self.assertEqual("linkedin", linkedin[0].platform)
        self.assertEqual({"utm_source": "linkedin"}, linkedin[0].destination.utm_parameters)
        self.assertEqual("g-1", google[0].provider_record_id)
        self.assertEqual("2026-03-01", google[0].last_seen_at)
        self.assertEqual("adyntel_ads_normalizer_v1", google[0].normalizer_version)

    def test_normalizes_meta_results_shape_and_epoch_dates(self):
        ads, warnings = normalize_adyntel_ads("meta", {"results": [{
            "ad_archive_id": "meta-1", "page_name": "Example",
            "snapshot": {"body": {"text": "Meta copy"}, "link_url": "https://example.com/demo"},
            "start_date": 1788246000, "end_date_string": "2026-09-12T07:00:00.000Z",
            "url": "https://www.facebook.com/ads/library?id=meta-1",
        }]}, observed_at="2026-09-12T00:00:00+00:00")
        self.assertEqual([], warnings)
        self.assertEqual("Meta copy", ads[0].creative_text)
        self.assertEqual("https://example.com/demo", ads[0].destination.canonical_url)
        self.assertTrue(ads[0].first_seen_at.startswith("2026-"))

    def test_three_tools_run_once_and_partial_totals_are_auditable(self):
        runner = FakeRunner([
            contract("adyntel_facebook"), envelope({"ads": [], "total_ads": 0}, "meta-job"),
            contract("adyntel_linkedin"), envelope({
                "page_id": "123", "total_ads": 214, "continuation_token": "next",
                "ads": [{"ad_id": "li-1", "commentary": {"text": "Copy"},
                         "view_details_link": "https://www.linkedin.com/ad-library/detail/li-1"}],
            }, "li-job"),
            contract("adyntel_google"), envelope({
                "total_ad_count": 44, "continuation_token": "next",
                "ads": [{"creative_id": "g-1", "format": "Video",
                         "original_url": "https://adstransparency.google.com/creative/g-1"}],
            }, "google-job"),
        ])
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = self._run_dir(Path(temporary))
            result = collect_adyntel_ads(run_dir, "example.com", runner=runner)
            self.assertTrue(result.incomplete)
            self.assertEqual(2, len(result.records))
            execute_calls = [call for call in runner.calls if call[:2] == ["tools", "execute"]]
            self.assertEqual(3, len(execute_calls))
            status = json.loads((run_dir / "normalized/adyntel_collection.json").read_text())
            self.assertEqual(214, status["platforms"]["linkedin"]["provider_total_records"])
            self.assertEqual(44, status["platforms"]["google"]["provider_total_records"])
            self.assertEqual("completed", status["platforms"]["meta"]["status"])
            self.assertTrue(all((run_dir / path).is_file() for details in status["platforms"].values()
                                for path in details.get("raw", {}).values()))

    def test_empty_payload_is_inconclusive_and_preserves_apify_fallback(self):
        runner = FakeRunner([
            contract("adyntel_facebook"),
            {"job_id": "empty", "status": "completed", "toolResponse": {"rawV2": "", "raw": ""},
             "billing": {"credits_charged": 0.13}},
        ])
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = self._run_dir(Path(temporary))
            profile_path = run_dir / "normalized/external_profile.json"
            profile_path.write_text(json.dumps({
                "domain": "example.com", "technologies": [], "gap_observations": [],
                "ads": [{"platform": "meta", "provider_record_id": "apify-meta"}],
            }))
            result = collect_adyntel_ads(run_dir, "example.com", platforms=("meta",), runner=runner)
            self.assertTrue(result.incomplete)
            self.assertEqual("apify-meta", json.loads(profile_path.read_text())["ads"][0]["provider_record_id"])
            status = json.loads((run_dir / "normalized/adyntel_collection.json").read_text())
            self.assertEqual("inconclusive", status["platforms"]["meta"]["status"])

    def test_linkedin_page_id_is_audited_but_domain_is_sent_due_live_contract_bug(self):
        runner = FakeRunner([
            contract("adyntel_linkedin"), envelope({"ads": [], "total_ads": 0}),
        ])
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = self._run_dir(Path(temporary))
            collect_adyntel_ads(
                run_dir, "example.com", linkedin_page_id="65826193",
                platforms=("linkedin",), runner=runner,
            )
            execute = next(call for call in runner.calls if call[:2] == ["tools", "execute"])
            self.assertEqual({"company_domain": "example.com"}, json.loads(execute[4]))
            status = json.loads((run_dir / "normalized/adyntel_collection.json").read_text())
            self.assertEqual("65826193", status["platforms"]["linkedin"]["request"]["resolved_linkedin_page_id_hint"])

    def test_replay_repairs_saved_response_without_runner(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = self._run_dir(Path(temporary))
            response_path = run_dir / "raw" / "meta.json"
            response_path.parent.mkdir()
            response_path.write_text(json.dumps(envelope({
                "number_of_ads": 2, "continuation_token": "next", "results": [{
                    "ad_archive_id": "meta-1", "snapshot": {"body": {"text": "Copy"}},
                    "url": "https://www.facebook.com/ads/library?id=meta-1",
                }],
            })))
            result = replay_adyntel_response(
                run_dir, "example.com", platform="meta", response_path=response_path,
            )
            self.assertTrue(result.incomplete)
            self.assertEqual("meta-1", result.records[0]["provider_record_id"])
            status = json.loads((run_dir / "normalized/adyntel_collection.json").read_text())
            self.assertTrue(status["platforms"]["meta"]["replayed"])


if __name__ == "__main__":
    unittest.main()
