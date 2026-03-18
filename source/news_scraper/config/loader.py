"""Configuration loader for reading and merging YAML config files with environment settings."""
from typing import Dict, Any
import yaml

from ..core.config import settings


def load_config(config_path: str = None) -> Dict[str, Any]:
    """
    Load configuration from a YAML file if provided, otherwise return defaults.
    
    Args:
        config_path: Path to YAML configuration file (optional)
        
    Returns:
        Dictionary of configuration values
    """
    config = {}
    
    if config_path:
        # Try to load from specified path
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                loaded_config = yaml.safe_load(f) or {}
            
            # Merge loaded config with current settings
            for section in ['sites', 'scraping', 'backfill', 'export', 'validation', 'database']:
                if section in loaded_config:
                    config[section] = loaded_config[section]
                    
            return config
            
        except FileNotFoundError:
            print(f"Warning: Config file not found: {config_path}")
        except yaml.YAMLError as e:
            print(f"Error parsing YAML config: {e}")
    
    # Return default configuration
    return build_default_config()


def build_default_config() -> Dict[str, Any]:
    """Build default configuration from current settings."""
    return {
        'scraping': {
            'default_mode': 'incremental',
            'enable_full_scrape_mode': True,
            'rate_limit_enabled': True,
            'min_delay_between_requests': 1.0,
            'default_pages_to_scrape': settings.DEFAULT_BATCH_SIZE,
        },
        'backfill': {
            'date_cutoff': None,
            'max_pages_per_site': 20,
        },
        'export': {
            'csv_path': str(settings.DATA_DIR / 'exports' / 'scraped_articles.csv'),
            'json_path': str(settings.DATA_DIR / 'exports' / 'scraped_articles.json'),
            'auto_export': False,
            'preferred_format': 'csv',
        },
        'validation': {
            'enable_auto_validation': False,
            'sample_articles_to_validate': 0,
        },
        'database': {
            'max_articles_per_site': 10000,
            'enable_url_deduplication': True,
        },
    }


def load_sites_from_config(config_path: str = None) -> list:
    """
    Load site configurations from a YAML file.
    
    Args:
        config_path: Path to sites configuration file
        
    Returns:
        List of site dictionaries with name and URL (for adding to database)
    """
    config = load_config(config_path)
    
    sites_list = []
    
    if 'sites' in config:
        for site_data in config['sites']:
            site_url = site_data.get('url', '')
            site_name = site_data.get('name', '')
            
            # Only include valid sites (those with URL defined)
            if site_url and not site_url.startswith('#'):
                sites_list.append({
                    'name': site_name,
                    'url': site_url.strip(),
                    'country': site_data.get('country') or site_data.get('location'),
                    'location': site_data.get('location'),
                    'description': site_data.get('description'),
                    'language': site_data.get('language', 'en'),
                    'server_header': site_data.get('server_header'),
                    'server_vendor': site_data.get('server_vendor'),
                    'hosting_provider': site_data.get('hosting_provider'),
                    'technology_stack_summary': site_data.get('technology_stack_summary'),
                    'active': site_data.get('active', True),
                    'uses_javascript': site_data.get('uses_javascript', False),
                    'category_url_pattern': site_data.get('category_url_pattern'),
                    'categories': site_data.get('categories', []),
                    'technologies': site_data.get('technologies', []),
                    'scrape_strategy': site_data.get('scrape_strategy', {}),
                    'full_scrape_mode': site_data.get('full_scrape_mode', False),
                    'num_pages_to_scrape': site_data.get('num_pages_to_scrape', 3),
                })
    
    return sites_list


def load_from_cli_argument(cli_config_path: str) -> Dict[str, Any]:
    """
    Load configuration from command-line specified path.
    
    Args:
        cli_config_path: Path provided via --config flag
        
    Returns:
        Merged configuration dictionary
    """
    config = load_config(cli_config_path)
    return config


def merge_configs(base_config: Dict, override_config: Dict) -> Dict:
    """
    Merge two configuration dictionaries. Override values take precedence.
    
    Args:
        base_config: Base configuration (e.g., from scraper_config.yaml)
        override_config: Override configuration (e.g., CLI arguments)
        
    Returns:
        Merged configuration dictionary
    """
    merged = {**base_config}
    
    # Recursively merge nested dictionaries
    for key, value in override_config.items():
        if isinstance(value, dict) and key in merged and isinstance(merged[key], dict):
            merged[key] = merge_configs(merged[key], value)
        else:
            merged[key] = value
    
    return merged


def get_default_sites_from_config(config_path: str = None) -> list:
    """
    Get default news sites defined in configuration file.
    
    Args:
        config_path: Path to sites configuration file
        
    Returns:
        List of site dictionaries for seeding
    """
    return load_sites_from_config(config_path)


# =============================================================================
# Convenience functions for common operations
# =============================================================================

def init_from_config(config_path: str = 'news_scraper/config/sites_config.yaml') -> None:
    """
    Initialize database with sites from configuration file.
    
    Args:
        config_path: Path to sites configuration file
    """
    from ..database.session import init_db, get_session
    from ..scraping.config_registry import SiteConfigRegistry
    
    # Initialize database first
    init_db()
    
    session_gen = get_session()
    db = next(session_gen)
    registry = SiteConfigRegistry(db)
    
    # Load sites from config
    sites_list = load_sites_from_config(config_path)
    
    for site_data in sites_list:
        url = site_data['url']
        
        # Skip if already exists (URL-based deduplication)
        if registry.get_site_by_url(url):
            continue
        
        try:
            site = registry.add_site(
                name=site_data['name'],
                url=url,
                category_url_pattern=site_data.get('category_url_pattern'),
                num_pages_to_scrape=site_data.get('num_pages_to_scrape', 3),
                active=site_data.get('active', True),
                uses_javascript=site_data.get('uses_javascript', False),
                country=site_data.get('country'),
                location=site_data.get('location'),
                language=site_data.get('language', 'en'),
                description=site_data.get('description'),
                server_header=site_data.get('server_header'),
                server_vendor=site_data.get('server_vendor'),
                hosting_provider=site_data.get('hosting_provider'),
                technology_stack_summary=site_data.get('technology_stack_summary'),
            )
            print(f"+ {site.name} ({site.url})")
            
        except ValueError as e:
            print(f"- {site_data['name']}: Already exists - {e}")
    
    db.commit()
    print("\nConfiguration initialized!")


def list_config_sites(config_path: str = None) -> None:
    """
    List all sites defined in configuration file.
    
    Args:
        config_path: Path to sites configuration file (optional)
    """
    sites_list = load_sites_from_config(config_path)
    
    print(f"\nSites in configuration ({len(sites_list)} total):\n")
    print("-" * 80)
    for i, site in enumerate(sites_list, 1):
        print(f"{i}. {site['name']:.40} | {site['url']}")
        if site.get('location'):
            print(f"   Location: {site['location']:.30} | Lang: {site['language']}")
    print("-" * 80)
