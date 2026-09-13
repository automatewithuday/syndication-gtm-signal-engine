from __future__ import annotations

import hashlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .review_queue import DEFAULT_DATABASE_PATH, connect_database

DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "unified_account_scoring.v1.json"
)
SCORING_LOGIC_VERSION = "unified_scorer_v2"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _default_config() -> Path:
    candidates = (
        Path.cwd() / "config" / "unified_account_scoring.v1.json",
        DEFAULT_CONFIG_PATH,
        Path(sys.prefix) / "share" / "gtm-signal-engine" / "unified_account_scoring.v1.json",
    )
    return next((candidate for candidate in candidates if candidate.is_file()), candidates[0])


def _load(path: Path) -> tuple[dict[str, Any] | None, bytes | None]:
    if not path.is_file():
        return None, None
    raw = path.read_bytes()
    return json.loads(raw), raw


def _load_jsonl(path: Path) -> tuple[list[dict[str, Any]], bytes | None]:
    if not path.is_file():
        return [], None
    raw = path.read_bytes()
    return [json.loads(line) for line in raw.splitlines() if line.strip()], raw


def _tier_score(value: float, tiers: list[dict[str, Any]]) -> float:
    return float(max(
        (tier["score"] for tier in tiers if value >= float(tier["minimum"])),
        default=0,
    ))


def _points(value: float, maximum: float, full_at: float) -> float:
    return round(maximum * min(1.0, max(0.0, value) / full_at), 1)


def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _freshness(
    value: Any, as_of: date, credits: dict[str, float]
) -> tuple[float, int | None]:
    observed = _parse_date(value)
    if observed is None:
        return float(credits["unknown"]), None
    age_days = max(0, (as_of - observed).days)
    if age_days <= 90:
        bucket = "within_90_days"
    elif age_days <= 180:
        bucket = "within_180_days"
    elif age_days <= 365:
        bucket = "within_365_days"
    else:
        bucket = "older"
    return float(credits[bucket]), age_days


def _status(score: float, confidence: float, settings: dict[str, Any]) -> str:
    return (
        "provisional_pass"
        if score >= float(settings["minimum_score"])
        and confidence >= float(settings["minimum_confidence"])
        else "review"
    )


def _unknown(reason: str, *, risks: list[str] | None = None) -> dict[str, Any]:
    return {
        "score": None,
        "state": "unknown",
        "status": "insufficient_evidence",
        "confidence": 0.0,
        "evidence_coverage": 0.0,
        "evidence": [],
        "reasons": [reason],
        "risks": risks or [],
    }


def _weighted_known(
    values: dict[str, dict[str, Any]], weights: dict[str, float]
) -> tuple[float | None, float, float]:
    known = {
        key: item for key, item in values.items()
        if item.get("score") is not None and key in weights
    }
    effective_weights = {
        key: float(weights[key]) * float(item.get("evidence_coverage", 1.0))
        for key, item in known.items()
    }
    known_weight = sum(effective_weights.values())
    total_weight = sum(float(value) for value in weights.values())
    if not known_weight or not total_weight:
        return None, 0.0, 0.0
    score = sum(float(item["score"]) * effective_weights[key] for key, item in known.items())
    confidence = sum(
        float(item.get("confidence") or 0) * effective_weights[key]
        for key, item in known.items()
    )
    coverage = known_weight / total_weight
    return round(score / known_weight, 1), round(coverage, 3), round(confidence / total_weight, 3)


