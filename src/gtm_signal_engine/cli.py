from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Sequence

from .engine import analyze_account
from .collector import ScraplingFetcher, collect_website, repair_cross_path_canonicals
from .classification_run import classify_crawl_run
from .asset_analysis import analyze_asset_run
from .syndication_scoring import score_syndication_run
from .account_fit import score_account_fit_run
from .channel_gap import score_channel_gap_run
from .gap_discovery import collect_gap_targets, discover_gap_candidates, discover_initiative_candidates
from .review_queue import (
    DEFAULT_DATABASE_PATH,
    export_gap_profile,
    ingest_gap_candidates,
    list_gap_candidates,
    review_gap_candidate,
)
from .initiative_review import (
    export_trigger_profile,
    ingest_initiative_candidates,
    list_initiative_candidates,
    review_initiative_candidate,
)
from .trigger_scoring import score_business_trigger_run
from .review_report import build_account_review
from .workflow import crawl_and_analyze
from .paid_channel_scoring import score_paid_channel_run
from .external_collection import collect_deepline_technologies
from .apify_collection import collect_apify_ads, replay_apify_ads
from .jobs import enqueue_batch, list_jobs, run_job, run_pending_jobs
from .validation import (
    create_outreach_snapshot,
    import_outcomes,
    outcome_metrics,
    record_send,
    review_classification,
    signal_outcome_metrics,
)
from .evidence_bundle import export_evidence_bundle


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gtm-signals", description="Analyze B2B channel opportunities")
    subparsers = parser.add_subparsers(dest="command", required=True)
    analyze = subparsers.add_parser("analyze", help="Analyze a normalized account JSON file")
    analyze.add_argument("input", type=Path)
    analyze.add_argument("--output", type=Path)
    analyze.add_argument("--pretty", action="store_true")
    crawl = subparsers.add_parser("crawl", help="Collect and normalize a bounded public website crawl")
    crawl.add_argument("domain")
    crawl.add_argument("--output-dir", type=Path, default=Path("data/runs"))
    crawl.add_argument("--maximum-pages", type=int, default=100)
    crawl.add_argument("--maximum-sitemaps", type=int, default=20)
    crawl.add_argument("--delay-seconds", type=float, default=0.25)
    crawl_analyze = subparsers.add_parser(
        "crawl-and-analyze", help="Run a bounded Scrapling crawl and Phase 1 website analysis"
    )
    crawl_analyze.add_argument("domain")
    crawl_analyze.add_argument("--output", type=Path, required=True)
    crawl_analyze.add_argument("--output-dir", type=Path, default=Path("data/runs"))
    crawl_analyze.add_argument("--account-name")
    crawl_analyze.add_argument("--maximum-pages", type=int, default=100)
    crawl_analyze.add_argument("--maximum-sitemaps", type=int, default=20)
    crawl_analyze.add_argument("--delay-seconds", type=float, default=0.25)
    crawl_analyze.add_argument("--config", type=Path)
    classify = subparsers.add_parser("classify-crawl", help="Classify pages from a saved crawl run")
    classify.add_argument("run_dir", type=Path)
    repair_canonicals = subparsers.add_parser(
        "repair-canonicals", help="Repair older saved pages using immutable Scrapling final URLs"
    )
    repair_canonicals.add_argument("run_dir", type=Path)
    assets = subparsers.add_parser("analyze-assets", help="Assess asset quality and freshness from a saved crawl")
    assets.add_argument("run_dir", type=Path)
    score = subparsers.add_parser("score-syndication", help="Score content-syndication readiness from analyzed assets")
    score.add_argument("run_dir", type=Path)
    score.add_argument("--config", type=Path)
    fit = subparsers.add_parser("score-fit", help="Score sourced account-fit evidence")
    fit.add_argument("run_dir", type=Path)
    fit.add_argument("profile", type=Path)
    fit.add_argument("--config", type=Path)
    gap = subparsers.add_parser("score-gap", help="Score Scrapling-backed channel-gap evidence")
    gap.add_argument("run_dir", type=Path)
    gap.add_argument("profile", type=Path)
    gap.add_argument("--config", type=Path)
    collect_gap = subparsers.add_parser("collect-gap-targets", help="Fetch high-signal gap pages with Scrapling")
    collect_gap.add_argument("run_dir", type=Path)
    collect_gap.add_argument("--maximum-pages", type=int, default=10)
    collect_gap.add_argument("--maximum-depth", type=int, default=1)
    collect_gap.add_argument("--delay-seconds", type=float, default=0.25)
    collect_gap.add_argument("--url", action="append", dest="include_urls")
    discover_gap = subparsers.add_parser("discover-gap-candidates", help="Surface saved-page gap candidates for review")
    discover_gap.add_argument("run_dir", type=Path)
    discover_initiative = subparsers.add_parser(
        "discover-initiative-candidates", help="Surface dated job/campaign initiatives for trigger review"
    )
    discover_initiative.add_argument("run_dir", type=Path)
    ingest_initiative = subparsers.add_parser(
        "ingest-initiative-candidates", help="Ingest initiative candidates into the SQLite review queue"
    )
    ingest_initiative.add_argument("run_dir", type=Path)
    ingest_initiative.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    list_initiative = subparsers.add_parser(
        "list-initiative-candidates", help="List SQLite initiative review candidates"
    )
    list_initiative.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    list_initiative.add_argument("--status", choices=("pending", "approved", "rejected"))
    review_initiative = subparsers.add_parser(
        "review-initiative-candidate", help="Approve or reject one initiative candidate"
    )
    review_initiative.add_argument("candidate_id")
    review_initiative.add_argument("--decision", choices=("approve", "reject"), required=True)
    review_initiative.add_argument("--reviewer", required=True)
    review_initiative.add_argument("--notes", required=True)
    review_initiative.add_argument("--strength", choices=("confirmed", "likely", "possible"))
    review_initiative.add_argument("--confidence", type=float)
    review_initiative.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    export_trigger = subparsers.add_parser(
        "export-trigger-profile", help="Export approved run-bound initiative evidence"
    )
    export_trigger.add_argument("run_dir", type=Path)
    export_trigger.add_argument("--account-name", required=True)
    export_trigger.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    export_trigger.add_argument("--output", type=Path)
    score_trigger = subparsers.add_parser("score-trigger", help="Score reviewed business-trigger evidence")
    score_trigger.add_argument("run_dir", type=Path)
    score_trigger.add_argument("profile", type=Path)
    score_trigger.add_argument("--config", type=Path)
    score_trigger.add_argument("--as-of", type=date.fromisoformat)
    paid = subparsers.add_parser(
        "score-paid-channels", help="Score retargeting and programmatic readiness/gap evidence"
    )
    paid.add_argument("run_dir", type=Path)
    paid.add_argument("profile", type=Path)
    paid.add_argument("--config", type=Path)
    deepline = subparsers.add_parser(
        "collect-deepline", help="Collect live Deepline/BuiltWith technology observations"
    )
    deepline.add_argument("run_dir", type=Path)
    deepline.add_argument("domain")
    apify = subparsers.add_parser(
        "collect-apify-ads", help="Collect live LinkedIn and Meta ad-library observations"
    )
    apify.add_argument("run_dir", type=Path)
    apify.add_argument("domain")
    apify.add_argument("--account-name", required=True)
    apify.add_argument("--linkedin-company-id")
    apify.add_argument("--config", type=Path)
    apify.add_argument("--platform", action="append", choices=("linkedin", "meta"))
    apify_replay = subparsers.add_parser(
        "replay-apify-ads", help="Re-normalize saved Apify datasets without a paid run"
    )
    apify_replay.add_argument("run_dir", type=Path)
    apify_replay.add_argument("domain")
    apify_replay.add_argument("--account-name", required=True)
    enqueue = subparsers.add_parser("enqueue-batch", help="Idempotently enqueue CSV/JSONL account jobs")
    enqueue.add_argument("input", type=Path)
    enqueue.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    jobs = subparsers.add_parser("list-jobs", help="List local analysis jobs")
    jobs.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    jobs.add_argument("--status", choices=("pending", "running", "completed", "partial", "failed"))
    run_one = subparsers.add_parser("run-job", help="Run or resume one local analysis job")
    run_one.add_argument("job_id")
    run_one.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    run_one.add_argument("--output-dir", type=Path, default=Path("data/runs"))
    run_one.add_argument("--report-dir", type=Path, default=Path("reports"))
    run_batch = subparsers.add_parser("run-pending-jobs", help="Run pending local jobs with bounded concurrency")
    run_batch.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    run_batch.add_argument("--output-dir", type=Path, default=Path("data/runs"))
    run_batch.add_argument("--report-dir", type=Path, default=Path("reports"))
    run_batch.add_argument("--workers", type=int, default=1)
    class_review = subparsers.add_parser("review-classification", help="Agree, disagree, or correct a saved classification")
    class_review.add_argument("run_dir", type=Path)
    class_review.add_argument("--url", required=True)
    class_review.add_argument("--content-sha256", required=True)
    class_review.add_argument("--signal-type", required=True)
    class_review.add_argument("--original-value", required=True)
    class_review.add_argument("--decision", choices=("agree", "disagree", "correct"), required=True)
    class_review.add_argument("--corrected-value")
    class_review.add_argument("--reviewer", required=True)
    class_review.add_argument("--notes", required=True)
    class_review.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    snapshot = subparsers.add_parser("snapshot-outreach", help="Persist the exact evidence/score state before outreach")
    snapshot.add_argument("run_dir", type=Path)
    snapshot.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    send = subparsers.add_parser("record-send", help="Attach an authorized outreach send to a saved snapshot")
    send.add_argument("snapshot_id")
    send.add_argument("--contact-ref", required=True)
    send.add_argument("--sent-at", required=True)
    send.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    outcomes = subparsers.add_parser("import-outcomes", help="Import CSV/JSONL outreach outcomes")
    outcomes.add_argument("input", type=Path)
    outcomes.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    metrics = subparsers.add_parser("outcome-metrics", help="Report channel outcome quality beyond reply rate")
    metrics.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    signal_metrics = subparsers.add_parser("signal-outcome-metrics", help="Report outcomes by frozen signal and channel")
    signal_metrics.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    bundle = subparsers.add_parser("export-evidence-bundle", help="Export a qualified snapshot-bound evidence bundle")
    bundle.add_argument("run_dir", type=Path)
    bundle.add_argument("--output", type=Path, required=True)
    review_report = subparsers.add_parser(
        "build-review-report", help="Build an auditable account score and reasoning report"
    )
    review_report.add_argument("run_dir", type=Path)
    review_report.add_argument("--account-name", required=True)
    ingest_gap = subparsers.add_parser("ingest-gap-candidates", help="Ingest candidates into the SQLite review queue")
    ingest_gap.add_argument("run_dir", type=Path)
    ingest_gap.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    list_gap = subparsers.add_parser("list-gap-candidates", help="List SQLite gap review candidates")
    list_gap.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    list_gap.add_argument("--status", choices=("pending", "approved", "rejected"))
    review_gap = subparsers.add_parser("review-gap-candidate", help="Approve or reject one gap candidate")
    review_gap.add_argument("candidate_id")
    review_gap.add_argument("--decision", choices=("approve", "reject"), required=True)
    review_gap.add_argument("--reviewer", required=True)
    review_gap.add_argument("--notes", required=True)
    review_gap.add_argument("--strength", choices=("confirmed", "likely", "possible"))
    review_gap.add_argument("--confidence", type=float)
    review_gap.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    export_gap = subparsers.add_parser("export-gap-profile", help="Export approved run-bound gap evidence")
    export_gap.add_argument("run_dir", type=Path)
    export_gap.add_argument("--account-name", required=True)
    export_gap.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    export_gap.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "crawl":
        manifest, _, run_dir = collect_website(
            args.domain,
            output_root=args.output_dir,
            maximum_pages=args.maximum_pages,
            maximum_sitemaps=args.maximum_sitemaps,
            delay_seconds=args.delay_seconds,
            fetcher=ScraplingFetcher(),
        )
        print(json.dumps({"run_dir": str(run_dir), "manifest": manifest.__dict__}, indent=2, sort_keys=True))
        return 0 if manifest.status != "failed" else 1
    if args.command == "crawl-and-analyze":
        report = crawl_and_analyze(
            args.domain,
            output_path=args.output,
            output_root=args.output_dir,
            account_name=args.account_name,
            maximum_pages=args.maximum_pages,
            maximum_sitemaps=args.maximum_sitemaps,
            delay_seconds=args.delay_seconds,
            fetcher=ScraplingFetcher(),
            config_path=args.config,
        )
        print(json.dumps({"output": str(args.output), "run_dir": report["run_dir"]}, indent=2, sort_keys=True))
        return 0 if report["run"]["status"] != "failed" else 1
    if args.command == "classify-crawl":
        summary = classify_crawl_run(args.run_dir)
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    if args.command == "repair-canonicals":
        result = repair_cross_path_canonicals(args.run_dir)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.command == "analyze-assets":
        summary = analyze_asset_run(args.run_dir)
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    if args.command == "score-syndication":
        result = score_syndication_run(args.run_dir, args.config)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.command == "score-fit":
        result = score_account_fit_run(args.run_dir, args.profile, args.config)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.command == "score-gap":
        result = score_channel_gap_run(args.run_dir, args.profile, args.config)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.command == "collect-gap-targets":
        result = collect_gap_targets(
            args.run_dir,
            maximum_pages=args.maximum_pages,
            maximum_depth=args.maximum_depth,
            delay_seconds=args.delay_seconds,
            include_urls=args.include_urls,
            fetcher=ScraplingFetcher(),
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.command == "discover-gap-candidates":
        result = discover_gap_candidates(args.run_dir)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.command == "discover-initiative-candidates":
        result = discover_initiative_candidates(args.run_dir)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.command == "ingest-initiative-candidates":
        result = ingest_initiative_candidates(args.run_dir, args.database)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.command == "list-initiative-candidates":
        result = list_initiative_candidates(args.database, review_status=args.status)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.command == "review-initiative-candidate":
        result = review_initiative_candidate(
            args.candidate_id,
            decision=args.decision,
            reviewer=args.reviewer,
            notes=args.notes,
            database_path=args.database,
            strength=args.strength,
            confidence=args.confidence,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.command == "export-trigger-profile":
        result = export_trigger_profile(
            args.run_dir,
            account_name=args.account_name,
            database_path=args.database,
            output_path=args.output,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.command == "score-trigger":
        result = score_business_trigger_run(
            args.run_dir, args.profile, args.config, as_of=args.as_of
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.command == "build-review-report":
        result = build_account_review(args.run_dir, account_name=args.account_name)
        print(json.dumps({"json": result["json"], "markdown": result["markdown"]}, indent=2, sort_keys=True))
        return 0
    if args.command == "score-paid-channels":
        result = score_paid_channel_run(args.run_dir, args.profile, args.config)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.command == "collect-deepline":
        result = collect_deepline_technologies(args.run_dir, args.domain)
        print(json.dumps({
            "provider": result.provider,
            "records": len(result.records),
            "raw_payload_location": result.raw_payload_location,
            "incomplete": result.incomplete,
            "warnings": result.warnings,
        }, indent=2, sort_keys=True))
        return 1 if result.incomplete else 0
    if args.command == "collect-apify-ads":
        result = collect_apify_ads(
            args.run_dir, args.domain, account_name=args.account_name, config_path=args.config,
            linkedin_company_id=args.linkedin_company_id,
            platforms=tuple(args.platform) if args.platform else ("linkedin", "meta"),
        )
        print(json.dumps({
            "provider": result.provider,
            "records": len(result.records),
            "raw_payload_location": result.raw_payload_location,
            "incomplete": result.incomplete,
            "warnings": result.warnings,
        }, indent=2, sort_keys=True))
        return 1 if result.incomplete else 0
    if args.command == "replay-apify-ads":
        result = replay_apify_ads(args.run_dir, args.domain, account_name=args.account_name)
        print(json.dumps({
            "provider": result.provider, "records": len(result.records),
            "incomplete": result.incomplete, "warnings": result.warnings,
        }, indent=2, sort_keys=True))
        return 0
    if args.command == "enqueue-batch":
        result = enqueue_batch(args.input, args.database)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.command == "list-jobs":
        print(json.dumps(list_jobs(args.database, status=args.status), indent=2, sort_keys=True))
        return 0
    if args.command == "run-job":
        result = run_job(
            args.job_id, database_path=args.database, output_root=args.output_dir, report_root=args.report_dir
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.command == "run-pending-jobs":
        result = run_pending_jobs(
            database_path=args.database, output_root=args.output_dir,
            report_root=args.report_dir, workers=args.workers,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if all(item["status"] != "failed" for item in result) else 1
    if args.command == "review-classification":
        result = review_classification(
            args.run_dir, url=args.url, content_sha256=args.content_sha256,
            signal_type=args.signal_type, original_value=json.loads(args.original_value),
            decision=args.decision,
            corrected_value=json.loads(args.corrected_value) if args.corrected_value is not None else None,
            reviewer=args.reviewer, notes=args.notes, database_path=args.database,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.command == "snapshot-outreach":
        print(json.dumps(create_outreach_snapshot(args.run_dir, database_path=args.database), indent=2, sort_keys=True))
        return 0
    if args.command == "record-send":
        print(json.dumps(record_send(
            args.snapshot_id, contact_ref=args.contact_ref, sent_at=args.sent_at,
            database_path=args.database,
        ), indent=2, sort_keys=True))
        return 0
    if args.command == "import-outcomes":
        print(json.dumps(import_outcomes(args.input, args.database), indent=2, sort_keys=True))
        return 0
    if args.command == "outcome-metrics":
        print(json.dumps(outcome_metrics(args.database), indent=2, sort_keys=True))
        return 0
    if args.command == "signal-outcome-metrics":
        print(json.dumps(signal_outcome_metrics(args.database), indent=2, sort_keys=True))
        return 0
    if args.command == "export-evidence-bundle":
        print(json.dumps(export_evidence_bundle(args.run_dir, args.output), indent=2, sort_keys=True))
        return 0
    if args.command == "ingest-gap-candidates":
        result = ingest_gap_candidates(args.run_dir, args.database)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.command == "list-gap-candidates":
        result = list_gap_candidates(args.database, review_status=args.status)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.command == "review-gap-candidate":
        result = review_gap_candidate(
            args.candidate_id,
            decision=args.decision,
            reviewer=args.reviewer,
            notes=args.notes,
            database_path=args.database,
            strength=args.strength,
            confidence=args.confidence,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.command == "export-gap-profile":
        result = export_gap_profile(
            args.run_dir,
            account_name=args.account_name,
            database_path=args.database,
            output_path=args.output,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    result = analyze_account(payload)
    rendered = json.dumps(result, indent=2 if args.pretty else None, sort_keys=args.pretty)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
