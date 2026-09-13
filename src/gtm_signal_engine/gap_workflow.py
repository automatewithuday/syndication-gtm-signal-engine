from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .account_intelligence_report import build_account_intelligence_report
from .channel_gap import score_channel_gap_run
from .gap_discovery import discover_gap_candidates
from .paid_channel_scoring import score_paid_channel_run
from .paid_gap import discover_paid_gap_candidates
from .paid_gap_review import export_paid_gap_profile, ingest_paid_gap_candidates
from .outbound_calling import (
    discover_outbound_gap_candidates,
    export_outbound_gap_profile,
    ingest_outbound_gap_candidates,
    score_outbound_calling_run,
)
from .review_queue import DEFAULT_DATABASE_PATH, connect_database, export_gap_profile, ingest_gap_candidates
from .syndication_scoring import score_syndication_run
from .unified_scoring import score_unified_account_run

WORKFLOW_VERSION = "channel_gap_resolution_v2"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _current_candidates(run_dir: Path, database_path: Path) -> list[dict[str, Any]]:
    sources = (
        ("gap_candidates.jsonl", "gap_candidates", "content_syndication", "suggested_polarity"),
        ("paid_gap_candidates.jsonl", "paid_gap_candidates", None, "suggested_position"),
        (
            "outbound_gap_candidates.jsonl", "outbound_gap_candidates",
            "outbound_calling", "suggested_position",
        ),
    )
    result: list[dict[str, Any]] = []
    with connect_database(database_path) as connection:
        for filename, table, fixed_channel, position_field in sources:
            path = run_dir / "normalized" / filename
            if not path.is_file():
                continue
            for line in path.read_bytes().splitlines():
                if not line.strip():
                    continue
                item = json.loads(line)
                row = connection.execute(
                    f"SELECT review_status FROM {table} WHERE candidate_id = ?",
                    (item["candidate_id"],),
                ).fetchone()
                result.append({
                    "candidate_id": item["candidate_id"],
                    "channel": fixed_channel or item["channel"],
                    "signal_type": item["signal_type"],
                    "suggested_position": item[position_field],
                    "review_status": row["review_status"] if row else "pending",
                    "url": item["url"],
                    "excerpt": item["excerpt"],
                    "content_sha256": item["content_sha256"],
                })
    return sorted(result, key=lambda item: (item["channel"], item["candidate_id"]))


