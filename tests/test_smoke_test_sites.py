"""Focused tests for the smoke-test reporting helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


def load_smoke_test_module():
    module_path = Path("scripts/smoke_test_sites.py")
    spec = importlib.util.spec_from_file_location("smoke_test_sites", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_report_summarizes_statuses() -> None:
    smoke_test_sites = load_smoke_test_module()

    report = smoke_test_sites.build_report(
        [
            {
                "site_name": "Alpha",
                "active": True,
                "homepage": {"status": "ok"},
                "categories": [{"status": "ok"}],
            },
            {
                "site_name": "Bravo",
                "active": True,
                "homepage": {"status": "error"},
                "categories": [{"status": "ok"}, {"status": "error"}],
            },
            {
                "site_name": "Charlie",
                "active": False,
                "homepage": {"status": "error"},
                "categories": [],
            },
        ]
    )

    assert report["site_count"] == 3
    assert report["summary"] == {
        "all_green_sites": 1,
        "needs_attention_sites": 1,
        "inactive_sites": 1,
        "active_sites": 2,
    }
    assert [item["overall_status"] for item in report["results"]] == ["ok", "needs_attention", "inactive"]


def test_inspect_listing_requires_requested_article_count() -> None:
    smoke_test_sites = load_smoke_test_module()

    class FakeEngine:
        def __init__(self) -> None:
            self.article_fetches = 0

        def fetch_with_fallback(self, url, preferred_tool=None):
            self.article_fetches += int("story-" in url)
            return SimpleNamespace(tool=SimpleNamespace(value="scrapling"), html="<html></html>")

        def extract_listing_links(self, html, base_url, selectors):
            return [
                "https://example.com/story-1",
                "https://example.com/story-2",
            ]

        def extract_article(self, html, url, selectors):
            if url.endswith("story-2"):
                raise RuntimeError("selector missing")
            return {
                "article_title": "Story",
                "article_body": "Body",
                "date_published": "2026-03-21T00:00:00Z",
            }

    result = smoke_test_sites.inspect_listing(
        FakeEngine(),
        "https://example.com",
        "https://example.com",
        None,
        None,
        2,
    )

    assert result["status"] == "error"
    assert result["articles_attempted"] == 2
    assert result["articles_succeeded"] == 1
    assert "Only 1 of 2 sample articles" in result["error"]
