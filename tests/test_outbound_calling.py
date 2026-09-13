import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gtm_signal_engine.outbound_calling import (
    discover_outbound_gap_candidates,
    export_outbound_gap_profile,
    ingest_outbound_gap_candidates,
    list_outbound_gap_candidates,
    review_outbound_gap_candidate,
    score_outbound_calling_run,
)


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class OutboundCallingTests(unittest.TestCase):
    def _seed(self, root: Path, *, include_gap: bool = True) -> Path:
        run = root / "run"
        normalized = run / "normalized"
        text = (
            "We plan to expand cold calling this quarter. "
            "Our manual cold calling workflow is a bottleneck."
            if include_gap else
            "We help revenue teams understand their market."
        )
        _write(run / "manifest.json", {
            "run_id": "outbound-run", "provider": "ScraplingFetcher",
            "seed_url": "https://example.com/",
        })
        _write(normalized / "pages.jsonl", {
            "url": "https://example.com/news/sales-expansion",
            "text": text, "main_text": text, "links": [],
            "content_hash": "a" * 64,
            "observed_at": "2026-09-14T00:00:00Z",
        })
        evidence = [
            {
                "signal_type": "conversion_path", "value": "demo",
                "url": "https://example.com/demo", "confidence": 0.9,
            },
            {
                "signal_type": "conversion_path", "value": "contact_sales",
                "url": "https://example.com/contact", "confidence": 0.9,
            },
        ]
        (normalized / "evidence.jsonl").write_text(
            "\n".join(json.dumps(item) for item in evidence) + "\n",
            encoding="utf-8",
        )
        _write(normalized / "asset_summary.json", {
            "asset_types": {"case_study": 5},
        })
        factors = []
        for factor_id, maximum, observed in (
            ("professional_buyer_coverage", 25, ["marketing", "sales"]),
            ("sales_motion", 25, "enterprise"),
            ("operating_scale", 20, "enterprise"),
        ):
            factors.append({
                "id": factor_id, "state": "confirmed", "observed": observed,
                "points": maximum, "maximum_points": maximum,
                "evidence": [{"confidence": 0.9, "url": "https://example.com/about"}],
            })
        _write(normalized / "account_fit.json", {
            "snapshot_id": "fit", "component": {
                "score": 90, "confidence": 0.9,
                "state": "observed", "status": "provisional_pass",
                "factors": factors, "evidence": [],
            },
        })
        _write(normalized / "business_trigger.json", {
            "snapshot_id": "trigger", "component": {
                "score": 80, "confidence": 0.85,
                "state": "observed", "status": "provisional_pass",
                "evidence": [],
            },
        })
        return run

    def test_reviewed_exact_run_evidence_can_qualify_outbound(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = self._seed(root)
            database = root / "review.sqlite3"

            discovery = discover_outbound_gap_candidates(run)
            self.assertEqual(2, discovery["candidate_count"])
            first_ingest = ingest_outbound_gap_candidates(run, database)
            second_ingest = ingest_outbound_gap_candidates(run, database)
            self.assertEqual(2, first_ingest["inserted"])
            self.assertEqual(2, second_ingest["seen_again"])
            for candidate in list_outbound_gap_candidates(database):
                review_outbound_gap_candidate(
                    candidate["candidate_id"], decision="approve",
                    reviewer="analyst", notes="Claim describes the account's current motion.",
                    strength="confirmed", confidence=0.9,
                    database_path=database,
                )
            exported = export_outbound_gap_profile(
                run, account_name="Example", database_path=database,
            )
            score = score_outbound_calling_run(run, Path(exported["output"]))

            self.assertEqual(2, exported["approved_observations"])
            self.assertEqual("provisional_pass", score["components"]["gap"]["status"])
            self.assertEqual("provisional_pass", score["components"]["readiness"]["status"])
            self.assertEqual("qualified", score["qualification"]["opportunity_status"])
            self.assertIsNotNone(score["total"])

    def test_no_candidate_stays_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = self._seed(root, include_gap=False)
            database = root / "review.sqlite3"

            discovery = discover_outbound_gap_candidates(run)
            ingest_outbound_gap_candidates(run, database)
            profile = export_outbound_gap_profile(
                run, account_name="Example", database_path=database,
            )
            score = score_outbound_calling_run(run, Path(profile["output"]))

            self.assertEqual(0, discovery["candidate_count"])
            self.assertIsNone(score["components"]["gap"]["score"])
            self.assertEqual("insufficient_evidence", score["components"]["gap"]["status"])
            self.assertIsNone(score["total"])

    def test_changed_page_cannot_inherit_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = self._seed(root)
            database = root / "review.sqlite3"
            discover_outbound_gap_candidates(run)
            ingest_outbound_gap_candidates(run, database)
            candidate = list_outbound_gap_candidates(database)[0]
            review_outbound_gap_candidate(
                candidate["candidate_id"], decision="approve", reviewer="analyst",
                notes="Verified.", strength="confirmed", confidence=0.9,
                database_path=database,
            )
            page_path = run / "normalized" / "pages.jsonl"
            page = json.loads(page_path.read_text())
            page["content_hash"] = "b" * 64
            _write(page_path, page)

            with self.assertRaisesRegex(ValueError, "no longer binds"):
                export_outbound_gap_profile(
                    run, account_name="Example", database_path=database,
                )

    def test_standalone_profile_must_bind_to_saved_page(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = self._seed(root)
            profile = run / "normalized" / "outbound_gap_profile.json"
            _write(profile, {
                "account": {"name": "Example", "domain": "example.com"},
                "channel": "outbound_calling",
                "observations": [{
                    "channel": "outbound_calling",
                    "position": "supports_gap",
                    "signal_type": "explicit_expansion_intent",
                    "strength": "confirmed", "confidence": 0.9,
                    "url": "https://example.com/news/sales-expansion",
                    "excerpt": "invented claim not present on the saved page",
                    "observed_at": "2026-09-14T00:00:00Z",
                    "method": "scrapling_saved_page",
                    "content_sha256": "a" * 64,
                    "review_status": "approved",
                }],
            })

            with self.assertRaisesRegex(ValueError, "does not match"):
                score_outbound_calling_run(run, profile)

    def test_processing_timestamp_does_not_change_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = self._seed(root, include_gap=False)
            database = root / "review.sqlite3"
            discover_outbound_gap_candidates(run)
            ingest_outbound_gap_candidates(run, database)
            profile = export_outbound_gap_profile(
                run, account_name="Example", database_path=database,
            )
            first = score_outbound_calling_run(run, Path(profile["output"]))
            fit_path = run / "normalized" / "account_fit.json"
            fit = json.loads(fit_path.read_text())
            fit["scored_at"] = "2099-01-01T00:00:00Z"
            _write(fit_path, fit)
            trigger_path = run / "normalized" / "business_trigger.json"
            trigger = json.loads(trigger_path.read_text())
            trigger["scored_at"] = "2099-01-01T00:00:00Z"
            _write(trigger_path, trigger)

            second = score_outbound_calling_run(run, Path(profile["output"]))

            self.assertEqual(first["snapshot_id"], second["snapshot_id"])

    def test_unknown_readiness_factors_are_not_scored_as_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = self._seed(root, include_gap=False)
            (run / "normalized" / "account_fit.json").unlink()
            (run / "normalized" / "evidence.jsonl").unlink()
            (run / "normalized" / "asset_summary.json").unlink()
            database = root / "review.sqlite3"
            discover_outbound_gap_candidates(run)
            ingest_outbound_gap_candidates(run, database)
            profile = export_outbound_gap_profile(
                run, account_name="Example", database_path=database,
            )

            score = score_outbound_calling_run(run, Path(profile["output"]))

            self.assertIsNone(score["components"]["readiness"]["score"])
            self.assertEqual("unknown", score["components"]["readiness"]["state"])

    def test_documented_outbound_success_disqualifies_gap(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = self._seed(root, include_gap=False)
            page_path = run / "normalized" / "pages.jsonl"
            page = json.loads(page_path.read_text())
            page["text"] = page["main_text"] = (
                "Our cold calling generated qualified pipeline and booked meetings."
            )
            _write(page_path, page)
            database = root / "review.sqlite3"
            discovery = discover_outbound_gap_candidates(run)
            ingest_outbound_gap_candidates(run, database)
            self.assertEqual(1, discovery["candidate_count"])
            candidate = list_outbound_gap_candidates(database)[0]
            self.assertEqual("contradicts_gap", candidate["suggested_position"])
            review_outbound_gap_candidate(
                candidate["candidate_id"], decision="approve", reviewer="analyst",
                notes="This is the account's own current success claim.",
                strength="confirmed", confidence=0.9, database_path=database,
            )
            profile = export_outbound_gap_profile(
                run, account_name="Example", database_path=database,
            )

            score = score_outbound_calling_run(run, Path(profile["output"]))

            self.assertEqual("contradicted", score["components"]["gap"]["state"])
            self.assertEqual("disqualified", score["components"]["gap"]["status"])


if __name__ == "__main__":
    unittest.main()
