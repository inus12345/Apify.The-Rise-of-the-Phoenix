-- The Rise of the Phoenix - Simplified Database Schema
-- Single SQLite database for all site configuration data
-- Stores websites to scrape, their config, technologies, categories, and div selectors

CREATE TABLE IF NOT EXISTS sites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    country TEXT,
    language TEXT,
    description TEXT,
    active BOOLEAN DEFAULT 1,
    num_pages_to_scrape INTEGER DEFAULT 3,
    
    -- LLM-ready div selectors for scraping each site
    article_title_selector TEXT,
    article_body_selector TEXT, 
    publish_date_selector TEXT,
    author_selector TEXT,
    image_selector TEXT,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS technologies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_name TEXT NOT NULL,
    technology_name TEXT NOT NULL,
    technology_type TEXT NOT NULL DEFAULT 'cdn',  -- cdn, waf, anti-bot
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (site_name) REFERENCES sites(name) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_name TEXT NOT NULL,
    category_name TEXT NOT NULL,
    url TEXT NOT NULL,
    max_pages INTEGER DEFAULT 3,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (site_name) REFERENCES sites(name) ON DELETE CASCADE,
    UNIQUE(site_name, category_name)
);

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
    
    word_count INTEGER DEFAULT 0,
    reading_time_minutes INTEGER DEFAULT 0,
    
    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    source_url TEXT,
    
    FOREIGN KEY (site_name) REFERENCES sites(name) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_sites_active ON sites(active);
CREATE INDEX IF NOT EXISTS idx_categories_site ON categories(site_name);
CREATE INDEX IF NOT EXISTS idx_articles_site ON scraped_articles(site_name);
CREATE INDEX IF NOT EXISTS idx_articles_title ON scraped_articles(title);