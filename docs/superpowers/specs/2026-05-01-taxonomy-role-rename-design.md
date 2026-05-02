# Taxonomy `role` rename — design

The word **role** is overloaded in the data model. Three distinct things share
the name, two of them on the same row:

| Where | Values | What it means |
|---|---|---|
| `taxonomy_nodes.role` | `'brand'`, `'expression'`, `NULL` | What kind of taxonomy entry the node is. Closed vocabulary, structural. |
| `taxonomy_nodes.role_default` | `'base_spirit'`, `'modifier'`, `'citrus'`, `'sweetener'`, `'bitters'`, `'dilution'`, `'ice'`, `'garnish'`, `'wash'`, `'other'` | When a recipe references this substance, what's its default functional role in the drink. |
| `recipe_ingredients.role` | (same vocabulary as `role_default`) | This specific ingredient's classified role in this specific recipe. |

`role_default` and `recipe_ingredients.role` share a vocabulary and are
genuinely two faces of the same concept (default vs. resolved). `taxonomy_nodes.role`
is a different concept entirely — it answers "is this node a brand, a product,
or a regular substance?" The collision is real and lives on the same row as
its semantic neighbour.

A bonus collision: D's LLM-mapper contract uses the JSON key `"role"` to
mean the new node's *kind* (`{"action": "propose_brand", ..., "role": "brand"|"expression"}`).
Same word, same ambiguity, propagated into every cached response and every
prompt-engineering test.

## Recommendation

Rename two columns and one JSON key:

- `taxonomy_nodes.role` → `node_kind`
- `taxonomy_nodes.role_default` → `default_role`
- LLM mapper JSON key `"role"` → `"node_kind"` (in `propose_brand` actions)

Leave `recipe_ingredients.role` and `recipe_ingredients.role_source` alone.

### Why this direction

- **Right concept gets renamed.** `taxonomy_nodes.role` is structural metadata
  ("what kind of entry") — `node_kind` says exactly that. Calling it a "role"
  always required the qualifier "in the data model" (which the doc does, line
  47 of `docs/spirits-taxonomy.md`).
- **Ingredient role is genuinely a role.** Base spirit, modifier, bitters, garnish
  *are* the roles ingredients play in a drink. That's the natural English usage;
  renaming it would force a worse word.
- **Smallest blast radius.** ~25 occurrences of the structural concept (1
  migration, ~5 seed files, 4 Python files, fixtures, tests, 1 doc) vs. ~200+
  for `recipe_ingredients.role` + the dedup pipeline.
- **Pairing stays clean.** `taxonomy_nodes.role_default` becomes the obvious
  default-for-the-ingredient-role on a node, with no naming collision against
  `node_kind` on the same row.

### Name candidates considered

| Name | Verdict |
|---|---|
| `node_kind` | **Recommended.** Short, distinctive, no domain overload. |
| `entry_kind` | Fine alternative; slightly more abstract. |
| `node_class` | Avoid — "class" is overloaded with category-as-class. |
| `node_type` | Avoid — `type` is colloquially used for taxonomy levels (`type='gin'`). |
| `model_role` | Keeps "role"; doesn't fully resolve the collision. |
| `taxon_kind` | Jargon-y; the codebase already standardises on "node". |

## On `default_role` vs `default_recipe_role`

`default_role` over `default_recipe_role`. Once `taxonomy_nodes.role` is
gone, the only "role" left on that table can only mean ingredient-role —
there's nothing left to disambiguate against, so the qualifier is redundant.
`default_role` ↔ `recipe_ingredients.role` reads naturally as "default for
the role column on the related table." Also matches the precedent set by
the sibling column `is_defining_garnish`, which carries ingredient semantics
on `taxonomy_nodes` without a `recipe_` qualifier.

## Migration approach

A forward `ALTER TABLE ... RENAME COLUMN` for both columns. New migration
file, no rewriting of old migrations. The earlier
`20260426120000_create_taxonomy.sql` and `20260429160000_dedup_taxonomy_node_columns.sql`
continue to define the columns as `role` / `role_default`; the new migration
renames both as the last step, and seeds (which run after migrations) use
the final names.

