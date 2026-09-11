import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gtm_signal_engine.account_fit import score_account_fit, score_account_fit_run
from gtm_signal_engine.syndication_scoring import load_scoring_config


def fact(fact_type, value, *, strength="confirmed", confidence=0.9, suffix="one"):
    return {
        "fact_type": fact_type,
        "value": value,
        "strength": strength,
        "confidence": confidence,
        "url": f"https://example.com/evidence/{suffix}",
        "excerpt": "Direct supporting evidence.",
        "observed_at": "2026-09-10T00:00:00+00:00",
    }


class AccountFitTests(unittest.TestCase):
    def setUp(self):
        self.config, _, _ = load_scoring_config()
        self.profile = {
            "account": {"name": "Example", "domain": "example.com"},
            "facts": [
                fact("b2b_business_model", True, suffix="b2b"),
                fact("professional_buyers", ["sales", "marketing", "revops"], suffix="buyers"),
                fact("sales_motion", "consultative", suffix="motion"),
                fact("operating_scale", "established", suffix="scale"),
            ],
        }

    def test_scores_each_sourced_factor_without_requiring_employee_count(self):
        result = score_account_fit(self.profile, self.config)
        self.assertGreaterEqual(result["score"], 60)
        self.assertEqual("provisional_pass", result["status"])
        self.assertEqual(4, len(result["factors"]))
        self.assertTrue(all(item["evidence"] for item in result["factors"]))

    def test_conflicting_sales_motion_is_unknown_not_averaged(self):
        profile = deepcopy(self.profile)
        profile["facts"].append(fact("sales_motion", "enterprise", suffix="conflict"))
        result = score_account_fit(profile, self.config)
        motion = next(item for item in result["factors"] if item["id"] == "sales_motion")
        self.assertEqual("unknown", motion["state"])
        self.assertEqual(0, motion["points"])
        self.assertEqual("review", result["status"])

    def test_rejects_unsourced_fact(self):
        profile = deepcopy(self.profile)
        profile["facts"][0]["excerpt"] = ""
        with self.assertRaisesRegex(ValueError, "supporting excerpt"):
            score_account_fit(profile, self.config)

    def test_run_writes_stable_fit_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            normalized = root / "normalized"
            normalized.mkdir()
            profile = deepcopy(self.profile)
            pages = []
            for index, item in enumerate(profile["facts"]):
                content_hash = f"{index + 1:064x}"
                item["method"] = "scrapling_saved_page"
                item["content_sha256"] = content_hash
                pages.append({
                    "url": item["url"], "text": item["excerpt"], "main_text": item["excerpt"],
                    "links": [], "content_hash": content_hash, "observed_at": item["observed_at"],
                })
            (root / "manifest.json").write_text(json.dumps({
                "run_id": "fit-run", "seed_url": "https://example.com/", "provider": "ScraplingFetcher",
            }))
            (normalized / "pages.jsonl").write_text("".join(json.dumps(page) + "\n" for page in pages))
            profile_path = root / "profile.json"
            profile_path.write_text(json.dumps(profile, sort_keys=True))
            first = score_account_fit_run(root, profile_path)
            second = score_account_fit_run(root, profile_path)
            self.assertEqual(first["snapshot_id"], second["snapshot_id"])
            self.assertTrue((root / "normalized" / "account_fit.json").exists())

    def test_run_rejects_fact_not_bound_to_saved_scrapling_page(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "normalized").mkdir()
            (root / "manifest.json").write_text(json.dumps({
                "run_id": "fit-run", "seed_url": "https://example.com/", "provider": "ScraplingFetcher",
            }))
            (root / "normalized" / "pages.jsonl").write_text("")
            profile = deepcopy(self.profile)
            for item in profile["facts"]:
                item["method"] = "scrapling_saved_page"
                item["content_sha256"] = "a" * 64
            path = root / "profile.json"
            path.write_text(json.dumps(profile))
            with self.assertRaisesRegex(ValueError, "not present in the Scrapling run"):
                score_account_fit_run(root, path)


if __name__ == "__main__":
    unittest.main()
