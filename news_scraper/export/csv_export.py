"""CSV exporter for scraped article data."""
from typing import List, Dict, Any, Optional
from pathlib import Path
import csv

from ..database.models import ScrapedArticle


class CSVExporter:
    """Exporter for saving scraped articles to CSV format."""
    
    DEFAULT_FIELDS = [
        "id",
        "url",
        "title",
        "body",
        "authors",
        "date_publish",
        "date_download",
        "description",
        "image_url",
        "source_domain",
        "language",
        "scrape_status",
    ]
    
    def __init__(
        self,
        output_path: str = "./data/export.csv",
        fields: List[str] = None
    ):
        """
        Initialize the CSV exporter.
        
        Args:
            output_path: Path to save CSV file
            fields: List of fields to export (defaults to DEFAULT_FIELDS)
        """
        self.output_path = Path(output_path)
        self.fields = fields or self.DEFAULT_FIELDS
        
        # Ensure output directory exists
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
    
    def export_articles(
        self,
        articles: List[ScrapedArticle],
        overwrite: bool = False
    ) -> int:
        """
        Export a list of articles to CSV.
        
        Args:
            articles: List of ScrapedArticle objects to export
            overwrite: Whether to overwrite existing file
            
        Returns:
            Number of articles exported
        """
        if not articles:
            return 0
        
        mode = "w" if overwrite else "a"
        header_needed = overwrite or not self.output_path.exists()
        
        with open(self.output_path, mode, newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self.fields)
            
            if header_needed:
                writer.writeheader()
            
            for article in articles:
                row = self._article_to_dict(article)
                writer.writerow(row)
        
        return len(articles)
    
    def export_by_query(
        self,
        query,
        overwrite: bool = False
    ) -> int:
        """
        Export articles matching a database query to CSV.
        
        Args:
            query: SQLAlchemy query for articles
            overwrite: Whether to overwrite existing file
            
        Returns:
            Number of articles exported
        """
        articles = query.all()
        return self.export_articles(articles, overwrite)
    
    def _article_to_dict(self, article: ScrapedArticle) -> Dict[str, Any]:
        """Convert a ScrapedArticle to a dictionary for CSV export."""
        row = {}
        
        for field in self.fields:
            value = getattr(article, field, None)
            
            # Handle datetime objects
            if hasattr(value, "isoformat"):
                row[field] = value.isoformat()
            elif isinstance(value, list):
                row[field] = "|".join(str(v) for v in value)
            elif isinstance(value, dict):
                row[field] = str(value)
            else:
                row[field] = value
        
        return row
    
    def export_dict_list(
        self,
        data: List[Dict[str, Any]],
        overwrite: bool = False
    ) -> int:
        """
        Export a list of dictionaries to CSV.
        
        Args:
            data: List of dictionaries with article data
            overwrite: Whether to overwrite existing file
            
        Returns:
            Number of records exported
        """
        if not data:
            return 0
        
        # Get all keys from data for fieldnames
        fields = self.fields if self._has_all_keys(data) else list(data[0].keys())
        
        mode = "w" if overwrite else "a"
        header_needed = overwrite or not self.output_path.exists()
        
        with open(self.output_path, mode, newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            
            if header_needed:
                writer.writeheader()
            
            for record in data:
                row = {k: self._serialize_value(v) for k, v in record.items()}
                writer.writerow(row)
        
        return len(data)
    
    def _has_all_keys(self, data: List[Dict[str, Any]]) -> bool:
        """Check if all records have the default field keys."""
        required_keys = set(self.DEFAULT_FIELDS)
        return all(required_keys.issubset(record.keys()) for record in data)
    
    @staticmethod
    def _serialize_value(value: Any) -> str:
        """Serialize a value to string for CSV export."""
        if value is None:
            return ""
        
        if isinstance(value, list):
            return "|".join(str(v) for v in value)
        
        if isinstance(value, dict):
            import json
            return json.dumps(value)
        
        if hasattr(value, "isoformat"):
            return value.isoformat()
        
        return str(value)
    
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
            "row_count": 0,
        }
        
        if not stats["exists"]:
            return stats
        
        try:
            stats["size_bytes"] = self.output_path.stat().st_size
            
            with open(self.output_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                stats["row_count"] = len(rows)
        
        except Exception:
            pass
        
        return stats


def export_to_csv(
    articles: List[ScrapedArticle],
    output_path: str = "./data/export.csv"
) -> int:
    """
    Convenience function to export articles to CSV.
    
    Args:
        articles: List of ScrapedArticle objects
        output_path: Path to save CSV file
        
    Returns:
        Number of articles exported
    """
    exporter = CSVExporter(output_path)
    return exporter.export_articles(articles)