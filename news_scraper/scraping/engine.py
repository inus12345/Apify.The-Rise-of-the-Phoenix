"""Config-driven scraping engine with backend fallback and JSON outputs."""

from __future__ import annotations

import json
import logging
import os
import time
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from lxml import html as lxml_html
from zoneinfo import ZoneInfo

from news_scraper.config import (
    CategoryPaginationTracker,
    CategoryState,
    ErrorDatasetItem,
    ExecutionMode,
    InputConfig,
    ProxyConfig,
    RunDatasets,
    ScrapingHistoryEntry,
    ScrapingTool,
    SelectorMap,
    SelectorStrategy,
    SelectorType,
    SiteCatalog,
    SiteCatalogEntry,
    SiteCategoryTracker,
    SiteSelectorConfig,
    SiteVerificationResult,
    SuccessDatasetItem,
    VerificationReport,
    ensure_utc,
    load_json_model,
    md5_url,
    normalize_url,
    save_json_data,
    save_json_model,
    utc_now,
)


LOGGER = logging.getLogger("news_scraper")
ProgressCallback = Callable[[dict[str, Any]], None]

if not LOGGER.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.FileHandler("news_scraper/scraping.log"),
            logging.StreamHandler(),
        ],
    )


class ScraperError(Exception):
    """Base exception for scraper failures."""


class FetchError(ScraperError):
    """Raised when a page cannot be fetched or is blocked."""

    def __init__(self, message: str, attempts: list["FetchAttempt"] | None = None) -> None:
        super().__init__(message)
        self.attempts = attempts or []


class ExtractionError(ScraperError):
    """Raised when selector-based extraction fails."""


@dataclass(slots=True)
class FetchAttempt:
    """Telemetry for one tool attempt."""

    tool: ScrapingTool
    success: bool
    elapsed_ms: int
    error_type: str | None = None
    message: str | None = None
    block_detected: bool = False


@dataclass(slots=True)
class FetchResult:
    """Successful fetch plus preceding attempts."""

    url: str
    html: str
    tool: ScrapingTool
    elapsed_ms: int
    attempts: list[FetchAttempt] = field(default_factory=list)


@dataclass(slots=True)
class RuntimeConfig:
    """Resolved filesystem configuration for a run."""

    catalog_path: Path
    selectors_path: Path
    tracker_path: Path
    output_dir: Path


class BackendFetcher:
    """Base backend wrapper."""

    tool: ScrapingTool

    def __init__(self, timeout: int) -> None:
        self.timeout = timeout

    def fetch(self, url: str, proxy_url: str | None = None) -> str | None:
        raise NotImplementedError

    @property
    def headers(self) -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }


class ScraplingFetcher(BackendFetcher):
    """Primary scraping backend."""

    tool = ScrapingTool.SCRAPLING

    def fetch(self, url: str, proxy_url: str | None = None) -> str | None:
        force_httpx = os.getenv("NEWS_SCRAPER_FORCE_HTTPX_FETCH", "").strip().lower() in {"1", "true", "yes"}
        if force_httpx:
            return self._httpx_fetch(url, proxy_url)
        try:
            import scrapling
        except Exception:
            return self._httpx_fetch(url, proxy_url)

        try:
            fetcher = scrapling.Fetcher()
            response = fetcher.get(url, headers=self.headers, timeout=self.timeout)
            html = coerce_html(response)
            if html:
                return html
        except Exception:
            # Some scrapling versions rely on optional runtime deps that may be
            # absent in restricted environments; fall back to plain HTTP fetch.
            return self._httpx_fetch(url, proxy_url)
        return self._httpx_fetch(url, proxy_url)

    def _httpx_fetch(self, url: str, proxy_url: str | None) -> str | None:
        kwargs: dict[str, Any] = {
            "headers": self.headers,
            "timeout": self.timeout,
            "follow_redirects": True,
        }
        if proxy_url:
            kwargs["proxy"] = proxy_url
        with httpx.Client(**kwargs) as client:
            response = client.get(url)
            response.raise_for_status()
            return response.text


class PydollFetcher(BackendFetcher):
    """Secondary scraping backend."""

    tool = ScrapingTool.PYDOLL

    def fetch(self, url: str, proxy_url: str | None = None) -> str | None:
        try:
            import pydoll
        except Exception:
            return None

        browser_cls = getattr(pydoll, "Browser", None)
        if browser_cls is None:
            return None

        browser = None
        try:
            browser_kwargs: dict[str, Any] = {"headless": True}
            if proxy_url:
                browser_kwargs["proxy"] = proxy_url
            browser = browser_cls(**browser_kwargs)
            page = browser.new_page()
            page.goto(url, timeout=self.timeout * 1000)
            page.wait_for_load_state("networkidle")
            return page.content()
        except Exception:
            return None
        finally:
            if browser and hasattr(browser, "close"):
                browser.close()


class SeleniumFetcher(BackendFetcher):
    """Last-resort browser backend."""

    tool = ScrapingTool.SELENIUM

    def fetch(self, url: str, proxy_url: str | None = None) -> str | None:
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
        except ImportError:
            return None

        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        if proxy_url:
            options.add_argument(f"--proxy-server={proxy_url}")

        driver = webdriver.Chrome(options=options)
        driver.set_page_load_timeout(self.timeout)
        try:
            driver.get(url)
            wait_seconds = max(5, min(self.timeout, 20))
            try:
                WebDriverWait(driver, wait_seconds).until(
                    lambda current: current.execute_script("return document.readyState") == "complete"
                )
            except Exception:
                pass

            # Allow JS-driven listing cards to hydrate before reading page_source.
            selectors = ("a[href*='/news/']", "article a[href]", "main a[href]")
            for selector in selectors:
                try:
                    WebDriverWait(driver, 4).until(
                        lambda current, sel=selector: len(current.find_elements(By.CSS_SELECTOR, sel)) >= 5
                    )
                    break
                except Exception:
                    continue
            time.sleep(0.8)
            return driver.page_source
        finally:
            driver.quit()


def coerce_html(response: Any) -> str | None:
    """Extract HTML content from different response object shapes."""

    if response is None:
        return None
    if isinstance(response, str):
        return response
    if isinstance(response, (bytes, bytearray)):
        return response.decode("utf-8", errors="ignore")

    for attribute in ("text", "content", "body", "html"):
        if not hasattr(response, attribute):
            continue
        value = getattr(response, attribute)
        if callable(value):
            value = value()
        if value is None:
            continue
        if isinstance(value, str):
            return value
        if isinstance(value, (bytes, bytearray)):
            return value.decode("utf-8", errors="ignore")
    return None


