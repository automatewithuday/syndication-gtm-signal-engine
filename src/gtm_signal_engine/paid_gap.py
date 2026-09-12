from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .gap_discovery import _excerpt, _load_pages, _page_source_date

EXTRACTOR_VERSION = "paid_gap_candidate_rules_v1"

CHANNEL_TERMS = {
    "retargeting": r"(?:retargeting|remarketing|re-engag(?:e|ement|ing)|abandoned (?:site )?visitors?)",
    "programmatic": r"(?:programmatic(?: advertising)?|display advertising|demand-side platform|\bDSP\b|ABM advertising)",
}

SIGNAL_PATTERNS = (
    (
        "explicit_expansion_intent", "supports_gap",
        r"(?:plan(?:ning)? to|want to|need to|looking to|aim(?:ing)? to|will)\s+"
        r"(?:launch|add|expand|scale|increase|invest in|build)",
    ),
    (
        "documented_distribution_bottleneck", "supports_gap",
        r"(?:manual|struggl\w*|challenge\w*|bottleneck\w*|limited|unable to|lack(?:ing)?|gap)",
    ),
    (
        "active_partner_or_hiring_search", "supports_gap",
        r"(?:hiring|request for proposal|RFP|seeking\s+(?:an?\s+)?(?:agency|media|technology)\s+partner|"
        r"(?:agency|media|technology)\s+partner\s+wanted)",
    ),
    (
        "documented_performance_shortfall", "supports_gap",
        r"(?:low conversions?|declining pipeline|underperform\w*|poor ROI|missed pipeline|limited reach|"
        r"high acquisition costs?|rising CAC)",
    ),
    (
        "documented_healthy_channel_program", "contradicts_gap",
        r"(?:active|ongoing|mature|established|always-on|scaled|successful)\s+(?:program|campaign|strategy|channel)",
    ),
    (
        "documented_channel_success", "contradicts_gap",
        r"(?:generated|drove|delivered|increased|improved)\b.{0,90}"
        r"(?:pipeline|revenue|qualified leads?|conversions?|ROI|ROAS)",
    ),
)


def _channel_pattern(channel_term: str, evidence_term: str) -> re.Pattern[str]:
    # Both orders are accepted, but the bounded window forces the claim and channel
    # to occur in the same local statement instead of elsewhere on the page.
    return re.compile(
        rf"(?:\b{evidence_term}\b.{{0,180}}\b{channel_term}\b|"
        rf"\b{channel_term}\b.{{0,180}}\b{evidence_term}\b)",
        re.I | re.S,
    )


RULES = tuple(
    (channel, signal_type, position, _channel_pattern(channel_term, evidence_term))
    for channel, channel_term in CHANNEL_TERMS.items()
    for signal_type, position, evidence_term in SIGNAL_PATTERNS
)


def discover_paid_gap_candidates(run_dir: Path) -> dict[str, Any]:
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("provider") != "ScraplingFetcher":
        raise ValueError("paid gap discovery requires a ScraplingFetcher run")
    pages_path = run_dir / "normalized" / "pages.jsonl"
    pages, pages_bytes = _load_pages(pages_path)
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for page in pages:
        path_segments = {segment for segment in urlsplit(page.url).path.casefold().split("/") if segment}
        if path_segments.intersection({
            "tool", "tools", "category", "categories", "case-study", "case-studies",
            "customers", "customer-stories",
        }):
            continue
        text = " ".join((page.main_text or page.text).split())
        for channel, signal_type, position, pattern in RULES:
            for match in pattern.finditer(text):
                excerpt = _excerpt(text, match.start(), match.end())
                excerpt_hash = hashlib.sha256(excerpt.encode("utf-8")).hexdigest()
                identity = (page.url, channel, signal_type, excerpt_hash)
                if identity in seen:
                    continue
                seen.add(identity)
                candidates.append({
                    "candidate_id": hashlib.sha256("|".join(identity).encode("utf-8")).hexdigest(),
                    "channel": channel,
                    "signal_type": signal_type,
                    "suggested_position": position,
                    "review_status": "pending",
                    "url": page.url,
                    "excerpt": excerpt,
                    "matched_text": " ".join(match.group(0).split()),
                    "observed_at": page.observed_at,
                    "source_date": _page_source_date(page),
                    "content_sha256": page.content_hash,
                    "method": "scrapling_saved_page_candidate",
                    "extractor_version": EXTRACTOR_VERSION,
                })
    output_path = run_dir / "normalized" / "paid_gap_candidates.jsonl"
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
        "by_channel": dict(sorted(Counter(item["channel"] for item in candidates).items())),
        "by_signal_type": dict(sorted(Counter(item["signal_type"] for item in candidates).items())),
        "review_status": "pending" if candidates else "no_candidates",
        "warning": "candidates require review; no candidates means unknown, never no gap",
    }
    (run_dir / "normalized" / "paid_gap_candidate_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary
