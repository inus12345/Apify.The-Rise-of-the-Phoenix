# The Rise of the Phoenix - News Scraper

A scalable news scraping system designed for 100s of websites with LLM-ready spider graph metadata for structure drift detection. JSON output only (ETL-friendly) - no SQLite storage for scraped articles.

## Features

- **LLM-Ready Spider Graph Metadata**: Each site has extraction div selectors (title, body, date, author, images) stored for automated structure verification
- **Batch Scalability**: YAML-based configuration makes adding new sites straightforward  
- **Multi-Engine Scraping**: Supports scrapling, pydoll, and selenium with automatic fallback
- **Anti-Bot Handling**: Cloudflare, Akamai, and other anti-bot protection strategies configured per site
- **ETL-Friendly**: Only JSON output - scraped articles stored externally (PostgreSQL, BigQuery, etc.)

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Seed database with 16 news sites (BBC, Reuters, Guardian, CNN, NYT, etc.)
PYTHONPATH=. python source/scripts/seed_from_yaml.py

# Run Flask web interface:
python -m news_scraper.web --host 0.0.0.0 --port 5000

# Or use CLI:
python -m news_scraper scrape-config --config=data/seeds/sites_config.yaml --mode=current --output-json=./data/exports/scrape.json
```

## Project Structure

```
├── data/                              # Database and exports folder
│   ├── scraping.db                    # SQLite site configuration DB only
│   ├── seeds/                         # Site configurations (YAML)
│   │   └── sites_config.yaml          # 16 news sites with div_selectors
│   └── exports/                       # JSON scrape output files
├── source/                            # Source code
│   ├── news_scraper/                  # Main scraper package
│   │   ├── cli/                       # CLI commands  
│   │   ├── scraping/                  # Scraping engine with fallback chain
│   │   ├── extraction/                # Article content extraction
│   │   └── web/                       # Flask web interface
│   └── scripts/
├── database/models.py                 # SQLAlchemy models (4 core tables)  
├── requirements.txt                   # Python dependencies
└── README.md                         # This file
```

## Database Schema (Simplified - 4 Core Tables Only)

| Table | Purpose |
|-------|---------|
| **sites** | Site configs with div_selectors for LLM drift detection |
| **technologies** | CDN/WAF stack per site |
| **categories** | Category pages with pagination settings |
| **scraped_articles** | Extracted content (deprecated - JSON-only now) |

## Adding a New Site (Scale to 100s of Sites)

**Step 1:** Edit `data/seeds/sites_config.yaml`:

```yaml
sites:
  - name: Your News Site
    url: https://yournews.com/
    country: Country
    language: en
    description: Brief site description
    num_pages_to_scrape: 5
    
    div_selectors:  # Required for LLM drift detection
      article_title: "h1.article-title"
      article_body: ".article-content p:not(:first-of-type)"
      publish_date: ".published-date" 
      author: ".author-name"
      
    technologies:
      - name: Cloudflare
        type: cdn
    
    categories:
      - name: World News
        url: https://yournews.com/world
        max_pages: 4
```

**Step 2:** Run seed script:
```bash
PYTHONPATH=. python source/scripts/seed_from_yaml.py
```

**Step 3:** Scraper automatically discovers the new site when run.

## Running Scrapes

### Via Flask Web Interface

1. Start the web server:
   ```bash
   python -m news_scraper.web --host 0.0.0.0 --port 5000
   ```

2. Open browser to http://localhost:5000
3. Select site from dropdown, choose mode (current/historic), set limits
4. Click "Scrape & Save JSON"
5. Check `data/exports/` for output

### Via CLI

```bash
# Current pages only
python -m news_scraper scrape-config \
    --config=data/seeds/sites_config.yaml \
    --mode=current \
    --output-json=./data/exports/test_current.json

# Historic (deep backfill)  
python -m news_scraper scrape-config \
    --config=data/seeds/sites_config.yaml \
    --mode=historic \
    --cutoff-date 2024-01-01 \
    --max-pages 20 \
    --output-json=./data/exports/backfill.json
```

## JSON Output Structure

Each scraped article includes:
```json
{
  "article": {
    "title": "Breaking News",
    "body": "Full article content...",
    "url": "https://example.com/article",
    "publish_date": "2026-03-18T10:00:00"
  },
  "scrape": {
    "engine_used": "scrapling", 
    "scrape_date": "2026-03-18T10:05:00"
  }
}
```

## ETL Integration

JSON output can be piped to any ETL process:

```bash
# Export to PostgreSQL via COPY command
python -m news_scraper scrape-config \
    --config=data/seeds/sites_config.yaml \
    --mode=current \
    --output-json=./data/exports/articles.json
```

Then in your SQL:
```sql
COPY articles (title, body, url) FROM '/path/to/articles.json' WITH (FORMAT JSON);
```

## LLM Structure Drift Detection

Each site stores CSS selectors used for extraction. The system can periodically:
1. Scrape a sample article from each site  
2. Check if selectors still work (structure unchanged)
3. Detect changes in site HTML structure
4. Flag sites needing selector updates

## License

MIT License