# Taxonomy Graph UI — Curator-Pass Cleanup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clean up the taxonomy graph UI so the (single) curator can read it without legend confusion or label collisions: drop the `?` glyph, fix a `role`/`role_default` fallback bug, drop the dashed orphan ring, add directional arrows on edges, merge hover and click into a single auto-height node card with an X button, and rewrite the legend.

**Architecture:** No new components or libraries. Edits are confined to `web/src/components/taxonomy/` and `web/src/pages/Taxonomy.tsx`. The biggest change is renaming `SpecimenCard` to a more general `NodeCard` that handles both transient (hover) and pinned (click) modes from one component, and moving its render up into the `Taxonomy` page where focus state already lives. Test stack stays Vitest + Testing Library.

**Tech Stack:** React 19, TypeScript 6, Vite, Vitest, `@testing-library/react`, `@testing-library/user-event`, `react-force-graph-2d` 1.29.

**Spec:** [docs/superpowers/specs/2026-05-01-taxonomy-graph-ui-curator-pass-design.md](docs/superpowers/specs/2026-05-01-taxonomy-graph-ui-curator-pass-design.md)

---

## Conventions

- All commands run from the repo root (`/workspaces/spiritolo`) unless otherwise noted.
- Web tests run with `cd web && npm test -- <vitest pattern>`. The `npm test` script invokes `vitest run` (non-watch).
- TypeScript build check: `cd web && npm run build` (runs `tsc -b` then `vite build`).
- Lint: `cd web && npm run lint`.
- Each task ends with a commit on the current branch (`claude/taxonomy-graph-ui-4e67`). Use the imperative-mood, prefix-style commit subjects already used on the branch (`Taxonomy: <subject>`).

---

## Task 1 — Fix `effectiveRole`, drop `role_default` fallback, broaden type

**Why:** `effectiveRole` currently falls back from `role` to `role_default`, but `role_default` holds *recipe-position* roles (`'modifier'`, `'bitters'`, …), not taxonomy *type* roles. The fallback returns nonsensical values and causes the canvas-fill bug the curator saw as "substance nodes look empty."

**Files:**
- Modify: [web/src/components/taxonomy/shapeData.ts](web/src/components/taxonomy/shapeData.ts)
- Modify: [web/src/components/taxonomy/shapeData.test.ts](web/src/components/taxonomy/shapeData.test.ts)

- [ ] **Step 1: Update the failing tests in `shapeData.test.ts`**

Replace the `describe('effectiveRole', …)` block with:

```ts
describe('effectiveRole', () => {
  it('returns role when set', () => {
    expect(effectiveRole({ ...baseRow, role: 'expression', role_default: null })).toBe('expression');
  });

  it('returns "unknown" when role is null, regardless of role_default', () => {
    expect(effectiveRole({ ...baseRow, role: null, role_default: 'modifier' })).toBe('unknown');
    expect(effectiveRole({ ...baseRow, role: null, role_default: null })).toBe('unknown');
  });
});
```

- [ ] **Step 2: Run the tests; expect failures**

Run: `cd web && npm test -- shapeData`

Expected: the two assertions in the new `'unknown'` case fail because the current implementation still falls back on `role_default`.

- [ ] **Step 3: Fix `effectiveRole` and the `role_default` type**

In `shapeData.ts`:

Change the `TaxonomyViewRow` `role_default` field type from
`'brand' | 'expression' | 'substance' | null` to `string | null` (it
holds recipe-position role strings — `'base' | 'modifier' | 'bitters' | …`
— that aren't a closed enum in the UI):

```ts
export interface TaxonomyViewRow {
  id: number;
  slug: string;
  display_name: string;
  role: 'brand' | 'expression' | null;
  role_default: string | null;
  is_cluster_node: boolean;
  is_defining_garnish: boolean;
  parent_ids: number[];
  child_ids: number[];
  aliases: string[];
  recipe_count: number;
}
```

Replace `effectiveRole` with the no-fallback version:

```ts
export function effectiveRole(node: TaxonomyViewRow): TaxonomyRole {
  return (node.role ?? 'unknown') as TaxonomyRole;
}
```

- [ ] **Step 4: Run tests; expect pass**

Run: `cd web && npm test -- shapeData`
Expected: PASS for the `effectiveRole` block.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/taxonomy/shapeData.ts web/src/components/taxonomy/shapeData.test.ts
git commit -m "Taxonomy: drop role_default fallback in effectiveRole"
```

---

## Task 2 — Simplify `effectiveRoleLabel` (drop `?` suffix)

**Why:** `effectiveRoleLabel` was a textual mirror of the on-canvas `?` glyph. The glyph is being removed (Task 5); the label should likewise stop appending `?` for "role inferred from `role_default`."

**Files:**
- Modify: [web/src/components/taxonomy/shapeData.ts](web/src/components/taxonomy/shapeData.ts)
- Modify: [web/src/components/taxonomy/shapeData.test.ts](web/src/components/taxonomy/shapeData.test.ts)

- [ ] **Step 1: Update the failing tests**

Replace the `describe('effectiveRoleLabel', …)` block with:

```ts
describe('effectiveRoleLabel', () => {
  it('returns the asserted role unchanged when set', () => {
    expect(effectiveRoleLabel({ ...baseRow, role: 'expression', role_default: null })).toBe('expression');
  });

  it('returns "unknown" when role is null, regardless of role_default', () => {
    expect(effectiveRoleLabel({ ...baseRow, role: null, role_default: 'modifier' })).toBe('unknown');
    expect(effectiveRoleLabel({ ...baseRow, role: null, role_default: null })).toBe('unknown');
  });
});
```

- [ ] **Step 2: Run; expect failure on the inferred case**

Run: `cd web && npm test -- shapeData`
Expected: the `'modifier'` case fails because the current code returns `'modifier?'`.

- [ ] **Step 3: Simplify `effectiveRoleLabel`**

In `shapeData.ts`:

```ts
export function effectiveRoleLabel(node: TaxonomyViewRow): string {
  return node.role ?? 'unknown';
}
```

- [ ] **Step 4: Run; expect pass**

Run: `cd web && npm test -- shapeData`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/taxonomy/shapeData.ts web/src/components/taxonomy/shapeData.test.ts
git commit -m "Taxonomy: drop ? suffix from effectiveRoleLabel"
```

---

## Task 3 — Delete `TOP_LEVEL_ALLOWLIST` and `isOrphan`; simplify orphan filter

**Why:** Once edges show direction (Task 6), the curator can see "no incoming arrow" directly — the hardcoded allowlist of expected roots is no longer earning its keep. The "orphan" filter chip simplifies to "any node with no parents."

**Files:**
- Modify: [web/src/components/taxonomy/shapeData.ts](web/src/components/taxonomy/shapeData.ts)
- Modify: [web/src/components/taxonomy/shapeData.test.ts](web/src/components/taxonomy/shapeData.test.ts)

- [ ] **Step 1: Update tests**

In `shapeData.test.ts`:

a) Remove the `TOP_LEVEL_ALLOWLIST` import from the imports at the top, and remove `isOrphan` from imports.

b) Delete the entire `describe('TOP_LEVEL_ALLOWLIST', …)` and `describe('isOrphan', …)` blocks.

c) Replace the orphan-chip case inside `describe('rowMatchesFilters', …)` with the simpler predicate:

```ts
  it('orphan chip matches any node with no parents', () => {
    expect(rowMatchesFilters({ ...baseRow, slug: 'aperol',  parent_ids: [] }, new Set<FilterKey>(['orphan']))).toBe(true);
    expect(rowMatchesFilters({ ...baseRow, slug: 'whiskey', parent_ids: [] }, new Set<FilterKey>(['orphan']))).toBe(true);
    expect(rowMatchesFilters({ ...baseRow, slug: 'rye_whiskey', parent_ids: [1] }, new Set<FilterKey>(['orphan']))).toBe(false);
  });
```

d) Update the existing `rowMatchesFilters` test that mentions "substance via role_default fallback." With Task 1's change, that fallback is gone — substance must be asserted via `role`. Replace the test with:

```ts
  it('matches a role-chip via effectiveRole (substance asserted on role)', () => {
    const row: TaxonomyViewRow = { ...baseRow, role: 'expression' };
    expect(rowMatchesFilters({ ...row, role: 'expression' }, new Set<FilterKey>(['expression']))).toBe(true);
    expect(rowMatchesFilters({ ...row, role: 'expression' }, new Set<FilterKey>(['substance']))).toBe(false);
  });
```

(The `'AND-combines'` test below it stays valid — keep it as-is, but change its row to use `role: 'expression'` instead of relying on the role_default fallback so it still exercises the AND branch:)

```ts
  it('AND-combines: substance + expression matches nothing', () => {
    const row: TaxonomyViewRow = { ...baseRow, role: 'expression' };
    expect(rowMatchesFilters(row, new Set<FilterKey>(['substance', 'expression']))).toBe(false);
  });
```

- [ ] **Step 2: Run; expect failures**

Run: `cd web && npm test -- shapeData`
Expected: the orphan filter test fails on the `whiskey` case (current `isOrphan` excludes it via the allowlist), and the substance/expression tests may fail or compile-fail because of the type change in Task 1.

- [ ] **Step 3: Update `shapeData.ts`**

Delete the `TOP_LEVEL_ALLOWLIST` constant and the `isOrphan` function. In `rowMatchesFilters`, change the orphan branch from `isOrphan(row)` to `row.parent_ids.length === 0`:

```ts
export function rowMatchesFilters(
  row: TaxonomyViewRow,
  active: Set<FilterKey>,
): boolean {
  for (const f of active) {
    if (f === 'substance' || f === 'expression' || f === 'brand') {
      if (effectiveRole(row) !== f) return false;
      continue;
    }
    if (f === 'cluster' && !row.is_cluster_node) return false;
    if (f === 'orphan' && row.parent_ids.length > 0) return false;
    if (f === 'no aliases' && row.aliases.length > 0) return false;
    if (f === 'zero recipes' && row.recipe_count > 0) return false;
  }
  return true;
}
```

- [ ] **Step 4: Run tests; expect pass**

