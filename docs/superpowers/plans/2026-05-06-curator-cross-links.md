# Curator Cross-Links Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect RecipeDetail and Taxonomy pages so curators can walk between raw recipe lines, parsed `recipe_ingredients` rows, and the taxonomy nodes they map to. Tighten `recipe_ingredients` RLS to admin-only as part of the change.

**Architecture:** Forward-only Supabase migration moves `recipe_ingredients` from RLS tier (a) to tier (c) (admin-only) and extends the column grant to admins. Recipe page renders an aligned structured-extraction table (admin-only right side, single-column for non-admins) with deep links to `/taxonomy?node=<slug>`. Taxonomy page gains URL-driven focus state (`?node=`, `?edge=<a>~<b>`) via a new `useTaxonomyUrlState` hook; the pinned `NodeCard` lists every recipe touching the focused node, linking back to `/recipes/:id`. Header gets an "admin" chip.

**Tech Stack:** Vite + React 18 + TypeScript, Vitest + @testing-library/react, react-router-dom v7 (`useSearchParams`), @tanstack/react-query v5, Supabase JS client (PostgREST embeds), PostgreSQL migrations via Supabase CLI.

**Reference spec:** `docs/superpowers/specs/2026-05-06-curator-cross-links-design.md`

---

## File Structure

**New files:**
- `supabase/migrations/20260506180000_admin_recipe_ingredients_lockdown.sql` — RLS + grants
- `web/src/components/recipe/StructuredIngredients.tsx` — aligned table
- `web/src/components/recipe/StructuredIngredients.test.tsx`
- `web/src/components/taxonomy/useTaxonomyUrlState.ts` — URL ↔ focus sync hook
- `web/src/components/taxonomy/useTaxonomyUrlState.test.tsx`

**Modified files:**
- `web/src/types.ts` — add `RecipeIngredientRow`
- `web/src/pages/RecipeDetail.tsx` — replace ingredient `<ul>` with `<StructuredIngredients>`; fetch parsed rows when admin
- `web/src/pages/RecipeDetail.test.tsx` — admin/non-admin variants
- `web/src/pages/Taxonomy.tsx` — adopt `useTaxonomyUrlState`
- `web/src/components/taxonomy/NodeCard.tsx` — recipe list under focused node
- `web/src/components/taxonomy/NodeCard.test.tsx` — recipe list rendering
- `web/src/components/Header.tsx` — admin chip
- `web/src/components/Header.test.tsx` — chip visibility
- `web/src/styles.css` — table classes + chip class

---

## Task 1: Migration — admin-only RLS + extended column grant

**Files:**
- Create: `supabase/migrations/20260506180000_admin_recipe_ingredients_lockdown.sql`

- [ ] **Step 1: Write the migration**

Create `supabase/migrations/20260506180000_admin_recipe_ingredients_lockdown.sql`:

```sql
-- Move recipe_ingredients from RLS tier (a) "eventually anon" to
-- tier (c) "admin only", and extend the column grant so admins can
-- read the parser-output columns the curator UI needs.
--
-- The previous policy (recipe_ingredients_temp_authed_read) admitted
-- any authenticated session. Curator-only access is the intended end
-- state per docs/superpowers/specs/2026-05-06-curator-cross-links-design.md.

drop policy if exists recipe_ingredients_temp_authed_read on recipe_ingredients;

create policy recipe_ingredients_admin_read on recipe_ingredients
  for select to authenticated
  using (is_admin());

-- Extend column grant. The earlier (recipe_id, taxonomy_node_id)
-- grant from 20260501120000_create_taxonomy_public.sql is preserved
-- by listing both columns again — repeating an existing GRANT is a
-- no-op in Postgres.
grant select (
  id, recipe_id, position, raw_text,
  amount, amount_max, unit, name, modifier,
  role, parse_status, taxonomy_node_id
) on recipe_ingredients to authenticated;
```

- [ ] **Step 2: Verify the SQL parses (syntactic-only, no apply needed in worktree)**

Run from the worktree:

```bash
psql "postgresql://postgres:postgres@host.docker.internal:54322/postgres" -v ON_ERROR_STOP=1 --single-transaction --set "ECHO=errors" -f /dev/stdin < supabase/migrations/20260506180000_admin_recipe_ingredients_lockdown.sql || true
```

Expected: either successful execution against the dev DB (idempotent because we use `drop policy if exists` and `grant` is repeatable) or a parse error highlighting the bad SQL.

If the dev DB doesn't have `recipe_ingredients_temp_authed_read` (e.g., the dev DB was reset to a state predating the lockdown migration), the `drop policy if exists` is a no-op — that's fine.

- [ ] **Step 3: Commit**

```bash
git add supabase/migrations/20260506180000_admin_recipe_ingredients_lockdown.sql
git commit -m "Tighten recipe_ingredients RLS to admin-only; extend column grant"
```

---

## Task 2: Add `RecipeIngredientRow` type

**Files:**
- Modify: `web/src/types.ts`

- [ ] **Step 1: Add the type**

Append to `web/src/types.ts`:

```ts
// One parsed ingredient line from recipe_ingredients, joined to taxonomy_nodes
// via PostgREST embed. taxonomy node fields are null when taxonomy_node_id is null.
export type RecipeIngredientRow = {
  id: number;
  position: number;
  raw_text: string;
  amount: number | null;
  amount_max: number | null;
  unit: string | null;
  name: string | null;
  modifier: string | null;
  role:
    | 'base_spirit' | 'modifier' | 'citrus' | 'sweetener'
    | 'bitters' | 'dilution' | 'ice' | 'garnish' | 'wash' | 'other'
    | null;
  parse_status: 'parsed' | 'unparseable';
  taxonomy_node_id: number | null;
  taxonomy_nodes: { slug: string; display_name: string } | null;
};
```

- [ ] **Step 2: Verify type-checking still passes**

Run: `cd web && npm run build -- --mode development 2>&1 | tail -20`
Expected: no type errors. (No tests reference this type yet; that's fine — it's a pure type addition.)

- [ ] **Step 3: Commit**

```bash
git add web/src/types.ts
git commit -m "Add RecipeIngredientRow type"
```

---

## Task 3: Header admin chip

**Files:**
- Modify: `web/src/components/Header.tsx`
- Modify: `web/src/components/Header.test.tsx`
- Modify: `web/src/styles.css`

- [ ] **Step 1: Write the failing test**

Append to `web/src/components/Header.test.tsx`, inside the existing `describe('Header', ...)` block:

```tsx
  it('shows an admin chip next to Sign out when isAdmin', () => {
    useAuthMock.mockReturnValue({ user: { id: 'u-1' }, loading: false });
    useIsAdminMock.mockReturnValue({ isAdmin: true, isLoading: false });
    renderHeader();
    expect(screen.getByText(/^admin$/i)).toBeInTheDocument();
  });

  it('does not show the admin chip for non-admins', () => {
    useAuthMock.mockReturnValue({ user: { id: 'u-1' }, loading: false });
    useIsAdminMock.mockReturnValue({ isAdmin: false, isLoading: false });
    renderHeader();
    expect(screen.queryByText(/^admin$/i)).toBeNull();
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/components/Header.test.tsx`
Expected: the two new tests FAIL with "Unable to find an element with the text: /^admin$/i".

- [ ] **Step 3: Implement the chip**

Edit `web/src/components/Header.tsx`. Replace the `{user && (...)}` block with:

