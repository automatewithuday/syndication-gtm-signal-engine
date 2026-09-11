from __future__ import annotations

import hashlib
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

from .collector import canonicalize_url
from .external_signals import AdObservation, parse_campaign_url
from .providers import ProviderResult
from .vault import MacOSKeychainVault, SecretVault

SUPPORTED_CONFIG_VERSIONS = {"apify_ads_v1", "apify_ads_v2"}
APIFY_NORMALIZER_VERSION = "apify_ads_normalizer_v2"
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "apify_ads.v2.json"
TERMINAL_RUN_STATUSES = {"SUCCEEDED", "FAILED", "TIMED-OUT", "ABORTED"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _default_config() -> Path:
    candidates = (
        Path.cwd() / "config" / "apify_ads.v2.json",
        DEFAULT_CONFIG_PATH,
        Path(sys.prefix) / "share" / "gtm-signal-engine" / "apify_ads.v2.json",
    )
    return next((candidate for candidate in candidates if candidate.exists()), candidates[0])


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
        raise ValueError("Apify observations must attach to a ScraplingFetcher run")
    if _domain(str(manifest.get("seed_url", ""))) != domain:
        raise ValueError("Apify domain does not match the saved website run")


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    body: bytes


class ApifyTransport(Protocol):
    def request(
        self, method: str, url: str, *, headers: dict[str, str], body: bytes | None, timeout: int
    ) -> HttpResponse: ...


class UrllibApifyTransport:
    def request(
        self, method: str, url: str, *, headers: dict[str, str], body: bytes | None, timeout: int
    ) -> HttpResponse:
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return HttpResponse(response.status, response.read())
        except urllib.error.HTTPError as exc:
            return HttpResponse(exc.code, exc.read())


def _request_json(
    transport: ApifyTransport,
    method: str,
    url: str,
    *,
    token: str | None = None,
    payload: dict[str, Any] | None = None,
    timeout: int = 90,
) -> tuple[Any, bytes]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    response = transport.request(method, url, headers=headers, body=body, timeout=timeout)
    try:
        parsed = json.loads(response.body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Apify returned non-JSON HTTP {response.status_code}") from exc
    if not 200 <= response.status_code < 300:
        message = parsed.get("error", {}).get("message") if isinstance(parsed, dict) else None
        raise RuntimeError(f"Apify HTTP {response.status_code}: {message or 'request failed'}")
    return parsed, response.body


def _write_raw(raw_dir: Path, prefix: str, body: bytes) -> tuple[str, str]:
    digest = _sha256(body)
    path = raw_dir / f"{prefix}-{digest[:16]}.json"
    path.write_bytes(body)
    return str(path), digest


def _account_search_urls(
    account_name: str, config: dict[str, Any], *, linkedin_company_id: str | None = None
) -> dict[str, str]:
    country = str(config["country"])
    date_option = str(config["date_option"])
    linkedin_query = (
        urllib.parse.urlencode({"companyIds": linkedin_company_id})
        if linkedin_company_id
        else urllib.parse.urlencode({
            "accountOwner": account_name, "countries": country, "dateOption": date_option,
        })
    )
    meta_query = urllib.parse.urlencode({
        "active_status": "active", "ad_type": "all", "country": "ALL",
        "q": account_name, "search_type": str(config.get("meta_search_type", "keyword_unordered")),
    })
    return {
        "linkedin": f"https://www.linkedin.com/ad-library/search?{linkedin_query}",
        "meta": f"https://www.facebook.com/ads/library/?{meta_query}",
    }


def _actor_input(platform: str, search_url: str, results_limit: int) -> dict[str, Any]:
    if platform == "linkedin":
        return {"startUrls": [{"url": search_url}], "resultsLimit": results_limit, "skipDetails": False}
    if platform == "meta":
        return {
            "startUrls": [{"url": search_url}], "resultsLimit": results_limit,
            "onlyTotal": False, "includeAboutPage": False, "isDetailsPerAd": False,
            "activeStatus": "active", "enrichWithEcommerceData": False,
        }
    raise ValueError(f"unsupported ad platform {platform!r}")


def _matches_domain(url: str, domain: str) -> bool:
    hostname = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    return hostname == domain or hostname.endswith(f".{domain}")


def _normalized_name(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _attributable(*, advertiser_name: str, account_name: str, destination: str, domain: str) -> bool:
    exact_name = bool(advertiser_name) and _normalized_name(advertiser_name) == _normalized_name(account_name)
    return exact_name or _matches_domain(destination, domain)


def _first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            nested = value.get("text") or value.get("value")
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
    return ""


def _timestamp(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), timezone.utc).isoformat()
    return str(value)


def _meta_links(record: dict[str, Any]) -> list[str]:
    snapshot = record.get("snapshot") if isinstance(record.get("snapshot"), dict) else {}
    candidates = [record.get("linkUrl"), snapshot.get("linkUrl")]
    cards = snapshot.get("cards") if isinstance(snapshot.get("cards"), list) else []
    candidates.extend(card.get("linkUrl") for card in cards if isinstance(card, dict))
    return [str(value) for value in candidates if isinstance(value, str) and canonicalize_url(value)]


def _meta_ad_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Accept both direct ad rows and the actor's zero/small-result envelope."""
    flattened: list[dict[str, Any]] = []
    for record in records:
        nested = record.get("results")
        if isinstance(nested, list):
            flattened.extend(item for item in nested if isinstance(item, dict))
        else:
            flattened.append(record)
    return flattened


def normalize_apify_linkedin(
    records: list[dict[str, Any]], *, domain: str, account_name: str, observed_at: str
) -> tuple[list[AdObservation], list[str]]:
    observations: list[AdObservation] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for index, record in enumerate(records):
        record_id = str(record.get("adId") or "")
        destination = str(record.get("clickUrl") or "")
        advertiser_name = str(record.get("advertiserName") or "")
        if (
            not record_id or not _attributable(
                advertiser_name=advertiser_name, account_name=account_name,
                destination=destination, domain=domain,
            )
        ):
            warnings.append(f"linkedin record {index} skipped: missing ID or account attribution")
            continue
        if record_id in seen:
            continue
        seen.add(record_id)
        availability = record.get("availability") if isinstance(record.get("availability"), dict) else {}
        creative = " — ".join(filter(None, [
            _first_text(record.get("headline")), _first_text(record.get("body")),
        ]))
        observations.append(AdObservation(
            platform="linkedin", provider_record_id=record_id, creative_text=creative,
            destination=parse_campaign_url(destination) if canonicalize_url(destination) else None,
            source_url=str(record.get("adLibraryUrl") or f"https://www.linkedin.com/ad-library/detail/{record_id}"),
            observed_at=observed_at, first_seen_at=availability.get("start"),
            last_seen_at=availability.get("end"), confidence=0.9,
            method="apify_linkedin_ads_v1", normalizer_version=APIFY_NORMALIZER_VERSION,
        ))
    return observations, warnings


def normalize_apify_meta(
    records: list[dict[str, Any]], *, domain: str, account_name: str, observed_at: str
) -> tuple[list[AdObservation], list[str]]:
    observations: list[AdObservation] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for index, record in enumerate(_meta_ad_records(records)):
        record_id = str(record.get("adArchiveID") or record.get("adArchiveId") or record.get("adId") or "")
        links = _meta_links(record)
        destination = next((url for url in links if _matches_domain(url, domain)), links[0] if links else "")
        snapshot = record.get("snapshot") if isinstance(record.get("snapshot"), dict) else {}
        advertiser_name = str(record.get("pageName") or snapshot.get("pageName") or "")
        if (
            not record_id or not _attributable(
                advertiser_name=advertiser_name, account_name=account_name,
                destination=destination, domain=domain,
            )
        ):
            warnings.append(f"meta record {index} skipped: missing ID or account attribution")
            continue
        if record_id in seen:
            continue
        seen.add(record_id)
        cards = snapshot.get("cards") if isinstance(snapshot.get("cards"), list) else []
        card = next((item for item in cards if isinstance(item, dict)), {})
        creative = " — ".join(filter(None, [
            _first_text(snapshot.get("title"), card.get("title")),
            _first_text(snapshot.get("body"), card.get("body")),
        ]))
        observations.append(AdObservation(
            platform="meta", provider_record_id=record_id, creative_text=creative,
            destination=parse_campaign_url(destination) if destination else None,
            source_url=f"https://www.facebook.com/ads/library/?id={record_id}",
            observed_at=observed_at,
            first_seen_at=_timestamp(record.get("startDateFormatted") or record.get("startDate")),
            last_seen_at=_timestamp(record.get("endDateFormatted") or record.get("endDate")),
            confidence=0.9, method="apify_meta_ads_v1", normalizer_version=APIFY_NORMALIZER_VERSION,
        ))
    return observations, warnings


def _actor_url(actor_id: str) -> str:
    return f"https://api.apify.com/v2/actors/{urllib.parse.quote(actor_id, safe='~')}"


def _run_actor(
    platform: str,
    actor: dict[str, Any],
    actor_input: dict[str, Any],
    *,
    token: str,
    transport: ApifyTransport,
    raw_dir: Path,
    config: dict[str, Any],
    run_dir: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    actor_id = str(actor["actor_id"])
    metadata, metadata_raw = _request_json(transport, "GET", _actor_url(actor_id))
    actor_data = metadata.get("data", {}) if isinstance(metadata, dict) else {}
    if actor_data.get("isDeprecated") is True or actor_data.get("isPublic") is not True:
        raise RuntimeError(f"configured {platform} actor is deprecated or unavailable")
    metadata_path, metadata_sha = _write_raw(raw_dir, f"apify-{platform}-actor", metadata_raw)
    query = urllib.parse.urlencode({
        "build": actor["build"],
        "timeout": int(config["actor_timeout_seconds"]),
        "maxItems": int(config["results_limit"]),
        "maxTotalChargeUsd": float(actor["max_total_charge_usd"]),
        "restartOnError": "false",
    })
    initiation, initiation_raw = _request_json(
        transport, "POST", f"{_actor_url(actor_id)}/runs?{query}", token=token,
        payload=actor_input, timeout=90,
    )
    initiation_path, initiation_sha = _write_raw(raw_dir, f"apify-{platform}-run-start", initiation_raw)
    run = initiation.get("data", {}) if isinstance(initiation, dict) else {}
    last_run_raw = initiation_raw
    run_id = str(run.get("id") or "")
    if not run_id:
        raise RuntimeError(f"Apify {platform} response lacks a run ID")
    polls = 0
    while str(run.get("status")) not in TERMINAL_RUN_STATUSES and polls < int(config["maximum_polls"]):
        polls += 1
        run_payload, run_raw = _request_json(
            transport, "GET",
            f"https://api.apify.com/v2/actor-runs/{run_id}?waitForFinish={int(config['poll_wait_seconds'])}",
            token=token, timeout=int(config["poll_wait_seconds"]) + 15,
        )
        run = run_payload.get("data", {}) if isinstance(run_payload, dict) else {}
        last_run_raw = run_raw
    final_path, final_sha = _write_raw(raw_dir, f"apify-{platform}-run-final", last_run_raw)
    if str(run.get("status")) != "SUCCEEDED":
        raise RuntimeError(f"Apify {platform} run {run_id} ended with status {run.get('status')!r}")
    dataset_id = str(run.get("defaultDatasetId") or "")
    if not dataset_id:
        raise RuntimeError(f"Apify {platform} run {run_id} lacks a dataset ID")
    items, items_raw = _request_json(
        transport, "GET",
        f"https://api.apify.com/v2/datasets/{dataset_id}/items?format=json&clean=true&limit={int(config['results_limit'])}",
        token=token, timeout=90,
    )
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise RuntimeError(f"Apify {platform} dataset must contain JSON objects")
    dataset_path, dataset_sha = _write_raw(raw_dir, f"apify-{platform}-dataset", items_raw)
    return items, {
        "actor_id": actor_id, "build": actor["build"], "store_url": actor["store_url"],
        "run_id": run_id, "status": run.get("status"), "dataset_id": dataset_id,
        "usage_total_usd": run.get("usageTotalUsd"), "charged_event_counts": run.get("chargedEventCounts"),
        "raw": {
            "actor_metadata": str(Path(metadata_path).relative_to(run_dir)),
            "run_start": str(Path(initiation_path).relative_to(run_dir)),
            "run_final": str(Path(final_path).relative_to(run_dir)),
            "dataset": str(Path(dataset_path).relative_to(run_dir)),
        },
        "sha256": {
            "actor_metadata": metadata_sha, "run_start": initiation_sha,
            "run_final": final_sha, "dataset": dataset_sha,
        },
    }


def collect_apify_ads(
    run_dir: Path,
    domain: str,
    *,
    account_name: str,
    linkedin_company_id: str | None = None,
    config_path: Path | None = None,
    platforms: tuple[str, ...] = ("linkedin", "meta"),
    vault: SecretVault | None = None,
    transport: ApifyTransport | None = None,
) -> ProviderResult:
    domain = _domain(domain)
    if not account_name.strip():
        raise ValueError("account name is required")
    if linkedin_company_id is not None and not linkedin_company_id.isdigit():
        raise ValueError("LinkedIn company ID must contain digits only")
    if not platforms or set(platforms).difference({"linkedin", "meta"}):
        raise ValueError("platforms must contain linkedin, meta, or both")
    _validate_run_domain(run_dir, domain)
    selected_config = config_path or _default_config()
    config_bytes = selected_config.read_bytes()
    config = json.loads(config_bytes)
    if config.get("version") not in SUPPORTED_CONFIG_VERSIONS:
        raise ValueError("unsupported Apify collection configuration")
    raw_dir = run_dir / "raw"
    normalized_dir = run_dir / "normalized"
    raw_dir.mkdir(parents=True, exist_ok=True)
    normalized_dir.mkdir(parents=True, exist_ok=True)
    status_path = normalized_dir / "apify_collection.json"
    previous_status = (
        json.loads(status_path.read_text(encoding="utf-8")) if status_path.is_file() else {}
    )
    selected_platforms = tuple(dict.fromkeys(platforms))
    retained_platform_status = {
        key: value for key, value in previous_status.get("platforms", {}).items()
        if key not in set(selected_platforms)
    }
    status: dict[str, Any] = {
        "schema_version": "1.0", "collector_version": config["version"],
        "normalizer_version": APIFY_NORMALIZER_VERSION,
        "domain": domain, "account_name": account_name.strip(), "started_at": _now(),
        "finished_at": None, "status": "running", "incomplete": True,
        "config_sha256": _sha256(config_bytes), "platforms": retained_platform_status,
        "request_policy": {
            "automatic_paid_retries": False,
            "max_items_per_actor": int(config["results_limit"]),
            "max_total_charge_usd_per_actor": {
                key: float(value["max_total_charge_usd"]) for key, value in config["actors"].items()
            },
        },
        "selected_platforms": list(selected_platforms), "warnings": [],
    }
    status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        token = (vault or MacOSKeychainVault()).get_secret("apify-token")
    except Exception as exc:
        status.update({
            "finished_at": _now(), "status": "blocked", "incomplete": True,
            "warnings": [f"{type(exc).__name__}: Apify token unavailable in configured vault"],
        })
        status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return ProviderResult(
            provider="apify_ads", query=domain, incomplete=True, warnings=list(status["warnings"]),
        )
    transport = transport or UrllibApifyTransport()
    search_urls = _account_search_urls(
        account_name.strip(), config, linkedin_company_id=linkedin_company_id
    )
    observations: list[AdObservation] = []
    for platform in selected_platforms:
        try:
            actor_input = _actor_input(platform, search_urls[platform], int(config["results_limit"]))
            records, platform_status = _run_actor(
                platform, config["actors"][platform], actor_input, token=token,
                transport=transport, raw_dir=raw_dir, config=config, run_dir=run_dir,
            )
            normalized, warnings = (
                normalize_apify_linkedin(
                    records, domain=domain, account_name=account_name.strip(), observed_at=_now()
                )
                if platform == "linkedin"
                else normalize_apify_meta(
                    records, domain=domain, account_name=account_name.strip(), observed_at=_now()
                )
            )
            observations.extend(normalized)
            candidate_records = len(records) if platform == "linkedin" else len(_meta_ad_records(records))
            status["platforms"][platform] = {
                **platform_status, "raw_records": len(records), "normalized_records": len(normalized),
                "candidate_records": candidate_records,
                "search_url": search_urls[platform], "warnings": warnings,
                "search_identity": (
                    {"type": "linkedin_company_id", "value": linkedin_company_id}
                    if platform == "linkedin" and linkedin_company_id
                    else {"type": "account_name", "value": account_name.strip()}
                ),
            }
            status["warnings"].extend(warnings)
        except Exception as exc:
            warning = f"{platform}: {type(exc).__name__}: {exc}"
            status["platforms"][platform] = {"status": "failed", "warning": warning}
            status["warnings"].append(warning)
    completed = all(item.get("status") == "SUCCEEDED" for item in status["platforms"].values())
    profile_path = normalized_dir / "external_profile.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8")) if profile_path.is_file() else {}
    retained_ads = [
        item for item in profile.get("ads", []) if item.get("platform") not in set(selected_platforms)
    ]
    profile.update({
        "schema_version": "1.0", "domain": domain,
        "ads": [*retained_ads, *[asdict(item) for item in observations]],
    })
    profile.setdefault("technologies", [])
    profile.setdefault("gap_observations", [])
    profile_path.write_text(json.dumps(profile, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    status.update({
        "finished_at": _now(), "status": "completed" if completed else "partial",
        "incomplete": not completed, "records": len(observations),
    })
    status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    raw_locations = [
        details["raw"]["dataset"] for details in status["platforms"].values() if details.get("raw")
    ]
    return ProviderResult(
        provider="apify_ads", query=domain, records=[asdict(item) for item in observations],
        raw_payload_location=",".join(raw_locations) or None,
        incomplete=not completed, warnings=list(status["warnings"]),
    )


def replay_apify_ads(
    run_dir: Path, domain: str, *, account_name: str
) -> ProviderResult:
    """Re-normalize saved actor datasets without starting another paid run."""
    domain = _domain(domain)
    _validate_run_domain(run_dir, domain)
    status_path = run_dir / "normalized" / "apify_collection.json"
    if not status_path.is_file():
        raise FileNotFoundError("saved Apify collection status is required for replay")
    status = json.loads(status_path.read_text(encoding="utf-8"))
    observations: list[AdObservation] = []
    warnings: list[str] = []
    for platform, details in status.get("platforms", {}).items():
        if platform not in {"linkedin", "meta"}:
            warnings.append(f"{platform}: unsupported saved platform")
            continue
        location = details.get("raw", {}).get("dataset")
        if not location:
            warnings.append(f"{platform}: saved dataset location is unavailable")
            continue
        records = json.loads((run_dir / location).read_text(encoding="utf-8"))
        normalized, platform_warnings = (
            normalize_apify_linkedin(
                records, domain=domain, account_name=account_name, observed_at=_now()
            )
            if platform == "linkedin"
            else normalize_apify_meta(
                records, domain=domain, account_name=account_name, observed_at=_now()
            )
        )
        observations.extend(normalized)
        warnings.extend(platform_warnings)
        details["candidate_records"] = (
            len(records) if platform == "linkedin" else len(_meta_ad_records(records))
        )
        details["normalized_records"] = len(normalized)
        details["warnings"] = platform_warnings
    profile_path = run_dir / "normalized" / "external_profile.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8")) if profile_path.is_file() else {}
    replayed_platforms = set(status.get("platforms", {}))
    retained_ads = [item for item in profile.get("ads", []) if item.get("platform") not in replayed_platforms]
    profile.update({
        "schema_version": "1.0", "domain": domain,
        "ads": [*retained_ads, *[asdict(item) for item in observations]],
    })
    profile.setdefault("technologies", [])
    profile.setdefault("gap_observations", [])
    profile_path.write_text(json.dumps(profile, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    status.update({
        "normalizer_version": APIFY_NORMALIZER_VERSION, "replayed_at": _now(),
        "records": len(observations), "warnings": warnings,
    })
    status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return ProviderResult(
        provider="apify_ads_replay", query=domain,
        records=[asdict(item) for item in observations], warnings=warnings,
    )