class ArticleExtractor:
    """Selector-aware article extraction utilities."""

    def extract_listing_links(self, html: str, base_url: str, selectors: list[SelectorStrategy]) -> list[str]:
        """Extract article URLs from a listing page."""

        links: list[str] = []
        soup = BeautifulSoup(html, "lxml")
        document = lxml_html.fromstring(html)
        base_parts = urlsplit(base_url)
        base_host = base_parts.netloc.lower().removeprefix("www.")

        for selector in selectors:
            raw_values = self._run_selector(selector, soup, document)
            for raw_value in raw_values:
                if not raw_value:
                    continue
                resolved = urljoin(base_url, raw_value)
                if (
                    resolved.startswith("http")
                    and self._is_same_domain(resolved, base_host)
                    and self._is_valid_listing_candidate(resolved)
                ):
                    links.append(normalize_url(resolved))

        seen: set[str] = set()
        deduped: list[str] = []
        for link in links:
            if link in seen:
                continue
            seen.add(link)
            deduped.append(link)

        if not deduped:
            deduped = self._extract_fallback_listing_links(soup, html, base_url, base_host)
        return self._prioritize_article_links(deduped)

    def _extract_fallback_listing_links(
        self,
        soup: BeautifulSoup,
        html: str,
        base_url: str,
        base_host: str,
    ) -> list[str]:
        fallback_selectors = [
            "main a[href]",
            "article a[href]",
            "h1 a[href], h2 a[href], h3 a[href]",
            "[class*='title'] a[href], [class*='headline'] a[href]",
            "a[href*='/article/'], a[href*='/news/'], a[href*='/story/'], a[href*='/202']",
        ]
        links: list[str] = []
        for selector in fallback_selectors:
            for anchor in soup.select(selector):
                href = anchor.get("href")
                if not href:
                    continue
                resolved = urljoin(base_url, href)
                if (
                    resolved.startswith("http")
                    and self._is_same_domain(resolved, base_host)
                    and self._is_valid_listing_candidate(resolved)
                ):
                    links.append(normalize_url(resolved))

        if not links:
            for anchor in soup.select("a[href]"):
                href = anchor.get("href")
                if not href:
                    continue
                resolved = urljoin(base_url, href)
                if (
                    resolved.startswith("http")
                    and self._is_same_domain(resolved, base_host)
                    and self._is_valid_listing_candidate(resolved)
                ):
                    links.append(normalize_url(resolved))

        if not links:
            links.extend(self._extract_links_from_embedded_state(html, base_url, base_host))

        seen: set[str] = set()
        deduped: list[str] = []
        for link in links:
            if link in seen:
                continue
            seen.add(link)
            deduped.append(link)
        return deduped

    def _extract_links_from_embedded_state(self, html: str, base_url: str, base_host: str) -> list[str]:
        """Extract same-domain links from script/state blobs when anchors are missing."""

        normalized_html = html.replace("\\/", "/")
        absolute_candidates = re.findall(
            r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]{8,}",
            normalized_html,
        )
        relative_candidates = re.findall(
            r"/[A-Za-z0-9._~%-]+(?:/[A-Za-z0-9._~%-]+)+",
            normalized_html,
        )
        candidates = absolute_candidates + relative_candidates
        links: list[str] = []

        for candidate in candidates:
            if not candidate:
                continue
            candidate = candidate.rstrip(").,;:'\"")
            candidate_lower = candidate.lower()
            if candidate_lower.startswith("www.") or candidate_lower.startswith("/www."):
                continue
            if len(candidate) > 240:
                continue
            resolved = urljoin(base_url, candidate)
            if not resolved.startswith("http"):
                continue
            if not self._is_same_domain(resolved, base_host):
                continue
            if not self._is_valid_listing_candidate(resolved):
                continue
            score, blocked = self._score_article_url(resolved)
            if blocked or score <= 0:
                continue
            links.append(normalize_url(resolved))
        return links

    def _is_valid_listing_candidate(self, url: str) -> bool:
        parsed = urlsplit(url)
        path = parsed.path or "/"
        lowered = f"{path}?{parsed.query}".lower()
        segments = [segment for segment in path.split("/") if segment]

        if len(path) > 240:
            return False

        if any(token in lowered for token in ("\\u003c", "\\u003e", "</", "<strong", "if(", "this.canvasctx")):
            return False

        if re.search(r"[{}<>;|]", path):
            return False

        if any(re.fullmatch(r"(?:www\.)?[a-z0-9-]+\.[a-z]{2,}", segment.lower()) for segment in segments):
            return False

        lowered_path = path.lower()
        blocked_slug_tokens = {
            "title",
            "style",
            "script",
            "const",
            "button",
            "audio",
            "template",
            "head",
            "body",
            "html",
            "math",
            "span",
            "div",
        }
        segments = [segment for segment in lowered_path.split("/") if segment]
        if segments and all(segment in blocked_slug_tokens for segment in segments):
            return False

        return True

    def _is_same_domain(self, candidate_url: str, base_host: str) -> bool:
        candidate_host = urlsplit(candidate_url).netloc.lower().removeprefix("www.")
        return candidate_host == base_host or candidate_host.endswith(f".{base_host}")

    def extract_article(self, html: str, url: str, site_selectors: SiteSelectorConfig) -> dict[str, Any]:
        """Extract normalized article fields from an article page."""

        soup = BeautifulSoup(html, "lxml")
        document = lxml_html.fromstring(html)

        fields = site_selectors.fields
        extracted: dict[str, Any] = {}
        extracted["article_title"] = self._extract_field(fields.article_title, soup, document)
        extracted["author"] = self._extract_field(fields.author, soup, document)
        extracted["article_body"] = self._extract_field(fields.article_body, soup, document)
        extracted["tags"] = self._extract_field(fields.tags, soup, document)
        extracted["date_published"] = self._extract_date(fields.date_published, soup, document)
        extracted["article_url"] = self._extract_url(
            fields.article_url,
            soup,
            document,
            base_url=url,
        ) or url
        extracted["url_hash"] = md5_url(extracted["article_url"])
        extracted["main_image_url"] = self._extract_url(fields.main_image_url, soup, document, base_url=url)
        extracted["seo_description"] = self._extract_field(fields.seo_description, soup, document)
        extracted["source_html_lang"] = soup.html.get("lang") if soup.html else None
        self._apply_extraction_fallbacks(extracted, soup, url)
        self._validate_required_fields(extracted, fields)
        return extracted

    def _apply_extraction_fallbacks(self, extracted: dict[str, Any], soup: BeautifulSoup, url: str) -> None:
        if not extracted.get("article_title"):
            fallback_title = self._fallback_title(soup)
            if fallback_title:
                extracted["article_title"] = fallback_title

        if not extracted.get("article_body"):
            fallback_body = self._fallback_body(soup)
            if fallback_body:
                extracted["article_body"] = fallback_body

        if not extracted.get("date_published"):
            fallback_date = self._fallback_date(soup, url)
            if fallback_date:
                extracted["date_published"] = fallback_date

    def _validate_required_fields(self, extracted: dict[str, Any], fields: Any) -> None:
        required_fields = {
            "article_title": fields.article_title.required,
            "article_body": fields.article_body.required,
            "date_published": fields.date_published.required,
            "article_url": fields.article_url.required,
            "main_image_url": fields.main_image_url.required,
            "seo_description": fields.seo_description.required,
        }
        missing = [field for field, required in required_fields.items() if required and not extracted.get(field)]
        if missing:
            raise ExtractionError(f"Required selectors returned no data: {', '.join(missing)}")

    def _extract_field(self, field_rule: Any, soup: BeautifulSoup, document: Any) -> Any:
        values: list[Any] = []
        for selector in field_rule.selectors:
            values.extend(self._run_selector(selector, soup, document))
            if values:
                break

        if not values:
            return field_rule.default

        processed = [self._apply_postprocess(value, field_rule.postprocess) for value in values]
        cleaned = [value for value in processed if value not in (None, "", [])]
        if not cleaned:
            return field_rule.default
        deduped: list[Any] = []
        seen: set[str] = set()
        for item in cleaned:
            key = json.dumps(item, sort_keys=True) if not isinstance(item, str) else item
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        if len(deduped) == 1:
            return deduped[0]
        if "dedupe_list" in field_rule.postprocess:
            cleaned = deduped
        return cleaned

    def _extract_date(self, date_rule: Any, soup: BeautifulSoup, document: Any) -> datetime | None:
        raw_value = self._extract_field(date_rule, soup, document)
        if raw_value in (None, ""):
            return None

        candidates = raw_value if isinstance(raw_value, list) else [raw_value]
        first_candidate = candidates[0]

        for candidate in candidates:
            candidate_text = str(candidate)
            for fmt in date_rule.input_formats:
                try:
                    parsed = datetime.strptime(candidate_text, fmt)
                    return self._apply_timezone(parsed, date_rule.timezone)
                except ValueError:
                    continue

            parsed = self._parse_date(candidate_text)
            if parsed is not None:
                return self._apply_timezone(parsed, date_rule.timezone)

        raise ExtractionError(f"Unable to parse date value '{first_candidate}'")

    def _fallback_title(self, soup: BeautifulSoup) -> str | None:
        h1 = soup.select_one("h1")
        if h1:
            text = " ".join(h1.get_text(" ", strip=True).split())
            if text:
                return text

        if soup.title:
            text = " ".join(soup.title.get_text(" ", strip=True).split())
            if text:
                return text
        return None

    def _fallback_body(self, soup: BeautifulSoup) -> str | None:
        containers = [
            soup.select_one("[itemprop='articleBody']"),
            soup.select_one("article"),
            soup.select_one("[class*='story-content'], [class*='story_content']"),
            soup.select_one("[class*='article-content'], [class*='article_content']"),
            soup.select_one("[class*='content']"),
            soup.select_one("main"),
            soup.select_one(".post-content"),
            soup.select_one(".entry-content"),
            soup.select_one(".article-content"),
            soup.select_one(".article-body"),
        ]
        for container in containers:
            if not container:
                continue
            paragraphs = [
                " ".join(p.get_text(" ", strip=True).split())
                for p in container.select("p")
            ]
            paragraphs = [p for p in paragraphs if len(p) >= 40]
            if paragraphs:
                return "\n\n".join(paragraphs)

            # Some templates render rich text in generic divs/spans instead of <p>.
            lines = [
                " ".join(line.split())
                for line in container.get_text("\n", strip=True).splitlines()
            ]
            lines = [line for line in lines if len(line) >= 40]
            if len(lines) >= 2:
                return "\n\n".join(lines[:40])

        # Final safety net for layouts where article text lives in generic wrappers.
        paragraphs = [
            " ".join(p.get_text(" ", strip=True).split())
            for p in soup.select("p")
        ]
        paragraphs = [p for p in paragraphs if len(p) >= 40]
        if len(paragraphs) >= 3:
            return "\n\n".join(paragraphs[:40])
        return None

    def _fallback_date(self, soup: BeautifulSoup, url: str) -> datetime | None:
        for tag in soup.select("meta[content]"):
            name = (
                (tag.get("name") or "")
                + " "
                + (tag.get("property") or "")
                + " "
                + (tag.get("itemprop") or "")
            ).lower()
            if "date" not in name and "publish" not in name and "time" not in name:
                continue
            content = (tag.get("content") or "").strip()
            if not content:
                continue
            parsed = self._parse_date(content)
            if parsed:
                return self._apply_timezone(parsed, "UTC")

        for element in soup.select("[datetime]"):
            value = (element.get("datetime") or "").strip()
            if not value:
                continue
            parsed = self._parse_date(value)
            if parsed:
                return self._apply_timezone(parsed, "UTC")

        # Many themes expose publication date in plain text without datetime/meta fields.
        text_sources: list[str] = []
        for selector in (
            "article",
            "main",
            "header",
            "[class*='post-info']",
            "[class*='meta']",
            "[class*='date']",
            "time",
        ):
            for node in soup.select(selector):
                text = " ".join(node.get_text(" ", strip=True).split())
                if text:
                    text_sources.append(text)

        text_sources.append(" ".join(soup.get_text(" ", strip=True).split()))
        for source in text_sources:
            parsed_from_text = self._parse_date_from_text(source)
            if parsed_from_text:
                return self._apply_timezone(parsed_from_text, "UTC")

        for script in soup.find_all("script"):
            content = (script.string or script.get_text() or "").strip()
            if "datePublished" not in content:
                continue
            matches = re.findall(r'"datePublished"\s*:\s*"([^"]+)"', content)
            for value in matches:
                parsed = self._parse_date(value)
                if parsed:
                    return self._apply_timezone(parsed, "UTC")

        return self._extract_date_from_url(url)

    def _parse_date_from_text(self, text: str) -> datetime | None:
        date_patterns = [
            r"\b\d{2}/\d{2}/\d{4}(?:\s*[-–]\s*\d{1,2}:\d{2})?\b",
            r"\b\d{4}-\d{2}-\d{2}(?:[T\s]\d{1,2}:\d{2}(?::\d{2})?)?\b",
            r"\b(?:january|february|march|april|may|june|july|august|"
            r"september|october|november|december)\s+\d{1,2},\s+\d{4}\b",
            r"\b\d{1,2}\s+(?:january|february|march|april|may|june|july|"
            r"august|september|october|november|december)\s+\d{4}\b",
        ]
        lower_text = text.lower()
        for pattern in date_patterns:
            for match in re.findall(pattern, lower_text, flags=re.IGNORECASE):
                candidate = match.strip()
                parsed = self._parse_date(candidate)
                if parsed:
                    return parsed
        return None

    def _extract_date_from_url(self, url: str) -> datetime | None:
        path = urlsplit(url).path
        patterns = [
            r"/(?P<year>\d{4})/(?P<month>\d{1,2})/(?P<day>\d{1,2})(?:/|$)",
            r"/(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})(?:/|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, path)
            if not match:
                continue
            year = int(match.group("year"))
            month = int(match.group("month"))
            day = int(match.group("day"))
            try:
                return datetime(year, month, day, tzinfo=UTC)
            except ValueError:
                continue
        return None

    def _prioritize_article_links(self, links: list[str]) -> list[str]:
        if not links:
            return links

        ranked: list[tuple[int, int, str]] = []
        for index, link in enumerate(links):
            score, blocked = self._score_article_url(link)
            if blocked:
                continue
            ranked.append((score, index, link))

        if not ranked:
            return []

        ranked.sort(key=lambda item: (-item[0], item[1]))
        positives = [link for score, _, link in ranked if score > 0]
        if positives:
            return positives
        return [link for _, _, link in ranked]

    def _score_article_url(self, url: str) -> tuple[int, bool]:
        parts = urlsplit(url)
        path = (parts.path or "/").lower()
        host = parts.netloc.lower().removeprefix("www.")
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        segments = [segment for segment in path.split("/") if segment]

        if any(token in path for token in ("\\u003c", "\\u003e", "</", "if(", "this.canvasctx")):
            return (-10, True)

        if re.search(r"[{}<>;|]", path):
            return (-10, True)

        if segments and re.fullmatch(r"(?:www\.)?[a-z0-9-]+\.[a-z]{2,}", segments[0]):
            return (-10, True)

        if re.search(r"\.(pdf|jpe?g|png|gif|webp|svg|zip|mp4|mp3|docx?|xlsx?|pptx?)($|[?#])", path):
            return (-10, True)

        if host == "20.detik.com" or host == "x.detik.com":
            return (-10, True)

        # Strongly exclude non-article utility and profile routes.
        blocked_markers = [
            "/author/",
            "/authors/",
            "/writer",
            "/writers",
            "/editor",
            "/editors",
            "/tag/",
            "/tags/",
            "/category/",
            "/categories/",
            "/section/index/",
            "/search",
            "/contact",
            "/about",
            "/privacy",
            "/terms",
            "/account",
            "/login",
            "/wp-login",
            "/register",
            "/subscribe",
            "/newsletter",
            "/videos/",
            "/video/",
            "/x/detail/",
        ]
        if any(marker in path for marker in blocked_markers):
            return (-10, True)

        if re.search(r"/news/\d{4}/\d{1,2}/\d{1,2}/?$", path):
            return (-8, True)

        category_like_tokens = {
            "news",
            "local",
            "international",
            "business",
            "sports",
            "entertainment",
            "world",
            "politics",
            "health",
            "tech",
            "technology",
            "lifestyle",
            "opinion",
        }
        if len(segments) <= 2 and segments and all(segment in category_like_tokens for segment in segments):
            return (-9, True)

        score = 0
        if re.search(r"/\d{4}/\d{1,2}/\d{1,2}(?:/|$)", path):
            score += 6
        if re.search(r"/\d{4}-\d{1,2}-\d{1,2}(?:/|$)", path):
            score += 5
        if re.search(r"/\d{6,}(?:/|$)", path):
            score += 3

        slug = path.rstrip("/").split("/")[-1]
        if slug and len(slug) >= 20 and "-" in slug:
            score += 3
        if re.search(r"-\d{5,}$", slug):
            score += 3
        if re.fullmatch(r"\d{1,2}", slug):
            score -= 4
        if any(token in path for token in ("/article/", "/news/", "/story/", "/details/")):
            score += 2

        # Query-based article identifiers.
        for key in ("id", "storyid", "articleid", "p", "newsid"):
            if key in query and (query[key].isdigit() or len(query[key]) >= 5):
                score += 3
                break

        if path in ("", "/"):
            score -= 5

        return (score, False)

    def _extract_url(self, url_rule: Any, soup: BeautifulSoup, document: Any, base_url: str) -> str | None:
        raw_value = self._extract_field(url_rule, soup, document)
        if not raw_value:
            return None

        if isinstance(raw_value, list):
            raw_value = raw_value[0]

        resolved = urljoin(base_url, str(raw_value))
        return normalize_url(resolved) if url_rule.normalize_to_canonical else resolved

    def _run_selector(self, selector: SelectorStrategy, soup: BeautifulSoup, document: Any) -> list[Any]:
        if selector.type == SelectorType.CSS:
            if selector.multiple:
                elements = soup.select(selector.value)
            else:
                single = soup.select_one(selector.value)
                elements = [single] if single else []
            return [extract_element_value(element, selector.attribute) for element in elements if element]

        if selector.type == SelectorType.META:
            candidates = [
                soup.find("meta", attrs={"name": selector.value}),
                soup.find("meta", attrs={"property": selector.value}),
                soup.find("meta", attrs={"itemprop": selector.value}),
            ]
            values = []
            for candidate in candidates:
                if not candidate:
                    continue
                values.append(candidate.get(selector.attribute or "content"))
            return [value for value in values if value]

        if selector.type == SelectorType.XPATH:
            values = document.xpath(selector.value)
            normalized: list[Any] = []
            for value in values:
                if hasattr(value, "text_content"):
                    normalized.append(value.get(selector.attribute) if selector.attribute else value.text_content())
                else:
                    normalized.append(str(value))
            return normalized

        if selector.type == SelectorType.JSON_LD:
            return self._extract_json_ld(soup, selector.value)

        return []

    def _extract_json_ld(self, soup: BeautifulSoup, dotted_path: str) -> list[Any]:
        results: list[Any] = []
        for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
            content = tag.string or tag.get_text()
            if not content:
                continue
            try:
                payload = json.loads(content)
            except json.JSONDecodeError:
                continue
            for candidate in iterate_json_ld_nodes(payload):
                value = dotted_lookup(candidate, dotted_path)
                if value in (None, ""):
                    continue
                if isinstance(value, list):
                    results.extend(value)
                else:
                    results.append(value)
        return results

    def _parse_date(self, value: str) -> datetime | None:
        value = value.strip()
        try:
            return parsedate_to_datetime(value)
        except (TypeError, ValueError):
            pass
        try:
            return date_parser.parse(value)
        except (TypeError, ValueError, OverflowError):
            return None

    def _apply_timezone(self, value: datetime, timezone_name: str | None) -> datetime:
        if value.tzinfo is None:
            if timezone_name:
                return value.replace(tzinfo=ZoneInfo(timezone_name)).astimezone(UTC)
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def _apply_postprocess(self, value: Any, steps: list[str]) -> Any:
        result = value
        if hasattr(result, "get_text"):
            result = result.get_text(" ", strip=True)

        if isinstance(result, list):
            processed = [self._apply_postprocess(item, [step for step in steps if step != "dedupe_list"]) for item in result]
            if "dedupe_list" in steps:
                deduped: list[Any] = []
                seen: set[str] = set()
                for item in processed:
                    key = json.dumps(item, sort_keys=True) if not isinstance(item, str) else item
                    if key in seen:
                        continue
                    seen.add(key)
                    deduped.append(item)
                return deduped
            return processed

        if result is None:
            return None

        if not isinstance(result, str):
            result = str(result)

        for step in steps:
            if step == "strip":
                result = result.strip()
            elif step == "normalize_whitespace":
                result = " ".join(result.split())
            elif step == "trim_trailing_slash":
                result = result.rstrip("/")
            elif step == "join_paragraphs":
                parts = [part.strip() for part in result.splitlines() if part.strip()]
                result = "\n\n".join(parts)
            elif step == "html_to_text":
                result = BeautifulSoup(result, "lxml").get_text(" ", strip=True)
        return result


class ScraperEngine:
    """Low-level fetch and extraction engine."""

    strict_order = [
        ScrapingTool.SCRAPLING,
        ScrapingTool.PYDOLL,
        ScrapingTool.SELENIUM,
    ]

    def __init__(self, timeout: int = 30) -> None:
        self.timeout = timeout
        self.extractor = ArticleExtractor()
        self.backends: dict[ScrapingTool, BackendFetcher] = {
            ScrapingTool.SCRAPLING: ScraplingFetcher(timeout=timeout),
            ScrapingTool.PYDOLL: PydollFetcher(timeout=timeout * 2),
            ScrapingTool.SELENIUM: SeleniumFetcher(timeout=timeout * 4),
        }
        self.available_tools = [tool for tool in self.strict_order if self._is_tool_available(tool)]
        LOGGER.info(
            "Available scraping backends: %s",
            [tool.value for tool in self.available_tools] or ["none"],
        )

    def fetch_with_fallback(
        self,
        url: str,
        preferred_tool: ScrapingTool | None = None,
        proxy_config: ProxyConfig | None = None,
    ) -> FetchResult:
        """Fetch a page using the preferred tool, then strict fallback order."""

        attempts: list[FetchAttempt] = []
        proxy_url = resolve_proxy_url(proxy_config)
        ordered_tools = order_tools(preferred_tool, self.available_tools)

        if not ordered_tools:
            raise FetchError(
                f"No scraping backends available for {url}",
                attempts=[
                    FetchAttempt(
                        tool=ScrapingTool.SELENIUM,
                        success=False,
                        elapsed_ms=0,
                        error_type="BackendUnavailable",
                        message="No available backends were detected at runtime",
                    )
                ],
            )

        for tool in ordered_tools:
            html, attempt = self._fetch_once(url, tool=tool, proxy_url=proxy_url)
            attempts.append(attempt)
            if attempt.success:
                LOGGER.info("Fetch success url=%s tool=%s elapsed_ms=%d", url, tool.value, attempt.elapsed_ms)
            else:
                LOGGER.info(
                    "Fetch failed url=%s tool=%s reason=%s blocked=%s elapsed_ms=%d",
                    url,
                    tool.value,
                    attempt.error_type or "UnknownError",
                    attempt.block_detected,
                    attempt.elapsed_ms,
                )
            if html is not None and attempt.success:
                return FetchResult(url=url, html=html, tool=tool, elapsed_ms=attempt.elapsed_ms, attempts=attempts)

        raise FetchError(f"All scraping tools failed for {url}", attempts=attempts)

    def fetch_with_tool(
        self,
        url: str,
        tool: ScrapingTool,
        proxy_config: ProxyConfig | None = None,
    ) -> FetchResult:
        """Fetch a page with a specific backend tool only."""

        if tool not in self.available_tools:
            raise FetchError(
                f"{tool.value} backend unavailable for {url}",
                attempts=[
                    FetchAttempt(
                        tool=tool,
                        success=False,
                        elapsed_ms=0,
                        error_type="BackendUnavailable",
                        message=f"{tool.value} backend unavailable at runtime",
                    )
                ],
            )

        proxy_url = resolve_proxy_url(proxy_config)
        html, attempt = self._fetch_once(url, tool=tool, proxy_url=proxy_url)
        if attempt.success:
            LOGGER.info("Fetch success url=%s tool=%s elapsed_ms=%d", url, tool.value, attempt.elapsed_ms)
        else:
            LOGGER.info(
                "Fetch failed url=%s tool=%s reason=%s blocked=%s elapsed_ms=%d",
                url,
                tool.value,
                attempt.error_type or "UnknownError",
                attempt.block_detected,
                attempt.elapsed_ms,
            )
        if html is not None and attempt.success:
            return FetchResult(url=url, html=html, tool=tool, elapsed_ms=attempt.elapsed_ms, attempts=[attempt])
        raise FetchError(f"{tool.value} failed for {url}", attempts=[attempt])

    def _is_tool_available(self, tool: ScrapingTool) -> bool:
        try:
            if tool == ScrapingTool.SCRAPLING:
                import scrapling  # noqa: F401
                return True
            if tool == ScrapingTool.PYDOLL:
                import pydoll  # type: ignore
                browser_cls = getattr(pydoll, "Browser", None)
                if browser_cls is None:
                    return False
                # Only enable pydoll when it exposes the sync API shape used by this backend.
                return hasattr(browser_cls, "new_page") and hasattr(browser_cls, "close")
            if tool == ScrapingTool.SELENIUM:
                from selenium import webdriver  # noqa: F401
                return True
        except Exception:
            return False
        return False

    def extract_article(self, html: str, url: str, site_selectors: SiteSelectorConfig) -> dict[str, Any]:
        """Extract article fields using configured selectors."""

        return self.extractor.extract_article(html, url, site_selectors)

    def extract_listing_links(self, html: str, base_url: str, site_selectors: SiteSelectorConfig) -> list[str]:
        """Extract article links from a category or home page."""

        return self.extractor.extract_listing_links(html, base_url, site_selectors.article_link_selectors)

    def _fetch_once(self, url: str, tool: ScrapingTool, proxy_url: str | None) -> tuple[str | None, FetchAttempt]:
        backend = self.backends[tool]
        start = time.perf_counter()
        try:
            html = backend.fetch(url, proxy_url=proxy_url)
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            if not html:
                return None, FetchAttempt(
                    tool=tool,
                    success=False,
                    elapsed_ms=elapsed_ms,
                    error_type="EmptyResponse",
                    message="Fetcher returned no HTML",
                )

            blocked = self._looks_blocked(html)
            if blocked or not self._is_valid_html(html):
                return None, FetchAttempt(
                    tool=tool,
                    success=False,
                    elapsed_ms=elapsed_ms,
                    error_type="Blocked" if blocked else "InvalidHtml",
                    message="Response looks blocked or malformed",
                    block_detected=blocked,
                )

            return html, FetchAttempt(tool=tool, success=True, elapsed_ms=elapsed_ms)
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            return None, FetchAttempt(
                tool=tool,
                success=False,
                elapsed_ms=elapsed_ms,
                error_type=exc.__class__.__name__,
                message=str(exc),
            )

    def _is_valid_html(self, html: str) -> bool:
        text = BeautifulSoup(html, "lxml").get_text(" ", strip=True)
        return len(text) >= 120

    def _looks_blocked(self, html: str) -> bool:
        lower_text = BeautifulSoup(html, "lxml").get_text(" ", strip=True).lower()
        hard_indicators = [
            "attention required",
            "access denied",
            "verify you are human",
            "enable javascript and cookies",
            "bot verification",
            "http error 429",
            "your device sent us too many requests",
            "please wait a few minutes before retrying",
            "temporarily rate limited",
        ]
        if any(indicator in lower_text for indicator in hard_indicators):
            return True

        if "captcha" in lower_text and ("verify you are human" in lower_text or "access denied" in lower_text):
            return True
        if "forbidden" in lower_text and ("403" in lower_text or "access denied" in lower_text):
            return True
        if "too many requests" in lower_text and "429" in lower_text:
            return True

        # Avoid false positives from normal pages that merely mention Cloudflare.
        cloudflare_challenge_signals = [
            "/cdn-cgi/challenge-platform",
            "__cf_chl_",
            "cf-chl-",
            "checking your browser before accessing",
            "just a moment...",
        ]
        return any(signal in lower_text for signal in cloudflare_challenge_signals)


class ScraperRunner:
    """High-level orchestrator for config-driven scraping runs."""

    def __init__(self, runtime_config: RuntimeConfig, timeout: int = 30) -> None:
        self.runtime_config = runtime_config
        self.engine = ScraperEngine(timeout=timeout)

    def run(self, input_config: InputConfig, progress_callback: ProgressCallback | None = None) -> RunDatasets:
        """Execute a full scrape and persist state/datasets."""

        catalog = load_json_model(self.runtime_config.catalog_path, SiteCatalog)
        selector_map = load_json_model(self.runtime_config.selectors_path, SelectorMap)
        tracker = self._load_tracker()

        catalog_sites = self._select_sites(catalog, input_config)
        selector_by_name = {site.site_name: site for site in selector_map.sites}
        datasets = RunDatasets()
        total_targets = 0
        planned_targets_by_site: dict[str, int] = {}
        LOGGER.info(
            "Run config execution_mode=%s sites=%s max_items_per_site=%s category_filter_sites=%d",
            input_config.execution_mode.value,
            input_config.sites_to_scrape or "all-active",
            input_config.max_items_per_site,
            len(input_config.category_filters),
        )

        for site in catalog_sites:
            site_tracker = get_or_create_site_tracker(tracker, site.site_name)
            selected_categories = set(input_config.category_filters.get(site.site_name, [])) or None
            targets = self._build_targets(site, site_tracker, input_config.execution_mode, selected_categories)
            planned_targets_by_site[site.site_name] = len(targets)
            total_targets += len(targets)
            LOGGER.info(
                "Planned targets site=%s targets=%d selected_categories=%d",
                site.site_name,
                len(targets),
                len(selected_categories or set()),
            )

        self._emit_progress(
            progress_callback,
            event="run_started",
            mode=input_config.execution_mode.value,
            total_sites=len(catalog_sites),
            total_targets=total_targets,
            completed_targets=0,
            success_items=0,
            error_items=0,
        )

        completed_targets = 0

        for site_index, site in enumerate(catalog_sites, start=1):
            if site.site_name not in selector_by_name:
                datasets.error_log_dataset.append(
                    ErrorDatasetItem(
                        logged_at=utc_now(),
                        site_name=site.site_name,
                        failed_url=str(site.base_url),
                        url_hash=md5_url(str(site.base_url)),
                        error_type="MissingSelectorMap",
                        error_message="No selector configuration found for site",
                        execution_mode=input_config.execution_mode,
                    )
                )
                completed_targets += planned_targets_by_site.get(site.site_name, 0)
                self._emit_progress(
                    progress_callback,
                    event="site_missing_selectors",
                    site_name=site.site_name,
                    site_index=site_index,
                    total_sites=len(catalog_sites),
                    total_targets=total_targets,
                    completed_targets=completed_targets,
                    success_items=len(datasets.success_dataset),
                    error_items=len(datasets.error_log_dataset),
                    percent=progress_percent(completed_targets, total_targets),
                )
                continue

            site_selectors = selector_by_name[site.site_name]
            site_tracker = get_or_create_site_tracker(tracker, site.site_name)
            site_target_total = planned_targets_by_site.get(site.site_name, 0)
            selected_categories = set(input_config.category_filters.get(site.site_name, [])) or None

            self._emit_progress(
                progress_callback,
                event="site_started",
                site_name=site.site_name,
                site_index=site_index,
                total_sites=len(catalog_sites),
                site_total_targets=site_target_total,
                site_processed_targets=0,
                total_targets=total_targets,
                completed_targets=completed_targets,
                success_items=len(datasets.success_dataset),
                error_items=len(datasets.error_log_dataset),
                percent=progress_percent(completed_targets, total_targets),
            )

            base_completed_targets = completed_targets

            def site_progress(payload: dict[str, Any]) -> None:
                site_processed_targets = int(payload.get("site_processed_targets", 0))
                overall_completed = min(base_completed_targets + site_processed_targets, total_targets)
                self._emit_progress(
                    progress_callback,
                    **payload,
                    site_name=site.site_name,
                    site_index=site_index,
                    total_sites=len(catalog_sites),
                    total_targets=total_targets,
                    completed_targets=overall_completed,
                    success_items=len(datasets.success_dataset),
                    error_items=len(datasets.error_log_dataset),
                    percent=progress_percent(overall_completed, total_targets),
                )

            site_summary = self._scrape_site(
                site,
                site_selectors,
                site_tracker,
                input_config,
                datasets,
                selected_categories=selected_categories,
                progress_callback=site_progress,
            )
            completed_targets += site_summary["planned_targets"]
            self._emit_progress(
                progress_callback,
                event="site_completed",
                site_name=site.site_name,
                site_index=site_index,
                total_sites=len(catalog_sites),
                site_total_targets=site_summary["planned_targets"],
                site_processed_targets=site_summary["processed_targets"],
                site_collected_items=site_summary["collected_items"],
                total_targets=total_targets,
                completed_targets=completed_targets,
                success_items=len(datasets.success_dataset),
                error_items=len(datasets.error_log_dataset),
                percent=progress_percent(completed_targets, total_targets),
            )

        save_json_model(self.runtime_config.catalog_path, catalog)
        save_json_model(self.runtime_config.tracker_path, tracker)
        self._write_datasets(datasets)
        self._emit_progress(
            progress_callback,
            event="run_completed",
            mode=input_config.execution_mode.value,
            total_sites=len(catalog_sites),
            total_targets=total_targets,
            completed_targets=total_targets,
            success_items=len(datasets.success_dataset),
            error_items=len(datasets.error_log_dataset),
            percent=100,
        )
        return datasets

    def verify_sites(self, sites_to_verify: list[str] | None = None) -> VerificationReport:
        """Verify that each site's selectors still return valid data."""

        catalog = load_json_model(self.runtime_config.catalog_path, SiteCatalog)
        selector_map = load_json_model(self.runtime_config.selectors_path, SelectorMap)
        selector_by_name = {site.site_name: site for site in selector_map.sites}
        results: list[SiteVerificationResult] = []

        catalog_sites = [site for site in catalog.sites if site.active]
        if sites_to_verify:
            wanted = set(sites_to_verify)
            catalog_sites = [site for site in catalog_sites if site.site_name in wanted]

        for site in catalog_sites:
            issues: list[str] = []
            tool_used: ScrapingTool | None = None
            try:
                selector_config = selector_by_name.get(site.site_name)
                if selector_config is None:
                    issues.append("Missing selector map")
                    raise ExtractionError("Missing selector map")

                listing = self.engine.fetch_with_fallback(
                    str(site.base_url),
                    preferred_tool=site.preferred_scraping_tool,
                )
                tool_used = listing.tool
                links = self.engine.extract_listing_links(listing.html, str(site.base_url), selector_config)
                if not links:
                    issues.append("No article links discovered on listing page")
                    raise ExtractionError("No article links discovered")

                article_url = links[0]
                article_fetch = self.engine.fetch_with_fallback(
                    article_url,
                    preferred_tool=site.preferred_scraping_tool,
                )
                tool_used = article_fetch.tool
                extracted = self.engine.extract_article(article_fetch.html, article_url, selector_config)

                for required_key in ("article_title", "article_body", "date_published", "article_url"):
                    if not extracted.get(required_key):
                        issues.append(f"Required field empty: {required_key}")
            except Exception as exc:
                if not issues:
                    issues.append(str(exc))
                results.append(
                    SiteVerificationResult(
                        site_name=site.site_name,
                        fetched_url=str(site.base_url),
                        success=False,
                        tool_used=tool_used,
                        issues=issues,
                        verified_at=utc_now(),
                    )
                )
                continue

            site.last_verified_at = utc_now()
            results.append(
                SiteVerificationResult(
                    site_name=site.site_name,
                    fetched_url=str(site.base_url),
                    success=not issues,
                    tool_used=tool_used,
                    issues=issues,
                    verified_at=utc_now(),
                )
            )

        save_json_model(self.runtime_config.catalog_path, catalog)
        return VerificationReport(generated_at=utc_now(), results=results)

    def _scrape_site(
        self,
        site: SiteCatalogEntry,
        site_selectors: SiteSelectorConfig,
        site_tracker: SiteCategoryTracker,
        input_config: InputConfig,
        datasets: RunDatasets,
        selected_categories: set[str] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> dict[str, int]:
        targets = self._build_targets(site, site_tracker, input_config.execution_mode, selected_categories)
        seen_urls = {str(item.article_url) for item in datasets.success_dataset}
        max_items = input_config.max_items_per_site
        collected = 0
        processed_targets = 0
        total_targets = len(targets)
        LOGGER.info(
            "Site start site=%s mode=%s targets=%d max_items=%s selected_categories=%d",
            site.site_name,
            input_config.execution_mode.value,
            total_targets,
            max_items,
            len(selected_categories or set()),
        )

        for category_root_url, page_url, page_index in targets:
            if max_items is not None and collected >= max_items:
                break

            page_status = "ok"
            try:
                listing_fetch, links = self._fetch_listing_with_link_fallback(
                    site=site,
                    page_url=page_url,
                    site_selectors=site_selectors,
                    proxy_config=input_config.proxy_config,
                )
                self._record_site_attempt(site, listing_fetch.attempts)
                LOGGER.info(
                    "Listing parsed site=%s page=%s page_index=%d tool=%s links=%d",
                    site.site_name,
                    page_url,
                    page_index,
                    listing_fetch.tool.value,
                    len(links),
                )
                if links:
                    LOGGER.info("Listing link sample site=%s page=%s first_link=%s", site.site_name, page_url, links[0])

                category_state = upsert_category_state(site_tracker, category_root_url, page_index)
                category_state.total_known_pages = max(category_state.total_known_pages, page_index)
                category_state.last_scraped_page_index = max(category_state.last_scraped_page_index, page_index)

                for article_url in links:
                    if max_items is not None and collected >= max_items:
                        break
                    if article_url in seen_urls:
                        continue

                    success_item, error_item = self._scrape_article(
                        site,
                        article_url,
                        category_root_url,
                        site_selectors,
                        input_config.execution_mode,
                        input_config.historic_cutoff_date,
                        input_config.proxy_config,
                    )
                    if error_item is not None:
                        datasets.error_log_dataset.append(error_item)
                    if success_item is None:
                        continue
                    datasets.success_dataset.append(success_item)
                    seen_urls.add(str(success_item.article_url))
                    collected += 1
            except Exception as exc:
                page_status = "error"
                LOGGER.warning(
                    "Listing failed site=%s page=%s page_index=%d error=%s",
                    site.site_name,
                    page_url,
                    page_index,
                    exc,
                )
                fallback_tool_failed = exc.attempts[-1].tool if isinstance(exc, FetchError) and exc.attempts else None
                datasets.error_log_dataset.append(
                    ErrorDatasetItem(
                        logged_at=utc_now(),
                        site_name=site.site_name,
                        failed_url=page_url,
                        url_hash=md5_url(page_url),
                        error_type=exc.__class__.__name__,
                        error_message=str(exc),
                        fallback_tool_failed=fallback_tool_failed,
                        execution_mode=input_config.execution_mode,
                    )
                )
            finally:
                processed_targets += 1
                self._emit_progress(
                    progress_callback,
                    event="page_completed",
                    category_url=category_root_url,
                    page_url=page_url,
                    page_index=page_index,
                    page_status=page_status,
                    site_total_targets=total_targets,
                    site_processed_targets=processed_targets,
                    site_collected_items=collected,
                )

        if site.scraping_history:
            site.preferred_scraping_tool = choose_preferred_tool(site.scraping_history)
        return {
            "planned_targets": total_targets,
            "processed_targets": processed_targets,
            "collected_items": collected,
        }

    def _scrape_article(
        self,
        site: SiteCatalogEntry,
        article_url: str,
        category_url: str,
        site_selectors: SiteSelectorConfig,
        mode: ExecutionMode,
        cutoff_date: datetime | None,
        proxy_config: ProxyConfig,
    ) -> tuple[SuccessDatasetItem | None, ErrorDatasetItem | None]:
        try:
            fetch, article = self._fetch_article_with_extraction_fallback(
                site=site,
                article_url=article_url,
                site_selectors=site_selectors,
                proxy_config=proxy_config,
            )
            self._record_site_attempt(site, fetch.attempts)

            published = ensure_utc(article["date_published"])
            if cutoff_date and published < ensure_utc(cutoff_date):
                return None, None

            self._record_success(site, fetch.tool, fetch.elapsed_ms)
            LOGGER.info(
                "Article success site=%s url=%s tool=%s published=%s",
                site.site_name,
                article_url,
                fetch.tool.value,
                published.isoformat(),
            )
            return SuccessDatasetItem(
                site_name=site.site_name,
                country=site.country,
                region=site.region,
                language=site.language,
                article_title=article["article_title"],
                author=coerce_scalar(article.get("author")),
                article_body=coerce_body(article["article_body"]),
                tags=coerce_tags(article.get("tags")),
                date_published=published,
                article_url=article["article_url"],
                url_hash=article["url_hash"],
                main_image_url=article.get("main_image_url"),
                seo_description=coerce_scalar(article.get("seo_description")),
                scraped_at=utc_now(),
                scraping_tool=fetch.tool,
                execution_mode=mode,
                category_url=category_url,
                source_html_lang=coerce_scalar(article.get("source_html_lang")),
            ), None
        except Exception as exc:
            self._record_failure(site, exc)
            fallback_tool_failed = exc.attempts[-1].tool if isinstance(exc, FetchError) and exc.attempts else None
            return None, ErrorDatasetItem(
                logged_at=utc_now(),
                site_name=site.site_name,
                failed_url=article_url,
                url_hash=md5_url(article_url),
                error_type=exc.__class__.__name__,
                error_message=str(exc),
                fallback_tool_failed=fallback_tool_failed,
                execution_mode=mode,
            )

    def _fetch_listing_with_link_fallback(
        self,
        site: SiteCatalogEntry,
        page_url: str,
        site_selectors: SiteSelectorConfig,
        proxy_config: ProxyConfig,
    ) -> tuple[FetchResult, list[str]]:
        """Fetch listing page and retry extraction across tools when links are missing."""

        ordered_tools = order_tools(site.preferred_scraping_tool, self.engine.available_tools)
        issues: list[str] = []
        last_success_fetch: FetchResult | None = None

        for tool in ordered_tools:
            try:
                fetch = self.engine.fetch_with_tool(page_url, tool=tool, proxy_config=proxy_config)
                last_success_fetch = fetch
                links = self.engine.extract_listing_links(fetch.html, page_url, site_selectors)
                if links:
                    return fetch, links
                issues.append(f"{tool.value}: no article links")
                self._record_site_attempt(site, fetch.attempts)
            except FetchError as exc:
                self._record_site_attempt(site, exc.attempts)
                message = exc.attempts[-1].error_type if exc.attempts else exc.__class__.__name__
                issues.append(f"{tool.value}: {message}")

        feed_links = self._extract_links_from_feed(page_url, site, proxy_config)
        if feed_links and last_success_fetch is not None:
            LOGGER.info(
                "Feed fallback produced links site=%s page=%s links=%d",
                site.site_name,
                page_url,
                len(feed_links),
            )
            return last_success_fetch, feed_links

        raise ExtractionError(f"No article links found on listing page after tool fallback ({'; '.join(issues)})")

    def _fetch_article_with_extraction_fallback(
        self,
        site: SiteCatalogEntry,
        article_url: str,
        site_selectors: SiteSelectorConfig,
        proxy_config: ProxyConfig,
    ) -> tuple[FetchResult, dict[str, Any]]:
        """Fetch article and retry extraction across tools for selector-sensitive pages."""

        ordered_tools = order_tools(site.preferred_scraping_tool, self.engine.available_tools)
        issues: list[str] = []

        for tool in ordered_tools:
            try:
                fetch = self.engine.fetch_with_tool(article_url, tool=tool, proxy_config=proxy_config)
                article = self.engine.extract_article(fetch.html, article_url, site_selectors)
                return fetch, article
            except FetchError as exc:
                self._record_site_attempt(site, exc.attempts)
                message = exc.attempts[-1].error_type if exc.attempts else exc.__class__.__name__
                issues.append(f"{tool.value}: {message}")
            except ExtractionError as exc:
                issues.append(f"{tool.value}: {exc}")

        raise ExtractionError(f"Required selectors failed after tool fallback ({'; '.join(issues)})")

    def _extract_links_from_feed(
        self,
        page_url: str,
        site: SiteCatalogEntry,
        proxy_config: ProxyConfig,
    ) -> list[str]:
        feed_urls = self._build_feed_candidates(page_url)
        article_links: list[str] = []
        seen: set[str] = set()
        for feed_url in feed_urls:
            try:
                fetch = self.engine.fetch_with_fallback(
                    feed_url,
                    preferred_tool=site.preferred_scraping_tool,
                    proxy_config=proxy_config,
                )
                self._record_site_attempt(site, fetch.attempts)
                feed_links = self._parse_feed_links(fetch.html, str(site.base_url))
                for link in feed_links:
                    if link in seen:
                        continue
                    seen.add(link)
                    article_links.append(link)
            except Exception:
                continue
        return article_links

    def _build_feed_candidates(self, page_url: str) -> list[str]:
        normalized_page = normalize_url(page_url)
        trimmed = normalized_page.rstrip("/")
        candidates = [
            f"{trimmed}/feed.xml",
            f"{trimmed}/rss.xml",
        ]
        parsed = urlsplit(normalized_page)
        if parsed.path in {"", "/"}:
            candidates.extend(
                [
                    f"{parsed.scheme}://{parsed.netloc}/news/local/feed.xml",
                    f"{parsed.scheme}://{parsed.netloc}/news/international/feed.xml",
                    f"{parsed.scheme}://{parsed.netloc}/news/business/feed.xml",
                    f"{parsed.scheme}://{parsed.netloc}/news/sports/feed.xml",
                    f"{parsed.scheme}://{parsed.netloc}/news/entertainment/feed.xml",
                ]
            )
        deduped: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            normalized = normalize_url(candidate)
            if normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(normalized)
        return deduped

    def _parse_feed_links(self, content: str, base_url: str) -> list[str]:
        soup = BeautifulSoup(content, "xml")
        links: list[str] = []
        parsed_base = urlsplit(base_url)
        base_host = parsed_base.netloc.lower().removeprefix("www.")

        for item in soup.find_all("item"):
            link_tag = item.find("link")
            value = link_tag.get_text(strip=True) if link_tag else ""
            if value:
                links.append(value)

        for entry in soup.find_all("entry"):
            for link_tag in entry.find_all("link"):
                value = link_tag.get("href") or link_tag.get_text(strip=True)
                if value:
                    links.append(value)

        normalized_links: list[str] = []
        seen: set[str] = set()
        for link in links:
            resolved = urljoin(base_url, str(link).strip())
            if not resolved.startswith("http"):
                continue
            host = urlsplit(resolved).netloc.lower().removeprefix("www.")
            if host != base_host and not host.endswith(f".{base_host}"):
                continue
            if not self.engine.extractor._is_valid_listing_candidate(resolved):
                continue
            score, blocked = self.engine.extractor._score_article_url(resolved)
            if blocked or score <= 0:
                continue
            normalized = normalize_url(resolved)
            if normalized in seen:
                continue
            seen.add(normalized)
            normalized_links.append(normalized)
        return normalized_links

    def _record_site_attempt(self, site: SiteCatalogEntry, attempts: list[FetchAttempt]) -> None:
        for attempt in attempts:
            if attempt.success:
                continue
            self._append_history(
                site,
                attempt.tool,
                success=False,
                elapsed_ms=attempt.elapsed_ms,
                block_detected=attempt.block_detected,
                error_type=attempt.error_type,
            )

    def _record_success(self, site: SiteCatalogEntry, tool: ScrapingTool, elapsed_ms: int) -> None:
        self._append_history(site, tool, success=True, elapsed_ms=elapsed_ms, block_detected=False, error_type=None)
        site.preferred_scraping_tool = choose_preferred_tool(site.scraping_history)

    def _record_failure(self, site: SiteCatalogEntry, exc: Exception) -> None:
        site.preferred_scraping_tool = choose_preferred_tool(site.scraping_history or [])
        LOGGER.warning("Article scrape failed for %s: %s", site.site_name, exc)

    def _append_history(
        self,
        site: SiteCatalogEntry,
        tool: ScrapingTool,
        success: bool,
        elapsed_ms: int,
        block_detected: bool,
        error_type: str | None,
    ) -> None:
        prior = [entry for entry in site.scraping_history if entry.tool == tool]
        sample_size = len(prior) + 1
        successes = sum(1 for entry in prior if entry.success) + int(success)
        success_rate = successes / sample_size
        avg_times = [entry.avg_response_time_ms for entry in prior if entry.avg_response_time_ms is not None]
        avg_response_time_ms = int((sum(avg_times) + elapsed_ms) / (len(avg_times) + 1)) if elapsed_ms else None
        site.scraping_history.append(
            ScrapingHistoryEntry(
                timestamp=utc_now(),
                tool=tool,
                success=success,
                success_rate=success_rate,
                sample_size=sample_size,
                avg_response_time_ms=avg_response_time_ms,
                block_detected=block_detected,
                error_type=error_type,
            )
        )

    def _build_targets(
        self,
        site: SiteCatalogEntry,
        site_tracker: SiteCategoryTracker,
        mode: ExecutionMode,
        selected_categories: set[str] | None = None,
    ) -> list[tuple[str, str, int]]:
        if not site_tracker.categories:
            site_tracker.categories.append(
                CategoryState(
                    category_name="front_page",
                    category_url=str(site.base_url),
                    total_known_pages=2 if mode == ExecutionMode.CURRENT else 50,
                    last_scraped_page_index=0,
                )
            )

        if selected_categories:
            selected = {normalize_url(category_url) for category_url in selected_categories}
            categories = [
                category
                for category in site_tracker.categories
                if normalize_url(str(category.category_url)) in selected
            ]
        else:
            categories = site_tracker.categories

        targets: list[tuple[str, str, int]] = []
        for category in categories:
            if mode == ExecutionMode.CURRENT:
                max_page = min(category.total_known_pages, 2)
                for page_index in range(1, max_page + 1):
                    targets.append(
                        (str(category.category_url), build_page_url(str(category.category_url), page_index), page_index)
                    )
            else:
                start_page = max(category.last_scraped_page_index + 1, 1)
                end_page = max(category.total_known_pages, start_page)
                for page_index in range(start_page, end_page + 1):
                    targets.append(
                        (str(category.category_url), build_page_url(str(category.category_url), page_index), page_index)
                    )
        return targets

    def _select_sites(self, catalog: SiteCatalog, input_config: InputConfig) -> list[SiteCatalogEntry]:
        sites = [site for site in catalog.sites if site.active]
        if input_config.sites_to_scrape:
            allowed = set(input_config.sites_to_scrape)
            sites = [site for site in sites if site.site_name in allowed]
        return sites

    def _load_tracker(self) -> CategoryPaginationTracker:
        if self.runtime_config.tracker_path.exists():
            return load_json_model(self.runtime_config.tracker_path, CategoryPaginationTracker)
        tracker = CategoryPaginationTracker(schema_version="1.0.0", sites=[])
        save_json_model(self.runtime_config.tracker_path, tracker)
        return tracker

    def _write_datasets(self, datasets: RunDatasets) -> None:
        self.runtime_config.output_dir.mkdir(parents=True, exist_ok=True)
        save_json_data(
            self.runtime_config.output_dir / "success_dataset.json",
            [item.model_dump(mode="json") for item in datasets.success_dataset],
        )
        save_json_data(
            self.runtime_config.output_dir / "error_log_dataset.json",
            [item.model_dump(mode="json") for item in datasets.error_log_dataset],
        )

    def _emit_progress(self, progress_callback: ProgressCallback | None, **payload: Any) -> None:
        """Dispatch UI progress updates when a callback is provided."""

        if progress_callback is None:
            return
        progress_callback(payload)


def resolve_proxy_url(proxy_config: ProxyConfig | None) -> str | None:
    """Resolve a proxy URL from runtime config and environment."""

    if proxy_config and proxy_config.proxyUrls:
        return proxy_config.proxyUrls[0]
    if proxy_config and proxy_config.useApifyProxy:
        return os.getenv("APIFY_PROXY_URL") or os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
    return os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")


def extract_element_value(element: Any, attribute: str | None) -> Any:
    """Extract either text or an attribute value from a parsed element."""

    if attribute:
        if hasattr(element, "get"):
            return element.get(attribute)
        return None
    if hasattr(element, "decode_contents"):
        return element.decode_contents() if element.name in {"script", "style"} else element.get_text(" ", strip=True)
    if hasattr(element, "text_content"):
        return element.text_content()
    return str(element)


def iterate_json_ld_nodes(payload: Any) -> list[dict[str, Any]]:
    """Flatten JSON-LD values into a list of dict nodes."""

    if isinstance(payload, list):
        nodes: list[dict[str, Any]] = []
        for item in payload:
            nodes.extend(iterate_json_ld_nodes(item))
        return nodes
    if isinstance(payload, dict):
        if "@graph" in payload and isinstance(payload["@graph"], list):
            nodes = [payload]
            nodes.extend(iterate_json_ld_nodes(payload["@graph"]))
            return nodes
        return [payload]
    return []


def dotted_lookup(payload: dict[str, Any], dotted_path: str) -> Any:
    """Resolve a dotted key path inside a dict."""

    current: Any = payload
    for part in dotted_path.split("."):
        if isinstance(current, list):
            collected = []
            for item in current:
                if isinstance(item, dict) and part in item:
                    collected.append(item[part])
            current = collected
            continue
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def order_tools(preferred_tool: ScrapingTool | None, order: list[ScrapingTool]) -> list[ScrapingTool]:
    """Move the preferred tool to the front without changing fallback order."""

    if preferred_tool is None:
        return order[:]
    return [preferred_tool] + [tool for tool in order if tool != preferred_tool]


def choose_preferred_tool(history: list[ScrapingHistoryEntry]) -> ScrapingTool:
    """Pick the tool with the best success rate, then highest sample size."""

    if not history:
        return ScrapingTool.SCRAPLING

    ranked = sorted(
        history,
        key=lambda entry: (
            entry.success_rate,
            entry.sample_size,
            -1 * (entry.avg_response_time_ms or 10**9),
        ),
        reverse=True,
    )
    return ranked[0].tool


def get_or_create_site_tracker(tracker: CategoryPaginationTracker, site_name: str) -> SiteCategoryTracker:
    """Return tracker entry for a site."""

    for site_tracker in tracker.sites:
        if site_tracker.site_name == site_name:
            return site_tracker
    site_tracker = SiteCategoryTracker(site_name=site_name, categories=[])
    tracker.sites.append(site_tracker)
    return site_tracker


def upsert_category_state(site_tracker: SiteCategoryTracker, category_url: str, page_index: int) -> CategoryState:
    """Return or create a category state record."""

    normalized = normalize_url(category_url)
    for category in site_tracker.categories:
        if normalize_url(str(category.category_url)) == normalized:
            return category
    category = CategoryState(
        category_name=derive_category_name(normalized),
        category_url=normalized,
        total_known_pages=max(page_index, 1),
        last_scraped_page_index=max(page_index - 1, 0),
    )
    site_tracker.categories.append(category)
    return category


def derive_category_name(category_url: str) -> str:
    """Create a readable category name from a URL path."""

    path = urlsplit(category_url).path.strip("/")
    if not path:
        return "front_page"
    return path.replace("/", "_")


def build_page_url(category_url: str, page_index: int) -> str:
    """Create a page URL from a configured category URL."""

    if page_index <= 1:
        return normalize_url(category_url.replace("{page}", "1"))

    if "{page}" in category_url:
        return normalize_url(category_url.format(page=page_index))

    parsed = urlsplit(category_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if "page" in query:
        query["page"] = str(page_index)
        return normalize_url(urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), "")))

    if parsed.path.endswith("/"):
        new_path = f"{parsed.path}page/{page_index}/"
    else:
        new_path = f"{parsed.path}/page/{page_index}/"
    return normalize_url(urlunsplit((parsed.scheme, parsed.netloc, new_path, parsed.query, "")))


