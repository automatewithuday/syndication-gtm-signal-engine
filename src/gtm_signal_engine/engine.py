from __future__ import annotations

from typing import Any

from .classifiers import analyze_page
from .models import Page
from .scoring import aggregate_metrics, score_opportunities


def analyze_account(payload: dict[str, Any]) -> dict[str, Any]:
    account = payload.get("account", {})
    pages = [Page(**page) for page in payload.get("pages", [])]
    evidence = [item for page in pages for item in analyze_page(page)]
    metrics = aggregate_metrics(evidence, account)
    opportunities = sorted(
        score_opportunities(account, metrics),
        key=lambda item: (item.total is not None, item.total or -1),
        reverse=True,
    )
    return {
        "schema_version": "1.0",
        "engine_version": "1.0.0",
        "account": {"name": account.get("name"), "domain": account.get("domain")},
        "metrics": metrics,
        "opportunities": [item.to_dict() for item in opportunities],
        "evidence": [item.to_dict() for item in evidence],
    }
