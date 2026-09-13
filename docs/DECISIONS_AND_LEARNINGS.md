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

### 2026-09-12 — Deterministic Adyntel creative analysis V1

- Added a local-only, versioned creative-analysis stage over saved Adyntel
  responses. It makes no provider or AI calls and can be replayed whenever the
  rules change.
- Provider inventory and inspected creatives remain separate measurements.
  ColdIQ has 258 provider-reported ads across conclusive channels and 34 rows
  inspected; DailyPay has 534 and 30 respectively. Each platform retains its
  exact coverage ratio and a sample-confidence band.
- Raw records are joined to normalized evidence by platform and provider ad ID.
  The analyzer verifies each raw response against the SHA-256 recorded at
  collection time before using advertiser, headline, body, CTA, creative type,
  media, destination, and activity metadata.
- Real Google results exposed a semantic-quality trap: strings such as
  `DailyPay, Inc. — Text` are advertiser/format metadata, not creative copy.
  Classification now uses raw headline/body/CTA fields when a raw record is
  available. Redacted or absent provider content remains unknown and does not
  lower account qualification.
- Provider-specific format labels are collapsed into format families; Meta
  distribution surfaces such as Facebook and Instagram are stored separately
  rather than incorrectly counted as different creative formats.
- V1 is deliberately text-and-metadata only. Image and video URLs are retained,
  but their pixels/audio are marked `not_performed`; multimodal creative review
  is a later milestone rather than an inferred result.
- Ad-library totals are inventory evidence, not proof that every channel is
  currently active. The aggregate therefore says `observed_ad_platforms`; each
  creative's current/recent/historical state is derived separately from an
  explicit provider flag or saved dates, and otherwise remains unknown.
- ColdIQ's 24 analyzable LinkedIn creatives emphasize pipeline/growth and
  marketing/GTM themes; its ten Google rows expose formats and dates but no
  usable text. DailyPay has 20 analyzable creatives across LinkedIn and Meta;
  its ten Google rows likewise lack usable creative text. These are sample-level
  observations, not claims about the complete inventory.

### 2026-09-12 — Paid-channel scoring V3 uses known-evidence normalization

- Added `paid_channels_v3` without modifying V1 or V2. Score snapshots now
  include the creative-analysis file and SHA-256 so every creative-derived
  point is bound to an immutable input version.
- V3 factors cover provider inventory, observed platform diversity,
  current/recent creative evidence, tracked destinations, relevant technology,
  content inventory/diversity, creative formats, funnel stages, and messaging
  themes. Thresholds and weights live in configuration.
- The first implementation incorrectly converted ColdIQ's historical Google
  sample plus undated LinkedIn sample into zero current creatives. The corrected
  rule returns unknown when zero current evidence coexists with unknown activity
  states; positive active/recent evidence remains usable.
- Missing destination URLs in partial provider samples also remain unknown. A
  zero is allowed only when collection is complete, while an observed tracked
  URL is always positive evidence.
- Readiness is normalized over known factor weights. Unknown factors reduce the
  explicit evidence-coverage ratio and final confidence, preventing sparse
  evidence from qualifying merely because the known-factor score is high.
- ColdIQ V3 readiness is 97.6 retargeting with review status at 0.70 evidence
  coverage, and 93.8 programmatic with provisional-pass status at 0.80 coverage.
  DailyPay is 98.0 retargeting and 100.0 programmatic, both provisional-pass;
  its tracked destinations remain unknown in the partial Adyntel sample. Gap
  evidence remains unknown for both accounts.

### 2026-09-12 — Resumable one-command account workflow

- Added `run-account-v1` to connect Scrapling analysis, Deepline/BuiltWith,
  Deepline/Adyntel Meta/LinkedIn/Google, selective Apify fallback, deterministic
  creative analysis, `paid_channels_v3`, and a decision-ready JSON/Markdown
  report.
- Every stage is checkpointed in `normalized/account_pipeline.json`; batch jobs
  mirror those checkpoints to the new `analysis_job_stages` SQLite table.
- Resume logic reuses completed website artifacts instead of rescanning the raw
  directory. This matters because provider envelopes intentionally share the
  run's raw boundary but are not Scrapling page metadata.
- BuiltWith is not automatically retried after a paid attempt. Adyntel purchases
  only missing platforms, and a truncated first page remains a valid partial
  result that is not repurchased. Apify fallback applies only to failed or
  inconclusive Meta/LinkedIn collection, never to partial samples or explicit
  zero results.
