# Account-fit validation — 2026-09-10

## Scope

This milestone adds evidence-backed account fit for content syndication. It
normalizes four independent factors: B2B business model, identifiable
professional buyers, sales motion, and operating scale. It does not require an
employee count when better first-party scale indicators are available.

Each input fact retains value, strength, confidence, URL, excerpt, observation
time, and method. Categorical conflicts remain unknown rather than being
averaged. Fit thresholds and strength credits are configuration-driven and
remain provisional.

## Provider blocker

Parallel web search was attempted first and returned `Insufficient credit in
account`. This was recorded as provider incompleteness, not missing company
evidence. Research continued through direct public-web retrieval without adding
funds, credentials, or repository secrets.

This validation predates the Scrapling-only policy adopted later on 2026-09-10.
Its scores remain useful for deterministic scorer testing, but they are not
eligible for production qualification. Re-collect the supporting pages with
Scrapling and regenerate the normalized fit facts before using either account
operationally.

## DailyPay

DailyPay scored **86.2 fit** at **0.953 fit confidence**.

- B2B motion is directly supported by its employer demo path.
- HR and payroll buyers are explicitly addressed by a current business guide.
- Enterprise motion is likely based on personalized demos and integration
  requirements, while the profile records that a small-business self-serve
  offer also exists.
- Enterprise operating scale is likely based on the company's claim of 1,000+
  clients and access for 5M+ employees.

Sources: `https://www.dailypay.com/demo/`,
`https://www.dailypay.com/resource-center/blog/what-is-on-demand-pay-a-business-guide-for-hr-and-payroll-teams/`,
`https://www.dailypay.com/integrations/`, and
`https://www.dailypay.com/about-us/`.

## ColdIQ

ColdIQ scored **81.0 fit** at **0.904 fit confidence**.

- A first-party page explicitly targets B2B technology companies above a stated
  revenue threshold.
- Current case studies show marketing/growth, sales, and revenue-operations
  stakeholders in the serviced buying context.
- A strategy call with leadership and multi-month engagements support a likely
  consultative motion.
- A first-party $4.5M ARR claim supports an established scale tier, with lower
  confidence because it is a marketing claim rather than audited evidence.
- The profile records ColdIQ's mixed API and agency/services positioning as a
  material risk rather than forcing one universal sales motion.

Sources: `https://wf.coldiq.com/`,
`https://coldiq.com/case-studies/airops-abm`,
`https://coldiq.com/case-studies/aircall`,
`https://coldiq.com/case-studies/teikametrics`, and
`https://coldiq.com/blog/b2b-sales-funnel`.

## Integrated state

After `score-fit` and a syndication-score replay:

| Account | Fit | Readiness | Trigger | Remaining blocker |
| --- | ---: | ---: | ---: | --- |
| DailyPay | 86.2 | 86 | 15 | Gap evidence |
| ColdIQ | 81.0 | 93 | 60 | Gap evidence |

Both fit components are `provisional_pass`. The overall opportunity total is
still `null`, because neither account yet has positive evidence establishing an
underdeveloped content-syndication channel.
