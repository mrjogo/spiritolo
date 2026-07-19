# Explicit runs: replacing version-derived queues with operator-selected runs

**Status:** design approved (2026-07-18) · **Branch:** `claude/queue-selection-ui`

## Problem

Today "the queue" for a Zone-2 stage is a *derived predicate*: an entity is queued
when it qualifies for the stage AND has no `stage_runs` row at the current version
constant. The worker's stage function re-derives that same predicate when it runs.

Two consequences make the pipeline hard to operate:

1. **You cannot cherry-pick.** The predicate *is* the selection; a run is all-or-
   (site/limit). There is no way to say "re-run exactly these 40 recipes."
2. **Parked residue is invisible.** A deterministic cold-build writes a `stage_runs`
   row (outcome `pending`/`abstain`) for everything an LLM couldn't resolve. Because
   the predicate keys on *row existence*, those parked entities drop out of the queue
   — so wiring up an LLM worker later does nothing until you bump a version constant
   or hand-delete rows. The `/ops` "Run queue" button enqueues a job that then finds
   nothing to do.

The whole version-as-queue-driver apparatus exists to support **automatic re-queue on
version bump** — a feature we are deliberately removing.

## Goal

Make a **run a first-class object the operator assembles explicitly**: create a run,
load it with any set of entities via a rich filtering/selection UI (including already-
processed ones, to force a re-run), then start it. Remove automatic queuing except a
one-click **cold-start** seed when a stage has never run.

## The model

Three processing tables replace the current twelve-ish. Everything else is either a
live/content table (unchanged) or deleted along with the auto-requeue feature.

### `jobs` — the run

The run itself. Extends today's `jobs`:

- `stage` (fixed at create — a run does not mix stages)
- `state`: `draft → queued → claimed → running → done` (+ `failed`). **`awaiting_approval`
  is removed** — the Start confirmation modal is the only cost gate; there is no second
  approval.
- `llm_provider` / `llm_model` — the LLM tier chosen **per run** (see Provider registry).
- `cost_estimate_cents`, `max_cost_cents` (hard cap), `cost_actual_cents`
- `apply_mode`: `auto` | `hold` — the per-run apply-gate toggle
- `created_by`, timestamps

Only in `draft` can tasks be added/removed and the LLM tier chosen. **Membership freezes
at Start.**

### `job_items` — per-entity membership *and* outcome (was `stage_runs`)

One row per `(job, entity)`. It does double duty: **intent when `pending`, outcome when
terminal** — which is the "create → load in a pending state → start" lifecycle.

- `job_id`, `entity_type` (`page`|`recipe`|…), `entity_id`
- `state`: `pending → running → { applied | pending_apply | flagged | failed }`
- `outcome_payload` (jsonb) — for `pending_apply`, the would-be change held pre-apply
- `code_version` — informational stamp of the code version that produced it (NOT a queue
  driver); enables a "processed before v4" filter
- `method` (`deterministic`|`llm`|`manual`), `model_id`, `cost_cents`

`job_items` is **append-only across runs** (each run creates its own rows per entity), so
re-running an entity adds a new row and we get free run history. "Current status of entity
X at stage Y" = its **most recent** `job_item` — this derived view powers the add-page
status facets (the status index).

### `human_reviews` — individual human-attention queue (was `stage_reviews`, folds `taxonomy_proposals`)

Items surfaced for a human to inspect *one at a time* — distinct from the batch run UI and
**not a stage** (individual, interactive, asynchronous; may be human-initiated with no job).

- optional FK to the `job_item` that raised it (machine origin) — or standalone (human flag)
- `state`: `open | resolved | dismissed`, plus the correction payload
- Subsumes the old `taxonomy_proposals` (a `propose_form` becomes a `human_reviews` row
  with a taxonomy payload).

### `audit.log` — unchanged forensic tape, gains a `job_id` back-link

Append-only content-mutation history (actor/source/before/after/changed_keys). It already
encodes the job via `source`/`actor_id`; formalize with a nullable `job_id bigint references
jobs(id)`. The **content diff lives only here** (never duplicated onto `job_items`): a
`pending_apply` change sits in `job_items.outcome_payload` pre-apply, and on Apply the live
write fires the audit row — different lifecycle phases, no overlap.

### Deleted / folded

`job_batches` (no fan-out — one run = one explicit set) · `review_floors` (all `0.0`, dead)
· `stage_live_version` + `stage_queue_versions` (only fed the version predicate) ·
`stage_config` (no longer needed — see Metering) · `taxonomy_proposals` → `human_reviews`.

### Metering

A run is **metered iff its chosen `llm_provider` is a hosted paid API** (`openai`/`claude`/
`deepseek`); the local `ollama` tier is free. This derives from a code constant
(`FREE_PROVIDERS = {"ollama"}`), not a per-stage table — so metering is a property of the
run's selected tier, not of the stage. (The Zone-1 `fetch`/ScraperAPI metering is out of
scope; those stages are untracked by `/ops`.)

## UI

Three surfaces, all mobile-friendly (single 640px breakpoint, table→stacked-cards).

### Runs list + New run

