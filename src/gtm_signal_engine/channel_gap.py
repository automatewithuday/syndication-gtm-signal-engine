from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .syndication_scoring import _sha256, load_scoring_config

VALID_STRENGTHS = {"confirmed", "likely", "possible", "unknown", "contradicted"}
VALID_POLARITIES = {"supports_gap", "contradicts_gap"}


def _normalized_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _load_scrapling_pages(run_dir: Path) -> tuple[dict[str, dict[str, Any]], bytes, dict[str, Any]]:
    manifest_path = run_dir / "manifest.json"
    pages_path = run_dir / "normalized" / "pages.jsonl"
    if not manifest_path.exists() or not pages_path.exists():
        raise FileNotFoundError("Scrapling manifest/pages missing; run crawl first")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("provider") != "ScraplingFetcher":
        raise ValueError("channel-gap evidence requires a ScraplingFetcher run")
    pages_bytes = pages_path.read_bytes()
    pages = {
        item["url"]: item
        for line in pages_bytes.splitlines()
        if line.strip()
        for item in [json.loads(line)]
    }
    return pages, pages_bytes, manifest


def _validate_profile(profile: dict[str, Any], pages: dict[str, dict[str, Any]]) -> None:
    account = profile.get("account", {})
    if not account.get("name") or not account.get("domain"):
        raise ValueError("gap profile requires account.name and account.domain")
    if profile.get("channel") != "content_syndication":
        raise ValueError("gap profile channel must be content_syndication")
    observations = profile.get("observations")
    if not isinstance(observations, list):
        raise ValueError("gap profile observations must be a list")
    for index, observation in enumerate(observations):
        required = {
            "signal_type", "polarity", "strength", "confidence", "url", "excerpt",
            "observed_at", "method", "content_sha256",
        }
        missing = required.difference(observation)
        if missing:
            raise ValueError(f"observation {index} missing fields: {', '.join(sorted(missing))}")
        if observation["polarity"] not in VALID_POLARITIES:
            raise ValueError(f"observation {index} has invalid polarity")
        if observation["strength"] not in VALID_STRENGTHS:
            raise ValueError(f"observation {index} has invalid strength")
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


def _validate_gap_config(config: dict[str, Any]) -> None:
    factors = config.get("gap_factors", [])
    if not factors or sum(float(factor["maximum_points"]) for factor in factors) != 100:
        raise ValueError("gap factor maximum_points must sum to 100")
    known = {factor["signal_type"] for factor in factors}
    contradictions = set(config.get("gap_interpretation", {}).get("contradiction_signal_types", []))
    if known.intersection(contradictions):
        raise ValueError("gap support and contradiction signal types must be distinct")


