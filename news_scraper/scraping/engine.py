"""Core scraper engine with prioritized backend fallback for Apify-style scraping."""

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any, Tuple
from urllib.parse import urljoin, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup

from ..validation.output_schema import ArticleData, ErrorLogEntry, ScrapingResult


class ScraplingScraper:
    """Primary scraper using Scrapling library for fast static content extraction."""
    
    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "DNT": "1",
        }
    
    def fetch(self, url: str) -> Optional[str]:
        """Fetch page using Scrapling's optimized static scraping."""
        try:
            import scrapling
            fetcher = scrapling.Fetcher()
            response = fetcher.get(url, headers=self.headers, timeout=self.timeout)
            return self._coerce_html_from_response(response)
        except ImportError:
            # Fallback to httpx if Scrapling not available
            client = httpx.Client(headers=self.headers, timeout=self.timeout)
            try:
                response = client.get(url)
                return response.text
            finally:
                client.close()
    
    def _coerce_html_from_response(self, response) -> Optional[str]:
        """Extract HTML text from various response types."""
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
                return value.strip() if value.strip() else None
            if isinstance(value, (bytes, bytearray)):
                decoded = value.decode("utf-8", errors="ignore")
                return decoded.strip() if decoded.strip() else None
        
        return None


class PydollScraper:
    """Backup scraper using Pydoll for JavaScript-heavy sites."""
    
    def __init__(self, timeout: int = 60):
        self.timeout = timeout
    
    def fetch(self, url: str) -> Optional[str]:
        """Fetch page using Pydoll browser automation."""
        try:
            import pydoll
            browser = pydoll.Browser(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=self.timeout * 1000)
            content = page.content()
            if hasattr(browser, "close"):
                browser.close()
            return content if isinstance(content, str) else None
        except ImportError:
            return None
        except Exception as e:
            print(f"Pydoll fetch failed for {url}: {e}")
            return None


class SeleniumScraper:
    """Fallback scraper using Selenium for heavily blocked sites."""
    
    def __init__(self, headless: bool = True, timeout: int = 120):
        self.headless = headless
        self.timeout = timeout
    
    def fetch(self, url: str) -> Optional[str]:
        """Fetch page using Selenium as last resort."""
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.common.by import By
            
            options = Options()
            options.add_argument("--headless")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option("useAutomationExtension", False)
            
            driver = webdriver.Chrome(options=options)
            try:
                driver.get(url)
                return driver.page_source
            finally:
                driver.quit()
        except ImportError:
            return None
        except Exception as e:
            print(f"Selenium fetch failed for {url}: {e}")
            return None


