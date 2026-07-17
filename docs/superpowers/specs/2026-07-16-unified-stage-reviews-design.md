# Unified stage reviews: one human-in-the-loop layer for every pipeline stage

Every Zone-2 stage already shares one machine substrate — the `stage_runs`
ledger ([supabase/migrations/20260712_020000_stage_runs.sql](../../../supabase/migrations/20260712_020000_stage_runs.sql))
— keyed `(entity_type, entity_id, stage)` with a standardized `outcome` enum,
`method`, `confidence`, and a `payload` jsonb. The ops UI already shares one
substrate too: parallel browsers over `OpsLayout` + a reusable `StageCard`
([web/src/pages/ops/](../../../web/src/pages/ops)).

What is **not** shared is the human-review layer. Three bespoke mechanisms do
the same job in three different shapes:

- `taxonomy_proposals` — the map stage's form-node review queue
  ([supabase/migrations/20260429140200_create_taxonomy_proposals.sql](../../../supabase/migrations/20260429140200_create_taxonomy_proposals.sql)).
- `recipegf_proposals` — the convert stage's proposal queue
  ([supabase/migrations/20260711120000_recipegf_export.sql](../../../supabase/migrations/20260711120000_recipegf_export.sql)).
- `ingredient_resolutions.method='manual'` (+ null-slug abstain) — the map
  stage's human override, which is **silently clobbered** on every rerun by
  `write_resolution`'s unconditional `on conflict … do update`
  ([ingredients/src/ingredients/mapping/resolutions.py](../../../ingredients/src/ingredients/mapping/resolutions.py)).

These are the same record wearing three costumes. This spec consolidates them
into **one** `stage_reviews` table — flag, proposal, and override are one row
distinguished by `state`/`origin` — deletes the two proposal tables, and makes
human input survive reruns. It also adopts the append-versioned ledger shape
that a future shadow-diff eval workflow needs, without building that UI yet.

The acceptance test for each consolidation step: **did we delete a bespoke
mechanism?**

## Goals

- One `stage_reviews` table subsuming flags, machine proposals, and human
  overrides for **every** stage — present and future.
- Human input (overrides, flags) lives in a table the stage_fn never writes,
  so a rerun or version bump **cannot** clobber it ("pin survives rerun").
- Flag anything, at any stage, from **both** the ops console and the
  public-facing recipe site (curator-only), pinpointing the specific entity.
- `needs_review` is a **derived** view, not a stored state or new enum value.
- Append-versioned `stage_runs` + a live-version pointer + a decision-in-payload
  contract — the data shape a shadow-diff eval consumes — laid down now.
- A thin, uniform per-stage seam: a stage joins the whole system by writing one
  `apply()`, one renderer, and one registry line.
- Migrate all existing rows into the new model without loss; delete the two
  proposal tables. One branch/PR.

## Non-goals (deferred or out of scope)

- **Shadow-diff eval UI** — the diff view, promote/rollback controls, and true
  shadow runs (compute a version without it going live). We build the data
  model they consume; the UI is a follow-up spec.
- **Anonymous / crowd flagging.** Public-site flags are curator-only (reuse the
  existing magic-link + `is_admin()` auth). Anonymous writes, rate limiting, and
  moderation are a later product decision.
- **Vector/embedding retrieval.** Distance-gated flagging uses the existing
  `pg_trgm` similarity; embeddings are a later optimization.
- **The taxonomy graph editor** (`web/src/components/taxonomy/` — parents,
  aliases, create-child) stays its own richer surface. Node *mapping*
  corrections flow through reviews; node *connection* editing does not.
- **`audit.log`** stays as-is — it is an append-only audit trail, a different
  concern from a review queue.
- **Versioning the content tables.** `recipe_ingredients`, `recipe_steps`, etc.
  stay single, live-version rows; version history is ledger-carried.

## Architecture

### Data model

**`stage_reviews`** — the un-clobbered human/proposal layer:

```sql
create table stage_reviews (
  id             bigserial primary key,
  entity_kind    text not null,   -- recipe_ingredient | ingredient_name | recipe_step | recipe | cluster | page
  entity_id      text not null,   -- text: holds bigint ids AND name-keys (ingredient_name = normalized name)
  stage          text not null,   -- extract|parse|map|convert|cluster|export
  state          text not null default 'open'
                 check (state in ('open','resolved','dismissed')),
  origin         text not null
                 check (origin in ('human_flag','machine_proposal','distance_gate')),
  payload        jsonb,           -- suggested-or-confirmed correction + machine context (candidates, reason)
  note           text,            -- optional free-text "what's wrong"
  origin_version text,            -- stage version that produced a machine proposal; null for human rows
  created_by     text,            -- auth.uid() (human) | job id | null
  reviewed_by    text,
  reviewed_at    timestamptz,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

-- At most ONE active review per (entity, stage); resolved/dismissed rows accumulate as history.
create unique index stage_reviews_one_open
  on stage_reviews (entity_kind, entity_id, stage) where state = 'open';

create index stage_reviews_queue_idx on stage_reviews (stage, state);
```

