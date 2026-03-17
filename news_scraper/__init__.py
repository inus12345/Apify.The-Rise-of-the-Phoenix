"""
The Rise of the Phoenix - News & Blog Scraping Platform
Phase 1: Foundation MVP

A modular web scraping platform with clean architecture.
"""

__version__ = "0.1.0"
__author__ = "The_Rise_of_the_Phoenix Team"

from .core.config import settings
from .database.session import (
    Base,
    SpiderBase,
    engine,
    primary_engine,
    spider_engine,
    get_session,
    get_primary_session,
    get_spider_session,
)
from .database.models import (
    SiteConfig,
    SiteCategory,
    CategoryCrawlState,
    SiteTechnology,
    ScrapeStrategy,
    SpiderDiagram,
    SpiderNode,
    SpiderEdge,
    SiteStructureSnapshot,
    SiteStructureChange,
    CatalogChangeLog,
    ArticleUrlLedger,
    ScrapedArticle,
    ScrapeRun,
    HistoricalScrapeProgress,
    ValidationRun,
    LLMAssessmentRun,
    LLMAssessmentLine,
    ScrapeLog
)

# Web interface (Phase 4)
from .web.app import create_app, app as web_app
from .pipelines import run_config_scrape, sync_sites_from_config

__all__ = [
    "__version__",
    "__author__",
    "settings",
    "get_session",
    "get_primary_session",
    "get_spider_session",
    "engine",
    "primary_engine",
    "spider_engine",
    "Base",
    "SpiderBase",
    "SiteConfig",
    "SiteCategory",
    "CategoryCrawlState",
    "SiteTechnology",
    "ScrapeStrategy",
    "SpiderDiagram",
    "SpiderNode",
    "SpiderEdge",
    "SiteStructureSnapshot",
    "SiteStructureChange",
    "CatalogChangeLog",
    "ArticleUrlLedger",
    "ScrapedArticle",
    "ScrapeRun",
    "HistoricalScrapeProgress",
    "ValidationRun",
    "LLMAssessmentRun",
    "LLMAssessmentLine",
    "ScrapeLog",
    "run_config_scrape",
    "sync_sites_from_config",
    "create_app",
    "web_app",
]
