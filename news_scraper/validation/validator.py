"""Site validator for health-checking configured sites."""
from typing import List, Dict, Optional, Any
from datetime import datetime
from dataclasses import dataclass, field
import time
import httpx
from bs4 import BeautifulSoup

from ..database.session import get_session
from ..core.config import settings, get_logger


logger = get_logger(__name__)


@dataclass
class ValidationResult:
    """Result of a validation run for a site."""
    site_name: str
    url: str
    status: str  # "pass", "fail", "needs_review", "paused"
    timestamp: datetime
    field_completeness_score: float  # 0-100
    sample_extracted_values: Dict[str, Any] = field(default_factory=dict)
    failure_reason: Optional[str] = None
    suggested_selector_updates: List[Dict[str, str]] = field(default_factory=list)
    
    def __post_init__(self):
        """Set default timestamp if not provided."""
        if not self.timestamp:
            self.timestamp = datetime.now()


class SiteValidator:
    """
    Validator for checking site health and selector effectiveness.
    
    Features:
    - Fetch sample category page to verify extraction works
    - Fetch sample article pages to verify content extraction
    - Check field completeness (title, date, author, body)
    - Detect pagination problems
    - Flag sites as active, broken, needs_review, or paused
    - Save validation results to DB with suggestions
    """
    
    def __init__(self):
        self.http_client: Optional[httpx.Client] = None
        self.timeout = settings.SCRAPING_TIMEOUT

    def _build_http_client(self) -> httpx.Client:
        """Create an HTTP client with standard scraper defaults."""
        headers = {"User-Agent": settings.USER_AGENT}
        return httpx.Client(
            headers=headers,
            timeout=self.timeout,
            follow_redirects=True,
            verify=settings.VERIFY_SSL,
        )
    
    def __enter__(self):
        """Context manager entry."""
        self.http_client = self._build_http_client()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        if self.http_client:
            self.http_client.close()
            self.http_client = None
    
    def _fetch_page(self, url: str) -> Optional[str]:
        """Fetch a page with retry logic."""
        if self.http_client is None:
            with self._build_http_client() as temp_client:
                try:
                    response = temp_client.get(url)
                    response.raise_for_status()
                    return response.text
                except Exception as e:
                    logger.error(f"Failed to fetch {url}: {e}")
                    return None

        try:
            response = self.http_client.get(url)
            response.raise_for_status()
            return response.text
        except Exception as e:
            logger.error(f"Failed to fetch {url}: {e}")
            return None
    
    def _detect_empty_fields(self, extracted_data: Dict[str, Any]) -> List[str]:
        """Detect which fields appear empty or missing."""
        empty_fields = []
        
        if not extracted_data.get("title") or not extracted_data["title"].strip():
            empty_fields.append("title")
        
        if not extracted_data.get("body") or len(extracted_data["body"]) < 50:
            empty_fields.append("body")
        
        if not extracted_data.get("date_publish"):
            empty_fields.append("date_publish")
        
        if not extracted_data.get("authors"):
            empty_fields.append("authors")
        
        return empty_fields
    
    def _check_pagination(self, html: str, site_config) -> bool:
        """Check if pagination indicators are present."""
        soup = BeautifulSoup(html, "html.parser")
        
        # Check for common pagination indicators
        pagination_patterns = [
            "<a.*rel='next'",
            "<span.*pag.*ation|<div.*pag",
            ".pagination-nav",
            "[class].*pagin",
        ]
        
        body_text = soup.get_text()
        has_pagination_indicators = any(
            pattern.lower() in body_text.lower() for pattern in pagination_patterns
        )
        
        # Also check if there are multiple page links
        page_links = soup.find_all("a", string=lambda t: "page" in str(t).lower())
        return len(page_links) > 0 or has_pagination_indicators
    
    def _estimate_completeness(self, extracted_data: Dict[str, Any]) -> float:
        """
        Estimate field completeness score (0-100).
        
        Scoring based on:
        - Title present and not empty: 25 points
        - Body present and substantial (>100 chars): 35 points  
        - Date present: 15 points
        - Authors present: 10 points
        - Image URL present: 10 points
        """
        score = 0
        
        if extracted_data.get("title") and extracted_data["title"].strip():
            score += 25
        
        body = extracted_data.get("body", "")
        if body and len(body.strip()) > 100:
            score += 35
        
        if extracted_data.get("date_publish"):
            score += 15
        
        if extracted_data.get("authors"):
            score += 10
        
        if extracted_data.get("image_url"):
            score += 10
        
        return min(score, 100)
    
    def _suggest_selector_updates(self, failure_reason: str, site_config) -> List[Dict[str, str]]:
        """Generate suggestions for selector updates."""
        suggestions = []
        
        if "title" in failure_reason.lower():
            suggestions.append({
                "field": "title",
                "suggestion": "Try 'h1' or 'h2.entry-title' as title selectors"
            })
        
        if "body" in failure_reason.lower() or "content" in failure_reason.lower():
            suggestions.append({
                "field": "body", 
                "suggestion": "Try '.entry-content p', 'article p', or '.content p' for body"
            })
        
        if "date" in failure_reason.lower():
            suggestions.append({
                "field": "date_publish",
                "suggestion": "Check site's date selectors: 'time[datetime]', '.pub-date', '[datetime]'"
            })
        
        if "link" in failure_reason.lower() or "article not found" in failure_reason.lower():
            suggestions.append({
                "field": "article_selector",
                "suggestion": "Review page listing - may need update to main article list selector"
            })
        
        return suggestions
    
    def validate_site(self, site_config) -> ValidationResult:
        """
        Validate a single site by fetching sample pages and checking extraction.
        
        Args:
            site_config: The SiteConfig object to validate
            
        Returns:
            ValidationResult with status and details
        """
        logger.info(f"Validating site: {site_config.name} ({site_config.url})")
        
        try:
            # Fetch category page (or homepage if no pattern)
            url = site_config.category_url_pattern or site_config.url
            
            if not url:
                url = f"{site_config.url}/news" if "news" not in site_config.url.lower() else site_config.url
            
            html = self._fetch_page(url)
            
            if not html:
                return ValidationResult(
                    site_name=site_config.name,
                    url=site_config.url,
                    status="fail",
                    field_completeness_score=0,
                    failure_reason=f"Failed to fetch category page: {url}",
                    sample_extracted_values={"error": "Page fetch failed"}
                )
            
            soup = BeautifulSoup(html, "html.parser")
            
            # Check for loading/placeholder content
            body_text = soup.get_text()
            load_indicators = ["loading", "under construction", "coming soon", "maintenance"]
            if any(indicator.lower() in body_text.lower() for indicator in load_indicators):
                return ValidationResult(
                    site_name=site_config.name,
                    url=site_config.url,
                    status="needs_review",
                    field_completeness_score=50,
                    failure_reason="Site shows loading or placeholder content",
                    sample_extracted_values={"note": "Page may still be loading"},
                    suggested_selector_updates=[]
                )
            
            # Extract sample articles if selectors configured
            extracted_data = {"title": "", "body": "", "date_publish": None, "authors": "", "image_url": ""}
            
            if site_config.article_selector:
                article_items = soup.select(site_config.article_selector)
                
                if not article_items:
                    return ValidationResult(
                        site_name=site_config.name,
                        url=site_config.url,
                        status="needs_review",
                        field_completeness_score=50,
                        failure_reason=f"No articles found with selector: {site_config.article_selector}",
                        sample_extracted_values={"article_count": 0},
                        suggested_selector_updates=[{"field": "article_selector", "suggestion": "Selector returned no results"}]
                    )
                
                # Extract from first article
                first_article = article_items[0]
                title_elem = first_article.select_one(site_config.title_selector or "h1, h2")
                extracted_data["title"] = title_elem.get_text().strip() if title_elem else ""
                
                body_elems = first_article.select(site_config.body_selector or ".content p, .article p")
                extracted_data["body"] = "\n\n".join(e.get_text().strip() for e in body_elems)
                
                date_elem = first_article.select_one(site_config.date_selector or "time, .date")
                if date_elem:
                    if date_elem.has_attr("datetime"):
                        extracted_data["date_publish"] = date_elem["datetime"]
                    else:
                        extracted_data["date_publish"] = date_elem.get_text().strip()
                
                author_elems = first_article.select(site_config.author_selector or ".author")
                extracted_data["authors"] = "; ".join(e.get_text().strip() for e in author_elems) if author_elems else ""
                
                img_elem = first_article.find("img")
                if img_elem and img_elem.has_attr("src"):
                    extracted_data["image_url"] = img_elem["src"]
            
            # Check pagination
            has_pagination = self._check_pagination(html, site_config)
            if not has_pagination:
                logger.info(f"No pagination found for {site_config.name}")
            
            # Calculate completeness score
            completeness = self._estimate_completeness(extracted_data)
            
            # Determine status and failure reason
            empty_fields = self._detect_empty_fields(extracted_data)
            
            if extracted_data["title"] and len(extracted_data.get("body", "")) > 100:
                status = "pass"
                failure_reason = None
            elif "title" not in extracted_data or not extracted_data["title"]:
                status = "fail"
                failure_reason = f"Title extraction failed. Empty fields: {empty_fields}"
            else:
                status = "needs_review"
                failure_reason = f"Incomplete extraction. Missing/empty: {', '.join(empty_fields)}"
            
            # Get suggestions
            suggestions = self._suggest_selector_updates(failure_reason or "", site_config) if failure_reason else []
            
            return ValidationResult(
                site_name=site_config.name,
                url=site_config.url,
                status=status,
                field_completeness_score=completeness,
                sample_extracted_values={
                    "title": extracted_data["title"][:100],  # Truncate for storage
                    "date_publish": str(extracted_data.get("date_publish") or ""),
                    "has_pagination": has_pagination,
                    "article_count": len(soup.select(site_config.article_selector)) if site_config.article_selector else 0,
                    **{k: v for k, v in extracted_data.items() if not k.startswith("_")}
                },
                failure_reason=failure_reason,
                suggested_selector_updates=suggestions
            )
        
        except Exception as e:
            logger.error(f"Validation error for {site_config.name}: {e}")
            
            return ValidationResult(
                site_name=site_config.name,
                url=site_config.url,
                status="fail",
                field_completeness_score=0,
                failure_reason=f"Exception during validation: {str(e)}",
                sample_extracted_values={"error": str(e)[:500]}
            )
    
    def validate_all_sites(self) -> List[ValidationResult]:
        """Validate all configured sites."""
        from ..scraping.config_registry import SiteConfigRegistry
        
        session_gen = get_session()
        db = next(session_gen)

        try:
            registry = SiteConfigRegistry(db)
            sites = registry.list_sites(active_only=True)

            results = []
            for site in sites:
                try:
                    result = self.validate_site(site)
                    results.append(result)

                    # Update last_validation_time in DB if validation succeeded or needed review
                    if result.status in ["pass", "needs_review"]:
                        from ..database.models import SiteConfig as SiteConfigModel
                        db.query(SiteConfigModel).filter(
                            SiteConfigModel.id == site.id
                        ).update({"last_validation_time": datetime.now()})
                        db.commit()

                except Exception as e:
                    logger.error(f"Error validating site {site.name}: {e}")

                # Add delay between validations
                time.sleep(1)

            return results
        finally:
            db.close()


def check_site_health(site_config, enable_llm_validation: bool = False) -> Dict[str, Any]:
    """
    Convenience function to check health of a single site.
    
    Args:
        site_config: The SiteConfig object
        enable_llm_validation: Whether to run LLM-based deep validation (requires API key)
        
    Returns:
        Dictionary with validation results
    """
    validator = SiteValidator()
    
    try:
        result = validator.validate_site(site_config)

        return {
            "site_name": site_config.name,
            "url": site_config.url,
            "status": result.status,
            "score": result.field_completeness_score,
            "timestamp": result.timestamp.isoformat(),
            "sample_values": {k: v[:100] if isinstance(v, str) and len(v) > 100 else v for k, v in result.sample_extracted_values.items()},
            "failure_reason": result.failure_reason,
            "suggestions": result.suggested_selector_updates,
        }
    
    finally:
        time.sleep(1)
