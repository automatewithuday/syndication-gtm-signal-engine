# Real-account reviews and Phase 1 workflow — 2026-09-11

## Scope

Validated the current content-syndication pipeline against bounded Scrapling
runs for DailyPay and ColdIQ, added auditable account review reports, and added
the single-command Phase 1 entrypoint required by the execution brief.

## Real-company results

DailyPay run `20260910T224631Z-52eaa2e5` contains 112 normalized pages after
targeted collection. It produced fit 86.2 (confidence 0.95), readiness 85.0
(0.75), and trigger 59.5 (0.98). The trigger is a confirmed, dated first-party
campaign launch. Gap remains unknown, so the weighted opportunity total is
null and qualification is `insufficient_evidence`.

ColdIQ run `20260910T224633Z-e599a4a6` contains 103 normalized pages. It
produced fit 84.8 (confidence 0.915), readiness 93.0 (0.745), and combined
trigger 60.0 (0.745). Review confirmed a new advertising division and active
Ads Manager hiring, but the page lacks an attributable publication date; the
initiative-only trigger is therefore capped at 50.0/0.65. Gap remains unknown,
so the weighted opportunity total is null.

These are bounded-crawl scores, not claims of full-site coverage or evidence
that either company does not use content syndication.

## Blockers and resolutions

- Some pages declared a homepage or migrated-page canonical despite being
  fetched at a different final path. Normalization now accepts declared
  canonicals only for the same path. `repair-canonicals` repairs older
  normalized pages from immutable Scrapling raw metadata.
- An explicit DailyPay press-release target was already present in the normal
  priority queue, preventing promotion and causing a different page to consume
  the one-page budget. Explicit, discovery-validated targets are now enqueued
  before ordinary targets.
- Candidate identity can recur across crawls while body hashes change. Current
  review state now returns to pending for a new run/hash while historical
  append-only review decisions remain available for replay.

## End-to-end command

`gtm-signals crawl-and-analyze <domain> --output <report.json>` performs a
bounded Scrapling crawl, classification, asset analysis, gap/initiative
candidate discovery, and initial scoring. Its report includes evidence samples
with URLs/excerpts and explicitly represents missing fit/gap evidence as
unknown.

## Verification

The complete fixture-only suite passes: 95 tests. No paid provider or live
website is contacted by the test suite.
