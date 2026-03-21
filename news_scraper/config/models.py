"""Typed configuration and output models for the scraper."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


class ScrapingTool(str, Enum):
    """Supported scraping backends in strict fallback order."""

    SCRAPLING = "scrapling"
    PYDOLL = "pydoll"
    SELENIUM = "selenium"


class ExecutionMode(str, Enum):
    """Supported run modes."""

    CURRENT = "current"
    HISTORIC = "historic"


class SelectorType(str, Enum):
    """Selector strategies supported by the generic extractor."""

    CSS = "css"
    XPATH = "xpath"
    META = "meta"
    JSON_LD = "json_ld"


class SelectorStrategy(BaseModel):
    """Single extraction strategy for a field."""

    model_config = ConfigDict(extra="forbid")

    type: SelectorType
    value: str = Field(min_length=1)
    attribute: str | None = None
    multiple: bool = False


class FieldRule(BaseModel):
    """Extraction rules for a simple field."""

    model_config = ConfigDict(extra="forbid")

    selectors: list[SelectorStrategy] = Field(min_length=1)
    required: bool = True
    postprocess: list[
        Literal[
            "strip",
            "normalize_whitespace",
            "html_to_text",
            "join_paragraphs",
            "dedupe_list",
            "trim_trailing_slash",
        ]
    ] = Field(default_factory=lambda: ["strip", "normalize_whitespace"])
    default: str | list[str] | None = None


class DateFieldRule(BaseModel):
    """Extraction rules for published dates."""

    model_config = ConfigDict(extra="forbid")

    selectors: list[SelectorStrategy] = Field(min_length=1)
    required: bool = True
    input_formats: list[str] = Field(default_factory=list)
    timezone: str | None = None
    output_format: Literal["iso8601"] = "iso8601"
    postprocess: list[
        Literal[
            "strip",
            "normalize_whitespace",
            "html_to_text",
            "join_paragraphs",
            "dedupe_list",
            "trim_trailing_slash",
        ]
    ] = Field(default_factory=lambda: ["strip", "normalize_whitespace"])
    default: str | None = None


class UrlFieldRule(BaseModel):
    """Extraction rules for URLs."""

    model_config = ConfigDict(extra="forbid")

    selectors: list[SelectorStrategy] = Field(min_length=1)
    required: bool = True
    normalize_to_canonical: bool = True
    postprocess: list[
        Literal[
            "strip",
            "normalize_whitespace",
            "html_to_text",
            "join_paragraphs",
            "dedupe_list",
            "trim_trailing_slash",
        ]
    ] = Field(default_factory=lambda: ["strip", "normalize_whitespace", "trim_trailing_slash"])
    default: str | None = None


class HashFieldRule(BaseModel):
    """Computed hash field configuration."""

    model_config = ConfigDict(extra="forbid")

    source_field: Literal["article_url"] = "article_url"
    algorithm: Literal["md5"] = "md5"


class SiteFieldRules(BaseModel):
    """Expected article field rules for a site."""

    model_config = ConfigDict(extra="forbid")

    article_title: FieldRule
    author: FieldRule
    article_body: FieldRule
    tags: FieldRule
    date_published: DateFieldRule
    article_url: UrlFieldRule
    url_hash: HashFieldRule = Field(default_factory=HashFieldRule)
    main_image_url: UrlFieldRule
    seo_description: FieldRule


class SiteSelectorConfig(BaseModel):
    """Per-site selector definition."""

    model_config = ConfigDict(extra="forbid")

    site_name: str = Field(min_length=1)
    article_link_selectors: list[SelectorStrategy] = Field(min_length=1)
    canonical_url_selector: SelectorStrategy | None = None
    fields: SiteFieldRules


class SelectorMap(BaseModel):
    """Registry of per-site selector configuration."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0.0"
    sites: list[SiteSelectorConfig] = Field(min_length=1)


class ScrapingHistoryEntry(BaseModel):
    """Historical success telemetry for a site/backend pair."""

    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    tool: ScrapingTool
    success: bool
    success_rate: float = Field(ge=0.0, le=1.0)
    sample_size: int = Field(ge=0)
    avg_response_time_ms: int | None = Field(default=None, ge=0)
    block_detected: bool = False
    error_type: str | None = None


class SiteCatalogEntry(BaseModel):
    """Catalog entry describing a target website."""

    model_config = ConfigDict(extra="forbid")

    site_name: str = Field(min_length=1)
    base_url: HttpUrl
    country: str = Field(min_length=2)
    region: str = Field(min_length=1)
    language: str = Field(min_length=2)
    underlying_tech: str = Field(min_length=1)
    active: bool = True
    preferred_scraping_tool: ScrapingTool = ScrapingTool.SCRAPLING
    scraping_history: list[ScrapingHistoryEntry] = Field(default_factory=list)
    notes: str | None = None
    last_verified_at: datetime | None = None


