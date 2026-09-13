---
name: gtm-channel-gap-analysis
description: Build, run, or extend evidence-backed analysis of B2B opportunities for content syndication, retargeting, programmatic advertising, and outbound calling. Use for account website intelligence, channel-readiness scoring, provider integrations, or auditable outreach qualification.
---

# GTM channel gap analysis

Produce an auditable account assessment, not a claim of externally unknowable absence.

## Operating rules

- Analyze `fit`, `readiness`, `gap evidence`, and `trigger` separately.
- Treat a missing tag, job phrase, page, or provider result as `unknown` unless independent evidence supports a gap.
- Preserve the source URL, excerpt, observed time, extraction method, and confidence for every material conclusion.
- Keep vendor payloads behind normalized provider adapters.
- Prefer deterministic extraction; use semantic classification for ambiguous pages and record its model/prompt version.
- Tie downstream outreach and outcomes to the exact evidence and scoring snapshot used.
- Do not submit forms, create accounts, or launch outreach without explicit authorization.
- Work in small milestones and validate each milestone against representative
  real public companies before broadening scope.
- Make canonical company enrichment the first pipeline stage. Persist one
  normalized account row keyed by canonical domain, then source every downstream
  provider input from that record: domain for website/technology/ads/search and
  numeric LinkedIn company ID for LinkedIn jobs. Reuse the cached record by
  default; require an explicit refresh before repurchasing firmographics.
- Use Prospeo through Deepline as the primary mechanical firmographic source.
  Never call Prospeo's API directly. Treat Prospeo's public documentation as
  semantic reference and Deepline's live Prospeo tool schema as the executable
  contract, billing surface, and source of truth when the two differ.
  If Prospeo returns a LinkedIn URL without its numeric ID, use a free exact-domain
  identity resolver and persist the merged identifiers. Keep Crunchbase funding
  as a separate required source rather than treating Prospeo funding as final.
- For a known domain, use cached company enrichment and never call Prospeo
  company search merely to duplicate that record. Reserve Prospeo company-search
  filters for account discovery or prequalification. Treat its hiring, funding,
  technology, news, growth, and website fields as candidate-selection hints;
  final scoring still requires the dedicated attributable evidence source.
- Validate Prospeo search filters against the live contract and current enum or
  suggestion values. Preserve `PLAN_REQUIRED` and `INVALID_FILTERS` as bounded
  provider outcomes; do not silently broaden, guess enums, or automatically
  repurchase a corrected query.
- Turn real observations into sanitized deterministic fixtures; unit tests must
  not depend on live websites or paid provider calls.
- Treat scoring weights and qualification thresholds as provisional until they
  are supported by documented real-company validation.
- Use local files and SQLite for early persistence unless the current milestone
  explicitly requires a remote store.
- Obtain live-provider credentials through an encrypted vault integration. Never
  write credentials into source files, fixtures, logs, databases, or raw payloads.
- Log blockers, resolutions, test coverage, and reusable lessons in
  `docs/DECISIONS_AND_LEARNINGS.md`, then update this skill when a lesson changes
  the operating procedure.
- Discover broadly from both sitemaps and rendered page links. Under a page cap,
  prioritize proof, substantial assets, segment/solution pages, and conversion
  paths ahead of bulk blogs, categories, tags, or tool directories; never rely on
  sitemap order as a representative sample.
- Persist the complete discovered URL inventory separately from fetched pages so
  crawl coverage and unobserved candidates remain auditable. “Discovered” must
  never be treated as “successfully fetched.”
- Do not classify an asset as gated merely because its page contains a form;
  global newsletter, contact, and footer forms commonly appear on every page.
  Require evidence connecting the form to the asset CTA/access path.
- Prefer explicit site-section semantics over product-name keywords. A tool named
  “ReportGarden” under `/tools/` is a tool page, not a report asset.
- Match form-purpose language on word/token boundaries; for example,
  `unsubscribe` must not satisfy a `subscribe` rule.
- Expect JavaScript form platforms to omit fields from server-rendered HTML.
  Preserve container identifiers/classes and surrounding form copy, and return
  unknown unless page-family context connects the form to an asset.
- Treat repeated global forms as independent assets or newsletter offers, not as
  proof that the current page is gated.
- Keep TLS certificate verification enabled. If a provider cannot use the local
  trust chain, use Scrapling's browser-backed transport with a locally installed
  browser. Do not switch to Parallel, curl, browser search, or another web
  collector; if Scrapling still fails, leave unobserved evidence unknown.
- Use Scrapling as the sole live web-collection provider for account research,
  website crawling, and channel-gap evidence. Derive normalized facts from its
  saved raw/normalized artifacts so every scored claim can be traced back to a
  Scrapling run.
