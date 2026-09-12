# Decisions and learnings

This file is the durable project memory for implementation decisions, real-world
validation findings, blockers, and changes that should be folded back into the
repository skill.

## Working decisions

### 2026-09-10 — Incremental delivery and real-company validation

- Build in small, independently testable milestones rather than implementing an
  entire execution phase at once.
- Validate each milestone with real public companies in addition to synthetic
  unit-test fixtures.
- Keep deterministic, sanitized fixtures derived from those observations so the
  test suite does not depend on live sites or paid APIs.
- Complete and validate one pipeline stage at a time: account collection,
  normalization, classification, scoring, qualification, and later activation.
- Treat scoring configuration as provisional. Revise weights, thresholds, and
  signals only after examining real examples; do not treat the current example
  configuration as authoritative.
- Use the local filesystem for raw and normalized artifacts during early
  milestones. SQLite is the preferred initial structured store.
- Keep secrets and API keys out of repository files, SQLite databases, fixtures,
  logs, and raw payloads. Provider credentials will be supplied through a secure,
  encrypted vault integration when live adapters are introduced.
- Record every material blocker with its observed behavior, cause, resolution,
  test coverage, and any resulting skill/documentation change.

## Milestone completion record

For each milestone, append an entry containing:

1. Scope and acceptance test
2. Real companies evaluated and why they were selected
3. Evidence collected, including observation time and method
4. False positives, false negatives, and unknowns
5. Blockers and their resolutions
6. Scoring or model changes justified by the examples
7. Tests and fixtures added
8. Lessons incorporated into `skills/gtm-channel-gap-analysis/`

Do not place credentials, private customer data, or unrestricted raw provider
payloads in this log.

## Milestone 1 — Account collection

### Selected validation accounts

- `dailypay.com`: enterprise B2B site with a broad industry taxonomy, resource
  center, case studies, integrations, quantified customer proof, and demo paths.
- `coldiq.com`: developer-led GTM product with a comparatively compact site,
  product/API detail, public pricing, self-serve signup, demo paths, and
  quantified case studies.

The contrast is intentional: collection and normalization must work for both a
large enterprise content estate and a compact product-led website.

### 2026-09-10 — Initial collection blocker

- Attempted method: Parallel URL extraction for both homepages.
- Observed behavior: both requests returned an explicit `Insufficient credit in
  account` error and no usable records.
- Interpretation: provider failure/incompleteness, not negative website evidence.
- Temporary resolution: standard public-web retrieval confirmed that both sites
  are reachable and contain useful crawl seeds.
- Required implementation behavior: provider attempts must record status,
  warnings, and incomplete state; a failed provider must never emit absence
  evidence. Account collection should support a provider fallback or a resumable
  retry without contaminating normalized observations.
- Skill impact: already covered by the operating rule that failed or unavailable
  providers produce explicit incomplete states. Add a regression test when the
  first collection adapter is implemented.

### 2026-09-10 — Bounded whole-site collection increment

- Implemented a provider-neutral collector with a Scrapling fetcher, sitemap and
  homepage-link discovery, same-site restriction, robots.txt rules, tracking
  parameter removal, content hashing, and separate raw/normalized artifacts.
- Added a verified system-curl fetcher because Scrapling's bundled TLS backend
  could not validate the local network certificate chain. Certificate
  verification remains enabled; disabling TLS verification is not an acceptable
  workaround.
- DailyPay canary: 1,345 canonical page candidates discovered; 10-page and
  12-page bounded samples completed. One legacy sitemap returned non-XML content
  and was recorded as an explicit discovery error.
- ColdIQ canary: 6,307 canonical page candidates discovered; 10-page and 12-page
  bounded samples completed without request errors.
- Initial low-budget samples exposed sitemap-order bias: DailyPay favored old
  blog posts and ColdIQ favored its large tools/catalog estate. Crawl scheduling
  now prioritizes the homepage, case studies/customer proof, substantial assets,
  segment/solution pages, and conversion pages before bulk blog/catalog pages.
- A broad `/customer` substring rule incorrectly prioritized ColdIQ category and
  tool URLs such as customer-profiling products. It was narrowed to explicit
  proof path families such as `/case-studies`, `/customer-stories`, and
  `/customers/`.
