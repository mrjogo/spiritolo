<!-- [repo-mixin:devcontainer-claude] Base CLAUDE.md with PR conventions. -->

# spiritolo

Cocktail recipe scraper + verification UI, in two zones. **Zone 1 (`scraper/`)** crawls: discover → classify_url → fetch (runs HTML validation + drink scoring inline), caching page HTML. **Zone 2 (`ingredients/`)** builds the relational recipe from those pages: extract → parse → map → convert → cluster → export, each a versioned stage over the `stage_runs` ledger. Vite/React SPA reads `recipes_public`.

- `scraper/` — Python 3.11+ (uv), pytest. Zone-1 stage CLIs in `scraper/src/scraper/{discover,classify,fetch,validate}.py`. Work queue: `data/scraper.db` (SQLite).
- `ingredients/` — Zone-2 content pipeline + the always-on worker. Stages in `ingredients/src/ingredients/pipeline/stages/`; depends on `common/`, not on `scraper/`.
- `common/` — shared utilities (`supabase_client`, `providers`, `progress`, `summary`, `cli_common`), a root-level uv workspace both zones depend on.
- `supabase/migrations/` — `recipes`/`recipe_ingredients`/`recipe_steps`, `taxonomy_*`, `ingredient_resolutions`, `recipe_clusters`, `jobs` + `stage_runs`.
- `web/` — Vite + React + TS + Vitest.
- `docs/` — design + roadmap.

Run `cd scraper && uv run …`, `cd ingredients && uv run …`, and `cd web && npm …` from the repo root.

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

**Test DB.** DB-integration tests (`ingredients/tests/test_stage_map.py`, the upload smoke tests in `scripts/tests/`, et al) run against `TEST_DB_URL` — a *separate* Postgres database from `SUPABASE_DB_URL` — so `pytest` can `TRUNCATE … CASCADE` freely without nuking the dev data. Add this to `.env`:

```
TEST_DB_URL=postgresql://postgres:postgres@host.docker.internal:54322/spiritolo_test
```

The `ingredients` conftest auto-creates `spiritolo_test` if missing and applies any new `supabase/migrations/*.sql` files on session start (tracked in a `_test_db_migrations` table). It refuses to run if `TEST_DB_URL` equals `SUPABASE_DB_URL` or points at the default `postgres` database. The `scripts` conftest (for the upload smoke tests) derives two ephemeral DBs from `TEST_DB_URL` (`<base>_upload_local`, `<base>_upload_staging`), drops+recreates them per session, and re-applies all migrations fresh — its names don't collide with the dev DB by construction. With `TEST_DB_URL` unset, DB tests in either suite skip cleanly.

URL classifier needs ollama: `ollama pull qwen3:14b`.

## Data model

**Zone 1 — `data/scraper.db` (SQLite).** `pages` is the canonical per-URL state. Each scraper stage has a `*_runs` table (latest-only UPSERT, prunable — deleting puts pages back on the work queue). A stage's queue is "qualifies AND has no `*_runs` row." Snapshot columns (`pages_*_before`) record what flipped.

**Zone 2 — Supabase (relational content model).** The recipe is stored across `recipes` (header + raw Schema.org `source` JSON-LD), `recipe_ingredients` (RecipeGF ingredient rows), and `recipe_steps` (verb-frame steps). Ingredient → taxonomy resolution is **shared and name-keyed** in `ingredient_resolutions` — fix a name once and every recipe that uses it follows, so a taxonomy correction never rewrites a recipe. Drink identity is derived into `recipe_clusters` (+ `recipes.cluster_id`/`variant_key`). Taxonomy is `taxonomy_nodes` / `taxonomy_edges` / `taxonomy_aliases` (multi-parent DAG, see Spirits Taxonomy below). The RecipeGF bundle a consumer imports is generated on demand from these rows; only a published export is frozen (`recipe_exports`). The website reads `recipes_public`.

