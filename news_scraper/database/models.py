"""Simplified database models for the news scraper platform."""
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, String, Text,
)
from sqlalchemy.orm import declarative_base, relationship

# Create declarative base - this will be shared with session.py
Base = declarative_base()


class SiteConfig(Base):
    """Configuration for a website to scrape."""
    
    __tablename__ = "sites"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    url = Column(String(500), nullable=False, unique=True)
    
    # CSS selectors for content extraction
    article_selector = Column(String(255), nullable=True)
    title_selector = Column(String(255), nullable=True)
    date_selector = Column(String(255), nullable=True)
    body_selector = Column(String(255), nullable=True)
    
    # Scraping settings
    num_pages_to_scrape = Column(Integer, default=1)
    active = Column(Boolean, default=True)
    
    # Additional metadata fields
    domain = Column(String(255), nullable=True)
    category_url_pattern = Column(String(500), nullable=True)
    uses_javascript = Column(Boolean, default=False)
    country = Column(String(100), nullable=True)
    location = Column(String(100), nullable=True)
    language = Column(String(50), default="en")
    description = Column(Text, nullable=True)
    server_header = Column(String(255), nullable=True)
    server_vendor = Column(String(255), nullable=True)
    hosting_provider = Column(String(255), nullable=True)
    technology_stack_summary = Column(Text, nullable=True)
    preferred_scraper_type = Column(String(50), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    last_scraped = Column(DateTime, nullable=True)
    
    def __repr__(self):
        return f"<SiteConfig(id={self.id}, name='{self.name}', url='{self.url}')>"


class SiteCategory(Base):
    """A category within a site configuration."""
    
    __tablename__ = "site_categories"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    site_id = Column(Integer, ForeignKey('sites.id'), nullable=False)
    name = Column(String(255), nullable=False)
    url = Column(String(500), nullable=False)
    max_pages = Column(Integer, default=1)
    
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    def __repr__(self):
        return f"<SiteCategory(id={self.id}, name='{self.name}', site_id={self.site_id})>"
