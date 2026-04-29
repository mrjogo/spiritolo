-- Persist the LLM's proposed display_name so the review CLI can use it
-- instead of fabricating one from the slug.
alter table taxonomy_proposals add column proposed_display_name text;
