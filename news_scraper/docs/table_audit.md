# Table Audit And Split Rationale

This project intentionally uses two databases:

- **Primary DB:** source metadata, scraper strategy, and URL-level scrape ledger.
- **Spider DB:** category/spider planning metadata and structure-governance data for LLM review.

## Primary DB (source + ledger)

| Table | Needed | Reason |
|---|---|---|
| `site_configs` | Yes | Canonical source identity and extraction defaults. |
| `site_technologies` | Yes | Per-site detected tech stack for strategy and analytics. |
| `scrape_strategies` | Yes | Runtime fetch/parser strategy and anti-blocking guidance. |
| `article_url_ledger` | Yes | URL/hash dedupe + historical/current coverage counters without storing article body payload. |
| `catalog_change_log` | Yes | Audit trail for site/category/strategy mutations (manual/config/LLM). |
| `scrape_runs` | Yes | Run-level metrics and operational observability. |
| `scrape_logs` | Yes | Event/error traceability for scraper ops. |
| `historical_scrape_progress` | Yes | Chunked backfill tracking for Apify actor slices. |
| `llm_assessment_runs` | Yes | Line-by-line governance run metadata. |
| `llm_assessment_lines` | Yes | Field-level recommended updates and audit trail. |

## Spider DB (planning + structure governance)

| Table | Needed | Reason |
|---|---|---|
| `site_categories` | Yes | Category/page traversal source-of-truth. |
| `category_crawl_state` | Yes | Per-category crawl coverage and pagination checkpoints. |
| `spider_diagrams` | Yes | Versioned crawl map per site. |
| `spider_nodes` | Yes | Fine-grained extraction/traversal steps. |
| `spider_edges` | Yes | Traversal relationships and ordering. |
| `site_structure_snapshots` | Yes | Canonical structure fingerprints over time. |
| `site_structure_changes` | Yes | Drift events for LLM review/remediation workflow. |

## Why this split works

- **Payload isolation:** article/story payloads are emitted as JSON, not stored in SQL.
- **Planner isolation:** structure/versioning/LLM drift artifacts stay in Spider DB.
- **Operational clarity:** actor and scraper choose targets from SQL metadata, while story data is returned/output as JSON batches.

## Future optional tables

- `scrape_job_queue` in Spider DB for explicit distributed orchestration state.
- `output_manifest` in Primary DB if you later need durable references to exported JSON artifacts.
