# Paid-channel scoring V3 validation — 2026-09-12

## Purpose

Consume `ad_creative_analysis_v1` without silently changing historical scoring
or treating missing provider fields as negative account evidence.

## Model

- Retargeting weights: inventory 15, current/recent creatives 15, tracked
  destinations 15, relevant technology 25, content inventory 20, funnel-stage
  diversity 5, and messaging-theme diversity 5.
- Programmatic weights: inventory 15, platform diversity 15, current/recent
  creatives 10, tracked destinations 10, relevant technology 20, content
  diversity 10, creative-format diversity 10, and messaging-theme diversity 10.
- A known factor earns points against its configured saturation threshold.
- An unknown factor has null observed value and null points. The readiness score
  is normalized across known factor weights, while evidence coverage reduces
  final confidence and gates qualification.
- V3 remains provisional until the five-account acceptance milestone is
  complete.

## Saved-account comparison

| Account | Channel | V2 readiness | V3 readiness | V3 confidence | Evidence coverage | Status |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| ColdIQ | Retargeting | 80.0 | 97.6 | 0.600 | 0.70 | review |
| ColdIQ | Programmatic | 80.0 | 93.8 | 0.675 | 0.80 | provisional pass |
| DailyPay | Retargeting | 80.0 | 98.0 | 0.722 | 0.85 | provisional pass |
| DailyPay | Programmatic | 80.0 | 100.0 | 0.765 | 0.90 | provisional pass |

The V3 values represent readiness, not channel-gap opportunity. All four gap
scores remain null/unknown because no approved positive gap evidence exists.

## Correctness cases

- Missing creative analysis leaves all creative-derived factors unknown.
- Mixed historical and undated samples cannot become a zero-current-activity
  claim.
- Missing destination URLs in partial samples remain unknown.
- A score snapshot includes the exact creative-analysis hash.
- V2 tests continue to exercise the unchanged historical behavior.
