"""Minimal Flask interface for the JSON-driven scraper runtime."""

from __future__ import annotations

import json
from pathlib import Path

from flask import Flask, jsonify, request

from news_scraper.config import InputConfig, ProxyConfig, load_json_model
from news_scraper.config.models import SiteCatalog
from news_scraper.scraping import ScraperRunner, default_runtime_config


def create_app() -> Flask:
    """Create the Flask app."""

    app = Flask(__name__)
    app.secret_key = "news-scraper-secret-key"
    runtime = default_runtime_config(Path(__file__).resolve().parents[2])
    app.config["RUNTIME"] = runtime
    return app


app = create_app()


def load_sites() -> list[dict[str, str]]:
    """Load active sites from the JSON site catalog."""

    runtime = app.config["RUNTIME"]
    catalog = load_json_model(runtime.catalog_path, SiteCatalog)
    return [
        {"name": site.site_name, "url": str(site.base_url)}
        for site in catalog.sites
        if site.active
    ]


@app.route("/")
def index() -> str:
    """Render a compact HTML control panel."""

    runtime = app.config["RUNTIME"]
    sites = load_sites()
    data_dir = runtime.output_dir

    if not sites:
        return (
            "<!DOCTYPE html><html><head><title>The Rise of the Phoenix</title>"
            "<style>body{font-family:Arial,sans-serif;background:#152238;color:#fff;margin:0;padding:40px;}"
            ".container{max-width:800px;margin:0 auto;}.title{font-size:36px;font-weight:bold;margin-bottom:20px;}"
            ".subtitle{color:#c7d0dc;font-size:16px;margin-bottom:20px;}</style></head>"
            "<body><div class='container'><h1 class='title'>The Rise of the Phoenix</h1>"
            "<p class='subtitle'>No active sites found in the JSON catalog.</p>"
            f"<p>Update <code>{runtime.catalog_path}</code> and <code>{runtime.selectors_path}</code>.</p>"
            "</div></body></html>"
        )

    options = "".join(
        f"<option value='{site['name']}'>{site['name']} ({site['url']})</option>"
        for site in sites
    )
    return (
        "<!DOCTYPE html><html><head><title>The Rise of the Phoenix</title>"
        "<style>body{font-family:Arial,sans-serif;background:#edf2f7;padding:40px 20px;}"
        ".container{max-width:820px;margin:0 auto;background:#fff;border-radius:16px;box-shadow:0 20px 60px rgba(0,0,0,.12);overflow:hidden;}"
        ".header{background:#12355b;color:#fff;padding:28px 32px;}"
        ".content{padding:28px 32px;}form{display:grid;gap:14px;}select,input{padding:12px;border:1px solid #cbd5e0;border-radius:8px;font-size:15px;}"
        "button{padding:14px 18px;background:#12355b;color:#fff;border:none;border-radius:8px;font-size:16px;cursor:pointer;}"
        ".note{margin-top:18px;padding:14px;background:#f7fafc;border-left:4px solid #12355b;border-radius:8px;color:#334155;}</style></head>"
        "<body><div class='container'><div class='header'><h1>The Rise of the Phoenix</h1></div><div class='content'>"
        f"<p>Outputs are written to <code>{data_dir}</code>.</p>"
        "<form method='POST' action='/scrape'>"
        "<label>Site</label>"
        f"<select name='site_name' required>{options}</select>"
        "<label>Mode</label>"
        "<select name='mode'><option value='current'>Current</option><option value='historic'>Historic</option></select>"
        "<label>Max items</label><input type='number' name='max_items_per_site' value='25' min='1' max='500'>"
        "<label>Historic cutoff date (ISO 8601, historic mode only)</label>"
        "<input type='text' name='historic_cutoff_date' placeholder='2025-01-01T00:00:00Z'>"
        "<button type='submit'>Run Scrape</button>"
        "</form>"
        "<div class='note'>Selectors and categories come from the JSON catalog files, not SQLite.</div>"
        "</div></div></body></html>"
    )


@app.route("/scrape", methods=["POST"])
def scrape() -> tuple[str, int] | str:
    """Run the scraper for a single selected site."""

    site_name = request.form.get("site_name", "").strip()
    mode = request.form.get("mode", "current").strip()
    max_items_per_site = int(request.form.get("max_items_per_site", "25"))
    cutoff = request.form.get("historic_cutoff_date", "").strip() or None

    if not site_name:
        return jsonify({"error": "Please select a site"}), 400
    if mode not in {"current", "historic"}:
        return jsonify({"error": "Mode must be 'current' or 'historic'"}), 400
    if mode == "historic" and not cutoff:
        return jsonify({"error": "Historic mode requires a cutoff date"}), 400

    runtime = app.config["RUNTIME"]
    runner = ScraperRunner(runtime)
    input_payload = InputConfig(
        sites_to_scrape=[site_name],
        max_items_per_site=max_items_per_site,
        historic_cutoff_date=cutoff if mode == "historic" else None,
        proxy_config=ProxyConfig(),
    )
    datasets = runner.run(input_payload)
    result_path = runtime.output_dir / "success_dataset.json"

    return (
        "<!DOCTYPE html><html><head><title>Scrape Complete</title>"
        "<style>body{font-family:Arial,sans-serif;background:#edf2f7;padding:40px 20px;}"
        ".box{max-width:720px;margin:0 auto;background:#fff;border-radius:16px;padding:28px;box-shadow:0 20px 60px rgba(0,0,0,.12);}</style></head>"
        "<body><div class='box'>"
        "<h1>Scrape Complete</h1>"
        f"<p><strong>Site:</strong> {site_name}</p>"
        f"<p><strong>Mode:</strong> {mode}</p>"
        f"<p><strong>Success items:</strong> {len(datasets.success_dataset)}</p>"
        f"<p><strong>Error items:</strong> {len(datasets.error_log_dataset)}</p>"
        f"<p><strong>Success dataset:</strong> {result_path}</p>"
        f"<pre>{json.dumps([item.model_dump(mode='json') for item in datasets.success_dataset[:2]], indent=2)}</pre>"
        "<p><a href='/'>Back</a></p>"
        "</div></body></html>"
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Flask JSON scraper UI")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5001)
    args = parser.parse_args()
    app.run(debug=False, host=args.host, port=args.port)
