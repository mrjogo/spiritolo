# Taxonomy Graph UI — Layout, Color, and Labels — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land round 2 of curator UI changes: catch the web code up to PR #38's column rename (`role` → `node_kind`, `role_default` → `default_role`), drop the centring force so disconnected components stop stacking, swap expression to deep teal and clustering ring to rust, stack the legend + node card in one flex column, draw node labels with anti-overlap via `d3-bboxCollide`, and rewrite the legend.

**Architecture:** All changes live in `web/src/components/taxonomy/` plus `web/src/pages/Taxonomy.tsx` and one supabase migration. New dependency: `d3-bboxCollide` (frozen 2018, stable, ~200 lines on a stable d3-force quadtree API). The biggest piece is making the simulation label-aware — once each node's bbox includes its label rectangle, the existing force machinery does the spacing for us; no per-frame collision pass.

**Tech Stack:** React 19, TypeScript 6, Vite, Vitest, `react-force-graph-2d` 1.29, `d3-bboxCollide` ^1.0.4.

**Spec:** [docs/superpowers/specs/2026-05-02-taxonomy-graph-ui-layout-and-labels-design.md](docs/superpowers/specs/2026-05-02-taxonomy-graph-ui-layout-and-labels-design.md)

---

## Conventions

- Repo root: `/workspaces/spiritolo`. All commands run from there unless otherwise noted.
- Web tests: `cd web && npm test -- <vitest pattern>`. Bare `npm test` runs the full suite (`vitest run`).
- TypeScript build: `cd web && npm run build`.
- Lint: `cd web && npm run lint`.
- Branch: `claude/taxonomy-graph-ui-4e67` (continued from round 1; do NOT push, do NOT branch elsewhere). Origin/main was just merged in (`faffa7a`); the new spec sits at `7eb7e62`.
- Commit subject style: `Taxonomy: <imperative subject>`.

---

## Task 0 — Catch the web code up to `node_kind` / `default_role`

**Why:** PR #38 renamed `taxonomy_nodes.role` → `node_kind` and `role_default` → `default_role`. The merge brought the migration into this branch, but the web code still selects and reads the old column names. First query at runtime would error. The interim NodeCard labels ("Role (taxonomy)" / "Default Role (recipe ingredient)") simplify in step with the rename: now that the columns have unambiguous names, the labels can match.

**Files:**
- Modify: `supabase/migrations/20260501120000_create_taxonomy_public.sql`
- Modify: `web/src/components/taxonomy/shapeData.ts`
- Modify: `web/src/components/taxonomy/shapeData.test.ts`
- Modify: `web/src/components/taxonomy/NodeCard.tsx`
- Modify: `web/src/components/taxonomy/NodeCard.test.tsx`
- Modify: `web/src/pages/Taxonomy.tsx`

- [ ] **Step 1: Update the `taxonomy_public` view migration**

In `supabase/migrations/20260501120000_create_taxonomy_public.sql`, replace `n.role,` and `n.role_default,` (lines 15–16) with `n.node_kind,` and `n.default_role,` respectively, and update the column-grants list at the bottom (line 46) from `id, slug, display_name, role, role_default,` to `id, slug, display_name, node_kind, default_role,`.

- [ ] **Step 2: Update `shapeData.ts`**

In `web/src/components/taxonomy/shapeData.ts`:

a) Rename the `TaxonomyViewRow` fields:

```ts
export interface TaxonomyViewRow {
  id: number;
  slug: string;
  display_name: string;
  node_kind: 'brand' | 'expression' | null;
  default_role: string | null;
  is_cluster_node: boolean;
  is_defining_garnish: boolean;
  parent_ids: number[];
  child_ids: number[];
  aliases: string[];
  recipe_count: number;
}
```

b) Rename the `effectiveRole` function to `effectiveKind`, and replace its body:

```ts
export function effectiveKind(node: TaxonomyViewRow): TaxonomyRole {
  return (node.node_kind ?? 'unknown') as TaxonomyRole;
}
```

(`TaxonomyRole` keeps its name and contents — `'brand' | 'expression' | 'substance' | 'unknown'` — since this is the role-kind enum, conceptually identical to `node_kind` plus an "unknown" sentinel.)

c) Update `rowMatchesFilters`'s role-chip branch to call `effectiveKind` instead of `effectiveRole`.

