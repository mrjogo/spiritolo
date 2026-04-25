# Ingredient Parser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a Zone-2 ingredient parser that reads `recipes` from Supabase, parses each `jsonld.recipeIngredient` string with strict abstain discipline, and writes structured rows to a new `recipe_ingredients` table — alongside extracting shared utilities into a new `common/` package and migrating `scraper` to depend on it.

**Architecture:** Three-package uv workspace at the repo root: `common/` (shared utilities), `scraper/` (existing Zone 1, migrated to depend on `common`), `ingredients/` (new Zone 2 reconciling worker). The parser is hand-rolled rules over a closed unit table; precision over recall — anything that does not cleanly match a rule lands in `parse_status='unparseable'`.

**Tech Stack:** Python 3.11+, uv (workspaces), psycopg, pytest, Supabase Postgres, `python-dotenv`. No ML libraries; no LLM. Deterministic regex rules only.

**Spec:** [docs/superpowers/specs/2026-04-25-ingredient-parser-design.md](../specs/2026-04-25-ingredient-parser-design.md)

---

## Notes for the engineer

- **Working directory.** All work happens inside the worktree at `.worktrees/ingredient-parser-spec/`. Use absolute or `cd`-prefixed paths in `git` commands.
- **Test discipline.** Never write the implementation before the failing test for new code. For *moves* (Phase 1), existing tests are the discipline — they MUST continue to pass after each move; if they fail, fix the move, do not weaken the tests.
- **Commit cadence.** One commit per task. Each commit message starts with a verb in lowercase imperative ("add", "move", "wire up").
- **Supabase.** Migrations apply via `supabase db reset --db-url ... --yes`. The local Supabase runs on the Mac host; the devcontainer connects via `host.docker.internal` (or its IPv4 `192.168.65.254` for migrations). See `CLAUDE.md` for details.
- **uv.** This repo currently has no root-level uv workspace. Phase 0 sets one up. After Phase 0, run all uv commands from the appropriate package directory (`common/`, `scraper/`, or `ingredients/`).

---

## Phase 0 — Workspace skeleton

### Task 0: Create root `pyproject.toml` declaring the uv workspace

**Files:**
- Create: `pyproject.toml` (repo root)

- [ ] **Step 1: Verify scraper tests still pass before any structural change**

```bash
cd scraper && uv run pytest -q
```

Expected: all green. (Captures the baseline; everything from here keeps it green.)

- [ ] **Step 2: Create the root pyproject**

Create `pyproject.toml` at the repo root with:

```toml
[tool.uv.workspace]
members = ["common", "scraper", "ingredients"]
```

That is the entire file. The root has no `[project]` table — it is a workspace declaration, not a publishable package.

- [ ] **Step 3: Confirm uv recognizes the workspace**

```bash
uv tree --workspace 2>&1 | head -20 || true
```

The command will fail until the member packages exist (Phase 1+), but it should not complain that the workspace file is malformed. We only care that the toml parses.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "add root pyproject declaring uv workspace"
```

---

## Phase 1 — `common/` package: extract shared utilities

The strategy in this phase is **move, not copy**. Each move task: create the new file under `common/src/spiritolo_common/`, move the test file to `common/tests/`, update its imports, run the new tests, delete the old scraper file, redirect every scraper import. Each task is one utility and ends with all scraper tests still passing.

### Task 1: Create `common/` package skeleton

**Files:**
- Create: `common/pyproject.toml`
- Create: `common/src/spiritolo_common/__init__.py`
- Create: `common/tests/__init__.py`
- Create: `common/tests/conftest.py`

- [ ] **Step 1: Create `common/pyproject.toml`**

```toml
[project]
name = "spiritolo-common"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "psycopg[binary]>=3.2",
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

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Create empty package init**

Create `common/src/spiritolo_common/__init__.py` with:

```python
"""Shared utilities used by spiritolo-scraper and spiritolo-ingredients."""
```

- [ ] **Step 3: Create empty tests init and conftest**

Create `common/tests/__init__.py` as an empty file (one newline).

Create `common/tests/conftest.py` with:

```python
"""Pytest configuration for spiritolo-common tests."""
```

- [ ] **Step 4: Verify the skeleton installs cleanly**

```bash
cd common && uv sync --extra dev
```

Expected: a `.venv` is created, `pytest` is available; `uv run pytest -q` reports `no tests ran` (zero tests, zero errors).

- [ ] **Step 5: Commit**

```bash
git add common/
git commit -m "scaffold spiritolo-common package"
```

---

### Task 2: Move `progress.py` to `common`

**Files:**
- Create: `common/src/spiritolo_common/progress.py`
- Create: `common/tests/test_progress.py`
- Delete: `scraper/src/progress.py`
- Delete: `scraper/tests/test_progress.py`
- Modify: every scraper file importing `scraper.src.progress`

- [ ] **Step 1: Copy the file to its new home**

Copy `scraper/src/progress.py` verbatim to `common/src/spiritolo_common/progress.py`. No content change — this is a pure relocation.

- [ ] **Step 2: Copy the test file to its new home**

Copy `scraper/tests/test_progress.py` to `common/tests/test_progress.py`, then change the one import line:

```python
from scraper.src.progress import PROGRESS_EVERY, format_eta, make_progress
```

becomes:

```python
from spiritolo_common.progress import PROGRESS_EVERY, format_eta, make_progress
```

- [ ] **Step 3: Run the relocated tests in the new package**

```bash
cd common && uv run pytest tests/test_progress.py -v
```

Expected: every test passes. (This is the "new code passes" gate before we touch scraper imports.)

- [ ] **Step 4: Find every scraper import of `scraper.src.progress`**

```bash
cd .. && grep -rn "scraper.src.progress" scraper/
```

Note each file. There are at least: `scraper/src/extract.py`, `scraper/src/classify.py`, `scraper/src/validate.py`, `scraper/src/fetch.py`, plus their tests.

- [ ] **Step 5: Update each scraper import**

For every file printed in step 4, replace:

```python
from scraper.src.progress import ...
```

with:

```python
from spiritolo_common.progress import ...
```

Do not change anything else in those files.

- [ ] **Step 6: Add `spiritolo-common` as a scraper dependency**

In `scraper/pyproject.toml`, add `"spiritolo-common"` to `dependencies`, and add a `[tool.uv.sources]` table mapping it to the workspace:

```toml
[project]
# ... existing fields ...
dependencies = [
    "spiritolo-common",      # NEW
    "requests>=2.31",
    "lxml>=5.0",
    # ... rest unchanged ...
]

# Append at the end of the file:
[tool.uv.sources]
spiritolo-common = { workspace = true }
```

- [ ] **Step 7: Re-sync scraper and run its full test suite**

```bash
cd scraper && uv sync --extra dev && uv run pytest -q
```

Expected: every test passes. If anything fails, do not weaken the test — find the broken import, fix it, re-run.

- [ ] **Step 8: Delete the now-unused scraper files**

```bash
cd .. && rm scraper/src/progress.py scraper/tests/test_progress.py
```

- [ ] **Step 9: Re-run scraper tests one more time to confirm nothing referenced the deleted files**

```bash
cd scraper && uv run pytest -q
```

Expected: green.

- [ ] **Step 10: Commit**

```bash
cd .. && git add common/src/spiritolo_common/progress.py common/tests/test_progress.py scraper/
git commit -m "move progress utility to spiritolo-common"
```

---

### Task 3: Move `summary.py` to `common`

**Files:**
- Create: `common/src/spiritolo_common/summary.py`
- Create: `common/tests/test_summary.py`
- Delete: `scraper/src/summary.py`
- Delete: `scraper/tests/test_summary.py`
- Modify: every scraper file importing `scraper.src.summary`

- [ ] **Step 1: Copy file to new home**

Copy `scraper/src/summary.py` verbatim to `common/src/spiritolo_common/summary.py`.

- [ ] **Step 2: Copy test file with import rewrite**

Copy `scraper/tests/test_summary.py` to `common/tests/test_summary.py`. Replace `from scraper.src.summary import ...` with `from spiritolo_common.summary import ...`. Nothing else changes.

- [ ] **Step 3: Run new tests**

```bash
cd common && uv run pytest tests/test_summary.py -v
```

Expected: all green.

- [ ] **Step 4: Rewrite scraper imports**

```bash
cd .. && grep -rln "scraper.src.summary" scraper/ | xargs sed -i.bak 's|from scraper\.src\.summary|from spiritolo_common.summary|g'
find scraper -name "*.bak" -delete
```

(Or rewrite each file by hand if `sed` quoting is uncomfortable. The end state must have zero `scraper.src.summary` references.)

- [ ] **Step 5: Run scraper tests**

```bash
cd scraper && uv run pytest -q
```

Expected: green.

- [ ] **Step 6: Delete old scraper files**

```bash
cd .. && rm scraper/src/summary.py scraper/tests/test_summary.py
```

- [ ] **Step 7: Re-run scraper tests**

```bash
cd scraper && uv run pytest -q
```

Expected: green.

- [ ] **Step 8: Commit**

```bash
cd .. && git add -A
git commit -m "move summary printer to spiritolo-common"
```

---

### Task 4: Move `cli_common.py` to `common`

**Files:**
- Create: `common/src/spiritolo_common/cli_common.py`
- Create: `common/tests/test_cli_common.py`
- Delete: `scraper/src/cli_common.py`
- Delete: `scraper/tests/test_cli_common.py`
- Modify: every scraper file importing `scraper.src.cli_common`

- [ ] **Step 1: Copy file**

Copy `scraper/src/cli_common.py` verbatim to `common/src/spiritolo_common/cli_common.py`.

- [ ] **Step 2: Copy test file with rewrite**

Copy `scraper/tests/test_cli_common.py` to `common/tests/test_cli_common.py`. Rewrite `from scraper.src.cli_common import ...` → `from spiritolo_common.cli_common import ...`.

- [ ] **Step 3: Run new tests**

```bash
cd common && uv run pytest tests/test_cli_common.py -v
```

Expected: green.

- [ ] **Step 4: Rewrite scraper imports**

```bash
cd .. && grep -rln "scraper.src.cli_common" scraper/ | xargs sed -i.bak 's|from scraper\.src\.cli_common|from spiritolo_common.cli_common|g'
find scraper -name "*.bak" -delete
```

- [ ] **Step 5: Run scraper tests**

```bash
cd scraper && uv run pytest -q
```

Expected: green.

- [ ] **Step 6: Delete old scraper files**

```bash
cd .. && rm scraper/src/cli_common.py scraper/tests/test_cli_common.py
```

- [ ] **Step 7: Re-run scraper tests**

```bash
cd scraper && uv run pytest -q
```

Expected: green.

- [ ] **Step 8: Commit**

```bash
cd .. && git add -A
git commit -m "move cli_common helpers to spiritolo-common"
```

---

### Task 5: Move `supabase_client.py` to `common`

**Files:**
- Create: `common/src/spiritolo_common/supabase_client.py`
- Create: `common/tests/test_supabase_client.py` (only if a corresponding test exists in scraper; check first)
- Delete: `scraper/src/supabase_client.py`
- Delete: `scraper/tests/test_supabase_client.py` (only if it exists)
- Modify: every scraper file importing `scraper.src.supabase_client`

