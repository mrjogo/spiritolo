# Taxonomy harmonization + stage rename + apply teardown — design

**Date:** 2026-07-19
**Branch:** `claude/taxonomy-harmonization`
**Status:** approved design, ready for planning

## Summary

Three intertwined changes to the Zone-2 content pipeline, shipped in one PR as
separable phases:

1. **Tear out the apply/hold feature.** It gates nothing — every stage already
   writes to the live tables during processing, so `apply` is a no-op state
   flip. Remove `apply_mode` / `pending_apply` / `apply_run_items` end to end;
   application is always immediate. The audit log stays as the rollback
   substrate; **rollback itself is not built** (deferred).
2. **Rename the stages** to canonical `<verb>-<object>` names everywhere in the
   UI, docs, and everywhere we refer to them (code renames where cheap).
3. **Split taxonomy node creation into a naive-create-then-harmonize pipeline.**
   `map-ingredient` stops making structural decisions inline: it resolves a name
   to an existing live node, or — on abstain — *mechanically mints a provisional
   node*. Two new stages then harmonize: **`combine-nodes`** (dedup/merge,
   preferring existing live nodes as the survivor) and **`connect-nodes`**
   (assign `node_kind` + parent edges + `is_cluster_node`, then promote
   `provisional → live`). A `status` flag on `taxonomy_nodes` keeps un-harmonized
   nodes out of downstream stages.

## Motivation

- The apply/hold machinery implies a gate that does not exist. Reading
  `apply_run_items` (`run_rpcs.sql:405-412`): content is written to live tables
  during processing; "apply" is the state flip itself, with no deferred write to
  replay. It is dead weight that confuses the mental model.
- Stage verbs (`extract`, `map`, `convert`, …) each act on and produce a
  *different* object, so the bare verb is ambiguous. `<verb>-<object>` names
  disambiguate.
- `map-ingredient` today overloads one LLM call to classify + place + dedup a
  name inline, and the result is **order-dependent** (whether "Angostura"
  resolves right depends on whether its node exists yet when the name is seen).
  Splitting into liberal-create then whole-set harmonization removes the
  ordering dependence, isolates the expensive judgment, and mirrors the proven
  `cluster-recipes` pattern (content-address, then collapse duplicates).

## Non-goals

- **Rollback / revert of a run.** The audit log already captures before+after
  images per row tagged with the job id (`audit_triggers.sql:26-44`), so revert
  is buildable later by replaying `before` images. Not in scope now.
- **A separate provisional/staging table.** Provisional state is a `status`
  column on `taxonomy_nodes`, not a new table (see Decisions).
- **Changing what the public recipe page renders.** `recipes_public` still
  serves header + raw JSON-LD + cluster grouping; it only gains a
  `status = 'live'` taxonomy gate where it reads taxonomy.
- **Convert's "new verb" case.** A missing technique/verb is a YAML/code change,
  not a DB row; unchanged here.

## Decisions

- **Apply is immediate; no hold.** `item_state` collapses to
  `resolved→applied`, `failed→failed`, parked→`flagged`. No `pending_apply`.
- **Canonical stage names:** `extract-recipe`, `parse-ingredients`,
  `map-ingredient`, `convert-steps`, `cluster-recipes`, `export-recipegf`, plus
  new `combine-nodes`, `connect-nodes`.
- **`create-nodes` is folded into `map-ingredient`,** not a separate stage. On
  abstain, map mints a provisional node in its deterministic tier. Rationale:
  the mint is mechanical (name → deterministic kebab slug → insert-on-conflict);
  a separate stage buys nothing since it does no matching (map already tried).
- **Provisional nodes via `taxonomy_nodes.status`** (`'live'` default,
  `'provisional'`), not a staging table. Edges and resolutions point at
  provisional nodes natively, so promotion is a cheap, auditable flag flip
  rather than a cross-table row move.
- **Downstream gate:** `cluster-recipes`, `export-recipegf`, and the taxonomy
  reads in `recipes_public` / `taxonomy_public` filter to `status = 'live'`.
- **combine/connect prefer existing live nodes** as the blessed survivor /
  attachment target over provisional ones.
- **combine/connect can run broadly** — a run may target the existing live set,
  not just the newest provisional residue, to harmonize pre-existing taxonomy.
