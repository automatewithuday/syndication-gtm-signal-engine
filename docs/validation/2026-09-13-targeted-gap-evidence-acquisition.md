# Targeted gap-evidence acquisition validation — 2026-09-13

## Scope

This milestone closes the acquisition step between saved account intelligence
and exact-run gap review. It adds a provider-free target planner and a
Scrapling-only bounded collector. It does not interpret unavailable pages or
empty result sets as proof that a company is not using a channel.

## Behavior verified

- Merge saved discovery URLs, attributable ad destinations, and explicitly
  marked `scrapling_saved_serp` rows.
- Retain same-domain targets only, canonicalize query variants, rank structural
  paths deterministically, and cap selection.
- Reject search rows without Scrapling provenance.
- Preserve a stable plan snapshot across processing-time-only manifest changes.
- Skip pages already fetched and failures already attempted; expose
  `--retry-failed` as the only automatic retry override.
- Reject cross-path redirects so homepage content cannot be attributed to a
  campaign or career URL.
- Run candidate discovery, review ingestion/export, dependent channel scoring,
  unified scoring, and report refresh after collection.

## Real-company replay

| Account | Relevant targets | Already fetched | Held failures | Newly selected | Gap result |
|---|---:|---:|---:|---:|---|
| DailyPay | 9 | 7 | 2 | 0 | all three channels `insufficient_evidence` |
| ColdIQ | 3 | 3 | 0 | 0 | all three channels `insufficient_evidence` |

Before the final replay, a bounded live DailyPay Scrapling pass successfully
collected the schools total-rewards campaign page. The general-campaign and
SHRM routes redirected to the homepage. The workflow now records those as
target failures and does not request them again without explicit retry.

The first planner iteration surfaced 106 broad DailyPay press URLs. The
selection rules were tightened to require channel-specific press/partner slugs,
reducing the final relevant inventory to nine without asserting anything about
the unselected pages.

## Outcome

No new request was necessary on the final DailyPay or ColdIQ replay, and no
paid provider call was made. Both accounts remain high-priority research
candidates from other signals, but neither is a qualified channel-gap
opportunity because the required positive gap evidence is still absent.
