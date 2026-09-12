CREATE TABLE paid_gap_candidates (
    candidate_id TEXT PRIMARY KEY,
    account_domain TEXT NOT NULL,
    channel TEXT NOT NULL CHECK(channel IN ('retargeting', 'programmatic')),
    signal_type TEXT NOT NULL,
    suggested_position TEXT NOT NULL CHECK(suggested_position IN ('supports_gap', 'contradicts_gap')),
    url TEXT NOT NULL,
    excerpt TEXT NOT NULL,
    matched_text TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    source_date_json TEXT,
    review_status TEXT NOT NULL DEFAULT 'pending' CHECK(review_status IN ('pending', 'approved', 'rejected')),
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    latest_run_id TEXT NOT NULL,
    latest_content_sha256 TEXT NOT NULL
);

CREATE TABLE paid_gap_candidate_occurrences (
    candidate_id TEXT NOT NULL REFERENCES paid_gap_candidates(candidate_id),
    run_id TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    source_date_json TEXT,
    ingested_at TEXT NOT NULL,
    PRIMARY KEY(candidate_id, run_id, content_sha256)
);

CREATE TABLE paid_gap_candidate_reviews (
    review_id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id TEXT NOT NULL REFERENCES paid_gap_candidates(candidate_id),
    run_id TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    decision TEXT NOT NULL CHECK(decision IN ('approve', 'reject')),
    reviewer TEXT NOT NULL,
    notes TEXT NOT NULL,
    strength TEXT CHECK(strength IN ('confirmed', 'likely', 'possible')),
    confidence REAL CHECK(confidence >= 0 AND confidence <= 1),
    reviewed_at TEXT NOT NULL,
    FOREIGN KEY(candidate_id, run_id, content_sha256)
        REFERENCES paid_gap_candidate_occurrences(candidate_id, run_id, content_sha256)
);

CREATE INDEX paid_gap_candidates_status_idx
ON paid_gap_candidates(review_status, channel, last_seen_at);
