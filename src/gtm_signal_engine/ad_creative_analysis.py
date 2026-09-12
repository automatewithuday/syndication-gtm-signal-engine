from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "ad_creative_analysis.v1.json"


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _default_config() -> Path:
    candidates = (
        Path.cwd() / "config" / "ad_creative_analysis.v1.json",
        DEFAULT_CONFIG_PATH,
        Path(sys.prefix) / "share" / "gtm-signal-engine" / "ad_creative_analysis.v1.json",
    )
    return next((candidate for candidate in candidates if candidate.exists()), candidates[0])


def _provider_payload(envelope: dict[str, Any]) -> dict[str, Any] | None:
    response = envelope.get("toolResponse", {})
    if not isinstance(response, dict):
        return None
    for key in ("rawV2", "raw"):
        candidate = response.get(key)
        if isinstance(candidate, dict):
            return candidate
    return None


def _records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    value = payload.get("ads", payload.get("results", []))
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _record_id(record: dict[str, Any]) -> str:
    return str(
        record.get("ad_id")
        or record.get("creative_id")
        or record.get("adArchiveID")
        or record.get("ad_archive_id")
        or ""
    )


def _text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(re.sub(r"<[^>]+>", " ", value).split()).strip()


def _object_text(value: Any, *keys: str) -> str:
    if isinstance(value, str):
        return _text(value)
    if not isinstance(value, dict):
        return ""
    return " — ".join(filter(None, (_text(value.get(key)) for key in keys)))


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _format_family(value: str) -> str:
    normalized = value.casefold()
    for family in ("video", "carousel", "document", "image", "text", "audio"):
        if family in normalized:
            return family
    if "status_update" in normalized or "native" in normalized:
        return "native"
    return normalized


def _raw_fields(platform: str, record: dict[str, Any]) -> dict[str, Any]:
    advertiser = record.get("advertiser") if isinstance(record.get("advertiser"), dict) else {}
    headline = record.get("headline") if isinstance(record.get("headline"), dict) else {}
    commentary = record.get("commentary") if isinstance(record.get("commentary"), dict) else {}
    snapshot = record.get("snapshot") if isinstance(record.get("snapshot"), dict) else {}
    body = snapshot.get("body") if isinstance(snapshot.get("body"), dict) else {}
    variants = record.get("variants") if isinstance(record.get("variants"), list) else []
    variant_texts = [_text(item.get("content")) for item in variants if isinstance(item, dict)]

    if platform == "linkedin":
        headline_text = _object_text(headline, "title", "description")
        body_text = _object_text(commentary, "text")
        cta_text = _object_text(record.get("cta"), "text", "title", "name")
        formats = [_text(record.get("type")), _text(record.get("creative_type"))]
        image = record.get("image") if isinstance(record.get("image"), dict) else {}
        media_urls = [_text(image.get("url"))]
        if record.get("carousel"):
            formats.append("carousel")
    elif platform == "meta":
        headline_text = " — ".join(filter(None, [
            _text(snapshot.get("title")), _text(snapshot.get("link_description"))
        ]))
        body_text = _object_text(body, "text")
        cta_text = " — ".join(filter(None, [
            _text(snapshot.get("cta_text")), _text(snapshot.get("cta_type"))
        ]))
        formats = [_text(snapshot.get("display_format"))]
        media_urls = []
        for key in ("images", "videos", "extra_images", "extra_videos"):
            for item in snapshot.get(key, []) if isinstance(snapshot.get(key), list) else []:
                if isinstance(item, dict):
                    media_urls.extend(_text(item.get(url_key)) for url_key in (
                        "url", "resized_image_url", "video_preview_image_url", "video_hd_url", "video_sd_url"
                    ))
    else:
        headline_text = ""
        body_text = " — ".join(filter(None, variant_texts))
        cta_text = ""
        formats = [_text(record.get("format"))]
        media_urls = []

    return {
        "advertiser_name": _text(
            advertiser.get("name") or record.get("advertiser_name")
            or record.get("page_name") or snapshot.get("page_name")
        ),
        "headline": headline_text,
        "body": body_text,
        "cta": cta_text,
        "creative_formats": _dedupe([_format_family(value) for value in formats if value]),
        "provider_creative_types": _dedupe([value.lower() for value in formats]),
        "distribution_platforms": _dedupe([
            _text(item).lower() for item in record.get("publisher_platform", [])
        ]),
        "media_urls": _dedupe(media_urls),
        "provider_active_state": record.get("is_active") if isinstance(record.get("is_active"), bool) else None,
    }


