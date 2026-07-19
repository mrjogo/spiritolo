# Explicit Runs Queue Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace version-derived stage queues with operator-assembled runs — create a run, load any entities via rich filtering, start it — delivered in one PR.

**Architecture:** A run is a `jobs` row (`draft → queued → running → done`) that owns explicit `job_items` (per-entity membership + outcome, renamed from `stage_runs`). The worker processes a job's `pending` `job_items` instead of re-deriving a NOT-EXISTS predicate. `human_reviews` is `stage_reviews` renamed. New `/ops` UI: runs list, run detail (LLM selector + start-confirm + tri-mode tasks table), add-tasks (JIRA-style filtering).

**Tech Stack:** Postgres (Supabase migrations), Python 3.11 (uv, psycopg, pytest) worker/pipeline, Vite + React + TS + Vitest web.

## Global Constraints

- New migration timestamps must sort **after `20260725090000`** — use `20260726090000`+ (unbroken 14-digit `YYYYMMDDHHMMSS_snake.sql`).
- `taxonomy_proposals` **no longer exists** (dropped `20260725090000`); its rows are already `stage_reviews` with `origin='machine_proposal'`. Do NOT reference it.
- `pages` fetched-content column is **`corpus_key`** (not `r2_key`).
- `stage_runs` unique key is already `(entity_type, entity_id, stage, version)` (append-versioned).
- RPCs: `security definer`, `set search_path = ''`, `is_admin()` gate raising `42501`, `revoke all from public; grant execute to authenticated`.
- RLS on new tables: `enable row level security` + one `_admin_read` select policy `using (is_admin())` + `grant select to authenticated`.
- DB tests run against `TEST_DB_URL`; the `ingredients` conftest auto-applies new migrations. Never point tests at `SUPABASE_DB_URL`.
- Web reads via publishable key; `/ops` is admin-gated (`RequireAdmin`).
- Frequent commits; TDD; DRY; YAGNI.

## Naming contract (used across tasks)

Tables: `jobs` (run), `job_items` (was `stage_runs`), `human_reviews` (was `stage_reviews`), `audit.log` (+`job_id`).

`jobs` new/changed columns: `state` gains `'draft'` and `'done'` (keep existing enum values; `'succeeded'` stays a synonym the app maps to "done", `'awaiting_approval'` retained in enum but unused), `llm_provider text`, `llm_model text`, `apply_mode text not null default 'auto' check (apply_mode in ('auto','hold'))`.

`job_items` (renamed from `stage_runs`) new columns: `state text not null default 'pending' check (state in ('pending','running','applied','pending_apply','flagged','failed'))`, `outcome_payload jsonb`. `job_id bigint` becomes the membership FK (already exists, no-FK today → add FK). Keep `outcome`/`version`/`method`/`model_id`/`cost_cents`; `version` is renamed in meaning to `code_version` (add alias column, keep `version` populated for back-compat within this PR, drop `version` at the end).

RPC surface (Task 3):
- `create_run(p_stage text, p_apply_mode text default 'auto') returns bigint`
- `add_run_items(p_job_id bigint, p_entity_type text, p_entity_ids bigint[]) returns int`
- `add_run_items_by_filter(p_job_id bigint, p_filter jsonb) returns int`
- `remove_run_items(p_job_id bigint, p_item_ids bigint[]) returns int`
- `set_run_llm(p_job_id bigint, p_provider text, p_model text) returns void`
- `start_run(p_job_id bigint, p_max_cost_cents int default null) returns void`  (draft→queued; sets estimate)
- `apply_run_items(p_job_id bigint, p_item_ids bigint[] default null) returns int` (pending_apply→applied)
- `eligible_pool(p_stage text, p_filter jsonb, p_sort text, p_limit int, p_offset int) returns table(...)` + `eligible_pool_facets(p_stage text, p_filter jsonb) returns jsonb`
- `run_items(p_job_id bigint, p_filter jsonb, p_sort text, p_limit int, p_offset int) returns table(...)` + `run_items_facets`

`p_filter` jsonb shape (JIRA filtering): `{"status":["flagged","failed"],"source":["diffordsguide"],"code_version_before":"v4","search":"neg"}` — arrays are OR within a key, keys AND together.

---

## WAVE 0 — foundation (blocks everything)

### Task 1: Schema migration — jobs/job_items/human_reviews + data migration

**Files:**
- Create: `supabase/migrations/20260726090000_explicit_runs.sql`
- Test: `ingredients/tests/test_explicit_runs_schema.py`

