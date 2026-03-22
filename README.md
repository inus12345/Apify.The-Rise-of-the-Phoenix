# The Rise of the Phoenix - News Scraper

A configuration-driven news and blog scraper built for Apify-style execution. The runtime uses JSON catalogs and selector maps, supports `Scrapling -> Pydoll -> Selenium` fallback, and writes JSON datasets only. No SQL database is used by the scraper runtime.

## Features

- **JSON-first architecture**: Site catalog, selector map, pagination tracker, and outputs are all JSON-backed and schema-validated
- **Apify-style input**: The runtime consumes an `INPUT.json` with site filtering, max item controls, proxy settings, and historic cutoff dates
- **Dual execution modes**: Current scraping for front pages / shallow categories and historic scraping for deeper backfills
- **Fallback scraping stack**: `Scrapling` first, `Pydoll` second, `Selenium` last
- **Operational telemetry**: Successful backends update per-site preference history for future runs
- **Verification utility**: `verify_sites.py` checks selector drift, malformed data, and likely blocking changes

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Review the sample JSON configs:
# - news_scraper/data/catalog/site_catalog.json
# - news_scraper/data/catalog/selector_map.json
# - news_scraper/data/catalog/category_pagination_tracker.json

# Run the scraper (creates INPUT.json if missing)
python -m news_scraper

# Verify selector health across sites
python verify_sites.py
```

## Project Structure

```
├── news_scraper/
│   ├── config/                        # Pydantic models and JSON helpers
│   ├── data/catalog/                  # Site catalog, selector map, pagination tracker
│   ├── data/exports/                  # Success + error datasets
│   └── scraping/                      # Fetching, extraction, fallback, orchestration
├── verify_sites.py                    # Selector verification utility
├── requirements.txt                   # Python dependencies
└── README.md                          # This file
```

## Configuration Files

- `news_scraper/data/catalog/site_catalog.json`
  Tracks site metadata, preferred scraping backend, and backend success history.
- `news_scraper/data/catalog/selector_map.json`
  Stores per-site selector rules for article links and normalized fields.
- `news_scraper/data/catalog/category_pagination_tracker.json`
  Tracks category URLs, known page counts, and resume positions for historic crawls.
- `INPUT.json`
  Runtime input with `sites_to_scrape`, `max_items_per_site`, `historic_cutoff_date`, and `proxy_config`.

The previous SQLite-based configuration path has been removed. Edit the JSON catalog files directly.

The Flask UI is self-contained and does not use the legacy Jinja template set that existed in earlier versions.

## Running Scrapes

```bash
# Current mode: omit historic_cutoff_date in INPUT.json
python -m news_scraper

# Historic mode: include historic_cutoff_date in INPUT.json
python -m news_scraper --input ./INPUT.json

# Verify selectors without running a full scrape
python verify_sites.py --sites "example-news.com"
```

## JSON Output Structure

Each successful scrape item includes normalized fields such as:
```json
{
  "site_name": "example-news.com",
  "article_title": "Breaking News",
  "article_body": "Full article content...",
  "article_url": "https://example.com/article",
  "date_published": "2026-03-18T10:00:00Z",
  "url_hash": "7d0e1f...",
  "scraped_at": "2026-03-18T10:05:00Z",
  "scraping_tool": "scrapling",
  "execution_mode": "current"
}
```

## License

MIT License
