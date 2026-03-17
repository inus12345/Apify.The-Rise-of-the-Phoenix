"""JSON exporter for scraped article data."""
from typing import List, Dict, Any, Optional
from pathlib import Path
import json

from ..database.models import ScrapedArticle


class JSONExporter:
    """Exporter for saving scraped articles to JSON format."""
    
    def __init__(
        self,
        output_path: str = "./data/export.json",
        indent: int = 2,
        ensure_ascii: bool = False
    ):
        """
        Initialize the JSON exporter.
        
        Args:
            output_path: Path to save JSON file
            indent: Indentation level for pretty printing (None for compact)
            ensure_ascii: Whether to escape non-ASCII characters
        """
        self.output_path = Path(output_path)
        self.indent = indent
        self.ensure_ascii = ensure_ascii
        
        # Ensure output directory exists
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
    
    def export_articles(
        self,
        articles: List[ScrapedArticle],
        overwrite: bool = True
    ) -> int:
        """
        Export a list of articles to JSON.
        
        Args:
            articles: List of ScrapedArticle objects to export
            overwrite: Whether to overwrite existing file
            
        Returns:
            Number of articles exported
        """
        if not articles:
            return 0
        
        data = [self._article_to_dict(article) for article in articles]
        self._write_json(data, overwrite)
        
        return len(articles)
    
    def export_by_query(
        self,
        query,
        overwrite: bool = True
    ) -> int:
        """
        Export articles matching a database query to JSON.
        
        Args:
            query: SQLAlchemy query for articles
            overwrite: Whether to overwrite existing file
            
        Returns:
            Number of articles exported
        """
        articles = query.all()
        return self.export_articles(articles, overwrite)
    
    def export_dict_list(
        self,
        data: List[Dict[str, Any]],
        overwrite: bool = True
    ) -> int:
        """
        Export a list of dictionaries to JSON.
        
        Args:
            data: List of dictionaries with article data
            overwrite: Whether to overwrite existing file
            
        Returns:
            Number of records exported
        """
        self._write_json(data, overwrite)
        return len(data) if isinstance(data, list) else 0
    
    def _article_to_dict(self, article: ScrapedArticle) -> Dict[str, Any]:
        """Convert a ScrapedArticle to a dictionary for JSON export."""
        site = getattr(article, "site_config", None)
        strategy = site.scrape_strategy if site else None
        site_country = (site.country or site.location) if site else None
        site_language = site.language if site else article.language
        technologies = []
        if site and getattr(site, "technologies", None):
            technologies = [
                {
                    "technology_name": tech.technology_name,
                    "technology_type": tech.technology_type,
                    "version": tech.version,
                    "confidence_score": tech.confidence_score,
                    "detection_source": tech.detection_source,
                    "notes": tech.notes,
                }
                for tech in site.technologies
            ]
        result = {
            "id": article.id,
            "url": article.url,
            "canonical_url": article.canonical_url,
            "title": article.title,
            "body": article.body,
            "authors": article.authors,
            "section": article.section,
            "tags": article.tags,
            "date_publish": self._serialize_date(article.date_publish),
            "scrape_date": self._serialize_date(article.scrape_date),
            "date_download": self._serialize_date(article.date_download),
            "description": article.description,
            "image_url": article.image_url,
            "image_links": article.image_links,
            "extra_links": article.extra_links,
            "word_count": article.word_count,
            "reading_time_minutes": article.reading_time_minutes,
            "raw_metadata": article.raw_metadata,
            "content_hash": article.content_hash,
            "source_domain": article.source_domain,
            "language": article.language,
            "source_site_name": site.name if site else None,
            "source_site_url": site.url if site else None,
            "source_site_domain": site.domain if site else article.source_domain,
            "source_site_country": site_country,
            "source_site_language": site_language,
            "scrape_status": article.scrape_status,
            "scraper_engine_used": article.scraper_engine_used,
            "site": {
                "site_config_id": site.id if site else article.site_config_id,
                "name": site.name if site else None,
                "url": site.url if site else None,
                "domain": site.domain if site else article.source_domain,
                "country": site_country,
                "location": site.location if site else None,
                "language": site_language,
                "description": site.description if site else None,
                "server_header": site.server_header if site else None,
                "server_vendor": site.server_vendor if site else None,
                "hosting_provider": site.hosting_provider if site else None,
                "ip_address": site.ip_address if site else None,
                "technology_stack_summary": site.technology_stack_summary if site else None,
                "category_url_pattern": site.category_url_pattern if site else None,
                "num_pages_to_scrape": site.num_pages_to_scrape if site else None,
                "status": site.status if site else None,
                "active": site.active if site else None,
                "notes": site.notes if site else None,
                "preferred_scraper_type": site.preferred_scraper_type if site else None,
                "uses_javascript": site.uses_javascript if site else None,
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
            },
        }
        
        return result
    
    @staticmethod
    def _serialize_date(date_value) -> Optional[str]:
        """Serialize a date value to ISO format string."""
        if date_value is None:
            return None
        
        if hasattr(date_value, "isoformat"):
            return date_value.isoformat()
        
        return str(date_value)
    
    def _write_json(
        self,
        data,
        overwrite: bool
    ) -> None:
        """Write JSON data to file."""
        mode = "w" if overwrite else "a"
        
        with open(self.output_path, mode, encoding="utf-8") as f:
            json.dump(
                data,
                f,
                indent=self.indent,
                ensure_ascii=self.ensure_ascii,
                default=str
            )

    def export_run_payload(
        self,
        records: List[Dict[str, Any]],
        run_metadata: Dict[str, Any],
        overwrite: bool = True
    ) -> int:
        """
        Export a structured run payload.

        Output format:
        {
          "run_metadata": {...},
          "record_count": N,
          "records": [...]
        }
        """
        payload = {
            "run_metadata": run_metadata,
            "record_count": len(records),
            "records": records,
        }
        self._write_json(payload, overwrite=overwrite)
        return len(records)
    
    def append_articles(
        self,
        articles: List[ScrapedArticle]
    ) -> int:
        """
        Append articles to existing JSON file.
        
        Args:
            articles: List of ScrapedArticle objects
            
        Returns:
            Number of articles appended
        """
        if not articles:
            return 0
        
        # Read existing data if file exists
        all_data = []
        if self.output_path.exists():
            try:
                with open(self.output_path, "r", encoding="utf-8") as f:
                    all_data = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                all_data = []
        
        # Add new articles
        for article in articles:
            article_dict = self._article_to_dict(article)
            
            # Avoid duplicates by URL
            if not any(d.get("url") == article.url for d in all_data):
                all_data.append(article_dict)
        
        self._write_json(all_data, overwrite=True)
        return len(articles)
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get statistics about exported data.
        
        Returns:
            Dictionary with export statistics
        """
        stats = {
            "path": str(self.output_path),
            "exists": self.output_path.exists(),
            "size_bytes": 0,
            "record_count": 0,
        }
        
        if not stats["exists"]:
            return stats
        
        try:
            stats["size_bytes"] = self.output_path.stat().st_size
            
            with open(self.output_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                stats["record_count"] = len(data) if isinstance(data, list) else 1
        
        except Exception:
            pass
        
        return stats
    
    def clear(self) -> None:
        """Clear all exported data from the file."""
        self._write_json([], overwrite=True)


def export_to_json(
    articles: List[ScrapedArticle],
    output_path: str = "./data/export.json"
) -> int:
    """
    Convenience function to export articles to JSON.
    
    Args:
        articles: List of ScrapedArticle objects
        output_path: Path to save JSON file
        
    Returns:
        Number of articles exported
    """
    exporter = JSONExporter(output_path)
    return exporter.export_articles(articles)