def _text_quality(text: str, config: dict[str, Any]) -> str:
    normalized = text.strip().casefold()
    markers = [str(value).casefold() for value in config["text_quality"]["redacted_markers"]]
    if not normalized:
        return "missing"
    if any(marker in normalized for marker in markers):
        return "redacted"
    if len(normalized) < int(config["text_quality"]["minimum_usable_characters"]):
        return "minimal"
    return "usable"


def _matched_labels(text: str, rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for rule in rules:
        terms = [pattern for pattern in rule["patterns"] if re.search(pattern, text, re.IGNORECASE)]
        if terms:
            matches.append({"label": rule["label"], "matched_patterns": terms})
    return matches


def classify_creative(text: str, config: dict[str, Any]) -> dict[str, Any]:
    quality = _text_quality(text, config)
    if quality != "usable":
        return {
            "text_quality": quality,
            "funnel_stage": {"label": "unknown", "confidence": 0.0, "matched_patterns": []},
            "offer_types": [], "audiences": [], "messaging_themes": [],
        }
    funnel_matches = _matched_labels(text, config["funnel_stages"])
    funnel = funnel_matches[0] if funnel_matches else {"label": "awareness", "matched_patterns": []}
    funnel["confidence"] = 0.85 if funnel_matches else 0.55
    return {
        "text_quality": quality,
        "funnel_stage": funnel,
        "offer_types": _matched_labels(text, config["offer_types"]),
        "audiences": _matched_labels(text, config["audiences"]),
        "messaging_themes": _matched_labels(text, config["messaging_themes"]),
    }


def _datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    candidate = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(candidate[:10])
        except ValueError:
            return None
    return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc)


def _creative_activity_state(
    provider_active_state: bool | None,
    first_seen_at: Any,
    last_seen_at: Any,
    observed_at: Any,
) -> dict[str, Any]:
    if provider_active_state is True:
        return {"state": "active", "confidence": 0.95, "basis": "provider_active_state"}
    if provider_active_state is False:
        return {"state": "inactive", "confidence": 0.95, "basis": "provider_active_state"}
    observed = _datetime(observed_at)
    last_seen = _datetime(last_seen_at)
    first_seen = _datetime(first_seen_at)
    if observed and last_seen:
        age_days = max(0, (observed - last_seen).days)
        return {
            "state": "recently_observed" if age_days <= 30 else "historical",
            "confidence": 0.8,
            "basis": "last_seen_at",
            "age_days_at_observation": age_days,
        }
    if observed and first_seen and first_seen > observed - timedelta(days=30):
        return {
            "state": "recently_observed", "confidence": 0.65,
            "basis": "first_seen_at_without_end_state",
        }
    return {"state": "unknown", "confidence": 0.0, "basis": "missing_activity_dates"}


