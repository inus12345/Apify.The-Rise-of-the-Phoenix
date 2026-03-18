"""Structure snapshot/change tracking for scraper planning and LLM verification."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session, joinedload

from ..database.models import (
    SiteCategory,
    SiteConfig,
    SiteStructureChange,
    SiteStructureSnapshot,
    SpiderDiagram,
)


def _canonical_json(value: Any) -> str:
    """Stable JSON representation for hashing/comparison."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _diff_top_sections(previous: Dict[str, Any], current: Dict[str, Any]) -> List[str]:
    """Return changed top-level payload sections."""
    changed: List[str] = []
    all_keys = set(previous.keys()) | set(current.keys())
    for key in sorted(all_keys):
        if _canonical_json(previous.get(key)) != _canonical_json(current.get(key)):
            changed.append(key)
    return changed


def _normalized_payload(
    site: SiteConfig,
    categories: List[SiteCategory],
    diagrams: List[SpiderDiagram],
) -> Dict[str, Any]:
    """Build normalized structure payload for drift detection."""
    category_payload = [
        {
            "name": category.name,
            "url": category.url,
            "max_pages": category.max_pages,
            "page_url_pattern": category.page_url_pattern,
            "start_page": category.start_page,
            "active": category.active,
        }
        for category in sorted(categories, key=lambda x: (x.name or "", x.url or "", x.id or 0))
    ]

    diagram_payload: List[Dict[str, Any]] = []
    for diagram in sorted(diagrams, key=lambda x: (x.name or "", x.version or 0, x.id or 0)):
        nodes = sorted(diagram.nodes, key=lambda x: (x.visit_order or 0, x.node_key or "", x.id or 0))
        edges = sorted(diagram.edges, key=lambda x: (x.priority or 100, x.id or 0))
        diagram_payload.append(
            {
                "id": diagram.id,
                "name": diagram.name,
                "version": diagram.version,
                "entrypoint_url": diagram.entrypoint_url,
                "is_active": diagram.is_active,
                "nodes": [
                    {
                        "id": node.id,
                        "node_key": node.node_key,
                        "node_type": node.node_type,
                        "url_pattern": node.url_pattern,
                        "selector": node.selector,
                        "extraction_target": node.extraction_target,
                        "pagination_rule": node.pagination_rule,
                        "visit_order": node.visit_order,
                        "active": node.active,
                    }
                    for node in nodes
                ],
                "edges": [
                    {
                        "id": edge.id,
                        "from_node_id": edge.from_node_id,
                        "to_node_id": edge.to_node_id,
                        "traversal_type": edge.traversal_type,
                        "link_selector": edge.link_selector,
                        "condition_expression": edge.condition_expression,
                        "priority": edge.priority,
                    }
                    for edge in edges
                ],
            }
        )

    strategy = site.scrape_strategy
    strategy_payload = {
        "scraper_engine": strategy.scraper_engine if strategy else None,
        "fallback_engine_chain": strategy.fallback_engine_chain if strategy else None,
        "content_parser": strategy.content_parser if strategy else None,
        "browser_automation_tool": strategy.browser_automation_tool if strategy else None,
        "rendering_required": strategy.rendering_required if strategy else None,
        "requires_proxy": strategy.requires_proxy if strategy else None,
        "proxy_region": strategy.proxy_region if strategy else None,
        "login_required": strategy.login_required if strategy else None,
        "auth_strategy": strategy.auth_strategy if strategy else None,
        "anti_bot_protection": strategy.anti_bot_protection if strategy else None,
        "blocking_signals": strategy.blocking_signals if strategy else None,
        "bypass_techniques": strategy.bypass_techniques if strategy else None,
        "rate_limit_per_minute": strategy.rate_limit_per_minute if strategy else None,
    }

    site_payload = {
        "id": site.id,
        "name": site.name,
        "url": site.url,
        "domain": site.domain,
        "country": site.country,
        "location": site.location,
        "language": site.language,
        "category_url_pattern": site.category_url_pattern,
        "num_pages_to_scrape": site.num_pages_to_scrape,
        "preferred_scraper_type": site.preferred_scraper_type,
        "uses_javascript": site.uses_javascript,
        "selectors": {
            "article_selector": site.article_selector,
            "title_selector": site.title_selector,
            "author_selector": site.author_selector,
            "date_selector": site.date_selector,
            "body_selector": site.body_selector,
        },
    }

    return {
        "site": site_payload,
        "scrape_strategy": strategy_payload,
        "categories": category_payload,
        "spider_diagrams": diagram_payload,
    }


