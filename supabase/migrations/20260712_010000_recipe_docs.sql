-- B2 — recipe_docs: the source-of-truth content table for the v2.1 redesign.
--
-- The content of a recipe is split across three JSONB columns so the public/
-- internal boundary is enforceable with COLUMN-LEVEL grants (a grant can hide a
-- whole column, but not a sub-key inside one jsonb):
--
--   * doc    — the PORTABLE recipegf/cocktail/v1 recipe ONLY (schema, id, title,
--              ingredients, steps, equipment). No internal fields. This column
--              IS the export, verbatim — nothing to strip at export time.
--   * source — raw Schema.org JSON-LD + display provenance the public site
--              renders (nullable; filled at extract). Public.
--   * x      — internal-only bookkeeping (taxonomy node ids, mapper method, role,
--              cluster/variant keys, jsonld_origin, position mirror, …).
--              ADMIN-ONLY: never granted to anon, never exported.
--
-- The doc validates against RecipeGF's own schema (doc_schema defaults to
-- 'recipegf/cocktail/v1'), since it no longer carries an _x superset.

create table recipe_docs (
  id          bigserial primary key,
  source_url  text not null unique,

  -- Portable RecipeGF recipe — this column is the export, verbatim.
  doc         jsonb not null,
  doc_schema  text not null default 'recipegf/cocktail/v1',

  -- Raw source JSON-LD + display provenance the public site renders. Public.
  source      jsonb,

  -- Internal-only pipeline bookkeeping. Admin-only, never public, never
  -- exported; the column grant below deliberately omits it.
  x           jsonb not null default '{}',

  -- Public scalar columns (populated by the extract stage; nullable until then).
  name        text,
  author      text,
  image_url   text,

  -- Advisory pipeline cursor (denormalized for cheap queue gating). Authority
  -- is stage_runs (§2 / B4), not this column.
  state       text not null default 'extracted'
              check (state in ('extracted','parsed','mapped','clustered','exported')),

  -- Generated projection columns. title comes from the portable doc; the rest
  -- from the internal x sidecar. Generated columns are real columns, grantable
  -- one-by-one — so `site` can be public while cluster_key/canonical_name/
  -- variant_key stay internal (never granted to anon).
  title          text generated always as (doc ->> 'title') stored,
  site           text generated always as (x ->> 'site') stored,
  canonical_name text generated always as (x ->> 'canonical_name') stored,
  cluster_key    text generated always as (x ->> 'cluster_key') stored,
  variant_key    text generated always as (x ->> 'variant_key') stored,

  updated_at  timestamptz not null default now()
);

-- jsonb_path_ops GIN (not default jsonb_ops): we containment-query the portable
-- doc (doc @> '{"ingredients":[{"ref":"spiritolo/gin"}]}'), which jsonb_path_ops
-- indexes at a fraction of the size.
create index recipe_docs_doc_gin   on recipe_docs using gin (doc jsonb_path_ops);
create index recipe_docs_site_idx  on recipe_docs (site);
create index recipe_docs_state_idx on recipe_docs (state);
create index recipe_docs_cluster_idx on recipe_docs (cluster_key) where cluster_key is not null;
-- Trigram indexes for the substring search the current recipes_search_trgm
-- migration provides today. gin_trgm_ops resolves via the extensions schema on
-- the search_path (pg_trgm was relocated there by 20260503180000_security_lints).
create index recipe_docs_title_trgm     on recipe_docs using gin (title gin_trgm_ops);
create index recipe_docs_canonical_trgm on recipe_docs using gin (canonical_name gin_trgm_ops);

-- RLS on with a public read policy, exactly like the recipes/recipes_public
-- pattern (20260424054315): the security_invoker view runs as the invoker, so
-- anon needs a select policy + column grants on the base table.
alter table recipe_docs enable row level security;

create policy recipe_docs_public_read on recipe_docs
  for select to anon, authenticated
  using (true);

-- COLUMN-LEVEL grant — the crux of the public/internal split. anon/authenticated
-- may read the public recipe (doc), the rendered source, the public scalar
-- columns, and the public `site`, but NOT the internal x sidecar nor the
-- internal-only generated keys (cluster_key/canonical_name/variant_key). So even
-- a direct `select x from recipe_docs` is denied at the privilege level — the
-- sidecar can never leak. No write grant => an anon INSERT/UPDATE/DELETE fails
-- with insufficient_privilege.
grant select (id, source_url, site, name, author, image_url, doc, source)
  on recipe_docs to anon, authenticated;

-- Public read surface. security_invoker=true so RLS + the column grants above
-- apply to the caller (matches the existing recipes_public). Preserves the
-- current public column contract exactly — id, source_url, site, name, author,
-- image_url, jsonld — so the deployed public site keeps rendering unchanged.
-- jsonld is the rendered source JSON-LD; no internal x field is reachable here.
--
-- recipes_public already exists (created over the legacy `recipes` table, last
-- redefined by the dedup migration to add cluster_id/variant_key). The v2.1
-- redesign supersedes that projection: the view now reads from recipe_docs.
-- Because CREATE OR REPLACE can only append columns, drop first. No other object
-- depends on the view (recipe_variants reads `recipes`, not this).
drop view if exists recipes_public;
create view recipes_public with (security_invoker = true) as
  select
    id,
    source_url,
    site,
    name,
    author,
    image_url,
    source -> 'jsonld' as jsonld
  from recipe_docs;

grant select on recipes_public to anon, authenticated;
