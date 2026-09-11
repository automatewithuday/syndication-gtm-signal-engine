import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gtm_signal_engine.classifiers import classify_asset, classify_gating
from gtm_signal_engine.models import Page


class ClassificationPrecisionTests(unittest.TestCase):
    def test_manually_labeled_precision_meets_initial_targets(self):
        labels = json.loads((ROOT / "tests/fixtures/labeled_classification_pages.json").read_text())
        asset_correct = 0
        gating_correct = 0
        gating_total = 0
        for label in labels:
            expected_asset = label.pop("asset_type")
            expected_gating = label.pop("gating")
            page = Page(**label)
            asset_evidence = classify_asset(page)
            predicted_asset = asset_evidence[0].value if asset_evidence else None
            asset_correct += int(predicted_asset == expected_asset)
            if expected_asset is not None:
                gating_total += 1
                gating_correct += int(classify_gating(page).value == expected_gating)
        asset_precision = asset_correct / len(labels)
        gating_precision = gating_correct / gating_total
        self.assertGreaterEqual(asset_precision, 0.90)
        self.assertGreaterEqual(gating_precision, 0.85)


if __name__ == "__main__":
    unittest.main()