def _firmographic_signal(
    company: dict[str, Any], account_fit: dict[str, Any] | None, config: dict[str, Any]
) -> dict[str, Any]:
    settings = config["firmographic_fit"]
    sources: dict[str, dict[str, Any]] = {}
    if account_fit and account_fit.get("component", {}).get("score") is not None:
        component = account_fit["component"]
        sources["reviewed_account_fit"] = {
            "score": float(component["score"]),
            "confidence": float(component.get("confidence") or 0),
            "snapshot_id": account_fit.get("snapshot_id"),
            "source": "normalized/account_fit.json",
        }

    firmographics = company.get("firmographics", {})
    scale_factors: list[dict[str, Any]] = []
    employee_count = firmographics.get("employee_count")
    if isinstance(employee_count, (int, float)):
        scale_factors.append({
            "id": "employee_count",
            "observed": employee_count,
            "score": _tier_score(float(employee_count), settings["headcount_tiers"]),
        })
    revenue = firmographics.get("revenue_range")
    revenue_minimum = revenue.get("min") if isinstance(revenue, dict) else None
    if isinstance(revenue_minimum, (int, float)):
        scale_factors.append({
            "id": "revenue_minimum",
            "observed": revenue_minimum,
            "score": _tier_score(float(revenue_minimum), settings["revenue_tiers"]),
        })
    if scale_factors:
        scale_coverage = len(scale_factors) / 2
        sources["provider_commercial_scale"] = {
            "score": round(sum(item["score"] for item in scale_factors) / len(scale_factors), 1),
            "confidence": round(float(settings["provider_confidence"]) * scale_coverage, 3),
            "evidence_coverage": scale_coverage,
            "factors": scale_factors,
            "source": "normalized/company_enrichment.json",
            "provenance": company.get("field_provenance", {}),
        }
    score, coverage, confidence = _weighted_known(sources, settings["source_weights"])
    if score is None:
        return _unknown("neither reviewed account fit nor provider commercial scale is available")
    return {
        "score": score,
        "state": "observed",
        "status": _status(score, confidence, settings),
        "confidence": confidence,
        "evidence_coverage": coverage,
        "evidence": list(sources.values()),
        "reasons": [f"{len(sources)} of 2 configured fit sources are available"],
        "risks": [
            "commercial-scale tiers are provisional and do not replace ICP-specific fit criteria"
        ],
    }


def _hiring_signal(
    jobs: list[dict[str, Any]], business_trigger: dict[str, Any] | None,
    domain: str, config: dict[str, Any], as_of: date,
) -> dict[str, Any]:
    settings = config["hiring"]
    evidence: list[dict[str, Any]] = []
    for job in jobs:
        if str(job.get("company_domain", "")).lower().removeprefix("www.") != domain:
            continue
        base = settings["role_scores"].get(job.get("role_family"))
        if base is None:
            continue
        freshness, age_days = _freshness(job.get("posted_at"), as_of, settings["freshness_credit"])
        evidence.append({
            "signal_key": f"external:{job.get('source')}:{job.get('provider_record_id')}",
            "signal_type": "active_job_posting",
            "score": round(float(base) * freshness, 1),
            "confidence": float(job.get("confidence") or 0),
            "age_days": age_days,
            "source": "normalized/job_postings.jsonl",
            "observation": job,
        })
    if business_trigger:
        for item in business_trigger.get("component", {}).get("evidence", []):
            base = settings["initiative_scores"].get(item.get("signal_type"))
            if base is None:
                continue
            source_date = item.get("source_date", {}).get("value") if item.get("source_date") else None
            freshness, age_days = _freshness(source_date, as_of, settings["freshness_credit"])
            confidence = float(item.get("confidence") or 0)
            if age_days is None:
                confidence = min(confidence, float(settings["unknown_date_confidence_cap"]))
            evidence.append({
                "signal_key": f"first_party:{item.get('signal_type')}:{item.get('url')}",
                "signal_type": item.get("signal_type"),
                "score": round(float(base) * freshness, 1),
                "confidence": confidence,
                "age_days": age_days,
                "source": "normalized/business_trigger.json",
                "observation": item,
            })
    if not evidence:
        return _unknown(
            "no attributable demand-generation or GTM hiring evidence was observed",
            risks=["completed zero-result searches are scoped coverage, not proof of no hiring"],
        )
    selected = sorted(evidence, key=lambda item: (item["score"], item["confidence"]), reverse=True)
    distinct = len({item["signal_key"] for item in selected})
    score = min(
        100.0,
        float(selected[0]["score"])
        + float(settings["additional_distinct_signal_bonus"]) * (distinct - 1),
    )
    confidence = round(sum(item["confidence"] for item in selected) / len(selected), 3)
    return {
        "score": round(score, 1),
        "state": "observed",
        "status": _status(score, confidence, settings),
        "confidence": confidence,
        "evidence_coverage": 1.0,
        "evidence": selected,
        "reasons": [f"{distinct} attributable active hiring observation(s)"],
        "risks": ["hiring is a timing signal and does not establish a channel gap"],
    }


