# Five-account V1 acceptance

Validated on 2026-09-12 against ColdIQ, DailyPay, HubSpot, Gong, and Linear.
This is an evidence-system acceptance test, not a claim that every account is a
qualified sales opportunity. Missing provider evidence remains unknown.

## Outcome

| Account | Pipeline | BuiltWith | Meta | LinkedIn | Google | Retargeting | Programmatic |
|---|---|---:|---:|---:|---:|---:|---:|
| ColdIQ | Complete with fallback | 130 | Adyntel unknown; Apify explicit zero | 214 / 24 | 44 / 10 | 97.6 review | 93.8 pass |
| DailyPay | Complete | 442 | 16 / 10 | 318 / 10 | 200 / 10 | 98.0 pass | 100.0 pass |
| HubSpot | Complete | 839 | 74 / 10 | 1,410 / 24 | 4,000 / 40 | 74.5 pass | 92.6 pass |
| Gong | Complete with fallback | 972 | Explicit zero | 25 / 25 Apify fallback | 900 / 40 | 100.0 pass | 76.0 pass |
| Linear | Partial | 132 | Explicit zero | Unknown | 26 / 26 | 69.9 pass | 54.6 review |

Ad cells show provider-reported total / inspected rows. A `pass` is a
provisional readiness result, not proof of channel gap or final qualification.

## Acceptance gates

- One-command orchestration and resumable stage checkpoints: passed on 5/5.
- JSON and Markdown decision reports: generated for 5/5.
- BuiltWith normalization: completed on 5/5. Gong required a local replay after
  one unnamed provider row was safely skipped and audited.
- Primary Adyntel coverage: complete or valid partial results on 12/15 channel
  calls. ColdIQ Meta was inconclusive; Gong and Linear LinkedIn calls were
  charged by attempt but exited without a provider payload.
- Fallback behavior: Gong recovered 25 attributable LinkedIn ads. Linear's
  name-based fallback returned 25 candidates but none passed exact account
  attribution, so LinkedIn remains unknown.
- Unknown semantics: passed. Linear LinkedIn remains a blocker. ColdIQ Meta is
  inconclusive in Adyntel but has a separately retained Apify explicit-zero
  result; neither state is presented as proof that a channel is unused.
- Paid scoring: version `paid_channels_v3` persisted for 5/5 with evidence
  coverage and confidence gates.
- Fixture suite: 137 tests pass with no paid API calls.

## Spend audit

The three new accounts consumed exactly 1.59 Deepline credits ($0.159), measured
by the balance change from 227.52 to 225.93. This matches the 12 approved calls
at their observed prices: three BuiltWith calls at 0.14 credits plus nine
Adyntel calls at 0.13 credits. Gong and Linear also used one LinkedIn Apify
fallback each, totaling $0.12810. New-account provider spend was therefore
$0.28710.

The two failed Adyntel LinkedIn CLI responses did not include billing metadata
in their saved envelopes even though Deepline's billing ledger later showed the
0.13-credit attempt charges. Per-run reports mark those costs incomplete rather
than silently claiming the captured subtotal is exact.

## Remaining blockers

- ColdIQ: Adyntel Meta returned no provider payload. The explicit-zero Apify
  fallback resolves the bounded evidence state, while the primary-provider
  result remains visibly inconclusive.
- Linear: Adyntel LinkedIn exited without a payload, and name-based Apify output
  could not be attributed safely. Resolve Linear's authoritative LinkedIn
  company ID before authorizing a new targeted fallback call.
- All five channel-gap scores remain unknown until positive, reviewed gap
  evidence is attached. Readiness alone must not trigger outreach.

Authoritative local outputs remain in each run under
`normalized/account_intelligence.{json,md}`. Raw provider payloads remain local
and are intentionally excluded from Git.
