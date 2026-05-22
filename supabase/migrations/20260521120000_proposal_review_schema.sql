-- Schema support for the proposal review UI:
--   1. `recipe_ingredients.flag_reason` — free-text reviewer note for
--      ingredients that need more thought before mapping. Nullable;
--      indexed only on non-null values so the typical query
--      `select distinct flag_reason where flag_reason is not null` is
--      cheap. Free text by design — the frontend auto-suggests prior
--      values; convergence happens naturally.
--   2. Extend `taxonomy_proposals.status` to allow 'flagged' alongside
--      the existing 'pending' / 'approved' / 'rejected'. 'rejected'
--      stays in the constraint so existing rows (if any) remain valid;
--      the UI itself does not emit 'rejected' (Flag replaces it).

alter table public.recipe_ingredients
  add column flag_reason text;

create index recipe_ingredients_flagged_idx
  on public.recipe_ingredients (flag_reason)
  where flag_reason is not null;

alter table public.taxonomy_proposals
  drop constraint taxonomy_proposals_status_check;

alter table public.taxonomy_proposals
  add constraint taxonomy_proposals_status_check
  check (status in ('pending', 'approved', 'rejected', 'flagged'));
