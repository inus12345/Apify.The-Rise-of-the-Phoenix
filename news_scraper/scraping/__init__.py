"""Scraping module for the news scraper platform."""
from .config_registry import SiteConfigRegistry, get_default_sites
from .engine import ScraperEngine

__all__ = [
    "SiteConfigRegistry",
    "get_default_sites",
    "ScraperEngine",
]
