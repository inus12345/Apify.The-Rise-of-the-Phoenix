"""Database models for The Rise of the Phoenix News Scraper - Simplified version.

This module contains lightweight models for a scalable news scraping system.
Designed to handle 100s of websites efficiently with minimal database overhead.
"""
from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship


class Site(Base):
    """Core site configuration for a news website.

    Stores essential metadata and extraction selectors for each scraped site.
    """
    __tablename__ = "sites"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, index=True)
    url = Column(String(500), nullable=False, unique=True)
    country = Column(String(100), nullable=True)
    language = Column(String(10), default="en")
    description = Column(Text, nullable=True)

    # Extraction selectors for article content
    article_title_selector = Column(String(500), nullable=True)
    article_body_selector = Column(String(500), nullable=True)
    publish_date_selector = Column(String(255), nullable=True)
    author_selector = Column(String(255), nullable=True)
    image_selector = Column(String(255), nullable=True)

    # Scraping configuration
    active = Column(Boolean, default=True)
    num_pages_to_scrape = Column(Integer, default=3)

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        Index("idx_sites_active", "active"),
        Index("idx_sites_language", "language"),
    )


class Technology(Base):
    """Technology stack information for a site (CDN, WAF, etc.)."""
    __tablename__ = "technologies"

    id = Column(Integer, primary_key=True)
    site_name = Column(String(255), nullable=False, ForeignKey("sites.name"), index=True)
    technology_name = Column(String(255), nullable=False)
    technology_type = Column(String(100), default="cdn")

    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        UniqueConstraint("site_name", "technology_name", name="uq_site_tech"),
    )


class Category(Base):
    """Category page configuration for a site."""
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True)
    site_name = Column(String(255), nullable=False, ForeignKey("sites.name"), index=True)
    category_name = Column(String(255), nullable=False)
    url = Column(String(500), nullable=False)
    max_pages = Column(Integer, default=3)

    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        UniqueConstraint("site_name", "category_name", name="uq_site_category"),
    )


class ScrapedArticle(Base):
    """Scraped article content from a site."""
    __tablename__ = "scraped_articles"

    id = Column(Integer, primary_key=True)
    site_name = Column(String(255), nullable=False, ForeignKey("sites.name"), index=True)
    
    # Article metadata
    title = Column(Text, nullable=True)
    url = Column(String(1000), nullable=False)
    excerpt = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    section = Column(String(255), nullable=True)
    tags = Column(JSON, nullable=True)

    # Extracted content
    article_body = Column(Text, nullable=True)
    publish_date = Column(DateTime, nullable=True)
    author = Column(String(500), nullable=True)

    # Images
    featured_image_url = Column(String(1000), nullable=True)

    # Metadata
    word_count = Column(Integer, default=0)
    reading_time_minutes = Column(Integer, default=0)

    scraped_at = Column(DateTime, default=datetime.now)
    source_url = Column(String(500), nullable=True)

    __table_args__ = (
        Index("idx_articles_site", "site_name"),
        Index("idx_articles_url", "url"),
        Index("idx_articles_date", "publish_date"),
    )


class Site(Base):
    """Extended site configuration with spider graph support."""
    __tablename__ = "site_configs"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, unique=True)
    url = Column(String(1000), nullable=False, index=True)

    # Country/region metadata
    country = Column(String(100))
    location = Column(String(100))
    language = Column(String(10), default="en")
    description = Column(Text)

    # Active status and settings
    active = Column(Boolean, default=True)
    status = Column(String(50), default="active")
    num_pages_to_scrape = Column(Integer, default=3)

    # Timestamps
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    last_scraped = Column(DateTime)

    __table_args__ = (
        Index("idx_site_configs_active", "active"),
        Index("idx_site_configs_language", "language"),
    )


class SiteCategory(Base):
    """Category configuration for a site."""
    __tablename__ = "site_categories"

    id = Column(Integer, primary_key=True)
    site_config_id = Column(Integer, ForeignKey("site_configs.id"), nullable=False, index=True)

    name = Column(String(255), nullable=False)
    url = Column(String(500), nullable=False)
    max_pages = Column(Integer, default=3)

    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class ScrapedArticle(Base):
    """Scraped article with spider graph metadata."""
    __tablename__ = "scraped_articles_spider"

    id = Column(Integer, primary_key=True)
    site_config_id = Column(Integer, ForeignKey("site_configs.id"), nullable=False, index=True)

    title = Column(Text)
    url = Column(String(1000), nullable=False)
    excerpt = Column(Text)
    
    article_body = Column(Text)
    publish_date = Column(DateTime)
    author = Column(String(500))
    image_url = Column(String(1000))

    word_count = Column(Integer, default=0)
    reading_time_minutes = Column(Integer, default=0)
    scraped_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_spider_articles_site", "site_config_id"),
        Index("idx_spider_articles_url", "url"),
    )