- Local setup exposed a macOS/Python 3.14 issue where the generated editable
  `.pth` file was marked hidden and skipped by Python. A non-editable `uv sync`
  works in this environment; this is an environment/setup issue, not crawl
  evidence.
- Tests cover URL canonicalization, raw/normalized artifact separation, robots
  exclusions, provider failure semantics, redirect header parsing, and strategic
  page priority under a low crawl budget.

The current runs remain `partial` by design because their page caps were reached.
They validate collection behavior; they are not yet sufficient for account
scoring or claims about channel gaps.

### 2026-09-10 — Relevant-site crawl results

- Persisted the complete normalized discovery inventory even when the fetch cap
  is smaller than the discovered website. This separates “known URL universe”
  from “pages successfully observed.”
- DailyPay relevant-site pass: 125 pages collected from 1,345 discovered URLs;
  every collected response had a unique content hash. The legacy sitemap parse
  error remained explicit.
- ColdIQ relevant-site pass: 85 pages collected from 6,307 discovered URLs;
  every collected response had a unique content hash. Two discovered URLs
  returned HTTP 404 and were retained as fetch errors, not negative evidence.
- A second priority issue appeared on DailyPay: a generic `/resource` rule
  promoted podcasts, videos, and consumer financial-literacy pages alongside
  campaign-ready reports and ebooks. The generic rule was removed; explicit
  asset families remain prioritized.
- Every sampled page on both sites contained at least one HTML form, apparently
  because global newsletter/contact UI is repeated across templates. Therefore,
  form presence alone cannot establish asset gating. The classification milestone
  must use form purpose, placement, CTA relationship, destination, and field
  semantics and should return `unknown` when those are ambiguous.

These passes constitute full URL discovery plus bounded retrieval of the
highest-value GTM surfaces. Fetching all 6,307 ColdIQ URLs indiscriminately would
mostly collect tool/catalog and SEO inventory, increase load, and make validation
less representative. Future expansion should be driven by explicit page-family
coverage rather than raw page count.

### 2026-09-10 — Page family, form purpose, and gating increment

- Added versioned deterministic classification output for saved crawl runs. It
  writes an auditable evidence ledger and summary without producing scores.
- Page-family classification uses URL section and title signals rather than the
  full page body, preventing repeated navigation/footer copy from turning blogs
  into reports or webinars.
- Form normalization now retains form ID, name, class, data name, field type and
  placeholder, submit label, and in-form text. This supports purpose detection
  without submitting forms.
- Real ColdIQ pages exposed a substring bug: `unsubscribe` matched `subscribe`.
  Newsletter detection now uses a word boundary, while “one email per guide” is
  treated as an asset delivery signal.
- Real ColdIQ tool names such as ReportGarden and WebinarKit exposed a precedence
  bug. Explicit site section (`/tools/`) now outranks asset words in a product
  name.
- Real DailyPay ebook pages showed that a JavaScript-populated Marketo container
  may have no server-rendered fields. On an ebook/report/guide/webinar page, the
  marketing-form container plus asset context is usable evidence; field count is
  not required.
- A repeated playbook form on a case-study template does not gate the case study.
  Gating requires a relationship between the current page family and its access
  path.
- Validation details are recorded in
  `docs/validation/2026-09-10-classification.md`.

### 2026-09-10 — Asset quality and freshness increment

- Added `analyze-assets` for saved crawl runs. It emits versioned per-asset
  records and aggregate freshness, gating, substance, and syndication-suitability
  metrics without making new network requests.
- Freshness is calculated against each page's recorded observation time. A
  publication/creation date is distinct from a modification date; sitemap
  `lastmod` is never treated as publication.
- DailyPay supplied `article:published_time` for all 61 classified detail assets.
  ColdIQ supplied uniquely attributable embedded `createdAt` values for 24 of 42
  assets; the other 18 remain unknown.
- Twenty-two ColdIQ sitemap `lastmod` values clustered within one minute and
  appeared to be deployment/sitemap-build metadata. They were flagged and
  excluded rather than creating false recency.
- Asset listing pages caused false counts: DailyPay's paginated case-study pages
  and ColdIQ's `/guides` and `/case-studies` indexes were being treated as
  individual assets. Listing and pagination paths are now taxonomy.