class SiteCatalog(BaseModel):
    """Central site registry."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0.0"
    sites: list[SiteCatalogEntry] = Field(min_length=1)


class CategoryState(BaseModel):
    """Pagination state for a single category."""

    model_config = ConfigDict(extra="forbid")

    category_name: str = Field(min_length=1)
    category_url: HttpUrl
    total_known_pages: int = Field(default=1, ge=1)
    last_scraped_page_index: int = Field(default=0, ge=0)


class SiteCategoryTracker(BaseModel):
    """Tracked categories for a single site."""

    model_config = ConfigDict(extra="forbid")

    site_name: str = Field(min_length=1)
    categories: list[CategoryState] = Field(default_factory=list)


class CategoryPaginationTracker(BaseModel):
    """Global pagination state."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0.0"
    sites: list[SiteCategoryTracker] = Field(default_factory=list)


class ProxyConfig(BaseModel):
    """Apify-style proxy configuration."""

    model_config = ConfigDict(extra="forbid")

    useApifyProxy: bool = False
    apifyProxyGroups: list[str] = Field(default_factory=list)
    countryCode: str | None = None
    proxyUrls: list[str] = Field(default_factory=list)


class InputConfig(BaseModel):
    """Runtime input contract compatible with INPUT.json."""

    model_config = ConfigDict(extra="forbid")

    sites_to_scrape: list[str] = Field(default_factory=list)
    category_filters: dict[str, list[str]] = Field(default_factory=dict)
    max_items_per_site: int = Field(default=50, ge=1)
    historic_cutoff_date: datetime | None = None
    proxy_config: ProxyConfig = Field(default_factory=ProxyConfig)

    @property
    def execution_mode(self) -> ExecutionMode:
        return ExecutionMode.HISTORIC if self.historic_cutoff_date else ExecutionMode.CURRENT


class SuccessDatasetItem(BaseModel):
    """Normalized successful extraction payload."""

    model_config = ConfigDict(extra="forbid")

    site_name: str = Field(min_length=1)
    country: str = Field(min_length=2)
    region: str = Field(min_length=1)
    language: str = Field(min_length=2)
    article_title: str = Field(min_length=1)
    author: str | None = None
    article_body: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    date_published: datetime
    article_url: HttpUrl
    url_hash: str = Field(pattern=r"^[a-fA-F0-9]{32}$")
    main_image_url: HttpUrl | None = None
    seo_description: str | None = None
    scraped_at: datetime
    scraping_tool: ScrapingTool
    execution_mode: ExecutionMode
    category_url: HttpUrl | None = None
    source_html_lang: str | None = None

    @field_validator("article_url", "main_image_url", "category_url", mode="before")
    @classmethod
    def _normalize_http_urls(cls, value: Any) -> Any:
        if isinstance(value, str):
            return normalize_url(value)
        return value

    @field_validator("url_hash", mode="before")
    @classmethod
    def _strip_hash(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.lower()
        return value

    @model_validator(mode="after")
    def _normalize_success_datetimes(self) -> "SuccessDatasetItem":
        self.date_published = ensure_utc(self.date_published)
        self.scraped_at = ensure_utc(self.scraped_at)
        return self


class ErrorDatasetItem(BaseModel):
    """Telemetry row for a failed scrape."""

    model_config = ConfigDict(extra="forbid")

    logged_at: datetime
    site_name: str = Field(min_length=1)
    failed_url: str = Field(min_length=1)
    url_hash: str = Field(pattern=r"^[a-fA-F0-9]{32}$")
    error_type: str = Field(min_length=1)
    error_message: str = Field(min_length=1)
    fallback_tool_failed: ScrapingTool | None = None
    execution_mode: ExecutionMode

    @field_validator("url_hash", mode="before")
    @classmethod
    def _strip_hash(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.lower()
        return value

    @model_validator(mode="after")
    def _normalize_error_datetime(self) -> "ErrorDatasetItem":
        self.logged_at = ensure_utc(self.logged_at)
        return self


class SiteVerificationResult(BaseModel):
    """Verification outcome for one site."""

    model_config = ConfigDict(extra="forbid")

    site_name: str
    fetched_url: str
    success: bool
    tool_used: ScrapingTool | None = None
    issues: list[str] = Field(default_factory=list)
    verified_at: datetime


class VerificationReport(BaseModel):
    """Verification report for all sites."""

    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    results: list[SiteVerificationResult] = Field(default_factory=list)


class RunDatasets(BaseModel):
    """Top-level run output for local execution."""

    model_config = ConfigDict(extra="forbid")

    success_dataset: list[SuccessDatasetItem] = Field(default_factory=list)
    error_log_dataset: list[ErrorDatasetItem] = Field(default_factory=list)


def normalize_url(url: str) -> str:
    """Normalize a URL for deduplication and canonical output."""

    parts = urlsplit(url.strip())
    path = parts.path or "/"
    normalized = urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            path.rstrip("/") or "/",
            parts.query,
            "",
        )
    )
    return normalized


def md5_url(url: str) -> str:
    """Create the canonical MD5 URL hash."""

    return hashlib.md5(normalize_url(url).encode("utf-8")).hexdigest()


def utc_now() -> datetime:
    """Return timezone-aware UTC timestamp."""

    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Normalize a datetime to UTC."""

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
