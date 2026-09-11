from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .syndication_scoring import _sha256, _tier_points, load_scoring_config

VALID_STRENGTHS = {"confirmed", "likely", "possible", "unknown", "contradicted"}


def _normalized_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _load_scrapling_run(run_dir: Path) -> tuple[dict[tuple[str, str], dict[str, Any]], bytes, dict[str, Any]]:
    manifest_path = run_dir / "manifest.json"
    pages_path = run_dir / "normalized" / "pages.jsonl"
    if not manifest_path.exists() or not pages_path.exists():
        raise FileNotFoundError("account-fit scoring requires a saved Scrapling manifest and pages")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("provider") != "ScraplingFetcher":
        raise ValueError("account-fit evidence requires a ScraplingFetcher run")
    pages_bytes = pages_path.read_bytes()
    pages = {
        (item["url"], item["content_hash"]): item
        for line in pages_bytes.splitlines() if line.strip()
        for item in [json.loads(line)]
    }
    return pages, pages_bytes, manifest


def _validate_scrapling_facts(
    profile: dict[str, Any], pages: dict[tuple[str, str], dict[str, Any]], manifest: dict[str, Any]
) -> None:
    profile_domain = str(profile.get("account", {}).get("domain", "")).lower().removeprefix("www.")
    seed_domain = (urlsplit(str(manifest.get("seed_url", ""))).hostname or "").lower().removeprefix("www.")
    if profile_domain != seed_domain:
        raise ValueError("account-fit profile domain does not match the Scrapling run seed domain")
    for index, fact in enumerate(profile["facts"]):
        if fact.get("method") != "scrapling_saved_page":
            raise ValueError(f"fact {index} must use method scrapling_saved_page")
        content_hash = str(fact.get("content_sha256", ""))
        if not re.fullmatch(r"[0-9a-f]{64}", content_hash):
            raise ValueError(f"fact {index} has invalid content_sha256")
        page = pages.get((str(fact["url"]), content_hash))
        if page is None:
            raise ValueError(f"fact {index} URL/content hash is not present in the Scrapling run")
        if fact["observed_at"] != page.get("observed_at"):
            raise ValueError(f"fact {index} observed_at does not match the saved page")
        excerpt = _normalized_text(str(fact["excerpt"]))
        page_text = _normalized_text(f"{page.get('main_text', '')} {page.get('text', '')}")
        if excerpt not in page_text:
            raise ValueError(f"fact {index} excerpt is not present in the saved page")


def _validate_profile(profile: dict[str, Any]) -> None:
    account = profile.get("account", {})
    if not account.get("name") or not account.get("domain"):
        raise ValueError("account profile requires account.name and account.domain")
    facts = profile.get("facts")
    if not isinstance(facts, list) or not facts:
        raise ValueError("account profile requires at least one evidence-backed fact")
    for index, fact in enumerate(facts):
        missing = {
            key for key in ("fact_type", "value", "strength", "confidence", "url", "excerpt", "observed_at")
            if key not in fact
        }
        if missing:
            raise ValueError(f"fact {index} missing fields: {', '.join(sorted(missing))}")
        if fact["strength"] not in VALID_STRENGTHS:
            raise ValueError(f"fact {index} has invalid strength")
        if not 0 <= float(fact["confidence"]) <= 1:
            raise ValueError(f"fact {index} confidence must be between 0 and 1")
        if urlsplit(str(fact["url"])).scheme not in {"http", "https"}:
            raise ValueError(f"fact {index} requires a public HTTP(S) evidence URL")
        if not str(fact["excerpt"]).strip():
            raise ValueError(f"fact {index} requires a supporting excerpt")
        try:
            datetime.fromisoformat(str(fact["observed_at"]).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"fact {index} has invalid observed_at") from exc


def _validate_fit_config(config: dict[str, Any]) -> None:
    factors = config.get("fit_factors", [])
    if not factors or sum(float(factor["maximum_points"]) for factor in factors) != 100:
        raise ValueError("fit factor maximum_points must sum to 100")
    for factor in factors:
        maximum = float(factor["maximum_points"])
        if factor["kind"] == "counted_list" and any(float(tier["points"]) > maximum for tier in factor["tiers"]):
            raise ValueError(f"fit factor {factor['id']} tier exceeds maximum_points")
        if factor["kind"] == "categorical" and any(float(points) > maximum for points in factor["points"].values()):
            raise ValueError(f"fit factor {factor['id']} value exceeds maximum_points")


def _supporting_facts(facts: list[dict[str, Any]], fact_type: str) -> list[dict[str, Any]]:
    return [
        fact for fact in facts
        if fact["fact_type"] == fact_type and fact["strength"] not in {"unknown", "contradicted"}
    ]


