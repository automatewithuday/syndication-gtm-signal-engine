# Data model

## Core tables

### `accounts`

Canonical company identity and slow-changing firmographics.

### `analysis_runs`

One account analysis attempt: start/end time, configuration version, code version, status, provider cost, and errors.

### `provider_observations`

Pointers to raw provider responses with provider, query, observed time, checksum, and expiry. Avoid copying raw vendor schemas into core tables.

### `website_pages`

Canonical URL, original URL, title, publication/update dates, content hash, page type, first/last seen times, and raw-content pointer.

### `evidence`

`account_id`, `run_id`, `page_id`, `signal_type`, typed value, evidence strength, confidence, URL, excerpt, observed time, method, extractor version, and optional expiry.

### `content_assets`

Normalized reports, ebooks, guides, white papers, webinars, research, and case studies. Include asset type, topic, funnel stage, personas, industries, gating type, dates, landing URL, asset URL, and syndication suitability.

### `conversion_paths`

Source page, CTA text/type, destination, form/scheduler/signup type, field count, conversion tool, and friction score.

### `campaign_urls`

Observed destination URL, canonical landing page, platform, creative ID, UTM parameters, click identifiers, first/last observed times.

### `ad_creative_analysis`

Versioned run artifact containing provider inventory totals, inspected-row and
usable-text coverage, normalized advertiser/copy/CTA/format/media fields,
creative fingerprints, evidence lineage, deterministic funnel/offer/audience/
theme classifications, and per-creative activity state. Provider totals are
inventory rather than proof of current activity. Raw provider payloads remain
outside this model and are referenced by path and SHA-256.

### `opportunity_scores`

Channel, fit, readiness, gap, trigger, total, confidence, scoring version, reasons, risks, and evidence snapshot ID.

### `unified_account_scores`

Immutable account-priority snapshots keyed by account and run. Each row stores
the configuration version, scoring-logic version, six-signal result, priority
score, evidence coverage, confidence, qualification state, and stable snapshot
ID. The JSON result retains the upstream artifact identities; raw provider
payloads remain outside this table.

### `gap_target_plan.json`

Run-local, provider-neutral acquisition plan containing canonical same-domain
targets, deterministic priority/category, source and reason, fetched state,
prior attempt count, last error, selection state, planner version, logical input
hashes, and snapshot ID. Saved search inputs must identify Scrapling as their
collection method. Processing timestamps are excluded from logical identity.

### `gap_evidence_acquisition.json`

Run-local acquisition outcome linking the exact plan snapshot to the targeted
Scrapling collection and downstream gap-resolution summary. `no_targets` and
`partial` are coverage states, not negative channel evidence. Version 2 marks
when resolution is deferred to the account pipeline's single resolver stage.

### `gap_candidates`

Stable candidate identity, account/channel, proposed signal and polarity,
source URL/excerpt, extractor version, current review status, and first/latest
seen metadata. Re-ingestion updates recency without resetting a decision.

### `gap_candidate_occurrences`

The exact run ID, page content hash, observation time, and ingestion time for
each appearance of a candidate. This separates a stable candidate from the
versioned page snapshots where it appeared.

### `gap_candidate_reviews`

Append-only approve/reject decisions with reviewer, notes, decision time, and
approval strength/confidence. A review references the exact candidate
occurrence so later page changes cannot inherit approval.

### `initiative_candidates`

Stable campaign, hiring, or new-channel candidate identity with account,
signal type, trigger relevance, source excerpt, extractor version, and review
status. These records are never channel-gap evidence.

### `initiative_candidate_occurrences`

The exact run, page content hash, observation time, and attributable source-date
metadata for each appearance of an initiative candidate.

### `initiative_candidate_reviews`

Append-only decisions bound to a specific occurrence. Approvals include an
explicit evidence strength and reviewer confidence before trigger scoring.

### `outcomes`

Outreach event and business outcome tied to the exact opportunity-score snapshot used. This prevents current website state from being incorrectly attributed to historical outreach.

### `analysis_jobs` and `analysis_job_events`

Idempotent local account requests plus append-only execution transitions.
Records attempts, saved run/report paths, partial/failure state, and provider
cost so deterministic analysis can resume from an existing crawl.

### `analysis_job_stages`

One current checkpoint per job and pipeline stage, with status, JSON detail,
start/end time, and last update. This mirrors the run-local
`normalized/account_pipeline.json` state into SQLite and makes interrupted
provider workflows auditable and resumable.

### `account_portfolio.{json,csv,md}`

Provider-free derived views over the latest persisted job for each canonical
domain. They retain job/report availability, priority score, evidence coverage,
confidence, channel statuses, blockers, cost, and historical-job count. The
snapshot hash excludes output paths and generation time. Priority ordering does
not override channel qualification.

### `classification_reviews`

Agree/disagree/correct decisions bound to an exact run, page URL, content hash,
signal type, original value, reviewer, and rationale.

### `outreach_snapshots`, `outreach_sends`, and `outreach_outcomes`

Immutable score/evidence snapshots at send time, idempotent send references,
and downstream events used for channel- and signal-level validation.

## Evidence state

- `confirmed`: direct positive evidence.
- `likely`: multiple or strong indirect observations.
- `possible`: weak but relevant indication.
- `unknown`: insufficient evidence either way.
- `contradicted`: positive evidence conflicts with the proposed gap.

Never convert `unknown` into a positive gap merely because a provider returned no result.
