-- Provenance for taxonomy_nodes auto-created by the mapper, plus a
-- record for hand-seeded nodes when desired. The audit pass (deferred
-- spec) reads this to flag suspicious LLM creations.
create table taxonomy_provenance (
  node_id        bigint primary key references taxonomy_nodes(id) on delete cascade,
  source         text not null check (source in ('seed', 'llm-mapper', 'manual')),
  mapper_version text,
  raw_string     text,         -- the ingredient string that triggered creation
  prompt_hash    text,
  model_id       text,         -- e.g. 'claude-haiku-4-5' or 'qwen3:14b'
  created_at     timestamptz not null default now()
);

alter table taxonomy_provenance enable row level security;
