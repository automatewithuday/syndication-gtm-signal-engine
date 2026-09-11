import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gtm_signal_engine.vault import MacOSKeychainVault


class VaultTests(unittest.TestCase):
    def test_reads_named_secret_without_logging_it(self):
        with patch("gtm_signal_engine.vault.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, stdout="secret-value\n", stderr="")
            value = MacOSKeychainVault(service="app", account="acct").get_secret("apify-token")
        self.assertEqual("secret-value", value)
        self.assertEqual(
            ["security", "find-generic-password", "-a", "acct", "-s", "app:apify-token", "-w"],
            run.call_args.args[0],
        )

    def test_missing_secret_raises_without_exposing_stderr(self):
        with patch("gtm_signal_engine.vault.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess([], 44, stdout="", stderr="sensitive backend detail")
            with self.assertRaisesRegex(KeyError, "was not found") as raised:
                MacOSKeychainVault().get_secret("deepline-key")
        self.assertNotIn("sensitive backend detail", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
