from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .review_queue import (
    DEFAULT_DATABASE_PATH,
    VALID_DECISIONS,
    VALID_STRENGTHS,
    _load_scrapling_run,
    _now,
    connect_database,
)


def ingest_paid_gap_candidates(
    run_dir: Path, database_path: Path = DEFAULT_DATABASE_PATH
) -> dict[str, Any]:
    manifest, domain = _load_scrapling_run(run_dir)
    candidates_path = run_dir / "normalized" / "paid_gap_candidates.jsonl"
    if not candidates_path.exists():
        raise FileNotFoundError("paid gap candidates missing; run discover-paid-gap-candidates first")
    candidates = [json.loads(line) for line in candidates_path.read_bytes().splitlines() if line.strip()]
    inserted = 0
    seen_again = 0
    ingested_at = _now()
    with connect_database(database_path) as connection:
        for candidate in candidates:
            existing = connection.execute(
                "SELECT review_status FROM paid_gap_candidates WHERE candidate_id = ?",
                (candidate["candidate_id"],),
            ).fetchone()
            connection.execute(
                """
                INSERT INTO paid_gap_candidates(
                    candidate_id, account_domain, channel, signal_type, suggested_position,
                    url, excerpt, matched_text, extractor_version, source_date_json,
                    first_seen_at, last_seen_at, latest_run_id, latest_content_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(candidate_id) DO UPDATE SET
                    review_status = CASE
                        WHEN paid_gap_candidates.latest_run_id = excluded.latest_run_id
                         AND paid_gap_candidates.latest_content_sha256 = excluded.latest_content_sha256
                        THEN paid_gap_candidates.review_status ELSE 'pending' END,
                    last_seen_at = excluded.last_seen_at,
                    latest_run_id = excluded.latest_run_id,
                    latest_content_sha256 = excluded.latest_content_sha256,
                    source_date_json = excluded.source_date_json
                """,
                (
                    candidate["candidate_id"], domain, candidate["channel"], candidate["signal_type"],
                    candidate["suggested_position"], candidate["url"], candidate["excerpt"],
                    candidate["matched_text"], candidate["extractor_version"],
                    json.dumps(candidate.get("source_date"), sort_keys=True) if candidate.get("source_date") else None,
                    ingested_at, ingested_at, manifest["run_id"], candidate["content_sha256"],
                ),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO paid_gap_candidate_occurrences(
                    candidate_id, run_id, content_sha256, observed_at, source_date_json, ingested_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate["candidate_id"], manifest["run_id"], candidate["content_sha256"],
                    candidate["observed_at"],
                    json.dumps(candidate.get("source_date"), sort_keys=True) if candidate.get("source_date") else None,
                    ingested_at,
                ),
            )
            seen_again += int(existing is not None)
            inserted += int(existing is None)
        counts = dict(connection.execute(
            "SELECT review_status, COUNT(*) FROM paid_gap_candidates GROUP BY review_status"
        ).fetchall())
    return {
        "run_id": manifest["run_id"], "database": str(database_path),
        "candidates_in_file": len(candidates), "inserted": inserted,
        "seen_again": seen_again, "status_counts": counts,
    }


def list_paid_gap_candidates(
    database_path: Path = DEFAULT_DATABASE_PATH, *, review_status: str | None = None,
    channel: str | None = None,
) -> list[dict[str, Any]]:
    if review_status not in {None, "pending", "approved", "rejected"}:
        raise ValueError("review_status must be pending, approved, or rejected")
    if channel not in {None, "retargeting", "programmatic"}:
        raise ValueError("channel must be retargeting or programmatic")
    clauses: list[str] = []
    params: list[str] = []
    if review_status:
        clauses.append("review_status = ?")
        params.append(review_status)
    if channel:
        clauses.append("channel = ?")
        params.append(channel)
    sql = "SELECT * FROM paid_gap_candidates"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY last_seen_at DESC, candidate_id"
    with connect_database(database_path) as connection:
        return [dict(row) for row in connection.execute(sql, tuple(params))]


