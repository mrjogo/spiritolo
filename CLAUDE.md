<!-- [repo-mixin:devcontainer-claude] Base CLAUDE.md with PR conventions. -->

# spiritolo

Cocktail recipe scraper + verification UI. Stages: discover → fetch → classify_url → validate (HTML + drink scoring) → extract (Schema.org Recipe JSON-LD → Supabase). Vite/React SPA reads `recipes_public`.

- `scraper/` — Python 3.11+ (uv), pytest. Stage CLIs in `scraper/src/{fetch,classify,validate,extract}.py`. Work queue: `data/scraper.db` (SQLite).
- `supabase/migrations/` — `recipes` + `taxonomy_*` tables.
- `web/` — Vite + React + TS + Vitest.
- `docs/` — design + roadmap.

Run `cd scraper && uv run …` and `cd web && npm …` from the repo root.

## Workflow

**PRs:** `gh pr create` against `main` (occasionally `development`). Optional one-paragraph description, up to 8 bullets. No sections, no test plan. After merge: check out main, pull, delete branch.

**Branches for AI agent sessions:** stay on the `claude/<topic>-<short-id>` branch named in the session task. Never push elsewhere.

## Local environment

**Supabase runs on the Mac host, not the devcontainer** (DooD vs `supabase start`'s bind mounts). Host setup: `brew install supabase/tap/supabase && supabase start`. Studio at http://localhost:54323.

Devcontainer `.env`: `SUPABASE_DB_URL=postgresql://postgres:postgres@host.docker.internal:54322/postgres`. App code (psycopg, JS clients, browser) connects fine via this URL — glibc's resolver returns the IPv4 address (`192.168.65.254`) and there's no IPv6 record to trip over.

**The `supabase` CLI is the exception.** Its Go-based resolver picks up an IPv6 form of `host.docker.internal` that isn't routable from the container, so commands that talk to the DB (`db reset`, `migration list`, etc.) need the IPv4 literal:

```bash
supabase db reset --db-url "postgresql://postgres:postgres@192.168.65.254:54322/postgres" --yes
```

The trailing `tls error (server refused TLS connection)` is misleading — migrations succeed. Verify with a `select`.

URL classifier needs ollama: `ollama pull qwen3:14b`.

## Data model

`data/scraper.db`: `pages` is the canonical per-URL state. Each stage has a `*_runs` table (latest-only UPSERT, prunable — deleting puts pages back on the work queue). A stage's queue is "qualifies AND has no `*_runs` row." Snapshot columns (`pages_*_before`) record what flipped.

Supabase: `recipes` (website-facing columns + full `jsonld`); `taxonomy_nodes` / `taxonomy_edges` / `taxonomy_aliases` (multi-parent DAG, see Spirits Taxonomy below).

## Pipeline conventions

Stage CLIs (`fetch`, `classify`, `validate`, `extract`) share `--site` / `--limit` / `--dry-run` / `--reset [--site S] [--except-version V] [--older-than ISO_TS] [--yes]`. Bare `--reset` wipes the stage's eval scope.

- `validate --reset` clears `validate_html_runs` + `classify_drink_runs` together.
- `classify --reset` also nulls `pages.content_type` (its queue gates on `content_type IS NULL`, not eval-row presence).

**Versioning:** every evaluator has a version constant in its eval rows. When you change logic, bump the constant and re-run with `--reset --except-version <prior>` so prior-version rows fall back on the work queue.

| Stage | Constant | File |
|---|---|---|
| URL classification | `PROMPT_VERSION` | [classify_prompt.py](scraper/src/classify_prompt.py) |
| HTML validation | `VALIDATOR_VERSION` | [validation.py](scraper/src/validation.py) |
| Drink scoring | `SCORER_VERSION` | [classify_drink.py](scraper/src/classify_drink.py) |
| JSON-LD extraction | `EXTRACTOR_VERSION` | [extract.py](scraper/src/extract.py) |

## Pipeline stages

- **`classify.py`** — local ollama on `content_type IS NULL` rows. Iterate prompts via `--review` against the checked-in eval set; use `--sample` for spot-checks. Bump `PROMPT_VERSION` after edits.
- **`validate.py`** — fetch runs validation + drink scoring inline, so this CLI exists only to re-evaluate cached HTML after a version bump.
- **`extract.py`** — parses Schema.org Recipe JSON-LD into Supabase `recipes`. UPSERTs on `source_url`; re-runs are idempotent. To re-extract: clear `extract_runs` rows.

## Spirits Taxonomy

DAG of canonical ingredients. **Read [docs/spirits-taxonomy.md](docs/spirits-taxonomy.md) before adding nodes** — the lean stance (taxonomy for definitional categories + hard constraints; vector layer for soft similarity) is load-bearing. Don't add sensory, stylistic, or colloquial nodes.

Add by editing `supabase/seed.sql` (local dev only — Supabase doesn't apply seed files to prod) and re-running `supabase db reset`.

## Ingredient Parser

`ingredients/` is a Zone-2 worker that reads `recipes` from Supabase, parses each `jsonld.recipeIngredient` string with strict abstain discipline, and writes rows to `recipe_ingredients`. It depends on the shared `common/` package, not on `scraper/`.

**Versioning:** `PARSER_VERSION` lives in [parser.py](ingredients/src/ingredients/parser.py). Bump it whenever any parser rule changes (including unit-table edits). Rows carry the version they were parsed under.

**Typical usage (from repo root):**

```bash
# Main run — parse every recipe lacking a row at the current PARSER_VERSION.
cd ingredients && uv run python -m ingredients.cli

# Scoped to one site, with a row cap.
cd ingredients && uv run python -m ingredients.cli --site punch --limit 200

# Dry-run preview, no DB writes.
cd ingredients && uv run python -m ingredients.cli --dry-run

# Run the eval set; no DB writes. Use during rule iteration.
cd ingredients && uv run python -m ingredients.cli --review

# After bumping PARSER_VERSION, re-parse everything left at the old version.
cd ingredients && uv run python -m ingredients.cli --reset --except-version v1 --yes
```

The eval set is `ingredients/src/ingredients/eval_set.py`. Add a new should-parse-as-X case whenever you teach the parser a new pattern; add a should-abstain case whenever you find an over-match.

**Common, scraper, ingredients packages.** `common/` holds shared utilities (`supabase_client`, `progress`, `summary`, `cli_common`); both `scraper/` (Zone 1) and `ingredients/` (Zone 2) depend on it via the root-level uv workspace.

## Web UI

Reads `recipes_public` via the publishable key (`sb_publishable_…`, post-Nov-2025 replacement for the legacy anon key). No backend.

```bash
cd web && npm install
cp .env.local.example .env.local   # paste publishable key from `supabase status`
npm run dev                        # localhost:5173, VS Code auto-forwards
npm test                           # Vitest + @testing-library/react
```

Main suite: [normalizeRecipe.test.ts](web/src/normalizeRecipe.test.ts) covers messy Schema.org Recipe variants. Supabase must be running on the host for the dev server to load data.
