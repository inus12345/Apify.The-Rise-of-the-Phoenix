"""Database models for The Rise of the Phoenix news scraper platform."""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship


class SiteConfig:
    """
    Configuration for a website to scrape.

    This is the primary table for site metadata, extraction defaults, and
    high-level crawl settings.
    """

    __tablename__ = "site_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Website identification
    name = Column(String(255), nullable=False, comment="Human-readable site name")
    url = Column(String(500), nullable=False, unique=True, comment="Base URL of the site")
    domain = Column(String(255), nullable=True, index=True, comment="Domain (e.g., example.com)")

    # Website metadata
    country = Column(String(100), nullable=True, comment="Country where site is based")
    location = Column(String(100), nullable=True, comment="Legacy location field (country/region)")
    description = Column(Text, nullable=True, comment="Brief description of the outlet")
    language = Column(String(10), default="en", comment="Primary language code (ISO 639-1)")

    # Server/discovery metadata
    server_header = Column(String(255), nullable=True, comment="Observed Server HTTP header")
    server_vendor = Column(String(255), nullable=True, comment="Detected server vendor or stack")
    hosting_provider = Column(String(255), nullable=True, comment="Detected hosting provider")
    ip_address = Column(String(64), nullable=True, comment="Resolved public IP address")
    technology_stack_summary = Column(
        Text,
        nullable=True,
        comment="Human/LLM-maintained summary of detected technologies",
    )

    # Notes
    notes = Column(Text, nullable=True, comment="Additional notes about this site configuration")

    # Scraping configuration
    category_url_pattern = Column(String(500), nullable=True, comment="Pattern for listing pages (e.g., {url}?page={page})")
    num_pages_to_scrape = Column(Integer, default=1, comment="Default number of pages to scrape")

    # XPath/CSS selectors for content extraction
    article_selector = Column(String(255), nullable=True, comment="CSS selector or XPath for article elements")
    title_selector = Column(String(255), nullable=True, comment="Selector for article title")
    author_selector = Column(String(255), nullable=True, comment="Selector for author name(s)")
    date_selector = Column(String(255), nullable=True, comment="Selector for publication date")
    body_selector = Column(String(255), nullable=True, comment="Selector for article body content")

    # Scraper configuration
    preferred_scraper_type = Column(
        String(50),
        default="scrapling",
        comment="Preferred scraper engine. Priority order: scrapling, pydoll, selenium.",
    )
    uses_javascript = Column(Boolean, default=False, comment="Whether the site requires JavaScript rendering")
    active = Column(Boolean, default=True, comment="Whether this site should be scraped")

    # Status flags
    status = Column(String(50), default="active", comment="Site status: active, paused, error, deprecated")

    # Timestamps
    created_at = Column(DateTime, default=datetime.now, comment="When this site was added")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="Last update time")
    last_scraped = Column(DateTime, nullable=True, comment="When this site was last scraped")
    last_successful_scrape = Column(DateTime, nullable=True, comment="When this site last had a successful scrape")
    last_validation_time = Column(DateTime, nullable=True, comment="When this site was last validated")

    __table_args__ = (
        Index("idx_site_configs_country", "country"),
        Index("idx_site_configs_active_country", "active", "country"),
        Index("idx_site_configs_active_language", "active", "language"),
    )

    def __repr__(self) -> str:
        return f"<SiteConfig(id={self.id}, name='{self.name}', url='{self.url}')>"

    @property
    def url_hash(self) -> str:
        """Generate MD5 hash of the URL for deduplication."""
        import hashlib
        return hashlib.md5(self.url.encode("utf-8")).hexdigest()


class SiteCategory:
    """A category within a site configuration for spider DB."""
    __tablename__ = "site_categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_config_id = Column(Integer, nullable=False, index=True)

    name = Column(String(255), nullable=False)
    url = Column(String(500), nullable=False)
    max_pages = Column(Integer, default=1)
    page_url_pattern = Column(String(500), nullable=True)
    start_page = Column(Integer, default=1)
    active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        Index("idx_site_categories_site_active", "site_config_id", "active"),
        Index("idx_site_categories_site_start_page", "site_config_id", "start_page"),
    )

    def __repr__(self) -> str:
        return f"<SiteCategory(id={self.id}, name='{self.name}', site_config_id={self.site_config_id})>"


