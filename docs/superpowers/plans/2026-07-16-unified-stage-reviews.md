# Unified Stage Reviews Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate the three bespoke human-review mechanisms (`taxonomy_proposals`, `recipegf_proposals`, `ingredient_resolutions.method='manual'`) into one `stage_reviews` table where flag = proposal = override, make human input survive reruns, and adopt an append-versioned ledger — deleting two tables.

**Architecture:** A new `stage_reviews` table holds every stage's flags/proposals/overrides, distinguished by `state`/`origin`. Materialization of a resolved override into the stage's live output table is a single SQL function `apply_review(review_id)` called from both the `resolve_review` RPC (web, no backend) and a Python re-apply loop (worker). `stage_runs` becomes append-versioned; a `needs_review` view unifies the curator queue. A thin per-stage Python adapter (`entity_kind` + `load_context`) plus a per-stage `apply_review` SQL branch is the only stage-specific code.

**Tech Stack:** Postgres (Supabase migrations, plpgsql, RLS, pg_trgm), Python 3.11 (uv, psycopg, pytest), React + TypeScript + Vite + Vitest + React Query.

## Global Constraints

- One branch/PR: `claude/unified-stage-reviews` off `main`. Commit and push as each task lands.
- Slugs/kebab, house SQL style: lowercase keywords, `create table` etc. (match existing migrations).
- Every stage version constant is unchanged by this work — this is storage/review, not resolution logic. **Eval sets must not drift.**
- DB-integration tests run against `TEST_DB_URL` (auto-migrates; skip if unset). Never connect via `SUPABASE_DB_URL` in tests.
- Migrations are forward-only. Additive schema first; backfill+drop last; code in between so each commit is coherent.
- `apply_review` materialization is **SQL** (callable with the publishable key via `security definer` RPC) — the public site has no backend.
- RPCs are `security definer` and guard `if not public.is_admin() then raise`.
- Diff/promote UI, shadow runs, anonymous flagging, embeddings, and the taxonomy graph editor are **out of scope** (see spec Non-goals).

## File Structure

**New:**
- `supabase/migrations/<ts>_stage_reviews_schema.sql` — `stage_reviews`, `stage_live_version`, `review_floors`, `needs_review` view, `apply_review()` + `flag_review()` + `resolve_review()` + `floor_for()` functions, RLS, audit trigger. (Task 1, 8, 9)
- `supabase/migrations/<ts>_stage_reviews_backfill.sql` — backfill from the three sources, in-migration count asserts, drop the two proposal tables. (Task 15, LAST)
- `ingredients/src/ingredients/reviews/__init__.py`
- `ingredients/src/ingredients/reviews/model.py` — `insert_review`, `set_state`, `open_reviews_for`, `resolved_overrides_for`. (Task 4)
- `ingredients/src/ingredients/reviews/registry.py` — `StageReviewAdapter` protocol + `ADAPTERS` registry + `register`. (Task 3)
- `ingredients/src/ingredients/reviews/reapply.py` — `reapply_overrides(conn, stage, entity_ids)` + `supersede_stale(conn, stage, entity_ids)`. (Task 5)
- `ingredients/src/ingredients/reviews/adapters/{extract,parse,map,convert,cluster}.py` — one `StageReviewAdapter` each. (Tasks 10a-e, PARALLEL)
- `web/src/reviews/flagReview.ts` — RPC clients. (Task 11)
- `web/src/reviews/useNeedsReview.ts` — React Query hook over `needs_review`. (Task 11)
- `web/src/components/reviews/ReviewCard.tsx` + `bodies/{Map,Parse,Convert,Cluster,Extract}ReviewBody.tsx`. (Task 12 shell, 13a-e PARALLEL bodies)
- `web/src/components/reviews/FlagButton.tsx` — admin-only flag affordance. (Task 12)
- `web/src/pages/ops/ReviewsBrowser.tsx`. (Task 14)
- Tests alongside each (see tasks).

