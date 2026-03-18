"""Config-driven scraping pipeline for large-scale multi-site ingestion."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlencode, urlparse

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..config.loader import load_config
from ..assessment.structure_tracker import capture_site_structure_snapshot
from ..database.session import get_spider_session
from ..database.models import (
    CatalogChangeLog,
    ScrapeStrategy,
    SiteCategory,
    SiteConfig,
    SiteTechnology,
)
from ..export.json_export import JSONExporter
from ..scraping.config_registry import SiteConfigRegistry
from ..scraping.engine import ScraperEngine
from ..scraping.spider_planner import ensure_default_spider_diagram


def _normalize_mode(mode: str) -> str:
    mapping = {
        "current": "current",
        "incremental": "current",
        "historic": "historical",
        "historical": "historical",
        "backfill": "historical",
        "full": "historical",
    }
    return mapping.get((mode or "current").lower(), "current")


def _normalize_text_list(values: Optional[Iterable[str]]) -> List[str]:
    """Normalize list-like string values for stable filtering."""
    if not values:
        return []
    normalized: List[str] = []
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            normalized.append(text)
    return normalized


def _log_catalog_event(
    db_session: Session,
    *,
    site_config_id: Optional[int],
    entity_type: str,
    entity_key: str,
    action: str,
    payload: Optional[Dict[str, Any]] = None,
    source: str = "config_sync",
) -> None:
    """Persist a catalog mutation event for auditability."""
    db_session.add(
        CatalogChangeLog(
            site_config_id=site_config_id,
            entity_type=entity_type,
            entity_key=entity_key,
            action=action,
            change_source=source,
            change_payload=payload or {},
        )
    )


def _listing_url(base_url: str, page_number: int) -> str:
    """Build a fallback page URL when no explicit page pattern exists."""
    if page_number <= 1:
        return base_url
    separator = "&" if "?" in base_url else "?"
    query = urlencode({"page": page_number})
    return f"{base_url}{separator}{query}"


def _build_category_targets(
    site: SiteConfig,
    categories: List[SiteCategory],
    mode: str,
    start_page: int,
    end_page: Optional[int],
    max_pages: Optional[int],
) -> List[Dict[str, Any]]:
    """
    Build category/page targets from spider DB category metadata.

    Returns an empty list when no active categories exist.
    """
    if not categories:
        return []

    normalized_mode = _normalize_mode(mode)
    targets: List[Dict[str, Any]] = []
    default_pages = max(int(site.num_pages_to_scrape or 1), 1)
    global_start = max(int(start_page or 1), 1)

    for category in categories:
        base_url = (category.url or "").strip()
        if not base_url:
            continue

        category_start = max(int(category.start_page or 1), 1)
        start = max(global_start, category_start)

        max_pages_for_category = int(category.max_pages or default_pages)
        if max_pages is not None:
            max_pages_for_category = min(max(max_pages_for_category, 1), max(max_pages, 1))

        # For historical mode, allow deeper default traversal only when caller
        # did not provide explicit page bounds.
        if normalized_mode == "historical" and max_pages is None and end_page is None:
            max_pages_for_category = max(max_pages_for_category, default_pages * 2)

        if end_page is not None and int(end_page) >= start:
            stop = int(end_page)
        else:
            stop = start + max_pages_for_category - 1

        page_pattern = (category.page_url_pattern or site.category_url_pattern or "").strip()
        page_urls: List[Dict[str, Any]] = []
        for page_number in range(start, stop + 1):
            if page_pattern and "{page}" in page_pattern:
                page_url = page_pattern.replace("{page}", str(page_number))
            else:
                page_url = _listing_url(base_url, page_number)
            page_urls.append({"url": page_url, "page_number": page_number})

        targets.append(
            {
                "category_id": category.id,
                "category_name": category.name,
                "category_url": base_url,
                "page_urls": page_urls,
            }
        )

    return targets


def _upsert_categories(
    db_session: Session,
    site: SiteConfig,
    site_data: Dict[str, Any],
    audit_session: Optional[Session] = None,
) -> Dict[str, int]:
    stats = {"added": 0, "updated": 0}
    categories = site_data.get("categories") or []
    if not isinstance(categories, list):
        return stats

    existing_categories = (
        db_session.query(SiteCategory)
        .filter(SiteCategory.site_config_id == site.id)
        .all()
    )
    existing_by_url = {cat.url: cat for cat in existing_categories if cat.url}
    existing_by_name = {
        (cat.name or "").strip().lower(): cat
        for cat in existing_categories
        if (cat.name or "").strip()
    }
    default_pages = int(site_data.get("num_pages_to_scrape", site.num_pages_to_scrape or 1))
    configured_urls = set()

    for category_data in categories:
        if not isinstance(category_data, dict):
            continue
        category_url = (category_data.get("url") or "").strip()
        if not category_url:
            continue

        category_name = (category_data.get("name") or category_url.split("/")[-1] or "category").strip()
        payload = {
            "name": category_name,
            "url": category_url,
            "max_pages": int(category_data.get("max_pages", default_pages)),
            "page_url_pattern": category_data.get("page_url_pattern"),
            "start_page": int(category_data.get("start_page", 1)),
            "active": bool(category_data.get("active", True)),
        }
        configured_urls.add(category_url)

        existing = existing_by_url.get(category_url)
        if not existing:
            existing = existing_by_name.get(category_name.lower())

        if existing:
            changed = False
            for key, value in payload.items():
                if getattr(existing, key) != value:
                    setattr(existing, key, value)
                    changed = True
            existing_by_url[existing.url] = existing
            existing_by_name[(existing.name or "").strip().lower()] = existing
            if changed:
                stats["updated"] += 1
                if audit_session is not None:
                    _log_catalog_event(
                        audit_session,
                        site_config_id=site.id,
                        entity_type="site_category",
                        entity_key=category_url,
                        action="updated",
                        payload=payload,
                    )
        else:
            new_category = SiteCategory(site_config_id=site.id, **payload)
            db_session.add(new_category)
            existing_by_url[category_url] = new_category
            existing_by_name[category_name.lower()] = new_category
            stats["added"] += 1
            if audit_session is not None:
                _log_catalog_event(
                    audit_session,
                    site_config_id=site.id,
                    entity_type="site_category",
                    entity_key=category_url,
                    action="created",
                    payload=payload,
                )

    # Deactivate stale categories that are no longer in config for this site.
    for category in existing_categories:
        if category.url not in configured_urls and category.active:
            category.active = False
            stats["updated"] += 1
            if audit_session is not None:
                _log_catalog_event(
                    audit_session,
                    site_config_id=site.id,
                    entity_type="site_category",
                    entity_key=category.url or category.name,
                    action="deactivated",
                    payload={"name": category.name, "url": category.url},
                )

    return stats


def _upsert_technologies(
    db_session: Session,
    site: SiteConfig,
    site_data: Dict[str, Any],
    audit_session: Optional[Session] = None,
) -> Dict[str, int]:
    stats = {"added": 0, "updated": 0}
    technologies = site_data.get("technologies") or []
    if not isinstance(technologies, list):
        return stats

    existing_by_name = {
        (tech.technology_name or "").lower(): tech for tech in site.technologies
    }
    for technology in technologies:
        if isinstance(technology, str):
            technology = {"name": technology}
        if not isinstance(technology, dict):
            continue

        name = (technology.get("name") or technology.get("technology_name") or "").strip()
        if not name:
            continue

        payload = {
            "technology_name": name,
            "technology_type": technology.get("type") or technology.get("technology_type"),
            "version": technology.get("version"),
            "confidence_score": technology.get("confidence_score"),
            "detection_source": technology.get("detection_source") or "config",
            "notes": technology.get("notes"),
        }

        existing = existing_by_name.get(name.lower())
        if existing:
            changed = False
            for key, value in payload.items():
                if getattr(existing, key) != value:
                    setattr(existing, key, value)
                    changed = True
            if changed:
                stats["updated"] += 1
                if audit_session is not None:
                    _log_catalog_event(
                        audit_session,
                        site_config_id=site.id,
                        entity_type="site_technology",
                        entity_key=name,
                        action="updated",
                        payload=payload,
                    )
        else:
            db_session.add(SiteTechnology(site_config_id=site.id, **payload))
            stats["added"] += 1
            if audit_session is not None:
                _log_catalog_event(
                    audit_session,
                    site_config_id=site.id,
                    entity_type="site_technology",
                    entity_key=name,
                    action="created",
                    payload=payload,
                )

    return stats


def _upsert_scrape_strategy(
    db_session: Session,
    site: SiteConfig,
    site_data: Dict[str, Any],
    audit_session: Optional[Session] = None,
) -> int:
    strategy_data = site_data.get("scrape_strategy") or {}
    if not isinstance(strategy_data, dict) or not strategy_data:
        return 0

    payload = {
        "scraper_engine": strategy_data.get("scraper_engine", site.preferred_scraper_type or "scrapling"),
        "fallback_engine_chain": strategy_data.get("fallback_engine_chain", ["pydoll", "selenium"]),
        "content_parser": strategy_data.get("content_parser", "beautifulsoup"),
        "browser_automation_tool": strategy_data.get("browser_automation_tool"),
        "rendering_required": bool(strategy_data.get("rendering_required", site.uses_javascript)),
        "requires_proxy": bool(strategy_data.get("requires_proxy", False)),
        "proxy_region": strategy_data.get("proxy_region"),
        "login_required": bool(strategy_data.get("login_required", False)),
        "auth_strategy": strategy_data.get("auth_strategy"),
        "anti_bot_protection": strategy_data.get("anti_bot_protection"),
        "blocking_signals": strategy_data.get("blocking_signals"),
        "bypass_techniques": strategy_data.get("bypass_techniques"),
        "request_headers": strategy_data.get("request_headers"),
        "cookie_preset": strategy_data.get("cookie_preset"),
        "rate_limit_per_minute": strategy_data.get("rate_limit_per_minute"),
        "notes": strategy_data.get("notes"),
    }

    strategy = site.scrape_strategy
    was_changed = False
    if strategy:
        changed = False
        for key, value in payload.items():
            if getattr(strategy, key) != value:
                setattr(strategy, key, value)
                changed = True
        was_changed = changed
        if changed and audit_session is not None:
            _log_catalog_event(
                audit_session,
                site_config_id=site.id,
                entity_type="scrape_strategy",
                entity_key=site.url,
                action="updated",
                payload=payload,
            )
    else:
        db_session.add(ScrapeStrategy(site_config_id=site.id, **payload))
        was_changed = True
        if audit_session is not None:
            _log_catalog_event(
                audit_session,
                site_config_id=site.id,
                entity_type="scrape_strategy",
                entity_key=site.url,
                action="created",
                payload=payload,
            )

    site.preferred_scraper_type = payload["scraper_engine"]
    site.uses_javascript = payload["rendering_required"]
    return 1 if was_changed else 0


def sync_sites_from_config(
    db_session: Session,
    config_path: str,
    spider_session: Optional[Session] = None,
) -> Dict[str, Any]:
    """
    Upsert site catalog from YAML config into SQL.

    Supports site metadata, categories, technologies, and scrape strategy.
    """
    owns_spider_session = spider_session is None
    if spider_session is None:
        spider_session = next(get_spider_session())

    try:
        config = load_config(config_path)
        sites_data = config.get("sites") or []
        registry = SiteConfigRegistry(db_session)

        stats = {
            "configured_sites": len(sites_data),
            "added_sites": 0,
            "updated_sites": 0,
            "added_categories": 0,
            "updated_categories": 0,
            "added_technologies": 0,
            "updated_technologies": 0,
            "updated_strategies": 0,
        }

        for site_data in sites_data:
            if not isinstance(site_data, dict):
                continue
            url = (site_data.get("url") or "").strip()
            name = (site_data.get("name") or "").strip()
            if not url or not name:
                continue

            existing = registry.get_site_by_url(url)
            payload = {
                "name": name,
                "url": url,
                "domain": (urlparse(url).netloc or "").lower().replace("www.", "") or None,
                "category_url_pattern": site_data.get("category_url_pattern"),
                "num_pages_to_scrape": int(site_data.get("num_pages_to_scrape", 3)),
                "active": bool(site_data.get("active", True)),
                "uses_javascript": bool(site_data.get("uses_javascript", False)),
                "country": site_data.get("country") or site_data.get("location"),
                "location": site_data.get("location") or site_data.get("country"),
                "language": site_data.get("language", "en"),
                "description": site_data.get("description"),
                "server_header": site_data.get("server_header"),
                "server_vendor": site_data.get("server_vendor"),
                "hosting_provider": site_data.get("hosting_provider"),
                "technology_stack_summary": site_data.get("technology_stack_summary"),
            }

            if existing:
                site_changed = False
                for key, value in payload.items():
                    if value is not None and getattr(existing, key) != value:
                        setattr(existing, key, value)
                        site_changed = True
                site = existing
                if site_changed:
                    stats["updated_sites"] += 1
                    _log_catalog_event(
                        db_session,
                        site_config_id=site.id,
                        entity_type="site_config",
                        entity_key=site.url,
                        action="updated",
                        payload=payload,
                    )
            else:
                site = registry.add_site(**payload)
                stats["added_sites"] += 1
                _log_catalog_event(
                    db_session,
                    site_config_id=site.id,
                    entity_type="site_config",
                    entity_key=site.url,
                    action="created",
                    payload=payload,
                )

            category_stats = _upsert_categories(
                spider_session,
                site,
                site_data,
                audit_session=db_session,
            )
            tech_stats = _upsert_technologies(
                db_session,
                site,
                site_data,
                audit_session=db_session,
            )
            strategy_updated = _upsert_scrape_strategy(
                db_session,
                site,
                site_data,
                audit_session=db_session,
            )
            ensure_default_spider_diagram(spider_session, site)
            capture_site_structure_snapshot(
                primary_session=db_session,
                spider_session=spider_session,
                site_config_id=site.id,
                source="config_sync",
            )

            stats["added_categories"] += category_stats["added"]
            stats["updated_categories"] += category_stats["updated"]
            stats["added_technologies"] += tech_stats["added"]
            stats["updated_technologies"] += tech_stats["updated"]
            stats["updated_strategies"] += strategy_updated

        db_session.commit()
        spider_session.commit()
        return stats
    except Exception:
        db_session.rollback()
        spider_session.rollback()
        raise
    finally:
        if owns_spider_session:
            spider_session.close()


def run_config_scrape(
    db_session: Session,
    config_path: str,
    mode: str = "current",
    output_json: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
    cutoff_date: Optional[datetime] = None,
    max_pages: Optional[int] = None,
    start_page: int = 1,
    end_page: Optional[int] = None,
    chunk_id: Optional[str] = None,
    site_urls: Optional[List[str]] = None,
    site_names: Optional[List[str]] = None,
    countries: Optional[List[str]] = None,
    enable_rate_limiting: bool = True,
    sync_first: bool = True,
    spider_session: Optional[Session] = None,
    story_batch_size: int = 200,
    store_in_db: bool = False,  # Default: DO NOT store scraped articles in DB - JSON output only
) -> Dict[str, Any]:
    """
    Execute a config-driven scrape run and persist structured JSON output.

    IMPORTANT: scraped article data is stored in JSON output only, NOT in this database.
    ETL processes should handle persistence to target databases (PostgreSQL, etc.).

    Args:
        store_in_db: If True, articles are inserted into scraped_articles table (deprecated - set to False)
    """
    started_at = datetime.now()
    normalized_mode = _normalize_mode(mode)
    config = load_config(config_path)
    configured_sites = config.get("sites") or []

    owns_spider_session = spider_session is None
    if spider_session is None:
        spider_session = next(get_spider_session())

    try:
        sync_stats = None
        if sync_first:
            sync_stats = sync_sites_from_config(
                db_session,
                config_path,
                spider_session=spider_session,
            )

        configured_urls = [
            (site.get("url") or "").strip()
            for site in configured_sites
            if isinstance(site, dict) and site.get("url")
        ]
        selected_urls = _normalize_text_list(site_urls)
        selected_names = _normalize_text_list(site_names)
        selected_countries = _normalize_text_list(countries)

        sites_query = db_session.query(SiteConfig)
        if configured_urls:
            sites_query = sites_query.filter(SiteConfig.url.in_(configured_urls))
        sites_query = sites_query.filter(SiteConfig.active.is_(True)).order_by(SiteConfig.id.asc())

        if selected_urls:
            sites_query = sites_query.filter(
                func.lower(SiteConfig.url).in_([value.lower() for value in selected_urls])
            )
        if selected_names:
            sites_query = sites_query.filter(
                func.lower(SiteConfig.name).in_([value.lower() for value in selected_names])
            )
        if selected_countries:
            countries_lower = [value.lower() for value in selected_countries]
            sites_query = sites_query.filter(
                or_(
                    func.lower(SiteConfig.country).in_(countries_lower),
                    func.lower(SiteConfig.location).in_(countries_lower),
                )
            )

        if offset:
            sites_query = sites_query.offset(offset)
        if limit is not None:
            sites_query = sites_query.limit(limit)

        sites = sites_query.all()
        results: List[Dict[str, Any]] = []
        records: List[Dict[str, Any]] = []
        batch_size = int(story_batch_size) if story_batch_size else 0
        if batch_size < 0:
            raise ValueError("story_batch_size must be >= 0")
        remaining_records = batch_size if batch_size > 0 else None

        with ScraperEngine(enable_rate_limiting=enable_rate_limiting) as engine:
            for site in sites:
                if remaining_records is not None and remaining_records <= 0:
                    break

                categories = (
                    spider_session.query(SiteCategory)
                    .filter(
                        SiteCategory.site_config_id == site.id,
                        SiteCategory.active.is_(True),
                    )
                    .order_by(SiteCategory.id.asc())
                    .all()
                )
                category_targets = _build_category_targets(
                    site=site,
                    categories=categories,
                    mode=normalized_mode,
                    start_page=start_page,
                    end_page=end_page,
                    max_pages=max_pages,
                )

                stats = engine.scrape_site(
                    site_config=site,
                    db_session=db_session,
                    spider_session=spider_session,
                    mode=normalized_mode,
                    date_cutoff=cutoff_date,
                    max_pages=max_pages,
                    start_page=start_page,
                    end_page=end_page,
                    category_targets=category_targets or None,
                    chunk_id=chunk_id,
                    enable_rate_limiting=enable_rate_limiting,
                    store_in_db=store_in_db,  # Only store if explicitly requested (deprecated behavior)
                    max_new_articles=remaining_records,
                )
                site_records = stats.get("records", [])
                if site_records:
                    records.extend(site_records)
                site_result = dict(stats)
                site_result.pop("records", None)
                results.append(site_result)
                if remaining_records is not None:
                    remaining_records -= len(site_records)

        if not output_json:
            ts = started_at.strftime("%Y%m%d_%H%M%S")
            output_json = f"./data/exports/scrape_run_{normalized_mode}_{ts}.json"
        output_path = Path(output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        exporter = JSONExporter(str(output_path))
        
        summary = {
            "sites_targeted": len(sites),
            "sites_processed": len(results),
            "sites_with_errors": sum(1 for r in results if r.get("errors")),
            "articles_found": sum(r.get("articles_found", 0) for r in results),
            "articles_saved": 0,  # NOT stored in SQLite - JSON output only (ETL handles persistence)
            "articles_skipped": sum(r.get("articles_skipped", 0) for r in results),
            "records_exported": len(records),
            "stored_in_db": False,  # Articles are JSON-only, NOT persisted to this DB
            "story_batch_size": batch_size if batch_size > 0 else None,
            "batch_limit_reached": (remaining_records is not None and remaining_records <= 0),
        }

        run_metadata = {
            "pipeline": "config_driven_scrape",
            "mode": normalized_mode,
            "started_at": started_at.isoformat(),
            "completed_at": datetime.now().isoformat(),
            "config_path": str(config_path),
            "limit": limit,
            "offset": offset,
            "cutoff_date": cutoff_date.isoformat() if cutoff_date else None,
            "max_pages": max_pages,
            "start_page": start_page,
            "end_page": end_page,
            "chunk_id": chunk_id,
            "selected_site_urls": selected_urls,
            "selected_site_names": selected_names,
            "selected_countries": selected_countries,
            "rate_limiting": enable_rate_limiting,
            "story_batch_size": batch_size if batch_size > 0 else None,
            "summary": summary,
            "site_results": results,
            "sync_stats": sync_stats,
        }
        exporter.export_run_payload(records=records, run_metadata=run_metadata, overwrite=True)

        return {
            "output_json": str(output_path),
            "run_metadata": run_metadata,
            "record_count": len(records),
            "records": records,
        }
    finally:
        if owns_spider_session:
            spider_session.close()
