# Proposal Review UI — Design

**Date:** 2026-05-21
**Branch:** `claude/proposal-review-ui` (TBD)
**Status:** Awaiting user review.

## Problem

Form-node taxonomy proposals from the LLM mapper accumulate in
`taxonomy_proposals` and are reviewable today only via
`ingredients ... map review-proposals`, a single-record CLI walker.
There are 694 pending proposals locally; reviewing them in a terminal
is friction enough that they're not getting reviewed.

The CLI has a real capability gap on top of that: it offers approve /
reject / skip / edit-slug, but **no path to alias the raw_string to
an existing taxonomy node** when one of the LLM's candidate
nearest-neighbors is the right answer. Today the only escape is
"reject" — which marks the proposal `rejected` and does nothing to the
raw_string, so the next mapper run proposes it again.

This design adds a web page that does what the CLI does, closes the
"map to existing" gap, and adds a single low-cost flag column so
reviewers can defer cases that need more thought.

## Scope and what this is not

**In scope:** review of `taxonomy_proposals` (form-node proposals only).

**Explicitly out of scope:**

- Reviewing the *other* surfaces where the LLM writes silently today —
  brand/expression auto-creates, ingredient-→-node LLM resolutions,
  canonical-name LLM resolutions, `pending_llm_tried` parked rows,
  `cluster audit` signals. Each is a different decision shape; force-fit
  into one queue produces a worst-of-both UX. Build them per surface
  when they hurt.
- A generic "old-row / new-row" diff-review surface for hypothetical
  Claude-Code-fixes-rows workflows. Real pattern, real future need,
  but a different generation pipeline. The page's *shell* (list/detail
  split, RPC write boundary, decision audit) is structured so a diff-
  review detail-view component can slot in later without redesigning.
- Splitting one `recipe_ingredients` row into multiple ingredients.
  The current `unique (recipe_id, position)` constraint forbids it.
  Captured via the catchall flag in v1; full splitting workflow gets
  its own design when enough flagged rows tell us what it should look
  like.
- Bulk actions / multi-select. Single-reviewer at hundreds-scale is
  fine without them; add when needed.

## Audience

Single admin reviewer (the user), signed in via Supabase magic-link.
Same gating as the existing taxonomy curation UI.

## Design

### 1. Schema change

One column on `recipe_ingredients`, plus an index:

```sql
-- 2026MMDD_add_recipe_ingredient_flag.sql
alter table recipe_ingredients
  add column flag_reason text;

create index recipe_ingredients_flagged_idx
  on recipe_ingredients (flag_reason)
  where flag_reason is not null;
```

And extend the `taxonomy_proposals.status` check constraint to allow
`'flagged'`:

```sql
alter table taxonomy_proposals
  drop constraint taxonomy_proposals_status_check;

alter table taxonomy_proposals
  add constraint taxonomy_proposals_status_check
  check (status in ('pending', 'approved', 'rejected', 'flagged'));
```

Rationale for picking `flag_reason` over `is_ingredient`:

- `mapper_source` (which already includes `'abstain'`) is a *process*
  column — "how did we decide?" — and is the wrong home for the data
  fact "this isn't an ingredient."
- A boolean `is_ingredient` was considered, but the flag covers the
  same case ("not an ingredient" becomes a converging flag reason)
  without committing to a downstream invariant. If patterns warrant it
  later, the column can be promoted to `is_ingredient bool` with a
  one-shot migration.
- The flag reason is **free text** with frontend autosuggest from
  `select distinct flag_reason from recipe_ingredients where flag_reason
  is not null`. No upfront enum, no migrations per new reason,
  convergence happens naturally as the operator reuses prior text.
- `flagged_at` / `flagged_by` audit columns were considered and cut.
  Single-reviewer system; add if a second reviewer ever appears.

### 2. Reviewer action set

Four actions. Every action either closes the proposal (statuses
`approved` / `flagged`) or leaves it pending for next time (`defer`).

| Action                | Effect on `taxonomy_*` tables                                                                                                                                                                                                                       | Effect on `recipe_ingredients`                                                       | Proposal `status` |
|-----------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------|-------------------|
| **Create new node**   | Insert `taxonomy_nodes` (slug + display_name); insert `taxonomy_edges` (proposed_parent_id → new node); insert `taxonomy_aliases` (raw_string → new node); insert `taxonomy_provenance` row (source='llm-mapper-reviewed').                          | `write_resolution(...)` on rows where `name = raw_string`: set `taxonomy_node_id`, `mapper_source='llm'`, `mapper_version`. | `approved`        |
| **Map to existing**   | Insert `taxonomy_aliases` (raw_string → chosen_node_id) if not present.                                                                                                                                                                              | Same `write_resolution(...)` against chosen_node_id.                                | `approved`        |
| **Flag for later**    | None.                                                                                                                                                                                                                                               | Update rows where `name = raw_string`: set `flag_reason = <input>`.                  | `flagged`         |
| **Defer**             | None.                                                                                                                                                                                                                                               | None.                                                                                | `pending` (unchanged) |

The three write actions are exposed as **Postgres RPC functions**, one
each — `apply_proposal_create`, `apply_proposal_map_to_existing`,
`apply_proposal_flag` — each one a single transaction with `security
definer` and an admin-only check. This is the same pattern the
taxonomy curation UI uses ([`web/src/components/taxonomy/rpcs.ts`](../../../web/src/components/taxonomy/rpcs.ts)).

### 3. Layout

List + detail split, admin-gated, route `/proposals` (sibling of
`/taxonomy`). Linked from the existing admin nav.

