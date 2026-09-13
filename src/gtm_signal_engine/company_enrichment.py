from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .external_collection import (
    DeeplineCliRunner,
    SubprocessDeeplineCliRunner,
    _domain,
    _run_json,
    _usage_summary,
)
from .review_queue import DEFAULT_DATABASE_PATH, connect_database

ENRICHMENT_VERSION = "account_company_enrichment_v2"
PROSPEO_TOOL_ID = "prospeo_enrich_company"
IDENTITY_TOOL_ID = "crustdata_v3_company_identify"
FUNDING_DISCOVERY_VERSION = "deepline_crunchbase_discovery_v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _database_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _tool_payload(envelope: dict[str, Any]) -> Any:
    response = envelope.get("toolResponse")
    if isinstance(response, dict):
        for key in ("rawV2", "raw"):
            if response.get(key) is not None:
                return response[key]
    if envelope.get("data") is not None:
        return envelope["data"]
    raise ValueError("Deepline response does not contain a provider payload")


def _validate_contract(contract: dict[str, Any], tool_id: str, field: str) -> None:
    if contract.get("toolId") != tool_id or not contract.get("callable"):
        raise ValueError(f"Deepline company tool is missing or not callable: {tool_id}")
    if contract.get("connected") is not True:
        raise ValueError(f"Deepline company tool is not connected: {tool_id}")
    properties = contract.get("inputSchema", {}).get("jsonSchema", {}).get("properties", {})
    if field not in properties:
        raise ValueError(f"live {tool_id} contract lacks {field}")


def _company_from_prospeo(payload: Any, domain: str) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("company"), dict):
        raise ValueError("Prospeo response does not contain a company record")
    company = payload["company"]
    returned_domain = _domain(str(company.get("domain") or company.get("website") or ""))
    if returned_domain != domain:
        raise ValueError("Prospeo returned a different company domain")
    return company


def _identity_from_crustdata(payload: Any, domain: str) -> dict[str, Any]:
    if not isinstance(payload, list):
        raise ValueError("Crustdata identity response must be a list")
    candidates: list[tuple[float, dict[str, Any]]] = []
    for result in payload:
        if not isinstance(result, dict) or str(result.get("matched_on", "")).lower() != domain:
            continue
        for match in result.get("matches", []):
            if not isinstance(match, dict):
                continue
            basic = match.get("company_data", {}).get("basic_info", {})
            if not isinstance(basic, dict) or not basic.get("primary_domain"):
                continue
            if _domain(str(basic["primary_domain"])) != domain:
                continue
            candidates.append((float(match.get("confidence_score") or 0), match))
    if not candidates:
        raise ValueError("Crustdata did not return an exact domain identity")
    return max(candidates, key=lambda item: item[0])[1]


def _crunchbase_tool(
    runner: DeeplineCliRunner,
) -> tuple[dict[str, Any] | None, dict[str, Any], bytes]:
    catalog, raw = _run_json(
        runner, ["tools", "search", "crunchbase", "--json"]
    )
    tools = catalog.get("tools", [])
    if not isinstance(tools, list):
        raise ValueError("Deepline tool search did not return a tools list")
    matches = [
        item for item in tools
        if isinstance(item, dict)
        and str(item.get("provider", "")).casefold() == "crunchbase"
        and item.get("connected") is True
        and bool(item.get("executeCommand"))
    ]
    if not matches:
        return None, catalog, raw
    selected = sorted(matches, key=lambda item: str(item.get("toolId", "")))[0]
    tool_id = str(selected.get("toolId") or selected.get("id") or "")
    if not tool_id:
        raise ValueError("Deepline Crunchbase catalog row lacks a tool ID")
    contract, _ = _run_json(runner, ["tools", "describe", tool_id, "--json"])
    if (
        contract.get("toolId") != tool_id
        or contract.get("callable") is not True
        or contract.get("connected") is not True
        or str(contract.get("provider", "")).casefold() != "crunchbase"
    ):
        raise ValueError("live Deepline Crunchbase tool is not callable and connected")
    return contract, catalog, raw


