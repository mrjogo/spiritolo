# Taxonomy Curation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the taxonomy graph editable: inline-edit NodeCard fields, add a child via a `+` on hover, edit parents via a fuzzy-search overlay, and delete a node with a blocking-aware confirmation.

**Architecture:** Reads stay on the existing `taxonomy_public` view + publishable key. Writes go through five new SECURITY DEFINER plpgsql RPCs (`get_taxonomy_node_blockers`, `create_taxonomy_node`, `update_taxonomy_node`, `set_node_parents`, `delete_taxonomy_node`), each guarded by `public.is_admin()`. The SPA gets four new modal components plus an inline `EditableField` primitive and a `+` overlay; everything uses `react-hook-form + zod`. Post-save, the page-level `rows` array is mutated incrementally so the force-graph keeps positions instead of remounting.

**Tech Stack:** TypeScript, React 18, Vite, react-force-graph-2d, react-hook-form 7+, zod 3+, @hookform/resolvers/zod, Supabase JS, plpgsql, pytest+psycopg for DB-side tests.

**Spec:** [`docs/superpowers/specs/2026-05-07-taxonomy-curation-design.md`](docs/superpowers/specs/2026-05-07-taxonomy-curation-design.md)

---

## File map

**New:**
- `supabase/migrations/20260507130000_taxonomy_curation_rpcs.sql` — five RPC functions
- `web/src/components/taxonomy/rpcs.ts` — typed wrappers around `supabase.rpc(...)`
- `web/src/components/taxonomy/schemas.ts` — zod schemas shared by all forms
- `web/src/components/taxonomy/cycle.ts` — client-side reachability helper for cycle prevention
- `web/src/components/taxonomy/EditableField.tsx` — inline-edit primitive (text / dropdown / toggle)
- `web/src/components/taxonomy/AliasChipEditor.tsx` — chip editor for the aliases array
- `web/src/components/taxonomy/CreateChildModal.tsx` — RHF form for new child
- `web/src/components/taxonomy/EditParentsModal.tsx` — fuzzy-search overlay
- `web/src/components/taxonomy/DeleteNodeModal.tsx` — confirmation with blocker preflight
- `web/src/components/taxonomy/PlusButton.tsx` — HTML overlay badge tracking the hovered node
- `web/src/components/taxonomy/HighlightPulse.tsx` — gold-ring pulse effect on the graph
- `web/src/components/taxonomy/Toast.tsx` — minimal RPC-error toast
- `web/src/components/taxonomy/cycle.test.ts`
- `web/src/components/taxonomy/EditableField.test.tsx`
- `web/src/components/taxonomy/AliasChipEditor.test.tsx`
- `web/src/components/taxonomy/CreateChildModal.test.tsx`
- `web/src/components/taxonomy/EditParentsModal.test.tsx`
- `web/src/components/taxonomy/DeleteNodeModal.test.tsx`
- `ingredients/tests/test_taxonomy_rpcs.py` — DB-side tests for the five RPCs (parked in `ingredients/tests/` because that's where the migrations-on-session-start conftest already lives)

**Modify:**
- `web/package.json` — add `react-hook-form`, `zod`, `@hookform/resolvers`
- `web/src/components/taxonomy/NodeCard.tsx` — wire inline editors, add PARENTS / CHILDREN sections, add delete link
- `web/src/components/taxonomy/NodeCard.test.tsx` — new assertions for the editable surface
- `web/src/components/taxonomy/ForceCanvas.tsx` — expose a `getNodeScreenCoords(id)` and `panTo(x, y, ms)` on the imperative handle
- `web/src/components/taxonomy/taxonomy.css` — pencil hover ring, modal chrome, chip styling, pulse keyframes
- `web/src/pages/Taxonomy.tsx` — orchestrate the four modals, the `+` overlay, post-save state mutation, focus, pulse, pan

---

## Phase 0 — Setup

### Task 0.1: Install form libraries

**Files:**
- Modify: `web/package.json`

- [ ] **Step 1: Install dependencies**

```bash
cd web && npm install react-hook-form zod @hookform/resolvers
```

- [ ] **Step 2: Verify install**

```bash
cd web && grep -E "react-hook-form|@hookform|^\s+\"zod\"" package.json
```

Expected: three matching lines, all under `"dependencies"`.

- [ ] **Step 3: Run baseline web tests**

```bash
cd web && npm test -- --run
```

Expected: all existing tests pass.

- [ ] **Step 4: Commit**

```bash
git add web/package.json web/package-lock.json
git commit -m "Add react-hook-form, zod, @hookform/resolvers for taxonomy curation forms"
```

---

## Phase 1 — Backend RPCs

The migration adds five plpgsql functions and grants `execute` on each to `authenticated`. RLS on `taxonomy_nodes` / `taxonomy_edges` / `taxonomy_aliases` is already maximal (enabled with no policies = deny-all), so no policy changes are needed. SECURITY DEFINER bypasses RLS for the function body.

### Task 1.1: Write the migration file

**Files:**
- Create: `supabase/migrations/20260507130000_taxonomy_curation_rpcs.sql`

- [ ] **Step 1: Write the SQL**

```sql
-- Taxonomy curation RPCs.
--
-- Five SECURITY DEFINER functions are the only write path for the curator
-- UI on taxonomy_nodes / taxonomy_edges / taxonomy_aliases. RLS on those
-- three tables stays deny-all (enabled, no policies); the functions
-- bypass RLS by virtue of running as the function owner.
--
-- All five guard on public.is_admin(). The read-only blocker counter
-- (get_taxonomy_node_blockers) is separated from the destructive
-- delete_taxonomy_node so the UI can preflight without invoking the
-- delete path.

------------------------------------------------------------------------
-- get_taxonomy_node_blockers(id) — read-only preflight for delete UI
------------------------------------------------------------------------
create or replace function public.get_taxonomy_node_blockers(p_id bigint)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
begin
  if not public.is_admin() then
    raise exception 'permission denied: not admin' using errcode = '42501';
  end if;

  return jsonb_build_object(
    'children', (
      select count(*)::int from public.taxonomy_edges where parent_id = p_id
    ),
    'child_names', coalesce(
      (
        select jsonb_agg(
          jsonb_build_object('id', n.id, 'display_name', n.display_name)
          order by n.display_name
        )
        from public.taxonomy_edges e
        join public.taxonomy_nodes n on n.id = e.child_id
        where e.parent_id = p_id
      ),
      '[]'::jsonb
    ),
    'parents', (
      select count(*)::int from public.taxonomy_edges where child_id = p_id
    ),
    'aliases', (
      select count(*)::int from public.taxonomy_aliases where node_id = p_id
    ),
    'provenance', (
      select count(*)::int from public.taxonomy_provenance where node_id = p_id
    ),
    'recipe_ingredients', (
      select count(*)::int from public.recipe_ingredients where taxonomy_node_id = p_id
    ),
    'taxonomy_proposals', (
      select count(*)::int from public.taxonomy_proposals where proposed_parent_id = p_id
    )
  );
end;
$$;

grant execute on function public.get_taxonomy_node_blockers(bigint) to authenticated;

------------------------------------------------------------------------
-- create_taxonomy_node(...) — atomic node + edge + aliases insert
------------------------------------------------------------------------
create or replace function public.create_taxonomy_node(
  p_parent_id           bigint,
  p_slug                text,
  p_display_name        text,
  p_node_kind           text default null,
  p_default_role        text default null,
  p_is_cluster_node     boolean default false,
  p_is_defining_garnish boolean default false,
  p_aliases             text[] default '{}'::text[]
)
returns bigint
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_new_id bigint;
begin
  if not public.is_admin() then
    raise exception 'permission denied: not admin' using errcode = '42501';
  end if;

  if p_parent_id is not null
     and not exists (select 1 from public.taxonomy_nodes where id = p_parent_id) then
    raise exception 'parent_id % not found', p_parent_id using errcode = '23503';
  end if;

  insert into public.taxonomy_nodes (
    slug, display_name, node_kind, default_role,
    is_cluster_node, is_defining_garnish
  )
  values (
    p_slug, p_display_name, p_node_kind, p_default_role,
    p_is_cluster_node, p_is_defining_garnish
  )
  returning id into v_new_id;

  if p_parent_id is not null then
    insert into public.taxonomy_edges (parent_id, child_id)
    values (p_parent_id, v_new_id);
  end if;

  insert into public.taxonomy_aliases (alias, node_id)
  select a, v_new_id
  from unnest(p_aliases) as a
  where a is not null and trim(a) <> '';

  return v_new_id;
end;
$$;

grant execute on function public.create_taxonomy_node(
  bigint, text, text, text, text, boolean, boolean, text[]
) to authenticated;

------------------------------------------------------------------------
-- update_taxonomy_node(id, patch jsonb) — partial update
------------------------------------------------------------------------
-- Patch keys recognized: slug, display_name, node_kind, default_role,
-- is_cluster_node, is_defining_garnish, aliases. Missing keys leave
-- the column alone. Explicit JSON null in node_kind / default_role
-- sets the column to NULL (those columns are nullable). Aliases is
-- replace-all when present.
create or replace function public.update_taxonomy_node(
  p_id    bigint,
  p_patch jsonb
)
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
  if not public.is_admin() then
    raise exception 'permission denied: not admin' using errcode = '42501';
  end if;

  if not exists (select 1 from public.taxonomy_nodes where id = p_id) then
    raise exception 'taxonomy_node % not found', p_id using errcode = '23503';
  end if;

  update public.taxonomy_nodes
  set
    slug         = case when p_patch ? 'slug' then p_patch->>'slug' else slug end,
    display_name = case when p_patch ? 'display_name' then p_patch->>'display_name' else display_name end,
    node_kind    = case when p_patch ? 'node_kind' then nullif(p_patch->>'node_kind', '') else node_kind end,
    default_role = case when p_patch ? 'default_role' then nullif(p_patch->>'default_role', '') else default_role end,
    is_cluster_node = case
      when p_patch ? 'is_cluster_node' then (p_patch->>'is_cluster_node')::boolean
      else is_cluster_node
    end,
    is_defining_garnish = case
      when p_patch ? 'is_defining_garnish' then (p_patch->>'is_defining_garnish')::boolean
      else is_defining_garnish
    end
  where id = p_id;

  if p_patch ? 'aliases' then
    delete from public.taxonomy_aliases where node_id = p_id;
    insert into public.taxonomy_aliases (alias, node_id)
    select a, p_id
    from jsonb_array_elements_text(p_patch->'aliases') as t(a)
    where a is not null and trim(a) <> '';
  end if;
end;
$$;

grant execute on function public.update_taxonomy_node(bigint, jsonb) to authenticated;

------------------------------------------------------------------------
-- set_node_parents(id, parent_ids[]) — replace edge set, reject cycles
------------------------------------------------------------------------
create or replace function public.set_node_parents(
  p_id         bigint,
  p_parent_ids bigint[]
)
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
  if not public.is_admin() then
    raise exception 'permission denied: not admin' using errcode = '42501';
  end if;

  if not exists (select 1 from public.taxonomy_nodes where id = p_id) then
    raise exception 'taxonomy_node % not found', p_id using errcode = '23503';
  end if;

  if p_id = any(coalesce(p_parent_ids, '{}'::bigint[])) then
    raise exception 'cycle: a node cannot be its own parent' using errcode = '23514';
  end if;

  -- Reject if any proposed parent is a (transitive) descendant of p_id.
  if exists (
    with recursive descendants as (
      select child_id from public.taxonomy_edges where parent_id = p_id
      union
      select e.child_id
      from public.taxonomy_edges e
      join descendants d on e.parent_id = d.child_id
    )
    select 1 from descendants
    where child_id = any(coalesce(p_parent_ids, '{}'::bigint[]))
  ) then
    raise exception 'cycle: at least one proposed parent is a descendant of node %', p_id
      using errcode = '23514';
  end if;

  delete from public.taxonomy_edges where child_id = p_id;
  insert into public.taxonomy_edges (parent_id, child_id)
  select p, p_id
  from unnest(coalesce(p_parent_ids, '{}'::bigint[])) as p
  where p is not null;
end;
$$;

grant execute on function public.set_node_parents(bigint, bigint[]) to authenticated;

------------------------------------------------------------------------
-- delete_taxonomy_node(id) — refuse if children / refs exist
------------------------------------------------------------------------
create or replace function public.delete_taxonomy_node(p_id bigint)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_children    int;
  v_recipes     int;
  v_proposals   int;
begin
  if not public.is_admin() then
    raise exception 'permission denied: not admin' using errcode = '42501';
  end if;

  if not exists (select 1 from public.taxonomy_nodes where id = p_id) then
    raise exception 'taxonomy_node % not found', p_id using errcode = '23503';
  end if;

  select count(*) into v_children
    from public.taxonomy_edges where parent_id = p_id;
  select count(*) into v_recipes
    from public.recipe_ingredients where taxonomy_node_id = p_id;
  select count(*) into v_proposals
    from public.taxonomy_proposals where proposed_parent_id = p_id;

  if v_children > 0 or v_recipes > 0 or v_proposals > 0 then
    raise exception
      'blocked: % children, % recipe references, % proposal references',
      v_children, v_recipes, v_proposals
      using errcode = '23503',
            detail = jsonb_build_object(
              'children', v_children,
              'recipe_ingredients', v_recipes,
              'taxonomy_proposals', v_proposals
            )::text;
  end if;

  delete from public.taxonomy_nodes where id = p_id;
end;
$$;

grant execute on function public.delete_taxonomy_node(bigint) to authenticated;
```

- [ ] **Step 2: Apply the migration locally**

Run from the **Mac host** (per CLAUDE.md):

```bash
supabase migration up --include-all
```

Expected: shows the new migration applied; no errors.

- [ ] **Step 3: Sanity-check from inside the devcontainer**

```bash
psql "$SUPABASE_DB_URL" -c "\df public.get_taxonomy_node_blockers"
psql "$SUPABASE_DB_URL" -c "\df public.create_taxonomy_node"
psql "$SUPABASE_DB_URL" -c "\df public.update_taxonomy_node"
psql "$SUPABASE_DB_URL" -c "\df public.set_node_parents"
psql "$SUPABASE_DB_URL" -c "\df public.delete_taxonomy_node"
```

Expected: each prints one row.

- [ ] **Step 4: Commit**

```bash
git add supabase/migrations/20260507130000_taxonomy_curation_rpcs.sql
git commit -m "Migration: 5 RPCs for taxonomy curation (admin-guarded, cycle-checked)"
```

### Task 1.2: Write DB-side tests for the RPCs

**Files:**
- Create: `ingredients/tests/test_taxonomy_rpcs.py`

The conftest in `ingredients/tests/` auto-applies new migrations to `TEST_DB_URL` on session start. The tests stub `auth.uid()` per-test to simulate admin / non-admin / anonymous.

- [ ] **Step 1: Write the test scaffold**

```python
"""DB-side tests for the five taxonomy curation RPCs.

The functions guard on public.is_admin(), which reads
profiles.is_admin filtered by auth.uid(). The conftest stubs
auth.uid() to return null. Each test that needs an authenticated
admin overrides auth.uid() locally + inserts a profiles row.
"""
from __future__ import annotations

import os
import uuid

import psycopg
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("TEST_DB_URL") is None,
    reason="TEST_DB_URL not set; DB-integration tests skip",
)


@pytest.fixture
def db():
    url = os.environ["TEST_DB_URL"]
    with psycopg.connect(url, autocommit=False) as conn:
        # leave migrations applied; clean only the rows we'll touch
        conn.execute("delete from taxonomy_aliases")
        conn.execute("delete from taxonomy_edges")
        conn.execute("delete from taxonomy_provenance")
        conn.execute("delete from taxonomy_proposals")
        conn.execute("delete from recipe_ingredients")
        conn.execute("delete from taxonomy_nodes")
        conn.execute("delete from profiles")
        conn.execute("delete from auth.users")
        conn.commit()
        yield conn


def _become(conn: psycopg.Connection, *, admin: bool) -> uuid.UUID:
    """Insert an auth.users + profiles row and rewire auth.uid() to it."""
    uid = uuid.uuid4()
    conn.execute(
        "insert into auth.users (id, email) values (%s, %s)",
        (uid, f"{uid}@test"),
    )
    conn.execute(
        "insert into profiles (id, is_admin) values (%s, %s)",
        (uid, admin),
    )
    conn.execute(
        f"create or replace function auth.uid() returns uuid "
        f"language sql stable as $$ select '{uid}'::uuid $$"
    )
    conn.commit()
    return uid


def _become_anon(conn: psycopg.Connection) -> None:
    conn.execute(
        "create or replace function auth.uid() returns uuid "
        "language sql stable as $$ select null::uuid $$"
    )
    conn.commit()
```

- [ ] **Step 2: Add tests for create_taxonomy_node**

Append to `ingredients/tests/test_taxonomy_rpcs.py`:

```python
def test_create_inserts_node_edge_aliases(db):
    _become(db, admin=True)
    db.execute(
        "insert into taxonomy_nodes (id, slug, display_name) values (1, 'amari', 'amari')"
    )
    db.commit()

    new_id = db.execute(
        "select create_taxonomy_node(%s, %s, %s, %s, %s, %s, %s, %s)",
        (1, "campari", "Campari", "brand", "modifier", True, False, ["campari aperitivo"]),
    ).fetchone()[0]
    db.commit()

    row = db.execute(
        "select slug, display_name, node_kind, default_role, "
        "is_cluster_node, is_defining_garnish from taxonomy_nodes where id = %s",
        (new_id,),
    ).fetchone()
    assert row == ("campari", "Campari", "brand", "modifier", True, False)
    assert db.execute(
        "select count(*) from taxonomy_edges where parent_id = 1 and child_id = %s",
        (new_id,),
    ).fetchone()[0] == 1
    assert sorted(
        r[0] for r in db.execute(
            "select alias from taxonomy_aliases where node_id = %s", (new_id,)
        ).fetchall()
    ) == ["campari aperitivo"]


def test_create_rejects_non_admin(db):
    _become(db, admin=False)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute(
            "select create_taxonomy_node(%s, %s, %s, %s, %s, %s, %s, %s)",
            (None, "x", "X", None, None, False, False, []),
        )


def test_create_rejects_anonymous(db):
    _become_anon(db)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute(
            "select create_taxonomy_node(%s, %s, %s, %s, %s, %s, %s, %s)",
            (None, "x", "X", None, None, False, False, []),
        )
```

- [ ] **Step 3: Add tests for update_taxonomy_node**

```python
def test_update_patches_only_listed_keys(db):
    _become(db, admin=True)
    db.execute(
        "insert into taxonomy_nodes (id, slug, display_name, node_kind, default_role, "
        "is_cluster_node, is_defining_garnish) values "
        "(1, 'campari', 'Campari', 'brand', 'modifier', true, false)"
    )
    db.commit()

    db.execute(
        "select update_taxonomy_node(%s, %s::jsonb)",
        (1, '{"display_name": "Campari Aperitivo"}'),
    )
    db.commit()

    row = db.execute(
        "select slug, display_name, node_kind, default_role, "
        "is_cluster_node, is_defining_garnish from taxonomy_nodes where id = 1"
    ).fetchone()
    # Only display_name changed.
    assert row == ("campari", "Campari Aperitivo", "brand", "modifier", True, False)


def test_update_replaces_aliases_when_key_present(db):
    _become(db, admin=True)
    db.execute(
        "insert into taxonomy_nodes (id, slug, display_name) values (1, 'campari', 'Campari')"
    )
    db.execute(
        "insert into taxonomy_aliases (alias, node_id) values ('old1', 1), ('old2', 1)"
    )
    db.commit()

    db.execute(
        "select update_taxonomy_node(%s, %s::jsonb)",
        (1, '{"aliases": ["new1", "new2", "new3"]}'),
    )
    db.commit()

    aliases = sorted(
        r[0] for r in db.execute(
            "select alias from taxonomy_aliases where node_id = 1"
        ).fetchall()
    )
    assert aliases == ["new1", "new2", "new3"]


def test_update_clears_aliases_with_empty_array(db):
    _become(db, admin=True)
    db.execute(
        "insert into taxonomy_nodes (id, slug, display_name) values (1, 'campari', 'Campari')"
    )
    db.execute("insert into taxonomy_aliases (alias, node_id) values ('old', 1)")
    db.commit()

    db.execute("select update_taxonomy_node(1, '{\"aliases\": []}'::jsonb)")
    db.commit()

    assert db.execute(
        "select count(*) from taxonomy_aliases where node_id = 1"
    ).fetchone()[0] == 0


def test_update_can_null_node_kind(db):
    _become(db, admin=True)
    db.execute(
        "insert into taxonomy_nodes (id, slug, display_name, node_kind) "
        "values (1, 'x', 'X', 'brand')"
    )
    db.commit()

    db.execute(
        "select update_taxonomy_node(1, '{\"node_kind\": null}'::jsonb)"
    )
    db.commit()

    assert db.execute(
        "select node_kind from taxonomy_nodes where id = 1"
    ).fetchone()[0] is None


def test_update_rejects_non_admin(db):
    _become(db, admin=False)
    db.execute(
        "insert into taxonomy_nodes (id, slug, display_name) values (1, 'x', 'X')"
    )
    db.commit()
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("select update_taxonomy_node(1, '{}'::jsonb)")
```

- [ ] **Step 4: Add tests for set_node_parents**

```python
def test_set_parents_replaces_edge_set(db):
    _become(db, admin=True)
    db.execute(
        "insert into taxonomy_nodes (id, slug, display_name) values "
        "(1,'a','A'),(2,'b','B'),(3,'c','C'),(4,'d','D')"
    )
    db.execute(
        "insert into taxonomy_edges (parent_id, child_id) values (1, 4), (2, 4)"
    )
    db.commit()

    db.execute("select set_node_parents(4, ARRAY[2, 3]::bigint[])")
    db.commit()

    parents = sorted(
        r[0] for r in db.execute(
            "select parent_id from taxonomy_edges where child_id = 4"
        ).fetchall()
    )
    assert parents == [2, 3]


def test_set_parents_rejects_self(db):
    _become(db, admin=True)
    db.execute(
        "insert into taxonomy_nodes (id, slug, display_name) values (1, 'a', 'A')"
    )
    db.commit()
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("select set_node_parents(1, ARRAY[1]::bigint[])")


def test_set_parents_rejects_descendant(db):
    _become(db, admin=True)
    # 1 → 2 → 3
    db.execute(
        "insert into taxonomy_nodes (id, slug, display_name) values "
        "(1,'a','A'),(2,'b','B'),(3,'c','C')"
    )
    db.execute(
        "insert into taxonomy_edges (parent_id, child_id) values (1, 2), (2, 3)"
    )
    db.commit()
    # Trying to make 3 a parent of 1 would create a cycle.
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("select set_node_parents(1, ARRAY[3]::bigint[])")


def test_set_parents_to_empty_clears(db):
    _become(db, admin=True)
    db.execute(
        "insert into taxonomy_nodes (id, slug, display_name) values "
        "(1,'a','A'),(2,'b','B')"
    )
    db.execute("insert into taxonomy_edges (parent_id, child_id) values (1, 2)")
    db.commit()

    db.execute("select set_node_parents(2, ARRAY[]::bigint[])")
    db.commit()

    assert db.execute(
        "select count(*) from taxonomy_edges where child_id = 2"
    ).fetchone()[0] == 0
```

- [ ] **Step 5: Add tests for delete_taxonomy_node + get_taxonomy_node_blockers**

```python
def test_delete_succeeds_when_no_blockers(db):
    _become(db, admin=True)
    db.execute(
        "insert into taxonomy_nodes (id, slug, display_name) values "
        "(1,'a','A'),(2,'b','B')"
    )
    db.execute("insert into taxonomy_edges (parent_id, child_id) values (1, 2)")
    db.execute("insert into taxonomy_aliases (alias, node_id) values ('x', 2)")
    db.commit()

    db.execute("select delete_taxonomy_node(2)")
    db.commit()

    assert db.execute(
        "select count(*) from taxonomy_nodes where id = 2"
    ).fetchone()[0] == 0
    # Cascade dropped the edge + alias.
    assert db.execute(
        "select count(*) from taxonomy_edges where child_id = 2"
    ).fetchone()[0] == 0
    assert db.execute(
        "select count(*) from taxonomy_aliases where node_id = 2"
    ).fetchone()[0] == 0


def test_delete_blocked_by_children(db):
    _become(db, admin=True)
    db.execute(
        "insert into taxonomy_nodes (id, slug, display_name) values "
        "(1,'a','A'),(2,'b','B')"
    )
    db.execute("insert into taxonomy_edges (parent_id, child_id) values (1, 2)")
    db.commit()
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        db.execute("select delete_taxonomy_node(1)")


def test_blockers_report_all_dimensions(db):
    _become(db, admin=True)
    db.execute(
        "insert into taxonomy_nodes (id, slug, display_name) values "
        "(1,'a','A'),(2,'b','B'),(3,'c','C')"
    )
    db.execute(
        "insert into taxonomy_edges (parent_id, child_id) values (1, 2), (1, 3)"
    )
    db.execute("insert into taxonomy_aliases (alias, node_id) values ('x', 1)")
    db.commit()

    blockers = db.execute(
        "select get_taxonomy_node_blockers(1)"
    ).fetchone()[0]
    assert blockers["children"] == 2
    assert sorted(c["display_name"] for c in blockers["child_names"]) == ["B", "C"]
    assert blockers["aliases"] == 1
    assert blockers["parents"] == 0
    assert blockers["recipe_ingredients"] == 0
```

- [ ] **Step 6: Run the new tests**

From the devcontainer, sourcing parent `.env` (per the worktree-tests memory):

```bash
set -a && source /workspaces/spiritolo/.env && set +a
cd /workspaces/spiritolo/.claude/worktrees/claude+taxonomy-curation-ui/ingredients && uv run pytest tests/test_taxonomy_rpcs.py -v
```

Expected: all tests in this file pass; pre-existing tests are unaffected.

- [ ] **Step 7: Commit**

```bash
git add ingredients/tests/test_taxonomy_rpcs.py
git commit -m "Tests: taxonomy curation RPCs (admin guard, cycle, blockers)"
```

---

## Phase 2 — Web RPC client + zod schemas + cycle helper

### Task 2.1: zod schemas for the four write paths

**Files:**
- Create: `web/src/components/taxonomy/schemas.ts`

- [ ] **Step 1: Write the schemas**

```ts
import { z } from 'zod';

// Allowed default_role values, derived from the role classifier in
// ingredients/src/ingredients/dedup/cluster.py + role_classifier.py.
export const DEFAULT_ROLE_OPTIONS = [
  'base_spirit',
  'modifier',
  'bitters',
  'citrus',
  'sweetener',
  'dilution',
  'wash',
  'garnish',
  'other',
] as const;

export const NODE_KIND_OPTIONS = ['brand', 'expression'] as const;

const slugSchema = z
  .string()
  .min(1, 'slug required')
  .regex(/^[a-z0-9_]+$/, 'slug must be lowercase letters, digits, underscores');

const displayNameSchema = z.string().min(1, 'display name required');
const aliasArraySchema = z.array(z.string().min(1)).default([]);

export const createChildSchema = z.object({
  display_name: displayNameSchema,
  slug: slugSchema,
  node_kind: z.enum(NODE_KIND_OPTIONS).nullable(),
  default_role: z.enum(DEFAULT_ROLE_OPTIONS).nullable(),
  is_cluster_node: z.boolean(),
  is_defining_garnish: z.boolean(),
  aliases: aliasArraySchema,
});
export type CreateChildInput = z.infer<typeof createChildSchema>;

// Inline-edit schemas — one per editor type. RHF forms use these per row.
export const updateDisplayNameSchema = z.object({ display_name: displayNameSchema });
export const updateSlugSchema = z.object({ slug: slugSchema });
export const updateNodeKindSchema = z.object({
  node_kind: z.enum(NODE_KIND_OPTIONS).nullable(),
});
export const updateDefaultRoleSchema = z.object({
  default_role: z.enum(DEFAULT_ROLE_OPTIONS).nullable(),
});
export const updateBoolSchema = z.object({ value: z.boolean() });
export const updateAliasesSchema = z.object({ aliases: aliasArraySchema });

export const setNodeParentsSchema = z.object({
  parent_ids: z.array(z.number().int().positive()),
});

// Slug auto-derivation from display name.
export function deriveSlug(displayName: string): string {
  return displayName
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');
}
```

- [ ] **Step 2: Commit**

```bash
git add web/src/components/taxonomy/schemas.ts
git commit -m "Add zod schemas + slug deriver for taxonomy curation forms"
```

### Task 2.2: RPC wrappers

**Files:**
- Create: `web/src/components/taxonomy/rpcs.ts`

- [ ] **Step 1: Write the wrappers**

```ts
import { supabase } from '../../supabase';
import type { CreateChildInput } from './schemas';

export type TaxonomyBlockers = {
  children: number;
  child_names: { id: number; display_name: string }[];
  parents: number;
  aliases: number;
  provenance: number;
  recipe_ingredients: number;
  taxonomy_proposals: number;
};

export class RpcError extends Error {
  constructor(message: string, public readonly cause: unknown) {
    super(message);
    this.name = 'RpcError';
  }
}

function unwrap<T>(data: T | null, error: { message: string } | null, op: string): T {
  if (error) throw new RpcError(`${op}: ${error.message}`, error);
  if (data === null) throw new RpcError(`${op}: empty response`, null);
  return data;
}

export async function getTaxonomyNodeBlockers(id: number): Promise<TaxonomyBlockers> {
  const { data, error } = await supabase.rpc('get_taxonomy_node_blockers', { p_id: id });
  return unwrap<TaxonomyBlockers>(data as TaxonomyBlockers, error, 'get_taxonomy_node_blockers');
}

export async function createTaxonomyNode(parentId: number, input: CreateChildInput): Promise<number> {
  const { data, error } = await supabase.rpc('create_taxonomy_node', {
    p_parent_id: parentId,
    p_slug: input.slug,
    p_display_name: input.display_name,
    p_node_kind: input.node_kind,
    p_default_role: input.default_role,
    p_is_cluster_node: input.is_cluster_node,
    p_is_defining_garnish: input.is_defining_garnish,
    p_aliases: input.aliases,
  });
  return unwrap<number>(data as number, error, 'create_taxonomy_node');
}

// Patch may contain any subset of: slug, display_name, node_kind,
// default_role, is_cluster_node, is_defining_garnish, aliases.
export async function updateTaxonomyNode(
  id: number,
  patch: Record<string, unknown>,
): Promise<void> {
  const { error } = await supabase.rpc('update_taxonomy_node', {
    p_id: id,
    p_patch: patch,
  });
  if (error) throw new RpcError(`update_taxonomy_node: ${error.message}`, error);
}

export async function setNodeParents(id: number, parentIds: number[]): Promise<void> {
  const { error } = await supabase.rpc('set_node_parents', {
    p_id: id,
    p_parent_ids: parentIds,
  });
  if (error) throw new RpcError(`set_node_parents: ${error.message}`, error);
}

export async function deleteTaxonomyNode(id: number): Promise<void> {
  const { error } = await supabase.rpc('delete_taxonomy_node', { p_id: id });
  if (error) throw new RpcError(`delete_taxonomy_node: ${error.message}`, error);
}
```

- [ ] **Step 2: Commit**

```bash
git add web/src/components/taxonomy/rpcs.ts
git commit -m "Add typed RPC wrappers for taxonomy curation"
```

### Task 2.3: Cycle reachability helper

**Files:**
- Create: `web/src/components/taxonomy/cycle.ts`
- Create: `web/src/components/taxonomy/cycle.test.ts`

- [ ] **Step 1: Write the failing tests**

```ts
// web/src/components/taxonomy/cycle.test.ts
import { describe, it, expect } from 'vitest';
import { descendantsOf } from './cycle';
import type { TaxonomyViewRow } from './shapeData';

function row(id: number, child_ids: number[] = []): TaxonomyViewRow {
  return {
    id, slug: `n${id}`, display_name: `N${id}`,
    node_kind: null, default_role: null,
    is_cluster_node: false, is_defining_garnish: false,
    parent_ids: [], child_ids, aliases: [], recipe_count: 0,
  };
}

describe('descendantsOf', () => {
  it('returns empty set for leaf node', () => {
    const rows = [row(1), row(2)];
    expect(descendantsOf(1, rows)).toEqual(new Set());
  });

  it('returns immediate children', () => {
    const rows = [row(1, [2, 3]), row(2), row(3)];
    expect(descendantsOf(1, rows)).toEqual(new Set([2, 3]));
  });

  it('returns transitive descendants', () => {
    const rows = [row(1, [2]), row(2, [3]), row(3, [4]), row(4)];
    expect(descendantsOf(1, rows)).toEqual(new Set([2, 3, 4]));
  });

  it('handles diamond (descendant reachable via two paths)', () => {
    const rows = [row(1, [2, 3]), row(2, [4]), row(3, [4]), row(4)];
    expect(descendantsOf(1, rows)).toEqual(new Set([2, 3, 4]));
  });

  it('does not include the seed node itself', () => {
    const rows = [row(1, [2]), row(2, [1])]; // would-be cycle in data; defensive
    const got = descendantsOf(1, rows);
    expect(got.has(1)).toBe(false);
    expect(got.has(2)).toBe(true);
  });
});
```

- [ ] **Step 2: Run, expect FAIL ("Cannot find module './cycle'")**

```bash
cd web && npm test -- --run cycle.test.ts
```

- [ ] **Step 3: Implement cycle.ts**

```ts
import type { TaxonomyViewRow } from './shapeData';

/**
 * Walk child_ids transitively from `seedId` and return the set of
 * descendants (excluding the seed). Used by the parent-edit overlay
 * to grey out nodes that would create a cycle if added as a parent.
 *
 * Defensive against pre-existing cycles in the data: we mark visited
 * ids and stop walking through them, so a malformed graph doesn't
 * loop forever.
 */
export function descendantsOf(seedId: number, rows: TaxonomyViewRow[]): Set<number> {
  const byId = new Map(rows.map((r) => [r.id, r]));
  const out = new Set<number>();
  const stack: number[] = [seedId];
  const seen = new Set<number>([seedId]);
  while (stack.length > 0) {
    const cur = stack.pop()!;
    const node = byId.get(cur);
    if (!node) continue;
    for (const childId of node.child_ids) {
      if (seen.has(childId)) continue;
      seen.add(childId);
      out.add(childId);
      stack.push(childId);
    }
  }
  return out;
}
```

- [ ] **Step 4: Run tests, expect PASS**

```bash
cd web && npm test -- --run cycle.test.ts
```

- [ ] **Step 5: Commit**

```bash
git add web/src/components/taxonomy/cycle.ts web/src/components/taxonomy/cycle.test.ts
git commit -m "Add descendantsOf helper for client-side cycle prevention"
```

---

## Phase 3 — Inline-edit primitives

### Task 3.1: EditableField component

A single component that handles all three editor types (text / dropdown / toggle). The chip editor for `aliases` is a separate component (Task 3.2) because chip semantics differ enough.

**Files:**
- Create: `web/src/components/taxonomy/EditableField.tsx`
- Create: `web/src/components/taxonomy/EditableField.test.tsx`

- [ ] **Step 1: Write failing tests**

```tsx
// web/src/components/taxonomy/EditableField.test.tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { EditableField } from './EditableField';

describe('EditableField — text', () => {
  it('shows pencil on hover and value when not editing', async () => {
    const user = userEvent.setup();
    render(
      <EditableField
        label="DISPLAY NAME"
        kind="text"
        value="Campari"
        onSave={vi.fn()}
      />,
    );
    expect(screen.getByText('Campari')).toBeInTheDocument();
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    await user.hover(screen.getByText('Campari'));
    expect(screen.getByRole('button', { name: /edit/i })).toBeInTheDocument();
  });

  it('opens textbox on pencil click, prefilled with value', async () => {
    const user = userEvent.setup();
    render(<EditableField label="X" kind="text" value="hello" onSave={vi.fn()} />);
    await user.hover(screen.getByText('hello'));
    await user.click(screen.getByRole('button', { name: /edit/i }));
    const input = screen.getByRole('textbox') as HTMLInputElement;
    expect(input.value).toBe('hello');
  });

  it('Enter calls onSave with new value, then exits edit mode', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<EditableField label="X" kind="text" value="hello" onSave={onSave} />);
    await user.hover(screen.getByText('hello'));
    await user.click(screen.getByRole('button', { name: /edit/i }));
    const input = screen.getByRole('textbox');
    await user.clear(input);
    await user.type(input, 'world{Enter}');
    expect(onSave).toHaveBeenCalledWith('world');
  });

  it('Esc cancels and reverts', async () => {
    const onSave = vi.fn();
    const user = userEvent.setup();
    render(<EditableField label="X" kind="text" value="hello" onSave={onSave} />);
    await user.hover(screen.getByText('hello'));
    await user.click(screen.getByRole('button', { name: /edit/i }));
    const input = screen.getByRole('textbox');
    await user.clear(input);
    await user.type(input, 'world');
    await user.keyboard('{Escape}');
    expect(onSave).not.toHaveBeenCalled();
    expect(screen.getByText('hello')).toBeInTheDocument();
  });

  it('reverts and surfaces error if onSave rejects', async () => {
    const onSave = vi.fn().mockRejectedValue(new Error('boom'));
    const onError = vi.fn();
    const user = userEvent.setup();
    render(
      <EditableField label="X" kind="text" value="hello" onSave={onSave} onError={onError} />,
    );
    await user.hover(screen.getByText('hello'));
    await user.click(screen.getByRole('button', { name: /edit/i }));
    await user.clear(screen.getByRole('textbox'));
    await user.type(screen.getByRole('textbox'), 'world{Enter}');
    expect(onError).toHaveBeenCalled();
    expect(screen.getByText('hello')).toBeInTheDocument();
  });
});

describe('EditableField — dropdown', () => {
  it('selecting an option commits immediately', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(
      <EditableField
        label="NODE KIND"
        kind="dropdown"
        value="brand"
        options={[
          { value: '', label: '(none)' },
          { value: 'brand', label: 'brand' },
          { value: 'expression', label: 'expression' },
        ]}
        onSave={onSave}
      />,
    );
    await user.hover(screen.getByText('brand'));
    await user.click(screen.getByRole('button', { name: /edit/i }));
    await user.selectOptions(screen.getByRole('combobox'), 'expression');
    expect(onSave).toHaveBeenCalledWith('expression');
  });
});

describe('EditableField — toggle', () => {
  it('clicking the toggle commits the new boolean immediately', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(
      <EditableField
        label="CLUSTER"
        kind="toggle"
        value={false}
        onSave={onSave}
      />,
    );
    await user.click(screen.getByRole('switch'));
    expect(onSave).toHaveBeenCalledWith(true);
  });
});
```

- [ ] **Step 2: Run, expect FAIL ("Cannot find module './EditableField'")**

```bash
cd web && npm test -- --run EditableField.test.tsx
```

- [ ] **Step 3: Implement EditableField.tsx**

```tsx
import { useEffect, useRef, useState } from 'react';

type Props =
  | TextProps
  | DropdownProps
  | ToggleProps;

interface BaseProps {
  label: string;
  onError?: (e: unknown) => void;
}

interface TextProps extends BaseProps {
  kind: 'text';
  value: string;
  onSave: (next: string) => Promise<void> | void;
}

interface DropdownProps extends BaseProps {
  kind: 'dropdown';
  value: string;
  options: { value: string; label: string }[];
  onSave: (next: string) => Promise<void> | void;
}

interface ToggleProps extends BaseProps {
  kind: 'toggle';
  value: boolean;
  onSave: (next: boolean) => Promise<void> | void;
}

const ROW_STYLE: React.CSSProperties = {
  position: 'relative',
  padding: '2px 6px',
  border: '1px solid transparent',
  borderRadius: 3,
};
const ROW_HOVER_STYLE: React.CSSProperties = {
  borderColor: '#8b6f3a',
};

export function EditableField(props: Props) {
  if (props.kind === 'text') return <TextField {...props} />;
  if (props.kind === 'dropdown') return <DropdownField {...props} />;
  return <ToggleField {...props} />;
}

function TextField({ label, value, onSave, onError }: TextProps) {
  const [hover, setHover] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!editing) setDraft(value);
  }, [value, editing]);

  useEffect(() => {
    if (editing) inputRef.current?.select();
  }, [editing]);

  async function commit(next: string) {
    setEditing(false);
    if (next === value) return;
    try {
      await onSave(next);
    } catch (e) {
      setDraft(value);
      onError?.(e);
    }
  }

  if (editing) {
    return (
      <div style={ROW_STYLE} aria-label={label}>
        <input
          ref={inputRef}
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') void commit(draft);
            else if (e.key === 'Escape') {
              setDraft(value);
              setEditing(false);
            }
          }}
          onBlur={() => void commit(draft)}
          style={{ width: '100%', font: 'inherit', color: 'inherit', background: 'transparent', border: 'none' }}
        />
      </div>
    );
  }

  return (
    <div
      style={{ ...ROW_STYLE, ...(hover ? ROW_HOVER_STYLE : {}) }}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      aria-label={label}
    >
      {value}
      {hover && (
        <button
          type="button"
          aria-label={`edit ${label}`}
          onClick={() => setEditing(true)}
          style={{
            position: 'absolute', right: 4, top: '50%', transform: 'translateY(-50%)',
            background: 'transparent', border: 'none', cursor: 'pointer', color: '#8b6f3a',
            padding: 0, lineHeight: 1, fontSize: 13,
          }}
        >
          ✎
        </button>
      )}
    </div>
  );
}

function DropdownField({ label, value, options, onSave, onError }: DropdownProps) {
  const [hover, setHover] = useState(false);
  const [editing, setEditing] = useState(false);

  async function commit(next: string) {
    setEditing(false);
    if (next === value) return;
    try {
      await onSave(next);
    } catch (e) {
      onError?.(e);
    }
  }

  if (editing) {
    return (
      <div style={ROW_STYLE} aria-label={label}>
        <select
          autoFocus
          defaultValue={value}
          onChange={(e) => void commit(e.target.value)}
          onBlur={() => setEditing(false)}
          onKeyDown={(e) => { if (e.key === 'Escape') setEditing(false); }}
          style={{ font: 'inherit', color: 'inherit', background: 'transparent' }}
        >
          {options.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </div>
    );
  }

  return (
    <div
      style={{ ...ROW_STYLE, ...(hover ? ROW_HOVER_STYLE : {}) }}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      aria-label={label}
    >
      {options.find((o) => o.value === value)?.label ?? value}
      {hover && (
        <button
          type="button"
          aria-label={`edit ${label}`}
          onClick={() => setEditing(true)}
          style={{
            position: 'absolute', right: 4, top: '50%', transform: 'translateY(-50%)',
            background: 'transparent', border: 'none', cursor: 'pointer', color: '#8b6f3a',
            padding: 0, lineHeight: 1, fontSize: 13,
          }}
        >
          ✎
        </button>
      )}
    </div>
  );
}

function ToggleField({ label, value, onSave, onError }: ToggleProps) {
  const [pending, setPending] = useState(false);
  return (
    <div style={ROW_STYLE} aria-label={label}>
      <button
        type="button"
        role="switch"
        aria-checked={value}
        disabled={pending}
        onClick={async () => {
          setPending(true);
          try {
            await onSave(!value);
          } catch (e) {
            onError?.(e);
          } finally {
            setPending(false);
          }
        }}
        style={{
          width: 28, height: 14, borderRadius: 7, position: 'relative',
          background: value ? '#b8924d' : '#d4c8a8',
          border: 'none', cursor: 'pointer',
        }}
      >
        <span
          style={{
            position: 'absolute',
            left: value ? 14 : 1,
            top: 1,
            width: 12, height: 12, borderRadius: '50%',
            background: 'white',
            transition: 'left 100ms',
          }}
        />
      </button>
    </div>
  );
}
```

- [ ] **Step 4: Run tests, expect PASS**

```bash
cd web && npm test -- --run EditableField.test.tsx
```

- [ ] **Step 5: Commit**

```bash
git add web/src/components/taxonomy/EditableField.tsx web/src/components/taxonomy/EditableField.test.tsx
git commit -m "Add EditableField inline-edit primitive (text / dropdown / toggle)"
```

### Task 3.2: AliasChipEditor component

**Files:**
- Create: `web/src/components/taxonomy/AliasChipEditor.tsx`
- Create: `web/src/components/taxonomy/AliasChipEditor.test.tsx`

- [ ] **Step 1: Write failing tests**

```tsx
// web/src/components/taxonomy/AliasChipEditor.test.tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AliasChipEditor } from './AliasChipEditor';

describe('AliasChipEditor', () => {
  it('renders chips and shows pencil on hover when not editing', async () => {
    const user = userEvent.setup();
    render(<AliasChipEditor value={['a', 'b']} onSave={vi.fn()} />);
    expect(screen.getByText('a')).toBeInTheDocument();
    expect(screen.getByText('b')).toBeInTheDocument();
    await user.hover(screen.getByText('a'));
    expect(screen.getByRole('button', { name: /edit aliases/i })).toBeInTheDocument();
  });

  it('add chip via Enter, remove via × — does not save until blur', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<AliasChipEditor value={['a']} onSave={onSave} />);
    await user.hover(screen.getByText('a'));
    await user.click(screen.getByRole('button', { name: /edit aliases/i }));
    const input = screen.getByPlaceholderText(/add alias/i);
    await user.type(input, 'b{Enter}');
    expect(screen.getByText('b')).toBeInTheDocument();
    expect(onSave).not.toHaveBeenCalled();
    await user.click(screen.getByLabelText(/remove a/i));
    expect(onSave).not.toHaveBeenCalled();
    // Move focus outside the editor to trigger blur-save
    input.blur();
    // Allow microtask to flush
    await Promise.resolve();
    expect(onSave).toHaveBeenCalledWith(['b']);
  });

  it('Esc discards staged chip changes', async () => {
    const onSave = vi.fn();
    const user = userEvent.setup();
    render(<AliasChipEditor value={['a']} onSave={onSave} />);
    await user.hover(screen.getByText('a'));
    await user.click(screen.getByRole('button', { name: /edit aliases/i }));
    await user.type(screen.getByPlaceholderText(/add alias/i), 'b{Enter}');
    await user.keyboard('{Escape}');
    expect(onSave).not.toHaveBeenCalled();
    expect(screen.queryByText('b')).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run, expect FAIL**

```bash
cd web && npm test -- --run AliasChipEditor.test.tsx
```

- [ ] **Step 3: Implement AliasChipEditor.tsx**

```tsx
import { useEffect, useRef, useState } from 'react';

interface Props {
  value: string[];
  onSave: (next: string[]) => Promise<void> | void;
  onError?: (e: unknown) => void;
}

const ROW_STYLE: React.CSSProperties = {
  position: 'relative',
  padding: '2px 6px',
  border: '1px solid transparent',
  borderRadius: 3,
  display: 'flex',
  flexWrap: 'wrap',
  gap: 4,
  alignItems: 'center',
};
const HOVER_STYLE: React.CSSProperties = { borderColor: '#8b6f3a' };

const CHIP_STYLE: React.CSSProperties = {
  background: '#faf5e6',
  border: '1px solid #b8924d',
  borderRadius: 10,
  padding: '1px 6px',
  fontSize: 11,
  display: 'inline-flex',
  alignItems: 'center',
  gap: 4,
};

export function AliasChipEditor({ value, onSave, onError }: Props) {
  const [hover, setHover] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<string[]>(value);
  const [input, setInput] = useState('');
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!editing) setDraft(value);
  }, [value, editing]);

  useEffect(() => {
    if (editing) inputRef.current?.focus();
  }, [editing]);

  async function commit() {
    setEditing(false);
    setInput('');
    if (arraysEqual(draft, value)) return;
    try {
      await onSave(draft);
    } catch (e) {
      setDraft(value);
      onError?.(e);
    }
  }

  function addCurrent() {
    const trimmed = input.trim();
    if (trimmed === '' || draft.includes(trimmed)) return;
    setDraft([...draft, trimmed]);
    setInput('');
  }

  function remove(i: number) {
    setDraft(draft.filter((_, idx) => idx !== i));
  }

  if (editing) {
    return (
      <div
        ref={containerRef}
        style={{ ...ROW_STYLE, ...HOVER_STYLE }}
        onBlur={(e) => {
          // Only save if focus is leaving the whole editor
          if (containerRef.current && !containerRef.current.contains(e.relatedTarget as Node | null)) {
            void commit();
          }
        }}
      >
        {draft.map((a, i) => (
          <span key={`${a}-${i}`} style={CHIP_STYLE}>
            {a}
            <button
              type="button"
              aria-label={`remove ${a}`}
              onClick={() => remove(i)}
              style={{ background: 'transparent', border: 'none', color: '#c44', cursor: 'pointer', fontSize: 12, padding: 0, lineHeight: 1 }}
            >×</button>
          </span>
        ))}
        <input
          ref={inputRef}
          type="text"
          value={input}
          placeholder="+ add alias"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              addCurrent();
            } else if (e.key === 'Escape') {
              setDraft(value);
              setInput('');
              setEditing(false);
            }
          }}
          style={{ font: 'inherit', color: 'inherit', background: 'transparent', border: 'none', flex: '1 1 80px', minWidth: 80 }}
        />
      </div>
    );
  }

  return (
    <div
      style={{ ...ROW_STYLE, ...(hover ? HOVER_STYLE : {}) }}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      {value.length === 0
        ? <span style={{ fontStyle: 'italic', opacity: 0.6 }}>—</span>
        : value.map((a) => <span key={a} style={CHIP_STYLE}>{a}</span>)}
      {hover && (
        <button
          type="button"
          aria-label="edit aliases"
          onClick={() => setEditing(true)}
          style={{
            position: 'absolute', right: 4, top: 2,
            background: 'transparent', border: 'none', cursor: 'pointer',
            color: '#8b6f3a', padding: 0, lineHeight: 1, fontSize: 13,
          }}
        >✎</button>
      )}
    </div>
  );
}

