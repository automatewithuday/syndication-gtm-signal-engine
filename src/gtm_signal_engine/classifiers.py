from __future__ import annotations

import re
from datetime import date
from typing import Any, cast
from urllib.parse import urlparse

from .models import Evidence, EvidenceStrength, Page

ASSET_FAMILIES = {"case_study", "ebook", "guide", "report", "white_paper", "webinar"}
GATEABLE_FAMILIES = {"ebook", "guide", "report", "white_paper", "webinar"}

CTA_PATTERNS: dict[str, tuple[str, ...]] = {
    "demo": ("book a demo", "request a demo", "get a demo", "schedule a demo"),
    "contact_sales": ("contact sales", "talk to sales", "speak to sales"),
    "trial": ("start free trial", "free trial", "try for free"),
    "pricing": ("request pricing", "view pricing", "see pricing"),
}

LEGAL_DOCUMENT_MARKERS = (
    "privacy", "terms", "legal", "accessibility", "consumer-notice",
    "consumer_notice", "glba", "compliance-notice",
)
ASSET_DOCUMENT_MARKERS = (
    "download", "case-study", "case_study", "ebook", "e-book", "guide",
    "report", "research", "whitepaper", "white-paper", "asset", "primer",
)


def _haystack(page: Page) -> str:
    return f"{page.url} {page.title} {page.text}".lower()


def _excerpt(text: str, phrase: str, radius: int = 90) -> str:
    normalized = " ".join(text.split())
    index = normalized.lower().find(phrase.lower())
    if index < 0:
        return normalized[: radius * 2]
    return normalized[max(0, index - radius) : index + len(phrase) + radius]


def _make_evidence(
    page: Page,
    *,
    signal_type: str,
    value: Any,
    strength: str,
    confidence: float,
    excerpt: str = "",
) -> Evidence:
    return Evidence(
        signal_type=signal_type,
        value=value,
        strength=cast(EvidenceStrength, strength),
        confidence=confidence,
        url=page.url,
        excerpt=excerpt,
        observed_at=page.observed_at or date.today().isoformat(),
    )


def classify_page_family(page: Page) -> Evidence:
    path = urlparse(page.url).path.lower().rstrip("/")
    title = page.title.lower()
    path_and_title = f"{path} {title}"

    if not path:
        family, confidence, matched = "homepage", 0.99, page.title
    elif re.search(r"/(case-studies|customer-stories|success-stories)(?:/page/\d+)?$", path):
        family, confidence, matched = "taxonomy", 0.98, "asset listing URL"
    elif path == "/guides":
        family, confidence, matched = "taxonomy", 0.98, "guide listing URL"
    elif any(marker in path for marker in ("/case-stud", "/customer-stor", "/success-stor")):
        family, confidence, matched = "case_study", 0.98, "case study URL"
    elif "/customers/" in path:
        family, confidence, matched = "case_study", 0.88, "customer URL"
    elif "/blog/" in path:
        family, confidence, matched = "blog", 0.98, "blog URL"
    elif "/blog-categories/" in path or "/category/" in path or "/tag/" in path or "/author/" in path:
        family, confidence, matched = "taxonomy", 0.96, "taxonomy URL"
    elif "/financial-literacy/" in path:
        family, confidence, matched = "article", 0.94, "article URL"
    elif "/podcast" in path:
        family, confidence, matched = "podcast", 0.98, "podcast URL"
    elif "/video" in path:
        family, confidence, matched = "video", 0.96, "video URL"
    elif "/tools/" in path or path == "/free-tools" or "/free-tools/" in path:
        family, confidence, matched = "tool_catalog", 0.94, "tool URL"
    elif "/skills/" in path:
        family, confidence, matched = "skill_catalog", 0.94, "skill URL"
    elif "/apis/" in path or path == "/apis":
        family, confidence, matched = "api_catalog", 0.94, "API URL"
    elif "/mcp/" in path or path == "/mcp":
        family, confidence, matched = "mcp_catalog", 0.94, "MCP URL"
    elif "/tech-stacks/" in path or path == "/tech-stacks":
        family, confidence, matched = "tech_stack", 0.92, "tech-stack URL"
    elif "/benchmarks/" in path or path == "/benchmarks":
        family, confidence, matched = "comparison", 0.88, "benchmark URL"
    elif "whitepaper" in path_and_title or "white paper" in title:
        family, confidence, matched = "white_paper", 0.96, "white paper"
    elif "/ebook" in path or re.search(r"\be-?book\b", title):
        family, confidence, matched = "ebook", 0.96, "ebook"
    elif "/webinar" in path or "webinar" in title:
        family, confidence, matched = "webinar", 0.96, "webinar"
    elif "/guide" in path or any(word in title for word in ("guide", "playbook", "handbook")):
        family, confidence, matched = "guide", 0.91, "guide"
    elif any(marker in path for marker in ("/report", "/research")) or any(
        phrase in title for phrase in ("benchmark report", "industry report", "research report")
    ):
        family, confidence, matched = "report", 0.91, "report"
    elif "/industr" in path:
        family, confidence, matched = "industry", 0.95, "industry URL"
    elif "/use-case" in path:
        family, confidence, matched = "use_case", 0.95, "use-case URL"
    elif "/solution" in path:
        family, confidence, matched = "solution", 0.93, "solution URL"
    elif "/integration" in path:
        family, confidence, matched = "integration", 0.93, "integration URL"
    elif "/pricing" in path:
        family, confidence, matched = "pricing", 0.98, "pricing URL"
    elif any(marker in path for marker in ("/demo", "/contact", "/get-started", "/trial")):
        family, confidence, matched = "conversion", 0.90, "conversion URL"
    elif path in {"/about", "/investors", "/careers", "/company"}:
        family, confidence, matched = "company", 0.90, "company URL"
    else:
        family, confidence, matched = "unknown", 0.25, page.title

    return _make_evidence(
        page,
        signal_type="page_family",
        value=family,
        strength="likely" if family != "unknown" else "unknown",
        confidence=confidence,
        excerpt=matched,
    )


