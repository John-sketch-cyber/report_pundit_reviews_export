"""Paginated HTTP fetch for the Report Pundit reviews page.

Politeness & resilience per spec §9: session with retry/backoff, custom
User-Agent, randomized inter-page delay, and a deep-pagination cap guard
(§4.1) that stops if a page repeats the previous page's review set.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Callable, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .parse import parse_page

log = logging.getLogger("scraper.fetch")

BASE_URL = "https://apps.shopify.com/report-pundit/reviews"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)
DELAY_RANGE = (2.0, 4.0)   # seconds between pages
TIMEOUT = 30               # per-request seconds


def _build_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=4,
        backoff_factor=1.5,                       # 1.5s, 3s, 6s, 12s
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        respect_retry_after_header=True,
    )
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
    return s


def scrape_all_pages(
    max_pages: Optional[int] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    session: Optional[requests.Session] = None,
) -> dict[str, dict]:
    """Scrape every reviews page. Returns {review_id: review}.

    Stops on the first empty page, or if a page repeats the previous page's
    exact set of review ids (deep-pagination cap / loop guard).
    """
    session = session or _build_session()
    reviews: dict[str, dict] = {}
    prev_ids: Optional[frozenset[str]] = None
    page = 1

    while True:
        if max_pages is not None and page > max_pages:
            log.info("Reached max_pages=%s; stopping.", max_pages)
            break

        url = f"{BASE_URL}?page={page}"
        resp = session.get(url, timeout=TIMEOUT)
        resp.raise_for_status()

        block = parse_page(resp.text)
        if not block:
            log.info("Page %s returned 0 reviews; treating as last page.", page)
            break

        page_ids = frozenset(r["review_id"] for r in block)
        if page_ids == prev_ids:
            log.warning(
                "Page %s repeats page %s's review ids — likely a pagination "
                "cap. Stopping; health check will decide if the run is valid.",
                page, page - 1,
            )
            break

        new = 0
        for r in block:
            if r["review_id"] not in reviews:
                reviews[r["review_id"]] = r
                new += 1
        log.info("Page %s: %s reviews (%s new). Total=%s", page, len(block), new, len(reviews))

        prev_ids = page_ids
        page += 1
        sleep_fn(random.uniform(*DELAY_RANGE))

    log.info("Scrape complete: %s unique reviews across %s page(s).", len(reviews), page - 1)
    return reviews
