from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "content_syndication_scoring.v2.json"


def _default_config_path() -> Path:
    candidates = (
        Path.cwd() / "config" / "content_syndication_scoring.v2.json",
        DEFAULT_CONFIG_PATH,
        Path(sys.prefix) / "share" / "gtm-signal-engine" / "content_syndication_scoring.v2.json",
    )
    return next((candidate for candidate in candidates if candidate.exists()), candidates[0])


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _tier_points(value: float, tiers: list[dict[str, Any]]) -> float:
    points = 0.0
    for tier in sorted(tiers, key=lambda item: float(item["minimum"])):
        if value >= float(tier["minimum"]):
            points = float(tier["points"])
    return points


def _validate_config(config: dict[str, Any]) -> None:
    weights = config.get("component_weights", {})
    if set(weights) != {"fit", "readiness", "gap", "trigger"}:
        raise ValueError("component_weights must define fit, readiness, gap, and trigger")
    if abs(sum(float(value) for value in weights.values()) - 1.0) > 1e-9:
        raise ValueError("component_weights must sum to 1.0")
    factors = config.get("readiness_factors", [])
    if not factors or sum(float(item["maximum_points"]) for item in factors) != 100:
        raise ValueError("readiness factor maximum_points must sum to 100")
    for factor in factors:
        maximum = float(factor["maximum_points"])
        if any(float(tier["points"]) > maximum for tier in factor["tiers"]):
            raise ValueError(f"factor {factor['id']} tier exceeds maximum_points")
    confidence_weights = config.get("confidence", {}).get("weights", {})
    if abs(sum(float(value) for value in confidence_weights.values()) - 1.0) > 1e-9:
        raise ValueError("confidence weights must sum to 1.0")
    trigger = config.get("trigger", {})
    if any(float(tier["points"]) > float(trigger["maximum_points_from_content"]) for tier in trigger["recent_asset_tiers"]):
        raise ValueError("trigger tier exceeds maximum_points_from_content")


def load_scoring_config(path: Path | None = None) -> tuple[dict[str, Any], bytes, Path]:
    selected = path or _default_config_path()
    config_bytes = selected.read_bytes()
    config = json.loads(config_bytes)
    _validate_config(config)
    return config, config_bytes, selected


def _load_jsonl(path: Path) -> tuple[list[dict[str, Any]], bytes]:
    value = path.read_bytes()
    return [json.loads(line) for line in value.splitlines() if line.strip()], value


