 #!/usr/bin/env python3
"""Main entry point for the news scraper."""
import json
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from news_scraper.validation.input_validator import load_and_validate_input
from news_scraper.scraping.engine import ScraperEngine


def main():
    """Main scraping entry point."""
    
    # Load and validate INPUT.json
    input_path = Path("INPUT.json")
    
    if not input_path.exists():
        print("=" * 70)
        print("The Rise of the Phoenix - News Scraper")
        print("=" * 70)
        print()
        print("No INPUT.json found. Creating default configuration...")
        print()
        
        # Create default INPUT.json
        default_input = {
            "sites_to_scrape": ["BBC News", "Reuters", "The Guardian"],
            "max_items_per_site": 10,
            "historic_cutoff_date": None,
            "proxy_config": {
                "useApifyProxy": False,
                "apifyProxyGroups": [],
                "countryCode": None
            }
        }
        
        with open(input_path, "w") as f:
            json.dump(default_input, f, indent=2)
        
        print("Default INPUT.json created.")
        print()
    
    # Load input configuration
    input_data = load_and_validate_input(str(input_path))
    
    print("=" * 70)
    print("The Rise of the Phoenix - News Scraper")
    print("=" * 70)
    print()
    print(f"Configuration loaded from: {input_path}")
    print()
    
    # Print configuration
    print("Scraping Configuration:")
    print("-" * 40)
    print(f"  Sites to scrape: {', '.join(input_data['sites_to_scrape']) or 'All active sites'}")
    print(f"  Max items per site: {input_data['max_items_per_site']}")
    print(f"  Historic cutoff date: {input_data['historic_cutoff_date'] or 'None (all articles)'}")
    print()
    
    # Initialize scraper engine
    engine = ScraperEngine(timeout=30)
    
    # Get sites to scrape
    from news_scraper.database.session import get_session
    session_gen = get_session()
    db = next(session_gen)
    
    if input_data['sites_to_scrape']:
        # Specific sites requested
        sites_to_scrape = [site for site in db.query(SiteConfig).filter(
            SiteConfig.name.in_(input_data['sites_to_scrape'])
        )]
        
        if not sites_to_scrape:
            print(f"Error: None of the requested sites were found:")
            for site_name in input_data['sites_to_scrape']:
                print(f"  - {site_name}")
            sys.exit(1)
    else:
        # Scrape all active sites
        from news_scraper.database.models import SiteConfig
        sites_to_scrape = db.query(SiteConfig).filter(SiteConfig.active == True).all()
    
    print(f"Found {len(sites_to_scrape)} site(s) to scrape:")
    for site in sites_to_scrape:
        print(f"  - {site.name} ({site.url})")
    print()
    
    # Scrape each site
    scraped_count = 0
    error_count = 0
    
    for site in sites_to_scrape:
        print(f"Scraping: {site.name}")
        print("-" * 40)
        
        try:
            # Fetch homepage
            html, _ = engine.fetch_with_fallback(site.url)
            
            if html:
                # Extract articles (simplified - would need full article extraction logic)
                print(f"  ✓ Successfully fetched {site.name}")
                scraped_count += 1
            else:
                print(f"  ✗ Failed to fetch {site.name}")
                error_count += 1
                
        except Exception as e:
            print(f"  ✗ Error scraping {site.name}: {str(e)}")
            error_count += 1
    
    print()
    print("=" * 70)
    print("Scraping Complete!")
    print("=" * 70)
    print(f"Successfully scraped: {scraped_count} site(s)")
    print(f"Failed: {error_count} site(s)")
    print()
    print("Data would be exported to JSON datasets:")
    print("  - Success Dataset: articles.json")
    print("  - Error Log Dataset: errors.json")


if __name__ == "__main__":
    main()
