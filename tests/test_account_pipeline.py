import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gtm_signal_engine.account_pipeline import run_account_v1


def _write(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class AccountPipelineTests(unittest.TestCase):
    def test_company_enrichment_runs_first_and_supplies_downstream_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir = root / "run"
            calls = []
            _write(run_dir / "manifest.json", {
                "run_id": "run", "seed_url": "https://example.com/",
                "provider": "ScraplingFetcher", "status": "completed", "fetched_pages": 1,
            })
            _write(run_dir / "normalized" / "asset_summary.json", {
                "substantial": {"yes": 0}, "asset_types": {},
            })
            _write(run_dir / "normalized" / "deepline_collection.json", {"status": "completed"})
            _write(run_dir / "normalized" / "adyntel_collection.json", {"platforms": {
                key: {"status": "completed", "incomplete": False, "provider_total_records": 0}
                for key in ("meta", "linkedin", "google")
            }})
            _write(run_dir / "normalized" / "external_profile.json", {
                "schema_version": "1.0", "domain": "example.com",
                "technologies": [], "ads": [], "gap_observations": [],
            })

            def company(domain, **kwargs):
                calls.append(("company", domain))
                return {
                    "domain": domain, "name": "Canonical Example", "status": "completed",
                    "cache_hit": True, "last_enriched_at": "2026-09-13T00:00:00Z",
                    "identifiers": {"linkedin_company_id": "123", "linkedin_url": "https://linkedin.com/company/example"},
                    "firmographics": {"employee_count": 50},
                    "funding": {"status": "completed", "required_provider": "crunchbase_via_deepline"},
                    "downstream_keys": {"linkedin_jobs": "123"}, "current_run_billing": [],
                }

            def jobs(saved, domain, **kwargs):
                calls.append(("jobs", kwargs["linkedin_company_id"], kwargs["account_name"]))
                _write(saved / "normalized" / "job_collection.json", {
                    "status": "completed", "normalized_records": 0, "sources": {},
                })
                (saved / "normalized" / "job_postings.jsonl").write_text("")
                return SimpleNamespace(incomplete=False, records=[], warnings=[])

            def resolve_gaps(saved, **kwargs):
                calls.append(("gaps", str(saved)))
                score = {
                    "scoring_version": "unified_account_v1",
                    "priority": {"score": 75, "status": "high_priority"},
                    "qualification": {"opportunity_status": "insufficient_evidence"},
                }
                _write(saved / "normalized" / "unified_account_score.json", score)
                return {
                    "status": "insufficient_evidence", "review_counts": {},
                    "channels": {},
                    "unified_account_score": {
                        "snapshot_id": "snapshot", "priority": score["priority"],
                        "opportunity_status": "insufficient_evidence",
                    },
                }

            result = run_account_v1(
                "example.com", account_name="Input Example", run_dir=run_dir,
                company_enricher=company, jobs_collector=jobs,
                unified_scorer=lambda *_args, **_kwargs: self.fail("fallback scorer ran"),
                gap_resolver=resolve_gaps,
            )
            self.assertEqual([
                ("company", "example.com"),
                ("jobs", "123", "Canonical Example"),
                ("gaps", str(run_dir)),
            ], calls)
            self.assertEqual("completed", result["pipeline"]["status"])
            reference = json.loads(
                (run_dir / "normalized" / "company_enrichment.json").read_text()
            )
            self.assertEqual("123", reference["identifiers"]["linkedin_company_id"])
            self.assertEqual(
                "completed", result["pipeline"]["stages"]["unified_scoring"]["status"]
            )
            self.assertEqual(
                "completed", result["pipeline"]["stages"]["channel_gap_resolution"]["status"]
            )
            self.assertEqual(75, result["unified_account_score"]["priority"]["score"])

    def test_pipeline_runs_once_then_resumes_without_paid_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir = root / "runs" / "run-1"
            calls = []

            def website(domain, **kwargs):
                _write(run_dir / "manifest.json", {
                    "run_id": "run-1", "seed_url": "https://example.com/",
                    "provider": "ScraplingFetcher", "status": "completed", "fetched_pages": 3,
                })
                _write(run_dir / "normalized" / "asset_summary.json", {
                    "substantial": {"yes": 5}, "asset_types": {"case_study": 3, "guide": 2},
                })
                _write(run_dir / "normalized" / "syndication_score.json", {"score": 70})
                return {"run": {"status": "completed"}, "run_dir": str(run_dir)}

            def builtwith(saved, domain):
                calls.append("builtwith")
                technology = {
                    "technology": "Example Pixel", "category": "Advertising", "state": "detected",
                    "source_url": "https://example.com/", "excerpt": "Detected", "observed_at": "2026-09-12T00:00:00+00:00",
                    "confidence": 0.9, "method": "fixture", "limitations": [], "first_seen_at": None,
                    "last_seen_at": None, "normalizer_version": "fixture_v1",
                }
                _write(saved / "normalized" / "deepline_collection.json", {
                    "status": "completed", "attempts": 1, "records": 1,
                    "usage": {"billing": {"credits_charged": 0.14, "cost_usd": 0.014}},
                })
                _write(saved / "normalized" / "external_profile.json", {
                    "schema_version": "1.0", "domain": domain, "technologies": [technology],
                    "ads": [], "gap_observations": [],
                })
                return SimpleNamespace(incomplete=False, records=[technology], warnings=[])

            def adyntel(saved, domain, **kwargs):
                calls.append(("adyntel", kwargs["platforms"]))
                platforms = {
                    key: {"status": "partial", "incomplete": True, "provider_total_records": 10,
                          "returned_records": 0, "normalized_records": 0,
                          "billing": {"credits_charged": 0.13, "cost_usd": 0.013}}
                    for key in kwargs["platforms"]
                }
                _write(saved / "normalized" / "adyntel_collection.json", {
                    "status": "partial", "platforms": platforms, "warnings": [],
                })
                return SimpleNamespace(incomplete=True, records=[], warnings=["first page sample"])

            result = run_account_v1(
                "example.com", account_name="Example", output_root=root / "runs",
                website_runner=website, builtwith_collector=builtwith, adyntel_collector=adyntel,
                skip_ad_platforms=("meta",), unified_scorer=None, gap_resolver=None,
            )
            self.assertEqual("completed", result["pipeline"]["status"])
            self.assertEqual(0.4, result["provider_cost"]["credits"])
            self.assertEqual(["builtwith", ("adyntel", ("linkedin", "google"))], calls)
            self.assertEqual(
                "not_collected_by_decision",
                result["paid_ads"]["platforms"]["meta"]["evidence_state"],
            )
            self.assertTrue(Path(result["outputs"]["markdown"]).is_file())

            resumed = run_account_v1(
                "example.com", account_name="Example", run_dir=run_dir,
                builtwith_collector=lambda *_args, **_kwargs: self.fail("BuiltWith was repurchased"),
                adyntel_collector=lambda *_args, **_kwargs: self.fail("Adyntel was repurchased"),
                skip_ad_platforms=("meta",), unified_scorer=None, gap_resolver=None,
            )
            self.assertEqual("completed", resumed["pipeline"]["status"])

    def test_failed_adyntel_uses_apify_but_partial_does_not(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir = root / "run"
            _write(run_dir / "manifest.json", {
                "run_id": "run", "seed_url": "https://example.com/", "provider": "ScraplingFetcher",
                "status": "completed", "fetched_pages": 1,
            })
            _write(run_dir / "normalized" / "asset_summary.json", {"substantial": {"yes": 0}, "asset_types": {}})
            _write(run_dir / "normalized" / "syndication_score.json", {})
            _write(run_dir / "normalized" / "deepline_collection.json", {"status": "completed", "attempts": 1})
            _write(run_dir / "normalized" / "external_profile.json", {
                "schema_version": "1.0", "domain": "example.com", "technologies": [], "ads": [], "gap_observations": [],
            })
            _write(run_dir / "normalized" / "adyntel_collection.json", {"platforms": {
                "meta": {"status": "failed", "incomplete": True},
                "linkedin": {"status": "partial", "incomplete": True, "provider_total_records": 4},
                "google": {"status": "completed", "incomplete": False, "provider_total_records": 0},
            }})
            fallback = []

            def apify(saved, domain, **kwargs):
                fallback.extend(kwargs["platforms"])
                _write(saved / "normalized" / "apify_collection.json", {"platforms": {"meta": {"status": "SUCCEEDED"}}})
                return SimpleNamespace(incomplete=False, records=[], warnings=[])

            run_account_v1(
                "example.com", run_dir=run_dir, apify_collector=apify,
                unified_scorer=None, gap_resolver=None,
            )
            self.assertEqual(["meta"], fallback)


if __name__ == "__main__":
    unittest.main()
