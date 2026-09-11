import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gtm_signal_engine.syndication_scoring import load_scoring_config, score_syndication_run


def asset(index, *, asset_type="guide", age_days=30, gating="fully_gated", substantial="yes", suitability="suitable"):
    return {
        "url": f"https://example.com/assets/{index}",
        "asset_type": asset_type,
        "age_days": age_days,
        "gating": gating,
        "substantial": substantial,
        "syndication_suitability": suitability,
        "published_or_created": {"value": "2026-08-01T00:00:00+00:00"} if age_days is not None else None,
    }


class SyndicationScoringTests(unittest.TestCase):
    def make_run(self, directory, assets):
        run_dir = Path(directory)
        normalized = run_dir / "normalized"
        normalized.mkdir()
        assets_text = "".join(json.dumps(item, sort_keys=True) + "\n" for item in assets)
        (normalized / "assets.jsonl").write_text(assets_text)
        (normalized / "asset_summary.json").write_text(json.dumps({
            "raw_artifacts": {"documents_available": len(assets), "errors": []}
        }))
        (run_dir / "manifest.json").write_text(json.dumps({
            "run_id": "fixture-run", "incomplete": True, "status": "partial"
        }))
        return run_dir

    def test_high_readiness_does_not_invent_fit_gap_or_total(self):
        assets = [asset(index, asset_type="case_study" if index < 15 else "guide") for index in range(25)]
        with tempfile.TemporaryDirectory() as directory:
            result = score_syndication_run(self.make_run(directory, assets))
            self.assertGreaterEqual(result["components"]["readiness"]["score"], 65)
            self.assertIsNone(result["components"]["fit"]["score"])
            self.assertIsNone(result["components"]["gap"]["score"])
            self.assertIsNone(result["total"])
            self.assertEqual("provisional_pass", result["qualification"]["readiness_status"])
            self.assertEqual("insufficient_evidence", result["qualification"]["opportunity_status"])
            self.assertLessEqual(result["confidence"], 0.75)
            self.assertTrue((Path(directory) / "normalized" / "syndication_score.json").exists())

    def test_unknown_dates_do_not_create_a_trigger(self):
        assets = [asset(index, age_days=None) for index in range(3)]
        with tempfile.TemporaryDirectory() as directory:
            result = score_syndication_run(self.make_run(directory, assets))
            self.assertEqual(0, result["metrics"]["assets_within_90_days"])
            self.assertIsNone(result["components"]["trigger"]["score"])
            self.assertEqual("unknown", result["components"]["trigger"]["state"])

    def test_existing_fit_snapshot_fills_fit_but_gap_remains_unknown(self):
        assets = [asset(index) for index in range(10)]
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self.make_run(directory, assets)
            (run_dir / "normalized" / "account_fit.json").write_text(json.dumps({
                "snapshot_id": "fit-snapshot",
                "component": {
                    "score": 82,
                    "state": "observed",
                    "confidence": 0.9,
                    "factors": [],
                    "reasons": ["sourced fit"],
                    "risks": [],
                    "status": "provisional_pass"
                }
            }))
            result = score_syndication_run(run_dir)
            self.assertEqual(82, result["components"]["fit"]["score"])
            self.assertEqual(["gap"], result["qualification"]["blockers"])
            self.assertIsNone(result["total"])

    def test_gap_snapshot_is_integrated_but_disqualified_gap_never_qualifies(self):
        assets = [asset(index) for index in range(10)]
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self.make_run(directory, assets)
            normalized = run_dir / "normalized"
            (normalized / "account_fit.json").write_text(json.dumps({
                "snapshot_id": "fit-snapshot",
                "component": {
                    "score": 82, "state": "observed", "confidence": 0.9,
                    "factors": [], "reasons": [], "risks": [], "status": "provisional_pass"
                }
            }))
            (normalized / "channel_gap.json").write_text(json.dumps({
                "snapshot_id": "gap-snapshot",
                "component": {
                    "score": 0, "state": "contradicted", "confidence": 0.95,
                    "factors": [], "reasons": [], "risks": [], "status": "disqualified"
                }
            }))
            result = score_syndication_run(run_dir)
            self.assertIsNotNone(result["total"])
            self.assertEqual("disqualified", result["qualification"]["gap_status"])
            self.assertEqual("insufficient_evidence", result["qualification"]["opportunity_status"])
            self.assertEqual("gap-snapshot", result["input"]["channel_gap_snapshot_id"])

    def test_reviewed_business_trigger_is_integrated_without_adding_to_gap(self):
        assets = [asset(index) for index in range(3)]
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self.make_run(directory, assets)
            (run_dir / "normalized" / "business_trigger.json").write_text(json.dumps({
                "snapshot_id": "trigger-snapshot",
                "component": {
                    "score": 70.0, "state": "observed", "confidence": 0.9,
                    "status": "provisional_pass", "factors": [],
                    "reasons": ["reviewed campaign launch"], "risks": [], "evidence": [],
                },
            }))
            result = score_syndication_run(run_dir)
            self.assertEqual(70.0, result["components"]["trigger"]["score"])
            self.assertIsNone(result["components"]["gap"]["score"])
            self.assertEqual("trigger-snapshot", result["input"]["business_trigger_snapshot_id"])

    def test_snapshot_id_is_stable_for_unchanged_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self.make_run(directory, [asset(1), asset(2), asset(3)])
            first = score_syndication_run(run_dir)
            summary_path = run_dir / "normalized" / "asset_summary.json"
            summary = json.loads(summary_path.read_text())
            summary["analyzed_at"] = "a later replay time"
            summary_path.write_text(json.dumps(summary))
            second = score_syndication_run(run_dir)
            self.assertEqual(first["snapshot_id"], second["snapshot_id"])

    def test_default_config_is_valid_and_readiness_maxima_sum_to_100(self):
        config, _, _ = load_scoring_config()
        self.assertEqual(100, sum(item["maximum_points"] for item in config["readiness_factors"]))

    def test_v1_config_remains_loadable_for_historical_replay(self):
        config, _, _ = load_scoring_config(ROOT / "config" / "content_syndication_scoring.v1.json")
        self.assertEqual("content_syndication_v1", config["version"])
        self.assertNotIn("initiative_trigger", config)

    def test_installed_share_directory_is_a_default_config_fallback(self):
        from gtm_signal_engine import syndication_scoring

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            share = root / "share" / "gtm-signal-engine"
            share.mkdir(parents=True)
            share.joinpath("content_syndication_scoring.v2.json").write_bytes(
                (ROOT / "config" / "content_syndication_scoring.v2.json").read_bytes()
            )
            with patch.object(syndication_scoring.Path, "cwd", return_value=root / "elsewhere"), \
                 patch.object(syndication_scoring, "DEFAULT_CONFIG_PATH", root / "missing.json"), \
                 patch.object(syndication_scoring.sys, "prefix", str(root)):
                config, _, selected = syndication_scoring.load_scoring_config()
            self.assertEqual("content_syndication_v2", config["version"])
            self.assertEqual(share / "content_syndication_scoring.v2.json", selected)


if __name__ == "__main__":
    unittest.main()