- For a new website-only account pass, prefer `gtm-signals crawl-and-analyze`
  so collection, classification, asset analysis, candidate discovery, scoring,
  and the portable report share one run identity. Expect fit and gap to remain
  unknown until separately reviewed run-bound evidence is added.
- Accept a declared canonical URL only when its normalized path matches the
  fetched final URL path. Cross-path canonicals can collapse unrelated pages;
  repair historical runs from immutable raw `final_url` metadata with
  `repair-canonicals`, then regenerate every derived artifact and score.
- Treat asset indexes and paginated listing pages as taxonomy, not as individual
  assets. Confirm that an asset URL identifies a detail page before counting it.
- Attribute downloadable documents to the current asset using URL and anchor
  context. Exclude repeated legal, privacy, terms, accessibility, and consumer
  notice PDFs; a document extension alone is not asset evidence.
- Keep publication/creation dates separate from modification dates. Compute age
  against the page's observation time, and do not promote sitemap `lastmod` to a
  publication date. Ignore or flag near-identical `lastmod` values across many
  pages because they commonly represent a deployment or sitemap rebuild.
- Embedded application-state `createdAt`/`updatedAt` values may support content
  dates only when a single record is attributable to the detail page. If related
  records make attribution ambiguous, leave the date unknown.
- Separate observable substance from promotability. A gated asset offer can be
  a possible syndication candidate while the full asset's substance remains
  unknown; do not infer quality from landing-page length alone.
- A strong readiness score is not a qualified opportunity. Keep fit, readiness,
  gap, and trigger separate, and leave the overall total unset when a required
  component lacks evidence. Never substitute zero for unknown.
- Positive observations from a bounded priority crawl may establish readiness,
  but asset counts are lower bounds and cannot support absence claims. Cap or
  reduce score confidence when the crawl is incomplete and state the scope.
- Treat recent content production as only one possible trigger and cap its
  contribution until independent business-trigger evidence is available.
- Give configurable partial credit to visible gated offers whose full contents
  were not observed; do not score them like verified reusable assets.
- Persist the scoring configuration version/hash and the exact evidence snapshot
  identity with every score. Keep snapshot identity stable across replays that
  change only processing timestamps.
- Mark initial thresholds as provisional until labeled examples and outcomes
  support calibration. A behavior check on a few real companies is not a
  precision claim or authorization for automated outreach.
- Package default scoring configuration with an installed CLI and test config
  discovery outside the source working directory; source-relative paths alone
  fail under non-editable installs.
- Score account fit only from normalized facts with URL, excerpt, observation
  time, method, strength, and confidence. Keep first-party company claims
  distinguishable from independently verified facts.
- Do not require employee count as the universal scale proxy. Client count,
  revenue, transaction/access scale, funding capacity, or another sourced
  commercial indicator may be more relevant; normalize it to an explicit,
  configurable tier and retain the inference risk.
- Support multiple evidence items for buyer coverage. Do not stretch one client
  story or excerpt across personas it does not actually identify.
- Preserve hybrid business and sales motions as risks. A company may expose
  self-serve, enterprise, API, and service offers simultaneously; score only the
  evidenced motion relevant to the analyzed offer.
- When credible boolean or categorical fit evidence conflicts, leave that factor
  unknown and route it to review rather than averaging incompatible labels.
- Accept channel-gap claims only when their URL, content hash, observation time,
  and excerpt match a saved page from the current Scrapling run. Ad hoc research
  or a differently sourced crawl cannot inherit Scrapling provenance.
- Require positive gap evidence such as explicit expansion intent, a documented
  distribution bottleneck, an active partner/hiring search, or a documented
  performance shortfall. Asset volume and failure to observe a syndication
  footprint establish readiness or uncertainty, not a gap.
- Treat documented healthy or successful use of the channel as contradicting
  the gap. If credible supporting and contradicting evidence coexist, route the
  account to review until timing and scope are resolved.
- Keep gap-candidate discovery separate from scoring. Deterministic matches are
  pending review until a reviewer confirms the statement describes the account,
  channel, timing, and claimed limitation; candidate rules must not write
  directly to a scored profile.
- Rank targeted URLs by structural path meaning, not arbitrary substrings. Skip
  tool/catalog directories when extracting account-level gap claims, and do not
  combine labels from separate list items into a synthetic statement.
- For bounded targeted collection, validate same-domain URLs before fetching,
  deduplicate by canonical path rather than query variants, and regression-test
  that depth/page arguments reach the intended CLI branch. Prefer topical press
  detail slugs and listing-page link discovery over crawling every news item.
