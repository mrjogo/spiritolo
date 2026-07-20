# Taxonomy harmonization + stage rename + apply teardown — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the no-op apply/hold feature, rename the six pipeline stages to canonical `<verb>-<object>` names, and split taxonomy node creation into a naive-mint (in `map-ingredient`) + `combine-nodes` + `connect-nodes` harmonization pipeline gated by a `taxonomy_nodes.status` flag.

**Architecture:** Zone-2 stages are `stage_fn(job, conn, providers)` registered in `worker.dispatch.STAGE_FNS`; content writes are immediate to live tables; the audit log captures before/after per row. This plan rips out `apply_mode`/`pending_apply`/`apply_run_items`, moves all taxonomy node creation out of `map-ingredient`'s inline LLM path into a mint-then-harmonize pipeline, and adds a provisional/live status gate so downstream stages ignore un-harmonized nodes.

**Tech Stack:** Python 3.11 (uv, psycopg, pytest), Supabase/Postgres (SQL migrations), Vite/React/TS (Vitest). `TEST_DB_URL` drives DB-integration tests.

## Global Constraints

- Migrations are immutable history — never edit an existing `supabase/migrations/*.sql`; add a new forward migration.
- Slugs are kebab-case; `taxonomy_nodes.slug` carries a CHECK forbidding `_`.
- `is_cluster_node` invariant: no `is_cluster_node` node has an `is_cluster_node` ancestor.
- Canonical stage names everywhere in UI + docs: `extract-recipe`, `parse-ingredients`, `map-ingredient`, `convert-steps`, `cluster-recipes`, `export-recipegf`, `combine-nodes`, `connect-nodes`.
- Reuse existing taxonomy RPCs (`create_taxonomy_node`, `update_taxonomy_node`) — do not reinvent node creation.
- Every phase ends with a green suite: `cd ingredients && uv run --extra dev pytest`, `cd scraper && uv run pytest`, `cd web && npm test`.
- Commit frequently; conventional-ish messages; end each commit body with the Co-Authored-By trailer.

---

## Phase 1 — Apply teardown + stage rename

**Deliverable:** the apply/hold feature is gone end-to-end; the six existing stages carry canonical names in code, DB, UI, and docs; suite green. No behavior change beyond removing the no-op apply gate.

### File map (Phase 1)

- SQL: **create** `supabase/migrations/20260719120000_drop_apply_and_rename_stages.sql` — drop `jobs.apply_mode`; rewrite `job_items.state` CHECK to remove `pending_apply`; `drop function apply_run_items`; recreate `create_run` without the `apply_mode` arg; UPDATE stored `stage` strings (`jobs`, `job_items`, `human_reviews`, `stage_live_version`, `review_floors`) old→new.
- Python: `ingredients/src/ingredients/pipeline/stages/base.py` (`item_state` drop hold branch; remove `apply_mode` kwargs); each stage file `extract.py|parse.py|map.py|convert.py|cluster.py|export.py` (drop `apply_mode = job.get(...)`, rename `STAGE`); `worker/dispatch.py` registry keys; `worker/loop.py`/`cli.py`/`coldbuild.py` stage-name literals + CLI subcommands; version-constant call sites unaffected.
- Web: `web/src/ui/pipelineStages.ts` (canonical list — the source of truth); `web/src/pages/ops/runs/RunDetail.tsx`, `RunsList.tsx`, `web/src/ui/runs/{useRun.ts,useRunItems.ts,tasksTableModel.ts,badges.tsx}` (remove apply-mode toggle, "apply held items", `pending_apply` badge); `web/src/ui/opsLinks.tsx` + any stage-string consumers.
- Docs: `CLAUDE.md`, `docs/pipeline.md`, `docs/deployment.md` — scrub apply/hold language, use canonical names.

### Task 1.1 — Drop-apply + rename forward migration

**Files:**
- Create: `supabase/migrations/20260719120000_drop_apply_and_rename_stages.sql`
- Test: `ingredients/tests/test_migration_drop_apply.py`

**Interfaces:**
- Produces: `jobs` has no `apply_mode`; `job_items.state` CHECK = `('pending','running','applied','flagged','failed')`; no `apply_run_items` function; stage strings stored as canonical names.

