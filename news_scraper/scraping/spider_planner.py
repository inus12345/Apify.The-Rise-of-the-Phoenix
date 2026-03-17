"""Spider diagram bootstrap helpers."""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..database.models import SiteConfig, SpiderDiagram, SpiderEdge, SpiderNode


def ensure_default_spider_diagram(
    db_session: Session,
    site_config: SiteConfig,
    diagram_name: str = "default_news_flow",
) -> SpiderDiagram:
    """
    Create a default spider diagram for a site when one does not exist.

    Diagram structure:
    seed -> category -> pagination -> article -> extraction
    """
    existing = (
        db_session.query(SpiderDiagram)
        .filter(
            SpiderDiagram.site_config_id == site_config.id,
            SpiderDiagram.name == diagram_name,
            SpiderDiagram.is_active.is_(True),
        )
        .order_by(SpiderDiagram.version.desc())
        .first()
    )
    if existing:
        return existing

    diagram = SpiderDiagram(
        site_config_id=site_config.id,
        name=diagram_name,
        version=1,
        entrypoint_url=site_config.url,
        is_active=True,
        notes="Auto-generated baseline spider flow with scraper priority hints.",
    )
    db_session.add(diagram)
    db_session.flush()

    seed_node = SpiderNode(
        spider_diagram_id=diagram.id,
        node_key="seed",
        node_type="seed",
        url_pattern=site_config.url,
        visit_order=1,
        notes="Site entry point.",
    )
    category_node = SpiderNode(
        spider_diagram_id=diagram.id,
        node_key="category",
        node_type="category",
        url_pattern=site_config.category_url_pattern or site_config.url,
        selector=site_config.article_selector or "a[href]",
        visit_order=2,
        notes="Category/listing page traversal.",
    )
    pagination_node = SpiderNode(
        spider_diagram_id=diagram.id,
        node_key="pagination",
        node_type="pagination",
        url_pattern=site_config.category_url_pattern or f"{site_config.url}?page={{page}}",
        pagination_rule="{page}",
        visit_order=3,
        notes="Iterate listing pages.",
    )
    article_node = SpiderNode(
        spider_diagram_id=diagram.id,
        node_key="article",
        node_type="article",
        selector=site_config.article_selector or "a[href]",
        visit_order=4,
        notes="Resolve article URLs from listing pages.",
    )
    extract_node = SpiderNode(
        spider_diagram_id=diagram.id,
        node_key="extract",
        node_type="extract",
        selector=site_config.body_selector or "article",
        extraction_target={
            "required_fields": [
                "title",
                "body",
                "date_publish",
                "scrape_date",
                "extra_links",
                "image_links",
            ],
            "optional_fields": [
                "authors",
                "description",
                "canonical_url",
                "section",
                "tags",
                "word_count",
                "reading_time_minutes",
                "raw_metadata",
            ],
            "selectors": {
                "title": site_config.title_selector,
                "date_publish": site_config.date_selector,
                "authors": site_config.author_selector,
                "body": site_config.body_selector,
            },
            "scraper_priority": [
                site_config.preferred_scraper_type or "scrapling",
                "pydoll",
                "selenium",
            ],
            "content_parser": (
                site_config.scrape_strategy.content_parser
                if site_config.scrape_strategy and site_config.scrape_strategy.content_parser
                else "beautifulsoup"
            ),
        },
        visit_order=5,
        notes="Final extraction fields with explicit scraper order metadata.",
    )

    db_session.add_all([seed_node, category_node, pagination_node, article_node, extract_node])
    db_session.flush()

    edges = [
        SpiderEdge(
            spider_diagram_id=diagram.id,
            from_node_id=seed_node.id,
            to_node_id=category_node.id,
            traversal_type="follow_link",
            link_selector="a[href]",
            priority=10,
            notes="Enter category flow from seed URL.",
        ),
        SpiderEdge(
            spider_diagram_id=diagram.id,
            from_node_id=category_node.id,
            to_node_id=pagination_node.id,
            traversal_type="paginate",
            link_selector="a[rel='next'], .pagination a",
            priority=20,
            notes="Follow pagination links.",
        ),
        SpiderEdge(
            spider_diagram_id=diagram.id,
            from_node_id=pagination_node.id,
            to_node_id=article_node.id,
            traversal_type="follow_link",
            link_selector=site_config.article_selector or "a[href]",
            priority=30,
            notes="Collect article links from each listing page.",
        ),
        SpiderEdge(
            spider_diagram_id=diagram.id,
            from_node_id=article_node.id,
            to_node_id=extract_node.id,
            traversal_type="extract",
            link_selector=None,
            priority=40,
            notes="Fetch article page and extract fields.",
        ),
    ]
    db_session.add_all(edges)
    db_session.commit()
    db_session.refresh(diagram)
    return diagram
