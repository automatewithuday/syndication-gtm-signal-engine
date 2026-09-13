import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gtm_signal_engine.review_queue import connect_database
from gtm_signal_engine.unified_scoring import score_unified_account_run


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _seed_account(database: Path, domain: str = "example.com") -> None:
    with connect_database(database) as connection:
        connection.execute(
            """
            INSERT INTO accounts(
                account_domain, canonical_name, website_url, enrichment_status,
                funding_status, enrichment_version, profile_json,
                field_provenance_json, created_at, updated_at, last_enriched_at
            ) VALUES (?, 'Example', 'https://example.com', 'partial',
                      'blocked_provider_unavailable', 'test', '{}', '{}',
                      '2026-09-01T00:00:00Z', '2026-09-01T00:00:00Z',
                      '2026-09-01T00:00:00Z')
            """,
            (domain,),
        )


def _seed_run(root: Path, *, domain: str = "example.com", include_job: bool = True) -> Path:
    run_dir = root / "run"
    normalized = run_dir / "normalized"
    _write(run_dir / "manifest.json", {
        "run_id": "run-1", "provider": "ScraplingFetcher",
        "seed_url": f"https://{domain}/", "status": "partial",
    })
    _write(normalized / "company_enrichment.json", {
        "domain": domain, "name": "Example", "last_enriched_at": "2026-09-01T00:00:00Z",
        "identifiers": {"linkedin_company_id": "123"},
        "firmographics": {
            "employee_count": 500, "employee_range": "201-500",
            "revenue_range": {"min": 50000000, "max": 100000000},
            "industry": "Software", "company_type": "Private",
        },
        "funding": {
            "status": "blocked_provider_unavailable",
            "required_provider": "crunchbase_via_deepline",
            "interpretation": "Crunchbase remains unresolved",
        },
        "field_provenance": {"firmographics": "prospeo_enrich_company"},
        "source_snapshots": [{"provider": "prospeo", "response_sha256": "a" * 64}],
    })
    _write(normalized / "account_fit.json", {
        "snapshot_id": "fit-snapshot",
        "component": {"score": 82, "confidence": 0.9, "status": "provisional_pass"},
    })
    _write(normalized / "business_trigger.json", {
        "snapshot_id": "trigger-snapshot",
        "component": {"score": None, "confidence": 0, "evidence": []},
    })
    _write(normalized / "ad_creative_analysis.json", {
        "snapshot_id": "creative-snapshot",
        "scoring_inputs": {
            "provider_total_ads": 120, "observed_platform_diversity": 2,
            "ads_inspected": 20, "analyzable_ads": 15,
            "observed_ad_platforms": ["linkedin", "google"],
        },
        "platforms": {
            "linkedin": {
                "provider_status": "partial", "ads_inspected": 10,
                "sample_confidence": "medium",
                "creative_activity_states": {"active": 5, "unknown": 5},
            },
            "google": {
                "provider_status": "partial", "ads_inspected": 10,
                "sample_confidence": "medium",
                "creative_activity_states": {"recently_observed": 10},
            },
        },
    })
    technology = {
        "state": "detected", "category": "Marketing Automation | Analytics",
        "confidence": 0.9, "technology": "Example Tech",
    }
    _write(normalized / "external_profile.json", {
        "domain": domain, "technologies": [technology] * 6,
        "ads": [], "gap_observations": [],
    })
    _write(normalized / "deepline_collection.json", {
        "status": "completed", "incomplete": False, "response_sha256": "b" * 64,
    })
    unknown_gap = {
        "score": None, "confidence": 0, "state": "unknown",
        "status": "insufficient_evidence", "evidence": [],
    }
    paid_readiness = {
        "score": 80, "confidence": 0.75, "state": "observed",
        "status": "provisional_pass",
    }
    _write(normalized / "paid_channel_scores.json", {
        "snapshot_id": "paid-snapshot", "channels": {
            "retargeting": {"readiness": paid_readiness, "gap": unknown_gap},
            "programmatic": {"readiness": paid_readiness, "gap": unknown_gap},
        },
    })
    _write(normalized / "syndication_score.json", {
        "snapshot_id": "website-snapshot",
        "components": {
            "readiness": {"score": 78, "state": "observed", "reasons": [], "risks": []},
            "gap": unknown_gap,
        },
        "component_confidence": {"readiness": 0.8},
        "qualification": {"readiness_status": "provisional_pass"},
    })
    if include_job:
        job = {
            "source": "linkedin_jobs", "provider_record_id": "job-1",
            "title": "Demand Generation Manager", "role_family": "demand_generation",
            "company_domain": domain, "posted_at": "2026-08-15T00:00:00Z",
            "confidence": 0.95, "url": "https://linkedin.com/jobs/1",
        }
        (normalized / "job_postings.jsonl").write_text(
            json.dumps(job) + "\n", encoding="utf-8"
        )
    return run_dir


