<!-- [repo-mixin:devcontainer-claude] Base CLAUDE.md with PR conventions.
     Adapt project name and add project-specific instructions below. -->

# spiritolo

## Pull Requests

Look at the branch commit log and file changes compared to destination branch. Create the PR directly with `gh pr create` against the primary branch (usually `main`, occasionally `development`). Description should be terse: optional descriptive paragraph, up to 8 bullets (fewer for simple changes). No repeated or unnecessary information. No sections or test information.

Once the PR is merged, checkout the primary branch, pull it, and delete the old branch.

## URL Classifier

The classifier lives at `scraper/src/classify.py`. It reads `content_type IS NULL` rows from `data/scraper.db`, sends each URL to a local ollama model, and writes the label back plus an audit row in the `classifications` table.

**One-time setup:**

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen3:14b
```

**Typical usage (from repo root):**

```bash
# Main run — classify all remaining NULL rows for a site.
cd scraper && uv run python -m scraper.src.classify --site liquor

# Prompt iteration — run against the checked-in eval set, no DB writes.
cd scraper && uv run python -m scraper.src.classify --review

# Ad-hoc spot-check after a run. Filters are optional; combine as needed.
cd scraper && uv run python -m scraper.src.classify --sample --n 20                                                # N random across all sites/labels
cd scraper && uv run python -m scraper.src.classify --sample --site imbibe --n 20                                  # N random from one site
cd scraper && uv run python -m scraper.src.classify --sample --site liquor --category likely_drink_recipe --n 10   # site + label
cd scraper && uv run python -m scraper.src.classify --sample --urls "https://foo/bar" "https://baz/qux"            # look up specific URLs
```

The prompt lives in `scraper/src/classify_prompt.py`. To iterate, edit the prompt, bump `PROMPT_VERSION`, and re-run `--review` until the eval set passes at an acceptable rate.

## JSON-LD Extractor

The extractor lives at `scraper/src/extract.py`. It reads drink-recipe pages (`content_type IN ('likely_drink_recipe', 'confirmed_drink')`) with cached HTML that have no `extract_runs` row yet, parses the embedded Schema.org `Recipe` JSON-LD, writes it to the local Supabase `recipes` table (website-facing columns + full `jsonld` blob), and UPSERTs an `extract_runs` row recording the outcome (`extracted` / `no_recipe` / `html_missing`).

**Supabase runs on the Mac host, not in the devcontainer.** DooD doesn't play well with `supabase start`'s bind-mount paths and network probes. The devcontainer connects to the host's Supabase via `host.docker.internal`.

**One-time setup (on the Mac host):**

```bash
brew install supabase/tap/supabase   # if not already installed
cd /Users/ruddick/code-projects/spiritolo
supabase start                       # local Postgres + Studio on the host
```

**Inside the devcontainer, configure `.env` at the repo root:**

```
SUPABASE_DB_URL=postgresql://postgres:postgres@host.docker.internal:54322/postgres
```

**Applying migrations** works from inside the devcontainer via `--db-url`, but note the host must be given as the IPv4 address (`host.docker.internal` resolves IPv6-only from the container, which isn't routable):

```bash
supabase db reset \
  --db-url "postgresql://postgres:postgres@192.168.65.254:54322/postgres" \
  --yes
```

The CLI may print a misleading `tls error` at the end — the migration actually succeeds; verify with a quick `select`.

**Typical usage (from repo root):**

```bash
# Main run — extract all unprocessed drink-recipe pages for a site.
cd scraper && uv run python -m scraper.src.extract --site diffordsguide

# Small smoke run.
cd scraper && uv run python -m scraper.src.extract --limit 10
```

**Re-extraction:** delete the relevant `extract_runs` rows (via `--reset`, the prune CLI, or raw SQL); those pages land back on the extract work queue. Supabase UPSERTs on `source_url` so re-runs are idempotent.

**Local Supabase Studio:** http://localhost:54323 (on the Mac host).

## Validate CLI

`scraper/src/validate.py` re-runs `validate()` + `classify_drink()` over cached HTML that hasn't been evaluated by the current schema yet. Work queue is "pages with `html_path` set that have no row in `validate_html_runs`" — runs are resumable, restart picks up where it left off.

Each invocation opens a `pipeline_runs` row (stage=`validate_html`), writes one `validate_html_runs` and one `classify_drink_runs` row per processed page (UPSERT on `page_id` — latest-only), and snapshots the pre-run `pages.status` / `pages.content_type` onto those eval rows so "what flipped on the last run" is a trivial SELECT:

```sql
SELECT p.url, d.pages_content_type_before AS was, d.label AS now
FROM classify_drink_runs d JOIN pages p ON p.id = d.page_id
WHERE d.label IS NOT NULL AND d.label != d.pages_content_type_before
  AND d.run_id = (SELECT MAX(id) FROM pipeline_runs WHERE stage='classify_drink');
```

```bash
# Re-process everything that hasn't been evaluated yet.
cd scraper && uv run python -m scraper.src.validate

# Dry-run preview, scoped to one site. Doesn't write eval rows or pages updates.
cd scraper && uv run python -m scraper.src.validate --site imbibe --dry-run

# Force re-evaluation of imbibe: deletes its validate_html_runs + classify_drink_runs
# rows first, so everything lands back on the work queue.
cd scraper && uv run python -m scraper.src.validate --site imbibe --reset

# Selective re-evaluation via the prune CLI (see below) — e.g. drop rows from
# an older scorer version so only those get re-scored:
#   cd scraper && uv run python -m scraper.src.prune --stage classify_drink --except-version v2
# Then run `validate` normally.
```

All pipeline scripts (`fetch`, `classify`, `extract`, `validate`) share the same `--site` / `--limit` / `--dry-run` / `--reset --yes` conventions where applicable, the same progress line (`X/Y (Z%) rows/s ETA 1h3m34s`), and the same per-site / per-category summary.

## Prune CLI

`scraper/src/prune.py` deletes rows from the per-stage eval tables (`classify_url_runs`, `validate_html_runs`, `classify_drink_runs`, `extract_runs`) to manage DB disk usage. Eval tables are latest-only and regeneratable — pruning just puts pages back on the corresponding stage's work queue. `pages` and `pipeline_runs` are never touched.

```bash
cd scraper && uv run python -m scraper.src.prune --stage classify_drink --older-than 2026-01-01T00:00:00+00:00
cd scraper && uv run python -m scraper.src.prune --stage validate_html --except-version v1
cd scraper && uv run python -m scraper.src.prune --stage classify_url --site imbibe
cd scraper && uv run python -m scraper.src.prune --all --yes     # wipe every eval table
```

Filters AND together. Without any filter, `--stage X` empties X's whole table.

## Web UI

A basic Vite + React + TypeScript SPA under `web/` for verifying the extracted recipes. Reads the `recipes_public` view via the publishable key (`sb_publishable_...`, the post-Nov-2025 replacement for the legacy anon key) — no backend.

**One-time setup:**

```bash
cd web
npm install
cp .env.local.example .env.local
# edit .env.local and paste in the publishable key from `supabase status` on the Mac host
```

**Running:**

```bash
cd web && npm run dev
```

Vite binds to `localhost:5173`; VS Code auto-forwards the port to the Mac host. Supabase must be running locally on the Mac host (see the JSON-LD Extractor section above).

**Tests:**

```bash
cd web && npm test
```

Every unit of logic is built red-first (Vitest + `@testing-library/react`). The main suite is `normalizeRecipe.test.ts`, which covers the messy Schema.org Recipe variants.