**Modified:**
- `ingredients/src/ingredients/pipeline/ledger.py` — append-versioned UPSERT + `work_queue`. (Task 2)
- `ingredients/src/ingredients/pipeline/stages/base.py` — invoke re-apply after each chunk. (Task 6)
- `ingredients/src/ingredients/mapping/resolutions.py` — stop clobbering `method='manual'`. (Task 7)
- `ingredients/src/ingredients/mapping/proposals.py` + `pipeline/stages/map.py` — write unified reviews on `propose_form`; approve path via `resolve_review`. (Task 10c-wiring, folded into map adapter task)
- `web/src/pages/ops/StageRunsBrowser.tsx` — filter to live version. (Task 14)
- Public recipe views (`web/src/pages/*Recipe*`, ingredient/step rendering) — mount `FlagButton`. (Task 12-wiring)

**Deleted:** `taxonomy_proposals`, `recipegf_proposals` (tables + `proposals.py` bespoke bits superseded by reviews).

**Interfaces locked here (used across tasks):**
- SQL: `flag_review(p_entity_kind text, p_entity_id text, p_stage text, p_note text) returns bigint`
- SQL: `resolve_review(p_id bigint, p_payload jsonb, p_dismiss boolean default false) returns void`
- SQL: `apply_review(p_id bigint) returns void`
- SQL: `floor_for(p_stage text) returns real`
- Python: `reviews.model.insert_review(conn, *, entity_kind, entity_id, stage, origin, payload=None, note=None, origin_version=None, state='open') -> int`
- Python: `reviews.registry.StageReviewAdapter` = Protocol(`entity_kind: str`, `load_context(conn, entity_id) -> dict`)
- Python: `reviews.reapply.reapply_overrides(conn, *, stage, entity_ids: list[str]) -> None`

---

## Phase 0 — Schema & shared model (SEQUENTIAL SPINE — Tasks 1–7 in order)

### Task 1: `stage_reviews` schema migration (tables + indexes + RLS)

**Files:**
- Create: `supabase/migrations/<ts>_stage_reviews_schema.sql`
- Test: `ingredients/tests/test_stage_reviews_schema.py`

**Produces:** `stage_reviews`, `stage_live_version`, `review_floors` tables.

- [ ] **Step 1: Write the failing test**

```python
# ingredients/tests/test_stage_reviews_schema.py
import os, psycopg, pytest

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DB_URL"), reason="no TEST_DB_URL")

def test_one_open_review_per_entity_stage(db):  # `db` = autouse migrated conn fixture
    db.execute("insert into stage_reviews(entity_kind,entity_id,stage,origin) "
               "values ('ingredient_name','lime','map','human_flag')")
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute("insert into stage_reviews(entity_kind,entity_id,stage,origin) "
                   "values ('ingredient_name','lime','map','machine_proposal')")

def test_resolved_rows_do_not_block_new_open(db):
    db.execute("insert into stage_reviews(entity_kind,entity_id,stage,origin,state) "
               "values ('ingredient_name','gin','map','human_flag','resolved')")
    db.execute("insert into stage_reviews(entity_kind,entity_id,stage,origin) "
               "values ('ingredient_name','gin','map','human_flag')")  # must succeed
```

- [ ] **Step 2: Run — expect FAIL** (`relation "stage_reviews" does not exist`)
  Run: `cd ingredients && uv run --extra dev pytest tests/test_stage_reviews_schema.py -v`