- The report keeps provider totals separate from inspected creatives, includes
  cost and evidence coverage, and renders unresolved collection as unknown
  rather than a zero or an absence claim.
- Initial strict-Adyntel resume validation produced a complete DailyPay report
  at the already observed 0.53-credit ($0.053) provider cost. ColdIQ's primary
  Meta response remained inconclusive; the later five-account pass incorporated
  its retained explicit-zero Apify fallback without repeating a provider call.

### 2026-09-12 — Five-account acceptance and provider hardening

- Ran the complete bounded workflow on HubSpot, Gong, and Linear, then combined
  them with ColdIQ and DailyPay for a five-account acceptance set. Each new
  website crawl was capped at 30 pages and all paid stages were single-attempt.
- HubSpot completed with 839 technology detections and Adyntel totals of 74
  Meta, 1,410 LinkedIn, and 4,000 Google ads. Gong completed through a 25-ad
  LinkedIn fallback after Adyntel LinkedIn failed. Linear remains partial:
  Adyntel LinkedIn failed and all 25 name-search fallback candidates failed
  strict attribution, so the signal remains unknown.
- A single unnamed item in Gong's otherwise valid BuiltWith response originally
  invalidated the full paid result. Normalization now skips and audits malformed
  technology rows, and a hash-checked local replay recovered the response
  without a second provider call.
- Meta returned a provider total of zero plus a continuation token for Gong and
  Linear. An explicit zero with zero returned rows now wins over the contradictory
  token and is stored as `none_observed`, not an unknown and not a claim about
  activity outside the provider's observed scope.
- Apify `SUCCEEDED` describes actor execution, not evidence quality. When an
  actor returns candidates but strict normalization attributes none to the
  account, the provider stage is now `inconclusive` and remains a blocker.
- Deepline balance moved from 227.52 to 225.93: exactly 1.59 credits ($0.159),
  matching three BuiltWith and nine Adyntel attempts. Two failed LinkedIn CLI
  calls lacked billing fields in their response files but appeared later in the
  billing ledger. Reports now distinguish captured cost from complete cost.
- Gong and Linear Apify fallbacks cost $0.03205 and $0.09605 respectively. The
  total new-account provider spend was $0.28710. No paid request was retried.

### 2026-09-13 — ColdIQ Meta enrichment explicitly skipped

- The user removed ColdIQ Meta enrichment from the active collection scope.
- Added repeatable `--skip-ad-platform` support to `run-account-v1` and batch
  requests. Skipped platforms are excluded from Adyntel collection and Apify
  fallback, including on a fresh run.
- A skip is persisted as `not_collected_by_decision`. It is not translated into
  zero activity, negative gap evidence, or a blocker. Historical raw artifacts
  are retained rather than deleted or rewritten.
- The ColdIQ authoritative run was replayed locally with Meta skipped. No paid
  provider call was made.

### 2026-09-13 — Demand-gen hiring, funding, and paid-gap review

- Demand-generation, paid-media, performance, growth, acquisition, and ads
  roles are now surfaced as a distinct `active_demand_generation_hiring`
  candidate. Broader content, brand, and marketing-operations hiring remains a
  separate lower-weight business-timing signal.
- Attributable company announcements that explicitly state a raise, close,
  secure, or funding announcement are surfaced as `funding_round_announced`.
  Funding-oriented press-detail slugs receive targeted-crawl priority.
- Hiring and funding stay in the initiative/trigger stream. They do not prove a
  retargeting, programmatic, or syndication gap unless the same saved statement
  explicitly documents a channel limitation or expansion need.
- Added a separate SQLite review queue for retargeting/programmatic gap
  candidates. Discovery uses saved Scrapling pages only; approval binds URL,
  content hash, observation time, matched text, reviewer, rationale, strength,
  and confidence before merging evidence into the external profile.
- Paid-channel V3 now requires two distinct approved positive gap signal types,
  a score of at least 45, and confidence of at least 0.70. Mixed positive and
  contradictory evidence routes to review; explicit healthy/successful channel
  evidence disqualifies the gap. Public-web absence remains unknown.
- External ATS pages are not followed automatically in this increment. Current
  hiring coverage is first-party and same-domain; a missing job signal therefore
  means unknown, not no hiring. A later bounded collector may follow only ATS
  URLs discovered from an authoritative company careers page.

### 2026-09-13 — External job-source routing and Crunchbase boundary

- Hiring now has three explicit collection surfaces: first-party career pages
  via Scrapling, LinkedIn Jobs via Deepline/HarvestAPI, and Google for Jobs via
  Deepline/OpenWebNinja. Provider payloads, billing, response hashes, query
  scope, and normalized records remain separate.