def progress_percent(completed_targets: int, total_targets: int) -> int:
    """Convert target progress to a UI-friendly integer percentage."""

    if total_targets <= 0:
        return 100
    ratio = max(0.0, min(completed_targets / total_targets, 1.0))
    return int(round(ratio * 100))


def coerce_scalar(value: Any) -> str | None:
    """Convert extracted values to a scalar string."""

    if value is None:
        return None
    if isinstance(value, list):
        parts = [str(item).strip() for item in value if str(item).strip()]
        if not parts:
            return None
        deduped: list[str] = []
        seen: set[str] = set()
        for part in parts:
            if part in seen:
                continue
            seen.add(part)
            deduped.append(part)
        return ", ".join(deduped)
    text = str(value).strip()
    return text or None


def coerce_body(value: Any) -> str:
    """Normalize article body output."""

    if isinstance(value, list):
        parts = [str(part).strip() for part in value if str(part).strip()]
        return "\n\n".join(parts)
    return str(value).strip()


def coerce_tags(value: Any) -> list[str]:
    """Normalize tags into a list of strings."""

    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [tag.strip() for tag in str(value).split(",") if tag.strip()]


def default_runtime_config(base_dir: str | Path | None = None) -> RuntimeConfig:
    """Resolve standard JSON config locations."""

    root = Path(base_dir or Path.cwd())
    return RuntimeConfig(
        catalog_path=root / "news_scraper" / "data" / "catalog" / "site_catalog.json",
        selectors_path=root / "news_scraper" / "data" / "catalog" / "selector_map.json",
        tracker_path=root / "news_scraper" / "data" / "catalog" / "category_pagination_tracker.json",
        output_dir=root / "news_scraper" / "data" / "exports",
    )