def capture_site_structure_snapshot(
    primary_session: Session,
    spider_session: Session,
    site_config_id: int,
    source: str = "config_sync",
    snapshot_notes: Optional[str] = None,
) -> SiteStructureSnapshot:
    """
    Capture structure snapshot and emit a change record when drift is detected.

    Designed for Spider DB persistence while reading source-of-truth site metadata
    from Primary DB.
    """
    # Ensure new Spider DB tables exist even if caller did not run init recently.
    bind = spider_session.get_bind()
    SiteStructureSnapshot.__table__.create(bind=bind, checkfirst=True)
    SiteStructureChange.__table__.create(bind=bind, checkfirst=True)

    site = (
        primary_session.query(SiteConfig)
        .options(joinedload(SiteConfig.scrape_strategy))
        .filter(SiteConfig.id == site_config_id)
        .first()
    )
    if not site:
        raise ValueError(f"SiteConfig not found: {site_config_id}")

    categories = (
        spider_session.query(SiteCategory)
        .filter(SiteCategory.site_config_id == site_config_id)
        .order_by(SiteCategory.id.asc())
        .all()
    )
    diagrams = (
        spider_session.query(SpiderDiagram)
        .options(joinedload(SpiderDiagram.nodes), joinedload(SpiderDiagram.edges))
        .filter(SpiderDiagram.site_config_id == site_config_id)
        .order_by(SpiderDiagram.id.asc())
        .all()
    )

    payload = _normalized_payload(site, categories, diagrams)
    fingerprint = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    now = datetime.now()

    latest_snapshot = (
        spider_session.query(SiteStructureSnapshot)
        .filter(SiteStructureSnapshot.site_config_id == site_config_id)
        .order_by(SiteStructureSnapshot.last_seen_at.desc(), SiteStructureSnapshot.id.desc())
        .first()
    )
    existing_same = (
        spider_session.query(SiteStructureSnapshot)
        .filter(
            SiteStructureSnapshot.site_config_id == site_config_id,
            SiteStructureSnapshot.fingerprint_hash == fingerprint,
        )
        .first()
    )

    if existing_same:
        existing_same.last_seen_at = now
        existing_same.source = source
        if snapshot_notes:
            existing_same.snapshot_notes = snapshot_notes
        return existing_same

    snapshot = SiteStructureSnapshot(
        site_config_id=site_config_id,
        source=source,
        fingerprint_hash=fingerprint,
        structure_payload=payload,
        snapshot_notes=snapshot_notes,
        first_seen_at=now,
        last_seen_at=now,
    )
    spider_session.add(snapshot)
    spider_session.flush()

    if latest_snapshot and latest_snapshot.fingerprint_hash != fingerprint:
        changed_sections = _diff_top_sections(
            latest_snapshot.structure_payload or {},
            payload,
        )
        summary = "Structure drift detected"
        if changed_sections:
            summary = f"Changed sections: {', '.join(changed_sections)}"

        spider_session.add(
            SiteStructureChange(
                site_config_id=site_config_id,
                previous_snapshot_id=latest_snapshot.id,
                current_snapshot_id=snapshot.id,
                previous_fingerprint_hash=latest_snapshot.fingerprint_hash,
                current_fingerprint_hash=fingerprint,
                detection_source=source,
                change_type="structure_update",
                changed_sections=changed_sections,
                change_summary=summary,
                llm_review_status="pending",
                detected_at=now,
            )
        )

    return snapshot
