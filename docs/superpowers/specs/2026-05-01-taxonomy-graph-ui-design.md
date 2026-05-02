# Taxonomy Graph UI — Design

**Date:** 2026-05-01
**Branch:** `claude/taxonomy-graph-ui-4e67`
**Status:** Awaiting user review.

## Problem

We have ~166 taxonomy nodes, ~151 edges, and ~209 aliases in the local
Supabase, much of it freshly hand-seeded. There is no way to see the graph
structure other than by reading SQL or seed files. Curator-grade QA needs
to be able to spot, at a glance:

- Orphans (nodes with no parents that aren't intentional roots)
- `is_cluster_node` placement that violates the "no cluster ancestor"
  invariant or looks asymmetric
- Brand/expression nodes hanging off the wrong type
- Missing or misspelled aliases
- Nodes nobody is using (zero recipes)
- Role / `role_default` mismatches

## Goals

1. **Browse the entire taxonomy on one canvas** — force-directed layout
   so structurally similar nodes settle near each other; pan/zoom; visible
   QA signals via color, ring style, dashed border, size.
2. **Click a node to focus it** — that node centers, parents and children
   pin to a radial layout around it, aliases float as labels, the rest of
   the graph dims but stays in place. Esc returns to global.
3. **Look like a cocktail bar / Art Deco compendium**, not a sci-fi HUD.
   Walnut field, antique gold lines, ivory ink, deco bracket corners,
   Cinzel + Cormorant Garamond. The detail panel reads like a cocktail
   menu insert.
4. **No backend.** Reuse the existing Supabase publishable-key pattern.

## Non-goals (v1)

- Editing or adding nodes/edges/aliases from the UI. Future-relevant but
  explicitly out of v1; chosen library does not paint us into a corner if
  we add this later.
- Drilling from a taxonomy node into a filtered recipe list. Recipes and
  taxonomy stay separate routes for now.
- Descendant-recipe-count rollup. v1 shows direct recipe counts only.
- 3D, mobile layout, multi-select, server-side pagination of the graph.

## Library

**`react-force-graph-2d`** (vasturiano).

Selection rationale (full research lives in the brainstorming transcript;
the headline points):

- Force-directed layout *is* the headline feature; 166 nodes is trivial.
- Canvas renderer — fast, sharp, no SVG node-explosion at zoom.
- First-class TS, declarative React props (`onNodeClick`, `nodeColor`,
  `nodeCanvasObject`).
- Polished defaults — the vasturiano demos are why people pick it.
- Radial focus mode is a DIY layer (pin neighbor `fx`/`fy` to a ring
  around the focused node, animate camera with `centerAt` /`zoomToFit`)
  but it's evening-sized work.
- Editing nodes/edges later is moderate-effort but does not require
  switching libraries. Cytoscape would beat it on editing but loses on
  React-idiom and aesthetic polish; per the rule "only switch libs if
  future drastically changes things," the future trade-off does not.

Skipped: React Flow (workflow-builder aesthetic, wrong vibe), vis-network
(stagnant, looks like 2015), Sigma.js (overkill at 166 nodes), raw d3-force
(reinventing react-force-graph badly).

## Data flow

One SQL view: `taxonomy_public`. One client fetch on page load. All
force layout, focus mode, search, and filtering are computed locally
against the in-memory result. No further Supabase calls until full
reload.

### View shape

```
taxonomy_public
  id                    bigint
  slug                  text
  display_name          text
  role                  text         -- nullable: 'brand' | 'expression' | null
  role_default          text         -- nullable: substance role hint
  is_cluster_node       bool
  is_defining_garnish   bool
  parent_ids            bigint[]     -- aggregated from taxonomy_edges
  child_ids             bigint[]
  aliases               text[]       -- aggregated from taxonomy_aliases
  recipe_count          int          -- count(distinct recipe_id) via
                                     --   recipe_ingredients.taxonomy_node_id = id
                                     -- direct only; no descendant rollup
```

### Migration

A new `supabase/migrations/<ts>_create_taxonomy_public.sql`,
mirroring the `recipes_public` pattern (`security_invoker = true` +
column-level grants + public-read RLS on each underlying table):

1. `create view taxonomy_public with (security_invoker = true) as (...)`
2. `grant select on taxonomy_public to anon, authenticated;`
3. For each of `taxonomy_nodes`, `taxonomy_edges`, `taxonomy_aliases`:
   column-level `grant select` on all current columns + a public-read
   `for select using (true)` policy.
4. For `recipe_ingredients`: a tightly-scoped column-level
   `grant select (recipe_id, taxonomy_node_id)` (and nothing else) plus
   a public-read policy. Because invoker permissions only let anon see
   those two columns, the view's `recipe_count` aggregate works without
   exposing parser status, raw ingredient text, parser version, etc.
   to direct queries.

### Fetch

```ts
const { data, error } = await supabase
  .from('taxonomy_public')
  .select(
    'id, slug, display_name, role, role_default, ' +
    'is_cluster_node, is_defining_garnish, ' +
    'parent_ids, child_ids, aliases, recipe_count'
  );
```

## Routing & integration

- New route `/taxonomy` rendered by `<Taxonomy />` in `App.tsx`.
- A small top header is added to `App.tsx` and rendered on every page:
  - Left: wordmark **SPIRITOLO** in Cinzel, letterspaced.
  - Right: `Recipes` and `Taxonomy` nav links.
  - This is the first cross-page chrome — RecipeList and RecipeDetail
    keep their existing layout, the header just sits above them.
- Cinzel + Cormorant Garamond loaded once via `<link>` in `index.html`.
  Scoped by class on the taxonomy page so the new fonts don't leak
  into recipe pages (recipes stay system-sans).

## Component breakdown

```
web/src/pages/Taxonomy.tsx
  Owns: fetch, view state (focused id, search query, filter chips,
        zoom level). Composes the rest. Layout: full-bleed canvas with
        floating overlay panels.

web/src/components/taxonomy/
  ForceCanvas.tsx        Wraps react-force-graph-2d. Custom node draw
                         (bottle-cap style: dark fill, gold ring,
                         optional cluster halo). Handles click/hover.
                         Camera animation entry point.

  FocusOverlay.tsx       When a node is focused: dims non-neighbors via
                         link/node opacity props, pins parents and
                         children to a radial layout (fx/fy on the
                         neighbor subset), renders alias italics as
                         absolutely-positioned text over the canvas.

  SpecimenCard.tsx       Slide-in cream "menu card" detail panel with
                         the focused node's properties, alias list,
                         recipe count, copyable slug, "esc to dismiss"
                         hint.

  SearchBox.tsx          Cmd-K or click. Substring match on slug,
                         display_name, aliases. Matches stay
                         full-opacity, others dim. Enter focuses top
                         match.

  FilterChips.tsx        Toggleable chips: substance / expression /
                         brand / cluster-only / orphans / no-aliases /
                         zero-recipes.

  Legend.tsx             Static deco-card legend, top-right.

  ZoomControls.tsx       Bottom-right deco-card with - / + / fit-to-view.

  shapeData.ts           Pure transforms: view rows -> ForceGraph
                         nodes/links; orphan detection; neighborsOf;
                         radialPositions; substring matching.

  taxonomy.css           Palette tokens, deco corner mixin, gold rules,
                         menu-card paper.
```

`shapeData.ts` is the only place with non-trivial logic that doesn't
touch the DOM or canvas. It is the unit-test boundary.

## Visual & interaction reference

The brainstorm visual companion file
`.superpowers/brainstorm/82445-1777612943/content/visual-design-v2.html`
is the canonical visual reference. Summary:

- **Field:** radial gradient `#2a1d11 → #160d05 → #0d0703` (walnut to
  near-black); deco bracket corners in `#c9a449` (antique gold).
- **Title cartouche** centered top: "— A COMPENDIUM OF —" small caps
  letterspaced + "SPIRITS & LIQUEURS" larger Cinzel + hairline gold rule.
- **Type:** Cinzel for headings and node labels (small caps,
  `letter-spacing: 0.18em`); Cormorant Garamond for body and aliases
  (italic for aliases).
- **Nodes:** filled dark center (`#1a0f06`), gold ring (`#c9a449`),
  inner halo for `is_cluster_node`. Color of the inner fill encodes role.
- **Edges:** thin gold curves at ~55% opacity (active) / ~10% (faded
  when something is focused).
- **Sidebar = menu card:** cream paper (`#f5e9c8 → #ecddb4`), dark
  brown ink (`#2c1d0c`), Cinzel section labels in `#7a5520`. Slides in
  from the right when a node is focused.

### QA signals on the canvas

| Signal | Visual |
|---|---|
| `role` (or `role_default` when role is null) | Inner fill color: cream (substance), brick (expression), aged copper-green (brand) |
| Role inferred from `role_default` (not asserted) | Small `?` glyph next to the node |
| `is_cluster_node = true` | Inner halo ring |
| `is_defining_garnish = true` | Leaf glyph |
| Orphan (no parents AND not on the curated top-level allowlist) | Dashed border in brick red |
| `recipe_count` | Node radius = `sqrt(recipe_count + 1) * k` (zero-recipe nodes still visible) |

The curated top-level allowlist (e.g. `whiskey`, `vermouth`, `bitters`,
`liqueur`, `juice`, `sweetener`, …) lives in `shapeData.ts` so the
orphan check doesn't false-positive on the actual roots of the DAG.

### Interactions

- **Hover:** tooltip with display_name, role / role_default, recipe_count,
  alias count.
- **Click node:** focus mode. Camera animates to the node; neighbors pin
  to a radial ring; non-neighbors dim to ~12% opacity; sidebar slides in.
- **Click empty canvas / Esc:** exit focus mode; camera returns to last
  global view; sidebar slides out.
- **Search:** live substring filter highlights matches; Enter focuses
  top match.
- **Filter chips:** toggle node visibility (faded, not removed — keeps
  layout stable).

## Implementation discipline

- **Red/green TDD** as ground rule for `shapeData.ts` and any other
  pure-logic module. Write a failing test, make it pass, refactor.
- **Component tests** with `@testing-library/react` + Vitest for
  Search, FilterChips, SpecimenCard — anything whose behavior is DOM-
  observable.
- **Canvas pixels are not unit-tested.** ForceCanvas and FocusOverlay
  are validated by hand in the dev server.
- **Do not test against react-force-graph internals.** Treat it as an
  opaque dependency; assert against the props we pass it and the data
  we shape.

## Testing surface

| Module | Test approach |
|---|---|
| `shapeData.ts` | Vitest unit tests. Covers: view-row → node mapping, orphan detection (with allowlist), `neighborsOf`, `radialPositions` (deterministic), substring match including alias matches, role coalescing (`role ?? role_default`). |
| `SpecimenCard.tsx` | RTL: renders props; Esc dismisses; copy-slug click writes to clipboard. |
| `SearchBox.tsx` | RTL: typing emits change; Enter emits focus event. |
| `FilterChips.tsx` | RTL: toggling a chip updates filter set. |
| Migration | `supabase db reset` followed by a Vitest smoke that fetches `taxonomy_public` and asserts non-zero rows + expected columns. |
| Whole page | Manual: open `/taxonomy`, check global view, focus rye_whiskey, hit Esc, search "rye". |

## Open implementation questions (resolve in plan)

- Cmd-K vs explicit search box — start with both: an always-visible
  search input and a Cmd-K shortcut that focuses it.
- Mobile: deferred. Page renders something usable on small screens
  (graph zooms out, panel becomes full-screen overlay) but no
  responsive tuning.
- Dark mode: there is no light mode; `/taxonomy` is always dark walnut.
  RecipeList stays system / light as today.

## Scope summary

This is one focused implementation plan. Building blocks:

1. Migration: `taxonomy_public` view + grants + policies.
2. Header: new top nav in `App.tsx`, font loading.
3. Pure data module: `shapeData.ts` with full unit-test coverage.
4. Page shell: `Taxonomy.tsx` + global force canvas with deco styling.
5. Focus mode: radial layout, dim, sidebar.
6. Search + filters + legend + zoom.
7. Manual integration check in dev server.

Single-PR-size; no decomposition needed.
