"""Run a lightweight scrape health check across configured sites."""
from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import List, Optional, Tuple
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from ..database.models import SiteCategory, SiteConfig
from ..database.session import get_primary_session, get_spider_session
from ..scraping.engine import ScraperEngine


@dataclass
class SiteHealthResult:
    site_id: int
    site_name: str
    site_url: str
    configured_country: Optional[str]
    configured_language: Optional[str]
    detected_domain: Optional[str]
    detected_html_lang: Optional[str]
    detected_server_header: Optional[str]
    metadata_language_status: str
    metadata_country_status: str
    status: str
    listing_url: str
    listing_url_used: Optional[str]
    listing_engine: Optional[str]
    links_found: int
    article_url: Optional[str]
    article_engine: Optional[str]
    title_chars: int
    body_chars: int
    quality_score: int
    quality_notes: Optional[str]
    error: Optional[str]
    duration_seconds: float


COUNTRY_TLD_MAP = {
    "ae": "United Arab Emirates",
    "au": "Australia",
    "br": "Brazil",
    "ca": "Canada",
    "cn": "China",
    "de": "Germany",
    "eg": "Egypt",
    "es": "Spain",
    "fr": "France",
    "id": "Indonesia",
    "in": "India",
    "it": "Italy",
    "jo": "Jordan",
    "jp": "Japan",
    "kw": "Kuwait",
    "lb": "Lebanon",
    "ma": "Morocco",
    "mx": "Mexico",
    "my": "Malaysia",
    "ng": "Nigeria",
    "nz": "New Zealand",
    "om": "Oman",
    "pk": "Pakistan",
    "qa": "Qatar",
    "ru": "Russia",
    "sa": "Saudi Arabia",
    "sg": "Singapore",
    "tr": "Turkey",
    "uk": "United Kingdom",
    "us": "United States",
    "za": "South Africa",
}

SKIP_PATH_TOKENS = (
    "/cdn-cgi/",
    "/privacy",
    "/terms",
    "/policy",
    "/policies",
    "/sitemap",
    "/rss",
    "/feed",
    "/tag/",
    "/tags/",
    "/topic/",
    "/topics/",
    "/author/",
    "/authors/",
    "/subscribe",
    "/login",
    "/register",
    "/account",
    "/about",
    "/contact",
    "/newsletter",
    "/newsletters",
    "/events",
    "/conference",
    "/conferences",
    "/careers",
    "/jobs",
    "/blogs/",
    "/pro/news",
    "/home/page/",
    "/latest/page/",
    "/v2/partners-list",
)

SKIP_PATH_SUFFIXES = (
    ".pdf",
    ".xml",
    ".rss",
    ".atom",
    ".ics",
    ".json",
    ".zip",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
    ".svg",
)


def _listing_url_for_site(spider_session: Session, site: SiteConfig) -> str:
    category = (
        spider_session.query(SiteCategory)
        .filter(
            SiteCategory.site_config_id == site.id,
            SiteCategory.active.is_(True),
        )
        .order_by(SiteCategory.start_page.asc(), SiteCategory.id.asc())
        .first()
    )
    return category.url if category and category.url else site.url


def _fetch_with_probe_chain(
    engine: ScraperEngine,
    url: str,
    allow_selenium: bool,
) -> Tuple[Optional[str], Optional[str]]:
    """Fetch URL with deterministic probe priority."""
    backends = ["scrapling", "pydoll"]
    if allow_selenium:
        backends.append("selenium")

    for backend in backends:
        if backend == "scrapling":
            html = engine._fetch_page_scrapling(url)
        elif backend == "pydoll":
            html = engine._fetch_page_pydoll(url)
        else:
            html = engine._fetch_page_selenium(url)

        if not html:
            continue
        if html.lstrip().startswith("%PDF"):
            continue
        try:
            if engine._detect_content_missing(html):
                continue
        except Exception:
            # Non-HTML/malformed payloads should not terminate the health check.
            pass
        return html, backend

    return None, None


