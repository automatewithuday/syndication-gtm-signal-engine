CREATE TABLE analysis_job_stages (
    job_id TEXT NOT NULL REFERENCES analysis_jobs(job_id),
    stage TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'completed', 'partial', 'failed', 'skipped')),
    detail_json TEXT NOT NULL DEFAULT '{}',
    started_at TEXT,
    finished_at TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (job_id, stage)
);

CREATE INDEX analysis_job_stages_status_idx ON analysis_job_stages(status, updated_at);