def _metrics(assets: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    substantial = [asset for asset in assets if asset.get("substantial") == "yes"]
    suitable = sum(asset.get("syndication_suitability") == "suitable" for asset in assets)
    possible = sum(asset.get("syndication_suitability") == "possible" for asset in assets)
    possible_credit = float(config["interpretation"]["possible_suitability_credit"])
    effective_suitability = suitable + possible * possible_credit
    gated_values = set(config["interpretation"]["gated_values"])
    return {
        "asset_count": len(assets),
        "substantial_asset_count": len(substantial),
        "substantial_asset_type_count": len({asset.get("asset_type") for asset in substantial}),
        "substantial_case_study_count": sum(asset.get("asset_type") == "case_study" for asset in substantial),
        "assets_within_90_days": sum(
            isinstance(asset.get("age_days"), int) and asset["age_days"] <= 90 for asset in assets
        ),
        "assets_within_365_days": sum(
            isinstance(asset.get("age_days"), int) and asset["age_days"] <= 365 for asset in assets
        ),
        "effective_suitability_ratio": round(effective_suitability / len(assets), 4) if assets else 0.0,
        "lead_capture_asset_count": sum(asset.get("gating") in gated_values for asset in assets),
        "known_date_count": sum(asset.get("published_or_created") is not None for asset in assets),
        "known_substance_count": sum(asset.get("substantial") in {"yes", "no"} for asset in assets),
        "known_gating_count": sum(asset.get("gating") != "unknown" for asset in assets),
        "suitable_asset_count": suitable,
        "possible_suitability_count": possible,
    }


def _factor_urls(factor_id: str, assets: list[dict[str, Any]]) -> list[str]:
    predicates = {
        "substantial_asset_inventory": lambda asset: asset.get("substantial") == "yes",
        "asset_type_diversity": lambda asset: asset.get("substantial") == "yes",
        "customer_proof": lambda asset: asset.get("substantial") == "yes" and asset.get("asset_type") == "case_study",
        "assets_within_90_days": lambda asset: isinstance(asset.get("age_days"), int) and asset["age_days"] <= 90,
        "assets_within_365_days": lambda asset: isinstance(asset.get("age_days"), int) and asset["age_days"] <= 365,
        "effective_suitability_ratio": lambda asset: asset.get("syndication_suitability") in {"suitable", "possible"},
        "lead_capture_assets": lambda asset: asset.get("gating") not in {"fully_ungated", "unknown"},
    }
    if factor_id == "asset_type_diversity":
        selected: dict[str, str] = {}
        for asset in assets:
            if asset.get("substantial") == "yes" and asset.get("asset_type") not in selected:
                selected[str(asset.get("asset_type"))] = asset["url"]
        return list(selected.values())[:5]
    predicate = predicates[factor_id]
    return [asset["url"] for asset in assets if predicate(asset)][:5]


def _readiness(
    assets: list[dict[str, Any]], metrics: dict[str, Any], config: dict[str, Any]
) -> tuple[float, list[dict[str, Any]]]:
    factors: list[dict[str, Any]] = []
    score = 0.0
    for factor in config["readiness_factors"]:
        observed = float(metrics[factor["metric"]])
        points = _tier_points(observed, factor["tiers"])
        score += points
        factors.append({
            "id": factor["id"],
            "metric": factor["metric"],
            "observed": metrics[factor["metric"]],
            "points": points,
            "maximum_points": factor["maximum_points"],
            "evidence_urls": _factor_urls(factor["id"], assets),
        })
    return round(score, 1), factors


def _confidence(
    assets: list[dict[str, Any]], summary: dict[str, Any], manifest: dict[str, Any] | None,
    config: dict[str, Any],
) -> tuple[float, dict[str, float], list[str]]:
    count = max(1, len(assets))
    raw = summary.get("raw_artifacts", {})
    raw_integrity = 1.0 if raw.get("documents_available", 0) and not raw.get("errors") else 0.0
    factors = {
        "raw_integrity": raw_integrity,
        "date_coverage": sum(asset.get("published_or_created") is not None for asset in assets) / count,
        "substance_coverage": sum(asset.get("substantial") in {"yes", "no"} for asset in assets) / count,
        "gating_coverage": sum(asset.get("gating") != "unknown" for asset in assets) / count,
        "crawl_completeness": (
            1.0 if manifest and not manifest.get("incomplete", True)
            else float(config["confidence"]["partial_crawl_value"]) if manifest
            else 0.0
        ),
    }
    value = sum(
        factors[name] * float(weight)
        for name, weight in config["confidence"]["weights"].items()
    )
    risks: list[str] = []
    if manifest and manifest.get("incomplete", True):
        value = min(value, float(config["confidence"]["incomplete_crawl_cap"]))
        risks.append("crawl was bounded/partial; scores describe observed priority pages, not the full site")
    elif manifest is None:
        value = min(value, float(config["confidence"]["missing_manifest_cap"]))
        risks.append("crawl manifest unavailable; collection completeness could not be verified")
    if factors["date_coverage"] < 1:
        risks.append("some asset publication/creation dates are unknown")
    if factors["substance_coverage"] < 1:
        risks.append("some gated or thin assets have unknown substance")
    if raw.get("errors"):
        risks.append("raw artifact integrity errors reduced confidence")
    return round(max(0.0, min(1.0, value)), 3), {key: round(value, 3) for key, value in factors.items()}, risks


def _weighted_total(components: dict[str, dict[str, Any]], weights: dict[str, float]) -> float | None:
    if any(components[name]["score"] is None for name in weights):
        return None
    return round(sum(float(components[name]["score"]) * float(weight) for name, weight in weights.items()), 1)


def _summary_fingerprint(summary: dict[str, Any]) -> str:
    stable = {key: value for key, value in summary.items() if key != "analyzed_at"}
    return _sha256(json.dumps(stable, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def score_syndication_run(run_dir: Path, config_path: Path | None = None) -> dict[str, Any]:
    assets_path = run_dir / "normalized" / "assets.jsonl"
    summary_path = run_dir / "normalized" / "asset_summary.json"
    if not assets_path.exists() or not summary_path.exists():
        raise FileNotFoundError("asset analysis outputs missing; run analyze-assets first")
    assets, assets_bytes = _load_jsonl(assets_path)
    summary_bytes = summary_path.read_bytes()
    summary = json.loads(summary_bytes)
    config, config_bytes, selected_config = load_scoring_config(config_path)
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else None
    metrics = _metrics(assets, config)
    readiness_score, readiness_factors = _readiness(assets, metrics, config)
    confidence, confidence_factors, risks = _confidence(assets, summary, manifest, config)
    readiness_confidence = confidence
    fit_path = run_dir / "normalized" / "account_fit.json"
    fit_report = json.loads(fit_path.read_text(encoding="utf-8")) if fit_path.exists() else None
    if fit_report:
        fit_component = {**fit_report["component"], "snapshot_id": fit_report["snapshot_id"]}
        confidence = round(min(confidence, float(fit_component["confidence"])), 3)
        confidence_factors["fit_component"] = float(fit_component["confidence"])
    else:
        fit_component = {
            "score": None,
            "state": "unknown",
            "reasons": [],
            "risks": ["sourced account-fit assessment is unavailable; run score-fit first"],
        }
    gap_path = run_dir / "normalized" / "channel_gap.json"
    gap_report = json.loads(gap_path.read_text(encoding="utf-8")) if gap_path.exists() else None
    if gap_report:
        gap_component = {**gap_report["component"], "snapshot_id": gap_report["snapshot_id"]}
        if gap_component.get("score") is not None and gap_component.get("confidence") is not None:
            confidence = round(min(confidence, float(gap_component["confidence"])), 3)
            confidence_factors["gap_component"] = float(gap_component["confidence"])
    else:
        gap_component = {
            "score": None,
            "state": "unknown",
            "reasons": [],
            "risks": ["Scrapling-backed channel-gap assessment is unavailable; run score-gap first"],
            "status": "insufficient_evidence",
        }
    recent_count = metrics["assets_within_90_days"]
    trigger_score = _tier_points(float(recent_count), config["trigger"]["recent_asset_tiers"])
    content_trigger_component: dict[str, Any]
    if metrics["known_date_count"] == 0:
        content_trigger_component = {
            "score": None,
            "state": "unknown",
            "confidence": 0.0,
            "status": "insufficient_evidence",
            "reasons": ["no attributable publication or creation dates were observed"],
            "risks": ["absence of dated assets is not proof that no current trigger exists"],
        }
    else:
        content_trigger_component = {
            "score": trigger_score,
            "state": "possible",
            "confidence": readiness_confidence,
            "status": "review",
            "reasons": [f"{recent_count} observed assets were created or published within 90 days"],
            "risks": [
                f"content activity contributes at most {config['trigger']['maximum_points_from_content']} trigger points; external business triggers are not yet analyzed"
            ],
        }
    trigger_path = run_dir / "normalized" / "business_trigger.json"
    trigger_report = json.loads(trigger_path.read_text(encoding="utf-8")) if trigger_path.exists() else None
    reviewed_trigger = trigger_report["component"] if trigger_report else None
    if reviewed_trigger and reviewed_trigger.get("score") is not None:
        content_score = content_trigger_component.get("score")
        reviewed_score = float(reviewed_trigger["score"])
        if content_score is None or reviewed_score >= float(content_score):
            trigger_component = {
                **reviewed_trigger,
                "reasons": [
                    *reviewed_trigger.get("reasons", []),
                    *content_trigger_component.get("reasons", []),
                ],
                "risks": [
                    *reviewed_trigger.get("risks", []),
                    "reviewed initiatives and content activity are combined by maximum score to avoid double counting",
                ],
            }
        else:
            trigger_component = {
                **content_trigger_component,
                "reviewed_initiative_component": reviewed_trigger,
                "risks": [
                    *content_trigger_component.get("risks", []),
                    "reviewed initiatives and content activity are combined by maximum score to avoid double counting",
                ],
            }
    else:
        trigger_component = content_trigger_component
    if trigger_component.get("score") is not None and trigger_component.get("confidence") is not None:
        confidence = round(min(confidence, float(trigger_component["confidence"])), 3)
        confidence_factors["trigger_component"] = float(trigger_component["confidence"])
    components = {
        "fit": fit_component,
        "readiness": {
            "score": readiness_score,
            "state": "observed",
            "factors": readiness_factors,
            "reasons": [
                f"{metrics['substantial_asset_count']} substantial assets observed",
                f"{metrics['assets_within_90_days']} assets observed within 90 days",
                f"{metrics['lead_capture_asset_count']} assets have an observed lead-capture path",
            ],
            "risks": risks,
        },
        "gap": gap_component,
        "trigger": trigger_component,
    }
    total = _weighted_total(components, config["component_weights"])
    qualification = config["qualification"]
    readiness_pass = (
        readiness_score >= float(qualification["minimum_readiness"])
        and confidence >= float(qualification["minimum_confidence"])
        and len(assets) >= int(qualification["minimum_asset_evidence"])
    )
    blockers = [name for name in ("fit", "gap", "trigger") if components[name]["score"] is None]
    summary_fingerprint = _summary_fingerprint(summary)
    fit_snapshot_id = fit_report["snapshot_id"] if fit_report else None
    gap_snapshot_id = gap_report["snapshot_id"] if gap_report else None
    trigger_snapshot_id = trigger_report["snapshot_id"] if trigger_report else None
    snapshot_material = json.dumps({
        "assets_sha256": _sha256(assets_bytes),
        "summary_fingerprint_sha256": summary_fingerprint,
        "config_sha256": _sha256(config_bytes),
        "scoring_version": config["version"],
        "calibration_status": config["calibration"]["status"],
        "fit_snapshot_id": fit_snapshot_id,
        "gap_snapshot_id": gap_snapshot_id,
        "trigger_snapshot_id": trigger_snapshot_id,
    }, sort_keys=True).encode("utf-8")
    result = {
        "schema_version": "1.0",
        "channel": "content_syndication",
        "scoring_version": config["version"],
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "snapshot_id": _sha256(snapshot_material),
        "input": {
            "run_id": manifest.get("run_id") if manifest else run_dir.name,
            "assets_file": str(assets_path.relative_to(run_dir)),
            "assets_sha256": _sha256(assets_bytes),
            "asset_summary_sha256": _sha256(summary_bytes),
            "asset_summary_fingerprint_sha256": summary_fingerprint,
            "config_file": str(selected_config),
            "config_sha256": _sha256(config_bytes),
            "account_fit_file": str(fit_path.relative_to(run_dir)) if fit_report else None,
            "account_fit_snapshot_id": fit_snapshot_id,
            "channel_gap_file": str(gap_path.relative_to(run_dir)) if gap_report else None,
            "channel_gap_snapshot_id": gap_snapshot_id,
            "business_trigger_file": str(trigger_path.relative_to(run_dir)) if trigger_report else None,
            "business_trigger_snapshot_id": trigger_snapshot_id,
        },
        "metrics": metrics,
        "components": components,
        "total": total,
        "confidence": confidence,
        "component_confidence": {
            "readiness": readiness_confidence,
            "fit": fit_component.get("confidence"),
            "gap": gap_component.get("confidence"),
            "trigger": trigger_component.get("confidence"),
        },
        "confidence_factors": confidence_factors,
        "qualification": {
            "readiness_status": "provisional_pass" if readiness_pass else "review",
            "fit_status": fit_component.get("status", "insufficient_evidence"),
            "gap_status": gap_component.get("status", "insufficient_evidence"),
            "trigger_status": trigger_component.get("status", "insufficient_evidence"),
            "opportunity_status": (
                "qualified"
                if total is not None
                and readiness_pass
                and fit_component.get("status") == "provisional_pass"
                and gap_component.get("status") == "provisional_pass"
                else "insufficient_evidence"
            ),
            "blockers": blockers,
            "thresholds": qualification,
        },
    }
    output_path = run_dir / "normalized" / "syndication_score.json"
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result
