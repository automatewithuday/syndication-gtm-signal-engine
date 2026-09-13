from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .review_queue import DEFAULT_DATABASE_PATH, connect_database

VALID_REVIEW_DECISIONS = {"agree", "disagree", "correct"}
VALID_OUTCOMES = {"reply", "positive_reply", "meeting", "opportunity", "bounce", "opt_out"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _component_evidence(components: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Normalize frozen component inputs into signal-bearing outcome evidence."""
    result: dict[str, list[dict[str, Any]]] = {}
    for component_name, component in components.items():
        items = list(component.get("evidence", []))
        if component_name == "readiness" and not items:
            items = [
                {
                    "signal": factor.get("id"),
                    "state": factor.get("state"),
                    "observed": factor.get("observed"),
                    "confidence": factor.get("confidence"),
                    "source": factor.get("source"),
                }
                for factor in component.get("factors", [])
                if factor.get("state") == "observed"
            ]
        result[component_name] = items
    return result


def review_classification(
    run_dir: Path,
    *,
    url: str,
    content_sha256: str,
    signal_type: str,
    original_value: Any,
    decision: str,
    reviewer: str,
    notes: str,
    corrected_value: Any = None,
    database_path: Path = DEFAULT_DATABASE_PATH,
) -> dict[str, Any]:
    if decision not in VALID_REVIEW_DECISIONS:
        raise ValueError("decision must be agree, disagree, or correct")
    if decision == "correct" and corrected_value is None:
        raise ValueError("correct decision requires corrected_value")
    if not reviewer.strip() or not notes.strip():
        raise ValueError("reviewer and notes are required")
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    pages = [json.loads(line) for line in (run_dir / "normalized/pages.jsonl").read_text().splitlines() if line.strip()]
    if not any(page["url"] == url and page["content_hash"] == content_sha256 for page in pages):
        raise ValueError("classification review must match a saved page URL/content hash")
    domain = (urlsplit(manifest["seed_url"]).hostname or "").removeprefix("www.")
    timestamp = _now()
    with connect_database(database_path) as connection:
        cursor = connection.execute(
            """INSERT INTO classification_reviews(
               account_domain, run_id, url, content_sha256, signal_type,
               original_value_json, decision, corrected_value_json, reviewer, notes, reviewed_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (domain, manifest["run_id"], url, content_sha256, signal_type,
             json.dumps(original_value, sort_keys=True), decision,
             json.dumps(corrected_value, sort_keys=True) if corrected_value is not None else None,
             reviewer.strip(), notes.strip(), timestamp),
        )
        review_id = cursor.lastrowid
    return {"review_id": review_id, "decision": decision, "reviewed_at": timestamp}


def create_outreach_snapshot(
    run_dir: Path,
    *,
    database_path: Path = DEFAULT_DATABASE_PATH,
    channel: str = "content_syndication",
) -> dict[str, Any]:
    if channel == "outbound_calling":
        score = json.loads(
            (run_dir / "normalized/unified_account_score.json").read_text(encoding="utf-8")
        )
        channel_score = score.get("channels", {}).get(channel, {})
        if channel_score.get("status") != "qualified":
            raise ValueError("outbound outreach snapshot requires a qualified channel")
        snapshot_id = score["snapshot_id"]
        evidence = _component_evidence(channel_score["components"])
        account = score["account"]
        run_id = score["input"]["run_id"]
        scoring_version = score["scoring_version"]
        stored_score = channel_score
    elif channel == "content_syndication":
        review = json.loads((run_dir / "normalized/account_review.json").read_text(encoding="utf-8"))
        score = json.loads((run_dir / "normalized/syndication_score.json").read_text(encoding="utf-8"))
        if review["overall"]["snapshot_id"] != score["snapshot_id"]:
            raise ValueError("account review and score snapshot do not match")
        snapshot_id = score["snapshot_id"]
        evidence = review["signals"]
        account = review["account"]
        run_id = review["run"]["run_id"]
        scoring_version = score["scoring_version"]
        stored_score = score
    else:
        raise ValueError("channel must be content_syndication or outbound_calling")
    timestamp = _now()
    with connect_database(database_path) as connection:
        connection.execute(
            """INSERT OR IGNORE INTO outreach_snapshots(
               snapshot_id, account_domain, channel, run_id, scoring_version,
               score_json, evidence_json, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (snapshot_id, account["domain"], channel, run_id,
             scoring_version, json.dumps(stored_score, sort_keys=True),
             json.dumps(evidence, sort_keys=True), timestamp),
        )
    return {"snapshot_id": snapshot_id, "account": account, "channel": channel}


def record_send(
    snapshot_id: str,
    *,
    contact_ref: str,
    sent_at: str,
    database_path: Path = DEFAULT_DATABASE_PATH,
) -> dict[str, Any]:
    if not contact_ref.strip():
        raise ValueError("contact_ref is required")
    datetime.fromisoformat(sent_at.replace("Z", "+00:00"))
    send_id = hashlib.sha256(f"{snapshot_id}\0{contact_ref}\0{sent_at}".encode()).hexdigest()
    with connect_database(database_path) as connection:
        if connection.execute("SELECT 1 FROM outreach_snapshots WHERE snapshot_id = ?", (snapshot_id,)).fetchone() is None:
            raise KeyError("unknown outreach snapshot")
        connection.execute(
            "INSERT OR IGNORE INTO outreach_sends(send_id, snapshot_id, contact_ref, sent_at, created_at) VALUES (?, ?, ?, ?, ?)",
            (send_id, snapshot_id, contact_ref, sent_at, _now()),
        )
    return {"send_id": send_id, "snapshot_id": snapshot_id, "sent_at": sent_at}


def _load_outcomes(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))
    if path.suffix.lower() in {".jsonl", ".ndjson"}:
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    raise ValueError("outcomes input must be CSV or JSONL")


def import_outcomes(path: Path, database_path: Path = DEFAULT_DATABASE_PATH) -> dict[str, Any]:
    inserted = 0
    duplicates = 0
    with connect_database(database_path) as connection:
        for index, item in enumerate(_load_outcomes(path)):
            event_type = item.get("event_type")
            if event_type not in VALID_OUTCOMES:
                raise ValueError(f"outcome row {index} has invalid event_type")
            occurred_at = str(item.get("occurred_at", ""))
            datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
            metadata = item.get("metadata", {})
            if isinstance(metadata, str):
                metadata = json.loads(metadata) if metadata else {}
            cursor = connection.execute(
                """INSERT OR IGNORE INTO outreach_outcomes(
                   send_id, event_type, occurred_at, metadata_json, imported_at
                   ) VALUES (?, ?, ?, ?, ?)""",
                (item["send_id"], event_type, occurred_at, json.dumps(metadata, sort_keys=True), _now()),
            )
            inserted += int(bool(cursor.rowcount))
            duplicates += int(not cursor.rowcount)
    return {"inserted": inserted, "duplicates": duplicates, "database": str(database_path)}


def outcome_metrics(database_path: Path = DEFAULT_DATABASE_PATH) -> list[dict[str, Any]]:
    with connect_database(database_path) as connection:
        rows = connection.execute(
            """SELECT s.channel, COUNT(DISTINCT send.send_id) sends,
               COUNT(DISTINCT CASE WHEN o.event_type = 'reply' THEN send.send_id END) replies,
               COUNT(DISTINCT CASE WHEN o.event_type = 'positive_reply' THEN send.send_id END) positive_replies,
               COUNT(DISTINCT CASE WHEN o.event_type = 'meeting' THEN send.send_id END) meetings,
               COUNT(DISTINCT CASE WHEN o.event_type = 'opportunity' THEN send.send_id END) opportunities,
               COUNT(DISTINCT CASE WHEN o.event_type = 'bounce' THEN send.send_id END) bounces,
               COUNT(DISTINCT CASE WHEN o.event_type = 'opt_out' THEN send.send_id END) opt_outs
               FROM outreach_snapshots s
               JOIN outreach_sends send ON send.snapshot_id = s.snapshot_id
               LEFT JOIN outreach_outcomes o ON o.send_id = send.send_id
               GROUP BY s.channel ORDER BY s.channel"""
        ).fetchall()
    metrics = []
    for row in rows:
        item = dict(row)
        sends = item["sends"]
        item.update({
            "reply_rate": round(item["replies"] / sends, 4) if sends else None,
            "positive_reply_rate": round(item["positive_replies"] / sends, 4) if sends else None,
            "meeting_rate": round(item["meetings"] / sends, 4) if sends else None,
            "opportunity_rate": round(item["opportunities"] / sends, 4) if sends else None,
        })
        metrics.append(item)
    return metrics


def signal_outcome_metrics(database_path: Path = DEFAULT_DATABASE_PATH) -> list[dict[str, Any]]:
    """Evaluate downstream outcomes for each frozen signal family."""
    with connect_database(database_path) as connection:
        rows = connection.execute(
            """SELECT send.send_id, s.channel, s.evidence_json, o.event_type
               FROM outreach_sends send
               JOIN outreach_snapshots s ON s.snapshot_id = send.snapshot_id
               LEFT JOIN outreach_outcomes o ON o.send_id = send.send_id"""
        ).fetchall()
    by_send: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row["send_id"], row["channel"])
        entry = by_send.setdefault(key, {"evidence": json.loads(row["evidence_json"]), "events": set()})
        if row["event_type"]:
            entry["events"].add(row["event_type"])
    aggregates: dict[tuple[str, str], dict[str, Any]] = {}
    for (_, channel), item in by_send.items():
        evidence = item["evidence"]
        def identities(values: list[dict[str, Any]]) -> set[str]:
            return {
                str(value.get("signal") or value.get("signal_type") or value.get("id"))
                for value in values
                if value.get("signal") or value.get("signal_type") or value.get("id")
            }
        signals = {
            *(f"fit:{value}" for value in identities(evidence.get("fit", []))),
            *(f"readiness:{value}" for value in identities(evidence.get("readiness", []))),
            *(f"gap:{value}" for value in identities(evidence.get("gap", []))),
            *(f"trigger:{value}" for value in identities(
                evidence.get("reviewed_initiatives", []) + evidence.get("trigger", [])
            )),
        }
        for signal in signals:
            if signal.endswith(":None"):
                continue
            aggregate = aggregates.setdefault((channel, signal), {
                "channel": channel, "signal": signal, "sends": 0,
                "positive_replies": 0, "meetings": 0, "opportunities": 0,
            })
            aggregate["sends"] += 1
            aggregate["positive_replies"] += int("positive_reply" in item["events"])
            aggregate["meetings"] += int("meeting" in item["events"])
            aggregate["opportunities"] += int("opportunity" in item["events"])
    result = []
    for aggregate in aggregates.values():
        sends = aggregate["sends"]
        result.append({
            **aggregate,
            "positive_reply_rate": round(aggregate["positive_replies"] / sends, 4),
            "meeting_rate": round(aggregate["meetings"] / sends, 4),
            "opportunity_rate": round(aggregate["opportunities"] / sends, 4),
        })
    return sorted(result, key=lambda item: (item["channel"], item["signal"]))
