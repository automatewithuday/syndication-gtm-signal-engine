# GTM Signal Engine

An evidence-first system for identifying B2B companies that are good candidates for content syndication, retargeting, programmatic advertising, and outbound calling.

The engine does **not** claim that a company is definitely missing a channel. It combines:

1. ICP fit
2. Channel readiness
3. Observable gap evidence
4. A timely business trigger

Every conclusion retains its source URL, excerpt, observation date, extraction method, and confidence so an agent or human can audit it before outreach.

## Version 1 status

Version 1 is a complete local review release. It includes:

- A portable coding-agent skill in `skills/gtm-channel-gap-analysis/`
- Typed domain models and deterministic website classifiers
- Configurable opportunity scoring
- A CLI and example input that run without paid APIs
- Scrapling-only live website collection with bounded, resumable crawls
- Live Deepline CLI/BuiltWith and guarded Apify advertising collectors, plus a
  provider-neutral recorded Scrapling search adapter
- Versioned SQLite migrations, batch jobs, review queues, evidence snapshots,
  and outcome measurement
- Qualification-gated evidence bundles that prevent unsupported outreach claims
- A 138-test fixture-only suite covering classification, scoring, persistence, workflow, and
  validation behavior

The [DailyPay and ColdIQ review](reports/REAL_ACCOUNT_REVIEW.md) demonstrates the
system on two real companies. Raw crawl bodies and local databases are excluded
from Git because they can contain copied website content or incidental personal
data.

## Quick start

Requires Python 3.11+.

```bash
uv sync
uv run gtm-signals analyze examples/account.json --pretty
uv run pytest -q
```

Or install it as a package:

```bash
python3 -m pip install -e .
gtm-signals analyze examples/account.json --pretty
```

For a bounded live website crawl, install the optional scraper and run:

```bash
uv sync --extra scrape
uv run gtm-signals crawl dailypay.com --maximum-pages 100
uv run gtm-signals crawl coldiq.com --maximum-pages 100
```

Run the complete Phase 1 website workflow and write one portable report:

```bash
uv run gtm-signals crawl-and-analyze example.com \
  --account-name Example \
  --maximum-pages 100 \
  --output reports/example.json
```

The report contains observed asset evidence plus provisional readiness and
trigger scores. Fit and gap remain explicitly unknown until run-bound evidence
is reviewed; missing public evidence never becomes a zero or an absence claim.

Run the complete V1 account-intelligence workflow with stage checkpoints:

```bash
uv run gtm-signals run-account-v1 example.com --account-name Example
```

This runs Scrapling website analysis, Deepline/BuiltWith, all three
Deepline/Adyntel channels, local creative analysis, `paid_channels_v3`, and a
JSON/Markdown decision report. Resume an existing run without repurchasing
completed or partial provider stages:

```bash
uv run gtm-signals run-account-v1 example.com --account-name Example \
  --resume-run data/runs/<run-id>
```

Skip a deliberately out-of-scope ad channel without treating it as a zero:

```bash
uv run gtm-signals run-account-v1 coldiq.com --account-name ColdIQ \
  --resume-run data/runs/<run-id> --skip-ad-platform meta
```

The skip is persisted as `not_collected_by_decision`. Existing raw observations
remain available for audit, but the skipped platform is not called, retried, or
used as evidence of channel absence.

Apify is invoked only for failed or inconclusive Meta/LinkedIn Adyntel stages;
use `--no-apify-fallback` to keep a strictly Adyntel-only run. Provider totals
and inspected rows remain separate, and a partial first page is a successful
paid observation rather than a retry condition. The run writes
`normalized/account_pipeline.json` plus
`normalized/account_intelligence.{json,md}`.

Scrapling is the sole live web-collection provider for this project. Do not
silently fall back to Parallel, generic browser research, curl, or another
scraper. If Scrapling cannot retrieve a source, keep certificate verification
enabled. The adapter may switch from Scrapling's static transport to its
browser-backed transport for certificate-chain failures; this remains within
Scrapling and uses a locally installed Chrome when available. If both transports
fail, record the collection as incomplete. Unobserved facts remain `unknown`.

