"""CLI commands for the news scraper platform."""
import click
from tabulate import tabulate
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, urlunparse
import importlib
import re

from sqlalchemy import func

from ..database.session import get_session, get_spider_session
from ..database.models import ArticleUrlLedger, CategoryCrawlState, SiteCategory, SiteConfig
from ..assessment.line_review import (
    apply_line_updates,
    create_line_assessment_run,
    export_assessment_payload,
)
from ..scraping.config_registry import SiteConfigRegistry, get_default_sites
from ..scraping.engine import ScraperEngine
from ..scraping.spider_planner import ensure_default_spider_diagram
from ..pipelines.config_driven import run_config_scrape, sync_sites_from_config
from ..config_templates.templates import (
    SITE_TEMPLATES,
    create_site_config_from_template,
)


def _quick_rank_links(links: list[str]) -> list[str]:
    """Rank likely article links above navigation links for quick scraping."""

    def score(link: str) -> tuple[int, int]:
        parsed = urlparse(link)
        path = (parsed.path or "").lower()
        query = (parsed.query or "").lower()
        value = 0

        if re.search(r"/20\d{2}/\d{1,2}/\d{1,2}/", path) or re.search(r"/\d{7,}", path):
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
            )
        ):
            value -= 4
        if "utm_" in query or "ref=" in query:
            value -= 1

        return value, len(path)

    return sorted(links, key=lambda link: score(link), reverse=True)


def _to_jsonable(value):
    """Recursively convert values into JSON-safe primitives."""
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_jsonable(v) for v in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


@click.group()
@click.version_option(version="0.1.0", prog_name="news-scraper")
def cli():
    """The Rise of the Phoenix - News & Blog Scraping Platform
    
    A modular web scraping platform with clean architecture.
    
    Examples:
      news-scraper init           # Initialize the database
      news-scraper add-site --url https://example.com --name "Example Site"
      news-scraper list-sites     # List all configured sites
      news-scraper scrape-site https://example.com
      news-scraper scrape-all     # Scrape all configured sites
      news-scraper validate-all   # Validate all sites
    """
    pass


@cli.command()
def init():
    """Initialize the database and create tables."""
    click.echo("Initializing database...")
    
    try:
        from ..database.session import init_db as _init_db
        from ..database.session import _primary_db_url, _spider_db_url
        _init_db()
        click.echo(click.style("Database initialized successfully!", fg="green"))
        click.echo(f"Primary DB: {_primary_db_url()}")
        click.echo(f"Spider DB:  {_spider_db_url()}")
    except Exception as e:
        click.echo(click.style(f"Error initializing database: {e}", fg="red"), err=True)
        return 1
    
    return 0


@cli.command()
@click.option("--url", "-u", required=True, help="Base URL of the site to scrape")
@click.option("--name", "-n", default=None, help="Human-readable name for the site")
@click.option("--pattern", "-p", default=None, help="Category page pattern (e.g., {url}?page={page})")
@click.option("--pages", "-v", type=int, default=1, help="Number of pages to scrape")
@click.option("--active/--inactive", default=True, show_default=True, help="Whether the site is active")
def add_site(url: str, name: str, pattern: str, pages: int, active: bool):
    """Add a new site configuration."""
    if not name:
        # Generate friendly name from URL
        from urllib.parse import urlparse
        parsed = urlparse(url)
        name = f"{parsed.netloc.replace('www.', '').replace('.', ' ').title()} News"
    
    session_gen = get_session()
    db = next(session_gen)
    
    try:
        registry = SiteConfigRegistry(db)
        site = registry.add_site(
            name=name,
            url=url,
            category_url_pattern=pattern,
            num_pages_to_scrape=pages,
            active=active
        )
        
        click.echo(click.style(f"Site added successfully! (ID: {site.id})", fg="green"))
        click.echo(f"  Name: {site.name}")
        click.echo(f"  URL: {site.url}")
    except ValueError as e:
        click.echo(click.style(str(e), fg="red"), err=True)
    except Exception as e:
        click.echo(click.style(f"Error adding site: {e}", fg="red"), err=True)
    finally:
        db.close()


@cli.command("list-sites")
@click.option("--all", "show_all", is_flag=True, help="Show inactive sites too")
def list_sites(show_all: bool):
    """List all configured sites."""
    session_gen = get_session()
    db = next(session_gen)
    
    try:
        registry = SiteConfigRegistry(db)
        sites = registry.list_sites(active_only=not show_all)
        
        if not sites:
            click.echo(click.style("No sites found. Add a site with 'add-site' command.", fg="yellow"))
            return 0
        
        table_data = []
        for site in sites:
            status = "✓" if site.active else "✗"
            js_status = "⚡" if site.uses_javascript else "-"
            last_scraped = site.last_scraped.strftime("%Y-%m-%d") if site.last_scraped else "Never"
            
            table_data.append([
                site.id,
                status,
                site.name,
                site.url[:50] + ("..." if len(site.url) > 50 else ""),
                f"{site.num_pages_to_scrape} pages",
                last_scraped,
                js_status
            ])
        
        headers = ["ID", "Act", "Name", "URL", "Pages", "Last Scrape", "JS"]
        click.echo(tabulate(table_data, headers=headers, tablefmt="grid"))
        
    except Exception as e:
        click.echo(click.style(f"Error listing sites: {e}", fg="red"), err=True)
    finally:
        db.close()


@cli.command()
@click.argument("url")
@click.option("--csv", "-c", "export_csv", help="Export results to CSV file")
@click.option("--json", "-j", "export_json", help="Export results to JSON file")
@click.option("--rate-limit/--no-rate-limit", default=True,
              help="Enable/disable rate limiting (default: enabled)")
