-- Proposal review write boundary. Three SECURITY DEFINER functions,
-- one transaction each, all guarded by public.is_admin() — mirroring
-- the taxonomy curation RPCs (20260507130000_taxonomy_curation_rpcs.sql).
--
-- Versioning note: each RPC stamps recipe_ingredients with
-- (mapper_source='llm', mapper_version=<proposal.mapper_version>). When
-- MAPPER_VERSION later bumps, the next mapper run will re-process these
-- rows — but the Create/Map actions inserted a taxonomy_alias for the
-- raw_string, so the alias layer (Phase 1) will resolve it immediately
-- and write back at the new mapper_version. No curator work is lost.
-- (Flagged rows have no alias; they will re-queue as a fresh proposal
-- under the new mapper_version. The flag_reason on the underlying
-- recipe_ingredients row persists either way.)

------------------------------------------------------------------------
-- apply_proposal_create(proposal_id, slug_override)
-- Insert new taxonomy_node + edge to proposed_parent + alias for
-- raw_string + provenance row; resolve all matching recipe_ingredients
-- rows; mark proposal approved.
-- slug_override allows the reviewer to tweak the LLM's proposed slug
-- inline before approving. Pass NULL to keep proposed_slug as-is.
------------------------------------------------------------------------
create or replace function public.apply_proposal_create(
  p_proposal_id   bigint,
  p_slug_override text default null
)
returns bigint
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_raw            text;
  v_slug           text;
  v_display_name   text;
  v_parent_id      bigint;
  v_mapper_version text;
  v_new_node_id    bigint;
begin
  if not public.is_admin() then
    raise exception 'permission denied: not admin' using errcode = '42501';
  end if;

  select raw_string, proposed_slug, proposed_display_name,
         proposed_parent_id, mapper_version
    into v_raw, v_slug, v_display_name, v_parent_id, v_mapper_version
  from public.taxonomy_proposals
  where id = p_proposal_id and status = 'pending';

  if not found then
    raise exception 'proposal % not found or not pending', p_proposal_id
      using errcode = '02000';
  end if;

  if p_slug_override is not null and trim(p_slug_override) <> '' then
    v_slug := p_slug_override;
  end if;

  -- proposed_parent_id may be null (LLM did not pick one); allow but
  -- skip the edge insert in that case. proposed_display_name may also
  -- be null for legacy proposals; fall back to the slug.
  insert into public.taxonomy_nodes (slug, display_name)
  values (v_slug, coalesce(v_display_name, v_slug))
  returning id into v_new_node_id;

  if v_parent_id is not null then
    insert into public.taxonomy_edges (parent_id, child_id)
    values (v_parent_id, v_new_node_id);
  end if;

  insert into public.taxonomy_aliases (alias, node_id)
  values (v_raw, v_new_node_id)
  on conflict (alias, node_id) do nothing;

  insert into public.taxonomy_provenance
    (node_id, source, mapper_version, raw_string)
  values
    (v_new_node_id, 'llm-mapper', v_mapper_version, v_raw);

  update public.recipe_ingredients
     set taxonomy_node_id = v_new_node_id,
         mapper_source    = 'llm',
         mapper_version   = v_mapper_version,
         mapper_at        = now()
   where lower(trim(name)) = v_raw;

  update public.taxonomy_proposals
     set status      = 'approved',
         decided_by  = coalesce(auth.uid()::text, 'web'),
         decided_at  = now()
   where id = p_proposal_id;

  return v_new_node_id;
end;
$$;

grant execute on function public.apply_proposal_create(bigint, text)
  to authenticated;

------------------------------------------------------------------------
-- apply_proposal_map_to_existing(proposal_id, node_id)
-- Alias raw_string → node_id; resolve matching recipe_ingredients rows;
-- mark proposal approved.
------------------------------------------------------------------------
create or replace function public.apply_proposal_map_to_existing(
  p_proposal_id bigint,
  p_node_id     bigint
)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_raw            text;
  v_mapper_version text;
begin
  if not public.is_admin() then
    raise exception 'permission denied: not admin' using errcode = '42501';
  end if;

  if not exists (select 1 from public.taxonomy_nodes where id = p_node_id) then
    raise exception 'taxonomy_node % not found', p_node_id using errcode = '23503';
  end if;

  select raw_string, mapper_version
    into v_raw, v_mapper_version
  from public.taxonomy_proposals
  where id = p_proposal_id and status = 'pending';

  if not found then
    raise exception 'proposal % not found or not pending', p_proposal_id
      using errcode = '02000';
  end if;

  insert into public.taxonomy_aliases (alias, node_id)
  values (v_raw, p_node_id)
  on conflict (alias, node_id) do nothing;

  update public.recipe_ingredients
     set taxonomy_node_id = p_node_id,
         mapper_source    = 'llm',
         mapper_version   = v_mapper_version,
         mapper_at        = now()
   where lower(trim(name)) = v_raw;

  update public.taxonomy_proposals
     set status      = 'approved',
         decided_by  = coalesce(auth.uid()::text, 'web'),
         decided_at  = now()
   where id = p_proposal_id;
end;
$$;

grant execute on function public.apply_proposal_map_to_existing(bigint, bigint)
  to authenticated;

------------------------------------------------------------------------
-- apply_proposal_flag(proposal_id, reason)
-- Write flag_reason to all matching recipe_ingredients rows; mark
-- proposal flagged. Reason is required (caller-side enforced too).
------------------------------------------------------------------------
create or replace function public.apply_proposal_flag(
  p_proposal_id bigint,
  p_reason      text
)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_raw text;
begin
  if not public.is_admin() then
    raise exception 'permission denied: not admin' using errcode = '42501';
  end if;

  if p_reason is null or trim(p_reason) = '' then
    raise exception 'flag reason required' using errcode = '22023';
  end if;

  select raw_string into v_raw
  from public.taxonomy_proposals
  where id = p_proposal_id and status = 'pending';

  if not found then
    raise exception 'proposal % not found or not pending', p_proposal_id
      using errcode = '02000';
  end if;

  update public.recipe_ingredients
     set flag_reason = p_reason
   where lower(trim(name)) = v_raw;

  update public.taxonomy_proposals
     set status      = 'flagged',
         decided_by  = coalesce(auth.uid()::text, 'web'),
         decided_at  = now()
   where id = p_proposal_id;
end;
$$;

grant execute on function public.apply_proposal_flag(bigint, text)
  to authenticated;
