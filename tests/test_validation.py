import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gtm_signal_engine.validation import (
    create_outreach_snapshot,
    import_outcomes,
    outcome_metrics,
    record_send,
    review_classification,
    signal_outcome_metrics,
)
from gtm_signal_engine.review_queue import connect_database


class ValidationTests(unittest.TestCase):
    def make_run(self, root: Path) -> Path:
        run = root / "run"
        (run / "normalized").mkdir(parents=True)
        (run / "manifest.json").write_text(json.dumps({
            "run_id": "run-1", "seed_url": "https://example.com/", "provider": "ScraplingFetcher"
        }))
        (run / "normalized/pages.jsonl").write_text(json.dumps({
            "url": "https://example.com/guide", "content_hash": "a" * 64,
            "observed_at": "2026-09-11T00:00:00+00:00",
        }) + "\n")
        score = {
            "snapshot_id": "snapshot-1", "channel": "content_syndication",
            "scoring_version": "v1", "components": {},
        }
        review = {
            "account": {"name": "Example", "domain": "example.com"},
            "run": {"run_id": "run-1"}, "overall": {"snapshot_id": "snapshot-1"},
            "signals": {
                "fit": [{"signal": "b2b_business_model"}],
                "readiness": [{"signal": "customer_proof"}],
                "gap": [],
                "reviewed_initiatives": [{"signal_type": "public_campaign_launch"}],
            },
        }
        (run / "normalized/syndication_score.json").write_text(json.dumps(score))
        (run / "normalized/account_review.json").write_text(json.dumps(review))
        return run

    def test_corrected_classification_is_bound_to_saved_page(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = review_classification(
                self.make_run(root), url="https://example.com/guide", content_sha256="a" * 64,
                signal_type="page_family", original_value="unknown", decision="correct",
                corrected_value="guide", reviewer="analyst", notes="Detail page contains a guide.",
                database_path=root / "db.sqlite3",
            )
            self.assertEqual("correct", result["decision"])

    def test_snapshot_send_outcomes_and_metrics_are_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "db.sqlite3"
            snapshot = create_outreach_snapshot(self.make_run(root), database_path=database)
            send = record_send(
                snapshot["snapshot_id"], contact_ref="crm:contact-1",
                sent_at="2026-09-11T01:00:00+00:00", database_path=database,
            )
            outcomes = root / "outcomes.jsonl"
            outcomes.write_text("\n".join([
                json.dumps({"send_id": send["send_id"], "event_type": "reply", "occurred_at": "2026-09-12T00:00:00+00:00"}),
                json.dumps({"send_id": send["send_id"], "event_type": "meeting", "occurred_at": "2026-09-13T00:00:00+00:00"}),
            ]) + "\n")
            first = import_outcomes(outcomes, database)
            second = import_outcomes(outcomes, database)
            metrics = outcome_metrics(database)
            self.assertEqual(2, first["inserted"])
            self.assertEqual(2, second["duplicates"])
            self.assertEqual(1.0, metrics[0]["reply_rate"])
            self.assertEqual(1.0, metrics[0]["meeting_rate"])
            self.assertEqual(0.0, metrics[0]["opportunity_rate"])
            by_signal = signal_outcome_metrics(database)
            self.assertEqual(3, len(by_signal))
            self.assertTrue(all(item["meeting_rate"] == 1.0 for item in by_signal))

    def test_qualified_outbound_snapshot_is_frozen_by_channel(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = self.make_run(root)
            database = root / "db.sqlite3"
            components = {
                key: {"score": 80, "confidence": 0.8, "evidence": []}
                for key in ("fit", "readiness", "gap", "trigger")
            }
            components["readiness"]["factors"] = [{
                "id": "sales_motion", "state": "observed",
                "observed": "enterprise", "confidence": 0.9,
                "source": "normalized/account_fit.json",
            }]
            (run / "normalized/unified_account_score.json").write_text(json.dumps({
                "snapshot_id": "outbound-snapshot", "scoring_version": "unified_account_v1",
                "account": {"name": "Example", "domain": "example.com"},
                "input": {"run_id": "run-1"},
                "channels": {"outbound_calling": {
                    "status": "qualified", "components": components,
                }},
            }))

            result = create_outreach_snapshot(
                run, database_path=database, channel="outbound_calling",
            )

            self.assertEqual("outbound_calling", result["channel"])
            self.assertEqual("outbound-snapshot", result["snapshot_id"])
            with connect_database(database) as connection:
                frozen = json.loads(connection.execute(
                    "SELECT evidence_json FROM outreach_snapshots WHERE snapshot_id = ?",
                    (result["snapshot_id"],),
                ).fetchone()[0])
            self.assertEqual("sales_motion", frozen["readiness"][0]["signal"])

    def test_unqualified_outbound_snapshot_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = self.make_run(root)
            (run / "normalized/unified_account_score.json").write_text(json.dumps({
                "channels": {"outbound_calling": {"status": "insufficient_evidence"}},
            }))
            with self.assertRaisesRegex(ValueError, "requires a qualified"):
                create_outreach_snapshot(
                    run, database_path=root / "db.sqlite3",
                    channel="outbound_calling",
                )


if __name__ == "__main__":
    unittest.main()
