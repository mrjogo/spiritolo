# Taxonomy Graph UI — Layout, Color, and Labels — Design

**Date:** 2026-05-02
**Branch:** `claude/taxonomy-graph-ui-4e67`
**Status:** Awaiting user review.

## Problem

After the curator-pass round (`docs/superpowers/specs/2026-05-01-taxonomy-graph-ui-curator-pass-design.md`) shipped and was viewed in the running app, the curator flagged six remaining issues:

1. **Disconnected components pile on top of each other.** The default
   force-directed layout pulls every node toward a single centre, so
   nodes from unconnected sub-trees end up stacked on top of each other
   and the visual reads as one tangled blob.
2. **"Gray fill" wording is confusing in the legend.** All three role
   swatches are fills (cream, rust, sage), so calling the null-role
   marker a "gray fill" reads ambiguously — "gray" is the value; "fill"
   is the channel.
3. **The arrow explanation in the legend is redundant.** Once arrows
   are visible on the canvas, the curator doesn't need a legend line
   for them.
4. **The "extra ring" treatment for clustering nodes is too subtle.**
   A thin gold halo on top of the gold ring is visually a fence-post
   error — easy to miss. A *different ring colour* would be unambiguous.
5. **The specimen card overlaps the legend** at narrow viewport heights
   or when the legend wraps. The card's `top: 150` was a hand-coded
   offset that doesn't track the legend's actual rendered height.
6. **Nodes have no on-canvas labels.** Hovering reveals a card with
   the name, but the curator wants names visible at a glance when
   zoomed in close enough that the labels don't have to be tiny.

## Audience

Single curator (still). No public surface area. No backend changes.

## Non-goals

- Renaming `taxonomy_nodes.role` and `role_default`. That work is
  starting in a separate worktree
  (`.worktrees/role-rename/docs/superpowers/specs/2026-05-02-taxonomy-role-rename-design.md`)
  and the interim "Role (taxonomy)" / "Default Role (recipe ingredient)"
  labels stay untouched here.
- Mobile layout, accessibility audit, public read-only mode.
- Drilling from a taxonomy node into a filtered recipe list.
- Antichain-invariant violation highlighting.

## Design

### A. Drop the centring force; bump charge

[ForceCanvas.tsx](web/src/components/taxonomy/ForceCanvas.tsx)
currently relies on `react-force-graph-2d`'s defaults — among them a
`forceCenter` that pulls every node toward `(width/2, height/2)`,
which is what stacks disconnected components on top of each other.

