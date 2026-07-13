-- Relational content model: the recipe stored in RecipeGF shape, normalized.
--
-- The recipe is canonical and stored across three tables — `recipes` (header +
-- raw source JSON-LD), `recipe_ingredients` (RecipeGF ingredient rows), and
-- `recipe_steps` (RecipeGF verb-frame steps). Ingredient -> taxonomy resolution
-- is a SHARED, name-keyed mapping (`ingredient_resolutions`): fix a name once
-- and every recipe that uses it follows, so a taxonomy correction never rewrites
-- a recipe. Cluster/variant identity is derived (`recipe_clusters` + the
-- `cluster_id`/`variant_key` columns). The RecipeGF bundle a consumer imports is
-- assembled on demand from these rows + the current resolution + the in-repo
-- verb-defs; only a published export is frozen (`recipe_exports`).
--
-- The WHAT/HOW split is at the table level: these tables hold public recipe
-- facts; per-stage status/version/cost lives in `stage_runs` (admin-only). So
-- there is no per-recipe status column and no hidden sidecar here.
--
-- This replaces the earlier `recipes`/`recipe_ingredients` shape (parser output
-- carried a taxonomy_node_id + status columns) and the per-cluster `recipegf_*`
-- relational trio (the bundle is now generated per recipe on demand).

-- ---------------------------------------------------------------------------
-- 1. Drop the legacy content surface and everything that depended on it.
-- ---------------------------------------------------------------------------
-- Read-surface RPCs first (SQL functions carry a dependency on the tables they
-- project, so drop them before the tables).
drop function if exists public.recipegf_bundle(text, text);
drop function if exists public.recipegf_catalog(text);

-- The per-cluster RecipeGF relational trio + its proposal/verb-def sidecars.
drop table if exists public.recipegf_ingredients cascade;
drop table if exists public.recipegf_steps       cascade;
drop table if exists public.recipegf_proposals   cascade;
drop table if exists public.recipegf_verb_defs   cascade;
drop table if exists public.recipegf_recipes     cascade;

-- The legacy content tables + their views/policies/indexes. Dropping
-- recipe_ingredients also drops the taxonomy_public view (its recipe_count
-- subquery reads that table); it is recreated below against the new schema.
drop view  if exists public.recipe_variants;
drop view  if exists public.recipes_public;
drop table if exists public.recipe_ingredients cascade;
drop table if exists public.recipe_clusters    cascade;
drop table if exists public.recipes            cascade;
drop view  if exists public.taxonomy_public;