def _frequency(records: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for record in records:
        value = record["classification"][field]
        labels = [value["label"]] if isinstance(value, dict) else [item["label"] for item in value]
        counts.update(label for label in labels if label != "unknown")
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _inventory_level(total: int | None, status: str, config: dict[str, Any]) -> str:
    if total is None or status in {"inconclusive", "failed"}:
        return "unknown"
    for tier in config["inventory_tiers"]:
        if total >= int(tier["minimum_total_ads"]):
            return str(tier["label"])
    return "unknown"


def _sample_confidence(inspected: int, total: int | None, incomplete: bool, config: dict[str, Any]) -> str:
    if inspected == 0:
        return "none"
    if not incomplete or total is not None and total > 0 and inspected / total >= float(
        config["sample_confidence"]["high_minimum_ratio"]
    ) or inspected >= int(config["sample_confidence"]["high_minimum_inspected"]):
        return "high"
    if inspected >= int(config["sample_confidence"]["medium_minimum_inspected"]):
        return "medium"
    return "low"


def _aggregate_platform(
    platform: str, records: list[dict[str, Any]], status: dict[str, Any], config: dict[str, Any]
) -> dict[str, Any]:
    total = status.get("provider_total_records")
    total = int(total) if isinstance(total, int) else None
    inspected = len(records)
    analyzable = sum(record["classification"]["text_quality"] == "usable" for record in records)
    texts = [record["creative_text"].casefold().strip() for record in records
             if record["classification"]["text_quality"] == "usable"]
    formats = sorted({value for record in records for value in record["creative_formats"]})
    coverage = round(inspected / total, 4) if total else (1.0 if total == 0 else None)
    result = {
        "provider_status": status.get("status", "unknown"),
        "provider_total_ads": total,
        "returned_ads": status.get("returned_records"),
        "ads_inspected": inspected,
        "sample_coverage_ratio": coverage,
        "sample_coverage_percent": round(coverage * 100, 2) if coverage is not None else None,
        "sample_confidence": _sample_confidence(inspected, total, bool(status.get("incomplete", True)), config),
        "inventory_level": _inventory_level(total, str(status.get("status", "unknown")), config),
        "analyzable_ads": analyzable,
        "text_analysis_coverage_ratio": round(analyzable / inspected, 4) if inspected else None,
        "creative_diversity": {
            "unique_usable_texts": len(set(texts)),
            "duplicate_exact_text_records": max(0, len(texts) - len(set(texts))),
            "exact_text_diversity_ratio": round(len(set(texts)) / len(texts), 4) if texts else None,
            "formats": formats,
            "format_count": len(formats),
        },
        "funnel_stages": _frequency(records, "funnel_stage"),
        "offer_types": _frequency(records, "offer_types"),
        "audiences": _frequency(records, "audiences"),
        "messaging_themes": _frequency(records, "messaging_themes"),
        "creative_activity_states": dict(sorted(Counter(
            record["creative_activity"]["state"] for record in records
        ).items())),
    }
    return result


def analyze_ad_creatives(run_dir: Path, config_path: Path | None = None) -> dict[str, Any]:
    normalized_dir = run_dir / "normalized"
    profile_path = normalized_dir / "external_profile.json"
    status_path = normalized_dir / "adyntel_collection.json"
    if not profile_path.is_file() or not status_path.is_file():
        raise FileNotFoundError("external_profile.json and adyntel_collection.json are required")
    selected_config = config_path or _default_config()
    profile_bytes = profile_path.read_bytes()
    status_bytes = status_path.read_bytes()
    config_bytes = selected_config.read_bytes()
    profile = json.loads(profile_bytes)
    collection = json.loads(status_bytes)
    config = json.loads(config_bytes)

    raw_by_platform: dict[str, dict[str, dict[str, Any]]] = {}
    raw_inputs: list[dict[str, str]] = []
    for platform, platform_status in collection.get("platforms", {}).items():
        relative = platform_status.get("raw", {}).get("response")
        if not relative:
            continue
        raw_path = (run_dir / relative).resolve()
        try:
            raw_path.relative_to(run_dir.resolve())
        except ValueError as exc:
            raise ValueError("Adyntel raw response path escapes the account run") from exc
        raw_bytes = raw_path.read_bytes()
        expected = platform_status.get("sha256", {}).get("response")
        actual = _sha256(raw_bytes)
        if expected and expected != actual:
            raise ValueError(f"Adyntel {platform} raw response hash does not match collection status")
        envelope = json.loads(raw_bytes)
        payload = _provider_payload(envelope) if isinstance(envelope, dict) else None
        raw_by_platform[platform] = {
            _record_id(record): record for record in _records(payload or {}) if _record_id(record)
        }
        raw_inputs.append({"platform": platform, "file": str(Path(relative)), "sha256": actual})

    creatives: list[dict[str, Any]] = []
    for ad in profile.get("ads", []):
        platform = str(ad.get("platform", "")).lower()
        record_id = str(ad.get("provider_record_id", ""))
        if not platform or not record_id or not str(ad.get("method", "")).startswith("deepline_adyntel_"):
            continue
        raw_record = raw_by_platform.get(platform, {}).get(record_id)
        details = _raw_fields(platform, raw_record or {})
        creative_text = _text(ad.get("creative_text"))
        semantic_text = " — ".join(filter(None, [details["body"], details["headline"], details["cta"]]))
        analyzed_text = semantic_text if raw_record is not None else creative_text
        destination = ad.get("destination") if isinstance(ad.get("destination"), dict) else None
        creatives.append({
            "platform": platform,
            "provider_record_id": record_id,
            "advertiser_name": details["advertiser_name"],
            "creative_text": creative_text,
            "headline": details["headline"],
            "body": details["body"],
            "cta": details["cta"],
            "creative_formats": details["creative_formats"],
            "provider_creative_types": details["provider_creative_types"],
            "distribution_platforms": details["distribution_platforms"],
            "media_urls": details["media_urls"],
            "destination_url": destination.get("observed_url") if destination else None,
            "source_url": ad.get("source_url"),
            "first_seen_at": ad.get("first_seen_at"),
            "last_seen_at": ad.get("last_seen_at"),
            "provider_active_state": details["provider_active_state"],
            "creative_activity": _creative_activity_state(
                details["provider_active_state"], ad.get("first_seen_at"),
                ad.get("last_seen_at"), ad.get("observed_at"),
            ),
            "observed_at": ad.get("observed_at"),
            "confidence": ad.get("confidence"),
            "method": ad.get("method"),
            "normalizer_version": ad.get("normalizer_version"),
            "creative_fingerprint": _sha256(creative_text.casefold().encode()),
            "analyzed_text": analyzed_text,
            "classification": classify_creative(analyzed_text, config),
            "visual_analysis": {"status": "not_performed", "reason": "v1 analyzes text and metadata only"},
        })

    platforms: dict[str, Any] = {}
    all_platforms = sorted(set(collection.get("platforms", {})) | {item["platform"] for item in creatives})
    for platform in all_platforms:
        platform_records = [item for item in creatives if item["platform"] == platform]
        platforms[platform] = _aggregate_platform(
            platform, platform_records, collection.get("platforms", {}).get(platform, {}), config
        )

    observed_platforms = [
        platform for platform, summary in platforms.items()
        if summary["provider_total_ads"] is not None and summary["provider_total_ads"] > 0
        and summary["provider_status"] not in {"failed", "inconclusive"}
    ]
    output = {
        "schema_version": "1.0",
        "analysis_version": config["version"],
        "analysis_scope": config["analysis_scope"],
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "domain": collection.get("domain") or profile.get("domain"),
        "input": {
            "external_profile_file": str(profile_path),
            "external_profile_sha256": _sha256(profile_bytes),
            "adyntel_collection_file": str(status_path),
            "adyntel_collection_sha256": _sha256(status_bytes),
            "config_file": str(selected_config),
            "config_sha256": _sha256(config_bytes),
            "raw_responses": raw_inputs,
        },
        "platforms": platforms,
        "scoring_inputs": {
            "observed_ad_platforms": observed_platforms,
            "observed_platform_diversity": len(observed_platforms),
            "provider_total_ads": sum(
                summary["provider_total_ads"] for summary in platforms.values()
                if summary["provider_total_ads"] is not None
                and summary["provider_status"] not in {"failed", "inconclusive"}
            ),
            "ads_inspected": len(creatives),
            "analyzable_ads": sum(
                item["classification"]["text_quality"] == "usable" for item in creatives
            ),
            "creative_format_diversity": len({
                value for item in creatives for value in item["creative_formats"]
            }),
            "messaging_theme_diversity": len({
                match["label"] for item in creatives
                for match in item["classification"]["messaging_themes"]
            }),
        },
        "limitations": [
            "Provider totals measure inventory; creative classifications cover only returned ads.",
            "Partial first pages are samples and may not represent the full creative mix.",
            "Missing or redacted text is unknown and does not count against the account.",
            "Image and video contents are not analyzed in v1.",
            "Missing destination URLs prevent landing-page and tracking analysis for those ads.",
        ],
        "creatives": creatives,
    }
    snapshot_payload = {
        "profile": output["input"]["external_profile_sha256"],
        "collection": output["input"]["adyntel_collection_sha256"],
        "config": output["input"]["config_sha256"],
        "raw": raw_inputs,
        "version": config["version"],
    }
    output["snapshot_id"] = _sha256(json.dumps(snapshot_payload, sort_keys=True).encode())
    output_path = normalized_dir / "ad_creative_analysis.json"
    output_path.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output
