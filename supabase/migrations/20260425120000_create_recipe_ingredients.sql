create table recipe_ingredients (
  id              bigserial primary key,
  recipe_id       bigint not null references recipes(id) on delete cascade,
  position        int not null,
  raw_text        text not null,
  amount          numeric,
  amount_max      numeric,
  unit            text,
  name            text,
  modifier        text,
  parse_status    text not null check (parse_status in ('parsed', 'unparseable')),
  parser_rule     text,
  parser_version  text not null,
  parsed_at       timestamptz not null default now(),

  unique (recipe_id, position)
);

create index recipe_ingredients_recipe_idx on recipe_ingredients (recipe_id);
create index recipe_ingredients_name_idx   on recipe_ingredients (name) where name is not null;
create index recipe_ingredients_unit_idx   on recipe_ingredients (unit) where unit is not null;

-- RLS off; nothing public reads this table yet.
alter table recipe_ingredients enable row level security;
