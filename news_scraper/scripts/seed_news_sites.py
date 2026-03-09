#!/usr/bin/env python3
"""Seed the database with popular news sites and their categories."""
import sys
sys.path.insert(0, '..')

from news_scraper.database.session import get_session, init_db
from news_scraper.scraping.config_registry import SiteConfigRegistry
from news_scraper.database.models import SiteConfig


def seed_news_sites():
    """Seed database with top news sites and categories."""
    
    # Initialize fresh database
    init_db()
    
    session_gen = get_session()
    db = next(session_gen)
    registry = SiteConfigRegistry(db)
    
    print("=" * 60)
    print("The Rise of the Phoenix - News Sites Seeder")
    print("=" * 60)
    print()
    
    # List of popular news sites to add with categories
    news_sites = [
        {
            "name": "BBC News",
            "url": "https://bbc.com/news",
        },
        {
            "name": "The Guardian", 
            "url": "https://theguardian.com/world",
        },
        {
            "name": "Reuters",
            "url": "https://reuters.com/news",
        },
        {
            "name": "CNN",
            "url": "https://cnn.com/world",
        },
        {
            "name": "Associated Press",
            "url": "https://apnews.com/technology",
        },
        {
            "name": "NPR",
            "url": "https://npr.org/sections/all Things Considered/",
        },
        {
            "name": "Vox",
            "url": "https://vox.com/policy-and-politics",
        },
        {
            "name": "Ars Technica",
            "url": "https://arstechnica.com/science/",
        }
    ]
    
    print(f"Adding {len(news_sites)} news sites with categories:\n")
    print("-" * 60)
    
    added_count = 0
    
    for site_info in news_sites:
        name = site_info["name"]
        url = site_info["url"]
        
        # Check if already exists
        existing = registry.get_site_by_url(url)
        if existing:
            print(f"- {name}: Already exists")
            continue
        
        try:
            # Add the site
            site = registry.add_site(
                name=name,
                url=url,
                category_url_pattern=None,
                num_pages_to_scrape=3,
                active=True
            )
            
            print(f"+ {name} ({site.url})")
            added_count += 1
            
            # Add categories for major news sites
            categories = [
                {"name": "World", "url": f"{url}/world"},
                {"name": "Business", "url": f"{url}/business"},
                {"name": "Technology", "url": f"{url}/technology"},
                {"name": "Science", "url": f"{url}/science"},
            ]
            
            for cat in categories:
                try:
                    db.add(SiteConfig(
                        site_config_id=site.id,
                        name=cat["name"],
                        url=cat["url"],
                        num_pages_to_scrape=2,
                        active=True
                    ))
                except Exception as e:
                    print(f"  - {cat['name']}: {e}")
            
            print()
        
        except ValueError as e:
            print(f"- {name}: Failed - {e}")
    
    # Count total site configs created (sites + categories)
    from sqlalchemy import func
    config_count = db.query(func.count(SiteConfig.id)).scalar()
    
    print("-" * 60)
    print(f"\nTotal sites added: {added_count}/{len(news_sites)}")
    print(f"Total SiteConfigs (sites + categories): {config_count}")
    
    db.commit()
    
    print("\n" + "=" * 60)
    print("Seeding complete!")
    print("=" * 60)


if __name__ == "__main__":
    seed_news_sites()