def _funding_input(
    contract: dict[str, Any], domain: str, crunchbase_url: str | None,
) -> dict[str, str]:
    properties = contract.get("inputSchema", {}).get("jsonSchema", {}).get("properties", {})
    if crunchbase_url:
        for field in ("crunchbase_url", "organization_url", "company_url"):
            if field in properties:
                return {field: crunchbase_url}
    for field in ("company_domain", "domain", "company_website", "website"):
        if field in properties:
            return {field: domain}
    raise ValueError("live Deepline Crunchbase contract lacks a supported company identifier")


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, dict):
        for key in ("usd", "value", "amount"):
            if key in value:
                return _number(value[key])
    return None


def _canonical_source_url(value: str) -> tuple[str, str]:
    parsed = urlsplit(value if "://" in value else f"https://{value}")
    host = (parsed.hostname or "").casefold()
    if host.startswith("www."):
        host = host[4:]
    return host, parsed.path.rstrip("/").casefold()


def _normalize_crunchbase_funding(
    payload: Any, *, domain: str, crunchbase_url: str | None,
    provider_tool: str, observed_at: str,
) -> dict[str, Any]:
    value = payload
    if isinstance(value, list):
        if len(value) != 1 or not isinstance(value[0], dict):
            raise ValueError("Crunchbase response must identify exactly one company")
        value = value[0]
    if not isinstance(value, dict):
        raise ValueError("Crunchbase response does not contain a company object")
    for key in ("organization", "company", "data", "result"):
        if isinstance(value.get(key), dict):
            value = value[key]
            break
    returned_domain = _domain(str(
        value.get("domain") or value.get("website") or value.get("website_url") or ""
    ))
    returned_crunchbase_url = str(
        value.get("crunchbase_url") or value.get("permalink_url") or value.get("url") or ""
    ) or None
    if returned_domain:
        if returned_domain != domain:
            raise ValueError("Crunchbase returned a different company domain")
    elif crunchbase_url and returned_crunchbase_url:
        if _canonical_source_url(returned_crunchbase_url) != _canonical_source_url(crunchbase_url):
            raise ValueError("Crunchbase returned a different organization URL")
    else:
        raise ValueError("Crunchbase response lacks an attributable company identity")
    rounds = value.get("funding_rounds") or value.get("rounds") or []
    if not isinstance(rounds, list):
        rounds = []
    normalized_rounds = []
    for item in rounds:
        if not isinstance(item, dict):
            continue
        normalized_rounds.append({
            "announced_at": item.get("announced_at") or item.get("announced_on") or item.get("date"),
            "round_type": item.get("round_type") or item.get("funding_type") or item.get("stage"),
            "amount_usd": _number(
                item.get("amount_usd") or item.get("money_raised_usd") or item.get("amount")
            ),
            "source_url": item.get("source_url") or item.get("url"),
        })
    dated_rounds = [item for item in normalized_rounds if item["announced_at"]]
    latest = max(dated_rounds, key=lambda item: str(item["announced_at"])) if dated_rounds else {}
    return {
        "provider": "crunchbase_via_deepline",
        "provider_tool": provider_tool,
        "company_domain": domain,
        "source_url": returned_crunchbase_url or crunchbase_url,
        "total_funding_usd": _number(
            value.get("total_funding_usd") or value.get("funding_total_usd")
            or value.get("total_funding")
        ),
        "round_count": len(normalized_rounds),
        "latest_funding_date": (
            latest.get("announced_at") or value.get("latest_funding_date")
            or value.get("last_funding_date")
        ),
        "latest_round_type": latest.get("round_type") or value.get("latest_round_type"),
        "latest_round_amount_usd": (
            latest.get("amount_usd") or _number(value.get("latest_round_amount_usd"))
        ),
        "rounds": normalized_rounds,
        "observed_at": observed_at,
        "confidence": 0.9,
        "method": "deepline_crunchbase_v1",
        "normalizer_version": FUNDING_DISCOVERY_VERSION,
    }


