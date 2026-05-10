# Park LLM-batch failures Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the chunked Phase-2 drain (mapping + dedup) from re-submitting names that fail to clear, both within a single run and across runs. Operator gets a `retry-failures` command to unpark when the underlying blocker is resolved.

**Architecture:** Add a new state value `pending_llm_tried` to `recipe_ingredients.mapper_source` and `recipes.canonical_name_source`. After each chunk's ingest, bulk-flip any name still at `pending_llm` to `pending_llm_tried`. The existing drain queries naturally exclude parked rows. A new `retry-failures` CLI subcommand bulk-flips `pending_llm_tried` back to `pending_llm`.

**Tech Stack:** Python 3.11+ (uv), psycopg, pytest, Postgres (Supabase). All work happens in the `ingredients/` package and one new `supabase/migrations/` file. Branch: `claude/batch-ingest-hardening-9b3a`.

**Spec:** [docs/superpowers/specs/2026-05-09-park-llm-failures-design.md](../specs/2026-05-09-park-llm-failures-design.md)

---

## File Structure

| File | Purpose | Action |
|---|---|---|
| `supabase/migrations/<ts>_park_llm_tried.sql` | Extend two CHECK constraints | Create |
| `ingredients/src/ingredients/mapping/types.py` | Extend `MapperSource` literal | Modify |
| `ingredients/src/ingredients/mapping/db.py` | `park_attempted_names`, `unpark_failures` | Modify |
| `ingredients/src/ingredients/mapping/llm_resolver.py` | `submit_phase2_batch` returns submitted names | Modify |
| `ingredients/src/ingredients/dedup/types.py` | Extend `NormalizerSource` literal | Modify |
| `ingredients/src/ingredients/dedup/db.py` | `park_attempted_names`, `unpark_failures` (parallel to mapping) | Modify |
| `ingredients/src/ingredients/dedup/normalizer_llm.py` | `submit_normalize_names_batch` returns submitted names | Modify |
| `common/src/common/llm/batch_runner.py` | Extend `BatchSubmitOutcome` with `submitted_names` | Modify |
| `ingredients/src/ingredients/cli.py` | Wire parking into both drain loops; add `retry-failures` subparsers + handlers | Modify |
| `ingredients/tests/test_mapping_resolve_pending_batch.py` | Add parking tests to existing file | Modify |
| `ingredients/tests/test_normalize_names_resolve_pending_batch.py` | Add parking tests to existing file | Modify |
| `ingredients/tests/test_mapping_retry_failures.py` | New file: tests for `map retry-failures` | Create |
| `ingredients/tests/test_normalize_names_retry_failures.py` | New file: tests for `normalize-names retry-failures` | Create |
| `CLAUDE.md` | Document new states + `retry-failures` commands | Modify |

---

## Reference: codebase context

