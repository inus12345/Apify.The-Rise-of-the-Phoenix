"""Core scraper engine with prioritized backend fallback."""
from typing import List, Dict, Optional, Any, Tuple, Set
from datetime import datetime
import hashlib
import json
import re
from urllib.parse import urljoin, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup

from ..database.models import (
    ArticleUrlLedger,
    CategoryCrawlState,
    HistoricalScrapeProgress,
    SiteConfig,
)
from ..core.config import settings, get_logger
from ..extraction.article_extractor import ArticleExtractor
from ..policies.rate_limiter import RateLimiter, DomainThrottler
from ..policies.retry_policy import RetryPolicy
from .selenium_fallback import SeleniumScraper


logger = get_logger(__name__)

NON_ARTICLE_PATH_TERMS = (
    "/about",
    "/contact",
    "/privacy",
    "/terms",
    "/cookies",
    "/accessibility",
    "/newsletters",
    "/newsletter",
    "/live/",
    "/video/",
    "/audio/",
    "/signin",
    "/login",
    "/register",
    "/help",
    "/weather",
    "/undefined",
    "/sitemap",
    "/rss",
    "/feed",
    "/tag/",
    "/tags/",
    "/topic/",
    "/topics/",
    "/author/",
    "/authors/",
    "/account",
    "/events",
    "/conference",
    "/conferences",
    "/careers",
    "/jobs",
    "/cdn-cgi/",
    "/v2/partners-list",
    "/home/page/",
    "/latest/page/",
)

NON_ARTICLE_PATH_SUFFIXES = (
    ".pdf",
    ".xml",
    ".rss",
    ".atom",
    ".ics",
    ".json",
    ".zip",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
    ".svg",
)