- `entity_id` is `text` so one table holds both numeric ids and map's
  name-keys.
- The partial unique index enforces one *open* item per `(entity, stage)` while
  keeping resolved/dismissed rows as a trail.
- Overrides carry **no** version — a resolved override is version-independent,
  which is exactly why it survives bumps. `origin_version` only stamps machine
  proposals (preserving the old `mapper_version` / `converter_version`).
- Gets the existing audit trigger attached
  ([supabase/migrations/20260717091000_audit_triggers.sql](../../../supabase/migrations/20260717091000_audit_triggers.sql)),
  RLS with an `is_admin()` read/write policy like `stage_runs`.

**`stage_runs` → append-versioned.** History is kept instead of overwritten:

```sql
-- was: unique (entity_type, entity_id, stage)          -- latest-only, destroyed history
   now: unique (entity_type, entity_id, stage, version) -- one row per version, history preserved
```

The queue predicate ("no row at current version") and the `(stage, version,
entity_type)` index are unchanged. Every stage writes its **decision** into
`payload` (the contract that enables a future cross-version diff).

**`stage_live_version`** — per-stage live pointer:

```sql
create table stage_live_version (stage text primary key, version text not null);
```

"Live" defaults to the latest run (observable behavior unchanged today); the
pointer exists so the deferred promote/rollback can flip it. Readers of
`stage_runs` that assumed one row per `(entity, stage)` now filter to the live
version (or `max(version)`).

### Lifecycle & the derived review queue

State machine (one open row per `(entity, stage)`; history accumulates):

```
          curator sets a correction / approves a proposal
  open ─────────────────────────────────────────────────▶ resolved   (override, pinned)
    │     curator says "not actually wrong" / rejects
    └─────────────────────────────────────────────────────▶ dismissed
```

A later re-flag opens a *new* row. To change a resolved override, set a new one;
it supersedes.

Three origins = three curator affordances (what `ReviewCard` branches on):

- `human_flag` — curator marked it wrong. Card shows current output + note;
  actions: fix (→resolved) / dismiss.
- `machine_proposal` — the stage had a candidate but wanted sign-off (migrated
  `taxonomy_proposals` / `recipegf_proposals`). Card shows candidate + context;
  actions: approve (→resolved) / reject (→dismissed).
- `distance_gate` — nothing was close enough (the mint signal). Card shows the
  weak candidates; actions: mint/map manually (→resolved) / dismiss.

**`needs_review` is a derived view** — the one uniform queue, identical for
every stage:

```sql
create view needs_review as
  select … from stage_runs where outcome in ('abstain','proposes_new')
  union
  select … from stage_reviews where state = 'open'
  union
  select … from stage_runs sr where sr.confidence < floor_for(sr.stage);
```

