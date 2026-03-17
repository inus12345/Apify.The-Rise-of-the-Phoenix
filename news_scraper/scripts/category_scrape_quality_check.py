"""Run a per-category scrape quality audit across active sites/categories."""
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from ..database.models import SiteCategory, SiteConfig
from ..database.session import get_primary_session, get_spider_session
from ..scraping.engine import ScraperEngine
from .site_scrape_health_check import (
    _country_signal_from_domain,
    _country_status,
    _extract_html_lang,
    _is_candidate_article_link,
    _language_status,
    _quality_score,
    _rank_article_candidates,
)


@dataclass
class CategoryQualityResult:
    site_id: int
    site_name: str
    site_url: str
    site_country: Optional[str]
    site_language: Optional[str]
    category_id: int
    category_name: Optional[str]
    category_url: str
    status: str
    metadata_language_status: str
    metadata_country_status: str
    listing_url_used: Optional[str]
    listing_engine: Optional[str]
    links_found: int
    candidate_links_found: int
    article_url: Optional[str]
    article_engine: Optional[str]
    title_chars: int
    body_chars: int
    quality_score: int
    quality_notes: Optional[str]
    error: Optional[str]
    duration_seconds: float


def _write_csv(results: List[dict], output_path: Path) -> None:
    fieldnames = list(CategoryQualityResult.__annotations__.keys())
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in results:
            writer.writerow({name: row.get(name) for name in fieldnames})


def _load_active_sites(primary_session: Session) -> Dict[int, SiteConfig]:
    sites = (
        primary_session.query(SiteConfig)
        .filter(SiteConfig.active.is_(True))
        .order_by(SiteConfig.id.asc())
        .all()
    )
    return {site.id: site for site in sites}


def _fetch_for_audit(
    engine: ScraperEngine,
    url: str,
    *,
    probe_mode: str,
    allow_selenium: bool,
) -> tuple[Optional[str], Optional[str]]:
    mode = (probe_mode or "http").strip().lower()
    if mode == "scraper-chain":
        backends = ["scrapling", "pydoll"]
    elif mode == "hybrid":
        backends = ["beautifulsoup", "scrapling", "pydoll"]
    else:
        backends = ["beautifulsoup"]

    if allow_selenium:
        backends.append("selenium")

    for backend in backends:
        if backend == "beautifulsoup":
            html = engine._fetch_page_beautifulsoup(url)
        elif backend == "scrapling":
            html = engine._fetch_page_scrapling(url)
        elif backend == "pydoll":
            html = engine._fetch_page_pydoll(url)
        else:
            html = engine._fetch_page_selenium(url)

        if not html:
            continue
        try:
            if engine._detect_content_missing(html):
                continue
        except Exception:
            pass
        return html, backend

    return None, None


