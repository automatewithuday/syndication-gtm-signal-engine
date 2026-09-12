# Project status

Status as of 2026-09-13. “Complete” means implemented and fixture-tested; it
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
launches, channel/team launches, demand-generation/paid-media hiring, broader
marketing hiring, and funding rounds are normalized from saved
Scrapling pages and reviewed before trigger scoring. Recorded Apify ad and
Deepline technology payloads normalize into provider-neutral observations;
tracked and canonical destinations, UTM/click identifiers, source dates,
provenance, confidence, and limitations are preserved. Saved Scrapling SERP
results can add campaign pages missed by the internal crawl. Retargeting and
programmatic readiness/gap scores are versioned and configuration-driven. V3
requires two distinct reviewed positive gap signal types; explicit evidence of
a healthy channel disqualifies the gap, and absence stays unknown. Paid-gap
candidates use a separate exact-provenance SQLite review queue.

A native Deepline CLI integration is live-validated against the managed
BuiltWith provider for DailyPay and ColdIQ. It inspects the provider contract
before execution, keeps authentication outside the application, disables PII
and company metadata, retains the raw response and billing metadata, binds the
domain to the exact Scrapling run, and records failures as incomplete. The
resulting technology signals feed versioned paid-channel scoring. V1 and V2
remain available for historical replay.

The Deepline/Adyntel ads boundary is now the primary provider-neutral path for
Meta, LinkedIn, and Google. It performs one paid call per selected channel,
persists immutable provider envelopes and hashes, records billing/job IDs and
provider-reported totals, and marks first-page or empty-payload results partial
or inconclusive. Inconclusive replacement data never erases prior evidence.
Live validation records ColdIQ totals of 214 LinkedIn and 44 Google ads, with
24 and ten normalized first-page rows; its Meta response remains inconclusive.
DailyPay records totals of 16 Meta, 318 LinkedIn, and 200 Google ads, with ten
normalized first-page rows for each channel.

The first Adyntel creative-analysis layer is also complete. It hash-verifies
the saved provider envelopes, joins raw creative detail back to normalized ad
evidence, and deterministically classifies usable text by funnel stage, offer,
audience, messaging theme, and provider-neutral format. It persists exact
provider-total-versus-inspected coverage, inventory tiers, sample-confidence
bands, text availability, duplicate creative fingerprints, provenance, and a
stable scoring-input summary. Missing or redacted copy stays unknown; image and
video contents are explicitly outside the V1 analysis scope.

`paid_channels_v3` now consumes this creative artifact. Its factors cover
observed inventory, current/recent creative evidence, destinations, relevant
technology, content, funnel stages, message themes, platforms, and formats.
Unknown factors have null points and reduce evidence coverage/confidence rather
than becoming zeros. ColdIQ currently scores 97.6 retargeting readiness with a
review status because current activity and destinations remain unknown; its
programmatic readiness is 93.8 provisional-pass. DailyPay scores 98.0 and
100.0 respectively, with observed active/recent creative evidence. Gap scores
for both accounts remain unknown.

The Apify live boundary remains implemented as a fallback and replay source with
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

The `run-account-v1` orchestrator now connects the full website, BuiltWith,
three-channel Adyntel, selective Apify fallback, creative-analysis, V3 scoring,
and decision-report path. Each stage checkpoints into the account run; queued
jobs also mirror stage state into SQLite migration 006. Completed BuiltWith
work and completed/partial Adyntel channels are never automatically purchased
again. Apify fallback is limited to failed or inconclusive Meta/LinkedIn stages.
The final JSON/Markdown report preserves provider totals, inspected coverage,
creative patterns, cost, evidence confidence, and blockers.

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

## Five-account acceptance

The complete V1 workflow has now been exercised on ColdIQ, DailyPay, HubSpot,
Gong, and Linear. All five produced resumable checkpoints, technology evidence,
creative-aware paid scores, and decision reports. ColdIQ, DailyPay, HubSpot,
and Gong completed; ColdIQ's inconclusive Adyntel Meta response is bounded by
an explicit-zero Apify result. Linear remains partial because neither Adyntel
nor the name-based Apify fallback resolved LinkedIn safely. The acceptance record is in
`reports/FIVE_ACCOUNT_ACCEPTANCE.md`.

The run exposed and fixed three real-provider edge cases: unnamed BuiltWith
rows now skip with an audit warning and can be locally replayed; explicit
Adyntel zero results override stray continuation tokens; and an Apify actor run
with candidates but no attributable normalized ads is inconclusive rather than
completed. Provider-cost reports now include Apify and flag paid attempts whose
billing metadata was not returned inline.

The complete deterministic suite passes 138 tests.

## Current account-specific collection policy

ColdIQ Meta enrichment is explicitly skipped by user decision. The pipeline
persists this as `not_collected_by_decision`; it is not a zero, blocker, or
absence claim. Historical raw/provider artifacts remain immutable for audit,
while future ColdIQ runs should pass `--skip-ad-platform meta`.
