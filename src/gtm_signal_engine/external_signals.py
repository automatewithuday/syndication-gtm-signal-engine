from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from .collector import TRACKING_PARAMETERS, canonicalize_url
from .providers import ProviderResult

EXTERNAL_NORMALIZER_VERSION = "external_signals_v1"


@dataclass(frozen=True)
class CampaignUrl:
    observed_url: str
    canonical_url: str
    utm_parameters: dict[str, str]
    click_identifiers: dict[str, str]


@dataclass(frozen=True)
class AdObservation:
    platform: str
    provider_record_id: str
    creative_text: str
    destination: CampaignUrl
    source_url: str
    observed_at: str
    first_seen_at: str | None
    last_seen_at: str | None
    confidence: float
    method: str
    normalizer_version: str = EXTERNAL_NORMALIZER_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TechnologyObservation:
    technology: str
    category: str
    state: str
    source_url: str
    excerpt: str
    observed_at: str
    confidence: float
    method: str
    limitations: list[str]
    first_seen_at: str | None = None
    last_seen_at: str | None = None
    normalizer_version: str = EXTERNAL_NORMALIZER_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SearchResultObservation:
    query: str
    position: int
    title: str
    result_url: str
    canonical_url: str
    excerpt: str
    source_url: str
    observed_at: str
    method: str = "scrapling_saved_serp"
    normalizer_version: str = EXTERNAL_NORMALIZER_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_campaign_url(url: str) -> CampaignUrl:
    canonical = canonicalize_url(url)
    if not canonical:
        raise ValueError("campaign destination must be an absolute HTTP(S) URL")
    query = parse_qsl(urlsplit(url).query, keep_blank_values=True)
    utm = {key.lower(): value for key, value in query if key.lower().startswith("utm_")}
    click = {key.lower(): value for key, value in query if key.lower() in TRACKING_PARAMETERS}
    return CampaignUrl(
        observed_url=url,
        canonical_url=canonical,
        utm_parameters=dict(sorted(utm.items())),
        click_identifiers=dict(sorted(click.items())),
    )


def normalize_apify_ads(payload: list[dict[str, Any]], *, observed_at: str) -> list[AdObservation]:
    """Normalize recorded actor results without exposing actor fields downstream."""
    observations: list[AdObservation] = []
    for index, record in enumerate(payload):
        destination_url = record.get("destination_url") or record.get("landing_page_url")
        source_url = record.get("source_url") or record.get("ad_library_url")
        platform = str(record.get("platform", "")).lower()
        record_id = str(record.get("id") or record.get("ad_archive_id") or "")
        if not destination_url or not source_url or not platform or not record_id:
            raise ValueError(f"ad record {index} lacks platform, ID, destination, or source URL")
        observations.append(AdObservation(
            platform=platform,
            provider_record_id=record_id,
            creative_text=str(record.get("creative_text") or record.get("ad_text") or record.get("body") or ""),
            destination=parse_campaign_url(str(destination_url)),
            source_url=str(source_url),
            observed_at=observed_at,
            first_seen_at=record.get("first_seen_at") or record.get("start_date"),
            last_seen_at=record.get("last_seen_at") or record.get("end_date"),
            confidence=float(record.get("confidence", 0.9)),
            method="apify_recorded_payload",
        ))
    return observations


def normalize_deepline_technologies(
    payload: dict[str, Any], *, observed_at: str, method: str = "deepline_recorded_payload"
) -> list[TechnologyObservation]:
    """Normalize recorded technology detections with explicit limitations."""
    records = payload.get("technologies", [])
    observations: list[TechnologyObservation] = []
    for index, record in enumerate(records):
        source_url = record.get("source_url")
        technology = record.get("name") or record.get("technology")
        if not source_url or not technology:
            raise ValueError(f"technology record {index} lacks name or source URL")
        observations.append(TechnologyObservation(
            technology=str(technology),
            category=str(record.get("category", "unknown")),
            state=str(record.get("state", "detected")),
            source_url=str(source_url),
            excerpt=str(record.get("evidence") or record.get("excerpt") or ""),
            observed_at=observed_at,
            confidence=float(record.get("confidence", 0.7)),
            method=method,
            limitations=list(record.get("limitations") or [
                "technology detection shows observable implementation evidence, not complete deployment or active use"
            ]),
        ))
    return observations