function arraysEqual(a: string[], b: string[]) {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}
```

- [ ] **Step 4: Run tests, expect PASS**

```bash
cd web && npm test -- --run AliasChipEditor.test.tsx
```

- [ ] **Step 5: Commit**

```bash
git add web/src/components/taxonomy/AliasChipEditor.tsx web/src/components/taxonomy/AliasChipEditor.test.tsx
git commit -m "Add AliasChipEditor (chips + RHF-local state, save on blur)"
```

---

## Phase 4 — NodeCard refactor

The card adds inline editors for the existing fields, two new sections (PARENTS / CHILDREN), and a Delete link in pinned mode. We pass three callbacks (`onEditField`, `onEditParents`, `onDelete`) so the parent owns the actual mutation flow — the card stays declarative.

### Task 4.1: Extend NodeCard with edit hooks + new sections

**Files:**
- Modify: `web/src/components/taxonomy/NodeCard.tsx`
- Modify: `web/src/components/taxonomy/NodeCard.test.tsx`

- [ ] **Step 1: Add tests for the new behaviors**

Append to `web/src/components/taxonomy/NodeCard.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { NodeCard } from './NodeCard';
import type { TaxonomyNode } from './shapeData';

function node(over: Partial<TaxonomyNode> = {}): TaxonomyNode {
  return {
    id: 42, slug: 'campari', display_name: 'Campari',
    node_kind: 'brand', default_role: 'modifier',
    is_cluster_node: true, is_defining_garnish: false,
    parent_ids: [17, 84], child_ids: [], aliases: ['campari aperitivo'],
    recipe_count: 0,
    labelW: 60, labelH: 11,
    ...over,
  };
}

