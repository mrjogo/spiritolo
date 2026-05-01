# Taxonomy Graph UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a `/taxonomy` route in the existing Vite/React/TS web app that renders the full taxonomy DAG as a force-directed canvas with a click-to-focus radial mode and an Art Deco speakeasy aesthetic.

**Architecture:** Single Supabase fetch from a new `taxonomy_public` view → in-memory force-graph state → `react-force-graph-2d` canvas. Pure-logic transforms live in `shapeData.ts` (only TDD-tested module). No backend changes beyond the migration; no impact on existing recipe routes other than a shared top header.

**Tech Stack:** React 19, Vite, TypeScript, react-router-dom 7, `@supabase/supabase-js` 2, `react-force-graph-2d` (new), Vitest 4 + `@testing-library/react` 16. Cinzel + Cormorant Garamond from Google Fonts. Postgres 16 (Supabase local).

**Spec:** [docs/superpowers/specs/2026-05-01-taxonomy-graph-ui-design.md](../specs/2026-05-01-taxonomy-graph-ui-design.md). Re-read before starting.

**Branch:** `claude/taxonomy-graph-ui-4e67` (already created).

**Discipline reminders:**
- Red/green TDD for every pure-logic and component test: write the failing test first, run it, see it fail with the right error message, then write the minimum implementation, run again, see it pass.
- Commit after each green. The plan tells you when.
- Never edit `shapeData.ts` without first writing or modifying a test in `shapeData.test.ts`.
- Canvas pixels are not unit-tested. ForceCanvas, focus-mode wiring, and CSS are validated by hand in the dev server. The plan calls out the manual checks.

---

## Task 1: Migration — `taxonomy_public` view + grants + policies

**Files:**
- Create: `supabase/migrations/20260501120000_create_taxonomy_public.sql`

**Background:** The view is `security_invoker = true`, mirroring `recipes_public`. It joins `taxonomy_nodes` + aggregated edges + aggregated aliases + a `recipe_count` aggregate over `recipe_ingredients` (column `taxonomy_node_id`). Each underlying table needs a public-read RLS policy. `recipe_ingredients` gets a column-level grant on only `(recipe_id, taxonomy_node_id)` so anon cannot read parser internals.

- [ ] **Step 1: Run a "red" check that the view does not yet exist**

```bash
DB_URL='postgresql://postgres:postgres@host.docker.internal:54322/postgres'
psql "$DB_URL" -c 'select count(*) from taxonomy_public;'
```

Expected: ERROR — `relation "taxonomy_public" does not exist`.

- [ ] **Step 2: Write the migration**

Create `supabase/migrations/20260501120000_create_taxonomy_public.sql`:

```sql
-- Public read surface for the taxonomy DAG. One row per node with edges
-- and aliases pre-aggregated and a direct (non-rollup) recipe count.
-- Mirrors the recipes_public pattern: security_invoker = true plus
-- public-read policies and column-level grants on each underlying table.
-- recipe_ingredients exposes only (recipe_id, taxonomy_node_id) so the
-- view can compute counts without leaking parser internals to anon.

create view taxonomy_public
  with (security_invoker = true)
as
select
  n.id,
  n.slug,
  n.display_name,
  n.role,
  n.role_default,
  n.is_cluster_node,
  n.is_defining_garnish,
  coalesce(p.parent_ids, '{}'::bigint[]) as parent_ids,
  coalesce(c.child_ids,  '{}'::bigint[]) as child_ids,
  coalesce(a.aliases,    '{}'::text[])   as aliases,
  coalesce(r.recipe_count, 0)            as recipe_count
from taxonomy_nodes n
left join lateral (
  select array_agg(parent_id order by parent_id) as parent_ids
  from taxonomy_edges where child_id = n.id
) p on true
left join lateral (
  select array_agg(child_id order by child_id) as child_ids
  from taxonomy_edges where parent_id = n.id
) c on true
left join lateral (
  select array_agg(alias order by alias) as aliases
  from taxonomy_aliases where node_id = n.id
) a on true
left join lateral (
  select count(distinct recipe_id)::int as recipe_count
  from recipe_ingredients
  where taxonomy_node_id = n.id
) r on true;

grant select on taxonomy_public to anon, authenticated;

-- taxonomy_nodes: full column-level grant + public-read policy.
grant select (
  id, slug, display_name, role, role_default,
  is_cluster_node, is_defining_garnish, created_at
) on taxonomy_nodes to anon, authenticated;

create policy taxonomy_nodes_public_read on taxonomy_nodes
  for select to anon, authenticated using (true);

-- taxonomy_edges: full column-level grant + public-read policy.
grant select (parent_id, child_id) on taxonomy_edges to anon, authenticated;

create policy taxonomy_edges_public_read on taxonomy_edges
  for select to anon, authenticated using (true);

-- taxonomy_aliases: full column-level grant + public-read policy.
grant select (alias, node_id) on taxonomy_aliases to anon, authenticated;

create policy taxonomy_aliases_public_read on taxonomy_aliases
  for select to anon, authenticated using (true);

-- recipe_ingredients: tightly scoped grant — only the two columns the
-- view needs to compute recipe_count. Parser internals stay private.
grant select (recipe_id, taxonomy_node_id)
  on recipe_ingredients to anon, authenticated;

create policy recipe_ingredients_taxonomy_count_read on recipe_ingredients
  for select to anon, authenticated using (true);
```

- [ ] **Step 3: Apply the migration to local Supabase**

```bash
DB_URL='postgresql://postgres:postgres@192.168.65.254:54322/postgres?sslmode=disable'
supabase migration up --db-url "$DB_URL" --include-all
```

Expected: applies one migration, lists `20260501120000_create_taxonomy_public` in the output.

- [ ] **Step 4: Run a "green" check that the view now returns rows**

```bash
DB_URL='postgresql://postgres:postgres@host.docker.internal:54322/postgres'
psql "$DB_URL" -c 'select count(*) from taxonomy_public;'
psql "$DB_URL" -c "select id, slug, role, is_cluster_node, array_length(parent_ids, 1) parents, array_length(child_ids, 1) children, array_length(aliases, 1) aliases, recipe_count from taxonomy_public order by slug limit 10;"
```

Expected: count is non-zero (~166); the listing shows ten rows with at least some having non-null parent/child/alias counts.

- [ ] **Step 5: Smoke-test the view via the Supabase JS client (anon key)**

The web `.env.local` already has the publishable (anon-equivalent) key. From the repo root:

```bash
cd web && npx tsx -e "
import { createClient } from '@supabase/supabase-js';
import 'dotenv/config';
const url = process.env.VITE_SUPABASE_URL!;
const key = process.env.VITE_SUPABASE_PUBLISHABLE_KEY!;
const sb = createClient(url, key);
const { data, error, count } = await sb
  .from('taxonomy_public')
  .select('id, slug, recipe_count', { count: 'exact' })
  .limit(3);
console.log({ count, error, sample: data });
" 2>&1 | tail -10
```

Expected: `count: ~166`, `error: null`, `sample` is an array of 3 rows. If `error` is non-null, RLS or grants are wrong — fix before continuing.

If `tsx` is not installed, install with `npx tsx` first or use a quick `node --experimental-strip-types` wrapper. The exact env-var names live in `web/.env.local`; if they differ, read that file first.

- [ ] **Step 6: Commit**

```bash
git add supabase/migrations/20260501120000_create_taxonomy_public.sql
git commit -m "$(cat <<'EOF'
Add taxonomy_public view + grants

One-fetch read surface for the curator-QA UI: pre-aggregated parents,
children, aliases, and direct recipe count per node. security_invoker
= true with column-level grants and public-read policies on each
underlying table. recipe_ingredients exposes only (recipe_id,
taxonomy_node_id).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Install `react-force-graph-2d` + load Art Deco fonts

**Files:**
- Modify: `web/package.json`, `web/package-lock.json`
- Modify: `web/index.html`

- [ ] **Step 1: Install the graph library**

```bash
cd web && npm install react-force-graph-2d
```

Expected: dependency added, `package-lock.json` updated. No type-only @types package needed — `react-force-graph-2d` ships its own types.

- [ ] **Step 2: Add Google Fonts links to `web/index.html`**

Read the current `web/index.html`. Inside `<head>`, immediately before the existing module script tag, add:

```html
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Cinzel:wght@400;600;700&family=Cormorant+Garamond:ital,wght@0,400;0,600;1,400&display=swap">
```

- [ ] **Step 3: Verify the dev server still starts**

```bash
cd web && timeout 8 npm run dev 2>&1 | head -20
```

Expected: Vite prints "ready in Nms" and a `Local: http://localhost:5173/` line. If it errors, fix before continuing.

- [ ] **Step 4: Verify tests still pass**

```bash
cd web && npm test
```

