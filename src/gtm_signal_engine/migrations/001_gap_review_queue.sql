CREATE TABLE gap_candidates (
    candidate_id TEXT PRIMARY KEY,
    account_domain TEXT NOT NULL,
    channel TEXT NOT NULL CHECK (channel = 'content_syndication'),
    signal_type TEXT NOT NULL,
    suggested_polarity TEXT NOT NULL CHECK (suggested_polarity IN ('supports_gap', 'contradicts_gap')),
    url TEXT NOT NULL,
    excerpt TEXT NOT NULL,
    matched_text TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'pending' CHECK (review_status IN ('pending', 'approved', 'rejected')),
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    latest_run_id TEXT NOT NULL,
    latest_content_sha256 TEXT NOT NULL
);

CREATE TABLE gap_candidate_occurrences (
    candidate_id TEXT NOT NULL REFERENCES gap_candidates(candidate_id),
    run_id TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    PRIMARY KEY (candidate_id, run_id, content_sha256)
);

CREATE TABLE gap_candidate_reviews (
    review_id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id TEXT NOT NULL REFERENCES gap_candidates(candidate_id),
    run_id TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('approve', 'reject')),
    reviewer TEXT NOT NULL,
    notes TEXT NOT NULL,
    strength TEXT CHECK (strength IN ('confirmed', 'likely', 'possible')),
    confidence REAL CHECK (confidence >= 0 AND confidence <= 1),
    reviewed_at TEXT NOT NULL,
    FOREIGN KEY (candidate_id, run_id, content_sha256)
        REFERENCES gap_candidate_occurrences(candidate_id, run_id, content_sha256)
);

CREATE INDEX gap_candidates_status_idx ON gap_candidates(review_status, last_seen_at);
CREATE INDEX gap_candidate_reviews_candidate_idx ON gap_candidate_reviews(candidate_id, review_id);
