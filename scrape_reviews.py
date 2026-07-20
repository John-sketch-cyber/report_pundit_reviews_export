#!/usr/bin/env python3
"""Report Pundit — weekly review-export scraper (entry point).

Flow (spec §6.2):
  load state (archive) -> scrape all pages -> HEALTH CHECK (no writes yet)
  -> reconcile into archive -> save state atomically -> render Google Sheet.

The health check runs before any mutation, so a network/markup hiccup or a
pagination cap can never falsely flag hundreds of reviews as removed.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from scraper.diff import (
    assert_scrape_is_healthy,
    load_state,
    reconcile,
    run_date_utc,
    save_state_atomic,
    ScrapeHealthError,
)
from scraper.fetch import scrape_all_pages

DEFAULT_STATE = os.path.join(os.path.dirname(__file__), "state", "reviews_state.json")


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description="Scrape Report Pundit reviews weekly.")
    p.add_argument("--state-file", default=DEFAULT_STATE)
    p.add_argument("--max-pages", type=int, default=None, help="Cap pages (testing).")
    p.add_argument("--dry-run", action="store_true", help="Skip the Google Sheet write.")
    return p.parse_args(argv)


def main(argv=None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("scrape_reviews")
    args = _parse_args(argv)

    run_date = run_date_utc()
    log.info("Run date (UTC): %s", run_date)

    archive = load_state(args.state_file)
    current = scrape_all_pages(max_pages=args.max_pages)

    # Fail-safe gate BEFORE any write (§9). Abort non-zero, leave state intact.
    try:
        assert_scrape_is_healthy(current, archive)
    except ScrapeHealthError as exc:
        log.error("ABORT — unhealthy scrape, no state/sheet written: %s", exc)
        return 2

    archive = reconcile(current, archive, run_date)
    live = sum(1 for r in archive.values() if r["status"] == "live")
    removed = sum(1 for r in archive.values() if r["status"] == "removed")
    log.info("Reconciled: %s live, %s removed, %s archived total.", live, removed, len(archive))

    save_state_atomic(args.state_file, archive)
    log.info("State saved: %s", args.state_file)

    if args.dry_run:
        log.info("--dry-run: skipping Google Sheet write.")
        return 0

    sheet_id = os.environ.get("REVIEWS_SHEET_ID")
    creds = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not sheet_id or not creds:
        log.warning(
            "REVIEWS_SHEET_ID / GOOGLE_SERVICE_ACCOUNT_JSON not set; "
            "state written but Sheet NOT updated. Use --dry-run to silence."
        )
        return 0

    from scraper.sheets import write_sheet
    write_sheet(sheet_id, creds, archive)
    return 0


if __name__ == "__main__":
    sys.exit(main())
