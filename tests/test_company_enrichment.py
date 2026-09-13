import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gtm_signal_engine.company_enrichment import (
    enrich_company, enrich_company_funding, get_account,
)
from gtm_signal_engine.review_queue import connect_database


class FixtureRunner:
    def __init__(self):
        self.calls = []

    def run(self, arguments):
        self.calls.append(list(arguments))
        tool_id = arguments[2]
        if arguments[1] == "search":
            payload = {
                "tools": [
                    {
                        "toolId": "aviato_get_company_funding_rounds",
                        "provider": "aviato", "connected": True,
                        "executeCommand": "deepline tools execute aviato_get_company_funding_rounds",
                    },
                    {
                        "toolId": "leadmagic_company_funding",
                        "provider": "leadmagic", "connected": True,
                        "executeCommand": "deepline tools execute leadmagic_company_funding",
                    },
                ],
                "count": 2,
            }
        elif arguments[1] == "describe":
            field = "company_website" if tool_id == "prospeo_enrich_company" else "domains"
            payload = {
                "toolId": tool_id, "callable": True, "connected": True,
                "inputSchema": {"jsonSchema": {"properties": {field: {"type": "string"}}}},
            }
        elif tool_id == "prospeo_enrich_company":
            payload = {
                "job_id": "prospeo-job", "status": "completed",
                "billing": {"credits_charged": 0.55, "cost_usd": 0.055},
                "toolResponse": {"rawV2": {"company": {
                    "company_id": "prospeo-1", "name": "Example",
                    "website": "https://example.com", "domain": "example.com",
                    "linkedin_url": "https://www.linkedin.com/company/example",
                    "linkedin_id": None, "crunchbase_url": "https://crunchbase.com/example",
                    "industry": "Software", "employee_count": 42,
                    "employee_range": "21-50", "revenue_range": {"min": 1000000, "max": 5000000},
                    "type": "Private", "founded": 2020,
                    "location": {"country": "US"}, "funding": {"total": 1},
                }}}
            }
        else:
            payload = {
                "job_id": "identity-job", "status": "completed",
                "toolResponse": {"rawV2": [{
                    "matched_on": "example.com", "match_type": "domain",
                    "matches": [{"confidence_score": 1, "company_data": {
                        "crustdata_company_id": 99,
                        "basic_info": {
                            "name": "Example", "primary_domain": "example.com",
                            "professional_network_url": "https://www.linkedin.com/company/example",
                            "professional_network_id": "12345",
                        },
                    }}],
                }]}
            }
        return subprocess.CompletedProcess(arguments, 0, stdout=json.dumps(payload), stderr="")


class CrunchbaseFixtureRunner(FixtureRunner):
    def run(self, arguments):
        if arguments[1] == "search":
            self.calls.append(list(arguments))
            payload = {"tools": [{
                "toolId": "crunchbase_company_funding",
                "provider": "crunchbase", "connected": True,
                "executeCommand": "deepline tools execute crunchbase_company_funding",
            }]}
            return subprocess.CompletedProcess(
                arguments, 0, stdout=json.dumps(payload), stderr=""
            )
        if arguments[1] == "describe" and arguments[2] == "crunchbase_company_funding":
            self.calls.append(list(arguments))
            payload = {
                "toolId": "crunchbase_company_funding", "provider": "crunchbase",
                "callable": True, "connected": True,
                "inputSchema": {"jsonSchema": {"properties": {
                    "organization_url": {"type": "string"},
                }}},
            }
            return subprocess.CompletedProcess(
                arguments, 0, stdout=json.dumps(payload), stderr=""
            )
        if arguments[1] == "execute" and arguments[2] == "crunchbase_company_funding":
            self.calls.append(list(arguments))
            payload = {
                "job_id": "funding-job", "status": "completed",
                "billing": {"credits_charged": 0.4, "cost_usd": 0.04},
                "toolResponse": {"rawV2": {"organization": {
                    "domain": "example.com",
                    "crunchbase_url": "https://crunchbase.com/example",
                    "total_funding_usd": 12000000,
                    "funding_rounds": [{
                        "announced_on": "2026-01-05", "funding_type": "series_a",
                        "money_raised_usd": 12000000,
                        "source_url": "https://crunchbase.com/example/rounds/one",
                    }],
                }}},
            }
            return subprocess.CompletedProcess(
                arguments, 0, stdout=json.dumps(payload), stderr=""
            )
        return super().run(arguments)


