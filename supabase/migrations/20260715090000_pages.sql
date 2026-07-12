-- WS-B20: relocate the scraper's `pages` work-queue table from SQLite
-- (scraper/src/scraper/db.py) into the one Postgres. This is one of the two
-- preserved clean-slate inputs for the v2.1 rebuild (docs/redesign.md §9.1.4)
-- — the other being the R2 HTML corpus, keyed sha256(url) and populated by
-- scripts/src/corpus_loader.
--
-- `pages` stays deliberately lightweight: the HTML bytes never live here (R2
-- holds those, read-only, keyed by `r2_key`). The legacy SQLite table's
-- per-field snapshot columns (`pages_status_before`, ...) and its
-- `attempts`/`fetch_error` bookkeeping are gone on purpose — that history now
-- lives in `stage_runs.payload` / `audit_log` (foundation tables from other
-- workstreams), not on the row itself.
--
-- RLS: enabled with zero policies and no grants to anon/authenticated — the
-- same deny-all convention used by taxonomy_proposals / recipegf_recipes.
-- Only the table owner and service_role (BYPASSRLS) can read/write directly;
-- there is no RPC surface for `pages` in this workstream.
create table pages (
  id              bigserial primary key,
  url             text not null unique,
  site            text not null,
  r2_key          text,                     -- sha256(url); null until fetched
  content_type    text,                      -- classify stage output label
  denylist        boolean not null default false,
  denylist_reason text,
  fetch_status    text check (fetch_status in ('ok', 'blocked', 'failed')),
  fetch_meta      jsonb,                     -- {http_status, rendered, scraperapi_cost_cents, bytes}
  discovered_at   timestamptz not null default now(),
  fetched_at      timestamptz
);

create index pages_site_idx     on pages (site);
create index pages_content_idx  on pages (content_type);
create index pages_denylist_idx on pages (denylist) where denylist;

alter table pages enable row level security;
