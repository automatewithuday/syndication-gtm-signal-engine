from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_bytes().splitlines() if line.strip()] if path.is_file() else []


def _top(values: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    return [
        {"label": key, "count": int(value)}
        for key, value in sorted(values.items(), key=lambda item: (-int(item[1]), item[0]))[:limit]
    ]


def _compact_usd(value: Any) -> str | None:
    if not isinstance(value, (int, float)):
        return None
    for divisor, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if abs(value) >= divisor:
            amount = value / divisor
            return f"${amount:g}{suffix}"
    return f"${value:g}"


def _revenue_display(value: Any) -> str:
    if isinstance(value, dict):
        minimum = _compact_usd(value.get("min"))
        maximum = _compact_usd(value.get("max"))
        if minimum and maximum:
            return f"{minimum}–{maximum}"
        return minimum or maximum or "unknown"
    return str(value) if value not in (None, "") else "unknown"


def _billing(run_dir: Path) -> dict[str, Any]:
    company = _load(run_dir / "normalized" / "company_enrichment.json")
    builtwith = _load(run_dir / "normalized" / "deepline_collection.json")
    adyntel = _load(run_dir / "normalized" / "adyntel_collection.json")
    apify = _load(run_dir / "normalized" / "apify_collection.json")
    jobs = _load(run_dir / "normalized" / "job_collection.json")
    billings = [builtwith.get("usage", {}).get("billing", {})]
    billings.extend(item.get("billing", {}) for item in company.get("current_run_billing", []))
    billings.extend(item.get("billing", {}) for item in adyntel.get("platforms", {}).values())
    billings.extend(item.get("usage", {}).get("billing", {}) for item in jobs.get("sources", {}).values())
    apify_usd = sum(
        float(item.get("usage_total_usd") or 0)
        for item in apify.get("platforms", {}).values()
    )
    unpriced_attempts = [
        f"adyntel:{platform}"
        for platform, item in adyntel.get("platforms", {}).items()
        if item.get("status") == "failed" and not item.get("billing")
    ]
    return {
        "credits": round(sum(float(item.get("credits_charged") or 0) for item in billings), 4),
        "usd": round(sum(float(item.get("cost_usd") or 0) for item in billings) + apify_usd, 5),
        "deepline_usd": round(sum(float(item.get("cost_usd") or 0) for item in billings), 4),
        "apify_usd": round(apify_usd, 5),
        "complete": not unpriced_attempts,
        "unpriced_attempts": unpriced_attempts,
    }


def build_account_intelligence_report(
    run_dir: Path, *, account_name: str | None = None, output_path: Path | None = None
) -> dict[str, Any]:
    """Build a decision-ready report without converting missing evidence into a zero."""
    manifest = _load(run_dir / "manifest.json")
    assets = _load(run_dir / "normalized" / "asset_summary.json")
    asset_rows = _load_jsonl(run_dir / "normalized" / "assets.jsonl")
    syndication = _load(run_dir / "normalized" / "syndication_score.json")
    profile = _load(run_dir / "normalized" / "external_profile.json")
    builtwith = _load(run_dir / "normalized" / "deepline_collection.json")
    adyntel = _load(run_dir / "normalized" / "adyntel_collection.json")
    apify = _load(run_dir / "normalized" / "apify_collection.json")
    creative = _load(run_dir / "normalized" / "ad_creative_analysis.json")
    paid = _load(run_dir / "normalized" / "paid_channel_scores.json")
    initiatives = _load(run_dir / "normalized" / "initiative_candidate_summary.json")
    gap_candidates = _load(run_dir / "normalized" / "paid_gap_candidate_summary.json")
    job_collection = _load(run_dir / "normalized" / "job_collection.json")
    job_postings = _load_jsonl(run_dir / "normalized" / "job_postings.jsonl")
    company_enrichment = _load(run_dir / "normalized" / "company_enrichment.json")
    unified_score = _load(run_dir / "normalized" / "unified_account_score.json")
    outbound_calling = _load(run_dir / "normalized" / "outbound_calling_score.json")
    gap_acquisition = _load(
        run_dir / "normalized" / "gap_evidence_acquisition.json"
    )
    pipeline = _load(run_dir / "normalized" / "account_pipeline.json")
    domain = (urlsplit(str(manifest.get("seed_url", ""))).hostname or profile.get("domain") or "").removeprefix("www.")

    platforms: dict[str, Any] = {}
    skipped_platforms = set(pipeline.get("collection_policy", {}).get("skipped_ad_platforms", []))
    for platform in ("meta", "linkedin", "google"):
        summary = creative.get("platforms", {}).get(platform, {})
        provider = adyntel.get("platforms", {}).get(platform, {})
        fallback = apify.get("platforms", {}).get(platform, {})
        primary_total = summary.get("provider_total_ads", provider.get("provider_total_records"))
        fallback_records = int(fallback.get("normalized_records", 0))
        fallback_zero = (
            fallback.get("status") == "SUCCEEDED"
            and "candidate_records" in fallback
            and int(fallback["candidate_records"]) == 0
        )
        evidence_state = "not_collected_by_decision" if platform in skipped_platforms else (
            "observed" if (isinstance(primary_total, int) and primary_total > 0) or fallback_records > 0
            else "none_observed" if (
                provider.get("status") == "completed" and primary_total == 0
            ) or fallback_zero
            else "unknown"
        )
        platforms[platform] = {
            "provider_status": (
                "skipped_by_user" if platform in skipped_platforms
                else summary.get("provider_status") or provider.get("status", "unknown")
            ),
            "provider_total_ads": primary_total,
            "ads_inspected": summary.get("ads_inspected", provider.get("normalized_records", 0)),
            "fallback_status": fallback.get("status"),
            "fallback_ads_inspected": fallback_records,
            "evidence_state": evidence_state,
            "sample_coverage_percent": summary.get("sample_coverage_percent"),
            "sample_confidence": summary.get("sample_confidence", "none"),
            "inventory_level": summary.get("inventory_level", "unknown"),
            "activity_states": summary.get("creative_activity_states", {}),
            "formats": summary.get("creative_diversity", {}).get("formats", []),
            "funnel_stages": _top(summary.get("funnel_stages", {})),
            "offers": _top(summary.get("offer_types", {})),
            "audiences": _top(summary.get("audiences", {})),
            "themes": _top(summary.get("messaging_themes", {})),
        }

    top_creatives = [
        {
            "platform": item.get("platform"), "ad_id": item.get("provider_record_id"),
            "headline": item.get("headline"), "body": item.get("body"), "cta": item.get("cta"),
            "source_url": item.get("source_url"), "destination_url": item.get("destination_url"),
            "funnel_stage": item.get("classification", {}).get("funnel_stage", {}).get("label", "unknown"),
            "themes": [value.get("label") for value in item.get("classification", {}).get("messaging_themes", [])],
        }
        for item in creative.get("creatives", [])
        if item.get("classification", {}).get("text_quality") == "usable"
    ][:12]
    blockers = list(pipeline.get("blockers", []))
    for platform, detail in platforms.items():
        if detail["evidence_state"] == "unknown":
            blockers.append(
                f"{platform} ad evidence remains unresolved after primary and fallback providers; channel absence is unknown"
            )
    if not profile.get("technologies"):
        blockers.append("technology evidence is unavailable; absence is unknown")

    report = {
        "schema_version": "1.0",
        "account": {"name": account_name or domain, "domain": domain},
        "run": {"run_id": manifest.get("run_id"), "run_dir": str(run_dir), "status": manifest.get("status")},
        "pipeline": {"version": pipeline.get("pipeline_version"), "status": pipeline.get("status"), "stages": pipeline.get("stages", {})},
        "provider_cost": _billing(run_dir),
        "website": {
            "pages": manifest.get("pages_collected", manifest.get("fetched_pages")), "assets": assets,
            "case_studies": {
                "count": int(assets.get("asset_types", {}).get("case_study", 0)),
                "examples": [
                    {"title": item.get("title"), "url": item.get("url"), "substantial": item.get("substantial")}
                    for item in asset_rows if item.get("asset_type") == "case_study"
                ][:10],
            },
            "content_syndication_score": syndication or None,
        },
        "technology": {"provider_status": builtwith.get("status", "unknown"), "detections": len(profile.get("technologies", []))},
        "paid_ads": {"provider": "adyntel", "fallback_provider": "apify" if apify else None, "platforms": platforms},
        "paid_channel_scores": paid.get("channels") or None,
        "outbound_calling_score": outbound_calling or None,
        "business_signals": {
            "candidate_count": initiatives.get("candidate_count", 0),
            "dated_candidate_count": initiatives.get("dated_candidate_count", 0),
            "by_signal_type": initiatives.get("by_signal_type", {}),
            "review_status": initiatives.get("review_status", "not_run"),
            "interpretation": "Hiring and funding candidates affect business timing only after evidence review; they do not prove a channel gap.",
            "external_job_postings": {
                "count": len(job_postings),
                "sources": {
                    key: {
                        "status": value.get("status", "unknown"),
                        "records_returned": value.get("records_returned"),
                        "normalized_records": value.get("normalized_records", 0),
                    }
                    for key, value in job_collection.get("sources", {}).items()
                },
                "examples": [
                    {"title": item.get("title"), "source": item.get("source"), "url": item.get("url"), "posted_at": item.get("posted_at")}
                    for item in job_postings[:10]
                ],
            },
            "funding": company_enrichment.get("funding", {
                "required_provider": "crunchbase_via_deepline",
                "status": "not_collected",
            }),
        },
        "company_enrichment": company_enrichment or None,
        "unified_account_score": unified_score or None,
        "gap_evidence_acquisition": gap_acquisition or None,
        "paid_gap_candidates": gap_candidates or None,
        "top_creatives": top_creatives,
        "blockers": list(dict.fromkeys(blockers)),
        "interpretation": "Unknown means evidence was not resolved; it is not a zero and is not proof that a channel is unused.",
    }
    output_path = output_path or run_dir / "normalized" / "account_intelligence.json"
    markdown_path = output_path.with_suffix(".md")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        f"# {report['account']['name']} account intelligence", "",
        f"- Domain: {domain}",
        f"- Pipeline status: {report['pipeline']['status'] or 'unknown'}",
        f"- Captured provider cost: {report['provider_cost']['credits']} Deepline credits (${report['provider_cost']['usd']:.3f} including Apify)",
        f"- Cost capture complete: {report['provider_cost']['complete']}", "",
    ]
    if company_enrichment:
        identifiers = company_enrichment.get("identifiers", {})
        firmographics = company_enrichment.get("firmographics", {})
        revenue = firmographics.get("revenue_range")
        revenue_display = _revenue_display(revenue)
        lines.extend([
            "## Company profile", "",
            f"- Enrichment cache hit: {company_enrichment.get('cache_hit', False)}",
            f"- LinkedIn: {identifiers.get('linkedin_url') or 'unresolved'}",
            f"- LinkedIn company ID: {identifiers.get('linkedin_company_id') or 'unresolved'}",
            f"- Employees: {firmographics.get('employee_count') or 'unknown'} "
            f"({firmographics.get('employee_range') or 'range unknown'})",
            f"- Revenue range: {revenue_display}",
            f"- Industry: {firmographics.get('industry') or 'unknown'}", "",
        ])
    if unified_score:
        priority = unified_score.get("priority", {})
        lines.extend([
            "## Unified account score", "",
            f"- Priority score: {priority.get('score', 'unknown')}",
            f"- Evidence coverage: {float(priority.get('evidence_coverage') or 0):.0%}",
            f"- Confidence: {float(priority.get('confidence') or 0):.0%}",
            f"- Priority status: {priority.get('status', 'unknown')}",
            f"- Opportunity status: {unified_score.get('qualification', {}).get('opportunity_status', 'unknown')}",
            "- Priority is not a channel-gap claim or outreach authorization.", "",
            "| Signal | Score | State | Confidence |", "|---|---:|---|---:|",
        ])
        for signal, detail in unified_score.get("signals", {}).items():
            lines.append(
                f"| {signal.replace('_', ' ').title()} | "
                f"{detail.get('score') if detail.get('score') is not None else 'unknown'} | "
                f"{detail.get('state', 'unknown')} | {float(detail.get('confidence') or 0):.0%} |"
            )
        lines.append("")
    if gap_acquisition:
        plan = gap_acquisition.get("plan", {})
        collection = gap_acquisition.get("collection") or {}
        lines.extend([
            "## Targeted gap-evidence acquisition", "",
            f"- Status: {gap_acquisition.get('status', 'unknown')}",
            f"- Relevant targets: {plan.get('target_count', 0)}",
            f"- Selected this pass: {plan.get('selected_count', 0)}",
            f"- Pages fetched: {len(collection.get('pages_fetched', []))}",
            f"- Held prior failures: {plan.get('skipped_previously_attempted', 0)}",
            "- Unavailable or unselected targets are unknown, not evidence of channel absence.",
            "",
        ])
    lines.extend([
        "## Paid advertising", "",
        "| Channel | Adyntel | Total ads | Adyntel inspected | Fallback | Fallback inspected | Evidence state |", "|---|---:|---:|---:|---:|---:|---:|",
    ])
    for platform, item in platforms.items():
        lines.append(f"| {platform.title()} | {item['provider_status']} | {item['provider_total_ads'] if item['provider_total_ads'] is not None else 'unknown'} | {item['ads_inspected']} | {item['fallback_status'] or 'not used'} | {item['fallback_ads_inspected']} | {item['evidence_state']} |")
    lines.extend(["", "## Website proof", ""])
    lines.append(f"- Case studies observed: {report['website']['case_studies']['count']}")
    lines.extend(["", "## Readiness", ""])
    for channel, item in (report["paid_channel_scores"] or {}).items():
        readiness = item.get("readiness", {})
        lines.append(f"- {channel.title()}: {readiness.get('score', 'unknown')} / 100; {readiness.get('status', 'unknown')}; confidence {readiness.get('confidence', 0)}; evidence coverage {readiness.get('evidence_coverage', 'unknown')}")
    if report["outbound_calling_score"]:
        readiness = report["outbound_calling_score"].get("components", {}).get("readiness", {})
        lines.append(
            f"- Outbound calling: {readiness.get('score', 'unknown')} / 100; "
            f"{readiness.get('status', 'unknown')}; confidence "
            f"{readiness.get('confidence', 0)}; evidence coverage "
            f"{readiness.get('evidence_coverage', 'unknown')}"
        )
    lines.extend(["", "## Business-timing signals", ""])
    lines.append(
        f"- Pending/reviewed candidates: {report['business_signals']['candidate_count']} "
        f"({report['business_signals']['dated_candidate_count']} with a source date)"
    )
    lines.append(f"- External demand-gen job postings: {report['business_signals']['external_job_postings']['count']}")
    funding = report["business_signals"]["funding"]
    lines.append(
        f"- Funding: {funding.get('status', 'unknown')} "
        f"(required source: {funding.get('required_provider', 'crunchbase_via_deepline')})"
    )
    for signal_type, count in report["business_signals"]["by_signal_type"].items():
        lines.append(f"- {signal_type}: {count}")
    lines.append(f"- {report['business_signals']['interpretation']}")
    lines.extend(["", "## Blockers", ""])
    lines.extend([f"- {item}" for item in report["blockers"]] or ["- None recorded."])
    lines.extend(["", report["interpretation"], ""])
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return {**report, "outputs": {"json": str(output_path), "markdown": str(markdown_path)}}
