"""Bootstrap-based Flask UI for the JSON-driven scraper runtime."""

from __future__ import annotations

import argparse
import json
import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

from flask import Flask, jsonify, render_template, request

from news_scraper.config import InputConfig, ProxyConfig, load_json_model, save_json_data, utc_now
from news_scraper.config.models import CategoryPaginationTracker, SiteCatalog
from news_scraper.scraping import ScraperRunner, default_runtime_config

RUNS_LOCK = threading.Lock()
RUN_EXECUTION_LOCK = threading.Lock()
RUNS: dict[str, dict[str, Any]] = {}


def create_app() -> Flask:
    """Create the Flask app."""

    app = Flask(__name__)
    app.secret_key = "news-scraper-secret-key"
    runtime = default_runtime_config(Path(__file__).resolve().parents[2])
    app.config["RUNTIME"] = runtime
    app.config["FLASK_RUN_OUTPUT_DIR"] = runtime.output_dir / "flask_runs"
    return app


app = create_app()


def load_site_options() -> list[dict[str, Any]]:
    """Load active sites plus category choices from the JSON registries."""

    runtime = app.config["RUNTIME"]
    catalog = load_json_model(runtime.catalog_path, SiteCatalog)
    tracker = load_json_model(runtime.tracker_path, CategoryPaginationTracker)
    tracker_by_name = {site.site_name: site for site in tracker.sites}

    options: list[dict[str, Any]] = []
    for site in sorted((site for site in catalog.sites if site.active), key=lambda entry: entry.site_name.lower()):
        tracked = tracker_by_name.get(site.site_name)
        categories = []
        if tracked:
            categories = [
                {
                    "name": category.category_name,
                    "url": str(category.category_url),
                    "known_pages": category.total_known_pages,
                }
                for category in tracked.categories
            ]
        if not categories:
            categories = [
                {
                    "name": "front_page",
                    "url": str(site.base_url),
                    "known_pages": 1,
                }
            ]

        options.append(
            {
                "name": site.site_name,
                "url": str(site.base_url),
                "country": site.country,
                "region": site.region,
                "language": site.language,
                "technology": site.underlying_tech,
                "categories": categories,
            }
        )

    return options


def has_active_run() -> bool:
    """Return whether a run is currently queued or in flight."""

    with RUNS_LOCK:
        return any(run["status"] in {"queued", "running"} for run in RUNS.values())