describe('NodeCard — pinned mode editing', () => {
  it('renders PARENTS section with each parent name #id', () => {
    render(
      <MemoryRouter>
        <NodeCard
          node={node()}
          mode="pinned"
          onDismiss={vi.fn()}
          onEditField={vi.fn()}
          onEditParents={vi.fn()}
          onDelete={vi.fn()}
          parentLookup={new Map([
            [17, { id: 17, display_name: 'Amari' }],
            [84, { id: 84, display_name: 'Bitter Aperitif' }],
          ])}
        />
      </MemoryRouter>,
    );
    expect(screen.getByText(/PARENTS · 2/)).toBeInTheDocument();
    expect(screen.getByText(/Amari/)).toBeInTheDocument();
    expect(screen.getByText('#17')).toBeInTheDocument();
  });

  it('clicking pencil on PARENTS section calls onEditParents', async () => {
    const onEditParents = vi.fn();
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <NodeCard
          node={node()}
          mode="pinned"
          onDismiss={vi.fn()}
          onEditField={vi.fn()}
          onEditParents={onEditParents}
          onDelete={vi.fn()}
          parentLookup={new Map([[17, { id: 17, display_name: 'Amari' }], [84, { id: 84, display_name: 'Bitter Aperitif' }]])}
        />
      </MemoryRouter>,
    );
    await user.hover(screen.getByText(/PARENTS · 2/));
    await user.click(screen.getByRole('button', { name: /edit parents/i }));
    expect(onEditParents).toHaveBeenCalledWith(42);
  });

  it('hover mode hides Delete link and edit affordances', () => {
    render(
      <MemoryRouter>
        <NodeCard
          node={node()}
          mode="hover"
          onDismiss={vi.fn()}
        />
      </MemoryRouter>,
    );
    expect(screen.queryByRole('button', { name: /delete/i })).not.toBeInTheDocument();
  });

  it('clicking Delete in pinned mode calls onDelete with node id', async () => {
    const onDelete = vi.fn();
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <NodeCard
          node={node()}
          mode="pinned"
          onDismiss={vi.fn()}
          onEditField={vi.fn()}
          onEditParents={vi.fn()}
          onDelete={onDelete}
        />
      </MemoryRouter>,
    );
    await user.click(screen.getByRole('button', { name: /delete node/i }));
    expect(onDelete).toHaveBeenCalledWith(42);
  });
});
```

- [ ] **Step 2: Run, expect FAIL**

```bash
cd web && npm test -- --run NodeCard.test.tsx
```

Expected: new tests fail because `onEditField` / `onEditParents` / `onDelete` / `parentLookup` props don't exist yet.

- [ ] **Step 3: Wire the new props and sections in NodeCard.tsx**

This is a focused edit, not a full rewrite. Update the `Props` interface, replace the static `PropertyGrid` cells with `<EditableField>` / `<AliasChipEditor>` instances (only in pinned mode), and add the PARENTS / CHILDREN / Delete blocks below the existing content.

In `web/src/components/taxonomy/NodeCard.tsx`:

```tsx
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import type { TaxonomyNode } from './shapeData';
import { TX_BROWN_INK, TX_BROWN_MID, TX_FRAME_EDGE } from './palette';
import { supabase } from '../../supabase';
import { EditableField } from './EditableField';
import { AliasChipEditor } from './AliasChipEditor';
import { NODE_KIND_OPTIONS, DEFAULT_ROLE_OPTIONS } from './schemas';

