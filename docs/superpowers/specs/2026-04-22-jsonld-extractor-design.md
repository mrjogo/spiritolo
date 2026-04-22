# JSON-LD Recipe Extractor → Supabase

**Date:** 2026-04-22
**Status:** Design
**Phase:** 2 (Extractor) — see `docs/future-direction.md`

## Goal

Read archived HTML for pages classified as drink recipes, extract the embedded Schema.org JSON-LD `Recipe` object, and store it in Supabase in a shape a website can render directly — similar to how recipe-clipper apps display saved recipes.

## Scope

**In scope**
- A Python extractor that reads `content_type = 'likely_drink_recipe'` rows from `scraper.db`, parses JSON-LD from the saved HTML, and writes to a local Supabase instance.
- First Supabase migration defining the `recipes` table, its RLS config, and a public-facing view.
- Local Supabase workflow (dev loop, migrations).

**Out of scope**
- LLM extraction / any fallback when JSON-LD is absent. Pages without usable JSON-LD are marked and skipped.
- Ingredient normalization, canonical catalog, hierarchy, brand-level filtering. These will be an additive layer built later on top of `jsonld`.
- Syncing local Supabase → hosted/prod Supabase. Deferred until a website exists.
- The website / API surface itself (Phase 3).

## Architectural Decisions

### JSON-LD only, no fallback
Target sites (diffordsguide first) ship Schema.org `Recipe` JSON-LD. We rely on it exclusively. Pages without it are marked `extract_error = 'no_jsonld_recipe'` and left alone. If coverage turns out patchy in practice, we revisit with a separate spec.

### Thin & lazy schema
One `recipes` table. A handful of promoted columns for display/query, plus a `jsonld JSONB` blob carrying the rest (ingredients, instructions, times, yield, ratings, …). The website renders from `jsonld`. A normalization layer can be added later without changing this table.

### Local Supabase as staging
Schema lives in `supabase/migrations/`. Extractor writes to local Supabase. Iteration is `edit migration → supabase db reset → re-run extractor`. Sync-to-prod is deferred.

### Docker-outside-of-docker for the devcontainer
Supabase requires Docker. The devcontainer mounts the host Docker socket so `supabase start` (run inside the container) starts Supabase containers on the host. Host ports are reachable from the devcontainer at `host.docker.internal`.

## Schema (first migration)

```sql
create table recipes (
  id           bigserial primary key,
  source_url   text not null unique,
  site         text not null,
  name         text,
  author       text,
  image_url    text,
  jsonld       jsonb not null,
  fetched_at   timestamptz not null,
  extracted_at timestamptz not null default now()
);

create index recipes_site_idx on recipes (site);
create index recipes_jsonld_gin on recipes using gin (jsonld);

-- RLS: base table has no anon-read access.
alter table recipes enable row level security;
-- No SELECT policy for anon → anon gets nothing from this table.
-- service_role bypasses RLS, so the extractor writes without a policy.

-- Public-facing projection: only the columns a website renders.
create view recipes_public as
  select id, source_url, site, name, author, image_url, jsonld
  from recipes;

grant select on recipes_public to anon, authenticated;
```

**Promoted columns (top-level):** `source_url`, `site`, `name`, `author`, `image_url`, `fetched_at`.
**In `jsonld`:** everything else — `recipeIngredient`, `recipeInstructions`, `prepTime`, `cookTime`, `totalTime`, `recipeYield`, `aggregateRating`, original `author` object, etc.

**Column sourcing:**
- `source_url` — the scraped URL (from `pages.url`), *not* `jsonld.url` which is sometimes wrong.
- `site` — from `pages.site`.
- `name` — `jsonld.name`.
- `author` — `jsonld.author.name` if `author` is an object, else `jsonld.author` if it's a bare string, else null.
- `image_url` — first URL in `jsonld.image` (which may be a string, object with `url`, or array).
- `fetched_at` — cast from `pages.fetched_at` (TEXT ISO-8601 in scraper.db).
- `extracted_at` — DB default `now()`.

**RLS shape:** The website queries `recipes_public`. The extractor writes to `recipes` via `service_role`. `fetched_at` / `extracted_at` exist for ops and debugging and are never exposed publicly.

## scraper.db changes

Add two columns to the `pages` table:

```sql
ALTER TABLE pages ADD COLUMN extracted_at TEXT;
ALTER TABLE pages ADD COLUMN extract_error TEXT;
```

Encoded in `db.py`'s `CREATE TABLE` for fresh databases, plus a one-shot `ALTER TABLE` (idempotent via `try/except` or a `PRAGMA table_info` check) for the existing DB.

## Extractor (`scraper/src/extract.py`)

### Work queue

```sql
SELECT id, site, url, html_path, fetched_at FROM pages
WHERE content_type = 'likely_drink_recipe'
  AND html_path IS NOT NULL
  AND extracted_at IS NULL
  AND extract_error IS NULL
ORDER BY id;
```

Optional `--site` filter. Defaults to all sites.

The `extract_error IS NULL` filter keeps pages with known-bad HTML (e.g., no JSON-LD Recipe found) out of the queue. To retry them — say, after fixing the parser — clear both columns: `UPDATE pages SET extracted_at = NULL, extract_error = NULL WHERE extract_error IS NOT NULL`.

