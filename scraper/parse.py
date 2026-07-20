"""Parse Shopify App Store review blocks into dicts.

Selectors were confirmed against the live Report Pundit reviews page
(§2.1 / §4.2 of the spec). We anchor on stable signals only —
``data-*`` attributes, ``aria-label``, and the "using the app" text
pattern — never on the volatile Tailwind ``tw-*`` utility classes.
"""

from __future__ import annotations

import re
from typing import Optional

from bs4 import BeautifulSoup

# "5 out of 5 stars" / "5.0 out of 5 stars"
_STARS_RE = re.compile(r"([\d.]+)\s+out of\s+5", re.I)
# "July 13, 2026"
_DATE_RE = re.compile(r"([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})")
# trailing "Show more" / "Show less" toggle text baked into the review body
_TOGGLE_RE = re.compile(r"\s*(Show more|Show less)\s*$", re.I)

_MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        ],
        start=1,
    )
}


def _iso_date(raw: str) -> Optional[str]:
    m = _DATE_RE.search(raw or "")
    if not m:
        return None
    month = _MONTHS.get(m.group(1).capitalize())
    if not month:
        return None
    return f"{int(m.group(3)):04d}-{month:02d}-{int(m.group(2)):02d}"


def _duration_days(raw: str) -> Optional[int]:
    """Best-effort normalization of '… using the app' to a day count."""
    if not raw:
        return None
    num = re.search(r"\d+", raw)
    if not num:
        return None
    n = int(num.group())
    low = raw.lower()
    if "year" in low:
        return n * 365
    if "month" in low:
        return n * 30
    if "week" in low:
        return n * 7
    if "day" in low:
        return n
    if "hour" in low or "minute" in low:
        return 0  # used for less than a day
    return None


def parse_page(html: str) -> list[dict]:
    """Return a list of review dicts for one reviews page (may be empty)."""
    soup = BeautifulSoup(html, "html.parser")
    reviews: list[dict] = []

    for block in soup.select("[data-review-content-id]"):
        # Drop the developer-reply subtree so its date/text can't contaminate
        # the review fields.
        for reply in block.select("[data-merchant-review-reply]"):
            reply.extract()

        review_id = (block.get("data-review-content-id") or "").strip()
        if not review_id:
            continue

        # Stars — parse from the star element's aria-label.
        stars: Optional[int] = None
        star_el = block.select_one('[aria-label*="out of 5 stars"]')
        if star_el:
            sm = _STARS_RE.search(star_el.get("aria-label", ""))
            if sm:
                stars = int(round(float(sm.group(1))))

        # Review body — full text lives in data-truncate-review; strip toggle.
        review_text = ""
        body_el = block.select_one("[data-truncate-review]")
        if body_el:
            review_text = _TOGGLE_RE.sub("", body_el.get_text(" ", strip=True)).strip()

        # Merchant block: the leaf holding "… using the app", whose parent
        # groups [shop_name, country, duration] as its leaf children in order.
        shop_name = country = duration_used = ""
        dur_leaf = None
        for el in block.find_all(True):
            if el.find(True) is None and el.get_text(strip=True).endswith("using the app"):
                dur_leaf = el
                break
        if dur_leaf is not None:
            duration_used = dur_leaf.get_text(strip=True)
            leaves = [
                e.get_text(strip=True)
                for e in dur_leaf.parent.find_all(True)
                if e.find(True) is None and e.get_text(strip=True)
            ]
            if len(leaves) >= 3:
                shop_name, country = leaves[0], leaves[-2]
            elif len(leaves) == 2:
                shop_name = leaves[0]

        # Date — first Month DD, YYYY match in the (reply-stripped) block.
        review_date_raw = ""
        dm = _DATE_RE.search(block.get_text(" ", strip=True))
        if dm:
            review_date_raw = dm.group(0)

        reviews.append(
            {
                "review_id": review_id,
                "review_date": _iso_date(review_date_raw),
                "review_date_raw": review_date_raw,
                "shop_name": shop_name,
                "country": country,
                "duration_used": duration_used,
                "duration_days": _duration_days(duration_used),
                "review_text": review_text,
                "stars": stars,
                "shop_domain": "",   # §4.3 — not available on the page
                "website_link": "",  # §4.3 — not available on the page
            }
        )

    return reviews
