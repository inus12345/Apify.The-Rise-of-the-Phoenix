"""CLI commands for the news scraper platform."""
import click
from tabulate import tabulate
import json

from ..database.session import init_db, get_session
from ..database.models import SiteConfig, ScrapedArticle, ValidationRun
from ..scraping.config_registry import SiteConfigRegistry, get_default_sites
from ..scraping.engine import ScraperEngine
from ..config_templates.templates import (
    SITE_TEMPLATES,
    create_site_config_from_template,
    list_available_templates
)


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
        _init_db()
        click.echo(click.style("Database initialized successfully!", fg="green"))
        click.echo("Database file created at: data/scraping.db")
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
@click.option("--no-rate-limit/--rate-limit", default=True, 
              help="Disable/enable rate limiting (default: enabled)")
def scrape_site(url: str, export_csv: str, export_json: str, no_rate_limit: bool):
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
        enable_rate_limiting = not no_rate_limit
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


@cli.command()
@click.option("--limit", "-l", type=int, default=None, help="Maximum number of sites to scrape")
@click.option("--csv", "-c", "export_csv", help="Export all results to CSV file")
@click.option("--json", "-j", "export_json", help="Export all results to JSON file")
@click.option("--no-rate-limit/--rate-limit", default=True,
              help="Disable/enable rate limiting (default: enabled)")
def scrape_all(limit: int = None, export_csv: str = None, export_json: str = None, 
               no_rate_limit: bool = True):
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
        
        enable_rate_limiting = not no_rate_limit
        click.echo(f"Found {total_sites} active site(s) to scrape...")
        
        if enable_rate_limiting:
            click.echo(click.style("Rate limiting enabled: 1+ second delay between requests", fg="blue"))
        
        with ScraperEngine(enable_rate_limiting=enable_rate_limiting) as engine:
            results = engine.scrape_all_sites(
                db, active_only=True, export_csv=export_csv, export_json=export_json,
                enable_rate_limiting=enable_rate_limiting
            )
            
            # Apply limit if specified
            if limit:
                results = results[:limit]
        
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
@click.option("--no-rate-limit/--rate-limit", default=True,
              help="Disable/enable rate limiting (default: enabled)")
def scrape_all_incremental(export_csv: str = None, export_json: str = None, 
                         no_rate_limit: bool = True):
    """Scrape all configured sites in incremental mode (only newest articles)."""
    session_gen = get_session()
    db = next(session_gen)
    
    try:
        registry = SiteConfigRegistry(db)
        total_sites = len(registry.list_sites(active_only=True))
        
        if total_sites == 0:
            click.echo(click.style("No active sites configured.", fg="yellow"))
            return 1
        
        enable_rate_limiting = not no_rate_limit
        click.echo(click.style("\nIncremental scraping mode: Fresh articles from current pages", fg="green"))
        click.echo(f"Found {total_sites} active site(s) to scrape...")
        
        with ScraperEngine(enable_rate_limiting=enable_rate_limiting) as engine:
            results = engine.scrape_all_sites(
                db, active_only=True, mode="incremental", export_csv=export_csv, 
                export_json=export_json, enable_rate_limiting=enable_rate_limiting
            )
        
        click.echo(click.style("\nIncremental Scraping Summary:", fg="green"))
        total_articles_saved = sum(r.get("articles_saved", 0) for r in results)
        
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
@click.option("--no-rate-limit/--rate-limit", default=True,
              help="Disable/enable rate limiting (default: enabled)")
@click.option("--cutoff-date", "--date", "-d", type=str, default=None, 
              help="Date cutoff in YYYY-MM-DD format (backfill older articles before this date)")
@click.option("--max-pages", "-p", type=int, default=None,
              help="Maximum pages to go deep for each site")
