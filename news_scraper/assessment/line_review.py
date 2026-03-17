"""Line-by-line LLM assessment workflow helpers."""
from __future__ import annotations

from datetime import datetime
import json
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session, joinedload

from ..database.session import get_spider_session
from ..database.models import (
    LLMAssessmentLine,
    LLMAssessmentRun,
    ScrapeStrategy,
    SiteCategory,
    SiteConfig,
    SpiderDiagram,
    SpiderEdge,
    SpiderNode,
)
from .structure_tracker import capture_site_structure_snapshot


def _serialize_value(value: Any) -> Optional[str]:
    """Serialize values to a text payload for review."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _iter_entity_fields(entity_type: str, entity: Any) -> Iterable[Tuple[str, Optional[str]]]:
    """Yield field/value pairs for each assessable entity type."""
    field_map: Dict[str, List[str]] = {
        "site_config": [
            "name",
            "url",
            "domain",
            "country",
            "language",
            "server_header",
            "server_vendor",
            "hosting_provider",
            "technology_stack_summary",
            "preferred_scraper_type",
            "uses_javascript",
            "status",
            "notes",
        ],
        "site_category": [
            "name",
            "url",
            "max_pages",
            "page_url_pattern",
            "start_page",
            "active",
        ],
        "scrape_strategy": [
            "scraper_engine",
            "fallback_engine_chain",
            "content_parser",
            "browser_automation_tool",
            "rendering_required",
            "requires_proxy",
            "proxy_region",
            "login_required",
            "auth_strategy",
            "anti_bot_protection",
            "blocking_signals",
            "bypass_techniques",
            "rate_limit_per_minute",
            "notes",
        ],
        "spider_diagram": [
            "name",
            "version",
            "entrypoint_url",
            "is_active",
            "notes",
        ],
        "spider_node": [
            "node_key",
            "node_type",
            "url_pattern",
            "selector",
            "extraction_target",
            "pagination_rule",
            "visit_order",
            "active",
            "notes",
        ],
        "spider_edge": [
            "from_node_id",
            "to_node_id",
            "traversal_type",
            "link_selector",
            "condition_expression",
            "priority",
            "notes",
        ],
    }

    for field_name in field_map.get(entity_type, []):
        value = getattr(entity, field_name, None)
        yield field_name, _serialize_value(value)


def create_line_assessment_run(
    db_session: Session,
    site_config_id: int,
    llm_model: str = "gpt-4.1-mini",
    trigger_type: str = "manual",
    scope: str = "full",
    spider_session: Optional[Session] = None,
) -> LLMAssessmentRun:
    """
    Create a line-by-line assessment run for a site and linked planning data.

    Primary DB entities (site config + strategy) are read from `db_session`.
    Spider/category entities are read from `spider_session`.
    """
    owns_spider_session = spider_session is None
    if spider_session is None:
        spider_session = next(get_spider_session())

    try:
        site = (
            db_session.query(SiteConfig)
            .options(joinedload(SiteConfig.scrape_strategy))
            .filter(SiteConfig.id == site_config_id)
            .first()
        )
        if not site:
            raise ValueError(f"SiteConfig not found: {site_config_id}")

        categories = (
            spider_session.query(SiteCategory)
            .filter(SiteCategory.site_config_id == site.id)
            .order_by(SiteCategory.id.asc())
            .all()
        )
        diagrams = (
            spider_session.query(SpiderDiagram)
            .options(joinedload(SpiderDiagram.nodes), joinedload(SpiderDiagram.edges))
            .filter(SpiderDiagram.site_config_id == site.id)
            .order_by(SpiderDiagram.id.asc())
            .all()
        )

        run = LLMAssessmentRun(
            site_config_id=site.id,
            trigger_type=trigger_type,
            scope=scope,
            status="running",
            llm_model=llm_model,
            started_at=datetime.now(),
        )
        db_session.add(run)
        db_session.flush()

        lines: List[LLMAssessmentLine] = []
        line_number = 1

        for field_name, current_value in _iter_entity_fields("site_config", site):
            lines.append(
                LLMAssessmentLine(
                    assessment_run_id=run.id,
                    line_number=line_number,
                    entity_type="site_config",
                    entity_id=site.id,
                    field_name=field_name,
                    current_value=current_value,
                    suggested_value=None,
                    recommended_action="keep",
                    reasoning="Pending LLM review.",
                    status="pending",
                )
            )
            line_number += 1

        for category in categories:
            for field_name, current_value in _iter_entity_fields("site_category", category):
                lines.append(
                    LLMAssessmentLine(
                        assessment_run_id=run.id,
                        line_number=line_number,
                        entity_type="site_category",
                        entity_id=category.id,
                        field_name=field_name,
                        current_value=current_value,
                        suggested_value=None,
                        recommended_action="keep",
                        reasoning="Pending LLM review.",
                        status="pending",
                    )
                )
                line_number += 1

        strategy = site.scrape_strategy
        if strategy:
            for field_name, current_value in _iter_entity_fields("scrape_strategy", strategy):
                lines.append(
                    LLMAssessmentLine(
                        assessment_run_id=run.id,
                        line_number=line_number,
                        entity_type="scrape_strategy",
                        entity_id=strategy.id,
                        field_name=field_name,
                        current_value=current_value,
                        suggested_value=None,
                        recommended_action="keep",
                        reasoning="Pending LLM review.",
                        status="pending",
                    )
                )
                line_number += 1

        for diagram in diagrams:
            for field_name, current_value in _iter_entity_fields("spider_diagram", diagram):
                lines.append(
                    LLMAssessmentLine(
                        assessment_run_id=run.id,
                        line_number=line_number,
                        entity_type="spider_diagram",
                        entity_id=diagram.id,
                        field_name=field_name,
                        current_value=current_value,
                        suggested_value=None,
                        recommended_action="keep",
                        reasoning="Pending LLM review.",
                        status="pending",
                    )
                )
                line_number += 1

            for node in sorted(diagram.nodes, key=lambda x: x.id):
                for field_name, current_value in _iter_entity_fields("spider_node", node):
                    lines.append(
                        LLMAssessmentLine(
                            assessment_run_id=run.id,
                            line_number=line_number,
                            entity_type="spider_node",
                            entity_id=node.id,
                            field_name=field_name,
                            current_value=current_value,
                            suggested_value=None,
                            recommended_action="keep",
                            reasoning="Pending LLM review.",
                            status="pending",
                        )
                    )
                    line_number += 1

            for edge in sorted(diagram.edges, key=lambda x: x.id):
                for field_name, current_value in _iter_entity_fields("spider_edge", edge):
                    lines.append(
                        LLMAssessmentLine(
                            assessment_run_id=run.id,
                            line_number=line_number,
                            entity_type="spider_edge",
                            entity_id=edge.id,
                            field_name=field_name,
                            current_value=current_value,
                            suggested_value=None,
                            recommended_action="keep",
                            reasoning="Pending LLM review.",
                            status="pending",
                        )
                    )
                    line_number += 1

        db_session.add_all(lines)
        run.total_lines = len(lines)
        run.status = "pending"
        run.completed_at = None
        db_session.commit()
        db_session.refresh(run)
        return run
    finally:
        if owns_spider_session:
            spider_session.close()


def export_assessment_payload(db_session: Session, assessment_run_id: int) -> Dict[str, Any]:
    """Export an assessment run into a JSON-ready payload for LLM review."""
    run = (
        db_session.query(LLMAssessmentRun)
        .options(joinedload(LLMAssessmentRun.lines))
        .filter(LLMAssessmentRun.id == assessment_run_id)
        .first()
    )
    if not run:
        raise ValueError(f"LLMAssessmentRun not found: {assessment_run_id}")

    lines_payload = []
    for line in sorted(run.lines, key=lambda x: x.line_number):
        lines_payload.append(
            {
                "line_number": line.line_number,
                "entity_type": line.entity_type,
                "entity_id": line.entity_id,
                "field_name": line.field_name,
                "current_value": line.current_value,
                "suggested_value": line.suggested_value,
                "recommended_action": line.recommended_action,
                "reasoning": line.reasoning,
                "confidence_score": line.confidence_score,
                "status": line.status,
            }
        )

    return {
        "assessment_run": {
            "id": run.id,
            "site_config_id": run.site_config_id,
            "trigger_type": run.trigger_type,
            "scope": run.scope,
            "status": run.status,
            "llm_model": run.llm_model,
            "total_lines": run.total_lines,
        },
        "instructions": {
            "review_style": "line-by-line",
            "allowed_actions": ["keep", "update", "remove", "review"],
            "required_fields_per_line": [
                "line_number",
                "recommended_action",
                "suggested_value",
                "reasoning",
                "confidence_score",
            ],
        },
        "lines": lines_payload,
    }


def _entity_class(entity_type: str):
    mapping = {
        "site_config": SiteConfig,
        "site_category": SiteCategory,
        "scrape_strategy": ScrapeStrategy,
        "spider_diagram": SpiderDiagram,
        "spider_node": SpiderNode,
        "spider_edge": SpiderEdge,
    }
    return mapping.get(entity_type)


def _target_session(entity_type: str, primary_session: Session, spider_session: Session) -> Session:
    if entity_type in {"site_category", "spider_diagram", "spider_node", "spider_edge"}:
        return spider_session
    return primary_session


def _decode_suggested_value(value: Optional[str]) -> Any:
    if value is None:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    if candidate.lower() in ("true", "false"):
        return candidate.lower() == "true"
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return value


def apply_line_updates(
    db_session: Session,
    assessment_run_id: int,
    approved_lines: List[Dict[str, Any]],
    reviewed_by: str = "llm",
    spider_session: Optional[Session] = None,
) -> LLMAssessmentRun:
    """
    Apply approved line-level updates from an LLM review output.

    `approved_lines` expects objects containing:
    - line_number
    - recommended_action (keep/update/remove/review)
    - suggested_value
    - reasoning
    - confidence_score
    """
    owns_spider_session = spider_session is None
    if spider_session is None:
        spider_session = next(get_spider_session())

    try:
        run = (
            db_session.query(LLMAssessmentRun)
            .options(joinedload(LLMAssessmentRun.lines))
            .filter(LLMAssessmentRun.id == assessment_run_id)
            .first()
        )
        if not run:
            raise ValueError(f"LLMAssessmentRun not found: {assessment_run_id}")

        run.status = "running"
        line_index = {line.line_number: line for line in run.lines}
        applied_count = 0
        flagged_count = 0

        for record in approved_lines:
            line_number = record.get("line_number")
            line = line_index.get(line_number)
            if not line:
                continue

            action = record.get("recommended_action", "keep")
            line.recommended_action = action
            line.suggested_value = _serialize_value(record.get("suggested_value"))
            line.reasoning = record.get("reasoning") or line.reasoning
            line.confidence_score = record.get("confidence_score")
            line.reviewed_by = reviewed_by
            line.reviewed_at = datetime.now()

            if action in ("update", "remove", "review"):
                flagged_count += 1

            if action == "update":
                entity_cls = _entity_class(line.entity_type)
                if entity_cls and line.entity_id:
                    target_session = _target_session(line.entity_type, db_session, spider_session)
                    entity = target_session.get(entity_cls, line.entity_id)
                    if entity and hasattr(entity, line.field_name):
                        setattr(entity, line.field_name, _decode_suggested_value(line.suggested_value))
                        line.status = "applied"
                        line.applied_at = datetime.now()
                        applied_count += 1
                        continue

            if action == "keep":
                line.status = "approved"
            elif action == "update":
                line.status = "rejected"
            else:
                line.status = "pending"

        run.lines_flagged = flagged_count
        run.lines_applied = applied_count
        if applied_count > 0:
            capture_site_structure_snapshot(
                primary_session=db_session,
                spider_session=spider_session,
                site_config_id=run.site_config_id,
                source="llm_apply",
                snapshot_notes=f"Assessment run {run.id} applied {applied_count} updates.",
            )
        run.completed_at = datetime.now()
        run.status = "complete"
        db_session.commit()
        spider_session.commit()
        db_session.refresh(run)
        return run
    except Exception:
        db_session.rollback()
        spider_session.rollback()
        raise
    finally:
        if owns_spider_session:
            spider_session.close()
