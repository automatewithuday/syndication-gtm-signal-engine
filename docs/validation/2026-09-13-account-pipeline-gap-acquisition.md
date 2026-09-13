# Account-pipeline gap acquisition validation — 2026-09-13

## Scope

This milestone integrates the targeted Scrapling acquisition workflow into
`run-account-v1` without making additional website requests by default. It
versions the orchestration as `account_pipeline_v2` and the acquisition output
as `gap_evidence_acquisition_v2`.

## Contract

- `--gap-evidence-pages` enables the stage only when greater than zero.
- `--gap-evidence-targets` caps planned targets.
- `--gap-evidence-depth` caps same-domain traversal depth.
- `--retry-gap-evidence` explicitly permits retries of prior failed targets.
- The stage runs after paid scoring and before channel-gap resolution.
- Acquisition defers resolution to the existing pipeline resolver, preventing
  duplicate score/report rebuilds.
- Policy and results are checkpointed in `account_pipeline.json` and exposed in
  the account-intelligence report.

## Blocker found and resolved

The first integration fixture created a realistic `pages.jsonl` artifact and
exposed that `run-account-v1` called `discover_gap_candidates` without importing
it. Runs with normalized pages could therefore raise `NameError`. The import is
now explicit, and the fixture exercises company enrichment, website candidate
discovery, jobs, paid scoring, targeted acquisition, gap resolution, unified
scoring, and report construction in order.

## Real-account cached replay

| Account | Planned targets | Selected | Held failures | Pages fetched | Resolution |
|---|---:|---:|---:|---:|---|
| DailyPay | 9 | 0 | 2 | 0 | `insufficient_evidence` |
| ColdIQ | 3 | 0 | 0 | 0 | `insufficient_evidence` |

Every paid collector was replaced with a fail-fast sentinel during these
replays. Neither sentinel ran, confirming that completed saved provider stages
were reused and no paid provider request was made. A zero-target result remains
coverage information only; it does not establish channel absence.
