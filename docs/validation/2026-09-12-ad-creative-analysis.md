# Ad creative analysis validation — 2026-09-12

## Scope

Validate `ad_creative_analysis_v1` against the saved, authoritative ColdIQ and
DailyPay Deepline/Adyntel responses. The validation is local-only: it performs
no paid provider requests and no AI inference.

## Contract

- Verify every raw response against the SHA-256 stored by the collector.
- Join raw creative details to normalized ads by platform and provider ID.
- Preserve provider totals separately from returned and inspected rows.
- Classify only usable text; redacted, missing, or metadata-only content is
  unknown.
- Record the exact regex patterns supporting funnel, offer, audience, and theme
  labels.
- Normalize provider creative types into format families and keep distribution
  platforms separate.
- Infer creative activity only from an explicit provider active flag or saved
  first/last-seen dates relative to the collection observation time.
- Treat provider totals as observed inventory, not proof of current activity.
- Mark image/video understanding as not performed.

## Real-account results

| Account | Channel | Provider total | Inspected | Usable text | Sample coverage | Sample confidence |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| ColdIQ | LinkedIn | 214 | 24 | 24 | 11.21% | medium |
| ColdIQ | Google | 44 | 10 | 0 | 22.73% | medium |
| ColdIQ | Meta | unknown | 0 | 0 | unknown | none |
| DailyPay | LinkedIn | 318 | 10 | 10 | 3.14% | medium |
| DailyPay | Google | 200 | 10 | 0 | 5.00% | medium |
| DailyPay | Meta | 16 | 10 | 10 | 62.50% | high |

ColdIQ's inspected LinkedIn sample is dominated by marketing/GTM,
sales/revenue, pipeline/growth, and educational-content signals. DailyPay's
LinkedIn sample is dominated by HR/people, employee retention/productivity,
and product/service messaging; its Meta sample is primarily employee/consumer
financial-access messaging. These findings describe the inspected samples, not
the complete provider inventories.

Google validates channel activity, format, and observation dates, but the
returned creative bodies are redacted or absent. V1 therefore produces no
Google message, audience, offer, or funnel classifications.

## Blockers and decisions

- A provider total does not establish creative composition. Composition
  confidence remains sample-scoped until additional pages are collected.
- LinkedIn destination URLs are frequently null. No landing-page score is
  manufactured from the ad-library detail URL.
- Visual URLs are retained, but image/video contents require a later multimodal
  analysis stage with its own artifact, cost, and validation boundary.
- The analysis emits a stable `scoring_inputs` block, but current
  `paid_channels_v2` weights are not silently changed. A future scoring revision
  must explicitly version and calibrate any creative-derived weights.

## Verification

- 127 deterministic tests pass.
- Source distribution and wheel build successfully and include
  `config/ad_creative_analysis.v1.json`.
- `git diff --check` passes.