**Top bar:** filter by `proposed_parent_id` (dropdown over the
distinct parents in the pending queue — currently 27 buckets). Pending
count to the right.

**Left (~38% width):** scrollable list of pending proposals. Each row
shows `raw_string → proposed_slug` and the proposed parent's
`display_name`. Selected row highlighted in the existing brown/gold
palette. Sort order: `created_at desc` (no sort picker in v1).

**Right (~62% width):** detail pane for the selected proposal.

- raw_string, prominently
- Proposed slug (inline-editable, RHF + zod), proposed display_name
  (read-only in v1), proposed parent (read-only in v1)
- Candidates list — `{display_name, similarity}` for each entry in
  `taxonomy_proposals.candidates`. Clicking a candidate row switches
  the action bar into "Map to existing" mode pre-targeted at that
  candidate.
- Action bar at the bottom: **Create** / **Map to existing** /
  **Flag** / **Defer**.

**"Map to existing" UX detail:** the default target is the
highest-similarity candidate, but the reviewer can also use a
**typeahead search over `taxonomy_nodes`** (slug + display_name +
aliases) when the right answer isn't in the candidates list. The
typeahead is the same component the taxonomy curation UI uses for its
parent picker — reuse, don't reinvent. **This typeahead stays in v1**:
without it, "map to existing" is candidates-only, which silently
recreates the same dead-end the CLI has today.

**"Flag" UX detail:** click Flag → an inline text input with
autocomplete over `select distinct flag_reason ...` opens above the
action bar. Reason is required. Submit writes through the
`apply_proposal_flag` RPC.

**Empty state:** "No pending proposals." Linked tip pointing at the
`map resolve-pending` CLI command.

### 4. Architecture

- **Auth gating:** `<RequireAdmin>` wrapper (same as
  [`web/src/App.tsx:70-78`](../../../web/src/App.tsx)).
- **Routing:** new `/proposals` route, lazy-loaded like Taxonomy.
- **Data layer:** **React Query** for list + selection caching, with
  invalidation after each write. Existing taxonomy page uses bespoke
  `useEffect` + `useState`; this feature adopts React Query without
  refactoring the existing page in the same PR. New file:
  `web/src/pages/Proposals.tsx`.
- **Form library:** React Hook Form + zod resolver. Project rule —
  no bespoke form code anywhere.
- **Components (new):**
  - `web/src/pages/Proposals.tsx` — page shell, RequireAdmin, route.
  - `web/src/components/proposals/ProposalList.tsx` — filtered/sorted
    list, selection state.
  - `web/src/components/proposals/ProposalDetail.tsx` — right pane.
  - `web/src/components/proposals/CandidatesList.tsx` — candidates
    rendering + click-to-target-map.
  - `web/src/components/proposals/FlagInput.tsx` — flag reason text
    input + autosuggest query.
  - `web/src/components/proposals/rpcs.ts` — typed wrappers around
    the three RPCs.
- **Components (reused):** the taxonomy curation UI's typeahead /
  node picker (whichever component implements the parent picker in
  `web/src/components/taxonomy/`). Pull it out into a shared
  `web/src/components/common/` module **if and only if** doing so is a
  small mechanical change. Otherwise import from `components/taxonomy/`
  directly and refactor later.

### 5. Downstream coordination

`flag_reason` doesn't break any existing pipeline (nullable, no code
reads it yet), so no other-package changes are required for v1.

For v2, if `is_ingredient` ever gets promoted from "common flag
reason" to a first-class column, the mapper, normalize-names, cluster
compute, and audit signals each need `where is_ingredient = true`
predicates. Out of v1 scope. Captured here so it isn't forgotten.

### 6. RLS

`taxonomy_proposals` has RLS enabled but no policies, matching the
"admin-only via service-role-equivalent RPCs" pattern. Continue that:
the three RPCs are `security definer`, owned by an admin role, and
internally check `is_admin(auth.uid())` against the existing helper
used elsewhere. No direct table reads from the client — all proposal
queries go through a `pending_proposals_view` (or equivalent) the
admin role can read.

## v1 cuts (i.e., obvious next adds, but not now)

- Keyboard shortcuts (j/k navigation, c/m/f/d actions, `/` search,
  Esc to cancel).
- Inline edit of proposed `display_name` and `proposed_parent_id`
  (slug-only edit matches CLI parity for v1; add when LLM proves
  consistently wrong on these).
- Status filter to view `approved` / `flagged` history with
  `decided_by` / `decided_at` audit columns.
- Sort options beyond `created_at desc`.
- Substring search on `raw_string`.
- "Sample recipes" panel showing 3 recipes where this `raw_string`
  appears, with the full ingredient line in context. High decision-
  confidence value; CLI doesn't have it either, so v1 doesn't either.
- Impact count ("N recipe_ingredients rows across M recipes").
- Bulk actions / multi-select.
- Similarity-grouping of related proposals.

## Testing

- Component tests with Vitest + @testing-library/react for the four
  action paths (Create / Map / Flag / Defer), matching the project's
  test pattern.
- Each RPC tested at the SQL level via a fixture loaded into the
  ingredients test DB. Tests assert: (a) the right tables get the
  right rows, (b) the proposal status transitions, (c) idempotency on
  retried Create (slug already exists → error path), (d) admin check
  rejects non-admin.
- One end-to-end happy path: admin loads `/proposals`, sees the list,
  picks a row, runs each of the three write actions in turn, sees the
  list shrink.

## Open questions

None. (Update on first review pass.)
