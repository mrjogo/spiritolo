-- Spiritolo schema, SQLite edition. One file replaces the 68 Postgres
-- migrations; the content model is carried over nearly verbatim (see the
-- greenfield design doc), the Supabase-specific layers (auth.users, profiles,
-- RLS, SECURITY DEFINER RPCs, worker_status) are gone, and the run/review/audit
-- logic lives in Python.
--
-- Conventions:
--   * ids are INTEGER PRIMARY KEY (rowid aliases). bigint → integer.
--   * timestamps are ISO-8601 UTC text, default strftime(...'now').
--   * jsonb / text[] → JSON text in a column declared JSONTEXT (TEXT affinity);
--     the declared type is how the API layer knows to parse the value.
--   * booleans are declared BOOLEAN and stored 0/1.
--   * enums become CHECK constraints.

-- ---------------------------------------------------------------- zone 1 pages
create table pages (
    id              integer primary key,
    url             text not null unique,
    site            text not null,
    corpus_key      text,
    content_type    text,
    denylist        boolean not null default 0,
    denylist_reason text,
    fetch_status    text check (fetch_status in ('ok', 'blocked', 'failed')),
    discovered_at   text not null default (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    fetched_at      text
);
create index pages_content_idx on pages (content_type);

-- ------------------------------------------------------------------- taxonomy
create table taxonomy_nodes (
    id                  integer primary key,
    slug                text not null unique check (slug not like '%\_%' escape '\'),
    display_name        text not null,
    node_kind           text check (node_kind in ('brand', 'expression')),
    default_role        text,
    is_cluster_node     boolean not null default 0,
    is_defining_garnish boolean not null default 0,
    status              text not null default 'live' check (status in ('live', 'provisional')),
    created_at          text not null default (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at          text not null default (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
create index taxonomy_nodes_provisional_idx on taxonomy_nodes (status) where status = 'provisional';

create table taxonomy_edges (
    parent_id  integer not null references taxonomy_nodes(id) on delete cascade,
    child_id   integer not null references taxonomy_nodes(id) on delete cascade,
    created_at text not null default (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    primary key (parent_id, child_id),
    check (parent_id <> child_id)
);
create index taxonomy_edges_child_idx on taxonomy_edges (child_id);

create table taxonomy_aliases (
    alias      text not null,
    node_id    integer not null references taxonomy_nodes(id) on delete cascade,
    created_at text not null default (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    primary key (alias, node_id)
);
create index taxonomy_aliases_alias_idx on taxonomy_aliases (alias);

create table taxonomy_provenance (
    node_id        integer primary key references taxonomy_nodes(id) on delete cascade,
    source         text not null check (source in ('seed', 'llm-mapper', 'manual', 'map-mint')),
    mapper_version text,
    raw_string     text,
    prompt_hash    text,
    model_id       text,
    created_at     text not null default (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

create table cocktail_aliases (
    alias          text not null,
    canonical_name text not null,
    source         text not null check (source in ('seed', 'llm', 'manual')),
    created_at     text not null default (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    primary key (alias, canonical_name)
);
create index cocktail_aliases_canonical_idx on cocktail_aliases (canonical_name);

-- -------------------------------------------------------------------- recipes
create table recipe_clusters (
    cluster_key              text primary key,
    canonical_name           text not null,
    ingredient_set           jsontext not null default '[]',
    representative_recipe_id integer,
    recipe_count             integer not null default 0,
    source_count             integer not null default 0,
    version                  text,
    created_at               text not null default (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
create index recipe_clusters_canonical_idx on recipe_clusters (canonical_name);

create table recipes (
    id             integer primary key,
    source_url     text not null unique,
    site           text not null,
    source         jsontext not null default '{}',
    title          text,
    author         text,
    image_url      text,
    equipment      jsontext not null default '[]',
    canonical_name text,
    cluster_id     text references recipe_clusters(cluster_key) deferrable initially deferred,
    variant_key    text,
    recipe_slug    text,
    created_at     text not null default (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at     text not null default (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
create index recipes_site_idx on recipes (site);
create index recipes_cluster_idx on recipes (cluster_id) where cluster_id is not null;
create index recipes_cluster_variant_idx on recipes (cluster_id, variant_key) where cluster_id is not null;
create index recipes_canonical_name_idx on recipes (canonical_name) where canonical_name is not null;
create index recipes_title_idx on recipes (title);

create table recipe_ingredients (
    id         integer primary key,
    recipe_id  integer not null references recipes(id) on delete cascade,
    position   integer not null,
    name       text,
    amount     real,
    amount_max real,
    unit       text,
    modifiers  jsontext not null default '[]',
    raw_text   text not null,
    unique (recipe_id, position)
);
create index recipe_ingredients_recipe_idx on recipe_ingredients (recipe_id);
create index recipe_ingredients_name_idx on recipe_ingredients (lower(trim(name))) where name is not null;

create table recipe_steps (
    id         integer primary key,
    recipe_id  integer not null references recipes(id) on delete cascade,
    step_index integer not null,
    verb       text not null,
    roles      jsontext not null default '{}',
    modifiers  jsontext not null default '[]',
    result     text not null,
    unique (recipe_id, step_index)
);
create index recipe_steps_recipe_idx on recipe_steps (recipe_id);

create table ingredient_resolutions (
    id              integer primary key,
    normalized_name text not null unique,
    taxonomy_slug   text,
    method          text check (method in ('alias', 'lexical', 'llm', 'manual', 'abstain', 'provisional')),
    confidence      real,
    model_id        text,
    version         text,
    created_at      text not null default (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at      text not null default (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
create index ingredient_resolutions_slug_idx on ingredient_resolutions (taxonomy_slug) where taxonomy_slug is not null;

create table recipe_exports (
    id                integer primary key,
    recipe_id         integer not null references recipes(id) on delete cascade,
    recipe_slug       text not null,
    recipe_ref        text not null,
    converter_version text not null,
    bundle            jsontext not null,
    exported_at       text not null default (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    unique (recipe_id, converter_version)
);
create index recipe_exports_slug_idx on recipe_exports (recipe_slug);

-- ----------------------------------------------------------------------- runs
create table jobs (
    id                  integer primary key,
    stage               text not null,
    version             text,
    kind                text not null default 'run' check (kind in ('run', 'reset', 'reconcile')),
    payload             jsontext not null default '{}',
    state               text not null default 'draft'
                        check (state in ('draft', 'queued', 'running', 'cancelling', 'done', 'failed', 'cancelled')),
    llm_provider        text,
    llm_model           text,
    cost_estimate_cents integer,
    cost_actual_cents   integer,
    max_cost_cents      integer,
    progress            jsontext not null default '{}',
    error_code          text,
    error_detail        text,
    worker_id           text,
    last_heartbeat      text,
    created_by          text,
    created_at          text not null default (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    started_at          text,
    finished_at         text
);
create index jobs_queue_idx on jobs (state, created_at);

create table job_items (
    id              integer primary key,
    entity_type     text not null check (entity_type in ('page', 'recipe', 'taxonomy_node')),
    entity_id       integer not null,
    stage           text not null,
    code_version    text not null,
    outcome         text not null check (outcome in ('resolved', 'abstain', 'pending', 'failed', 'proposes_new')),
    method          text not null check (method in ('deterministic', 'llm', 'manual')),
    confidence      real,
    model_id        text,
    cost_cents      real,
    error_code      text,
    job_id          integer references jobs(id) on delete set null,
    payload         jsontext,
    state           text not null default 'pending'
                    check (state in ('pending', 'running', 'applied', 'flagged', 'failed')),
    outcome_payload jsontext,
    started_at      text not null default (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    finished_at     text
);
create unique index job_items_ledger_key on job_items (entity_type, entity_id, stage, code_version) where job_id is null;
create index job_items_job_idx on job_items (job_id) where job_id is not null;
create index job_items_membership_idx on job_items (job_id, stage, state);
create index job_items_queue_idx on job_items (stage, code_version, entity_type);
create index job_items_latest_idx on job_items (stage, entity_id, id desc);

-- -------------------------------------------------------------------- reviews
create table human_reviews (
    id             integer primary key,
    entity_kind    text not null,
    entity_id      text not null,
    stage          text not null,
    state          text not null default 'open' check (state in ('open', 'resolved', 'dismissed')),
    origin         text not null check (origin in ('human_flag', 'machine_proposal', 'distance_gate')),
    payload        jsontext,
    note           text,
    origin_version text,
    created_by     text,
    reviewed_by    text,
    reviewed_at    text,
    created_at     text not null default (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at     text not null default (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
create unique index human_reviews_one_open on human_reviews (entity_kind, entity_id, stage) where state = 'open';
create index human_reviews_queue_idx on human_reviews (stage, state);

-- ---------------------------------------------------------------------- audit
create table audit_log (
    id           integer primary key,
    ts           text not null default (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    table_name   text not null,
    pk           text not null,
    op           text not null check (op in ('I', 'U', 'D')),
    actor_kind   text not null check (actor_kind in ('human', 'worker', 'system')),
    actor_id     text,
    source       text not null,
    before       jsontext,
    after        jsontext,
    changed_keys jsontext,
    job_id       integer
);
create index audit_log_table_pk_idx on audit_log (table_name, pk, ts desc);
create index audit_log_actor_idx on audit_log (actor_kind, ts desc);

-- ----------------------------------------------------------------------- auth
-- Operators log in with a passkey (WebAuthn). No email, no magic link.
create table operators (
    id           integer primary key,
    handle       text not null unique,
    display_name text not null,
    is_admin     boolean not null default 1,
    created_at   text not null default (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    last_login_at text
);

create table passkeys (
    credential_id text primary key,
    operator_id   integer not null references operators(id) on delete cascade,
    public_key    blob not null,
    sign_count    integer not null default 0,
    transports    jsontext not null default '[]',
    aaguid        text,
    label         text,
    created_at    text not null default (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    last_used_at  text
);
create index passkeys_operator_idx on passkeys (operator_id);

-- ---------------------------------------------------------------------- views
create view recipes_public as
select id, source_url, site, title as name, author, image_url,
       source as jsonld, cluster_id, variant_key
from recipes;

create view audit_log_public as
select id, ts, table_name, pk, op, actor_kind, actor_id, source, before, after, changed_keys
from audit_log;

create view needs_review as
select entity_kind, entity_id, stage, origin as reason
from human_reviews where state = 'open';

create view runs as
select j.id, j.stage, j.state, j.llm_provider, j.llm_model,
       coalesce(c.task_count, 0)      as task_count,
       coalesce(c.flagged_count, 0)   as flagged_count,
       coalesce(c.never_run_count, 0) as never_run_count,
       coalesce(c.failed_count, 0)    as failed_count,
       j.cost_estimate_cents, j.max_cost_cents, j.created_at, j.created_by,
       j.cost_actual_cents, j.error_code, j.error_detail, j.worker_id,
       j.last_heartbeat, j.started_at, j.finished_at,
       coalesce(c.items_pending, 0) as items_pending,
       coalesce(c.items_applied, 0) as items_applied,
       coalesce(c.items_flagged, 0) as items_flagged,
       coalesce(c.items_failed, 0)  as items_failed
from jobs j
left join (
    select job_id,
           count(*) as task_count,
           sum(case when outcome_payload ->> '$.why_added' = 'flagged'   then 1 else 0 end) as flagged_count,
           sum(case when outcome_payload ->> '$.why_added' = 'never_run' then 1 else 0 end) as never_run_count,
           sum(case when outcome_payload ->> '$.why_added' = 'failed'    then 1 else 0 end) as failed_count,
           sum(case when state = 'pending' then 1 else 0 end) as items_pending,
           sum(case when state = 'applied' then 1 else 0 end) as items_applied,
           sum(case when state = 'flagged' then 1 else 0 end) as items_flagged,
           sum(case when state = 'failed'  then 1 else 0 end) as items_failed
    from job_items where job_id is not null group by job_id
) c on c.job_id = j.id;

create view taxonomy_public as
select n.id, n.slug, n.display_name, n.node_kind, n.default_role,
       n.is_cluster_node, n.is_defining_garnish,
       coalesce((select json_group_array(parent_id) from
                 (select parent_id from taxonomy_edges where child_id = n.id order by parent_id)), '[]') as parent_ids,
       coalesce((select json_group_array(child_id) from
                 (select child_id from taxonomy_edges where parent_id = n.id order by child_id)), '[]') as child_ids,
       coalesce((select json_group_array(alias) from
                 (select alias from taxonomy_aliases where node_id = n.id order by alias)), '[]') as aliases,
       (select count(distinct ri.recipe_id)
          from ingredient_resolutions ir
          join recipe_ingredients ri on lower(trim(ri.name)) = ir.normalized_name
         where ir.taxonomy_slug = n.slug) as recipe_count
from taxonomy_nodes n
where n.status = 'live';
