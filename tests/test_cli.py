import contextlib
import io
import sys
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gtm_signal_engine import cli
from gtm_signal_engine.cli import build_parser


class CliTests(unittest.TestCase):
    def test_crawl_does_not_accept_an_alternate_fetcher(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                build_parser().parse_args(["crawl", "example.com", "--fetcher", "system-curl"])

    def test_crawl_does_not_receive_gap_depth_argument(self):
        manifest = SimpleNamespace(status="completed", __dict__={"status": "completed"})
        with patch.object(cli, "collect_website", return_value=(manifest, [], Path("run"))) as mocked, \
             patch("builtins.print"):
            cli.main(["crawl", "example.com"])
        self.assertNotIn("maximum_depth", mocked.call_args.kwargs)

    def test_gap_target_depth_reaches_collector(self):
        with patch.object(cli, "collect_gap_targets", return_value={}) as mocked, \
             patch("builtins.print"):
            cli.main(["collect-gap-targets", "run", "--maximum-depth", "2"])
        self.assertEqual(2, mocked.call_args.kwargs["maximum_depth"])

    def test_explicit_gap_urls_reach_collector(self):
        with patch.object(cli, "collect_gap_targets", return_value={}) as mocked, \
             patch("builtins.print"):
            cli.main([
                "collect-gap-targets", "run", "--url", "https://example.com/press/launch"
            ])
        self.assertEqual(
            ["https://example.com/press/launch"], mocked.call_args.kwargs["include_urls"]
        )

    def test_trigger_as_of_reaches_scorer(self):
        with patch.object(cli, "score_business_trigger_run", return_value={}) as mocked, \
             patch("builtins.print"):
            cli.main(["score-trigger", "run", "profile.json", "--as-of", "2026-09-11"])
        self.assertEqual(date(2026, 9, 11), mocked.call_args.kwargs["as_of"])

    def test_unified_score_arguments_reach_scorer(self):
        with patch.object(cli, "score_unified_account_run", return_value={}) as mocked, \
             patch("builtins.print"):
            cli.main([
                "score-unified-account", "run", "--database", "scores.sqlite3",
                "--as-of", "2026-09-13",
            ])
        self.assertEqual(Path("run"), mocked.call_args.args[0])
        self.assertEqual(Path("scores.sqlite3"), mocked.call_args.kwargs["database_path"])
        self.assertEqual(date(2026, 9, 13), mocked.call_args.kwargs["as_of"])

    def test_gap_resolution_arguments_reach_workflow(self):
        with patch.object(cli, "resolve_channel_gaps", return_value={}) as mocked, \
             patch("builtins.print"):
            cli.main([
                "resolve-channel-gaps", "run", "--account-name", "Example",
                "--database", "scores.sqlite3", "--as-of", "2026-09-13",
            ])
        self.assertEqual(Path("run"), mocked.call_args.args[0])
        self.assertEqual("Example", mocked.call_args.kwargs["account_name"])
        self.assertEqual(Path("scores.sqlite3"), mocked.call_args.kwargs["database_path"])
        self.assertEqual(date(2026, 9, 13), mocked.call_args.kwargs["as_of"])

    def test_gap_acquisition_arguments_reach_scrapling_workflow(self):
        with patch.object(cli, "acquire_gap_evidence", return_value={}) as mocked, \
             patch.object(cli, "ScraplingFetcher", return_value="scrapling"), \
             patch("builtins.print"):
            cli.main([
                "acquire-gap-evidence", "run", "--account-name", "Example",
                "--maximum-targets", "8", "--maximum-pages", "5",
                "--maximum-depth", "3", "--delay-seconds", "0.1",
                "--search-results", "saved-search.jsonl", "--retry-failed",
            ])
        self.assertEqual(Path("run"), mocked.call_args.args[0])
        self.assertEqual(8, mocked.call_args.kwargs["maximum_targets"])
        self.assertEqual(5, mocked.call_args.kwargs["maximum_pages"])
        self.assertEqual(3, mocked.call_args.kwargs["maximum_depth"])
        self.assertEqual([Path("saved-search.jsonl")], mocked.call_args.kwargs["search_result_paths"])
        self.assertTrue(mocked.call_args.kwargs["retry_failed"])
        self.assertEqual("scrapling", mocked.call_args.kwargs["fetcher"])

    def test_gap_plan_arguments_reach_planner(self):
        with patch.object(cli, "build_gap_target_plan", return_value={}) as mocked, \
             patch("builtins.print"):
            cli.main([
                "plan-gap-evidence", "run", "--maximum-targets", "8",
                "--search-results", "saved-search.jsonl", "--retry-failed",
            ])
        self.assertEqual(Path("run"), mocked.call_args.args[0])
        self.assertEqual(8, mocked.call_args.kwargs["maximum_targets"])
        self.assertEqual([Path("saved-search.jsonl")], mocked.call_args.kwargs["search_result_paths"])
        self.assertTrue(mocked.call_args.kwargs["retry_failed"])

    def test_deepline_arguments_reach_live_collector(self):
        result = SimpleNamespace(
            provider="deepline", records=[], raw_payload_location="raw/deepline.json",
            incomplete=False, warnings=[],
        )
        with patch.object(cli, "collect_deepline_technologies", return_value=result) as mocked, \
             patch("builtins.print"):
            exit_code = cli.main([
                "collect-deepline", "data/runs/test", "example.com"
            ])
        self.assertEqual(0, exit_code)
        self.assertEqual(Path("data/runs/test"), mocked.call_args.args[0])
        self.assertEqual("example.com", mocked.call_args.args[1])

    def test_apify_arguments_reach_live_collector(self):
        result = SimpleNamespace(
            provider="apify_ads", records=[], raw_payload_location=None,
            incomplete=False, warnings=[],
        )
        with patch.object(cli, "collect_apify_ads", return_value=result) as mocked, \
             patch("builtins.print"):
            exit_code = cli.main([
                "collect-apify-ads", "data/runs/test", "example.com",
                "--account-name", "Example",
            ])
        self.assertEqual(0, exit_code)
        self.assertEqual(Path("data/runs/test"), mocked.call_args.args[0])
        self.assertEqual("example.com", mocked.call_args.args[1])
        self.assertEqual("Example", mocked.call_args.kwargs["account_name"])
        self.assertIsNone(mocked.call_args.kwargs["linkedin_company_id"])
        self.assertEqual(("linkedin", "meta"), mocked.call_args.kwargs["platforms"])

    def test_apify_platform_selection_reaches_live_collector(self):
        result = SimpleNamespace(
            provider="apify_ads", records=[], raw_payload_location=None,
            incomplete=False, warnings=[],
        )
        with patch.object(cli, "collect_apify_ads", return_value=result) as mocked, \
             patch("builtins.print"):
            cli.main([
                "collect-apify-ads", "data/runs/test", "example.com",
                "--account-name", "Example", "--platform", "meta",
                "--linkedin-company-id", "65826193",
            ])
        self.assertEqual(("meta",), mocked.call_args.kwargs["platforms"])
        self.assertEqual("65826193", mocked.call_args.kwargs["linkedin_company_id"])

    def test_ad_creative_analysis_arguments_reach_analyzer(self):
        result = {
            "analysis_version": "ad_creative_analysis_v1",
            "scoring_inputs": {},
            "platforms": {},
        }
        with patch.object(cli, "analyze_ad_creatives", return_value=result) as mocked, \
             patch("builtins.print"):
            exit_code = cli.main([
                "analyze-ad-creatives", "data/runs/test", "--config", "config/custom.json"
            ])
        self.assertEqual(0, exit_code)
        self.assertEqual(Path("data/runs/test"), mocked.call_args.args[0])
        self.assertEqual(Path("config/custom.json"), mocked.call_args.args[1])

    def test_account_pipeline_platform_skip_reaches_orchestrator(self):
        result = {
            "pipeline": {"status": "completed"}, "run": {"run_dir": "run"},
            "outputs": {}, "provider_cost": {}, "blockers": [],
        }
        with patch.object(cli, "run_account_v1", return_value=result) as mocked, \
             patch("builtins.print"):
            cli.main([
                "run-account-v1", "coldiq.com", "--skip-ad-platform", "meta",
                "--gap-evidence-pages", "6", "--gap-evidence-targets", "12",
                "--gap-evidence-depth", "3", "--retry-gap-evidence",
            ])
        self.assertEqual(("meta",), mocked.call_args.kwargs["skip_ad_platforms"])
        self.assertIs(cli.enrich_company, mocked.call_args.kwargs["company_enricher"])
        self.assertIs(cli.score_unified_account_run, mocked.call_args.kwargs["unified_scorer"])
        self.assertIs(cli.resolve_channel_gaps, mocked.call_args.kwargs["gap_resolver"])
        self.assertIs(cli.acquire_gap_evidence, mocked.call_args.kwargs["gap_acquirer"])
        self.assertEqual(6, mocked.call_args.kwargs["gap_evidence_pages"])
        self.assertEqual(12, mocked.call_args.kwargs["gap_evidence_targets"])
        self.assertEqual(3, mocked.call_args.kwargs["gap_evidence_depth"])
        self.assertTrue(mocked.call_args.kwargs["retry_gap_evidence"])
        self.assertEqual(Path("data/gtm_signal_engine.sqlite3"), mocked.call_args.kwargs["database_path"])

    def test_portfolio_report_arguments_reach_builder(self):
        with patch.object(cli, "build_portfolio_report", return_value={}) as mocked, \
             patch("builtins.print"):
            exit_code = cli.main([
                "build-portfolio-report", "--database", "jobs.sqlite3",
                "--output", "reports/ranked.json",
            ])
        self.assertEqual(0, exit_code)
        self.assertEqual(Path("jobs.sqlite3"), mocked.call_args.kwargs["database_path"])
        self.assertEqual(Path("reports/ranked.json"), mocked.call_args.kwargs["output_path"])

    def test_company_enrichment_arguments_reach_cache_layer(self):
        result = {"domain": "example.com", "status": "partial"}
        with patch.object(cli, "enrich_company", return_value=result) as mocked, \
             patch("builtins.print"):
            cli.main([
                "enrich-company", "example.com", "--account-name", "Example",
                "--linkedin-company-id", "123", "--refresh",
                "--database", "custom.sqlite3", "--output-dir", "company-data",
            ])
        self.assertEqual("example.com", mocked.call_args.args[0])
        self.assertEqual("Example", mocked.call_args.kwargs["account_name"])
        self.assertEqual("123", mocked.call_args.kwargs["linkedin_company_id"])
        self.assertTrue(mocked.call_args.kwargs["refresh"])
        self.assertEqual(Path("custom.sqlite3"), mocked.call_args.kwargs["database_path"])

    def test_company_funding_refresh_uses_dedicated_command(self):
        result = {"domain": "example.com", "funding": {"status": "completed"}}
        with patch.object(cli, "enrich_company_funding", return_value=result) as mocked, \
             patch("builtins.print"):
            exit_code = cli.main([
                "enrich-company-funding", "example.com",
                "--database", "custom.sqlite3", "--output-dir", "company-data",
            ])
        self.assertEqual(0, exit_code)
        self.assertEqual("example.com", mocked.call_args.args[0])
        self.assertEqual(Path("custom.sqlite3"), mocked.call_args.kwargs["database_path"])
        self.assertEqual(Path("company-data"), mocked.call_args.kwargs["output_root"])

    def test_company_funding_refresh_reports_unresolved_exit(self):
        result = {
            "domain": "example.com",
            "funding": {"status": "blocked_provider_unavailable"},
        }
        with patch.object(cli, "enrich_company_funding", return_value=result), \
             patch("builtins.print"):
            exit_code = cli.main(["enrich-company-funding", "example.com"])
        self.assertEqual(1, exit_code)


if __name__ == "__main__":
    unittest.main()
