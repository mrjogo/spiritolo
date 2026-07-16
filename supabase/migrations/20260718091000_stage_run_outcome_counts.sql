-- stage_run_outcome_counts: the one dashboard aggregate the /ops StageCard
-- can compute today — a per-(stage, outcome) run count + summed cost from
-- stage_runs. This is deliberately NOT a content-queue-depth count: that
-- needs "content qualifies AND NOT EXISTS(stage_run @ current version)"
-- joined against the relational content tables (recipe_docs/recipes),
-- which haven't landed yet. The dashboard shows that gap as an explicit
-- placeholder rather than faking a number here.
--
-- security_invoker = true (mirrors recipes_public/taxonomy_public) so the
-- view runs with the CALLER's privileges: the existing admin-only RLS
-- policy on stage_runs applies to the view too, instead of the view
-- owner's broader privileges leaking through. That requires stage_runs
-- to actually grant SELECT to authenticated — a grant the original
-- 20260712_020000_stage_runs.sql migration omitted (its RLS policy was
-- written for `authenticated`, but no GRANT was ever issued, so no
-- authenticated role — not even an admin — could select from it). Added
-- here as an explicit, additive fix rather than editing the old migration.

grant select on stage_runs to authenticated;

create view stage_run_outcome_counts
  with (security_invoker = true)
as
select
  stage,
  outcome,
  count(*)::int                     as run_count,
  coalesce(sum(cost_cents), 0)::numeric as cost_cents
from stage_runs
group by stage, outcome;

grant select on stage_run_outcome_counts to authenticated;