def classify_asset(page: Page) -> list[Evidence]:
    family = classify_page_family(page)
    if family.value not in ASSET_FAMILIES:
        return []
    return [_make_evidence(
        page,
        signal_type="content_asset_type",
        value=family.value,
        strength="likely",
        confidence=family.confidence,
        excerpt=family.excerpt,
    )]


def asset_document_links(page: Page) -> list[str]:
    """Return downloadable documents plausibly connected to the current asset."""
    detail_text = {item.get("href", ""): item.get("text", "") for item in page.link_details}
    page_tokens = {
        token for token in re.findall(r"[a-z0-9]+", f"{urlparse(page.url).path} {page.title}".lower())
        if len(token) >= 4 and token not in {"with", "from", "your", "this", "that", "dailypay", "coldiq"}
    }
    results: list[str] = []
    for link in page.links:
        path = urlparse(link).path.lower()
        if not path.endswith((".pdf", ".ppt", ".pptx")) or any(marker in path for marker in LEGAL_DOCUMENT_MARKERS):
            continue
        context = f"{path} {detail_text.get(link, '')}".lower()
        link_tokens = set(re.findall(r"[a-z0-9]+", context))
        if any(marker in context for marker in ASSET_DOCUMENT_MARKERS) or bool(page_tokens & link_tokens):
            results.append(link)
    return sorted(set(results))


def _form_markers(form: dict[str, Any]) -> str:
    details = form.get("field_details", [])
    values = [
        form.get("action", ""), form.get("id", ""), form.get("name", ""),
        form.get("class", ""), form.get("data_name", ""), form.get("text", ""),
        form.get("submit_text", ""), form.get("purpose", ""),
        " ".join(str(value) for value in form.get("fields", [])),
    ]
    for detail in details:
        values.extend((detail.get("name", ""), detail.get("type", ""), detail.get("placeholder", "")))
    return " ".join(str(value) for value in values).lower()


def classify_forms(page: Page) -> list[Evidence]:
    results: list[Evidence] = []
    page_family = classify_page_family(page).value
    for index, form in enumerate(page.forms):
        markers = _form_markers(form)
        field_names = {str(value).lower() for value in form.get("fields", [])}
        field_types = {str(value.get("type", "")).lower() for value in form.get("field_details", [])}
        method = str(form.get("method", "get")).lower()
        declared_purpose = str(form.get("purpose", "")).lower()

        if declared_purpose in {"download", "asset", "asset_access"}:
            purpose, confidence, reason = "asset_access", 0.97, "declared asset purpose"
        elif declared_purpose in {"registration", "webinar"}:
            purpose, confidence, reason = "asset_access", 0.94, "declared registration purpose"
        elif "search" in field_types or (method == "get" and field_names & {"s", "q", "query", "search"}):
            purpose, confidence, reason = "site_search", 0.98, "search field or query parameter"
        elif any(word in markers for word in ("download", "access the", "receive ", "get the ")) and any(
            asset in markers for asset in ("ebook", "e-book", "guide", "report", "playbook", "whitepaper", "webinar")
        ):
            purpose, confidence, reason = "asset_access", 0.91, "asset-access language"
        elif page_family in GATEABLE_FAMILIES and ("mkto" in markers or "marketo" in markers):
            purpose, confidence, reason = "asset_access", 0.84, "asset-page marketing form"
        elif page_family in GATEABLE_FAMILIES and "guide" in markers and any(
            phrase in markers for phrase in ("work email", "complete check", "one email per guide")
        ):
            purpose, confidence, reason = "asset_access", 0.88, "guide delivery form"
        elif re.search(r"\bsubscribe\b", markers) or any(
            word in markers for word in ("newsletter", "inbox", "email updates")
        ):
            purpose, confidence, reason = "newsletter", 0.94, "newsletter language"
        elif any(word in markers for word in ("book a demo", "request a demo", "schedule a demo", "book a call")):
            purpose, confidence, reason = "demo", 0.90, "demo or scheduling language"
        elif any(word in markers for word in ("contact sales", "talk to sales", "contact us", "inquiry")):
            purpose, confidence, reason = "contact", 0.86, "contact language"
        else:
            purpose, confidence, reason = "unknown", 0.30, "insufficient form context"

        results.append(_make_evidence(
            page,
            signal_type="form_purpose",
            value={"form_index": index, "purpose": purpose, "reason": reason},
            strength="likely" if purpose != "unknown" else "unknown",
            confidence=confidence,
            excerpt=markers[:180],
        ))
    return results


