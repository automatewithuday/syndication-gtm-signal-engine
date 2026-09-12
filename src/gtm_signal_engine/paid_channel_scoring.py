from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "paid_channel_scoring.v3.json"


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _default_config() -> Path:
    candidates = (
        Path.cwd() / "config" / "paid_channel_scoring.v3.json",
        DEFAULT_CONFIG_PATH,
        Path(sys.prefix) / "share" / "gtm-signal-engine" / "paid_channel_scoring.v3.json",
    )
    return next((candidate for candidate in candidates if candidate.exists()), candidates[0])


def _points(observed: int, maximum: float, *, full_at: int) -> float:
    return round(maximum * min(1.0, observed / full_at), 1)


def _validate_profile(profile: dict[str, Any]) -> None:
    if not isinstance(profile.get("ads", []), list) or not isinstance(profile.get("technologies", []), list):
        raise ValueError("external profile ads and technologies must be lists")
    for index, ad in enumerate(profile.get("ads", [])):
        required = {"platform", "provider_record_id", "destination", "source_url", "observed_at", "confidence", "method"}
        if required.difference(ad):
            raise ValueError(f"ad observation {index} is missing normalized fields")
        destination = ad["destination"]
        if destination is not None and (
            not isinstance(destination, dict)
            or not destination.get("observed_url")
            or not destination.get("canonical_url")
        ):
            raise ValueError(f"ad observation {index} lacks observed/canonical destination")
    for index, observation in enumerate(profile.get("gap_observations", [])):
        required = {"channel", "position", "url", "excerpt", "observed_at", "confidence", "review_status"}
        if required.difference(observation):
            raise ValueError(f"gap observation {index} is missing evidence fields")


def _gap_component(channel: str, observations: list[dict[str, Any]]) -> dict[str, Any]:
    evidence = [item for item in observations if item["channel"] == channel and item["review_status"] == "approved"]
    supporting = [item for item in evidence if item["position"] == "supports_gap"]
    contradicting = [item for item in evidence if item["position"] == "contradicts_gap"]
    if supporting and contradicting:
        return {
            "score": None,
            "confidence": min(float(item["confidence"]) for item in evidence),
            "state": "unknown",
            "status": "review",
            "evidence": evidence,
            "reasons": ["approved supporting and contradicting gap evidence coexist"],
        }
    if supporting:
        confidence = round(sum(float(item["confidence"]) for item in supporting) / len(supporting), 3)
        return {
            "score": round(100 * confidence, 1),
            "confidence": confidence,
            "state": "observed",
            "status": "provisional_pass",
            "evidence": supporting,
            "reasons": [f"{len(supporting)} approved gap evidence item(s)"],
        }
    return {
        "score": None,
        "confidence": 0.0,
        "state": "unknown",
        "status": "insufficient_evidence",
        "evidence": contradicting,
        "reasons": ["no approved positive gap evidence; public-web absence is unknown"],
    }


