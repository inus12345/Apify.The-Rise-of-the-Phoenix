"""Apify-ready entrypoint for config-driven scraping runs."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import httpx

from .core.config import get_logger
from .database.session import get_session, init_db
from .pipelines.config_driven import run_config_scrape

logger = get_logger(__name__)


def _load_actor_input() -> Dict[str, Any]:
    """
    Load actor input payload.

    Supports:
    - `APIFY_INPUT` JSON string
    - `APIFY_INPUT_FILE` path to JSON file
    - local `INPUT.json`
    """
    raw_input = os.getenv("APIFY_INPUT")
    if raw_input:
        try:
            parsed = json.loads(raw_input)
            if isinstance(parsed, dict):
                return parsed
            raise ValueError("APIFY_INPUT must decode to a JSON object")
        except (ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"Failed to parse APIFY_INPUT: {exc}") from exc

    input_file = os.getenv("APIFY_INPUT_FILE", "INPUT.json")
    path = Path(input_file)
    if path.exists():
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                return parsed
            raise ValueError(f"{input_file} must contain a JSON object")
        except (ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"Failed to parse actor input file '{input_file}': {exc}") from exc

    return {}


def _parse_cutoff_date(raw_value: Any) -> Optional[datetime]:
    """Parse cutoff date from actor input string formats."""
    if raw_value in (None, ""):
        return None

    if isinstance(raw_value, datetime):
        return raw_value

    if isinstance(raw_value, str):
        value = raw_value.strip()
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return datetime.strptime(value, "%Y-%m-%d")

    raise ValueError("cutoff_date must be an ISO datetime or YYYY-MM-DD string")


def _parse_string_list(value: Any) -> Optional[List[str]]:
    """
    Parse list-like actor input values.

    Accepts:
    - JSON array: ["a", "b"]
    - comma-separated string: "a,b"
    - single scalar: "a"
    """
    if value in (None, "", []):
        return None

    if isinstance(value, list):
        parsed = [str(item).strip() for item in value if str(item).strip()]
        return parsed or None

    if isinstance(value, str):
        if "," in value:
            parsed = [item.strip() for item in value.split(",") if item.strip()]
            return parsed or None
        text = value.strip()
        return [text] if text else None

    text = str(value).strip()
    return [text] if text else None


def _parse_bool(value: Any, default: bool = False) -> bool:
    """Parse boolean-like actor input values."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    return default


def _parse_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    """Parse optional integer input values safely."""
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _split_websites_selector(value: Any) -> tuple[Optional[List[str]], Optional[List[str]]]:
    """Split generic `websites` input into URL and name selectors."""
    values = _parse_string_list(value)
    if not values:
        return None, None

    urls: List[str] = []
    names: List[str] = []
    for item in values:
        lowered = item.lower()
        if lowered.startswith("http://") or lowered.startswith("https://"):
            urls.append(item)
        else:
            names.append(item)
    return (urls or None, names or None)


def _resolve_actor_output_path() -> Path:
    """
    Resolve output path with Apify-local fallback.

    Priority:
    1. APIFY_OUTPUT_FILE
    2. APIFY_LOCAL_STORAGE_DIR/key_value_stores/default/OUTPUT.json
    3. ./OUTPUT.json
    """
    explicit = os.getenv("APIFY_OUTPUT_FILE")
    if explicit:
        return Path(explicit)

    local_storage_dir = os.getenv("APIFY_LOCAL_STORAGE_DIR")
    if local_storage_dir:
        return Path(local_storage_dir) / "key_value_stores" / "default" / "OUTPUT.json"

    return Path("OUTPUT.json")


def _iter_chunks(seq: List[Dict[str, Any]], size: int) -> Iterator[List[Dict[str, Any]]]:
    if size <= 0:
        yield seq
        return
    for idx in range(0, len(seq), size):
        yield seq[idx : idx + size]


def _apply_safe_site_limit(
    limit: Optional[int],
    *,
    site_urls: Optional[List[str]],
    site_names: Optional[List[str]],
    countries: Optional[List[str]],
    payload: Dict[str, Any],
) -> Optional[int]:
    """
    Apply a conservative default site cap when actor selectors are broad.

    This prevents accidental unbounded runs (e.g., empty input) from sweeping
    the entire catalog in a single execution.
    """
    enforce = _parse_bool(payload.get("enforce_safe_site_limit"), default=True)
    if not enforce:
        return limit
    if limit is not None:
        return max(int(limit), 0)
    if site_urls or site_names or countries:
        return limit

    default_limit = _parse_int(payload.get("default_site_limit"), default=25)
    if default_limit is None or default_limit < 1:
        return 25
    return default_limit


