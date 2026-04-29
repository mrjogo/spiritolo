-- Review queue for form-node proposals from Phase 2's LLM. Form nodes
-- (lemon_zest, lime_oil, etc.) require human review before entering the
-- canonical taxonomy. Brands/expressions auto-create silently and do
-- NOT use this table.
create table taxonomy_proposals (
  id                 bigserial primary key,
  raw_string         text not null,
  proposed_slug      text not null,
  proposed_parent_id bigint references taxonomy_nodes(id),
  candidates         jsonb not null,    -- [{node_id, display_name, similarity}]
  mapper_version     text not null,
  status             text not null default 'pending'
                     check (status in ('pending', 'approved', 'rejected')),
  decided_by         text,
  decided_at         timestamptz,
  created_at         timestamptz not null default now(),
  unique (raw_string, mapper_version)
);

create index taxonomy_proposals_status_idx
  on taxonomy_proposals (status, created_at);

alter table taxonomy_proposals enable row level security;
