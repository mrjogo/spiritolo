-- Make recipes_public run with the invoker's permissions so RLS on recipes applies.
alter view recipes_public set (security_invoker = true);

-- Column-level select on the base table (excludes fetched_at, extracted_at).
grant select (id, source_url, site, name, author, image_url, jsonld)
  on recipes to anon, authenticated;

-- Public read policy — required because RLS is enabled on recipes.
create policy recipes_public_read on recipes
  for select to anon, authenticated
  using (true);