- [ ] **Step 1: Copy file and adjust the .env path**

Copy `scraper/src/supabase_client.py` to `common/src/spiritolo_common/supabase_client.py`. **One change:** the original file resolves `.env` with `Path(__file__).resolve().parent.parent.parent / ".env"` — that walks up three levels from `scraper/src/supabase_client.py` to the repo root. The new location is one level deeper (`common/src/spiritolo_common/supabase_client.py`), so the new path needs an extra `.parent`:

```python
load_dotenv(Path(__file__).resolve().parent.parent.parent.parent / ".env")
```

That is the only diff between the two files. Verify with:

```bash
diff scraper/src/supabase_client.py common/src/spiritolo_common/supabase_client.py
```

Expected: a one-line difference on the `load_dotenv(...)` call.

- [ ] **Step 2: Move tests if any exist**

Check whether a test file exists for the supabase client:

```bash
ls scraper/tests/test_supabase_client.py 2>/dev/null && echo exists || echo none
```

- If it exists: copy to `common/tests/test_supabase_client.py` with the import rewrite (`scraper.src.supabase_client` → `spiritolo_common.supabase_client`); run `cd common && uv run pytest tests/test_supabase_client.py -v` — expect green; delete the original after.
- If it does not exist: skip this step.

- [ ] **Step 3: Rewrite scraper imports**

```bash
cd .. && grep -rln "scraper.src.supabase_client" scraper/ | xargs sed -i.bak 's|from scraper\.src\.supabase_client|from spiritolo_common.supabase_client|g'
find scraper -name "*.bak" -delete
```

- [ ] **Step 4: Run scraper tests**

```bash
cd scraper && uv run pytest -q
```

Expected: green. The integration tests that hit Supabase only run when `SUPABASE_DB_URL` is set; if it is set, those should also pass — they prove the moved client connects from its new home.

- [ ] **Step 5: Delete old scraper file**

```bash
cd .. && rm scraper/src/supabase_client.py
```

- [ ] **Step 6: Re-run scraper tests**

```bash
cd scraper && uv run pytest -q
```

Expected: green.

- [ ] **Step 7: Commit**

```bash
cd .. && git add -A
git commit -m "move supabase client to spiritolo-common"
```

---

## Phase 2 — Database migration

### Task 6: Add the `recipe_ingredients` migration

**Files:**
- Create: `supabase/migrations/20260425120000_create_recipe_ingredients.sql`

- [ ] **Step 1: Create the migration file**

Write `supabase/migrations/20260425120000_create_recipe_ingredients.sql` with:

```sql
create table recipe_ingredients (
  id              bigserial primary key,
  recipe_id       bigint not null references recipes(id) on delete cascade,
  position        int not null,
  raw_text        text not null,
  amount          numeric,
  amount_max      numeric,
  unit            text,
  name            text,
  modifier        text,
  parse_status    text not null check (parse_status in ('parsed', 'unparseable')),
  parser_rule     text,
  parser_version  text not null,
  parsed_at       timestamptz not null default now(),

  unique (recipe_id, position)
);

create index recipe_ingredients_recipe_idx on recipe_ingredients (recipe_id);
create index recipe_ingredients_name_idx   on recipe_ingredients (name) where name is not null;
create index recipe_ingredients_unit_idx   on recipe_ingredients (unit) where unit is not null;

-- RLS off; nothing public reads this table yet.
alter table recipe_ingredients enable row level security;
```

- [ ] **Step 2: Apply the migration to local Supabase**

From the devcontainer:

```bash
supabase db reset \
  --db-url "postgresql://postgres:postgres@192.168.65.254:54322/postgres" \
  --yes
```

(May print a misleading `tls error` at the end — verify success below.)

From the host:

```bash
supabase db reset --yes
```

- [ ] **Step 3: Verify the table exists**

```bash
psql "postgresql://postgres:postgres@localhost:54322/postgres" -c "\d recipe_ingredients"
```

Expected: column listing matches the migration. `recipes` count drops back to whatever the seed produces; users will need to re-extract.

- [ ] **Step 4: Commit**

```bash
git add supabase/migrations/20260425120000_create_recipe_ingredients.sql
git commit -m "add recipe_ingredients migration"
```

---

## Phase 3 — `ingredients/` package: parser core

This phase builds the pure parser as a leaf module with zero I/O. Every task here is TDD.

### Task 7: Create `ingredients/` package skeleton

**Files:**
- Create: `ingredients/pyproject.toml`
- Create: `ingredients/src/ingredients/__init__.py`
- Create: `ingredients/tests/__init__.py`
- Create: `ingredients/tests/conftest.py`

- [ ] **Step 1: Create pyproject**

Create `ingredients/pyproject.toml`:

```toml
[project]
name = "spiritolo-ingredients"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "spiritolo-common",
    "psycopg[binary]>=3.2",
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

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.uv.sources]
spiritolo-common = { workspace = true }
```

- [ ] **Step 2: Create package init**

Create `ingredients/src/ingredients/__init__.py`:

```python
"""Spiritolo ingredient parser — Zone-2 reconciling worker.

Reads recipes from Supabase, parses each recipeIngredient string with
strict abstain discipline, writes structured rows to recipe_ingredients.
"""
```

- [ ] **Step 3: Create tests init and conftest**

`ingredients/tests/__init__.py`: empty file (one newline).
`ingredients/tests/conftest.py`:

```python
"""Pytest configuration for spiritolo-ingredients tests."""
```

- [ ] **Step 4: Verify install**

```bash
cd ingredients && uv sync --extra dev && uv run pytest -q
```

Expected: package installs cleanly, `spiritolo-common` resolves via the workspace, `no tests ran`.

- [ ] **Step 5: Commit**

```bash
cd .. && git add ingredients/
git commit -m "scaffold spiritolo-ingredients package"
```

---

### Task 8: Define `units.py` — closed unit and count-noun tables

**Files:**
- Create: `ingredients/src/ingredients/units.py`
- Create: `ingredients/tests/test_units.py`

- [ ] **Step 1: Write the failing tests**

Create `ingredients/tests/test_units.py`:

```python
from ingredients.units import (
    canonicalize_unit,
    canonicalize_count_noun,
    is_unit_alias,
    is_count_noun_alias,
)


def test_canonicalize_unit_volume_aliases():
    assert canonicalize_unit("oz") == "oz"
    assert canonicalize_unit("oz.") == "oz"
    assert canonicalize_unit("ounce") == "oz"
    assert canonicalize_unit("Ounces") == "oz"
    assert canonicalize_unit("fl oz") == "oz"
    assert canonicalize_unit("ml") == "ml"
    assert canonicalize_unit("mL") == "ml"
    assert canonicalize_unit("cl") == "cl"
    assert canonicalize_unit("tsp") == "tsp"
    assert canonicalize_unit("teaspoon") == "tsp"
    assert canonicalize_unit("tablespoons") == "tbsp"
    assert canonicalize_unit("cup") == "cup"
    assert canonicalize_unit("cups") == "cup"


def test_canonicalize_unit_bartending():
    assert canonicalize_unit("dash") == "dash"
    assert canonicalize_unit("dashes") == "dash"
    assert canonicalize_unit("drop") == "drop"
    assert canonicalize_unit("drops") == "drop"
    assert canonicalize_unit("splash") == "splash"
    assert canonicalize_unit("barspoon") == "barspoon"
    assert canonicalize_unit("pinch") == "pinch"
    assert canonicalize_unit("part") == "part"
    assert canonicalize_unit("parts") == "part"


def test_canonicalize_unit_unknown_returns_none():
    assert canonicalize_unit("squeeze") is None
    assert canonicalize_unit("handful") is None
    assert canonicalize_unit("") is None
    assert canonicalize_unit("bourbon") is None


def test_is_unit_alias():
    assert is_unit_alias("oz")
    assert is_unit_alias("OUNCES")
    assert not is_unit_alias("squeeze")


def test_canonicalize_count_noun():
    assert canonicalize_count_noun("leaf") == "leaf"
    assert canonicalize_count_noun("leaves") == "leaf"
    assert canonicalize_count_noun("Slice") == "slice"
    assert canonicalize_count_noun("wedges") == "wedge"
    assert canonicalize_count_noun("cubes") == "cube"
    assert canonicalize_count_noun("egg white") == "egg white"
    assert canonicalize_count_noun("sprigs") == "sprig"


def test_canonicalize_count_noun_unknown_returns_none():
    assert canonicalize_count_noun("bourbon") is None
    assert canonicalize_count_noun("") is None


def test_is_count_noun_alias():
    assert is_count_noun_alias("leaves")
    assert not is_count_noun_alias("oz")
```

- [ ] **Step 2: Run the tests; expect failures**

```bash
cd ingredients && uv run pytest tests/test_units.py -v
```

Expected: all fail with `ModuleNotFoundError: No module named 'ingredients.units'`.

- [ ] **Step 3: Implement `units.py`**

Create `ingredients/src/ingredients/units.py`:

```python
"""Closed vocabulary tables for the ingredient parser.

Editing these tables is a parser logic change — bump PARSER_VERSION in
parser.py whenever you add or remove an alias.
"""

from __future__ import annotations

# Surface form -> canonical unit. Keys are matched case-insensitively.
UNIT_ALIASES: dict[str, str] = {
    # volume
    "oz": "oz", "oz.": "oz", "ounce": "oz", "ounces": "oz",
    "fl oz": "oz", "fl. oz.": "oz", "fl oz.": "oz",
    "fluid ounce": "oz", "fluid ounces": "oz",
    "ml": "ml", "ml.": "ml",
    "cl": "cl",
    "l": "l", "liter": "l", "liters": "l", "litre": "l", "litres": "l",
    "tsp": "tsp", "tsp.": "tsp", "teaspoon": "tsp", "teaspoons": "tsp",
    "tbsp": "tbsp", "tbsp.": "tbsp", "tablespoon": "tbsp", "tablespoons": "tbsp",
    "cup": "cup", "cups": "cup",
    # bartending counts treated as units
    "dash": "dash", "dashes": "dash",
    "drop": "drop", "drops": "drop",
    "splash": "splash", "splashes": "splash",
    "barspoon": "barspoon", "barspoons": "barspoon",
    "pinch": "pinch", "pinches": "pinch",
    "part": "part", "parts": "part",
    "jigger": "jigger", "jiggers": "jigger",
    "pony": "pony", "ponies": "pony",
}

# Surface form -> canonical count noun. Same lookup discipline.
COUNT_NOUN_ALIASES: dict[str, str] = {
    "leaf": "leaf", "leaves": "leaf",
    "slice": "slice", "slices": "slice",
    "wedge": "wedge", "wedges": "wedge",
    "wheel": "wheel", "wheels": "wheel",
    "stick": "stick", "sticks": "stick",
    "cube": "cube", "cubes": "cube",
    "sprig": "sprig", "sprigs": "sprig",
    "piece": "piece", "pieces": "piece",
    "egg white": "egg white", "egg whites": "egg white",
    "egg yolk": "egg yolk", "egg yolks": "egg yolk",
    "egg": "egg", "eggs": "egg",
    "twist": "twist", "twists": "twist",
}


def canonicalize_unit(surface: str) -> str | None:
    if not surface:
        return None
    return UNIT_ALIASES.get(surface.lower())


def canonicalize_count_noun(surface: str) -> str | None:
    if not surface:
        return None
    return COUNT_NOUN_ALIASES.get(surface.lower())


def is_unit_alias(surface: str) -> bool:
    return canonicalize_unit(surface) is not None


def is_count_noun_alias(surface: str) -> bool:
    return canonicalize_count_noun(surface) is not None
```

