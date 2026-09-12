from __future__ import annotations

import hashlib
import html
import json
import re
import subprocess
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, Sequence
from urllib.parse import urlsplit

from .collector import canonicalize_url
from .external_signals import AdObservation, parse_campaign_url
from .providers import ProviderResult

ADYNTEL_COLLECTION_VERSION = "adyntel_ads_v1"
ADYNTEL_NORMALIZER_VERSION = "adyntel_ads_normalizer_v1"
TOOL_IDS = {
    "meta": "adyntel_facebook",
    "linkedin": "adyntel_linkedin",
    "google": "adyntel_google",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


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
        raise ValueError("Adyntel observations must attach to a ScraplingFetcher run")
    if _domain(str(manifest.get("seed_url", ""))) != domain:
        raise ValueError("Adyntel domain does not match the saved website run")


class DeeplineCliRunner(Protocol):
    def run(self, arguments: Sequence[str]) -> subprocess.CompletedProcess[str]: ...


class SubprocessDeeplineCliRunner:
    """Run Deepline without copying its credential into this process."""

    def run(self, arguments: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["deepline", *arguments], check=False, capture_output=True, text=True
        )


def _run_json(
    runner: DeeplineCliRunner, arguments: Sequence[str]
) -> tuple[dict[str, Any], bytes]:
    completed = runner.run(arguments)
    if completed.returncode != 0:
        detail = completed.stderr.strip().splitlines()[-1] if completed.stderr.strip() else "no diagnostic"
        raise RuntimeError(f"Deepline command failed with exit {completed.returncode}: {detail}")
    raw = completed.stdout.encode("utf-8")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Deepline command must return one JSON object")
    if payload.get("ok") is False:
        error = payload.get("error", {})
        raise RuntimeError(str(error.get("message") or "Deepline tool execution failed"))
    return payload, raw


def _validate_contract(contract: dict[str, Any], platform: str) -> None:
    tool_id = TOOL_IDS[platform]
    if contract.get("toolId") != tool_id or contract.get("callable") is not True:
        raise ValueError(f"Deepline {tool_id} tool is missing or not callable")
    if contract.get("connected") is not True:
        raise ValueError(f"Deepline {tool_id} tool is not connected")
    properties = contract.get("inputSchema", {}).get("jsonSchema", {}).get("properties", {})
    if "company_domain" not in properties:
        raise ValueError(f"live {tool_id} contract lacks company_domain")


def _provider_payload(envelope: dict[str, Any]) -> dict[str, Any] | None:
    response = envelope.get("toolResponse", {})
    if not isinstance(response, dict):
        return None
    for key in ("rawV2", "raw"):
        candidate = response.get(key)
        if isinstance(candidate, dict):
            return candidate
    return None


def _write_raw(raw_dir: Path, prefix: str, body: bytes) -> tuple[str, str]:
    digest = _sha256(body)
    path = raw_dir / f"{prefix}-{digest[:16]}.json"
    path.write_bytes(body)
    return str(path), digest


def _plain_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = re.sub(r"<[^>]+>", " ", html.unescape(value))
    return " ".join(cleaned.split()).strip()


def _nested_text(record: dict[str, Any], key: str, field: str = "text") -> str:
    value = record.get(key)
    return _plain_text(value.get(field)) if isinstance(value, dict) else _plain_text(value)


def _timestamp(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), timezone.utc).isoformat()
    return str(value)


def _destination(value: Any):
    if isinstance(value, str) and canonicalize_url(value):
        return parse_campaign_url(value)
    return None