-- ---------------------------------------------------------------------------
-- 2. recipes — the header + the raw extracted source.
-- ---------------------------------------------------------------------------
-- `source` is the raw Schema.org Recipe JSON-LD (kept verbatim for re-derivation
-- and for the website's `jsonld` contract). The RecipeGF-shaped fields live in
-- the child rows; the identity fields (canonical_name, cluster_id, variant_key,
-- recipe_slug) are filled by the map/cluster/export stages.
create table recipes (
  id             bigserial primary key,
  source_url     text not null unique,
  site           text not null,
  source         jsonb not null default '{}'::jsonb,   -- raw Recipe JSON-LD
  title          text,
  author         text,
  image_url      text,
  equipment      text[] not null default '{}',          -- RecipeGF equipment list (convert output)
  canonical_name text,                                  -- dedup name normalization
  cluster_id     text,                                  -- -> recipe_clusters.cluster_key (deferred FK)
  variant_key    text,
  recipe_slug    text,                                  -- kebab slug minted at export
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create index recipes_site_idx           on recipes (site);
create index recipes_source_gin         on recipes using gin (source);
create index recipes_cluster_idx        on recipes (cluster_id) where cluster_id is not null;
create index recipes_cluster_variant_idx on recipes (cluster_id, variant_key) where cluster_id is not null;
create index recipes_canonical_name_idx on recipes (canonical_name) where canonical_name is not null;

drop trigger if exists set_updated_at on recipes;
create trigger set_updated_at
  before update on recipes
  for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------------
-- 3. recipe_ingredients — the RecipeGF ingredient rows (parse output).
-- ---------------------------------------------------------------------------
-- One row per source ingredient string, in RecipeGF shape: name + quantity
-- (amount, amount_max for ranges, unit) + freeform string[] modifiers. `name`
-- is the join key into the SHARED ingredient_resolutions (no per-row taxonomy
-- id — resolution is corrected once, centrally). `raw_text` preserves the
-- source string for audit.
create table recipe_ingredients (
  id          bigserial primary key,
  recipe_id   bigint not null references recipes(id) on delete cascade,
  position    int not null,
  name        text,
  amount      numeric,
  amount_max  numeric,
  unit        text,
  modifiers   text[] not null default '{}',
  raw_text    text not null,
  unique (recipe_id, position)
);

create index recipe_ingredients_recipe_idx on recipe_ingredients (recipe_id);
create index recipe_ingredients_name_idx   on recipe_ingredients (lower(btrim(name)))
  where name is not null;

-- ---------------------------------------------------------------------------
-- 4. recipe_steps — the RecipeGF verb-frame steps (convert output).
-- ---------------------------------------------------------------------------
-- Each step is a verb + a schemaless per-verb role map (input/to/using/…, held
-- in `roles`) + a `result` name + freeform string[] modifiers. The DAG is
-- implicit in the result/role name references, exactly as RecipeGF encodes it.
create table recipe_steps (
  id          bigserial primary key,
  recipe_id   bigint not null references recipes(id) on delete cascade,
  step_index  int not null,
  verb        text not null,
  roles       jsonb not null default '{}'::jsonb,
  modifiers   text[] not null default '{}',
  result      text not null,
  unique (recipe_id, step_index)
);

create index recipe_steps_recipe_idx on recipe_steps (recipe_id);

-- ---------------------------------------------------------------------------
-- 5. ingredient_resolutions — the SHARED name -> taxonomy resolution.
-- ---------------------------------------------------------------------------
-- Keyed by normalized ingredient name (lower(btrim(name))), NOT per recipe row.
-- One correction here re-points every recipe that uses that name. taxonomy_slug
-- null records a deliberate abstain (name seen, no confident node) so the map
-- stage's work queue can tell "never tried" from "tried, abstained".
create table ingredient_resolutions (
  id              bigserial primary key,
  normalized_name text not null unique,
  taxonomy_slug   text,                       -- null = abstain / unresolved
  method          text check (method in ('alias', 'lexical', 'llm', 'manual', 'abstain')),
  confidence      real,
  model_id        text,
  version         text,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create index ingredient_resolutions_slug_idx on ingredient_resolutions (taxonomy_slug)
  where taxonomy_slug is not null;

drop trigger if exists set_updated_at on ingredient_resolutions;
create trigger set_updated_at
  before update on ingredient_resolutions
  for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------------
-- 6. recipe_clusters — derived drink identity (role/cluster stage).
-- ---------------------------------------------------------------------------
-- cluster_key = hash(canonical_name, role-tagged ingredient slug set rolled up
-- to the curated antichain). `ingredient_set` snapshots the rolled-up set the
-- key hashed. Counts are recomputed by the cluster stage.
create table recipe_clusters (
  cluster_key              text primary key,
  canonical_name           text not null,
  ingredient_set           jsonb not null default '[]'::jsonb,
  representative_recipe_id  bigint,
  recipe_count             int not null default 0,
  source_count             int not null default 0,
  version                  text,
  created_at               timestamptz not null default now()
);

create index recipe_clusters_canonical_idx on recipe_clusters (canonical_name);

-- The recipes <-> recipe_clusters cycle: both sides deferrable so a bulk
-- restore/upload can push them in one transaction (SET CONSTRAINTS ALL
-- DEFERRED). INITIALLY IMMEDIATE keeps normal writes strict.
alter table recipes
  add constraint recipes_cluster_id_fkey
  foreign key (cluster_id) references recipe_clusters(cluster_key)
  deferrable initially immediate;

alter table recipe_clusters
  add constraint recipe_clusters_representative_recipe_id_fkey
  foreign key (representative_recipe_id) references recipes(id)
  deferrable initially immediate;

-- ---------------------------------------------------------------------------
-- 7. recipe_exports — the frozen pin-2 bundle (freeze on export).
-- ---------------------------------------------------------------------------
-- The live bundle is generated on demand and stays current with the taxonomy;
-- publishing to a consumer freezes a snapshot here, keyed by recipe + converter
-- version. Nothing public reads this (bundles are for consumer import via the
-- service role, not the website), so it stays admin/service-only.
create table recipe_exports (
  id                bigserial primary key,
  recipe_id         bigint not null references recipes(id) on delete cascade,
  recipe_slug       text not null,
  recipe_ref        text not null,            -- com.spiritolo/<slug>:v1
  converter_version text not null,
  bundle            jsonb not null,
  exported_at       timestamptz not null default now(),
  unique (recipe_id, converter_version)
);

create index recipe_exports_slug_idx on recipe_exports (recipe_slug);

-- ---------------------------------------------------------------------------
-- 8. recipes_public — the website contract (unchanged shape).
-- ---------------------------------------------------------------------------
-- security_invoker so the recipes RLS policy applies to view reads. `name`
-- aliases title and `jsonld` aliases source, preserving the columns the SPA and
-- normalizeRecipe already consume.
create view recipes_public with (security_invoker = true) as
  select id, source_url, site, title as name, author, image_url,
         source as jsonld, cluster_id, variant_key
  from recipes;

-- ---------------------------------------------------------------------------
-- 9. taxonomy_public — recreated (recipe_count now via the shared resolution).
-- ---------------------------------------------------------------------------
create view taxonomy_public
  with (security_invoker = true)
as
select
  n.id,
  n.slug,
  n.display_name,
  n.node_kind,
  n.default_role,
  n.is_cluster_node,
  n.is_defining_garnish,
  coalesce(p.parent_ids, '{}'::bigint[]) as parent_ids,
  coalesce(c.child_ids,  '{}'::bigint[]) as child_ids,
  coalesce(a.aliases,    '{}'::text[])   as aliases,
  coalesce(r.recipe_count, 0)            as recipe_count
from taxonomy_nodes n
left join lateral (
  select array_agg(parent_id order by parent_id) as parent_ids
  from taxonomy_edges where child_id = n.id
) p on true
left join lateral (
  select array_agg(child_id order by child_id) as child_ids
  from taxonomy_edges where parent_id = n.id
) c on true
left join lateral (
  select array_agg(alias order by alias) as aliases
  from taxonomy_aliases where node_id = n.id
) a on true
left join lateral (
  -- Recipes reaching this node through the shared name-keyed resolution.
  select count(distinct ri.recipe_id)::int as recipe_count
  from ingredient_resolutions ir
  join recipe_ingredients ri
    on lower(btrim(ri.name)) = ir.normalized_name
  where ir.taxonomy_slug = n.slug
) r on true;

-- ---------------------------------------------------------------------------
-- 10. RLS + grants.
-- ---------------------------------------------------------------------------
-- Content tables carry public recipe facts -> public read (anon + authenticated)
-- via a permissive read policy + column/table grants. Writes stay with the
-- table owner / service_role (BYPASSRLS); there is no anon/authenticated write
-- grant, so the read policy cannot widen into writes.
alter table recipes                enable row level security;
alter table recipe_ingredients     enable row level security;
alter table recipe_steps           enable row level security;
alter table ingredient_resolutions enable row level security;
alter table recipe_clusters        enable row level security;
alter table recipe_exports         enable row level security;   -- no policy: admin/service only

create policy recipes_public_read on recipes
  for select to anon, authenticated using (true);
create policy recipe_ingredients_public_read on recipe_ingredients
  for select to anon, authenticated using (true);
create policy recipe_steps_public_read on recipe_steps
  for select to anon, authenticated using (true);
create policy ingredient_resolutions_public_read on ingredient_resolutions
  for select to anon, authenticated using (true);
create policy recipe_clusters_public_read on recipe_clusters
  for select to anon, authenticated using (true);

grant select (id, source_url, site, title, author, image_url, source,
              cluster_id, variant_key, canonical_name, recipe_slug, equipment)
  on recipes to anon, authenticated;
grant select (id, recipe_id, position, name, amount, amount_max, unit,
              modifiers, raw_text)
  on recipe_ingredients to anon, authenticated;
grant select (id, recipe_id, step_index, verb, roles, modifiers, result)
  on recipe_steps to anon, authenticated;
grant select (id, normalized_name, taxonomy_slug, method, version)
  on ingredient_resolutions to anon, authenticated;
grant select (cluster_key, canonical_name, ingredient_set,
              representative_recipe_id, recipe_count, source_count, version)
  on recipe_clusters to anon, authenticated;

grant select on recipes_public  to anon, authenticated;
grant select on taxonomy_public to anon, authenticated;

-- ---------------------------------------------------------------------------
-- 11. Audit triggers — pipeline writes + manual edits captured identically.
-- ---------------------------------------------------------------------------
-- Same generic audit.log_change() the taxonomy tables use; attaching it here
-- fulfils the note left in 20260717091000_audit_triggers.sql.
create trigger audit_recipes
  after insert or update or delete on public.recipes
  for each row execute function audit.log_change();
create trigger audit_recipe_ingredients
  after insert or update or delete on public.recipe_ingredients
  for each row execute function audit.log_change();
create trigger audit_recipe_steps
  after insert or update or delete on public.recipe_steps
  for each row execute function audit.log_change();
create trigger audit_ingredient_resolutions
  after insert or update or delete on public.ingredient_resolutions
  for each row execute function audit.log_change();

-- ---------------------------------------------------------------------------
-- 12. Repoint the taxonomy-curation RPCs off the dropped
--     recipe_ingredients.taxonomy_node_id onto the shared resolution.
-- ---------------------------------------------------------------------------
-- A node's recipe usage is now "recipe_ingredients whose normalized name
-- resolves (via ingredient_resolutions) to a slug this node owns" — not a
-- per-row taxonomy id. Same signatures + semantics; only the usage subquery
-- changes, so the curation UI keeps working.
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
      select count(*)::int
      from public.recipe_ingredients ri
      join public.ingredient_resolutions ir
        on lower(btrim(ri.name)) = ir.normalized_name
      join public.taxonomy_nodes n on n.slug = ir.taxonomy_slug
      where n.id = p_id
    ),
    'taxonomy_proposals', (
      select count(*)::int from public.taxonomy_proposals where proposed_parent_id = p_id
    )
  );
end;
$$;

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
    from public.recipe_ingredients ri
    join public.ingredient_resolutions ir
      on lower(btrim(ri.name)) = ir.normalized_name
    join public.taxonomy_nodes n on n.slug = ir.taxonomy_slug
    where n.id = p_id;
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
