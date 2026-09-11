from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"required review artifact missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _component_summary(component: dict[str, Any]) -> dict[str, Any]:
    return {
        "score": component.get("score"),
        "confidence": component.get("confidence"),
        "state": component.get("state", "unknown"),
        "status": component.get("status"),
        "reasons": component.get("reasons", []),
        "risks": component.get("risks", []),
    }


def _fit_signals(component: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "signal": factor["id"],
            "points": factor.get("points"),
            "maximum_points": factor.get("maximum_points"),
            "state": factor.get("state"),
            "reason": factor.get("reason"),
            "evidence": factor.get("evidence", []),
        }
        for factor in component.get("factors", [])
    ]


def _readiness_signals(component: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "signal": factor["id"],
            "observed": factor.get("observed"),
            "points": factor.get("points"),
            "maximum_points": factor.get("maximum_points"),
            "evidence_urls": factor.get("evidence_urls", []),
        }
        for factor in component.get("factors", [])
    ]


def _markdown_fit_signals(signals: list[dict[str, Any]]) -> list[str]:
    rows: list[str] = []
    for signal in signals:
        evidence = signal.get("evidence", [])
        source = evidence[0] if evidence else {}
        source_link = f" [source]({source['url']})" if source.get("url") else ""
        excerpt = f" — “{source['excerpt']}”" if source.get("excerpt") else ""
        rows.append(
            f"- `{signal['signal']}`: {signal.get('points')}/{signal.get('maximum_points')} "
            f"points ({signal.get('state')}).{excerpt}{source_link}"
        )
    return rows or ["- No fit signals recorded."]


def _markdown_initiatives(signals: list[dict[str, Any]]) -> list[str]:
    rows: list[str] = []
    for signal in signals:
        source_date = signal.get("source_date", {}).get("value") if signal.get("source_date") else "date unknown"
        source_link = f" [source]({signal['url']})" if signal.get("url") else ""
        rows.append(
            f"- `{signal.get('signal_type')}`: {signal.get('strength')} at "
            f"{signal.get('confidence')} confidence; {source_date}. “{signal.get('excerpt', '')}”{source_link}"
        )
    return rows or ["- No reviewed initiative evidence recorded."]