def run_category_quality_check(
    *,
    site_limit: Optional[int] = None,
    site_offset: int = 0,
    max_article_attempts: int = 3,
    min_body_chars: int = 220,
    min_quality_score: int = 55,
    timeout: int = 8,
    max_retries: int = 0,
    allow_selenium: bool = False,
    probe_mode: str = "http",
) -> dict:
    primary_session = next(get_primary_session())
    spider_session = next(get_spider_session())

    try:
        sites_by_id = _load_active_sites(primary_session)
        site_ids = sorted(sites_by_id.keys())
        if site_offset:
            site_ids = site_ids[site_offset:]
        if site_limit is not None:
            site_ids = site_ids[: max(int(site_limit), 0)]
        selected_site_ids = set(site_ids)

        categories_query = (
            spider_session.query(SiteCategory)
            .filter(SiteCategory.active.is_(True))
            .order_by(SiteCategory.site_config_id.asc(), SiteCategory.id.asc())
        )
        categories = [
            category
            for category in categories_query.all()
            if category.site_config_id in selected_site_ids
        ]

        results: List[CategoryQualityResult] = []
        with ScraperEngine(
            timeout=timeout,
            max_retries=max_retries,
            enable_rate_limiting=False,
        ) as engine:
            for index, category in enumerate(categories, start=1):
                started = perf_counter()
                site = sites_by_id.get(category.site_config_id)
                if site is None:
                    results.append(
                        CategoryQualityResult(
                            site_id=category.site_config_id,
                            site_name="UNKNOWN_SITE",
                            site_url="",
                            site_country=None,
                            site_language=None,
                            category_id=category.id,
                            category_name=category.name,
                            category_url=category.url or "",
                            status="fail",
                            metadata_language_status="unknown",
                            metadata_country_status="unknown",
                            listing_url_used=category.url or "",
                            listing_engine=None,
                            links_found=0,
                            candidate_links_found=0,
                            article_url=None,
                            article_engine=None,
                            title_chars=0,
                            body_chars=0,
                            quality_score=0,
                            quality_notes=None,
                            error="site_not_found",
                            duration_seconds=round(perf_counter() - started, 3),
                        )
                    )
                    continue

                category_url = (category.url or "").strip() or site.url
                listing_html, listing_engine, listing_url_used = engine._fetch_listing_page_for_site(
                    site,
                    category_url,
                )

                detected_domain = (site.domain or "").lower().replace("www.", "") if site.domain else ""
                detected_html_lang = _extract_html_lang(listing_html)
                language_status = _language_status(site.language, detected_html_lang)
                country_status = _country_status(site.country or site.location, _country_signal_from_domain(detected_domain))

                status = "fail"
                links_found = 0
                candidate_links_found = 0
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
                        links = engine._parse_links_from_page(listing_html, listing_url_used or category_url)
                    except Exception:
                        links = []
                    links_found = len(links)
                    filtered_links = [link for link in links if _is_candidate_article_link(link)]
                    candidate_links_found = len(filtered_links)

                    if candidate_links_found == 0:
                        status = "partial"
                        error = "no_candidate_article_links"
                    else:
                        ranked_links = _rank_article_candidates(filtered_links)
                        for link in ranked_links[: max(int(max_article_attempts), 1)]:
                            article_html, used_engine = _fetch_for_audit(
                                engine,
                                link,
                                probe_mode=probe_mode,
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
                            quality_score, quality_notes = _quality_score(
                                article_data,
                                min_body_chars=min_body_chars,
                            )
                            if quality_score < min_quality_score:
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

                results.append(
                    CategoryQualityResult(
                        site_id=site.id,
                        site_name=site.name,
                        site_url=site.url,
                        site_country=site.country or site.location,
                        site_language=site.language,
                        category_id=category.id,
                        category_name=category.name,
                        category_url=category_url,
                        status=status,
                        metadata_language_status=language_status,
                        metadata_country_status=country_status,
                        listing_url_used=listing_url_used or category_url,
                        listing_engine=listing_engine,
                        links_found=links_found,
                        candidate_links_found=candidate_links_found,
                        article_url=article_url,
                        article_engine=article_engine,
                        title_chars=title_chars,
                        body_chars=body_chars,
                        quality_score=quality_score,
                        quality_notes=quality_notes,
                        error=error,
                        duration_seconds=round(perf_counter() - started, 3),
                    )
                )

                if index % 100 == 0:
                    print(f"Processed {index}/{len(categories)} categories...")

        summary = {
            "total_categories": len(results),
            "pass_categories": sum(1 for r in results if r.status == "pass"),
            "partial_categories": sum(1 for r in results if r.status == "partial"),
            "fail_categories": sum(1 for r in results if r.status == "fail"),
            "language_mismatch_categories": sum(
                1 for r in results if r.metadata_language_status == "mismatch"
            ),
            "country_mismatch_categories": sum(
                1 for r in results if r.metadata_country_status == "mismatch"
            ),
            "avg_quality_score": round(
                sum(r.quality_score for r in results) / len(results), 2
            )
            if results
            else 0.0,
            "categories_with_rubbish_risk": sum(
                1
                for r in results
                if r.status != "pass" or (r.quality_score and r.quality_score < min_quality_score)
            ),
        }
        return {
            "generated_at": datetime.now().isoformat(),
            "settings": {
                "site_limit": site_limit,
                "site_offset": site_offset,
                "max_article_attempts": max_article_attempts,
                "min_body_chars": min_body_chars,
                "min_quality_score": min_quality_score,
                "timeout": timeout,
                "max_retries": max_retries,
                "allow_selenium": allow_selenium,
                "probe_mode": probe_mode,
            },
            "summary": summary,
            "results": [asdict(r) for r in results],
        }
    finally:
        spider_session.close()
        primary_session.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run scrape quality checks for every active category.")
    parser.add_argument("--site-limit", type=int, default=None, help="Limit active sites")
    parser.add_argument("--site-offset", type=int, default=0, help="Offset active sites")
    parser.add_argument("--max-article-attempts", type=int, default=3, help="Max article links per category")
    parser.add_argument("--min-body-chars", type=int, default=220, help="Minimum body chars for pass")
    parser.add_argument("--min-quality-score", type=int, default=55, help="Minimum quality score for pass")
    parser.add_argument("--timeout", type=int, default=8, help="Fetch timeout seconds")
    parser.add_argument("--max-retries", type=int, default=0, help="Retries per request")
    parser.add_argument(
        "--allow-selenium",
        action="store_true",
        help="Allow Selenium fallback in probe chain (slower)",
    )
    parser.add_argument(
        "--probe-mode",
        type=str,
        default="http",
        choices=["http", "hybrid", "scraper-chain"],
        help="Probe backend mode: http (fast), hybrid, or scraper-chain",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output JSON path (default: data/reports/category_quality_<timestamp>.json)",
    )
    args = parser.parse_args()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    default_json = Path(f"data/reports/category_quality_{ts}.json")
    output_json = Path(args.output) if args.output else default_json
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_csv = output_json.with_suffix(".csv")

    payload = run_category_quality_check(
        site_limit=args.site_limit,
        site_offset=args.site_offset,
        max_article_attempts=args.max_article_attempts,
        min_body_chars=args.min_body_chars,
        min_quality_score=args.min_quality_score,
        timeout=args.timeout,
        max_retries=args.max_retries,
        allow_selenium=args.allow_selenium,
        probe_mode=args.probe_mode,
    )

    output_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_csv(payload["results"], output_csv)

    summary = payload["summary"]
    print("Category quality check complete.")
    print(f"  Total:   {summary['total_categories']}")
    print(f"  Pass:    {summary['pass_categories']}")
    print(f"  Partial: {summary['partial_categories']}")
    print(f"  Fail:    {summary['fail_categories']}")
    print(f"  JSON:    {output_json}")
    print(f"  CSV:     {output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
