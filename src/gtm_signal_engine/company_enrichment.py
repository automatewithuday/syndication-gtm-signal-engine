from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .external_collection import (
    DeeplineCliRunner,
    SubprocessDeeplineCliRunner,
    _domain,
    _run_json,
    _usage_summary,
)
from .review_queue import DEFAULT_DATABASE_PATH, connect_database

ENRICHMENT_VERSION = "account_company_enrichment_v1"
PROSPEO_TOOL_ID = "prospeo_enrich_company"
IDENTITY_TOOL_ID = "crustdata_v3_company_identify"


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
    funding_status = "blocked_provider_unavailable"
    profile = {
        "schema_version": "1.0",
        "enrichment_version": ENRICHMENT_VERSION,
        "domain": domain,
        "name": str(company.get("name") or identity_basic.get("name") or account_name or domain),
        "website_url": str(company.get("website") or f"https://{domain}"),
        "status": "partial",
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
        "funding": {
            "required_provider": "crunchbase_via_deepline",
            "status": funding_status,
            "prospeo_observation": funding_value,
            "interpretation": (
                "Prospeo funding is retained as non-authoritative context; Crunchbase is required for scoring."
                if funding_value else
                "No callable Deepline Crunchbase contract is available; funding remains unresolved."
            ),
        },
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