- [ ] **Step 3: Write the migration** (tables from the spec's Data model section, verbatim: `stage_reviews` with the partial unique index `stage_reviews_one_open`, `stage_queue_idx`; `stage_live_version`; `review_floors(stage text primary key, floor real not null)`). Enable RLS on `stage_reviews` with an `is_admin()` read+write policy (copy the `stage_runs` policy). Attach the audit trigger (`create trigger … execute function audit.log_change()` — match `20260717091000_audit_triggers.sql`).

- [ ] **Step 4: Run — expect PASS.** If a `db` fixture doesn't exist yet in conftest, add a function-scoped autouse fixture that yields an autocommit `psycopg.connect(TEST_DB_URL)` and `TRUNCATE stage_reviews` between tests.

- [ ] **Step 5: Commit** `git add -A && git commit -m "stage_reviews schema + one-open constraint"`

### Task 2: Append-versioned ledger

**Files:**
- Modify: `ingredients/src/ingredients/pipeline/ledger.py:47` (conflict target), `work_queue` (line ~112)
- Modify: `supabase/migrations/<ts>_stage_reviews_schema.sql` (add: `alter table stage_runs drop constraint stage_runs_entity_type_entity_id_stage_key, add unique (entity_type, entity_id, stage, version);`)
- Test: `ingredients/tests/test_append_versioned_ledger.py`

**Consumes:** Task 1 migration file. **Produces:** ledger keeps one row per `(entity,stage,version)`.

- [ ] **Step 1: Failing test** — record a run at `v1`, then `v2` for the same recipe; assert **two** `stage_runs` rows exist; assert `work_queue(version='v2')` still returns the recipe before its v2 run and not after.

```python
def test_ledger_appends_versions(db):
    from ingredients.pipeline import ledger
    ledger.record_run(db, entity_type='recipe', entity_id=1, stage='map', version='v1',
                      outcome='resolved', method='deterministic')
    ledger.record_run(db, entity_type='recipe', entity_id=1, stage='map', version='v2',
                      outcome='resolved', method='deterministic')
    n = db.execute("select count(*) from stage_runs where entity_id=1 and stage='map'").fetchone()[0]
    assert n == 2
```

- [ ] **Step 2: Run — expect FAIL** (count == 1, old UPSERT overwrote).
- [ ] **Step 3: Change** `ledger.py:47` conflict target to `on conflict (entity_type, entity_id, stage, version) do update set …`; update the `work_queue` docstring/logic that assumed ≤1 row per `(entity,stage)` — the NOT EXISTS predicate already keys on version, so only the comment + any "latest" read needs the `version` filter. Add the `alter table stage_runs` uniqueness change to the Task 1 migration.
- [ ] **Step 4: Run — expect PASS.** Also run the existing `tests/test_stage_map.py` to confirm no regression.
- [ ] **Step 5: Commit** `"append-versioned stage_runs ledger"`

### Task 3: Adapter registry + protocol

**Files:** Create `ingredients/src/ingredients/reviews/__init__.py`, `reviews/registry.py`; Test `ingredients/tests/test_review_registry.py`

**Produces:** `StageReviewAdapter` protocol, `register(adapter)`, `ADAPTERS: dict[str, StageReviewAdapter]`, `adapter_for(stage)`.

- [ ] **Step 1: Failing test**

```python
def test_register_and_lookup():
    from ingredients.reviews import registry
    class Fake:
        stage = 'parse'; entity_kind = 'recipe_ingredient'
        def load_context(self, conn, entity_id): return {'id': entity_id}
    registry.register(Fake())
    assert registry.adapter_for('parse').entity_kind == 'recipe_ingredient'
```

- [ ] **Step 2: Run — FAIL** (module missing).
- [ ] **Step 3: Implement** the `Protocol` (`stage: str`, `entity_kind: str`, `load_context(conn, entity_id) -> dict`), a module-level `ADAPTERS` dict, `register`, `adapter_for`.
- [ ] **Step 4: PASS.**  **Step 5: Commit** `"review adapter registry"`

### Task 4: Review model (row access)

**Files:** Create `reviews/model.py`; Test `tests/test_review_model.py`

**Produces:** `insert_review(...) -> int` (respects the one-open index: on conflict do nothing → return existing open id), `set_state(conn, id, state, reviewed_by)`, `open_reviews_for(conn, stage, entity_ids) -> list[dict]`, `resolved_overrides_for(conn, stage, entity_ids) -> list[dict]`.

- [ ] **Step 1: Failing test** — `insert_review` twice for same `(entity,stage)` returns the same id and leaves one open row; `set_state(...,'resolved')` frees the slot for a new open.
- [ ] **Step 2: FAIL. Step 3: Implement** with `insert … on conflict (entity_kind,entity_id,stage) where state='open' do nothing returning id`, falling back to a select of the open row's id. **Step 4: PASS. Step 5: Commit** `"review model row access"`

### Task 5: Re-apply overlay + supersede (Python)

**Files:** Create `reviews/reapply.py`; Test `tests/test_reapply.py`

**Consumes:** `apply_review` SQL (Task 8 — but Python calls it by name, so this task can land first and its test stubs `apply_review` as a trivial SQL fn, replaced in Task 8). **Produces:** `reapply_overrides(conn, *, stage, entity_ids)` (calls `select apply_review(id)` for each resolved override in scope) and `supersede_stale(conn, *, stage, entity_ids)` (dismiss open `machine_proposal`/`distance_gate` for entities now resolved; never touch `human_flag`/resolved).

- [ ] **Step 1: Failing test** — seed a resolved map override for `entity_id='lime'`; `reapply_overrides(stage='map', entity_ids=['lime'])` calls `apply_review`; assert the override's slug is in `ingredient_resolutions`. Seed an open `machine_proposal` for a recipe whose v-new run resolved; `supersede_stale` sets it `dismissed`; a `human_flag` in scope stays `open`.
- [ ] **Step 2: FAIL. Step 3: Implement.** **Step 4: PASS. Step 5: Commit** `"re-apply overlay + supersede-stale"`

### Task 6: base.py invokes re-apply after each chunk

**Files:** Modify `ingredients/src/ingredients/pipeline/stages/base.py` (after `record_many` in a chunk transaction, call `reapply_overrides` + `supersede_stale` for the chunk's entity ids). Test `tests/test_base_reapply_hook.py`

- [ ] **Step 1: Failing test** — run a fake stage_fn that records a chunk; assert `reapply_overrides` was invoked with the chunk's ids (monkeypatch/spy).
- [ ] **Step 2: FAIL. Step 3:** add a `reapply_after_chunk(conn, stage, entity_ids)` helper in base.py that stage_fns call at chunk-commit; wire it in the shared chunk path. **Step 4: PASS. Step 5: Commit** `"stage base: re-apply overrides after each chunk"`

### Task 7: resolutions.py stops clobbering manual

**Files:** Modify `ingredients/src/ingredients/mapping/resolutions.py`; Test `tests/test_pin_survives_rerun.py` (THE guarantee)

- [ ] **Step 1: Failing test**

```python
def test_manual_resolution_survives_rerun(db):
    from ingredients.mapping.resolutions import write_resolution
    # human override lands as a resolved review + live ingredient_resolutions row
    db.execute("insert into stage_reviews(entity_kind,entity_id,stage,origin,state,payload) "
               "values ('ingredient_name','fresh lime juice','map','human_flag','resolved',"
               "'{\"slug\":\"lime-juice\"}')")
    db.execute("select apply_review(id) from stage_reviews where entity_id='fresh lime juice'")
    # a rerun recomputes the auto answer, then re-apply overlays the override
    write_resolution(db, normalized_name='fresh lime juice', taxonomy_slug='WRONG-auto',
                     method='lexical', version='v2')
    from ingredients.reviews.reapply import reapply_overrides
    reapply_overrides(db, stage='map', entity_ids=['fresh lime juice'])
    slug = db.execute("select taxonomy_slug from ingredient_resolutions "
                      "where normalized_name='fresh lime juice'").fetchone()[0]
    assert slug == 'lime-juice'  # override won, not WRONG-auto
```

- [ ] **Step 2: FAIL. Step 3:** `write_resolution` must not overwrite a row whose durable override exists — simplest: leave `write_resolution` as-is (auto writes), but the re-apply overlay runs *after* and re-stamps. Ensure `write_resolution`'s auto write is not the final word: the chunk path (Task 6) always re-applies after. (No code change to `write_resolution` beyond a comment if the overlay covers it; if map writes outside the chunk path, call `reapply_overrides` there.)
- [ ] **Step 4: PASS. Step 5: Commit** `"pin: manual map resolutions survive reruns"`

---

## Phase 1 — SQL functions (SEQUENTIAL — Tasks 8, 9; needed by web + reapply)

### Task 8: `apply_review()` SQL function (per-stage materialization)

**Files:** Modify `<ts>_stage_reviews_schema.sql`; Test `tests/test_apply_review.py`

**Produces:** `apply_review(p_id bigint)` — branch on `stage`/`entity_kind`, write the resolved payload into the live table:

```sql
create or replace function apply_review(p_id bigint) returns void
language plpgsql security definer set search_path = public as $$
declare r stage_reviews; begin
  select * into r from stage_reviews where id = p_id and state = 'resolved';
  if not found then return; end if;
  if r.stage = 'map' then
    update ingredient_resolutions
       set taxonomy_slug = r.payload->>'slug', method = 'manual', updated_at = now()
     where normalized_name = r.entity_id;
    if not found then
      insert into ingredient_resolutions(normalized_name, taxonomy_slug, method, version)
      values (r.entity_id, r.payload->>'slug', 'manual', 'override');
    end if;
  elsif r.stage = 'parse' then
    update recipe_ingredients set
      name=coalesce(r.payload->>'name',name),
      amount=coalesce((r.payload->>'amount')::numeric,amount),
      unit=coalesce(r.payload->>'unit',unit)
     where id = r.entity_id::bigint;
  elsif r.stage = 'cluster' then
    update recipes set cluster_id=coalesce(r.payload->>'cluster_id',cluster_id),
      variant_key=coalesce(r.payload->>'variant_key',variant_key),
      canonical_name=coalesce(r.payload->>'canonical_name',canonical_name)
     where id = r.entity_id::bigint;
  elsif r.stage = 'extract' then
    update recipes set title=coalesce(r.payload->>'title',title),
      author=coalesce(r.payload->>'author',author),
      image_url=coalesce(r.payload->>'image_url',image_url)
     where id = r.entity_id::bigint;
  elsif r.stage = 'convert' then
    delete from recipe_steps where recipe_id = r.entity_id::bigint;
    insert into recipe_steps(recipe_id, step_index, verb, roles, result, modifiers)
    select r.entity_id::bigint, (ordinality-1), e->>'verb',
           coalesce(e->'roles','{}'::jsonb), e->>'result',
           coalesce((select array_agg(x) from jsonb_array_elements_text(e->'modifiers') x), '{}')
    from jsonb_array_elements(r.payload->'steps') with ordinality as t(e, ordinality);
  end if;
end $$;
```

- [ ] **Step 1: Failing test** per stage (map/parse/cluster/extract/convert) — insert a resolved review, call `apply_review`, assert the live table changed. **Step 2: FAIL. Step 3: add function. Step 4: PASS. Step 5: Commit** `"apply_review() per-stage materialization"`

### Task 9: `flag_review`, `resolve_review`, `floor_for`, `needs_review` view

**Files:** Modify `<ts>_stage_reviews_schema.sql`; Test `tests/test_review_rpcs.py`, `tests/test_needs_review.py`

- [ ] **Step 1: Failing tests** — `floor_for('map')` returns the `review_floors` value or a default (e.g. `0.0`); `flag_review(...)` inserts an open `human_flag` and is rejected for non-admin; `resolve_review(id, payload)` sets `resolved` + calls `apply_review`; `resolve_review(id, null, true)` sets `dismissed`; `needs_review` returns the union (abstain/proposes_new ∪ open reviews ∪ `confidence < floor_for(stage)`).
- [ ] **Step 2: FAIL. Step 3:** add the three RPCs (`security definer`, `is_admin()` guard on the write ones) and the `needs_review` view + `floor_for` from the spec. Seed `review_floors` with conservative defaults. **Step 4: PASS. Step 5: Commit** `"flag/resolve RPCs + needs_review view + floors"`

---

## Phase 2 — Per-stage adapters (PARALLEL — Tasks 10a–10e, disjoint files, all depend on Task 3)

Each adapter is `reviews/adapters/<stage>.py` implementing the `StageReviewAdapter` protocol (Task 3) and registered in `reviews/__init__.py`. `load_context` returns the current live output + machine context for the card. **These five have no shared files (except a one-line register in `__init__.py` — the integrating agent adds all five register lines in one commit after the parallel bodies land).**

### Task 10a: `parse` adapter — `entity_kind='recipe_ingredient'`
**Files:** Create `reviews/adapters/parse.py`; Test `tests/adapters/test_parse_adapter.py`
- [ ] Failing test: `load_context(conn, '<recipe_ingredient id>')` returns `{raw_text, name, amount, unit}` from `recipe_ingredients`. Implement. PASS. Commit `"parse review adapter"`.

### Task 10b: `map` adapter — `entity_kind='ingredient_name'` (+ wire propose_form → unified review)
**Files:** Create `reviews/adapters/map.py`; Modify `mapping/proposals.py` + `pipeline/stages/map.py` (replace `enqueue_form_proposal` with `insert_review(origin='machine_proposal', entity_kind='ingredient_name', entity_id=name, stage='map', origin_version=version, payload={proposed_slug,...,candidates})`; the distance-gate path inserts `origin='distance_gate'`). Test `tests/adapters/test_map_adapter.py`, `tests/test_map_writes_reviews.py`
- [ ] Failing test: a `propose_form` outcome inserts a `machine_proposal` review (not a `taxonomy_proposals` row). `load_context` returns `{normalized_name, current_slug, candidates}`. Implement. PASS. Commit `"map review adapter + propose_form→review"`.

### Task 10c: `cluster` adapter — `entity_kind='recipe'`
**Files:** Create `reviews/adapters/cluster.py`; Test `tests/adapters/test_cluster_adapter.py`
- [ ] Failing test: `load_context` returns `{canonical_name, cluster_id, variant_key, ingredient_set}`. Implement. PASS. Commit.

### Task 10d: `extract` adapter — `entity_kind='recipe'`
**Files:** Create `reviews/adapters/extract.py`; Test `tests/adapters/test_extract_adapter.py`
- [ ] Failing test: `load_context` returns `{title, author, image_url, source_url}`. Implement. PASS. Commit.

### Task 10e: `convert` adapter — `entity_kind='recipe_step'`/`recipe`
**Files:** Create `reviews/adapters/convert.py`; Test `tests/adapters/test_convert_adapter.py`
- [ ] Failing test: `load_context` returns `{steps: [...], technique}` for the recipe. Implement. PASS. Commit.

### Task 10f (INTEGRATION, after 10a–e): adapter conformance + register all
**Files:** Modify `reviews/__init__.py` (register all five); Test `tests/test_adapter_conformance.py`
- [ ] Parametrized test across `registry.ADAPTERS`: each declares `entity_kind`, `load_context` returns a dict for a seeded entity, and `apply_review` is idempotent (call twice → same live state). Commit `"register adapters + conformance"`.

---

## Phase 3 — Web (PARALLEL where noted; all depend on Task 9 RPCs)

### Task 11: RPC clients + needs-review hook
**Files:** Create `web/src/reviews/flagReview.ts` (`flagReview`, `resolveReview`, `dismissReview` calling `supabase.rpc(...)`), `web/src/reviews/useNeedsReview.ts`; Test `web/src/reviews/flagReview.test.ts`
- [ ] Failing Vitest: `flagReview(...)` calls `supabase.rpc('flag_review', {...})` (mock supabase). Implement. PASS. Commit `"web: review RPC clients + hook"`.

### Task 12: FlagButton (admin-only) + mount on public recipe views
**Files:** Create `web/src/components/reviews/FlagButton.tsx`; Modify public recipe render (ingredient line, step, title). Test `web/src/components/reviews/FlagButton.test.tsx`
- [ ] Failing test: renders `null` when `useIsAdmin()` is false; renders a button that calls `flagReview` when true. Implement (reuse `useIsAdmin`). Mount on ingredient/step/title/cluster-name elements passing the right `(entity_kind, entity_id, stage)`. PASS. Commit `"web: admin-only FlagButton on recipe views"`.

### Task 13a–e (PARALLEL): per-stage ReviewBody renderers
**Files:** Create `web/src/components/reviews/bodies/{Parse,Map,Cluster,Extract,Convert}ReviewBody.tsx` + `.test.tsx` each. Each renders `load_context` data + an edit form producing the stage's `payload`, and calls `resolveReview`/`dismissReview`. Disjoint files → parallel.
- [ ] Each: failing test renders the body for a sample review and fires resolve with the expected payload shape. Implement. PASS. Commit per body.

### Task 12s: ReviewCard shell (after 13 bodies exist)
**Files:** Create `web/src/components/reviews/ReviewCard.tsx` (state buttons, note, who/when; picks the body by `stage`); Test `ReviewCard.test.tsx`
- [ ] Failing test: given a review with `stage='map'`, renders `MapReviewBody`. Implement a `BODIES: Record<string, Component>` map. PASS. Commit `"web: ReviewCard shell + body dispatch"`.

### Task 14: ReviewsBrowser + StageRunsBrowser live-version filter
**Files:** Create `web/src/pages/ops/ReviewsBrowser.tsx`; Modify `web/src/pages/ops/StageRunsBrowser.tsx`. Tests alongside.
- [ ] Failing test: `ReviewsBrowser` lists `needs_review` rows and renders a `ReviewCard` per item; `StageRunsBrowser` query filters to the live version. Implement. PASS. Commit `"web: ReviewsBrowser + live-version filter"`.

---

## Phase 4 — Migration cutover + guardrails (SEQUENTIAL — LAST)

### Task 15: Backfill + drop migration
**Files:** Create `supabase/migrations/<ts>_stage_reviews_backfill.sql`; Test `tests/test_stage_reviews_migration.py` (parity)
- [ ] **Step 1: Failing test** — seed representative `taxonomy_proposals`, `recipegf_proposals`, and `ingredient_resolutions(method='manual')` rows; apply the backfill; assert each maps to a `stage_reviews` row with correct `state/origin/payload/origin_version` (mapping table from the spec), counts match, `ingredient_resolutions` live rows untouched, and the two proposal tables are gone.
- [ ] **Step 2: FAIL. Step 3:** write the backfill (three `insert … select` from the spec's mapping), an in-migration `do $$ begin assert (select count(*) …) = …; end $$;` guard per source, then `drop table taxonomy_proposals; drop table recipegf_proposals;` (note: `recipegf_proposals` has no code writer — grep clean — so only rows + table go). **Step 4: PASS. Step 5: Commit** `"backfill 3 mechanisms into stage_reviews + drop proposal tables"`

### Task 16: Queue-preservation + eval no-drift guardrails
**Files:** Test `tests/test_queue_preservation.py`; run eval suites.
- [ ] Assert `needs_review` surfaces the same items the old queries did (open proposals ∪ abstains) for a fixed fixture. Run `cd ingredients && uv run --extra dev pytest` (eval sets included) — assert green, no score drift. Commit `"guardrails: queue preservation + eval no-drift"`.

### Task 17: Full-suite + web build verification
- [ ] `cd ingredients && uv run --extra dev pytest` — all pass.
- [ ] `cd web && npm test` — all pass.
- [ ] `cd web && npm run build` — clean.
- [ ] Push. Open PR base `main`.

---

## Self-Review

**Spec coverage:** stage_reviews (T1), append-versioned ledger (T2), registry/adapters (T3,10), model+reapply+supersede (T4,5,6), pin-survives-rerun (T7), apply_review SQL (T8), RPCs+needs_review+floors (T9), web flag/card/bodies/browser + public-site admin-only flag (T11–14), migration+backfill+drop (T15), guardrails+eval-no-drift (T16,17). All spec sections mapped.

**Refinement vs spec:** the spec described `apply()` as a per-stage hook; the plan pins it as the SQL function `apply_review()` (Task 8) called from both `resolve_review` (web, no backend) and the Python re-apply loop — same intent, realized once, reachable from the backendless web. The Python adapter keeps `entity_kind` + `load_context` (card/queue side).

**Placeholder scan:** no TBD/TODO; representative code shown for spine + one example per parallel family, with the pattern stated for replicas.

**Type consistency:** `insert_review`, `reapply_overrides`, `apply_review`, `flag_review`, `resolve_review`, `floor_for`, `adapter_for`, `StageReviewAdapter(entity_kind, load_context)` used consistently across tasks.
