from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .account_intelligence_report import build_account_intelligence_report
from .ad_creative_analysis import analyze_ad_creatives
from .adyntel_collection import collect_adyntel_ads
from .apify_collection import collect_apify_ads
from .external_collection import collect_deepline_technologies, replay_deepline_technologies
from .paid_channel_scoring import score_paid_channel_run
from .gap_discovery import discover_initiative_candidates
from .paid_gap import discover_paid_gap_candidates
from .job_collection import collect_deepline_jobs
from .review_queue import DEFAULT_DATABASE_PATH
from .unified_scoring import score_unified_account_run
from .workflow import analyze_saved_run, crawl_and_analyze

StageCallback = Callable[[str, str, dict[str, Any]], None]
Collector = Callable[..., Any]
PIPELINE_VERSION = "account_pipeline_v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _save(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_account_v1(
    domain: str, *, account_name: str | None = None, output_root: Path = Path("data/runs"),
    report_path: Path | None = None, run_dir: Path | None = None, maximum_pages: int = 100,
    maximum_sitemaps: int = 20, delay_seconds: float = 0.25,
    linkedin_company_id: str | None = None, apify_fallback: bool = True,
    skip_ad_platforms: tuple[str, ...] = (),
    stage_callback: StageCallback | None = None,
    website_runner: Collector = crawl_and_analyze,
    builtwith_collector: Collector = collect_deepline_technologies,
    adyntel_collector: Collector = collect_adyntel_ads,
    apify_collector: Collector = collect_apify_ads,
    jobs_collector: Collector | None = None,
    company_enricher: Collector | None = None,
    unified_scorer: Collector | None = score_unified_account_run,
    database_path: Path = DEFAULT_DATABASE_PATH,
    refresh_company: bool = False,
) -> dict[str, Any]:
    """Run or resume one evidence-first account workflow without rebuying completed stages."""
    invalid_skips = set(skip_ad_platforms).difference({"meta", "linkedin", "google"})
    if invalid_skips:
        raise ValueError("skip_ad_platforms must contain only meta, linkedin, or google")
    skipped_platforms = tuple(dict.fromkeys(skip_ad_platforms))
    requested_platforms = tuple(
        platform for platform in ("meta", "linkedin", "google")
        if platform not in skipped_platforms
    )
    callback = stage_callback or (lambda *_: None)
    company_profile: dict[str, Any] | None = None
    if company_enricher is not None:
        company_profile = company_enricher(
            domain, account_name=account_name, database_path=database_path,
            linkedin_company_id=linkedin_company_id, refresh=refresh_company,
        )
        account_name = company_profile.get("name") or account_name
        linkedin_company_id = (
            company_profile.get("identifiers", {}).get("linkedin_company_id")
            or linkedin_company_id
        )
    if run_dir is None:
        temporary_report = output_root / "_pipeline_reports" / f"{domain.replace('.', '-')}.json"
        website = website_runner(
            domain, output_path=temporary_report, output_root=output_root,
            account_name=account_name, maximum_pages=maximum_pages,
            maximum_sitemaps=maximum_sitemaps, delay_seconds=delay_seconds,
        )
        run_dir = Path(website["run_dir"])
    else:
        manifest_path = run_dir / "manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError("resume run requires manifest.json")
        manifest = _load(manifest_path)
        if (run_dir / "normalized" / "asset_summary.json").is_file():
            website = {"run": manifest, "run_dir": str(run_dir), "resumed": True}
        else:
            website = analyze_saved_run(
                run_dir, output_path=run_dir / "normalized" / "website_analysis.json",
                account_name=account_name,
            )
    state_path = run_dir / "normalized" / "account_pipeline.json"
    state = _load(state_path) or {
        "schema_version": "1.0", "pipeline_version": PIPELINE_VERSION,
        "domain": domain, "account_name": account_name or domain, "started_at": _now(),
        "finished_at": None, "status": "running", "stages": {}, "blockers": [],
    }
    # Blockers describe the current evidence state, not an append-only error log.
    # Stage checkpoints retain the historical details across resumptions.
    state["blockers"] = []
    state["status"] = "running"
    state["collection_policy"] = {
        "skipped_ad_platforms": list(skipped_platforms),
        "skip_means": "not collected by user decision; not zero and not evidence of absence",
    }

    def checkpoint(stage: str, status: str, detail: dict[str, Any] | None = None) -> None:
        payload = {"status": status, "updated_at": _now(), **(detail or {})}
        state["stages"][stage] = payload
        _save(state_path, state)
        callback(stage, status, payload)

    if company_profile is not None:
        company_reference = {
            "schema_version": "1.0",
            "domain": company_profile["domain"],
            "name": company_profile["name"],
            "status": company_profile["status"],
            "cache_hit": company_profile.get("cache_hit", False),
            "identifiers": company_profile["identifiers"],
            "firmographics": company_profile["firmographics"],
            "funding": company_profile["funding"],
            "downstream_keys": company_profile["downstream_keys"],
            "field_provenance": company_profile.get("field_provenance", {}),
            "source_snapshots": company_profile.get("source_snapshots", []),
            "request_policy": company_profile.get("request_policy", {}),
            "last_enriched_at": company_profile["last_enriched_at"],
            "current_run_billing": company_profile.get("current_run_billing", []),
        }
        _save(run_dir / "normalized" / "company_enrichment.json", company_reference)
        company_status = "completed" if company_profile["status"] == "completed" else "partial"
        checkpoint("company_enrichment", company_status, {
            "cache_hit": company_profile.get("cache_hit", False),
            "linkedin_company_id": linkedin_company_id,
            "funding_status": company_profile["funding"]["status"],
        })
        if company_status == "partial":
            state["blockers"].append(company_profile["funding"]["interpretation"])
    else:
        checkpoint("company_enrichment", "skipped", {
            "reason": "no company enricher supplied by this library caller",
        })

    checkpoint("website", "completed" if website["run"].get("status") != "failed" else "partial", {"run_dir": str(run_dir)})

    if (run_dir / "normalized" / "pages.jsonl").is_file():
        initiatives = discover_initiative_candidates(run_dir)
        paid_gaps = discover_paid_gap_candidates(run_dir)
        checkpoint("business_signal_discovery", "completed", {
            "initiative_candidates": initiatives["candidate_count"],
            "paid_gap_candidates": paid_gaps["candidate_count"],
            "review_required": bool(initiatives["candidate_count"] or paid_gaps["candidate_count"]),
        })
    else:
        checkpoint("business_signal_discovery", "partial", {
            "reason": "normalized pages are unavailable",
        })

    jobs_path = run_dir / "normalized" / "job_collection.json"
    jobs_status = _load(jobs_path)
    if jobs_status.get("status") == "completed":
        checkpoint("external_jobs", "completed", {
            "resumed": True, "records": jobs_status.get("normalized_records", 0),
        })
    elif int(sum(
        int(item.get("attempts", 0)) for item in jobs_status.get("sources", {}).values()
    )) > 0:
        checkpoint("external_jobs", "partial", {
            "resumed": True, "reason": "previous paid attempts are not retried automatically",
        })
        state["blockers"].extend(jobs_status.get("warnings", [
            "External job coverage is incomplete; previous paid attempts were not retried"
        ]))
    elif jobs_collector is not None:
        jobs_result = jobs_collector(
            run_dir, domain, account_name=account_name or domain,
            linkedin_company_id=linkedin_company_id,
        )
        checkpoint("external_jobs", "partial" if jobs_result.incomplete else "completed", {
            "records": len(jobs_result.records), "warnings": jobs_result.warnings,
        })
        if jobs_result.incomplete:
            state["blockers"].extend(jobs_result.warnings)
    else:
        checkpoint("external_jobs", "skipped", {
            "reason": "no jobs collector supplied by this library caller",
        })

    builtwith_status_path = run_dir / "normalized" / "deepline_collection.json"
    builtwith_status = _load(builtwith_status_path)
    if builtwith_status.get("status") == "completed":
        checkpoint("builtwith", "completed", {"resumed": True})
    elif builtwith_status.get("raw_payload_location"):
        result = replay_deepline_technologies(run_dir, domain)
        checkpoint("builtwith", "completed", {
            "resumed": True, "replayed": True, "records": len(result.records),
            "warnings": result.warnings,
        })
    elif int(builtwith_status.get("attempts", 0)) > 0:
        checkpoint("builtwith", "partial", {"resumed": True, "reason": "previous paid attempt is not retried automatically"})
        state["blockers"].append("BuiltWith did not complete; previous paid attempt was preserved without retry")
    else:
        result = builtwith_collector(run_dir, domain)
        builtwith_status = _load(builtwith_status_path)
        status = "completed" if not result.incomplete else "partial"
        checkpoint("builtwith", status, {"records": len(result.records), "warnings": result.warnings})
        if result.incomplete:
            state["blockers"].extend(result.warnings)

    adyntel_path = run_dir / "normalized" / "adyntel_collection.json"
    adyntel_status = _load(adyntel_path)
    existing_platforms = adyntel_status.get("platforms", {})
    missing = tuple(platform for platform in requested_platforms if platform not in existing_platforms)
    if missing:
        result = adyntel_collector(
            run_dir, domain, linkedin_page_id=linkedin_company_id, platforms=missing
        )
    adyntel_status = _load(adyntel_path)
    platform_states = {key: value.get("status", "unknown") for key, value in adyntel_status.get("platforms", {}).items()}
    unresolved = [
        key for key in requested_platforms
        if platform_states.get(key) in {None, "failed", "inconclusive", "unknown"}
    ]
    checkpoint("adyntel", "completed" if not unresolved else "partial", {
        "platforms": platform_states, "resumed_platforms": sorted(existing_platforms),
        "skipped_platforms": list(skipped_platforms),
    })

    fallback_platforms = tuple(platform for platform in unresolved if platform in {"meta", "linkedin"})
    apify_status = _load(run_dir / "normalized" / "apify_collection.json")
    already_fallback = set(apify_status.get("platforms", {}))
    missing_fallback = tuple(platform for platform in fallback_platforms if platform not in already_fallback)
    if apify_fallback and missing_fallback:
        result = apify_collector(
            run_dir, domain, account_name=account_name or domain,
            linkedin_company_id=linkedin_company_id, platforms=missing_fallback,
        )
        checkpoint("apify_fallback", "partial" if result.incomplete else "completed", {"platforms": list(missing_fallback), "warnings": result.warnings})
    elif fallback_platforms and set(fallback_platforms).issubset(already_fallback):
        saved_states = {
            platform: apify_status["platforms"][platform].get("status", "unknown")
            for platform in fallback_platforms
        }
        checkpoint(
            "apify_fallback",
            "completed" if all(value == "SUCCEEDED" for value in saved_states.values()) else "partial",
            {"resumed": True, "platforms": saved_states},
        )
    else:
        checkpoint("apify_fallback", "skipped", {"reason": "not needed or disabled"})

    apify_status = _load(run_dir / "normalized" / "apify_collection.json")
    def fallback_resolved(platform: str) -> bool:
        detail = apify_status.get("platforms", {}).get(platform, {})
        return detail.get("status") == "SUCCEEDED" and (
            int(detail.get("normalized_records", 0)) > 0
            or "candidate_records" in detail and int(detail["candidate_records"]) == 0
        )

    remaining_unresolved = [platform for platform in unresolved if not fallback_resolved(platform)]
    if remaining_unresolved:
        state["blockers"].append(
            "Ad evidence unresolved after configured providers for: "
            + ", ".join(remaining_unresolved)
        )

    try:
        creative = analyze_ad_creatives(run_dir)
        checkpoint("creative_analysis", "completed", {"ads_inspected": creative["scoring_inputs"]["ads_inspected"]})
    except (FileNotFoundError, ValueError) as exc:
        creative = None
        state["blockers"].append(f"Creative analysis unavailable: {exc}")
        checkpoint("creative_analysis", "partial", {"error": str(exc)})

    profile_path = run_dir / "normalized" / "external_profile.json"
    if profile_path.is_file():
        paid = score_paid_channel_run(run_dir, profile_path)
        checkpoint("paid_scoring", "completed", {"scoring_version": paid["scoring_version"]})
    else:
        state["blockers"].append("Paid scoring unavailable: normalized external profile is missing")
        checkpoint("paid_scoring", "partial", {"reason": "external profile missing"})

    if unified_scorer is not None:
        unified = unified_scorer(run_dir, database_path=database_path)
        checkpoint("unified_scoring", "completed", {
            "scoring_version": unified["scoring_version"],
            "priority_score": unified["priority"]["score"],
            "priority_status": unified["priority"]["status"],
            "opportunity_status": unified["qualification"]["opportunity_status"],
        })
    else:
        checkpoint("unified_scoring", "skipped", {
            "reason": "no unified scorer supplied by this library caller",
        })

    state["blockers"] = list(dict.fromkeys(state["blockers"]))
    state["status"] = "partial" if state["blockers"] else "completed"
    state["finished_at"] = _now()
    _save(state_path, state)
    checkpoint("report", "running")
    final_report = build_account_intelligence_report(
        run_dir, account_name=account_name, output_path=report_path
    )
    checkpoint("report", "completed", final_report["outputs"])
    state["status"] = "partial" if state["blockers"] else "completed"
    state["finished_at"] = _now()
    _save(state_path, state)
    return build_account_intelligence_report(
        run_dir, account_name=account_name, output_path=report_path
    )
