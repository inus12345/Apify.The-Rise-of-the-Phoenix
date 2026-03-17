# The Rise of the Phoenix - News Scraper Platform

A modular web scraping platform with clean architecture.

## Features

### Phase 1: Foundation MVP
- **SQLAlchemy ORM**: Split-database architecture (local SQLite by default)
- **URL-based deduplication**: MD5 hash for efficient duplicate detection
- **Preferred scraper stack**: Scrapling first, Pydoll second, Selenium as last resort
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

### Phase 5: Metadata Governance (New)
- **Site metadata model**: Country/language/server/domain/technology persistence
- **Spider graph model**: Versioned node/edge crawl maps per site
- **Structure drift tracking**: Snapshot/hash + change events for LLM review in Spider DB
- **Scrape strategy model**: Per-site engine + anti-blocking strategy
- **LLM line-by-line review**: Structured assessment runs and field-level updates
- **Config-driven scraping pipeline**: Sync thousands of sites from YAML and scrape in `current` or `historical` mode
- **Historical progress tracking**: `historical_scrape_progress` table for chunked backfill coverage/state

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
│   └── models.py            # Source catalog + crawl-state models
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

### ArticleUrlLedger
URL-level scrape ledger (no article body storage in SQL):
- `site_config_id`, `source_url_hash`, `article_url`: Deduplication identity
- `first_seen_at`, `last_seen_at`: Discovery tracking
- `first_publish_at`, `last_publish_at`: Publish-date tracking
- `seen_count`, `total_records_emitted`: Historic/current progress counters

### CategoryCrawlState
Category-level crawl coverage:
- `site_config_id`, `site_category_id`, `category_url`
- `last_page_scraped`, `max_page_seen`, `last_page_url`
- `total_listing_pages_scraped`, `total_links_discovered`, `total_records_emitted`
- `last_mode`, `last_chunk_id`, `last_scraped_at`

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Local Quick Start

1. Initialize databases:

```bash
python -m news_scraper init
```

2. Optional: run environment diagnostics (DB + scraper engines):

```bash
python -m news_scraper doctor
```

3. Load the site catalog into SQL:

```bash
python -m news_scraper sync-config-sites --config news_scraper/config/sites_config.yaml
```

4. Run a small live scrape and export JSON:

```bash
python -m news_scraper scrape-config \
  --mode current \
  --story-batch-size 200 \
  --output-json ./data/exports/local_smoke_run.json
```

## Usage

### Initialize Database

```bash
python -m news_scraper init
```

By default this creates:
- primary DB: `data/scraping.db`
- spider DB: `data/spider_tracking.db`

This repo is configured for local JSON-first runs. You do not need PostgreSQL to run the actor flow locally.

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

### Quick Scrape (JSON Test Mode)

Fast single-URL testing command that does not require adding a site first.

Auto mode (detect article vs listing):
```bash
python -m news_scraper quick-scrape \
  "https://www.reuters.com/world/" \
  --max-articles 2 \
  --output-json ./data/exports/quick_test_reuters.json
```

Force article mode:
```bash
python -m news_scraper quick-scrape \
  "https://www.bbc.com/news/world-us-canada-00000000" \
  --mode article \
  --output-json ./data/exports/quick_test_article.json
```

Force listing mode + engine preference:
```bash
python -m news_scraper quick-scrape \
  "https://www.aljazeera.com/news/" \
  --mode listing \
  --engine scrapling \
  --max-articles 3 \
  --output-json ./data/exports/quick_test_listing.json
```

Quick-scrape output JSON contains:
- `run_metadata`: mode, engine, candidate counts, timing info
- `records`: extracted article payloads + attached site metadata (country/language/domain when known)

### Scrape All Sites

```bash
python -m news_scraper scrape-all [--limit 5]
```

### Sync Sites From Config File

```bash
python -m news_scraper sync-config-sites --config news_scraper/config/sites_config.yaml
```

### Config-Driven Scrape Modes

Current mode (fresh pages):
```bash
python -m news_scraper scrape-config \
  --mode current \
  --story-batch-size 200 \
  --output-json ./data/exports/current_batch.json
```

