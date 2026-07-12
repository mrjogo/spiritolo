-- P3 read-surface hardening for the RecipeGF export stage.
--
-- Barbot's menu-build import (P3) pulls each drink's pin-2 bundle by *slug* —
-- offline via the <slug>.json drop, or live via a service-role DB adapter over
-- PostgREST. This migration makes that read path safe and clean:
--
--   1. slug is a unique join/sync key per converter_version (today only
--      (cluster_id, converter_version) is unique, but Barbot joins by slug).
--   2. a small cache of the in-repo spiritolo/ verb-defs, so the bundle RPC can
--      return a genuinely *self-contained* pin-2 bundle (the YAML defs live in
--      the ingredients package; the cache is refreshed from them on every
--      export — see db.sync_verb_defs — so it never drifts).
--   3. two SECURITY DEFINER RPCs (catalog + bundle) callable by service_role,
--      giving the live adapter a clean network read path without exposing the
--      relational tables.
--
-- Nothing here changes what the converter emits or how bundles are generated:
-- the recipegf_* relational rows stay the source of truth and db.generate_bundle
-- stays the canonical (Python) projection. The bundle RPC is a second projection
-- of the SAME rows; a DB parity test pins the two equal on recipe/verbs/
-- meta.slug/meta.source (byte-for-byte) and on meta.imported_at as the same
-- instant. imported_at is the ONLY field not byte-identical: to_jsonb(timestamptz)
-- and Python datetime.isoformat() render one instant slightly differently
-- (fractional-second / offset form). That is safe because nothing content-hashes
-- a bundle across the two ingress paths — the bundle is stored as JSONB and
-- validated structurally, never compared byte-for-byte between RPC and Python.

------------------------------------------------------------------------
-- 1. slug uniqueness (per converter_version, exported rows only)
------------------------------------------------------------------------
-- Self-heal first: if the DB already holds >1 exported row for the same
-- (slug, converter_version) — two distinct clusters minting the same identity,
-- a real conflict — keep the lowest cluster_id and delete the rest so the
-- unique index below can always build (the deploy can't fail on pre-existing
-- data). Deleting a header cascades its ingredient/step rows; the affected
-- clusters simply re-queue. The export stage's mint-time guard
-- (db.slug_claimed_by_other_cluster) then parks them into recipegf_proposals
-- for human dedup, so the conflict is surfaced, not silently dropped.
delete from recipegf_recipes r
using recipegf_recipes keep
where r.status = 'exported'
  and keep.status = 'exported'
  and r.slug = keep.slug
  and r.converter_version = keep.converter_version
  and r.cluster_id > keep.cluster_id;

-- Partial: 'uncertain' parking rows have slug null and must not collide.
create unique index recipegf_recipes_slug_version_uidx
  on recipegf_recipes (slug, converter_version)
  where status = 'exported';

