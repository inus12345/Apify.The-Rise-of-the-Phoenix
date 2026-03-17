"""Flask web application for The Rise of the Phoenix news scraper."""
import os
from urllib.parse import urlparse
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify

from ..database.session import init_db, get_session
from ..database.models import SiteConfig, ScrapedArticle
from ..scraping.config_registry import SiteConfigRegistry, get_default_sites
from ..scraping.engine import ScraperEngine


def create_app():
    """Create and configure the Flask application."""
    app = Flask(__name__)
    app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-for-phase-4')
    
    # Database path
    app.config['DATABASE_PATH'] = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
        'data', 
        'scraping.db'
    )
    
    return app


app = create_app()


def get_db_session():
    """Get a database session generator."""
    return get_session()


@app.route('/')
def index():
    """Home page - show recent activity and statistics."""
    session_gen = get_db_session()
    db = next(session_gen)
    
    try:
        # Count sites
        total_sites = db.query(SiteConfig).count()
        active_sites = db.query(SiteConfig).filter_by(active=True).count()
        
        # Count articles
        total_articles = db.query(ScrapedArticle).count()
        
        # Get latest scrapes
        recent_sites = db.query(SiteConfig).order_by(
            SiteConfig.last_scraped.desc()
        ).limit(5).all()
        
        # Recent articles
        recent_articles = db.query(ScrapedArticle).order_by(
            ScrapedArticle.id.desc()
        ).limit(10).all()
        
        return render_template('index.html',
                            total_sites=total_sites,
                            active_sites=active_sites,
                            total_articles=total_articles,
                            recent_sites=recent_sites,
                            recent_articles=recent_articles)
    finally:
        db.close()


@app.route('/sites')
def list_sites():
    """List all sites."""
    session_gen = get_db_session()
    db = next(session_gen)
    
    try:
        registry = SiteConfigRegistry(db)
        show_inactive = request.args.get('show_inactive', 'false') == 'true'
        sites = registry.list_sites(active_only=not show_inactive)
        
        return render_template('sites.html',
                             sites=sites,
                             show_inactive=show_inactive)
    finally:
        db.close()


@app.route('/site/add', methods=['GET', 'POST'])
def add_site():
    """Add a new site configuration."""
    if request.method == 'POST':
        session_gen = get_db_session()
        db = next(session_gen)
        
        try:
            url = request.form.get('url')
            name = request.form.get('name') or None
            pattern = request.form.get('pattern') or None
            pages = int(request.form.get('pages', 1))
            active = request.form.get('active') == 'on'
            
            if not url:
                flash('URL is required!', 'error')
                return redirect(url_for('add_site'))

            if not name:
                parsed = urlparse(url)
                name = f"{parsed.netloc.replace('www.', '').replace('.', ' ').title()} News"
            
            registry = SiteConfigRegistry(db)
            site = registry.add_site(
                name=name,
                url=url,
                category_url_pattern=pattern,
                num_pages_to_scrape=pages,
                active=active
            )
            
            flash(f'Site added successfully! (ID: {site.id})', 'success')
            return redirect(url_for('view_site', site_id=site.id))
        except ValueError as e:
            flash(str(e), 'error')
        except Exception as e:
            flash(f'Error adding site: {e}', 'error')
        finally:
            db.close()
    
    return render_template('add_site.html')


@app.route('/site/<int:site_id>')
def view_site(site_id):
    """View a specific site's details."""
    session_gen = get_db_session()
    db = next(session_gen)
    
    try:
        site = db.query(SiteConfig).get(site_id)
        
        if not site:
            flash('Site not found!', 'error')
            return redirect(url_for('list_sites'))
        
        # Get article count
        article_count = db.query(ScrapedArticle).filter_by(
            site_config_id=site_id
        ).count()
        
        # Get recent articles for this site
        recent_articles = db.query(ScrapedArticle).filter_by(
            site_config_id=site_id
        ).order_by(ScrapedArticle.id.desc()).limit(5).all()
        
        return render_template('view_site.html',
                             site=site,
                             article_count=article_count,
                             recent_articles=recent_articles)
    finally:
        db.close()