def sanitize_run_request(payload: dict[str, Any], site_options: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate and normalize a frontend run request."""

    available_sites = {site["name"]: site for site in site_options}
    selected_sites = [str(site).strip() for site in payload.get("sites", []) if str(site).strip()]
    if not selected_sites:
        raise ValueError("Select at least one website.")

    unknown_sites = [site for site in selected_sites if site not in available_sites]
    if unknown_sites:
        raise ValueError(f"Unknown or inactive sites: {', '.join(sorted(unknown_sites))}")

    mode = str(payload.get("mode", "current")).strip().lower()
    if mode not in {"current", "historic"}:
        raise ValueError("Mode must be either current or historic.")

    try:
        max_items_per_site = int(payload.get("max_items_per_site", 10))
    except (TypeError, ValueError) as exc:
        raise ValueError("Max items per site must be a number.") from exc
    if max_items_per_site < 1 or max_items_per_site > 1000:
        raise ValueError("Max items per site must be between 1 and 1000.")

    historic_cutoff_date = str(payload.get("historic_cutoff_date", "") or "").strip() or None
    if mode == "historic" and not historic_cutoff_date:
        raise ValueError("Historic mode requires a cutoff date.")
    historic_max_pages_raw = payload.get("historic_max_pages_per_category")
    if historic_max_pages_raw in (None, ""):
        historic_max_pages_per_category: int | None = None
    else:
        try:
            historic_max_pages_per_category = int(historic_max_pages_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("Historic pages per category must be a number.") from exc
        if historic_max_pages_per_category < 1 or historic_max_pages_per_category > 1000:
            raise ValueError("Historic pages per category must be between 1 and 1000.")
    if mode != "historic":
        historic_max_pages_per_category = None

    raw_categories = payload.get("categories", {}) or {}
    category_filters: dict[str, list[str]] = {}
    for site_name in selected_sites:
        requested = raw_categories.get(site_name, []) or []
        available_category_urls = {
            category["url"]
            for category in available_sites[site_name]["categories"]
        }
        sanitized = [str(category_url).strip() for category_url in requested if str(category_url).strip()]
        sanitized = [category_url for category_url in sanitized if category_url in available_category_urls]
        if sanitized:
            category_filters[site_name] = sorted(set(sanitized))

    return {
        "sites": selected_sites,
        "category_filters": category_filters,
        "mode": mode,
        "max_items_per_site": max_items_per_site,
        "historic_cutoff_date": historic_cutoff_date,
        "historic_max_pages_per_category": historic_max_pages_per_category,
    }


def build_run_state(run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Create the initial JSON payload exposed to the frontend."""

    selected_category_count = sum(len(values) for values in payload["category_filters"].values())
    return {
        "run_id": run_id,
        "status": "queued",
        "created_at": utc_now().isoformat(),
        "updated_at": utc_now().isoformat(),
        "request": {
            "sites": payload["sites"],
            "mode": payload["mode"],
            "max_items_per_site": payload["max_items_per_site"],
            "historic_cutoff_date": payload["historic_cutoff_date"],
            "historic_max_pages_per_category": payload["historic_max_pages_per_category"],
            "category_filters": payload["category_filters"],
        },
        "progress": {
            "percent": 0,
            "current_site": None,
            "total_sites": len(payload["sites"]),
            "site_index": 0,
            "total_targets": 0,
            "completed_targets": 0,
            "site_total_targets": 0,
            "site_processed_targets": 0,
            "message": "Waiting to start…",
        },
        "summary": {
            "success_items": 0,
            "error_items": 0,
            "selected_site_count": len(payload["sites"]),
            "selected_category_count": selected_category_count,
        },
        "result": None,
        "events": [],
        "error": None,
    }


def append_event(run: dict[str, Any], message: str, *, level: str = "info") -> None:
    """Append a short status event for the frontend activity feed."""

    run["events"].insert(
        0,
        {
            "timestamp": utc_now().isoformat(),
            "level": level,
            "message": message,
        },
    )
    del run["events"][18:]


def progress_message(event: dict[str, Any]) -> str:
    """Convert backend progress events into concise UI text."""

    event_name = event.get("event")
    site_name = event.get("site_name")
    if event_name == "run_started":
        return f"Preparing {event.get('total_sites', 0)} site(s) for {event.get('mode', 'current')} mode."
    if event_name == "site_started" and site_name:
        return f"Scraping {site_name}."
    if event_name == "page_completed" and site_name:
        page_index = event.get("page_index", 0)
        category_url = event.get("category_url", "")
        return f"{site_name}: finished page {page_index} for {category_url}."
    if event_name == "site_completed" and site_name:
        return f"{site_name}: completed with {event.get('site_collected_items', 0)} item(s)."
    if event_name == "site_missing_selectors" and site_name:
        return f"{site_name}: skipped because no selector map was found."
    if event_name == "run_completed":
        return "Scrape finished successfully."
    return "Scrape in progress…"


def update_run_progress(run_id: str, payload: dict[str, Any]) -> None:
    """Update stored run state from backend progress events."""

    with RUNS_LOCK:
        run = RUNS.get(run_id)
        if run is None:
            return

        run["status"] = "running"
        run["updated_at"] = utc_now().isoformat()
        progress = run["progress"]
        progress["percent"] = int(payload.get("percent", progress["percent"]))
        progress["current_site"] = payload.get("site_name", progress["current_site"])
        progress["total_sites"] = int(payload.get("total_sites", progress["total_sites"]))
        progress["site_index"] = int(payload.get("site_index", progress["site_index"]))
        progress["total_targets"] = int(payload.get("total_targets", progress["total_targets"]))
        progress["completed_targets"] = int(payload.get("completed_targets", progress["completed_targets"]))
        progress["site_total_targets"] = int(payload.get("site_total_targets", progress["site_total_targets"]))
        progress["site_processed_targets"] = int(
            payload.get("site_processed_targets", progress["site_processed_targets"])
        )
        progress["message"] = progress_message(payload)
        run["summary"]["success_items"] = int(payload.get("success_items", run["summary"]["success_items"]))
        run["summary"]["error_items"] = int(payload.get("error_items", run["summary"]["error_items"]))

        if payload.get("event") in {"run_started", "site_started", "site_completed", "site_missing_selectors"}:
            append_event(run, progress["message"], level="info")
        elif payload.get("event") == "page_completed":
            append_event(run, progress["message"], level="muted")


def execute_run(run_id: str, payload: dict[str, Any]) -> None:
    """Background job worker for a UI-triggered scrape."""

    with RUN_EXECUTION_LOCK:
        with RUNS_LOCK:
            run = RUNS[run_id]
            run["status"] = "running"
            run["updated_at"] = utc_now().isoformat()
            append_event(run, "Run accepted. Initializing scraper.", level="info")

        runtime = app.config["RUNTIME"]
        flask_output_dir = app.config["FLASK_RUN_OUTPUT_DIR"]
        run_runtime = type(runtime)(
            catalog_path=runtime.catalog_path,
            selectors_path=runtime.selectors_path,
            tracker_path=runtime.tracker_path,
            output_dir=flask_output_dir,
        )
        runner = ScraperRunner(run_runtime)
        input_payload = InputConfig(
            sites_to_scrape=payload["sites"],
            category_filters=payload["category_filters"],
            max_items_per_site=payload["max_items_per_site"],
            historic_cutoff_date=payload["historic_cutoff_date"] if payload["mode"] == "historic" else None,
            historic_max_pages_per_category=(
                payload["historic_max_pages_per_category"] if payload["mode"] == "historic" else None
            ),
            proxy_config=ProxyConfig(),
        )

        try:
            datasets = runner.run(input_payload, progress_callback=lambda event: update_run_progress(run_id, event))
        except Exception as exc:  # pragma: no cover - defensive UI error path
            with RUNS_LOCK:
                run = RUNS[run_id]
                run["status"] = "failed"
                run["updated_at"] = utc_now().isoformat()
                run["error"] = str(exc)
                run["progress"]["message"] = "Run failed."
                append_event(run, f"Run failed: {exc}", level="error")
            return

        finished_at = utc_now()
        timestamp = finished_at.strftime("%Y%m%d_%H%M%S")
        run_suffix = run_id[:8]
        success_path = flask_output_dir / f"success_dataset_{timestamp}_{run_suffix}.json"
        error_path = flask_output_dir / f"error_log_dataset_{timestamp}_{run_suffix}.json"
        save_json_data(
            success_path,
            [item.model_dump(mode="json") for item in datasets.success_dataset],
        )
        save_json_data(
            error_path,
            [item.model_dump(mode="json") for item in datasets.error_log_dataset],
        )

        # Runner persists default filenames; remove them so Flask output stays timestamped-only.
        default_success = flask_output_dir / "success_dataset.json"
        default_error = flask_output_dir / "error_log_dataset.json"
        if default_success.exists():
            default_success.unlink()
        if default_error.exists():
            default_error.unlink()

        with RUNS_LOCK:
            run = RUNS[run_id]
            run["status"] = "completed"
            run["updated_at"] = finished_at.isoformat()
            run["progress"]["percent"] = 100
            run["progress"]["message"] = "Scrape finished successfully."
            run["summary"]["success_items"] = len(datasets.success_dataset)
            run["summary"]["error_items"] = len(datasets.error_log_dataset)
            run["result"] = {
                "success_dataset_path": str(success_path),
                "error_dataset_path": str(error_path),
                "success_preview": [item.model_dump(mode="json") for item in datasets.success_dataset[:3]],
            }
            append_event(
                run,
                f"Run complete: {len(datasets.success_dataset)} success item(s), "
                f"{len(datasets.error_log_dataset)} error item(s).",
                level="success",
            )


@app.route("/")
def index() -> str:
    """Render the Bootstrap control panel."""

    flask_output_dir = app.config["FLASK_RUN_OUTPUT_DIR"]
    site_options = load_site_options()
    return render_template(
        "dashboard.html",
        site_options=site_options,
        site_data_json=json.dumps(site_options, ensure_ascii=False),
        output_dir=str(flask_output_dir),
        site_count=len(site_options),
        category_count=sum(len(site["categories"]) for site in site_options),
    )


@app.get("/api/options")
def options() -> Any:
    """Return the active site and category options."""

    flask_output_dir = app.config["FLASK_RUN_OUTPUT_DIR"]
    return jsonify(
        {
            "sites": load_site_options(),
            "output_dir": str(flask_output_dir),
            "active_run": has_active_run(),
        }
    )


@app.post("/api/runs")
def start_run() -> Any:
    """Start a background scrape run."""

    if has_active_run():
        return jsonify({"error": "A scrape is already running. Wait for it to finish first."}), 409

    payload = request.get_json(silent=True) or {}
    site_options = load_site_options()
    try:
        sanitized = sanitize_run_request(payload, site_options)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    run_id = uuid4().hex
    run_state = build_run_state(run_id, sanitized)
    with RUNS_LOCK:
        RUNS[run_id] = run_state

    worker = threading.Thread(target=execute_run, args=(run_id, sanitized), daemon=True)
    worker.start()
    return jsonify(run_state), 202


@app.get("/api/runs/<run_id>")
def get_run(run_id: str) -> Any:
    """Return run state for the polling frontend."""

    with RUNS_LOCK:
        run = RUNS.get(run_id)
        if run is None:
            return jsonify({"error": "Run not found"}), 404
        return jsonify(run)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Flask JSON scraper UI")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5001)
    args = parser.parse_args()
    app.run(debug=False, host=args.host, port=args.port)