export type NodeCardMode = 'hover' | 'pinned';

export type FieldKey =
  | 'display_name' | 'slug'
  | 'node_kind' | 'default_role'
  | 'is_cluster_node' | 'is_defining_garnish'
  | 'aliases';

export type ParentLookup = Map<number, { id: number; display_name: string }>;

interface Props {
  node: TaxonomyNode;
  mode: NodeCardMode;
  onDismiss: () => void;
  // Curator hooks (only meaningful in pinned mode; ignored in hover)
  onEditField?: (id: number, key: FieldKey, next: unknown) => Promise<void>;
  onEditParents?: (id: number) => void;
  onDelete?: (id: number) => void;
  parentLookup?: ParentLookup;
}
```

**Where the changes go in the existing file** (so the PARENTS / CHILDREN / Delete additions don't disrupt the existing RECIPES block):

1. The existing `<PropertyGrid>` + the `ALIASES` heading + alias text-list together form the read-only "data fields" block. Wrap **only that block** in the conditional below.
2. The existing `RECIPES` heading and the recipe `<ul>` underneath stay exactly where they are.
3. Insert PARENTS / CHILDREN sections **between** the data-fields block and the RECIPES heading.
4. Insert the Delete link at the very bottom of the card (after the recipes scroll region).

The conditional render replacing the data-fields block:

```tsx
{mode === 'pinned' && onEditField ? (
  <>
    <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', padding: '2px 6px' }}>
      <span style={{ opacity: 0.7, fontSize: 10 }}>ID</span>
      <span style={{ ...monoStyle }}>{node.id}</span>
    </div>
    <EditableField
      label="DISPLAY NAME"
      kind="text"
      value={node.display_name}
      onSave={(v) => onEditField(node.id, 'display_name', v)}
    />
    <EditableField
      label="SLUG"
      kind="text"
      value={node.slug}
      onSave={(v) => onEditField(node.id, 'slug', v)}
    />
    <EditableField
      label="NODE KIND"
      kind="dropdown"
      value={node.node_kind ?? ''}
      options={[
        { value: '', label: '(none)' },
        ...NODE_KIND_OPTIONS.map((v) => ({ value: v, label: v })),
      ]}
      onSave={(v) => onEditField(node.id, 'node_kind', v === '' ? null : v)}
    />
    <EditableField
      label="DEFAULT ROLE"
      kind="dropdown"
      value={node.default_role ?? ''}
      options={[
        { value: '', label: '(none)' },
        ...DEFAULT_ROLE_OPTIONS.map((v) => ({ value: v, label: v })),
      ]}
      onSave={(v) => onEditField(node.id, 'default_role', v === '' ? null : v)}
    />
    <EditableField
      label="CLUSTER"
      kind="toggle"
      value={node.is_cluster_node}
      onSave={(v) => onEditField(node.id, 'is_cluster_node', v)}
    />
    <EditableField
      label="DEFINING GARNISH"
      kind="toggle"
      value={node.is_defining_garnish}
      onSave={(v) => onEditField(node.id, 'is_defining_garnish', v)}
    />
    <AliasChipEditor
      value={node.aliases}
      onSave={(v) => onEditField(node.id, 'aliases', v)}
    />
  </>
) : (
  // Hover mode (or pinned without onEditField): keep the original read-only
  // PropertyGrid + ALIASES line — i.e. leave the existing JSX block in place.
  <>
    <PropertyGrid>
      <Cell label="ID"><span style={monoStyle}>{node.id}</span></Cell>
      <Cell label="Slug">
        <span style={{ ...monoStyle, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'block' }}>
          {node.slug}
        </span>
      </Cell>
      <Cell label="Node kind">{node.node_kind ?? '—'}</Cell>
      <Cell label="Default ingredient role">{node.default_role ?? '—'}</Cell>
      <Cell label="Clustering node">{yesNo(node.is_cluster_node)}</Cell>
      <Cell label="Defining garnish">{yesNo(node.is_defining_garnish)}</Cell>
    </PropertyGrid>
    <div className="tx-card__heading" style={{ marginTop: 10 }}>
      ALIASES <span style={{ fontStyle: 'italic', color: TX_FRAME_EDGE }}>({node.aliases.length})</span>
    </div>
    <div>{node.aliases.length > 0 ? node.aliases.join(', ') : '—'}</div>
  </>
)}
```

Add PARENTS section (only in pinned mode), below the editable grid:

```tsx
{mode === 'pinned' && (
  <ParentsSection
    parentIds={node.parent_ids}
    parentLookup={parentLookup ?? new Map()}
    onEdit={onEditParents ? () => onEditParents(node.id) : undefined}
  />
)}
```

Where `ParentsSection` is a small local component (defined at the bottom of the file):

```tsx
function ParentsSection({
  parentIds, parentLookup, onEdit,
}: {
  parentIds: number[];
  parentLookup: ParentLookup;
  onEdit?: () => void;
}) {
  const [hover, setHover] = useState(false);
  return (
    <div
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        position: 'relative',
        padding: '6px 8px',
        marginTop: 10,
        border: hover ? '1px solid #8b6f3a' : '1px solid transparent',
        borderRadius: 3,
      }}
    >
      <div className="tx-card__heading">
        PARENTS · {parentIds.length}
      </div>
      {parentIds.map((pid) => {
        const p = parentLookup.get(pid);
        return (
          <div key={pid} style={{ padding: '2px 0' }}>
            {p?.display_name ?? `(${pid})`}{' '}
            <span style={{ fontFamily: 'ui-monospace, monospace', opacity: 0.5 }}>
              #{pid}
            </span>
          </div>
        );
      })}
      {hover && onEdit && (
        <button
          type="button"
          aria-label="edit parents"
          onClick={onEdit}
          style={{
            position: 'absolute', top: 6, right: 8,
            background: 'transparent', border: 'none', cursor: 'pointer',
            color: '#8b6f3a', padding: 0, lineHeight: 1, fontSize: 13,
          }}
        >✎</button>
      )}
    </div>
  );
}
```

Add a CHILDREN section below PARENTS:

```tsx
{mode === 'pinned' && (
  <div style={{ padding: '6px 8px', marginTop: 6 }}>
    <div className="tx-card__heading">
      CHILDREN · {node.child_ids.length}{' '}
      <span style={{ fontStyle: 'italic', color: TX_FRAME_EDGE, fontSize: 9 }}>
        (use + on graph to add)
      </span>
    </div>
  </div>
)}
```

Add Delete link at the very bottom, only in pinned mode and only when `onDelete` is supplied:

```tsx
{mode === 'pinned' && onDelete && (
  <div style={{ padding: '8px 18px 14px', textAlign: 'right' }}>
    <button
      type="button"
      aria-label="delete node"
      onClick={() => onDelete(node.id)}
      style={{
        background: 'transparent', border: 'none', cursor: 'pointer',
        color: TX_BROWN_MID, opacity: 0.7,
        fontFamily: "'Cinzel', serif", fontSize: 10, letterSpacing: '0.18em',
        textTransform: 'uppercase',
      }}
    >Delete node</button>
  </div>
)}
```

- [ ] **Step 4: Run tests, expect PASS**

```bash
cd web && npm test -- --run NodeCard.test.tsx
```

- [ ] **Step 5: Commit**

```bash
git add web/src/components/taxonomy/NodeCard.tsx web/src/components/taxonomy/NodeCard.test.tsx
git commit -m "NodeCard: inline-editable fields + PARENTS / CHILDREN sections + delete link"
```

---

## Phase 5 — CreateChildModal

### Task 5.1: CreateChildModal with RHF + zod

**Files:**
- Create: `web/src/components/taxonomy/CreateChildModal.tsx`
- Create: `web/src/components/taxonomy/CreateChildModal.test.tsx`

- [ ] **Step 1: Write failing tests**

```tsx
// web/src/components/taxonomy/CreateChildModal.test.tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CreateChildModal } from './CreateChildModal';

