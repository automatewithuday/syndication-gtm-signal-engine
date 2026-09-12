from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlsplit

from .external_collection import (
    DeeplineCliRunner,
    SubprocessDeeplineCliRunner,
    _domain,
    _run_json,
    _usage_summary,
    _validate_run_domain,
)
from .providers import ProviderResult

COLLECTOR_VERSION = "deepline_jobs_v1"
LINKEDIN_TOOL_ID = "harvestapi_search_jobs"
GOOGLE_JOBS_TOOL_ID = "openwebninja_jsearch_search"
ROLE_PATTERN = re.compile(
    r"\b(?:demand gen(?:eration)?|paid (?:media|acquisition|social|search)|performance marketing|"
    r"growth marketing|acquisition marketing|digital advertising|ads? manager)\b",
    re.I,
)
GTM_ROLE_PATTERN = re.compile(r"\b(?:GTM|go-to-market|growth|marketing) engineer(?:ing)?\b", re.I)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _normalized_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _role_family(title: str) -> str | None:
    if ROLE_PATTERN.search(title):
        return "demand_generation"
    if GTM_ROLE_PATTERN.search(title):
        return "gtm_engineering"
    return None


def _provider_payload(envelope: dict[str, Any]) -> dict[str, Any]:
    response = envelope.get("toolResponse", {})
    candidates: list[Any] = []
    for key in ("rawV2", "raw"):
        candidate = response.get(key) if isinstance(response, dict) else None
        if isinstance(candidate, dict):
            candidates.extend([candidate.get("data"), candidate])
    candidates.extend([envelope.get("data"), envelope])
    for candidate in candidates:
        if isinstance(candidate, dict) and any(key in candidate for key in ("elements", "data")):
            return candidate
    raise ValueError("Deepline response does not contain a declared jobs payload")


def _records(payload: dict[str, Any], source: str) -> list[dict[str, Any]]:
    value = payload.get("elements") if source == "linkedin_jobs" else payload.get("data")
    if isinstance(value, dict):
        value = value.get("data") or value.get("jobs") or value.get("results")
    if not isinstance(value, list):
        raise ValueError(f"{source} response does not contain a record list")
    return [item for item in value if isinstance(item, dict)]


def _job_url(record: dict[str, Any]) -> str | None:
    for key in ("url", "job_apply_link", "job_google_link"):
        value = record.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
    return None


def _normalize_linkedin(
    records: list[dict[str, Any]], *, account_name: str, domain: str,
    company_id: str | None, observed_at: str, response_sha256: str,
) -> list[dict[str, Any]]:
    normalized = []
    for record in records:
        title = str(record.get("title") or "").strip()
        role_family = _role_family(title)
        if not title or role_family is None:
            continue
        company = record.get("company") if isinstance(record.get("company"), dict) else {}
        company_name = str(company.get("name") or "").strip()
        if not company_id and _normalized_name(company_name) != _normalized_name(account_name):
            continue
        job_url = _job_url(record)
        if not job_url:
            continue
        normalized.append({
            "source": "linkedin_jobs", "provider": "harvestapi",
            "provider_record_id": str(record.get("id") or job_url),
            "title": title, "role_family": role_family,
            "company_name": company_name or account_name, "company_domain": domain,
            "location": str((record.get("location") or {}).get("linkedinText") or ""),
            "url": job_url, "posted_at": record.get("postedDate"),
            "observed_at": observed_at,
            "confidence": 0.97 if company_id else 0.86,
            "method": "deepline_harvestapi_linkedin_jobs",
            "attribution": "linkedin_company_id" if company_id else "exact_company_name",
            "provider_response_sha256": response_sha256,
            "normalizer_version": COLLECTOR_VERSION,
        })
    return normalized


def _normalize_google(
    records: list[dict[str, Any]], *, account_name: str, domain: str,
    observed_at: str, response_sha256: str,
) -> list[dict[str, Any]]:
    normalized = []
    for record in records:
        title = str(record.get("job_title") or record.get("title") or "").strip()
        role_family = _role_family(title)
        if not title or role_family is None:
            continue
        employer = str(record.get("employer_name") or record.get("company") or "").strip()
        website = str(record.get("employer_website") or "").strip()
        website_domain = (urlsplit(website).hostname or website).lower().removeprefix("www.")
        name_match = _normalized_name(employer) == _normalized_name(account_name)
        domain_match = website_domain == domain
        if not name_match and not domain_match:
            continue
        job_url = _job_url(record)
        if not job_url:
            continue
        normalized.append({
            "source": "google_jobs", "provider": "openwebninja",
            "provider_record_id": str(record.get("job_id") or record.get("id") or job_url),
            "title": title, "role_family": role_family,
            "company_name": employer or account_name, "company_domain": domain,
            "location": str(record.get("job_city") or record.get("job_location") or ""),
            "url": job_url,
            "posted_at": record.get("job_posted_at_datetime_utc") or record.get("posted_at"),
            "observed_at": observed_at, "confidence": 0.92 if domain_match else 0.84,
            "method": "deepline_openwebninja_google_jobs",
            "attribution": "employer_domain" if domain_match else "exact_company_name",
            "provider_response_sha256": response_sha256,
            "normalizer_version": COLLECTOR_VERSION,
        })
    return normalized


