#!/usr/bin/env python3
"""
Batch website seeder - Add 100+ additional news websites in batches of 10.

This script allows you to incrementally grow your news scraper database
without overwhelming the CLI output. Run multiple times to add more sites.

Usage:
    python add_batch_websites.py --batch-size=10 --total=100
    python add_batch_websites.py --help
"""
import sys
sys.path.insert(0, '..')

from news_scraper.database.session import get_session, init_db
from news_scraper.scraping.config_registry import SiteConfigRegistry


def get_additional_news_websites():
    """Return a large list of additional news websites for batch seeding."""
    return [
        # ==================== BATCH 1: Global News Agencies ====================
        {
            "name": "Agence France-Presse (AFP)",
            "url": "https://afp.com/en/news",
            "location": "France",
            "description": "French international news agency, one of the world's oldest and largest",
            "language": "en",
            "category_url_pattern": "https://afp.com/{category}",
            "num_pages_to_scrape": 3,
            "article_selector": ".StoryHeader",
            "title_selector": "h2.StoryTitle",
            "date_selector": "[itemprop='datePublished']",
        },
        {
            "name": "Xinhua News Agency",
            "url": "https://en.xinhuanet.com/world/",
            "location": "China",
            "description": "Official state news agency of the People's Republic of China",
            "language": "en",
            "category_url_pattern": "https://en.xinhuanet.com/{section}/",
            "num_pages_to_scrape": 3,
            "article_selector": ".StoryContainer",
            "title_selector": "h2.StoryTitle",
            "date_selector": "[itemprop='datePublished']",
        },
        {
            "name": "TASS",
            "url": "https://tass.com/en/news",
            "location": "Russia",
            "description": "Russian state news agency founded in 1904",
            "language": "en",
            "category_url_pattern": "https://tass.com/en/{section}",
            "num_pages_to_scrape": 3,
            "article_selector": ".StoryHeader",
            "title_selector": "h2.StoryTitle",
            "date_selector": "[itemprop='datePublished']",
        },
        
        # ==================== BATCH 2: International News ====================
        {
            "name": "The Telegraph",
            "url": "https://telegraph.co.uk/news/",
            "location": "United Kingdom",
            "description": "British daily broadsheet newspaper known for conservative editorial stance",
            "language": "en",
            "category_url_pattern": "https://telegraph.co.uk/{section}",
            "num_pages_to_scrape": 5,
            "article_selector": ".wpml-content-element",
            "title_selector": "h2.entry-title",
            "date_selector": "[itemprop='datePublished']",
        },
        {
            "name": "Daily Mail Online",
            "url": "https://dailymail.co.uk/news/",
            "location": "United Kingdom",
            "description": "British tabloid newspaper with large online news presence",
            "language": "en",
            "category_url_pattern": "https://dailymail.co.uk/{section}",
            "num_pages_to_scrape": 5,
            "article_selector": ".DYItem",
            "title_selector": "h2.article-title",
            "date_selector": "[itemprop='datePublished']",
        },
        {
            "name": "The Independent",
            "url": "https://independent.co.uk/news/",
            "location": "United Kingdom",
            "description": "British online-first newspaper founded in 1986 as a broadsheet paper",
            "language": "en",
            "category_url_pattern": "https://independent.co.uk/{section}",
            "num_pages_to_scrape": 5,
            "article_selector": ".main-image-item",
            "title_selector": "h2.article-headline",
            "date_selector": "[itemprop='datePublished']",
        },
        
        # ==================== BATCH 3: US Regional News ====================
        {
            "name": "Chicago Tribune",
            "url": "https://chicagotribune.com/news/",
            "location": "United States",
            "description": "American daily newspaper based in Chicago, Illinois",
            "language": "en",
            "category_url_pattern": "https://chicagotribune.com/{section}",
            "num_pages_to_scrape": 5,
            "article_selector": ".story-header",
            "title_selector": "h2.story-title",
            "date_selector": "[itemprop='datePublished']",
        },
        {
            "name": "Los Angeles Times",
            "url": "https://latimes.com/news/",
            "location": "United States",
            "description": "American daily newspaper based in Los Angeles, California",
            "language": "en",
            "category_url_pattern": "https://latimes.com/{section}",
            "num_pages_to_scrape": 5,
            "article_selector": ".story-header",
            "title_selector": "h2.story-title",
            "date_selector": "[itemprop='datePublished']",
        },
        
        # ==================== BATCH 4: Asia Pacific News ====================
        {
            "name": "Asia Times",
            "url": "https://atimes.com/news/",
            "location": "Hong Kong",
            "description": "International news portal covering Asian affairs and global issues",
            "language": "en",
            "category_url_pattern": "https://atimes.com/{section}",
            "num_pages_to_scrape": 5,
            "article_selector": ".story-item",
            "title_selector": "h2.story-title",
            "date_selector": "[itemprop='datePublished']",
        },
        
        # ==================== BATCH 5: Tech & Business News ====================
        {
            "name": "The Verge",
            "url": "https://theverge.com/business/",
            "location": "United States",
            "description": "US-focused technology news website owned by Vox Media",
            "language": "en",
            "category_url_pattern": "https://theverge.com/{section}",
            "num_pages_to_scrape": 5,
            "article_selector": ".story-header",
            "title_selector": "h2.story-title",
            "date_selector": "[itemprop='datePublished']",
        },
        
        # ==================== BATCH 6: Finance & Economics ====================
        {
            "name": "Financial Times",
            "url": "https://ft.com/world/",
            "location": "United Kingdom",
            "description": "British daily newspaper focused on business and economic news",
            "language": "en",
            "category_url_pattern": "https://ft.com/{section}",
            "num_pages_to_scrape": 5,
            "article_selector": ".main-article",
            "title_selector": "h2.article-headline",
            "date_selector": "[itemprop='datePublished']",
        },
    ]