@app.route('/site/<int:site_id>/edit', methods=['GET', 'POST'])
def edit_site(site_id):
    """Edit a site configuration."""
    session_gen = get_db_session()
    db = next(session_gen)
    
    try:
        site = db.query(SiteConfig).get(site_id)
        
        if not site:
            flash('Site not found!', 'error')
            return redirect(url_for('list_sites'))
        
        if request.method == 'POST':
            site.name = request.form.get('name', site.name)
            site.url = request.form.get('url', site.url)
            site.category_url_pattern = request.form.get('pattern') or None
            site.num_pages_to_scrape = int(request.form.get('pages', 1))
            site.active = request.form.get('active') == 'on'
            
            db.commit()
            flash('Site updated successfully!', 'success')
            return redirect(url_for('view_site', site_id=site.id))
        
        return render_template('edit_site.html', site=site)
    except Exception as e:
        db.rollback()
        flash(f'Error editing site: {e}', 'error')
        return redirect(url_for('list_sites'))
    finally:
        db.close()


@app.route('/site/<int:site_id>/delete', methods=['POST'])
def delete_site(site_id):
    """Delete a site configuration."""
    session_gen = get_db_session()
    db = next(session_gen)
    
    try:
        site = db.query(SiteConfig).get(site_id)
        
        if not site:
            flash('Site not found!', 'error')
            return redirect(url_for('list_sites'))
        
        registry = SiteConfigRegistry(db)
        if registry.delete_site(site_id):
            flash('Site deleted successfully!', 'success')
        else:
            flash('Failed to delete site.', 'error')
    except Exception as e:
        db.rollback()
        flash(f'Error deleting site: {e}', 'error')
    finally:
        db.close()
    
    return redirect(url_for('list_sites'))


@app.route('/site/<int:site_id>/scrape', methods=['POST'])
def scrape_site(site_id):
    """Scrape a specific site."""
    session_gen = get_db_session()
    db = next(session_gen)
    
    try:
        site = db.query(SiteConfig).get(site_id)
        
        if not site:
            flash('Site not found!', 'error')
            return redirect(url_for('list_sites'))
        
        export_csv = request.form.get('export_csv', None) or None
        export_json = request.form.get('export_json', None) or None
        enable_rate_limiting = request.form.get('rate_limit') != 'off'
        
        with ScraperEngine(enable_rate_limiting=enable_rate_limiting) as engine:
            stats = engine.scrape_site(
                site_config=site,
                db_session=db,
                export_csv=export_csv,
                export_json=export_json,
                enable_rate_limiting=enable_rate_limiting,
            )
        
        flash(f'Scraping complete! Saved {stats["articles_saved"]} articles.', 'success')
        return redirect(url_for('view_site', site_id=site.id))
    except Exception as e:
        db.rollback()
        flash(f'Error scraping site: {e}', 'error')
        return redirect(url_for('view_site', site_id=site.id))
    finally:
        db.close()


@app.route('/scrape-all', methods=['POST'])
def scrape_all():
    """Scrape all configured sites."""
    session_gen = get_db_session()
    db = next(session_gen)
    
    try:
        registry = SiteConfigRegistry(db)
        total_sites = len(registry.list_sites(active_only=True))
        
        if total_sites == 0:
            flash('No active sites configured. Add sites first!', 'warning')
            return redirect(url_for('list_sites'))
        
        export_csv = request.form.get('export_csv', None) or None
        export_json = request.form.get('export_json', None) or None
        enable_rate_limiting = request.form.get('rate_limit') != 'off'
        
        with ScraperEngine(enable_rate_limiting=enable_rate_limiting) as engine:
            results = engine.scrape_all_sites(
                db, active_only=True, export_csv=export_csv, export_json=export_json,
                enable_rate_limiting=enable_rate_limiting
            )
        
        total_saved = sum(r.get("articles_saved", 0) for r in results)
        flash(f'Scraping complete! Saved {total_saved} articles from {len(results)} sites.', 'success')
        return redirect(url_for('list_sites'))
    except Exception as e:
        db.rollback()
        flash(f'Error scraping sites: {e}', 'error')
        return redirect(url_for('list_sites'))
    finally:
        db.close()