const parent = { id: 42, display_name: 'Campari' };

describe('CreateChildModal', () => {
  it('renders title with parent name and id', () => {
    render(
      <CreateChildModal parent={parent} onCancel={vi.fn()} onCreate={vi.fn()} />,
    );
    expect(screen.getByText(/New child of Campari/i)).toBeInTheDocument();
    expect(screen.getByText(/#42/)).toBeInTheDocument();
  });

  it('auto-derives slug from display_name until slug is touched', async () => {
    const user = userEvent.setup();
    render(<CreateChildModal parent={parent} onCancel={vi.fn()} onCreate={vi.fn()} />);
    const dn = screen.getByLabelText(/display name/i);
    await user.type(dn, 'Aperol Spritz');
    const slug = screen.getByLabelText(/^slug/i) as HTMLInputElement;
    expect(slug.value).toBe('aperol_spritz');
    // Touch the slug — auto-derive should stop.
    await user.clear(slug);
    await user.type(slug, 'aperol_spritz_v2');
    await user.clear(dn);
    await user.type(dn, 'Other Name');
    expect(slug.value).toBe('aperol_spritz_v2');
  });

  it('rejects empty display_name', async () => {
    const onCreate = vi.fn();
    const user = userEvent.setup();
    render(<CreateChildModal parent={parent} onCancel={vi.fn()} onCreate={onCreate} />);
    await user.click(screen.getByRole('button', { name: /create/i }));
    expect(onCreate).not.toHaveBeenCalled();
    expect(screen.getByText(/display name required/i)).toBeInTheDocument();
  });

  it('CREATE calls onCreate with the form payload and parent id', async () => {
    const onCreate = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<CreateChildModal parent={parent} onCancel={vi.fn()} onCreate={onCreate} />);
    await user.type(screen.getByLabelText(/display name/i), 'Negroni');
    await user.click(screen.getByRole('button', { name: /create/i }));
    expect(onCreate).toHaveBeenCalledWith(42, expect.objectContaining({
      display_name: 'Negroni',
      slug: 'negroni',
      node_kind: null,
      default_role: null,
      is_cluster_node: false,
      is_defining_garnish: false,
      aliases: [],
    }));
  });

  it('CANCEL calls onCancel', async () => {
    const onCancel = vi.fn();
    const user = userEvent.setup();
    render(<CreateChildModal parent={parent} onCancel={onCancel} onCreate={vi.fn()} />);
    await user.click(screen.getByRole('button', { name: /cancel/i }));
    expect(onCancel).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run, expect FAIL**

```bash
cd web && npm test -- --run CreateChildModal.test.tsx
```

- [ ] **Step 3: Implement CreateChildModal.tsx**

```tsx
import { useEffect, useRef } from 'react';
import { useForm, Controller } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import {
  createChildSchema, deriveSlug,
  NODE_KIND_OPTIONS, DEFAULT_ROLE_OPTIONS,
  type CreateChildInput,
} from './schemas';
import { AliasChipEditor } from './AliasChipEditor';

interface Props {
  parent: { id: number; display_name: string };
  onCancel: () => void;
  onCreate: (parentId: number, input: CreateChildInput) => Promise<void> | void;
}

export function CreateChildModal({ parent, onCancel, onCreate }: Props) {
  const slugTouchedRef = useRef(false);

  const form = useForm<CreateChildInput>({
    resolver: zodResolver(createChildSchema),
    defaultValues: {
      display_name: '',
      slug: '',
      node_kind: null,
      default_role: null,
      is_cluster_node: false,
      is_defining_garnish: false,
      aliases: [],
    },
  });

  const dn = form.watch('display_name');
  useEffect(() => {
    if (slugTouchedRef.current) return;
    form.setValue('slug', deriveSlug(dn), { shouldValidate: false });
  }, [dn, form]);

  return (
    <ModalShell onBackdropClick={onCancel}>
      <h2 className="tx-modal__title">New child of {parent.display_name}</h2>
      <div className="tx-modal__subtitle">PARENT · {parent.display_name} (#{parent.id})</div>
      <form onSubmit={form.handleSubmit((v) => onCreate(parent.id, v))}>
        <Field label="DISPLAY NAME *" error={form.formState.errors.display_name?.message}>
          <input
            id="dn"
            aria-label="display name"
            {...form.register('display_name')}
          />
        </Field>
        <Field label="SLUG *" error={form.formState.errors.slug?.message}>
          <input
            id="slug"
            aria-label="slug"
            {...form.register('slug', {
              onChange: () => { slugTouchedRef.current = true; },
            })}
          />
        </Field>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
          <Field label="NODE KIND">
            <Controller
              control={form.control}
              name="node_kind"
              render={({ field }) => (
                <select
                  aria-label="node kind"
                  value={field.value ?? ''}
                  onChange={(e) => field.onChange(e.target.value === '' ? null : e.target.value)}
                >
                  <option value="">(none)</option>
                  {NODE_KIND_OPTIONS.map((v) => (
                    <option key={v} value={v}>{v}</option>
                  ))}
                </select>
              )}
            />
          </Field>
          <Field label="DEFAULT ROLE">
            <Controller
              control={form.control}
              name="default_role"
              render={({ field }) => (
                <select
                  aria-label="default role"
                  value={field.value ?? ''}
                  onChange={(e) => field.onChange(e.target.value === '' ? null : e.target.value)}
                >
                  <option value="">(none)</option>
                  {DEFAULT_ROLE_OPTIONS.map((v) => (
                    <option key={v} value={v}>{v}</option>
                  ))}
                </select>
              )}
            />
          </Field>
        </div>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginTop: 8 }}>
          <ToggleControl name="is_cluster_node" label="cluster" form={form} />
          <ToggleControl name="is_defining_garnish" label="garnish" form={form} />
        </div>
        <Field label="ALIASES">
          <Controller
            control={form.control}
            name="aliases"
            render={({ field }) => (
              <AliasChipEditor
                value={field.value}
                onSave={(v) => { field.onChange(v); }}
              />
            )}
          />
        </Field>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 16 }}>
          <button type="button" onClick={onCancel}>CANCEL</button>
          <button type="submit" disabled={form.formState.isSubmitting}>CREATE</button>
        </div>
      </form>
    </ModalShell>
  );
}

function Field({
  label, error, children,
}: { label: string; error?: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 8 }}>
      <label className="tx-modal__label">{label}</label>
      {children}
      {error && <div className="tx-modal__error">{error}</div>}
    </div>
  );
}

function ToggleControl({
  form, name, label,
}: {
  form: ReturnType<typeof useForm<CreateChildInput>>;
  name: 'is_cluster_node' | 'is_defining_garnish';
  label: string;
}) {
  const value = form.watch(name);
  return (
    <button
      type="button"
      role="switch"
      aria-checked={value}
      aria-label={label}
      onClick={() => form.setValue(name, !value)}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 6,
        background: 'transparent', border: 'none', cursor: 'pointer',
      }}
    >
      <span style={{
        width: 28, height: 14, borderRadius: 7, position: 'relative',
        background: value ? '#b8924d' : '#d4c8a8',
      }}>
        <span style={{
          position: 'absolute', left: value ? 14 : 1, top: 1,
          width: 12, height: 12, borderRadius: '50%', background: 'white',
        }} />
      </span>
      <span style={{ fontFamily: "'Cinzel', serif", fontSize: 10 }}>{label}</span>
    </button>
  );
}

export function ModalShell({
  onBackdropClick, children,
}: { onBackdropClick: () => void; children: React.ReactNode }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onBackdropClick(); };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [onBackdropClick]);
  return (
    <div
      role="dialog"
      aria-modal="true"
      onClick={(e) => { if (e.target === e.currentTarget) onBackdropClick(); }}
      style={{
        position: 'fixed', inset: 0, zIndex: 100,
        background: 'rgba(42, 31, 16, 0.92)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}
    >
      <div className="tx-modal">{children}</div>
    </div>
  );
}
```

- [ ] **Step 4: Add minimal CSS for `.tx-modal*`**

Append to `web/src/components/taxonomy/taxonomy.css`:

```css
.tx-modal {
  background: linear-gradient(180deg, #f8f0d8 0%, #efe2bf 100%);
  border: 1px solid var(--tx-frame-edge, #8b6f3a);
  padding: 18px 20px;
  border-radius: 4px;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.6);
  max-width: 360px;
  width: calc(100vw - 48px);
  font-family: 'Cinzel', serif;
  color: var(--tx-brown-ink, #4a2c0f);
}
.tx-modal__title {
  font-family: 'Cormorant Garamond', serif;
  font-size: 18px;
  font-weight: 600;
  margin: 0 0 4px;
}
.tx-modal__subtitle {
  font-size: 9px;
  letter-spacing: 0.18em;
  opacity: 0.7;
  margin-bottom: 12px;
}
.tx-modal__label {
  display: block;
  font-size: 9px;
  letter-spacing: 0.18em;
  opacity: 0.7;
  margin-bottom: 2px;
}
.tx-modal__error {
  font-size: 10px;
  font-style: italic;
  color: #b04040;
  margin-top: 2px;
}
.tx-modal input[type="text"],
.tx-modal select {
  width: 100%;
  padding: 6px 8px;
  border: 1px solid #b8924d;
  background: white;
  font-family: inherit;
  font-size: 12px;
  color: inherit;
}
```

- [ ] **Step 5: Run tests, expect PASS**

```bash
cd web && npm test -- --run CreateChildModal.test.tsx
```

- [ ] **Step 6: Commit**

```bash
git add web/src/components/taxonomy/CreateChildModal.tsx web/src/components/taxonomy/CreateChildModal.test.tsx web/src/components/taxonomy/taxonomy.css
git commit -m "Add CreateChildModal with RHF + zod, auto-slug from display_name"
```

---

## Phase 6 — EditParentsModal

### Task 6.1: Modal with current-parents + add via fuzzy search

**Files:**
- Create: `web/src/components/taxonomy/EditParentsModal.tsx`
- Create: `web/src/components/taxonomy/EditParentsModal.test.tsx`

- [ ] **Step 1: Write failing tests**

```tsx
// web/src/components/taxonomy/EditParentsModal.test.tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { EditParentsModal } from './EditParentsModal';
import type { TaxonomyViewRow } from './shapeData';

function row(id: number, name: string, child_ids: number[] = []): TaxonomyViewRow {
  return {
    id, slug: name.toLowerCase().replace(/ /g, '_'), display_name: name,
    node_kind: null, default_role: null,
    is_cluster_node: false, is_defining_garnish: false,
    parent_ids: [], child_ids, aliases: [], recipe_count: 0,
  };
}

const ROWS = [
  row(1, 'amari'),
  row(42, 'campari', []),
  row(84, 'bitter_aperitif'),
  row(312, 'italian_aperitif'),
  row(208, 'italian_liqueur'),
  row(319, 'italicus'),
];

const NODE = row(42, 'campari');

describe('EditParentsModal', () => {
  it('lists current parents with name #id and × to remove', () => {
    render(
      <EditParentsModal
        node={NODE}
        currentParentIds={[1, 84]}
        rows={ROWS}
        onCancel={vi.fn()}
        onSave={vi.fn()}
      />,
    );
    expect(screen.getByText('amari')).toBeInTheDocument();
    expect(screen.getByText('#1')).toBeInTheDocument();
    expect(screen.getByText('bitter_aperitif')).toBeInTheDocument();
    expect(screen.getAllByLabelText(/^remove/i)).toHaveLength(2);
  });

  it('removing a parent stages the change without saving', async () => {
    const onSave = vi.fn();
    const user = userEvent.setup();
    render(
      <EditParentsModal
        node={NODE} currentParentIds={[1, 84]} rows={ROWS}
        onCancel={vi.fn()} onSave={onSave}
      />,
    );
    await user.click(screen.getByLabelText('remove amari'));
    expect(onSave).not.toHaveBeenCalled();
  });

  it('search shows results with #id; pressing Enter on highlighted adds to staging', async () => {
    const user = userEvent.setup();
    render(
      <EditParentsModal
        node={NODE} currentParentIds={[]} rows={ROWS}
        onCancel={vi.fn()} onSave={vi.fn()}
      />,
    );
    await user.type(screen.getByPlaceholderText(/search/i), 'ital');
    expect(screen.getByText('italian_liqueur')).toBeInTheDocument();
    expect(screen.getByText('italicus')).toBeInTheDocument();
    await user.keyboard('{Enter}');
    // First result added — exact behavior: top result
    expect(screen.getAllByText(/^italian_/i).length).toBeGreaterThan(0);
  });

  it('greys out descendants of the current node (would-cycle)', () => {
    // make 312 a descendant of 42: 42 → 312
    const rowsWithDescendant = [
      ...ROWS.filter((r) => r.id !== 42),
      { ...NODE, child_ids: [312] },
    ];
    render(
      <EditParentsModal
        node={{ ...NODE, child_ids: [312] }}
        currentParentIds={[]}
        rows={rowsWithDescendant}
        onCancel={vi.fn()}
        onSave={vi.fn()}
      />,
    );
    const input = screen.getByPlaceholderText(/search/i);
    input.focus();
    // Type a term that matches the descendant
    userEvent.setup().type(input, 'italian_aperitif');
    // The descendant row should render with the cycle marker
    // (matches inline `would create cycle` text)
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect((screen as any).queryByText(/would create cycle/i)).toBeTruthy();
  });

  it('SAVE calls onSave with merged parent_ids (current minus removed plus added)', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(
      <EditParentsModal
        node={NODE} currentParentIds={[1, 84]} rows={ROWS}
        onCancel={vi.fn()} onSave={onSave}
      />,
    );
    await user.click(screen.getByLabelText('remove amari'));
    await user.type(screen.getByPlaceholderText(/search/i), 'italian_liqueur');
    await user.keyboard('{Enter}');
    await user.click(screen.getByRole('button', { name: /^save$/i }));
    expect(onSave).toHaveBeenCalledWith(42, expect.arrayContaining([84, 208]));
    expect(onSave.mock.calls[0][1]).not.toContain(1);
  });
});
```

- [ ] **Step 2: Run, expect FAIL**

```bash
cd web && npm test -- --run EditParentsModal.test.tsx
```

- [ ] **Step 3: Implement EditParentsModal.tsx**

```tsx
import { useMemo, useState } from 'react';
import type { TaxonomyViewRow } from './shapeData';
import { descendantsOf } from './cycle';
import { ModalShell } from './CreateChildModal';

interface Props {
  node: TaxonomyViewRow;
  currentParentIds: number[];
  rows: TaxonomyViewRow[];
  onCancel: () => void;
  onSave: (id: number, parentIds: number[]) => Promise<void> | void;
}

export function EditParentsModal({ node, currentParentIds, rows, onCancel, onSave }: Props) {
  const [removed, setRemoved] = useState<Set<number>>(new Set());
  const [added, setAdded] = useState<number[]>([]);
  const [query, setQuery] = useState('');
  const [highlight, setHighlight] = useState(0);
  const [submitting, setSubmitting] = useState(false);

  const blocked = useMemo(() => {
    const desc = descendantsOf(node.id, rows);
    desc.add(node.id);
    return desc;
  }, [node.id, rows]);

  const stagedSet = useMemo(() => {
    const s = new Set(currentParentIds.filter((id) => !removed.has(id)));
    for (const a of added) s.add(a);
    return s;
  }, [currentParentIds, removed, added]);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (q === '') return [];
    return rows
      .filter((r) =>
        r.display_name.toLowerCase().includes(q) ||
        r.slug.toLowerCase().includes(q),
      )
      .slice(0, 20);
  }, [query, rows]);

  function toggleRemove(id: number) {
    setRemoved((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  function addParent(id: number) {
    if (blocked.has(id)) return;
    if (stagedSet.has(id)) return;
    setAdded((a) => [...a, id]);
    setQuery('');
    setHighlight(0);
  }

  function unstageAdded(id: number) {
    setAdded((a) => a.filter((x) => x !== id));
  }

  async function save() {
    setSubmitting(true);
    try {
      await onSave(node.id, Array.from(stagedSet));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <ModalShell onBackdropClick={onCancel}>
      <h2 className="tx-modal__title">Edit parents of {node.display_name}</h2>
      <div className="tx-modal__subtitle">
        {currentParentIds.length} CURRENT · +{added.length} STAGED ·{' '}
        {removed.size > 0 ? `-${removed.size} REMOVED · ` : ''}
        {(removed.size > 0 || added.length > 0) ? 'UNSAVED' : 'CLEAN'}
      </div>

      <div className="tx-modal__label">CURRENT PARENTS</div>
      {currentParentIds.map((pid) => {
        const row = rows.find((r) => r.id === pid);
        const isRemoved = removed.has(pid);
        return (
          <ParentRow
            key={pid}
            label={`${row?.display_name ?? '(unknown)'} #${pid}`}
            removed={isRemoved}
            ariaLabel={isRemoved ? `undo remove ${row?.display_name ?? pid}` : `remove ${row?.display_name ?? pid}`}
            onClick={() => toggleRemove(pid)}
          />
        );
      })}
      {added.map((id) => {
        const row = rows.find((r) => r.id === id);
        return (
          <ParentRow
            key={`added-${id}`}
            label={`+ ${row?.display_name ?? '(unknown)'} #${id}`}
            staged
            ariaLabel={`unstage ${row?.display_name ?? id}`}
            onClick={() => unstageAdded(id)}
          />
        );
      })}

      <div className="tx-modal__label" style={{ marginTop: 12 }}>ADD PARENT</div>
      <input
        type="text"
        value={query}
        placeholder="search by name or slug..."
        onChange={(e) => { setQuery(e.target.value); setHighlight(0); }}
        onKeyDown={(e) => {
          const eligible = results.filter((r) => !blocked.has(r.id) && !stagedSet.has(r.id));
          if (e.key === 'ArrowDown') {
            e.preventDefault();
            setHighlight((h) => Math.min(h + 1, eligible.length - 1));
          } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            setHighlight((h) => Math.max(h - 1, 0));
          } else if (e.key === 'Enter') {
            e.preventDefault();
            const target = eligible[highlight];
            if (target) addParent(target.id);
          }
        }}
      />
      {results.length > 0 && (
        <div style={{ background: 'white', border: '1px solid #b8924d', maxHeight: 160, overflow: 'auto', marginTop: 4 }}>
          {results.map((r, i) => {
            const cycle = blocked.has(r.id);
            const already = stagedSet.has(r.id);
            const eligibleIdx = results
              .slice(0, i + 1)
              .filter((x) => !blocked.has(x.id) && !stagedSet.has(x.id))
              .length - 1;
            const highlighted = !cycle && !already && eligibleIdx === highlight;
            return (
              <div
                key={r.id}
                onClick={() => addParent(r.id)}
                style={{
                  padding: '4px 8px',
                  background: highlighted ? '#faf5e6' : 'transparent',
                  cursor: cycle || already ? 'not-allowed' : 'pointer',
                  opacity: cycle || already ? 0.5 : 1,
                  display: 'flex', justifyContent: 'space-between',
                }}
              >
                <span>
                  {r.display_name}
                  {cycle && <em style={{ marginLeft: 6, fontSize: 10 }}>would create cycle</em>}
                  {already && !cycle && <em style={{ marginLeft: 6, fontSize: 10 }}>already added</em>}
                </span>
                <span style={{ fontFamily: 'ui-monospace, monospace', opacity: 0.5 }}>#{r.id}</span>
              </div>
            );
          })}
        </div>
      )}

      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 16 }}>
        <button type="button" onClick={onCancel}>CANCEL</button>
        <button
          type="button"
          onClick={() => void save()}
          disabled={submitting || (removed.size === 0 && added.length === 0)}
        >SAVE</button>
      </div>
    </ModalShell>
  );
}

