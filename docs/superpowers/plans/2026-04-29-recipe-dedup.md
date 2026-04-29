# Recipe Dedup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cluster recipes that represent the same drink so the website can display a "stack" of variants per cocktail (canonical recipe on top, ratio/brand variants below) instead of N near-duplicate rows. Identity is deterministic: `hash(canonical_name, role-tagged ingredient set rolled up to a curated antichain in the taxonomy DAG)`.

**Architecture:** Three sub-pipelines that all live in `ingredients/src/ingredients/dedup/`. (1) **Normalize names** — phased cascade (alias → pg_trgm → LLM) writes `recipes.canonical_name`. (2) **Compute clusters** — deterministic; tags `recipe_ingredients.role`, rolls each ingredient up to its `is_cluster_node` ancestor, hashes `(canonical_name, role-tagged set)` to produce `cluster_key` and `variant_key`. (3) **Audit + promote** — operator-driven: 5 audit queries, plus a one-shot `promote-substances` walk that fixes auto-created brand/expression nodes that should have been substance nodes (Campari, Aperol, Angostura, etc.). Reuses D's `LLMProvider`, retry helper, normalize, alias/lexical layer shapes, and all of `spiritolo_common`. Code reuse is the pattern; only domain-specific layers are E-original.

**Tech Stack:** Python 3.11+ (uv workspace), psycopg, pytest, Postgres (Supabase) with `pg_trgm`, Anthropic + Ollama LLM providers (already wired in `mapping/`).

**Spec:** [docs/superpowers/specs/2026-04-29-recipe-dedup-design.md](../specs/2026-04-29-recipe-dedup-design.md)

**Parallelization note.** The reviewer-gated taxonomy seed expansion (gin sub-styles, individual amari, individual bitters, key liqueurs/cordials, fortified wines, broader categories — juices/syrups/mixers/dairy/fresh herbs, alias seed) runs as a **fully parallel curator track**, gated only on Phase 0 of this plan. After Phase 0 lands (one tiny migration, can ship as its own PR), the curator can edit `supabase/seeds/taxonomy_nodes.sql` independently — adding new substance nodes, marking the antichain, setting role_defaults, marking defining garnishes — without coordinating with the code track. Code is developed against `eval_fixture.py`, which doesn't depend on production seed state. The two tracks reconcile at end-to-end integration time. The ≥95% antichain rollup coverage from the spec is the curator track's success criterion, not a gate on this plan's tasks.

This plan's task decomposition includes a **Phase 0** to unblock the curator immediately, then the rest of the work (Phases 1–11) which runs against the fixture and lands code that's ready when the curator track catches up.

**Definitions referenced throughout:**
- `MAPPER_VERSION` — D's constant in `ingredients/src/ingredients/mapping/mapper.py`. E does not modify.
- `NORMALIZER_VERSION = "v1"` — E's name-normalization version constant.
- `DEDUP_VERSION = "v1"` — E's cluster + role compute version constant.
- "Antichain" — the set of `taxonomy_nodes.is_cluster_node = true` nodes. Cluster identity rolls each ingredient up to its nearest such ancestor.

---

## File Structure

