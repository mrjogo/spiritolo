<!-- [repo-mixin:devcontainer-claude] Base CLAUDE.md with PR conventions. -->

# spiritolo

Cocktail recipe scraper + verification UI, in two zones. **Zone 1 (`scraper/`)** crawls: discover → classify_url → fetch (runs HTML validation + drink scoring inline), caching page HTML. **Zone 2 (`ingredients/`)** builds the relational recipe from those pages: extract-recipe → parse-ingredients → map-ingredient → convert-steps → cluster-recipes → export-recipegf. An operator assembles explicit **runs** in `/ops` (a `jobs` row that owns per-entity `job_items`); an **executor thread inside the API process** processes a run's `pending` `job_items`. Everything is one Railway service: FastAPI (`app/`) serving the public API + `/api/ops` + the built React app, over a **SQLite** file on a volume, replicated by Litestream.

- `scraper/` — Python 3.11+ (uv), pytest. Zone-1 stage CLIs in `scraper/src/scraper/{discover,classify,fetch,validate}.py`. Work queue: `data/scraper.db` (SQLite).
- `ingredients/` — Zone-2 content pipeline (stages in `ingredients/src/ingredients/pipeline/stages/`, run logic in `runs.py`, the executor loop in `worker/runner.py`); depends on `common/`, not on `scraper/`.
- `common/` — shared utilities: `common.db` (the SQLite layer: psycopg-shaped `Connection`, migrations, audit triggers), `providers`, `text.trigram`, `progress`, `summary`, `cli_common`. A root-level uv workspace every other member depends on.
- `common/src/common/db/migrations/` — plain SQL, applied at boot in filename order, tracked in `schema_migrations`: `pages`, `taxonomy_*`, `recipes`/`recipe_ingredients`/`recipe_steps`, `ingredient_resolutions`, `recipe_clusters`, `recipe_exports`, `jobs` (runs) + `job_items` (per-entity membership + outcome), `human_reviews`, `audit_log`, `operators` + `passkeys`, and the views (`recipes_public`, `runs`, `taxonomy_public`, …). No down migrations: write a new forward one.
- `app/` — the service: package `spiritolo` (FastAPI). `settings.py` (env), `db.py` (per-thread connections), `auth.py` (passkeys + signed cookie), `executor.py` (the in-process run loop), `query.py` (the allowlisted generic table read behind `/api/ops/query`), `importdb.py` (database import), `routers/{public,auth,ops}.py`. Tests in `app/tests/`.
- `scripts/` — `pg_to_sqlite` (the one-time Postgres-dump → SQLite ETL), `entrypoint.sh`, `snapshot-sqlite.sh`, the legacy `corpus_loader`.
- `web/` — Vite + React + TS + Vitest. Talks to `/api` on the same origin (Vite proxies it in dev); `@simplewebauthn/browser` for passkeys.
- `Dockerfile`, `railway.json`, `litestream.yml`, `secrets.env` — the deploy, all declared in the repo (see Hosting).
- `docs/` — design + roadmap.

Run `cd scraper && uv run …`, `cd ingredients && uv run …`, `cd app && uv run …`, and `cd web && npm …` from the repo root.

## Workflow

**PRs:** `gh pr create` against `main` (occasionally `development`). Optional one-paragraph description, up to 8 bullets. No sections, no test plan. After merge: check out main, pull, delete branch. **Then tear down anything local you spun up for the work** — stop the dev API process and `npm run dev`, and delete any scratch SQLite files you created outside `data/`. Don't leave orphaned processes holding ports.

**Branches for AI agent sessions:** stay on the `claude/<topic>-<short-id>` branch named in the session task. Never push elsewhere.

## Local environment

There is no external database. The app, the CLI and every test open a SQLite file through `common.db.open_database`, which applies the bundled migrations on open. Nothing to install, start or stop.

**Run the service locally:**

