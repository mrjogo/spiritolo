-- Lock in the snake→kebab transition. The one-time data cleanup
-- (replacing underscores with dashes in taxonomy_nodes.slug and
-- taxonomy_proposals.proposed_slug, plus merging the 23 snake/kebab
-- duplicates that existed in pairs) ran manually against local and was
-- uploaded to staging — see PR notes.
--
-- The constraint is narrow on purpose: it only forbids the word
-- separator we just removed (`_`). Pre-existing slugs include accented
-- characters, apostrophes, periods, and parentheses that are out of
-- scope for this change; a future migration can tighten further once
-- those are cleaned up.

alter table public.taxonomy_nodes
  add constraint taxonomy_nodes_slug_no_underscore
  check (slug !~ '_');

alter table public.taxonomy_proposals
  add constraint taxonomy_proposals_proposed_slug_no_underscore
  check (proposed_slug !~ '_');