def review_paid_gap_candidate(
    candidate_id: str, *, decision: str, reviewer: str, notes: str,
    database_path: Path = DEFAULT_DATABASE_PATH, strength: str | None = None,
    confidence: float | None = None,
) -> dict[str, Any]:
    if decision not in VALID_DECISIONS:
        raise ValueError("decision must be approve or reject")
    if not reviewer.strip() or not notes.strip():
        raise ValueError("reviewer and notes are required")
    if decision == "approve":
        if strength not in VALID_STRENGTHS:
            raise ValueError("approved candidates require confirmed, likely, or possible strength")
        if confidence is None or not 0 <= confidence <= 1:
            raise ValueError("approved candidates require confidence between 0 and 1")
    elif strength is not None or confidence is not None:
        raise ValueError("strength and confidence apply only to approvals")
    with connect_database(database_path) as connection:
        candidate = connection.execute(
            "SELECT * FROM paid_gap_candidates WHERE candidate_id = ?", (candidate_id,)
        ).fetchone()
        if candidate is None:
            raise KeyError(f"candidate not found: {candidate_id}")
        reviewed_at = _now()
        connection.execute(
            """
            INSERT INTO paid_gap_candidate_reviews(
                candidate_id, run_id, content_sha256, decision, reviewer, notes,
                strength, confidence, reviewed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate_id, candidate["latest_run_id"], candidate["latest_content_sha256"],
                decision, reviewer.strip(), notes.strip(), strength, confidence, reviewed_at,
            ),
        )
        status = "approved" if decision == "approve" else "rejected"
        connection.execute(
            "UPDATE paid_gap_candidates SET review_status = ? WHERE candidate_id = ?",
            (status, candidate_id),
        )
    return {
        "candidate_id": candidate_id, "run_id": candidate["latest_run_id"],
        "content_sha256": candidate["latest_content_sha256"],
        "review_status": status, "reviewed_at": reviewed_at,
    }


def export_paid_gap_profile(
    run_dir: Path, *, account_name: str, database_path: Path = DEFAULT_DATABASE_PATH,
    output_path: Path | None = None,
) -> dict[str, Any]:
    manifest, domain = _load_scrapling_run(run_dir)
    pages = [
        json.loads(line) for line in (run_dir / "normalized" / "pages.jsonl").read_bytes().splitlines()
        if line.strip()
    ]
    exact_pages = {(item["url"], item["content_hash"]): item for item in pages}
    with connect_database(database_path) as connection:
        rows = connection.execute(
            """
            SELECT c.*, o.observed_at, o.content_sha256 AS occurrence_content_sha256,
                   o.source_date_json AS occurrence_source_date_json,
                   r.strength, r.confidence
            FROM paid_gap_candidates c
            JOIN paid_gap_candidate_occurrences o
              ON o.candidate_id = c.candidate_id AND o.run_id = ?
            JOIN paid_gap_candidate_reviews r ON r.review_id = (
                SELECT MAX(r2.review_id) FROM paid_gap_candidate_reviews r2
                WHERE r2.candidate_id = c.candidate_id AND r2.run_id = o.run_id
                  AND r2.content_sha256 = o.content_sha256
            )
            WHERE c.account_domain = ? AND r.decision = 'approve'
            ORDER BY c.candidate_id
            """,
            (manifest["run_id"], domain),
        ).fetchall()
    observations: list[dict[str, Any]] = []
    for row in rows:
        page = exact_pages.get((row["url"], row["occurrence_content_sha256"]))
        if page is None:
            raise ValueError(f"approved evidence no longer binds to an exact saved page: {row['candidate_id']}")
        compact_text = " ".join((page.get("main_text") or page.get("text") or "").split())
        if " ".join(row["matched_text"].split()) not in compact_text:
            raise ValueError(f"approved evidence text is not present in the saved page: {row['candidate_id']}")
        observation = {
            "channel": row["channel"], "position": row["suggested_position"],
            "signal_type": row["signal_type"], "strength": row["strength"],
            "url": row["url"], "excerpt": row["excerpt"],
            "observed_at": row["observed_at"], "confidence": row["confidence"],
            "review_status": "approved", "method": "scrapling_saved_page",
            "content_sha256": row["occurrence_content_sha256"],
        }
        if row["occurrence_source_date_json"]:
            observation["source_date"] = json.loads(row["occurrence_source_date_json"])
        observations.append(observation)
    selected_output = output_path or run_dir / "normalized" / "external_profile.json"
    profile = json.loads(selected_output.read_text(encoding="utf-8")) if selected_output.is_file() else {
        "schema_version": "1.0", "domain": domain, "technologies": [], "ads": []
    }
    existing = [
        item for item in profile.get("gap_observations", [])
        if item.get("channel") not in {"retargeting", "programmatic"}
    ]
    profile["gap_observations"] = [*existing, *observations]
    profile["account_name"] = profile.get("account_name") or account_name
    selected_output.parent.mkdir(parents=True, exist_ok=True)
    selected_output.write_text(json.dumps(profile, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "run_id": manifest["run_id"], "database": str(database_path),
        "output": str(selected_output), "approved_observations": len(observations),
    }