**Run ledgers.** Every Zone-2 stage records exactly one latest-only `stage_runs` row per `(entity, stage)` at its version constant; a stage's queue is "content qualifies AND no `stage_runs` row at the current version," so deleting rows re-queues work. The worker claims `jobs` rows (dispatch intent — "run `<stage>` over `<payload scope>`"): free/deterministic stages enqueue straight to `queued`, metered LLM stages enqueue to `awaiting_approval` for a confirm-before-cost gate.

## Pipeline conventions

**Zone-1 scraper CLIs** (`fetch`, `classify`, `validate`) share `--site` / `--limit` / `--dry-run` / `--reset [--site S] [--except-version V] [--older-than ISO_TS] [--yes]`. Bare `--reset` wipes the stage's eval scope.

- `validate --reset` clears `validate_html_runs` + `classify_drink_runs` together.
- `classify --reset` also nulls `pages.content_type` (its queue gates on `content_type IS NULL`, not eval-row presence).

**Zone-2 stages** take no reset flags; you re-queue by deleting the relevant `stage_runs` rows (or bumping the version constant, which drops the old rows out of the queue).

**Versioning:** every stage/evaluator carries a version constant recorded on its run rows. When you change logic, bump the constant so prior-version rows fall back onto the work queue.

Zone 1:

| Stage | Constant | File |
|---|---|---|
| URL classification | `PROMPT_VERSION` | [classify_prompt.py](scraper/src/scraper/classify_prompt.py) |
| HTML validation | `VALIDATOR_VERSION` | [validation.py](scraper/src/scraper/validation.py) |
| Drink scoring | `SCORER_VERSION` | [classify_drink.py](scraper/src/scraper/classify_drink.py) |

Zone 2 (`ingredients/`):

| Stage | Constant | File |
|---|---|---|
| Extract (JSON-LD → recipes) | `EXTRACTOR_VERSION` | [pipeline/stages/extract.py](ingredients/src/ingredients/pipeline/stages/extract.py) |
| Parse (ingredient strings) | `PARSER_VERSION` | [parser.py](ingredients/src/ingredients/parser.py) |
| Map (name → taxonomy slug) | `MAPPER_VERSION` | [pipeline/stages/map.py](ingredients/src/ingredients/pipeline/stages/map.py) |
| Name normalization | `NORMALIZER_VERSION` | [dedup/version.py](ingredients/src/ingredients/dedup/version.py) |
| Cluster (dedup identity) | `DEDUP_VERSION` | [dedup/version.py](ingredients/src/ingredients/dedup/version.py) |
| Convert + Export (RecipeGF) | `CONVERTER_VERSION` | [recipegf/version.py](ingredients/src/ingredients/recipegf/version.py) |

## Zone-1 pipeline stages (scraper)

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

Schema.org Recipe JSON-LD extraction is no longer a scraper CLI — the Zone-2 `extract` stage owns page → `recipes` now (see below).

## Spirits Taxonomy

DAG of canonical ingredients. **Read [docs/spirits-taxonomy.md](docs/spirits-taxonomy.md) before adding nodes** — the lean stance (taxonomy for definitional categories + hard constraints; vector layer for soft similarity) is load-bearing. Don't add sensory, stylistic, or colloquial nodes.

Three non-obvious rules worth surfacing here (full treatment in the doc):

- **Slugs are kebab-case** — `taxonomy_nodes.slug` and `taxonomy_proposals.proposed_slug` carry a DB CHECK forbidding underscores (`slug !~ '_'`). The LLM prompt at [mapping/prompt.py](ingredients/src/ingredients/mapping/prompt.py) instructs `<kebab-case>` for `propose_brand` / `propose_form`. Display names and taxonomy aliases are free-text (spaces, capitalization, accents fine); only slugs are constrained.
- **Brand and product names always get their own nodes** (`node_kind='brand'` / `'expression'`), never aliases. Aliases are reserved for capitalization/punctuation/language variants of one canonical name, plus the brand-as-substance carve-out (`'aromatic bitters'` → `angostura-bitters`).
- **`is_cluster_node` cuts the DAG asymmetrically.** A type node is the cluster identity in some branches (`orange-bitters`, `bourbon`); an expression node is the cluster identity in others (`angostura-bitters`, `peychauds-bitters` — brand-as-substance). The only invariant: no `is_cluster_node` node has an `is_cluster_node` ancestor.

