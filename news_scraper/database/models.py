"""Database models for the news scraper platform."""
from datetime import datetime
from typing import Optional, List
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, Enum, JSON, Index
from sqlalchemy.orm import relationship
from ..database.session import Base


class SiteConfig(Base):
    """
    Configuration for a website to scrape.
    
    URL-based deduplication via MD5 hash is used throughout the system.
    Supports multiple categories per site.
    """
    __tablename__ = "site_configs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Website identification
    name = Column(String(255), nullable=False, comment="Human-readable site name")
    url = Column(String(500), nullable=False, unique=True, comment="Base URL of the site")
    domain = Column(String(255), nullable=True, index=True, comment="Domain (e.g., example.com)")
    
    # Notes
    notes = Column(Text, nullable=True, comment="Additional notes about this site configuration")
    
    # Scraping configuration
    category_url_pattern = Column(String(500), nullable=True, comment="Pattern for listing pages (e.g., {url}?page={page})")
    num_pages_to_scrape = Column(Integer, default=1, comment="Number of pages to scrape")
    
    # XPath/CSS selectors for content extraction
    article_selector = Column(String(255), nullable=True, comment="CSS selector or XPath for article elements")
    title_selector = Column(String(255), nullable=True, comment="Selector for article title")
    author_selector = Column(String(255), nullable=True, comment="Selector for author name(s)")
    date_selector = Column(String(255), nullable=True, comment="Selector for publication date")
    body_selector = Column(String(255), nullable=True, comment="Selector for article body content")
    
    # Scraper configuration
    preferred_scraper_type = Column(String(50), default="httpx", comment="Preferred scraper: httpx or selenium")
    uses_javascript = Column(Boolean, default=False, comment="Whether the site requires JavaScript rendering (Selenium fallback)")
    active = Column(Boolean, default=True, comment="Whether this site should be scraped")
    
    # Status flags
    status = Column(String(50), default="active", comment="Site status: active, paused, error, deprecated")
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.now, comment="When this site was added")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="Last update time")
    last_scraped = Column(DateTime, nullable=True, comment="When this site was last scraped")
    last_successful_scrape = Column(DateTime, nullable=True, comment="When this site last had a successful scrape")
    last_validation_time = Column(DateTime, nullable=True, comment="When this site was last validated")
    
    # Relationships
    categories = relationship("SiteCategory", back_populates="site_config", cascade="all, delete-orphan")
    articles = relationship("ScrapedArticle", back_populates="site_config", cascade="all, delete-orphan")
    scrape_runs = relationship("ScrapeRun", back_populates="site_config", cascade="all, delete-orphan")
    scrape_logs = relationship("ScrapeLog", back_populates="site_config", cascade="all, delete-orphan")
    
    def __repr__(self) -> str:
        return f"<SiteConfig(id={self.id}, name='{self.name}', url='{self.url}')>"
    
    @property
    def url_hash(self) -> str:
        """Generate MD5 hash of the URL for deduplication."""
        import hashlib
        return hashlib.md5(self.url.encode("utf-8")).hexdigest()


class SiteCategory(Base):
    """
    A category within a site configuration.
    Allows multiple categories per site.
    """
    __tablename__ = "site_categories"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    site_config_id = Column(Integer, ForeignKey("site_configs.id"), nullable=False)
    
    name = Column(String(255), nullable=False, comment="Category name (e.g., 'News', 'Blog')")
    url = Column(String(500), nullable=False, comment="Category URL")
    max_pages = Column(Integer, default=1, comment="Max pages for this category")
    
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Relationships
    site_config = relationship("SiteConfig", back_populates="categories")
    
    def __repr__(self) -> str:
        return f"<SiteCategory(id={self.id}, name='{self.name}')>"


class ScrapedArticle(Base):
    """
    A scraped article from a configured website.
    
    Uses URL-based deduplication via MD5 hash stored in source_url_hash.
    """
    __tablename__ = "scraped_articles"
    
    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # URL information (for deduplication)
    url = Column(String(1000), nullable=False, comment="Full article URL")
    source_url_hash = Column(String(32), nullable=False, index=True, comment="MD5 hash of URL for deduplication")
    
    # Article content
    title = Column(Text, nullable=True, comment="Article title")
    body = Column(Text, nullable=True, comment="Main article content")
    description = Column(Text, nullable=True, comment="Article excerpt/description")
    
    # Metadata
    authors = Column(String(500), nullable=True, comment="Comma-separated author names")
    date_publish = Column(DateTime, nullable=True, comment="Publication date")
    date_download = Column(DateTime, default=datetime.now, comment="When article was downloaded")
    image_url = Column(String(1000), nullable=True, comment="Featured image URL")
    
    # Source information
    source_domain = Column(String(255), nullable=True, comment="Source domain (e.g., example.com)")
    language = Column(String(10), nullable=True, comment="Detected language code")
    
    # Scrape metadata
    site_config_id = Column(Integer, ForeignKey("site_configs.id"), nullable=False, comment="ID of the SiteConfig that scraped this article")
    scrape_status = Column(String(20), default="success", comment="Status: success, failed, skipped")
    error_message = Column(Text, nullable=True, comment="Error message if scraping failed")
    
    # Validation
    is_validated = Column(Boolean, default=False, comment="Whether the article has been validated")
    validation_score = Column(Integer, nullable=True, comment="LLM validation score (0-100)")
    
    # Relationships
    site_config = relationship("SiteConfig", back_populates="articles")
    validation_runs = relationship("ValidationRun", back_populates="article", cascade="all, delete-orphan")
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    __table_args__ = (
        Index("idx_url_hash_site", "source_url_hash", "site_config_id"),
    )
    
    def __repr__(self) -> str:
        return f"<ScrapedArticle(id={self.id}, title='{self.title}', url='{self.url}')>"
    
    @property
    def article_url_hash(self) -> str:
        """Generate MD5 hash of the article URL for deduplication."""
        import hashlib
        return hashlib.md5(self.url.encode("utf-8")).hexdigest()