- **New entity kind `taxonomy_node`** in the runs/`job_items` model
  (map's entity stays `ingredient_name`; combine/connect operate on nodes).

## Architecture

### Stage order

```
extract-recipe → parse-ingredients → map-ingredient → combine-nodes → connect-nodes
                                                        └─ taxonomy sub-pipeline ─┘
                                              ↓ (recipes whose nodes are all live)
                                    convert-steps → cluster-recipes → export-recipegf
```

`map-ingredient` emits provisional nodes; `combine-nodes` + `connect-nodes`
harmonize and promote them to `live`; only then are a recipe's ingredients fully
`live`, making it eligible for `convert-steps` / `cluster-recipes` /
`export-recipegf`. A recipe with any provisional-node ingredient is "partially
through the pipeline" and is filtered out of the downstream stages until
`connect-nodes` promotes.

### The three taxonomy stages

**`map-ingredient`** (was `map`) — *resolve to existing, else mint provisional.*
- Deterministic tier: alias → lexical match against **live** nodes. On hit,
  write the shared `ingredient_resolutions` row (name → live slug).
- LLM tier (optional): fuzzy-attach a name to an existing **live** node.
- On abstain (no live match): **mechanically mint** a provisional node —
  deterministic kebab slug from the normalized name,
  `insert into taxonomy_nodes (slug, display_name, status, node_kind)
  values (…, 'provisional', NULL) on conflict (slug) do nothing`, write the
  provisional resolution + `taxonomy_provenance`. Identical names collapse via
  the deterministic slug; synonyms are left for `combine-nodes`.
- **Removed:** the old inline `propose_brand` / `propose_expression`
  auto-create and the `propose_form` human-proposal path. All new nodes now
  flow through mint → combine → connect.

**`combine-nodes`** (new) — *dedup/merge; entity kind `taxonomy_node`.*
- Candidate set: provisional nodes (default), or the broader live set when run
  broadly.
- Judgment (LLM/embedding tier): "is node X the same substance as node Y?"
  Uncertain merges open a `human_reviews` **combine** review (curator confirms).
- Merge action: pick the **blessed survivor preferring an existing live node**;
  repoint every `ingredient_resolutions.taxonomy_slug` and `taxonomy_edges`
  reference from the absorbed node to the survivor; delete/tombstone the
  absorbed provisional node.
- Outcome recorded per node in `job_items` at `COMBINE_VERSION`.

**`connect-nodes`** (new) — *place + promote; entity kind `taxonomy_node`.*
- Operates on surviving provisional nodes (default) or broadly on live nodes.
- Judgment (LLM + human): assign `node_kind`, parent `taxonomy_edges`, and
  `is_cluster_node` (respecting the antichain invariant — no `is_cluster_node`
  ancestor). The curator-sensitive calls open a `human_reviews` **connect**
  review.
- Promotion: once a node has `node_kind` + ≥1 parent edge and its placement is
  accepted, flip `status` `provisional → live`. This promotion is the taxonomy
  analogue of the (now-deleted) generic "apply".
- Outcome recorded per node in `job_items` at `CONNECT_VERSION`.

### Schema changes

- `taxonomy_nodes.status text not null default 'live' check (status in ('live','provisional'))`
  + index on `status` for the downstream gate + facets.
- New version constants: `COMBINE_VERSION`, `CONNECT_VERSION` (module-level, in
  new stage files under `pipeline/stages/`).
- `human_reviews`: no schema change; two new `stage` values (`combine-nodes`,
  `connect-nodes`) and their `machine_proposal` payload shapes. (`origin` and
  `state` domains are unchanged.)
- Downstream gate: add `status = 'live'` (or `n.status = 'live'`) predicates to
  the taxonomy joins in `cluster-recipes`, `export-recipegf` bundle generation,
  and `recipes_public` / `taxonomy_public`.
- **Removed schema:** `jobs.apply_mode`, the `pending_apply` value in the
  `job_items.state` CHECK, `apply_run_items()`, the hold branch of `create_run`.

### Apply teardown surface

- SQL: `20260726090000_explicit_runs.sql` (state CHECK, apply_mode column),
  `20260726093000_run_rpcs.sql` (`create_run` apply_mode arg,
  `apply_run_items`). Handled via a **new forward migration** that drops the
  column/function and rewrites the `job_items.state` CHECK — existing migrations
  are immutable history and are not edited.
- Python: `base.item_state` (drop hold branch), the `apply_mode = job.get(...)`
  lines + `apply_mode=` kwargs in every stage_fn (`extract`, `parse`, `map`,
  `convert`, `cluster`, `export`, `base.record*`).
- Web: `RunDetail.tsx`, `RunsList.tsx`, `useRun.ts`, `useRunItems.ts`,
  `tasksTableModel.ts`, `badges.tsx`, and their tests — remove the apply-mode
  toggle, the "apply held items" action, and the `pending_apply` badge.

### `/ops` filtering + item-filtering UI

- **Per-stage progress facets** for the two new stages and, generally, a
  "partially through the pipeline" filter: select entities by their most-recent
  terminal `job_item` per stage (existing derived-status index, extended to the
  new stages) and by taxonomy `status`.
- Expose the **new fields** the filter UI needs: `taxonomy_nodes.status`, the
  `taxonomy_node` entity kind in the add-tasks facets/read surfaces, and the
  create/combine/connect stage-status. Central stage list lives in
  `web/src/ui/pipelineStages.ts` — update it and let consumers follow.
- **Review surfaces:** `ReviewCard` gains `combine-nodes` and `connect-nodes`
  bodies. `combine` review = confirm/deny a merge (with the blessed survivor).
  `connect` review = confirm `node_kind` + parent + `is_cluster_node`. Approving
  a connect review reuses the existing `create_taxonomy_node` /
  `update_taxonomy_node` RPCs and flips `status` to `live`.

## Rename map

| Old (`STAGE`, DB `stage`, UI) | New canonical |
|---|---|
| `extract` | `extract-recipe` |
| `parse` | `parse-ingredients` |
| `map` | `map-ingredient` |
| `convert` | `convert-steps` |
| `cluster` | `cluster-recipes` |
| `export` | `export-recipegf` |
| — | `combine-nodes` (new) |
| — | `connect-nodes` (new) |

The `stage` string is a stored value (`job_items.stage`, `human_reviews.stage`,
`jobs.stage`, `stage_live_version.stage`, `review_floors.stage`). A data
migration rewrites existing rows to the new names; the `STAGE_FNS` registry keys,
version-constant call sites, CLI subcommands, `pipelineStages.ts`, docs, and
`CLAUDE.md` all move to the new names. Deep internal variable names are renamed
where cheap; a full identifier sweep is not required for correctness.

## Testing

- **Apply teardown:** existing run/stage tests updated to drop apply-mode
  assertions; a migration test confirms `pending_apply`/`apply_mode` are gone and
  no run path references them.
- **map mint:** unit test that an unresolved name yields exactly one provisional
  node (idempotent under repeat) + a provisional resolution.
- **combine-nodes:** eval-style fixture — two synonym provisional nodes merge to
  one; an existing live node is always the survivor when present; resolutions +
  edges repoint; absorbed node tombstoned.
- **connect-nodes:** fixture — a provisional node gains node_kind + parent edge +
  is_cluster_node and promotes to live; antichain invariant preserved; a
  recipe's downstream eligibility flips only after promotion.
- **Downstream gate:** cluster/export/`recipes_public` ignore provisional-node
  ingredients; a recipe becomes eligible only post-promotion.
- **/ops filter:** facet query returns "partially through" entities; new
  `taxonomy_node` entity kind and `status` field surface in the add-tasks filter.
- **Rename:** a guard test/grep that no live code path uses the bare old stage
  names; `pipelineStages.ts` drives the UI list.

## Phasing (separable commits, one PR)

1. **Apply teardown + rename.** Drop apply_mode/pending_apply/apply_run_items
   (Python, SQL migration, web); rename the six existing stages to canonical
   names across code/UI/docs; data migration for stored `stage` strings. Green
   test suite before moving on.
2. **Provisional-node model + downstream gate.** `taxonomy_nodes.status`
   migration; gate `cluster-recipes` / `export-recipegf` / `recipes_public`;
   `map-ingredient` mints provisional nodes on abstain and stops auto-creating /
   proposing forms.
3. **`combine-nodes` + `connect-nodes` stages.** New stage files + version
   constants + registry entries; resolution/edge repointing; promotion;
   `taxonomy_node` entity kind in runs/job_items; eval fixtures.
4. **`/ops` filter + facets + new fields.** Per-stage progress + "partially
   through" filter; expose `status` + `taxonomy_node`; `pipelineStages.ts`.
5. **Review surfaces.** `ReviewCard` combine/connect bodies wired to
   `create_taxonomy_node` / `update_taxonomy_node` + promotion.

Each phase keeps the suite green and is independently reviewable.