def _funding_signal(company: dict[str, Any], config: dict[str, Any], as_of: date) -> dict[str, Any]:
    settings = config["funding"]
    funding = company.get("funding", {})
    observation = funding.get("crunchbase_observation") or funding.get("authoritative_observation")
    if funding.get("status") != "completed" or not isinstance(observation, dict):
        return _unknown(
            "authoritative Crunchbase funding evidence is unresolved",
            risks=[str(funding.get("interpretation") or "funding absence is unknown")],
        )
    provider = str(observation.get("provider") or funding.get("provider") or "").casefold()
    if "crunchbase" not in provider:
        return _unknown("funding payload is not attributable to Crunchbase")
    event_date = (
        observation.get("latest_funding_date")
        or observation.get("raised_at")
        or observation.get("announced_at")
    )
    freshness, age_days = _freshness(event_date, as_of, settings["freshness_credit"])
    confidence = float(observation.get("confidence") or 0.9)
    if age_days is None:
        confidence = min(confidence, float(settings["unknown_date_confidence_cap"]))
    score = round(float(settings["base_score"]) * freshness, 1)
    return {
        "score": score,
        "state": "observed",
        "status": _status(score, confidence, settings),
        "confidence": round(confidence, 3),
        "evidence_coverage": 1.0,
        "evidence": [{"source": "normalized/company_enrichment.json", "observation": observation}],
        "reasons": ["scored from authoritative Crunchbase funding evidence"],
        "risks": ["funding is a timing/capacity signal and does not establish a channel gap"],
    }


def _advertising_signal(creative: dict[str, Any] | None, config: dict[str, Any]) -> dict[str, Any]:
    if not creative:
        return _unknown("ad creative analysis is unavailable")
    settings = config["advertising"]
    scoring = creative.get("scoring_inputs", {})
    platforms = creative.get("platforms", {})
    conclusive = [
        item for item in platforms.values()
        if isinstance(item, dict)
        and item.get("provider_status") not in {"failed", "inconclusive", "unknown"}
    ]
    inventory = int(scoring.get("provider_total_ads") or 0)
    if inventory <= 0 and not any(int(item.get("ads_inspected") or 0) for item in conclusive):
        return _unknown(
            "no positive attributable ad activity was observed",
            risks=["public ad-library absence is uncertainty, not proof that advertising is unused"],
        )
    current_recent = sum(
        int(item.get("creative_activity_states", {}).get(state, 0))
        for item in conclusive for state in ("active", "recently_observed")
    )
    values: dict[str, tuple[float, bool]] = {
        "ad_inventory": (inventory, inventory > 0),
        "platform_diversity": (int(scoring.get("observed_platform_diversity") or 0), True),
        "current_or_recent_creatives": (current_recent, current_recent > 0),
        "analyzable_ads": (int(scoring.get("analyzable_ads") or 0), True),
    }
    factors = []
    known_weight = 0.0
    earned = 0.0
    for key, maximum in settings["factor_weights"].items():
        value, known = values[key]
        points = _points(value, float(maximum), float(settings["full_at"][key])) if known else None
        factors.append({
            "id": key, "observed": value if known else None,
            "state": "observed" if known else "unknown",
            "maximum_points": maximum, "points": points,
        })
        if known:
            known_weight += float(maximum)
            earned += float(points)
    score = round(100 * earned / known_weight, 1)
    confidence_map = {"high": 0.9, "medium": 0.7, "low": 0.4, "none": 0.0}
    samples = [
        confidence_map.get(str(item.get("sample_confidence", "none")), 0.0)
        for item in conclusive if int(item.get("ads_inspected") or 0) > 0
    ]
    sample_confidence = sum(samples) / len(samples) if samples else 0.0
    coverage = known_weight / sum(float(value) for value in settings["factor_weights"].values())
    confidence = round(sample_confidence * coverage, 3)
    return {
        "score": score,
        "state": "observed",
        "status": _status(score, confidence, settings),
        "confidence": confidence,
        "evidence_coverage": round(coverage, 3),
        "evidence": [{
            "source": "normalized/ad_creative_analysis.json",
            "snapshot_id": creative.get("snapshot_id"),
            "platforms": sorted(creative.get("scoring_inputs", {}).get("observed_ad_platforms", [])),
        }],
        "factors": factors,
        "reasons": [f"{inventory} provider ads with {scoring.get('ads_inspected', 0)} rows inspected"],
        "risks": ["provider totals and inspected creative samples are not impression or spend data"],
    }


