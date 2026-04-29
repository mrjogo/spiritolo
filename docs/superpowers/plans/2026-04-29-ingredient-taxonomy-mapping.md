# Ingredient → Taxonomy Mapping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a Zone-2 taxonomy mapper that resolves `recipe_ingredients.name` strings to `taxonomy_nodes.id` references, in two phases: Phase 1 (alias + lexical) runs eagerly with no external deps; Phase 2 (LLM) is a separate operator-triggered subcommand with provider choice (Claude or Ollama) deferred until residual count is known.

**Architecture:** New `ingredients/src/ingredients/mapping/` submodule. Phase 1 cascade walks `taxonomy_aliases` (exact match) then `pg_trgm` similarity. Misses get `mapper_source='pending_llm'`. Phase 2 dispatches pending rows through a small `LLMProvider` interface with `claude` and `ollama` implementations. Output lives in new columns on `recipe_ingredients`. Brand/expression auto-create writes provenance; form proposals queue for human review.

**Tech Stack:** Python 3.11+, uv (workspace member `ingredients`), psycopg, `anthropic` SDK, `httpx` (for ollama HTTP), pytest, Supabase Postgres + `pg_trgm`.

**Spec:** [docs/superpowers/specs/2026-04-29-ingredient-taxonomy-mapping-design.md](../specs/2026-04-29-ingredient-taxonomy-mapping-design.md)

---

## Notes for the engineer

- **Working directory.** All work happens inside the worktree at `.worktrees/ingredient-taxonomy-mapping/`. Use absolute or `cd`-prefixed paths in `git` commands.
- **Test discipline.** Write the failing test before the implementation in every task that creates new code. DB-integration tests skip cleanly when `TEST_DB_URL` is unset (see `ingredients/tests/conftest.py`); set it per CLAUDE.md before running them locally.
- **Commit cadence.** One commit per task. Commit messages start with a verb in lowercase imperative ("add", "wire up", "extend").
- **Migrations.** Apply via `supabase db reset --db-url "postgresql://postgres:postgres@192.168.65.254:54322/postgres" --yes` from the host (or via the auto-apply path in `ingredients/tests/conftest.py` for the test DB). The trailing `tls error` message after `db reset` is misleading — the migration succeeded if `select` works.
- **uv.** Run `uv run` from `ingredients/` (e.g. `cd ingredients && uv run pytest -q`).
- **Coordination with [E].** [E] is adding `is_cluster_node`, `role_default`, `is_defining_garnish` columns to `taxonomy_nodes` in its own migration. Don't touch those columns here. The auto-create code in this plan reads `is_cluster_node` only to set the default `false` on new rows.
- **[E]-coordination on seed.** This plan's tests use a fixture taxonomy in `ingredients/src/ingredients/mapping/eval_fixture.py`, not the production seed. The eval set runs against the fixture so it's reproducible regardless of what [E] or future seed-expansion work adds. The fixture lives inside the package so the `map --review` CLI can import it without touching `tests/`.

---

## Phase A — Schema migrations

### Task 1: Migration — add mapping columns to `recipe_ingredients`

**Files:**
- Create: `supabase/migrations/20260429140000_alter_recipe_ingredients_mapping.sql`

- [ ] **Step 1: Write the migration**

```sql
-- Mapping output: which canonical node this ingredient resolved to,
-- which cascade layer (or phase) decided, and the version under which.
alter table recipe_ingredients
  add column taxonomy_node_id bigint references taxonomy_nodes(id),
  add column mapper_source    text check (mapper_source in
    ('alias', 'lexical', 'pending_llm', 'llm', 'abstain')),
  add column mapper_version   text,
  add column mapper_at        timestamptz;

create index recipe_ingredients_taxonomy_idx
  on recipe_ingredients (taxonomy_node_id)
  where taxonomy_node_id is not null;

create index recipe_ingredients_pending_llm_idx
  on recipe_ingredients (mapper_version)
  where mapper_source = 'pending_llm';
```

- [ ] **Step 2: Apply to local Supabase and confirm**

```bash
supabase db reset --db-url "postgresql://postgres:postgres@192.168.65.254:54322/postgres" --yes
```

Then verify (any of these is fine):

```bash
PGPASSWORD=postgres psql -h host.docker.internal -p 54322 -U postgres -d postgres -c "\d recipe_ingredients" 2>/dev/null | grep -E "taxonomy_node_id|mapper_source|mapper_version|mapper_at" || \
uv run --project ingredients python -c "
import os, psycopg
from dotenv import load_dotenv; load_dotenv('/workspaces/spiritolo/.env')
with psycopg.connect(os.environ['SUPABASE_DB_URL']) as c:
    cols = [r[0] for r in c.execute(\"select column_name from information_schema.columns where table_name='recipe_ingredients'\").fetchall()]
print([c for c in cols if c.startswith(('taxonomy_node_id','mapper_'))])"
```

Expected: `['taxonomy_node_id', 'mapper_source', 'mapper_version', 'mapper_at']`.

- [ ] **Step 3: Commit**

```bash
git add supabase/migrations/20260429140000_alter_recipe_ingredients_mapping.sql
git commit -m "add mapping columns to recipe_ingredients"
```

---

### Task 2: Migration — `taxonomy_provenance` table

**Files:**
- Create: `supabase/migrations/20260429140100_create_taxonomy_provenance.sql`

- [ ] **Step 1: Write the migration**

```sql
-- Provenance for taxonomy_nodes auto-created by the mapper, plus a
-- record for hand-seeded nodes when desired. The audit pass (deferred
-- spec) reads this to flag suspicious LLM creations.
create table taxonomy_provenance (
  node_id        bigint primary key references taxonomy_nodes(id) on delete cascade,
  source         text not null check (source in ('seed', 'llm-mapper', 'manual')),
  mapper_version text,
  raw_string     text,         -- the ingredient string that triggered creation
  prompt_hash    text,
  model_id       text,         -- e.g. 'claude-haiku-4-5' or 'qwen3:14b'
  created_at     timestamptz not null default now()
);

alter table taxonomy_provenance enable row level security;
```

- [ ] **Step 2: Apply and confirm**

```bash
supabase db reset --db-url "postgresql://postgres:postgres@192.168.65.254:54322/postgres" --yes
```

```bash
uv run --project ingredients python -c "
import os, psycopg
from dotenv import load_dotenv; load_dotenv('/workspaces/spiritolo/.env')
with psycopg.connect(os.environ['SUPABASE_DB_URL']) as c:
    print(c.execute(\"select to_regclass('public.taxonomy_provenance')\").fetchone())"
```

Expected: `('taxonomy_provenance',)`.

- [ ] **Step 3: Commit**

```bash
git add supabase/migrations/20260429140100_create_taxonomy_provenance.sql
git commit -m "add taxonomy_provenance table for mapper-created nodes"
```

---

### Task 3: Migration — `taxonomy_proposals` table (form review queue)

**Files:**
- Create: `supabase/migrations/20260429140200_create_taxonomy_proposals.sql`

- [ ] **Step 1: Write the migration**

```sql
-- Review queue for form-node proposals from Phase 2's LLM. Form nodes
-- (lemon_zest, lime_oil, etc.) require human review before entering the
-- canonical taxonomy. Brands/expressions auto-create silently and do
-- NOT use this table.
create table taxonomy_proposals (
  id                 bigserial primary key,
  raw_string         text not null,
  proposed_slug      text not null,
  proposed_parent_id bigint references taxonomy_nodes(id),
  candidates         jsonb not null,    -- [{node_id, display_name, similarity}]
  mapper_version     text not null,
  status             text not null default 'pending'
                     check (status in ('pending', 'approved', 'rejected')),
  decided_by         text,
  decided_at         timestamptz,
  created_at         timestamptz not null default now(),
  unique (raw_string, mapper_version)
);

create index taxonomy_proposals_status_idx
  on taxonomy_proposals (status, created_at);

alter table taxonomy_proposals enable row level security;
```

- [ ] **Step 2: Apply and confirm**

```bash
supabase db reset --db-url "postgresql://postgres:postgres@192.168.65.254:54322/postgres" --yes
```

```bash
uv run --project ingredients python -c "
import os, psycopg
from dotenv import load_dotenv; load_dotenv('/workspaces/spiritolo/.env')
with psycopg.connect(os.environ['SUPABASE_DB_URL']) as c:
    print(c.execute(\"select to_regclass('public.taxonomy_proposals')\").fetchone())"
```

Expected: `('taxonomy_proposals',)`.

- [ ] **Step 3: Commit**

```bash
git add supabase/migrations/20260429140200_create_taxonomy_proposals.sql
git commit -m "add taxonomy_proposals review queue table"
```

---

## Phase B — Test fixtures

### Task 4: Fixture taxonomy module

A minimal hand-built taxonomy that exercises every cascade path. Lives **inside the package** (not under `tests/`) so both pytest and the `map --review` CLI can import it without sys.path gymnastics.

**Files:**
- Create: `ingredients/src/ingredients/mapping/eval_fixture.py`

- [ ] **Step 1: Write the fixture loader**

```python
# ingredients/src/ingredients/mapping/eval_fixture.py
"""A minimal taxonomy that exercises every Phase 1/Phase 2 path in tests.

Layout (relevant for cascade coverage):

    citrus
      └── lemon
            ├── lemon_juice    [alias: 'lemon juice']
            └── lemon_wheel
    gin                        [alias: 'gin', 'london dry gin']
      └── london_dry_gin
            └── tanqueray      (role=brand, alias: 'tanqueray', 'tanqueray gin')
    bourbon                    [alias: 'bourbon']

Tests assert mapper outcomes against this fixture rather than the
production seed, so eval results don't drift as the seed grows.
"""

from __future__ import annotations

import psycopg


def seed(conn: psycopg.Connection) -> dict[str, int]:
    """Wipe taxonomy_* tables and load the fixture. Returns slug -> id."""
    conn.execute("truncate table taxonomy_aliases, taxonomy_edges, taxonomy_nodes restart identity cascade")

    nodes = [
        ("citrus",          "Citrus",          None),
        ("lemon",           "Lemon",           None),
        ("lemon_juice",     "Lemon Juice",     None),
        ("lemon_wheel",     "Lemon Wheel",     None),
        ("gin",             "Gin",             None),
        ("london_dry_gin",  "London Dry Gin",  None),
        ("tanqueray",       "Tanqueray",       "brand"),
        ("bourbon",         "Bourbon",         None),
    ]
    ids: dict[str, int] = {}
    for slug, name, role in nodes:
        row = conn.execute(
            "insert into taxonomy_nodes (slug, display_name, role) "
            "values (%s, %s, %s) returning id",
            (slug, name, role),
        ).fetchone()
        ids[slug] = row[0]

    edges = [
        ("citrus",         "lemon"),
        ("lemon",          "lemon_juice"),
        ("lemon",          "lemon_wheel"),
        ("gin",            "london_dry_gin"),
        ("london_dry_gin", "tanqueray"),
    ]
    for parent, child in edges:
        conn.execute(
            "insert into taxonomy_edges (parent_id, child_id) values (%s, %s)",
            (ids[parent], ids[child]),
        )

    aliases = [
        ("lemon juice",      "lemon_juice"),
        ("gin",              "gin"),
        ("london dry gin",   "london_dry_gin"),
        ("tanqueray",        "tanqueray"),
        ("tanqueray gin",    "tanqueray"),
        ("bourbon",          "bourbon"),
    ]
    for alias, slug in aliases:
        conn.execute(
            "insert into taxonomy_aliases (alias, node_id) values (%s, %s)",
            (alias, ids[slug]),
        )

    conn.commit()
    return ids
```

- [ ] **Step 2: Smoke test the fixture against the test DB**

Run a one-off script (no test file yet — Task 6 is the first DB-using test):

```bash
cd ingredients && uv run python -c "
import psycopg, os
from dotenv import load_dotenv; load_dotenv('/workspaces/spiritolo/.env')
from ingredients.mapping.eval_fixture import seed
url = os.environ.get('TEST_DB_URL')
assert url, 'set TEST_DB_URL'
with psycopg.connect(url) as c:
    ids = seed(c)
    print(sorted(ids))
    print(c.execute('select count(*) from taxonomy_aliases').fetchone())
"
```

Expected: prints `['bourbon', 'citrus', 'gin', 'lemon', 'lemon_juice', 'lemon_wheel', 'london_dry_gin', 'tanqueray']` then `(6,)`.

- [ ] **Step 3: Commit**

```bash
git add ingredients/src/ingredients/mapping/eval_fixture.py
git commit -m "add fixture taxonomy for mapper tests + eval"
```

---

## Phase C — Phase 1 building blocks

### Task 5: Normalize + typed result classes

**Files:**
- Create: `ingredients/src/ingredients/mapping/__init__.py`
- Create: `ingredients/src/ingredients/mapping/types.py`
- Create: `ingredients/src/ingredients/mapping/normalize.py`
- Create: `ingredients/tests/test_mapping_normalize.py`

- [ ] **Step 1: Create mapping package init**

```python
# ingredients/src/ingredients/mapping/__init__.py
"""Phase 1 + Phase 2 mapper for recipe_ingredients.name -> taxonomy_nodes.id."""
```

- [ ] **Step 2: Write the failing normalize test**

```python
# ingredients/tests/test_mapping_normalize.py
from ingredients.mapping.normalize import normalize_name


def test_lowercases_and_trims():
    assert normalize_name("  Lemon Juice  ") == "lemon juice"


def test_collapses_internal_whitespace():
    assert normalize_name("simple   syrup") == "simple syrup"


def test_returns_empty_string_for_none():
    assert normalize_name(None) == ""


def test_does_not_strip_punctuation_or_diacritics():
    # Form-node decisions depend on punctuation (e.g. "lemon, juiced").
    # Diacritics distinguish jalapeño from jalapeno in alias seed.
    assert normalize_name("Jalapeño Tincture") == "jalapeño tincture"
    assert normalize_name("Lemon, juiced") == "lemon, juiced"
```

