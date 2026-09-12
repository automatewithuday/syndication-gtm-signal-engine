# Architecture

## Processing flow

```text
Account source
  -> website discovery/crawl
  -> deterministic extraction
  -> raw provider collection (BuiltWith + Adyntel)
  -> provider-neutral normalization
  -> creative analysis
  -> evidence ledger
  -> account aggregation
  -> channel scoring
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

### Extraction

Run deterministic rules first. Ambiguous cases remain unknown unless an
explicit, versioned semantic classifier is configured. Persist the method and
logic version.

### Evidence ledger

Evidence is append-only by observation run. A later crawl may contradict earlier evidence without erasing history. Derived account state uses the most recent valid observations.

### Scoring

Score fit, readiness, gap, and trigger separately. Channel totals are configuration-driven. A high total with low evidence confidence does not qualify automatically.

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