- [ ] Step 1: Write failing test — after migrations apply to `TEST_DB_URL`, assert (a) `information_schema.columns` has no `jobs.apply_mode`, (b) `apply_run_items` absent from `pg_proc`, (c) `pending_apply` not in the `job_items_state_check` clause, (d) a seeded `job_items` row with `stage='map'` is rewritten to `'map-ingredient'`. Use the `ingredients` conftest DB fixture.
- [ ] Step 2: Run `cd ingredients && uv run --extra dev pytest tests/test_migration_drop_apply.py -v` → FAIL.
- [ ] Step 3: Write the migration: `alter table jobs drop column apply_mode;`; `alter table job_items drop constraint job_items_state_check, add constraint job_items_state_check check (state in ('pending','running','applied','flagged','failed'));` (verify exact constraint name from `20260726090000_explicit_runs.sql`); `drop function if exists public.apply_run_items(bigint, bigint[]);`; `create or replace function public.create_run(stage text) …` (drop the apply_mode arg/insert); UPDATE each table's `stage` column via a `case` old→new.
- [ ] Step 4: Apply (`supabase migration up --include-all` on host, or let conftest apply) and rerun the test → PASS.
- [ ] Step 5: Commit.

### Task 1.2 — Python: collapse `item_state`, drop `apply_mode`, rename `STAGE`

**Files:**
- Modify: `ingredients/src/ingredients/pipeline/stages/base.py`, `extract.py`, `parse.py`, `map.py`, `convert.py`, `cluster.py`, `export.py`, `worker/dispatch.py`
- Test: `ingredients/tests/test_stage_base.py` (or existing base test)

**Interfaces:**
- Produces: `item_state(outcome) -> str` (no `apply_mode` param): `resolved→applied`, `failed→failed`, else `flagged`. `STAGE` constants = canonical names. `STAGE_FNS` keyed by canonical names.

- [ ] Step 1: Write failing test asserting `item_state('resolved') == 'applied'` and `item_state('pending') == 'flagged'` and that `STAGE_FNS` contains `'map-ingredient'` not `'map'`.
- [ ] Step 2: Run pytest → FAIL.
- [ ] Step 3: Edit `base.py` `item_state` to drop the `apply_mode` param + hold branch; remove `apply_mode` kwargs from `record`/`record_many`; in each stage file delete `apply_mode = job.get("apply_mode") or "auto"` and pass-throughs, set `STAGE` to the canonical name; update `dispatch.py` registration.
- [ ] Step 4: Run the full `ingredients` suite → PASS (update any test asserting old names/apply-mode).
- [ ] Step 5: Commit.

### Task 1.3 — CLI + coldbuild stage names

**Files:**
- Modify: `ingredients/src/ingredients/cli.py`, `ingredients/src/ingredients/pipeline/coldbuild.py`
- Test: `ingredients/tests/test_cli.py`

- [ ] Step 1: Failing test: `cli` subcommands are the canonical names (`map-ingredient`, …) and `cold-build` runs them in order.
- [ ] Step 2: pytest → FAIL.
- [ ] Step 3: Rename subcommands + coldbuild order list to canonical names.
- [ ] Step 4: pytest → PASS.
- [ ] Step 5: Commit.

### Task 1.4 — Web: remove apply-mode UI + canonical stage list

**Files:**
- Modify: `web/src/ui/pipelineStages.ts`, `web/src/pages/ops/runs/RunDetail.tsx`, `RunsList.tsx`, `web/src/ui/runs/{useRun.ts,useRunItems.ts,tasksTableModel.ts,badges.tsx}`, `web/src/ui/opsLinks.tsx`
- Test: existing `web/src/ui/runs/TasksTable.test.tsx`, `web/src/pages/ops/runs/AddTasks.test.tsx`, `web/src/ui/FilterBar.test.tsx`

- [ ] Step 1: Update `pipelineStages.ts` to the canonical list; update failing tests to expect canonical names + no `pending_apply`/apply-mode.
- [ ] Step 2: `cd web && npm test` → FAIL (drives the change).
- [ ] Step 3: Remove the apply-mode create toggle, the apply-held action, the `pending_apply` badge; replace stage-string literals with `pipelineStages` values.
- [ ] Step 4: `npm test` → PASS.
- [ ] Step 5: Commit.

### Task 1.5 — Docs sweep

**Files:** Modify `CLAUDE.md`, `docs/pipeline.md`, `docs/deployment.md`

- [ ] Step 1: Replace apply/hold/`apply_run_items`/`pending_apply` prose with immediate-application wording; rename stages to canonical names; note the audit log is the (unbuilt) rollback substrate.
- [ ] Step 2: `grep -rn "apply_mode\|pending_apply\|apply_run_items" docs CLAUDE.md` → only historical spec/plan files remain.
- [ ] Step 3: Commit.

---

## Phase 2 — Provisional-node model + downstream gate + map mint

