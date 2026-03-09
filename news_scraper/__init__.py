"""
The Rise of the Phoenix - News & Blog Scraping Platform
Phase 1: Foundation MVP

A modular web scraping platform with clean architecture.
"""

__version__ = "0.1.0"
__author__ = "The_Rise_of_the_Phoenix Team"

from .core.config import settings
from .database.session import get_session, engine, Base
from .database.models import (
    SiteConfig,
    SiteCategory,
    ScrapedArticle,
    ScrapeRun,
    ValidationRun,
    ScrapeLog
)

# Web interface (Phase 4)
from .web.app import create_app, app as web_app

__all__ = [
    "__version__",
    "__author__",
    "settings",
    "get_session",
    "engine",
    "Base",
    "SiteConfig",
    "SiteCategory",
    "ScrapedArticle",
    "ScrapeRun",
    "ValidationRun",
    "ScrapeLog",
    "create_app",
    "web_app",
]