Run: `cd web && npm test -- shapeData`
Expected: PASS.

- [ ] **Step 5: Verify nothing else imports `TOP_LEVEL_ALLOWLIST` or `isOrphan`**

Run: `grep -rn "TOP_LEVEL_ALLOWLIST\|isOrphan" web/src`
Expected: no matches outside of test files (which were already updated). If `ForceCanvas.tsx` still imports `isOrphan`, also delete that import — it will be removed for real in Task 4 along with the dashed-ring drawing.

If `ForceCanvas.tsx` imports `isOrphan`, comment its single usage in the dashed-ring branch and remove the import temporarily so this task's commit doesn't break the type-check:

```ts
// Replace lines that use isOrphan() in drawNode with a temporary `false`:
const orphan = false;  // dashed-ring branch removed in Task 4.
```

This is a 30-second bridge that Task 4 will replace properly.

- [ ] **Step 6: Run typecheck**

Run: `cd web && npm run build`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add web/src/components/taxonomy/shapeData.ts web/src/components/taxonomy/shapeData.test.ts web/src/components/taxonomy/ForceCanvas.tsx
git commit -m "Taxonomy: drop TOP_LEVEL_ALLOWLIST + isOrphan; simplify orphan filter"
```

---

## Task 4 — Drop the dashed orphan ring from canvas

**Why:** Now that arrows are about to land (Task 6), the dashed ring is redundant. Also removes the temporary bridge introduced in Task 3.

**Files:**
- Modify: [web/src/components/taxonomy/ForceCanvas.tsx](web/src/components/taxonomy/ForceCanvas.tsx)

- [ ] **Step 1: Edit `drawNode` in `ForceCanvas.tsx`**

In `drawNode`, the gold-ring/dashed-ring branch currently looks like:

```ts
// Gold ring (or dashed red if orphan)
ctx.beginPath();
ctx.arc(node.x, node.y, outerR, 0, 2 * Math.PI);
if (isOrphan(node)) {
  ctx.strokeStyle = TX_ORPHAN_RING;
  ctx.setLineDash([2.2, 1.8]);
  ctx.lineWidth = 1.0;
} else {
  ctx.strokeStyle = TX_GOLD;
  ctx.setLineDash([]);
  ctx.lineWidth = 1.0;
}
ctx.stroke();
ctx.setLineDash([]);
```

Replace with:

```ts
// Gold ring
ctx.beginPath();
ctx.arc(node.x, node.y, outerR, 0, 2 * Math.PI);
ctx.strokeStyle = TX_GOLD;
ctx.lineWidth = 1.0;
ctx.stroke();
```

Also remove `TX_ORPHAN_RING` and `isOrphan` from the imports at the top of the file. If you added a `const orphan = false;` bridge in Task 3, remove it as well.

- [ ] **Step 2: Type-check**

Run: `cd web && npm run build`
Expected: PASS.

- [ ] **Step 3: Run all web tests to ensure no regressions**

Run: `cd web && npm test`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add web/src/components/taxonomy/ForceCanvas.tsx
git commit -m "Taxonomy: drop dashed orphan ring from canvas"
```

---

## Task 5 — Drop the `?` glyph from canvas

**Why:** The `?` flagged a narrow sub-case of "role (taxonomy) is null" (specifically: `role` null AND `role_default` set). After Task 1, null-role nodes render as gray fill (the `unknown` palette entry, `#888888`); the curator can triage from those gray dots and click in for the partial-classification distinction.

**Files:**
- Modify: [web/src/components/taxonomy/ForceCanvas.tsx](web/src/components/taxonomy/ForceCanvas.tsx)

- [ ] **Step 1: Delete the `?` block in `drawNode`**

Remove these lines (currently around `ForceCanvas.tsx:136–142`):

```ts
// Inferred-role marker: '?' near the node when role is null but
// role_default is set (the QA tool wants these flagged for curator
// review — the role hasn't been asserted yet).
if (node.role == null && node.role_default != null) {
  ctx.font = `bold ${Math.max(7, radius * 1.2)}px 'Cinzel', serif`;
  ctx.fillStyle = TX_GOLD;
  ctx.textAlign = 'left';
  ctx.textBaseline = 'top';
  ctx.fillText('?', node.x + outerR + 1, node.y - outerR - 1);
}
```

Leave the defining-garnish glyph block immediately below it untouched.

- [ ] **Step 2: Type-check + run all tests**

Run: `cd web && npm run build && npm test`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add web/src/components/taxonomy/ForceCanvas.tsx
git commit -m "Taxonomy: drop ? glyph from canvas"
```

---

## Task 6 — Add directional arrows on edges

**Why:** The DAG runs parent → child. With arrows, a curator can see directionality at a glance and spot parentless nodes without a marker.

**Files:**
- Modify: [web/src/components/taxonomy/ForceCanvas.tsx](web/src/components/taxonomy/ForceCanvas.tsx)

- [ ] **Step 1: Add the three arrow props on `<ForceGraph2D>`**

Edit the `ForceGraph2D` JSX in `ForceCanvas.tsx`. Add the three directional-arrow props alongside the existing link-styling props:

```tsx
<ForceGraph2D
  ref={inner}
  graphData={data}
  width={width}
  height={height}
  backgroundColor="rgba(0,0,0,0)"
  nodeRelSize={4}
  nodeVal={(n) => nodeRadius(n as TaxonomyNode)}
  linkColor={() => TX_LINK}
  linkWidth={0.6}
  linkCurvature={0.18}
  linkDirectionalArrowLength={4}
  linkDirectionalArrowRelPos={0.92}
  linkDirectionalArrowColor={() => TX_GOLD}
  enableNodeDrag={false}
  cooldownTicks={120}
  …rest unchanged
