# Taxonomy Curation UI — Design

**Date:** 2026-05-07
**Branch:** `claude/taxonomy-curation-ui`
**Status:** Awaiting user review.

## Problem

The taxonomy graph UI is read-only. Every node addition, parent change,
field tweak, and deletion still happens via SQL or the LLM-mapper's
auto-creation path. The curator wants to do day-to-day taxonomy work
inside the same UI they already use to inspect the graph: rename a
node, add a child, move parents around, drop a stale node.

Three surfaces:

1. **Inline field edit** on the NodeCard — hover a data field, get a
   pencil, click to edit in place.
2. **Add child** — a `+` on every hovered node opens a modal to create
   a new child node under it.
3. **Edit parents** — a pencil on a new PARENTS section in the NodeCard
   opens an overlay to add/remove parents (fuzzy-search picker shows
   `name #id`, blocks cycles).

Plus:

4. **Delete node** — a Delete button on the focused NodeCard opens a
   blocking-aware confirmation modal.

## Audience

Single curator (the user), local dev environment, signed in as the
admin via Supabase magic-link. No multi-user concerns; no anonymous
write access; no public preview to keep stable.

## Non-goals

- Editing edges directly on the canvas (parents are managed in the
  NodeCard overlay; children via the canvas `+`).
- Audit log of edits. The RPC layer makes this trivial to add later;
  not built in this pass.
- Drag-to-reparent on the canvas. Force-directed layouts make
  drop-target affordances unreliable, and the user explicitly
  rejected this.
- Backfilling rename side-effects in dependent code (eval sets,
  `promote_substances.py`, prior LLM-resolved proposals). Curator's
  responsibility; surfaces listed below.
- Mobile layout, accessibility audit beyond what already exists,
  public read-only mode.
- Cascading delete (decision: refuse if children/recipe/proposal refs
  exist; curator must clean up first).

## Design

### A. Inline field edit on the NodeCard

Today's NodeCard ([`web/src/components/taxonomy/NodeCard.tsx:76-99`](web/src/components/taxonomy/NodeCard.tsx#L76-L99))
is a flat read-only property grid. Add per-field hover affordances and
inline editors.

**Hover affordance:** a 1px solid border in the card's existing brown
palette appears around the field. No background change. A small pencil
glyph appears on the right of the field. Pattern matches Notion /
Linear / Airtable inline-edit conventions.

**Click affordance:** the field swaps into the appropriate editor
inline (no modal):

| Field                  | Editor                                             |
|------------------------|----------------------------------------------------|
| `display_name` (title) | text input                                         |
| `slug`                 | text input                                         |
| `node_kind`            | dropdown: `brand` / `expression` / `(none)`        |
| `default_role`         | dropdown: `base_spirit`, `modifier`, `bitters`, `citrus`, `sweetener`, `dilution`, `wash`, `garnish`, `other`, `(none)` |
| `is_cluster_node`      | toggle                                             |
| `is_defining_garnish`  | toggle                                             |
| `aliases`              | chip editor — each alias is a removable chip; "+ add alias" input below |

**Display-name as title.** `display_name` is the card's heading
(currently the `<div>` rendered before the table). Same hover-pencil
behavior applies — clicking the title's pencil makes the heading
editable in place.

**Read-only fields:** `id`, `recipe_count`. These render with no
hover state and no pencil.

**Slug is editable.** Slug is `unique not null` text but **not a
foreign-key target** anywhere — `parent_ids` / `child_ids` are arrays
of `id`. The only soft references are:

