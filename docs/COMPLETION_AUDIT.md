# Completion audit — local review release

Audited 2026-09-11 against `docs/CODEX_EXECUTION_BRIEF.md`, `AGENTS.md`, and the
user's milestone decisions. This is the full local review release. Live paid
provider activation, remote persistence, and automated outreach are outside the
approved current scope: credentials are to be added later through an encrypted
vault, local files/SQLite were explicitly selected for now, and no outreach was
authorized.

## Cross-cutting invariants

| Requirement | Evidence | Result |
| --- | --- | --- |
| Public-web absence remains unknown | `channel_gap.py`, `paid_channel_scoring.py`, and corrected legacy `scoring.py`; regression tests | Pass |
| URL/excerpt/time/method/confidence provenance | `Evidence`, fit/gap/trigger validators, account review JSON | Pass |
| Raw provider isolation | provider protocols and recorded adapters return normalized models with raw artifact pointers | Pass |
| Canonical/content-hash idempotency | collector identities, canonical repair, exact occurrence tables | Pass |
| Configured/versioned scoring | content v1/v2 and paid-channel v1 configs plus snapshot hashes | Pass |
| No untraceable outreach claims | qualification-gated bundle export and send-time snapshots | Pass |
| Secrets remain outside artifacts | `SecretVault` and macOS Keychain adapter; repository secret-pattern check empty | Pass |

## Phase 1 — website intelligence

| Requirement | Evidence | Result |
| --- | --- | --- |
| Sole live website provider | `ScraplingFetcher`, browser transport still inside Scrapling | Pass |
| Raw/normalized separation | `raw/*.body`, raw metadata, `normalized/pages.jsonl` | Pass |
| Bounded discovery and deduplication | sitemap/link inventory, page cap, canonical URL and body hash | Pass |
| Typed page/asset/form/conversion/proof models | `models.py` | Pass |
| Deterministic rules plus optional structured fallback | `classifiers.py`, `semantic.py` | Pass |
| Asset type, gating, freshness, segments, funnel, proof | classifiers and asset analysis | Pass |
| Configurable content-syndication scoring | `content_syndication_scoring.v2.json` and component scorers | Pass |
| Single-domain JSON command | `gtm-signals crawl-and-analyze ... --output ...`; end-to-end fixture test | Pass |
| Precision gates | 20/20 asset family and 17/17 gating on maintained sanitized benchmark | Pass |

Firecrawl in the original brief is superseded by the explicit Scrapling-only
decision. Ambiguous cases remain unknown when no semantic provider is configured.

## Phase 2 — external and campaign signals

| Requirement | Evidence | Result |
| --- | --- | --- |
| Deepline normalization | recorded enrichment adapter and technology fixture | Pass |
| Apify Meta/LinkedIn ad normalization | recorded advertising adapter and both platform fixtures | Pass |
| Observed/canonical URLs plus UTM/click IDs | `CampaignUrl` and parser tests | Pass |
| Campaign/SERP pages missed by crawl | recorded Scrapling SERP adapter | Pass |
| Technology source and limits | `TechnologyObservation` | Pass |
| Retargeting/programmatic readiness and gap | `paid_channel_scoring.py`, packaged v1 config | Pass |

Adapters are replay/fixture ready. Live actor/endpoint configuration is pending
the later vault-credential milestone; no unsupported real score is fabricated.

## Phase 3 — local persistence and orchestration

| Requirement | Evidence | Result |
| --- | --- | --- |
| Versioned migrations | five packaged SQLite migrations | Pass |
| Idempotent/resumable jobs | stable request hash, job transitions, saved-run analysis replay | Pass |
| Concurrency/rate limit/retries/cost | bounded workers, crawl delay, Scrapling retries, cost field | Pass |
| CSV/JSONL batches | `enqueue-batch`, `run-pending-jobs` | Pass |
| Provider mocks/end-to-end fixtures | recorded provider fixtures and complete workflow test | Pass |
| Qualified evidence export | snapshot-checked `export-evidence-bundle` with hard qualification gate | Pass |

Supabase/Postgres is intentionally deferred by the user's local SQLite decision.

## Phase 4 — validation and learning

| Requirement | Evidence | Result |
| --- | --- | --- |
| Agree/disagree/correct review | `classification_reviews` and `review-classification` | Pass |
| Exact send-time evidence/score snapshot | `outreach_snapshots` and snapshot command | Pass |
| Outcome imports | six explicit event types with idempotent CSV/JSONL import | Pass |
| Precision by channel and signal | channel and frozen-signal outcome metrics | Pass |
| Configurable validation thresholds | versioned config; explicitly `provisional` pending a real outcome sample | Pass |

No outreach was sent and no outcome calibration is claimed. The infrastructure
is ready to learn once authorized campaigns generate a meaningful sample.

## Real-account acceptance

- DailyPay authoritative run: `20260910T224631Z-52eaa2e5`.
- ColdIQ authoritative run: `20260910T224633Z-e599a4a6`.
- Both account reports pass snapshot/hash consistency checks.
- `reports/REAL_ACCOUNT_REVIEW.json` matches both authoritative report values.
- Both remain `insufficient_evidence` because content-syndication gap is unknown.

## Verification record

- Full suite: 95 tests passed in the final verification run, including both
  recorded ad-platform fixtures.
- Python compile check and `git diff --check`: pass.
- Wheel build: pass.
- Clean temporary wheel install: pass; CLI, five migrations, and installed
  content/paid scoring configs are present.
