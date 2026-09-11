import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gtm_signal_engine.providers import FetchedDocument
from gtm_signal_engine.workflow import analyze_saved_run, crawl_and_analyze


class ScraplingFetcher:
    def __init__(self, responses):
        self.responses = responses

    def fetch(self, url):
        item = self.responses[url]
        return FetchedDocument(
            requested_url=url,
            final_url=url,
            status_code=200,
            headers={"content-type": item.get("content_type", "text/html")},
            body=item["body"],
        )


class WorkflowTests(unittest.TestCase):
    def test_crawl_and_analyze_writes_evidence_report_with_unknowns(self):
        responses = {
            "https://example.com/robots.txt": {
                "content_type": "text/plain",
                "body": b"User-agent: *\nAllow: /\n",
            },
            "https://example.com/sitemap.xml": {
                "content_type": "application/xml",
                "body": (
                    b'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                    b"<url><loc>https://example.com/</loc></url>"
                    b"<url><loc>https://example.com/case-studies/acme</loc></url></urlset>"
                ),
            },
            "https://example.com/": {
                "body": b'<html><main>B2B platform</main><a href="/case-studies/acme">Proof</a></html>',
            },
            "https://example.com/case-studies/acme": {
                "body": (
                    b'<html><head><meta property="article:published_time" content="2026-09-01T00:00:00+00:00">'
                    b"</head><main>Case Study " + b"Measured customer outcome. " * 300 + b"</main></html>"
                ),
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "report.json"
            report = crawl_and_analyze(
                "example.com",
                output_path=output,
                output_root=root / "runs",
                maximum_pages=5,
                delay_seconds=0,
                fetcher=ScraplingFetcher(responses),
            )

            saved = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual("ScraplingFetcher", saved["run"]["provider"])
            self.assertIsNone(saved["scores"]["components"]["fit"]["score"])
            self.assertIsNone(saved["scores"]["components"]["gap"]["score"])
            self.assertTrue(saved["evidence_samples"])
            self.assertIn("Unknown components", report["interpretation"])

            replay_output = root / "replayed.json"
            replay = analyze_saved_run(
                Path(report["run_dir"]), output_path=replay_output, account_name="Example"
            )
            self.assertEqual(report["run"]["run_id"], replay["run"]["run_id"])
            self.assertTrue(replay_output.exists())


if __name__ == "__main__":
    unittest.main()
