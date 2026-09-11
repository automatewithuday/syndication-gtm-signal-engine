from __future__ import annotations

import hashlib
import heapq
import json
import re
import shutil
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree

from .models import Page
from .providers import FetchedDocument, WebsiteFetcher

TRACKING_PARAMETERS = {
    "fbclid",
    "gclid",
    "li_fat_id",
    "mc_cid",
    "mc_eid",
    "msclkid",
}
IGNORED_EXTENSIONS = {
    ".7z", ".avi", ".css", ".csv", ".doc", ".docx", ".gif", ".gz",
    ".ico", ".jpeg", ".jpg", ".js", ".json", ".mov", ".mp3", ".mp4",
    ".pdf", ".png", ".ppt", ".pptx", ".rar", ".rss", ".svg", ".tar",
    ".tgz", ".txt", ".wav", ".webm", ".webp", ".xls", ".xlsx", ".xml",
    ".zip",
}
MAX_DISCOVERY_BODY_BYTES = 5_000_000


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_seed(domain_or_url: str) -> str:
    value = domain_or_url.strip()
    if not value:
        raise ValueError("domain must not be empty")
    if "://" not in value:
        value = f"https://{value}"
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError(f"unsupported website URL: {domain_or_url!r}")
    return canonicalize_url(value)


def canonicalize_url(url: str, base_url: str | None = None) -> str:
    absolute = urljoin(base_url, url) if base_url else url
    parts = urlsplit(absolute)
    scheme = parts.scheme.lower()
    hostname = (parts.hostname or "").lower()
    if not scheme or not hostname:
        return ""
    port = parts.port
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        hostname = f"{hostname}:{port}"
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_PARAMETERS
    ]
    return urlunsplit((scheme, hostname, path, urlencode(sorted(query)), ""))


def _allowed_hosts(seed_url: str) -> set[str]:
    host = (urlsplit(seed_url).hostname or "").lower()
    apex = host[4:] if host.startswith("www.") else host
    return {apex, f"www.{apex}"}


def _is_crawlable(url: str, allowed_hosts: set[str]) -> bool:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or (parts.hostname or "").lower() not in allowed_hosts:
        return False
    path = parts.path.lower()
    return not any(path.endswith(extension) for extension in IGNORED_EXTENSIONS)