**Interfaces:**
- Produces: tables `jobs` (extended), `job_items` (renamed), `human_reviews` (renamed); `audit.log.job_id`; synthetic backfill jobs. Consumed by every later task.

- [ ] **Step 1: Write the failing test** — assert the new shape exists and data migrated.

```python
# ingredients/tests/test_explicit_runs_schema.py
import psycopg, pytest

@pytest.fixture()
def conn(test_db_url):
    with psycopg.connect(test_db_url, autocommit=True) as c:
        yield c

def test_job_items_has_state_and_membership(conn):
    cols = {r[0] for r in conn.execute(
        "select column_name from information_schema.columns where table_name='job_items'")}
    assert {"state", "outcome_payload", "code_version", "job_id"} <= cols

def test_human_reviews_replaces_stage_reviews(conn):
    assert conn.execute("select to_regclass('public.human_reviews')").fetchone()[0]
    assert conn.execute("select to_regclass('public.stage_reviews')").fetchone()[0] is None

def test_folded_tables_dropped(conn):
    for t in ("job_batches","review_floors","stage_live_version","stage_queue_versions","stage_config"):
        assert conn.execute("select to_regclass(%s)", (f"public.{t}",)).fetchone()[0] is None, t

def test_audit_log_has_job_id(conn):
    cols = {r[0] for r in conn.execute(
        "select column_name from information_schema.columns "
        "where table_schema='audit' and table_name='log'")}
    assert "job_id" in cols

def test_backfill_maps_outcome_to_state(conn):
    # a synthetic backfill job owns migrated items; resolved→applied, pending→flagged
    conn.execute("insert into recipes (id, source) values (9001, '{}'::jsonb) on conflict do nothing")
    jid = conn.execute(
        "insert into jobs (stage, state) values ('map','draft') returning id").fetchone()[0]
    conn.execute("insert into job_items (job_id, entity_type, entity_id, stage, code_version, "
                 "outcome, method, state) values (%s,'recipe',9001,'map','v1','resolved','deterministic','applied')",(jid,))
    row = conn.execute("select state from job_items where entity_id=9001").fetchone()
    assert row[0] == "applied"
```

- [ ] **Step 2: Run to verify it fails** — `cd ingredients && uv run --extra dev pytest tests/test_explicit_runs_schema.py -q` → FAIL (no `human_reviews`, etc.).

- [ ] **Step 3: Write the migration.** Structure (full SQL to author):
  1. `alter type job_state add value if not exists 'draft'; add value if not exists 'done';`
  2. `alter table jobs add column llm_provider text, add column llm_model text, add column apply_mode text not null default 'auto' check (apply_mode in ('auto','hold'));`
  3. `alter table jobs alter column state set default 'draft';`
  4. `alter table stage_runs rename to job_items;` then `add column state text ...`, `add column outcome_payload jsonb`, `rename column version to code_version` (update the unique index + `stage_runs_queue_idx`/`stage_runs_job_idx` names → `job_items_*`; recreate the unique index on `(entity_type,entity_id,stage,code_version)`).
  5. Backfill `job_items.state` from `outcome`: `update job_items set state = case outcome when 'resolved' then 'applied' when 'failed' then 'failed' else 'flagged' end;`
  6. Synthetic backfill jobs: `insert into jobs (stage, state, kind, created_by) select distinct stage, 'done', 'run', null from job_items where job_id is null;` then `update job_items i set job_id = j.id from jobs j where i.job_id is null and j.state='done' and j.stage=i.stage and j.created_by is null;` Add FK `job_items.job_id → jobs(id)`.
  7. `alter table stage_reviews rename to human_reviews;` — and rename every dependent function/view/index/trigger body: `apply_review`, `flag_review`, `resolve_review`, `needs_review`, `stage_reviews_one_open`→`human_reviews_one_open`, `stage_reviews_queue_idx`, `audit_stage_reviews`. (Recreate each `create or replace function ...` with `stage_reviews`→`human_reviews` in the body.)
  8. `alter table audit.log add column job_id bigint references public.jobs(id);`
  9. Drop folded objects: `drop view if exists stage_run_outcome_counts; drop function if exists stage_queue_counts; drop table if exists stage_queue_versions, stage_live_version, review_floors, stage_config, job_batches cascade;` (job_batches FK from jobs must be dropped first: `alter table jobs drop column batch_id;`).
  10. Update `stage_run_outcome_counts` replacement is dropped (facets now come from RPCs in Task 3) — remove, do not recreate.

