"""Database models for the news scraper platform."""
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

from ..database.session import Base, SpiderBase


class SiteConfig(Base):
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

    # Relationships
    technologies = relationship("SiteTechnology", back_populates="site_config", cascade="all, delete-orphan")
    scrape_strategy = relationship("ScrapeStrategy", back_populates="site_config", cascade="all, delete-orphan", uselist=False)
    articles = relationship("ScrapedArticle", back_populates="site_config", cascade="all, delete-orphan")
    article_url_ledger = relationship("ArticleUrlLedger", back_populates="site_config", cascade="all, delete-orphan")
    catalog_change_events = relationship("CatalogChangeLog", back_populates="site_config", cascade="all, delete-orphan")
    scrape_runs = relationship("ScrapeRun", back_populates="site_config", cascade="all, delete-orphan")
    scrape_logs = relationship("ScrapeLog", back_populates="site_config", cascade="all, delete-orphan")
    llm_assessment_runs = relationship("LLMAssessmentRun", back_populates="site_config", cascade="all, delete-orphan")
    historical_progress_runs = relationship(
        "HistoricalScrapeProgress",
        back_populates="site_config",
        cascade="all, delete-orphan",
    )

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


class SiteCategory(SpiderBase):
    """
    A category within a site configuration.

    Supports per-category pagination tuning (max pages/start page/pattern).
    """

    __tablename__ = "site_categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_config_id = Column(Integer, nullable=False, index=True, comment="Primary DB site_configs.id reference")

    name = Column(String(255), nullable=False, comment="Category name (e.g., 'World', 'Tech')")
    url = Column(String(500), nullable=False, comment="Category URL")
    max_pages = Column(Integer, default=1, comment="Max pages for this category")
    page_url_pattern = Column(String(500), nullable=True, comment="Category-specific page URL pattern")
    start_page = Column(Integer, default=1, comment="Starting page number for this category")
    active = Column(Boolean, default=True, comment="Whether this category is active for scraping")

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        Index("idx_site_categories_site_active", "site_config_id", "active"),
        Index("idx_site_categories_site_start_page", "site_config_id", "start_page"),
    )

    def __repr__(self) -> str:
        return f"<SiteCategory(id={self.id}, name='{self.name}', site_config_id={self.site_config_id})>"


class CategoryCrawlState(SpiderBase):
    """
    Crawl-state record keeping for each site/category combination.

    This table tracks category coverage and pagination progress without storing
    article payloads.
    """

    __tablename__ = "category_crawl_state"

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_config_id = Column(Integer, nullable=False, index=True, comment="Primary DB site_configs.id reference")
    site_category_id = Column(Integer, nullable=True, index=True, comment="Spider DB site_categories.id reference")

    category_name = Column(String(255), nullable=True, comment="Category label")
    category_url = Column(String(1000), nullable=False, comment="Category/listing URL")
    last_page_scraped = Column(Integer, nullable=True, comment="Most recent page number scraped")
    max_page_seen = Column(Integer, nullable=True, comment="Highest page number encountered")
    last_page_url = Column(String(1000), nullable=True, comment="Most recent listing page URL")

    total_listing_pages_scraped = Column(Integer, default=0, comment="Total listing pages scraped")
    total_links_discovered = Column(Integer, default=0, comment="Total article links discovered")
    total_records_emitted = Column(Integer, default=0, comment="Total JSON records emitted")

    last_mode = Column(String(50), nullable=True, comment="Last mode used (current/historical)")
    last_chunk_id = Column(String(100), nullable=True, comment="Most recent chunk identifier")
    last_scraped_at = Column(DateTime, nullable=True, comment="Most recent scrape timestamp")
    notes = Column(Text, nullable=True, comment="Optional operator notes")

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


class SiteTechnology(Base):
    """Detected or manually configured technologies for a website."""

    __tablename__ = "site_technologies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_config_id = Column(Integer, ForeignKey("site_configs.id"), nullable=False, index=True)

    technology_name = Column(String(255), nullable=False, comment="Technology name (WordPress, React, Cloudflare)")
    technology_type = Column(String(100), nullable=True, comment="Category (CMS, framework, CDN, WAF, analytics)")
    version = Column(String(100), nullable=True, comment="Detected version if available")
    confidence_score = Column(Float, nullable=True, comment="Detection confidence from 0.0 to 1.0")
    detection_source = Column(String(100), nullable=True, comment="How it was detected: headers, html, manual, llm")
    notes = Column(Text, nullable=True, comment="Additional details")

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    site_config = relationship("SiteConfig", back_populates="technologies")

    __table_args__ = (
        UniqueConstraint("site_config_id", "technology_name", "version", name="uq_site_technology"),
    )

    def __repr__(self) -> str:
        return f"<SiteTechnology(site_id={self.site_config_id}, technology='{self.technology_name}')>"


