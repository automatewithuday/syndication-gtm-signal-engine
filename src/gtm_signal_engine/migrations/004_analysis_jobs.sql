CREATE TABLE analysis_jobs (
    job_id TEXT PRIMARY KEY,
    account_domain TEXT NOT NULL,
    account_name TEXT NOT NULL,
    request_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'partial', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    run_dir TEXT,
    report_path TEXT,
    provider_cost_usd REAL NOT NULL DEFAULT 0 CHECK (provider_cost_usd >= 0),
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX analysis_jobs_status_idx ON analysis_jobs(status, updated_at);

CREATE TABLE analysis_job_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES analysis_jobs(job_id),
    status TEXT NOT NULL,
    detail_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX analysis_job_events_job_idx ON analysis_job_events(job_id, event_id);