On macOS, if Python skips the generated editable `.pth` file because the file is
marked hidden, use `uv sync --extra scrape --no-editable` and resync after source
changes. This keeps the workaround explicit instead of modifying virtualenv
metadata by hand.

Live crawl output is written beneath `data/runs/<run-id>/`, with provider/raw
responses separated from normalized `pages.jsonl`. The complete canonical URL
inventory is retained in `normalized/discovered_urls.jsonl`, even when the page
fetch budget is smaller than the discovered site. The run manifest records
partial failures and crawl limits. Live output is intentionally gitignored;
tests use sanitized fixtures and never contact target websites.

Older Scrapling runs created before cross-path canonical validation can be
repaired from immutable raw final-URL metadata, then reanalyzed:

```bash
uv run gtm-signals repair-canonicals data/runs/<run-id>
```

Classify a saved crawl without making additional web requests:

```bash
uv run gtm-signals classify-crawl data/runs/<run-id>
```

This writes `normalized/evidence.jsonl` and
`normalized/classification_summary.json`. Classification is versioned and does
not imply that the account is qualified or ready for outreach.

Assess the classified assets for publication/creation dates, observable
substance, and content-syndication suitability without making another request:

```bash
uv run gtm-signals analyze-assets data/runs/<run-id>
```

This writes `normalized/assets.jsonl` and `normalized/asset_summary.json`.
Freshness uses the crawl's observation time, distinguishes publication/creation
from modification, and leaves dates unknown when only an unreliable batch-like
sitemap timestamp is available. `possible` suitability means an asset offer was
observed but its gated contents or reuse rights still require review.

Generate the provisional content-syndication readiness score:

```bash
uv run gtm-signals score-syndication data/runs/<run-id>
```

The command writes `normalized/syndication_score.json`. Its factor thresholds,
component weights, confidence rules, and qualification thresholds come from
`config/content_syndication_scoring.v2.json`; pass another version with
`--config`. A readiness pass is not account qualification. Fit and gap remain
unknown until separately sourced evidence exists, so the overall opportunity
total remains `null` rather than treating missing evidence as zero or as proof
of an unused channel.

Add a sourced account-fit component, then regenerate the syndication score:

```bash
uv run gtm-signals score-fit data/runs/<run-id> examples/account-fit/dailypay.json
uv run gtm-signals score-syndication data/runs/<run-id>
```

The fit input is normalized evidence derived from saved Scrapling artifacts,
not an unrestricted provider response or an ad hoc web lookup.
Every fact requires a public URL, excerpt, observation time, strength, and
confidence. The scorer covers B2B model, professional buyers, sales motion, and
operating scale; conflicting categorical evidence stays unknown. Fit output is
written to `normalized/account_fit.json` and is automatically incorporated on
the next `score-syndication` run.

Score channel-gap evidence only after verifying it against pages saved by the
same Scrapling run:

```bash
uv run gtm-signals score-gap data/runs/<run-id> examples/channel-gap/dailypay.json
uv run gtm-signals score-syndication data/runs/<run-id>
```

Each non-empty observation must use `method: scrapling_saved_page` and match a
saved page's canonical URL, content hash, observation time, and excerpt. The
supported positive signals are explicit expansion intent, a documented
distribution bottleneck, an active partner/hiring search, and a documented
performance shortfall. Evidence of a healthy or successful current syndication
program contradicts the gap. An empty profile remains `unknown`; it is never
scored as zero.

Expand a saved Scrapling run with high-signal pages and surface review
candidates before creating a non-empty gap profile:

```bash
uv run gtm-signals collect-gap-targets data/runs/<run-id> --maximum-pages 10 --maximum-depth 2
uv run gtm-signals collect-gap-targets data/runs/<run-id> --maximum-pages 1 \
  --url https://example.com/press/releases/specific-launch
uv run gtm-signals discover-gap-candidates data/runs/<run-id>
uv run gtm-signals discover-initiative-candidates data/runs/<run-id>
```