def resolve_channel_gaps(
    run_dir: Path,
    *,
    account_name: str | None = None,
    database_path: Path = DEFAULT_DATABASE_PATH,
    content_config_path: Path | None = None,
    paid_config_path: Path | None = None,
    outbound_config_path: Path | None = None,
    unified_config_path: Path | None = None,
    as_of: date | None = None,
) -> dict[str, Any]:
    """Apply exact-run gap reviews and rebuild all dependent scores without provider calls."""
    manifest = _load(run_dir / "manifest.json")
    if manifest.get("provider") != "ScraplingFetcher":
        raise ValueError("channel-gap resolution requires a ScraplingFetcher run")
    company = _load(run_dir / "normalized" / "company_enrichment.json")
    domain = (urlsplit(str(manifest.get("seed_url", ""))).hostname or "").lower().removeprefix("www.")
    if not domain:
        raise ValueError("channel-gap resolution requires a run seed domain")
    if str(company.get("domain", "")).lower().removeprefix("www.") != domain:
        raise ValueError("channel-gap resolution requires the matching cached company profile")
    selected_name = account_name or company.get("name") or domain

    content_discovery = discover_gap_candidates(run_dir)
    paid_discovery = discover_paid_gap_candidates(run_dir)
    outbound_discovery = discover_outbound_gap_candidates(run_dir)
    content_ingestion = ingest_gap_candidates(run_dir, database_path)
    paid_ingestion = ingest_paid_gap_candidates(run_dir, database_path)
    outbound_ingestion = ingest_outbound_gap_candidates(run_dir, database_path)
    candidates = _current_candidates(run_dir, database_path)
    review_counts = dict(sorted(Counter(item["review_status"] for item in candidates).items()))

    content_profile = export_gap_profile(
        run_dir, account_name=selected_name, database_path=database_path
    )
    content_gap = score_channel_gap_run(
        run_dir, Path(content_profile["output"]), content_config_path
    )
    syndication = score_syndication_run(run_dir, content_config_path)

    paid_profile = export_paid_gap_profile(
        run_dir, account_name=selected_name, database_path=database_path
    )
    paid = score_paid_channel_run(
        run_dir, Path(paid_profile["output"]), paid_config_path
    )
    outbound_profile = export_outbound_gap_profile(
        run_dir, account_name=selected_name, database_path=database_path
    )
    outbound = score_outbound_calling_run(
        run_dir, Path(outbound_profile["output"]), outbound_config_path
    )
    unified = score_unified_account_run(
        run_dir, database_path=database_path, config_path=unified_config_path,
        as_of=as_of,
    )

    channel_results = {
        "content_syndication": {
            "gap_score": content_gap["component"].get("score"),
            "gap_status": content_gap["component"].get("status"),
            "opportunity_total": syndication.get("total"),
            "opportunity_status": syndication.get("qualification", {}).get("opportunity_status"),
        },
        **{
            channel: {
                "gap_score": details["gap"].get("score"),
                "gap_status": details["gap"].get("status"),
                "opportunity_total": unified["channels"][channel].get("total"),
                "opportunity_status": unified["channels"][channel].get("status"),
            }
            for channel, details in paid["channels"].items()
        },
        "outbound_calling": {
            "gap_score": outbound["components"]["gap"].get("score"),
            "gap_status": outbound["components"]["gap"].get("status"),
            "opportunity_total": unified["channels"]["outbound_calling"].get("total"),
            "opportunity_status": unified["channels"]["outbound_calling"].get("status"),
        },
    }
    pending = int(review_counts.get("pending", 0))
    ambiguous = any(item["gap_status"] == "review" for item in channel_results.values())
    insufficient = any(
        item["gap_status"] == "insufficient_evidence" for item in channel_results.values()
    )
    status = (
        "review_required" if pending or ambiguous
        else "insufficient_evidence" if insufficient
        else "resolved"
    )
    blockers = []
    if pending:
        blockers.append(f"{pending} channel-gap candidate(s) require human review")
    blockers.extend(
        f"{channel}: gap remains {detail['gap_status']}"
        for channel, detail in channel_results.items()
        if detail["gap_status"] in {"review", "insufficient_evidence"}
    )
    result = {
        "schema_version": "1.0",
        "workflow_version": WORKFLOW_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "run_id": manifest.get("run_id") or run_dir.name,
        "account": {"name": selected_name, "domain": domain},
        "discovery": {
            "content_syndication": content_discovery,
            "paid_channels": paid_discovery,
            "outbound_calling": outbound_discovery,
        },
        "ingestion": {
            "content_syndication": content_ingestion,
            "paid_channels": paid_ingestion,
            "outbound_calling": outbound_ingestion,
        },
        "review_counts": review_counts,
        "review_queue": candidates,
        "channels": channel_results,
        "unified_account_score": {
            "snapshot_id": unified["snapshot_id"],
            "priority": unified["priority"],
            "opportunity_status": unified["qualification"]["opportunity_status"],
        },
        "blockers": blockers,
        "interpretation": (
            "Candidates are prompts for human review. No candidates or rejected candidates "
            "leave gap evidence unknown; they do not prove that a channel is unused."
        ),
    }
    output_path = run_dir / "normalized" / "channel_gap_resolution.json"
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report = build_account_intelligence_report(run_dir, account_name=selected_name)
    result["outputs"] = {
        "resolution": str(output_path),
        "account_json": report["outputs"]["json"],
        "account_markdown": report["outputs"]["markdown"],
    }
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result
