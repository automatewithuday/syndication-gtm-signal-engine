from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Literal

EvidenceStrength = Literal["confirmed", "likely", "possible", "unknown", "contradicted"]
Channel = Literal["content_syndication", "retargeting", "programmatic", "outbound_calling"]


@dataclass(frozen=True)
class FormField:
    name: str
    field_type: str
    placeholder: str = ""


@dataclass(frozen=True)
class FormObservation:
    action_url: str
    method: str
    fields: list[FormField]
    submit_text: str
    purpose: str = "unknown"
    confidence: float = 0.0


@dataclass(frozen=True)
class ContentAsset:
    url: str
    title: str
    asset_type: str
    gating: str
    substantial: str
    syndication_suitability: str
    content_hash: str
    observed_at: str
    published_or_created: dict[str, Any] | None = None
    evidence_excerpts: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ConversionPath:
    url: str
    conversion_type: str
    excerpt: str
    observed_at: str
    confidence: float


@dataclass(frozen=True)
class CustomerProof:
    url: str
    customer_name: str | None
    excerpt: str
    quantified_outcome: str | None
    observed_at: str
    confidence: float


@dataclass(frozen=True)
class Page:
    url: str
    original_url: str | None = None
    title: str = ""
    text: str = ""
    main_text: str = ""
    published_at: str | None = None
    date_candidates: list[dict[str, str]] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    link_details: list[dict[str, str]] = field(default_factory=list)
    forms: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    content_hash: str | None = None
    observed_at: str | None = None
    status_code: int | None = None


@dataclass(frozen=True)
class Evidence:
    signal_type: str
    value: Any
    strength: EvidenceStrength
    confidence: float
    url: str
    excerpt: str = ""
    method: str = "deterministic_rule"
    extractor_version: str = "page_rules_v1"
    observed_at: str = field(default_factory=lambda: date.today().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OpportunityScore:
    channel: Channel
    fit: float
    readiness: float
    gap: float | None
    trigger: float | None
    confidence: float
    reasons: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)

    @property
    def total(self) -> float | None:
        if self.gap is None or self.trigger is None:
            return None
        return round(self.fit * 0.30 + self.readiness * 0.25 + self.gap * 0.25 + self.trigger * 0.20, 1)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["total"] = self.total
        return result