function ParentRow({
  label, removed, staged, ariaLabel, onClick,
}: {
  label: string;
  removed?: boolean;
  staged?: boolean;
  ariaLabel: string;
  onClick: () => void;
}) {
  return (
    <div
      style={{
        display: 'flex', alignItems: 'center',
        padding: '6px 8px', marginBottom: 4,
        background: staged ? '#faf5e6' : 'white',
        border: staged ? '1px dashed #b8924d' : '1px solid #b8924d',
        textDecoration: removed ? 'line-through' : 'none',
        opacity: removed ? 0.6 : 1,
        fontSize: 11,
      }}
    >
      <span style={{ flex: 1 }}>{label}</span>
      <button
        type="button"
        aria-label={ariaLabel}
        onClick={onClick}
        style={{ background: 'transparent', border: 'none', color: removed ? '#2a7a3a' : '#c44', cursor: 'pointer', fontSize: 14, lineHeight: 1 }}
      >{removed ? '↩' : '×'}</button>
    </div>
  );
}
```

- [ ] **Step 4: Run tests, expect PASS**

```bash
cd web && npm test -- --run EditParentsModal.test.tsx
```

- [ ] **Step 5: Commit**

```bash
git add web/src/components/taxonomy/EditParentsModal.tsx web/src/components/taxonomy/EditParentsModal.test.tsx
git commit -m "Add EditParentsModal: stage changes, fuzzy search, cycle prevention"
```

---

## Phase 7 — DeleteNodeModal

### Task 7.1: Confirmation modal with blocker preflight

**Files:**
- Create: `web/src/components/taxonomy/DeleteNodeModal.tsx`
- Create: `web/src/components/taxonomy/DeleteNodeModal.test.tsx`

- [ ] **Step 1: Write failing tests**

```tsx
// web/src/components/taxonomy/DeleteNodeModal.test.tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DeleteNodeModal } from './DeleteNodeModal';

const NODE = { id: 42, slug: 'campari', display_name: 'Campari' };