def scrape_all_backfill(export_csv: str = None, export_json: str = None, 
                       no_rate_limit: bool = True, cutoff_date: str = None, 
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
        
        enable_rate_limiting = not no_rate_limit
        cutoff_datetime = None
        if cutoff_date:
            from datetime import datetime as dt
            try:
                cutoff_datetime = dt.strptime(cutoff_date, "%Y-%m-%d")
            except ValueError:
                click.echo(click.style(f"Invalid date format for --cutoff-date. Use YYYY-MM-DD.", fg="red"))
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
        
        # Store in database
        try:
            run = ValidationRun(
                site_name=site_config.name,
                url=site_config.url,
                status=result.status,
                field_completeness_score=result.field_completeness_score,
                sample_extracted_values=json.dumps(result.sample_extracted_values),
                failure_reason=result.failure_reason,
            )
            db.add(run)
            db.commit()
        except Exception:
            pass
        
        return 0
        
    except Exception as e:
        click.echo(click.style(f"Error validating site: {e}", fg="red"), err=True)
        return 1


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
        
        # Store results in database
        for result in results:
            run = ValidationRun(
                site_name=result.site_name,
                url=result.url,
                status=result.status,
                field_completeness_score=result.field_completeness_score,
                sample_extracted_values=json.dumps(result.sample_extracted_values),
                failure_reason=result.failure_reason,
            )
            db.add(run)
        
        db.commit()
        
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
    db = next(session_gen)
    
    try:
        # Count sites
        total_sites = db.query(SiteConfig).count()
        active_sites = db.query(SiteConfig).filter_by(active=True).count()
        
        # Count articles
        total_articles = db.query(ScrapedArticle).count()
        
        # Get latest scrape
        from datetime import datetime, timedelta
        recent_cutoff = datetime.now() - timedelta(days=7)
        recently_scraped = db.query(SiteConfig).filter(
            SiteConfig.last_scraped >= recent_cutoff
        ).count()
        
        click.echo(click.style("Database Statistics:", fg="cyan"))
        click.echo(f"  Total sites configured: {total_sites}")
        click.echo(f"  Active sites: {active_sites}")
        click.echo(f"  Total articles scraped: {total_articles:,}")
        click.echo(f"  Sites scraped in last 7 days: {recently_scraped}")
        
        # Show validation stats
        total_validations = db.query(ValidationRun).count()
        passed_validations = db.query(ValidationRun).filter(
            ValidationRun.status == "pass"
        ).count()
        click.echo(f"  Total validations: {total_validations}")
        click.echo(f"  Validated sites (pass): {passed_validations}")
        
    except Exception as e:
        click.echo(click.style(f"Error getting stats: {e}", fg="red"), err=True)
    finally:
        db.close()


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
        for field in ["article_selector", "title_selector", "date_selector", "content_selector"]:
            if template_data.get(field):
                setattr(site, field, template_data[field])
        
        db.commit()
        db.refresh(site)
        
        click.echo(click.style(f"Site added from '{template}' template! (ID: {site.id})", fg="green"))
        click.echo(f"  Name: {site.name}")
        click.echo(f"  URL: {site.url}")
        click.echo(f"  Pages: {pages}")
        click.echo(click.style("\nSelectors configured:", fg="cyan"))
        for field in ["article_selector", "title_selector", "date_selector", "content_selector"]:
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
                "category_url_pattern": site.category_url_pattern,
                "num_pages_to_scrape": site.num_pages_to_scrape,
                "active": site.active,
                "uses_javascript": site.uses_javascript,
                "selectors": {
                    "article_selector": site.article_selector,
                    "title_selector": site.title_selector,
                    "date_selector": site.date_selector,
                    "content_selector": site.content_selector,
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
                    click.echo(click.style(f"Skipping: no URL provided", fg="yellow"))
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
            
            click.echo(click.style(f"\nImport complete!", fg="green"))
            click.echo(f"  Imported: {imported_count}")
            click.echo(f"  Skipped (exists): {skipped_count}")
            
        except Exception as e:
            click.echo(click.style(f"Error importing sites: {e}", fg="red"), err=True)
            
    except FileNotFoundError:
        click.echo(click.style(f"File not found: {input_file}", fg="red"), err=True)
    except json.JSONDecodeError as e:
        click.echo(click.style(f"Invalid JSON: {e}", fg="red"), err=True)
    finally:
        db.close()


@cli.command("web")
@click.option("--host", "-h", default="0.0.0.0", help="Host to run the web server on")
@click.option("--port", "-p", default=5000, type=int, help="Port to run the web server on")
@click.option("--debug/--no-debug", default=False, help="Enable/disable debug mode")
def web_server(host: str, port: int, debug: bool):
    """Start the web interface server (Phase 4)."""
    try:
        from .app import create_app
        app = create_app()
        
        click.echo(click.style(f"Starting The Rise of the Phoenix Web Interface", fg="green"))
        click.echo(click.style(f"Web server running on: http://{host}:{port}", fg="cyan"))
        click.echo(click.style("Press Ctrl+C to stop.", fg="yellow"))
        click.echo("")
        
        app.run(host=host, port=port, debug=debug)
        
    except ImportError as e:
        click.echo(click.style(f"Error: Flask is not installed. Run 'pip install flask'", fg="red"), err=True)
        return 1
    except Exception as e:
        click.echo(click.style(f"Error starting web server: {e}", fg="red"), err=True)
        return 1


if __name__ == "__main__":
    cli()