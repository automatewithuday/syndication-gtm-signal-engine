import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gtm_signal_engine.job_collection import collect_deepline_jobs, replay_deepline_jobs


class FixtureRunner:
    def __init__(self):
        self.calls = []

    def run(self, arguments):
        self.calls.append(list(arguments))
        tool_id = arguments[2]
        if arguments[1] == "describe":
            payload = {"toolId": tool_id, "callable": True, "connected": True}
        elif tool_id == "harvestapi_search_jobs":
            payload = {"status": "completed", "toolResponse": {"raw": {"elements": [
                {
                    "id": "li-1", "title": "Demand Generation Manager",
                    "url": "https://www.linkedin.com/jobs/view/li-1",
                    "postedDate": "2026-09-10T00:00:00Z",
                    "company": {"name": "Example", "linkedinUrl": "https://linkedin.com/company/example"},
                    "location": {"linkedinText": "Remote"},
                },
                {
                    "id": "li-2", "title": "Backend Engineer",
                    "url": "https://www.linkedin.com/jobs/view/li-2",
                    "company": {"name": "Example"},
                },
                {
                    "id": "li-3", "title": "GTM Engineer",
                    "url": "https://www.linkedin.com/jobs/view/li-3",
                    "company": {"name": "Example"},
                },
            ]}}}
        else:
            payload = {"status": "completed", "toolResponse": {"raw": {"data": [
                {
                    "job_id": "g-1", "job_title": "Paid Media Lead",
                    "employer_name": "Example", "employer_website": "https://example.com",
                    "job_apply_link": "https://jobs.example-board.com/g-1",
                    "job_posted_at_datetime_utc": "2026-09-09T00:00:00Z",
                },
                {
                    "job_id": "g-2", "job_title": "Growth Marketing Manager",
                    "employer_name": "Different Company", "employer_website": "https://different.example",
                    "job_apply_link": "https://jobs.example-board.com/g-2",
                },
            ]}}}
        return subprocess.CompletedProcess(arguments, 0, stdout=json.dumps(payload), stderr="")


class JobCollectionTests(unittest.TestCase):
    def test_collects_linkedin_and_google_jobs_with_strict_account_attribution(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            (run_dir / "normalized").mkdir()
            (run_dir / "manifest.json").write_text(json.dumps({
                "run_id": "run", "seed_url": "https://example.com/",
                "provider": "ScraplingFetcher",
            }))
            runner = FixtureRunner()
            result = collect_deepline_jobs(
                run_dir, "example.com", account_name="Example",
                linkedin_company_id="123", runner=runner,
            )
            self.assertFalse(result.incomplete)
            self.assertEqual(3, len(result.records))
            self.assertEqual({"linkedin_jobs", "google_jobs"}, {item["source"] for item in result.records})
            self.assertEqual(
                {"demand_generation", "gtm_engineering"},
                {item["role_family"] for item in result.records},
            )
            self.assertTrue(all(item["provider_response_sha256"] for item in result.records))
            status = json.loads((run_dir / "normalized/job_collection.json").read_text())
            self.assertEqual("completed", status["status"])
            self.assertEqual(1, status["sources"]["google_jobs"]["normalized_records"])
            replayed = replay_deepline_jobs(
                run_dir, "example.com", account_name="Example", linkedin_company_id="123"
            )
            self.assertEqual(3, len(replayed.records))
            self.assertFalse(replayed.incomplete)

    def test_linkedin_without_company_id_requires_exact_company_name(self):
        records = [{
            "id": "wrong", "title": "Demand Generation Manager",
            "url": "https://www.linkedin.com/jobs/view/wrong",
            "company": {"name": "Different Company"},
        }]
        from gtm_signal_engine.job_collection import _normalize_linkedin
        self.assertEqual([], _normalize_linkedin(
            records, account_name="Example", domain="example.com", company_id=None,
            observed_at="2026-09-13T00:00:00Z", response_sha256="a" * 64,
        ))

    def test_collection_skips_linkedin_without_authoritative_company_id(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            (run_dir / "normalized").mkdir()
            (run_dir / "manifest.json").write_text(json.dumps({
                "run_id": "run", "seed_url": "https://example.com/",
                "provider": "ScraplingFetcher",
            }))
            runner = FixtureRunner()
            result = collect_deepline_jobs(
                run_dir, "example.com", account_name="Example",
                sources=("linkedin_jobs",), runner=runner,
            )
            self.assertTrue(result.incomplete)
            self.assertEqual([], result.records)
            self.assertFalse(any(call[1] == "execute" for call in runner.calls))

    def test_incremental_linkedin_collection_preserves_saved_google_jobs(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            normalized = run_dir / "normalized"
            normalized.mkdir()
            (run_dir / "manifest.json").write_text(json.dumps({
                "run_id": "run", "seed_url": "https://example.com/",
                "provider": "ScraplingFetcher",
            }))
            (normalized / "job_collection.json").write_text(json.dumps({
                "sources": {"google_jobs": {"status": "completed"}}
            }))
            google_record = {
                "source": "google_jobs", "provider_record_id": "saved-google",
                "title": "Paid Media Lead",
            }
            (normalized / "job_postings.jsonl").write_text(json.dumps(google_record) + "\n")

            result = collect_deepline_jobs(
                run_dir, "example.com", account_name="Example",
                linkedin_company_id="123", sources=("linkedin_jobs",),
                runner=FixtureRunner(),
            )

            self.assertFalse(result.incomplete)
            self.assertEqual(3, len(result.records))
            self.assertIn(google_record, result.records)
            status = json.loads((normalized / "job_collection.json").read_text())
            self.assertTrue(status["incremental_update"])
            self.assertEqual({"google_jobs", "linkedin_jobs"}, set(status["sources"]))


if __name__ == "__main__":
    unittest.main()
