# Channel-gap evidence validation — 2026-09-10

## Scope

This milestone adds deterministic content-syndication gap scoring without
interpreting public-web absence as proof. It accepts only claims verified
against normalized pages from a saved `ScraplingFetcher` run.

Every observation must match the saved page's canonical URL, content hash,
observation time, and excerpt. This prevents manually researched or stale text
from entering the operational gap score under Scrapling provenance.

## Evidence states

- Positive evidence: explicit expansion intent, a documented distribution
  bottleneck, an active partner/hiring search, or a documented performance
  shortfall.
- Contradicting evidence: a documented healthy syndication program or measured
  syndication success. This yields a zero gap score and disqualified status.
- Mixed positive and contradicting evidence: unknown/review until its timing and
  scope are resolved.
- No verified observations: unknown/insufficient evidence, never zero.

Initial factor weights and the provisional-pass threshold are configuration
driven and not outcome calibrated. A pass requires at least two positive signal
types, a score of 45, and confidence of 0.70.

## Current real-company status

The earlier DailyPay and ColdIQ runs used `SystemCurlFetcher`, so the gap scorer
rejects them by design. Fresh one-page Scrapling canaries were collected as
`20260910T152504Z-2ee8204b` and `20260910T152513Z-5d110bec`; both preserved raw
responses without provider errors. Empty profiles produce the honest current
result for each account: gap score `null`, state `unknown`, and status
`insufficient_evidence`. Broader Scrapling collection is required before either
can receive a positive or contradicting gap score.

## Tests

Fixture-backed tests cover provenance rejection, excerpt verification, unknown
absence, positive scoring, contradiction handling, and integration into the
overall syndication score. Tests do not contact live websites.