class CategoryCrawlState:
    """Crawl-state record keeping for each site/category combination."""
    __tablename__ = "category_crawl_state"

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_config_id = Column(Integer, nullable=False, index=True)
    site_category_id = Column(Integer, nullable=False, index=True)

    category_name = Column(String(255), nullable=True)
    category_url = Column(String(1000), nullable=False)
    last_page_scraped = Column(Integer, nullable=True)
    max_page_seen = Column(Integer, nullable=True)
    last_page_url = Column(String(1000), nullable=True)

    total_listing_pages_scraped = Column(Integer, default=0)
    total_links_discovered = Column(Integer, default=0)
    total_records_emitted = Column(Integer, default=0)

    last_mode = Column(String(50), nullable=True)
    last_chunk_id = Column(String(100), nullable=True)
    last_scraped_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        UniqueConstraint("site_config_id", "category_url", name="uq_category_crawl_state_site_category"),
        Index("idx_category_crawl_state_site_updated", "site_config_id", "updated_at"),
        Index("idx_category_crawl_state_site_category_id", "site_config_id", "site_category_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<CategoryCrawlState(site_id={self.site_config_id}, category_url='{self.category_url}', "
            f"pages={self.total_listing_pages_scraped}, emitted={self.total_records_emitted})>"
        )


class SiteTechnology:
    """Detected or manually configured technologies for a website."""
    __tablename__ = "site_technologies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_config_id = Column(Integer, nullable=False, index=True)

    technology_name = Column(String(255), nullable=False)
    technology_type = Column(String(100), nullable=True)
    version = Column(String(100), nullable=True)
    confidence_score = Column(Float, nullable=True)
    detection_source = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        UniqueConstraint("site_config_id", "technology_name", "version", name="uq_site_technology"),
    )

    def __repr__(self) -> str:
        return f"<SiteTechnology(site_id={self.site_config_id}, technology='{self.technology_name}')>"


class ScrapeStrategy:
    """Scraping and anti-blocking strategy for a website."""
    __tablename__ = "scrape_strategies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_config_id = Column(Integer, nullable=False, unique=True, index=True)

    scraper_engine = Column(String(50), default="scrapling")
    fallback_engine_chain = Column(JSON, nullable=True)
    content_parser = Column(String(50), default="beautifulsoup")
    browser_automation_tool = Column(String(50), nullable=True)
    rendering_required = Column(Boolean, default=False)
    requires_proxy = Column(Boolean, default=False)
    proxy_region = Column(String(100), nullable=True)
    login_required = Column(Boolean, default=False)
    auth_strategy = Column(String(255), nullable=True)
    anti_bot_protection = Column(String(255), nullable=True)
    blocking_signals = Column(JSON, nullable=True)
    bypass_techniques = Column(JSON, nullable=True)
    request_headers = Column(JSON, nullable=True)
    cookie_preset = Column(JSON, nullable=True)
    rate_limit_per_minute = Column(Integer, nullable=True)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = ()

    def __repr__(self) -> str:
        return f"<ScrapeStrategy(site_id={self.site_config_id}, engine='{self.scraper_engine}')>"


class SpiderDiagram:
    """Spider flow definition for exact crawl/extract traversal."""
    __tablename__ = "spider_diagrams"

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_config_id = Column(Integer, nullable=False, index=True)

    name = Column(String(255), nullable=False)
    version = Column(Integer, default=1)
    entrypoint_url = Column(String(1000), nullable=False)
    is_active = Column(Boolean, default=True)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        UniqueConstraint("site_config_id", "name", "version", name="uq_spider_diagram_version"),
        Index("idx_spider_diagrams_site_active_version", "site_config_id", "is_active", "version"),
    )

    def __repr__(self) -> str:
        return f"<SpiderDiagram(id={self.id}, site_id={self.site_config_id}, name='{self.name}', version={self.version})>"


class SpiderNode:
    """Node in a spider diagram representing a crawl/extraction step."""
    __tablename__ = "spider_nodes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    spider_diagram_id = Column(Integer, nullable=False, index=True)

    node_key = Column(String(100), nullable=False)
    node_type = Column(String(50), nullable=False)
    url_pattern = Column(String(1000), nullable=True)
    selector = Column(String(255), nullable=True)
    extraction_target = Column(JSON, nullable=True)
    pagination_rule = Column(String(255), nullable=True)
    visit_order = Column(Integer, default=0)
    active = Column(Boolean, default=True)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        UniqueConstraint("spider_diagram_id", "node_key", name="uq_spider_node_key"),
        Index("idx_spider_nodes_diagram_type_active", "spider_diagram_id", "node_type", "active"),
        Index("idx_spider_nodes_diagram_visit_order", "spider_diagram_id", "visit_order"),
    )

    def __repr__(self) -> str:
        return f"<SpiderNode(id={self.id}, node_key='{self.node_key}', type='{self.node_type}')>"


