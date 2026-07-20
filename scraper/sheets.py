"""Render the archive into a 3-tab Google Sheet (spec §5).

Bulk-write only (§5.3): one values-update per tab, never cell-by-cell, to
stay well under Google's ~60 writes/min quota. gspread/google-auth are
imported lazily so the scraper can run --dry-run without them installed.
"""

from __future__ import annotations

import json
import logging

log = logging.getLogger("scraper.sheets")

# Column order shared by all three tabs (§5.1).
COLUMNS = [
    "review_id", "review_date", "review_date_raw", "shop_name", "country",
    "duration_used", "duration_days", "review_text", "stars",
    "shop_domain", "website_link", "first_seen", "last_seen", "status",
]

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _rows(records: list[dict]) -> list[list]:
    """Header + deterministically ordered rows (review_date desc, id)."""
    ordered = sorted(
        records,
        key=lambda r: (r.get("review_date") or "", r.get("review_id") or ""),
        reverse=True,
    )
    out = [COLUMNS]
    for r in ordered:
        out.append([("" if r.get(c) is None else r.get(c)) for c in COLUMNS])
    return out


def _write_tab(spreadsheet, title: str, records: list[dict]) -> None:
    try:
        ws = spreadsheet.worksheet(title)
    except Exception:  # WorksheetNotFound
        ws = spreadsheet.add_worksheet(title=title, rows="100", cols=str(len(COLUMNS)))
    ws.clear()
    ws.update(range_name="A1", values=_rows(records))
    log.info("Wrote tab %r: %s data row(s).", title, len(records))


def write_sheet(sheet_id: str, service_account_json: str, archive: dict[str, dict]) -> None:
    """Render Reviews / Removed Review / Archived Review from the archive."""
    import gspread
    from google.oauth2.service_account import Credentials

    info = json.loads(service_account_json)
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    gc = gspread.authorize(creds)
    ss = gc.open_by_key(sheet_id)

    records = list(archive.values())
    _write_tab(ss, "Reviews", [r for r in records if r.get("status") == "live"])
    _write_tab(ss, "Removed Review", [r for r in records if r.get("status") == "removed"])
    _write_tab(ss, "Archived Review", records)
    log.info("Google Sheet updated: %s", sheet_id)
