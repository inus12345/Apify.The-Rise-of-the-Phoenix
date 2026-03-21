"""Focused tests for scraping helper behavior."""

from news_scraper.config import (
    CategoryState,
    ExecutionMode,
    InputConfig,
    RunDatasets,
    ScrapingHistoryEntry,
    ScrapingTool,
    SiteCategoryTracker,
    SiteCatalogEntry,
    SiteSelectorConfig,
    SuccessDatasetItem,
    md5_url,
    utc_now,
)
from news_scraper.apify_actor import normalize_actor_input
from news_scraper.scraping.engine import (
    FetchResult,
    RuntimeConfig,
    ScraperEngine,
    ScraperRunner,
    build_page_url,
    choose_preferred_tool,
    order_tools,
    progress_percent,
)


def test_order_tools_prioritizes_preferred_without_duplication() -> None:
    ordered = order_tools(
        ScrapingTool.PYDOLL,
        [ScrapingTool.SCRAPLING, ScrapingTool.PYDOLL, ScrapingTool.SELENIUM],
    )

    assert ordered == [ScrapingTool.PYDOLL, ScrapingTool.SCRAPLING, ScrapingTool.SELENIUM]


def test_choose_preferred_tool_uses_success_rate_then_sample_size() -> None:
    history = [
        ScrapingHistoryEntry(
            timestamp=utc_now(),
            tool=ScrapingTool.SCRAPLING,
            success=True,
            success_rate=0.75,
            sample_size=4,
            avg_response_time_ms=500,
            block_detected=False,
            error_type=None,
        ),
        ScrapingHistoryEntry(
            timestamp=utc_now(),
            tool=ScrapingTool.PYDOLL,
            success=True,
            success_rate=0.90,
            sample_size=2,
            avg_response_time_ms=1200,
            block_detected=False,
            error_type=None,
        ),
    ]

    assert choose_preferred_tool(history) == ScrapingTool.PYDOLL


def test_build_page_url_uses_query_or_path_conventions() -> None:
    assert build_page_url("https://example.com/news?page=1", 3) == "https://example.com/news?page=3"
    assert build_page_url("https://example.com/news", 2) == "https://example.com/news/page/2"


def test_build_targets_can_filter_categories() -> None:
    runner = ScraperRunner(
        RuntimeConfig(
            catalog_path="catalog.json",
            selectors_path="selectors.json",
            tracker_path="tracker.json",
            output_dir="exports",
        )
    )
    site = SiteCatalogEntry(
        site_name="Example News",
        base_url="https://example.com",
        country="United States",
        region="North America",
        language="en",
        underlying_tech="WordPress",
        active=True,
        preferred_scraping_tool=ScrapingTool.SCRAPLING,
        scraping_history=[],
        notes=None,
        last_verified_at=None,
    )
    tracker = SiteCategoryTracker(
        site_name="Example News",
        categories=[
            CategoryState(
                category_name="world",
                category_url="https://example.com/world",
                total_known_pages=3,
                last_scraped_page_index=0,
            ),
            CategoryState(
                category_name="politics",
                category_url="https://example.com/politics",
                total_known_pages=2,
                last_scraped_page_index=0,
            ),
        ],
    )

    targets = runner._build_targets(
        site,
        tracker,
        ExecutionMode.CURRENT,
        selected_categories={"https://example.com/politics"},
    )

    assert targets == [
        ("https://example.com/politics", "https://example.com/politics", 1),
        ("https://example.com/politics", "https://example.com/politics/page/2", 2),
    ]


def test_progress_percent_handles_empty_totals() -> None:
    assert progress_percent(0, 0) == 100
    assert progress_percent(1, 4) == 25


def test_looks_blocked_detects_rate_limit_pages() -> None:
    engine = ScraperEngine()

    html = """
    <html>
        <body>
            <h1>HTTP Error 429 - Too many requests</h1>
            <p>Your device sent us too many requests in the past 5 minutes.</p>
        </body>
    </html>
    """

    assert engine._looks_blocked(html) is True