class CompanyEnrichmentTests(unittest.TestCase):
    def test_enrichment_persists_account_and_reuses_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "accounts.sqlite3"
            runner = FixtureRunner()
            first = enrich_company(
                "example.com", account_name="Example", database_path=database,
                output_root=root / "company-data", runner=runner,
            )
            self.assertFalse(first["cache_hit"])
            self.assertEqual("12345", first["identifiers"]["linkedin_company_id"])
            self.assertEqual("partial", first["status"])
            self.assertEqual(
                "blocked_provider_unavailable", first["funding"]["status"]
            )
            self.assertEqual("deepline", first["request_policy"]["provider_gateway"])
            self.assertFalse(first["request_policy"]["direct_provider_api_calls"])
            self.assertEqual(5, len(runner.calls))
            self.assertTrue(Path(first["source_snapshots"][0]["raw_payload_path"]).is_file())

            second = enrich_company(
                "example.com", database_path=database,
                output_root=root / "company-data", runner=runner,
            )
            self.assertTrue(second["cache_hit"])
            self.assertEqual([], second["current_run_billing"])
            self.assertEqual(5, len(runner.calls))
            self.assertEqual("Example", get_account("example.com", database)["name"])
            with connect_database(database) as connection:
                account = connection.execute("SELECT * FROM accounts").fetchone()
                snapshots = connection.execute(
                    "SELECT provider FROM account_enrichment_snapshots ORDER BY provider"
                ).fetchall()
            self.assertEqual(42, account["employee_count"])
            self.assertEqual('{"max":5000000,"min":1000000}', account["revenue_range"])
            self.assertEqual(
                ["crustdata-v3", "deepline-tool-catalog", "prospeo"],
                [row["provider"] for row in snapshots],
            )

    def test_verified_linkedin_id_skips_identity_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = FixtureRunner()
            result = enrich_company(
                "example.com", database_path=root / "accounts.sqlite3",
                output_root=root / "company-data", linkedin_company_id="777",
                runner=runner,
            )
            self.assertEqual("777", result["identifiers"]["linkedin_company_id"])
            self.assertEqual(3, len(runner.calls))
            self.assertEqual("user_verified", result["field_provenance"]["linkedin_company_id"])

    def test_saved_provider_response_replay_does_not_count_as_new_spend(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_runner = FixtureRunner()
            response = source_runner.run([
                "tools", "execute", "prospeo_enrich_company"
            ]).stdout
            response_path = root / "saved-prospeo-response.json"
            response_path.write_text(response, encoding="utf-8")
            import_runner = FixtureRunner()

            result = enrich_company(
                "example.com", database_path=root / "accounts.sqlite3",
                output_root=root / "company-data", linkedin_company_id="777",
                prospeo_response_path=response_path, runner=import_runner,
            )

            self.assertEqual([], result["current_run_billing"])
            self.assertEqual(1, len(import_runner.calls))
            self.assertEqual("search", import_runner.calls[0][1])
            self.assertFalse(result["cache_hit"])

    def test_exact_crunchbase_provider_is_normalized_and_billed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = CrunchbaseFixtureRunner()
            result = enrich_company(
                "example.com", database_path=root / "accounts.sqlite3",
                output_root=root / "company-data", linkedin_company_id="777",
                runner=runner,
            )

            self.assertEqual("completed", result["status"])
            self.assertEqual("completed", result["funding"]["status"])
            funding = result["funding"]["crunchbase_observation"]
            self.assertEqual(12000000.0, funding["total_funding_usd"])
            self.assertEqual("2026-01-05", funding["latest_funding_date"])
            self.assertEqual("series_a", funding["latest_round_type"])
            self.assertEqual("crunchbase", result["current_run_billing"][-1]["provider"])
            providers = [item["provider"] for item in result["source_snapshots"]]
            self.assertIn("crunchbase", providers)
            self.assertIn("deepline-tool-catalog", providers)

    def test_funding_refresh_uses_cache_without_calling_prospeo(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "accounts.sqlite3"
            enrich_company(
                "example.com", database_path=database,
                output_root=root / "company-data", linkedin_company_id="777",
                runner=FixtureRunner(),
            )
            runner = CrunchbaseFixtureRunner()

            result = enrich_company_funding(
                "example.com", database_path=database,
                output_root=root / "company-data", runner=runner,
            )

            self.assertEqual("completed", result["funding"]["status"])
            self.assertEqual("completed", get_account("example.com", database)["status"])
            snapshot_count = len(result["source_snapshots"])
            repeated = enrich_company_funding(
                "example.com", database_path=database,
                output_root=root / "company-data", runner=runner,
            )
            self.assertEqual(snapshot_count, len(repeated["source_snapshots"]))
            called_tools = [call[2] for call in runner.calls]
            self.assertNotIn("prospeo_enrich_company", called_tools)
            self.assertEqual(
                [
                    "crunchbase", "crunchbase_company_funding",
                    "crunchbase_company_funding", "crunchbase",
                    "crunchbase_company_funding", "crunchbase_company_funding",
                ],
                called_tools,
            )

    def test_funding_refresh_requires_cached_company(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "enriched and cached"):
                enrich_company_funding(
                    "example.com", database_path=root / "accounts.sqlite3",
                    output_root=root / "company-data", runner=FixtureRunner(),
                )


if __name__ == "__main__":
    unittest.main()