def score_channel_gap(profile: dict[str, Any], pages: dict[str, dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    _validate_profile(profile, pages)
    _validate_gap_config(config)
    interpretation = config["gap_interpretation"]
    credits = interpretation["strength_credit"]
    support_types = {factor["signal_type"] for factor in config["gap_factors"]}
    contradiction_types = set(interpretation["contradiction_signal_types"])
    for index, observation in enumerate(profile["observations"]):
        signal_type = observation["signal_type"]
        if signal_type not in support_types | contradiction_types:
            raise ValueError(f"unsupported gap signal type: {signal_type}")
        expected_polarity = "supports_gap" if signal_type in support_types else "contradicts_gap"
        if observation["polarity"] != expected_polarity:
            raise ValueError(f"observation {index} polarity does not match signal type {signal_type}")
    usable = [
        observation for observation in profile["observations"]
        if observation["strength"] not in {"unknown", "contradicted"}
    ]
    contradictions = [
        observation for observation in usable
        if observation["polarity"] == "contradicts_gap"
        or observation["signal_type"] in contradiction_types
    ]
    support = [observation for observation in usable if observation["polarity"] == "supports_gap"]
    if support and contradictions:
        confidence = round(sum(float(item["confidence"]) for item in usable) / len(usable), 3)
        return {
            "score": None,
            "state": "unknown",
            "confidence": confidence,
            "status": "review",
            "factors": [],
            "reasons": ["supporting and contradicting channel-gap evidence conflict"],
            "risks": ["resolve timing and scope before scoring the channel gap"],
            "evidence": usable,
        }
    if contradictions:
        confidence = round(sum(float(item["confidence"]) for item in contradictions) / len(contradictions), 3)
        return {
            "score": 0.0,
            "state": "contradicted",
            "confidence": confidence,
            "status": "disqualified",
            "factors": [],
            "reasons": ["saved evidence documents an active or successful content-syndication program"],
            "risks": ["do not claim the channel is unused or underdeveloped"],
            "evidence": contradictions,
        }
    if not support:
        return {
            "score": None,
            "state": "unknown",
            "confidence": 0.0,
            "status": "insufficient_evidence",
            "factors": [],
            "reasons": [],
            "risks": ["no positive gap evidence was observed; public-web absence is not a channel gap"],
            "evidence": [],
        }

    factors: list[dict[str, Any]] = []
    score = 0.0
    selected_evidence: list[dict[str, Any]] = []
    for factor in config["gap_factors"]:
        candidates = [item for item in support if item["signal_type"] == factor["signal_type"]]
        if not candidates:
            factors.append({**factor, "points": 0.0, "state": "unknown", "evidence": []})
            continue
        strongest = max(candidates, key=lambda item: (credits[item["strength"]], float(item["confidence"])))
        points = round(float(factor["maximum_points"]) * float(credits[strongest["strength"]]), 1)
        score += points
        selected_evidence.append(strongest)
        factors.append({
            **factor,
            "points": points,
            "state": strongest["strength"],
            "evidence": [strongest],
        })
    confidence = round(sum(float(item["confidence"]) for item in selected_evidence) / len(selected_evidence), 3)
    pass_gap = (
        score >= float(interpretation["minimum_gap"])
        and confidence >= float(interpretation["minimum_confidence"])
        and len(selected_evidence) >= int(interpretation["minimum_supporting_evidence"])
    )
    return {
        "score": round(score, 1),
        "state": "observed",
        "confidence": confidence,
        "status": "provisional_pass" if pass_gap else "review",
        "factors": factors,
        "reasons": [f"{len(selected_evidence)} positive gap signal type(s) verified against saved Scrapling pages"],
        "risks": list(profile.get("risks", [])),
        "evidence": selected_evidence,
    }


def score_channel_gap_run(run_dir: Path, profile_path: Path, config_path: Path | None = None) -> dict[str, Any]:
    pages, pages_bytes, manifest = _load_scrapling_pages(run_dir)
    profile_bytes = profile_path.read_bytes()
    profile = json.loads(profile_bytes)
    profile_domain = str(profile.get("account", {}).get("domain", "")).lower().removeprefix("www.")
    seed_domain = (urlsplit(str(manifest.get("seed_url", ""))).hostname or "").lower().removeprefix("www.")
    if profile_domain != seed_domain:
        raise ValueError("gap profile domain does not match the Scrapling run seed domain")
    config, config_bytes, selected_config = load_scoring_config(config_path)
    component = score_channel_gap(profile, pages, config)
    snapshot_material = json.dumps({
        "profile_sha256": _sha256(profile_bytes),
        "pages_sha256": _sha256(pages_bytes),
        "config_sha256": _sha256(config_bytes),
        "scoring_version": config["version"],
    }, sort_keys=True).encode("utf-8")
    result = {
        "schema_version": "1.0",
        "scoring_version": config["version"],
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "snapshot_id": hashlib.sha256(snapshot_material).hexdigest(),
        "account": profile["account"],
        "channel": profile["channel"],
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
    output_path = run_dir / "normalized" / "channel_gap.json"
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result