def normalize_adyntel_ads(
    platform: str, payload: dict[str, Any], *, observed_at: str
) -> tuple[list[AdObservation], list[str]]:
    if platform not in TOOL_IDS:
        raise ValueError(f"unsupported Adyntel platform {platform!r}")
    records = payload.get("ads", payload.get("results"))
    if not isinstance(records, list):
        raise ValueError(f"Adyntel {platform} payload lacks an ads list")
    observations: list[AdObservation] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            warnings.append(f"{platform} record {index} skipped: not an object")
            continue
        record_id = str(
            record.get("ad_id")
            or record.get("creative_id")
            or record.get("adArchiveID")
            or record.get("ad_archive_id")
            or ""
        )
        if not record_id:
            warnings.append(f"{platform} record {index} skipped: missing provider ID")
            continue
        if record_id in seen:
            continue
        seen.add(record_id)

        advertiser = record.get("advertiser") if isinstance(record.get("advertiser"), dict) else {}
        headline = record.get("headline") if isinstance(record.get("headline"), dict) else {}
        snapshot = record.get("snapshot") if isinstance(record.get("snapshot"), dict) else {}
        variants = record.get("variants") if isinstance(record.get("variants"), list) else []
        variant_text = next(
            (_plain_text(item.get("content")) for item in variants if isinstance(item, dict) and _plain_text(item.get("content"))),
            "",
        )
        creative = " — ".join(filter(None, [
            _nested_text(record, "commentary"),
            _plain_text(headline.get("title")),
            _nested_text(snapshot, "body"),
            _plain_text(record.get("primary_text") or record.get("body") or record.get("ad_creative_body") or snapshot.get("title")),
            variant_text,
        ]))
        advertiser_name = _plain_text(
            advertiser.get("name") or record.get("advertiser_name") or record.get("page_name") or snapshot.get("page_name")
        )
        if not creative:
            creative = " — ".join(filter(None, [advertiser_name, _plain_text(record.get("format") or record.get("type"))]))

        source_url = str(
            record.get("view_details_link")
            or record.get("original_url")
            or record.get("ad_library_url")
            or record.get("url")
            or (
                f"https://www.linkedin.com/ad-library/detail/{record_id}"
                if platform == "linkedin"
                else f"https://www.facebook.com/ads/library/?id={record_id}"
                if platform == "meta"
                else ""
            )
        )
        if not canonicalize_url(source_url):
            warnings.append(f"{platform} record {index} skipped: missing evidence URL")
            continue
        eu = record.get("eu_transparency") if isinstance(record.get("eu_transparency"), dict) else {}
        destination_url = (
            record.get("destinationUrl") or record.get("destination_url")
            or record.get("link_url") or snapshot.get("link_url")
        )
        observations.append(AdObservation(
            platform=platform,
            provider_record_id=record_id,
            creative_text=creative,
            destination=_destination(destination_url),
            source_url=source_url,
            observed_at=observed_at,
            first_seen_at=_timestamp(record.get("start") or record.get("start_date_string") or record.get("start_date") or eu.get("startDate")),
            last_seen_at=_timestamp(record.get("last_seen") or record.get("end_date_string") or record.get("end_date") or eu.get("endDate")),
            confidence=0.9,
            method=f"deepline_{TOOL_IDS[platform]}_v1",
            normalizer_version=ADYNTEL_NORMALIZER_VERSION,
        ))
    return observations, warnings


def _total_records(payload: dict[str, Any], returned: int) -> int | None:
    for key in ("total_ads", "total_ad_count", "total_count", "number_of_ads"):
        value = payload.get(key)
        if isinstance(value, int) and value >= 0:
            return value
    return returned


