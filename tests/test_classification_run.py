import json
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gtm_signal_engine.classification_run import classify_crawl_run
from gtm_signal_engine.models import Page


class ClassificationRunTests(unittest.TestCase):
    def test_writes_versioned_evidence_and_summary(self):
        page = Page(
            url="https://example.com/case-studies/acme",
            title="How Acme improved retention",
            text="A complete customer story with quantified results. " * 20,
            observed_at="2026-09-10T00:00:00+00:00",
            forms=[{
                "method": "post",
                "fields": ["email"],
                "field_details": [{"name": "email", "type": "email", "placeholder": "Inbox"}],
                "submit_text": "Subscribe",
            }],
        )
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            normalized = run_dir / "normalized"
            normalized.mkdir()
            (normalized / "pages.jsonl").write_text(json.dumps(asdict(page)) + "\n")

            summary = classify_crawl_run(run_dir)

            self.assertEqual({"case_study": 1}, summary["page_families"])
            self.assertEqual({"fully_ungated": 1}, summary["gating_types"])
            self.assertEqual({"newsletter": 1}, summary["form_purposes"])
            evidence = [json.loads(line) for line in (normalized / "evidence.jsonl").read_text().splitlines()]
            self.assertTrue(all(item["extractor_version"] == "page_rules_v1" for item in evidence))
            self.assertTrue(all(item["observed_at"] == page.observed_at for item in evidence))


if __name__ == "__main__":
    unittest.main()