- [ ] **Step 3: Update `shapeData.test.ts`**

In `web/src/components/taxonomy/shapeData.test.ts`:

a) Replace `effectiveRole` with `effectiveKind` in the import list at the top.

b) Update the `baseRow` test fixture's field names:

```ts
const baseRow: TaxonomyViewRow = {
  id: 1,
  slug: 'whiskey',
  display_name: 'Whiskey',
  node_kind: null,
  default_role: 'substance',
  is_cluster_node: true,
  is_defining_garnish: false,
  parent_ids: [],
  child_ids: [2, 3],
  aliases: ['whisky'],
  recipe_count: 12,
};
```

c) Update the `describe('effectiveRole', …)` block — rename it to `describe('effectiveKind', …)` and replace `effectiveRole` and `role:` / `role_default:` mentions inside:

```ts
describe('effectiveKind', () => {
  it('returns node_kind when set', () => {
    expect(effectiveKind({ ...baseRow, node_kind: 'expression', default_role: null })).toBe('expression');
  });

  it('returns "unknown" when node_kind is null, regardless of default_role', () => {
    expect(effectiveKind({ ...baseRow, node_kind: null, default_role: 'modifier' })).toBe('unknown');
    expect(effectiveKind({ ...baseRow, node_kind: null, default_role: null })).toBe('unknown');
  });
});
```

d) Update the two `rowMatchesFilters` test cases that currently set `role: 'expression'` to set `node_kind: 'expression'` instead:

```ts
  it('matches a role-chip via effectiveKind (kind asserted)', () => {
    const row: TaxonomyViewRow = { ...baseRow, node_kind: 'expression' };
    expect(rowMatchesFilters(row, new Set<FilterKey>(['expression']))).toBe(true);
    expect(rowMatchesFilters(row, new Set<FilterKey>(['substance']))).toBe(false);
  });

  it('AND-combines: substance + expression matches nothing', () => {
    const row: TaxonomyViewRow = { ...baseRow, node_kind: 'expression' };
    expect(rowMatchesFilters(row, new Set<FilterKey>(['substance', 'expression']))).toBe(false);
  });
```

- [ ] **Step 4: Update `NodeCard.tsx` and `NodeCard.test.tsx`**

In `web/src/components/taxonomy/NodeCard.tsx`:

a) Replace these two `<Row …/>` lines:

```tsx
<Row label="Role (taxonomy)" value={node.role ?? '—'} />
<Row label="Default Role (recipe ingredient)" value={node.role_default ?? '—'} />
```

with:

```tsx
<Row label="Node kind" value={node.node_kind ?? '—'} />
<Row label="Default ingredient role" value={node.default_role ?? '—'} />
```

In `web/src/components/taxonomy/NodeCard.test.tsx`:

b) Update the test fixture (lines 8–13) to use the new field names:

```tsx
const node: TaxonomyNode = {
  id: 1, slug: 'rye_whiskey', display_name: 'Rye Whiskey',
  node_kind: 'expression', default_role: 'modifier',
  is_cluster_node: true, is_defining_garnish: false,
  parent_ids: [10, 11], child_ids: [20, 21],
  aliases: ['rye', 'rye whisky'], recipe_count: 47,
};
```

c) Update the label-assertion test:

```tsx
it('renders the node properties with the renamed labels', () => {
  render(<NodeCard node={node} mode="pinned" onDismiss={() => {}} />);
  expect(screen.getByText('RYE WHISKEY')).toBeInTheDocument();
  expect(screen.getByText(/47 drinks call for this/i)).toBeInTheDocument();
  expect(screen.getByText(/rye, rye whisky/)).toBeInTheDocument();
  expect(screen.getByText(/node kind/i)).toBeInTheDocument();
  expect(screen.getByText(/default ingredient role/i)).toBeInTheDocument();
  expect(screen.getByText(/clustering node/i)).toBeInTheDocument();
});
```

- [ ] **Step 5: Update `Taxonomy.tsx`'s `COLUMNS` constant**

In `web/src/pages/Taxonomy.tsx` (line ~31):

```ts
const COLUMNS =
  'id, slug, display_name, node_kind, default_role, ' +
  'is_cluster_node, is_defining_garnish, ' +
  'parent_ids, child_ids, aliases, recipe_count';
```

