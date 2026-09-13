CREATE TABLE unified_account_scores (
    snapshot_id TEXT PRIMARY KEY,
    account_domain TEXT NOT NULL REFERENCES accounts(account_domain),
    run_id TEXT NOT NULL,
    scoring_version TEXT NOT NULL,
    priority_score REAL,
    evidence_coverage REAL NOT NULL,
    confidence REAL NOT NULL,
    priority_status TEXT NOT NULL,
    opportunity_status TEXT NOT NULL,
    result_json TEXT NOT NULL,
    scored_at TEXT NOT NULL,
    UNIQUE(account_domain, run_id, scoring_version, snapshot_id)
);

CREATE INDEX unified_account_scores_account_idx
ON unified_account_scores(account_domain, scored_at);

CREATE INDEX unified_account_scores_run_idx
ON unified_account_scores(run_id, scoring_version);