class ScrapeStrategy(Base):
    """
    Scraping and anti-blocking strategy for a website.

    Stores which scraper stack to use and what protections need handling.
    """

    __tablename__ = "scrape_strategies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_config_id = Column(Integer, ForeignKey("site_configs.id"), nullable=False, unique=True, index=True)

    scraper_engine = Column(
        String(50),
        default="scrapling",
        comment="Primary scraper engine for this site.",
    )
    fallback_engine_chain = Column(
        JSON,
        nullable=True,
        comment="Ordered fallback engines (e.g., ['pydoll', 'selenium']).",
    )
    content_parser = Column(
        String(50),
        default="beautifulsoup",
        comment="Primary HTML parser (beautifulsoup, lxml).",
    )
    browser_automation_tool = Column(String(50), nullable=True, comment="Selenium, Playwright, Puppeteer, etc.")
    rendering_required = Column(Boolean, default=False, comment="Whether JavaScript rendering is required")
    requires_proxy = Column(Boolean, default=False, comment="Whether a proxy is required")
    proxy_region = Column(String(100), nullable=True, comment="Preferred proxy region/country")
    login_required = Column(Boolean, default=False, comment="Whether login/session auth is required")
    auth_strategy = Column(String(255), nullable=True, comment="Auth strategy (cookies, oauth, login-form)")
    anti_bot_protection = Column(String(255), nullable=True, comment="Protection provider (Cloudflare, Akamai, DataDome)")
    blocking_signals = Column(JSON, nullable=True, comment="Observed block signatures/captchas/errors")
    bypass_techniques = Column(JSON, nullable=True, comment="Techniques to handle blocks")
    request_headers = Column(JSON, nullable=True, comment="Header overrides required for this site")
    cookie_preset = Column(JSON, nullable=True, comment="Known cookie values or templates")
    rate_limit_per_minute = Column(Integer, nullable=True, comment="Max requests per minute for stable scraping")
    notes = Column(Text, nullable=True, comment="Operational notes and constraints")

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    site_config = relationship("SiteConfig", back_populates="scrape_strategy")

    def __repr__(self) -> str:
        return f"<ScrapeStrategy(site_id={self.site_config_id}, engine='{self.scraper_engine}')>"


class SpiderDiagram(SpiderBase):
    """Spider flow definition for exact crawl/extract traversal."""

    __tablename__ = "spider_diagrams"

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_config_id = Column(Integer, nullable=False, index=True, comment="Primary DB site_configs.id reference")

    name = Column(String(255), nullable=False, comment="Diagram name (e.g., 'default_news_flow')")
    version = Column(Integer, default=1, comment="Version number")
    entrypoint_url = Column(String(1000), nullable=False, comment="Primary crawl entry URL")
    is_active = Column(Boolean, default=True, comment="Whether this diagram is active")
    notes = Column(Text, nullable=True, comment="Design notes for operators/LLM")

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    nodes = relationship("SpiderNode", back_populates="spider_diagram", cascade="all, delete-orphan")
    edges = relationship("SpiderEdge", back_populates="spider_diagram", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("site_config_id", "name", "version", name="uq_spider_diagram_version"),
        Index("idx_spider_diagrams_site_active_version", "site_config_id", "is_active", "version"),
    )

    def __repr__(self) -> str:
        return f"<SpiderDiagram(id={self.id}, site_id={self.site_config_id}, name='{self.name}', version={self.version})>"