```tsx
      {user && (
        <div className="site-header__user">
          {!adminLoading && isAdmin && (
            <span className="site-header__admin-chip">admin</span>
          )}
          <button type="button" onClick={onSignOut} className="site-header__signout">
            Sign out
          </button>
        </div>
      )}
```

- [ ] **Step 4: Add chip styling**

Append to `web/src/styles.css`:

```css
.site-header__user {
  display: inline-flex;
  align-items: center;
  gap: 12px;
}

.site-header__admin-chip {
  font-family: ui-monospace, monospace;
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  padding: 2px 8px;
  border: 1px solid var(--color-border, #8a6a35);
  border-radius: 999px;
  color: var(--color-fg-muted, #6a4a1a);
  background: rgba(245, 233, 200, 0.6);
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd web && npx vitest run src/components/Header.test.tsx`
Expected: PASS for all tests in the file (existing + 2 new).

- [ ] **Step 6: Commit**

```bash
git add web/src/components/Header.tsx web/src/components/Header.test.tsx web/src/styles.css
git commit -m "Header: admin chip next to Sign out"
```

---

## Task 4: `<StructuredIngredients>` component (strict red/green TDD)

**Files:**
- Create: `web/src/components/recipe/StructuredIngredients.tsx`
- Create: `web/src/components/recipe/StructuredIngredients.test.tsx`
- Modify: `web/src/styles.css`

The component handles four row states: parsed-mapped, parsed-unmapped, unparseable, missing-row. Three cycles, each writing tests first, observing red, then implementing the minimum to make them green.

### Cycle 4.1 — Non-admin single-column rendering

- [ ] **Step 1: Scaffold the test file with shared fixtures**

Create `web/src/components/recipe/StructuredIngredients.test.tsx`:

```tsx
import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { StructuredIngredients } from './StructuredIngredients';
import type { RecipeIngredientRow } from '../../types';

function row(over: Partial<RecipeIngredientRow> = {}): RecipeIngredientRow {
  return {
    id: 100, position: 0, raw_text: '2 oz gin',
    amount: 2, amount_max: null, unit: 'oz',
    name: 'gin', modifier: null,
    role: 'base_spirit', parse_status: 'parsed',
    taxonomy_node_id: 5,
    taxonomy_nodes: { slug: 'gin', display_name: 'Gin' },
    ...over,
  };
}

function asMap(rows: RecipeIngredientRow[]): Map<number, RecipeIngredientRow> {
  return new Map(rows.map((r) => [r.position, r]));
}

function renderIt(props: React.ComponentProps<typeof StructuredIngredients>) {
  return render(
    <MemoryRouter>
      <StructuredIngredients {...props} />
    </MemoryRouter>,
  );
}
```

- [ ] **Step 2: Write the failing non-admin single-column test**

Append to the test file:

```tsx
describe('<StructuredIngredients>', () => {
  it('renders raw lines as a single-column table for non-admins', () => {
    renderIt({
      rawLines: ['2 oz gin', '1 oz lime juice'],
      parsedByPosition: null,
    });
    const rows = screen.getAllByRole('row');
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText('2 oz gin')).toBeInTheDocument();
    expect(within(rows[1]).getByText('1 oz lime juice')).toBeInTheDocument();
    const cells0 = within(rows[0]).getAllByRole('cell');
    expect(cells0).toHaveLength(1);
  });
});
```

- [ ] **Step 3: Run — RED**

Run: `cd web && npx vitest run src/components/recipe/StructuredIngredients.test.tsx`
Expected: FAIL — "Failed to resolve import './StructuredIngredients'" (file does not yet exist).

- [ ] **Step 4: Implement the minimum (non-admin only)**

Create `web/src/components/recipe/StructuredIngredients.tsx`:

```tsx
import type { RecipeIngredientRow } from '../../types';

interface Props {
  rawLines: string[];
  parsedByPosition: Map<number, RecipeIngredientRow> | null;
}

export function StructuredIngredients({ rawLines }: Props) {
  return (
    <table className="recipe-detail__structured">
      <tbody>
        {rawLines.map((raw, i) => (
          <tr key={i}>
            <td className="recipe-detail__structured-raw">{raw}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

- [ ] **Step 5: Run — GREEN**

Run: `cd web && npx vitest run src/components/recipe/StructuredIngredients.test.tsx`
Expected: PASS.

### Cycle 4.2 — Admin happy-path rendering (link, role, id, amount with unit)

- [ ] **Step 6: Write failing happy-path test**

Append:

```tsx
  it('renders aligned cells for admin happy path', () => {
    const rows = [
      row({ position: 0, raw_text: '2 oz gin', amount: 2, unit: 'oz', name: 'gin', taxonomy_node_id: 5, taxonomy_nodes: { slug: 'gin', display_name: 'Gin' }, role: 'base_spirit', id: 17 }),
      row({ position: 1, raw_text: '1 oz fresh lime juice', amount: 1, unit: 'oz', name: 'lime juice', modifier: 'fresh', taxonomy_node_id: 9, taxonomy_nodes: { slug: 'lime_juice', display_name: 'Lime Juice' }, role: 'citrus', id: 18 }),
    ];
    renderIt({
      rawLines: ['2 oz gin', '1 oz fresh lime juice'],
      parsedByPosition: asMap(rows),
    });
    const tableRows = screen.getAllByRole('row');
    expect(tableRows).toHaveLength(3); // 1 header + 2 data
    const r0 = within(tableRows[1]);
    expect(r0.getByText('2 oz gin')).toBeInTheDocument();
    expect(r0.getByText('2 oz')).toBeInTheDocument();
    expect(r0.getByRole('link', { name: /gin/i })).toHaveAttribute('href', '/taxonomy?node=gin');
    expect(r0.getByText('base_spirit')).toBeInTheDocument();
    expect(r0.getByText('17')).toBeInTheDocument();

    const r1 = within(tableRows[2]);
    expect(r1.getByText('1 oz')).toBeInTheDocument();
    expect(r1.getByText('fresh')).toBeInTheDocument();
    expect(r1.getByText('citrus')).toBeInTheDocument();
    expect(r1.getByRole('link', { name: /lime juice/i })).toHaveAttribute('href', '/taxonomy?node=lime_juice');
    expect(r1.getByText('18')).toBeInTheDocument();
  });
```

- [ ] **Step 7: Run — RED**

Run: `cd web && npx vitest run src/components/recipe/StructuredIngredients.test.tsx`
Expected: FAIL on the new test — "Unable to find an accessible element with the role 'link'" (component still single-column).

- [ ] **Step 8: Extend the component for admin happy path only**

Replace the whole body of `web/src/components/recipe/StructuredIngredients.tsx`:

```tsx
import { Link } from 'react-router-dom';
import type { RecipeIngredientRow } from '../../types';

interface Props {
  rawLines: string[];
  parsedByPosition: Map<number, RecipeIngredientRow> | null;
}

