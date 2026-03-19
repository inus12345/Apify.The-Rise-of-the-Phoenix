"""Utility script to verify site accessibility and selector health."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from news_scraper.scraping.engine import ScraperRunner, default_runtime_config


def build_parser() -> argparse.ArgumentParser:
    """Build CLI args for site verification."""

    parser = argparse.ArgumentParser(description="Verify scraper site selectors")
    parser.add_argument(
        "--sites",
        nargs="*",
        default=None,
        help="Optional subset of site names to verify",
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
        "--output",
        default="news_scraper/data/exports/verification_report.json",
        help="Where to write the verification JSON report",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Primary fetch timeout in seconds",
    )
    return parser


def main() -> None:
    """Run verification and emit a JSON report."""

    args = build_parser().parse_args()
    runtime = default_runtime_config()

    if args.catalog:
        runtime.catalog_path = Path(args.catalog)
    if args.selectors:
        runtime.selectors_path = Path(args.selectors)
    if args.tracker:
        runtime.tracker_path = Path(args.tracker)

    runner = ScraperRunner(runtime, timeout=args.timeout)
    report = runner.verify_sites(args.sites)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")

    passed = sum(1 for result in report.results if result.success)
    failed = len(report.results) - passed
    print(f"Verified sites: {len(report.results)}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Report: {output_path}")


if __name__ == "__main__":
    main()
