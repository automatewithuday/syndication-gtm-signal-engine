import hashlib
import json
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gtm_signal_engine.asset_analysis import analyze_asset_page, analyze_asset_run
from gtm_signal_engine.models import Page


class AssetAnalysisTests(unittest.TestCase):
    def test_structured_publication_date_and_substantial_case_study(self):
        page = Page(
            url="https://example.com/case-studies/acme",
            title="Acme reduced turnover by 46%",
            main_text=("Acme documented a 46% reduction in turnover with named outcomes. " * 40),
            metadata={"article:published_time": "2026-08-01T10:00:00Z"},
            observed_at="2026-09-10T10:00:00Z",
        )
        result = analyze_asset_page(page)
        self.assertIsNotNone(result)
        self.assertEqual("meta.article:published_time", result.published_or_created.source)
        self.assertEqual("within_90_days", result.recency_bucket)
        self.assertEqual("yes", result.substantial)
        self.assertEqual("suitable", result.syndication_suitability)

    def test_batch_sitemap_date_is_not_treated_as_publication(self):
        page = Page(
            url="https://example.com/guides/one",
            title="A practical guide",
            main_text="Detailed steps and examples. " * 100,
            observed_at="2026-09-10T10:00:00Z",
        )
        result = analyze_asset_page(
            page,
            sitemap_lastmod="2026-09-09T22:51:36Z",
            sitemap_is_batch_like=True,
        )
        self.assertIsNone(result.published_or_created)
        self.assertIsNone(result.modified)
        self.assertEqual("unknown", result.recency_bucket)
        self.assertTrue(any("batch deployment" in risk for risk in result.risks))

    def test_run_uses_single_embedded_created_at_and_writes_versioned_outputs(self):
        body = b'''<html><head><title>Pipeline Guide</title></head><body><main>
        <h1>Pipeline Guide</h1><p>''' + (b"A detailed pipeline workflow with examples and implementation notes. " * 80) + b'''</p>
        </main><form><input name="email" type="email"><button>Get the guide</button></form>
        <script>self.__data="createdAt\\\":\\\"2026-08-01T10:00:00.000Z\\\",\\\"updatedAt\\\":\\\"2026-08-02T10:00:00.000Z"</script>
        </body></html>'''
        page = Page(
            url="https://example.com/guides/pipeline",
            original_url="https://example.com/guides/pipeline",
            title="Pipeline Guide",
            text="Pipeline Guide",
            observed_at="2026-09-10T10:00:00+00:00",
            content_hash=hashlib.sha256(body).hexdigest(),
        )
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            normalized = run_dir / "normalized"
            raw = run_dir / "raw"
            normalized.mkdir()
            raw.mkdir()
            (normalized / "pages.jsonl").write_text(json.dumps(asdict(page)) + "\n")
            key = "document"
            (raw / f"{key}.body").write_bytes(body)
            (raw / f"{key}.json").write_text(json.dumps({
                "requested_url": page.url,
                "final_url": page.url,
                "status_code": 200,
                "headers": {"content-type": "text/html; charset=utf-8"},
                "observed_at": page.observed_at,
                "body_file": f"{key}.body",
                "body_sha256": hashlib.sha256(body).hexdigest(),
            }))

            summary = analyze_asset_run(run_dir)

            self.assertEqual(1, summary["asset_count"])
            self.assertEqual(1, summary["dated_asset_count"])
            self.assertEqual("completed", summary["status"])
            saved = json.loads((normalized / "assets.jsonl").read_text())
            self.assertEqual("embedded_application_state.createdAt", saved["published_or_created"]["source"])
            self.assertEqual("asset_rules_v1", saved["extractor_version"])
            self.assertGreater(len(saved["substance_reasons"]), 0)


if __name__ == "__main__":
    unittest.main()
