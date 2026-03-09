
# Lightweight Web Scraper (No AWS)

Refactor of your Selenium/BeautifulSoup scraper to remove AWS and use CSV only.
Adds **strong dedup**, **resume on crash**, and a **URLs-only mode** — without changing your public API.

## Layout

```
WebScraperProject_Fixed/
├─ run_scraper.py
└─ Libraries/
   ├─ __init__.py
   ├─ webscraping_v2.py
   └─ my_logger.py
```

## Install

```
pip install pandas beautifulsoup4 selenium tqdm news-please lxml html5lib
```

## Usage

### Categories mode (default)
Each row describes a category or section to page through.

Required: `url` column. Optional: `name,pages_urls,num_pages,anti_robot,load_more_button,alt_source_domain`

```
python3 run_scraper.py -i input_jobs.csv -o results.csv --mode categories
```

### URLs mode
Scrape a flat list of article URLs directly.

Provide either a single `url` per row **or** a column `urls` with `| ; ,` or space-separated lists.

```
python3 run_scraper.py -i urls.csv -o results.csv --mode urls
```

### Crash-safe & dedup
- De-dup by `source_url_hash` using both the output CSV and a checkpoint file.
- Results are appended **incrementally** after each batch from inside the scraper (`out_csv_path`).
- If the process dies mid-run, re-run the same command: already-scraped URLs are skipped.

Useful flags:
```
--batch-size 40       # internal batching for scraping/extraction
--checkpoint state.json
--retries 2           # per-job retries
--test                # disable dedup against history (debugging)
```