def _score_legacy_paid_channels(
    profile: dict[str, Any], asset_summary: dict[str, Any], config: dict[str, Any]
) -> dict[str, Any]:
    _validate_profile(profile)
    for channel, weights in config.get("readiness", {}).items():
        if sum(float(value) for value in weights.values()) != 100:
            raise ValueError(f"{channel} readiness weights must sum to 100")
    category_markers = config.get("technology_category_markers", {})
    ads = profile.get("ads", [])
    technologies = profile.get("technologies", [])
    platforms = {str(ad["platform"]).lower() for ad in ads}
    tracked = [
        ad for ad in ads
        if ad["destination"] and (
            ad["destination"].get("utm_parameters")
            or ad["destination"].get("click_identifiers")
        )
    ]
    tech = [item for item in technologies if item.get("state") == "detected"]
    substantial = int(asset_summary.get("substantial", {}).get("yes", 0))
    asset_types = len(asset_summary.get("asset_types", {}))
    components: dict[str, Any] = {}
    relevant_technology_counts: dict[str, int] = {}
    for channel in ("retargeting", "programmatic"):
        weights = config["readiness"][channel]
        markers = [str(marker).casefold() for marker in category_markers.get(channel, [])]
        relevant_tech = [
            item for item in tech
            if not markers or any(marker in str(item.get("category", "")).casefold() for marker in markers)
        ]
        relevant_technology_counts[channel] = len(relevant_tech)
        confidence_inputs = [float(item["confidence"]) for item in [*ads, *relevant_tech]]
        external_confidence = (
            round(sum(confidence_inputs) / len(confidence_inputs), 3) if confidence_inputs else 0.0
        )
        metrics = {
            "ad_activity": len(ads),
            "tracked_destinations": len(tracked),
            "observable_technology": len(relevant_tech),
            "content_inventory": substantial,
            "platform_diversity": len(platforms),
            "content_diversity": asset_types,
        }
        full_at = {
            "ad_activity": 3,
            "tracked_destinations": 2,
            "observable_technology": 2,
            "content_inventory": 10,
            "platform_diversity": 2,
            "content_diversity": 3,
        }
        factors = [
            {
                "id": factor,
                "observed": metrics[factor],
                "maximum_points": maximum,
                "points": _points(metrics[factor], float(maximum), full_at=full_at[factor]),
            }
            for factor, maximum in weights.items()
        ]
        readiness_score = round(sum(float(item["points"]) for item in factors), 1)
        evidence_coverage = sum(bool(metrics[item]) for item in weights) / len(weights)
        confidence = round(min(0.9, external_confidence * evidence_coverage), 3) if confidence_inputs else 0.0
        components[channel] = {
            "readiness": {
                "score": readiness_score,
                "confidence": confidence,
                "state": "observed" if evidence_coverage else "unknown",
                "status": (
                    "provisional_pass"
                    if readiness_score >= config["qualification"]["minimum_readiness"]
                    and confidence >= config["qualification"]["minimum_confidence"]
                    else "review"
                ),
                "factors": factors,
                "risks": [
                    "technology detections are observable indicators, not proof of complete or active deployment",
                    "provisional weights require real-company calibration",
                ],
            },
            "gap": _gap_component(channel, profile.get("gap_observations", [])),
        }
    return {"channels": components, "metrics": {
        "ads": len(ads), "platforms": sorted(platforms), "tracked_destinations": len(tracked),
        "technology_detections": len(tech), "relevant_technology_detections": relevant_technology_counts,
        "substantial_assets": substantial, "asset_types": asset_types,
    }}


def _creative_metrics(
    creative_analysis: dict[str, Any], config: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, bool], float]:
    scoring_inputs = creative_analysis.get("scoring_inputs", {})
    platforms = creative_analysis.get("platforms", {})
    if not isinstance(scoring_inputs, dict) or not isinstance(platforms, dict):
        raise ValueError("creative analysis scoring inputs and platforms must be objects")
    conclusive = [
        details for details in platforms.values()
        if isinstance(details, dict) and details.get("provider_status") not in {"failed", "inconclusive", "unknown"}
    ]
    activity_states = {
        state: sum(int(details.get("creative_activity_states", {}).get(state, 0)) for details in conclusive)
        for state in ("active", "recently_observed", "historical", "inactive", "unknown")
    }
    funnel_stages = {
        label for details in conclusive for label in details.get("funnel_stages", {})
        if label != "unknown"
    }
    confidence_values = config["sample_confidence_values"]
    sample_values = [
        confidence_values.get(str(details.get("sample_confidence", "none")), 0.0)
        for details in conclusive if int(details.get("ads_inspected", 0)) > 0
    ]
    sample_confidence = round(sum(sample_values) / len(sample_values), 3) if sample_values else 0.0
    metrics = {
        "ad_inventory": int(scoring_inputs.get("provider_total_ads", 0)),
        "observed_platform_diversity": int(scoring_inputs.get("observed_platform_diversity", 0)),
        "current_or_recent_creatives": activity_states["active"] + activity_states["recently_observed"],
        "creative_format_diversity": int(scoring_inputs.get("creative_format_diversity", 0)),
        "funnel_stage_diversity": len(funnel_stages),
        "messaging_theme_diversity": int(scoring_inputs.get("messaging_theme_diversity", 0)),
    }
    current_or_recent = metrics["current_or_recent_creatives"]
    known_activity_states = sum(
        activity_states[state] for state in ("active", "recently_observed", "historical", "inactive")
    )
    known = {
        "ad_inventory": bool(conclusive),
        "observed_platform_diversity": bool(conclusive),
        "current_or_recent_creatives": (
            current_or_recent > 0
            or known_activity_states > 0 and activity_states["unknown"] == 0
            or metrics["ad_inventory"] == 0 and bool(conclusive)
        ),
        "creative_format_diversity": int(scoring_inputs.get("ads_inspected", 0)) > 0,
        "funnel_stage_diversity": int(scoring_inputs.get("analyzable_ads", 0)) > 0,
        "messaging_theme_diversity": int(scoring_inputs.get("analyzable_ads", 0)) > 0,
    }
    return metrics, known, sample_confidence


