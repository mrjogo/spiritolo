<!-- [repo-mixin:devcontainer-claude] Base CLAUDE.md with PR conventions. -->

# spiritolo

Cocktail recipe scraper + verification UI. Stages: discover → classify_url → fetch (runs HTML validation + drink scoring inline) → extract (Schema.org Recipe JSON-LD → Supabase). `validate` is a re-scoring CLI for cached HTML after a version bump, not a normal pipeline step. Vite/React SPA reads `recipes_public`.

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

Devcontainer `.env`: `SUPABASE_DB_URL=postgresql://postgres:postgres@host.docker.internal:54322/postgres`. App code (psycopg, JS clients, browser, the `psql` CLI) connects fine via this URL.

**Run `supabase` CLI commands from the Mac host** (where `supabase start` lives) — no `--db-url` flag needed; the CLI auto-detects its local cluster:

```bash
supabase db reset --yes
supabase migration up --include-all       # forward-apply, doesn't wipe data
supabase migration list
supabase db push --include-all
```

Use `migration up` when you want to add new migrations without losing local processed data; `db reset` wipes and replays migrations only — there are no seed files. To populate local with realistic data (taxonomy, cocktail aliases, recipes, etc.), restore a staging backup; see [docs/backups.md](docs/backups.md).

(If you ever need to invoke the `supabase` CLI from inside the devcontainer — uncommon — its Go resolver picks an IPv6 form of `host.docker.internal` that isn't routable, and it defaults to TLS which the local Postgres rejects. Both surface as `tls error (server refused TLS connection)`. Workaround: pass `--db-url` with your container's gateway IPv4 plus `?sslmode=disable`. The literal varies by environment — `getent hosts host.docker.internal` and `ip route` show what's reachable from your container.)

**Test DB.** DB-integration tests (in `ingredients/tests/test_db.py`, et al) run against `TEST_DB_URL` — a *separate* Postgres database from `SUPABASE_DB_URL` — so `pytest` can `TRUNCATE … CASCADE` freely without nuking the dev data. Add this to `.env`:

```
TEST_DB_URL=postgresql://postgres:postgres@host.docker.internal:54322/spiritolo_test
```

The `ingredients` conftest auto-creates the database if missing and applies any new `supabase/migrations/*.sql` files on session start (tracked in a `_test_db_migrations` table). With `TEST_DB_URL` unset, DB tests skip cleanly. The conftest refuses to run if `TEST_DB_URL` equals `SUPABASE_DB_URL` or points at the default `postgres` database.

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
| Ingredient → taxonomy mapping | `MAPPER_VERSION` | [mapping/mapper.py](ingredients/src/ingredients/mapping/mapper.py) |

## Pipeline stages

- **`classify.py`** — local ollama on `content_type IS NULL` rows. Iterate prompts via `--review` against the checked-in eval set; use `--sample` for spot-checks. Bump `PROMPT_VERSION` after edits.
- **`validate.py`** — fetch runs validation + drink scoring inline, so this CLI exists only to re-evaluate cached HTML after a version bump.
- **`extract.py`** — parses Schema.org Recipe JSON-LD into Supabase `recipes`. UPSERTs on `source_url`; re-runs are idempotent. To re-extract: clear `extract_runs` rows.

## Spirits Taxonomy

DAG of canonical ingredients. **Read [docs/spirits-taxonomy.md](docs/spirits-taxonomy.md) before adding nodes** — the lean stance (taxonomy for definitional categories + hard constraints; vector layer for soft similarity) is load-bearing. Don't add sensory, stylistic, or colloquial nodes.

Two non-obvious rules worth surfacing here (full treatment in the doc):

- **Brand and product names always get their own nodes** (`node_kind='brand'` / `'expression'`), never aliases. Aliases are reserved for capitalization/punctuation/language variants of one canonical name, plus the brand-as-substance carve-out (`'aromatic bitters'` → `angostura_bitters`).
- **`is_cluster_node` cuts the DAG asymmetrically.** A type node is the cluster identity in some branches (`orange_bitters`, `bourbon`); an expression node is the cluster identity in others (`angostura_bitters`, `peychauds_bitters` — brand-as-substance). The only invariant: no `is_cluster_node` node has an `is_cluster_node` ancestor.

Taxonomy nodes are managed on staging via the curation UI; they are not maintained as local seed files. To work against current reference data locally, restore a fresh `scripts/backup-supabase.sh` dump (see [docs/backups.md](docs/backups.md)).

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

## Ingredient → Taxonomy Mapper

The mapper resolves `recipe_ingredients.name` strings to `taxonomy_nodes.id` references in two phases:

- **Phase 1** (alias + lexical) runs eagerly with no external deps. Misses are marked `mapper_source='pending_llm'`.
- **Phase 2** (LLM) is operator-triggered. Provider chosen at invocation: `--provider claude` (Anthropic, modest cost) or `--provider ollama` (local qwen3:14b, free). The CLI prints residual count + top-N before any external call.

**Versioning:** `MAPPER_VERSION` in [mapping/mapper.py](ingredients/src/ingredients/mapping/mapper.py). Stored on every mapped row.

**Typical usage (from repo root):**

```bash
# Phase 1 — alias + lexical against unresolved rows.
cd ingredients && uv run python -m ingredients.cli map

# Scoped, with a row cap.
cd ingredients && uv run python -m ingredients.cli map --site punch --limit 500

# Spot-check pending names without writing.
cd ingredients && uv run python -m ingredients.cli map --sample 25

# Run the eval set against the fixture taxonomy (needs TEST_DB_URL).
cd ingredients && uv run python -m ingredients.cli map --review

# Phase 2 — drain the pending_llm queue with a provider. Confirms before any cost.
cd ingredients && uv run python -m ingredients.cli map resolve-pending --provider claude
cd ingredients && uv run python -m ingredients.cli map resolve-pending --provider ollama --limit 100

# Walk the form-proposal review queue.
cd ingredients && uv run python -m ingredients.cli map review-proposals

# After bumping MAPPER_VERSION, re-map everything left at the old version.
cd ingredients && uv run python -m ingredients.cli map --reset --except-version v1 --yes
```

Brand/expression nodes auto-create silently when the LLM proposes one with an existing parent; provenance is recorded in `taxonomy_provenance`. Form nodes (lemon_zest, lime_oil, ...) queue in `taxonomy_proposals` for human review via `map review-proposals`. Auto-created nodes default to `is_cluster_node = false` (the column added by `[E]`); the antichain stays curator-controlled.

The eval set is `ingredients/src/ingredients/mapping/eval_set.py`, run against the fixture taxonomy in `ingredients/src/ingredients/mapping/eval_fixture.py` so eval results don't drift with seed changes.

`ANTHROPIC_API_KEY` is required for `--provider claude`; `OLLAMA_BASE_URL` defaults to `http://localhost:11434` for `--provider ollama`.

## Recipe Dedup

E groups recipes that represent the same drink into a `recipe_clusters` row, with per-recipe `cluster_id` + `variant_key` on `recipes`. Cluster identity is `hash(canonical_name, role-tagged ingredient set rolled up to a curated antichain in the taxonomy DAG)`. Two recipes share a variant iff they also share amounts and brand call-outs; multiple sources publishing identical recipes collapse to one variant with `source_count > 1`.

**Versioning:**
- `NORMALIZER_VERSION` in [dedup/version.py](ingredients/src/ingredients/dedup/version.py) — name normalization (alias + lexical + LLM phases).
- `DEDUP_VERSION` in the same file — role classification + cluster + variant compute.

**Typical usage (from repo root):**

```bash
# Phase 1: alias + lexical name normalization (deterministic).
cd ingredients && uv run python -m ingredients.cli normalize-names

# Inspect what's queued for Phase 2.
cd ingredients && uv run python -m ingredients.cli normalize-names list-pending --limit 50

# Phase 2: drain the pending_llm queue with a chosen provider.
cd ingredients && uv run python -m ingredients.cli normalize-names resolve-pending --provider ollama
cd ingredients && uv run python -m ingredients.cli normalize-names resolve-pending --provider claude

# Cluster compute. Tags roles, computes cluster + variant keys,
# writes recipe_clusters / recipes.cluster_id / recipes.variant_key.
cd ingredients && uv run python -m ingredients.cli cluster

# Audit signals (operator triages by hand — no automated remediation).
cd ingredients && uv run python -m ingredients.cli cluster audit

# One-shot post-D substance promotion (Campari, Aperol, Angostura, etc.
# auto-created as brand/expression by D's mapper become substance-role
# antichain nodes).
cd ingredients && uv run python -m ingredients.cli promote-substances

# Convenience: phase-1 normalize + cluster in one go.
cd ingredients && uv run python -m ingredients.cli dedup-all

# Run the eval set against the fixture (no DB writes).
cd ingredients && uv run python -m ingredients.cli normalize-names --review
cd ingredients && uv run python -m ingredients.cli cluster --review

# After bumping a version constant, re-run leftovers.
cd ingredients && uv run python -m ingredients.cli normalize-names --reset --except-version v1 --yes
cd ingredients && uv run python -m ingredients.cli cluster --reset --except-version v1 --yes
```

The canonical-name pool grows bottom-up on staging: ~20 well-known cocktails are bootstrapped as `cocktail_aliases`, and LLM resolutions add to it. Restore a staging backup to get the current pool locally.

The eval set is [dedup/eval_set.py](ingredients/src/ingredients/dedup/eval_set.py), run against the fixture taxonomy in [dedup/eval_fixture.py](ingredients/src/ingredients/dedup/eval_fixture.py) so eval results don't drift with seed changes.

## Data flow

Schema is the only thing that flows local → staging (via the migrations CI workflow on push to the `staging` branch). **Pipeline data lives on staging** — it is the source of truth for `recipes`, `recipe_ingredients`, `recipe_clusters`, taxonomy growth, etc. Pipelines that mutate this data (the parser, mapper LLM phase, normalize-names LLM phase, cluster compute) should be pointed at staging via `SUPABASE_DB_URL` rather than producing local-only state that has to be sync'd back.

**Local dev** has two viable shapes:

- **Schema-only:** `supabase db reset` is enough. You get the migrated schema and empty tables. Fine for UI work and migration writing, but you'll need to re-invite an admin via Studio after the reset to use anything that requires auth.
- **Schema + a snapshot of staging data:** restore a `scripts/backup-supabase.sh` dump into the local DB. This is the only way to get current reference data (taxonomy, cocktail aliases) and any pipeline output locally. See [docs/backups.md](docs/backups.md).

## Hosting

The app is hosted on Supabase + Vercel free tiers under the project name
`spiritolo-staging`. There is no separate production environment yet.

**Branches:**

- `main` — integration trunk. PRs from `claude/<topic>` branches land here.
  Deploys nowhere.
- `staging` — deploy trunk. Both Vercel and the migrations workflow watch
  this branch.

**Promotion (run locally):**

```bash
git checkout staging
git merge --ff-only main
git push
```

If `--ff-only` refuses, something landed on `staging` that isn't on `main`.
Investigate before forcing.

**Frontend deploys:** Vercel handles them natively on every push to
`staging` (production) and every PR (preview).

**Migrations:** [.github/workflows/deploy-migrations.yml](.github/workflows/deploy-migrations.yml) pushes any
migration changes to staging when `staging` advances. Requires the
`SUPABASE_STAGING_DB_URL` repo secret.

**Auth:** Magic-link only, no self-signup. Create users from Supabase
Studio (Authentication → Users → Invite). After their first sign-in,
flip `profiles.is_admin` in the table editor to grant admin access.

**Backups:** [scripts/backup-supabase.sh](scripts/backup-supabase.sh)
runs `pg_dump` of staging's `public` schema (excluding `profiles`).
Manual locally; via the `Backup staging database` GH Action in CI
(currently `workflow_dispatch`-only). Restore flow + caveats in
[docs/backups.md](docs/backups.md).

See [docs/deployment.md](docs/deployment.md) for the full picture
(Vercel project + URL, Supabase project URL, Resend constraints).

## Web UI

Reads `recipes_public` via the publishable key (`sb_publishable_…`, post-Nov-2025 replacement for the legacy anon key). No backend.

```bash
cd web && npm install
cp .env.local.example .env.local   # paste publishable key from `supabase status`
npm run dev                        # localhost:5173, VS Code auto-forwards
npm test                           # Vitest + @testing-library/react
```

Main suite: [normalizeRecipe.test.ts](web/src/normalizeRecipe.test.ts) covers messy Schema.org Recipe variants. Supabase must be running on the host for the dev server to load data.