def _crawl_priority(url: str, seed_url: str) -> int:
    if canonicalize_url(url) == canonicalize_url(seed_url):
        return 0
    path = urlsplit(url).path.lower()
    if any(marker in path for marker in ("/blog/", "/news/", "/press/", "/press-center/", "/author/", "/tag/", "/category/")):
        return 80
    priority_markers = (
        (10, ("/case-stud", "/customer-stor", "/success-stor", "/customers/")),
        (20, ("/guide", "/report", "/research", "/whitepaper", "/ebook", "/webinar")),
        (30, ("/industr", "/solution", "/use-case", "/integration", "/persona", "/teams/")),
        (40, ("/demo", "/contact", "/pricing", "/trial", "/get-started")),
        (60, ("/tools/", "/skills/")),
    )
    return next((priority for priority, markers in priority_markers if any(marker in path for marker in markers)), 50)


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.main_text_parts: list[str] = []
        self.links: list[str] = []
        self.link_details: list[dict[str, str]] = []
        self.forms: list[dict[str, Any]] = []
        self.metadata: dict[str, Any] = {}
        self.canonical_href: str | None = None
        self._in_title = False
        self._suppressed_depth = 0
        self._main_depth = 0
        self._current_form: dict[str, Any] | None = None
        self._current_link: dict[str, Any] | None = None
        self._current_time: dict[str, Any] | None = None
        self.date_candidates: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"}:
            self._suppressed_depth += 1
        if tag in {"main", "article"}:
            self._main_depth += 1
        if tag == "title":
            self._in_title = True
        elif tag == "a" and values.get("href"):
            self.links.append(values["href"])
            self._current_link = {"href": values["href"], "text_parts": []}
        elif tag == "link" and "canonical" in values.get("rel", "").lower().split():
            self.canonical_href = values.get("href") or None
        elif tag == "meta":
            key = values.get("property") or values.get("name")
            if key and values.get("content"):
                self.metadata[key.lower()] = values["content"]
        elif tag == "time" and values.get("datetime"):
            self._current_time = {"value": values["datetime"], "source": "html_time_datetime", "text_parts": []}
        elif tag == "form":
            self._current_form = {
                "action": values.get("action", ""),
                "method": values.get("method", "get").lower(),
                "id": values.get("id", ""),
                "name": values.get("name", ""),
                "class": values.get("class", ""),
                "data_name": values.get("data-name", ""),
                "fields": [],
                "field_details": [],
                "submit_text": [],
                "text_parts": [],
            }
        elif tag in {"input", "select", "textarea"} and self._current_form is not None:
            name = values.get("name")
            if name:
                self._current_form["fields"].append(name)
            detail = {
                "name": name or "",
                "type": values.get("type", tag).lower(),
                "placeholder": values.get("placeholder", ""),
            }
            self._current_form["field_details"].append(detail)
            if tag == "input" and values.get("type", "").lower() in {"submit", "button"} and values.get("value"):
                self._current_form["submit_text"].append(values["value"])

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"} and self._suppressed_depth:
            self._suppressed_depth -= 1
        if tag in {"main", "article"} and self._main_depth:
            self._main_depth -= 1
        if tag == "title":
            self._in_title = False
        elif tag == "form" and self._current_form is not None:
            self._current_form["text"] = " ".join(self._current_form.pop("text_parts"))
            self._current_form["submit_text"] = " ".join(self._current_form["submit_text"])
            self.forms.append(self._current_form)
            self._current_form = None
        elif tag == "a" and self._current_link is not None:
            self.link_details.append({
                "href": self._current_link["href"],
                "text": " ".join(self._current_link["text_parts"]),
            })
            self._current_link = None
        elif tag == "time" and self._current_time is not None:
            self.date_candidates.append({
                "value": self._current_time["value"],
                "source": self._current_time["source"],
                "text": " ".join(self._current_time["text_parts"]),
            })
            self._current_time = None

    def handle_data(self, data: str) -> None:
        if self._suppressed_depth:
            return
        cleaned = " ".join(data.split())
        if not cleaned:
            return
        self.text_parts.append(cleaned)
        if self._main_depth:
            self.main_text_parts.append(cleaned)
        if self._current_form is not None:
            self._current_form["text_parts"].append(cleaned)
        if self._current_link is not None:
            self._current_link["text_parts"].append(cleaned)
        if self._current_time is not None:
            self._current_time["text_parts"].append(cleaned)
        if self._in_title:
            self.title_parts.append(cleaned)


def normalize_html(document: FetchedDocument, observed_at: str) -> Page:
    parser = _PageParser()
    encoding = "utf-8"
    content_type = document.headers.get("content-type", "")
    match = re.search(r"charset=([^;\s]+)", content_type, flags=re.IGNORECASE)
    if match:
        encoding = match.group(1).strip('"\'')
    try:
        html = document.body.decode(encoding, errors="replace")
    except LookupError:
        html = document.body.decode("utf-8", errors="replace")
    parser.feed(html)
    final_url = canonicalize_url(document.final_url or document.requested_url)
    declared_canonical = canonicalize_url(parser.canonical_href, final_url) if parser.canonical_href else ""
    canonical = (
        declared_canonical
        if declared_canonical
        and urlsplit(declared_canonical).path == urlsplit(final_url).path
        else final_url
    )
    links = sorted({
        normalized
        for href in parser.links
        if (normalized := canonicalize_url(href, final_url))
    })
    forms = []
    for form in parser.forms:
        normalized_form = dict(form)
        if normalized_form["action"]:
            normalized_form["action"] = canonicalize_url(normalized_form["action"], final_url)
        forms.append(normalized_form)
    link_details = [
        {"href": canonicalize_url(item["href"], final_url), "text": item["text"]}
        for item in parser.link_details
        if canonicalize_url(item["href"], final_url)
    ]
    return Page(
        url=canonical,
        original_url=document.requested_url,
        title=" ".join(parser.title_parts),
        text=" ".join(parser.text_parts),
        main_text=" ".join(parser.main_text_parts),
        date_candidates=parser.date_candidates,
        links=links,
        link_details=link_details,
        forms=forms,
        metadata=parser.metadata,
        content_hash=hashlib.sha256(document.body).hexdigest(),
        observed_at=observed_at,
        status_code=document.status_code,
    )