```bash
cd app && uv run python -m spiritolo            # FastAPI + executor on :8000, DB at data/spiritolo.db (SPIRITOLO_DB)
cd web && npm run dev                           # Vite on :5173, proxies /api → :8000 (VITE_API_PROXY)
```

First visit to `/login` with an empty `operators` table offers **first-time passkey setup** (registers you as admin). `SESSION_SECRET` unset → a random per-process secret, so sessions die on restart — fine locally. `RUN_EXECUTOR=0` turns the executor thread off. To get realistic data locally, build a file from a staging dump with `scripts/pg_to_sqlite` (see [docs/migration.md](docs/migration.md)) or copy a Litestream restore / `VACUUM INTO` snapshot to `data/spiritolo.db`.

**Preview a branch against live data** (on barbot or any machine with `op` access to the vault): `scripts/preview.sh <branch>` serves it on a scratch Litestream restore with passkey-free `/api/auth/dev-login`; `scripts/preview.sh --smoke <branch>` runs the headless LLM smoke test (`python -m ingredients.smoke`) instead and prints a report. See [docs/pipeline.md](docs/pipeline.md#smoke-testing-an-llm-tier).

**Tests** need no services: every suite uses a fresh SQLite file under pytest's `tmp_path` (or in-memory).

```bash
cd common && uv run --extra dev pytest
cd ingredients && uv run --extra dev pytest
cd app && uv run --extra dev pytest
cd scripts && uv run --extra dev pytest
cd web && npm test
```

The `ingredients` conftest points `SPIRITOLO_DB` at a nonexistent path so an accidental fall-back fails loudly instead of touching `data/`. (`scripts/tests` still carries `TEST_DB_URL`-gated Postgres tests for the legacy `corpus_loader`; they skip when it is unset.)

**`common.db` conventions that bite:** JSON columns are declared `JSONTEXT` and come back parsed (dict/list); booleans are `BOOLEAN` → `bool`; timestamps are ISO-8601 UTC text (`SQL_NOW`); Python's `sqlite3` reports `rowcount` only for statements that *start* with INSERT/UPDATE/DELETE, so put a CTE after `insert into t (cols)`, not before. Use `conn.transaction()` for a unit of work (BEGIN IMMEDIATE, nested → SAVEPOINT) and `set_actor` so the audit triggers attribute the writes. pg_trgm similarity is `common.text.trigram.TrigramIndex`.

URL classifier needs ollama: `ollama pull qwen3:14b`.

## Data model

**Zone 1 — `data/scraper.db` (SQLite).** `pages` is the canonical per-URL state. Each scraper stage has a `*_runs` table (latest-only UPSERT, prunable — deleting puts pages back on the work queue). A stage's queue is "qualifies AND has no `*_runs` row." Snapshot columns (`pages_*_before`) record what flipped.

**Zone 2 — the service's SQLite file (relational content model).** The recipe is stored across `recipes` (header + raw Schema.org `source` JSON-LD), `recipe_ingredients` (RecipeGF ingredient rows), and `recipe_steps` (verb-frame steps). Ingredient → taxonomy resolution is **shared and name-keyed** in `ingredient_resolutions` — fix a name once and every recipe that uses it follows, so a taxonomy correction never rewrites a recipe. Drink identity is derived into `recipe_clusters` (+ `recipes.cluster_id`/`variant_key`). Taxonomy is `taxonomy_nodes` / `taxonomy_edges` / `taxonomy_aliases` (multi-parent DAG, see Spirits Taxonomy below); `taxonomy_nodes.status` gates a node's visibility — `live` (default) nodes are the real, placed taxonomy, while `provisional` nodes are freshly minted stubs awaiting harmonization and are hidden from `taxonomy_public` and skipped by the downstream cluster/convert/export stages. The RecipeGF bundle a consumer imports is generated on demand from these rows; only a published export is frozen (`recipe_exports`). The website reads `recipes_public`.

**Runs, not derived queues.** A **run** is a `jobs` row (`draft → queued → claimed → running → done`/`failed`) that carries a per-run LLM tier (`llm_provider`/`llm_model`). Its membership is the set of `job_items` it owns — one per `(job, entity)`, in state `pending → running → {applied | flagged | failed}`. Application is always immediate — a stage writes its content rows as it processes, so a terminal `applied` item is already live; there is no hold mode or deferred apply step. **`job_items` replaced `stage_runs`**: it's both the run's membership (when `pending`) and the per-entity outcome (when terminal), append-only across runs so an entity can be re-run. "Current status of entity X at stage Y" = its most recent terminal `job_item`; that derived status index powers the `/ops` add-tasks filter facets. The operator assembles a run in `/ops` (create → filter/select entities → load `pending` items → **Start**); the single cost gate is the Start-confirm modal (metered = the run's LLM tier is a hosted API; local `ollama` is free — no separate approval step). The executor claims a `queued` job and processes exactly its `pending` `job_items`. (The append-only `audit_log` captures each mutation tagged with the job id; it is written by per-connection TEMP triggers from an **explicit actor** (`human:<operator>` / `worker:<job>` / `system`) set via `common.db.audit.set_actor`, since the application is the only write path — the intended substrate for a future run rollback, which is not yet built. It stores *diffs*, not full row images: an UPDATE keeps only the `changed_keys` subset, an INSERT keeps the event with no payload, a DELETE keeps the whole row. That is lossless because the inserted value is recoverable from the current row by reverse-applying each UPDATE's `before` image newest → oldest — an invariant that holds only while a row's audit chain is unbroken, so **do not add retention or pruning to `audit_log`** without reinstating full INSERT payloads.)

## Pipeline conventions

**Zone-1 scraper CLIs** (`fetch`, `classify`, `validate`) share `--site` / `--limit` / `--dry-run` / `--reset [--site S] [--except-version V] [--older-than ISO_TS] [--yes]`. Bare `--reset` wipes the stage's eval scope.

- `validate --reset` clears `validate_html_runs` + `classify_drink_runs` together.
- `classify --reset` also nulls `pages.content_type` (its queue gates on `content_type IS NULL`, not eval-row presence).

**Zone-2 stages** are driven by explicit runs, not a version predicate. To (re)process entities, assemble a run in `/ops` and select them — including already-`applied` ones to force a re-run — then Start. There are no reset flags and no auto-requeue on version bump. (The CLI cold-build still uses the legacy NOT-EXISTS predicate path when `job["id"] is None` — see Two run surfaces.)

**Versioning:** every stage/evaluator carries a version constant, stamped onto each `job_items` row as `code_version` for provenance and as an add-tasks filter ("processed before v4"). Bumping a constant no longer auto-requeues anything — re-processing is an explicit operator run.

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
| Combine (dedup provisional nodes) | `COMBINE_VERSION` | [pipeline/stages/combine.py](ingredients/src/ingredients/pipeline/stages/combine.py) |
| Connect (place + promote nodes) | `CONNECT_VERSION` | [pipeline/stages/connect.py](ingredients/src/ingredients/pipeline/stages/connect.py) |
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

Schema.org Recipe JSON-LD extraction is no longer a scraper CLI — the Zone-2 `extract-recipe` stage owns page → `recipes` now (see below).

## Spirits Taxonomy

DAG of canonical ingredients. **Read [docs/spirits-taxonomy.md](docs/spirits-taxonomy.md) before adding nodes** — the lean stance (taxonomy for definitional categories + hard constraints; vector layer for soft similarity) is load-bearing. Don't add sensory, stylistic, or colloquial nodes.

Three non-obvious rules worth surfacing here (full treatment in the doc):

- **Slugs are kebab-case** — `taxonomy_nodes.slug` carries a DB CHECK forbidding underscores (`slug !~ '_'`). `map-ingredient` mints provisional nodes with a deterministic kebab slug from the ingredient name; `combine-nodes`/`connect-nodes` then merge + place them. Display names and taxonomy aliases are free-text (spaces, capitalization, accents fine); only slugs are constrained.
- **Brand and product names always get their own nodes** (`node_kind='brand'` / `'expression'`), never aliases. Aliases are reserved for capitalization/punctuation/language variants of one canonical name, plus the brand-as-substance carve-out (`'aromatic bitters'` → `angostura-bitters`).
- **`is_cluster_node` cuts the DAG asymmetrically.** A type node is the cluster identity in some branches (`orange-bitters`, `bourbon`); an expression node is the cluster identity in others (`angostura-bitters`, `peychauds-bitters` — brand-as-substance). The only invariant: no `is_cluster_node` node has an `is_cluster_node` ancestor.

Taxonomy nodes are managed on the live service via the curation UI (`/ops → Taxonomy`, `/api/ops/taxonomy/*`); they are not maintained as local seed files. To work against current reference data locally, copy a snapshot of the live database (see [docs/backups.md](docs/backups.md)).

## Content pipeline (Zone 2)

`ingredients/` turns crawled pages into the relational recipe. Each stage is a `stage_fn(job, conn, providers)` registered into `worker.dispatch.STAGE_FNS`; the run order is **extract-recipe → parse-ingredients → map-ingredient → combine-nodes → connect-nodes → convert-steps → cluster-recipes → export-recipegf**. A stage processes the run's `pending` `job_items` over a provider chain (deterministic tier first, an LLM tier for the residue), writes its content rows, and finalizes each item (`applied` / `flagged` / `failed`).

**Two run surfaces:**

- **CLI — one stage, or the whole cold build, deterministically.** It passes no providers, so LLM tiers are skipped and anything only an LLM could resolve parks as `pending`. Good for a local cold build off a staging restore.

  ```bash
  cd ingredients && uv run python -m ingredients.cli <stage>            # extract-recipe|parse-ingredients|map-ingredient|combine-nodes|connect-nodes|convert-steps|cluster-recipes|export-recipegf
  cd ingredients && uv run python -m ingredients.cli map-ingredient --site punch --limit 200
  cd ingredients && uv run python -m ingredients.cli cold-build         # every stage in order
  ```

  Every subcommand takes `--site` / `--limit`. To re-run a stage, delete its `stage_runs` rows or bump the version constant. (Verified against [cli.py](ingredients/src/ingredients/cli.py) + [coldbuild.py](ingredients/src/ingredients/pipeline/coldbuild.py): the subcommands are exactly `extract-recipe`, `parse-ingredients`, `map-ingredient`, `combine-nodes`, `connect-nodes`, `convert-steps`, `cluster-recipes`, `export-recipegf`, `cold-build` — no `--review` / `--reset` / `--dry-run` / provider flags.)

- **Executor — a thread inside the API process (`spiritolo.executor.Executor` over `ingredients.worker.runner`).** Woken by **Start**, it claims a `queued` job (`BEGIN IMMEDIATE` in SQLite; nothing else competes), dispatches it to its stage_fn with the run's own `ProviderChain` (a single LLM tier + a per-job cost cap), then finalizes. At boot `requeue_interrupted` puts a job left `running` by a crash back to `queued`. **The run picks the model:** its `llm_provider` / `llm_model` (chosen at run assembly via `set_run_llm`, the same fields the cost gate reads) select exactly one LLM provider, built per job from the env's API keys — a run that names no provider (or whose key is absent) runs deterministic-only. The deterministic alias/lexical tiers live in the stage code itself, and `pack_size` (items per LLM call) is a per-stage code constant (`STAGE_PACK_SIZE` in `worker/providers.py`). There is no external provider-chain config file.

  Runs are assembled in the `/ops` console over `/api/ops/runs…` (`ingredients.runs`: `create_run` (draft) → `add_run_items`/`add_run_items_by_filter` (load `pending` members) → `start_run` (draft → `queued`, wakes the executor)). The executor then processes the job's `pending` `job_items`, writing content immediately as it goes (no separate apply step). `/api/ops/executor` and `/api/health` report its liveness.

**The stages:**

- **extract-recipe** — reads a classified page's cached HTML from the object store, finds the Schema.org Recipe JSON-LD, and UPSERTs a `recipes` row (raw `source` verbatim + derived title/author/image). No Recipe JSON-LD → the LLM tier synthesizes a recipe source from the page, else it abstains.
- **parse-ingredients** — parses each `recipes.source` `recipeIngredient` string with strict abstain discipline into `recipe_ingredients` (RecipeGF shape: name + amount/amount_max/unit + `string[]` modifiers). `PARSER_VERSION` in [parser.py](ingredients/src/ingredients/parser.py); bump on any rule or unit-table change.
- **map-ingredient** — resolves each `recipe_ingredients.name` to an existing **live** taxonomy node in the **shared** `ingredient_resolutions` (name-keyed — resolved once for every recipe that uses it): alias → lexical → LLM-attach → abstain. It no longer proposes or auto-creates placed nodes inline. On abstain it **mechanically mints** a `provisional` node instead — a deterministic kebab slug, `node_kind=NULL`, no parent — with a `map-mint` `taxonomy_provenance` row and a `provisional` resolution; the mint needs no LLM, so it works in the CLI cold build. Harmonizing those provisional stubs into the real taxonomy is the job of the next two stages.
- **combine-nodes** (entity: `taxonomy_node`) — dedups provisional nodes. Deterministic candidate generation (pg_trgm similarity + token overlap) feeds an LLM tier that merges true synonyms via `combine_merge` — the blessed survivor prefers an existing **live** node, and the merge repoints resolutions/edges/aliases then deletes the absorbed node. Uncertain cases open a `combine-nodes` `human_reviews` row. Can run broadly over the live set, not just the fresh provisional residue. `COMBINE_VERSION` in [pipeline/stages/combine.py](ingredients/src/ingredients/pipeline/stages/combine.py).
- **connect-nodes** (entity: `taxonomy_node`) — places and promotes a provisional node. An LLM tier assigns `node_kind` (brand/expression/`NULL`), parent edges, and `is_cluster_node` via `connect_place` (enforcing the antichain invariant), then flips `status` `provisional → live`. Unknown-parent / antichain-violation / uncertain cases open a `connect-nodes` `human_reviews` row and leave the node provisional. Also runnable broadly over the live set. `CONNECT_VERSION` in [pipeline/stages/connect.py](ingredients/src/ingredients/pipeline/stages/connect.py).
- **convert-steps** — deterministic technique keyword scan → RecipeGF verb-frame `recipe_steps`. Anything uncertain (no technique, muddle, untranslatable unit, unresolved ingredient, or an ingredient resolved to a still-`provisional` node) records a `pending` / `proposes_new` outcome and writes no steps until the node is promoted.
- **cluster-recipes** — normalizes the cocktail name (`NORMALIZER_VERSION`), role-tags ingredients and rolls them up to the curated antichain, then writes `recipe_clusters` (+ `recipes.cluster_id`/`variant_key`). Cluster identity is `hash(canonical_name, role-tagged rolled-up ingredient set)`; two recipes share a variant iff they also share amounts and brand call-outs, so identical recipes from multiple sources collapse to one variant with `source_count > 1`. Like convert, it holds `pending` (no cluster) for a recipe with any provisional-node ingredient.
- **export-recipegf** — freezes the on-demand bundle into `recipe_exports`, keyed by recipe + `CONVERTER_VERSION`; also skips any recipe still carrying a provisional-node ingredient.

**Generate-on-demand bundles.** Spiritolo emits validated **RecipeGF pin-2 bundles** — one per recipe — so a consumer (Barbot) imports self-contained docs with no runtime dependency on Spiritolo. The bundle is `{recipe, verbs:[<spiritolo/ defs used>], meta:{slug, source, imported_at}}`, generated from `recipes` + `recipe_ingredients` + `recipe_steps` by [recipegf/generate.py](ingredients/src/ingredients/recipegf/generate.py) (`generate_bundle`) — not a stored blob. Depends on the pinned `recipegf` v0.4.0 library; **read [docs/recipegf-export.md](docs/recipegf-export.md)**. Non-obvious invariants:

- **Recipe ids are reverse-DNS `com.spiritolo/<slug>:v1`.** A bare `spiritolo/<slug>` id is rejected — the `spiritolo` namespace is for VERBS, not recipe authorities. `meta.slug` equals `parse_recipe_id(id).slug`.
- **Bundles are self-contained:** each carries the `spiritolo/` extension verb-defs its steps reference, so a consumer validates against `core ∪ spiritolo/` with no external lookup. Extension verbs are self-describing YAML in [recipegf/verbs/](ingredients/src/ingredients/recipegf/verbs) (`spiritolo-blend.yaml`, `spiritolo-top.yaml`), loaded via RecipeGF's overlay API.

**Eval sets** run through pytest (`cd ingredients && uv run --extra dev pytest`), not a CLI flag: [eval_set.py](ingredients/src/ingredients/eval_set.py) (parser), [mapping/eval_set.py](ingredients/src/ingredients/mapping/eval_set.py) + [mapping/eval_fixture.py](ingredients/src/ingredients/mapping/eval_fixture.py), [dedup/eval_set.py](ingredients/src/ingredients/dedup/eval_set.py) + [dedup/eval_fixture.py](ingredients/src/ingredients/dedup/eval_fixture.py), and [recipegf/eval_set.py](ingredients/src/ingredients/recipegf/eval_set.py). Fixtures are frozen so eval results don't drift with seed changes.

**Providers + writes.** The LLM tiers need credentials per chosen provider: `ANTHROPIC_API_KEY` (claude), `OLLAMA_BASE_URL` (defaults `http://localhost:11434`, ollama), `OPENAI_API_KEY` (openai), `DEEPSEEK_API_KEY`. In the container they arrive through `op run` from 1Password (`secrets.env`), never as Railway variables. Writes go to the SQLite file `SPIRITOLO_DB` points at — including the provisional taxonomy nodes map-ingredient mints and the merges/promotions the combine-nodes / connect-nodes LLM tiers apply.

## Data flow

**Pipeline data lives on the service's volume** — `/data/spiritolo.db` on the `spiritolo` Railway service is the source of truth for `recipes`, `recipe_ingredients`, `recipe_steps`, `ingredient_resolutions`, `recipe_clusters`, taxonomy growth, runs, the audit log. Pipeline runs execute in that process; the curation UI and `/api/ops/query` read and write the same file. Schema changes ship as new `common/db/migrations/*.sql` files and apply when the new image boots.

**Getting data out / in:** Litestream replicates continuously to a bucket (restore: [docs/backups.md](docs/backups.md)); `scripts/snapshot-sqlite.sh` takes a `VACUUM INTO` copy; `/ops → Import` (`POST /api/ops/import-db`) replaces the live file with an uploaded one after verifying it (digest, `integrity_check`, migration ledger) — in the container that exits the process so the entrypoint swaps the file before Litestream starts.

**One-time data migration (Supabase → SQLite)** — done 2026-10-24: the (since removed) *Backup staging database* Action dumped the legacy Postgres, `scripts/pg_to_sqlite` converts the dump offline, `/ops → Import` loads it: [docs/migration.md](docs/migration.md).

## Hosting

One Railway service in project **spiritolo-neo** (environment `prod`, service `spiritolo`, volume at `/data`, domain `https://spiritolo.com` — apex on Cloudflare DNS, `www` redirected to it there; moved off `spiritolo-staging.up.railway.app` 2026-10-24). It is the only hosted environment — Ruddick's data runs are one-shot and belong in the real data, so there is no standing staging; fork one from a Litestream restore if a change ever needs it. Full picture: [docs/deployment.md](docs/deployment.md); zero-to-deployed steps: [docs/devops-runbook.md](docs/devops-runbook.md).

**Branches:** `main` is the integration trunk; PRs from `claude/<topic>-<id>` branches land there. The Railway service deploys from the branch set in its Settings → Source (a UI setting; the API refuses it to a project token). That is **`prod`**, a promotion branch (the old `staging`, renamed): `main` is Ruddick's dev branch and never deploys on its own; a release is a PR `main → prod`, merged with a **merge commit, never squash** (a squash diverges the trees and breaks the next promotion). During the Supabase → Railway changeover the service deployed from the work branch `claude/project-thread-0e8m4j`. Vercel is gone.

**Everything is declared in the repo:** `railway.json` (DOCKERFILE builder, `/api/health` check, `ON_FAILURE` restarts, one replica), `Dockerfile` (node build of `web/` → `python:3.11-slim` runtime with `uv sync --frozen --package spiritolo-app`, plus the litestream / `op` / tailscale binaries), `scripts/entrypoint.sh` (staged-import swap → `op run` → `litestream restore -if-replica-exists` → `litestream replicate -exec uvicorn`), `litestream.yml`, `secrets.env`.

**Secrets:** never literal Railway variables. `secrets.env` holds `op://spiritolo-prod/<ENV_NAME>/password` references (session secret, LLM keys, Tailscale key); the service's only sealed variable is `OP_SERVICE_ACCOUNT_TOKEN`. Bucket credentials are **Railway reference variables** from the attached buckets, not vault items: each set is named for its purpose — `LITESTREAM_*` (`BUCKET`, `ENDPOINT`, `REGION`, `ACCESS_KEY_ID`, `SECRET_ACCESS_KEY`) → `${{spiritolo-litestream.*}}` and `CORPUS_*` (same suffixes) → `${{spiritolo-corpus.*}}`. Don't use Railway's "Add to service" presets, whose generic `BUCKET_*` / `AWS_*` names would collide. Plain variables: `PUBLIC_ORIGIN`, `SPIRITOLO_DB`, `STATIC_DIR`, `RUN_EXECUTOR`, `LOG_LEVEL`. When an AI session drives Railway through the GraphQL API with a project token: never print variable values, never call the bucket-credential mutations, and ask before anything destructive (deleting a service/volume/bucket, wiping the database).

**Auth:** passkeys only (WebAuthn via `py_webauthn` + `@simplewebauthn/browser`), signed HttpOnly session cookie. First-time setup is open while `operators` is empty; afterwards a passkey is added by its signed-in owner or via a **registration link** (`/ops → Operators` → `operator_invites`: single-use, 7-day token, redeemed at `/login?invite=<token>` with no session). Passkeys are bound to `PUBLIC_ORIGIN`'s hostname, so mint a link *before* changing the origin or every operator is locked out. `operators.is_admin` gates `/ops`.

**CI (PR → main):** `python-ci.yml` (common, ingredients, app, scripts suites; SQLite, no services), `web-ci.yml` (Vitest), `workflows-ci.yml` (shape tests over the deploy artifacts).

**RecipeGF** is a private git dependency (`mrjogo/RecipeGF@v0.4.0`): the image build and `python-ci.yml` take a `RECIPEGF_TOKEN` (build arg / repo secret) unless the repo is public. Cloud AI sessions cannot clone it; they work against a local stub and must restore the real `recipegf` blocks in `uv.lock` before committing.

## Web UI

The React app calls the FastAPI API on the same origin (`web/src/api.ts`: `api()`, `queryTable()` / `queryOne()` / `queryAll()` over the allowlisted `POST /api/ops/query`). No Supabase client, no keys in the browser. Public pages read `/api/recipes…`; `/ops` and the taxonomy editor use `/api/ops/*` behind an admin passkey session; `/login` does passkey sign-in and first-time setup.

```bash
cd web && npm install
cp .env.local.example .env.local   # VITE_API_PROXY (default http://localhost:8000)
npm run dev                        # localhost:5173, proxies /api to the uv-run API process
npm test                           # Vitest + @testing-library/react
```

Main suite: [normalizeRecipe.test.ts](web/src/normalizeRecipe.test.ts) covers messy Schema.org Recipe variants. Tests mock `'../api'` (`vi.mock` with `importOriginal` spread) rather than a network layer. Lint has ~17 pre-existing errors in untouched files; CI runs only `npm test`.

**`package-lock.json` — regenerate under the CI Node version before committing it.** CI (`.github/workflows/web-ci.yml`) pins **Node 20 / npm 10** and runs `npm ci`, which *fails the whole web job* if the lock was written by a different npm major (Node 22 ships npm 11, whose lock format npm 10 rejects — surfaces as `npm error … Missing: <pkg> from lock file`). So whenever a change touches `web/package-lock.json` (a dependency add/bump, or a stray `npm install` rewriting it), before check-in regenerate + verify it under Node 20:

```bash
nvm use 20                      # match CI (nvm install 20 first if needed)
cd web && rm -f package-lock.json && npm install && npm ci   # npm ci must pass clean
```

If you didn't intend to change dependencies, `git checkout -- web/package-lock.json` to drop an incidental rewrite rather than committing it.

## UI mockups (design phase)

The preferred way to explore UI designs here is **static HTML mockups → screenshot → inspect the image**, iterating with the user before any real code:

1. Build the mockup(s) as plain HTML/CSS (throwaway), render each to a PNG with headless chromium (Playwright: chromium is cached under `~/.cache/ms-playwright/…`; import `playwright` and pass `executablePath`), at both desktop and mobile widths.
2. **`Read` the PNGs** — the user reviews the rendered images inline and reacts; iterate on the HTML and re-screenshot. Don't write a markdown gallery unless asked; the Read-the-image flow is the review surface.
3. Keep all of it in `.mockups/` (gitignored) — never commit mockup HTML/PNGs.

**Caveat — images only render over the app's remote-control surface.** Inline image viewing (both you reading a PNG and the user seeing it) works in the desktop/web app when the user is driving via **remote-control**, but **not from the plain CLI**, which can't display images to the model. You generally *can't tell* which surface the user is on, so when you set out to produce screenshots for review, say so up front — if the user is on the CLI they'll tell you to switch, or ask for an alternative (e.g. a self-contained HTML file they open themselves).

## Walkthroughs (showboat)

`uvx showboat` builds an *executable* markdown doc — commentary (`note`), captured code blocks (`exec`), and screenshots (`image`) — that doubles as reproducible proof: `showboat verify` re-runs every code block and diffs the output. Use it to demo UI/pipeline work. Paths differ per machine, so keep the throwaway bits (Playwright project, screenshots, the doc) in the session scratchpad, not the repo.

Recipe for a UI walkthrough:

1. **Fresh DB + fake data.** Point `SPIRITOLO_DB` at a scratch file, start `python -m spiritolo` (migrations apply on open), then seed *fake* data straight into the tables the views read — plain `INSERT`s via `sqlite3`, no snapshot needed for a demo. For `/ops`: `recipes` / `recipe_ingredients` / `recipe_steps` / `jobs` (runs) + `job_items` (per-entity, with varied `state` so the add-tasks facets show something) / `recipe_clusters` / `recipe_exports` / `human_reviews`; audit-log rows generate themselves via the table triggers.
2. **Serve.** `cd web && npm run dev` (`:5173`, proxying `/api`).
3. **Headless admin auth (no passkey ceremony).** Insert an `operators` row, mint a session cookie with `spiritolo.auth.Sessions(settings).token(operator_id)` (same `SESSION_SECRET` as the running process) and set it as `spiritolo_session` on the Playwright context. Then `page.goto` each route + `screenshot({ fullPage: true })`. Install Playwright + chromium in the scratchpad.
4. **Assemble + prove.** `showboat init/note/exec/image` (an `exec` `sqlite3` row-count block makes good re-runnable proof), then `showboat verify`. Optionally render to a self-contained HTML artifact (inline the PNGs as `data:` URIs) for viewing.
