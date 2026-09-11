# Content-syndication readiness scoring validation — 2026-09-10

## Scope and contract

Version `content_syndication_v1` scores observable content readiness from saved
asset assessments. All thresholds are configuration-driven and remain
`provisional_unlabeled`; the two accounts below are behavior checks, not a
precision or outcome calibration set.

The report keeps four components separate:

- `readiness`: scored from substantial inventory, asset diversity, customer
  proof, 90/365-day activity, effective suitability, and lead-capture assets;
- `trigger`: recent content production contributes at most 60 points because it
  is only one kind of reason to act;
- `fit`: unknown until sourced ICP/economic evidence is added; and
- `gap`: unknown until positive evidence supports an underdeveloped channel.

If a required component is unknown, the overall opportunity total is `null`.
This is intentional and prevents missing public evidence from becoming either a
zero score or a fabricated channel gap.

## Real-company behavior checks

### DailyPay

- Readiness: **86/100**.
- Trigger: **15/100** from one observed asset within 90 days.
- Confidence: **0.750**, capped because the crawl was bounded/partial.
- Qualification: `provisional_pass` for readiness;
  `insufficient_evidence` for the opportunity because fit and gap are unknown.
- Main distinction: a large, diverse, highly reusable proof library receives
  strong readiness credit, while the low recent-publication count limits the
  freshness factors.

### ColdIQ

- Readiness: **93/100**.
- Trigger: **60/100** from 18 observed assets within 90 days.
- Confidence: **0.745**, reflecting both bounded coverage and unknown dates or
  substance for some assets.
- Qualification: `provisional_pass` for readiness;
  `insufficient_evidence` for the opportunity because fit and gap are unknown.
- Main distinction: high recent output receives strong freshness credit, while
  gated assets whose full content was not observed receive only fractional
  suitability credit.

These scores describe observed, prioritized pages and are not whole-site asset
counts. They do not assert that either company uses or does not use content
syndication.

## Audit and replay behavior

Each factor stores its observed metric, awarded/configured points, and supporting
asset URLs. The report records asset, summary, and configuration hashes plus a
stable snapshot ID. Replay timestamps are excluded from the snapshot identity,
so an unchanged evidence/configuration set retains the same ID.

The current readiness threshold is not approved for automated outreach. Human
labels and downstream outcomes are required before changing calibration status.