/>
```

- [ ] **Step 2: Type-check + run all tests**

Run: `cd web && npm run build && npm test`
Expected: PASS (no test exercises arrow rendering; this is a visual change verified manually in step 3).

- [ ] **Step 3: Manual smoke check**

Run: `cd web && npm run dev` (Supabase must be running on the host).

Open the forwarded port, navigate to the Taxonomy page. Verify:
- Arrows are visible on edges, pointing parent → child.
- Arrows sit just inside the target ring, not at the node centre.
- Color matches the existing gold edges (no chrome blue/green).
- Background, ring, and node fills look as before.

If arrows look chunky next to small nodes, drop `linkDirectionalArrowLength` to `3`. If they look too small at fit-zoom, raise to `5`. Pick the value that reads as engraving, not UI chrome, and update Step 1 accordingly. Stop the dev server with Ctrl-C when done.

- [ ] **Step 4: Commit**

```bash
git add web/src/components/taxonomy/ForceCanvas.tsx
git commit -m "Taxonomy: directional arrows on edges (parent → child)"
```

---

## Task 7 — Drop the on-canvas alias orbit

**Why:** Aliases are listed canonically in the node card; the orbit duplicates them and overlaps in dense subtrees. The curator flagged this directly.

**Files:**
- Modify: [web/src/components/taxonomy/ForceCanvas.tsx](web/src/components/taxonomy/ForceCanvas.tsx)

- [ ] **Step 1: Remove `drawAliasOrbit` and its call site**

In `ForceCanvas.tsx`:

a) Remove the call to `drawAliasOrbit` inside `nodeCanvasObject`:

```ts
// BEFORE
nodeCanvasObject={(node, ctx) => {
  const n = node as TaxonomyNode & { x: number; y: number };
  const dimmed = dimmedIds?.has(n.id) ?? false;
  ctx.globalAlpha = dimmed ? 0.18 : 1;
  drawNode(n, ctx);
  if (focusedId != null && n.id === focusedId && n.aliases.length > 0) {
    drawAliasOrbit(n, ctx);
  }
  ctx.globalAlpha = 1;
}}

