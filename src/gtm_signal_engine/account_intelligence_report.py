from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _top(values: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    return [
        {"label": key, "count": int(value)}
        for key, value in sorted(values.items(), key=lambda item: (-int(item[1]), item[0]))[:limit]
    ]


def _billing(run_dir: Path) -> dict[str, Any]:
    builtwith = _load(run_dir / "normalized" / "deepline_collection.json")
    adyntel = _load(run_dir / "normalized" / "adyntel_collection.json")
    apify = _load(run_dir / "normalized" / "apify_collection.json")
    billings = [builtwith.get("usage", {}).get("billing", {})]
    billings.extend(item.get("billing", {}) for item in adyntel.get("platforms", {}).values())
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
    syndication = _load(run_dir / "normalized" / "syndication_scores.json")
    profile = _load(run_dir / "normalized" / "external_profile.json")
    builtwith = _load(run_dir / "normalized" / "deepline_collection.json")
    adyntel = _load(run_dir / "normalized" / "adyntel_collection.json")
    apify = _load(run_dir / "normalized" / "apify_collection.json")
    creative = _load(run_dir / "normalized" / "ad_creative_analysis.json")
    paid = _load(run_dir / "normalized" / "paid_channel_scores.json")
    pipeline = _load(run_dir / "normalized" / "account_pipeline.json")
    domain = (urlsplit(str(manifest.get("seed_url", ""))).hostname or profile.get("domain") or "").removeprefix("www.")

    platforms: dict[str, Any] = {}
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
        evidence_state = (
            "observed" if (isinstance(primary_total, int) and primary_total > 0) or fallback_records > 0
            else "none_observed" if (
                provider.get("status") == "completed" and primary_total == 0
            ) or fallback_zero
            else "unknown"
        )
        platforms[platform] = {
            "provider_status": summary.get("provider_status") or provider.get("status", "unknown"),
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
            "content_syndication_score": syndication or None,
        },
        "technology": {"provider_status": builtwith.get("status", "unknown"), "detections": len(profile.get("technologies", []))},
        "paid_ads": {"provider": "adyntel", "fallback_provider": "apify" if apify else None, "platforms": platforms},
        "paid_channel_scores": paid.get("channels") or None,
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
        "## Paid advertising", "",
        "| Channel | Adyntel | Total ads | Adyntel inspected | Fallback | Fallback inspected | Evidence state |", "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for platform, item in platforms.items():
        lines.append(f"| {platform.title()} | {item['provider_status']} | {item['provider_total_ads'] if item['provider_total_ads'] is not None else 'unknown'} | {item['ads_inspected']} | {item['fallback_status'] or 'not used'} | {item['fallback_ads_inspected']} | {item['evidence_state']} |")
    lines.extend(["", "## Readiness", ""])
    for channel, item in (report["paid_channel_scores"] or {}).items():
        readiness = item.get("readiness", {})
        lines.append(f"- {channel.title()}: {readiness.get('score', 'unknown')} / 100; {readiness.get('status', 'unknown')}; confidence {readiness.get('confidence', 0)}; evidence coverage {readiness.get('evidence_coverage', 'unknown')}")
    lines.extend(["", "## Blockers", ""])
    lines.extend([f"- {item}" for item in report["blockers"]] or ["- None recorded."])
    lines.extend(["", report["interpretation"], ""])
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return {**report, "outputs": {"json": str(output_path), "markdown": str(markdown_path)}}
