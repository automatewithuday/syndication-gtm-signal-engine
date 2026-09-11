import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gtm_signal_engine.collector import (
    ScraplingFetcher,
    _crawl_priority,
    canonicalize_url,
    collect_website,
    repair_cross_path_canonicals,
)
from gtm_signal_engine.providers import FetchedDocument


class FixtureFetcher:
    def __init__(self, responses):
        self.responses = responses

    def fetch(self, url):
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return FetchedDocument(
            requested_url=url,
            final_url=url,
            status_code=response.get("status", 200),
            headers={"content-type": response.get("content_type", "text/html; charset=utf-8")},
            body=response["body"],
        )


class CollectorTests(unittest.TestCase):
    def fixture(self, name):
        return (ROOT / "tests" / "fixtures" / "collector" / name).read_bytes()

    def test_canonicalization_removes_tracking_and_fragment(self):
        value = canonicalize_url("/report/?b=2&utm_source=x&a=1#top", "https://WWW.Example.com/start")
        self.assertEqual("https://www.example.com/report?a=1&b=2", value)

    def test_scrapling_uses_browser_transport_only_for_certificate_errors(self):
        class CertificateVerifyError(RuntimeError):
            pass

        class TestFetcher(ScraplingFetcher):
            def _fetch_static(self, url):
                raise CertificateVerifyError("certificate verify failed")

            def _fetch_browser(self, url):
                return "browser-result"

        self.assertEqual("browser-result", TestFetcher(browser_executable="/fake").fetch("https://example.com"))

    def test_scrapling_does_not_hide_non_certificate_errors(self):
        class TestFetcher(ScraplingFetcher):
            def _fetch_static(self, url):
                raise RuntimeError("connection timed out")

            def _fetch_browser(self, url):
                raise AssertionError("browser transport must not run")

        with self.assertRaisesRegex(RuntimeError, "timed out"):
            TestFetcher(browser_executable="/fake").fetch("https://example.com")

    def test_normalization_preserves_main_content_and_time_candidates(self):
        from gtm_signal_engine.collector import normalize_html

        body = b'<html><body><nav>Repeated menu</nav><main><time datetime="2026-08-01">August 1</time><p>Core article</p></main></body></html>'
        page = normalize_html(FetchedDocument(
            requested_url="https://example.com/guide",
            final_url="https://example.com/guide",
            status_code=200,
            headers={"content-type": "text/html; charset=utf-8"},
            body=body,
        ), "2026-09-10T00:00:00+00:00")
        self.assertEqual("August 1 Core article", page.main_text)
        self.assertEqual(
            [{"value": "2026-08-01", "source": "html_time_datetime", "text": "August 1"}],
            page.date_candidates,
        )

    def test_normalization_preserves_link_text(self):
        from gtm_signal_engine.collector import normalize_html

        page = normalize_html(FetchedDocument(
            requested_url="https://example.com/guide",
            final_url="https://example.com/guide",
            status_code=200,
            headers={"content-type": "text/html"},
            body=b'<a href="/files/report.pdf"><span>Download</span> report</a>',
        ), "2026-09-10T00:00:00+00:00")
        self.assertEqual(
            [{"href": "https://example.com/files/report.pdf", "text": "Download report"}],
            page.link_details,
        )

    def test_cross_path_declared_canonical_does_not_replace_fetched_url(self):
        from gtm_signal_engine.collector import normalize_html

        page = normalize_html(FetchedDocument(
            requested_url="https://example.com/contact-finder",
            final_url="https://example.com/contact-finder",
            status_code=200,
            headers={"content-type": "text/html"},
            body=b'<html><head><link rel="canonical" href="https://example.com/"></head><main>Finder</main></html>',
        ), "2026-09-10T00:00:00+00:00")
        self.assertEqual("https://example.com/contact-finder", page.url)

    def test_repair_cross_path_canonical_uses_raw_final_url(self):
        import hashlib

        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            (run_dir / "normalized").mkdir()
            (run_dir / "raw").mkdir()
            (run_dir / "manifest.json").write_text(
                json.dumps({"provider": "ScraplingFetcher"}), encoding="utf-8"
            )
            original_url = "https://example.com/contact-finder"
            page = {
                "url": "https://example.com/",
                "original_url": original_url,
                "content_hash": "abc",
            }
            (run_dir / "normalized" / "pages.jsonl").write_text(
                json.dumps(page) + "\n", encoding="utf-8"
            )
            raw_key = hashlib.sha256(original_url.encode("utf-8")).hexdigest()
            (run_dir / "raw" / f"{raw_key}.json").write_text(
                json.dumps({"final_url": original_url}), encoding="utf-8"
            )

            result = repair_cross_path_canonicals(run_dir)

            repaired_page = json.loads(
                (run_dir / "normalized" / "pages.jsonl").read_text(encoding="utf-8")
            )
            saved_manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(1, result["pages_repaired"])
            self.assertEqual(original_url, repaired_page["url"])
            self.assertEqual("cross_path_canonical_repair_v1", saved_manifest["normalization_repairs"][0]["version"])

    def test_blog_under_resource_center_is_still_bulk_content(self):
        seed = "https://example.com/"
        self.assertGreater(
            _crawl_priority("https://example.com/resource-center/blog/old-post", seed),
            _crawl_priority("https://example.com/resource-center/guides/report", seed),
        )

    def test_collects_sitemap_and_link_pages_with_separate_artifacts(self):
        responses = {
            "https://example.com/robots.txt": {"body": b"User-agent: *\nDisallow: /private/\nSitemap: https://example.com/sitemap.xml\n", "content_type": "text/plain"},
            "https://example.com/sitemap.xml": {"body": b'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://example.com/</loc></url><url><loc>https://example.com/resources/report/</loc></url></urlset>', "content_type": "application/xml"},
            "https://example.com/": {"body": self.fixture("home.html")},
            "https://example.com/resources/report": {"body": self.fixture("report.html")},
        }
        with tempfile.TemporaryDirectory() as directory:
            manifest, pages, run_dir = collect_website(
                "example.com", output_root=Path(directory), maximum_pages=10,
                delay_seconds=0, fetcher=FixtureFetcher(responses),
            )
            self.assertEqual(2, len(pages))
            self.assertEqual("completed", manifest.status)
            self.assertEqual(1, manifest.robots_disallowed_count)
            self.assertEqual("https://www.example.com/", pages[0].url)
            self.assertEqual(["email", "company"], pages[1].forms[0]["fields"])
            self.assertEqual("Download report", pages[1].forms[0]["submit_text"])
            self.assertTrue((run_dir / "manifest.json").exists())
            self.assertEqual(2, len((run_dir / "normalized" / "pages.jsonl").read_text().splitlines()))
            self.assertEqual(3, len((run_dir / "normalized" / "discovered_urls.jsonl").read_text().splitlines()))
            self.assertGreaterEqual(len(list((run_dir / "raw").glob("*.body"))), 4)

    def test_provider_failure_is_partial_not_negative_evidence(self):
        responses = {
            "https://example.com/robots.txt": RuntimeError("provider unavailable"),
            "https://example.com/sitemap.xml": RuntimeError("provider unavailable"),
            "https://example.com/": {"body": self.fixture("home.html")},
            "https://example.com/resources/report": RuntimeError("blocked"),
        }
        with tempfile.TemporaryDirectory() as directory:
            manifest, pages, run_dir = collect_website(
                "example.com", output_root=Path(directory), maximum_pages=10,
                delay_seconds=0, fetcher=FixtureFetcher(responses),
            )
            self.assertEqual(1, len(pages))
            self.assertEqual("partial", manifest.status)
            self.assertTrue(manifest.incomplete)
            saved = json.loads((run_dir / "manifest.json").read_text())
            self.assertEqual(4, len(saved["errors"]))

    def test_low_budget_prioritizes_proof_over_bulk_blog_pages(self):
        sitemap = b'''<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://example.com/category/customer-profiling</loc></url>
          <url><loc>https://example.com/blog/old-post</loc></url>
          <url><loc>https://example.com/customers/proof</loc></url>
        </urlset>'''
        responses = {
            "https://example.com/robots.txt": {"body": b"", "content_type": "text/plain"},
            "https://example.com/sitemap.xml": {"body": sitemap, "content_type": "application/xml"},
            "https://example.com/": {"body": b"<html><title>Home</title></html>"},
            "https://example.com/customers/proof": {"body": b"<html><title>Customer proof</title></html>"},
        }
        with tempfile.TemporaryDirectory() as directory:
            _, pages, _ = collect_website(
                "example.com", output_root=Path(directory), maximum_pages=2,
                delay_seconds=0, fetcher=FixtureFetcher(responses),
            )
            self.assertEqual(
                ["https://example.com/", "https://example.com/customers/proof"],
                [page.url for page in pages],
            )


if __name__ == "__main__":
    unittest.main()
