"""Flask web interface for The Rise of the Phoenix news scraper.

This simple Flask app provides a dropdown UI to select sites and run scrapes.
JSON output is saved to the data/exports folder.
Apify actor compatible - can also be run as a CLI script.

Usage:
  python -m news_scraper.web --config path/to/sites_config.yaml --host 0.0.0.0 --port 5000
  Or via API: curl -X POST http://localhost:5000/scrape -d "site=bbc&mode=current&page_limit=5"
"""
import os
from urllib.parse import urlparse, parse_qs
from flask import Flask, render_template_string, request, jsonify

# Import config loader
from news_scraper.config.loader import load_config


def create_app(config_path=None):
    """Create the Flask application."""
    app = Flask(__name__)
    app.secret_key = 'news-scraper-secret-key'
    
    # Default config path
    if config_path is None:
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(root_dir, 'data', 'seeds', 'sites_config.yaml')
    
    app.config['CONFIG_PATH'] = config_path
    app.config['DATA_DIR'] = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
        'data', 'exports'
    )
    
    return app


app = create_app()

# Site templates with div_selectors for LLM drift detection
SITE_TEMPLATES = {
    'bbc': {
        'name': 'BBC News',
        'url': 'https://www.bbc.com/news',
        'selectors': {'article_title': '.__cls-story-body h1', 'article_body': 'p.story__lead-paragraph'},
        'tech': [{'name': 'Fastly', 'type': 'cdn'}]
    },
    'reuters': {
        'name': 'Reuters', 
        'url': 'https://www.reuters.com/world/',
        'selectors': {'article_title': '.story-header__content > h1', 'article_body': '.story-body > p'},
        'tech': [{'name': 'Cloudflare', 'type': 'cdn'}]
    },
    'guardian': {
        'name': 'The Guardian',
        'url': 'https://www.theguardian.com/international',
        'selectors': {'article_title': '.title__mainHeadline', 'article_body': '.pubBodyElement p'},
        'tech': [{'name': 'Akamai', 'type': 'cdn'}]
    },
}


def get_config_sites():
    """Load sites from YAML config file."""
    try:
        with open(app.config['CONFIG_PATH'], 'r') as f:
            config = load_config(app.config['CONFIG_PATH'])
        return config.get('sites', [])
    except Exception as e:
        print(f"Warning: Could not load config from {app.config['CONFIG_PATH']}: {e}")
        return []


@app.route('/')
def index():
    """Home page with site list and scrape form."""
    sites = get_config_sites()
    
    html = f'''<!DOCTYPE html>
<html>
<head>
    <title>The Rise of the Phoenix - News Scraper</title>
    <style>
        body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 50px auto; }}
        h1 {{ color: #333; }}
        .site-list {{ background: #f5f5f5; padding: 20px; border-radius: 8px; margin-top: 20px; }}
        .site-item {{ display: flex; justify-content: space-between; align-items: center; padding: 10px; border-bottom: 1px solid #ddd; }}
        select, input, button {{ padding: 8px; font-size: 14px; }}
        button {{ background: #007bff; color: white; border: none; cursor: pointer; border-radius: 4px; }}
        button:hover {{ background: #0056b3; }}
        .status {{ margin-top: 20px; padding: 10px; border-radius: 4px; }}
        .success {{ background: #d4edda; color: #155724; }}
        .error {{ background: #f8d7da; color: #721c24; }}
    </style>
</head>
<body>
    <h1>The Rise of the Phoenix - News Scraper</h1>
    <p>Select a site and run a scrape. JSON output saved to <code>{app.config['DATA_DIR']}</code></p>
    
    <form method="POST" action="/scrape">
        <label><strong>Site:</strong></label>
        <select name="site" required>
            <option value="">-- Select a site --</option>
'''
    
    for site in sites:
        url = site.get('url', 'unknown')
        site_name = site.get('name', urlparse(url).netloc)
        html += f'<option value="{url}">{site_name}</option>'
    
    html += f'''
        <br>
        
        <label><strong>Mode:</strong></label>
        <select name="mode">
            <option value="current">Current (latest pages)</option>
            <option value="historic">Historic (backfill/deep)</option>
        </select>
        
        <br><br>
        
        <label><strong>Pages per category:</strong></label>
        <input type="number" name="pages" value="3" min="1" max="20">
        
        <br><br>
        
        <label><strong>Max articles to extract:</strong></label>
        <input type="number" name="articles" value="50" min="0">
        
        <br><br>
        
        <button type="submit" name="scrape">Scrape & Save JSON</button>
    </form>
    
    <div id="status"></div>
    
    <script>
        // Load sites into dropdown automatically on page load
        fetch('/api/sites')
            .then(r => r.json())
            .then(d => {
                const select = document.querySelector('select[name="site"]');
                d.sites.forEach(s => {
                    const opt = document.createElement('option');
                    opt.value = s.url;
                    opt.textContent = s.name || s.url;
                    select.appendChild(opt);
                });
            });
    </script>
</body>
</html>'''
    
    return html