def _funding_discovery_snapshot(
    *, catalog: dict[str, Any], raw: bytes, domain: str,
    output_root: Path, observed_at: str,
) -> dict[str, Any]:
    """Persist the exact tool catalog used to decide Crunchbase availability."""
    return _write_snapshot(
        envelope=catalog, raw=raw, domain=domain, provider="deepline-tool-catalog",
        tool_id="tools_search_crunchbase",
        output_root=output_root, observed_at=observed_at,
    )


def _collect_funding(
    *, domain: str, crunchbase_url: str | None, runner: DeeplineCliRunner,
    output_root: Path, observed_at: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    snapshots: list[dict[str, Any]] = []
    billing: list[dict[str, Any]] = []
    try:
        contract, catalog, catalog_raw = _crunchbase_tool(runner)
    except Exception as exc:
        return ({
            "required_provider": "crunchbase_via_deepline",
            "status": "provider_discovery_failed",
            "error": f"{type(exc).__name__}: {exc}",
            "observed_at": observed_at,
            "discovery_version": FUNDING_DISCOVERY_VERSION,
        }, snapshots, billing)

    discovery_snapshot = _funding_discovery_snapshot(
        catalog=catalog, raw=catalog_raw, domain=domain,
        output_root=output_root, observed_at=observed_at,
    )
    snapshots.append(discovery_snapshot)
    if contract is None:
        return ({
            "required_provider": "crunchbase_via_deepline",
            "status": "blocked_provider_unavailable",
            "interpretation": (
                "No callable, connected Deepline tool whose provider is exactly Crunchbase "
                "was available; alternative funding providers were not substituted."
            ),
            "observed_at": observed_at,
            "discovery_version": FUNDING_DISCOVERY_VERSION,
            "catalog_response_sha256": discovery_snapshot["response_sha256"],
        }, snapshots, billing)

    tool_id = str(contract["toolId"])
    try:
        request = _funding_input(contract, domain, crunchbase_url)
        envelope, raw = _run_json(runner, [
            "tools", "execute", tool_id, "--input",
            json.dumps(request, separators=(",", ":")), "--json",
        ])
    except Exception as exc:
        return ({
            "required_provider": "crunchbase_via_deepline",
            "provider_tool": tool_id,
            "status": "provider_error",
            "error": f"{type(exc).__name__}: {exc}",
            "observed_at": observed_at,
            "discovery_version": FUNDING_DISCOVERY_VERSION,
        }, snapshots, billing)

    provider_snapshot = _write_snapshot(
        envelope=envelope, raw=raw, domain=domain, provider="crunchbase",
        tool_id=tool_id, output_root=output_root, observed_at=observed_at,
    )
    snapshots.append(provider_snapshot)
    if provider_snapshot.get("billing"):
        billing.append({"provider": "crunchbase", "billing": provider_snapshot["billing"]})
    try:
        normalized = _normalize_crunchbase_funding(
            _tool_payload(envelope), domain=domain, crunchbase_url=crunchbase_url,
            provider_tool=tool_id, observed_at=observed_at,
        )
    except Exception as exc:
        return ({
            "required_provider": "crunchbase_via_deepline",
            "provider_tool": tool_id,
            "status": "normalization_failed",
            "error": f"{type(exc).__name__}: {exc}",
            "observed_at": observed_at,
            "raw_response_sha256": provider_snapshot["response_sha256"],
            "discovery_version": FUNDING_DISCOVERY_VERSION,
        }, snapshots, billing)
    return ({
        "required_provider": "crunchbase_via_deepline",
        "status": "completed",
        "crunchbase_observation": normalized,
        "observed_at": observed_at,
        "raw_response_sha256": provider_snapshot["response_sha256"],
        "discovery_version": FUNDING_DISCOVERY_VERSION,
    }, snapshots, billing)


def get_account(domain: str, database_path: Path = DEFAULT_DATABASE_PATH) -> dict[str, Any] | None:
    domain = _domain(domain)
    with connect_database(database_path) as connection:
        row = connection.execute(
            "SELECT profile_json FROM accounts WHERE account_domain = ?", (domain,)
        ).fetchone()
    if not row:
        return None
    profile = json.loads(row["profile_json"])
    profile.pop("cache_hit", None)
    profile.pop("current_run_billing", None)
    return profile


def _write_snapshot(
    *, envelope: dict[str, Any], raw: bytes, domain: str, provider: str,
    tool_id: str, output_root: Path, observed_at: str,
) -> dict[str, Any]:
    response_hash = _sha256(raw)
    raw_dir = output_root / domain / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"{provider}-{response_hash[:16]}.json"
    if not path.exists():
        path.write_bytes(raw)
    usage = _usage_summary(envelope)
    return {
        "snapshot_id": hashlib.sha256(
            f"{domain}|{provider}|{response_hash}".encode("utf-8")
        ).hexdigest(),
        "provider": provider,
        "provider_tool": tool_id,
        "provider_record_id": None,
        "response_sha256": response_hash,
        "raw_payload_path": str(path),
        "billing": usage.get("billing"),
        "job_id": usage.get("job_id"),
        "observed_at": observed_at,
    }


def _persist(
    profile: dict[str, Any], snapshots: list[dict[str, Any]], database_path: Path,
) -> None:
    domain = profile["domain"]
    timestamp = profile["last_enriched_at"]
    firmographics = profile["firmographics"]
    identifiers = profile["identifiers"]
    stored_profile = {
        key: value for key, value in profile.items()
        if key not in {"cache_hit", "current_run_billing"}
    }
    with connect_database(database_path) as connection:
        connection.execute(
            """
            INSERT INTO accounts(
                account_domain, canonical_name, website_url, linkedin_url,
                linkedin_company_id, prospeo_company_id, crustdata_company_id,
                crunchbase_url, industry, employee_count, employee_range,
                revenue_range, company_type, founded_year, headquarters_json,
                enrichment_status, funding_status, enrichment_version,
                profile_json, field_provenance_json, created_at, updated_at,
                last_enriched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_domain) DO UPDATE SET
                canonical_name=excluded.canonical_name,
                website_url=excluded.website_url,
                linkedin_url=excluded.linkedin_url,
                linkedin_company_id=excluded.linkedin_company_id,
                prospeo_company_id=excluded.prospeo_company_id,
                crustdata_company_id=excluded.crustdata_company_id,
                crunchbase_url=excluded.crunchbase_url,
                industry=excluded.industry,
                employee_count=excluded.employee_count,
                employee_range=excluded.employee_range,
                revenue_range=excluded.revenue_range,
                company_type=excluded.company_type,
                founded_year=excluded.founded_year,
                headquarters_json=excluded.headquarters_json,
                enrichment_status=excluded.enrichment_status,
                funding_status=excluded.funding_status,
                enrichment_version=excluded.enrichment_version,
                profile_json=excluded.profile_json,
                field_provenance_json=excluded.field_provenance_json,
                updated_at=excluded.updated_at,
                last_enriched_at=excluded.last_enriched_at
            """,
            (
                domain, profile["name"], profile["website_url"],
                identifiers.get("linkedin_url"), identifiers.get("linkedin_company_id"),
                identifiers.get("prospeo_company_id"), identifiers.get("crustdata_company_id"),
                identifiers.get("crunchbase_url"), firmographics.get("industry"),
                firmographics.get("employee_count"), firmographics.get("employee_range"),
                _database_text(firmographics.get("revenue_range")), firmographics.get("company_type"),
                firmographics.get("founded_year"), json.dumps(firmographics.get("headquarters")),
                profile["status"], profile["funding"]["status"], ENRICHMENT_VERSION,
                json.dumps(stored_profile, sort_keys=True), json.dumps(profile["field_provenance"], sort_keys=True),
                timestamp, timestamp, timestamp,
            ),
        )
        for snapshot in snapshots:
            provider_record_id = snapshot.get("provider_record_id")
            connection.execute(
                """
                INSERT OR IGNORE INTO account_enrichment_snapshots(
                    snapshot_id, account_domain, provider, provider_tool,
                    provider_record_id, response_sha256, raw_payload_path,
                    billing_json, observed_at, enrichment_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot["snapshot_id"], domain, snapshot["provider"],
                    snapshot["provider_tool"], provider_record_id,
                    snapshot["response_sha256"], snapshot["raw_payload_path"],
                    json.dumps(snapshot.get("billing"), sort_keys=True),
                    snapshot["observed_at"], ENRICHMENT_VERSION,
                ),
            )


def enrich_company(
    domain: str, *, account_name: str | None = None,
    database_path: Path = DEFAULT_DATABASE_PATH,
    output_root: Path = Path("data/company_enrichment"),
    linkedin_company_id: str | None = None,
    refresh: bool = False,
    prospeo_response_path: Path | None = None,
    runner: DeeplineCliRunner | None = None,
) -> dict[str, Any]:
    """Enrich and cache one canonical account before downstream provider calls."""
    domain = _domain(domain)
    if linkedin_company_id is not None and not linkedin_company_id.isdigit():
        raise ValueError("LinkedIn company ID must contain digits only")
    cached = get_account(domain, database_path)
    if cached and not refresh:
        if linkedin_company_id and cached.get("identifiers", {}).get("linkedin_company_id") != linkedin_company_id:
            cached["identifiers"]["linkedin_company_id"] = linkedin_company_id
            cached["downstream_keys"]["linkedin_jobs"] = linkedin_company_id
            cached["identity"] = {"status": "completed", "warning": None}
            cached["field_provenance"]["linkedin_company_id"] = "user_verified"
            cached["last_enriched_at"] = _now()
            _persist(cached, [], database_path)
            normalized_dir = output_root / domain / "normalized"
            normalized_dir.mkdir(parents=True, exist_ok=True)
            (normalized_dir / "company_profile.json").write_text(
                json.dumps(cached, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        return {**cached, "cache_hit": True, "current_run_billing": []}

    runner = runner or SubprocessDeeplineCliRunner()
    observed_at = _now()
    snapshots: list[dict[str, Any]] = []
    current_run_billing: list[dict[str, Any]] = []
    if prospeo_response_path is not None:
        prospeo_raw = prospeo_response_path.read_bytes()
        prospeo_envelope = json.loads(prospeo_raw)
    else:
        contract, _ = _run_json(runner, ["tools", "describe", PROSPEO_TOOL_ID, "--json"])
        _validate_contract(contract, PROSPEO_TOOL_ID, "company_website")
        prospeo_envelope, prospeo_raw = _run_json(runner, [
            "tools", "execute", PROSPEO_TOOL_ID, "--input",
            json.dumps({"company_website": domain}, separators=(",", ":")), "--json",
        ])
    prospeo_payload = _tool_payload(prospeo_envelope)
    company = _company_from_prospeo(prospeo_payload, domain)
    prospeo_snapshot = _write_snapshot(
        envelope=prospeo_envelope, raw=prospeo_raw, domain=domain,
        provider="prospeo", tool_id=PROSPEO_TOOL_ID,
        output_root=output_root, observed_at=observed_at,
    )
    prospeo_snapshot["provider_record_id"] = company.get("company_id")
    snapshots.append(prospeo_snapshot)
    if prospeo_response_path is None and prospeo_snapshot.get("billing"):
        current_run_billing.append({"provider": "prospeo", "billing": prospeo_snapshot["billing"]})

    linkedin_url = company.get("linkedin_url")
    resolved_linkedin_id = linkedin_company_id or company.get("linkedin_id")
    identity_match: dict[str, Any] | None = None
    identity_warning: str | None = None
    if not resolved_linkedin_id:
        try:
            contract, _ = _run_json(runner, ["tools", "describe", IDENTITY_TOOL_ID, "--json"])
            _validate_contract(contract, IDENTITY_TOOL_ID, "domains")
            identity_envelope, identity_raw = _run_json(runner, [
                "tools", "execute", IDENTITY_TOOL_ID, "--input",
                json.dumps({
                    "domains": [domain], "fields": ["basic_info", "social_profiles"]
                }, separators=(",", ":")), "--json",
            ])
            identity_match = _identity_from_crustdata(_tool_payload(identity_envelope), domain)
            basic = identity_match["company_data"]["basic_info"]
            resolved_linkedin_id = basic.get("professional_network_id")
            linkedin_url = linkedin_url or basic.get("professional_network_url")
            identity_snapshot = _write_snapshot(
                envelope=identity_envelope, raw=identity_raw, domain=domain,
                provider="crustdata-v3", tool_id=IDENTITY_TOOL_ID,
                output_root=output_root, observed_at=observed_at,
            )
            identity_snapshot["provider_record_id"] = str(
                identity_match["company_data"].get("crustdata_company_id") or ""
            ) or None
            snapshots.append(identity_snapshot)
            if identity_snapshot.get("billing"):
                current_run_billing.append({
                    "provider": "crustdata-v3", "billing": identity_snapshot["billing"]
                })
        except Exception as exc:
            identity_warning = f"{type(exc).__name__}: {exc}"

    if resolved_linkedin_id is not None:
        resolved_linkedin_id = str(resolved_linkedin_id)
        if not resolved_linkedin_id.isdigit():
            identity_warning = "resolved LinkedIn company ID was not numeric"
            resolved_linkedin_id = None

    identity_basic = (
        identity_match.get("company_data", {}).get("basic_info", {})
        if identity_match else {}
    )
    funding_value = company.get("funding")
    funding, funding_snapshots, funding_billing = _collect_funding(
        domain=domain, crunchbase_url=company.get("crunchbase_url"),
        runner=runner, output_root=output_root, observed_at=observed_at,
    )
    snapshots.extend(funding_snapshots)
    current_run_billing.extend(funding_billing)
    if funding_value is not None:
        funding["prospeo_observation"] = funding_value
        funding["prospeo_interpretation"] = (
            "Retained as non-authoritative context; only the exact Crunchbase observation is scored."
        )
    profile = {
        "schema_version": "1.0",
        "enrichment_version": ENRICHMENT_VERSION,
        "domain": domain,
        "name": str(company.get("name") or identity_basic.get("name") or account_name or domain),
        "website_url": str(company.get("website") or f"https://{domain}"),
        "status": (
            "completed"
            if resolved_linkedin_id and funding["status"] == "completed"
            else "partial"
        ),
        "cache_hit": False,
        "last_enriched_at": observed_at,
        "identity": {
            "status": "completed" if resolved_linkedin_id else "partial",
            "warning": identity_warning,
        },
        "identifiers": {
            "linkedin_url": linkedin_url,
            "linkedin_company_id": resolved_linkedin_id,
            "prospeo_company_id": company.get("company_id"),
            "crustdata_company_id": (
                str(identity_match["company_data"].get("crustdata_company_id"))
                if identity_match else None
            ),
            "crunchbase_url": company.get("crunchbase_url"),
        },
        "firmographics": {
            "industry": company.get("industry"),
            "employee_count": company.get("employee_count"),
            "employee_range": company.get("employee_range") or identity_basic.get("employee_count_range"),
            "revenue_range": company.get("revenue_range"),
            "company_type": company.get("type") or identity_basic.get("company_type"),
            "founded_year": company.get("founded") or identity_basic.get("year_founded"),
            "headquarters": company.get("location"),
        },
        "funding": funding,
        "downstream_keys": {
            "website_scrape": domain,
            "builtwith": domain,
            "linkedin_jobs": resolved_linkedin_id,
            "adyntel": domain,
            "google_search": domain,
        },
        "request_policy": {
            "provider_gateway": "deepline",
            "direct_provider_api_calls": False,
            "cache_reuse_default": True,
            "refresh_requires_explicit_flag": True,
            "automatic_paid_retries": False,
        },
        "field_provenance": {
            "canonical_company": "prospeo_enrich_company",
            "firmographics": "prospeo_enrich_company",
            "linkedin_url": "prospeo_enrich_company",
            "crunchbase_url": "prospeo_enrich_company",
            "linkedin_company_id": (
                "user_verified" if linkedin_company_id else
                "prospeo_enrich_company" if company.get("linkedin_id") else
                "crustdata_v3_company_identify" if resolved_linkedin_id else
                "unresolved"
            ),
            "funding": "crunchbase_via_deepline_required",
        },
        "source_snapshots": snapshots,
        "current_run_billing": current_run_billing,
    }
    _persist(profile, snapshots, database_path)
    normalized_dir = output_root / domain / "normalized"
    normalized_dir.mkdir(parents=True, exist_ok=True)
    (normalized_dir / "company_profile.json").write_text(
        json.dumps(profile, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return profile


def enrich_company_funding(
    domain: str, *, database_path: Path = DEFAULT_DATABASE_PATH,
    output_root: Path = Path("data/company_enrichment"),
    runner: DeeplineCliRunner | None = None,
) -> dict[str, Any]:
    """Refresh only authoritative funding for an already cached company."""
    domain = _domain(domain)
    profile = get_account(domain, database_path)
    if profile is None:
        raise ValueError(
            "company must be enriched and cached before funding can be refreshed"
        )
    observed_at = _now()
    runner = runner or SubprocessDeeplineCliRunner()
    funding, snapshots, billing = _collect_funding(
        domain=domain,
        crunchbase_url=profile.get("identifiers", {}).get("crunchbase_url"),
        runner=runner, output_root=output_root, observed_at=observed_at,
    )
    previous_context = profile.get("funding", {}).get("prospeo_observation")
    if previous_context is not None:
        funding["prospeo_observation"] = previous_context
        funding["prospeo_interpretation"] = (
            "Retained as non-authoritative context; only the exact Crunchbase observation is scored."
        )
    profile["funding"] = funding
    profile["enrichment_version"] = ENRICHMENT_VERSION
    profile["status"] = (
        "completed"
        if profile.get("identity", {}).get("status") == "completed"
        and funding["status"] == "completed"
        else "partial"
    )
    profile["last_enriched_at"] = observed_at
    profile["field_provenance"]["funding"] = (
        "crunchbase_via_deepline"
        if funding["status"] == "completed"
        else "crunchbase_via_deepline_required"
    )
    existing_snapshots = {
        item["snapshot_id"]: item for item in profile.get("source_snapshots", [])
    }
    for snapshot in snapshots:
        existing_snapshots.setdefault(snapshot["snapshot_id"], snapshot)
    profile["source_snapshots"] = list(existing_snapshots.values())
    profile["cache_hit"] = True
    profile["current_run_billing"] = billing
    _persist(profile, snapshots, database_path)
    normalized_dir = output_root / domain / "normalized"
    normalized_dir.mkdir(parents=True, exist_ok=True)
    (normalized_dir / "company_profile.json").write_text(
        json.dumps(profile, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return profile
