# The Rise of the Phoenix

Configuration-driven news and blog scraper prepared for Apify Actor deployment.

## What it does

- Reads site metadata, selector maps, and category pagination state from JSON files in `news_scraper/data/catalog/`
- Accepts Apify input with site selection, max items, historic cutoff, proxy settings, and optional per-site category filters
- Scrapes using the fallback chain `scrapling -> pydoll -> selenium`
- Pushes successful article objects to the default Apify dataset
- Pushes failed scrape telemetry to a named dataset called `error-log`

## Input notes

- Leave `sites_to_scrape` empty to scrape all active sites in the catalog
- `historic_cutoff_date` switches the run into historic mode
- `site_category_filters` is optional and lets you limit individual sites to specific tracked category URLs
- `proxy_config` uses Apify's proxy input editor and also accepts custom proxy URLs

## Output

- Default dataset: successful article records
- Named dataset `error-log`: failed URLs, failure type, and fallback telemetry
- Key-value store record `OUTPUT`: compact run summary
