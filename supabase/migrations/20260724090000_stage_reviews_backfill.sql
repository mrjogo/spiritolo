-- Backfill the three bespoke review mechanisms into stage_reviews.
--
-- DATA MIGRATION ONLY — this migration is additive and does NOT drop anything.
-- After it, stage_reviews is the consolidated store and the map writer already
-- emits unified reviews. recipegf_proposals was already dropped from the schema
-- by an earlier migration (zero readers). taxonomy_proposals is left in place but
-- DEPRECATED (no new rows written); dropping it is a follow-up that must first
-- rewire its remaining readers: the node-delete blocker functions in
-- 20260507130000_taxonomy_curation_rpcs.sql (`blockers`, `delete_node`, which
-- count proposed_parent_id = p_id), mapping/proposals.py + its tests, and web
-- DeleteNodeModal / rpcs.ts. Keeping it here means zero data loss and zero
-- broken readers in this step.

-- 1. taxonomy_proposals -> map machine_proposal reviews.
insert into stage_reviews
    (entity_kind, entity_id, stage, state, origin, payload, origin_version,
     reviewed_by, reviewed_at, created_at)
select
    'ingredient_name', tp.raw_string, 'map',
    case tp.status
      when 'pending'  then 'open'
      when 'approved' then 'resolved'
      when 'rejected' then 'dismissed'
    end,
    'machine_proposal',
    jsonb_build_object(
        'kind', 'form',
        'proposed_slug', tp.proposed_slug,
        'proposed_display_name', tp.proposed_display_name,
        'proposed_parent_id', tp.proposed_parent_id,
        'candidates', tp.candidates
    ),
    tp.mapper_version, tp.decided_by, tp.decided_at, tp.created_at
from taxonomy_proposals tp
on conflict (entity_kind, entity_id, stage) where state = 'open' do nothing;

-- 2. recipegf_proposals: already dropped from the schema by an earlier
--    migration (it had zero readers), so there is nothing to migrate — that
--    bespoke mechanism is already gone.

-- 3. ingredient_resolutions.method='manual' -> map human_flag resolved overrides.
--    The live resolution row stays; this backs it with a durable override so it
--    survives reruns.
insert into stage_reviews
    (entity_kind, entity_id, stage, state, origin, payload, created_at)
select
    'ingredient_name', ir.normalized_name, 'map', 'resolved', 'human_flag',
    jsonb_build_object('slug', ir.taxonomy_slug), ir.created_at
from ingredient_resolutions ir
where ir.method = 'manual' and ir.taxonomy_slug is not null
on conflict do nothing;

-- 4. Verify: every source entity is represented in stage_reviews (robust to the
--    one-open dedup and to empty sources — passes as a no-op on an empty DB).
do $$
declare missing int;
begin
  select count(*) into missing
  from (select distinct raw_string from taxonomy_proposals) t
  where not exists (
    select 1 from stage_reviews sr
    where sr.stage = 'map' and sr.origin = 'machine_proposal'
      and sr.entity_id = t.raw_string
  );
  assert missing = 0, 'taxonomy_proposals rows not fully migrated to stage_reviews';

  select count(*) into missing
  from (
    select distinct normalized_name from ingredient_resolutions
    where method = 'manual' and taxonomy_slug is not null
  ) t
  where not exists (
    select 1 from stage_reviews sr
    where sr.stage = 'map' and sr.origin = 'human_flag' and sr.state = 'resolved'
      and sr.entity_id = t.normalized_name
  );
  assert missing = 0, 'manual resolutions not fully migrated to stage_reviews';
end $$;
