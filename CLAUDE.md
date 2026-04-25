<!-- [repo-mixin:devcontainer-claude] Base CLAUDE.md with PR conventions.
     Adapt project name and add project-specific instructions below. -->

# spiritolo

## Pull Requests

Look at the branch commit log and file changes compared to destination branch. Create the PR directly with `gh pr create` against the primary branch (usually `main`, occasionally `development`). Description should be terse: optional descriptive paragraph, up to 8 bullets (fewer for simple changes). No repeated or unnecessary information. No sections or test information.

Once the PR is merged, checkout the primary branch, pull it, and delete the old branch.

## Data model

`data/scraper.db` (SQLite) has one canonical table plus five stage-scoped run tables:

- **`pages`** — one row per URL. Tracks work-queue state: `site`, `url`, `status`, `content_type`, `html_path`, `fetched_at`, `fetch_error`, `attempts`, `disabled_reason`, etc. This is the only table that holds permanent state about a page.
- **`pipeline_runs`** — one row per CLI invocation: `stage`, `started_at`, `finished_at`, `site`, `args` (JSON), `summary` (JSON). Audit trail for "what ran when."
- **`classify_url_runs`**, **`validate_html_runs`**, **`classify_drink_runs`**, **`extract_runs`** — one row per `page_id` (latest-only UPSERT), keyed as primary key. Each carries a `run_id` FK to `pipeline_runs`, an evaluator version string, an `evaluated_at` timestamp, and — for stages that mutate a `pages.*` field — a snapshot of that field's pre-run value. These tables are prunable: deleting rows just puts pages back on the corresponding stage's work queue.

Each stage's work queue is "pages that qualify for this stage AND have no `*_runs` row for it" — no timestamp flags on `pages` to forget to clear. Extracted recipes live in the Mac-host Supabase `recipes` table (website-facing columns + full `jsonld` blob).

### Versioning

Every evaluator has a version constant, written into every eval row it produces:

| Stage | Constant | File |
|---|---|---|
| URL classification | `PROMPT_VERSION` | [classify_prompt.py](scraper/src/classify_prompt.py) |
| HTML validation | `VALIDATOR_VERSION` | [validation.py](scraper/src/validation.py) |
| Drink scoring | `SCORER_VERSION` | [classify_drink.py](scraper/src/classify_drink.py) |
| JSON-LD extraction | `EXTRACTOR_VERSION` | [extract.py](scraper/src/extract.py) |

**Re-run workflow when you change an evaluator's logic:** bump the constant, then run that stage's CLI with `--reset --except-version V` so rows from prior versions fall back on the work queue:

```bash
cd scraper && uv run python -m scraper.src.validate --reset --except-version v2 --yes
```

Bumping the constant without resetting just means new rows land at the new version alongside old ones — useful when you want the diff side-by-side but are fine with a gradual migration.

### Reset surface

Every stage CLI with an eval table (`classify`, `validate`, `extract`) accepts the same flags: `--reset [--site S] [--except-version V] [--older-than ISO_TS] [--yes]`. Filters AND together; `--reset` alone wipes the stage's whole eval scope. `validate --reset` clears both `validate_html_runs` and `classify_drink_runs` together (they're written and consumed together). `classify --reset` also nulls `pages.content_type` for the cleared rows — required because the classify work queue gates on `content_type IS NULL`, not on eval-row presence.

## URL Classifier

The classifier lives at `scraper/src/classify.py`. It reads `content_type IS NULL` rows from `data/scraper.db`, sends each URL to a local ollama model, UPSERTs a `classify_url_runs` row (label + model + prompt_version + raw_response + latency_ms, latest-only per page), and updates `pages.content_type`. Each invocation opens a `pipeline_runs` row with stage=`classify_url`.

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

**Re-extraction:** delete the relevant `extract_runs` rows (via `--reset` or raw SQL); those pages land back on the extract work queue. Supabase UPSERTs on `source_url` so re-runs are idempotent.

**Local Supabase Studio:** http://localhost:54323 (on the Mac host).

## Validate CLI

`scraper/src/validate.py` runs `validate()` + `classify_drink_scored()` on cached HTML and writes `validate_html_runs` + `classify_drink_runs` rows. Fetch performs the same evaluations inline at fetch time, so a run here is only needed to re-evaluate older pages after a version bump or prompt change — the work queue surfaces exactly those.

```bash
# Process every cached-HTML page that lacks a validate_html_runs row.
cd scraper && uv run python -m scraper.src.validate

# Dry-run preview, scoped to one site. Doesn't write eval rows or pages updates.
cd scraper && uv run python -m scraper.src.validate --site imbibe --dry-run

# Force re-evaluation of imbibe: deletes its validate_html_runs +
# classify_drink_runs rows first so they land back on the work queue.
cd scraper && uv run python -m scraper.src.validate --site imbibe --reset
```

The snapshot columns (`pages_status_before`, `pages_content_type_before`) let you see "what flipped on the last run" without any history kept:

```sql
SELECT p.url, d.pages_content_type_before AS was, d.label AS now
FROM classify_drink_runs d JOIN pages p ON p.id = d.page_id
WHERE d.label IS NOT NULL AND d.label != d.pages_content_type_before
  AND d.run_id = (SELECT MAX(id) FROM pipeline_runs WHERE stage='classify_drink');
```

All pipeline scripts (`fetch`, `classify`, `extract`, `validate`) share the same `--site` / `--limit` / `--dry-run` / `--reset --yes` conventions where applicable, the same progress line (`X/Y (Z%) rows/s ETA 1h3m34s`), and the same per-site / per-category summary.

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
