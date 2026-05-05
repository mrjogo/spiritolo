-- Make the two FKs in the recipes ↔ recipe_clusters cycle deferrable so
-- the upload-to-staging script can push both sides in one transaction
-- with SET CONSTRAINTS ALL DEFERRED. INITIALLY IMMEDIATE keeps default
-- behavior for normal application writes unchanged; only an explicit
-- SET CONSTRAINTS DEFERRED inside a transaction defers them.
--
-- ALTER CONSTRAINT is metadata-only — no row is touched, no FK protection
-- is dropped at any moment, no validation re-pass is needed.
--
-- Spec: docs/superpowers/specs/2026-05-05-stage-2-uploader-design.md

alter table public.recipes
  alter constraint recipes_cluster_id_fkey
  deferrable initially immediate;

alter table public.recipe_clusters
  alter constraint recipe_clusters_representative_recipe_id_fkey
  deferrable initially immediate;

-- Verify the post-state. If a constraint name has drifted from the
-- expected default in some prior migration, this raises and the
-- migration aborts; manual investigation before re-applying.
do $$
declare
  bad_count int;
  found_count int;
begin
  select count(*)
    into bad_count
    from pg_constraint
    where conname = any (array[
      'recipes_cluster_id_fkey',
      'recipe_clusters_representative_recipe_id_fkey'
    ])
      and (not condeferrable or condeferred);

  if bad_count > 0 then
    raise exception
      'Expected both target FKs to be deferrable+immediate; % violated', bad_count;
  end if;

  select count(*) into found_count
    from pg_constraint
    where conname = any (array[
      'recipes_cluster_id_fkey',
      'recipe_clusters_representative_recipe_id_fkey'
    ]);

  if found_count <> 2 then
    raise exception 'Expected to find exactly 2 matching constraints by name; found %', found_count;
  end if;
end $$;