- [ ] **Step 6: Apply the migration locally and verify against the live DB**

If you have access to a local Supabase (host-side per CLAUDE.md), run:

```bash
DB_URL='postgresql://postgres:postgres@192.168.65.254:54322/postgres?sslmode=disable'
supabase migration up --db-url "$DB_URL" --include-all
```

If you don't have host-side Supabase access, skip this step — the build/test gates below are sufficient for the curator's local verification.

- [ ] **Step 7: Run gates**

```bash
cd web && npm run build && npm test && npm run lint
```

Expected: all green. Test count should match the prior round's 134.

- [ ] **Step 8: Commit**

```bash
git add supabase/migrations/20260501120000_create_taxonomy_public.sql \
        web/src/components/taxonomy/shapeData.ts \
        web/src/components/taxonomy/shapeData.test.ts \
        web/src/components/taxonomy/NodeCard.tsx \
        web/src/components/taxonomy/NodeCard.test.tsx \
        web/src/pages/Taxonomy.tsx
git commit -m "Taxonomy: catch web code up to node_kind / default_role rename"
```

---

## Task 1 — Palette swap: deep-teal expression, rust clustering ring

**Why:** "Extra ring = clustering node" was too subtle (a thin halo on top of the gold ring). Replace with a different ring colour. The natural pick is the rust the expression fill currently occupies; expression moves to deep teal so the colours stay distinct.

**Files:**
- Modify: `web/src/components/taxonomy/palette.ts`
- Modify: `web/src/components/taxonomy/taxonomy.css`
- Modify: `web/src/components/taxonomy/ForceCanvas.tsx`

- [ ] **Step 1: Update `palette.ts`**

In `web/src/components/taxonomy/palette.ts`:

a) Add a new constant after `TX_GOLD`:

```ts
export const TX_CLUSTER_RING = '#a85b3a';   // rust — was the prior expression fill
```

b) Update the expression entry in `ROLE_FILL`:

```ts
export const ROLE_FILL: Record<TaxonomyRole, string> = {
  substance:  '#e8d9b0',
  expression: '#3a6b6e',                    // was #a85b3a; rust moved to TX_CLUSTER_RING
  brand:      '#7a9a82',
  unknown:    '#888888',
};
```

- [ ] **Step 2: Update the matching CSS variable**

In `web/src/components/taxonomy/taxonomy.css`, change the `--tx-expression` line:

```css
  --tx-expression: #3a6b6e;
```

- [ ] **Step 3: Update `ForceCanvas.tsx`'s `drawNode`**

In `web/src/components/taxonomy/ForceCanvas.tsx`:

a) Add `TX_CLUSTER_RING` to the palette imports.

b) Delete the entire cluster-halo block in `drawNode`:

```ts
// DELETE this block:
if (node.is_cluster_node) {
  ctx.beginPath();
  ctx.arc(node.x, node.y, haloR, 0, 2 * Math.PI);
  ctx.strokeStyle = TX_GOLD;
  ctx.lineWidth = 0.4;
  ctx.stroke();
}
```

c) Replace the gold-ring stroke colour with a kind-aware ternary:

```ts
// BEFORE:
ctx.beginPath();
ctx.arc(node.x, node.y, outerR, 0, 2 * Math.PI);
ctx.strokeStyle = TX_GOLD;
ctx.lineWidth = 1.0;
ctx.stroke();

// AFTER:
ctx.beginPath();
ctx.arc(node.x, node.y, outerR, 0, 2 * Math.PI);
ctx.strokeStyle = node.is_cluster_node ? TX_CLUSTER_RING : TX_GOLD;
ctx.lineWidth = 1.0;
ctx.stroke();
```

d) The local `haloR` constant is now unused. Delete its declaration line.

- [ ] **Step 4: Gates**

```bash
cd web && npm run build && npm test
```

Expected: green.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/taxonomy/palette.ts \
        web/src/components/taxonomy/taxonomy.css \
        web/src/components/taxonomy/ForceCanvas.tsx
