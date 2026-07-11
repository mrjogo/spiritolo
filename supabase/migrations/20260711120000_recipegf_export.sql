-- P2 (RecipeGF export): persist per-drink RecipeGF pin-2 bundles + a
-- propose→review queue for drinks the deterministic converter can't yet emit.
--
-- A "drink" is a recipe_clusters row (the canonical drink identity). One bundle
-- per cluster: slug minted from canonical_name, recipe content from the
-- cluster's representative recipe. Mirrors the dedup pattern of writing
-- resolution + source + version directly onto the row (no separate cache).

alter table recipe_clusters
  add column recipegf_slug        text,
  add column recipegf_bundle      jsonb,
  add column recipegf_source      text,
  add column recipegf_version     text,
  add column recipegf_status      text check (recipegf_status in ('exported', 'uncertain')),
  add column recipegf_exported_at timestamptz;

-- The export work queue gates on "no current-version bundle": a cluster with
-- recipegf_version null or <> the current CONVERTER_VERSION needs (re)export.
create index recipe_clusters_recipegf_pending_idx
  on recipe_clusters (recipegf_version);

-- Review queue for drinks the converter parked as Uncertain (no technique,
-- unresolved ingredient, muddle, untranslatable unit, ...). Mirrors
-- taxonomy_proposals: a text+CHECK status, idempotent enqueue via a unique
-- (cluster, version) key. Resolving one is a taxonomy/data/rules fix followed
-- by `recipegf-export --reset` (or a CONVERTER_VERSION bump).
create table recipegf_proposals (
  id                bigserial primary key,
  cluster_id        bigint references recipe_clusters(id),
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

-- Admin/pipeline-only: nothing public reads this queue.
alter table recipegf_proposals enable row level security;
