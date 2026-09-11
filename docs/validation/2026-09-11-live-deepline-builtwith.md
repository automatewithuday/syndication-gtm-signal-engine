# Live Deepline/BuiltWith validation — 2026-09-11

## Scope

Validate the smallest live external-provider increment on the authoritative
Scrapling runs for DailyPay and ColdIQ. This milestone covers technology
observations only; LinkedIn and Meta advertising observations remain pending.

## Provider boundary

- Official Deepline CLI version: 0.3.89.
- Authentication and managed BuiltWith credentials remain inside Deepline.
- `deepline preflight --json` confirmed account, provider health, and available
  balance before execution.
- The collector inspects `builtwith_domain_lookup` before every paid execution
  and validates the expected `Results -> Result.Paths -> Technologies` shape.
- Requests use `live_only=true`, `no_pii=true`, and `no_meta=true`.
- Paid lookup execution has no automatic retry, preventing ambiguous failures
  from silently creating duplicate charges.
- Raw envelopes and contracts remain under the ignored run directories. The
  normalized domain model contains provenance, detection dates, confidence,
  method, limitations, and normalizer version without provider credentials.

## Results

| Account | Authoritative run | Observations | Cost | Retargeting-relevant | Programmatic-relevant |
| --- | --- | ---: | ---: | ---: | ---: |
| DailyPay | `20260910T224631Z-52eaa2e5` | 442 | 0.14 credits / $0.014 | 37 | 30 |
| ColdIQ | `20260910T224633Z-e599a4a6` | 130 | 0.14 credits / $0.014 | 18 | 11 |

DailyPay examples include Google Tag Manager, Heap, Facebook Pixel and Custom
Audiences, LinkedIn Insights, Google Remarketing, DoubleClick Floodlight,
6sense, StackAdapt, Marketo, and Bizible. ColdIQ examples include Google Tag
Manager, Google Remarketing, Facebook Pixel and Custom Audiences,
DoubleClick.Net, Get Koala, Factors.ai, PostHog, and Hyros.

## Scoring outcome and learning

The initial paid-channel scorer counted all detected technologies, including
irrelevant CDN and DNS entries. That would inflate readiness. The correction is
versioned as `paid_channels_v2`; v1 remains unchanged for reproducible replay.
Version 2 uses channel-specific category markers and persists the number of
relevant detections.

Both accounts score 55/100 retargeting readiness and 40/100 programmatic
readiness. Confidence is 0.45 and 0.36 respectively because ad activity,
platform diversity, and tracked ad destinations have not yet been collected.
Both scores remain in review. Gap is null/unknown because no approved positive
gap evidence exists; observable technology evidence contradicts any simplistic
claim that the channel is unused.

## Next milestone

Select and fixture-test narrowly scoped Apify actors for LinkedIn and Meta ad
libraries, then run the same two-account canary with explicit cost capture and
no unsupported absence inference.