git commit -m "Taxonomy: deep-teal expression, rust clustering ring"
```

---

## Task 2 — Stack legend + node card in one flex column

**Why:** The card overlaps the legend at narrow heights or when the legend wraps. A single flex column container places the card under the legend automatically — no measurement.

**Files:**
- Modify: `web/src/components/taxonomy/Legend.tsx`
- Modify: `web/src/components/taxonomy/NodeCard.tsx`
- Modify: `web/src/pages/Taxonomy.tsx`

- [ ] **Step 1: Strip self-positioning from `Legend.tsx`**

In `web/src/components/taxonomy/Legend.tsx`, remove the `position: absolute, top: 14, right: 14, zIndex: 2` keys from the root `<div>`'s `style`. Keep the rest (`padding`, `fontSize`, `lineHeight`, `width`):

```tsx
<div
  className="tx-card"
  style={{
    padding: '8px 12px', fontSize: 12, lineHeight: 1.55, width: 180,
  }}
>
```

- [ ] **Step 2: Strip self-positioning from `NodeCard.tsx`**

In `web/src/components/taxonomy/NodeCard.tsx`, remove the `position: absolute, top: 150, right: 14, zIndex: 4` keys from the `<aside>`'s `style`. Keep `width: 240` and `padding: '20px 18px'`:

```tsx
<aside
  className="tx-card"
  role={mode === 'pinned' ? 'dialog' : 'tooltip'}
  aria-label={`Taxonomy node: ${node.display_name}`}
  style={{ width: 240, padding: '20px 18px' }}
>
```

- [ ] **Step 3: Wrap both in a flex column in `Taxonomy.tsx`**

In `web/src/pages/Taxonomy.tsx`, find the existing renders of `<Legend />` and the IIFE that renders the card. Replace BOTH (they currently sit at separate positions in the JSX) with a single positioned wrapper:

```tsx
<div
  style={{
    position: 'absolute', top: 14, right: 14, zIndex: 3,
    display: 'flex', flexDirection: 'column', gap: 12,
  }}
>
  <Legend />
  {(() => {
    if (focusedNode) {
      return <NodeCard node={focusedNode} mode="pinned" onDismiss={() => setFocusedId(null)} />;
    }
    if (hovered) {
      return <NodeCard node={hovered} mode="hover" onDismiss={() => {}} />;
    }
    return null;
  })()}
</div>
```

The standalone `<Legend />` render and the standalone IIFE that previously rendered the card are removed; the wrapper above replaces both.

- [ ] **Step 4: Gates**

```bash
cd web && npm run build && npm test
```

Expected: green. NodeCard and Legend tests do not assert positioning, so no test churn here.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/taxonomy/Legend.tsx \
        web/src/components/taxonomy/NodeCard.tsx \
        web/src/pages/Taxonomy.tsx
git commit -m "Taxonomy: stack legend + node card in one flex column"
```

---

## Task 3 — Rewrite the legend (third revision)

**Why:** With the rust-ring treatment, the "extra ring" line goes away. With the renamed columns, "role (taxonomy) not set" becomes "node kind not set". The arrow line is also dropped (curator gets it without a legend hint).

**Files:**
- Modify: `web/src/components/taxonomy/Legend.tsx`

- [ ] **Step 1: Replace the italic block**

In `web/src/components/taxonomy/Legend.tsx`, replace the current italic block (which has three lines: `extra ring = clustering node`, `gray fill = role (taxonomy) not set`, `arrow = parent → child`) with two:

```tsx
<div style={{ marginTop: 4, fontStyle: 'italic', color: TX_BROWN_SOFT, lineHeight: 1.4 }}>
  ◯ rust ring = clustering node<br />
  ◯ gray = node kind not set
</div>
```

The width was bumped from 160 → 180 in round 1 to fit the longest italic line; keep it at 180.

- [ ] **Step 2: Gates**

```bash
cd web && npm run build && npm test
```

Expected: green.

- [ ] **Step 3: Commit**

```bash
git add web/src/components/taxonomy/Legend.tsx
git commit -m "Taxonomy: rewrite legend (rust-ring line, drop arrow line, node kind language)"
```

---

## Task 4 — Drop centring force; bump charge

**Why:** Disconnected components currently pile up because `forceCenter` pulls every node to a single point. Removing the centre force lets charge push them apart.

**Files:**
- Modify: `web/src/components/taxonomy/ForceCanvas.tsx`

- [ ] **Step 1: Add an effect that nulls `'center'` and bumps `'charge'`**