- [ ] **Step 4: Run tests; expect pass**

```bash
uv run pytest tests/test_units.py -v
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
cd .. && git add ingredients/src/ingredients/units.py ingredients/tests/test_units.py
git commit -m "add units and count-noun alias tables"
```

---

### Task 9: Define `ParseResult` dataclass and `pre_clean()` hygiene step

**Files:**
- Create: `ingredients/src/ingredients/parser.py`
- Create: `ingredients/tests/test_pre_clean.py`

- [ ] **Step 1: Write failing tests**

Create `ingredients/tests/test_pre_clean.py`:

```python
from ingredients.parser import pre_clean, ParseResult, PARSER_VERSION


def test_parser_version_is_a_nonempty_string():
    assert isinstance(PARSER_VERSION, str)
    assert PARSER_VERSION


def test_pre_clean_unicode_fractions_to_ascii():
    assert pre_clean("½ oz gin") == "1/2 oz gin"
    assert pre_clean("¾ ounce rye") == "3/4 ounce rye"
    assert pre_clean("⅓ cup sugar") == "1/3 cup sugar"


def test_pre_clean_collapses_whitespace():
    assert pre_clean("1   oz   gin") == "1 oz gin"
    assert pre_clean("1\toz\tgin") == "1 oz gin"


def test_pre_clean_strips_outer_whitespace_and_punct():
    assert pre_clean("  1 oz gin  ") == "1 oz gin"
    assert pre_clean("1 oz gin,") == "1 oz gin"
    assert pre_clean("1 oz gin.") == "1 oz gin"


def test_pre_clean_preserves_inner_punct():
    assert pre_clean("1 oz gin (such as Beefeater)") == "1 oz gin (such as Beefeater)"


def test_pre_clean_nfkc_normalizes():
    # U+00BD (½) handled; also non-breaking space (U+00A0) becomes regular space.
    assert pre_clean("1 oz gin") == "1 oz gin"


def test_parse_result_default_shape():
    r = ParseResult(raw_text="x", parse_status="unparseable")
    assert r.raw_text == "x"
    assert r.parse_status == "unparseable"
    assert r.parser_rule is None
    assert r.amount is None
    assert r.amount_max is None
    assert r.unit is None
    assert r.name is None
    assert r.modifier is None
```

- [ ] **Step 2: Run; expect fail**

```bash
cd ingredients && uv run pytest tests/test_pre_clean.py -v
```

Expected: `ModuleNotFoundError: No module named 'ingredients.parser'`.

- [ ] **Step 3: Implement `parser.py` (skeleton + pre_clean)**

Create `ingredients/src/ingredients/parser.py`:

```python
"""Ingredient string parser. Pure functions, no I/O.

See docs/superpowers/specs/2026-04-25-ingredient-parser-design.md for the
parser ladder. Bump PARSER_VERSION whenever any rule's behavior changes
(including unit-table edits, regex changes, new rules).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

PARSER_VERSION = "v1"


@dataclass
class ParseResult:
    raw_text: str
    parse_status: str  # 'parsed' | 'unparseable'
    parser_rule: str | None = None
    amount: float | None = None
    amount_max: float | None = None
    unit: str | None = None
    name: str | None = None
    modifier: str | None = None  # v1: always None


_UNICODE_FRACTIONS = {
    "¼": "1/4", "½": "1/2", "¾": "3/4",
    "⅐": "1/7", "⅑": "1/9", "⅒": "1/10",
    "⅓": "1/3", "⅔": "2/3",
    "⅕": "1/5", "⅖": "2/5", "⅗": "3/5", "⅘": "4/5",
    "⅙": "1/6", "⅚": "5/6",
    "⅛": "1/8", "⅜": "3/8", "⅝": "5/8", "⅞": "7/8",
}

_TRIM_PUNCT = ",.;:"


def pre_clean(s: str) -> str:
    """Normalize a raw ingredient string for downstream rule matching.

    Idempotent. Lossy only in trivial ways (whitespace, trailing punct).
    The original string is preserved in ParseResult.raw_text for audit.
    """
    if s is None:
        return ""
    # NFKC: collapses non-breaking spaces, normalizes width forms.
    s = unicodedata.normalize("NFKC", s)
    # Replace unicode fraction chars with ASCII fractions.
    for u, ascii_frac in _UNICODE_FRACTIONS.items():
        if u in s:
            s = s.replace(u, ascii_frac)
    # Collapse all whitespace runs to single space; strip outer.
    s = re.sub(r"\s+", " ", s).strip()
    # Strip trailing junk punctuation.
    while s and s[-1] in _TRIM_PUNCT:
        s = s[:-1].rstrip()
    # And leading.
    while s and s[0] in _TRIM_PUNCT:
        s = s[1:].lstrip()
    return s
```

- [ ] **Step 4: Run; expect pass**

```bash
uv run pytest tests/test_pre_clean.py -v
```

Expected: green.

- [ ] **Step 5: Commit**

```bash
cd .. && git add ingredients/src/ingredients/parser.py ingredients/tests/test_pre_clean.py
git commit -m "add ParseResult and pre_clean hygiene"
```

---

### Task 10: Add quantity sub-parser

**Files:**
- Modify: `ingredients/src/ingredients/parser.py` (append `parse_quantity`)
- Create: `ingredients/tests/test_parse_quantity.py`

- [ ] **Step 1: Write failing tests**

Create `ingredients/tests/test_parse_quantity.py`:

```python
from ingredients.parser import parse_quantity


def test_integer():
    assert parse_quantity("3 oz gin") == (3.0, None, 1)


def test_decimal():
    assert parse_quantity("0.25 cup honey") == (0.25, None, 4)
    assert parse_quantity("1.5 oz") == (1.5, None, 3)


def test_fraction():
    assert parse_quantity("1/2 oz") == (0.5, None, 3)
    assert parse_quantity("3/4 oz") == (0.75, None, 3)


def test_mixed_number():
    assert parse_quantity("1 1/2 oz gin") == (1.5, None, 5)
    assert parse_quantity("2 3/4 cups") == (2.75, None, 5)


def test_range_with_to():
    assert parse_quantity("1/2 to 3/4 oz") == (0.5, 0.75, 10)
    assert parse_quantity("1 to 2 oz") == (1.0, 2.0, 6)


def test_range_with_dash():
    """Some sites write '1-2 oz' instead of '1 to 2 oz'. Treat as range."""
    assert parse_quantity("1-2 oz") == (1.0, 2.0, 3)


def test_no_quantity_prefix_returns_none():
    assert parse_quantity("Garnish: lemon twist") is None
    assert parse_quantity("ice") is None
    assert parse_quantity("") is None
    assert parse_quantity("oz gin") is None


def test_quantity_with_no_following_text():
    """A quantity at end of string still parses; consumer decides if useful."""
    assert parse_quantity("2") == (2.0, None, 1)
    assert parse_quantity("1/2") == (0.5, None, 3)
```

- [ ] **Step 2: Run; expect fail**

```bash
cd ingredients && uv run pytest tests/test_parse_quantity.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Implement**

Append to `ingredients/src/ingredients/parser.py`:

```python
# Atomic numeric token: integer, decimal, fraction, or mixed number.
# Mixed and fraction must come BEFORE plain integer in alternations.
_NUM_ATOM = r"(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)"
_QTY_RE = re.compile(rf"^(?P<a>{_NUM_ATOM})(?:\s*(?:to|-)\s*(?P<b>{_NUM_ATOM}))?")


def _atom_to_float(token: str) -> float:
    token = token.strip()
    if " " in token:
        whole, frac = token.split(None, 1)
        num, den = frac.split("/")
        return float(whole) + float(num) / float(den)
    if "/" in token:
        num, den = token.split("/")
        return float(num) / float(den)
    return float(token)


def parse_quantity(s: str) -> tuple[float, float | None, int] | None:
    """Match a leading quantity in s.

    Returns (amount, amount_max, end_index) where end_index is the position
    in s immediately after the matched quantity. Returns None when s does
    not start with a recognizable quantity.

    amount_max is non-None only for ranges ('1/2 to 3/4', '1-2').
    """
    m = _QTY_RE.match(s)
    if not m:
        return None
    a = _atom_to_float(m.group("a"))
    b = _atom_to_float(m.group("b")) if m.group("b") else None
    return a, b, m.end()
```

- [ ] **Step 4: Run; expect pass**

```bash
uv run pytest tests/test_parse_quantity.py -v
```

Expected: green.

- [ ] **Step 5: Commit**

```bash
cd .. && git add ingredients/src/ingredients/parser.py ingredients/tests/test_parse_quantity.py
git commit -m "add quantity sub-parser (int/decimal/fraction/mixed/range)"
```

---

### Task 11: Add the `garnish_prefix` rule

**Files:**
- Modify: `ingredients/src/ingredients/parser.py` (append rule + `parse`)
- Create: `ingredients/tests/test_rule_garnish_prefix.py`

This task introduces the public `parse()` orchestrator with a single rule. Subsequent rule tasks (12, 13, 14) extend the orchestrator.

- [ ] **Step 1: Write failing tests**

Create `ingredients/tests/test_rule_garnish_prefix.py`:

```python
from ingredients.parser import parse


def test_garnish_prefix_basic():
    r = parse("Garnish: lemon twist")
    assert r.parse_status == "parsed"
    assert r.parser_rule == "garnish_prefix"
    assert r.amount is None
    assert r.unit is None
    assert r.name == "lemon twist"


def test_garnish_prefix_case_insensitive():
    r = parse("garnish: orange peel")
    assert r.parse_status == "parsed"
    assert r.parser_rule == "garnish_prefix"
    assert r.name == "orange peel"


def test_garnish_prefix_with_extra_spaces():
    r = parse("Garnish:   pineapple leaf")
    assert r.parse_status == "parsed"
    assert r.parser_rule == "garnish_prefix"
    assert r.name == "pineapple leaf"


def test_garnish_prefix_lowercases_name():
    r = parse("Garnish: Cinnamon Stick")
    assert r.name == "cinnamon stick"


def test_garnish_prefix_empty_name_abstains():
    """A bare 'Garnish:' with no text after must not parse to an empty name."""
    r = parse("Garnish:")
    assert r.parse_status == "unparseable"


def test_no_garnish_prefix_leaves_unparseable_for_now():
    """Other rules don't exist yet; non-matching strings stay unparseable."""
    r = parse("1 oz gin")
    assert r.parse_status == "unparseable"


def test_raw_text_preserved_on_parse():
    r = parse("Garnish: lemon twist")
    assert r.raw_text == "Garnish: lemon twist"


