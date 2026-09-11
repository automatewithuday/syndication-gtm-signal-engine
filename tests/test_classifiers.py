import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gtm_signal_engine.classifiers import (
    classify_asset,
    classify_forms,
    classify_gating,
    classify_page_family,
    classify_segment_page,
)
from gtm_signal_engine.models import Page


class ClassifierTests(unittest.TestCase):
    def test_asset_listing_pages_are_taxonomy_not_assets(self):
        for url in (
            "https://example.com/case-studies",
            "https://example.com/resource-center/case-studies/page/2",
            "https://example.com/guides",
        ):
            page = Page(url=url, title="Resources")
            self.assertEqual("taxonomy", classify_page_family(page).value)
            self.assertEqual([], classify_asset(page))

    def test_legal_pdf_is_not_attributed_to_an_asset(self):
        page = Page(
            url="https://example.com/ebooks/payroll",
            title="Payroll guide",
            text="Complete the form to download the guide.",
            links=["https://example.com/legal/glba-consumer-notice.pdf"],
            forms=[{"purpose": "download", "fields": ["email"]}],
        )
        self.assertEqual("fully_gated", classify_gating(page).value)

    def test_report_and_gate_are_detected(self):
        page = Page(
            url="https://example.com/resources/security-report",
            title="Security Benchmark Report",
            text="Complete the form to download the report.",
            forms=[{"purpose": "download", "fields": ["name", "email"]}],
        )
        self.assertIn("report", [item.value for item in classify_asset(page)])
        self.assertEqual("fully_gated", classify_gating(page).value)

    def test_industry_page_uses_url_path(self):
        page = Page(url="https://example.com/industries/healthcare", title="Healthcare")
        evidence = classify_segment_page(page)
        self.assertEqual("industry", evidence[0].value["kind"])

    def test_page_family_uses_high_signal_url_not_footer_copy(self):
        page = Page(
            url="https://example.com/blog/retention",
            title="Retention tactics",
            text="Footer: download our benchmark report and watch our webinar.",
        )
        self.assertEqual("blog", classify_page_family(page).value)
        self.assertEqual([], classify_asset(page))

    def test_tool_section_outranks_asset_word_in_product_name(self):
        page = Page(
            url="https://example.com/tools/reportgarden",
            title="ReportGarden Review: Features and Pricing",
        )
        self.assertEqual("tool_catalog", classify_page_family(page).value)
        self.assertEqual([], classify_asset(page))

    def test_repeated_playbook_form_does_not_gate_a_case_study(self):
        page = Page(
            url="https://example.com/case-studies/acme",
            title="How Acme grew",
            text="The complete customer story and its results. " * 30,
            forms=[{
                "method": "post",
                "fields": ["email"],
                "submit_text": "Receive our GTM playbook",
                "text": "Enter your email",
            }],
        )
        self.assertEqual("asset_access", classify_forms(page)[0].value["purpose"])
        self.assertEqual("fully_ungated", classify_gating(page).value)

    def test_search_and_newsletter_forms_are_distinguished(self):
        page = Page(
            url="https://example.com/",
            forms=[
                {"method": "get", "fields": ["s"], "field_details": [{"type": "search"}]},
                {"method": "post", "fields": ["email"], "submit_text": "Subscribe"},
            ],
        )
        self.assertEqual(
            ["site_search", "newsletter"],
            [item.value["purpose"] for item in classify_forms(page)],
        )

    def test_unsubscribe_does_not_turn_guide_gate_into_newsletter(self):
        page = Page(
            url="https://example.com/guides/agent-workflow",
            title="Agent Workflow Guide",
            text="A useful preview of the guide. " * 80,
            forms=[{
                "method": "post",
                "fields": [],
                "text": "Work email Complete check. One email per guide; unsubscribe any time.",
            }],
        )
        self.assertEqual("asset_access", classify_forms(page)[0].value["purpose"])
        self.assertEqual("summary_ungated_full_asset_gated", classify_gating(page).value)

    def test_marketo_form_on_ebook_is_connected_to_asset(self):
        page = Page(
            url="https://example.com/resources/ebooks/payroll",
            title="Payroll eBook",
            text="Learn about payroll.",
            links=["https://assets.example.com/payroll.pdf"],
            forms=[{"id": "mktoForm_1011", "class": "marketo-form", "text": "Sign up"}],
        )
        self.assertEqual("asset_access", classify_forms(page)[0].value["purpose"])
        self.assertEqual("optional_gate", classify_gating(page).value)

    def test_webinar_replay_without_registration_is_ungated(self):
        page = Page(
            url="https://example.com/webinar/ai-agents",
            title="AI Agents Webinar",
            text="Webinar Replay " + ("Resources and full session details. " * 50),
        )
        self.assertEqual("fully_ungated", classify_gating(page).value)


if __name__ == "__main__":
    unittest.main()