- DailyPay repeats a GLBA consumer-notice PDF across resource templates. The
  earlier “any PDF means direct asset” rule overstated accessibility. Document
  links now require asset context and exclude legal/privacy/terms documents.
- A visible gated offer supports `possible` syndication suitability, but it does
  not prove the inaccessible asset is substantial or licensed for reuse.
- Raw artifacts are verified against their stored hashes. Missing, unreadable,
  or mismatched raw data produces an explicit partial analysis state.
- Validation details are recorded in
  `docs/validation/2026-09-10-asset-quality-and-freshness.md`.

### 2026-09-10 — Provisional content-syndication readiness score

- Added a configuration-driven `score-syndication` command over saved asset
  analysis. It writes factor-level evidence, confidence inputs, qualification
  blockers, configuration hashes, and a stable evidence snapshot ID.
- Readiness, fit, gap, and trigger remain separate. Website assets can establish
  readiness, but they do not establish economic/ICP fit or prove that an
  off-site distribution channel is unused. Unknown required components produce
  a `null` total rather than zero or a positive gap.
- A bounded priority crawl can establish positive presence but is not exhaustive.
  Both real-company confidence scores are capped at 0.75, and the output states
  that counts describe the observed sample.
- Recent content production is a possible trigger, not a complete buying trigger.
  The configuration caps content-only trigger contribution at 60/100 pending
  external business signals.
- Gated assets with unobserved full content receive fractional, configurable
  suitability credit. This prevents a visible offer from receiving the same
  readiness credit as a verified reusable document.
- DailyPay scored 86 readiness and 15 trigger at 0.750 confidence. ColdIQ scored
  93 readiness and 60 trigger at 0.745 confidence. Both are provisional readiness
  passes and remain `insufficient_evidence` opportunities because fit and gap
  are unknown.
- Thresholds remain `provisional_unlabeled`. Two behavior checks are not enough
  to claim precision or authorize automated qualification/outreach.
- Snapshot identity is based on stable evidence, summary content, configuration,
  and scoring version; replay timestamps do not create a new logical snapshot.
- The first installed-CLI acceptance run could not find the repository-relative
  default scoring JSON because the project uses a non-editable package install.
  The default configuration is now included as installed package data, discovery
  checks both source and installed locations, and a test covers execution away
  from the repository working directory.
- Validation details are recorded in
  `docs/validation/2026-09-10-syndication-readiness-scoring.md`.

### 2026-09-10 — Evidence-backed account fit

- Added `score-fit` with configuration-driven factors for B2B model,
  professional buyer coverage, sales motion, and operating scale. Each fact must
  retain URL, excerpt, observation time, strength, confidence, and method.
- Parallel web search again returned `Insufficient credit in account`. The
  failure remained explicit provider incompleteness; direct public-web research
  supplied the current evidence without adding credentials or funds.
- Do not force employee count as the only scale proxy. DailyPay's first-party
  client/access figures and ColdIQ's first-party ARR statement are more directly
  relevant to commercial capacity, but remain source assertions with explicit
  confidence and risk.
- Buyer personas must be supported by the buying/service context. ColdIQ's
  marketing/growth and sales/RevOps coverage uses separate case-study evidence
  rather than one excerpt being stretched across all personas.
- Multi-offer companies can have hybrid sales motions. DailyPay exposes both
  enterprise demos and a small-business self-serve offer; ColdIQ presents an API
  plus consulting/agency services. Preserve the ambiguity as a risk even when a
  dominant motion is scored.
- Conflicting boolean or categorical fit facts return unknown and zero factor
  points; they are not averaged into false certainty.
- DailyPay scored 86.2 fit at 0.953 fit confidence. ColdIQ scored 81.0 at 0.904.
  Both are provisional passes. After integration, `gap` is the sole unknown
  required component and both opportunity totals correctly remain `null`.
- Validation details are recorded in
  `docs/validation/2026-09-10-account-fit.md`.

### 2026-09-10 — Scrapling-only collection policy

- Scrapling is the sole live web-collection provider for account research,
  website crawling, and channel-gap evidence. Do not use Parallel, curl,
  generic browser research, or another scraper as an automatic fallback.
- A Scrapling failure produces an explicit incomplete run. Repair or retry the
  Scrapling environment; facts that were not observed remain `unknown`.
