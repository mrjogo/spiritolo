-- Scope the extract-recipe run universe to what the stage can actually process.
--
-- `_eligible_base`'s extract-recipe branch used *all* pages, so the /ops
-- add-tasks facets advertised a "never run" count covering the entire crawl
-- (~484k) — pages that are not recipe content, or were never fetched, and that
-- the extract stage will never touch. The extract queue itself is gated to
-- classified recipe pages that have cached HTML (a corpus key):
-- `content_type in ('likely_drink_recipe','confirmed_drink') and corpus_key is
-- not null` (see extract.py `_page_queue`). Match the universe to that gate so
-- "never run" means genuinely-unextracted recipe pages, not the whole web.
--
-- Only the extract-recipe universe branch changes; the rest of the body is
-- copied verbatim from 20260727124000.
create or replace function public._eligible_base(p_stage text, p_filter jsonb)
returns table(
  entity_id bigint, title text, source text,
  status text, code_version text, last_run timestamptz
)
language sql
stable
set search_path = ''
as $$
  with universe as (
    select r.id as entity_id,
           coalesce(nullif(btrim(r.title), ''), r.source_url) as title,
           r.site as source
    from public.recipes r
    where p_stage not in ('extract-recipe', 'combine-nodes', 'connect-nodes')
    union all
    select p.id, p.url, p.site
    from public.pages p
    where p_stage = 'extract-recipe'
      and p.content_type = any (array['likely_drink_recipe', 'confirmed_drink'])
      and p.corpus_key is not null
    union all
    select n.id as entity_id, n.display_name as title, n.status as source
    from public.taxonomy_nodes n
    where p_stage in ('combine-nodes', 'connect-nodes')
  ),
  latest as (
    select distinct on (i.entity_id)
           i.entity_id,
           i.state as status,
           i.code_version,
           coalesce(i.finished_at, i.started_at) as last_run
    from public.job_items i
    where i.stage = p_stage
      and i.state in ('applied', 'flagged', 'failed')
    order by i.entity_id, i.id desc
  ),
  joined as (
    select u.entity_id, u.title, u.source,
           coalesce(l.status, 'never_run') as status,
           coalesce(l.code_version, '') as code_version,
           l.last_run
    from universe u
    left join latest l on l.entity_id = u.entity_id
  )
  select entity_id, title, source, status, code_version, last_run
  from joined
  where (p_filter -> 'status' is null
         or status = any (array(select jsonb_array_elements_text(p_filter -> 'status'))))
    and (p_filter -> 'source' is null
         or source = any (array(select jsonb_array_elements_text(p_filter -> 'source'))))
    and (p_filter ->> 'code_version_before' is null
         or code_version < (p_filter ->> 'code_version_before'))
    and (p_filter ->> 'search' is null
         or title ilike '%' || (p_filter ->> 'search') || '%');
$$;