```bash
cd ingredients && uv run pytest tests/test_mapping_normalize.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'ingredients.mapping.normalize'`.

- [ ] **Step 3: Write `normalize.py`**

```python
# ingredients/src/ingredients/mapping/normalize.py
"""Canonical normalization for ingredient name lookups.

Kept narrow on purpose: lowercase + whitespace cleanup. Punctuation and
diacritics are preserved because form-node distinctions ('lemon, juiced')
and alias seeds for accented strings depend on them.
"""

from __future__ import annotations

import re

_WS = re.compile(r"\s+")


def normalize_name(raw: str | None) -> str:
    if raw is None:
        return ""
    return _WS.sub(" ", raw.strip().lower())
```

- [ ] **Step 4: Write the typed result module**

```python
# ingredients/src/ingredients/mapping/types.py
"""Typed cascade results. Layer modules return one of these; the
orchestrator records the chosen variant on each recipe_ingredients row.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Source values match the recipe_ingredients.mapper_source check constraint.
MapperSource = Literal["alias", "lexical", "pending_llm", "llm", "abstain"]


@dataclass(frozen=True)
class Resolved:
    """The string mapped to a node."""
    taxonomy_node_id: int
    source: MapperSource          # 'alias' | 'lexical' | 'llm'


@dataclass(frozen=True)
class Pending:
    """Phase 1 didn't resolve; row will be picked up by Phase 2."""


@dataclass(frozen=True)
class Abstain:
    """Phase 2 considered the string and declined; no node assigned."""


@dataclass(frozen=True)
class BrandProposal:
    """LLM proposed a new brand/expression node with an existing parent."""
    proposed_slug: str
    proposed_display_name: str
    parent_node_id: int
    role: Literal["brand", "expression"]


@dataclass(frozen=True)
class FormProposal:
    """LLM proposed a new form node; goes to taxonomy_proposals queue."""
    proposed_slug: str
    proposed_display_name: str
    parent_node_id: int
    candidates: list[dict]        # [{node_id, display_name, similarity}]


# Phase 1 layer return type.
Phase1Result = Resolved | Pending

# Phase 2 LLM-call return type.
Phase2Result = Resolved | BrandProposal | FormProposal | Abstain
```

- [ ] **Step 5: Run tests and verify pass**

```bash
cd ingredients && uv run pytest tests/test_mapping_normalize.py -q
```

Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add ingredients/src/ingredients/mapping/__init__.py \
        ingredients/src/ingredients/mapping/types.py \
        ingredients/src/ingredients/mapping/normalize.py \
        ingredients/tests/test_mapping_normalize.py
git commit -m "add mapping package skeleton: normalize + typed results"
```

---

### Task 6: `alias_layer.py` — Phase 1, Layer 1

**Files:**
- Create: `ingredients/src/ingredients/mapping/alias_layer.py`
- Create: `ingredients/tests/test_mapping_alias_layer.py`

- [ ] **Step 1: Add a conftest fixture for fixture-seeded DB**

Append to `ingredients/tests/conftest.py`:

```python
@pytest.fixture
def fixture_taxonomy(test_db_url: str):
    """Yield (psycopg conn, slug->id dict) with taxonomy_* truncated and
    seeded from ingredients.mapping.eval_fixture. Truncates on teardown."""
    from ingredients.mapping.eval_fixture import seed

    conn = psycopg.connect(test_db_url)
    ids = seed(conn)
    yield conn, ids
    conn.execute("truncate table taxonomy_aliases, taxonomy_edges, taxonomy_nodes restart identity cascade")
    conn.commit()
    conn.close()
```

- [ ] **Step 2: Write the failing alias-layer test**

```python
# ingredients/tests/test_mapping_alias_layer.py
import pytest

from ingredients.mapping.alias_layer import resolve_alias
from ingredients.mapping.types import Resolved, Pending


@pytest.mark.usefixtures("fixture_taxonomy")
def test_exact_alias_hit_returns_resolved(fixture_taxonomy):
    conn, ids = fixture_taxonomy
    result = resolve_alias(conn, "lemon juice")
    assert isinstance(result, Resolved)
    assert result.taxonomy_node_id == ids["lemon_juice"]
    assert result.source == "alias"


def test_unknown_string_returns_pending(fixture_taxonomy):
    conn, _ = fixture_taxonomy
    result = resolve_alias(conn, "fancy unknown thing")
    assert isinstance(result, Pending)


def test_alias_with_extra_whitespace_does_not_match(fixture_taxonomy):
    # The orchestrator normalizes before calling; alias_layer expects
    # already-normalized input. Confirming the contract.
    conn, _ = fixture_taxonomy
    result = resolve_alias(conn, "  lemon juice  ")
    assert isinstance(result, Pending)
```

```bash
cd ingredients && uv run pytest tests/test_mapping_alias_layer.py -q
```

Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `alias_layer.py`**

```python
# ingredients/src/ingredients/mapping/alias_layer.py
"""Phase 1, Layer 1 — exact match against taxonomy_aliases.

Caller is expected to pass a normalized name (see normalize.normalize_name).
Returns Resolved(source='alias') or Pending. Never raises on miss.
"""

from __future__ import annotations

import psycopg

from .types import Pending, Phase1Result, Resolved


def resolve_alias(conn: psycopg.Connection, normalized_name: str) -> Phase1Result:
    if not normalized_name:
        return Pending()
    row = conn.execute(
        "select node_id from taxonomy_aliases where alias = %s limit 1",
        (normalized_name,),
    ).fetchone()
    if row is None:
        return Pending()
    return Resolved(taxonomy_node_id=row[0], source="alias")
```

- [ ] **Step 4: Run tests**

```bash
cd ingredients && uv run pytest tests/test_mapping_alias_layer.py -q
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add ingredients/src/ingredients/mapping/alias_layer.py \
        ingredients/tests/test_mapping_alias_layer.py \
        ingredients/tests/conftest.py
git commit -m "add Phase 1 alias layer + fixture_taxonomy fixture"
```

---

### Task 7: `lexical_layer.py` — Phase 1, Layer 2 (pg_trgm)

**Files:**
- Create: `ingredients/src/ingredients/mapping/lexical_layer.py`
- Create: `ingredients/tests/test_mapping_lexical_layer.py`

- [ ] **Step 1: Write the failing lexical-layer test**

```python
# ingredients/tests/test_mapping_lexical_layer.py
import pytest

from ingredients.mapping.lexical_layer import (
    LEXICAL_MIN_SIM, LEXICAL_RATIO, lexical_candidates, resolve_lexical,
)
from ingredients.mapping.types import Pending, Resolved


def test_resolves_high_confidence_typo(fixture_taxonomy):
    conn, ids = fixture_taxonomy
    # "lemon juicee" is a typo; trigram similarity to "lemon juice" is
    # very high, the next-best match much lower.
    result = resolve_lexical(conn, "lemon juicee")
    assert isinstance(result, Resolved)
    assert result.taxonomy_node_id == ids["lemon_juice"]
    assert result.source == "lexical"


def test_pending_when_top1_too_close_to_top2(fixture_taxonomy):
    conn, _ = fixture_taxonomy
    # "gin" matches both 'gin' and 'london dry gin' with high similarity;
    # the ratio guard should reject the ambiguous case in favor of LLM.
    # NOTE: 'gin' is also an alias hit in the fixture, but resolve_lexical
    # is called only after the alias layer misses, so we test it directly
    # with a string that has multiple lexical neighbors.
    result = resolve_lexical(conn, "dry gin")
    assert isinstance(result, Pending)


def test_pending_when_below_min_sim(fixture_taxonomy):
    conn, _ = fixture_taxonomy
    result = resolve_lexical(conn, "totally unrelated phrase")
    assert isinstance(result, Pending)


def test_lexical_candidates_returns_top_n_with_scores(fixture_taxonomy):
    conn, _ = fixture_taxonomy
    cands = lexical_candidates(conn, "tanqueray", limit=5)
    assert len(cands) >= 1
    assert cands[0]["display_name"] == "Tanqueray"
    assert cands[0]["similarity"] >= LEXICAL_MIN_SIM
    assert "node_id" in cands[0]


def test_thresholds_are_tunable_constants():
    # Sanity guard: values should match the spec's "fail closed" stance.
    assert LEXICAL_MIN_SIM == 0.92
    assert LEXICAL_RATIO == 1.5
```

```bash
cd ingredients && uv run pytest tests/test_mapping_lexical_layer.py -q
```

Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 2: Implement `lexical_layer.py`**

```python
# ingredients/src/ingredients/mapping/lexical_layer.py
"""Phase 1, Layer 2 — pg_trgm similarity over taxonomy display names + aliases.

Fail-closed thresholds: accept only when top-1 similarity clears
LEXICAL_MIN_SIM AND is at least LEXICAL_RATIO times top-2. Anything
ambiguous falls through to Pending so Phase 2 can decide.
"""

from __future__ import annotations

from typing import Any

import psycopg

from .types import Pending, Phase1Result, Resolved

LEXICAL_MIN_SIM = 0.92
LEXICAL_RATIO = 1.5

# Top-N candidates surfaced to Phase 2 even when this layer abstains.
_CANDIDATE_LIMIT_DEFAULT = 20


def _candidates_sql(limit: int) -> str:
    return f"""
        with hits as (
            select n.id as node_id, n.display_name as text, similarity(n.display_name, %s) as sim
            from taxonomy_nodes n
            union all
            select a.node_id, a.alias as text, similarity(a.alias, %s) as sim
            from taxonomy_aliases a
        )
        select node_id, text, max(sim) as sim
        from hits
        group by node_id, text
        order by sim desc
        limit {int(limit)}
    """