def _push_records_to_apify_dataset(
    records: List[Dict[str, Any]],
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Push records to the default Apify dataset when runtime env is available.

    Uses APIFY_TOKEN + APIFY_DEFAULT_DATASET_ID.
    """
    dataset_id = os.getenv("APIFY_DEFAULT_DATASET_ID")
    token = os.getenv("APIFY_TOKEN")
    if not dataset_id or not token:
        return {"attempted": False, "reason": "dataset env vars not available"}

    if not records:
        return {"attempted": True, "pushed": 0, "status": "skipped_empty"}

    api_base = os.getenv("APIFY_API_BASE_URL", "https://api.apify.com").rstrip("/")
    if api_base.endswith("/v2"):
        endpoint = f"{api_base}/datasets/{dataset_id}/items"
    else:
        endpoint = f"{api_base}/v2/datasets/{dataset_id}/items"
    timeout_seconds = _parse_int(payload.get("apify_dataset_timeout_seconds"), default=60) or 60
    chunk_size = _parse_int(payload.get("apify_dataset_chunk_size"), default=100) or 100
    clean_start = _parse_bool(payload.get("apify_dataset_clean_start"), default=False)

    pushed = 0
    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            for index, chunk in enumerate(_iter_chunks(records, chunk_size)):
                params = {"token": token}
                if clean_start and index == 0:
                    params["clean"] = "true"
                response = client.post(
                    endpoint,
                    params=params,
                    json=chunk,
                    headers={"Content-Type": "application/json; charset=utf-8"},
                )
                response.raise_for_status()
                pushed += len(chunk)
    except Exception as exc:  # pragma: no cover - network/runtime dependent
        logger.warning("Dataset push failed: %s", exc)
        return {
            "attempted": True,
            "pushed": pushed,
            "status": "error",
            "error": str(exc),
        }

    return {"attempted": True, "pushed": pushed, "status": "ok"}


def main() -> int:
    try:
        payload = _load_actor_input()

        config_path = payload.get("config_path", "news_scraper/config/sites_config.yaml")
        mode = str(payload.get("mode", "current") or "current").strip().lower()
        if mode == "historic":
            mode = "historical"
        output_json = payload.get("output_json")
        limit = _parse_int(payload.get("limit"), default=None)
        offset = _parse_int(payload.get("offset", 0), default=0) or 0
        max_pages = _parse_int(payload.get("max_pages"), default=None)
        start_page = _parse_int(payload.get("start_page", 1), default=1) or 1
        end_page = _parse_int(payload.get("end_page"), default=None)
        chunk_id = payload.get("chunk_id")
        story_batch_size = _parse_int(
            payload.get("story_batch_size") or payload.get("stories_per_batch") or payload.get("batch_size"),
            default=200,
        )
        if story_batch_size is None:
            story_batch_size = 200
        elif story_batch_size < 0:
            story_batch_size = 200
        cutoff_date = _parse_cutoff_date(payload.get("cutoff_date"))
        generic_site_urls, generic_site_names = _split_websites_selector(payload.get("websites"))
        site_urls = _parse_string_list(payload.get("site_urls") or payload.get("website_urls"))
        site_names = _parse_string_list(payload.get("site_names"))
        if not site_urls:
            site_urls = generic_site_urls
        if not site_names:
            site_names = generic_site_names
        countries = _parse_string_list(payload.get("countries"))
        limit = _apply_safe_site_limit(
            limit,
            site_urls=site_urls,
            site_names=site_names,
            countries=countries,
            payload=payload,
        )
        allow_deep_historical = _parse_bool(payload.get("allow_deep_historical"), default=False)
        rate_limit = _parse_bool(payload.get("rate_limit"), default=True)
        sync_first = _parse_bool(payload.get("sync_first"), default=True)
        push_to_dataset = _parse_bool(payload.get("push_to_dataset"), default=True)
        include_records_in_output = _parse_bool(payload.get("include_records_in_output"), default=True)

        # Keep historical runs intentionally shallow by default for actor cost/speed.
        normalized_mode = str(mode).lower()
        if normalized_mode in {"historical", "backfill", "full"} and not allow_deep_historical:
            if max_pages is None:
                max_pages = 5
            else:
                max_pages = min(int(max_pages), 10)

        init_db()

        session_gen = get_session()
        db = next(session_gen)
        try:
            result = run_config_scrape(
                db_session=db,
                config_path=config_path,
                mode=mode,
                output_json=output_json,
                limit=limit,
                offset=offset,
                max_pages=max_pages,
                start_page=start_page,
                end_page=end_page,
                chunk_id=chunk_id,
                cutoff_date=cutoff_date,
                site_urls=site_urls,
                site_names=site_names,
                countries=countries,
                enable_rate_limiting=rate_limit,
                sync_first=sync_first,
                story_batch_size=story_batch_size,
            )
        finally:
            db.close()

        if push_to_dataset:
            delivery = _push_records_to_apify_dataset(result.get("records") or [], payload=payload)
            run_metadata = result.get("run_metadata") or {}
            run_metadata["apify_dataset_delivery"] = delivery
            result["run_metadata"] = run_metadata
        if not include_records_in_output:
            result["records"] = []

        actor_output_path = _resolve_actor_output_path()
        actor_output_path.parent.mkdir(parents=True, exist_ok=True)
        actor_output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        return 0
    except Exception as exc:
        logger.exception("Actor execution failed: %s", exc)
        error_payload = {
            "status": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "occurred_at": datetime.utcnow().isoformat() + "Z",
        }
        try:
            actor_output_path = _resolve_actor_output_path()
            actor_output_path.parent.mkdir(parents=True, exist_ok=True)
            actor_output_path.write_text(
                json.dumps(error_payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            logger.exception("Failed to write actor failure output payload.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