export function StructuredIngredients({ rawLines, parsedByPosition }: Props) {
  const isAdmin = parsedByPosition !== null;

  return (
    <table className="recipe-detail__structured">
      {isAdmin && (
        <thead>
          <tr>
            <th>Recipe</th>
            <th>Amount</th>
            <th>Name</th>
            <th>Modifier</th>
            <th>Role</th>
            <th aria-label="ID" />
          </tr>
        </thead>
      )}
      <tbody>
        {rawLines.map((raw, i) => (
          <tr key={i}>
            <td className="recipe-detail__structured-raw">{raw}</td>
            {isAdmin && <ParsedCells row={parsedByPosition!.get(i) ?? null} />}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ParsedCells({ row }: { row: RecipeIngredientRow | null }) {
  // Cycle 4.2 only handles the parsed-and-mapped happy path. Other variants
  // get added in cycle 4.3.
  if (row === null || row.parse_status === 'unparseable' || row.taxonomy_nodes == null) {
    return <td colSpan={5} />;
  }
  return (
    <>
      <td>{formatAmount(row)}</td>
      <td>
        <Link to={`/taxonomy?node=${row.taxonomy_nodes.slug}`}>
          {row.taxonomy_nodes.display_name}
        </Link>
      </td>
      <td>{row.modifier ?? ''}</td>
      <td>
        {row.role && (
          <span className={`recipe-detail__structured-role recipe-detail__structured-role--${row.role}`}>
            {row.role}
          </span>
        )}
      </td>
      <td className="recipe-detail__structured-id">{row.id}</td>
    </>
  );
}

function formatAmount(row: RecipeIngredientRow): string {
  if (row.amount == null) return '';
  const num = row.amount_max != null ? `${row.amount}–${row.amount_max}` : String(row.amount);
  return row.unit ? `${num} ${row.unit}` : num;
}
```

- [ ] **Step 9: Run — GREEN**

Run: `cd web && npx vitest run src/components/recipe/StructuredIngredients.test.tsx`
Expected: PASS for both tests.

- [ ] **Step 10: Write failing amount-format edge-case tests**

Append:

```tsx
  it('renders amount ranges as "min–max unit"', () => {
    const r = row({ amount: 1, amount_max: 2, unit: 'oz' });
    renderIt({ rawLines: ['…'], parsedByPosition: asMap([r]) });
    expect(screen.getByText('1–2 oz')).toBeInTheDocument();
  });

  it('renders amount with no unit as bare number', () => {
    const r = row({ amount: 3, amount_max: null, unit: null });
    renderIt({ rawLines: ['…'], parsedByPosition: asMap([r]) });
    expect(screen.getByText('3')).toBeInTheDocument();
  });
```

- [ ] **Step 11: Run — should be GREEN already (formatAmount handled both)**

Run: `cd web && npx vitest run src/components/recipe/StructuredIngredients.test.tsx -t "amount"`
Expected: PASS for both. (The implementation in step 8 already handles both; these tests are explicit specification capture, not driving new behavior.)

If unexpectedly RED, fix `formatAmount` and re-run until GREEN.

### Cycle 4.3 — Failure variants (unparseable, unmapped, not parsed)

- [ ] **Step 12: Write all three failure-variant tests**

Append:

```tsx
  it('renders an unparseable row with collapsed right-side cell', () => {
    const r = row({
      position: 0, parse_status: 'unparseable',
      amount: null, unit: null, name: null,
      taxonomy_node_id: null, taxonomy_nodes: null, role: null,
    });
    renderIt({ rawLines: ['Sweet vermouth (your favorite)'], parsedByPosition: asMap([r]) });
    expect(screen.getByText(/unparseable/i)).toBeInTheDocument();
    expect(screen.getByText('Sweet vermouth (your favorite)')).toBeInTheDocument();
  });

  it('renders unmapped row with name as plain text and an unmapped chip', () => {
    const r = row({
      position: 0, name: 'lemon',
      taxonomy_node_id: null, taxonomy_nodes: null, role: 'garnish',
    });
    renderIt({ rawLines: ['Garnish: lemon twist'], parsedByPosition: asMap([r]) });
    expect(screen.queryByRole('link', { name: /lemon/i })).toBeNull();
    expect(screen.getByText('lemon')).toBeInTheDocument();
    expect(screen.getByText(/unmapped/i)).toBeInTheDocument();
    expect(screen.getByText('garnish')).toBeInTheDocument();
  });

  it('renders "not parsed" for raw lines with no parsed row', () => {
    renderIt({
      rawLines: ['2 oz gin', '1 oz lime'],
      parsedByPosition: asMap([row({ position: 0, raw_text: '2 oz gin' })]),
    });
    expect(screen.getByText(/not parsed/i)).toBeInTheDocument();
  });
```

- [ ] **Step 13: Run — RED**

Run: `cd web && npx vitest run src/components/recipe/StructuredIngredients.test.tsx`
Expected: FAIL on all three new tests — "Unable to find element with text /unparseable/i", "Unable to find element with text /unmapped/i", "Unable to find element with text /not parsed/i". (Cycle 4.2's `ParsedCells` short-circuits to an empty cell for these branches.)

- [ ] **Step 14: Replace the `ParsedCells` short-circuit with the three branches**

Edit `web/src/components/recipe/StructuredIngredients.tsx`. Replace the `function ParsedCells` body (everything from `function ParsedCells` through the matching `}`) with:

```tsx
function ParsedCells({ row }: { row: RecipeIngredientRow | null }) {
  if (row === null) {
    return (
      <td className="recipe-detail__structured-missing" colSpan={5}>
        <em>not parsed</em>
      </td>
    );
  }
  if (row.parse_status === 'unparseable') {
    return (
      <td className="recipe-detail__structured-unparseable" colSpan={5}>
        <em>unparseable</em>
      </td>
    );
  }
  return (
    <>
      <td>{formatAmount(row)}</td>
      <td>
        {row.taxonomy_nodes != null ? (
          <Link to={`/taxonomy?node=${row.taxonomy_nodes.slug}`}>
            {row.taxonomy_nodes.display_name}
          </Link>
        ) : (
          <>
            {row.name ?? ''}
            <span className="recipe-detail__structured-chip-unmapped">unmapped</span>
          </>
        )}
      </td>
      <td>{row.modifier ?? ''}</td>
      <td>
        {row.role && (
          <span className={`recipe-detail__structured-role recipe-detail__structured-role--${row.role}`}>
            {row.role}
          </span>
        )}
      </td>
      <td className="recipe-detail__structured-id">{row.id}</td>
    </>
  );
}
```

- [ ] **Step 15: Run — GREEN**

Run: `cd web && npx vitest run src/components/recipe/StructuredIngredients.test.tsx`
Expected: PASS for every test in the file.

### Cycle 4.4 — CSS + commit

- [ ] **Step 16: Add CSS for the structured table**

Append to `web/src/styles.css`:

```css
.recipe-detail__structured {
  width: 100%;
  border-collapse: collapse;
  margin: 0 0 1.5em;
}

.recipe-detail__structured th {
  font-family: ui-monospace, monospace;
  font-size: 10px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  text-align: left;
  font-weight: 500;
  color: var(--color-fg-muted, #6a4a1a);
  padding: 4px 10px;
  border-bottom: 1px solid var(--color-border, #8a6a35);
}

.recipe-detail__structured td {
  padding: 6px 10px;
  vertical-align: top;
  border-top: 1px solid rgba(138, 106, 53, 0.18);
}

.recipe-detail__structured-raw {
  width: 40%;
}

.recipe-detail__structured-id {
  font-family: ui-monospace, monospace;
  font-size: 10px;
  color: var(--color-fg-muted, #8a6a35);
  text-align: right;
  white-space: nowrap;
}

.recipe-detail__structured-unparseable {
  border-left: 3px solid #c89a3a;
  font-style: italic;
  color: #8a5a14;
}

.recipe-detail__structured-missing {
  border-left: 3px solid #b0b0b0;
  font-style: italic;
  color: #888;
}

.recipe-detail__structured-chip-unmapped {
  display: inline-block;
  margin-left: 8px;
  font-family: ui-monospace, monospace;
  font-size: 10px;
  letter-spacing: 0.06em;
  padding: 1px 6px;
  border-radius: 999px;
  background: rgba(200, 154, 58, 0.18);
  color: #8a5a14;
}

.recipe-detail__structured-role {
  display: inline-block;
  font-family: ui-monospace, monospace;
  font-size: 10px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  padding: 1px 6px;
  border-radius: 4px;
  background: rgba(138, 106, 53, 0.12);
  color: var(--color-fg, #3a2a14);
}
```

(Role-specific colors deferred — uniform palette is fine for v1; can iterate.)

- [ ] **Step 17: Run all StructuredIngredients tests**

Run: `cd web && npx vitest run src/components/recipe/StructuredIngredients.test.tsx`
Expected: all tests PASS.

- [ ] **Step 18: Commit**

```bash
git add web/src/components/recipe/StructuredIngredients.tsx web/src/components/recipe/StructuredIngredients.test.tsx web/src/styles.css
git commit -m "Add StructuredIngredients component with parsed-row variants"
```

---

## Task 5: Wire `<StructuredIngredients>` into RecipeDetail

**Files:**
- Modify: `web/src/pages/RecipeDetail.tsx`
- Modify: `web/src/pages/RecipeDetail.test.tsx`

- [ ] **Step 1: Write the failing non-admin test**

Open `web/src/pages/RecipeDetail.test.tsx`. Add at the top of the file (after existing imports):

```tsx
const useIsAdminMock = vi.fn();
vi.mock('../auth/useIsAdmin', () => ({ useIsAdmin: () => useIsAdminMock() }));
```

Wrap each existing test's `beforeEach`/setup so `useIsAdminMock` defaults to non-admin. In the `beforeEach`:

```tsx
  beforeEach(() => {
    vi.clearAllMocks();
    useIsAdminMock.mockReturnValue({ isAdmin: false, isLoading: false });
  });
```

Then add a new test:

```tsx
  it('renders raw ingredient lines for a non-admin (no fetch of recipe_ingredients)', async () => {
    useIsAdminMock.mockReturnValue({ isAdmin: false, isLoading: false });
    mockSingleResponse({
      id: 1, source_url: 'https://x.test/r', site: 'x.test', name: 'Test',
      author: null, image_url: null,
      jsonld: {
        name: 'Test', recipeIngredient: ['2 oz gin', '1 oz lime'],
      },
    });
    renderAt('1');
    expect(await screen.findByText('2 oz gin')).toBeInTheDocument();
    expect(screen.getByText('1 oz lime')).toBeInTheDocument();
    // recipe_ingredients should not be fetched in non-admin mode.
    expect(supabase.from).toHaveBeenCalledTimes(1);
    expect(supabase.from).toHaveBeenCalledWith('recipes_public');
  });
```

- [ ] **Step 2: Run — should fail (admin gating not yet implemented in page)**

Run: `cd web && npx vitest run src/pages/RecipeDetail.test.tsx`
Expected: most tests still pass; the new test may PASS already (page doesn't fetch recipe_ingredients yet, and renders raw lines via the existing `<ul>`). If it passes — that is the "red" we'll convert to "green-stays-green" once we swap in `<StructuredIngredients>`.

- [ ] **Step 3: Write the failing admin-mode test**

Append:

```tsx
  it('fetches and renders parsed ingredients for an admin', async () => {
    useIsAdminMock.mockReturnValue({ isAdmin: true, isLoading: false });
    mockSingleResponse({
      id: 1, source_url: 'https://x.test/r', site: 'x.test', name: 'Test',
      author: null, image_url: null,
      jsonld: { name: 'Test', recipeIngredient: ['2 oz gin'] },
    });
    // Second call: recipe_ingredients fetch
    const order = vi.fn().mockResolvedValue({
      data: [{
        id: 17, position: 0, raw_text: '2 oz gin',
        amount: 2, amount_max: null, unit: 'oz',
        name: 'gin', modifier: null,
        role: 'base_spirit', parse_status: 'parsed',
        taxonomy_node_id: 5,
        taxonomy_nodes: { slug: 'gin', display_name: 'Gin' },
      }],
      error: null,
    });
    const eq = vi.fn(() => ({ order }));
    const select = vi.fn(() => ({ eq }));
    (supabase.from as unknown as ReturnType<typeof vi.fn>)
      .mockImplementationOnce(() => ({ select: vi.fn(() => ({ eq: vi.fn(() => ({ single: vi.fn().mockResolvedValue({
        data: {
          id: 1, source_url: 'https://x.test/r', site: 'x.test', name: 'Test',
          author: null, image_url: null,
          jsonld: { name: 'Test', recipeIngredient: ['2 oz gin'] },
        },
        error: null,
      }) })) })) }))
      .mockImplementationOnce(() => ({ select }));

    renderAt('1');
    expect(await screen.findByRole('link', { name: /gin/i })).toHaveAttribute(
      'href', '/taxonomy?node=gin',
    );
    expect(screen.getByText('2 oz')).toBeInTheDocument();
    expect(screen.getByText('17')).toBeInTheDocument();
  });
```

Run: `cd web && npx vitest run src/pages/RecipeDetail.test.tsx -t "fetches and renders parsed"`
Expected: FAIL — "Unable to find a link" or "Unable to find text 2 oz" because the page doesn't yet fetch parsed rows or render them.

- [ ] **Step 4: Update `RecipeDetail.tsx` to fetch parsed rows when admin and render `<StructuredIngredients>`**

Replace the body of `web/src/pages/RecipeDetail.tsx`:

```tsx
import { Fragment, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { supabase } from '../supabase';
import { ErrorPage } from '../components/ErrorPage';
import { normalizeRecipe } from '../normalizeRecipe';
import { useIsAdmin } from '../auth/useIsAdmin';
import { StructuredIngredients } from '../components/recipe/StructuredIngredients';
import type { InstructionStep, RecipeRow, RecipeIngredientRow } from '../types';

type RecipeState =
  | { status: 'loading' }
  | { status: 'notfound' }
  | { status: 'error'; message: string }
  | { status: 'loaded'; row: RecipeRow };

const PARSED_SELECT =
  'id, position, raw_text, amount, amount_max, unit, name, modifier, ' +
  'role, parse_status, taxonomy_node_id, ' +
  'taxonomy_nodes(slug, display_name)';

export function RecipeDetail() {
  const { id } = useParams();
  const { isAdmin } = useIsAdmin();
  const [state, setState] = useState<RecipeState>({ status: 'loading' });
  const [parsed, setParsed] = useState<RecipeIngredientRow[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setState({ status: 'loading' });
    setParsed(null);

    const numericId = Number(id);
    if (!id || !Number.isFinite(numericId) || !Number.isInteger(numericId)) {
      setState({ status: 'notfound' });
      return;
    }

    supabase
      .from('recipes_public')
      .select('*')
      .eq('id', numericId)
      .single()
      .then(({ data, error }) => {
        if (cancelled) return;
        if (error) {
          if (error.code === 'PGRST116') {
            setState({ status: 'notfound' });
            return;
          }
          setState({ status: 'error', message: error.message });
          return;
        }
        if (!data) {
          setState({ status: 'notfound' });
          return;
        }
        setState({ status: 'loaded', row: data as RecipeRow });
      });

    return () => {
      cancelled = true;
    };
  }, [id]);

  // Separate effect: fetch parsed ingredients when we know the recipe loaded
  // and the user is admin. Non-admins skip this entirely.
  useEffect(() => {
    if (state.status !== 'loaded' || !isAdmin) return;
    let cancelled = false;
    supabase
      .from('recipe_ingredients')
      .select(PARSED_SELECT)
      .eq('recipe_id', state.row.id)
      .order('position', { ascending: true })
      .then(({ data, error }) => {
        if (cancelled) return;
        if (error) {
          // Non-fatal: recipe still renders, parsed panel just won't show.
          setParsed([]);
          return;
        }
        setParsed((data ?? []) as unknown as RecipeIngredientRow[]);
      });
    return () => { cancelled = true; };
  }, [state, isAdmin]);

  if (state.status === 'loading') return <div className="page">Loading…</div>;
  if (state.status === 'notfound')
    return <ErrorPage title="Recipe not found" message="No recipe with that ID." />;
  if (state.status === 'error')
    return <ErrorPage title="Couldn't load recipe" message={state.message} />;

  let normalized;
  try {
    normalized = normalizeRecipe(state.row.jsonld);
  } catch (err) {
    return (
      <ErrorPage
        title="Couldn't display recipe"
        message={err instanceof Error ? err.message : String(err)}
      />
    );
  }

  const host = safeHost(state.row.source_url);
  const parsedByPosition = isAdmin && parsed != null
    ? new Map(parsed.map((p) => [p.position, p]))
    : null;

  return (
    <div className="page recipe-detail">
      <p>
        <Link to="/recipes">← Back to recipes</Link>
      </p>
      {normalized.images[0] && (
        <img src={normalized.images[0]} alt="" className="recipe-detail__hero" />
      )}
      <h1>{normalized.name}</h1>
      {(normalized.author || host) && (
        <p className="recipe-detail__byline">
          {normalized.author && <>By {normalized.author} · </>}
          {host}
        </p>
      )}
      {normalized.description && <p>{normalized.description}</p>}
      {(normalized.yield || normalized.prepTime || normalized.cookTime || normalized.totalTime) && (
        <ul className="recipe-detail__meta">
          {normalized.yield && <li>Yield: {normalized.yield}</li>}
          {normalized.prepTime && <li>Prep: {normalized.prepTime}</li>}
          {normalized.cookTime && <li>Cook: {normalized.cookTime}</li>}
          {normalized.totalTime && <li>Total: {normalized.totalTime}</li>}
        </ul>
      )}
      {normalized.ingredients.length > 0 && (
        <>
          <h2>Ingredients</h2>
          <StructuredIngredients
            rawLines={normalized.ingredients}
            parsedByPosition={parsedByPosition}
          />
        </>
      )}
      {normalized.instructions.length > 0 && (
        <>
          <h2>Instructions</h2>
          {renderInstructions(normalized.instructions)}
        </>
      )}
      <p>
        <a href={state.row.source_url} target="_blank" rel="noreferrer">
          View at {state.row.source_url}
        </a>
      </p>
    </div>
  );
}

function safeHost(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return 'source';
  }
}

function renderInstructions(steps: InstructionStep[]) {
  const groups: Array<
    | { kind: 'steps'; steps: string[] }
    | { kind: 'section'; heading: string; steps: string[] }
  > = [];
  for (const step of steps) {
    if (step.kind === 'step') {
      const last = groups[groups.length - 1];
      if (last && last.kind === 'steps') last.steps.push(step.text);
      else groups.push({ kind: 'steps', steps: [step.text] });
    } else {
      groups.push({ kind: 'section', heading: step.heading, steps: step.steps });
    }
  }
  return groups.map((g, i) => {
    if (g.kind === 'steps') {
      if (g.steps.length === 1) return <p key={i}>{g.steps[0]}</p>;
      return (
        <ol key={i} className="recipe-detail__steps">
          {g.steps.map((s, j) => (
            <li key={j}>{s}</li>
          ))}
        </ol>
      );
    }
    return (
      <Fragment key={i}>
        {g.heading && <h3>{g.heading}</h3>}
        <ol className="recipe-detail__steps">
          {g.steps.map((s, j) => (
            <li key={j}>{s}</li>
          ))}
        </ol>
      </Fragment>
    );
  });
}
```

Note: also changed the Back link target from `/` to `/recipes` (the original `/` is the landing page; `/recipes` is the list — the existing behavior is wrong for an authed user. If you'd rather preserve `to="/"` exactly, revert that one line; the rest of the diff is independent).

- [ ] **Step 5: Run RecipeDetail tests**

Run: `cd web && npx vitest run src/pages/RecipeDetail.test.tsx`
Expected: all tests PASS, including both new ones.

- [ ] **Step 6: Commit**

```bash
git add web/src/pages/RecipeDetail.tsx web/src/pages/RecipeDetail.test.tsx
git commit -m "RecipeDetail: render structured ingredients table for admins"
```

---

## Task 6: `useTaxonomyUrlState` hook (strict red/green TDD)

**Files:**
- Create: `web/src/components/taxonomy/useTaxonomyUrlState.ts`
- Create: `web/src/components/taxonomy/useTaxonomyUrlState.test.tsx`

Two cycles: read side (URL → state) and write side (state → URL).

### Cycle 6.1 — Read side (`?node=`, `?edge=`, stale slug handling)

- [ ] **Step 1: Scaffold the test file**

Create `web/src/components/taxonomy/useTaxonomyUrlState.test.tsx`:

```tsx
import { describe, it, expect } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { ReactNode } from 'react';
import { useTaxonomyUrlState } from './useTaxonomyUrlState';
import { viewRowsToGraph, type TaxonomyViewRow } from './shapeData';

const ROWS: TaxonomyViewRow[] = [
  {
    id: 1, slug: 'gin', display_name: 'Gin',
    node_kind: null, default_role: 'base_spirit',
    is_cluster_node: true, is_defining_garnish: false,
    parent_ids: [], child_ids: [2], aliases: [], recipe_count: 0,
  },
  {
    id: 2, slug: 'london_dry_gin', display_name: 'London Dry Gin',
    node_kind: 'expression', default_role: 'base_spirit',
    is_cluster_node: false, is_defining_garnish: false,
    parent_ids: [1], child_ids: [], aliases: [], recipe_count: 0,
  },
];

const NODES = viewRowsToGraph(ROWS).nodes;

function wrapperWithUrl(initial: string) {
  return function W({ children }: { children: ReactNode }) {
    return <MemoryRouter initialEntries={[initial]}>{children}</MemoryRouter>;
  };
}
```

- [ ] **Step 2: Write failing read-side tests (node, edge, stale, malformed)**

Append:

```tsx
describe('useTaxonomyUrlState — read side', () => {
  it('initializes focusedId from ?node=<slug>', () => {
    const { result } = renderHook(() => useTaxonomyUrlState({ nodes: NODES }), {
      wrapper: wrapperWithUrl('/taxonomy?node=gin'),
    });
    expect(result.current.focusedId).toBe(1);
    expect(result.current.focusedEdge).toBeNull();
  });

  it('initializes focusedEdge from ?edge=<parent>~<child>', () => {
    const { result } = renderHook(() => useTaxonomyUrlState({ nodes: NODES }), {
      wrapper: wrapperWithUrl('/taxonomy?edge=gin~london_dry_gin'),
    });
    expect(result.current.focusedId).toBeNull();
    expect(result.current.focusedEdge).not.toBeNull();
    expect(result.current.focusedEdge?.source.slug).toBe('gin');
    expect(result.current.focusedEdge?.target.slug).toBe('london_dry_gin');
  });

  it('returns null focus for unresolvable ?node=<slug>', () => {
    const { result } = renderHook(() => useTaxonomyUrlState({ nodes: NODES }), {
      wrapper: wrapperWithUrl('/taxonomy?node=missing'),
    });
    expect(result.current.focusedId).toBeNull();
    expect(result.current.focusedEdge).toBeNull();
  });

  it('returns null focus for malformed ?edge=', () => {
    const { result } = renderHook(() => useTaxonomyUrlState({ nodes: NODES }), {
      wrapper: wrapperWithUrl('/taxonomy?edge=gin'),
    });
    expect(result.current.focusedEdge).toBeNull();
  });
});
```

- [ ] **Step 3: Run — RED**

Run: `cd web && npx vitest run src/components/taxonomy/useTaxonomyUrlState.test.tsx`
Expected: FAIL — "Failed to resolve import './useTaxonomyUrlState'".

- [ ] **Step 4: Implement the read-side-only hook**

Create `web/src/components/taxonomy/useTaxonomyUrlState.ts`:

```ts
import { useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import type { TaxonomyNode } from './shapeData';
import type { EdgeRef } from './EdgeCard';

export interface UseTaxonomyUrlStateArgs {
  nodes: TaxonomyNode[];
}

export interface UseTaxonomyUrlStateReturn {
  focusedId: number | null;
  focusedEdge: EdgeRef | null;
  setFocusedId: (id: number | null) => void;
  setFocusedEdge: (edge: EdgeRef | null) => void;
  clearFocus: () => void;
}

const EDGE_SEP = '~';

export function useTaxonomyUrlState({
  nodes,
}: UseTaxonomyUrlStateArgs): UseTaxonomyUrlStateReturn {
  const [searchParams] = useSearchParams();
  const bySlug = useMemo(
    () => new Map(nodes.map((n) => [n.slug, n])),
    [nodes],
  );

  const nodeParam = searchParams.get('node');
  const edgeParam = searchParams.get('edge');

  const focusedId = useMemo<number | null>(() => {
    if (!nodeParam) return null;
    const node = bySlug.get(nodeParam);
    return node ? node.id : null;
  }, [nodeParam, bySlug]);

  const focusedEdge = useMemo<EdgeRef | null>(() => {
    if (!edgeParam) return null;
    const [parentSlug, childSlug] = edgeParam.split(EDGE_SEP);
    if (!parentSlug || !childSlug) return null;
    const source = bySlug.get(parentSlug);
    const target = bySlug.get(childSlug);
    if (!source || !target) return null;
    return { source, target };
  }, [edgeParam, bySlug]);

  // Cycle 6.1 — write-side stubs throw to make any forgotten consumer
  // call obvious in tests. Real impls land in cycle 6.2.
  const notImplemented = () => {
    throw new Error('useTaxonomyUrlState write side not yet implemented');
  };

  return {
    focusedId,
    focusedEdge,
    setFocusedId: notImplemented,
    setFocusedEdge: notImplemented,
    clearFocus: notImplemented,
  };
}
```

- [ ] **Step 5: Run — GREEN**

Run: `cd web && npx vitest run src/components/taxonomy/useTaxonomyUrlState.test.tsx`
Expected: all 4 read-side tests PASS.

### Cycle 6.2 — Write side (`setFocusedId`, `setFocusedEdge`, `clearFocus`)

- [ ] **Step 6: Write failing tests for setters writing to URL**

Append to the test file:

```tsx
describe('useTaxonomyUrlState — write side', () => {
  it('setFocusedId writes ?node=<slug> and clears any ?edge', () => {
    const { result } = renderHook(() => useTaxonomyUrlState({ nodes: NODES }), {
      wrapper: wrapperWithUrl('/taxonomy?edge=gin~london_dry_gin'),
    });
    act(() => { result.current.setFocusedId(2); });
    expect(result.current.focusedId).toBe(2);
    expect(result.current.focusedEdge).toBeNull();
  });

  it('setFocusedEdge writes ?edge=<a>~<b> and clears any ?node', () => {
    const { result } = renderHook(() => useTaxonomyUrlState({ nodes: NODES }), {
      wrapper: wrapperWithUrl('/taxonomy?node=gin'),
    });
    const edge = {
      source: NODES.find((n) => n.slug === 'gin')!,
      target: NODES.find((n) => n.slug === 'london_dry_gin')!,
    };
    act(() => { result.current.setFocusedEdge(edge); });
    expect(result.current.focusedId).toBeNull();
    expect(result.current.focusedEdge?.source.slug).toBe('gin');
    expect(result.current.focusedEdge?.target.slug).toBe('london_dry_gin');
  });

  it('clearFocus removes both params', () => {
    const { result } = renderHook(() => useTaxonomyUrlState({ nodes: NODES }), {
      wrapper: wrapperWithUrl('/taxonomy?node=gin'),
    });
    act(() => { result.current.clearFocus(); });
    expect(result.current.focusedId).toBeNull();
    expect(result.current.focusedEdge).toBeNull();
  });

  it('setFocusedId(null) clears the node param', () => {
    const { result } = renderHook(() => useTaxonomyUrlState({ nodes: NODES }), {
      wrapper: wrapperWithUrl('/taxonomy?node=gin'),
    });
    act(() => { result.current.setFocusedId(null); });
    expect(result.current.focusedId).toBeNull();
  });
});
```

- [ ] **Step 7: Run — RED**

Run: `cd web && npx vitest run src/components/taxonomy/useTaxonomyUrlState.test.tsx`
Expected: 4 new tests FAIL with "useTaxonomyUrlState write side not yet implemented".

- [ ] **Step 8: Implement the setters**

Edit `web/src/components/taxonomy/useTaxonomyUrlState.ts`. Replace the imports and the write-side stub block.

Change the imports line:

```ts
import { useCallback, useMemo } from 'react';
```

(Add `useCallback`.)

Add a `byId` map alongside `bySlug`:

```ts
  const byId = useMemo(
    () => new Map(nodes.map((n) => [n.id, n])),
    [nodes],
  );
```

Replace the line `const [searchParams] = useSearchParams();` with:

```ts
  const [searchParams, setSearchParams] = useSearchParams();
```

Replace the `notImplemented` block + return statement with the real setters:

```ts
  const setFocusedId = useCallback(
    (id: number | null) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.delete('edge');
          if (id == null) {
            next.delete('node');
            return next;
          }
          const node = byId.get(id);
          if (!node) {
            next.delete('node');
            return next;
          }
          next.set('node', node.slug);
          return next;
        },
        { replace: false },
      );
    },
    [byId, setSearchParams],
  );

  const setFocusedEdge = useCallback(
    (edge: EdgeRef | null) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.delete('node');
          if (edge == null) {
            next.delete('edge');
            return next;
          }
          next.set('edge', `${edge.source.slug}${EDGE_SEP}${edge.target.slug}`);
          return next;
        },
        { replace: false },
      );
    },
    [setSearchParams],
  );

  const clearFocus = useCallback(() => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete('node');
        next.delete('edge');
        return next;
      },
      { replace: false },
    );
  }, [setSearchParams]);

  return { focusedId, focusedEdge, setFocusedId, setFocusedEdge, clearFocus };