def scrape_site(url: str, export_csv: str, export_json: str, rate_limit: bool):
    """Scrape a specific site by URL."""
    session_gen = get_session()
    db = next(session_gen)
    
    try:
        # Check if site exists
        registry = SiteConfigRegistry(db)
        site_config = registry.get_site_by_url(url)
        
        if not site_config:
            click.echo(click.style(f"Site not found: {url}", fg="yellow"))
            click.echo("Add it first with 'add-site' command.")
            return 1
        
        # Run scraper
        enable_rate_limiting = rate_limit
        with ScraperEngine(enable_rate_limiting=enable_rate_limiting) as engine:
            stats = engine.scrape_site(site_config, db, export_csv=export_csv, 
                                       export_json=export_json, enable_rate_limiting=enable_rate_limiting)
        
        # Display results
        click.echo(click.style(f"\nScraping complete for: {stats['site_name']}", fg="green"))
        click.echo(f"  Pages scraped: {stats['pages_scraped']}")
        click.echo(f"  Articles found: {stats['articles_found']}")
        click.echo(f"  Articles saved: {stats['articles_saved']}")
        click.echo(f"  Articles skipped (duplicates): {stats['articles_skipped']}")
        
        if stats["selenium_fallbacks"]:
            click.echo(click.style(f"  Selenium fallbacks used: {stats['selenium_fallbacks']}", fg="yellow"))
        
        if export_csv:
            click.echo(click.style(f"  CSV exported to: {export_csv}", fg="cyan"))
        if export_json:
            click.echo(click.style(f"  JSON exported to: {export_json}", fg="cyan"))
        
        if stats["errors"]:
            click.echo(click.style(f"\nErrors ({len(stats['errors'])}):", fg="yellow"))
            for error in stats["errors"][:5]:
                click.echo(f"  - {error}")
            if len(stats["errors"]) > 5:
                click.echo(f"  ... and {len(stats['errors']) - 5} more")
        
    except Exception as e:
        click.echo(click.style(f"Error scraping site: {e}", fg="red"), err=True)
    finally:
        db.close()


