# Classification precision benchmark — 2026-09-11

## Dataset

`tests/fixtures/labeled_classification_pages.json` contains 20 manually labeled,
sanitized pages spanning case studies, guides, ebooks, webinars, reports, white
papers, non-assets, and an ambiguous asset-access case. Seventeen rows are
content assets with gating labels.

The examples are derived from page structures encountered during DailyPay and
ColdIQ rule development but contain no copied article bodies or personal data.

## Result

- Asset-family classification: 20/20 correct, precision 1.00. Target: at least
  0.90.
- Gating classification: 17/17 correct, precision 1.00. Target: at least 0.85.
- The ambiguous guide is returned as `unknown` rather than forced into a gated
  or ungated class.

`tests/test_classification_precision.py` recomputes these gates on every test
run.

## Interpretation

This satisfies the execution brief's initial acceptance gate on the maintained
labeled fixture set. The sample is deliberately small and stratified, so it
does not establish production-population precision. Continue adding sanitized
review corrections and evaluate larger holdout sets before automating outreach
qualification.
