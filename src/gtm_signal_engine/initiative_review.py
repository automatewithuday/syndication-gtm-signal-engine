from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .review_queue import DEFAULT_DATABASE_PATH, VALID_DECISIONS, VALID_STRENGTHS, _load_scrapling_run, _now, connect_database


def ingest_initiative_candidates(
    run_dir: Path, database_path: Path = DEFAULT_DATABASE_PATH
) -> dict[str, Any]:
    manifest, domain = _load_scrapling_run(run_dir)
    candidates_path = run_dir / "normalized" / "initiative_candidates.jsonl"
    if not candidates_path.exists():
        raise FileNotFoundError("initiative candidates missing; run discover-initiative-candidates first")
    candidates = [json.loads(line) for line in candidates_path.read_bytes().splitlines() if line.strip()]
    inserted = 0
    seen_again = 0
    ingested_at = _now()
    with connect_database(database_path) as connection:
        for candidate in candidates:
            existing = connection.execute(
                "SELECT review_status FROM initiative_candidates WHERE candidate_id = ?",
                (candidate["candidate_id"],),
            ).fetchone()
            source_date_json = (
                json.dumps(candidate["source_date"], sort_keys=True)
                if candidate.get("source_date") else None
            )
            connection.execute(
                """
                INSERT INTO initiative_candidates(
                    candidate_id, account_domain, signal_type, trigger_relevance,
                    url, excerpt, matched_text, extractor_version, first_seen_at,
                    last_seen_at, latest_run_id, latest_content_sha256,
                    latest_source_date_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(candidate_id) DO UPDATE SET
                    review_status = CASE
                        WHEN initiative_candidates.latest_run_id = excluded.latest_run_id
                         AND initiative_candidates.latest_content_sha256 = excluded.latest_content_sha256
                        THEN initiative_candidates.review_status
                        ELSE 'pending'
                    END,
                    last_seen_at = excluded.last_seen_at,
                    latest_run_id = excluded.latest_run_id,
                    latest_content_sha256 = excluded.latest_content_sha256,
                    latest_source_date_json = excluded.latest_source_date_json
                """,
                (
                    candidate["candidate_id"], domain, candidate["signal_type"],
                    candidate["trigger_relevance"], candidate["url"], candidate["excerpt"],
                    candidate["matched_text"], candidate["extractor_version"], ingested_at,
                    ingested_at, manifest["run_id"], candidate["content_sha256"], source_date_json,
                ),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO initiative_candidate_occurrences(
                    candidate_id, run_id, content_sha256, observed_at,
                    source_date_json, ingested_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate["candidate_id"], manifest["run_id"], candidate["content_sha256"],
                    candidate["observed_at"], source_date_json, ingested_at,
                ),
            )
            if existing:
                seen_again += 1
            else:
                inserted += 1
        status_counts = dict(connection.execute(
            "SELECT review_status, COUNT(*) FROM initiative_candidates GROUP BY review_status"
        ).fetchall())
    return {
        "run_id": manifest["run_id"],
        "database": str(database_path),
        "candidates_in_file": len(candidates),
        "inserted": inserted,
        "seen_again": seen_again,
        "status_counts": status_counts,
    }


def list_initiative_candidates(
    database_path: Path = DEFAULT_DATABASE_PATH, *, review_status: str | None = None
) -> list[dict[str, Any]]:
    if review_status not in {None, "pending", "approved", "rejected"}:
        raise ValueError("review_status must be pending, approved, or rejected")
    with connect_database(database_path) as connection:
        sql = "SELECT * FROM initiative_candidates"
        params: tuple[Any, ...] = ()
        if review_status:
            sql += " WHERE review_status = ?"
            params = (review_status,)
        sql += " ORDER BY last_seen_at DESC, candidate_id"
        return [dict(row) for row in connection.execute(sql, params)]


def review_initiative_candidate(
    candidate_id: str,
    *,
    decision: str,
    reviewer: str,
    notes: str,
    database_path: Path = DEFAULT_DATABASE_PATH,
    strength: str | None = None,
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
            "SELECT * FROM initiative_candidates WHERE candidate_id = ?", (candidate_id,)
        ).fetchone()
        if candidate is None:
            raise KeyError(f"candidate not found: {candidate_id}")
        reviewed_at = _now()
        connection.execute(
            """
            INSERT INTO initiative_candidate_reviews(
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
            "UPDATE initiative_candidates SET review_status = ? WHERE candidate_id = ?",
            (status, candidate_id),
        )
        return {
            "candidate_id": candidate_id,
            "run_id": candidate["latest_run_id"],
            "content_sha256": candidate["latest_content_sha256"],
            "review_status": status,
            "reviewed_at": reviewed_at,
        }


def export_trigger_profile(
    run_dir: Path,
    *,
    account_name: str,
    database_path: Path = DEFAULT_DATABASE_PATH,
    output_path: Path | None = None,
) -> dict[str, Any]:
    manifest, domain = _load_scrapling_run(run_dir)
    with connect_database(database_path) as connection:
        rows = connection.execute(
            """
            SELECT c.*, o.observed_at, o.content_sha256 AS occurrence_content_sha256,
                   o.source_date_json AS occurrence_source_date_json,
                   r.strength, r.confidence
            FROM initiative_candidates c
            JOIN initiative_candidate_occurrences o
              ON o.candidate_id = c.candidate_id AND o.run_id = ?
            JOIN initiative_candidate_reviews r
              ON r.review_id = (
                  SELECT MAX(r2.review_id)
                  FROM initiative_candidate_reviews r2
                  WHERE r2.candidate_id = c.candidate_id
                    AND r2.run_id = o.run_id
                    AND r2.content_sha256 = o.content_sha256
              )
            WHERE c.account_domain = ? AND r.decision = 'approve'
            ORDER BY c.candidate_id
            """,
            (manifest["run_id"], domain),
        ).fetchall()
    observations = []
    for row in rows:
        observation = {
            "signal_type": row["signal_type"],
            "trigger_relevance": row["trigger_relevance"],
            "strength": row["strength"],
            "confidence": row["confidence"],
            "url": row["url"],
            "excerpt": row["excerpt"],
            "observed_at": row["observed_at"],
            "method": "scrapling_saved_page",
            "content_sha256": row["occurrence_content_sha256"],
        }
        if row["occurrence_source_date_json"]:
            observation["source_date"] = json.loads(row["occurrence_source_date_json"])
        observations.append(observation)
    profile = {
        "account": {"name": account_name, "domain": domain},
        "kind": "business_trigger",
        "observations": observations,
        "risks": ["Reviewed initiative evidence establishes timing context, not a channel gap."],
    }
    selected_output = output_path or run_dir / "normalized" / "reviewed_trigger_profile.json"
    selected_output.parent.mkdir(parents=True, exist_ok=True)
    selected_output.write_text(json.dumps(profile, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "run_id": manifest["run_id"],
        "database": str(database_path),
        "output": str(selected_output),
        "approved_observations": len(observations),
    }