def test_raw_text_preserved_on_unparseable():
    r = parse("¯\\_(ツ)_/¯")
    assert r.raw_text == "¯\\_(ツ)_/¯"
    assert r.parse_status == "unparseable"
```

- [ ] **Step 2: Run; expect fail**

```bash
cd ingredients && uv run pytest tests/test_rule_garnish_prefix.py -v
```

Expected: `ImportError` on `parse`.

- [ ] **Step 3: Implement**

Append to `ingredients/src/ingredients/parser.py`:

```python
_GARNISH_PREFIX_RE = re.compile(r"^garnish\s*:\s*(?P<name>.+)$", re.IGNORECASE)


def _try_garnish_prefix(cleaned: str, raw: str) -> ParseResult | None:
    m = _GARNISH_PREFIX_RE.match(cleaned)
    if not m:
        return None
    name = m.group("name").strip().lower()
    if not name:
        return None
    return ParseResult(
        raw_text=raw,
        parse_status="parsed",
        parser_rule="garnish_prefix",
        name=name,
    )


_RULES = [
    _try_garnish_prefix,
]


def parse(raw: str, site: str | None = None) -> ParseResult:
    """Apply the parser ladder to `raw`. Returns ParseResult; never raises.

    `site` is informational only; rules may use it to dispatch quirks but
    must not relax strictness based on it.
    """
    cleaned = pre_clean(raw)
    if not cleaned:
        return ParseResult(raw_text=raw, parse_status="unparseable")
    for rule in _RULES:
        result = rule(cleaned, raw)
        if result is not None:
            return result
    return ParseResult(raw_text=raw, parse_status="unparseable")
```

- [ ] **Step 4: Run; expect pass**

```bash
uv run pytest tests/test_rule_garnish_prefix.py -v
```

Expected: green.

- [ ] **Step 5: Commit**

```bash
cd .. && git add ingredients/src/ingredients/parser.py ingredients/tests/test_rule_garnish_prefix.py
git commit -m "add garnish_prefix rule and parse() orchestrator"
```

---

### Task 12: Add the `topup` rule

**Files:**
- Modify: `ingredients/src/ingredients/parser.py`
- Create: `ingredients/tests/test_rule_topup.py`

- [ ] **Step 1: Write failing tests**

Create `ingredients/tests/test_rule_topup.py`:

```python
from ingredients.parser import parse


def test_topup_basic():
    r = parse("Top up with Brut sparkling wine")
    assert r.parse_status == "parsed"
    assert r.parser_rule == "topup"
    assert r.amount is None
    assert r.unit is None
    assert r.name == "brut sparkling wine"


def test_topup_case_insensitive():
    r = parse("top up with ginger beer")
    assert r.parse_status == "parsed"
    assert r.parser_rule == "topup"
    assert r.name == "ginger beer"


def test_topup_with_parenthetical():
    r = parse("Top up with Soda (club soda) water")
    assert r.parse_status == "parsed"
    assert r.parser_rule == "topup"
    assert r.name == "soda (club soda) water"


def test_topup_empty_name_abstains():
    r = parse("Top up with")
    assert r.parse_status == "unparseable"


def test_topup_does_not_match_just_top():
    r = parse("Topping: cherries")
    assert r.parse_status == "unparseable"
```

- [ ] **Step 2: Run; expect fail**

```bash
cd ingredients && uv run pytest tests/test_rule_topup.py -v
```

- [ ] **Step 3: Implement**

In `ingredients/src/ingredients/parser.py`, add (after `_try_garnish_prefix`):

```python
_TOPUP_RE = re.compile(r"^top up with\s+(?P<name>.+)$", re.IGNORECASE)


def _try_topup(cleaned: str, raw: str) -> ParseResult | None:
    m = _TOPUP_RE.match(cleaned)
    if not m:
        return None
    name = m.group("name").strip().lower()
    if not name:
        return None
    return ParseResult(
        raw_text=raw,
        parse_status="parsed",
        parser_rule="topup",
        name=name,
    )
```

Update `_RULES` to:

```python
_RULES = [
    _try_garnish_prefix,
    _try_topup,
]
```

- [ ] **Step 4: Run; expect pass**

```bash
uv run pytest tests/test_rule_topup.py tests/test_rule_garnish_prefix.py -v
```

Expected: green (both rules' tests).

- [ ] **Step 5: Commit**

```bash
cd .. && git add ingredients/src/ingredients/parser.py ingredients/tests/test_rule_topup.py
git commit -m "add topup rule"
```

---

### Task 13: Add the `qty_unit` rule (the 90% case)

**Files:**
- Modify: `ingredients/src/ingredients/parser.py`
- Create: `ingredients/tests/test_rule_qty_unit.py`

- [ ] **Step 1: Write failing tests**

Create `ingredients/tests/test_rule_qty_unit.py`:

```python
from ingredients.parser import parse


def _assert_parsed(r, *, amount, unit, name, amount_max=None):
    assert r.parse_status == "parsed", f"unexpected unparseable: {r}"
    assert r.parser_rule == "qty_unit", f"wrong rule: {r.parser_rule}"
    assert r.amount == amount
    assert r.amount_max == amount_max
    assert r.unit == unit
    assert r.name == name


def test_simple_oz():
    _assert_parsed(parse("2 oz gin"), amount=2.0, unit="oz", name="gin")


def test_decimal_oz_period_alias():
    _assert_parsed(parse("0.5 oz. rye"), amount=0.5, unit="oz", name="rye")


def test_mixed_number_ounce_word():
    _assert_parsed(parse("1 1/2 ounces lime juice"), amount=1.5, unit="oz", name="lime juice")


def test_unicode_fraction_normalized_then_parsed():
    _assert_parsed(parse("¾ ounce campari"), amount=0.75, unit="oz", name="campari")


def test_ml_canonicalizes():
    _assert_parsed(parse("45 ml Light gold rum 1-3yo"),
                   amount=45.0, unit="ml", name="light gold rum 1-3yo")


def test_cl_canonicalizes():
    _assert_parsed(parse("4 cl gin"), amount=4.0, unit="cl", name="gin")


def test_teaspoon_canonicalizes():
    _assert_parsed(parse("1 teaspoon honey"), amount=1.0, unit="tsp", name="honey")
    _assert_parsed(parse("2 tsp. honey"), amount=2.0, unit="tsp", name="honey")


def test_tablespoon_canonicalizes():
    _assert_parsed(parse("3 tablespoons sugar"), amount=3.0, unit="tbsp", name="sugar")


def test_cup_canonicalizes():
    _assert_parsed(parse("1/4 cup honey"), amount=0.25, unit="cup", name="honey")


def test_dash_drop_splash():
    _assert_parsed(parse("1 dash Aromatic bitters"), amount=1.0, unit="dash", name="aromatic bitters")
    _assert_parsed(parse("3 drops Xocolatl mole bitters"), amount=3.0, unit="drop", name="xocolatl mole bitters")
    _assert_parsed(parse("1 splash soda"), amount=1.0, unit="splash", name="soda")


def test_range_to():
    _assert_parsed(parse("1/2 to 3/4 oz simple syrup"),
                   amount=0.5, amount_max=0.75, unit="oz", name="simple syrup")


def test_range_dash():
    _assert_parsed(parse("1-2 oz vodka"), amount=1.0, amount_max=2.0, unit="oz", name="vodka")


def test_name_lowercased_whitespace_collapsed():
    _assert_parsed(parse("  2  oz   GIN  "), amount=2.0, unit="oz", name="gin")


def test_unknown_unit_abstains():
    """If the unit token isn't in the table, qty_unit must abstain."""
    r = parse("1 squeeze fresh lime juice")
    assert r.parse_status == "unparseable"


def test_qty_with_no_unit_abstains():
    r = parse("3 fresh basil leaves")  # 'leaves' is count_noun, not unit; that's task 14
    assert r.parser_rule != "qty_unit"


def test_empty_name_after_qty_unit_abstains():
    r = parse("2 oz")
    assert r.parse_status == "unparseable"
```

- [ ] **Step 2: Run; expect fail**

```bash
cd ingredients && uv run pytest tests/test_rule_qty_unit.py -v
```

- [ ] **Step 3: Implement**

In `ingredients/src/ingredients/parser.py`, add at the top of the file alongside other imports:

```python
from ingredients.units import canonicalize_unit
```

Then add (after `_try_topup`):

```python
def _try_qty_unit(cleaned: str, raw: str) -> ParseResult | None:
    qty = parse_quantity(cleaned)
    if qty is None:
        return None
    amount, amount_max, qty_end = qty
    rest = cleaned[qty_end:]
    if not rest.startswith(" "):
        return None
    rest = rest.lstrip()
    if not rest:
        return None
    # Greedy match the longest unit alias that prefixes the remaining text.
    # Multi-word aliases (e.g. 'fluid ounce', 'fl oz') must be tried before
    # single-word aliases.
    unit_canon = None
    name_start = -1
    for alias_len_words in (3, 2, 1):
        tokens = rest.split(" ", alias_len_words)
        if len(tokens) <= alias_len_words:
            continue
        candidate_alias = " ".join(tokens[:alias_len_words])
        canon = canonicalize_unit(candidate_alias)
        if canon is None:
            continue
        # Prefer the longest matching alias by trying alias_len_words=3 first.
        unit_canon = canon
        name_start = len(candidate_alias)
        break
    if unit_canon is None:
        return None
    name_part = rest[name_start:].lstrip().lower()
    name_part = re.sub(r"\s+", " ", name_part).strip()
    if not name_part:
        return None
    return ParseResult(
        raw_text=raw,
        parse_status="parsed",
        parser_rule="qty_unit",
        amount=amount,
        amount_max=amount_max,
        unit=unit_canon,
        name=name_part,
    )
```

Update `_RULES`:

```python
_RULES = [
    _try_garnish_prefix,
    _try_topup,
    _try_qty_unit,
]
```

- [ ] **Step 4: Run; expect pass**

```bash
uv run pytest tests/ -v
```

Expected: every test in the package passes (units, pre_clean, parse_quantity, all three rules so far).

- [ ] **Step 5: Commit**

```bash
cd .. && git add ingredients/src/ingredients/parser.py ingredients/tests/test_rule_qty_unit.py
git commit -m "add qty_unit rule covering 90% of ingredient strings"
```

---

### Task 14: Add the `count_noun` rule

**Files:**
- Modify: `ingredients/src/ingredients/parser.py`
- Create: `ingredients/tests/test_rule_count_noun.py`

- [ ] **Step 1: Write failing tests**

Create `ingredients/tests/test_rule_count_noun.py`. Note the abstain cases below: they enforce the "no count noun in the alias table → unparseable" discipline. Empty-name parses (`1 egg white`) also abstain because we never store empty names.

```python
from ingredients.parser import parse


def _assert_parsed(r, *, amount, unit, name):
    assert r.parse_status == "parsed", f"unexpected unparseable: {r}"
    assert r.parser_rule == "count_noun", f"wrong rule: {r.parser_rule}"
    assert r.amount == amount
    assert r.unit == unit
    assert r.name == name


def test_basic_count_noun_after_qualifier():
    _assert_parsed(parse("3 fresh basil leaves"),
                   amount=3.0, unit="leaf", name="basil")