- Scrapling's static `curl_cffi` transport failed certificate-chain validation
  on the current machine. Its browser-backed transport succeeded with the local
  Chrome while retaining TLS verification, so the adapter uses that transport
  only for certificate verification errors. This is a transport change within
  Scrapling, not a provider fallback.
- Installed-adapter canary: `https://dailypay.com/` resolved through Scrapling
  to `https://www.dailypay.com/` with HTTP 200 after the verified browser
  transport engaged.
- Normalized scoring facts must be derived from saved Scrapling artifacts so
  their provenance can be traced to a specific collection run.
- The public crawl CLI no longer exposes the prior `system-curl` alternative.
- Existing DailyPay and ColdIQ crawl manifests name `SystemCurlFetcher`, and
  their account-fit profiles include generic public-web research. Preserve that
  provenance: these are pre-policy deterministic validation examples, not
  operationally qualified evidence. Fresh Scrapling runs must replace them
  before final qualification.

### 2026-09-10 — Positive channel-gap evidence

- Added `score-gap` for content syndication. It only accepts observations that
  match a canonical URL, content hash, observation time, and excerpt in the
  current run's saved Scrapling pages.
- Supported positive evidence is deliberately narrow: explicit expansion
  intent, a documented distribution bottleneck, an active partner/hiring
  search, or a documented performance shortfall. Asset volume or failure to
  find a syndication footprint is not gap evidence.
- A documented healthy or successful syndication program contradicts the gap
  and disqualifies this opportunity. When supporting and contradicting evidence
  coexist, route the account to review instead of averaging them.
- The initial gap pass requires two positive signal types, score 45, and
  confidence 0.70. These thresholds remain provisional and require labeled
  examples/outcomes before calibration.
- DailyPay and ColdIQ remain `unknown` for gap because their existing full
  samples predate the Scrapling-only policy. This is the intended result, not a
  collection failure disguised as a negative finding.
- Fresh one-page Scrapling canaries for DailyPay and ColdIQ completed without
  provider errors. Empty evidence profiles correctly produced `null` gap scores,
  `unknown` state, and `insufficient_evidence` status for both accounts.
- Validation details are recorded in
  `docs/validation/2026-09-10-channel-gap.md`.

### 2026-09-10 — Targeted gap candidate discovery

- Added `collect-gap-targets` to resume a Scrapling run by fetching only
  high-signal URLs already present in its discovered inventory. Selection uses
  structural path segments for careers/jobs, partner programs, marketing and
  campaign pages, press/news pages, and explicit syndication pages.
- Added `discover-gap-candidates` to write pending-review candidates from saved
  page text. Candidate rules never write to the scored gap profile.
- DailyPay supplied careers and press-center targets. ColdIQ supplied an openings
  page and an AI marketing tools directory. Scrapling fetched all selected pages
  plus robots policies without provider errors.
- The first ColdIQ pass produced four false positives by combining unrelated
  labels across a tool directory. Resolution: exclude tool directories, require
  first-person expansion intent, use compact performance phrases, and avoid
  arbitrary URL substring matching.
- After replay, both accounts produced zero candidates. This keeps their gap
  state unknown and confirms that candidate absence is not negative evidence.
- Validation details are recorded in
  `docs/validation/2026-09-10-gap-candidate-discovery.md`.

### 2026-09-11 — SQLite gap-review queue

- Added a versioned SQLite migration and CLI workflow to ingest, list, review,
  and export gap candidates. Local review state defaults to
  `data/gtm_signal_engine.sqlite3` and is gitignored.
- Separate stable candidates from run/content-hash occurrences and append-only
  reviews. This keeps rejection decisions across re-ingestion without allowing
  a later page snapshot to inherit an earlier approval.
- Require reviewer identity and notes for every decision. Approvals additionally
  require explicit strength and confidence; deterministic candidate confidence
  is never silently promoted into evidence confidence.
- Export only approved observations bound to the requested Scrapling run and
  validate them against saved pages before writing a scoreable profile.
- Historical approval replay initially depended on the candidate's latest
  content hash. A later crawl could therefore hide an older valid approval. The
  query now uses the exact reviewed occurrence, preserving historical replay.
- DailyPay and ColdIQ currently contain zero reviewed candidates; both ingest as
  empty without inventing evidence or decisions.
- Validation details are recorded in
  `docs/validation/2026-09-11-sqlite-gap-review.md`.

