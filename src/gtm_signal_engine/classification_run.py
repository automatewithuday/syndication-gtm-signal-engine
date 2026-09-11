from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .classifiers import analyze_page
from .models import Evidence, Page
from .semantic import SemanticClassifier, resolve_unknown


def classify_crawl_run(
    run_dir: Path, semantic_classifier: SemanticClassifier | None = None
) -> dict[str, Any]:
    pages_path = run_dir / "normalized" / "pages.jsonl"
    if not pages_path.exists():
        raise FileNotFoundError(f"normalized crawl pages not found: {pages_path}")

    input_bytes = pages_path.read_bytes()
    pages = [Page(**json.loads(line)) for line in input_bytes.splitlines() if line.strip()]
    evidence = [
        resolve_unknown(page, item, semantic_classifier)
        for page in pages
        for item in analyze_page(page)
    ]

    evidence_path = run_dir / "normalized" / "evidence.jsonl"
    with evidence_path.open("w", encoding="utf-8") as handle:
        for item in evidence:
            handle.write(json.dumps(item.to_dict(), sort_keys=True) + "\n")

    def values(signal_type: str) -> list[Any]:
        return [item.value for item in evidence if item.signal_type == signal_type]

    summary = {
        "schema_version": "1.0",
        "extractor_version": "page_rules_v1",
        "semantic_fallback": (
            {
                "model_version": semantic_classifier.model_version,
                "prompt_version": semantic_classifier.prompt_version,
            }
            if semantic_classifier else None
        ),
        "classified_at": datetime.now(timezone.utc).isoformat(),
        "input": {
            "pages_file": str(pages_path.relative_to(run_dir)),
            "sha256": hashlib.sha256(input_bytes).hexdigest(),
            "page_count": len(pages),
        },
        "page_families": dict(sorted(Counter(values("page_family")).items())),
        "asset_types": dict(sorted(Counter(values("content_asset_type")).items())),
        "gating_types": dict(sorted(Counter(values("gating_type")).items())),
        "form_purposes": dict(sorted(Counter(
            value["purpose"] for value in values("form_purpose")
        ).items())),
        "unknown": {
            "page_family": sum(1 for value in values("page_family") if value == "unknown"),
            "gating_type": sum(1 for value in values("gating_type") if value == "unknown"),
            "form_purpose": sum(1 for value in values("form_purpose") if value["purpose"] == "unknown"),
        },
        "evidence_count": len(evidence),
    }
    (run_dir / "normalized" / "classification_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary
