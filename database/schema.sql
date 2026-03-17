-- =============================================================================
-- The Rise of the Phoenix - Database Schema
-- Primary and Spider Database Tables
-- =============================================================================

-- =============================================================================
-- PRIMARY DATABASE TABLES
-- =============================================================================

-- Site configurations (primary DB)
CREATE TABLE IF NOT EXISTS site_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(255) NOT NULL,
    url VARCHAR(500) NOT NULL UNIQUE,
    domain VARCHAR(255),

    -- Website metadata
    country VARCHAR(100),
    location VARCHAR(100),
    description TEXT,
    language VARCHAR(10) DEFAULT 'en',

    -- Server/discovery metadata
    server_header VARCHAR(255),
    server_vendor VARCHAR(255),
    hosting_provider VARCHAR(255),
    ip_address VARCHAR(64),
    technology_stack_summary TEXT,

    -- Notes
    notes TEXT,

    -- Scraping configuration
    category_url_pattern VARCHAR(500),
    num_pages_to_scrape INTEGER DEFAULT 1,

    -- XPath/CSS selectors for content extraction
    article_selector VARCHAR(255),
    title_selector VARCHAR(255),
    author_selector VARCHAR(255),
    date_selector VARCHAR(255),
    body_selector VARCHAR(255),

    -- Scraper configuration
    preferred_scraper_type VARCHAR(50) DEFAULT 'scrapling',
    uses_javascript BOOLEAN DEFAULT FALSE,
    active BOOLEAN DEFAULT TRUE,

    -- Status flags
    status VARCHAR(50) DEFAULT 'active',

    -- Timestamps
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_scraped DATETIME,
    last_successful_scrape DATETIME,
    last_validation_time DATETIME,

    INDEX idx_site_configs_country (country),
    INDEX idx_site_configs_active_country (active, country),
    INDEX idx_site_configs_active_language (active, language)
);

-- Detected technologies for a website (primary DB)
CREATE TABLE IF NOT EXISTS site_technologies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_config_id INTEGER NOT NULL,
    technology_name VARCHAR(255) NOT NULL,
    technology_type VARCHAR(100),
    version VARCHAR(100),
    confidence_score FLOAT,
    detection_source VARCHAR(100),
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(site_config_id, technology_name, version),
    FOREIGN KEY (site_config_id) REFERENCES site_configs(id) ON DELETE CASCADE
);

-- Scraping and anti-blocking strategy for a website (primary DB)
CREATE TABLE IF NOT EXISTS scrape_strategies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_config_id INTEGER NOT NULL UNIQUE,
    scraper_engine VARCHAR(50) DEFAULT 'scrapling',
    fallback_engine_chain JSON,
    content_parser VARCHAR(50) DEFAULT 'beautifulsoup',
    browser_automation_tool VARCHAR(50),
    rendering_required BOOLEAN DEFAULT FALSE,
    requires_proxy BOOLEAN DEFAULT FALSE,
    proxy_region VARCHAR(100),
    login_required BOOLEAN DEFAULT FALSE,
    auth_strategy VARCHAR(255),
    anti_bot_protection VARCHAR(255),
    blocking_signals JSON,
    bypass_techniques JSON,
    request_headers JSON,
    cookie_preset JSON,
    rate_limit_per_minute INTEGER,
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (site_config_id) REFERENCES site_configs(id) ON DELETE CASCADE
);

-- URL-level scrape ledger for dedupe and tracking (primary DB)
CREATE TABLE IF NOT EXISTS article_url_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_config_id INTEGER NOT NULL,
    article_url VARCHAR(1000) NOT NULL,
    source_url_hash VARCHAR(32) NOT NULL,
    canonical_url VARCHAR(1000),

    first_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    first_publish_at DATETIME,
    last_publish_at DATETIME,
    last_scrape_date DATETIME,

    seen_count INTEGER DEFAULT 1,
    total_records_emitted INTEGER DEFAULT 1,
    last_scraper_engine VARCHAR(50),
    content_hash VARCHAR(64),
    status VARCHAR(30) DEFAULT 'active',
    last_error TEXT,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(site_config_id, source_url_hash),
    INDEX idx_article_url_ledger_site_last_seen (site_config_id, last_seen_at),
    INDEX idx_article_url_ledger_site_publish (site_config_id, last_publish_at),
    FOREIGN KEY (site_config_id) REFERENCES site_configs(id) ON DELETE CASCADE
);

