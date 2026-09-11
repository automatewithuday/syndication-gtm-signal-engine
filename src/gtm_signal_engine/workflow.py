from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .asset_analysis import analyze_asset_run
from .classification_run import classify_crawl_run
from .collector import ScraplingFetcher, collect_website
from .gap_discovery import discover_gap_candidates, discover_initiative_candidates
from .providers import WebsiteFetcher
from .syndication_scoring import score_syndication_run


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def crawl_and_analyze(
    domain: str,
    *,
    output_path: Path,
    output_root: Path = Path("data/runs"),
    account_name: str | None = None,
    maximum_pages: int = 100,
    maximum_sitemaps: int = 20,
    delay_seconds: float = 0.25,
    fetcher: WebsiteFetcher | None = None,
    config_path: Path | None = None,
) -> dict[str, Any]:
    """Run the Phase 1 website workflow and write one auditable JSON report."""
    _, _, run_dir = collect_website(
        domain,
        output_root=output_root,
        maximum_pages=maximum_pages,
        maximum_sitemaps=maximum_sitemaps,
        delay_seconds=delay_seconds,
        fetcher=fetcher or ScraplingFetcher(),
    )
    return analyze_saved_run(
        run_dir, output_path=output_path, account_name=account_name, config_path=config_path
    )


def analyze_saved_run(
    run_dir: Path,
    *,
    output_path: Path,
    account_name: str | None = None,
    config_path: Path | None = None,
) -> dict[str, Any]:
    """Resume deterministic analysis from an existing saved crawl."""
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    classification = classify_crawl_run(run_dir)
    asset_summary = analyze_asset_run(run_dir)
    gap_candidates = discover_gap_candidates(run_dir)
    initiative_candidates = discover_initiative_candidates(run_dir)
    score = score_syndication_run(run_dir, config_path)
    assets = _load_jsonl(run_dir / "normalized" / "assets.jsonl")
    evidence_samples = [
        {
            "url": asset["url"],
            "title": asset.get("title"),
            "asset_type": asset.get("asset_type"),
            "gating": asset.get("gating"),
            "substantial": asset.get("substantial"),
            "syndication_suitability": asset.get("syndication_suitability"),
            "published_or_created": asset.get("published_or_created"),
            "excerpts": asset.get("evidence_excerpts", []),
        }
        for asset in sorted(
            assets,
            key=lambda item: (
                item.get("substantial") != "yes",
                item.get("syndication_suitability") != "suitable",
                item.get("url", ""),
            ),
        )[:20]
    ]
    hostname = (urlsplit(manifest["seed_url"]).hostname or "").removeprefix("www.")
    report = {
        "schema_version": "1.0",
        "account": {"name": account_name or hostname, "domain": hostname},
        "run": manifest,
        "run_dir": str(run_dir),
        "classification": classification,
        "asset_summary": asset_summary,
        "scores": score,
        "review_queues": {
            "gap_candidates": gap_candidates,
            "initiative_candidates": initiative_candidates,
        },
        "evidence_samples": evidence_samples,
        "interpretation": (
            "Unknown components are unresolved evidence requirements, not zero scores or proof that a channel is absent. "
            "Fit, gap, and reviewed initiatives must be completed in the saved run before final qualification."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report