**State enums** ([mapping/types.py:11](../../ingredients/src/ingredients/mapping/types.py#L11), [dedup/types.py:14](../../ingredients/src/ingredients/dedup/types.py#L14)):
```python
MapperSource     = Literal["alias", "lexical", "pending_llm", "llm", "abstain"]
NormalizerSource = Literal["alias", "lexical", "pending_llm", "llm", "abstain"]
```

**Drain queries** today ([mapping/db.py:147-161](../../ingredients/src/ingredients/mapping/db.py#L147), [dedup/db.py:52-67](../../ingredients/src/ingredients/dedup/db.py#L52)):
```sql
-- mapping
select distinct lower(trim(name)) as n
from recipe_ingredients
where mapper_source = 'pending_llm' and mapper_version = %s
order by n
[ limit %s ]

-- dedup
select distinct name from recipes
where canonical_name_source = 'pending_llm'
  and normalizer_version = %s
order by name
[ limit %s ]
```
These are **already correct** for the post-fix world: they filter on `'pending_llm'` exactly, so parked rows at `'pending_llm_tried'` get excluded for free. **Do not change them.**

**Drain loops** ([cli.py:501](../../ingredients/src/ingredients/cli.py#L501) `_drain_mapping_in_chunks`, [cli.py:682](../../ingredients/src/ingredients/cli.py#L682) `_drain_dedup_in_chunks`): identical shape, fetch → submit → poll → ingest, looping until `if not remaining: break`.

**`BatchSubmitOutcome`** ([common/src/common/llm/batch_runner.py:34](../../common/src/common/llm/batch_runner.py#L34)):
```python
@dataclass(frozen=True)
class BatchSubmitOutcome:
    submission: BatchSubmission
    sidecar_path: Path
```

**MAPPER_VERSION / NORMALIZER_VERSION**: defined in `ingredients/src/ingredients/mapping/mapper.py` and `ingredients/src/ingredients/dedup/version.py`. Import as `from ingredients.mapping.mapper import MAPPER_VERSION` etc.

**Test DB**: `TEST_DB_URL` env var. The `ingredients/conftest.py` auto-creates `spiritolo_test` and applies new `supabase/migrations/*.sql` on session start. To run a single test with the test DB: `cd ingredients && uv run pytest tests/test_X.py::test_Y -v`.

**Pre-flight commands** (read before implementing each task):
```bash
# What branch are we on?
git status

# Have the existing tests pass first?
cd ingredients && uv run pytest -x
```

---

## Task 1: Migration — extend check constraints

**Files:**
- Create: `supabase/migrations/<YYYYMMDDHHMMSS>_park_llm_tried.sql`

The migration filename uses today's UTC date with a fresh timestamp. Pick a timestamp later than the most recent existing migration:

```bash
ls supabase/migrations/ | sort | tail -5
date -u +%Y%m%d%H%M%S
```

- [ ] **Step 1: Create the migration file**

Filename pattern: `supabase/migrations/<YYYYMMDDHHMMSS>_park_llm_tried.sql` (replace timestamp). Content:

```sql
-- Park LLM-batch failures: add 'pending_llm_tried' to mapper_source and
-- canonical_name_source so the chunked Phase-2 drain stops re-submitting
-- names that consistently fail. Operator runs `map retry-failures` /
-- `normalize-names retry-failures` to unpark.

alter table recipe_ingredients
  drop constraint recipe_ingredients_mapper_source_check;

alter table recipe_ingredients
  add constraint recipe_ingredients_mapper_source_check
  check (mapper_source in
    ('alias', 'lexical', 'pending_llm', 'pending_llm_tried',
     'llm', 'abstain'));

alter table recipes
  drop constraint recipes_canonical_name_source_check;

alter table recipes
  add constraint recipes_canonical_name_source_check
  check (canonical_name_source in
    ('alias', 'lexical', 'pending_llm', 'pending_llm_tried',
     'llm', 'abstain'));
```

- [ ] **Step 2: Verify the constraint names**

Postgres autogenerates check-constraint names as `<table>_<column>_check` by default, but if either was created with a custom name we'd need that name. Verify against the local DB before applying:

```bash
psql "$SUPABASE_DB_URL" -c "
  select conname, conrelid::regclass, pg_get_constraintdef(oid)
  from pg_constraint
  where conrelid in ('recipe_ingredients'::regclass, 'recipes'::regclass)
    and contype = 'c'
    and pg_get_constraintdef(oid) like '%pending_llm%';
"
```

If the actual constraint names differ from the assumed `recipe_ingredients_mapper_source_check` / `recipes_canonical_name_source_check`, update the `drop constraint` lines in the migration to match. (If `SUPABASE_DB_URL` isn't reachable from your environment, ask the human to run the query and report back.)

- [ ] **Step 3: Apply the migration to the test DB and verify**

```bash
cd ingredients && uv run pytest tests/test_db.py -v
```

The conftest auto-applies new migrations before tests run. If the migration fails to apply, the conftest will fail loudly and abort the test session — fix the migration and re-run.

To verify by hand against `TEST_DB_URL`:

```bash
psql "$TEST_DB_URL" -c "
  insert into recipes (source_url, site, name, canonical_name_source)
  values ('test://1', 'test', 't', 'pending_llm_tried')
  returning id;
"
psql "$TEST_DB_URL" -c "delete from recipes where source_url = 'test://1';"
```

The INSERT must succeed. If it fails with a check-constraint violation, the migration didn't apply correctly.

- [ ] **Step 4: Apply the migration to the local Supabase dev DB**

The local Supabase host runs on the Mac, not in the devcontainer (per CLAUDE.md). Run:

```bash
# From the Mac host:
supabase migration up --include-all
```

If you can't run `supabase` from the Mac host yourself (e.g., you're inside the devcontainer), call this out in the task report and ask the human to run it. The migration is forward-compatible and idempotent in spirit (re-creating the constraint with the superset is safe), so the human can apply it any time before running the new code.

- [ ] **Step 5: Commit**

```bash
git add supabase/migrations/<filename>.sql
git commit -m "$(cat <<'EOF'
Migration: extend mapper_source / canonical_name_source with pending_llm_tried

New value 'pending_llm_tried' lets the chunked Phase-2 drain park names
that didn't clear (propose_form, parse failure, transient provider error,
etc.) so they don't get re-submitted every chunk and every run. Operator
runs `map retry-failures` / `normalize-names retry-failures` to unpark
after resolving the underlying blocker.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Extend BatchSubmitOutcome with submitted_names

**Files:**
- Modify: `common/src/common/llm/batch_runner.py:34-37`
- Modify: `ingredients/src/ingredients/mapping/llm_resolver.py:255-317` (`submit_phase2_batch`)
- Modify: `ingredients/src/ingredients/dedup/normalizer_llm.py:113-152` (`submit_normalize_names_batch`)
- Test: `common/tests/test_batch_runner.py`

The drain loop needs to know which names a chunk submitted so it can park the stuck ones afterwards. Today `submit_phase2_batch` re-queries internally and returns only `BatchSubmitOutcome(submission, sidecar_path)`. Extend the dataclass and populate the new field from both `submit_*_batch` functions.

- [ ] **Step 1: Read `common/src/common/llm/batch_runner.py:34-68`**

This is the existing `BatchSubmitOutcome` and `submit_batch`. The flow-agnostic `submit_batch` is *not* the place to populate names — the names are flow-specific (mapping passes the normalized name as `row[0]`; dedup passes the raw recipe name as `row[0]`). The right place is the per-flow caller (`submit_phase2_batch`, `submit_normalize_names_batch`) — they already build `names` (mapping) or `raw_names` (dedup) before calling `submit_batch`, and they construct the returned `BatchSubmitOutcome`.

- [ ] **Step 2: Extend the dataclass**

Edit `common/src/common/llm/batch_runner.py:34-37`:

```python
@dataclass(frozen=True)
class BatchSubmitOutcome:
    submission: BatchSubmission
    sidecar_path: Path
    submitted_names: tuple[str, ...] = ()  # row identities sent in this batch
```

Default `()` keeps existing call-sites that construct `BatchSubmitOutcome` directly (only `submit_batch` itself, plus any test mocks) backward-compatible — they just won't populate the field. The drain-loop reader needs to handle the empty case (treat as "no parking to do").

- [ ] **Step 3: Update `submit_batch` to pass through the row IDs**

Edit `common/src/common/llm/batch_runner.py:67-68`:

```python
    path = write_sidecar(sc, batches_dir=batches_dir)
    return BatchSubmitOutcome(
        submission=submission, sidecar_path=path,
        submitted_names=tuple(request_map.values()),
    )
```

`request_map.values()` is the sequence of `row_to_id(row)` for every submitted row — exactly the identities the caller cares about for parking. Casting to `tuple` matches the frozen-dataclass convention.

- [ ] **Step 4: Add a test for the new field**

Add to `common/tests/test_batch_runner.py` (locate the existing test for `submit_batch` and add this near it):

```python
def test_submit_batch_returns_submitted_names():
    """BatchSubmitOutcome.submitted_names exposes row IDs in submit order
    so the caller can drive post-ingest bookkeeping (e.g. parking failures)
    without re-loading the sidecar."""
    from common.llm.batch_runner import submit_batch
    from common.llm.batch_provider import BatchRequest, BatchSubmission
    from pathlib import Path
    from unittest.mock import MagicMock

    rows = [("alpha", "sys", "u1"), ("beta", "sys", "u2"), ("gamma", "sys", "u3")]
    provider = MagicMock()
    provider.submit.return_value = BatchSubmission(
        batch_id="b1", provider="openai",
        model_id="gpt-5-mini", request_count=3,
    )

    outcome = submit_batch(
        provider=provider, rows=rows,
        to_request=lambda i, r: BatchRequest(
            custom_id=f"r{i}", system_prompt=r[1], user_prompt=r[2],
        ),
        row_to_id=lambda r: r[0],
        flow="test_flow",
        version_constant="vtest",
        batches_dir=Path("/tmp"),
    )
    assert outcome.submitted_names == ("alpha", "beta", "gamma")
```

- [ ] **Step 5: Run the new test, expect it to pass after Step 3**

```bash
cd common && uv run pytest tests/test_batch_runner.py::test_submit_batch_returns_submitted_names -v
```

Expected: PASS. (If the file uses a different path-import shape — check `cd common && uv run pytest tests/test_batch_runner.py -v` to see existing patterns.)

- [ ] **Step 6: Run the full common-tests suite to confirm no regressions**

```bash
cd common && uv run pytest -x
```

Expected: all green.

- [ ] **Step 7: Run the ingredients suite to confirm no regression**

```bash
cd ingredients && uv run pytest -x
```

Expected: all green. (Some tests construct `BatchSubmitOutcome` mocks; the default-`()` field keeps them working.)

- [ ] **Step 8: Commit**

```bash
git add common/src/common/llm/batch_runner.py common/tests/test_batch_runner.py
git commit -m "$(cat <<'EOF'
batch_runner: expose submitted row IDs on BatchSubmitOutcome

Drain loops need to know which names a chunk submitted so they can park
the stuck ones after ingest without re-loading the sidecar. Defaulting
to () keeps existing mock construction sites backward-compatible.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Mapping db helpers — park_attempted_names + unpark_failures

**Files:**
- Modify: `ingredients/src/ingredients/mapping/types.py:11`
- Modify: `ingredients/src/ingredients/mapping/db.py` (append two new functions)
- Test: `ingredients/tests/test_mapping_db_park.py` (new file)

- [ ] **Step 1: Extend the `MapperSource` literal**

Edit `ingredients/src/ingredients/mapping/types.py:11`:

```python
MapperSource = Literal[
    "alias", "lexical", "pending_llm", "pending_llm_tried", "llm", "abstain",
]
```

- [ ] **Step 2: Write the failing tests**

Create `ingredients/tests/test_mapping_db_park.py`:

```python
"""DB-integration tests for park_attempted_names / unpark_failures.
Runs against TEST_DB_URL (the conftest fixture provides `db_conn`)."""

from __future__ import annotations

import pytest

from ingredients.mapping.db import (
    park_attempted_names, unpark_failures,
)


def _seed_recipe_ingredient(conn, *, name, mapper_source, mapper_version):
    """Insert a recipe + a single recipe_ingredients row at the requested
    state. Returns the recipe_ingredients id."""
    rec_id = conn.execute(
        """
        insert into recipes (source_url, site, name)
        values (%s, 'test', %s)
        returning id
        """,
        (f"test://{name}/{mapper_version}/{mapper_source}", name),
    ).fetchone()[0]
    ri_id = conn.execute(
        """
        insert into recipe_ingredients
            (recipe_id, position, raw_text, name,
             parse_status, mapper_source, mapper_version, mapper_at)
        values (%s, 0, %s, %s, 'parsed', %s, %s, now())
        returning id
        """,
        (rec_id, name, name, mapper_source, mapper_version),
    ).fetchone()[0]
    conn.commit()
    return ri_id


def test_park_flips_pending_to_pending_tried(db_conn):
    """A row at mapper_source='pending_llm' for the given version flips
    to 'pending_llm_tried' when its name is in the parking list."""
    rid = _seed_recipe_ingredient(
        db_conn, name="lemon juice",
        mapper_source="pending_llm", mapper_version="v1",
    )

    n = park_attempted_names(
        db_conn, mapper_version="v1", names=["lemon juice"],
    )
    db_conn.commit()
    assert n == 1

    src = db_conn.execute(
        "select mapper_source from recipe_ingredients where id = %s", (rid,),
    ).fetchone()[0]
    assert src == "pending_llm_tried"


def test_park_skips_already_resolved(db_conn):
    """A row that has been moved off pending_llm (e.g. to 'llm' or
    'abstain') by the ingest is not touched by parking, even if its
    normalized name appears in the parking list."""
    rid = _seed_recipe_ingredient(
        db_conn, name="dry vermouth",
        mapper_source="llm", mapper_version="v1",
    )

    park_attempted_names(db_conn, mapper_version="v1", names=["dry vermouth"])
    db_conn.commit()

    src = db_conn.execute(
        "select mapper_source from recipe_ingredients where id = %s", (rid,),
    ).fetchone()[0]
    assert src == "llm"


def test_park_respects_version(db_conn):
    """A row at pending_llm but at a *different* mapper_version is not
    touched."""
    rid = _seed_recipe_ingredient(
        db_conn, name="campari",
        mapper_source="pending_llm", mapper_version="v0",
    )
    park_attempted_names(db_conn, mapper_version="v1", names=["campari"])
    db_conn.commit()
    src = db_conn.execute(
        "select mapper_source from recipe_ingredients where id = %s", (rid,),
    ).fetchone()[0]
    assert src == "pending_llm"


def test_park_handles_empty_names(db_conn):
    """Empty names list is a no-op, returns 0, does not touch the DB."""
    n = park_attempted_names(db_conn, mapper_version="v1", names=[])
    assert n == 0


def test_unpark_flips_back(db_conn):
    """unpark_failures flips pending_llm_tried rows at the given version
    back to pending_llm."""
    rid = _seed_recipe_ingredient(
        db_conn, name="orgeat",
        mapper_source="pending_llm_tried", mapper_version="v1",
    )
    n = unpark_failures(db_conn, mapper_version="v1")
    db_conn.commit()
    assert n == 1
    src = db_conn.execute(
        "select mapper_source from recipe_ingredients where id = %s", (rid,),
    ).fetchone()[0]
    assert src == "pending_llm"


def test_unpark_respects_version(db_conn):
    """unpark_failures does not touch rows at a different mapper_version."""
    rid = _seed_recipe_ingredient(
        db_conn, name="falernum",
        mapper_source="pending_llm_tried", mapper_version="v0",
    )
    n = unpark_failures(db_conn, mapper_version="v1")
    db_conn.commit()
    assert n == 0
    src = db_conn.execute(
        "select mapper_source from recipe_ingredients where id = %s", (rid,),
    ).fetchone()[0]
    assert src == "pending_llm_tried"


def test_unpark_with_limit(db_conn):
    """unpark_failures(limit=N) flips at most N rows."""
    for n in ("a-name", "b-name", "c-name"):
        _seed_recipe_ingredient(
            db_conn, name=n,
            mapper_source="pending_llm_tried", mapper_version="v1",
        )
    rc = unpark_failures(db_conn, mapper_version="v1", limit=2)
    db_conn.commit()
    assert rc == 2
    remaining = db_conn.execute(
        "select count(*) from recipe_ingredients "
        "where mapper_source = 'pending_llm_tried' and mapper_version = %s",
        ("v1",),
    ).fetchone()[0]
    assert remaining == 1
```

The `db_conn` fixture comes from `ingredients/conftest.py` — it provides a clean psycopg connection against `TEST_DB_URL`. Verify by skimming `ingredients/conftest.py` if needed; if the fixture has a different name (e.g., `conn` or `pgconn`), use that name and update the test.

- [ ] **Step 3: Run the failing tests, expect failures**

```bash
cd ingredients && uv run pytest tests/test_mapping_db_park.py -v
```

Expected: ImportError or AttributeError on `park_attempted_names` / `unpark_failures` (not yet defined).

- [ ] **Step 4: Implement the helpers**

Append to `ingredients/src/ingredients/mapping/db.py`:

```python
def park_attempted_names(
    conn: psycopg.Connection, *, mapper_version: str, names: list[str],
) -> int:
    """Flip recipe_ingredients rows from 'pending_llm' to
    'pending_llm_tried' for the given mapper_version, restricted to rows
    whose normalized name is in `names`. Caller commits.

    Used by the chunked Phase-2 drain after each chunk's ingest: names
    that did not get a clearing action ('chose' or 'abstain') stay at
    'pending_llm' and would otherwise re-appear in the next chunk's
    fetch_pending_llm_names. Parking them excludes them from the queue
    until a version bump or `map retry-failures` resurrects them.

    Returns rowcount (informational; can be > len(names) when one name
    has many recipe_ingredients rows)."""
    if not names:
        return 0
    cur = conn.execute(
        """
        update recipe_ingredients
           set mapper_source = 'pending_llm_tried'
         where mapper_version = %s
           and mapper_source  = 'pending_llm'
           and lower(trim(name)) = any(%s::text[])
        """,
        (mapper_version, names),
    )
    return cur.rowcount


def unpark_failures(
    conn: psycopg.Connection, *, mapper_version: str, limit: int | None = None,
) -> int:
    """Flip 'pending_llm_tried' rows at the given mapper_version back to
    'pending_llm' so the next `map resolve-pending` re-submits them.
    Caller commits.

    With `limit=N`, flips at most N rows (selected by id, no ordering
    guarantees beyond Postgres's default). Without `limit`, flips
    everything at the version. Returns rowcount."""
    if limit is None:
        cur = conn.execute(
            """
            update recipe_ingredients
               set mapper_source = 'pending_llm'
             where mapper_version = %s
               and mapper_source  = 'pending_llm_tried'
            """,
            (mapper_version,),
        )
    else:
        cur = conn.execute(
            """
            update recipe_ingredients
               set mapper_source = 'pending_llm'
             where id in (
                 select id from recipe_ingredients
                  where mapper_version = %s
                    and mapper_source  = 'pending_llm_tried'
                  limit %s
             )
            """,
            (mapper_version, limit),
        )
    return cur.rowcount
```

- [ ] **Step 5: Run the tests, expect them to pass**

```bash
cd ingredients && uv run pytest tests/test_mapping_db_park.py -v
```

Expected: 7/7 passing.

- [ ] **Step 6: Run the full mapping suite, no regressions**

```bash
cd ingredients && uv run pytest tests/ -k mapping -v
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add ingredients/src/ingredients/mapping/types.py \
        ingredients/src/ingredients/mapping/db.py \
        ingredients/tests/test_mapping_db_park.py
git commit -m "$(cat <<'EOF'
Mapping: park_attempted_names + unpark_failures

Helpers for the chunked Phase-2 drain to park names that didn't clear,
and for the new `map retry-failures` CLI to unpark them after the
underlying blocker is resolved. Both keyed by mapper_version so a
version bump (which deletes old-version rows) implicitly clears the
parked state.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Wire mapping drain parking + add `map retry-failures` CLI

**Files:**
- Modify: `ingredients/src/ingredients/mapping/llm_resolver.py:255-317` (`submit_phase2_batch`)
- Modify: `ingredients/src/ingredients/cli.py:501-630` (`_drain_mapping_in_chunks`)
- Modify: `ingredients/src/ingredients/cli.py` (add `retry-failures` subparser under `map_sub` near line ~171)
- Modify: `ingredients/src/ingredients/cli.py` (`run_map` dispatcher near line ~877)
- Test: `ingredients/tests/test_mapping_resolve_pending_batch.py` (extend with parking test)
- Test: `ingredients/tests/test_mapping_retry_failures.py` (new)

- [ ] **Step 1: Update `submit_phase2_batch` to populate `submitted_names` on its return**

Find `submit_phase2_batch` in `ingredients/src/ingredients/mapping/llm_resolver.py:255`. The function already builds `names` (line 268) and ends with `return submit_batch(...)` (line 308). The `submit_batch` function (modified in Task 2) now returns a `BatchSubmitOutcome` with `submitted_names` populated from `request_map.values()`, which equals `names` because `row_to_id=lambda r: r[0]` and `r[0]` is the name.

**No code change needed in `submit_phase2_batch` itself** — the new field already gets populated by `submit_batch`. Verify by reading the function and confirming `row_to_id=lambda r: r[0]` is unchanged.

- [ ] **Step 2: Write the failing parking test**

Add to `ingredients/tests/test_mapping_resolve_pending_batch.py` (near the existing `test_run_all_drains_queue_in_chunks`):

```python
def test_drain_parks_stuck_names(tmp_path, monkeypatch):
    """A chunk whose ingest leaves a name at pending_llm (e.g. propose_form)
    parks that name to pending_llm_tried after ingest, so it doesn't appear
    in the next iteration's fetch_pending_llm_names. The drain then exits."""
    from ingredients.cli import _drain_mapping_in_chunks
    from common.llm.batch_provider import BatchResult, BatchStatus, BatchSubmission

    # Two pending names; only "good" gets cleared. "stuck" stays at pending_llm
    # and must be parked.
    pending = ["good", "stuck"]
    parked: list[str] = []

    def _fetch(conn, mapper_version, limit=None):
        # The fetch query naturally excludes parked names.
        live = [n for n in pending if n not in parked]
        return live[:limit] if limit else list(live)

    monkeypatch.setattr(
        "ingredients.mapping.llm_resolver.fetch_pending_llm_names", _fetch,
    )
    monkeypatch.setattr(
        "ingredients.mapping.db.fetch_pending_llm_names", _fetch,
    )
    monkeypatch.setattr(
        "ingredients.mapping.llm_resolver._candidates_with_parents",
        lambda c, n: [],
    )
    monkeypatch.setattr(
        "ingredients.mapping.lexical_layer.bulk_lexical_candidates",
        lambda conn, names, limit=20: {n: [] for n in names},
    )

    # Simulate ingest: "good" gets a chose write (clears it from queue);
    # "stuck" gets a propose_form (no DB write at all here).
    def _write_resolution(conn, normalized_name, taxonomy_node_id, source, mapper_version):
        if normalized_name in pending:
            pending.remove(normalized_name)
    monkeypatch.setattr(
        "ingredients.mapping.llm_resolver.write_resolution", _write_resolution,
    )
    monkeypatch.setattr(
        "ingredients.mapping.llm_resolver.enqueue_form_proposal",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr(
        "ingredients.mapping.llm_resolver._lookup_node_by_slug",
        lambda c, s: 1,
    )

    # park_attempted_names: record what was parked.
    def _park(conn, mapper_version, names):
        for n in names:
            if n in pending and n not in parked:
                parked.append(n)
        return len(names)
    monkeypatch.setattr(
        "ingredients.mapping.db.park_attempted_names", _park,
    )

    submit_calls: list[int] = []
    def _submit(requests):
        reqs = list(requests)
        submit_calls.append(len(reqs))
        return BatchSubmission(
            batch_id=f"b{len(submit_calls)}", provider="openai",
            model_id="gpt-5-mini", request_count=len(reqs),
        )
    provider = MagicMock()
    provider.model_id = "gpt-5-mini"
    provider.submit.side_effect = _submit
    provider.status.side_effect = lambda bid: BatchStatus(
        batch_id=bid, state="completed", completed=2, total=2,
    )

    from common.llm.sidecar import load_sidecar
    def _fetch_results(batch_id):
        sc = load_sidecar(batch_id, batches_dir=tmp_path)
        # Map the two custom_ids to chose vs propose_form.
        out = []
        for cid, name in sc.request_map.items():
            if name == "good":
                out.append(BatchResult(
                    custom_id=cid,
                    raw_text='{"action": "chose", "node_id": 1}',
                    error=None,
                ))
            else:
                out.append(BatchResult(
                    custom_id=cid,
                    raw_text='{"action": "propose_form", "slug": "x", '
                             '"display_name": "X", "parent_slug": "p"}',
                    error=None,
                ))
        return iter(out)
    provider.fetch_results.side_effect = _fetch_results

    db = MagicMock()
    db.conn = MagicMock()
    rc = _drain_mapping_in_chunks(
        db, provider, tmp_path,
        chunk_size=10, total_limit=None, poll_interval=0,
    )
    assert rc == 0
    # Exactly one chunk submitted (the second iteration finds queue empty
    # because "stuck" was parked).
    assert submit_calls == [2]
    assert parked == ["stuck"]
```

- [ ] **Step 3: Run the test, expect failure**

```bash
cd ingredients && uv run pytest tests/test_mapping_resolve_pending_batch.py::test_drain_parks_stuck_names -v
```

Expected: failure — either `submit_calls` has 2+ entries (loop didn't terminate because parking isn't happening) or `parked` is empty.

- [ ] **Step 4: Wire parking into `_drain_mapping_in_chunks`**

Edit `ingredients/src/ingredients/cli.py` — find `_drain_mapping_in_chunks` (around line 501). Two changes:

(a) Add `park_attempted_names` import alongside the existing imports inside the function (around line 516-521):

```python
    from ingredients.mapping.db import (
        fetch_pending_llm_names, park_attempted_names,
    )
```

(b) After the ingest block (around line 624, after `log.info("chunk %d ingested: ...")`), call park:

```python
            # Park names that didn't clear ('propose_form', parse error,
            # provider error, etc.) so they don't reappear in the next
            # chunk or the next run. Operator runs `map retry-failures`
            # to unpark after resolving the underlying blocker.
            stuck = park_attempted_names(
                db.conn, mapper_version=MAPPER_VERSION,
                names=list(outcome.submitted_names),
            )
            db.conn.commit()
            if stuck:
                aggregate_counts["parked"] = aggregate_counts.get("parked", 0) + stuck
                log.info("chunk %d parked %d stuck names as pending_llm_tried",
                         chunk_idx, stuck)
```

The `aggregate_counts` map already collects per-key counts; adding a `parked` key surfaces it in the final summary print without bespoke wiring.

- [ ] **Step 5: Update the run-summary log line**

Edit the `print_summary(...)` call at the end of `_drain_mapping_in_chunks` (around line 627-630). Before the print, add a one-liner if any names were parked across the whole run:

```python
    parked_total = aggregate_counts.get("parked", 0)
    if parked_total:
        log.info(
            "parked %d names as pending_llm_tried "
            "(run 'map retry-failures' to retry)",
            parked_total,
        )
    print_summary(
        f"Map resolve-pending ({chunk_idx} chunks, {drained} drained)",
        {"all": aggregate_counts}, mode="applied",
    )
```

- [ ] **Step 6: Run the test, expect it to pass**

```bash
cd ingredients && uv run pytest tests/test_mapping_resolve_pending_batch.py::test_drain_parks_stuck_names -v
```

Expected: PASS.

- [ ] **Step 7: Run the existing drain tests, no regressions**

```bash
cd ingredients && uv run pytest tests/test_mapping_resolve_pending_batch.py -v
```

Expected: all green. The existing `test_run_all_drains_queue_in_chunks` may need a tiny update: it monkeypatches `fetch_pending_llm_names` (in two places) and removes names from `pending` as `_write_resolution` fires. The new parking call also tries to update `mapper_source`, but on a `MagicMock` `db.conn`, the call is just a no-op-ish mock invocation. If the test fails because `aggregate_counts.get("parked", 0)` is now nonzero from a mock returning nonzero, fix the test by also monkeypatching `park_attempted_names` to return 0.

- [ ] **Step 8: Add `retry-failures` subparser under `map`**

Find the `map` subparser block in `ingredients/src/ingredients/cli.py` (around line 100-179). The structure is:
```python
p_map = sub.add_parser("map", ...)
map_sub = p_map.add_subparsers(dest="map_cmd")
p_resolve = map_sub.add_parser("resolve-pending", ...)
...
p_review = map_sub.add_parser("review-proposals", ...)
```

Add another subparser, after `p_review`:

```python
    p_retry = map_sub.add_parser(
        "retry-failures",
        help="Unpark names parked by the chunked drain "
             "(pending_llm_tried -> pending_llm). Run after the "
             "underlying blocker is resolved (form proposal approved, "
             "taxonomy edit landed, etc.).",
    )
    p_retry.add_argument(
        "--limit", type=int, default=None,
        help="Unpark at most N rows (no ordering guarantees).",
    )
    p_retry.add_argument(
        "--yes", action="store_true",
        help="Skip the count-and-confirm prompt.",
    )
```

- [ ] **Step 9: Add the dispatcher branch in `run_map`**

Find `run_map` (around line 877) — its first lines dispatch to subcommands:

```python
def run_map(args: argparse.Namespace) -> int:
    if getattr(args, "map_cmd", None) == "resolve-pending":
        return run_resolve_pending(args)
    if getattr(args, "map_cmd", None) == "review-proposals":
        return run_review_proposals(args)
    ...
```

Add a new branch:

```python
    if getattr(args, "map_cmd", None) == "retry-failures":
        return run_map_retry_failures(args)
```

- [ ] **Step 10: Implement the handler**

Add a new top-level function in `ingredients/src/ingredients/cli.py` (next to the other `run_*` functions, e.g. before `run_resolve_pending`):

```python
def run_map_retry_failures(args: argparse.Namespace) -> int:
    """Unpark Phase-2 failures: flip mapper_source 'pending_llm_tried'
    back to 'pending_llm' for the current MAPPER_VERSION."""
    from ingredients.mapping.db import unpark_failures
    from ingredients.mapping.mapper import MAPPER_VERSION

    db = IngredientsDatabase()
    try:
        # Show current count first.
        n_parked = db.conn.execute(
            """
            select count(*) from recipe_ingredients
            where mapper_source = 'pending_llm_tried'
              and mapper_version = %s
            """,
            (MAPPER_VERSION,),
        ).fetchone()[0]
        if n_parked == 0:
            log.info("nothing parked at mapper_version=%s", MAPPER_VERSION)
            return 0

        cap = (
            min(args.limit, n_parked) if args.limit is not None else n_parked
        )
        log.info("would unpark %d of %d parked rows at mapper_version=%s",
                 cap, n_parked, MAPPER_VERSION)
        if not args.yes:
            sys.stderr.write("Proceed? [y/N]: ")
            sys.stderr.flush()
            answer = sys.stdin.readline().strip().lower()
            if answer not in ("y", "yes"):
                log.info("aborted by operator")
                return 1

        n = unpark_failures(db.conn, mapper_version=MAPPER_VERSION,
                            limit=args.limit)
        db.conn.commit()
        log.info(
            "unparked %d rows; run 'map resolve-pending --provider …' "
            "to re-submit", n,
        )
        return 0
    finally:
        db.close()
```

- [ ] **Step 11: Write the CLI integration test**

Create `ingredients/tests/test_mapping_retry_failures.py`:

```python
"""Integration test for `map retry-failures`. Hits TEST_DB_URL via the
db_conn fixture; constructs argparse.Namespace by hand to bypass parser."""

from __future__ import annotations

import argparse
from unittest.mock import patch


def _seed_parked(conn, *, name, mapper_version):
    rec_id = conn.execute(
        """
        insert into recipes (source_url, site, name)
        values (%s, 'test', %s) returning id
        """,
        (f"test://{name}/{mapper_version}", name),
    ).fetchone()[0]
    conn.execute(
        """
        insert into recipe_ingredients
            (recipe_id, position, raw_text, name, parse_status,
             mapper_source, mapper_version, mapper_at)
        values (%s, 0, %s, %s, 'parsed', 'pending_llm_tried', %s, now())
        """,
        (rec_id, name, name, mapper_version),
    )
    conn.commit()


def test_retry_failures_unparks_at_current_version(db_conn, monkeypatch):
    from ingredients.cli import run_map_retry_failures
    from ingredients.mapping.mapper import MAPPER_VERSION

    _seed_parked(db_conn, name="pisco", mapper_version=MAPPER_VERSION)
    _seed_parked(db_conn, name="batavia arrack", mapper_version=MAPPER_VERSION)

    # Stub IngredientsDatabase to use the test connection.
    class _StubDB:
        def __init__(self):
            self.conn = db_conn
        def close(self):
            pass
    monkeypatch.setattr("ingredients.cli.IngredientsDatabase", _StubDB)

    args = argparse.Namespace(map_cmd="retry-failures", limit=None, yes=True)
    rc = run_map_retry_failures(args)
    assert rc == 0

    n_remaining = db_conn.execute(
        "select count(*) from recipe_ingredients "
        "where mapper_source = 'pending_llm_tried' and mapper_version = %s",
        (MAPPER_VERSION,),
    ).fetchone()[0]
    assert n_remaining == 0
    n_pending = db_conn.execute(
        "select count(*) from recipe_ingredients "
        "where mapper_source = 'pending_llm' and mapper_version = %s "
        "and name in ('pisco', 'batavia arrack')",
        (MAPPER_VERSION,),
    ).fetchone()[0]
    assert n_pending == 2


def test_retry_failures_empty_returns_zero(db_conn, monkeypatch):
    from ingredients.cli import run_map_retry_failures

    class _StubDB:
        def __init__(self):
            self.conn = db_conn
        def close(self):
            pass
    monkeypatch.setattr("ingredients.cli.IngredientsDatabase", _StubDB)

    args = argparse.Namespace(map_cmd="retry-failures", limit=None, yes=True)
    rc = run_map_retry_failures(args)
    assert rc == 0


def test_retry_failures_respects_limit(db_conn, monkeypatch):
    from ingredients.cli import run_map_retry_failures
    from ingredients.mapping.mapper import MAPPER_VERSION

    for n in ("a-rum", "b-rum", "c-rum"):
        _seed_parked(db_conn, name=n, mapper_version=MAPPER_VERSION)

    class _StubDB:
        def __init__(self):
            self.conn = db_conn
        def close(self):
            pass
    monkeypatch.setattr("ingredients.cli.IngredientsDatabase", _StubDB)

    args = argparse.Namespace(map_cmd="retry-failures", limit=2, yes=True)
    rc = run_map_retry_failures(args)
    assert rc == 0

    remaining = db_conn.execute(
        "select count(*) from recipe_ingredients "
        "where mapper_source = 'pending_llm_tried' and mapper_version = %s",
        (MAPPER_VERSION,),
    ).fetchone()[0]
    assert remaining == 1
```

- [ ] **Step 12: Run the test, expect it to pass**

```bash
cd ingredients && uv run pytest tests/test_mapping_retry_failures.py -v
```

Expected: 3/3 passing.

- [ ] **Step 13: Run the full ingredients suite, no regressions**

```bash
cd ingredients && uv run pytest -x
```

Expected: all green.

- [ ] **Step 14: Commit**

```bash
git add ingredients/src/ingredients/cli.py \
        ingredients/tests/test_mapping_resolve_pending_batch.py \
        ingredients/tests/test_mapping_retry_failures.py
git commit -m "$(cat <<'EOF'
Mapping drain: park stuck names + add `map retry-failures`

After each chunk's ingest, names that didn't get a clearing action stay
at mapper_source='pending_llm' and would reappear forever. Now flipped
to 'pending_llm_tried' so the next fetch_pending_llm_names skips them
and the drain terminates.

`map retry-failures` flips them back when the operator has resolved the
underlying blocker (form proposal approved, taxonomy edit, etc.).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Dedup db helpers — park_attempted_names + unpark_failures

**Files:**
- Modify: `ingredients/src/ingredients/dedup/types.py:14`
- Modify: `ingredients/src/ingredients/dedup/db.py` (append two new functions)
- Test: `ingredients/tests/test_dedup_db_park.py` (new file)

Mirror image of Task 3 against `recipes.canonical_name_source`.

- [ ] **Step 1: Extend the `NormalizerSource` literal**

Edit `ingredients/src/ingredients/dedup/types.py:14`:

```python
NormalizerSource = Literal[
    "alias", "lexical", "pending_llm", "pending_llm_tried", "llm", "abstain",
]
```

- [ ] **Step 2: Write the failing tests**

Create `ingredients/tests/test_dedup_db_park.py`:

```python
"""DB-integration tests for dedup's park_attempted_names + unpark_failures."""

from __future__ import annotations

from ingredients.dedup.db import (
    park_attempted_names, unpark_failures,
)


def _seed_recipe(conn, *, name, source, version):
    rec_id = conn.execute(
        """
        insert into recipes
            (source_url, site, name, canonical_name_source,
             normalizer_version, normalized_at)
        values (%s, 'test', %s, %s, %s, now())
        returning id
        """,
        (f"test://{name}/{version}/{source}", name, source, version),
    ).fetchone()[0]
    conn.commit()
    return rec_id


def test_park_flips_pending_to_pending_tried(db_conn):
    rid = _seed_recipe(db_conn, name="negroni", source="pending_llm", version="v1")
    n = park_attempted_names(db_conn, normalizer_version="v1", names=["negroni"])
    db_conn.commit()
    assert n == 1
    src = db_conn.execute(
        "select canonical_name_source from recipes where id = %s", (rid,),
    ).fetchone()[0]
    assert src == "pending_llm_tried"


def test_park_skips_already_resolved(db_conn):
    rid = _seed_recipe(db_conn, name="manhattan", source="llm", version="v1")
    park_attempted_names(db_conn, normalizer_version="v1", names=["manhattan"])
    db_conn.commit()
    src = db_conn.execute(
        "select canonical_name_source from recipes where id = %s", (rid,),
    ).fetchone()[0]
    assert src == "llm"


def test_park_respects_version(db_conn):
    rid = _seed_recipe(db_conn, name="sazerac", source="pending_llm", version="v0")
    park_attempted_names(db_conn, normalizer_version="v1", names=["sazerac"])
    db_conn.commit()
    src = db_conn.execute(
        "select canonical_name_source from recipes where id = %s", (rid,),
    ).fetchone()[0]
    assert src == "pending_llm"


def test_park_handles_empty_names(db_conn):
    n = park_attempted_names(db_conn, normalizer_version="v1", names=[])
    assert n == 0


def test_unpark_flips_back(db_conn):
    rid = _seed_recipe(db_conn, name="last word", source="pending_llm_tried", version="v1")
    n = unpark_failures(db_conn, normalizer_version="v1")
    db_conn.commit()
    assert n == 1
    src = db_conn.execute(
        "select canonical_name_source from recipes where id = %s", (rid,),
    ).fetchone()[0]
    assert src == "pending_llm"


def test_unpark_respects_version(db_conn):
    rid = _seed_recipe(db_conn, name="aviation", source="pending_llm_tried", version="v0")
    n = unpark_failures(db_conn, normalizer_version="v1")
    db_conn.commit()
    assert n == 0
    src = db_conn.execute(
        "select canonical_name_source from recipes where id = %s", (rid,),
    ).fetchone()[0]
    assert src == "pending_llm_tried"


def test_unpark_with_limit(db_conn):
    for n in ("a-tini", "b-tini", "c-tini"):
        _seed_recipe(db_conn, name=n, source="pending_llm_tried", version="v1")
    rc = unpark_failures(db_conn, normalizer_version="v1", limit=2)
    db_conn.commit()
    assert rc == 2
    remaining = db_conn.execute(
        "select count(*) from recipes "
        "where canonical_name_source = 'pending_llm_tried' "
        "and normalizer_version = %s",
        ("v1",),
    ).fetchone()[0]
    assert remaining == 1
```

- [ ] **Step 3: Run the failing tests**

```bash
cd ingredients && uv run pytest tests/test_dedup_db_park.py -v
```

Expected: ImportError / AttributeError.

- [ ] **Step 4: Implement the helpers**

Append to `ingredients/src/ingredients/dedup/db.py`:

```python
def park_attempted_names(
    conn: psycopg.Connection, *, normalizer_version: str, names: list[str],
) -> int:
    """Flip recipes rows from canonical_name_source='pending_llm' to
    'pending_llm_tried' for the given normalizer_version, restricted to
    rows whose .name is in `names`. Caller commits.

    Same role as the mapping-side helper of the same name: parks names
    that didn't clear in a chunk's ingest so they don't reappear in
    the next chunk or run. Operator runs `normalize-names retry-failures`
    to unpark.

    Returns rowcount."""
    if not names:
        return 0
    cur = conn.execute(
        """
        update recipes
           set canonical_name_source = 'pending_llm_tried'
         where normalizer_version  = %s
           and canonical_name_source = 'pending_llm'
           and name = any(%s::text[])
        """,
        (normalizer_version, names),
    )
    return cur.rowcount


def unpark_failures(
    conn: psycopg.Connection, *, normalizer_version: str,
    limit: int | None = None,
) -> int:
    """Flip 'pending_llm_tried' rows at the given normalizer_version
    back to 'pending_llm'. Caller commits.

    With `limit=N`, flips at most N rows. Returns rowcount."""
    if limit is None:
        cur = conn.execute(
            """
            update recipes
               set canonical_name_source = 'pending_llm'
             where normalizer_version  = %s
               and canonical_name_source = 'pending_llm_tried'
            """,
            (normalizer_version,),
        )
    else:
        cur = conn.execute(
            """
            update recipes
               set canonical_name_source = 'pending_llm'
             where id in (
                 select id from recipes
                  where normalizer_version  = %s
                    and canonical_name_source = 'pending_llm_tried'
                  limit %s
             )
            """,
            (normalizer_version, limit),
        )
    return cur.rowcount
```

- [ ] **Step 5: Run the tests, expect them to pass**

```bash
cd ingredients && uv run pytest tests/test_dedup_db_park.py -v
```

Expected: 7/7 passing.

- [ ] **Step 6: Run the full ingredients suite**

```bash
cd ingredients && uv run pytest -x
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add ingredients/src/ingredients/dedup/types.py \
        ingredients/src/ingredients/dedup/db.py \
        ingredients/tests/test_dedup_db_park.py
git commit -m "$(cat <<'EOF'
Dedup: park_attempted_names + unpark_failures

Mirror of the mapping-side helpers, against
recipes.canonical_name_source. Same parking semantics for the
normalize-names Phase-2 chunked drain.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Wire dedup drain parking + add `normalize-names retry-failures` CLI

**Files:**
- Modify: `ingredients/src/ingredients/dedup/normalizer_llm.py:113-152` (`submit_normalize_names_batch`)
- Modify: `ingredients/src/ingredients/cli.py:682-797` (`_drain_dedup_in_chunks`)
- Modify: `ingredients/src/ingredients/cli.py` (add `retry-failures` subparser under `norm_sub`)
- Modify: `ingredients/src/ingredients/cli.py` (`run_normalize_names` dispatcher)
- Test: `ingredients/tests/test_normalize_names_resolve_pending_batch.py` (extend with parking test)
- Test: `ingredients/tests/test_normalize_names_retry_failures.py` (new)

Mirror of Task 4. The shape is identical to mapping; the differences are:
- Function/import names: `submit_normalize_names_batch`, `fetch_pending_canonical_names`, `NORMALIZER_VERSION`.
- Column: `canonical_name_source` instead of `mapper_source`; key column is `name` (not `lower(trim(name))`).
- The propose-form-equivalent action in dedup is `propose` (a name proposal); but for parking purposes, the relevant case is "any action that doesn't write a resolution leaves the row pending and needs parking." Same logic applies.

- [ ] **Step 1: Verify `submit_normalize_names_batch` will get `submitted_names` populated**

Read `ingredients/src/ingredients/dedup/normalizer_llm.py:113-152`. Confirm that `row_to_id=lambda r: r[0]` is unchanged and `r[0]` is the raw recipe name. The `submit_batch` change from Task 2 already populates `submitted_names` from `request_map.values()`, so no code change is needed in this function.

- [ ] **Step 2: Write the failing parking test**

Add to `ingredients/tests/test_normalize_names_resolve_pending_batch.py`:

```python
def test_dedup_drain_parks_stuck_names(tmp_path, monkeypatch):
    """Dedup version of the same test: a chunk that leaves a name at
    pending_llm parks it so the next iteration's queue is empty and the
    drain terminates."""
    from ingredients.cli import _drain_dedup_in_chunks
    from common.llm.batch_provider import BatchResult, BatchStatus, BatchSubmission
    from unittest.mock import MagicMock

    pending = ["good drink", "stuck drink"]
    parked: list[str] = []

    def _fetch(conn, normalizer_version, limit=None):
        live = [n for n in pending if n not in parked]
        return live[:limit] if limit else list(live)

    monkeypatch.setattr(
        "ingredients.dedup.normalizer_llm.fetch_pending_canonical_names", _fetch,
    )
    monkeypatch.setattr(
        "ingredients.dedup.db.fetch_pending_canonical_names", _fetch,
    )
    monkeypatch.setattr(
        "ingredients.dedup.normalizer_llm.lexical_candidates",
        lambda conn, normalized, limit=20: [],
    )

    def _write_normalization(conn, raw_name, normalized, canonical_name, source, normalizer_version):
        if raw_name in pending:
            pending.remove(raw_name)
    monkeypatch.setattr(
        "ingredients.dedup.normalizer_llm.write_normalization",
        _write_normalization,
    )

    def _park(conn, normalizer_version, names):
        for n in names:
            if n in pending and n not in parked:
                parked.append(n)
        return len(names)
    monkeypatch.setattr(
        "ingredients.dedup.db.park_attempted_names", _park,
    )

    submit_calls: list[int] = []
    def _submit(requests):
        reqs = list(requests)
        submit_calls.append(len(reqs))
        return BatchSubmission(
            batch_id=f"b{len(submit_calls)}", provider="openai",
            model_id="gpt-5-mini", request_count=len(reqs),
        )
    provider = MagicMock()
    provider.model_id = "gpt-5-mini"
    provider.submit.side_effect = _submit
    provider.status.side_effect = lambda bid: BatchStatus(
        batch_id=bid, state="completed", completed=2, total=2,
    )

    from common.llm.sidecar import load_sidecar
    def _fetch_results(batch_id):
        sc = load_sidecar(batch_id, batches_dir=tmp_path)
        out = []
        for cid, raw in sc.request_map.items():
            if raw == "good drink":
                out.append(BatchResult(
                    custom_id=cid,
                    raw_text='{"action": "chose", "canonical_name": "Good Drink"}',
                    error=None,
                ))
            else:
                # Action that leaves the row pending — same semantic as
                # mapping's propose_form: ingest takes no DB write.
                out.append(BatchResult(
                    custom_id=cid,
                    raw_text='{"action": "abstain"}',
                    error=None,
                ))
        return iter(out)
    provider.fetch_results.side_effect = _fetch_results

    db = MagicMock()
    db.conn = MagicMock()
    rc = _drain_dedup_in_chunks(
        db, provider, tmp_path,
        chunk_size=10, total_limit=None, poll_interval=0,
    )
    assert rc == 0
    # Note: in dedup, abstain DOES write — adjust the expectation if your
    # actual on_result writes for 'abstain'. Check the implementation:
    # ingest_normalize_names_batch's on_result calls write_normalize_abstain
    # for action='abstain', so the row IS removed from pending. To exercise
    # the parking path with dedup, the simulated action must be one that
    # falls through *without* writing — e.g., a malformed action string
    # that the parser accepts but the dispatch ignores. Use an unrecognized
    # action string instead:
    assert submit_calls == [2]
    # `parked` will be empty if 'abstain' clears the row; if so, replace
    # the abstain stub above with an unrecognized action that the on_result
    # body ignores. Rework the assertion accordingly.
```

**Important note:** read `ingredients/src/ingredients/dedup/normalizer_llm.py`'s `on_result` body before finalizing this test. The dispatch logic determines which actions clear the row vs leave it pending. Pick an action (or fabricate a malformed-but-parseable JSON) that exercises the leave-pending path. If `abstain` clears the row, swap it for an unrecognized action like `{"action": "noop"}` and add a `monkeypatch.setattr` for `_parse_response` if needed to keep parsing working. Iterate the test until it actually exercises the bug being fixed (i.e., a stuck row that needs parking).

- [ ] **Step 3: Run the test, expect failure (and adjust as noted in Step 2)**

```bash
cd ingredients && uv run pytest tests/test_normalize_names_resolve_pending_batch.py::test_dedup_drain_parks_stuck_names -v
```

- [ ] **Step 4: Wire parking into `_drain_dedup_in_chunks`**

Edit `ingredients/src/ingredients/cli.py` — find `_drain_dedup_in_chunks` (around line 682). Two changes:

(a) Add `park_attempted_names` import:

```python
    from ingredients.dedup.db import (
        fetch_pending_canonical_names, park_attempted_names,
    )
```

(b) After the ingest block (around line 791), add:

```python
            stuck = park_attempted_names(
                db.conn, normalizer_version=NORMALIZER_VERSION,
                names=list(outcome.submitted_names),
            )
            db.conn.commit()
            if stuck:
                aggregate_counts["parked"] = aggregate_counts.get("parked", 0) + stuck
                log.info("chunk %d parked %d stuck names as pending_llm_tried",
                         chunk_idx, stuck)
```

- [ ] **Step 5: Update the run-summary log**

Before `print_summary(...)` near line 793:

```python
    parked_total = aggregate_counts.get("parked", 0)
    if parked_total:
        log.info(
            "parked %d names as pending_llm_tried "
            "(run 'normalize-names retry-failures' to retry)",
            parked_total,
        )
    print_summary(
        f"normalize-names resolve-pending ({chunk_idx} chunks, {drained} drained)",
        {"all": aggregate_counts}, mode="applied",
    )
```

- [ ] **Step 6: Run the parking test, expect pass**

```bash
cd ingredients && uv run pytest tests/test_normalize_names_resolve_pending_batch.py::test_dedup_drain_parks_stuck_names -v
```

Expected: PASS.

- [ ] **Step 7: Run the existing dedup-drain tests**

```bash
cd ingredients && uv run pytest tests/test_normalize_names_resolve_pending_batch.py -v
```

Expected: all green. Same caveat as Task 4 Step 7: pre-existing tests may need a `park_attempted_names` monkeypatch returning 0 if they fail.

- [ ] **Step 8: Add `retry-failures` subparser under `normalize-names`**

Find `norm_sub` (around line 184) — it has `resolve-pending` and `list-pending` subparsers. Add:

```python
    p_retry_norm = norm_sub.add_parser(
        "retry-failures",
        help="Unpark names parked by the chunked drain "
             "(pending_llm_tried -> pending_llm). Run after the "
             "underlying blocker is resolved.",
    )
    p_retry_norm.add_argument(
        "--limit", type=int, default=None,
        help="Unpark at most N rows.",
    )
    p_retry_norm.add_argument(
        "--yes", action="store_true",
        help="Skip the count-and-confirm prompt.",
    )
```

- [ ] **Step 9: Add the dispatcher branch in `run_normalize_names`**

Find `run_normalize_names` (around line 969). It currently handles `resolve-pending` and `list-pending`. Add:

```python
    if getattr(args, "normalize_cmd", None) == "retry-failures":
        return run_normalize_names_retry_failures(args)
```

near the top of the function alongside the existing branches.

- [ ] **Step 10: Implement the handler**

Add a top-level function in `ingredients/src/ingredients/cli.py`:

```python
def run_normalize_names_retry_failures(args: argparse.Namespace) -> int:
    """Unpark Phase-2 dedup failures: flip canonical_name_source
    'pending_llm_tried' back to 'pending_llm' for the current
    NORMALIZER_VERSION."""
    from ingredients.dedup.db import unpark_failures
    from ingredients.dedup.version import NORMALIZER_VERSION

    db = IngredientsDatabase()
    try:
        n_parked = db.conn.execute(
            """
            select count(*) from recipes
            where canonical_name_source = 'pending_llm_tried'
              and normalizer_version = %s
            """,
            (NORMALIZER_VERSION,),
        ).fetchone()[0]
        if n_parked == 0:
            log.info("nothing parked at normalizer_version=%s", NORMALIZER_VERSION)
            return 0

        cap = (
            min(args.limit, n_parked) if args.limit is not None else n_parked
        )
        log.info("would unpark %d of %d parked rows at normalizer_version=%s",
                 cap, n_parked, NORMALIZER_VERSION)
        if not args.yes:
            sys.stderr.write("Proceed? [y/N]: ")
            sys.stderr.flush()
            answer = sys.stdin.readline().strip().lower()
            if answer not in ("y", "yes"):
                log.info("aborted by operator")
                return 1

        n = unpark_failures(db.conn, normalizer_version=NORMALIZER_VERSION,
                            limit=args.limit)
        db.conn.commit()
        log.info(
            "unparked %d rows; run 'normalize-names resolve-pending --provider …' "
            "to re-submit", n,
        )
        return 0
    finally:
        db.close()
```

- [ ] **Step 11: Write the integration test**

Create `ingredients/tests/test_normalize_names_retry_failures.py`:

```python
"""Integration test for `normalize-names retry-failures`."""

from __future__ import annotations

import argparse


def _seed_parked(conn, *, name, normalizer_version):
    conn.execute(
        """
        insert into recipes
            (source_url, site, name, canonical_name_source,
             normalizer_version, normalized_at)
        values (%s, 'test', %s, 'pending_llm_tried', %s, now())
        """,
        (f"test://{name}/{normalizer_version}", name, normalizer_version),
    )
    conn.commit()


def test_retry_failures_unparks(db_conn, monkeypatch):
    from ingredients.cli import run_normalize_names_retry_failures
    from ingredients.dedup.version import NORMALIZER_VERSION

    _seed_parked(db_conn, name="garibaldi", normalizer_version=NORMALIZER_VERSION)
    _seed_parked(db_conn, name="americano", normalizer_version=NORMALIZER_VERSION)

    class _StubDB:
        def __init__(self):
            self.conn = db_conn
        def close(self):
            pass
    monkeypatch.setattr("ingredients.cli.IngredientsDatabase", _StubDB)

    args = argparse.Namespace(
        normalize_cmd="retry-failures", limit=None, yes=True,
    )
    rc = run_normalize_names_retry_failures(args)
    assert rc == 0

    n_remaining = db_conn.execute(
        "select count(*) from recipes "
        "where canonical_name_source = 'pending_llm_tried' "
        "and normalizer_version = %s",
        (NORMALIZER_VERSION,),
    ).fetchone()[0]
    assert n_remaining == 0


def test_retry_failures_empty_returns_zero(db_conn, monkeypatch):
    from ingredients.cli import run_normalize_names_retry_failures

    class _StubDB:
        def __init__(self):
            self.conn = db_conn
        def close(self):
            pass
    monkeypatch.setattr("ingredients.cli.IngredientsDatabase", _StubDB)

    args = argparse.Namespace(
        normalize_cmd="retry-failures", limit=None, yes=True,
    )
    rc = run_normalize_names_retry_failures(args)
    assert rc == 0


def test_retry_failures_respects_limit(db_conn, monkeypatch):
    from ingredients.cli import run_normalize_names_retry_failures
    from ingredients.dedup.version import NORMALIZER_VERSION

    for n in ("a-tail", "b-tail", "c-tail"):
        _seed_parked(db_conn, name=n, normalizer_version=NORMALIZER_VERSION)

    class _StubDB:
        def __init__(self):
            self.conn = db_conn
        def close(self):
            pass
    monkeypatch.setattr("ingredients.cli.IngredientsDatabase", _StubDB)

    args = argparse.Namespace(
        normalize_cmd="retry-failures", limit=2, yes=True,
    )
    rc = run_normalize_names_retry_failures(args)
    assert rc == 0

    remaining = db_conn.execute(
        "select count(*) from recipes "
        "where canonical_name_source = 'pending_llm_tried' "
        "and normalizer_version = %s",
        (NORMALIZER_VERSION,),
    ).fetchone()[0]
    assert remaining == 1
```

- [ ] **Step 12: Run the test**

```bash
cd ingredients && uv run pytest tests/test_normalize_names_retry_failures.py -v
```

Expected: 3/3 passing.

- [ ] **Step 13: Run the full ingredients suite**

```bash
cd ingredients && uv run pytest -x
```

Expected: all green.

- [ ] **Step 14: Commit**

```bash
git add ingredients/src/ingredients/cli.py \
        ingredients/tests/test_normalize_names_resolve_pending_batch.py \
        ingredients/tests/test_normalize_names_retry_failures.py
git commit -m "$(cat <<'EOF'
Dedup drain: park stuck names + add `normalize-names retry-failures`

Mirror of the mapping-side wiring against canonical_name_source. The
chunked drain now flips stuck rows to 'pending_llm_tried' after each
chunk's ingest; `normalize-names retry-failures` unparks them.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

Add a brief note in two sections (Mapper, Recipe Dedup) about the new state and command. Don't bloat the file — the spec lives in `docs/superpowers/specs/`; CLAUDE.md just needs operators to know the command exists.

- [ ] **Step 1: Read the current `CLAUDE.md` Mapper section**

Find the section starting with `## Ingredient → Taxonomy Mapper`. Look for the Phase-2 example commands and the surrounding context.

- [ ] **Step 2: Add the retry-failures command to the Mapper usage block**

In the existing Phase-2 examples block, after the `map resolve-pending --reset --except-version v1` line, add:

````markdown
# Unpark names that previous runs parked at 'pending_llm_tried' (e.g.
# after approving a form proposal or editing the taxonomy). Then re-run
# `map resolve-pending --provider …` to re-submit.
cd ingredients && uv run python -m ingredients.cli map retry-failures
````

And add one paragraph immediately above or below the examples (whichever
flows better):

> The chunked Batch drain (`--batch`) parks any name that didn't get a
> clearing action ('chose' or 'abstain') from a chunk's ingest — most
> commonly `propose_form`, but also parse failures and transient provider
> errors — by flipping `mapper_source` to `pending_llm_tried`. Parked
> names are excluded from `fetch_pending_llm_names`, so subsequent chunks
> and subsequent runs don't re-submit them. Run `map retry-failures` to
> unpark after the blocker is resolved.

- [ ] **Step 3: Add the parallel note to the Recipe Dedup section**

In `## Recipe Dedup`, in the normalize-names example block, after the
`normalize-names --reset --except-version v1` line:

````markdown
# Unpark names that previous runs parked at 'pending_llm_tried'.
cd ingredients && uv run python -m ingredients.cli normalize-names retry-failures
````

And the same kind of paragraph adapted to dedup:

> The chunked Batch drain parks names whose chunk didn't produce a
> clearing action by flipping `canonical_name_source` to
> `pending_llm_tried`. Run `normalize-names retry-failures` to unpark.

- [ ] **Step 4: Verify nothing else in CLAUDE.md mentions the literal `pending_llm` enum value as exhaustive**

```bash
grep -n "'alias', 'lexical', 'pending_llm', 'llm', 'abstain'" CLAUDE.md
```

If it shows results, update those lists to include `'pending_llm_tried'`. (The spec lives elsewhere, so the file probably doesn't enumerate; this is a precaution.)

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "$(cat <<'EOF'
CLAUDE.md: document retry-failures + pending_llm_tried state

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review Checklist (controller, after all tasks)

After all tasks are complete:

1. **Spec coverage:**
   - State model (`pending_llm_tried` on both columns) — Task 1 (migration), Task 3 (mapping types), Task 5 (dedup types).
   - End-of-chunk parking — Task 4 (mapping wiring), Task 6 (dedup wiring).
   - Within-run termination — naturally follows from parking; covered by `test_drain_parks_stuck_names` in both files.
   - Across-run termination — naturally follows from parking; the existing `fetch_pending_llm_names` query excludes parked rows.
   - Recovery via MAPPER_VERSION bump — already works (existing `--reset --except-version`); no task.
   - Recovery via `retry-failures` — Task 4 (mapping CLI), Task 6 (dedup CLI).
   - Form-proposal approval recovery — covered by `retry-failures` (operator runs after approving).
   - Sidecar / batch-runner changes — Task 2 (`BatchSubmitOutcome.submitted_names`).
   - Crash-window tradeoff — accepted, no task needed.
   - Telemetry (parked-count log) — Task 4 Step 5, Task 6 Step 5.
   - Tests for both drains and both `retry-failures` commands — Tasks 3, 4, 5, 6.
   - CLAUDE.md updates — Task 7.

2. **Placeholder scan:** every step has concrete code or commands. Migration filename uses `<YYYYMMDDHHMMSS>` placeholder filled at the moment of creation, with explicit instructions to derive it.

3. **Type consistency:** `park_attempted_names(conn, *, mapper_version, names)` and `unpark_failures(conn, *, mapper_version, limit=None)` use consistent kwarg names across mapping and dedup (with `mapper_version` ↔ `normalizer_version` swap as appropriate). `BatchSubmitOutcome.submitted_names: tuple[str, ...]` defined once, used in both drain wirings.

## After implementation

After all 7 tasks pass and commits land, dispatch the final code-reviewer subagent for the entire implementation, then proceed with `superpowers:finishing-a-development-branch` (or open the PR directly per CLAUDE.md PR convention).