Targeted collection ranks structural paths such as careers, jobs, partner
programs, demand-generation pages, topical campaign/launch/funding press releases, and
explicit syndication pages. It stays on the account domain, ignores query-string
duplicates, and can follow relevant links up to the bounded depth. Candidate
output is written to `normalized/gap_candidates.jsonl`; every record remains
`pending` and cannot be scored until reviewed and promoted into a gap profile.

Initiative discovery writes a separate
`normalized/initiative_candidates.jsonl`. Public campaign launches, new channel
or team launches, demand-generation/paid-media hiring, broader marketing hiring,
and funding rounds can provide trigger context, but they are never promoted
into channel-gap evidence. A source date is retained
only when it can be attributed to the saved page; relative job copy such as
“soon” does not establish a publication date.

Collect external demand-generation hiring from LinkedIn Jobs and Google for
Jobs through Deepline; the Scrapling crawl remains the career-page source:

```bash
uv run gtm-signals collect-deepline-jobs data/runs/<run-id> example.com \
  --account-name Example --linkedin-company-id <linkedin-company-id>
uv run gtm-signals replay-deepline-jobs data/runs/<run-id> example.com \
  --account-name Example --linkedin-company-id <linkedin-company-id>
```

LinkedIn collection is skipped when the authoritative company ID is missing.
Google job-board rows must match the exact employer name or employer domain.
Corrective single-source runs preserve previously collected sources and their
normalized records, so adding a LinkedIn ID does not rebuy Google Jobs data.
The replay command hash-checks saved responses and never makes a paid call.
Crunchbase-through-Deepline is the required structured funding source; the
current workspace does not expose that callable contract, so first-party press
announcements remain corroboration rather than a Crunchbase substitute.

Persist and review initiative candidates separately from the gap queue:

```bash
uv run gtm-signals ingest-initiative-candidates data/runs/<run-id>
uv run gtm-signals list-initiative-candidates --status pending
uv run gtm-signals review-initiative-candidate <candidate-id> \
  --decision approve --reviewer <name> --notes <reason> \
  --strength confirmed --confidence 0.9
uv run gtm-signals export-trigger-profile data/runs/<run-id> --account-name <company>
uv run gtm-signals score-trigger data/runs/<run-id> \
  data/runs/<run-id>/normalized/reviewed_trigger_profile.json
uv run gtm-signals score-syndication data/runs/<run-id>
```

Approvals bind to the exact run and content hash reviewed. Trigger scoring is
configuration-driven, discounts older evidence, and caps undated evidence.
The final syndication score combines content activity and reviewed initiatives
by their maximum rather than summing potentially overlapping signals.

Discover and review retargeting/programmatic gap evidence independently:

```bash
uv run gtm-signals discover-paid-gap-candidates data/runs/<run-id>
uv run gtm-signals ingest-paid-gap-candidates data/runs/<run-id>
uv run gtm-signals list-paid-gap-candidates --status pending
uv run gtm-signals review-paid-gap-candidate <candidate-id> \
  --decision approve --reviewer <name> --notes <reason> \
  --strength confirmed --confidence 0.9
uv run gtm-signals export-paid-gap-profile data/runs/<run-id> --account-name <company>
uv run gtm-signals score-paid-channels data/runs/<run-id> \
  data/runs/<run-id>/normalized/external_profile.json
```

Paid-channel V3 requires two distinct approved supporting signal types and the
configured score/confidence thresholds. Explicit healthy-channel evidence
disqualifies the gap; mixed evidence routes to review; no candidates remains
unknown. The current job-posting coverage is first-party/same-domain only, so
externally hosted ATS listings are a known coverage gap rather than evidence of
no hiring.

Persist candidates and review decisions locally in SQLite:

