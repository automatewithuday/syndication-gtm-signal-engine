# Initiative review and trigger scoring validation

Date: 2026-09-11

## Scope

This milestone adds local human review and deterministic scoring for saved
initiative candidates. It does not approve real-company evidence, alter the
channel-gap queue, or authorize outreach.

## Persistence and provenance

Migration `003_initiative_review_queue.sql` creates separate initiative
candidate, occurrence, and append-only review tables. Approvals require reviewer
identity, notes, strength, and confidence and are bound to the exact run and
content hash. Tests verify that changed content does not inherit approval while
the historical reviewed occurrence remains replayable.

The default database successfully migrated through versions 001, 002, and 003.
The existing DailyPay and ColdIQ initiative files were ingested as four pending
candidates: one for DailyPay and three for ColdIQ. No candidates were approved.

## Trigger scoring

The reviewed profile must match its saved Scrapling page by URL, content hash,
observation time, and excerpt. `content_syndication_v2` then scores the strongest
reviewed occurrence per initiative type using configurable base points,
reviewer-strength credit, and source-date freshness.

- Unknown dates receive 0.50 freshness credit and cap component confidence at
  0.65. Observation time is not treated as event time.
- Scoring accepts an explicit `--as-of YYYY-MM-DD` for reproducible replay and
  rejects source dates after that date.
- Multiple source pages for one initiative type do not multiply its points.
- Distinct initiative types receive a small configurable bonus.
- Reviewed initiatives and recent content are merged by maximum score to avoid
  counting a campaign launch twice.

A deterministic dated fixture scored a confirmed campaign launch at 70/100 and
`provisional_pass`. An undated confirmed new-channel launch scored 40/100 with
confidence capped at 0.65 and remained in `review`.

## Verification

- 65 local unit tests passed, including queue, provenance, freshness, scoring,
  integration, and CLI behavior.
- The skill validator passed after documenting the new operating rules.
- Both v1 and v2 scoring configurations are retained; v2 is the packaged
  default and snapshot identities include its hash plus the reviewed trigger
  snapshot ID.
