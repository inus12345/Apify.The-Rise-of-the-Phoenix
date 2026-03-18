"""Apply blocking-strategy fixes from a category quality report."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from ..database.models import ScrapeStrategy, SiteConfig
from ..database.session import get_primary_session


@dataclass
class SiteFixResult:
    site_id: int
    site_name: str
    domain: Optional[str]
    pass_count: int
    non_pass_count: int
    listing_fail_count: int
    applied: bool
    reason: str
    requires_proxy: Optional[bool]
    anti_bot_protection: Optional[str]
    fallback_engine_chain: Optional[List[str]]


def _load_results(path: Path) -> List[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        return payload["results"]
    if isinstance(payload, list):
        return payload
    raise ValueError(f"Unsupported report format: {path}")


def _merge_unique(existing: Optional[List[str]], additions: List[str]) -> List[str]:
    values = list(existing or [])
    seen = {str(v).strip().lower() for v in values if isinstance(v, str)}
    for item in additions:
        key = item.strip().lower()
        if key and key not in seen:
            values.append(item)
            seen.add(key)
    return values


def apply_fixes(
    *,
    report_path: Path,
    min_non_pass: int = 2,
    min_listing_fail_ratio: float = 0.6,
    dry_run: bool = False,
) -> dict:
    rows = _load_results(report_path)

    by_site: Dict[int, dict] = defaultdict(lambda: {
        "site_name": "",
        "domain": None,
        "pass_count": 0,
        "non_pass_count": 0,
        "listing_fail_count": 0,
        "errors": set(),
    })

    for row in rows:
        site_id = int(row.get("site_id"))
        item = by_site[site_id]
        item["site_name"] = row.get("site_name") or item["site_name"]
        site_url = row.get("site_url") or ""
        item["domain"] = site_url.replace("https://", "").replace("http://", "").split("/")[0] or item["domain"]
        status = str(row.get("status") or "")
        error = str(row.get("error") or "")
        if status == "pass":
            item["pass_count"] += 1
        else:
            item["non_pass_count"] += 1
            if error:
                item["errors"].add(error)
            if error == "listing_fetch_failed":
                item["listing_fail_count"] += 1

    session = next(get_primary_session())
    results: List[SiteFixResult] = []
    try:
        for site_id, agg in sorted(by_site.items()):
            non_pass = int(agg["non_pass_count"])
            if non_pass < max(int(min_non_pass), 1):
                results.append(
                    SiteFixResult(
                        site_id=site_id,
                        site_name=agg["site_name"],
                        domain=agg["domain"],
                        pass_count=int(agg["pass_count"]),
                        non_pass_count=non_pass,
                        listing_fail_count=int(agg["listing_fail_count"]),
                        applied=False,
                        reason="below_non_pass_threshold",
                        requires_proxy=None,
                        anti_bot_protection=None,
                        fallback_engine_chain=None,
                    )
                )
                continue

            listing_ratio = (agg["listing_fail_count"] / non_pass) if non_pass else 0.0
            all_failed = int(agg["pass_count"]) == 0 and non_pass > 0
            needs_blocking_fix = all_failed or listing_ratio >= float(min_listing_fail_ratio)

            if not needs_blocking_fix:
                results.append(
                    SiteFixResult(
                        site_id=site_id,
                        site_name=agg["site_name"],
                        domain=agg["domain"],
                        pass_count=int(agg["pass_count"]),
                        non_pass_count=non_pass,
                        listing_fail_count=int(agg["listing_fail_count"]),
                        applied=False,
                        reason="mixed_results_no_blocking_fix",
                        requires_proxy=None,
                        anti_bot_protection=None,
                        fallback_engine_chain=None,
                    )
                )
                continue

            site = session.query(SiteConfig).filter(SiteConfig.id == site_id).first()
            if site is None:
                results.append(
                    SiteFixResult(
                        site_id=site_id,
                        site_name=agg["site_name"],
                        domain=agg["domain"],
                        pass_count=int(agg["pass_count"]),
                        non_pass_count=non_pass,
                        listing_fail_count=int(agg["listing_fail_count"]),
                        applied=False,
                        reason="site_not_found",
                        requires_proxy=None,
                        anti_bot_protection=None,
                        fallback_engine_chain=None,
                    )
                )
                continue

            strategy = site.scrape_strategy
            if strategy is None:
                strategy = ScrapeStrategy(site_config_id=site.id)
                session.add(strategy)

            blocking_signals = sorted(agg["errors"])
            bypass = _merge_unique(
                strategy.bypass_techniques if isinstance(strategy.bypass_techniques, list) else [],
                [
                    "residential_proxy_pool",
                    "session_cookie_reuse",
                    "user_agent_rotation",
                    "captcha_detection_and_escalation",
                ],
            )

            strategy.scraper_engine = strategy.scraper_engine or "scrapling"
            strategy.fallback_engine_chain = ["pydoll", "selenium", "beautifulsoup"]
            strategy.requires_proxy = True
            strategy.rate_limit_per_minute = strategy.rate_limit_per_minute or 20
            strategy.blocking_signals = blocking_signals
            strategy.bypass_techniques = bypass
            strategy.anti_bot_protection = strategy.anti_bot_protection or "waf_or_access_gate"
            strategy.notes = (
                f"{(strategy.notes or '').strip()} "
                f"[auto-fix {datetime.now().strftime('%Y-%m-%d')}: "
                f"non-pass={non_pass}, listing-fail={agg['listing_fail_count']}]"
            ).strip()

            if not dry_run:
                session.flush()

            results.append(
                SiteFixResult(
                    site_id=site.id,
                    site_name=site.name,
                    domain=site.domain,
                    pass_count=int(agg["pass_count"]),
                    non_pass_count=non_pass,
                    listing_fail_count=int(agg["listing_fail_count"]),
                    applied=True,
                    reason="blocking_strategy_updated" if not dry_run else "would_update_blocking_strategy",
                    requires_proxy=strategy.requires_proxy,
                    anti_bot_protection=strategy.anti_bot_protection,
                    fallback_engine_chain=strategy.fallback_engine_chain,
                )
            )

        if dry_run:
            session.rollback()
        else:
            session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    summary = {
        "total_sites_in_report": len(by_site),
        "sites_marked_for_blocking_fix": sum(1 for r in results if r.applied),
        "dry_run": dry_run,
        "generated_at": datetime.now().isoformat(),
        "report_path": str(report_path),
    }

    return {
        "summary": summary,
        "results": [asdict(r) for r in results],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply blocking strategy fixes from category quality report.")
    parser.add_argument(
        "--report",
        type=str,
        default="data/reports/category_quality_full_http_20260312.json",
        help="Path to category quality report JSON",
    )
    parser.add_argument("--min-non-pass", type=int, default=2, help="Minimum non-pass categories before applying fix")
    parser.add_argument(
        "--min-listing-fail-ratio",
        type=float,
        default=0.6,
        help="Minimum listing_fetch_failed / non_pass ratio to apply blocking fix",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing to DB")
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output path for applied-fix summary JSON",
    )
    args = parser.parse_args()

    payload = apply_fixes(
        report_path=Path(args.report),
        min_non_pass=args.min_non_pass,
        min_listing_fail_ratio=args.min_listing_fail_ratio,
        dry_run=args.dry_run,
    )

    out = Path(args.output) if args.output else Path(
        f"data/reports/blocking_strategy_fixes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print("Blocking strategy fix complete.")
    print(f"  Sites in report:  {payload['summary']['total_sites_in_report']}")
    print(f"  Sites updated:    {payload['summary']['sites_marked_for_blocking_fix']}")
    print(f"  Dry run:          {payload['summary']['dry_run']}")
    print(f"  Output:           {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