Taxonomy nodes are managed on staging via the curation UI; they are not maintained as local seed files. To work against current reference data locally, restore a fresh `scripts/backup-supabase.sh` dump (see [docs/backups.md](docs/backups.md)).

## Content pipeline (Zone 2)

`ingredients/` turns crawled pages into the relational recipe. Each stage is a `stage_fn(job, conn, providers)` registered into `worker.dispatch.STAGE_FNS`; the run order is **extract → parse → map → convert → cluster → export**. A stage resolves its work queue from `stage_runs` ("content qualifies AND no run at the current version"), does its work over a provider chain (deterministic tier first, an LLM tier for the residue), writes its content rows, and UPSERTs one `stage_runs` row per entity — so a re-run only touches what a prior run left undone.

**Two run surfaces:**

- **CLI — one stage, or the whole cold build, deterministically.** It passes no providers, so LLM tiers are skipped and anything only an LLM could resolve parks as `pending`. Good for a local cold build off a staging restore.

  ```bash
  cd ingredients && uv run python -m ingredients.cli <stage>            # extract|parse|map|convert|cluster|export
  cd ingredients && uv run python -m ingredients.cli map --site punch --limit 200
  cd ingredients && uv run python -m ingredients.cli cold-build         # every stage in order
  ```

  Every subcommand takes `--site` / `--limit`. To re-run a stage, delete its `stage_runs` rows or bump the version constant. (Verified against [cli.py](ingredients/src/ingredients/cli.py) + [coldbuild.py](ingredients/src/ingredients/pipeline/coldbuild.py): the subcommands are exactly `extract`, `parse`, `map`, `convert`, `cluster`, `export`, `cold-build` — no `--review` / `--reset` / `--dry-run` / provider flags.)

- **Worker — the always-on daemon over the `jobs` queue.** Claims a job (`FOR UPDATE SKIP LOCKED`), dispatches it to its stage_fn with a config-not-code `ProviderChain` (LLM tiers + a per-job cost cap), heartbeats while it runs, then finalizes. Provider chains are wired from `PROVIDER_CHAIN_CONFIG` (a JSON file); the schema is never rewired for a provider change.

  ```bash
  cd ingredients && uv run python -m ingredients.worker
  ```

  Jobs are enqueued via the `enqueue_job` RPC (the `/ops` console) — a free stage lands in `queued`, a metered one in `awaiting_approval` until an admin approves it.

**The stages:**

- **extract** — reads a classified page's cached HTML from the R2 corpus, finds the Schema.org Recipe JSON-LD, and UPSERTs a `recipes` row (raw `source` verbatim + derived title/author/image). No Recipe JSON-LD → the LLM tier synthesizes a recipe source from the page, else it abstains.
- **parse** — parses each `recipes.source` `recipeIngredient` string with strict abstain discipline into `recipe_ingredients` (RecipeGF shape: name + amount/amount_max/unit + `string[]` modifiers). `PARSER_VERSION` in [parser.py](ingredients/src/ingredients/parser.py); bump on any rule or unit-table change.
- **map** — resolves each `recipe_ingredients.name` to a taxonomy slug in the **shared** `ingredient_resolutions` (name-keyed — resolved once for every recipe that uses it): alias → lexical → LLM tier → abstain. An LLM `propose_brand`/expression whose parent slug already exists auto-creates the node + edge + `taxonomy_provenance` (`is_cluster_node=false`) and writes the resolution; a `propose_form` queues a `taxonomy_proposals` row for human review (the curation UI) and parks the name.
- **convert** — deterministic technique keyword scan → RecipeGF verb-frame `recipe_steps`. Anything uncertain (no technique, muddle, untranslatable unit, unresolved ingredient) records a `pending` / `proposes_new` outcome in `stage_runs` and writes no steps.
- **cluster** — normalizes the cocktail name (`NORMALIZER_VERSION`), role-tags ingredients and rolls them up to the curated antichain, then writes `recipe_clusters` (+ `recipes.cluster_id`/`variant_key`). Cluster identity is `hash(canonical_name, role-tagged rolled-up ingredient set)`; two recipes share a variant iff they also share amounts and brand call-outs, so identical recipes from multiple sources collapse to one variant with `source_count > 1`.
- **export** — freezes the on-demand bundle into `recipe_exports`, keyed by recipe + `CONVERTER_VERSION`.