Expected: all existing tests pass (we haven't added any yet).

- [ ] **Step 5: Commit**

```bash
git add web/package.json web/package-lock.json web/index.html
git commit -m "$(cat <<'EOF'
Add react-force-graph-2d + Art Deco fonts

Brings in the canvas-based force-directed graph library used by the
taxonomy page and preloads Cinzel + Cormorant Garamond from Google
Fonts.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `Header` component + wire into `App.tsx`

**Files:**
- Create: `web/src/components/Header.tsx`
- Create: `web/src/components/Header.test.tsx`
- Modify: `web/src/App.tsx`
- Modify: `web/src/styles.css`

- [ ] **Step 1: Write the failing test**

Create `web/src/components/Header.test.tsx`:

```tsx
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { Header } from './Header';

describe('<Header>', () => {
  it('renders the SPIRITOLO wordmark', () => {
    render(
      <MemoryRouter>
        <Header />
      </MemoryRouter>,
    );
    expect(screen.getByText(/spiritolo/i)).toBeInTheDocument();
  });

  it('links to / and /taxonomy', () => {
    render(
      <MemoryRouter>
        <Header />
      </MemoryRouter>,
    );
    expect(screen.getByRole('link', { name: /recipes/i })).toHaveAttribute('href', '/');
    expect(screen.getByRole('link', { name: /taxonomy/i })).toHaveAttribute('href', '/taxonomy');
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd web && npm test -- Header
```

Expected: FAIL — `Cannot find module './Header'`.

- [ ] **Step 3: Implement `Header.tsx`**

Create `web/src/components/Header.tsx`:

```tsx
import { Link } from 'react-router-dom';

export function Header() {
  return (
    <header className="site-header">
      <Link to="/" className="site-header__brand">SPIRITOLO</Link>
      <nav className="site-header__nav">
        <Link to="/">Recipes</Link>
        <Link to="/taxonomy">Taxonomy</Link>
      </nav>
    </header>
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd web && npm test -- Header
```

Expected: PASS, both cases green.

- [ ] **Step 5: Add header chrome styles**

Append to `web/src/styles.css`:

```css
.site-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid #e5e5e5;
  background: #fff;
}

.site-header__brand {
  font-family: 'Cinzel', Georgia, serif;
  font-weight: 700;
  letter-spacing: 0.18em;
  font-size: 1rem;
  color: #2c1d0c;
  text-decoration: none;
}

.site-header__nav {
  display: flex;
  gap: 1rem;
  font-size: 0.95rem;
}
```

- [ ] **Step 6: Wire `<Header />` into `App.tsx`**

Replace the contents of `web/src/App.tsx` with:

```tsx
import { Routes, Route } from 'react-router-dom';
import { Header } from './components/Header';
import { RecipeList } from './pages/RecipeList';
import { RecipeDetail } from './pages/RecipeDetail';
import { ErrorPage } from './components/ErrorPage';

export default function App() {
  return (
    <>
      <Header />
      <Routes>
        <Route path="/" element={<RecipeList />} />
        <Route path="/recipes/:id" element={<RecipeDetail />} />
        <Route
          path="*"
          element={<ErrorPage title="Page not found" message="That URL doesn't match any page." />}
        />
      </Routes>
    </>
  );
}
```

(Note: the `/taxonomy` route is added in Task 7, after the page exists. Until then, that link will hit the not-found page.)

- [ ] **Step 7: Run the full test suite**

```bash
cd web && npm test
```

Expected: all tests pass (the new Header tests and the existing RecipeList / RecipeDetail tests).

- [ ] **Step 8: Commit**

```bash
git add web/src/components/Header.tsx web/src/components/Header.test.tsx web/src/App.tsx web/src/styles.css
git commit -m "$(cat <<'EOF'
Add top-nav Header (wordmark + Recipes/Taxonomy links)

Single shared header above all routes. Recipes link points to / for
parity with the existing nav-less landing; Taxonomy link will go live
when the route is added in a later commit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `shapeData.ts` — types + `effectiveRole` + `viewRowsToGraph`

**Files:**
- Create: `web/src/components/taxonomy/shapeData.ts`
- Create: `web/src/components/taxonomy/shapeData.test.ts`

This task is pure logic, full TDD. We add three things: shared types, `effectiveRole(node)`, and `viewRowsToGraph(rows)`.

- [ ] **Step 1: Write failing tests**

Create `web/src/components/taxonomy/shapeData.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { effectiveRole, viewRowsToGraph } from './shapeData';
import type { TaxonomyViewRow } from './shapeData';

const baseRow: TaxonomyViewRow = {
  id: 1,
  slug: 'whiskey',
  display_name: 'Whiskey',
  role: null,
  role_default: 'substance',
  is_cluster_node: true,
  is_defining_garnish: false,
  parent_ids: [],
  child_ids: [2, 3],
  aliases: ['whisky'],
  recipe_count: 12,
};

describe('effectiveRole', () => {
  it('returns role when set', () => {
    expect(effectiveRole({ ...baseRow, role: 'expression', role_default: null })).toBe('expression');
  });

  it('falls back to role_default when role is null', () => {
    expect(effectiveRole({ ...baseRow, role: null, role_default: 'substance' })).toBe('substance');
  });

  it('returns "unknown" when both are null', () => {
    expect(effectiveRole({ ...baseRow, role: null, role_default: null })).toBe('unknown');
  });
});

describe('viewRowsToGraph', () => {
  it('returns nodes mirroring rows and links from child_ids', () => {
    const rows: TaxonomyViewRow[] = [
      { ...baseRow, id: 1, slug: 'whiskey', child_ids: [2] },
      { ...baseRow, id: 2, slug: 'rye_whiskey', parent_ids: [1], child_ids: [] },
    ];
    const { nodes, links } = viewRowsToGraph(rows);
    expect(nodes).toHaveLength(2);
    expect(nodes[0].id).toBe(1);
    expect(nodes[0].slug).toBe('whiskey');
    expect(links).toEqual([{ source: 1, target: 2 }]);
  });

  it('does not double-emit links derived from parent_ids', () => {
    const rows: TaxonomyViewRow[] = [
      { ...baseRow, id: 1, slug: 'whiskey', child_ids: [2] },
      { ...baseRow, id: 2, slug: 'rye_whiskey', parent_ids: [1], child_ids: [] },
    ];
    const { links } = viewRowsToGraph(rows);
    expect(links).toHaveLength(1);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd web && npm test -- shapeData
```

Expected: FAIL — `Cannot find module './shapeData'`.

- [ ] **Step 3: Implement the minimum needed to pass**

Create `web/src/components/taxonomy/shapeData.ts`:

```ts
export type TaxonomyRole = 'brand' | 'expression' | 'substance' | 'unknown';

export interface TaxonomyViewRow {
  id: number;
  slug: string;
  display_name: string;
  role: 'brand' | 'expression' | null;
  role_default: 'brand' | 'expression' | 'substance' | null;
  is_cluster_node: boolean;
  is_defining_garnish: boolean;
  parent_ids: number[];
  child_ids: number[];
  aliases: string[];
  recipe_count: number;
}

export interface TaxonomyNode extends TaxonomyViewRow {}

export interface TaxonomyLink {
  source: number;
  target: number;
}

export function effectiveRole(node: TaxonomyViewRow): TaxonomyRole {
  return (node.role ?? node.role_default ?? 'unknown') as TaxonomyRole;
}

export function viewRowsToGraph(rows: TaxonomyViewRow[]): {
  nodes: TaxonomyNode[];
  links: TaxonomyLink[];
} {
  const nodes: TaxonomyNode[] = rows.map((r) => ({ ...r }));
  const links: TaxonomyLink[] = [];
  for (const row of rows) {
    for (const childId of row.child_ids) {
      links.push({ source: row.id, target: childId });
    }
  }
  return { nodes, links };
}
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd web && npm test -- shapeData
```

Expected: PASS, all five cases green.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/taxonomy/shapeData.ts web/src/components/taxonomy/shapeData.test.ts
git commit -m "$(cat <<'EOF'
shapeData: types + effectiveRole + viewRowsToGraph

Pure transforms used by the taxonomy graph page. Links derive from
child_ids only (parent_ids is the inverse view), so each edge is
emitted exactly once.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `shapeData.ts` — orphan detection + substring matching

**Files:**
- Modify: `web/src/components/taxonomy/shapeData.ts`
- Modify: `web/src/components/taxonomy/shapeData.test.ts`

Add `TOP_LEVEL_ALLOWLIST`, `isOrphan(node)`, and `matchesQuery(node, query)`.

- [ ] **Step 1: Append failing tests**

Append to `web/src/components/taxonomy/shapeData.test.ts`:

```ts
import { isOrphan, matchesQuery, TOP_LEVEL_ALLOWLIST } from './shapeData';

describe('TOP_LEVEL_ALLOWLIST', () => {
  it('includes the canonical roots of the DAG', () => {
    expect(TOP_LEVEL_ALLOWLIST).toEqual(
      expect.arrayContaining([
        'whiskey',
        'vermouth',
        'bitters',
        'liqueur',
        'juice',
        'sweetener',
      ]),
    );
  });
});

describe('isOrphan', () => {
  it('flags a node with no parents that is not on the allowlist', () => {
    expect(isOrphan({ ...baseRow, slug: 'aperol', parent_ids: [] })).toBe(true);
  });

  it('does not flag a node with no parents that is on the allowlist', () => {
    expect(isOrphan({ ...baseRow, slug: 'whiskey', parent_ids: [] })).toBe(false);
  });

  it('does not flag a node that has parents', () => {
    expect(isOrphan({ ...baseRow, slug: 'rye_whiskey', parent_ids: [1] })).toBe(false);
  });
});

describe('matchesQuery', () => {
  it('returns true for a substring of slug', () => {
    expect(matchesQuery({ ...baseRow, slug: 'rye_whiskey' }, 'rye')).toBe(true);
  });

  it('returns true for a substring of display_name', () => {
    expect(matchesQuery({ ...baseRow, display_name: 'Rye Whiskey' }, 'whisk')).toBe(true);
  });

  it('returns true for a substring of any alias', () => {
    expect(matchesQuery({ ...baseRow, aliases: ['rye', 'straight rye'] }, 'straight')).toBe(true);
  });

  it('is case-insensitive', () => {
    expect(matchesQuery({ ...baseRow, slug: 'rye_whiskey' }, 'RYE')).toBe(true);
  });

  it('returns true for an empty query (no filter applied)', () => {
    expect(matchesQuery({ ...baseRow }, '')).toBe(true);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd web && npm test -- shapeData
```

Expected: FAIL — `isOrphan`, `matchesQuery`, `TOP_LEVEL_ALLOWLIST` not exported.

- [ ] **Step 3: Implement the additions**

Append to `web/src/components/taxonomy/shapeData.ts`:

```ts
export const TOP_LEVEL_ALLOWLIST: readonly string[] = [
  'whiskey',
  'gin',
  'rum',
  'tequila',
  'mezcal',
  'brandy',
  'vodka',
  'aquavit',
  'vermouth',
  'amaro',
  'bitters',
  'liqueur',
  'wine',
  'fortified_wine',
  'sparkling_wine',
  'beer',
  'cider',
  'juice',
  'syrup',
  'sweetener',
  'water',
  'dairy',
  'egg',
  'fruit',
  'herb',
  'spice',
  'salt',
  'tea',
  'coffee',
];

export function isOrphan(node: TaxonomyViewRow): boolean {
  if (node.parent_ids.length > 0) return false;
  return !TOP_LEVEL_ALLOWLIST.includes(node.slug);
}

export function matchesQuery(node: TaxonomyViewRow, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (q === '') return true;
  if (node.slug.toLowerCase().includes(q)) return true;
  if (node.display_name.toLowerCase().includes(q)) return true;
  return node.aliases.some((a) => a.toLowerCase().includes(q));
}
```

(The actual top-level slugs may differ slightly from the seed file. After this task lands, run a one-off psql to verify: any nodes with zero parents that are NOT on this list will be flagged as orphans. If you find legitimate roots that aren't listed, add them and update the test in a follow-up.)

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd web && npm test -- shapeData
```

Expected: PASS, all cases green.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/taxonomy/shapeData.ts web/src/components/taxonomy/shapeData.test.ts
git commit -m "$(cat <<'EOF'
shapeData: TOP_LEVEL_ALLOWLIST + isOrphan + matchesQuery

Orphan detection uses a curated allowlist of DAG roots. matchesQuery
does case-insensitive substring match across slug, display_name, and
aliases; empty query matches everything.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `shapeData.ts` — `neighborsOf` + `radialPositions`

**Files:**
- Modify: `web/src/components/taxonomy/shapeData.ts`
- Modify: `web/src/components/taxonomy/shapeData.test.ts`

These two are used by focus mode. `neighborsOf` returns the focused node + its parents and children; `radialPositions` deterministically lays parents on a top arc and children on a bottom arc around the focused node's coordinates.

- [ ] **Step 1: Append failing tests**

Append to `web/src/components/taxonomy/shapeData.test.ts`:

```ts
import { neighborsOf, radialPositions } from './shapeData';

describe('neighborsOf', () => {
  it('returns focused + parents + children, all distinct', () => {
    const rows: TaxonomyViewRow[] = [
      { ...baseRow, id: 1, slug: 'whiskey',     child_ids: [2] },
      { ...baseRow, id: 2, slug: 'rye_whiskey', parent_ids: [1], child_ids: [3] },
      { ...baseRow, id: 3, slug: 'rittenhouse', parent_ids: [2], child_ids: [] },
    ];
    const byId = new Map(rows.map((r) => [r.id, r]));
    const result = neighborsOf(rows[1], byId);
    expect(result.focused.id).toBe(2);
    expect(result.parents.map((p) => p.id)).toEqual([1]);
    expect(result.children.map((c) => c.id)).toEqual([3]);
  });

  it('skips ids that are not in the byId map (defensive)', () => {
    const rows: TaxonomyViewRow[] = [
      { ...baseRow, id: 2, slug: 'rye_whiskey', parent_ids: [99], child_ids: [101] },
    ];
    const byId = new Map(rows.map((r) => [r.id, r]));
    const result = neighborsOf(rows[0], byId);
    expect(result.parents).toEqual([]);
    expect(result.children).toEqual([]);
  });
});

describe('radialPositions', () => {
  const focused = { id: 2, x: 100, y: 200 };

  it('places parents above the focused node and children below', () => {
    const positions = radialPositions(focused, [{ id: 1 }], [{ id: 3 }], 50);
    expect(positions.get(1)!.y).toBeLessThan(focused.y);
    expect(positions.get(3)!.y).toBeGreaterThan(focused.y);
  });

  it('returns positions at the requested radius (within 0.5 px)', () => {
    const positions = radialPositions(focused, [{ id: 1 }, { id: 4 }], [{ id: 3 }], 50);
    for (const id of [1, 3, 4]) {
      const p = positions.get(id)!;
      const dx = p.x - focused.x;
      const dy = p.y - focused.y;
      expect(Math.hypot(dx, dy)).toBeCloseTo(50, 0);
    }
  });

  it('is deterministic for the same input', () => {
    const a = radialPositions(focused, [{ id: 1 }, { id: 4 }], [{ id: 3 }], 50);
    const b = radialPositions(focused, [{ id: 1 }, { id: 4 }], [{ id: 3 }], 50);
    expect(Array.from(a.entries())).toEqual(Array.from(b.entries()));
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd web && npm test -- shapeData
```

Expected: FAIL — `neighborsOf`, `radialPositions` not exported.

- [ ] **Step 3: Implement the additions**

Append to `web/src/components/taxonomy/shapeData.ts`:

```ts
export interface NeighborSet {
  focused: TaxonomyViewRow;
  parents: TaxonomyViewRow[];
  children: TaxonomyViewRow[];
}

export function neighborsOf(
  node: TaxonomyViewRow,
  byId: Map<number, TaxonomyViewRow>,
): NeighborSet {
  const lookup = (id: number) => byId.get(id);
  const parents = node.parent_ids.map(lookup).filter((n): n is TaxonomyViewRow => !!n);
  const children = node.child_ids.map(lookup).filter((n): n is TaxonomyViewRow => !!n);
  return { focused: node, parents, children };
}

export interface RadialFocus {
  id: number;
  x: number;
  y: number;
}

export interface RadialNeighbor {
  id: number;
}

export function radialPositions(
  focused: RadialFocus,
  parents: RadialNeighbor[],
  children: RadialNeighbor[],
  radius: number,
): Map<number, { x: number; y: number }> {
  const out = new Map<number, { x: number; y: number }>();
  // Parents arc the top semicircle (-PI to 0); children arc the bottom (0 to PI).
  const placeArc = (
    list: RadialNeighbor[],
    arcStart: number,
    arcEnd: number,
  ) => {
    if (list.length === 0) return;
    const sorted = [...list].sort((a, b) => a.id - b.id);
    if (sorted.length === 1) {
      const angle = (arcStart + arcEnd) / 2;
      out.set(sorted[0].id, {
        x: focused.x + radius * Math.cos(angle),
        y: focused.y + radius * Math.sin(angle),
      });
      return;
    }
    for (let i = 0; i < sorted.length; i++) {
      const t = i / (sorted.length - 1);
      const angle = arcStart + t * (arcEnd - arcStart);
      out.set(sorted[i].id, {
        x: focused.x + radius * Math.cos(angle),
        y: focused.y + radius * Math.sin(angle),
      });
    }
  };
  placeArc(parents,  -Math.PI, 0);
  placeArc(children, 0, Math.PI);
  return out;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd web && npm test -- shapeData
```

Expected: PASS, all cases green (including the original tests from Tasks 4 and 5).

- [ ] **Step 5: Commit**

```bash
git add web/src/components/taxonomy/shapeData.ts web/src/components/taxonomy/shapeData.test.ts
git commit -m "$(cat <<'EOF'
shapeData: neighborsOf + radialPositions

Focus-mode helpers. radialPositions arcs parents across the top
semicircle and children across the bottom, sorted by id for
determinism.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: `Taxonomy` page shell — fetch + loading/error/loaded states

**Files:**
- Create: `web/src/pages/Taxonomy.tsx`
- Create: `web/src/pages/Taxonomy.test.tsx`
- Modify: `web/src/App.tsx` (add `/taxonomy` route)

This task builds the page's outer shell — the fetch and the three render states. The graph canvas itself goes in Task 9. Until then, the loaded state shows a placeholder with the node count.

- [ ] **Step 1: Write the failing test**

Create `web/src/pages/Taxonomy.test.tsx`, modeled on `RecipeList.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../supabase', () => ({ supabase: { from: vi.fn() } }));
import { supabase } from '../supabase';
import { Taxonomy } from './Taxonomy';

type Row = {
  id: number;
  slug: string;
  display_name: string;
  role: string | null;
  role_default: string | null;
  is_cluster_node: boolean;
  is_defining_garnish: boolean;
  parent_ids: number[];
  child_ids: number[];
  aliases: string[];
  recipe_count: number;
};

function mockTaxonomyResponse(rows: Row[], error: unknown = null) {
  const select = vi.fn().mockResolvedValue({ data: rows, error });
  (supabase.from as unknown as ReturnType<typeof vi.fn>).mockReturnValue({ select });
  return { select };
}

function row(slug: string, overrides: Partial<Row> = {}): Row {
  return {
    id: Math.floor(Math.random() * 1_000_000),
    slug,
    display_name: slug,
    role: null,
    role_default: 'substance',
    is_cluster_node: false,
    is_defining_garnish: false,
    parent_ids: [],
    child_ids: [],
    aliases: [],
    recipe_count: 0,
    ...overrides,
  };
}

describe('<Taxonomy>', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows a loading state initially', () => {
    mockTaxonomyResponse([]);
    render(
      <MemoryRouter>
        <Taxonomy />
      </MemoryRouter>,
    );
    expect(screen.getByText(/loading taxonomy/i)).toBeInTheDocument();
  });

  it('shows an error state when the fetch fails', async () => {
    mockTaxonomyResponse([], { message: 'db unreachable' });
    render(
      <MemoryRouter>
        <Taxonomy />
      </MemoryRouter>,
    );
    expect(await screen.findByText(/db unreachable/i)).toBeInTheDocument();
  });

  it('shows the loaded state with node count', async () => {
    mockTaxonomyResponse([row('whiskey'), row('gin'), row('rum')]);
    render(
      <MemoryRouter>
        <Taxonomy />
      </MemoryRouter>,
    );
    expect(await screen.findByText(/3 nodes/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd web && npm test -- Taxonomy
```

Expected: FAIL — `Cannot find module './Taxonomy'`.

- [ ] **Step 3: Implement the page shell**

Create `web/src/pages/Taxonomy.tsx`:

```tsx
import { useEffect, useState } from 'react';
import { supabase } from '../supabase';
import type { TaxonomyViewRow } from '../components/taxonomy/shapeData';

type State =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'loaded'; rows: TaxonomyViewRow[] };

const COLUMNS =
  'id, slug, display_name, role, role_default, ' +
  'is_cluster_node, is_defining_garnish, ' +
  'parent_ids, child_ids, aliases, recipe_count';

export function Taxonomy() {
  const [state, setState] = useState<State>({ status: 'loading' });

  useEffect(() => {
    let cancelled = false;
    supabase
      .from('taxonomy_public')
      .select(COLUMNS)
      .then(({ data, error }) => {
        if (cancelled) return;
        if (error) {
          setState({ status: 'error', message: error.message });
          return;
        }
        setState({ status: 'loaded', rows: (data ?? []) as TaxonomyViewRow[] });
      });
    return () => { cancelled = true; };
  }, []);

  if (state.status === 'loading') {
    return <div className="page">Loading taxonomy…</div>;
  }
  if (state.status === 'error') {
    return <div className="page">Error: {state.message}</div>;
  }
  return (
    <div className="page">
      <p>{state.rows.length} nodes loaded.</p>
    </div>
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd web && npm test -- Taxonomy
```

Expected: PASS, three cases green.

- [ ] **Step 5: Wire `/taxonomy` into `App.tsx`**

Modify `web/src/App.tsx`:

```tsx
import { Routes, Route } from 'react-router-dom';
import { Header } from './components/Header';
import { RecipeList } from './pages/RecipeList';
import { RecipeDetail } from './pages/RecipeDetail';
import { Taxonomy } from './pages/Taxonomy';
import { ErrorPage } from './components/ErrorPage';

export default function App() {
  return (
    <>
      <Header />
      <Routes>
        <Route path="/" element={<RecipeList />} />
        <Route path="/recipes/:id" element={<RecipeDetail />} />
        <Route path="/taxonomy" element={<Taxonomy />} />
        <Route
          path="*"
          element={<ErrorPage title="Page not found" message="That URL doesn't match any page." />}
        />
      </Routes>
    </>
  );
}
```

- [ ] **Step 6: Run the full test suite**

```bash
cd web && npm test
```

Expected: all tests pass.

- [ ] **Step 7: Manual smoke**

Start the dev server and visit `/taxonomy`. You should see "166 nodes loaded." (or however many your local DB has).

```bash
cd web && npm run dev
```

Confirm in browser, then stop the dev server.

- [ ] **Step 8: Commit**

```bash
git add web/src/pages/Taxonomy.tsx web/src/pages/Taxonomy.test.tsx web/src/App.tsx
git commit -m "$(cat <<'EOF'
Add /taxonomy route + page shell with fetch states

Three-state shell: loading, error, loaded with node count. Loaded view
gets the canvas in a later commit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Deco styling foundation — `taxonomy.css` + page chrome

**Files:**
- Create: `web/src/components/taxonomy/taxonomy.css`
- Modify: `web/src/pages/Taxonomy.tsx`

No tests — this is pure CSS + layout chrome. The full visual contract lives in the design spec; the v2 mockup at `.superpowers/brainstorm/<id>/content/visual-design-v2.html` is the canonical visual reference. Open it in a browser if you need to compare side-by-side as you tune values.

- [ ] **Step 1: Create `taxonomy.css`**

Create `web/src/components/taxonomy/taxonomy.css`:

```css
/* Palette tokens. Used directly and via the .taxonomy-page scope. */
.taxonomy-page {
  --tx-walnut-deep: #160d05;
  --tx-walnut: #2a1d11;
  --tx-walnut-edge: #0d0703;
  --tx-gold: #c9a449;
  --tx-gold-bright: #e0c073;
  --tx-ivory: #e8d9b0;
  --tx-ivory-bright: #f0e0b0;
  --tx-cream: #f5e9c8;
  --tx-cream-deep: #ecddb4;
  --tx-brown-ink: #2c1d0c;
  --tx-brown-mid: #3a2a14;
  --tx-brown-soft: #5a3f1a;
  --tx-brown-faint: #7a5520;
  --tx-frame-edge: #8a6a35;

  --tx-substance: var(--tx-ivory);
  --tx-expression: #a85b3a;
  --tx-brand: #7a9a82;
  --tx-orphan: #a85b3a;

  font-family: 'Cormorant Garamond', Georgia, serif;
  color: var(--tx-ivory);
  background: radial-gradient(
    ellipse at center,
    var(--tx-walnut) 0%,
    var(--tx-walnut-deep) 70%,
    var(--tx-walnut-edge) 100%
  );
  position: relative;
  min-height: calc(100vh - 56px); /* account for site header */
  overflow: hidden;
}

.taxonomy-page__title {
  position: absolute;
  top: 18px;
  left: 50%;
  transform: translateX(-50%);
  text-align: center;
  pointer-events: none;
  z-index: 2;
}

.taxonomy-page__title-eyebrow {
  font-family: 'Cinzel', serif;
  font-size: 11px;
  letter-spacing: 0.4em;
  color: var(--tx-gold);
}

.taxonomy-page__title-main {
  font-family: 'Cinzel', serif;
  font-size: 22px;
  font-weight: 700;
  letter-spacing: 0.18em;
  color: var(--tx-ivory-bright);
  margin-top: 4px;
}

.taxonomy-page__title-rule {
  height: 1px;
  width: 160px;
  margin: 6px auto 0;
  background: linear-gradient(90deg, transparent, var(--tx-gold), transparent);
}

.taxonomy-page__corner {
  position: absolute;
  width: 56px;
  height: 56px;
  border: 1.5px solid var(--tx-gold);
  opacity: 0.85;
  pointer-events: none;
  z-index: 2;
}
.taxonomy-page__corner--tl { top: 12px; left: 12px;
  border-right: none; border-bottom: none; }
.taxonomy-page__corner--tr { top: 12px; right: 12px;
  border-left: none; border-bottom: none; }
.taxonomy-page__corner--bl { bottom: 12px; left: 12px;
  border-right: none; border-top: none; }
.taxonomy-page__corner--br { bottom: 12px; right: 12px;
  border-left: none; border-top: none; }

.taxonomy-page__corner::after {
  content: '';
  position: absolute;
  width: 24px; height: 24px;
  border: 1px solid var(--tx-gold);
}
.taxonomy-page__corner--tl::after { top: 6px; left: 6px;
  border-right: none; border-bottom: none; }
.taxonomy-page__corner--tr::after { top: 6px; right: 6px;
  border-left: none; border-bottom: none; }
.taxonomy-page__corner--bl::after { bottom: 6px; left: 6px;
  border-right: none; border-top: none; }
.taxonomy-page__corner--br::after { bottom: 6px; right: 6px;
  border-left: none; border-top: none; }

/* Cream "menu card" used by Legend, SearchBox, ZoomControls, SpecimenCard. */
.tx-card {
  background: linear-gradient(180deg, var(--tx-cream) 0%, var(--tx-cream-deep) 100%);
  color: var(--tx-brown-ink);
  border: 1px solid var(--tx-frame-edge);
  box-shadow:
    0 0 0 2px var(--tx-cream),
    0 0 0 3px var(--tx-frame-edge),
    0 6px 18px rgba(0, 0, 0, 0.4);
  font-family: 'Cormorant Garamond', Georgia, serif;
  border-radius: 2px;
}

.tx-card__heading {
  font-family: 'Cinzel', serif;
  font-size: 9px;
  letter-spacing: 0.25em;
  font-weight: 600;
  color: var(--tx-brown-faint);
}

.tx-rule {
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--tx-gold) 20%, var(--tx-gold) 80%, transparent);
}
```

- [ ] **Step 2: Update `Taxonomy.tsx` to render the deco chrome**

Modify the loaded branch of `web/src/pages/Taxonomy.tsx`:

```tsx
import { useEffect, useState } from 'react';
import { supabase } from '../supabase';
import type { TaxonomyViewRow } from '../components/taxonomy/shapeData';
import '../components/taxonomy/taxonomy.css';

type State =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'loaded'; rows: TaxonomyViewRow[] };

const COLUMNS =
  'id, slug, display_name, role, role_default, ' +
  'is_cluster_node, is_defining_garnish, ' +
  'parent_ids, child_ids, aliases, recipe_count';

export function Taxonomy() {
  const [state, setState] = useState<State>({ status: 'loading' });

  useEffect(() => {
    let cancelled = false;
    supabase
      .from('taxonomy_public')
      .select(COLUMNS)
      .then(({ data, error }) => {
        if (cancelled) return;
        if (error) {
          setState({ status: 'error', message: error.message });
          return;
        }
        setState({ status: 'loaded', rows: (data ?? []) as TaxonomyViewRow[] });
      });
    return () => { cancelled = true; };
  }, []);

  if (state.status === 'loading') {
    return <div className="page">Loading taxonomy…</div>;
  }
  if (state.status === 'error') {
    return <div className="page">Error: {state.message}</div>;
  }

  return (
    <div className="taxonomy-page">
      <div className="taxonomy-page__corner taxonomy-page__corner--tl" />
      <div className="taxonomy-page__corner taxonomy-page__corner--tr" />
      <div className="taxonomy-page__corner taxonomy-page__corner--bl" />
      <div className="taxonomy-page__corner taxonomy-page__corner--br" />

      <div className="taxonomy-page__title">
        <div className="taxonomy-page__title-eyebrow">— A COMPENDIUM OF —</div>
        <div className="taxonomy-page__title-main">SPIRITS &amp; LIQUEURS</div>
        <div className="taxonomy-page__title-rule" />
      </div>

      <div style={{ position: 'absolute', bottom: 24, left: 24, color: 'var(--tx-ivory)' }}>
        {state.rows.length} nodes loaded.
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Verify all tests still pass**

```bash
cd web && npm test
```

Expected: all green. The Taxonomy tests assert on the loaded text ("3 nodes") which still appears in a `<div>`.

- [ ] **Step 4: Manual visual check**

```bash
cd web && npm run dev
```

Visit `/taxonomy`. You should see: dark walnut field, four gold corner brackets, centered title cartouche reading "A COMPENDIUM OF / SPIRITS & LIQUEURS", and a small "166 nodes loaded." note in the lower-left corner. Stop the dev server when satisfied.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/taxonomy/taxonomy.css web/src/pages/Taxonomy.tsx
git commit -m "$(cat <<'EOF'
Taxonomy: deco field, gold corner brackets, title cartouche

Walnut radial gradient background + four corner brackets + centered
'A COMPENDIUM OF / SPIRITS & LIQUEURS' title. Palette tokens and the
shared cream 'menu card' surface live in taxonomy.css.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: `ForceCanvas` — wraps `react-force-graph-2d`

**Files:**
- Create: `web/src/components/taxonomy/ForceCanvas.tsx`
- Modify: `web/src/pages/Taxonomy.tsx` (render the canvas)

This is the visual core. We delegate force layout, pan/zoom, and event plumbing to the library. Custom canvas drawing (`nodeCanvasObject`) renders the bottle-cap aesthetic. No unit tests for the canvas — the lib mocks badly under jsdom and we'd be testing pixels. We rely on manual smoke checks and the `shapeData` tests for everything that *does* have testable logic.

- [ ] **Step 1: Implement `ForceCanvas.tsx`**

Create `web/src/components/taxonomy/ForceCanvas.tsx`:

```tsx
import { useMemo, useRef } from 'react';
import ForceGraph2D, { type ForceGraphMethods } from 'react-force-graph-2d';
import {
  effectiveRole,
  isOrphan,
  type TaxonomyNode,
  type TaxonomyLink,
  type TaxonomyRole,
} from './shapeData';

const ROLE_FILL: Record<TaxonomyRole, string> = {
  substance:  '#e8d9b0',
  expression: '#a85b3a',
  brand:      '#7a9a82',
  unknown:    '#888888',
};

const RING        = '#c9a449';
const NODE_BG     = '#1a0f06';
const ORPHAN_RING = '#a85b3a';
const LINK        = 'rgba(201, 164, 73, 0.55)';

interface Props {
  nodes: TaxonomyNode[];
  links: TaxonomyLink[];
  width: number;
  height: number;
  onNodeClick: (node: TaxonomyNode) => void;
  onNodeHover: (node: TaxonomyNode | null) => void;
}

export function ForceCanvas({
  nodes, links, width, height, onNodeClick, onNodeHover,
}: Props) {
  const ref = useRef<ForceGraphMethods | undefined>(undefined);

  const data = useMemo(() => ({ nodes, links }), [nodes, links]);

  return (
    <ForceGraph2D
      ref={ref}
      graphData={data}
      width={width}
      height={height}
      backgroundColor="rgba(0,0,0,0)"
      nodeRelSize={4}
      nodeVal={(n) => Math.sqrt((n as TaxonomyNode).recipe_count + 1) * 2.2}
      linkColor={() => LINK}
      linkWidth={0.6}
      linkCurvature={0.18}
      enableNodeDrag={false}
      cooldownTicks={120}
      onNodeClick={(n) => onNodeClick(n as TaxonomyNode)}
      onNodeHover={(n) => onNodeHover((n as TaxonomyNode | null) ?? null)}
      nodeCanvasObject={(node, ctx) => drawNode(node as TaxonomyNode & { x: number; y: number }, ctx)}
      nodeCanvasObjectMode={() => 'replace'}
    />
  );
}

function drawNode(
  node: TaxonomyNode & { x: number; y: number },
  ctx: CanvasRenderingContext2D,
) {
  const role = effectiveRole(node);
  const fill = ROLE_FILL[role];
  const radius = Math.max(3, Math.sqrt(node.recipe_count + 1) * 2.2);

  // Outer dark cap
  ctx.beginPath();
  ctx.arc(node.x, node.y, radius + 2.5, 0, 2 * Math.PI);
  ctx.fillStyle = NODE_BG;
  ctx.fill();

  // Cluster halo (thin extra ring)
  if (node.is_cluster_node) {
    ctx.beginPath();
    ctx.arc(node.x, node.y, radius + 1.7, 0, 2 * Math.PI);
    ctx.strokeStyle = RING;
    ctx.lineWidth = 0.4;
    ctx.stroke();
  }

  // Gold ring
  ctx.beginPath();
  ctx.arc(node.x, node.y, radius + 2.5, 0, 2 * Math.PI);
  if (isOrphan(node)) {
    ctx.strokeStyle = ORPHAN_RING;
    ctx.setLineDash([2.2, 1.8]);
    ctx.lineWidth = 1.0;
  } else {
    ctx.strokeStyle = RING;
    ctx.setLineDash([]);
    ctx.lineWidth = 1.0;
  }
  ctx.stroke();
  ctx.setLineDash([]);

  // Inner role-colored dot
  ctx.beginPath();
  ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI);
  ctx.fillStyle = fill;
  ctx.fill();
}
```

- [ ] **Step 2: Render the canvas in `Taxonomy.tsx`**

Modify `web/src/pages/Taxonomy.tsx` — replace the lower-left node-count div with the canvas. Add the import and a `useMemo` for the graph payload:

```tsx
import { useEffect, useMemo, useState } from 'react';
import { supabase } from '../supabase';
import { ForceCanvas } from '../components/taxonomy/ForceCanvas';
import {
  viewRowsToGraph,
  type TaxonomyNode,
  type TaxonomyViewRow,
} from '../components/taxonomy/shapeData';
import '../components/taxonomy/taxonomy.css';

// ... unchanged State + COLUMNS + useEffect ...

  if (state.status === 'loaded') {
    return <LoadedView rows={state.rows} />;
  }
}

function LoadedView({ rows }: { rows: TaxonomyViewRow[] }) {
  const { nodes, links } = useMemo(() => viewRowsToGraph(rows), [rows]);
  const [size, setSize] = useState({ w: window.innerWidth, h: window.innerHeight - 56 });

  useEffect(() => {
    const handler = () => setSize({ w: window.innerWidth, h: window.innerHeight - 56 });
    window.addEventListener('resize', handler);
    return () => window.removeEventListener('resize', handler);
  }, []);

  return (
    <div className="taxonomy-page">
      <div className="taxonomy-page__corner taxonomy-page__corner--tl" />
      <div className="taxonomy-page__corner taxonomy-page__corner--tr" />
      <div className="taxonomy-page__corner taxonomy-page__corner--bl" />
      <div className="taxonomy-page__corner taxonomy-page__corner--br" />

      <div className="taxonomy-page__title">
        <div className="taxonomy-page__title-eyebrow">— A COMPENDIUM OF —</div>
        <div className="taxonomy-page__title-main">SPIRITS &amp; LIQUEURS</div>
        <div className="taxonomy-page__title-rule" />
      </div>

      <ForceCanvas
        nodes={nodes as TaxonomyNode[]}
        links={links}
        width={size.w}
        height={size.h}
        onNodeClick={() => { /* wired in Task 14 */ }}
        onNodeHover={() => { /* wired in Task 14 */ }}
      />
    </div>
  );
}
```

(Hold the original `Taxonomy` function around the loading/error branches and delegate to `LoadedView` for the third state. The test from Task 7 still passes because "3 nodes" was previously the string under check — switch the assertion target now to a stable element if needed; see step 3.)

- [ ] **Step 3: Update `Taxonomy.test.tsx` to keep the loaded-state assertion meaningful**

Because the loaded view no longer renders "3 nodes", change the third test in `web/src/pages/Taxonomy.test.tsx` to assert on a stable structural element. Replace the third `it`:

```tsx
  it('renders the deco title cartouche when loaded', async () => {
    mockTaxonomyResponse([row('whiskey'), row('gin'), row('rum')]);
    render(
      <MemoryRouter>
        <Taxonomy />
      </MemoryRouter>,
    );
    expect(await screen.findByText(/spirits & liqueurs/i)).toBeInTheDocument();
  });
```

The canvas itself is not rendered under jsdom (the lib bails out gracefully when `HTMLCanvasElement` lacks a 2D context). That's fine — the assertion is on a sibling DOM element.

- [ ] **Step 4: Run tests**

```bash
cd web && npm test
```

Expected: all pass. If `react-force-graph-2d` throws under jsdom anyway, mock it inside the test file:

```tsx
vi.mock('../components/taxonomy/ForceCanvas', () => ({ ForceCanvas: () => null }));
```

Apply the mock only if the test fails; do not add it pre-emptively.

- [ ] **Step 5: Manual visual check**

```bash
cd web && npm run dev
```

Visit `/taxonomy`. You should see ~166 small bottle-cap nodes settling into a force-directed layout, gold curved edges, dashed-red orphan rings on a few nodes, the title cartouche overlaid, and corner brackets. Pan with click-drag on background, zoom with mouse-wheel.

- [ ] **Step 6: Commit**

```bash
git add web/src/components/taxonomy/ForceCanvas.tsx web/src/pages/Taxonomy.tsx web/src/pages/Taxonomy.test.tsx
git commit -m "$(cat <<'EOF'
Taxonomy: render the force-directed canvas

Wraps react-force-graph-2d with a custom node draw that paints
bottle-cap nodes (dark fill, gold ring, optional cluster halo, dashed
ring for orphans). Click and hover handlers are stubs until focus
mode lands.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: `Legend` (presentational) + tooltip on hover

**Files:**
- Create: `web/src/components/taxonomy/Legend.tsx`
- Modify: `web/src/pages/Taxonomy.tsx`

The legend is static markup. The tooltip is a small absolutely-positioned card that follows the cursor while hovering a node.

- [ ] **Step 1: Create `Legend.tsx`**

```tsx
export function Legend() {
  return (
    <div
      className="tx-card"
      style={{
        position: 'absolute', top: 14, right: 14, zIndex: 2,
        padding: '8px 12px', fontSize: 12, lineHeight: 1.55, width: 160,
      }}
    >
      <div className="tx-card__heading" style={{ marginBottom: 4 }}>LEGEND</div>
      <LegendDot color="#e8d9b0" /> substance<br />
      <LegendDot color="#a85b3a" /> expression<br />
      <LegendDot color="#7a9a82" /> brand<br />
      <div style={{ marginTop: 4, fontStyle: 'italic', color: '#5a3f1a' }}>
        ◯ ring = cluster · ⌀ dashed = orphan
      </div>
    </div>
  );
}

function LegendDot({ color }: { color: string }) {
  return (
    <span
      style={{
        display: 'inline-block', width: 9, height: 9, borderRadius: '50%',
        background: color, border: '1px solid #8a6a35', verticalAlign: 'middle',
        marginRight: 6,
      }}
    />
  );
}
```

- [ ] **Step 2: Wire the legend and a hover tooltip into `Taxonomy.tsx`**

In `LoadedView`, add a `hovered` state, render `<Legend />` and a tooltip when `hovered != null`:

```tsx
import { Legend } from '../components/taxonomy/Legend';
// ...

function LoadedView({ rows }: { rows: TaxonomyViewRow[] }) {
  const { nodes, links } = useMemo(() => viewRowsToGraph(rows), [rows]);
  const [size, setSize] = useState({ w: window.innerWidth, h: window.innerHeight - 56 });
  const [hovered, setHovered] = useState<TaxonomyNode | null>(null);

  // ... resize effect unchanged ...

  return (
    <div className="taxonomy-page">
      {/* corner brackets unchanged */}
      {/* title cartouche unchanged */}

      <ForceCanvas
        nodes={nodes as TaxonomyNode[]}
        links={links}
        width={size.w}
        height={size.h}
        onNodeClick={() => { /* Task 14 */ }}
        onNodeHover={setHovered}
      />

      <Legend />

      {hovered && (
        <div
          className="tx-card"
          style={{
            position: 'absolute', top: 80, right: 14, zIndex: 3,
            padding: '8px 12px', fontSize: 12, lineHeight: 1.5, width: 200,
          }}
        >
          <div style={{ fontFamily: "'Cinzel', serif", fontWeight: 600, letterSpacing: '0.12em' }}>
            {hovered.display_name}
          </div>
          <div style={{ color: '#5a3f1a', fontStyle: 'italic' }}>
            {effectiveRoleLabel(hovered)} · {hovered.recipe_count} recipes · {hovered.aliases.length} aliases
          </div>
        </div>
      )}
    </div>
  );
}

function effectiveRoleLabel(n: TaxonomyNode): string {
  if (n.role) return n.role;
  if (n.role_default) return `${n.role_default}?`;
  return 'unknown';
}
```

- [ ] **Step 3: Verify tests still pass**

```bash
cd web && npm test
```

Expected: all green.

- [ ] **Step 4: Manual visual check**

Dev server. Hover any node; the tooltip card should appear in the upper-right area below the legend, showing display_name, role label (with `?` if inferred), recipe count, alias count.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/taxonomy/Legend.tsx web/src/pages/Taxonomy.tsx
git commit -m "$(cat <<'EOF'
Taxonomy: legend + hover tooltip

Static legend top-right. Hovering a node renders a cream menu-card
tooltip with display_name, role label (with ? when inferred from
role_default), recipe count, and alias count.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: `SearchBox`

**Files:**
- Create: `web/src/components/taxonomy/SearchBox.tsx`
- Create: `web/src/components/taxonomy/SearchBox.test.tsx`
- Modify: `web/src/pages/Taxonomy.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SearchBox } from './SearchBox';

describe('<SearchBox>', () => {
  it('emits onChange as the user types', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<SearchBox value="" onChange={onChange} onSubmit={() => {}} />);
    await user.type(screen.getByRole('textbox'), 'rye');
    expect(onChange).toHaveBeenLastCalledWith('rye');
  });

  it('emits onSubmit on Enter', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<SearchBox value="rye" onChange={() => {}} onSubmit={onSubmit} />);
    await user.type(screen.getByRole('textbox'), '{Enter}');
    expect(onSubmit).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run, verify fail**

```bash
cd web && npm test -- SearchBox
```

Expected: `Cannot find module './SearchBox'`.

- [ ] **Step 3: Implement**

```tsx
interface Props {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
}

export function SearchBox({ value, onChange, onSubmit }: Props) {
  return (
    <div
      className="tx-card"
      style={{
        position: 'absolute', top: 14, left: 14, zIndex: 3,
        padding: '8px 12px', width: 180,
      }}
    >
      <div className="tx-card__heading" style={{ marginBottom: 4 }}>SEARCH</div>
      <input
        type="text"
        value={value}
        placeholder="rye, vermouth, …"
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter') onSubmit(); }}
        style={{
          width: '100%', background: 'transparent', border: 'none',
          borderBottom: '1px solid #8a6a35', outline: 'none',
          fontFamily: "'Cormorant Garamond', Georgia, serif",
          fontStyle: 'italic', fontSize: 14, color: '#3a2a14', padding: '2px 0',
        }}
      />
    </div>
  );
}
```

(`<input>`s without an explicit `type="text"` and inside a non-form parent still expose `role="textbox"` to RTL.)

- [ ] **Step 4: Run, verify pass**

```bash
cd web && npm test -- SearchBox
```

Expected: PASS.

- [ ] **Step 5: Wire into `Taxonomy.tsx`**

Add `query` state, render `<SearchBox value={query} onChange={setQuery} onSubmit={...} />`. Filter nodes by `matchesQuery`. Hide non-matches by setting node opacity in `ForceCanvas` — extend `ForceCanvas` Props with `dimmedIds: Set<number>`, set node alpha to 0.18 when `dimmedIds.has(node.id)`. Update the `drawNode` to honor it: read `dimmedIds` via a closure passed in.

In `Taxonomy.tsx`:

```tsx
import { SearchBox } from '../components/taxonomy/SearchBox';
import { matchesQuery } from '../components/taxonomy/shapeData';
// ...
const [query, setQuery] = useState('');

const dimmedIds = useMemo(() => {
  if (query.trim() === '') return new Set<number>();
  return new Set(rows.filter((r) => !matchesQuery(r, query)).map((r) => r.id));
}, [rows, query]);

// ...
<SearchBox
  value={query}
  onChange={setQuery}
  onSubmit={() => { /* focus top match in Task 14 */ }}
/>
<ForceCanvas
  nodes={nodes as TaxonomyNode[]}
  links={links}
  width={size.w}
  height={size.h}
  dimmedIds={dimmedIds}
  onNodeClick={() => {}}
  onNodeHover={setHovered}
/>
```

In `ForceCanvas.tsx`, accept and use `dimmedIds`:

```tsx
interface Props {
  nodes: TaxonomyNode[];
  links: TaxonomyLink[];
  width: number;
  height: number;
  dimmedIds?: Set<number>;
  onNodeClick: (node: TaxonomyNode) => void;
  onNodeHover: (node: TaxonomyNode | null) => void;
}
```

In `drawNode`, fetch dim state from a closure-captured `dimmedIds`:

```tsx
nodeCanvasObject={(node, ctx) => {
  const n = node as TaxonomyNode & { x: number; y: number };
  const dimmed = dimmedIds?.has(n.id) ?? false;
  ctx.globalAlpha = dimmed ? 0.18 : 1;
  drawNode(n, ctx);
  ctx.globalAlpha = 1;
}}
```

- [ ] **Step 6: Run all tests**

```bash
cd web && npm test
```

Expected: all green.

- [ ] **Step 7: Manual visual check**

Type "rye" — non-matching nodes dim. Clear — all return.

- [ ] **Step 8: Commit**

```bash
git add web/src/components/taxonomy/SearchBox.tsx web/src/components/taxonomy/SearchBox.test.tsx web/src/components/taxonomy/ForceCanvas.tsx web/src/pages/Taxonomy.tsx
git commit -m "$(cat <<'EOF'
Taxonomy: live search box dims non-matching nodes

Cmd-K-style cream menu card upper-left. Substring match on slug,
display_name, and aliases via shapeData.matchesQuery. Non-matches
render at 0.18 alpha; layout stays stable.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: `FilterChips`

**Files:**
- Create: `web/src/components/taxonomy/FilterChips.tsx`
- Create: `web/src/components/taxonomy/FilterChips.test.tsx`
- Modify: `web/src/pages/Taxonomy.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FilterChips, type FilterKey } from './FilterChips';

describe('<FilterChips>', () => {
  it('renders one chip per filter key', () => {
    render(<FilterChips active={new Set()} onToggle={() => {}} />);
    for (const label of ['substance', 'expression', 'brand', 'cluster', 'orphan', 'no aliases', 'zero recipes']) {
      expect(screen.getByRole('button', { name: new RegExp(label, 'i') })).toBeInTheDocument();
    }
  });

  it('emits onToggle with the chip key when clicked', async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();
    render(<FilterChips active={new Set()} onToggle={onToggle} />);
    await user.click(screen.getByRole('button', { name: /expression/i }));
    expect(onToggle).toHaveBeenCalledWith('expression' satisfies FilterKey);
  });

  it('marks active chips with aria-pressed=true', () => {
    render(<FilterChips active={new Set(['orphan'])} onToggle={() => {}} />);
    const chip = screen.getByRole('button', { name: /orphan/i });
    expect(chip).toHaveAttribute('aria-pressed', 'true');
  });
});
```

- [ ] **Step 2: Run, verify fail**

```bash
cd web && npm test -- FilterChips
```

- [ ] **Step 3: Implement**

```tsx
export type FilterKey =
  | 'substance' | 'expression' | 'brand'
  | 'cluster' | 'orphan' | 'no aliases' | 'zero recipes';

const ORDERED: FilterKey[] = [
  'substance', 'expression', 'brand',
  'cluster', 'orphan', 'no aliases', 'zero recipes',
];

interface Props {
  active: Set<FilterKey>;
  onToggle: (key: FilterKey) => void;
}

export function FilterChips({ active, onToggle }: Props) {
  return (
    <div
      style={{
        position: 'absolute', top: 70, left: 14, zIndex: 3,
        display: 'flex', flexWrap: 'wrap', gap: 4, maxWidth: 220,
      }}
    >
      {ORDERED.map((key) => {
        const isActive = active.has(key);
        return (
          <button
            key={key}
            type="button"
            aria-pressed={isActive}
            onClick={() => onToggle(key)}
            style={{
              fontFamily: "'Cinzel', serif",
              fontSize: 9, letterSpacing: '0.2em',
              padding: '3px 8px',
              borderRadius: 10,
              border: '1px solid #8a6a35',
              background: isActive ? '#c9a449' : 'rgba(245, 233, 200, 0.85)',
              color: isActive ? '#1a0f06' : '#3a2a14',
              cursor: 'pointer',
              textTransform: 'uppercase',
            }}
          >
            {key}
          </button>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 4: Run, verify pass**

```bash
cd web && npm test -- FilterChips
```

- [ ] **Step 5: Wire into `Taxonomy.tsx`**

Add `filters` state and combine with the existing `dimmedIds`:

```tsx
import { FilterChips, type FilterKey } from '../components/taxonomy/FilterChips';
import { effectiveRole, isOrphan } from '../components/taxonomy/shapeData';
// ...
const [filters, setFilters] = useState<Set<FilterKey>>(new Set());

const dimmedIds = useMemo(() => {
  const dim = new Set<number>();
  for (const r of rows) {
    if (query.trim() !== '' && !matchesQuery(r, query)) { dim.add(r.id); continue; }
    if (filters.size > 0 && !rowMatchesFilters(r, filters)) { dim.add(r.id); }
  }
  return dim;
}, [rows, query, filters]);

function toggleFilter(key: FilterKey) {
  setFilters((prev) => {
    const next = new Set(prev);
    if (next.has(key)) next.delete(key); else next.add(key);
    return next;
  });
}

// helper:
function rowMatchesFilters(r: TaxonomyViewRow, active: Set<FilterKey>): boolean {
  // OR within role chips, AND across families. Simpler v1: a node passes
  // if it matches every active chip. If only role chips are active,
  // require role match; otherwise apply each chip individually.
  for (const f of active) {
    if (f === 'substance' || f === 'expression' || f === 'brand') {
      if (effectiveRole(r) !== f) return false;
    } else if (f === 'cluster' && !r.is_cluster_node) return false;
    else if (f === 'orphan' && !isOrphan(r)) return false;
    else if (f === 'no aliases' && r.aliases.length > 0) return false;
    else if (f === 'zero recipes' && r.recipe_count > 0) return false;
  }
  return true;
}
```

(Yes, AND-across-chips makes role chips mutually exclusive — that's fine for v1; users picking "substance + expression" together would expect "either" but the simpler v1 returns nothing, which makes the bug obvious. We can rework to OR-within-family, AND-across-families later if it becomes annoying.)

Render `<FilterChips active={filters} onToggle={toggleFilter} />` next to `<SearchBox />`.

- [ ] **Step 6: Run all tests**

```bash
cd web && npm test
```

Expected: all green.

- [ ] **Step 7: Manual visual check**

Toggle "orphan" — only orphan-flagged nodes stay visible. Toggle "cluster" — only cluster nodes. Untoggle all — all return.

- [ ] **Step 8: Commit**

```bash
git add web/src/components/taxonomy/FilterChips.tsx web/src/components/taxonomy/FilterChips.test.tsx web/src/pages/Taxonomy.tsx
git commit -m "$(cat <<'EOF'
Taxonomy: filter chips for QA signals

Toggleable Cinzel chips for role (substance/expression/brand) and
flag (cluster/orphan/no aliases/zero recipes). Combines with the
search query — non-matches dim instead of being removed so the layout
stays stable.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: `ZoomControls`

**Files:**
- Create: `web/src/components/taxonomy/ZoomControls.tsx`
- Create: `web/src/components/taxonomy/ZoomControls.test.tsx`
- Modify: `web/src/components/taxonomy/ForceCanvas.tsx` (expose ref + zoom methods)
- Modify: `web/src/pages/Taxonomy.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ZoomControls } from './ZoomControls';

describe('<ZoomControls>', () => {
  it('emits zoomIn on +', async () => {
    const user = userEvent.setup();
    const onZoomIn = vi.fn();
    render(<ZoomControls onZoomIn={onZoomIn} onZoomOut={() => {}} onFit={() => {}} />);
    await user.click(screen.getByRole('button', { name: /zoom in/i }));
    expect(onZoomIn).toHaveBeenCalled();
  });

  it('emits zoomOut on −', async () => {
    const user = userEvent.setup();
    const onZoomOut = vi.fn();
    render(<ZoomControls onZoomIn={() => {}} onZoomOut={onZoomOut} onFit={() => {}} />);
    await user.click(screen.getByRole('button', { name: /zoom out/i }));
    expect(onZoomOut).toHaveBeenCalled();
  });

  it('emits fit on the fit button', async () => {
    const user = userEvent.setup();
    const onFit = vi.fn();
    render(<ZoomControls onZoomIn={() => {}} onZoomOut={() => {}} onFit={onFit} />);
    await user.click(screen.getByRole('button', { name: /fit/i }));
    expect(onFit).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run, verify fail**

- [ ] **Step 3: Implement**

```tsx
interface Props {
  onZoomIn: () => void;
  onZoomOut: () => void;
  onFit: () => void;
}

export function ZoomControls({ onZoomIn, onZoomOut, onFit }: Props) {
  return (
    <div
      className="tx-card"
      style={{
        position: 'absolute', bottom: 24, right: 24, zIndex: 3,
        padding: 0, display: 'flex',
        fontFamily: "'Cinzel', serif", fontSize: 13,
      }}
    >
      <button type="button" aria-label="Zoom out" onClick={onZoomOut}
        style={btn('right')}>−</button>
      <button type="button" aria-label="Zoom in" onClick={onZoomIn}
        style={btn('right')}>+</button>
      <button type="button" aria-label="Fit to view" onClick={onFit}
        style={btn('none')}>⊡</button>
    </div>
  );
}

function btn(borderRight: 'right' | 'none'): React.CSSProperties {
  return {
    background: 'transparent', border: 'none',
    padding: '6px 10px', cursor: 'pointer', color: '#3a2a14',
    borderRight: borderRight === 'right' ? '1px solid #8a6a35' : 'none',
    fontFamily: 'inherit', fontSize: 'inherit',
  };
}
```

- [ ] **Step 4: Run, verify pass**

- [ ] **Step 5: Expose imperative zoom on `ForceCanvas`**

Convert `ForceCanvas` to use `forwardRef`:

```tsx
import { forwardRef, useImperativeHandle, useMemo, useRef } from 'react';
import ForceGraph2D, { type ForceGraphMethods } from 'react-force-graph-2d';

export interface ForceCanvasHandle {
  zoom: (factor: number) => void;
  fit: () => void;
  centerAt: (x: number, y: number, ms?: number) => void;
}

export const ForceCanvas = forwardRef<ForceCanvasHandle, Props>(function ForceCanvas(
  { nodes, links, width, height, dimmedIds, onNodeClick, onNodeHover }, ref,
) {
  const inner = useRef<ForceGraphMethods | undefined>(undefined);

  useImperativeHandle(ref, () => ({
    zoom: (factor) => {
      const g = inner.current;
      if (!g) return;
      const cur = g.zoom();
      g.zoom(cur * factor, 250);
    },
    fit: () => inner.current?.zoomToFit(400, 60),
    centerAt: (x, y, ms = 400) => inner.current?.centerAt(x, y, ms),
  }), []);

  // ... existing JSX, use `inner` instead of `ref` on ForceGraph2D ...
});
```

- [ ] **Step 6: Wire `ZoomControls` into `Taxonomy.tsx`**

```tsx
import { ZoomControls } from '../components/taxonomy/ZoomControls';
// ...
const canvasRef = useRef<ForceCanvasHandle>(null);

<ForceCanvas ref={canvasRef} ... />
<ZoomControls
  onZoomIn={() => canvasRef.current?.zoom(1.4)}
  onZoomOut={() => canvasRef.current?.zoom(1 / 1.4)}
  onFit={() => canvasRef.current?.fit()}
/>
```

- [ ] **Step 7: Run all tests**

```bash
cd web && npm test
```

- [ ] **Step 8: Manual check**

`+` zooms in, `−` zooms out, `⊡` fits all nodes.

- [ ] **Step 9: Commit**

```bash
git add web/src/components/taxonomy/ZoomControls.tsx web/src/components/taxonomy/ZoomControls.test.tsx web/src/components/taxonomy/ForceCanvas.tsx web/src/pages/Taxonomy.tsx
git commit -m "$(cat <<'EOF'
Taxonomy: zoom controls

Bottom-right deco button group: − / + / fit. Drives an imperative
handle exposed by ForceCanvas which delegates to the underlying
react-force-graph-2d ref.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: `SpecimenCard` + focus mode wiring + Esc/click-empty exit

**Files:**
- Create: `web/src/components/taxonomy/SpecimenCard.tsx`
- Create: `web/src/components/taxonomy/SpecimenCard.test.tsx`
- Modify: `web/src/components/taxonomy/ForceCanvas.tsx` (focused-id-aware draw + click-empty handler + neighbor pinning)
- Modify: `web/src/pages/Taxonomy.tsx` (focus state + camera animation + dim non-neighbors)

This is the biggest task: it integrates everything from prior tasks into the focus interaction.

- [ ] **Step 1: Write the failing test for `SpecimenCard`**

```tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SpecimenCard } from './SpecimenCard';
import type { TaxonomyNode } from './shapeData';

const node: TaxonomyNode = {
  id: 1, slug: 'rye_whiskey', display_name: 'Rye Whiskey',
  role: null, role_default: 'substance',
  is_cluster_node: true, is_defining_garnish: false,
  parent_ids: [10, 11], child_ids: [20, 21],
  aliases: ['rye', 'rye whisky'], recipe_count: 47,
};

describe('<SpecimenCard>', () => {
  it('renders the focused node properties', () => {
    render(<SpecimenCard node={node} onDismiss={() => {}} />);
    expect(screen.getByText('RYE WHISKEY')).toBeInTheDocument();
    expect(screen.getByText(/47 drinks call for this/i)).toBeInTheDocument();
    expect(screen.getByText(/rye, rye whisky/)).toBeInTheDocument();
    expect(screen.getByText(/cluster node/i)).toBeInTheDocument();
  });

  it('calls onDismiss when Escape is pressed', async () => {
    const user = userEvent.setup();
    const onDismiss = vi.fn();
    render(<SpecimenCard node={node} onDismiss={onDismiss} />);
    await user.keyboard('{Escape}');
    expect(onDismiss).toHaveBeenCalled();
  });

  it('writes the slug to the clipboard when the slug row is clicked', async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(<SpecimenCard node={node} onDismiss={() => {}} />);
    await user.click(screen.getByText(/rye_whiskey/));
    expect(writeText).toHaveBeenCalledWith('rye_whiskey');
  });
});
```

- [ ] **Step 2: Run, verify fail**

```bash
cd web && npm test -- SpecimenCard
```

- [ ] **Step 3: Implement `SpecimenCard.tsx`**

```tsx
import { useEffect } from 'react';
import type { TaxonomyNode } from './shapeData';

interface Props {
  node: TaxonomyNode;
  onDismiss: () => void;
}

export function SpecimenCard({ node, onDismiss }: Props) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onDismiss(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onDismiss]);

  const copySlug = async () => {
    try { await navigator.clipboard.writeText(node.slug); } catch { /* swallow */ }
  };

  return (
    <aside
      className="tx-card"
      style={{
        position: 'absolute', top: 0, right: 0, bottom: 0, width: 240, zIndex: 4,
        padding: '20px 18px', borderRadius: 0, borderRight: 'none',
      }}
    >
      <div style={{ textAlign: 'center' }}>
        <div className="tx-card__heading">— SPECIMEN —</div>
        <div
          style={{
            fontFamily: "'Cinzel', serif", fontSize: 16, fontWeight: 700,
            letterSpacing: '0.18em', color: '#2c1d0c', marginTop: 4,
            textTransform: 'uppercase',
          }}
        >
          {node.display_name}
        </div>
        <div className="tx-rule" style={{ margin: '8px 16px' }} />
      </div>

      <div style={{ fontSize: 13, lineHeight: 1.55, color: '#3a2a14' }}>
        <div className="tx-card__heading" style={{ marginTop: 4 }}>PROPERTIES</div>
        <Row label="role" value={node.role ?? '—'} />
        <Row label="role default" value={node.role_default ?? '—'} />
        <Row label="cluster node" value={node.is_cluster_node ? '✓' : '—'} />
        <Row label="defining garnish" value={node.is_defining_garnish ? '✓' : '—'} />

        <div className="tx-card__heading" style={{ marginTop: 10 }}>
          ALIASES <span style={{ fontStyle: 'italic', color: '#8a6a35' }}>({node.aliases.length})</span>
        </div>
        <div style={{ fontStyle: 'italic' }}>{node.aliases.join(', ') || '—'}</div>

        <div className="tx-card__heading" style={{ marginTop: 10 }}>RECIPES</div>
        <div>{node.recipe_count} drinks call for this</div>

        <div className="tx-card__heading" style={{ marginTop: 10 }}>SLUG</div>
        <div
          onClick={copySlug}
          role="button"
          tabIndex={0}
          style={{
            fontFamily: 'ui-monospace, monospace', fontSize: 12,
            cursor: 'pointer', userSelect: 'none',
          }}
        >
          ⊕ {node.slug}
        </div>
      </div>

      <div
        style={{
          position: 'absolute', left: 0, right: 0, bottom: 16, textAlign: 'center',
          fontFamily: "'Cinzel', serif", fontSize: 9, letterSpacing: '0.3em', color: '#7a5520',
        }}
      >
        ESC TO DISMISS
      </div>
    </aside>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
      <span>{label}</span>
      <span style={{ fontStyle: 'italic' }}>{value}</span>
    </div>
  );
}
```

- [ ] **Step 4: Run SpecimenCard tests**

```bash
cd web && npm test -- SpecimenCard
```

Expected: all three pass.

- [ ] **Step 5: Add focus mode to `Taxonomy.tsx`**

Add focused state, the neighbor calculation, the radial pinning, the click-empty handler, and render the SpecimenCard when something is focused. Replace `LoadedView` with:

```tsx
function LoadedView({ rows }: { rows: TaxonomyViewRow[] }) {
  const { nodes, links } = useMemo(() => viewRowsToGraph(rows), [rows]);
  const byId = useMemo(() => new Map(rows.map((r) => [r.id, r])), [rows]);
  const [size, setSize] = useState({ w: window.innerWidth, h: window.innerHeight - 56 });
  const [hovered, setHovered] = useState<TaxonomyNode | null>(null);
  const [focusedId, setFocusedId] = useState<number | null>(null);
  const [query, setQuery] = useState('');
  const [filters, setFilters] = useState<Set<FilterKey>>(new Set());
  const canvasRef = useRef<ForceCanvasHandle>(null);

  useEffect(() => {
    const handler = () => setSize({ w: window.innerWidth, h: window.innerHeight - 56 });
    window.addEventListener('resize', handler);
    return () => window.removeEventListener('resize', handler);
  }, []);

  const focusedNode = focusedId ? byId.get(focusedId) ?? null : null;

  // Compute neighbor set + dimming.
  const neighborIds = useMemo(() => {
    if (!focusedNode) return null;
    const { parents, children } = neighborsOf(focusedNode, byId);
    return new Set<number>([
      focusedNode.id,
      ...parents.map((p) => p.id),
      ...children.map((c) => c.id),
    ]);
  }, [focusedNode, byId]);

  const dimmedIds = useMemo(() => {
    const dim = new Set<number>();
    for (const r of rows) {
      let dimMe = false;
      if (neighborIds && !neighborIds.has(r.id)) dimMe = true;
      if (query.trim() !== '' && !matchesQuery(r, query)) dimMe = true;
      if (filters.size > 0 && !rowMatchesFilters(r, filters)) dimMe = true;
      if (dimMe) dim.add(r.id);
    }
    return dim;
  }, [rows, neighborIds, query, filters]);

  // Pin radial neighbors when focused.
  useEffect(() => {
    if (!focusedNode) {
      // Release pins.
      for (const n of nodes as Array<TaxonomyNode & { fx?: number; fy?: number; x?: number; y?: number }>) {
        n.fx = undefined; n.fy = undefined;
      }
      return;
    }
    const focusedXY = nodes.find((n) => n.id === focusedId) as { x?: number; y?: number } | undefined;
    if (!focusedXY?.x || !focusedXY?.y) return;
    const { parents, children } = neighborsOf(focusedNode, byId);
    const positions = radialPositions(
      { id: focusedNode.id, x: focusedXY.x, y: focusedXY.y },
      parents, children,
      Math.min(size.w, size.h) * 0.22,
    );
    for (const n of nodes as Array<TaxonomyNode & { fx?: number; fy?: number }>) {
      const p = positions.get(n.id);
      if (p) { n.fx = p.x; n.fy = p.y; }
      else if (n.id === focusedNode.id) { n.fx = focusedXY.x; n.fy = focusedXY.y; }
      else { n.fx = undefined; n.fy = undefined; }
    }
    canvasRef.current?.centerAt(focusedXY.x, focusedXY.y, 600);
  }, [focusedNode, nodes, byId, size, focusedId]);

  return (
    <div className="taxonomy-page">
      <div className="taxonomy-page__corner taxonomy-page__corner--tl" />
      <div className="taxonomy-page__corner taxonomy-page__corner--tr" />
      <div className="taxonomy-page__corner taxonomy-page__corner--bl" />
      <div className="taxonomy-page__corner taxonomy-page__corner--br" />

      <div className="taxonomy-page__title">
        <div className="taxonomy-page__title-eyebrow">— A COMPENDIUM OF —</div>
        <div className="taxonomy-page__title-main">SPIRITS &amp; LIQUEURS</div>
        <div className="taxonomy-page__title-rule" />
      </div>

      <ForceCanvas
        ref={canvasRef}
        nodes={nodes as TaxonomyNode[]}
        links={links}
        width={size.w}
        height={size.h}
        dimmedIds={dimmedIds}
        onNodeClick={(n) => setFocusedId(n.id)}
        onNodeHover={setHovered}
        onBackgroundClick={() => setFocusedId(null)}
      />

      <SearchBox
        value={query}
        onChange={setQuery}
        onSubmit={() => {
          const top = rows.find((r) => matchesQuery(r, query));
          if (top) setFocusedId(top.id);
        }}
      />
      <FilterChips
        active={filters}
        onToggle={(k) => setFilters((prev) => {
          const next = new Set(prev);
          if (next.has(k)) next.delete(k); else next.add(k);
          return next;
        })}
      />
      <Legend />
      <ZoomControls
        onZoomIn={() => canvasRef.current?.zoom(1.4)}
        onZoomOut={() => canvasRef.current?.zoom(1 / 1.4)}
        onFit={() => canvasRef.current?.fit()}
      />

      {hovered && !focusedNode && (
        <div className="tx-card" style={{
          position: 'absolute', top: 80, right: 14, zIndex: 3,
          padding: '8px 12px', fontSize: 12, lineHeight: 1.5, width: 200,
        }}>
          <div style={{ fontFamily: "'Cinzel', serif", fontWeight: 600, letterSpacing: '0.12em' }}>
            {hovered.display_name}
          </div>
          <div style={{ color: '#5a3f1a', fontStyle: 'italic' }}>
            {effectiveRoleLabel(hovered)} · {hovered.recipe_count} recipes · {hovered.aliases.length} aliases
          </div>
        </div>
      )}

      {focusedNode && (
        <SpecimenCard node={focusedNode} onDismiss={() => setFocusedId(null)} />
      )}
    </div>
  );
}
```

- [ ] **Step 6: Add `onBackgroundClick` to `ForceCanvas`**

In `ForceCanvas.tsx`, extend Props and pass to ForceGraph2D:

```tsx
interface Props {
  // ... existing ...
  onBackgroundClick?: () => void;
}

// inside JSX:
onBackgroundClick={onBackgroundClick}
```

- [ ] **Step 7: Run all tests**

```bash
cd web && npm test
```

Expected: all green.

- [ ] **Step 8: Manual visual check (the big one)**

Dev server. Click `rye_whiskey`. Camera animates to it; parents pin to the top arc, children to the bottom; non-neighbors fade. Specimen card slides in from the right with all properties. Press Esc — pins release, card slides out, layout returns. Type "negroni" in search and hit Enter — it focuses the top-matching node.

- [ ] **Step 9: Commit**

```bash
git add web/src/components/taxonomy/SpecimenCard.tsx web/src/components/taxonomy/SpecimenCard.test.tsx web/src/components/taxonomy/ForceCanvas.tsx web/src/pages/Taxonomy.tsx
git commit -m "$(cat <<'EOF'
Taxonomy: focus mode + specimen card + Esc/click-empty exit

Click a node: it centers, parents pin to a top arc, children to a
bottom arc, non-neighbors dim. SpecimenCard slides in from the right
with role / cluster / garnish flags, alias list, recipe count, copy-
to-clipboard slug. Esc, click on empty canvas, or hitting Search Enter
on a different node re-focuses.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 15: Manual smoke + lint + final tidy

**Files:** none changed unless something turns up.

- [ ] **Step 1: Run the full test suite**

```bash
cd web && npm test
```

Expected: all green.

- [ ] **Step 2: Run lint**

```bash
cd web && npm run lint
```

Expected: clean, or fix any warnings the new code introduces.

- [ ] **Step 3: Build**

```bash
cd web && npm run build
```

Expected: clean compile + bundle.

- [ ] **Step 4: Manual integration walkthrough**

```bash
cd web && npm run dev
```

Check each:

- [ ] Header is visible on every route. Wordmark links to `/`. "Recipes" and "Taxonomy" both navigate.
- [ ] `/taxonomy` shows: dark walnut field, four gold corner brackets, title cartouche, force-directed graph of ~166 nodes, gold curved edges, dashed rings on orphans.
- [ ] Hover any node: tooltip card appears upper-right.
- [ ] Click a node: centers, parents above, children below, others dim, sidebar slides in.
- [ ] Esc: layout returns to global.
- [ ] Click empty canvas while focused: layout returns.
- [ ] Type "rye": non-matches dim. Hit Enter: focuses top match.
- [ ] Toggle "orphan" chip: only orphans visible.
- [ ] Toggle "cluster": only cluster nodes visible.
- [ ] Untoggle all: returns.
- [ ] Zoom buttons (`−`, `+`, `⊡`) all work.
- [ ] Resize the window: canvas resizes.
- [ ] `/recipes/:id` and `/` (RecipeList) still render correctly with the new header above them.

- [ ] **Step 5: If anything is off, fix it inline and commit a follow-up**

Stay scoped — fix only what's broken in the v1 surface. Anything noted as future-out-of-scope (descendant rollup, mobile, edit) stays out of scope.

- [ ] **Step 6: Push the branch and open a PR**

```bash
git push -u origin claude/taxonomy-graph-ui-4e67
gh pr create --base main --title "Add /taxonomy graph UI" --body "$(cat <<'EOF'
Force-directed canvas of the taxonomy DAG with click-to-focus radial
mode, search, role/flag filter chips, hover tooltip, sidebar specimen
card, and Art Deco speakeasy chrome. New `taxonomy_public` view +
grants makes one fetch return everything (~166 nodes, edges, aliases,
direct recipe counts).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-review

- [x] **Spec coverage:** Migration (Task 1), routing & header (Tasks 3, 7), shapeData full coverage (Tasks 4–6), force canvas with QA-signal node draw (Task 9), deco styling (Task 8), search + filters + legend + zoom (Tasks 10–13), specimen card + focus mode (Task 14), manual smoke (Task 15). The "open implementation questions" from the spec resolve as: search has both an always-visible box and an Enter-to-focus shortcut (no Cmd-K hotkey in v1 — added if asked); mobile is deferred and untested; only-dark mode for the taxonomy page (no light variant).
- [x] **Placeholder scan:** No "TBD"/"TODO"/"add error handling here" / "similar to task N" anywhere. All code blocks complete. Manual checks call out the exact thing to look at.
- [x] **Type consistency:** `TaxonomyViewRow` (DB-shaped), `TaxonomyNode` (alias to it for graph use), `TaxonomyLink`, `FilterKey` (re-used in tests + component + page), `ForceCanvasHandle` (forwarded ref). `effectiveRole` returns `TaxonomyRole` and is used everywhere a role color is decided. `radialPositions` takes `{id, x, y}` for focus and `{id}` for neighbors — used unchanged in `Taxonomy.tsx` Step 5.