In `web/src/components/taxonomy/ForceCanvas.tsx`, after the existing `useImperativeHandle` block, add:

```ts
useEffect(() => {
  const fg = inner.current;
  if (!fg) return;
  fg.d3Force('center', null);
  // d3-force's charge accessor returns ForceFn | undefined; the underlying
  // forceManyBody() exposes .strength(). Cast narrowly to that shape.
  const charge = fg.d3Force('charge') as { strength(s: number): unknown } | undefined;
  charge?.strength(-120);
}, []);
```

(The same effect grows another statement in Task 5 to install the bbox-collide force. Don't pre-empt — Task 5 owns that line.)

- [ ] **Step 2: Gates**

```bash
cd web && npm run build && npm test
```

Expected: green. No tests exercise the simulation, so this is a visual change verified later.

- [ ] **Step 3: Commit**

```bash
git add web/src/components/taxonomy/ForceCanvas.tsx
git commit -m "Taxonomy: drop centring force; bump charge to -120"
```

---

## Task 5 — Pre-measure label bboxes; install `d3-bboxCollide`

**Why:** Bake each node's label rectangle into the simulation's collision shape so the layout naturally reserves room for labels without a per-frame collision pass.

**Files:**
- Modify: `web/package.json`
- Create: `web/src/types/d3-bboxCollide.d.ts`
- Modify: `web/src/components/taxonomy/shapeData.ts`
- Modify: `web/src/components/taxonomy/shapeData.test.ts`
- Modify: `web/src/components/taxonomy/ForceCanvas.tsx`

- [ ] **Step 1: Add the dependency**

```bash
cd web && npm install d3-bboxCollide@^1.0.4
```

This updates `web/package.json` and `web/package-lock.json`. Verify the version landed: `grep d3-bboxCollide web/package.json`.

- [ ] **Step 2: Add a type shim**

Create `web/src/types/d3-bboxCollide.d.ts`:

```ts
declare module 'd3-bboxCollide' {
  type Bounds = [[number, number], [number, number]];
  interface BboxForce {
    iterations(n: number): BboxForce;
    initialize(nodes: unknown[]): void;
    (alpha: number): void;
  }
  export function bboxCollide(bbox: (node: unknown) => Bounds): BboxForce;
}
```

(Loose `unknown` typing is intentional: ForceCanvas narrows to `TaxonomyNode` at the call site.)

- [ ] **Step 3: Add `labelW` / `labelH` to the node shape and populate them in `viewRowsToGraph`**

In `web/src/components/taxonomy/shapeData.ts`:

a) Replace the `TaxonomyNode = TaxonomyViewRow` alias with a proper interface that adds the two label dimensions:

```ts
export interface TaxonomyNode extends TaxonomyViewRow {
  labelW: number;
  labelH: number;
}
```

b) Add a module-scoped measurement context near the top of the file (after imports, before exports):

```ts
const LABEL_FONT = "9px 'Cinzel', serif";
const LABEL_HEIGHT = 11;  // approx Cinzel cap+descender at 9px

let measureCtx: CanvasRenderingContext2D | null = null;
function getMeasureCtx(): CanvasRenderingContext2D {
  if (measureCtx) return measureCtx;
  const c = document.createElement('canvas');
  const ctx = c.getContext('2d');
  if (!ctx) throw new Error('canvas 2d context unavailable');
  ctx.font = LABEL_FONT;
  measureCtx = ctx;
  return ctx;
}
```

c) Update `viewRowsToGraph` to populate the new fields:

```ts
export function viewRowsToGraph(rows: TaxonomyViewRow[]): {
  nodes: TaxonomyNode[];
  links: TaxonomyLink[];
} {
  const ctx = getMeasureCtx();
  const nodes: TaxonomyNode[] = rows.map((r) => ({
    ...r,
    labelW: ctx.measureText(r.display_name).width,
    labelH: LABEL_HEIGHT,
  }));
  const links: TaxonomyLink[] = [];
  for (const row of rows) {
    for (const childId of row.child_ids) {
      links.push({ source: row.id, target: childId });
    }
  }
  return { nodes, links };
}
```

d) Export `LABEL_FONT` and `LABEL_HEIGHT` so ForceCanvas can keep its label-draw font in lockstep with the measurement font:

```ts
export { LABEL_FONT, LABEL_HEIGHT };
```

(Place the export at the same level as the constants — direct named exports work too. Use whichever syntax matches the file's existing patterns.)

- [ ] **Step 4: Update `shapeData.test.ts`**

Two test concerns:

a) **`baseRow` fixture.** Add `labelW` and `labelH` (any plausible numbers will do — the fixture doesn't test measurement). Keep them as plain literals; the cast `as TaxonomyViewRow` widens to the parent type, so the `TaxonomyNode`-only fields are extra and harmless to other tests:

```ts
const baseRow: TaxonomyViewRow = {
  id: 1,
  slug: 'whiskey',
  display_name: 'Whiskey',
  node_kind: null,
  default_role: 'substance',
  is_cluster_node: true,
  is_defining_garnish: false,
  parent_ids: [],
  child_ids: [2, 3],
  aliases: ['whisky'],
  recipe_count: 12,
};
```

(`baseRow` is `TaxonomyViewRow`, not `TaxonomyNode`; it does NOT need the label fields. Tests that need `TaxonomyNode` already construct their own nodes elsewhere.)

b) **`viewRowsToGraph` test.** The existing tests check that `nodes` mirrors rows and that links are correctly emitted. Add a separate test that verifies `labelW` is populated and positive:

```ts
it('populates labelW and labelH on each node', () => {
  const rows: TaxonomyViewRow[] = [
    { ...baseRow, id: 1, slug: 'whiskey', display_name: 'Whiskey', child_ids: [] },
  ];
  const { nodes } = viewRowsToGraph(rows);
  expect(nodes[0].labelW).toBeGreaterThan(0);
  expect(nodes[0].labelH).toBeGreaterThan(0);
});
```

(jsdom's `canvas.getContext('2d')` returns a stub that supports `measureText`. Confirm by running the test. If jsdom's stub is missing `measureText`, the test will throw with a clear error — in that case, add a small mock at the top of the file:

```ts
beforeAll(() => {
  if (!HTMLCanvasElement.prototype.getContext) return;
  const ctx = HTMLCanvasElement.prototype.getContext('2d') as CanvasRenderingContext2D | null;
  if (ctx && typeof ctx.measureText !== 'function') {
    ctx.measureText = ((text: string) => ({ width: text.length * 6 } as TextMetrics));
  }
});
```

Don't add the mock pre-emptively — only if needed.)

- [ ] **Step 5: Install `bboxCollide` in ForceCanvas**

In `web/src/components/taxonomy/ForceCanvas.tsx`:

a) Add the import:

```ts
import { bboxCollide } from 'd3-bboxCollide';
```

b) Extend the effect from Task 4 (the one that nulls `center` and bumps `charge`) to also install the bbox-collide force:

```ts
useEffect(() => {
  const fg = inner.current;
  if (!fg) return;

  fg.d3Force('center', null);

  const charge = fg.d3Force('charge') as { strength(s: number): unknown } | undefined;
  charge?.strength(-120);

  const PAD = 4;
  fg.d3Force(
    'collide',
    bboxCollide((node: unknown) => {
      const n = node as TaxonomyNode;
      const r = nodeRadius(n);
      const halfW = n.labelW / 2 + r + PAD;
      const halfH = n.labelH / 2 + r + PAD;
      return [[-halfW, -halfH], [halfW, halfH]];
    }).iterations(2),
  );
}, []);
```

`nodeRadius` is already imported via the palette module.

- [ ] **Step 6: Gates**

```bash
cd web && npm run build && npm test
```

Expected: green. The new `viewRowsToGraph` label-fields test passes if jsdom supports `measureText`; otherwise add the mock from step 4(b) and re-run.

- [ ] **Step 7: Commit**

```bash
git add web/package.json web/package-lock.json \
        web/src/types/d3-bboxCollide.d.ts \
        web/src/components/taxonomy/shapeData.ts \
        web/src/components/taxonomy/shapeData.test.ts \
        web/src/components/taxonomy/ForceCanvas.tsx
git commit -m "Taxonomy: install d3-bboxCollide; bake label bboxes into simulation"
```

---

## Task 6 — Draw the labels in `nodeCanvasObject`