class UnifiedScoringTests(unittest.TestCase):
    def test_scores_six_signals_persists_snapshot_and_keeps_gap_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "scores.sqlite3"
            _seed_account(database)
            run_dir = _seed_run(root)

            first = score_unified_account_run(
                run_dir, database, as_of=date(2026, 9, 13)
            )
            second = score_unified_account_run(
                run_dir, database, as_of=date(2026, 9, 13)
            )

            self.assertEqual({
                "firmographic_fit", "hiring", "funding", "advertising",
                "technology", "website",
            }, set(first["signals"]))
            self.assertIsNotNone(first["priority"]["score"])
            self.assertEqual(0.9, first["priority"]["evidence_coverage"])
            self.assertEqual("unknown", first["signals"]["funding"]["state"])
            self.assertEqual("observed", first["signals"]["hiring"]["state"])
            self.assertIsNone(first["channels"]["content_syndication"]["total"])
            self.assertIn("gap", first["channels"]["content_syndication"]["blockers"])
            self.assertEqual("insufficient_evidence", first["qualification"]["opportunity_status"])
            self.assertEqual("unified_scorer_v1", first["scoring_logic_version"])
            self.assertEqual(first["snapshot_id"], second["snapshot_id"])
            with connect_database(database) as connection:
                rows = connection.execute("SELECT * FROM unified_account_scores").fetchall()
            self.assertEqual(1, len(rows))
            self.assertEqual(first["priority"]["score"], rows[0]["priority_score"])

    def test_zero_attributable_jobs_stays_unknown_instead_of_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "scores.sqlite3"
            _seed_account(database)
            run_dir = _seed_run(root, include_job=False)

            result = score_unified_account_run(
                run_dir, database, as_of=date(2026, 9, 13)
            )

            self.assertIsNone(result["signals"]["hiring"]["score"])
            self.assertEqual("unknown", result["signals"]["hiring"]["state"])
            self.assertIn("not proof of no hiring", result["signals"]["hiring"]["risks"][0])

    def test_authoritative_crunchbase_round_contributes_funding_signal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "scores.sqlite3"
            _seed_account(database)
            run_dir = _seed_run(root)
            company_path = run_dir / "normalized" / "company_enrichment.json"
            company = json.loads(company_path.read_text(encoding="utf-8"))
            company["funding"] = {
                "status": "completed",
                "provider": "crunchbase_via_deepline",
                "crunchbase_observation": {
                    "provider": "crunchbase_via_deepline",
                    "announced_at": "2026-08-20",
                    "round_type": "series_b",
                    "amount_usd": 25000000,
                    "confidence": 0.95,
                },
            }
            _write(company_path, company)

            result = score_unified_account_run(
                run_dir, database, as_of=date(2026, 9, 13)
            )

            self.assertEqual("observed", result["signals"]["funding"]["state"])
            self.assertEqual(85.0, result["signals"]["funding"]["score"])
            self.assertEqual("provisional_pass", result["signals"]["funding"]["status"])

    def test_snapshot_ignores_upstream_generation_timestamps(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "scores.sqlite3"
            _seed_account(database)
            run_dir = _seed_run(root)

            first = score_unified_account_run(
                run_dir, database, as_of=date(2026, 9, 13)
            )
            for filename in (
                "account_fit.json", "business_trigger.json",
                "ad_creative_analysis.json", "paid_channel_scores.json",
                "syndication_score.json",
            ):
                path = run_dir / "normalized" / filename
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["scored_at"] = "2099-01-01T00:00:00Z"
                _write(path, payload)

            second = score_unified_account_run(
                run_dir, database, as_of=date(2026, 9, 13)
            )

            self.assertEqual(first["snapshot_id"], second["snapshot_id"])
            with connect_database(database) as connection:
                rows = connection.execute(
                    "SELECT scoring_logic_version FROM unified_account_scores"
                ).fetchall()
            self.assertEqual(["unified_scorer_v1"], [row[0] for row in rows])

    def test_rejects_cached_company_from_another_domain(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "scores.sqlite3"
            _seed_account(database)
            run_dir = _seed_run(root)
            company_path = run_dir / "normalized" / "company_enrichment.json"
            company = json.loads(company_path.read_text())
            company["domain"] = "wrong.example"
            _write(company_path, company)

            with self.assertRaisesRegex(ValueError, "does not match"):
                score_unified_account_run(run_dir, database)


if __name__ == "__main__":
    unittest.main()
