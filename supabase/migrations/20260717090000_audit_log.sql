-- Audit log (WS-B26), part 1 of 2: the append-only audit.log table.
--
-- One generic AFTER-trigger (20260717091000_audit_triggers.sql) writes exactly
-- one row here per content mutation, capturing actor (human | worker | system),
-- source, before/after snapshots, and changed_keys. See docs/redesign.md §4.
--
-- We deliberately DO NOT adopt the supa_audit extension. Its fixed
-- record_version schema stores (record, old_record, op, table_oid, record_id,
-- ts) but has no notion of our actor model — the human-vs-worker-vs-system and
-- manual-UI-vs-automated distinctions are the entire point of *our* audit log,
-- and supa_audit can't express them without a bolted-on side channel (an
-- extension dependency PLUS a parallel actor table anyway). The ~40-line custom
-- trigger captures exactly actor + source + diff + time and nothing more.
--
-- Shape choice: we store before + after + changed_keys rather than a full jsonb
-- diff blob. changed_keys answers "what did this edit touch" in one array; the
-- full before->after diff is derivable on read for the rare deep inspection.
-- (YAGNI: no stored full-diff jsonb; no retention/partitioning yet — append-only
-- is fine at current volume.)

create schema if not exists audit;

create table audit.log (
  id           bigserial primary key,
  ts           timestamptz not null default now(),
  table_name   text    not null,
  pk           text    not null,   -- to_jsonb(row)->>'id'
  op           char(1) not null check (op in ('I', 'U', 'D')),

  actor_kind   text    not null check (actor_kind in ('human', 'worker', 'system')),
  actor_id     text,               -- auth.uid()::text | job id | null (system)
  source       text    not null,   -- 'manual-ui-edit' | 'job:<stage>' | 'unknown' | ...

  before       jsonb,              -- null on INSERT
  after        jsonb,              -- null on DELETE
  changed_keys text[]              -- UPDATE only: keys whose value changed
);

create index audit_log_table_pk_idx on audit.log (table_name, pk, ts desc);
create index audit_log_actor_idx    on audit.log (actor_kind, ts desc);

-- Append-only, admin-read-only. The trigger (SECURITY DEFINER, owned by the
-- migration role) and the service-role worker (BYPASSRLS) are the only writers;
-- RLS carries NO insert/update/delete policy, so no client role can forge or
-- mutate history. /ops reads it under the same authenticated + is_admin() tier
-- as jobs / proposals.
alter table audit.log enable row level security;

create policy audit_log_admin_read on audit.log
  for select to authenticated
  using (public.is_admin());

grant usage on schema audit to authenticated, service_role;
grant select on audit.log to authenticated, service_role;
