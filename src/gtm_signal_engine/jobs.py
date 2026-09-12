from __future__ import annotations

import csv
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from .collector import normalize_seed
from .review_queue import DEFAULT_DATABASE_PATH, connect_database
from .workflow import analyze_saved_run, crawl_and_analyze
from .account_pipeline import run_account_v1
from .company_enrichment import enrich_company
from .job_collection import collect_deepline_jobs

JobRunner = Callable[..., dict[str, Any]]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request(record: dict[str, Any]) -> dict[str, Any]:
    seed = normalize_seed(str(record["domain"]))
    domain = (urlsplit(seed).hostname or "").removeprefix("www.")
    raw_skips = record.get("skip_ad_platforms") or record.get("skip_ad_platform") or ""
    skip_ad_platforms = [
        value.strip().lower() for value in str(raw_skips).split(",") if value.strip()
    ]
    if set(skip_ad_platforms).difference({"meta", "linkedin", "google"}):
        raise ValueError("skip_ad_platforms must be a comma-separated subset of meta, linkedin, google")
    return {
        "domain": domain,
        "account_name": str(record.get("account_name") or domain),
        "maximum_pages": int(record.get("maximum_pages") or 100),
        "maximum_sitemaps": int(record.get("maximum_sitemaps") or 20),
        "delay_seconds": float(record.get("delay_seconds") or 0.25),
        "linkedin_company_id": str(record.get("linkedin_company_id") or "") or None,
        "apify_fallback": str(record.get("apify_fallback", "true")).strip().lower() not in {"0", "false", "no"},
        "skip_ad_platforms": list(dict.fromkeys(skip_ad_platforms)),
    }


