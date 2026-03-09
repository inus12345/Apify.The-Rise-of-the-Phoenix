# The Rise of the Phoenix - News Scraper Platform

A modular web scraping platform with clean architecture.

## Features

### Phase 1: Foundation MVP
- **SQLAlchemy ORM**: PostgreSQL-ready database schema (SQLite for MVP)
- **URL-based deduplication**: MD5 hash for efficient duplicate detection
- **Scrapling-style scraper**: HTTPX + BeautifulSoup for efficient static site scraping
- **CLI interface**: Easy command-line management with Click

### Phase 2: Enhanced Extraction
- **Custom selectors**: Per-site content extraction rules
- **Template-based configurations**: Predefined selector templates for popular platforms

### Phase 3: JavaScript Support
- **Selenium fallback**: Automatic fallback to headless browser for dynamic sites

### Phase 4: Web Interface (Current)
- **Flask web server**: Browser-based management interface
- **Full CRUD operations**: Add, edit, delete, and view site configurations
- **Scraping controls**: Start individual or bulk scraping jobs
- **Real-time statistics**: View database and scraping metrics

## Project Structure

```
news_scraper/
├── __init__.py              # Package initialization
├── __main__.py              # CLI entry point
├── requirements.txt         # Dependencies
├── README.md                # This file
├── data/                    # Database and logs (created at runtime)
│   └── scraping.db          # SQLite database
├── core/
│   ├── __init__.py
│   └── config.py            # Configuration management
├── database/
│   ├── __init__.py
│   ├── session.py           # Session management, engine, Base
│   └── models.py            # SiteConfig, ScrapedArticle models
├── scraping/
│   ├── __init__.py
│   ├── config_registry.py   # Site configuration registry
│   ├── engine.py            # Core scraper engine (Scrapling-style)
│   └── selenium_fallback.py # Selenium fallback for JavaScript sites
├── extraction/
│   ├── __init__.py
│   ├── article_extractor.py # Article content extraction with custom selectors
│   └── selector_parser.py   # CSS selector parsing utilities
├── export/
│   ├── __init__.py
│   ├── csv_export.py        # CSV export functionality
│   └── json_export.py       # JSON export functionality
├── policies/
│   ├── __init__.py
│   ├── rate_limiter.py      # Rate limiting for polite scraping
│   └── retry_policy.py      # Retry policy for failed requests
├── config_templates/
│   ├── __init__.py
│   └── templates.py         # Predefined site configuration templates
└── cli/
    ├── __init__.py
    └── commands.py          # CLI commands (add-site, list-sites, etc.)

Web Interface (Phase 4):
├── web/
│   ├── __init__.py
│   ├── app.py               # Flask application with routes
│   └── templates/           # HTML templates for web interface
│       ├── base.html        # Base template with navigation
│       ├── index.html       # Dashboard/home page
│       ├── sites.html       # Site listing page
│       ├── add_site.html    # Add new site form
│       ├── view_site.html   # View/edit site details
│       ├── edit_site.html   # Edit site configuration
│       └── stats.html       # Statistics page
```

## Database Models

### SiteConfig
Configuration for a website to scrape:
- `id`: Primary key
- `name`, `url`: Site identification
- `category_url_pattern`: Pattern for listing pages
- `num_pages_to_scrape`: Pages to process
- `active`, `uses_javascript`: Flags
- `created_at`, `updated_at`, `last_scraped`: Timestamps

### ScrapedArticle
A scraped article:
- `id`: Primary key
- `url`, `source_url_hash`: URL and MD5 hash (for deduplication)
- `title`, `body`, `description`: Article content
- `authors`, `date_publish`, `image_url`: Metadata
- `source_domain`, `language`: Source info
- `site_config_id`: Foreign key to SiteConfig

## Installation

```bash
pip install -r requirements.txt
```

## Usage

### Initialize Database

```bash
python -m news_scraper init
```

This creates the SQLite database at `data/scraping.db`.

### Add a Site

```bash
python -m news_scraper add-site --url "https://example.com/news" --name "Example News"
```

Optional parameters:
- `--pattern`: Category page pattern (e.g., `{url}?page={page}`)
- `--pages`: Number of pages to scrape (default: 1)
- `--inactive`: Mark site as inactive

### List Sites

```bash
python -m news_scraper list-sites
```

### Scrape a Single Site

```bash
python -m news_scraper scrape-site "https://example.com/news"
```

### Scrape All Sites

```bash
python -m news_scraper scrape-all [--limit 5]
```

### Seed Test Sites

```bash
python -m news_scraper seed --force
```

This adds 3 default test sites.

### Show Database Statistics

```bash
python -m news_scraper stats
```

## Key Technical Decisions

1. **SQLAlchemy ORM**: Provides database abstraction for PostgreSQL readiness while using SQLite for MVP simplicity.
2. **URL-based deduplication**: MD5 hash of URLs ensures articles aren't duplicated across scrapes.
3. **HTTPX + BeautifulSoup**: Lightweight scraper engine that's fast and reliable for static sites (Scrapling-style).
4. **Selenium fallback**: Planned for Phase 4 for JavaScript-heavy sites.
5. **Clean architecture**: Modular design with separation of concerns between database, scraping logic, and CLI.

## Configuration

Configuration is managed via `core/config.py` using Pydantic Settings:
- Database URL (defaults to SQLite)
- Batch size, timeout, retry settings
- User agent string
- Logging configuration

## Next Steps (Phase 2+)

1. Enhanced content extraction with custom selectors
2. Selenium fallback for JavaScript sites
3. Rate limiting and polite scraping
4. Web interface for management
5. Export to various formats (JSON, CSV, etc.)
6. Email notifications for completed scrapes