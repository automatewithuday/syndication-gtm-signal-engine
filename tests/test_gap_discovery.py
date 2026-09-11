import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gtm_signal_engine.gap_discovery import (
    collect_gap_targets,
    discover_gap_candidates,
    discover_initiative_candidates,
    gap_target_priority,
)
from gtm_signal_engine.providers import FetchedDocument


class FixtureFetcher:
    def __init__(self, responses):
        self.responses = responses
        self.requested = []

    def fetch(self, url):
        self.requested.append(url)
        return FetchedDocument(
            requested_url=url,
            final_url=url,
            status_code=200,
            headers={"content-type": "text/plain" if url.endswith("robots.txt") else "text/html"},
            body=self.responses[url],
        )


class GapDiscoveryTests(unittest.TestCase):
    def make_run(self, directory):
        run_dir = Path(directory)
        normalized = run_dir / "normalized"
        normalized.mkdir()
        (run_dir / "raw").mkdir()
        (run_dir / "manifest.json").write_text(json.dumps({
            "run_id": "scrapling-run",
            "seed_url": "https://example.com/",
            "provider": "ScraplingFetcher",
            "pages_collected": 1,
            "requests_attempted": 1,
            "raw_responses": 1,
            "errors": [],
        }))
        (normalized / "pages.jsonl").write_text(json.dumps({
            "url": "https://example.com/",
            "text": "Homepage",
            "main_text": "Homepage",
            "links": [],
            "content_hash": "a" * 64,
            "observed_at": "2026-09-10T00:00:00+00:00",
        }) + "\n")
        (normalized / "discovered_urls.jsonl").write_text("".join(
            json.dumps({"url": url, "priority": 0}) + "\n"
            for url in (
                "https://example.com/careers",
                "https://example.com/blog/ordinary-post",
                "https://external.example/news",
            )
        ))
        return run_dir

    def test_target_priority_prefers_explicit_syndication_over_news(self):
        self.assertLess(
            gap_target_priority("https://example.com/content-syndication"),
            gap_target_priority("https://example.com/news"),
        )
        self.assertEqual(100, gap_target_priority("https://example.com/on-demand-pay"))
        self.assertEqual(100, gap_target_priority("https://example.com/case-study/strong-partnership"))
        self.assertEqual(100, gap_target_priority("https://example.com/category/content-syndication-platforms"))
        self.assertEqual(100, gap_target_priority("https://example.com/press-center/page/2"))
        self.assertEqual(3, gap_target_priority("https://example.com/job-offer/demand-gen"))
        self.assertEqual(12, gap_target_priority("https://example.com/press-center/releases/product-launch"))
        self.assertEqual(100, gap_target_priority("https://example.com/press-center/releases/board-appointment"))

    def test_targeted_collection_fetches_only_high_signal_discovered_urls(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self.make_run(directory)
            fetcher = FixtureFetcher({
                "https://example.com/robots.txt": b"User-agent: *\nAllow: /\n",
                "https://example.com/careers": (
                    b"<html><main>We are hiring a demand generation partner and expanding "
                    b"content distribution this quarter.</main></html>"
                ),
            })
            result = collect_gap_targets(run_dir, maximum_pages=3, delay_seconds=0, fetcher=fetcher)
            self.assertEqual(["https://example.com/careers"], result["pages_fetched"])
            self.assertNotIn("https://example.com/blog/ordinary-post", fetcher.requested)
            self.assertNotIn("https://external.example/news", fetcher.requested)
            self.assertEqual(2, json.loads((run_dir / "manifest.json").read_text())["pages_collected"])

    def test_targeted_collection_follows_relevant_links_within_depth(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self.make_run(directory)
            fetcher = FixtureFetcher({
                "https://example.com/robots.txt": b"User-agent: *\nAllow: /\n",
                "https://example.com/careers": b'<html><a href="/job-offer/demand-gen">Role</a></html>',
                "https://example.com/job-offer/demand-gen": b"<html><main>Role description</main></html>",
            })
            result = collect_gap_targets(
                run_dir, maximum_pages=3, maximum_depth=2, delay_seconds=0, fetcher=fetcher
            )
            self.assertEqual(
                ["https://example.com/careers", "https://example.com/job-offer/demand-gen"],
                result["pages_fetched"],
            )

    def test_explicit_target_must_be_discovered_and_bypasses_topic_priority(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self.make_run(directory)
            press_url = "https://example.com/press-center/releases/campaign-launch"
            with (run_dir / "normalized" / "discovered_urls.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"url": press_url, "priority": 80}) + "\n")
            fetcher = FixtureFetcher({
                "https://example.com/robots.txt": b"User-agent: *\nAllow: /\n",
                press_url: b"<html><main>We launched the Future of Pay campaign.</main></html>",
            })

            result = collect_gap_targets(
                run_dir,
                maximum_pages=1,
                delay_seconds=0,
                include_urls=[press_url],
                fetcher=fetcher,
            )

            self.assertEqual([press_url], result["pages_fetched"])
            self.assertEqual([press_url], result["explicit_targets"])

            with self.assertRaisesRegex(ValueError, "not present"):
                collect_gap_targets(
                    run_dir,
                    include_urls=["https://example.com/undiscovered"],
                    delay_seconds=0,
                    fetcher=fetcher,
                )

    def test_candidate_rules_create_pending_review_not_scored_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self.make_run(directory)
            pages_path = run_dir / "normalized" / "pages.jsonl"
            pages_path.write_text(json.dumps({
                "url": "https://example.com/careers",
                "text": "We are hiring a demand generation partner as we expand content distribution.",
                "main_text": "We are hiring a demand generation partner as we expand content distribution.",
                "links": [],
                "content_hash": "b" * 64,
                "observed_at": "2026-09-10T00:00:00+00:00",
                "metadata": {"article:published_time": "2026-09-01T00:00:00+00:00"},
            }) + "\n")
            summary = discover_gap_candidates(run_dir)
            candidates = [
                json.loads(line)
                for line in (run_dir / "normalized" / "gap_candidates.jsonl").read_text().splitlines()
            ]
            self.assertGreaterEqual(summary["candidate_count"], 1)
            self.assertTrue(all(item["review_status"] == "pending" for item in candidates))
            self.assertTrue(all(item["method"] == "scrapling_saved_page_candidate" for item in candidates))
            self.assertEqual("2026-09-01T00:00:00+00:00", candidates[0]["source_date"]["value"])
            self.assertIn("not scored evidence", summary["warning"])

    def test_tool_directory_labels_do_not_create_gap_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self.make_run(directory)
            (run_dir / "normalized" / "pages.jsonl").write_text(json.dumps({
                "url": "https://example.com/ai-marketing-tools",
                "text": "Low Solo teams scaling social selling and inbound leads",
                "main_text": "Low Solo teams scaling social selling and inbound leads",
                "links": [],
                "content_hash": "c" * 64,
                "observed_at": "2026-09-10T00:00:00+00:00",
            }) + "\n")
            summary = discover_gap_candidates(run_dir)
            self.assertEqual(0, summary["candidate_count"])

    def test_initiative_candidates_preserve_date_and_stay_out_of_gap(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self.make_run(directory)
            (run_dir / "normalized" / "pages.jsonl").write_text(json.dumps({
                "url": "https://example.com/press/campaign",
                "text": "Today we launched Project Reach, a campaign for finance leaders.",
                "main_text": "Today we launched Project Reach, a campaign for finance leaders.",
                "links": [],
                "content_hash": "f" * 64,
                "observed_at": "2026-09-11T00:00:00+00:00",
                "metadata": {"article:published_time": "2026-09-01T00:00:00+00:00"},
            }) + "\n")
            initiative = discover_initiative_candidates(run_dir)
            gap = discover_gap_candidates(run_dir)
            candidate = json.loads(
                (run_dir / "normalized" / "initiative_candidates.jsonl").read_text().splitlines()[0]
            )
            self.assertEqual(1, initiative["candidate_count"])
            self.assertEqual(1, initiative["dated_candidate_count"])
            self.assertEqual("public_campaign_launch", candidate["signal_type"])
            self.assertEqual("2026-09-01T00:00:00+00:00", candidate["source_date"]["value"])
            self.assertEqual(0, gap["candidate_count"])

    def test_initiative_candidates_dedupe_same_signal_on_one_page(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self.make_run(directory)
            (run_dir / "normalized" / "pages.jsonl").write_text(json.dumps({
                "url": "https://example.com/job-offer/ads-manager",
                "text": "We are looking for an Ads Manager. We are hiring an Ads Manager now.",
                "main_text": "We are looking for an Ads Manager. We are hiring an Ads Manager now.",
                "links": [],
                "content_hash": "e" * 64,
                "observed_at": "2026-09-11T00:00:00+00:00",
            }) + "\n")
            summary = discover_initiative_candidates(run_dir)
            self.assertEqual(1, summary["candidate_count"])
            self.assertEqual({"active_marketing_hiring": 1}, summary["by_signal_type"])


if __name__ == "__main__":
    unittest.main()
