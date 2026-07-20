# Report Pundit — Weekly Review Export

Scrapes every review of the Report Pundit app on the Shopify App Store once a
week and maintains a 3-tab Google Sheet (**Reviews**, **Removed Review**,
**Archived Review**). Implements `REVIEW_EXPORT_AUTOMATION_SPEC_v0.2.md`.

## §2.1 verification gate — PASSED (2026-07-20)

- Live page returns **HTTP 200** with full server-rendered HTML; **no Cloudflare
  challenge** from a datacenter IP.
- Deep pagination works: `?page=150` returns distinct content (not a page-1
  fallback); pagination control tops out at **page 185** (~1,846 reviews).
- Stable per-review id confirmed: **`data-review-content-id`** (no hash fallback
  needed in practice). Stars via `aria-label="N out of 5 stars"`. Full review
  text via `data-truncate-review` (trailing "Show more" stripped).

> Re-check this gate if the scraper suddenly aborts on the health check — Shopify
> markup or bot-protection may have changed.

## How it works

`state/reviews_state.json` is the single source of truth (the archive). Each run:
load state → scrape all pages → **health check (no writes yet)** → reconcile →
save state atomically → render the Sheet. All three tabs are derived from the
archive by `status` (`live` / `removed`).

## Local run

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Dry run (scrape + write state JSON, skip the Sheet):
python scrape_reviews.py --dry-run --max-pages 3

# Full run (writes the Google Sheet):
export GOOGLE_SA_JSON="$(cat service_account.json)"
export REVIEWS_SHEET_ID="<spreadsheet id>"
python scrape_reviews.py
```

## Scheduling (GitHub Actions)

`.github/workflows/weekly.yml` runs Mondays 07:00 UTC (plus manual
`workflow_dispatch`), commits the updated state file back, and writes the Sheet.

Required repo **secrets**:

| Secret | Value |
|---|---|
| `GOOGLE_SA_JSON` | Full service-account JSON key (same account as the PostHog sync) |
| `REVIEWS_SHEET_ID` | Target spreadsheet id (share the Sheet with the service-account email) |

**Alerting:** GitHub Actions emails the repo owner on any non-zero exit. A failed
health check exits `2` (no state/Sheet write), so false mass-removals never ship.

## Layout

```
scrape_reviews.py            entry point / orchestration + health gate
scraper/fetch.py             paginated HTTP + retry/backoff + cap guard
scraper/parse.py             review block -> dict (stable selectors)
scraper/diff.py              archive reconciliation + health check + atomic state
scraper/sheets.py            gspread bulk writer (3 tabs)
state/reviews_state.json     between-run source of truth (committed)
.github/workflows/weekly.yml weekly cron
```

## Known limitations

- **Shop Domain / Website link** are always blank — not present on the App Store
  page (spec §4.3). Blank means "not available," not "scrape failed."
- If a merchant edits review text, the `data-review-content-id` still keeps the
  row stable (the composite-hash fallback would not).