```bash
uv run gtm-signals ingest-gap-candidates data/runs/<run-id>
uv run gtm-signals list-gap-candidates --status pending
uv run gtm-signals review-gap-candidate <candidate-id> \
  --decision approve --reviewer <name> --notes <reason> \
  --strength confirmed --confidence 0.9
uv run gtm-signals export-gap-profile data/runs/<run-id> --account-name <company>
```

The default database is `data/gtm_signal_engine.sqlite3`; pass `--database` to
use another local file. Rejections and review history are retained across
re-ingestion. Approvals bind to the exact run and page content hash reviewed.
Export verifies the resulting profile against the saved Scrapling pages before
writing `normalized/reviewed_gap_profile.json`.

Collect live Deepline/BuiltWith technology observations after a Scrapling run:

```bash
npm install -g deepline@latest
deepline setup --json  # only when the CLI is not already authenticated
deepline preflight --json
uv run gtm-signals collect-deepline data/runs/<run-id> example.com
```

The integration uses Deepline's authenticated native CLI, so Deepline credentials
never enter the Python process or run artifacts. Before the paid lookup, the
collector inspects the current `builtwith_domain_lookup` contract and validates
its required input/output fields. It requests live technology data with PII and
company metadata disabled, makes one paid attempt without ambiguous automatic
retries, writes the immutable response under `raw/`, updates
`normalized/external_profile.json`, and records cost and explicit incomplete
failure state in `normalized/deepline_collection.json`.

Score normalized external ad/technology observations for paid channels:

```bash
uv run gtm-signals score-paid-channels \
  data/runs/<run-id> data/runs/<run-id>/normalized/external_profile.json
```

The normalized profile preserves observed and canonical campaign URLs, UTM and
click identifiers, source provenance, confidence, and technology-detection
limitations. Without approved positive gap evidence, paid-channel gap scores
remain unknown. The default `paid_channels_v3` scorer consumes the saved
creative-analysis artifact, records its hash in the score snapshot, normalizes
readiness over known evidence, and leaves unavailable creative activity or
destination factors unknown instead of awarding zero points. Pass an older
configuration explicitly when reproducing a V1 or V2 score.

Collect all three paid-ad channels through Deepline's managed Adyntel tools:

```bash
uv run gtm-signals collect-adyntel-ads \
  data/runs/<run-id> example.com
```

Adyntel is the primary live ads provider. The collector inspects each live tool
contract, then makes exactly one paid request per selected platform (`meta`,
`linkedin`, and `google` by default). Every full response is stored and hashed;
billing, job IDs, returned rows, provider-reported totals, and pagination state
are recorded in `normalized/adyntel_collection.json`. A response with empty
`raw`/`rawV2` fields is inconclusive and does not erase usable evidence from an
earlier provider. Provider totals can exceed the returned first page, in which
case the run is explicitly partial rather than pretending the saved rows are a
complete ad count.

Use `--platform` for a bounded correction. `--linkedin-page-id` records a
verified identity hint, while domain lookup is sent until Deepline resolves the
current page-ID type mismatch in the live Adyntel contract.

Re-normalize an already stored envelope after a parser fix without paying for a
new provider call:

```bash
uv run gtm-signals replay-adyntel-ads \
  data/runs/<run-id> example.com --platform meta \
  --response data/runs/<run-id>/raw/deepline-adyntel_facebook-response-<hash>.json
```

Analyze the saved Adyntel creatives locally after collection or replay:

```bash
uv run gtm-signals analyze-ad-creatives data/runs/<run-id>
```

This writes `normalized/ad_creative_analysis.json`. The versioned deterministic
classifier separates provider totals from inspected rows, records exact sample
coverage and inventory tiers, and classifies usable copy by funnel stage,
offer, audience, message theme, and creative format. Redacted or missing copy
remains unknown. Provider
raw responses are hash-verified before their richer fields are used, while the
normalized output retains evidence URLs, observed times, methods, confidence,
and raw-file lineage. V1 analyzes text and metadata only; it does not claim to
understand image or video contents. The aggregate `scoring_inputs` block is the
stable boundary for the next paid-channel scoring revision.

