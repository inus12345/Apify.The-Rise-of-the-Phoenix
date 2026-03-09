"""Core scraper engine using Scrapling for efficient web scraping with Selenium fallback."""
from typing import List, Dict, Optional, Any
from datetime import datetime
import hashlib
import time

import httpx
from bs4 import BeautifulSoup

from ..database.models import SiteConfig, ScrapedArticle
from ..core.config import settings, get_logger
from ..extraction.article_extractor import ArticleExtractor
from ..policies.rate_limiter import RateLimiter, DomainThrottler
from ..policies.retry_policy import RetryPolicy
from .selenium_fallback import SeleniumScraper


logger = get_logger(__name__)


class ScraperEngine:
    """
    Core scraper engine using Scrapling for efficient web scraping with Selenium fallback.
    
    Features:
    - URL-based deduplication via MD5 hash
    - Support for static and JavaScript-rendered sites (Selenium fallback)
    - Batch processing
    - Rate limiting for polite scraping
    - Retry policy with exponential backoff
    - Error handling with retry logic
    - Configurable selectors via ArticleExtractor
    """
    
    def __init__(
        self,
        batch_size: int = None,
        timeout: int = None,
        max_retries: int = None,
        use_custom_selectors: bool = False,
        verify_ssl: bool = True,
        enable_rate_limiting: bool = True,
        min_delay_between_requests: float = 1.0
    ):
        self.batch_size = batch_size or settings.DEFAULT_BATCH_SIZE
        self.timeout = timeout or settings.SCRAPING_TIMEOUT
        self.max_retries = max_retries or settings.MAX_RETRIES
        self.user_agent = settings.USER_AGENT
        
        # HTTP client for Scrapling-style requests
        self.http_client: Optional[httpx.Client] = None
        
        # Custom selector extractor (optional)
        self.extractor: Optional[ArticleExtractor] = (
            ArticleExtractor() if use_custom_selectors else None
        )
        
        # SSL verification setting
        self.verify_ssl = verify_ssl
        
        # Rate limiting
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
        headers = {"User-Agent": self.user_agent}
        
        # Configure SSL verification based on settings
        verify = True if self.verify_ssl else False
        
        self.http_client = httpx.Client(
            headers=headers,
            timeout=self.timeout,
            follow_redirects=True,
            verify=verify
        )
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        if self.http_client:
            self.http_client.close()
    
    def _rate_limit_wait(self, url: str) -> float:
        """Apply rate limiting before a request."""
        if not self.enable_rate_limiting or self.rate_limiter is None:
            return 0.0
        
        return self.rate_limiter.wait_if_needed(url)
    
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
    
    def _fetch_page(self, url: str, method: str = "httpx") -> Optional[str]:
        """Fetch a page using HTTP or Selenium fallback."""
        
        # Apply rate limiting for HTTP requests
        if method == "httpx":
            wait_time = self._rate_limit_wait(url)
            if wait_time > 0:
                logger.debug(f"Rate limited. Waiting {wait_time:.2f}s before fetching {url}")
            
            def fetch():
                """Inner function for retry wrapper."""
                response = self.http_client.get(url)
                response.raise_for_status()
                return response.text
            
            try:
                result = self.retry_policy.execute_with_callback(
                    fetch,
                    name=url[:50] + "..." if len(url) > 50 else url
                )
                
                self._record_success(url)
                return result
            
            except Exception as e:
                self._record_error(url)
                logger.error(f"Failed to fetch {url} after retries: {e}")
                return None
        
        # Use Selenium for JS-heavy sites or when HTTP fails
        else:
            try:
                with SeleniumScraper(headless=True, timeout=30) as selenium_scraper:
                    html = selenium_scraper.fetch_page(url)
                    
                    if html:
                        logger.info(f"Selenium fallback successful for {url}")
                        return html
                    
            except Exception as e:
                logger.error(f"Selenium fallback failed for {url}: {e}")
            
            return None
    
    def _parse_links_from_page(self, html: str, base_url: str) -> List[str]:
        """Parse article links from a page's HTML content."""
        soup = BeautifulSoup(html, "html.parser")
        links = []
        
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            
            # Resolve relative URLs
            if href.startswith("/"):
                from urllib.parse import urlparse
                parsed = urlparse(base_url)
                href = f"{parsed.scheme}://{parsed.netloc}{href}"
            elif not href.startswith(("http://", "https://")):
                continue
            
            links.append(href)
        
        return list(set(links))  # Remove duplicates
    
    def _extract_article(self, url: str, html: str, method: str = "httpx") -> Optional[Dict[str, Any]]:
        """Extract article data from HTML content."""
        try:
            if self.extractor:
                return self.extractor.extract(url, html)
            
            soup = BeautifulSoup(html, "html.parser")
            
            article_content = self._find_element(
                soup,
                ["article", ".article", "#article", "main", ".content"]
            )
            
            if not article_content:
                # Try body as fallback
                article_content = soup.body or soup
            
            title = self._find_text(
                article_content,
                ["h1", ".title", "#title", "article h1"]
            )
            if not title:
                title_elem = soup.find("title")
                title = title_elem.text.strip() if title_elem else ""
            
            paragraphs = article_content.find_all("p")
            body = "\n\n".join(p.get_text().strip() for p in paragraphs)
            
            if not body or len(body) < 100:
                # Try to find any text content
                body = soup.get_text()[:5000]  # Limit to first 5000 chars
            
            date_published = self._find_date(
                article_content,
                ["time", ".date", "#date", "[datetime]"]
            )
            
            authors_elem = self._find_element(
                article_content,
                [".author", "authors", ".byline"]
            )
            authors = authors_elem.get_text().strip() if authors_elem else ""
            
            image_elem = article_content.find("img")
            image_url = image_elem["src"] if image_elem and image_elem.has_attr("src") else ""
            
            return {
                "url": url,
                "source_url_hash": self._get_url_hash(url),
                "title": title,
                "body": body.strip(),
                "authors": authors,
                "date_publish": date_published,
                "image_url": image_url,
                "scrape_method": method,  # Track which method was used
                "scrape_status": "success",
            }
        
        except Exception as e:
            logger.error(f"Error extracting article from {url}: {e}")
            return None
    
    def _find_element(self, soup: BeautifulSoup, selectors: List[str]):
        """Try multiple CSS selectors and return first match."""
        for selector in selectors:
            elem = soup.select_one(selector)
            if elem:
                return elem
        return None
    
    def _find_text(self, element, selectors: List[str]) -> Optional[str]:
        """Find text content using multiple selectors."""
        for selector in selectors:
            elem = element.select_one(selector)
            if elem and elem.get_text():
                return elem.get_text().strip()
        return None
    
    def _find_date(self, soup: BeautifulSoup, selectors: List[str]) -> Optional[str]:
        """Try to find date in various formats."""
        for selector in selectors:
            elem = soup.select_one(selector)
            if elem:
                if elem.has_attr("datetime"):
                    return elem["datetime"]
                text = elem.get_text()
                if text:
                    return text
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
        
        date_str = str(article_data["date_publish"])
        
        if hasattr(date_str, "strftime"):
            date_str = date_str.strftime("%Y-%m-%d")
        
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
        if not site_config.category_url_pattern:
            return [site_config.url]
        
        urls = []
        pattern = site_config.category_url_pattern
        
        if mode == "incremental":
            num_pages = min(
                site_config.num_pages_to_scrape,
                max_pages or 100
            )
            for page_num in range(start_page, start_page + num_pages):
                url = pattern.replace("{page}", str(page_num))
                urls.append(url)
        
        elif mode == "backfill":
            if max_pages is None:
                max_pages = site_config.num_pages_to_scrape * 5
            
            for page_num in range(start_page, start_page + max_pages):
                url = pattern.replace("{page}", str(page_num))
                
                if date_cutoff:
                    try:
                        html = self._fetch_page(url, "httpx")
                        if html:
                            date_str = self._extract_page_date(html, site_config.date_selector or "")
                            if date_str:
                                parsed_date = self._parse_date_from_selector(date_str)
                                if parsed_date < date_cutoff:
                                    urls.append(url)
                    except Exception:
                        pass
                
                else:
                    urls.append(url)
        
        return urls

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
        soup = BeautifulSoup(html, "html.parser")
        
        # Check for loading states
        body_text = soup.get_text()
        
        load_indicators = ["loading", "advertising", "ad space", "under construction"]
        for indicator in load_indicators:
            if indicator.lower() in body_text.lower():
                return True
        
        # Check for placeholder content
        no_content_indicators = [
            "content will be available soon",
            "coming soon",
            "this page is unavailable",
            "site under maintenance"
        ]
        for indicator in no_content_indicators:
            if indicator.lower() in body_text.lower():
                return True
        
        # Check for very short content
        if len(body_text.strip()) < 200 and soup.find("body"):
            return True
        
        return False

    def scrape_site(
        self,
        site_config: SiteConfig,
        db_session,
        mode: str = "incremental",
        export_csv: str = None,
        export_json: str = None,
        verify_ssl: bool = True,
        enable_rate_limiting: bool = None,
        start_page: int = 1,
        end_page: Optional[int] = None,
        date_cutoff: Optional[datetime] = None,
        max_pages: Optional[int] = None,
        job_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Scrape a configured website with incremental or backfill mode."""
        stats = {
            "site_name": site_config.name,
            "url": site_config.url,
            "mode": mode,
            "pages_scraped": 0,
            "articles_found": 0,
            "articles_saved": 0,
            "articles_skipped": 0,
            "errors": [],
            "selenium_fallbacks": 0,
        }
        
        scrape_run = None
        if job_id:
            from ..database.models import ScrapeRun
            try:
                scrape_run = db_session.query(ScrapeRun).filter(
                    ScrapeRun.site_config_id == site_config.id,
                    ScrapeRun.status.in_(["running", "partial"])
                ).first()
                
                if scrape_run and scrape_run.status == "partial":
                    stats["pages_scraped"] = scrape_run.pages_scraped
                    stats["articles_found"] = scrape_run.articles_found
                    logger.info(f"Resuming job {job_id} for {site_config.name}")
            except Exception as e:
                logger.warning(f"Could not load resume data: {e}")
        
        try:
            original_verify = self.verify_ssl
            self.verify_ssl = verify_ssl
            
            if self.rate_limiter:
                self._reset_rate_limiter_state()
            
            page_urls = self._get_page_urls(
                site_config,
                mode=mode,
                start_page=start_page,
                end_page=end_page,
                date_cutoff=date_cutoff,
                max_pages=max_pages
            )
            
            for page_url in page_urls:
                stats["pages_scraped"] += 1
                
                # Try HTTP first, then Selenium fallback
                html = self._fetch_page(page_url, "httpx")
                
                if not html or self._detect_content_missing(html):
                    error_msg = f"Failed to fetch page {page_url}: content missing or loading"
                    stats["errors"].append(error_msg)
                    
                    # Try Selenium fallback
                    try:
                        logger.info(f"Selenium fallback for {site_config.name}: {page_url}")
                        html = self._fetch_page(page_url, "selenium")
                        
                        if html and not self._detect_content_missing(html):
                            stats["selenium_fallbacks"] += 1
                            logger.info(f"Selenium fallback succeeded for {page_url}")
                        else:
                            error_msg += " (Selenium also failed)"
                    except Exception as e:
                        logger.error(f"Selenium fallback failed: {e}")
                
                if not html:
                    continue
                
                links = self._parse_links_from_page(html, site_config.url)
                
                for link in links:
                    stats["articles_found"] += 1
                    
                    url_hash = self._get_url_hash(link)
                    existing = db_session.query(ScrapedArticle).filter(
                        ScrapedArticle.source_url_hash == url_hash
                    ).first()
                    
                    if existing:
                        stats["articles_skipped"] += 1
                        continue
                    
                    # Try HTTP extraction first, then Selenium fallback for content
                    article_html = self._fetch_page(link, "httpx")
                    
                    if not article_html or self._detect_content_missing(article_html):
                        error_msg = f"Failed to fetch article {link}: content missing"
                        stats["errors"].append(error_msg)
                        
                        # Try Selenium fallback for articles
                        try:
                            logger.debug(f"Selenium fallback for article: {link}")
                            article_html = self._fetch_page(link, "selenium")
                            
                            if article_html and not self._detect_content_missing(article_html):
                                stats["selenium_fallbacks"] += 1
                                link_scrape_method = "selenium"
                                logger.info(f"Selenium fallback succeeded for article: {link}")
                            else:
                                error_msg += " (Selenium also failed)"
                        except Exception as e:
                            logger.error(f"Selenium fallback failed: {e}")
                            continue
                    
                    if not article_html:
                        continue
                    
                    # Extract with specified method
                    article_data = self._extract_article(link, article_html)
                    
                    if not article_data:
                        error_msg = f"Failed to extract article: {link}"
                        stats["errors"].append(error_msg)
                        continue
                    
                    parsed_date = self._get_article_date(article_data)
                    if parsed_date:
                        article_data["date_publish"] = parsed_date.strftime("%Y-%m-%d")
                    
                    scraped_article = ScrapedArticle(
                        site_config_id=site_config.id,
                        **article_data
                    )
                    
                    db_session.add(scraped_article)
                    db_session.commit()
                    
                    stats["articles_saved"] += 1
            
            self._export_results(site_config, db_session, export_csv, export_json)
        
        except Exception as e:
            logger.error(f"Error scraping {site_config.name}: {e}")
        
        finally:
            self.verify_ssl = original_verify
            
            site_config.last_scraped = datetime.now()
            
            if scrape_run:
                articles_count = db_session.query(ScrapedArticle).filter(
                    ScrapedArticle.site_config_id == site_config.id
                ).count()
                
                scrape_run.pages_scraped = stats["pages_scraped"]
                scrape_run.articles_found = stats["articles_found"]
                scrape_run.articles_saved = stats["articles_saved"]
                scrape_run.articles_skipped = stats["articles_skipped"]
                scrape_run.error_count = len(stats["errors"])
                if stats["errors"]:
                    scrape_run.last_error = stats["errors"][-1]
                
                site_config.last_successful_scrape = datetime.now()
            
            db_session.commit()
        
        logger.info(f"Scraping complete for {site_config.name} ({mode}): "
                   f"{stats['pages_scraped']} pages, {stats['articles_saved']} new articles, "
                   f"{stats['selenium_fallbacks']} Selenium fallbacks used")
        
        if stats["errors"]:
            logger.warning(f"Site {site_config.name} had {len(stats['errors'])} errors during scrape")
        
        return stats
    
    def _reset_rate_limiter_state(self) -> None:
        """Reset rate limiter state for this site's domain."""
        if self.rate_limiter and self.http_client:
            from urllib.parse import urlparse
            parsed = urlparse(site_config.url)
            domain = f"{parsed.scheme}://{parsed.netloc}"
            self.rate_limiter.reset_domain(domain)

    def _export_results(
        self,
        site_config: SiteConfig,
        db_session,
        export_csv: str = None,
        export_json: str = None
    ) -> None:
        """Export scraped results to file if paths provided."""
        from ..export.csv_export import CSVExporter
        from ..export.json_export import JSONExporter
        
        articles = db_session.query(ScrapedArticle).filter(
            ScrapedArticle.site_config_id == site_config.id
        ).all()
        
        if export_csv:
            try:
                exporter = CSVExporter(export_csv)
                count = exporter.export_articles(articles, overwrite=True)
                logger.info(f"Exported {count} articles to CSV: {export_csv}")
            except Exception as e:
                logger.error(f"Failed to export CSV: {e}")
        
        if export_json:
            try:
                exporter = JSONExporter(export_json)
                count = exporter.export_articles(articles, overwrite=True)
                logger.info(f"Exported {count} articles to JSON: {export_json}")
            except Exception as e:
                logger.error(f"Failed to export JSON: {e}")

    def scrape_all_sites(
        self,
        db_session,
        mode: str = "incremental",
        active_only: bool = True,
        export_csv: str = None,
        export_json: str = None,
        verify_ssl: bool = True,
        enable_rate_limiting: bool = True,
        job_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Scrape all configured sites."""
        from ..scraping.config_registry import SiteConfigRegistry
        
        registry = SiteConfigRegistry(db_session)
        sites = registry.list_sites(active_only=active_only)
        
        results = []
        for site in sites:
            try:
                stats = self.scrape_site(
                    site, db_session, mode=mode, export_csv=export_csv, 
                    export_json=export_json, verify_ssl=verify_ssl, 
                    enable_rate_limiting=enable_rate_limiting, job_id=job_id
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
    verify_ssl: bool = True,
    enable_rate_limiting: bool = True,
    mode: str = "incremental",
) -> Dict[str, Any]:
    """Convenience function to scrape a single site by URL."""
    from ..scraping.config_registry import SiteConfigRegistry
    
    registry = SiteConfigRegistry(db_session)
    site_config = registry.get_site_by_url(site_url)
    
    if not site_config:
        return {"error": f"Site not found: {site_url}"}
    
    with ScraperEngine(
        verify_ssl=verify_ssl,
        enable_rate_limiting=enable_rate_limiting
    ) as engine:
        return engine.scrape_site(site_config, db_session, mode=mode)