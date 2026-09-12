import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gtm_signal_engine.external_collection import (
    collect_deepline_technologies, normalize_deepline_builtwith,
    replay_deepline_technologies,
)


CONTRACT = {
    "toolId": "builtwith_domain_lookup", "callable": True, "connected": True,
    "inputSchema": {"jsonSchema": {"properties": {
        "domain": {}, "live_only": {}, "no_pii": {}, "no_meta": {},
    }}},
    "outputSchema": {"jsonSchema": {"properties": {"Results": {}}}},
}

PROVIDER_PAYLOAD = {
    "Errors": [],
    "Results": [{
        "Lookup": "example.com",
        "Result": {"Paths": [{
            "Domain": "example.com", "SubDomain": "www",
            "Technologies": [{
                "Name": "Example Tag Manager", "Categories": ["Tag Management", "Analytics"],
                "Description": "A tag-management product.",
                "FirstDetected": 1704067200000, "LastDetected": 1735689600000,
            }],
        }]},
    }],
}


def _completed(arguments, payload, returncode=0, stderr=""):
    return subprocess.CompletedProcess(arguments, returncode, stdout=json.dumps(payload), stderr=stderr)


class FakeRunner:
    def __init__(self, responses):
        self.responses = list(responses)
        self.arguments = []

    def run(self, arguments):
        self.arguments.append(list(arguments))
        return self.responses.pop(0)


class DeeplineCollectionTests(unittest.TestCase):
    def _run_dir(self, root: Path, provider="ScraplingFetcher") -> Path:
        run_dir = root / "run"
        (run_dir / "normalized").mkdir(parents=True)
        (run_dir / "manifest.json").write_text(json.dumps({
            "provider": provider, "seed_url": "https://example.com/", "run_id": "run",
        }))
        return run_dir

    def test_normalizes_live_builtwith_contract_with_dates_and_categories(self):
        result = normalize_deepline_builtwith(
            PROVIDER_PAYLOAD, observed_at="2026-09-11T00:00:00+00:00"
        )[0]
        self.assertEqual("Example Tag Manager", result.technology)
        self.assertEqual("Tag Management | Analytics", result.category)
        self.assertEqual("https://www.example.com/", result.source_url)
        self.assertEqual("2024-01-01T00:00:00+00:00", result.first_seen_at)
        self.assertEqual("2025-01-01T00:00:00+00:00", result.last_seen_at)
        self.assertEqual("deepline_builtwith_domain_lookup", result.method)
        self.assertEqual("deepline_builtwith_v1", result.normalizer_version)

    def test_inspects_contract_then_collects_without_credentials_in_process(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = self._run_dir(Path(temporary))
            envelope = {
                "job_id": "job-1", "status": "completed",
                "toolResponse": {"rawV2": {"data": PROVIDER_PAYLOAD}, "meta": {"usage": {"credits": 0.14}}},
            }
            runner = FakeRunner([_completed([], CONTRACT), _completed([], envelope)])
            result = collect_deepline_technologies(run_dir, "example.com", runner=runner)

            self.assertFalse(result.incomplete)
            self.assertEqual("deepline_builtwith", result.provider)
            self.assertEqual("describe", runner.arguments[0][1])
            self.assertEqual("execute", runner.arguments[1][1])
            request = json.loads(runner.arguments[1][runner.arguments[1].index("--input") + 1])
            self.assertEqual({
                "domain": "example.com", "live_only": True, "no_pii": True,
                "no_meta": True, "no_attr": False, "hide_text": False, "hide_dl": False,
            }, request)
            profile = json.loads((run_dir / "normalized" / "external_profile.json").read_text())
            self.assertEqual(1, len(profile["technologies"]))
            status = json.loads((run_dir / "normalized" / "deepline_collection.json").read_text())
            self.assertEqual(1, status["attempts"])
            self.assertFalse(status["request_policy"]["automatic_paid_retries"])
            self.assertEqual(0.14, status["usage"]["provider_usage"]["credits"])
            self.assertTrue((run_dir / status["raw_payload_location"]).is_file())
            self.assertTrue((run_dir / status["contract_location"]).is_file())
            self.assertIn(status["response_sha256"][:16], status["raw_payload_location"])
            self.assertIn(status["contract_sha256"][:16], status["contract_location"])

    def test_malformed_technology_is_skipped_and_saved_response_can_be_replayed(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = self._run_dir(Path(temporary))
            payload = json.loads(json.dumps(PROVIDER_PAYLOAD))
            payload["Results"][0]["Result"]["Paths"][0]["Technologies"].append({"Name": ""})
            envelope = {
                "job_id": "job-1", "status": "completed",
                "toolResponse": {"rawV2": {"data": payload}},
                "billing": {"credits_charged": 0.14, "cost_usd": 0.014},
            }
            runner = FakeRunner([_completed([], CONTRACT), _completed([], envelope)])
            result = collect_deepline_technologies(run_dir, "example.com", runner=runner)
            self.assertEqual(1, len(result.records))
            status = json.loads((run_dir / "normalized/deepline_collection.json").read_text())
            self.assertIn("missing name", status["warnings"][0])
            replayed = replay_deepline_technologies(run_dir, "example.com")
            self.assertEqual(1, len(replayed.records))
            self.assertTrue(json.loads((run_dir / "normalized/deepline_collection.json").read_text())["replayed"])

    def test_command_failure_is_incomplete_and_is_not_retried(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = self._run_dir(Path(temporary))
            runner = FakeRunner([
                _completed([], CONTRACT),
                _completed([], {}, returncode=5, stderr="provider unavailable"),
            ])
            result = collect_deepline_technologies(run_dir, "example.com", runner=runner)
            status = json.loads((run_dir / "normalized" / "deepline_collection.json").read_text())
            self.assertTrue(result.incomplete)
            self.assertEqual("failed", status["status"])
            self.assertEqual(2, len(runner.arguments))
            self.assertFalse((run_dir / "normalized" / "external_profile.json").exists())

    def test_contract_drift_stops_before_paid_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = self._run_dir(Path(temporary))
            drifted = {**CONTRACT, "outputSchema": {"jsonSchema": {"properties": {}}}}
            runner = FakeRunner([_completed([], drifted)])
            result = collect_deepline_technologies(run_dir, "example.com", runner=runner)
            self.assertTrue(result.incomplete)
            self.assertEqual(1, len(runner.arguments))

    def test_rejects_non_scrapling_run_before_cli(self):
        with tempfile.TemporaryDirectory() as temporary:
            runner = FakeRunner([])
            with self.assertRaisesRegex(ValueError, "ScraplingFetcher"):
                collect_deepline_technologies(
                    self._run_dir(Path(temporary), provider="OtherFetcher"),
                    "example.com", runner=runner,
                )
            self.assertEqual([], runner.arguments)


if __name__ == "__main__":
    unittest.main()