**Deliverable:** `taxonomy_nodes.status` exists; `map-ingredient` mints provisional nodes on abstain (no more inline auto-create / form-proposal); `cluster-recipes`/`export-recipegf`/`recipes_public` ignore provisional nodes. Suite green.

### Tasks (detailed when Phase 1 lands)
- 2.1 Migration: `taxonomy_nodes.status text not null default 'live' check (status in ('live','provisional'))` + `status` index. Test: column + default + CHECK.
- 2.2 `map-ingredient` mint-on-abstain: deterministic kebab slug from normalized name, `insert … status='provisional', node_kind=NULL on conflict (slug) do nothing`, provisional resolution + provenance. Remove `propose_brand`/`propose_expression` auto-create + `propose_form` path from `mapping/llm_actions.py`. Tests: idempotent single provisional node; identical names collapse; no live-node matching.
- 2.3 Downstream gate: add `status='live'` predicates to `cluster-recipes` join (`cluster.py`), `export-recipegf` bundle generation, `recipes_public`/`taxonomy_public` taxonomy reads. Tests: a provisional-node ingredient excludes the recipe from cluster/export until promoted.

---

## Phase 3 — `combine-nodes` + `connect-nodes` stages

**Deliverable:** two new stage_fns + version constants + registry entries; `taxonomy_node` entity kind; resolution/edge repointing on merge; promotion to live on connect; eval fixtures. Suite green.

### Tasks (detailed when Phase 2 lands)
- 3.1 `taxonomy_node` entity kind in the runs/`job_items` model + work-queue helpers (`base.py` node queue).
- 3.2 `combine-nodes` stage: candidate set (provisional default; broad = live set); LLM/embedding same-substance judgment; blessed survivor prefers live; repoint `ingredient_resolutions.taxonomy_slug` + `taxonomy_edges`; tombstone absorbed provisional; uncertain → `human_reviews` combine machine_proposal. `COMBINE_VERSION`. Eval fixture: synonyms merge; live wins.
- 3.3 `connect-nodes` stage: assign `node_kind` + parent edges + `is_cluster_node` (antichain invariant); promote `provisional→live`; uncertain → `human_reviews` connect machine_proposal. `CONNECT_VERSION`. Eval fixture: node placed + promoted; recipe eligibility flips.
- 3.4 Register both in `STAGE_FNS`; add to `cold-build` order after `map-ingredient`.

---

## Phase 4 — `/ops` filter + facets + new fields

**Deliverable:** add-tasks filter facets for the new stages + a "partially through the pipeline" filter; `taxonomy_nodes.status` and the `taxonomy_node` entity kind surfaced. Suite green.

### Tasks (detailed when Phase 3 lands)
- 4.1 Read surfaces / views: extend the derived per-stage status index + add-tasks facet queries to the new stages and `taxonomy_node` entities; expose `status`.
- 4.2 Web: `pipelineStages.ts` already canonical (Phase 1); add facet UI for new stages + a partial-pipeline filter; expose node `status`. Tests in `AddTasks.test.tsx`/`FilterBar.test.tsx`.

---

## Phase 5 — Review surfaces for combine/connect

**Deliverable:** `ReviewCard` renders `combine-nodes` and `connect-nodes` bodies; approving wires to `create_taxonomy_node`/`update_taxonomy_node` + promotion. Suite green.

### Tasks (detailed when Phase 4 lands)
- 5.1 `web/src/components/reviews/bodies/CombineReviewBody.tsx` — show merge (absorbed → blessed survivor); Resolve confirms the merge.
- 5.2 `web/src/components/reviews/bodies/ConnectReviewBody.tsx` — show/edit `node_kind` + parent + `is_cluster_node`; Resolve calls the taxonomy RPCs + flips status live.
- 5.3 Register both in `ReviewCard` `BODIES`; tests.

---

## Self-review notes

- **Spec coverage:** apply teardown → Phase 1; rename → Phase 1; provisional model + gate → Phase 2; map mint → Phase 2; combine/connect → Phase 3; broad-run + prefer-existing → Phase 3 (3.2/3.3); `/ops` filter + fields → Phase 4; review surfaces → Phase 5. All spec sections mapped.
- **Immutable migrations honored:** all schema changes are new forward migrations.
- **No rollback build** (non-goal) — audit log left intact.
- Phases 2–5 are intentionally task-outlined, not code-complete: they'll be expanded to full TDD granularity (with real code read from the codebase) at the start of each phase, per the sequential-plan approach, to avoid speculative code drift across a 40+ file refactor.