def _technology_signal(
    profile: dict[str, Any] | None, collection: dict[str, Any] | None, config: dict[str, Any]
) -> dict[str, Any]:
    technologies = [
        item for item in (profile or {}).get("technologies", [])
        if item.get("state") == "detected"
    ]
    if not technologies:
        return _unknown(
            "no positive technology detections are available",
            risks=["missing detections do not prove a technology is absent"],
        )
    settings = config["technology"]
    markers = [str(value).casefold() for value in settings["category_markers"]]
    relevant = [
        item for item in technologies
        if any(marker in str(item.get("category", "")).casefold() for marker in markers)
    ]
    categories = {
        part.strip().casefold()
        for item in technologies
        for part in str(item.get("category", "")).split("|")
        if part.strip()
    }
    values = {
        "relevant_marketing_technologies": len(relevant),
        "category_diversity": len(categories),
    }
    factors = []
    for key, maximum in settings["factor_weights"].items():
        factors.append({
            "id": key, "observed": values[key], "state": "observed",
            "maximum_points": maximum,
            "points": _points(values[key], float(maximum), float(settings["full_at"][key])),
        })
    score = round(sum(float(item["points"]) for item in factors), 1)
    evidence_confidence = sum(float(item.get("confidence") or 0) for item in technologies) / len(technologies)
    if collection and collection.get("incomplete"):
        evidence_confidence = min(evidence_confidence, 0.65)
    confidence = round(min(0.9, evidence_confidence), 3)
    return {
        "score": score,
        "state": "observed",
        "status": _status(score, confidence, settings),
        "confidence": confidence,
        "evidence_coverage": 1.0,
        "evidence": [{
            "source": "normalized/external_profile.json",
            "collection_sha256": (collection or {}).get("response_sha256"),
            "detected_count": len(technologies),
            "relevant_count": len(relevant),
        }],
        "factors": factors,
        "reasons": [f"{len(technologies)} BuiltWith detections across {len(categories)} categories"],
        "risks": ["technology detections do not prove complete or active deployment"],
    }


def _website_signal(syndication: dict[str, Any] | None) -> dict[str, Any]:
    readiness = (syndication or {}).get("components", {}).get("readiness", {})
    if readiness.get("score") is None:
        return _unknown("versioned website-readiness scoring is unavailable")
    confidence = float((syndication or {}).get("component_confidence", {}).get("readiness") or 0)
    score = float(readiness["score"])
    return {
        "score": score,
        "state": readiness.get("state", "observed"),
        "status": (syndication or {}).get("qualification", {}).get("readiness_status", "review"),
        "confidence": confidence,
        "evidence_coverage": 1.0,
        "evidence": [{
            "source": "normalized/syndication_score.json",
            "snapshot_id": (syndication or {}).get("snapshot_id"),
        }],
        "reasons": list(readiness.get("reasons", [])),
        "risks": list(readiness.get("risks", [])),
    }


