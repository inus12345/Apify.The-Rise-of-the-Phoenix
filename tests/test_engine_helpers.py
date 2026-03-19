"""Focused tests for scraping helper behavior."""

from news_scraper.config import ScrapingHistoryEntry, ScrapingTool, utc_now
from news_scraper.scraping.engine import build_page_url, choose_preferred_tool, order_tools


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