Two changes, expressed in the same `useEffect` shown in section E
(don't duplicate the code here):
- Null out the `'center'` force.
- Raise the `'charge'` force's strength from the default (−30) to
  about −120, so disconnected components visibly push apart on
  repulsion alone.

−120 is a starting value; the implementation plan will tune it once
labels (section E) are also active, since label-aware bbox-collide
adds significant per-node radius and changes how strongly charge
needs to push.

### B. Palette swap

In [palette.ts](web/src/components/taxonomy/palette.ts):

- `ROLE_FILL.expression`: `#a85b3a` → `#3a6b6e` (deep teal).
- New constant `TX_CLUSTER_RING = '#a85b3a'` (the rust the expression
  fill used to occupy).
- `--tx-expression` in [taxonomy.css](web/src/components/taxonomy/taxonomy.css)
  similarly retargets to the deep teal hex.

In [ForceCanvas.tsx](web/src/components/taxonomy/ForceCanvas.tsx)
`drawNode`:

- The cluster-halo block (`if (node.is_cluster_node) { ctx.arc(haloR, …) }`)
  is deleted entirely.
- The gold-ring stroke becomes role-aware: `ctx.strokeStyle = node.is_cluster_node ? TX_CLUSTER_RING : TX_GOLD;`. Nothing else
  in the ring drawing changes (still solid, still `lineWidth: 1.0`).

The `haloR` local variable becomes unused; remove it.

### C. Stack legend and node card in one flex column

In [Taxonomy.tsx](web/src/pages/Taxonomy.tsx), wrap the existing
`<Legend />` render and the `(focusedNode | hovered)` `<NodeCard …/>`
IIFE in a single absolutely-positioned flex column:

```tsx
<div
  style={{
    position: 'absolute', top: 14, right: 14, zIndex: 3,
    display: 'flex', flexDirection: 'column', gap: 12,
  }}
>
  <Legend />
  {(() => {
    if (focusedNode) return <NodeCard … mode="pinned" … />;
    if (hovered)     return <NodeCard … mode="hover"  … />;
    return null;
  })()}
</div>
```

Both children drop their own `position: absolute` / `top` / `right`
styling. The browser stacks them; when the card mounts it appears
under the legend with a 12 px gap, regardless of the legend's
rendered height. No `useRef`, no measurement, no layout effect.

The wrapping `<div>`'s `zIndex: 3` matches the higher of the two
prior values (legend was 2, card was 4 — neither needs to be above
the other now since they don't overlap; 3 keeps both above the
canvas).

### D. Legend rewrite (third revision)

Final body of [Legend.tsx](web/src/components/taxonomy/Legend.tsx):

```tsx
<div className="tx-card" style={{ padding: '8px 12px', fontSize: 12, lineHeight: 1.55, width: 180 }}>
  <div className="tx-card__heading" style={{ marginBottom: 4 }}>LEGEND</div>
  <LegendDot color={ROLE_FILL.substance} /> substance<br />
  <LegendDot color={ROLE_FILL.expression} /> expression<br />
  <LegendDot color={ROLE_FILL.brand} /> brand<br />
  <div style={{ marginTop: 4, fontStyle: 'italic', color: TX_BROWN_SOFT, lineHeight: 1.4 }}>
    ◯ rust ring = clustering node<br />
    ◯ gray = role (taxonomy) not set
  </div>
</div>
```

Removed: the `extra ring = clustering node` line (replaced by the
rust-ring line), the `arrow = parent → child` line, the word `fill`
on the gray line. The `position: absolute / top / right / zIndex`
inline-style block also goes — section C's flex container owns it
now.

### E. Node labels via `d3-bboxCollide`

The biggest change.

**Dependency.** Add `d3-bboxCollide` to `web/package.json` at
`^1.0.4` (current latest on npm, last published 2018; stable). The
package ships no TypeScript types; add a one-line shim at
`web/src/types/d3-bboxCollide.d.ts`:

```ts
declare module 'd3-bboxCollide' {
  export function bboxCollide(
    bbox: (node: unknown) => [[number, number], [number, number]]
  ): {
    iterations(n: number): typeof this;
    initialize: (nodes: unknown[]) => void;
    (alpha: number): void;
  };
}
```

(The type is loose on purpose: the shim is a thin import
declaration, not a model of the full d3-force interface. The actual
nodes carry `TaxonomyNode` shape, which the call site narrows.)

**Pre-measurement.** Each node needs a `labelW` and `labelH`
populated once before the simulation reads them. Build a single
hidden `OffscreenCanvas` (or `document.createElement('canvas')` if
OffscreenCanvas isn't typed cleanly) at module scope inside
[shapeData.ts](web/src/components/taxonomy/shapeData.ts), set the
font to the production label font (`9px 'Cinzel', serif` in canvas
units — see "Font sizing" below), then for each row in
`viewRowsToGraph`:

```ts
const m = measureCtx.measureText(row.display_name);
node.labelW = m.width;
node.labelH = 11;          // approximate Cinzel cap-height + descender at 9px
```

Cache results so re-running on the same `display_name` is free.
`labelW`/`labelH` become non-optional fields on the `TaxonomyNode`
type (which is currently `= TaxonomyViewRow`). Add them as a
secondary intersection type so `TaxonomyViewRow` itself stays a
pure DB shape:

```ts
export interface TaxonomyNode extends TaxonomyViewRow {
  labelW: number;
  labelH: number;
}
```

`viewRowsToGraph` returns the populated `TaxonomyNode`s.

**Collide force install.** In [ForceCanvas.tsx](web/src/components/taxonomy/ForceCanvas.tsx),
after the `useImperativeHandle` block, an effect installs the new
collide force once the inner ref is ready:

```ts
useEffect(() => {
  const fg = inner.current;
  if (!fg) return;
  const PAD = 4;
  fg.d3Force(
    'collide',
    bboxCollide((n: TaxonomyNode) => {
      const r = nodeRadius(n);
      const halfW = n.labelW / 2 + r + PAD;
      const halfH = n.labelH / 2 + r + PAD;
      return [[-halfW, -halfH], [halfW, halfH]];
    }).iterations(2),
  );
  fg.d3Force('center', null);
  const charge = fg.d3Force('charge') as { strength(s: number): unknown } | undefined;
  charge?.strength(-120);
}, []);
```

The bbox is centred on the node (label drawn centred underneath the
dot, see "Drawing" below; the bbox is a vertical-axis-symmetric
rectangle that's loose by `r + PAD` on every side). This is
deliberately conservative — the rectangle is taller than the actual
label-plus-dot stack, so the simulation reserves a bit of slack
that the human eye reads as "well-spaced."

**Drawing.** In `nodeCanvasObject`, after `drawNode(n, ctx)`:

```ts
const SHOW_LABEL_AT = 1.2;
if (globalScale > SHOW_LABEL_AT) {
  ctx.font = "9px 'Cinzel', serif";
  ctx.fillStyle = TX_BROWN_FAINT;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  ctx.fillText(n.display_name, n.x, n.y + nodeRadius(n) + 3);
}
```

The font size is in canvas units, NOT divided by `globalScale`. This
is intentional and matches the bbox-collide configuration: the
simulation reserves space sized for `9px` at canvas units, so when
the label draws it fits exactly the reserved space at the chosen
zoom.

The label colour `TX_BROWN_FAINT` (`#7a5520`) is a muted gold that
sits between gold ring and brown ink — it reads as engraving on
walnut, not as UI chrome. The `dimmedIds` `globalAlpha` already in
place wraps `drawNode`; extend it to wrap the label draw too so
filtered-out nodes' names also dim.

**Why no per-frame collision pass.** The bbox-collide force does
its work as part of the simulation tick. By the time the canvas
draws, nodes are already separated by enough distance that their
labels don't overlap each other or other nodes. There's no
per-render collision check, no quadtree built per frame, no labels
to skip — the layout simply *is* label-aware.

**Cost.** At 166 nodes, `d3-bboxCollide` is cheap (its quadtree is
the same shape `forceCollide` uses today). The added per-tick cost
is ~1 ms; well under one frame budget.

**Tradeoff.** The graph is more spread out than today, even at
fit-zoom when labels aren't drawn. The curator agreed this is the
right tradeoff: any zoom level "just works" with labels appearing
naturally, no rearrangement.

### F. "Gray fill" → "gray"

The string change in section D's legend body (`gray fill =` →
`gray =`) is the entire fix. The drawing of null-role nodes (gray
fill) is unchanged.

## File-level impact

- **[ForceCanvas.tsx](web/src/components/taxonomy/ForceCanvas.tsx)** —
  add a `useEffect` that installs `bboxCollide`, nulls `center`,
  bumps `charge` strength; cluster-aware ring colour in `drawNode`
  (delete the cluster-halo block); label draw inside
  `nodeCanvasObject` gated on `globalScale`.
- **[palette.ts](web/src/components/taxonomy/palette.ts)** —
  retarget `ROLE_FILL.expression` to deep teal; add
  `TX_CLUSTER_RING` constant.
- **[taxonomy.css](web/src/components/taxonomy/taxonomy.css)** —
  update `--tx-expression` to deep teal.
- **[shapeData.ts](web/src/components/taxonomy/shapeData.ts)** —
  add `labelW` / `labelH` to a new `TaxonomyNode` interface that
  extends `TaxonomyViewRow`; populate via `ctx.measureText` in
  `viewRowsToGraph`.
- **[Legend.tsx](web/src/components/taxonomy/Legend.tsx)** —
  rewrite italic block; drop self-positioning styles.
- **[Taxonomy.tsx](web/src/pages/Taxonomy.tsx)** — wrap
  `<Legend />` and the card IIFE in a flex column container.
- **`web/src/types/d3-bboxCollide.d.ts`** — new file; one-line
  module declaration shim.
- **`web/package.json`** — add `d3-bboxCollide` dependency.
- Tests: existing tests for shapeData need to accept the
  `labelW`/`labelH` fields (the `baseRow` fixture grows two
  fields). NodeCard tests are unaffected. Legend has no test today
  and stays untested. ForceCanvas has no test today (canvas
  rendering doesn't unit-test cleanly); the visual change is
  verified in-browser.

## Risks / things to watch

- **Pre-measurement font drift.** The label font is hard-coded as
  `9px 'Cinzel', serif` in two places (the offscreen measurement
  context and the draw call). They MUST stay in lockstep — if the
  draw uses a different size or family, the bbox reservation no
  longer matches and labels can clip. Codify by extracting a
  `LABEL_FONT = "9px 'Cinzel', serif"` constant and using it
  in both places.
- **Cinzel may not be loaded yet at first render.** The offscreen
  measurement uses whatever the browser has at that instant. If
  Cinzel hasn't loaded, the measurer falls back to serif metrics,
  which are usually a couple px wider — the bbox reservation ends
  up *bigger* than the actual draw. That's the safe direction
  (slack, not clip). Worth verifying in practice; if it produces
  too much spread on cold loads, we add a `document.fonts.ready`
  await before populating measurements.
- **Initial layout bounciness.** Adding bbox-collide on first
  simulation tick with the default initial positions (random in a
  small radius around centre) can cause noticeable jitter for
  ~250 ms before settling. Acceptable; if it bothers the curator,
  raise `cooldownTicks` or pre-position via a hand-rolled circle
  pack on first render.
- **Bumped charge interacting with link springs.** With `−120`
  charge and the existing default link strength, tightly-connected
  sub-trees could stretch. If so, raise link strength via
  `fg.d3Force('link')!.strength(0.7)` (or similar). Not specified
  ahead of time — adjust if visually wrong at implementation.
- **`d3-bboxCollide` is frozen since 2018.** It's stable code on a
  stable d3-force quadtree API. If npm install ever breaks because
  d3-force changes its node-array contract, the fix is to vendor
  the ~200-line force into our repo. Don't pre-empt; act on
  breakage.
- **Type shim looseness.** The `.d.ts` shim types `bboxCollide` as
  taking `(node: unknown) => …`. The call site narrows to
  `TaxonomyNode`. If a future caller passes the wrong shape, the
  shim won't catch it. Acceptable: only ForceCanvas uses
  bboxCollide in this repo.

## Out of scope (logged for follow-up)

- Renaming `taxonomy_nodes.role` and `role_default` (separate
  worktree).
- Showing antichain-invariant violations on the canvas.
- Hover-card auto-dismiss when the cursor lingers on the canvas
  background after a pinned-card dismiss (final reviewer flagged
  this in the prior round; punt to whenever it actually annoys
  the curator).
- Per-component initial positioning (vs. random-around-centre).
- Replacing the offscreen `measureText` cache with a font-load
  await unless cold-load measurement drift becomes visible.
