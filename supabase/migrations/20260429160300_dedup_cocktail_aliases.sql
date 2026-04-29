-- Cocktail alias table — exact analogue of taxonomy_aliases. Used by
-- E's Phase-1 alias-layer lookups; grown by Phase-2 LLM resolutions.

create table cocktail_aliases (
  alias          text not null,
  canonical_name text not null,
  source         text not null check (source in ('seed', 'llm', 'manual')),
  created_at     timestamptz not null default now(),
  primary key (alias, canonical_name)
);

create index cocktail_aliases_canonical_idx
  on cocktail_aliases (canonical_name);