def test_count_noun_no_qualifier():
    _assert_parsed(parse("4 sugar cubes"),
                   amount=4.0, unit="cube", name="sugar")


def test_dried_qualifier_with_no_real_count_noun_abstains():
    """'2 dried Star anise' has no count noun -> unparseable."""
    r = parse("2 dried Star anise")
    assert r.parse_status == "unparseable"


def test_pineapple_not_a_count_noun_abstains():
    r = parse("1 whole Pineapple")
    assert r.parse_status == "unparseable"


def test_egg_white_with_no_name_abstains():
    """'1 egg white' would parse to empty name; we abstain rather than store."""
    r = parse("1 egg white")
    assert r.parse_status == "unparseable"


def test_sprig_qualifier():
    _assert_parsed(parse("1 fresh rosemary sprig"),
                   amount=1.0, unit="sprig", name="rosemary")


def test_lime_wedge():
    _assert_parsed(parse("1 lime wedge"),
                   amount=1.0, unit="wedge", name="lime")


def test_count_noun_at_end_with_qualifier():
    _assert_parsed(parse("1 fresh Mint leaves"),
                   amount=1.0, unit="leaf", name="mint")


def test_count_noun_multi_word_name():
    _assert_parsed(parse("3 fresh sage leaves"),
                   amount=3.0, unit="leaf", name="sage")


def test_unknown_count_noun_abstains():
    r = parse("3 dollops cream")
    assert r.parse_status == "unparseable"
```

- [ ] **Step 2: Run; expect fail**

```bash
cd ingredients && uv run pytest tests/test_rule_count_noun.py -v
```

- [ ] **Step 3: Implement**

In `ingredients/src/ingredients/parser.py`, import:

```python
from ingredients.units import canonicalize_unit, canonicalize_count_noun
```

Add (after `_try_qty_unit`):

```python
_QUALIFIERS = ("fresh", "dried", "whole")


def _try_count_noun(cleaned: str, raw: str) -> ParseResult | None:
    """Match `<qty> [fresh|dried|whole]? <name_tokens>* <count_noun>` OR
    `<qty> [fresh|dried|whole]? <count_noun> <name_tokens>+`.

    The count noun must be in COUNT_NOUN_ALIASES. Strings with no count noun
    abstain. Strings with no name (e.g. '1 egg white') also abstain — empty
    names produce no useful structure.
    """
    qty = parse_quantity(cleaned)
    if qty is None:
        return None
    amount, amount_max, qty_end = qty
    rest = cleaned[qty_end:].lstrip().lower()
    if not rest:
        return None

    tokens = rest.split()
    # Strip a leading qualifier if present (drop it; modifier=None for v1).
    if tokens and tokens[0] in _QUALIFIERS:
        tokens = tokens[1:]
    if not tokens:
        return None

    # Try count noun at end-of-string first (most common: '3 fresh basil leaves').
    # Then try at the start (rare: '1 lime wedge' is end-style; an at-start
    # placement would be e.g. '1 leaf basil' which is uncommon — skip for v1).
    # Multi-word count nouns ('egg white') need a 2-token tail check.
    for tail_words in (2, 1):
        if len(tokens) < tail_words + 1:
            continue
        tail = " ".join(tokens[-tail_words:])
        canon = canonicalize_count_noun(tail)
        if canon is None:
            continue
        name_tokens = tokens[:-tail_words]
        name_part = " ".join(name_tokens).strip()
        if not name_part:
            return None
        return ParseResult(
            raw_text=raw,
            parse_status="parsed",
            parser_rule="count_noun",
            amount=amount,
            amount_max=amount_max,
            unit=canon,
            name=name_part,
        )
    return None
```

Update `_RULES`:

```python
_RULES = [
    _try_garnish_prefix,
    _try_topup,
    _try_qty_unit,
    _try_count_noun,
]
```

- [ ] **Step 4: Run; expect pass**

```bash
uv run pytest tests/ -v
```

Expected: every test in the package green.

- [ ] **Step 5: Commit**

```bash
cd .. && git add ingredients/src/ingredients/parser.py ingredients/tests/test_rule_count_noun.py
git commit -m "add count_noun rule for cocktail count-based ingredients"
```

---

### Task 15: Add an abstain-set test guarding precision

**Files:**
- Create: `ingredients/tests/test_rule_abstain.py`

This task adds a test file that asserts the parser correctly abstains on examples we expect to be hard. No implementation change should be needed — if any test fails, fix the rule that over-matched.

- [ ] **Step 1: Write the abstain test**

Create `ingredients/tests/test_rule_abstain.py`:

```python
"""Negative-case guard: strings the parser MUST NOT 'best-effort' parse.

Each entry here is something we observed in the corpus where any partial
parse would be wrong. Adding a new entry here is the way you record an
over-match bug: write the failing test, then tighten the rule that fired.
"""

import pytest

from ingredients.parser import parse


ABSTAIN_CASES = [
    # foodandwine concatenated bug — multiple ingredients glued together.
    "0.5 oz Santoni Amaro3 oz Lambrusco Del Emilia Rosé1 oz club soda",
    # Reverse format (name first, qty after) — too ambiguous for v1.
    "D'Usse VSOP: 30 ml",
    "Peychaud Bitters: 2 dashes",
    # Multiple parenthesized equivalent volumes — which to use?
    "1 (375ml) bottle (1 1/2 cups) rye whiskey or blended scotch",
    "3/4 ounce (1 1/2 tablespoons) St-Germain elderflower liqueur",
    # Footnote artifact — liquor.com convention.
    "Coconut ice sphere*",
    # Bare bottle/can phrasing — "1 12-oz. can ginger beer" has structure
    # we're not going to attempt in v1.
    "1 12-oz. can ginger beer",
    # No quantity, no recognized prefix.
    "Ice",
    "Float Whipping cream",
    "Hard apple cider, to top",
    "Salt, to rim (optional)",
    "Lemon wedge, for rimming",
    # Quantity but unrecognized unit and no count noun.
    "1 squeeze fresh lime juice",
    "Few tablespoons honey (optional)",  # 'few' isn't numeric
    "Large pinch salt",
    "Dash of Angostura bitters",  # leading word 'Dash' but no qty before it
    # Empty / whitespace.
    "",
    "   ",
]


@pytest.mark.parametrize("s", ABSTAIN_CASES)
def test_must_abstain(s):
    r = parse(s)
    assert r.parse_status == "unparseable", (
        f"expected unparseable for {s!r}, "
        f"got rule={r.parser_rule} amount={r.amount} unit={r.unit} name={r.name}"
    )