describe('DeleteNodeModal', () => {
  it('shows loading state, then no-blocker form when fetchBlockers resolves clean', async () => {
    const fetchBlockers = vi.fn().mockResolvedValue({
      children: 0, child_names: [], parents: 2, aliases: 1, provenance: 1,
      recipe_ingredients: 0, taxonomy_proposals: 0,
    });
    render(
      <DeleteNodeModal node={NODE} fetchBlockers={fetchBlockers} onCancel={vi.fn()} onConfirm={vi.fn()} />,
    );
    await waitFor(() => expect(screen.getByText(/Delete Campari/i)).toBeInTheDocument());
    expect(screen.getByText(/Type slug to confirm/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^delete$/i })).toBeDisabled();
  });

  it('disables DELETE button when blockers exist; surfaces blocker list', async () => {
    const fetchBlockers = vi.fn().mockResolvedValue({
      children: 3, child_names: [
        { id: 118, display_name: 'gin_campari' },
        { id: 127, display_name: 'aperol_campari_blend' },
        { id: 200, display_name: 'other' },
      ],
      parents: 2, aliases: 1, provenance: 1,
      recipe_ingredients: 12, taxonomy_proposals: 0,
    });
    render(
      <DeleteNodeModal node={NODE} fetchBlockers={fetchBlockers} onCancel={vi.fn()} onConfirm={vi.fn()} />,
    );
    await waitFor(() => expect(screen.getByText(/3 children/i)).toBeInTheDocument());
    expect(screen.getByText(/12 recipe_ingredients references/i)).toBeInTheDocument();
    expect(screen.queryByText(/Type slug to confirm/i)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^delete$/i })).toBeDisabled();
  });

  it('enables DELETE only when typed slug matches', async () => {
    const fetchBlockers = vi.fn().mockResolvedValue({
      children: 0, child_names: [], parents: 0, aliases: 0, provenance: 0,
      recipe_ingredients: 0, taxonomy_proposals: 0,
    });
    const onConfirm = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(
      <DeleteNodeModal node={NODE} fetchBlockers={fetchBlockers} onCancel={vi.fn()} onConfirm={onConfirm} />,
    );
    await waitFor(() => expect(screen.getByLabelText(/confirm slug/i)).toBeInTheDocument());
    const del = screen.getByRole('button', { name: /^delete$/i });
    expect(del).toBeDisabled();
    await user.type(screen.getByLabelText(/confirm slug/i), 'campari');
    expect(del).not.toBeDisabled();
    await user.click(del);
    expect(onConfirm).toHaveBeenCalledWith(42);
  });
});
```

- [ ] **Step 2: Run, expect FAIL**

```bash
cd web && npm test -- --run DeleteNodeModal.test.tsx
```

- [ ] **Step 3: Implement DeleteNodeModal.tsx**

```tsx
import { useEffect, useState } from 'react';
import { ModalShell } from './CreateChildModal';
import type { TaxonomyBlockers } from './rpcs';

interface Props {
  node: { id: number; slug: string; display_name: string };
  fetchBlockers: (id: number) => Promise<TaxonomyBlockers>;
  onCancel: () => void;
  onConfirm: (id: number) => Promise<void> | void;
}

export function DeleteNodeModal({ node, fetchBlockers, onCancel, onConfirm }: Props) {
  const [b, setB] = useState<TaxonomyBlockers | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [confirmInput, setConfirmInput] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchBlockers(node.id)
      .then((res) => { if (!cancelled) setB(res); })
      .catch((e: unknown) => { if (!cancelled) setErr(String(e)); });
    return () => { cancelled = true; };
  }, [fetchBlockers, node.id]);

  if (err) {
    return (
      <ModalShell onBackdropClick={onCancel}>
        <h2 className="tx-modal__title">Delete {node.display_name}?</h2>
        <div className="tx-modal__error">Failed to read blockers: {err}</div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 12 }}>
          <button type="button" onClick={onCancel}>CLOSE</button>
        </div>
      </ModalShell>
    );
  }

  if (b === null) {
    return (
      <ModalShell onBackdropClick={onCancel}>
        <h2 className="tx-modal__title">Delete {node.display_name}?</h2>
        <div style={{ fontStyle: 'italic', opacity: 0.7 }}>Checking blockers…</div>
      </ModalShell>
    );
  }

  const blocked = b.children > 0 || b.recipe_ingredients > 0 || b.taxonomy_proposals > 0;
  const cascade: string[] = [];
  if (b.parents > 0) cascade.push(`${b.parents} parent edge${b.parents === 1 ? '' : 's'}`);
  if (b.aliases > 0) cascade.push(`${b.aliases} alias${b.aliases === 1 ? '' : 'es'}`);
  if (b.provenance > 0) cascade.push(`${b.provenance} provenance row${b.provenance === 1 ? '' : 's'}`);

  const blockerLines: string[] = [];
  if (b.children > 0) blockerLines.push(`${b.children} children — re-parent or delete first`);
  if (b.recipe_ingredients > 0) blockerLines.push(`${b.recipe_ingredients} recipe_ingredients references — remap first`);
  if (b.taxonomy_proposals > 0) blockerLines.push(`${b.taxonomy_proposals} open taxonomy_proposals references`);

  return (
    <ModalShell onBackdropClick={onCancel}>
      <h2 className="tx-modal__title">Delete {node.display_name} (#{node.id})?</h2>

      {cascade.length > 0 && (
        <>
          <div className="tx-modal__label">Will cascade:</div>
          <ul style={{ margin: '0 0 12px', paddingLeft: 16, fontSize: 11 }}>
            {cascade.map((c) => <li key={c}>{c}</li>)}
          </ul>
        </>
      )}

      {blocked && (
        <>
          <div className="tx-modal__label" style={{ color: '#b04040' }}>Blockers:</div>
          <ul style={{ margin: '0 0 12px', paddingLeft: 16, fontSize: 11 }}>
            {blockerLines.map((l) => <li key={l}>{l}</li>)}
          </ul>
          {b.child_names.length > 0 && (
            <div style={{ fontSize: 10, opacity: 0.7, marginBottom: 12 }}>
              Children: {b.child_names.slice(0, 5).map((c) => `${c.display_name} (#${c.id})`).join(', ')}
              {b.child_names.length > 5 && `, … +${b.child_names.length - 5} more`}
            </div>
          )}
        </>
      )}

      {!blocked && (
        <div style={{ marginBottom: 12 }}>
          <label className="tx-modal__label" htmlFor="confirm-slug">
            Type slug to confirm:
          </label>
          <input
            id="confirm-slug"
            aria-label="confirm slug"
            type="text"
            value={confirmInput}
            onChange={(e) => setConfirmInput(e.target.value)}
            placeholder={node.slug}
          />
        </div>
      )}

      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
        <button type="button" onClick={onCancel}>CANCEL</button>
        <button
          type="button"
          disabled={blocked || confirmInput !== node.slug || submitting}
          onClick={async () => {
            setSubmitting(true);
            try { await onConfirm(node.id); }
            finally { setSubmitting(false); }
          }}
        >DELETE</button>
      </div>
    </ModalShell>
  );
}
```

- [ ] **Step 4: Run tests, expect PASS**

```bash
cd web && npm test -- --run DeleteNodeModal.test.tsx
```

- [ ] **Step 5: Commit**

```bash
git add web/src/components/taxonomy/DeleteNodeModal.tsx web/src/components/taxonomy/DeleteNodeModal.test.tsx
git commit -m "Add DeleteNodeModal with blocker preflight + slug confirm"
```

---

## Phase 8 — Plus button overlay + ForceCanvas integration

### Task 8.1: Expose getNodeScreenCoords + panTo on ForceCanvas

**Files:**
- Modify: `web/src/components/taxonomy/ForceCanvas.tsx`

- [ ] **Step 1: Extend ForceCanvasHandle**

In `web/src/components/taxonomy/ForceCanvas.tsx`, replace the `ForceCanvasHandle` interface and `useImperativeHandle` block:

```tsx
export interface ForceCanvasHandle {
  zoom: (factor: number) => void;
  fit: () => void;
  centerAt: (x: number, y: number, ms?: number) => void;
  /** Convert a node's simulation coords to viewport (CSS) pixel coords. Returns null if not yet positioned. */
  getNodeScreenCoords: (id: number) => { x: number; y: number } | null;
}

useImperativeHandle(ref, () => ({
  zoom: (factor) => {
    const g = inner.current;
    if (!g) return;
    const cur = g.zoom();
    g.zoom(cur * factor, 250);
  },
  fit: () => inner.current?.zoomToFit(400, 60),
  centerAt: (x, y, ms = 400) => inner.current?.centerAt(x, y, ms),
  getNodeScreenCoords: (id) => {
    const g = inner.current;
    if (!g) return null;
    const node = nodes.find((n) => n.id === id) as { x?: number; y?: number } | undefined;
    if (node?.x == null || node.y == null) return null;
    const { x, y } = g.graph2ScreenCoords(node.x, node.y);
    return { x, y };
  },
}), [nodes]);
```

- [ ] **Step 2: Verify by typing — run typecheck**

```bash
cd web && npx tsc --noEmit
```

Expected: zero errors. (`graph2ScreenCoords` is documented on `ForceGraphMethods`.)

- [ ] **Step 3: Commit**

```bash
git add web/src/components/taxonomy/ForceCanvas.tsx
git commit -m "ForceCanvas: expose getNodeScreenCoords for HTML overlays"
```

### Task 8.2: PlusButton overlay component

**Files:**
- Create: `web/src/components/taxonomy/PlusButton.tsx`

This is a small, presentational component — no test needed beyond the integration test in Phase 10.

- [ ] **Step 1: Implement PlusButton.tsx**

```tsx
interface Props {
  x: number;          // viewport pixel x of node center
  y: number;          // viewport pixel y of node center
  radius: number;     // node radius in viewport pixels
  onClick: () => void;
  ariaLabel: string;
}