def classify_gating(page: Page) -> Evidence:
    family = classify_page_family(page).value
    direct_asset = bool(asset_document_links(page))
    form_purposes = [item.value["purpose"] for item in classify_forms(page)]
    has_asset_form = "asset_access" in form_purposes
    has_marketing_form = any("mkto" in _form_markers(form) or "marketo" in _form_markers(form) for form in page.forms)
    focus = f"{page.title} {page.text[:2500]}".lower()
    gate_language = any(phrase in focus for phrase in (
        "complete the form", "fill out the form", "download now", "download the",
        "access the report", "register now", "watch on demand", "send our ebook",
    ))

    if family == "case_study" and len(page.text) >= 500:
        value, confidence, strength, excerpt = "fully_ungated", 0.86, "likely", page.title
    elif family == "webinar" and has_asset_form:
        value, confidence, strength, excerpt = "registration_required", 0.91, "likely", "webinar registration form"
    elif family == "webinar" and any(phrase in focus for phrase in ("webinar replay", "watch the replay", "replay available")):
        value, confidence, strength, excerpt = "fully_ungated", 0.88, "likely", "webinar replay available"
    elif family in GATEABLE_FAMILIES and direct_asset and (has_asset_form or (has_marketing_form and gate_language)):
        value, confidence, strength, excerpt = "optional_gate", 0.82, "likely", "form and direct asset link"
    elif family in GATEABLE_FAMILIES and (has_asset_form or (has_marketing_form and gate_language)):
        if len(page.text) >= 1200:
            value, confidence, strength, excerpt = (
                "summary_ungated_full_asset_gated", 0.84, "likely", "page content and asset-access form"
            )
        else:
            value, confidence, strength, excerpt = "fully_gated", 0.88, "likely", "asset-access form"
    elif family in GATEABLE_FAMILIES and direct_asset:
        value, confidence, strength, excerpt = "fully_ungated", 0.90, "likely", "direct asset link"
    else:
        value, confidence, strength, excerpt = "unknown", 0.30, "unknown", "insufficient asset-access evidence"

    return _make_evidence(
        page,
        signal_type="gating_type",
        value=value,
        strength=strength,
        confidence=confidence,
        excerpt=excerpt,
    )


def classify_conversion_paths(page: Page) -> list[Evidence]:
    haystack = _haystack(page)
    results: list[Evidence] = []
    for cta_type, phrases in CTA_PATTERNS.items():
        matched = next((phrase for phrase in phrases if phrase in haystack), None)
        if matched:
            results.append(_make_evidence(
                page,
                signal_type="conversion_path",
                value=cta_type,
                strength="likely",
                confidence=0.85,
                excerpt=_excerpt(page.text or page.title, matched),
            ))
    return results


def classify_segment_page(page: Page) -> list[Evidence]:
    path = urlparse(page.url).path.lower()
    results: list[Evidence] = []
    for kind, marker in (("industry", "/industr"), ("persona", "/teams/"), ("use_case", "/use-case")):
        if marker in path:
            slug = re.split(r"/", path.strip("/"))[-1].replace("-", " ")
            results.append(_make_evidence(
                page,
                signal_type="segment_page",
                value={"kind": kind, "segment": slug},
                strength="likely",
                confidence=0.82,
                excerpt=page.title,
            ))
    return results


def analyze_page(page: Page) -> list[Evidence]:
    family = classify_page_family(page)
    evidence = [family]
    assets = classify_asset(page)
    evidence.extend(assets)
    evidence.extend(classify_forms(page))
    if assets:
        evidence.append(classify_gating(page))
    evidence.extend(classify_conversion_paths(page))
    evidence.extend(classify_segment_page(page))
    return evidence