class SpiderNode(SpiderBase):
    """Node in a spider diagram representing a crawl/extraction step."""

    __tablename__ = "spider_nodes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    spider_diagram_id = Column(Integer, ForeignKey("spider_diagrams.id"), nullable=False, index=True)

    node_key = Column(String(100), nullable=False, comment="Stable key (seed, category, pagination, article)")
    node_type = Column(String(50), nullable=False, comment="Node type: seed, category, pagination, article, extract")
    url_pattern = Column(String(1000), nullable=True, comment="URL or URL pattern for this node")
    selector = Column(String(255), nullable=True, comment="Selector used at this node")
    extraction_target = Column(JSON, nullable=True, comment="Fields to extract at this node")
    pagination_rule = Column(String(255), nullable=True, comment="Pagination pattern/rule (e.g. ?page={page})")
    visit_order = Column(Integer, default=0, comment="Traversal order hint")
    active = Column(Boolean, default=True, comment="Whether this node is active")
    notes = Column(Text, nullable=True, comment="Operator notes")

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    spider_diagram = relationship("SpiderDiagram", back_populates="nodes")
    outgoing_edges = relationship(
        "SpiderEdge",
        foreign_keys="SpiderEdge.from_node_id",
        back_populates="from_node",
        cascade="all, delete-orphan",
    )
    incoming_edges = relationship(
        "SpiderEdge",
        foreign_keys="SpiderEdge.to_node_id",
        back_populates="to_node",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("spider_diagram_id", "node_key", name="uq_spider_node_key"),
        Index("idx_spider_nodes_diagram_type_active", "spider_diagram_id", "node_type", "active"),
        Index("idx_spider_nodes_diagram_visit_order", "spider_diagram_id", "visit_order"),
    )

    def __repr__(self) -> str:
        return f"<SpiderNode(id={self.id}, node_key='{self.node_key}', type='{self.node_type}')>"


class SpiderEdge(SpiderBase):
    """Directed edge in a spider diagram between nodes."""

    __tablename__ = "spider_edges"

    id = Column(Integer, primary_key=True, autoincrement=True)
    spider_diagram_id = Column(Integer, ForeignKey("spider_diagrams.id"), nullable=False, index=True)
    from_node_id = Column(Integer, ForeignKey("spider_nodes.id"), nullable=False)
    to_node_id = Column(Integer, ForeignKey("spider_nodes.id"), nullable=False)

    traversal_type = Column(String(50), nullable=False, default="follow_link", comment="follow_link, paginate, extract")
    link_selector = Column(String(255), nullable=True, comment="Selector used to resolve next links")
    condition_expression = Column(String(255), nullable=True, comment="Condition for traversing this edge")
    priority = Column(Integer, default=100, comment="Lower value means higher traversal priority")
    notes = Column(Text, nullable=True, comment="Additional traversal context")

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    spider_diagram = relationship("SpiderDiagram", back_populates="edges")
    from_node = relationship("SpiderNode", foreign_keys=[from_node_id], back_populates="outgoing_edges")
    to_node = relationship("SpiderNode", foreign_keys=[to_node_id], back_populates="incoming_edges")

    __table_args__ = (
        Index("idx_spider_edges_diagram_priority", "spider_diagram_id", "priority"),
        Index("idx_spider_edges_from_node", "from_node_id"),
        Index("idx_spider_edges_to_node", "to_node_id"),
    )

    def __repr__(self) -> str:
        return f"<SpiderEdge(id={self.id}, from={self.from_node_id}, to={self.to_node_id}, type='{self.traversal_type}')>"


