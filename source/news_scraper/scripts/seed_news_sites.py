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
    
    print("=" * 70)
    print("The Rise of the Phoenix - News Sites Seeder")
    print("=" * 70)
    print()
    
    # List of top news sites with complete metadata and selectors
    news_sites = [
        {
            "name": "BBC News",
            "url": "https://bbc.com/news",
            "location": "United Kingdom",
            "description": "British public service broadcaster, one of the world's largest news networks",
            "language": "en",
            "category_url_pattern": "https://bbc.com/{category}",
            "num_pages_to_scrape": 5,
            "article_selector": ".gs_ux9Lb",
            "title_selector": "h2.lC4Htd",
            "date_selector": "[data-timestamp]",
        },
        {
            "name": "The Guardian",
            "url": "https://theguardian.com/world",
            "location": "United Kingdom",
            "description": "British daily newspaper focused on liberal/left-wing politics and international news",
            "language": "en",
            "category_url_pattern": "https://theguardian.com/{category}",
            "num_pages_to_scrape": 5,
            "article_selector": ".cw-tv7b",
            "title_selector": "h2.cw-tv7b",
            "date_selector": "[datetime]",
        },
        {
            "name": "Reuters",
            "url": "https://reuters.com/news",
            "location": "United States",
            "description": "International news agency headquartered in London, owned by Thomson Reuters",
            "language": "en",
            "category_url_pattern": "https://reuters.com/{category}",
            "num_pages_to_scrape": 5,
            "article_selector": ".js-main-story",
            "title_selector": "h1.main-headline",
            "date_selector": "[rel='dc.date']",
        },
        {
            "name": "CNN",
            "url": "https://cnn.com/world",
            "location": "United States",
            "description": "US news media network owned by Warner Bros. Discovery, known for 24-hour cable news",
            "language": "en",
            "category_url_pattern": "https://cnn.com/{category}",
            "num_pages_to_scrape": 5,
            "article_selector": ".CRDB0e",
            "title_selector": "h1.js-headline-title",
            "date_selector": "[rel='dc.date']",
        },
        {
            "name": "Associated Press",
            "url": "https://apnews.com/technology",
            "location": "United States",
            "description": "American not-for-profit cooperative news agency based in New York City",
            "language": "en",
            "category_url_pattern": "https://apnews.com/{category}",
            "num_pages_to_scrape": 5,
            "article_selector": ".story-content",
            "title_selector": "h1.article-headline",
            "date_selector": "[itemprop='datePublished']",
        },
        {
            "name": "NPR",
            "url": "https://npr.org/sections/all-things-considered/",
            "location": "United States",
            "description": "National Public Radio, US-based public media organization",
            "language": "en",
            "category_url_pattern": "https://npr.org/{category}",
            "num_pages_to_scrape": 3,
            "article_selector": ".ArticleItem__container",
            "title_selector": "h2.ArticleHeadline--headline",
            "date_selector": "[datetime]",
        },
        {
            "name": "Vox",
            "url": "https://vox.com/policy-and-politics",
            "location": "United States",
            "description": "Progressive online news and opinion website focused on politics, culture, economics",
            "language": "en",
            "category_url_pattern": "https://vox.com/{category}",
            "num_pages_to_scrape": 3,
            "article_selector": ".StoryItem",
            "title_selector": "h2.StoryHeadingTitle",
            "date_selector": "[datetime]",
        },
        {
            "name": "Ars Technica",
            "url": "https://arstechnica.com/science/",
            "location": "United States",
            "description": "Science and technology website covering computing, science, law, and policy",
            "language": "en",
            "category_url_pattern": "https://arstechnica.com/{category}",
            "num_pages_to_scrape": 3,
            "article_selector": ".post-content",
            "title_selector": "h1.article-title",
            "date_selector": "[rel='dc.date']",
        },
        {
            "name": "Politico",
            "url": "https://politico.com/news",
            "location": "United States",
            "description": "US political journalism organization focused on politics and policy",
            "language": "en",
            "category_url_pattern": "https://politico.com/{category}",
            "num_pages_to_scrape": 5,
            "article_selector": ".StoryHeader",
            "title_selector": "h2.StoryTitle",
            "date_selector": "[itemprop='datePublished']",
        },
        {
            "name": "Axios",
            "url": "https://axios.com/now",
            "location": "United States",
            "description": "US-based news media company focusing on business, politics, and technology",
            "language": "en",
            "category_url_pattern": "https://axios.com/{category}",
            "num_pages_to_scrape": 5,
            "article_selector": ".StreamRow",
            "title_selector": "h2 a",
            "date_selector": "[datetime]",
        },
        {
            "name": "Bloomberg",
            "url": "https://bloomberg.com/news",
            "location": "United States",
            "description": "US-focused international business and financial news company",
            "language": "en",
            "category_url_pattern": "https://bloomberg.com/{category}",
            "num_pages_to_scrape": 5,
            "article_selector": ".StoryHeader",
            "title_selector": "h2.StoryTitle",
            "date_selector": "[itemprop='datePublished']",
        },
        {
            "name": "The Hill",
            "url": "https://thehill.com/news",
            "location": "United States",
            "description": "US political journalism organization based in Washington DC",
            "language": "en",
            "category_url_pattern": "https://thehill.com/{category}",
            "num_pages_to_scrape": 5,
            "article_selector": ".js-story-header",
            "title_selector": "h2.StoryTitle",
            "date_selector": "[itemprop='datePublished']",
        },
        {
            "name": "The New York Times",
            "url": "https://nytimes.com/world",
            "location": "United States",
            "description": "American daily newspaper based in New York City, one of the world's most influential newspapers",
            "language": "en",
            "category_url_pattern": "https://nytimes.com/{section}",
            "num_pages_to_scrape": 5,
            "article_selector": "[data-component-name='IndexStory']",
            "title_selector": "h2,a[data-test='headline-text']",
            "date_selector": "time[datetime]",
        },
        {
            "name": "The Washington Post",
            "url": "https://washingtonpost.com/world",
            "location": "United States",
            "description": "American daily newspaper published in Washington, DC, owned by Jeff Bezos",
            "language": "en",
            "category_url_pattern": "https://washingtonpost.com/{section}",
            "num_pages_to_scrape": 5,
            "article_selector": ".StoryHeader",
            "title_selector": "h2.StoryTitle",
            "date_selector": "[itemprop='datePublished']",
        },
        {
            "name": "Wall Street Journal",
            "url": "https://wsj.com/articles",
            "location": "United States",
            "description": "American business-focused daily newspaper owned by News Corp",
            "language": "en",
            "category_url_pattern": "https://wsj.com/{section}",
            "num_pages_to_scrape": 5,
            "article_selector": ".js-story-header",
            "title_selector": "h2.StoryTitle",
            "date_selector": "[itemprop='datePublished']",
        },
        {
            "name": "USA Today",
            "url": "https://usatoday.com/news",
            "location": "United States",
            "description": "American daily middle-market newspaper distributed nationwide",
            "language": "en",
            "category_url_pattern": "https://usatoday.com/{section}",
            "num_pages_to_scrape": 5,
            "article_selector": ".article-content",
            "title_selector": "h2.article-title",
            "date_selector": "[itemprop='datePublished']",
        },
        {
            "name": "Al Jazeera",
            "url": "https://aljazeera.com/news",
            "location": "Qatar",
            "description": "International English-language news media organization owned by the Qatar Islamic Fund",
            "language": "en",
            "category_url_pattern": "https://aljazeera.com/{section}",
            "num_pages_to_scrape": 5,
            "article_selector": ".Card__content",
            "title_selector": "h2.Card__title",
            "date_selector": "[itemprop='datePublished']",
        },
        {
            "name": "Deutsche Welle (DW)",
            "url": "https://dw.com/en/news",
            "location": "Germany",
            "description": "German state-owned international broadcaster, world's largest public international broadcaster",
            "language": "en",
            "category_url_pattern": "https://dw.com/{section}",
            "num_pages_to_scrape": 5,
            "article_selector": ".ArticleListItem",
            "title_selector": "h2.ArticleHeadlineHeadline",
            "date_selector": "[itemprop='datePublished']",
        },
        {
            "name": "TechCrunch",
            "url": "https://techcrunch.com/startups/",
            "location": "United States",
            "description": "American online technology company that reports on the tech industry and startups",
            "language": "en",
            "category_url_pattern": "https://techcrunch.com/{section}",
            "num_pages_to_scrape": 5,
            "article_selector": ".post-card",
            "title_selector": "h2.post-title",
            "date_selector": "[itemprop='datePublished']",
        },
        {
            "name": "Wired",
            "url": "https://wired.com/news",
            "location": "United States",
            "description": "American men's lifestyle and technology magazine owned by Condé Nast",
            "language": "en",
            "category_url_pattern": "https://wired.com/{section}",
            "num_pages_to_scrape": 5,
            "article_selector": ".story-item",
            "title_selector": "h2.story-title",
            "date_selector": "[itemprop='datePublished']",
        },
        {
            "name": "Engadget",
            "url": "https://engadget.com/latest/",
            "location": "United States",
            "description": "Technology news website owned by Condé Nast, covering gadgets and digital culture",
            "language": "en",
            "category_url_pattern": "https://engadget.com/{section}",
            "num_pages_to_scrape": 3,
            "article_selector": ".article-item",
            "title_selector": "h2.article-title",
            "date_selector": "[itemprop='datePublished']",
        },
        {
            "name": "Polygon",
            "url": "https://polygon.com/news",
            "location": "United States",
            "description": "Video game and pop culture website owned by Verizon Media",
            "language": "en",
            "category_url_pattern": "https://polygon.com/{section}",
            "num_pages_to_scrape": 5,
            "article_selector": ".PostList__item",
            "title_selector": "h2.PostTitleHeadline",
            "date_selector": "[rel='dc.date']",
        },
        {
            "name": "Kotaku",
            "url": "https://kotaku.com/recent",
            "location": "United States",
            "description": "Video game website owned by Gizmodo Media Group",
            "language": "en",
            "category_url_pattern": "https://kotaku.com/{section}",
            "num_pages_to_scrape": 5,
            "article_selector": ".ArticleListItem",
            "title_selector": "h2.ArticleTitleHeadline",
            "date_selector": "[datetime]",
        },
        {
            "name": "Ars Technica",
            "url": "https://arstechnica.com/civs/",
            "location": "United States",
            "description": "Science and technology website covering computing, science, law, and policy",
            "language": "en",
            "category_url_pattern": "https://arstechnica.com/{section}",
            "num_pages_to_scrape": 3,
            "article_selector": ".post-content",
            "title_selector": "h1.article-title",
            "date_selector": "[rel='dc.date']",
        },
        {
            "name": "South China Morning Post",
            "url": "https://scmp.com/news/hong-kong",
            "location": "Hong Kong",
            "description": "English-language daily newspaper published in Hong Kong",
            "language": "en",
            "category_url_pattern": "https://scmp.com/{section}",
            "num_pages_to_scrape": 5,
            "article_selector": ".StoryContainer",
            "title_selector": "h2.StoryTitle",
            "date_selector": "[itemprop='datePublished']",
        },
        {
            "name": "Nikkei Asia",
            "url": "https://asia.nikkei.com/Business",
            "location": "Japan",
            "description": "Japanese business newspaper published in Tokyo, part of Nikkei Inc.",
            "language": "en",
            "category_url_pattern": "https://asia.nikkei.com/{section}",
            "num_pages_to_scrape": 5,
            "article_selector": ".StoryItem",
            "title_selector": "h2.StoryTitleHeadline",
            "date_selector": "[itemprop='datePublished']",
        },
        {
            "name": "Caixin",
            "url": "https://caixin.com/business",
            "location": "China",
            "description": "Chinese business newspaper based in Beijing, known for investigative journalism",
            "language": "en",
            "category_url_pattern": "https://caixin.com/{section}",
            "num_pages_to_scrape": 3,
            "article_selector": ".story-item",
            "title_selector": "h2.story-title",
            "date_selector": "[itemprop='datePublished']",
        },
        {
            "name": "ABC News",
            "url": "https://abcnews.go.com/International",
            "location": "United States",
            "description": "News division of American broadcast network ABC, part of Disney-ABC Television Group",
            "language": "en",
            "category_url_pattern": "https://abcnews.go.com/{section}",
            "num_pages_to_scrape": 5,
            "article_selector": ".StoryHeader",
            "title_selector": "h2.StoryTitle",
            "date_selector": "[itemprop='datePublished']",
        },
        {
            "name": "NBC News",
            "url": "https://nbcnews.com/world",
            "location": "United States",
            "description": "News division of the US broadcast network NBC, owned by Comcast",
            "language": "en",
            "category_url_pattern": "https://nbcnews.com/{section}",
            "num_pages_to_scrape": 5,
            "article_selector": ".StoryHeader",
            "title_selector": "h2.StoryTitle",
            "date_selector": "[itemprop='datePublished']",
        },
        {
            "name": "CBS News",
            "url": "https://cbsnews.com/news/",
            "location": "United States",
            "description": "News division of CBS television network, owned by Paramount Global",
            "language": "en",
            "category_url_pattern": "https://cbsnews.com/{section}",
            "num_pages_to_scrape": 5,
            "article_selector": ".StoryHeader",
            "title_selector": "h2.StoryTitle",
            "date_selector": "[itemprop='datePublished']",
        },
    ]
    
    print(f"\nAdding {len(news_sites)} news sites with categories:\n")
    print("-" * 70)
    
    added_count = 0
    category_template_urls = {
        "World": "{url}/world",
        "Business": "{url}/business",
        "Technology": "{url}/technology",
        "Science": "{url}/science",
        "Politics": "{url}/politics",
        "Health": "{url}/health",
        "Sports": "{url}/sports",
        "Entertainment": "{url}/entertainment",
    }
    
    for site_info in news_sites:
        name = site_info["name"]
        url = site_info["url"]
        
        # Check if already exists (URL-based deduplication)
        existing = registry.get_site_by_url(url)
        if existing:
            print(f"- {name}: Already exists")
            continue
        
        try:
            # Add the main site with full metadata
            site = registry.add_site(
                name=name,
                url=url,
                category_url_pattern=site_info.get("category_url_pattern"),
                num_pages_to_scrape=site_info.get("num_pages_to_scrape", 3),
                active=True,
                uses_javascript=False,
            )
            
            # Update site with metadata fields
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
            db.commit()
            
            print(f"+ {name} ({site.url})")
            
            # Add categories for each site (using template URLs)
            categories = []
            pattern_template = category_template_urls.get(name.split(" ")[0].lower().replace("_", ""))
            
            if pattern_template:
                try:
                    base_url = url.rstrip("/")
                    for cat_name, cat_pattern in category_template_urls.items():
                        cat_url = cat_pattern.format(url=base_url)
                        categories.append({
                            "name": cat_name,
                            "url": cat_url,
                            "max_pages": site_info.get("num_pages_to_scrape", 2),
                        })
                except Exception:
                    pass
            
            for cat in categories[:5]:  # Max 5 categories per site
                try:
                    site_cat = SiteConfig(
                        site_config_id=site.id,
                        name=cat["name"],
                        url=cat["url"],
                        num_pages_to_scrape=cat.get("max_pages", 2),
                        active=True,
                    )
                    
                    # Copy parent selectors if not category-specific
                    if site.article_selector:
                        site_cat.article_selector = site.article_selector
                    if site.title_selector:
                        site_cat.title_selector = site.title_selector
                    
                    db.add(site_cat)
                except Exception as e:
                    print(f"  - {cat['name']}: Skipped ({e})")
            
            print()
        
        except ValueError as e:
            print(f"- {name}: Failed to add - {e}")
    
    # Count total site configs created (sites + categories)
    from sqlalchemy import func
    config_count = db.query(func.count(SiteConfig.id)).scalar()
    
    print("-" * 70)
    print(f"\nTotal sites added: {added_count}/{len(news_sites)}")
    print(f"Total SiteConfigs (sites + categories): {config_count}")
    
    db.commit()
    
    print("\n" + "=" * 70)
    print("Seeding complete!")
    print("=" * 70)


if __name__ == "__main__":
    seed_news_sites()