- LinkedIn Jobs requires an authoritative company ID. Without it the source is
  `skipped_missing_identifier`; a broad title search is not accepted as company
  coverage. Google results require exact employer-name or employer-domain
  attribution because quoted queries can still return unrelated employers.
- Role classification includes demand generation, paid media/acquisition,
  performance/growth marketing, and GTM/growth/marketing engineering. Unrelated
  roles are retained only in raw provider responses.
- The ColdIQ pilot returned one attributable LinkedIn role: `GTM Engineer`.
  Google returned ten unrelated employers and therefore normalized to zero.
  The DailyPay pilot returned one attributable Google-for-Jobs role: `Senior
  Growth Marketing Manager, Acquisition & Paid`. A focused company lookup
  resolved DailyPay's LinkedIn company ID as `10497554`; the resulting
  company-ID-scoped LinkedIn Jobs request completed with zero matching roles,
  so both external sources now have bounded attributable coverage.
- The two-account job pilot used 0.16 Deepline credits ($0.016): one LinkedIn
  page and one Google Jobs request per account. Saved responses can be replayed
  without another provider request.
- Resolving DailyPay's LinkedIn identity used 0.03 additional credits and its
  corrective LinkedIn-only jobs request used 0.01. Selective collection now
  preserves the previously purchased Google Jobs source and normalized rows,
  preventing a corrective source run from rebuying or overwriting other source
  evidence.
- Live Deepline discovery exposed no callable Crunchbase provider in the current
  workspace. `aviato_get_company_funding_rounds` accepts a Crunchbase ID but is
  explicitly an Aviato source, so it is not used or relabeled. First-party
  funding discovery remains corroboration only until the Crunchbase contract is
  available. An attempted provider-availability feedback submission was blocked
  by the external-data approval boundary and no session data was sent.

### 2026-09-13 — Company enrichment becomes the pipeline identity gate

- Company enrichment now runs before website, technology, jobs, ads, or search.
  The normalized SQLite `accounts` row is the canonical source for company name,
  domain, LinkedIn URL and numeric company ID, employee size, revenue range,
  industry, headquarters, company type, founding year, Prospeo ID, Crustdata ID,
  and Crunchbase URL.
- Deepline's research-workflow documentation reinforced the durable contract:
  preserve the stable input row, source URL or record ID, unresolved reason, and
  review boundary. Raw provider payloads therefore remain in account-level files;
  append-only database snapshots retain their paths, SHA-256 hashes, billing,
  observation times, and normalizer version.
- Prospeo is the primary mechanical firmographic source. If it returns a
  LinkedIn URL without the numeric ID, the waterfall calls the free exact-domain
  Crustdata identity tool. Downstream LinkedIn Jobs consumes the stored numeric
  ID; Scrapling, BuiltWith, Adyntel, and Google search consume the stored domain.
- Cache reuse is the default. Only explicit `--refresh` can repurchase Prospeo.
  An already-saved provider response can be imported with `--prospeo-response`,
  which was used for the ColdIQ pilot rather than repeating its lookup.
- The real ColdIQ profile stores 44 employees, a 21-50 range, Advertising
  Services, LinkedIn company ID `65826193`, and its Crunchbase organization URL.
  DailyPay stores 987 employees, a 501-1000 range, Financial Services, a
  $250M-$500M revenue range, LinkedIn company ID `10497554`, and its Crunchbase
  organization URL.
- The live Prospeo pilot cost 0 credits for ColdIQ because the response was
  flagged as a free enrichment and 0.55 credits ($0.055) for DailyPay. The
  exact-domain identity fallback is free. Subsequent account-pipeline replays
  showed zero new company-enrichment cost because both records were cache hits.
- DailyPay's live Prospeo result returned revenue as a `{min,max}` object. The
  first persistence attempt rejected that value instead of coercing it. Because
  the raw envelope had already been written, normalization was fixed and the
  saved response was replayed without another paid request.
- Prospeo also returned a DailyPay funding observation. It is stored as
  non-authoritative context only; the account remains partial because the user
  requires Crunchbase through Deepline for funding scoring and that callable
  contract is not currently exposed.

### 2026-09-13 — Prospeo search filters are sourcing criteria, not duplicate enrichment

- Prospeo is accessed only through Deepline. The public Prospeo documentation
  describes upstream filter semantics; it does not authorize direct Prospeo API
  requests. Every execution must use a connected Deepline Prospeo tool and
  preserve Deepline billing and provider-envelope provenance.