### 2026-09-11 — Broader initiative discovery

- Extended targeted Scrapling collection with a bounded depth. Relevant links
  are queued only after same-domain validation, canonical path identity ignores
  query-string variants, and tool/category/tag/pagination paths are excluded.
- The first DailyPay depth-two command exposed a CLI wiring bug: the depth value
  was sent to the ordinary crawl branch, while targeted collection kept its
  default depth of one. The manifest correctly recorded depth one. The wiring
  was fixed and command-level tests now verify both branches.
- Broad press-detail selection fetched unrelated board and recognition news.
  Future collection now accepts press detail pages only when the terminal slug
  signals a launch, campaign, marketing, partner, growth, or opening; press/news
  listing pages remain eligible for link discovery. Existing raw evidence was
  retained rather than rewritten.
- Added an initiative-candidate stream for public campaign launches, new channel
  or team launches, and active marketing hiring. It is explicitly separate from
  channel-gap discovery and all results remain pending trigger review.
- DailyPay produced one dated direct campaign-launch candidate: “The Future of
  Pay,” published 2026-06-08. ColdIQ produced three page-level candidates across
  active ads hiring and a new ColdIQ Ads growth engine; none had an attributable
  publication date, so their source dates remain null.
- ColdIQ initially emitted two active-hiring matches from the same job page
  (“looking for” and “hiring”). Candidate extraction now keeps one occurrence
  per page and signal type while preserving separate source pages.
- Both accounts still produced zero channel-gap candidates. This means the gap
  remains unknown; initiative evidence is not a substitute for a documented
  channel limitation.
- Added a migration that preserves attributable source-date metadata on gap
  candidates and exact run/content occurrences.
- Validation details are recorded in
  `docs/validation/2026-09-11-broader-initiative-discovery.md`.

### 2026-09-11 — Initiative review and trigger scoring

- Added a separate SQLite initiative queue with stable candidates, exact
  run/content occurrences, and append-only reviews. Gap and initiative tables
  remain structurally and semantically separate.
- Initiative approvals require reviewer identity, rationale, strength, and
  confidence. Re-ingestion preserves decisions, while changed content or a new
  run cannot inherit an earlier approval.
- Added a reviewed trigger profile and deterministic trigger scorer. Every
  observation must match a saved Scrapling URL, content hash, observation time,
  and excerpt before it can score.
- Scoring version `content_syndication_v2` assigns provisional base points by
  initiative type, then applies reviewer-strength and freshness credits. An
  undated initiative receives a 0.50 freshness credit and a 0.65 confidence
  cap; `observed_at` is not substituted for an unknown event/publication date.
- The scoring date is explicit (`--as-of` is available for deterministic
  replay). Future-dated evidence relative to that date is rejected.
- Reviewed initiative and recent-content trigger scores are combined using the
  maximum, not addition, because a campaign launch can also generate recent
  content and must not be counted twice.
- The real DailyPay and ColdIQ candidates were ingested as four pending items.
  None were auto-approved, so no real trigger evidence entered qualification.
- Kept the prior v1 scoring configuration for replay and packaged v1 and v2;
  v2 is now the default.
- Validation details are recorded in
  `docs/validation/2026-09-11-initiative-review-and-trigger-scoring.md`.

### 2026-09-11 — Authoritative real-account reviews and Phase 1 command

- Completed new 100-page Scrapling crawls for DailyPay and ColdIQ, then added
  bounded targeted pages required for initiative review. Both manifests remain
  explicitly partial because page caps and isolated collection errors mean the
  sites were not exhaustively observed.
- A ColdIQ page declared the homepage as its canonical despite the Scrapling
  final URL remaining `/contact-finder`. DailyPay exposed a similar migrated
  ebook case. Resolution: accept declared canonicals only when their paths match
  the fetched final path, and add `repair-canonicals` to correct historical
  normalized pages from immutable raw final-URL metadata.
- An exact DailyPay press-release override initially lost priority because its
  identity was already in the ordinary target queue. Resolution: validate
  explicit URLs against the saved discovery inventory and enqueue them before
  ordinary targets.
- Reviewed the current DailyPay campaign launch as confirmed (0.98 confidence).
  Reviewed ColdIQ's new ads division (0.94) and Ads Manager hiring (0.92), while
  rejecting the weaker list-page duplicate. Each review is bound to the exact
  run and content hash.
