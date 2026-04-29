-- E's role tagging on recipe_ingredients. Roles are written by E's cluster
-- compute (which bundles role classification). They share the DEDUP_VERSION
-- lifecycle — role_source records where the assignment came from, but the
-- version stamp lives on the recipe row (recipes.dedup_version) since
-- cluster compute and role tagging always run together.

alter table recipe_ingredients
  add column role         text check (role in (
                            'base_spirit', 'modifier', 'citrus',
                            'sweetener', 'bitters', 'dilution', 'ice',
                            'garnish', 'wash', 'other')),
  add column role_source  text check (role_source in
                            ('default', 'rule', 'manual'));

create index recipe_ingredients_role_idx
  on recipe_ingredients (role) where role is not null;