- A live, read-only Deepline contract inspection confirmed that
  `prospeo_search_company` is connected with managed credentials and is priced
  at 0.55 Deepline credits ($0.055) per returned result. No search was executed.
- Deepline's current adapter exposes a narrower contract than the latest
  Prospeo page. It includes core firmographic, funding, technology, headcount
  growth, hiring-title/count, department-headcount, MX-provider, and pagination
  fields, but not the documented news, intent, website-search, traffic,
  key-executive, ICP, product/service, integration, award, or language filters.
  It also represents some inputs differently, including hiring titles as an
  array and company type as a scalar enum. Code must validate against Deepline's
  live schema and must not forward undocumented fields directly to Prospeo.
- The official Prospeo filter documentation distinguishes `/search-company`
  filters from per-company enrichment. A known domain continues through the
  cached `prospeo_enrich_company` identity gate; calling company search for that
  same account would add cost and a second, unnecessary source path.
- A future account-discovery stage can use Prospeo filters for company identity,
  location, headcount/range, industry, revenue, type, founding year, headcount
  growth, technologies, active job titles/count, and funding stage/date/amount.
  Newer upstream filters may be added only after they appear in Deepline's live
  contract.
- `company_funding`, `company_technology`, `company_job_posting_hiring_for`, and
  `company_job_posting_quantity` require at least Prospeo Starter. Website
  full-text/structure search, Google discovery, key-executive events, and
  traffic filtering require Pro; some additional fields require Growth.
  `PLAN_REQUIRED` and `INVALID_FILTERS` must be preserved as explicit provider
  outcomes rather than silently broadening or retrying a query.
- Search results are candidate-selection evidence only. Prospeo hiring filters
  do not replace attributable LinkedIn Jobs, Google Jobs, or career-page rows;
  Prospeo funding filters do not replace the required Crunchbase record; and
  technology filters do not replace the stored BuiltWith observation.
- Prospeo fixes results at 25 rows per page, caps page number at 1,000, limits
  total filter values to 20,000, and rejects exclude-only searches. Filter enums
  should be obtained from Prospeo's current enum/suggestion surfaces rather than
  invented locally.
- The page was retrieved successfully with the project's Scrapling adapter
  after Parallel extraction reported insufficient credit. No alternate web
  collector was used for the source review.

### 2026-09-13 — Cached profiles feed unified account scoring

- Added `unified_account_v1`, a configuration-driven score over firmographic
  fit, attributable hiring, required-source funding, advertising, technology,
  and website evidence. The score ranks positive account priority only; it does
  not assert a missing channel or authorize outreach.
- Unknown signals are omitted from the normalized numeric average and reduce
  coverage. A real ColdIQ replay exposed that partially observed inputs also
  need proportional weight: firmographic and advertising sub-coverage now
  flows into aggregate coverage and confidence.
- Channel outputs remain separate fit/readiness/gap/trigger evaluations. Any
  missing required component keeps the channel total null; positive advertising
  or website readiness cannot fill an unknown gap.
- Results persist in the versioned `unified_account_scores` SQLite table and in
  `normalized/unified_account_score.json`. Snapshot identity includes the
  scoring configuration and code-logic version plus stable upstream artifact
  IDs, so generation timestamps do not create duplicate logical snapshots.
- Cached replays produced DailyPay 91.7 priority, 90.0% coverage, and 74.9%
  confidence (`high_priority`), and ColdIQ 88.6 priority, 81.2% coverage, and
  58.9% confidence (`review`). Funding and all three channel gaps remain
  unknown for both accounts. No paid provider calls were made.

### 2026-09-13 — Channel-gap review becomes a single replayable stage

- Added `resolve-channel-gaps` to connect deterministic content and paid-gap
  discovery, idempotent SQLite ingestion, exact-run review export, all dependent
  scorers, and the account intelligence report. The full account pipeline now
  invokes the same stage after ad creative analysis.
- The workflow never approves rule matches automatically. Only human approvals
  bound to the current run and page content hash enter scoring; rejected and
  stale approvals remain historical audit records.
- Status semantics now distinguish work that is actually reviewable from absent
  evidence: pending candidates or conflicting approved evidence produce
  `review_required`, while an empty queue with unknown gaps produces
  `insufficient_evidence`.
- A deterministic integration fixture verifies that approved content and
  retargeting evidence updates only those channels while programmatic stays
  unknown. DailyPay and ColdIQ replays produced zero current candidates and all
  null channel totals, with priority scores unchanged at 91.7 and 88.6. No paid
  provider calls were made.

