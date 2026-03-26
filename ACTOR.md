# The Rise of the Phoenix - Apify News Scraper

A high-scale **Apify news scraper** for **real-time and historical news extraction** across a large global publisher catalog.

Built for production data pipelines, monitoring, intelligence, media analysis, and research workflows.

## Why This Actor

- Scrapes current and historic articles from hundreds of tracked news sites
- Uses resilient fallback fetching: `scrapling -> pydoll -> selenium`
- Supports targeted site/category runs or broad catalog runs
- Returns structured article output plus structured scrape error telemetry
- Works with Apify Proxy for difficult sites

## Apify Input Reference

Use these exact input keys in your Apify run:

| Input field | Type | Required | Description |
| --- | --- | --- | --- |
| `sites_to_scrape` | `array[string]` | No | Select one or more active catalog sites. Leave empty to scrape all active sites. |
| `categories_to_scrape` | `array[string]` | No | Manual category override values in format `Site Name|||https://category-url`. |
| `execution_mode` | `string` | Yes | `current` or `historic`. |
| `historic_cutoff_date` | `string` | Required in historic mode | ISO timestamp cutoff, e.g. `2025-01-01T00:00:00Z`. |
| `max_items_per_site` | `integer` | No | Per-site cap when `no_items_limit` is `false`. |
| `no_items_limit` | `boolean` | No | If `true`, ignores `max_items_per_site`. |
| `proxy_config` | `object` | No | Apify proxy or custom proxy URLs. |
| `site_category_filters` | `array[object]` | No | Advanced legacy override for explicit site-to-category mapping. |

## Input Examples

### 1) Current scraping (selected sites)

```json
{
  "sites_to_scrape": ["Reuters", "Gulf News"],
  "execution_mode": "current",
  "max_items_per_site": 50,
  "no_items_limit": false,
  "proxy_config": {
    "useApifyProxy": true,
    "apifyProxyGroups": ["RESIDENTIAL"]
  }
}
```

### 2) Historic scraping (with cutoff)

```json
{
  "sites_to_scrape": ["The Punch"],
  "execution_mode": "historic",
  "historic_cutoff_date": "2025-01-01T00:00:00Z",
  "no_items_limit": true,
  "proxy_config": {
    "useApifyProxy": true
  }
}
```

### 3) Category-targeted scraping

```json
{
  "sites_to_scrape": ["Gulf News", "Reuters"],
  "categories_to_scrape": [
    "Gulf News|||https://gulfnews.com/business",
    "Reuters|||https://www.reuters.com/world/"
  ],
  "execution_mode": "current",
  "max_items_per_site": 100
}
```

## Output

This Actor writes:

- **Default dataset**: successful article records
- **Named dataset `error-log`**: failed URLs, tool fallback diagnostics, and extraction errors
- **Key-value store `OUTPUT`**: run summary (`successItemCount`, `errorItemCount`, mode, and site scope)
- **Apify Output tab links**: configured via `.actor/output_schema.json` for quick access to dataset items and run summary

## Best Practices

- Use `execution_mode: "current"` for daily monitoring and near-real-time ingestion.
- Use `execution_mode: "historic"` with `historic_cutoff_date` for backfills.
- Use `categories_to_scrape` for precise topical runs without editing catalog files.
- Keep `proxy_config.useApifyProxy` enabled for better stability on protected domains.

## Keywords

Apify news scraper, historical news scraping, web scraping API, article extraction, media monitoring, dataset automation, scalable scraping pipeline.
