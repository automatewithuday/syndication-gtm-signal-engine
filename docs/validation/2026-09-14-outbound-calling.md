# Outbound-calling channel validation — 2026-09-14

## Scope

Completed the missing modern outbound-calling path across discovery, review,
scoring, unified account ranking, reporting, evidence export, send-time
snapshots, and signal-level outcome measurement. No outreach or provider call
was authorized or performed.

## Safety checks

- Deterministic candidates remain pending until human review.
- Approved evidence is accepted only for the current Scrapling run and exact
  URL/content hash. The standalone scorer also verifies method, observation
  time, and that the excerpt is present in the saved page.
- Two distinct supporting signal types are required. Contradictions disqualify;
  mixed support and contradiction routes to review.
- Missing readiness or gap evidence is unknown, never zero.
- Snapshot identity is stable across processing-timestamp-only changes.
- Outcome snapshots freeze named readiness factors as auditable signals.

## Automated verification

`uv run pytest -q` completed with **195 passed**. Focused outbound, validation,
bundle, unified, resolver, and CLI coverage completed with **43 passed**.

## Real-account replay

The authoritative saved runs were replayed through `resolve-channel-gaps` with
no paid provider calls:

| Account | Run | Outbound readiness | Gap | Total |
| --- | --- | ---: | --- | ---: |
| DailyPay | `20260910T224631Z-52eaa2e5` | 78.7, provisional pass | unknown / insufficient evidence | null |
| ColdIQ | `20260910T224633Z-e599a4a6` | 84.8, provisional pass | unknown / insufficient evidence | null |

The result is intentionally conservative: addressable sales motion is visible,
but neither saved public-web corpus contains reviewed evidence that the company
needs, is expanding, or is underperforming in outbound calling.
