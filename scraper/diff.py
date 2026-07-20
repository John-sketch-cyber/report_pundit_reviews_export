"""State reconciliation & health checks (spec §6.2 and §9).

The state file *is* the archive — a single source of truth keyed by
review_id. All three sheet tabs are derived from it each run.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone

log = logging.getLogger("scraper.diff")

MIN_FRACTION_OF_PREV_LIVE = 0.90   # §9 count guard
MAX_PARSE_FAIL_FRACTION = 0.05     # §9 markup-drift guard


def run_date_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def load_state(path: str) -> dict[str, dict]:
    if not os.path.exists(path):
        log.info("No prior state at %s; first run.", path)
        return {}
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return data.get("reviews", data) if isinstance(data, dict) else {}


def save_state_atomic(path: str, archive: dict[str, dict]) -> None:
    """Write state via temp-file + rename so a crash never corrupts it (§9)."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload = {"generated_at": datetime.now(timezone.utc).isoformat(), "reviews": archive}
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


class ScrapeHealthError(RuntimeError):
    """Raised when a scrape looks unhealthy; the run aborts with NO writes."""


def assert_scrape_is_healthy(current: dict[str, dict], archive: dict[str, dict]) -> None:
    """Abort BEFORE any state/sheet mutation if the scrape looks broken (§9)."""
    n = len(current)
    if n == 0:
        raise ScrapeHealthError("Scrape returned 0 reviews.")

    prev_live = sum(1 for r in archive.values() if r.get("status") == "live")
    if prev_live > 0 and n < MIN_FRACTION_OF_PREV_LIVE * prev_live:
        raise ScrapeHealthError(
            f"Captured {n} reviews, below {MIN_FRACTION_OF_PREV_LIVE:.0%} of the "
            f"prior live count ({prev_live}). Refusing to flag mass removals."
        )

    bad = sum(1 for r in current.values() if not r.get("stars") or not r.get("review_date"))
    if bad / n > MAX_PARSE_FAIL_FRACTION:
        raise ScrapeHealthError(
            f"{bad}/{n} reviews missing stars/date "
            f"(> {MAX_PARSE_FAIL_FRACTION:.0%}) — likely markup drift."
        )
    log.info("Health check passed: %s reviews, %s parse gaps, prior live=%s.", n, bad, prev_live)


def reconcile(current: dict[str, dict], archive: dict[str, dict], run_date: str) -> dict[str, dict]:
    """Merge this run's live reviews into the archive and mark removals (§6.2).

    Mutates and returns ``archive``. Call ``assert_scrape_is_healthy`` first.
    """
    # 1. Reconcile scraped (live) reviews.
    for rid, r in current.items():
        prior = archive.get(rid)
        r = dict(r)
        r["first_seen"] = prior["first_seen"] if prior else run_date   # preserve original
        r["last_seen"] = run_date
        r["status"] = "live"
        archive[rid] = r

    # 2. Anything in the archive not seen this run is 'removed'
    #    (last_seen keeps its prior last-live value).
    for rid, rec in archive.items():
        if rid not in current:
            rec["status"] = "removed"

    return archive
