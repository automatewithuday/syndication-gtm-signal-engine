import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gtm_signal_engine.gap_workflow import resolve_channel_gaps
from gtm_signal_engine.paid_gap_review import review_paid_gap_candidate
from gtm_signal_engine.review_queue import connect_database, review_gap_candidate


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class GapWorkflowTests(unittest.TestCase):
    def _seed(self, root: Path) -> tuple[Path, Path]:
        run_dir = root / "run"
        normalized = run_dir / "normalized"
        database = root / "review.sqlite3"
        text = (
            "We plan to expand content distribution this quarter. "
            "Our manual content distribution process is a bottleneck. "
            "We plan to expand retargeting to re-engage site visitors. "
            "Our manual retargeting workflow is a bottleneck."
        )
        _write(run_dir / "manifest.json", {
            "run_id": "gap-run", "seed_url": "https://example.com/",
            "provider": "ScraplingFetcher",
        })
        _write(normalized / "company_enrichment.json", {
            "domain": "example.com", "name": "Example",
        })
        _write(normalized / "pages.jsonl", {
            "url": "https://example.com/news/expansion", "text": text,
            "main_text": text, "links": [], "content_hash": "a" * 64,
            "observed_at": "2026-09-13T00:00:00Z",
        })
        _write(normalized / "external_profile.json", {
            "schema_version": "1.0", "domain": "example.com",
            "technologies": [], "ads": [], "gap_observations": [],
        })
        with connect_database(database) as connection:
            connection.execute(
                """
                INSERT INTO accounts(
                    account_domain, canonical_name, website_url, enrichment_status,
                    funding_status, enrichment_version, profile_json,
                    field_provenance_json, created_at, updated_at, last_enriched_at
                ) VALUES (
                    'example.com', 'Example', 'https://example.com', 'partial',
                    'blocked_provider_unavailable', 'test', '{}', '{}',
                    '2026-09-13T00:00:00Z', '2026-09-13T00:00:00Z',
                    '2026-09-13T00:00:00Z'
                )
                """
            )
        return run_dir, database

    def _run(self, run_dir: Path, database: Path) -> dict:
        def content_score(_run_dir, profile_path, _config=None):
            observations = json.loads(profile_path.read_text())["observations"]
            status = "provisional_pass" if len(observations) >= 2 else "insufficient_evidence"
            return {"component": {
                "score": 65.0 if observations else None,
                "status": status, "confidence": 0.9 if observations else 0.0,
            }}

        def syndication_score(*_args, **_kwargs):
            gap = json.loads((run_dir / "normalized" / "reviewed_gap_profile.json").read_text())
            qualified = len(gap["observations"]) >= 2
            return {
                "total": 78.0 if qualified else None,
                "qualification": {"opportunity_status": "qualified" if qualified else "insufficient_evidence"},
            }

        def paid_score(_run_dir, profile_path, _config=None):
            observations = json.loads(profile_path.read_text())["gap_observations"]
            channels = {}
            for channel in ("retargeting", "programmatic"):
                selected = [item for item in observations if item["channel"] == channel]
                channels[channel] = {"gap": {
                    "score": 65.0 if len(selected) >= 2 else None,
                    "status": "provisional_pass" if len(selected) >= 2 else "insufficient_evidence",
                }}
            return {"channels": channels}

        def unified(*_args, **_kwargs):
            paid = paid_score(run_dir, run_dir / "normalized" / "external_profile.json")
            return {
                "snapshot_id": "unified-snapshot",
                "priority": {"score": 80, "status": "high_priority"},
                "qualification": {"opportunity_status": "insufficient_evidence"},
                "channels": {
                    channel: {
                        "total": 75.0 if detail["gap"]["status"] == "provisional_pass" else None,
                        "status": "qualified" if detail["gap"]["status"] == "provisional_pass" else "insufficient_evidence",
                    }
                    for channel, detail in paid["channels"].items()
                },
            }

        with patch("gtm_signal_engine.gap_workflow.score_channel_gap_run", side_effect=content_score), \
             patch("gtm_signal_engine.gap_workflow.score_syndication_run", side_effect=syndication_score), \
             patch("gtm_signal_engine.gap_workflow.score_paid_channel_run", side_effect=paid_score), \
             patch("gtm_signal_engine.gap_workflow.score_unified_account_run", side_effect=unified), \
             patch("gtm_signal_engine.gap_workflow.build_account_intelligence_report", return_value={
                 "outputs": {"json": "account.json", "markdown": "account.md"}
             }):
            return resolve_channel_gaps(run_dir, database_path=database)

    def test_ingests_review_queue_and_applies_only_approved_exact_run_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir, database = self._seed(Path(directory))

            first = self._run(run_dir, database)
            self.assertEqual("review_required", first["status"])
            self.assertEqual(4, first["review_counts"]["pending"])
            self.assertIsNone(first["channels"]["content_syndication"]["gap_score"])
            self.assertIsNone(first["channels"]["retargeting"]["gap_score"])

            for item in first["review_queue"]:
                review = review_gap_candidate if item["channel"] == "content_syndication" else review_paid_gap_candidate
                review(
                    item["candidate_id"], decision="approve", reviewer="tester",
                    notes="First-person account expansion evidence.",
                    strength="confirmed", confidence=0.9, database_path=database,
                )

            second = self._run(run_dir, database)
            self.assertEqual(4, second["review_counts"]["approved"])
            self.assertEqual("provisional_pass", second["channels"]["content_syndication"]["gap_status"])
            self.assertEqual("provisional_pass", second["channels"]["retargeting"]["gap_status"])
            self.assertEqual("insufficient_evidence", second["channels"]["programmatic"]["gap_status"])
            self.assertEqual("insufficient_evidence", second["status"])


if __name__ == "__main__":
    unittest.main()