@cli.command("quick-scrape")
@click.argument("url")
@click.option("--output-json", "-o", default=None, help="Output JSON path")
@click.option(
    "--mode",
    type=click.Choice(["auto", "article", "listing"], case_sensitive=False),
    default="auto",
    show_default=True,
    help="Auto-detect article vs listing, or force mode",
)
@click.option("--max-articles", type=int, default=3, show_default=True, help="Max extracted articles")
@click.option(
    "--engine",
    type=click.Choice(["auto", "scrapling", "pydoll", "selenium", "beautifulsoup"], case_sensitive=False),
    default="auto",
    show_default=True,
    help="Preferred fetch engine for this quick run",
)
@click.option("--timeout", type=int, default=25, show_default=True, help="Fetch timeout in seconds")
@click.option("--rate-limit/--no-rate-limit", default=False, show_default=True, help="Enable per-domain rate limiting")
def quick_scrape(
    url: str,
    output_json: str,
    mode: str,
    max_articles: int,
    engine: str,
    timeout: int,
    rate_limit: bool,
):
    """Quick test scrape for one URL and export structured JSON."""
    if max_articles < 1:
        click.echo(click.style("--max-articles must be >= 1", fg="red"), err=True)
        return 1

    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        click.echo(click.style("URL must be absolute and start with http:// or https://", fg="red"), err=True)
        return 1

    clean_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", parsed.query, ""))
    domain = (parsed.netloc or "").lower().replace("www.", "")
    requested_mode = (mode or "auto").lower()
    engine_choice = (engine or "auto").lower()
    preferred_engine = engine_choice

    session_gen = get_session()
    db = next(session_gen)
    site: SiteConfig | None = None
    try:
        registry = SiteConfigRegistry(db)
        site = registry.get_site_by_url(clean_url)
        if site is None and domain:
            site = (
                db.query(SiteConfig)
                .filter(SiteConfig.domain == domain)
                .order_by(SiteConfig.id.asc())
                .first()
            )

        if preferred_engine == "auto":
            preferred_engine = site.preferred_scraper_type if site and site.preferred_scraper_type else "scrapling"

        temp_site = SiteConfig(
            name=(site.name if site else domain or "Quick Test Site"),
            url=clean_url,
            domain=domain or None,
            preferred_scraper_type=preferred_engine,
            uses_javascript=bool(site.uses_javascript) if site else False,
            language=(site.language if site else "en"),
            country=(site.country if site else None),
            location=((site.location or site.country) if site else None),
        )

        records = []
        attempted_urls = []
        listing_links_found = 0
        listing_engine = None

        with ScraperEngine(
            timeout=timeout,
            enable_rate_limiting=rate_limit,
            min_delay_between_requests=0.75,
        ) as scraper:
            def _quick_fetch(target_url: str):
                if engine_choice == "auto":
                    return scraper._fetch_page_for_site(temp_site, target_url)

                if preferred_engine == "scrapling":
                    html = scraper._fetch_page_scrapling(target_url)
                elif preferred_engine == "pydoll":
                    html = scraper._fetch_page_pydoll(target_url)
                elif preferred_engine == "selenium":
                    html = scraper._fetch_page_selenium(target_url)
                elif preferred_engine == "beautifulsoup":
                    html = scraper._fetch_page_beautifulsoup(target_url)
                else:
                    html = None

                if not html or scraper._detect_content_missing(html):
                    return None, preferred_engine
                return html, preferred_engine

            page_html, listing_engine = _quick_fetch(clean_url)
            if not page_html:
                click.echo(click.style("Failed to fetch the provided URL with configured backends.", fg="red"), err=True)
                return 1

            def _is_good_article(candidate: dict) -> bool:
                title = str(candidate.get("title") or "").strip()
                body = str(candidate.get("body") or "").strip()
                if not title or title.lower() == "untitled article":
                    return False
                return len(body) >= 180

            resolved_mode = requested_mode
            base_article = None
            if requested_mode in ("auto", "article"):
                base_article = scraper._extract_article(clean_url, page_html)
                if base_article and _is_good_article(base_article):
                    attempted_urls.append(clean_url)
                    records.append(
                        {
                            "article": _to_jsonable(base_article),
                            "scrape": {
                                "url": clean_url,
                                "engine_used": listing_engine,
                                "scrape_date": datetime.now().isoformat(),
                                "content_hash": scraper._get_content_hash(
                                    base_article.get("title"),
                                    base_article.get("body"),
                                ),
                            },
                        }
                    )
                    if requested_mode == "auto":
                        resolved_mode = "article"

            if requested_mode == "listing" or (requested_mode == "auto" and not records):
                resolved_mode = "listing"
                listing_links = scraper._parse_links_from_page(page_html, clean_url)
                listing_links_found = len(listing_links)
                for link in _quick_rank_links(listing_links):
                    if len(records) >= max_articles:
                        break
                    if link in attempted_urls:
                        continue
                    attempted_urls.append(link)

                    article_html, used_engine = _quick_fetch(link)
                    if not article_html:
                        continue

                    article_data = scraper._extract_article(link, article_html)
                    if not article_data or not _is_good_article(article_data):
                        continue

                    records.append(
                        {
                            "article": _to_jsonable(article_data),
                            "scrape": {
                                "url": link,
                                "engine_used": used_engine,
                                "scrape_date": datetime.now().isoformat(),
                                "content_hash": scraper._get_content_hash(
                                    article_data.get("title"),
                                    article_data.get("body"),
                                ),
                            },
                        }
                    )

            site_metadata = {
                "site_config_id": site.id if site else None,
                "name": (site.name if site else temp_site.name),
                "url": (site.url if site else clean_url),
                "domain": (site.domain if site and site.domain else domain),
                "country": (site.country or site.location) if site else None,
                "language": (site.language if site else None),
                "preferred_scraper_type": preferred_engine,
                "uses_javascript": bool(site.uses_javascript) if site else None,
            }
            for record in records:
                record["site"] = site_metadata

        if not output_json:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_domain = re.sub(r"[^a-zA-Z0-9.-]+", "-", domain or "quick")
            output_json = f"./data/exports/quick_scrape_{safe_domain}_{ts}.json"

        output_path = Path(output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        from ..export.json_export import JSONExporter

        run_metadata = {
            "pipeline": "quick_scrape",
            "input_url": clean_url,
            "requested_mode": requested_mode,
            "resolved_mode": resolved_mode,
            "preferred_engine": preferred_engine,
            "listing_engine_used": listing_engine,
            "max_articles": max_articles,
            "listing_links_found": listing_links_found,
            "candidate_urls_tested": len(attempted_urls),
            "records_exported": len(records),
            "timeout_seconds": timeout,
            "rate_limited": rate_limit,
            "generated_at": datetime.now().isoformat(),
        }

        exporter = JSONExporter(str(output_path))
        exporter.export_run_payload(records=_to_jsonable(records), run_metadata=run_metadata, overwrite=True)

        click.echo(click.style("Quick scrape complete.", fg="green"))
        click.echo(f"  Mode: {resolved_mode}")
        click.echo(f"  Records exported: {len(records)}")
        click.echo(f"  Output JSON: {output_path}")
        return 0
    except Exception as e:
        click.echo(click.style(f"Error in quick scrape: {e}", fg="red"), err=True)
        return 1
    finally:
        db.close()


@cli.command()
@click.option("--limit", "-l", type=int, default=None, help="Maximum number of sites to scrape")
@click.option("--csv", "-c", "export_csv", help="Export all results to CSV file")
@click.option("--json", "-j", "export_json", help="Export all results to JSON file")
@click.option("--rate-limit/--no-rate-limit", default=True,
              help="Enable/disable rate limiting (default: enabled)")
def scrape_all(limit: int = None, export_csv: str = None, export_json: str = None, 
               rate_limit: bool = True):
    """Scrape all configured sites."""
    session_gen = get_session()
    db = next(session_gen)
    
    try:
        # Count active sites
        registry = SiteConfigRegistry(db)
        total_sites = len(registry.list_sites(active_only=True))
        
        if total_sites == 0:
            click.echo(click.style("No active sites configured. Add sites with 'add-site' command.", fg="yellow"))
            return 1
        
        enable_rate_limiting = rate_limit
        click.echo(f"Found {total_sites} active site(s) to scrape...")
        
        if enable_rate_limiting:
            click.echo(click.style("Rate limiting enabled: 1+ second delay between requests", fg="blue"))
        
        with ScraperEngine(enable_rate_limiting=enable_rate_limiting) as engine:
            results = engine.scrape_all_sites(
                db, active_only=True, limit=limit, export_csv=export_csv, export_json=export_json,
                enable_rate_limiting=enable_rate_limiting
            )
        
        # Display summary
        click.echo(click.style("\nScraping Summary:", fg="green"))
        total_articles_saved = sum(r.get("articles_saved", 0) for r in results)
        total_articles_found = sum(r.get("articles_found", 0) for r in results)
        
        click.echo(f"  Sites processed: {len(results)}")
        click.echo(f"  Articles found: {total_articles_found}")
        click.echo(f"  Articles saved: {total_articles_saved}")
        
        if export_csv:
            click.echo(click.style(f"  CSV exported to: {export_csv}", fg="cyan"))
        if export_json:
            click.echo(click.style(f"  JSON exported to: {export_json}", fg="cyan"))
        
        # Display per-site details
        click.echo(click.style("\nPer-Site Results:", fg="cyan"))
        for result in results:
            name = result.get("site_name", "Unknown")
            articles_saved = result.get("articles_saved", 0)
            
            if "error" in result:
                status = click.style("ERROR", fg="red")
                error_msg = f" - {result['error']}"
            else:
                status = click.style(f"✓ ({articles_saved} articles)", fg="green")
                error_msg = ""
            
            click.echo(f"  {name}: {status}{error_msg}")
        
    except Exception as e:
        click.echo(click.style(f"Error scraping sites: {e}", fg="red"), err=True)
    finally:
        db.close()


@cli.command()
@click.option("--force", "-f", is_flag=True, help="Skip confirmation prompt")
def seed(force: bool = False):
    """Seed the database with default test sites."""
    
    if not force:
        click.confirm(
            "This will add 3 default test sites. Continue?",
            abort=True
        )
    
    session_gen = get_session()
    db = next(session_gen)
    
    try:
        registry = SiteConfigRegistry(db)
        
        # Get existing URLs
        existing_urls = {s.url for s in registry.list_sites(active_only=False)}
        
        # Add default sites (skip if already exists)
        added_count = 0
        for site_data in get_default_sites():
            url = site_data["url"]
            
            if url not in existing_urls:
                try:
                    registry.add_site(
                        name=site_data["name"],
                        url=url,
                        category_url_pattern=site_data.get("category_url_pattern"),
                        num_pages_to_scrape=site_data.get("num_pages_to_scrape", 1),
                        active=site_data.get("active", True)
                    )
                    click.echo(click.style(f"✓ Added: {site_data['name']}", fg="green"))
                    added_count += 1
                except ValueError as e:
                    click.echo(click.style(f"✗ Skipped ({url}): {e}", fg="yellow"))
            else:
                click.echo(click.style(f"- Already exists: {site_data['name']}", fg="blue"))
        
        click.echo(click.style(f"\nSeeding complete! Added {added_count} new site(s).", fg="green"))
        
    except Exception as e:
        click.echo(click.style(f"Error seeding sites: {e}", fg="red"), err=True)
    finally:
        db.close()


@cli.command("sync-config-sites")
@click.option(
    "--config",
    "config_path",
    default="news_scraper/config/sites_config.yaml",
    show_default=True,
    help="Path to YAML sites config file",
)
def sync_config_sites(config_path: str):
    """Sync site definitions from config file into SQL."""
    session_gen = get_session()
    spider_session_gen = get_spider_session()
    db = next(session_gen)
    spider_db = next(spider_session_gen)
    try:
        stats = sync_sites_from_config(db, config_path, spider_session=spider_db)
        click.echo(click.style("Config sync complete.", fg="green"))
        click.echo(f"  Configured sites: {stats['configured_sites']}")
        click.echo(f"  Added sites: {stats['added_sites']}")
        click.echo(f"  Updated sites: {stats['updated_sites']}")
        click.echo(f"  Added categories: {stats['added_categories']}")
        click.echo(f"  Updated categories: {stats['updated_categories']}")
        click.echo(f"  Added technologies: {stats['added_technologies']}")
        click.echo(f"  Updated technologies: {stats['updated_technologies']}")
        click.echo(f"  Updated strategies: {stats['updated_strategies']}")
    except Exception as e:
        click.echo(click.style(f"Error syncing config sites: {e}", fg="red"), err=True)
        return 1
    finally:
        spider_db.close()
        db.close()

    return 0


@cli.command("scrape-config")
@click.option(
    "--config",
    "config_path",
    default="news_scraper/config/sites_config.yaml",
    show_default=True,
    help="Path to YAML sites config file",
)
@click.option(
    "--mode",
    type=click.Choice(["current", "historic", "historical"], case_sensitive=False),
    default="current",
    show_default=True,
    help="Current=latest pages, Historic/Historical=deep/backfill mode",
)
@click.option("--output-json", default=None, help="Output JSON path")
@click.option("--limit", type=int, default=None, help="Limit number of configured sites to scrape")
@click.option("--offset", type=int, default=0, show_default=True, help="Offset over configured sites")
@click.option("--cutoff-date", type=str, default=None, help="Historical mode cutoff date (YYYY-MM-DD)")
@click.option("--max-pages", type=int, default=None, help="Max pages per site for historical mode")
@click.option("--start-page", type=int, default=1, show_default=True, help="Start page for historical chunking")
@click.option("--end-page", type=int, default=None, help="End page for historical chunking")
@click.option("--chunk-id", type=str, default=None, help="Optional chunk id for actor batch tracking")
@click.option(
    "--story-batch-size",
    type=int,
    default=200,
    show_default=True,
    help="Maximum stories to export in this run (0 disables cap)",
)
@click.option("--site-url", "site_urls", multiple=True, help="Only scrape matching site URL(s)")
@click.option("--site-name", "site_names", multiple=True, help="Only scrape matching site name(s)")
@click.option("--country", "countries", multiple=True, help="Only scrape sites from these country values")
@click.option("--sync/--no-sync", default=True, show_default=True, help="Sync config into SQL before scraping")
@click.option("--rate-limit/--no-rate-limit", default=True, show_default=True, help="Enable per-domain rate limiting")
def scrape_config(
    config_path: str,
    mode: str,
    output_json: str,
    limit: int,
    offset: int,
    cutoff_date: str,
    max_pages: int,
    start_page: int,
    end_page: int,
    chunk_id: str,
    story_batch_size: int,
    site_urls: tuple[str, ...],
    site_names: tuple[str, ...],
    countries: tuple[str, ...],
    sync: bool,
    rate_limit: bool,
):
    """
    Run config-driven scraping for large batches of sites.

    Every exported JSON record includes article fields + site metadata from SQL.
    """
    cutoff_datetime = None
    if cutoff_date:
        from datetime import datetime as dt

        try:
            cutoff_datetime = dt.strptime(cutoff_date, "%Y-%m-%d")
        except ValueError:
            click.echo(click.style("Invalid --cutoff-date format. Use YYYY-MM-DD.", fg="red"), err=True)
            return 1
    if story_batch_size < 0:
        click.echo(click.style("--story-batch-size must be >= 0", fg="red"), err=True)
        return 1

    session_gen = get_session()
    spider_session_gen = get_spider_session()
    db = next(session_gen)
    spider_db = next(spider_session_gen)
    try:
        result = run_config_scrape(
            db_session=db,
            spider_session=spider_db,
            config_path=config_path,
            mode=mode,
            output_json=output_json,
            limit=limit,
            offset=offset,
            cutoff_date=cutoff_datetime,
            max_pages=max_pages,
            start_page=start_page,
            end_page=end_page,
            chunk_id=chunk_id,
            site_urls=list(site_urls) or None,
            site_names=list(site_names) or None,
            countries=list(countries) or None,
            enable_rate_limiting=rate_limit,
            sync_first=sync,
            story_batch_size=story_batch_size,
        )
        metadata = result["run_metadata"]
        summary = metadata["summary"]

        click.echo(click.style("Config-driven scrape complete.", fg="green"))
        click.echo(f"  Mode: {metadata['mode']}")
        click.echo(f"  Sites targeted: {summary['sites_targeted']}")
        click.echo(f"  Articles found: {summary['articles_found']}")
        click.echo(f"  Articles saved: {summary['articles_saved']}")
        click.echo(f"  Records exported: {summary['records_exported']}")
        if metadata.get("story_batch_size"):
            click.echo(f"  Story batch size: {metadata['story_batch_size']}")
        if metadata.get("selected_site_urls"):
            click.echo(f"  Site URL filters: {len(metadata['selected_site_urls'])}")
        if metadata.get("selected_site_names"):
            click.echo(f"  Site name filters: {len(metadata['selected_site_names'])}")
        if metadata.get("selected_countries"):
            click.echo(f"  Country filters: {', '.join(metadata['selected_countries'])}")
        if mode.lower() in {"historical", "historic"}:
            click.echo(f"  Page window: {metadata.get('start_page')} -> {metadata.get('end_page') or 'auto'}")
            if metadata.get("chunk_id"):
                click.echo(f"  Chunk ID: {metadata['chunk_id']}")
        click.echo(f"  Output JSON: {result['output_json']}")
    except Exception as e:
        click.echo(click.style(f"Error in config-driven scrape: {e}", fg="red"), err=True)
        return 1
    finally:
        spider_db.close()
        db.close()

    return 0


@cli.command()
@click.argument("url")
def remove_site(url: str):
    """Remove a site configuration by URL."""
    session_gen = get_session()
    db = next(session_gen)
    
    try:
        registry = SiteConfigRegistry(db)
        
        # Find site by URL
        site_config = registry.get_site_by_url(url)
        
        if not site_config:
            click.echo(click.style(f"Site not found: {url}", fg="yellow"))
            return 1
        
        # Confirm deletion
        click.confirm(
            f"Are you sure you want to remove '{site_config.name}' ({url})?",
            abort=True
        )
        
        if registry.delete_site(site_config.id):
            click.echo(click.style(f"Site removed: {url}", fg="green"))
        else:
            click.echo(click.style("Failed to remove site.", fg="red"), err=True)
            
    except Exception as e:
        click.echo(click.style(f"Error removing site: {e}", fg="red"), err=True)
    finally:
        db.close()


@cli.command("scrape-all-incremental")
@click.option("--csv", "-c", "export_csv", help="Export all results to CSV file")
@click.option("--json", "-j", "export_json", help="Export all results to JSON file")
@click.option("--rate-limit/--no-rate-limit", default=True,
              help="Enable/disable rate limiting (default: enabled)")
def scrape_all_incremental(export_csv: str = None, export_json: str = None, 
                         rate_limit: bool = True):
    """Scrape all configured sites in incremental mode (only newest articles)."""
    session_gen = get_session()
    db = next(session_gen)
    
    try:
        registry = SiteConfigRegistry(db)
        total_sites = len(registry.list_sites(active_only=True))
        
        if total_sites == 0:
            click.echo(click.style("No active sites configured.", fg="yellow"))
            return 1
        
        enable_rate_limiting = rate_limit
        click.echo(click.style("\nIncremental scraping mode: Fresh articles from current pages", fg="green"))
        click.echo(f"Found {total_sites} active site(s) to scrape...")
        
        with ScraperEngine(enable_rate_limiting=enable_rate_limiting) as engine:
            results = engine.scrape_all_sites(
                db, active_only=True, mode="incremental", export_csv=export_csv, 
                export_json=export_json, enable_rate_limiting=enable_rate_limiting
            )
        
        click.echo(click.style("\nIncremental Scraping Summary:", fg="green"))
        total_articles_saved = sum(r.get("articles_saved", 0) for r in results)
        click.echo(f"  Total new articles: {total_articles_saved}")
        
        for result in results:
            if "error" not in result:
                site_name = result.get("site_name", "Unknown")
                articles = result.get("articles_saved", 0)
                click.echo(f"  {site_name}: ✓ ({articles} new articles)")
    
    except Exception as e:
        click.echo(click.style(f"Error scraping sites: {e}", fg="red"), err=True)
    finally:
        db.close()


@cli.command("scrape-all-backfill")
@click.option("--csv", "-c", "export_csv", help="Export all results to CSV file")
@click.option("--json", "-j", "export_json", help="Export all results to JSON file")
@click.option("--rate-limit/--no-rate-limit", default=True,
              help="Enable/disable rate limiting (default: enabled)")
@click.option("--cutoff-date", "--date", "-d", type=str, default=None, 
              help="Date cutoff in YYYY-MM-DD format (backfill older articles before this date)")
@click.option("--max-pages", "-p", type=int, default=None,
              help="Maximum pages to go deep for each site")
def scrape_all_backfill(export_csv: str = None, export_json: str = None, 
                       rate_limit: bool = True, cutoff_date: str = None, 
                       max_pages: int = None):
    """Scrape all configured sites in backfill mode (historical articles)."""
    session_gen = get_session()
    db = next(session_gen)
    
    try:
        registry = SiteConfigRegistry(db)
        total_sites = len(registry.list_sites(active_only=True))
        
        if total_sites == 0:
            click.echo(click.style("No active sites configured.", fg="yellow"))
            return 1
        
        enable_rate_limiting = rate_limit
        cutoff_datetime = None
        if cutoff_date:
            from datetime import datetime as dt
            try:
                cutoff_datetime = dt.strptime(cutoff_date, "%Y-%m-%d")
            except ValueError:
                click.echo(click.style("Invalid date format for --cutoff-date. Use YYYY-MM-DD.", fg="red"))
                return 1
        
        click.echo(click.style("\nBackfill mode: Historical articles up to date cutoff", fg="green"))
        if cutoff_date:
            click.echo(f"  Date cutoff: {cutoff_date}")
        else:
            click.echo("  (No date cutoff - going as deep as configured pages)")
        if max_pages:
            click.echo(f"  Max pages per site: {max_pages}")
        
        with ScraperEngine(enable_rate_limiting=enable_rate_limiting) as engine:
            results = engine.scrape_all_sites(
                db, active_only=True, mode="backfill", export_csv=export_csv, 
                export_json=export_json, enable_rate_limiting=enable_rate_limiting,
                date_cutoff=cutoff_datetime, max_pages=max_pages
            )
        
        click.echo(click.style("\nBackfill Scraping Summary:", fg="green"))
        total_articles_saved = sum(r.get("articles_saved", 0) for r in results)
        click.echo(f"  Total new articles: {total_articles_saved}")
        
        for result in results:
            if "error" not in result:
                site_name = result.get("site_name", "Unknown")
                articles = result.get("articles_saved", 0)
                click.echo(f"  {site_name}: ✓ ({articles} new articles)")
    
    except Exception as e:
        click.echo(click.style(f"Error scraping sites: {e}", fg="red"), err=True)
    finally:
        db.close()


@cli.command("validate-site")
@click.argument("url")
def validate_site(url: str):
    """Validate a single site's extraction selectors."""
    session_gen = get_session()
    db = next(session_gen)
    
    try:
        registry = SiteConfigRegistry(db)
        site_config = registry.get_site_by_url(url)
        
        if not site_config:
            click.echo(click.style(f"Site not found: {url}", fg="yellow"))
            return 1
        
        from ..validation.validator import SiteValidator
        validator = SiteValidator()
        result = validator.validate_site(site_config)
        
        status_colors = {
            "pass": ("green", "✓"),
            "fail": ("red", "✗"),
            "needs_review": ("yellow", "!"),
            "paused": ("blue", "-"),
        }
        
        color, symbol = status_colors.get(result.status, ("white", "?"))
        click.echo(click.style(f"Validation for {result.site_name}:", fg=color))
        click.echo(f"  Status: {symbol} {result.status.upper()}")
        click.echo(f"  Score: {result.field_completeness_score}/100")
        
        if result.failure_reason:
            click.echo(click.style(f"  Reason: {result.failure_reason}", fg="red"))
        
        if result.sample_extracted_values:
            click.echo("  Sample Values:")
            for key, value in result.sample_extracted_values.items():
                if key == "error":
                    click.echo(f"    - {key}: {click.style(value, fg='red')}")
                else:
                    display_value = str(value)[:50] + "..." if isinstance(value, str) and len(value) > 50 else value
                    click.echo(f"    - {key}: {display_value}")
        
        if result.suggested_selector_updates:
            click.echo(click.style("\nSuggested Updates:", fg="yellow"))
            for suggestion in result.suggested_selector_updates:
                click.echo(f"    - {suggestion['field']}: {suggestion['suggestion']}")
        
        return 0
        
    except Exception as e:
        click.echo(click.style(f"Error validating site: {e}", fg="red"), err=True)
        return 1
    finally:
        db.close()


@cli.command("validate-all")
def validate_all():
    """Validate all configured sites."""
    session_gen = get_session()
    db = next(session_gen)
    
    try:
        from ..validation.validator import SiteValidator
        validator = SiteValidator()
        results = validator.validate_all_sites()
        
        passed = sum(1 for r in results if r.status == "pass")
        failed = sum(1 for r in results if r.status == "fail")
        needs_review = sum(1 for r in results if r.status == "needs_review")
        
        click.echo(click.style("\nValidation Complete:", fg="cyan"))
        click.echo(f"  Sites validated: {len(results)}")
        click.echo(f"  Passed: {passed}")
        click.echo(f"  Failed: {failed}")
        click.echo(f"  Needs Review: {needs_review}")
        
    except Exception as e:
        click.echo(click.style(f"Error validating sites: {e}", fg="red"), err=True)
    finally:
        db.close()


@cli.command("stats")
@click.option("--output-format", "-f", type=click.Choice(["table", "json"]), default="table",
              help="Output format for rate limiter stats")
def stats(output_format: str):
    """Show database and rate limiter statistics."""
    session_gen = get_session()
    spider_session_gen = get_spider_session()
    db = next(session_gen)
    spider_db = next(spider_session_gen)
    
    try:
        # Count sites
        total_sites = db.query(SiteConfig).count()
        active_sites = db.query(SiteConfig).filter_by(active=True).count()
        
        # URL-level crawl ledger
        tracked_urls = db.query(ArticleUrlLedger).count()
        total_record_emits = db.query(func.coalesce(func.sum(ArticleUrlLedger.total_records_emitted), 0)).scalar() or 0
        
        # Get latest scrape
        from datetime import datetime, timedelta
        recent_cutoff = datetime.now() - timedelta(days=7)
        recently_scraped = db.query(SiteConfig).filter(
            SiteConfig.last_scraped >= recent_cutoff
        ).count()

        # Spider/category planning coverage
        total_categories = spider_db.query(SiteCategory).count()
        active_categories = spider_db.query(SiteCategory).filter(SiteCategory.active.is_(True)).count()
        category_states = spider_db.query(CategoryCrawlState).count()
        
        click.echo(click.style("Database Statistics:", fg="cyan"))
        click.echo(f"  Total sites configured: {total_sites}")
        click.echo(f"  Active sites: {active_sites}")
        click.echo(f"  Tracked article URLs (ledger): {tracked_urls:,}")
        click.echo(f"  Total JSON records emitted: {int(total_record_emits):,}")
        click.echo(f"  Sites scraped in last 7 days: {recently_scraped}")
        click.echo(f"  Configured categories: {total_categories}")
        click.echo(f"  Active categories: {active_categories}")
        click.echo(f"  Category crawl states tracked: {category_states}")
        
    except Exception as e:
        click.echo(click.style(f"Error getting stats: {e}", fg="red"), err=True)
    finally:
        spider_db.close()
        db.close()


@cli.command()
def doctor():
    """Check local runtime readiness (DB + scraper backends)."""
    from ..database.session import test_connection, _primary_db_url, _spider_db_url

    click.echo(click.style("Runtime Diagnostics", fg="cyan"))
    click.echo(f"  Primary DB URL: {_primary_db_url()}")
    click.echo(f"  Spider DB URL:  {_spider_db_url()}")

    db_ok = test_connection()
    click.echo(f"  Database connectivity: {'OK' if db_ok else 'FAIL'}")

    modules = [
        ("scrapling", "Primary engine"),
        ("pydoll", "Secondary engine"),
        ("selenium", "Fallback browser engine"),
        ("bs4", "HTML parser"),
    ]
    missing = []
    for module_name, label in modules:
        try:
            importlib.import_module(module_name)
            click.echo(f"  {label}: OK ({module_name})")
        except Exception:
            click.echo(f"  {label}: MISSING ({module_name})")
            missing.append(module_name)

    if not db_ok:
        click.echo(click.style("Doctor check failed: database connection issue.", fg="red"), err=True)
        return 1

    if missing:
        click.echo(click.style("Doctor check partial: optional scraper backends missing.", fg="yellow"))
        click.echo("Install full requirements for maximum coverage.")
        return 0

    click.echo(click.style("Doctor check passed.", fg="green"))
    return 0


@cli.command("list-templates")
def list_templates():
    """List available site configuration templates."""
    click.echo(click.style("Available Site Templates:", fg="cyan"))
    
    table_data = []
    for template_name, info in SITE_TEMPLATES.items():
        selectors = [k for k in info.keys() if not k == "name"]
        table_data.append([
            template_name,
            info["name"],
            ", ".join(selectors[:3]) + ("..." if len(selectors) > 3 else "")
        ])
    
    headers = ["Name", "Description", "Selectors"]
    click.echo(tabulate(table_data, headers=headers, tablefmt="grid"))


@cli.command()
@click.option("--template", "-t", required=True, help="Template name to use")
@click.option("--url", "-u", required=True, help="Site URL")
@click.option("--name", "-n", default=None, help="Display name (auto-generated if not provided)")
@click.option("--pages", "-p", type=int, default=1, help="Number of pages to scrape")
def add_from_template(template: str, url: str, name: str, pages: int):
    """Add a site using a predefined template."""
    if template not in SITE_TEMPLATES:
        click.echo(click.style(f"Template '{template}' not found.", fg="yellow"))
        click.echo("Available templates:")
        for t_name in SITE_TEMPLATES:
            click.echo(f"  - {t_name}")
        return 1
    
    session_gen = get_session()
    db = next(session_gen)
    
    try:
        if not name:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            name = f"{parsed.netloc.replace('www.', '').replace('.', ' ').title()} News"
        
        # Get template and create config
        template_data = SITE_TEMPLATES[template]
        config = create_site_config_from_template(name, url, template, pages)
        
        registry = SiteConfigRegistry(db)
        site = registry.add_site(
            name=config["name"],
            url=config["url"],
            category_url_pattern=config.get("category_url_pattern"),
            num_pages_to_scrape=pages,
            active=True
        )
        
        # Update selectors on the created site
        selector_mapping = {
            "article_selector": "article_selector",
            "title_selector": "title_selector",
            "date_selector": "date_selector",
            "content_selector": "body_selector",
        }
        for template_field, model_field in selector_mapping.items():
            if template_data.get(template_field):
                setattr(site, model_field, template_data[template_field])
        
        db.commit()
        db.refresh(site)
        
        click.echo(click.style(f"Site added from '{template}' template! (ID: {site.id})", fg="green"))
        click.echo(f"  Name: {site.name}")
        click.echo(f"  URL: {site.url}")
        click.echo(f"  Pages: {pages}")
        click.echo(click.style("\nSelectors configured:", fg="cyan"))
        for field in ["article_selector", "title_selector", "date_selector", "body_selector"]:
            value = getattr(site, field)
            if value:
                click.echo(f"  {field}: {value}")
        
    except ValueError as e:
        click.echo(click.style(str(e), fg="red"), err=True)
    except Exception as e:
        click.echo(click.style(f"Error adding site: {e}", fg="red"), err=True)
    finally:
        db.close()


@cli.command()
@click.argument("output", required=False)
def export_sites(output: str = None):
    """Export site configurations to JSON or print to stdout."""
    session_gen = get_session()
    db = next(session_gen)
    
    try:
        registry = SiteConfigRegistry(db)
        sites = registry.list_sites(active_only=False)
        
        data = []
        for site in sites:
            site_data = {
                "name": site.name,
                "url": site.url,
                "domain": site.domain,
                "country": site.country or site.location,
                "language": site.language,
                "server_header": site.server_header,
                "server_vendor": site.server_vendor,
                "hosting_provider": site.hosting_provider,
                "technology_stack_summary": site.technology_stack_summary,
                "category_url_pattern": site.category_url_pattern,
                "num_pages_to_scrape": site.num_pages_to_scrape,
                "active": site.active,
                "uses_javascript": site.uses_javascript,
                "selectors": {
                    "article_selector": site.article_selector,
                    "title_selector": site.title_selector,
                    "date_selector": site.date_selector,
                    "body_selector": site.body_selector,
                }
            }
            data.append(site_data)
        
        json_output = json.dumps(data, indent=2)
        
        if output:
            with open(output, 'w') as f:
                f.write(json_output)
            click.echo(click.style(f"Exported {len(data)} sites to: {output}", fg="green"))
        else:
            click.echo(json_output)
            
    except Exception as e:
        click.echo(click.style(f"Error exporting sites: {e}", fg="red"), err=True)
    finally:
        db.close()


@cli.command()
@click.argument("input_file")
def import_sites(input_file: str):
    """Import site configurations from JSON file."""
    db = None
    try:
        with open(input_file, 'r') as f:
            data = json.load(f)
        
        if not isinstance(data, list):
            click.echo(click.style("Invalid format: expected a JSON array", fg="red"), err=True)
            return 1
        
        session_gen = get_session()
        db = next(session_gen)
        
        try:
            registry = SiteConfigRegistry(db)
            
            imported_count = 0
            skipped_count = 0
            
            for site_data in data:
                url = site_data.get("url")
                
                if not url:
                    click.echo(click.style("Skipping: no URL provided", fg="yellow"))
                    continue
                
                # Check if already exists
                existing = registry.get_site_by_url(url)
                if existing:
                    skipped_count += 1
                    click.echo(click.style(f"- Already exists: {url}", fg="blue"))
                    continue
                
                # Add the site
                try:
                    registry.add_site(
                        name=site_data.get("name", "Unknown"),
                        url=url,
                        category_url_pattern=site_data.get("category_url_pattern"),
                        num_pages_to_scrape=site_data.get("num_pages_to_scrape", 1),
                        active=site_data.get("active", True)
                    )
                    imported_count += 1
                    click.echo(click.style(f"✓ Added: {url}", fg="green"))
                except ValueError as e:
                    click.echo(click.style(f"✗ Skipped ({url}): {e}", fg="yellow"))
            
            click.echo(click.style("\nImport complete!", fg="green"))
            click.echo(f"  Imported: {imported_count}")
            click.echo(f"  Skipped (exists): {skipped_count}")
            
        except Exception as e:
            click.echo(click.style(f"Error importing sites: {e}", fg="red"), err=True)
            
    except FileNotFoundError:
        click.echo(click.style(f"File not found: {input_file}", fg="red"), err=True)
    except json.JSONDecodeError as e:
        click.echo(click.style(f"Invalid JSON: {e}", fg="red"), err=True)
    finally:
        if db is not None:
            db.close()


@cli.command("prepare-assessment")
@click.option("--site-id", type=int, default=None, help="SiteConfig ID to assess")
@click.option("--url", type=str, default=None, help="Site URL to assess")
@click.option("--model", default="gpt-4.1-mini", show_default=True, help="LLM model label")
@click.option("--trigger", default="manual", show_default=True, help="Trigger type (manual/scheduled/post_scrape)")
def prepare_assessment(site_id: int = None, url: str = None, model: str = "gpt-4.1-mini", trigger: str = "manual"):
    """Create a line-by-line LLM assessment run for one site."""
    if not site_id and not url:
        click.echo(click.style("Provide either --site-id or --url.", fg="red"), err=True)
        return 1

    session_gen = get_session()
    spider_session_gen = get_spider_session()
    db = next(session_gen)
    spider_db = next(spider_session_gen)
    try:
        registry = SiteConfigRegistry(db)
        site = registry.get_site(site_id) if site_id else registry.get_site_by_url(url)
        if not site:
            click.echo(click.style("Site not found.", fg="yellow"))
            return 1

        run = create_line_assessment_run(
            db_session=db,
            site_config_id=site.id,
            llm_model=model,
            trigger_type=trigger,
            scope="full",
            spider_session=spider_db,
        )
        click.echo(click.style("Assessment run created.", fg="green"))
        click.echo(f"  run_id: {run.id}")
        click.echo(f"  site_id: {run.site_config_id}")
        click.echo(f"  total_lines: {run.total_lines}")
        click.echo("Use `export-assessment <run_id>` to send the payload to your LLM.")
    except Exception as e:
        click.echo(click.style(f"Error preparing assessment: {e}", fg="red"), err=True)
        return 1
    finally:
        spider_db.close()
        db.close()

    return 0


@cli.command("export-assessment")
@click.argument("run_id", type=int)
@click.option("--output", "-o", default=None, help="Write JSON payload to file (stdout if omitted)")
def export_assessment(run_id: int, output: str = None):
    """Export an assessment run payload for LLM review."""
    session_gen = get_session()
    db = next(session_gen)
    try:
        payload = export_assessment_payload(db, run_id)
        serialized = json.dumps(payload, indent=2, ensure_ascii=False)

        if output:
            with open(output, "w", encoding="utf-8") as f:
                f.write(serialized)
            click.echo(click.style(f"Assessment payload saved to {output}", fg="green"))
        else:
            click.echo(serialized)
    except Exception as e:
        click.echo(click.style(f"Error exporting assessment: {e}", fg="red"), err=True)
        return 1
    finally:
        db.close()

    return 0


@cli.command("apply-assessment")
@click.argument("run_id", type=int)
@click.argument("review_file")
@click.option("--reviewed-by", default="llm", show_default=True, help="Reviewer identifier")
def apply_assessment(run_id: int, review_file: str, reviewed_by: str = "llm"):
    """
    Apply reviewed line-level recommendations from a JSON file.

    Expected JSON shape:
      {"lines": [...]}  or [...]
    """
    session_gen = get_session()
    spider_session_gen = get_spider_session()
    db = next(session_gen)
    spider_db = next(spider_session_gen)
    try:
        with open(review_file, "r", encoding="utf-8") as f:
            payload = json.load(f)

        approved_lines = payload.get("lines") if isinstance(payload, dict) else payload
        if not isinstance(approved_lines, list):
            click.echo(click.style("Review file must contain a list of lines or {'lines': [...]} structure.", fg="red"), err=True)
            return 1

        run = apply_line_updates(
            db_session=db,
            assessment_run_id=run_id,
            approved_lines=approved_lines,
            reviewed_by=reviewed_by,
            spider_session=spider_db,
        )
        click.echo(click.style("Assessment updates applied.", fg="green"))
        click.echo(f"  run_id: {run.id}")
        click.echo(f"  lines_flagged: {run.lines_flagged}")
        click.echo(f"  lines_applied: {run.lines_applied}")
    except FileNotFoundError:
        click.echo(click.style(f"File not found: {review_file}", fg="red"), err=True)
        return 1
    except json.JSONDecodeError as e:
        click.echo(click.style(f"Invalid JSON: {e}", fg="red"), err=True)
        return 1
    except Exception as e:
        click.echo(click.style(f"Error applying assessment: {e}", fg="red"), err=True)
        return 1
    finally:
        spider_db.close()
        db.close()

    return 0


@cli.command("bootstrap-spider")
@click.option("--site-id", type=int, default=None, help="SiteConfig ID to bootstrap")
@click.option("--url", type=str, default=None, help="Site URL to bootstrap")
@click.option("--name", default="default_news_flow", show_default=True, help="Spider diagram name")
def bootstrap_spider(site_id: int = None, url: str = None, name: str = "default_news_flow"):
    """Create a default spider diagram for a site if one does not exist."""
    if not site_id and not url:
        click.echo(click.style("Provide either --site-id or --url.", fg="red"), err=True)
        return 1

    session_gen = get_session()
    spider_session_gen = get_spider_session()
    db = next(session_gen)
    spider_db = next(spider_session_gen)
    try:
        registry = SiteConfigRegistry(db)
        site = registry.get_site(site_id) if site_id else registry.get_site_by_url(url)
        if not site:
            click.echo(click.style("Site not found.", fg="yellow"))
            return 1

        diagram = ensure_default_spider_diagram(spider_db, site, diagram_name=name)
        click.echo(click.style("Spider diagram ready.", fg="green"))
        click.echo(f"  site_id: {site.id}")
        click.echo(f"  diagram_id: {diagram.id}")
        click.echo(f"  name: {diagram.name}")
        click.echo(f"  version: {diagram.version}")
    except Exception as e:
        click.echo(click.style(f"Error bootstrapping spider diagram: {e}", fg="red"), err=True)
        return 1
    finally:
        spider_db.close()
        db.close()

    return 0


@cli.command("web")
@click.option("--host", "-h", default="0.0.0.0", help="Host to run the web server on")
@click.option("--port", "-p", default=5000, type=int, help="Port to run the web server on")
@click.option("--debug/--no-debug", default=False, help="Enable/disable debug mode")
def web_server(host: str, port: int, debug: bool):
    """Start the web interface server (Phase 4)."""
    try:
        from ..web.app import create_app
        app = create_app()
        
        click.echo(click.style("Starting The Rise of the Phoenix Web Interface", fg="green"))
        click.echo(click.style(f"Web server running on: http://{host}:{port}", fg="cyan"))
        click.echo(click.style("Press Ctrl+C to stop.", fg="yellow"))
        click.echo("")
        
        app.run(host=host, port=port, debug=debug)
        
    except ImportError:
        click.echo(click.style("Error: Flask is not installed. Run 'pip install flask'", fg="red"), err=True)
        return 1
    except Exception as e:
        click.echo(click.style(f"Error starting web server: {e}", fg="red"), err=True)
        return 1


if __name__ == "__main__":
    cli()
