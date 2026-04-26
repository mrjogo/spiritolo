# Spirits Taxonomy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the lean three-table spirits taxonomy in Supabase with a hand-curated starter seed of definitional spirit and produce categories, plus the aliases needed to resolve common ingredient strings.

**Architecture:** Three Postgres tables (`taxonomy_nodes`, `taxonomy_edges`, `taxonomy_aliases`) form a multi-parent DAG. RLS-locked, no public views yet — only the future [D] mapper (server-side, postgres role) reads the data. Schema follows the lean YAGNI shape: five columns on nodes, two on aliases.

**Spec:** [`docs/spirits-taxonomy.md`](../../spirits-taxonomy.md)

---

## File Structure

**New files**
- `supabase/migrations/20260426120000_create_taxonomy.sql` — schema
- `supabase/migrations/20260426120100_seed_taxonomy.sql` — initial nodes / edges / aliases

**Modified files**
- `CLAUDE.md` — short Spirits Taxonomy section under Data model

---

## Task 1: Schema migration

**Files:**
- Create: `supabase/migrations/20260426120000_create_taxonomy.sql`

- [ ] **Step 1: Write the migration**

```sql
create table taxonomy_nodes (
  id            bigserial primary key,
  slug          text unique not null,
  display_name  text not null,
  role          text check (role in ('brand', 'expression')),
  created_at    timestamptz not null default now()
);

create table taxonomy_edges (
  parent_id  bigint not null references taxonomy_nodes(id) on delete cascade,
  child_id   bigint not null references taxonomy_nodes(id) on delete cascade,
  primary key (parent_id, child_id),
  check (parent_id <> child_id)
);

create index taxonomy_edges_child_idx on taxonomy_edges (child_id);

create table taxonomy_aliases (
  alias    text   not null,
  node_id  bigint not null references taxonomy_nodes(id) on delete cascade,
  primary key (alias, node_id)
);

create index taxonomy_aliases_alias_idx on taxonomy_aliases (alias);

alter table taxonomy_nodes   enable row level security;
alter table taxonomy_edges   enable row level security;
alter table taxonomy_aliases enable row level security;
```

Notes:
- `bigserial` matches the convention in `20260422120000_create_recipes.sql`.
- Index on `taxonomy_edges.child_id` for parent-of-X traversal (PK already covers parent_id-leading queries).
- Index on `taxonomy_aliases.alias` for the mapper's primary lookup.
- RLS enabled with no policies = locked to postgres role only. Add public views later if a non-server consumer needs read.

- [ ] **Step 2: Commit**

```bash
git add supabase/migrations/20260426120000_create_taxonomy.sql
git commit -m "Taxonomy: schema migration for nodes, edges, aliases"
```

---

## Task 2: Seed migration

**Files:**
- Create: `supabase/migrations/20260426120100_seed_taxonomy.sql`

Hand-curated starter set. Covers the major spirit families and a few produce groupings — enough for the [D] mapper to demonstrate alias resolution end-to-end. Long-tail brands and expressions are left for the mapper to auto-create later.

- [ ] **Step 1: Write the seed**

```sql
-- Top-level spirit families and base liqueurs.
insert into taxonomy_nodes (slug, display_name) values
  ('whiskey',    'Whiskey'),
  ('gin',        'Gin'),
  ('vodka',      'Vodka'),
  ('rum',        'Rum'),
  ('tequila',    'Tequila'),
  ('mezcal',     'Mezcal'),
  ('brandy',     'Brandy'),
  ('vermouth',   'Vermouth'),
  ('amaro',      'Amaro'),
  ('bitters',    'Bitters');

-- Whiskey subtypes.
insert into taxonomy_nodes (slug, display_name) values
  ('bourbon',         'Bourbon'),
  ('rye_whiskey',     'Rye Whiskey'),
  ('scotch_whisky',   'Scotch Whisky'),
  ('irish_whiskey',   'Irish Whiskey'),
  ('japanese_whisky', 'Japanese Whisky');

-- Rum / Tequila / Vermouth / Brandy subtypes.
insert into taxonomy_nodes (slug, display_name) values
  ('white_rum',         'White Rum'),
  ('dark_rum',          'Dark Rum'),
  ('aged_rum',          'Aged Rum'),
  ('blanco_tequila',    'Blanco Tequila'),
  ('reposado_tequila',  'Reposado Tequila'),
  ('anejo_tequila',     'Añejo Tequila'),
  ('sweet_vermouth',    'Sweet Vermouth'),
  ('dry_vermouth',      'Dry Vermouth'),
  ('blanc_vermouth',    'Blanc Vermouth'),
  ('cognac',            'Cognac'),
  ('armagnac',          'Armagnac'),
  ('calvados',          'Calvados');

-- Produce.
insert into taxonomy_nodes (slug, display_name) values
  ('citrus',     'Citrus'),
  ('lemon',      'Lemon'),
  ('lime',       'Lime'),
  ('orange',     'Orange'),
  ('grapefruit', 'Grapefruit');

-- Edges: parent_slug -> child_slug pairs, resolved via slug lookup.
insert into taxonomy_edges (parent_id, child_id)
select p.id, c.id
from taxonomy_nodes p
join taxonomy_nodes c on (p.slug, c.slug) in (
  ('whiskey', 'bourbon'),
  ('whiskey', 'rye_whiskey'),
  ('whiskey', 'scotch_whisky'),
  ('whiskey', 'irish_whiskey'),
  ('whiskey', 'japanese_whisky'),
  ('rum',     'white_rum'),
  ('rum',     'dark_rum'),
  ('rum',     'aged_rum'),
  ('tequila', 'blanco_tequila'),
  ('tequila', 'reposado_tequila'),
  ('tequila', 'anejo_tequila'),
  ('vermouth','sweet_vermouth'),
  ('vermouth','dry_vermouth'),
  ('vermouth','blanc_vermouth'),
  ('brandy',  'cognac'),
  ('brandy',  'armagnac'),
  ('brandy',  'calvados'),
  ('citrus',  'lemon'),
  ('citrus',  'lime'),
  ('citrus',  'orange'),
  ('citrus',  'grapefruit')
);

-- Aliases: free-text strings recipes use, mapped to canonical nodes.
insert into taxonomy_aliases (alias, node_id)
select a.alias, n.id
from taxonomy_nodes n
join (values
  ('whisky',          'whiskey'),
  ('rye',             'rye_whiskey'),
  ('scotch',          'scotch_whisky'),
  ('single malt',     'scotch_whisky'),
  ('bourbon whiskey', 'bourbon'),
  ('rye whiskey',     'rye_whiskey'),
  ('blanco',          'blanco_tequila'),
  ('reposado',        'reposado_tequila'),
  ('anejo',           'anejo_tequila'),
  ('añejo',           'anejo_tequila'),
  ('sweet vermouth',  'sweet_vermouth'),
  ('rosso vermouth',  'sweet_vermouth'),
  ('italian vermouth','sweet_vermouth'),
  ('dry vermouth',    'dry_vermouth'),
  ('french vermouth', 'dry_vermouth')
) as a(alias, slug) on n.slug = a.slug;
```

