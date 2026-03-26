"""Smoke-test one listing page and one sample article per site and category."""

from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

from news_scraper.config import (
    CategoryPaginationTracker,
    ScrapingTool,
    SelectorMap,
    SiteCatalog,
    load_json_model,
    save_json_data,
)
from news_scraper.scraping.engine import FetchError, ScraperEngine, default_runtime_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Smoke-test one page per site/category")
    parser.add_argument("--sites", nargs="*", default=None, help="Optional subset of site names")
    parser.add_argument("--sites-file", help="JSON file containing objects with site_name fields")
    parser.add_argument(
        "--active-only",
        action="store_true",
        help="Only verify sites currently marked active in the catalog",
    )
    parser.add_argument("--catalog", help="Override the site catalog JSON path")
    parser.add_argument("--selectors", help="Override the selector map JSON path")
    parser.add_argument("--tracker", help="Override the tracker JSON path")
    parser.add_argument(
        "--homepage-only",
        action="store_true",
        help="Only verify the homepage/front page for each site",
    )
    parser.add_argument(
        "--output",
        default="news_scraper/data/exports/smoke_test_sites.json",
        help="Where to write the JSON report",
    )
    parser.add_argument("--timeout", type=int, default=20, help="Fetcher timeout in seconds")
    parser.add_argument("--workers", type=int, default=6, help="Number of sites to test in parallel")
    parser.add_argument(
        "--articles-per-page",
        type=int,
        default=1,
        help="How many sample articles to verify from each listing page",
    )
    parser.add_argument(
        "--fast-http-only",
        action="store_true",
        help="Use Scrapling/httpx only (skip Pydoll and Selenium) for faster validation runs",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.fast_http_only:
        os.environ["NEWS_SCRAPER_FORCE_HTTPX_FETCH"] = "1"
    runtime = default_runtime_config()
    if args.catalog:
        runtime.catalog_path = Path(args.catalog)
    if args.selectors:
        runtime.selectors_path = Path(args.selectors)
    if args.tracker:
        runtime.tracker_path = Path(args.tracker)

    catalog = load_json_model(runtime.catalog_path, SiteCatalog)
    selector_map = load_json_model(runtime.selectors_path, SelectorMap)
    tracker = load_json_model(runtime.tracker_path, CategoryPaginationTracker)
    selector_by_name = {site.site_name: site for site in selector_map.sites}
    tracker_by_name = {site.site_name: site for site in tracker.sites}

    selected = set(args.sites or [])
    if args.sites_file:
        payload = json.loads(Path(args.sites_file).read_text(encoding="utf-8"))
        selected.update(item["site_name"] for item in payload)
    sites = [site for site in catalog.sites if not selected or site.site_name in selected]
    if args.active_only:
        sites = [site for site in sites if site.active]
    results: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=max(args.workers, 1)) as executor:
        future_map = {
            executor.submit(
                inspect_site,
                site,
                selector_by_name,
                tracker_by_name,
                args.timeout,
                args.articles_per_page,
                args.homepage_only,
                args.fast_http_only,
            ): site.site_name
            for site in sites
        }
        for future in as_completed(future_map):
            results.append(future.result())
            save_report(args.output, results)

    output = build_report(results)
    save_json_data(args.output, output)
    print(f"Smoke-tested sites: {len(results)}")
    print(f"All-green sites: {output['summary']['all_green_sites']}")
    print(f"Report: {args.output}")