class SpiderEdge:
    """Directed edge in a spider diagram between nodes."""
    __tablename__ = "spider_edges"

    id = Column(Integer, primary_key=True, autoincrement=True)
    spider_diagram_id = Column(Integer, nullable=False, index=True)
    from_node_id = Column(Integer, nullable=False)
    to_node_id = Column(Integer, nullable=False)

    traversal_type = Column(String(50), nullable=False, default="follow_link")
    link_selector = Column(String(255), nullable=True)
    condition_expression = Column(String(255), nullable=True)
    priority = Column(Integer, default=100)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        Index("idx_spider_edges_diagram_priority", "spider_diagram_id", "priority"),
        Index("idx_spider_edges_from_node", "from_node_id"),
        Index("idx_spider_edges_to_node", "to_node_id"),
    )

    def __repr__(self) -> str:
        return f"<SpiderEdge(id={self.id}, from={self.from_node_id}, to={self.to_node_id}, type='{self.traversal_type}')>"


class SiteStructureSnapshot:
    """Normalized structure snapshot per site for change detection."""
    __tablename__ = "site_structure_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_config_id = Column(Integer, nullable=False, index=True)

    source = Column(String(50), default="config_sync")
    fingerprint_hash = Column(String(64), nullable=False)
    structure_payload = Column(JSON, nullable=False)
    snapshot_notes = Column(Text, nullable=True)

    first_seen_at = Column(DateTime, default=datetime.now)
    last_seen_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        UniqueConstraint("site_config_id", "fingerprint_hash", name="uq_site_structure_snapshot_hash"),
        Index("idx_structure_snapshots_site_seen", "site_config_id", "last_seen_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<SiteStructureSnapshot(id={self.id}, site_id={self.site_config_id}, "
            f"fingerprint='{self.fingerprint_hash[:8]}...')>"
        )


class SiteStructureChange:
    """Recorded change event between two structure snapshots."""
    __tablename__ = "site_structure_changes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_config_id = Column(Integer, nullable=False, index=True)

    previous_snapshot_id = Column(Integer, nullable=True)
    current_snapshot_id = Column(Integer, nullable=False)
    previous_fingerprint_hash = Column(String(64), nullable=True)
    current_fingerprint_hash = Column(String(64), nullable=False)

    detection_source = Column(String(50), default="snapshot_diff")
    change_type = Column(String(50), default="structure_update")
    changed_sections = Column(JSON, nullable=True)
    change_summary = Column(Text, nullable=True)

    llm_review_status = Column(String(50), default="pending")
    llm_review_notes = Column(Text, nullable=True)

    detected_at = Column(DateTime, default=datetime.now)
    reviewed_at = Column(DateTime, nullable=True)
    resolved_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_structure_changes_site_status_detected", "site_config_id", "llm_review_status", "detected_at"),
        Index("idx_structure_changes_current_snapshot", "current_snapshot_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<SiteStructureChange(id={self.id}, site_id={self.site_config_id}, "
            f"status='{self.llm_review_status}', type='{self.change_type}')>"
        )