Historical mode (deep/backfill):
```bash
python -m news_scraper scrape-config \
  --mode historical \
  --story-batch-size 200 \
  --max-pages 20 \
  --cutoff-date 2024-01-01 \
  --output-json ./data/exports/historical_batch.json
```

Country/site targeting (for large catalogs):
```bash
python -m news_scraper scrape-config \
  --mode current \
  --story-batch-size 200 \
  --country "United States" \
  --country "United Kingdom" \
  --site-name "Reuters"
```

Structured JSON output includes:
- article fields (`title`, `body`, `date_publish`, `scrape_date`, `extra_links`, `image_links`, etc.)
- nested `site` metadata from SQL (`name`, `domain`, `country`, `language`, server fields, full scrape strategy, detected technologies)
- a run batch cap (`story_batch_size`) so each run exports at most the configured number of stories (default `200`)

The same config structure also works for non-news websites (blogs, docs, ecommerce, forums) by defining the site URL, categories, and scrape strategy.

### Apify-Ready Entrypoint

```bash
python -m news_scraper.apify_actor
```

Input can be passed via:
- `APIFY_INPUT` (JSON string), or
- `APIFY_INPUT_FILE` (JSON file path, defaults to `INPUT.json`)

Actor packaging files included in repo:
- `.actor/actor.json`
- `.actor/input_schema.json`
- `Dockerfile`

Apify input fields for large-scale targeting:
- `mode`: `current` or `historic` (`historical` also supported)
- `story_batch_size`: max stories per run (default `200`)
- `site_urls`: list or comma-separated string
- `site_names`: list or comma-separated string
- `websites`: mixed list of URLs and names (auto-split)
- `countries`: list or comma-separated string
- `limit`, `offset`: batch controls
- `default_site_limit`, `enforce_safe_site_limit`: safety guard for broad unfiltered runs
- `start_page`, `end_page`, `chunk_id`, `cutoff_date`
- `push_to_dataset`: push story records to default Apify dataset (default `true`)
- `include_records_in_output`: keep or omit full `records` array in `OUTPUT.json`
- `apify_dataset_chunk_size`, `apify_dataset_timeout_seconds`, `apify_dataset_clean_start`

Example:
```json
{
  "mode": "current",
  "story_batch_size": 200,
  "countries": ["United States", "United Kingdom"],
  "site_names": ["Reuters", "BBC News"],
  "limit": 25,
  "offset": 0
}
```

Run actor locally with an input file:

```bash
cat > INPUT.json << 'JSON'
{
  "mode": "current",
  "story_batch_size": 200,
  "countries": ["Qatar", "United Arab Emirates", "Saudi Arabia"],
  "output_json": "./data/exports/apify_local_batch.json"
}
JSON

python -m news_scraper.apify_actor
```

Actor output (`OUTPUT.json` by default) contains:
- `run_metadata`
- `record_count`
- `records` (each story with attached source site metadata)

When running in Apify with `APIFY_TOKEN` + `APIFY_DEFAULT_DATASET_ID`, records are also pushed to the dataset API in chunks.
Delivery status is recorded under `run_metadata.apify_dataset_delivery`.

For cost/speed safety on Apify, historical mode is intentionally shallow by default:
- if `max_pages` is omitted, actor uses `5`
- if `max_pages` is provided, actor caps it at `10`
- set `allow_deep_historical=true` to disable this cap

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

1. **SQLAlchemy ORM**: Supports split persistence: primary DB (site/source/scraper/articles) and spider DB (categories/spider graph).
2. **URL-based deduplication**: MD5 hash of URLs ensures articles aren't duplicated across scrapes.
3. **Tiered fetch engine**: `scrapling -> pydoll -> selenium` with parser-level BeautifulSoup extraction.
4. **Site strategy in SQL**: Every site stores engine choice, fallback chain, parser, and spider map hints.
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

## Metadata/Spider/LLM Design

See:
- `news_scraper/docs/metadata_strategy_and_spider_model.md`