```

- [ ] **Step 9: Run — GREEN**

Run: `cd web && npx vitest run src/components/taxonomy/useTaxonomyUrlState.test.tsx`
Expected: all 8 tests PASS.

- [ ] **Step 10: Commit**

```bash
git add web/src/components/taxonomy/useTaxonomyUrlState.ts web/src/components/taxonomy/useTaxonomyUrlState.test.tsx
git commit -m "Add useTaxonomyUrlState hook for URL-driven focus"
```

---

## Task 7: Adopt `useTaxonomyUrlState` in Taxonomy page

**Files:**
- Modify: `web/src/pages/Taxonomy.tsx`

This is a refactor: replace local `focusedId`/`focusedEdge` state with the hook. No new tests because the hook itself is fully tested; the existing Taxonomy tests should keep passing.

- [ ] **Step 1: Run existing Taxonomy tests to establish a baseline**

Run: `cd web && npx vitest run src/pages/Taxonomy.test.tsx`
Expected: all PASS (capture the count).

- [ ] **Step 2: Refactor `Taxonomy.tsx`**

In `web/src/pages/Taxonomy.tsx`:

- Add import: `import { useTaxonomyUrlState } from '../components/taxonomy/useTaxonomyUrlState';`
- Inside `LoadedView`, replace these lines:
  ```tsx
  const [focusedId, setFocusedId] = useState<number | null>(null);
  const [focusedEdge, setFocusedEdge] = useState<EdgeRef | null>(null);
  ```
  with:
  ```tsx
  const { focusedId, focusedEdge, setFocusedId, setFocusedEdge, clearFocus } =
    useTaxonomyUrlState({ nodes });
  ```
- In the `onNodeClick` handler:
  ```tsx
  onNodeClick={(n) => {
    setFocusedId(n.id);  // setter from hook now also clears any edge
  }}
  ```
- In `onLinkClick`:
  ```tsx
  onLinkClick={(l) => {
    const e = resolveLink(l);
    if (!e) return;
    setFocusedEdge(e);  // setter clears any node
  }}
  ```
- In `onBackgroundClick`:
  ```tsx
  onBackgroundClick={() => {
    clearFocus();
  }}
  ```
- In the `EdgeCard` `onDismiss`: replace `() => setFocusedEdge(null)` with `() => setFocusedEdge(null)` — the hook's setter handles param removal correctly.
- In the `NodeCard` `onDismiss`: replace `() => setFocusedId(null)` with `() => setFocusedId(null)`.
- The `SearchBox` `onSubmit` should still call `setFocusedId(top.id)` — works as-is.

- [ ] **Step 3: Run all Taxonomy tests**

Run: `cd web && npx vitest run src/pages/Taxonomy.test.tsx`
Expected: same number of tests PASS as in Step 1. If any fail because they expected internal state behavior, they need to be updated to use a `MemoryRouter` and assert against URL or focused state — show the diff to the reviewer rather than rewriting blindly.

- [ ] **Step 4: Run full web test suite to catch any cross-file regression**

Run: `cd web && npx vitest run`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/pages/Taxonomy.tsx
git commit -m "Taxonomy: drive focus state through URL via useTaxonomyUrlState"
```