export function PlusButton({ x, y, radius, onClick, ariaLabel }: Props) {
  return (
    <button
      type="button"
      aria-label={ariaLabel}
      onClick={onClick}
      style={{
        position: 'absolute',
        left: x + radius * 0.7 - 9,
        top: y - radius * 0.7 - 9,
        width: 18, height: 18, borderRadius: 9,
        background: '#f8f0d8',
        border: '1px solid #8b6f3a',
        color: '#5a4220',
        cursor: 'pointer',
        font: 'bold 14px sans-serif', lineHeight: '14px',
        padding: 0,
        zIndex: 5,
        boxShadow: '0 2px 4px rgba(0,0,0,0.3)',
      }}
    >+</button>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add web/src/components/taxonomy/PlusButton.tsx
git commit -m "Add PlusButton overlay (HTML badge for hovered nodes)"
```

---

## Phase 9 — HighlightPulse + Toast

### Task 9.1: HighlightPulse component

**Files:**
- Create: `web/src/components/taxonomy/HighlightPulse.tsx`
- Modify: `web/src/components/taxonomy/taxonomy.css`

- [ ] **Step 1: Implement HighlightPulse.tsx**

```tsx
interface Props {
  x: number;
  y: number;
  radius: number;
}

export function HighlightPulse({ x, y, radius }: Props) {
  const size = (radius + 8) * 2;
  return (
    <div
      aria-hidden
      className="tx-highlight-pulse"
      style={{
        position: 'absolute',
        left: x - size / 2, top: y - size / 2,
        width: size, height: size,
        pointerEvents: 'none',
        zIndex: 4,
      }}
    />
  );
}
```

- [ ] **Step 2: Append CSS keyframes**

In `web/src/components/taxonomy/taxonomy.css`:

```css
@keyframes tx-pulse {
  0%   { box-shadow: 0 0 0 0   var(--tx-gold, #d4a857); opacity: 1;   }
  70%  { box-shadow: 0 0 0 18px rgba(212, 168, 87, 0); opacity: 0.4; }
  100% { box-shadow: 0 0 0 18px rgba(212, 168, 87, 0); opacity: 0;   }
}
.tx-highlight-pulse {
  border-radius: 50%;
  animation: tx-pulse 2s ease-out 1 forwards;
}
```

- [ ] **Step 3: Commit**

```bash
git add web/src/components/taxonomy/HighlightPulse.tsx web/src/components/taxonomy/taxonomy.css
git commit -m "Add HighlightPulse: ~2s gold ring on the affected node"
```

### Task 9.2: Toast component

**Files:**
- Create: `web/src/components/taxonomy/Toast.tsx`

- [ ] **Step 1: Implement Toast.tsx**

```tsx
import { useEffect } from 'react';

interface Props {
  message: string;
  kind?: 'info' | 'error';
  onDismiss: () => void;
}

export function Toast({ message, kind = 'info', onDismiss }: Props) {
  useEffect(() => {
    const t = setTimeout(onDismiss, 4000);
    return () => clearTimeout(t);
  }, [onDismiss]);
  return (
    <div
      role="status"
      style={{
        position: 'fixed', bottom: 24, left: '50%', transform: 'translateX(-50%)',
        background: kind === 'error' ? '#3a1818' : '#2a1f10',
        color: '#f8f0d8',
        border: '1px solid ' + (kind === 'error' ? '#b04040' : '#8b6f3a'),
        padding: '8px 14px', borderRadius: 4, fontSize: 12,
        fontFamily: "'Cinzel', serif", letterSpacing: '0.1em',
        boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
        zIndex: 200,
      }}
    >
      {message}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add web/src/components/taxonomy/Toast.tsx
git commit -m "Add Toast for RPC errors + post-save confirmations"
```

---

## Phase 10 — Wire everything into Taxonomy.tsx

### Task 10.1: Centralize the post-save state mutation helper

**Files:**
- Modify: `web/src/pages/Taxonomy.tsx`

The page's `LoadedView` currently derives `nodes` and `links` via a `useMemo` from the prop `rows`, which is set once by the parent `Taxonomy()` after the initial fetch. To support incremental updates, lift `rows` into local state of `LoadedView` (initialized from the prop) and provide an `applyMutation(rowChanges)` helper.

- [ ] **Step 1: Refactor LoadedView to own mutable rows**

In `web/src/pages/Taxonomy.tsx`, replace `function LoadedView({ rows }: ...)`'s opening lines:

```tsx
function LoadedView({ rows: initialRows }: { rows: TaxonomyViewRow[] }) {
  const [rows, setRows] = useState<TaxonomyViewRow[]>(initialRows);
  // ... rest of the hooks, replacing `rows` references unchanged
```

Keep all subsequent references to `rows` as-is — `useMemo`s on `rows` will re-derive when state changes.

- [ ] **Step 2: Verify nothing broke**

```bash
cd web && npm test -- --run
```

Expected: all existing tests still pass.

- [ ] **Step 3: Commit**

```bash
git add web/src/pages/Taxonomy.tsx
git commit -m "Taxonomy: lift rows into LoadedView state for incremental mutations"
```

### Task 10.2: Wire the inline-edit RPC

**Files:**
- Modify: `web/src/pages/Taxonomy.tsx`

- [ ] **Step 1: Add RPC handler + post-save mutation**

In `LoadedView`, near the other handlers, add:

```tsx
import { updateTaxonomyNode } from '../components/taxonomy/rpcs';
import type { FieldKey } from '../components/taxonomy/NodeCard';

const [toast, setToast] = useState<{ message: string; kind?: 'info' | 'error' } | null>(null);

async function handleEditField(id: number, key: FieldKey, next: unknown) {
  // For toggles and dropdowns we send the value directly; for aliases, replace-all.
  const patch: Record<string, unknown> = { [key]: next };
  await updateTaxonomyNode(id, patch);
  setRows((prev) =>
    prev.map((r) => (r.id === id ? { ...r, [key]: next as never } : r)),
  );
}
```

- [ ] **Step 2: Pass it to NodeCard's pinned instances**

Replace the two `<NodeCard ...>` JSX blocks with the editing-aware versions:

```tsx
const parentLookup = useMemo(
  () => new Map(rows.map((r) => [r.id, { id: r.id, display_name: r.display_name }])),
  [rows],
);

// pinned card
<NodeCard
  node={focusedNode}
  mode="pinned"
  onDismiss={() => setFocusedId(null)}
  onEditField={handleEditField}
  onEditParents={(id) => setEditingParentsFor(id)}
  onDelete={(id) => setDeletingId(id)}
  parentLookup={parentLookup}
/>

// hover card stays unchanged (no edit hooks)
```

- [ ] **Step 3: Verify by running web tests + typecheck**

```bash
cd web && npm test -- --run && npx tsc --noEmit
```

- [ ] **Step 4: Commit**

```bash
git add web/src/pages/Taxonomy.tsx
git commit -m "Wire inline-edit RPC + per-row state update through Taxonomy page"
```

### Task 10.3: Wire the create-child flow (PlusButton + Modal + RPC + post-save)

**Files:**
- Modify: `web/src/pages/Taxonomy.tsx`

- [ ] **Step 1: Add hover-tracked plus button**

In `LoadedView`, after `const [hovered, setHovered] = useState(...)`:

```tsx
import { PlusButton } from '../components/taxonomy/PlusButton';
import { CreateChildModal } from '../components/taxonomy/CreateChildModal';
import { createTaxonomyNode } from '../components/taxonomy/rpcs';

const [creatingFor, setCreatingFor] = useState<TaxonomyViewRow | null>(null);
const [plusCoords, setPlusCoords] = useState<{ x: number; y: number; r: number } | null>(null);

// Recompute the plus position each animation frame while a node is hovered.
useEffect(() => {
  if (!hovered) { setPlusCoords(null); return; }
  let frame = 0;
  const tick = () => {
    const c = canvasRef.current?.getNodeScreenCoords(hovered.id);
    if (c) {
      const r = nodeRadius(hovered, sizeMode);
      setPlusCoords({ x: c.x, y: c.y, r });
    }
    frame = requestAnimationFrame(tick);
  };
  frame = requestAnimationFrame(tick);
  return () => cancelAnimationFrame(frame);
}, [hovered, sizeMode]);
```

(Import `nodeRadius` from `../components/taxonomy/palette` — it already exists.)

- [ ] **Step 2: Render PlusButton + CreateChildModal**

Inside the JSX, after `<ForceCanvas .../>`:

```tsx
{hovered && plusCoords && (
  <PlusButton
    x={plusCoords.x}
    y={plusCoords.y}
    radius={plusCoords.r}
    ariaLabel={`Add child of ${hovered.display_name}`}
    onClick={() => setCreatingFor(hovered)}
  />
)}
{creatingFor && (
  <CreateChildModal
    parent={{ id: creatingFor.id, display_name: creatingFor.display_name }}
    onCancel={() => setCreatingFor(null)}
    onCreate={async (parentId, input) => {
      try {
        const newId = await createTaxonomyNode(parentId, input);
        setRows((prev) => [
          ...prev,
          {
            id: newId, slug: input.slug, display_name: input.display_name,
            node_kind: input.node_kind, default_role: input.default_role,
            is_cluster_node: input.is_cluster_node,
            is_defining_garnish: input.is_defining_garnish,
            parent_ids: [parentId], child_ids: [],
            aliases: input.aliases, recipe_count: 0,
          },
          // also append the new id to the parent's child_ids
        ].map((r) => r.id === parentId ? { ...r, child_ids: [...r.child_ids, newId] } : r));
        setCreatingFor(null);
        setFocusedId(newId);
        setPulseFor(newId);
        setToast({ message: `Created ${input.display_name} (#${newId})` });
      } catch (e) {
        setToast({ message: `Create failed: ${String(e)}`, kind: 'error' });
      }
    }}
  />
)}
```

- [ ] **Step 3: Add pulse + pan-to-view effect**

```tsx
import { HighlightPulse } from '../components/taxonomy/HighlightPulse';

const [pulseFor, setPulseFor] = useState<number | null>(null);
const [pulseCoords, setPulseCoords] = useState<{ x: number; y: number; r: number } | null>(null);

useEffect(() => {
  if (pulseFor === null) return;
  const t = setTimeout(() => setPulseFor(null), 2000);
  return () => clearTimeout(t);
}, [pulseFor]);

// Compute pulse coords + pan if off-screen
useEffect(() => {
  if (pulseFor === null) { setPulseCoords(null); return; }
  // Wait one frame for the simulation to tick and assign x/y
  const id = requestAnimationFrame(() => {
    const c = canvasRef.current?.getNodeScreenCoords(pulseFor);
    if (!c) return;
    const node = rows.find((r) => r.id === pulseFor);
    if (!node) return;
    setPulseCoords({ x: c.x, y: c.y, r: nodeRadius(node as TaxonomyNode, sizeMode) });
    if (c.x < 0 || c.y < 0 || c.x > size.w || c.y > size.h) {
      // off-screen — pan to the simulation coords (use centerAt with sim coords)
      // graph2ScreenCoords is the inverse; we want sim coords from rows[].x/y
      const runtime = (rows.find((r) => r.id === pulseFor) as { x?: number; y?: number } | undefined);
      if (runtime?.x != null && runtime.y != null) {
        canvasRef.current?.centerAt(runtime.x, runtime.y, 600);
      }
    }
  });
  return () => cancelAnimationFrame(id);
}, [pulseFor, rows, sizeMode, size]);
```

Render the pulse:

```tsx
{pulseCoords && <HighlightPulse {...pulseCoords} />}
```

- [ ] **Step 4: Verify**

```bash
cd web && npm test -- --run && npx tsc --noEmit
```

- [ ] **Step 5: Commit**

```bash
git add web/src/pages/Taxonomy.tsx
git commit -m "Wire create-child: hover + button + modal + RPC + incremental update + pulse"
```

### Task 10.4: Wire edit-parents + delete flows

**Files:**
- Modify: `web/src/pages/Taxonomy.tsx`

- [ ] **Step 1: Add modal state + handlers**

```tsx
import { EditParentsModal } from '../components/taxonomy/EditParentsModal';
import { DeleteNodeModal } from '../components/taxonomy/DeleteNodeModal';
import { setNodeParents, deleteTaxonomyNode, getTaxonomyNodeBlockers } from '../components/taxonomy/rpcs';

const [editingParentsFor, setEditingParentsFor] = useState<number | null>(null);
const [deletingId, setDeletingId] = useState<number | null>(null);

const editingParentsNode = editingParentsFor != null ? rows.find((r) => r.id === editingParentsFor) ?? null : null;
const deletingNode = deletingId != null ? rows.find((r) => r.id === deletingId) ?? null : null;
```

- [ ] **Step 2: Render the modals**

```tsx
{editingParentsNode && (
  <EditParentsModal
    node={editingParentsNode}
    currentParentIds={editingParentsNode.parent_ids}
    rows={rows}
    onCancel={() => setEditingParentsFor(null)}
    onSave={async (id, parentIds) => {
      try {
        await setNodeParents(id, parentIds);
        setRows((prev) => {
          // Replace the affected node's parent_ids; also rebuild every other row's child_ids
          // to reflect the new edge set involving `id`.
          const next = prev.map((r) => {
            if (r.id === id) return { ...r, parent_ids: parentIds };
            const wasParent = r.child_ids.includes(id);
            const isParent = parentIds.includes(r.id);
            if (wasParent && !isParent) return { ...r, child_ids: r.child_ids.filter((c) => c !== id) };
            if (!wasParent && isParent) return { ...r, child_ids: [...r.child_ids, id] };
            return r;
          });
          return next;
        });
        setEditingParentsFor(null);
        setPulseFor(id);
        setToast({ message: `Updated parents of ${editingParentsNode.display_name}` });
      } catch (e) {
        setToast({ message: `Save failed: ${String(e)}`, kind: 'error' });
      }
    }}
  />
)}
{deletingNode && (
  <DeleteNodeModal
    node={{ id: deletingNode.id, slug: deletingNode.slug, display_name: deletingNode.display_name }}
    fetchBlockers={getTaxonomyNodeBlockers}
    onCancel={() => setDeletingId(null)}
    onConfirm={async (id) => {
      try {
        await deleteTaxonomyNode(id);
        setRows((prev) => prev
          .filter((r) => r.id !== id)
          .map((r) => ({
            ...r,
            parent_ids: r.parent_ids.filter((p) => p !== id),
            child_ids: r.child_ids.filter((c) => c !== id),
          })),
        );
        setDeletingId(null);
        if (focusedId === id) setFocusedId(null);
        setToast({ message: `Deleted ${deletingNode.display_name} (#${id})` });
      } catch (e) {
        setToast({ message: `Delete failed: ${String(e)}`, kind: 'error' });
      }
    }}
  />
)}
{toast && <Toast {...toast} onDismiss={() => setToast(null)} />}
```

(Import `Toast` from `'../components/taxonomy/Toast'`.)

- [ ] **Step 3: Verify**

```bash
cd web && npm test -- --run && npx tsc --noEmit
```

- [ ] **Step 4: Commit**

```bash
git add web/src/pages/Taxonomy.tsx
git commit -m "Wire edit-parents, delete, and toast flows"
```

---

## Phase 11 — Manual end-to-end smoke test

The unit tests cover individual components and the DB tests cover the RPCs in isolation. The full flow needs a manual walkthrough against live local Supabase.

### Task 11.1: Smoke test all four flows in the browser

- [ ] **Step 1: Ensure local Supabase is running with restored data**

From the **Mac host:**

```bash
supabase status   # confirm it's running
```

If a backup hasn't been restored recently, restore one per [`docs/backups.md`](docs/backups.md) so there's realistic data.

- [ ] **Step 2: Start the dev server**

In the worktree:

```bash
cd web && npm install && npm run dev
```

Open [http://localhost:5173/taxonomy](http://localhost:5173/taxonomy) in the browser. Sign in via magic link as the dev admin (`admin@local.test`).

- [ ] **Step 3: Walk the inline-edit flow**

Click any node to pin its NodeCard. Hover each editable field (DISPLAY NAME, SLUG, NODE KIND, DEFAULT ROLE, CLUSTER toggle, GARNISH toggle, ALIASES). Verify:

- Solid border + pencil appears on hover.
- Click pencil → text becomes input / select / chip editor.
- Type new value, press Enter → field updates and persists (refresh the page; value is still there).
- Open another field and press Esc → field reverts.
- Toggle a boolean → value flips.
- Add an alias chip via Enter, remove one via ×, then click outside → aliases save in one shot.

- [ ] **Step 4: Walk the create-child flow**

Hover any node. A `+` badge appears at the top-right of its circle. Click it. Modal opens. Type a display name, watch the slug auto-fill. Adjust node_kind, default_role, toggle is_cluster_node, add an alias. Click CREATE.

Verify: modal closes, new node appears on the graph (no full redraw — surrounding nodes don't jump), focus pins to the new node, gold pulse plays on it for ~2s, camera pans if it landed off-screen.

- [ ] **Step 5: Walk the edit-parents flow**

Click a node to pin. Hover the PARENTS section, click pencil. Modal opens with current parents listed. Click `×` next to one → it gets struck through. Type in the search box → results list with `name #id`. Use ↑/↓/Enter to add a result. Try typing a descendant's name — verify it shows greyed with "would create cycle". Click SAVE.

Verify: modal closes, NodeCard's PARENTS section reflects the change, gold pulse plays.

- [ ] **Step 6: Walk the delete flow**

Click a node with no children and no recipe references (a freshly-created one is the easiest). Click "Delete node" at the bottom of its NodeCard. Modal opens, says "Will cascade: …", shows no blockers. Type the slug → DELETE button enables. Click DELETE.

Verify: modal closes, node disappears from the graph, focus clears, toast says "Deleted …".

Also: try deleting a node that does have children. Verify the modal lists the children and disables DELETE.

- [ ] **Step 7: Verify the worktree is clean**

```bash
cd /workspaces/spiritolo/.claude/worktrees/claude+taxonomy-curation-ui && git status
```

Expected: clean working tree, all commits are on `claude/taxonomy-curation-ui`.

- [ ] **Step 8: Final test pass**

```bash
cd /workspaces/spiritolo/.claude/worktrees/claude+taxonomy-curation-ui/web && npm test -- --run
set -a && source /workspaces/spiritolo/.env && set +a
cd /workspaces/spiritolo/.claude/worktrees/claude+taxonomy-curation-ui/ingredients && uv run pytest tests/test_taxonomy_rpcs.py -v
```

Expected: both green.

- [ ] **Step 9: Hand back to user**

Report:
- Branch is `claude/taxonomy-curation-ui`.
- All migrations applied locally; staging not touched.
- Spec at [`docs/superpowers/specs/2026-05-07-taxonomy-curation-design.md`](docs/superpowers/specs/2026-05-07-taxonomy-curation-design.md).
- Plan at [`docs/superpowers/plans/2026-05-07-taxonomy-curation.md`](docs/superpowers/plans/2026-05-07-taxonomy-curation.md).
- Ready for review / PR.