-- Scraped article content (primary DB)
CREATE TABLE IF NOT EXISTS scraped_articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url VARCHAR(1000) NOT NULL,
    source_url_hash VARCHAR(32) NOT NULL,
    canonical_url VARCHAR(1000),

    -- Article content
    title TEXT,
    body TEXT,
    description TEXT,
    section VARCHAR(255),
    tags JSON,

    -- Metadata
    authors VARCHAR(500),
    date_publish DATETIME,
    scrape_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    date_download DATETIME DEFAULT CURRENT_TIMESTAMP,
    image_url VARCHAR(1000),
    image_links JSON,
    extra_links JSON,
    word_count INTEGER,
    reading_time_minutes INTEGER,
    raw_metadata JSON,
    content_hash VARCHAR(64),

    -- Source information
    source_domain VARCHAR(255),
    language VARCHAR(10),

    -- Scrape metadata
    site_config_id INTEGER NOT NULL,
    scrape_status VARCHAR(20) DEFAULT 'success',
    scraper_engine_used VARCHAR(50),
    error_message TEXT,

    -- Validation
    is_validated BOOLEAN DEFAULT FALSE,
    validation_score INTEGER,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_url_hash_site (source_url_hash, site_config_id),
    INDEX idx_scraped_articles_site_scrape_date (site_config_id, scrape_date),
    INDEX idx_scraped_articles_site_publish_date (site_config_id, date_publish),
    FOREIGN KEY (site_config_id) REFERENCES site_configs(id) ON DELETE CASCADE
);

-- Scrape run records (primary DB)
CREATE TABLE IF NOT EXISTS scrape_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_config_id INTEGER NOT NULL,

    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME,
    status VARCHAR(50) DEFAULT 'running',

    pages_scraped INTEGER DEFAULT 0,
    articles_found INTEGER DEFAULT 0,
    articles_saved INTEGER DEFAULT 0,
    articles_skipped INTEGER DEFAULT 0,

    error_count INTEGER DEFAULT 0,
    last_error TEXT,

    csv_export_path VARCHAR(500),
    json_export_path VARCHAR(500),

    FOREIGN KEY (site_config_id) REFERENCES site_configs(id) ON DELETE CASCADE
);

-- Historical scrape progress for backfill tracking (primary DB)
CREATE TABLE IF NOT EXISTS historical_scrape_progress (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_config_id INTEGER NOT NULL,

    mode VARCHAR(50) DEFAULT 'backfill',
    chunk_id VARCHAR(100),
    start_page INTEGER,
    end_page INTEGER,
    max_pages INTEGER,
    pages_targeted INTEGER DEFAULT 0,
    pages_scraped INTEGER DEFAULT 0,
    last_page_url VARCHAR(1000),
    cutoff_date DATETIME,

    articles_found INTEGER DEFAULT 0,
    articles_saved INTEGER DEFAULT 0,
    articles_skipped INTEGER DEFAULT 0,

    status VARCHAR(50) DEFAULT 'running',
    error_count INTEGER DEFAULT 0,
    last_error TEXT,
    run_metadata JSON,

    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME,

    INDEX idx_historical_progress_site_mode (site_config_id, mode),
    INDEX idx_historical_progress_chunk_id (chunk_id),
    FOREIGN KEY (site_config_id) REFERENCES site_configs(id) ON DELETE CASCADE
);

-- Catalog change log for audit tracking (primary DB)
CREATE TABLE IF NOT EXISTS catalog_change_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_config_id INTEGER,
    entity_type VARCHAR(50) NOT NULL,
    entity_key VARCHAR(500) NOT NULL,
    action VARCHAR(50) NOT NULL,
    change_source VARCHAR(50) DEFAULT 'config_sync',
    change_payload JSON,
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (site_config_id) REFERENCES site_configs(id) ON DELETE SET NULL,
    INDEX idx_catalog_change_entity_created (entity_type, created_at),
    INDEX idx_catalog_change_site_created (site_config_id, created_at)
);

