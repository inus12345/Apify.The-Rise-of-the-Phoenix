# Split Database Layout

The scraper now supports two database backends:

## 1) Primary DB (source catalog + scrape ledger)
Stores:
- `site_configs`
- `site_technologies`
- `scrape_strategies`
- `article_url_ledger` (URL/hash dedupe + record counters, no article body)
- `catalog_change_log` (audit trail for site/category/strategy updates)
- `historical_scrape_progress` (historical/backfill chunk tracking)
- `scrape_runs`
- `scrape_logs`
- `llm_assessment_runs`
- `llm_assessment_lines`

## 2) Spider DB (category planning + spider graph)
Stores:
- `site_categories` (category URL + page count tracking)
- `category_crawl_state` (per-category page/link/emit coverage)
- `spider_diagrams`
- `spider_nodes`
- `spider_edges`
- `site_structure_snapshots` (normalized structure fingerprints)
- `site_structure_changes` (LLM review queue for structure drift)

## Environment Variables

```bash
PRIMARY_DATABASE_URL=sqlite:///./data/scraping.db
SPIDER_DATABASE_URL=sqlite:///./data/spider_tracking.db
```

If `PRIMARY_DATABASE_URL` is unset, the app falls back to `DATABASE_URL`.

## Initialize

```bash
python3 -m news_scraper.cli.commands init
```

## Sync website catalog and spider data

```bash
python3 -m news_scraper.cli.commands sync-config-sites --config news_scraper/config/sites_config.yaml
```

This writes site/source/scraper rows and catalog audit events to the Primary DB, and spider/category rows to the Spider DB.

## Chunked historical scraping (Apify-friendly)

For piece-wise historical runs, pass:
- `mode=historical`
- `start_page`
- `end_page` (optional)
- `cutoff_date` (`YYYY-MM-DD` or ISO datetime, optional)
- `chunk_id` (optional, recommended)
- `site_urls` / `site_names` / `countries` (optional targeting filters)

Each run updates `historical_scrape_progress` and `category_crawl_state` with:
- pages targeted/scraped
- article links found/new/skipped
- last processed page URL
- status (`running`, `partial`, `complete`, `failed`)

Apify actor defaults historical runs to a shallow scope for speed/cost:
- default `max_pages=5`
- cap `max_pages` at `10`
- set `allow_deep_historical=true` to disable the cap
