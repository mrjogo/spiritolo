-- RecipeGF export: store each drink's RecipeGF verb-frame recipe in
-- RELATIONAL form (mirroring how Spiritolo stores parsed ingredients as rows,
-- not as an opaque JSON blob), plus a propose→review queue for drinks the
-- deterministic converter can't yet emit.
--
-- A "drink" is a recipe_clusters row (the canonical drink identity). The pin-2
-- bundle Barbot imports is *generated deterministically on demand* from these
-- rows (+ the in-repo spiritolo/ verb-defs + meta) — the tables here are the
-- source of truth, the bundle JSON is a projection.
--
-- Shape mirrors the parser's recipes -> recipe_ingredients relationship:
--   recipe_clusters -> recipegf_recipes (header, 1 per cluster per version)
--                       -> recipegf_ingredients (rows)
--                       -> recipegf_steps       (rows)
-- The export work queue is "clusters with no recipegf_recipes row at the
-- current CONVERTER_VERSION" (a NOT EXISTS, exactly like the parser queue).

-- Recipe header: one row per (cluster, converter_version). An `exported` row
-- has children in recipegf_ingredients/_steps; an `uncertain` row is a parking
-- marker (no children) that keeps the cluster off the queue and pairs with a
-- recipegf_proposals row.
create table recipegf_recipes (
  id                bigserial primary key,
  cluster_id        bigint not null references recipe_clusters(id) on delete cascade,
  status            text not null check (status in ('exported', 'uncertain')),
  slug              text,                 -- null on uncertain
  recipe_id         text,                 -- full com.spiritolo/<slug>:v1; null on uncertain
  title             text,
  technique         text,                 -- stir/shake/build/blend (audit)
  equipment         text[] not null default '{}',
  source_url        text,
  converter_version text not null,
  exported_at       timestamptz not null default now(),
  unique (cluster_id, converter_version)
);

create index recipegf_recipes_cluster_idx on recipegf_recipes (cluster_id);
create index recipegf_recipes_status_idx  on recipegf_recipes (status);

-- The RecipeGF-projected ingredients: name is the taxonomy slug (or a
-- kebab-slug of the parsed name), quantity is (amount, unit) already validated
-- against RecipeGF's unit registry.
create table recipegf_ingredients (
  id                 bigserial primary key,
  recipegf_recipe_id bigint not null references recipegf_recipes(id) on delete cascade,
  position           int not null,
  name               text not null,
  amount             numeric not null,
  unit               text not null,
  unique (recipegf_recipe_id, position)
);

-- The verb-frame steps (the DAG). `verb` + `result` are the fixed fields; the
-- verb-specific role map (input/to/using/...) is genuinely schemaless per verb,
-- so it lives in `roles` jsonb (consistent with Spiritolo's other jsonb use:
-- recipes.jsonld, recipe_clusters.ingredient_set, taxonomy_proposals.candidates).
-- `modifiers` is optional freeform nuance (never validated).
create table recipegf_steps (
  id                 bigserial primary key,
  recipegf_recipe_id bigint not null references recipegf_recipes(id) on delete cascade,
  step_index         int not null,
  verb               text not null,
  result             text not null,
  roles              jsonb not null default '{}'::jsonb,
  modifiers          jsonb,
  unique (recipegf_recipe_id, step_index)
);

-- Review queue for drinks the converter parked as Uncertain (no technique,
-- unresolved ingredient, muddle, untranslatable unit, ...). Mirrors
-- taxonomy_proposals: a text+CHECK status, idempotent enqueue via a unique
-- (cluster, version) key. Resolving one is a taxonomy/data/rules fix followed
-- by re-running the export stage (delete its stage_runs rows, or bump
-- CONVERTER_VERSION).
create table recipegf_proposals (
  id                bigserial primary key,
  cluster_id        bigint references recipe_clusters(id) on delete cascade,
  canonical_name    text not null,
  proposed_slug     text,
  reason            text not null,   -- stable machine code (see converter.py)
  detail            text,            -- human-readable specifics
  source_url        text,
  converter_version text not null,
  status            text not null default 'pending'
                    check (status in ('pending', 'resolved', 'rejected')),
  decided_by        text,
  decided_at        timestamptz,
  created_at        timestamptz not null default now(),
  unique (cluster_id, converter_version)
);

create index recipegf_proposals_status_idx
  on recipegf_proposals (status, created_at);

-- Admin/pipeline-only: nothing public reads these (bundles are for Barbot
-- import via the service role, not the website). RLS on, no policy.
alter table recipegf_recipes     enable row level security;
alter table recipegf_ingredients enable row level security;
alter table recipegf_steps       enable row level security;
alter table recipegf_proposals   enable row level security;
