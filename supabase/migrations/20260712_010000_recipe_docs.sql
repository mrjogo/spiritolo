-- B2 — recipe_docs: the source-of-truth content table for the v2.1 redesign.
--
-- One RecipeGF-shaped JSONB document per recipe (doc), starting partial at the
-- extract stage and growing field-by-field through the pipeline. Pipeline-
-- internal fields live in an `_x` sidecar that is stripped at export, so the
-- portable subset is byte-identical to the exported pin-2 bundle.
--
-- Foundation §1.1: the doc is the single writer; the structured columns below
-- are GENERATED straight out of the doc (adding one is free, removing one loses
-- nothing — the fact still lives in the doc). The authoritative per-stage "has
-- stage X run at version V" truth is stage_runs (§2 / B4); `state` here is only
-- a cheap denormalized queue prefilter.

create table recipe_docs (
  id          bigserial primary key,
  source_url  text not null unique,
  doc         jsonb not null,
  doc_schema  text not null default 'spiritolo/recipe-doc/v1',

  -- Advisory pipeline cursor (denormalized for cheap queue gating). Authority
  -- is stage_runs, not this column.
  state       text not null default 'extracted'
              check (state in ('extracted','parsed','mapped','clustered','exported')),

  -- Generated projection columns — the ONLY structured columns, read straight
  -- out of the doc so indexes/joins are cheap and the doc stays the sole writer.
  site           text generated always as (doc #>> '{_x,site}') stored,
  canonical_name text generated always as (doc #>> '{_x,canonical_name}') stored,
  cluster_key    text generated always as (doc #>> '{_x,cluster_key}') stored,
  variant_key    text generated always as (doc #>> '{_x,variant_key}') stored,
  title          text generated always as (doc ->> 'title') stored,

  updated_at  timestamptz not null default now()
);

-- jsonb_path_ops GIN (not default jsonb_ops): we containment-query the doc
-- (doc @> '{"ingredients":[{"ref":"spiritolo/gin"}]}'), which jsonb_path_ops
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

-- Deny-write RLS. Direct writes are RPC/pipeline-only (service_role bypasses
-- RLS); anon/authenticated get read only. The security_invoker recipes_public
-- view below runs as the invoker, so anon needs SELECT + a read policy on the
-- base table for the view to return rows — this mirrors the original
-- recipes_public_read pattern (20260424054315). No write grant + no write
-- policy => an anon INSERT/UPDATE/DELETE fails with insufficient_privilege.
alter table recipe_docs enable row level security;

create policy recipe_docs_public_read on recipe_docs
  for select to anon, authenticated
  using (true);

grant select on recipe_docs to anon, authenticated;

-- Public read surface. security_invoker=true so RLS on recipe_docs applies to
-- the caller (matches the existing recipes_public). Preserves the current public
-- column contract exactly — id, source_url, site, name, author, image_url,
-- jsonld — so the deployed public site keeps rendering unchanged. Every public
-- field is projected out of the doc; no _x internal field is exposed beyond the
-- whitelisted jsonld path.
--
-- recipes_public already exists (created over the legacy `recipes` table, last
-- redefined by the dedup migration to add cluster_id/variant_key). The v2.1
-- redesign supersedes that projection: the view now reads from recipe_docs, and
-- cluster identity lives in the doc (cluster_key/variant_key), not as public
-- columns. Because CREATE OR REPLACE can only append columns, drop first. No
-- other object depends on the view (recipe_variants reads `recipes`, not this).
drop view if exists recipes_public;
create view recipes_public with (security_invoker = true) as
  select
    id,
    source_url,
    site,
    coalesce(doc ->> 'title', doc #>> '{_x,source,jsonld,name}') as name,
    doc #>> '{_x,source,jsonld,author}' as author,
    doc #>> '{_x,source,jsonld,image}'  as image_url,
    doc #>  '{_x,source,jsonld}'         as jsonld
  from recipe_docs;

grant select on recipes_public to anon, authenticated;
