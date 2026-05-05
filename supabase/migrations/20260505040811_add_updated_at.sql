-- Add an auto-maintained updated_at column + BEFORE UPDATE trigger to every
-- public-schema table that doesn't already have one. A future workflow uses
-- updated_at to detect row-level changes by timestamp.
--
-- Also backfill created_at on the four tables that lack it (recipes,
-- recipe_ingredients, taxonomy_edges, taxonomy_aliases), so every public table
-- exposes both timestamps. Existing rows get now() as their created_at — no
-- pre-migration history is recoverable.
--
-- Skipped (with reason):
--   recipes_public        view (triggers don't apply)
--   recipe_variants       view
--   taxonomy_public       view

create or replace function public.set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

------------------------------------------------------------------------
-- recipes
------------------------------------------------------------------------
alter table public.recipes
  add column if not exists created_at timestamptz not null default now(),
  add column if not exists updated_at timestamptz not null default now();
drop trigger if exists set_updated_at on public.recipes;
create trigger set_updated_at
  before update on public.recipes
  for each row execute function public.set_updated_at();

------------------------------------------------------------------------
-- recipe_ingredients
------------------------------------------------------------------------
alter table public.recipe_ingredients
  add column if not exists created_at timestamptz not null default now(),
  add column if not exists updated_at timestamptz not null default now();
drop trigger if exists set_updated_at on public.recipe_ingredients;
create trigger set_updated_at
  before update on public.recipe_ingredients
  for each row execute function public.set_updated_at();

------------------------------------------------------------------------
-- taxonomy_nodes
------------------------------------------------------------------------
alter table public.taxonomy_nodes
  add column if not exists updated_at timestamptz not null default now();
drop trigger if exists set_updated_at on public.taxonomy_nodes;
create trigger set_updated_at
  before update on public.taxonomy_nodes
  for each row execute function public.set_updated_at();

------------------------------------------------------------------------
-- taxonomy_edges
------------------------------------------------------------------------
alter table public.taxonomy_edges
  add column if not exists created_at timestamptz not null default now(),
  add column if not exists updated_at timestamptz not null default now();
drop trigger if exists set_updated_at on public.taxonomy_edges;
create trigger set_updated_at
  before update on public.taxonomy_edges
  for each row execute function public.set_updated_at();

------------------------------------------------------------------------
-- taxonomy_aliases
------------------------------------------------------------------------
alter table public.taxonomy_aliases
  add column if not exists created_at timestamptz not null default now(),
  add column if not exists updated_at timestamptz not null default now();
drop trigger if exists set_updated_at on public.taxonomy_aliases;
create trigger set_updated_at
  before update on public.taxonomy_aliases
  for each row execute function public.set_updated_at();

------------------------------------------------------------------------
-- taxonomy_provenance
------------------------------------------------------------------------
alter table public.taxonomy_provenance
  add column if not exists updated_at timestamptz not null default now();
drop trigger if exists set_updated_at on public.taxonomy_provenance;
create trigger set_updated_at
  before update on public.taxonomy_provenance
  for each row execute function public.set_updated_at();

------------------------------------------------------------------------
-- taxonomy_proposals
------------------------------------------------------------------------
alter table public.taxonomy_proposals
  add column if not exists updated_at timestamptz not null default now();
drop trigger if exists set_updated_at on public.taxonomy_proposals;
create trigger set_updated_at
  before update on public.taxonomy_proposals
  for each row execute function public.set_updated_at();

------------------------------------------------------------------------
-- cocktail_aliases
------------------------------------------------------------------------
alter table public.cocktail_aliases
  add column if not exists updated_at timestamptz not null default now();
drop trigger if exists set_updated_at on public.cocktail_aliases;
create trigger set_updated_at
  before update on public.cocktail_aliases
  for each row execute function public.set_updated_at();

------------------------------------------------------------------------
-- recipe_clusters
------------------------------------------------------------------------
alter table public.recipe_clusters
  add column if not exists updated_at timestamptz not null default now();
drop trigger if exists set_updated_at on public.recipe_clusters;
create trigger set_updated_at
  before update on public.recipe_clusters
  for each row execute function public.set_updated_at();

------------------------------------------------------------------------
-- profiles
------------------------------------------------------------------------
alter table public.profiles
  add column if not exists updated_at timestamptz not null default now();
drop trigger if exists set_updated_at on public.profiles;
create trigger set_updated_at
  before update on public.profiles
  for each row execute function public.set_updated_at();
