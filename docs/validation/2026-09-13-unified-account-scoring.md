# Unified account scoring validation — 2026-09-13

## Scope

The six-signal scorer was replayed against the saved DailyPay and ColdIQ
company profiles and evidence artifacts. The replay made no provider requests
and incurred no new cost.

## Results

| Account | Priority | Coverage | Confidence | Status | Funding | Channel qualification |
|---|---:|---:|---:|---|---|---|
| DailyPay | 91.7 | 90.0% | 74.9% | high priority | unknown | blocked by unknown gap |
| ColdIQ | 88.6 | 81.2% | 58.9% | review | unknown | blocked by unknown gap |

DailyPay's known signals were firmographic fit 88.1, hiring 90, advertising
100, technology 100, and website 85. ColdIQ's were firmographic fit 77.8,
hiring 90, advertising 88.9, technology 100, and website 93. Funding remains
unknown for both because the required Crunchbase-through-Deepline evidence is
not available.

ColdIQ's overall status is `review` despite its high numeric priority because
partial firmographic and advertising coverage reduce confidence below the
configured 60% threshold. This real-account replay exposed and verified the
need to propagate within-signal coverage into the aggregate rather than giving
a partially observed signal full weight.

All content-syndication, retargeting, and programmatic totals remain null. The
positive readiness and timing signals rank the accounts for investigation but
do not prove a channel gap or authorize outreach.