- [ ] **Step 4: Apply + run tests** — `cd ingredients && uv run --extra dev pytest tests/test_explicit_runs_schema.py -q` → PASS. Also run the full `ingredients` suite; expect failures in tests that reference dropped tables (`test_stage_queue_counts.py`, `test_stage_config.py`, `test_stage_run_outcome_counts.py`) — mark those for deletion/rewrite in Task 4.

- [ ] **Step 5: Commit** — `git add supabase/migrations/20260726090000_explicit_runs.sql ingredients/tests/test_explicit_runs_schema.py && git commit -m "feat(db): explicit runs schema — job_items, human_reviews, backfill"`

### Task 2: Purge dropped-table references (Python + SQL callers)

**Files:**
- Modify: `ingredients/src/ingredients/pipeline/ledger.py` (`set_live_version` → remove; `_RECORD_RUN_SQL` table name `stage_runs`→`job_items`, `version`→`code_version`), `pipeline/stages/base.py` (`finalize_run` drops `set_live_version`).
- Delete: `ingredients/tests/test_stage_queue_counts.py`, `test_stage_config.py`, `test_stage_run_outcome_counts.py`.
- Modify: any `from ... import` of removed symbols.

**Interfaces:**
- Produces: a green `ingredients` suite (minus intentionally-deleted tests) on the new schema.

- [ ] **Step 1** Grep the blast radius: `rg -n 'stage_runs|stage_live_version|stage_queue|stage_config|stage_reviews|job_batches|set_live_version' ingredients/src` — fix each to the new names or remove.
- [ ] **Step 2** Update `_RECORD_RUN_SQL` to `insert into job_items (... code_version ...) on conflict (entity_type, entity_id, stage, code_version) do update ...`.
- [ ] **Step 3** Remove `set_live_version` + its call in `base.finalize_run`; `finalize_run` now only calls `reapply_overrides`.
- [ ] **Step 4** Delete the three obsolete test files.
- [ ] **Step 5** Run `cd ingredients && uv run --extra dev pytest -q` → all green.
- [ ] **Step 6** Commit `refactor: point pipeline at job_items, drop live-version/queue-count machinery`.

---

## WAVE 1 — worker + RPCs + presentational UI (parallel after Wave 0)

### Task 3: Run RPCs

**Files:**
- Create: `supabase/migrations/20260726093000_run_rpcs.sql`
- Test: `ingredients/tests/test_run_rpcs.py`

**Interfaces:** Produces the full RPC surface listed in the Naming contract. Consumed by all web hooks (Tasks 5–7).

- [ ] **Step 1: Failing test** covering the create→add→start→apply lifecycle and the filter shape:

```python
def test_run_lifecycle(conn):
    conn.execute("insert into recipes (id, source) values (1, '{}') , (2,'{}') on conflict do nothing")
    jid = conn.execute("select create_run('map','hold')").fetchone()[0]
    n = conn.execute("select add_run_items(%s,'recipe', array[1,2])", (jid,)).fetchone()[0]
    assert n == 2
    assert conn.execute("select count(*) from job_items where job_id=%s and state='pending'",(jid,)).fetchone()[0] == 2
    conn.execute("select set_run_llm(%s,'deepseek','deepseek-chat')",(jid,))
    conn.execute("select start_run(%s, 500)",(jid,))
    assert conn.execute("select state from jobs where id=%s",(jid,)).fetchone()[0] == 'queued'

def test_eligible_pool_filter_and_facets(conn):
    # AND across keys, OR within a key
    rows = conn.execute("select * from eligible_pool('map', %s, 'last_run_desc', 50, 0)",
                        ('{"status":["flagged","failed"],"source":["diffordsguide"]}',)).fetchall()
    facets = conn.execute("select eligible_pool_facets('map','{}')").fetchone()[0]
    assert 'flagged' in facets['status']
```

- [ ] **Step 2** Run → FAIL (functions absent).
- [ ] **Step 3** Author the RPCs. Key implementation notes:
  - `eligible_pool` builds on a `latest_job_item` CTE: `select distinct on (entity_type,entity_id) * from job_items where stage=p_stage order by entity_type,entity_id, id desc` → status = its `state`, or `'never run'` when the recipe has no item. Join `recipes` for `source`/title. Apply `p_filter` (status IN, source IN, `code_version < before`, `search ILIKE`), `p_sort` (`last_run_desc`/`title_asc`/…), `limit/offset`.
  - `add_run_items_by_filter` = `insert into job_items (job_id, entity_type, entity_id, stage, state) select p_job_id,'recipe',id,p_stage,'pending' from eligible_pool_ids(p_stage,p_filter)` (dedupe against existing pending in the job).
  - `start_run`: guard `state='draft'`; set `state='queued'`, `max_cost_cents`, `cost_estimate_cents` (estimate = count(pending)×per-item constant from a `_estimate_cents(stage, provider)` helper), `approved=true`.
  - `apply_run_items`: for `map`/`parse`/… reuse the existing `apply_review`-style materialization or, simpler, flip `state='applied'` and write `outcome_payload` into the live tables via the stage's writer (documented per stage; MVP: map/parse only, others no-op flip). Keep within YAGNI — only `hold` runs need it.