def _score_v3_paid_channels(
    profile: dict[str, Any], asset_summary: dict[str, Any], config: dict[str, Any],
    creative_analysis: dict[str, Any] | None,
) -> dict[str, Any]:
    _validate_profile(profile)
    for channel, weights in config.get("readiness", {}).items():
        if sum(float(value) for value in weights.values()) != 100:
            raise ValueError(f"{channel} readiness weights must sum to 100")
    ads = profile.get("ads", [])
    technologies = profile.get("technologies", [])
    tech = [item for item in technologies if item.get("state") == "detected"]
    tracked = [
        ad for ad in ads if ad["destination"] and (
            ad["destination"].get("utm_parameters") or ad["destination"].get("click_identifiers")
        )
    ]
    substantial = int(asset_summary.get("substantial", {}).get("yes", 0))
    asset_types = len(asset_summary.get("asset_types", {}))
    creative_values: dict[str, Any] = {}
    creative_known: dict[str, bool] = {}
    sample_confidence = 0.0
    if creative_analysis:
        creative_values, creative_known, sample_confidence = _creative_metrics(
            creative_analysis, config
        )

    collection_complete = False
    if creative_analysis:
        platform_details = creative_analysis.get("platforms", {})
        collection_complete = bool(platform_details) and all(
            isinstance(details, dict)
            and details.get("provider_status") == "completed"
            and details.get("sample_coverage_ratio") in {1, 1.0}
            for details in platform_details.values()
        )

    base_values = {
        "tracked_destinations": len(tracked),
        "content_inventory": substantial,
        "content_diversity": asset_types,
    }
    base_known = {
        "tracked_destinations": bool(tracked) or collection_complete,
        "content_inventory": True,
        "content_diversity": True,
    }
    components: dict[str, Any] = {}
    relevant_technology_counts: dict[str, int] = {}
    all_factor_metrics: dict[str, Any] = {**base_values, **creative_values}
    for channel in ("retargeting", "programmatic"):
        markers = [
            str(marker).casefold()
            for marker in config.get("technology_category_markers", {}).get(channel, [])
        ]
        relevant_tech = [
            item for item in tech
            if not markers or any(marker in str(item.get("category", "")).casefold() for marker in markers)
        ]
        relevant_technology_counts[channel] = len(relevant_tech)
        values = {**all_factor_metrics, "observable_technology": len(relevant_tech)}
        known = {**base_known, **creative_known, "observable_technology": True}
        technology_confidence = (
            round(sum(float(item.get("confidence", 0.0)) for item in relevant_tech) / len(relevant_tech), 3)
            if relevant_tech else 0.6
        )
        confidence_by_factor = {
            "ad_inventory": 0.9,
            "observed_platform_diversity": 0.9,
            "current_or_recent_creatives": sample_confidence,
            "tracked_destinations": sample_confidence,
            "observable_technology": technology_confidence,
            "content_inventory": 0.85,
            "content_diversity": 0.85,
            "creative_format_diversity": sample_confidence,
            "funnel_stage_diversity": sample_confidence,
            "messaging_theme_diversity": sample_confidence,
        }
        factors: list[dict[str, Any]] = []
        known_maximum = 0.0
        earned_points = 0.0
        weighted_confidence = 0.0
        for factor, maximum in config["readiness"][channel].items():
            maximum = float(maximum)
            factor_known = bool(known.get(factor, False))
            points = (
                _points(int(values.get(factor, 0)), maximum, full_at=int(config["full_at"][factor]))
                if factor_known else None
            )
            confidence = confidence_by_factor.get(factor, 0.0) if factor_known else 0.0
            source = (
                "normalized/ad_creative_analysis.json"
                if factor in creative_known
                else "normalized/external_profile.json"
                if factor in {"tracked_destinations", "observable_technology"}
                else "normalized/asset_summary.json"
            )
            factors.append({
                "id": factor,
                "state": "observed" if factor_known else "unknown",
                "observed": int(values.get(factor, 0)) if factor_known else None,
                "maximum_points": maximum,
                "points": points,
                "confidence": round(confidence, 3),
                "source": source,
            })
            if factor_known:
                known_maximum += maximum
                earned_points += float(points)
                weighted_confidence += maximum * confidence
        readiness_score = round(100 * earned_points / known_maximum, 1) if known_maximum else None
        evidence_coverage = round(known_maximum / 100, 3)
        confidence = (
            round(min(0.9, weighted_confidence / known_maximum) * evidence_coverage, 3)
            if known_maximum else 0.0
        )
        qualifies = (
            readiness_score is not None
            and readiness_score >= config["qualification"]["minimum_readiness"]
            and confidence >= config["qualification"]["minimum_confidence"]
            and evidence_coverage >= config["qualification"]["minimum_evidence_coverage"]
        )
        components[channel] = {
            "readiness": {
                "score": readiness_score,
                "confidence": confidence,
                "evidence_coverage": evidence_coverage,
                "state": "observed" if known_maximum else "unknown",
                "status": "provisional_pass" if qualifies else "review",
                "factors": factors,
                "risks": [
                    "creative composition covers returned samples, not necessarily complete provider inventory",
                    "missing or redacted creative fields reduce confidence and never become negative evidence",
                    "technology detections are observable indicators, not proof of complete or active deployment",
                    "V3 creative-derived weights remain provisional pending five-account acceptance validation",
                ],
            },
            "gap": _gap_component(channel, profile.get("gap_observations", [])),
        }
    return {
        "channels": components,
        "metrics": {
            "normalized_ad_rows": len(ads),
            "tracked_destinations": len(tracked),
            "technology_detections": len(tech),
            "relevant_technology_detections": relevant_technology_counts,
            "substantial_assets": substantial,
            "asset_types": asset_types,
            "creative_sample_confidence": sample_confidence,
            **creative_values,
        },
    }


