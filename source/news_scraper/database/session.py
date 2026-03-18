"""Database session management for split primary + spider persistence."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Sequence

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker

from ..core.config import settings


def _primary_db_url() -> str:
    """Return configured primary DB URL with backward-compatible fallback."""
    return (settings.PRIMARY_DATABASE_URL or settings.DATABASE_URL).strip()


def _spider_db_url() -> str:
    """Return configured spider DB URL."""
    spider = (settings.SPIDER_DATABASE_URL or "").strip()
    return spider or _primary_db_url()


def _connect_args(db_url: str) -> Dict[str, object]:
    if db_url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


def _build_engine(db_url: str) -> Engine:
    return create_engine(
        db_url,
        echo=False,
        connect_args=_connect_args(db_url),
    )


# Primary DB: websites/source metadata + scraper strategy + articles/story data.
primary_engine = _build_engine(_primary_db_url())
# Spider DB: categories/page tracking + spider diagrams.
spider_engine = _build_engine(_spider_db_url())

# Backward-compatible aliases used by existing imports.
engine = primary_engine

# Session factories
PrimarySessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=primary_engine)
SpiderSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=spider_engine)

# Base classes per database.
Base = declarative_base()
SpiderBase = declarative_base()


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

def get_primary_session():
    """Yield a primary-database session."""
    db = PrimarySessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_spider_session():
    """Yield a spider-database session."""
    db = SpiderSessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_session():
    """Backward-compatible alias for primary database session."""
    yield from get_primary_session()


# ---------------------------------------------------------------------------
# Init/reset
# ---------------------------------------------------------------------------

def _ensure_sqlite_parent_dir(db_url: str) -> None:
    """Create parent directory for SQLite DB files."""
    if not db_url.startswith("sqlite"):
        return

    db_path = db_url.replace("sqlite:///", "")
    db_dir = Path(db_path).parent
    db_dir.mkdir(parents=True, exist_ok=True)


def init_db():
    """Initialize both primary and spider databases."""
    _ensure_sqlite_parent_dir(_primary_db_url())
    _ensure_sqlite_parent_dir(_spider_db_url())

    from . import models

    _ = models
    Base.metadata.create_all(bind=primary_engine)
    SpiderBase.metadata.create_all(bind=spider_engine)
    run_additive_migrations()
    migrate_legacy_spider_data()


def reset_db():
    """Drop and recreate all tables in both databases (use with caution)."""
    from . import models

    _ = models
    Base.metadata.drop_all(bind=primary_engine)
    SpiderBase.metadata.drop_all(bind=spider_engine)
    Base.metadata.create_all(bind=primary_engine)
    SpiderBase.metadata.create_all(bind=spider_engine)
    run_additive_migrations()


# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------

def _column_set(inspector, table_name: str, table_names: set) -> set:
    if table_name not in table_names:
        return set()
    return {col["name"] for col in inspector.get_columns(table_name)}


def run_additive_migrations() -> None:
    """Apply additive migrations for both databases."""
    _run_primary_additive_migrations()
    _run_spider_additive_migrations()


def _run_primary_additive_migrations() -> None:
    inspector = inspect(primary_engine)
    table_names = set(inspector.get_table_names())

    with primary_engine.begin() as conn:
        # Site-level metadata additions.
        site_columns = _column_set(inspector, "site_configs", table_names)
        site_additions = {
            "location": "ALTER TABLE site_configs ADD COLUMN location VARCHAR(100)",
            "description": "ALTER TABLE site_configs ADD COLUMN description TEXT",
            "language": "ALTER TABLE site_configs ADD COLUMN language VARCHAR(10)",
            "country": "ALTER TABLE site_configs ADD COLUMN country VARCHAR(100)",
            "server_header": "ALTER TABLE site_configs ADD COLUMN server_header VARCHAR(255)",
            "server_vendor": "ALTER TABLE site_configs ADD COLUMN server_vendor VARCHAR(255)",
            "hosting_provider": "ALTER TABLE site_configs ADD COLUMN hosting_provider VARCHAR(255)",
            "ip_address": "ALTER TABLE site_configs ADD COLUMN ip_address VARCHAR(64)",
            "technology_stack_summary": "ALTER TABLE site_configs ADD COLUMN technology_stack_summary TEXT",
        }
        for column_name, ddl in site_additions.items():
            if column_name not in site_columns:
                conn.execute(text(ddl))

        if "site_configs" in table_names:
            site_indexes = {idx.get("name") for idx in inspector.get_indexes("site_configs")}
            if "idx_site_configs_country" not in site_indexes:
                conn.execute(text("CREATE INDEX idx_site_configs_country ON site_configs (country)"))
            if "idx_site_configs_active_country" not in site_indexes:
                conn.execute(
                    text("CREATE INDEX idx_site_configs_active_country ON site_configs (active, country)")
                )
            if "idx_site_configs_active_language" not in site_indexes:
                conn.execute(
                    text("CREATE INDEX idx_site_configs_active_language ON site_configs (active, language)")
                )

        if "preferred_scraper_type" in site_columns:
            conn.execute(
                text(
                    """
                    UPDATE site_configs
                    SET preferred_scraper_type = 'scrapling'
                    WHERE preferred_scraper_type IS NULL OR preferred_scraper_type IN ('', 'httpx', 'playwright')
                    """
                )
            )

        # Article-level extraction additions.
        article_columns = _column_set(inspector, "scraped_articles", table_names)
        article_additions = {
            "canonical_url": "ALTER TABLE scraped_articles ADD COLUMN canonical_url VARCHAR(1000)",
            "section": "ALTER TABLE scraped_articles ADD COLUMN section VARCHAR(255)",
            "tags": "ALTER TABLE scraped_articles ADD COLUMN tags JSON",
            "scrape_date": "ALTER TABLE scraped_articles ADD COLUMN scrape_date DATETIME",
            "image_links": "ALTER TABLE scraped_articles ADD COLUMN image_links JSON",
            "extra_links": "ALTER TABLE scraped_articles ADD COLUMN extra_links JSON",
            "word_count": "ALTER TABLE scraped_articles ADD COLUMN word_count INTEGER",
            "reading_time_minutes": "ALTER TABLE scraped_articles ADD COLUMN reading_time_minutes INTEGER",
            "raw_metadata": "ALTER TABLE scraped_articles ADD COLUMN raw_metadata JSON",
            "content_hash": "ALTER TABLE scraped_articles ADD COLUMN content_hash VARCHAR(64)",
        }
        for column_name, ddl in article_additions.items():
            if column_name not in article_columns:
                conn.execute(text(ddl))

        if "scraped_articles" in table_names:
            article_indexes = {idx.get("name") for idx in inspector.get_indexes("scraped_articles")}
            if "idx_scraped_articles_site_scrape_date" not in article_indexes:
                conn.execute(
                    text(
                        "CREATE INDEX idx_scraped_articles_site_scrape_date "
                        "ON scraped_articles (site_config_id, scrape_date)"
                    )
                )
            if "idx_scraped_articles_site_publish_date" not in article_indexes:
                conn.execute(
                    text(
                        "CREATE INDEX idx_scraped_articles_site_publish_date "
                        "ON scraped_articles (site_config_id, date_publish)"
                    )
                )

        if "scraper_engine_used" not in article_columns:
            conn.execute(text("ALTER TABLE scraped_articles ADD COLUMN scraper_engine_used VARCHAR(50)"))

        # Strategy additions.
        strategy_columns = _column_set(inspector, "scrape_strategies", table_names)
        strategy_additions = {
            "fallback_engine_chain": "ALTER TABLE scrape_strategies ADD COLUMN fallback_engine_chain JSON",
            "content_parser": "ALTER TABLE scrape_strategies ADD COLUMN content_parser VARCHAR(50) DEFAULT 'beautifulsoup'",
        }
        for column_name, ddl in strategy_additions.items():
            if column_name not in strategy_columns:
                conn.execute(text(ddl))

        if "scraper_engine" in strategy_columns:
            conn.execute(
                text(
                    """
                    UPDATE scrape_strategies
                    SET scraper_engine = 'scrapling'
                    WHERE scraper_engine IS NULL OR scraper_engine IN ('', 'httpx', 'playwright')
                    """
                )
            )

        strategy_columns = _column_set(inspector, "scrape_strategies", table_names)
        if "fallback_engine_chain" in strategy_columns:
            conn.execute(
                text(
                    """
                    UPDATE scrape_strategies
                    SET fallback_engine_chain = '["pydoll","selenium"]'
                    WHERE fallback_engine_chain IS NULL
                    """
                )
            )
        if "content_parser" in strategy_columns:
            conn.execute(
                text(
                    """
                    UPDATE scrape_strategies
                    SET content_parser = COALESCE(content_parser, 'beautifulsoup')
                    """
                )
            )

        if "scraped_articles" in table_names:
            conn.execute(
                text(
                    """
                    UPDATE scraped_articles
                    SET scrape_date = COALESCE(scrape_date, date_download, CURRENT_TIMESTAMP)
                    """
                )
            )

        if "historical_scrape_progress" in table_names:
            historical_indexes = {
                idx.get("name")
                for idx in inspector.get_indexes("historical_scrape_progress")
            }
            if "idx_historical_progress_chunk_id" not in historical_indexes:
                conn.execute(
                    text(
                        "CREATE INDEX idx_historical_progress_chunk_id "
                        "ON historical_scrape_progress (chunk_id)"
                    )
                )

        if "article_url_ledger" in table_names:
            ledger_indexes = {idx.get("name") for idx in inspector.get_indexes("article_url_ledger")}
            if "idx_article_url_ledger_site_last_seen" not in ledger_indexes:
                conn.execute(
                    text(
                        "CREATE INDEX idx_article_url_ledger_site_last_seen "
                        "ON article_url_ledger (site_config_id, last_seen_at)"
                    )
                )
            if "idx_article_url_ledger_site_publish" not in ledger_indexes:
                conn.execute(
                    text(
                        "CREATE INDEX idx_article_url_ledger_site_publish "
                        "ON article_url_ledger (site_config_id, last_publish_at)"
                    )
                )

        if "catalog_change_log" in table_names:
            catalog_indexes = {idx.get("name") for idx in inspector.get_indexes("catalog_change_log")}
            if "idx_catalog_change_entity_created" not in catalog_indexes:
                conn.execute(
                    text(
                        "CREATE INDEX idx_catalog_change_entity_created "
                        "ON catalog_change_log (entity_type, created_at)"
                    )
                )
            if "idx_catalog_change_site_created" not in catalog_indexes:
                conn.execute(
                    text(
                        "CREATE INDEX idx_catalog_change_site_created "
                        "ON catalog_change_log (site_config_id, created_at)"
                    )
                )


def _run_spider_additive_migrations() -> None:
    inspector = inspect(spider_engine)
    table_names = set(inspector.get_table_names())

    with spider_engine.begin() as conn:
        category_columns = _column_set(inspector, "site_categories", table_names)
        category_additions = {
            "page_url_pattern": "ALTER TABLE site_categories ADD COLUMN page_url_pattern VARCHAR(500)",
            "start_page": "ALTER TABLE site_categories ADD COLUMN start_page INTEGER DEFAULT 1",
            "active": "ALTER TABLE site_categories ADD COLUMN active BOOLEAN DEFAULT 1",
        }
        for column_name, ddl in category_additions.items():
            if column_name not in category_columns:
                conn.execute(text(ddl))

        if "site_categories" in table_names:
            category_indexes = {idx.get("name") for idx in inspector.get_indexes("site_categories")}
            if "idx_site_categories_site_active" not in category_indexes:
                conn.execute(
                    text("CREATE INDEX idx_site_categories_site_active ON site_categories (site_config_id, active)")
                )
            if "idx_site_categories_site_start_page" not in category_indexes:
                conn.execute(
                    text(
                        "CREATE INDEX idx_site_categories_site_start_page "
                        "ON site_categories (site_config_id, start_page)"
                    )
                )

        if "category_crawl_state" in table_names:
            crawl_indexes = {idx.get("name") for idx in inspector.get_indexes("category_crawl_state")}
            if "idx_category_crawl_state_site_updated" not in crawl_indexes:
                conn.execute(
                    text(
                        "CREATE INDEX idx_category_crawl_state_site_updated "
                        "ON category_crawl_state (site_config_id, updated_at)"
                    )
                )
            if "idx_category_crawl_state_site_category_id" not in crawl_indexes:
                conn.execute(
                    text(
                        "CREATE INDEX idx_category_crawl_state_site_category_id "
                        "ON category_crawl_state (site_config_id, site_category_id)"
                    )
                )

        if "spider_diagrams" in table_names:
            diagram_indexes = {idx.get("name") for idx in inspector.get_indexes("spider_diagrams")}
            if "idx_spider_diagrams_site_active_version" not in diagram_indexes:
                conn.execute(
                    text(
                        "CREATE INDEX idx_spider_diagrams_site_active_version "
                        "ON spider_diagrams (site_config_id, is_active, version)"
                    )
                )

        if "spider_nodes" in table_names:
            node_indexes = {idx.get("name") for idx in inspector.get_indexes("spider_nodes")}
            if "idx_spider_nodes_diagram_type_active" not in node_indexes:
                conn.execute(
                    text(
                        "CREATE INDEX idx_spider_nodes_diagram_type_active "
                        "ON spider_nodes (spider_diagram_id, node_type, active)"
                    )
                )
            if "idx_spider_nodes_diagram_visit_order" not in node_indexes:
                conn.execute(
                    text(
                        "CREATE INDEX idx_spider_nodes_diagram_visit_order "
                        "ON spider_nodes (spider_diagram_id, visit_order)"
                    )
                )

        if "spider_edges" in table_names:
            edge_indexes = {idx.get("name") for idx in inspector.get_indexes("spider_edges")}
            if "idx_spider_edges_diagram_priority" not in edge_indexes:
                conn.execute(
                    text(
                        "CREATE INDEX idx_spider_edges_diagram_priority "
                        "ON spider_edges (spider_diagram_id, priority)"
                    )
                )
            if "idx_spider_edges_from_node" not in edge_indexes:
                conn.execute(text("CREATE INDEX idx_spider_edges_from_node ON spider_edges (from_node_id)"))
            if "idx_spider_edges_to_node" not in edge_indexes:
                conn.execute(text("CREATE INDEX idx_spider_edges_to_node ON spider_edges (to_node_id)"))

        if "site_structure_snapshots" in table_names:
            snapshot_indexes = {idx.get("name") for idx in inspector.get_indexes("site_structure_snapshots")}
            if "idx_structure_snapshots_site_seen" not in snapshot_indexes:
                conn.execute(
                    text(
                        "CREATE INDEX idx_structure_snapshots_site_seen "
                        "ON site_structure_snapshots (site_config_id, last_seen_at)"
                    )
                )

        if "site_structure_changes" in table_names:
            change_indexes = {idx.get("name") for idx in inspector.get_indexes("site_structure_changes")}
            if "idx_structure_changes_site_status_detected" not in change_indexes:
                conn.execute(
                    text(
                        "CREATE INDEX idx_structure_changes_site_status_detected "
                        "ON site_structure_changes (site_config_id, llm_review_status, detected_at)"
                    )
                )
            if "idx_structure_changes_current_snapshot" not in change_indexes:
                conn.execute(
                    text(
                        "CREATE INDEX idx_structure_changes_current_snapshot "
                        "ON site_structure_changes (current_snapshot_id)"
                    )
                )


# ---------------------------------------------------------------------------
# Legacy split migration (single DB -> primary+spider)
# ---------------------------------------------------------------------------

def _quote_identifier(name: str) -> str:
    # Identifiers are fixed internal names; keep SQL portable across MySQL/PostgreSQL/SQLite.
    return name


def _shared_columns(source_cols: Sequence[str], target_cols: Sequence[str]) -> List[str]:
    source_set = set(source_cols)
    return [col for col in target_cols if col in source_set]


def _copy_table_rows(table_name: str, ordered_columns: Sequence[str]) -> None:
    if not ordered_columns:
        return

    selected = ", ".join(_quote_identifier(col) for col in ordered_columns)
    placeholders = ", ".join(f":{col}" for col in ordered_columns)
    insert_sql = text(
        f"INSERT INTO {_quote_identifier(table_name)} ({selected}) VALUES ({placeholders})"
    )

    with primary_engine.connect() as source_conn, spider_engine.begin() as target_conn:
        rows = source_conn.execute(
            text(f"SELECT {selected} FROM {_quote_identifier(table_name)}")
        ).mappings().all()
        if rows:
            target_conn.execute(insert_sql, rows)


def migrate_legacy_spider_data() -> None:
    """
    Migrate spider/category tables from a legacy single DB into spider DB.

    Only runs when primary and spider URLs differ and target spider tables are empty.
    """
    if _primary_db_url() == _spider_db_url():
        return

    primary_inspector = inspect(primary_engine)
    spider_inspector = inspect(spider_engine)

    primary_tables = set(primary_inspector.get_table_names())
    spider_tables = set(spider_inspector.get_table_names())

    transfer_order = [
        "site_categories",
        "category_crawl_state",
        "spider_diagrams",
        "spider_nodes",
        "spider_edges",
    ]

    with spider_engine.connect() as spider_conn:
        for table_name in transfer_order:
            if table_name not in primary_tables or table_name not in spider_tables:
                continue

            row_count = spider_conn.execute(
                text(f"SELECT COUNT(1) FROM {_quote_identifier(table_name)}")
            ).scalar_one()
            if row_count and row_count > 0:
                continue

            source_cols = [col["name"] for col in primary_inspector.get_columns(table_name)]
            target_cols = [col["name"] for col in spider_inspector.get_columns(table_name)]
            columns = _shared_columns(source_cols, target_cols)
            _copy_table_rows(table_name, columns)


# ---------------------------------------------------------------------------
# Health checks
# ---------------------------------------------------------------------------

def test_connection() -> bool:
    """Test connectivity for both primary and spider databases."""
    try:
        with primary_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        with spider_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
