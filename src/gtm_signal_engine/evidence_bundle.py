from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def export_evidence_bundle(run_dir: Path, output_path: Path) -> dict[str, Any]:
    normalized = run_dir / "normalized"
    review = json.loads((normalized / "account_review.json").read_text(encoding="utf-8"))
    score = json.loads((normalized / "syndication_score.json").read_text(encoding="utf-8"))
    if review["overall"]["snapshot_id"] != score["snapshot_id"]:
        raise ValueError("account review and syndication score snapshots do not match")
    qualification = score["qualification"]
    if qualification["opportunity_status"] != "qualified":
        raise ValueError(
            "evidence bundle export requires a qualified account; "
            f"current blockers: {', '.join(qualification.get('blockers', [])) or 'qualification gate'}"
        )
    bundle = {
        "schema_version": "1.0",
        "account": review["account"],
        "channel": score["channel"],
        "run": review["run"],
        "score": {
            "scoring_version": score["scoring_version"],
            "snapshot_id": score["snapshot_id"],
            "components": review["components"],
            "weighted_total": score["total"],
            "confidence": score["confidence"],
            "qualification": qualification,
        },
        "evidence": review["signals"],
        "interpretation": review["interpretation"],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"output": str(output_path), "snapshot_id": score["snapshot_id"], "account": review["account"]}
