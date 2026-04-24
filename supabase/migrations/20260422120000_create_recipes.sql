create table recipes (
  id           bigserial primary key,
  source_url   text not null unique,
  site         text not null,
  name         text,
  author       text,
  image_url    text,
  jsonld       jsonb not null,
  fetched_at   timestamptz not null,
  extracted_at timestamptz not null default now()
);

create index recipes_site_idx on recipes (site);
create index recipes_jsonld_gin on recipes using gin (jsonld);

-- RLS: no anon/authenticated read access to the base table.
alter table recipes enable row level security;

-- Public-facing projection: only the columns a website renders.
create view recipes_public as
  select id, source_url, site, name, author, image_url, jsonld
  from recipes;

grant select on recipes_public to anon, authenticated;
