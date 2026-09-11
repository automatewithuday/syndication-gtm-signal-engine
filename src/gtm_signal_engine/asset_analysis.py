from __future__ import annotations

import hashlib
import html
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from xml.etree import ElementTree

from .classifiers import asset_document_links, classify_asset, classify_gating
from .collector import canonicalize_url, normalize_html
from .models import Page
from .providers import FetchedDocument

ASSET_ANALYZER_VERSION = "asset_rules_v1"
SubstanceStatus = Literal["yes", "no", "unknown"]
Suitability = Literal["suitable", "possible", "not_suitable", "unknown"]

TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "employee_financial_wellness": ("financial wellness", "earned wage", "on-demand pay", "pay experience"),
    "retention_and_engagement": ("retention", "turnover", "attrition", "employee engagement"),
    "outbound_and_pipeline": ("cold email", "outbound", "pipeline", "lead generation", "prospecting"),
    "content_and_social": ("linkedin", "content", "social media", "influencer"),
    "ai_and_automation": ("claude code", " ai ", "automation", "agent", "n8n"),
}

AUDIENCE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "human_resources": ("human resources", " hr ", "people leader", "total rewards", "benefits leader"),
    "finance": (" cfo", "finance leader", "payroll", "financial officer"),
    "sales_and_revenue": ("sales leader", "revenue", "revops", "gtm", "agency owner"),
    "marketing": ("marketing leader", "marketer", "content team", "demand generation"),
    "technical_builder": ("developer", "engineer", "claude code", "api", "technical team"),
}


@dataclass(frozen=True)
class DateEvidence:
    value: str
    kind: Literal["published", "created", "modified"]
    source: str
    confidence: float
    excerpt: str


@dataclass(frozen=True)
class AssetAssessment:
    url: str
    title: str
    asset_type: str
    observed_at: str
    content_hash: str | None
    published_or_created: DateEvidence | None
    modified: DateEvidence | None
    age_days: int | None
    recency_bucket: str
    gating: str
    gating_evidence: dict[str, Any]
    substantial: SubstanceStatus
    substance_confidence: float
    substance_reasons: list[str]
    evidence_excerpts: list[str]
    syndication_suitability: Suitability
    suitability_confidence: float
    suitability_reasons: list[str]
    topics: list[str] = field(default_factory=list)
    audiences: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    extractor_version: str = ASSET_ANALYZER_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_datetime(value: str) -> datetime | None:
    candidate = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", candidate):
        candidate += "T00:00:00+00:00"
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        result = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _normalized_date(value: str) -> str | None:
    parsed = _parse_datetime(value)
    return parsed.isoformat() if parsed else None


def _raw_documents(run_dir: Path) -> tuple[dict[str, tuple[dict[str, Any], bytes]], list[str]]:
    documents: dict[str, tuple[dict[str, Any], bytes]] = {}
    errors: list[str] = []
    for metadata_path in (run_dir / "raw").glob("*.json"):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"unreadable raw metadata {metadata_path.name}: {type(exc).__name__}")
            continue
        body_file = metadata.get("body_file")
        if not isinstance(body_file, str):
            errors.append(f"raw metadata missing body_file {metadata_path.name}")
            continue
        body_path = run_dir / "raw" / body_file
        if not body_path.exists():
            errors.append(f"missing raw body {body_path.name}")
            continue
        body = body_path.read_bytes()
        if hashlib.sha256(body).hexdigest() != metadata.get("body_sha256"):
            errors.append(f"raw body hash mismatch {body_path.name}")
            continue
        for value in (metadata.get("requested_url"), metadata.get("final_url")):
            if value:
                documents[canonicalize_url(value)] = (metadata, body)
    return documents, errors


def _sitemap_lastmods(documents: dict[str, tuple[dict[str, Any], bytes]]) -> dict[str, str]:
    results: dict[str, str] = {}
    for metadata, body in documents.values():
        content_type = str(metadata.get("headers", {}).get("content-type", "")).lower()
        if "xml" not in content_type:
            continue
        try:
            root = ElementTree.fromstring(body)
        except (ElementTree.ParseError, ValueError):
            continue
        for node in root:
            values = {child.tag.rsplit("}", 1)[-1].lower(): (child.text or "").strip() for child in node}
            normalized = canonicalize_url(values.get("loc", ""))
            if normalized and _normalized_date(values.get("lastmod", "")):
                results[normalized] = values["lastmod"]
    return results