class CatalogChangeLog:
    """Audit log of source catalog mutations."""
    __tablename__ = "catalog_change_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_config_id = Column(Integer, nullable=False, index=True)

    entity_type = Column(String(50), nullable=False)
    entity_key = Column(String(500), nullable=False)
    action = Column(String(50), nullable=False)
    change_source = Column(String(50), default="config_sync")
    change_payload = Column(JSON, nullable=True)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.now, index=True)

    __table_args__ = (
        Index("idx_catalog_change_entity_created", "entity_type", "created_at"),
        Index("idx_catalog_change_site_created", "site_config_id", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<CatalogChangeLog(id={self.id}, entity_type='{self.entity_type}', "
            f"action='{self.action}', source='{self.change_source}')>"
        )


class ArticleUrlLedger:
    """URL-level scrape ledger for dedupe and historical coverage tracking."""
    __tablename__ = "article_url_ledger"

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_config_id = Column(Integer, nullable=False, index=True)

    article_url = Column(String(1000), nullable=False)
    source_url_hash = Column(String(32), nullable=False)
    canonical_url = Column(String(1000), nullable=True)

    first_seen_at = Column(DateTime, default=datetime.now)
    last_seen_at = Column(DateTime, default=datetime.now)
    first_publish_at = Column(DateTime, nullable=True)
    last_publish_at = Column(DateTime, nullable=True)
    last_scrape_date = Column(DateTime, nullable=True)

    seen_count = Column(Integer, default=1)
    total_records_emitted = Column(Integer, default=1)
    last_scraper_engine = Column(String(50), nullable=True)
    content_hash = Column(String(64), nullable=True)
    status = Column(String(30), default="active")
    last_error = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        UniqueConstraint("site_config_id", "source_url_hash", name="uq_article_url_ledger_site_hash"),
        Index("idx_article_url_ledger_site_last_seen", "site_config_id", "last_seen_at"),
        Index("idx_article_url_ledger_site_publish", "site_config_id", "last_publish_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<ArticleUrlLedger(site_id={self.site_config_id}, hash='{self.source_url_hash}', "
            f"seen={self.seen_count}, emitted={self.total_records_emitted})>"
        )


class ScrapedArticle:
    """A scraped article from a configured website."""
    __tablename__ = "scraped_articles"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # URL information (for deduplication)
    url = Column(String(1000), nullable=False)
    source_url_hash = Column(String(32), nullable=False)
    canonical_url = Column(String(1000), nullable=True)

    # Article content
    title = Column(Text, nullable=True)
    body = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    section = Column(String(255), nullable=True)
    tags = Column(JSON, nullable=True)

    # Metadata
    authors = Column(String(500), nullable=True)
    date_publish = Column(DateTime, nullable=True)
    scrape_date = Column(DateTime, default=datetime.now)
    date_download = Column(DateTime, default=datetime.now)
    image_url = Column(String(1000), nullable=True)
    image_links = Column(JSON, nullable=True)
    extra_links = Column(JSON, nullable=True)
    word_count = Column(Integer, nullable=True)
    reading_time_minutes = Column(Integer, nullable=True)
    raw_metadata = Column(JSON, nullable=True)
    content_hash = Column(String(64), nullable=True)

    # Source information
    source_domain = Column(String(255), nullable=True)
    language = Column(String(10), nullable=True)

    # Scrape metadata
    site_config_id = Column(Integer, nullable=False)
    scrape_status = Column(String(20), default="success")
    scraper_engine_used = Column(String(50), nullable=True)
    error_message = Column(Text, nullable=True)

    # Validation
    is_validated = Column(Boolean, default=False)
    validation_score = Column(Integer, nullable=True)

    __table_args__ = (
        Index("idx_url_hash_site", "source_url_hash", "site_config_id"),
        Index("idx_scraped_articles_site_scrape_date", "site_config_id", "scrape_date"),
        Index("idx_scraped_articles_site_publish_date", "site_config_id", "date_publish"),
    )

    def __repr__(self) -> str:
        return f"<ScrapedArticle(id={self.id}, title='{self.title}', url='{self.url}')>"

    @property
    def article_url_hash(self) -> str:
        """Generate MD5 hash of the article URL for deduplication."""
        import hashlib
        return hashlib.md5(self.url.encode("utf-8")).hexdigest()


class ScrapeRun:
    """Records a single scraping run."""
    __tablename__ = "scrape_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_config_id = Column(Integer, nullable=False)

    started_at = Column(DateTime, default=datetime.now)
    completed_at = Column(DateTime, nullable=True)
    status = Column(String(50), default="running")

    pages_scraped = Column(Integer, default=0)
    articles_found = Column(Integer, default=0)
    articles_saved = Column(Integer, default=0)
    articles_skipped = Column(Integer, default=0)

    error_count = Column(Integer, default=0)
    last_error = Column(Text, nullable=True)

    csv_export_path = Column(String(500), nullable=True)
    json_export_path = Column(String(500), nullable=True)

    __table_args__ = ()

    def __repr__(self) -> str:
        return f"<ScrapeRun(id={self.id}, site_id={self.site_config_id}, status='{self.status}')>"


class HistoricalScrapeProgress:
    """Progress tracking for chunked historical/backfill scraping."""
    __tablename__ = "historical_scrape_progress"

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_config_id = Column(Integer, nullable=False, index=True)

    mode = Column(String(50), default="backfill")
    chunk_id = Column(String(100), nullable=True)
    start_page = Column(Integer, nullable=True)
    end_page = Column(Integer, nullable=True)
    max_pages = Column(Integer, nullable=True)
    pages_targeted = Column(Integer, default=0)
    pages_scraped = Column(Integer, default=0)
    last_page_url = Column(String(1000), nullable=True)
    cutoff_date = Column(DateTime, nullable=True)

    articles_found = Column(Integer, default=0)
    articles_saved = Column(Integer, default=0)
    articles_skipped = Column(Integer, default=0)

    status = Column(String(50), default="running")
    error_count = Column(Integer, default=0)
    last_error = Column(Text, nullable=True)
    run_metadata = Column(JSON, nullable=True)

    started_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    completed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_historical_progress_site_mode", "site_config_id", "mode"),
        Index("idx_historical_progress_chunk_id", "chunk_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<HistoricalScrapeProgress(id={self.id}, site_id={self.site_config_id}, "
            f"status='{self.status}', pages={self.pages_scraped}/{self.pages_targeted})>"
        )


class ValidationRun:
    """Records a validation run for a scraped article."""
    __tablename__ = "validation_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scraped_article_id = Column(Integer, nullable=False)

    started_at = Column(DateTime, default=datetime.now)
    completed_at = Column(DateTime, nullable=True)
    status = Column(String(50), default="pending")

    is_validated = Column(Boolean, default=False)
    validation_score = Column(Integer, nullable=True)
    validation_notes = Column(Text, nullable=True)

    llm_model = Column(String(255), nullable=True)
    prompt_tokens = Column(Integer, nullable=True)
    completion_tokens = Column(Integer, nullable=True)

    __table_args__ = ()

    def __repr__(self) -> str:
        return f"<ValidationRun(id={self.id}, article_id={self.scraped_article_id}, status='{self.status}')>"


class LLMAssessmentRun:
    """Tracks periodic line-by-line governance reviews executed by an LLM."""
    __tablename__ = "llm_assessment_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_config_id = Column(Integer, nullable=False, index=True)

    trigger_type = Column(String(50), default="manual")
    scope = Column(String(100), default="site_config")
    status = Column(String(50), default="pending")
    llm_model = Column(String(255), nullable=True)
    prompt_version = Column(String(50), nullable=True)
    started_at = Column(DateTime, default=datetime.now)
    completed_at = Column(DateTime, nullable=True)

    total_lines = Column(Integer, default=0)
    lines_flagged = Column(Integer, default=0)
    lines_applied = Column(Integer, default=0)

    summary = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = ()

    def __repr__(self) -> str:
        return f"<LLMAssessmentRun(id={self.id}, site_id={self.site_config_id}, status='{self.status}')>"


class LLMAssessmentLine:
    """Individual line item from an LLM governance run."""
    __tablename__ = "llm_assessment_lines"

    id = Column(Integer, primary_key=True, autoincrement=True)
    assessment_run_id = Column(Integer, nullable=False, index=True)

    line_number = Column(Integer, nullable=False)
    entity_type = Column(String(100), nullable=False)
    entity_id = Column(Integer, nullable=True)
    field_name = Column(String(100), nullable=False)
    current_value = Column(Text, nullable=True)
    suggested_value = Column(Text, nullable=True)
    recommended_action = Column(String(50), default="keep")
    reasoning = Column(Text, nullable=True)
    confidence_score = Column(Float, nullable=True)

    status = Column(String(50), default="pending")
    reviewed_by = Column(String(255), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    applied_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        UniqueConstraint("assessment_run_id", "line_number", name="uq_assessment_line_number"),
    )

    def __repr__(self) -> str:
        return (
            f"<LLMAssessmentLine(run_id={self.assessment_run_id}, line={self.line_number}, "
            f"field='{self.field_name}', action='{self.recommended_action}')>"
        )


class ScrapeLog:
    """Detailed log entries for scraping operations."""
    __tablename__ = "scrape_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_config_id = Column(Integer, nullable=False)
    scrape_run_id = Column(Integer, nullable=True)

    timestamp = Column(DateTime, default=datetime.now)
    level = Column(String(20), default="INFO")

    event_type = Column(String(50), nullable=True)
    message = Column(Text, nullable=False)
    extra_data = Column(JSON, nullable=True)

    __table_args__ = (
        Index("idx_logs_timestamp", "timestamp"),
    )

    def __repr__(self) -> str:
        return f"<ScrapeLog(id={self.id}, level='{self.level}', message='{self.message[:50]}...')>"