def inspect_listing(
    engine: ScraperEngine,
    page_url: str,
    base_url: str,
    preferred_tool,
    selectors,
    articles_per_page: int,
) -> dict[str, object]:
    result: dict[str, object] = {
        "page_url": page_url,
        "status": "error",
        "tool_used": None,
        "links_found": 0,
        "articles_attempted": 0,
        "articles_succeeded": 0,
        "article_results": [],
    }
    try:
        fetch = engine.fetch_with_fallback(page_url, preferred_tool=preferred_tool)
        result["tool_used"] = fetch.tool.value
        links = engine.extract_listing_links(fetch.html, base_url, selectors)
        result["links_found"] = len(links)
        if not links:
            result["error"] = "No article links found"
            return result

        required_article_count = max(articles_per_page, 1)
        candidate_count = max(required_article_count * 4, required_article_count)
        candidate_urls = links[:candidate_count]
        attempted_urls: list[str] = []
        successful_urls: list[str] = []

        for article_url in candidate_urls:
            if len(successful_urls) >= required_article_count:
                break
            article_result: dict[str, object] = {
                "article_url": article_url,
                "status": "error",
            }
            attempted_urls.append(article_url)
            try:
                article_fetch = engine.fetch_with_fallback(article_url, preferred_tool=preferred_tool)
                article_result["tool_used"] = article_fetch.tool.value
                article = engine.extract_article(article_fetch.html, article_url, selectors)
                article_result["status"] = "ok"
                article_result["article_title"] = article["article_title"]
                article_result["has_body"] = bool(article.get("article_body"))
                article_result["has_date_published"] = bool(article.get("date_published"))
                result["articles_succeeded"] += 1
                successful_urls.append(article_url)
            except FetchError as exc:
                article_result["error"] = str(exc)
                article_result["attempts"] = [
                    {
                        "tool": attempt.tool.value,
                        "success": attempt.success,
                        "error_type": attempt.error_type,
                        "block_detected": attempt.block_detected,
                        "message": attempt.message,
                    }
                    for attempt in exc.attempts
                ]
            except Exception as exc:  # pragma: no cover - operational telemetry
                article_result["error"] = f"{exc.__class__.__name__}: {exc}"
            result["article_results"].append(article_result)

        result["articles_attempted"] = len(attempted_urls)
        result["sample_article_urls"] = attempted_urls
        result["successful_article_urls"] = successful_urls
        if result["articles_succeeded"] < required_article_count:
            result["error"] = (
                f"Only {result['articles_succeeded']} of {required_article_count} sample articles "
                "scraped successfully"
            )
            return result

        first_success = next((item for item in result["article_results"] if item.get("status") == "ok"), None)
        result["status"] = "ok"
        if first_success:
            result["sample_article_url"] = first_success["article_url"]
            result["article_title"] = first_success.get("article_title")
            result["has_body"] = first_success.get("has_body")
            result["has_date_published"] = first_success.get("has_date_published")
        return result
    except FetchError as exc:
        result["error"] = str(exc)
        result["attempts"] = [
            {
                "tool": attempt.tool.value,
                "success": attempt.success,
                "error_type": attempt.error_type,
                "block_detected": attempt.block_detected,
                "message": attempt.message,
            }
            for attempt in exc.attempts
        ]
        return result
    except Exception as exc:  # pragma: no cover - operational telemetry
        result["error"] = f"{exc.__class__.__name__}: {exc}"
        return result


def inspect_site(
    site,
    selector_by_name,
    tracker_by_name,
    timeout: int,
    articles_per_page: int,
    homepage_only: bool,
    fast_http_only: bool,
) -> dict[str, object]:
    engine = ScraperEngine(timeout=timeout)
    if fast_http_only:
        engine.strict_order = [ScrapingTool.SCRAPLING]
        engine.available_tools = [tool for tool in engine.available_tools if tool == ScrapingTool.SCRAPLING]
    site_result: dict[str, object] = {
        "site_name": site.site_name,
        "base_url": str(site.base_url),
        "active": site.active,
        "homepage": {},
        "categories": [],
    }
    selectors = selector_by_name.get(site.site_name)
    if selectors is None:
        site_result["homepage"] = {"status": "error", "error": "Missing selector map"}
        return site_result

    site_result["homepage"] = inspect_listing(
        engine,
        str(site.base_url),
        str(site.base_url),
        site.preferred_scraping_tool,
        selectors,
        articles_per_page,
    )

    site_tracker = tracker_by_name.get(site.site_name)
    if site_tracker and not homepage_only:
        for category in site_tracker.categories:
            category_result = inspect_listing(
                engine,
                str(category.category_url),
                str(category.category_url),
                site.preferred_scraping_tool,
                selectors,
                articles_per_page,
            )
            category_result["category_name"] = category.category_name
            site_result["categories"].append(category_result)
    site_result["overall_status"] = classify_site_result(site_result)
    return site_result


def classify_site_result(result: dict[str, object]) -> str:
    if not result.get("active", True):
        return "inactive"
    homepage_ok = result.get("homepage", {}).get("status") == "ok"
    categories_ok = all(item.get("status") == "ok" for item in result.get("categories", []))
    return "ok" if homepage_ok and categories_ok else "needs_attention"


def build_report(results: list[dict[str, object]]) -> dict[str, object]:
    ordered_results = sorted(results, key=lambda item: str(item["site_name"]).casefold())
    summary = {
        "all_green_sites": 0,
        "needs_attention_sites": 0,
        "inactive_sites": 0,
        "active_sites": 0,
    }
    for result in ordered_results:
        status = result.get("overall_status") or classify_site_result(result)
        result["overall_status"] = status
        if result.get("active", True):
            summary["active_sites"] += 1
        else:
            summary["inactive_sites"] += 1
        if status == "ok":
            summary["all_green_sites"] += 1
        elif status == "needs_attention":
            summary["needs_attention_sites"] += 1

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "site_count": len(ordered_results),
        "summary": summary,
        "results": ordered_results,
    }


def save_report(path: str, results: list[dict[str, object]]) -> None:
    save_json_data(path, build_report(results))


if __name__ == "__main__":
    main()