def _job_id(request: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(request, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load_batch(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8") as handle:
            records = list(csv.DictReader(handle))
    elif path.suffix.lower() in {".jsonl", ".ndjson"}:
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    else:
        raise ValueError("batch input must be CSV or JSONL")
    if not records or any(not item.get("domain") for item in records):
        raise ValueError("batch input requires at least one row with domain")
    return records


def enqueue_batch(path: Path, database_path: Path = DEFAULT_DATABASE_PATH) -> dict[str, Any]:
    inserted = 0
    existing = 0
    job_ids: list[str] = []
    with connect_database(database_path) as connection:
        for record in load_batch(path):
            request = _request(record)
            job_id = _job_id(request)
            timestamp = _now()
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO analysis_jobs(
                    job_id, account_domain, account_name, request_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (job_id, request["domain"], request["account_name"], json.dumps(request, sort_keys=True), timestamp, timestamp),
            )
            if cursor.rowcount:
                inserted += 1
                connection.execute(
                    "INSERT INTO analysis_job_events(job_id, status, detail_json, created_at) VALUES (?, 'pending', '{}', ?)",
                    (job_id, timestamp),
                )
            else:
                existing += 1
            job_ids.append(job_id)
    return {"database": str(database_path), "inserted": inserted, "existing": existing, "job_ids": job_ids}


def list_jobs(database_path: Path = DEFAULT_DATABASE_PATH, *, status: str | None = None) -> list[dict[str, Any]]:
    with connect_database(database_path) as connection:
        if status:
            rows = connection.execute(
                "SELECT * FROM analysis_jobs WHERE status = ? ORDER BY created_at", (status,)
            ).fetchall()
        else:
            rows = connection.execute("SELECT * FROM analysis_jobs ORDER BY created_at").fetchall()
    return [{**dict(row), "request": json.loads(row["request_json"])} for row in rows]


def run_job(
    job_id: str,
    *,
    database_path: Path = DEFAULT_DATABASE_PATH,
    output_root: Path = Path("data/runs"),
    report_root: Path = Path("reports"),
    runner: JobRunner | None = None,
) -> dict[str, Any]:
    with connect_database(database_path) as connection:
        row = connection.execute("SELECT * FROM analysis_jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown analysis job: {job_id}")
        if row["status"] == "completed":
            return {"job_id": job_id, "status": "completed", "skipped": True, "report_path": row["report_path"]}
        timestamp = _now()
        connection.execute(
            "UPDATE analysis_jobs SET status = 'running', attempts = attempts + 1, last_error = NULL, updated_at = ? WHERE job_id = ?",
            (timestamp, job_id),
        )
        connection.execute(
            "INSERT INTO analysis_job_events(job_id, status, detail_json, created_at) VALUES (?, 'running', '{}', ?)",
            (job_id, timestamp),
        )
        request = json.loads(row["request_json"])
        prior_run_dir = Path(row["run_dir"]) if row["run_dir"] else None

    report_path = report_root / f"{job_id}.json"
    try:
        def stage_callback(stage: str, status: str, detail: dict[str, Any]) -> None:
            timestamp = _now()
            with connect_database(database_path) as connection:
                previous = connection.execute(
                    "SELECT started_at FROM analysis_job_stages WHERE job_id = ? AND stage = ?",
                    (job_id, stage),
                ).fetchone()
                started_at = previous["started_at"] if previous else timestamp
                finished_at = timestamp if status in {"completed", "partial", "failed", "skipped"} else None
                connection.execute(
                    """INSERT INTO analysis_job_stages(job_id, stage, status, detail_json, started_at, finished_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(job_id, stage) DO UPDATE SET status=excluded.status,
                       detail_json=excluded.detail_json, finished_at=excluded.finished_at, updated_at=excluded.updated_at""",
                    (job_id, stage, status, json.dumps(detail, sort_keys=True), started_at, finished_at, timestamp),
                )

        if runner is None:
            report = run_account_v1(
                request["domain"], account_name=request["account_name"], output_root=output_root,
                report_path=report_path, run_dir=prior_run_dir,
                maximum_pages=request["maximum_pages"], maximum_sitemaps=request["maximum_sitemaps"],
                delay_seconds=request["delay_seconds"], linkedin_company_id=request.get("linkedin_company_id"),
                apify_fallback=request.get("apify_fallback", True), stage_callback=stage_callback,
                skip_ad_platforms=tuple(request.get("skip_ad_platforms", ())),
                jobs_collector=collect_deepline_jobs, company_enricher=enrich_company,
                database_path=database_path,
            )
            final_status = report["pipeline"]["status"]
            run_dir = report["run"]["run_dir"]
            provider_cost = float(report["provider_cost"]["usd"])
        elif prior_run_dir and (prior_run_dir / "manifest.json").is_file():
            report = analyze_saved_run(
                prior_run_dir, output_path=report_path, account_name=request["account_name"]
            )
            final_status = "completed" if report["run"]["status"] == "completed" else "partial"
            run_dir = report["run_dir"]
            provider_cost = float(report["run"].get("provider_cost_usd", 0))
        else:
            report = runner(
                request["domain"], output_path=report_path, output_root=output_root,
                account_name=request["account_name"], maximum_pages=request["maximum_pages"],
                maximum_sitemaps=request["maximum_sitemaps"], delay_seconds=request["delay_seconds"],
            )
            final_status = "completed" if report["run"]["status"] == "completed" else "partial"
            run_dir = report["run_dir"]
            provider_cost = float(report["run"].get("provider_cost_usd", 0))
        timestamp = _now()
        with connect_database(database_path) as connection:
            connection.execute(
                """UPDATE analysis_jobs SET status = ?, run_dir = ?, report_path = ?,
                   provider_cost_usd = ?, updated_at = ? WHERE job_id = ?""",
                (final_status, run_dir, str(report_path), provider_cost, timestamp, job_id),
            )
            connection.execute(
                "INSERT INTO analysis_job_events(job_id, status, detail_json, created_at) VALUES (?, ?, ?, ?)",
                (job_id, final_status, json.dumps({"run_dir": run_dir, "report_path": str(report_path)}), timestamp),
            )
        return {"job_id": job_id, "status": final_status, "run_dir": run_dir, "report_path": str(report_path)}
    except Exception as exc:
        timestamp = _now()
        with connect_database(database_path) as connection:
            connection.execute(
                "UPDATE analysis_jobs SET status = 'failed', last_error = ?, updated_at = ? WHERE job_id = ?",
                (f"{type(exc).__name__}: {exc}", timestamp, job_id),
            )
            connection.execute(
                "INSERT INTO analysis_job_events(job_id, status, detail_json, created_at) VALUES (?, 'failed', ?, ?)",
                (job_id, json.dumps({"error": f"{type(exc).__name__}: {exc}"}), timestamp),
            )
        raise


def run_pending_jobs(
    *,
    database_path: Path = DEFAULT_DATABASE_PATH,
    output_root: Path = Path("data/runs"),
    report_root: Path = Path("reports"),
    workers: int = 1,
) -> list[dict[str, Any]]:
    if workers < 1 or workers > 8:
        raise ValueError("workers must be between 1 and 8")
    job_ids = [item["job_id"] for item in list_jobs(database_path, status="pending")]
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                run_job, job_id, database_path=database_path, output_root=output_root, report_root=report_root
            ): job_id
            for job_id in job_ids
        }
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:
                results.append({"job_id": futures[future], "status": "failed", "error": f"{type(exc).__name__}: {exc}"})
    return sorted(results, key=lambda item: item["job_id"])