def _batch_like_sitemap_dates(lastmods: dict[str, str], asset_urls: set[str]) -> set[str]:
    dated = [(url, value) for url, value in lastmods.items() if url in asset_urls and _parse_datetime(value)]
    buckets = Counter(_parse_datetime(value).strftime("%Y-%m-%dT%H:%M") for _, value in dated)  # type: ignore[union-attr]
    suspicious = {bucket for bucket, count in buckets.items() if count >= 5 and count / max(1, len(asset_urls)) >= 0.30}
    return {
        url for url, value in dated
        if _parse_datetime(value).strftime("%Y-%m-%dT%H:%M") in suspicious  # type: ignore[union-attr]
    }


def _embedded_state_dates(body: bytes) -> tuple[str | None, str | None]:
    decoded = html.unescape(body.decode("utf-8", errors="replace"))
    pairs = re.findall(
        r'createdAt\\?"?:\\?"([^"\\]+).*?updatedAt\\?"?:\\?"([^"\\]+)',
        decoded,
        flags=re.DOTALL,
    )
    valid = [(created, updated) for created, updated in pairs if _parse_datetime(created) and _parse_datetime(updated)]
    return valid[0] if len(valid) == 1 else (None, None)


def _date_evidence(
    page: Page,
    body: bytes | None,
    sitemap_lastmod: str | None,
    sitemap_is_batch_like: bool,
) -> tuple[DateEvidence | None, DateEvidence | None, list[str]]:
    risks: list[str] = []
    published: DateEvidence | None = None
    modified: DateEvidence | None = None
    published_candidates = (
        (page.published_at, "normalized_page.published_at", 0.98),
        (page.metadata.get("article:published_time"), "meta.article:published_time", 0.98),
        (page.metadata.get("datepublished"), "meta.datePublished", 0.94),
    )
    for value, source, confidence in published_candidates:
        if isinstance(value, str) and (normalized := _normalized_date(value)):
            published = DateEvidence(normalized, "published", source, confidence, value[:120])
            break

    if published is None and classify_asset(page)[0].value != "webinar" and len(page.date_candidates) == 1:
        candidate = page.date_candidates[0]
        value = candidate.get("value", "")
        if normalized := _normalized_date(value):
            excerpt = " ".join(filter(None, (candidate.get("text", ""), value)))[:120]
            published = DateEvidence(normalized, "published", "html.time[datetime]", 0.68, excerpt)

    embedded_created = embedded_updated = None
    if body:
        embedded_created, embedded_updated = _embedded_state_dates(body)
    if published is None and embedded_created and (normalized := _normalized_date(embedded_created)):
        published = DateEvidence(normalized, "created", "embedded_application_state.createdAt", 0.82, embedded_created)

    modified_candidates = (
        (page.metadata.get("article:modified_time"), "meta.article:modified_time", 0.96),
        (page.metadata.get("datemodified"), "meta.dateModified", 0.92),
        (embedded_updated, "embedded_application_state.updatedAt", 0.80),
    )
    for value, source, confidence in modified_candidates:
        if isinstance(value, str) and (normalized := _normalized_date(value)):
            modified = DateEvidence(normalized, "modified", source, confidence, value[:120])
            break
    if modified is None and sitemap_lastmod and not sitemap_is_batch_like:
        normalized = _normalized_date(sitemap_lastmod)
        if normalized:
            modified = DateEvidence(normalized, "modified", "sitemap.lastmod", 0.55, sitemap_lastmod[:120])
    elif sitemap_lastmod and sitemap_is_batch_like:
        risks.append("sitemap lastmod resembles a batch deployment timestamp and was not used as content freshness")
    if published is None:
        risks.append("publication or creation date not observed")
    return published, modified, risks


def _keyword_labels(page: Page, mapping: dict[str, tuple[str, ...]]) -> list[str]:
    source = f" {page.title} {page.metadata.get('description', '')} {page.metadata.get('og:description', '')} ".lower()
    return [label for label, phrases in mapping.items() if any(phrase in source for phrase in phrases)]


