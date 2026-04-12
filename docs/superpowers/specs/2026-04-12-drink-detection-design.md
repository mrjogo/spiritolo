# Drink Detection Design

Classify recipe URLs as drink or food so the scraper only fetches and stores drink recipes.

## Problem

All 15 target sites carry food recipes alongside drinks. Even "drinks focused" sites like Liquor.com have food content. With ~200K URLs from sitemaps, fetching everything wastes ScraperAPI credits and pollutes the database.

## Approach

Two-stage classification using a new `content_type` column:

1. **Pre-fetch (manual):** Claude Code classifies URLs by slug → `likely_drink` / `likely_food`
2. **Post-fetch (automatic):** JSON-LD structured data confirms → `confirmed_drink` / `confirmed_food`

## Database

### Schema change

Add `content_type` column to the `pages` table. No migration needed — delete `data/scraper.db` and re-run discovery to recreate:

```sql
CREATE TABLE IF NOT EXISTS pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending',
    content_type TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    discovered_at TEXT NOT NULL,
    fetched_at TEXT,
    error TEXT,
    html_path TEXT
);
```

### Column values

| Value | Set by | Meaning |
|---|---|---|
| `NULL` | default | Unclassified (fresh from sitemap) |
| `likely_drink` | Claude Code | URL slug looks like a drink recipe |
| `likely_food` | Claude Code | URL slug looks like a food recipe |
| `confirmed_drink` | fetch pipeline | JSON-LD structured signals confirm drink |
| `confirmed_food` | fetch pipeline | JSON-LD has no drink signals |

Note: `likely_drink` remaining after fetch means JSON-LD was inconclusive (e.g. no Recipe JSON-LD at all). These should be reviewed manually.

### Indexes

```sql
CREATE INDEX IF NOT EXISTS idx_pages_content_type ON pages(content_type);
CREATE INDEX IF NOT EXISTS idx_pages_status_content_type ON pages(status, content_type);
```

The composite index covers the primary fetch query: `WHERE status = 'pending' AND content_type = 'likely_drink'`.

### New methods on `Database`

- `set_content_type(url, content_type)` — update classification for a single URL
- `set_content_type_batch(ids, content_type)` — update classification for a list of IDs (for batch classification)
- `get_by_content_type(content_type, site=None, limit=None)` — query by classification

Modify `get_pending()` to accept an optional `content_type` filter.

## Fetch pipeline

`fetch_pages()` defaults to only fetching rows where `content_type = 'likely_drink'`. The `get_pending()` call becomes:

```python
pending = db.get_pending(site=site, limit=limit, content_type="likely_drink")
```

After fetch and validation, the pipeline calls `classify_drink(html)` and updates `content_type`:
- Returns `confirmed_drink` → update to `confirmed_drink`
- Returns `confirmed_food` → update to `confirmed_food`
- Returns `None` (no Recipe JSON-LD) → leave as `likely_drink`

## Drink confirmation logic

New function `classify_drink(html) -> str | None` in `validate.py`.

Extracts JSON-LD Recipe objects and checks three fields case-insensitively against a term list. Any match → `confirmed_drink`. All miss → `confirmed_food`. No Recipe JSON-LD → `None`.

### Term list

```python
DRINK_TERMS = {
    # drink types / categories
    "cocktail", "cocktails", "drink", "drinks", "drinking",
    "beverage", "beverages", "mixed drink",
    # cocktail families and styles
    "highball", "lowball", "aperitif", "aperitivo", "digestif",
    "nightcap", "spritz", "sour", "fizz", "flip", "toddy",
    "grog", "sangria", "shooter", "shot", "punch",
    "martini", "margarita", "daiquiri", "mojito", "negroni",
    "colada", "mule", "smash", "swizzle", "cobbler",
    "rickey", "julep", "bellini", "mimosa", "paloma",
}
```

Intentionally excludes spirit names (vodka, gin, rum, etc.) and ingredient names (bitters, vermouth, triple sec) — these appear in food recipes like "sake marinated salmon" or "bourbon glazed ribs".

### Fields checked

1. **`recipeCategory`** — split by comma, check each term
2. **`breadcrumb`** — extract `itemListElement` names, check each
3. **`keywords`** — split by comma, check each term

Matching is case-insensitive substring check on each comma-separated segment (e.g. `term in segment.strip().lower()`). Since these are structured metadata fields with short, intentional values — not free text — substring matching is sufficient and the risk of false positives is negligible.

## Classification prompt

Stored in `docs/runbooks/classify-urls.md`.

## Files changed

| File | Change |
|---|---|
| `scraper/src/db.py` | Add `content_type` to schema, new indexes, new methods, update `get_pending()` |
| `scraper/src/validate.py` | Add `classify_drink()` function and `DRINK_TERMS` |
| `scraper/src/fetch.py` | Default to `content_type='likely_drink'`, call `classify_drink()` after validate |
| `scraper/tests/test_db.py` | Tests for new DB methods |
| `scraper/tests/test_validate.py` | Tests for `classify_drink()` |
| `scraper/tests/test_fetch.py` | Update fetch tests for content_type filtering |
| `docs/runbooks/classify-urls.md` | Classification prompt for Claude Code |
