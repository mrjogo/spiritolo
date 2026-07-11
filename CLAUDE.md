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

**Supabase runs on the host, not inside the devcontainer** (DooD vs `supabase start`'s bind mounts). The host may be a Mac (`brew install supabase/tap/supabase && supabase start`) or a Linux box running the Supabase Docker stack directly — either way it's reachable at the configured `SUPABASE_DB_URL` (and `TEST_DB_URL`), so the DB-integration tests run wherever a Postgres is reachable, not only on a Mac. Studio at http://localhost:54323.

Devcontainer `.env`: `SUPABASE_DB_URL=postgresql://postgres:postgres@host.docker.internal:54322/postgres`. App code (psycopg, JS clients, browser, the `psql` CLI) connects fine via this URL.

**Run `supabase` CLI commands from the host where the Supabase stack lives** (where `supabase start` / the Docker stack runs) — no `--db-url` flag needed; the CLI auto-detects its local cluster:

```bash
supabase db reset --yes
supabase migration up --include-all       # forward-apply, doesn't wipe data
supabase migration list
supabase db push --include-all
```

Use `migration up` when you want to add new migrations without losing local processed data; `db reset` wipes, replays migrations, and applies the single `dev_admin_user.local-only.sql` seed (creates the `admin@local.test` magic-link user — `profiles` and `auth.users` aren't in staging dumps, so this stays a seed). To populate local with realistic data (taxonomy, cocktail aliases, recipes, etc.), restore a staging backup; see [docs/backups.md](docs/backups.md).

(If you ever need to invoke the `supabase` CLI from inside the devcontainer — uncommon — its Go resolver picks an IPv6 form of `host.docker.internal` that isn't routable, and it defaults to TLS which the local Postgres rejects. Both surface as `tls error (server refused TLS connection)`. Workaround: pass `--db-url` with your container's gateway IPv4 plus `?sslmode=disable`. The literal varies by environment — `getent hosts host.docker.internal` and `ip route` show what's reachable from your container.)

**Test DB.** DB-integration tests (`ingredients/tests/test_db.py`, the upload smoke tests in `scripts/tests/`, et al) run against `TEST_DB_URL` — a *separate* Postgres database from `SUPABASE_DB_URL` — so `pytest` can `TRUNCATE … CASCADE` freely without nuking the dev data. Add this to `.env`:

```
TEST_DB_URL=postgresql://postgres:postgres@host.docker.internal:54322/spiritolo_test
```

The `ingredients` conftest auto-creates `spiritolo_test` if missing and applies any new `supabase/migrations/*.sql` files on session start (tracked in a `_test_db_migrations` table). It refuses to run if `TEST_DB_URL` equals `SUPABASE_DB_URL` or points at the default `postgres` database. The `scripts` conftest (for the upload smoke tests) derives two ephemeral DBs from `TEST_DB_URL` (`<base>_upload_local`, `<base>_upload_staging`), drops+recreates them per session, and re-applies all migrations fresh — its names don't collide with the dev DB by construction. With `TEST_DB_URL` unset, DB tests in either suite skip cleanly.

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
| URL classification | `PROMPT_VERSION` | [classify_prompt.py](scraper/src/scraper/classify_prompt.py) |
| HTML validation | `VALIDATOR_VERSION` | [validation.py](scraper/src/scraper/validation.py) |
| Drink scoring | `SCORER_VERSION` | [classify_drink.py](scraper/src/scraper/classify_drink.py) |
| JSON-LD extraction | `EXTRACTOR_VERSION` | [extract.py](scraper/src/scraper/extract.py) |
| Ingredient → taxonomy mapping | `MAPPER_VERSION` | [mapping/mapper.py](ingredients/src/ingredients/mapping/mapper.py) |
| RecipeGF export conversion | `CONVERTER_VERSION` | [recipegf/version.py](ingredients/src/ingredients/recipegf/version.py) |

## Pipeline stages

- **`classify.py`** — classifies `content_type IS NULL` rows via LLM. Provider: `--provider ollama` (local qwen3:14b, default), `--provider claude`, or `--provider openai`. Iterate prompts via `--review` against the checked-in eval set; use `--sample` for spot-checks. Bump `PROMPT_VERSION` after edits.

  **Batch mode (OpenAI only):** 50% off real-time, ~24h SLA. Submit once, ingest later.

  ```bash
  # Submit and exit (prints batch_id + sidecar path).
  cd scraper && uv run python -m scraper.classify --provider openai --batch --yes

  # Ingest results after the batch completes.
  cd scraper && uv run python -m scraper.classify --provider openai --batch --ingest <batch_id>

  # One-shot: submit + poll + ingest inline (blocks until done).
  cd scraper && uv run python -m scraper.classify --provider openai --batch --wait --yes
  ```

  Sidecar at `data/batches/<batch_id>.json` (gitignored). Lose it and you must re-derive from the OpenAI dashboard or re-submit.
- **`validate.py`** — fetch runs validation + drink scoring inline, so this CLI exists only to re-evaluate cached HTML after a version bump.
- **`extract.py`** — parses Schema.org Recipe JSON-LD into Supabase `recipes` at whatever `SUPABASE_DB_URL` points at. UPSERTs on `source_url`; re-runs are idempotent. To re-extract: clear `extract_runs` rows. Bulk runs follow the local-restore-then-upload flow — see [docs/upload.md](docs/upload.md).

## Spirits Taxonomy

DAG of canonical ingredients. **Read [docs/spirits-taxonomy.md](docs/spirits-taxonomy.md) before adding nodes** — the lean stance (taxonomy for definitional categories + hard constraints; vector layer for soft similarity) is load-bearing. Don't add sensory, stylistic, or colloquial nodes.

Three non-obvious rules worth surfacing here (full treatment in the doc):

- **Slugs are kebab-case** — `taxonomy_nodes.slug` and `taxonomy_proposals.proposed_slug` carry a DB CHECK forbidding underscores (`slug !~ '_'`). The LLM prompt at [mapping/prompt.py](ingredients/src/ingredients/mapping/prompt.py) instructs `<kebab-case>` for `propose_brand` / `propose_form`. Display names and taxonomy aliases are free-text (spaces, capitalization, accents fine); only slugs are constrained.
- **Brand and product names always get their own nodes** (`node_kind='brand'` / `'expression'`), never aliases. Aliases are reserved for capitalization/punctuation/language variants of one canonical name, plus the brand-as-substance carve-out (`'aromatic bitters'` → `angostura-bitters`).
- **`is_cluster_node` cuts the DAG asymmetrically.** A type node is the cluster identity in some branches (`orange-bitters`, `bourbon`); an expression node is the cluster identity in others (`angostura-bitters`, `peychauds-bitters` — brand-as-substance). The only invariant: no `is_cluster_node` node has an `is_cluster_node` ancestor.

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

Writes go to whatever `SUPABASE_DB_URL` points at. Bulk runs use the local-restore-then-upload flow — see [docs/upload.md](docs/upload.md).

**Common, scraper, ingredients packages.** `common/` holds shared utilities (`supabase_client`, `progress`, `summary`, `cli_common`); both `scraper/` (Zone 1) and `ingredients/` (Zone 2) depend on it via the root-level uv workspace.

## Ingredient → Taxonomy Mapper

The mapper resolves `recipe_ingredients.name` strings to `taxonomy_nodes.id` references in two phases:

- **Phase 1** (alias + lexical) runs eagerly with no external deps. Misses are marked `mapper_source='pending_llm'`.
- **Phase 2** (LLM) is operator-triggered. Provider chosen at invocation: `--provider claude` (Anthropic, modest cost), `--provider ollama` (local qwen3:14b, free), or `--provider openai` (default gpt-5-mini). The CLI prints residual count + top-N before any external call.

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
cd ingredients && uv run python -m ingredients.cli map resolve-pending --provider openai

# Batch mode (OpenAI only): 50% off real-time, ~24h SLA.
cd ingredients && uv run python -m ingredients.cli map resolve-pending --provider openai --batch --yes
cd ingredients && uv run python -m ingredients.cli map resolve-pending --provider openai --batch --ingest <batch_id>
cd ingredients && uv run python -m ingredients.cli map resolve-pending --provider openai --batch --wait --yes

# Walk the form-proposal review queue.
cd ingredients && uv run python -m ingredients.cli map review-proposals

# After bumping MAPPER_VERSION, re-map everything left at the old version.
cd ingredients && uv run python -m ingredients.cli map --reset --except-version v1 --yes

# Unpark names that previous runs parked at 'pending_llm_tried' (e.g.
# after approving a form proposal or editing the taxonomy). Then re-run
# `map resolve-pending --provider …` to re-submit.
cd ingredients && uv run python -m ingredients.cli map retry-failures
```

The chunked Batch drain (`--batch`) parks any name that didn't get a clearing action ('chose' or 'abstain') from a chunk's ingest — most commonly `propose_form`, but also parse failures and transient provider errors — by flipping `mapper_source` to `pending_llm_tried`. Parked names are excluded from `fetch_pending_llm_names`, so subsequent chunks and subsequent runs don't re-submit them. Run `map retry-failures` to unpark after the blocker is resolved.

Brand/expression nodes auto-create silently when the LLM proposes one with an existing parent; provenance is recorded in `taxonomy_provenance`. Form nodes (lemon_zest, lime_oil, ...) queue in `taxonomy_proposals` for human review via `map review-proposals`. Auto-created nodes default to `is_cluster_node = false` (the column added by `[E]`); the antichain stays curator-controlled.

The eval set is `ingredients/src/ingredients/mapping/eval_set.py`, run against the fixture taxonomy in `ingredients/src/ingredients/mapping/eval_fixture.py` so eval results don't drift with seed changes.

`ANTHROPIC_API_KEY` is required for `--provider claude`; `OLLAMA_BASE_URL` defaults to `http://localhost:11434` for `--provider ollama`; `OPENAI_API_KEY` is required for `--provider openai` (defaults to model `gpt-5-mini`, override with `--model <id>`).

Writes go to whatever `SUPABASE_DB_URL` points at — including the LLM-resolved nodes Phase 2 auto-creates. Bulk runs (especially Phase 2, which costs money) use the local-restore-then-upload flow — see [docs/upload.md](docs/upload.md).

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
cd ingredients && uv run python -m ingredients.cli normalize-names resolve-pending --provider openai

# Batch mode (OpenAI only): 50% off real-time, ~24h SLA.
cd ingredients && uv run python -m ingredients.cli normalize-names resolve-pending --provider openai --batch --yes
cd ingredients && uv run python -m ingredients.cli normalize-names resolve-pending --provider openai --batch --ingest <batch_id>
cd ingredients && uv run python -m ingredients.cli normalize-names resolve-pending --provider openai --batch --wait --yes

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

# Unpark names that previous runs parked at 'pending_llm_tried'.
cd ingredients && uv run python -m ingredients.cli normalize-names retry-failures
```

The chunked Batch drain parks names whose chunk didn't produce a clearing action by flipping `canonical_name_source` to `pending_llm_tried`. Run `normalize-names retry-failures` to unpark.

The canonical-name pool grows bottom-up on staging: ~20 well-known cocktails are bootstrapped as `cocktail_aliases`, and LLM resolutions add to it. Restore a staging backup to get the current pool locally.

The eval set is [dedup/eval_set.py](ingredients/src/ingredients/dedup/eval_set.py), run against the fixture taxonomy in [dedup/eval_fixture.py](ingredients/src/ingredients/dedup/eval_fixture.py) so eval results don't drift with seed changes.

Writes go to whatever `SUPABASE_DB_URL` points at. Bulk runs use the local-restore-then-upload flow — see [docs/upload.md](docs/upload.md).

## RecipeGF Export

Spiritolo emits validated **RecipeGF pin-2 bundles** — one per drink
(`recipe_clusters` row) — so Barbot can import self-contained recipe docs with
no runtime dependency on Spiritolo. This is the P2 half of the cross-repo
recipe-identity design; **read [docs/recipegf-export.md](docs/recipegf-export.md)**
for the full treatment. Depends on the pinned `recipegf` v0.3.0 library (P1).

The bundle is `{recipe, verbs:[<spiritolo/ defs used>], meta:{slug, source, imported_at}}`.
Non-obvious invariants worth surfacing:

- **Recipe ids are reverse-DNS `com.spiritolo/<slug>:v1`.** A bare
  `spiritolo/<slug>` recipe id is rejected — the `spiritolo` namespace is for
  VERBS, not recipe authorities. `meta.slug` always equals
  `parse_recipe_id(id).slug` (via RecipeGF's parser).
- **Bundles are self-contained**: each carries the `spiritolo/` extension
  verb-defs its steps reference, so a consumer validates against
  `core ∪ spiritolo/` with no external lookup. Extension verbs live as
  self-describing YAML in [recipegf/verbs/](ingredients/src/ingredients/recipegf/verbs)
  (`spiritolo/blend`, `spiritolo/top`), loaded via RecipeGF's overlay API — D2b:
  iterate verbs in-repo, no RecipeGF PR per verb.
- **Deterministic Phase-1 converter** (technique keyword scan → step template).
  Anything uncertain (no technique, muddle, untranslatable unit, unresolved
  ingredient, …) routes to propose→review in `recipegf_proposals`, mirroring
  `taxonomy_proposals`; the cluster parks at the current `CONVERTER_VERSION`.

```bash
cd ingredients && uv run python -m ingredients.cli recipegf-export            # convert queue
cd ingredients && uv run python -m ingredients.cli recipegf-export --out data/recipegf
cd ingredients && uv run python -m ingredients.cli recipegf-export --review   # eval set (no DB)
cd ingredients && uv run python -m ingredients.cli recipegf-export review-proposals
cd ingredients && uv run python -m ingredients.cli recipegf-export --reset --except-version v1 --yes
```

The eval set is [recipegf/eval_set.py](ingredients/src/ingredients/recipegf/eval_set.py) —
real cocktails as pure fixtures (the converter is pure, so `--review` needs no
DB). The verb-frame recipe is stored **relationally** (`recipegf_recipes` +
`recipegf_ingredients` + `recipegf_steps`), and the bundle is *generated on
demand* from those rows by `db.generate_bundle` — not a stored blob. Writes go to
whatever `SUPABASE_DB_URL` points at.

## Data flow

Schema flows local → staging via the migrations CI workflow on push to the `staging` branch. **Pipeline data lives on staging** — staging is the source of truth for `recipes`, `recipe_ingredients`, `recipe_clusters`, taxonomy growth, etc. Bulk pipeline runs (the parser, mapper Phase 1+2, normalize-names Phase 1+2, cluster compute, promote-substances) happen against a local restore of staging and are pushed back through the uploader; see "Local-edit / staging-upload workflow" below. One-off SQL hand-edits and the curation UI hit staging directly.

**Local dev** has two viable shapes:

- **Schema-only:** `supabase db reset` is enough. You get the migrated schema, empty tables, and a pre-seeded `admin@local.test` magic-link user (see [supabase/seeds/dev_admin_user.local-only.sql](supabase/seeds/dev_admin_user.local-only.sql) — the only seed file). Fine for UI work and migration writing.
- **Schema + a snapshot of staging data:** restore a `scripts/backup-supabase.sh` dump into the local DB. This is the only way to get current reference data (taxonomy, cocktail aliases) and any pipeline output locally. The dev admin seed survives the restore (`profiles` and `auth.users` are excluded from the dump). See [docs/backups.md](docs/backups.md).

## Local-edit / staging-upload workflow

For any pipeline run that would write to Supabase, prefer this flow over
hitting staging directly:

1. `scripts/backup-supabase.sh` — produces `<file>.dump` plus
   `<file>.dump.meta.json` (sidecar).
2. `pg_restore` the dump into local Supabase
   (see [docs/backups.md](docs/backups.md)).
3. Run pipelines pointed at local (`SUPABASE_DB_URL` already points
   there in the devcontainer .env).
4. Push the diff back:

   ```bash
   uv run --package spiritolo-scripts python -m upload_to_staging \
     --dump path/to/<file>.dump            # dry-run
   uv run --package spiritolo-scripts python -m upload_to_staging \
     --dump path/to/<file>.dump --apply    # actually push
   ```

The uploader refuses to run if the sidecar is missing, if the dump
doesn't match the staging URL it was taken from, if a migration landed
during the work session, or if staging was written to during the work
session. Full flow + checks + failure modes documented in
[docs/upload.md](docs/upload.md).

## Hosting

The app is hosted on Supabase + Vercel free tiers under the project name
`spiritolo-staging`. There is no separate production environment yet.

**Branches:**

- `main` — integration trunk. PRs from `claude/<topic>` branches land here.
  Deploys nowhere.
- `staging` — deploy trunk. Both Vercel and the migrations workflow watch
  this branch.

**Promotion (open a PR):** `staging` is locked to PR-only merges by a
repository ruleset — direct pushes (including `git push` and force-push)
are rejected. Promote by opening a PR **base `staging`, head `main`** and
merging it:

```bash
gh pr create --base staging --head main \
  --title "Promote main → staging" --body "…"
```

**Merge that PR with a _merge commit_ — never squash.** Squash-merging a
promotion fabricates a new commit on `staging` containing all of `main`'s
diff, which diverges the two branches at the content level and makes the
next promotion conflict. A merge commit keeps trees converging cleanly.

Do **not** expect `git merge --ff-only main` to work: GitHub's PR merge is
never a fast-forward, so every promotion adds a merge commit and `staging`
stays *topologically* ahead of `main` (by the accumulated merge commits)
even though their file trees are identical after each promotion. That
divergence is expected and benign — don't try to "fix" it with a rewrite.
(The one thing that breaks it is a squash-merged promotion; see above.)

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
