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
-- 20260422120000_create_recipes.sql and security_invoker was set in
-- 20260424054315_recipes_public_security_invoker.sql; we replace it
-- preserving the security_invoker=true option.
create or replace view recipes_public with (security_invoker = true) as
  select id, source_url, site, name, author, image_url, jsonld,
         cluster_id, variant_key
  from recipes;

-- Extend the column-level grant on the base table to include the new columns
-- (the anon/authenticated grant in the security_invoker migration only covers
-- the original columns; without this the view would silently return nulls for
-- the new columns under RLS).
grant select (cluster_id, variant_key) on recipes to anon, authenticated;