- [ ] **Step 4** Run → PASS.
- [ ] **Step 5** Commit `feat(db): run lifecycle + eligible-pool RPCs`.

### Task 4: Worker consumes explicit job_items

**Files:**
- Modify: `ingredients/src/ingredients/pipeline/stages/base.py` (`recipe_queue` → `run_item_ids(conn, *, job_id, stage) -> list[int]`; `record`/`record_many` set `state` + honor `apply_mode`), each `pipeline/stages/*.py` (call `run_item_ids` when `job["id"]` is set; keep `recipe_queue` fallback for CLI cold-build where `id is None`).
- Modify: `pipeline/coldbuild.py` (cold-build now creates a real draft job + items, or keeps the predicate path — see step).
- Test: `ingredients/tests/test_worker_explicit_items.py`

**Interfaces:** Consumes Task 1 schema + Task 3 `create_run`/`add_run_items`. Produces stage_fns that process a job's pending items and set their `state`.

- [ ] **Step 1: Failing test** — a job with two pending map items, run `map_stage_fn(job, conn, fake_chain)`, assert both items move to `applied` (auto) and only those two are touched:

```python
def test_stage_processes_only_its_job_items(conn):
    conn.execute("insert into recipes (id, source) values (1,'{}'),(2,'{}'),(3,'{}') on conflict do nothing")
    jid = conn.execute("select create_run('map','auto')").fetchone()[0]
    conn.execute("select add_run_items(%s,'recipe',array[1,2])",(jid,))
    conn.execute("select start_run(%s, null)",(jid,))
    job = conn.execute("select * from jobs where id=%s",(jid,)).fetchone()  # dict-row in real fixture
    counts = map_stage_fn(_job_from_row(job), conn, _FakeChain())
    states = dict(conn.execute("select entity_id, state from job_items where job_id=%s",(jid,)).fetchall())
    assert states == {1:'applied', 2:'applied'}   # recipe 3 untouched (not a member)
```

- [ ] **Step 2** Run → FAIL.
- [ ] **Step 3** Implement `run_item_ids` (`select entity_id from job_items where job_id=%s and stage=%s and state='pending'`); in each stage_fn, `ids = base.run_item_ids(conn, job_id=job["id"], stage=STAGE) if job.get("id") else base.recipe_queue(...)`. `base.record` sets `state` from the outcome (`resolved`→ `applied` when `apply_mode='auto'` else `pending_apply`; parked → `flagged`; error → `failed`) and updates the existing member row (not upsert-new). Read `apply_mode` from `job`.
- [ ] **Step 4** Run → PASS; run full worker suite.
- [ ] **Step 5** Commit `feat(worker): process explicit job_items, honor apply_mode`.

### Task 5: Web — runs list + run detail (presentational + wired)

**Files:**
- Create: `web/src/pages/ops/runs/RunsList.tsx`, `RunDetail.tsx`, `LlmTierSelect.tsx`, `StartConfirmModal.tsx`, `TasksTable.tsx`, `web/src/ui/runs/useRun.ts`, `useRunItems.ts`.
- Modify: `web/src/App.tsx` (routes `/ops/runs`, `/ops/runs/:id`), `web/src/pages/ops/OpsLayout.tsx` (nav).
- Test: `web/src/pages/ops/runs/RunDetail.test.tsx`, `TasksTable.test.tsx` (Vitest + RTL).

**Interfaces:** Consumes Task 3 RPCs via `supabase.rpc(...)`. Mirrors mockups `run-detail-*.png`. Produces the run detail surface (tri-mode: draft=remove / running=inspect / done+hold=apply).

- [ ] **Step 1** RTL test: given a mocked `useRun` returning a draft run + items, the tasks table renders checkboxes and a "Remove from run" batch bar on selection; the LLM select shows the configured providers; Start opens the confirm modal.
- [ ] **Step 2** Run → FAIL.
- [ ] **Step 3** Build the components to match the mockups (`.mockups/run-detail.html`, `start-confirm.html`): header + state badge, `LlmTierSelect`, estimate, `StartConfirmModal` (no ack checkbox; `Cancel`/`Start run`), `TasksTable` with status filter chips + search + pagination + batch bar. Wire `create_run`/`set_run_llm`/`start_run`/`remove_run_items`/`apply_run_items`.
- [ ] **Step 4** `cd web && npm test` → PASS.
- [ ] **Step 5** Commit `feat(web): runs list + run detail`.