### 2026-09-13 — Targeted gap acquisition is planned, bounded, and resumable

- Added `plan-gap-evidence` to merge three saved sources: the complete
  same-domain discovery inventory, attributable ad destinations, and optional
  search rows carrying `scrapling_saved_serp` provenance. Generic search rows
  are rejected rather than silently entering the evidence path.
- An initial DailyPay plan admitted 106 broad press URLs. That was discovery
  noise, not a useful research queue. Press and partner detail pages now require
  a channel-specific slug (or an explicit partner-program path), while careers,
  campaign paths, ad destinations, and precise search results retain priority.
- Added `acquire-gap-evidence` to fetch only selected plan targets with
  Scrapling, preserve raw/normalized artifacts, and immediately replay the
  exact-run gap-resolution workflow. No alternate website provider is used.
- The live DailyPay check fetched the campaign strategy page successfully.
  Two legacy campaign URLs redirected to the homepage; cross-path redirects are
  now rejected and logged rather than misattributed as target-page evidence.
- Prior targeted attempts are persisted in the plan. Successful pages are
  excluded and failed targets require `--retry-failed`, preventing repeated
  requests to known dead routes. Logical plan hashes exclude timestamps and
  unrelated profile changes, so processing time alone does not change identity.
- Final replay selected no new pages: DailyPay had nine relevant targets, seven
  already fetched and two held failed targets; ColdIQ had three, all already
  fetched. All content-syndication, retargeting, and programmatic gaps remain
  null/`insufficient_evidence`. No paid provider calls were made.
- Validation: `docs/validation/2026-09-13-targeted-gap-evidence-acquisition.md`.

### 2026-09-13 — Targeted acquisition enters the account pipeline explicitly

- Added a budgeted `targeted_gap_acquisition` stage to
  `account_pipeline_v2`. It runs after ad normalization so attributable landing
  pages are available to planning, and before the existing exact-run resolver.
- The stage is opt-in: `--gap-evidence-pages 0` is the default. Target, page,
  and depth budgets plus the retry decision are persisted in the run's
  collection policy and checkpoint. Previously failed URLs are retried only
  with `--retry-gap-evidence`.
- Pipeline acquisition uses `gap_evidence_acquisition_v2` with deferred
  resolution. The pipeline's normal resolution stage then rediscovers evidence
  and rebuilds dependent scores exactly once.
- Enabling the stage in a realistic fixture exposed a latent missing import for
  `discover_gap_candidates`. Earlier tests did not create normalized pages and
  therefore missed the failing branch. The import is fixed and the integration
  fixture now exercises that path.
- Cached DailyPay and ColdIQ replays completed with paid collectors replaced by
  fail-fast sentinels, proving the integration made no paid request. Both
  acquisition stages returned `no_targets`; gap resolution remained
  `insufficient_evidence` rather than creating a zero score.
- Validation: `docs/validation/2026-09-13-account-pipeline-gap-acquisition.md`.

### 2026-09-13 — Batch jobs preserve the complete acquisition contract

- The batch runner already called `run_account_v1`, but its normalized request
  omitted all targeted gap-acquisition settings. A queued account therefore
  could not reproduce the equivalent single-account command.
- Added `account_job_v2` with the current pipeline version, page/target/depth
  budgets, and retry policy inside the hashed request. The runner forwards the
  stored values to `account_pipeline_v2`; legacy requests use safe defaults.
- Boolean collection authority is parsed strictly. Ambiguous CSV text is
  rejected instead of accidentally enabling a paid fallback or failed-target
  retry.
- Added a real-company example batch for DailyPay and ColdIQ. ColdIQ retains
  the user-directed Meta exclusion as request policy, not a zero observation.
- Validation: `docs/validation/2026-09-13-batch-gap-policy.md`.

### 2026-09-13 — Batch results become a priority portfolio, not a qualification shortcut

- Added `build-portfolio-report` to turn saved SQLite jobs and account reports
  into JSON, CSV, and Markdown without any provider call.
- Multiple job policies can exist for one domain. The portfolio selects the
  latest updated job as current and reports the history count instead of
  presenting duplicate accounts as separate prospects.
- Accounts with missing or malformed reports remain visible as unavailable and
  sort below known priority scores. They are not silently dropped or scored as
  zero.
- Priority score, evidence coverage, confidence, and channel qualification are
  separate output columns. The real-account replay ranks DailyPay 91.7 above
  ColdIQ 88.6, but both remain `insufficient_evidence` opportunities.
- Validation: `docs/validation/2026-09-13-portfolio-report.md`.