- DailyPay scores: fit 86.2/0.95, readiness 85.0/0.75, trigger 59.5/0.98.
  ColdIQ scores: fit 84.8/0.915, readiness 93.0/0.745, combined trigger
  60.0/0.745. Both gap components remain unknown, so neither account receives
  a weighted opportunity total or qualified status.
- Added `build-review-report` outputs with component reasoning, risks, fit
  evidence, reviewed initiative excerpts, and source links.
- Added `crawl-and-analyze` as the Phase 1 single-command workflow. It writes a
  portable JSON report containing evidence samples and preserves unresolved
  fit/gap components as unknown.
- Full fixture-only suite: 73 passed. Validation details are recorded in
  `docs/validation/2026-09-11-real-account-reviews-and-workflow.md`.

### 2026-09-11 — Local orchestration, external contracts, and outcomes

- Added provider-neutral recorded adapters for Apify ads, Deepline technology
  detections, and Scrapling-derived SERP results. Campaign destinations preserve
  the original tracked URL separately from the canonical URL, UTM parameters,
  and click identifiers. Technology observations always retain detection limits.
- Added versioned retargeting/programmatic readiness and gap scoring. Paid-channel
  gap stays null unless approved positive evidence is supplied; a missing pixel
  or vendor signature never creates a gap score.
- Added versioned SQLite jobs with idempotent CSV/JSONL enqueue, attempts,
  transitions, saved run/report paths, partial/failure state, bounded batch
  concurrency, and provider cost. Deterministic analysis can resume from an
  existing crawl without recollecting pages.
- Added exact-page classification corrections, immutable outreach score/evidence
  snapshots, idempotent sends and outcome imports, and outcome reporting by both
  channel and frozen signal. Reply, positive reply, meeting, opportunity, bounce,
  and opt-out remain distinct events.
- Added a qualification-gated evidence-bundle exporter. It refuses to export
  DailyPay and ColdIQ because their gap component is unknown.
- Added an encrypted-vault boundary and macOS Keychain reader. Provider secrets
  are not accepted through tracked configuration or persisted artifacts.

### 2026-09-11 — Completion audit corrections

- The original baseline `analyze` scorer still inferred high gap scores from
  missing technology/channel observations. This contradicted the evidence-first
  architecture even though the newer syndication pipeline was correct. Removed
  every absence-derived gap score: the legacy path now requires approved,
  attributable supporting evidence and otherwise emits null gap/total. Recent
  triggers likewise require URL, excerpt, observation time, and confidence.
- Added explicit typed models for content assets, forms, conversion paths, and
  customer proof plus an optional structured semantic-classifier interface.
  Semantic fallback runs only on deterministic unknowns and must record model
  and prompt versions.
- Added a 20-page manually labeled sanitized benchmark. Asset-family precision
  is 20/20 (1.00); gating precision is 17/17 (1.00), including an ambiguous case
  returned as unknown. This clears the initial fixture gates but is not treated
  as production-population calibration.
- Built and installed the wheel in a clean temporary environment. The installed
  CLI, five migrations, and all three packaged score configurations were present.
- Complete suite after the audit: 95 tests passed.

### 2026-09-11 — Live Deepline collection boundary

- Began live external-signal activation with the smallest provider increment:
  Deepline/BuiltWith technology observations only. Apify actors remain the next
  milestone.
- Parallel documentation search was blocked by insufficient account credit.
  Scrapling was used for the public documentation fallback. The user then
  supplied Deepline's official Codex surface, which established the supported
  native CLI workflow and removed the need to guess a direct HTTP contract.
- Installed and authenticated the official Deepline CLI, verified provider
  health and balance with `preflight`, inspected the live
  `builtwith_domain_lookup` schema, and used the free BuiltWith lookup as a
  zero-cost canary before paid enrichment.
- Replaced the provisional generic transport with a narrow native-CLI runner.
  The Python application passes no secret, invokes commands without a shell,
  binds the domain to the exact Scrapling run, requests live-only results with
  PII and company metadata disabled, and stops on contract drift before making
  a paid call.