No new enum value, no stored `needs_review` column — bump a floor or open a
review and the queue updates itself. The `floor_for(stage)` function returns a
per-stage confidence floor (the distance-gate's soft tier); floors are a small
config table or a constant map, tuned empirically.

### Per-stage seam

Everything above is built **once** and shared. A stage plugs in via a thin
adapter — the only stage-specific code.

Backend contract (one per stage, registered by stage name like the existing
`STAGE_FNS` dispatch):

```python
class StageReviewAdapter:
    entity_kind: str                        # what this stage's reviews point at
    def load_context(entity_id) -> dict     # current live output + machine context, for the card
    def apply(review) -> None               # write the CONFIRMED correction into this stage's live output table
```

`apply()` is the single stage-specific write:

| Stage   | `entity_kind`       | `apply(review)` writes into…                          |
|---------|---------------------|-------------------------------------------------------|
| extract | `recipe`            | `recipes` header fields from `payload`                |
| parse   | `recipe_ingredient` | that row's `amount/unit/name/modifiers`               |
| map     | `ingredient_name`   | `ingredient_resolutions[name] = payload.slug, method='manual'` |
| convert | `recipe_step`       | replace the recipe's `recipe_steps` from `payload`    |
| cluster | `recipe`            | `recipes.cluster_id/variant_key` or corrected `canonical_name` |

`apply()` is called from exactly two places, one code path: (1) when a curator
resolves a review — immediate materialization; (2) after each stage run, for
every resolved review on the touched entities — the pin re-apply.

**The map payoff is free:** a map review's entity is the *name*, so `apply()`
writes the shared `ingredient_resolutions` row — one override re-points every
recipe using that name. Fine-grained-per-stage entity makes shared corrections
shared and row corrections local, with no special-casing.

Frontend mirror: a per-stage payload renderer (`MapReviewBody`,
`ParseReviewBody`, …) registered by stage, dropped into the shared `ReviewCard`.
The shell (state buttons, note, who/when) is uniform; only the body varies.

### Versioning mechanics (built now vs deferred)

A stage run now does:

```
compute answer ─▶ write to live output table ─▶ INSERT stage_runs (entity,stage,VERSION)  ← prior versions KEPT
                                                 with the decision in payload
              ─▶ apply() overlays resolved overrides for touched entities
```

The only change from today is the middle step: the ledger row is appended, not
overwritten. `stage_live_version` defaults to latest, so live-output behavior is
unchanged (newest wins, immediately live).

| Built now (data model)                                   | Deferred (eval UI)                          |
|----------------------------------------------------------|---------------------------------------------|
| append-versioned `stage_runs` (history retained)         | diff view (compare vN vs vN-1 payloads)     |
| decision-in-`payload` contract per stage                 | promote/rollback (flip pointer + re-materialize) |
| `stage_live_version` pointer (defaults to latest)        | true *shadow* runs (compute vN without live)|
| overrides survive bumps (via `stage_reviews` + re-apply) | —                                           |

Two consequences handled in this PR:

1. **Readers of `stage_runs` pick a version** — anything assuming one row per
   `(entity, stage)` (e.g. `StageRunsBrowser`) filters to `stage_live_version`
   (or `max(version)`). Content-table readers (app/public site) are unaffected.
2. **Stale machine proposals get superseded** — when a newer version
   auto-resolves an entity, any *open* `machine_proposal`/`distance_gate` review
   for that `(entity, stage)` is auto-dismissed as `superseded`, never touching
   `human_flag`s or resolved overrides. This fixes today's `taxonomy_proposals`
   wart (keyed `raw_string+mapper_version`, so every bump re-piles).

Old ledger versions are prunable exactly like today's `*_runs` tables.

### Pin-survives-rerun

The pin is a re-apply, not a lock. The durable truth is the `stage_reviews` row
(the stage_fn never touches it); on every run the live output table gets the
human value re-stamped after the auto compute. A version bump recomputes freely
and the fix always wins the live row.

### UI

- **Ops console:** a shared `ReviewCard` embedded in the ops browsers, driven by
  the `needs_review` view. Per-stage body renderers by stage name. A flag button
  on every browser row.
- **Public recipe site:** a flag affordance on rendered recipe elements
  (ingredient line, step, title, cluster name), rendered **only** when
  `useIsAdmin()` is true ([web/src/auth/useIsAdmin.ts](../../../web/src/auth/useIsAdmin.ts)).
  Writes go through the `flag_review()` RPC, gated by `is_admin()`. No anonymous
  path.
- **Not unified:** the taxonomy graph editor stays separate.

## Data flow

**Flag (from either surface):** curator clicks flag on a rendered entity →
`flag_review(entity_kind, entity_id, stage, note)` RPC (is_admin-gated) →
inserts a `stage_reviews` row `(state=open, origin=human_flag)` → appears in
`needs_review`.

**Resolve:** curator opens the `ReviewCard` for a `needs_review` item → edits
via the per-stage body → `resolve_review(id, payload)` RPC sets
`state=resolved`, stamps `reviewed_by/at`, and calls the stage adapter's
`apply()` to materialize into the live output table.

**Rerun:** stage_fn computes auto answers → writes live output + appends a
`stage_runs` row at the current version → the re-apply loop overlays every
resolved override for the touched entities → open machine proposals for
now-resolved entities are superseded.

## Migration & cutover

One backfill, three sources → `stage_reviews` (in the migration SQL):

| Source row | → `stage_reviews` |
|---|---|
| `taxonomy_proposals` | `stage=map, entity_kind=ingredient_name, entity_id=raw_string, origin=machine_proposal, origin_version=mapper_version, payload={proposed_slug, proposed_parent_id, proposed_display_name, candidates}` |
| `recipegf_proposals` | `stage=convert†, entity_kind=cluster, entity_id=cluster_id, origin=machine_proposal, origin_version=converter_version, payload={proposed_slug, reason, detail, source_url}` |
| `ingredient_resolutions` where `method='manual'` | `stage=map, entity_kind=ingredient_name, entity_id=normalized_name, state=resolved, origin=human_flag, payload={slug: taxonomy_slug}` |

State maps: `pending→open`, `approved/resolved→resolved`, `rejected→dismissed`;
`decided_by/at → reviewed_by/at`; `created_at` preserved. († the exact stage —
`convert` vs `export` — is pinned at implementation by checking which stage
writes `recipegf_proposals`; the mapping is identical either way.)

Not lost:

- `ingredient_resolutions` is **not** dropped — it stays the live shared
  resolution. Each `method='manual'` row is *backed* by a durable override so it
  survives reruns; live rows are untouched.
- Null-slug abstains are **not** migrated — they are machine abstains, already
  surfaced by `needs_review` via the map adapter. No rows lost.

Cutover — atomic, one PR, no dual-write:

```
1. schema:   create stage_reviews + stage_live_version + alter stage_runs unique(+version) + needs_review view
2. backfill: INSERT stage_reviews SELECT … from the three sources
3. verify:   in-migration assert (migrated count == source count) — abort on mismatch
4. code:     map/convert write unified reviews; apply() hooks; re-apply loop; needs_review reads; flag_review/resolve_review RPCs
5. drop:     taxonomy_proposals, recipegf_proposals   (ingredient_resolutions kept)
```

No dual-write window is needed: the migrations workflow and Vercel both deploy
on the same push to `staging`. The Supabase backup (taken before the run) is the
rollback. Optionally step 5 renames tables to `*_deprecated` instead of dropping;
default is the clean drop.

## Error handling

- `flag_review` / `resolve_review` RPCs are `security definer`, `is_admin()`-gated;
  non-admin callers get permission denied (same pattern as the curation RPCs).
- `apply()` runs inside the resolve transaction; a failing `apply()` rolls back
  the state change so a review never shows resolved without its correction
  landing.
- The re-apply loop is idempotent (re-stamping the same override value is a
  no-op) and tolerant: one entity's `apply()` failure is logged and skipped, not
  fatal to the stage run.
- Backfill aborts (whole migration transaction) on any count mismatch.

## Testing

Highest-value tests prove **nothing was lost** and the **new guarantees hold**.
Surfaces: pytest DB-integration against `TEST_DB_URL`; Vitest for web; frozen
eval sets. TDD — items 1–4 are written failing first.

1. **Migration parity** — seed the three sources, run the migration, assert
   every row lands with correct `state/origin/payload/origin_version`; assert old
   tables gone and `ingredient_resolutions` live rows untouched.
2. **Queue behavior-preservation** — `needs_review` surfaces exactly the union
   the three old mechanisms did (modulo the new low-confidence tier).
3. **Pin-survives-rerun** — set an override; rerun same version and bumped
   version; assert the live output still shows the override, for `map`
   (the clobber bug), `parse`, `cluster`.
4. **Append-versioned + supersede** — run v1, bump v2, rerun; both ledger rows
   exist, `stage_live_version→v2`; an open `machine_proposal` from v1 is
   auto-dismissed `superseded`, a `human_flag`/override is not.
5. **Adapter conformance** — parametrized across all five adapters:
   `entity_kind` declared, `load_context()` returns for a known entity, `apply()`
   writes the live table idempotently.
6. **`flag_review` RPC + RLS** — admin writes; anon/non-admin rejected.
7. **Frontend (Vitest + RTL)** — `ReviewCard` renders the correct per-stage body;
   buttons call the RPC; the public flag affordance renders only when
   `useIsAdmin()`.
8. **Eval-set no-drift** — frozen map/parse/cluster eval sets pass unchanged
   (storage/review changed, resolution logic did not).

## Files touched

New:

- `supabase/migrations/<ts>_stage_reviews.sql` — `stage_reviews`,
  `stage_live_version`, `stage_runs` unique change, `needs_review` view,
  `floor_for`, backfill + verify + drops, RLS + audit trigger, `flag_review` /
  `resolve_review` RPCs.
- `ingredients/src/ingredients/reviews/` — the shared review model: table access,
  the re-apply overlay loop, the adapter registry + the five `StageReviewAdapter`
  implementations.
- `web/src/components/reviews/ReviewCard.tsx` + per-stage body renderers.
- `web/src/pages/ops/ReviewsBrowser.tsx` (or fold into existing browsers).
- Test modules alongside each of the above.

Modified:

- `ingredients/src/ingredients/mapping/resolutions.py` — manual rows backed by
  overrides; stop clobbering.
- `ingredients/src/ingredients/mapping/proposals.py` + map stage — write unified
  reviews instead of `taxonomy_proposals`.
- The convert stage — write unified reviews instead of `recipegf_proposals`.
- `ingredients/src/ingredients/pipeline/stages/base.py` — append-versioned
  ledger writes; live-version pointer; re-apply hook invocation.
- `web/src/pages/ops/StageRunsBrowser.tsx` — filter to live version.
- Public recipe views — flag affordance (admin-only).

Deleted:

- `taxonomy_proposals`, `recipegf_proposals` (tables + their bespoke code paths).

## Open questions

- **`recipegf_proposals` stage attribution** — `convert` vs `export`; pinned at
  implementation from the writer. Does not affect the migration mapping.
- **Confidence floors** — initial `floor_for(stage)` values are placeholders; a
  follow-up sizes them from the real distribution of best-candidate similarity.
  Starting conservative (flag more) is safe because the queue is curator-gated.
