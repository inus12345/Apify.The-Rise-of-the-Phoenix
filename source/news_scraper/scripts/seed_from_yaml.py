# Script to seed database from YAML configuration file in data/seeds/

import sys
from pathlib import Path

# Add project root to path for relative imports
ROOT_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))


def seed_from_yaml():
    """Load sites from YAML configuration file into database."""
    
    # Initialize fresh database (uses SQLite by default at database.db)
    from news_scraper.database.session import get_session, init_db
    
    init_db()
    
    session_gen = get_session()
    db = next(session_gen)
    
    print("=" * 70)
    print("Loading Sites from data/seeds/sites_config.yaml")
    print("=" * 70)
    print()
    
    # Load sites from YAML config (config_loader is in data/seeds/)
    import yaml
    with open(ROOT_DIR / 'data' / 'seeds' / 'sites_config.yaml', 'r') as f:
        config_data = yaml.safe_load(f) or {}
    
    if not config_data.get('sites'):
        print("No sites found in configuration file!")
        return
    
    # Build registry to add sites
    from news_scraper.scraping.config_registry import SiteConfigRegistry
    from news_scraper.database.models import SiteConfig
    from sqlalchemy import func
    
    registry = SiteConfigRegistry(db)
    
    sites_list = config_data['sites']
    print(f"Found {len(sites_list)} sites in configuration:\n")
    
    for i, site_data in enumerate(sites_list[:10], 1):  # Show first 10
        print(f"{i}. {site_data.get('name', 'N/A')[:35]} | {site_data.get('url', 'N/A')}")
    
    if len(sites_list) > 10:
        print(f"... and {len(sites_list) - 10} more sites (showing first 10)")
    
    print()
    print("=" * 70)
    
    # Load sites into database
    added_count = 0
    for site_data in sites_list:
        url = site_data.get('url', '')
        
        if not url:
            continue
        
        # Skip if already exists (URL-based deduplication)
        existing = registry.get_site_by_url(url)
        if existing:
            print(f"- {site_data.get('name', 'N/A')}: Already exists")
            continue
        
        try:
            name = site_data.get('name', '')
            
            # Add the main site with full metadata
            site = registry.add_site(
                name=name,
                url=url,
                category_url_pattern=site_data.get('category_url_pattern'),
                num_pages_to_scrape=site_data.get('num_pages_to_scrape', 3),
                active=site_data.get('active', True),
                uses_javascript=site_data.get('uses_javascript', False),
            )
            
            # Add metadata fields
            if site_data.get('country'):
                site.location = site_data['country']
            if site_data.get('description'):
                site.description = site_data['description']
            if site_data.get('language'):
                site.language = site_data['language']
            
            db.add(site)
            added_count += 1
            print(f"+ {name} ({site.url})")
        
        except Exception as e:
            print(f"- {name or 'Site'}: Failed - {e}")
    
    # Commit to save changes
    db.commit()
    
    print("-" * 70)
    print(f"\nSites added: {added_count}/{len(sites_list)}")
    
    # Count total SiteConfigs (sites + categories)
    config_count = db.query(func.count(SiteConfig.id)).scalar()
    
    print(f"Total database entries (sites + categories): {config_count}")
    
    print("\nSeed complete!")

if __name__ == "__main__":
    seed_from_yaml()