from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .syndication_scoring import _sha256, load_scoring_config

VALID_STRENGTHS = {"confirmed", "likely", "possible"}


def _normalized_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _parse_date(value: str, label: str) -> date:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError as exc:
        raise ValueError(f"invalid {label}: {value}") from exc


def _validate_profile(profile: dict[str, Any], pages: dict[str, dict[str, Any]]) -> None:
    account = profile.get("account", {})
    if not account.get("name") or not account.get("domain"):
        raise ValueError("trigger profile requires account.name and account.domain")
    if profile.get("kind") != "business_trigger":
        raise ValueError("trigger profile kind must be business_trigger")
    observations = profile.get("observations")
    if not isinstance(observations, list):
        raise ValueError("trigger profile observations must be a list")
    for index, observation in enumerate(observations):
        required = {
            "signal_type", "trigger_relevance", "strength", "confidence", "url",
            "excerpt", "observed_at", "method", "content_sha256",
        }
        missing = required.difference(observation)
        if missing:
            raise ValueError(f"observation {index} missing fields: {', '.join(sorted(missing))}")
        if observation["strength"] not in VALID_STRENGTHS:
            raise ValueError(f"observation {index} has invalid strength")
        if observation["trigger_relevance"] not in {"direct", "adjacent"}:
            raise ValueError(f"observation {index} has invalid trigger_relevance")
        if not 0 <= float(observation["confidence"]) <= 1:
            raise ValueError(f"observation {index} confidence must be between 0 and 1")
        if observation["method"] != "scrapling_saved_page":
            raise ValueError(f"observation {index} must use method scrapling_saved_page")
        url = str(observation["url"])
        if urlsplit(url).scheme not in {"http", "https"} or url not in pages:
            raise ValueError(f"observation {index} URL is not present in the Scrapling run")
        page = pages[url]
        if not re.fullmatch(r"[0-9a-f]{64}", str(observation["content_sha256"])):
            raise ValueError(f"observation {index} has invalid content_sha256")
        if observation["content_sha256"] != page.get("content_hash"):
            raise ValueError(f"observation {index} content hash does not match the saved page")
        if observation["observed_at"] != page.get("observed_at"):
            raise ValueError(f"observation {index} observed_at does not match the saved page")
        excerpt = _normalized_text(str(observation["excerpt"]))
        page_text = _normalized_text(f"{page.get('main_text', '')} {page.get('text', '')}")
        if not excerpt or excerpt not in page_text:
            raise ValueError(f"observation {index} excerpt is not present in the saved page")
        _parse_date(str(observation["observed_at"]), f"observation {index} observed_at")
        source_date = observation.get("source_date")
        if source_date is not None:
            if (
                not isinstance(source_date, dict)
                or not source_date.get("value")
                or not source_date.get("source")
                or not 0 <= float(source_date.get("confidence", -1)) <= 1
            ):
                raise ValueError(f"observation {index} has invalid source_date")
            _parse_date(str(source_date["value"]), f"observation {index} source_date")


def _validate_config(config: dict[str, Any]) -> None:
    settings = config.get("initiative_trigger", {})
    factors = settings.get("factors", [])
    if not factors:
        raise ValueError("initiative_trigger factors are required")
    if len({factor["signal_type"] for factor in factors}) != len(factors):
        raise ValueError("initiative_trigger signal types must be unique")
    if any(not 0 <= float(factor["base_points"]) <= 100 for factor in factors):
        raise ValueError("initiative_trigger base_points must be between 0 and 100")
    if set(settings.get("strength_credit", {})) != VALID_STRENGTHS:
        raise ValueError("initiative_trigger strength_credit is incomplete")
    freshness = settings.get("freshness_credit", {})
    if set(freshness) != {"within_90_days", "within_180_days", "within_365_days", "older", "unknown"}:
        raise ValueError("initiative_trigger freshness_credit is incomplete")
    if any(not 0 <= float(value) <= 1 for value in (*freshness.values(), *settings["strength_credit"].values())):
        raise ValueError("initiative_trigger credits must be between 0 and 1")


def _freshness_credit(observation: dict[str, Any], as_of: date, config: dict[str, Any]) -> tuple[float, int | None]:
    credits = config["initiative_trigger"]["freshness_credit"]
    source_date = observation.get("source_date")
    if not source_date:
        return float(credits["unknown"]), None
    event_date = _parse_date(str(source_date["value"]), "source_date")
    age_days = (as_of - event_date).days
    if age_days < 0:
        raise ValueError("source_date cannot be after the scoring as_of date")
    if age_days <= 90:
        key = "within_90_days"
    elif age_days <= 180:
        key = "within_180_days"
    elif age_days <= 365:
        key = "within_365_days"
    else:
        key = "older"
    return float(credits[key]), age_days


