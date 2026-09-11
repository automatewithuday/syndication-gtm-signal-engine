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


if __name__ == "__main__":
    unittest.main()
