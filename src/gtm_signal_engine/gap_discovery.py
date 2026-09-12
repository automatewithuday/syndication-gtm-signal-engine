from __future__ import annotations

import hashlib
import heapq
import json
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from .collector import LocalArtifactStore, ScraplingFetcher, canonicalize_url, normalize_html
from .models import Page
from .providers import WebsiteFetcher

EXTRACTOR_VERSION = "gap_candidate_rules_v1"
INITIATIVE_EXTRACTOR_VERSION = "initiative_candidate_rules_v3"
RULES = (
    (
        "explicit_expansion_intent",
        "supports_gap",
        re.compile(r"\bwe\s+(?:are\s+|plan to\s+|want to\s+|need to\s+)?(?:expand|scale|grow|increase)\w*\b.{0,80}\b(?:content distribution|content syndication|demand generation|audience reach)\b", re.I | re.S),
    ),
    (
        "documented_distribution_bottleneck",
        "supports_gap",
        re.compile(r"\b(?:manual|struggl\w*|challenge\w*|bottleneck\w*|limited|gap)\b.{0,120}\b(?:content distribution|content syndication|demand generation|audience reach)\b", re.I | re.S),
    ),
    (
        "active_partner_or_hiring_search",
        "supports_gap",
        re.compile(r"\b(?:hiring|seeking|looking for|join our team)\b.{0,140}\b(?:demand generation|content marketing|growth marketing|content distribution)\b", re.I | re.S),
    ),
    (
        "documented_performance_shortfall",
        "supports_gap",
        re.compile(r"\b(?:low conversions?|declining pipeline|underperforming campaigns?|poor roi|missed pipeline|limited reach)\b", re.I),
    ),
    (
        "documented_syndication_success",
        "contradicts_gap",
        re.compile(r"\bcontent syndication\b.{0,140}\b(?:generated|drove|delivered|pipeline|revenue|qualified leads?)\b", re.I | re.S),
    ),
    (
        "documented_healthy_syndication_program",
        "contradicts_gap",
        re.compile(r"\b(?:our|active|ongoing)\b.{0,80}\bcontent syndication (?:program|campaign|strategy)\b", re.I | re.S),
    ),
)
INITIATIVE_RULES = (
    (
        "public_campaign_launch",
        "direct",
        re.compile(r"\b(?:launch(?:ed|es|ing)?)\b.{0,120}\b(?:campaign|initiative)\b", re.I | re.S),
    ),
    (
        "new_channel_or_team_launch",
        "adjacent",
        re.compile(r"\b(?:launching|building)\b.{0,120}\b(?:new (?:growth engine|division|team|agency)|from the ground up)\b", re.I | re.S),
    ),
    (
        "active_marketing_hiring",
        "adjacent",
        re.compile(r"\b(?:hiring|looking for|seeking)\b.{0,100}\b(?:content marketing|brand marketing|marketing operations)\b", re.I | re.S),
    ),
    (
        "active_demand_generation_hiring",
        "adjacent",
        re.compile(
            r"\b(?:hiring|looking for|seeking|join our team)\b.{0,140}\b"
            r"(?:demand gen(?:eration)?|paid (?:media|acquisition|social)|performance marketing|"
            r"growth marketing|acquisition marketing|ads? manager)\b",
            re.I | re.S,
        ),
    ),
    (
        "funding_round_announced",
        "direct",
        re.compile(
            r"\b(?:we|our company|the company)\s+(?:has\s+)?(?:raised|secured|closed|announced)\b"
            r".{0,100}\b(?:\$[\d,.]+\s*(?:million|billion|m|b)?|seed|series\s+[a-z]|"
            r"funding|financing|investment round)\b",
            re.I | re.S,
        ),
    ),
)


def gap_target_priority(url: str) -> int:
    path = urlsplit(url).path.casefold().strip("/")
    segment_list = [segment for segment in path.split("/") if segment]
    segments = set(segment_list)
    if segments.intersection({"tool", "tools", "category", "categories", "tag", "tags"}):
        return 100
    if "page" in segments and any(segment.isdigit() for segment in segments):
        return 100
    if "syndicat" in path:
        return 0
    if "job-offer" in segments:
        return 3
    if segments.intersection({"career", "careers", "job", "jobs", "openings", "openings-job"}):
        return 5
    if segments.intersection({"partner", "partners", "partnerships", "partner-program"}):
        return 8
    if segments.intersection({
        "marketing", "content-marketing", "demand-generation", "growth-marketing",
        "campaign", "campaigns",
    }):
        return 10
    if segments.intersection({"press", "press-center", "news", "newsroom"}):
        if len(segment_list) < 3:
            return 15
        topical_slug_terms = (
            "launch", "campaign", "marketing", "partner", "growth", "open",
            "funding", "fundraise", "raised", "series", "financing", "investment",
        )
        return 12 if any(term in segment_list[-1] for term in topical_slug_terms) else 100
    return 100