def _validate_contract(contract: dict[str, Any], tool_id: str) -> None:
    if contract.get("toolId") != tool_id or not contract.get("callable"):
        raise ValueError(f"Deepline jobs tool is missing or not callable: {tool_id}")
    if contract.get("connected") is not True:
        raise ValueError(f"Deepline jobs tool is not connected: {tool_id}")


def _saved_job_records(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            records.append(value)
    return records


def collect_deepline_jobs(
    run_dir: Path, domain: str, *, account_name: str,
    linkedin_company_id: str | None = None,
    sources: Sequence[str] = ("linkedin_jobs", "google_jobs"),
    runner: DeeplineCliRunner | None = None,
) -> ProviderResult:
    domain = _domain(domain)
    _validate_run_domain(run_dir, domain)
    invalid = set(sources).difference({"linkedin_jobs", "google_jobs"})
    if invalid:
        raise ValueError("job sources must be linkedin_jobs or google_jobs")
    runner = runner or SubprocessDeeplineCliRunner()
    raw_dir = run_dir / "raw"
    normalized_dir = run_dir / "normalized"
    raw_dir.mkdir(parents=True, exist_ok=True)
    normalized_dir.mkdir(parents=True, exist_ok=True)
    status_path = normalized_dir / "job_collection.json"
    jobs_path = normalized_dir / "job_postings.jsonl"
    incremental = status_path.is_file() and set(sources) != {"linkedin_jobs", "google_jobs"}
    previous_status = json.loads(status_path.read_text(encoding="utf-8")) if incremental else {}
    status: dict[str, Any] = {
        "schema_version": "1.0", "collector_version": COLLECTOR_VERSION,
        "provider": "deepline", "domain": domain, "account_name": account_name,
        "started_at": _now(), "finished_at": None, "status": "running",
        "incomplete": True, "sources": dict(previous_status.get("sources", {})), "warnings": [],
        "request_policy": {"maximum_pages_per_source": 1, "automatic_paid_retries": False},
        "incremental_update": incremental,
    }
    all_records = [
        item for item in _saved_job_records(jobs_path)
        if item.get("source") not in set(sources)
    ] if incremental else []
    for source in sources:
        tool_id = LINKEDIN_TOOL_ID if source == "linkedin_jobs" else GOOGLE_JOBS_TOOL_ID
        detail: dict[str, Any] = {"tool_id": tool_id, "status": "running", "attempts": 0}
        status["sources"][source] = detail
        if source == "linkedin_jobs" and not linkedin_company_id:
            detail.update({
                "status": "skipped_missing_identifier",
                "warning": "LinkedIn company ID is required for attributable LinkedIn Jobs collection",
            })
            status["warnings"].append(f"{source}: {detail['warning']}")
            continue
        try:
            contract, contract_raw = _run_json(runner, ["tools", "describe", tool_id, "--json"])
            _validate_contract(contract, tool_id)
            contract_path = raw_dir / f"deepline-{source}-contract-{_sha256(contract_raw)[:16]}.json"
            contract_path.write_bytes(contract_raw)
            if source == "linkedin_jobs":
                request: dict[str, Any] = {
                    "search": "demand generation OR paid media OR performance marketing OR growth marketing",
                    "sortBy": "date", "postedLimit": "month", "page": 1,
                }
                request["companyId"] = linkedin_company_id
            else:
                request = {
                    "query": f'"{account_name}" ("demand generation" OR "paid media" OR "performance marketing" OR "growth marketing") jobs',
                    "page": 1, "num_pages": 1, "country": "us", "date_posted": "month",
                }
            detail["attempts"] = 1
            envelope, envelope_raw = _run_json(runner, [
                "tools", "execute", tool_id, "--input",
                json.dumps(request, separators=(",", ":")), "--json",
            ])
            response_hash = _sha256(envelope_raw)
            response_path = raw_dir / f"deepline-{source}-{response_hash[:16]}.json"
            response_path.write_bytes(envelope_raw)
            payload = _provider_payload(envelope)
            observed_at = _now()
            source_records = _records(payload, source)
            normalized = (
                _normalize_linkedin(
                    source_records, account_name=account_name, domain=domain,
                    company_id=linkedin_company_id, observed_at=observed_at,
                    response_sha256=response_hash,
                ) if source == "linkedin_jobs" else _normalize_google(
                    source_records, account_name=account_name, domain=domain,
                    observed_at=observed_at, response_sha256=response_hash,
                )
            )
            all_records.extend(normalized)
            detail.update({
                "status": "completed", "records_returned": len(source_records),
                "normalized_records": len(normalized),
                "raw_payload_location": str(response_path.relative_to(run_dir)),
                "response_sha256": response_hash,
                "contract_location": str(contract_path.relative_to(run_dir)),
                "contract_sha256": _sha256(contract_raw), "usage": _usage_summary(envelope),
            })
        except Exception as exc:
            detail.update({"status": "failed", "warning": f"{type(exc).__name__}: {exc}"})
            status["warnings"].append(f"{source}: {detail['warning']}")
    deduped = {
        (item["source"], item["provider_record_id"]): item for item in all_records
    }
    all_records = list(deduped.values())
    with jobs_path.open("w", encoding="utf-8") as handle:
        for item in all_records:
            handle.write(json.dumps(item, sort_keys=True) + "\n")
    status["warnings"] = [
        f"{name}: {item.get('warning', 'collection incomplete')}"
        for name, item in status["sources"].items() if item.get("status") != "completed"
    ]
    failed = [name for name, item in status["sources"].items() if item.get("status") != "completed"]
    status.update({
        "finished_at": _now(), "status": "partial" if failed else "completed",
        "incomplete": bool(failed), "normalized_records": len(all_records),
        "jobs_file": "normalized/job_postings.jsonl",
    })
    status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return ProviderResult(
        provider="deepline_jobs", query=domain, records=all_records,
        raw_payload_location=None, incomplete=bool(failed), warnings=list(status["warnings"]),
    )


def replay_deepline_jobs(
    run_dir: Path, domain: str, *, account_name: str,
    linkedin_company_id: str | None = None,
) -> ProviderResult:
    """Re-normalize hash-checked saved job responses without another paid request."""
    domain = _domain(domain)
    _validate_run_domain(run_dir, domain)
    status_path = run_dir / "normalized" / "job_collection.json"
    if not status_path.is_file():
        raise FileNotFoundError("job collection status is missing")
    status = json.loads(status_path.read_text(encoding="utf-8"))
    all_records: list[dict[str, Any]] = []
    warnings: list[str] = []
    for source, detail in status.get("sources", {}).items():
        if source == "linkedin_jobs" and not linkedin_company_id:
            detail.update({
                "status": "skipped_missing_identifier", "normalized_records": 0,
                "warning": "LinkedIn company ID is required for attributable LinkedIn Jobs collection",
            })
            warnings.append(f"{source}: {detail['warning']}")
            continue
        location = detail.get("raw_payload_location")
        expected_hash = detail.get("response_sha256")
        if not location or not expected_hash:
            warnings.append(f"{source}: saved response metadata is incomplete")
            continue
        response_path = run_dir / location
        raw = response_path.read_bytes()
        if _sha256(raw) != expected_hash:
            raise ValueError(f"saved {source} response hash does not match collection metadata")
        envelope = json.loads(raw)
        payload = _provider_payload(envelope)
        source_records = _records(payload, source)
        observed_at = status.get("finished_at") or _now()
        normalized = (
            _normalize_linkedin(
                source_records, account_name=account_name, domain=domain,
                company_id=linkedin_company_id, observed_at=observed_at,
                response_sha256=expected_hash,
            ) if source == "linkedin_jobs" else _normalize_google(
                source_records, account_name=account_name, domain=domain,
                observed_at=observed_at, response_sha256=expected_hash,
            )
        )
        all_records.extend(normalized)
        detail["normalized_records"] = len(normalized)
        detail["replayed_at"] = _now()
    all_records = list({
        (item["source"], item["provider_record_id"]): item for item in all_records
    }.values())
    with (run_dir / "normalized" / "job_postings.jsonl").open("w", encoding="utf-8") as handle:
        for item in all_records:
            handle.write(json.dumps(item, sort_keys=True) + "\n")
    incomplete = any(item.get("status") != "completed" for item in status.get("sources", {}).values())
    status.update({
        "collector_version": COLLECTOR_VERSION, "normalized_records": len(all_records),
        "incomplete": incomplete, "status": "partial" if incomplete else "completed",
        "warnings": warnings, "replayed_at": _now(),
    })
    status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return ProviderResult(
        provider="deepline_jobs_replay", query=domain, records=all_records,
        incomplete=incomplete, warnings=warnings,
    )