@app.route('/sites/export')
def export_sites():
    """Export all site configurations to JSON."""
    session_gen = get_db_session()
    db = next(session_gen)
    
    try:
        registry = SiteConfigRegistry(db)
        sites = registry.list_sites(active_only=False)
        
        data = []
        for site in sites:
            site_data = {
                "name": site.name,
                "url": site.url,
                "domain": site.domain,
                "country": site.country or site.location,
                "language": site.language,
                "server_header": site.server_header,
                "server_vendor": site.server_vendor,
                "hosting_provider": site.hosting_provider,
                "technology_stack_summary": site.technology_stack_summary,
                "category_url_pattern": site.category_url_pattern,
                "num_pages_to_scrape": site.num_pages_to_scrape,
                "active": site.active,
                "uses_javascript": site.uses_javascript
            }
            data.append(site_data)
        
        import json
        json_output = json.dumps(data, indent=2)
        
        response = app.response_class(
            response=json_output,
            status=200,
            mimetype='application/json'
        )
        response.headers['Content-Disposition'] = 'attachment; filename=sites_export.json'
        return response
    except Exception as e:
        flash(f'Error exporting sites: {e}', 'error')
        return redirect(url_for('list_sites'))
    finally:
        db.close()


@app.route('/stats')
def stats():
    """Show database and rate limiter statistics."""
    session_gen = get_db_session()
    db = next(session_gen)
    
    try:
        # Count sites
        total_sites = db.query(SiteConfig).count()
        active_sites = db.query(SiteConfig).filter_by(active=True).count()
        
        # Count articles
        total_articles = db.query(ScrapedArticle).count()
        
        # Get latest scrape
        from datetime import datetime, timedelta
        recent_cutoff = datetime.now() - timedelta(days=7)
        recently_scraped = db.query(SiteConfig).filter(
            SiteConfig.last_scraped >= recent_cutoff
        ).count()
        
        return render_template('stats.html',
                            total_sites=total_sites,
                            active_sites=active_sites,
                            total_articles=total_articles,
                            recently_scraped=recently_scraped)
    finally:
        db.close()


@app.route('/api/sites')
def api_list_sites():
    """API endpoint to list all sites (JSON)."""
    session_gen = get_db_session()
    db = next(session_gen)
    
    try:
        registry = SiteConfigRegistry(db)
        sites = registry.list_sites(active_only=False)
        
        data = []
        for site in sites:
            data.append({
                'id': site.id,
                'name': site.name,
                'url': site.url,
                'active': site.active,
                'last_scraped': site.last_scraped.isoformat() if site.last_scraped else None
            })
        
        return jsonify({'sites': data})
    finally:
        db.close()


@app.route('/api/seed', methods=['POST'])
def api_seed():
    """API endpoint to seed default sites."""
    session_gen = get_db_session()
    db = next(session_gen)
    
    try:
        registry = SiteConfigRegistry(db)
        existing_urls = {s.url for s in registry.list_sites(active_only=False)}
        
        added_count = 0
        for site_data in get_default_sites():
            url = site_data["url"]
            if url not in existing_urls:
                registry.add_site(
                    name=site_data["name"],
                    url=url,
                    category_url_pattern=site_data.get("category_url_pattern"),
                    num_pages_to_scrape=site_data.get("num_pages_to_scrape", 1),
                    active=site_data.get("active", True)
                )
                added_count += 1
        
        return jsonify({'added': added_count, 'message': f'Added {added_count} new site(s)'})
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()


if __name__ == '__main__':
    # Initialize database if needed
    os.makedirs(os.path.dirname(app.config['DATABASE_PATH']), exist_ok=True)
    
    try:
        init_db()
    except Exception as e:
        print(f"Warning: Could not initialize database: {e}")
    
    app.run(debug=True, host='0.0.0.0', port=5000)
