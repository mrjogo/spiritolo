<!-- [repo-mixin:devcontainer-claude] Base CLAUDE.md with PR conventions.
     Adapt project name and add project-specific instructions below. -->

# spiritolo

Cocktail recipe scraper + verification UI. Pipeline: discover → fetch → classify_url → validate (HTML structure + drink scoring) → extract (Schema.org Recipe JSON-LD → Supabase). React/Vite SPA reads the published recipes.

## Stack & layout

- **`scraper/`** — Python 3.11+ (uv), pytest. Pipeline CLIs in `scraper/src/`: `fetch.py`, `classify.py`, `validate.py`, `extract.py`. Shared work-queue DB: `data/scraper.db` (SQLite).
- **`supabase/migrations/`** — Schema for `recipes` and the spirits taxonomy. **Local Supabase runs on the Mac host, not in the devcontainer.**
- **`web/`** — Vite + React + TypeScript SPA. Vitest tests.
- **`docs/`** — Design specs and roadmap. See [Docs index](#docs) at the bottom.

Run all `cd scraper && uv run …` and `cd web && npm …` commands from the repo root.

## Workflow

### Pull requests

Look at the branch commit log and file changes vs the destination branch. Create the PR with `gh pr create` against the primary branch (usually `main`, occasionally `development`). Description: an optional descriptive paragraph plus up to 8 bullets (fewer for simple changes). No repeated info, no markdown sections, no test plan.

After the PR merges, check out main, pull, and delete the merged branch.

### Branches for AI agent sessions

Web/cloud Claude Code sessions develop on a `claude/<topic>-<short-id>` branch passed in via the session task description. Stay on that branch — push there, not anywhere else.

## Local environment

### Supabase (Mac host)

Local Supabase runs on the Mac host, not in the devcontainer. DooD doesn't play well with `supabase start`'s bind-mount paths and network probes. The devcontainer connects to the host via `host.docker.internal:54322`.

**One-time setup on the Mac host:**

```bash
brew install supabase/tap/supabase
cd <your local checkout of spiritolo>
supabase start                         # local Postgres + Studio
```

**Devcontainer `.env` at repo root:**

```
SUPABASE_DB_URL=postgresql://postgres:postgres@host.docker.internal:54322/postgres
```

**Applying migrations** from inside the devcontainer requires the IPv4 host address — `host.docker.internal` resolves IPv6-only from the container, which isn't routable:

```bash
supabase db reset \
  --db-url "postgresql://postgres:postgres@192.168.65.254:54322/postgres" \
  --yes
```

The CLI may print a trailing `tls error`; it's misleading — the migration succeeds. Verify with a quick `select`.

**Studio:** http://localhost:54323 (on the Mac host).

### Ollama (URL classification)

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen3:14b
```

## Data model

### `data/scraper.db` (SQLite)

One canonical table plus stage-scoped run tables.

- **`pages`** — one row per URL. Tracks work-queue state: `site`, `url`, `status`, `content_type`, `html_path`, `fetched_at`, `fetch_error`, `attempts`, `disabled_reason`, etc. The only table that holds permanent state about a page.
- **`pipeline_runs`** — one row per CLI invocation: `stage`, `started_at`, `finished_at`, `site`, `args` (JSON), `summary` (JSON). Audit trail for "what ran when."
- **`classify_url_runs`**, **`validate_html_runs`**, **`classify_drink_runs`**, **`extract_runs`** — one row per `page_id` (latest-only UPSERT). Each carries a `run_id` FK to `pipeline_runs`, the evaluator version, an `evaluated_at` timestamp, and — for stages that mutate a `pages.*` field — a snapshot of that field's pre-run value. Prunable: deleting rows puts the pages back on the corresponding stage's work queue.

Each stage's work queue is "pages that qualify for this stage AND have no `*_runs` row for it." No timestamp flags on `pages` to forget to clear.

### Supabase

- **`recipes`** — Mac-host Supabase. Website-facing columns + the full `jsonld` blob. Web UI reads via `recipes_public` view + the publishable key.
- **`taxonomy_nodes` / `taxonomy_edges` / `taxonomy_aliases`** — multi-parent DAG of canonical ingredients. See [Spirits Taxonomy](#spirits-taxonomy).

## Pipeline conventions

All stage CLIs (`fetch`, `classify`, `validate`, `extract`) share the same surface where applicable:

- **Common flags**: `--site S` / `--limit N` / `--dry-run` / `--reset [--site S] [--except-version V] [--older-than ISO_TS] [--yes]`. Reset filters AND together; bare `--reset` wipes the stage's whole eval scope.
- **Progress line**: `X/Y (Z%) rows/s ETA 1h3m34s`.
- **Per-site / per-category summary** at the end.

Two reset specifics worth knowing:

- `validate --reset` clears both `validate_html_runs` and `classify_drink_runs` together — they're written and consumed together.
- `classify --reset` also nulls `pages.content_type` for the cleared rows. Required: the classify work queue gates on `content_type IS NULL`, not on eval-row presence.

### Versioning

Every evaluator has a version constant, written into every eval row it produces:

| Stage | Constant | File |
|---|---|---|
| URL classification | `PROMPT_VERSION` | [classify_prompt.py](scraper/src/classify_prompt.py) |
| HTML validation | `VALIDATOR_VERSION` | [validation.py](scraper/src/validation.py) |
| Drink scoring | `SCORER_VERSION` | [classify_drink.py](scraper/src/classify_drink.py) |
| JSON-LD extraction | `EXTRACTOR_VERSION` | [extract.py](scraper/src/extract.py) |

**When you change an evaluator's logic:** bump the constant, then run that stage's CLI with `--reset --except-version V` so prior-version rows fall back on the work queue:

```bash
cd scraper && uv run python -m scraper.src.validate --reset --except-version v2 --yes
```

Bumping without resetting just means new rows land alongside old ones — useful for side-by-side diffs or a gradual migration.

## Pipeline stages

### URL Classifier

`scraper/src/classify.py`. Reads `content_type IS NULL` rows, calls a local ollama model, UPSERTs `classify_url_runs` (label + model + prompt_version + raw_response + latency_ms, latest-only per page), and updates `pages.content_type`. Each invocation opens a `pipeline_runs` row with stage=`classify_url`.

```bash
# Main run — classify all remaining NULL rows for a site.
cd scraper && uv run python -m scraper.src.classify --site liquor

# Prompt iteration — run against the checked-in eval set, no DB writes.
cd scraper && uv run python -m scraper.src.classify --review

# Spot-check after a run. Filters are optional; combine as needed.
cd scraper && uv run python -m scraper.src.classify --sample --n 20                                                # N random across all sites/labels
cd scraper && uv run python -m scraper.src.classify --sample --site imbibe --n 20                                  # N random from one site
cd scraper && uv run python -m scraper.src.classify --sample --site liquor --category likely_drink_recipe --n 10   # site + label
cd scraper && uv run python -m scraper.src.classify --sample --urls "https://foo/bar" "https://baz/qux"            # specific URLs
```

To iterate the prompt: edit [classify_prompt.py](scraper/src/classify_prompt.py), bump `PROMPT_VERSION`, re-run `--review` until the eval set passes.

### Validate

`scraper/src/validate.py` runs `validate()` + `classify_drink_scored()` on cached HTML and writes `validate_html_runs` + `classify_drink_runs` rows. Fetch performs the same evaluations inline at fetch time, so this CLI is only needed to re-evaluate older pages after a version bump or prompt change — the work queue surfaces exactly those.

```bash
# Process every cached-HTML page that lacks a validate_html_runs row.
cd scraper && uv run python -m scraper.src.validate

# Dry-run preview, scoped to one site.
cd scraper && uv run python -m scraper.src.validate --site imbibe --dry-run

# Force re-evaluation of imbibe.
cd scraper && uv run python -m scraper.src.validate --site imbibe --reset
```

Snapshot columns (`pages_status_before`, `pages_content_type_before`) let you see "what flipped on the last run" without keeping any history:

```sql
SELECT p.url, d.pages_content_type_before AS was, d.label AS now
FROM classify_drink_runs d JOIN pages p ON p.id = d.page_id
WHERE d.label IS NOT NULL AND d.label != d.pages_content_type_before
  AND d.run_id = (SELECT MAX(id) FROM pipeline_runs WHERE stage='classify_drink');
```

### JSON-LD Extractor

`scraper/src/extract.py` reads drink-recipe pages (`content_type IN ('likely_drink_recipe', 'confirmed_drink')`) with cached HTML and no `extract_runs` row. Parses the embedded Schema.org `Recipe` JSON-LD, writes website-facing columns + the full `jsonld` blob to the local Supabase `recipes` table, and UPSERTs an `extract_runs` row recording the outcome (`extracted` / `no_recipe` / `html_missing`).

```bash
# Main run.
cd scraper && uv run python -m scraper.src.extract --site diffordsguide

# Smoke run.
cd scraper && uv run python -m scraper.src.extract --limit 10
```

Re-extraction: delete the relevant `extract_runs` rows (via `--reset` or raw SQL); pages land back on the extract work queue. Supabase UPSERTs on `source_url`, so re-runs are idempotent.

### Spirits Taxonomy

Three Supabase tables (`taxonomy_nodes`, `taxonomy_edges`, `taxonomy_aliases`) form a multi-parent DAG of canonical ingredients. Recipes resolve free-text ingredients to node IDs via aliases; the DAG enables "all whiskeys" / "all citrus"-style queries.

**Read [docs/spirits-taxonomy.md](docs/spirits-taxonomy.md) before adding nodes.** The lean stance — taxonomy for definitional categories and hard constraints, vector layer for soft similarity — is load-bearing. Don't add nodes for sensory descriptors, style/occasion, or colloquial groupings.

To add nodes or aliases, edit `supabase/migrations/20260426120100_seed_taxonomy.sql` and re-apply via `supabase db reset` (host setup above). Definitional categories: add freely. Brands and expressions: hand-curate the well-known only — the long tail is the future [D] mapper's job.

## Web UI

A basic Vite + React + TypeScript SPA under `web/` for verifying extracted recipes. Reads the `recipes_public` view via the publishable key (`sb_publishable_...`, the post-Nov-2025 replacement for the legacy anon key). No backend.

```bash
# One-time setup.
cd web
npm install
cp .env.local.example .env.local
# paste the publishable key from `supabase status` on the Mac host into .env.local

# Dev server. Vite binds to localhost:5173; VS Code auto-forwards the port to the Mac host.
cd web && npm run dev

# Tests.
cd web && npm test
```

Every unit of logic is built red-first (Vitest + `@testing-library/react`). The main suite is [normalizeRecipe.test.ts](web/src/normalizeRecipe.test.ts), which covers the messy Schema.org Recipe variants. Supabase must be running on the Mac host for the dev server to load data.

## Docs

- [docs/future-direction.md](docs/future-direction.md) — Roadmap and feature decisions (search, taxonomy, dedup, embeddings, substitutions).
- [docs/spirits-taxonomy.md](docs/spirits-taxonomy.md) — Taxonomy schema and content rules. Read before touching nodes.
- [docs/site-research.md](docs/site-research.md) — Per-site scraping notes.
- [docs/devcontainer-setup.md](docs/devcontainer-setup.md) — Devcontainer details.
