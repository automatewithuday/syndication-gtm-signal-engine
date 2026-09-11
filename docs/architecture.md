# Architecture

## Processing flow

```text
Account source
  -> provider collection
  -> raw payload storage
  -> normalization
  -> website discovery/crawl
  -> deterministic extraction
  -> optional semantic extraction
  -> evidence ledger
  -> account aggregation
  -> channel scoring
  -> QA/qualification
  -> outreach packet or CRM export
```

## Components

### Provider adapters

- **Firecrawl:** sitemap discovery, bounded crawl, page markdown, metadata, links.
- **Apify/ad libraries:** creatives, observed dates, destination URLs, platforms.
- **Deepline/RapidAPI:** firmographics, technographics, hiring, news, intent.
- **SERP provider:** indexed landing pages, dated results, external mentions.
- **Supabase:** normalized entities, raw payload pointers, evidence, scores, runs.

Each adapter returns normalized domain objects. Vendor response fields must not be referenced by classifiers or scoring functions.

### Discovery

Seed from the homepage, sitemap, navigation, known resource directories, SERP results, and ad destination URLs. Canonicalize URLs while retaining the original campaign URL and UTM parameters as separate observations.

### Extraction

Run cheap deterministic rules first. Send only ambiguous or high-value pages to a structured-output LLM classifier. Persist both results and record the method/model version.

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