- [`ingredients/src/ingredients/mapping/llm_resolver.py:61`](ingredients/src/ingredients/mapping/llm_resolver.py#L61)
  `_lookup_node_by_slug` — Phase 2 LLM action handlers look up
  parents by slug. A renamed parent slug would silently miss → returns
  None → action treated as failed. Loud failure, not data corruption.
- [`ingredients/src/ingredients/mapping/eval_set.py`](ingredients/src/ingredients/mapping/eval_set.py)
  — eval cases assert on `expect_node_slug`. A rename would fail the
  eval suite, which is a loud, expected check.
- [`ingredients/src/ingredients/dedup/promote_substances.py`](ingredients/src/ingredients/dedup/promote_substances.py)
  — bootstrap loop selects nodes by hard-coded slug.

None of these silently corrupt data. The curator is responsible for
updating these surfaces if they rename a slug. The spec doesn't try to
detect or warn — listing the surfaces in this design is the durable
record.

**Save semantics by editor type:**

- **Text input** (`display_name`, `slug`, individual alias chips):
  `Enter` commits, `Esc` cancels and reverts, blur commits.
- **Dropdown** (`node_kind`, `default_role`): selecting an option
  commits immediately. `Esc` while the menu is open closes without
  changing.
- **Toggle** (`is_cluster_node`, `is_defining_garnish`): clicking the
  toggle commits immediately (single-click is the intent; no
  separate confirm).
- **Chip editor** (`aliases`): the editor manages chip add/remove in
  RHF-local state. Each chip add (typing + `Enter` in the "+ add
  alias" input) and chip remove (clicking the chip's `×`) updates
  local state without saving. Saving happens when the editor as a
  whole loses focus, sending the full new alias list in one
  `update_taxonomy_node(id, {aliases: [...]})` call. `Esc` exits the
  editor without saving and discards staged chip changes.

A failing RPC call reverts the field (or chip-editor list) to the
pre-edit value and surfaces a toast/banner with the error.

**Wiring:** each editable row delegates to a small `<EditableField>`
component (RHF + zod schema per field type). The card-level state
holds the canonical node from the loaded graph; editor commits update
the same in-memory object plus push a graph re-render.

### B. Add child — `+` on hover, then modal form

**Affordance.** When the cursor enters a node, an HTML overlay
positioned at the node's screen coordinates renders a small `+` badge
top-right of the node radius. Position is computed each frame from
the force-graph's `getScreenCoords(node)` so the badge tracks the
node as the simulation settles. The badge is interactive (HTML, not
canvas drawing) so it can receive clicks; the underlying canvas
hover-tooltip continues to render.

**Click.** Opens a centered modal with backdrop. Title:
`New child of <parent display_name>`. Subtitle: `PARENT · <name> (#id)`.
Fields:

| Field                  | Editor                          | Notes                              |
|------------------------|---------------------------------|------------------------------------|
| `display_name`         | text                            | required                           |
| `slug`                 | text                            | auto-derived from `display_name`; editable; required; unique |
| `node_kind`            | dropdown                        | `brand` / `expression` / `(none)` |
| `default_role`         | dropdown                        | the 9 known values + `(none)`     |
| `is_cluster_node`      | toggle                          | default off                       |
| `is_defining_garnish`  | toggle                          | default off                       |
| `aliases`              | chip editor                     | optional; same widget as in (A)   |

**Slug auto-derivation:** as the user types `display_name`, the
`slug` field fills from `display_name.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '')`.
Once the user focuses or edits the `slug` field directly, auto-fill
stops for the rest of the session of that modal.

**Cancel.** Discards the form, modal closes, no graph change.

**Create.** Calls `create_taxonomy_node(...)` (see §E). One
transaction inserts node + edge + aliases. UI behavior on success
follows §F.

### C. Edit parents — overlay with fuzzy search

**Card additions.** The NodeCard gains two new sections, below the
existing field grid:

- `PARENTS · N` — bordered group, each parent listed as `name #id`.
  Hovering the section shows the pencil top-right. Click → overlay.
- `CHILDREN · N (use + on graph to add)` — read-only count and a
  small italic hint. No edit affordance here; children are added via
  the canvas `+` in §B.

**Overlay.** Same modal-with-backdrop chrome as §B. Title:
`Edit parents of <node>`. Subtitle line shows current vs. staged
counts: `2 CURRENT · +1 STAGED · UNSAVED`.

Body has two regions:

1. **Current parents** — a vertical list of `name #id` rows, each
   with an `×` to remove. Removal stages the change (the row stays
   visible but visibly muted / strike-through). Re-clicking the
   `×` (now an undo arrow) on a staged-removal row undoes it.
2. **Staged additions** — newly added parents render in the same
   list with a `+` prefix and accent color. `×` removes from staging.
3. **Add parent** — a search input + result list below. Filter is a
   simple case-insensitive substring on `display_name` and on `slug`.
   Results show `name #id` (id muted, monospace, right-aligned) with
   the matched substring bolded. Each result is selectable by click
   or `Enter`.

**Cycle prevention (client-side):** before showing the result list,
compute the descendant set of the current node by walking
`child_ids` transitively over the in-memory graph. Any descendant —
plus the current node itself — renders greyed out with the inline
reason `<name> → <current> would create cycle`. Already-staged or
already-current parents render greyed with `already added`.
Greyed-out rows are not selectable.

**Cycle prevention (server-side):** `set_node_parents` re-checks the
proposed parent set in plpgsql via a recursive CTE and rejects with
`raise exception 'cycle: <parent_id> is descendant of <node_id>'`.

**Keyboard navigation in the picker:** `↑` / `↓` move highlight
through non-greyed results; `Enter` adds the highlighted result to
staging and clears the search input; `Esc` closes the modal. The
input keeps focus on stage to support multiple consecutive adds.

**Save semantics.** All adds and removes accumulate in modal-local
state. `CANCEL` discards staging and closes. `SAVE` commits all
changes in one RPC call, `set_node_parents(node_id, parent_ids[])`,
which atomically replaces the parent edge set. UI behavior on
success follows §F.

### D. Delete node

**Affordance.** A `Delete node` link/button at the bottom of the
focused NodeCard, only visible in pinned (focused) mode, never on
hover. Subdued styling — small caps, muted color, not a primary
button.

**Click.** Opens a blocking-aware confirmation modal. The modal
surfaces *both* what will cascade and what would block:

```
Delete campari (#42)?

Will cascade:
  · 2 parent edges
  · 1 alias
  · 1 provenance row

Blockers:
  · 3 children — re-parent or delete first
      gin_campari (#118), aperol_campari_blend (#127), …
  · 12 recipe_ingredients references — remap first
  · 0 open taxonomy_proposals

Type slug to confirm:  [______]   [DELETE]
```

If any blocker count is non-zero, the `DELETE` button is disabled
and the "type slug" input is hidden. The modal becomes a read-only
report of what's in the way.

If clean, the curator types the slug; the `DELETE` button enables
when the input matches; click → RPC `delete_taxonomy_node(id)`. The
RPC re-runs the same preflight checks server-side (children, refs,
proposals) and refuses if anything has appeared since the modal
opened. On success, the cascading deletes (`taxonomy_edges`,
`taxonomy_aliases`, `taxonomy_provenance`) happen automatically via
existing FK rules.

**Why preflight in the UI AND the RPC.** The UI count is convenience
(curator sees the impact before clicking). The RPC re-check is
correctness (another tab might have added a child between view and
click).

**After delete.** Drop the node and its edges from the in-memory
graph; clear focus; brief toast `Deleted campari (#42)`.

### E. Backend write path — RPC functions

A new migration adds four `SECURITY DEFINER` plpgsql functions, all
guarded by `(select coalesce(is_admin, false) from profiles where id = auth.uid())`:

| Function                                        | Purpose                                          |
|-------------------------------------------------|--------------------------------------------------|
| `create_taxonomy_node(parent_id, slug, display_name, node_kind, default_role, is_cluster_node, is_defining_garnish, aliases) returns bigint` | Insert node + edge + aliases atomically. Returns new id. |
| `update_taxonomy_node(id, patch jsonb) returns void` | Patch any subset of `slug`, `display_name`, `node_kind`, `default_role`, `is_cluster_node`, `is_defining_garnish`, `aliases`. `aliases` is replace-all. |
| `set_node_parents(id, parent_ids bigint[]) returns void` | Replace parent edge set; reject cycles via recursive CTE. |
| `delete_taxonomy_node(id) returns void`         | Preflight-check children + recipe_ingredients refs + open proposals; refuse if any. Else delete (cascades handle the rest). |

RLS on `taxonomy_nodes` / `taxonomy_edges` / `taxonomy_aliases` is
tightened so direct writes from the publishable / authenticated keys
are denied — only the SECURITY DEFINER functions can mutate. Existing
read grants on `taxonomy_public` remain.

The view `taxonomy_public` does not need to change; it already exposes
everything the SPA reads (parent_ids, child_ids, aliases, recipe_count
via lateral joins).

**Why RPC over RLS-on-tables.** Multi-row operations (parent edits,
new-node + edge + aliases) need to be atomic. Wrapping them in a
function gives one round-trip, one transaction, one audit surface,
and one place to add an `audit_log` table later without touching the
client.

### F. Post-save graph behavior

After any RPC succeeds (create / update / set_parents / delete), the
client must update the loaded graph state without a full re-fetch
and without a canvas re-mount.

- **Wait for RPC success.** No optimistic state. Simpler, no rollback
  ceremony, network round-trip is fast against local Supabase.
- **Incremental state update.** The page-level `rows` array (today
  set once via `setState({ status: 'loaded', rows })` in
  [`web/src/pages/Taxonomy.tsx:44-58`](web/src/pages/Taxonomy.tsx#L44-L58))
  becomes the canonical store. After a successful mutation, splice
  the affected row(s) in place and call `setState` with a new array
  reference; downstream `shapeData` / `ForceCanvas` re-derive nodes
  and edges. `react-force-graph-2d`'s reconciler keeps existing node
  positions and runs physics on the new node only.
- **Auto-focus the new / edited node.** `setFocusedId(newOrEditedId)`
  so its NodeCard opens, ready for follow-up edits.
- **Pulse highlight.** A 2-second gold ring pulse on the affected
  node, implemented as a transient CSS / canvas overlay. New entry
  in `palette.ts` reuses the existing gold token. Decays after ~2s,
  no permanent state.
- **Pan to bring into view.** If the affected node's screen
  coordinates fall outside the viewport after physics has settled,
  smoothly pan the camera to center it. If already on-screen, no
  movement.

### G. Cross-cutting — form library

All forms in `web/` standardize on **`react-hook-form` + `zod` +
`@hookform/resolvers/zod`**. Both the create-child modal and the
edit-parents overlay use this stack from day one. The inline editors
in (A) also use the same primitives (a per-field RHF instance, a
zod schema per editor type) so behavior is consistent across the
three surfaces.

This is recorded as a feedback memory and applies to every future
form in the project, including migrations of any pre-existing
non-RHF form.

### H. Authn / authz

The route is already gated by [`<RequireAdmin />`](web/src/App.tsx#L31).
The four RPC functions independently re-check `profiles.is_admin`
inside the function body, so the server enforces admin-only writes
even if the route guard is bypassed (e.g., via the Supabase REST
endpoint directly).

## Out of scope (recap)

- Drag-to-reparent on canvas.
- Cascading delete (children / recipe_ingredients re-mapping).
- Audit log of edits.
- Backfilling rename side-effects in `eval_set.py`,
  `promote_substances.py`, prior LLM-resolved proposals.
- Mobile layout, accessibility audit beyond existing, public preview.

## Open questions (none currently — all resolved during brainstorm)