Entry point. Lists runs; **New run** picks a stage (fixed for the run's life). A stage with
**zero `job_items` ever** offers a one-click **"load all eligible"** cold-start seed.

### Run detail

- **LLM-tier selector** (per run) — from the provider registry: `ollama` (free) + configured
  `openai`/`claude`/`deepseek` metered models. Changing it re-estimates cost. (Only relevant
  for stages that have an LLM tier; deterministic-only stages like `cluster`/`export` show it
  disabled or hidden.)
- **Estimate + Start** — Start opens the **confirmation modal** (stage · task count +
  composition · LLM tier · estimated cost · hard cost cap; **no ack checkbox**). Confirm →
  `queued`.
- **Apply-mode toggle** (`auto` | `hold`), set while draft.
- **Tasks table** below with the **same filter/sort/pagination as the add page**. Three modes
  over the run's life: **draft = select→Remove from run**, **running = inspect** (task states
  animate live), **done + `hold` = select→bulk Apply** (filtered to `pending apply`).

### Add tasks

Reached from Run detail's **Add tasks**. Browses the **eligible pool** for the stage.

- **JIRA-style filtering:** each dimension (Status, Source, Code version, Last run, +Add
  filter) is a multi-select dropdown listing **all options with counts**. **Multiple values
  within a dimension = OR** (a task has one status); **different dimensions = AND**. Active
  filters render as removable **pills** joined by explicit `AND`, with **Clear filters**.
- **Sorting** via a Sort control and clickable column headers.
- **Selection persists across filter changes** — banner: "N selected — kept as you change
  filters", with **Select all N matching**, **View selection**, and **Clear all selected**.
- **Add N to run → back to Run #.** Loading = inserting `pending` `job_items` under the
  draft job.

## Flow (state machines)

**Run:** `draft → (Start ▸ confirm) → queued → claimed → running → done` (`failed` on fatal
error). Membership freezes at Start.

**Task:** `pending → running → { applied | pending_apply | flagged | failed }`.
- confident + `apply_mode=auto` → `applied` (writes live tables + audit.log)
- confident + `apply_mode=hold` → `pending_apply` → (bulk **Apply**) → `applied`
- uncertain → `flagged` (raises a `human_reviews` row)
- fatal → `failed` (re-runnable)

**Re-run:** membership is frozen, so re-run **seeds a new draft** — "Re-run failed" /
"Re-run flagged" from a finished run pre-loads exactly those entities (keep or change the
LLM tier). Ad hoc: select already-`applied` entities on the add page to force reprocessing.

## Delivery

**One PR** delivers the whole redesign. The four areas below are the internal build order,
not separate PRs:

1. **Schema + worker core** — new `jobs` columns + `draft` state (drop `awaiting_approval`),
   `stage_runs`→`job_items` (rename + `state`/`outcome_payload`/membership), `audit.log.job_id`;
   worker reads the job's explicit `job_items` instead of the version predicate; drop the folded
   tables.
2. **Run detail UI** — runs list, New run, detail view (LLM selector, start-confirm, tasks
   table with the three modes).
3. **Add-tasks UI** — eligible-pool browse, JIRA filtering, sort, persistent selection,
   select-all-matching.
4. **Apply gate + human_reviews** — `apply_mode`, bulk Apply, fold `taxonomy_proposals` and
   port the existing reviews UI to `human_reviews`.

## Data migration

**There are no existing `jobs`/runs to preserve** — only cold-build output. The migration must
carry that output into the new tables so the status facets are populated from day one:

- **`stage_runs` → `job_items`.** `job_items` requires a `job_id`, so create **one synthetic
  backfill `jobs` row per stage** (`state='done'`, `method='deterministic'`, a clear
  `created_by=system` marker) and attach the migrated rows to it. Map outcomes to task states:
  `resolved → applied` (content was written to live), `failed → failed`, and
  `pending`/`abstain`/`proposes_new → flagged` (parked — no content written, needs an LLM/human
  pass). Carry the old `version` → `job_items.code_version`. Result: the add-page status facets
  immediately show what the cold build did, and every parked item is selectable into a first
  real (LLM) run — the exact workflow that motivated this redesign.
- **`stage_reviews` → `human_reviews`** — preserve state/payload/origin.
- **`taxonomy_proposals` → `human_reviews`** — `pending→open`, `approved→resolved`,
  `rejected→dismissed`, taxonomy candidate list into the payload.
- Drop the folded tables only after their data is migrated, in the same migration.
- Going forward, cold-start data enters runs via the **"load all eligible"** seed on a stage
  with no `job_items` — but after this backfill, stages already have `job_items`, so the normal
  add-tasks flow applies.

## Non-goals

- The LLM provider wiring itself (already merged, #102) — this consumes the registry, doesn't
  change it.
- Any change to the Zone-1 SQLite scraper stages (discover/classify/fetch) — they remain
  untracked by `/ops`.
- A filter *query language* — powerful UI filtering only.

## Decisions locked (2026-07-18)

1. Run object = extended `jobs` with a `draft` state; `stage_runs` becomes `job_items`
   (membership + outcome); `human_reviews` replaces `stage_reviews`.
2. Per-entity table name is `job_items` (neutral across the pending→terminal lifecycle).
3. `audit.log` gains a nullable `job_id` FK column (not a join table — the relation is 0..1).
4. Single cost gate: the Start confirmation modal. **No `awaiting_approval`, no second approval.**
5. Membership freezes at Start; add/remove is draft-only, running/done is inspect/apply.
6. Apply gate is a per-run `apply_mode` toggle (`auto`|`hold`); Apply is bulk from run detail.
7. Re-run = a new draft seeded from a prior run's failed/flagged subset.
8. Filtering: multi-select OR within a dimension, AND across dimensions; sortable; selection
   survives filter changes.
