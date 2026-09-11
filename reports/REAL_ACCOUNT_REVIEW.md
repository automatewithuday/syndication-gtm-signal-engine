# DailyPay and ColdIQ — GTM signal review

Generated from authoritative bounded Scrapling runs on 2026-09-11. Scores use
`content_syndication_v2`; thresholds remain provisional.

| Account | Fit | Readiness | Gap | Trigger | Overall confidence | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| DailyPay | 86.2 (0.95) | 85.0 (0.75) | Unknown (0.0) | 59.5 (0.98) | 0.75 | Insufficient evidence |
| ColdIQ | 84.8 (0.915) | 93.0 (0.745) | Unknown (0.0) | 60.0 (0.745) | 0.745 | Insufficient evidence |

The number in parentheses is component confidence. Neither account has a
weighted opportunity total because verified channel-gap evidence is required
and remains unknown. Unknown is not zero and does not mean the channel is
unused.

## DailyPay

- Run `20260910T224631Z-52eaa2e5`: 112 normalized pages; partial because the
  crawl was bounded, one legacy sitemap was malformed, and one case-study page
  timed out.
- Content: 90 assets observed, 60 substantial, 60 suitable, 27 possibly
  suitable, 37 with observed lead-capture paths, and 2 dated within 90 days.
- Fit: confirmed B2B employer offer and HCM/payroll buyers; enterprise motion
  and scale are likely based on 180+ integrations and millions of users.
- Trigger: confirmed first-party launch of “The Future of Pay” campaign,
  published 2026-06-08. At 95 days old on the scoring date it receives 0.85
  freshness credit: 70 × 0.85 = 59.5. [Source](https://www.dailypay.com/press-center/press-releases/dailypay-launches-the-future-of-pay-challenging-why-workers-still-get-paid-like-its-1938)
- Gap: no reviewed evidence of expansion intent, a distribution bottleneck,
  performance shortfall, or active syndication-partner search. The correct
  result is unknown, not “no syndication.”

The full run-bound evidence report remains in the local ignored crawl directory;
the evidence-backed factors needed for this public review are summarized above.

## ColdIQ

- Run `20260910T224633Z-e599a4a6`: 103 normalized pages; partial because the
  crawl was bounded and two requested pages returned 404.
- Content: 42 assets observed, 34 substantial, 16 suitable, 26 possibly
  suitable, 26 with observed lead-capture paths, and 18 dated within 90 days.
- Fit: confirmed B2B positioning and three professional buyer roles;
  consultative implementation motion and established scale are likely based on
  first-party claims of 275+ clients and $50M+ ARR generated.
- Reviewed initiatives: confirmed launch of a new ColdIQ Ads growth engine
  (0.94) and active Ads Manager hiring (0.92). The page has no attributable
  publication date, so the initiative-only score is capped at 50.0/0.65.
  Recent observed content is stronger at 60.0/0.745, and the engine combines
  them by maximum to avoid double counting. [Source](https://coldiq.com/job-offer/ads-agency)
- Gap: no reviewed evidence of a content-syndication limitation. This remains
  unknown regardless of the strong content volume and current initiatives.

The full run-bound evidence report remains in the local ignored crawl directory;
the evidence-backed factors needed for this public review are summarized above.

## Decision and next evidence

Both companies pass provisional fit and readiness, but neither should be called
a qualified content-syndication opportunity yet. The next useful evidence is
first-party discovery—an authorized internal interview, campaign-performance
data, CRM notes, or a reviewed statement documenting distribution expansion or
underperformance. More absence-oriented public crawling cannot close this gap.

## Paid-channel technographics

Live Deepline/BuiltWith observations are now available. DailyPay has 442 total
technology detections, of which 37 are retargeting-relevant and 30 are
programmatic-relevant. ColdIQ has 130 total detections, with 18 and 11 relevant
respectively. Examples include Google Remarketing, Facebook Pixel and Custom
Audiences, conversion tracking, and DoubleClick; DailyPay also shows LinkedIn
Insights, 6sense, StackAdapt, Marketo, and Bizible.

Under provisional `paid_channels_v2`, both accounts score 55 for retargeting
readiness and 40 for programmatic readiness. These are review results, not
qualified opportunities: no normalized LinkedIn/Meta ad-library observations
exist yet, and neither account has approved positive gap evidence. Both paid
channel gap scores therefore remain unknown rather than zero.
