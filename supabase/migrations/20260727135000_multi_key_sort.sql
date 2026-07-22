-- Multidimensional sort for the run-selection pool + task list.
--
-- _sort_clause took a single "col:dir" token. It now accepts a comma-separated
-- ORDERED list ("title:asc,source:desc") and builds a multi-key ORDER BY —
-- first key primary, the rest tiebreakers — validating each column against the
-- caller's whitelist (unknown tokens are skipped, not injected). A stable
-- entity_id tiebreaker is always appended so pagination stays deterministic.
-- Single-token input still works unchanged (no comma).
--
-- eligible_pool/run_items are re-created only to widen their sort whitelists
-- (add code_version / why_added) so the UI can offer more fields; their bodies
-- are otherwise the 20260726093000 versions.
create or replace function public._sort_clause(
  p_sort text, p_allowed text[], p_default_col text, p_alias text
) returns text
language plpgsql
immutable
set search_path = ''
as $$
declare
  v_token text;
  v_col text;
  v_dir text;
  v_clause text;
  v_parts text[] := '{}';
begin
  foreach v_token in array
    string_to_array(coalesce(nullif(btrim(p_sort), ''), p_default_col), ',')
  loop
    v_token := btrim(v_token);
    continue when v_token = '';
    v_col := lower(split_part(v_token, ':', 1));
    v_dir := lower(nullif(split_part(v_token, ':', 2), ''));
    if v_dir is null then
      if right(v_col, 4) = '_asc' then
        v_dir := 'asc'; v_col := left(v_col, length(v_col) - 4);
      elsif right(v_col, 5) = '_desc' then
        v_dir := 'desc'; v_col := left(v_col, length(v_col) - 5);
      else
        v_dir := 'desc';
      end if;
    end if;
    -- 'status' is the UI's name for a run item's task_state.
    if v_col = 'status' and 'task_state' = any (p_allowed) then
      v_col := 'task_state';
    end if;
    continue when not (v_col = any (p_allowed));  -- skip unknown columns
    if v_dir not in ('asc', 'desc') then
      v_dir := 'desc';
    end if;
    v_clause := format('%I.%I %s', p_alias, v_col, v_dir);
    if v_col = 'last_run' then
      v_clause := v_clause || case when v_dir = 'asc' then ' nulls first' else ' nulls last' end;
    end if;
    v_parts := v_parts || v_clause;
  end loop;
  -- Nothing valid parsed -> the default column.
  if array_length(v_parts, 1) is null then
    v_parts := array[format('%I.%I desc', p_alias, p_default_col)];
  end if;
  -- Deterministic tiebreaker (both bases expose entity_id).
  v_parts := v_parts || format('%I.entity_id asc', p_alias);
  return array_to_string(v_parts, ', ');
end;
$$;

-- eligible_pool: widen the sort whitelist with code_version.
create or replace function public.eligible_pool(
  stage text, p_filter jsonb, sort text, "limit" int default 50, "offset" int default 0
) returns table(
  entity_id text, title text, source text, status text,
  status_detail text, last_run_label text, total_count bigint
)
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  v_filter jsonb := coalesce(p_filter, '{}'::jsonb);
  v_limit int := coalesce("limit", 50);
  v_offset int := coalesce("offset", 0);
  v_order text;
begin
  if not public.is_admin() then
    raise exception 'permission denied: not admin' using errcode = '42501';
  end if;
  v_order := public._sort_clause(
    sort,
    array['title', 'source', 'status', 'last_run', 'code_version', 'entity_id'],
    'last_run', 'b'
  );
  return query execute
    'select b.entity_id::text, b.title, b.source, b.status, null::text, '
    || 'case when b.last_run is null then null else to_char(b.last_run, ''YYYY-MM-DD'') end, '
    || 'count(*) over () '
    || 'from public._eligible_base($1, $2) b order by ' || v_order || ' limit $3 offset $4'
    using stage, v_filter, v_limit, v_offset;
end;
$$;

-- run_items: widen the sort whitelist with why_added.
create or replace function public.run_items(
  job_id bigint, p_filter jsonb, sort text, "limit" int default 50, "offset" int default 0
) returns table(
  item_id text, entity_id text, title text, source text,
  why_added text, task_state text, total_count bigint
)
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  v_filter jsonb := coalesce(p_filter, '{}'::jsonb);
  v_limit int := coalesce("limit", 50);
  v_offset int := coalesce("offset", 0);
  v_order text;
begin
  if not public.is_admin() then
    raise exception 'permission denied: not admin' using errcode = '42501';
  end if;
  v_order := public._sort_clause(
    sort,
    array['title', 'source', 'task_state', 'why_added', 'entity_id', 'item_id'],
    'item_id', 'b'
  );
  return query execute
    'select b.item_id::text, b.entity_id::text, b.title, b.source, b.why_added, b.task_state, '
    || 'count(*) over () '
    || 'from public._run_items_base($1, $2) b order by ' || v_order || ' limit $3 offset $4'
    using run_items.job_id, v_filter, v_limit, v_offset;
end;
$$;
