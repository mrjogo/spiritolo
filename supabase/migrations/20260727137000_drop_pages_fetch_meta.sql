-- Drop the abandoned pages.fetch_meta column. It was added to hold
-- {http_status, rendered, scraperapi_cost_cents, bytes} but no code path ever
-- writes or reads it (verified by grep across python + web); the extract stage
-- reads only content_type + corpus_key. Remove the dead column.
alter table public.pages drop column if exists fetch_meta;
