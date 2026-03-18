"""Flask web interface for The Rise of the Phoenix news scraper."""
import os
import subprocess
import json
from flask import Flask, request, jsonify


def get_config_sites(db_path=None):
    """Load sites from SQLite database."""
    if db_path is None:
        db_path = 'data/scraping.db'

    if not os.path.exists(db_path):
        print(f"Warning: No database found at {db_path}. Run seed_from_yaml.py first.")
        return []

    import sqlite3
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT DISTINCT name, url FROM sites WHERE active = 1 ORDER BY name")
        rows = cursor.fetchall()
        conn.close()
        return [{'name': name, 'url': url} for name, url in rows]
    except Exception as e:
        print(f"Warning: Error reading sites from DB: {e}")
        return []


def create_app(config_path=None):
    app = Flask(__name__)
    app.secret_key = 'news-scraper-secret-key'

    if config_path is None:
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(root_dir, 'data', 'seeds', 'sites_config.yaml')

    app.config['CONFIG_PATH'] = config_path
    data_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
        'data', 'exports'
    )
    app.config['DATA_DIR'] = data_dir

    return app


app = create_app()


@app.route('/')
def index():
    sites = get_config_sites('data/scraping.db')
    data_dir_str = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'exports')

    if not sites:
        return '''<!DOCTYPE html><html><head><title>The Rise of the Phoenix</title>
<style>body{font-family:Arial,sans-serif;background:#1a1a2e;color:#fff;margin:0;padding:40px;}
.container{max-width:800px;margin:0 auto;}.title{font-size:36px;font-weight:bold;margin-bottom:20px;}
.subtitle{color:#aaa;font-size:16px;margin-bottom:40px;}</style></head>
<body><div class="container"><h1 class="title">The Rise of the Phoenix News Scraper</h1>
<p class="subtitle">Seed your sites first with: <code>PYTHONPATH=. python source/scripts/seed_from_yaml.py</code></p>
<p style="color:#aaa;margin-top:20px;">Then run: <code>python source/news_scraper/web/app.py --host 0.0.0.0 --port 5001</code></p></div></body></html>'''

    lines = [
        '<!DOCTYPE html><html><head><title>The Rise of the Phoenix - News Scraper</title>',
        '<style>body{font-family:"Segoe UI",Tahoma,Verdana,sans-serif;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);padding:40px 20px;}',
        '.container{max-width:800px;margin:0 auto;background:white;border-radius:16px;box-shadow:0 20px 60px rgba(0,0,0,.3);overflow:hidden;}',
        '.header{background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);padding:30px;text-align:center;color:white;}',
        '.header h1{margin:0;font-size:32px;font-weight:bold;}',
        '.content{padding:30px;}',
        'form{display:flex;flex-direction:column;gap:15px;}',
        'label{font-weight:600;color:#333;font-size:14px;}',
        'select,input{padding:12px 15px;border:2px solid #e0e0e0;border-radius:8px;font-size:15px;transition:all .3s;background:white;width:100%;box-sizing:border-box;}',
        'button{padding:15px 20px;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:white;border:none;border-radius:8px;font-size:16px;font-weight:600;cursor:pointer;margin-top:10px;}',
        '.info-box{background:#f0f4ff;border-left:4px solid #667eea;padding:15px;border-radius:8px;margin-top:20px;color:#555;}',
        '</style></head>',
        '<body><div class="container">',
        '<div class="header"><h1>The Rise of the Phoenix News Scraper</h1></div>',
    ]

    lines.append('<div class="content"><p style="color:#666;margin-bottom:20px;">Select a news site and scrape articles. JSON output saved to <code style="background:#f0f4ff;padding:8px 12px;border-radius:6px;">' + data_dir_str + '</code></p>')

    lines.append('<form method="POST" action="/scrape"><label><strong>News Site:</strong></label><select name="site" required>')

    for site in sites:
        escaped_url = site['url'].replace('&', '&').replace('<', '<').replace('>', '>')
        lines.append('<option value="' + escaped_url + '">' + site['name'] + '</option>')

    lines.extend([
        '</select><br><br>',
        '<label><strong>Mode:</strong></label><select name="mode"><option value="current">Current (latest pages)</option><option value="historic">Historic (deep backfill)</option></select><br>',
        '<label><strong>Pages per category:</strong></label><input type="number" name="pages" value="3" min="1" max="20"><br>',
        '<label><strong>Max articles to extract:</strong></label><input type="number" name="articles" value="50" min="0"><br><br>',
        '<button type="submit">Scrape & Save JSON</button></form>',
        '</div><div class="info-box"><strong>Add new sites:</strong><br>1. Edit <code style="font-weight:bold;">data/seeds/sites_config.yaml</code><br>',
        '2. Run <code>python source/scripts/seed_from_yaml.py</code><br>See README.md for details.</div></div></body></html>'
    ])

    return ''.join(lines)


def run_scrape_command(output_path, site_url, mode):
    """Run the scraper by importing and calling functions directly."""
    import sys
    import os
    
    # Add root directory to PYTHONPATH so imports work
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root_dir not in sys.path:
        sys.path.insert(0, root_dir)
    
    try:
        from news_scraper.pipelines.config_driven import run_config_scrape
        from news_scraper.database.session import get_session, get_spider_session
        
        # Get database sessions
        db = next(get_session())
        spider_db = next(get_spider_session())
        
        # Call the config-driven scrape function directly with required parameters
        result = run_config_scrape(
            db_session=db,
            config_path='data/seeds/sites_config.yaml',
            mode=mode,
            output_json=output_path,
            site_urls=[site_url],
            sync_first=False,  # Don't sync first to avoid issues
            enable_rate_limiting=True,
            story_batch_size=200,
            spider_session=spider_db
        )
        
        # Return success with metadata
        return 0, '', f"Scrape completed. Output: {result}"
    except Exception as e:
        return 1, '', str(e)


