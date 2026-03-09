#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
from pathlib import Path
from typing import List, Set
import pandas as pd

# ✅ This import is correct. It imports FROM webscraping_v2; webscraping_v2 must NOT import back.
from Libraries.webscraping_v2 import webscrape, processing
from Libraries.my_logger import setup_logger

def _parse_bool(val):
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    return s in {"1", "true", "yes", "y", "on"}

def _parse_pages(val):
    if isinstance(val, list):
        return val
    s = str(val or "").strip()
    if not s:
        return []
    import re
    parts = re.split(r"[|;, \t\r\n]+", s)
    return [p for p in (x.strip() for x in parts) if p]

def _flatten_urls_column(df: pd.DataFrame) -> List[str]:
    urls: List[str] = []
    if "urls" in df.columns:
        for cell in df["urls"].fillna("").astype(str).tolist():
            urls.extend([u.strip() for u in _parse_pages(cell)])
    elif "url" in df.columns:
        urls = [str(u).strip() for u in df["url"].tolist() if str(u).strip()]
    return [u for u in urls if u]

def _load_seen_hashes_exact(out_csv_path: Path, logger) -> Set[str]:
    seen: Set[str] = set()
    if not out_csv_path.exists():
        return seen
    try:
        s = pd.read_csv(out_csv_path, usecols=["source_url_hash"], dtype=str)["source_url_hash"]
        vals = s.dropna().astype(str).str.strip()
        seen.update(v for v in vals.tolist() if v)
        logger.info(f"[Runner] Loaded {len(seen)} hashes from 'source_url_hash'.")
    except ValueError as e:
        logger.warning(f"[Runner] 'source_url_hash' not found in {out_csv_path}: {e}")
    except Exception as e:
        logger.warning(f"[Runner] Could not load seen hashes from {out_csv_path}: {e}")
    return seen

def main():
    ap = argparse.ArgumentParser(
        description="Run the website scraper on a CSV of inputs and write results to a CSV (no AWS)."
    )
    ap.add_argument("--input", "-i", required=True,
                    help="Input CSV. For --mode=categories it must have at least 'url'. For --mode=urls it may have 'url' or 'urls'.")
    ap.add_argument("--output", "-o", required=True,
                    help="Output CSV path to append results into (created if missing).")
    ap.add_argument("--mode", choices=["categories", "urls"], default="categories",
                    help="Scrape category pages (default) or a flat list of URLs.")
    ap.add_argument("--batch-size", type=int, default=40, help="Internal batch size for scraping.")
    ap.add_argument("--checkpoint", default=".scraper_state.json",
                    help="Where to persist seen URL hashes and last run metadata.")
    ap.add_argument("--retries", type=int, default=2, help="Per-job retry count on failures.")
    ap.add_argument("--test", action="store_true",
                    help="Test mode: do not load existing hashes from output CSV (still dedups within the run).")
    args = ap.parse_args()

    logger = setup_logger("Runner")

    in_path = Path(args.input)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not in_path.exists():
        logger.error(f"Input CSV not found: {in_path}")
        return 2

    df_in = pd.read_csv(in_path)
    if args.mode == "categories" and "url" not in df_in.columns:
        logger.error("Input CSV must contain a 'url' column for --mode=categories.")
        return 2

    # Load checkpoint
    state = {"seen": []}
    ck = Path(args.checkpoint)
    if ck.exists():
        try:
            state = json.loads(ck.read_text())
        except Exception as e:
            logger.warning(f"Could not read checkpoint {ck}: {e}")

    # Build seen set ONLY from the output CSV (ignore checkpoint lifetime state)
    local_seen: Set[str] = set()
    if out_path.exists() and not args.test:
        prev_hashes = _load_seen_hashes_exact(out_path, logger)
        local_seen |= prev_hashes
        logger.info(f"De-duping only against output CSV: {len(local_seen)} hashes.")

    def save_state():
        try:
            ck.write_text(json.dumps({"seen": sorted(local_seen)}, indent=2))
        except Exception as e:
            logger.warning(f"Failed to write checkpoint {ck}: {e}")

    # Common config for scraper
    base_cfg = {
        "webscraper": {"multiprocessing": 2},
        "batch_size": args.batch_size,
        "local_seen_hashes": local_seen,
        "out_csv_path": str(out_path),
    }

    # -------- URLs mode (direct list) --------
    if args.mode == "urls":
        urls = _flatten_urls_column(df_in)
        if not urls:
            logger.info("No URLs to scrape.")
            return 0
        logger.info(f"Scraping {len(urls)} direct URLs.")
        for i in range(0, len(urls), 100):
            chunk = urls[i:i + 100]
            logger.info(f"Chunk {i+1}..{i+len(chunk)}")
            attempt = 0
            while attempt <= args.retries:
                try:
                    _ = webscrape(
                        name="direct_urls",
                        url=chunk[0],
                        pages_urls=[],
                        num_pages=1,
                        anti_robot=False,
                        load_more_button="",
                        alt_source_domain="",
                        config_data={**base_cfg, "direct_links": chunk},
                        test_scraper=args.test,
                    )
                    break
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    attempt += 1
                    logger.warning(f"Error in direct chunk {i}: {e} (attempt {attempt}/{args.retries})")
                    if attempt > args.retries:
                        break
            try:
                recent = _load_seen_hashes_exact(out_path, logger)
                local_seen |= recent
                save_state()
            except Exception:
                pass
        logger.info("Done.")
        return 0

    # -------- Categories mode --------
    for idx, row in df_in.iterrows():
        name = row.get("name") or ""
        url = row["url"]
        pages_urls = _parse_pages(row.get("pages_urls", ""))
        num_pages = int(row.get("num_pages", 1) or 1)
        anti_robot = _parse_bool(row.get("anti_robot", False))
        load_more_button = row.get("load_more_button", "")
        alt_source_domain = row.get("alt_source_domain", "")

        logger.info(f"[{idx+1}/{len(df_in)}] {url}")
        attempt = 0
        while attempt <= args.retries:
            try:
                _ = webscrape(
                    name=name or url,
                    url=url,
                    pages_urls=pages_urls,
                    num_pages=num_pages,
                    anti_robot=anti_robot,
                    load_more_button=load_more_button,
                    alt_source_domain=alt_source_domain,
                    config_data=base_cfg,
                    test_scraper=args.test,
                )
                break
            except KeyboardInterrupt:
                raise
            except Exception as e:
                attempt += 1
                logger.warning(f"Error scraping {url}: {e} (attempt {attempt}/{args.retries})")
                if attempt > args.retries:
                    break

        try:
            recent = _load_seen_hashes_exact(out_path, logger)
            local_seen |= recent
        except Exception:
            pass
        save_state()

    logger.info("All jobs complete.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