**New migrations** (after D's last `20260429140300`, all dated `20260429160xxx`):
- `supabase/migrations/20260429160000_dedup_taxonomy_node_columns.sql`
- `supabase/migrations/20260429160100_dedup_recipe_ingredients_role.sql`
- `supabase/migrations/20260429160200_dedup_recipes_normalize.sql`
- `supabase/migrations/20260429160300_dedup_cocktail_aliases.sql`
- `supabase/migrations/20260429160400_dedup_clusters.sql`

**New seed content (minimum-viable; full expansion is out of scope):**
- `supabase/seeds/taxonomy_nodes.sql` — extended with antichain markers + role_defaults on existing nodes; a small set of new nodes added (`london_dry_gin`, `angostura_bitters`, `peychauds_bitters`, `orange_bitters`, `campari`, `aperol`, `simple_syrup`, `soda_water`, `ice`, plus aliases).

**New code package:** `ingredients/src/ingredients/dedup/`
- `__init__.py`
- `version.py` — `NORMALIZER_VERSION`, `DEDUP_VERSION` constants
- `types.py` — `Resolved`, `Pending`, `Abstain`, `NameProposal` dataclasses (cocktail-name analogues of D's `mapping/types.py`)
- `normalize.py` — `normalize_cocktail_name(raw)` — wraps `mapping.normalize.normalize_name` and adds stop-word stripping, parenthetical removal, etc.
- `alias_layer.py` — Phase-1 Layer-1: exact lookup against `cocktail_aliases.alias`
- `lexical_layer.py` — Phase-1 Layer-2: pg_trgm against `cocktail_aliases`
- `db.py` — DB helpers: `fetch_unique_unresolved_names`, `write_resolution`, `write_pending`, `write_abstain`, `add_alias`
- `normalizer.py` — Phase-1 orchestrator: walk cascade, write to `recipes`
- `prompt.py` — `SYSTEM_PROMPT`, `build_user_prompt`, `parse_response` for cocktail-name LLM
- `normalizer_llm.py` — Phase-2 orchestrator: drains `pending_llm` via `mapping.llm_provider.LLMProvider`
- `role_classifier.py` — pure function `(node, role_default, amount, unit, position) → role`
- `rollup.py` — `roll_up_to_antichain(conn, node_id) → antichain_node_id`
- `cluster.py` — `compute_cluster_key`, `compute_variant_key`, orchestrator that writes `recipe_clusters`, `recipes.cluster_id`, `recipes.variant_key`, `recipe_ingredients.role`
- `audit.py` — five audit queries
- `promote_substances.py` — interactive CLI for substance promotion
- `eval_fixture.py` — fixture taxonomy + cocktail aliases (mirrors `mapping/eval_fixture.py`)
- `eval_set.py` — `DedupEvalCase` + `run_eval`

**Modified:**
- `ingredients/src/ingredients/cli.py` — adds `normalize-names`, `cluster`, `promote-substances`, `dedup-all` subcommands

**New tests in `ingredients/tests/`:**
- `test_dedup_normalize.py`
- `test_dedup_alias_layer.py`
- `test_dedup_lexical_layer.py`
- `test_dedup_db.py`
- `test_dedup_normalizer.py`
- `test_dedup_prompt.py`
- `test_dedup_normalizer_llm.py`
- `test_dedup_role_classifier.py`
- `test_dedup_rollup.py`
- `test_dedup_cluster.py`
- `test_dedup_audit.py`
- `test_dedup_promote_substances.py`
- `test_dedup_cli.py`
- `test_dedup_eval.py`
- `test_dedup_end_to_end.py`

**New scripts:**
- `scripts/refresh-processed-seeds.sh`
- `supabase/seeds/processed/` — empty directory, populated by the script after first dump

**Documentation:**
- `CLAUDE.md` — add dedup pipeline section + processed-seeds pattern

---

## Conventions used throughout this plan

- **TDD:** every code task writes failing test → runs to confirm fail → minimal impl → runs to confirm pass → commit. Where a single behavior naturally needs multiple tests, add them all in the test file in one step but verify each passes individually.
- **Run tests from `ingredients/`:** `cd ingredients && uv run pytest tests/<file>::<test> -v`. Always pass a specific test or file unless explicitly running the suite.
- **Migrations applied to test DB automatically** by `ingredients/tests/conftest.py` (per CLAUDE.md). For prod-side dev DB, run `supabase db reset --db-url "postgresql://postgres:postgres@192.168.65.254:54322/postgres" --yes`.
- **Commit messages:** terse, imperative; one feature per commit; co-author trailer per CLAUDE.md.
- **Mirror D where possible:** when a task's pattern matches an existing `mapping/` module, the task says "mirror `mapping/<file>.py` shape with the differences listed below" instead of re-deriving the pattern.

---

## Phase 0: Unblock the curator (ship as its own PR before everything else)

### Task 0.1: Add antichain / role_default / is_defining_garnish columns to taxonomy_nodes

**Files:**
- Create: `supabase/migrations/20260429160000_dedup_taxonomy_node_columns.sql`
- Test: `ingredients/tests/test_dedup_migrations.py` (new file, just this one test for now)

- [ ] **Step 1: Write the failing test**

Create `ingredients/tests/test_dedup_migrations.py`:

```python
"""Schema-level integration tests for E's migrations.

Tests run against TEST_DB_URL with all migrations applied (the
ingredients conftest auto-applies new ones). Each test asserts a
column or table exists with the expected shape.
"""

from __future__ import annotations

import pytest


def test_taxonomy_nodes_has_is_cluster_node_column(db_conn):
    row = db_conn.execute(
        """
        select column_name, data_type, is_nullable, column_default
        from information_schema.columns
        where table_name = 'taxonomy_nodes' and column_name = 'is_cluster_node'
        """
    ).fetchone()
    assert row is not None, "is_cluster_node column missing"
    name, dtype, nullable, default = row
    assert dtype == "boolean"
    assert nullable == "NO"
    assert "false" in (default or "").lower()


def test_taxonomy_nodes_has_role_default_column(db_conn):
    row = db_conn.execute(
        """
        select data_type, is_nullable
        from information_schema.columns
        where table_name = 'taxonomy_nodes' and column_name = 'role_default'
        """
    ).fetchone()
    assert row is not None, "role_default column missing"
    dtype, nullable = row
    assert dtype == "text"
    assert nullable == "YES"


def test_taxonomy_nodes_has_is_defining_garnish_column(db_conn):
    row = db_conn.execute(
        """
        select data_type, is_nullable, column_default
        from information_schema.columns
        where table_name = 'taxonomy_nodes' and column_name = 'is_defining_garnish'
        """
    ).fetchone()
    assert row is not None, "is_defining_garnish column missing"
    dtype, nullable, default = row
    assert dtype == "boolean"
    assert nullable == "NO"
    assert "false" in (default or "").lower()
```

(`db_conn` fixture is added to `ingredients/tests/conftest.py` as part of this task — it opens a `psycopg.connect(test_db_url, autocommit=True)` connection and yields it. The inherited `test_db_url` fixture skips the test if `TEST_DB_URL` is unset. No `pytest.mark.db` marker is needed.)

- [ ] **Step 2: Run test to verify it fails**

```bash
cd ingredients && uv run pytest tests/test_dedup_migrations.py -v
```

Expected: 3 failures with messages like "is_cluster_node column missing".

- [ ] **Step 3: Write the migration**

Create `supabase/migrations/20260429160000_dedup_taxonomy_node_columns.sql`:

```sql
-- E's three taxonomy_nodes annotations. is_cluster_node marks the antichain
-- used for cluster-key rollup; role_default seeds role classification at
-- substance level; is_defining_garnish flags garnishes that change drink
-- identity (cocktail onion → Gibson, salt rim → Salty Dog, etc.).
--
-- All three default to "off"/null so existing nodes (and any auto-created
-- by D's mapper) are not retroactively promoted into the antichain. Curator
-- review owns every is_cluster_node = true and is_defining_garnish = true.

alter table taxonomy_nodes
  add column is_cluster_node     boolean not null default false,
  add column role_default        text,
  add column is_defining_garnish boolean not null default false;
```

- [ ] **Step 4: Apply the migration to the test DB**

The conftest auto-applies new migrations on session start. Force a fresh session by re-running pytest:

```bash
cd ingredients && uv run pytest tests/test_dedup_migrations.py -v
```

Expected: 3 PASS.

- [ ] **Step 5: Apply to dev DB**

```bash
supabase db reset --db-url "postgresql://postgres:postgres@192.168.65.254:54322/postgres" --yes
```

(The "tls error (server refused TLS connection)" tail is benign per CLAUDE.md.)

- [ ] **Step 6: Commit**

```bash
git add supabase/migrations/20260429160000_dedup_taxonomy_node_columns.sql ingredients/tests/test_dedup_migrations.py
git commit -m "Phase 0: taxonomy_nodes antichain + role_default + is_defining_garnish columns

Unblocks the curator track for the [E] taxonomy seed expansion.
Once this lands, seed-content PRs can mark the antichain, set
role_defaults, and mark defining garnishes in parallel with the
rest of [E]'s code work.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 7: Open PR for Phase 0**

```bash
gh pr create --title "Phase 0: dedup taxonomy_nodes columns (unblocks curator)" --body "$(cat <<'EOF'
Lands the three taxonomy_nodes columns ([E] depends on) as a standalone PR so the curator-gated taxonomy seed expansion can proceed in parallel with the rest of [E]'s code work. No code changes; one migration plus its schema test.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

After this PR merges, the curator track is unblocked and the rest of this plan begins.

---

## Phase 1: Remaining migrations

All migrations in this phase land together as part of [E]'s main code PR(s). The test file `ingredients/tests/test_dedup_migrations.py` grows one assertion per column/table.

### Task 1.1: Add role columns on `recipe_ingredients`

**Files:**
- Create: `supabase/migrations/20260429160100_dedup_recipe_ingredients_role.sql`
- Modify: `ingredients/tests/test_dedup_migrations.py`

- [ ] **Step 1: Add failing tests**

Append to `ingredients/tests/test_dedup_migrations.py`:

```python
def test_recipe_ingredients_has_role_columns(db_conn):
    cols = {
        row[0]: (row[1], row[2])
        for row in db_conn.execute(
            """
            select column_name, data_type, is_nullable
            from information_schema.columns
            where table_name = 'recipe_ingredients'
              and column_name in ('role', 'role_source')
            """
        ).fetchall()
    }
    assert "role" in cols
    assert cols["role"] == ("text", "YES")
    assert "role_source" in cols
    assert cols["role_source"] == ("text", "YES")


def test_recipe_ingredients_role_check_constraint_rejects_unknown(db_conn):
    with pytest.raises(Exception):
        db_conn.execute(
            """
            insert into recipe_ingredients
                (recipe_id, position, raw_text, parse_status, parser_version, role)
            values (1, 1, 'x', 'parsed', 'v1', 'not_a_real_role')
            """
        )
```

- [ ] **Step 2: Run tests, expect fail**

```bash
cd ingredients && uv run pytest tests/test_dedup_migrations.py::test_recipe_ingredients_has_role_columns tests/test_dedup_migrations.py::test_recipe_ingredients_role_check_constraint_rejects_unknown -v
```

Expected: both fail (columns don't exist).

- [ ] **Step 3: Write the migration**

Create `supabase/migrations/20260429160100_dedup_recipe_ingredients_role.sql`:

```sql
-- E's role tagging on recipe_ingredients. Roles are written by E's cluster
-- compute (which bundles role classification). They share the DEDUP_VERSION
-- lifecycle — role_source records where the assignment came from, but the
-- version stamp lives on the recipe row (recipes.dedup_version) since
-- cluster compute and role tagging always run together.

alter table recipe_ingredients
  add column role         text check (role in (
                            'base_spirit', 'modifier', 'citrus',
                            'sweetener', 'bitters', 'dilution', 'ice',
                            'garnish', 'wash', 'other')),
  add column role_source  text check (role_source in
                            ('default', 'rule', 'manual'));

create index recipe_ingredients_role_idx
  on recipe_ingredients (role) where role is not null;
```

- [ ] **Step 4: Run tests, expect pass**

```bash
cd ingredients && uv run pytest tests/test_dedup_migrations.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add supabase/migrations/20260429160100_dedup_recipe_ingredients_role.sql ingredients/tests/test_dedup_migrations.py
git commit -m "Migration: recipe_ingredients role + role_source columns

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 1.2: Add normalization columns on `recipes`

**Files:**
- Create: `supabase/migrations/20260429160200_dedup_recipes_normalize.sql`
- Modify: `ingredients/tests/test_dedup_migrations.py`

- [ ] **Step 1: Add failing tests**

Append:

```python
def test_recipes_has_normalize_columns(db_conn):
    cols = {
        row[0]: row[1]
        for row in db_conn.execute(
            """
            select column_name, data_type
            from information_schema.columns
            where table_name = 'recipes'
              and column_name in (
                'canonical_name', 'canonical_name_source',
                'normalizer_version', 'normalized_at'
              )
            """
        ).fetchall()
    }
    assert cols.get("canonical_name") == "text"
    assert cols.get("canonical_name_source") == "text"
    assert cols.get("normalizer_version") == "text"
    assert cols.get("normalized_at") == "timestamp with time zone"


def test_recipes_canonical_name_source_check_constraint(db_conn):
    # Inserting an out-of-vocabulary source should fail.
    with pytest.raises(Exception):
        db_conn.execute(
            """
            update recipes
               set canonical_name_source = 'bogus'
             where false  -- empty match still triggers the check
            """
        )
```

- [ ] **Step 2: Run tests, expect fail**

```bash
cd ingredients && uv run pytest tests/test_dedup_migrations.py -v
```

Expected: 2 new fails.

- [ ] **Step 3: Write the migration**

Create `supabase/migrations/20260429160200_dedup_recipes_normalize.sql`:

```sql
-- E's name-normalization output written directly onto recipes.
-- Mirrors D's pattern of writing resolution + source + version directly
-- onto the source table (recipe_ingredients for D). No separate cache.
--
-- Phase 1 (alias + lexical) writes 'alias' or 'lexical' or 'pending_llm'.
-- Phase 2 (LLM) flips 'pending_llm' to 'llm' or 'abstain'.

alter table recipes
  add column canonical_name        text,
  add column canonical_name_source text check (canonical_name_source in
                                     ('alias', 'lexical', 'pending_llm',
                                      'llm', 'abstain')),
  add column normalizer_version    text,
  add column normalized_at         timestamptz;

create index recipes_pending_normalize_idx
  on recipes (canonical_name_source) where canonical_name_source = 'pending_llm';

create index recipes_canonical_name_idx
  on recipes (canonical_name) where canonical_name is not null;
```

- [ ] **Step 4: Run tests, expect pass + commit**

```bash
cd ingredients && uv run pytest tests/test_dedup_migrations.py -v
git add supabase/migrations/20260429160200_dedup_recipes_normalize.sql ingredients/tests/test_dedup_migrations.py
git commit -m "Migration: recipes normalization columns (canonical_name + source + version)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 1.3: Add `cocktail_aliases` table

**Files:**
- Create: `supabase/migrations/20260429160300_dedup_cocktail_aliases.sql`
- Modify: `ingredients/tests/test_dedup_migrations.py`

- [ ] **Step 1: Add failing test**

```python
def test_cocktail_aliases_table_exists(db_conn):
    cols = {
        row[0]: row[1]
        for row in db_conn.execute(
            """
            select column_name, data_type
            from information_schema.columns
            where table_name = 'cocktail_aliases'
            """
        ).fetchall()
    }
    assert cols.get("alias") == "text"
    assert cols.get("canonical_name") == "text"
    assert cols.get("source") == "text"
    assert cols.get("created_at") == "timestamp with time zone"


def test_cocktail_aliases_pkey_is_alias_canonical(db_conn):
    rows = db_conn.execute(
        """
        select a.attname
        from pg_index i
        join pg_attribute a on a.attrelid = i.indrelid and a.attnum = any(i.indkey)
        where i.indrelid = 'cocktail_aliases'::regclass and i.indisprimary
        order by a.attnum
        """
    ).fetchall()
    assert [r[0] for r in rows] == ["alias", "canonical_name"]
```

- [ ] **Step 2: Run, expect fail**

- [ ] **Step 3: Write the migration**

Create `supabase/migrations/20260429160300_dedup_cocktail_aliases.sql`:

```sql
-- Cocktail alias table — exact analogue of taxonomy_aliases. Used by
-- E's Phase-1 alias-layer lookups; grown by Phase-2 LLM resolutions.

create table cocktail_aliases (
  alias          text not null,
  canonical_name text not null,
  source         text not null check (source in ('seed', 'llm', 'manual')),
  created_at     timestamptz not null default now(),
  primary key (alias, canonical_name)
);

create index cocktail_aliases_canonical_idx
  on cocktail_aliases (canonical_name);
```

- [ ] **Step 4: Run + commit**

```bash
cd ingredients && uv run pytest tests/test_dedup_migrations.py -v
git add supabase/migrations/20260429160300_dedup_cocktail_aliases.sql ingredients/tests/test_dedup_migrations.py
git commit -m "Migration: cocktail_aliases table for cocktail-name resolution

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 1.4: Add `recipe_clusters`, recipes assignment columns, `recipe_variants` view, update `recipes_public`

**Files:**
- Create: `supabase/migrations/20260429160400_dedup_clusters.sql`
- Modify: `ingredients/tests/test_dedup_migrations.py`

- [ ] **Step 1: Add failing tests**

```python
def test_recipe_clusters_table_exists(db_conn):
    cols = {
        row[0]: row[1]
        for row in db_conn.execute(
            """
            select column_name, data_type
            from information_schema.columns
            where table_name = 'recipe_clusters'
            """
        ).fetchall()
    }
    assert cols.get("id") == "bigint"
    assert cols.get("cluster_key") == "text"
    assert cols.get("canonical_name") == "text"
    assert cols.get("ingredient_set") == "jsonb"
    assert cols.get("representative_recipe_id") == "bigint"
    assert cols.get("recipe_count") == "integer"
    assert cols.get("source_count") == "integer"
    assert cols.get("dedup_version") == "text"


def test_recipes_has_cluster_assignment_columns(db_conn):
    cols = {
        row[0]: row[1]
        for row in db_conn.execute(
            """
            select column_name, data_type
            from information_schema.columns
            where table_name = 'recipes'
              and column_name in ('cluster_id', 'variant_key', 'dedup_version')
            """
        ).fetchall()
    }
    assert cols.get("cluster_id") == "bigint"
    assert cols.get("variant_key") == "text"
    assert cols.get("dedup_version") == "text"


def test_recipe_variants_view_exists(db_conn):
    row = db_conn.execute(
        """
        select table_name from information_schema.views
        where table_name = 'recipe_variants'
        """
    ).fetchone()
    assert row is not None


def test_recipes_public_view_includes_cluster_id_and_variant_key(db_conn):
    cols = {
        row[0]
        for row in db_conn.execute(
            """
            select column_name from information_schema.columns
            where table_name = 'recipes_public'
            """
        ).fetchall()
    }
    assert "cluster_id" in cols
    assert "variant_key" in cols
```

- [ ] **Step 2: Run, expect fail**

- [ ] **Step 3: Write the migration**

Create `supabase/migrations/20260429160400_dedup_clusters.sql`:

```sql
-- E's cluster identity table + recipe assignment + variants view +
-- update recipes_public to expose cluster_id and variant_key.

create table recipe_clusters (
  id                       bigserial primary key,
  cluster_key              text unique not null,
  canonical_name           text not null,
  ingredient_set           jsonb not null,
  representative_recipe_id bigint references recipes(id),
  recipe_count             int not null default 0,
  source_count             int not null default 0,
  dedup_version            text not null,
  created_at               timestamptz not null default now()
);

create index recipe_clusters_canonical_idx on recipe_clusters (canonical_name);

alter table recipes
  add column cluster_id    bigint references recipe_clusters(id),
  add column variant_key   text,
  add column dedup_version text;

create index recipes_cluster_idx
  on recipes (cluster_id) where cluster_id is not null;
create index recipes_cluster_variant_idx
  on recipes (cluster_id, variant_key) where cluster_id is not null;

-- Variants are derived: equivalence classes of recipes sharing
-- (cluster_id, variant_key). Materializing as a table is a follow-up
-- if query patterns prove the aggregation is hot.
create view recipe_variants as
  select
    cluster_id,
    variant_key,
    min(id)                       as representative_recipe_id,
    count(*)                      as recipe_count,
    count(distinct site)          as source_count
  from recipes
  where cluster_id is not null and variant_key is not null
  group by cluster_id, variant_key;

-- Update the public projection. recipes_public was created in
-- 20260424054315_recipes_public_security_invoker.sql; we replace it.
create or replace view recipes_public as
  select id, source_url, site, name, author, image_url, jsonld,
         cluster_id, variant_key
  from recipes;
```

- [ ] **Step 4: Run + commit**

```bash
cd ingredients && uv run pytest tests/test_dedup_migrations.py -v
git add supabase/migrations/20260429160400_dedup_clusters.sql ingredients/tests/test_dedup_migrations.py
git commit -m "Migration: recipe_clusters, recipes assignment cols, recipe_variants view

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 2: Package skeleton + foundations

### Task 2.1: Create `dedup` package + version constants

**Files:**
- Create: `ingredients/src/ingredients/dedup/__init__.py`
- Create: `ingredients/src/ingredients/dedup/version.py`

- [ ] **Step 1: Create `__init__.py`**

```python
"""Recipe dedup pipeline. Reads D's mapper output, writes cluster + variant
identities onto recipes. See docs/superpowers/specs/2026-04-29-recipe-dedup-design.md
for the design."""
```

- [ ] **Step 2: Create `version.py`**

```python
"""Version constants for E's pipeline stages.

Bump NORMALIZER_VERSION when name-normalization rules change (alias
handling, stop-word list, lexical thresholds, prompt). Bumping requires
re-running normalize-names --reset --except-version <prior>.

Bump DEDUP_VERSION when role classifier rules change OR cluster/variant
key shape changes OR INCLUDED_ROLES changes OR is_defining_garnish allowlist
changes. Bumping requires re-running cluster --reset --except-version <prior>.
"""

from __future__ import annotations

NORMALIZER_VERSION = "v1"
DEDUP_VERSION = "v1"
```

- [ ] **Step 3: Commit**

```bash
git add ingredients/src/ingredients/dedup/__init__.py ingredients/src/ingredients/dedup/version.py
git commit -m "dedup: package skeleton + version constants

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 2.2: Implement `normalize_cocktail_name`

**Files:**
- Create: `ingredients/src/ingredients/dedup/normalize.py`
- Test: `ingredients/tests/test_dedup_normalize.py`

- [ ] **Step 1: Write the failing tests**

Create `ingredients/tests/test_dedup_normalize.py`:

```python
import pytest
from ingredients.dedup.normalize import normalize_cocktail_name


@pytest.mark.parametrize("raw, expected", [
    ("Negroni", "negroni"),
    ("The Negroni", "negroni"),
    ("Classic Negroni", "negroni"),
    ("Negroni Cocktail", "negroni"),
    ("Best Negroni Recipe", "negroni"),
    ("Perfect Negroni", "negroni"),
    ("How to Make a Negroni", "negroni"),
    ("Negroni (Italian Aperitivo)", "negroni"),
    ("  Negroni  ", "negroni"),
    ("Old Fashioned", "old fashioned"),
    ("THE OLD FASHIONED", "old fashioned"),
    ("Old-Fashioned", "old fashioned"),
])
def test_normalize_strips_editorial_noise(raw, expected):
    assert normalize_cocktail_name(raw) == expected


def test_preserves_drink_modifier_prefixes():
    # Modifier prefixes that mark a real variant must NOT be stripped.
    assert normalize_cocktail_name("Mezcal Negroni") == "mezcal negroni"
    assert normalize_cocktail_name("Smoked Old Fashioned") == "smoked old fashioned"
    assert normalize_cocktail_name("Hemingway Daiquiri") == "hemingway daiquiri"
    assert normalize_cocktail_name("White Negroni") == "white negroni"


def test_handles_empty_or_none():
    assert normalize_cocktail_name(None) == ""
    assert normalize_cocktail_name("") == ""
    assert normalize_cocktail_name("   ") == ""


def test_strips_recipe_or_cocktail_when_trailing():
    assert normalize_cocktail_name("Manhattan Recipe") == "manhattan"
    assert normalize_cocktail_name("Manhattan Cocktail") == "manhattan"
    # But NOT in the middle (defensive against false-strip)
    assert normalize_cocktail_name("Recipe for Manhattan") == "manhattan"
```

- [ ] **Step 2: Run, expect ImportError / fail**

```bash
cd ingredients && uv run pytest tests/test_dedup_normalize.py -v
```

- [ ] **Step 3: Implement `normalize.py`**

Create `ingredients/src/ingredients/dedup/normalize.py`:

```python
"""Canonical normalization for cocktail-name lookups.

Wraps mapping.normalize.normalize_name (lowercase + whitespace) and adds
cocktail-name specific cleanup: stop-word stripping ('the', 'best',
'classic', 'cocktail', 'recipe'), parenthetical removal, hyphen→space
folding. Stop-words apply only when they appear as standalone tokens
at the start, end, or surrounding the rest of the name; embedded "the"
inside a longer phrase ('Death in the Afternoon') is preserved.

This is the function the alias_layer keys against: a cocktail_aliases.alias
row is itself the output of this function applied to some raw title.
"""

from __future__ import annotations

import re

from ingredients.mapping.normalize import normalize_name as _base_normalize

# Tokens stripped wherever they appear as standalone words.
_STOP_WORDS = frozenset({
    "the", "a", "an",
    "best", "perfect", "classic", "ultimate", "easy", "simple", "quick",
    "cocktail", "recipe",
    "how", "to", "make", "for",
})

_PAREN = re.compile(r"\([^)]*\)")
_NON_WORD_PUNCT = re.compile(r"[^\w\s]")
_WS = re.compile(r"\s+")


def normalize_cocktail_name(raw: str | None) -> str:
    if raw is None:
        return ""
    s = _base_normalize(raw)
    if not s:
        return ""
    # Drop parentheticals.
    s = _PAREN.sub(" ", s)
    # Replace non-word punctuation with whitespace; preserve word characters.
    s = _NON_WORD_PUNCT.sub(" ", s)
    # Tokenize, strip stop-words, rejoin.
    tokens = [t for t in s.split() if t and t not in _STOP_WORDS]
    return _WS.sub(" ", " ".join(tokens)).strip()
```

- [ ] **Step 4: Run tests, expect pass**

```bash
cd ingredients && uv run pytest tests/test_dedup_normalize.py -v
```

- [ ] **Step 5: Commit**

```bash
git add ingredients/src/ingredients/dedup/normalize.py ingredients/tests/test_dedup_normalize.py
git commit -m "dedup: normalize_cocktail_name with stop-word + parenthetical stripping

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 2.3: Add `dedup/types.py`

**Files:**
- Create: `ingredients/src/ingredients/dedup/types.py`
- Test: none yet (types module is exercised by the layers that use it)

- [ ] **Step 1: Write the file**

```python
"""Typed cascade results for cocktail-name resolution.

Mirrors the shape of mapping/types.py; the difference is that the resolved
value is a `canonical_name: str` rather than a `taxonomy_node_id: int`,
because cocktail names have no taxonomy node — they're the keys of an
alias-only universe.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

NormalizerSource = Literal["alias", "lexical", "pending_llm", "llm", "abstain"]


@dataclass(frozen=True)
class Resolved:
    canonical_name: str
    source: NormalizerSource     # 'alias' | 'lexical' | 'llm'


@dataclass(frozen=True)
class Pending:
    """Phase 1 didn't resolve; row is queued for Phase 2."""


@dataclass(frozen=True)
class Abstain:
    """Phase 2 considered the name and declined to assign a canonical."""


@dataclass(frozen=True)
class NameProposal:
    """LLM proposed a new canonical name not yet in cocktail_aliases.

    The orchestrator auto-adds the alias with source='llm' and emits the
    Resolved result downstream. Hallucination concerns are surfaced via
    the audit pass, not via a human-review queue (form-style proposals
    aren't needed at v1; see spec).
    """
    canonical_name: str


Phase1Result = Resolved | Pending
Phase2Result = Resolved | NameProposal | Abstain
```

- [ ] **Step 2: Commit**

```bash
git add ingredients/src/ingredients/dedup/types.py
git commit -m "dedup: typed cascade results (Resolved/Pending/Abstain/NameProposal)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 2.4: Build `eval_fixture.py`

The fixture is a small in-memory taxonomy + cocktail aliases + recipes used by every dedup test that needs DB integration. Mirrors `mapping/eval_fixture.py`. Lets tests run against TEST_DB_URL without depending on production seed state.

**Files:**
- Create: `ingredients/src/ingredients/dedup/eval_fixture.py`
- Test: `ingredients/tests/test_dedup_eval_fixture.py`

- [ ] **Step 1: Write the failing test**

```python
"""Smoke test for the dedup eval fixture. Real exercise happens in the
layer/orchestrator tests that consume it."""

import pytest

from ingredients.dedup.eval_fixture import seed_dedup_fixture


def test_seed_dedup_fixture_creates_taxonomy_and_aliases(db_conn):
    ids = seed_dedup_fixture(db_conn)

    assert "gin" in ids
    assert "london_dry_gin" in ids
    assert "campari" in ids
    assert "sweet_vermouth" in ids
    assert "angostura_bitters" in ids
    assert "lemon_juice" in ids
    assert "ice" in ids

    # Antichain markers
    cluster_nodes = {
        row[0] for row in db_conn.execute(
            "select slug from taxonomy_nodes where is_cluster_node = true"
        ).fetchall()
    }
    assert "london_dry_gin" in cluster_nodes
    assert "campari" in cluster_nodes
    assert "sweet_vermouth" in cluster_nodes
    assert "bourbon" in cluster_nodes
    assert "rye_whiskey" in cluster_nodes
    assert "gin" not in cluster_nodes  # navigation parent, not antichain

    # role_default
    role_defaults = {
        row[0]: row[1]
        for row in db_conn.execute(
            "select slug, role_default from taxonomy_nodes where role_default is not null"
        ).fetchall()
    }
    assert role_defaults.get("london_dry_gin") == "base_spirit"
    assert role_defaults.get("campari") == "modifier"
    assert role_defaults.get("sweet_vermouth") == "modifier"
    assert role_defaults.get("angostura_bitters") == "bitters"
    assert role_defaults.get("lemon_juice") == "citrus"
    assert role_defaults.get("simple_syrup") == "sweetener"
    assert role_defaults.get("soda_water") == "dilution"
    assert role_defaults.get("ice") == "ice"

    # Cocktail aliases seeded
    aliases = {
        row[0]: row[1]
        for row in db_conn.execute(
            "select alias, canonical_name from cocktail_aliases"
        ).fetchall()
    }
    assert aliases.get("negroni") == "negroni"
    assert aliases.get("old fashioned") == "old fashioned"
    assert aliases.get("manhattan") == "manhattan"
```

- [ ] **Step 2: Run, expect fail**

- [ ] **Step 3: Implement `eval_fixture.py`**

```python
"""In-memory dedup fixture: small taxonomy + antichain markers + cocktail
aliases. Loaded into TEST_DB_URL by tests via seed_dedup_fixture(conn).

Returns a slug→id dict for tests to look up node_ids by name.

Mirrors mapping/eval_fixture.py shape. Adds antichain-related columns
that mapping/eval_fixture didn't need.
"""

from __future__ import annotations

import psycopg

# Each tuple: (slug, display_name, role, is_cluster_node, role_default,
#              is_defining_garnish, parent_slug_or_None)
_NODES = [
    # Spirit families (parents — not antichain)
    ("whiskey", "Whiskey", None, False, None, False, None),
    ("gin", "Gin", None, False, None, False, None),
    ("rum", "Rum", None, False, None, False, None),
    ("vermouth", "Vermouth", None, False, None, False, None),
    ("amaro", "Amaro", None, False, None, False, None),
    ("bitters", "Bitters", None, False, None, False, None),
    # Whiskey subtypes (antichain)
    ("bourbon", "Bourbon", None, True, "base_spirit", False, "whiskey"),
    ("rye_whiskey", "Rye Whiskey", None, True, "base_spirit", False, "whiskey"),
    # Gin sub-styles (antichain)
    ("london_dry_gin", "London Dry Gin", None, True, "base_spirit", False, "gin"),
    ("old_tom_gin", "Old Tom Gin", None, True, "base_spirit", False, "gin"),
    # Rum subtypes
    ("white_rum", "White Rum", None, True, "base_spirit", False, "rum"),
    # Vermouth subtypes (antichain)
    ("sweet_vermouth", "Sweet Vermouth", None, True, "modifier", False, "vermouth"),
    ("dry_vermouth", "Dry Vermouth", None, True, "modifier", False, "vermouth"),
    # Amari (antichain — substance-modeled)
    ("campari", "Campari", None, True, "modifier", False, "amaro"),
    ("aperol", "Aperol", None, True, "modifier", False, "amaro"),
    # Bitters (antichain — substance-modeled)
    ("angostura_bitters", "Angostura Bitters", None, True, "bitters", False, "bitters"),
    ("peychauds_bitters", "Peychaud's Bitters", None, True, "bitters", False, "bitters"),
    ("orange_bitters", "Orange Bitters", None, True, "bitters", False, "bitters"),
    # Citrus juices (antichain)
    ("lemon_juice", "Lemon Juice", None, True, "citrus", False, None),
    ("lime_juice", "Lime Juice", None, True, "citrus", False, None),
    # Sweeteners
    ("simple_syrup", "Simple Syrup", None, True, "sweetener", False, None),
    # Dilution + ice
    ("soda_water", "Soda Water", None, True, "dilution", False, None),
    ("ice", "Ice", None, True, "ice", False, None),
    # Garnish: one defining (cocktail_onion), one stylistic (lemon_twist)
    ("cocktail_onion", "Cocktail Onion", None, True, "garnish", True, None),
    ("lemon_twist", "Lemon Twist", None, False, "garnish", False, None),
    # Brand-level (NOT antichain)
    ("tanqueray", "Tanqueray", "brand", False, None, False, "london_dry_gin"),
    ("bombay_sapphire", "Bombay Sapphire", "brand", False, None, False, "london_dry_gin"),
]

_ALIASES_TAX = [
    ("rye", "rye_whiskey"),
    ("bourbon whiskey", "bourbon"),
    ("london dry", "london_dry_gin"),
    ("rosso vermouth", "sweet_vermouth"),
    ("italian vermouth", "sweet_vermouth"),
    ("french vermouth", "dry_vermouth"),
    ("angostura", "angostura_bitters"),
    ("peychauds", "peychauds_bitters"),
    ("peychaud's", "peychauds_bitters"),
]

_COCKTAIL_ALIASES = [
    # canonical → list of aliases (each is post-normalize_cocktail_name form)
    ("negroni", ["negroni"]),
    ("old fashioned", ["old fashioned", "old-fashioned"]),
    ("manhattan", ["manhattan"]),
    ("daiquiri", ["daiquiri", "daquiri"]),  # the typo is a useful seed
    ("martini", ["martini"]),
    ("gimlet", ["gimlet"]),
    ("whiskey sour", ["whiskey sour"]),
    ("tom collins", ["tom collins"]),
    ("aperol negroni", ["aperol negroni"]),
    ("white negroni", ["white negroni"]),
    ("hemingway daiquiri", ["hemingway daiquiri"]),
]


def seed_dedup_fixture(conn: psycopg.Connection) -> dict[str, int]:
    """Insert the fixture taxonomy + cocktail aliases. Idempotent: ON
    CONFLICT clauses make it safe to call multiple times in a session.

    Returns slug -> node_id mapping for the inserted/existing nodes.
    """
    ids: dict[str, int] = {}
    for slug, display, role, is_cluster, role_default, def_garnish, _parent in _NODES:
        row = conn.execute(
            """
            insert into taxonomy_nodes
                (slug, display_name, role, is_cluster_node, role_default,
                 is_defining_garnish)
            values (%s, %s, %s, %s, %s, %s)
            on conflict (slug) do update
                set is_cluster_node = excluded.is_cluster_node,
                    role_default    = excluded.role_default,
                    is_defining_garnish = excluded.is_defining_garnish
            returning id
            """,
            (slug, display, role, is_cluster, role_default, def_garnish),
        ).fetchone()
        ids[slug] = row[0]

    for slug, display, role, is_cluster, role_default, def_garnish, parent in _NODES:
        if parent is None:
            continue
        conn.execute(
            """
            insert into taxonomy_edges (parent_id, child_id)
            values (%s, %s)
            on conflict do nothing
            """,
            (ids[parent], ids[slug]),
        )

    for alias, slug in _ALIASES_TAX:
        conn.execute(
            """
            insert into taxonomy_aliases (alias, node_id)
            values (%s, %s)
            on conflict do nothing
            """,
            (alias, ids[slug]),
        )

    for canonical, aliases in _COCKTAIL_ALIASES:
        for a in aliases:
            conn.execute(
                """
                insert into cocktail_aliases (alias, canonical_name, source)
                values (%s, %s, 'seed')
                on conflict do nothing
                """,
                (a, canonical),
            )
    conn.commit()
    return ids
```

- [ ] **Step 4: Wire a `dedup_fixture` pytest fixture**

Append to `ingredients/tests/conftest.py` (read existing first to see fixture style):

```python
@pytest.fixture
def dedup_fixture(db_conn):
    """Seed the dedup fixture taxonomy + cocktail_aliases into TEST_DB_URL.
    Yields (conn, ids). Tables are truncated on session teardown by the
    existing db_conn fixture."""
    from ingredients.dedup.eval_fixture import seed_dedup_fixture
    ids = seed_dedup_fixture(db_conn)
    return db_conn, ids
```

(Inspect `ingredients/tests/conftest.py` first; if it already has a similar fixture for the mapping tests, model the dedup one after it.)

- [ ] **Step 5: Run tests, expect pass**

```bash
cd ingredients && uv run pytest tests/test_dedup_eval_fixture.py -v
```

- [ ] **Step 6: Commit**

```bash
git add ingredients/src/ingredients/dedup/eval_fixture.py ingredients/tests/test_dedup_eval_fixture.py ingredients/tests/conftest.py
git commit -m "dedup: eval fixture (small taxonomy + antichain + cocktail aliases)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 3: Phase-1 normalizer (alias + lexical)

### Task 3.1: `dedup/alias_layer.py` — exact match against `cocktail_aliases`

**Files:**
- Create: `ingredients/src/ingredients/dedup/alias_layer.py`
- Test: `ingredients/tests/test_dedup_alias_layer.py`

This task mirrors `mapping/alias_layer.py` exactly, swapping the table and the resolved value.

- [ ] **Step 1: Write failing tests**

```python
import pytest

from ingredients.dedup.alias_layer import resolve_alias
from ingredients.dedup.types import Pending, Resolved


def test_exact_alias_hit_returns_resolved(dedup_fixture):
    conn, _ = dedup_fixture
    result = resolve_alias(conn, "negroni")
    assert isinstance(result, Resolved)
    assert result.canonical_name == "negroni"
    assert result.source == "alias"


def test_typo_seed_resolves(dedup_fixture):
    conn, _ = dedup_fixture
    # 'daquiri' is seeded as an alias of 'daiquiri'
    result = resolve_alias(conn, "daquiri")
    assert isinstance(result, Resolved)
    assert result.canonical_name == "daiquiri"


def test_unknown_string_returns_pending(dedup_fixture):
    conn, _ = dedup_fixture
    result = resolve_alias(conn, "fancy unknown thing")
    assert isinstance(result, Pending)


def test_empty_string_returns_pending(dedup_fixture):
    conn, _ = dedup_fixture
    assert isinstance(resolve_alias(conn, ""), Pending)
```

- [ ] **Step 2: Run, expect fail**

- [ ] **Step 3: Implement**

```python
"""Phase 1, Layer 1 — exact match against cocktail_aliases.

Caller passes a name already through normalize_cocktail_name. Returns
Resolved(source='alias') or Pending. Never raises on miss.

Mirrors mapping/alias_layer.py shape.
"""

from __future__ import annotations

import psycopg

from .types import Pending, Phase1Result, Resolved


def resolve_alias(conn: psycopg.Connection, normalized_name: str) -> Phase1Result:
    if not normalized_name:
        return Pending()
    row = conn.execute(
        "select canonical_name from cocktail_aliases where alias = %s limit 1",
        (normalized_name,),
    ).fetchone()
    if row is None:
        return Pending()
    return Resolved(canonical_name=row[0], source="alias")
```

- [ ] **Step 4: Run + commit**

```bash
cd ingredients && uv run pytest tests/test_dedup_alias_layer.py -v
git add ingredients/src/ingredients/dedup/alias_layer.py ingredients/tests/test_dedup_alias_layer.py
git commit -m "dedup: alias_layer (Phase 1 Layer 1, cocktail_aliases lookup)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 3.2: `dedup/lexical_layer.py` — pg_trgm against `cocktail_aliases`

**Files:**
- Create: `ingredients/src/ingredients/dedup/lexical_layer.py`
- Test: `ingredients/tests/test_dedup_lexical_layer.py`

Mirrors `mapping/lexical_layer.py`. Same thresholds (`LEXICAL_MIN_SIM=0.75`, `LEXICAL_RATIO=1.5` — **but** see the threshold note at the end of the task; cocktail names may want tighter tuning).

- [ ] **Step 1: Write failing tests**

```python
import pytest

from ingredients.dedup.lexical_layer import resolve_lexical, lexical_candidates
from ingredients.dedup.types import Pending, Resolved


def test_close_match_resolves(dedup_fixture):
    # 'negronni' (extra n) should match 'negroni' via trgm
    conn, _ = dedup_fixture
    result = resolve_lexical(conn, "negronni")
    assert isinstance(result, Resolved)
    assert result.canonical_name == "negroni"
    assert result.source == "lexical"


def test_no_match_returns_pending(dedup_fixture):
    conn, _ = dedup_fixture
    result = resolve_lexical(conn, "completely unrelated phrase")
    assert isinstance(result, Pending)


def test_ambiguous_match_returns_pending(dedup_fixture):
    # If two candidates score within the ratio threshold of each other,
    # the layer abstains so Phase 2 / human can decide. Construct a name
    # roughly equidistant between two seeded canonicals.
    conn, _ = dedup_fixture
    # 'martini gimlet' shares trgrams with both 'martini' and 'gimlet'.
    result = resolve_lexical(conn, "martini gimlet")
    assert isinstance(result, Pending)


def test_lexical_candidates_returns_top_n_with_scores(dedup_fixture):
    conn, _ = dedup_fixture
    cands = lexical_candidates(conn, "negronni", limit=5)
    assert len(cands) >= 1
    assert cands[0]["canonical_name"] == "negroni"
    assert "similarity" in cands[0]
    assert 0.0 <= cands[0]["similarity"] <= 1.0
```

- [ ] **Step 2: Run, expect fail**

- [ ] **Step 3: Implement**

```python
"""Phase 1, Layer 2 — pg_trgm similarity over cocktail_aliases.

Mirrors mapping/lexical_layer.py. Differences:
  * Searches cocktail_aliases.alias (instead of taxonomy_nodes.display_name +
    taxonomy_aliases.alias).
  * Returns canonical_name (text) on hit, not taxonomy_node_id.
  * Same fail-closed thresholds (LEXICAL_MIN_SIM, LEXICAL_RATIO). Tune via
    eval-set if cocktail-name distribution differs materially from
    ingredient-name distribution.
"""

from __future__ import annotations

from typing import Any

import psycopg

from .types import Pending, Phase1Result, Resolved

LEXICAL_MIN_SIM = 0.75
LEXICAL_RATIO = 1.5

_CANDIDATE_LIMIT_DEFAULT = 20


def _candidates_sql(limit: int) -> str:
    return f"""
        select canonical_name,
               max(similarity(alias, %s)) as sim
        from cocktail_aliases
        group by canonical_name
        order by sim desc
        limit {int(limit)}
    """


def lexical_candidates(
    conn: psycopg.Connection, normalized_name: str, *, limit: int = _CANDIDATE_LIMIT_DEFAULT,
) -> list[dict[str, Any]]:
    if not normalized_name:
        return []
    rows = conn.execute(
        _candidates_sql(limit), (normalized_name,),
    ).fetchall()
    return [
        {"canonical_name": r[0], "similarity": float(r[1])}
        for r in rows
    ]


def resolve_lexical(conn: psycopg.Connection, normalized_name: str) -> Phase1Result:
    cands = lexical_candidates(conn, normalized_name, limit=2)
    if not cands or cands[0]["similarity"] < LEXICAL_MIN_SIM:
        return Pending()
    if len(cands) >= 2:
        top1, top2 = cands[0]["similarity"], cands[1]["similarity"]
        if top2 > 0 and top1 < LEXICAL_RATIO * top2:
            return Pending()
    return Resolved(canonical_name=cands[0]["canonical_name"], source="lexical")
```

- [ ] **Step 4: Run + commit**

```bash
cd ingredients && uv run pytest tests/test_dedup_lexical_layer.py -v
git add ingredients/src/ingredients/dedup/lexical_layer.py ingredients/tests/test_dedup_lexical_layer.py
git commit -m "dedup: lexical_layer (Phase 1 Layer 2, pg_trgm over cocktail_aliases)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 3.3: `dedup/db.py` — DB helpers for normalizer

**Files:**
- Create: `ingredients/src/ingredients/dedup/db.py`
- Test: `ingredients/tests/test_dedup_db.py`

- [ ] **Step 1: Write failing tests**

```python
"""DB helpers for E. Each function takes a psycopg conn so tests share
production code paths via TEST_DB_URL."""

import pytest

from ingredients.dedup.db import (
    fetch_unresolved_recipe_names,
    write_normalization,
    write_pending_normalize,
    write_normalize_abstain,
    add_cocktail_alias,
    fetch_pending_canonical_names,
)
from ingredients.dedup.version import NORMALIZER_VERSION


def test_fetch_unresolved_recipe_names_excludes_already_normalized(dedup_fixture, db_conn):
    conn, _ = dedup_fixture
    # Seed two recipes; one already normalized at current version.
    db_conn.execute("""
        insert into recipes (id, source_url, site, name, jsonld, fetched_at)
        values
            (1001, 'http://x/n1', 'punch', 'The Negroni', '{}'::jsonb, now()),
            (1002, 'http://x/n2', 'punch', 'Daquiri', '{}'::jsonb, now()),
            (1003, 'http://x/n3', 'punch', 'Old Fashioned', '{}'::jsonb, now())
        on conflict (source_url) do nothing
    """)
    db_conn.execute("""
        update recipes set canonical_name = 'old fashioned',
                           canonical_name_source = 'alias',
                           normalizer_version = %s, normalized_at = now()
         where id = 1003
    """, (NORMALIZER_VERSION,))
    db_conn.commit()
    names = fetch_unresolved_recipe_names(db_conn, normalizer_version=NORMALIZER_VERSION)
    assert "the negroni" in names or "negroni" in names  # depends on whether normalize is applied here
    # 1003 is excluded because it's already at current version
    assert "old fashioned" not in names


def test_write_normalization_updates_all_rows_sharing_name(dedup_fixture, db_conn):
    conn, _ = dedup_fixture
    db_conn.execute("""
        insert into recipes (id, source_url, site, name, jsonld, fetched_at) values
            (2001, 'http://x/a', 'punch', 'Negroni', '{}'::jsonb, now()),
            (2002, 'http://x/b', 'imbibe', 'Negroni', '{}'::jsonb, now())
        on conflict (source_url) do nothing
    """)
    db_conn.commit()
    n = write_normalization(
        db_conn, raw_name="Negroni", normalized="negroni",
        canonical_name="negroni", source="alias",
        normalizer_version=NORMALIZER_VERSION,
    )
    assert n == 2
    canonicals = db_conn.execute(
        "select canonical_name from recipes where id in (2001, 2002)"
    ).fetchall()
    assert all(r[0] == "negroni" for r in canonicals)


def test_add_cocktail_alias_idempotent(dedup_fixture, db_conn):
    conn, _ = dedup_fixture
    add_cocktail_alias(db_conn, alias="the best negroni", canonical_name="negroni", source="llm")
    add_cocktail_alias(db_conn, alias="the best negroni", canonical_name="negroni", source="llm")
    rows = db_conn.execute(
        "select count(*) from cocktail_aliases where alias = %s and canonical_name = %s",
        ("the best negroni", "negroni"),
    ).fetchone()
    assert rows[0] == 1
```

- [ ] **Step 2: Run, expect fail**

- [ ] **Step 3: Implement `dedup/db.py`**

```python
"""DB access for E's name normalizer + cluster compute. Pure-SQL helpers;
caller passes the psycopg connection.

Naming convention: the orchestrator works in two registers: the *raw*
recipes.name as it appears on the row, and the *normalized* form
produced by normalize_cocktail_name. Layer-1 and Layer-2 lookups key
on the normalized form. write_normalization fans the resolution out
to every recipes row whose lower(trim(name)) matches the raw form OR
whose normalize_cocktail_name(name) matches the normalized form.
"""

from __future__ import annotations

import psycopg

from .normalize import normalize_cocktail_name
from .types import NormalizerSource


def fetch_unresolved_recipe_names(
    conn: psycopg.Connection, *, normalizer_version: str,
    site: str | None = None, limit: int | None = None,
) -> list[str]:
    """Distinct normalized names lacking a current-version normalization.

    Excludes recipes whose canonical_name_source is 'pending_llm' at the
    current version — those are queued for Phase 2, not Phase 1.
    """
    params: list[object] = [normalizer_version, normalizer_version]
    site_clause = ""
    if site is not None:
        site_clause = "and site = %s"
        params.append(site)

    sql = f"""
        select distinct name
        from recipes
        where name is not null
          and (normalizer_version is null
               or (normalizer_version <> %s
                   and canonical_name_source <> 'pending_llm')
               or (normalizer_version = %s
                   and canonical_name_source is null))
          {site_clause}
        order by name
    """
    if limit is not None:
        sql += " limit %s"
        params.append(limit)
    return [row[0] for row in conn.execute(sql, params).fetchall()]


def fetch_pending_canonical_names(
    conn: psycopg.Connection, *, normalizer_version: str,
    limit: int | None = None,
) -> list[str]:
    """Distinct *raw* names whose current-version row is at canonical_name_source='pending_llm'."""
    sql = """
        select distinct name from recipes
        where canonical_name_source = 'pending_llm'
          and normalizer_version = %s
        order by name
    """
    params: list[object] = [normalizer_version]
    if limit is not None:
        sql += " limit %s"
        params.append(limit)
    return [row[0] for row in conn.execute(sql, params).fetchall()]


def write_normalization(
    conn: psycopg.Connection, *, raw_name: str, normalized: str,
    canonical_name: str, source: NormalizerSource, normalizer_version: str,
) -> int:
    """Stamp every recipes row whose name matches the raw form. Returns rowcount."""
    cur = conn.execute(
        """
        update recipes
           set canonical_name        = %s,
               canonical_name_source = %s,
               normalizer_version    = %s,
               normalized_at         = now()
         where name = %s
        """,
        (canonical_name, source, normalizer_version, raw_name),
    )
    conn.commit()
    return cur.rowcount


def write_pending_normalize(
    conn: psycopg.Connection, *, raw_name: str, normalizer_version: str,
) -> int:
    cur = conn.execute(
        """
        update recipes
           set canonical_name        = null,
               canonical_name_source = 'pending_llm',
               normalizer_version    = %s,
               normalized_at         = now()
         where name = %s
        """,
        (normalizer_version, raw_name),
    )
    conn.commit()
    return cur.rowcount


def write_normalize_abstain(
    conn: psycopg.Connection, *, raw_name: str, normalizer_version: str,
) -> int:
    cur = conn.execute(
        """
        update recipes
           set canonical_name        = null,
               canonical_name_source = 'abstain',
               normalizer_version    = %s,
               normalized_at         = now()
         where name = %s
        """,
        (normalizer_version, raw_name),
    )
    conn.commit()
    return cur.rowcount


def add_cocktail_alias(
    conn: psycopg.Connection, *, alias: str, canonical_name: str,
    source: str = "llm",
) -> None:
    conn.execute(
        """
        insert into cocktail_aliases (alias, canonical_name, source)
        values (%s, %s, %s)
        on conflict do nothing
        """,
        (alias, canonical_name, source),
    )
    conn.commit()
```

- [ ] **Step 4: Run + commit**

```bash
cd ingredients && uv run pytest tests/test_dedup_db.py -v
git add ingredients/src/ingredients/dedup/db.py ingredients/tests/test_dedup_db.py
git commit -m "dedup: db helpers for name normalization + alias growth

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 3.4: `dedup/normalizer.py` — Phase-1 orchestrator

**Files:**
- Create: `ingredients/src/ingredients/dedup/normalizer.py`
- Test: `ingredients/tests/test_dedup_normalizer.py`

- [ ] **Step 1: Write failing tests**

```python
import pytest

from ingredients.dedup.normalizer import run_phase1
from ingredients.dedup.version import NORMALIZER_VERSION


def test_phase1_resolves_alias_and_lexical_pending_for_unknown(dedup_fixture, db_conn):
    conn, _ = dedup_fixture
    db_conn.execute("""
        insert into recipes (id, source_url, site, name, jsonld, fetched_at) values
            (3001, 'http://x/a', 'punch', 'The Negroni',          '{}'::jsonb, now()),
            (3002, 'http://x/b', 'punch', 'Best Old Fashioned',   '{}'::jsonb, now()),
            (3003, 'http://x/c', 'punch', 'Negronni',             '{}'::jsonb, now()),
            (3004, 'http://x/d', 'punch', 'Some Wild House Drink','{}'::jsonb, now())
        on conflict (source_url) do nothing
    """)
    db_conn.commit()
    counts = run_phase1(db_conn)
    assert counts["alias"] >= 2     # 'negroni' and 'old fashioned' fixture aliases
    assert counts["lexical"] >= 1   # 'negronni' close-match
    assert counts["pending_llm"] >= 1  # 'some wild house drink'

    rows = db_conn.execute(
        "select id, canonical_name, canonical_name_source from recipes where id in (3001,3002,3003,3004) order by id"
    ).fetchall()
    statuses = {r[0]: (r[1], r[2]) for r in rows}
    assert statuses[3001] == ("negroni", "alias")
    assert statuses[3002] == ("old fashioned", "alias")
    assert statuses[3003] == ("negroni", "lexical")
    assert statuses[3004] == (None, "pending_llm")


def test_phase1_idempotent_at_current_version(dedup_fixture, db_conn):
    conn, _ = dedup_fixture
    db_conn.execute("""
        insert into recipes (id, source_url, site, name, jsonld, fetched_at)
        values (3101, 'http://x/idemp', 'punch', 'The Negroni', '{}'::jsonb, now())
        on conflict (source_url) do nothing
    """)
    db_conn.commit()
    counts1 = run_phase1(db_conn)
    counts2 = run_phase1(db_conn)
    # Second run touches nothing (already at current version)
    assert sum(counts2.values()) == 0
```

- [ ] **Step 2: Run, expect fail**

- [ ] **Step 3: Implement**

```python
"""Phase 1 orchestrator for cocktail-name normalization.

Fetches every distinct unresolved recipes.name, runs each through
normalize_cocktail_name, walks alias_layer → lexical_layer cascade,
and writes the result back to every recipes row sharing that raw name.
"""

from __future__ import annotations

import logging
from collections import Counter

import psycopg

from .alias_layer import resolve_alias
from .db import (
    fetch_unresolved_recipe_names,
    write_normalization,
    write_pending_normalize,
)
from .lexical_layer import resolve_lexical
from .normalize import normalize_cocktail_name
from .types import Pending, Resolved
from .version import NORMALIZER_VERSION

log = logging.getLogger("dedup.normalizer")


def run_phase1(
    conn: psycopg.Connection,
    *,
    site: str | None = None,
    limit: int | None = None,
) -> dict[str, int]:
    """Return Counter-shaped dict keyed by 'alias' | 'lexical' | 'pending_llm'."""
    counts: Counter[str] = Counter()
    raw_names = fetch_unresolved_recipe_names(
        conn, normalizer_version=NORMALIZER_VERSION, site=site, limit=limit,
    )
    for raw in raw_names:
        normalized = normalize_cocktail_name(raw)
        if not normalized:
            write_pending_normalize(conn, raw_name=raw, normalizer_version=NORMALIZER_VERSION)
            counts["pending_llm"] += 1
            continue

        result = resolve_alias(conn, normalized)
        if isinstance(result, Resolved):
            write_normalization(
                conn, raw_name=raw, normalized=normalized,
                canonical_name=result.canonical_name, source=result.source,
                normalizer_version=NORMALIZER_VERSION,
            )
            counts["alias"] += 1
            continue

        result = resolve_lexical(conn, normalized)
        if isinstance(result, Resolved):
            write_normalization(
                conn, raw_name=raw, normalized=normalized,
                canonical_name=result.canonical_name, source=result.source,
                normalizer_version=NORMALIZER_VERSION,
            )
            counts["lexical"] += 1
            continue

        # Pending → queue for Phase 2.
        write_pending_normalize(conn, raw_name=raw, normalizer_version=NORMALIZER_VERSION)
        counts["pending_llm"] += 1

    return dict(counts)
```

- [ ] **Step 4: Run + commit**

```bash
cd ingredients && uv run pytest tests/test_dedup_normalizer.py -v
git add ingredients/src/ingredients/dedup/normalizer.py ingredients/tests/test_dedup_normalizer.py
git commit -m "dedup: phase-1 normalizer orchestrator (alias + lexical + queue pending)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 4: Phase-2 LLM normalizer

### Task 4.1: `dedup/prompt.py` — system + user prompt + parser

**Files:**
- Create: `ingredients/src/ingredients/dedup/prompt.py`
- Test: `ingredients/tests/test_dedup_prompt.py`

The prompt task is: given a raw recipe title and a small list of similar canonical-name candidates, the LLM either picks one ("chose"), proposes a new canonical name ("propose"), or abstains. The shape is simpler than D's prompt (no parent inference, no role decision).

- [ ] **Step 1: Write failing tests**

```python
import json

import pytest

from ingredients.dedup.prompt import (
    SYSTEM_PROMPT, build_user_prompt, parse_response, prompt_hash,
)


def test_build_user_prompt_includes_raw_and_candidates():
    prompt = build_user_prompt(
        raw_name="Best Old Fashioned Recipe",
        normalized="best old fashioned recipe",
        candidates=[
            {"canonical_name": "old fashioned", "similarity": 0.62},
            {"canonical_name": "manhattan",     "similarity": 0.31},
        ],
    )
    assert "Best Old Fashioned Recipe" in prompt
    assert "old fashioned" in prompt
    assert "manhattan" in prompt


def test_parse_response_chose():
    raw = json.dumps({"action": "chose", "canonical_name": "old fashioned"})
    obj = parse_response(raw)
    assert obj == {"action": "chose", "canonical_name": "old fashioned"}


def test_parse_response_propose():
    raw = json.dumps({"action": "propose", "canonical_name": "smoked old fashioned"})
    obj = parse_response(raw)
    assert obj == {"action": "propose", "canonical_name": "smoked old fashioned"}


def test_parse_response_abstain():
    raw = json.dumps({"action": "abstain"})
    obj = parse_response(raw)
    assert obj == {"action": "abstain"}


def test_parse_response_strips_code_fence():
    raw = "```json\n" + json.dumps({"action": "chose", "canonical_name": "negroni"}) + "\n```"
    obj = parse_response(raw)
    assert obj["action"] == "chose"


def test_parse_response_rejects_unknown_action():
    with pytest.raises(ValueError):
        parse_response(json.dumps({"action": "merge", "canonical_name": "x"}))


def test_parse_response_chose_requires_canonical_name():
    with pytest.raises(ValueError):
        parse_response(json.dumps({"action": "chose"}))


def test_prompt_hash_stable_across_candidate_ordering():
    h1 = prompt_hash(
        "Best Old Fashioned Recipe", "best old fashioned recipe",
        [{"canonical_name": "old fashioned", "similarity": 0.62},
         {"canonical_name": "manhattan",     "similarity": 0.31}],
    )
    h2 = prompt_hash(
        "Best Old Fashioned Recipe", "best old fashioned recipe",
        [{"canonical_name": "manhattan",     "similarity": 0.31},
         {"canonical_name": "old fashioned", "similarity": 0.62}],
    )
    assert h1 == h2
```

- [ ] **Step 2: Run, expect fail**

- [ ] **Step 3: Implement `dedup/prompt.py`**

```python
"""LLM prompt for cocktail-name canonicalization.

Action vocabulary:
  - "chose"    : pick one of the supplied candidate canonical names.
  - "propose"  : the title is a real cocktail not yet seen; propose a new
                 canonical name. The orchestrator auto-adds the alias.
  - "abstain"  : the title is editorial noise, not a cocktail, or the
                 model can't decide. Orchestrator stamps abstain.

Output shape (always JSON, single object):

  {"action": "chose",   "canonical_name": "<existing canonical>"}
  {"action": "propose", "canonical_name": "<new canonical>"}
  {"action": "abstain"}

Mirrors mapping/prompt.py shape; the action set differs because cocktail
names don't have a parent-child structure to traverse.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

SYSTEM_PROMPT = """You canonicalize cocktail recipe titles.

Given a raw recipe title and a list of candidate canonical cocktail
names already known, you must return a single JSON object describing
your decision:

  - "chose": one of the candidate canonical names matches; pick it.
  - "propose": the title is a real cocktail not in the candidates;
    propose a new canonical name (lowercase, no articles, no
    "cocktail"/"recipe" suffix, no editorial words).
  - "abstain": the title is editorial noise, an unrelated drink, or you
    cannot decide.

Be conservative. If the raw title has editorial decoration ("Best",
"Classic", "Perfect", "How to Make a", trailing "Recipe" / "Cocktail")
around an existing candidate, "chose" that candidate. If the title
includes a meaningful prefix ("Mezcal Negroni", "Smoked Old Fashioned",
"Hemingway Daiquiri"), it is a *different* drink — propose a new
canonical or chose a candidate that already includes the prefix.

Output JSON only. No prose. No code fences."""


_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


def build_user_prompt(
    *, raw_name: str, normalized: str,
    candidates: list[dict[str, Any]],
) -> str:
    cand_lines = "\n".join(
        f"  - {c['canonical_name']!r} (similarity={c['similarity']:.2f})"
        for c in candidates
    ) or "  (none — propose or abstain)"
    return (
        f"Raw title: {raw_name!r}\n"
        f"Normalized: {normalized!r}\n"
        f"\n"
        f"Candidate canonical names:\n{cand_lines}\n"
        f"\n"
        f"Return one JSON object per the system prompt's vocabulary."
    )


def parse_response(raw: str) -> dict[str, Any]:
    cleaned = _FENCE.sub("", raw).strip()
    obj = json.loads(cleaned)
    if not isinstance(obj, dict):
        raise ValueError(f"Expected JSON object, got {type(obj).__name__}")
    action = obj.get("action")
    if action not in {"chose", "propose", "abstain"}:
        raise ValueError(f"Unknown action: {action!r}")
    if action in {"chose", "propose"} and not obj.get("canonical_name"):
        raise ValueError(f"Action {action!r} missing canonical_name")
    return obj


def prompt_hash(
    raw_name: str, normalized: str, candidates: list[dict[str, Any]],
) -> str:
    """Stable hash for prompt-cache provenance / dedup.

    Sorting candidate list keeps the hash stable across pg_trgm tie orderings.
    """
    sorted_cands = sorted(
        ({"canonical_name": c["canonical_name"]} for c in candidates),
        key=lambda c: c["canonical_name"],
    )
    payload = json.dumps(
        {"raw": raw_name, "normalized": normalized, "candidates": sorted_cands},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Run + commit**

```bash
cd ingredients && uv run pytest tests/test_dedup_prompt.py -v
git add ingredients/src/ingredients/dedup/prompt.py ingredients/tests/test_dedup_prompt.py
git commit -m "dedup: cocktail-name LLM prompt + parser + prompt_hash

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 4.2: `dedup/normalizer_llm.py` — Phase-2 orchestrator

**Files:**
- Create: `ingredients/src/ingredients/dedup/normalizer_llm.py`
- Test: `ingredients/tests/test_dedup_normalizer_llm.py`

This task **reuses D's `LLMProvider` Protocol and `_resolve_with_retry` directly** — see *Reuse from [D]* in the spec. To make `_resolve_with_retry` reusable, first lift it from `mapping/llm_resolver.py` to a public name.

- [ ] **Step 1: Lift `_resolve_with_retry` to public**

Edit `ingredients/src/ingredients/mapping/llm_resolver.py`:

Find:
```python
def _resolve_with_retry(
    provider: LLMProvider, *, system_prompt: str, user_prompt: str,
    normalized_name: str, max_attempts: int = 3,
) -> dict | None:
```

Add an alias at the bottom of the file (don't break existing callers):
```python
# Public re-export so other stages (e.g. dedup) can reuse the retry helper
# without depending on the orchestrator details.
resolve_with_retry = _resolve_with_retry
```

Commit:
```bash
git add ingredients/src/ingredients/mapping/llm_resolver.py
git commit -m "mapping: expose resolve_with_retry as public symbol for reuse

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 2: Write failing tests for `normalizer_llm.py`**

```python
"""Phase-2 LLM normalizer orchestrator. Tested with a stub provider that
yields scripted ProviderResult objects; the real Claude/Ollama providers
are exercised in mapping/'s tests already and don't need re-testing here."""

from dataclasses import dataclass
from typing import Iterator

import pytest

from ingredients.dedup.normalizer_llm import run_phase2
from ingredients.dedup.version import NORMALIZER_VERSION
from ingredients.mapping.llm_provider import ProviderResult


@dataclass
class StubProvider:
    scripted: Iterator[str]
    model_id: str = "stub-1.0"

    def resolve(self, *, system_prompt: str, user_prompt: str) -> ProviderResult:
        return ProviderResult(raw_text=next(self.scripted), model_id=self.model_id)


def test_phase2_chose_writes_canonical(dedup_fixture, db_conn):
    conn, _ = dedup_fixture
    db_conn.execute("""
        insert into recipes (id, source_url, site, name, jsonld, fetched_at,
                             canonical_name, canonical_name_source, normalizer_version, normalized_at)
        values (4001, 'http://x/a', 'punch', 'Some Wild House Drink',
                '{}'::jsonb, now(),
                null, 'pending_llm', %s, now())
        on conflict (source_url) do nothing
    """, (NORMALIZER_VERSION,))
    db_conn.commit()
    provider = StubProvider(iter(['{"action":"chose","canonical_name":"old fashioned"}']))
    counts = run_phase2(db_conn, provider=provider)
    assert counts["chose"] == 1
    row = db_conn.execute(
        "select canonical_name, canonical_name_source from recipes where id = 4001"
    ).fetchone()
    assert row == ("old fashioned", "llm")


def test_phase2_propose_adds_alias(dedup_fixture, db_conn):
    conn, _ = dedup_fixture
    db_conn.execute("""
        insert into recipes (id, source_url, site, name, jsonld, fetched_at,
                             canonical_name, canonical_name_source, normalizer_version, normalized_at)
        values (4002, 'http://x/b', 'punch', 'Bee''s Knees',
                '{}'::jsonb, now(),
                null, 'pending_llm', %s, now())
        on conflict (source_url) do nothing
    """, (NORMALIZER_VERSION,))
    db_conn.commit()
    provider = StubProvider(iter(['{"action":"propose","canonical_name":"bees knees"}']))
    counts = run_phase2(db_conn, provider=provider)
    assert counts["propose"] == 1
    row = db_conn.execute(
        "select canonical_name, canonical_name_source from recipes where id = 4002"
    ).fetchone()
    assert row == ("bees knees", "llm")
    alias = db_conn.execute(
        "select source from cocktail_aliases where alias = %s and canonical_name = 'bees knees'",
        ("bee s knees",),  # post-normalize_cocktail_name form
    ).fetchone()
    assert alias is not None
    assert alias[0] == "llm"


def test_phase2_abstain(dedup_fixture, db_conn):
    conn, _ = dedup_fixture
    db_conn.execute("""
        insert into recipes (id, source_url, site, name, jsonld, fetched_at,
                             canonical_name, canonical_name_source, normalizer_version, normalized_at)
        values (4003, 'http://x/c', 'punch', '5 Cocktail Recipes For Summer',
                '{}'::jsonb, now(),
                null, 'pending_llm', %s, now())
        on conflict (source_url) do nothing
    """, (NORMALIZER_VERSION,))
    db_conn.commit()
    provider = StubProvider(iter(['{"action":"abstain"}']))
    counts = run_phase2(db_conn, provider=provider)
    assert counts["abstain"] == 1
    row = db_conn.execute(
        "select canonical_name, canonical_name_source from recipes where id = 4003"
    ).fetchone()
    assert row == (None, "abstain")
```

- [ ] **Step 3: Implement `normalizer_llm.py`**

```python
"""Phase 2 orchestrator. Drains the pending_llm queue using a chosen provider.

Reuses:
  - mapping.llm_provider.LLMProvider (the Protocol)
  - mapping.llm_resolver.resolve_with_retry (the retry helper)

Branching by LLM action:
  chose    -> write_normalization(source='llm')
  propose  -> add_cocktail_alias + write_normalization(source='llm')
  abstain  -> write_normalize_abstain
"""

from __future__ import annotations

import logging
from collections import Counter

import psycopg

from ingredients.mapping.llm_provider import LLMProvider
from ingredients.mapping.llm_resolver import resolve_with_retry

from .db import (
    add_cocktail_alias,
    fetch_pending_canonical_names,
    write_normalization,
    write_normalize_abstain,
)
from .lexical_layer import lexical_candidates
from .normalize import normalize_cocktail_name
from .prompt import SYSTEM_PROMPT, build_user_prompt, parse_response
from .version import NORMALIZER_VERSION

log = logging.getLogger("dedup.normalizer_llm")


def run_phase2(
    conn: psycopg.Connection,
    *,
    provider: LLMProvider,
    limit: int | None = None,
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    raw_names = fetch_pending_canonical_names(
        conn, normalizer_version=NORMALIZER_VERSION, limit=limit,
    )
    for raw in raw_names:
        normalized = normalize_cocktail_name(raw)
        cands = lexical_candidates(conn, normalized, limit=20)
        user_prompt = build_user_prompt(
            raw_name=raw, normalized=normalized, candidates=cands,
        )
        action_obj = resolve_with_retry(
            provider,
            system_prompt=SYSTEM_PROMPT, user_prompt=user_prompt,
            normalized_name=normalized,
        )
        if action_obj is None:
            counts["error"] += 1
            continue
        action = action_obj["action"]

        if action == "chose":
            canonical = action_obj["canonical_name"]
            write_normalization(
                conn, raw_name=raw, normalized=normalized,
                canonical_name=canonical, source="llm",
                normalizer_version=NORMALIZER_VERSION,
            )
            counts["chose"] += 1
        elif action == "propose":
            canonical = action_obj["canonical_name"]
            add_cocktail_alias(
                conn, alias=normalized, canonical_name=canonical, source="llm",
            )
            write_normalization(
                conn, raw_name=raw, normalized=normalized,
                canonical_name=canonical, source="llm",
                normalizer_version=NORMALIZER_VERSION,
            )
            counts["propose"] += 1
        elif action == "abstain":
            write_normalize_abstain(
                conn, raw_name=raw, normalizer_version=NORMALIZER_VERSION,
            )
            counts["abstain"] += 1
    return dict(counts)
```

- [ ] **Step 4: Run + commit**

```bash
cd ingredients && uv run pytest tests/test_dedup_normalizer_llm.py -v
git add ingredients/src/ingredients/dedup/normalizer_llm.py ingredients/tests/test_dedup_normalizer_llm.py
git commit -m "dedup: phase-2 LLM normalizer (chose/propose/abstain)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 5: Role classifier

### Task 5.1: `dedup/role_classifier.py` — pure function over `(node, amount, unit, position)`

**Files:**
- Create: `ingredients/src/ingredients/dedup/role_classifier.py`
- Test: `ingredients/tests/test_dedup_role_classifier.py`

The classifier is pure and deterministic. Three layers in order: `taxonomy_nodes.role_default` → contextual rules → fall back to `'other'`.

- [ ] **Step 1: Write failing tests**

```python
import pytest

from ingredients.dedup.role_classifier import classify_role


def make_ing(*, role_default=None, slug="x", amount=None, unit=None, position=1, raw_text=""):
    """Test helper — builds the dict shape classify_role consumes."""
    return {
        "taxonomy_node_slug": slug,
        "role_default": role_default,
        "amount": amount,
        "unit": unit,
        "position": position,
        "raw_text": raw_text,
    }


@pytest.mark.parametrize("role_default", [
    "base_spirit", "modifier", "citrus", "sweetener",
    "bitters", "dilution", "ice", "garnish",
])
def test_taxonomy_default_used_when_present(role_default):
    role, source = classify_role(make_ing(role_default=role_default))
    assert role == role_default
    assert source == "default"


def test_bitters_with_large_amount_promotes_to_base_spirit():
    # Trinidad Sour: 1.5oz Angostura as the base
    role, source = classify_role(
        make_ing(role_default="bitters", amount=1.5, unit="oz", position=1),
    )
    assert role == "base_spirit"
    assert source == "rule"


def test_bitters_with_dash_amount_stays_bitters():
    role, source = classify_role(
        make_ing(role_default="bitters", amount=2.0, unit="dash", position=4),
    )
    assert role == "bitters"
    assert source == "default"


def test_modifier_with_position_one_and_large_amount_promotes_to_base():
    # Reverse Manhattan: 1.5oz sweet vermouth as the base
    role, source = classify_role(
        make_ing(role_default="modifier", amount=1.5, unit="oz", position=1),
    )
    assert role == "base_spirit"
    assert source == "rule"


def test_modifier_in_modifier_position_stays_modifier():
    role, source = classify_role(
        make_ing(role_default="modifier", amount=1.0, unit="oz", position=2),
    )
    assert role == "modifier"
    assert source == "default"


def test_wash_hint_in_raw_text_with_tiny_amount():
    role, source = classify_role(
        make_ing(role_default=None, slug="absinthe", amount=0.0625, unit="oz",
                 raw_text="absinthe rinse", position=1),
    )
    assert role == "wash"
    assert source == "rule"


def test_unknown_substance_position_one_with_base_amount_defaults_to_base_spirit():
    # No role_default; large amount in position 1; classifier infers base.
    role, source = classify_role(
        make_ing(role_default=None, amount=2.0, unit="oz", position=1),
    )
    assert role == "base_spirit"
    assert source == "rule"


def test_unknown_substance_no_amount_falls_back_to_other():
    role, source = classify_role(
        make_ing(role_default=None, amount=None, unit=None, position=3),
    )
    assert role == "other"
    assert source == "default"
```

- [ ] **Step 2: Run, expect fail**

- [ ] **Step 3: Implement `role_classifier.py`**

```python
"""Deterministic role classification for recipe_ingredients rows.

Inputs: (taxonomy_node_slug, role_default, amount, unit, position, raw_text).
Output: (role, role_source) where role_source is 'default' (taxonomy), 'rule'
(contextual override), or 'manual' (set by an explicit reviewer — never
emitted by this function; reserved).

No DB access. No LLM. Caller assembles the input dict by joining
recipe_ingredients with taxonomy_nodes.
"""

from __future__ import annotations

from typing import Any

# Volume in fluid ounces above which a "modifier" or "bitters" substance
# in position 1 is reclassified as base_spirit. 1.5 oz is the rough
# threshold between accent and structural; tighter thresholds over-fire
# on Reverse Manhattans, looser thresholds miss Trinidad Sours.
_BASE_SPIRIT_OZ = 1.5

_OZ_PER_UNIT = {
    "oz": 1.0, "ounce": 1.0, "ounces": 1.0,
    "ml": 0.0338,
    "cl": 0.338,
    "tsp": 0.166, "teaspoon": 0.166,
    "tbsp": 0.5, "tablespoon": 0.5,
    "dash": 0.03125,  # ~1/32 oz, for sanity in heuristics
    "dashes": 0.03125,
    "drop": 0.001, "drops": 0.001,
    "splash": 0.125,
    # Fall-through; volume unknown → no rule fires
}

_WASH_HINTS = ("rinse", "spritz", "wash", "mist", "spray")


def _to_oz(amount: float | None, unit: str | None) -> float | None:
    if amount is None:
        return None
    if not unit:
        return None
    factor = _OZ_PER_UNIT.get(unit.lower())
    if factor is None:
        return None
    return float(amount) * factor


def classify_role(ing: dict[str, Any]) -> tuple[str, str]:
    role_default = ing.get("role_default")
    amount = ing.get("amount")
    unit = ing.get("unit")
    position = ing.get("position") or 99
    raw_text = (ing.get("raw_text") or "").lower()
    oz = _to_oz(amount, unit)

    # Rule: wash-hint substance with tiny amount.
    if any(h in raw_text for h in _WASH_HINTS) and oz is not None and oz < 0.25:
        return "wash", "rule"

    # Rule: position 1 with structural amount of bitters → base_spirit.
    if (
        role_default == "bitters"
        and position == 1
        and oz is not None
        and oz >= _BASE_SPIRIT_OZ
    ):
        return "base_spirit", "rule"

    # Rule: position 1 with structural amount of modifier → base_spirit.
    # (Catches Reverse Manhattan, Adonis, Bamboo.)
    if (
        role_default == "modifier"
        and position == 1
        and oz is not None
        and oz >= _BASE_SPIRIT_OZ
    ):
        return "base_spirit", "rule"

    # Default-from-taxonomy.
    if role_default is not None:
        return role_default, "default"

    # Heuristic for nodes without role_default: position 1 + structural
    # amount → base_spirit. Otherwise 'other' (audit will flag).
    if position == 1 and oz is not None and oz >= _BASE_SPIRIT_OZ:
        return "base_spirit", "rule"

    return "other", "default"
```

- [ ] **Step 4: Run + commit**

```bash
cd ingredients && uv run pytest tests/test_dedup_role_classifier.py -v
git add ingredients/src/ingredients/dedup/role_classifier.py ingredients/tests/test_dedup_role_classifier.py
git commit -m "dedup: deterministic role classifier (taxonomy_default + contextual rules)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 6: Antichain rollup + cluster compute

### Task 6.1: `dedup/rollup.py` — DAG ancestor walk to `is_cluster_node`

**Files:**
- Create: `ingredients/src/ingredients/dedup/rollup.py`
- Test: `ingredients/tests/test_dedup_rollup.py`

- [ ] **Step 1: Write failing tests**

```python
import pytest

from ingredients.dedup.rollup import roll_up_to_antichain


def test_brand_rolls_up_to_substance_antichain(dedup_fixture):
    conn, ids = dedup_fixture
    # tanqueray (brand) rolls up to london_dry_gin (cluster_node)
    result = roll_up_to_antichain(conn, ids["tanqueray"])
    assert result == ids["london_dry_gin"]


def test_antichain_node_rolls_up_to_itself(dedup_fixture):
    conn, ids = dedup_fixture
    result = roll_up_to_antichain(conn, ids["campari"])
    assert result == ids["campari"]


def test_node_above_antichain_rolls_up_to_itself(dedup_fixture):
    conn, ids = dedup_fixture
    # 'gin' is above the cut (london_dry_gin / old_tom_gin are antichain).
    # No antichain ancestor exists → returns the node itself.
    result = roll_up_to_antichain(conn, ids["gin"])
    assert result == ids["gin"]


def test_unknown_node_id_returns_input(dedup_fixture):
    conn, _ = dedup_fixture
    result = roll_up_to_antichain(conn, 99_999_999)
    assert result == 99_999_999


def test_multi_parent_picks_first_antichain_ancestor(dedup_fixture, db_conn):
    """If a node has multiple parents and one parent is antichain, that
    ancestor is the answer. We don't have a multi-parent fixture by
    default; sketch one inline for this test.

    This test mostly guards against a regression: the recursive CTE
    must use the FIRST (cheapest-depth) antichain hit, not collapse
    randomly across parents.
    """
    conn, ids = dedup_fixture
    # All fixture brands have a single parent that is antichain. Test
    # that the rollup is stable across multiple invocations.
    a = roll_up_to_antichain(conn, ids["tanqueray"])
    b = roll_up_to_antichain(conn, ids["tanqueray"])
    assert a == b == ids["london_dry_gin"]
```

- [ ] **Step 2: Run, expect fail**

- [ ] **Step 3: Implement `rollup.py`**

```python
"""Antichain rollup: walk the taxonomy DAG from a node up to its nearest
ancestor with is_cluster_node = true, OR return the node itself if it is
one OR if no antichain ancestor exists (the node is "above the cut").

Uses a recursive CTE. Defensive depth cap of 10 (taxonomy is shallow;
real depth is 3-5).
"""

from __future__ import annotations

import psycopg

_SQL = """
    with recursive ancestors(id, depth) as (
        select n.id, 0
        from taxonomy_nodes n
        where n.id = %s

        union all

        select e.parent_id, a.depth + 1
        from ancestors a
        join taxonomy_edges e on e.child_id = a.id
        where a.depth < 10
    ),
    matches as (
        select a.id, a.depth
        from ancestors a
        join taxonomy_nodes n on n.id = a.id
        where n.is_cluster_node = true
        order by a.depth
        limit 1
    )
    select coalesce((select id from matches), %s)
"""


def roll_up_to_antichain(conn: psycopg.Connection, node_id: int) -> int:
    """Return the antichain ancestor of node_id (or node_id itself).

    Behaviour:
      - node_id is_cluster_node=true                     → returns node_id
      - node_id has an is_cluster_node=true ancestor     → returns nearest
      - node_id has no is_cluster_node anywhere upward   → returns node_id

    The third case is the "above the cut" path — recipes referencing a
    node above the antichain (e.g., generic 'amaro') flow through with
    that node verbatim and are flagged underspecified by the audit pass.
    """
    if node_id is None:
        return node_id
    row = conn.execute(_SQL, (node_id, node_id)).fetchone()
    return row[0]
```

- [ ] **Step 4: Run + commit**

```bash
cd ingredients && uv run pytest tests/test_dedup_rollup.py -v
git add ingredients/src/ingredients/dedup/rollup.py ingredients/tests/test_dedup_rollup.py
git commit -m "dedup: antichain rollup via recursive CTE

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 6.2: `dedup/cluster.py` — cluster_key + variant_key + orchestrator

**Files:**
- Create: `ingredients/src/ingredients/dedup/cluster.py`
- Test: `ingredients/tests/test_dedup_cluster.py`

This task covers the most logic in E. Split into sub-steps:
- 2a: pure `compute_cluster_key` and `compute_variant_key` functions
- 2b: orchestrator that joins recipes × recipe_ingredients × taxonomy, runs role classifier, computes keys, writes everything

- [ ] **Step 1: Write failing tests for the pure key functions**

```python
import pytest

from ingredients.dedup.cluster import (
    INCLUDED_ROLES,
    compute_cluster_key,
    compute_variant_key,
    in_cluster_key,
)


def _ing(role, antichain_node_id=1, taxonomy_node_id=1, amount=1.0,
         amount_max=None, unit="oz", is_defining_garnish=False):
    return {
        "role": role,
        "antichain_node_id": antichain_node_id,
        "taxonomy_node_id": taxonomy_node_id,
        "amount": amount,
        "amount_max": amount_max,
        "unit": unit,
        "is_defining_garnish": is_defining_garnish,
    }


def test_in_cluster_key_includes_default_roles():
    for role in INCLUDED_ROLES:
        assert in_cluster_key(_ing(role=role))


def test_in_cluster_key_excludes_ice():
    assert not in_cluster_key(_ing(role="ice"))


def test_in_cluster_key_garnish_uses_defining_flag():
    assert not in_cluster_key(_ing(role="garnish", is_defining_garnish=False))
    assert     in_cluster_key(_ing(role="garnish", is_defining_garnish=True))


def test_in_cluster_key_unknown_role_excluded_by_default():
    # The allow-list invariant from the spec: a future role added elsewhere
    # in the codebase doesn't accidentally enter the cluster key.
    assert not in_cluster_key(_ing(role="high_abv"))


def test_compute_cluster_key_independent_of_ingredient_ordering():
    ings1 = [_ing(role="base_spirit", antichain_node_id=1),
             _ing(role="modifier",    antichain_node_id=2)]
    ings2 = [_ing(role="modifier",    antichain_node_id=2),
             _ing(role="base_spirit", antichain_node_id=1)]
    assert compute_cluster_key("negroni", ings1) == compute_cluster_key("negroni", ings2)


def test_compute_cluster_key_independent_of_amount():
    a = [_ing(role="base_spirit", antichain_node_id=1, amount=1.0)]
    b = [_ing(role="base_spirit", antichain_node_id=1, amount=2.0)]
    assert compute_cluster_key("negroni", a) == compute_cluster_key("negroni", b)


def test_compute_variant_key_distinguishes_amounts():
    a = [_ing(role="base_spirit", antichain_node_id=1, amount=1.0, unit="oz")]
    b = [_ing(role="base_spirit", antichain_node_id=1, amount=2.0, unit="oz")]
    ck_a = compute_cluster_key("negroni", a)
    ck_b = compute_cluster_key("negroni", b)
    assert ck_a == ck_b  # same cluster
    assert compute_variant_key(ck_a, a) != compute_variant_key(ck_b, b)


def test_compute_variant_key_distinguishes_brand():
    base = _ing(role="base_spirit", antichain_node_id=1, taxonomy_node_id=1)
    branded = {**base, "taxonomy_node_id": 42}
    ck = compute_cluster_key("negroni", [base])
    assert compute_variant_key(ck, [base]) != compute_variant_key(ck, [branded])


def test_compute_cluster_key_excludes_ice():
    no_ice = [_ing(role="base_spirit", antichain_node_id=1)]
    with_ice = no_ice + [_ing(role="ice", antichain_node_id=99)]
    assert compute_cluster_key("negroni", no_ice) == compute_cluster_key("negroni", with_ice)
```

- [ ] **Step 2: Run, expect fail**

- [ ] **Step 3: Implement the pure-function half of `cluster.py`**

```python
"""Cluster + variant key derivation, plus the cluster compute orchestrator.

Pure key functions (compute_cluster_key, compute_variant_key, in_cluster_key)
are at the top; the DB-touching orchestrator (run_cluster_compute) is at
the bottom.

The allow-list (INCLUDED_ROLES) is the invariant the spec calls out: a
future role added elsewhere in the codebase does NOT enter the cluster
key without an explicit addition here AND a DEDUP_VERSION bump.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import Counter, defaultdict
from typing import Any

import psycopg

from .role_classifier import classify_role
from .rollup import roll_up_to_antichain
from .version import DEDUP_VERSION

log = logging.getLogger("dedup.cluster")

INCLUDED_ROLES = frozenset({
    "base_spirit", "modifier", "citrus", "sweetener",
    "bitters", "dilution", "wash", "other",
})


def in_cluster_key(ing: dict[str, Any]) -> bool:
    role = ing.get("role")
    if role == "garnish":
        return bool(ing.get("is_defining_garnish"))
    return role in INCLUDED_ROLES


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def compute_cluster_key(canonical_name: str, ingredients: list[dict[str, Any]]) -> str:
    """Cluster identity = sha256(canonical_name, sorted set of (role, antichain_node_id))."""
    members = sorted(
        (ing["role"], ing["antichain_node_id"])
        for ing in ingredients
        if in_cluster_key(ing)
    )
    payload = _canonical_json({
        "canonical_name": canonical_name,
        "ingredients": members,
    })
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_variant_key(cluster_key: str, ingredients: list[dict[str, Any]]) -> str:
    """Variant identity adds taxonomy_node_id (specific node), amount,
    amount_max, unit. Two recipes share a variant iff their amounts +
    brands match within the same cluster.
    """
    members = sorted(
        (
            ing["role"],
            ing["antichain_node_id"],
            ing.get("taxonomy_node_id"),
            ing.get("amount"),
            ing.get("amount_max"),
            ing.get("unit"),
        )
        for ing in ingredients
        if in_cluster_key(ing)
    )
    payload = _canonical_json({
        "cluster_key": cluster_key,
        "ingredients": members,
    })
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Run pure-function tests, expect pass**

```bash
cd ingredients && uv run pytest tests/test_dedup_cluster.py -v -k "cluster_key or variant_key or in_cluster_key"
```

- [ ] **Step 5: Append the orchestrator to `cluster.py`**

```python
def _fetch_recipe_ingredients(
    conn: psycopg.Connection, recipe_id: int,
) -> list[dict[str, Any]]:
    """Return the ingredient rows for one recipe with everything the
    role classifier and key functions need."""
    rows = conn.execute(
        """
        select ri.id,
               ri.position,
               ri.raw_text,
               ri.amount,
               ri.amount_max,
               ri.unit,
               ri.taxonomy_node_id,
               n.slug,
               n.role_default,
               n.is_defining_garnish
        from recipe_ingredients ri
        left join taxonomy_nodes n on n.id = ri.taxonomy_node_id
        where ri.recipe_id = %s
        order by ri.position
        """,
        (recipe_id,),
    ).fetchall()
    return [
        {
            "id": r[0],
            "position": r[1],
            "raw_text": r[2],
            "amount": float(r[3]) if r[3] is not None else None,
            "amount_max": float(r[4]) if r[4] is not None else None,
            "unit": r[5],
            "taxonomy_node_id": r[6],
            "taxonomy_node_slug": r[7],
            "role_default": r[8],
            "is_defining_garnish": bool(r[9]) if r[9] is not None else False,
        }
        for r in rows
    ]


def _fetch_recipes_to_cluster(
    conn: psycopg.Connection, *, dedup_version: str,
    site: str | None, limit: int | None,
) -> list[tuple[int, str | None, str]]:
    """Return (id, canonical_name, name) for every recipe needing a current
    DEDUP_VERSION cluster assignment AND with a non-null canonical_name."""
    params: list[object] = [dedup_version]
    site_clause = ""
    if site is not None:
        site_clause = "and r.site = %s"
        params.append(site)

    sql = f"""
        select r.id, r.canonical_name, r.name
        from recipes r
        where r.canonical_name is not null
          and (r.dedup_version is null or r.dedup_version <> %s)
          {site_clause}
        order by r.id
    """
    if limit is not None:
        sql += " limit %s"
        params.append(limit)
    return [(row[0], row[1], row[2]) for row in conn.execute(sql, params).fetchall()]


def _ingredient_set_jsonb(ingredients: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stable representation of the cluster's ingredient set, stored on
    recipe_clusters.ingredient_set for debugging / audit."""
    items = sorted(
        {
            (ing["role"], ing["antichain_node_id"], ing.get("antichain_slug"))
            for ing in ingredients
            if in_cluster_key(ing)
        }
    )
    return [
        {"role": role, "antichain_node_id": node_id, "antichain_slug": slug}
        for role, node_id, slug in items
    ]


def run_cluster_compute(
    conn: psycopg.Connection,
    *,
    site: str | None = None,
    limit: int | None = None,
) -> dict[str, int]:
    """Tag roles, compute cluster + variant keys, write recipe_clusters
    + recipes.cluster_id + recipes.variant_key + recipe_ingredients.role.

    Returns Counter-shaped summary keyed by 'recipes_clustered',
    'clusters_created', 'clusters_updated', 'underspecified'.
    """
    counts: Counter[str] = Counter()
    recipes = _fetch_recipes_to_cluster(
        conn, dedup_version=DEDUP_VERSION, site=site, limit=limit,
    )
    cluster_lookup: dict[str, int] = {}  # cluster_key → recipe_clusters.id

    for recipe_id, canonical_name, _raw_name in recipes:
        ingredients = _fetch_recipe_ingredients(conn, recipe_id)

        # Role classify + roll up each ingredient.
        for ing in ingredients:
            role, role_source = classify_role(ing)
            ing["role"] = role
            ing["role_source"] = role_source
            antichain_id = (
                roll_up_to_antichain(conn, ing["taxonomy_node_id"])
                if ing["taxonomy_node_id"] is not None
                else None
            )
            ing["antichain_node_id"] = antichain_id
            if antichain_id is not None:
                slug_row = conn.execute(
                    "select slug, is_cluster_node from taxonomy_nodes where id = %s",
                    (antichain_id,),
                ).fetchone()
                ing["antichain_slug"] = slug_row[0] if slug_row else None
                if slug_row and not slug_row[1]:
                    counts["underspecified"] += 1

        # Persist roles.
        for ing in ingredients:
            conn.execute(
                """
                update recipe_ingredients
                   set role = %s, role_source = %s
                 where id = %s
                """,
                (ing["role"], ing["role_source"], ing["id"]),
            )

        # Skip recipes whose key would be empty (no in-key ingredients).
        in_key_ings = [ing for ing in ingredients if in_cluster_key(ing)]
        if not in_key_ings:
            counts["skipped_no_ingredients"] += 1
            continue

        # Cluster key + cluster row.
        cluster_key = compute_cluster_key(canonical_name, ingredients)
        if cluster_key in cluster_lookup:
            cluster_id = cluster_lookup[cluster_key]
        else:
            row = conn.execute(
                """
                insert into recipe_clusters
                    (cluster_key, canonical_name, ingredient_set, dedup_version)
                values (%s, %s, %s::jsonb, %s)
                on conflict (cluster_key) do update
                    set canonical_name = excluded.canonical_name,
                        dedup_version  = excluded.dedup_version
                returning id
                """,
                (cluster_key, canonical_name,
                 _canonical_json(_ingredient_set_jsonb(ingredients)),
                 DEDUP_VERSION),
            ).fetchone()
            cluster_id = row[0]
            cluster_lookup[cluster_key] = cluster_id
            counts["clusters_created" if row else "clusters_updated"] += 1

        variant_key = compute_variant_key(cluster_key, ingredients)
        conn.execute(
            """
            update recipes
               set cluster_id    = %s,
                   variant_key   = %s,
                   dedup_version = %s
             where id = %s
            """,
            (cluster_id, variant_key, DEDUP_VERSION, recipe_id),
        )
        counts["recipes_clustered"] += 1

    # Refresh recipe_clusters.recipe_count, source_count,
    # representative_recipe_id (cheap; one update per cluster).
    conn.execute(
        """
        update recipe_clusters c
           set recipe_count = sub.recipe_count,
               source_count = sub.source_count,
               representative_recipe_id = sub.rep_id
        from (
            select cluster_id,
                   count(*)              as recipe_count,
                   count(distinct site)  as source_count,
                   min(id)               as rep_id
            from recipes
            where cluster_id is not null
              and dedup_version = %s
            group by cluster_id
        ) sub
        where c.id = sub.cluster_id
        """,
        (DEDUP_VERSION,),
    )

    conn.commit()
    return dict(counts)
```

- [ ] **Step 6: Add the integration test for the orchestrator**

Append to `tests/test_dedup_cluster.py`:

```python
def test_run_cluster_compute_groups_identical_negronis(dedup_fixture, db_conn):
    conn, ids = dedup_fixture
    # Two Negronis from different sources at identical ratios → same cluster, same variant.
    db_conn.execute("""
        insert into recipes (id, source_url, site, name, jsonld, fetched_at,
                             canonical_name, canonical_name_source, normalizer_version, normalized_at)
        values
            (5001, 'http://x/n1', 'punch',  'Negroni', '{}'::jsonb, now(),
             'negroni', 'alias', 'v1', now()),
            (5002, 'http://x/n2', 'imbibe', 'Negroni', '{}'::jsonb, now(),
             'negroni', 'alias', 'v1', now())
        on conflict (source_url) do nothing
    """)
    for rid in (5001, 5002):
        for pos, slug, amount in (
            (1, "london_dry_gin",  1.0),
            (2, "campari",         1.0),
            (3, "sweet_vermouth",  1.0),
        ):
            db_conn.execute("""
                insert into recipe_ingredients
                    (recipe_id, position, raw_text, amount, unit,
                     parse_status, parser_version, taxonomy_node_id,
                     mapper_source, mapper_version)
                values (%s, %s, 'x', %s, 'oz', 'parsed', 'v1', %s, 'alias', 'v1')
                on conflict (recipe_id, position) do nothing
            """, (rid, pos, amount, ids[slug]))
    db_conn.commit()

    from ingredients.dedup.cluster import run_cluster_compute
    counts = run_cluster_compute(db_conn)
    assert counts["recipes_clustered"] == 2

    rows = db_conn.execute(
        "select cluster_id, variant_key from recipes where id in (5001, 5002)"
    ).fetchall()
    assert rows[0][0] == rows[1][0]  # same cluster
    assert rows[0][1] == rows[1][1]  # same variant


def test_run_cluster_compute_separates_ratio_variants(dedup_fixture, db_conn):
    conn, ids = dedup_fixture
    db_conn.execute("""
        insert into recipes (id, source_url, site, name, jsonld, fetched_at,
                             canonical_name, canonical_name_source, normalizer_version, normalized_at)
        values
            (5101, 'http://x/r1', 'punch',  'Negroni', '{}'::jsonb, now(),
             'negroni', 'alias', 'v1', now()),
            (5102, 'http://x/r2', 'imbibe', 'Negroni', '{}'::jsonb, now(),
             'negroni', 'alias', 'v1', now())
        on conflict (source_url) do nothing
    """)
    # 5101: 1/1/1   5102: 1.5/1/1
    for rid, gin_amt in ((5101, 1.0), (5102, 1.5)):
        for pos, slug, amount in (
            (1, "london_dry_gin",  gin_amt),
            (2, "campari",         1.0),
            (3, "sweet_vermouth",  1.0),
        ):
            db_conn.execute("""
                insert into recipe_ingredients
                    (recipe_id, position, raw_text, amount, unit,
                     parse_status, parser_version, taxonomy_node_id,
                     mapper_source, mapper_version)
                values (%s, %s, 'x', %s, 'oz', 'parsed', 'v1', %s, 'alias', 'v1')
                on conflict (recipe_id, position) do nothing
            """, (rid, pos, amount, ids[slug]))
    db_conn.commit()

    from ingredients.dedup.cluster import run_cluster_compute
    run_cluster_compute(db_conn)

    rows = db_conn.execute(
        "select cluster_id, variant_key from recipes where id in (5101, 5102)"
    ).fetchall()
    assert rows[0][0] == rows[1][0]            # same cluster
    assert rows[0][1] != rows[1][1]            # different variant


def test_run_cluster_compute_ignores_ice(dedup_fixture, db_conn):
    """Recipe with ice and recipe without ice → same variant (ice not in key)."""
    conn, ids = dedup_fixture
    db_conn.execute("""
        insert into recipes (id, source_url, site, name, jsonld, fetched_at,
                             canonical_name, canonical_name_source, normalizer_version, normalized_at)
        values
            (5201, 'http://x/i1', 'punch',  'Negroni', '{}'::jsonb, now(),
             'negroni', 'alias', 'v1', now()),
            (5202, 'http://x/i2', 'imbibe', 'Negroni', '{}'::jsonb, now(),
             'negroni', 'alias', 'v1', now())
        on conflict (source_url) do nothing
    """)
    base = [
        (1, "london_dry_gin", 1.0),
        (2, "campari",        1.0),
        (3, "sweet_vermouth", 1.0),
    ]
    # 5202 also lists ice
    for rid, ings in ((5201, base), (5202, base + [(4, "ice", 1.0)])):
        for pos, slug, amount in ings:
            db_conn.execute("""
                insert into recipe_ingredients
                    (recipe_id, position, raw_text, amount, unit,
                     parse_status, parser_version, taxonomy_node_id,
                     mapper_source, mapper_version)
                values (%s, %s, 'x', %s, 'oz', 'parsed', 'v1', %s, 'alias', 'v1')
                on conflict (recipe_id, position) do nothing
            """, (rid, pos, amount, ids[slug]))
    db_conn.commit()

    from ingredients.dedup.cluster import run_cluster_compute
    run_cluster_compute(db_conn)
    rows = db_conn.execute(
        "select cluster_id, variant_key from recipes where id in (5201, 5202)"
    ).fetchall()
    assert rows[0] == rows[1]
```

- [ ] **Step 7: Run + commit**

```bash
cd ingredients && uv run pytest tests/test_dedup_cluster.py -v
git add ingredients/src/ingredients/dedup/cluster.py ingredients/tests/test_dedup_cluster.py
git commit -m "dedup: cluster + variant key + run_cluster_compute orchestrator

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 7: Audit queries

### Task 7.1: `dedup/audit.py` — five audit queries

**Files:**
- Create: `ingredients/src/ingredients/dedup/audit.py`
- Test: `ingredients/tests/test_dedup_audit.py`

Each query returns a list of dicts. The CLI prints them; nothing is auto-remediated.

- [ ] **Step 1: Write failing tests**

```python
import pytest

from ingredients.dedup.audit import (
    audit_name_divergence_within_cluster,
    audit_same_canonical_across_clusters,
    audit_underspecified_ingredients,
    audit_high_in_stack_diversity,
    audit_singleton_editorial_names,
    run_all_audits,
)


def test_audit_singleton_editorial_names_flags_best_perfect_ultimate(dedup_fixture, db_conn):
    conn, ids = dedup_fixture
    db_conn.execute("""
        insert into recipes (id, source_url, site, name, jsonld, fetched_at,
                             canonical_name, canonical_name_source, normalizer_version,
                             cluster_id, dedup_version)
        values
            -- A singleton-cluster recipe with editorial-looking name (should flag).
            (6001, 'http://x/best', 'punch', 'Best Negroni Recipe', '{}'::jsonb, now(),
             'negroni', 'alias', 'v1',
             null, 'v1')
        on conflict (source_url) do nothing
    """)
    db_conn.commit()

    rows = audit_singleton_editorial_names(db_conn)
    assert any("best" in (r.get("name") or "").lower() for r in rows)


def test_run_all_audits_returns_dict_keyed_by_signal_name(dedup_fixture, db_conn):
    conn, _ = dedup_fixture
    summary = run_all_audits(db_conn)
    assert "name_divergence_within_cluster" in summary
    assert "same_canonical_across_clusters" in summary
    assert "underspecified_ingredients" in summary
    assert "high_in_stack_diversity" in summary
    assert "singleton_editorial_names" in summary
```

- [ ] **Step 2: Run, expect fail**

- [ ] **Step 3: Implement `audit.py`**

```python
"""Five audit queries for the dedup pipeline. Operator-triaged via the
`cluster audit` CLI subcommand. No automated remediation in v1.
"""

from __future__ import annotations

from typing import Any

import psycopg

_NAME_DIVERGENCE_THRESHOLD = 4
_HIGH_DIVERSITY_THRESHOLD = 3        # distinct taxonomy_node_ids per role within cluster
_EDITORIAL_PATTERNS = ("best", "perfect", "ultimate", "easiest", "world s best")


def audit_name_divergence_within_cluster(conn: psycopg.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"""
        select c.id as cluster_id, c.canonical_name,
               count(distinct r.name) as distinct_names,
               array_agg(distinct r.name order by r.name) as names
        from recipes r
        join recipe_clusters c on c.id = r.cluster_id
        where r.cluster_id is not null
        group by c.id, c.canonical_name
        having count(distinct r.name) >= {_NAME_DIVERGENCE_THRESHOLD}
        order by distinct_names desc
        """
    ).fetchall()
    return [
        {"cluster_id": r[0], "canonical_name": r[1],
         "distinct_names": r[2], "names": r[3]}
        for r in rows
    ]


def audit_same_canonical_across_clusters(conn: psycopg.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select canonical_name, count(*) as cluster_count,
               array_agg(id order by id) as cluster_ids
        from recipe_clusters
        group by canonical_name
        having count(*) > 1
        order by cluster_count desc
        """
    ).fetchall()
    return [
        {"canonical_name": r[0], "cluster_count": r[1], "cluster_ids": r[2]}
        for r in rows
    ]


def audit_underspecified_ingredients(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """Recipes with ≥1 ingredient that resolves to a node where
    is_cluster_node = false (meaning rollup hit the "above the cut"
    case)."""
    rows = conn.execute(
        """
        select r.cluster_id, c.canonical_name,
               count(distinct r.id) as recipe_count,
               array_agg(distinct n.slug) as offending_slugs
        from recipes r
        join recipe_clusters c on c.id = r.cluster_id
        join recipe_ingredients ri on ri.recipe_id = r.id
        join taxonomy_nodes n on n.id = ri.taxonomy_node_id
        where r.cluster_id is not null
          and n.is_cluster_node = false
          and ri.role in ('base_spirit', 'modifier', 'bitters')
        group by r.cluster_id, c.canonical_name
        order by recipe_count desc
        """
    ).fetchall()
    return [
        {"cluster_id": r[0], "canonical_name": r[1],
         "recipe_count": r[2], "offending_slugs": r[3]}
        for r in rows
    ]


def audit_high_in_stack_diversity(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """Clusters where a single role slot has many different specific
    taxonomy_node_ids — surfaces sub-spirit-defining cases (Martinez
    with mixed gin sub-styles, etc.)."""
    rows = conn.execute(
        f"""
        select r.cluster_id, c.canonical_name, ri.role,
               count(distinct ri.taxonomy_node_id) as distinct_specific_nodes
        from recipes r
        join recipe_clusters c on c.id = r.cluster_id
        join recipe_ingredients ri on ri.recipe_id = r.id
        where r.cluster_id is not null
          and ri.role in ('base_spirit', 'modifier')
        group by r.cluster_id, c.canonical_name, ri.role
        having count(distinct ri.taxonomy_node_id) >= {_HIGH_DIVERSITY_THRESHOLD}
        order by distinct_specific_nodes desc
        """
    ).fetchall()
    return [
        {"cluster_id": r[0], "canonical_name": r[1], "role": r[2],
         "distinct_specific_nodes": r[3]}
        for r in rows
    ]


def audit_singleton_editorial_names(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """Recipes that didn't end up in a multi-recipe cluster AND whose
    raw name has editorial markers — likely a name-normalization miss."""
    pattern_clause = " or ".join(
        f"lower(r.name) like %s" for _ in _EDITORIAL_PATTERNS
    )
    params = [f"%{p}%" for p in _EDITORIAL_PATTERNS]
    rows = conn.execute(
        f"""
        select r.id, r.name, r.canonical_name, r.cluster_id
        from recipes r
        where ({pattern_clause})
          and (
            r.cluster_id is null
            or r.cluster_id in (
                select cluster_id from recipes
                where cluster_id is not null
                group by cluster_id
                having count(*) = 1
            )
          )
        order by r.id
        """,
        params,
    ).fetchall()
    return [
        {"id": r[0], "name": r[1], "canonical_name": r[2], "cluster_id": r[3]}
        for r in rows
    ]


def run_all_audits(conn: psycopg.Connection) -> dict[str, list[dict[str, Any]]]:
    return {
        "name_divergence_within_cluster":  audit_name_divergence_within_cluster(conn),
        "same_canonical_across_clusters":  audit_same_canonical_across_clusters(conn),
        "underspecified_ingredients":      audit_underspecified_ingredients(conn),
        "high_in_stack_diversity":         audit_high_in_stack_diversity(conn),
        "singleton_editorial_names":       audit_singleton_editorial_names(conn),
    }
```

- [ ] **Step 4: Run + commit**

```bash
cd ingredients && uv run pytest tests/test_dedup_audit.py -v
git add ingredients/src/ingredients/dedup/audit.py ingredients/tests/test_dedup_audit.py
git commit -m "dedup: five audit queries for cluster-quality review

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 8: promote-substances (post-D auto-create cleanup)

### Task 8.1: `dedup/promote_substances.py` — interactive substance-promotion

**Files:**
- Create: `ingredients/src/ingredients/dedup/promote_substances.py`
- Test: `ingredients/tests/test_dedup_promote_substances.py`

The procedure walks an allowlist of "definitional substance" names, finds matching auto-created `role IN ('brand','expression')` nodes, and promotes them to `role=NULL, is_cluster_node=true`. Each promotion is interactive (operator confirms) and writes a `taxonomy_provenance` audit row.

- [ ] **Step 1: Write failing tests**

```python
import pytest

from ingredients.dedup.promote_substances import (
    DEFINITIONAL_SUBSTANCES,
    candidate_promotions,
    promote_node,
)


def test_definitional_substances_includes_expected_names():
    expected = {
        "campari", "aperol", "fernet branca", "angostura",
        "peychaud's", "chartreuse", "cynar", "suze",
        "benedictine", "drambuie", "pimm's", "amaro montenegro",
    }
    seen = {s.lower() for s in DEFINITIONAL_SUBSTANCES}
    missing = expected - seen
    assert not missing, f"DEFINITIONAL_SUBSTANCES missing: {missing}"


def test_candidate_promotions_finds_auto_created_brands(dedup_fixture, db_conn):
    """Insert an auto-created 'campari' brand node (as if D's mapper made
    it before E's promote-substances run); the candidate query must find it."""
    conn, ids = dedup_fixture
    # Replace the fixture's substance-modeled campari with an auto-created
    # brand node to simulate the pre-promotion state.
    db_conn.execute("""
        update taxonomy_nodes
           set role = 'brand', is_cluster_node = false, role_default = null
         where slug = 'campari'
    """)
    db_conn.execute("""
        insert into taxonomy_provenance (node_id, source, mapper_version, raw_string, model_id)
        values ((select id from taxonomy_nodes where slug = 'campari'),
                'llm-mapper', 'v1', 'Campari', 'claude-haiku-4-5')
        on conflict (node_id) do update set source = 'llm-mapper'
    """)
    db_conn.commit()

    cands = candidate_promotions(db_conn)
    slugs = {c["slug"] for c in cands}
    assert "campari" in slugs


def test_promote_node_sets_role_null_and_is_cluster_node_true(dedup_fixture, db_conn):
    conn, ids = dedup_fixture
    db_conn.execute("""
        update taxonomy_nodes
           set role = 'brand', is_cluster_node = false, role_default = null
         where slug = 'campari'
    """)
    db_conn.commit()

    promote_node(
        db_conn, slug="campari",
        role_default="modifier",
        promoter="test-suite",
    )

    row = db_conn.execute(
        "select role, is_cluster_node, role_default from taxonomy_nodes where slug = 'campari'"
    ).fetchone()
    assert row == (None, True, "modifier")
```

- [ ] **Step 2: Run, expect fail**

- [ ] **Step 3: Implement `promote_substances.py`**

```python
"""One-shot post-D substance promotion.

D's mapper auto-creates role='brand' or role='expression' nodes for
strings that aren't in the seed. Some of those strings are commercially-
branded *but functionally definitional* substances (Campari, Aperol,
Angostura, Peychaud's, etc.). E's antichain modeling expects them as
role=NULL substance nodes, with is_cluster_node=true.

This module:
  - Holds the curator-reviewed allowlist of substance names.
  - Finds auto-created nodes matching the allowlist.
  - Promotes each (interactively in the CLI; programmatically via promote_node).

Auto-created brand nodes already have the right node_id (recipe_ingredients
rows reference them); no row updates are needed. Only role + is_cluster_node
+ role_default + a provenance log entry change.
"""

from __future__ import annotations

import psycopg

# Hand-curated. Add to this list when a new substance turns out to need
# promotion. Each name is matched case-insensitively against
# taxonomy_nodes.display_name.
#
# Default role mapping per substance (most are 'modifier'; bitters are 'bitters').
DEFINITIONAL_SUBSTANCES: list[tuple[str, str]] = [
    # (display_name_lower, role_default)
    ("campari",            "modifier"),
    ("aperol",             "modifier"),
    ("amaro montenegro",   "modifier"),
    ("amaro nonino",       "modifier"),
    ("fernet branca",      "modifier"),
    ("fernet-branca",      "modifier"),
    ("cynar",              "modifier"),
    ("chartreuse",         "modifier"),
    ("green chartreuse",   "modifier"),
    ("yellow chartreuse",  "modifier"),
    ("benedictine",        "modifier"),
    ("bénédictine",        "modifier"),
    ("drambuie",           "modifier"),
    ("pimm's",             "modifier"),
    ("pimms",              "modifier"),
    ("suze",               "modifier"),
    ("angostura",          "bitters"),
    ("angostura bitters",  "bitters"),
    ("peychaud's",         "bitters"),
    ("peychauds",          "bitters"),
    ("peychaud's bitters", "bitters"),
]


def candidate_promotions(conn: psycopg.Connection) -> list[dict]:
    """Return auto-created nodes whose display_name matches an allowlist
    entry AND whose current role is brand/expression."""
    names_lc = [n for n, _ in DEFINITIONAL_SUBSTANCES]
    rows = conn.execute(
        """
        select n.id, n.slug, n.display_name, n.role, p.raw_string, p.source
        from taxonomy_nodes n
        left join taxonomy_provenance p on p.node_id = n.id
        where n.role in ('brand', 'expression')
          and lower(n.display_name) = any(%s)
        order by n.display_name
        """,
        (names_lc,),
    ).fetchall()
    role_default_by_name = {
        n.lower(): rd for n, rd in DEFINITIONAL_SUBSTANCES
    }
    return [
        {
            "id": r[0],
            "slug": r[1],
            "display_name": r[2],
            "current_role": r[3],
            "provenance_raw_string": r[4],
            "provenance_source": r[5],
            "proposed_role_default": role_default_by_name.get(r[2].lower()),
        }
        for r in rows
    ]


def promote_node(
    conn: psycopg.Connection,
    *,
    slug: str,
    role_default: str,
    promoter: str = "operator",
) -> None:
    """Set role=NULL, is_cluster_node=true, role_default=<role_default>.
    Logs the promotion in taxonomy_provenance for audit (using a sentinel
    source value 'e-substance-promotion')."""
    conn.execute(
        """
        update taxonomy_nodes
           set role = null,
               is_cluster_node = true,
               role_default = %s
         where slug = %s
        """,
        (role_default, slug),
    )
    conn.execute(
        """
        insert into taxonomy_provenance
            (node_id, source, mapper_version, raw_string, model_id)
        select id, 'e-substance-promotion', 'v1', %s, %s
        from taxonomy_nodes
        where slug = %s
        on conflict (node_id) do update
            set source = 'e-substance-promotion',
                raw_string = excluded.raw_string,
                model_id = excluded.model_id
        """,
        (f"promoted by {promoter}", "manual", slug),
    )
    conn.commit()
```

- [ ] **Step 4: Run + commit**

```bash
cd ingredients && uv run pytest tests/test_dedup_promote_substances.py -v
git add ingredients/src/ingredients/dedup/promote_substances.py ingredients/tests/test_dedup_promote_substances.py
git commit -m "dedup: post-D substance-promotion (allowlist + promote_node)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 9: CLI integration

Add subcommands on the existing `parse_ingredients` CLI ([ingredients/src/ingredients/cli.py](../../ingredients/src/ingredients/cli.py)). Match D's `map` / `map resolve-pending` subcommand style.

### Task 9.1: CLI: `normalize-names` + sub-subcommands

**Files:**
- Modify: `ingredients/src/ingredients/cli.py`
- Test: `ingredients/tests/test_dedup_cli.py`

The existing CLI is a `argparse`-based dispatcher. Read it first to understand subparser conventions, then add:
- `normalize-names` (default behavior: phase 1)
- `normalize-names resolve-pending --provider {claude,ollama} [--limit N] [--yes]`
- `normalize-names list-pending [--limit N]`
- `normalize-names --review` (eval mode; runs against fixture, no DB writes)
- Standard flags: `--site`, `--limit`, `--dry-run`, `--reset --except-version V --older-than ISO_TS --yes`

- [ ] **Step 1: Add failing test for the dispatcher wiring**

```python
"""Test the CLI dispatcher recognizes the new subcommands. End-to-end
behavior is exercised in the layer tests already; this is just shape."""

import pytest

from ingredients.cli import build_arg_parser


def test_cli_recognizes_normalize_names_subcommand():
    args = build_arg_parser().parse_args(["normalize-names"])
    assert args.cmd == "normalize-names"


def test_cli_recognizes_normalize_names_resolve_pending():
    args = build_arg_parser().parse_args([
        "normalize-names", "resolve-pending", "--provider", "ollama",
    ])
    assert args.cmd == "normalize-names"
    assert args.normalize_cmd == "resolve-pending"
    assert args.provider == "ollama"


def test_cli_recognizes_cluster_subcommand():
    args = build_arg_parser().parse_args(["cluster"])
    assert args.cmd == "cluster"


def test_cli_recognizes_cluster_audit():
    args = build_arg_parser().parse_args(["cluster", "audit"])
    assert args.cmd == "cluster"
    assert args.cluster_cmd == "audit"


def test_cli_recognizes_promote_substances():
    args = build_arg_parser().parse_args(["promote-substances"])
    assert args.cmd == "promote-substances"


def test_cli_recognizes_dedup_all():
    args = build_arg_parser().parse_args(["dedup-all"])
    assert args.cmd == "dedup-all"
```

- [ ] **Step 2: Run, expect fail**

- [ ] **Step 3: Wire the new subcommands in `cli.py`**

Read `ingredients/src/ingredients/cli.py` first. Find the `build_arg_parser()` function and the place where `map` is registered (around line 86 in the version that shipped with D). Add new subparsers that mirror the `map` registration pattern.

Add helper functions for adding common flags (mirroring `_add_map_args`):

```python
def _add_normalize_names_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--review", action="store_true",
                   help="Run the dedup eval set; do not touch the database.")
    p.add_argument("--site", default=None,
                   help="Restrict to one source site.")
    p.add_argument("--limit", type=int, default=None,
                   help="Process at most N distinct names.")
    p.add_argument("--dry-run", action="store_true",
                   help="Compute resolutions; do not write to the database.")
    p.add_argument("--sample", type=int, default=None,
                   help="Spot-check N random pending names; print, write nothing.")
    add_reset_args(p, stage="recipes (normalization columns)")


def _add_cluster_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--site", default=None,
                   help="Restrict to one source site.")
    p.add_argument("--limit", type=int, default=None,
                   help="Process at most N recipes.")
    p.add_argument("--dry-run", action="store_true",
                   help="Compute clusters; do not write to the database.")
    p.add_argument("--review", action="store_true",
                   help="Run the dedup eval set; do not touch the database.")
    add_reset_args(p, stage="recipes (cluster_id, variant_key, dedup_version)")
```

Register the subparsers:

```python
# normalize-names subcommand: Phase 1 (alias + lexical) by default.
p_norm = sub.add_parser(
    "normalize-names",
    help="Cocktail-name normalization. Phase 1 by default.",
)
_add_normalize_names_args(p_norm)
norm_sub = p_norm.add_subparsers(dest="normalize_cmd")

p_resolve_norm = norm_sub.add_parser(
    "resolve-pending",
    help="Phase 2 — drain the pending_llm queue using the chosen provider.",
)
p_resolve_norm.add_argument(
    "--provider", choices=["claude", "ollama"], required=True,
    help="LLM provider to use.",
)
p_resolve_norm.add_argument(
    "--limit", type=int, default=None,
    help="Process at most N distinct pending names.",
)
p_resolve_norm.add_argument(
    "--yes", action="store_true",
    help="Skip the residual-count confirmation prompt.",
)

p_list_pending = norm_sub.add_parser(
    "list-pending",
    help="List names queued for Phase 2, ranked by recipe-row frequency.",
)
p_list_pending.add_argument(
    "--limit", type=int, default=50,
    help="List at most N names (default: 50).",
)

# cluster subcommand: cluster compute by default.
p_cluster = sub.add_parser(
    "cluster",
    help="Compute clusters + variants from normalized recipes.",
)
_add_cluster_args(p_cluster)
cluster_sub = p_cluster.add_subparsers(dest="cluster_cmd")
p_audit = cluster_sub.add_parser(
    "audit",
    help="Print the five cluster-quality audit signals.",
)

# promote-substances subcommand.
p_promote = sub.add_parser(
    "promote-substances",
    help="Walk the post-D substance-promotion allowlist interactively.",
)
p_promote.add_argument("--yes", action="store_true",
                       help="Promote without per-row confirmation.")

# dedup-all: chained convenience.
p_all = sub.add_parser(
    "dedup-all",
    help="Run normalize-names (phase 1) then cluster, in order.",
)
_add_cluster_args(p_all)
```

In the dispatcher (`main()` or equivalent), add branches for each new `args.cmd`:

```python
elif args.cmd == "normalize-names":
    if args.normalize_cmd == "resolve-pending":
        from ingredients.dedup.normalizer_llm import run_phase2
        from ingredients.mapping.llm_provider_claude import ClaudeProvider
        from ingredients.mapping.llm_provider_ollama import OllamaProvider
        provider = (
            ClaudeProvider() if args.provider == "claude"
            else OllamaProvider()
        )
        # Show residual count + top-N before charging.
        residuals = fetch_pending_canonical_names(conn, normalizer_version=NORMALIZER_VERSION)
        log.info("Phase 2: %d distinct names pending. Top 20:", len(residuals))
        for n in residuals[:20]:
            log.info("  %s", n)
        if not args.yes and len(residuals) > 0:
            confirm = input(f"Run Phase 2 against {args.provider} ({len(residuals)} names)? [y/N] ")
            if confirm.strip().lower() != "y":
                return
        counts = run_phase2(conn, provider=provider, limit=args.limit)
        print_summary("normalize-names resolve-pending", counts)
    elif args.normalize_cmd == "list-pending":
        residuals = fetch_pending_canonical_names(conn, normalizer_version=NORMALIZER_VERSION, limit=args.limit)
        for n in residuals:
            print(n)
    else:
        if args.review:
            from ingredients.dedup.eval_set import run_eval
            run_eval()
            return
        if args.reset:
            confirm_reset(args, scope=describe_reset_scope(...))
            # Reset normalize columns
            conn.execute("""
                update recipes
                   set canonical_name = null, canonical_name_source = null,
                       normalizer_version = null, normalized_at = null
                 where ...
            """)
            conn.commit()
        from ingredients.dedup.normalizer import run_phase1
        counts = run_phase1(conn, site=args.site, limit=args.limit)
        print_summary("normalize-names", counts)

elif args.cmd == "cluster":
    if args.cluster_cmd == "audit":
        from ingredients.dedup.audit import run_all_audits
        sigs = run_all_audits(conn)
        for name, rows in sigs.items():
            print(f"\n=== {name} ({len(rows)} rows) ===")
            for r in rows[:50]:
                print(f"  {r}")
    else:
        if args.review:
            from ingredients.dedup.eval_set import run_eval
            run_eval()
            return
        if args.reset:
            # Reset cluster + variant + role columns
            ...
        from ingredients.dedup.cluster import run_cluster_compute
        counts = run_cluster_compute(conn, site=args.site, limit=args.limit)
        print_summary("cluster", counts)

elif args.cmd == "promote-substances":
    from ingredients.dedup.promote_substances import (
        candidate_promotions, promote_node,
    )
    cands = candidate_promotions(conn)
    if not cands:
        log.info("No candidates for promotion.")
        return
    for c in cands:
        print(f"\nCandidate: {c['display_name']} (slug={c['slug']}, current_role={c['current_role']})")
        print(f"  proposed: role=NULL, is_cluster_node=true, role_default={c['proposed_role_default']}")
        if not args.yes:
            ans = input("Promote? [y/N/q] ").strip().lower()
            if ans == "q":
                break
            if ans != "y":
                continue
        promote_node(
            conn, slug=c["slug"],
            role_default=c["proposed_role_default"],
            promoter=os.environ.get("USER", "operator"),
        )
        log.info("Promoted %s.", c["slug"])

elif args.cmd == "dedup-all":
    from ingredients.dedup.normalizer import run_phase1
    from ingredients.dedup.cluster import run_cluster_compute
    n = run_phase1(conn, site=args.site, limit=args.limit)
    print_summary("normalize-names", n)
    c = run_cluster_compute(conn, site=args.site, limit=args.limit)
    print_summary("cluster", c)
```

Adapt the existing CLI's idioms (logger, exit codes, conn-fixture) to match.

- [ ] **Step 4: Run dispatcher tests + manually exercise**

```bash
cd ingredients && uv run pytest tests/test_dedup_cli.py -v
cd ingredients && uv run python -m ingredients.cli normalize-names --help
cd ingredients && uv run python -m ingredients.cli cluster --help
cd ingredients && uv run python -m ingredients.cli dedup-all --help
```

- [ ] **Step 5: Commit**

```bash
git add ingredients/src/ingredients/cli.py ingredients/tests/test_dedup_cli.py
git commit -m "dedup: CLI subcommands (normalize-names, cluster, promote-substances, dedup-all)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 10: Eval set + scripts + docs

### Task 10.1: `dedup/eval_set.py` — eval cases + driver

**Files:**
- Create: `ingredients/src/ingredients/dedup/eval_set.py`
- Test: `ingredients/tests/test_dedup_eval.py`

The eval set is the regression suite that runs on every version bump. Each case asserts a specific raw-name + ingredient-list combination resolves to an expected canonical name and an expected cluster-equivalent grouping.

- [ ] **Step 1: Build the case dataclass + a starter set**

Create `eval_set.py`:

```python
"""Dedup eval cases. Drives both --review (CI) and ad-hoc spot-checks.

Each case fixes:
  - raw_name        : what the recipe is titled
  - ingredients     : (slug, amount, unit, position) tuples
  - expect_canonical: post-normalize_cocktail_name lookup result
  - expect_cluster_label : a label string; cases sharing the same label
                          must end up in the same cluster after compute.

The fixture taxonomy (eval_fixture.py) is the only DB state these cases
depend on. Run --review against TEST_DB_URL.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import psycopg

from .cluster import compute_cluster_key, compute_variant_key
from .eval_fixture import seed_dedup_fixture
from .normalize import normalize_cocktail_name
from .role_classifier import classify_role
from .rollup import roll_up_to_antichain


@dataclass(frozen=True)
class DedupEvalCase:
    raw_name: str
    ingredients: list[tuple[str, float, str, int]]   # (slug, amount, unit, position)
    expect_canonical: str
    expect_cluster_label: str


CASES: list[DedupEvalCase] = [
    DedupEvalCase(
        raw_name="Negroni",
        ingredients=[("london_dry_gin", 1.0, "oz", 1),
                     ("campari",        1.0, "oz", 2),
                     ("sweet_vermouth", 1.0, "oz", 3)],
        expect_canonical="negroni",
        expect_cluster_label="negroni-classic",
    ),
    DedupEvalCase(
        raw_name="The Best Negroni Recipe",
        ingredients=[("london_dry_gin", 1.0, "oz", 1),
                     ("campari",        1.0, "oz", 2),
                     ("sweet_vermouth", 1.0, "oz", 3)],
        expect_canonical="negroni",
        expect_cluster_label="negroni-classic",
    ),
    DedupEvalCase(
        raw_name="Negroni (Italian Aperitivo)",
        ingredients=[("london_dry_gin", 1.5, "oz", 1),  # different ratio
                     ("campari",        1.0, "oz", 2),
                     ("sweet_vermouth", 1.0, "oz", 3)],
        expect_canonical="negroni",
        expect_cluster_label="negroni-classic",  # same cluster, different variant
    ),
    DedupEvalCase(
        # Aperol-Negroni-style swap: same name family pattern, but the modifier
        # antichain node differs (aperol vs campari). Demonstrates that
        # ingredient-set divergence produces a different cluster even when
        # the rolled-up category set looks "Negroni-shaped."
        raw_name="Aperol Negroni",
        ingredients=[("london_dry_gin", 1.0, "oz", 1),
                     ("aperol",         1.0, "oz", 2),
                     ("sweet_vermouth", 1.0, "oz", 3)],
        expect_canonical="aperol negroni",
        expect_cluster_label="aperol-negroni",  # different cluster from negroni-classic
    ),
    DedupEvalCase(
        raw_name="Old Fashioned",
        ingredients=[("bourbon",            2.0, "oz",   1),
                     ("simple_syrup",       0.25, "oz",  2),
                     ("angostura_bitters",  2.0, "dash", 3)],
        expect_canonical="old fashioned",
        expect_cluster_label="old-fashioned-bourbon",
    ),
    DedupEvalCase(
        raw_name="Rye Old Fashioned",
        ingredients=[("rye_whiskey",        2.0, "oz",   1),
                     ("simple_syrup",       0.25, "oz",  2),
                     ("angostura_bitters",  2.0, "dash", 3)],
        expect_canonical="old fashioned",  # name still normalizes
        expect_cluster_label="old-fashioned-rye",  # but ingredient set differs
    ),
]


@dataclass
class EvalReport:
    passed: int = 0
    failed: int = 0
    failures: list[str] = field(default_factory=list)


def run_eval() -> EvalReport:
    """Run cases against TEST_DB_URL using the fixture. Caller is the CLI;
    we do not orchestrate transaction control here beyond what
    seed_dedup_fixture does."""
    import os
    import psycopg as pg

    test_db_url = os.environ.get("TEST_DB_URL")
    if not test_db_url:
        raise RuntimeError("TEST_DB_URL not set; eval requires fixture DB.")

    report = EvalReport()
    with pg.connect(test_db_url, autocommit=False) as conn:
        ids = seed_dedup_fixture(conn)

        # Build {label: cluster_key} from cases as we go; cases sharing a
        # label must agree on cluster_key.
        labels: dict[str, str] = {}
        for case in CASES:
            try:
                _evaluate_case(conn, case, ids, labels)
                report.passed += 1
            except AssertionError as exc:
                report.failed += 1
                report.failures.append(f"{case.raw_name}: {exc}")

    if report.failures:
        for f in report.failures:
            print("FAIL:", f)
    print(f"\n{report.passed} passed, {report.failed} failed.")
    return report


def _evaluate_case(
    conn: psycopg.Connection,
    case: DedupEvalCase,
    ids: dict[str, int],
    labels: dict[str, str],
) -> None:
    # 1. Name normalization expectation.
    normalized = normalize_cocktail_name(case.raw_name)
    row = conn.execute(
        "select canonical_name from cocktail_aliases where alias = %s",
        (normalized,),
    ).fetchone()
    canonical = row[0] if row else None
    assert canonical == case.expect_canonical, (
        f"name normalization: got {canonical!r}, expected {case.expect_canonical!r}"
    )

    # 2. Build the ingredient list with role + antichain rollup.
    ings = []
    for slug, amount, unit, pos in case.ingredients:
        node_id = ids[slug]
        node_row = conn.execute(
            "select role_default, is_defining_garnish from taxonomy_nodes where id = %s",
            (node_id,),
        ).fetchone()
        role_default, is_def_garnish = node_row
        ing = {
            "taxonomy_node_slug": slug, "taxonomy_node_id": node_id,
            "role_default": role_default, "is_defining_garnish": is_def_garnish,
            "amount": amount, "unit": unit, "position": pos, "raw_text": "",
        }
        role, _ = classify_role(ing)
        ing["role"] = role
        ing["antichain_node_id"] = roll_up_to_antichain(conn, node_id)
        ings.append(ing)

    # 3. Cluster key expectation.
    cluster_key = compute_cluster_key(case.expect_canonical, ings)
    if case.expect_cluster_label in labels:
        assert labels[case.expect_cluster_label] == cluster_key, (
            f"cluster mismatch for label {case.expect_cluster_label}: "
            f"got {cluster_key[:8]}…, expected {labels[case.expect_cluster_label][:8]}…"
        )
    else:
        labels[case.expect_cluster_label] = cluster_key
```

- [ ] **Step 2: Add the smoke test**

```python
import pytest

from ingredients.dedup.eval_set import run_eval


def test_dedup_eval_passes(monkeypatch):
    import os
    if not os.environ.get("TEST_DB_URL"):
        pytest.skip("TEST_DB_URL not set")
    report = run_eval()
    assert report.failed == 0, report.failures
```

- [ ] **Step 3: Run + commit**

```bash
cd ingredients && uv run pytest tests/test_dedup_eval.py -v
git add ingredients/src/ingredients/dedup/eval_set.py ingredients/tests/test_dedup_eval.py
git commit -m "dedup: eval set + run_eval driver

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 10.2: Extend `supabase/seeds/taxonomy_nodes.sql` with starter antichain

The full curator-track seed expansion is out of scope for this plan, but we land a minimum-viable starter so the dev DB lets the pipeline run end-to-end against a few real recipes.

**Files:**
- Modify: `supabase/seeds/taxonomy_nodes.sql`

- [ ] **Step 1: Read the file to find the existing structure**

```bash
cat supabase/seeds/taxonomy_nodes.sql | head -120
```

- [ ] **Step 2: Append starter antichain content + role_defaults + a few new nodes**

Append at the end of `supabase/seeds/taxonomy_nodes.sql`:

```sql
-- E [Phase 10]: starter antichain markers + role_defaults on existing nodes.
-- The full curator-track expansion (gin sub-styles, individual amari,
-- individual bitters, key liqueurs, fortified wines, broader categories)
-- runs as parallel reviewer-gated PRs. This is the minimum needed for
-- the dev DB to exercise the dedup pipeline.

-- Mark whiskey subtypes as antichain.
update taxonomy_nodes set is_cluster_node = true, role_default = 'base_spirit'
 where slug in ('bourbon', 'rye_whiskey', 'scotch_whisky', 'irish_whiskey',
                'japanese_whisky');

-- Vermouth subtypes (already in seed; add antichain + role_default).
update taxonomy_nodes set is_cluster_node = true, role_default = 'modifier'
 where slug in ('sweet_vermouth', 'dry_vermouth', 'blanc_vermouth');

-- Rum + tequila subtypes.
update taxonomy_nodes set is_cluster_node = true, role_default = 'base_spirit'
 where slug in ('white_rum', 'dark_rum', 'aged_rum',
                'blanco_tequila', 'reposado_tequila', 'anejo_tequila',
                'mezcal');

-- Brandy subtypes.
update taxonomy_nodes set is_cluster_node = true, role_default = 'base_spirit'
 where slug in ('cognac', 'armagnac', 'calvados');

-- Citrus juices (existing produce).
update taxonomy_nodes set role_default = 'citrus'
 where slug in ('lemon', 'lime', 'orange', 'grapefruit');

-- Add a starter set of nodes that don't exist in the current seed but
-- are essential for the dedup pipeline to do useful work.
insert into taxonomy_nodes (slug, display_name, role, is_cluster_node, role_default) values
  -- Gin sub-styles (definitional)
  ('london_dry_gin',      'London Dry Gin',      null, true, 'base_spirit'),
  ('old_tom_gin',         'Old Tom Gin',         null, true, 'base_spirit'),
  ('plymouth_gin',        'Plymouth Gin',        null, true, 'base_spirit'),
  -- Bitters (definitional, not brand-modeled)
  ('angostura_bitters',   'Angostura Bitters',   null, true, 'bitters'),
  ('peychauds_bitters',   "Peychaud's Bitters",  null, true, 'bitters'),
  ('orange_bitters',      'Orange Bitters',      null, true, 'bitters'),
  -- Amari (definitional)
  ('campari',             'Campari',             null, true, 'modifier'),
  ('aperol',              'Aperol',              null, true, 'modifier'),
  -- Sweeteners
  ('simple_syrup',        'Simple Syrup',        null, true, 'sweetener'),
  ('demerara_syrup',      'Demerara Syrup',      null, true, 'sweetener'),
  ('honey_syrup',         'Honey Syrup',         null, true, 'sweetener'),
  -- Citrus juices (form nodes; D's mapper may auto-create these too)
  ('lemon_juice',         'Lemon Juice',         null, true, 'citrus'),
  ('lime_juice',          'Lime Juice',          null, true, 'citrus'),
  ('orange_juice',        'Orange Juice',        null, true, 'citrus'),
  ('grapefruit_juice',    'Grapefruit Juice',    null, true, 'citrus'),
  -- Dilution + ice
  ('soda_water',          'Soda Water',          null, true, 'dilution'),
  ('tonic_water',          'Tonic Water',         null, true, 'dilution'),
  ('ice',                 'Ice',                 null, true, 'ice'),
  -- Defining garnishes
  ('cocktail_onion',      'Cocktail Onion',      null, true, 'garnish'),
  ('salt_rim',            'Salt Rim',            null, true, 'garnish')
on conflict (slug) do nothing;

-- Mark defining-garnish flags.
update taxonomy_nodes set is_defining_garnish = true
 where slug in ('cocktail_onion', 'salt_rim');

-- Edges for new sub-style nodes.
insert into taxonomy_edges (parent_id, child_id)
select p.id, c.id
from (values
  ('gin', 'london_dry_gin'),
  ('gin', 'old_tom_gin'),
  ('gin', 'plymouth_gin'),
  ('bitters', 'angostura_bitters'),
  ('bitters', 'peychauds_bitters'),
  ('bitters', 'orange_bitters'),
  ('amaro', 'campari'),
  ('amaro', 'aperol'),
  ('lemon', 'lemon_juice'),
  ('lime',  'lime_juice'),
  ('orange', 'orange_juice'),
  ('grapefruit', 'grapefruit_juice')
) as e(parent_slug, child_slug)
join taxonomy_nodes p on p.slug = e.parent_slug
join taxonomy_nodes c on c.slug = e.child_slug
on conflict do nothing;

-- Aliases for the new substance nodes.
insert into taxonomy_aliases (alias, node_id)
select a.alias, n.id
from (values
  ('london dry',         'london_dry_gin'),
  ('old tom',            'old_tom_gin'),
  ('angostura',          'angostura_bitters'),
  ('peychauds',          'peychauds_bitters'),
  ("peychaud's",         'peychauds_bitters'),
  ('orange bitter',      'orange_bitters'),
  ('lemon juice',        'lemon_juice'),
  ('lime juice',         'lime_juice'),
  ('fresh lemon juice',  'lemon_juice'),
  ('fresh lime juice',   'lime_juice'),
  ('simple',             'simple_syrup'),
  ('demerara',           'demerara_syrup'),
  ('honey',              'honey_syrup'),
  ('soda',               'soda_water'),
  ('club soda',          'soda_water'),
  ('tonic',              'tonic_water')
) as a(alias, slug)
join taxonomy_nodes n on n.slug = a.slug
on conflict do nothing;

-- Cocktail aliases — starter seed for E's name normalizer.
insert into cocktail_aliases (alias, canonical_name, source) values
  ('negroni',          'negroni',         'seed'),
  ('old fashioned',    'old fashioned',   'seed'),
  ('manhattan',        'manhattan',       'seed'),
  ('martini',          'martini',         'seed'),
  ('daiquiri',         'daiquiri',        'seed'),
  ('daquiri',          'daiquiri',        'seed'),
  ('margarita',        'margarita',       'seed'),
  ('whiskey sour',     'whiskey sour',    'seed'),
  ('whisky sour',      'whiskey sour',    'seed'),
  ('tom collins',      'tom collins',     'seed'),
  ('gimlet',           'gimlet',          'seed'),
  ('aviation',         'aviation',        'seed'),
  ('last word',        'last word',       'seed'),
  ('sazerac',          'sazerac',         'seed'),
  ('sidecar',          'sidecar',         'seed'),
  ('vesper',           'vesper',          'seed'),
  ('boulevardier',     'boulevardier',    'seed'),
  ('paper plane',      'paper plane',     'seed'),
  ('penicillin',       'penicillin',      'seed'),
  ('jungle bird',      'jungle bird',     'seed')
on conflict do nothing;
```

- [ ] **Step 3: Apply to dev DB + commit**

```bash
supabase db reset --db-url "postgresql://postgres:postgres@192.168.65.254:54322/postgres" --yes
git add supabase/seeds/taxonomy_nodes.sql
git commit -m "seed: starter antichain markers + cocktail_aliases for [E]

Minimum-viable seed extension to exercise the dedup pipeline end-to-end.
The full reviewer-gated curator track will land additional gin sub-styles,
amari, bitters, liqueurs, fortified wines, and the broader alias seed
in subsequent PRs.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 10.3: `scripts/refresh-processed-seeds.sh` — restore + dump modes

**Files:**
- Create: `scripts/refresh-processed-seeds.sh`
- Create: `supabase/seeds/processed/` (empty placeholder; populated by first dump)

- [ ] **Step 1: Write the script**

```bash
#!/usr/bin/env bash
# scripts/refresh-processed-seeds.sh
#
# Two modes:
#   restore  — apply committed processed seeds, then run deterministic
#              recompute steps so the DB matches a from-scratch run.
#   dump     — refresh committed seed files from current DB state,
#              filtered to LLM-resolved + curator-promoted rows.
#
# This is the "rinse and repeat" pattern documented in CLAUDE.md.
# Default for all stages going forward; new stages plug in by adding
# their dump/restore steps to this script.

set -euo pipefail

DB_URL="${SUPABASE_DB_URL:-postgresql://postgres:postgres@host.docker.internal:54322/postgres}"
PROCESSED_DIR="$(git rev-parse --show-toplevel)/supabase/seeds/processed"
mkdir -p "$PROCESSED_DIR"

cmd="${1:-}"

dump_table() {
  local out="$1"
  local sql="$2"
  echo "Dumping → $out"
  psql "$DB_URL" -At -c "$sql" > "$out.tmp"
  mv "$out.tmp" "$out"
}

dump_mode() {
  # 00: taxonomy nodes auto-created or substance-promoted (provenance source != 'seed').
  dump_table "$PROCESSED_DIR/00_taxonomy_grown.sql" \
    "select format(
       'insert into taxonomy_nodes (slug, display_name, role, is_cluster_node, role_default, is_defining_garnish) values (%L, %L, %L, %L, %L, %L) on conflict (slug) do nothing;',
       n.slug, n.display_name, n.role, n.is_cluster_node, n.role_default, n.is_defining_garnish
     )
     from taxonomy_nodes n
     join taxonomy_provenance p on p.node_id = n.id
     where p.source in ('llm-mapper', 'e-substance-promotion')
     order by n.id"

  # Edges + aliases for those grown nodes — append to the same file.
  psql "$DB_URL" -At -c "
    select format(
      'insert into taxonomy_edges (parent_id, child_id) select %L::bigint, id from taxonomy_nodes where slug = %L on conflict do nothing;',
      e.parent_id, n.slug
    )
    from taxonomy_edges e
    join taxonomy_nodes n on n.id = e.child_id
    join taxonomy_provenance p on p.node_id = n.id
    where p.source in ('llm-mapper', 'e-substance-promotion')
    order by e.parent_id, e.child_id" >> "$PROCESSED_DIR/00_taxonomy_grown.sql"

  psql "$DB_URL" -At -c "
    select format(
      'insert into taxonomy_aliases (alias, node_id) select %L, id from taxonomy_nodes where slug = %L on conflict do nothing;',
      a.alias, n.slug
    )
    from taxonomy_aliases a
    join taxonomy_nodes n on n.id = a.node_id
    join taxonomy_provenance p on p.node_id = n.id
    where p.source in ('llm-mapper', 'e-substance-promotion')
    order by a.alias" >> "$PROCESSED_DIR/00_taxonomy_grown.sql"

  # 10: D's LLM-resolved recipe_ingredients rows.
  dump_table "$PROCESSED_DIR/10_recipe_ingredients_llm.sql" \
    "select format(
       'update recipe_ingredients set taxonomy_node_id = %L, mapper_source = %L, mapper_version = %L, mapper_at = now() where recipe_id = %L and position = %L;',
       ri.taxonomy_node_id, ri.mapper_source, ri.mapper_version, ri.recipe_id, ri.position
     )
     from recipe_ingredients ri
     where ri.mapper_source = 'llm'
     order by ri.recipe_id, ri.position"

  # 20: E's LLM-resolved recipes.canonical_name rows.
  dump_table "$PROCESSED_DIR/20_recipes_normalized.sql" \
    "select format(
       'update recipes set canonical_name = %L, canonical_name_source = %L, normalizer_version = %L, normalized_at = now() where source_url = %L;',
       r.canonical_name, r.canonical_name_source, r.normalizer_version, r.source_url
     )
     from recipes r
     where r.canonical_name_source = 'llm'
     order by r.id"

  # 30: cocktail_aliases grown by LLM (or curator manual entries).
  dump_table "$PROCESSED_DIR/30_cocktail_aliases.sql" \
    "select format(
       'insert into cocktail_aliases (alias, canonical_name, source) values (%L, %L, %L) on conflict do nothing;',
       a.alias, a.canonical_name, a.source
     )
     from cocktail_aliases a
     where a.source in ('llm', 'manual')
     order by a.alias"

  echo
  echo "Dump complete. Diff:"
  git -C "$(git rev-parse --show-toplevel)" diff --stat -- "$PROCESSED_DIR" || true
}

restore_mode() {
  echo "Applying processed seeds…"
  for f in "$PROCESSED_DIR"/*.sql; do
    [ -e "$f" ] || continue
    echo "  $f"
    psql "$DB_URL" -f "$f" >/dev/null
  done

  echo "Recomputing deterministic outputs…"
  pushd "$(git rev-parse --show-toplevel)/ingredients" >/dev/null
  uv run python -m ingredients.cli map                    # alias + lexical
  uv run python -m ingredients.cli normalize-names        # phase 1
  uv run python -m ingredients.cli cluster                # cluster + variants
  popd >/dev/null

  echo "Done. DB is fully populated."
}

case "$cmd" in
  dump)    dump_mode ;;
  restore) restore_mode ;;
  *)       echo "Usage: $0 {dump|restore}" ; exit 64 ;;
esac
```

- [ ] **Step 2: Make executable + create the directory**

```bash
chmod +x scripts/refresh-processed-seeds.sh
mkdir -p supabase/seeds/processed
touch supabase/seeds/processed/.gitkeep
```

- [ ] **Step 3: Smoke test**

```bash
scripts/refresh-processed-seeds.sh dump
ls -la supabase/seeds/processed/
```

(Files should appear; their content depends on what's in your dev DB. Empty or near-empty is fine for a fresh DB.)

- [ ] **Step 4: Commit**

```bash
git add scripts/refresh-processed-seeds.sh supabase/seeds/processed/.gitkeep
git commit -m "scripts: refresh-processed-seeds.sh (dump + restore for the rinse-and-repeat pattern)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 10.4: End-to-end integration test

**Files:**
- Create: `ingredients/tests/test_dedup_end_to_end.py`

This test wires together everything: seed fixture, insert recipes + ingredients, run phase-1 normalize, run cluster, assert the resulting cluster + variant assignments.

- [ ] **Step 1: Write the test**

```python
"""End-to-end dedup pipeline test against the fixture.

Inserts three Negroni recipes (two identical, one with different ratios)
plus an Old Fashioned. After running normalize + cluster, asserts cluster
membership + variant grouping.
"""

import pytest

from ingredients.dedup.cluster import run_cluster_compute
from ingredients.dedup.normalizer import run_phase1


def test_end_to_end_negroni_old_fashioned(dedup_fixture, db_conn):
    conn, ids = dedup_fixture

    # Three Negronis (two identical, one with different gin amount) +
    # one Old Fashioned.
    db_conn.execute("""
        insert into recipes (id, source_url, site, name, jsonld, fetched_at)
        values
            (7001, 'http://x/n1', 'punch',  'Negroni',                  '{}'::jsonb, now()),
            (7002, 'http://x/n2', 'imbibe', 'The Best Negroni Recipe',  '{}'::jsonb, now()),
            (7003, 'http://x/n3', 'serious-eats', 'Negroni',            '{}'::jsonb, now()),
            (7004, 'http://x/of', 'punch',  'Old Fashioned',            '{}'::jsonb, now())
        on conflict (source_url) do nothing
    """)

    def add_ingredients(rid, ings):
        for pos, slug, amount, unit in ings:
            db_conn.execute("""
                insert into recipe_ingredients
                    (recipe_id, position, raw_text, amount, unit,
                     parse_status, parser_version, taxonomy_node_id,
                     mapper_source, mapper_version)
                values (%s, %s, 'x', %s, %s, 'parsed', 'v1', %s, 'alias', 'v1')
                on conflict (recipe_id, position) do nothing
            """, (rid, pos, amount, unit, ids[slug]))

    add_ingredients(7001, [
        (1, "london_dry_gin",  1.0, "oz"),
        (2, "campari",         1.0, "oz"),
        (3, "sweet_vermouth",  1.0, "oz"),
    ])
    add_ingredients(7002, [
        (1, "london_dry_gin",  1.0, "oz"),
        (2, "campari",         1.0, "oz"),
        (3, "sweet_vermouth",  1.0, "oz"),
    ])
    add_ingredients(7003, [
        (1, "london_dry_gin",  1.5, "oz"),
        (2, "campari",         1.0, "oz"),
        (3, "sweet_vermouth",  1.0, "oz"),
    ])
    add_ingredients(7004, [
        (1, "bourbon",            2.0, "oz"),
        (2, "simple_syrup",       0.25, "oz"),
        (3, "angostura_bitters",  2.0, "dash"),
    ])
    db_conn.commit()

    # Run the pipeline
    norm_counts = run_phase1(db_conn)
    assert norm_counts.get("alias", 0) >= 2  # 'negroni' and 'old fashioned' alias hits
    cluster_counts = run_cluster_compute(db_conn)
    assert cluster_counts["recipes_clustered"] == 4

    # Assert cluster + variant assignments
    rows = {
        r[0]: (r[1], r[2])
        for r in db_conn.execute(
            "select id, cluster_id, variant_key from recipes where id in (7001,7002,7003,7004)"
        ).fetchall()
    }
    # Three Negronis share a cluster
    assert rows[7001][0] == rows[7002][0] == rows[7003][0]
    # 7001 and 7002 are identical → same variant
    assert rows[7001][1] == rows[7002][1]
    # 7003 has different gin amount → different variant
    assert rows[7003][1] != rows[7001][1]
    # Old Fashioned is a separate cluster
    assert rows[7004][0] != rows[7001][0]

    # recipe_clusters row counts populated
    cluster_rows = db_conn.execute(
        "select id, recipe_count, source_count from recipe_clusters where id in (%s, %s)",
        (rows[7001][0], rows[7004][0]),
    ).fetchall()
    counts_by_id = {r[0]: (r[1], r[2]) for r in cluster_rows}
    assert counts_by_id[rows[7001][0]] == (3, 3)  # 3 recipes, 3 distinct sites
    assert counts_by_id[rows[7004][0]] == (1, 1)
```

- [ ] **Step 2: Run + commit**

```bash
cd ingredients && uv run pytest tests/test_dedup_end_to_end.py -v
git add ingredients/tests/test_dedup_end_to_end.py
git commit -m "dedup: end-to-end integration test (3 Negronis + 1 Old Fashioned)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 10.5: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

Append a "Recipe Dedup" section after the existing "Ingredient → Taxonomy Mapper" section, plus a "Processed-data seeding pattern" subsection.

- [ ] **Step 1: Read existing CLAUDE.md to find insertion point**

- [ ] **Step 2: Add the dedup section**

After the "Ingredient → Taxonomy Mapper" section, insert:

```markdown
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

The canonical-name pool grows bottom-up: the seed in [supabase/seeds/taxonomy_nodes.sql](supabase/seeds/taxonomy_nodes.sql) ships ~20 well-known cocktails as `cocktail_aliases`; LLM resolutions add to it.

The eval set is [dedup/eval_set.py](ingredients/src/ingredients/dedup/eval_set.py), run against the fixture taxonomy in [dedup/eval_fixture.py](ingredients/src/ingredients/dedup/eval_fixture.py) so eval results don't drift with seed changes.

## Processed-data seeding pattern

The local Supabase DB gets reset frequently. LLM-touched data and curator-reviewed taxonomy promotions are expensive to recompute, so they're seeded; deterministic state (alias + lexical mappings, role tags, cluster compute) is recomputed on demand.

**Layout:**

```
supabase/seeds/
├── recipes.sql                       (raw scraped recipes)
├── taxonomy_nodes.sql                (hand-curated taxonomy seed)
└── processed/
    ├── 00_taxonomy_grown.sql         (D's auto-created brand/expression nodes,
    │                                  D's LLM-grown taxonomy_aliases,
    │                                  E's promote-substances output)
    ├── 10_recipe_ingredients_llm.sql (D's mapper Layer-3 rows only)
    ├── 20_recipes_normalized.sql     (E's Phase-2 LLM resolutions only)
    └── 30_cocktail_aliases.sql       (E's grown cocktail aliases)
```

**Workflow:**

```bash
# After supabase db reset: bring the DB up to a fully populated state.
scripts/refresh-processed-seeds.sh restore

# After running pipeline cycles that consumed LLM credits: refresh
# committed seed files from the current DB.
scripts/refresh-processed-seeds.sh dump
```

`restore` applies the committed seeds + runs the deterministic recompute steps (D's `map`, E's `normalize-names`, E's `cluster`). `dump` filters to LLM-touched + curator-promoted rows only — anything cheap to re-derive stays out of seeds.

**Going forward.** Any new pipeline stage that emits LLM-resolved or human-curated output adds itself to this pattern: a seed file in `supabase/seeds/processed/NN_<stage>.sql` (filtered to the LLM/curated subset) and an entry in `restore`'s recompute list if it has a deterministic step.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: CLAUDE.md — recipe dedup + processed-data seeding pattern

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Self-review checklist

Before opening the PR, run:

- [ ] All migrations apply cleanly: `supabase db reset --db-url "postgresql://postgres:postgres@192.168.65.254:54322/postgres" --yes`
- [ ] Full test suite green: `cd ingredients && uv run pytest -v`
- [ ] Eval passes: `cd ingredients && uv run python -m ingredients.cli normalize-names --review && cd ingredients && uv run python -m ingredients.cli cluster --review`
- [ ] End-to-end test populates clusters as expected: `cd ingredients && uv run pytest tests/test_dedup_end_to_end.py -v`
- [ ] Refresh script smoke-tests in both modes: `scripts/refresh-processed-seeds.sh dump && scripts/refresh-processed-seeds.sh restore`
- [ ] CLAUDE.md updated with dedup + seeding pattern sections.
- [ ] No debug prints, no commented-out code, no `TODO`s left in committed files.

---

## Open PR

After all tasks are committed:

```bash
git push -u origin worktree-dedup-design
gh pr create --title "Recipe dedup pipeline (Track [E])" --body "$(cat <<'EOF'
Implements [E] from docs/future-direction.md per the design at docs/superpowers/specs/2026-04-29-recipe-dedup-design.md.

Deduplicates recipes by joint key (canonical_name, role-tagged ingredient set rolled up to antichain). Two-level fold: clusters (same drink) + variants (same recipe within cluster). Phase-1 deterministic name normalization (alias + lexical), phase-2 LLM resolution. Reuses D's LLMProvider + retry helper + spiritolo_common utilities. Curator-track taxonomy seed expansion runs in parallel.

Includes a starter cocktail-alias seed (~20 well-known drinks) and a starter antichain marking on existing taxonomy nodes. Full curator-track seed expansion is reviewer-gated and ships in subsequent PRs.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

After merge:
- Land any pending curator-track seed PRs.
- Run `cd ingredients && uv run python -m ingredients.cli dedup-all` against the dev DB for a smoke test.
- Run `scripts/refresh-processed-seeds.sh dump` and commit any meaningful seed updates.