class SiteStructureSnapshot(SpiderBase):
    """
    Normalized structure snapshot per site for change detection.

    Stored in Spider DB to support scraper planning and LLM structure audits.
    """

    __tablename__ = "site_structure_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_config_id = Column(Integer, nullable=False, index=True, comment="Primary DB site_configs.id reference")

    source = Column(String(50), default="config_sync", comment="snapshot source: config_sync, scrape_probe, llm_apply")
    fingerprint_hash = Column(String(64), nullable=False, comment="SHA-256 hash of normalized structure payload")
    structure_payload = Column(JSON, nullable=False, comment="Canonical structure payload used for hashing")
    snapshot_notes = Column(Text, nullable=True, comment="Operator/LLM notes for this snapshot")

    first_seen_at = Column(DateTime, default=datetime.now)
    last_seen_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    changes_from = relationship(
        "SiteStructureChange",
        foreign_keys="SiteStructureChange.previous_snapshot_id",
        back_populates="previous_snapshot",
    )
    changes_to = relationship(
        "SiteStructureChange",
        foreign_keys="SiteStructureChange.current_snapshot_id",
        back_populates="current_snapshot",
    )

    __table_args__ = (
        UniqueConstraint("site_config_id", "fingerprint_hash", name="uq_site_structure_snapshot_hash"),
        Index("idx_structure_snapshots_site_seen", "site_config_id", "last_seen_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<SiteStructureSnapshot(id={self.id}, site_id={self.site_config_id}, "
            f"fingerprint='{self.fingerprint_hash[:8]}...')>"
        )


class SiteStructureChange(SpiderBase):
    """
    Recorded change event between two structure snapshots.

    This is the main queue for LLM structure verification and remediation.
    """

    __tablename__ = "site_structure_changes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_config_id = Column(Integer, nullable=False, index=True, comment="Primary DB site_configs.id reference")

    previous_snapshot_id = Column(Integer, ForeignKey("site_structure_snapshots.id"), nullable=True)
    current_snapshot_id = Column(Integer, ForeignKey("site_structure_snapshots.id"), nullable=False)
    previous_fingerprint_hash = Column(String(64), nullable=True)
    current_fingerprint_hash = Column(String(64), nullable=False)

    detection_source = Column(String(50), default="snapshot_diff", comment="How change was detected")
    change_type = Column(String(50), default="structure_update", comment="structure_update, selector_change, pagination_change")
    changed_sections = Column(JSON, nullable=True, comment="Top-level structure sections that changed")
    change_summary = Column(Text, nullable=True, comment="Human-readable summary of detected change")

    llm_review_status = Column(
        String(50),
        default="pending",
        comment="pending, in_review, confirmed, ignored, remediated",
    )
    llm_review_notes = Column(Text, nullable=True)

    detected_at = Column(DateTime, default=datetime.now)
    reviewed_at = Column(DateTime, nullable=True)
    resolved_at = Column(DateTime, nullable=True)

    previous_snapshot = relationship(
        "SiteStructureSnapshot",
        foreign_keys=[previous_snapshot_id],
        back_populates="changes_from",
    )
    current_snapshot = relationship(
        "SiteStructureSnapshot",
        foreign_keys=[current_snapshot_id],
        back_populates="changes_to",
    )

    __table_args__ = (
        Index("idx_structure_changes_site_status_detected", "site_config_id", "llm_review_status", "detected_at"),
        Index("idx_structure_changes_current_snapshot", "current_snapshot_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<SiteStructureChange(id={self.id}, site_id={self.site_config_id}, "
            f"status='{self.llm_review_status}', type='{self.change_type}')>"
        )


class CatalogChangeLog(Base):
    """
    Audit log of source catalog mutations.

    Captures when sites/categories/strategies are added or updated so an LLM or
    operator can review schema/config drift over time.
    """

    __tablename__ = "catalog_change_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_config_id = Column(Integer, ForeignKey("site_configs.id"), nullable=True, index=True)

    entity_type = Column(String(50), nullable=False, comment="site_config, site_category, strategy, technology")
    entity_key = Column(String(500), nullable=False, comment="Stable identifier (url/name/id)")
    action = Column(String(50), nullable=False, comment="created, updated, deactivated")
    change_source = Column(String(50), default="config_sync", comment="manual, config_sync, llm_apply")
    change_payload = Column(JSON, nullable=True, comment="Structured details for the change")
    notes = Column(Text, nullable=True, comment="Optional human notes")

    created_at = Column(DateTime, default=datetime.now, index=True)

    site_config = relationship("SiteConfig", back_populates="catalog_change_events")

    __table_args__ = (
        Index("idx_catalog_change_entity_created", "entity_type", "created_at"),
        Index("idx_catalog_change_site_created", "site_config_id", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<CatalogChangeLog(id={self.id}, entity_type='{self.entity_type}', "
            f"action='{self.action}', source='{self.change_source}')>"
        )


class ArticleUrlLedger(Base):
    """
    URL-level scrape ledger for dedupe and historical coverage tracking.

    This table intentionally stores only URL/hash level state and counters;
    article body/title payloads stay out of SQL and are returned as JSON.
    """

    __tablename__ = "article_url_ledger"

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_config_id = Column(Integer, ForeignKey("site_configs.id"), nullable=False, index=True)

    article_url = Column(String(1000), nullable=False, comment="Observed article URL")
    source_url_hash = Column(String(32), nullable=False, comment="MD5 hash for dedupe")
    canonical_url = Column(String(1000), nullable=True, comment="Latest observed canonical URL")

    first_seen_at = Column(DateTime, default=datetime.now, comment="First time discovered")
    last_seen_at = Column(DateTime, default=datetime.now, comment="Most recent discovery")
    first_publish_at = Column(DateTime, nullable=True, comment="Earliest observed publish datetime")
    last_publish_at = Column(DateTime, nullable=True, comment="Latest observed publish datetime")
    last_scrape_date = Column(DateTime, nullable=True, comment="Most recent scrape datetime")

    seen_count = Column(Integer, default=1, comment="Total times this URL was discovered")
    total_records_emitted = Column(Integer, default=1, comment="Total times emitted to JSON output")
    last_scraper_engine = Column(String(50), nullable=True, comment="Engine used last time emitted")
    content_hash = Column(String(64), nullable=True, comment="Latest normalized content hash")
    status = Column(String(30), default="active", comment="active, blocked, skipped")
    last_error = Column(Text, nullable=True, comment="Last observed scrape error")

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    site_config = relationship("SiteConfig", back_populates="article_url_ledger")

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


class ScrapedArticle(Base):
    """
    A scraped article from a configured website.

    Uses URL-based deduplication via MD5 hash stored in source_url_hash.
    """

    __tablename__ = "scraped_articles"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # URL information (for deduplication)
    url = Column(String(1000), nullable=False, comment="Full article URL")
    source_url_hash = Column(String(32), nullable=False, index=True, comment="MD5 hash of URL for deduplication")
    canonical_url = Column(String(1000), nullable=True, comment="Canonical URL for the article")

    # Article content
    title = Column(Text, nullable=True, comment="Article title")
    body = Column(Text, nullable=True, comment="Main article content")
    description = Column(Text, nullable=True, comment="Article excerpt/description")
    section = Column(String(255), nullable=True, comment="Section/category of article")
    tags = Column(JSON, nullable=True, comment="Tag/topic labels")

    # Metadata
    authors = Column(String(500), nullable=True, comment="Comma-separated author names")
    date_publish = Column(DateTime, nullable=True, comment="Publication date")
    scrape_date = Column(DateTime, default=datetime.now, comment="When the scraper captured this article")
    date_download = Column(DateTime, default=datetime.now, comment="Legacy download timestamp")
    image_url = Column(String(1000), nullable=True, comment="Featured image URL")
    image_links = Column(JSON, nullable=True, comment="All discovered image links")
    extra_links = Column(JSON, nullable=True, comment="Extra in-article links")
    word_count = Column(Integer, nullable=True, comment="Estimated word count of article body")
    reading_time_minutes = Column(Integer, nullable=True, comment="Estimated reading time")
    raw_metadata = Column(JSON, nullable=True, comment="Captured meta tags and structured data")
    content_hash = Column(String(64), nullable=True, comment="Hash of normalized content")

    # Source information
    source_domain = Column(String(255), nullable=True, comment="Source domain (e.g., example.com)")
    language = Column(String(10), nullable=True, comment="Detected language code")

    # Scrape metadata
    site_config_id = Column(Integer, ForeignKey("site_configs.id"), nullable=False, comment="ID of the SiteConfig that scraped this article")
    scrape_status = Column(String(20), default="success", comment="Status: success, failed, skipped")
    scraper_engine_used = Column(String(50), nullable=True, comment="Engine used for successful fetch (scrapling/pydoll/selenium)")
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


class ScrapeRun(Base):
    """
    Records a single scraping run.
    Tracks what was scraped, when, and how many articles were found/saved.
    """

    __tablename__ = "scrape_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)

    site_config_id = Column(Integer, ForeignKey("site_configs.id"), nullable=False, comment="Site that was scraped")
    scrape_logs = relationship("ScrapeLog", back_populates="scrape_run", cascade="all, delete-orphan")

    started_at = Column(DateTime, default=datetime.now, comment="When the scrape run started")
    completed_at = Column(DateTime, nullable=True, comment="When the scrape run finished")
    status = Column(String(50), default="running", comment="Run status: running, success, failed, partial")

    pages_scraped = Column(Integer, default=0, comment="Number of listing pages scraped")
    articles_found = Column(Integer, default=0, comment="Number of article URLs found")
    articles_saved = Column(Integer, default=0, comment="Number of new articles saved")
    articles_skipped = Column(Integer, default=0, comment="Number of duplicate articles skipped")

    error_count = Column(Integer, default=0, comment="Number of errors encountered")
    last_error = Column(Text, nullable=True, comment="Last error message if failed")

    csv_export_path = Column(String(500), nullable=True, comment="Path to CSV export file")
    json_export_path = Column(String(500), nullable=True, comment="Path to JSON export file")

    site_config = relationship("SiteConfig", back_populates="scrape_runs")

    def __repr__(self) -> str:
        return f"<ScrapeRun(id={self.id}, site_id={self.site_config_id}, status='{self.status}')>"


class HistoricalScrapeProgress(Base):
    """
    Progress tracking for chunked historical/backfill scraping.

    This table supports piece-wise scraping runs (e.g. Apify actor chunks) and
    provides resumable visibility into how much historical coverage was completed.
    """

    __tablename__ = "historical_scrape_progress"

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_config_id = Column(Integer, ForeignKey("site_configs.id"), nullable=False, index=True)

    mode = Column(String(50), default="backfill", comment="Scrape mode (backfill/historical)")
    chunk_id = Column(
        String(100),
        nullable=True,
        comment="External chunk identifier (e.g., actor batch id)",
    )
    start_page = Column(Integer, nullable=True, comment="Requested start page")
    end_page = Column(Integer, nullable=True, comment="Requested end page")
    max_pages = Column(Integer, nullable=True, comment="Max pages requested for this run")
    pages_targeted = Column(Integer, default=0, comment="Total listing pages planned for this run")
    pages_scraped = Column(Integer, default=0, comment="Listing pages completed")
    last_page_url = Column(String(1000), nullable=True, comment="Last listing page processed")
    cutoff_date = Column(DateTime, nullable=True, comment="Historical cutoff date constraint")

    articles_found = Column(Integer, default=0, comment="Article links discovered during this run")
    articles_saved = Column(Integer, default=0, comment="Articles newly persisted during this run")
    articles_skipped = Column(Integer, default=0, comment="Duplicate/ignored articles during this run")

    status = Column(String(50), default="running", comment="running, partial, complete, failed")
    error_count = Column(Integer, default=0, comment="Number of errors captured")
    last_error = Column(Text, nullable=True, comment="Last error observed")
    run_metadata = Column(JSON, nullable=True, comment="Arbitrary run metadata (actor input, chunk notes)")

    started_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    completed_at = Column(DateTime, nullable=True)

    site_config = relationship("SiteConfig", back_populates="historical_progress_runs")

    __table_args__ = (
        Index("idx_historical_progress_site_mode", "site_config_id", "mode"),
        Index("idx_historical_progress_chunk_id", "chunk_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<HistoricalScrapeProgress(id={self.id}, site_id={self.site_config_id}, "
            f"status='{self.status}', pages={self.pages_scraped}/{self.pages_targeted})>"
        )


class ValidationRun(Base):
    """
    Records a validation run for a scraped article.
    Used for LLM-assisted validation workflow.
    """

    __tablename__ = "validation_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)

    scraped_article_id = Column(Integer, ForeignKey("scraped_articles.id"), nullable=False, comment="Article being validated")

    article = relationship("ScrapedArticle", back_populates="validation_runs")

    started_at = Column(DateTime, default=datetime.now, comment="When validation started")
    completed_at = Column(DateTime, nullable=True, comment="When validation finished")
    status = Column(String(50), default="pending", comment="Status: pending, in_progress, complete, failed")

    is_validated = Column(Boolean, default=False, comment="Whether the article passed validation")
    validation_score = Column(Integer, nullable=True, comment="LLM validation score (0-100)")
    validation_notes = Column(Text, nullable=True, comment="Notes from validation")

    llm_model = Column(String(255), nullable=True, comment="LLM model used for validation")
    prompt_tokens = Column(Integer, nullable=True, comment="Number of input tokens")
    completion_tokens = Column(Integer, nullable=True, comment="Number of output tokens")

    def __repr__(self) -> str:
        return f"<ValidationRun(id={self.id}, article_id={self.scraped_article_id}, status='{self.status}')>"


class LLMAssessmentRun(Base):
    """
    Tracks periodic line-by-line governance reviews executed by an LLM.
    """

    __tablename__ = "llm_assessment_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_config_id = Column(Integer, ForeignKey("site_configs.id"), nullable=False, index=True)

    trigger_type = Column(String(50), default="manual", comment="manual, scheduled, post_scrape")
    scope = Column(String(100), default="site_config", comment="Review scope")
    status = Column(String(50), default="pending", comment="pending, running, complete, failed")
    llm_model = Column(String(255), nullable=True, comment="Model used for assessment")
    prompt_version = Column(String(50), nullable=True, comment="Prompt/version used")
    started_at = Column(DateTime, default=datetime.now, comment="When assessment started")
    completed_at = Column(DateTime, nullable=True, comment="When assessment completed")

    total_lines = Column(Integer, default=0, comment="Total line items in the run")
    lines_flagged = Column(Integer, default=0, comment="Line items flagged for change")
    lines_applied = Column(Integer, default=0, comment="Line items applied to DB")

    summary = Column(Text, nullable=True, comment="Review summary")
    error_message = Column(Text, nullable=True, comment="Error details if run failed")

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    site_config = relationship("SiteConfig", back_populates="llm_assessment_runs")
    lines = relationship("LLMAssessmentLine", back_populates="assessment_run", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<LLMAssessmentRun(id={self.id}, site_id={self.site_config_id}, status='{self.status}')>"


class LLMAssessmentLine(Base):
    """
    Individual line item from an LLM governance run.

    One row per field/value pair assessed.
    """

    __tablename__ = "llm_assessment_lines"

    id = Column(Integer, primary_key=True, autoincrement=True)
    assessment_run_id = Column(Integer, ForeignKey("llm_assessment_runs.id"), nullable=False, index=True)

    line_number = Column(Integer, nullable=False, comment="Stable line number within the assessment run")
    entity_type = Column(String(100), nullable=False, comment="site_config, site_category, strategy, spider_node, article")
    entity_id = Column(Integer, nullable=True, comment="Primary key of assessed entity")
    field_name = Column(String(100), nullable=False, comment="Field that was assessed")
    current_value = Column(Text, nullable=True, comment="Serialized current value")
    suggested_value = Column(Text, nullable=True, comment="Serialized suggested value")
    recommended_action = Column(String(50), default="keep", comment="keep, update, remove, review")
    reasoning = Column(Text, nullable=True, comment="LLM reasoning")
    confidence_score = Column(Float, nullable=True, comment="0.0 to 1.0 confidence")

    status = Column(String(50), default="pending", comment="pending, approved, applied, rejected")
    reviewed_by = Column(String(255), nullable=True, comment="Reviewer identifier")
    reviewed_at = Column(DateTime, nullable=True)
    applied_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    assessment_run = relationship("LLMAssessmentRun", back_populates="lines")

    __table_args__ = (
        UniqueConstraint("assessment_run_id", "line_number", name="uq_assessment_line_number"),
    )

    def __repr__(self) -> str:
        return (
            f"<LLMAssessmentLine(run_id={self.assessment_run_id}, line={self.line_number}, "
            f"field='{self.field_name}', action='{self.recommended_action}')>"
        )


class ScrapeLog(Base):
    """
    Detailed log entries for scraping operations.
    Tracks individual page fetches, errors, and important events.
    """

    __tablename__ = "scrape_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)

    site_config_id = Column(Integer, ForeignKey("site_configs.id"), nullable=False, comment="Site being scraped")
    scrape_run_id = Column(Integer, ForeignKey("scrape_runs.id"), nullable=True, comment="Related scrape run")

    timestamp = Column(DateTime, default=datetime.now, index=True)
    level = Column(String(20), default="INFO", comment="Log level: DEBUG, INFO, WARNING, ERROR")

    event_type = Column(String(50), nullable=True, comment="Type of event: page_fetch, article_found, scrape_start, etc.")
    message = Column(Text, nullable=False, comment="Log message")
    extra_data = Column(JSON, nullable=True, comment="Additional structured data (JSON)")

    site_config = relationship("SiteConfig", back_populates="scrape_logs")
    scrape_run = relationship("ScrapeRun", back_populates="scrape_logs")

    def __repr__(self) -> str:
        return f"<ScrapeLog(id={self.id}, level='{self.level}', message='{self.message[:50]}...')>"
