import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gtm_signal_engine.models import Evidence, Page
from gtm_signal_engine.semantic import resolve_unknown


class FixtureSemanticClassifier:
    model_version = "fixture-model-v1"
    prompt_version = "fixture-prompt-v1"

    def classify(self, page, signal_type):
        return Evidence(
            signal_type=signal_type, value="guide", strength="likely", confidence=0.8,
            url=page.url, excerpt="Guide", method="structured_llm:fixture-model-v1:fixture-prompt-v1",
        )


class SemanticFallbackTests(unittest.TestCase):
    def test_only_calls_fallback_for_unknown(self):
        page = Page(url="https://example.com/guide")
        unknown = Evidence("page_family", "unknown", "unknown", 0.2, page.url)
        result = resolve_unknown(page, unknown, FixtureSemanticClassifier())
        self.assertEqual("guide", result.value)

        observed = Evidence("page_family", "case_study", "confirmed", 0.98, page.url)
        self.assertIs(observed, resolve_unknown(page, observed, FixtureSemanticClassifier()))

    def test_without_provider_unknown_is_preserved(self):
        page = Page(url="https://example.com/")
        unknown = Evidence("page_family", "unknown", "unknown", 0.2, page.url)
        self.assertIs(unknown, resolve_unknown(page, unknown, None))


if __name__ == "__main__":
    unittest.main()
