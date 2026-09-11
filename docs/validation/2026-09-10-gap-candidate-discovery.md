# Gap candidate discovery validation — 2026-09-10

## Scope

This increment adds resumable, Scrapling-only collection of high-signal pages
from an existing run's discovered URL inventory and deterministic candidate
extraction from saved normalized text.

Collection and interpretation are separate commands. Target collection updates
the original run, preserves raw responses, records selected/fetched URLs and
errors in the manifest, and keeps the run partial because it remains bounded.
Candidate discovery never changes the score or evidence profile.

## Real-company collection

- DailyPay: selected and fetched `/careers` and `/press-center` from run
  `20260910T152504Z-2ee8204b`.
- ColdIQ: selected and fetched `/openings-job` and `/ai-marketing-tools` from run
  `20260910T152513Z-5d110bec`.
- All four pages and both robots policies were fetched through Scrapling with
  no provider errors.

## False-positive correction

The first candidate pass returned four ColdIQ matches from the AI marketing
tools directory. Review showed that the extractor combined unrelated directory
labels such as “Low,” “scaling,” and “inbound leads.” These were not statements
about ColdIQ's own channel performance or expansion intent.

The URL selector now uses structural path segments rather than arbitrary
substrings, excludes tool directories from candidate extraction, requires
first-person language for expansion intent, and restricts performance matches
to compact phrases such as “low conversion” or “declining pipeline.” The replay
returned zero candidates for both companies.

Zero candidates leaves the gap unknown. It does not lower the gap score or
support an outreach claim.

## Verification

The fixture suite covers URL prioritization, bounded targeted collection,
pending-review output, and the tool-directory false-positive. The full suite
passes without live requests.
