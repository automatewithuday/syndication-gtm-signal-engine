# Completion audit — local review release

Audited 2026-09-12 against `docs/CODEX_EXECUTION_BRIEF.md`, `AGENTS.md`, and the
user's milestone decisions. This is the full local V1 release. Live paid
providers are active through credentials held outside the repository; remote
persistence and automated outreach remain outside the approved scope. Local
files/SQLite were explicitly selected, and no outreach was authorized.

## Cross-cutting invariants

| Requirement | Evidence | Result |
| --- | --- | --- |
| Public-web absence remains unknown | `channel_gap.py`, `paid_channel_scoring.py`, and corrected legacy `scoring.py`; regression tests | Pass |
| URL/excerpt/time/method/confidence provenance | `Evidence`, fit/gap/trigger validators, account review JSON | Pass |
| Raw provider isolation | provider protocols and recorded adapters return normalized models with raw artifact pointers | Pass |
| Canonical/content-hash idempotency | collector identities, canonical repair, exact occurrence tables | Pass |
| Configured/versioned scoring | content v1/v2 and paid-channel v1/v2/v3 configs plus snapshot hashes | Pass |
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
| Deepline/BuiltWith normalization | live adapter, immutable envelopes, local replay, malformed-row audit, and fixtures | Pass |
| Deepline/Adyntel Meta/LinkedIn/Google | single-attempt calls, totals/coverage, billing, raw hashes, and five-account validation | Pass with two recorded inconclusive channels |
| Apify Meta/LinkedIn fallback | guarded live adapter, pinned actor builds, vault boundary, strict attribution, and fixtures | Pass |
| Observed/canonical URLs plus UTM/click IDs | `CampaignUrl` and parser tests | Pass |
| Campaign/SERP pages missed by crawl | recorded Scrapling SERP adapter | Pass |
| Technology source and limits | `TechnologyObservation` | Pass |
| Retargeting/programmatic readiness and gap | creative-aware `paid_channels_v3`, known-evidence normalization, v1/v2 replay | Pass |

No unsupported real score is fabricated. ColdIQ's primary Meta result stays
inconclusive alongside a bounded explicit-zero fallback result. Linear LinkedIn
stays unknown because configured providers did not resolve it conclusively.

## Phase 3 — local persistence and orchestration

| Requirement | Evidence | Result |
| --- | --- | --- |
| Versioned migrations | six packaged SQLite migrations | Pass |
| Idempotent/resumable jobs | stable request hash, account/stage transitions, saved-run replay without repurchase | Pass |
| Concurrency/rate limit/retries/cost | bounded workers, crawl delay, Scrapling retries, cost field | Pass |
| CSV/JSONL batches | `enqueue-batch`, `run-pending-jobs` | Pass |
| Provider mocks/end-to-end fixtures | recorded provider fixtures, complete workflow tests, and five-account live acceptance | Pass |
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
- HubSpot authoritative run: `20260912T154913Z-418b2e32`.
- Gong authoritative run: `20260912T155024Z-dabb2a1c`.
- Linear authoritative run: `20260912T155445Z-9cb88b7e`.
- `reports/FIVE_ACCOUNT_ACCEPTANCE.{json,md}` records the verified outputs,
  spend, provider coverage, and unresolved evidence.

## Verification record

- Full suite: 138 tests passed in the latest verification run; paid APIs are
  replaced by recorded payloads or fakes in tests.
- Python compile check and `git diff --check`: pass.
- Wheel build: pass.
- Wheel and source distribution build: pass; CLI, six migrations, and installed
  content/paid/creative configurations are present.
