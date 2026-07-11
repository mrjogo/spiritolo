-- Fix a pre-existing Supabase "splinter" lint: `public.set_updated_at`
-- (added in 20260505040811_add_updated_at.sql, after the earlier lint-fix
-- migrations) was created without a fixed search_path, so it trips
-- `function_search_path_mutable`. Recreate it with an empty search_path.
--
-- `set search_path = ''` is safe here: the only function referenced is now(),
-- which lives in pg_catalog and is always implicitly resolvable regardless of
-- search_path; `new.updated_at` is a trigger pseudo-column, not schema-scoped.
-- `create or replace` leaves the existing triggers that call this function
-- intact — no need to touch the per-table triggers.

create or replace function public.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;