-- Validation run records for LLM validation (primary DB)
CREATE TABLE IF NOT EXISTS validation_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scraped_article_id INTEGER NOT NULL,

    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME,
    status VARCHAR(50) DEFAULT 'pending',

    is_validated BOOLEAN DEFAULT FALSE,
    validation_score INTEGER,
    validation_notes TEXT,

    llm_model VARCHAR(255),
    prompt_tokens INTEGER,
    completion_tokens INTEGER,

    FOREIGN KEY (scraped_article_id) REFERENCES scraped_articles(id) ON DELETE CASCADE
);

-- LLM assessment run records for governance reviews (primary DB)
CREATE TABLE IF NOT EXISTS llm_assessment_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_config_id INTEGER NOT NULL,

    trigger_type VARCHAR(50) DEFAULT 'manual',
    scope VARCHAR(100) DEFAULT 'site_config',
    status VARCHAR(50) DEFAULT 'pending',
    llm_model VARCHAR(255),
    prompt_version VARCHAR(50),
    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME,

    total_lines INTEGER DEFAULT 0,
    lines_flagged INTEGER DEFAULT 0,
    lines_applied INTEGER DEFAULT 0,

    summary TEXT,
    error_message TEXT,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (site_config_id) REFERENCES site_configs(id) ON DELETE CASCADE
);

-- LLM assessment line items for governance reviews (primary DB)
CREATE TABLE IF NOT EXISTS llm_assessment_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_run_id INTEGER NOT NULL,
    line_number INTEGER NOT NULL,
    entity_type VARCHAR(100) NOT NULL,
    entity_id INTEGER,
    field_name VARCHAR(100) NOT NULL,
    current_value TEXT,
    suggested_value TEXT,
    recommended_action VARCHAR(50) DEFAULT 'keep',
    reasoning TEXT,
    confidence_score FLOAT,

    status VARCHAR(50) DEFAULT 'pending',
    reviewed_by VARCHAR(255),
    reviewed_at DATETIME,
    applied_at DATETIME,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(assessment_run_id, line_number),
    FOREIGN KEY (assessment_run_id) REFERENCES llm_assessment_runs(id) ON DELETE CASCADE
);

-- Scrape log entries for detailed operation tracking (primary DB)
CREATE TABLE IF NOT EXISTS scrape_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_config_id INTEGER NOT NULL,
    scrape_run_id INTEGER,

    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    level VARCHAR(20) DEFAULT 'INFO',

    event_type VARCHAR(50),
    message TEXT NOT NULL,
    extra_data JSON,

    FOREIGN KEY (site_config_id) REFERENCES site_configs(id) ON DELETE CASCADE,
    INDEX idx_logs_timestamp (timestamp)
);

-- =============================================================================
-- SPIDER DATABASE TABLES
-- =============================================================================

-- Site categories for spider DB (spider DB)
CREATE TABLE IF NOT EXISTS site_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_config_id INTEGER NOT NULL,

    name VARCHAR(255) NOT NULL,
    url VARCHAR(500) NOT NULL,
    max_pages INTEGER DEFAULT 1,
    page_url_pattern VARCHAR(500),
    start_page INTEGER DEFAULT 1,
    active BOOLEAN DEFAULT TRUE,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_site_categories_site_active (site_config_id, active),
    INDEX idx_site_categories_site_start_page (site_config_id, start_page)
);

-- Category crawl state tracking (spider DB)
CREATE TABLE IF NOT EXISTS category_crawl_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_config_id INTEGER NOT NULL,
    site_category_id INTEGER,

    category_name VARCHAR(255),
    category_url VARCHAR(1000) NOT NULL,
    last_page_scraped INTEGER,
    max_page_seen INTEGER,
    last_page_url VARCHAR(1000),

    total_listing_pages_scraped INTEGER DEFAULT 0,
    total_links_discovered INTEGER DEFAULT 0,
    total_records_emitted INTEGER DEFAULT 0,

    last_mode VARCHAR(50),
    last_chunk_id VARCHAR(100),
    last_scraped_at DATETIME,
    notes TEXT,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(site_config_id, category_url),
    INDEX idx_category_crawl_state_site_updated (site_config_id, updated_at),
    INDEX idx_category_crawl_state_site_category_id (site_config_id, site_category_id)
);

