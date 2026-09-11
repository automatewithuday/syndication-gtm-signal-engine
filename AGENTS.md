# Agent instructions

## Objective

Build a reusable, provider-neutral GTM signal engine that identifies evidence-backed channel opportunities for B2B accounts.

## Non-negotiable invariants

- Treat public-web absence as uncertainty, not proof that a channel is unused.
- Preserve evidence provenance: URL, excerpt, observed time, method, and confidence.
- Keep raw provider payloads outside the core domain model.
- Use canonical URLs and content hashes to make repeated crawls idempotent.
- Keep scoring weights and thresholds in configuration.
- Version extraction and scoring logic in persisted results.
- Do not submit lead forms, create accounts, or trigger external campaigns without explicit authorization.
- Do not generate outreach claims that cannot be traced to stored evidence.

## Engineering conventions

- Python 3.11+ with type hints.
- Core classifiers should be deterministic and testable; use an LLM only for semantic ambiguity.
- Provider adapters implement narrow protocols and return normalized models.
- Add fixtures for provider payloads rather than making paid API calls in unit tests.
- Use migrations for database changes.
- Prefer incremental account processing and resumable jobs.

## Definition of done for a feature

- Behavior is covered by a meaningful test.
- Failure and retry behavior are explicit.
- Persisted evidence remains auditable.
- Documentation and example configuration reflect the change.
- The relevant local test suite passes.