class ScrapeRun(Base):
    """
    Records a single scraping run.
    Tracks what was scraped, when, and how many articles were found/saved.
    """
    __tablename__ = "scrape_runs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    site_config_id = Column(Integer, ForeignKey("site_configs.id"), nullable=False, comment="Site that was scraped")
    scrape_logs = relationship("ScrapeLog", back_populates="scrape_run", cascade="all, delete-orphan")
    
    # Run metadata
    started_at = Column(DateTime, default=datetime.now, comment="When the scrape run started")
    completed_at = Column(DateTime, nullable=True, comment="When the scrape run finished")
    status = Column(String(50), default="running", comment="Run status: running, success, failed, partial")
    
    # Statistics
    pages_scraped = Column(Integer, default=0, comment="Number of listing pages scraped")
    articles_found = Column(Integer, default=0, comment="Number of article URLs found")
    articles_saved = Column(Integer, default=0, comment="Number of new articles saved")
    articles_skipped = Column(Integer, default=0, comment="Number of duplicate articles skipped")
    
    # Error tracking
    error_count = Column(Integer, default=0, comment="Number of errors encountered")
    last_error = Column(Text, nullable=True, comment="Last error message if failed")
    
    # Output files (if exported)
    csv_export_path = Column(String(500), nullable=True, comment="Path to CSV export file")
    json_export_path = Column(String(500), nullable=True, comment="Path to JSON export file")
    
    # Relationships
    site_config = relationship("SiteConfig", back_populates="scrape_runs")
    
    def __repr__(self) -> str:
        return f"<ScrapeRun(id={self.id}, site_id={self.site_config_id}, status='{self.status}')>"


class ValidationRun(Base):
    """
    Records a validation run for a scraped article.
    Used for LLM-assisted validation workflow.
    """
    __tablename__ = "validation_runs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    scraped_article_id = Column(Integer, ForeignKey("scraped_articles.id"), nullable=False, comment="Article being validated")
    
    # Relationships
    article = relationship("ScrapedArticle", back_populates="validation_runs")
    
    # Validation metadata
    started_at = Column(DateTime, default=datetime.now, comment="When validation started")
    completed_at = Column(DateTime, nullable=True, comment="When validation finished")
    status = Column(String(50), default="pending", comment="Status: pending, in_progress, complete, failed")
    
    # Validation results
    is_validated = Column(Boolean, default=False, comment="Whether the article passed validation")
    validation_score = Column(Integer, nullable=True, comment="LLM validation score (0-100)")
    validation_notes = Column(Text, nullable=True, comment="Notes from validation")
    
    # LLM metadata
    llm_model = Column(String(255), nullable=True, comment="LLM model used for validation")
    prompt_tokens = Column(Integer, nullable=True, comment="Number of input tokens")
    completion_tokens = Column(Integer, nullable=True, comment="Number of output tokens")
    
    def __repr__(self) -> str:
        return f"<ValidationRun(id={self.id}, article_id={self.scraped_article_id}, status='{self.status}')>"


class ScrapeLog(Base):
    """
    Detailed log entries for scraping operations.
    Tracks individual page fetches, errors, and important events.
    """
    __tablename__ = "scrape_logs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    site_config_id = Column(Integer, ForeignKey("site_configs.id"), nullable=False, comment="Site being scraped")
    scrape_run_id = Column(Integer, ForeignKey("scrape_runs.id"), nullable=True, comment="Related scrape run")
    
    # Log metadata
    timestamp = Column(DateTime, default=datetime.now, index=True)
    level = Column(String(20), default="INFO", comment="Log level: DEBUG, INFO, WARNING, ERROR")
    
    # Log details
    event_type = Column(String(50), nullable=True, comment="Type of event: page_fetch, article_found, scrape_start, etc.")
    message = Column(Text, nullable=False, comment="Log message")
    extra_data = Column(JSON, nullable=True, comment="Additional structured data (JSON)")
    
    # Relationships
    site_config = relationship("SiteConfig", back_populates="scrape_logs")
    scrape_run = relationship("ScrapeRun", back_populates="scrape_logs")
    
    def __repr__(self) -> str:
        return f"<ScrapeLog(id={self.id}, level='{self.level}', message='{self.message[:50]}...')>"