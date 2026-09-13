# Batch gap-acquisition policy validation — 2026-09-13

## Scope

This milestone makes CSV/JSONL jobs reproduce the targeted gap-acquisition
contract available on `run-account-v1`.

## Verified behavior

- Enqueue normalizes page, target, and depth budgets plus retry intent.
- `account_job_v2` and `account_pipeline_v2` are included in the hashed request.
- Re-enqueuing the same normalized row is idempotent.
- The default gap page budget is zero for legacy and unspecified rows.
- Stored settings reach `run_account_v1` unchanged.
- Invalid limits and ambiguous boolean values fail at enqueue time.
- SQLite stage callbacks continue to persist pipeline checkpoint details.

## Real-company example

`examples/accounts.v2.jsonl` contains bounded DailyPay and ColdIQ requests.
ColdIQ explicitly skips Meta and disables Apify fallback in accordance with the
current account policy. Both rows enable ten Scrapling target pages, cap the
candidate plan at 25 URLs and depth two, and do not authorize failed-target
retry.

The example was normalized and enqueued twice against a temporary SQLite
database: the first pass inserted two jobs and the second recognized both as
existing. No account job was executed and no live provider was called.
