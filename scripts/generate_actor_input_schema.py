"""Generate Apify input schema with dropdown options sourced from JSON catalogs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "news_scraper" / "data" / "catalog" / "site_catalog.json"
OUTPUT_PATH = ROOT / ".actor" / "input_schema.json"
DEFAULT_SITE_NAME = "AP News"
DEFAULT_MAX_ITEMS_PER_SITE = 10


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_site_options(catalog: dict[str, Any]) -> list[str]:
    active_sites = [site for site in catalog.get("sites", []) if site.get("active")]
    active_sites.sort(key=lambda site: str(site.get("site_name", "")).lower())

    site_names: list[str] = []
    for site in active_sites:
        site_name = str(site.get("site_name", "")).strip()
        if not site_name:
            continue
        site_names.append(site_name)
    return site_names


def build_schema(site_names: list[str]) -> dict[str, Any]:
    default_site_selection = [DEFAULT_SITE_NAME] if DEFAULT_SITE_NAME in site_names else (site_names[:1] if site_names else [])
    return {
        "title": "The Rise of the Phoenix input",
        "type": "object",
        "schemaVersion": 1,
        "properties": {
            "sites_to_scrape": {
                "title": "Websites to scrape",
                "type": "array",
                "description": (
                    "Select one or more active websites. Leave empty to scrape all active "
                    "sites in the catalog."
                ),
                "editor": "select",
                "prefill": default_site_selection,
                "default": default_site_selection,
                "uniqueItems": True,
                "items": {
                    "type": "string",
                    "enum": site_names,
                },
            },
            "categories_to_scrape": {
                "title": "Categories to scrape",
                "type": "array",
                "description": (
                    "Optional category overrides in the format 'Site Name|||https://category-url'. "
                    "Leave empty to scrape all tracked categories for selected websites."
                ),
                "editor": "stringList",
                "prefill": [],
                "uniqueItems": True,
                "items": {
                    "type": "string",
                },
            },
            "execution_mode": {
                "title": "Execution mode",
                "type": "string",
                "description": "Choose current mode for recent pages or historic mode for deep pagination.",
                "editor": "select",
                "enum": ["current", "historic"],
                "enumTitles": [
                    "Current (latest pages only)",
                    "Historic (deep crawl to cutoff date)",
                ],
                "default": "current",
            },
            "historic_cutoff_date": {
                "title": "Historic cutoff date",
                "type": "string",
                "description": (
                    "Required for historic mode. ISO 8601 timestamp; stop when articles are older than "
                    "this value."
                ),
                "editor": "textfield",
                "example": "2025-01-01T00:00:00Z",
            },
            "max_items_per_site": {
                "title": "Article limit per site",
                "type": "integer",
                "description": "Per-site article cap when no limit is disabled.",
                "editor": "number",
                "minimum": 1,
                "maximum": 20000,
                "default": DEFAULT_MAX_ITEMS_PER_SITE,
            },
            "no_items_limit": {
                "title": "No article limit",
                "type": "boolean",
                "description": "If enabled, max_items_per_site is ignored.",
                "default": False,
            },
            "proxy_config": {
                "title": "Proxy configuration",
                "type": "object",
                "description": "Select Apify Proxy or provide custom proxy URLs for difficult sites.",
                "editor": "proxy",
                "prefill": {
                    "useApifyProxy": True,
                    "apifyProxyGroups": ["RESIDENTIAL"],
                },
            },
            "site_category_filters": {
                "title": "Advanced: manual site category filters",
                "type": "array",
                "description": (
                    "Optional legacy override. Prefer categories_to_scrape entries above."
                ),
                "editor": "schemaBased",
                "prefill": [],
                "items": {
                    "type": "object",
                    "properties": {
                        "site_name": {
                            "title": "Site name",
                            "type": "string",
                            "description": "Exact site_name from the catalog.",
                            "editor": "select",
                            "enum": site_names,
                        },
                        "category_urls": {
                            "title": "Category URLs",
                            "type": "array",
                            "description": "Tracked category URLs for that site.",
                            "editor": "stringList",
                            "items": {
                                "type": "string",
                            },
                        },
                    },
                    "required": ["site_name", "category_urls"],
                    "additionalProperties": False,
                },
            },
        },
    }


def main() -> None:
    catalog = load_json(CATALOG_PATH)
    site_names = build_site_options(catalog)
    schema = build_schema(site_names)
    OUTPUT_PATH.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