### Per-page flow

1. Read HTML from `DATA_DIR/html/<html_path>`.
2. Call `jsonld.parse_recipe_from_html(html) -> dict | None`.
3. If a Recipe node is returned:
   a. Derive promoted fields (`name`, `author`, `image_url`).
   b. `INSERT INTO recipes (…) VALUES (…) ON CONFLICT (source_url) DO UPDATE SET …` — updates all columns except `id` on conflict. Re-extraction is safe.
   c. `UPDATE pages SET extracted_at = ?, extract_error = NULL WHERE id = ?` in scraper.db.
4. If `None`:
   a. `UPDATE pages SET extract_error = 'no_jsonld_recipe' WHERE id = ?`. `extracted_at` stays `NULL`, so the page won't be retried until the column is cleared.

### Idempotency & re-extraction

- `source_url UNIQUE` + `ON CONFLICT DO UPDATE` means re-running is safe.
- To force re-extraction of a subset: `UPDATE pages SET extracted_at = NULL, extract_error = NULL WHERE …` then re-run.

### Module layout

```
scraper/src/
  extract.py              # orchestration: CLI, queue, per-page loop
  jsonld.py               # pure: parse_recipe_from_html(html) -> dict | None
  supabase_client.py      # thin wrapper around psycopg + local Postgres URL
```

`jsonld.py` is pure functions, no I/O — heavily unit-tested. `supabase_client.py` connects via direct Postgres URL (from `supabase status`) using `psycopg`. Bypassing the HTTP SDK keeps bulk writes simple and fast; we're an admin tool, not an app client.

### JSON-LD parser requirements (`jsonld.py`)

Must handle:
- Multiple `<script type="application/ld+json">` blocks on the page.
- `@graph` wrappers (`{"@context": "...", "@graph": [{…}, {…}]}`).
- Top-level arrays (`[{…}, {…}]`).
- `@type` as a string (`"Recipe"`) or array (`["Recipe", "Thing"]`).
- Malformed JSON (skip that block, continue scanning others).
- No `Recipe` node present (return `None`).

Returns the raw Recipe dict on success. The caller derives promoted fields; the full dict is what gets stored in `jsonld`.

### CLI

```
cd scraper && uv run python -m scraper.src.extract [--site SITE] [--limit N]
```

Progress output mirrors `classify.py` — upfront total, per-batch progress with rows/sec and ETA.

## Local Supabase workflow

Assumes the Supabase CLI is installed on the host, and docker-outside-of-docker is wired into the devcontainer.

```bash
# One-time
supabase init                    # creates supabase/ with config.toml + migrations/
supabase start                   # starts local Postgres, Studio, etc.

# Dev loop
# 1. Edit supabase/migrations/*.sql
supabase db reset                # wipes local DB, replays all migrations
uv run python -m scraper.src.extract --site diffordsguide
# 2. Inspect at http://host.docker.internal:54323 (Studio)
```

The local Postgres connection string (from `supabase status`) goes into `.env` (gitignored) as `SUPABASE_DB_URL`. Extractor reads it.

## Devcontainer change

Add the docker-outside-of-docker feature to `.devcontainer/devcontainer.json`:

```json
"features": {
  "ghcr.io/devcontainers/features/github-cli:1": {},
  "ghcr.io/devcontainers/features/docker-outside-of-docker:1": {}
}
```

This mounts the host's `/var/run/docker.sock` into the container. `supabase` CLI calls from inside the container drive the host daemon. The devcontainer must be rebuilt after this change.

## Testing

- **`jsonld.py` unit tests:** ~8 fixture HTML files under `scraper/tests/fixtures/` drawn from `data/html/diffordsguide/`, covering:
  - Standard Recipe node at top level.
  - Recipe inside `@graph`.
  - Multiple `<script>` tags, Recipe in the second one.
  - `@type` as an array containing `"Recipe"`.
  - No JSON-LD at all.
  - Malformed JSON in one block, valid Recipe in another.
  - `author` as object, `author` as bare string.
  - `image` as string, object, and array.
- **`extract.py` integration test:** one small test against local Supabase — seed two rows in a scratch `pages` table, run the extractor, assert rows exist in `recipes` and that re-running is idempotent.

## Dependencies to add

```
psycopg[binary]     # direct Postgres connection
beautifulsoup4      # extracting <script> tags
```

(JSON-LD parsing itself uses the stdlib `json` module; BeautifulSoup only locates the `<script type="application/ld+json">` blocks.)

## Success criteria

- `uv run python -m scraper.src.extract --site diffordsguide` runs to completion.
- Every page with `content_type = 'likely_drink_recipe'` and fetched HTML is either (a) in the `recipes` table with a populated `jsonld`, or (b) marked `extract_error = 'no_jsonld_recipe'` in `scraper.db`.
- A second run produces no changes (idempotency).
- Manual spot-check: ten random rows in `recipes_public` have usable `name`, `image_url`, and `jsonld.recipeIngredient` / `jsonld.recipeInstructions` values.
- Querying `recipes` directly as anon returns nothing; querying `recipes_public` as anon returns rows without `fetched_at` / `extracted_at`.
