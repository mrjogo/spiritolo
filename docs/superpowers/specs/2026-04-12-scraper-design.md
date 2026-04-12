# Scraper Design Spec

Cocktail recipe scraper that fetches raw HTML from recipe sites via ScraperAPI and saves to local disk. Two-phase architecture: discover URLs, then fetch them. SQLite tracks state for resumability.

## Repo Structure

```
spiritolo/
├── scraper/
│   ├── pyproject.toml          # deps: requests, lxml, pyyaml
│   ├── config/
│   │   └── sites.yaml          # per-site config
│   ├── src/
│   │   ├── discover.py         # Phase 1: sitemaps/crawl → URLs to SQLite
│   │   ├── fetch.py            # Phase 2: pending URLs → ScraperAPI → HTML to disk
│   │   ├── validate.py         # Page validation pipeline
│   │   ├── client.py           # ScraperAPI wrapper (thin, swappable)
│   │   └── db.py               # SQLite state management
│   └── tests/
├── extractor/                  # future — see docs/future-direction.md
├── app/                        # future
├── supabase/                   # future
├── docs/
└── data/                       # .gitignored — SQLite DB + raw HTML
    ├── scraper.db
    └── html/
        └── {site_name}/{url_hash}.html
```

## Site Configuration

`scraper/config/sites.yaml`:

```yaml
sites:
  - name: diffordsguide
    domain: diffordsguide.com
    discovery:
      method: sitemap
      sitemap_url: https://www.diffordsguide.com/sitemap.xml
      url_pattern: "/cocktails/recipe/"

  - name: liquor
    domain: liquor.com
    discovery:
      method: sitemap
      sitemap_url: https://www.liquor.com/sitemap.xml
      url_pattern: "/recipes/"

  - name: example-crawl-site
    domain: example.com
    discovery:
      method: crawl
      start_url: https://example.com/recipes
      url_pattern: "/recipes/"
      next_page_selector: "a.next-page"
```

Most sites use sitemaps. Crawl is the fallback for sites with missing/incomplete sitemaps. Actual sitemap URLs and patterns need to be verified per site during implementation.

## SQLite State Database

```sql
CREATE TABLE pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    discovered_at TEXT NOT NULL,
    fetched_at TEXT,
    error TEXT,
    html_path TEXT
);

CREATE INDEX idx_pages_status ON pages(status);
CREATE INDEX idx_pages_site ON pages(site);
```

**Statuses:** `pending`, `fetched`, `blocked`, `unverified`, `failed`

- `pending` → `fetched` (validated successfully)
- `pending` → `blocked` (bot detection / blocker page)
- `pending` → `unverified` (passed blocker checks but no JSON-LD, inconclusive content)
- `pending` → `failed` (network error after 3 attempts)
- `blocked` / `unverified` / `failed` can be manually reset to `pending`

## Phase 1: Discovery

`discover.py` reads `sites.yaml` and populates the `pages` table.

**Sitemap sites:**
1. Fetch sitemap XML via ScraperAPI (sitemaps can be behind Cloudflare too)
2. Parse with `lxml` — handle sitemap index files (sitemap of sitemaps)
3. Filter URLs matching the site's `url_pattern`
4. Insert into `pages` as `pending`, skip existing URLs

**Crawl sites:**
1. Fetch `start_url` via ScraperAPI
2. Extract recipe links matching `url_pattern`
3. Follow pagination via `next_page_selector` until exhausted
4. Insert into `pages`, same as above

**CLI:**
```bash
python -m scraper.src.discover              # all sites
python -m scraper.src.discover --site name  # specific site
```

Idempotent — re-running adds new URLs without duplicating existing ones.

## Phase 2: Fetch

`fetch.py` pulls pending URLs from SQLite and fetches via ScraperAPI.

**Flow:**
1. Query pending URLs ordered by site, then discovered_at
2. For each URL:
   - Fetch via ScraperAPI
   - Validate the response (see validation pipeline below)
   - On valid: save HTML to `data/html/{site_name}/{sha256(url)[:16]}.html`, update status
   - On invalid: set appropriate status (`blocked`, `unverified`, or increment attempts toward `failed`)
3. Rate limit: 1-2 second delay between requests
4. Log progress: `[diffordsguide] 142/3500 fetched — https://...`

**CLI:**
```bash
python -m scraper.src.fetch                 # all pending
python -m scraper.src.fetch --site name     # specific site
python -m scraper.src.fetch --limit 10      # test run
python -m scraper.src.fetch --force-site name  # resume paused site
```

**Interruption:** SQLite updated per-URL, so Ctrl+C loses only the in-flight request.

**ScraperAPI key:** read from `SCRAPERAPI_KEY` environment variable.

## Page Validation Pipeline

`validate.py` — checks run in order, first decisive result wins:

1. **Size gate** — raw HTML under 5KB → `blocked` (recipe pages are always larger)
2. **Blocker fingerprints** — check for known strings: `cf-challenge-running`, `cf-turnstile`, `g-recaptcha`, `hcaptcha`, `Access Denied`, `_pxhd`, `datadome`, `Enable JavaScript`, `cf-mitigated` header. Match → `blocked`
3. **Recipe JSON-LD (primary accept gate)** — parse `<script type="application/ld+json">` blocks for `@type: "Recipe"` with `name` and `recipeIngredient` present. Found → `fetched`
4. **Fallback content check** — strip tags, measure visible text. Under 500 chars → `blocked` (empty JS shell). Check for `<meta name="robots" content="noindex">` and "not found" / "404" in title → `blocked`
5. **Inconclusive** — page passed blocker checks but no JSON-LD and modest content → `unverified`

`unverified` pages get a later pass via local open-source LLM ("is this a real recipe page? yes/no"). This is a separate manual step, not part of the automated pipeline.

## Site-Level Circuit Breaker

Track validation results per site in a rolling window. If >40% of the last 20 pages from a site return `blocked` or `unverified`:

- Pause fetching for that site
- Log warning: `[site_name] PAUSED — 12/20 recent pages failed validation`
- Continue fetching other sites
- Resume with `--force-site name` after investigation

## Dependencies

- `requests` — HTTP client
- `lxml` — XML/HTML parsing
- `pyyaml` — config parsing
- ScraperAPI via their REST API (no SDK needed — just `requests.get` with API key param)

## Scale

- ~15,000 total pages across all sites
- ~100MB SQLite database at completion
- ~1.5GB raw HTML on disk
- Runs on a local Ubuntu desktop machine