def score_business_trigger(
    profile: dict[str, Any],
    pages: dict[str, dict[str, Any]],
    config: dict[str, Any],
    *,
    as_of: date,
) -> dict[str, Any]:
    _validate_profile(profile, pages)
    _validate_config(config)
    observations = profile["observations"]
    if not observations:
        return {
            "score": None,
            "state": "unknown",
            "confidence": 0.0,
            "status": "insufficient_evidence",
            "factors": [],
            "reasons": [],
            "risks": ["no reviewed initiative evidence is available; candidate absence is not evidence of no trigger"],
            "evidence": [],
        }
    settings = config["initiative_trigger"]
    strength_credit = settings["strength_credit"]
    factors_by_type = {factor["signal_type"]: factor for factor in settings["factors"]}
    for observation in observations:
        factor = factors_by_type.get(observation["signal_type"])
        if factor is None:
            raise ValueError(f"unsupported initiative signal type: {observation['signal_type']}")
        if observation["trigger_relevance"] != factor["expected_relevance"]:
            raise ValueError(
                f"trigger relevance does not match signal type {observation['signal_type']}"
            )
    factors = []
    selected = []
    for factor in settings["factors"]:
        candidates = [item for item in observations if item["signal_type"] == factor["signal_type"]]
        if not candidates:
            factors.append({**factor, "points": 0.0, "state": "unknown", "evidence": []})
            continue
        ranked = []
        for observation in candidates:
            freshness, age_days = _freshness_credit(observation, as_of, config)
            points = round(
                float(factor["base_points"])
                * float(strength_credit[observation["strength"]])
                * freshness,
                1,
            )
            ranked.append((points, float(observation["confidence"]), observation, freshness, age_days))
        points, _, strongest, freshness, age_days = max(ranked, key=lambda item: (item[0], item[1]))
        selected.append(strongest)
        factors.append({
            **factor,
            "points": points,
            "state": strongest["strength"],
            "freshness_credit": freshness,
            "age_days": age_days,
            "evidence": [strongest],
        })
    selected_points = [float(factor["points"]) for factor in factors if factor["evidence"]]
    score = min(
        float(settings["maximum_score"]),
        max(selected_points) + float(settings["additional_signal_type_bonus"]) * (len(selected_points) - 1),
    )
    evidence_confidences = [
        min(
            float(item["confidence"]),
            float(item["source_date"]["confidence"]) if item.get("source_date") else 1.0,
        )
        for item in selected
    ]
    confidence = sum(evidence_confidences) / len(evidence_confidences)
    if any(item.get("source_date") is None for item in selected):
        confidence = min(confidence, float(settings["unknown_date_confidence_cap"]))
    confidence = round(confidence, 3)
    status = (
        "provisional_pass"
        if score >= float(settings["minimum_trigger"])
        and confidence >= float(settings["minimum_confidence"])
        else "review"
    )
    risks = list(profile.get("risks", []))
    if any(item.get("source_date") is None for item in selected):
        risks.append("one or more initiative dates are unknown; freshness and confidence were capped")
    return {
        "score": round(score, 1),
        "state": "observed",
        "confidence": confidence,
        "status": status,
        "factors": factors,
        "reasons": [f"{len(selected)} reviewed initiative signal type(s) scored as of {as_of.isoformat()}"],
        "risks": risks,
        "evidence": selected,
    }


def score_business_trigger_run(
    run_dir: Path,
    profile_path: Path,
    config_path: Path | None = None,
    *,
    as_of: date | None = None,
) -> dict[str, Any]:
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("provider") != "ScraplingFetcher":
        raise ValueError("trigger evidence requires a ScraplingFetcher run")
    pages_path = run_dir / "normalized" / "pages.jsonl"
    pages_bytes = pages_path.read_bytes()
    pages = {
        item["url"]: item
        for line in pages_bytes.splitlines() if line.strip()
        for item in [json.loads(line)]
    }
    profile_bytes = profile_path.read_bytes()
    profile = json.loads(profile_bytes)
    profile_domain = str(profile.get("account", {}).get("domain", "")).lower().removeprefix("www.")
    seed_domain = (urlsplit(str(manifest.get("seed_url", ""))).hostname or "").lower().removeprefix("www.")
    if profile_domain != seed_domain:
        raise ValueError("trigger profile domain does not match the Scrapling run seed domain")
    config, config_bytes, selected_config = load_scoring_config(config_path)
    selected_as_of = as_of or datetime.now(timezone.utc).date()
    component = score_business_trigger(profile, pages, config, as_of=selected_as_of)
    snapshot_material = json.dumps({
        "profile_sha256": _sha256(profile_bytes),
        "pages_sha256": _sha256(pages_bytes),
        "config_sha256": _sha256(config_bytes),
        "scoring_version": config["version"],
        "as_of": selected_as_of.isoformat(),
    }, sort_keys=True).encode("utf-8")
    result = {
        "schema_version": "1.0",
        "scoring_version": config["version"],
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "as_of": selected_as_of.isoformat(),
        "snapshot_id": hashlib.sha256(snapshot_material).hexdigest(),
        "account": profile["account"],
        "kind": profile["kind"],
        "input": {
            "run_id": manifest["run_id"],
            "profile_file": str(profile_path),
            "profile_sha256": _sha256(profile_bytes),
            "pages_file": "normalized/pages.jsonl",
            "pages_sha256": _sha256(pages_bytes),
            "config_file": str(selected_config),
            "config_sha256": _sha256(config_bytes),
        },
        "component": component,
    }
    output_path = run_dir / "normalized" / "business_trigger.json"
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result
