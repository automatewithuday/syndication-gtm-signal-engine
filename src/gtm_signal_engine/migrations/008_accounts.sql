CREATE TABLE accounts (
    account_domain TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    website_url TEXT NOT NULL,
    linkedin_url TEXT,
    linkedin_company_id TEXT,
    prospeo_company_id TEXT,
    crustdata_company_id TEXT,
    crunchbase_url TEXT,
    industry TEXT,
    employee_count INTEGER,
    employee_range TEXT,
    revenue_range TEXT,
    company_type TEXT,
    founded_year INTEGER,
    headquarters_json TEXT,
    enrichment_status TEXT NOT NULL
        CHECK(enrichment_status IN ('completed', 'partial', 'failed')),
    funding_status TEXT NOT NULL,
    enrichment_version TEXT NOT NULL,
    profile_json TEXT NOT NULL,
    field_provenance_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_enriched_at TEXT NOT NULL
);

CREATE TABLE account_enrichment_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    account_domain TEXT NOT NULL REFERENCES accounts(account_domain),
    provider TEXT NOT NULL,
    provider_tool TEXT NOT NULL,
    provider_record_id TEXT,
    response_sha256 TEXT NOT NULL,
    raw_payload_path TEXT NOT NULL,
    billing_json TEXT,
    observed_at TEXT NOT NULL,
    enrichment_version TEXT NOT NULL,
    UNIQUE(account_domain, provider, response_sha256)
);

CREATE INDEX accounts_linkedin_id_idx ON accounts(linkedin_company_id);
CREATE INDEX account_enrichment_snapshots_account_idx
ON account_enrichment_snapshots(account_domain, observed_at);
