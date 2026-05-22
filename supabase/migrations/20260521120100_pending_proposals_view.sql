-- Read views for the /proposals page. Both are security_invoker so they
-- honor the existing taxonomy_proposals admin-only RLS policy without
-- needing their own grants beyond a column-level select for authenticated.
--
-- pending_proposals_view denormalizes the proposed parent's display_name
-- so the list and detail panes don't need a second round-trip per row.
-- candidates is left as the raw jsonb the mapper wrote
-- ([{node_id, display_name, similarity}]); the client renders it.
--
-- pending_proposals_parents_view powers the top-bar filter (parent buckets
-- in the pending queue, with per-bucket pending counts).

create view public.pending_proposals_view
  with (security_invoker = true)
as
select
  p.id,
  p.raw_string,
  p.proposed_slug,
  p.proposed_display_name,
  p.proposed_parent_id,
  parent.display_name as proposed_parent_display_name,
  p.candidates,
  p.mapper_version,
  p.created_at
from public.taxonomy_proposals p
left join public.taxonomy_nodes parent on parent.id = p.proposed_parent_id
where p.status = 'pending';

grant select on public.pending_proposals_view to authenticated;

create view public.pending_proposals_parents_view
  with (security_invoker = true)
as
select
  p.proposed_parent_id,
  parent.display_name as proposed_parent_display_name,
  count(*)::int as pending_count
from public.taxonomy_proposals p
left join public.taxonomy_nodes parent on parent.id = p.proposed_parent_id
where p.status = 'pending'
group by p.proposed_parent_id, parent.display_name;

grant select on public.pending_proposals_parents_view to authenticated;
