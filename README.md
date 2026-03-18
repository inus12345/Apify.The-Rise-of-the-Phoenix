# The Rise of the Phoenix - News Scraper

A scalable news scraping system designed to handle 100s of websites with LLM-ready spider graph metadata for structure drift detection.

## Features

- **LLM-Ready Spider Graph Metadata**: Each site has extraction div selectors (title, body, date, author, images) stored in the database for automated structure verification
- **Batch Scalability**: YAML-based configuration makes adding new sites straightforward
- **Multi-Engine Scraping**: Supports scrapling, pydoll, and selenium with automatic fallback
- **Anti-Bot Handling**: Cloudflare, Akamai, and other anti-bot protection strategies configured per site

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Seed database with 16 sites (BBC News, Reuters, Guardian, CNN, NYT, etc.)
PYTHONPATH=. python source/scripts/seed_from_yaml.py

# Run scraper
python -m news_scraper --help
```

## Project Structure

```
├── data/                        # Database and exports
│   ├── scraping.db             # Main SQLite database (single file)
│   └── seeds/                  # Site configurations (YAML)
│       └── sites_config.yaml    # 16 news sites with full metadata
├── source/                     # Source code
│   ├── news_scraper/           # Main scraper package
│   │   ├── cli/                # CLI commands
│   │   ├── core/               # Core configuration and settings
│   │   ├── scraping/           # Scraping engine with fallback chain
│   │   ├── extraction/         # Article content extraction
│   │   ├── validation/         # LLM-assisted validation
│   │   └── export/             # JSON/CSV exports
│   └── scripts/                # Utility scripts
├── database/models.py          # Simplified SQLAlchemy models (4 core tables)
└── requirements.txt            # Python dependencies
```

## Database Schema (Simplified - 4 Core Tables)

### sites
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| name | TEXT | Site name (BBC News, Reuters, etc.) |
| url | TEXT | Base URL |
| country | TEXT | Country of origin |
| language | TEXT | ISO 639-1 code (en, de, fr) |
| description | TEXT | Brief description |
| article_title_selector | TEXT | CSS selector for article title |
| article_body_selector | TEXT | CSS selector for article body |
| publish_date_selector | TEXT | CSS selector for date |
| author_selector | TEXT | CSS selector for author |
| image_selector | TEXT | CSS selector for images |
| active | BOOLEAN | Whether site should be scraped |

### technologies
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| site_name | TEXT | Foreign key to sites.name |
| technology_name | TEXT | CDN/WAF name (Cloudflare, Fastly) |
| technology_type | TEXT | Category (cdn, waf, analytics) |

### categories  
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| site_name | TEXT | Foreign key to sites.name |
| category_name | TEXT | Category name (World, Business) |
| url | TEXT | Category URL |
| max_pages | INTEGER | Max pages for this category |

### scraped_articles
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| site_name | TEXT | Foreign key to sites.name |
| title | TEXT | Article title |
| url | TEXT | Full article URL |
| excerpt | TEXT | Article summary |
| article_body | TEXT | Main article content |
| publish_date | TIMESTAMP | Publication date |
| author | TEXT | Author name(s) |
| featured_image_url | TEXT | Featured image URL |
| word_count | INTEGER | Estimated word count |
| reading_time_minutes | INTEGER | Reading time estimate |

## Adding a New Site (Scale to 100s of Sites)

1. **Edit YAML config** (`data/seeds/sites_config.yaml`):
```yaml
sites:
  - name: Your News Site
    url: https://yournews.com/
    country: Country
    language: en
    description: Site description
    num_pages_to_scrape: 5
    
    # Extraction selectors (LLM drift detection)
    div_selectors:
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

2. **Run seed script**:
```bash
PYTHONPATH=. python source/scripts/seed_from_yaml.py
```

3. **Scraper automatically discovers** the new site when run.

## Configuration

Edit `source/news_scraper/config/scraper_config.yaml` for global settings:

- Rate limiting and delays
- Export paths (CSV, JSON)
- Validation settings  
- Database archival thresholds
- Logging level

## LLM Structure Drift Detection

Each site stores CSS selectors used for extraction. Periodically:

1. Scrape a sample article from each site
2. Check if selectors still work (structure unchanged)
3. Detect changes in site HTML structure
4. Update selectors or flag for manual review

## API Endpoints (Flask Web UI)

The scraper includes a Flask web interface at `source/news_scraper/web/`:

- `/sites` - List all configured sites
- `/sites/<name>/stats` - Scrape statistics per site
- `/stats/summary` - Overall scraping summary

## License

MIT License