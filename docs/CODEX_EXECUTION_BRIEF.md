# Codex execution brief

## Mission

Turn this starter into a production-capable, reusable Python repository that finds evidence-backed opportunities for content syndication, retargeting, programmatic advertising, and outbound calling across B2B accounts.

The implementation must remain operable by any coding agent through documented CLI commands and the repository skill.

## Delivery method

Implement the phases below as small, independently verifiable milestones. For
each milestone:

- evaluate representative real public companies;
- convert useful observations into sanitized, deterministic fixtures;
- document blockers, resolutions, and classification/scoring lessons in
  `docs/DECISIONS_AND_LEARNINGS.md`;
- update the repository skill when a lesson changes how future agents should
  collect, classify, score, or qualify evidence; and
- avoid treating provisional weights or thresholds as final until real-company
  validation supports them.

During the initial milestones, store artifacts on the local filesystem and use
SQLite when structured persistence is needed. Introduce remote persistence only
when a later milestone requires it. Credentials must come from an encrypted
vault integration and must never be persisted in repository artifacts.

## Phase 1 — Website intelligence MVP

Deliver a Firecrawl-backed account analysis pipeline for:

1. Substantial content asset discovery
2. Gated versus ungated classification
3. Publication frequency and recency
4. Industry/persona landing pages
5. Demo, contact-sales, and trial paths
6. Case studies and enterprise proof

Requirements:

- Add provider interfaces and a Firecrawl adapter.
- Save raw responses and normalized pages separately.
- Canonicalize and deduplicate URLs.
- Add structured models for assets, forms, conversion paths, and proof.
- Add deterministic classifiers plus an optional structured-output LLM fallback.
- Aggregate company metrics and produce a content-syndication score.
- Provide fixture-based tests; no paid API calls in unit tests.
- Add a CLI command that analyzes one domain and writes a JSON report.

Acceptance test:

```bash
gtm-signals crawl-and-analyze example.com --output report.json
```

The report must include evidence URLs/excerpts and distinguish unknown from absent.

## Phase 2 — External and campaign signals

- Implement normalized adapters for Deepline enrichment and selected Apify actors.
- Ingest Meta and LinkedIn ad observations, including creative and destination URL.
- Parse UTM and click identifiers while preserving canonical and observed URLs.
- Add SERP discovery for campaign and segment pages missed by the internal crawl.
- Add technology observations with detection source and limitations.
- Produce retargeting and programmatic readiness/gap scores.

## Phase 3 — Persistence and orchestration

- Add Supabase/Postgres migrations based on `docs/data-model.md`.
- Make account jobs idempotent and resumable.
- Add concurrency, rate limiting, retries, and provider cost tracking.
- Support batch input from CSV/JSONL.
- Add per-provider mocks and end-to-end tests using recorded fixtures.
- Export qualified accounts and their evidence bundles.

## Phase 4 — Validation and learning

- Add a human-review queue with `agree`, `disagree`, and corrected labels.
- Snapshot evidence and score versions at outreach-send time.
- Import outcomes such as reply, positive reply, meeting, opportunity, bounce, and opt-out.
- Evaluate precision by signal/channel; do not optimize solely for reply rate.
- Add configurable thresholds based on validation results.

## Initial success criteria

- At least 90% precision on substantial asset type in a manually labeled test set.
- At least 85% precision on gated/ungated classification, with ambiguous cases returned as unknown.
- Every qualifying claim traceable to one or more evidence records.
- Re-running an unchanged domain does not create duplicate current-state records.
- Provider failure leaves a resumable run and never silently becomes negative evidence.
- A batch can be reproduced from configuration, code version, and stored observations.

## Recommended first Codex prompt

> Read `AGENTS.md`, `README.md`, `docs/architecture.md`, `docs/data-model.md`, and the `$gtm-channel-gap-analysis` skill. Implement Phase 1 from `docs/CODEX_EXECUTION_BRIEF.md` in small test-backed increments. Preserve the provider-neutral domain model, treat missing observations as unknown, and make no paid API calls in tests. Run the complete test suite and update the example output before finishing.
