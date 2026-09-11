# Project status

Status as of 2026-09-11. “Complete” means implemented and fixture-tested; it
does not mean the provisional scoring model is calibrated for unattended use.

## Phase 1 — Website intelligence MVP

Complete for the user-selected Scrapling provider: bounded discovery/crawl,
raw-versus-normalized storage, canonical/content-hash deduplication, page/form/
asset classification, freshness, conversion/proof evidence, configurable
content-syndication scoring, SQLite review queues, real DailyPay/ColdIQ
validation, and `crawl-and-analyze` JSON reporting.

The maintained sanitized benchmark currently measures 1.00 asset-family
precision (20/20) and 1.00 gating precision (17/17), including an ambiguous
case returned as unknown. This clears the initial 0.90/0.85 fixture gates but is
not presented as production-population precision.

The optional LLM ambiguity fallback remains intentionally deferred; current
deterministic rules return unknown at ambiguous boundaries.

## Phase 2 — External and campaign signals

Complete at the local contract and recorded-fixture level. First-party campaign
launches, channel/team launches, and marketing hiring are normalized from saved
Scrapling pages and reviewed before trigger scoring. Recorded Apify ad and
Deepline technology payloads normalize into provider-neutral observations;
tracked and canonical destinations, UTM/click identifiers, source dates,
provenance, confidence, and limitations are preserved. Saved Scrapling SERP
results can add campaign pages missed by the internal crawl. Retargeting and
programmatic readiness/gap scores are versioned and configuration-driven.

A native Deepline CLI integration is live-validated against the managed
BuiltWith provider for DailyPay and ColdIQ. It inspects the provider contract
before execution, keeps authentication outside the application, disables PII
and company metadata, retains the raw response and billing metadata, binds the
domain to the exact Scrapling run, and records failures as incomplete. The
resulting technology signals feed versioned `paid_channels_v2` scoring.

The Apify live boundary is implemented, fixture-tested, and live-validated with
pinned LinkedIn and Meta actor builds, asynchronous run IDs, bounded polling,
explicit item/dollar caps, Keychain-only bearer authentication, immutable raw
payloads, exact account attribution, LinkedIn company-ID targeting,
platform-selective correction, and free raw-dataset replay. Ads without a
captured click URL remain valid activity evidence but cannot contribute tracking
evidence. DailyPay has 25 attributable LinkedIn ads and four Meta ads; its
retargeting and programmatic readiness scores are both 80 and provisional-pass.
ColdIQ has 25 attributable LinkedIn ads after switching from name search to its
company ID; retargeting readiness is 80 and programmatic readiness is 70, both
provisional-pass. Gap scores for both accounts remain unknown.

## Phase 3 — Persistence and orchestration

Complete for the approved local-MVP scope. Local files and versioned SQLite
migrations provide idempotent evidence/review/job persistence. Jobs track
attempts, status, run/report paths, failures, and provider cost; deterministic
analysis resumes from an existing crawl. CSV/JSONL batch input, bounded account
concurrency, per-request crawl delay/retry behavior, and qualification-gated
evidence-bundle export are implemented.

Remote Supabase/Postgres is intentionally deferred in line with the user's
decision to use local files and SQLite for now.

## Phase 4 — Validation and learning

Complete as validation infrastructure. Exact-run/content-hash review supports
agree, disagree, and corrected labels. Outreach snapshots freeze evidence and
score versions before an authorized send. CSV/JSONL outcomes support reply,
positive reply, meeting, opportunity, bounce, and opt-out; reporting evaluates
both channel and frozen-signal performance rather than optimizing only replies.
Thresholds remain configurable and explicitly provisional until a meaningful
labeled/outcome sample exists; the system does not fabricate calibration.

## Current real-account decision

DailyPay and ColdIQ both pass provisional fit and content readiness. DailyPay
also pass provisional paid-channel readiness after live ad and technology
collection. Neither account
is qualified as a channel-gap opportunity because verified gap evidence is
absent; absence on the public web or in bounded provider results is kept as
unknown. Review reports are stored inside each authoritative run under
`normalized/account_review.{json,md}`.
