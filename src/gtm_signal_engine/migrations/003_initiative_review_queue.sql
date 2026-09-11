CREATE TABLE initiative_candidates (
    candidate_id TEXT PRIMARY KEY,
    account_domain TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    trigger_relevance TEXT NOT NULL CHECK (trigger_relevance IN ('direct', 'adjacent')),
    url TEXT NOT NULL,
    excerpt TEXT NOT NULL,
    matched_text TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'pending' CHECK (review_status IN ('pending', 'approved', 'rejected')),
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    latest_run_id TEXT NOT NULL,
    latest_content_sha256 TEXT NOT NULL,
    latest_source_date_json TEXT
);

CREATE TABLE initiative_candidate_occurrences (
    candidate_id TEXT NOT NULL REFERENCES initiative_candidates(candidate_id),
    run_id TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    source_date_json TEXT,
    ingested_at TEXT NOT NULL,
    PRIMARY KEY (candidate_id, run_id, content_sha256)
);

CREATE TABLE initiative_candidate_reviews (
    review_id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id TEXT NOT NULL REFERENCES initiative_candidates(candidate_id),
    run_id TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('approve', 'reject')),
    reviewer TEXT NOT NULL,
    notes TEXT NOT NULL,
    strength TEXT CHECK (strength IN ('confirmed', 'likely', 'possible')),
    confidence REAL CHECK (confidence >= 0 AND confidence <= 1),
    reviewed_at TEXT NOT NULL,
    FOREIGN KEY (candidate_id, run_id, content_sha256)
        REFERENCES initiative_candidate_occurrences(candidate_id, run_id, content_sha256)
);

CREATE INDEX initiative_candidates_status_idx
    ON initiative_candidates(review_status, last_seen_at);
CREATE INDEX initiative_candidate_reviews_candidate_idx
    ON initiative_candidate_reviews(candidate_id, review_id);