def build_account_review(run_dir: Path, *, account_name: str) -> dict[str, Any]:
    normalized = run_dir / "normalized"
    manifest = _load(run_dir / "manifest.json")
    classification = _load(normalized / "classification_summary.json")
    assets = _load(normalized / "asset_summary.json")
    fit = _load(normalized / "account_fit.json")
    gap = _load(normalized / "channel_gap.json")
    score = _load(normalized / "syndication_score.json")
    pages_path = normalized / "pages.jsonl"
    pages_sha256 = _sha256(pages_path)
    if score.get("input", {}).get("run_id") != manifest.get("run_id"):
        raise ValueError("syndication score run ID does not match the crawl manifest")
    if score.get("input", {}).get("assets_sha256") != _sha256(normalized / "assets.jsonl"):
        raise ValueError("syndication score does not match the current asset evidence")
    if fit.get("input", {}).get("pages_sha256") != pages_sha256:
        raise ValueError("account-fit score does not match the current saved pages")
    if gap.get("input", {}).get("pages_sha256") != pages_sha256:
        raise ValueError("channel-gap score does not match the current saved pages")
    trigger_path = normalized / "business_trigger.json"
    trigger = _load(trigger_path) if trigger_path.exists() else None
    if trigger and trigger.get("input", {}).get("pages_sha256") != pages_sha256:
        raise ValueError("business-trigger score does not match the current saved pages")
    domain = (urlsplit(str(manifest["seed_url"])).hostname or "").removeprefix("www.")
    components = score["components"]
    report = {
        "schema_version": "1.0",
        "account": {"name": account_name, "domain": domain},
        "run": {
            "run_id": manifest["run_id"],
            "provider": manifest["provider"],
            "status": manifest["status"],
            "incomplete": manifest["incomplete"],
            "pages_collected": manifest["pages_collected"],
            "pages_sha256": pages_sha256,
            "errors": manifest.get("errors", []),
        },
        "classification": {
            "page_families": classification.get("page_families", {}),
            "asset_types": classification.get("asset_types", {}),
            "gating_types": classification.get("gating_types", {}),
        },
        "assets": {
            "asset_count": assets.get("asset_count"),
            "dated_asset_count": assets.get("dated_asset_count"),
            "freshness_windows": assets.get("freshness_windows", {}),
            "substantial": assets.get("substantial", {}),
            "syndication_suitability": assets.get("syndication_suitability", {}),
        },
        "components": {
            name: {
                **_component_summary(component),
                "confidence": component.get("confidence", score.get("component_confidence", {}).get(name)),
            }
            for name, component in components.items()
        },
        "signals": {
            "fit": _fit_signals(components["fit"]),
            "readiness": _readiness_signals(components["readiness"]),
            "gap": components["gap"].get("evidence", []),
            "reviewed_initiatives": trigger.get("component", {}).get("evidence", []) if trigger else [],
        },
        "reviewed_initiative_component": trigger.get("component") if trigger else None,
        "overall": {
            "weighted_total": score.get("total"),
            "confidence": score.get("confidence"),
            "qualification": score.get("qualification"),
            "scoring_version": score.get("scoring_version"),
            "snapshot_id": score.get("snapshot_id"),
        },
        "interpretation": (
            "A null weighted total means a required component is unknown; it is not a zero score. "
            "Public-web absence never proves that a channel is unused."
        ),
    }
    json_path = normalized / "account_review.json"
    markdown_path = normalized / "account_review.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    rows = []
    for name in ("fit", "readiness", "gap", "trigger"):
        component = report["components"][name]
        rows.append(
            f"| {name.title()} | {component['score'] if component['score'] is not None else 'Unknown'} "
            f"| {component['confidence'] if component['confidence'] is not None else '—'} "
            f"| {component['status'] or component['state']} |"
        )
    blockers = report["overall"]["qualification"].get("blockers", [])
    markdown = "\n".join([
        f"# {account_name} account review",
        "",
        f"Run: `{manifest['run_id']}` · Provider: `{manifest['provider']}` · Pages: {manifest['pages_collected']}",
        "",
        "| Component | Score | Confidence | Status |",
        "| --- | ---: | ---: | --- |",
        *rows,
        "",
        f"Weighted total: **{report['overall']['weighted_total'] if report['overall']['weighted_total'] is not None else 'Not calculated'}**",
        f"Overall confidence: **{report['overall']['confidence']}**",
        f"Qualification: **{report['overall']['qualification']['opportunity_status']}**",
        f"Blockers: **{', '.join(blockers) if blockers else 'None'}**",
        "",
        "## Observed asset signals",
        "",
        f"- {assets.get('asset_count', 0)} assets; {assets.get('substantial', {}).get('yes', 0)} substantial.",
        f"- {assets.get('freshness_windows', {}).get('within_90_days', 0)} published/created within 90 days.",
        f"- Suitability: {json.dumps(assets.get('syndication_suitability', {}), sort_keys=True)}.",
        "",
        "## Fit evidence",
        "",
        *_markdown_fit_signals(report["signals"]["fit"]),
        "",
        "## Reviewed initiative evidence",
        "",
        *_markdown_initiatives(report["signals"]["reviewed_initiatives"]),
        "",
        "## Reasoning and risks",
        "",
        *[
            f"- **{name.title()}** — {'; '.join(report['components'][name]['reasons']) or 'No positive evidence.'} "
            f"Risks: {'; '.join(report['components'][name]['risks']) or 'None recorded.'}"
            for name in ("fit", "readiness", "gap", "trigger")
        ],
        "",
        f"> {report['interpretation']}",
        "",
    ])
    markdown_path.write_text(markdown, encoding="utf-8")
    return {"report": report, "json": str(json_path), "markdown": str(markdown_path)}