- Paid executions are deliberately single-attempt. An ambiguous timeout is not
  automatically retried because that can create duplicate spend. Success stores
  the immutable provider envelope, normalized observations, tool contract,
  billing, provider job ID, and content hashes; failure is explicit and never
  converted into negative evidence.
- DailyPay returned 442 normalized technology observations and ColdIQ returned
  130. Each lookup cost 0.14 Deepline credits ($0.014). Both showed observable
  retargeting/conversion infrastructure, so any claim that they do not use
  retargeting would be contradicted by the collected evidence.
- Real data exposed a scoring flaw: the v1 implementation treated every
  technology, including CDN and DNS products, as paid-channel evidence. Kept v1
  intact for replay and added `paid_channels_v2`, which selects technology by
  channel-relevant categories. DailyPay now has 37 retargeting-relevant and 30
  programmatic-relevant detections; ColdIQ has 18 and 11 respectively.
- Both accounts score 55 retargeting readiness and 40 programmatic readiness,
  with review status. No live ad-library records exist yet, and both gap scores
  correctly remain null/unknown. Validation details are recorded in
  `docs/validation/2026-09-11-live-deepline-builtwith.md`.
- The complete fixture-only suite passed 103/103 after the live adapter and v2
  scoring boundary were added.

### 2026-09-11 — Apify actor selection and guarded live boundary

- Used the approved Scrapling-only research path after Parallel remained
  unavailable. Apify's public Store and API metadata were fetched through the
  project's pinned Scrapling dependency; no alternate scraper was introduced.
- Selected Apify's maintained `apify/facebook-ads-scraper` for Meta. At review
  time it had 35K+ total users, 5K+ monthly users, a current official build, and
  documented page/search URL input plus result limits and active-ad filters.
- Selected `silva95gustavo/linkedin-ad-library-scraper` for LinkedIn. It was the
  most established relevant Store result observed, with 3K+ total users, a 5.0
  rating across eight reviews, and over 118K successful public runs in the
  trailing 30-day stats. Its documented output includes ad ID, advertiser,
  active dates, copy, headline, click destination, and impressions.
- Pinned the observed builds (`0.0.374` for Meta and `1.1.52` for LinkedIn) in
  `apify_ads_v1`. Each actor is limited to 25 dataset items and a $0.15 maximum
  charge, with a 180-second actor timeout. The run starts asynchronously so the
  provider run ID is captured before waiting.
- Bearer credentials are read from macOS Keychain and never added to URLs,
  status files, or raw payloads. Paid POST requests have no automatic retry;
  polling and dataset reads are safe GET operations.
- Account-name search can return similarly named advertisers. The normalizer
  therefore requires an ad ID and a landing destination on the exact account
  domain or one of its subdomains. Unattributable records stay in ignored raw
  data and produce warnings instead of entering scoring.
- The initial DailyPay and ColdIQ commands created an explicit `blocked`
  collection state when the restricted process could not access the configured
  Keychain item. No actor was started and no Apify cost was incurred during
  those attempts. The later resolution is recorded below.

### 2026-09-11 — Live Apify canaries and attribution correction

- The Keychain token was present, but the restricted process could not see the
  user's login Keychain. Scoped host access resolved the blocker; the credential
  remained outside files, subprocess arguments, URLs, and artifacts.
- DailyPay proved domain-only destination attribution was too strict: four
  exact-advertiser LinkedIn ads used `bit.ly` or LinkedIn destinations. Added a
  conservative alternative gate requiring exact normalized advertiser name.
  Similar names still fail attribution.
- Unordered Meta keyword search returned unrelated advertisers. Added
  `apify_ads_v2` with exact-phrase search and retained v1 for replay. The
  corrected query yielded two attributable DailyPay Meta ads.
- Added local dataset replay so normalizer fixes do not require another paid
  run, plus platform-selective collection that preserves unselected ads and run
  metadata.
- ColdIQ exposed a second documented actor shape: a zero-result envelope with a
  nested `results` list. The normalizer now flattens envelopes and treats an
  empty completed envelope as zero candidates, not a malformed ad warning.
- DailyPay initially had six attributable ads with captured destinations across
  LinkedIn and Meta. Its retargeting/programmatic readiness scores were 80/80,
  while both gaps remained unknown. ColdIQ's name search produced no
  attributable ads in that bounded run; provider absence did not become a claim
  that a channel was unused.

