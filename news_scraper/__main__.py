"""CLI entry point for the config-driven news scraper."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from news_scraper.config import InputConfig
from news_scraper.scraping.engine import ScraperRunner, default_runtime_config


def build_parser() -> argparse.ArgumentParser:
    """Build the command line parser."""

    parser = argparse.ArgumentParser(description="The Rise of the Phoenix news scraper")
    parser.add_argument(
        "--input",
        default="INPUT.json",
        help="Path to the Apify-style INPUT.json file",
    )
    parser.add_argument(
        "--catalog",
        help="Override the site catalog JSON path",
    )
    parser.add_argument(
        "--selectors",
        help="Override the selector map JSON path",
    )
    parser.add_argument(
        "--tracker",
        help="Override the category pagination tracker JSON path",
    )
    parser.add_argument(
        "--output-dir",
        help="Override the output directory for success and error datasets",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Primary fetch timeout in seconds",
    )
    return parser


def load_input(path: str | Path) -> InputConfig:
    """Load and validate INPUT.json."""

    input_path = Path(path)
    if not input_path.exists():
        default_input = InputConfig().model_dump(mode="json")
        input_path.write_text(json.dumps(default_input, indent=2) + "\n", encoding="utf-8")
    return InputConfig.model_validate_json(input_path.read_text(encoding="utf-8"))


def main() -> None:
    """Run the scraper."""

    args = build_parser().parse_args()
    runtime = default_runtime_config()

    if args.catalog:
        runtime.catalog_path = Path(args.catalog)
    if args.selectors:
        runtime.selectors_path = Path(args.selectors)
    if args.tracker:
        runtime.tracker_path = Path(args.tracker)
    if args.output_dir:
        runtime.output_dir = Path(args.output_dir)

    input_config = load_input(args.input)
    runner = ScraperRunner(runtime, timeout=args.timeout)
    datasets = runner.run(input_config)

    print("The Rise of the Phoenix")
    print(f"Execution mode: {input_config.execution_mode.value}")
    print(f"Success dataset items: {len(datasets.success_dataset)}")
    print(f"Error dataset items: {len(datasets.error_log_dataset)}")
    print(f"Success dataset: {runtime.output_dir / 'success_dataset.json'}")
    print(f"Error log dataset: {runtime.output_dir / 'error_log_dataset.json'}")


if __name__ == "__main__":
    main()
