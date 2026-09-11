from __future__ import annotations

from typing import Protocol

from .models import Evidence, Page


class SemanticClassifier(Protocol):
    """Optional structured classifier for deterministic unknowns only."""

    model_version: str
    prompt_version: str

    def classify(self, page: Page, signal_type: str) -> Evidence: ...


def resolve_unknown(
    page: Page,
    deterministic: Evidence,
    fallback: SemanticClassifier | None,
) -> Evidence:
    if deterministic.strength != "unknown" or fallback is None:
        return deterministic
    semantic = fallback.classify(page, deterministic.signal_type)
    if semantic.signal_type != deterministic.signal_type:
        raise ValueError("semantic fallback returned the wrong signal type")
    if semantic.url != page.url:
        raise ValueError("semantic fallback evidence URL does not match the page")
    if not 0 <= semantic.confidence <= 1:
        raise ValueError("semantic fallback confidence must be between 0 and 1")
    if not semantic.method.startswith("structured_llm:"):
        raise ValueError("semantic fallback must record structured_llm method and versions")
    return semantic
