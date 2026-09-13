import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gtm_signal_engine.jobs import enqueue_batch
from gtm_signal_engine.portfolio_report import build_portfolio_report
from gtm_signal_engine.review_queue import connect_database


class PortfolioReportTests(unittest.TestCase):
    def test_report_ranks_known_scores_and_preserves_unavailable_accounts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batch = root / "accounts.jsonl"
            batch.write_text("\n".join([
                json.dumps({"domain": "low.example", "account_name": "Low"}),
                json.dumps({"domain": "high.example", "account_name": "High"}),
                json.dumps({"domain": "unknown.example", "account_name": "Unknown"}),
            ]) + "\n")
            database = root / "jobs.sqlite3"
            jobs = enqueue_batch(batch, database)
            by_domain = {
                item["account_domain"]: item
                for item in _jobs(database)
            }
            for domain, score, opportunity in (
                ("low.example", 55.0, "insufficient_evidence"),
                ("high.example", 91.0, "qualified"),
            ):
                report_path = root / f"{domain}.json"
                report_path.write_text(json.dumps({
                    "unified_account_score": {
                        "priority": {
                            "score": score, "status": "high_priority",
                            "evidence_coverage": 0.8, "confidence": 0.7,
                        },
                        "qualification": {"opportunity_status": opportunity},
                        "channels": {
                            "content_syndication": {
                                "status": opportunity, "total": 75 if opportunity == "qualified" else None,
                                "components": {"gap": {"status": "provisional_pass" if opportunity == "qualified" else "insufficient_evidence"}},
                            }
                        },
                    },
                    "blockers": [] if opportunity == "qualified" else ["gap unknown"],
                }))
                with connect_database(database) as connection:
                    connection.execute(
                        "UPDATE analysis_jobs SET status='completed', report_path=?, provider_cost_usd=? WHERE job_id=?",
                        (str(report_path), score / 1000, by_domain[domain]["job_id"]),
                    )

            result = build_portfolio_report(
                database_path=database, output_path=root / "portfolio.json"
            )

            self.assertEqual(3, result["account_count"])
            self.assertEqual(3, result["job_count"])
            self.assertEqual(2, result["ranked_count"])
            self.assertEqual(1, result["qualified_count"])
            self.assertEqual(
                ["high.example", "low.example", "unknown.example"],
                [item["domain"] for item in result["accounts"]],
            )
            self.assertEqual("unavailable", result["accounts"][2]["report_status"])
            with Path(result["outputs"]["csv"]).open(newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual("1", rows[0]["rank"])
            self.assertEqual("", rows[2]["rank"])
            self.assertTrue(Path(result["outputs"]["markdown"]).is_file())

    def test_latest_job_policy_is_the_current_account_row(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_batch = root / "first.jsonl"
            second_batch = root / "second.jsonl"
            first_batch.write_text('{"domain":"example.com","gap_evidence_pages":0}\n')
            second_batch.write_text('{"domain":"example.com","gap_evidence_pages":5}\n')
            database = root / "jobs.sqlite3"
            first_id = enqueue_batch(first_batch, database)["job_ids"][0]
            second_id = enqueue_batch(second_batch, database)["job_ids"][0]
            with connect_database(database) as connection:
                connection.execute(
                    "UPDATE analysis_jobs SET updated_at='2026-09-13T00:00:00Z' WHERE job_id=?",
                    (first_id,),
                )
                connection.execute(
                    "UPDATE analysis_jobs SET updated_at='2026-09-13T01:00:00Z' WHERE job_id=?",
                    (second_id,),
                )

            result = build_portfolio_report(
                database_path=database, output_path=root / "portfolio.json"
            )

            self.assertEqual(2, result["job_count"])
            self.assertEqual(1, result["account_count"])
            self.assertEqual(second_id, result["accounts"][0]["job_id"])
            self.assertEqual(2, result["accounts"][0]["job_history_count"])

    def test_snapshot_is_stable_across_generation_time(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batch = root / "accounts.jsonl"
            batch.write_text('{"domain":"example.com"}\n')
            database = root / "jobs.sqlite3"
            enqueue_batch(batch, database)

            first = build_portfolio_report(
                database_path=database, output_path=root / "first.json"
            )
            second = build_portfolio_report(
                database_path=database, output_path=root / "second.json"
            )

            self.assertEqual(first["snapshot_id"], second["snapshot_id"])


def _jobs(database: Path):
    with connect_database(database) as connection:
        return connection.execute("SELECT * FROM analysis_jobs").fetchall()


if __name__ == "__main__":
    unittest.main()
