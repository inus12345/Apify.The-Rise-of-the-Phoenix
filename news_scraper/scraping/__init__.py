"""Scraping module for the news scraper platform."""
from .config_registry import SiteConfigRegistry, get_default_sites
from .engine import ScraperEngine
from .selenium_fallback import SeleniumScraper, scrape_with_selenium

__all__ = [
    "SiteConfigRegistry",
    "get_default_sites", 
    "ScraperEngine",
    "SeleniumScraper",
    "scrape_with_selenium"
]