class ScraperEngine:
    """
    Core scraper engine with deterministic backend priority.
    
    Fallback order: Scrapling → Pydoll → Selenium
    Tracks which tool successfully extracted data and updates site catalog.
    """
    
    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.scrapling_scraper = ScraplingScraper(timeout=timeout)
        self.pydoll_scraper = PydollScraper(timeout=timeout * 2)
        self.selenium_scraper = SeleniumScraper(headless=True, timeout=timeout * 4)
    
    def fetch_with_fallback(self, url: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Fetch page using fallback pipeline.
        
        Returns:
            Tuple of (html_content, successful_tool_name)
        """
        # Try Scrapling first (fastest, best for standard bypasses)
        html = self.scrapling_scraper.fetch(url)
        if html and self._is_valid_html(html):
            return html, "Scrapling"
        
        # Backup 1: Pydoll (for Cloudflare and other bot-mitigation)
        html = self.pydoll_scraper.fetch(url)
        if html and self._is_valid_html(html):
            return html, "Pydoll"
        
        # Fallback: Selenium (last resort, fully headed or heavily stealthed)
        html = self.selenium_scraper.fetch(url)
        if html and self._is_valid_html(html):
            return html, "Selenium"
        
        return None, None
    
    def _is_valid_html(self, html: str) -> bool:
        """Check if HTML content appears valid."""
        if not html or not html.strip():
            return False
        
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(" ", strip=True)
        
        # Very short responses are usually placeholders or blocks
        if len(text) < 100:
            return False
        
        # Check for common block indicators
        lower_text = text.lower()
        block_indicators = [
            "captcha", "access denied", "forbidden", "under construction",
            "coming soon", "maintenance", "attention required"
        ]
        if any(indicator in lower_text for indicator in block_indicators):
            return False
        
        return True
    
    def compute_url_hash(self, url: str) -> str:
        """Generate MD5 hash of URL for deduplication."""
        return hashlib.md5(url.encode("utf-8")).hexdigest()
    
    def create_article_data(
        self,
        raw_data: dict,
        site_name: str,
        scraping_tool: str = "Scrapling",
        fallback_chain: List[str] = None,
        category: Optional[str] = None
    ) -> ArticleData:
        """Create ArticleData from raw scraped data."""
        if fallback_chain is None:
            fallback_chain = []
        
        url_hash = self.compute_url_hash(raw_data.get("article_url", ""))
        
        return ArticleData(
            article_id=str(uuid.uuid4()),
            scraped_at=datetime.now(timezone.utc).isoformat(),
            site_name=site_name,
            url_hash=url_hash,
            article_url=raw_data.get("article_url", ""),
            article_title=raw_data.get("article_title", ""),
            author=raw_data.get("author"),
            date_published=raw_data.get("date_published"),
            tags=raw_data.get("tags"),
            main_image_url=raw_data.get("main_image_url"),
            seo_description=raw_data.get("seo_description"),
            scraping_tool=scraping_tool,
            fallback_chain=fallback_chain,
            category=category
        )
    
    def create_error_log(
        self,
        site_name: str,
        url_hash: str,
        article_url: str,
        error_type: str,
        error_message: str,
        fallback_attempts: List[dict] = None,
        final_tool_used: Optional[str] = None,
        retry_count: int = 0
    ) -> ErrorLogEntry:
        """Create ErrorLogEntry for failed scraping attempts."""
        if fallback_attempts is None:
            fallback_attempts = []
        
        return ErrorLogEntry(
            logged_at=datetime.now(timezone.utc).isoformat(),
            site_name=site_name,
            url_hash=url_hash,
            article_url=article_url,
            error_type=error_type,
            error_message=error_message,
            fallback_attempts=fallback_attempts,
            final_tool_used=final_tool_used,
            retry_count=retry_count
        )
    
    def scrape_article(
        self,
        url: str,
        site_name: str,
        selectors: dict,
        historic_cutoff_date: Optional[datetime] = None
    ) -> ScrapingResult:
        """
        Scrape a single article with fallback pipeline.
        
        Args:
            url: Article URL to scrape
            site_name: Name of the site for catalog tracking
            selectors: SelectorMap configuration for this site
            historic_cutoff_date: Optional date cutoff for historic scraping
            
        Returns:
            ScrapingResult containing either success data or error log
        """
        fallback_chain = []
        fallback_attempts = []
        
        # Fetch page with fallback pipeline
        html, tool_used = self.fetch_with_fallback(url)
        
        if not html:
            # All tools failed - create error log
            url_hash = self.compute_url_hash(url)
            error_entry = self.create_error_log(
                site_name=site_name,
                url_hash=url_hash,
                article_url=url,
                error_type="Timeout",
                error_message="All scraping tools failed to fetch page",
                fallback_attempts=fallback_attempts,
                final_tool_used=None,
                retry_count=len(fallback_chain)
            )
            return ScrapingResult.error_result(error_entry)
        
        # Extract article data using selectors
        try:
            article_data = {
                "article_url": url,
                "article_title": self._extract_text(selectors.get("article_title", {}), html),
                "author": self._extract_text(selectors.get("author", {}), html) if selectors.get("author") else None,
                "date_published": self._extract_date(selectors.get("date_published", {}), html),
                "tags": self._extract_tags(selectors.get("tags", {}), html) if selectors.get("tags") else None,
                "main_image_url": self._extract_text(selectors.get("main_image_url", {}), html) if selectors.get("main_image_url") else None,
                "seo_description": self._extract_seo_description(html),
            }
            
            # Normalize date to ISO 8601 if present
            if article_data["date_published"]:
                article_data["date_published"] = self._normalize_date_to_iso8601(
                    article_data["date_published"],
                    historic_cutoff_date
                )
            
            # Check for historic cutoff
            if historic_cutoff_date and article_data["date_published"]:
                from datetime import datetime as dt
                parsed_date = dt.fromisoformat(article_data["date_published"].replace("Z", "+00:00"))
                if parsed_date.replace(tzinfo=None) < historic_cutoff_date.replace(tzinfo=timezone.utc):
                    # Article is too old, skip it
                    url_hash = self.compute_url_hash(url)
                    error_entry = self.create_error_log(
                        site_name=site_name,
                        url_hash=url_hash,
                        article_url=url,
                        error_type="HistoricCutoff",
                        error_message=f"Article date {article_data['date_published']} is before cutoff {historic_cutoff_date}",
                        fallback_attempts=fallback_attempts,
                        final_tool_used=tool_used,
                        retry_count=len(fallback_chain)
                    )
                    return ScrapingResult.error_result(error_entry)
            
            # Create success result
            article_data["scraped_at"] = datetime.now(timezone.utc).isoformat()
            fallback_chain.append(tool_used)
            
            result = self.create_article_data(
                raw_data=article_data,
                site_name=site_name,
                scraping_tool=tool_used,
                fallback_chain=fallback_chain
            )
            
            return ScrapingResult.success_result(result)
            
        except Exception as e:
            # Extraction failed - log error
            url_hash = self.compute_url_hash(url)
            error_entry = self.create_error_log(
                site_name=site_name,
                url_hash=url_hash,
                article_url=url,
                error_type="SelectorMissing",
                error_message=f"Failed to extract article data: {str(e)}",
                fallback_attempts=fallback_attempts,
                final_tool_used=tool_used,
                retry_count=len(fallback_chain)
            )
            return ScrapingResult.error_result(error_entry)
    
    def _extract_text(self, selector_config: dict, html: str) -> Optional[str]:
        """Extract text using CSS selector."""
        try:
            soup = BeautifulSoup(html, "html.parser")
            selector = selector_config.get("selector", "")
            
            element = soup.select_one(selector)
            if element:
                return element.get_text(strip=True)
            
            # Try XPath alternative
            xpath = selector_config.get("xpath_alternative", "")
            if xpath:
                elements = soup.select(xpath)
                if elements:
                    return elements[0].get_text(strip=True)
            
            # Try fallback selector
            fallback = selector_config.get("fallback_selector", "")
            if fallback:
                element = soup.select_one(fallback)
                if element:
                    return element.get_text(strip=True)
            
            return None
        except Exception:
            return None
    
    def _extract_date(self, selector_config: dict, html: str) -> Optional[str]:
        """Extract and parse date from article."""
        try:
            soup = BeautifulSoup(html, "html.parser")
            selector = selector_config.get("selector", "")
            
            element = soup.select_one(selector)
            if not element:
                return None
            
            # Check for datetime attribute
            if element.has_attr("datetime"):
                return element["datetime"]
            
            # Try to parse text content
            text = element.get_text(strip=True)
            if not text:
                return None
            
            # Try common date formats
            from datetime import datetime as dt
            from dateutil import parser
            
            for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y", "%b %d, %Y", "%B %d, %Y"]:
                try:
                    parsed = dt.strptime(text.strip(), fmt)
                    return parsed.isoformat()
                except ValueError:
                    continue
            
            # Try dateutil parser as last resort
            try:
                parsed = parser.parse(text.strip(), fuzzy=True)
                return parsed.isoformat()
            except Exception:
                pass
            
            return None
        except Exception:
            return None
    
    def _extract_tags(self, selector_config: dict, html: str) -> Optional[List[str]]:
        """Extract tags from article."""
        try:
            soup = BeautifulSoup(html, "html.parser")
            selector = selector_config.get("selector", "")
            
            elements = soup.select(selector)
            if not elements:
                return None
            
            tags = []
            for element in elements:
                text = element.get_text(strip=True)
                if text:
                    tags.append(text)
            
            return tags[:10]  # Limit to 10 tags
        except Exception:
            return None
    
    def _extract_seo_description(self, html: str) -> Optional[str]:
        """Extract SEO description from meta tags."""
        try:
            soup = BeautifulSoup(html, "html.parser")
            
            # Try meta description first
            meta_desc = soup.find("meta", attrs={"name": "description"})
            if meta_desc and meta_desc.get("content"):
                return meta_desc["content"]
            
            # Try og:description
            og_desc = soup.find("meta", attrs={"property": "og:description"})
            if og_desc and og_desc.get("content"):
                return og_desc["content"]
            
            # Try twitter:description
            tw_desc = soup.find("meta", attrs={"name": "twitter:description"})
            if tw_desc and tw_desc.get("content"):
                return tw_desc["content"]
            
            return None
        except Exception:
            return None
    
    def _normalize_date_to_iso8601(self, date_str: str, cutoff_date: Optional[datetime] = None) -> Optional[str]:
        """Normalize date string to ISO 8601 format."""
        try:
            from datetime import datetime as dt
            from dateutil import parser
            
            # Try parsing with various formats
            for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y", "%b %d, %Y", "%B %d, %Y"]:
                try:
                    parsed = dt.strptime(date_str.strip(), fmt)
                    return parsed.isoformat()
                except ValueError:
                    continue
            
            # Try dateutil parser
            try:
                parsed = parser.parse(date_str.strip(), fuzzy=True)
                return parsed.isoformat()
            except Exception:
                pass
            
            return None
        except Exception:
            return None