def collect_adyntel_ads(
    run_dir: Path,
    domain: str,
    *,
    linkedin_page_id: str | None = None,
    platforms: tuple[str, ...] = ("meta", "linkedin", "google"),
    runner: DeeplineCliRunner | None = None,
) -> ProviderResult:
    """Collect one paid Adyntel request per selected channel through Deepline."""
    domain = _domain(domain)
    if linkedin_page_id is not None and not linkedin_page_id.isdigit():
        raise ValueError("LinkedIn page ID must contain digits only")
    if not platforms or set(platforms).difference(TOOL_IDS):
        raise ValueError("platforms must contain meta, linkedin, or google")
    _validate_run_domain(run_dir, domain)
    selected_platforms = tuple(dict.fromkeys(platforms))
    runner = runner or SubprocessDeeplineCliRunner()
    raw_dir = run_dir / "raw"
    normalized_dir = run_dir / "normalized"
    raw_dir.mkdir(parents=True, exist_ok=True)
    normalized_dir.mkdir(parents=True, exist_ok=True)
    status_path = normalized_dir / "adyntel_collection.json"
    previous_status = json.loads(status_path.read_text()) if status_path.is_file() else {}
    retained_status = {
        key: value for key, value in previous_status.get("platforms", {}).items()
        if key not in set(selected_platforms)
    }
    status: dict[str, Any] = {
        "schema_version": "1.0",
        "collector_version": ADYNTEL_COLLECTION_VERSION,
        "normalizer_version": ADYNTEL_NORMALIZER_VERSION,
        "provider": "adyntel",
        "domain": domain,
        "started_at": _now(),
        "finished_at": None,
        "status": "running",
        "incomplete": True,
        "selected_platforms": list(selected_platforms),
        "platforms": retained_status,
        "request_policy": {
            "one_paid_request_per_selected_platform": True,
            "automatic_paid_retries": False,
            "credits_per_request": 0.13,
            "usd_per_request": 0.013,
        },
        "warnings": [],
    }
    status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")
    observations_by_platform: dict[str, list[AdObservation]] = {}
    for platform in selected_platforms:
        tool_id = TOOL_IDS[platform]
        audit: dict[str, Any] = {"tool_id": tool_id}
        try:
            contract, contract_raw = _run_json(runner, ["tools", "get", tool_id, "--json"])
            _validate_contract(contract, platform)
            contract_path, contract_sha = _write_raw(raw_dir, f"deepline-{tool_id}-contract", contract_raw)
            audit.update({
                "raw": {"contract": str(Path(contract_path).relative_to(run_dir))},
                "sha256": {"contract": contract_sha},
            })
            request: dict[str, Any] = {"company_domain": domain}
            # The live CLI currently coerces page IDs to integers while Adyntel requires a string.
            # Domain lookup resolves the same page safely, so page ID is audit metadata until fixed upstream.
            if platform == "linkedin" and linkedin_page_id:
                request["resolved_linkedin_page_id_hint"] = linkedin_page_id
            execution_request = {"company_domain": domain}
            envelope, envelope_raw = _run_json(runner, [
                "tools", "execute", tool_id, "--input",
                json.dumps(execution_request, separators=(",", ":")), "--json",
            ])
            execution_path, execution_sha = _write_raw(raw_dir, f"deepline-{tool_id}-response", envelope_raw)
            audit.update({
                "job_id": envelope.get("job_id"), "billing": envelope.get("billing"),
                "request": request,
            })
            audit["raw"]["response"] = str(Path(execution_path).relative_to(run_dir))
            audit["sha256"]["response"] = execution_sha
            payload = _provider_payload(envelope)
            if payload is None:
                warning = f"{platform}: completed request returned no provider payload; result is inconclusive"
                status["warnings"].append(warning)
                status["platforms"][platform] = {
                    "status": "inconclusive", "incomplete": True, "warning": warning,
                    **audit,
                }
                continue
            normalized, warnings = normalize_adyntel_ads(platform, payload, observed_at=_now())
            observations_by_platform[platform] = normalized
            provider_records = payload.get("ads", payload.get("results", []))
            returned = len(provider_records)
            total = _total_records(payload, returned)
            continuation = payload.get("continuation_token")
            truncated = not (total == 0 and returned == 0) and (
                bool(continuation) or (total is not None and total > returned)
            )
            platform_status = "partial" if truncated else "completed"
            if truncated:
                warnings.append(
                    f"{platform}: provider reports {total} ads but returned {returned}; total is preserved and rows are partial"
                )
            status["warnings"].extend(warnings)
            status["platforms"][platform] = {
                "status": platform_status, "incomplete": truncated,
                **audit,
                "returned_records": returned, "provider_total_records": total,
                "normalized_records": len(normalized),
                "has_continuation_token": bool(continuation), "warnings": warnings,
            }
        except Exception as exc:
            warning = f"{platform}: {type(exc).__name__}: {exc}"
            status["warnings"].append(warning)
            status["platforms"][platform] = {
                **audit, "status": "failed", "incomplete": True, "warning": warning,
            }

    profile_path = normalized_dir / "external_profile.json"
    profile = json.loads(profile_path.read_text()) if profile_path.is_file() else {}
    replaced_platforms = set(observations_by_platform)
    retained_ads = [
        item for item in profile.get("ads", []) if item.get("platform") not in replaced_platforms
    ]
    normalized_ads = [
        asdict(item) for platform in selected_platforms for item in observations_by_platform.get(platform, [])
    ]
    profile.update({
        "schema_version": "1.0", "domain": domain,
        "ads": [*retained_ads, *normalized_ads],
    })
    profile.setdefault("technologies", [])
    profile.setdefault("gap_observations", [])
    profile_path.write_text(json.dumps(profile, indent=2, sort_keys=True) + "\n")
    selected_details = [status["platforms"][key] for key in selected_platforms]
    incomplete = any(item.get("incomplete", True) for item in selected_details)
    status.update({
        "finished_at": _now(), "status": "partial" if incomplete else "completed",
        "incomplete": incomplete, "records": len(normalized_ads),
    })
    status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")
    raw_locations = [
        item.get("raw", {}).get("response") for item in selected_details if item.get("raw", {}).get("response")
    ]
    return ProviderResult(
        provider="deepline_adyntel_ads", query=domain,
        records=normalized_ads, raw_payload_location=",".join(raw_locations) or None,
        incomplete=incomplete, warnings=list(status["warnings"]),
    )