def _factor_score(
    factor: dict[str, Any], facts: list[dict[str, Any]], strength_credit: dict[str, float]
) -> dict[str, Any]:
    support = _supporting_facts(facts, factor["fact_type"])
    base = {
        "id": factor["id"],
        "fact_type": factor["fact_type"],
        "maximum_points": factor["maximum_points"],
        "evidence": support,
    }
    if not support:
        return {**base, "state": "unknown", "observed": None, "points": 0.0, "reason": "no usable supporting fact"}

    strongest = max(support, key=lambda fact: (strength_credit[fact["strength"]], float(fact["confidence"])))
    credit = float(strength_credit[strongest["strength"]])
    kind = factor["kind"]
    if kind == "boolean":
        if any(not isinstance(fact["value"], bool) for fact in support):
            raise ValueError(f"{factor['fact_type']} requires boolean values")
        values = {bool(fact["value"]) for fact in support if isinstance(fact["value"], bool)}
        if len(values) != 1:
            return {**base, "state": "unknown", "observed": "conflict", "points": 0.0, "reason": "conflicting boolean evidence"}
        observed = values.pop()
        raw_points = float(factor["maximum_points"]) if observed else 0.0
    elif kind == "counted_list":
        if any(not isinstance(fact["value"], list) for fact in support):
            raise ValueError(f"{factor['fact_type']} requires list values")
        observed_values = sorted({str(value) for fact in support for value in fact["value"]})
        observed = observed_values
        raw_points = _tier_points(float(len(observed_values)), factor["tiers"])
    elif kind == "categorical":
        if any(not isinstance(fact["value"], str) for fact in support):
            raise ValueError(f"{factor['fact_type']} requires string values")
        values = {str(fact["value"]) for fact in support}
        if len(values) != 1:
            return {**base, "state": "unknown", "observed": "conflict", "points": 0.0, "reason": "conflicting categorical evidence"}
        observed = values.pop()
        if observed not in factor["points"]:
            raise ValueError(f"unsupported {factor['fact_type']} value: {observed}")
        raw_points = float(factor["points"][observed])
    else:
        raise ValueError(f"unsupported fit factor kind: {kind}")

    points = round(raw_points * credit, 1)
    return {
        **base,
        "state": strongest["strength"],
        "observed": observed,
        "points": points,
        "unadjusted_points": raw_points,
        "strength_credit": credit,
        "reason": f"scored from {len(support)} evidence item(s); strongest strength is {strongest['strength']}",
    }


def score_account_fit(profile: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    _validate_profile(profile)
    _validate_fit_config(config)
    facts = profile["facts"]
    strength_credit = config["fit_interpretation"]["strength_credit"]
    factors = [_factor_score(factor, facts, strength_credit) for factor in config["fit_factors"]]
    known_factors = [factor for factor in factors if factor["state"] != "unknown"]
    score = round(sum(float(factor["points"]) for factor in factors), 1)
    confidence = round(
        sum(float(fact["confidence"]) for fact in facts if fact["strength"] not in {"unknown", "contradicted"})
        / max(1, sum(fact["strength"] not in {"unknown", "contradicted"} for fact in facts))
        * (len(known_factors) / len(factors)),
        3,
    )
    thresholds = config["fit_interpretation"]
    pass_fit = (
        score >= float(thresholds["minimum_fit"])
        and confidence >= float(thresholds["minimum_confidence"])
        and len(facts) >= int(thresholds["minimum_evidence_items"])
        and len(known_factors) == len(factors)
    )
    risks = list(profile.get("risks", []))
    if len(known_factors) < len(factors):
        risks.append("one or more fit factors remain unknown or conflicting")
    return {
        "score": score,
        "state": "observed" if known_factors else "unknown",
        "confidence": confidence,
        "factors": factors,
        "reasons": [f"{len(known_factors)} of {len(factors)} fit factors have usable evidence"],
        "risks": risks,
        "status": "provisional_pass" if pass_fit else "review",
    }


def score_account_fit_run(
    run_dir: Path, profile_path: Path, config_path: Path | None = None
) -> dict[str, Any]:
    pages, pages_bytes, manifest = _load_scrapling_run(run_dir)
    profile_bytes = profile_path.read_bytes()
    profile = json.loads(profile_bytes)
    _validate_scrapling_facts(profile, pages, manifest)
    config, config_bytes, selected_config = load_scoring_config(config_path)
    component = score_account_fit(profile, config)
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
        "input": {
            "profile_file": str(profile_path),
            "profile_sha256": _sha256(profile_bytes),
            "pages_file": "normalized/pages.jsonl",
            "pages_sha256": _sha256(pages_bytes),
            "config_file": str(selected_config),
            "config_sha256": _sha256(config_bytes),
        },
        "component": component,
    }
    output_path = run_dir / "normalized" / "account_fit.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result
