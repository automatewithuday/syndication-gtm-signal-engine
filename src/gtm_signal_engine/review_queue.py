from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .channel_gap import score_channel_gap
from .syndication_scoring import load_scoring_config

DEFAULT_DATABASE_PATH = Path("data/gtm_signal_engine.sqlite3")
VALID_DECISIONS = {"approve", "reject"}
VALID_STRENGTHS = {"confirmed", "likely", "possible"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect_database(path: Path = DEFAULT_DATABASE_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    _apply_migrations(connection)
    return connection


def _apply_migrations(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    migration_root = resources.files("gtm_signal_engine").joinpath("migrations")
    applied = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
    for migration in sorted(
        (item for item in migration_root.iterdir() if item.name.endswith(".sql")),
        key=lambda item: item.name,
    ):
        if migration.name in applied:
            continue
        with connection:
            connection.executescript(migration.read_text(encoding="utf-8"))
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (migration.name, _now()),
            )


def _load_scrapling_run(run_dir: Path) -> tuple[dict[str, Any], str]:
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("provider") != "ScraplingFetcher":
        raise ValueError("review queue requires a ScraplingFetcher run")
    domain = (urlsplit(str(manifest["seed_url"])).hostname or "").lower().removeprefix("www.")
    return manifest, domain


def ingest_gap_candidates(run_dir: Path, database_path: Path = DEFAULT_DATABASE_PATH) -> dict[str, Any]:
    manifest, domain = _load_scrapling_run(run_dir)
    candidates_path = run_dir / "normalized" / "gap_candidates.jsonl"
    if not candidates_path.exists():
        raise FileNotFoundError("gap candidates missing; run discover-gap-candidates first")
    candidates = [json.loads(line) for line in candidates_path.read_bytes().splitlines() if line.strip()]
    inserted = 0
    seen_again = 0
    ingested_at = _now()
    with connect_database(database_path) as connection:
        for candidate in candidates:
            existing = connection.execute(
                "SELECT review_status FROM gap_candidates WHERE candidate_id = ?",
                (candidate["candidate_id"],),
            ).fetchone()
            connection.execute(
                """
                INSERT INTO gap_candidates(
                    candidate_id, account_domain, channel, signal_type, suggested_polarity,
                    url, excerpt, matched_text, extractor_version, source_date_json,
                    first_seen_at, last_seen_at, latest_run_id, latest_content_sha256
                ) VALUES (?, ?, 'content_syndication', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(candidate_id) DO UPDATE SET
                    review_status = CASE
                        WHEN gap_candidates.latest_run_id = excluded.latest_run_id
                         AND gap_candidates.latest_content_sha256 = excluded.latest_content_sha256
                        THEN gap_candidates.review_status
                        ELSE 'pending'
                    END,
                    last_seen_at = excluded.last_seen_at,
                    latest_run_id = excluded.latest_run_id,
                    latest_content_sha256 = excluded.latest_content_sha256,
                    source_date_json = excluded.source_date_json
                """,
                (
                    candidate["candidate_id"], domain, candidate["signal_type"],
                    candidate["suggested_polarity"], candidate["url"], candidate["excerpt"],
                    candidate["matched_text"], candidate["extractor_version"],
                    json.dumps(candidate.get("source_date"), sort_keys=True) if candidate.get("source_date") else None,
                    ingested_at, ingested_at, manifest["run_id"], candidate["content_sha256"],
                ),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO gap_candidate_occurrences(
                    candidate_id, run_id, content_sha256, observed_at, ingested_at
                    , source_date_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate["candidate_id"], manifest["run_id"], candidate["content_sha256"],
                    candidate["observed_at"], ingested_at,
                    json.dumps(candidate.get("source_date"), sort_keys=True) if candidate.get("source_date") else None,
                ),
            )
            if existing:
                seen_again += 1
            else:
                inserted += 1
        status_counts = dict(connection.execute(
            "SELECT review_status, COUNT(*) FROM gap_candidates GROUP BY review_status"
        ).fetchall())
    return {
        "run_id": manifest["run_id"],
        "database": str(database_path),
        "candidates_in_file": len(candidates),
        "inserted": inserted,
        "seen_again": seen_again,
        "status_counts": status_counts,
    }


def list_gap_candidates(
    database_path: Path = DEFAULT_DATABASE_PATH, *, review_status: str | None = None
) -> list[dict[str, Any]]:
    if review_status not in {None, "pending", "approved", "rejected"}:
        raise ValueError("review_status must be pending, approved, or rejected")
    with connect_database(database_path) as connection:
        sql = "SELECT * FROM gap_candidates"
        params: tuple[Any, ...] = ()
        if review_status:
            sql += " WHERE review_status = ?"
            params = (review_status,)
        sql += " ORDER BY last_seen_at DESC, candidate_id"
        return [dict(row) for row in connection.execute(sql, params)]


def review_gap_candidate(
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
            "SELECT * FROM gap_candidates WHERE candidate_id = ?", (candidate_id,)
        ).fetchone()
        if candidate is None:
            raise KeyError(f"candidate not found: {candidate_id}")
        reviewed_at = _now()
        connection.execute(
            """
            INSERT INTO gap_candidate_reviews(
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
            "UPDATE gap_candidates SET review_status = ? WHERE candidate_id = ?",
            (status, candidate_id),
        )
        return {
            "candidate_id": candidate_id,
            "run_id": candidate["latest_run_id"],
            "content_sha256": candidate["latest_content_sha256"],
            "review_status": status,
            "reviewed_at": reviewed_at,
        }


def export_gap_profile(
    run_dir: Path,
    *,
    account_name: str,
    database_path: Path = DEFAULT_DATABASE_PATH,
    output_path: Path | None = None,
) -> dict[str, Any]:
    manifest, domain = _load_scrapling_run(run_dir)
    pages_path = run_dir / "normalized" / "pages.jsonl"
    pages = {
        item["url"]: item
        for line in pages_path.read_bytes().splitlines()
        if line.strip()
        for item in [json.loads(line)]
    }
    with connect_database(database_path) as connection:
        rows = connection.execute(
            """
            SELECT c.*, o.observed_at, o.content_sha256 AS occurrence_content_sha256,
                   o.source_date_json AS occurrence_source_date_json,
                   r.strength, r.confidence
            FROM gap_candidates c
            JOIN gap_candidate_occurrences o
             ON o.candidate_id = c.candidate_id
             AND o.run_id = ?
            JOIN gap_candidate_reviews r
              ON r.review_id = (
                  SELECT MAX(r2.review_id)
                  FROM gap_candidate_reviews r2
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
            "polarity": row["suggested_polarity"],
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
        "channel": "content_syndication",
        "observations": observations,
        "risks": ["Approved observations remain subject to the provisional gap scoring configuration."],
    }
    config, _, _ = load_scoring_config()
    score_channel_gap(profile, pages, config)
    selected_output = output_path or run_dir / "normalized" / "reviewed_gap_profile.json"
    selected_output.parent.mkdir(parents=True, exist_ok=True)
    selected_output.write_text(json.dumps(profile, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "run_id": manifest["run_id"],
        "database": str(database_path),
        "output": str(selected_output),
        "approved_observations": len(observations),
    }