class ScraplingFetcher:
    """Scrapling-only fetcher with a browser transport for TLS-chain failures."""

    def __init__(self, *, timeout_seconds: float = 30.0, browser_executable: str | None = None) -> None:
        self.timeout_seconds = timeout_seconds
        self.browser_executable = browser_executable or self._find_browser_executable()

    def fetch(self, url: str) -> FetchedDocument:
        try:
            return self._fetch_static(url)
        except Exception as exc:
            if not self._is_certificate_error(exc):
                raise
            return self._fetch_browser(url)

    def _fetch_static(self, url: str) -> FetchedDocument:
        try:
            from scrapling.fetchers import Fetcher
        except ImportError as exc:  # pragma: no cover - exercised by installation state
            raise RuntimeError("Install the scraper with: uv sync --extra scrape") from exc
        response = Fetcher.get(
            url,
            timeout=self.timeout_seconds,
            retries=2,
            retry_delay=1,
            impersonate="chrome",
            stealthy_headers=True,
        )
        return FetchedDocument(
            requested_url=url,
            final_url=str(response.url),
            status_code=int(response.status),
            headers={str(key).lower(): str(value) for key, value in response.headers.items()},
            body=response.body,
        )

    def _fetch_browser(self, url: str) -> FetchedDocument:
        try:
            from scrapling.fetchers import DynamicFetcher
        except ImportError as exc:  # pragma: no cover - exercised by installation state
            raise RuntimeError("Install the scraper with: uv sync --extra scrape") from exc
        kwargs: dict[str, Any] = {
            "headless": True,
            "timeout": self.timeout_seconds * 1_000,
            "disable_resources": True,
            "retries": 2,
            "retry_delay": 1,
        }
        if self.browser_executable:
            kwargs["executable_path"] = self.browser_executable
        response = DynamicFetcher.fetch(url, **kwargs)
        return FetchedDocument(
            requested_url=url,
            final_url=str(response.url),
            status_code=int(response.status),
            headers={str(key).lower(): str(value) for key, value in response.headers.items()},
            body=response.body,
        )

    @staticmethod
    def _is_certificate_error(exc: Exception) -> bool:
        return exc.__class__.__name__ == "CertificateVerifyError" or "certificate verify" in str(exc).lower()

    @staticmethod
    def _find_browser_executable() -> str | None:
        candidates = [
            shutil.which("google-chrome"),
            shutil.which("chromium"),
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        ]
        return next((candidate for candidate in candidates if candidate and Path(candidate).is_file()), None)


@dataclass
class CrawlManifest:
    run_id: str
    seed_url: str
    provider: str
    started_at: str
    finished_at: str | None = None
    status: str = "running"
    incomplete: bool = True
    maximum_pages: int = 0
    pages_collected: int = 0
    requests_attempted: int = 0
    raw_responses: int = 0
    sitemap_urls_discovered: int = 0
    robots_disallowed_count: int = 0
    errors: list[dict[str, str]] = field(default_factory=list)


