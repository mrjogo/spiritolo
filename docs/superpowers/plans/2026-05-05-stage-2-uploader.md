# Stage 2 Uploader — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the local-edit / staging-upload workflow: a backup-script
that emits a sidecar metadata file, a Python uploader that pushes a
dirty-row diff from local to staging behind mandatory protections, the
matching JSON Schema, smoke tests, GH-Action update, and docs.

**Architecture:** Two PRs in series. **PR A** lands a tiny migration that
makes the two FKs in the `recipes ↔ recipe_clusters` cycle deferrable so
`SET CONSTRAINTS ALL DEFERRED` works inside the uploader's serializable
transaction. After PR A merges and deploys to staging, **PR B** lands
all of Stage 2 proper: backup-script sidecar, JSON Schema (load-bearing,
runtime-validated), the Python uploader as a small workspace member, end-
to-end smoke tests against two ephemeral local databases, GH-Action
artifact update, and docs.

**Tech Stack:** Postgres 17 (Supabase), bash (`scripts/backup-supabase.sh`),
Python 3.11+ with `psycopg[binary]` and `jsonschema`, pytest, GitHub
Actions, uv workspace.

**Spec:** [docs/superpowers/specs/2026-05-05-stage-2-uploader-design.md](../specs/2026-05-05-stage-2-uploader-design.md)

---

## File Structure

### PR A files
- Create: `supabase/migrations/20260505180000_defer_recipes_cluster_fks.sql`
- Modify: `WORKFLOW_PLAN.md` (mark deferrable-FK pre-work shipped)

### PR B files
- Modify: `pyproject.toml` (add `scripts` to uv workspace)
- Create: `scripts/pyproject.toml`
- Create: `scripts/src/upload_to_staging/__init__.py`
- Create: `scripts/src/upload_to_staging/__main__.py`
- Create: `scripts/src/upload_to_staging/cli.py`
- Create: `scripts/src/upload_to_staging/tables.py`
- Create: `scripts/src/upload_to_staging/sidecar.py`
- Create: `scripts/src/upload_to_staging/sidecar.schema.json`
- Create: `scripts/src/upload_to_staging/dump.py`
- Create: `scripts/src/upload_to_staging/db.py`
- Create: `scripts/src/upload_to_staging/upsert.py`
- Create: `scripts/tests/__init__.py`
- Create: `scripts/tests/conftest.py`
- Create: `scripts/tests/test_sidecar.py`
- Create: `scripts/tests/test_tables.py`
- Create: `scripts/tests/test_dump.py`
- Create: `scripts/tests/test_db.py`
- Create: `scripts/tests/test_upsert.py`
- Create: `scripts/tests/test_smoke_upload.py`
- Create: `scripts/tests/fixtures/__init__.py`
- Create: `scripts/tests/fixtures/seed.py`
- Modify: `scripts/backup-supabase.sh`
- Modify: `.github/workflows/backup-staging-db.yml`
- Create: `docs/upload.md`
- Modify: `docs/backups.md`
- Modify: `CLAUDE.md`
- Modify: `WORKFLOW_PLAN.md` (mark Stage 2 shipped)

**Boundary rationale.** The uploader is split into thin focused modules
(`tables`, `sidecar`, `dump`, `db`, `upsert`, `cli`) so each module has a
single responsibility, fits in context, and can be unit-tested in
isolation. The CLI module is a thin orchestrator over the others.

---

# Phase 1 — PR A: Deferrable-FK pre-work

This phase is on the existing branch `claude/stage2-uploader-prework`,
which already carries the spec commit.

## Task 1: Write the deferrable-FK migration

**Files:**
- Create: `supabase/migrations/20260505180000_defer_recipes_cluster_fks.sql`

- [ ] **Step 1: Create the migration file**

Write to `supabase/migrations/20260505180000_defer_recipes_cluster_fks.sql`:

```sql
-- Make the two FKs in the recipes ↔ recipe_clusters cycle deferrable so
-- the upload-to-staging script can push both sides in one transaction
-- with SET CONSTRAINTS ALL DEFERRED. INITIALLY IMMEDIATE keeps default
-- behavior for normal application writes unchanged; only an explicit
-- SET CONSTRAINTS DEFERRED inside a transaction defers them.
--
-- ALTER CONSTRAINT is metadata-only — no row is touched, no FK protection
-- is dropped at any moment, no validation re-pass is needed.
--
-- Spec: docs/superpowers/specs/2026-05-05-stage-2-uploader-design.md

alter table public.recipes
  alter constraint recipes_cluster_id_fkey
  deferrable initially immediate;

alter table public.recipe_clusters
  alter constraint recipe_clusters_representative_recipe_id_fkey
  deferrable initially immediate;

-- Verify the post-state. If a constraint name has drifted from the
-- expected default in some prior migration, this raises and the
-- migration aborts; manual investigation before re-applying.
do $$
declare
  bad_count int;
begin
  select count(*)
    into bad_count
    from pg_constraint
    where conname = any (array[
      'recipes_cluster_id_fkey',
      'recipe_clusters_representative_recipe_id_fkey'
    ])
      and (not condeferrable or condeferred);

  if bad_count > 0 then
    raise exception
      'Expected both target FKs to be deferrable+immediate; % violated', bad_count;
  end if;

  if (select count(*)
      from pg_constraint
      where conname = any (array[
        'recipes_cluster_id_fkey',
        'recipe_clusters_representative_recipe_id_fkey'
      ])) <> 2 then
    raise exception 'Expected to find exactly 2 matching constraints by name';
  end if;
end $$;
```

- [ ] **Step 2: Commit the migration**

```bash
git add supabase/migrations/20260505180000_defer_recipes_cluster_fks.sql
git commit -m "$(cat <<'EOF'
Make recipes ↔ recipe_clusters cycle FKs deferrable

ALTER CONSTRAINT only — no FK is dropped at any point. INITIALLY IMMEDIATE
keeps default behavior for normal queries unchanged; the upload-to-staging
script issues SET CONSTRAINTS ALL DEFERRED inside its txn to defer these
two FKs only.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

## Task 2: Apply migration locally and verify

**Files:**
- Read: `supabase/migrations/20260505180000_defer_recipes_cluster_fks.sql`

- [ ] **Step 1: Apply the migration via the host's supabase CLI**

The supabase CLI runs on the Mac host, not the devcontainer. Per
[CLAUDE.md], `supabase migration up --include-all` forward-applies new
migrations without wiping data.

Hand off to the user:

> Please run `supabase migration up --include-all` on your Mac host to
> apply the new deferrable-FK migration to your local Supabase. Reply
> "applied" when done.

If you (the agent) cannot run the host command yourself, prompt the user
and wait for confirmation before continuing.

- [ ] **Step 2: Verify the constraints are deferrable**

From the devcontainer, query the local DB:

```bash
psql "$SUPABASE_DB_URL" -c "
  select conname, condeferrable, condeferred
  from pg_constraint
  where conname in (
    'recipes_cluster_id_fkey',
    'recipe_clusters_representative_recipe_id_fkey'
  );
"
```

Expected output: both constraints listed, `condeferrable = t`,
`condeferred = f`.

If either is `f / *` or `* / t`, the migration didn't take — investigate
before continuing.

## Task 3: Mark pre-work shipped, push, open PR A

**Files:**
- Modify: `WORKFLOW_PLAN.md`

- [ ] **Step 1: Update the Pre-work heading status**

Find the heading:

```markdown
## Pre-work — Deferrable FKs for the recipes / recipe_clusters cycle
```

and change to:

```markdown
## Pre-work — Deferrable FKs for the recipes / recipe_clusters cycle *(shipped)*
```

- [ ] **Step 2: Commit the status update**

```bash
git add WORKFLOW_PLAN.md
git commit -m "$(cat <<'EOF'
Mark deferrable-FK pre-work shipped in WORKFLOW_PLAN.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 3: Push and open PR**

```bash
git push -u origin claude/stage2-uploader-prework
gh pr create --base main --title "Stage 2 pre-work: deferrable-FKs migration + spec" --body "$(cat <<'EOF'
Pre-work for the Stage 2 local-edit / staging-upload workflow.

Two commits: the design spec for the full Stage 2 effort, and a tiny
migration that makes the `recipes.cluster_id` and
`recipe_clusters.representative_recipe_id` FKs deferrable. The migration
uses ALTER CONSTRAINT (metadata-only — no FK is dropped at any moment)
and INITIALLY IMMEDIATE (default behavior for normal queries unchanged).
Includes a verification block that asserts both constraints ended up
`condeferrable=t / condeferred=f`.

After this merges to main, promote `main → staging` so the
deploy-migrations workflow applies it to staging. PR B (the uploader)
depends on staging carrying this migration.

Spec: docs/superpowers/specs/2026-05-05-stage-2-uploader-design.md

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: Capture PR URL**

Note the PR URL printed by `gh pr create`. That's the user's checkpoint to
review and merge.

---

# ⛔ Manual gate between Phase 1 and Phase 2 ⛔

Before any task in Phase 2 starts:

1. PR A must be merged to `main`.
2. The user (or you, with explicit approval) must promote `main → staging`:
   ```bash
   git checkout staging && git merge --ff-only main && git push
   git checkout main
   ```
3. The `Deploy migrations` workflow run on `staging` must be green —
   confirms the deferrable-FK migration is applied to staging.

If any of those isn't done, **stop and ask the user before starting
Phase 2**. The smoke tests and the uploader's `--apply` path require
staging to carry the migration.

---

# Phase 2 — PR B: The uploader

This phase happens on a new branch: `claude/stage2-uploader-impl`.

## Task 4: Switch branch and add `scripts/` as a workspace member

**Files:**
- Modify: `pyproject.toml`
- Create: `scripts/pyproject.toml`
- Create: `scripts/src/upload_to_staging/__init__.py`

- [ ] **Step 1: Create new branch off latest main**

```bash
git checkout main
git pull
git checkout -b claude/stage2-uploader-impl
```

- [ ] **Step 2: Add `scripts` to the uv workspace**

Edit `pyproject.toml`:

```toml
[tool.uv.workspace]
members = ["common", "scraper", "ingredients", "scripts"]
```

- [ ] **Step 3: Create the workspace member skeleton**

Create `scripts/pyproject.toml`:

```toml
[project]
name = "spiritolo-scripts"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "psycopg[binary]>=3.2",
    "jsonschema>=4",
    "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
]