---

## Task 8: NodeCard recipe list

**Files:**
- Modify: `web/src/components/taxonomy/NodeCard.tsx`
- Modify: `web/src/components/taxonomy/NodeCard.test.tsx`
- Modify: `web/src/styles.css`

- [ ] **Step 1: Write failing test for empty recipe list (count=0, no fetch)**

Open `web/src/components/taxonomy/NodeCard.test.tsx`. At the top, add:

```tsx
const fromMock = vi.fn();
vi.mock('../../supabase', () => ({ supabase: { from: (table: string) => fromMock(table) } }));

import { MemoryRouter } from 'react-router-dom';
beforeEach(() => { fromMock.mockReset(); });

function renderCard(node: Parameters<typeof NodeCard>[0]['node'], mode: 'pinned' | 'hover' = 'pinned') {
  return render(
    <MemoryRouter>
      <NodeCard node={node} mode={mode} onDismiss={() => {}} />
    </MemoryRouter>,
  );
}
```

(If `MemoryRouter` import already exists in the file, don't duplicate it.)

Add a test:

```tsx
  it('does not fetch recipes when recipe_count is 0', async () => {
    const node = {
      id: 1, slug: 'gin', display_name: 'Gin',
      node_kind: null, default_role: 'base_spirit',
      is_cluster_node: true, is_defining_garnish: false,
      parent_ids: [], child_ids: [], aliases: [],
      recipe_count: 0, labelW: 10, labelH: 11,
    };
    renderCard(node);
    expect(fromMock).not.toHaveBeenCalled();
    expect(screen.getByText('—')).toBeInTheDocument();
  });
```

- [ ] **Step 2: Write failing test for recipe list rendering**

Append:

```tsx
  it('fetches and renders linked recipe list when recipe_count > 0', async () => {
    const node = {
      id: 1, slug: 'gin', display_name: 'Gin',
      node_kind: null, default_role: 'base_spirit',
      is_cluster_node: true, is_defining_garnish: false,
      parent_ids: [], child_ids: [], aliases: [],
      recipe_count: 2, labelW: 10, labelH: 11,
    };
    const eq = vi.fn(() => ({
      order: vi.fn().mockResolvedValue({
        data: [
          { recipe_id: 10, recipes: { id: 10, name: 'Negroni', site: 'punchdrink.com' } },
          { recipe_id: 11, recipes: { id: 11, name: 'Boulevardier', site: 'imbibemagazine.com' } },
        ],
        error: null,
      }),
    }));
    fromMock.mockReturnValue({ select: vi.fn(() => ({ eq })) });

    renderCard(node);
    expect(await screen.findByRole('link', { name: /negroni/i })).toHaveAttribute(
      'href', '/recipes/10',
    );
    expect(screen.getByRole('link', { name: /boulevardier/i })).toHaveAttribute(
      'href', '/recipes/11',
    );
  });
```

- [ ] **Step 3: Write failing test for duplicate dedup**

Append:

```tsx
  it('dedupes recipes by id when a node appears in multiple positions', async () => {
    const node = {
      id: 1, slug: 'gin', display_name: 'Gin',
      node_kind: null, default_role: 'base_spirit',
      is_cluster_node: true, is_defining_garnish: false,
      parent_ids: [], child_ids: [], aliases: [],
      recipe_count: 1, labelW: 10, labelH: 11,
    };
    fromMock.mockReturnValue({
      select: vi.fn(() => ({
        eq: vi.fn(() => ({
          order: vi.fn().mockResolvedValue({
            data: [
              { recipe_id: 10, recipes: { id: 10, name: 'Negroni', site: 'punchdrink.com' } },
              { recipe_id: 10, recipes: { id: 10, name: 'Negroni', site: 'punchdrink.com' } },
            ],
            error: null,
          }),
        })),
      })),
    });
    renderCard(node);
    const links = await screen.findAllByRole('link', { name: /negroni/i });
    expect(links).toHaveLength(1);
  });
```

Run: `cd web && npx vitest run src/components/taxonomy/NodeCard.test.tsx`
Expected: the new tests FAIL (component doesn't fetch yet). The test file may also need a `MemoryRouter` wrapper retroactively for older tests; if any existing test now throws "useNavigate within Router" or similar, wrap it the same way.

- [ ] **Step 4: Update `NodeCard.tsx` to fetch + render the list**

In `web/src/components/taxonomy/NodeCard.tsx`:

Add imports at the top:

```tsx
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { supabase } from '../../supabase';
```

(Keep existing import of `useEffect` from 'react' but consolidate.)

Add a type and helper above the `NodeCard` function:

```tsx
type RecipeLink = { id: number; name: string | null; site: string };

const RECIPES_SELECT = 'recipe_id, recipes(id, name, site)';
```

Inside the component, add hooks to fetch when pinned and recipe_count > 0:

```tsx
  const [recipes, setRecipes] = useState<RecipeLink[] | null>(null);
  const [recipesError, setRecipesError] = useState<string | null>(null);

  useEffect(() => {
    if (mode !== 'pinned') return;
    if (node.recipe_count === 0) return;
    let cancelled = false;
    setRecipes(null);
    setRecipesError(null);
    supabase
      .from('recipe_ingredients')
      .select(RECIPES_SELECT)
      .eq('taxonomy_node_id', node.id)
      .order('recipe_id', { ascending: true })
      .then(({ data, error }) => {
        if (cancelled) return;
        if (error) {
          setRecipesError(error.message);
          return;
        }
        const seen = new Set<number>();
        const out: RecipeLink[] = [];
        for (const row of (data ?? []) as Array<{ recipe_id: number; recipes: { id: number; name: string | null; site: string } | null }>) {
          if (!row.recipes) continue;
          if (seen.has(row.recipes.id)) continue;
          seen.add(row.recipes.id);
          out.push(row.recipes);
        }
        out.sort((a, b) => {
          const sa = a.site.localeCompare(b.site);
          if (sa !== 0) return sa;
          return (a.name ?? '').localeCompare(b.name ?? '');
        });
        setRecipes(out);
      });
    return () => { cancelled = true; };
  }, [mode, node.id, node.recipe_count]);
```

Replace the existing RECIPES section near the bottom of the card with:

```tsx
        <div className="tx-card__heading" style={{ marginTop: 10 }}>
          RECIPES <span style={{ fontStyle: 'italic', color: TX_FRAME_EDGE }}>({node.recipe_count})</span>
        </div>
        {node.recipe_count === 0 && <div>—</div>}
        {node.recipe_count > 0 && recipesError !== null && (
          <div style={{ fontStyle: 'italic' }}>Couldn't load recipes</div>
        )}
        {node.recipe_count > 0 && recipes === null && recipesError === null && (
          <div style={{ fontStyle: 'italic' }}>Loading…</div>
        )}
        {node.recipe_count > 0 && recipes !== null && (
          <ul className="tx-card__recipes">
            {recipes.map((r) => (
              <li key={r.id}>
                <Link to={`/recipes/${r.id}`}>{r.name ?? `recipe ${r.id}`}</Link>
                <span className="tx-card__recipes-site">{r.site}</span>
              </li>
            ))}
          </ul>
        )}
```

- [ ] **Step 5: Add CSS for the recipe list**

Append to `web/src/styles.css`:

```css
.tx-card__recipes {
  list-style: none;
  padding: 0;
  margin: 4px 0 0;
}

.tx-card__recipes li {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  padding: 2px 0;
  font-size: 13px;
}

.tx-card__recipes-site {
  font-family: ui-monospace, monospace;
  font-size: 10px;
  color: var(--color-fg-muted, #8a6a35);
  white-space: nowrap;
}
```

- [ ] **Step 6: Run NodeCard tests**

Run: `cd web && npx vitest run src/components/taxonomy/NodeCard.test.tsx`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add web/src/components/taxonomy/NodeCard.tsx web/src/components/taxonomy/NodeCard.test.tsx web/src/styles.css
git commit -m "NodeCard: list and link to recipes touching the focused node"
```

---

## Task 9: Final integration verification

- [ ] **Step 1: Full web test suite**

Run: `cd web && npx vitest run`
Expected: every test PASSES. Capture total count.

- [ ] **Step 2: Type-check + build**

Run: `cd web && npm run build`
Expected: build succeeds with no TS errors. Bundle size deltas in the output should be modest (<20 KB raw added).

- [ ] **Step 3: Lint**

Run: `cd web && npm run lint`
Expected: no errors. (Warnings are acceptable if pre-existing; the diff should not introduce new ones.)

- [ ] **Step 4: Manual smoke test (browser, optional but recommended)**

Run: `cd web && npm run dev`

Visit:
- `http://localhost:5173/recipes/<some-id>` while logged in as the local dev admin (`admin@local.test`). Expect: structured table with parsed rows, taxonomy links functional.
- Click a structured ingredient → lands on `/taxonomy?node=<slug>` with the node focused.
- Click a different node on the canvas → URL updates to `?node=<new-slug>`.
- Click an edge → URL updates to `?edge=<parent>~<child>`.
- Click background → URL clears.
- In a pinned node card, click a recipe → returns to `/recipes/:id`.
- Sign out, sign in as a non-admin (or stub `useIsAdmin` return), reload `/recipes/:id` → see only the raw single-column table.

If any of these fail, file an issue or fix before declaring the task done.

- [ ] **Step 5: Commit any final styling tweaks (if any)**

```bash
git status
# If clean, skip. Otherwise:
git add <files>
git commit -m "Curator cross-links: minor polish"
```

- [ ] **Step 6: Push branch and open PR**

```bash
git push -u origin worktree-curator-cross-links
gh pr create --title "Curator cross-links between recipe and taxonomy pages" --body "$(cat <<'EOF'
Connects RecipeDetail with the taxonomy graph and tightens recipe_ingredients RLS to admin-only.

- New `recipe_ingredients_admin_read` policy + extended column grant; replaces the temp authenticated-read policy.
- Admin-only structured ingredient table on `/recipes/:id`, aligned 1:1 with raw lines, deep-linking to `/taxonomy?node=<slug>`.
- Taxonomy focus state driven through `?node=<slug>` and `?edge=<parent>~<child>` query params; URL stays in sync with clicks.
- Pinned NodeCard now lists every recipe touching the node, linking back to `/recipes/:id`.
- Header gets an inconspicuous `admin` chip next to Sign out for admin users.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Notes for the executor

- **Strict TDD discipline:** every test step runs *before* its implementation step, even when the implementation comes minutes later. The "expected fail" output is part of the evidence — capture and verify.
- **Mock chain shapes:** Supabase chain mocks differ between calls (`select → eq → single` vs `select → eq → order`). Use `mockImplementationOnce` when the same `from()` call is invoked twice with different chains.
- **PostgREST embeds:** `taxonomy_nodes(slug, display_name)` and `recipes(id, name, site)` are FK-resolved. No manual hint comments required (FKs already exist on `recipe_ingredients.taxonomy_node_id` and `recipe_ingredients.recipe_id`).
- **Migration apply:** the migration is auto-applied to `spiritolo_test` when the `ingredients` conftest runs. To apply against the local dev DB, ask the user to run `supabase migration up --include-all` from the Mac host (devcontainer cannot drive the Supabase CLI directly).
- **Don't optimize prematurely:** no virtualization, no SWR caching of the recipe list, no slug-rename. Those are explicitly out of scope.