- [ ] **Step 2: Commit**

```bash
git add supabase/migrations/20260426120100_seed_taxonomy.sql
git commit -m "Taxonomy: seed initial spirit families, subtypes, citrus, aliases"
```

---

## Task 3: Apply and verify

> **Human step required:** Local Supabase runs on the Mac host, not in the devcontainer. Run `supabase status` on the host to confirm it's up before this task.

- [ ] **Step 1: Apply migrations**

From inside the devcontainer:

```bash
supabase db reset \
  --db-url "postgresql://postgres:postgres@192.168.65.254:54322/postgres" \
  --yes
```

A trailing `tls error` from the CLI is expected and harmless; the migrations succeed regardless.

- [ ] **Step 2: Verify counts and basic shape**

```bash
psql "postgresql://postgres:postgres@192.168.65.254:54322/postgres" -c "
  select 'nodes' as t, count(*) from taxonomy_nodes
  union all select 'edges', count(*) from taxonomy_edges
  union all select 'aliases', count(*) from taxonomy_aliases;
"
```

Expected: `nodes` = 32, `edges` = 21, `aliases` = 15.

- [ ] **Step 3: Verify alias resolution**

```bash
psql "postgresql://postgres:postgres@192.168.65.254:54322/postgres" -c "
  select n.slug, n.display_name
  from taxonomy_aliases a join taxonomy_nodes n on n.id = a.node_id
  where a.alias = 'rye';
"
```

Expected: one row, `slug = rye_whiskey`.

- [ ] **Step 4: Verify ancestor traversal**

```bash
psql "postgresql://postgres:postgres@192.168.65.254:54322/postgres" -c "
  with recursive ancestors(id, slug) as (
    select id, slug from taxonomy_nodes where slug = 'rye_whiskey'
    union all
    select n.id, n.slug
    from ancestors a
    join taxonomy_edges e on e.child_id = a.id
    join taxonomy_nodes n on n.id = e.parent_id
  )
  select slug from ancestors order by slug;
"
```

Expected: `rye_whiskey`, `whiskey`.

---

## Task 4: Document in CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add a Spirits Taxonomy section**

Insert after the "JSON-LD Extractor" section, before "Validate CLI":

```markdown
## Spirits Taxonomy

Three Supabase tables (`taxonomy_nodes`, `taxonomy_edges`, `taxonomy_aliases`) form a multi-parent DAG of canonical ingredients. Recipes resolve free-text ingredients to node IDs via aliases; the DAG enables "all whiskeys" / "all citrus"-style queries.

Design and content rules: [`docs/spirits-taxonomy.md`](docs/spirits-taxonomy.md). The lean stance — taxonomy for definitional categories and hard constraints, vector layer for soft similarity — is load-bearing; read it before adding nodes.

To add nodes or aliases, edit `supabase/migrations/20260426120100_seed_taxonomy.sql` and re-run `supabase db reset`. New definitional categories at any time. Brands and expressions: hand-curate the well-known, leave the long tail for the future [D] mapper.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "Taxonomy: document tables and curation workflow in CLAUDE.md"
```

---

## Done when

- All migrations applied cleanly to local Supabase.
- The three verification queries return the expected results.
- `CLAUDE.md` points future contributors at the design doc and the curation workflow.