def _is_candidate_article_link(link: str) -> bool:
    parsed = urlparse(link)
    if parsed.scheme not in {"http", "https"}:
        return False

    path = (parsed.path or "").lower()
    query = (parsed.query or "").lower()
    if not path or path in {"/", ""}:
        return False
    if any(path.endswith(suffix) for suffix in SKIP_PATH_SUFFIXES):
        return False
    if any(token in path for token in SKIP_PATH_TOKENS):
        return False
    if "sessionid=" in query:
        return False
    if re.search(r"/page/\d+/?$", path):
        return False
    return True


def _extract_html_lang(html: Optional[str]) -> Optional[str]:
    if not html:
        return None
    match = re.search(r"<html[^>]+lang=['\"]?([a-zA-Z-]{2,10})", html, flags=re.IGNORECASE)
    return match.group(1).strip() if match else None


def _normalize_lang(language: Optional[str]) -> Optional[str]:
    if not language:
        return None
    value = language.strip().replace("_", "-")
    if not value:
        return None
    return value.split("-")[0].lower()


def _country_signal_from_domain(domain: str) -> Optional[str]:
    host = (domain or "").lower().replace("www.", "").strip(".")
    if not host or "." not in host:
        return None

    if host.endswith(".co.uk") or host.endswith(".gov.uk") or host.endswith(".ac.uk"):
        return "United Kingdom"

    suffix = host.split(".")[-1]
    return COUNTRY_TLD_MAP.get(suffix)


def _language_status(configured: Optional[str], detected: Optional[str]) -> str:
    configured_norm = _normalize_lang(configured)
    detected_norm = _normalize_lang(detected)
    if not configured_norm:
        return "missing_config"
    if not detected_norm:
        return "unknown"
    return "match" if configured_norm == detected_norm else "mismatch"


def _country_status(configured: Optional[str], domain_signal: Optional[str]) -> str:
    configured_norm = (configured or "").strip().lower()
    signal_norm = (domain_signal or "").strip().lower()
    if not configured_norm:
        return "missing_config"
    if not signal_norm:
        return "unknown"
    return "match" if configured_norm == signal_norm else "mismatch"


def _quality_score(article_data: dict, min_body_chars: int) -> Tuple[int, str]:
    title = (article_data.get("title") or "").strip()
    body = (article_data.get("body") or "").strip()
    body_words = re.findall(r"[A-Za-z]{2,}", body)
    unique_words = set(word.lower() for word in body_words)
    lexical_diversity = (len(unique_words) / len(body_words)) if body_words else 0.0

    score = 0
    notes: List[str] = []
    if len(title) >= 20:
        score += 20
    else:
        notes.append("short_title")

    if len(body) >= min_body_chars:
        score += 25
    else:
        notes.append("short_body")

    if len(body) >= 800:
        score += 20

    if lexical_diversity >= 0.35 and len(body_words) >= 120:
        score += 15
    else:
        notes.append("low_diversity")

    if article_data.get("date_publish"):
        score += 10
    else:
        notes.append("missing_publish_date")

    has_links = bool(article_data.get("extra_links"))
    has_images = bool(article_data.get("image_links") or article_data.get("image_url"))
    if has_links or has_images:
        score += 10
    else:
        notes.append("sparse_media_links")

    return min(score, 100), ",".join(notes) if notes else "ok"