```

- [ ] **Step 2: Run; expect either green, or specific failures pointing at over-matching rules**

```bash
cd ingredients && uv run pytest tests/test_rule_abstain.py -v
```

- If green: parser is properly precision-tuned. Move on.
- If any test fails: identify which rule's regex matched the input, and tighten it. **Do not edit the test to make it pass.** Common fixes you may need:
  - **Concatenated-row sniff (most likely failure).** The foodandwine row `"0.5 oz Santoni Amaro3 oz Lambrusco..."` legitimately has a leading `0.5 oz` and a "name" that happens to contain another `\d+\s*<unit>` sequence — the qty_unit rule will faithfully parse the prefix and produce a garbage name. Tighten qty_unit: after building the candidate name, scan it for the pattern `\d+\s*(?:oz|ml|cl|tsp|tbsp|cup|dash|drop|splash|pinch|part|jigger|barspoon)\b` (case-insensitive). If the pattern fires, abstain. Note this would not catch a clean year suffix like `1-3yo` (no following unit token) or a brand year like `Reserve 10` (no following unit token) — only the concatenation case.
  - **Reverse format (`D'Usse VSOP: 30 ml`).** This currently doesn't match qty_unit (no leading number) or any other rule, so it should already abstain. If it does parse, your pre_clean is doing something unexpected — check that punctuation stripping isn't dropping the `:` and reordering anything.
  - **`1 12-oz. can ginger beer`.** qty_unit matches `1` as quantity, then sees `12-oz.` as the next token. `12-oz.` is not in the unit alias table, so the 1-word check fails. Multi-word checks try `12-oz. can`, `12-oz. can ginger` — also not aliases. So the rule abstains naturally. If a test fails here, your alias table accidentally includes a partial match.
  - **Unit alias word-boundary.** Make sure your alias table never matches a substring of a longer word. The current implementation splits on whitespace before lookup, so this should be safe — but verify with a test like `"5 ozzy strong gin"` which must abstain (`ozzy` isn't an alias).

Run again. Repeat until all abstain cases pass.

- [ ] **Step 3: Commit**

```bash
cd .. && git add ingredients/tests/test_rule_abstain.py ingredients/src/ingredients/parser.py
git commit -m "guard precision via abstain-set tests"
```

(If the parser file did not change, drop it from the `add`.)

---

## Phase 4 — Eval set + `--review` CLI

### Task 16: Create eval set fixture

**Files:**
- Create: `ingredients/src/ingredients/eval_set.py`
- Create: `ingredients/tests/test_eval_set.py`

- [ ] **Step 1: Write failing test**

Create `ingredients/tests/test_eval_set.py`:

```python
from ingredients.eval_set import EVAL_CASES, run_eval


def test_eval_cases_exist():
    assert len(EVAL_CASES) >= 20


def test_run_eval_returns_pass_fail_breakdown():
    result = run_eval()
    assert "passed" in result
    assert "failed" in result
    assert "cases" in result
    assert result["passed"] + result["failed"] == len(EVAL_CASES)


def test_all_eval_cases_pass():
    result = run_eval()
    assert result["failed"] == 0, result["cases"]
```

- [ ] **Step 2: Run; expect fail**

```bash
cd ingredients && uv run pytest tests/test_eval_set.py -v
```

- [ ] **Step 3: Implement**

Create `ingredients/src/ingredients/eval_set.py`:

```python
"""Checked-in golden cases used by the `--review` CLI. Bumping
PARSER_VERSION should be paired with re-running --review until it passes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ingredients.parser import parse


@dataclass
class EvalCase:
    raw: str
    site: str | None
    expect_status: str  # 'parsed' | 'unparseable'
    expect_rule: str | None = None
    expect_amount: float | None = None
    expect_amount_max: float | None = None
    expect_unit: str | None = None
    expect_name: str | None = None


# Should-parse-as-X cases.
_PARSE_CASES: list[EvalCase] = [
    EvalCase("2 oz gin", "punch",
             expect_status="parsed", expect_rule="qty_unit",
             expect_amount=2.0, expect_unit="oz", expect_name="gin"),
    EvalCase("1 1/2 oz Tanqueray gin", "tastingtable",
             expect_status="parsed", expect_rule="qty_unit",
             expect_amount=1.5, expect_unit="oz", expect_name="tanqueray gin"),
    EvalCase("0.25 cup honey", "marthastewart",
             expect_status="parsed", expect_rule="qty_unit",
             expect_amount=0.25, expect_unit="cup", expect_name="honey"),
    EvalCase("3/4 ounce rum, such as Coruba", "punch",
             expect_status="parsed", expect_rule="qty_unit",
             expect_amount=0.75, expect_unit="oz",
             expect_name="rum, such as coruba"),
    EvalCase("¾ ounce campari", "punch",
             expect_status="parsed", expect_rule="qty_unit",
             expect_amount=0.75, expect_unit="oz", expect_name="campari"),
    EvalCase("45 ml Light gold rum 1-3yo", "diffordsguide",
             expect_status="parsed", expect_rule="qty_unit",
             expect_amount=45.0, expect_unit="ml",
             expect_name="light gold rum 1-3yo"),
    EvalCase("1 dash Aromatic bitters", "diffordsguide",
             expect_status="parsed", expect_rule="qty_unit",
             expect_amount=1.0, expect_unit="dash",
             expect_name="aromatic bitters"),
    EvalCase("3 drops Xocolatl mole bitters", "diffordsguide",
             expect_status="parsed", expect_rule="qty_unit",
             expect_amount=3.0, expect_unit="drop",
             expect_name="xocolatl mole bitters"),
    EvalCase("1/2 to 3/4 oz simple syrup", None,
             expect_status="parsed", expect_rule="qty_unit",
             expect_amount=0.5, expect_amount_max=0.75,
             expect_unit="oz", expect_name="simple syrup"),
    EvalCase("Garnish: lemon wheel", "liquor",
             expect_status="parsed", expect_rule="garnish_prefix",
             expect_name="lemon wheel"),
    EvalCase("Garnish: orange twist", "liquor",
             expect_status="parsed", expect_rule="garnish_prefix",
             expect_name="orange twist"),
    EvalCase("Top up with Brut sparkling wine", "diffordsguide",
             expect_status="parsed", expect_rule="topup",
             expect_name="brut sparkling wine"),
    EvalCase("Top up with Soda (club soda) water", "diffordsguide",
             expect_status="parsed", expect_rule="topup",
             expect_name="soda (club soda) water"),
    EvalCase("3 fresh basil leaves", "liquor",
             expect_status="parsed", expect_rule="count_noun",
             expect_amount=3.0, expect_unit="leaf", expect_name="basil"),
    EvalCase("4 sugar cubes", "liquor",
             expect_status="parsed", expect_rule="count_noun",
             expect_amount=4.0, expect_unit="cube", expect_name="sugar"),
    EvalCase("1 fresh rosemary sprig", "thekitchn",
             expect_status="parsed", expect_rule="count_noun",
             expect_amount=1.0, expect_unit="sprig", expect_name="rosemary"),
]

# Should-abstain cases (kept in sync with test_rule_abstain.py).
_ABSTAIN_CASES: list[EvalCase] = [
    EvalCase("0.5 oz Santoni Amaro3 oz Lambrusco Del Emilia Rosé1 oz club soda",
             "foodandwine", expect_status="unparseable"),
    EvalCase("D'Usse VSOP: 30 ml", "foodandwine", expect_status="unparseable"),
    EvalCase("1 (375ml) bottle (1 1/2 cups) rye whiskey or blended scotch",
             "simplyrecipes", expect_status="unparseable"),
    EvalCase("Coconut ice sphere*", "liquor", expect_status="unparseable"),
    EvalCase("Ice", "thekitchn", expect_status="unparseable"),
    EvalCase("1 squeeze fresh lime juice", "liquor", expect_status="unparseable"),
    EvalCase("Few tablespoons honey (optional)", "marthastewart", expect_status="unparseable"),
]

EVAL_CASES: list[EvalCase] = _PARSE_CASES + _ABSTAIN_CASES


def run_eval() -> dict[str, Any]:
    """Run every eval case and return a pass/fail summary plus per-case detail."""
    cases = []
    passed = 0
    failed = 0
    for case in EVAL_CASES:
        result = parse(case.raw, site=case.site)
        ok = (
            result.parse_status == case.expect_status
            and (case.expect_rule is None or result.parser_rule == case.expect_rule)
            and (case.expect_amount is None or result.amount == case.expect_amount)
            and (case.expect_amount_max is None or result.amount_max == case.expect_amount_max)
            and (case.expect_unit is None or result.unit == case.expect_unit)
            and (case.expect_name is None or result.name == case.expect_name)
        )
        cases.append({"raw": case.raw, "ok": ok, "result": result})
        if ok:
            passed += 1
        else:
            failed += 1
    return {"passed": passed, "failed": failed, "cases": cases}
```

- [ ] **Step 4: Run; expect pass**

```bash
uv run pytest tests/test_eval_set.py -v
```

If any case fails the `test_all_eval_cases_pass` assertion, the printed `result["cases"]` lists which raw strings produced unexpected parses. Fix the rule (do not weaken the eval case) and re-run.

- [ ] **Step 5: Commit**

```bash
cd .. && git add ingredients/src/ingredients/eval_set.py ingredients/tests/test_eval_set.py
git commit -m "add ingredient parser eval set"
```

---

### Task 17: Build the `--review` CLI command

**Files:**
- Create: `ingredients/src/ingredients/cli.py`
- Create: `ingredients/tests/test_cli_review.py`

- [ ] **Step 1: Write failing test**

Create `ingredients/tests/test_cli_review.py`:

```python
import io
import sys

from ingredients.cli import run_review


def test_run_review_prints_summary_and_returns_zero_on_pass(capsys):
    rc = run_review()
    captured = capsys.readouterr()
    assert "passed" in captured.out.lower()
    assert rc == 0
```

- [ ] **Step 2: Run; expect fail**

```bash
cd ingredients && uv run pytest tests/test_cli_review.py -v
```

- [ ] **Step 3: Implement**

Create `ingredients/src/ingredients/cli.py`:

```python
"""parse_ingredients CLI.

Modes:
  --review                run the eval set, print pass/fail, exit 0 on green.
  (no flags)              run the polling worker. Implemented in a later task.

Shared options (added in a later task) match the scraper conventions:
  --site / --limit / --dry-run / --reset --yes / --except-version / --older-than
"""

from __future__ import annotations

import argparse
import sys

from ingredients.eval_set import run_eval


def run_review() -> int:
    result = run_eval()
    print(f"--- Parser eval ---")
    print(f"  passed: {result['passed']}")
    print(f"  failed: {result['failed']}")
    if result["failed"]:
        print()
        print("Failures:")
        for case in result["cases"]:
            if case["ok"]:
                continue
            r = case["result"]
            print(
                f"  {case['raw']!r}\n"
                f"    -> status={r.parse_status} rule={r.parser_rule} "
                f"amount={r.amount} amount_max={r.amount_max} "
                f"unit={r.unit} name={r.name!r}"
            )
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="parse_ingredients",
        description="Spiritolo ingredient parser — Zone-2 reconciling worker.",
    )
    parser.add_argument(
        "--review", action="store_true",
        help="Run the eval set against the parser; do not touch the database.",
    )
    args = parser.parse_args()
    if args.review:
        return run_review()
    parser.error("worker mode not yet implemented; pass --review for now")
    return 2  # unreachable


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run; expect pass**

```bash
uv run pytest tests/test_cli_review.py -v
```

- [ ] **Step 5: Smoke-test the CLI from the shell**

```bash
uv run python -m ingredients.cli --review
```

Expected output ends with `passed: 23` (or whatever the case count is) and `failed: 0`. Exit code 0.

- [ ] **Step 6: Commit**

```bash
cd .. && git add ingredients/src/ingredients/cli.py ingredients/tests/test_cli_review.py
git commit -m "add parse_ingredients --review mode"
```

---

## Phase 5 — Polling worker: DB layer

### Task 18: Add Supabase data-access layer for the worker

**Files:**
- Create: `ingredients/src/ingredients/db.py`
- Create: `ingredients/tests/test_db.py`

The worker DB layer is a thin wrapper around psycopg that knows three things: the work queue (recipes lacking a current-version parse), how to write structured rows for one recipe, and how to clear rows for `--reset`.

- [ ] **Step 1: Write failing tests**

Create `ingredients/tests/test_db.py`:

```python
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

requires_supabase = pytest.mark.skipif(
    not os.environ.get("SUPABASE_DB_URL"),
    reason="SUPABASE_DB_URL not set; skipping integration test",
)

PARSER_VERSION_TEST = "v-test"


@requires_supabase
@pytest.fixture
def isolated_db():
    """Truncate recipes + recipe_ingredients, yield a Database, clean up after."""
    from ingredients.db import IngredientsDatabase
    db = IngredientsDatabase()
    db.conn.execute("truncate table recipe_ingredients cascade")
    db.conn.execute("truncate table recipes cascade")
    db.conn.commit()
    yield db
    db.conn.execute("truncate table recipe_ingredients cascade")
    db.conn.execute("truncate table recipes cascade")
    db.conn.commit()
    db.close()


def _seed_recipe(db, *, source_url, site, jsonld):
    import json
    db.conn.execute(
        """
        insert into recipes (source_url, site, name, jsonld, fetched_at)
        values (%s, %s, %s, %s::jsonb, '2026-04-25T00:00:00Z')
        returning id
        """,
        (source_url, site, "test", json.dumps(jsonld)),
    )
    db.conn.commit()
    return db.conn.execute(
        "select id from recipes where source_url = %s", (source_url,)
    ).fetchone()[0]


@requires_supabase
def test_work_queue_returns_recipes_lacking_current_version_parse(isolated_db):
    db = isolated_db
    rid = _seed_recipe(db, source_url="https://example.com/r1", site="punch",
                       jsonld={"recipeIngredient": ["2 oz gin", "1 oz lime"]})

    queue = db.fetch_work_queue(parser_version=PARSER_VERSION_TEST)
    assert len(queue) == 1
    assert queue[0]["id"] == rid
    assert queue[0]["site"] == "punch"
    assert queue[0]["recipe_ingredient"] == ["2 oz gin", "1 oz lime"]


@requires_supabase
def test_work_queue_skips_recipes_with_current_version_parse(isolated_db):
    db = isolated_db
    rid = _seed_recipe(db, source_url="https://example.com/r2", site="punch",
                       jsonld={"recipeIngredient": ["2 oz gin"]})
    db.write_recipe_parses(
        recipe_id=rid,
        rows=[{
            "position": 0, "raw_text": "2 oz gin",
            "amount": 2.0, "amount_max": None, "unit": "oz", "name": "gin",
            "modifier": None, "parse_status": "parsed", "parser_rule": "qty_unit",
        }],
        parser_version=PARSER_VERSION_TEST,
    )
    queue = db.fetch_work_queue(parser_version=PARSER_VERSION_TEST)
    assert queue == []


@requires_supabase
def test_work_queue_returns_recipe_with_old_version_parse(isolated_db):
    db = isolated_db
    rid = _seed_recipe(db, source_url="https://example.com/r3", site="punch",
                       jsonld={"recipeIngredient": ["2 oz gin"]})
    db.write_recipe_parses(
        recipe_id=rid,
        rows=[{
            "position": 0, "raw_text": "2 oz gin",
            "amount": 2.0, "amount_max": None, "unit": "oz", "name": "gin",
            "modifier": None, "parse_status": "parsed", "parser_rule": "qty_unit",
        }],
        parser_version="v0",
    )
    queue = db.fetch_work_queue(parser_version=PARSER_VERSION_TEST)
    assert len(queue) == 1
    assert queue[0]["id"] == rid


@requires_supabase
def test_write_replaces_existing_rows_for_recipe(isolated_db):
    db = isolated_db
    rid = _seed_recipe(db, source_url="https://example.com/r4", site="punch",
                       jsonld={"recipeIngredient": ["2 oz gin"]})
    db.write_recipe_parses(
        recipe_id=rid,
        rows=[{
            "position": 0, "raw_text": "old", "amount": 1.0, "amount_max": None,
            "unit": "oz", "name": "old", "modifier": None,
            "parse_status": "parsed", "parser_rule": "qty_unit",
        }],
        parser_version="v0",
    )
    db.write_recipe_parses(
        recipe_id=rid,
        rows=[{
            "position": 0, "raw_text": "new", "amount": 2.0, "amount_max": None,
            "unit": "oz", "name": "new", "modifier": None,
            "parse_status": "parsed", "parser_rule": "qty_unit",
        }],
        parser_version=PARSER_VERSION_TEST,
    )
    rows = db.conn.execute(
        "select raw_text, parser_version from recipe_ingredients where recipe_id = %s",
        (rid,),
    ).fetchall()
    assert rows == [("new", PARSER_VERSION_TEST)]


@requires_supabase
def test_count_eval_rows_filters(isolated_db):
    db = isolated_db
    rid = _seed_recipe(db, source_url="https://example.com/r5", site="punch",
                       jsonld={"recipeIngredient": ["2 oz gin"]})
    db.write_recipe_parses(
        recipe_id=rid,
        rows=[{
            "position": 0, "raw_text": "x", "amount": 1.0, "amount_max": None,
            "unit": "oz", "name": "x", "modifier": None,
            "parse_status": "parsed", "parser_rule": "qty_unit",
        }],
        parser_version="v0",
    )
    assert db.count_eval_rows(site=None, except_version=None, older_than=None) == 1
    assert db.count_eval_rows(site="punch", except_version=None, older_than=None) == 1
    assert db.count_eval_rows(site="liquor", except_version=None, older_than=None) == 0
    assert db.count_eval_rows(site=None, except_version="v0", older_than=None) == 0
    assert db.count_eval_rows(site=None, except_version="v1", older_than=None) == 1


@requires_supabase
def test_clear_eval_rows_returns_deleted_count(isolated_db):
    db = isolated_db
    rid = _seed_recipe(db, source_url="https://example.com/r6", site="punch",
                       jsonld={"recipeIngredient": ["2 oz gin"]})
    db.write_recipe_parses(
        recipe_id=rid,
        rows=[{
            "position": 0, "raw_text": "x", "amount": 1.0, "amount_max": None,
            "unit": "oz", "name": "x", "modifier": None,
            "parse_status": "parsed", "parser_rule": "qty_unit",
        }],
        parser_version="v0",
    )
    n = db.clear_eval_rows(site=None, except_version=None, older_than=None)
    assert n == 1
```

- [ ] **Step 2: Run; expect import failure**

```bash
cd ingredients && uv run pytest tests/test_db.py -v
```

If `SUPABASE_DB_URL` is not set, the tests skip — that's fine for the import-error gate. Add it to your environment via `.env` at the repo root before continuing.

- [ ] **Step 3: Implement**

Create `ingredients/src/ingredients/db.py`:

```python
"""Postgres data-access layer for the ingredient parser worker.

All queries are written against Supabase Postgres (the local one in dev).
Connection credentials come from SUPABASE_DB_URL via spiritolo_common.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable

import psycopg
from dotenv import load_dotenv


def _env_url() -> str:
    url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        load_dotenv(Path(__file__).resolve().parent.parent.parent.parent / ".env")
        url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        raise RuntimeError(
            "SUPABASE_DB_URL is not set. Run `supabase status` and add it to .env."
        )
    return url


class IngredientsDatabase:
    """Connection + queries for recipes -> recipe_ingredients."""

    def __init__(self, db_url: str | None = None):
        self.conn = psycopg.connect(db_url or _env_url())

    def close(self) -> None:
        self.conn.close()

    def fetch_work_queue(
        self, *, parser_version: str, site: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Recipes that need parsing under the current PARSER_VERSION.

        A recipe needs parsing when it has zero recipe_ingredients rows at
        `parser_version`. (Older-version rows are ignored — they don't satisfy
        the requirement, and they will be replaced when the recipe is parsed.)
        """
        params: list[Any] = [parser_version]
        site_clause = ""
        if site is not None:
            site_clause = "and r.site = %s"
            params.append(site)

        sql = f"""
            select r.id, r.site, r.source_url, r.jsonld->'recipeIngredient' as recipe_ingredient
            from recipes r
            where jsonb_typeof(r.jsonld->'recipeIngredient') = 'array'
              and not exists (
                select 1 from recipe_ingredients ri
                where ri.recipe_id = r.id and ri.parser_version = %s
              )
              {site_clause}
            order by r.id
        """
        if limit is not None:
            sql += " limit %s"
            params.append(limit)

        rows = self.conn.execute(sql, params).fetchall()
        return [
            {
                "id": row[0], "site": row[1], "source_url": row[2],
                "recipe_ingredient": row[3] or [],
            }
            for row in rows
        ]

    def write_recipe_parses(
        self, *, recipe_id: int, rows: Iterable[dict[str, Any]],
        parser_version: str,
    ) -> None:
        """Replace all recipe_ingredients rows for `recipe_id` atomically.

        Each row dict must contain: position, raw_text, amount, amount_max,
        unit, name, modifier, parse_status, parser_rule.
        """
        with self.conn.transaction():
            self.conn.execute(
                "delete from recipe_ingredients where recipe_id = %s",
                (recipe_id,),
            )
            for r in rows:
                self.conn.execute(
                    """
                    insert into recipe_ingredients (
                        recipe_id, position, raw_text,
                        amount, amount_max, unit, name, modifier,
                        parse_status, parser_rule, parser_version
                    ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        recipe_id, r["position"], r["raw_text"],
                        r["amount"], r["amount_max"], r["unit"], r["name"],
                        r["modifier"], r["parse_status"], r["parser_rule"],
                        parser_version,
                    ),
                )

    def count_eval_rows(
        self, *, site: str | None, except_version: str | None,
        older_than: str | None,
    ) -> int:
        sql, params = self._eval_rows_filter(
            select="select count(*)", site=site,
            except_version=except_version, older_than=older_than,
        )
        return self.conn.execute(sql, params).fetchone()[0]

    def clear_eval_rows(
        self, *, site: str | None, except_version: str | None,
        older_than: str | None,
    ) -> int:
        sql, params = self._eval_rows_filter(
            select="delete", site=site,
            except_version=except_version, older_than=older_than,
        )
        cur = self.conn.execute(sql, params)
        self.conn.commit()
        return cur.rowcount

    @staticmethod
    def _eval_rows_filter(
        *, select: str, site: str | None,
        except_version: str | None, older_than: str | None,
    ) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if site is not None:
            clauses.append("ri.recipe_id in (select id from recipes where site = %s)")
            params.append(site)
        if except_version is not None:
            clauses.append("ri.parser_version <> %s")
            params.append(except_version)
        if older_than is not None:
            clauses.append("ri.parsed_at < %s::timestamptz")
            params.append(older_than)
        where = (" where " + " and ".join(clauses)) if clauses else ""
        return f"{select} from recipe_ingredients ri{where}", params
```

- [ ] **Step 4: Run; expect pass**

```bash
uv run pytest tests/test_db.py -v
```

Expected: green if `SUPABASE_DB_URL` is set; otherwise tests skip.

- [ ] **Step 5: Commit**

```bash
cd .. && git add ingredients/src/ingredients/db.py ingredients/tests/test_db.py
git commit -m "add Supabase data-access layer for ingredient worker"
```

---

## Phase 6 — Polling worker: orchestration

### Task 19: Add the recipe-parsing function and wire it through the CLI

**Files:**
- Create: `ingredients/src/ingredients/worker.py`
- Modify: `ingredients/src/ingredients/cli.py`
- Create: `ingredients/tests/test_worker.py`

- [ ] **Step 1: Write failing tests**

Create `ingredients/tests/test_worker.py`:

```python
from ingredients.worker import build_rows_for_recipe


def test_build_rows_skips_non_string_entries():
    rows = build_rows_for_recipe(["2 oz gin", None, 5, "1 oz lime"])
    assert [r["raw_text"] for r in rows] == ["2 oz gin", "1 oz lime"]
    assert [r["position"] for r in rows] == [0, 3]


def test_build_rows_records_unparseable():
    rows = build_rows_for_recipe(["¯\\_(ツ)_/¯"])
    assert len(rows) == 1
    r = rows[0]
    assert r["parse_status"] == "unparseable"
    assert r["amount"] is None
    assert r["unit"] is None
    assert r["name"] is None
    assert r["raw_text"] == "¯\\_(ツ)_/¯"


def test_build_rows_parsed_payload_shape():
    rows = build_rows_for_recipe(["2 oz gin"])
    assert len(rows) == 1
    r = rows[0]
    assert r["position"] == 0
    assert r["raw_text"] == "2 oz gin"
    assert r["amount"] == 2.0
    assert r["amount_max"] is None
    assert r["unit"] == "oz"
    assert r["name"] == "gin"
    assert r["modifier"] is None
    assert r["parse_status"] == "parsed"
    assert r["parser_rule"] == "qty_unit"
```

- [ ] **Step 2: Run; expect fail**

```bash
cd ingredients && uv run pytest tests/test_worker.py -v
```

- [ ] **Step 3: Implement**

Create `ingredients/src/ingredients/worker.py`:

```python
"""Per-recipe parsing logic. The CLI wires this into a Supabase loop."""

from __future__ import annotations

from typing import Any, Iterable

from ingredients.parser import parse


def build_rows_for_recipe(
    raw_ingredients: Iterable[Any], site: str | None = None,
) -> list[dict[str, Any]]:
    """Run the parser over every string in `raw_ingredients`. Non-string
    entries are skipped (their `position` is also skipped, so re-runs land at
    the same indexes).

    Returns a list of insertable dicts ready for IngredientsDatabase.write_recipe_parses.
    """
    rows: list[dict[str, Any]] = []
    for idx, raw in enumerate(raw_ingredients):
        if not isinstance(raw, str):
            continue
        result = parse(raw, site=site)
        rows.append({
            "position": idx,
            "raw_text": result.raw_text,
            "amount": result.amount,
            "amount_max": result.amount_max,
            "unit": result.unit,
            "name": result.name,
            "modifier": result.modifier,
            "parse_status": result.parse_status,
            "parser_rule": result.parser_rule,
        })
    return rows
```

- [ ] **Step 4: Run; expect pass**

```bash
uv run pytest tests/test_worker.py -v
```

- [ ] **Step 5: Commit**

```bash
cd .. && git add ingredients/src/ingredients/worker.py ingredients/tests/test_worker.py
git commit -m "add per-recipe row-building worker function"
```

---

### Task 20: Wire the worker into the CLI (main worker mode + --reset)

**Files:**
- Modify: `ingredients/src/ingredients/cli.py`
- Create: `ingredients/tests/test_cli_main.py`

- [ ] **Step 1: Write failing test (CLI parses arguments and dispatches)**

Create `ingredients/tests/test_cli_main.py`:

```python
import os

import pytest

from ingredients.cli import build_arg_parser


def test_arg_parser_review():
    p = build_arg_parser()
    args = p.parse_args(["--review"])
    assert args.review is True
    assert args.site is None
    assert args.limit is None
    assert args.dry_run is False
    assert args.reset is False


def test_arg_parser_full_worker_options():
    p = build_arg_parser()
    args = p.parse_args([
        "--site", "punch", "--limit", "100", "--dry-run",
    ])
    assert args.review is False
    assert args.site == "punch"
    assert args.limit == 100
    assert args.dry_run is True


def test_arg_parser_reset_flags():
    p = build_arg_parser()
    args = p.parse_args(["--reset", "--except-version", "v0", "--yes"])
    assert args.reset is True
    assert args.except_version == "v0"
    assert args.yes is True
```

- [ ] **Step 2: Run; expect fail**

```bash
cd ingredients && uv run pytest tests/test_cli_main.py -v
```

- [ ] **Step 3: Rewrite `cli.py`**

Replace the contents of `ingredients/src/ingredients/cli.py` with:

```python
"""parse_ingredients CLI.

Modes:
  --review      Run the eval set, print pass/fail, exit 0 on green.
  default       Polling worker. Reads `recipes` from Supabase, parses each
                row's recipeIngredient array, writes rows to recipe_ingredients.
                Skips recipes that already have rows at the current PARSER_VERSION.

Reset flow (matches scraper conventions):
  --reset --yes [--site S] [--except-version V] [--older-than ISO_TS]
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter

from spiritolo_common.cli_common import (
    add_reset_args, confirm_reset, describe_reset_scope,
)
from spiritolo_common.progress import make_progress
from spiritolo_common.summary import print_summary

from ingredients.db import IngredientsDatabase
from ingredients.eval_set import run_eval
from ingredients.parser import PARSER_VERSION
from ingredients.worker import build_rows_for_recipe

log = logging.getLogger("parse_ingredients")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="parse_ingredients",
        description="Spiritolo ingredient parser — Zone-2 reconciling worker.",
    )
    parser.add_argument(
        "--review", action="store_true",
        help="Run the eval set against the parser; do not touch the database.",
    )
    parser.add_argument(
        "--site", default=None,
        help="Restrict processing to one source site (e.g. 'punch').",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Process at most N recipes.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Parse and report counts; do not write to the database.",
    )
    add_reset_args(parser, stage="recipe_ingredients")
    return parser


def run_review() -> int:
    result = run_eval()
    print(f"--- Parser eval ---")
    print(f"  passed: {result['passed']}")
    print(f"  failed: {result['failed']}")
    if result["failed"]:
        print()
        print("Failures:")
        for case in result["cases"]:
            if case["ok"]:
                continue
            r = case["result"]
            print(
                f"  {case['raw']!r}\n"
                f"    -> status={r.parse_status} rule={r.parser_rule} "
                f"amount={r.amount} amount_max={r.amount_max} "
                f"unit={r.unit} name={r.name!r}"
            )
        return 1
    return 0


def run_worker(args: argparse.Namespace) -> int:
    db = IngredientsDatabase()
    try:
        if args.reset:
            to_delete = db.count_eval_rows(
                site=args.site,
                except_version=args.except_version,
                older_than=args.older_than,
            )
            scope = describe_reset_scope(
                site=args.site,
                except_version=args.except_version,
                older_than=args.older_than,
            )
            if not confirm_reset(
                row_count=to_delete, scope_desc=scope, assume_yes=args.yes,
            ):
                log.error("reset aborted")
                return 1
            if to_delete:
                n = db.clear_eval_rows(
                    site=args.site,
                    except_version=args.except_version,
                    older_than=args.older_than,
                )
                log.info("cleared %d recipe_ingredients rows", n)

        queue = db.fetch_work_queue(
            parser_version=PARSER_VERSION,
            site=args.site,
            limit=args.limit,
        )
        total = len(queue)
        if total == 0:
            log.info("nothing to parse")
            return 0
        log.info("parsing %d recipes (parser_version=%s)", total, PARSER_VERSION)

        progress = make_progress(total=total)
        changes: dict[str, Counter] = {}

        for idx, recipe in enumerate(queue, start=1):
            site = recipe["site"]
            rows = build_rows_for_recipe(recipe["recipe_ingredient"], site=site)
            if not args.dry_run:
                db.write_recipe_parses(
                    recipe_id=recipe["id"], rows=rows,
                    parser_version=PARSER_VERSION,
                )
            counter = changes.setdefault(site, Counter())
            for r in rows:
                counter[r["parse_status"]] += 1
            progress(idx)

        mode = "dry-run" if args.dry_run else "applied"
        print_summary("Parse ingredients", changes, mode=mode)
        return 0
    finally:
        db.close()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = build_arg_parser()
    args = parser.parse_args()
    if args.review:
        return run_review()
    return run_worker(args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Update existing CLI test for `run_review` location**

Verify `ingredients/tests/test_cli_review.py` still imports `run_review` from `ingredients.cli`. It should — `run_review` is still exported from that module. Run:

```bash
uv run pytest tests/test_cli_review.py tests/test_cli_main.py -v
```

Expected: green.

- [ ] **Step 5: Run the full test suite**

```bash
uv run pytest -v
```

Expected: every test in the package passes.

- [ ] **Step 6: Smoke-test the CLI from the shell, dry-run**

```bash
uv run python -m ingredients.cli --dry-run --limit 5
```

Expected: connects to Supabase (assumes recipes exist), processes up to 5, prints a per-site summary like:

```
--- Parse ingredients ---
  diffordsguide:
       45  parsed
        2  unparseable
Total: 47 (dry-run)
```

If recipes exist but you see "nothing to parse," verify the migration applied (`Task 6`).

- [ ] **Step 7: Commit**

```bash
cd .. && git add ingredients/src/ingredients/cli.py ingredients/tests/test_cli_main.py
git commit -m "wire parse_ingredients worker mode and --reset flow"
```

---

## Phase 7 — Smoke test + docs

### Task 21: Run the parser against the loaded Supabase corpus and report unparseable rate

**Files:** none modified (this is verification only)

- [ ] **Step 1: Apply the recipe_ingredients migration if you haven't yet**

```bash
psql "postgresql://postgres:postgres@localhost:54322/postgres" -c "\dt recipe_ingredients" 2>&1 | grep recipe_ingredients
```

If absent, apply Task 6's migration first.

- [ ] **Step 2: Run the worker end-to-end**

```bash
cd ingredients && uv run python -m ingredients.cli
```

Expected: completes without errors. Final summary lists per-site `parsed` and `unparseable` counts.

- [ ] **Step 3: Compute the unparseable rate**

```bash
psql "postgresql://postgres:postgres@localhost:54322/postgres" -c "
select
  count(*) filter (where parse_status='parsed') as parsed,
  count(*) filter (where parse_status='unparseable') as unparseable,
  round(100.0 * count(*) filter (where parse_status='unparseable') / count(*), 2) as unparseable_pct
from recipe_ingredients;
"
```

Target: `unparseable_pct < 3.0`.

- If under 3%: parser is shipping at acceptable precision. Move to Task 22.
- If over 3%: dump the most common failure shapes:

```bash
psql "postgresql://postgres:postgres@localhost:54322/postgres" -c "
select substring(raw_text, 1, 80), count(*) as n
from recipe_ingredients
where parse_status='unparseable'
group by 1 order by n desc limit 50;
"
```

Read the patterns. If a clear new rule emerges, file it as a follow-up (do not extend the v1 plan). Note: per the spec, exceeding 3% is the trigger to consider an `ingredient-parser-nlp` second pass — but that's a separate decision, not part of this plan.

- [ ] **Step 4: Spot-check a per-site sample**

```bash
psql "postgresql://postgres:postgres@localhost:54322/postgres" -c "
select r.site, ri.raw_text, ri.amount, ri.unit, ri.name
from recipe_ingredients ri join recipes r on r.id = ri.recipe_id
where ri.parse_status='parsed'
order by random() limit 25;
"
```

Eyeball: do the parses look right? If you spot a clearly-wrong parse (e.g. `amount` clearly off, `name` clearly truncated), that is a precision regression — file it against Task 15's abstain set with the failing case, then bump `PARSER_VERSION` and re-parse.

- [ ] **Step 5: No commit needed if nothing changed**

This task is observational. If you adjusted rules, the task that altered the rule covered the commit.

---

### Task 22: Document the new package and CLI in `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Append new sections to CLAUDE.md**

Add this content **before** the `## Web UI` section (so all parser-shaped pipeline docs cluster together):

````markdown
## Ingredient Parser

`ingredients/` is a Zone-2 worker that reads `recipes` from Supabase, parses each `jsonld.recipeIngredient` string with strict abstain discipline, and writes rows to `recipe_ingredients`. It depends on the shared `common/` package, not on `scraper/`.

**Versioning:** `PARSER_VERSION` lives in [parser.py](ingredients/src/ingredients/parser.py). Bump it whenever any parser rule changes (including unit-table edits). Rows carry the version they were parsed under.

**Typical usage (from repo root):**

```bash
# Main run — parse every recipe lacking a row at the current PARSER_VERSION.
cd ingredients && uv run python -m ingredients.cli

# Scoped to one site, with a row cap.
cd ingredients && uv run python -m ingredients.cli --site punch --limit 200

# Dry-run preview, no DB writes.
cd ingredients && uv run python -m ingredients.cli --dry-run

# Run the eval set; no DB writes. Use during rule iteration.
cd ingredients && uv run python -m ingredients.cli --review

# After bumping PARSER_VERSION, re-parse everything left at the old version.
cd ingredients && uv run python -m ingredients.cli --reset --except-version v1 --yes
```

The eval set is `ingredients/src/ingredients/eval_set.py`. Add a new should-parse-as-X case whenever you teach the parser a new pattern; add a should-abstain case whenever you find an over-match.

**Common, scraper, ingredients packages.** `common/` holds shared utilities (`supabase_client`, `progress`, `summary`, `cli_common`); both `scraper/` (Zone 1) and `ingredients/` (Zone 2) depend on it via the root-level uv workspace.
````

- [ ] **Step 2: Verify the file renders sensibly**

```bash
grep -n "## Ingredient Parser\|## Web UI" CLAUDE.md
```

Expected: `## Ingredient Parser` line precedes `## Web UI` line.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "document ingredient parser CLI in CLAUDE.md"
```

---

## Done

After Task 22, the worktree branch contains:

- A uv workspace at the repo root with `common/`, `scraper/`, `ingredients/` members
- Shared utilities living in `common/`; scraper migrated to import from there
- A `recipe_ingredients` Supabase migration
- A pure parser module with strict-abstain rules and an eval set
- A polling-worker CLI (`parse_ingredients`) matching scraper conventions
- An end-to-end smoke run with measured unparseable rate

Open `gh pr create` against `main`, terse description per `CLAUDE.md` ("Pull Requests" section). Once merged, the Phase 2 work in the future-direction roadmap (`[D]` taxonomy mapping, `[E]` dedup, `[F]` re-pointed search) becomes unblocked.