- Build targeted acquisition plans from saved same-domain discovery inventory,
  attributable ad destinations, and search rows with explicit Scrapling
  provenance. Keep plans bounded and hash their logical inputs; processing
  timestamps and unrelated profile mutations must not change plan identity.
- Require channel-specific slugs before selecting press or partner detail URLs.
  Broad press archives produce large noisy queues and consume page budgets
  without improving gap evidence.
- Treat a redirect to an unrelated path as a failed target, not as evidence for
  the requested URL. Persist successful and failed attempts, exclude both from
  automatic repeat collection, and require an explicit retry for failures.
- In a full account pipeline, run optional targeted acquisition after ad
  normalization and before exact-run gap resolution. Require an explicit page
  budget, persist all caps and retry intent, and defer scoring to the pipeline's
  single resolver stage so dependent scores are not rebuilt twice.
- Normalize every batch row into a versioned request whose hash includes the
  pipeline version, provider exclusions, collection budgets, and retry intent.
  Reject ambiguous boolean policy and let legacy jobs default to no additional
  gap acquisition rather than inheriting new live-request behavior.
- Build portfolio views from the latest persisted job per canonical domain and
  retain older job-policy counts for audit. Rank only known priority scores,
  keep unavailable reports visible, and present account priority separately
  from channel qualification.
- When an analyst supplies an exact high-value target, require it to exist in
  the saved discovery inventory and enqueue it before ordinary targets so the
  explicit priority cannot be lost to a previously queued copy.
- Require grammatical context for candidate phrases—for example, first-person
  expansion intent or a compact performance statement. A word such as “Low” or
  “scaling” near an unrelated lead-generation listing is not evidence.
- Store campaign launches, new channel/team launches, and marketing hiring in a
  trigger/initiative candidate stream separate from channel-gap evidence. These
  can explain timing but do not prove a missing or underperforming channel.
- Treat demand-generation, paid-media, performance, growth, and acquisition
  hiring as a distinct business-timing signal. Treat attributable funding-round
  announcements as another direct timing signal. Neither becomes channel-gap
  evidence unless the same saved excerpt explicitly documents a channel
  expansion, bottleneck, partner search, or performance shortfall.
- For retargeting and programmatic gap scoring, require at least two distinct
  approved supporting signal types. Bind each item to an exact Scrapling URL,
  content hash, observation time, and excerpt; route mixed supporting and
  contradicting evidence to review, and let explicit healthy-channel evidence
  disqualify the gap. No candidates must remain unknown.
- Treat outbound calling as a separate reviewed channel, not as a synonym for
  general sales motion. Buyer coverage, operating scale, conversion paths, and
  customer proof establish only readiness. Require at least two distinct,
  approved outbound gap types before qualification; public silence about an
  internal calling program remains unknown.
- At both export and standalone scoring time, revalidate outbound observations
  against the exact saved Scrapling URL, content hash, observation time, and
  excerpt. Validate signal polarity against the configured support and
  contradiction sets so an edited profile cannot invert meaning.
- Count distinct conversion-path types for readiness, not the number of URLs;
  repeated demo or contact links otherwise inflate the score. Freeze named
  readiness factors in outreach snapshots so outcome analysis can calibrate
  signal usefulness later.
- Collect hiring through three separately attributed sources: LinkedIn Jobs via
  Deepline/HarvestAPI using an authoritative LinkedIn company ID, Google for
  Jobs via Deepline/OpenWebNinja with exact employer-name or employer-domain
  validation, and same-domain career pages through Scrapling. A completed
  search with no attributable rows is scoped coverage, not proof of no hiring.
- When an identifier is resolved after an initial partial job run, rerun only
  the missing source and merge it with hash-verified saved sources. Do not
  repurchase or overwrite already completed Google or LinkedIn job evidence.
- Use Crunchbase through a callable Deepline Crunchbase contract as the primary
  structured funding source. Do not relabel Aviato, another aggregator, or a
  first-party announcement as Crunchbase. Company press releases may corroborate
  funding but are not a substitute for the requested Crunchbase source.
- Discover that contract from the live Deepline catalog and require the provider
  field to equal `crunchbase`, then inspect its live input schema before use.
  Persist the catalog response and provider payload with hashes. If unavailable,
  save `blocked_provider_unavailable`; retry funding independently from the
  cached company so a retry never repurchases Prospeo.
- Preserve a source date only when it is attributable to the saved page through
  publication metadata or an unambiguous page date. Relative copy such as
  “soon” is not a publication date; retain the observation time and leave the
  source date unknown.
- Deduplicate repeated rule matches for the same signal on one page, while
  retaining separate page occurrences for provenance and later entity review.
