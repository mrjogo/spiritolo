# Taxonomy Graph UI — Curator-Pass Cleanup — Design

**Date:** 2026-05-01
**Branch:** `claude/taxonomy-graph-ui-4e67`
**Status:** Awaiting user review.

## Problem

After living with the v1 taxonomy graph UI for a session, the curator (the
only audience) flagged a punch list of friction points:

1. The hover label sits at a fixed position in the top-right and overlaps
   the legend.
2. The on-canvas `?` glyph that flags "role inferred" is overloaded in
   meaning, overlaps when nodes cluster, and doesn't survive a re-read of
   the legend.
3. Substance-role nodes look "empty" on the canvas while the legend shows
   them filled — the actual cause is a fallback bug, not a styling issue.
4. The specimen card is a full-height drawer; clicking a node feels heavy.
   The on-canvas alias orbit overlaps and duplicates what's already in the
   card.
5. The legend's `cluster` and `orphan` markers don't say what those mean,
   and "cluster" collides with the unrelated `recipe_clusters` concept.
6. Edge directionality (parent → child) isn't visually expressed; the
   curator has to click into a node to know which way the DAG runs.
7. Two columns on `taxonomy_nodes` named `role` and `role_default` mean
   different things (taxonomy node *type* vs. typical *recipe-position
   role*), and the UI labels reproduce that confusion verbatim.

The fix is curator-quality-of-life work — no architectural changes, no new
features, no public surface area. Render bugs and labels.

## Non-goals

- Renaming the underlying `role` / `role_default` columns. That's a
  separate, larger change that touches the role classifier, the dedup
  pipeline, the seed files, and migrations. The UI labels in this pass
  are an interim fix; the column rename is tracked separately.
- Adding new QA signals (e.g., descendant-recipe-count rollup, antichain
  invariant violations highlighted on the canvas). Out of scope.
- Mobile layout, accessibility audit beyond what already exists, public
  read-only mode. Out of scope.

## Audience

Single curator, local dev environment. No multi-user concerns, no public
read view to preserve, no analytics to maintain.

## Design

### A. Single hover/click card, sized to content

Today there are two separate components:

- A small hover card at fixed `top: 150, right: 14` that overlaps the
  legend ([Taxonomy.tsx:201–216](web/src/pages/Taxonomy.tsx#L201-L216)).
- A full-height `SpecimenCard` drawer pinned at `top: 0, right: 0,
  bottom: 0` ([SpecimenCard.tsx:21–30](web/src/components/taxonomy/SpecimenCard.tsx#L21-L30)).

Replace both with **one component** that renders in two modes:

- **Hover mode** (transient): cursor enters a node → card appears with
  that node's details. Cursor leaves all nodes → card disappears. No
  pinning of neighbors, no canvas dimming.
- **Pinned mode**: click a node → card stays. Neighbor pinning + canvas
  dimming kick in (same behavior as today's `focusedId`). Hover-over
  *other* nodes does **not** swap the card while it's pinned.

**Placement:** top-right gutter, *below* the legend. Approximate
`top: ~150, right: 14`, sized to its content (auto height, no
`bottom: 0`, no fixed `width: 240` unless content forces it). Visually
this is the same slot where the legend's hover card lives today, so no
new real-estate decisions.

**Dismiss (pinned mode):**
- Explicit X button in the card's top-right corner.
- Esc key (existing).
- Click on empty canvas (existing wiring at
  [Taxonomy.tsx:190](web/src/pages/Taxonomy.tsx#L190); verify it fires
  while the card is open and that `pointer-events` on the card don't
  swallow background clicks).
- Replace the existing "ESC TO DISMISS" footer text — the X plus the
  three exit paths above are enough.

**Drop the on-canvas alias orbit.**
[ForceCanvas.tsx:161–183](web/src/components/taxonomy/ForceCanvas.tsx#L161-L183)
renders a focused node's aliases as labels around it; in dense subtrees
they overlap each other and the underlying nodes. The card already
prints the canonical alias list. Remove the orbit drawing entirely;
keep the card's `ALIASES (n) — comma list` block.

### B. Drop the `?` glyph; render null-role nodes as gray

Today's behavior:

- `effectiveRole` ([shapeData.ts:27–29](web/src/components/taxonomy/shapeData.ts#L27-L29))
  falls back from `role` to `role_default`. That's wrong: `role_default`
  values like `'modifier'` or `'bitters'` are recipe-position roles,
  not taxonomy types — the palette has no entry for them and they
  render with an undefined fill.
- `drawNode` paints `?` near a node when `role IS NULL AND role_default
  IS NOT NULL` ([ForceCanvas.tsx:136–142](web/src/components/taxonomy/ForceCanvas.tsx#L136-L142)).
  That's a sub-case of "role (taxonomy) is null" — the
  partial-classification subset where the recipe-position role has been
  filled in. The legend currently labels this `? = role inferred`,
  which is actively misleading.

Fix:

1. Change `effectiveRole` to return `'unknown'` whenever `role IS NULL`,
   without consulting `role_default`. The TS type for
   `TaxonomyViewRow.role_default` becomes `string | null` (it was
   incorrectly typed as a union of taxonomy-role values).
2. Stop drawing the `?` glyph. The QA signal collapses to the gray fill
   that null-role nodes already get from the `unknown` palette entry
   (`#888888`) once the fallback bug is fixed. Curator triages from gray
   dots and reads the specimen card for the partial-classification
   distinction.

Removing the glyph also resolves the canvas-cluttering overlap the
curator flagged in dense subtrees.

### C. Specimen-card label rename (interim)

In the specimen card's PROPERTIES block:

- `role` → **"Role (taxonomy)"** — values: `substance` / `expression` /
  `brand` / `—`.
- `role default` → **"Default Role (recipe ingredient)"** — values:
  `base` / `modifier` / `bitters` / etc., or `—`.
- `cluster node` → **"Clustering node"**.
- `defining garnish` row stays.

These labels are explicit-but-verbose on purpose so the curator can
disambiguate at a glance. They get cleaner once the underlying columns
are renamed (separate work).

### D. Drop the dashed orphan ring; rely on arrows + parent-edge presence

Today, an "orphan" is a node with no parent and not in the hardcoded
`TOP_LEVEL_ALLOWLIST`
([shapeData.ts:51–76](web/src/components/taxonomy/shapeData.ts#L51-L76))
of slugs we expect to be top-level (`whiskey`, `gin`, `rum`, etc.).
Orphans get a dashed rust-colored ring.

After arrows are added (next section), the curator can see directly that
a node has no incoming edge and judge whether it should — the allowlist
becomes a maintenance burden with no remaining payoff.

- **Drop the dashed orphan ring** in `drawNode`
  ([ForceCanvas.tsx:113–125](web/src/components/taxonomy/ForceCanvas.tsx#L113-L125)).
- **Delete the `TOP_LEVEL_ALLOWLIST` and `isOrphan` function.** No
  remaining caller besides the orphan filter chip (next bullet).
- **Replace the orphan filter chip's predicate** with the simpler
  `parent_ids.length === 0` — i.e., "any parentless node," not "any
  parentless node not on the allowlist." Curator can scan the few
  legitimate roots (whiskey, gin, …) in their head; exposing the
  allowlist as code wasn't earning its weight.

### E. Directional arrows on edges

`react-force-graph-2d` ships built-in directional arrows. Configure on
the `<ForceGraph2D>` element:

- `linkDirectionalArrowLength={4}` — short triangular tip; will be
  fine-tuned in implementation against the actual canvas zoom levels.
- `linkDirectionalArrowRelPos={0.92}` — sits just inside the target
  node's outer ring rather than at the node centre.
- `linkDirectionalArrowColor={() => TX_GOLD}` — same antique gold as
  the rings; the arrow reads as "engraving direction," not as UI chrome.

Edges already curl (`linkCurvature={0.18}`), so the arrow gets a natural
hook into the target. If at the chosen sizes the arrows look chunky next
to the small nodes, fall back on `linkDirectionalArrowLength={3}` and
revisit. No alternative library is needed; this is a one-line config.

### F. Legend rewrite

Final legend body — three role swatches up top (rendered as filled
circles in the existing palette, same `LegendDot` component as today),
followed by an italic explanation block:

```
— LEGEND —

● substance       (cream swatch)
● expression      (rust swatch)
● brand           (sage swatch)

○ extra ring  = clustering node (dedup rollup target)
○ gray fill   = role (taxonomy) not set
→             = parent → child
```

The "(cream/rust/sage swatch)" parentheticals above describe what the
swatch *looks like* — they are not literal text the legend shows. The
actual rendered label next to each dot is just `substance` /
`expression` / `brand`, as today.

Removed: the `?` line, the dashed-orphan line, the defining-garnish
line. The ❦ glyph still draws on defining-garnish nodes
([ForceCanvas.tsx:148–154](web/src/components/taxonomy/ForceCanvas.tsx#L148-L154));
its row also stays in the specimen card. Curator doesn't need it
explained at a glance.

## File-level impact

- **[ForceCanvas.tsx](web/src/components/taxonomy/ForceCanvas.tsx)** —
  drop `?` rendering; drop dashed-ring branch; drop `drawAliasOrbit`
  and its call site; add directional arrow props.
- **[shapeData.ts](web/src/components/taxonomy/shapeData.ts)** —
  fix `effectiveRole`; broaden the `role_default` type; delete
  `TOP_LEVEL_ALLOWLIST` and `isOrphan`; tighten `rowMatchesFilters`'s
  orphan branch.
- **[Legend.tsx](web/src/components/taxonomy/Legend.tsx)** — rewrite per
  section F.
- **[Taxonomy.tsx](web/src/pages/Taxonomy.tsx)** — drop the inline
  hover-card JSX; wire hover into the same component now used for click;
  ensure `onBackgroundClick` still dismisses while pinned.
- **[SpecimenCard.tsx](web/src/components/taxonomy/SpecimenCard.tsx)** —
  rename to a more general name (e.g. `NodeCard`) since it now serves
  both hover and pinned modes; auto-height layout; X button; updated
  labels per section C; drop the "ESC TO DISMISS" footer.
- **[SpecimenCard.test.tsx](web/src/components/taxonomy/SpecimenCard.test.tsx)** —
  update to the new component name; add tests for the hover-vs-pinned
  branching, X-button dismiss, and click-empty dismiss.
- **[shapeData.test.ts](web/src/components/taxonomy/shapeData.test.ts)** —
  update the `effectiveRole` cases (no more `role_default` fallback);
  remove `isOrphan` cases; update orphan-filter cases to the parent-only
  predicate.
- **[FilterChips.tsx](web/src/components/taxonomy/FilterChips.tsx)** —
  rename the visible "cluster" chip to "clustering node" (`FilterKey`
  string stays; the user-visible label changes).
- **[FilterChips.test.tsx](web/src/components/taxonomy/FilterChips.test.tsx)** —
  update label assertions.

The `effectiveRoleLabel` function
([shapeData.ts:31–35](web/src/components/taxonomy/shapeData.ts#L31-L35))
currently returns `role`, or `role_default + '?'`, or `'unknown'`. The
`?`-suffix branch was a textual mirror of the canvas glyph; with the
glyph gone, simplify the function to `return node.role ?? 'unknown'`.
Its only caller is the hover-card subtitle, which reads cleaner without
the recipe-role bleed-through.

## Risks / things to watch

- **Click-empty dismiss while pinned.** Need to verify
  `onBackgroundClick` actually fires when the card overlay is open. If
  the card's container intercepts pointer events outside its visible
  bounds, fix by tightening `pointer-events` on the card root rather
  than by adding an explicit overlay div.
- **Arrow size at the curator's typical zoom.** `linkDirectionalArrowLength`
  is a constant in canvas units, not screen pixels — it scales with
  zoom. If it reads too large at fit-zoom or too small zoomed-in, we
  may want to adjust based on the empirical sweet spot rather than
  guessing here.
- **Hover/pin transitions.** Moving the cursor off a node onto the card
  itself shouldn't dismiss the (pinned) card. In hover mode it should:
  the card is transient and disappears when not hovering a node.

## Out of scope (logged for follow-up)

- Renaming `taxonomy_nodes.role` and `taxonomy_nodes.role_default` to
  unambiguous names. Touches the role classifier, dedup compute,
  fixtures, eval set, and seeds. Separate spec.
- Showing antichain-invariant violations directly on the canvas (e.g.,
  cluster-node-with-cluster-ancestor flagged in red).
- Promoting the orphan filter chip into an "unparented & unintentional"
  flag once the curator picks back up triaging top-level coverage.
