"""Validate and repair tracker categories for a batch of sites."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from news_scraper.config import (
    CategoryPaginationTracker,
    CategoryState,
    ScrapingTool,
    SelectorMap,
    SiteCatalog,
    load_json_model,
    normalize_url,
    save_json_model,
)
from news_scraper.scraping.engine import (
    ScraperEngine,
    build_page_url,
    default_runtime_config,
    derive_category_name,
    get_or_create_site_tracker,
    supports_implicit_pagination,
)

BAD_CATEGORY_PATH = re.compile(
    r"/(tag|tags|author|authors|search|login|subscribe|newsletter|privacy|terms|about|contact|advert|"
    r"video|videos|audio|podcast|live|shop|careers|jobs|events|epaper|cart|account|comment|comments|"
    r"user|register|password|faq|services|feed|cdn-cgi|email-protection|offres|offers|checkout|"
    r"identity-service|helpcenter|media-kit|connexion|abonnement|abonnements|compte|"
    r"mentions-legales|a-propos|nous-contacter|web-tv|admin|users|newsletters|categories)"
    r"(/|$)",
    re.IGNORECASE,
)
BAD_CATEGORY_SUBSTRINGS = (
    "/redirect",
    "/consent",
    "/collectconsent",
    "/partners-list",
    "/v2/partners",
    "/post/submit",
    "/reader-resources",
    "/classifieds",
    "/help/",
    "/helpcenter",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Repair category tracker entries for selected sites")
    parser.add_argument("--sites-file", required=True, help="JSON file containing objects with site_name fields")
    parser.add_argument("--catalog", help="Override the site catalog JSON path")
    parser.add_argument("--selectors", help="Override the selector map JSON path")
    parser.add_argument("--tracker", help="Override the tracker JSON path")
    parser.add_argument("--timeout", type=int, default=12, help="HTTP timeout in seconds")
    parser.add_argument("--max-categories", type=int, default=8, help="Max working categories to keep per site")
    parser.add_argument(
        "--historic-pages",
        type=int,
        default=50,
        help="Seed total_known_pages for categories where page-2 probing works",
    )
    parser.add_argument(
        "--deactivate-on-failure",
        action="store_true",
        help="Mark sites inactive when no working categories can be validated",
    )
    return parser


def validate_category(
    engine: ScraperEngine,
    category_url: str,
    selectors: Any,
) -> tuple[bool, bool]:
    """Return (category_valid, supports_pagination)."""

    try:
        listing = engine.fetch_with_tool(category_url, tool=ScrapingTool.SCRAPLING)
        links = engine.extract_listing_links(listing.html, category_url, selectors)
        if not links:
            return (False, False)

        article_url = links[0]
        article_fetch = engine.fetch_with_tool(article_url, tool=ScrapingTool.SCRAPLING)
        engine.extract_article(article_fetch.html, article_url, selectors)
    except Exception:
        return (False, False)

    pagination_supported = False
    page2_url = build_page_url(category_url, 2)
    if normalize_url(page2_url) != normalize_url(category_url):
        try:
            page2_fetch = engine.fetch_with_tool(page2_url, tool=ScrapingTool.SCRAPLING)
            page2_links = engine.extract_listing_links(page2_fetch.html, page2_url, selectors)
            pagination_supported = bool(page2_links)
        except Exception:
            pagination_supported = False

    return (True, pagination_supported)


def is_likely_news_category(url: str) -> bool:
    parsed = urlsplit(url)
    lowered_path = parsed.path.lower()
    lowered = f"{parsed.path}?{parsed.query}".lower()
    if BAD_CATEGORY_PATH.search(lowered_path):
        return False
    if any(token in lowered for token in BAD_CATEGORY_SUBSTRINGS):
        return False
    return True


def main() -> None:
    args = build_parser().parse_args()
    runtime = default_runtime_config()
    if args.catalog:
        runtime.catalog_path = Path(args.catalog)
    if args.selectors:
        runtime.selectors_path = Path(args.selectors)
    if args.tracker:
        runtime.tracker_path = Path(args.tracker)

    payload = json.loads(Path(args.sites_file).read_text(encoding="utf-8"))
    selected = {str(item.get("site_name", "")).strip() for item in payload if str(item.get("site_name", "")).strip()}
    if not selected:
        raise SystemExit("No site_name values found in sites-file payload.")

    catalog = load_json_model(runtime.catalog_path, SiteCatalog)
    selector_map = load_json_model(runtime.selectors_path, SelectorMap)
    tracker = load_json_model(runtime.tracker_path, CategoryPaginationTracker)
    selectors_by_name = {site.site_name: site for site in selector_map.sites}

    engine = ScraperEngine(timeout=args.timeout)
    engine.strict_order = [ScrapingTool.SCRAPLING]
    engine.available_tools = [tool for tool in engine.available_tools if tool == ScrapingTool.SCRAPLING]

    repaired = 0
    deactivated = 0
    summary: list[dict[str, Any]] = []

    try:
        for site in catalog.sites:
            if site.site_name not in selected:
                continue

            selectors = selectors_by_name.get(site.site_name)
            if selectors is None:
                summary.append(
                    {
                        "site_name": site.site_name,
                        "status": "missing_selectors",
                        "kept_categories": 0,
                        "active": site.active,
                    }
                )
                continue

            site_tracker = get_or_create_site_tracker(tracker, site.site_name)
            candidate_urls: list[str] = [normalize_url(str(site.base_url))]
            try:
                homepage_fetch = engine.fetch_with_tool(str(site.base_url), tool=ScrapingTool.SCRAPLING)
                discovered = engine.extractor.discover_category_urls(
                    homepage_fetch.html,
                    str(site.base_url),
                    limit_categories=max(args.max_categories * 3, 12),
                )
                for category_url in discovered:
                    normalized = normalize_url(str(category_url))
                    if normalized not in candidate_urls:
                        candidate_urls.append(normalized)
            except Exception:
                pass
            for state in site_tracker.categories:
                normalized = normalize_url(str(state.category_url))
                if normalized not in candidate_urls:
                    candidate_urls.append(normalized)

            candidate_urls = [url for url in candidate_urls if is_likely_news_category(url)]

            repaired_states: list[CategoryState] = []
            for category_url in candidate_urls:
                valid, supports_pagination = validate_category(engine, category_url, selectors)
                if not valid:
                    continue
                seeded_pages = 1
                if supports_pagination:
                    seeded_pages = max(args.historic_pages, 2)
                elif supports_implicit_pagination(category_url):
                    seeded_pages = max(min(args.historic_pages, 3), 2)
                repaired_states.append(
                    CategoryState(
                        category_name=derive_category_name(category_url),
                        category_url=category_url,
                        total_known_pages=seeded_pages,
                        last_scraped_page_index=0,
                    )
                )
                if len(repaired_states) >= args.max_categories:
                    break

            if not repaired_states:
                repaired_states = [
                    CategoryState(
                        category_name="front_page",
                        category_url=normalize_url(str(site.base_url)),
                        total_known_pages=1,
                        last_scraped_page_index=0,
                    )
                ]
                if args.deactivate_on_failure and site.active:
                    site.active = False
                    note = "Auto-deactivated during category repair: no working category/article pair validated via Scrapling."
                    site.notes = f"{site.notes} {note}".strip() if site.notes else note
                    deactivated += 1
                    status = "deactivated"
                else:
                    status = "fallback_front_page_only"
            else:
                status = "repaired"
                repaired += 1
                site.active = True

            site_tracker.categories = repaired_states
            summary.append(
                {
                    "site_name": site.site_name,
                    "status": status,
                    "kept_categories": len(repaired_states),
                    "active": site.active,
                }
            )
    finally:
        engine.close()

    save_json_model(runtime.catalog_path, catalog)
    save_json_model(runtime.tracker_path, tracker)

    print(f"Sites requested: {len(selected)}")
    print(f"Sites repaired: {repaired}")
    print(f"Sites deactivated: {deactivated}")
    for row in summary:
        print(
            f"- {row['site_name']}: status={row['status']} kept_categories={row['kept_categories']} active={row['active']}"
        )


if __name__ == "__main__":
    main()
