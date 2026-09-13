# Portfolio report validation — 2026-09-13

## Scope

This milestone adds a provider-free decision view over persisted account jobs.
It writes JSON, CSV, and Markdown and never performs enrichment or collection.

## Verified behavior

- Known priority scores sort descending; unknown scores remain visible last.
- The latest updated job policy is the current row for a canonical domain.
- Historical job count is retained without duplicating the account.
- Missing and malformed reports produce explicit unavailable states.
- Priority, evidence coverage, confidence, opportunity status, blockers, and
  provider cost remain separate fields.
- Snapshot identity is stable when only generation time or output location
  changes.

## Real-account replay

| Rank | Account | Priority | Coverage | Confidence | Opportunity |
|---:|---|---:|---:|---:|---|
| 1 | DailyPay | 91.7 | 90.0% | 74.9% | `insufficient_evidence` |
| 2 | ColdIQ | 88.6 | 81.2% | 58.9% | `insufficient_evidence` |

The replay used the authoritative saved account reports through a temporary
SQLite job database. No website, Deepline, Adyntel, Apify, or other provider was
called. The ordering is an analyst-priority decision only; neither account is
channel-qualified while its required gap evidence remains unresolved.