### Task 6: Web — add-tasks page with JIRA-style filtering

**Files:**
- Create: `web/src/pages/ops/runs/AddTasks.tsx`, `web/src/ui/runs/FilterBar.tsx`, `FilterPopover.tsx`, `useEligiblePool.ts`, `web/src/ui/runs/filter.ts` (the `p_filter` builder + selection-persistence store).
- Modify: `web/src/App.tsx` (route `/ops/runs/:id/add`).
- Test: `web/src/ui/runs/filter.test.ts`, `AddTasks.test.tsx`.

**Interfaces:** Consumes `eligible_pool`/`eligible_pool_facets`/`add_run_items(_by_filter)`. Mirrors `add-tasks-v2.png`. Produces the add surface.

- [ ] **Step 1** Unit test `filter.ts`: multi-select within a dimension → array (OR); multiple dimensions → object keys (AND); toggling a value preserves others; selection set survives a filter change (a `Set<id>` store independent of the query).
- [ ] **Step 2** Run → FAIL.
- [ ] **Step 3** Build `FilterBar` (per-dimension `FilterPopover` with all options + counts from facets, multi-check, Apply), active-filter pills with `AND` + `Clear filters`, sort control + sortable headers, persistent selection banner (`Select all N matching` / `View selection` / `Clear all selected`), and the `Add N to run → back` action bar. Wire RPCs.
- [ ] **Step 4** `cd web && npm test` → PASS.
- [ ] **Step 5** Commit `feat(web): add-tasks page with faceted filtering`.

### Task 7: Retire the old /ops queue UI + cold-start seed

**Files:**
- Delete: `web/src/pages/ops/Dashboard.tsx`, `StageCard.tsx`, `web/src/ui/TriggerBar.tsx`, `CostConfirmModal.tsx`, `web/src/ui/stageConfig.ts`, `web/src/ui/hooks/useStageQueueCounts.ts`, `web/src/ui/pipelineStages.ts` (or repurpose), and their tests.
- Modify: `OpsLayout.tsx` default route → `RunsList`; add "load all eligible" empty-state (calls `add_run_items_by_filter(jid, '{"status":["never run"]}')` after `create_run`).
- Modify: any imports of `enqueue_job`/`approve_job` (replaced by `create_run`/`start_run`).

- [ ] **Step 1** Delete old components + tests; fix imports; `cd web && npm run build` clean.
- [ ] **Step 2** Implement the cold-start empty state on `RunsList`/`New run`.
- [ ] **Step 3** `npm test` + `npm run build` green.
- [ ] **Step 4** Commit `refactor(web): retire version-queue dashboard, add cold-start seed`.

---

## WAVE 2 — integration

### Task 8: End-to-end verify + docs + CLAUDE.md

**Files:** Modify `CLAUDE.md` (data-model + pipeline-conventions sections: queues are now explicit runs; `stage_runs`→`job_items`; `stage_reviews`→`human_reviews`; drop version-requeue prose), `docs/` as needed.

- [ ] **Step 1** `supabase db reset` locally; seed fake data; drive the flow with Playwright per the CLAUDE.md walkthrough recipe (create run → add flagged → start → items move). Screenshot proof.
- [ ] **Step 2** Full suites: `cd ingredients && uv run --extra dev pytest -q`, `cd web && npm test`, `cd common && uv run --extra dev pytest -q`.
- [ ] **Step 3** Update CLAUDE.md + commit `docs: explicit runs model`.
- [ ] **Step 4** Open the PR (base `main`).

## Self-review notes

- Spec coverage: model (T1), metering-as-provider (T3 `_estimate_cents`/`start_run`), UI runs/detail (T5), add-tasks filtering (T6), apply gate (T3 `apply_run_items` + T4 `apply_mode`), flagged→human_reviews (T1 rename + existing `flag_review`), re-run = new draft (T5 "Re-run failed/flagged" buttons seed `create_run`+`add_run_items`), cold-start (T7), migration (T1 backfill). human_reviews UI already exists (ported by rename in T1/T2).
- Open risk to verify during T3/T4: `apply_run_items` materialization is only meaningful for `hold` runs; MVP implements map/parse and no-ops the rest — call this out in the PR.