def _rank_article_candidates(links: List[str]) -> List[str]:
    """Prioritize likely article URLs over navigation/utility links."""

    def score(link: str) -> tuple[int, int]:
        parsed = urlparse(link)
        path = (parsed.path or "").lower()
        query = (parsed.query or "").lower()

        value = 0
        if re.search(r"/20\\d{2}/\\d{1,2}/\\d{1,2}/", path) or re.search(r"/\\d{7,}", path):
            value += 5
        if any(token in path for token in ("/article", "/story", "/news/", "/politics/", "/business/", "/technology/")):
            value += 3
        if path.count("/") >= 3:
            value += 1

        if any(
            token in path
            for token in (
                "/video",
                "/live",
                "/podcast",
                "/gallery",
                "/photo",
                "/topic/",
                "/topics/",
                "/tag/",
                "/tags/",
                "/section/",
                "/category/",
                "/search",
                "/subscribe",
                "/login",
                "/register",
                "/account",
                "/about",
                "/contact",
                "/newsletter",
                "/newsletters",
                "/privacy",
                "/terms",
                "/policy",
                "/policies",
                "/sitemap",
                "/rss",
                "/feed",
                "/tag/",
                "/tags/",
                "/topic/",
                "/topics/",
                "/author/",
                "/authors/",
                "/events",
                "/conference",
                "/conferences",
                "/careers",
                "/jobs",
                "/blogs/",
                "/pro/news",
                "/home/page/",
                "/latest/page/",
                "/v2/partners-list",
                "/cdn-cgi/",
            )
        ):
            value -= 4
        if "utm_" in query or "ref=" in query:
            value -= 1

        return value, len(path)

    return sorted(links, key=lambda link: score(link), reverse=True)


def run_health_check(
    limit: Optional[int] = None,
    offset: int = 0,
    max_article_attempts: int = 5,
    min_body_chars: int = 200,
    timeout: int = 20,
    max_retries: int = 1,
    allow_selenium: bool = False,
) -> dict:
    primary_session = next(get_primary_session())
    spider_session = next(get_spider_session())

    try:
        query = (
            primary_session.query(SiteConfig)
            .filter(SiteConfig.active.is_(True))
            .order_by(SiteConfig.id.asc())
        )
        if offset:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)

        sites = query.all()
        results: List[SiteHealthResult] = []

        with ScraperEngine(
            timeout=timeout,
            max_retries=max_retries,
            enable_rate_limiting=False,
        ) as engine:
            for site in sites:
                started = perf_counter()
                listing_url = _listing_url_for_site(spider_session, site)
                listing_html, listing_engine, listing_url_used = engine._fetch_listing_page_for_site(
                    site,
                    listing_url,
                )
                detected_domain = (urlparse(listing_url).netloc or "").lower().replace("www.", "") or None
                detected_server_header = None
                try:
                    response = httpx.get(
                        listing_url,
                        timeout=timeout,
                        follow_redirects=True,
                        headers={"User-Agent": engine.user_agent},
                    )
                    response.raise_for_status()
                    detected_domain = (response.url.host or detected_domain or "").lower().replace("www.", "") or None
                    detected_server_header = response.headers.get("server")
                except Exception:
                    pass
                detected_html_lang = _extract_html_lang(listing_html)
                language_status = _language_status(site.language, detected_html_lang)
                country_status = _country_status(site.country or site.location, _country_signal_from_domain(detected_domain or ""))

                status = "fail"
                links_found = 0
                article_url: Optional[str] = None
                article_engine: Optional[str] = None
                title_chars = 0
                body_chars = 0
                quality_score = 0
                quality_notes: Optional[str] = None
                error: Optional[str] = None

                if not listing_html:
                    error = "listing_fetch_failed"
                else:
                    try:
                        links = engine._parse_links_from_page(listing_html, listing_url_used or listing_url)
                    except Exception:
                        links = []
                    links_found = len(links)
                    if links_found == 0:
                        status = "partial"
                        error = "no_article_links_detected"
                    else:
                        filtered_links = [link for link in links if _is_candidate_article_link(link)]
                        ranked_links = _rank_article_candidates(filtered_links)
                        for link in ranked_links[:max_article_attempts]:
                            article_html, used_engine = _fetch_with_probe_chain(
                                engine,
                                link,
                                allow_selenium=allow_selenium,
                            )
                            if not article_html:
                                continue

                            try:
                                article_data = engine._extract_article(link, article_html)
                            except Exception:
                                continue
                            if not article_data:
                                continue

                            title = (article_data.get("title") or "").strip()
                            body = (article_data.get("body") or "").strip()
                            if not title or len(body) < min_body_chars:
                                continue
                            quality_score, quality_notes = _quality_score(article_data, min_body_chars=min_body_chars)
                            if quality_score < 55:
                                continue

                            article_url = link
                            article_engine = used_engine
                            title_chars = len(title)
                            body_chars = len(body)
                            status = "pass"
                            error = None
                            break

                        if status != "pass":
                            status = "partial"
                            error = "article_extraction_not_verified"

                elapsed = round(perf_counter() - started, 3)
                results.append(
                    SiteHealthResult(
                        site_id=site.id,
                        site_name=site.name,
                        site_url=site.url,
                        configured_country=site.country or site.location,
                        configured_language=site.language,
                        detected_domain=detected_domain,
                        detected_html_lang=detected_html_lang,
                        detected_server_header=detected_server_header,
                        metadata_language_status=language_status,
                        metadata_country_status=country_status,
                        status=status,
                        listing_url=listing_url,
                        listing_url_used=listing_url_used or listing_url,
                        listing_engine=listing_engine,
                        links_found=links_found,
                        article_url=article_url,
                        article_engine=article_engine,
                        title_chars=title_chars,
                        body_chars=body_chars,
                        quality_score=quality_score,
                        quality_notes=quality_notes,
                        error=error,
                        duration_seconds=elapsed,
                    )
                )

        summary = {
            "total_sites": len(results),
            "pass_sites": sum(1 for r in results if r.status == "pass"),
            "partial_sites": sum(1 for r in results if r.status == "partial"),
            "fail_sites": sum(1 for r in results if r.status == "fail"),
            "language_mismatch_sites": sum(1 for r in results if r.metadata_language_status == "mismatch"),
            "country_mismatch_sites": sum(1 for r in results if r.metadata_country_status == "mismatch"),
            "avg_quality_score": round(
                sum(r.quality_score for r in results) / len(results), 2
            ) if results else 0.0,
        }
        return {
            "generated_at": datetime.now().isoformat(),
            "settings": {
                "limit": limit,
                "offset": offset,
                "max_article_attempts": max_article_attempts,
                "min_body_chars": min_body_chars,
                "timeout": timeout,
                "max_retries": max_retries,
                "allow_selenium": allow_selenium,
            },
            "summary": summary,
            "results": [asdict(r) for r in results],
        }
    finally:
        spider_session.close()
        primary_session.close()


