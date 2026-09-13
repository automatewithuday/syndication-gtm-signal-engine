from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .collector import ScraplingFetcher, canonicalize_url
from .gap_discovery import _target_identity, collect_gap_targets, gap_target_priority
from .gap_workflow import resolve_channel_gaps
from .providers import WebsiteFetcher
from .review_queue import DEFAULT_DATABASE_PATH

PLANNER_VERSION = "gap_target_planner_v1"
ACQUISITION_VERSION = "gap_evidence_acquisition_v2"
CONTEXT_TERMS = (
    "syndicat", "content distribution", "retarget", "remarket", "programmatic",
    "display advertising", "demand generation", "paid media", "growth marketing",
    "campaign", "partner", "hiring", "expansion", "bottleneck", "pipeline",
)
CHANNEL_TARGET_TERMS = (
    "syndicat", "content-distribution", "content_distribution", "demand-generation",
    "demand_generation", "retarget", "remarket", "programmatic", "advertis",
    "paid-media", "paid_media", "media-buying", "media_buying", "campaign",
)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load_jsonl(path: Path) -> tuple[list[dict[str, Any]], bytes]:
    raw = path.read_bytes()
    return [json.loads(line) for line in raw.splitlines() if line.strip()], raw


def _category(url: str) -> str:
    path = urlsplit(url).path.casefold()
    if "syndicat" in path:
        return "syndication"
    for category, terms in (
        ("careers", ("/career", "/job", "/opening")),
        ("partners", ("/partner", "/partnership")),
        ("campaigns", ("/campaign", "/marketing", "/growth", "/demand-generation")),
        ("press", ("/press", "/news", "/newsroom")),
    ):
        if any(term in path for term in terms):
            return category
    return "campaign_destination"


