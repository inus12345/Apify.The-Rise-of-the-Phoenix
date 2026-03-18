# Seed database from YAML configuration - The Rise of the Phoenix
# Simplified: Single SQLite database with 4 core tables + additional useful selectors

import os
import sys
from pathlib import Path
import sqlite3
import yaml

# ROOT_DIR should be the project root (where news_scraper and data folders are)
ROOT_DIR = Path(__file__).parent.parent.parent


def main():
    """Main entry point"""
    config_path = ROOT_DIR / "data" / "seeds" / "sites_config.yaml"
    
    print("=" * 60)
    print("Loading Sites from YAML Configuration")
    print("=" * 60)
    
    # Load configuration
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    sites = config['sites']
    print(f"\nFound {len(sites)} sites in configuration:")
    for i, site in enumerate(sites, 1):
        name = site.get('name', '')
        url = site.get('url', '')
        print(f"  {i}. {name:35} | {url}")
    
    # Connect to SQLite database at project root: data/scraping.db
    db_path = ROOT_DIR / "data" / "scraping.db"
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    print(f"\nDatabase file: {db_path}")
    
    # Create 4 core tables with expanded div_selectors
    print("\nCreating simplified database schema (4 core tables)...")
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            url TEXT NOT NULL,
            country TEXT,
            language TEXT,
            description TEXT,
            active BOOLEAN DEFAULT 1,
            num_pages_to_scrape INTEGER DEFAULT 3,
            
            -- Core article content selectors
            article_title_selector TEXT,
            article_body_selector TEXT,
            
            -- Metadata selectors (publication date, author, etc.)
            publish_date_selector TEXT,
            author_selector TEXT,
            
            -- Media selectors  
            featured_image_selector TEXT,
            main_image_selector TEXT,
            
            -- Additional useful selectors for metadata extraction
            meta_description_selector TEXT,      -- Article description/summary
            reading_time_selector TEXT,           -- Reading time indicator
            word_count_selector TEXT,             -- Word count or reading estimate
            source_credit_selector TEXT,          -- Source/attribution credit
            tags_selector TEXT,                   -- Article tags/categories links
            category_links_selector TEXT,         -- Navigation category links
            
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
    print("  - sites table (with core article + metadata selectors)")
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS technologies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_name TEXT NOT NULL,
            technology_name TEXT NOT NULL,
            technology_type TEXT NOT NULL DEFAULT 'cdn',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (site_name) REFERENCES sites(name) ON DELETE CASCADE
        )""")
    print("  - technologies table")
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_name TEXT NOT NULL,
            category_name TEXT NOT NULL,
            url TEXT NOT NULL,
            max_pages INTEGER DEFAULT 3,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (site_name) REFERENCES sites(name) ON DELETE CASCADE,
            UNIQUE(site_name, category_name)
        )""")
    print("  - categories table")
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scraped_articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_name TEXT NOT NULL,
            title TEXT,
            url TEXT NOT NULL,
            excerpt TEXT,
            
            -- Extracted article content using div selectors
            article_body TEXT,
            publish_date TIMESTAMP,
            author TEXT,
            
            -- Media
            featured_image_url TEXT,
            main_image_url TEXT,
            
            -- Metadata (extracted from site during scraping)
            word_count INTEGER DEFAULT 0,
            reading_time_minutes INTEGER DEFAULT 0,
            meta_description TEXT,
            
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            source_url TEXT,
            
            FOREIGN KEY (site_name) REFERENCES sites(name) ON DELETE SET NULL
        )""")
    print("  - scraped_articles table")
    
    # Create indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sites_active ON sites(active)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_categories_site ON categories(site_name)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_articles_site ON scraped_articles(site_name)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_articles_title ON scraped_articles(title)")
    
    conn.commit()
    print("\n4 core tables created!")
    
    # Insert all sites with div_selectors
    added_count = 0
    
    print("\nInserting site configurations with div_selectors...")
    for site in sites:
        name = site.get('name', '')
        url = site.get('url', '')
        
        # Extract ALL available selectors from YAML structure
        div_selectors = site.get('div_selectors', {}) or {}
        
        # Core article selectors (required)
        title_sel = str(div_selectors.get('article_title', ''))
        body_sel = str(div_selectors.get('article_body', ''))
        
        # Metadata selectors  
        date_sel = str(div_selectors.get('publish_date', ''))
        author_sel = str(div_selectors.get('author', ''))
        
        # Media selectors (may not exist on all sites)
        img_sel = str(div_selectors.get('image', ''))
        
        # Additional useful selectors (extract if available, else NULL/empty)
        meta_desc_sel = str(div_selectors.get('meta_description', ''))
        reading_time_sel = str(div_selectors.get('reading_time', ''))
        word_count_sel = str(div_selectors.get('word_count', ''))
        source_credit_sel = str(div_selectors.get('source_credit', ''))
        tags_sel = str(div_selectors.get('tags', ''))
        category_links_sel = str(div_selectors.get('category_links', ''))
        
        # Insert site config with all fields
        cursor.execute("""
            INSERT OR REPLACE INTO sites 
                (name, url, country, language, description, num_pages_to_scrape,
                 article_title_selector, article_body_selector,
                 publish_date_selector, author_selector,
                 featured_image_selector, main_image_selector,
                 meta_description_selector, reading_time_selector,
                 word_count_selector, source_credit_selector,
                 tags_selector, category_links_selector)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            name, url, site.get('country'), site.get('language'), 
            site.get('description'), site.get('num_pages_to_scrape', 3),
            title_sel, body_sel, date_sel, author_sel, img_sel, '',
            meta_desc_sel, reading_time_sel, word_count_sel, source_credit_sel, tags_sel, category_links_sel,
        ))
        
        added_count += 1
        
        # Insert technologies as separate rows
        tech_list = site.get('technologies', []) or []
        for tech in tech_list:
            if isinstance(tech, dict):
                tech_name = tech.get('name', '')
                tech_type = tech.get('type', 'cdn')
                cursor.execute("""
                    INSERT OR IGNORE INTO technologies (site_name, technology_name, technology_type)
                    VALUES (?, ?, ?)
                """, (name, tech_name, tech_type))
    
    # Insert categories as separate rows
    for site in sites:
        name = site.get('name', '')
        categories = site.get('categories', []) or []
        
        for cat in categories:
            if isinstance(cat, dict):
                cat_name = cat.get('name', '')
                cat_url = cat.get('url', '')
                max_pages = cat.get('max_pages', 3)
                cursor.execute("""
                    INSERT OR IGNORE INTO categories (site_name, category_name, url, max_pages)
                    VALUES (?, ?, ?, ?)
                """, (name, cat_name, cat_url, max_pages))
    
    conn.commit()
    print(f"\nInserted {added_count} sites with div_selectors!")
    
    # Verify by querying the database
    cursor.execute("SELECT COUNT(*) FROM sites")
    count = cursor.fetchone()[0]
    print(f"Total sites in database: {count}")
    
    # Check for sites with empty core selectors (title/body required)
    cursor.execute("""
        SELECT name, 
               COALESCE(article_title_selector, 'EMPTY') as title_sel,
               COALESCE(article_body_selector, 'EMPTY') as body_sel
        FROM sites
        WHERE article_title_selector = '' OR article_body_selector = ''
    """)
    empty_core_selectors = cursor.fetchall()
    if empty_core_selectors:
        print(f"\nWarning: {len(empty_core_selectors)} sites have empty core div_selectors!")
    else:
        print("\nAll sites have core div_selectors (title, body) populated!")
    
    # Show which additional selectors are available
    cursor.execute("""
        SELECT name, 
               COALESCE(meta_description_selector, 'NULL') as meta_desc,
               COALESCE(reading_time_selector, 'NULL') as reading_time,
               COALESCE(tags_selector, 'NULL') as tags
        FROM sites
        LIMIT 3
    """)
    rows = cursor.fetchall()
    print("\nSample additional selectors:")
    for row in rows:
        meta_d = row[1] or "not available"
        rt = row[2] or "not available"  
        tags = row[3] or "not available"
        print(f"  {row[0]}: meta_desc={meta_d}, reading_time={rt}, tags={tags}")
    
    cursor.execute("SELECT name, article_title_selector[:40] FROM sites LIMIT 3")
    rows = cursor.fetchall()
    print("\nSample sites:")
    for row in rows:
        print(f"  - {row[0]}: title='{row[1]}'")
    
    conn.close()
    
    print("\n" + "=" * 60)
    print("Seed complete! Single database with 4 core tables.")
    print("=" * 60)
    
    print("\nAdditional useful selectors added:")
    print("  - meta_description_selector: Article description/summary")
    print("  - reading_time_selector: Reading time indicator")  
    print("  - word_count_selector: Word count or reading estimate")
    print("  - source_credit_selector: Source/attribution credit")
    print("  - tags_selector: Article tags/categories links")
    print("  - category_links_selector: Navigation category links")
    print("\nNote: Sites without these selectors have NULL values.")


if __name__ == "__main__":
    main()