// AFTER
nodeCanvasObject={(node, ctx) => {
  const n = node as TaxonomyNode & { x: number; y: number };
  const dimmed = dimmedIds?.has(n.id) ?? false;
  ctx.globalAlpha = dimmed ? 0.18 : 1;
  drawNode(n, ctx);
  ctx.globalAlpha = 1;
}}
```

b) Delete the entire `drawAliasOrbit` function definition at the bottom of the file (the comment block above it as well).

c) `focusedId` is now unused in this file. Remove it from the `Props` interface and from the destructure at the top of the component:

```ts
interface Props {
  nodes: TaxonomyNode[];
  links: TaxonomyLink[];
  width: number;
  height: number;
  dimmedIds?: Set<number>;
  onNodeClick: (node: TaxonomyNode) => void;
  onNodeHover: (node: TaxonomyNode | null) => void;
  onBackgroundClick?: () => void;
}
```

```ts
export const ForceCanvas = forwardRef<ForceCanvasHandle, Props>(function ForceCanvas(
  { nodes, links, width, height, dimmedIds, onNodeClick, onNodeHover, onBackgroundClick },
  ref,
) {
```

d) `Taxonomy.tsx` currently passes `focusedId={focusedId}` to `<ForceCanvas>`. That prop call becomes a type error after the prop is removed. Edit [web/src/pages/Taxonomy.tsx](web/src/pages/Taxonomy.tsx) and remove the line `focusedId={focusedId}` from the JSX.

- [ ] **Step 2: Type-check + run all tests**

Run: `cd web && npm run build && npm test`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add web/src/components/taxonomy/ForceCanvas.tsx web/src/pages/Taxonomy.tsx
git commit -m "Taxonomy: drop on-canvas alias orbit (card already lists them)"
```

---

## Task 8 — Rename `SpecimenCard` → `NodeCard`; rebuild as auto-height overlay with X button

**Why:** The card now serves both hover (transient) and pinned (clicked) modes. The "specimen" framing is curator-Latin; a plain `NodeCard` is honest about what it is. While we're here: drop the full-height drawer styling, drop the "ESC TO DISMISS" footer in favor of an explicit X button, and rename the property labels per the spec.

**Files:**
- Rename: `web/src/components/taxonomy/SpecimenCard.tsx` → `web/src/components/taxonomy/NodeCard.tsx`
- Rename: `web/src/components/taxonomy/SpecimenCard.test.tsx` → `web/src/components/taxonomy/NodeCard.test.tsx`
- Modify: [web/src/pages/Taxonomy.tsx](web/src/pages/Taxonomy.tsx) (import + usage; full wiring lands in Task 9)

- [ ] **Step 1: Rename the files via `git mv`**

```bash
git mv web/src/components/taxonomy/SpecimenCard.tsx web/src/components/taxonomy/NodeCard.tsx
git mv web/src/components/taxonomy/SpecimenCard.test.tsx web/src/components/taxonomy/NodeCard.test.tsx
```

- [ ] **Step 2: Replace the test file content**

Overwrite `web/src/components/taxonomy/NodeCard.test.tsx` with:

```tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { NodeCard } from './NodeCard';
import type { TaxonomyNode } from './shapeData';

const node: TaxonomyNode = {
  id: 1, slug: 'rye_whiskey', display_name: 'Rye Whiskey',
  role: 'expression', role_default: 'modifier',
  is_cluster_node: true, is_defining_garnish: false,
  parent_ids: [10, 11], child_ids: [20, 21],
  aliases: ['rye', 'rye whisky'], recipe_count: 47,
};

describe('<NodeCard>', () => {
  it('renders the node properties with the renamed labels', () => {
    render(<NodeCard node={node} mode="pinned" onDismiss={() => {}} />);
    expect(screen.getByText('RYE WHISKEY')).toBeInTheDocument();
    expect(screen.getByText(/47 drinks call for this/i)).toBeInTheDocument();
    expect(screen.getByText(/rye, rye whisky/)).toBeInTheDocument();
    expect(screen.getByText(/role \(taxonomy\)/i)).toBeInTheDocument();
    expect(screen.getByText(/default role \(recipe ingredient\)/i)).toBeInTheDocument();
    expect(screen.getByText(/clustering node/i)).toBeInTheDocument();
  });

  it('shows the X button only in pinned mode and dismisses on click', async () => {
    const user = userEvent.setup();
    const onDismiss = vi.fn();
    const { rerender } = render(<NodeCard node={node} mode="pinned" onDismiss={onDismiss} />);
    const close = screen.getByRole('button', { name: /close/i });
    await user.click(close);
    expect(onDismiss).toHaveBeenCalled();

    rerender(<NodeCard node={node} mode="hover" onDismiss={onDismiss} />);
    expect(screen.queryByRole('button', { name: /close/i })).toBeNull();
  });

  it('calls onDismiss when Escape is pressed in pinned mode', async () => {
    const user = userEvent.setup();
    const onDismiss = vi.fn();
    render(<NodeCard node={node} mode="pinned" onDismiss={onDismiss} />);
    await user.keyboard('{Escape}');
    expect(onDismiss).toHaveBeenCalled();
  });

  it('does NOT call onDismiss on Escape in hover mode', async () => {
    const user = userEvent.setup();
    const onDismiss = vi.fn();
    render(<NodeCard node={node} mode="hover" onDismiss={onDismiss} />);
    await user.keyboard('{Escape}');
    expect(onDismiss).not.toHaveBeenCalled();
  });

  it('writes the slug to the clipboard when the slug row is clicked', async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    render(<NodeCard node={node} mode="pinned" onDismiss={() => {}} />);
    await user.click(screen.getByText(/rye_whiskey/));
    expect(writeText).toHaveBeenCalledWith('rye_whiskey');
  });
});
```

- [ ] **Step 3: Run; expect failures**

Run: `cd web && npm test -- NodeCard`
Expected: every assertion fails (component still exports as `SpecimenCard`, has the old labels, no `mode` prop, no X button).

- [ ] **Step 4: Replace `NodeCard.tsx` content**

Overwrite `web/src/components/taxonomy/NodeCard.tsx` with:

```tsx
import { useEffect } from 'react';
import type { TaxonomyNode } from './shapeData';
import { TX_BROWN_INK, TX_BROWN_MID, TX_FRAME_EDGE } from './palette';

export type NodeCardMode = 'hover' | 'pinned';

interface Props {
  node: TaxonomyNode;
  mode: NodeCardMode;
  onDismiss: () => void;
}

export function NodeCard({ node, mode, onDismiss }: Props) {
  useEffect(() => {
    if (mode !== 'pinned') return;
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onDismiss(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [mode, onDismiss]);

  const copySlug = async () => {
    try { await navigator.clipboard.writeText(node.slug); } catch { /* swallow */ }
  };

  return (
    <aside
      className="tx-card"
      role={mode === 'pinned' ? 'dialog' : 'tooltip'}
      aria-label={`Taxonomy node: ${node.display_name}`}
      style={{
        position: 'absolute', top: 150, right: 14, width: 240, zIndex: 4,
        padding: '20px 18px',
      }}
    >
      {mode === 'pinned' && (
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Close"
          style={{
            position: 'absolute', top: 6, right: 8,
            background: 'none', border: 'none', cursor: 'pointer',
            color: TX_BROWN_MID, fontSize: 16, lineHeight: 1,
            fontFamily: "'Cinzel', serif",
          }}
        >
          ×
        </button>
      )}

      <div style={{ textAlign: 'center' }}>
        <div className="tx-card__heading">— SPECIMEN —</div>
        <div
          style={{
            fontFamily: "'Cinzel', serif", fontSize: 16, fontWeight: 700,
            letterSpacing: '0.18em', color: TX_BROWN_INK, marginTop: 4,
          }}
        >
          {node.display_name.toUpperCase()}
        </div>
        <div className="tx-rule" style={{ margin: '8px 16px' }} />
      </div>

      <div style={{ fontSize: 13, lineHeight: 1.55, color: TX_BROWN_MID }}>
        <div className="tx-card__heading" style={{ marginTop: 4 }}>PROPERTIES</div>
        <Row label="Role (taxonomy)" value={node.role ?? '—'} />
        <Row label="Default Role (recipe ingredient)" value={node.role_default ?? '—'} />
        <Row label="Clustering node" value={node.is_cluster_node ? '✓' : '—'} />
        <Row label="Defining garnish" value={node.is_defining_garnish ? '✓' : '—'} />

        <div className="tx-card__heading" style={{ marginTop: 10 }}>
          ALIASES <span style={{ fontStyle: 'italic', color: TX_FRAME_EDGE }}>({node.aliases.length})</span>
        </div>
        <div style={{ fontStyle: 'italic' }}>{node.aliases.join(', ') || '—'}</div>

        <div className="tx-card__heading" style={{ marginTop: 10 }}>RECIPES</div>
        <div>{node.recipe_count} drinks call for this</div>

        <div className="tx-card__heading" style={{ marginTop: 10 }}>SLUG</div>
        <button
          type="button"
          onClick={copySlug}
          aria-label={`Copy slug ${node.slug} to clipboard`}
          style={{
            background: 'none', border: 'none', padding: 0,
            color: 'inherit', textAlign: 'left',
            fontFamily: 'ui-monospace, monospace', fontSize: 12,
            cursor: 'pointer', userSelect: 'none',
          }}
        >
          ⊕ {node.slug}
        </button>
      </div>
    </aside>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
      <span>{label}</span>
      <span style={{ fontStyle: 'italic', textAlign: 'right' }}>{value}</span>
    </div>
  );
}
```

Key changes vs. the old `SpecimenCard`:
- Renamed export `SpecimenCard` → `NodeCard`.
- Added `mode` prop; X button rendered only in pinned mode.
- Removed the bottom "ESC TO DISMISS" footer and the `bottom: 0` full-height styling.
- `top: 150` places it just below the legend; auto-height by virtue of dropping `bottom: 0`.
- Property labels renamed: "role" → "Role (taxonomy)", "role default" → "Default Role (recipe ingredient)", "cluster node" → "Clustering node", "defining garnish" → "Defining garnish".
- Esc handler only attaches in pinned mode (transient hover-cards shouldn't grab the key).
- The `Row` value column gets `textAlign: 'right'` so longer labels like "Default Role (recipe ingredient)" don't shove the value off-card.

- [ ] **Step 5: Update the import + usage in `Taxonomy.tsx`**

In `Taxonomy.tsx`:

a) Replace `import { SpecimenCard } from '…/SpecimenCard';` with `import { NodeCard } from '…/NodeCard';`.

b) Replace the existing pinned-card render at the bottom of the JSX:

```tsx
// BEFORE
{focusedNode && (
  <SpecimenCard node={focusedNode} onDismiss={() => setFocusedId(null)} />
)}

// AFTER (still pinned-only for now; hover wiring lands in Task 9)
{focusedNode && (
  <NodeCard node={focusedNode} mode="pinned" onDismiss={() => setFocusedId(null)} />
)}
```

- [ ] **Step 6: Run; expect pass**

Run: `cd web && npm test -- NodeCard && npm run build`
Expected: PASS for both.

- [ ] **Step 7: Commit**

```bash
git add web/src/components/taxonomy/NodeCard.tsx web/src/components/taxonomy/NodeCard.test.tsx web/src/pages/Taxonomy.tsx
git commit -m "Taxonomy: rename SpecimenCard → NodeCard; auto-height + X button + label cleanup"
```

---

## Task 9 — Merge hover and pinned card; drop the inline hover JSX

**Why:** Today there are two different right-rail card implementations (the inline hover card in `Taxonomy.tsx` and the `SpecimenCard` drawer). With `NodeCard` now mode-aware, both states render through one component. While focused, hover events are ignored so the pinned card doesn't swap.

**Files:**
- Modify: [web/src/pages/Taxonomy.tsx](web/src/pages/Taxonomy.tsx)

- [ ] **Step 1: Rewrite the bottom of the `LoadedView` JSX**

In `Taxonomy.tsx`, find the existing block that renders the inline hover card and the pinned `NodeCard`:

```tsx
{hovered && !focusedNode && (
  <div
    className="tx-card"
    style={{
      position: 'absolute', top: 150, right: 14, zIndex: 3,
      padding: '8px 12px', fontSize: 12, lineHeight: 1.5, width: 200,
    }}
  >
    <div style={{ fontFamily: "'Cinzel', serif", fontWeight: 600, letterSpacing: '0.12em' }}>
      {hovered.display_name}
    </div>
    <div style={{ color: TX_BROWN_SOFT, fontStyle: 'italic' }}>
      {effectiveRoleLabel(hovered)} · {hovered.recipe_count} recipes · {hovered.aliases.length} aliases
    </div>
  </div>
)}

{focusedNode && (
  <NodeCard node={focusedNode} mode="pinned" onDismiss={() => setFocusedId(null)} />
)}
```

Replace with a single block that derives which node (if any) the card should display, and which mode:

```tsx
{(() => {
  if (focusedNode) {
    return <NodeCard node={focusedNode} mode="pinned" onDismiss={() => setFocusedId(null)} />;
  }
  if (hovered) {
    return <NodeCard node={hovered} mode="hover" onDismiss={() => {}} />;
  }
  return null;
})()}
```

Hover events while pinned are intentionally ignored: `focusedNode` takes precedence so the user's pinned target doesn't swap when the cursor passes over a neighbor.

- [ ] **Step 2: Remove now-unused imports**

In `Taxonomy.tsx`, remove these imports if they are no longer referenced:
- `effectiveRoleLabel` from `./components/taxonomy/shapeData`.
- `TX_BROWN_SOFT` from `./components/taxonomy/palette`.

(`hovered` is still used for the hover-mode card, so its `useState` and `onNodeHover` wiring stay.)

- [ ] **Step 3: Manual smoke check (click-empty dismiss)**

Run: `cd web && npm run dev`.

In the browser:
- Hover a node → card appears with `mode="hover"`, no X button, Esc does nothing.
- Click a node → card pins, X button visible.
- Move cursor over other nodes → pinned card does NOT swap.
- Click the X → card closes.
- Click a node again → card pins.
- Press Esc → card closes.
- Click a node again → card pins.
- Click on an empty area of the canvas → card closes (`onBackgroundClick` already wired at [Taxonomy.tsx:190](web/src/pages/Taxonomy.tsx#L190)).

If click-empty does not dismiss, the most likely cause is that `pointer-events` on the card root or its container is intercepting the canvas click. Add `pointerEvents: 'auto'` only to the card root (already implicit) and leave the rest of the page's overlays alone — `react-force-graph` handles background clicks at the canvas level, so as long as the card is positioned outside the canvas's hit region the canvas should still see the click.

If click-empty still doesn't fire, log inside the `onBackgroundClick` handler temporarily, identify the offending element, and tighten its `pointer-events: none` (do NOT add a fullscreen overlay div — that's the wrong shape of fix).

Stop the dev server with Ctrl-C.

- [ ] **Step 4: Run all tests + typecheck**

Run: `cd web && npm test && npm run build`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/pages/Taxonomy.tsx
git commit -m "Taxonomy: hover and pinned card share one NodeCard render"
```

---

## Task 10 — Rewrite the legend

**Why:** The current legend mislabels `?` as "role inferred", explains "cluster" with no context (and collides with the unrelated `recipe_clusters` concept), and lists "defining garnish" — a glyph the curator doesn't need at a glance.

**Files:**
- Modify: [web/src/components/taxonomy/Legend.tsx](web/src/components/taxonomy/Legend.tsx)

- [ ] **Step 1: Replace `Legend.tsx` content**

Overwrite the file with:

```tsx
import { ROLE_FILL, TX_BROWN_SOFT, TX_FRAME_EDGE } from './palette';

export function Legend() {
  return (
    <div
      className="tx-card"
      style={{
        position: 'absolute', top: 14, right: 14, zIndex: 2,
        padding: '8px 12px', fontSize: 12, lineHeight: 1.55, width: 180,
      }}
    >
      <div className="tx-card__heading" style={{ marginBottom: 4 }}>LEGEND</div>
      <LegendDot color={ROLE_FILL.substance} /> substance<br />
      <LegendDot color={ROLE_FILL.expression} /> expression<br />
      <LegendDot color={ROLE_FILL.brand} /> brand<br />
      <div style={{ marginTop: 4, fontStyle: 'italic', color: TX_BROWN_SOFT, lineHeight: 1.4 }}>
        ◯ extra ring = clustering node<br />
        ◯ gray fill = role (taxonomy) not set<br />
        → arrow = parent → child
      </div>
    </div>
  );
}

function LegendDot({ color }: { color: string }) {
  return (
    <span
      style={{
        display: 'inline-block', width: 9, height: 9, borderRadius: '50%',
        background: color, border: `1px solid ${TX_FRAME_EDGE}`, verticalAlign: 'middle',
        marginRight: 6,
      }}
    />
  );
}
```

Width bumped to `180` so the new "role (taxonomy) not set" line doesn't wrap awkwardly. Removed: `?` line, dashed-orphan line, defining-garnish line.

- [ ] **Step 2: Type-check + run all tests**

Run: `cd web && npm run build && npm test`
Expected: PASS (no test asserts legend content; it's a visual change).

- [ ] **Step 3: Manual smoke check**

Run: `cd web && npm run dev`. Confirm the legend on the page reads as the rewritten body. Stop the dev server with Ctrl-C.

- [ ] **Step 4: Commit**

```bash
git add web/src/components/taxonomy/Legend.tsx
git commit -m "Taxonomy: rewrite legend (drop ?, drop orphan/garnish lines, add arrow line)"
```

---

## Task 11 — Rename "cluster" filter chip label to "clustering node"

**Why:** Match the rename used everywhere else (legend, NodeCard). The internal `FilterKey` string stays `'cluster'` to avoid touching `rowMatchesFilters`; only the visible label changes.

**Files:**
- Modify: [web/src/components/taxonomy/FilterChips.tsx](web/src/components/taxonomy/FilterChips.tsx)
- Modify: [web/src/components/taxonomy/FilterChips.test.tsx](web/src/components/taxonomy/FilterChips.test.tsx)

- [ ] **Step 1: Update the failing test**

In `FilterChips.test.tsx`, the existing test loops through expected button labels. Replace the labels list:

```ts
for (const label of ['substance', 'expression', 'brand', 'clustering node', 'orphan', 'no aliases', 'zero recipes']) {
  expect(screen.getByRole('button', { name: new RegExp(label, 'i') })).toBeInTheDocument();
}
```

(All other tests in this file stay valid; the `aria-pressed` test uses `'orphan'` and the toggle test uses `'expression'`, both still labeled the same.)

- [ ] **Step 2: Run; expect failure**

Run: `cd web && npm test -- FilterChips`
Expected: the "renders one chip per filter key" test fails because the rendered chip text is still `cluster`, not `clustering node`.

- [ ] **Step 3: Add a label map in `FilterChips.tsx`**

Edit `FilterChips.tsx`. Add a label map after the `ORDERED` constant:

```ts
const LABELS: Record<FilterKey, string> = {
  substance: 'substance',
  expression: 'expression',
  brand: 'brand',
  cluster: 'clustering node',
  orphan: 'orphan',
  'no aliases': 'no aliases',
  'zero recipes': 'zero recipes',
};
```

In the JSX, change the chip body from `{key}` to `{LABELS[key]}`:

```tsx
<button
  key={key}
  type="button"
  aria-pressed={isActive}
  onClick={() => onToggle(key)}
  style={{ /* unchanged */ }}
>
  {LABELS[key]}
</button>
```

- [ ] **Step 4: Run; expect pass**

Run: `cd web && npm test -- FilterChips`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/taxonomy/FilterChips.tsx web/src/components/taxonomy/FilterChips.test.tsx
git commit -m "Taxonomy: rename cluster filter chip label to 'clustering node'"
```

---

## Task 12 — Final verification

**Why:** End-to-end gate before handing off.

- [ ] **Step 1: Run the full test suite**

Run: `cd web && npm test`
Expected: PASS.

- [ ] **Step 2: Type-check**

Run: `cd web && npm run build`
Expected: PASS.

- [ ] **Step 3: Lint**

Run: `cd web && npm run lint`
Expected: PASS (or only pre-existing warnings; no new ones).

- [ ] **Step 4: Manual end-to-end smoke**

Run: `cd web && npm run dev`. Confirm in the browser:
1. Legend in top-right reads as Task 10 specifies.
2. `?` glyphs are gone from the canvas.
3. Dashed orphan rings are gone — every ring is solid gold.
4. Edges show small gold arrows pointing to children.
5. Hover a node → card appears top-right under the legend, no X button.
6. Click a node → card pins, X button visible. Pinned card stays even when hovering other nodes.
7. Click X → card closes.
8. Click another node → re-pin.
9. Press Esc → card closes.
10. Click another node → re-pin.
11. Click empty canvas → card closes.
12. Cluster filter chip label reads "clustering node."
13. Orphan filter chip now also matches `whiskey`, `gin`, etc. (any node with no parents).

Stop the dev server with Ctrl-C.

- [ ] **Step 5: Final commit (only if you spotted small fixups in step 4)**

If anything in Step 4 needed an inline fix, commit it now with an honest subject. Otherwise skip.

---

## Self-Review Notes

The plan covers every requirement from the spec:

- §A "Single hover/click card, sized to content" → Tasks 8, 9.
- §B "Drop the `?` glyph; render null-role nodes as gray" → Tasks 1, 2, 5.
- §C "Specimen-card label rename" → Task 8.
- §D "Drop the dashed orphan ring" → Tasks 3, 4.
- §E "Directional arrows on edges" → Task 6.
- §F "Legend rewrite" → Task 10.
- "Drop the on-canvas alias orbit" (§A) → Task 7.
- "Rename cluster chip label" (§D mention) → Task 11.

Type/method consistency check: `NodeCard` is used with `mode: 'hover' | 'pinned'` everywhere it appears (Tasks 8 and 9). `effectiveRole` is consistently the no-fallback version after Task 1. `TOP_LEVEL_ALLOWLIST` and `isOrphan` are removed from imports in every file that referenced them (Tasks 3, 4). `focusedId` is removed both from `ForceCanvas`'s `Props` and from `Taxonomy.tsx`'s usage in Task 7.
