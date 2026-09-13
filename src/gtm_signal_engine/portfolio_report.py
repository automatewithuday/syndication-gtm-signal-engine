from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .review_queue import DEFAULT_DATABASE_PATH, connect_database

PORTFOLIO_REPORT_VERSION = "account_portfolio_v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load(path: Path | None) -> tuple[dict[str, Any], str | None]:
    if path is None or not path.is_file():
        return {}, "account report is unavailable"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, f"account report could not be read: {type(exc).__name__}: {exc}"
    if not isinstance(value, dict):
        return {}, "account report is not a JSON object"
    return value, None


def _account_row(database_row: Any) -> dict[str, Any]:
    request = json.loads(database_row["request_json"])
    report_path = Path(database_row["report_path"]) if database_row["report_path"] else None
    report, report_error = _load(report_path)
    unified = report.get("unified_account_score") or {}
    priority = unified.get("priority") or {}
    channels = unified.get("channels") or {}
    channel_statuses = {
        channel: {
            "status": detail.get("status", "unknown"),
            "total": detail.get("total"),
            "gap_status": detail.get("components", {}).get("gap", {}).get("status", "unknown"),
        }
        for channel, detail in channels.items()
        if isinstance(detail, dict)
    }
    return {
        "job_id": database_row["job_id"],
        "account_name": request.get("account_name") or database_row["account_name"],
        "domain": request.get("domain") or database_row["account_domain"],
        "job_status": database_row["status"],
        "job_error": database_row["last_error"],
        "pipeline_version": request.get("pipeline_version"),
        "report_path": str(report_path) if report_path else None,
        "report_status": "unavailable" if report_error else "available",
        "report_error": report_error,
        "priority_score": priority.get("score"),
        "priority_status": priority.get("status", "unknown"),
        "evidence_coverage": priority.get("evidence_coverage"),
        "confidence": priority.get("confidence"),
        "opportunity_status": (
            unified.get("qualification", {}).get("opportunity_status")
            or "unknown"
        ),
        "channels": channel_statuses,
        "blockers": report.get("blockers", []),
        "provider_cost_usd": database_row["provider_cost_usd"],
    }


def build_portfolio_report(
    *, database_path: Path = DEFAULT_DATABASE_PATH,
    output_path: Path = Path("reports/account_portfolio.json"),
) -> dict[str, Any]:
    """Build a provider-free priority view from persisted account job reports."""
    with connect_database(database_path) as connection:
        database_rows = connection.execute(
            "SELECT * FROM analysis_jobs ORDER BY updated_at, job_id"
        ).fetchall()
    history_counts: Counter[str] = Counter()
    latest_by_domain: dict[str, Any] = {}
    for row in database_rows:
        domain = str(json.loads(row["request_json"]).get("domain") or row["account_domain"])
        history_counts[domain] += 1
        latest_by_domain[domain] = row
    accounts = [_account_row(row) for row in latest_by_domain.values()]
    for item in accounts:
        item["job_history_count"] = history_counts[item["domain"]]
    accounts.sort(key=lambda item: (
        item["priority_score"] is None,
        -(float(item["priority_score"]) if item["priority_score"] is not None else -1),
        item["domain"],
    ))
    snapshot_rows = [{
        key: value for key, value in item.items()
        if key not in {"report_path"}
    } for item in accounts]
    snapshot_id = hashlib.sha256(json.dumps({
        "report_version": PORTFOLIO_REPORT_VERSION,
        "accounts": snapshot_rows,
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    result = {
        "schema_version": "1.0",
        "report_version": PORTFOLIO_REPORT_VERSION,
        "generated_at": _now(),
        "snapshot_id": snapshot_id,
        "database": str(database_path),
        "job_count": len(database_rows),
        "account_count": len(accounts),
        "ranked_count": sum(item["priority_score"] is not None for item in accounts),
        "qualified_count": sum(
            item["opportunity_status"] == "qualified" for item in accounts
        ),
        "accounts": accounts,
        "interpretation": (
            "Priority ranks accounts for analyst review. Channel qualification remains separate "
            "and requires complete fit, readiness, gap, and trigger evidence."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path = output_path.with_suffix(".csv")
    markdown_path = output_path.with_suffix(".md")
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = [
            "rank", "account_name", "domain", "job_status", "priority_score",
            "priority_status", "evidence_coverage", "confidence",
            "opportunity_status", "provider_cost_usd", "report_path", "blockers",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for rank, item in enumerate(accounts, 1):
            writer.writerow({
                **{key: item.get(key) for key in fieldnames if key not in {"rank", "blockers"}},
                "rank": rank if item["priority_score"] is not None else "",
                "blockers": " | ".join(str(value) for value in item["blockers"]),
            })
    lines = [
        "# Account portfolio", "",
        f"- Accounts: {len(accounts)}",
        f"- Job records: {len(database_rows)}",
        f"- Ranked: {result['ranked_count']}",
        f"- Channel-qualified: {result['qualified_count']}", "",
        "| Rank | Account | Priority | Coverage | Confidence | Opportunity | Job |",
        "|---:|---|---:|---:|---:|---|---|",
    ]
    for rank, item in enumerate(accounts, 1):
        score = item["priority_score"]
        coverage = item["evidence_coverage"]
        confidence = item["confidence"]
        rank_label = str(rank) if score is not None else "—"
        score_label = str(score) if score is not None else "unknown"
        coverage_label = f"{float(coverage):.0%}" if coverage is not None else "unknown"
        confidence_label = (
            f"{float(confidence):.0%}" if confidence is not None else "unknown"
        )
        lines.append(
            f"| {rank_label} | {item['account_name']} | {score_label} | "
            f"{coverage_label} | {confidence_label} | "
            f"{item['opportunity_status']} | {item['job_status']} |"
        )
    lines.extend(["", result["interpretation"], ""])
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    result["outputs"] = {
        "json": str(output_path), "csv": str(csv_path), "markdown": str(markdown_path),
    }
    return result
