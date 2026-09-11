from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .models import Page


@dataclass(frozen=True)
class ProviderResult:
    provider: str
    query: str
    records: list[dict[str, Any]] = field(default_factory=list)
    raw_payload_location: str | None = None
    incomplete: bool = False
    warnings: list[str] = field(default_factory=list)


class WebsiteProvider(Protocol):
    """Normalize crawled pages; implementations may use Firecrawl or another crawler."""

    def crawl_domain(self, domain: str, *, maximum_pages: int) -> list[Page]: ...


class WebsiteFetcher(Protocol):
    """Fetch one public URL without exposing a provider response to core logic."""

    def fetch(self, url: str) -> "FetchedDocument": ...


@dataclass(frozen=True)
class FetchedDocument:
    requested_url: str
    final_url: str
    status_code: int
    headers: dict[str, str]
    body: bytes


class EnrichmentProvider(Protocol):
    """Normalize firmographic, technology, hiring, news, and trigger observations."""

    def enrich_account(self, domain: str) -> ProviderResult: ...


class AdvertisingProvider(Protocol):
    """Normalize creatives and their observed destination URLs."""

    def find_ads(self, domain: str) -> ProviderResult: ...


class SearchProvider(Protocol):
    """Find indexed campaign, resource, proof, and segment pages."""

    def search_pages(self, domain: str, query: str) -> ProviderResult: ...