def _trigger_component(
    hiring: dict[str, Any], funding: dict[str, Any], business_trigger: dict[str, Any] | None
) -> dict[str, Any]:
    candidates = [
        {"id": "hiring", **hiring},
        {"id": "funding", **funding},
    ]
    component = (business_trigger or {}).get("component", {})
    if component.get("score") is not None:
        candidates.append({
            "id": "reviewed_business_trigger",
            "score": component["score"],
            "confidence": component.get("confidence", 0),
            "status": component.get("status", "review"),
            "state": component.get("state", "observed"),
            "snapshot_id": (business_trigger or {}).get("snapshot_id"),
        })
    known = [item for item in candidates if item.get("score") is not None]
    if not known:
        return _unknown("no attributable hiring, funding, or reviewed business trigger is available")
    selected = max(known, key=lambda item: (float(item["score"]), float(item.get("confidence") or 0)))
    return {
        "score": float(selected["score"]),
        "confidence": float(selected.get("confidence") or 0),
        "state": selected.get("state", "observed"),
        "status": selected.get("status", "review"),
        "source_signal": selected["id"],
        "reasons": ["trigger alternatives are combined by maximum to avoid double counting"],
        "risks": ["trigger evidence does not establish a channel gap"],
    }


def _gap_for_channel(
    channel: str, syndication: dict[str, Any] | None, paid: dict[str, Any] | None,
    outbound: dict[str, Any] | None,
) -> dict[str, Any]:
    if channel == "content_syndication":
        return dict((syndication or {}).get("components", {}).get("gap") or _unknown(
            "content-syndication gap evidence is unavailable"
        ))
    if channel == "outbound_calling":
        return dict((outbound or {}).get("components", {}).get("gap") or _unknown(
            "outbound-calling gap evidence is unavailable"
        ))
    return dict((paid or {}).get("channels", {}).get(channel, {}).get("gap") or _unknown(
        f"{channel} gap evidence is unavailable"
    ))


def _readiness_for_channel(
    channel: str, website: dict[str, Any], paid: dict[str, Any] | None,
    outbound: dict[str, Any] | None,
) -> dict[str, Any]:
    if channel == "content_syndication":
        return website
    if channel == "outbound_calling":
        return dict((outbound or {}).get("components", {}).get("readiness") or _unknown(
            "outbound-calling readiness is unavailable"
        ))
    return dict((paid or {}).get("channels", {}).get(channel, {}).get("readiness") or _unknown(
        f"{channel} readiness is unavailable"
    ))


def _channel_scores(
    firmographic: dict[str, Any], website: dict[str, Any], hiring: dict[str, Any],
    funding: dict[str, Any], business_trigger: dict[str, Any] | None,
    syndication: dict[str, Any] | None, paid: dict[str, Any] | None,
    outbound: dict[str, Any] | None,
    config: dict[str, Any],
) -> dict[str, Any]:
    trigger = _trigger_component(hiring, funding, business_trigger)
    weights = config["channel_component_weights"]
    thresholds = config["qualification"]
    result: dict[str, Any] = {}
    for channel in (
        "content_syndication", "retargeting", "programmatic", "outbound_calling",
    ):
        components = {
            "fit": firmographic,
            "readiness": _readiness_for_channel(channel, website, paid, outbound),
            "gap": _gap_for_channel(channel, syndication, paid, outbound),
            "trigger": trigger,
        }
        blockers = [key for key, value in components.items() if value.get("score") is None]
        total = None if blockers else round(sum(
            float(components[key]["score"]) * float(weight) for key, weight in weights.items()
        ), 1)
        known_confidences = [
            float(item.get("confidence") or 0) for item in components.values()
            if item.get("score") is not None
        ]
        component_coverage = round(sum(
            float(weights[key]) for key, item in components.items()
            if item.get("score") is not None
        ), 3)
        confidence = (
            round(min(known_confidences) * component_coverage, 3)
            if known_confidences else 0.0
        )
        disqualified = components["gap"].get("status") == "disqualified"
        qualified = (
            total is not None
            and total >= float(thresholds["minimum_channel_total"])
            and confidence >= float(thresholds["minimum_channel_confidence"])
            and components["fit"].get("status") == "provisional_pass"
            and components["readiness"].get("status") == "provisional_pass"
            and components["gap"].get("status") == "provisional_pass"
        )
        result[channel] = {
            "components": components,
            "total": total,
            "confidence": confidence,
            "evidence_coverage": component_coverage,
            "status": "disqualified" if disqualified else "qualified" if qualified else "insufficient_evidence",
            "blockers": blockers,
        }
    return result