def score_paid_channels(
    profile: dict[str, Any], asset_summary: dict[str, Any], config: dict[str, Any],
    creative_analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if config.get("version") == "paid_channels_v3":
        return _score_v3_paid_channels(profile, asset_summary, config, creative_analysis)
    return _score_legacy_paid_channels(profile, asset_summary, config)


def score_paid_channel_run(
    run_dir: Path, profile_path: Path, config_path: Path | None = None
) -> dict[str, Any]:
    summary_path = run_dir / "normalized" / "asset_summary.json"
    if not summary_path.is_file():
        raise FileNotFoundError("asset summary missing; run analyze-assets first")
    profile_bytes = profile_path.read_bytes()
    summary_bytes = summary_path.read_bytes()
    selected_config = config_path or _default_config()
    config_bytes = selected_config.read_bytes()
    profile = json.loads(profile_bytes)
    creative_path = run_dir / "normalized" / "ad_creative_analysis.json"
    creative_bytes = creative_path.read_bytes() if creative_path.is_file() else None
    result = score_paid_channels(
        profile, json.loads(summary_bytes), json.loads(config_bytes),
        json.loads(creative_bytes) if creative_bytes else None,
    )
    snapshot = _sha256(json.dumps({
        "profile": _sha256(profile_bytes), "assets": _sha256(summary_bytes),
        "config": _sha256(config_bytes), "version": json.loads(config_bytes)["version"],
        "creative_analysis": _sha256(creative_bytes) if creative_bytes else None,
    }, sort_keys=True).encode())
    output = {
        "schema_version": "1.0",
        "scoring_version": json.loads(config_bytes)["version"],
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "snapshot_id": snapshot,
        "input": {
            "profile_file": str(profile_path), "profile_sha256": _sha256(profile_bytes),
            "asset_summary_sha256": _sha256(summary_bytes), "config_file": str(selected_config),
            "config_sha256": _sha256(config_bytes),
            "creative_analysis_file": str(creative_path) if creative_bytes else None,
            "creative_analysis_sha256": _sha256(creative_bytes) if creative_bytes else None,
        },
        **result,
    }
    output_path = run_dir / "normalized" / "paid_channel_scores.json"
    output_path.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output