def _write_csv(results: List[dict], output_path: Path) -> None:
    fieldnames = list(SiteHealthResult.__annotations__.keys())
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in results:
            writer.writerow({name: row.get(name) for name in fieldnames})


def main() -> int:
    parser = argparse.ArgumentParser(description="Run scrape health checks for configured sites.")
    parser.add_argument("--limit", type=int, default=None, help="Limit active sites to check")
    parser.add_argument("--offset", type=int, default=0, help="Offset into active site list")
    parser.add_argument("--max-article-attempts", type=int, default=5, help="Max article links to probe per site")
    parser.add_argument("--min-body-chars", type=int, default=200, help="Minimum body chars for pass")
    parser.add_argument("--timeout", type=int, default=20, help="Fetch timeout seconds")
    parser.add_argument("--max-retries", type=int, default=1, help="Max retries per request")
    parser.add_argument(
        "--allow-selenium",
        action="store_true",
        help="Include Selenium fallback in probe chain (slower)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output JSON path (default: data/reports/site_health_<timestamp>.json)",
    )
    args = parser.parse_args()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    default_json = Path(f"data/reports/site_health_{ts}.json")
    output_json = Path(args.output) if args.output else default_json
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_csv = output_json.with_suffix(".csv")

    payload = run_health_check(
        limit=args.limit,
        offset=args.offset,
        max_article_attempts=args.max_article_attempts,
        min_body_chars=args.min_body_chars,
        timeout=args.timeout,
        max_retries=args.max_retries,
        allow_selenium=args.allow_selenium,
    )

    output_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_csv(payload["results"], output_csv)

    summary = payload["summary"]
    print("Site health check complete.")
    print(f"  Total:   {summary['total_sites']}")
    print(f"  Pass:    {summary['pass_sites']}")
    print(f"  Partial: {summary['partial_sites']}")
    print(f"  Fail:    {summary['fail_sites']}")
    print(f"  JSON:    {output_json}")
    print(f"  CSV:     {output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
