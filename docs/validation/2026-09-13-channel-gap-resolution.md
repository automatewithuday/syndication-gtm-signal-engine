# Channel-gap resolution validation — 2026-09-13

## Scope

The milestone connects candidate discovery, SQLite ingestion, exact-run human
reviews, profile export, channel scoring, unified scoring, and decision reports
through `resolve-channel-gaps`. The workflow uses saved artifacts only and does
not make provider calls.

## Deterministic acceptance

The integration fixture produces two content-syndication and two retargeting
candidates. Before review, all remain pending and neither gap receives a score.
After exact-run approvals, content syndication and retargeting pass their gap
rules; programmatic remains `insufficient_evidence`. This verifies that one
channel's approval cannot leak into another and that unresolved channels retain
null totals.

## Real-account replay

| Account | Content candidates | Paid candidates | Resolution status | Channel totals |
|---|---:|---:|---|---|
| DailyPay | 0 | 0 | insufficient evidence | all null |
| ColdIQ | 0 | 0 | insufficient evidence | all null |

The saved DailyPay and ColdIQ crawls contain no deterministic, reviewable gap
claims under the current rules. Their priority scores remain 91.7 and 88.6,
respectively. This is a collection/evidence limitation, not evidence that any
channel is absent or healthy. No provider cost was incurred by the replay.