def _substance(page: Page, gating: str) -> tuple[SubstanceStatus, float, list[str], list[str]]:
    text = page.main_text or str(page.metadata.get("og:description", ""))
    words = len(re.findall(r"\b[\w'-]+\b", text))
    combined = f"{page.title} {page.metadata.get('og:description', '')} {text}".lower()
    direct_links = asset_document_links(page)
    direct_download = bool(direct_links)
    quantified = bool(re.search(r"(?:[$€£]\s?\d|\b\d[\d,.]*\s?%|\b\d[\d,.]*\+)", combined))
    reasons: list[str] = []
    excerpts: list[str] = []
    if words >= 300:
        reasons.append(f"{words} words observed in main content")
        excerpts.append(" ".join(text.split())[:240])
    if direct_download:
        reasons.append("direct document download observed")
        excerpts.append(direct_links[0][:240])
    if quantified:
        reasons.append("quantified detail observed")
        match = re.search(r"(?:[$€£]\s?\d|\b\d[\d,.]*\s?%|\b\d[\d,.]*\+)", combined)
        if match:
            excerpts.append(combined[max(0, match.start() - 90):match.end() + 90][:240])
    family = classify_asset(page)[0].value
    if family == "case_study" and words >= 250 and quantified:
        return "yes", 0.91, reasons, excerpts
    if direct_download:
        return "yes", 0.90, reasons, excerpts
    if family in {"guide", "report", "ebook", "white_paper"} and words >= 500:
        return "yes", 0.84, reasons, excerpts
    if family == "webinar" and words >= 200 and gating in {"fully_ungated", "registration_required"}:
        return "yes", 0.80, reasons, excerpts
    if gating in {"fully_gated", "summary_ungated_full_asset_gated"}:
        reasons.append("full asset content was not publicly observable")
        return "unknown", 0.45, reasons, excerpts
    reasons.append("insufficient observable main-content detail")
    return "unknown", 0.35, reasons, excerpts


def _suitability(
    page: Page, gating: str, substantial: SubstanceStatus
) -> tuple[Suitability, float, list[str]]:
    direct_download = bool(asset_document_links(page))
    family = classify_asset(page)[0].value
    if substantial == "yes" and (direct_download or family in {"case_study", "webinar"}):
        return "suitable", 0.86, ["substantial reusable asset and accessible content observed"]
    if family in {"guide", "report", "ebook", "white_paper", "webinar"} and gating != "unknown":
        return "possible", 0.67, ["promotable asset offer observed; full-content or rights review remains"]
    if substantial == "no":
        return "not_suitable", 0.75, ["asset lacks observable substance"]
    return "unknown", 0.35, ["insufficient evidence for syndication readiness"]


def analyze_asset_page(
    page: Page,
    *,
    body: bytes | None = None,
    sitemap_lastmod: str | None = None,
    sitemap_is_batch_like: bool = False,
) -> AssetAssessment | None:
    asset = classify_asset(page)
    if not asset:
        return None
    published, modified, risks = _date_evidence(page, body, sitemap_lastmod, sitemap_is_batch_like)
    observed = _parse_datetime(page.observed_at or "") or datetime.now(timezone.utc)
    published_date = _parse_datetime(published.value) if published else None
    if published_date and published_date > observed:
        risks.append("publication or creation date is later than observation time and was not used for recency")
        published_date = None
    age_days = (observed - published_date).days if published_date else None
    if age_days is None:
        recency = "unknown"
    elif age_days <= 90:
        recency = "within_90_days"
    elif age_days <= 180:
        recency = "within_180_days"
    elif age_days <= 365:
        recency = "within_365_days"
    else:
        recency = "older_than_365_days"
    gating_result = classify_gating(page)
    gating = str(gating_result.value)
    substantial, substance_confidence, substance_reasons, evidence_excerpts = _substance(page, gating)
    suitability, suitability_confidence, suitability_reasons = _suitability(page, gating, substantial)
    if not page.main_text:
        risks.append("main-content boundary unavailable; substance used metadata fallback")
    return AssetAssessment(
        url=page.url,
        title=page.title,
        asset_type=str(asset[0].value),
        observed_at=page.observed_at or observed.isoformat(),
        content_hash=page.content_hash,
        published_or_created=published,
        modified=modified,
        age_days=age_days,
        recency_bucket=recency,
        gating=gating,
        gating_evidence=gating_result.to_dict(),
        substantial=substantial,
        substance_confidence=substance_confidence,
        substance_reasons=substance_reasons,
        evidence_excerpts=evidence_excerpts,
        syndication_suitability=suitability,
        suitability_confidence=suitability_confidence,
        suitability_reasons=suitability_reasons,
        topics=_keyword_labels(page, TOPIC_KEYWORDS),
        audiences=_keyword_labels(page, AUDIENCE_KEYWORDS),
        risks=risks,
    )


