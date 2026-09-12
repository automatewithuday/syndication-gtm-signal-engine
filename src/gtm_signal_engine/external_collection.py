from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, Sequence
from urllib.parse import urlsplit

from .external_signals import TechnologyObservation
from .providers import ProviderResult

DEEPLINE_COLLECTION_VERSION = "deepline_builtwith_v2"
DEEPLINE_TOOL_ID = "builtwith_domain_lookup"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class DeeplineCliRunner(Protocol):
    def run(self, arguments: Sequence[str]) -> subprocess.CompletedProcess[str]: ...


class SubprocessDeeplineCliRunner:
    """Run Deepline without placing its workspace credential in this process."""

    def run(self, arguments: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["deepline", *arguments],
            check=False,
            capture_output=True,
            text=True,
        )


def _domain(value: str) -> str:
    candidate = value.strip().lower()
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    hostname = (urlsplit(candidate).hostname or "").removeprefix("www.")
    if not hostname:
        raise ValueError("a valid account domain is required")
    return hostname


def _validate_run_domain(run_dir: Path, domain: str) -> None:
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError("saved website run manifest is required before external collection")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("provider") != "ScraplingFetcher":
        raise ValueError("Deepline observations must attach to a ScraplingFetcher run")
    if _domain(str(manifest.get("seed_url", ""))) != domain:
        raise ValueError("Deepline domain does not match the saved website run")


def _run_json(runner: DeeplineCliRunner, arguments: Sequence[str]) -> tuple[dict[str, Any], bytes]:
    completed = runner.run(arguments)
    if completed.returncode != 0:
        detail = completed.stderr.strip().splitlines()[-1] if completed.stderr.strip() else "no diagnostic"
        raise RuntimeError(f"Deepline command failed with exit {completed.returncode}: {detail}")
    raw = completed.stdout.encode("utf-8")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Deepline command must return one JSON object")
    return payload, raw


def _validate_contract(contract: dict[str, Any]) -> None:
    if contract.get("toolId") != DEEPLINE_TOOL_ID or not contract.get("callable"):
        raise ValueError("Deepline BuiltWith tool is missing or not callable")
    if contract.get("connected") is not True:
        raise ValueError("Deepline BuiltWith tool is not connected")
    properties = contract.get("inputSchema", {}).get("jsonSchema", {}).get("properties", {})
    if {"domain", "live_only", "no_pii", "no_meta"}.difference(properties):
        raise ValueError("live BuiltWith contract lacks required privacy/domain fields")
    output_properties = contract.get("outputSchema", {}).get("jsonSchema", {}).get("properties", {})
    if "Results" not in output_properties:
        raise ValueError("live BuiltWith contract lacks the Results output")


def _provider_payload(envelope: dict[str, Any]) -> dict[str, Any]:
    response = envelope.get("toolResponse", {})
    candidates: list[Any] = []
    for key in ("rawV2", "raw"):
        candidate = response.get(key) if isinstance(response, dict) else None
        if isinstance(candidate, dict):
            candidates.extend([candidate.get("data"), candidate])
    candidates.extend([envelope.get("data"), envelope])
    for candidate in candidates:
        if isinstance(candidate, dict) and ("Results" in candidate or "Errors" in candidate):
            return candidate
    raise ValueError("Deepline response does not contain the BuiltWith provider payload")


