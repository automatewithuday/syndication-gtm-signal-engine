from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .gap_discovery import _excerpt, _load_pages, _page_source_date
from .review_queue import (
    DEFAULT_DATABASE_PATH,
    VALID_DECISIONS,
    VALID_STRENGTHS,
    _load_scrapling_run,
    _now,
    connect_database,
)

EXTRACTOR_VERSION = "outbound_gap_candidate_rules_v1"
SCORING_LOGIC_VERSION = "outbound_calling_scorer_v1"
DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "outbound_calling_scoring.v1.json"
)

CHANNEL_TERM = (
    r"(?:outbound calling|cold calling|phone outreach|telephone outreach|"
    r"prospecting calls?|sales calls?|calling prospects?|power dialer|sales dialer)"
)
SIGNAL_PATTERNS = (
    (
        "explicit_expansion_intent", "supports_gap",
        r"(?:plan(?:ning)? to|want to|need to|looking to|aim(?:ing)? to|will)\s+"
        r"(?:launch|add|expand|scale|increase|invest in|build)",
    ),
    (
        "documented_outbound_bottleneck", "supports_gap",
        r"(?:manual|struggl\w*|challenge\w*|bottleneck\w*|limited|unable to|"
        r"lack(?:ing)?|capacity gap)",
    ),
    (
        "active_outbound_partner_or_hiring_search", "supports_gap",
        r"(?:hiring|request for proposal|RFP|seeking\s+(?:an?\s+)?(?:agency|sales|"
        r"outbound)\s+partner|(?:agency|sales|outbound)\s+partner\s+wanted)",
    ),
    (
        "documented_outbound_performance_shortfall", "supports_gap",
        r"(?:low connect rates?|low conversions?|declining pipeline|underperform\w*|"
        r"missed pipeline|limited reach|not enough meetings?|poor conversion)",
    ),
    (
        "documented_healthy_outbound_program", "contradicts_gap",
        r"(?:active|ongoing|mature|established|always-on|scaled|successful)\s+"
        r"(?:program|team|motion|strategy|channel)",
    ),
    (
        "documented_outbound_success", "contradicts_gap",
        r"(?:generated|drove|delivered|increased|improved|booked)\b.{0,90}"
        r"(?:pipeline|revenue|qualified leads?|meetings?|opportunities|conversion)",
    ),
)


def _rule(evidence_term: str) -> re.Pattern[str]:
    return re.compile(
        rf"(?:\b{evidence_term}\b.{{0,180}}\b{CHANNEL_TERM}\b|"
        rf"\b{CHANNEL_TERM}\b.{{0,180}}\b{evidence_term}\b)",
        re.I | re.S,
    )