def analyze_asset_run(run_dir: Path) -> dict[str, Any]:
    pages_path = run_dir / "normalized" / "pages.jsonl"
    if not pages_path.exists():
        raise FileNotFoundError(f"normalized crawl pages not found: {pages_path}")
    input_bytes = pages_path.read_bytes()
    pages = [Page(**json.loads(line)) for line in input_bytes.splitlines() if line.strip()]
    documents, raw_errors = _raw_documents(run_dir)

    enriched_pages: list[tuple[Page, bytes | None]] = []
    for page in pages:
        raw = documents.get(canonicalize_url(page.original_url or page.url)) or documents.get(canonicalize_url(page.url))
        body = raw[1] if raw else None
        if raw and "html" in str(raw[0].get("headers", {}).get("content-type", "")).lower():
            document = FetchedDocument(
                requested_url=raw[0]["requested_url"], final_url=raw[0]["final_url"],
                status_code=raw[0]["status_code"], headers=raw[0]["headers"], body=body,
            )
            reparsed = normalize_html(document, page.observed_at or raw[0].get("observed_at", ""))
            page = Page(**{
                **asdict(page),
                "main_text": reparsed.main_text,
                "date_candidates": reparsed.date_candidates,
                "link_details": reparsed.link_details,
            })
        enriched_pages.append((page, body))

    asset_urls = {page.url for page, _ in enriched_pages if classify_asset(page)}
    lastmods = _sitemap_lastmods(documents)
    batch_like_urls = _batch_like_sitemap_dates(lastmods, asset_urls)
    assessments = [
        result for page, body in enriched_pages
        if (result := analyze_asset_page(
            page, body=body, sitemap_lastmod=lastmods.get(page.url),
            sitemap_is_batch_like=page.url in batch_like_urls,
        )) is not None
    ]

    output_path = run_dir / "normalized" / "assets.jsonl"
    with output_path.open("w", encoding="utf-8") as handle:
        for assessment in assessments:
            handle.write(json.dumps(assessment.to_dict(), sort_keys=True) + "\n")

    dates = [_parse_datetime(item.published_or_created.value) for item in assessments if item.published_or_created]
    dates = sorted(value for value in dates if value)
    publication_days = sorted({value.date() for value in dates})
    intervals = [(right - left).days for left, right in zip(publication_days, publication_days[1:])]
    recency_ages = [item.age_days for item in assessments if item.age_days is not None]
    summary = {
        "schema_version": "1.0",
        "extractor_version": ASSET_ANALYZER_VERSION,
        "status": "completed" if documents and not raw_errors else "partial",
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "input": {
            "pages_file": str(pages_path.relative_to(run_dir)),
            "sha256": hashlib.sha256(input_bytes).hexdigest(),
            "page_count": len(pages),
        },
        "asset_count": len(assessments),
        "asset_types": dict(sorted(Counter(item.asset_type for item in assessments).items())),
        "substantial": dict(sorted(Counter(item.substantial for item in assessments).items())),
        "syndication_suitability": dict(sorted(Counter(item.syndication_suitability for item in assessments).items())),
        "gating_types": dict(sorted(Counter(item.gating for item in assessments).items())),
        "recency": dict(sorted(Counter(item.recency_bucket for item in assessments).items())),
        "dated_asset_count": len(dates),
        "unknown_date_count": sum(item.published_or_created is None for item in assessments),
        "freshness_windows": {
            "within_90_days": sum(age <= 90 for age in recency_ages),
            "within_180_days": sum(age <= 180 for age in recency_ages),
            "within_365_days": sum(age <= 365 for age in recency_ages),
        },
        "distinct_publishing_dates": len(publication_days),
        "median_publishing_interval_days": sorted(intervals)[len(intervals) // 2] if intervals else None,
        "batch_like_sitemap_lastmod_ignored": len(batch_like_urls),
        "raw_artifacts": {
            "documents_available": len(documents),
            "errors": raw_errors,
        },
    }
    (run_dir / "normalized" / "asset_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary
