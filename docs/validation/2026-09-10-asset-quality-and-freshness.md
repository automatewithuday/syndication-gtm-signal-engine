# Asset quality and freshness validation — 2026-09-10

## Scope

This milestone analyzes saved crawl artifacts only; it makes no new web
requests. Version `asset_rules_v1` extracts publication/creation and modification
dates, measures observable asset substance, and assigns a conservative
content-syndication suitability state. Results retain the source URL, observation
time, content hash, date source/confidence, evidence excerpts, and risks.

## DailyPay

Input run: `20260910T134053Z-c9a824c7` (65 fetched pages).

- 61 detail assets: 46 case studies, 14 ebooks, and 1 white paper.
- 61/61 have a structured publication date. Relative to crawl observation time,
  1 was within 90 days, 4 within 180 days, and 8 within 365 days.
- 57 have directly observable substance and are currently marked suitable; 4
  gated offers remain possible because the full asset was not observable.
- Gating: 48 fully ungated, 9 optional gate, and 4 summary ungated/full asset
  gated.

The previous classifier counted two paginated case-study listing pages and the
listing page as assets. Those are now taxonomy. DailyPay also repeats a GLBA
consumer-notice PDF in page templates. Document attribution now excludes legal
PDFs and uses link context, correcting four asset-access assessments that had
been overstated by the unrelated document.

## ColdIQ

Input run: `20260910T134052Z-4c3a69dd` (50 fetched pages).

- 42 detail assets: 15 case studies, 26 guides, and 1 webinar.
- 24 assets have an attributable creation date from a single embedded detail
  record; 18 remain unknown. Of the dated assets, 18 were within 90 days and all
  24 were within 180 days of observation.
- 34 have directly observable substance; 8 remain unknown. The 26 gated guide
  offers are marked possible rather than suitable until the delivered asset or
  reuse rights are reviewed.
- Gating: 16 fully ungated and 26 summary ungated/full asset gated.

ColdIQ's sitemap exposed near-identical timestamps for 22 fetched asset URLs.
They resemble a sitemap build/deployment time, so they are logged and ignored as
content-freshness evidence. The `/guides` and `/case-studies` indexes are now
taxonomy rather than individual assets.

## Acceptance and limitations

- `gtm-signals analyze-assets data/runs/<run-id>` writes versioned
  `normalized/assets.jsonl` and `normalized/asset_summary.json`.
- Missing or hash-mismatched raw artifacts produce a partial summary rather than
  silently lowering evidence quality.
- Topic and audience labels are deterministic keyword observations, not final
  semantic judgments.
- Suitability does not establish licensing or reuse rights and does not qualify
  an account for outreach.
