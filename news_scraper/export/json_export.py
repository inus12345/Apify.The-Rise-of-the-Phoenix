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
        result = {
            "id": article.id,
            "url": article.url,
            "title": article.title,
            "body": article.body,
            "authors": article.authors,
            "date_publish": self._serialize_date(article.date_publish),
            "date_download": self._serialize_date(article.date_download),
            "description": article.description,
            "image_url": article.image_url,
            "source_domain": article.source_domain,
            "language": article.language,
            "scrape_status": article.scrape_status,
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
        data: List[Dict[str, Any]],
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