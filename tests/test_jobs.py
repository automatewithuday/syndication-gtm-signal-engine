import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gtm_signal_engine.jobs import enqueue_batch, list_jobs, run_job
from gtm_signal_engine.review_queue import connect_database


class JobTests(unittest.TestCase):
    def test_batch_enqueue_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batch = root / "accounts.jsonl"
            batch.write_text(json.dumps({
                "domain": "example.com", "account_name": "Example", "maximum_pages": 5,
                "gap_evidence_pages": 6, "gap_evidence_targets": 12,
                "gap_evidence_depth": 3, "retry_gap_evidence": True,
            }) + "\n")
            database = root / "jobs.sqlite3"
            first = enqueue_batch(batch, database)
            second = enqueue_batch(batch, database)
            self.assertEqual(1, first["inserted"])
            self.assertEqual(1, second["existing"])
            jobs = list_jobs(database)
            self.assertEqual(1, len(jobs))
            self.assertEqual(6, jobs[0]["request"]["gap_evidence_pages"])
            self.assertEqual(12, jobs[0]["request"]["gap_evidence_targets"])
            self.assertEqual(3, jobs[0]["request"]["gap_evidence_depth"])
            self.assertTrue(jobs[0]["request"]["retry_gap_evidence"])
            self.assertEqual("account_job_v2", jobs[0]["request"]["request_version"])
            self.assertEqual("account_pipeline_v2", jobs[0]["request"]["pipeline_version"])

    def test_batch_rejects_ambiguous_boolean_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batch = root / "accounts.jsonl"
            batch.write_text(
                '{"domain":"example.com","retry_gap_evidence":"sometimes"}\n'
            )

            with self.assertRaisesRegex(ValueError, "retry_gap_evidence must be"):
                enqueue_batch(batch, root / "jobs.sqlite3")

    def test_job_records_partial_run_and_skips_only_completed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batch = root / "accounts.csv"
            batch.write_text("domain,account_name,maximum_pages\nexample.com,Example,5\n")
            database = root / "jobs.sqlite3"
            job_id = enqueue_batch(batch, database)["job_ids"][0]

            def runner(domain, **kwargs):
                kwargs["output_path"].parent.mkdir(parents=True, exist_ok=True)
                kwargs["output_path"].write_text("{}")
                return {
                    "run": {"status": "partial", "provider_cost_usd": 0},
                    "run_dir": str(root / "saved-run"),
                }

            result = run_job(
                job_id, database_path=database, output_root=root / "runs",
                report_root=root / "reports", runner=runner,
            )
            self.assertEqual("partial", result["status"])
            saved = list_jobs(database)[0]
            self.assertEqual(1, saved["attempts"])
            self.assertEqual(0, saved["provider_cost_usd"])

    def test_completed_job_is_not_run_twice(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batch = root / "accounts.jsonl"
            batch.write_text('{"domain":"example.com"}\n')
            database = root / "jobs.sqlite3"
            job_id = enqueue_batch(batch, database)["job_ids"][0]
            calls = []

            def runner(domain, **kwargs):
                calls.append(domain)
                return {"run": {"status": "completed"}, "run_dir": str(root / "run")}

            first = run_job(job_id, database_path=database, report_root=root / "reports", runner=runner)
            second = run_job(job_id, database_path=database, report_root=root / "reports", runner=runner)
            self.assertEqual("completed", first["status"])
            self.assertTrue(second["skipped"])
            self.assertEqual(["example.com"], calls)

    def test_full_pipeline_checkpoints_stages_in_sqlite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batch = root / "accounts.jsonl"
            batch.write_text(json.dumps({
                "domain": "example.com", "gap_evidence_pages": 4,
                "gap_evidence_targets": 8, "gap_evidence_depth": 3,
                "retry_gap_evidence": True,
            }) + "\n")
            database = root / "jobs.sqlite3"
            job_id = enqueue_batch(batch, database)["job_ids"][0]

            def pipeline(domain, **kwargs):
                self.assertEqual(4, kwargs["gap_evidence_pages"])
                self.assertEqual(8, kwargs["gap_evidence_targets"])
                self.assertEqual(3, kwargs["gap_evidence_depth"])
                self.assertTrue(kwargs["retry_gap_evidence"])
                kwargs["stage_callback"]("builtwith", "completed", {"records": 3})
                kwargs["stage_callback"]("adyntel", "partial", {"platforms": {"meta": "partial"}})
                return {
                    "pipeline": {"status": "completed"},
                    "run": {"run_dir": str(root / "run")},
                    "provider_cost": {"usd": 0.053},
                }

            with patch("gtm_signal_engine.jobs.run_account_v1", side_effect=pipeline):
                result = run_job(job_id, database_path=database, report_root=root / "reports")
            self.assertEqual("completed", result["status"])
            with connect_database(database) as connection:
                rows = connection.execute(
                    "SELECT stage, status, detail_json FROM analysis_job_stages WHERE job_id = ? ORDER BY stage",
                    (job_id,),
                ).fetchall()
            self.assertEqual([("adyntel", "partial"), ("builtwith", "completed")], [
                (row["stage"], row["status"]) for row in rows
            ])
            self.assertEqual(3, json.loads(rows[1]["detail_json"])["records"])


if __name__ == "__main__":
    unittest.main()