[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
upload_to_staging = ["sidecar.schema.json"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

Create `scripts/src/upload_to_staging/__init__.py`:

```python
"""Spiritolo: local-edit / staging-upload tooling.

Modules:
- ``tables`` — owned-tables list (single source of truth, also imported
  by Stage 3 utilities).
- ``sidecar`` — JSONC parser + jsonschema validation of the .meta.json.
- ``dump``   — pg_restore --list parsing, file/schema sha256.
- ``db``     — staging/local connection helpers, applied-migrations,
              max(updated_at), dirty-set queries.
- ``upsert`` — UPSERT SQL builder, sequence-resync SQL builder.
- ``cli``    — argparse + orchestration. Entry point is ``__main__``.
"""
```

- [ ] **Step 4: Sync uv workspace and confirm scripts is recognized**

```bash
cd /workspaces/spiritolo
uv sync
uv run --package spiritolo-scripts python -c "import upload_to_staging; print('ok')"
```

Expected output: `ok`.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml scripts/pyproject.toml scripts/src/upload_to_staging/__init__.py
git commit -m "$(cat <<'EOF'
Add scripts/ as uv workspace member with upload_to_staging package

Skeleton only — empty package and dev-only deps (psycopg, jsonschema,
python-dotenv, pytest). Subsequent commits add modules with TDD.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

## Task 5: Owned-tables list (single source of truth)

**Files:**
- Create: `scripts/src/upload_to_staging/tables.py`
- Create: `scripts/tests/__init__.py`
- Create: `scripts/tests/test_tables.py`

- [ ] **Step 1: Create the empty tests package**

Create `scripts/tests/__init__.py` (empty file).

- [ ] **Step 2: Write the failing test**

Create `scripts/tests/test_tables.py`:

```python
"""Owned-tables registry: shape and invariants."""
from upload_to_staging.tables import OWNED_TABLES, OwnedTable


def test_expected_tables_present():
    names = [t.name for t in OWNED_TABLES]
    assert names == [
        "recipes",
        "taxonomy_nodes",
        "cocktail_aliases",
        "recipe_ingredients",
        "taxonomy_edges",
        "taxonomy_aliases",
        "taxonomy_provenance",
        "taxonomy_proposals",
        "recipe_clusters",
    ]


def test_each_table_has_pk_columns():
    for t in OWNED_TABLES:
        assert isinstance(t.pk_columns, tuple)
        assert len(t.pk_columns) >= 1
        assert all(isinstance(c, str) and c for c in t.pk_columns)


def test_sequence_set_only_for_bigserial_tables():
    by_name = {t.name: t for t in OWNED_TABLES}
    assert by_name["recipes"].sequence == "recipes_id_seq"
    assert by_name["recipe_ingredients"].sequence == "recipe_ingredients_id_seq"
    assert by_name["taxonomy_nodes"].sequence == "taxonomy_nodes_id_seq"
    assert by_name["taxonomy_proposals"].sequence == "taxonomy_proposals_id_seq"
    assert by_name["recipe_clusters"].sequence == "recipe_clusters_id_seq"
    # Composite-PK tables have no sequence
    for name in ("cocktail_aliases", "taxonomy_edges",
                 "taxonomy_aliases", "taxonomy_provenance"):
        assert by_name[name].sequence is None


def test_owned_table_is_immutable_dataclass():
    t = OWNED_TABLES[0]
    import dataclasses
    assert dataclasses.is_dataclass(t)
    assert getattr(type(t), "__dataclass_params__").frozen is True
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd /workspaces/spiritolo
uv run --package spiritolo-scripts pytest scripts/tests/test_tables.py -v
```

Expected: collection errors / import failure (module doesn't exist yet).

- [ ] **Step 4: Implement `tables.py`**

Create `scripts/src/upload_to_staging/tables.py`:

```python
"""The 9 public-schema tables the uploader pushes from local to staging.

Definitive list and dependency order. Imported by both the uploader and
(later) Stage 3 utilities. Excluded from this list and from the upload:
profiles (excluded from the dump; FKs to auth.users), all views.
"""
from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class OwnedTable:
    name: str
    pk_columns: tuple[str, ...]
    sequence: str | None  # None for composite-PK tables (no auto-id sequence)


OWNED_TABLES: tuple[OwnedTable, ...] = (
    OwnedTable("recipes", ("id",), "recipes_id_seq"),
    OwnedTable("taxonomy_nodes", ("id",), "taxonomy_nodes_id_seq"),
    OwnedTable("cocktail_aliases", ("alias", "canonical_name"), None),
    OwnedTable("recipe_ingredients", ("id",), "recipe_ingredients_id_seq"),
    OwnedTable("taxonomy_edges", ("parent_id", "child_id"), None),
    OwnedTable("taxonomy_aliases", ("alias", "node_id"), None),
    OwnedTable("taxonomy_provenance", ("node_id",), None),
    OwnedTable("taxonomy_proposals", ("id",), "taxonomy_proposals_id_seq"),
    OwnedTable("recipe_clusters", ("id",), "recipe_clusters_id_seq"),
)
```

- [ ] **Step 5: Run test to verify it passes**

```bash
uv run --package spiritolo-scripts pytest scripts/tests/test_tables.py -v
```

Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add scripts/src/upload_to_staging/tables.py scripts/tests/__init__.py scripts/tests/test_tables.py
git commit -m "$(cat <<'EOF'
upload_to_staging: owned-tables registry

Single source of truth for the 9 public tables the uploader pushes.
Frozen dataclass; sequence is None for composite-PK tables.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

## Task 6: JSON Schema for the sidecar

**Files:**
- Create: `scripts/src/upload_to_staging/sidecar.schema.json`
- Create: `scripts/tests/test_schema_shape.py`

- [ ] **Step 1: Write the schema-shape test**

Create `scripts/tests/test_schema_shape.py`:

```python
"""Sanity checks on the sidecar JSON Schema itself.

These run before any sidecar parsing — if the schema is broken, every
other test breaks downstream. Prefer to learn here.
"""
from __future__ import annotations

import importlib.resources
import json

import jsonschema


def _load_schema() -> dict:
    with importlib.resources.files("upload_to_staging").joinpath(
        "sidecar.schema.json"
    ).open("rb") as f:
        return json.load(f)


def test_schema_is_valid_draft_2020_12():
    schema = _load_schema()
    jsonschema.Draft202012Validator.check_schema(schema)


def test_schema_lists_expected_required_fields():
    schema = _load_schema()
    assert set(schema["required"]) == {
        "taken_at",
        "staging_fingerprint",
        "applied_migrations",
        "dump_basename",
        "dump_sha256",
        "dump_schema_sha256",
        "backup_script_version",
    }


def test_minimal_valid_sidecar_passes_validation():
    schema = _load_schema()
    valid = {
        "taken_at": "2026-05-05T14:30:42.117Z",
        "staging_fingerprint": "0" * 64,
        "applied_migrations": ["20260422120000"],
        "dump_basename": "spiritolo-staging-x.dump",
        "dump_sha256": "0" * 64,
        "dump_schema_sha256": "0" * 64,
        "backup_script_version": 1,
    }
    jsonschema.validate(valid, schema)


def test_missing_required_field_fails():
    schema = _load_schema()
    invalid = {
        "taken_at": "2026-05-05T14:30:42.117Z",
        # staging_fingerprint missing
        "applied_migrations": [],
        "dump_basename": "x",
        "dump_sha256": "0" * 64,
        "dump_schema_sha256": "0" * 64,
        "backup_script_version": 1,
    }
    import pytest
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid, schema)
```

- [ ] **Step 2: Run to confirm failures**

```bash
uv run --package spiritolo-scripts pytest scripts/tests/test_schema_shape.py -v
```

Expected: failures because the schema file doesn't exist yet.

- [ ] **Step 3: Write the schema**

Create `scripts/src/upload_to_staging/sidecar.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Spiritolo backup sidecar",
  "description": "Metadata file written next to a Supabase pg_dump backup. The upload-to-staging script requires this file to exist and to validate against this schema before doing any other work.",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "taken_at",
    "staging_fingerprint",
    "applied_migrations",
    "dump_basename",
    "dump_sha256",
    "dump_schema_sha256",
    "backup_script_version"
  ],
  "properties": {
    "$schema": {
      "type": "string",
      "description": "Optional reference to this schema for IDE autocomplete."
    },
    "taken_at": {
      "type": "string",
      "format": "date-time",
      "description": "ISO-8601 UTC timestamp captured AFTER pg_dump returns successfully. Reference time T for the staleness/dirty-set computation."
    },
    "staging_fingerprint": {
      "type": "string",
      "pattern": "^[0-9a-f]{64}$",
      "description": "sha256 of `host:dbname` from SUPABASE_STAGING_DB_URL. Password and port excluded — the host is enough to distinguish Supabase projects."
    },
    "applied_migrations": {
      "type": "array",
      "items": {"type": "string"},
      "description": "Full list of `version` values from supabase_migrations.schema_migrations on staging at backup time. Order matches Postgres' default ordering."
    },
    "dump_basename": {
      "type": "string",
      "description": "Basename of the .dump file at write time. Lets the uploader detect renamed/diverged pairs."
    },
    "dump_sha256": {
      "type": "string",
      "pattern": "^[0-9a-f]{64}$",
      "description": "sha256 of the dump file bytes."
    },
    "dump_schema_sha256": {
      "type": "string",
      "pattern": "^[0-9a-f]{64}$",
      "description": "sha256 of `pg_restore --schema-only <dump>` output. Stable across pg_restore runs on the same dump (the archive's TOC is canonical)."
    },
    "backup_script_version": {
      "type": "integer",
      "minimum": 1,
      "description": "Bumped if the sidecar format changes incompatibly."
    }
  }
}
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run --package spiritolo-scripts pytest scripts/tests/test_schema_shape.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/src/upload_to_staging/sidecar.schema.json scripts/tests/test_schema_shape.py
git commit -m "$(cat <<'EOF'
upload_to_staging: JSON Schema for the .meta.json sidecar

Draft 2020-12. additionalProperties: false. Hex-pattern validation on
the three sha256 fields and the staging fingerprint. Required-field set
checked by tests so future schema edits can't silently drop one.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

## Task 7: Sidecar JSONC parser + validator

**Files:**
- Create: `scripts/src/upload_to_staging/sidecar.py`
- Create: `scripts/tests/test_sidecar.py`

- [ ] **Step 1: Write the failing tests**

Create `scripts/tests/test_sidecar.py`:

```python
"""Sidecar load + validation."""
from __future__ import annotations

import json

import jsonschema
import pytest

from upload_to_staging.sidecar import (
    Sidecar,
    SidecarError,
    load_sidecar,
    strip_jsonc_comments,
)


def _valid_dict() -> dict:
    return {
        "taken_at": "2026-05-05T14:30:42.117Z",
        "staging_fingerprint": "0" * 64,
        "applied_migrations": ["20260422120000", "20260424054315"],
        "dump_basename": "spiritolo-staging-x.dump",
        "dump_sha256": "a" * 64,
        "dump_schema_sha256": "b" * 64,
        "backup_script_version": 1,
    }


def test_strip_line_comments():
    raw = '{\n  // hi\n  "x": 1\n}'
    assert json.loads(strip_jsonc_comments(raw)) == {"x": 1}


def test_strip_block_comments():
    raw = '{\n  /* hi\n     and bye */\n  "x": 1\n}'
    assert json.loads(strip_jsonc_comments(raw)) == {"x": 1}


def test_does_not_eat_comment_like_substrings_in_strings():
    raw = '{"x": "// not a comment"}'
    assert json.loads(strip_jsonc_comments(raw)) == {"x": "// not a comment"}


def test_load_sidecar_happy_path(tmp_path):
    p = tmp_path / "x.dump.meta.json"
    p.write_text(json.dumps(_valid_dict()))
    s = load_sidecar(p)
    assert isinstance(s, Sidecar)
    assert s.taken_at == "2026-05-05T14:30:42.117Z"
    assert s.applied_migrations == ("20260422120000", "20260424054315")


def test_load_sidecar_missing_file(tmp_path):
    with pytest.raises(SidecarError, match="not found"):
        load_sidecar(tmp_path / "nope.meta.json")


def test_load_sidecar_invalid_json(tmp_path):
    p = tmp_path / "x.meta.json"
    p.write_text('{ this is not json')
    with pytest.raises(SidecarError, match="parse"):
        load_sidecar(p)


def test_load_sidecar_schema_violation(tmp_path):
    bad = _valid_dict()
    del bad["staging_fingerprint"]
    p = tmp_path / "x.meta.json"
    p.write_text(json.dumps(bad))
    with pytest.raises(SidecarError) as exc:
        load_sidecar(p)
    assert "schema" in str(exc.value).lower()


def test_load_sidecar_with_jsonc_comments(tmp_path):
    raw = (
        '{\n'
        '  // taken_at is captured after pg_dump returns\n'
        '  "taken_at": "2026-05-05T14:30:42.117Z",\n'
        '  "staging_fingerprint": "' + "0" * 64 + '",\n'
        '  "applied_migrations": [],\n'
        '  "dump_basename": "x.dump",\n'
        '  "dump_sha256": "' + "a" * 64 + '",\n'
        '  "dump_schema_sha256": "' + "b" * 64 + '",\n'
        '  "backup_script_version": 1\n'
        '}'
    )
    p = tmp_path / "x.dump.meta.json"
    p.write_text(raw)
    s = load_sidecar(p)
    assert s.backup_script_version == 1
```

- [ ] **Step 2: Run tests to confirm failures**

```bash
uv run --package spiritolo-scripts pytest scripts/tests/test_sidecar.py -v
```

Expected: import errors / failures (module doesn't exist).

- [ ] **Step 3: Implement `sidecar.py`**

Create `scripts/src/upload_to_staging/sidecar.py`:

```python
"""Sidecar load + JSON-Schema validation.

The .meta.json file is JSONC: comments allowed (line `//`, block `/* */`).
Comments are stripped with a regex pre-pass that ignores comment-like
substrings inside string literals.
"""
from __future__ import annotations

import dataclasses
import importlib.resources
import json
import pathlib
import re

import jsonschema


class SidecarError(Exception):
    """Any failure loading or validating a sidecar."""


@dataclasses.dataclass(frozen=True)
class Sidecar:
    taken_at: str
    staging_fingerprint: str
    applied_migrations: tuple[str, ...]
    dump_basename: str
    dump_sha256: str
    dump_schema_sha256: str
    backup_script_version: int


# Matches: line comments (//... to EOL), block comments (/* ... */),
# and string literals (so we can pass them through untouched).
_JSONC_PATTERN = re.compile(
    r'"(?:\\.|[^"\\])*"'      # string literal — preserved
    r'|//[^\n]*'              # line comment — replaced with empty
    r'|/\*.*?\*/',            # block comment — replaced with empty
    re.DOTALL,
)


def strip_jsonc_comments(text: str) -> str:
    """Strip `//` and `/* */` comments without eating comment-like
    substrings inside string literals."""
    def _replace(m: re.Match[str]) -> str:
        s = m.group(0)
        if s.startswith('"'):
            return s          # preserve strings
        return ""             # drop comments
    return _JSONC_PATTERN.sub(_replace, text)


def _schema() -> dict:
    with importlib.resources.files("upload_to_staging").joinpath(
        "sidecar.schema.json"
    ).open("rb") as f:
        return json.load(f)


def load_sidecar(path: pathlib.Path) -> Sidecar:
    """Read, parse, schema-validate, and return a Sidecar.

    Raises SidecarError on any failure with a message that names the
    specific problem (file missing, JSON parse failure, schema
    violation).
    """
    if not path.is_file():
        raise SidecarError(f"Sidecar not found at {path}")

    try:
        raw = path.read_text()
    except OSError as e:
        raise SidecarError(f"Could not read sidecar {path}: {e}") from e

    stripped = strip_jsonc_comments(raw)
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as e:
        raise SidecarError(f"Could not parse sidecar JSON {path}: {e}") from e

    try:
        jsonschema.validate(data, _schema())
    except jsonschema.ValidationError as e:
        raise SidecarError(
            f"Sidecar {path.name} fails schema validation: {e.message}"
        ) from e

    return Sidecar(
        taken_at=data["taken_at"],
        staging_fingerprint=data["staging_fingerprint"],
        applied_migrations=tuple(data["applied_migrations"]),
        dump_basename=data["dump_basename"],
        dump_sha256=data["dump_sha256"],
        dump_schema_sha256=data["dump_schema_sha256"],
        backup_script_version=data["backup_script_version"],
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run --package spiritolo-scripts pytest scripts/tests/test_sidecar.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/src/upload_to_staging/sidecar.py scripts/tests/test_sidecar.py
git commit -m "$(cat <<'EOF'
upload_to_staging: JSONC sidecar parser + jsonschema validation

Single regex strips line and block comments while preserving comment-like
substrings inside string literals. SidecarError messages name the specific
failure (missing, parse, schema).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

## Task 8: Dump inspection — sha256 helpers + schema-only hash

**Files:**
- Create: `scripts/src/upload_to_staging/dump.py`
- Create: `scripts/tests/test_dump.py`

- [ ] **Step 1: Write the failing tests**

Create `scripts/tests/test_dump.py`:

```python
"""Dump-file inspection helpers."""
from __future__ import annotations

import hashlib
import pathlib
import subprocess

import pytest

from upload_to_staging.dump import (
    DumpInspectionError,
    sha256_of_file,
    sha256_of_schema_only,
)


def test_sha256_of_file_matches_python_sha256(tmp_path):
    p = tmp_path / "x.bin"
    p.write_bytes(b"hello dump\n")
    assert sha256_of_file(p) == hashlib.sha256(b"hello dump\n").hexdigest()


def test_sha256_of_file_missing(tmp_path):
    with pytest.raises(DumpInspectionError, match="not found"):
        sha256_of_file(tmp_path / "nope.dump")


def test_sha256_of_schema_only_runs_pg_restore(tmp_path, monkeypatch):
    """Patch subprocess so we don't need a real dump file."""
    canned = b"-- canned schema-only output\nCREATE TABLE x (...);\n"
    expected = hashlib.sha256(canned).hexdigest()

    class _CompletedProcess:
        returncode = 0
        stdout = canned
        stderr = b""

    captured: dict = {}

    def _run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _CompletedProcess()

    monkeypatch.setattr(subprocess, "run", _run)
    p = tmp_path / "fake.dump"
    p.write_bytes(b"")
    got = sha256_of_schema_only(p)
    assert got == expected
    assert captured["cmd"][0] == "pg_restore"
    assert "--schema-only" in captured["cmd"]
    assert str(p) in captured["cmd"]


def test_sha256_of_schema_only_subprocess_failure(tmp_path, monkeypatch):
    class _Failed:
        returncode = 1
        stdout = b""
        stderr = b"pg_restore: error: input file appears to be corrupt"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Failed())
    p = tmp_path / "x.dump"
    p.write_bytes(b"")
    with pytest.raises(DumpInspectionError, match="pg_restore"):
        sha256_of_schema_only(p)
```

- [ ] **Step 2: Run tests to confirm failures**

```bash
uv run --package spiritolo-scripts pytest scripts/tests/test_dump.py -v
```

Expected: failures (module missing).

- [ ] **Step 3: Implement `dump.py`**

Create `scripts/src/upload_to_staging/dump.py`:

```python
"""Dump-file integrity helpers.

`sha256_of_file` reads bytes; `sha256_of_schema_only` shells out to
`pg_restore --schema-only --no-owner --no-privileges <dump>` and hashes
the resulting SQL. The schema-only output is canonical for a given dump
file (just rendering the archive's TOC) so the resulting hash is byte-
stable across runs of pg_restore.
"""
from __future__ import annotations

import hashlib
import pathlib
import subprocess


class DumpInspectionError(Exception):
    """Any failure reading or running pg_restore against a dump."""


_BUF_SIZE = 64 * 1024


def sha256_of_file(path: pathlib.Path) -> str:
    if not path.is_file():
        raise DumpInspectionError(f"Dump file not found: {path}")
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_BUF_SIZE):
            h.update(chunk)
    return h.hexdigest()


def sha256_of_schema_only(path: pathlib.Path) -> str:
    if not path.is_file():
        raise DumpInspectionError(f"Dump file not found: {path}")
    proc = subprocess.run(
        ["pg_restore", "--schema-only", "--no-owner", "--no-privileges",
         str(path)],
        capture_output=True,
    )
    if proc.returncode != 0:
        raise DumpInspectionError(
            f"pg_restore --schema-only failed for {path}: "
            f"{proc.stderr.decode(errors='replace').strip()}"
        )
    return hashlib.sha256(proc.stdout).hexdigest()
```

- [ ] **Step 4: Run tests to verify pass**

```bash
uv run --package spiritolo-scripts pytest scripts/tests/test_dump.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/src/upload_to_staging/dump.py scripts/tests/test_dump.py
git commit -m "$(cat <<'EOF'
upload_to_staging: dump-file integrity helpers (sha256, schema-only sha)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

## Task 9: DB layer — connection helpers + introspection queries

**Files:**
- Create: `scripts/src/upload_to_staging/db.py`
- Create: `scripts/tests/conftest.py`
- Create: `scripts/tests/test_db.py`

- [ ] **Step 1: Write the conftest with the two-DB fixture**

Create `scripts/tests/conftest.py`:

```python
"""Test fixtures for the uploader.

Spins up two ephemeral databases on the local Postgres cluster derived
from TEST_DB_URL. They simulate the uploader's "local" and "staging"
inputs end-to-end.

If TEST_DB_URL is unset, DB-backed tests skip cleanly.
"""
from __future__ import annotations

import os
import pathlib
from urllib.parse import urlparse, urlunparse

import psycopg
import pytest
from dotenv import load_dotenv


load_dotenv(pathlib.Path(__file__).resolve().parent.parent.parent / ".env")

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
_MIGRATIONS_DIR = _REPO_ROOT / "supabase" / "migrations"


def _base_url() -> str | None:
    return os.environ.get("TEST_DB_URL")


def _db_name(url: str) -> str:
    return urlparse(url).path.lstrip("/")


def _with_db(url: str, name: str) -> str:
    return urlunparse(urlparse(url)._replace(path=f"/{name}"))


def _admin_url(url: str) -> str:
    return _with_db(url, "postgres")


def _ensure_db(admin_url: str, name: str) -> None:
    with psycopg.connect(admin_url, autocommit=True) as conn:
        existed = conn.execute(
            "select 1 from pg_database where datname = %s", (name,)
        ).fetchone() is not None
        if existed:
            # Drop and recreate to guarantee clean state per session.
            # Disconnect any clients first.
            conn.execute(
                "select pg_terminate_backend(pid) from pg_stat_activity "
                "where datname = %s and pid <> pg_backend_pid()",
                (name,),
            )
            conn.execute(f'drop database "{name}"')
        conn.execute(f'create database "{name}"')


def _bootstrap_supabase_stubs(conn: psycopg.Connection) -> None:
    conn.execute("create schema if not exists auth")
    conn.execute(
        """
        create table if not exists auth.users (
            id uuid primary key default gen_random_uuid(),
            email text
        )
        """
    )
    conn.execute(
        "create or replace function auth.uid() returns uuid "
        "language sql stable as 'select null::uuid'"
    )
    conn.execute("create schema if not exists extensions")
    conn.execute(
        "create schema if not exists supabase_migrations"
    )
    conn.execute(
        """
        create table if not exists
            supabase_migrations.schema_migrations (
            version text primary key,
            name text,
            statements text[]
        )
        """
    )


def _apply_migrations(url: str) -> list[str]:
    versions: list[str] = []
    with psycopg.connect(url, autocommit=True) as conn:
        _bootstrap_supabase_stubs(conn)
        for path in sorted(_MIGRATIONS_DIR.glob("*.sql")):
            sql = path.read_text()
            with conn.transaction():
                conn.execute(sql)
                version = path.stem.split("_", 1)[0]
                conn.execute(
                    "insert into supabase_migrations.schema_migrations "
                    "(version, name) values (%s, %s) on conflict do nothing",
                    (version, path.stem),
                )
                versions.append(version)
    return versions


@pytest.fixture(scope="session")
def db_pair():
    """Yield (local_url, staging_url) for two freshly-migrated DBs.
    Skips the test if TEST_DB_URL is unset."""
    base = _base_url()
    if not base:
        pytest.skip("TEST_DB_URL not set; skipping DB-backed test")

    base_name = _db_name(base)
    local_name = f"{base_name}_upload_local"
    staging_name = f"{base_name}_upload_staging"

    admin = _admin_url(base)
    _ensure_db(admin, local_name)
    _ensure_db(admin, staging_name)

    local_url = _with_db(base, local_name)
    staging_url = _with_db(base, staging_name)
    _apply_migrations(local_url)
    _apply_migrations(staging_url)

    yield local_url, staging_url


@pytest.fixture
def fresh_db_pair(db_pair):
    """Truncate every owned table in both DBs before yielding."""
    from upload_to_staging.tables import OWNED_TABLES
    local_url, staging_url = db_pair
    table_list = ", ".join(t.name for t in OWNED_TABLES)
    for url in (local_url, staging_url):
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(f"truncate {table_list} restart identity cascade")
    yield local_url, staging_url
```

- [ ] **Step 2: Write the failing tests**

Create `scripts/tests/test_db.py`:

```python
"""DB-layer queries: applied migrations, max(updated_at), dirty set."""
from __future__ import annotations

import datetime as dt

import psycopg

from upload_to_staging.db import (
    fetch_applied_migrations,
    fetch_max_updated_at_per_table,
    fetch_dirty_rows_per_table,
)
from upload_to_staging.tables import OWNED_TABLES


def test_fetch_applied_migrations_returns_versions(fresh_db_pair):
    local_url, _ = fresh_db_pair
    with psycopg.connect(local_url) as conn:
        got = fetch_applied_migrations(conn)
    # The conftest seeds at least one migration.
    assert len(got) > 0
    assert all(isinstance(v, str) and v for v in got)
    # Sorted ascending.
    assert list(got) == sorted(got)


def test_max_updated_at_empty_tables(fresh_db_pair):
    _, staging_url = fresh_db_pair
    with psycopg.connect(staging_url) as conn:
        got = fetch_max_updated_at_per_table(conn, OWNED_TABLES)
    assert set(got.keys()) == {t.name for t in OWNED_TABLES}
    for v in got.values():
        assert v is None


def test_dirty_rows_returns_only_recent(fresh_db_pair):
    local_url, _ = fresh_db_pair
    with psycopg.connect(local_url, autocommit=True) as conn:
        # Two old recipes (pre-T), one new (post-T).
        conn.execute(
            "insert into recipes (source_url, site, name, jsonld) values "
            "('u1', 's', 'old1', '{}'::jsonb), "
            "('u2', 's', 'old2', '{}'::jsonb)"
        )
        # Sleep just enough that updated_at differs; pg now() advances per stmt.
        T = dt.datetime.now(dt.timezone.utc)
        # New row inserted strictly after T.
        import time
        time.sleep(0.05)
        conn.execute(
            "insert into recipes (source_url, site, name, jsonld) values "
            "('u3', 's', 'new1', '{}'::jsonb)"
        )

        recipes_table = next(t for t in OWNED_TABLES if t.name == "recipes")
        got = fetch_dirty_rows_per_table(conn, [recipes_table], T)
        rows = got["recipes"]
        names = sorted(r["name"] for r in rows)
        assert names == ["new1"]
```

- [ ] **Step 3: Run to confirm failures**

```bash
uv run --package spiritolo-scripts pytest scripts/tests/test_db.py -v
```

Expected: failures (db.py missing). If TEST_DB_URL is unset, all skip —
in that case, set it per CLAUDE.md and re-run.

- [ ] **Step 4: Implement `db.py`**

Create `scripts/src/upload_to_staging/db.py`:

```python
"""Read-side DB queries used by the uploader.

Centralized so tests can exercise each query in isolation without
spinning up the full CLI.
"""
from __future__ import annotations

import datetime as dt
from typing import Iterable

import psycopg

from .tables import OwnedTable


def fetch_applied_migrations(conn: psycopg.Connection) -> tuple[str, ...]:
    """Read every `version` from supabase_migrations.schema_migrations.

    Sorted ascending so the result is order-stable across calls and
    regardless of insert order.
    """
    rows = conn.execute(
        "select version from supabase_migrations.schema_migrations "
        "order by version"
    ).fetchall()
    return tuple(r[0] for r in rows)


def fetch_max_updated_at_per_table(
    conn: psycopg.Connection,
    tables: Iterable[OwnedTable],
) -> dict[str, dt.datetime | None]:
    """For each table, return max(updated_at) (or None if empty)."""
    out: dict[str, dt.datetime | None] = {}
    for t in tables:
        row = conn.execute(
            f"select max(updated_at) from public.{t.name}"
        ).fetchone()
        out[t.name] = row[0] if row else None
    return out


def fetch_dirty_rows_per_table(
    conn: psycopg.Connection,
    tables: Iterable[OwnedTable],
    after: dt.datetime,
) -> dict[str, list[dict]]:
    """For each table, return rows with updated_at > `after`, as dicts
    keyed by column name. Empty list when none."""
    out: dict[str, list[dict]] = {}
    for t in tables:
        cur = conn.execute(
            f"select * from public.{t.name} where updated_at > %s",
            (after,),
        )
        cols = [d.name for d in cur.description]
        out[t.name] = [dict(zip(cols, row)) for row in cur.fetchall()]
    return out
```

- [ ] **Step 5: Run tests to verify pass**

```bash
uv run --package spiritolo-scripts pytest scripts/tests/test_db.py -v
```

Expected: 3 passed (or all 3 skipped if TEST_DB_URL unset; set it and re-run).

- [ ] **Step 6: Commit**

```bash
git add scripts/src/upload_to_staging/db.py scripts/tests/conftest.py scripts/tests/test_db.py
git commit -m "$(cat <<'EOF'
upload_to_staging: read-side DB queries + two-DB pytest fixture

Conftest spins up <base>_upload_local and <base>_upload_staging on the
TEST_DB_URL host; applies all supabase/migrations/*.sql against both;
yields URLs. Per-test fixture truncates the owned tables so smoke runs
start from a known state.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

## Task 10: UPSERT and sequence-resync SQL builders

**Files:**
- Create: `scripts/src/upload_to_staging/upsert.py`
- Create: `scripts/tests/test_upsert.py`

- [ ] **Step 1: Write the failing tests**

Create `scripts/tests/test_upsert.py`:

```python
"""UPSERT and sequence-resync SQL generation."""
from __future__ import annotations

import psycopg

from upload_to_staging.tables import OWNED_TABLES, OwnedTable
from upload_to_staging.upsert import build_upsert_sql, resync_sequence_sql


_RECIPES = next(t for t in OWNED_TABLES if t.name == "recipes")
_TAXEDGES = next(t for t in OWNED_TABLES if t.name == "taxonomy_edges")


def test_upsert_sql_single_pk():
    sql = build_upsert_sql(_RECIPES, columns=["id", "name", "updated_at"])
    rendered = sql.as_string(None)
    assert "insert into" in rendered.lower()
    assert '"recipes"' in rendered
    assert "on conflict (\"id\")" in rendered.lower() or 'on conflict ("id")' in rendered
    assert 'do update set "name" = excluded."name"' in rendered.lower() \
        or '"name" = excluded."name"' in rendered.lower()
    # PK column never appears in the SET list.
    set_clause = rendered.lower().split("do update set", 1)[1]
    assert '"id"' not in set_clause


def test_upsert_sql_composite_pk():
    sql = build_upsert_sql(
        _TAXEDGES,
        columns=["parent_id", "child_id", "rank", "updated_at"],
    )
    rendered = sql.as_string(None)
    assert "(\"parent_id\", \"child_id\")" in rendered.lower() \
        or '("parent_id", "child_id")' in rendered.lower()


def test_resync_sequence_sql_for_serial_table():
    sql = resync_sequence_sql(_RECIPES)
    assert sql is not None
    rendered = sql.as_string(None)
    assert "setval" in rendered.lower()
    assert "recipes_id_seq" in rendered
    assert "max(\"id\")" in rendered.lower() or 'max("id")' in rendered.lower()


def test_resync_sequence_sql_returns_none_for_composite_pk_table():
    assert resync_sequence_sql(_TAXEDGES) is None
```

- [ ] **Step 2: Run to confirm failures**

```bash
uv run --package spiritolo-scripts pytest scripts/tests/test_upsert.py -v
```

Expected: import errors.

- [ ] **Step 3: Implement `upsert.py`**

Create `scripts/src/upload_to_staging/upsert.py`:

```python
"""SQL builders for the per-table UPSERT batches and the post-batch
sequence resync."""
from __future__ import annotations

from psycopg import sql

from .tables import OwnedTable


def build_upsert_sql(
    table: OwnedTable, columns: list[str]
) -> sql.Composed:
    """`INSERT INTO <table> (<cols>) VALUES %s ON CONFLICT (<pk>) DO UPDATE
    SET <non-pk> = EXCLUDED.<non-pk>...` — to be invoked with
    `cursor.executemany` or via parameterized batched INSERT.
    """
    pk_set = set(table.pk_columns)
    non_pk = [c for c in columns if c not in pk_set]

    placeholders = sql.SQL(", ").join([sql.Placeholder()] * len(columns))
    set_clause = sql.SQL(", ").join(
        sql.SQL("{col} = excluded.{col}").format(col=sql.Identifier(c))
        for c in non_pk
    )

    return sql.SQL(
        "insert into public.{tbl} ({cols}) values ({vals}) "
        "on conflict ({pk}) do update set {sets}"
    ).format(
        tbl=sql.Identifier(table.name),
        cols=sql.SQL(", ").join(sql.Identifier(c) for c in columns),
        vals=placeholders,
        pk=sql.SQL(", ").join(sql.Identifier(c) for c in table.pk_columns),
        sets=set_clause,
    )


def resync_sequence_sql(table: OwnedTable) -> sql.Composed | None:
    """`select setval(<seq>, max(<pk>)) from <table>` — but safe when
    the table is empty (max returns NULL, which setval rejects). We
    coalesce to nextval(seq)-1 so an empty table is a no-op.

    Returns None for tables without a sequence (composite PKs).
    """
    if table.sequence is None:
        return None
    if len(table.pk_columns) != 1:
        return None  # belt-and-braces; sequence implies single-column PK

    pk = sql.Identifier(table.pk_columns[0])
    seq = sql.Literal(table.sequence)
    return sql.SQL(
        "select setval({seq}, "
        "  greatest(coalesce(max({pk}), 0), nextval({seq}) - 1), "
        "  true) "
        "from public.{tbl}"
    ).format(seq=seq, pk=pk, tbl=sql.Identifier(table.name))
```

- [ ] **Step 4: Run tests to verify pass**

```bash
uv run --package spiritolo-scripts pytest scripts/tests/test_upsert.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/src/upload_to_staging/upsert.py scripts/tests/test_upsert.py
git commit -m "$(cat <<'EOF'
upload_to_staging: per-table UPSERT and sequence-resync SQL builders

Composed via psycopg.sql so identifiers are always quoted safely. PK
columns never appear in the DO UPDATE SET list. Sequence resync is a
no-op for composite-PK tables.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

## Task 11: CLI orchestration — argparse + check pipeline + dry-run

**Files:**
- Create: `scripts/src/upload_to_staging/cli.py`
- Create: `scripts/src/upload_to_staging/__main__.py`

- [ ] **Step 1: Implement `__main__.py` (thin entry)**

Create `scripts/src/upload_to_staging/__main__.py`:

```python
"""Module entry: `python -m upload_to_staging ...`"""
from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 2: Implement `cli.py`**

Create `scripts/src/upload_to_staging/cli.py`:

```python
"""CLI entry: argparse, orchestration of all checks, dry-run vs apply."""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import os
import pathlib
import sys
from urllib.parse import urlparse

import psycopg

from .db import (
    fetch_applied_migrations,
    fetch_dirty_rows_per_table,
    fetch_max_updated_at_per_table,
)
from .dump import sha256_of_file, sha256_of_schema_only
from .sidecar import Sidecar, SidecarError, load_sidecar
from .tables import OWNED_TABLES, OwnedTable
from .upsert import build_upsert_sql, resync_sequence_sql


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="upload-to-staging",
        description="Push dirty rows from a local Supabase to staging "
                    "behind mandatory protections.",
    )
    p.add_argument("--dump", required=True, type=pathlib.Path,
                   help="Path to the .dump file. Sidecar must exist as "
                        "<dump>.meta.json next to it.")
    p.add_argument("--local-db", default=os.environ.get("SUPABASE_DB_URL"),
                   help="Local Postgres URL (default: $SUPABASE_DB_URL).")
    p.add_argument("--staging-db",
                   default=os.environ.get("SUPABASE_STAGING_DB_URL"),
                   help="Staging Postgres URL (default: $SUPABASE_STAGING_DB_URL).")
    p.add_argument("--apply", action="store_true",
                   help="Actually push. Without it, dry-run only.")
    p.add_argument("--yes", action="store_true",
                   help="Skip the y/N confirmation before --apply.")
    return p.parse_args(argv)


def _staging_fingerprint_from_url(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    db = (parsed.path or "").lstrip("/")
    return hashlib.sha256(f"{host}:{db}".encode()).hexdigest()


def _fail(msg: str) -> int:
    print(f"ERROR: {msg}", file=sys.stderr)
    return 1


def main(argv: list[str]) -> int:
    args = _parse_args(argv)

    if not args.local_db:
        return _fail("--local-db not given and SUPABASE_DB_URL unset")
    if not args.staging_db:
        return _fail("--staging-db not given and SUPABASE_STAGING_DB_URL unset")

    sidecar_path = pathlib.Path(str(args.dump) + ".meta.json")
    try:
        sidecar = load_sidecar(sidecar_path)
    except SidecarError as e:
        return _fail(str(e))

    # 2. Dump integrity
    actual_sha = sha256_of_file(args.dump)
    if actual_sha != sidecar.dump_sha256:
        return _fail(
            f"Dump file sha256 differs from sidecar:\n"
            f"  expected {sidecar.dump_sha256}\n"
            f"  actual   {actual_sha}"
        )
    actual_schema_sha = sha256_of_schema_only(args.dump)
    if actual_schema_sha != sidecar.dump_schema_sha256:
        return _fail(
            f"Dump schema-only sha256 differs from sidecar:\n"
            f"  expected {sidecar.dump_schema_sha256}\n"
            f"  actual   {actual_schema_sha}"
        )

    # 3. Staging fingerprint
    actual_fp = _staging_fingerprint_from_url(args.staging_db)
    if actual_fp != sidecar.staging_fingerprint:
        return _fail(
            f"Sidecar's staging fingerprint doesn't match --staging-db.\n"
            f"  sidecar host:db hash {sidecar.staging_fingerprint}\n"
            f"  --staging-db   hash  {actual_fp}\n"
            f"Confirm you're pointing at the right Supabase project."
        )

    # Connect to both DBs.
    with psycopg.connect(args.staging_db) as staging, \
         psycopg.connect(args.local_db) as local:

        # 4. Schema check (migration list equality)
        sidecar_migs = list(sidecar.applied_migrations)
        staging_migs = list(fetch_applied_migrations(staging))
        local_migs = list(fetch_applied_migrations(local))
        if sidecar_migs != staging_migs or sidecar_migs != local_migs:
            return _fail(_format_migration_mismatch(
                sidecar_migs, staging_migs, local_migs
            ))

        # 5. Staleness check
        T = dt.datetime.fromisoformat(sidecar.taken_at.replace("Z", "+00:00"))
        staging_max = fetch_max_updated_at_per_table(staging, OWNED_TABLES)
        stale = {
            name: ts for name, ts in staging_max.items()
            if ts is not None and ts > T
        }
        if stale:
            lines = "\n".join(
                f"  {name}: max(updated_at)={ts.isoformat()} > T={T.isoformat()}"
                for name, ts in stale.items()
            )
            return _fail(
                "Staging was modified after the dump was taken. "
                "Manual reconciliation required (re-take backup, redo work):\n"
                + lines
            )

        # 6. Compute dirty set
        dirty = fetch_dirty_rows_per_table(local, OWNED_TABLES, T)

        # 7. Print plan
        _print_plan(args, sidecar, T, dirty)

        if not args.apply:
            return 0

        # Confirm
        if not args.yes:
            ans = input("Apply to staging? [y/N] ").strip().lower()
            if ans not in ("y", "yes"):
                print("Aborted.")
                return 0

        # 8. Apply (serializable txn)
        return _apply(staging, sidecar, T, dirty)


def _format_migration_mismatch(
    sidecar_migs: list[str],
    staging_migs: list[str],
    local_migs: list[str],
) -> str:
    s_set, st_set, l_set = map(set, (sidecar_migs, staging_migs, local_migs))
    parts = ["Migration list mismatch — refuse to upload."]
    if st_set - s_set:
        parts.append(f"  staging has migrations the dump doesn't: "
                     f"{sorted(st_set - s_set)}")
    if s_set - st_set:
        parts.append(f"  dump has migrations staging doesn't: "
                     f"{sorted(s_set - st_set)}")
    if l_set - s_set:
        parts.append(f"  local has migrations the dump doesn't: "
                     f"{sorted(l_set - s_set)}")
    if s_set - l_set:
        parts.append(f"  dump has migrations local doesn't: "
                     f"{sorted(s_set - l_set)}")
    return "\n".join(parts)


def _print_plan(
    args: argparse.Namespace,
    sidecar: Sidecar,
    T: dt.datetime,
    dirty: dict[str, list[dict]],
) -> None:
    print(f"Dump:       {args.dump}")
    print(f"Sidecar:    {args.dump}.meta.json")
    print(f"T (taken):  {T.isoformat()}")
    print(f"Local DB:   {urlparse(args.local_db).hostname}/"
          f"{urlparse(args.local_db).path.lstrip('/')}")
    print(f"Staging DB: {urlparse(args.staging_db).hostname}/"
          f"{urlparse(args.staging_db).path.lstrip('/')}")
    print()
    print("All checks passed.")
    print()
    total = 0
    print("Dirty rows (local with updated_at > T):")
    for t in OWNED_TABLES:
        n = len(dirty.get(t.name, []))
        total += n
        print(f"  {t.name:24s} {n:>7d}")
    print(f"  {'─' * 32}")
    print(f"  {'total':24s} {total:>7d}")
    print()
    if args.apply:
        print("Applying (--apply set)...")
    else:
        print("Dry run. Re-run with --apply to push.")


def _apply(
    staging: psycopg.Connection,
    sidecar: Sidecar,
    T: dt.datetime,
    dirty: dict[str, list[dict]],
) -> int:
    staging.autocommit = False
    try:
        with staging.cursor() as cur:
            cur.execute("set transaction isolation level serializable")
            cur.execute("set constraints all deferred")

            # Re-verify staleness inside the txn — closes the gap between
            # the earlier read and the COMMIT.
            staging_max = fetch_max_updated_at_per_table(staging, OWNED_TABLES)
            stale = {
                n: ts for n, ts in staging_max.items()
                if ts is not None and ts > T
            }
            if stale:
                staging.rollback()
                return _fail(
                    "Staging changed between the pre-check and the apply txn. "
                    f"Aborted. Tables: {list(stale)}"
                )

            applied: dict[str, int] = {}
            for table in OWNED_TABLES:
                rows = dirty.get(table.name, [])
                if not rows:
                    applied[table.name] = 0
                    continue
                cols = list(rows[0].keys())
                stmt = build_upsert_sql(table, cols)
                # Batch in chunks of 1000.
                for i in range(0, len(rows), 1000):
                    batch = rows[i:i + 1000]
                    cur.executemany(
                        stmt,
                        [tuple(r[c] for c in cols) for r in batch],
                    )
                applied[table.name] = len(rows)

            for table in OWNED_TABLES:
                stmt = resync_sequence_sql(table)
                if stmt is not None:
                    cur.execute(stmt)

            staging.commit()
    except psycopg.errors.SerializationFailure as e:
        staging.rollback()
        return _fail(
            f"Serialization conflict at COMMIT — concurrent staging "
            f"write tripped SERIALIZABLE. Re-run --apply, or re-take "
            f"backup if it persists. ({e})"
        )

    print()
    print("Applied to staging:")
    total = 0
    for table in OWNED_TABLES:
        n = applied[table.name]
        total += n
        print(f"  {table.name:24s} {n:>7d}")
    print(f"  {'─' * 32}")
    print(f"  {'total':24s} {total:>7d}")
    print()
    print("Done.")
    return 0
```

- [ ] **Step 3: Sanity-check the CLI module imports**

```bash
uv run --package spiritolo-scripts python -m upload_to_staging --help
```

Expected: argparse usage text, no traceback.

- [ ] **Step 4: Commit**

```bash
git add scripts/src/upload_to_staging/cli.py scripts/src/upload_to_staging/__main__.py
git commit -m "$(cat <<'EOF'
upload_to_staging: CLI orchestration

argparse entry that runs the full check pipeline (sidecar, dump integrity,
staging fingerprint, migration-list equality, staleness), prints the dirty
set, and on --apply opens a SERIALIZABLE txn that re-verifies staleness,
UPSERTs all dirty rows, resyncs sequences, and commits.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

## Task 12: Modify `backup-supabase.sh` to write the sidecar

**Files:**
- Modify: `scripts/backup-supabase.sh`

- [ ] **Step 1: Edit the backup script**

Apply this patch — append new logic after the existing `pg_dump`
invocation (which currently ends with `ls -lh "$OUT"`). Replace the
final `ls -lh "$OUT"` line with the block below:

```bash
META="${OUT}.meta.json"

# Snapshot reference time T — captured AFTER pg_dump so any row updated
# during the snapshot window has updated_at <= T.
TAKEN_AT=$(psql "$URL" -tAX -c "select to_char(now() at time zone 'utc', 'YYYY-MM-DD\"T\"HH24:MI:SS.MS\"Z\"')")

# Migration list at backup time. Used by the uploader's schema-version
# check.
MIGRATIONS_JSON=$(psql "$URL" -tAX -c "
  select json_agg(version order by version)
  from supabase_migrations.schema_migrations
")
[[ "$MIGRATIONS_JSON" == "" ]] && MIGRATIONS_JSON="[]"

# Fingerprint = sha256 of "host:dbname". No password, no port.
DBNAME="${URL##*/}"; DBNAME="${DBNAME%%\?*}"
FINGERPRINT=$(printf "%s:%s" "$HOST" "$DBNAME" | sha256sum | awk '{print $1}')

DUMP_SHA=$(sha256sum "$OUT" | awk '{print $1}')
SCHEMA_SHA=$(pg_restore --schema-only --no-owner --no-privileges "$OUT" \
             | sha256sum | awk '{print $1}')

cat > "$META" <<EOF_META
{
  // Generated by scripts/backup-supabase.sh — see
  // scripts/src/upload_to_staging/sidecar.schema.json for the schema.
  // The upload-to-staging script requires this sidecar to exist and to
  // validate against the schema before doing any other work.

  "taken_at": "$TAKEN_AT",
  "staging_fingerprint": "$FINGERPRINT",
  "applied_migrations": $MIGRATIONS_JSON,
  "dump_basename": "$(basename "$OUT")",
  "dump_sha256": "$DUMP_SHA",
  "dump_schema_sha256": "$SCHEMA_SHA",
  "backup_script_version": 1
}
EOF_META

ls -lh "$OUT" "$META"
```

Also: at the top of the script (after the existing `set -euo pipefail`),
add a cleanup trap so a failure between `pg_dump` success and sidecar-
write removes the orphan dump:

```bash
cleanup_partial() {
  local rc=$?
  if (( rc != 0 )) && [[ -f "$OUT" && ! -f "$META" ]]; then
    rm -f "$OUT"
    echo "Removed partial dump $OUT (sidecar write failed)" >&2
  fi
}
trap cleanup_partial EXIT
```

(Place the trap just before the `pg_dump` invocation so `$OUT` is in
scope.)

- [ ] **Step 2: Smoke-test the backup script against the local mirror**

If `SUPABASE_STAGING_DB_URL` points at staging, do not run this against
real staging during dev — use a local clone. Easiest: run against the
`spiritolo_test_upload_staging` DB the test fixture creates. Manual
shell session:

```bash
SUPABASE_STAGING_DB_URL="postgresql://postgres:postgres@host.docker.internal:54322/spiritolo_test_upload_staging" \
  ./scripts/backup-supabase.sh --dest /tmp
ls -l /tmp/spiritolo-staging-*
cat /tmp/spiritolo-staging-*.dump.meta.json | head -30
```

Expected: both files present, sidecar has all fields, JSON parses after
comments stripped.

- [ ] **Step 3: Commit**

```bash
git add scripts/backup-supabase.sh
git commit -m "$(cat <<'EOF'
backup-supabase: write a .meta.json sidecar alongside every dump

Captures taken_at (after pg_dump returns), the applied-migrations list,
sha256 of the dump bytes, sha256 of the dump's schema-only output, and
a sha256 fingerprint of the staging URL's host:dbname. JSONC format so
the file can carry inline comments. Cleanup trap removes the .dump if
sidecar generation fails so we never leave orphaned half-paired artifacts.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

## Task 13: Smoke tests — happy path + staleness abort

**Files:**
- Create: `scripts/tests/fixtures/__init__.py`
- Create: `scripts/tests/fixtures/seed.py`
- Create: `scripts/tests/test_smoke_upload.py`

- [ ] **Step 1: Create the seed helper**

Create `scripts/tests/fixtures/__init__.py` (empty).

Create `scripts/tests/fixtures/seed.py`:

```python
"""Tiny shared fixture: insert identical seed data into a DB.

Three recipes, three taxonomy nodes, one cocktail alias. Kept minimal —
each owned table doesn't need data for the smoke tests to exercise the
upload pipeline; they only need to exist and be addressable.
"""
from __future__ import annotations

import psycopg


def seed(url: str) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(
            "insert into public.recipes "
            "(source_url, site, name, jsonld, fetched_at) "
            "values "
            "('http://e/1', 'e', 'Old Fashioned', '{}'::jsonb, now()),"
            "('http://e/2', 'e', 'Manhattan',     '{}'::jsonb, now()),"
            "('http://e/3', 'e', 'Negroni',       '{}'::jsonb, now())"
        )
        # node_kind has a CHECK constraint ('brand' | 'expression'); leaving
        # it NULL is fine — it's nullable and the smoke tests don't care.
        conn.execute(
            "insert into public.taxonomy_nodes (slug, display_name) "
            "values "
            "('whiskey', 'Whiskey'),"
            "('rye',     'Rye'),"
            "('bourbon', 'Bourbon')"
        )
        conn.execute(
            "insert into public.cocktail_aliases "
            "(alias, canonical_name, source) "
            "values ('old fashioned', 'Old Fashioned', 'seed')"
        )
```

- [ ] **Step 2: Write the failing smoke tests**

Create `scripts/tests/test_smoke_upload.py`:

```python
"""End-to-end smoke tests for upload-to-staging.

Runs the real `scripts/backup-supabase.sh` against the staging mirror to
generate the .dump + .meta.json, then invokes the uploader as a subprocess
exactly as a user would.

Skips when TEST_DB_URL is unset.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
from urllib.parse import urlparse

import psycopg
import pytest

from upload_to_staging.tables import OWNED_TABLES

from .fixtures.seed import seed


_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
_BACKUP_SCRIPT = _REPO_ROOT / "scripts" / "backup-supabase.sh"


def _take_backup(staging_url: str, dest_dir: pathlib.Path) -> pathlib.Path:
    env = os.environ.copy()
    env["SUPABASE_STAGING_DB_URL"] = staging_url
    proc = subprocess.run(
        [str(_BACKUP_SCRIPT), "--dest", str(dest_dir)],
        env=env,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"backup-supabase.sh failed:\n{proc.stderr.decode()}"
        )
    dumps = sorted(dest_dir.glob("spiritolo-staging-*.dump"))
    assert dumps, "backup script produced no .dump file"
    return dumps[-1]


def _run_uploader(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "upload_to_staging", *args],
        capture_output=True,
        check=False,
    )


def test_smoke_happy_path(fresh_db_pair, tmp_path):
    local_url, staging_url = fresh_db_pair
    seed(local_url)
    seed(staging_url)

    dump_path = _take_backup(staging_url, tmp_path)

    # Modify a row locally — give the uploader something to push.
    with psycopg.connect(local_url, autocommit=True) as conn:
        conn.execute("update public.recipes set name = 'Old Fashioned (v2)' "
                     "where name = 'Old Fashioned'")

    proc = _run_uploader(
        "--dump", str(dump_path),
        "--local-db", local_url,
        "--staging-db", staging_url,
        "--apply", "--yes",
    )
    assert proc.returncode == 0, (
        f"uploader failed:\nstdout:\n{proc.stdout.decode()}\n"
        f"stderr:\n{proc.stderr.decode()}"
    )

    with psycopg.connect(staging_url) as conn:
        name = conn.execute(
            "select name from public.recipes where source_url = 'http://e/1'"
        ).fetchone()[0]
    assert name == "Old Fashioned (v2)"


def test_smoke_staleness_aborts(fresh_db_pair, tmp_path):
    local_url, staging_url = fresh_db_pair
    seed(local_url)
    seed(staging_url)

    dump_path = _take_backup(staging_url, tmp_path)

    # Out-of-band write to staging AFTER the backup — simulates someone
    # using the curation UI during the work session.
    with psycopg.connect(staging_url, autocommit=True) as conn:
        conn.execute("update public.recipes set name = 'Manhattan (UI edit)' "
                     "where name = 'Manhattan'")

    # Local change too, just so there'd be something to push if we didn't abort.
    with psycopg.connect(local_url, autocommit=True) as conn:
        conn.execute("update public.recipes set name = 'Negroni (local)' "
                     "where name = 'Negroni'")

    proc = _run_uploader(
        "--dump", str(dump_path),
        "--local-db", local_url,
        "--staging-db", staging_url,
        "--apply", "--yes",
    )
    assert proc.returncode != 0
    err = proc.stderr.decode()
    assert "Staging was modified" in err or "staleness" in err.lower()

    # Negroni's name on staging should be unchanged.
    with psycopg.connect(staging_url) as conn:
        name = conn.execute(
            "select name from public.recipes where source_url = 'http://e/3'"
        ).fetchone()[0]
    assert name == "Negroni"
```

- [ ] **Step 3: Run smoke tests**

```bash
uv run --package spiritolo-scripts pytest scripts/tests/test_smoke_upload.py -v
```

If the seed script's column names don't match the actual schema, fix
the SQL in `scripts/tests/fixtures/seed.py` and re-run. Iterate until
both tests pass. (If you need a quick column reference:
`psql "$TEST_DB_URL" -c "\d public.taxonomy_nodes"`.)

Expected, when correct: 2 passed.

- [ ] **Step 4: Run the full uploader test suite to make sure nothing regressed**

```bash
uv run --package spiritolo-scripts pytest scripts/tests/ -v
```

Expected: all green (the 21+ tests created across tasks 5-13).

- [ ] **Step 5: Commit**

```bash
git add scripts/tests/fixtures/ scripts/tests/test_smoke_upload.py
git commit -m "$(cat <<'EOF'
upload_to_staging: end-to-end smoke tests (happy + staleness abort)

Spins up two ephemeral DBs derived from TEST_DB_URL, seeds identical
data, runs the real backup-supabase.sh against the staging mirror to
generate the dump + sidecar, then drives the uploader as a subprocess.
Two scenarios: a happy-path push and a staleness-detected abort.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

## Task 14: GH Action — include sidecar in artifact

**Files:**
- Modify: `.github/workflows/backup-staging-db.yml`

- [ ] **Step 1: Update the artifact upload step**

In `.github/workflows/backup-staging-db.yml`, change:

```yaml
      - name: Upload dump as workflow artifact
        uses: actions/upload-artifact@v4
        with:
          name: spiritolo-staging-dump-${{ github.run_id }}
          path: spiritolo-staging-*.dump
          retention-days: 7
          if-no-files-found: error
```

to:

```yaml
      - name: Upload dump + sidecar as workflow artifact
        uses: actions/upload-artifact@v4
        with:
          name: spiritolo-staging-dump-${{ github.run_id }}
          path: |
            spiritolo-staging-*.dump
            spiritolo-staging-*.dump.meta.json
          retention-days: 7
          if-no-files-found: error
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/backup-staging-db.yml
git commit -m "$(cat <<'EOF'
backup-staging-db workflow: include the .meta.json sidecar in the artifact

Both the .dump and its sidecar end up in the same artifact zip. Required
because the uploader refuses to run without the sidecar.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

## Task 15: Documentation

**Files:**
- Create: `docs/upload.md`
- Modify: `docs/backups.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Write `docs/upload.md`**

Create `docs/upload.md`:

````markdown
# Pushing local edits back to staging

End-to-end "back up staging → restore locally → run pipelines on local
→ push the diff back" workflow. Implements the model laid out in
[WORKFLOW_PLAN.md] (which gets deleted once Stage 3 ships).

## When to use this

You want to run a Supabase-writing pipeline (parser, mapper Phase 2,
normalize-names, cluster, …) without hitting staging directly — for
speed, for free-tier egress, or because you're iterating and may want
to throw the result away. The protected push at the end means an honest
mistake doesn't clobber the curation UI's edits.

You **don't** need this for read-only work, schema migrations (those
flow through `git push` to the `staging` branch and the
deploy-migrations workflow), or one-off SQL hand-edits to staging.

## The four steps

### 1. Take a backup

```bash
set -a && source /workspaces/spiritolo/.env && set +a
cd ~/somewhere-outside-the-repo
/workspaces/spiritolo/scripts/backup-supabase.sh
```

Produces two files:
```
spiritolo-staging-<UTC>.dump
spiritolo-staging-<UTC>.dump.meta.json
```

The sidecar carries the snapshot timestamp `T`, the staging URL
fingerprint, the applied-migration list, and integrity hashes. The
uploader requires both files. See
[scripts/src/upload_to_staging/sidecar.schema.json] for the schema.

### 2. Restore into local Supabase

Standard restore (same as before, only the .dump matters here):

```bash
# On Mac host:
supabase db reset --yes

# From devcontainer:
pg_restore \
  --dbname="$SUPABASE_DB_URL" \
  --clean --if-exists --no-owner --no-privileges \
  --single-transaction \
  ~/path/to/spiritolo-staging-*.dump
```

### 3. Run pipelines locally

Point pipelines at local (the default for `SUPABASE_DB_URL`) and run
freely. Borked the local DB? Re-restore the dump.

```bash
cd ingredients && uv run python -m ingredients.cli           # parser
cd ingredients && uv run python -m ingredients.cli map       # mapper Phase 1
# ... etc.
```

### 4. Push the diff back

```bash
cd /workspaces/spiritolo
uv run --package spiritolo-scripts python -m upload_to_staging \
  --dump ~/path/to/spiritolo-staging-<UTC>.dump
```

Without `--apply` the script prints a per-table dirty-row count and
exits. Add `--apply` to actually push:

```bash
uv run --package spiritolo-scripts python -m upload_to_staging \
  --dump ~/path/to/spiritolo-staging-<UTC>.dump \
  --apply
```

(`--yes` skips the y/N prompt.)

## What the uploader checks

In order, before any write:

1. Sidecar present and validates against the schema.
2. Dump file's sha256 matches sidecar (catches wrong file / corruption).
3. Dump's schema-only sha256 matches sidecar (catches archive
   tampering).
4. Staging URL's `host:dbname` fingerprint matches sidecar (catches
   pointing at the wrong project).
5. `supabase_migrations.schema_migrations` lists match exactly between
   the sidecar, local, and staging (catches a migration landing during
   the work session).
6. `max(updated_at)` on every owned staging table is `<= taken_at`
   (catches staging writes during the work session).

Any failure aborts with a precise message.

On `--apply`, the push runs inside a SERIALIZABLE transaction with
`SET CONSTRAINTS ALL DEFERRED`, re-verifies staleness, UPSERTs every
dirty row, resyncs sequences for the bigserial-PK tables, and commits.

## Honor system

The whole workflow assumes a single human writer (you). The staleness
check defends against accidental concurrent writes, but it can't help
if you ignore it: don't make a curation-UI edit to staging mid work
session, and if you do, re-take the backup before doing more work.

## When the uploader refuses

| Message starts with | What it means | What to do |
|---|---|---|
| `Sidecar not found` | The .meta.json is missing next to the dump | Re-take backup — older dumps predate this workflow. |
| `Dump file sha256 differs` | The .dump file isn't the one the sidecar describes | You probably grabbed the wrong file. |
| `Sidecar's staging fingerprint doesn't match` | --staging-db points at a different project than the dump | Confirm the URL. |
| `Migration list mismatch` | A migration ran on staging since the backup | Re-take backup. |
| `Staging was modified` | Someone wrote to staging after the backup | Re-take backup, redo work. |
| `Serialization conflict at COMMIT` | A concurrent staging write tripped SERIALIZABLE | Re-run --apply; if it persists, re-take backup. |

[WORKFLOW_PLAN.md]: ../WORKFLOW_PLAN.md
[scripts/src/upload_to_staging/sidecar.schema.json]: ../scripts/src/upload_to_staging/sidecar.schema.json
````

- [ ] **Step 2: Add a cross-reference to `docs/backups.md`**

Find the section "## Run a backup" and immediately above it, add:

```markdown
> **Pushing edits back to staging?** After restoring a backup locally,
> running pipelines, and wanting to upload the diff, see
> [docs/upload.md](upload.md). The backup script writes a sidecar
> metadata file alongside the .dump that the uploader requires.

```

- [ ] **Step 3: Add a section to `CLAUDE.md`**

Find the "## Data flow" section in `CLAUDE.md`. Immediately after it,
insert a new section:

````markdown
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
````

- [ ] **Step 4: Commit**

```bash
git add docs/upload.md docs/backups.md CLAUDE.md
git commit -m "$(cat <<'EOF'
Document the local-edit / staging-upload workflow

New docs/upload.md covers the full backup → restore → edit → upload
loop with concrete commands and the uploader's check pipeline. Adds a
cross-reference from docs/backups.md and a CLAUDE.md section for
agentic readers.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

## Task 16: Mark Stage 2 shipped, push, open PR B

**Files:**
- Modify: `WORKFLOW_PLAN.md`

- [ ] **Step 1: Update the Stage 2 heading**

Find:

```markdown
## Stage 2 — Build the uploader script
```

Change to:

```markdown
## Stage 2 — Build the uploader script *(shipped)*
```

- [ ] **Step 2: Commit**

```bash
git add WORKFLOW_PLAN.md
git commit -m "$(cat <<'EOF'
Mark Stage 2 (uploader) shipped in WORKFLOW_PLAN.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 3: Push and open PR**

```bash
git push -u origin claude/stage2-uploader-impl
gh pr create --base main --title "Stage 2: upload-to-staging script + sidecar + docs" --body "$(cat <<'EOF'
Implements the local-edit / staging-upload workflow (Stage 2 of WORKFLOW_PLAN.md).

- New `scripts/` workspace member containing the `upload_to_staging` package: argparse CLI, modular helpers (sidecar, dump, db, upsert, tables), JSON Schema for the .meta.json sidecar, smoke tests against two ephemeral DBs.
- `backup-supabase.sh` now writes a `.meta.json` sidecar next to every dump (taken_at, applied-migration list, sha256s, staging-URL fingerprint).
- GitHub Action artifact updated to include the sidecar.
- `docs/upload.md` covers the full backup → restore → edit → upload loop and the uploader's check pipeline; cross-referenced from docs/backups.md and CLAUDE.md.

Depends on the deferrable-FK pre-work having been deployed to staging. Spec at docs/superpowers/specs/2026-05-05-stage-2-uploader-design.md.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: Capture PR URL**

Note the PR URL printed by `gh pr create`. That's the user's checkpoint
to review and merge.

---

## After merge

After PR B merges to `main`, promote `main → staging` so Vercel and the
deploy-migrations workflow pick up any frontend / migration changes the
PRs may have touched (this PR has no migrations beyond PR A's
already-shipped one, but the merge promotion is the project's standard
post-merge ritual).

Then exercise the full workflow once end-to-end against real staging
(small, cosmetic edit to a single row) before declaring the workflow
"shipped" in the original spirit of the WORKFLOW_PLAN cleanup section.

---

# Self-review against spec

The plan covers every section of the spec:

- **Sidecar shape (Spec §"Sidecar metadata file")** — Task 6 (schema) +
  Task 7 (loader) + Task 12 (writer) + Task 6 (`$schema`).
- **Schema-version check B+ (Spec §"Order of operations" steps 4 & 2)**
  — Task 9 (`fetch_applied_migrations`) + Task 11 (CLI compares
  three-way) + Task 8 (`sha256_of_schema_only`).
- **Owned tables (Spec §"Owned tables")** — Task 5.
- **Pre-work A′ (Spec §"Migration 2")** — Phase 1 Tasks 1-3.
- **CLI shape (Spec §"CLI")** — Task 11.
- **Order of operations (Spec §"Order of operations")** — Task 11.
- **UPSERT + sequences (Spec §"Order of operations" step 8 + §"Owned
  tables" sequence column)** — Task 10 + Task 11.
- **Smoke tests (Spec §"Smoke tests")** — Task 13.
- **Backup script (Spec §"Backup script changes")** — Task 12.
- **GH Action (Spec §"GitHub Action changes")** — Task 14.
- **Docs (Spec §"Documentation deliverables")** — Task 15.
- **PR plan (Spec §"PR plan")** — Phase boundary + Tasks 3 and 16.

No placeholders, no "TBD", no "implement appropriate error handling"
hand-waves. Every code step has the actual code.
