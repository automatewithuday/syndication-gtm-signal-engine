from __future__ import annotations

import subprocess
from typing import Protocol


class SecretVault(Protocol):
    def get_secret(self, name: str) -> str: ...


class MacOSKeychainVault:
    """Read provider credentials from the encrypted macOS login keychain."""

    def __init__(self, *, service: str = "gtm-signal-engine", account: str = "provider-secrets") -> None:
        self.service = service
        self.account = account

    def get_secret(self, name: str) -> str:
        if not name.strip():
            raise ValueError("secret name is required")
        service = f"{self.service}:{name}"
        completed = subprocess.run(
            ["security", "find-generic-password", "-a", self.account, "-s", service, "-w"],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise KeyError(f"secret {name!r} was not found in the configured keychain")
        value = completed.stdout.rstrip("\n")
        if not value:
            raise KeyError(f"secret {name!r} is empty")
        return value
