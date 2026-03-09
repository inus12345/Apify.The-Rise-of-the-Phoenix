"""Site configuration registry for managing website scraping settings."""
from typing import List, Dict, Optional
from datetime import datetime

from ..database.models import SiteConfig


class SiteConfigRegistry:
    """
    Registry for managing site configurations.
    
    Provides CRUD operations for site configs and supports
    URL-based deduplication via MD5 hash.
    """
    
    def __init__(self, db_session):
        self.db = db_session
    
    def add_site(
        self,
        name: str,
        url: str,
        category_url_pattern: Optional[str] = None,
        num_pages_to_scrape: int = 1,
        active: bool = True,
        uses_javascript: bool = False,
    ) -> SiteConfig:
        """
        Add a new site configuration.
        
        Args:
            name: Human-readable site name
            url: Base URL of the site (must be unique)
            category_url_pattern: Optional pattern for listing pages
            num_pages_to_scrape: Number of pages to scrape
            active: Whether this site should be scraped
            uses_javascript: Whether the site requires JavaScript rendering
            
        Returns:
            The created SiteConfig object
        """
        # Check if URL already exists (deduplication)
        existing = self.db.query(SiteConfig).filter(
            SiteConfig.url == url
        ).first()
        
        if existing:
            raise ValueError(f"Site with URL '{url}' already exists")
        
        site_config = SiteConfig(
            name=name,
            url=url,
            category_url_pattern=category_url_pattern,
            num_pages_to_scrape=num_pages_to_scrape,
            active=active,
            uses_javascript=uses_javascript,
        )
        
        self.db.add(site_config)
        self.db.commit()
        self.db.refresh(site_config)
        
        return site_config
    
    def get_site(self, site_id: int) -> Optional[SiteConfig]:
        """Get a site configuration by ID."""
        return self.db.query(SiteConfig).filter(SiteConfig.id == site_id).first()
    
    def get_site_by_url(self, url: str) -> Optional[SiteConfig]:
        """Get a site configuration by URL."""
        return self.db.query(SiteConfig).filter(SiteConfig.url == url).first()
    
    def list_sites(
        self,
        active_only: bool = True,
        limit: int = 100,
        offset: int = 0
    ) -> List[SiteConfig]:
        """
        List site configurations with optional filtering.
        
        Args:
            active_only: Whether to only return active sites
            limit: Maximum number of results
            offset: Offset for pagination
            
        Returns:
            List of SiteConfig objects
        """
        query = self.db.query(SiteConfig)
        if active_only:
            query = query.filter(SiteConfig.active == True)
        
        return query.offset(offset).limit(limit).all()
    
    def update_site(
        self,
        site_id: int,
        **kwargs
    ) -> Optional[SiteConfig]:
        """
        Update a site configuration.
        
        Args:
            site_id: ID of the site to update
            **kwargs: Fields to update (name, url, active, etc.)
            
        Returns:
            The updated SiteConfig object or None if not found
        """
        site = self.get_site(site_id)
        if not site:
            return None
        
        for key, value in kwargs.items():
            if hasattr(site, key):
                setattr(site, key, value)
        
        self.db.commit()
        self.db.refresh(site)
        return site
    
    def delete_site(self, site_id: int) -> bool:
        """
        Delete a site configuration.
        
        Args:
            site_id: ID of the site to delete
            
        Returns:
            True if deleted, False if not found
        """
        site = self.get_site(site_id)
        if not site:
            return False
        
        self.db.delete(site)
        self.db.commit()
        return True
    
    def get_all_sites(self) -> List[Dict]:
        """
        Get all sites as dictionaries for display.
        
        Returns:
            List of site configurations as dictionaries
        """
        sites = self.list_sites(active_only=False)
        return [self._site_to_dict(site) for site in sites]
    
    @staticmethod
    def _site_to_dict(site: SiteConfig) -> Dict:
        """Convert a SiteConfig object to a dictionary."""
        return {
            "id": site.id,
            "name": site.name,
            "url": site.url,
            "category_url_pattern": site.category_url_pattern,
            "num_pages_to_scrape": site.num_pages_to_scrape,
            "active": site.active,
            "uses_javascript": site.uses_javascript,
            "created_at": site.created_at.isoformat() if site.created_at else None,
            "updated_at": site.updated_at.isoformat() if site.updated_at else None,
            "last_scraped": site.last_scraped.isoformat() if site.last_scraped else None,
        }


def get_default_sites() -> List[Dict]:
    """
    Get a list of default test sites to seed the database.
    
    Returns:
        List of dictionaries containing site configuration data
    """
    return [
        {
            "name": "Example News Site",
            "url": "https://example.com/news",
            "category_url_pattern": "https://example.com/news?page={page}",
            "num_pages_to_scrape": 3,
            "active": True,
            "uses_javascript": False,
            "description": "A sample news website for testing"
        },
        {
            "name": "Blog Platform",
            "url": "https://blog.example.com",
            "category_url_pattern": None,
            "num_pages_to_scrape": 5,
            "active": True,
            "uses_javascript": False,
            "description": "A blog platform for testing"
        },
        {
            "name": "Tech News Portal",
            "url": "https://tech.example.org",
            "category_url_pattern": "https://tech.example.org/page/{page}",
            "num_pages_to_scrape": 2,
            "active": True,
            "uses_javascript": False,
            "description": "Technology news portal for testing"
        },
    ]