def _validate_config(config: dict[str, Any]) -> None:
    if config.get("version") != "unified_account_v1":
        raise ValueError("unsupported unified scoring version")
    if round(sum(float(value) for value in config.get("priority_weights", {}).values()), 8) != 1:
        raise ValueError("unified priority weights must sum to 1")
    if round(sum(float(value) for value in config.get("channel_component_weights", {}).values()), 8) != 1:
        raise ValueError("channel component weights must sum to 1")
    for section in ("advertising", "technology"):
        if sum(float(value) for value in config[section]["factor_weights"].values()) != 100:
            raise ValueError(f"{section} factor weights must sum to 100")


def score_unified_account_run(
    run_dir: Path,
    database_path: Path = DEFAULT_DATABASE_PATH,
    config_path: Path | None = None,
    *,
    as_of: date | None = None,
) -> dict[str, Any]:
    manifest, manifest_raw = _load(run_dir / "manifest.json")
    company, company_raw = _load(run_dir / "normalized" / "company_enrichment.json")
    if not manifest or not company or not manifest_raw or not company_raw:
        raise FileNotFoundError("unified scoring requires manifest.json and company_enrichment.json")
    domain = (urlsplit(str(manifest.get("seed_url", ""))).hostname or "").lower().removeprefix("www.")
    if manifest.get("provider") != "ScraplingFetcher":
        raise ValueError("unified scoring requires a ScraplingFetcher run")
    if str(company.get("domain", "")).lower().removeprefix("www.") != domain:
        raise ValueError("cached company profile does not match the run domain")

    config_file = config_path or _default_config()
    config_raw = config_file.read_bytes()
    config = json.loads(config_raw)
    _validate_config(config)
    selected_as_of = as_of or datetime.now(timezone.utc).date()

    artifact_names = {
        "account_fit": "account_fit.json",
        "business_trigger": "business_trigger.json",
        "creative": "ad_creative_analysis.json",
        "technology_collection": "deepline_collection.json",
        "external_profile": "external_profile.json",
        "paid_channels": "paid_channel_scores.json",
        "outbound_calling": "outbound_calling_score.json",
        "syndication": "syndication_score.json",
    }
    artifacts: dict[str, dict[str, Any] | None] = {}
    hashes: dict[str, str | None] = {}
    for key, filename in artifact_names.items():
        value, raw = _load(run_dir / "normalized" / filename)
        artifacts[key] = value
        hashes[key] = (
            str(value.get("snapshot_id") or value.get("response_sha256"))
            if value and (value.get("snapshot_id") or value.get("response_sha256"))
            else _sha256(raw) if raw else None
        )
    jobs, jobs_raw = _load_jsonl(run_dir / "normalized" / "job_postings.jsonl")
    hashes["job_postings"] = _sha256(jobs_raw) if jobs_raw else None

    signals = {
        "firmographic_fit": _firmographic_signal(company, artifacts["account_fit"], config),
        "hiring": _hiring_signal(
            jobs, artifacts["business_trigger"], domain, config, selected_as_of
        ),
        "funding": _funding_signal(company, config, selected_as_of),
        "advertising": _advertising_signal(artifacts["creative"], config),
        "technology": _technology_signal(
            artifacts["external_profile"], artifacts["technology_collection"], config
        ),
        "website": _website_signal(artifacts["syndication"]),
    }
    priority_score, coverage, confidence = _weighted_known(signals, config["priority_weights"])
    qualification = config["qualification"]
    priority_status = (
        "insufficient_evidence" if priority_score is None
        else "high_priority" if (
            priority_score >= float(qualification["minimum_priority_score"])
            and coverage >= float(qualification["minimum_priority_coverage"])
            and confidence >= float(qualification["minimum_priority_confidence"])
        ) else "review"
    )
    channels = _channel_scores(
        signals["firmographic_fit"], signals["website"], signals["hiring"],
        signals["funding"], artifacts["business_trigger"], artifacts["syndication"],
        artifacts["paid_channels"], artifacts["outbound_calling"], config,
    )
    qualified_channels = [key for key, value in channels.items() if value["status"] == "qualified"]
    opportunity_status = "qualified" if qualified_channels else "insufficient_evidence"
    blockers = sorted({
        f"{channel}:{component}"
        for channel, result in channels.items()
        for component in result["blockers"]
    })
    stable_company = {
        key: value for key, value in company.items()
        if key not in {"cache_hit", "current_run_billing"}
    }
    company_fingerprint = _sha256(json.dumps(
        stable_company, sort_keys=True, separators=(",", ":")
    ).encode("utf-8"))
    snapshot_material = json.dumps({
        "run_id": manifest.get("run_id") or run_dir.name,
        "company_fingerprint": company_fingerprint,
        "artifact_hashes": hashes,
        "config_sha256": _sha256(config_raw),
        "scoring_version": config["version"],
        "scoring_logic_version": SCORING_LOGIC_VERSION,
        "as_of": selected_as_of.isoformat(),
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")
    scored_at = _now()
    result = {
        "schema_version": "1.0",
        "scoring_version": config["version"],
        "scoring_logic_version": SCORING_LOGIC_VERSION,
        "scored_at": scored_at,
        "as_of": selected_as_of.isoformat(),
        "snapshot_id": _sha256(snapshot_material),
        "account": {
            "name": company.get("name") or domain,
            "domain": domain,
            "linkedin_company_id": company.get("identifiers", {}).get("linkedin_company_id"),
        },
        "priority": {
            "score": priority_score,
            "score_mode": config["score_mode"],
            "evidence_coverage": coverage,
            "confidence": confidence,
            "status": priority_status,
            "interpretation": (
                "This ranks positive fit, readiness, and timing signals. It is not a channel-gap claim or outreach authorization."
            ),
        },
        "signals": signals,
        "channels": channels,
        "qualification": {
            "opportunity_status": opportunity_status,
            "qualified_channels": qualified_channels,
            "blockers": blockers,
            "thresholds": qualification,
        },
        "input": {
            "run_id": manifest.get("run_id") or run_dir.name,
            "company_file": "normalized/company_enrichment.json",
            "company_fingerprint_sha256": company_fingerprint,
            "artifact_sha256": hashes,
            "config_file": str(config_file),
            "config_sha256": _sha256(config_raw),
        },
        "calibration": config["calibration"],
    }
    with connect_database(database_path) as connection:
        account = connection.execute(
            "SELECT 1 FROM accounts WHERE account_domain = ?", (domain,)
        ).fetchone()
        if account is None:
            raise ValueError("unified scoring requires the cached account row in SQLite")
        connection.execute(
            """
            INSERT OR REPLACE INTO unified_account_scores(
                snapshot_id, account_domain, run_id, scoring_version, scoring_logic_version,
                priority_score, evidence_coverage, confidence, priority_status,
                opportunity_status, result_json, scored_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result["snapshot_id"], domain, result["input"]["run_id"],
                result["scoring_version"], result["scoring_logic_version"],
                priority_score, coverage, confidence,
                priority_status, opportunity_status,
                json.dumps(result, sort_keys=True), scored_at,
            ),
        )
    output_path = run_dir / "normalized" / "unified_account_score.json"
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result