class ScraperEngine:
    """
    Core scraper engine with deterministic backend priority.
    
    Features:
    - URL-based deduplication via MD5 hash
    - Multi-backend fallback order: scrapling -> pydoll -> selenium
    - Batch processing
    - Rate limiting for polite scraping
    - Retry policy with exponential backoff
    - Error handling with retry logic
    """
    
    def __init__(
        self,
        batch_size: int = None,
        timeout: int = None,
        max_retries: int = None,
        verify_ssl: bool = True,
        enable_rate_limiting: bool = True,
        min_delay_between_requests: float = 1.0
    ):
        self.batch_size = settings.DEFAULT_BATCH_SIZE if batch_size is None else int(batch_size)
        self.timeout = settings.SCRAPING_TIMEOUT if timeout is None else int(timeout)
        self.max_retries = settings.MAX_RETRIES if max_retries is None else int(max_retries)
        self.user_agent = settings.USER_AGENT
        
        self.http_client: Optional[httpx.Client] = None
        self.selenium_scraper: Optional[SeleniumScraper] = None
        self.verify_ssl = verify_ssl
        self.article_extractor = ArticleExtractor()

        # Lightweight caches to avoid recomputing static per-site decisions.
        self._engine_chain_cache: Dict[int, List[str]] = {}
        self._request_headers_cache: Dict[int, Dict[str, str]] = {}
        self._scrapling_module: Optional[Any] = None
        self._scrapling_checked = False
        self._scrapling_logging_configured = False
        
        self.enable_rate_limiting = enable_rate_limiting
        self.min_delay_between_requests = min_delay_between_requests
        self.rate_limiter: Optional[RateLimiter] = None
        if enable_rate_limiting:
            self.rate_limiter = DomainThrottler(
                global_delay=0.5,
                per_domain_delay=min_delay_between_requests
            )
        
        # Retry policy
        self.retry_policy = RetryPolicy(
            max_retries=self.max_retries,
            base_delay=1.0,
            jitter_range=0.3
        )
    
    def __enter__(self):
        """Context manager entry."""
        headers = self._default_request_headers()
        verify = True if self.verify_ssl else False
        self.http_client = httpx.Client(
            headers=headers,
            timeout=self.timeout,
            follow_redirects=True,
            verify=verify,
            http2=True,
        )
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        if self.http_client:
            self.http_client.close()
        if self.selenium_scraper:
            self.selenium_scraper.__exit__(exc_type, exc_val, exc_tb)
            self.selenium_scraper = None
        self._engine_chain_cache.clear()
        self._request_headers_cache.clear()
    
    def _rate_limit_wait(self, url: str) -> float:
        """Apply rate limiting before a request."""
        if not self.enable_rate_limiting or self.rate_limiter is None:
            return 0.0
        return self.rate_limiter.wait_if_needed(url)

    def _default_request_headers(self) -> Dict[str, str]:
        """Return browser-like default headers for broad compatibility."""
        return {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Upgrade-Insecure-Requests": "1",
            "DNT": "1",
        }

    def _request_headers_for_site(self, site_config: Optional[SiteConfig]) -> Dict[str, str]:
        """Merge per-site header overrides on top of defaults."""
        site_id = getattr(site_config, "id", None)
        if site_id is not None and site_id in self._request_headers_cache:
            return dict(self._request_headers_cache[site_id])

        headers = self._default_request_headers()
        strategy = getattr(site_config, "scrape_strategy", None)
        custom_headers = strategy.request_headers if strategy else None
        if isinstance(custom_headers, dict):
            for key, value in custom_headers.items():
                if key is None or value is None:
                    continue
                headers[str(key)] = str(value)
        if site_id is not None:
            self._request_headers_cache[int(site_id)] = dict(headers)
        return headers
    
    def _record_success(self, url: str) -> None:
        """Record a successful request for rate limiting."""
        if self.enable_rate_limiting and self.rate_limiter:
            self.rate_limiter.record_success(url)
    
    def _record_error(self, url: str) -> None:
        """Record a failed request for rate limiting."""
        if self.enable_rate_limiting and self.rate_limiter:
            self.rate_limiter.record_error(url)
    
    def _get_url_hash(self, url: str) -> str:
        """Generate MD5 hash for URL deduplication."""
        return hashlib.md5(url.encode("utf-8")).hexdigest()

    def _get_content_hash(self, title: Optional[str], body: Optional[str]) -> Optional[str]:
        """Generate a deterministic hash for article content."""
        normalized = f"{(title or '').strip()}::{(body or '').strip()}"
        if normalized == "::":
            return None
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    @staticmethod
    def _serialize_datetime(value: Optional[datetime]) -> Optional[str]:
        """Serialize datetime values into ISO strings."""
        if value is None:
            return None
        return value.isoformat() if hasattr(value, "isoformat") else str(value)

    def _site_metadata_payload(self, site_config: SiteConfig) -> Dict[str, Any]:
        """Build source metadata payload attached to every emitted record."""
        strategy = site_config.scrape_strategy
        technologies = [
            {
                "technology_name": tech.technology_name,
                "technology_type": tech.technology_type,
                "version": tech.version,
                "confidence_score": tech.confidence_score,
                "detection_source": tech.detection_source,
                "notes": tech.notes,
            }
            for tech in (site_config.technologies or [])
        ]
        return {
            "site_config_id": site_config.id,
            "name": site_config.name,
            "url": site_config.url,
            "domain": site_config.domain,
            "country": site_config.country or site_config.location,
            "location": site_config.location,
            "language": site_config.language,
            "description": site_config.description,
            "server_header": site_config.server_header,
            "server_vendor": site_config.server_vendor,
            "hosting_provider": site_config.hosting_provider,
            "ip_address": site_config.ip_address,
            "technology_stack_summary": site_config.technology_stack_summary,
            "category_url_pattern": site_config.category_url_pattern,
            "num_pages_to_scrape": site_config.num_pages_to_scrape,
            "status": site_config.status,
            "active": site_config.active,
            "notes": site_config.notes,
            "preferred_scraper_type": site_config.preferred_scraper_type,
            "uses_javascript": site_config.uses_javascript,
            "technologies": technologies,
            "scrape_strategy": {
                "scraper_engine": strategy.scraper_engine if strategy else None,
                "fallback_engine_chain": strategy.fallback_engine_chain if strategy else None,
                "content_parser": strategy.content_parser if strategy else None,
                "browser_automation_tool": strategy.browser_automation_tool if strategy else None,
                "rendering_required": strategy.rendering_required if strategy else None,
                "requires_proxy": strategy.requires_proxy if strategy else None,
                "proxy_region": strategy.proxy_region if strategy else None,
                "login_required": strategy.login_required if strategy else None,
                "auth_strategy": strategy.auth_strategy if strategy else None,
                "anti_bot_protection": strategy.anti_bot_protection if strategy else None,
                "blocking_signals": strategy.blocking_signals if strategy else None,
                "bypass_techniques": strategy.bypass_techniques if strategy else None,
                "request_headers": strategy.request_headers if strategy else None,
                "cookie_preset": strategy.cookie_preset if strategy else None,
                "rate_limit_per_minute": strategy.rate_limit_per_minute if strategy else None,
                "notes": strategy.notes if strategy else None,
            },
        }

    def _update_category_state(
        self,
        spider_session,
        *,
        site_config_id: int,
        category_id: Optional[int],
        category_name: Optional[str],
        category_url: str,
        page_url: str,
        page_number: Optional[int],
        links_discovered: int,
        records_emitted: int,
        mode: str,
        chunk_id: Optional[str],
    ) -> None:
        """Upsert crawl coverage state for a category page scrape."""
        if spider_session is None or not category_url:
            return
        try:
            state = (
                spider_session.query(CategoryCrawlState)
                .filter(
                    CategoryCrawlState.site_config_id == site_config_id,
                    CategoryCrawlState.category_url == category_url,
                )
                .first()
            )
            if state is None:
                state = CategoryCrawlState(
                    site_config_id=site_config_id,
                    site_category_id=category_id,
                    category_name=category_name,
                    category_url=category_url,
                    total_listing_pages_scraped=0,
                    total_links_discovered=0,
                    total_records_emitted=0,
                )
                spider_session.add(state)

            state.site_category_id = category_id or state.site_category_id
            state.category_name = category_name or state.category_name
            state.last_page_scraped = page_number
            state.max_page_seen = max(page_number or 0, state.max_page_seen or 0) or None
            state.last_page_url = page_url
            state.last_mode = mode
            state.last_chunk_id = chunk_id
            state.last_scraped_at = datetime.now()
            state.total_listing_pages_scraped = int(state.total_listing_pages_scraped or 0) + 1
            state.total_links_discovered = int(state.total_links_discovered or 0) + int(links_discovered or 0)
            state.total_records_emitted = int(state.total_records_emitted or 0) + int(records_emitted or 0)
            spider_session.commit()
        except Exception as exc:
            spider_session.rollback()
            logger.debug(f"Failed to update category crawl state for {category_url}: {exc}")

    @staticmethod
    def _normalize_engine_name(engine: Optional[str]) -> str:
        """Normalize engine labels into supported backend names."""
        value = (engine or "scrapling").strip().lower()
        mapping = {
            "httpx": "scrapling",
            "playwright": "pydoll",
            "bs4": "beautifulsoup",
            "beautiful_soup": "beautifulsoup",
        }
        return mapping.get(value, value)

    @staticmethod
    def _coerce_html_from_response(response: Any) -> Optional[str]:
        """Extract HTML text from heterogeneous scraper response objects."""
        if response is None:
            return None
        if isinstance(response, str):
            return response
        if isinstance(response, (bytes, bytearray)):
            return response.decode("utf-8", errors="ignore")

        for attr in ("text", "content", "body", "html"):
            if not hasattr(response, attr):
                continue

            value = getattr(response, attr)
            if value is None:
                continue

            if isinstance(value, str):
                if value.strip():
                    return value
                continue
            if isinstance(value, (bytes, bytearray)):
                decoded = value.decode("utf-8", errors="ignore")
                if decoded.strip():
                    return decoded
                continue

            coerced = str(value)
            if coerced.strip():
                return coerced

        return None

    def _get_engine_chain(self, site_config: SiteConfig) -> List[str]:
        """Resolve backend fallback chain from site config/strategy."""
        site_id = getattr(site_config, "id", None)
        if site_id is not None and int(site_id) in self._engine_chain_cache:
            return list(self._engine_chain_cache[int(site_id)])

        strategy = getattr(site_config, "scrape_strategy", None)
        primary = self._normalize_engine_name(
            strategy.scraper_engine if strategy and strategy.scraper_engine else site_config.preferred_scraper_type
        )

        fallback_raw = strategy.fallback_engine_chain if strategy else None
        if not isinstance(fallback_raw, list):
            fallback_raw = ["pydoll", "selenium"]

        candidates = [primary] + [self._normalize_engine_name(engine) for engine in fallback_raw]

        # Always enforce the global priority guarantees.
        for must_have in ["scrapling", "pydoll", "selenium"]:
            if must_have not in candidates:
                candidates.append(must_have)

        deduped: List[str] = []
        for candidate in candidates:
            if candidate and candidate not in deduped:
                deduped.append(candidate)
        if site_id is not None:
            self._engine_chain_cache[int(site_id)] = list(deduped)
        return deduped

    def _get_scrapling_module(self) -> Optional[Any]:
        """Resolve Scrapling module once and reuse for the run."""
        if self._scrapling_checked:
            return self._scrapling_module

        self._scrapling_checked = True
        try:
            import scrapling  # type: ignore

            self._scrapling_module = scrapling
            if not self._scrapling_logging_configured:
                try:
                    from scrapling.core.utils import log as scrapling_log  # type: ignore

                    scrapling_log.setLevel("ERROR")
                    self._scrapling_logging_configured = True
                except Exception:
                    pass
            return self._scrapling_module
        except Exception:
            self._scrapling_module = None
            return None

    def _fetch_page_beautifulsoup(self, url: str, headers: Optional[Dict[str, str]] = None) -> Optional[str]:
        """Fetch static HTML using HTTPX (BeautifulSoup parser path)."""
        if self.http_client is None:
            # Allow direct use without context manager in utility/test scenarios.
            with httpx.Client(
                headers=self._default_request_headers(),
                timeout=self.timeout,
                follow_redirects=True,
                verify=self.verify_ssl,
                http2=True,
            ) as temp_client:
                self.http_client = temp_client
                try:
                    return self._fetch_page_beautifulsoup(url, headers=headers)
                finally:
                    self.http_client = None

        wait_time = self._rate_limit_wait(url)
        if wait_time > 0:
            logger.debug(f"Rate limited. Waiting {wait_time:.2f}s before fetching {url}")

        request_headers = headers or self._default_request_headers()

        def fetch():
            response = self.http_client.get(url, headers=request_headers)
            text = response.text or ""
            if response.status_code >= 500:
                response.raise_for_status()
            if response.status_code >= 400 and self._detect_content_missing(text):
                response.raise_for_status()
            return text

        try:
            result = self.retry_policy.execute_with_callback(fetch, name=url[:50])
            self._record_success(url)
            return result
        except Exception as e:
            self._record_error(url)
            logger.debug(f"BeautifulSoup fetch failed for {url}: {e}")
            return None

    def _fetch_page_scrapling(self, url: str, headers: Optional[Dict[str, str]] = None) -> Optional[str]:
        """
        Fetch page using Scrapling if installed.

        If Scrapling is unavailable in the runtime, falls back to the static
        BeautifulSoup HTTP fetch path while preserving engine priority semantics.
        """
        scrapling = self._get_scrapling_module()
        if scrapling is None:
            return self._fetch_page_beautifulsoup(url)

        wait_time = self._rate_limit_wait(url)
        if wait_time > 0:
            logger.debug(f"Rate limited. Waiting {wait_time:.2f}s before fetching {url}")

        def fetch():
            request_headers = headers or self._default_request_headers()
            request_kwargs = {
                "headers": request_headers,
                "timeout": self.timeout,
                "retries": 0,
                "retry_delay": 0,
                "follow_redirects": True,
            }

            if hasattr(scrapling, "Fetcher"):
                fetcher = scrapling.Fetcher()
                if hasattr(fetcher, "configure"):
                    fetcher.configure(**request_kwargs)
                    response = fetcher.get(url)
                else:
                    response = fetcher.get(url, **request_kwargs)
                html = self._coerce_html_from_response(response)
                if html:
                    return html

            if hasattr(scrapling, "Scraper"):
                scraper = scrapling.Scraper()
                response = scraper.get(url, **request_kwargs)
                html = self._coerce_html_from_response(response)
                if html:
                    return html

            # Fallback when the installed Scrapling API differs from expected.
            return self._fetch_page_beautifulsoup(url)

        try:
            result = self.retry_policy.execute_with_callback(fetch, name=f"scrapling:{url[:40]}")
            self._record_success(url)
            return result
        except Exception as e:
            self._record_error(url)
            logger.debug(f"Scrapling fetch failed for {url}: {e}")
            return None

    def _fetch_page_pydoll(self, url: str) -> Optional[str]:
        """Fetch page using pydoll if available."""
        try:
            import pydoll  # type: ignore
        except Exception:
            return None

        try:
            # The API varies across versions; try common entrypoints defensively.
            if hasattr(pydoll, "Browser"):
                browser = pydoll.Browser(headless=True)
                page = browser.new_page()
                page.goto(url, timeout=self.timeout * 1000)
                content = page.content()
                if hasattr(browser, "close"):
                    browser.close()
                if isinstance(content, str):
                    return content
        except Exception as e:
            logger.debug(f"Pydoll Browser API failed for {url}: {e}")

        try:
            if hasattr(pydoll, "launch"):
                browser = pydoll.launch(headless=True)
                page = browser.new_page()
                page.goto(url, timeout=self.timeout * 1000)
                content = page.content()
                if hasattr(browser, "close"):
                    browser.close()
                if isinstance(content, str):
                    return content
        except Exception as e:
            logger.debug(f"Pydoll launch API failed for {url}: {e}")

        return None

    def _fetch_page_selenium(self, url: str) -> Optional[str]:
        """Fetch page using Selenium as final fallback."""
        try:
            if self.selenium_scraper is None:
                self.selenium_scraper = SeleniumScraper(headless=True, timeout=self.timeout)
                self.selenium_scraper.__enter__()
            return self.selenium_scraper.fetch_page(url)
        except Exception as e:
            logger.debug(f"Selenium fetch failed for {url}: {e}")
            return None

    def _fetch_page_for_site(
        self,
        site_config: SiteConfig,
        url: str,
    ) -> Tuple[Optional[str], Optional[str]]:
        """Fetch page using configured backend fallback chain for a site."""
        headers = self._request_headers_for_site(site_config)
        for engine_name in self._get_engine_chain(site_config):
            if engine_name == "scrapling":
                html = self._fetch_page_scrapling(url, headers=headers)
            elif engine_name == "pydoll":
                html = self._fetch_page_pydoll(url)
            elif engine_name == "selenium":
                html = self._fetch_page_selenium(url)
            elif engine_name == "beautifulsoup":
                html = self._fetch_page_beautifulsoup(url, headers=headers)
            else:
                logger.debug(f"Unknown scraper engine '{engine_name}' for site '{site_config.name}'")
                html = None

            if not html:
                continue
            if self._detect_content_missing(html):
                logger.debug(f"Engine {engine_name} produced low-content response for {url}; trying fallback.")
                continue
            return html, engine_name

        # Legacy static fallback for resilience.
        html = self._fetch_page_beautifulsoup(url, headers=headers)
        if html and not self._detect_content_missing(html):
            return html, "beautifulsoup"
        return None, None

    def _fetch_static_page_for_site(
        self,
        site_config: SiteConfig,
        url: str,
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Fetch using static engines only (Scrapling/BeautifulSoup).

        This keeps listing/category fetches fast and deterministic while article
        detail pages can still use the full browser fallback chain.
        """
        headers = self._request_headers_for_site(site_config)
        preferred_chain = self._get_engine_chain(site_config)
        static_chain = [engine for engine in preferred_chain if engine in {"scrapling", "beautifulsoup"}]
        if "scrapling" not in static_chain:
            static_chain.insert(0, "scrapling")
        if "beautifulsoup" not in static_chain:
            static_chain.append("beautifulsoup")

        for engine_name in self._ordered_unique(static_chain):
            if engine_name == "scrapling":
                html = self._fetch_page_scrapling(url, headers=headers)
            else:
                html = self._fetch_page_beautifulsoup(url, headers=headers)

            if not html:
                continue
            if self._detect_content_missing(html):
                continue
            return html, engine_name
        return None, None

    def _fetch_page(self, url: str) -> Optional[str]:
        """Legacy compatibility fetch path (static)."""
        return self._fetch_page_beautifulsoup(url)

    @staticmethod
    def _registrable_domain(hostname: str) -> str:
        """Return a coarse registrable domain for cross-subdomain matching."""
        host = (hostname or "").lower().replace("www.", "").strip(".")
        parts = host.split(".")
        if len(parts) < 2:
            return host
        return ".".join(parts[-2:])

    def _is_same_site_domain(self, base_domain: str, candidate_domain: str) -> bool:
        """Allow same host, parent/subdomain, or same registrable domain."""
        base = (base_domain or "").lower().replace("www.", "").strip(".")
        cand = (candidate_domain or "").lower().replace("www.", "").strip(".")
        if not base or not cand:
            return True
        if cand.endswith(base) or base.endswith(cand):
            return True
        if self._registrable_domain(base) == self._registrable_domain(cand):
            return True

        base_labels = base.split(".")
        cand_labels = cand.split(".")
        if len(base_labels) >= 2 and len(cand_labels) >= 2:
            if base_labels[0] == cand_labels[0] and base_labels[-1] == cand_labels[-1]:
                return True

        return False

    def _is_candidate_article_url(self, absolute_url: str, base_domain: str) -> bool:
        """Heuristically filter non-article and utility URLs."""
        parsed = urlparse(absolute_url)
        if parsed.scheme not in ("http", "https"):
            return False

        domain = (parsed.netloc or "").lower().replace("www.", "")
        if not self._is_same_site_domain(base_domain, domain):
            return False

        path = (parsed.path or "").lower()
        if not path or path == "/" or len(path) < 5:
            return False
        if any(path.endswith(suffix) for suffix in NON_ARTICLE_PATH_SUFFIXES):
            return False
        if any(term in path for term in NON_ARTICLE_PATH_TERMS):
            return False
        if re.search(r"/page/\d+/?$", path):
            return False
        return True

    def _is_article_payload_usable(self, url: str, article_data: Dict[str, Any]) -> bool:
        """Quality guardrail to reduce non-article/rubbish records."""
        title = (article_data.get("title") or "").strip()
        body = (article_data.get("body") or "").strip()
        if len(title) < 12 or len(body) < 180:
            return False

        lower_url = (url or "").lower()
        if any(token in lower_url for token in NON_ARTICLE_PATH_TERMS):
            return False
        if re.search(r"/page/\d+/?$", urlparse(lower_url).path or ""):
            return False

        lower_title = title.lower()
        if any(token in lower_title for token in ("privacy policy", "terms of service", "cookie policy", "newsletter")):
            return False
        return True

    @staticmethod
    def _ordered_unique(values: List[str]) -> List[str]:
        """Preserve list order while removing duplicates."""
        seen: Set[str] = set()
        ordered: List[str] = []
        for value in values:
            item = (value or "").strip()
            if not item or item in seen:
                continue
            seen.add(item)
            ordered.append(item)
        return ordered

    @staticmethod
    def _root_url(url: str) -> str:
        """Normalize a URL to its site root."""
        parsed = urlparse(url or "")
        if not parsed.scheme or not parsed.netloc:
            return ""
        return f"{parsed.scheme}://{parsed.netloc}/"

    def _candidate_listing_urls(self, site_config: SiteConfig, page_url: str) -> List[str]:
        """Build resilient listing URL candidates for a category."""
        parsed = urlparse(page_url or "")
        no_query = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", "")) if parsed.netloc else ""
        candidates = [
            page_url,
            no_query,
            site_config.url,
            self._root_url(page_url),
            self._root_url(site_config.url),
        ]
        return self._ordered_unique(candidates)

    def _default_feed_candidates(self, url: str) -> List[str]:
        """Generate common feed endpoint guesses for a site/section URL."""
        parsed = urlparse(url or "")
        if not parsed.scheme or not parsed.netloc:
            return []

        root = f"{parsed.scheme}://{parsed.netloc}"
        path = (parsed.path or "").rstrip("/")
        guesses = [
            f"{root}/feed",
            f"{root}/rss",
            f"{root}/feed.xml",
            f"{root}/rss.xml",
        ]
        if path:
            guesses.extend(
                [
                    f"{root}{path}/feed",
                    f"{root}{path}/rss",
                    f"{root}{path}.xml",
                ]
            )
        return self._ordered_unique(guesses)

    def _discover_feed_urls(self, html: str, base_url: str) -> List[str]:
        """Extract feed endpoints from a page and add common fallbacks."""
        soup = BeautifulSoup(html, "html.parser")
        candidates: List[str] = []

        for link_tag in soup.find_all("link", href=True):
            href = (link_tag.get("href") or "").strip()
            if not href:
                continue
            rel_values = [str(v).lower() for v in (link_tag.get("rel") or [])]
            mime = (link_tag.get("type") or "").lower()
            href_lower = href.lower()
            if (
                "alternate" in rel_values
                and any(token in mime for token in ("rss", "atom", "xml"))
            ) or any(token in href_lower for token in ("/rss", "/feed", ".xml", "/feeds/")):
                candidates.append(urljoin(base_url, href))

        for anchor in soup.find_all("a", href=True):
            href = (anchor.get("href") or "").strip()
            if not href:
                continue
            href_lower = href.lower()
            if any(token in href_lower for token in ("/rss", "/feed", ".xml", "/feeds/")):
                candidates.append(urljoin(base_url, href))

        candidates.extend(self._default_feed_candidates(base_url))
        return self._ordered_unique(candidates)

    @staticmethod
    def _is_hard_block_page(html: str) -> bool:
        """Detect hard anti-bot/interstitial responses where feed probing is pointless."""
        lower_html = (html or "").lower()
        signals = (
            "captcha-delivery.com",
            "geo.captcha-delivery.com",
            "cf-chl",
            "checking your browser",
            "attention required",
            "access denied",
            "forbidden",
            "datadome",
            "perimeterx",
            "/cdn-cgi/challenge-platform/",
        )
        return any(signal in lower_html for signal in signals)

    def _fetch_listing_page_for_site(
        self,
        site_config: SiteConfig,
        page_url: str,
    ) -> Tuple[Optional[str], Optional[str], str]:
        """
        Fetch listing content with recovery steps.

        Recovery order:
        1. Category URL and close variants.
        2. Site homepage/root.
        3. Discovered/common RSS/Atom feeds.
        """
        attempts: List[Tuple[str, Optional[str], Optional[str]]] = []
        feed_candidates: List[str] = []
        saw_non_block_html = False

        for candidate in self._candidate_listing_urls(site_config, page_url):
            html, engine = self._fetch_static_page_for_site(site_config, candidate)
            attempts.append((candidate, html, engine))
            if not html:
                continue
            if self._is_hard_block_page(html):
                continue
            saw_non_block_html = True

            try:
                links = self._parse_links_from_page(html, candidate)
            except Exception:
                links = []
            if links:
                return html, engine, candidate

            try:
                feed_candidates.extend(self._discover_feed_urls(html, candidate))
            except Exception:
                continue

        if saw_non_block_html:
            feed_candidates.extend(self._default_feed_candidates(page_url))
            feed_candidates.extend(self._default_feed_candidates(site_config.url))

        for feed_url in self._ordered_unique(feed_candidates)[:8]:
            html, engine = self._fetch_static_page_for_site(site_config, feed_url)
            if not html:
                continue
            try:
                links = self._parse_links_from_page(html, feed_url)
            except Exception:
                links = []
            if links:
                return html, engine, feed_url

        # Return the first fetched HTML, if any, for diagnostics.
        for attempted_url, html, engine in attempts:
            if html:
                return html, engine, attempted_url

        return None, None, page_url

    def _parse_links_from_page(self, html: str, base_url: str) -> List[str]:
        """Parse article links from a page's HTML content."""
        if isinstance(html, (bytes, bytearray)):
            html = html.decode("utf-8", errors="ignore")
        elif not isinstance(html, str):
            html = str(html or "")

        links: List[str] = []
        lower_html = html.lower()
        stripped_html = html.lstrip().lower()
        base_domain = (urlparse(base_url).netloc or "").lower().replace("www.", "")
        is_xml_feed = (
            stripped_html.startswith("<?xml")
            or "<rss" in lower_html[:3000]
            or "<feed" in lower_html[:3000]
        )

        if is_xml_feed:
            feed_soup = BeautifulSoup(html, "xml")
            for link_tag in feed_soup.find_all("link"):
                raw_link = (link_tag.get("href") or link_tag.get_text() or "").strip()
                if not raw_link:
                    continue
                parsed = urlparse(raw_link)
                if parsed.scheme not in ("http", "https"):
                    continue
                normalized = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", parsed.query, ""))
                if not self._is_candidate_article_url(normalized, base_domain):
                    continue
                links.append(normalized)
            return list(dict.fromkeys(links))

        soup = BeautifulSoup(html, "html.parser")

        for a_tag in soup.find_all("a", href=True):
            href = (a_tag["href"] or "").strip()
            if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue

            absolute = urljoin(base_url, href)
            if not self._is_candidate_article_url(absolute, base_domain):
                continue

            parsed = urlparse(absolute)
            normalized = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", parsed.query, ""))
            links.append(normalized)

        # Also inspect JSON-LD blobs for article URLs on JS-heavy listing pages.
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            raw = script.string or script.get_text() or ""
            if isinstance(raw, (bytes, bytearray)):
                raw = raw.decode("utf-8", errors="ignore")
            if not isinstance(raw, str):
                raw = str(raw)
            raw = raw.strip()
            if not raw:
                continue

            try:
                payload = json.loads(raw)
            except Exception:
                continue

            stack = [payload]
            while stack:
                node = stack.pop()
                if isinstance(node, dict):
                    for key, value in node.items():
                        if key in {"url", "@id", "mainEntityOfPage"} and isinstance(value, str):
                            absolute = urljoin(base_url, value)
                            if self._is_candidate_article_url(absolute, base_domain):
                                parsed = urlparse(absolute)
                                normalized = urlunparse(
                                    (parsed.scheme, parsed.netloc, parsed.path, "", parsed.query, "")
                                )
                                links.append(normalized)
                        elif isinstance(value, (dict, list)):
                            stack.append(value)
                elif isinstance(node, list):
                    stack.extend(node)

        return list(dict.fromkeys(links))

    def _extract_article(self, url: str, html: str) -> Optional[Dict[str, Any]]:
        """Extract article data from HTML content using ArticleExtractor."""
        try:
            return self.article_extractor.extract(url, html)
        except Exception as e:
            logger.error(f"Error extracting article from {url}: {e}")
            return None
    
    def _parse_date_from_selector(self, date_str: str) -> Optional[datetime]:
        """Parse a date string from article data."""
        try:
            from datetime import datetime as dt
            from dateutil import parser
            
            for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y", "%b %d, %Y"]:
                try:
                    return dt.strptime(date_str.strip(), fmt)
                except ValueError:
                    continue
            
            parsed = parser.parse(date_str.strip(), fuzzy=True)
            return parsed
        except Exception:
            return None

    def _get_article_date(self, article_data: Dict[str, Any]) -> Optional[datetime]:
        """Extract date from article data."""
        if not article_data.get("date_publish"):
            return None

        raw_date = article_data["date_publish"]
        if hasattr(raw_date, "strftime"):
            return raw_date

        date_str = str(raw_date)
        
        parsed_date = self._parse_date_from_selector(date_str)
        return parsed_date

    def _get_page_urls(
        self,
        site_config: SiteConfig,
        mode: str = "incremental",
        start_page: int = 1,
        end_page: Optional[int] = None,
        date_cutoff: Optional[datetime] = None,
        max_pages: Optional[int] = None
    ) -> List[str]:
        """Generate list of page URLs to scrape."""
        mode = self._normalize_mode(mode)
        if not site_config.category_url_pattern:
            return [site_config.url]

        urls: List[str] = []
        pattern = site_config.category_url_pattern
        start = max(int(start_page or 1), 1)

        if mode == "incremental":
            default_pages = max(int(site_config.num_pages_to_scrape or 1), 1)
            page_budget = min(default_pages, max_pages or default_pages)
            stop = end_page if end_page and end_page >= start else (start + page_budget - 1)

            for page_num in range(start, stop + 1):
                url = pattern.replace("{page}", str(page_num))
                urls.append(url)

        elif mode == "backfill":
            page_budget = max_pages if max_pages is not None else max(int(site_config.num_pages_to_scrape or 1) * 5, 1)
            stop = end_page if end_page and end_page >= start else (start + page_budget - 1)

            for page_num in range(start, stop + 1):
                url = pattern.replace("{page}", str(page_num))

                if date_cutoff:
                    try:
                        html, _ = self._fetch_page_for_site(site_config, url)
                        if html:
                            date_str = self._extract_page_date(html, site_config.date_selector or "")
                            if date_str:
                                parsed_date = self._parse_date_from_selector(date_str)
                                if parsed_date and parsed_date < date_cutoff:
                                    urls.append(url)
                                continue
                    except Exception:
                        pass

                    # If page date cannot be read, still include for resilience.
                    urls.append(url)
                else:
                    urls.append(url)

        return urls

    @staticmethod
    def _normalize_mode(mode: str) -> str:
        """Normalize user-friendly mode names into engine mode names."""
        mapping = {
            "current": "incremental",
            "incremental": "incremental",
            "historic": "backfill",
            "historical": "backfill",
            "backfill": "backfill",
            "full": "backfill",
        }
        return mapping.get((mode or "incremental").lower(), "incremental")

    def _extract_page_date(self, html: str, selector: str) -> Optional[str]:
        """Extract date from a listing page."""
        soup = BeautifulSoup(html, "html.parser")
        
        date_selectors = [selector] if selector else [
            ".date", "#date", "[datetime]",
            '.pub-date', '.timestamp', '.post-meta time',
            'time[datetime]'
        ]
        
        for sel in date_selectors:
            elem = soup.select_one(sel)
            if elem:
                if elem.has_attr("datetime"):
                    return elem["datetime"]
                
                text = elem.get_text(strip=True)
                if text and len(text) > 5:
                    from datetime import datetime as dt
                    for fmt in ["%Y-%m-%d", "%Y/%m/%d"]:
                        try:
                            dt.strptime(text, fmt)
                            return text
                        except ValueError:
                            pass
        
        return None

    def _detect_content_missing(self, html: str) -> bool:
        """Detect if content appears to be missing or loading."""
        if not html or not html.strip():
            return True

        lower_html = html.lower()
        stripped_html = html.lstrip().lower()
        is_xml_feed = (
            stripped_html.startswith("<?xml")
            or "<rss" in lower_html[:3000]
            or "<feed" in lower_html[:3000]
        )

        if is_xml_feed:
            feed_soup = BeautifulSoup(html, "xml")
            if feed_soup.find("item") or feed_soup.find("entry"):
                return False
            feed_text = feed_soup.get_text(" ", strip=True)
            return len(feed_text) < 80

        soup = BeautifulSoup(html, "html.parser")

        body_text = soup.get_text(" ", strip=True)
        lower_text = body_text.lower()
        text_len = len(body_text)

        # Very short responses are usually placeholders, consent stubs, or blocks.
        if text_len < 120:
            return True

        load_indicators = [
            "loading",
            "under construction",
            "please wait",
            "initializing",
        ]
        for indicator in load_indicators:
            # Guard with a low-text threshold to avoid false positives on real pages.
            if indicator in lower_text and text_len < 1200:
                return True

        no_content_indicators = [
            "content will be available soon",
            "coming soon",
            "this page is unavailable",
            "site under maintenance",
            "access denied",
            "forbidden",
            "temporarily unavailable",
            "please enable javascript",
            "captcha",
            "just a moment",
            "attention required",
            "checking your browser before accessing",
        ]
        for indicator in no_content_indicators:
            if indicator in lower_text and text_len < 3000:
                return True

        if text_len < 200 and soup.find("body"):
            return True

        return False

    def _ensure_historical_progress_table(self, db_session) -> None:
        """Create historical progress table on demand for older databases."""
        try:
            HistoricalScrapeProgress.__table__.create(bind=db_session.get_bind(), checkfirst=True)
        except Exception as e:
            logger.debug(f"Could not ensure historical progress table exists: {e}")

    def scrape_site(
        self,
        site_config: SiteConfig,
        db_session,
        spider_session=None,
        mode: str = "incremental",
        export_csv: str = None,
        export_json: str = None,
        verify_ssl: bool = True,
        enable_rate_limiting: bool = None,
        start_page: int = 1,
        end_page: Optional[int] = None,
        date_cutoff: Optional[datetime] = None,
        max_pages: Optional[int] = None,
        chunk_id: Optional[str] = None,
        max_new_articles: Optional[int] = None,
        category_targets: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Scrape a configured website."""
        mode = self._normalize_mode(mode)

        stats = {
            "site_name": site_config.name,
            "url": site_config.url,
            "mode": mode,
            "scraper_chain": self._get_engine_chain(site_config),
            "content_parser": (
                site_config.scrape_strategy.content_parser
                if site_config.scrape_strategy and site_config.scrape_strategy.content_parser
                else "beautifulsoup"
            ),
            "pages_scraped": 0,
            "articles_found": 0,
            "articles_saved": 0,
            "articles_skipped": 0,
            "errors": [],
            "selenium_fallbacks": 0,
            "scraper_engines_used": {},
            "historical_progress_id": None,
            "chunk_id": chunk_id,
            "max_new_articles": max_new_articles,
            "stopped_reason": None,
            "records": [],
        }

        if max_new_articles is not None and int(max_new_articles) <= 0:
            stats["stopped_reason"] = "site_article_cap_reached"
            return stats
        
        original_verify = self.verify_ssl
        self.verify_ssl = verify_ssl

        if self.rate_limiter:
            self._reset_rate_limiter_state(site_config.url)

        if enable_rate_limiting is not None:
            self.enable_rate_limiting = enable_rate_limiting
        
        page_targets: List[Dict[str, Any]] = []
        if category_targets:
            for target in category_targets:
                category_id = target.get("category_id")
                category_name = target.get("category_name")
                category_url = target.get("category_url") or site_config.url
                for entry in target.get("page_urls", []):
                    if isinstance(entry, dict):
                        page_url = (entry.get("url") or "").strip()
                        page_number = entry.get("page_number")
                    else:
                        page_url = str(entry).strip()
                        page_number = None
                    if not page_url:
                        continue
                    page_targets.append(
                        {
                            "page_url": page_url,
                            "page_number": page_number,
                            "category_id": category_id,
                            "category_name": category_name,
                            "category_url": category_url,
                        }
                    )

        if not page_targets:
            page_urls = self._get_page_urls(
                site_config,
                mode=mode,
                start_page=start_page,
                end_page=end_page,
                date_cutoff=date_cutoff,
                max_pages=max_pages,
            )
            for idx, page_url in enumerate(page_urls, start=1):
                page_targets.append(
                    {
                        "page_url": page_url,
                        "page_number": idx,
                        "category_id": None,
                        "category_name": None,
                        "category_url": site_config.url,
                    }
                )

        stats["pages_targeted"] = len(page_targets)
        site_metadata = self._site_metadata_payload(site_config)

        historical_progress: Optional[HistoricalScrapeProgress] = None
        if mode == "backfill":
            self._ensure_historical_progress_table(db_session)
            historical_progress = HistoricalScrapeProgress(
                site_config_id=site_config.id,
                mode=mode,
                chunk_id=chunk_id,
                start_page=start_page,
                end_page=end_page,
                max_pages=max_pages,
                pages_targeted=len(page_targets),
                pages_scraped=0,
                cutoff_date=date_cutoff,
                status="running",
                run_metadata={
                    "site_name": site_config.name,
                    "site_url": site_config.url,
                    "scraper_chain": stats["scraper_chain"],
                },
            )
            try:
                db_session.add(historical_progress)
                db_session.commit()
                db_session.refresh(historical_progress)
                stats["historical_progress_id"] = historical_progress.id
            except Exception as e:
                db_session.rollback()
                historical_progress = None
                stats["errors"].append(f"Failed to start historical progress tracking: {e}")
        
        try:
            for page_target in page_targets:
                if max_new_articles is not None and stats["articles_saved"] >= int(max_new_articles):
                    stats["stopped_reason"] = "site_article_cap_reached"
                    break

                page_url = page_target["page_url"]
                stats["pages_scraped"] += 1

                html, page_engine, resolved_listing_url = self._fetch_listing_page_for_site(site_config, page_url)
                if not html:
                    error_msg = f"Failed to fetch page {page_url}: no backend returned valid content"
                    stats["errors"].append(error_msg)
                    continue
                if page_engine:
                    stats["scraper_engines_used"][page_engine] = stats["scraper_engines_used"].get(page_engine, 0) + 1
                    if page_engine == "selenium":
                        stats["selenium_fallbacks"] += 1

                listing_source_url = resolved_listing_url or page_url
                links = self._parse_links_from_page(html, listing_source_url)
                emitted_on_page = 0
                link_hash_pairs = [(link, self._get_url_hash(link)) for link in links]
                hashes = [item[1] for item in link_hash_pairs]
                existing_ledgers: Dict[str, ArticleUrlLedger] = {}
                if hashes:
                    for ledger in (
                        db_session.query(ArticleUrlLedger)
                        .filter(
                            ArticleUrlLedger.site_config_id == site_config.id,
                            ArticleUrlLedger.source_url_hash.in_(hashes),
                        )
                        .all()
                    ):
                        existing_ledgers[ledger.source_url_hash] = ledger

                pending_ledgers: List[ArticleUrlLedger] = []
                pending_records: List[Dict[str, Any]] = []
                pending_ledgers_by_hash: Dict[str, ArticleUrlLedger] = {}
                page_had_ledger_updates = False

                for link, url_hash in link_hash_pairs:
                    if max_new_articles is not None and (
                        stats["articles_saved"] + len(pending_ledgers)
                    ) >= int(max_new_articles):
                        stats["stopped_reason"] = "site_article_cap_reached"
                        break

                    stats["articles_found"] += 1

                    ledger_entry = existing_ledgers.get(url_hash)
                    if ledger_entry is not None:
                        now = datetime.now()
                        ledger_entry.last_seen_at = now
                        ledger_entry.last_scrape_date = now
                        ledger_entry.seen_count = int(ledger_entry.seen_count or 0) + 1
                        page_had_ledger_updates = True
                        stats["articles_skipped"] += 1
                        continue

                    pending_duplicate = pending_ledgers_by_hash.get(url_hash)
                    if pending_duplicate is not None:
                        now = datetime.now()
                        pending_duplicate.last_seen_at = now
                        pending_duplicate.last_scrape_date = now
                        pending_duplicate.seen_count = int(pending_duplicate.seen_count or 0) + 1
                        stats["articles_skipped"] += 1
                        continue

                    article_html, article_engine = self._fetch_page_for_site(site_config, link)
                    if not article_html:
                        error_msg = f"Failed to fetch article {link}: no backend returned valid content"
                        stats["errors"].append(error_msg)
                        continue
                    if article_engine:
                        stats["scraper_engines_used"][article_engine] = stats["scraper_engines_used"].get(article_engine, 0) + 1
                        if article_engine == "selenium":
                            stats["selenium_fallbacks"] += 1

                    article_data = self._extract_article(link, article_html)

                    if not article_data:
                        error_msg = f"Failed to extract article: {link}"
                        stats["errors"].append(error_msg)
                        continue
                    if not self._is_article_payload_usable(link, article_data):
                        stats["articles_skipped"] += 1
                        continue

                    parsed_date = self._get_article_date(article_data)
                    if parsed_date:
                        article_data["date_publish"] = parsed_date

                    scrape_date = article_data.get("scrape_date") or datetime.now()
                    date_download = article_data.get("date_download") or datetime.now()
                    source_domain = (urlparse(link).netloc or site_config.domain or "").lower()
                    content_hash = self._get_content_hash(
                        article_data.get("title"),
                        article_data.get("body"),
                    )

                    record = {
                        "url": link,
                        "canonical_url": article_data.get("canonical_url"),
                        "title": article_data.get("title"),
                        "body": article_data.get("body"),
                        "authors": article_data.get("authors"),
                        "section": article_data.get("section"),
                        "tags": article_data.get("tags"),
                        "date_publish": self._serialize_datetime(parsed_date or article_data.get("date_publish")),
                        "scrape_date": self._serialize_datetime(scrape_date),
                        "date_download": self._serialize_datetime(date_download),
                        "description": article_data.get("description"),
                        "image_url": article_data.get("image_url"),
                        "image_links": article_data.get("image_links"),
                        "extra_links": article_data.get("extra_links"),
                        "word_count": article_data.get("word_count"),
                        "reading_time_minutes": article_data.get("reading_time_minutes"),
                        "raw_metadata": article_data.get("raw_metadata"),
                        "content_hash": content_hash,
                        "source_url_hash": url_hash,
                        "source_domain": source_domain,
                        "language": article_data.get("language") or site_metadata.get("language"),
                        "scrape_status": "success",
                        "scraper_engine_used": article_engine,
                        "source_site_name": site_metadata.get("name"),
                        "source_site_url": site_metadata.get("url"),
                        "source_site_domain": site_metadata.get("domain") or source_domain,
                        "source_site_country": site_metadata.get("country"),
                        "source_site_language": site_metadata.get("language"),
                        "site": site_metadata,
                        "category": {
                            "site_category_id": page_target.get("category_id"),
                            "name": page_target.get("category_name"),
                            "url": page_target.get("category_url"),
                            "page_url": page_url,
                            "page_number": page_target.get("page_number"),
                        },
                    }

                    new_ledger_entry = ArticleUrlLedger(
                        site_config_id=site_config.id,
                        article_url=link,
                        source_url_hash=url_hash,
                        canonical_url=article_data.get("canonical_url"),
                        first_seen_at=datetime.now(),
                        last_seen_at=datetime.now(),
                        first_publish_at=parsed_date,
                        last_publish_at=parsed_date,
                        last_scrape_date=scrape_date,
                        seen_count=1,
                        total_records_emitted=1,
                        last_scraper_engine=article_engine,
                        content_hash=content_hash,
                        status="active",
                    )
                    pending_ledgers.append(new_ledger_entry)
                    pending_ledgers_by_hash[url_hash] = new_ledger_entry
                    pending_records.append(record)

                if pending_ledgers:
                    try:
                        db_session.add_all(pending_ledgers)
                        db_session.commit()
                        saved_count = len(pending_ledgers)
                        stats["articles_saved"] += saved_count
                        emitted_on_page += saved_count
                        stats["records"].extend(pending_records)
                        page_had_ledger_updates = False
                    except Exception as batch_error:
                        db_session.rollback()
                        stats["errors"].append(
                            f"Batch DB save failed for page {listing_source_url}; falling back per article: {batch_error}"
                        )
                        for ledger_entry, record in zip(pending_ledgers, pending_records):
                            try:
                                db_session.add(ledger_entry)
                                db_session.commit()
                                stats["articles_saved"] += 1
                                emitted_on_page += 1
                                stats["records"].append(record)
                            except Exception as db_error:
                                db_session.rollback()
                                stats["errors"].append(f"DB save failed for {record.get('url')}: {db_error}")

                if page_had_ledger_updates:
                    try:
                        db_session.commit()
                    except Exception as ledger_error:
                        db_session.rollback()
                        stats["errors"].append(
                            f"Ledger update commit failed for listing page {listing_source_url}: {ledger_error}"
                        )

                if max_new_articles is not None and stats["articles_saved"] >= int(max_new_articles):
                    stats["stopped_reason"] = "site_article_cap_reached"

                self._update_category_state(
                    spider_session,
                    site_config_id=site_config.id,
                    category_id=page_target.get("category_id"),
                    category_name=page_target.get("category_name"),
                    category_url=page_target.get("category_url") or site_config.url,
                    page_url=listing_source_url,
                    page_number=page_target.get("page_number"),
                    links_discovered=len(links),
                    records_emitted=emitted_on_page,
                    mode=mode,
                    chunk_id=chunk_id,
                )

                if historical_progress is not None:
                    try:
                        historical_progress.pages_scraped = stats["pages_scraped"]
                        historical_progress.articles_found = stats["articles_found"]
                        historical_progress.articles_saved = stats["articles_saved"]
                        historical_progress.articles_skipped = stats["articles_skipped"]
                        historical_progress.last_page_url = listing_source_url
                        historical_progress.error_count = len(stats["errors"])
                        historical_progress.last_error = stats["errors"][-1] if stats["errors"] else None
                        db_session.commit()
                    except Exception as progress_error:
                        db_session.rollback()
                        stats["errors"].append(f"Historical progress update failed: {progress_error}")

            self._export_results(site_config, stats["records"], export_csv, export_json)

            site_config.last_scraped = datetime.now()
            if stats["articles_saved"] > 0:
                site_config.last_successful_scrape = datetime.now()
            db_session.commit()

            if historical_progress is not None:
                try:
                    historical_progress.status = "complete" if not stats["errors"] else "partial"
                    historical_progress.pages_scraped = stats["pages_scraped"]
                    historical_progress.articles_found = stats["articles_found"]
                    historical_progress.articles_saved = stats["articles_saved"]
                    historical_progress.articles_skipped = stats["articles_skipped"]
                    historical_progress.error_count = len(stats["errors"])
                    historical_progress.last_error = stats["errors"][-1] if stats["errors"] else None
                    historical_progress.completed_at = datetime.now()
                    db_session.commit()
                except Exception as progress_finalize_error:
                    db_session.rollback()
                    stats["errors"].append(f"Failed to finalize historical progress: {progress_finalize_error}")
        except Exception as scrape_error:
            if historical_progress is not None:
                try:
                    historical_progress.status = "failed"
                    historical_progress.pages_scraped = stats["pages_scraped"]
                    historical_progress.articles_found = stats["articles_found"]
                    historical_progress.articles_saved = stats["articles_saved"]
                    historical_progress.articles_skipped = stats["articles_skipped"]
                    historical_progress.error_count = len(stats["errors"]) + 1
                    historical_progress.last_error = str(scrape_error)
                    historical_progress.completed_at = datetime.now()
                    db_session.commit()
                except Exception:
                    db_session.rollback()
            raise
        finally:
            self.verify_ssl = original_verify
        
        logger.info(f"Scraping complete for {site_config.name} ({mode}): "
                   f"{stats['pages_scraped']} pages, {stats['articles_saved']} new articles")
        
        if stats["errors"]:
            logger.warning(f"Site {site_config.name} had {len(stats['errors'])} errors during scrape")
        
        return stats
    
    def _reset_rate_limiter_state(self, url: str) -> None:
        """Reset rate limiter state for a specific URL's domain."""
        if self.rate_limiter and self.http_client:
            parsed = urlparse(url)
            domain = f"{parsed.scheme}://{parsed.netloc}"
            self.rate_limiter.reset_domain(domain)

    def _export_results(
        self,
        site_config: SiteConfig,
        records: List[Dict[str, Any]],
        export_csv: str = None,
        export_json: str = None
    ) -> None:
        """Export scraped results to file if paths provided."""
        from ..export.csv_export import CSVExporter
        from ..export.json_export import JSONExporter

        if export_csv:
            try:
                exporter = CSVExporter(export_csv)
                count = exporter.export_dict_list(records, overwrite=True)
                logger.info(f"Exported {count} records to CSV: {export_csv}")
            except Exception as e:
                logger.error(f"Failed to export CSV: {e}")
        
        if export_json:
            try:
                exporter = JSONExporter(export_json)
                count = exporter.export_dict_list(records, overwrite=True)
                logger.info(f"Exported {count} records to JSON: {export_json}")
            except Exception as e:
                logger.error(f"Failed to export JSON: {e}")

    def scrape_all_sites(
        self,
        db_session,
        mode: str = "incremental",
        active_only: bool = True,
        limit: Optional[int] = None,
        offset: int = 0,
        export_csv: str = None,
        export_json: str = None,
        enable_rate_limiting: bool = True,
        start_page: int = 1,
        end_page: Optional[int] = None,
        date_cutoff: Optional[datetime] = None,
        max_pages: Optional[int] = None,
        chunk_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Scrape all configured sites."""
        mode = self._normalize_mode(mode)
        from ..scraping.config_registry import SiteConfigRegistry
        
        registry = SiteConfigRegistry(db_session)
        sites = registry.list_sites(active_only=active_only, limit=limit, offset=offset)
        
        results = []
        for site in sites:
            try:
                stats = self.scrape_site(
                    site, db_session, mode=mode, export_csv=export_csv, 
                    export_json=export_json, enable_rate_limiting=enable_rate_limiting,
                    start_page=start_page, end_page=end_page,
                    date_cutoff=date_cutoff, max_pages=max_pages, chunk_id=chunk_id,
                )
                results.append(stats)
            except Exception as e:
                logger.error(f"Error scraping {site.name}: {e}")
                results.append({
                    "site_name": site.name,
                    "mode": mode,
                    "error": str(e),
                })
        
        return results


def scrape_single_site(
    db_session,
    site_url: str,
    export_csv: str = None,
    export_json: str = None,
    enable_rate_limiting: bool = True,
    mode: str = "incremental",
    chunk_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Convenience function to scrape a single site by URL."""
    from ..scraping.config_registry import SiteConfigRegistry
    
    registry = SiteConfigRegistry(db_session)
    site_config = registry.get_site_by_url(site_url)
    
    if not site_config:
        return {"error": f"Site not found: {site_url}"}
    
    with ScraperEngine(enable_rate_limiting=enable_rate_limiting) as engine:
        return engine.scrape_site(
            site_config,
            db_session,
            mode=mode,
            export_csv=export_csv,
            export_json=export_json,
            enable_rate_limiting=enable_rate_limiting,
            chunk_id=chunk_id,
        )
