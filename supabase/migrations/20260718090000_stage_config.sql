-- stage_config: the metered-vs-free reference table the /ops TriggerBar
-- consults before deciding whether a run needs a CostConfirmModal.
--
-- Deliberately a plain data table, not a hardcoded TS literal — the provider
-- chain behind each stage is owner-rewired config, and whether a stage
-- currently costs money is part of that same config.
-- `metered` and `requires_approval` are stored separately (rather than
-- deriving one from the other) so an operator can require approval on a
-- free stage for policy reasons without that implying a cost estimate, or
-- vice versa, without a schema change.
--
-- Seed reflects the current chain: `fetch` is the one stage that goes
-- through ScraperAPI (a metered HTTP API); every other stage defaults to a
-- free deterministic/local provider chain. Adjust the seed values directly
-- (or via the curation UI, once one exists for this table) as the owner
-- rewires providers — no code change required either way.

create table stage_config (
  stage             text primary key,
  metered           boolean not null default false,
  requires_approval boolean not null default false
);

insert into stage_config (stage, metered, requires_approval) values
  ('discover', false, false),
  ('classify', false, false),
  ('fetch',    true,  true),
  ('extract',  false, false),
  ('parse',    false, false),
  ('map',      false, false),
  ('convert',  false, false),
  ('cluster',  false, false),
  ('export',   false, false);

-- Admin-only read, mirroring the jobs/stage_runs pattern: RLS on, one
-- authenticated+is_admin() policy, explicit grant (anon gets nothing at
-- all — no grant, so it's a permission error rather than an empty result).
alter table stage_config enable row level security;

create policy stage_config_admin_read on stage_config
  for select to authenticated
  using (is_admin());

grant select on stage_config to authenticated;
