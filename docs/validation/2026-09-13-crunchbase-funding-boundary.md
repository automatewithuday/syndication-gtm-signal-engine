# Crunchbase funding boundary validation — 2026-09-13

## Outcome

The company-enrichment milestone now has a provider-safe funding path. Initial
company enrichment and the dedicated `enrich-company-funding` command search
the live Deepline catalog, accept only a connected tool whose provider is
exactly `crunchbase`, inspect its current schema, and normalize only a response
attributable to the cached company domain or Crunchbase organization URL.

The funding-only command requires an existing cached account and does not call
Prospeo. Raw catalog and provider responses are immutable local files referenced
from SQLite by SHA-256 hash. Provider errors and normalization failures remain
explicit partial states; a raw paid response is retained even when it cannot be
normalized.

## Live provider check

The Deepline catalog query `crunchbase` returned no callable
provider named `crunchbase`. It did return callable Aviato and LeadMagic funding
tools. They were deliberately rejected because the requested source is
Crunchbase and provider substitutes cannot be relabeled.

The funding-only refresh was run for cached DailyPay and ColdIQ records. Both
remain `partial` with funding status `blocked_provider_unavailable`. Each record
contains the catalog observation time and response hash; current-run billing is
empty. No Prospeo or funding-provider call was made.

## Deterministic verification

- An exact Crunchbase fixture is discovered, schema-checked, executed,
  domain-validated, normalized, billed, and persisted.
- Aviato and LeadMagic catalog rows do not satisfy the provider boundary.
- Repeating the funding refresh does not duplicate content-addressed snapshots.
- A missing cached company is rejected before catalog or provider execution.
- The complete suite passes: 180 tests.
