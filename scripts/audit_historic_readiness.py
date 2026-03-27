"""Audit and optionally fix historic-depth readiness for all active catalog sites.

This script performs a deterministic tracker audit (no network calls) using the same
pagination heuristics as the scraper engine. It helps guarantee that historic mode
has enough seeded depth to crawl far back in history.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from news_scraper.config import (
    CategoryPaginationTracker,
    SiteCatalog,
    load_json_model,
    save_json_model,
)
from news_scraper.scraping.engine import (
    default_runtime_config,
    supports_explicit_pagination,
    supports_implicit_pagination,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit historic scraping readiness for all active sites and optionally seed depth."
    )
    parser.add_argument("--catalog", help="Override site catalog JSON path.")
    parser.add_argument("--tracker", help="Override category tracker JSON path.")
    parser.add_argument(
        "--min-pages",
        type=int,
        default=50,
        help="Minimum total_known_pages required for paginatable categories.",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Seed total_known_pages to --min-pages for shallow paginatable categories.",
    )
    parser.add_argument(
        "--report",
        default="news_scraper/data/exports/historic_readiness_report.json",
        help="Path to write JSON audit report.",
    )
    return parser


def category_is_paginatable(url: str) -> bool:
    return supports_explicit_pagination(url) or supports_implicit_pagination(url)


def main() -> None:
    args = build_parser().parse_args()
    runtime = default_runtime_config()
    if args.catalog:
        runtime.catalog_path = Path(args.catalog)
    if args.tracker:
        runtime.tracker_path = Path(args.tracker)

    catalog = load_json_model(runtime.catalog_path, SiteCatalog)
    tracker = load_json_model(runtime.tracker_path, CategoryPaginationTracker)
    tracker_by_site = {site.site_name: site for site in tracker.sites}

    report_sites: list[dict[str, Any]] = []
    updated_categories = 0
    updated_sites = 0

    active_sites = [site for site in catalog.sites if site.active]
    for site in active_sites:
        site_tracker = tracker_by_site.get(site.site_name)
        categories = list(site_tracker.categories) if site_tracker else []
        total_categories = len(categories)

        paginatable = []
        deep_ready = 0
        shallow_indexes: list[int] = []
        known_pages_values: list[int] = []

        for idx, category in enumerate(categories):
            known_pages = int(category.total_known_pages)
            known_pages_values.append(known_pages)
            category_url = str(category.category_url)
            if not category_is_paginatable(category_url):
                continue
            paginatable.append(category_url)
            if known_pages >= args.min_pages:
                deep_ready += 1
            else:
                shallow_indexes.append(idx)

        seeded_for_site = 0
        if args.fix and site_tracker and shallow_indexes:
            for idx in shallow_indexes:
                category = site_tracker.categories[idx]
                if category.total_known_pages < args.min_pages:
                    category.total_known_pages = args.min_pages
                    seeded_for_site += 1
                    updated_categories += 1
            if seeded_for_site:
                updated_sites += 1

        if total_categories == 0:
            status = "no_categories"
        elif not paginatable:
            status = "no_paginatable_categories"
        elif deep_ready == len(paginatable):
            status = "ready_deep_historic"
        else:
            status = "needs_depth_seed"

        report_sites.append(
            {
                "site_name": site.site_name,
                "status": status,
                "category_count": total_categories,
                "paginatable_category_count": len(paginatable),
                "deep_ready_category_count": deep_ready if not args.fix else (deep_ready + seeded_for_site),
                "seeded_category_count": seeded_for_site,
                "min_known_pages": min(known_pages_values) if known_pages_values else 0,
                "max_known_pages": max(known_pages_values) if known_pages_values else 0,
            }
        )

    if args.fix and updated_categories:
        save_json_model(runtime.tracker_path, tracker)

    status_counts: dict[str, int] = {}
    for row in report_sites:
        status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1

    report_payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "active_site_count": len(active_sites),
        "min_pages_target": args.min_pages,
        "fix_applied": bool(args.fix),
        "updated_site_count": updated_sites,
        "updated_category_count": updated_categories,
        "status_counts": status_counts,
        "sites": report_sites,
    }

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Active sites audited: {len(active_sites)}")
    print(f"Status counts: {status_counts}")
    print(f"Depth target (--min-pages): {args.min_pages}")
    print(f"Fix applied: {args.fix}")
    print(f"Updated sites: {updated_sites}")
    print(f"Updated categories: {updated_categories}")
    print(f"Report: {report_path}")


if __name__ == "__main__":
    main()