def _timestamp(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        seconds = float(value) / 1_000 if float(value) > 10_000_000_000 else float(value)
        return datetime.fromtimestamp(seconds, timezone.utc).isoformat()
    return str(value)


def normalize_deepline_builtwith(
    payload: dict[str, Any], *, observed_at: str, warnings: list[str] | None = None
) -> list[TechnologyObservation]:
    """Flatten the inspected BuiltWith Results/Paths/Technologies contract."""
    observations: list[TechnologyObservation] = []
    seen: set[tuple[str, str]] = set()
    results = payload.get("Results", [])
    if not isinstance(results, list):
        raise ValueError("BuiltWith Results must be a list")
    for result_index, result in enumerate(results):
        if not isinstance(result, dict):
            raise ValueError(f"BuiltWith result {result_index} must be an object")
        lookup = _domain(str(result.get("Lookup", "")))
        paths = result.get("Result", {}).get("Paths", [])
        if not isinstance(paths, list):
            raise ValueError(f"BuiltWith result {result_index} Paths must be a list")
        for path_index, path in enumerate(paths):
            if not isinstance(path, dict):
                raise ValueError(f"BuiltWith path {path_index} must be an object")
            detected_domain = str(path.get("Domain") or lookup)
            subdomain = str(path.get("SubDomain") or "").strip(".")
            host = detected_domain if not subdomain or detected_domain.startswith(f"{subdomain}.") else f"{subdomain}.{detected_domain}"
            source_url = str(path.get("Url") or f"https://{host}/")
            technologies = path.get("Technologies", [])
            if not isinstance(technologies, list):
                raise ValueError(f"BuiltWith path {path_index} Technologies must be a list")
            for technology_index, technology in enumerate(technologies):
                if not isinstance(technology, dict) or not technology.get("Name"):
                    if warnings is not None:
                        warnings.append(
                            f"BuiltWith path {path_index} technology {technology_index} skipped: missing name"
                        )
                    continue
                name = str(technology["Name"])
                identity = (name.casefold(), source_url.casefold())
                if identity in seen:
                    continue
                seen.add(identity)
                categories = [str(item) for item in technology.get("Categories", []) if str(item).strip()]
                category = " | ".join(categories) or str(technology.get("Tag") or technology.get("Parent") or "unknown")
                description = str(technology.get("Description") or "").strip()
                observations.append(TechnologyObservation(
                    technology=name,
                    category=category,
                    state="detected",
                    source_url=source_url,
                    excerpt=description or f"BuiltWith reported {name} on {host}.",
                    observed_at=observed_at,
                    confidence=0.9,
                    method="deepline_builtwith_domain_lookup",
                    limitations=[
                        "BuiltWith detection is observable technographic evidence, not proof of complete or active deployment",
                        "the request excluded PII and company metadata and returned only currently live technologies",
                    ],
                    first_seen_at=_timestamp(technology.get("FirstDetected")),
                    last_seen_at=_timestamp(technology.get("LastDetected")),
                    normalizer_version="deepline_builtwith_v1",
                ))
    return observations


def _usage_summary(envelope: dict[str, Any]) -> dict[str, Any]:
    response = envelope.get("toolResponse", {})
    meta = response.get("meta", {}) if isinstance(response, dict) else {}
    return {
        "job_id": envelope.get("job_id") or envelope.get("jobId"),
        "status": envelope.get("status"),
        "billing": envelope.get("billing"),
        "provider_usage": meta.get("usage") if isinstance(meta, dict) else None,
    }


def collect_deepline_technologies(
    run_dir: Path,
    domain: str,
    *,
    runner: DeeplineCliRunner | None = None,
) -> ProviderResult:
    """Inspect then execute Deepline's live BuiltWith tool for one saved account run."""
    domain = _domain(domain)
    _validate_run_domain(run_dir, domain)
    runner = runner or SubprocessDeeplineCliRunner()
    raw_dir = run_dir / "raw"
    normalized_dir = run_dir / "normalized"
    raw_dir.mkdir(parents=True, exist_ok=True)
    normalized_dir.mkdir(parents=True, exist_ok=True)
    status_path = normalized_dir / "deepline_collection.json"
    status: dict[str, Any] = {
        "schema_version": "1.0",
        "collector_version": DEEPLINE_COLLECTION_VERSION,
        "provider": "deepline",
        "provider_tool": DEEPLINE_TOOL_ID,
        "domain": domain,
        "started_at": _now(),
        "finished_at": None,
        "status": "running",
        "incomplete": True,
        "attempts": 0,
        "request_policy": {
            "live_only": True,
            "no_pii": True,
            "no_meta": True,
            "automatic_paid_retries": False,
        },
        "raw_payload_location": None,
        "warnings": [],
    }
    status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        contract, contract_raw = _run_json(runner, ["tools", "describe", DEEPLINE_TOOL_ID, "--json"])
        _validate_contract(contract)
        contract_name = f"deepline-builtwith-contract-{_sha256(contract_raw)[:16]}.json"
        (raw_dir / contract_name).write_bytes(contract_raw)
        request_payload = {
            "domain": domain, "live_only": True, "no_pii": True, "no_meta": True,
            "no_attr": False, "hide_text": False, "hide_dl": False,
        }
        status["attempts"] = 1
        envelope, envelope_raw = _run_json(runner, [
            "tools", "execute", DEEPLINE_TOOL_ID,
            "--input", json.dumps(request_payload, separators=(",", ":")), "--json",
        ])
        raw_name = f"deepline-builtwith-{_sha256(envelope_raw)[:16]}.json"
        raw_path = raw_dir / raw_name
        raw_path.write_bytes(envelope_raw)
        raw_location = str(raw_path.relative_to(run_dir))
        status.update({
            "raw_payload_location": raw_location,
            "response_sha256": _sha256(envelope_raw),
            "contract_sha256": _sha256(contract_raw),
            "contract_location": str((raw_dir / contract_name).relative_to(run_dir)),
            "usage": _usage_summary(envelope),
        })
        if envelope.get("status") not in {None, "completed", "success"}:
            raise RuntimeError(f"Deepline BuiltWith job ended with status {envelope.get('status')!r}")
        provider_payload = _provider_payload(envelope)
        provider_errors = provider_payload.get("Errors") or []
        if provider_errors:
            raise RuntimeError(f"BuiltWith returned {len(provider_errors)} provider error(s)")
        normalization_warnings: list[str] = []
        normalized = [asdict(item) for item in normalize_deepline_builtwith(
            provider_payload, observed_at=_now(), warnings=normalization_warnings
        )]
        profile_path = normalized_dir / "external_profile.json"
        profile = json.loads(profile_path.read_text(encoding="utf-8")) if profile_path.is_file() else {}
        profile.update({"schema_version": "1.0", "domain": domain, "technologies": normalized})
        profile.setdefault("ads", [])
        profile.setdefault("gap_observations", [])
        profile_path.write_text(json.dumps(profile, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        status.update({
            "finished_at": _now(), "status": "completed", "incomplete": False,
            "records": len(normalized), "warnings": normalization_warnings,
        })
        status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return ProviderResult(
            provider="deepline_builtwith", query=domain, records=normalized,
            raw_payload_location=raw_location,
        )
    except Exception as exc:
        status.update({
            "finished_at": _now(), "status": "failed", "incomplete": True,
            "warnings": [f"{type(exc).__name__}: {exc}"],
        })
        status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return ProviderResult(
            provider="deepline_builtwith", query=domain, incomplete=True,
            warnings=list(status["warnings"]), raw_payload_location=status.get("raw_payload_location"),
        )


def replay_deepline_technologies(
    run_dir: Path, domain: str, *, response_path: Path | None = None
) -> ProviderResult:
    """Re-normalize a saved paid BuiltWith envelope without another provider call."""
    domain = _domain(domain)
    _validate_run_domain(run_dir, domain)
    status_path = run_dir / "normalized" / "deepline_collection.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    relative = Path(response_path) if response_path else Path(str(status.get("raw_payload_location", "")))
    raw_path = relative if relative.is_absolute() else run_dir / relative
    resolved = raw_path.resolve()
    try:
        relative = resolved.relative_to(run_dir.resolve())
    except ValueError as exc:
        raise ValueError("saved BuiltWith response must be inside the account run") from exc
    raw = resolved.read_bytes()
    expected = status.get("response_sha256")
    if expected and expected != _sha256(raw):
        raise ValueError("saved BuiltWith response hash does not match collection status")
    envelope = json.loads(raw)
    provider_payload = _provider_payload(envelope)
    provider_errors = provider_payload.get("Errors") or []
    if provider_errors:
        raise RuntimeError(f"BuiltWith returned {len(provider_errors)} provider error(s)")
    warnings: list[str] = []
    normalized = [asdict(item) for item in normalize_deepline_builtwith(
        provider_payload, observed_at=_now(), warnings=warnings
    )]
    profile_path = run_dir / "normalized" / "external_profile.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8")) if profile_path.is_file() else {}
    profile.update({"schema_version": "1.0", "domain": domain, "technologies": normalized})
    profile.setdefault("ads", [])
    profile.setdefault("gap_observations", [])
    profile_path.write_text(json.dumps(profile, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    status.update({
        "finished_at": _now(), "status": "completed", "incomplete": False,
        "records": len(normalized), "warnings": warnings, "replayed": True,
        "raw_payload_location": str(relative), "response_sha256": _sha256(raw),
    })
    status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return ProviderResult(
        provider="deepline_builtwith", query=domain, records=normalized,
        raw_payload_location=str(relative), warnings=warnings,
    )
