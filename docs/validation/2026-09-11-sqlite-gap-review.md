# SQLite gap-review validation — 2026-09-11

## Scope

This milestone adds a local SQLite human-review boundary between deterministic
gap candidates and scoreable evidence. Schema changes are applied from a
versioned SQL migration packaged with the installed CLI.

## Workflow

1. Ingest `normalized/gap_candidates.jsonl` idempotently.
2. List pending, approved, or rejected candidates.
3. Approve or reject a candidate with reviewer identity, required notes, and a
   timestamp. Approvals also require evidence strength and confidence.
4. Export approved observations for one exact Scrapling run.
5. Validate the exported profile against that run's saved pages before writing.

Candidates, occurrences, and reviews are separate tables. Re-ingestion never
resets review status. Review history is append-only, and approvals bind to the
run/content-hash occurrence reviewed. Historical approvals remain replayable
even after a later crawl observes changed page content.

## Real-company state

DailyPay and ColdIQ currently have zero gap candidates after false-positive
correction. Ingesting both real runs therefore creates no queue entries; this is
the expected unknown state. No approvals were fabricated to demonstrate the
workflow. Fixture tests exercise approval, rejection, export, and replay using
fully traceable saved-page evidence.

## Safety and persistence

- The database is local and gitignored.
- Candidate ingestion accepts only `ScraplingFetcher` runs.
- Rejections persist across repeated ingestion.
- Approved evidence is not exported into a different run automatically.
- Export invokes the same provenance validation used by `score-gap`.
