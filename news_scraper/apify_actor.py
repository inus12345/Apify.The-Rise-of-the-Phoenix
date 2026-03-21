"""Apify Actor entrypoint for the JSON-driven news scraper."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

try:
    from apify import Actor
except ModuleNotFoundError:  # pragma: no cover - handled at runtime after dependency install
    Actor = None

from news_scraper.config import InputConfig, ProxyConfig
from news_scraper.scraping import ScraperRunner, default_runtime_config

ERROR_DATASET_NAME = "error-log"
CATEGORY_OPTION_DELIMITER = "|||"


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def normalize_actor_input(raw_input: dict[str, Any] | None) -> InputConfig:
    """Normalize Actor input into the runtime InputConfig."""

    payload = dict(raw_input or {})
    mode = str(payload.get("execution_mode", "") or "").strip().lower()
    no_items_limit = _coerce_bool(payload.pop("no_items_limit", False))
    selected_sites = [str(site).strip() for site in payload.get("sites_to_scrape", []) or [] if str(site).strip()]

    site_category_filters = payload.pop("site_category_filters", []) or []
    categories_to_scrape = payload.pop("categories_to_scrape", []) or []
    category_filters = dict(payload.get("category_filters") or {})

    for item in site_category_filters:
        if not isinstance(item, dict):
            continue
        site_name = str(item.get("site_name", "")).strip()
        category_urls = item.get("category_urls", []) or []
        if not site_name:
            continue
        cleaned_urls = [str(url).strip() for url in category_urls if str(url).strip()]
        if cleaned_urls:
            category_filters[site_name] = cleaned_urls

    for value in categories_to_scrape:
        if not isinstance(value, str):
            continue
        raw_pair = value.strip()
        if not raw_pair or CATEGORY_OPTION_DELIMITER not in raw_pair:
            continue
        site_name, category_url = raw_pair.split(CATEGORY_OPTION_DELIMITER, 1)
        site_name = site_name.strip()
        category_url = category_url.strip()
        if not site_name or not category_url:
            continue
        category_filters.setdefault(site_name, []).append(category_url)

    for site_name, urls in list(category_filters.items()):
        deduped = sorted({str(url).strip() for url in urls if str(url).strip()})
        if deduped:
            category_filters[site_name] = deduped
        else:
            category_filters.pop(site_name, None)

    if selected_sites:
        selected_set = set(selected_sites)
        category_filters = {
            site_name: urls
            for site_name, urls in category_filters.items()
            if site_name in selected_set
        }

    payload["sites_to_scrape"] = selected_sites
    payload["category_filters"] = category_filters

    cutoff = payload.get("historic_cutoff_date")
    if cutoff == "":
        payload["historic_cutoff_date"] = None

    if mode in {"current", "historic"}:
        payload["execution_mode"] = mode
    elif payload.get("historic_cutoff_date") is not None:
        payload["execution_mode"] = "historic"
    else:
        payload["execution_mode"] = "current"

    if payload["execution_mode"] == "current":
        payload["historic_cutoff_date"] = None

    payload["no_items_limit"] = no_items_limit
    if no_items_limit:
        payload["max_items_per_site"] = None
    elif payload.get("max_items_per_site") == "":
        payload["max_items_per_site"] = None

    payload.setdefault("sites_to_scrape", [])
    payload.setdefault("max_items_per_site", 50)
    payload.setdefault(
        "proxy_config",
        {
            "useApifyProxy": True,
            "apifyProxyGroups": [],
        },
    )

    return InputConfig.model_validate(payload)


async def prepare_proxy(proxy_config: ProxyConfig) -> None:
    """Resolve an Apify proxy URL for the existing sync scraper pipeline."""

    if Actor is None:  # pragma: no cover - defensive runtime guard
        raise RuntimeError("The 'apify' package is required to run the Apify Actor entrypoint.")

    if proxy_config.proxyUrls:
        os.environ["APIFY_PROXY_URL"] = proxy_config.proxyUrls[0]
        Actor.log.info("Using custom proxy URL from input.")
        return

    if not proxy_config.useApifyProxy:
        Actor.log.info("Proxy disabled by input configuration.")
        return

    actor_proxy_input: dict[str, Any] = {
        "useApifyProxy": True,
    }
    if proxy_config.apifyProxyGroups:
        actor_proxy_input["apifyProxyGroups"] = proxy_config.apifyProxyGroups
    if proxy_config.countryCode:
        actor_proxy_input["countryCode"] = proxy_config.countryCode

    proxy_configuration = await Actor.create_proxy_configuration(actor_proxy_input=actor_proxy_input)
    if proxy_configuration is None:
        Actor.log.warning("Apify proxy configuration could not be created; continuing without proxy.")
        return

    new_proxy_url = await proxy_configuration.new_url()
    if new_proxy_url:
        os.environ["APIFY_PROXY_URL"] = new_proxy_url
        Actor.log.info("Apify proxy URL resolved and configured.")
    else:
        Actor.log.warning("Apify proxy configuration returned no URL; continuing without proxy.")


async def push_datasets(runner: ScraperRunner, input_config: InputConfig) -> dict[str, Any]:
    """Run the scraper and push outputs to Apify datasets."""

    if Actor is None:  # pragma: no cover - defensive runtime guard
        raise RuntimeError("The 'apify' package is required to run the Apify Actor entrypoint.")

    datasets = await asyncio.to_thread(runner.run, input_config)
    success_items = [item.model_dump(mode="json") for item in datasets.success_dataset]
    error_items = [item.model_dump(mode="json") for item in datasets.error_log_dataset]

    if success_items:
        await Actor.push_data(success_items)

    if error_items:
        error_dataset = await Actor.open_dataset(name=ERROR_DATASET_NAME)
        await error_dataset.push_data(error_items)
        Actor.log.warning("Sample scrape errors: %s", error_items[:3])

    summary = {
        "executionMode": input_config.execution_mode.value,
        "successItemCount": len(success_items),
        "errorItemCount": len(error_items),
        "errorDatasetName": ERROR_DATASET_NAME,
        "sitesRequested": input_config.sites_to_scrape,
        "categoryFilters": input_config.category_filters,
    }
    await Actor.set_value("OUTPUT", summary)
    return summary


async def main() -> None:
    """Actor runtime entrypoint."""

    if Actor is None:  # pragma: no cover - defensive runtime guard
        raise RuntimeError("The 'apify' package is required to run the Apify Actor entrypoint.")

    async with Actor:
        raw_input = await Actor.get_input() or {}
        input_config = normalize_actor_input(raw_input)
        await prepare_proxy(input_config.proxy_config)

        runtime = default_runtime_config(Path.cwd())
        runner = ScraperRunner(runtime)

        Actor.log.info(
            "Starting scraper run in %s mode for %s with max_items_per_site=%s (proxy: useApifyProxy=%s, customProxy=%s)",
            input_config.execution_mode.value,
            input_config.sites_to_scrape or "all active sites",
            input_config.max_items_per_site,
            input_config.proxy_config.useApifyProxy,
            bool(input_config.proxy_config.proxyUrls),
        )

        summary = await push_datasets(runner, input_config)
        Actor.log.info("Actor run completed: %s", summary)


if __name__ == "__main__":
    asyncio.run(main())