**Generate-on-demand bundles.** Spiritolo emits validated **RecipeGF pin-2 bundles** — one per recipe — so a consumer (Barbot) imports self-contained docs with no runtime dependency on Spiritolo. The bundle is `{recipe, verbs:[<spiritolo/ defs used>], meta:{slug, source, imported_at}}`, generated from `recipes` + `recipe_ingredients` + `recipe_steps` by [recipegf/generate.py](ingredients/src/ingredients/recipegf/generate.py) (`generate_bundle`) — not a stored blob. Depends on the pinned `recipegf` v0.4.0 library; **read [docs/recipegf-export.md](docs/recipegf-export.md)**. Non-obvious invariants:

- **Recipe ids are reverse-DNS `com.spiritolo/<slug>:v1`.** A bare `spiritolo/<slug>` id is rejected — the `spiritolo` namespace is for VERBS, not recipe authorities. `meta.slug` equals `parse_recipe_id(id).slug`.
- **Bundles are self-contained:** each carries the `spiritolo/` extension verb-defs its steps reference, so a consumer validates against `core ∪ spiritolo/` with no external lookup. Extension verbs are self-describing YAML in [recipegf/verbs/](ingredients/src/ingredients/recipegf/verbs) (`spiritolo-blend.yaml`, `spiritolo-top.yaml`), loaded via RecipeGF's overlay API.

**Eval sets** run through pytest (`cd ingredients && uv run --extra dev pytest`), not a CLI flag: [eval_set.py](ingredients/src/ingredients/eval_set.py) (parser), [mapping/eval_set.py](ingredients/src/ingredients/mapping/eval_set.py) + [mapping/eval_fixture.py](ingredients/src/ingredients/mapping/eval_fixture.py), [dedup/eval_set.py](ingredients/src/ingredients/dedup/eval_set.py) + [dedup/eval_fixture.py](ingredients/src/ingredients/dedup/eval_fixture.py), and [recipegf/eval_set.py](ingredients/src/ingredients/recipegf/eval_set.py). Fixtures are frozen so eval results don't drift with seed changes.

**Providers + writes.** The worker's LLM tiers need credentials per chosen provider: `ANTHROPIC_API_KEY` (claude), `OLLAMA_BASE_URL` (defaults `http://localhost:11434`, ollama), `OPENAI_API_KEY` (openai). Writes go to whatever `SUPABASE_DB_URL` points at — including the taxonomy nodes the map stage's LLM tier auto-creates. The worker runs against the hosted DB directly; there is no separate upload step.

## Data flow

Schema flows local → staging via the migrations CI workflow on push to the `staging` branch. **Pipeline data lives on staging** — staging is the source of truth for `recipes`, `recipe_ingredients`, `recipe_steps`, `ingredient_resolutions`, `recipe_clusters`, taxonomy growth, etc. Pipeline runs execute against the hosted DB directly — the worker daemon over the `jobs` queue, or the CLI pointed at `SUPABASE_DB_URL`. One-off SQL hand-edits and the curation UI hit staging directly.

**Local dev** has two viable shapes:

- **Schema-only:** `supabase db reset` is enough. You get the migrated schema, empty tables, and a pre-seeded `admin@local.test` magic-link user (see [supabase/seeds/dev_admin_user.local-only.sql](supabase/seeds/dev_admin_user.local-only.sql) — the only seed file). Fine for UI work and migration writing.
- **Schema + a snapshot of staging data:** restore a `scripts/backup-supabase.sh` dump into the local DB. This is the only way to get current reference data (taxonomy, cocktail aliases) and any pipeline output locally. The dev admin seed survives the restore (`profiles` and `auth.users` are excluded from the dump). See [docs/backups.md](docs/backups.md).

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
