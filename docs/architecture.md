# Architecture

## Processing flow

```text
Account source
  -> cached canonical company enrichment (Deepline/Prospeo)
  -> website discovery/crawl
  -> deterministic extraction
  -> raw provider collection (BuiltWith + Adyntel)
  -> provider-neutral normalization
  -> creative analysis
  -> evidence ledger
  -> account aggregation
  -> six-signal account priority scoring
  -> channel scoring
  -> bounded gap target planning and Scrapling acquisition
  -> exact-run gap review resolution
  -> decision report and human QA
```

## Components

### Provider adapters

- **Scrapling:** sole live website provider for sitemap discovery, bounded page
  collection, browser fallback, metadata, bodies, and links.
- **Deepline/BuiltWith:** primary technology evidence.
- **Deepline/Adyntel:** primary Meta, LinkedIn, and Google ad-library evidence.
- **Apify:** bounded Meta/LinkedIn fallback only after failed or inconclusive
  Adyntel evidence.
- **SQLite/local files:** run state, review queues, raw payload pointers,
  evidence, scores, and stage checkpoints.

Each adapter returns normalized domain objects. Vendor response fields must not be referenced by classifiers or scoring functions.

### Discovery

Seed from the homepage, sitemap, navigation, known resource directories, SERP results, and ad destination URLs. Canonicalize URLs while retaining the original campaign URL and UTM parameters as separate observations.

The gap target planner consumes only saved discovery inventory, attributable
same-domain ad destinations, and saved search rows carrying explicit Scrapling
provenance. It assigns deterministic structural priorities, excludes broad
press/partner noise, caps selection, and records a hash of logical inputs.
Previously attempted failures require an explicit retry. Cross-path redirects
are failures because their content cannot be attributed to the requested target.

### Extraction

Run deterministic rules first. Ambiguous cases remain unknown unless an
explicit, versioned semantic classifier is configured. Persist the method and
logic version.

### Evidence ledger

Evidence is append-only by observation run. A later crawl may contradict earlier evidence without erasing history. Derived account state uses the most recent valid observations.

### Scoring

The unified account-priority layer combines firmographic fit, hiring, funding,
advertising, technology, and website evidence using configuration-driven
weights. Unknown signals are excluded from the numeric average while reducing
reported evidence coverage and confidence. This priority score is a ranking
aid, not evidence of a channel gap.

Score fit, readiness, gap, and trigger separately for each channel. Channel
totals are configuration-driven and remain null when any required component is
unknown. A high total with low evidence confidence does not qualify
automatically.

The gap-resolution workflow rediscovers and idempotently ingests deterministic
candidates, then exports only human approvals tied to the current run and page
content hash. It rebuilds content, paid-channel, unified, and account-report
artifacts locally without making provider calls. Pending evidence is
`review_required`; an empty queue is `insufficient_evidence`.

## Production requirements

- Resumable jobs and per-provider retry policies
- Provider rate limiting and spend ceilings
- Canonical URL and content-hash deduplication
- Raw response retention with secret/PII controls
- Versioned extraction prompts and scoring configs
- Per-signal freshness windows
- Human QA queue before outreach
- Outcome feedback tied to the exact score/evidence snapshot used at send time

`run-account-v1` is the V1 orchestration boundary. It writes a checkpoint after
each stage and never repurchases completed BuiltWith or completed/partial
Adyntel work during resume.

`account_pipeline_v2` optionally runs targeted gap acquisition after paid-ad
normalization and before exact-run gap resolution. The stage is disabled unless
the caller supplies a positive page budget. Its target, page, and depth limits
and failed-target retry choice are persisted as collection policy. Acquisition
defers resolution to the existing pipeline stage, so dependent scores are
rebuilt exactly once.