- Keep initiative reviews in tables and profiles separate from gap reviews.
  Require the same exact run, content-hash, observed-time, URL, and excerpt
  binding before reviewed initiative evidence can affect trigger scoring.
- Apply trigger freshness against an explicit scoring date. Do not substitute
  crawl observation time for an unknown event/publication date; cap the score
  and confidence of undated evidence instead.
- Combine recent-content activity and reviewed initiative trigger evidence by
  maximum rather than addition unless independent calibration demonstrates that
  they are non-overlapping signals.
- Persist candidate review separately from run-specific occurrences. Repeated
  ingestion of the exact reviewed run/content hash may retain its decision, but
  changed content or a later run must return the current candidate to pending;
  preserve the older append-only review for historical replay.
- Bind every review to the exact run and content hash inspected. Do not transfer
  approval to changed content or a later crawl automatically, and keep older
  reviewed occurrences replayable for historical scoring.
- Require reviewer identity and rationale for approve/reject decisions. Require
  an explicit evidence strength and confidence for approval; candidate-rule
  output cannot supply those judgments automatically.
- Audit every scoring entrypoint, including legacy/example commands, for absence
  inference. A newer evidence-safe pipeline does not compensate for an older CLI
  path that assigns gap or trigger points from missing observations.
- Normalize paid-ad destinations into both observed and canonical URLs; preserve
  UTM and click identifiers separately. Technology detection must include its
  source, confidence, and limitations and cannot prove complete or active use.
- Attribute name-searched ad-library rows only through an exact normalized
  advertiser-name match or an account-domain destination. Shortened or
  platform-hosted destinations make domain-only attribution incomplete, while
  fuzzy advertiser names create false positives.
- Use the narrowest provider-supported account query, preserve unmatched rows as
  raw data, and support free replay of saved datasets when normalization changes.
  Accept documented direct-row and result-envelope variants; an empty completed
  provider result is collection coverage, never proof that advertising is absent.
- Make corrective paid-provider runs platform-selective and preserve the other
  platform's prior evidence and provenance. Never automatically retry an
  ambiguous paid start.
- Persist user-directed platform exclusions explicitly. A skipped channel must
  not be collected or sent to a fallback provider, and must be represented as
  `not_collected_by_decision` rather than zero, unknown-provider failure, or
  evidence of absence. Retain older raw evidence for audit.
- Prefer a verified provider entity ID over company-name search and persist the
  identity type/value used. A successful zero-result name query is not adequate
  coverage when an authoritative entity-ID page exists.
- Do not require a click destination to retain an attributable ad as activity
  evidence. Represent an unavailable destination as null and exclude that ad
  from landing-page and tracking metrics.
- Distinguish an explicit, documented zero-result response from an empty or
  missing provider payload. The latter is inconclusive and must not become
  negative channel evidence. Do not repeat a request-priced lookup merely to
  recover output lost by a client/export failure without fresh authorization.
- Freeze the exact score and evidence snapshot before recording an authorized
  outreach send. Attribute downstream outcomes to that snapshot and evaluate
  meetings/opportunities by signal and channel, not reply rate alone.
- Export sales-ready evidence bundles only after every qualification gate passes.
  A review report for an insufficient-evidence account is not a qualified bundle.
- Keep a six-signal account-priority score separate from channel qualification.
  Firmographic fit, hiring, funding, advertising, technology, and website
  evidence can rank an account for review, but they do not establish a gap.
  When normalizing over known signals, propagate each signal's internal evidence
  coverage into aggregate coverage and confidence instead of treating a partial
  signal as fully observed.
- Make gap review application a provider-free, idempotent replay. Rediscover and
  ingest deterministic candidates, export only approvals bound to the current
  run and page hash, then rebuild every dependent channel and account score.
  Use `review_required` only when candidates are pending or evidence conflicts;
  an empty queue with unresolved gaps is `insufficient_evidence`.
- Maintain a sanitized labeled benchmark for classifier precision. Report its
  sample size and limits; do not generalize fixture precision to the production
  population.

## Route the work

- For architecture, schemas, or provider work, read [`references/system-design.md`](references/system-design.md).
- For website asset, gating, funnel, segmentation, and proof detection, read [`references/website-intelligence.md`](references/website-intelligence.md).
- For scoring, qualification, or outreach evidence rules, read [`references/qualification.md`](references/qualification.md).

## Expected outputs

Depending on the request, return one or more of:

- Normalized evidence records
- Page/content classifications
- Account-level website metrics
- Channel opportunity scores with confidence and risks
- A QA-ready evidence bundle
- Provider adapters, migrations, fixtures, or tests

When implementing repository changes, follow `AGENTS.md` and the current execution phase in `docs/CODEX_EXECUTION_BRIEF.md`.
