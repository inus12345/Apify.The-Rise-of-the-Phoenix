"""Focused tests for config and output models."""

from datetime import UTC, datetime

from news_scraper.config import InputConfig, SuccessDatasetItem, md5_url, normalize_url


def test_input_config_uses_historic_mode_when_cutoff_present() -> None:
    config = InputConfig.model_validate(
        {
            "sites_to_scrape": ["example-news.com"],
            "max_items_per_site": 10,
            "historic_cutoff_date": "2025-01-01T00:00:00Z",
            "proxy_config": {
                "useApifyProxy": True,
                "apifyProxyGroups": ["RESIDENTIAL"],
                "countryCode": "US",
            },
        }
    )

    assert config.execution_mode.value == "historic"


def test_success_item_normalizes_urls_and_datetimes() -> None:
    item = SuccessDatasetItem(
        site_name="example-news.com",
        country="United States",
        region="North America",
        language="en",
        article_title="Title",
        author="Author",
        article_body="Body",
        tags=["tag"],
        date_published="2025-01-01T12:00:00+02:00",
        article_url="HTTPS://Example.com/path/",
        url_hash=md5_url("https://example.com/path/"),
        main_image_url="https://example.com/image.jpg/",
        seo_description="Description",
        scraped_at="2025-01-01T10:00:00Z",
        scraping_tool="scrapling",
        execution_mode="current",
        category_url="https://example.com/world/",
        source_html_lang="en",
    )

    assert str(item.article_url) == "https://example.com/path"
    assert str(item.main_image_url) == "https://example.com/image.jpg"
    assert str(item.category_url) == "https://example.com/world"
    assert item.date_published == datetime(2025, 1, 1, 10, 0, tzinfo=UTC)


def test_normalize_url_removes_fragment_and_lowercases_host() -> None:
    assert normalize_url("HTTPS://Example.com/news/story/?a=1#fragment") == "https://example.com/news/story?a=1"
