-- Rename pages.r2_key -> pages.corpus_key. The HTML corpus moved off Cloudflare
-- R2 to a generic S3-compatible object store (Railway Storage Bucket, Tigris),
-- so the "r2" name is stale; corpus_key matches corpus_loader / CorpusReader.
-- The key is unchanged (sha256(url)).
alter table pages rename column r2_key to corpus_key;

-- stage_queue_counts() is a SECURITY DEFINER function, not a view, so its stored
-- body does NOT auto-update on the column rename. Recreate it with the new
-- column name; the body is otherwise identical to
-- 20260721090000_stage_queue_counts.sql, and `create or replace` keeps the
-- existing grants.
create or replace function public.stage_queue_counts()
returns table(stage text, queue_depth bigint)
language plpgsql
stable
security definer
set search_path = ''
as $$
begin
  if not public.is_admin() then
    raise exception 'permission denied: not admin' using errcode = '42501';
  end if;

  return query
  select
    v.stage,
    case v.content_table
      when 'pages' then (
        select count(*)
        from public.pages p
        where p.content_type = any(array['likely_drink_recipe', 'confirmed_drink'])
          and p.corpus_key is not null
          and not exists (
            select 1 from public.stage_runs r
            where r.entity_type = 'page' and r.entity_id = p.id
              and r.stage = v.stage and r.version = v.version
          )
      )
      when 'recipes' then (
        select count(*)
        from public.recipes c
        where not exists (
          select 1 from public.stage_runs r
          where r.entity_type = 'recipe' and r.entity_id = c.id
            and r.stage = v.stage and r.version = v.version
        )
      )
    end as queue_depth
  from public.stage_queue_versions v
  order by v.stage;
end;
$$;
