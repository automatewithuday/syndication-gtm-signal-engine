CREATE TABLE classification_reviews (
    review_id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_domain TEXT NOT NULL,
    run_id TEXT NOT NULL,
    url TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    original_value_json TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('agree', 'disagree', 'correct')),
    corrected_value_json TEXT,
    reviewer TEXT NOT NULL,
    notes TEXT NOT NULL,
    reviewed_at TEXT NOT NULL
);

CREATE INDEX classification_reviews_lookup_idx
    ON classification_reviews(account_domain, signal_type, reviewed_at);

CREATE TABLE outreach_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    account_domain TEXT NOT NULL,
    channel TEXT NOT NULL,
    run_id TEXT NOT NULL,
    scoring_version TEXT NOT NULL,
    score_json TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE outreach_sends (
    send_id TEXT PRIMARY KEY,
    snapshot_id TEXT NOT NULL REFERENCES outreach_snapshots(snapshot_id),
    contact_ref TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE outreach_outcomes (
    outcome_id INTEGER PRIMARY KEY AUTOINCREMENT,
    send_id TEXT NOT NULL REFERENCES outreach_sends(send_id),
    event_type TEXT NOT NULL CHECK (
        event_type IN ('reply', 'positive_reply', 'meeting', 'opportunity', 'bounce', 'opt_out')
    ),
    occurred_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    UNIQUE(send_id, event_type, occurred_at)
);

CREATE INDEX outreach_outcomes_send_idx ON outreach_outcomes(send_id, occurred_at);