@app.route('/scrape', methods=['POST'])
def scrape():
    form = request.form
    site_url = form.get('site', '')
    mode = form.get('mode', 'current')

    try:
        pages = int(form.get('pages', 3))

        if not site_url:
            return jsonify({'error': 'Please select a site'}), 400

        if mode not in ['current', 'historic']:
            return jsonify({'error': 'Invalid mode. Use "current" or "historic"'})

        safe_name = site_url.replace('/', '_')
        
        # Ensure output directory exists
        output_path = os.path.join(app.config['DATA_DIR'], 'scrape_' + safe_name + '.json')
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Create initial output file
        with open(output_path, 'w') as f:
            json.dump([{'site': site_url, 'mode': mode}], f, indent=2)

        # Run the scraper
        return_code, stdout, stderr = run_scrape_command(output_path, site_url, mode)
        
        if return_code == 0:
            scrape_result = {
                'site': site_url,
                'mode': mode,
                'pages_scraped': pages,
                'articles_found': 0,
                'articles_saved': 0,
                'output_path': output_path,
                'status': 'success'
            }
            
            # Update the output file with results
            with open(output_path, 'w') as f:
                json.dump([scrape_result], f, indent=2)

            return '<!DOCTYPE html><html><head><title>Scrape Complete</title>' + \
                   '<style>body{font-family:Arial;margin:40px 20px;background:#f5f5f5;}' + \
                   '.box{max-width:600px;margin:0 auto;background:white;border-radius:16px;padding:30px;box-shadow:0 20px 60px rgba(0,0,0,.1);}</style></head>' + \
                   '<body><div class="box"><h1 style="color:#667eea;margin-bottom:15px;">Scrape Complete!</h1>' + \
                   '<p style="background:#d4edda;padding:15px;color:#155724;border-radius:8px;"><strong>Site:</strong> ' + site_url.replace('&', '&').replace('<', '<').replace('>', '>') + '</p>' + \
                   '<p style="background:#d4edda;padding:15px;color:#155724;border-radius:8px;"><strong>Mode:</strong> ' + mode + '</p>' + \
                   '<p style="background:#e9ecef;padding:15px;color:#495057;border-radius:8px;"><strong>Output:</strong> ' + output_path + '</p>' + \
                   '<a href="/" style="display:inline-block;margin-top:20px;background:#667eea;color:white;padding:12px 24px;text-decoration:none;border-radius:8px;">Back to Scraper</a></div></body></html>'

        else:
            error_msg = str(stderr).strip()[:500] if stderr else 'Unknown error'
            return '<!DOCTYPE html><html><head><title>Scrape Failed</title>' + \
                   '<style>body{font-family:Arial;margin:40px 20px;background:#f5f5f5;}' + \
                   '.box{max-width:600px;margin:0 auto;background:white;border-radius:16px;padding:30px;}</style></head>' + \
                   '<body><div class="box"><h1 style="color:#dc3545;">Scrape Failed!</h1>' + \
                   '<p style="background:#f8d7da;padding:15px;color:#721c24;border-radius:8px;"><strong>Error:</strong> ' + error_msg.replace('&', '&').replace('<', '<').replace('>', '>') + '</p>' + \
                   '<a href="/" style="display:inline-block;margin-top:20px;background:#667eea;color:white;padding:12px 24px;text-decoration:none;border-radius:8px;">Back to Scraper</a></div></body></html>'

    except RuntimeError as e:
        return '<!DOCTYPE html><html><head><title>Timeout</title>' + \
               '<style>body{font-family:Arial;margin:40px 20px;background:#f5f5f5;}' + \
               '.box{max-width:600px;margin:0 auto;background:white;border-radius:16px;padding:30px;}</style></head>' + \
               '<body><div class="box"><h1 style="color:#ffc107;">Timeout!</h1>' + \
               '<p style="background:#fff3cd;padding:15px;color:#856404;border-radius:8px;"><strong>Error:</strong> ' + str(e) + '</p>' + \
               '<a href="/" style="display:inline-block;margin-top:20px;background:#667eea;color:white;padding:12px 24px;text-decoration:none;border-radius:8px;">Back to Scraper</a></div></body></html>'

    except Exception as e:
        return '<!DOCTYPE html><html><head><title>Error</title>' + \
               '<style>body{font-family:Arial;margin:40px 20px;background:#f5f5f5;}' + \
               '.box{max-width:600px;margin:0 auto;background:white;border-radius:16px;padding:30px;box-shadow:0 20px 60px rgba(0,0,0,.1);}</style></head>' + \
               '<body><div class="box"><h1 style="color:#dc3545;margin-bottom:15px;">Scrape Error!</h1>' + \
               '<p style="background:#f8d7da;padding:15px;color:#721c24;border-radius:8px;"><strong>Error:</strong> ' + str(e)[:200].replace('&', '&').replace('<', '<').replace('>', '>') + '</p>' + \
               '<a href="/" style="display:inline-block;margin-top:20px;background:#667eea;color:white;padding:12px 24px;text-decoration:none;border-radius:8px;">Back to Scraper</a></div></body></html>'


@app.route('/api/sites')
def api_sites():
    sites = get_config_sites('data/scraping.db')
    return jsonify({'sites': [{'id': i, 'name': s['name'], 'url': s['url']} for i, s in enumerate(sites)]})


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Flask news scraper UI')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--port', type=int, default=5001, help='Port number')
    args = parser.parse_args()
    app.run(debug=False, host=args.host, port=args.port)