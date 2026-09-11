from __future__ import annotations

from collections import Counter
from typing import Any

from .models import Evidence, OpportunityScore


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, round(value, 1)))


def aggregate_metrics(evidence: list[Evidence], account: dict[str, Any]) -> dict[str, Any]:
    asset_types = [e.value for e in evidence if e.signal_type == "content_asset_type"]
    paths = {e.value for e in evidence if e.signal_type == "conversion_path"}
    segments = [e for e in evidence if e.signal_type == "segment_page"]
    gated_values = {
        "gated", "optional_or_partial_gate",  # schema v0 compatibility
        "fully_gated", "optional_gate", "summary_ungated_full_asset_gated", "registration_required",
    }
    gated = [e for e in evidence if e.signal_type == "gating_type" and e.value in gated_values]
    external = account.get("external_signals", {})
    return {
        "substantial_asset_count": len(asset_types),
        "asset_types": dict(Counter(asset_types)),
        "gated_asset_count": len(gated),
        "conversion_paths": sorted(paths),
        "segment_page_count": len(segments),
        "case_study_count": asset_types.count("case_study"),
        "active_ad_channels": external.get("active_ad_channels", []),
        "detected_technologies": external.get("detected_technologies", []),
        "recent_triggers": external.get("recent_triggers", []),
    }


def score_opportunities(account: dict[str, Any], metrics: dict[str, Any]) -> list[OpportunityScore]:
    employee_count = int(account.get("employee_count") or 0)
    b2b = bool(account.get("b2b", True))
    high_acv = bool(account.get("high_acv", False))
    assets = metrics["substantial_asset_count"]
    conversions = len(metrics["conversion_paths"])
    proof = metrics["case_study_count"]
    segments = metrics["segment_page_count"]
    ads = {str(v).lower() for v in metrics["active_ad_channels"]}
    tech = {str(v).lower() for v in metrics["detected_technologies"]}
    triggers = metrics["recent_triggers"]

    common_fit = _clamp((35 if b2b else 0) + (30 if high_acv else 10) + min(employee_count / 4, 35))
    attributable_triggers = [
        item for item in triggers
        if isinstance(item, dict)
        and item.get("url") and item.get("excerpt") and item.get("observed_at")
        and item.get("confidence") is not None
    ]
    trigger_score = _clamp(len(attributable_triggers) * 25) if attributable_triggers else None
    base_confidence = _clamp(45 + assets * 3 + conversions * 6 + proof * 3) / 100

    syndication_readiness = _clamp(assets * 14 + proof * 8 + conversions * 12 + segments * 3)
    retargeting_readiness = _clamp(conversions * 20 + segments * 5 + (25 if ads else 0))
    programmatic_readiness = _clamp((35 if high_acv else 10) + segments * 8 + proof * 6 + min(employee_count / 5, 30))
    outbound_readiness = _clamp((45 if high_acv else 15) + min(employee_count / 4, 25) + segments * 7)

    gap_profiles = account.get("external_signals", {}).get("gap_evidence", {})

    def gap_for(channel: str) -> tuple[float | None, list[dict[str, Any]]]:
        evidence = [
            item for item in gap_profiles.get(channel, [])
            if isinstance(item, dict) and item.get("review_status") == "approved"
            and item.get("url") and item.get("excerpt") and item.get("confidence") is not None
        ]
        supporting = [item for item in evidence if item.get("position") == "supports_gap"]
        contradicting = [item for item in evidence if item.get("position") == "contradicts_gap"]
        if supporting and not contradicting:
            return _clamp(100 * sum(float(item["confidence"]) for item in supporting) / len(supporting)), supporting
        if contradicting and not supporting:
            return 0.0, contradicting
        return None, evidence

    syndication_gap, syndication_gap_evidence = gap_for("content_syndication")
    retargeting_gap, retargeting_gap_evidence = gap_for("retargeting")
    programmatic_gap, programmatic_gap_evidence = gap_for("programmatic")
    outbound_gap, outbound_gap_evidence = gap_for("outbound_calling")

    return [
        OpportunityScore("content_syndication", common_fit, syndication_readiness, syndication_gap, trigger_score, base_confidence,
                         [f"Detected {assets} substantial assets", f"Detected {proof} case studies"],
                         ["Public evidence cannot prove that syndication is absent"], syndication_gap_evidence),
        OpportunityScore("retargeting", common_fit, retargeting_readiness, retargeting_gap, trigger_score, base_confidence,
                         [f"Detected {len(ads)} active ad channels", f"Detected {conversions} conversion paths"],
                         ["Pixels may be consent-gated or implemented server-side"], retargeting_gap_evidence),
        OpportunityScore("programmatic", common_fit, programmatic_readiness, programmatic_gap, trigger_score, base_confidence,
                         [f"Detected {segments} segment-specific pages", f"High-ACV motion: {high_acv}"],
                         ["Programmatic vendors may not expose client-side technology"], programmatic_gap_evidence),
        OpportunityScore("outbound_calling", common_fit, outbound_readiness, outbound_gap, trigger_score, base_confidence,
                         [f"Employee count: {employee_count}", f"High-ACV motion: {high_acv}"],
                         ["Calling activity is rarely observable from the public web"], outbound_gap_evidence),
    ]
