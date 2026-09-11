from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "paid_channel_scoring.v2.json"


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _default_config() -> Path:
    candidates = (
        Path.cwd() / "config" / "paid_channel_scoring.v2.json",
        DEFAULT_CONFIG_PATH,
        Path(sys.prefix) / "share" / "gtm-signal-engine" / "paid_channel_scoring.v2.json",
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


def score_paid_channels(
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
    result = score_paid_channels(profile, json.loads(summary_bytes), json.loads(config_bytes))
    snapshot = _sha256(json.dumps({
        "profile": _sha256(profile_bytes), "assets": _sha256(summary_bytes),
        "config": _sha256(config_bytes), "version": json.loads(config_bytes)["version"],
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
        },
        **result,
    }
    output_path = run_dir / "normalized" / "paid_channel_scores.json"
    output_path.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output
