# Broader initiative discovery validation

Date: 2026-09-11

## Scope

This milestone expanded two existing Scrapling-only runs with bounded,
high-signal link traversal and introduced a separate initiative-candidate
stream. It did not approve candidates, infer channel absence, or alter an
account's qualification score.

## Runs

| Account | Run | Existing pages after collection | New targeted pages | Target depth | Provider errors |
| --- | --- | ---: | ---: | ---: | ---: |
| DailyPay | `20260910T152504Z-2ee8204b` | 9 | 6 | 1 | 0 |
| ColdIQ | `20260910T152513Z-5d110bec` | 5 | 2 | 2 | 0 |

The DailyPay command was intended to use depth two, but a CLI dispatch bug left
targeted collection at its default depth one. The manifest records the actual
depth. The dispatch was corrected and is covered by command-level regression
tests. The collected pages remain valid saved Scrapling evidence.

The initial DailyPay press selection was broader than useful and included a
board appointment and an analyst-recognition page. Selection now requires a
topical launch/campaign/marketing/partner/growth/opening term for press detail
slugs while retaining listing pages for discovery.

## Candidate results

DailyPay produced one pending initiative candidate:

- `public_campaign_launch` (`direct`) from the “Future of Pay” press release.
- Matched statement: `launched "The Future of Pay," a campaign`.
- Source date: `2026-06-08T08:16:56+00:00`, attributed to
  `meta.article:published_time` with confidence `0.98`.

ColdIQ produced three pending page-level candidates across two types:

- `active_marketing_hiring` on the openings page.
- `new_channel_or_team_launch` on the ColdIQ Ads job page.
- `active_marketing_hiring` on that job detail page.

The job detail describes “launching a new growth engine: ColdIQ Ads” and
building a performance ad agency from the ground up. Neither ColdIQ page
exposes an attributable publication date, so all source dates remain null.
“Start date Soon” is scheduling copy, not publication metadata.

Repeated “looking for” and “hiring” matches on the same ColdIQ page initially
created two candidates for one signal. Extractor version
`initiative_candidate_rules_v2` keeps one candidate per page and signal type.

## Gap boundary

Replaying `gap_candidate_rules_v1` produced zero channel-gap candidates for
both accounts. The result is `unknown`, not evidence that content syndication
is unused. Initiative candidates are trigger-review context and cannot be
inserted into or scored as channel-gap observations.

## Verification

- 56 local unit tests passed.
- Tests cover same-domain depth traversal, URL filtering, CLI argument routing,
  source-date preservation, initiative/gap separation, and per-page signal
  deduplication.
- No live provider was used other than Scrapling during collection.