def lexical_candidates(
    conn: psycopg.Connection, normalized_name: str, *, limit: int = _CANDIDATE_LIMIT_DEFAULT,
) -> list[dict[str, Any]]:
    if not normalized_name:
        return []
    rows = conn.execute(
        _candidates_sql(limit), (normalized_name, normalized_name),
    ).fetchall()
    return [
        {"node_id": r[0], "display_name": r[1], "similarity": float(r[2])}
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
    return Resolved(taxonomy_node_id=cands[0]["node_id"], source="lexical")
```

- [ ] **Step 3: Run tests**

```bash
cd ingredients && uv run pytest tests/test_mapping_lexical_layer.py -q
```

Expected: 5 passed.

- [ ] **Step 4: Commit**

```bash
git add ingredients/src/ingredients/mapping/lexical_layer.py \
        ingredients/tests/test_mapping_lexical_layer.py
git commit -m "add Phase 1 lexical layer with fail-closed pg_trgm thresholds"
```

---

## Phase D — Phase 1 orchestration

### Task 8: `db.py` — mapper data-access layer

**Files:**
- Create: `ingredients/src/ingredients/mapping/db.py`
- Create: `ingredients/tests/test_mapping_db.py`

- [ ] **Step 1: Write the failing DB-access test**

```python
# ingredients/tests/test_mapping_db.py
import psycopg
import pytest

from ingredients.mapping.db import (
    fetch_unique_pending_names, write_resolution, write_pending,
)


def _seed_recipes_and_ingredients(conn: psycopg.Connection) -> dict[str, int]:
    """Two recipes, with overlapping ingredient names so we can verify
    the unique-names query collapses duplicates and the batch UPDATE
    flips every row sharing a name."""
    conn.execute("truncate table recipe_ingredients, recipes restart identity cascade")
    rid1 = conn.execute(
        "insert into recipes (site, source_url, jsonld) values ('punch', 'https://example.com/a', '{}'::jsonb) returning id"
    ).fetchone()[0]
    rid2 = conn.execute(
        "insert into recipes (site, source_url, jsonld) values ('punch', 'https://example.com/b', '{}'::jsonb) returning id"
    ).fetchone()[0]
    rows = [
        (rid1, 0, "2 oz gin",          "gin",          "parsed", "qty_unit"),
        (rid1, 1, "1 oz lemon juice",  "lemon juice",  "parsed", "qty_unit"),
        (rid2, 0, "2 oz gin",          "gin",          "parsed", "qty_unit"),
        (rid2, 1, "0.5 oz simple syrup", "simple syrup", "parsed", "qty_unit"),
    ]
    for r in rows:
        conn.execute(
            "insert into recipe_ingredients "
            "(recipe_id, position, raw_text, name, parse_status, parser_rule, parser_version) "
            "values (%s,%s,%s,%s,%s,%s,'v1')",
            r,
        )
    conn.commit()
    return {"recipe1": rid1, "recipe2": rid2}


def test_fetch_unique_pending_names_collapses_duplicates(fixture_taxonomy):
    conn, _ = fixture_taxonomy
    _seed_recipes_and_ingredients(conn)
    names = fetch_unique_pending_names(conn, mapper_version="v1")
    # 'gin' appears in both recipes but should be deduped.
    assert sorted(names) == ["gin", "lemon juice", "simple syrup"]


def test_write_resolution_updates_every_row_sharing_name(fixture_taxonomy):
    conn, ids = fixture_taxonomy
    _seed_recipes_and_ingredients(conn)
    write_resolution(
        conn, normalized_name="gin", taxonomy_node_id=ids["gin"],
        source="alias", mapper_version="v1",
    )
    rows = conn.execute(
        "select taxonomy_node_id, mapper_source, mapper_version "
        "from recipe_ingredients where lower(trim(name)) = 'gin' order by id"
    ).fetchall()
    assert len(rows) == 2
    for r in rows:
        assert r == (ids["gin"], "alias", "v1")


def test_write_pending_marks_rows_pending_llm(fixture_taxonomy):
    conn, _ = fixture_taxonomy
    _seed_recipes_and_ingredients(conn)
    write_pending(conn, normalized_name="simple syrup", mapper_version="v1")
    row = conn.execute(
        "select taxonomy_node_id, mapper_source, mapper_version "
        "from recipe_ingredients where lower(trim(name)) = 'simple syrup'"
    ).fetchone()
    assert row == (None, "pending_llm", "v1")


def test_fetch_skips_already_mapped_at_current_version(fixture_taxonomy):
    conn, ids = fixture_taxonomy
    _seed_recipes_and_ingredients(conn)
    write_resolution(
        conn, normalized_name="gin", taxonomy_node_id=ids["gin"],
        source="alias", mapper_version="v1",
    )
    names = fetch_unique_pending_names(conn, mapper_version="v1")
    assert "gin" not in names
    assert sorted(names) == ["lemon juice", "simple syrup"]
```

```bash
cd ingredients && uv run pytest tests/test_mapping_db.py -q
```

Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 2: Implement `mapping/db.py`**

```python
# ingredients/src/ingredients/mapping/db.py
"""DB access for the mapper. Caller passes a psycopg connection so the
fixture-DB tests and the production worker share the same code paths.

A name is "in scope" if it has at least one recipe_ingredients row whose
mapper_version is NULL or differs from the current MAPPER_VERSION.
Updates fan out to every row sharing the normalized name string.
"""

from __future__ import annotations

import psycopg

from .types import MapperSource


def fetch_unique_pending_names(
    conn: psycopg.Connection, *, mapper_version: str,
    site: str | None = None, limit: int | None = None,
) -> list[str]:
    """Distinct normalized names lacking a current-version mapping."""
    params: list[object] = [mapper_version]
    site_clause = ""
    if site is not None:
        site_clause = "and r.site = %s"
        params.append(site)

    sql = f"""
        select distinct lower(trim(ri.name)) as n
        from recipe_ingredients ri
        join recipes r on r.id = ri.recipe_id
        where ri.name is not null
          and ri.parse_status = 'parsed'
          and (ri.mapper_version is null or ri.mapper_version <> %s)
          {site_clause}
        order by n
    """
    if limit is not None:
        sql += " limit %s"
        params.append(limit)
    return [row[0] for row in conn.execute(sql, params).fetchall()]


def write_resolution(
    conn: psycopg.Connection, *, normalized_name: str,
    taxonomy_node_id: int, source: MapperSource, mapper_version: str,
) -> int:
    """UPDATE every row whose normalized name matches. Returns rowcount."""
    cur = conn.execute(
        """
        update recipe_ingredients
           set taxonomy_node_id = %s,
               mapper_source    = %s,
               mapper_version   = %s,
               mapper_at        = now()
         where lower(trim(name)) = %s
        """,
        (taxonomy_node_id, source, mapper_version, normalized_name),
    )
    conn.commit()
    return cur.rowcount


def write_pending(
    conn: psycopg.Connection, *, normalized_name: str, mapper_version: str,
) -> int:
    """Mark every row whose normalized name matches as pending_llm. Returns rowcount."""
    cur = conn.execute(
        """
        update recipe_ingredients
           set taxonomy_node_id = null,
               mapper_source    = 'pending_llm',
               mapper_version   = %s,
               mapper_at        = now()
         where lower(trim(name)) = %s
        """,
        (mapper_version, normalized_name),
    )
    conn.commit()
    return cur.rowcount


def write_abstain(
    conn: psycopg.Connection, *, normalized_name: str, mapper_version: str,
) -> int:
    """Mark rows as abstained (Phase 2 considered and declined)."""
    cur = conn.execute(
        """
        update recipe_ingredients
           set taxonomy_node_id = null,
               mapper_source    = 'abstain',
               mapper_version   = %s,
               mapper_at        = now()
         where lower(trim(name)) = %s
        """,
        (mapper_version, normalized_name),
    )
    conn.commit()
    return cur.rowcount


def fetch_pending_llm_names(
    conn: psycopg.Connection, *, mapper_version: str, limit: int | None = None,
) -> list[str]:
    """Distinct names currently marked pending_llm at this version."""
    sql = """
        select distinct lower(trim(name)) as n
        from recipe_ingredients
        where mapper_source = 'pending_llm' and mapper_version = %s
        order by n
    """
    params: list[object] = [mapper_version]
    if limit is not None:
        sql += " limit %s"
        params.append(limit)
    return [row[0] for row in conn.execute(sql, params).fetchall()]
```

- [ ] **Step 3: Run tests**

```bash
cd ingredients && uv run pytest tests/test_mapping_db.py -q
```

Expected: 4 passed.

- [ ] **Step 4: Commit**

```bash
git add ingredients/src/ingredients/mapping/db.py \
        ingredients/tests/test_mapping_db.py
git commit -m "add mapping db layer for fetch + batched updates"
```

---

### Task 9: `mapper.py` — Phase 1 orchestrator + `MAPPER_VERSION`

**Files:**
- Create: `ingredients/src/ingredients/mapping/mapper.py`
- Create: `ingredients/tests/test_mapping_mapper.py`

- [ ] **Step 1: Write the failing mapper test**

```python
# ingredients/tests/test_mapping_mapper.py
import psycopg

from ingredients.mapping.mapper import MAPPER_VERSION, run_phase1


def _seed_two_recipes(conn: psycopg.Connection) -> None:
    conn.execute("truncate table recipe_ingredients, recipes restart identity cascade")
    rid = conn.execute(
        "insert into recipes (site, source_url, jsonld) values ('punch', 'https://example.com/a', '{}'::jsonb) returning id"
    ).fetchone()[0]
    rows = [
        (rid, 0, "2 oz gin",          "gin"),                 # alias hit
        (rid, 1, "1 oz lemon juicee", "lemon juicee"),        # lexical hit (typo)
        (rid, 2, "0.5 oz weird thing", "totally weird thing"),# pending_llm
    ]
    for pos, raw, name in [(p, r, n) for (_, p, r, n) in rows]:
        conn.execute(
            "insert into recipe_ingredients "
            "(recipe_id, position, raw_text, name, parse_status, parser_rule, parser_version) "
            "values (%s,%s,%s,%s,'parsed','qty_unit','v1')",
            (rid, pos, raw, name),
        )
    conn.commit()


def test_phase1_resolves_alias_lexical_and_marks_pending(fixture_taxonomy):
    conn, ids = fixture_taxonomy
    _seed_two_recipes(conn)
    summary = run_phase1(conn)
    rows = conn.execute(
        "select lower(trim(name)), taxonomy_node_id, mapper_source, mapper_version "
        "from recipe_ingredients order by position"
    ).fetchall()
    assert rows == [
        ("gin",                  ids["gin"],         "alias",       MAPPER_VERSION),
        ("lemon juicee",         ids["lemon_juice"], "lexical",     MAPPER_VERSION),
        ("totally weird thing",  None,               "pending_llm", MAPPER_VERSION),
    ]
    assert summary == {"alias": 1, "lexical": 1, "pending_llm": 1}


def test_phase1_is_idempotent(fixture_taxonomy):
    conn, _ = fixture_taxonomy
    _seed_two_recipes(conn)
    run_phase1(conn)
    second = run_phase1(conn)
    # Already at current version; nothing in scope.
    assert second == {"alias": 0, "lexical": 0, "pending_llm": 0}
```

```bash
cd ingredients && uv run pytest tests/test_mapping_mapper.py -q
```

Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 2: Implement `mapper.py`**

```python
# ingredients/src/ingredients/mapping/mapper.py
"""Phase 1 orchestrator. Walks the unique-pending-names list through
alias -> lexical, batch-updating recipe_ingredients per name.

Phase 2 (LLM) lives in llm_resolver.py and is triggered separately by
the operator; nothing in this module makes external calls.
"""

from __future__ import annotations

from collections import Counter

import psycopg

from .alias_layer import resolve_alias
from .db import (
    fetch_unique_pending_names, write_pending, write_resolution,
)
from .lexical_layer import resolve_lexical
from .normalize import normalize_name
from .types import Resolved

MAPPER_VERSION = "v1"


def run_phase1(
    conn: psycopg.Connection,
    *,
    site: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Resolve every distinct pending name through alias -> lexical.
    Returns a Counter-shaped summary keyed by mapper_source."""
    counts: Counter[str] = Counter()
    names = fetch_unique_pending_names(
        conn, mapper_version=MAPPER_VERSION, site=site, limit=limit,
    )
    for raw in names:
        normalized = normalize_name(raw)
        result = resolve_alias(conn, normalized)
        if isinstance(result, Resolved):
            counts["alias"] += 1
            if not dry_run:
                write_resolution(
                    conn, normalized_name=normalized,
                    taxonomy_node_id=result.taxonomy_node_id,
                    source="alias", mapper_version=MAPPER_VERSION,
                )
            continue

        result = resolve_lexical(conn, normalized)
        if isinstance(result, Resolved):
            counts["lexical"] += 1
            if not dry_run:
                write_resolution(
                    conn, normalized_name=normalized,
                    taxonomy_node_id=result.taxonomy_node_id,
                    source="lexical", mapper_version=MAPPER_VERSION,
                )
            continue

        counts["pending_llm"] += 1
        if not dry_run:
            write_pending(
                conn, normalized_name=normalized, mapper_version=MAPPER_VERSION,
            )
    return dict(counts)
```

- [ ] **Step 3: Run tests**

```bash
cd ingredients && uv run pytest tests/test_mapping_mapper.py -q
```

Expected: 2 passed.

- [ ] **Step 4: Commit**

```bash
git add ingredients/src/ingredients/mapping/mapper.py \
        ingredients/tests/test_mapping_mapper.py
git commit -m "add Phase 1 orchestrator + MAPPER_VERSION constant"
```

---

## Phase E — CLI integration for Phase 1

### Task 10: Extend `cli.py` with `map` subcommand (Phase 1)

**Files:**
- Modify: `ingredients/src/ingredients/cli.py`
- Create: `ingredients/tests/test_mapping_cli.py`

- [ ] **Step 1: Refactor existing CLI to use subparsers**

Read `ingredients/src/ingredients/cli.py`. The current file has a single argparse parser for the `parse_ingredients` worker. Replace `build_arg_parser()` with subcommand-aware structure that keeps the parse worker as the **default** subcommand for backward compatibility.

Replace `build_arg_parser()` with:

```python
def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="parse_ingredients",
        description="Spiritolo ingredient parser + taxonomy mapper.",
    )
    sub = parser.add_subparsers(dest="cmd")

    # Parse subcommand (default — preserves backward-compatible CLI).
    p_parse = sub.add_parser("parse", help="Parser worker (default).")
    _add_parse_args(p_parse)

    # Map subcommand: Phase 1 (alias + lexical).
    p_map = sub.add_parser("map", help="Taxonomy mapper. Phase 1 by default.")
    _add_map_args(p_map)
    map_sub = p_map.add_subparsers(dest="map_cmd")
    # Phase 2 + review subcommands attach to map_sub in Tasks 16/17.

    return parser


def _add_parse_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--review", action="store_true",
                   help="Run the parser eval set; do not touch the database.")
    p.add_argument("--site", default=None,
                   help="Restrict processing to one source site (e.g. 'punch').")
    p.add_argument("--limit", type=int, default=None,
                   help="Process at most N recipes.")
    p.add_argument("--dry-run", action="store_true",
                   help="Parse and report counts; do not write to the database.")
    add_reset_args(p, stage="recipe_ingredients")


def _add_map_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--review", action="store_true",
                   help="Run the mapper eval set; do not touch the database.")
    p.add_argument("--site", default=None,
                   help="Restrict to one source site.")
    p.add_argument("--limit", type=int, default=None,
                   help="Process at most N distinct names.")
    p.add_argument("--dry-run", action="store_true",
                   help="Compute resolutions; do not write to the database.")
    p.add_argument("--sample", type=int, default=None,
                   help="Spot-check N random pending names; print results, write nothing.")
    add_reset_args(p, stage="recipe_ingredients (mapping columns)")
```

Update `main()` to dispatch on `args.cmd`:

```python
def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = build_arg_parser()
    args = parser.parse_args()
    cmd = args.cmd or "parse"
    if cmd == "parse":
        if args.review:
            return run_review()
        return run_worker(args)
    if cmd == "map":
        return run_map(args)
    parser.error(f"unknown command {cmd!r}")
    return 2
```

Add `run_map` (Phase 1 only for this task; Phase 2 dispatch wired in Task 17):

```python
def run_map(args: argparse.Namespace) -> int:
    from ingredients.mapping.mapper import MAPPER_VERSION, run_phase1
    if args.review:
        log.error("--review for map not implemented yet (Task 21)")
        return 2
    if args.sample is not None:
        log.error("--sample for map not implemented yet (Task 20)")
        return 2
    db = IngredientsDatabase()
    try:
        if args.reset:
            log.error("map --reset not implemented yet (Task 20)")
            return 2
        summary = run_phase1(
            db.conn, site=args.site, limit=args.limit, dry_run=args.dry_run,
        )
        mode = "dry-run" if args.dry_run else "applied"
        changes = {"all": Counter(summary)}
        print_summary(f"Map ingredients (Phase 1, {MAPPER_VERSION})", changes, mode=mode)
        return 0
    finally:
        db.close()
```

- [ ] **Step 2: Write the failing CLI smoke test**

```python
# ingredients/tests/test_mapping_cli.py
import io
import os
import subprocess
import sys

import psycopg
import pytest


def _run_cli(args: list[str], env_overrides: dict[str, str]) -> subprocess.CompletedProcess:
    env = {**os.environ, **env_overrides}
    return subprocess.run(
        [sys.executable, "-m", "ingredients.cli", *args],
        env=env, capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(__file__)),
    )


def _seed_one(conn: psycopg.Connection) -> None:
    conn.execute("truncate table recipe_ingredients, recipes restart identity cascade")
    rid = conn.execute(
        "insert into recipes (site, source_url, jsonld) values ('punch', 'https://example.com/a', '{}'::jsonb) returning id"
    ).fetchone()[0]
    conn.execute(
        "insert into recipe_ingredients "
        "(recipe_id, position, raw_text, name, parse_status, parser_rule, parser_version) "
        "values (%s, 0, '2 oz gin', 'gin', 'parsed', 'qty_unit', 'v1')",
        (rid,),
    )
    conn.commit()


def test_cli_map_phase1_dry_run_reports_counts(fixture_taxonomy, test_db_url):
    conn, _ = fixture_taxonomy
    _seed_one(conn)
    # Force the CLI's IngredientsDatabase to point at the test DB.
    proc = _run_cli(["map", "--dry-run"], {"SUPABASE_DB_URL": test_db_url})
    assert proc.returncode == 0, proc.stderr
    assert "Map ingredients" in proc.stdout
    assert "alias" in proc.stdout
    # Dry-run wrote nothing.
    row = conn.execute(
        "select mapper_source from recipe_ingredients where lower(trim(name))='gin'"
    ).fetchone()
    assert row[0] is None


def test_cli_map_phase1_applied_writes_alias_resolution(fixture_taxonomy, test_db_url):
    conn, ids = fixture_taxonomy
    _seed_one(conn)
    proc = _run_cli(["map"], {"SUPABASE_DB_URL": test_db_url})
    assert proc.returncode == 0, proc.stderr
    row = conn.execute(
        "select taxonomy_node_id, mapper_source, mapper_version "
        "from recipe_ingredients where lower(trim(name))='gin'"
    ).fetchone()
    assert row == (ids["gin"], "alias", "v1")
```

```bash
cd ingredients && uv run pytest tests/test_mapping_cli.py -q
```

Expected: FAIL initially because the CLI changes haven't been made. After Step 1's edits, expected: 2 passed.

- [ ] **Step 3: Verify the existing parser CLI still works**

Backward-compat smoke check:

```bash
cd ingredients && uv run python -m ingredients.cli --help 2>&1 | head -5
cd ingredients && uv run python -m ingredients.cli parse --help 2>&1 | head -5
cd ingredients && uv run pytest tests/test_cli_main.py tests/test_cli_review.py -q
```

Expected: top-level help shows `parse` and `map` subcommands; existing parser CLI tests still pass.

- [ ] **Step 4: Commit**

```bash
git add ingredients/src/ingredients/cli.py ingredients/tests/test_mapping_cli.py
git commit -m "wire up map subcommand for Phase 1"
```

---

## Phase F — Phase 2 plumbing

### Task 11: Add `anthropic` and `httpx` to `ingredients/pyproject.toml`

**Files:**
- Modify: `ingredients/pyproject.toml`

- [ ] **Step 1: Add deps**

Edit `ingredients/pyproject.toml`. The `dependencies` list currently contains `spiritolo-common`, `psycopg[binary]`, `python-dotenv`. Add the two new entries:

```toml
dependencies = [
    "spiritolo-common",
    "psycopg[binary]>=3.2",
    "python-dotenv>=1.0",
    "anthropic>=0.40",
    "httpx>=0.27",
]
```

- [ ] **Step 2: Sync the workspace**

```bash
cd ingredients && uv sync
```

Expected: success, lockfile updated, both packages installed.

- [ ] **Step 3: Sanity-import**

```bash
cd ingredients && uv run python -c "import anthropic, httpx; print(anthropic.__version__, httpx.__version__)"
```

Expected: prints two version strings.

- [ ] **Step 4: Commit**

```bash
git add ingredients/pyproject.toml /workspaces/spiritolo/uv.lock
git commit -m "add anthropic + httpx deps for Phase 2 LLM providers"
```

---

### Task 12: `prompt.py` — provider-agnostic prompt building

**Files:**
- Create: `ingredients/src/ingredients/mapping/prompt.py`
- Create: `ingredients/tests/test_mapping_prompt.py`

- [ ] **Step 1: Write the failing prompt test**

```python
# ingredients/tests/test_mapping_prompt.py
from ingredients.mapping.prompt import (
    SYSTEM_PROMPT, build_user_prompt, parse_response, prompt_hash,
)


def test_user_prompt_includes_name_unit_and_candidates():
    candidates = [
        {"node_id": 1, "display_name": "Lemon",       "similarity": 0.91, "parents": ["citrus"]},
        {"node_id": 2, "display_name": "Lemon Juice", "similarity": 0.88, "parents": ["lemon"]},
    ]
    prompt = build_user_prompt(
        normalized_name="lemon",
        parser_unit="oz",
        site="punch",
        candidates=candidates,
    )
    assert "lemon" in prompt
    assert "oz" in prompt
    assert "punch" in prompt
    assert "Lemon Juice" in prompt
    assert '"node_id": 1' in prompt or '"node_id":1' in prompt or "node_id=1" in prompt


def test_parse_response_chosen_node():
    raw = '{"action": "chose", "node_id": 17}'
    out = parse_response(raw)
    assert out == {"action": "chose", "node_id": 17}


def test_parse_response_brand_proposal():
    raw = (
        '{"action": "propose_brand", "slug": "tanqueray", '
        '"display_name": "Tanqueray", "parent_slug": "london_dry_gin", '
        '"role": "brand"}'
    )
    out = parse_response(raw)
    assert out["action"] == "propose_brand"
    assert out["slug"] == "tanqueray"
    assert out["role"] == "brand"


def test_parse_response_form_proposal():
    raw = (
        '{"action": "propose_form", "slug": "lemon_zest", '
        '"display_name": "Lemon Zest", "parent_slug": "lemon"}'
    )
    out = parse_response(raw)
    assert out["action"] == "propose_form"
    assert out["slug"] == "lemon_zest"


def test_parse_response_abstain():
    assert parse_response('{"action": "abstain"}') == {"action": "abstain"}


def test_parse_response_rejects_unknown_action():
    import pytest
    with pytest.raises(ValueError):
        parse_response('{"action": "explode"}')


def test_parse_response_handles_code_fence_wrapping():
    raw = '```json\n{"action": "chose", "node_id": 5}\n```'
    assert parse_response(raw) == {"action": "chose", "node_id": 5}


def test_prompt_hash_is_stable_for_identical_inputs():
    h1 = prompt_hash("lemon", "oz", "punch", [{"node_id": 1, "display_name": "L"}])
    h2 = prompt_hash("lemon", "oz", "punch", [{"node_id": 1, "display_name": "L"}])
    assert h1 == h2
    h3 = prompt_hash("lime", "oz", "punch", [{"node_id": 1, "display_name": "L"}])
    assert h1 != h3
```

```bash
cd ingredients && uv run pytest tests/test_mapping_prompt.py -q
```

Expected: FAIL — module missing.

- [ ] **Step 2: Implement `prompt.py`**

```python
# ingredients/src/ingredients/mapping/prompt.py
"""Provider-agnostic prompt building and response parsing.

Both providers (claude, ollama) speak the same JSON-out contract so the
provider modules stay thin. The system prompt names the legal actions
and the JSON shapes; the user prompt assembles per-string context.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

SYSTEM_PROMPT = """\
You map free-text cocktail-recipe ingredient strings to canonical taxonomy nodes.

You receive:
- A normalized ingredient string (e.g. "tanqueray gin", "lemon juice", "Buffalo Trace bourbon").
- The unit the recipe used (oz, ml, dash, none, ...). Helpful for distinguishing fruit-as-juice from fruit-as-garnish.
- Optionally a source site name.
- A list of plausible candidate nodes already in the taxonomy, with their immediate parent names and a similarity score.

You choose ONE of four actions and reply with a single JSON object, no commentary:

1. CHOOSE an existing candidate node:
   {"action": "chose", "node_id": <int>}

2. PROPOSE a new brand or expression node when the string clearly names a real product whose parent category is already present in the candidates:
   {"action": "propose_brand", "slug": "<snake_case>", "display_name": "<Title Case>",
    "parent_slug": "<existing_parent_slug>", "role": "brand" | "expression"}

3. PROPOSE a new form node (e.g. "lemon zest", "lime oil") when the string names a substance form not already in the taxonomy:
   {"action": "propose_form", "slug": "<snake_case>", "display_name": "<Title Case>",
    "parent_slug": "<existing_parent_slug>"}

4. ABSTAIN when you genuinely cannot tell:
   {"action": "abstain"}

Rules:
- Never invent a parent_slug that isn't in the candidates' parents.
- Prefer "chose" over "propose_*" when a candidate clearly fits.
- Prefer "abstain" over guessing.
- Output JSON only. No prose, no markdown fences.
"""


def build_user_prompt(
    *,
    normalized_name: str,
    parser_unit: str | None,
    site: str | None,
    candidates: list[dict[str, Any]],
) -> str:
    cand_lines = [
        json.dumps({
            "node_id": c["node_id"],
            "display_name": c["display_name"],
            "similarity": round(float(c.get("similarity", 0.0)), 3),
            "parents": c.get("parents") or [],
        })
        for c in candidates
    ]
    context = json.dumps({
        "name": normalized_name,
        "parser_unit": parser_unit,
        "site": site,
    })
    return (
        "INPUT:\n" + context + "\n\n"
        "CANDIDATES (highest similarity first):\n"
        + ("\n".join(cand_lines) if cand_lines else "(none)")
    )


_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)
_VALID_ACTIONS = {"chose", "propose_brand", "propose_form", "abstain"}


def parse_response(raw: str) -> dict[str, Any]:
    """Parse the provider's response. Strips a single ```json fence wrap if present."""
    text = raw.strip()
    m = _FENCE_RE.match(text)
    if m:
        text = m.group(1).strip()
    obj = json.loads(text)
    action = obj.get("action")
    if action not in _VALID_ACTIONS:
        raise ValueError(f"unknown action {action!r}")
    return obj


def prompt_hash(
    normalized_name: str, parser_unit: str | None, site: str | None,
    candidates: list[dict[str, Any]],
) -> str:
    """Stable hash of the prompt inputs, written to taxonomy_provenance.prompt_hash."""
    payload = json.dumps(
        {"name": normalized_name, "unit": parser_unit, "site": site,
         "candidates": [(c["node_id"], c["display_name"]) for c in candidates]},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

- [ ] **Step 3: Run tests**

```bash
cd ingredients && uv run pytest tests/test_mapping_prompt.py -q
```

Expected: 8 passed.

- [ ] **Step 4: Commit**

```bash
git add ingredients/src/ingredients/mapping/prompt.py \
        ingredients/tests/test_mapping_prompt.py
git commit -m "add provider-agnostic prompt + response parser"
```

---

### Task 13: `llm_provider.py` — provider interface

**Files:**
- Create: `ingredients/src/ingredients/mapping/llm_provider.py`

- [ ] **Step 1: Write the interface**

```python
# ingredients/src/ingredients/mapping/llm_provider.py
"""Provider interface used by Phase 2.

Implementations: llm_provider_claude.py, llm_provider_ollama.py.

Tests inject StubProvider via the same Protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ProviderResult:
    """Raw provider output. Caller parses with prompt.parse_response."""
    raw_text: str
    model_id: str           # e.g. 'claude-haiku-4-5' or 'qwen3:14b'


class LLMProvider(Protocol):
    """Anything that can answer a single prompt with structured JSON text."""

    def resolve(
        self, *, system_prompt: str, user_prompt: str,
    ) -> ProviderResult: ...

    @property
    def model_id(self) -> str: ...
```

- [ ] **Step 2: Sanity-import**

```bash
cd ingredients && uv run python -c "from ingredients.mapping.llm_provider import LLMProvider, ProviderResult; print('ok')"
```

Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add ingredients/src/ingredients/mapping/llm_provider.py
git commit -m "add LLMProvider protocol and ProviderResult"
```

---

### Task 14: `llm_provider_claude.py` — Anthropic implementation

**Files:**
- Create: `ingredients/src/ingredients/mapping/llm_provider_claude.py`
- Create: `ingredients/tests/test_mapping_provider_claude.py`

- [ ] **Step 1: Write the failing provider test**

```python
# ingredients/tests/test_mapping_provider_claude.py
from unittest.mock import MagicMock

from ingredients.mapping.llm_provider_claude import ClaudeProvider


def _fake_anthropic_client(reply_text: str) -> MagicMock:
    client = MagicMock()
    fake_message = MagicMock()
    fake_message.content = [MagicMock(text=reply_text)]
    client.messages.create.return_value = fake_message
    return client


def test_resolve_returns_provider_result_with_model_id():
    client = _fake_anthropic_client('{"action": "chose", "node_id": 7}')
    p = ClaudeProvider(client=client, model_id="claude-haiku-4-5")
    out = p.resolve(system_prompt="sys", user_prompt="u")
    assert out.raw_text == '{"action": "chose", "node_id": 7}'
    assert out.model_id == "claude-haiku-4-5"
    client.messages.create.assert_called_once()
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-haiku-4-5"
    assert kwargs["system"] == "sys"
    assert kwargs["messages"][0]["content"] == "u"


def test_model_id_property_matches_constructor():
    p = ClaudeProvider(client=MagicMock(), model_id="claude-sonnet-4-6")
    assert p.model_id == "claude-sonnet-4-6"
```

```bash
cd ingredients && uv run pytest tests/test_mapping_provider_claude.py -q
```

Expected: FAIL — module missing.

- [ ] **Step 2: Implement `llm_provider_claude.py`**

```python
# ingredients/src/ingredients/mapping/llm_provider_claude.py
"""Anthropic Claude provider for Phase 2.

Defaults to Haiku 4.5; the resolver may instantiate a Sonnet 4.6 instance
on retry for low-confidence cases (deferred — out of scope for v1 plan).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .llm_provider import ProviderResult

DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_MAX_TOKENS = 256


@dataclass
class ClaudeProvider:
    client: object               # anthropic.Anthropic; typed as object so tests can pass a Mock.
    model_id: str = DEFAULT_MODEL
    max_tokens: int = DEFAULT_MAX_TOKENS

    @classmethod
    def from_env(cls, *, model_id: str = DEFAULT_MODEL) -> "ClaudeProvider":
        import anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set. Add it to .env or export before "
                "running `map resolve-pending --provider claude`."
            )
        return cls(client=anthropic.Anthropic(api_key=api_key), model_id=model_id)

    def resolve(self, *, system_prompt: str, user_prompt: str) -> ProviderResult:
        msg = self.client.messages.create(
            model=self.model_id,
            max_tokens=self.max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        # Anthropic returns a list of content blocks; the first one is text.
        text = msg.content[0].text
        return ProviderResult(raw_text=text, model_id=self.model_id)
```

- [ ] **Step 3: Run tests**

```bash
cd ingredients && uv run pytest tests/test_mapping_provider_claude.py -q
```

Expected: 2 passed.

- [ ] **Step 4: Commit**

```bash
git add ingredients/src/ingredients/mapping/llm_provider_claude.py \
        ingredients/tests/test_mapping_provider_claude.py
git commit -m "add ClaudeProvider for Phase 2"
```

---

### Task 15: `llm_provider_ollama.py` — Ollama implementation

**Files:**
- Create: `ingredients/src/ingredients/mapping/llm_provider_ollama.py`
- Create: `ingredients/tests/test_mapping_provider_ollama.py`

- [ ] **Step 1: Write the failing provider test**

```python
# ingredients/tests/test_mapping_provider_ollama.py
from unittest.mock import MagicMock

from ingredients.mapping.llm_provider_ollama import OllamaProvider


def _fake_httpx_client(reply_text: str) -> MagicMock:
    client = MagicMock()
    fake_resp = MagicMock()
    fake_resp.json.return_value = {"response": reply_text}
    fake_resp.raise_for_status.return_value = None
    client.post.return_value = fake_resp
    return client


def test_resolve_posts_to_generate_endpoint_and_returns_text():
    client = _fake_httpx_client('{"action": "abstain"}')
    p = OllamaProvider(client=client, model_id="qwen3:14b", base_url="http://localhost:11434")
    out = p.resolve(system_prompt="sys", user_prompt="u")
    assert out.raw_text == '{"action": "abstain"}'
    assert out.model_id == "qwen3:14b"

    client.post.assert_called_once()
    args = client.post.call_args
    assert args.args[0].endswith("/api/generate")
    payload = args.kwargs["json"]
    assert payload["model"] == "qwen3:14b"
    assert payload["system"] == "sys"
    assert payload["prompt"] == "u"
    assert payload["stream"] is False


def test_model_id_property_matches_constructor():
    p = OllamaProvider(client=MagicMock(), model_id="llama3:8b")
    assert p.model_id == "llama3:8b"
```

```bash
cd ingredients && uv run pytest tests/test_mapping_provider_ollama.py -q
```

Expected: FAIL — module missing.

- [ ] **Step 2: Implement `llm_provider_ollama.py`**

```python
# ingredients/src/ingredients/mapping/llm_provider_ollama.py
"""Ollama provider for Phase 2.

Calls the local /api/generate endpoint over HTTP. No streaming.
The classify pipeline already pulls qwen3:14b; reuse that model here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .llm_provider import ProviderResult

DEFAULT_MODEL = "qwen3:14b"
DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_TIMEOUT = 120.0


@dataclass
class OllamaProvider:
    client: object               # httpx.Client; typed as object so tests can pass a Mock.
    model_id: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL

    @classmethod
    def from_env(cls, *, model_id: str = DEFAULT_MODEL) -> "OllamaProvider":
        import httpx
        base_url = os.environ.get("OLLAMA_BASE_URL", DEFAULT_BASE_URL)
        client = httpx.Client(timeout=DEFAULT_TIMEOUT)
        return cls(client=client, model_id=model_id, base_url=base_url)

    def resolve(self, *, system_prompt: str, user_prompt: str) -> ProviderResult:
        url = self.base_url.rstrip("/") + "/api/generate"
        resp = self.client.post(
            url,
            json={
                "model": self.model_id,
                "system": system_prompt,
                "prompt": user_prompt,
                "stream": False,
            },
        )
        resp.raise_for_status()
        text = resp.json().get("response", "")
        return ProviderResult(raw_text=text, model_id=self.model_id)
```

- [ ] **Step 3: Run tests**

```bash
cd ingredients && uv run pytest tests/test_mapping_provider_ollama.py -q
```

Expected: 2 passed.

- [ ] **Step 4: Commit**

```bash
git add ingredients/src/ingredients/mapping/llm_provider_ollama.py \
        ingredients/tests/test_mapping_provider_ollama.py
git commit -m "add OllamaProvider for Phase 2"
```

---

### Task 16: `proposals.py` — write/read `taxonomy_proposals`

**Files:**
- Create: `ingredients/src/ingredients/mapping/proposals.py`
- Create: `ingredients/tests/test_mapping_proposals.py`

- [ ] **Step 1: Write the failing proposals test**

```python
# ingredients/tests/test_mapping_proposals.py
import psycopg

from ingredients.mapping.proposals import (
    enqueue_form_proposal, fetch_pending_proposals, mark_decided,
)


def test_enqueue_writes_pending_row(fixture_taxonomy):
    conn, ids = fixture_taxonomy
    pid = enqueue_form_proposal(
        conn,
        raw_string="lemon zest",
        proposed_slug="lemon_zest",
        proposed_display_name="Lemon Zest",
        proposed_parent_id=ids["lemon"],
        candidates=[{"node_id": ids["lemon_wheel"], "display_name": "Lemon Wheel", "similarity": 0.6}],
        mapper_version="v1",
    )
    row = conn.execute(
        "select raw_string, proposed_slug, status from taxonomy_proposals where id = %s",
        (pid,),
    ).fetchone()
    assert row == ("lemon zest", "lemon_zest", "pending")


def test_enqueue_is_idempotent_per_version(fixture_taxonomy):
    conn, ids = fixture_taxonomy
    enqueue_form_proposal(
        conn, raw_string="lemon zest", proposed_slug="lemon_zest",
        proposed_display_name="Lemon Zest", proposed_parent_id=ids["lemon"],
        candidates=[], mapper_version="v1",
    )
    # Same string + same version: no duplicate row, returns existing id.
    pid2 = enqueue_form_proposal(
        conn, raw_string="lemon zest", proposed_slug="lemon_zest",
        proposed_display_name="Lemon Zest", proposed_parent_id=ids["lemon"],
        candidates=[], mapper_version="v1",
    )
    assert conn.execute("select count(*) from taxonomy_proposals").fetchone()[0] == 1
    assert isinstance(pid2, int)


def test_fetch_pending_returns_only_pending(fixture_taxonomy):
    conn, ids = fixture_taxonomy
    pid = enqueue_form_proposal(
        conn, raw_string="lemon zest", proposed_slug="lemon_zest",
        proposed_display_name="Lemon Zest", proposed_parent_id=ids["lemon"],
        candidates=[], mapper_version="v1",
    )
    enqueue_form_proposal(
        conn, raw_string="lime oil", proposed_slug="lime_oil",
        proposed_display_name="Lime Oil", proposed_parent_id=ids["lemon"],
        candidates=[], mapper_version="v1",
    )
    mark_decided(conn, proposal_id=pid, status="rejected", decided_by="alice")
    pending = fetch_pending_proposals(conn)
    assert [p["raw_string"] for p in pending] == ["lime oil"]


def test_mark_decided_rejects_invalid_status(fixture_taxonomy):
    import pytest
    conn, _ = fixture_taxonomy
    with pytest.raises(ValueError):
        mark_decided(conn, proposal_id=1, status="maybe", decided_by="alice")
```

```bash
cd ingredients && uv run pytest tests/test_mapping_proposals.py -q
```

Expected: FAIL — module missing.

- [ ] **Step 2: Implement `proposals.py`**

```python
# ingredients/src/ingredients/mapping/proposals.py
"""CRUD over taxonomy_proposals (form-node review queue).

Brand/expression auto-creates do NOT use this table — they go straight
into taxonomy_nodes with a taxonomy_provenance row.
"""

from __future__ import annotations

import json
from typing import Any

import psycopg

_VALID_STATUSES = {"pending", "approved", "rejected"}


def enqueue_form_proposal(
    conn: psycopg.Connection,
    *,
    raw_string: str,
    proposed_slug: str,
    proposed_display_name: str,
    proposed_parent_id: int | None,
    candidates: list[dict[str, Any]],
    mapper_version: str,
) -> int:
    """Insert if (raw_string, mapper_version) absent; return existing id otherwise."""
    row = conn.execute(
        """
        insert into taxonomy_proposals
            (raw_string, proposed_slug, proposed_parent_id, candidates, mapper_version)
        values (%s, %s, %s, %s::jsonb, %s)
        on conflict (raw_string, mapper_version) do update
            set proposed_slug = excluded.proposed_slug
        returning id
        """,
        (raw_string, proposed_slug, proposed_parent_id, json.dumps(candidates), mapper_version),
    ).fetchone()
    conn.commit()
    # The display_name isn't stored on the row (it's reconstructable from the
    # node when the proposal is approved); kept as a parameter for future use
    # by the review CLI without changing the schema. Suppress unused-arg warning.
    _ = proposed_display_name
    return row[0]


def fetch_pending_proposals(conn: psycopg.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select id, raw_string, proposed_slug, proposed_parent_id, candidates, mapper_version
        from taxonomy_proposals
        where status = 'pending'
        order by created_at, id
        """
    ).fetchall()
    return [
        {
            "id": r[0], "raw_string": r[1], "proposed_slug": r[2],
            "proposed_parent_id": r[3], "candidates": r[4], "mapper_version": r[5],
        }
        for r in rows
    ]


def mark_decided(
    conn: psycopg.Connection, *,
    proposal_id: int, status: str, decided_by: str,
) -> None:
    if status not in _VALID_STATUSES:
        raise ValueError(f"invalid status {status!r}; expected one of {_VALID_STATUSES}")
    conn.execute(
        "update taxonomy_proposals "
        "set status = %s, decided_by = %s, decided_at = now() where id = %s",
        (status, decided_by, proposal_id),
    )
    conn.commit()
```

- [ ] **Step 3: Run tests**

```bash
cd ingredients && uv run pytest tests/test_mapping_proposals.py -q
```

Expected: 4 passed.

- [ ] **Step 4: Commit**

```bash
git add ingredients/src/ingredients/mapping/proposals.py \
        ingredients/tests/test_mapping_proposals.py
git commit -m "add taxonomy_proposals CRUD for form-node review queue"
```

---

### Task 17: `llm_resolver.py` — Phase 2 orchestrator + auto-create + queue enqueue

**Files:**
- Create: `ingredients/src/ingredients/mapping/llm_resolver.py`
- Create: `ingredients/tests/test_mapping_llm_resolver.py`

- [ ] **Step 1: Write the failing resolver test**

```python
# ingredients/tests/test_mapping_llm_resolver.py
"""Phase 2 orchestrator. We exercise it with a stub provider so the test
covers cascade -> auto-create / queue / abstain branches without going
out to the network."""

from __future__ import annotations

import psycopg

from ingredients.mapping.db import write_pending
from ingredients.mapping.llm_provider import ProviderResult
from ingredients.mapping.llm_resolver import run_phase2
from ingredients.mapping.mapper import MAPPER_VERSION


class StubProvider:
    """Returns a configurable response per (normalized_name, hit count)."""
    def __init__(self, responses: dict[str, str]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str]] = []
        self.model_id = "stub-1"

    def resolve(self, *, system_prompt: str, user_prompt: str) -> ProviderResult:
        # Find which name this prompt is about by inspecting user_prompt.
        for name in self.responses:
            if f'"name": "{name}"' in user_prompt:
                self.calls.append((name, self.responses[name]))
                return ProviderResult(raw_text=self.responses[name], model_id=self.model_id)
        raise AssertionError(f"no stub response configured for prompt: {user_prompt[:200]}")


def _seed_pending(conn: psycopg.Connection, names: list[str]) -> None:
    conn.execute("truncate table recipe_ingredients, recipes restart identity cascade")
    rid = conn.execute(
        "insert into recipes (site, source_url, jsonld) values ('punch', 'https://example.com/x', '{}'::jsonb) returning id"
    ).fetchone()[0]
    for pos, name in enumerate(names):
        conn.execute(
            "insert into recipe_ingredients "
            "(recipe_id, position, raw_text, name, parse_status, parser_rule, parser_version) "
            "values (%s,%s,%s,%s,'parsed','qty_unit','v1')",
            (rid, pos, f"1 oz {name}", name),
        )
    conn.commit()
    for name in names:
        write_pending(conn, normalized_name=name.lower().strip(), mapper_version=MAPPER_VERSION)


def test_resolver_handles_chose_action(fixture_taxonomy):
    conn, ids = fixture_taxonomy
    _seed_pending(conn, ["fancy gin variant"])
    provider = StubProvider({
        "fancy gin variant": '{"action": "chose", "node_id": ' + str(ids["gin"]) + '}',
    })
    summary = run_phase2(conn, provider=provider)
    row = conn.execute(
        "select taxonomy_node_id, mapper_source from recipe_ingredients "
        "where lower(trim(name)) = 'fancy gin variant'"
    ).fetchone()
    assert row == (ids["gin"], "llm")
    assert summary == {"chose": 1}


def test_resolver_auto_creates_brand_with_existing_parent(fixture_taxonomy):
    conn, ids = fixture_taxonomy
    _seed_pending(conn, ["bombay sapphire"])
    provider = StubProvider({
        "bombay sapphire": (
            '{"action": "propose_brand", "slug": "bombay_sapphire", '
            '"display_name": "Bombay Sapphire", "parent_slug": "london_dry_gin", '
            '"role": "brand"}'
        ),
    })
    summary = run_phase2(conn, provider=provider)
    new_node = conn.execute(
        "select id, role from taxonomy_nodes where slug = 'bombay_sapphire'"
    ).fetchone()
    assert new_node is not None
    new_id, new_role = new_node
    assert new_role == "brand"

    # Edge to parent.
    parent_id_row = conn.execute(
        "select parent_id from taxonomy_edges where child_id = %s", (new_id,),
    ).fetchone()
    assert parent_id_row[0] == ids["london_dry_gin"]

    # Provenance row written.
    prov = conn.execute(
        "select source, model_id, raw_string from taxonomy_provenance where node_id = %s", (new_id,),
    ).fetchone()
    assert prov == ("llm-mapper", "stub-1", "bombay sapphire")

    # Recipe row got mapped.
    row = conn.execute(
        "select taxonomy_node_id, mapper_source from recipe_ingredients "
        "where lower(trim(name)) = 'bombay sapphire'"
    ).fetchone()
    assert row == (new_id, "llm")
    assert summary == {"propose_brand": 1}


def test_resolver_abstains_when_proposed_parent_missing(fixture_taxonomy):
    conn, _ = fixture_taxonomy
    _seed_pending(conn, ["mystery liqueur"])
    provider = StubProvider({
        "mystery liqueur": (
            '{"action": "propose_brand", "slug": "mystery", "display_name": "Mystery", '
            '"parent_slug": "does_not_exist", "role": "brand"}'
        ),
    })
    summary = run_phase2(conn, provider=provider)
    row = conn.execute(
        "select taxonomy_node_id, mapper_source from recipe_ingredients "
        "where lower(trim(name)) = 'mystery liqueur'"
    ).fetchone()
    assert row == (None, "abstain")
    assert summary == {"abstain": 1}


def test_resolver_enqueues_form_proposal_and_marks_pending(fixture_taxonomy):
    conn, ids = fixture_taxonomy
    _seed_pending(conn, ["lemon zest"])
    provider = StubProvider({
        "lemon zest": (
            '{"action": "propose_form", "slug": "lemon_zest", '
            '"display_name": "Lemon Zest", "parent_slug": "lemon"}'
        ),
    })
    summary = run_phase2(conn, provider=provider)
    # Row stays pending_llm — form proposals require human review before mapping.
    row = conn.execute(
        "select taxonomy_node_id, mapper_source from recipe_ingredients "
        "where lower(trim(name)) = 'lemon zest'"
    ).fetchone()
    assert row == (None, "pending_llm")

    proposals = conn.execute(
        "select raw_string, proposed_slug, proposed_parent_id, status from taxonomy_proposals"
    ).fetchall()
    assert proposals == [("lemon zest", "lemon_zest", ids["lemon"], "pending")]
    assert summary == {"propose_form": 1}


def test_resolver_handles_explicit_abstain(fixture_taxonomy):
    conn, _ = fixture_taxonomy
    _seed_pending(conn, ["truly unknown"])
    provider = StubProvider({"truly unknown": '{"action": "abstain"}'})
    summary = run_phase2(conn, provider=provider)
    row = conn.execute(
        "select taxonomy_node_id, mapper_source from recipe_ingredients "
        "where lower(trim(name)) = 'truly unknown'"
    ).fetchone()
    assert row == (None, "abstain")
    assert summary == {"abstain": 1}


def test_resolver_respects_limit(fixture_taxonomy):
    conn, ids = fixture_taxonomy
    _seed_pending(conn, ["fancy gin variant", "another thing"])
    provider = StubProvider({
        "fancy gin variant": '{"action": "chose", "node_id": ' + str(ids["gin"]) + '}',
        "another thing":     '{"action": "abstain"}',
    })
    summary = run_phase2(conn, provider=provider, limit=1)
    assert sum(summary.values()) == 1
    # The remaining one is still pending_llm.
    pending = conn.execute(
        "select count(*) from recipe_ingredients where mapper_source = 'pending_llm'"
    ).fetchone()[0]
    assert pending == 1
```

```bash
cd ingredients && uv run pytest tests/test_mapping_llm_resolver.py -q
```

Expected: FAIL — module missing.

- [ ] **Step 2: Implement `llm_resolver.py`**

```python
# ingredients/src/ingredients/mapping/llm_resolver.py
"""Phase 2 orchestrator. Drains the pending_llm queue using a chosen provider.

Branching by LLM action:

  chose          -> write_resolution(source='llm')
  propose_brand  -> insert taxonomy_node + edge + provenance, then resolve
  propose_form   -> enqueue_form_proposal; row stays pending_llm for review
  abstain        -> write_abstain
"""

from __future__ import annotations

from collections import Counter

import psycopg

from .db import fetch_pending_llm_names, write_abstain, write_resolution
from .lexical_layer import lexical_candidates
from .llm_provider import LLMProvider
from .mapper import MAPPER_VERSION
from .normalize import normalize_name
from .prompt import (
    SYSTEM_PROMPT, build_user_prompt, parse_response, prompt_hash,
)
from .proposals import enqueue_form_proposal


def _candidates_with_parents(
    conn: psycopg.Connection, normalized: str, limit: int = 20,
) -> list[dict]:
    cands = lexical_candidates(conn, normalized, limit=limit)
    if not cands:
        return []
    ids_tuple = tuple({c["node_id"] for c in cands})
    parent_rows = conn.execute(
        """
        select e.child_id, n.slug
        from taxonomy_edges e
        join taxonomy_nodes n on n.id = e.parent_id
        where e.child_id = any(%s)
        """,
        (list(ids_tuple),),
    ).fetchall()
    parents_by_child: dict[int, list[str]] = {}
    for child, slug in parent_rows:
        parents_by_child.setdefault(child, []).append(slug)
    for c in cands:
        c["parents"] = parents_by_child.get(c["node_id"], [])
    return cands


def _lookup_node_by_slug(conn: psycopg.Connection, slug: str) -> int | None:
    row = conn.execute(
        "select id from taxonomy_nodes where slug = %s", (slug,),
    ).fetchone()
    return row[0] if row else None


def _create_brand_node(
    conn: psycopg.Connection,
    *,
    slug: str,
    display_name: str,
    parent_id: int,
    role: str,
    raw_string: str,
    prompt_hash_value: str,
    model_id: str,
) -> int:
    """Insert the new node + edge + provenance. is_cluster_node defaults
    to false (E's column); the antichain stays curator-controlled."""
    new_id = conn.execute(
        "insert into taxonomy_nodes (slug, display_name, role) "
        "values (%s, %s, %s) returning id",
        (slug, display_name, role),
    ).fetchone()[0]
    conn.execute(
        "insert into taxonomy_edges (parent_id, child_id) values (%s, %s)",
        (parent_id, new_id),
    )
    conn.execute(
        """
        insert into taxonomy_provenance
            (node_id, source, mapper_version, raw_string, prompt_hash, model_id)
        values (%s, 'llm-mapper', %s, %s, %s, %s)
        """,
        (new_id, MAPPER_VERSION, raw_string, prompt_hash_value, model_id),
    )
    conn.commit()
    return new_id


def run_phase2(
    conn: psycopg.Connection,
    *,
    provider: LLMProvider,
    site: str | None = None,
    limit: int | None = None,
) -> dict[str, int]:
    """Drain the pending_llm queue. Returns Counter-shaped summary keyed by action."""
    counts: Counter[str] = Counter()
    names = fetch_pending_llm_names(conn, mapper_version=MAPPER_VERSION, limit=limit)
    for normalized in names:
        cands = _candidates_with_parents(conn, normalized)
        user_prompt = build_user_prompt(
            normalized_name=normalized, parser_unit=None, site=site, candidates=cands,
        )
        raw = provider.resolve(system_prompt=SYSTEM_PROMPT, user_prompt=user_prompt).raw_text
        action_obj = parse_response(raw)
        action = action_obj["action"]

        if action == "chose":
            write_resolution(
                conn, normalized_name=normalized,
                taxonomy_node_id=int(action_obj["node_id"]),
                source="llm", mapper_version=MAPPER_VERSION,
            )
            counts["chose"] += 1
        elif action == "propose_brand":
            parent_id = _lookup_node_by_slug(conn, action_obj["parent_slug"])
            if parent_id is None:
                write_abstain(conn, normalized_name=normalized, mapper_version=MAPPER_VERSION)
                counts["abstain"] += 1
                continue
            new_id = _create_brand_node(
                conn,
                slug=action_obj["slug"],
                display_name=action_obj["display_name"],
                parent_id=parent_id,
                role=action_obj["role"],
                raw_string=normalized,
                prompt_hash_value=prompt_hash(normalized, None, site, cands),
                model_id=provider.model_id,
            )
            write_resolution(
                conn, normalized_name=normalized, taxonomy_node_id=new_id,
                source="llm", mapper_version=MAPPER_VERSION,
            )
            counts["propose_brand"] += 1
        elif action == "propose_form":
            parent_id = _lookup_node_by_slug(conn, action_obj["parent_slug"])
            enqueue_form_proposal(
                conn,
                raw_string=normalized,
                proposed_slug=action_obj["slug"],
                proposed_display_name=action_obj["display_name"],
                proposed_parent_id=parent_id,
                candidates=cands,
                mapper_version=MAPPER_VERSION,
            )
            # Row stays pending_llm awaiting human review.
            counts["propose_form"] += 1
        elif action == "abstain":
            write_abstain(conn, normalized_name=normalized, mapper_version=MAPPER_VERSION)
            counts["abstain"] += 1
    return dict(counts)
```

- [ ] **Step 3: Run tests**

```bash
cd ingredients && uv run pytest tests/test_mapping_llm_resolver.py -q
```

Expected: 6 passed.

- [ ] **Step 4: Commit**

```bash
git add ingredients/src/ingredients/mapping/llm_resolver.py \
        ingredients/tests/test_mapping_llm_resolver.py
git commit -m "add Phase 2 resolver: chose / brand auto-create / form queue / abstain"
```

---

### Task 18: CLI — `map resolve-pending --provider {claude|ollama}`

**Files:**
- Modify: `ingredients/src/ingredients/cli.py`
- Modify: `ingredients/tests/test_mapping_cli.py`

- [ ] **Step 1: Add the `resolve-pending` subparser**

In `cli.py`, locate the `map_sub = p_map.add_subparsers(dest="map_cmd")` line added in Task 10 and append:

```python
    p_resolve = map_sub.add_parser(
        "resolve-pending",
        help="Phase 2 — drain the pending_llm queue using the chosen provider.",
    )
    p_resolve.add_argument(
        "--provider", choices=["claude", "ollama"], required=True,
        help="LLM provider to use.",
    )
    p_resolve.add_argument("--limit", type=int, default=None,
                           help="Process at most N distinct pending names.")
    p_resolve.add_argument("--yes", action="store_true",
                           help="Skip the residual-count confirmation prompt.")
```

- [ ] **Step 2: Add the `run_resolve_pending` dispatch**

In `cli.py`, edit `run_map` to dispatch on `args.map_cmd` *before* falling through to the Phase 1 logic from Task 10. The existing body of `run_map` (the dry-run / sample / reset stubs and the `run_phase1` call) stays in place — only add the early-return at the top:

```python
def run_map(args: argparse.Namespace) -> int:
    if getattr(args, "map_cmd", None) == "resolve-pending":
        return run_resolve_pending(args)
    # — Phase 1 logic from Task 10 (run_phase1, dry-run, sample, reset) —
    # (unchanged; the rest of run_map stays exactly as it was)
    if args.review:
        log.error("--review for map not implemented yet (Task 21)")
        return 2
    if args.sample is not None:
        log.error("--sample for map not implemented yet (Task 20)")
        return 2
    db = IngredientsDatabase()
    try:
        if args.reset:
            log.error("map --reset not implemented yet (Task 20)")
            return 2
        from ingredients.mapping.mapper import MAPPER_VERSION, run_phase1
        summary = run_phase1(
            db.conn, site=args.site, limit=args.limit, dry_run=args.dry_run,
        )
        mode = "dry-run" if args.dry_run else "applied"
        changes = {"all": Counter(summary)}
        print_summary(f"Map ingredients (Phase 1, {MAPPER_VERSION})", changes, mode=mode)
        return 0
    finally:
        db.close()


def run_resolve_pending(args: argparse.Namespace) -> int:
    from ingredients.mapping.db import fetch_pending_llm_names
    from ingredients.mapping.llm_resolver import run_phase2
    from ingredients.mapping.mapper import MAPPER_VERSION

    db = IngredientsDatabase()
    try:
        pending = fetch_pending_llm_names(db.conn, mapper_version=MAPPER_VERSION)
        if not pending:
            log.info("nothing pending; queue is empty")
            return 0

        # Show residual count + top-N before any external call so the
        # operator can choose to skip / hand-curate / proceed.
        log.info("%d distinct names pending Phase 2", len(pending))
        for n in pending[:20]:
            log.info("  %s", n)
        if len(pending) > 20:
            log.info("  ... and %d more", len(pending) - 20)

        if not args.yes:
            sys.stderr.write(f"Proceed with --provider {args.provider}? [y/N]: ")
            sys.stderr.flush()
            answer = sys.stdin.readline().strip().lower()
            if answer not in ("y", "yes"):
                log.info("aborted by operator")
                return 1

        if args.provider == "claude":
            from ingredients.mapping.llm_provider_claude import ClaudeProvider
            provider = ClaudeProvider.from_env()
        else:
            from ingredients.mapping.llm_provider_ollama import OllamaProvider
            provider = OllamaProvider.from_env()

        summary = run_phase2(db.conn, provider=provider, limit=args.limit)
        changes = {"all": Counter(summary)}
        print_summary(
            f"Map resolve-pending ({args.provider}, {MAPPER_VERSION})",
            changes, mode="applied",
        )
        return 0
    finally:
        db.close()
```

- [ ] **Step 3: Append a CLI test**

Add to `ingredients/tests/test_mapping_cli.py`:

```python
def test_cli_map_resolve_pending_aborts_without_yes_on_pipe(fixture_taxonomy, test_db_url):
    conn, _ = fixture_taxonomy
    # Seed one pending row.
    conn.execute("truncate table recipe_ingredients, recipes restart identity cascade")
    rid = conn.execute(
        "insert into recipes (site, source_url, jsonld) values ('punch', 'https://example.com/q', '{}'::jsonb) returning id"
    ).fetchone()[0]
    conn.execute(
        "insert into recipe_ingredients "
        "(recipe_id, position, raw_text, name, parse_status, parser_rule, parser_version, "
        " mapper_source, mapper_version) "
        "values (%s, 0, '1 oz unknown', 'unknown', 'parsed', 'qty_unit', 'v1', 'pending_llm', 'v1')",
        (rid,),
    )
    conn.commit()

    proc = _run_cli(
        ["map", "resolve-pending", "--provider", "claude"],
        {"SUPABASE_DB_URL": test_db_url},
    )
    # Without --yes and with non-tty stdin, the run aborts cleanly (exit 1).
    assert proc.returncode == 1
    # Nothing got resolved.
    row = conn.execute(
        "select mapper_source from recipe_ingredients where lower(trim(name))='unknown'"
    ).fetchone()
    assert row[0] == "pending_llm"


def test_cli_map_resolve_pending_empty_queue_exits_zero(fixture_taxonomy, test_db_url):
    conn, _ = fixture_taxonomy
    conn.execute("truncate table recipe_ingredients, recipes restart identity cascade")
    conn.commit()
    proc = _run_cli(
        ["map", "resolve-pending", "--provider", "claude"],
        {"SUPABASE_DB_URL": test_db_url},
    )
    assert proc.returncode == 0
```

```bash
cd ingredients && uv run pytest tests/test_mapping_cli.py -q
```

Expected: 4 passed.

- [ ] **Step 4: Commit**

```bash
git add ingredients/src/ingredients/cli.py ingredients/tests/test_mapping_cli.py
git commit -m "wire up map resolve-pending subcommand with provider gating"
```

---

## Phase G — Review queue CLI + reset + sample

### Task 19: CLI — `map review-proposals` (interactive form review)

**Files:**
- Modify: `ingredients/src/ingredients/cli.py`
- Modify: `ingredients/tests/test_mapping_cli.py`

- [ ] **Step 1: Add the `review-proposals` subparser and a script-friendly `--input-stream` test hook**

In `cli.py`, append to `map_sub`:

```python
    p_review = map_sub.add_parser(
        "review-proposals",
        help="Walk the pending taxonomy_proposals queue interactively.",
    )
    p_review.add_argument(
        "--decided-by", default=os.environ.get("USER", "operator"),
        help="Name recorded on each decision.",
    )
```

Add this near the top of `cli.py`:

```python
import os
```

And dispatch in `run_map`:

```python
    if getattr(args, "map_cmd", None) == "review-proposals":
        return run_review_proposals(args)
```

- [ ] **Step 2: Implement `run_review_proposals`**

```python
def run_review_proposals(args: argparse.Namespace) -> int:
    from ingredients.mapping.db import write_resolution
    from ingredients.mapping.mapper import MAPPER_VERSION
    from ingredients.mapping.proposals import (
        fetch_pending_proposals, mark_decided,
    )

    db = IngredientsDatabase()
    try:
        pending = fetch_pending_proposals(db.conn)
        if not pending:
            log.info("no pending proposals")
            return 0

        for p in pending:
            print()
            print(f"proposal #{p['id']}  raw_string={p['raw_string']!r}  proposed_slug={p['proposed_slug']!r}")
            parent_label = "(none)"
            if p["proposed_parent_id"]:
                row = db.conn.execute(
                    "select slug, display_name from taxonomy_nodes where id = %s",
                    (p["proposed_parent_id"],),
                ).fetchone()
                if row:
                    parent_label = f"{row[1]} ({row[0]}, id={p['proposed_parent_id']})"
            print(f"  parent: {parent_label}")
            print("  closest existing candidates:")
            for c in (p["candidates"] or [])[:5]:
                print(f"    {c.get('display_name')}  sim={c.get('similarity'):.2f}  id={c.get('node_id')}")

            answer = input("[a]pprove / [r]eject / [s]kip / [e]dit slug: ").strip().lower()
            slug = p["proposed_slug"]
            if answer == "e":
                slug = input(f"new slug (was {slug!r}): ").strip() or slug
                answer = "a"  # treat edited as approve

            if answer == "a":
                if not p["proposed_parent_id"]:
                    log.error("cannot approve without a parent_id; rejecting instead")
                    mark_decided(db.conn, proposal_id=p["id"], status="rejected", decided_by=args.decided_by)
                    continue
                # Create the new node + edge + alias; resolve the row.
                new_id = db.conn.execute(
                    "insert into taxonomy_nodes (slug, display_name) values (%s, %s) returning id",
                    (slug, slug.replace("_", " ").title()),
                ).fetchone()[0]
                db.conn.execute(
                    "insert into taxonomy_edges (parent_id, child_id) values (%s, %s)",
                    (p["proposed_parent_id"], new_id),
                )
                db.conn.execute(
                    "insert into taxonomy_aliases (alias, node_id) values (%s, %s) on conflict do nothing",
                    (p["raw_string"], new_id),
                )
                db.conn.commit()
                write_resolution(
                    db.conn, normalized_name=p["raw_string"],
                    taxonomy_node_id=new_id, source="llm",
                    mapper_version=MAPPER_VERSION,
                )
                mark_decided(db.conn, proposal_id=p["id"], status="approved", decided_by=args.decided_by)
                log.info("approved %s as node id=%s", slug, new_id)
            elif answer == "r":
                mark_decided(db.conn, proposal_id=p["id"], status="rejected", decided_by=args.decided_by)
                log.info("rejected %s", p["proposed_slug"])
            else:
                continue  # skip
        return 0
    finally:
        db.close()
```

- [ ] **Step 3: Add a smoke test (subprocess can't easily drive `input()`, so test via direct call)**

Append to `ingredients/tests/test_mapping_cli.py`:

```python
def test_review_proposals_approve_creates_node(fixture_taxonomy, test_db_url, monkeypatch):
    """Drive run_review_proposals directly with a stubbed input() so we
    don't need to wrangle a subprocess pty."""
    from ingredients.cli import run_review_proposals
    from ingredients.mapping.proposals import enqueue_form_proposal
    import argparse

    conn, ids = fixture_taxonomy
    enqueue_form_proposal(
        conn, raw_string="lemon zest", proposed_slug="lemon_zest",
        proposed_display_name="Lemon Zest", proposed_parent_id=ids["lemon"],
        candidates=[{"node_id": ids["lemon_wheel"], "display_name": "Lemon Wheel", "similarity": 0.6}],
        mapper_version="v1",
    )

    answers = iter(["a"])  # approve first proposal
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    monkeypatch.setenv("SUPABASE_DB_URL", test_db_url)

    rc = run_review_proposals(argparse.Namespace(decided_by="tester"))
    assert rc == 0

    new_node = conn.execute(
        "select id from taxonomy_nodes where slug = 'lemon_zest'"
    ).fetchone()
    assert new_node is not None
    status = conn.execute(
        "select status, decided_by from taxonomy_proposals where raw_string = 'lemon zest'"
    ).fetchone()
    assert status == ("approved", "tester")
```

```bash
cd ingredients && uv run pytest tests/test_mapping_cli.py -q
```

Expected: 5 passed.

- [ ] **Step 4: Commit**

```bash
git add ingredients/src/ingredients/cli.py ingredients/tests/test_mapping_cli.py
git commit -m "wire up map review-proposals interactive subcommand"
```

---

### Task 20: CLI — `--reset` and `--sample` for `map`

**Files:**
- Modify: `ingredients/src/ingredients/cli.py`
- Create: `ingredients/src/ingredients/mapping/admin.py`
- Modify: `ingredients/tests/test_mapping_cli.py`

- [ ] **Step 1: Write the failing CLI tests**

Append to `ingredients/tests/test_mapping_cli.py`:

```python
def test_cli_map_reset_clears_mapping_columns_in_scope(fixture_taxonomy, test_db_url):
    conn, ids = fixture_taxonomy
    conn.execute("truncate table recipe_ingredients, recipes restart identity cascade")
    rid = conn.execute(
        "insert into recipes (site, source_url, jsonld) values ('punch', 'https://example.com/r', '{}'::jsonb) returning id"
    ).fetchone()[0]
    conn.execute(
        "insert into recipe_ingredients "
        "(recipe_id, position, raw_text, name, parse_status, parser_rule, parser_version, "
        " taxonomy_node_id, mapper_source, mapper_version, mapper_at) "
        "values (%s, 0, '2 oz gin', 'gin', 'parsed', 'qty_unit', 'v1', %s, 'alias', 'v1', now())",
        (rid, ids["gin"]),
    )
    conn.commit()

    proc = _run_cli(["map", "--reset", "--yes"], {"SUPABASE_DB_URL": test_db_url})
    assert proc.returncode == 0, proc.stderr
    row = conn.execute(
        "select taxonomy_node_id, mapper_source, mapper_version "
        "from recipe_ingredients where lower(trim(name))='gin'"
    ).fetchone()
    assert row == (None, None, None)


def test_cli_map_sample_writes_nothing(fixture_taxonomy, test_db_url):
    conn, _ = fixture_taxonomy
    conn.execute("truncate table recipe_ingredients, recipes restart identity cascade")
    rid = conn.execute(
        "insert into recipes (site, source_url, jsonld) values ('punch', 'https://example.com/s', '{}'::jsonb) returning id"
    ).fetchone()[0]
    conn.execute(
        "insert into recipe_ingredients "
        "(recipe_id, position, raw_text, name, parse_status, parser_rule, parser_version) "
        "values (%s, 0, '2 oz gin', 'gin', 'parsed', 'qty_unit', 'v1')",
        (rid,),
    )
    conn.commit()

    proc = _run_cli(["map", "--sample", "5"], {"SUPABASE_DB_URL": test_db_url})
    assert proc.returncode == 0, proc.stderr
    row = conn.execute(
        "select taxonomy_node_id, mapper_source from recipe_ingredients where lower(trim(name))='gin'"
    ).fetchone()
    assert row == (None, None)
    # Sample output should appear in stdout.
    assert "gin" in proc.stdout
```

```bash
cd ingredients && uv run pytest tests/test_mapping_cli.py -q
```

Expected: FAIL on the two new tests because dispatch is still the "not implemented yet" stub.

- [ ] **Step 2: Implement `mapping/admin.py`**

```python
# ingredients/src/ingredients/mapping/admin.py
"""Reset + sample helpers for the map CLI."""

from __future__ import annotations

from typing import Any

import psycopg


def count_mapped_rows(
    conn: psycopg.Connection,
    *,
    site: str | None,
    except_version: str | None,
    older_than: str | None,
) -> int:
    sql, params = _filter_clause(
        "select count(*)", site=site, except_version=except_version, older_than=older_than,
    )
    return conn.execute(sql, params).fetchone()[0]


def clear_mapping_columns(
    conn: psycopg.Connection,
    *,
    site: str | None,
    except_version: str | None,
    older_than: str | None,
) -> int:
    sql, params = _filter_clause(
        "update recipe_ingredients ri "
        "set taxonomy_node_id = null, mapper_source = null, "
        "    mapper_version = null, mapper_at = null",
        site=site, except_version=except_version, older_than=older_than,
    )
    cur = conn.execute(sql, params)
    conn.commit()
    return cur.rowcount


def sample_pending(
    conn: psycopg.Connection,
    *,
    n: int,
    mapper_version: str,
    site: str | None = None,
) -> list[str]:
    """Return up to N random distinct pending names. Read-only."""
    params: list[Any] = [mapper_version]
    site_clause = ""
    if site is not None:
        site_clause = "and r.site = %s"
        params.append(site)
    params.append(n)
    rows = conn.execute(
        f"""
        select distinct lower(trim(ri.name))
        from recipe_ingredients ri
        join recipes r on r.id = ri.recipe_id
        where ri.name is not null
          and ri.parse_status = 'parsed'
          and (ri.mapper_version is null or ri.mapper_version <> %s)
          {site_clause}
        order by random()
        limit %s
        """,
        params,
    ).fetchall()
    return [r[0] for r in rows]


def _filter_clause(
    select: str, *, site: str | None,
    except_version: str | None, older_than: str | None,
) -> tuple[str, list[Any]]:
    clauses = ["ri.mapper_version is not null"]
    params: list[Any] = []
    if site is not None:
        clauses.append("ri.recipe_id in (select id from recipes where site = %s)")
        params.append(site)
    if except_version is not None:
        clauses.append("ri.mapper_version <> %s")
        params.append(except_version)
    if older_than is not None:
        clauses.append("ri.mapper_at < %s::timestamptz")
        params.append(older_than)
    where = " where " + " and ".join(clauses)
    # Distinguish UPDATE (uses alias `ri`) from SELECT (also uses `ri`).
    if select.lstrip().lower().startswith("update"):
        return select + where, params
    return f"{select} from recipe_ingredients ri{where}", params
```

- [ ] **Step 3: Wire up `--reset` and `--sample` in `run_map`**

Replace the two `log.error(... "not implemented yet")` stubs in `run_map` with:

```python
    if args.sample is not None:
        from ingredients.mapping.admin import sample_pending
        from ingredients.mapping.alias_layer import resolve_alias
        from ingredients.mapping.lexical_layer import resolve_lexical
        from ingredients.mapping.mapper import MAPPER_VERSION
        from ingredients.mapping.normalize import normalize_name
        from ingredients.mapping.types import Resolved
        db = IngredientsDatabase()
        try:
            for raw in sample_pending(
                db.conn, n=args.sample, mapper_version=MAPPER_VERSION, site=args.site,
            ):
                normalized = normalize_name(raw)
                a = resolve_alias(db.conn, normalized)
                if isinstance(a, Resolved):
                    print(f"  {raw!r:40s} -> alias  node_id={a.taxonomy_node_id}")
                    continue
                l = resolve_lexical(db.conn, normalized)
                if isinstance(l, Resolved):
                    print(f"  {raw!r:40s} -> lexical node_id={l.taxonomy_node_id}")
                else:
                    print(f"  {raw!r:40s} -> would mark pending_llm")
            return 0
        finally:
            db.close()
```

And:

```python
    if args.reset:
        from ingredients.mapping.admin import (
            clear_mapping_columns, count_mapped_rows,
        )
        db = IngredientsDatabase()
        try:
            to_clear = count_mapped_rows(
                db.conn,
                site=args.site, except_version=args.except_version,
                older_than=args.older_than,
            )
            scope = describe_reset_scope(
                site=args.site, except_version=args.except_version, older_than=args.older_than,
            )
            if not confirm_reset(
                row_count=to_clear, scope_desc=scope, assume_yes=args.yes,
            ):
                log.error("reset aborted")
                return 1
            if to_clear:
                n = clear_mapping_columns(
                    db.conn,
                    site=args.site, except_version=args.except_version,
                    older_than=args.older_than,
                )
                log.info("cleared mapping columns on %d rows", n)
            return 0
        finally:
            db.close()
```

- [ ] **Step 4: Run tests**

```bash
cd ingredients && uv run pytest tests/test_mapping_cli.py -q
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add ingredients/src/ingredients/cli.py \
        ingredients/src/ingredients/mapping/admin.py \
        ingredients/tests/test_mapping_cli.py
git commit -m "wire up map --reset and --sample"
```

---

## Phase H — Eval set + final integration

### Task 21: `mapping/eval_set.py` + `--review` runner

**Files:**
- Create: `ingredients/src/ingredients/mapping/eval_set.py`
- Create: `ingredients/tests/test_mapping_eval.py`
- Modify: `ingredients/src/ingredients/cli.py`

- [ ] **Step 1: Write the eval set**

```python
# ingredients/src/ingredients/mapping/eval_set.py
"""Checked-in golden cases for the mapper. Bumping MAPPER_VERSION should
be paired with re-running --review until it passes.

Cases run against the fixture taxonomy in ingredients/tests/fixtures/
(NOT the production seed). Add cases when:
  - A new pattern was taught (alias added, threshold tuned).
  - A wrong mapping was caught (corrective should-abstain case).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import psycopg

from .alias_layer import resolve_alias
from .lexical_layer import resolve_lexical
from .normalize import normalize_name
from .types import Pending, Resolved


@dataclass
class MapperEvalCase:
    raw_name: str
    parser_unit: str | None
    site: str | None
    expect_node_slug: str | None
    expect_source: str | None       # 'alias' | 'lexical' | 'pending_llm' | 'llm' | 'abstain'


# Fixture-anchored cases. Add new ones liberally.
EVAL_CASES: list[MapperEvalCase] = [
    # alias hits
    MapperEvalCase("gin",            "oz", "punch", "gin",          "alias"),
    MapperEvalCase("Lemon Juice",    "oz", "punch", "lemon_juice",  "alias"),
    MapperEvalCase("tanqueray gin",  "oz", "punch", "tanqueray",    "alias"),
    MapperEvalCase("bourbon",        "oz", "punch", "bourbon",      "alias"),
    # lexical hit (typo)
    MapperEvalCase("lemon juicee",   "oz", "punch", "lemon_juice",  "lexical"),
    # ambiguous lexical -> pending_llm
    MapperEvalCase("dry gin",        "oz", "punch", None,           "pending_llm"),
    # off-corpus -> pending_llm (Phase 1 only)
    MapperEvalCase("totally weird",  "oz", "punch", None,           "pending_llm"),
]


def run_eval(conn: psycopg.Connection) -> dict[str, Any]:
    """Run Phase 1 (alias + lexical) against each case. Phase 2 isn't
    exercised here — that's covered by test_mapping_llm_resolver.py."""
    cases: list[dict[str, Any]] = []
    passed = 0
    failed = 0
    for case in EVAL_CASES:
        normalized = normalize_name(case.raw_name)
        result = resolve_alias(conn, normalized)
        if isinstance(result, Pending):
            result = resolve_lexical(conn, normalized)
        slug = None
        source: str
        if isinstance(result, Resolved):
            slug_row = conn.execute(
                "select slug from taxonomy_nodes where id = %s", (result.taxonomy_node_id,),
            ).fetchone()
            slug = slug_row[0] if slug_row else None
            source = result.source
        else:
            source = "pending_llm"
        ok = (
            (case.expect_node_slug is None or slug == case.expect_node_slug)
            and (case.expect_source is None or source == case.expect_source)
        )
        cases.append({
            "raw": case.raw_name, "ok": ok, "slug": slug, "source": source,
        })
        if ok:
            passed += 1
        else:
            failed += 1
    return {"passed": passed, "failed": failed, "cases": cases}
```

- [ ] **Step 2: Write the failing eval test**

```python
# ingredients/tests/test_mapping_eval.py
from ingredients.mapping.eval_set import run_eval


def test_all_eval_cases_pass_against_fixture(fixture_taxonomy):
    conn, _ = fixture_taxonomy
    out = run_eval(conn)
    assert out["failed"] == 0, [c for c in out["cases"] if not c["ok"]]
    assert out["passed"] == len(out["cases"])
```

```bash
cd ingredients && uv run pytest tests/test_mapping_eval.py -q
```

Expected: PASS (the eval set was authored to pass against the fixture).

- [ ] **Step 3: Wire up `--review` in `run_map`**

Replace the `--review` stub with:

```python
    if args.review:
        # Eval runs against the fixture taxonomy in tests/fixtures/, so it
        # needs the test DB. Refuse if TEST_DB_URL isn't set.
        test_url = os.environ.get("TEST_DB_URL")
        if not test_url:
            log.error("--review needs TEST_DB_URL set; see CLAUDE.md")
            return 2
        from ingredients.mapping.eval_set import run_eval
        from ingredients.mapping.eval_fixture import seed
        import psycopg as _psycopg
        with _psycopg.connect(test_url) as conn:
            seed(conn)
            out = run_eval(conn)
        print("--- Mapper eval (fixture taxonomy) ---")
        print(f"  passed: {out['passed']}")
        print(f"  failed: {out['failed']}")
        if out["failed"]:
            print()
            for c in out["cases"]:
                if not c["ok"]:
                    print(f"  {c['raw']!r}\n    -> source={c['source']!r} slug={c['slug']!r}")
            return 1
        return 0
```

- [ ] **Step 4: Run all mapping tests**

```bash
cd ingredients && uv run pytest tests/ -q -k mapping
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add ingredients/src/ingredients/mapping/eval_set.py \
        ingredients/tests/test_mapping_eval.py \
        ingredients/src/ingredients/cli.py
git commit -m "add mapper eval set + --review CLI wiring"
```

---

### Task 22: End-to-end Phase 1 + Phase 2 DB integration test

A single happy-path test that exercises Phase 1 then Phase 2 with a stub provider, against a fresh fixture-seeded DB. Catches integration regressions across the whole mapper.

**Files:**
- Create: `ingredients/tests/test_mapping_end_to_end.py`

- [ ] **Step 1: Write the integration test**

```python
# ingredients/tests/test_mapping_end_to_end.py
"""Phase 1 + Phase 2 happy path against the fixture taxonomy."""

from __future__ import annotations

import psycopg

from ingredients.mapping.llm_provider import ProviderResult
from ingredients.mapping.llm_resolver import run_phase2
from ingredients.mapping.mapper import run_phase1


class StubProvider:
    def __init__(self, responses: dict[str, str]) -> None:
        self.responses = responses
        self.model_id = "stub-1"

    def resolve(self, *, system_prompt: str, user_prompt: str) -> ProviderResult:
        for name, reply in self.responses.items():
            if f'"name": "{name}"' in user_prompt:
                return ProviderResult(raw_text=reply, model_id=self.model_id)
        raise AssertionError(f"no stub for: {user_prompt[:200]}")


def _seed_recipes(conn: psycopg.Connection) -> int:
    conn.execute("truncate table recipe_ingredients, recipes restart identity cascade")
    rid = conn.execute(
        "insert into recipes (site, source_url, jsonld) values ('punch', 'https://example.com/end', '{}'::jsonb) returning id"
    ).fetchone()[0]
    rows = [
        (rid, 0, "2 oz gin",                  "gin"),
        (rid, 1, "1 oz lemon juicee",         "lemon juicee"),       # lexical
        (rid, 2, "0.5 oz bombay sapphire",    "bombay sapphire"),    # phase 2 brand auto-create
        (rid, 3, "1 dash lemon zest",         "lemon zest"),         # phase 2 form proposal
        (rid, 4, "1 oz mystery spirit",       "mystery spirit"),     # phase 2 abstain
    ]
    for _, pos, raw, name in rows:
        conn.execute(
            "insert into recipe_ingredients "
            "(recipe_id, position, raw_text, name, parse_status, parser_rule, parser_version) "
            "values (%s,%s,%s,%s,'parsed','qty_unit','v1')",
            (rid, pos, raw, name),
        )
    conn.commit()
    return rid


def test_full_pipeline_against_fixture(fixture_taxonomy):
    conn, ids = fixture_taxonomy
    _seed_recipes(conn)

    p1 = run_phase1(conn)
    assert p1["alias"] == 1            # gin
    assert p1["lexical"] == 1          # lemon juicee
    assert p1["pending_llm"] == 3      # bombay sapphire, lemon zest, mystery spirit

    provider = StubProvider({
        "bombay sapphire": (
            '{"action": "propose_brand", "slug": "bombay_sapphire", '
            '"display_name": "Bombay Sapphire", "parent_slug": "london_dry_gin", '
            '"role": "brand"}'
        ),
        "lemon zest": (
            '{"action": "propose_form", "slug": "lemon_zest", '
            '"display_name": "Lemon Zest", "parent_slug": "lemon"}'
        ),
        "mystery spirit": '{"action": "abstain"}',
    })
    p2 = run_phase2(conn, provider=provider)
    assert p2 == {"propose_brand": 1, "propose_form": 1, "abstain": 1}

    final = conn.execute(
        "select lower(trim(name)), mapper_source, taxonomy_node_id is null "
        "from recipe_ingredients order by position"
    ).fetchall()
    assert final == [
        ("gin",             "alias",       False),
        ("lemon juicee",    "lexical",     False),
        ("bombay sapphire", "llm",         False),
        ("lemon zest",      "pending_llm", True),     # awaiting human review
        ("mystery spirit",  "abstain",     True),
    ]

    # Auto-created brand exists with provenance.
    new_node = conn.execute(
        "select id from taxonomy_nodes where slug = 'bombay_sapphire'"
    ).fetchone()
    assert new_node is not None
    prov = conn.execute(
        "select source from taxonomy_provenance where node_id = %s", (new_node[0],),
    ).fetchone()
    assert prov == ("llm-mapper",)

    # Form proposal queued.
    proposals = conn.execute(
        "select raw_string, status from taxonomy_proposals"
    ).fetchall()
    assert proposals == [("lemon zest", "pending")]
```

- [ ] **Step 2: Run it**

```bash
cd ingredients && uv run pytest tests/test_mapping_end_to_end.py -q
```

Expected: 1 passed.

- [ ] **Step 3: Run the entire test suite to catch regressions**

```bash
cd ingredients && uv run pytest -q
```

Expected: all green (pre-existing parser tests + every mapping test).

- [ ] **Step 4: Commit**

```bash
git add ingredients/tests/test_mapping_end_to_end.py
git commit -m "add end-to-end Phase 1 + Phase 2 integration test"
```

---

### Task 23: Documentation — CLAUDE.md mapper section + roadmap status bump

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/future-direction.md`

- [ ] **Step 1: Add the Mapper section to CLAUDE.md**

In `CLAUDE.md`, immediately after the `## Ingredient Parser` section, insert:

```markdown
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

The eval set is `ingredients/src/ingredients/mapping/eval_set.py`, run against the fixture taxonomy in `ingredients/tests/fixtures/taxonomy_fixture.py` so eval results don't drift with seed changes.

`ANTHROPIC_API_KEY` is required for `--provider claude`; `OLLAMA_BASE_URL` defaults to `http://localhost:11434` for `--provider ollama`.
```

- [ ] **Step 2: Update the Pipeline conventions table in CLAUDE.md**

In the `## Pipeline conventions` section's table, append a row:

```markdown
| Ingredient → taxonomy mapping | `MAPPER_VERSION` | [mapping/mapper.py](ingredients/src/ingredients/mapping/mapper.py) |
```

- [ ] **Step 3: Bump roadmap status in `docs/future-direction.md`**

Find the `## Status` block. Append `[D]` to the completed list:

```markdown
- **Completed** [A], [B], [C], [D]
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md docs/future-direction.md
git commit -m "docs: add mapper section to CLAUDE.md, mark [D] complete"
```

---

## Wrap-up: final test run

After all tasks land, the final state should pass:

```bash
cd ingredients && uv run pytest -q
```

with all parser tests (pre-existing) and every new mapping test green.

The first end-to-end production run on the real corpus (Phase 1 against `recipes` in Supabase, then `resolve-pending --provider claude` to drain the queue) is gated on enough taxonomy seed coverage to make eval pass against production data — see the spec's *Prerequisite* section.