def normalize_scrapling_serp_results(
    payload: list[dict[str, Any]], *, query: str, source_url: str, observed_at: str
) -> list[SearchResultObservation]:
    """Normalize results extracted from a saved Scrapling SERP page."""
    results: list[SearchResultObservation] = []
    for index, record in enumerate(payload):
        result_url = str(record.get("url", ""))
        canonical = canonicalize_url(result_url)
        if not canonical:
            raise ValueError(f"search result {index} requires an absolute HTTP(S) URL")
        results.append(SearchResultObservation(
            query=query,
            position=int(record.get("position", index + 1)),
            title=str(record.get("title", "")),
            result_url=result_url,
            canonical_url=canonical,
            excerpt=str(record.get("excerpt", "")),
            source_url=source_url,
            observed_at=observed_at,
        ))
    return results


class RecordedApifyAdvertisingAdapter:
    """Fixture/replay adapter implementing the provider-neutral ad protocol."""

    def __init__(self, payload: list[dict[str, Any]], *, observed_at: str, raw_payload_location: str) -> None:
        self.payload = payload
        self.observed_at = observed_at
        self.raw_payload_location = raw_payload_location

    def find_ads(self, domain: str) -> ProviderResult:
        records = [item.to_dict() for item in normalize_apify_ads(self.payload, observed_at=self.observed_at)]
        domain = domain.lower().removeprefix("www.")
        selected = [
            item for item in records
            if (urlsplit(item["destination"]["canonical_url"]).hostname or "").lower().removeprefix("www.") == domain
        ]
        return ProviderResult(
            provider="apify_recorded",
            query=domain,
            records=selected,
            raw_payload_location=self.raw_payload_location,
        )


class RecordedDeeplineEnrichmentAdapter:
    """Fixture/replay adapter implementing the provider-neutral enrichment protocol."""

    def __init__(self, payload: dict[str, Any], *, observed_at: str, raw_payload_location: str) -> None:
        self.payload = payload
        self.observed_at = observed_at
        self.raw_payload_location = raw_payload_location

    def enrich_account(self, domain: str) -> ProviderResult:
        records = [
            item.to_dict()
            for item in normalize_deepline_technologies(self.payload, observed_at=self.observed_at)
        ]
        return ProviderResult(
            provider="deepline_recorded",
            query=domain.lower().removeprefix("www."),
            records=records,
            raw_payload_location=self.raw_payload_location,
        )


class RecordedScraplingSearchAdapter:
    """Fixture/replay adapter for results extracted from a saved Scrapling SERP."""

    def __init__(
        self, payload: list[dict[str, Any]], *, source_url: str, observed_at: str,
        raw_payload_location: str,
    ) -> None:
        self.payload = payload
        self.source_url = source_url
        self.observed_at = observed_at
        self.raw_payload_location = raw_payload_location

    def search_pages(self, domain: str, query: str) -> ProviderResult:
        records = [
            item.to_dict() for item in normalize_scrapling_serp_results(
                self.payload, query=query, source_url=self.source_url, observed_at=self.observed_at
            )
        ]
        domain = domain.lower().removeprefix("www.")
        selected = [
            item for item in records
            if (urlsplit(item["canonical_url"]).hostname or "").lower().removeprefix("www.") == domain
        ]
        return ProviderResult(
            provider="scrapling_serp_recorded",
            query=query,
            records=selected,
            raw_payload_location=self.raw_payload_location,
        )