def _target_identity(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path.rstrip('/') or '/'}"


def _load_pages(path: Path) -> tuple[list[Page], bytes]:
    value = path.read_bytes()
    return [Page(**json.loads(line)) for line in value.splitlines() if line.strip()], value


def collect_gap_targets(
    run_dir: Path,
    *,
    maximum_pages: int = 10,
    maximum_depth: int = 1,
    delay_seconds: float = 0.25,
    include_urls: list[str] | None = None,
    fetcher: WebsiteFetcher | None = None,
) -> dict[str, Any]:
    if maximum_pages < 1:
        raise ValueError("maximum_pages must be at least 1")
    if maximum_depth < 1:
        raise ValueError("maximum_depth must be at least 1")
    manifest_path = run_dir / "manifest.json"
    pages_path = run_dir / "normalized" / "pages.jsonl"
    discovered_path = run_dir / "normalized" / "discovered_urls.jsonl"
    if not manifest_path.exists() or not pages_path.exists() or not discovered_path.exists():
        raise FileNotFoundError("crawl manifest, pages, or discovered URL inventory missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("provider") != "ScraplingFetcher":
        raise ValueError("targeted gap collection requires a ScraplingFetcher run")
    seed_url = str(manifest["seed_url"])
    seed_host = (urlsplit(seed_url).hostname or "").lower()
    base_host = seed_host.removeprefix("www.")
    allowed_hosts = {base_host, f"www.{base_host}"}
    pages, _ = _load_pages(pages_path)
    existing_urls = {page.url for page in pages}
    discovered = [json.loads(line)["url"] for line in discovered_path.read_bytes().splitlines() if line.strip()]
    existing_target_ids = {_target_identity(url) for url in existing_urls}
    target_queue: list[tuple[int, int, str]] = []
    queued_target_ids: set[str] = set()

    def enqueue(url: str, depth: int, *, explicit: bool = False) -> None:
        normalized = canonicalize_url(url)
        if (urlsplit(normalized).hostname or "").lower() not in allowed_hosts:
            return
        identity = _target_identity(normalized)
        priority = gap_target_priority(normalized)
        if (priority >= 100 and not explicit) or identity in existing_target_ids or identity in queued_target_ids:
            return
        queued_target_ids.add(identity)
        heapq.heappush(target_queue, (-1 if explicit else priority, depth, normalized))

    discovered_identities = {_target_identity(canonicalize_url(url)) for url in discovered}
    for url in include_urls or []:
        normalized = canonicalize_url(url)
        if _target_identity(normalized) not in discovered_identities:
            raise ValueError(f"explicit target is not present in the saved discovery inventory: {url}")
        enqueue(normalized, 1, explicit=True)
    for url in discovered:
        enqueue(url, 1)
    fetcher = fetcher or ScraplingFetcher()
    store = LocalArtifactStore(run_dir.parent, run_dir.name)
    errors: list[dict[str, str]] = []
    fetched_pages: list[Page] = []
    requests_attempted = 0
    raw_responses = 0
    selected_targets: list[str] = []
    all_discovered = set(discovered)

    robots = RobotFileParser()
    robots_url = urljoin(seed_url, "/robots.txt")
    robots.set_url(robots_url)
    try:
        requests_attempted += 1
        robots_document = fetcher.fetch(robots_url)
        store.save_raw(robots_document)
        raw_responses += 1
        robots.parse(robots_document.body.decode("utf-8", errors="replace").splitlines())
        robots_available = robots_document.status_code < 400
    except Exception as exc:
        robots_available = False
        errors.append({"url": robots_url, "purpose": "robots", "error": f"{type(exc).__name__}: {exc}"})

    while target_queue and len(selected_targets) < maximum_pages:
        _, depth, target = heapq.heappop(target_queue)
        selected_targets.append(target)
        if robots_available and not robots.can_fetch("*", target):
            errors.append({"url": target, "purpose": "targeted_gap", "error": "robots.txt disallowed"})
            continue
        requests_attempted += 1
        try:
            document = fetcher.fetch(target)
            store.save_raw(document)
            raw_responses += 1
            final_host = (urlsplit(document.final_url).hostname or "").lower()
            if final_host not in allowed_hosts:
                raise ValueError(f"redirected outside allowed hosts to {document.final_url}")
            content_type = document.headers.get("content-type", "").lower()
            if "html" not in content_type and not document.body.lstrip().lower().startswith((b"<!doctype html", b"<html")):
                raise ValueError("target did not return HTML")
            page = normalize_html(document, datetime.now(timezone.utc).isoformat())
            fetched_pages.append(page)
            existing_target_ids.add(_target_identity(page.url))
            all_discovered.update(page.links)
            if depth < maximum_depth:
                for link in page.links:
                    enqueue(link, depth + 1)
        except Exception as exc:
            errors.append({"url": target, "purpose": "targeted_gap", "error": f"{type(exc).__name__}: {exc}"})
        if delay_seconds:
            time.sleep(delay_seconds)

    by_identity = {(page.url, page.content_hash): page for page in [*pages, *fetched_pages]}
    all_pages = list(by_identity.values())
    store.save_pages(all_pages)
    store.save_discovered_urls(all_discovered, seed_url)
    manifest["pages_collected"] = len(all_pages)
    manifest["requests_attempted"] = int(manifest.get("requests_attempted", 0)) + requests_attempted
    manifest["raw_responses"] = int(manifest.get("raw_responses", 0)) + raw_responses
    manifest["incomplete"] = True
    manifest["status"] = "partial" if all_pages else "failed"
    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    manifest.setdefault("errors", []).extend(errors)
    manifest.setdefault("targeted_collections", []).append({
        "kind": "channel_gap",
        "collector_version": "gap_targets_v1",
        "finished_at": manifest["finished_at"],
        "maximum_pages": maximum_pages,
        "maximum_depth": maximum_depth,
        "explicit_targets": [canonicalize_url(url) for url in include_urls or []],
        "targets_selected": selected_targets,
        "pages_fetched": [page.url for page in fetched_pages],
        "errors": errors,
    })
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest["targeted_collections"][-1]


def _excerpt(text: str, start: int, end: int, radius: int = 140) -> str:
    compact = " ".join(text.split())
    left = max(0, start - radius)
    right = min(len(compact), end + radius)
    return compact[left:right].strip()


def _page_source_date(page: Page) -> dict[str, Any] | None:
    candidates = (
        (page.published_at, "normalized_page.published_at", 0.98),
        (page.metadata.get("article:published_time"), "meta.article:published_time", 0.98),
        (page.metadata.get("datepublished"), "meta.datePublished", 0.94),
    )
    for value, source, confidence in candidates:
        if isinstance(value, str) and value.strip():
            return {"value": value.strip(), "source": source, "confidence": confidence}
    if len(page.date_candidates) == 1:
        candidate = page.date_candidates[0]
        if candidate.get("value"):
            return {
                "value": candidate["value"],
                "source": candidate.get("source", "html.time[datetime]"),
                "confidence": 0.68,
            }
    return None


def discover_gap_candidates(run_dir: Path) -> dict[str, Any]:
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("provider") != "ScraplingFetcher":
        raise ValueError("gap candidate discovery requires a ScraplingFetcher run")
    pages_path = run_dir / "normalized" / "pages.jsonl"
    pages, pages_bytes = _load_pages(pages_path)
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for page in pages:
        path_segments = {segment for segment in urlsplit(page.url).path.casefold().split("/") if segment}
        if path_segments.intersection({"tool", "tools", "ai-marketing-tools"}):
            continue
        text = " ".join((page.main_text or page.text).split())
        for signal_type, polarity, pattern in RULES:
            for match in pattern.finditer(text):
                excerpt = _excerpt(text, match.start(), match.end())
                identity = (page.url, signal_type, hashlib.sha256(excerpt.encode("utf-8")).hexdigest())
                if identity in seen:
                    continue
                seen.add(identity)
                candidates.append({
                    "candidate_id": hashlib.sha256("|".join(identity).encode("utf-8")).hexdigest(),
                    "signal_type": signal_type,
                    "suggested_polarity": polarity,
                    "review_status": "pending",
                    "url": page.url,
                    "excerpt": excerpt,
                    "matched_text": " ".join(match.group(0).split()),
                    "observed_at": page.observed_at,
                    "content_sha256": page.content_hash,
                    "source_date": _page_source_date(page),
                    "method": "scrapling_saved_page_candidate",
                    "extractor_version": EXTRACTOR_VERSION,
                })
    output_path = run_dir / "normalized" / "gap_candidates.jsonl"
    with output_path.open("w", encoding="utf-8") as handle:
        for candidate in candidates:
            handle.write(json.dumps(candidate, sort_keys=True) + "\n")
    summary = {
        "schema_version": "1.0",
        "extractor_version": EXTRACTOR_VERSION,
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "input": {
            "run_id": manifest["run_id"],
            "pages_file": "normalized/pages.jsonl",
            "pages_sha256": hashlib.sha256(pages_bytes).hexdigest(),
            "page_count": len(pages),
        },
        "candidate_count": len(candidates),
        "by_signal_type": dict(sorted(Counter(item["signal_type"] for item in candidates).items())),
        "review_status": "pending" if candidates else "no_candidates",
        "warning": "candidates are review prompts, not scored evidence; no candidates means unknown",
    }
    (run_dir / "normalized" / "gap_candidate_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def discover_initiative_candidates(run_dir: Path) -> dict[str, Any]:
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("provider") != "ScraplingFetcher":
        raise ValueError("initiative discovery requires a ScraplingFetcher run")
    pages_path = run_dir / "normalized" / "pages.jsonl"
    pages, pages_bytes = _load_pages(pages_path)
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for page in pages:
        path_segments = {segment for segment in urlsplit(page.url).path.casefold().split("/") if segment}
        if path_segments.intersection({"tool", "tools", "category", "categories", "ai-marketing-tools"}):
            continue
        text = " ".join((page.main_text or page.text).split())
        for signal_type, relevance, pattern in INITIATIVE_RULES:
            if signal_type == "funding_round_announced" and path_segments.intersection({
                "case-study", "case-studies", "customers", "customer-stories"
            }):
                continue
            for match in pattern.finditer(text):
                page_signal_identity = (page.url, signal_type)
                if page_signal_identity in seen:
                    continue
                excerpt = _excerpt(text, match.start(), match.end())
                excerpt_hash = hashlib.sha256(excerpt.encode("utf-8")).hexdigest()
                identity = (page.url, signal_type, excerpt_hash)
                seen.add(page_signal_identity)
                candidates.append({
                    "candidate_id": hashlib.sha256("|".join(identity).encode("utf-8")).hexdigest(),
                    "signal_type": signal_type,
                    "trigger_relevance": relevance,
                    "review_status": "pending",
                    "url": page.url,
                    "excerpt": excerpt,
                    "matched_text": " ".join(match.group(0).split()),
                    "observed_at": page.observed_at,
                    "source_date": _page_source_date(page),
                    "content_sha256": page.content_hash,
                    "method": "scrapling_saved_page_candidate",
                    "extractor_version": INITIATIVE_EXTRACTOR_VERSION,
                })
    output_path = run_dir / "normalized" / "initiative_candidates.jsonl"
    with output_path.open("w", encoding="utf-8") as handle:
        for candidate in candidates:
            handle.write(json.dumps(candidate, sort_keys=True) + "\n")
    summary = {
        "schema_version": "1.0",
        "extractor_version": INITIATIVE_EXTRACTOR_VERSION,
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "input": {
            "run_id": manifest["run_id"],
            "pages_file": "normalized/pages.jsonl",
            "pages_sha256": hashlib.sha256(pages_bytes).hexdigest(),
            "page_count": len(pages),
        },
        "candidate_count": len(candidates),
        "dated_candidate_count": sum(candidate["source_date"] is not None for candidate in candidates),
        "by_signal_type": dict(sorted(Counter(item["signal_type"] for item in candidates).items())),
        "review_status": "pending" if candidates else "no_candidates",
        "warning": "initiative candidates are pending trigger-review context, not channel-gap evidence",
    }
    (run_dir / "normalized" / "initiative_candidate_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary
