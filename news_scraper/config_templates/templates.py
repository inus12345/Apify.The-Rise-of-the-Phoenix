"""Site configuration templates for common scraping patterns."""
from typing import Dict, Any, List


# Common CSS selectors for news/blog sites
DEFAULT_SELECTORS = {
    "article": ["article", ".article", "#article", ".post"],
    "title": ["h1", ".title", "#title", "[property='og:title']"],
    "date": [
        "time[datetime]",
        ".date",
        ".pub-date",
        ".timestamp",
        "[rel='publish']"
    ],
    "author": [".author", ".byline", "[rel='author']", "[itemprop='author']"],
    "content": ["article", ".content", "#main-content", "[itemprop='articleBody']"],
    "image": [
        'meta[property="og:image"]',
        '.featured-image img',
        '[itemprop="image"]'
    ],
    "description": ['meta[name="description"]', '.excerpt'],
}


# Predefined site templates for common news/blog platforms
SITE_TEMPLATES = {
    # Generic templates
    "generic_news": {
        "name": "Generic News Site",
        "article_selector": ".article|article|.post",
        "title_selector": "h1|h2.entry-title",
        "date_selector": "time[datetime]|.pub-date",
        "author_selector": ".author|[rel='author']",
        "content_selector": "article p|.entry-content p",
        "description_selector": 'meta[name="description"][property="og:description"]',
        "image_selector": "[property='og:image'], .featured-image img",
    },
    "blog_simple": {
        "name": "Simple Blog",
        "article_selector": ".post|article",
        "title_selector": "h1, h2.title",
        "date_selector": ".date, time",
        "author_selector": ".author",
        "content_selector": ".entry-content p",
    },
    "tech_cms": {
        "name": "Tech CMS Site",
        "article_selector": ".news-article|article.tech",
        "title_selector": "h1.main-title",
        "date_selector": "time.published, .publish-date",
        "author_selector": ".writer, .by-author",
        "content_selector": ".body-text p, article p",
    },
    
    # Popular news site templates (10 initial sources)
    "bbc_news": {
        "name": "BBC News",
        "article_selector": ".gs_ux9Lb",
        "title_selector": "h2.lC4Htd, .wpf-bd8Zc",
        "date_selector": ".of-5n1Qf, [data-timestamp]",
        "author_selector": "[itemprop='author']",
        "content_selector": ".eGJX9d, .e3yKz",
        "description_selector": 'meta[name="description"]',
        "image_selector": '[property="og:image"], .uq2k6B img',
    },
    "theguardian": {
        "name": "The Guardian",
        "article_selector": ".cw-tv7b, .main-section__content-item",
        "title_selector": "h2.cw-tv7b, h1",
        "date_selector": "[datetime], .timestamp",
        "author_selector": "[itemprop='author']",
        "content_selector": ".cw-8d5c p, .main-section__content-item__element-body p",
        "description_selector": 'meta[property="og:description"]',
        "image_selector": '[property="og:image"], .cw-tv7b__primary-image img',
    },
    "reuters": {
        "name": "Reuters",
        "article_selector": ".js-main-story, article.story",
        "title_selector": "h1.main-headline, h2.js-headline-title",
        "date_selector": "[rel='dc.date'], .published-time",
        "author_selector": "[itemprop='author']",
        "content_selector": ".main-article p, article p",
        "description_selector": 'meta[property="og:description"]',
        "image_selector": '[property="og:image"], .main-image img',
    },
    "cnn": {
        "name": "CNN",
        "article_selector": ".CRDB0e, .MainBody__content",
        "title_selector": "h1.js-headline-title, h2.headline",
        "date_selector": "[rel='dc.date'], .time-published-granular",
        "author_selector": "[itemprop='author']",
        "content_selector": ".CRDB0e p, .MainBody__content p",
        "description_selector": 'meta[property="og:description"]',
        "image_selector": '[property="og:image"], .MainImage__image img',
    },
    "associated_press": {
        "name": "Associated Press",
        "article_selector": ".story-content, article.story",
        "title_selector": "h1.article-headline, h2.headline",
        "date_selector": "[itemprop='datePublished']",
        "author_selector": "[itemprop='author']",
        "content_selector": ".story-content p, article p",
        "description_selector": 'meta[name="description"]',
        "image_selector": '[property="og:image"]',
    },
    "npr": {
        "name": "NPR",
        "article_selector": ".ArticleItem__container, .js-article",
        "title_selector": "h2.ArticleHeadline--headline",
        "date_selector": "[datetime], .Timestamp",
        "author_selector": "[itemprop='author']",
        "content_selector": ".BodyCopy p, article p",
        "description_selector": 'meta[property="og:description"]',
        "image_selector": '[property="og:image"], .ArticleHeadlineImage img',
    },
    "vox": {
        "name": "Vox",
        "article_selector": ".StoryItem, .js-story-item",
        "title_selector": "h2.StoryHeadingTitle",
        "date_selector": "[datetime], .PublishedDate--text",
        "author_selector": "[itemprop='author']",
        "content_selector": ".ArticleBody p, .StoryContent__text p",
        "description_selector": 'meta[property="og:description"]',
        "image_selector": '[property="og:image"], .StoryHeroImage img',
    },
    "vice": {
        "name": "Vice Magazine",
        "article_selector": ".ArticleItem, article.article-item",
        "title_selector": "h1.ArticleTitle",
        "date_selector": "[datetime], .PublishedDate",
        "author_selector": "[itemprop='author']",
        "content_selector": ".Content__text p, article p",
        "description_selector": 'meta[property="og:description"]',
        "image_selector": '[property="og:image"], .ArticleImage img',
    },
    "polygon": {
        "name": "Polygon (Gaming)",
        "article_selector": ".PostList__item, article.post",
        "title_selector": "h2.PostTitleHeadline",
        "date_selector": "[rel='dc.date'], .DatePosted",
        "author_selector": "[itemprop='author']",
        "content_selector": ".PostBody p, article p",
        "description_selector": 'meta[property="og:description"]',
        "image_selector": '[property="og:image"], .CoverImage img',
    },
    "kotaku": {
        "name": "Kotaku",
        "article_selector": ".ArticleListItem, article.article-list-item",
        "title_selector": "h2.ArticleTitleHeadline",
        "date_selector": "[datetime], .DatePosted",
        "author_selector": "[itemprop='author']",
        "content_selector": ".ArticleBody p, article p",
        "description_selector": 'meta[property="og:description"]',
        "image_selector": '[property="og:image"], .Image img',
    },
    "arstechnica": {
        "name": "Ars Technica",
        "article_selector": ".post-content, article.post-content",
        "title_selector": "h1.article-title",
        "date_selector": "[rel='dc.date']",
        "author_selector": "[itemprop='author']",
        "content_selector": ".post-content p, article p",
        "description_selector": 'meta[property="og:description"]',
        "image_selector": '[property="og:image"]',
    },
}


def get_site_template(name: str) -> Dict[str, Any]:
    """
    Get a site configuration template by name.
    
    Args:
        name: Template name (e.g., 'generic_news', 'blog_simple')
        
    Returns:
        Template dictionary with selectors
    """
    return SITE_TEMPLATES.get(
        name,
        {
            "name": "Custom",
            **DEFAULT_SELECTORS,
        }
    )


def get_all_templates() -> Dict[str, Dict[str, Any]]:
    """Get all available site templates."""
    return {**SITE_TEMPLATES}


def create_site_config_from_template(
    name: str,
    url: str,
    template_name: str = "generic_news",
    num_pages: int = 1
) -> Dict[str, Any]:
    """
    Create a complete site configuration from a template.
    
    Args:
        name: Site display name
        url: Base URL of the site
        template_name: Template to use (default: 'generic_news')
        num_pages: Number of pages to scrape
        
    Returns:
        Complete site configuration dictionary
    """
    template = get_site_template(template_name)
    
    return {
        "name": name,
        "url": url,
        "category_url_pattern": f"{url.rstrip('/')}/page/{{page}}" if "/" in url else None,
        "num_pages_to_scrape": num_pages,
        "article_selector": template.get("article_selector"),
        "title_selector": template.get("title_selector"),
        "date_selector": template.get("date_selector"),
        "content_selector": template.get("content_selector"),
        "uses_javascript": False,  # Update to True for JS sites
    }


def list_available_templates() -> List[Dict[str, Any]]:
    """List all available templates with descriptions."""
    return [
        {
            "name": name,
            "description": info["name"],
            "selectors_used": [k for k in info.keys() if not k == "name"]
        }
        for name, info in SITE_TEMPLATES.items()
    ]