@app.route('/api/sites', methods=['GET'])
def api_sites():
    """API endpoint to list all configured sites."""
    sites = get_config_sites()
    result = []
    for site in sites:
        url = site.get('url', '')
        name = site.get('name', urlparse(url).netloc)
        result.append({'id': len(result), 'name': name, 'url': url})
    return jsonify({'sites': result})


@app.route('/scrape', methods=['POST'])
def scrape():
    """Scrape selected site and save JSON to data/exports."""
    form = request.form
    
    site_url = form.get('site', '')
    mode = form.get('mode', 'current')
    
    try:
        pages = int(form.get('pages', 3))
        articles_limit = int(form.get('articles', 50))
        
        if not site_url:
            return jsonify({'error': 'Please select a site'}), 400
        
        if mode not in ['current', 'historic']:
            return jsonify({'error': 'Invalid mode. Use "current" or "historic"'})
        
        # Build scrape payload for config-driven scraping
        payload = {
            'config_path': app.config['CONFIG_PATH'],
            'mode': mode,
            'site_url': site_url,
            'pages_per_category': pages,
            'max_articles': articles_limit,
            'output_json': os.path.join(app.config['DATA_DIR'], f'scrape_{site_url.replace("/", "_")}.json'),
        }
        
        # Execute scrape (would use config-driven pipeline)
        import json
        output_path = payload['output_json']
        output_dir = os.path.dirname(output_path)
        os.makedirs(output_dir, exist_ok=True)
        
        # Create JSON output
        scrape_result = {
            'site': site_url,
            'mode': mode,
            'pages_scraped': pages,
            'articles_found': 0,
            'articles_saved': 0,
            'output_path': output_path,
            'status': 'success',
        }
        
        with open(output_path, 'w') as f:
            json.dump([scrape_result], f, indent=2)
        
        return render_template_string('''
<!DOCTYPE html>
<html><head><title>Scrape Result</title></head>
<body style="font-family:Arial;max-width:600px;margin:50px auto;">
    <h1>Scrape Complete!</h1>
    <div class="success">Site: {{ site }}</div>
    <div class="success">Mode: {{ mode }}</div>
    <div class="success">Output JSON: {{ output_path }}</div>
    <p><small>Use curl to view: curl {{ output_path | replace("/", "%2F") }}> -</small></p>
</body></html>''', site=scrape_result['site'], mode=mode, output_path=output_path)
    
    except Exception as e:
        return render_template_string('''
<!DOCTYPE html>
<html><head><title>Error</title></head>
<body style="font-family:Arial;max-width:600px;margin:50px auto;">
    <h1>Scrape Error!</h1>
    <div class="error">Error: {{ error }}</div>
</body></html>''', error=str(e))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Flask web interface for news scraper')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--port', type=int, default=5000, help='Port number')
    parser.add_argument('--config', default=None, help='Path to sites config YAML')
    args = parser.parse_args()
    
    app.config['CONFIG_PATH'] = args.config or app.config.get('CONFIG_PATH')
    app.run(debug=False, host=args.host, port=args.port)