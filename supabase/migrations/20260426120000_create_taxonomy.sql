create table taxonomy_nodes (
  id            bigserial primary key,
  slug          text unique not null,
  display_name  text not null,
  role          text check (role in ('brand', 'expression')),
  created_at    timestamptz not null default now()
);

create table taxonomy_edges (
  parent_id  bigint not null references taxonomy_nodes(id) on delete cascade,
  child_id   bigint not null references taxonomy_nodes(id) on delete cascade,
  primary key (parent_id, child_id),
  check (parent_id <> child_id)
);

create index taxonomy_edges_child_idx on taxonomy_edges (child_id);

create table taxonomy_aliases (
  alias    text   not null,
  node_id  bigint not null references taxonomy_nodes(id) on delete cascade,
  primary key (alias, node_id)
);

create index taxonomy_aliases_alias_idx on taxonomy_aliases (alias);

alter table taxonomy_nodes   enable row level security;
alter table taxonomy_edges   enable row level security;
alter table taxonomy_aliases enable row level security;