def build_gap_target_plan(
    run_dir: Path,
    *,
    maximum_targets: int = 25,
    search_result_paths: list[Path] | None = None,
    retry_failed: bool = False,
) -> dict[str, Any]:
    if maximum_targets < 1:
        raise ValueError("maximum_targets must be at least 1")
    manifest_path = run_dir / "manifest.json"
    discovered_path = run_dir / "normalized" / "discovered_urls.jsonl"
    pages_path = run_dir / "normalized" / "pages.jsonl"
    if not manifest_path.is_file() or not discovered_path.is_file() or not pages_path.is_file():
        raise FileNotFoundError("gap target planning requires manifest, pages, and discovered URLs")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("provider") != "ScraplingFetcher":
        raise ValueError("gap target planning requires a ScraplingFetcher run")
    domain = (urlsplit(str(manifest.get("seed_url", ""))).hostname or "").lower().removeprefix("www.")
    allowed_hosts = {domain, f"www.{domain}"}
    discovered, _ = _load_jsonl(discovered_path)
    pages, _ = _load_jsonl(pages_path)
    existing = {_target_identity(str(item["url"])) for item in pages}
    previous_attempts: Counter[str] = Counter()
    last_errors: dict[str, str] = {}
    for collection in manifest.get("targeted_collections", []):
        if collection.get("kind") != "channel_gap":
            continue
        for url in collection.get("targets_selected", []):
            previous_attempts[_target_identity(canonicalize_url(str(url)))] += 1
        for error in collection.get("errors", []):
            url = str(error.get("url", ""))
            if url:
                last_errors[_target_identity(canonicalize_url(url))] = str(error.get("error", ""))
    candidates: dict[str, dict[str, Any]] = {}
    sources: dict[str, set[str]] = defaultdict(set)
    reasons: dict[str, set[str]] = defaultdict(set)
    manifest_fingerprint = {
        "run_id": manifest.get("run_id"),
        "seed_url": manifest.get("seed_url"),
        "provider": manifest.get("provider"),
        "targeted_collections": [
            {
                "kind": collection.get("kind"),
                "targets_selected": collection.get("targets_selected", []),
                "pages_fetched": collection.get("pages_fetched", []),
                "errors": [
                    {
                        "url": error.get("url"),
                        "purpose": error.get("purpose"),
                        "error": error.get("error"),
                    }
                    for error in collection.get("errors", [])
                ],
            }
            for collection in manifest.get("targeted_collections", [])
            if collection.get("kind") == "channel_gap"
        ],
    }
    input_hashes = {
        "manifest.logical_state": _sha256(json.dumps(
            manifest_fingerprint, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")),
        "normalized/discovered_urls.identity_set": _sha256(json.dumps(
            sorted({_target_identity(canonicalize_url(str(item["url"]))) for item in discovered}),
            separators=(",", ":"),
        ).encode("utf-8")),
        "normalized/pages.identity_set": _sha256(json.dumps(
            sorted(existing), separators=(",", ":")
        ).encode("utf-8")),
    }

    def add(url: str, *, source: str, priority: int, reason: str) -> None:
        normalized = canonicalize_url(url)
        if not normalized or (urlsplit(normalized).hostname or "").lower() not in allowed_hosts:
            return
        identity = _target_identity(normalized)
        current = candidates.get(identity)
        if current is None or priority < current["priority"]:
            candidates[identity] = {
                "url": normalized, "priority": priority,
                "category": _category(normalized),
                "already_fetched": identity in existing,
            }
        sources[identity].add(source)
        reasons[identity].add(reason)

    for item in discovered:
        url = str(item.get("url", ""))
        priority = gap_target_priority(url)
        if priority < 100:
            category = _category(url)
            path = urlsplit(url).path.casefold()
            if category == "press" and not any(term in path for term in CHANNEL_TARGET_TERMS):
                continue
            if category == "partners" and not (
                "partner-program" in path
                or any(term in path for term in CHANNEL_TARGET_TERMS)
            ):
                continue
            add(
                url, source="discovered_url_inventory", priority=priority,
                reason="same-domain structural path is relevant to gap or trigger evidence",
            )

    external_path = run_dir / "normalized" / "external_profile.json"
    if external_path.is_file():
        external = json.loads(external_path.read_text(encoding="utf-8"))
        ad_destinations: set[str] = set()
        for ad in external.get("ads", []):
            destination = ad.get("destination")
            if isinstance(destination, dict):
                url = destination.get("canonical_url") or destination.get("observed_url")
                if url:
                    ad_destinations.add(canonicalize_url(str(url)))
                    add(
                        str(url), source="attributable_ad_destination", priority=6,
                        reason="saved attributable ad points to this same-domain landing page",
                    )
        input_hashes["normalized/external_profile.ad_destinations"] = _sha256(json.dumps(
            sorted(ad_destinations), separators=(",", ":")
        ).encode("utf-8"))

    default_search_paths = [
        run_dir / "normalized" / "serp_results.jsonl",
        run_dir / "normalized" / "search_results.jsonl",
    ]
    selected_search_paths = list(dict.fromkeys([
        *default_search_paths, *(search_result_paths or []),
    ]))
    for path in selected_search_paths:
        if not path.is_file():
            continue
        rows, raw = _load_jsonl(path)
        try:
            label = str(path.relative_to(run_dir))
        except ValueError:
            label = str(path)
        input_hashes[label] = _sha256(raw)
        for index, item in enumerate(rows):
            if item.get("method") != "scrapling_saved_serp":
                raise ValueError(f"saved search result {index} in {path} lacks Scrapling provenance")
            query = str(item.get("query", "")).casefold()
            context = " ".join(str(item.get(key, "")) for key in ("title", "excerpt")).casefold()
            query_relevant = any(term.replace("-", " ").replace("_", " ") in query for term in CHANNEL_TARGET_TERMS)
            if not query_relevant or not any(term in f"{query} {context}" for term in CONTEXT_TERMS):
                continue
            url = item.get("canonical_url") or item.get("result_url")
            if url:
                add(
                    str(url), source=f"saved_scrapling_serp:{label}", priority=7,
                    reason="saved targeted Scrapling search result contains gap-relevant context",
                )

    ordered = sorted(
        candidates.items(), key=lambda pair: (
            pair[1]["already_fetched"], pair[1]["priority"], pair[1]["url"]
        )
    )
    remaining = maximum_targets
    targets = []
    for identity, item in ordered:
        attempts = int(previous_attempts[identity])
        selected = (
            not item["already_fetched"]
            and (retry_failed or attempts == 0)
            and remaining > 0
        )
        remaining -= int(selected)
        targets.append({
            **item, "selected": selected,
            "previous_attempts": attempts,
            "last_error": last_errors.get(identity),
            "sources": sorted(sources[identity]),
            "reasons": sorted(reasons[identity]),
        })
    snapshot_material = json.dumps({
        "planner_version": PLANNER_VERSION,
        "run_id": manifest.get("run_id"),
        "account_domain": domain,
        "maximum_targets": maximum_targets,
        "retry_failed": retry_failed,
        "input_sha256": input_hashes,
        "targets": targets,
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")
    result = {
        "schema_version": "1.0", "planner_version": PLANNER_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "snapshot_id": _sha256(snapshot_material),
        "run_id": manifest.get("run_id"), "account_domain": domain,
        "maximum_targets": maximum_targets, "input_sha256": input_hashes,
        "retry_failed": retry_failed,
        "target_count": len(targets),
        "selected_count": sum(item["selected"] for item in targets),
        "skipped_previously_attempted": sum(
            bool(item["previous_attempts"] and not item["already_fetched"] and not retry_failed)
            for item in targets
        ),
        "targets": targets,
        "interpretation": (
            "The plan is a bounded positive-evidence search. Unselected, unavailable, or failed "
            "targets do not prove that a channel is unused."
        ),
    }
    output_path = run_dir / "normalized" / "gap_target_plan.json"
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def acquire_gap_evidence(
    run_dir: Path,
    *,
    account_name: str | None = None,
    database_path: Path = DEFAULT_DATABASE_PATH,
    maximum_targets: int = 25,
    maximum_pages: int = 10,
    maximum_depth: int = 2,
    delay_seconds: float = 0.25,
    search_result_paths: list[Path] | None = None,
    retry_failed: bool = False,
    fetcher: WebsiteFetcher | None = None,
    resolve_after_collection: bool = True,
) -> dict[str, Any]:
    plan = build_gap_target_plan(
        run_dir, maximum_targets=maximum_targets,
        search_result_paths=search_result_paths, retry_failed=retry_failed,
    )
    selected = [item["url"] for item in plan["targets"] if item["selected"]]
    collection: dict[str, Any] | None = None
    if selected:
        plan_path = run_dir / "normalized" / "gap_target_plan.json"
        collection = collect_gap_targets(
            run_dir, maximum_pages=min(maximum_pages, len(selected)),
            maximum_depth=maximum_depth, delay_seconds=delay_seconds,
            include_urls=selected, target_plan_path=plan_path,
            fetcher=fetcher or ScraplingFetcher(),
        )
    resolution = (
        resolve_channel_gaps(
            run_dir, account_name=account_name, database_path=database_path
        )
        if resolve_after_collection else None
    )
    result = {
        "schema_version": "1.0", "acquisition_version": ACQUISITION_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": plan["run_id"], "account_domain": plan["account_domain"],
        "resolution_deferred": not resolve_after_collection,
        "status": (
            "no_targets" if not selected else
            "partial" if collection and collection.get("errors") else "completed"
        ),
        "plan": {
            "snapshot_id": plan["snapshot_id"], "target_count": plan["target_count"],
            "selected_count": plan["selected_count"],
            "skipped_previously_attempted": plan["skipped_previously_attempted"],
        },
        "collection": collection,
        "resolution": None if resolution is None else {
            "status": resolution["status"],
            "review_counts": resolution["review_counts"],
            "channels": resolution["channels"],
        },
        "interpretation": plan["interpretation"],
    }
    output_path = run_dir / "normalized" / "gap_evidence_acquisition.json"
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result["output"] = str(output_path)
    return result