Apify remains a fallback/replay path for LinkedIn and Meta. Collect observations
after storing a scoped Apify
token in macOS Keychain Access. Use account `provider-secrets` and service
`gtm-signal-engine:apify-token`; do not place the token in a tracked file or a
shell command.

```bash
uv run gtm-signals collect-apify-ads \
  data/runs/<run-id> example.com --account-name "Example"
```

When the LinkedIn company ID is known, prefer it over name search:

```bash
uv run gtm-signals collect-apify-ads \
  data/runs/<run-id> example.com --account-name "Example" \
  --linkedin-company-id 12345678 --platform linkedin
```

The fallback's versioned default uses
[`silva95gustavo/linkedin-ad-library-scraper`](https://apify.com/silva95gustavo/linkedin-ad-library-scraper)
for LinkedIn and Apify's maintained
[`apify/facebook-ads-scraper`](https://apify.com/apify/facebook-ads-scraper)
for Meta. Actor builds, result limits, timeouts, and per-run dollar caps are
pinned in `config/apify_ads.v2.json`. Paid starts are never automatically
retried. An ad enters the normalized profile only when its advertiser name
exactly matches the requested account after conservative normalization, or its
destination belongs to the account domain. Unattributable name-search results
remain raw and generate warnings rather than evidence.
Attributable ads without a captured click URL still count as ad activity, but
their destination is null and they cannot contribute tracking evidence.

Limit a corrective run to one platform without replacing saved evidence from
the other platform, or replay already saved datasets without a paid actor call:

```bash
uv run gtm-signals collect-apify-ads \
  data/runs/<run-id> example.com --account-name "Example" --platform meta
uv run gtm-signals replay-apify-ads \
  data/runs/<run-id> example.com --account-name "Example"
```

Run local batches and resume jobs through SQLite:

```bash
uv run gtm-signals enqueue-batch accounts.jsonl
uv run gtm-signals list-jobs --status pending
uv run gtm-signals run-pending-jobs --workers 2
uv run gtm-signals run-job <job-id>
```

Record validation and downstream outcomes without sending outreach:

```bash
uv run gtm-signals review-classification data/runs/<run-id> \
  --url <saved-url> --content-sha256 <hash> --signal-type page_family \
  --original-value '"unknown"' --decision correct \
  --corrected-value '"guide"' --reviewer <name> --notes <reason>
uv run gtm-signals snapshot-outreach data/runs/<run-id>
uv run gtm-signals import-outcomes outcomes.jsonl
uv run gtm-signals outcome-metrics
uv run gtm-signals signal-outcome-metrics
```

`record-send` only records an externally authorized send; it does not contact a
person or launch a campaign. `export-evidence-bundle` refuses accounts that have
not passed every qualification gate.

Provider credentials are read through the `SecretVault` boundary. The included
macOS adapter reads encrypted Keychain entries and never persists values in
repository files, raw payloads, logs, or SQLite.

## Input contract

The baseline command accepts normalized account JSON containing company metadata, discovered website pages, and external signals. Providers should map their responses to this contract instead of leaking vendor-specific payloads into the analysis layer.

See `examples/account.json` and `docs/data-model.md`.

## Output

The CLI returns:

- Page classifications and page-level evidence
- Website-level content and funnel metrics
- Opportunity scores for each supported GTM channel
- Confidence, reasons, risks, and recommended next action
- An evidence bundle suitable for QA and outreach personalization

## Guiding constraint

Missing pixels, tags, job-description phrases, or public campaign pages are not proof of absence. The engine uses `confirmed`, `likely`, `possible`, `unknown`, and `contradicted` evidence states and should phrase outreach accordingly.

## Start here for implementation

Give your coding agent [`docs/CODEX_EXECUTION_BRIEF.md`](docs/CODEX_EXECUTION_BRIEF.md), or invoke the repository skill with a request such as:

> Use `$gtm-channel-gap-analysis` to implement Phase 1 from the execution brief, run the tests, and report any assumptions.