**Why:** With the bbox baked into the collide force, nodes are spaced for their labels. Now actually draw the text, gated on a zoom threshold so labels disappear when too small to read.

**Files:**
- Modify: `web/src/components/taxonomy/ForceCanvas.tsx`

- [ ] **Step 1: Draw labels gated on zoom**

In `web/src/components/taxonomy/ForceCanvas.tsx`, extend `nodeCanvasObject`. Use the `LABEL_FONT` and `LABEL_HEIGHT` exports from `shapeData.ts` to keep draw + measurement in lockstep.

a) Add to the import line that already pulls from `./shapeData`:

```ts
import {
  effectiveKind,
  type TaxonomyNode,
  type TaxonomyLink,
  LABEL_FONT,
  LABEL_HEIGHT,
} from './shapeData';
```

(Import names must match what Task 0 left in `shapeData.ts`; if the file uses `effectiveRole`/`effectiveKind` differently after Task 0, match its actual exports.)

b) Add `TX_BROWN_FAINT` to the palette imports if not already present.

c) Define a zoom threshold near the other drawing constants:

```ts
const SHOW_LABEL_AT = 1.2;
```

d) Extend the `nodeCanvasObject` callback:

```tsx
nodeCanvasObject={(node, ctx, globalScale) => {
  const n = node as TaxonomyNode & { x: number; y: number };
  const dimmed = dimmedIds?.has(n.id) ?? false;
  ctx.globalAlpha = dimmed ? 0.18 : 1;
  drawNode(n, ctx);
  if (globalScale > SHOW_LABEL_AT) {
    ctx.font = LABEL_FONT;
    ctx.fillStyle = TX_BROWN_FAINT;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillText(n.display_name, n.x, n.y + nodeRadius(n) + 3);
  }
  ctx.globalAlpha = 1;
}}
```

The dimmed-alpha wrap continues to cover both node and label.

- [ ] **Step 2: Gates**

```bash
cd web && npm run build && npm test
```

Expected: green.

- [ ] **Step 3: Commit**

```bash
git add web/src/components/taxonomy/ForceCanvas.tsx
git commit -m "Taxonomy: draw node labels under the dot, zoom-gated"
```

---

## Task 7 — Final verification

**Why:** End-to-end gate before merge.

- [ ] **Step 1: Full test suite**

```bash
cd web && npm test
```

Expected: PASS.

- [ ] **Step 2: Build**

```bash
cd web && npm run build
```

Expected: clean.

- [ ] **Step 3: Lint**

```bash
cd web && npm run lint
```

Expected: clean.

- [ ] **Step 4: Manual end-to-end smoke (controller does this; not in subagent scope)**

(Skipped for subagent execution — the controller / curator does the visual verification.)

---

## Self-Review Notes

The plan covers every requirement from the spec:

- §A "Drop the centring force; bump charge" → Task 4.
- §B "Palette swap" → Task 1.
- §C "Stack legend and node card in one flex column" → Task 2.
- §D "Legend rewrite (third revision)" → Task 3.
- §E "Node labels via d3-bboxCollide" → Tasks 5 + 6.
- §F "Gray fill → gray" → covered by Task 3's italic-block rewrite.
- "Adjacent change merged in: node_kind / default_role rename" → Task 0.

Type/method consistency:
- `effectiveRole` → `effectiveKind` rename happens in Task 0 and propagates through Task 6's import.
- `TaxonomyNode` extends `TaxonomyViewRow` (Task 5) — `baseRow` fixture stays typed as `TaxonomyViewRow` so existing test sites don't need to grow `labelW`/`labelH`.
- `LABEL_FONT` / `LABEL_HEIGHT` exported from `shapeData.ts` (Task 5) and consumed by ForceCanvas (Task 6) — single source of truth so measurement and draw font stay locked.
- `bboxCollide` import path is `d3-bboxCollide` (matches the npm package name and the `.d.ts` shim's module name).
- `nodeRadius` is in `palette.ts`; ForceCanvas already imports it. No new imports needed.

Tasks 4, 5, 6 all touch the same `useEffect` and `nodeCanvasObject` in ForceCanvas. Task 4 introduces the effect; Task 5 extends it with one statement; Task 6 doesn't touch the effect at all (only `nodeCanvasObject`). Each task's diff stays focused.
