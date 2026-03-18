"""Site configuration registry for managing website scraping settings."""
from typing import List, Dict, Optional
from urllib.parse import urlparse

from ..database.models import CategoryCrawlState, SiteCategory, SiteConfig, SpiderDiagram, SpiderEdge, SpiderNode
from ..database.session import get_spider_session


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
        domain: Optional[str] = None,
        category_url_pattern: Optional[str] = None,
        num_pages_to_scrape: int = 1,
        active: bool = True,
        uses_javascript: bool = False,
        country: Optional[str] = None,
        location: Optional[str] = None,
        language: str = "en",
        description: Optional[str] = None,
        server_header: Optional[str] = None,
        server_vendor: Optional[str] = None,
        hosting_provider: Optional[str] = None,
        technology_stack_summary: Optional[str] = None,
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
        parsed = urlparse(url)
        resolved_domain = (domain or (parsed.netloc.lower().replace("www.", "") if parsed.netloc else None))

        # Check if URL already exists (deduplication)
        existing = self.db.query(SiteConfig).filter(
            SiteConfig.url == url
        ).first()
        
        if existing:
            raise ValueError(f"Site with URL '{url}' already exists")
        
        site_config = SiteConfig(
            name=name,
            url=url,
            domain=resolved_domain,
            category_url_pattern=category_url_pattern,
            num_pages_to_scrape=num_pages_to_scrape,
            active=active,
            uses_javascript=uses_javascript,
            country=country,
            location=location or country,
            language=language,
            description=description,
            server_header=server_header,
            server_vendor=server_vendor,
            hosting_provider=hosting_provider,
            technology_stack_summary=technology_stack_summary,
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
        limit: Optional[int] = None,
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

        query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        return query.all()
    
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

        spider_session = next(get_spider_session())
        try:
            # Clean up spider/category planning rows in the dedicated spider DB.
            diagram_ids = [
                row[0]
                for row in spider_session.query(SpiderDiagram.id)
                .filter(SpiderDiagram.site_config_id == site_id)
                .all()
            ]
            if diagram_ids:
                spider_session.query(SpiderEdge).filter(
                    SpiderEdge.spider_diagram_id.in_(diagram_ids)
                ).delete(synchronize_session=False)
                spider_session.query(SpiderNode).filter(
                    SpiderNode.spider_diagram_id.in_(diagram_ids)
                ).delete(synchronize_session=False)
                spider_session.query(SpiderDiagram).filter(
                    SpiderDiagram.id.in_(diagram_ids)
                ).delete(synchronize_session=False)

            spider_session.query(SiteCategory).filter(
                SiteCategory.site_config_id == site_id
            ).delete(synchronize_session=False)
            spider_session.query(CategoryCrawlState).filter(
                CategoryCrawlState.site_config_id == site_id
            ).delete(synchronize_session=False)

            self.db.delete(site)
            self.db.commit()
            spider_session.commit()
            return True
        except Exception:
            self.db.rollback()
            spider_session.rollback()
            raise
        finally:
            spider_session.close()
    
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
            "domain": site.domain,
            "country": site.country or site.location,
            "language": site.language,
            "server_header": site.server_header,
            "server_vendor": site.server_vendor,
            "hosting_provider": site.hosting_provider,
            "technology_stack_summary": site.technology_stack_summary,
            "preferred_scraper_type": site.preferred_scraper_type,
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