RULES = tuple(
    (signal_type, position, _rule(term))
    for signal_type, position, term in SIGNAL_PATTERNS
)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _stable_artifact_identity(path: Path) -> str | None:
    """Return an upstream semantic identity without hashing processing timestamps."""
    if not path.is_file():
        return None
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return _sha256(raw)
    if value.get("snapshot_id"):
        return str(value["snapshot_id"])
    artifact_input = value.get("input")
    if isinstance(artifact_input, dict):
        stable_input = {
            key: item for key, item in artifact_input.items()
            if key.endswith("sha256") or key in {"run_id", "page_count"}
        }
        if stable_input:
            return _sha256(json.dumps(
                stable_input, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8"))
    return _sha256(raw)


def _default_config() -> Path:
    candidates = (
        Path.cwd() / "config" / "outbound_calling_scoring.v1.json",
        DEFAULT_CONFIG_PATH,
        Path(sys.prefix) / "share" / "gtm-signal-engine" / "outbound_calling_scoring.v1.json",
    )
    return next((candidate for candidate in candidates if candidate.is_file()), candidates[0])


def discover_outbound_gap_candidates(run_dir: Path) -> dict[str, Any]:
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("provider") != "ScraplingFetcher":
        raise ValueError("outbound gap discovery requires a ScraplingFetcher run")
    pages, pages_raw = _load_pages(run_dir / "normalized" / "pages.jsonl")
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for page in pages:
        segments = {part for part in urlsplit(page.url).path.casefold().split("/") if part}
        if segments.intersection({
            "case-study", "case-studies", "customer", "customers",
            "customer-stories", "partners", "directory", "tools",
        }):
            continue
        text = " ".join((page.main_text or page.text).split())
        for signal_type, position, pattern in RULES:
            for match in pattern.finditer(text):
                excerpt = _excerpt(text, match.start(), match.end())
                identity = (page.url, signal_type, _sha256(excerpt.encode("utf-8")))
                if identity in seen:
                    continue
                seen.add(identity)
                candidate_id = _sha256("|".join(identity).encode("utf-8"))
                candidates.append({
                    "candidate_id": candidate_id,
                    "channel": "outbound_calling",
                    "signal_type": signal_type,
                    "suggested_position": position,
                    "review_status": "pending",
                    "url": page.url,
                    "excerpt": excerpt,
                    "matched_text": " ".join(match.group(0).split()),
                    "observed_at": page.observed_at,
                    "source_date": _page_source_date(page),
                    "content_sha256": page.content_hash,
                    "method": "scrapling_saved_page_candidate",
                    "extractor_version": EXTRACTOR_VERSION,
                })
    output = run_dir / "normalized" / "outbound_gap_candidates.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for candidate in candidates:
            handle.write(json.dumps(candidate, sort_keys=True) + "\n")
    summary = {
        "schema_version": "1.0",
        "extractor_version": EXTRACTOR_VERSION,
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "input": {
            "run_id": manifest["run_id"],
            "pages_file": "normalized/pages.jsonl",
            "pages_sha256": _sha256(pages_raw),
            "page_count": len(pages),
        },
        "candidate_count": len(candidates),
        "by_signal_type": dict(sorted(Counter(
            item["signal_type"] for item in candidates
        ).items())),
        "review_status": "pending" if candidates else "no_candidates",
        "warning": "candidates require review; no candidates means unknown, never no gap",
    }
    (run_dir / "normalized" / "outbound_gap_candidate_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def ingest_outbound_gap_candidates(
    run_dir: Path, database_path: Path = DEFAULT_DATABASE_PATH,
) -> dict[str, Any]:
    manifest, domain = _load_scrapling_run(run_dir)
    path = run_dir / "normalized" / "outbound_gap_candidates.jsonl"
    if not path.is_file():
        raise FileNotFoundError(
            "outbound gap candidates missing; run discover-outbound-gap-candidates first"
        )
    candidates = [json.loads(line) for line in path.read_bytes().splitlines() if line.strip()]
    inserted = 0
    seen_again = 0
    timestamp = _now()
    with connect_database(database_path) as connection:
        for item in candidates:
            existing = connection.execute(
                "SELECT review_status FROM outbound_gap_candidates WHERE candidate_id = ?",
                (item["candidate_id"],),
            ).fetchone()
            connection.execute(
                """
                INSERT INTO outbound_gap_candidates(
                    candidate_id, account_domain, signal_type, suggested_position,
                    url, excerpt, matched_text, extractor_version, source_date_json,
                    first_seen_at, last_seen_at, latest_run_id, latest_content_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(candidate_id) DO UPDATE SET
                    review_status = CASE
                        WHEN outbound_gap_candidates.latest_run_id = excluded.latest_run_id
                         AND outbound_gap_candidates.latest_content_sha256 = excluded.latest_content_sha256
                        THEN outbound_gap_candidates.review_status ELSE 'pending' END,
                    last_seen_at = excluded.last_seen_at,
                    latest_run_id = excluded.latest_run_id,
                    latest_content_sha256 = excluded.latest_content_sha256,
                    source_date_json = excluded.source_date_json
                """,
                (
                    item["candidate_id"], domain, item["signal_type"],
                    item["suggested_position"], item["url"], item["excerpt"],
                    item["matched_text"], item["extractor_version"],
                    json.dumps(item.get("source_date"), sort_keys=True)
                    if item.get("source_date") else None,
                    timestamp, timestamp, manifest["run_id"], item["content_sha256"],
                ),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO outbound_gap_candidate_occurrences(
                    candidate_id, run_id, content_sha256, observed_at,
                    source_date_json, ingested_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    item["candidate_id"], manifest["run_id"], item["content_sha256"],
                    item["observed_at"],
                    json.dumps(item.get("source_date"), sort_keys=True)
                    if item.get("source_date") else None,
                    timestamp,
                ),
            )
            inserted += int(existing is None)
            seen_again += int(existing is not None)
    return {
        "run_id": manifest["run_id"], "database": str(database_path),
        "candidates_in_file": len(candidates), "inserted": inserted,
        "seen_again": seen_again,
    }


def list_outbound_gap_candidates(
    database_path: Path = DEFAULT_DATABASE_PATH, *, review_status: str | None = None,
) -> list[dict[str, Any]]:
    if review_status not in {None, "pending", "approved", "rejected"}:
        raise ValueError("review_status must be pending, approved, or rejected")
    sql = "SELECT * FROM outbound_gap_candidates"
    parameters: tuple[str, ...] = ()
    if review_status:
        sql += " WHERE review_status = ?"
        parameters = (review_status,)
    sql += " ORDER BY last_seen_at DESC, candidate_id"
    with connect_database(database_path) as connection:
        return [dict(row) for row in connection.execute(sql, parameters)]


def review_outbound_gap_candidate(
    candidate_id: str, *, decision: str, reviewer: str, notes: str,
    database_path: Path = DEFAULT_DATABASE_PATH, strength: str | None = None,
    confidence: float | None = None,
) -> dict[str, Any]:
    if decision not in VALID_DECISIONS:
        raise ValueError("decision must be approve or reject")
    if not reviewer.strip() or not notes.strip():
        raise ValueError("reviewer and notes are required")
    if decision == "approve":
        if strength not in VALID_STRENGTHS:
            raise ValueError("approved candidates require confirmed, likely, or possible strength")
        if confidence is None or not 0 <= confidence <= 1:
            raise ValueError("approved candidates require confidence between 0 and 1")
    elif strength is not None or confidence is not None:
        raise ValueError("strength and confidence apply only to approvals")
    with connect_database(database_path) as connection:
        candidate = connection.execute(
            "SELECT * FROM outbound_gap_candidates WHERE candidate_id = ?",
            (candidate_id,),
        ).fetchone()
        if candidate is None:
            raise KeyError(f"candidate not found: {candidate_id}")
        reviewed_at = _now()
        connection.execute(
            """
            INSERT INTO outbound_gap_candidate_reviews(
                candidate_id, run_id, content_sha256, decision, reviewer, notes,
                strength, confidence, reviewed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate_id, candidate["latest_run_id"],
                candidate["latest_content_sha256"], decision, reviewer.strip(),
                notes.strip(), strength, confidence, reviewed_at,
            ),
        )
        status = "approved" if decision == "approve" else "rejected"
        connection.execute(
            "UPDATE outbound_gap_candidates SET review_status = ? WHERE candidate_id = ?",
            (status, candidate_id),
        )
    return {
        "candidate_id": candidate_id, "run_id": candidate["latest_run_id"],
        "content_sha256": candidate["latest_content_sha256"],
        "review_status": status, "reviewed_at": reviewed_at,
    }


def export_outbound_gap_profile(
    run_dir: Path, *, account_name: str,
    database_path: Path = DEFAULT_DATABASE_PATH,
    output_path: Path | None = None,
) -> dict[str, Any]:
    manifest, domain = _load_scrapling_run(run_dir)
    pages = {
        (item["url"], item["content_hash"]): item
        for line in (run_dir / "normalized" / "pages.jsonl").read_bytes().splitlines()
        if line.strip() for item in [json.loads(line)]
    }
    with connect_database(database_path) as connection:
        rows = connection.execute(
            """
            SELECT c.*, o.observed_at, o.content_sha256 AS occurrence_content_sha256,
                   o.source_date_json AS occurrence_source_date_json,
                   r.strength, r.confidence
            FROM outbound_gap_candidates c
            JOIN outbound_gap_candidate_occurrences o
              ON o.candidate_id = c.candidate_id AND o.run_id = ?
            JOIN outbound_gap_candidate_reviews r ON r.review_id = (
                SELECT MAX(r2.review_id) FROM outbound_gap_candidate_reviews r2
                WHERE r2.candidate_id = c.candidate_id AND r2.run_id = o.run_id
                  AND r2.content_sha256 = o.content_sha256
            )
            WHERE c.account_domain = ? AND r.decision = 'approve'
            ORDER BY c.candidate_id
            """,
            (manifest["run_id"], domain),
        ).fetchall()
    observations: list[dict[str, Any]] = []
    for row in rows:
        page = pages.get((row["url"], row["occurrence_content_sha256"]))
        if page is None:
            raise ValueError(
                f"approved outbound evidence no longer binds to a saved page: {row['candidate_id']}"
            )
        page_text = " ".join((page.get("main_text") or page.get("text") or "").split())
        if " ".join(row["matched_text"].split()) not in page_text:
            raise ValueError(
                f"approved outbound evidence text is not present in the saved page: {row['candidate_id']}"
            )
        item = {
            "channel": "outbound_calling",
            "position": row["suggested_position"],
            "signal_type": row["signal_type"],
            "strength": row["strength"],
            "confidence": row["confidence"],
            "url": row["url"], "excerpt": row["excerpt"],
            "observed_at": row["observed_at"],
            "method": "scrapling_saved_page",
            "content_sha256": row["occurrence_content_sha256"],
            "review_status": "approved",
        }
        if row["occurrence_source_date_json"]:
            item["source_date"] = json.loads(row["occurrence_source_date_json"])
        observations.append(item)
    profile = {
        "schema_version": "1.0",
        "account": {"name": account_name, "domain": domain},
        "channel": "outbound_calling",
        "observations": observations,
        "risks": [
            "Calling activity is rarely public; no approved observation means unknown, not no gap."
        ],
    }
    selected = output_path or run_dir / "normalized" / "outbound_gap_profile.json"
    selected.parent.mkdir(parents=True, exist_ok=True)
    selected.write_text(json.dumps(profile, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "run_id": manifest["run_id"], "database": str(database_path),
        "output": str(selected), "approved_observations": len(observations),
    }


def _gap_component(observations: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    settings = config["gap"]
    approved = [item for item in observations if item.get("review_status") == "approved"]
    for item in approved:
        signal_type = item.get("signal_type")
        position = item.get("position")
        valid_position = (
            position == "supports_gap" and signal_type in settings["signal_points"]
        ) or (
            position == "contradicts_gap" and signal_type in settings["contradiction_types"]
        )
        if item.get("channel") != "outbound_calling" or not valid_position:
            raise ValueError("outbound gap evidence has an unsupported signal type or position")
        if (
            item.get("method") != "scrapling_saved_page"
            or not item.get("content_sha256")
            or not item.get("url")
            or not item.get("excerpt")
            or not item.get("observed_at")
        ):
            raise ValueError("outbound gap evidence must be bound to an approved Scrapling page")
        if item.get("strength") not in settings["strength_credit"]:
            raise ValueError("outbound gap evidence has an unsupported strength")
        confidence = item.get("confidence")
        if not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
            raise ValueError("outbound gap evidence confidence must be between 0 and 1")
    supporting = [item for item in approved if item.get("position") == "supports_gap"]
    contradicting = [item for item in approved if item.get("position") == "contradicts_gap"]
    if supporting and contradicting:
        return {
            "score": None, "state": "unknown", "status": "review",
            "confidence": min(float(item["confidence"]) for item in approved),
            "evidence": approved,
            "reasons": ["approved supporting and contradicting outbound evidence coexist"],
        }
    if contradicting:
        return {
            "score": 0.0, "state": "contradicted", "status": "disqualified",
            "confidence": round(sum(float(item["confidence"]) for item in contradicting) / len(contradicting), 3),
            "evidence": contradicting,
            "reasons": ["approved evidence documents a healthy or successful outbound-calling motion"],
        }
    if not supporting:
        return {
            "score": None, "state": "unknown", "status": "insufficient_evidence",
            "confidence": 0.0, "evidence": [],
            "reasons": ["no approved positive outbound gap evidence; public-web absence is unknown"],
        }
    strongest: dict[str, tuple[float, dict[str, Any]]] = {}
    for item in supporting:
        signal_type = item["signal_type"]
        if signal_type not in settings["signal_points"]:
            raise ValueError(f"unsupported outbound gap signal type: {signal_type}")
        rank = float(item["confidence"]) * float(settings["strength_credit"][item["strength"]])
        if signal_type not in strongest or rank > strongest[signal_type][0]:
            strongest[signal_type] = (rank, item)
    score = round(sum(
        float(settings["signal_points"][key]) * value[0]
        for key, value in strongest.items()
    ), 1)
    confidence = round(sum(float(value[1]["confidence"]) for value in strongest.values()) / len(strongest), 3)
    passes = (
        len(strongest) >= int(settings["minimum_supporting_signal_types"])
        and score >= float(settings["minimum_score"])
        and confidence >= float(settings["minimum_confidence"])
    )
    return {
        "score": score, "state": "observed",
        "status": "provisional_pass" if passes else "review",
        "confidence": confidence,
        "evidence": [value[1] for value in strongest.values()],
        "reasons": [f"{len(strongest)} distinct approved outbound gap signal type(s)"],
    }


def _readiness_component(
    account_fit: dict[str, Any] | None, evidence: list[dict[str, Any]],
    assets: dict[str, Any] | None, config: dict[str, Any],
) -> dict[str, Any]:
    settings = config["readiness"]
    weights = settings["factor_weights"]
    fit_factors = {
        item.get("id"): item
        for item in (account_fit or {}).get("component", {}).get("factors", [])
    }
    factors: list[dict[str, Any]] = []
    known_weight = 0.0
    earned = 0.0
    confidence_total = 0.0
    for factor_id in ("professional_buyer_coverage", "sales_motion", "operating_scale"):
        maximum = float(weights[factor_id])
        source = fit_factors.get(factor_id, {})
        known = source.get("state") not in {None, "unknown"}
        source_maximum = float(source.get("maximum_points") or 0)
        points = (
            round(maximum * float(source.get("points") or 0) / source_maximum, 1)
            if known and source_maximum else None
        )
        source_evidence = source.get("evidence", [])
        confidence = (
            sum(float(item.get("confidence") or 0) for item in source_evidence) / len(source_evidence)
            if source_evidence else 0.0
        )
        factors.append({
            "id": factor_id, "state": "observed" if known else "unknown",
            "observed": source.get("observed") if known else None,
            "maximum_points": maximum, "points": points,
            "confidence": round(confidence, 3), "source": "normalized/account_fit.json",
        })
        if points is not None:
            known_weight += maximum
            earned += points
            confidence_total += maximum * confidence
    conversion_items = [
        item for item in evidence
        if item.get("signal_type") == "conversion_path"
        and item.get("value") in {"demo", "contact_sales", "pricing"}
    ]
    case_studies = int((assets or {}).get("asset_types", {}).get("case_study", 0))
    for factor_id, count, source_name in (
        ("sales_conversion_paths", len({item.get("value") for item in conversion_items}), "normalized/evidence.jsonl"),
        ("customer_proof", case_studies, "normalized/asset_summary.json"),
    ):
        maximum = float(weights[factor_id])
        known = count > 0
        points = (
            round(maximum * min(1.0, count / float(settings["full_at"][factor_id])), 1)
            if known else None
        )
        confidence = (
            sum(float(item.get("confidence") or 0) for item in conversion_items) / len(conversion_items)
            if factor_id == "sales_conversion_paths" and conversion_items
            else 0.85 if known else 0.0
        )
        factors.append({
            "id": factor_id, "state": "observed" if known else "unknown",
            "observed": count if known else None, "maximum_points": maximum,
            "points": points, "confidence": round(confidence, 3), "source": source_name,
        })
        if points is not None:
            known_weight += maximum
            earned += points
            confidence_total += maximum * confidence
    if not known_weight:
        return {
            "score": None, "state": "unknown", "status": "insufficient_evidence",
            "confidence": 0.0, "evidence_coverage": 0.0, "factors": factors,
            "reasons": ["no positive outbound-readiness evidence is available"],
            "risks": ["unobserved readiness factors are unknown, not zero"],
        }
    score = round(100 * earned / known_weight, 1)
    coverage = round(known_weight / 100, 3)
    confidence = round(confidence_total / 100, 3)
    passes = (
        score >= float(settings["minimum_score"])
        and confidence >= float(settings["minimum_confidence"])
        and coverage >= float(settings["minimum_evidence_coverage"])
    )
    return {
        "score": score, "state": "observed",
        "status": "provisional_pass" if passes else "review",
        "confidence": confidence, "evidence_coverage": coverage,
        "factors": factors,
        "reasons": [f"{sum(item['state'] == 'observed' for item in factors)} of {len(factors)} readiness factors observed"],
        "risks": [
            "readiness indicates an addressable sales motion; it does not prove a calling gap",
            "weights are provisional pending outbound outcome labels",
        ],
    }


def score_outbound_calling_run(
    run_dir: Path, profile_path: Path | None = None,
    config_path: Path | None = None,
) -> dict[str, Any]:
    manifest, domain = _load_scrapling_run(run_dir)
    selected_profile = profile_path or run_dir / "normalized" / "outbound_gap_profile.json"
    if not selected_profile.is_file():
        raise FileNotFoundError("outbound gap profile missing; export reviewed outbound evidence first")
    profile_raw = selected_profile.read_bytes()
    profile = json.loads(profile_raw)
    if profile.get("channel") != "outbound_calling" or str(
        profile.get("account", {}).get("domain", "")
    ).lower().removeprefix("www.") != domain:
        raise ValueError("outbound profile does not match the Scrapling run")
    pages = {
        (page.url, page.content_hash): page
        for page in _load_pages(run_dir / "normalized" / "pages.jsonl")[0]
    }
    for observation in profile.get("observations", []):
        page = pages.get((observation.get("url"), observation.get("content_sha256")))
        if page is None:
            raise ValueError("outbound profile evidence does not bind to this saved Scrapling run")
        page_text = " ".join((page.main_text or page.text).split())
        excerpt = " ".join(str(observation.get("excerpt", "")).split())
        if (
            observation.get("method") != "scrapling_saved_page"
            or observation.get("observed_at") != page.observed_at
            or not excerpt
            or excerpt not in page_text
        ):
            raise ValueError("outbound profile evidence does not match its saved Scrapling page")
    config_file = config_path or _default_config()
    config_raw = config_file.read_bytes()
    config = json.loads(config_raw)
    if config.get("version") != "outbound_calling_v1":
        raise ValueError("unsupported outbound calling scoring version")
    if abs(sum(float(value) for value in config["readiness"]["factor_weights"].values()) - 100) > 1e-9:
        raise ValueError("outbound readiness weights must sum to 100")
    if abs(sum(float(value) for value in config["component_weights"].values()) - 1) > 1e-9:
        raise ValueError("outbound component weights must sum to 1")
    if set(config["gap"]["signal_points"]).intersection(config["gap"]["contradiction_types"]):
        raise ValueError("outbound supporting and contradiction signal types must be disjoint")
    account_fit_path = run_dir / "normalized" / "account_fit.json"
    evidence_path = run_dir / "normalized" / "evidence.jsonl"
    assets_path = run_dir / "normalized" / "asset_summary.json"
    trigger_path = run_dir / "normalized" / "business_trigger.json"
    account_fit = json.loads(account_fit_path.read_text()) if account_fit_path.is_file() else None
    evidence_raw = evidence_path.read_bytes() if evidence_path.is_file() else b""
    evidence = [json.loads(line) for line in evidence_raw.splitlines() if line.strip()]
    assets = json.loads(assets_path.read_text()) if assets_path.is_file() else None
    trigger = json.loads(trigger_path.read_text()) if trigger_path.is_file() else None
    fit = dict((account_fit or {}).get("component") or {
        "score": None, "state": "unknown", "status": "insufficient_evidence",
        "confidence": 0.0,
    })
    readiness = _readiness_component(account_fit, evidence, assets, config)
    gap = _gap_component(profile.get("observations", []), config)
    trigger_component = dict((trigger or {}).get("component") or {
        "score": None, "state": "unknown", "status": "insufficient_evidence",
        "confidence": 0.0,
    })
    components = {
        "fit": fit, "readiness": readiness, "gap": gap, "trigger": trigger_component,
    }
    blockers = [key for key, value in components.items() if value.get("score") is None]
    total = None if blockers else round(sum(
        float(components[key]["score"]) * float(weight)
        for key, weight in config["component_weights"].items()
    ), 1)
    known_confidences = [
        float(item.get("confidence") or 0) for item in components.values()
        if item.get("score") is not None
    ]
    coverage = round(sum(
        float(config["component_weights"][key]) for key, item in components.items()
        if item.get("score") is not None
    ), 3)
    confidence = round(min(known_confidences) * coverage, 3) if known_confidences else 0.0
    qualified = (
        total is not None
        and total >= float(config["qualification"]["minimum_total"])
        and confidence >= float(config["qualification"]["minimum_confidence"])
        and fit.get("status") == "provisional_pass"
        and readiness.get("status") == "provisional_pass"
        and gap.get("status") == "provisional_pass"
    )
    hashes = {
        "profile": _sha256(profile_raw),
        "account_fit": _stable_artifact_identity(account_fit_path),
        "evidence": _sha256(evidence_raw) if evidence_raw else None,
        "assets": _stable_artifact_identity(assets_path),
        "business_trigger": _stable_artifact_identity(trigger_path),
        "config": _sha256(config_raw),
    }
    snapshot_id = _sha256(json.dumps({
        "run_id": manifest["run_id"], "hashes": hashes,
        "scoring_logic_version": SCORING_LOGIC_VERSION,
    }, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    result = {
        "schema_version": "1.0", "channel": "outbound_calling",
        "scoring_version": config["version"],
        "scoring_logic_version": SCORING_LOGIC_VERSION,
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "snapshot_id": snapshot_id,
        "account": profile["account"], "components": components,
        "total": total, "confidence": confidence,
        "evidence_coverage": coverage,
        "qualification": {
            "opportunity_status": "qualified" if qualified else "insufficient_evidence",
            "blockers": blockers,
            "thresholds": config["qualification"],
        },
        "input": {"run_id": manifest["run_id"], "artifact_sha256": hashes},
        "calibration": config["calibration"],
    }
    (run_dir / "normalized" / "outbound_calling_score.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result