### 2026-09-11 — LinkedIn company identity and destination-optional ads

- The user supplied ColdIQ's LinkedIn Ad Library URL with company ID `65826193`,
  proving the prior account-name query was a false negative. A company-ID run
  returned 25 ColdIQ records. Prefer verified platform entity IDs over names and
  persist the identity strategy and value beside the search URL.
- Thirteen ColdIQ records and only four of 25 DailyPay LinkedIn records contained
  click destinations. Missing destinations do not invalidate exact-advertiser ad
  activity. The normalized model now permits a null destination; such ads count
  toward activity and platform diversity but never tracking metrics.
- Free replay retained 25 ColdIQ LinkedIn ads and 29 DailyPay ads (25 LinkedIn,
  four Meta) without new provider calls. ColdIQ readiness moved from 55/40 review
  to 80 retargeting and 70 programmatic, both provisional-pass. Gap evidence for
  both companies remains unknown.
- Live Apify validation usage totals $0.15005 for DailyPay and $0.08810 for
  ColdIQ. The complete deterministic suite passes 116 tests, and package builds
  include both the replayable v1 and current v2 configurations.

### 2026-09-12 — Adyntel Meta validation returned an ambiguous empty payload

- Ran the user-requested `adyntel_facebook` lookup for `coldiq.com` using
  Deepline's managed integration, active-only default, and US default. The live
  price was 0.13 credits ($0.013) per call.
- The first paid call completed upstream but the CLI treated object-shaped output
  as CSV because `--out` was supplied, then discarded the response without a
  retrievable run ID. After explicit approval, one corrected JSON call completed
  with a job ID but returned empty `raw` and `rawV2` fields.
- Total validation cost was 0.26 Deepline credits ($0.026). No third call was
  attempted. Empty provider payloads without an explicit zero-result contract
  are `inconclusive`, not confirmation that Meta ads are absent.
- The audit record is stored at
  `deepline/data/coldiq-meta-ads-validation/adyntel-facebook-coldiq.json`.

### 2026-09-12 — Adyntel selected as the primary three-channel ads provider

- The user selected Deepline's managed Adyntel integration as the primary ads
  source because one provider covers Meta, LinkedIn, and Google. Apify remains a
  fallback and immutable replay source rather than being deleted.
- Live catalog inspection confirmed `adyntel_facebook`, `adyntel_linkedin`, and
  `adyntel_google` are connected at 0.13 credits ($0.013) per company/channel
  call. All accept a bare company domain.
- A ColdIQ Google pilot reported 44 total creatives and returned ten dated rows
  with official Google Ads Transparency Center evidence URLs. A ColdIQ LinkedIn
  domain lookup resolved page ID 65826193, reported 214 total ads, and returned
  24 first-page rows.
- The documented LinkedIn page-ID input is currently coerced by the Deepline CLI
  and rejected upstream as the wrong type. The collector therefore records a
  verified page ID as an identity hint but sends the domain until this contract
  mismatch is fixed.
- Provider-reported totals and returned rows are distinct. Continuation tokens
  or totals larger than the response are persisted as partial coverage, not
  represented as a complete count. Empty raw payloads remain inconclusive.
- Added `collect-adyntel-ads`, a provider-neutral normalizer and guarded merge
  policy. Successful selected platforms replace older normalized platform rows;
  failed or inconclusive platforms preserve existing Apify evidence. Paid calls
  are single-attempt and full envelopes, hashes, billing, and job IDs remain
  auditable.
- End-to-end runs confirmed the boundary on both real accounts. ColdIQ saved 24
  LinkedIn and ten Google rows against provider totals of 214 and 44; Meta again
  returned no payload and stayed inconclusive. DailyPay saved ten rows per
  channel against totals of 16 Meta, 318 LinkedIn, and 200 Google ads.
- DailyPay exposed Meta's distinct `results`/`number_of_ads` response shape. The
  first implementation had persisted the envelope but lost its audit pointer
  when normalization rejected the shape. The failure path now retains response
  hashes, billing, and job IDs, and `replay-adyntel-ads` repaired the saved
  response locally without another paid call.
- This uses one provider relationship but still invokes three channel-native
  tools. The two-account end-to-end collection cost 0.78 credits ($0.078), and
  first-page truncation remains explicit. The complete suite passes 122 tests.
