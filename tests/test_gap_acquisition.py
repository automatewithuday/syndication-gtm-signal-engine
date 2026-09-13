import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gtm_signal_engine.gap_acquisition import acquire_gap_evidence, build_gap_target_plan
from gtm_signal_engine.providers import FetchedDocument


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class FixtureFetcher:
    def __init__(self, responses: dict[str, bytes]):
        self.responses = responses
        self.requested: list[str] = []

    def fetch(self, url: str) -> FetchedDocument:
        self.requested.append(url)
        return FetchedDocument(
            requested_url=url, final_url=url, status_code=200,
            headers={"content-type": "text/plain" if url.endswith("robots.txt") else "text/html"},
            body=self.responses[url],
        )


class GapAcquisitionTests(unittest.TestCase):
    def _run(self, root: Path) -> Path:
        run_dir = root / "run"
        normalized = run_dir / "normalized"
        (run_dir / "raw").mkdir(parents=True)
        _write(run_dir / "manifest.json", {
            "run_id": "acquisition-run", "seed_url": "https://example.com/",
            "provider": "ScraplingFetcher", "pages_collected": 1,
            "requests_attempted": 1, "raw_responses": 1, "errors": [],
        })
        _write(normalized / "pages.jsonl", {
            "url": "https://example.com/", "text": "Home", "main_text": "Home",
            "links": [], "content_hash": "a" * 64,
            "observed_at": "2026-09-13T00:00:00Z",
        })
        (normalized / "discovered_urls.jsonl").write_text("\n".join([
            json.dumps({"url": "https://example.com/careers", "priority": 50}),
            json.dumps({"url": "https://example.com/blog/ordinary", "priority": 50}),
            json.dumps({"url": "https://outside.example/press/launch", "priority": 50}),
        ]) + "\n")
        _write(normalized / "external_profile.json", {
            "domain": "example.com", "technologies": [], "gap_observations": [],
            "ads": [{
                "destination": {
                    "observed_url": "https://example.com/landing/new-offer?utm_source=linkedin",
                    "canonical_url": "https://example.com/landing/new-offer",
                }
            }],
        })
        (normalized / "serp_results.jsonl").write_text(json.dumps({
            "query": "site:example.com demand generation campaign",
            "title": "New campaign", "excerpt": "Demand generation expansion",
            "result_url": "https://example.com/press/releases/growth-campaign",
            "canonical_url": "https://example.com/press/releases/growth-campaign",
            "source_url": "https://search.example/results", "position": 1,
            "observed_at": "2026-09-13T00:00:00Z", "method": "scrapling_saved_serp",
        }) + "\n")
        return run_dir

    def test_plan_merges_saved_sources_and_selects_bounded_same_domain_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self._run(Path(directory))
            first = build_gap_target_plan(run_dir, maximum_targets=2)
            second = build_gap_target_plan(run_dir, maximum_targets=2)

            self.assertEqual(3, first["target_count"])
            self.assertEqual(2, first["selected_count"])
            self.assertEqual(first["snapshot_id"], second["snapshot_id"])
            selected = [item for item in first["targets"] if item["selected"]]
            self.assertEqual(
                ["https://example.com/careers", "https://example.com/landing/new-offer"],
                [item["url"] for item in selected],
            )
            self.assertTrue(all("outside.example" not in item["url"] for item in first["targets"]))
            self.assertTrue(all("/blog/ordinary" not in item["url"] for item in first["targets"]))

    def test_rejects_search_rows_without_scrapling_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self._run(Path(directory))
            path = run_dir / "normalized" / "serp_results.jsonl"
            row = json.loads(path.read_text())
            row["method"] = "generic_search"
            path.write_text(json.dumps(row) + "\n")

            with self.assertRaisesRegex(ValueError, "lacks Scrapling provenance"):
                build_gap_target_plan(run_dir)

    def test_failed_target_is_skipped_until_retry_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self._run(Path(directory))
            manifest_path = run_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["targeted_collections"] = [{
                "kind": "channel_gap",
                "finished_at": "2026-09-13T01:00:00Z",
                "targets_selected": ["https://example.com/careers"],
                "pages_fetched": [],
                "errors": [{
                    "url": "https://example.com/careers",
                    "purpose": "targeted_gap",
                    "error": "ValueError: redirected to unrelated path https://example.com/",
                }],
            }]
            _write(manifest_path, manifest)

            default_plan = build_gap_target_plan(run_dir, maximum_targets=10)
            retry_plan = build_gap_target_plan(
                run_dir, maximum_targets=10, retry_failed=True
            )

            careers = next(
                item for item in default_plan["targets"] if item["url"].endswith("/careers")
            )
            retry_careers = next(
                item for item in retry_plan["targets"] if item["url"].endswith("/careers")
            )
            self.assertFalse(careers["selected"])
            self.assertEqual(1, careers["previous_attempts"])
            self.assertIn("redirected to unrelated path", careers["last_error"])
            self.assertEqual(1, default_plan["skipped_previously_attempted"])
            self.assertTrue(retry_careers["selected"])

    def test_snapshot_ignores_nonlogical_manifest_timestamps(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self._run(Path(directory))
            first = build_gap_target_plan(run_dir, maximum_targets=2)
            manifest_path = run_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["finished_at"] = "2099-01-01T00:00:00Z"
            _write(manifest_path, manifest)

            second = build_gap_target_plan(run_dir, maximum_targets=2)

            self.assertEqual(first["snapshot_id"], second["snapshot_id"])

    def test_acquisition_fetches_saved_plan_and_refreshes_resolution(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self._run(Path(directory))
            fetcher = FixtureFetcher({
                "https://example.com/robots.txt": b"User-agent: *\nAllow: /\n",
                "https://example.com/careers": b"<html><main>Careers</main></html>",
                "https://example.com/landing/new-offer": (
                    b"<html><main>We plan to expand retargeting to re-engage visitors.</main></html>"
                ),
            })
            resolution = {
                "status": "review_required", "review_counts": {"pending": 1},
                "channels": {"retargeting": {"gap_status": "insufficient_evidence"}},
            }
            with patch(
                "gtm_signal_engine.gap_acquisition.resolve_channel_gaps",
                return_value=resolution,
            ):
                result = acquire_gap_evidence(
                    run_dir, maximum_targets=2, maximum_pages=2,
                    delay_seconds=0, fetcher=fetcher,
                )

            self.assertEqual("completed", result["status"])
            self.assertEqual(2, len(result["collection"]["pages_fetched"]))
            self.assertEqual("review_required", result["resolution"]["status"])
            self.assertEqual(
                result["plan"]["snapshot_id"],
                result["collection"]["target_plan_snapshot_id"],
            )
            self.assertTrue((run_dir / "normalized" / "gap_evidence_acquisition.json").is_file())

    def test_pipeline_mode_defers_resolution(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self._run(Path(directory))
            with patch(
                "gtm_signal_engine.gap_acquisition.resolve_channel_gaps"
            ) as resolver:
                result = acquire_gap_evidence(
                    run_dir, maximum_targets=2, maximum_pages=2,
                    resolve_after_collection=False,
                    fetcher=FixtureFetcher({
                        "https://example.com/robots.txt": b"User-agent: *\nAllow: /\n",
                        "https://example.com/careers": b"<html><main>Careers</main></html>",
                        "https://example.com/landing/new-offer": b"<html><main>Offer</main></html>",
                    }),
                    delay_seconds=0,
                )

            resolver.assert_not_called()
            self.assertIsNone(result["resolution"])
            self.assertTrue(result["resolution_deferred"])


if __name__ == "__main__":
    unittest.main()