class LocalArtifactStore:
    def __init__(self, root: Path, run_id: str) -> None:
        self.run_dir = root / run_id
        self.raw_dir = self.run_dir / "raw"
        self.normalized_dir = self.run_dir / "normalized"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.normalized_dir.mkdir(parents=True, exist_ok=True)

    def save_raw(self, document: FetchedDocument) -> str:
        key = hashlib.sha256(document.requested_url.encode("utf-8")).hexdigest()
        body_path = self.raw_dir / f"{key}.body"
        meta_path = self.raw_dir / f"{key}.json"
        body_path.write_bytes(document.body)
        meta_path.write_text(json.dumps({
            "requested_url": document.requested_url,
            "final_url": document.final_url,
            "status_code": document.status_code,
            "headers": document.headers,
            "observed_at": utc_now(),
            "body_file": body_path.name,
            "body_sha256": hashlib.sha256(document.body).hexdigest(),
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return str(meta_path.relative_to(self.run_dir))

    def save_pages(self, pages: Iterable[Page]) -> None:
        path = self.normalized_dir / "pages.jsonl"
        with path.open("w", encoding="utf-8") as handle:
            for page in pages:
                handle.write(json.dumps(asdict(page), sort_keys=True) + "\n")

    def save_discovered_urls(self, urls: Iterable[str], seed_url: str) -> None:
        path = self.normalized_dir / "discovered_urls.jsonl"
        with path.open("w", encoding="utf-8") as handle:
            for url in sorted(set(urls), key=lambda item: (_crawl_priority(item, seed_url), item)):
                handle.write(json.dumps({
                    "url": url,
                    "priority": _crawl_priority(url, seed_url),
                }, sort_keys=True) + "\n")

    def save_manifest(self, manifest: CrawlManifest) -> None:
        (self.run_dir / "manifest.json").write_text(
            json.dumps(asdict(manifest), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _sitemap_locations(body: bytes) -> tuple[list[str], list[str]]:
    if len(body) > MAX_DISCOVERY_BODY_BYTES:
        raise ValueError("sitemap exceeds the discovery size limit")
    root = ElementTree.fromstring(body)
    root_name = root.tag.rsplit("}", 1)[-1].lower()
    locations = [
        (element.text or "").strip()
        for element in root.iter()
        if element.tag.rsplit("}", 1)[-1].lower() == "loc" and (element.text or "").strip()
    ]
    return ([], locations) if root_name == "sitemapindex" else (locations, [])


def _robots_sitemaps(body: bytes) -> list[str]:
    text = body[:MAX_DISCOVERY_BODY_BYTES].decode("utf-8", errors="replace")
    return [line.split(":", 1)[1].strip() for line in text.splitlines() if line.lower().startswith("sitemap:")]


def collect_website(
    domain_or_url: str,
    *,
    output_root: Path,
    maximum_pages: int = 100,
    maximum_sitemaps: int = 20,
    delay_seconds: float = 0.25,
    fetcher: WebsiteFetcher | None = None,
) -> tuple[CrawlManifest, list[Page], Path]:
    if maximum_pages < 1:
        raise ValueError("maximum_pages must be at least 1")
    seed_url = normalize_seed(domain_or_url)
    allowed_hosts = _allowed_hosts(seed_url)
    fetcher = fetcher or ScraplingFetcher()
    run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    store = LocalArtifactStore(output_root, run_id)
    manifest = CrawlManifest(
        run_id=run_id,
        seed_url=seed_url,
        provider=type(fetcher).__name__,
        started_at=utc_now(),
        maximum_pages=maximum_pages,
    )
    store.save_manifest(manifest)

    pages: list[Page] = []
    page_queue: list[tuple[int, int, str]] = []
    queued_page_urls: set[str] = set()
    seen_requests: set[str] = set()
    queue_sequence = 0

    def enqueue_page(url: str) -> bool:
        nonlocal queue_sequence
        if url in queued_page_urls or url in seen_requests:
            return False
        queued_page_urls.add(url)
        heapq.heappush(page_queue, (_crawl_priority(url, seed_url), queue_sequence, url))
        queue_sequence += 1
        return True

    enqueue_page(seed_url)
    sitemap_queue: deque[str] = deque([
        urljoin(seed_url, "/robots.txt"),
        urljoin(seed_url, "/sitemap.xml"),
    ])
    seen_pages: set[tuple[str, str]] = set()
    robots_policy: RobotFileParser | None = None
    robots_delay = 0.0

    def fetch(url: str, purpose: str) -> FetchedDocument | None:
        if url in seen_requests:
            return None
        seen_requests.add(url)
        manifest.requests_attempted += 1
        try:
            document = fetcher.fetch(url)
            store.save_raw(document)
            manifest.raw_responses += 1
            if document.status_code >= 400:
                manifest.errors.append({"url": url, "purpose": purpose, "error": f"HTTP {document.status_code}"})
                return None
            final_host = (urlsplit(document.final_url).hostname or "").lower()
            if purpose == "page" and final_host not in allowed_hosts:
                manifest.errors.append({
                    "url": url,
                    "purpose": purpose,
                    "error": f"redirected outside allowed hosts to {document.final_url}",
                })
                return None
            if delay_seconds:
                time.sleep(delay_seconds)
            return document
        except Exception as exc:  # provider boundary: preserve failure as incomplete
            manifest.errors.append({"url": url, "purpose": purpose, "error": f"{type(exc).__name__}: {exc}"})
            return None

    sitemaps_processed = 0
    while sitemap_queue and sitemaps_processed < maximum_sitemaps:
        sitemap_url = canonicalize_url(sitemap_queue.popleft())
        document = fetch(sitemap_url, "discovery")
        if document is None:
            continue
        try:
            if urlsplit(sitemap_url).path.endswith("robots.txt"):
                robots_policy = RobotFileParser()
                robots_policy.set_url(sitemap_url)
                robots_policy.parse(document.body.decode("utf-8", errors="replace").splitlines())
                declared_delay = robots_policy.crawl_delay("*")
                if declared_delay is not None:
                    robots_delay = max(0.0, float(declared_delay))
                child_sitemaps = _robots_sitemaps(document.body)
                page_urls: list[str] = []
            else:
                page_urls, child_sitemaps = _sitemap_locations(document.body)
                sitemaps_processed += 1
            for child in child_sitemaps:
                normalized = canonicalize_url(child, sitemap_url)
                if normalized and _is_crawlable(normalized, allowed_hosts) is False and urlsplit(normalized).path.endswith(".xml"):
                    if (urlsplit(normalized).hostname or "").lower() in allowed_hosts:
                        sitemap_queue.append(normalized)
                elif normalized and (urlsplit(normalized).hostname or "").lower() in allowed_hosts:
                    sitemap_queue.append(normalized)
            for page_url in page_urls:
                normalized = canonicalize_url(page_url, sitemap_url)
                if normalized and _is_crawlable(normalized, allowed_hosts):
                    if enqueue_page(normalized):
                        manifest.sitemap_urls_discovered += 1
        except (ElementTree.ParseError, ValueError) as exc:
            manifest.errors.append({"url": sitemap_url, "purpose": "discovery", "error": f"{type(exc).__name__}: {exc}"})

    while page_queue and len(pages) < maximum_pages:
        _, _, queued_url = heapq.heappop(page_queue)
        requested_url = canonicalize_url(queued_url)
        if not requested_url or not _is_crawlable(requested_url, allowed_hosts):
            continue
        if robots_policy is not None and not robots_policy.can_fetch("*", requested_url):
            manifest.robots_disallowed_count += 1
            continue
        document = fetch(requested_url, "page")
        if document is None:
            continue
        content_type = document.headers.get("content-type", "").lower()
        if "html" not in content_type and not document.body.lstrip().lower().startswith((b"<!doctype html", b"<html")):
            continue
        observed_at = utc_now()
        page = normalize_html(document, observed_at)
        identity = (page.url, page.content_hash or "")
        if identity in seen_pages:
            continue
        seen_pages.add(identity)
        pages.append(page)
        for link in page.links:
            if _is_crawlable(link, allowed_hosts):
                enqueue_page(link)
        if robots_delay > delay_seconds:
            time.sleep(robots_delay - delay_seconds)

    manifest.pages_collected = len(pages)
    manifest.finished_at = utc_now()
    if not pages:
        manifest.status = "failed"
        manifest.incomplete = True
    elif manifest.errors or page_queue or sitemap_queue:
        manifest.status = "partial"
        manifest.incomplete = True
    else:
        manifest.status = "completed"
        manifest.incomplete = False
    store.save_discovered_urls(queued_page_urls, seed_url)
    store.save_pages(pages)
    store.save_manifest(manifest)
    return manifest, pages, store.run_dir


def repair_cross_path_canonicals(run_dir: Path) -> dict[str, Any]:
    """Repair pages normalized by older code that trusted cross-path canonicals.

    The immutable raw Scrapling metadata records the actual final URL. A repair
    is made only when that final URL's path differs from the saved normalized
    path, which preserves legitimate redirects.
    """
    manifest_path = run_dir / "manifest.json"
    pages_path = run_dir / "normalized" / "pages.jsonl"
    if not manifest_path.is_file() or not pages_path.is_file():
        raise ValueError("run must contain manifest.json and normalized/pages.jsonl")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("provider") != "ScraplingFetcher":
        raise ValueError("canonical repair requires a saved ScraplingFetcher run")

    pages = [json.loads(line) for line in pages_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    repaired: list[dict[str, str]] = []
    for page in pages:
        original_url = page.get("original_url")
        if not original_url:
            continue
        raw_key = hashlib.sha256(original_url.encode("utf-8")).hexdigest()
        raw_meta_path = run_dir / "raw" / f"{raw_key}.json"
        if not raw_meta_path.is_file():
            continue
        raw_meta = json.loads(raw_meta_path.read_text(encoding="utf-8"))
        final_url = canonicalize_url(raw_meta.get("final_url") or original_url)
        saved_url = canonicalize_url(page.get("url", ""))
        if not final_url or not saved_url:
            continue
        if urlsplit(final_url).path == urlsplit(saved_url).path:
            continue
        page["url"] = final_url
        repaired.append({"original_url": original_url, "from": saved_url, "to": final_url})

    if repaired:
        rendered = "".join(json.dumps(page, sort_keys=True) + "\n" for page in pages)
        temporary_path = pages_path.with_suffix(".jsonl.tmp")
        temporary_path.write_text(rendered, encoding="utf-8")
        temporary_path.replace(pages_path)

    repair_record = {
        "version": "cross_path_canonical_repair_v1",
        "repaired_at": utc_now(),
        "pages_repaired": len(repaired),
        "repairs": repaired,
    }
    manifest.setdefault("normalization_repairs", []).append(repair_record)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return repair_record