------------------------------------------------------------------------
-- 2. verb-def cache (self-contained-bundle support)
------------------------------------------------------------------------
-- Mirror of the in-repo spiritolo/ verb-definition YAML (recipegf/verbs/*.yaml),
-- keyed by fully-qualified verb name. Source of truth stays the YAML; this table
-- is refreshed from it at export time (db.sync_verb_defs), so a bundle row and
-- the verb-defs its steps reference are always written in the same run.
create table recipegf_verb_defs (
  verb        text primary key,
  definition  jsonb not null,
  updated_at  timestamptz not null default now()
);

-- Admin/pipeline + service-role only (matches the recipegf_* tables): RLS on,
-- no policy. The SECURITY DEFINER RPCs below read it as owner.
alter table recipegf_verb_defs enable row level security;

------------------------------------------------------------------------
-- 3a. recipegf_catalog() — list exported drinks (slug/title/…)
------------------------------------------------------------------------
-- Barbot's live adapter lists the catalog, then pulls each bundle by slug.
-- p_converter_version null => all exported versions; otherwise scope to one.
create or replace function public.recipegf_catalog(p_converter_version text default null)
returns table (
  slug              text,
  title             text,
  technique         text,
  converter_version text,
  exported_at       timestamptz
)
language sql
stable
security definer
set search_path = ''
as $$
  select slug, title, technique, converter_version, exported_at
  from public.recipegf_recipes
  where status = 'exported'
    and (p_converter_version is null or converter_version = p_converter_version)
  order by slug, converter_version;
$$;

------------------------------------------------------------------------
-- 3b. recipegf_bundle(slug, converter_version) — the self-contained bundle
------------------------------------------------------------------------
-- Reconstructs the pin-2 bundle {recipe, verbs, meta} from the relational rows
-- (+ the verb-def cache). Equivalent to db.generate_bundle: byte-identical on
-- recipe/verbs/meta.slug/meta.source, and the same instant on meta.imported_at
-- (the timestamp's rendering differs — see the header note). Returns null when
-- no exported row matches. This is the SQL twin of db.generate_bundle_by_slug;
-- a parity test asserts they agree, so the shape lives in one behavior even
-- though it has two implementations.
create or replace function public.recipegf_bundle(
  p_slug text,
  p_converter_version text
)
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
  with hdr as (
    select id, slug, recipe_id, title, equipment, source_url, exported_at
    from public.recipegf_recipes
    where slug = p_slug
      and converter_version = p_converter_version
      and status = 'exported'
    limit 1
  ),
  ings as (
    select coalesce(
             jsonb_agg(
               jsonb_build_object(
                 'name', ri.name,
                 'quantity', jsonb_build_object('amount', ri.amount::float8, 'unit', ri.unit)
               ) order by ri.position),
             '[]'::jsonb) as arr
    from public.recipegf_ingredients ri
    join hdr on hdr.id = ri.recipegf_recipe_id
  ),
  stps as (
    select coalesce(
             jsonb_agg(
               (jsonb_build_object('verb', rs.verb, 'result', rs.result)
                 || coalesce(rs.roles, '{}'::jsonb)
                 || case when rs.modifiers is not null
                         then jsonb_build_object('modifiers', rs.modifiers)
                         else '{}'::jsonb end)
               order by rs.step_index),
             '[]'::jsonb) as arr
    from public.recipegf_steps rs
    join hdr on hdr.id = rs.recipegf_recipe_id
  ),
  vdefs as (
    select coalesce(jsonb_agg(vd.definition order by vd.verb), '[]'::jsonb) as arr
    from public.recipegf_verb_defs vd
    where vd.verb in (
      select distinct rs.verb
      from public.recipegf_steps rs
      join hdr on hdr.id = rs.recipegf_recipe_id
      where rs.verb like 'spiritolo/%'
    )
  )
  select jsonb_build_object(
    'recipe', jsonb_build_object(
      'schema', 'recipegf/cocktail/v1',   -- RECIPE_SCHEMA (stable const; parity test guards drift)
      'id', hdr.recipe_id,
      'title', hdr.title,
      'ingredients', ings.arr,
      'equipment', to_jsonb(hdr.equipment),
      'steps', stps.arr
    ),
    'verbs', vdefs.arr,
    'meta', jsonb_build_object(
      'slug', hdr.slug,
      'source', coalesce(hdr.source_url, ''),
      -- Same instant as the Python projection's exported_at.isoformat(); the ISO
      -- string form may differ (fractional-second/offset). Instant-equal is the
      -- contract — see the header note and the parity test.
      'imported_at', to_jsonb(hdr.exported_at)
    )
  )
  from hdr, ings, stps, vdefs;
$$;

-- Lock down, expose EXECUTE only to service_role (Barbot's live adapter role).
revoke all on function public.recipegf_catalog(text) from public;
revoke all on function public.recipegf_bundle(text, text) from public;
grant execute on function public.recipegf_catalog(text) to service_role;
grant execute on function public.recipegf_bundle(text, text) to service_role;