```sql
-- supabase/migrations/20260502120000_rename_taxonomy_node_role_columns.sql
alter table taxonomy_nodes rename column role         to node_kind;
alter table taxonomy_nodes rename column role_default to default_role;
-- The CHECK constraint on node_kind follows automatically.
-- (role_default has no CHECK; default_role inherits its absence.)
```

### In-place vs forward-rename

Forward-rename is the safe default — keep it.

In-place would mean editing
[supabase/migrations/20260426120000_create_taxonomy.sql:5](supabase/migrations/20260426120000_create_taxonomy.sql#L5)
and [supabase/migrations/20260429160000_dedup_taxonomy_node_columns.sql:12](supabase/migrations/20260429160000_dedup_taxonomy_node_columns.sql#L12)
directly. Aesthetic upside: schema history reads top-to-bottom in one
consistent vocabulary; one fewer migration file. The hard constraint:
**Supabase tracks applied migrations by filename, not content hash.** Any DB
that has already applied either of those files will *skip* it on the next
`migration up` after we edit, leaving the old column names in place silently.
Code expects `node_kind` / `default_role`; queries break.

Conditions for in-place to be safe:

- Every dev DB the team uses can be `db reset`.
- No remote/staging/prod DB has applied either of those migrations, OR all
  remote DBs can be reset too.

If those hold, in-place is a one-time cleanup; otherwise forward-rename is
the only option that converges every DB on next migrate.

## Exhaustive change list

Numbered for tracking; nothing here is conditional unless flagged.

### 1. Migration

- **NEW**: `supabase/migrations/20260502120000_rename_taxonomy_node_role_columns.sql`
  with two `ALTER TABLE ... RENAME COLUMN` statements (`role` → `node_kind`,
  `role_default` → `default_role`).

- *Or*, if in-place is approved: edit
  [supabase/migrations/20260426120000_create_taxonomy.sql:5](supabase/migrations/20260426120000_create_taxonomy.sql#L5)
  to read `node_kind text check (node_kind in ('brand', 'expression'))`,
  and edit
  [supabase/migrations/20260429160000_dedup_taxonomy_node_columns.sql:12](supabase/migrations/20260429160000_dedup_taxonomy_node_columns.sql#L12)
  to read `add column default_role text`. Skip the new migration file.

### 2. Seed files (column lists in INSERTs and UPDATEs)

Both `role` → `node_kind` and `role_default` → `default_role` apply.

- [supabase/seeds/taxonomy_nodes_00_families.sql:23, 35](supabase/seeds/taxonomy_nodes_00_families.sql)
  — both INSERTs use `role_default`. Rename to `default_role`.
- [supabase/seeds/taxonomy_nodes_bitters.sql:9, 11, 22-28, 33-40](supabase/seeds/taxonomy_nodes_bitters.sql)
  — `update ... set role_default = 'bitters'`, `(slug, display_name, is_cluster_node, role_default)`,
  `(slug, display_name, role)`, `(slug, display_name, role, role_default)`. All flip.
- Every other `taxonomy_nodes_*.sql` (gin, whiskey, rum, tequila, brandy,
  vermouth, amari, fortified_wines, liqueurs, syrups, mixers, herbs, fruit,
  dairy) — sweep for any `role`/`role_default` column reference; most
  almost certainly use `role_default` and need the `default_role` flip.
- `supabase/seeds/processed/00_taxonomy_grown.sql` — generated by
  `scripts/refresh-processed-seeds.sh dump` from the live DB. It currently
  doesn't exist in the worktree (empty `processed/` dir on this branch).
  After applying the rename, re-run `dump` against a freshly seeded local
  DB so the file lands with the new column names if/when it's regenerated.

### 3. Python — `taxonomy_nodes` column reads/writes

Two columns to track: `role` → `node_kind`, `role_default` → `default_role`.

`role` → `node_kind`:

- [ingredients/src/ingredients/mapping/llm_resolver.py:69, 76-79](ingredients/src/ingredients/mapping/llm_resolver.py)
  — `_create_brand_node(... role: str ...)` parameter and the INSERT.
  Rename param to `node_kind` and update SQL.
- [ingredients/src/ingredients/dedup/promote_substances.py:3-7, 54-66, 72-78, 91-100](ingredients/src/ingredients/dedup/promote_substances.py)
  — module docstring, the `select n.role` query, the
  `where n.role in ('brand', 'expression')` filter, return-dict key
  `"current_role"` → `"current_node_kind"`, and the `update ... set role = null`
  in `promote_node`.
- Any caller of `promote_node` / `candidate_promotions` printing
  `current_role` — sweep `ingredients/src/ingredients/cli.py` and
  `dedup/__init__.py` for the dict key.

`role_default` → `default_role`:

- [ingredients/src/ingredients/dedup/role_classifier.py:48-88](ingredients/src/ingredients/dedup/role_classifier.py)
  — `classify_role` reads `ing["role_default"]`. Rename the dict key access.
  (Function name `classify_role` itself stays — it classifies the
  ingredient role, which keeps that name.)
- [ingredients/src/ingredients/dedup/cluster.py:121](ingredients/src/ingredients/dedup/cluster.py#L121)
  — SQL `select ... n.role_default ...` in the join. Rename column.
  Also update wherever the result is read into a dict (around line 140-160)
  to match the new column name.
- [ingredients/src/ingredients/dedup/eval_set.py:145-151](ingredients/src/ingredients/dedup/eval_set.py#L145-L151)
  — `select role_default, is_defining_garnish from taxonomy_nodes ...`
  and `ing["role_default"]` build. Rename SQL column and dict key.
- [ingredients/src/ingredients/dedup/promote_substances.py:67-78, 96-98](ingredients/src/ingredients/dedup/promote_substances.py)
  — `role_default_by_name` dict (local var name — keep or rename to
  `default_role_by_name` for consistency), `proposed_role_default` dict
  key on the return shape, `set ... role_default = %s` in `promote_node`'s
  UPDATE.
- [ingredients/src/ingredients/dedup/audit.py:145-146](ingredients/src/ingredients/dedup/audit.py)
  — any reference to `role_default` (audit code).

### 4. LLM contract (JSON key `"role"` in propose_brand)

This is a **wire-format change**. The system prompt, the parser, the tests,
and any cached responses all need to flip together.

- [ingredients/src/ingredients/mapping/prompt.py:30-31](ingredients/src/ingredients/mapping/prompt.py#L30-L31)
  — system prompt: `"role": "brand" | "expression"` → `"node_kind": "brand" | "expression"`.
- [ingredients/src/ingredients/mapping/llm_resolver.py](ingredients/src/ingredients/mapping/llm_resolver.py)
  — wherever `action_obj["role"]` is read, switch to `action_obj["node_kind"]`.
- [ingredients/tests/test_mapping_prompt.py:34, 39](ingredients/tests/test_mapping_prompt.py#L34)
  — fake response strings `'"role": "brand"'` → `'"node_kind": "brand"'`.
- [ingredients/tests/test_mapping_llm_resolver.py:71, 76, 79-80, 109, 231](ingredients/tests/test_mapping_llm_resolver.py)
  — same. Note line 76 also has a SQL `select id, role from taxonomy_nodes`
  that needs the column-name rename. Line 79-80 unpack `(new_id, new_role)`
  → rename local var to `new_node_kind`.
- [ingredients/tests/test_mapping_end_to_end.py:61](ingredients/tests/test_mapping_end_to_end.py#L61)
  — same.
- **Cached LLM responses in DB.** `taxonomy_provenance` only stores `raw_string`
  and `prompt_hash`, not the response JSON, so no DB rewrite is needed.

### 5. Test fixtures

- [ingredients/src/ingredients/mapping/eval_fixture.py:38-42](ingredients/src/ingredients/mapping/eval_fixture.py)
  — `for slug, name, role in nodes:` and the SQL `insert into taxonomy_nodes (slug, display_name, role)`.
  Rename loop var and SQL column to `node_kind`.
- [ingredients/src/ingredients/dedup/eval_fixture.py:14-15](ingredients/src/ingredients/dedup/eval_fixture.py#L14-L15)
  — comment header `# Each tuple: (slug, display_name, role, is_cluster_node, role_default, ...)`.
  Relabel positions 2 and 4 as `node_kind` and `default_role`.
- [ingredients/src/ingredients/dedup/eval_fixture.py:93-110](ingredients/src/ingredients/dedup/eval_fixture.py)
  — the `seed_dedup_fixture` insert column list (`role`, `role_default`),
  the loop unpacking variable names, and the `on conflict do update set`
  clause (`role_default = excluded.role_default`). Tuple *positions* don't
  change; only the column names in SQL and the local variable names flip.
- [ingredients/tests/test_dedup_eval_fixture.py:31-45](ingredients/tests/test_dedup_eval_fixture.py)
  — fixture validation reads `role_defaults.get(...)` etc. Rename the local
  dict name and the SQL column it queries to `default_role`.

### 6. Tests touching the columns directly

- `ingredients/tests/test_dedup_migrations.py` — sweep for assertions on
  column names and CHECK constraints. Anything testing
  `taxonomy_nodes.role` / `role_default` flips to `node_kind` / `default_role`.
  (The CHECK on `node_kind` survives the rename automatically; tests should
  refer to it by the new name.)
- `ingredients/tests/test_dedup_role_classifier.py` — `make_ing(role_default=...)`
  helper. Rename the kwarg to `default_role` so the fixture matches the new
  dict key shape consumed by `classify_role`.
- `ingredients/tests/test_dedup_cluster.py` — sweep; any direct reads on
  `role_default` from a fetched row flip.

### 7. Documentation

- [docs/spirits-taxonomy.md](docs/spirits-taxonomy.md) — authoritative doc.
  Lines 21, 47-57, 64, 90 (and any "role in the data model" prose) need
  rewriting in terms of `node_kind`. The phrasing improves: instead of "role
  marks a node's role in the data model" → "node_kind marks what kind of
  taxonomy entry this is."
- [CLAUDE.md](CLAUDE.md) — Spirits Taxonomy section: the bullet "Brand and
  product names always get their own nodes (`role='brand'` / `'expression'`)"
  → `node_kind='brand'`. The asymmetric-antichain bullet doesn't reference
  `role` and is unaffected.
- `docs/superpowers/specs/2026-04-29-recipe-dedup-design.md` and
  `docs/superpowers/plans/2026-04-29-*.md` — update if they reference
  `role='brand'` or similar; otherwise leave as historical record.

### 8. Things explicitly NOT changing

- `recipe_ingredients.role` (the column) — kept.
- `recipe_ingredients.role_source` — kept.
- `dedup/role_classifier.py` (filename and function `classify_role`) — kept.
- `dedup/cluster.py` constants `INCLUDED_ROLES`, the `role`/`role_source`
  bulk-update SQL, cluster-key/variant-key sorting on `ing["role"]` — all
  kept; all about `recipe_ingredients`.
- `dedup/audit.py` queries filtering `ri.role in (...)` — kept.
- Web (`web/src/**`) — confirmed clean of `role` references already.

## Test plan

After the changes:

1. **DB sanity** — `supabase db reset --db-url …` (per CLAUDE.md devcontainer
   recipe) plus `psql -f supabase/seeds/recipes.sql`. Verify `\d taxonomy_nodes`
   shows `node_kind` and the CHECK constraint is intact.
2. **Pipeline tests**:
   - `cd ingredients && uv run pytest`
   - `cd scraper && uv run pytest` (sanity — should be unaffected)
   - `cd web && npm test` (sanity — should be unaffected)
3. **Eval sets**:
   - `cd ingredients && uv run python -m ingredients.cli map --review`
   - `cd ingredients && uv run python -m ingredients.cli cluster --review`
4. **Restore flow**: `scripts/refresh-processed-seeds.sh restore` should
   complete without column-name errors. If it fails on `00_taxonomy_grown.sql`
   pre-existing content, that's a stale seed — re-`dump` after the rename.

No `MAPPER_VERSION` / `DEDUP_VERSION` bump is required. The classifier outputs
are unchanged; only the column name housing the structural metadata moves.

## Open questions

1. **Edit migrations in place vs. forward-rename migration?** Forward-rename
   is the safe default. In-place only if no remote/staging DB has applied
   the originals (and every dev DB can be reset).

## PR shape

One PR, single commit if simple enough; otherwise:

- commit 1: migration + SQL seeds (both columns at once)
- commit 2: Python column reads/writes — `node_kind` side (resolver,
  promote_substances) + `default_role` side (role_classifier, cluster,
  eval_set, audit, fixtures)
- commit 3: LLM contract JSON key flip (prompt + parser + tests in lockstep)
- commit 4: docs

Per CLAUDE.md: PR against `main`, one-paragraph description, up to 8 bullets,
no test plan section.
