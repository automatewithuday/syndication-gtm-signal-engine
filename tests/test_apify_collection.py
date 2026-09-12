import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gtm_signal_engine.apify_collection import (
    HttpResponse,
    collect_apify_ads,
    normalize_apify_linkedin,
    normalize_apify_meta,
    replay_apify_ads,
)


class FakeVault:
    def __init__(self, value="secret-token", missing=False):
        self.value = value
        self.missing = missing

    def get_secret(self, name):
        if self.missing:
            raise KeyError(name)
        return self.value


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def request(self, method, url, *, headers, body, timeout):
        self.requests.append({"method": method, "url": url, "headers": headers, "body": body, "timeout": timeout})
        status, payload = self.responses.pop(0)
        return HttpResponse(status, json.dumps(payload).encode())


def response(data):
    return (200, {"data": data})


class ApifyCollectionTests(unittest.TestCase):
    def _run_dir(self, root):
        run_dir = root / "run"
        (run_dir / "normalized").mkdir(parents=True)
        (run_dir / "manifest.json").write_text(json.dumps({
            "provider": "ScraplingFetcher", "seed_url": "https://example.com/", "run_id": "run",
        }))
        return run_dir

    def test_provider_specific_normalizers_require_account_destination(self):
        linkedin = json.loads((ROOT / "tests/fixtures/providers/apify_linkedin_raw.json").read_text())
        meta = json.loads((ROOT / "tests/fixtures/providers/apify_meta_raw.json").read_text())
        linked, linked_warnings = normalize_apify_linkedin(
            linkedin, domain="example.com", account_name="Example",
            observed_at="2026-09-11T00:00:00+00:00",
        )
        facebook, meta_warnings = normalize_apify_meta(
            meta, domain="example.com", account_name="Example",
            observed_at="2026-09-11T00:00:00+00:00",
        )
        self.assertEqual(["li-123"], [item.provider_record_id for item in linked])
        self.assertEqual(["meta-456"], [item.provider_record_id for item in facebook])
        self.assertEqual("apify_ads_normalizer_v2", linked[0].normalizer_version)
        self.assertTrue(linked[0].destination.observed_url.startswith("https://bit.ly/"))
        self.assertEqual({"fbclid": "click-2"}, facebook[0].destination.click_identifiers)
        self.assertEqual(1, len(linked_warnings))
        self.assertEqual(1, len(meta_warnings))

    def test_missing_vault_token_blocks_before_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            transport = FakeTransport([])
            result = collect_apify_ads(
                self._run_dir(Path(temporary)), "example.com", account_name="Example",
                vault=FakeVault(missing=True), transport=transport,
            )
            self.assertTrue(result.incomplete)
            self.assertEqual([], transport.requests)
            status = json.loads((Path(temporary) / "run/normalized/apify_collection.json").read_text())
            self.assertEqual("blocked", status["status"])
            self.assertNotIn("secret-token", json.dumps(status))

    def test_runs_each_actor_once_with_caps_and_persists_normalized_ads(self):
        linked = json.loads((ROOT / "tests/fixtures/providers/apify_linkedin_raw.json").read_text())
        meta = json.loads((ROOT / "tests/fixtures/providers/apify_meta_raw.json").read_text())
        responses = [
            response({"isPublic": True, "isDeprecated": False}),
            response({"id": "run-li", "status": "READY"}),
            response({"id": "run-li", "status": "SUCCEEDED", "defaultDatasetId": "ds-li", "usageTotalUsd": 0.01}),
            (200, linked),
            response({"isPublic": True, "isDeprecated": False}),
            response({"id": "run-meta", "status": "READY"}),
            response({"id": "run-meta", "status": "SUCCEEDED", "defaultDatasetId": "ds-meta", "usageTotalUsd": 0.02}),
            (200, meta),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = self._run_dir(Path(temporary))
            transport = FakeTransport(responses)
            result = collect_apify_ads(
                run_dir, "example.com", account_name="Example",
                vault=FakeVault(), transport=transport,
            )
            self.assertFalse(result.incomplete)
            self.assertEqual(2, len(result.records))
            posts = [request for request in transport.requests if request["method"] == "POST"]
            self.assertEqual(2, len(posts))
            self.assertTrue(all("maxItems=25" in request["url"] for request in posts))
            self.assertTrue(all("maxTotalChargeUsd=0.15" in request["url"] for request in posts))
            self.assertTrue(all(request["headers"]["Authorization"] == "Bearer secret-token" for request in posts))
            profile = json.loads((run_dir / "normalized/external_profile.json").read_text())
            self.assertEqual({"linkedin", "meta"}, {item["platform"] for item in profile["ads"]})
            status = json.loads((run_dir / "normalized/apify_collection.json").read_text())
            for details in status["platforms"].values():
                for artifact, location in details["raw"].items():
                    self.assertTrue((run_dir / location).is_file())
                    self.assertIn(details["sha256"][artifact][:16], location)
            persisted = json.dumps(status)
            self.assertNotIn("secret-token", persisted)
            for artifact in run_dir.rglob("*.json"):
                self.assertNotIn("secret-token", artifact.read_text())

    def test_platform_selection_preserves_existing_other_platform_ads(self):
        meta = json.loads((ROOT / "tests/fixtures/providers/apify_meta_raw.json").read_text())
        responses = [
            response({"isPublic": True, "isDeprecated": False}),
            response({"id": "run-meta", "status": "READY"}),
            response({"id": "run-meta", "status": "SUCCEEDED", "defaultDatasetId": "ds-meta"}),
            (200, meta),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = self._run_dir(Path(temporary))
            profile_path = run_dir / "normalized/external_profile.json"
            profile_path.write_text(json.dumps({
                "domain": "example.com", "technologies": [], "gap_observations": [],
                "ads": [{"platform": "linkedin", "provider_record_id": "saved-li"}],
            }))
            (run_dir / "normalized/apify_collection.json").write_text(json.dumps({
                "platforms": {"linkedin": {"status": "SUCCEEDED", "raw": {}}}
            }))
            transport = FakeTransport(responses)
            result = collect_apify_ads(
                run_dir, "example.com", account_name="Example", platforms=("meta",),
                vault=FakeVault(), transport=transport,
            )
            self.assertFalse(result.incomplete)
            self.assertEqual(1, len([item for item in transport.requests if item["method"] == "POST"]))
            profile = json.loads(profile_path.read_text())
            self.assertEqual(
                {"saved-li", "meta-456"}, {item["provider_record_id"] for item in profile["ads"]}
            )
            status = json.loads((run_dir / "normalized/apify_collection.json").read_text())
            self.assertEqual({"linkedin", "meta"}, set(status["platforms"]))

    def test_replay_renormalizes_saved_datasets_without_network(self):
        linked = (ROOT / "tests/fixtures/providers/apify_linkedin_raw.json").read_bytes()
        meta = (ROOT / "tests/fixtures/providers/apify_meta_raw.json").read_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = self._run_dir(Path(temporary))
            raw_dir = run_dir / "raw"
            raw_dir.mkdir()
            (raw_dir / "linkedin.json").write_bytes(linked)
            (raw_dir / "meta.json").write_bytes(meta)
            (run_dir / "normalized/apify_collection.json").write_text(json.dumps({
                "platforms": {
                    "linkedin": {"raw": {"dataset": "raw/linkedin.json"}},
                    "meta": {"raw": {"dataset": "raw/meta.json"}},
                }
            }))
            result = replay_apify_ads(run_dir, "example.com", account_name="Example")
            self.assertEqual(2, len(result.records))
            profile = json.loads((run_dir / "normalized/external_profile.json").read_text())
            self.assertEqual({"linkedin", "meta"}, {item["platform"] for item in profile["ads"]})

    def test_meta_zero_result_envelope_is_not_treated_as_an_ad(self):
        records = [{
            "inputUrl": "https://www.facebook.com/ads/library/",
            "isResultComplete": True, "totalCount": 0, "results": [],
        }]
        observations, warnings = normalize_apify_meta(
            records, domain="example.com", account_name="Example",
            observed_at="2026-09-11T00:00:00+00:00",
        )
        self.assertEqual([], observations)
        self.assertEqual([], warnings)

    def test_exact_advertiser_ad_is_retained_without_destination(self):
        records = [{
            "adId": "li-no-destination", "advertiserName": "Example",
            "headline": "A verified active ad",
        }]
        observations, warnings = normalize_apify_linkedin(
            records, domain="example.com", account_name="Example",
            observed_at="2026-09-11T00:00:00+00:00",
        )
        self.assertEqual([], warnings)
        self.assertEqual("li-no-destination", observations[0].provider_record_id)
        self.assertIsNone(observations[0].destination)

    def test_paid_start_is_not_retried_after_failure(self):
        responses = [
            response({"isPublic": True, "isDeprecated": False}),
            (500, {"error": {"message": "provider failed"}}),
            response({"isPublic": True, "isDeprecated": False}),
            (500, {"error": {"message": "provider failed"}}),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            transport = FakeTransport(responses)
            result = collect_apify_ads(
                self._run_dir(Path(temporary)), "example.com", account_name="Example",
                vault=FakeVault(), transport=transport,
            )
            self.assertTrue(result.incomplete)
            self.assertEqual(2, len([item for item in transport.requests if item["method"] == "POST"]))

    def test_successful_actor_with_only_unattributable_rows_is_inconclusive(self):
        records = [{"adId": "other", "advertiserName": "Different Company"}]
        responses = [
            response({"isPublic": True, "isDeprecated": False}),
            response({"id": "run-li", "status": "SUCCEEDED", "defaultDatasetId": "ds-li"}),
            (200, records),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = self._run_dir(Path(temporary))
            result = collect_apify_ads(
                run_dir, "example.com", account_name="Example", platforms=("linkedin",),
                vault=FakeVault(), transport=FakeTransport(responses),
            )
            self.assertTrue(result.incomplete)
            status = json.loads((run_dir / "normalized/apify_collection.json").read_text())
            self.assertEqual("inconclusive", status["platforms"]["linkedin"]["status"])
            self.assertEqual("SUCCEEDED", status["platforms"]["linkedin"]["actor_run_status"])

    def test_linkedin_company_id_targets_authoritative_library_identity(self):
        linked = json.loads((ROOT / "tests/fixtures/providers/apify_linkedin_raw.json").read_text())
        responses = [
            response({"isPublic": True, "isDeprecated": False}),
            response({"id": "run-li", "status": "READY"}),
            response({"id": "run-li", "status": "SUCCEEDED", "defaultDatasetId": "ds-li"}),
            (200, linked),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = self._run_dir(Path(temporary))
            transport = FakeTransport(responses)
            result = collect_apify_ads(
                run_dir, "example.com", account_name="Example",
                linkedin_company_id="65826193", platforms=("linkedin",),
                vault=FakeVault(), transport=transport,
            )
            self.assertFalse(result.incomplete)
            post = next(item for item in transport.requests if item["method"] == "POST")
            payload = json.loads(post["body"])
            self.assertEqual(
                "https://www.linkedin.com/ad-library/search?companyIds=65826193",
                payload["startUrls"][0]["url"],
            )
            status = json.loads((run_dir / "normalized/apify_collection.json").read_text())
            self.assertEqual(
                {"type": "linkedin_company_id", "value": "65826193"},
                status["platforms"]["linkedin"]["search_identity"],
            )

    def test_invalid_linkedin_company_id_blocks_before_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            transport = FakeTransport([])
            with self.assertRaisesRegex(ValueError, "digits only"):
                collect_apify_ads(
                    self._run_dir(Path(temporary)), "example.com", account_name="Example",
                    linkedin_company_id="not-a-number", platforms=("linkedin",),
                    vault=FakeVault(), transport=transport,
                )
            self.assertEqual([], transport.requests)


if __name__ == "__main__":
    unittest.main()