def test_scrape_site_appends_success_items(monkeypatch) -> None:
    runner = ScraperRunner(
        RuntimeConfig(
            catalog_path="catalog.json",
            selectors_path="selectors.json",
            tracker_path="tracker.json",
            output_dir="exports",
        )
    )
    site = SiteCatalogEntry(
        site_name="Example News",
        base_url="https://example.com",
        country="United States",
        region="North America",
        language="en",
        underlying_tech="WordPress",
        active=True,
        preferred_scraping_tool=ScrapingTool.SCRAPLING,
        scraping_history=[],
        notes=None,
        last_verified_at=None,
    )
    tracker = SiteCategoryTracker(
        site_name="Example News",
        categories=[
            CategoryState(
                category_name="world",
                category_url="https://example.com/world",
                total_known_pages=1,
                last_scraped_page_index=0,
            )
        ],
    )
    site_selectors = SiteSelectorConfig.model_validate(
        {
            "site_name": "Example News",
            "article_link_selectors": [
                {"type": "css", "value": "article a[href]", "attribute": "href", "multiple": True}
            ],
            "fields": {
                "article_title": {"selectors": [{"type": "css", "value": "h1"}], "required": True},
                "author": {"selectors": [{"type": "css", "value": ".author"}], "required": False},
                "article_body": {
                    "selectors": [{"type": "css", "value": "article p", "multiple": True}],
                    "required": True,
                },
                "tags": {
                    "selectors": [{"type": "css", "value": ".tags a", "multiple": True}],
                    "required": False,
                },
                "date_published": {"selectors": [{"type": "css", "value": "time", "attribute": "datetime"}], "required": True},
                "article_url": {"selectors": [{"type": "meta", "value": "og:url", "attribute": "content"}], "required": True},
                "url_hash": {"source_field": "article_url", "algorithm": "md5"},
                "main_image_url": {
                    "selectors": [{"type": "meta", "value": "og:image", "attribute": "content"}],
                    "required": False,
                },
                "seo_description": {
                    "selectors": [{"type": "meta", "value": "description", "attribute": "content"}],
                    "required": False,
                },
            },
        }
    )
    datasets = RunDatasets()
    input_config = InputConfig.model_validate(
        {
            "sites_to_scrape": ["Example News"],
            "max_items_per_site": 5,
            "proxy_config": {
                "useApifyProxy": False,
                "apifyProxyGroups": [],
                "countryCode": None,
            },
        }
    )

    monkeypatch.setattr(
        runner.engine,
        "fetch_with_fallback",
        lambda *args, **kwargs: FetchResult(
            url="https://example.com/world",
            html="<html><body></body></html>",
            tool=ScrapingTool.SCRAPLING,
            elapsed_ms=1,
            attempts=[],
        ),
    )
    monkeypatch.setattr(
        runner.engine,
        "extract_listing_links",
        lambda *args, **kwargs: ["https://example.com/world/story-1"],
    )
    monkeypatch.setattr(
        runner,
        "_scrape_article",
        lambda *args, **kwargs: (
            SuccessDatasetItem(
                site_name="Example News",
                country="United States",
                region="North America",
                language="en",
                article_title="Story",
                author=None,
                article_body="Body",
                tags=[],
                date_published="2026-03-20T12:00:00Z",
                article_url="https://example.com/world/story-1",
                url_hash=md5_url("https://example.com/world/story-1"),
                main_image_url=None,
                seo_description=None,
                scraped_at="2026-03-20T12:05:00Z",
                scraping_tool=ScrapingTool.SCRAPLING,
                execution_mode=ExecutionMode.CURRENT,
                category_url="https://example.com/world",
                source_html_lang="en",
            ),
            None,
        ),
    )

    summary = runner._scrape_site(site, site_selectors, tracker, input_config, datasets)

    assert len(datasets.success_dataset) == 1
    assert summary["collected_items"] == 1


def test_normalize_actor_input_merges_site_category_filters() -> None:
    config = normalize_actor_input(
        {
            "sites_to_scrape": ["Example News"],
            "site_category_filters": [
                {
                    "site_name": "Example News",
                    "category_urls": [
                        "https://example.com/world",
                        "https://example.com/politics",
                    ],
                }
            ],
            "max_items_per_site": 10,
            "proxy_config": {
                "useApifyProxy": True,
                "apifyProxyGroups": ["RESIDENTIAL"],
            },
        }
    )

    assert config.category_filters == {
        "Example News": [
            "https://example.com/world",
            "https://example.com/politics",
        ]
    }
