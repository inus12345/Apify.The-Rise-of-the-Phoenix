# The Rise of the Phoenix

Configuration-driven news and blog scraper prepared for Apify Actor deployment.

## What it does

- Reads site metadata, selector maps, and category pagination state from JSON files in `news_scraper/data/catalog/`
- Accepts Apify input with site selection, max items, historic cutoff, proxy settings, and optional per-site category filters
- Scrapes using the fallback chain `scrapling -> pydoll -> selenium`
- Pushes successful article objects to the default Apify dataset
- Pushes failed scrape telemetry to a named dataset called `error-log`

## Input notes

- `sites_to_scrape` is a dropdown-backed multi-select of active catalog sites; leave it empty to scrape all active sites
- `categories_to_scrape` accepts manual entries in the format `Site Name|||https://category-url`
- `execution_mode` explicitly selects `current` or `historic`
- `historic_cutoff_date` is required for historic mode
- `no_items_limit` disables `max_items_per_site` when you want unlimited article collection
- `site_category_filters` is still supported as an advanced legacy override
- `proxy_config` uses Apify's proxy input editor and also accepts custom proxy URLs

## Output

- Default dataset: successful article records
- Named dataset `error-log`: failed URLs, failure type, and fallback telemetry
- Key-value store record `OUTPUT`: compact run summary