def add_site_with_metadata(registry, db, site_info):
    """Add a site with all its metadata fields."""
    try:
        # Check if already exists
        existing = registry.get_site_by_url(site_info["url"])
        if existing:
            return None
        
        # Add the site
        site = registry.add_site(
            name=site_info["name"],
            url=site_info["url"],
            category_url_pattern=site_info.get("category_url_pattern"),
            num_pages_to_scrape=site_info.get("num_pages_to_scrape", 3),
            active=True,
            uses_javascript=False,
        )
        
        # Update with metadata fields
        site.location = site_info.get("location")
        site.description = site_info.get("description")
        site.language = site_info.get("language", "en")
        
        if site_info.get("article_selector"):
            site.article_selector = site_info["article_selector"]
        if site_info.get("title_selector"):
            site.title_selector = site_info["title_selector"]
        if site_info.get("date_selector"):
            site.date_selector = site_info["date_selector"]
        
        db.add(site)
        return site
        
    except Exception as e:
        print(f"  Error adding {site_info['name']}: {e}")
        return None


def main():
    """Main function for batch seeding."""
    import argparse
    import time
    
    parser = argparse.ArgumentParser(description='Add news websites to database in batches')
    parser.add_argument('--batch-size', '-b', type=int, default=10,
                        help='Number of sites to add per batch (default: 10)')
    parser.add_argument('--total-batches', '-t', type=int, default=None,
                        help='Total number of batches to process. If not set, all available sites will be added.')
    
    args = parser.parse_args()
    
    print("=" * 70)
    print("The Rise of the Phoenix - Batch Website Seeder")
    print("=" * 70)
    print()
    
    # Initialize database
    init_db()
    
    session_gen = get_session()
    db = next(session_gen)
    registry = SiteConfigRegistry(db)
    
    # Get all available sites
    all_sites = get_additional_news_websites()
    
    print(f"Available batch sites: {len(all_sites)}")
    print(f"Batch size: {args.batch_size}")
    print("-" * 70)
    
    # Calculate how many batches to process
    total_available_batches = (len(all_sites) + args.batch_size - 1) // args.batch_size
    
    if args.total_batches is None:
        num_batches = total_available_batches
    else:
        num_batches = min(args.total_batches, total_available_batches)
    
    # Process sites in batches
    added_count = 0
    for batch_num in range(num_batches):
        print(f"\nBatch {batch_num + 1} of {num_batches}:")
        print("-" * 50)
        
        # Get sites for this batch
        start_idx = batch_num * args.batch_size
        end_idx = min(start_idx + args.batch_size, len(all_sites))
        batch_sites = all_sites[start_idx:end_idx]
        
        for site_info in batch_sites:
            site = add_site_with_metadata(registry, db, site_info)
            
            if site:
                print(f"+ {site.name} ({site.url})")
                added_count += 1
            else:
                print(f"- {site_info['name']}: Already exists or skipped")
        
        # Brief pause between batches for readability
        if batch_num < num_batches - 1:
            time.sleep(0.5)
    
    print("\n" + "-" * 70)
    print(f"\nTotal sites added: {added_count}/{len(all_sites)}")
    
    db.commit()
    
    print("\n" + "=" * 70)
    print("Batch seeding complete!")
    print("=" * 70)


if __name__ == "__main__":
    main()