def replay_adyntel_response(
    run_dir: Path, domain: str, *, platform: str, response_path: Path
) -> ProviderResult:
    """Re-normalize one saved Deepline envelope without another paid request."""
    domain = _domain(domain)
    _validate_run_domain(run_dir, domain)
    if platform not in TOOL_IDS:
        raise ValueError(f"unsupported Adyntel platform {platform!r}")
    try:
        relative_response = response_path.resolve().relative_to(run_dir.resolve())
    except ValueError as exc:
        raise ValueError("saved response must be inside the account run directory") from exc
    raw = response_path.read_bytes()
    envelope = json.loads(raw)
    if not isinstance(envelope, dict):
        raise ValueError("saved Deepline response must be one JSON object")
    payload = _provider_payload(envelope)
    if payload is None:
        raise ValueError("saved Deepline response has no provider payload")
    observations, warnings = normalize_adyntel_ads(platform, payload, observed_at=_now())
    provider_records = payload.get("ads", payload.get("results", []))
    returned = len(provider_records)
    total = _total_records(payload, returned)
    truncated = not (total == 0 and returned == 0) and (
        bool(payload.get("continuation_token")) or (total is not None and total > returned)
    )
    if truncated:
        warnings.append(
            f"{platform}: provider reports {total} ads but returned {returned}; total is preserved and rows are partial"
        )

    normalized_dir = run_dir / "normalized"
    status_path = normalized_dir / "adyntel_collection.json"
    status = json.loads(status_path.read_text()) if status_path.is_file() else {
        "schema_version": "1.0", "collector_version": ADYNTEL_COLLECTION_VERSION,
        "normalizer_version": ADYNTEL_NORMALIZER_VERSION, "provider": "adyntel",
        "domain": domain, "platforms": {}, "warnings": [],
    }
    status["platforms"][platform] = {
        "status": "partial" if truncated else "completed", "incomplete": truncated,
        "tool_id": TOOL_IDS[platform], "job_id": envelope.get("job_id"),
        "billing": envelope.get("billing"), "returned_records": returned,
        "provider_total_records": total, "normalized_records": len(observations),
        "has_continuation_token": bool(payload.get("continuation_token")),
        "warnings": warnings, "replayed": True,
        "raw": {"response": str(relative_response)},
        "sha256": {"response": _sha256(raw)},
    }
    status["warnings"] = [
        warning for warning in status.get("warnings", []) if not warning.startswith(f"{platform}:")
    ] + warnings
    incomplete = any(item.get("incomplete", True) for item in status["platforms"].values())
    status.update({
        "finished_at": _now(), "status": "partial" if incomplete else "completed",
        "incomplete": incomplete,
        "records": sum(item.get("normalized_records", 0) for item in status["platforms"].values()),
    })
    status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")

    profile_path = normalized_dir / "external_profile.json"
    profile = json.loads(profile_path.read_text()) if profile_path.is_file() else {}
    retained_ads = [item for item in profile.get("ads", []) if item.get("platform") != platform]
    profile.update({
        "schema_version": "1.0", "domain": domain,
        "ads": [*retained_ads, *[asdict(item) for item in observations]],
    })
    profile.setdefault("technologies", [])
    profile.setdefault("gap_observations", [])
    profile_path.write_text(json.dumps(profile, indent=2, sort_keys=True) + "\n")
    return ProviderResult(
        provider="deepline_adyntel_ads", query=domain,
        records=[asdict(item) for item in observations],
        raw_payload_location=str(relative_response), incomplete=truncated, warnings=warnings,
    )