-- Spider diagram definitions (spider DB)
CREATE TABLE IF NOT EXISTS spider_diagrams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_config_id INTEGER NOT NULL,

    name VARCHAR(255) NOT NULL,
    version INTEGER DEFAULT 1,
    entrypoint_url VARCHAR(1000) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    notes TEXT,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(site_config_id, name, version),
    INDEX idx_spider_diagrams_site_active_version (site_config_id, is_active, version)
);

-- Spider diagram nodes (spider DB)
CREATE TABLE IF NOT EXISTS spider_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    spider_diagram_id INTEGER NOT NULL,

    node_key VARCHAR(100) NOT NULL,
    node_type VARCHAR(50) NOT NULL,
    url_pattern VARCHAR(1000),
    selector VARCHAR(255),
    extraction_target JSON,
    pagination_rule VARCHAR(255),
    visit_order INTEGER DEFAULT 0,
    active BOOLEAN DEFAULT TRUE,
    notes TEXT,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(spider_diagram_id, node_key),
    INDEX idx_spider_nodes_diagram_type_active (spider_diagram_id, node_type, active),
    INDEX idx_spider_nodes_diagram_visit_order (spider_diagram_id, visit_order),
    FOREIGN KEY (spider_diagram_id) REFERENCES spider_diagrams(id) ON DELETE CASCADE
);

-- Spider diagram edges (spider DB)
CREATE TABLE IF NOT EXISTS spider_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    spider_diagram_id INTEGER NOT NULL,
    from_node_id INTEGER NOT NULL,
    to_node_id INTEGER NOT NULL,

    traversal_type VARCHAR(50) DEFAULT 'follow_link',
    link_selector VARCHAR(255),
    condition_expression VARCHAR(255),
    priority INTEGER DEFAULT 100,
    notes TEXT,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_spider_edges_diagram_priority (spider_diagram_id, priority),
    INDEX idx_spider_edges_from_node (from_node_id),
    INDEX idx_spider_edges_to_node (to_node_id),
    FOREIGN KEY (spider_diagram_id) REFERENCES spider_diagrams(id) ON DELETE CASCADE,
    FOREIGN KEY (from_node_id) REFERENCES spider_nodes(id) ON DELETE CASCADE,
    FOREIGN KEY (to_node_id) REFERENCES spider_nodes(id) ON DELETE CASCADE
);

-- Site structure snapshots for change detection (spider DB)
CREATE TABLE IF NOT EXISTS site_structure_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_config_id INTEGER NOT NULL,

    source VARCHAR(50) DEFAULT 'config_sync',
    fingerprint_hash VARCHAR(64) NOT NULL,
    structure_payload JSON NOT NULL,
    snapshot_notes TEXT,

    first_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(site_config_id, fingerprint_hash),
    INDEX idx_structure_snapshots_site_seen (site_config_id, last_seen_at)
);

-- Site structure change events for LLM review queue (spider DB)
CREATE TABLE IF NOT EXISTS site_structure_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_config_id INTEGER NOT NULL,

    previous_snapshot_id INTEGER,
    current_snapshot_id INTEGER NOT NULL,
    previous_fingerprint_hash VARCHAR(64),
    current_fingerprint_hash VARCHAR(64) NOT NULL,

    detection_source VARCHAR(50) DEFAULT 'snapshot_diff',
    change_type VARCHAR(50) DEFAULT 'structure_update',
    changed_sections JSON,
    change_summary TEXT,

    llm_review_status VARCHAR(50) DEFAULT 'pending',
    llm_review_notes TEXT,

    detected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    reviewed_at DATETIME,
    resolved_at DATETIME,

    INDEX idx_structure_changes_site_status_detected (site_config_id, llm_review_status, detected_at),
    INDEX idx_structure_changes_current_snapshot (current_snapshot_id),
    FOREIGN KEY (site_config_id) REFERENCES site_configs(id) ON DELETE CASCADE,
    FOREIGN KEY (previous_snapshot_id) REFERENCES site_structure_snapshots(id) ON DELETE SET NULL,
    FOREIGN KEY (current_snapshot_id) REFERENCES site_structure_snapshots(id) ON DELETE CASCADE
);

-- =============================================================================
-- End of Schema
-- =============================================================================